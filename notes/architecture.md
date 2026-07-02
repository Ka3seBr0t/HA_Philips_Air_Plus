# Architecture — Philips CX3550/01 → Home Assistant (Phase 0 / Gate 0)

Status: **Gate 0 passed** (architecture understood from source). Written from a full read of both
candidate integrations. Nothing here is guessed; every claim cites the source file it came from.
The CX3550/01 itself has **not** been contacted yet — the device-specific property keys are still
unknown and are the goal of Phase 1–2.

Repos read (shallow-cloned into `vendor/`):
- `renaudallard/homeassistant_philips_homeid` (domain `philips_homeid`) — **primary**
- `ShorMeneses/philips-airplus-homeassistant` (domain `philips_airplus`) — **secondary / likely better fit**

---

## TL;DR — what changed vs. the original brief

1. **No browser, no OAuth redirect, no rooted phone needed for auth.** Both integrations log in with
   **email + a one-time code (OTP)** sent to the Philips account email, then complete a *pure-HTTP*
   Gigya/OIDC PKCE exchange. The human only has to read a 6-digit code out of their inbox. The
   `[MENSCH]` "Cloud-Login im Browser / OAuth-Redirect-Code" step in the brief is replaced by
   "give the script your account email, then type the code you receive."
2. **The credential-extractor / rooted-Android path is only for LOCAL devices.** The CX3550/01 is
   cloud-only (the brief confirms this), which means it is a **FUSION** device and uses the OIDC
   token directly. **Phase 4 (MITM/Frida) is very likely unnecessary** and should stay a last resort.
3. **The AWS device shadow is only half the data.** For Air+ class devices the meaningful properties
   do **not** live in `shadow/reported` — they come over an **NCP port channel** (`Status` port) on a
   separate MQTT topic. The dump tool must capture *both* and must **poll `getPort` periodically**,
   because NCP pushes only carry changed fields.
4. **Two property-encoding dialects exist** for Philips Air FUSION devices. Which one the fan uses is
   the single most important unknown the sweep will resolve (see §6).

---

## 1. Identity / auth path (both integrations, identical)

Source: `philips_homeid/cloud_auth.py`, `philips_homeid/const.py`,
`philips_airplus/const.py` (same Gigya key + client_id confirm both use the same flow).

| Item | Value |
|------|-------|
| Gigya API key | `4_JGZWlP8eQHpEqkvQElolbA` |
| Gigya base | `https://cdc.accounts.home.id` |
| OIDC issuer | `https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA` |
| OAuth client_id | `-u6aTznrxp9_9e_0a57CpvEG` |
| Mobile redirect URI | `com.philips.ka.oneka.app.prod://oauthredirect` |

Flow (`cloud_auth.py`):
1. `POST {gigya}/accounts.auth.otp.email.sendCode` `{email, apiKey, format=json}` → **`vToken`**.
   *(This triggers the email with the code.)*
2. `POST {gigya}/accounts.auth.otp.email.login` `{email, code, vToken, apiKey, format=json}` →
   `sessionInfo.cookieValue` (= Gigya **session token**).
   - errorCode `206001` = "account pending registration": the email isn't a fully-registered HomeID
     account (social login / never finished signup). Fix: sign in once in the app, then retry.
3. Pure-HTTP PKCE OAuth (`get_oidc_tokens` / `_http_oauth`):
   - `GET {issuer}/authorize?...&prompt=none` (no redirect-follow) → grab `context` JWT from `Location`.
   - `POST {gigya}/socialize.getIDs {APIKey, includeTicket=true}` → `gmidTicket`.
   - `GET {issuer}/authorize/continue?context&login_token=<session>&gmidTicket&client_id` → `code`.
   - `POST {issuer}/token` (`grant_type=authorization_code` + PKCE verifier) →
     **`access_token`, `id_token`, `refresh_token`, `expires_in`**.
4. Refresh: `POST {issuer}/token grant_type=refresh_token`. Access token lives ~1 h; refresh proactively.

Tokens we carry forward: **`access_token`** (Bearer for IoT REST + MQTT), **`id_token`** (only for
`get-id`), **`refresh_token`** (long-lived; lets the dump reconnect without a new OTP).

---

## 2. Device discovery + FUSION detection

