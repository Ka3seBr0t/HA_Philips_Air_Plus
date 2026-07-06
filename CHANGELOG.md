# Changelog

All notable changes to this integration are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.2] - 2026-07-06

### Fixed
- Physical / device-side state changes (speed, mode, power set on the unit
  itself) now sync to Home Assistant within ~30 s. The integration is a pure
  push model over the AWS IoT device shadow, and the Philips cloud doesn't
  reliably deliver `shadow/update/documents` pushes for physical changes; a
  periodic `shadow/get` reconcile poll was added to pull the current reported
  state. Push remains the primary path; the poll is a safety net.

## [0.3.1] - 2026-07-04

### Added
- HACS Action + hassfest CI validation (`.github/workflows/validate.yaml`),
  required for eventual `hacs/default` submission.

### Fixed
- `manifest.json` keys weren't alphabetically sorted (hassfest requirement:
  `domain`/`name` first, then alphabetical).
- Config flow description embedded raw URLs, which hassfest's translation
  linter rejects. Points to the README instead.

## [0.3.0] - 2026-07-04

### Added
- **12-hour auto-off timer** via a new `number` entity ("Timer duration",
  0–12 h). The duration is encoded directly in `D03110` as `hours + 1`
  (2 = 1 h … 13 = 12 h; 0 = off), verified by live shadow write + read-back
  (`D03110=13` → 720 min remaining; remaining = 60·(D03110−1)). Previously the
  only timer control was the on/off switch, which always wrote the 1 h default.
  The switch now reflects any running duration (on = `D03110 ≠ 0`) and the
  `number` entity sets the length; the read-only remaining-minutes sensor is
  unchanged.
- `brand/` folder: `icon.png`/`icon@2x.png`/`logo.png`/`logo@2x.png`
  (256²/512², transparent background) plus the original `source.png`. Shown
  at repo root for the README logo, and duplicated into
  `custom_components/philips_airplus/brand/` so the icon shows up directly
  in the Home Assistant UI (local brand images, supported since HA 2026.3.0
  — no `home-assistant/brands` submission needed).
- German README (`README.de.md`) alongside the English one, with a
  language-switcher link at the top of each.
- "Open in HACS" badge in the README for one-click repository setup.

### Changed
- Fan `preset_mode` display is now localized via `translation_key` — shows
  "Sleep"/"Natural breeze" (EN) or "Schlafen"/"Natürliche Brise" (DE) in the
  UI while the underlying `preset_mode` values used in automations/scripts
  stay the stable `sleep`/`natural` strings.
- APK download link points directly to the current APKMirror version page
  (verified live) instead of only the generic overview page, with a documented
  fallback once that specific version page eventually 404s.

### Fixed
- **Intermittent connection failures from a transient `mqttInfo` error**: the
  Philips backend sporadically returns code `16002` "Not binding to the device"
  even for correctly-bound devices (`deviceList` confirms the binding). It now
  retries this like a 503 instead of treating it as a hard failure.
- **Config flow crash on start** (`AttributeError: property '_reauth_entry_id' of
  'PhilipsAirplusConfigFlow' object has no setter`): a newer Home Assistant
  Core version reserves `_reauth_entry_id` as a read-only property on the
  `ConfigFlow` base class. Renamed our own bookkeeping attribute to
  `_philips_reauth_id` to avoid the collision.
- **APK upload step failing**: `manifest.json` was missing the
  `file_upload` dependency required by any integration using a `FileSelector`
  in its config flow. Added `"dependencies": ["file_upload"]`.
- **Entities showed "available" but couldn't be controlled** when the
  physical fan itself was offline (only visible via the Philips app showing
  "not available"): `available` only checked whether *our own* MQTT socket
  reached the AWS IoT broker, which succeeds independently of whether the
  device itself is connected. Added `PhilipsAirplusCoordinator.device_available`,
  which additionally checks the shadow's own `ConnectType` field once a
  reported state has arrived; `fan`/`switch`/`sensor` entities and
  `diagnostics.py` now use it instead of the raw socket-connected flag.
- Integration README's "Notes / gotchas" still described the old
  `user_id`-only reauth flow (leftover from before the config flow rewrite);
  updated to describe the actual email+OTP reauth behavior.
- Grammar fix (comma splice) in the German APK-step description.

## [0.2.0] - 2026-07-02

Initial public release.

- Email + OTP setup flow: upload your own Philips Air+ APK (mSecret extracted
  locally via `apk_extract.py`, never committed to the repo), sign in with
  email + one-time code (`oneid_login.py` derives the gaoda `user_id` directly
  from the Gigya OTP login response — no OAuth/PKCE dance needed).
- `fan`, `switch` (beep, timer), `sensor` (timer remaining, RSSI, uptime,
  free memory) entities for the CX3550/01, driven by a persistent
  MQTT-over-WSS device-shadow connection.
- Repo hardened for publication: no decompiled APK, no RE tooling, no
  personal identifiers or account secrets in git history.
