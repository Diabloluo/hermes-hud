# experiments/desktop-alpha — Hermes HUD Desktop Prototype (Tauri 2)

Desktop Foundation v0.1 prototype. **Not a release.** Local unsigned .app only.

## Security invariant (MUST NOT REGRESS)

Remote HUD WebView (`http://127.0.0.1:<port>/hud`) has **ZERO Tauri capabilities**:

| Surface | Grant |
|---|---|
| Tauri IPC (`invoke`) | NONE |
| shell | NONE |
| filesystem | NONE |
| native commands | NONE |
| updater | NONE |
| dialog | NONE |

- `capabilities/default.json` is an **empty permission set**.
- The `/hud` page talks to the Dashboard like a normal browser: `fetch` /
  `WebSocket` / `localStorage` — plain HTTP(S)/WS to `127.0.0.1`.
- No Tauri HTTP plugin capability is granted to the remote URL.
- The native Rust shell exposes **no command bridge** to the page.

## Behavior

- Startup: window loads bundled `assets/fallback.html`; a Rust thread probes
  `http://127.0.0.1:9119/api/plugins/hermes-hud/health`.
- Dashboard up + `api_schema_version==1` + `plugin_version>=1.1.0` →
  navigate to `http://127.0.0.1:9119/hud`.
- Not detected / incompatible → stay on fallback with reason; **Retry** is a
  plain `location.href` back to the Dashboard URL (no IPC needed).
- Tray: **Open Hermes HUD** / **Quit**. Close button hides to tray.
- Navigation guard: only `127.0.0.1` / `localhost` / `tauri://`; external
  origins are blocked.

## Build & run

```bash
source "$HOME/.cargo/env"
cargo build --release          # first build compiles the whole Tauri stack
./target/release/hermes-hud-desktop
```

Requires: Rust stable (rustup), Xcode Command Line Tools, macOS WKWebView.
Dashboard must run with `hermes dashboard --host 127.0.0.1 --port 9119 --no-open`
for the HUD view (fallback screen otherwise).

## Compatibility contract

Probed from `/health`: `api_schema_version` (must be 1) and `plugin_version`
(must be >= 1.1.0). Mismatch → explicit error on the fallback screen; the app
never white-screens or crashes.
