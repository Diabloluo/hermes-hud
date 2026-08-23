# Community Post Drafts — Hermes HUD v1.0.1

Three drafts: Hermes Discord (short), Reddit r/hermesagent (detailed, scenario-first),
X/Twitter (short). **Do not post automatically — user confirmation required first.**

---

## 1. Hermes Discord — 短版

> **Hermes HUD v1.0.1** — a local monitoring dashboard plugin for Hermes Agent
>
> 11 tabs (Overview / Live / Token & Cost / Sessions / Memory / Skills / Cron / Channels /
> Errors & Incidents / System / Settings), 2-second realtime via shared snapshot cache +
> WebSocket, strict read-only (never touches state.db writes, zero outbound telemetry),
> redaction-first so secrets never reach the UI, and an optional Telegram/Feishu alert
> helper for new incidents / upgrades / recoveries.
>
> Install: clone to `~/.hermes/plugins/hermes-hud` → `hermes plugins enable hermes-hud` →
> restart dashboard. Ships prebuilt frontend, no web UI rebuild needed.
>
> Tested on macOS; Linux expected, Windows experimental. Feedback and compatibility
> reports welcome. Repo: https://github.com/Diabloluo/hermes-hud

---

## 2. Reddit r/hermesagent — 详细版（场景开头，不营销，不要求 Star）

> **I kept restarting my dashboard to check things — so I built a monitoring tab for it**
>
> Real background: I run Hermes as a 24/7 gateway with ~20 cron jobs (daily reviews,
> market briefings, watchdogs). Every morning I'd open the dashboard, click around four
> pages to answer the same questions: did the overnight jobs run? did Telegram/Feishu
> stay connected? what did yesterday actually cost? And twice a week I'd find out the
> hard way — a failed job, a silently disconnected channel — because nothing surfaces it.
>
> So I built Hermes HUD, a user-level Dashboard plugin that puts all of that on one
> screen, locally:
>
> - **Overview** — health score, gateway/channel/cron status, today's token/cost, ~30
>   health checks, and an incident timeline that keeps recovered incidents (so you can
>   see what actually went wrong this week)
> - **Token & Cost** — 7/30/90-day trends, per-model and per-aux-task aggregation.
>   Cost labels are honest: estimated vs actual vs unbilled
> - **Live** — active sessions, 2s incremental event stream over WebSocket, recent tool
>   calls
> - **Cron / Channels / Errors / System / Skills / Sessions / Memory / Settings** —
>   job states and execution history, "connected but jittery" channels flagged yellow,
>   error fingerprint aggregation, launchd state, disk/memory
> - **Optional alert helper** — pushes new incidents / upgrades / recoveries to
>   Telegram + Feishu, with dedup and a recovery state machine (it only marks an
>   incident recovered after a channel actually confirmed delivery)
>
> Design constraints I cared about:
> - **Read-only**: state.db is opened `mode=ro` + `query_only`, short timeouts, never
>   locks the gateway. HUD writes only its own telemetry under `~/.hermes/hud/`
> - **No outbound telemetry**: listens on 127.0.0.1 only
> - **Redaction-first**: logs/paths are redacted before they reach the API; error
>   fingerprints are generated after redaction
> - No dependency on rebuilding the web UI — prebuilt frontend ships in the repo
>
> Tested on macOS; on Linux it should work (launchd checks are skipped properly) and
> community reports are welcome. Windows is experimental. PR #3's CI runs pytest on
> 3 Python versions × 2 OSes.
>
> Repo + screenshots: https://github.com/Diabloluo/hermes-hud
>
> Happy to answer questions about the collector/rule design — especially if you have
> ideas for what else to surface from `state.db` that I'm not showing yet.

---

## 3. X/Twitter — 短帖版

> Built a local monitoring dashboard plugin for Hermes Agent:
>
> • 11 tabs: health, token/cost, cron, channels, errors, skills, system
> • 2s realtime (shared snapshot cache + WebSocket)
> • read-only — never writes state.db, zero outbound telemetry
> • redaction-first; optional Telegram/Feishu incident alerts
>
> Install: clone to ~/.hermes/plugins/hermes-hud → hermes plugins enable hermes-hud
> Ships prebuilt frontend. Tested macOS, Linux expected.
>
> https://github.com/Diabloluo/hermes-hud
