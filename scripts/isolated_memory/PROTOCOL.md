# Finite remote memory experiment

This test branch adds private diagnostic tooling, not a product release. A successful run means finite execution evidence is valid; memory risk remains WARN_NOT_ACCEPTED and public release remains BLOCK. Historical memory growth is still unassigned. No new growth acceptance threshold is invented.

## Authorization and workflow

The owner authorized preparation and push of this public test branch, then one SHA-bound remote execution after a focused safety review. No main change, version change, merge, tag, release or promotion is authorized. Do not publish private historical reports, user paths, credentials or raw evidence. Nonblocking remarks are recorded without another preparation loop.

The branch derives from candidate c9f90b3ca0559221859f26bb2e35da9c2e72116d. The existing fresh-install.yml filename is reused only on this branch because GitHub requires a registered default-branch workflow for manual dispatch; dispatch must specify the reviewed test branch. There are no push, pull_request or schedule triggers here. Checkout uses the reviewed full SHA, no persisted credentials, read-only repository permission, and immutable action revisions.

Before dispatch, the controller must write an exclusive local dispatch claim containing the grant ID and exact reviewed SHA and freeze digest. Check branch HEAD remotely first; issue only one API request. An ambiguous dispatch outcome consumes the grant: inspect run metadata, never retry the request. The workflow itself rejects run_attempt other than 1 and consumes exclusive setup and experiment claims before running. Fresh CI files alone cannot prevent a different manually created dispatch; the local consumed grant plus API readback is the authority boundary. No old claims or native permits are reused.

## Environment and fixture

Use a fresh GitHub-hosted macOS runner, Python 3.13 and Hermes 0.19.0. The setup step has a 30 minute GitHub timeout and an 1800 second monotonic setup budget. venv creation is synchronous; cancellation/cleanup is not a deterministic hard OS deadline. Installation subprocess stdout and stderr are DEVNULL. Measured children get an explicit minimal environment, never copied GitHub tokens, provider keys or user settings. No custom secrets are referenced.

Both arms use freshly created synthetic homes with the same epoch and data: 5000 sessions, 200000 messages, 4900 usage rows, 20 active sessions, 4980 ended sessions, 2000 tool messages, 1000 skill ledger records. SCHEMA_SQL is read by AST from the pinned public distribution, never by running its schema/config modules. Missing required DDL is a feasibility failure; it is not patched into success. Counts are independently read through mode=ro and query_only, the main DB path is exact, and only the two newly owned source files are hashed. Timeline event total is not inferred.

Fixture hashes must match across arms and remain unchanged. Public CLI, FastAPI, Starlette, Uvicorn, psutil and websockets Python tree fingerprints and interpreter/distribution versions are recorded before/after. This is not the historical Mac mini/Python 3.14 environment, a full DDL migration proof or final v2.0.0 compatibility acceptance.

## Loads and intervention

Order is sham then snapshot, both trace_depth=1 from the same pre-host-import point. Each arm has warmup 60 seconds, baseline idle 120 seconds, four cycles of load 300 and cooldown 180, then final idle 120. At baseline and each cooldown, both arms reserve a 30 second window. Sham never captures a snapshot; snapshot has five checkpoints, all compared with the first retained baseline. No forced GC, allocator trim or vmmap. Snapshot temporaries are released normally; the baseline remains held intentionally. Filenames, including pseudo and relative names, are hashed without resolving or exporting paths. This is filename provenance, not allocation ownership.

Load runs four bounded REST endpoints on rotating locales plus a real authenticated WebSocket frame lane. No redirects, proxies, production port 9119 or external child network destinations. HTTP/WS bodies and session token remain memory-only. The host's auth gates are not monkeypatched or weakened. Dashboard stdout/stderr are DEVNULL. Public urllib3 is identically preloaded in both arms before tracing and audit; its optional import-time IPv6 capability probe is not a request to an existing service. Audit starts after this dependency preload. Python audit guards do not provide kernel containment and do not cover every metadata/ctypes operation; fresh GitHub isolation, explicit environment and no secret injection are the primary separation from real user data. Child subprocess operations are refused; system diagnostic availability is outside this experiment's acceptance scope.

## Validity resources and cleanup

Pair budget 6000 seconds, arm budget 3000, cleanup reserve 20, startup 120, each checkpoint completion below 30. Every parent tick checks full PID, creation time, cwd and argv, process RSS, available memory, disk, sampler heartbeat and self footprint. Start thresholds are 3 GiB available and 5 GiB disk; running floors 512 MiB available and 1 GiB disk; process ceiling 2500 MiB. These are safety guards, not a leak pass threshold. A synchronous operation may delay a guard; GitHub step cancellation and monotonic guards are bounded mechanisms, not deterministic OS deadlines.

Samples every 2 seconds carry separate RSS, Mach self resident_size, phys_footprint, compressed, traced current/metadata bytes, threads, FD and three cache counts. Phase and last-60-second count coverage must both be at least 90 percent; actual maximum gaps are reported. Checkpoint activity allows a 32 second heartbeat tolerance; ordinary heartbeats allow 10. Sample coverage remains required during the scheduled non-checkpoint phases.

Signals require PID, birth, exact synthetic-home cwd, fixed observer entry and full argv with the owned non-9119 port. Recheck before TERM and again before KILL; unknown identity receives no signal. TERM waits 15 seconds, KILL at most 5. A natural early exit is not fabricated into identity-matched cleanup. Failures stop the second arm, preserve fixed diagnostics and never automatically retry. Missing terminal evidence, cleanup or tool/source hashes cannot be upgraded.

## Independent interpretation and artifacts

The offline analyzer imports neither runner nor host and never opens a DB, synthetic home or service log. It verifies recorded cleanup, tool bindings, fixture counts/hashes, phase order/load, sample/tail coverage, five checkpoints and no GC; live process exit remains a recorded fact rather than an offline OS observation. It reports each arm's final-minus-baseline and four-cooldown-point OLS only. Comparing absolute memory between arms is forbidden. Sequential order, system pressure and tracing/checkpoint instrumentation confound causal inference. Net traced bytes cannot rule out product/native retention; RSS versus compressed differences are not a conservation equation.

Only the analyzer's fixed-schema aggregate projection is uploaded. No raw service log, HTML, token, allocation text, source database, fixture configuration, backup, ZIP or historical private evidence. Failure is DIAGNOSTIC_ONLY_NOT_VERIFIED, never PASS. A valid finite run is not long-term no-leak proof, historical cause attribution, user risk acceptance or public release PASS.

Local tests use injected process/trace/transport models and generated aggregate records. They reject subprocess, network, SQLite and signal attempts after dependency preload. No local host/Mach call is executed. Their model success does not verify real CI transport, host startup or resource cleanup. One focused code/workflow safety review precedes the single remote run; no further per-low-item audit cycle is required.
