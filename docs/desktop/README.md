# Hermes HUD — Desktop (macOS)

**Desktop Alpha 0.1.0** · Apple Silicon (arm64) · local-first, read-only

Hermes HUD Desktop is a native macOS window into your Hermes Agent. It is a
**companion to the existing Web dashboard plugin** — it does not replace it.

## What it is

- A native macOS app (Tauri shell) that connects to the Hermes Dashboard
  already running on your machine.
- One window showing the same HUD you know from the browser: **Agent
  Timeline**, **Skill Analytics**, **Cost Intelligence**, health, sessions,
  cron, channels, errors & incidents.
- Automatically discovers Hermes, connects to a running Dashboard, or can
  safely start the local Dashboard for you.
- Menu-bar tray with Open / Retry / Quit.

## Support scope (current)

| | |
|---|---|
| macOS | ✅ (current OS versions) |
| Architecture | **Apple Silicon (arm64) only** |
| Desktop version | 0.1.0-alpha |
| Hermes Agent | required (≥ 0.19.0; HUD plugin ≥ 1.1.0) |
| HUD plugin | separately versioned (v1.1.0) — independent of Desktop |
| Intel / Universal / Windows / Linux Desktop | ❌ not provided / not claimed |

## Relationship of the three pieces

| Piece | What it is | Versioning |
|---|---|---|
| **Hermes Agent** | the AI agent runtime (state.db, gateway, etc.) | own versioning |
| **Hermes HUD plugin** | dashboard plugin (Web UI + backend API) | v1.1.0 |
| **Hermes HUD Desktop** | native app shell over the Dashboard | 0.1.0-alpha |

Downloading Hermes HUD Desktop does **not** install Hermes Agent. You need a
compatible Hermes Agent already installed.

## Install

See [INSTALL_MACOS.md](INSTALL_MACOS.md) · [UNINSTALL_MACOS.md](UNINSTALL_MACOS.md)
· [SECURITY.md](SECURITY.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

## Web UI remains supported

The browser-based HUD keeps working exactly as before. Desktop is an
additional surface, not a replacement.