IoT REST base (EU "DaConnect" region — correct for Germany):
`https://prod.eu-da.iot.versuni.com/api/da` (`cloud_api.py:52`, `philips_airplus/const.py:8`).

- **Device list:** `GET .../user/self/device` (Bearer access_token) → array of
  `{id, ctn, friendlyName, macAddress, thingName, ...}` (`cloud_api.py:253`).
  - **`thingName`** is the AWS IoT thing name used in all MQTT topics. For Air+ devices it has the
    form **`da-<uuid>`** (confirmed by `philips_airplus/mqtt_client.py:47` which force-prefixes `da-`).
  - `ctn` is the marketing CTN (e.g. it should read **`CX3550/01`** for our fan). This is the key we
    match on to pick the device and later to name the model entry.
- **Richer appliance metadata (HomeID backend):** `get_appliances_via_homeid()` (`cloud_api.py:355`)
  walks `/.well-known/tenant/oneka` → profile → `userAppliances`, exposing `clientId`, `clientSecret`,
  `externalDeviceId`, `registeredIn`, `firmwareVersion`.

**FUSION decision (config_flow.py:691-723):**
```
if appliance has clientId AND clientSecret      -> LOCAL device (HTTP, needs local creds)
elif appliance has externalDeviceId (no creds)  -> FUSION cloud relay (MQTT)  <-- expected for CX3550
else                                            -> unusable (paired outside HomeID flow)
```
The CX3550/01 is cloud-only ⇒ we expect **no local creds + an `externalDeviceId` ⇒ FUSION**. The dump
tool will print these fields so we can confirm at runtime (this is the runtime check the brief asked for).

---

## 3. MQTT transport (FUSION / cloud relay)

Source: `philips_homeid/mqtt_api.py`, corroborated by `philips_airplus/mqtt_client.py`.

| Item | Value |
|------|-------|
| Library | **`paho-mqtt`** (Python). `philips_homeid` uses CallbackAPIVersion **VERSION2**; `philips_airplus` uses MQTTv311 + v1 callbacks. Either works. |
| Broker | `ats.prod.eu-da.iot.versuni.com` |
| Transport / port | **WebSocket Secure, port 443**, WS path **`/mqtt`** |
| TLS | `tls_set(CERT_REQUIRED)` (`mqtt_api.py:305`). Port 8883 (mTLS) is *not* usable — no client certs. |
| Auth | **AWS IoT Custom Authorizer** via WS upgrade headers (no mTLS, no SigV4) |
| client_id | **`{userId}_{uuid4}`** (`mqtt_api.py:288`). `userId` from `get-id` (see below). The IoT policy reportedly rejects CONNECT *silently* if the prefix isn't the userId (`__init__.py:114`). `philips_airplus` instead uses `ha-{device_id}` / a fixed id — treat as fallback only. |

WS upgrade headers (`mqtt_api.py:311`, `philips_airplus/mqtt_client.py:93`):
```
x-amz-customauthorizer-name:      CustomAuthorizer
x-amz-customauthorizer-signature: <mqtt_signature>      # see below
token-header:                     Bearer <access_token>
tenant:                           da
content-type:                     application/json
# paho's default "Origin" header MUST be removed (Custom Authorizer rejects it). mqtt_api strips it.
```

Two REST calls produce the missing MQTT inputs (`cloud_api.py`):
- **signature:** `GET https://prod.eu-da.iot.versuni.com/api/da/user/self/signature` (Bearer) →
  JSON `{"signature": "..."}`. Use `resp["signature"]` as `x-amz-customauthorizer-signature`
  (`cloud_api.py:115`, extraction at `__init__.py:196,229`). The APK/integration use the **OIDC
  access_token** for `token-header`, *not* anything from the signature response.
- **userId:** `POST https://prod.eu-da.iot.versuni.com/api/da/user/self/get-id` `{idToken}` →
  `{"userId": "..."}` (`cloud_api.py:151`). This is the MQTT client-id prefix.

Keepalive 30 s (`philips_homeid`) / 60 s (`philips_airplus`).

---

## 4. Topics & the shadow ⇄ NCP split

With `tn` = thingName (`da-<uuid>`) and tenant `da` (`mqtt_api.py:210`, `philips_airplus/const.py:75`):

