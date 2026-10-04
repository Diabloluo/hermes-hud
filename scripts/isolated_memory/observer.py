"""Fresh CI child. Scalar self memory and hashed filename provenance, never raw output."""
import ctypes
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import threading
import time
import tracemalloc

# -I excludes the script directory; this exact reviewed directory is explicit.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import atomic, read, protocol, require, Refused, LABELS
from identity_contract import FAILURE_STAGES, FAILURE_CODES
_failure_out = None
_failure_stage = 'preload'


def failure_record(error, stage):
    require(stage in FAILURE_STAGES, 'failure_stage')
    code = 'internal'
    if type(error) is Refused and len(error.args) == 1 and type(error.args[0]) is str \
            and error.args[0] in FAILURE_CODES:
        code = error.args[0]
    site, tb, frames = None, error.__traceback__, 0
    while tb is not None and frames < 128:
        site = {'filename_sha256': hashlib.sha256(tb.tb_frame.f_code.co_filename.encode()).hexdigest(),
                'line': tb.tb_lineno}
        tb, frames = tb.tb_next, frames+1
    if tb is not None:
        site = None
    return {'schema': 'hud_remote_observer_failure_v2', 'error': code, 'stage': stage,
            'site': site, 'site_semantics': 'filename_provenance_only_not_source_hash',
            'raw_persisted': False}



class VMInfo(ctypes.Structure):
    _pack_ = 4
    _fields_ = [('virtual_size', ctypes.c_uint64), ('region_count', ctypes.c_int32),
                ('page_size', ctypes.c_int32)] + [(k, ctypes.c_uint64) for k in (
        'resident_size', 'resident_size_peak', 'device', 'device_peak', 'internal', 'internal_peak',
        'external', 'external_peak', 'reusable', 'reusable_peak', 'purgeable_volatile_pmap',
        'purgeable_volatile_resident', 'purgeable_volatile_virtual', 'compressed',
        'compressed_peak', 'compressed_lifetime', 'phys_footprint')]


