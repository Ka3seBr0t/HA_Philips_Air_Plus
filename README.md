# Philips Air+ (CX3550/01) for Home Assistant

🇬🇧 English | [🇩🇪 Deutsch](README.de.md)

<img src="https://raw.githubusercontent.com/Ka3seBr0t/HA_Philips_Air_Plus/main/brand/logo.png" alt="Philips Air+ integration icon" width="96" height="96">

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Ka3seBr0t&repository=HA_Philips_Air_Plus&category=integration)

A Home Assistant custom integration for **Philips Air+ cloud-only fans**,
verified against the **CX3550/01** ("Series 3000" stand fan, Air Matters app).
These fans have no local API — they're controlled via an AWS IoT device
shadow over MQTT-over-WSS, behind Philips' client-signed *air-matters/gaoda*
auth chain.

> **Not** the upstream Versuni/HomeID integration (e.g.
> `ShorMeneses/philips-airplus-homeassistant`). That one returns "no devices
> found" for the CX3550 — it targets a different backend (the AC air-purifier
> line). This integration speaks the fan's actual cloud protocol.

## Disclaimer

*Unofficial, not affiliated with Philips/Versuni. Trademarks are used only
descriptively to identify compatible devices. This integration performs
reverse engineering solely for interoperability with your own device (EU
UrhG §§69e, 69g; Directive 2009/24/EC Art. 6 & 8; GeschGehG §3). No app
constants, no decompiled APK, and no personal data are published or
distributed. Each user extracts the signing value from their own, lawfully
acquired copy of the app.* This is **not legal advice**.

## Why you need to provide an APK

This fan's cloud backend requires a client-side HMAC signing value
(`mSecret`) that Philips embeds only inside their own app — there is no API,
config endpoint, or account flow that hands it out. The only way to get it is
to extract it from a copy of the app you're entitled to use, the same way any
interoperability tool would.

This repo therefore **never ships that value**. Instead, the integration
extracts it locally from an APK **you** provide, during setup, and stores it
only in your own Home Assistant instance. Nothing is uploaded anywhere.
See [`custom_components/philips_airplus/apk_extract.py`](custom_components/philips_airplus/apk_extract.py)
for the (tiny, dependency-free) extraction logic.

## Setup

### 1. Install via HACS

Click the "Open in HACS" badge above (adds this repository to HACS
automatically), then install "Philips Air+" from HACS. Or add it manually as
a HACS custom repository, or copy `custom_components/philips_airplus/` into
your HA `config/custom_components/` folder. Restart Home Assistant.

### 2. Add the integration

**Settings → Devices & Services → Add integration → "Philips Air+"**, then:

1. **Upload the Philips Air+ APK** (`com.philips.ph.homecare`). Any of these
   work — the signing value is the same across app versions/regions:
   - **Cleanest / most trustworthy:** pull it from your own phone —
     `adb shell pm path com.philips.ph.homecare` then `adb pull <path>`.
   - **Convenience:** download it from
     [APKMirror, version 3.19.0](https://www.apkmirror.com/apk/versuni-netherlands-b-v/philips-air/philips-air-3-19-0-release/)
     (June 2026) in your browser. If that link 404s by the time you read
     this, Philips has shipped a newer version — use the
     [app overview page](https://www.apkmirror.com/apk/versuni-netherlands-b-v/philips-air/)
     instead, which always lists whatever is current. The integration only
     reads text strings out of the file — it never executes it — but your
     own device is still the most trustworthy source.
2. **Enter your Philips account email.** You'll get a 6-digit code by email.
3. **Enter the code.** The integration signs in, discovers your bound
   devices, and creates the entry.

That's it — no password, no manual IDs, nothing to look up in traffic
captures.

## What it gives you (per fan)

| Entity | Platform | Controls / shows |
|---|---|---|
| Fan | `fan` | on/off, speed 1/2/3 (percentage), presets **sleep** / **natural**, oscillate |
| Key beep | `switch` | key-tone on/off (config) |
| Timer | `switch` | auto-off timer on/off (config) |
| Timer duration | `number` | auto-off timer length, 0–12 h (config) |
| Timer remaining | `sensor` | countdown minutes (read-only) |
| Signal strength | `sensor` | WiFi RSSI dBm (diagnostic, off by default) |
| Uptime | `sensor` | device runtime seconds (diagnostic, off by default) |
| Free memory | `sensor` | free heap bytes (diagnostic, off by default) |

All control writes are verified against a physical CX3550/01: power, speed
1/2/3, sleep/natural presets, oscillate, beep, timer on/off and duration.

## Troubleshooting

- **"Could not find the signing value in that file"** — make sure you
  uploaded the Philips Air+ / Philips HomeCare APK itself, not a
  language/density-only split. The base APK (or a `.apkm`/`.xapk` bundle
  containing it) is what's needed.
- **"Authentication failed against the Philips cloud"** — rare, but some APK
  variant/region builds may differ. Try a different source for the APK (e.g.
  your own device via `adb pull` instead of a mirror site).
- **Close the Philips phone app while Home Assistant is connected.** If both
  hold a connection with the same client identity, AWS IoT disconnects one
  (`rc 128`); HA backs off and reconnects, but the app will keep fighting it.
- Auth failures during normal operation (e.g. account changes) trigger a
  reauth flow automatically — re-enter your email/code in the UI.

## Repository layout

```
custom_components/philips_airplus/   the integration (what HACS installs)
notes/                                sanitized RE process notes (no secrets/personal data)
```

Decompiled APK contents, RE tooling, and raw network captures used during
development are gitignored and never part of this repository's history.

## License

MIT — see [LICENSE](LICENSE).