**AWS IoT Device Shadow (classic):**
```
$aws/things/{tn}/shadow/get               (pub "{}" to request)
$aws/things/{tn}/shadow/get/accepted      (sub) -> full shadow document
$aws/things/{tn}/shadow/get/rejected      (sub)
$aws/things/{tn}/shadow/update            (pub: {"state":{"desired":{"powerOn":true}}})
$aws/things/{tn}/shadow/update/accepted   (sub) -> broadcast of any reported/desired change
$aws/things/{tn}/shadow/update/rejected   (sub)
$aws/things/{tn}/shadow/update/delta      (standard; device-facing, usually subscribable)
```
Shadow `state.reported` carries **device-level** keys only: `powerOn`, and per the airfryer code
`productState`, error, firmware. Power on/off for non-airfryer FUSION devices is a shadow
`desired.powerOn` write (`coordinator.py:331`, `mqtt_api.py:467`).

**NCP port channel (where the real per-feature data is):**
```
{tenant}_ctrl/{tn}/to_ncp     -> da_ctrl/{tn}/to_ncp     (pub commands)
{tenant}_ctrl/{tn}/from_ncp   -> da_ctrl/{tn}/from_ncp   (sub responses + spontaneous pushes)
```
NCP command envelope (`mqtt_api.py:534`, `philips_airplus/mqtt_client.py:347`):
```json
{"cid":"<8 hex>","time":"2026-06-25T19:40:00Z","type":"command","cn":"<cmd>","ct":"mobile",
 "data":{"portName":"<port>","properties":{...}}}
```
Commands: `getAllPorts` (discover ports + read/write direction), `getPort` (read one port),
`setPort`/`updatePort` (write). `getAllPorts` response lists ports with `direction: read|write`
(`mqtt_api.py:722`). For Air+ purifiers the live data is read from the **`Status`** port; writes go to
the **`Control`** port; filters via `filtRd`/`filtWr` (`philips_airplus/models.yaml`,
`philips_airplus/const.py:55`).

> **Key consequence for capture:** `ShorMeneses` subscribes *only* to `from_ncp` and never reads the
> shadow for state — all fan/mode/sensor data for AC0650/AC0651 arrives as `getPort Status` responses
> on `from_ncp`. So the dump must drive `getAllPorts` → `getPort` and **re-poll `getPort` on each
> discovered read port on a timer** (NCP pushes are partial/changed-fields-only per
> `mqtt_api.py:795`). Polling gives a full snapshot per sweep step → clean diffs.

---

## 5. Where raw properties flow (the logging tap)

- `philips_homeid/mqtt_api.py:658` `_on_message()` — **every** inbound frame; line 671 already
  `_LOGGER.debug("MQTT message on %s: %s", topic, payload)`. This is the canonical tap point.
  - `_handle_shadow()` (`:685`) parses `state.reported`.
  - `_handle_ncp_response()` (`:717`) parses `data.portName` + `data.properties`; note it **renames**
    NCP keys via `_NCP_PROPERTY_MAP`/`_VENUS_KEY_MAP` — for capture we want the **raw** keys, so the
    standalone dump logs the payload *before* any mapping.
- `philips_airplus/mqtt_client.py:125` `_on_message()` — same idea; also handles the AWS quirk where
  **multiple JSON objects are concatenated in one WS frame** (uses `JSONDecoder.raw_decode` in a loop).
  The dump tool replicates this so no frame is dropped.

The standalone `scripts/shadow_dump.py` does **not** import these modules (they use HA-relative
imports and pull in `homeassistant`). It re-implements the exact same HTTP calls + a minimal raw paho
logger. This is the "minimal nachbauen" option the brief allows, and it keeps the capture free of HA
log noise.

---

## 6. Property-encoding dialects — the central unknown

Two confirmed-in-the-wild schemes for Philips Air FUSION `Status`/`Control` ports:

**Dialect A — hex "DI" codes (ShorMeneses, AC0650/AC0651/AC1715, cloud-only):** `philips_airplus/models.yaml`
| meaning | key | notes |
|---|---|---|
| mode / fan_speed (setpoint) | `D0310C` | integer-coded modes: Auto 0/1, Medium 1, Fast 2, Sleep 17, Turbo 18 |
| power / actual fan level | `D0310D` | 0=off,1=slow…18=turbo |
| PM2.5 | `D03221` | µg/m³ |
| allergen index | `D03120` | |
| filter replace nominal/remaining | `D05408` / `D0540E` | |
| filter clean nominal/remaining | `D05207` / `D0520D` | |
| model CTN | `ctn` | |

