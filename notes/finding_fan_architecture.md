# Befund: Die CX3550-Lüfter nutzen eine NEUERE Cloud-Architektur

Stand 2026-06-26. Quelle: Pi-hole-DNS-Log (v6) vom lokalen Pi-hole + direkte
Endpunkt-Tests mit dem Air+-Gigya-Token.

## Kernaussage

Die CX3550/01-Lüfter hängen **nicht** an dem Cloud-Pfad, den die beiden
Referenz-Integrationen (`renaudallard/...homeid`, `ShorMeneses/philips-airplus`)
**und** unser `shadow_dump.py` implementieren. Die nutzen alle:

> Gigya-OIDC-Bearer-Token → `prod.eu-da.iot.versuni.com/api/da/user/self/device`
> → AWS-IoT WSS mit Custom Authorizer.

Für **dieses Konto** ist dieser Pfad leer (0 Geräte) — verifiziert. Die Lüfter
laufen über einen **neueren Pfad**, den die App (laut Pi-hole) tatsächlich nutzt.

## Belege (Pi-hole + Endpunkt-Tests)

Hosts, die die Air+-App / die Geräte real ansprechen (vorher nie probiert):

| Host | Bedeutung | Test-Ergebnis |
|---|---|---|
| `cognito-identity.eu-west-1.amazonaws.com` | **AWS Cognito** Identity Pool | App tauscht Gigya→AWS-Credentials |
| `www.api.air.philips.com` | Philips-Air Geräte-API (Cloudflare) | 404 auf geratene Pfade (Pfad unbekannt) |
| `prod.global-da.iot.versuni.com` | Geräte-**Bootstrap** (`/configuration`) | 400 „URI does not contain '/configuration'" |
| `a2gv4wmvb0sdt5-ats.iot.eu-central-1.amazonaws.com` | rohes **AWS IoT eu-central-1** | von einem Gerät im lokalen Netz angefragt (Geräte-Broker) |

Tenant-Test auf dem eu-da-Host:
- `/api/da/user/self/device` → `200 []`  (mein Token gilt, aber 0 Geräte)
- `/api/global-da/user/self/device` → **`401 Unauthorized`** (Tenant existiert,
  mein `da`-Token ist dafür nicht autorisiert)

## Schlussfolgerung

Die Lüfter sind eine **neuere Geräte-Generation** mit:
- **AWS-Cognito-Auth** (eu-west-1) statt/zusätzlich zum Gigya-Bearer,
- Geräte-/Listen-API über `www.api.air.philips.com` und/oder Tenant `global-da`,
- AWS IoT vermutlich in **eu-central-1** (SigV4 via Cognito), nicht der
  Custom-Authorizer-WSS auf `ats.prod.eu-da`.

→ **Keine** der existierenden Integrationen unterstützt das. „Modell-Eintrag
schreiben" reicht nicht; es wäre eine **neue Integration für eine neue
Cloud-Architektur** (Cognito-Credential-Exchange + SigV4 + neuer IoT-Endpoint +
neues Topic-/Property-Schema).

## Was für den Bau noch fehlt (nur per App-Mitschnitt / Method B zu kriegen)

1. **Cognito Identity Pool ID** (eu-west-1) + Login-Provider-Key — steckt in der App.
2. Der echte **Geräte-Listen-Endpunkt** + Pfad auf `www.api.air.philips.com`.
3. Der/die **thingName(s)** der Lüfter.
4. Der **AWS-IoT-Endpoint** + Auth (SigV4 vs Authorizer) + Topic-Schema.

Das S26 blockt HTTP Toolkit (Pinning, kein Root) → Mitschnitt nur über
rootbaren Emulator + frida, oder gerootetes Gerät.

## Verifizierte Sackgassen (nicht nochmal probieren)
- Wildcard-MQTT-Abo → Broker trennt (rc128); Policy erlaubt nur eigene Things (0).
- ShorMeneses-Integration + Debug-Log → braucht Gerät aus der leeren Liste; kein Wildcard.
- Regionen us/ap/cn-da, eu-cc/di/fc/hc → existieren nicht / 401 / leer für dieses Token.

---

## APK-Analyse (com.philips.ph.homecare, „Philips HomeCare", von Air Matters)

Aus `base.apk` (vom S26 per adb gezogen, reine String-Analyse, kein Decompiler):

**Die App bündelt ZWEI Clouds:**
1. **Air-Matters-Backend (gaoda-SDK)** — Geräte-Verwaltung/Liste/MQTT-Info:
   Host **`data.air-matters.com`**, API `enduser/*`:
   - `enduser/login/`, `enduser/getToken/`, `enduser/v2/getToken/` → **eigener
     Air-Matters-Token** (NICHT der Philips/Gigya-Token!)
   - `enduser/deviceList/` → die Lüfter (Gigya-Bearer → `403 "unauthorized request"`)
   - **`enduser/mqttInfo/` / `enduser/v2/mqttInfo/`** ← der Jackpot: Broker + Thing +
     Credentials fürs MQTT-Control
   - `enduser/bindDevice/`, `enduser/share/*`, `enduser/grantDevice/` …
2. **Versuni DaConnect-SDK** (`com.philips.cl.daconnect`) — das eigentliche Control:
   gleiches **Shadow/NCP-Port-Modell** wie die bekannten Integrationen
   (`DaMqttClient`, `DeviceShadowDocument`, `Port/PortCommandName/Direction`,
   `NcpStatusCode`). REST: `air.prod.eu-da.iot.versuni.com/api` (Gigya-Bearer → 403),
   MQTT: `ats.prod.eu-da.iot.versuni.com`.

**Auth-Hürde:** Das Air-Matters-Backend hat ein **eigenes Konto-/Token-System**
(`getToken`/`login`) + **App-seitige Request-Signierung** (`ClientKey`/`ApiKey`,
Fehlerstring „Cannot construct an Api with a null ClientKey"). Der Philips-Gigya-Token
allein reicht nicht. Es gibt zwei Gigya-Keys: `4_JGZWlP8eQHpEqkvQElolbA` (genutzt) +
`4_iX8FG_ECkagDbamClfS7Fg`.

**Geräte:** ESP32 (Espressif-Provisioning), WLAN.

**Fazit:** Voller Zugriff = Air-Matters' signierte `getToken→deviceList→mqttInfo`-Kette
nachbauen (proprietär, ClientKey-Signierung) **oder** einen Live-Mitschnitt dieser
3 Calls machen (Emulator+frida; das S26 pinnt). Danach ist Control wieder das
bekannte DaConnect-Shadow/NCP-Schema → unser `shadow_dump.py` greift wieder.
