# Auth & Refresh-Loop — geknackt & bewiesen (Stand 2026-06-27)

Siehe auch `architecture.md` (Cloud-Pfad) und `properties.md` (Shadow/D-Codes).
Arbeitscode: `methodb/airmatters_auth.py` (volle Kette, standalone, lauffähig).

## TL;DR — alles geknackt

- Die **air-matters Request-Signierung ist geknackt und live bewiesen** (Server akzeptiert
  die `Signature`, `getToken` + `mqttInfo` liefern echte Responses, code 0).
- Für den **periodischen JWT-Refresh brauchst du KEINEN refresh_token** — nur die statische
  `user_id` (32-hex, einmalig aus dem OneID-Login, läuft nie ab) + `app_id` + `mSecret`.
- Der **air-matters JWT ist 7 Tage** gültig (nicht 1 h; `exp = orig_iat + 604800`).
- Nur die **vorsignierte WSS-URL** aus `mqttInfo` ist 1 h gültig **und SINGLE-USE**
  (eine URL = genau eine WS-Verbindung; nach Disconnect verbraucht).
- HA kann also **vollautonom** laufen: JWT alle ~6 Tage refreshen, WSS-URL alle ~50 min.

## Die Token-Kette — bewiesen 2026-06-27

```
user_id (32-hex, stabil/ewig) + app_id + mSecret   [einmalig, statisch]
        │  POST enduser/v2/getToken/
        │     body {timestamp, username="PHILIPS:<user_id>", app_id}
        │     Header: Signature = sha256_HMAC(sha256_HMAC(bodyParams, mSecret), username)
        │            bodyParams = "app_id=<app_id>&timestamp=<ts>&username=<urlenc(username)>"
        ▼
air-matters JWT  (7 Tage; identification="PHILIPS:<user_id>")
        │  POST enduser/v2/mqttInfo/
        │     body {"device_id":["<id>",...]}
        │     Header: Authorization: jwt <JWT>     (KEINE Signature nötig!)
        ▼
mqttInfo = { device_id -> { host: wss://<broker>/mqtt?X-Amz-Signature=…&X-Amz-Security-Token=…,
                            endpoint, path, client_id } }
        │  X-Amz-Expires=3600  → URL 1 h gültig; SINGLE-USE (1 URL = 1 WS-Verbindung)
        │  client_id wird pro mqttInfo-Abruf neu vergeben (rotiert)
        ▼
paho MQTT-over-WSS connect  (Auth steckt in der URL-Query, kein Custom Authorizer)
        │  client_id MUSS die aus mqttInfo sein (SigV4-Policy scope-t darauf)
        ▼
$aws/things/<device_id>/shadow/...   → reported state (D-Codes) + desired (Steuerung)
```

| Token | Gültigkeit | Woher | Für |
|---|---|---|---|
| `user_id` (32-hex) | ewig | einmaliger OneID-OTP-Login → gecacht | `getToken`-username (stabil) |
| `mSecret` / `app_id` | ewig | APK-Bytecode (`HttpRequestManager`, `od.a`) | Signatur |
| air-matters JWT | **7 Tage** | signiertes `getToken` | `mqttInfo`-Aufruf (`Authorization: jwt …`) |
| SigV4 WSS-URL | **1 h, SINGLE-USE** | `mqttInfo` | MQTT-Connect (genau 1 Verbindung) |
| `client_id` | rotiert pro `mqttInfo` | `mqttInfo.client_id` | Connection-ID (SigV4-policy-gebunden) |

> Hinweis: Der `refresh_token` (`st2.s.…`, 236 Zeichen, in `scripts/.tokens.json`) gehört zum
> **OneID-OAuth-Layer** (`com.airmatters.oneid.OneIdAuth`, `grant_type=refresh_token`) und
> wird nur beim **initialen Login** gebraucht, um die `user_id`/`access_token` zu erhalten.
> Für den laufenden JWT-Refresh ist er **nicht** nötig. Falls die `user_id` irgendwann
> ungültig würde (Account-Reset), wäre der OneID-Refresh-Flow der Fallback.

## Signatur-Algorithmus (aus DEX-Bytecode, verifiziert gegen Live-Server)

`HttpRequestManager` (gaoda SDK), `mSecret = "<redacted — extracted per-user from own APK, see apk_extract.py>"`:

