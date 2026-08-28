# Troubleshooting — Hermes HUD Desktop

> Terminal commands below are for **advanced diagnostics** only. Normal
> users don't need Terminal.

## "Hermes Dashboard not detected"

- Make sure Hermes Agent is installed and the HUD plugin is enabled.
- If Hermes is installed but the Dashboard isn't running, the app offers
  **Start Hermes Dashboard** (or menu-bar tray → Retry Connection after
  starting it yourself).

## "Hermes Agent not found"

- The app looks for Hermes in your PATH and common install locations. If
  Hermes is installed somewhere unusual, add it to your PATH and retry.
- Installing Hermes HUD Desktop does **not** install Hermes Agent — you
  need Hermes separately.

## "插件版本不兼容" / incompatible plugin

- Desktop requires HUD plugin ≥ 1.1.1 (API schema 1). The first official
  HUD release providing this contract is **v1.1.1** — if you installed the
  plugin from the `v1.1.0` tag, upgrade to `v1.1.1` (install command pins
  `--branch v1.1.1`), restart the Dashboard, then Retry.

## Dashboard won't start

- Check the Dashboard port is free (`127.0.0.1:9119` by default). If
  another process uses it, the app will not start a second Dashboard —
  resolve the conflict and retry.
- Advanced diagnostics:
  ```
  hermes dashboard --host 127.0.0.1 --port 9119 --no-open
  ```
  and open the browser HUD at http://127.0.0.1:9119/hud to see if the
  Web HUD works (if it does, the backend is fine).

## Tray / menu-bar icon

- Close button hides the window to the tray; use **Open Hermes HUD** to
  bring it back and **Quit** to exit.

## Logs

- The app writes no user-facing log files by default. For deep diagnostics
  run the binary from Terminal and observe stdout/stderr.

## Still stuck?

- Open an issue: https://github.com/Diabloluo/hermes-hud/issues
- Or start a Discussion: https://github.com/Diabloluo/hermes-hud/discussions
