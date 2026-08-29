# Hermes HUD Desktop Alpha 0.1.0 — Your local window into Hermes

**Native macOS app · Apple Silicon · local-first, read-only**

Hermes HUD Desktop puts Hermes right on your desktop — a real macOS app
that discovers your Hermes Agent, connects to your Dashboard, and brings
everything into one window:

- **📍 Agent Timeline** — what your agent did, in order (sessions, skills,
  tools, incidents).
- **📊 Skill Analytics** — which skills actually ran, success rates,
  coverage truth.
- **💰 Cost Intelligence** — honest estimated-cost view: pricing coverage
  and attribution-aware windows.
- **🖥 Health, sessions, cron, channels, errors & incidents** — the full HUD.

## Local-first & read-only

- Desktop observability data stays local; the Desktop app sends no outbound telemetry.
- Hermes core data is read-only.
- The HUD page has zero native capability.

## Automatic

- Discovers Hermes on your machine.
- Connects to an already-running Dashboard.
- Or **safely starts** the local Dashboard for you (no second instance,
  fixed safe command).
- Menu-bar tray: Open / Retry / Quit.

## Brand

Observer Core — the observability mark for a platform that will grow
beyond any single agent.

---

**Alpha** · Apple Silicon (arm64) only · requires Hermes Agent (HUD plugin
≥ 1.1.1 — the first official HUD release with API schema 1) · no auto
updater yet.

## Known limitation (Alpha)

**Multi-user Macs:** the Dashboard listens on localhost, which is a
machine-local boundary, not a per-macOS-user boundary. In this Alpha,
another local account on the same Mac may be able to reach an
already-running Dashboard. Do not treat untrusted local macOS accounts as
isolated from HUD data.

Install: see [docs/desktop/INSTALL_MACOS.md](../desktop/INSTALL_MACOS.md)
