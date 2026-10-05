# Remote single short startup backend — preparation only

This directory is a private diagnostic tool, not a product version. Current state:
IMPLEMENTED_OFFLINE / NATIVE_NOT_RUN. No gate, permit, claim, accepted-report copy,
remote branch update or execution is created by this preparation. This is the
2026-10-05 B1 exit-status correction; EXIT_STATUS_REPAIR.md specifies its delta.

## Frozen proposed scope

One fresh macOS CI installation (1800 s maximum observed setup budget) and one
owned synthetic startup (300 s, reserving 20 s for cleanup). It is **not** the old
100-minute pair and cannot reuse its grant. Only one authenticated plugin HTTP
`/settings` call and one high-level `/events?locale=en` WS connect/recv; readiness TCP
polling is not an additional HTTP/WS call. No GC, tracing, vmmap, growth budget,
production 9119 access, real-home fallback, version change or release.

Candidate file contract: c9f90b3ca0559221859f26bb2e35da9c2e72116d, 16 relative
dashboard runtime files. Public distribution: hermes-agent 0.19.0; dependencies
psutil 7.2.2 and websockets 15.0.1. Five public critical files are byte-bound in
SOURCE_MANIFEST.json. They are **not a full transitive dependency closure**; other
fresh-venv public files are readable. Floating macos-latest and the unpinned
transitive installer dependencies remain limitations. Do not claim host compatibility
before an actual authorized run. The source manifest uses hermes_state.py because
that is the published 0.19.0 SCHEMA_SQL module; no fallback DDL is invented.

## Authority and single consumption

Local controller reads exactly AUTHORIZATION.json, REVIEW_ACCEPTANCE.json,
FREEZE.json and the accepted same-name report. Its runtime checks do not use
assert. It checks the dedicated test branch SHA, rechecks expiry, exclusively
creates DISPATCH_CLAIM.json, then makes **one POST**. Timeout or unknown outcome
is OUTCOME_UNKNOWN_NO_RETRY; the claim is never removed. An API acknowledgement
is not execution success. Local single consumption does not promise global
server deduplication against another actor manually creating a dispatch.

Future report location in the review directory is not the controller binding
location. Before any separately authorized execution, place a **byte-identical
copy** named DOT_REMOTE_SHORT_STARTUP_EXITFIX_REVIEW.md in this directory.
controller.REPORT enforces this corrected name.
Verify its SHA against the reviewer original; bind that SHA in the acceptance
and authority. Do not synthesize a PASS report or overwrite the original.

Authority has exactly schema/id/scope/freeze_sha256/review_sha256/issued/expires/
max_runs/owner_confirmed/sha/repository/branch. Schema and scope are those in
controller/lifecycle; max_runs is strict integer 1, confirmation strict True,
expiry window ≤1 hour. Acceptance has exactly schema/sha/freeze_sha256/
report_sha256/safety/scope. The concrete new SHA will be known only after a
separately authorized exact-file test-branch delivery; no SHA is fabricated here.

Remote job additionally binds repository, workflow_dispatch, run_attempt=1,
dedicated test ref, reviewed SHA, the actual workflow bytes and tool freeze.
Re-run is rejected. Setup consumes SETUP_CLAIM before venv/install; the startup
consumes RUN_CLAIM before fixture/init/spawn. Failures and stale evidence are
not repairable in place for another attempt. The common active lock is held
through publication. No current gate is materialized in this preparation.

## Actual backend definitions

NativeIO implements Popen, full parent-derived pid/birth/cwd/argv/exe matching,
bounded readiness, authenticated HTTP/WS, fixed control acknowledgements,
owned cleanup and separate terminal seal. The 11-item command uses -I -B;
controller/child/entry/analyzer explicitly bind their same-directory imports.
One original Popen handle is retained even if identity admission fails. Before
TERM/KILL, full saved identity must match; unknown identity gets zero signal,
and a failed pre-KILL check gets no further signal. Natural exit is not an
identity-matched cleanup. Birth is checked against the spawn wall-clock window;
argv0/exe are derived from the trusted fresh-venv parent, not adopted from a
child. This is trusted same-privilege process observation, not OS attestation.

Fixture: 5000 sessions, 200000 messages, 4900 usage rows, 20 active/4980 ended,
2000 tool messages, 1000 skill records. DDL is extracted by AST from the fresh
public distribution; missing required fields stop, never add columns to pass.
Counts are queried with mode=ro/query_only and a single main database. Setup
creates only a new owned home; no existing home or user DB is inspected.

The synthetic session token is generated anew in RAM and passed through the
explicit child environment and authenticated transport. It is not read from a
real credential, saved in evidence, scraped from HTML or an auth monkeypatch.
Raw response/frame data are RAM-only and not actively persisted; dropping a
buffer reference is not secure memory erasure. Export contains only
bounded status/schema/byte/count scalars. DEVNULL child streams mean there are
no raw host logs to recover. Full identity/fixture metadata stay private in the
CI temporary root; upload is only aggregate-artifact/analysis.json.

## Child policy and terminal closure

The reviewed file adapter is an additional hook alongside the old network,
SQLite, child-process and signal guards, never their replacement. Public roots
are read-only; covered writes/SQLite are restricted to the owned synthetic home
and evidence. chdir is not audited by GuardStack and is not claimed contained.
Two exact darwin /proc probe call sites may each once receive a
synthetic OSError, without opening /proc. Unknown accesses remain sticky fatal.
An arbitrary extra flag is denied rather than guessed benign.

