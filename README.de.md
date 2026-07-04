# Philips Air+ (CX3550/01) für Home Assistant

[🇬🇧 English](README.md) | 🇩🇪 Deutsch

<img src="https://raw.githubusercontent.com/Ka3seBr0t/HA_Philips_Air_Plus/main/brand/logo.png" alt="Philips Air+ Integrations-Icon" width="96" height="96">

[![Öffne deine Home-Assistant-Instanz und öffne ein Repository in der Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Ka3seBr0t&repository=HA_Philips_Air_Plus&category=integration)

Eine Home-Assistant-Custom-Integration für **Philips-Air+-Cloud-only-Ventilatoren**,
verifiziert am **CX3550/01** (Standventilator "Series 3000", Air-Matters-App).
Diese Ventilatoren haben keine lokale API — sie werden über ein AWS-IoT-Device-Shadow
per MQTT-over-WSS gesteuert, hinter Philips' clientseitig signierter *air-matters/gaoda*-
Auth-Kette.

> **Nicht** die Upstream-Versuni/HomeID-Integration (z.B.
> `ShorMeneses/philips-airplus-homeassistant`). Die liefert "no devices
> found" für den CX3550 — sie zielt auf ein anderes Backend (die
> AC-Luftreiniger-Linie). Diese Integration spricht das tatsächliche
> Cloud-Protokoll des Ventilators.

## Haftungsausschluss

*Inoffiziell, nicht mit Philips/Versuni verbunden. Markennamen werden nur
beschreibend verwendet, um kompatible Geräte zu identifizieren. Diese
Integration betreibt Reverse Engineering ausschließlich zur Interoperabilität
mit dem eigenen Gerät (§§69e, 69g UrhG; Richtlinie 2009/24/EG Art. 6 & 8;
§3 GeschGehG). Keine App-Konstanten, keine dekompilierte APK und keine
persönlichen Daten werden veröffentlicht oder weitergegeben. Jeder Nutzer
extrahiert den Signierwert aus seiner eigenen, rechtmäßig erworbenen Kopie
der App.* Dies ist **keine Rechtsberatung**.

## Warum du eine APK bereitstellen musst

Das Cloud-Backend dieses Ventilators braucht einen clientseitigen
HMAC-Signierwert (`mSecret`), den Philips ausschließlich in der eigenen App
einbettet — es gibt keine API, keinen Konfigurations-Endpunkt und keinen
Account-Flow, der ihn herausgibt. Der einzige Weg, ihn zu bekommen, ist die
Extraktion aus einer Kopie der App, zu deren Nutzung du berechtigt bist —
genau wie bei jedem anderen Interoperabilitäts-Tool.

Dieses Repo liefert diesen Wert daher **niemals mit**. Stattdessen extrahiert
die Integration ihn lokal aus einer APK, die **du** beim Setup bereitstellst,
und speichert ihn ausschließlich in deiner eigenen Home-Assistant-Instanz.
Nichts wird irgendwohin hochgeladen. Siehe
[`custom_components/philips_airplus/apk_extract.py`](custom_components/philips_airplus/apk_extract.py)
für die (winzige, abhängigkeitsfreie) Extraktions-Logik.

## Einrichtung

### 1. Installation via HACS

Klick auf den "In HACS öffnen"-Button oben (fügt dieses Repository
automatisch zu HACS hinzu), installier dann "Philips Air+" aus HACS. Oder
füg es manuell als HACS-Custom-Repository hinzu, oder kopier
`custom_components/philips_airplus/` in deinen HA-Ordner
`config/custom_components/`. Home Assistant neu starten.

### 2. Integration hinzufügen

**Einstellungen → Geräte & Dienste → Integration hinzufügen → "Philips Air+"**, dann:

