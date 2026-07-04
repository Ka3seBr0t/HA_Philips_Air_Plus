# Changelog

All notable changes to this integration are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
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

### Changed
- Fan `preset_mode` display is now localized via `translation_key` — shows
  "Sleep"/"Natural breeze" (EN) or "Schlafen"/"Natürliche Brise" (DE) in the
  UI while the underlying `preset_mode` values used in automations/scripts
  stay the stable `sleep`/`natural` strings.
- APK download link points directly to the current APKMirror version page
  (verified live) instead of only the generic overview page, with a documented
  fallback once that specific version page eventually 404s.

### Added
- `brand/` folder: `icon.png`/`icon@2x.png`/`logo.png`/`logo@2x.png`
  (256²/512², transparent background) plus the original `source.png`,
  ready for an eventual `home-assistant/brands` submission. Root README now
  shows the logo.

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