The child keeps one GuardStack, acknowledges ready/http/ws/finish with clean
sticky state, and emits a terminal record only after the host main returns.
The parent issues the commanded finish and only accepts a bound terminal with
clean guards, source_start=end, exit0 and verified owned cleanup. Source buckets
cover 16 candidate +5 public critical files +4 newly created synthetic seed
files; they do not prove every readable installed dependency unchanged.

Python audit is not a kernel sandbox: it does not prove complete native/fd/
ctypes/metadata containment. Bound frame hashes are source provenance, not OS
identity. Hook counters after preload alone are not a containment proof.

## Budgets, sealing and failures

Start thresholds: available RAM ≥3 GiB, disk ≥5 GiB. Running: available RAM
≥512 MiB, disk ≥1 GiB, host RSS <2500 MiB. Readiness ≤120 s; ack ≤10 s;
HTTP/WS open/read ≤10 s, WS close ≤2 s; TERM wait15/KILL wait5. No retry.
Each side checks elapsed budget, but blocking native operations and CI hard
termination can interrupt cleanup: **not a deterministic hard deadline**.
EnvBuilder itself is not interrupt-bounded by the Python controller; the
installation step timeout and post-check provide the disclosed outer boundary.

result.json is always provisional PENDING_TERMINAL_SEAL. Completion binds the
exact payload SHA, freeze and review. Missing/invalid seal is never PASS.
Budget/source/freeze rereads occur before completion publication. Completion
publication and interpreter exit are excluded from the measured pre-seal budget;
failed publication gives no authoritative PASS. Early/missing evidence produces
DIAGNOSTIC_ONLY_NOT_VERIFIED. Old schemas, raw fields, bool-as-int and malformed
FAIL evidence are rejected, not exported.

The independent analyzer does not import the runner, reopen DB/home/logs, or
inspect PIDs. It validates self-reported sealed evidence, not independently
attests actual transport. Highest future result is
VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY; a model-generated row with
that label is **not a real execution receipt**.

## Evidence and handoff limits

The prior 258 offline tests =169 unchanged regressions +89 backend tests remain.
The corrected suite is 300 =258 retained +42 B1 exit-status cases.
Popen/process/OS files are modeled; HTTP uses a fake opener; WS uses cooperative
immediate awaits, **not a real event loop/socketpair or OS pipe**. Entry setup and
controller call their real functions with modeled IO. Observer full boot/loader/
worker lifecycle is statically reviewed, not dynamically exercised as a host.
Audit is installed after dependency preloads and fixed source reads; it blocks
open/process/network/SQLite/signals during tests. Actual counts/exit/output and
input hashes are in receipts. Current-platform test Python is 3.14, not the
proposed fresh CI Python3.13; syntax/import tests do not prove remote compatibility.

readback.py separately runs true freeze_check and source group hashing against
an exact fixed read whitelist; no authority(), fixture(), host or native IO run.
It does not expand historical protective manifests or read synthetic-home.
The first metadata construction failed on a nonexistent hermes_state_common.py;
the actual published module was then selected. Historical native failures,
unknown root causes, all old records and consumed claims are untouched.

Next boundary: one incremental read-only dot review of B1 and the bounded delta,
retaining the prior Workbuddy non-B1 findings rather than reopening 65 files.
Only a new concrete single-run authority
after that review may permit test-branch delivery/run. No optional wording
comment requires a new preparation–review–confirmation loop.

The old review's nonblocking limits remain: a single high-level WS connect does
not independently prove one library-internal handshake or redirect refusal;
actual host compatibility and launchd-related fail-closed behavior are unverified;
DEVNULL does not forbid private owned-home files. No new transport guarantees,
kernel containment, dependency closure or risk acceptance is claimed here.

Always retained: HOST/HTTP/WS/CI NOT VERIFIED; MEMORY NOT CLOSED /
WARN_NOT_ACCEPTED; PUBLIC RELEASE BLOCK. No memory attribution claim, risk
acceptance, version stamp or product/public PASS follows from this preparation.

## Diagnostic v2 superseding delta (offline only)

The preceding B1 history remains preserved. This directory is a new v2 backend,
completion and freeze schema; child-terminal schema remains v1. See the frozen
DIAGNOSTICS_DELTA.md for bounded first-failure sites, comparison booleans and
original-handle observation. No raw identity values or exception text are exported.
close_owned is byte-identical; no new signal authority or identity inspection is
added. One extra poll of the original handle is a separate observation, not an
identity match and not a substituted transport or cleanup exit code. Parent and
analyzer both reject successful candidates with diagnostics or a nonzero/unknown
final handle observation. All B1 actual-exit conditions remain enforced.

This preparation creates no gates and authorizes no native run or push. Future
materialization, only after separate concrete owner authority, must bind the new
freeze and a byte-identical accepted DOT_REMOTE_SHORT_STARTUP_DIAGNOSTICS_V2_REVIEW.md
at HERE. Old consumed grants/claims are never reusable. Old v1 failures require
the old analyzer. Historical root cause remains UNKNOWN; current host compatibility,
memory risk closure and public release are not verified by these offline models.
