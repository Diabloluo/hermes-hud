# Bounded Hermes 0.23 compatibility check (2026-11-09)

This record describes what was actually exercised. It does not promise support
for every Hermes version, every installation method, or future host updates.

## Pinned inputs

- Hermes **0.23.0**, source commit
  `2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19`.
- HUD **1.2.2**, source commit
  `7d9392b0c9483a988ed1f9030deb6fd67f9d6aea`, before this repair.
- macOS integration used an **existing** Hermes-managed Python 3.14.9 dependency
  environment, a copied HUD runtime, a synthetic profile, a spare loopback port,
  and an existing host web distribution with builds disabled.
- Unit and schema-contract checks used an isolated Python 3.12.14 environment.

No production sessions or credentials were used as fixtures. The checks did not
start an Agent or Gateway, install dependencies on the host, build its frontend,
send notifications, or delete a live plugin directory.

## Executed checks

| Check | Result and limit |
|---|---|
| Helper enable, repeated enable, disable | Passed; two unrelated enabled plugin names and a disabled list were preserved in synthetic configuration. |
| Native `hermes plugins disable hermes-hud` | Reproduced `No plugin named 'hermes-hud'`; isolated configuration hash was unchanged. Use the repository helper for this Dashboard plugin. |
| Dashboard loading | Passed with existing dependencies and static assets, not a clean installation. |
| Plugin health | Unauthorized request 401; authorized request 200, API schema 1 and plugin version 1.2.2. |
| Snapshot | Authorized request 200. |
| WebSocket | Unauthorized connection 403; authorized schema-1 frames arrived approximately every two seconds. |
| Synthetic Cron failure/recovery | Failure streak 3 became failing=1; clearing it returned failing=0 in stream and snapshot. |
| Cleanup | Only the owned test server was stopped, and its spare port was released. |
| Current state schema | Cost/session reads worked with the exact host schema (version 32), extracted from pinned source into a synthetic database. |
| Cost coverage and privacy | A known priced subtotal plus unknown pricing stayed incomplete; actual-cost semantics remained recorded/unverified; synthetic path secrets were redacted and state DB contents were unchanged. |

The original HUD unit suite produced **424 passed, 32 skipped, 1 explicitly
excluded**. Skips were 19 browser cases and 13 real-host CLI cases in the cloud
unit environment. The excluded optional test reads real telemetry; it was not
appropriate for an isolated test. These counts do not replace host integration.

## Defect reproduced and repaired

The host's Cron ledger stores aware ISO timestamp strings. The old summary
compared them to an epoch number and subtracted them directly in SQLite.

A synthetic 30-second completed attempt from the last minute plus a failed
attempt from 60 days earlier should yield one completed attempt, no failure and
30 seconds in the last-30-day summary. Before this repair it yielded two
attempts, one failure and zero seconds. Individual-row duration was correct;
the aggregate window and elapsed-time calculation were not.

The repair parses both ISO and legacy epoch representations before filtering
and aggregation. Regression cases cover UTC, positive/negative timezone
offsets, numeric/numeric-string epoch timestamps, malformed input, missing
durations, non-finite values, strict JSON serialization, independence from the
visible-row limit, and read-only DB access.
See `tests/test_cron_timestamp_contract.py`; final test evidence belongs to the
reviewed PR/commit rather than a blanket compatibility claim.

Independent review passed the repaired aggregation and its ten regression
cases. The complete repaired unit suite produced **434 passed, 32 skipped,
1 explicitly excluded** in the environment described above. The original
execution-list text ordering is outside this repair. Summaries use records
still retained by the host; its retention limit can prevent them from covering
every execution in a busy 30-day window.

## Not certified by this check

- A clean Hermes 0.23 install or dependency resolution from scratch.
- Full browser, Desktop Alpha UI, or macOS signing/notarization behavior.
- Removal of plugin files or all persistent HUD telemetry.
- Every current-host API, operating system, workload, or future host version.

The existing Fresh Install CI lane remains pinned to Hermes 0.19.0. Its green
result proves that lane, not Hermes 0.23. A separately pinned current-host lane
is still desirable; do not silently turn an older minimum-version lane into a
claim of complete version-range coverage.
