# Hermes HUD v1.1.0 — Observability gets serious

**Local-first, read-only observability platform for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

## 📍 Agent Timeline
What did the agent do, in order. A unified event model (sessions · skills · tools · incidents) with stable pagination, idempotent collection, and a watermark commit point — observed truth only, never guessed events.

## 📊 Skill Analytics
From static inventory to observable objects: registered vs observed runs, success rates (null when there is no evidence — never fake 0%), duration, and an honest runtime-coverage model (`observed` / `inventory_only` / `unavailable`).

## 💰 Cost Intelligence
One canonical cost surface built on Hermes' recorded usage rows, with honest semantics:
- **estimated cost** — never presented as provider invoices
- **pricing coverage** — known vs unknown pricing provenance is reported, not hidden
- **attribution-aware time windows** — cumulative usage rows attributed by last activity; `All` is lifetime-cumulative, windowed ranges are explicitly not exact

## 💬 Discussions
The repository now has Discussions — welcome, show us your setup, and tell us what HUD should observe next.

## ✅ Fresh-install CI
Every install-relevant change is now automatically verified on a clean macOS runner: Python 3.13 + Hermes ≥ 0.19.0, clone the exact commit under test, enable, start, HTTP smoke, and precise cleanup.

---

**Install** (pinned to this release tag — not floating `main`):
```bash
git clone --branch v1.1.0 --depth 1 https://github.com/Diabloluo/hermes-hud ~/.hermes/plugins/hermes-hud
python3 ~/.hermes/plugins/hermes-hud/scripts/enable_dashboard_plugin.py enable
```

**Docs**: [README](https://github.com/Diabloluo/hermes-hud#readme) · [INSTALL.md](https://github.com/Diabloluo/hermes-hud/blob/main/INSTALL.md) · [First 5 minutes](https://github.com/Diabloluo/hermes-hud/blob/main/FIRST_5_MINUTES.md) · [Changelog](https://github.com/Diabloluo/hermes-hud/blob/main/CHANGELOG.md)

_Support: macOS tested · Linux expected (community testing welcome) · Windows experimental._
