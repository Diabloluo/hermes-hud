# B1 actual exit status acceptance correction

2026-10-05. This is a new private directory, not an overwrite of the reviewed
2026-10-04 tool or report. B1 is corrected in the parent success path and the
independent analyzer; native execution remains NOT_RUN. Dot is the requested
temporary independent reviewer. No permit/claim/report copy/dispatch is created.

## Minimal implementation delta

lifecycle.py leaves close_owned and every signal/identity/budget operation
unchanged. After validated child PASS, actual cleanup.exit_code must have strict
type int, equal 0, and equal child.exit_code before candidate can become PASS.
Successful safe KILL cleanup may still have error=None and exit=-9, but startup
acceptance becomes FAIL with error=finish. Original signed exit status, child
record and consumed-claim state are retained, not rewritten to simulate exit0.

analyze_integration.py independently enforces strict int exit0 and equality to
the child exit code. Valid nonzero-exit FAIL records remain DIAGNOSTIC_ONLY;
forged completion PASS over nonzero/mismatched/bool/null/text/float exits is
rejected. Neither implementation imports the other's success predicate.

entry.py only adds test_exit_status.py and this document to the 24-file freeze.
controller.py only changes REPORT to DOT_REMOTE_SHORT_STARTUP_EXITFIX_REVIEW.md.
The reviewer original belongs in the new review directory; a future byte-identical
copy into the tool root is a separately authorized step. Do not reuse the old
BLOCK report as an acceptance, and do not invent the dot report or its hash.
The existing payload/schema stays compatible, but new freeze/report digests
prevent old authorities from authorizing the changed files. This stage creates
neither gates nor a new grant. PROTOCOL.md incorporates the B1 status, dot name,
current counts and truthful wording for the previously registered O1/O4/O8
limits; it does not change executable boundaries.

## Reproduction and regression evidence

TerminalFirstIO uses real ChildLifecycle to create a clean PASS after the four
acknowledgments BEFORE the simulated original Popen handle receives its final
wait status. These are deliberate same-process, in-memory fixtures, not a real
host/psutil/event-loop/pipe/signal run. Both MODEL and simulated NATIVE record
paths are exercised. NATIVE labels in this test are not execution receipts.

42 new cases: parent18 (six nonzero codes in two modes, KILL2, zero controls2,
child/actual disagreement2); analyzer24 (ten actual-code mutations in two modes
plus four child/actual disagreement cases). All 258 prior cases are retained.

BEFORE_REPAIR runs the unchanged old parent/analyzer with the new tests: 300 total,
24 assertion failures, exit1, all post-preload prohibited attempt counters zero.
This is an expected defect reproduction, not a native or product test run.
AFTER_REPAIR is 300/300, exit0; FINAL after freeze is the current evidence.
Each command, cwd, input hash, actual count and complete merged output is saved.

The initial FIRST_HARNESS_ABORT hit the first modeled B1 assertion, after which
unittest's default traceback formatter tried a linecache source read; the existing
no-open audit hook refused it. No complete test total/footer was emitted. The
new fixed result formatter keeps failure counts but omits exception text/source
tracebacks; the hook is not broadened. The abort is retained, never upgraded.
Copy preparation also initially normalized one audit_adapter trailing newline;
it was restored byte-identically before the final corrected run. No executable
policy change occurred, and no previous directory was edited.

## Scope carried forward

No retry, real-user data, production9119, permissions, source-manifest/fixture/
auth/HTTP/WS argv/identity checks/TERM/KILL/resources/budgets/CI action edits.
No original reviewed file or historical FAIL/claim is changed. The old Workbuddy
report's non-B1 observations remain registered; dot is not asked to repeat the
65-item audit or to read the whole old protection chain. Mechanical byte/hash
comparison and actual fixed-file readback support the declared small delta;
they do not prove current Git/remote/host compatibility or native execution.

Only independently accepted dot review may support requesting a new concrete
single remote short-startup grant. Successful review is not that grant, not
memory-risk acceptance and not a public release decision.

HOST/HTTP/WS/CI NOT VERIFIED. MEMORY NOT CLOSED / WARN_NOT_ACCEPTED.
PUBLIC RELEASE BLOCK. No growth acceptance threshold is created.
