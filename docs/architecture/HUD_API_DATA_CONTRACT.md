# HUD API data contract — audit repair candidate

Applies to `/api/plugins/hermes-hud/` REST responses and snapshot/health data
sent through WebSocket `/events`. This candidate retains schema **1** and plugin
version **1.2.1**; it has not been released. The corrections below affect existing
field semantics and nullability. Consumers that assumed every numeric or boolean
field was always populated must update their handling before adopting it.

## Pricing and completeness

The only pricing source is Hermes `state.db.session_model_usage`. A row is priced
only when `cost_status == "estimated"` and `cost_source` is nonempty and not
`"none"`. Legacy missing metadata and `unknown` status do not establish pricing.
Raw `sessions.estimated_cost_usd` and cached timeline sums are not independent
pricing sources. No historical price is recomputed from current price lists.

| Field | Meaning and nullability |
| --- | --- |
| `estimated_cost_usd` | Sum of priced rows only. Readable source with no priced rows returns `0`, even when costs are incomplete. Unavailable source returns `null`. This is an estimate, not an invoice. |
| `/usage` `est_cost` | Alias of the same known subtotal, including the same nullable behavior. |
| `usage_rows` | Actual matching usage-row count; `null` if unavailable. Missing session records are not invented as usage rows. |
| `pricing_known_rows`, `pricing_unknown_rows` | Provenance counts among actual matching rows; `null` if unavailable. |
| `pricing_coverage_ratio` | Known rows / matching rows. Empty complete aggregation is `1`; empty unknown/unavailable aggregation is `null`. It measures existing-row coverage, not coverage of missing session records. |
| `cost_complete` | Boolean indicating whether this view has complete pricing. Missing provenance or an unavailable source makes it false. `/usage` additionally checks session activity with no usage records. |
| `cost_source_status` | `healthy` means the pricing source is readable, not that all pricing is complete; `unavailable` means it could not be read. |
| `/usage` `sessions_without_usage` | Count of sessions in the token/activity window that have no usage row anywhere in their lifetime. Present in totals/day/model/task pricing objects; task objects report `0` because session activity has no observed task to attribute. A nonzero count makes the corresponding view incomplete. |
| `cost_semantics` | `estimated`. |
| Timeline `session.completed.cost_usd` | Known subtotal only when that session's pricing is complete; otherwise `null`. Existing telemetry history is revalidated for the response, without rewriting stored records. |
| `/usage` `actual_cost` | Recorded, unverified value with `actual_cost_semantics="recorded_unverified"`; not a provider invoice and not a replacement for missing pricing. |

Clients must check `cost_complete` and source status before describing a subtotal
as a full cost. In particular, `{estimated_cost_usd: 0, cost_complete: false}`
means **no priced subtotal is available**, not “this session was free.” A mixed
view can have a positive known subtotal and still be incomplete. A coverage ratio
of `1` can coexist with `cost_complete=false` if sessions have no usage records.

Session list/detail/search pricing covers the session lifetime. `/usage` retains
its existing token accounting: sessions are selected by `started_at`; auxiliary
rows (`task != ''`) by `last_seen`; main-session token duplicates are excluded.
Its pricing window and pricing day/model/task buckets use usage `last_seen`.
`window_attribution="last_seen"` and `window_exact=false` disclose the cumulative
attribution. A recent session with only old usage rows may therefore have known
lifetime pricing but unknown pricing in the requested usage window. An activity
bucket without pricing rows is incomplete; an entirely empty, readable activity
window remains a complete zero.

`/cost/*` and snapshot aggregates describe coverage of their matching usage rows;
they do not perform `/usage`'s additional session-activity completeness check.
An empty, readable usage source can give a complete zero in those aggregates
while a session without usage has unknown pricing. This distinction is explicit;
these scopes must not be presented as interchangeable session-coverage metrics.

## Diagnostics and nullable health inputs

| Field | Meaning and nullability |
| --- | --- |
| `launchd.managed` | Boolean observed management status, or `null` before a usable observation / on query failure. `null` is not “unmanaged.” |
| `sample_status` | `pending`, `ready`, `refreshing`, `stale` or `unavailable`. |
| `sampled_at` | Epoch time of observation completion; `null` before any observation. |
| `sample_age_seconds` | Monotonic observation age; `null` before any observation. |
| `refresh_interval_seconds` | Requested sampling interval, currently `30`. |
| Errors `count_30m` | Parsed records in the requested recent window, or `null` when the log/timestamps are unavailable. With `timestamp_status="partial"`, this is only the known subset, not an exact total. |
| `timestamp_status` | `known`, `partial` or `unavailable`. `timestamp_unknown_records` counts relevant headers that could not be resolved; `future_records` counts parsed future records excluded from the recent count. |

Diagnostics refresh in the background when read. From age 30 to less than 60
seconds, `refreshing` retains the previous observation for health evaluation.
At age 60 seconds it becomes `stale` and health is unknown; a failed completed
collection becomes `unavailable` on the next read. A successful refresh replaces
the old result on the next read, including newly observed service failures.
Clock changes do not affect freshness. Cold starts are `pending` and may yield
warning until the first collection completes.

Sampling is **read-driven**, not a periodic background timer. After at least
60 seconds idle, the first read can return stale/unknown while scheduling a
refresh. Slow external monitors must allow a follow-up read; HUD UI/WS polling
normally reads every two seconds. This known behavior is not a deployment
acceptance claim. Health-change event emission has a separate pre-existing
ordering issue; clients should use health responses rather than relying on that
event as proof of transitions.

Database-wide statistics are shared across locales for 30 seconds. Database
replacement, configured timezone and day boundary invalidate them; WAL changes
may appear at the next sample. Gateway and active-session data still refresh
with the two-second snapshot. Sampling metadata distinguishes freshness from
service status; consumers must preserve that distinction.

Log timestamps with an explicit offset use it. Naive timestamps use the producer
process's local timezone, or explicit `HUD_LOG_TIMEZONE` (IANA name) when the
producer uses a different zone. `HUD_TIMEZONE` controls statistics grouping,
not log parsing. Ambiguous/nonexistent DST times without offsets are unknown;
future records are excluded from the recent count.

## Privacy and read-only boundary

Session titles are sanitized before truncation. Session detail `cwd` is sanitized
like active-session paths; `null` and empty paths retain their values. Search
`%`, `_` and backslash characters are literal. State queries use read-only
connections; only HUD's own telemetry is writable. These changes neither grant
write APIs nor change Dashboard authentication.
