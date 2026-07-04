# CX3550/01 — Property-Map (Phase 2, Stand 2026-06-27)

Quelle: **echter, vom AWS-IoT-Broker gelesener Shadow** (Mitschnitt der
`$aws/things/<id>/shadow/get/accepted`-MQTT-Nachricht für einen der beiden Lüfter,
`device_id <device_id>`). Geknackt per frida-interceptierter
`mqttInfo`-URL (pre-signed SigV4 WSS) → paho connect → `shadow/get`. Siehe
`captures/raw_shadow.jsonl` für den Rohmitschnitt und `notes/architecture.md`
für die Cloud-Architektur.

Beide Geräte (hier „Fan1"/„Fan2" genannt) sind `CX3550/01` (type `Trident`,
swversion `0.1.7`) → gleiche D-Code-Schema. Ein Shadow-Read pro Modell reicht.

## 1. Verifizierte Architektur (alle 4 unknowns aus `finding_fan_architecture.md` geklärt)

| Item | Wert | Quelle |
|---|---|---|
| Broker | `a2gv4wmvb0sdt5-ats.iot.eu-central-1.amazonaws.com` | `mqttInfo.endpoint` |
| Auth | pre-signed **SigV4 WSS-URL** (X-Amz-Signature + X-Amz-Security-Token aus Cognito/STS), **1 h gültig** (`X-Amz-Expires=3600`) | `mqttInfo.host`/`path` |
| thingName | = `device_id` (z.B. `<device_id>`) | `shadow/get/accepted`-Topic |
| Shadow-Topic | `$aws/things/<device_id>/shadow/...` | MQTT-Subscribe |
| client_id | pro Gerät + pro mqttInfo-Abruf neu (rotiert); nur Client-Identifikation, nicht sensibel | `mqttInfo.client_id` |

**Auth-Pfad zum Verbindungsaufbau** (funktioniert, bewiesen):
air-matters refresh_token → `enduser/v2/getToken/` → JWT →
`enduser/v2/mqttInfo/` → pre-signed WSS-URL → `paho` connect → shadow.

