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
| **Day 7** | 2026-09-05 | **2** | **4** | **1** | **0** | **2**（#16 公告 + #18 v1.1.1 发布帖，均 maintainer） | **1**（PR #4 mariopablobarron） | **0** | **0** |
| **Day 30** | 2026-09-28 | **3** | **9** | **2** | **0** | **3**（#16 / #18 / #25，均 maintainer；评论 0） | **2**（#4 merged / #26 open） | **1**（Manaf-Alkadi，持续贡献与多轮复审互动） | **0** |
| Day 60 | 2026-10-28 | — | — | — | — | — | — | — | — |
| Day 90 | 2026-11-27 | — | — | — | — | — | — | — | — |

> Day 0 baseline captured live from GitHub API on 2026-08-29 (not hand-filled).
> Day 7 values re-read live from GitHub API on 2026-09-06 immediately before commit（closeout executed 2026-09-06; Day 7 window date = 2026-09-05）.
> Day 30 values captured from GitHub REST / GraphQL APIs on 2026-09-28, 19:54–19:55 Asia/Shanghai (11:54–11:55 UTC), against `main` at `fe86ebfc5dd1efc8c75d1544323f16130d46f4f0`. These are a checkpoint snapshot, not automatically refreshed counters.

## Day 7 review — decision（2026-09-06 closeout）

**Decision**

- P0 product defects: **0**
- P1 product defects: **0**
- One P1 candidate was investigated during the window and **closed as local stale-installation state** — NOT an external Desktop product defect; no product code shipped for it. Recorded only as:

  `P1 candidate → investigated → local environment → remediated → CLOSED`

- Desktop 0.1.1: **NO-GO**
- HUD v1.1.3: **NO-GO**
- Next priority: **Distribution + Observation**
- Show HN: **UNBLOCKED**
- Next formal checkpoint: **Day 30 — 2026-09-28**

**Strict evidence notes**

- **Meaningful external users = 0.** The only external human signal is mariopablobarron's
  merged PR #4 (2026-08-29, +119/−2 functional fix) — counted under external PRs = 1. He is
  NOT counted as a meaningful user: his entire repo engagement is that single PR, with zero
  issues / comments / discussion / review interaction (API-verified 2026-09-06), which does not
  clear the "beyond a single drive-by action" bar — consistent with the Day 0 baseline, where
  the same author's open PR also counted 0. Download counts are not user evidence.
- **Non-Hermes collector requests = 0** — no public evidence exists.
- Week-1 trend: stars 1→4 · forks 1 · external issues 0 · discussions 2（均 maintainer 帖）·
  external PRs 1（merged）. Minimum-signal thresholds（≥25 dl / ≥5 meaningful users / ≥3
  threads）not approached — no action beyond Distribution + Observation.

## Day 30 review — evidence and pending product decisions（2026-09-28）

**Evidence and counting decisions**

- **DMG downloads = 3** for `Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg` in the public
  [desktop-v0.1.0-alpha release](https://github.com/Diabloluo/hermes-hud/releases/tag/desktop-v0.1.0-alpha).
  Draft/staging assets and `SHA256SUMS.txt` downloads are excluded. Downloads remain
  a release-asset count, not an install count or user count.
- **Stars = 9; Forks = 2.** External Issues = **0** after excluding PRs from the issues API.
- **Discussions = 3**: [#16](https://github.com/Diabloluo/hermes-hud/discussions/16),
  [#18](https://github.com/Diabloluo/hermes-hud/discussions/18), and
  [#25](https://github.com/Diabloluo/hermes-hud/discussions/25). All are maintainer-authored,
  with zero comments; they do not establish three substantive external feedback threads.
- **External PRs = 2**: mariopablobarron's
  [#4](https://github.com/Diabloluo/hermes-hud/pull/4) is merged; Manaf-Alkadi's
  [#26](https://github.com/Diabloluo/hermes-hud/pull/26) is open.
- **Meaningful external users = 1: Manaf-Alkadi.** Counted under the existing
  "beyond a single drive-by action" definition because of repeated substantive engagement:
  a [build/CI clarification on September 14](https://github.com/Diabloluo/hermes-hud/pull/26#issuecomment-5659875138),
  a [blocker-fix and test report on September 16](https://github.com/Diabloluo/hermes-hud/pull/26#issuecomment-5695661743),
  and a [second reproduction/fix report on September 18](https://github.com/Diabloluo/hermes-hud/pull/26#issuecomment-5736938816),
  together with follow-up commits. This is contributor-engagement evidence; it does not
  establish a Desktop installation. PR #4's author remains uncounted under this definition:
  no additional issue-comment/review interaction was found at this checkpoint. Day 0 and
  Day 7 historical values remain unchanged; PR #26 was created after both checkpoints.
- **Non-Hermes collector requests = 0**: no explicit external request was found in the
  public Issues, Discussions, or external PR records inspected. Maintainer-written
  prompts asking about other agents do not count as external demand.

**Product gate status**

- Minimum signal remains unmet: **3 / 25** downloads, **1 / 5** meaningful external users,
  and no substantive external Issue/Discussion thread observed. PR #26 nevertheless
  supplies a concrete sustained-contributor signal.
- `main` remains at `fe86ebf`; HUD is still **v1.1.2**, Desktop is still **0.1.0 Alpha**.
- PR #26 is **OPEN / unmerged / mergeable**, head
  `742b4e0b3e48c47204faebae71b29e3b47a92546`; the latest review on this head is
  **APPROVED**, and all **9 check runs passed**. Technical approval and product/release
  authorization remain separate.
- Maintainer decisions are **pending** for: PR #26 merge timing, UX Sprint 1 start,
  and whether to enter a next minor release. Recording this checkpoint grants none of
  those authorizations; Distribution + Observation continues while they are pending.
- The September 27/28 static audit reports need runtime reproduction and performance
  measurements before their candidates are treated as verified operational defects or
  a release gate. No runtime defect count is asserted by this docs-only update.
- Next formal checkpoint: **Day 60 — 2026-10-28**.

This checkpoint changes documentation only. It does not modify source code, PR #26,
Desktop/DMG artifacts, versions, tags, or releases.

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
