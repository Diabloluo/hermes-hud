# Upgrade to 驿览 · RelayGlance Desktop 0.1.1

**Preparation for the unreleased 0.1.1 candidate.** Follow this procedure
only after a verified, signed/notarized 0.1.1 download is published. The
current 0.1.0 release is still named Hermes HUD.

## What changes

The new application is `驿览 · RelayGlance.app`, using the approved radar
icon. The new DMG is `RelayGlance-Desktop-0.1.1-macOS-arm64.dmg`.
The bundle ID stays `com.diabloluo.hermes-hud-desktop`; preferences, caches
and application support paths retain that identity. The Hermes Agent,
Dashboard plugin, `/hud`, configuration and observed data are not renamed.

## Upgrade checks

1. Keep the existing verified 0.1.0 installer or a recoverable copy of
   `Hermes HUD.app`. Record its version and the exact existing location.
2. Finish active work and quit **only the old Desktop app** with its tray
   Quit command. Do not stop Hermes Agent or its shared Dashboard service.
3. Open the verified 0.1.1 DMG and drag `驿览 · RelayGlance.app` into
   Applications. The different filename will not replace `Hermes HUD.app`.
4. Move the old app to a clearly marked backup location outside Applications
   or to recoverable Trash, retaining the verified old installer. Both apps
   have the same bundle ID; do not keep two active launch targets.
5. Launch the new app from Applications. Check the radar icon, full name,
   0.1.1 setup/about label, tray Open/Retry/Quit, close-to-tray and second
   launch behavior. Replace an old Dock shortcut with the new app if needed.
6. Confirm the same plugin/settings/data are visible. Test already-running
   Dashboard, stopped Dashboard recovery and incompatible plugin behavior
   in an isolated test setup without interrupting real user work.

No preference deletion, cache purge, launchd change, credential export,
quarantine removal or Gatekeeper bypass is part of this procedure.

## Roll back if needed

Quit only the new Desktop app, move it to a recoverable backup location or
Trash, restore `Hermes HUD.app` from the saved 0.1.0 copy/verified installer,
and launch it. Leave all Hermes data, plugin files and identity-based
preferences untouched. Do not report a rollback as successful until the
old app is actually running and its version and connection have been checked.

## Uninstall the new app

Quit it and move `驿览 · RelayGlance.app` from Applications to Trash. The
existing [uninstall data-path notes](UNINSTALL_MACOS.md) still apply because
the bundle ID is unchanged. Removing the Desktop app does not stop or remove
the shared Hermes Dashboard, Hermes Agent or the Web plugin.
