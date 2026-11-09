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
| Hermes Agent | required (≥ 0.19.0; HUD plugin ≥ 1.1.1) |
| HUD plugin | separately versioned; plugin release **v1.2.3**. Minimum schema-1 plugin: **v1.1.1** |
| Intel / Universal / Windows / Linux Desktop | ❌ not provided / not claimed |

## Relationship of the three pieces

| Piece | What it is | Versioning |
|---|---|---|
| **Hermes Agent** | the AI agent runtime (state.db, gateway, etc.) | own versioning |
| **Hermes HUD plugin** | dashboard plugin (Web UI + backend API) | v1.2.3; minimum v1.1.1 for schema 1 |
| **Hermes HUD Desktop** | native app shell over the Dashboard | 0.1.0-alpha |

Downloading Hermes HUD Desktop does **not** install Hermes Agent. You need a
compatible Hermes Agent already installed.

The 2026-11-09 Hermes 0.23.0 check covered isolated plugin backend paths in an existing dependency environment. It did **not** revalidate the Desktop UI, its launcher or a fresh Desktop installation. Desktop Alpha remains 0.1.0; plugin changes do not imply a new Desktop binary. See the [compatibility record](../quality/HERMES_023_COMPATIBILITY_20261109.md).

## Install

See [INSTALL_MACOS.md](INSTALL_MACOS.md) · [UNINSTALL_MACOS.md](UNINSTALL_MACOS.md)
· [SECURITY.md](SECURITY.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

## Web UI remains supported

The browser-based HUD keeps working exactly as before. Desktop is an
additional surface, not a replacement.
