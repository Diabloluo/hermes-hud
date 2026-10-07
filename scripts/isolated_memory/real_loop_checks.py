"""One real stdlib loop with synthetic IO only. Loop infrastructure is created before audit."""
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import asyncio
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_async_loop
import test_pair
import execution_diagnostics
import ctypes
import sqlite3
import subprocess
import signal
HERE=Path(__file__).resolve().parent
inputs=tuple(HERE/n for n in test_pair.entry.FILES)+(test_async_loop.LEGACY,)
allowed={str(p) for p in inputs}
# One genuine SelectorEventLoop and its stdlib self-wakeup socketpair. No host/socket endpoint.
loop=asyncio.new_event_loop()
test_async_loop.LOOP=loop
attempts={'process':0,'network':0,'sqlite':0,'signal':0,'native_library':0,'write':0,'outside_read':0}
def audit(event,args):
    category=None
    if event in ('subprocess.Popen','os.system','os.fork','os.exec','os.posix_spawn'):category='process'
    elif event.startswith('socket.'):category='network'
    elif event=='sqlite3.connect':category='sqlite'
    elif event in ('os.kill','os.killpg'):category='signal'
    elif event in ('ctypes.dlopen','ctypes.dlsym'):category='native_library'
    elif event=='open':
        path,mode,flags=args
        if (type(mode) is str and any(c in mode for c in 'wax+')) or type(flags) is int and flags & 577:category='write'
        elif type(path) is not str or path not in allowed:category='outside_read'
    if category:
        attempts[category]+=1;raise RuntimeError('offline_boundary')
sys.addaudithook(audit)
sources={str(p.relative_to(HERE)) if p.is_relative_to(HERE) else 'bound_prior_native_io.py':
 hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
started=loop.time()
out=io.StringIO()
try:
    result=unittest.TextTestRunner(stream=out,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_async_loop))
    pending=len(asyncio.all_tasks(loop))
finally:
    loop.close()
record={'schema':'hud_pair_real_loop_synthetic_receipt_v1','tests':result.testsRun,
 'python_version':sys.version,'loop_class':type(loop).__name__,
 'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
 'exit':0 if result.wasSuccessful() and pending==0 else 2,'elapsed_seconds':loop.time()-started,
 'pending_tasks_at_end':pending,'loop_closed':loop.is_closed(),'inputs':sources,
 'attempts_after_hook':attempts,'unittest_output':out.getvalue(),
 'audit_scope':'IMPORT_PRELOAD_AND_ONE_REAL_LOOP_CREATION_SELF_WAKEUP_SOCKETPAIR_NOT_COVERED_AFTER_HOOK_ALL_SOCKET_EVENTS_DENIED',
 'execution_scope':'REAL_STDLIB_SELECTOR_EVENT_LOOP_SCHEDULER_WAIT_FOR_CANCELLATION_SYNTHETIC_CONNECTOR_PROCESS_PHASES_FIXTURE_AND_DATA',
 'not_verified':['REAL_WEBSOCKETS','OS_TRANSPORT_PIPE','REAL_HOST','MACH','PSUTIL','HTTP','CI','NATIVE_TIMEOUT_BEHAVIOR'],
 'runtime_timeout_seconds':10,'timeout_overridden':False,
 'legacy_method_sha256':test_async_loop.LEGACY_SHA,'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK'}
print(json.dumps(record,ensure_ascii=False))
raise SystemExit(record['exit'])