**Dialect B — friendly keys (renaudallard fan.py, the classic py-air-control/CoAP vocabulary):**
`om` (fan speed), `mode` (A/M/S/T/AG/B/N), `pwr`, `cl` (child lock), `pm25`, `iaql`, `rh`, `temp`.
These appear in `coordinator.py` FUSION command paths (`status`+`om`/`mode`/`cl`) **and** in
`fan.py`, but renaudallard's fan entity is gated to `air_purifier` + local connectivity and **no
purifier is listed as a tested FUSION device** — so Dialect B is most likely its *local-HTTP*
vocabulary, not what a cloud fan emits.

**Hypothesis for CX3550/01:** as a cloud-only device it most likely speaks **Dialect A (`Dxxxxx` on a
`Status` port)**, like its AC0650/AC0651 siblings. But the fan adds functions purifiers don't have —
**oscillation** and a **timer** — whose `Dxxxxx` codes are unknown and must come from the sweep. The
sweep+diff (Phase 2) is what settles dialect *and* the oscillation/timer keys.

---

## 7. ShorMeneses model-entry format (Route B target)

`models.yaml` is a flat dict keyed by CTN; `model_manager.py:40` does exact-then-prefix match
(so `CX3550/01` matches a device reporting `CX3550/01-EU`). A model entry:
```yaml
"CX3550/01":
  name: "Philips Air+ CX3550/01"
  modes:              # preset_mode name -> integer written to the mode property
    Auto: 0
    Sleep: 17
    Turbo: 18
  ports:              # logical role -> NCP port name (defaults: Status/Control/Config/filtRd/filtWr)
    status: "Status"
    control: "Control"
    config: "Config"
  properties:         # logical name -> raw MQTT key (Dxxxxx) or literal
    fan_speed: "D0310C"
    mode: "D0310C"
    power: "D0310D"
    pm25: "D03221"
  sensors: [ pm25, fan_level ]
  switches: [ ... ]   # boolean Control-port props (e.g. child lock, oscillation?)
  buttons:  [ ... ]
```
Entities are built generically from this map (`fan.py`/`sensor.py`/`switch.py` read the keys via the
model config). **Gaps for a fan:** the current schema models purifier concepts only — it has **no
oscillation switch convention and no timer/number** beyond filter resets. Supporting oscillation +
timer on Route B will need a small schema/code extension (a `switches:` entry can likely cover
oscillation if it's a boolean Control prop; the timer likely needs a new `number`/duration concept).

---

## 8. Route recommendation (decide after Phase 2 data)

- **Lean Route B (ShorMeneses)** *if* the fan reports Dialect-A `Dxxxxx` keys on a `Status` port and
  its functions map to mode-int + booleans. Rationale: it is purpose-built for cloud-MQTT Air+, the
  model entry is pure YAML, and the on-wire scheme matches. Cost: extend the schema for
  oscillation/timer.
- **Consider Route A (renaudallard)** if the fan needs richer/coupled behavior, exposes friendly keys,
  or if we want its more robust token-refresh/reconnect machinery. Cost: add a fan-over-FUSION device
  type + NCP hex-key translation; more code than a YAML entry.

Both share auth + transport, so the Phase 1 dump tool is route-agnostic and serves either.

---

## 9. Open items to confirm at runtime (Phase 1)

1. Device-list `ctn` reads `CX3550/01`; appliance has **`externalDeviceId` and no clientId/secret**
   ⇒ confirms FUSION. (If it *has* local creds, revisit — local control might be possible.)
2. MQTT CONNECT succeeds with `client_id = {userId}_{uuid}` and the Custom Authorizer headers.
3. `getAllPorts` returns the fan's actual port names (expect `Status`/`Control`; could differ).
4. Whether real state is in `from_ncp` `Status` (expected) or in `shadow/reported` (fallback).
5. Dialect A vs B, and the oscillation/timer keys (Phase 2).
