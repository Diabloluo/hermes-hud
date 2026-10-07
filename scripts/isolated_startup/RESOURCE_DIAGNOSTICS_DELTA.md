# Initial resource diagnostics preparation

Private offline v6 preparation, not product v2.0.0 or execution. Last run37568873965
remains FAIL at resource before RUN_CLAIM/init/spawn, HTTP/WS0. Its resource values
and actual query exception remain UNKNOWN and are never backfilled.

Initial admission thresholds remain inclusive: available memory>=3221225472 bytes
(3 GiB), owned-root disk free>=5368709120 bytes (5 GiB). Short circuit unchanged:
one dependency load, one memory query, at most one disk query and only after memory
passes. No retry or added probe. All running checks, budgets, identity/signal rules,
sources, guards, synthetic optional contracts, token/HTTP/WS and actual-exit0 remain.

resource_diagnostics.KEYS is exact; byte scalars strict int 0..2**63-1 (bool/float/
negative/overflow rejected). Below-threshold values retained; failed/unattempted
values null, never zero-filled. SKIPPED means unattempted; ERROR means attempted
but no accepted scalar. Fixed errors: dependency_failed/permission_denied/os_error/
query_error/invalid_scalar, no type names/text/path/PID/argv/credentials/total RAM.
psutil-specific exceptions without an OSError ancestry use query_error rather than
guessing class names. Scalars mean admission resources, not footprint or attribution.

Lifecycle adds resource_diagnostic and resource_diagnostic_error. The getter reads
a cached projection, never measures. Missing/malformed/raising diagnostics or bool/
projection disagreement forbid NATIVE success. MODEL may omit projection, not
native evidence. Early prepared/authority/active failure can have no projection;
interrupted queries stay FAIL with unavailable/read_failed diagnostics. First
resource cause is preserved; diagnostic error is separate. Measurement BaseException
propagates to lifecycle; getter BaseException maps to read_failed, never success.

Independent analyzer imports only the inert validator, not psutil/runner. New
fields are validated BEFORE both FAIL export and PASS. Unknown/raw fields dropped.
Same-process record consistency does not attest true measurements or OS transport.
Backend/completion/freeze v6 reject v5, while child/guard v3, file boundary v2 and
interpreter v3 are unchanged. Old FAIL requires old analyzer.

Future report: WORKBUDDY_REMOTE_SHORT_STARTUP_RESOURCE_DIAGNOSTICS_REVIEW.md.
After independent accepted review and separate specific owner authorization only,
place a byte-identical HERE report copy and bind digest in new acceptance/grant.
Scope: one_owned_resource_diagnostic_startup_300s_http1_ws1_no_retry_no_risk_acceptance.
Preparation creates no gates/copy/claim/run/push. Old SETUP/DISPATCH consumption
prohibits retry even without RUN_CLAIM. Future proposal still installation<=1800s,
startup<300s, HTTP/WS each once, failure/unknown no retry, no production/main/version
or risk acceptance. Preparation is not dispatch or threshold-change authorization.

Tests use injected objects and cooperative process models only, no real psutil,
OS pipe, resource measurement or host startup. Audit begins after preloads/fixed
public-source hash reads, not interpreter startup or kernel containment.
HOST/HTTP/WS/CI NOT VERIFIED; historical causes UNKNOWN.
MEMORY NOT CLOSED/WARN_NOT_ACCEPTED; PUBLIC RELEASE BLOCK.
