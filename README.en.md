[English](README.en.md) | **中文**

# Hermes HUD 🛰️

> A local, real-time monitoring command center for Hermes Agent — health overview, token/cost, models, memory, sessions, cron jobs, channels, errors, and machine health at a glance. When something goes wrong, you see it immediately.

A **user-level Hermes Dashboard plugin**: it does not modify the `~/.hermes/hermes-agent` core, survives Hermes upgrades, and can be disabled/rolled back in one command.

![release](https://img.shields.io/github/v/release/Diabloluo/hermes-hud?label=release) ![ci](https://img.shields.io/github/actions/workflow/status/Diabloluo/hermes-hud/ci.yml?label=CI) ![license](https://img.shields.io/github/license/Diabloluo/hermes-hud) ![stars](https://img.shields.io/github/stars/Diabloluo/hermes-hud) ![platform](https://img.shields.io/badge/Tested-macOS-2ea44f)

## ✨ Highlights

- 🖥 **One screen, many tabs**: Overview, Live, Token & Cost (Cost Intelligence), Sessions, Timeline, Memory, Skills, Skill Analytics, Cron, Channels, Errors & Incidents, System & Storage, Settings
- ⚡ **2-second realtime**: shared snapshot cache + WebSocket incremental event stream; REST and WS never duplicate collection
- 🔒 **Strict read-only boundary**: Hermes core data is always read-only (`mode=ro`, never locks the Gateway); logs/paths redacted first, fingerprints generated after redaction — raw secrets never leave
- 📊 **Trustworthy cost accounting**: estimated-cost semantics with pricing-provenance coverage (known vs unknown pricing rows) and attribution-aware time windows — never presented as provider invoices
- 🚨 **Proactive alerts**: optional `hud_alert.py` pushes new incidents / upgrades / recoveries to Telegram + Feishu (dedup + confirmed-recovery state machine)

## 🚀 Quick Start

```bash
git clone https://github.com/Diabloluo/hermes-hud ~/.hermes/plugins/hermes-hud
python3 ~/.hermes/plugins/hermes-hud/scripts/enable_dashboard_plugin.py enable
hermes dashboard --host 127.0.0.1 --port 9119 --no-open
# Open http://127.0.0.1:9119 → "Hermes HUD" in the sidebar
```

> Prebuilt frontend ships in the repo — no web UI rebuild needed.
> Full install/uninstall/troubleshooting: **[INSTALL.md](INSTALL.md)** · First-run guide: **[FIRST_5_MINUTES.md](FIRST_5_MINUTES.md)** · Enabling Discussions (maintainers): **[DISCUSSIONS_GUIDE.md](DISCUSSIONS_GUIDE.md)**.

## 🎬 Demo (19.5s · sanitized demo data)

![Hermes HUD demo](assets/demo.gif)

## 📸 Screenshots

**Token & Cost** (per-model / per-aux-task aggregation; costs explicitly labeled as estimated):

![Token & Cost](assets/screenshot-usage.png)

**Skills** (skill directory statistics with category filtering):

![Skills](assets/screenshot-skills.png)

## ✨ Features

| Tab | Contents |
|---|---|
| ◉ Overview | Health score (normal/warning/critical), Gateway/channel/cron status, today's token/cost, 30 health checks, incident timeline, system mini-cards |
| ⚡ Live | Active sessions, 2s incremental event stream (WebSocket + polling fallback), recent tool calls |
| ¥ Token & Cost | 7/30/90-day trends, per-model / per-aux-task aggregation, costs labeled "estimated / actual / unbilled" |
| ☰ Sessions | Search, pagination, session detail (message preview + model usage) |
| 🧠 Memory | MEMORY.md/USER.md metadata, lock-file health |
| ⚒ Skills | Skill directory statistics, category filtering and local skill list |
| ⏱ Cron | Job enabled state, schedules, failure counts and execution history (claimed→running→completed/failed) |
| ⇄ Channels | Telegram/Feishu "connected but jittery" correctly highlighted in yellow (not masked by a connected state) |
| ⚠ Errors & Incidents | 30-min error count, fingerprint aggregation, incident timeline (recovered ones are kept), redacted log tail |
| ▤ System & Storage | CPU/memory/disk/processes, launchd management state, telemetry trend chart |
| ⚙ Settings | Thresholds/budget/retention, collector data quality, security boundary, one-click Dashboard menu language |

**Bonus**: `scripts/hud_alert.py` — proactive incident push alerts (Telegram + Feishu) on new incidents / severity upgrades / recovery, with deduplication and throttling.

## 📦 Installation

```bash
# 1. Clone into your user plugins directory
git clone https://github.com/Diabloluo/hermes-hud ~/.hermes/plugins/hermes-hud

# 2. Enable the plugin (read → merge → write back; preserves your other plugins)
python3 ~/.hermes/plugins/hermes-hud/scripts/enable_dashboard_plugin.py enable

# 3. Start the Dashboard (backend API routes mount at startup, so restart it)
hermes dashboard --host 127.0.0.1 --port 9119 --no-open
# Open http://127.0.0.1:9119 → "Hermes HUD" in the sidebar

# Uninstall (removes only HUD, keeps every other plugin):
python3 ~/.hermes/plugins/hermes-hud/scripts/enable_dashboard_plugin.py disable
```

> The repo ships prebuilt frontend assets (`dashboard/dist/`); no need to rebuild the Hermes web UI.
> Only if your Hermes is missing `hermes_cli/web_dist/` (Dashboard shows the boot screen):
> `cd ~/.hermes/hermes-agent && npm run install:web && cd web && npm run build`

### Alert helper (optional)

```bash
# .env needs (hud_alert.py loads only these allowlisted variables):
#   TELEGRAM_BOT_TOKEN + TELEGRAM_HOME_CHANNEL
#   FEISHU_APP_ID + FEISHU_APP_SECRET + FEISHU_ALLOWED_USERS (open_id)
#   (optional) HUD_TG_PROXY — no proxy by default; set e.g. http://127.0.0.1:7897 where Telegram is blocked
cp scripts/hud_alert.py ~/.hermes/scripts/hud_alert.py
# Test
python3 ~/.hermes/scripts/hud_alert.py --dry-run
# Cron every 5 minutes (inside Hermes):
hermes cron add --script hud_alert.py --schedule '*/5 * * * *' --no-agent
```

## 🏗 Architecture

```
Hermes data sources (read-only)
  ├─ state.db / session_model_usage   ← SQLite read-only connection (mode=ro)
  ├─ cron/jobs.json / executions.db
  ├─ gateway_state.json / process liveness
  ├─ memories/ (MEMORY.md / USER.md)
  ├─ logs/ (agent.log / errors.log)
  └─ ~/.hermes/skills/                ← SKILL.md metadata scan
                 │
                 ▼
       hermes-hud plugin_api.py
  collectors → normalizer → rules engine (health rules)
                 │
        ┌────────┴────────┐
        ▼                 ▼
 snapshot REST       authenticated WebSocket
        │                 │
        └────────┬────────┘
                 ▼
        Hermes HUD tab UI
                 │
                 ▼
      ~/.hermes/hud/telemetry.db
   (minute-level metrics / incident fingerprints / short summaries)
```

- Plugin API mounts at `/api/plugins/hermes-hud/`, reusing the Dashboard's standard session-token auth
- WebSocket goes through the Dashboard's standard auth gate (`_ws_auth_ok`); no second token scheme
- telemetry.db is independent of state.db and can be deleted/rebuilt entirely

## 🔒 Security boundary

- Listens on `127.0.0.1` by default; no outbound telemetry
- **Read-only boundary**: Hermes core data is always read-only (state.db opened with `mode=ro` + `query_only` + short timeouts, never locks the Gateway); HUD writes only its own telemetry and alert state under `~/.hermes/hud/`
- **The Dashboard plugin itself never reads `.env` / `auth.json`**; the optional `hud_alert.py` helper loads only the notification credentials it needs (allowlist: TELEGRAM_*/FEISHU_*/HUD_TG_PROXY)
- Logs/conversations/memory are redacted first (key/token/secret/bearer/JWT/long hex/base64); log fingerprints are generated after redaction — raw secrets never enter fingerprints, incidents, APIs or WebSocket
- Conversation and memory bodies never enter the event stream; details load on demand as short previews
- Local paths and command-line summaries are privacy-sanitized (usernames / middle directories hidden)
- telemetry.db stores only aggregates, incident fingerprints and short summaries
- HUD itself is purely observational; install/uninstall links jump to existing Dashboard protected pages

## 📊 Data accounting

- **Three cost buckets**: `actual` (provider billing) / `estimated` (per-model price table) / `unbilled`. Without billing data everything is labeled "local estimate"
- **No double counting**: main sessions come from `sessions`; auxiliary calls only from `session_model_usage.task != ''` (`task=''` rows duplicate main-session billing and are excluded); API calls sum the database's `api_call_count`
- **Statistics timezone**: `HUD_TIMEZONE` (e.g. `Asia/Shanghai`) > system local timezone > UTC; UTC epochs are converted only at query time
- **state.db fully read-only**: `mode=ro` + short timeout + `query_only`, never blocks the Gateway
- **Incident counts**: `observations` = times observed, `state_changes` = substantive state changes; 2s-poll observations are not presented as "trigger counts"

## 🩺 Health rules (thresholds overridable via `HUD_*` env vars)

| Level | Rule |
|---|---|
| 🔴 critical | Gateway process not alive; state.db unreadable; disk < 5%; Cron consecutive failures ≥ 3 |
| 🟡 warning | Channel connected but heartbeat > 60s (jitter); > 20 errors in 30 min; disk < 15%; memory > 85%; launchd unmanaged; today's cost over 80% of daily budget |

> Field experience: `gateway_state.json` is written on state *changes*, not as a periodic heartbeat (it can be 60+ minutes stale while the process is healthy). Therefore **process liveness is the critical criterion**; a stale state file is only a warning.

## ❓ FAQ

- **Dashboard shows the desktop boot screen** ("Desktop boot failed"): when started from a Hermes desktop-app shell, `HERMES_DESKTOP=1` + `HERMES_WEB_DIST` are inherited; start with `env -u HERMES_WEB_DIST -u HERMES_DESKTOP -u HERMES_SERVE_HEADLESS hermes dashboard ...`
- **Menu language resets to English after restart**: menu language lives in browser localStorage (`hermes-locale`), unrelated to server restarts; the HUD Settings tab has a one-click "set Chinese menu"
- **Plugin not showing**: make sure `scripts/enable_dashboard_plugin.py enable` ran, then restart the dashboard
- **Backend 401**: in loopback mode the token is injected into the page HTML; the frontend carries it automatically. For curl, extract it first

## 🧩 Compatibility

- **Tested: macOS**; Linux expected to work (community testing welcome); Windows experimental
- Hermes v0.20+ (Dashboard plugin SDK: manifest.json + plugin_api.py + IIFE bundle)
- The plugin itself survives Hermes upgrades; rebuild the web UI only if needed (`npm run build`)
- Full uninstall: `hermes plugins disable hermes-hud` + remove the plugin directory

## 🤝 Community

- **Issues**: [Bug report](https://github.com/Diabloluo/hermes-hud/issues/new?template=bug_report.yml) / [Compatibility report](https://github.com/Diabloluo/hermes-hud/issues/new?template=compatibility_report.yml)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, tests, PR workflow and security boundary
- **Maintainers**: optionally enable GitHub community-event notifications (Star / Issue / Fork → Telegram) via `.github/workflows/community-telegram.yml`
- **Discussions**: not enabled yet on this repo; suggested categories once enabled: General / Installation Help / Compatibility / Ideas / Show and Tell

## 📄 License

MIT
