# Desktop Alpha Validation Log

90-day public validation window for the Desktop Alpha release.
**Day 0 = 2026-08-29**（Public Desktop Alpha released）· Window: Day 0 → Day 90.

## Data source & honesty rules

- Metrics come **only from the GitHub public API**. **No Desktop telemetry** is
  added or used (the Desktop app sends no outbound telemetry by design).
- **Download counts are NOT a proxy for real users.** A download may be a bot,
  a mirror, a re-test, or one person downloading twice. "Meaningful external
  users" is assessed separately from qualitative signals (Issues / PRs /
  Discussions / direct contact).
- Threshold reference: [DESKTOP_ALPHA_90_DAY_VALIDATION.md](../product/DESKTOP_ALPHA_90_DAY_VALIDATION.md)
  - **Minimum signal**: ≥25 Desktop downloads · ≥5 external users with meaningful interaction · ≥3 substantive Issue/Discussion threads
  - **Strong signal**: ≥100 Desktop downloads · ≥15 meaningful external users · ≥5 feature/compatibility requests
  - **Platform signal**: repeated requests for ≥1 non-Hermes agent collector

## Metrics

| metric | definition |
|---|---|
| DMG downloads | `Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg` download_count (release `desktop-v0.1.0-alpha`) |
| Stars | `stargazers_count` |
| Forks | `forks_count` |
| external Issues | issues opened by non-maintainer accounts (PRs excluded) |
| Discussions | discussion count (note: announcement post is maintainer-authored) |
| external PRs | PRs opened by non-maintainer accounts |
| meaningful external users | distinct humans who engaged (Issue/PR/Discussion/contact) beyond a single drive-by action |
| non-Hermes collector requests | requests to use the HUD as a data collector for a non-Hermes agent/system |

## Checkpoints

| checkpoint | date | DMG dl | Stars | Forks | ext Issues | Disc | ext PRs | meaningful users | non-Hermes requests |
|---|---|---|---|---|---|---|---|---|---|
| **Day 0** | 2026-08-29 | **2** | **1** | **1** | **0** | **1**（公告帖 #16，maintainer） | **1**（PR #4 mariopablobarron） | **0** | **0** |
| Day 7 | 2026-09-05 | — | — | — | — | — | — | — | — |
| Day 30 | 2026-09-28 | — | — | — | — | — | — | — | — |
| Day 60 | 2026-10-28 | — | — | — | — | — | — | — | — |
| Day 90 | 2026-11-27 | — | — | — | — | — | — | — | — |

> Day 0 baseline captured live from GitHub API on 2026-08-29 (not hand-filled).

## Issue triage policy

| priority | definition | action |
|---|---|---|
| **P0** | security / data corruption / cannot launch | **immediate triage** (same-day, highest urgency) |
| **P1** | install failure / connect failure / core feature incorrect | evaluate for **0.1.1** (next patch window) |
| **P2** | UX / feature request / enhancement | collect until **Day 7 review** |

Rules:
- P0 → immediate triage, no batching.
- P1 → evaluate for 0.1.1 (Desktop patch) at the next release gate.
- P2 → batch and review at the Day 7 Product Review.
- No new Desktop feature development starts before the Day 7 review
  (Post-Launch Operations v1 scope).

## How to update

Daily: a cron agent (`hud-release-metrics`) reads the GitHub public API and
posts the daily summary to Telegram — the log itself is updated at each
checkpoint (Day 7 / 30 / 60 / 90) via a normal repo PR.
