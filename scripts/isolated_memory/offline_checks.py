"""Offline-only test harness. Audit follows dependency preloading; no ctypes/process/DB/network."""
import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_pair
import test_runner_profile
import observer_smoke
import ctypes
import sqlite3
import tempfile
import ssl
import signal
import subprocess
import urllib.request
import asyncio
import venv
HERE=Path(__file__).resolve().parent
inputs=tuple(HERE/n for n in test_pair.entry.FILES if n!='offline_checks.py')+(HERE/'offline_checks.py',)
allowed={str(p) for p in inputs}
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
        writing=(type(mode) is str and any(c in mode for c in 'wax+')) or (type(flags) is int and flags & 577)
        if writing:category='write'
        elif type(path) is not str or path not in allowed:category='outside_read'
    if category:
        attempts[category]+=1;raise RuntimeError('offline_boundary')
sys.addaudithook(audit)
sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
for p in inputs:
    if p.suffix=='.py':ast.parse(p.read_bytes())
output=io.StringIO()
result=unittest.TextTestRunner(stream=output,verbosity=2).run(unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_pair,test_runner_profile)]))
record={'schema':'hud_same_trace_pair_offline_receipt_v1','tests':result.testsRun,
 'python_version':sys.version,
 'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
 'exit':0 if result.wasSuccessful() else 2,'inputs':sources,'attempts_after_hook':attempts,
 'audit_scope':'PRELOADED_IMPORTS_AND_INTERPRETER_STARTUP_NOT_COVERED_CTYPES_DENIED_AFTER_HOOK',
 'model_scope':'COOPERATIVE_IN_MEMORY_NATIVE_RECORD_FIXTURES_AND_ASYNC_RUN_ARM_NO_REAL_PIPE_MACH_PSUTIL',
 'unittest_output':output.getvalue(),'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK'}
print(json.dumps(record,ensure_ascii=False))
raise SystemExit(record['exit'])