def self_vm():
    lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
    lib.mach_task_self.restype = ctypes.c_uint32
    lib.task_info.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_void_p,
                             ctypes.POINTER(ctypes.c_uint32)]
    info = VMInfo()
    count = ctypes.c_uint32(ctypes.sizeof(info)//4)
    rc = lib.task_info(lib.mach_task_self(), 22, ctypes.byref(info), ctypes.byref(count))
    require(rc == 0 and count.value >= ctypes.sizeof(info)//4, 'mach_scalar')
    return {k: getattr(info, k) for k in ('resident_size', 'phys_footprint', 'compressed')}


def checkpoint(trace, baseline):
    import hashlib
    current = trace.take_snapshot()
    stats = current.statistics('lineno')
    deltas = [] if baseline is None else current.compare_to(baseline, 'lineno')
    # All filenames, including pseudo/relative paths, are hashed without resolve.
    # Hash grouping is file provenance ONLY, never allocation ownership.
    top = [{'file_sha256': hashlib.sha256(s.traceback[0].filename.encode()).hexdigest(),
            'line': s.traceback[0].lineno, 'bytes': s.size, 'blocks': s.count}
           for s in stats[:25]]
    row = {'trace_records': len(current.traces), 'snapshot_bytes': sum(s.size for s in stats),
           'delta_rows': len(deltas), 'net_delta_bytes': sum(s.size_diff for s in deltas),
           'top': top, 'interpretation': 'filename_provenance_only_not_ownership'}
    return row, current if baseline is None else baseline


def boot():
    global _failure_out, _failure_stage
    require(os.environ.get('HUD_REMOTE_CHILD') == '1' and sys.platform == 'darwin', 'child_authority')
    p = protocol()
    home, out, repo = (Path(os.environ[k]).resolve() for k in ('HERMES_HOME', 'HUD_OUT', 'HUD_REPO'))
    arm = os.environ['HUD_ARM']
    port = int(os.environ['HUD_PORT'])
    require(Path.cwd() == home and home.name == 'synthetic-home'
            and out == home.parent/'evidence' and home.parent.name == arm
            and home.parent.parent.name == 'hud-finite-owned'
            and arm in p['arms'] and 1024 <= port <= 65535 and port != 9119, 'child_scope')
    _failure_out, _failure_stage = out, 'preload'
    import psutil
    import signal
    # Pinned public networking library performs an optional IPv6 capability
    # probe at import. Preload identically in both fresh arms before the audit
    # hook and tracing, rather than turning its benign import into a fake failure.
    # This is not a production request or a probe of an existing local service.
    import urllib3  # noqa: F401
    _failure_stage = 'policy'
    # Public CI code and interpreter libraries are readable; writes are owned only.
    roots = (repo, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
             Path('/System'), Path('/usr/lib'), Path('/Library/Developer'))
    def audit(event, args):
        if event in ('socket.bind', 'socket.connect'):
            a = args[1]
            require(isinstance(a, tuple) and a[0] in ('127.0.0.1', '::1')
                    and a[1] == port and a[1] != 9119, 'network_boundary')
        if event == 'sqlite3.connect':
            raw = str(args[0]).split('?', 1)[0].removeprefix('file:')
            require(Path(raw).resolve().is_relative_to(home), 'sqlite_boundary')
        if event == 'open' and isinstance(args[0], (str, bytes)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1:3]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                type(flags) is int and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            owned = path.is_relative_to(home) or path.is_relative_to(out)
            require(owned or (not writing and any(path.is_relative_to(root) for root in roots)), 'file_boundary')
        if event in ('subprocess.Popen', 'os.system', 'os.fork', 'os.exec', 'os.posix_spawn'):
            # Diagnostics' subprocess availability is not part of this experiment.
            raise PermissionError('child_process_boundary')
    sys.addaudithook(audit)
    # Both arms begin tracing at the identical pre-host-import point.
    tracemalloc.start(p['trace_depth'])
    failed = threading.Event()
    own = psutil.Process()
    state = {'baseline': None, 'next': 0}
    def failure(error, stage):
        failed.set()
        atomic(out/'observer-failure.json', failure_record(error, stage))
    def sampler(mod):
        try:
            while not failed.is_set():
                c = read(out/'control.json')
                require(set(c) == {'phase', 'sequence'} and type(c['sequence']) is int
                        and c['phase'] in {x[0] for x in __import__('common').schedule(p)} | {'startup', 'checkpoint'},
                        'control')
                at = time.monotonic()
                row = {'at': at, 'phase': c['phase'], 'rss_bytes': own.memory_info().rss,
                       **self_vm(), 'traced_current_bytes': tracemalloc.get_traced_memory()[0],
                       'trace_metadata_bytes': tracemalloc.get_tracemalloc_memory(),
                       'threads': own.num_threads(), 'fds': own.num_fds(),
                       'snapshot_cache': len(mod._snapshot_cache),
                       'db_cache': len(mod.collectors._DB_SAMPLE._entries),
                       'diagnostic_cache': len(mod.collectors._DIAGNOSTIC_SAMPLES._entries)}
                with (out/'samples.jsonl').open('a') as stream:
                    stream.write(json.dumps(row, sort_keys=True)+'\n')
                atomic(out/'latest.json', row)
                atomic(out/'phase-ack.json', {**c, 'at': at})
                time.sleep(p['sample_seconds'])
        except BaseException as error:
            failure(error, 'sampler')
    def worker():
        try:
            while not failed.is_set():
                path = out/'operation.json'
                if path.exists():
                    req = read(path)
                    seq = req['sequence']
                    if seq > state['next']:
                        require(type(seq) is int and seq == state['next']+1 and seq <= 5
                                and set(req) == {'sequence', 'label', 'at'}
                                and req['label'] == LABELS[seq-1]
                                and 0 <= time.monotonic()-req['at'] < 30, 'operation')
                        values = None
                        if arm == 'snapshot':
                            values, state['baseline'] = checkpoint(tracemalloc, state['baseline'])
                        elapsed = time.monotonic()-req['at']
                        require(elapsed < 30, 'operation_budget')
                        atomic(out/f'checkpoint-{seq}.json', {'sequence': seq, 'label': req['label'],
                            'compare_to': None if seq == 1 else 1, 'snapshot_count': int(arm == 'snapshot'),
                            'gc_count': 0, 'seconds': elapsed, 'values': values})
                        atomic(out/'operation-done.json', {'sequence': seq, 'seconds': elapsed})
                        state['next'] = seq
                time.sleep(.05)
        except BaseException as error:
            failure(error, 'worker')
    original = importlib.machinery.SourceFileLoader.exec_module
    activated = False
    def load(loader, mod):
        nonlocal activated
        value = original(loader, mod)
        if Path(loader.path).resolve() == repo/'dashboard/plugin_api.py':
            require(not activated, 'duplicate_observer')
            activated = True
            threading.Thread(target=sampler, args=(mod,), daemon=True).start()
            threading.Thread(target=worker, daemon=True).start()
            atomic(out/'ready.json', {'arm': arm, 'trace_depth': 1, 'pid': os.getpid()})
        return value
    importlib.machinery.SourceFileLoader.exec_module = load
    # TERM causes Python finally handling where possible; parent still verifies exit.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    _failure_stage = 'host_import'
    from hermes_cli.main import main
    _failure_stage = 'host_main'
    main()


if __name__ == '__main__':
    try:
        boot()
    except BaseException as error:
        # No console stack, argv, token, HTML or exception text.
        if _failure_out is not None:
            try:
                atomic(_failure_out/'observer-failure.json', failure_record(error, _failure_stage))
            except BaseException:
                pass  # Missing/failed diagnostic never authorizes a PASS.
        raise SystemExit(2) from None