1. **Lade die Philips-Air+-APK hoch** (`com.philips.ph.homecare`). Jede
   dieser Quellen funktioniert — der Signierwert ist über App-Versionen/
   Regionen hinweg identisch:
   - **Am saubersten / vertrauenswürdigsten:** vom eigenen Handy ziehen —
     `adb shell pm path com.philips.ph.homecare`, dann `adb pull <path>`.
   - **Bequem:** von [APKMirror, Version 3.19.0](https://www.apkmirror.com/apk/versuni-netherlands-b-v/philips-air/philips-air-3-19-0-release/)
     (Juni 2026) im Browser herunterladen. Falls der Link bei dir 404
     liefert, hat Philips eine neuere Version veröffentlicht — nutz
     stattdessen die [App-Übersichtsseite](https://www.apkmirror.com/apk/versuni-netherlands-b-v/philips-air/),
     die immer die aktuelle Version listet. Die Integration liest nur
     Text-Strings aus der Datei — sie führt sie nie aus — aber das eigene
     Gerät ist trotzdem die vertrauenswürdigste Quelle.
2. **Gib deine Philips-Konto-E-Mail ein.** Du bekommst einen 6-stelligen
   Code per E-Mail.
3. **Gib den Code ein.** Die Integration meldet sich an, entdeckt deine
   gebundenen Geräte und legt den Eintrag an.

Das war's — kein Passwort, keine manuellen IDs, nichts, was aus
Traffic-Mitschnitten rausgesucht werden müsste.

## Was du bekommst (pro Ventilator)

| Entität | Plattform | Steuert / zeigt |
|---|---|---|
| Ventilator | `fan` | An/Aus, Stufe 1/2/3 (Prozent), Presets **Schlafen** / **Natürlich**, Oszillation |
| Piepton | `switch` | Tastenton An/Aus (Konfiguration) |
| Timer | `switch` | Auto-Aus-Timer An/Aus (Konfiguration) |
| Timer-Dauer | `number` | Auto-Aus-Timer-Länge, 0–12 h (Konfiguration) |
| Timer-Restzeit | `sensor` | Countdown in Minuten (nur lesbar) |
| Signalstärke | `sensor` | WiFi-RSSI in dBm (Diagnose, standardmäßig aus) |
| Laufzeit | `sensor` | Geräte-Laufzeit in Sekunden (Diagnose, standardmäßig aus) |
| Freier Speicher | `sensor` | Freier Heap in Bytes (Diagnose, standardmäßig aus) |

Alle Steuer-Writes sind an einem physischen CX3550/01 verifiziert: An/Aus,
Stufe 1/2/3, Schlafen-/Natürlich-Presets, Oszillation, Piepton, Timer An/Aus
und -Dauer.

## Fehlerbehebung

- **"Could not find the signing value in that file"** — stell sicher, dass
  du die Philips-Air+-/Philips-HomeCare-APK selbst hochgeladen hast, nicht
  einen Sprach-/Density-only-Split. Die Basis-APK (oder ein `.apkm`-/
  `.xapk`-Bundle, das sie enthält) wird gebraucht.
- **"Authentication failed against the Philips cloud"** — selten, aber
  manche APK-Varianten/Regions-Builds können abweichen. Probier eine andere
  Quelle für die APK (z.B. das eigene Gerät via `adb pull` statt einer
  Mirror-Seite).
- **Schließ die Philips-Handy-App, während Home Assistant verbunden ist.**
  Halten beide eine Verbindung mit derselben Client-Identität, trennt AWS
  IoT eine davon (`rc 128`); HA macht Backoff und verbindet neu, aber die
  App kämpft weiter dagegen an.
- Auth-Fehler im laufenden Betrieb (z.B. Account-Änderungen) lösen
  automatisch einen Reauth-Flow aus — E-Mail/Code erneut in der UI eingeben.

## Repository-Aufbau

```
custom_components/philips_airplus/   die Integration (das, was HACS installiert)
notes/                                bereinigte RE-Prozess-Notizen (keine Secrets/persönlichen Daten)
```

Dekompilierte APK-Inhalte, RE-Tooling und rohe Netzwerk-Mitschnitte aus der
Entwicklung sind gitignored und nie Teil der Repository-History.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
