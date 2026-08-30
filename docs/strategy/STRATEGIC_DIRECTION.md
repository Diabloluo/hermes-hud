# Strategic Direction — v1 (frozen 2026-08-30)

Source: [dutybook-strategy-2026-08-30.md](dutybook-strategy-2026-08-30.md) (preserved verbatim)

> This document is a **strategy freeze**. It records direction only —
> no rename, no refactor, no second adapter, no new feature development
> starts from this document.

## 1. Current official status

- **Current shipping product**: Hermes HUD Desktop Alpha 0.1.0
  (public, signed + notarized, `desktop-v0.1.0-alpha`).
- **Dutybook (值班本)**: Strategic Direction / candidate long-term
  product identity — **not** yet the shipped product name.
- Product direction (one line): *local duty log for agent spend,
  incidents and health. Hermes is the first adapter.*

## 2. Explicitly NOT being executed now

- repo rename
- Desktop bundle rename
- plugin rename
- second adapter
- Plugin SDK
- multi-agent UI
- workspace / chat / IDE surface
- telemetry (no outbound product telemetry, ever, per product principle)
- API interception / budget blocking / auto circuit-breaking

## 3. Core capability priorities (the fort)

**Cost Truth**
- estimated / actual / unpriced (unbilled) — three separate buckets
- no double counting (primary + auxiliary calls)
- estimation is never presented as invoice

**Incident Model**
- fingerprint (dedup identical error classes)
- repeated incident vs new incident
- first / last seen
- recovery confirmation

**Operational Health**
- Gateway
- Channels (Telegram etc. — alive vs "connected but flapping")
- Cron (continuous failures)
- stale / flapping / failure states

## 4. Product principles

> **Observe, do not control.**

- Local-first
- Read-only (never write back to agent data)
- No outbound product telemetry

## 5. Architectural direction (future, NOT now)

Recommended long-term shape — **no refactor in this cycle**:

```
core/
  cost/
  incidents/
  health/

adapters/
  hermes/        # first adapter — currently the deepest
```

- Hermes should gradually become the **first adapter**, not the permanent
  home of all core business logic.
- **NO REFACTOR NOW.** Only reduce Hermes-specific coupling incidentally
  when normal feature iteration touches the relevant code. Do not perform
  large-scale "premature abstraction" refactors.

## 6. Second adapter gate

The second adapter is **not** a current development task. Enter review
only when any real signal is met:

- 10–20 meaningful external users, OR
- ~50 GitHub Stars, OR
- multiple real users actively requesting Codex / Claude Code support, OR
- Day 30/60 validation shows clear multi-agent demand

Rules:
- **Only one** second adapter.
- Prefer the agent the maintainer actually uses daily (no daily traffic =
  a display piece).
- Forbidden: developing Codex + Claude Code + Cursor + other harnesses
  in parallel.

## 7. Dutybook name policy

| surface | current name | rename? |
|---|---|---|
| Product direction | **Dutybook / 值班本** | strategy/copy only, for now |
| Repository | `Diabloluo/hermes-hud` | **no** |
| Dashboard plugin | Hermes HUD | **no** |
| Desktop public Alpha | Hermes HUD Desktop Alpha | **no** |

Formal brand migration window opens when:
- the second adapter is about to ship, **OR**
- market signal reaches ~50 Stars / clear external recognition.

Until then, Dutybook may only be tested in strategy / marketing copy.

## 8. Product filter (three long-term correction questions)

1. Is this feature helping users: reconcile / stand duty / find
   incidents / judge system health — or is it just adding another agent page?
2. Are we becoming: chat / workspace / IDE?
3. Are we, in the name of accuracy, starting to: write back to agent
   data / intercept APIs / auto circuit-break?

If the answer drifts from the Dutybook core: **STOP / REASSESS**.

## 9. Day 7 review (unchanged plan)

This strategy document does not change the current Post-Launch plan:
- Day 0 → Day 7 observation continues.
- P0: handle immediately.
- P1: evaluate for Desktop 0.1.1.
- P2 / new features: batch review at Day 7.
- **Day 7 = 2026-09-05.**

Day 7 Product Review adds three validation questions:
- Is Cost Intelligence seeing real usage/feedback?
- Are Incident / Health showing real demand?
- Has any external user actively requested a non-Hermes adapter?

Use real data to validate the Dutybook strategic hypothesis.
