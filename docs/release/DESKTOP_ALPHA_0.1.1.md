# 驿览 · RelayGlance Desktop Alpha 0.1.1 — source candidate

**Not released. No new binary is claimed by this source change.**

Desktop 0.1.0 remains the published Hermes HUD Desktop release. Do not
replace its tag, app, DMG, checksums or historical release notes.

## Changes

- Native app, window, setup page, tray menu and tooltip adopt
  **驿览 · RelayGlance**, with “Formerly Hermes HUD” on the setup page.
- The user-selected radar replaces Observer Core in the app icon, ICNS,
  setup image and monochrome menu-bar mark.
- Fix the tray builder overwriting its template icon with the default
  full-color app icon. No connection/recovery behavior is otherwise changed.
- New Desktop version 0.1.1, independently versioned from the Web plugin.

## Identity and data stay stable

The bundle ID is still `com.diabloluo.hermes-hud-desktop`; the executable
and Cargo package are still `hermes-hud-desktop`. Plugin ID `hermes-hud`,
`/hud`, `/api/plugins/hermes-hud`, schema 1, configuration and data locations
are unchanged. No agent install, service restart, security setting change,
auto-updater or data migration is part of this candidate.

## Intended artifacts, after all release gates pass

- `驿览 · RelayGlance.app`
- `RelayGlance-Desktop-0.1.1-macOS-arm64.dmg`
- `SHA256SUMS.txt` containing the exact new DMG filename

The updated bundle verifier checks the canonical filename, checksum,
arm64 architecture, bundle/display/executable identities, version, exact
radar ICNS bytes, Applications symlink and absence of test hooks. Its
successful result is explicitly **unsigned verification scope only**.
Use the old release tag's verifier for the historical 0.1.0 DMG.

## Checks required before release

All [Go/No-Go gates](DESKTOP_ALPHA_GO_NO_GO.md) remain required. In particular:

1. Pin the final source commit and pass main, fresh-install and Desktop CI.
2. Build the real public arm64 app/DMG on macOS with test hooks disabled;
   check the negative-string proof and the new bundle verifier.
3. Verify Developer ID signature, Hardened Runtime, notarization Accepted,
   stapling and the real downloaded-file Gatekeeper path. Do not bypass it.
4. Visually inspect Finder, Dock, app menu, window title, setup screen and
   light/dark menu bars, including Retina displays. Verify `iconutil`
   decodes the new ICNS. Cloud PNG/container checks do not prove macOS rendering.
5. Test clean install and 0.1.0 upgrade/rollback, including the same-bundle-ID
   filename transition and second-instance behavior. Never run duplicate old
   and new app copies as if they were independent applications.
6. Recheck connection/recovery/incompatibility behavior separately. This
   rebrand does not certify or fix earlier blank-window or incorrect
   “Dashboard not running” reports.

Use the [upgrade and rollback plan](../desktop/UPGRADE_RELAYGLANCE.md).
Build caches, packaging temporaries and logs must use a verified external
work disk when internal storage is limited. Coordinate the build slot before
starting native compilation; this source change does not start a build,
modify an installed app or publish a release.
