# Direct interpreter and cleanup correction

Preparation only. This private v3 tool removes one unsupported synchronization
assumption: successful Popen of a macOS framework wrapper does not acknowledge
the wrapper's later interpreter handoff. It does not prove that handoff caused
run37301504760. Its raw argv/exe and exact CI build remain unknown.

## Direct launch and child context

Before spawn, bind_parent captures the trusted parent launcher/prefix, OS argv0,
OS exe and launcher/image SHA256. binding schema is v3. revalidate_binding checks
the canonical prebound image, owned venv prefix and both actual-file hashes.
direct_launch requires the fixed 11-argument command, -I/-B, exact observer path,
dashboard/127.0.0.1, canonical ASCII decimal non9119 port and no-open/skip-build.

Popen receives argv=[bound parent argv0]+the unchanged argument tail and
executable=bound parent OS exe. The wrapper is not executed in this child.
__PYVENV_LAUNCHER__ is added to the existing explicit minimal environment with
the prebound owned venv launcher value. No caller environment is copied, and no
child observation chooses an executable or argv0. The post-rehash pre-spawn
budget still reserves 20 seconds within 300; no wait loop, extra Popen or retry
is introduced. A direct-image failure does not fall back to the wrapper.

Before importing psutil or the host, observer_smoke requires the child's
sys.executable and resolved sys.prefix to match the owned venv, orig_argv length
11 with -I/-B, isolated strict int1 and no-bytecode strict True. A lost or ignored
venv launcher hint fails closed. This is not proof that the proposed Python3.13
CI build supports this launch mode; current test Python is 3.14.

CPython v3.13.0 reference getpath.py:265-284 and getpath.c:898-903 load the special
launcher hint and use it for executable/venv discovery. This is source-based
mechanism support, not a statement of the actual runner build. The source links
and claim limits are in DIRECT_SOURCE_REFERENCES.json. Native compatibility is
not inferred from models, and no real interpreter probe has been executed here.

## Initial admission and cleanup

The first full PID/birth/cwd/argv/exe check remains exact. The child image must
already be the prebound direct image; intermediate or unknown images are not
temporarily accepted. Birth is captured once within the existing spawn window;
only a matching original PID can establish the cleanup seed. Seed command/image/
cwd always come from the trusted launch contract. A separate captured birth
prevents mutating seed.birth into a new authority.

If expected() fails before returning, lifecycle may ask cleanup_expected for
the original handle's reconstructed seed. Same PID on a different handle is
rejected; malformed, changed or absent seeds return no authority. It is never
used as a substitute for successful admission or to clear the first diagnostic.
Unknown or changed identity still gets zero signals. The old close_owned body
is byte-identical and checks exact live identity before TERM and pre-KILL; its
15/5-second waits and natural-exit failure semantics are unchanged. Cleanup may
succeed after a transient mismatch ends, but the original experiment still FAILs.

This is a disclosed change in cleanup data availability, not OS attestation:
the prebound seed no longer disappears solely because a Python call raised.
Same-privilege model data and live inspection are not independent kernel proof.
If a first inspection raises or has wrong PID/birth window, no seed is available.
No synthetic field fills a missing cleanup match or exit code.

## Unchanged release and isolation boundaries

One fresh owned setup≤1800s and startup≤300s only; HTTP/WS once, no production9119,
no tracing/GC/vmmap, no acceptance growth budget, no real home/config/DB/logs,
no product version/main writes or publication. Full GuardStack and source checks,
payload/completion separation, actual exit0 versus child exit0 and diagnostic
disqualifiers remain. Nondeterministic blocking IO/deadline and partial public
dependency closure limitations remain. Analysis validates record consistency,
not actual transport attestation; FAIL cannot be upgraded.

Backend, completion, freeze, interpreter binding now use v3. Scope and report
name change together; old evidence requires its old analyzer. Old27 frozen
inputs, run37301504760 FAIL and consumed claims are retained without backfilling.
Protocol contains a new current section and preserves older text as history.

Future independent review must assess actual code delta, no-child-adoption,
binary drift before spawn, child context, failure cleanup and no PASS upgrades.
The same-name reviewer report must be byte-identical at HERE before any later
acceptance; no report/acceptance/authority/claim is created by this preparation.
No command authorizing native execution is supplied with this review.

HOST/HTTP/WS/CI NOT VERIFIED. Historical root cause UNKNOWN.
MEMORY NOT CLOSED / WARN_NOT_ACCEPTED. PUBLIC RELEASE BLOCK.