```
bodyParams = "app_id=" + APP_ID + "&timestamp=" + ts + "&username=" + URLEncoder.encode(username,"utf-8")
hmac1       = HmacSHA256(key=mSecret.getBytes(), data=bodyParams.getBytes())  -> lowercase hex
signature   = HmacSHA256(key=username.getBytes(), data=hmac1.getBytes())       -> lowercase hex
Header: "Signature": signature    (nur bei getToken; mqttInfo/deviceList brauchen KEINE Signatur)
Body  : JSON {"timestamp","username","app_id"}  (Content-Type: application/json;charset:utf-8)
```

`URLEncoder.encode` (Java): `-._*` bleiben, Space→`+`, Rest→`%XX`. In Python nachgebaut in
`airmatters_auth._java_urlencode`. Header-Name exakt `Signature`, User-Agent `okhttp/4.9.3`.

## Wichtige Korrekturen (vs. früherer Annahmen)

- **JWT = 7 Tage, nicht 1 h.** Die 1 h gelten nur der WSS-URL. (`exp=orig_iat+604800`.)
- **`username` für getToken = `"PHILIPS:<user_id>"`** (mit Prefix!). Ohne Prefix kommt ein
  Token in einem anderen Namespace → `mqttInfo` meldet `code 16002 "Not binding to the device"`.
- **refresh_token ist NICHT der username** (236 Zeichen → Server: "Length exceeds upper limit").
- **`"Cannot construct an Api with a null ClientKey"` gehört zu Google Play Services**,
  NICHT zu air-matters. Der echte air-matters-Signaturfehler ist `code 10001 "Lack of Signature"`.
- **WSS-URL ist SINGLE-USE.** Eine verbrauchte URL nach Disconnect erneut zu nutzen →
  "WebSocket handshake error, connection not upgraded". Pro Verbindung frisch holen.
  (Das hat die frühere "client_id must be mqttInfo"-Schlussfolgerung mitverwechselt —
  client_id aus mqttInfo ist trotzdem korrekt/nötig, aber der eigentliche Constraint
  ist die single-use URL.)
- **503-Transient:** `api.air.philips.com` beantwortet urllib-Requests intermittierend
  mit HTTP 503 (LB/WAF). Die App (okhttp) maskiert das mit Silent Retries. → in Python
  retrien (siehe `airmatters_auth._post`, 5×/8× Retry).

## Connect-Constraints (bewiesen 2026-06-27)

- **`client_id` aus `mqttInfo` verwenden** (rotiert pro Abruf; SigV4-Policy scope-t darauf).
- **Eine Verbindung pro Gerät gleichzeitig.** Gleiche client_id = App/HA flappen
  (DISCONNECT 128, last-one-wins). App lassen, während HA läuft (oder umgekehrt).
- **Pfad byte-identisch** an paho `ws_set_options(path=…)` — keine Re-Encodierung.
  `Origin`-Header strippen (AWS lehnt ab).
- **Single-use URL:** nach Trennung NEU holen (`mqttInfo`), nie dieselbe wiederverwenden.
- **Gerät pusht State selbst** (`shadow/update/accepted`, `desired:null` + neue `reported`
  bei jeder Geräteänderung). → in HA kein Pollen; einmalig `shadow/get` beim Connect,
  dann Deltas konsumieren.

## Was HA tun muss (Ziel-Zustand) — jetzt vollständig umsetzbar

1. **Einmal-Setup:** OTP-Login (über App/frida) → `user_id` (32-hex) notieren. Danach:
   `scripts/.tokens.json` brauchst du nur noch als Fallback (OneID-refresh).
2. **JWT-Loop (alle ~6 Tage):** `get_jwt()` aus `airmatters_auth.py` → JWT cachen.
3. **WSS-Loop (alle ~50 min ODER bei Disconnect):** `get_mqtt_info(jwt, [device_id])` →
   frische single-use URL + client_id → paho (re)connect.
4. **MQ offen halten** (keepalive); Shadow-Deltas konsumieren; `shadow/get` beim Connect.

**Keine Stunde-Neuanmeldung. Kein OTP. User_id + mSecret sind ewig.**

## Offen / nächste Schritte

- ✅ Signatur geknackt, JWT-Chain standalone bewiesen.
- ⬜ **Control-Write-Test:** `desired` an Shadow publishen und am Gerät verifizieren
  (Richtung Schreiben war bisher nicht bewiesen — lesen ja). Jetzt mit frischer URL machbar.
- ⬜ HA-Integration (custom integration / HACS-Domain `airplus_cx3550`): Refresh-Loop +
  Shadow-Mapping (`properties.md` §3e Entity-Map) anbinden.
- ⬜ Cleanup: `/h/.oma_url.tmp`, `/h/.oma_cid.tmp` (alte SigV4-Cred-Dateien) löschen.