**OFFEN für standalone HA:** die air-matters **Request-Signierung**
(ClientKey/ApiKey, Fehlerstring „Cannot construct an Api with a null ClientKey")
für `getToken`/`deviceList`/`mqttInfo`. Ohne die kann HA sich die 1h-URL nicht
selbst holen — siehe `notes/auth_refresh.md`.

## 2. Echte `reported`-Payload (CX3550/01, „Fan1", 2026-06-27)

```json
{"state":{"reported":{
  "ConnectType":"Online",
  "DeviceId":"<device_id>",
  "StatusType":"status",
  "D01102":2,
  "D01S03":"Fan1",
  "D01S04":"Trident",
  "D01S05":"CX3550/01",
  "D01107":0, "D01108":3, "D01109":3, "D0110A":0, "D0110B":1,
  "D01S0D":"000000000000",
  "D0110F":3,
  "D01S12":"0.1.7",
  "D01213":0,
  "ProductId":"b3d240e5b11711ee88c206d016384e4a",
  "otacheck":false,
  "Runtime":161799392,
  "rssi":-67,
  "wifilog":false,
  "blelog":-1,
  "free_memory":95536,
  "WifiVersion":"AWS_Philips_AIR_Combo@86",
  "D03102":1, "D03105":0, "D0310A":1, "D0310C":2, "D0310D":2,
  "D0320F":23040, "D03110":0, "D03211":0, "D03130":0, "D0313B":20
}}}
```

## 3. D-Code → Bedeutung

### Gesichert (aus Cross-Reference mit der AC0650-Referenz-Config + Wert-Semantik)

| D-Code | Bedeutung | Wert (Fan1) | Nachweis |
|---|---|---|---|
| `D01S03` | device name / alias | `"Fan1"` | String = Gerätename aus App |
| `D01S04` | device type | `"Trident"` | String = interner Typ |
| `D01S05` | model / CTN | `"CX3550/01"` | String = Modellnummer |
| `D01S0D` | Seriennummer / device-id-Suffix | `"000000000000"` | String, MAC-nah (`mac` in deviceList, gleiches Format) |
| `D01S12` | firmware / swversion | `"0.1.7"` | String = `swversion` aus deviceList |
| `D0310C` | **fan speed / mode** | `2` | AC0650-Config: `fan_speed`+`mode` = `D0310C`; läuft auf Stufe 2 |
| `D0310D` | **power / fan level** | `2` | AC0650-Config: `power`+`fan_level` = `D0310D`; 0=off… |
| `Runtime` | uptime (Sekunden) | `161799392` | wächst monoton zw. zwei Reads (161799392→161800428) |
| `rssi` | WiFi-RSSI (dBm) | `-67` | typischer WiFi-Wert |
| `free_memory` | freier Heap (Bytes) | `95536` | Plausibel |
| `ConnectType` | online/offline | `"Online"` | Statusflag |
| `WifiVersion` | WiFi-FW-Version | `"AWS_Philips_AIR_Combo@86"` | String |
| `ProductId` | Produkt-ID | `b3d240e5…` | = `product_id` aus deviceList |

### Offen (Wert bekannt, Bedeutung unklar — der Funktions-Sweep muss sie klären)

Diese Codes hat ein einzelner Shadow-Read geliefert, aber ihre Semantik ist
**nicht** aus einem Read ableitbar — nur indem man am Lüfter jede Funktion
ändert und zuschaut, welcher Code sich ändert (der Sweep, der 2026-06-27 am
429-Rate-Limit scheiterte):

| D-Code | Wert (Fan1) | Verdachts-Bedeutung (zu verifizieren) |
|---|---|---|
| `D01102` | `2` | ? (D01xx = Gerätemeta-Bereich) — nicht nutzersteuerbar |
| `D01107` | `0` | ? — nicht nutzersteuerbar |
| `D01108` | `3` | ? — nicht nutzersteuerbar |
| `D01109` | `3` | ? — nicht nutzersteuerbar |
| `D0110A` | `0` | ? — nicht nutzersteuerbar |
| `D0110B` | `1` | ? — nicht nutzersteuerbar |
| `D0110F` | `3` | ? — nicht nutzersteuerbar |
| `D01213` | `0` | ? — nicht nutzersteuerbar |
| `D0310A` | `1` | ? — durch keine User-Aktion bewegt (Konfig/Feature-Flag) |
| `D03105` | `0`/`100` | **transienter Ack/Dirty-Flag** (kippt bei jeder Änderung, kein Property) |
| `D0313B` | `20` | konstant — durch nichts bewegt (Konfig/Hardware-Flag) |

> **Geklärt via Live-Sweep (siehe 3b/3c/3d):** `D0310C`=Modus/Speed-Preset
> (1/2/3/17/130), `D0310D`=Lüfterstufe (0–3), `D03102`=Power-Flag (0/1),
> `D0320F`=Oszillation (0/23040), `D03110`=Timer aktiv (0/2),
> `D03211`=Timer-Minuten (Countdown), `D03130`=Piepton (0/100).
> `D0313B=20` war die ursprüngliche Timer-Vermutung — falsch; konstanter Wert.

> CX3550 = Series-3000 Standventilator, **kein** Luftreiniger → erwartet: keine
> PM2.5/Filter-Codes (D03221/D0540x fehlen korrekterweise). Typische Fan-Funktionen
> die noch zugeordnet werden müssen: **Oszillation, Timer, Richtung, Naturmodus**.

## 3b. Live-Beobachtung (2026-06-27, eigene Verbindung)

Erfolgreicher Connect (CONNACK 0) mit `client_id` aus `mqttInfo` (`b16b2dff…`),
frischer pre-signed URL (`X-Amz-Date=20260627T131831Z`). Das Gerät pusht
`shadow/update/accepted` (mit `desired:null`) bei jeder eigenen Änderung — eine
manuelle Speed-Änderung 2→3 lieferte:

| D-Code | vorher | nachher | Schluss |
|---|---|---|---|
| `D0310C` | 2 | 3 | bestätigt: **Speed/Mode** (trackt Stufe) |
| `D0310D` | 2 | 3 | bestätigt: **Level/Power** (trackt Stufe mit) |
| `Runtime` | 164362528 | 164380958 | hochgezählt (uptime) |
| `rssi` | -68 | -63 | schwankt (WiFi) |

→ `D0310C` und `D0310D` ändern sich **gemeinsam** mit der Stufe. Für HA heißt das:
beide Codes spiegeln die aktuelle Fan-Stufe; ein Schreibbefehl geht vermutlich auf
einen der beiden (oder via NCP `to_ncp`-Topic — Control noch ungeklärt, siehe 4.).

### 3c. Natur-Modus & Timer/Oszillation geklärt (Live-Sweep 2026-06-27, ~15:30)

User-Korrelation: Lüfter an, **Modus Natur**, **Sweep an**, **Timer an**. Aktueller
`reported`-State dazu:

| deine Angabe | D-Code | Wert | Bedeutung (jetzt gesichert) |
|---|---|---|---|
| Lüfter **an** | `D0310D` | `2` | Level (Power): 0=aus, 1/2/3=Stufe |
| Modus **Natur** | `D0310C` | `-126` | **Natur-Modus = 130** (s.u.) |
| **Sweep** an | `D0320F` | `23040` | Oszillation: **23040=an, 0=aus** (Sweep-Aus-Sprung live beobachtet) |
| **Timer** an | `D03110` | `2` | Timer-aktiv-Flag: 0=aus, 2=an |
| Timer-Rest | `D03211` | `59` | Minuten-Countdown (60→59 beobachtet) |

**`D0310C = -126` ist KEIN Glitch** — es ist der fehlende Modus-Code. `-126`
als **signed int8 = `130` (`0x82`)**. Die AC0650-Referenz kannte Auto=1, Sleep=17,
Turbo=18 — **Achtung: CX3550 hat KEIN Turbo** (nur Stufe 1/2/3, Natürlich,
Schlafen). Turbo=18 gilt für andere Geräte, für CX3550 entfällt er. Damit ist
die komplette Modus-Tabelle geklärt:

| `D0310C` | Modus | live bestätigt |
|---|---|---|
| `1` / `2` / `3` | manuelle Stufe 1 / 2 / 3 | ✅ (2→3, Stufe 3=3) |
| `17` | Schlafen (Sleep) | ✅ |
| `130` (`-126`, `0x82`) | Natürlich (Breeze) | ✅ (re-bestätigt) |

→ Für HA: `D0310C` ist der **Modus/Speed-Preset**-Select (5 Werte), `D0310D`
die **Lüfterstufe** (0=aus…3), `D0320F` Oszillation (bool, Wert `23040`=an),
`D03110` Timer aktiv (bool), `D03211` Timer-Minuten (Zähler runter).

### 3d. Kontrollierte Verifikationsrunde (2026-06-27, ~15:42–15:48)

User-dirigierter Sweep („du sagst was, ich stelle ein, du verifizierst"):
je Aktion Ground-Truth vom User + Shadow-Auslese verglichen.

| Aktion (User bestätigt) | D-Code | vorher → nachher | Schluss |
|---|---|---|---|
| Power **AUS** | `D0310D` | 2 → 0 | ✅ Power-Level 0=aus |
| Power **AUS** | `D03102` | 1 → 0 | ✅ **`D03102` = Power-Flag** (1=an, 0=aus) |
| Power **AUS** | `D0310C` | 130 → 130 | Modus bleibt beim Aus-Schalten gespeichert |
| Power **AN** + Sleep | `D0310C` | 130 → 17 | ✅ Sleep=17 |
| Power **AN** | `D03102` | 0 → 1 | ✅ Power-Flag Roundtrip 1→0→1 |
| Stufe **3** | `D0310C`/`D0310D` | 17/1 → 3/3 | ✅ manuelle Stufe: beide Codes identisch |
| **Natürliche Brise** | `D0310C` | 3 → -126 (130) | ✅ Natur=130 re-bestätigt |
| Piepton **AUS** (User hört: kein Piep) | `D03130` | 100 → 0 | ✅ **`D03130` = Piepton** (0=aus) |
| Piepton **AN** (User hört: Piep) | `D03130` | 0 → 100 | ✅ Piepton 100=an — Roundtrip 0→100→0 |

**Neu geklärt in dieser Runde:** `D03102` (Power-Flag 0/1), `D03130` (Piepton 0/100).
Beide Roundtrips sauber (an→aus→an).

**Verbleibend offen (HA-irrelevant):** `D0310A=1`, `D0313B=20` — durch **keine**
User-Aktion bewegt (Power, alle Modi, Oszillation, Timer, Piepton). Vermutlich
interne Konfig-/Hardware-Flags, nicht nutzersteuerbar. `D03105` (0/100) ist ein
**transienter Ack/Dirty-Flag** (kippt bei jeder beliebigen Änderung, kein Property).

### 3e. Finale HA-Entity-Map (CX3550/01)

Alle Writes am Fan1-Lüfter verifiziert (`methodb/verify_writes.py` + `verify_two.py`,
2026-06-27): publish `desired` → `shadow/update/accepted` (Version hochgezählt) →
`shadow/get` Read-back verglichen. **Alle 6 Writes funktionieren**; ein Code ist
read-only.

| HA-Entität | D-Code(s) | Werte | Write-Verifikation |
|---|---|---|---|
| `fan` (An/Aus) | `D03102` | 1=an, 0=aus | ✅ verifiziert (Roundtrip 1→0→1, §3d) |
| `fan` (Stufe/Speed) | `D0310D` | 0–3 | ✅ verifiziert (Stufe 1/2/3, §3c) |
| `preset_mode` (Modus) | `D0310C` | 1/2/3/17/130 | ✅ Sleep=17, Natural=130 verifiziert |
| `oscillate` | `D0320F` | **SCHREIB 90 = an, 0 = aus**; gelesen 23040 = an | ✅ verifiziert (siehe 3f) |
| `switch` Piepton | `D03130` | 100=an, 0=aus | ✅ Beep ON=100 + OFF=0 verifiziert |
| `switch` Timer aktiv | `D03110` | 2=an, 0=aus | ✅ verifiziert: write 2 → reported timer_act=2 |
| `sensor` Timer Restminuten | `D03211` | Countdown int | ⚠ **READ-ONLY** — write `D03211=2` ignoriert; Gerät setzt beim Aktivieren (D03110=2) selbst auf 60 und zählt runter. → Sensor, keine Number. |

**Write-Ziel für alle Writes:** `$aws/things/<id>/shadow/update` mit
`{"state":{"desired":{<D-Code>:<wert>}}}`. Cloud bestätigt via
`shadow/update/accepted` (Version++, `StatusType` status→control→status), Gerät
spiegelt via `reported`.

### 3f. Oszillation: Schreib- vs. Lese-Wert (Korrektur 2026-06-27)

**Achtung — Lese- und Schreibwert von `D0320F` sind verschieden!**

- Gelesen: `23040` (= `0x5A00` = `90<<8`) = Schwenk **an**, `0` = aus.
- Geschrieben: **`90`** = an (Winkel in Grad), `0` = aus.
- Schreibt man `23040`, **lehnt das Gerät ab** — reported springt auf `0`
  (Oszillation aus). Getestet am Fan1-Lüfter (AN, Stufe 2/3):
  `write 90 → reported 23040` (schwenkt), `write 0 → reported 0` (stoppt),
  `write 23040 → reported 0` (abgelehnt), `write 1/2/100 → 0` (abgelehnt),
  `write 255 → 23040` (an, vermutlich Default-Winkel).

→ HA-Integration schreibt `D0320F=90` für `oscillate on`, liest `!= 0` für den
Status. (Früherer control_test „Beweis" mit Schreib 23040 war ein
Fehlschluss — damals vermutlich schon an.)

### 3g. Timer-Dauer geknackt: `D03110` = Stunden + 1 (2026-07-04)

`D03110` ist **nicht** nur ein An/Aus-Flag — der Wert kodiert die Timer-Dauer
direkt: **`D03110` = Stunden + 1** (0 = aus). Per Direct-Write am Fan1-Lüfter
verifiziert (kein App-Roundtrip nötig); `D03211` (Restminuten, read-only) folgt
als `60·(D03110−1)`:

| write `D03110` | reported `D03211` | = Dauer |
|---|---|---|
| 0  | 0    | aus |
| 2  | 60   | 1 h |
| 4  | 180  | 3 h |
| 6  | 300  | 5 h |
| 12 | 660  | 11 h |
| **13** | **720** | **12 h** ✅ |
| 24 | 1380 | 23 h (Firmware erlaubt mehr; App kappt bei 12 h) |

- `D03110 = 1` ist out-of-range → Gerät coerced auf `2`. Gültige An-Codes: 2..13.
- Deshalb konnte die alte Integration nur „1 h": ihr `TIMER_ON = 2` **ist** exakt
  1 h. Der frühere Befund „Gerät setzt beim Aktivieren selbst auf 60" war nur der
  Sonderfall Stunden = 1.
- `D03105` sprang bei Aktivierung 0→100, ist aber **kein** sauberer Indikator
  (blieb 100 auch nach `D03110=0`) → für den Timer irrelevant.

→ HA: neues `number` „Timer duration" (0–12 h) schreibt `D03110 = h+1` (0→0),
liest `h = D03110−1`. Der Timer-**Switch** liest jetzt `!= 0` (nicht `== 2`),
damit er bei jeder Dauer „an" zeigt. `D03211`-Sensor unverändert.

**Gotcha (HA-Deploy):** Ein Config-Entry-**Reload** reicht NICHT, um neue
Platforms / geänderte Module dieser Custom-Integration zu laden — die
Python-Module bleiben in `sys.modules` gecacht (die alte `PLATFORMS`-Liste ohne
`number` läuft weiter, ganz ohne Import-Error). Es braucht einen **vollen
HA-Neustart**.

1. **Funktions-Sweep neu laufen lassen** (das eigentliche Ziel): frische
   `mqttInfo`-URL besorgen (frida-Mitschnitt, 1h gültig) → mitschreibende
   Verbindung (`methodb/connect_shadow.py`) → am Lüfter je eine Funktion ändern
   (Power, Stufe 1/2/3, Oszillation an/aus, Timer) → Diff der `reported`-Codes
   → offene Tabelle oben ausfüllen. Das hätte 2026-06-27 geklappt, wenn nicht
   der Server-429-Sturm den `_sweep_capture.py`-Schreibvorgang gekillt hätte.
2. **air-matters Request-Signierung knacken** (ClientKey/ApiKey aus der APK) →
   dann kann HA die 1h-URL selbst refreshen. Siehe `notes/auth_refresh.md`.
3. **Control-Write testen**: `desired` mit `D0310C`/`D0310D` auf
   `$aws/things/<id>/shadow/update` publishen → Lüfter reagiert? (beweist
   Steuerung, nicht nur Lesezugriff).

   ✅ **ERLEDIGT 2026-06-27** (`methodb/control_test.py`, Fan1-Lüfter): `desired
   {"D0320F":0}` → Oszillation physisch gestoppt (User bestätigt); `desired
   {"D0320F":23040}` → Oszillation wieder gestartet. Cloud akzeptierte beide
   (`shadow/update/accepted`, Version hochgezählt, `StatusType` status→control→status).
   **Beide Richtungen (Lesen + Schreiben) bewiesen, standalone über geknackte
   Auth-Kette** (`airmatters_auth.py`). Siehe `notes/auth_refresh.md`.