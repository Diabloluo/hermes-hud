# Uninstall — Hermes HUD Desktop (macOS)

> This page describes the published Hermes HUD Desktop 0.1.0. The renamed 驿览 · RelayGlance 0.1.1 is not yet released; see the [candidate upgrade guide](UPGRADE_RELAYGLANCE.md).

1. Quit Hermes HUD (menu bar tray → **Quit**).
2. Drag `Hermes HUD` from Applications to Trash (or right-click → Move to
   Trash).
3. Optional: remove settings/preferences if you want a full clean removal:

   - `~/Library/Application Support/com.diabloluo.hermes-hud-desktop/`
   - `~/Library/Preferences/com.diabloluo.hermes-hud-desktop.plist`
   - `~/Library/Caches/com.diabloluo.hermes-hud-desktop/`

   > Use Finder → Go → Go to Folder for these paths, or Terminal
   > (advanced) if you prefer.

## What uninstalling the Desktop app does NOT do

- Does **not** remove Hermes Agent.
- Does **not** remove the Hermes HUD plugin (Web dashboard keeps working).
- Does **not** touch your Hermes data (state.db, memories, skills, cron).
- Does **not** stop a Dashboard it started — Hermes Dashboard is a shared
  service that may be used by the browser HUD too; the app only *starts*
  it, it does not own or kill it on quit.
