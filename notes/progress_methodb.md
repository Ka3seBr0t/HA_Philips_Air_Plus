# Method B — Fortschritts-Log

Stand: 2026-06-26

## Kontext

Ziel: Philips CX3550/01 Standventilator (Series 3000, Air+) in Home Assistant
einbinden. Auth & Transport sind geklärt (`notes/architecture.md`). Der fehlende
Baustein ist der gerätespezifische `thingName` (`da-<uuid>`) + die Property-Map.

## Bisher gemacht

### 1. Projekt kennengelernt
- Vollständiger Read von `README.md`, `methodb/README.md`, `notes/architecture.md`,
  `scripts/shadow_dump.py`, `scripts/analyze_capture.py`, `methodb/*`, `.env.example`,
  `.gitignore`.
- Status festgestellt: Phase 0 (Architektur) + Phase 1 (Capture-Tool) erledigt;
  Phasen 1-Lauf, 2 (Property-Map), 3 (HA-Eintrag) offen. `notes/properties.md`
  existiert noch nicht.

### 2. IST-Stand über `shadow_dump.py` geprüft (read-only)
- Token ist für App `airplus` gecacht (`scripts/.tokens.json`) → kein `.env`/OTP nötig.
- Lauf: `scripts/shadow_dump.py --list-only --debug`
- Ergebnis (bestätigt die Method-B-Annahme):
  - `GET /user/self/device` → **`[]`** (Ventilator steht NICHT in der IoT-Device-Liste
    des Accounts).
  - HomeID-Backend (`backend.vbs.versuni.com` profile) → **HTTP 401** (Air+-Token gilt
    nicht für die HomeID-HAL).
  - `[IoT /device] 0 device(s) | [HomeID appliances] 0 appliance(s)` → 0 Kandidaten.
- Schluss: Der `thingName` ist nur client-seitig im Air+-App-Pairing bekannt. → Method B
  (App-Traffic abfangen) ist nötig.

### 3. Entscheidung: Handy statt Emulator
- Setup des Nutzers: echtes **Samsung S26 Ultra** (`SM-S948B`, schon mit dem Ventilator
  gepairt) + **HTTP Toolkit**.
- Empfehlung: **Handy**, weil die Gerätesichtbarkeit (Punkt 2 der zwei Schwierigkeiten)
  dort schon gelöst ist; der Emulator hätte das offene Risiko „frischer Login zeigt keine
  Ventilatoren + physischen Lüfter nicht neu paaren können".
- Einziges Risiko am Handy: nicht gerootet (Knox) → nur User-CA → Air+ App pinnt evtl.
  → Test in 5 min, mit sauberem Plan B.

### 4. Werkzeuge vorbereitet
- **platform-tools** aus `Downloads/platform-tools-latest-windows.zip` entpackt nach
  `C:\Users\user\platform-tools\` (enthält `adb.exe` v1.0.41 / 37.0.0).
- Ordner **dauerhaft zum Benutzer-PATH** hinzugefügt, damit HTTP Toolkit adb findet.
- Handy per USB verbunden, USB-Debugging aktiviert, ADB-Autorisierungs-Popup bestätigt:
  - `adb devices -l` → `SERIAL0000  device  product:m3qxeea model:SM-S948B ...`
  - (vorher: `unauthorized` → nach Bestätigung: `device`).

### 5. HTTP Toolkit verbinden — OFFEN / blockiert
- HTTP Toolkit installiert; PATH gesetzt nach vollständigem Neustart von HTTP Toolkit.
- **Aktuell hängts:** die HTTP-Interception kommt nicht zustande (Nutzer-Rückmeldung
  „geht nicht, weil ich nicht http interception [habe/rd]“). Genauer Zustand noch
  unklar — muss geklärt werden (siehe „Nächste Schritte“).

## Nächste Schritte

1. HTTP-Interception in HTTP Toolkit klären:
   - HTTP Toolkit komplett beenden (auch Tray) und neu starten, damit PATH greift.
   - „Android device via ADB" klicken → Companion-App + VPN + CA aufs Handy pushen.
   - Auf „Connected · Intercepting" achten; Handy-Popups (VPN, CA) bestätigen.
2. Wenn verbunden: Air+ App öffnen (Login mit eigenem Account + Mail-Code falls
   abgemeldet), Ventilator öffnen, Einstellung ändern (Speed 1→2→3, Oszillation).
3. In HTTP Toolkit Filter auf `versuni` → Traffic zu
   `prod.eu-da.iot.versuni.com` / `ats.prod.eu-da.iot.versuni.com` suchen.
4. HAR exportieren → `methodb/extract_things.py` darauf → `da-<uuid>` thingName.
5. `scripts/shadow_dump.py --thing da-<uuid>` → physischer Function-Sweep →
   `scripts/analyze_capture.py` → `notes/properties.md` → HA-Model-Eintrag.

## Offene Risiken / Plan B

- **Pinning** (App lädt nicht / kein `versuni`-Traffic bei „Connected"): nicht-gerootetes
  Samsung kriegt nur User-CA → App vertraut vermutlich nur System-CAs + pinnt.
  Plan B: frida-Bypass (`methodb/frida_unpin.js`, braucht root/frida-server) oder
  Emulator als letzte Reserve (System-CA, aber evtl. kein Lüfter sichtbar).
- **App zeigt gar keine Ventilatoren** nach frischem Login: Pairing ist geräte-lokal →
  muss am gepairten Handy bleiben; ggf. Account/Pairing-Setup koordinieren.

## Optionale Lotterie (übersprungen)

- `scripts/shadow_dump.py --app homeid --list-only --debug` könnte mit einem HomeID-Token
  statt 401 eine 200 + die Appliance-Liste (evtl. mit thingName) liefern → ganz ohne MITM.
  Niedrige Wahrscheinlichkeit (HomeID listet eher Küchengeräte); falls die Handy-Route
  dauerhaft blockt, als nächstes ausprobieren.

## Artefakte / Pfade
- Capture-Tool: `scripts/shadow_dump.py` (Token-Cache: `scripts/.tokens.json`, app=airplus)
- Analyse: `scripts/analyze_capture.py`
- Method-B-Tools: `methodb/mitm_capture.py`, `methodb/extract_things.py`,
  `methodb/frida_unpin.js`
- Capture-Landing: `captures/raw_shadow.jsonl` (noch nicht vorhanden)
- ADB: `C:\Users\user\platform-tools\adb.exe`