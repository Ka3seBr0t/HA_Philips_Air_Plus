#!/usr/bin/env python3
"""
shadow_dump.py — Standalone raw shadow/NCP capture for Philips Air+ FUSION devices.

Purpose
-------
Authenticate to the Philips/Versuni cloud exactly the way the Home Assistant
integrations do (email OTP -> Gigya/OIDC -> AWS IoT Custom Authorizer), connect
to the AWS IoT MQTT-over-WSS broker for ONE device (e.g. the CX3550/01 fan), and
write every inbound message to captures/raw_shadow.jsonl with an ISO timestamp.

It captures BOTH channels that matter for Philips Air+ class devices:
  * the AWS IoT device shadow  ($aws/things/<thing>/shadow/...)  -> powerOn etc.
  * the NCP port channel        (da_ctrl/<thing>/from_ncp)        -> the real
    per-feature properties (fan speed, mode, oscillation, timer, sensors...)

Because NCP pushes only carry CHANGED fields, the tool also POLLS getPort on the
device's read ports on a timer, so each step of a manual function sweep yields a
full snapshot that diffs cleanly in Phase 2.

This script re-implements (does not import) the integration auth logic, so it has
no Home Assistant dependency. See ../notes/architecture.md for the source mapping.

Dependencies:  pip install -r requirements.txt   (requests, paho-mqtt>=2.1)

Human-in-the-loop ([MENSCH] steps):
  1. Provide the Philips account email (env PHILIPS_EMAIL or prompt).
  2. Type the 6-digit code emailed to that address (first run only; the refresh
     token is cached to .tokens.json so later runs reconnect without an OTP).
  3. Make sure the device is online in the app, then trigger functions to sweep.

Usage:
  python shadow_dump.py --list-only        # log in, list devices, exit (confirm CTN/online)
  python shadow_dump.py                     # auto-pick device whose CTN matches --ctn
  python shadow_dump.py --ctn CX3550/01
  python shadow_dump.py --thing da-xxxxxxxx # connect to an explicit thingName
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import ssl
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests'. Run: pip install -r requirements.txt")
try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.exit("Missing dependency 'paho-mqtt'. Run: pip install -r requirements.txt")

# --------------------------------------------------------------------------- #
# Constants (from philips_homeid/const.py + philips_airplus/const.py)
# --------------------------------------------------------------------------- #
GIGYA_API_KEY = "4_JGZWlP8eQHpEqkvQElolbA"
GIGYA_API_URL = "https://cdc.accounts.home.id"
OIDC_ISSUER = f"https://cdc.accounts.home.id/oidc/op/v1.0/{GIGYA_API_KEY}"
OIDC_AUTH_ENDPOINT = f"{OIDC_ISSUER}/authorize"
OIDC_TOKEN_ENDPOINT = f"{OIDC_ISSUER}/token"
# App OAuth profiles. SAME Gigya/OIDC endpoints — only client_id/redirect/scopes
# differ. Air+ tokens are accepted by the IoT device-list API (lists fans/
# purifiers); HomeID tokens see the VBS appliance backend (kitchen, e.g. airfryers).
# (philips_airplus/const.py + email_auth.py EmailOTPAuth defaults.)
HOMEID_CLIENT_ID = "-u6aTznrxp9_9e_0a57CpvEG"
HOMEID_REDIRECT_URI = "com.philips.ka.oneka.app.prod://oauthredirect"
HOMEID_SCOPES = (
    "openid profile email offline_access "
    "DI.Account.read DI.AccountProfile.read DI.AccountProfile.write "
    "DI.AccountGeneralConsent.read DI.AccountGeneralConsent.write "
    "DI.GeneralConsent.read DI.GeneralConsent.write "
    "VoiceProvider.read VoiceProvider.write "
    "subscriptions consent profile_extended "
    "DI.AccountSubscription.write DI.AccountSubscription.read"
)
AIRPLUS_CLIENT_ID = "-XsK7O6iEkLml77yDGDUi0ku"
AIRPLUS_REDIRECT_URI = "com.philips.air://loginredirect"
AIRPLUS_SCOPES = (
    "openid email profile address DI.Account.read DI.Account.write "
    "DI.AccountProfile.read DI.AccountProfile.write DI.AccountGeneralConsent.read "
    "DI.AccountGeneralConsent.write DI.GeneralConsent.read subscriptions "
    "profile_extended consents DI.AccountSubscription.read DI.AccountSubscription.write"
)
AUTH_PROFILES = {
    "airplus": (AIRPLUS_CLIENT_ID, AIRPLUS_REDIRECT_URI, AIRPLUS_SCOPES),
    "homeid": (HOMEID_CLIENT_ID, HOMEID_REDIRECT_URI, HOMEID_SCOPES),
}

# EU "DaConnect" region — correct for Germany. Override via env if needed.
PLATFORM_REST_URL = os.environ.get("PHILIPS_PLATFORM_REST_URL", "prod.eu-da.iot.versuni.com")
TENANT = os.environ.get("PHILIPS_TENANT", "da")
MQTT_HOST = os.environ.get("PHILIPS_MQTT_HOST", "ats.prod.eu-da.iot.versuni.com")
MQTT_PORT = 443
MQTT_PATH = "/mqtt"
KEEPALIVE = 30

HOMEID_USER_AGENT = "HomeID/8.16.0 (com.philips.ka.oneka.app; build:8160001; Android 14)"
HOMEID_X_USER_AGENT = "Android 14;8.16.0"

# HomeID backend (APK BackendConfigKt) — the authoritative paired-appliance list
# (what the app shows). Used as a second discovery source + diagnostics.
BACKEND_BASE = "https://www.backend.vbs.versuni.com"
BACKEND_API_BASE = f"{BACKEND_BASE}/api"
HOMEID_ACCEPT = "application/vnd.oneka.v2.0+json"

# Flipped on by --debug to dump raw discovery responses.
DEBUG = False

# Air+ well-known NCP ports (philips_airplus/const.py). We poll these even if
# getAllPorts is unsupported, so capture works for the purifier/fan family.
DEFAULT_READ_PORTS = ["Status", "Config", "filtRd"]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CAPTURES_DIR = os.path.join(PROJECT_DIR, "captures")
TOKENS_FILE = os.path.join(SCRIPT_DIR, ".tokens.json")
ENV_FILE = os.path.join(PROJECT_DIR, ".env")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ncp_time() -> str:
    # APK NcpRequestTime format, no fractional seconds.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_env_file() -> None:
    """Minimal .env loader so python-dotenv isn't required."""
    if not os.path.isfile(ENV_FILE):
        return
    with open(ENV_FILE, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


# --------------------------------------------------------------------------- #
# Cloud auth + REST (mirrors cloud_auth.py / cloud_api.py)
# --------------------------------------------------------------------------- #
class CloudError(Exception):
    pass


class PhilipsCloud:
    def __init__(self, client_id: str = AIRPLUS_CLIENT_ID,
                 redirect_uri: str = AIRPLUS_REDIRECT_URI,
                 scopes: str = AIRPLUS_SCOPES) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": HOMEID_USER_AGENT})
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._scopes = scopes

    # ---- OTP + OIDC ----
    def request_otp(self, email: str) -> str:
        r = self.s.post(
            f"{GIGYA_API_URL}/accounts.auth.otp.email.sendCode",
            data={"email": email, "apiKey": GIGYA_API_KEY, "format": "json"},
            timeout=30,
        )
        data = r.json()
        if data.get("errorCode", -1) != 0:
            raise CloudError(f"OTP send failed: {data.get('errorMessage', data)}")
        vtoken = data.get("vToken")
        if not vtoken:
            raise CloudError("No vToken in OTP response")
        return vtoken

    def verify_otp(self, email: str, code: str, vtoken: str) -> str:
        r = self.s.post(
            f"{GIGYA_API_URL}/accounts.auth.otp.email.login",
            data={"email": email, "code": code, "vToken": vtoken,
                  "apiKey": GIGYA_API_KEY, "format": "json"},
            timeout=30,
        )
        data = r.json()
        if data.get("errorCode", -1) == 206001:
            raise CloudError(
                "Account pending registration: this email is not a fully registered "
                "Philips HomeID account. Sign in once in the Philips app, then retry."
            )
        if data.get("errorCode", -1) != 0:
            raise CloudError(f"OTP verify failed: {data.get('errorMessage', data)}")
        token = data.get("sessionInfo", {}).get("cookieValue")
        if not token:
            raise CloudError("No session token in OTP verify response")
        return token

    def get_oidc_tokens(self, session_token: str) -> dict:
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()

        auth_params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": self._scopes,
            "state": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "none",
        }
        r = self.s.get(
            f"{OIDC_AUTH_ENDPOINT}?{urllib.parse.urlencode(auth_params)}",
            allow_redirects=False, timeout=30,
        )
        if r.status_code not in (301, 302, 303, 307, 308):
            raise CloudError(f"/authorize expected redirect, got {r.status_code}: {r.text[:200]}")
        loc = r.headers.get("Location", "")
        context = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get("context", [""])[0]
        if not context:
            raise CloudError(f"/authorize: no 'context' in redirect ({loc[:160]})")

        ids = self.s.post(
            f"{GIGYA_API_URL}/socialize.getIDs",
            data={"APIKey": GIGYA_API_KEY, "includeTicket": "true", "format": "json"},
            timeout=30,
        ).json()
        gmid = ids.get("gmidTicket")
        if not gmid:
            raise CloudError(f"socialize.getIDs: no gmidTicket ({ids.get('errorMessage')})")

        cont = self.s.get(
            f"{OIDC_ISSUER}/authorize/continue",
            params={"context": context, "login_token": session_token,
                    "gmidTicket": gmid, "client_id": self._client_id},
            allow_redirects=False, timeout=30,
        )
        if cont.status_code not in (301, 302, 303, 307, 308):
            raise CloudError(f"/authorize/continue expected redirect, got {cont.status_code}: {cont.text[:200]}")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(cont.headers.get("Location", "")).query)
        if q.get("errorMessage"):
            raise CloudError(f"/authorize/continue: {q['errorMessage'][0]}")
        code = q.get("code", [""])[0]
        if not code:
            raise CloudError("/authorize/continue: no 'code' in redirect")

        return self._exchange(code, verifier)

    def _exchange(self, code: str, verifier: str) -> dict:
        r = self.s.post(OIDC_TOKEN_ENDPOINT, data={
            "client_id": self._client_id, "grant_type": "authorization_code",
            "code": code, "redirect_uri": self._redirect_uri, "code_verifier": verifier,
        }, timeout=30)
        tok = r.json()
        if "access_token" not in tok:
            raise CloudError(f"Token exchange failed: {tok.get('error_description', tok)}")
        return tok

    def refresh_tokens(self, refresh_token: str) -> dict:
        r = self.s.post(OIDC_TOKEN_ENDPOINT, data={
            "client_id": self._client_id, "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, timeout=30)
        tok = r.json()
        if "access_token" not in tok:
            raise CloudError(f"Token refresh rejected: {tok.get('error_description', tok)}")
        return tok

    # ---- IoT REST ----
    def _iot(self, method: str, path: str, access_token: str, **kw):
        url = f"https://{PLATFORM_REST_URL}/api/{TENANT}{path}"
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        headers.update(kw.pop("headers", {}))
        return self.s.request(method, url, headers=headers, timeout=30, **kw)

    def get_devices(self, access_token: str) -> list:
        r = self._iot("GET", "/user/self/device", access_token)
        if DEBUG:
            print(f"[debug] GET /user/self/device -> HTTP {r.status_code}\n{r.text[:1500]}\n")
        if r.status_code != 200:
            raise CloudError(f"device list HTTP {r.status_code}: {r.text[:200]}")
        return _extract_device_list(r.json())

    def get_mqtt_user_id(self, access_token: str, id_token: str) -> str | None:
        r = self._iot("POST", "/user/self/get-id", access_token,
                      headers={"Content-Type": "application/json"},
                      data=json.dumps({"idToken": id_token}))
        if r.status_code != 200:
            raise CloudError(f"get-id HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("userId")

    def get_mqtt_signature(self, access_token: str) -> str:
        r = self._iot("GET", "/user/self/signature", access_token)
        if r.status_code != 200:
            raise CloudError(f"signature HTTP {r.status_code}: {r.text[:200]}")
        return r.json().get("signature", "")

    def get_appliances_via_homeid(self, access_token: str) -> list:
        """Authoritative paired-appliance list via the HomeID backend (HAL).

        Chain (cloud_api.get_appliances_via_homeid): discovery -> profile ->
        _embedded.userAppliances or _links.userAppliances.
        """
        disc = self.s.get(f"{BACKEND_BASE}/.well-known/tenant/oneka", timeout=30)
        if DEBUG:
            print(f"[debug] discovery HTTP {disc.status_code}: {disc.text[:300]}")
        if disc.status_code != 200:
            return []
        profile_url = disc.json().get("profileUrl")
        if not profile_url:
            return []
        if profile_url.startswith("/"):
            profile_url = f"{BACKEND_API_BASE}{profile_url}"
        ts = int(time.time() * 1000)
        hal = {
            "Authorization": f"Bearer {access_token}",
            "Accept": HOMEID_ACCEPT,
            "Accept-Language": "en-GB",
            "User-Agent": HOMEID_USER_AGENT,
            "X-USER-AGENT": HOMEID_X_USER_AGENT,
        }
        pr = self.s.get(f"{profile_url}?ts={ts}", headers=hal, timeout=30)
        if DEBUG:
            print(f"[debug] profile HTTP {pr.status_code}: {pr.text[:600]}")
        if pr.status_code != 200:
            return []
        profile = pr.json()
        emb = profile.get("_embedded", {})
        ua = emb.get("userAppliances", {}) if isinstance(emb, dict) else {}
        if isinstance(ua, dict):
            items = ua.get("_embedded", {}).get("item", [])
            if items:
                return items
        links = profile.get("_links", {})
        ua_link = links.get("userAppliances") if isinstance(links, dict) else None
        href = ua_link.get("href", "") if isinstance(ua_link, dict) else ""
        if not href:
            return []
        if href.startswith("/"):
            href = f"{BACKEND_API_BASE}{href}"
        href = re.sub(r"\{[^}]*\}", "", href)
        ar = self.s.get(f"{href}?ts={ts}&includeSkippedPairing=true", headers=hal, timeout=30)
        if DEBUG:
            print(f"[debug] appliances HTTP {ar.status_code}: {ar.text[:800]}")
        if ar.status_code != 200:
            return []
        data = ar.json()
        if isinstance(data, dict):
            return data.get("_embedded", {}).get("item", [])
        if isinstance(data, list):
            return data
        return []

    def _hal_get(self, url: str, access_token: str) -> dict:
        """GET a HomeID HAL resource; return {} on any failure."""
        try:
            r = self.s.get(url, headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": HOMEID_ACCEPT,
                "Accept-Language": "en-GB",
                "User-Agent": HOMEID_USER_AGENT,
                "X-USER-AGENT": HOMEID_X_USER_AGENT,
            }, timeout=30)
            if DEBUG:
                print(f"[debug] HAL GET {url[:96]} -> HTTP {r.status_code}: {r.text[:700]}")
            return r.json() if r.status_code == 200 else {}
        except Exception as e:
            if DEBUG:
                print(f"[debug] HAL GET failed: {e}")
            return {}

    def appliance_to_candidate(self, item: dict, access_token: str) -> dict:
        """Enrich a thin HomeID appliance into a connectable device candidate.

        The appliance item only carries _links; follow the self (appliance
        details) and device links. The Device resource's UUID is the base of
        the AWS thing name (da-<deviceUuid>), matching philips_airplus topics.
        """
        links = item.get("_links", {}) if isinstance(item, dict) else {}
        self_href = (links.get("self") or {}).get("href", "")
        device_href = (links.get("device") or {}).get("href", "")

        detail = self._hal_get(self_href, access_token) if self_href else {}
        device_uuid = ""
        dev: dict = {}
        if device_href:
            clean = re.sub(r"\{[^}]*\}", "", device_href).rstrip("/")
            device_uuid = clean.split("/")[-1]
            dev = self._hal_get(clean, access_token)

        def pick(*vals):
            for v in vals:
                if v:
                    return v
            return ""

        name = pick(detail.get("name"), item.get("name"), dev.get("name"),
                    dev.get("deviceName")) or "?"
        mac = pick(dev.get("macAddress"), dev.get("mac"), detail.get("macAddress")) or "?"
        ctn = pick(dev.get("modelId"), dev.get("ctn"), dev.get("model"), dev.get("type"),
                   detail.get("modelId"), detail.get("ctn")) or "?"
        thing = pick(dev.get("thingName"), detail.get("thingName"))  # explicit, if present
        if not thing and device_uuid:
            thing = device_uuid if device_uuid.startswith("da-") else f"da-{device_uuid}"
        return {"name": str(name), "ctn": str(ctn), "mac": str(mac),
                "uuid": device_uuid, "thing": thing,
                "raw": {"appliance": detail or item, "device": dev}}


# --------------------------------------------------------------------------- #
# Token cache (so the human only does one OTP)
# --------------------------------------------------------------------------- #
def save_tokens(tok: dict, app: str) -> None:
    try:
        with open(TOKENS_FILE, "w", encoding="utf-8") as fh:
            json.dump({"app": app, "refresh_token": tok.get("refresh_token", "")}, fh)
        os.chmod(TOKENS_FILE, 0o600)
    except OSError as e:
        print(f"[warn] could not cache tokens: {e}")


def load_refresh_token(app: str) -> str | None:
    if not os.path.isfile(TOKENS_FILE):
        return None
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("app") != app:   # cached token belongs to a different app/client
            return None
        return data.get("refresh_token") or None
    except (OSError, json.JSONDecodeError):
        return None


def authenticate(cloud: PhilipsCloud, email: str | None, app: str,
                 force_otp: bool = False) -> dict:
    """Return OIDC tokens, preferring a cached refresh token over a new OTP."""
    rt = load_refresh_token(app)
    if rt and not force_otp:
        try:
            print(f"[auth] using cached {app} refresh token ...")
            tok = cloud.refresh_tokens(rt)
            save_tokens(tok, app)
            return tok
        except CloudError as e:
            print(f"[auth] refresh failed ({e}); falling back to email OTP")

    if not email:
        email = input("Philips account email: ").strip()
    print(f"[auth] requesting OTP for {email}  ({app} login) ...")
    vtoken = cloud.request_otp(email)
    print(f"[auth] OTP sent. Check the inbox of {email}.")
    code = input("Enter the verification code: ").strip()
    session_token = cloud.verify_otp(email, code, vtoken)
    tok = cloud.get_oidc_tokens(session_token)
    save_tokens(tok, app)
    print("[auth] OIDC tokens obtained.")
    return tok


# --------------------------------------------------------------------------- #
# Device selection
# --------------------------------------------------------------------------- #
def _extract_device_list(data) -> list:
    """Pull the device array out of /user/self/device across schema variants.

    Mirrors philips_airplus/api.list_devices: accept a bare list, a dict with a
    known key, a HAL _embedded list, or any nested list of id/uuid-bearing dicts.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("devices", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        emb = data.get("_embedded")
        if isinstance(emb, dict):
            for v in emb.values():
                if isinstance(v, list):
                    return v
        for v in data.values():  # last resort: scan for a list of device-like dicts
            if isinstance(v, list) and any(
                isinstance(i, dict) and (i.get("uuid") or i.get("id") or i.get("thingName"))
                for i in v
            ):
                return v
    return []


def normalize_device(d: dict) -> dict:
    """Normalize an IoT device object. Air+ devices use `uuid` and no thingName;
    the AWS thing name for those is `da-<uuid>` (philips_airplus/mqtt_client.py)."""
    u = str(d.get("uuid") or d.get("id") or d.get("deviceId") or "")
    thing = d.get("thingName") or ""
    if not thing and u:
        thing = u if u.startswith("da-") else f"da-{u}"
    return {
        "name": d.get("name") or d.get("deviceName") or d.get("friendlyName") or "?",
        "ctn": str(d.get("ctn") or d.get("modelId") or d.get("type") or d.get("deviceType") or "?"),
        "mac": str(d.get("macAddress") or d.get("mac") or "?"),
        "uuid": u,
        "thing": thing,
        "raw": d,
    }


def describe_device(d: dict) -> str:
    return (f"name={d['name']!r:24} ctn={d['ctn']:14} mac={d['mac']:18} "
            f"uuid={d['uuid'] or '-'} thing={d['thing'] or '-'}")


def pick_device(devices: list, ctn: str | None, thing: str | None) -> dict:
    """Select from NORMALIZED device dicts."""
    if thing:
        for d in devices:
            if d["thing"] == thing or d["uuid"] == thing:
                return d
        return {"name": thing, "ctn": ctn or "?", "mac": "?", "uuid": "", "thing": thing, "raw": {}}
    if ctn:
        matches = [d for d in devices
                   if d["ctn"].upper().startswith(ctn.upper()) or ctn.upper() in d["name"].upper()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"[warn] multiple devices match {ctn!r}; choose below.")
            devices = matches
    if not devices:
        raise CloudError("No devices to choose from.")
    if len(devices) == 1:
        return devices[0]
    print("\nPick a device:")
    for i, d in enumerate(devices):
        print(f"  [{i}] {describe_device(d)}")
    return devices[int(input("Index: ").strip())]


# --------------------------------------------------------------------------- #
# Raw MQTT capture client
# --------------------------------------------------------------------------- #
class ShadowDumper:
    def __init__(self, thing: str, access_token: str, signature: str,
                 user_id: str, capture_path: str, poll_interval: float,
                 client_id_override: str | None = None) -> None:
        self.thing = thing
        self.access_token = access_token
        self.signature = signature
        self.user_id = user_id
        self.capture_path = capture_path
        self.poll_interval = poll_interval
        self.client_id = client_id_override or f"{user_id}_{uuid.uuid4()}"

        self.connected = threading.Event()
        self._stop = threading.Event()
        self._fh = open(capture_path, "a", encoding="utf-8")
        self._last_values: dict[str, dict] = {}     # namespace -> {key: value}
        self._read_ports: list[str] = list(DEFAULT_READ_PORTS)
        self._lock = threading.Lock()

        t = self.thing
        self.topics_sub = [
            f"$aws/things/{t}/shadow/get/accepted",
            f"$aws/things/{t}/shadow/get/rejected",
            f"$aws/things/{t}/shadow/update/accepted",
            f"$aws/things/{t}/shadow/update/rejected",
            f"$aws/things/{t}/shadow/update/delta",
            f"{TENANT}_ctrl/{t}/from_ncp",
        ]
        self.topic_shadow_get = f"$aws/things/{t}/shadow/get"
        self.topic_to_ncp = f"{TENANT}_ctrl/{t}/to_ncp"

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id, transport="websockets", clean_session=True,
        )
        self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)
        headers = {
            "x-amz-customauthorizer-name": "CustomAuthorizer",
            "x-amz-customauthorizer-signature": self.signature,
            "token-header": f"Bearer {self.access_token}",
            "tenant": TENANT,
            "content-type": "application/json",
        }

        def apply_ws(default_headers):
            default_headers.pop("Origin", None)   # Custom Authorizer rejects Origin
            default_headers.update(headers)
            return default_headers

        self.client.ws_set_options(path=MQTT_PATH, headers=apply_ws)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    # ---- lifecycle ----
    def run(self) -> None:
        print(f"[mqtt] client_id={self.client_id}")
        print(f"[mqtt] connecting wss://{MQTT_HOST}:{MQTT_PORT}{MQTT_PATH} for thing {self.thing}")
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=KEEPALIVE)
        self.client.loop_start()
        if not self.connected.wait(timeout=30):
            self.client.loop_stop()
            raise CloudError(
                "MQTT did not connect within 30s. Common causes: client_id prefix "
                "must equal the get-id userId; token expired; wrong region/tenant."
            )
        poller = threading.Thread(target=self._poll_loop, daemon=True)
        poller.start()
        print(f"[capture] appending to {self.capture_path}")
        print("[ready] Trigger functions on the device now. Ctrl+C to stop.\n")
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[stop] disconnecting ...")
        finally:
            self._stop.set()
            self.client.loop_stop()
            self.client.disconnect()
            self._fh.flush()
            self._fh.close()

    def _poll_loop(self) -> None:
        if self.poll_interval <= 0:
            return
        while not self._stop.wait(self.poll_interval):
            if not self.connected.is_set():
                continue
            self._publish(self.topic_shadow_get, "{}")
            with self._lock:
                ports = list(self._read_ports)
            for p in ports:
                self._send_ncp("getPort", p, {})

    # ---- MQTT callbacks ----
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[mqtt] CONNACK rejected: {reason_code}")
            return
        print("[mqtt] connected.")
        for topic in self.topics_sub:
            client.subscribe(topic, qos=0)
        self.connected.set()
        # initial state pulls
        self._publish(self.topic_shadow_get, "{}")
        self._send_ncp("getAllPorts", "", None)
        for p in self._read_ports:
            self._send_ncp("getPort", p, {})

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected.clear()
        if not self._stop.is_set():
            print(f"[mqtt] disconnected ({reason_code}); paho will retry ...")

    def _on_message(self, client, userdata, msg):
        # AWS IoT may concatenate multiple JSON objects in one frame.
        text = msg.payload.decode("utf-8", errors="replace")
        dec = json.JSONDecoder()
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx] in " \t\r\n":
                idx += 1
            if idx >= len(text):
                break
            try:
                payload, end = dec.raw_decode(text, idx)
            except json.JSONDecodeError:
                self._record(msg.topic, {"_raw_undecodable": text[idx:]})
                break
            self._record(msg.topic, payload)
            # If the device just told us its ports, poll all read ports too.
            self._maybe_learn_ports(payload)
            idx = end

    # ---- recording + console diff ----
    def _record(self, topic: str, payload) -> None:
        line = json.dumps({"ts": now_iso(), "topic": topic, "payload": payload},
                          ensure_ascii=False, separators=(",", ":"))
        self._fh.write(line + "\n")
        self._fh.flush()
        self._print_changes(topic, payload)

    def _namespace_and_props(self, topic: str, payload) -> tuple[str, dict] | None:
        """Reduce a message to (namespace, flat-dict-of-interesting-keys)."""
        if topic.endswith("/from_ncp"):
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict) and "properties" in data:
                port = data.get("portName", "?")
                props = data.get("properties")
                if isinstance(props, dict):
                    return f"ncp:{port}", props
            return None
        if "/shadow/" in topic:
            state = payload.get("state", {}) if isinstance(payload, dict) else {}
            reported = state.get("reported") or state.get("desired") or {}
            if isinstance(reported, dict):
                # keep only scalar top-level keys for the live view
                flat = {k: v for k, v in reported.items() if not isinstance(v, (dict, list))}
                return "shadow", flat
            return None
        return None

    def _print_changes(self, topic: str, payload) -> None:
        np = self._namespace_and_props(topic, payload)
        if not np:
            return
        namespace, props = np
        prev = self._last_values.setdefault(namespace, {})
        changes = []
        for k, v in props.items():
            if k not in prev:
                changes.append(f"+{k}={v!r}")
            elif prev[k] != v:
                changes.append(f"{k}:{prev[k]!r}->{v!r}")
            prev[k] = v
        if changes:
            print(f"{now_iso()}  {namespace:14} {'  '.join(changes)}")

    def _maybe_learn_ports(self, payload) -> None:
        if not isinstance(payload, dict) or payload.get("cn") != "getAllPorts":
            return
        data = payload.get("data")
        if not isinstance(data, list):
            return
        read_ports = [p.get("portName") for p in data
                      if isinstance(p, dict) and p.get("direction") == "read" and p.get("portName")]
        if read_ports:
            with self._lock:
                merged = list(dict.fromkeys(self._read_ports + read_ports))
                self._read_ports = merged
            print(f"[ncp] discovered read ports: {read_ports}")
            for p in read_ports:
                self._send_ncp("getPort", p, {})

    # ---- publishing ----
    def _publish(self, topic: str, payload: str) -> None:
        if self.client:
            self.client.publish(topic, payload, qos=1)

    def _send_ncp(self, command: str, port: str, properties) -> None:
        envelope = {
            "cid": secrets.token_bytes(4).hex(),
            "time": ncp_time(),
            "type": "command",
            "cn": command,
            "ct": "mobile",
        }
        if port:
            data = {"portName": port}
            if properties is not None:
                data["properties"] = properties
            envelope["data"] = data
        self._publish(self.topic_to_ncp, json.dumps(envelope, separators=(",", ":")))


# --------------------------------------------------------------------------- #
def main() -> int:
    load_env_file()
    ap = argparse.ArgumentParser(description="Raw Philips Air+ FUSION shadow/NCP capture.")
    ap.add_argument("--email", default=os.environ.get("PHILIPS_EMAIL"),
                    help="Philips account email (or set PHILIPS_EMAIL / .env).")
    ap.add_argument("--relogin", action="store_true",
                    help="Ignore the cached token and force a fresh email-OTP login "
                         "(use when switching to a different Philips account).")
    ap.add_argument("--app", choices=("airplus", "homeid"), default="airplus",
                    help="Which Philips app account to use. 'airplus' (default) lists "
                         "fans/purifiers; 'homeid' lists kitchen appliances (airfryers).")
    ap.add_argument("--ctn", default=os.environ.get("PHILIPS_DEVICE_CTN", "CX3550"),
                    help="CTN prefix to auto-pick the device (default: CX3550).")
    ap.add_argument("--thing", default=None, help="Explicit AWS IoT thingName (da-...).")
    ap.add_argument("--list-only", action="store_true",
                    help="Log in, list devices, and exit (confirm CTN / online state).")
    ap.add_argument("--poll-interval", type=float, default=4.0,
                    help="Seconds between getPort polls of read ports (0 = push-only).")
    ap.add_argument("--out", default=os.path.join(CAPTURES_DIR, "raw_shadow.jsonl"),
                    help="Capture file (JSON lines, append-only).")
    ap.add_argument("--client-id", default=os.environ.get("PHILIPS_MQTT_CLIENT_ID"),
                    help="Override MQTT client_id (debug; default {userId}_{uuid}).")
    ap.add_argument("--debug", action="store_true",
                    help="Dump raw HTTP responses from the discovery endpoints.")
    args = ap.parse_args()
    global DEBUG
    DEBUG = args.debug

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    client_id, redirect_uri, scopes = AUTH_PROFILES[args.app]
    cloud = PhilipsCloud(client_id, redirect_uri, scopes)

    try:
        tokens = authenticate(cloud, args.email, args.app, force_otp=args.relogin)
        access_token = tokens["access_token"]
        id_token = tokens.get("id_token", "")

        # Discovery. The IoT registry (/user/self/device) is empty for these
        # cloud appliances, so the authoritative source is the HomeID backend:
        # each appliance links to a Device resource whose UUID gives the AWS
        # thing name (da-<deviceUuid>).
        try:
            raw_devices = cloud.get_devices(access_token)
        except CloudError as e:
            print(f"[warn] IoT /device failed: {e}")
            raw_devices = []
        candidates = [normalize_device(d) for d in raw_devices]

        try:
            appliances = cloud.get_appliances_via_homeid(access_token)
        except Exception as e:
            print(f"[warn] HomeID appliances failed: {e}")
            appliances = []
        seen = {c["thing"] for c in candidates}
        for a in appliances:
            cand = cloud.appliance_to_candidate(a, access_token)
            if cand["thing"] and cand["thing"] not in seen:
                seen.add(cand["thing"])
                candidates.append(cand)

        print(f"\n[IoT /device] {len(raw_devices)} device(s) | "
              f"[HomeID appliances] {len(appliances)} appliance(s)")
        print(f"\n[candidates] {len(candidates)} connectable device(s):")
        for d in candidates:
            print("   " + describe_device(d))

        if args.list_only:
            print("\n[list-only] done. Re-run without --list-only to capture.")
            return 0

        if not candidates:
            raise CloudError(
                "No connectable devices. Re-run with --list-only --debug and share the output."
            )
        device = pick_device(candidates, args.ctn, args.thing)
        thing = device["thing"]
        if not thing:
            raise CloudError(f"Selected device has no resolvable thingName: {device}")
        print(f"\n[device] capturing: {describe_device(device)}")

        user_id = cloud.get_mqtt_user_id(access_token, id_token) if id_token else None
        if not user_id and not args.client_id:
            raise CloudError("Could not obtain MQTT userId (get-id). The IoT policy will reject CONNECT.")
        signature = cloud.get_mqtt_signature(access_token)
        if not signature:
            raise CloudError("Empty MQTT signature from /user/self/signature.")

        dumper = ShadowDumper(
            thing=thing, access_token=access_token, signature=signature,
            user_id=user_id or "", capture_path=args.out,
            poll_interval=args.poll_interval, client_id_override=args.client_id,
        )
        dumper.run()
        return 0
    except CloudError as e:
        print(f"\n[error] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
