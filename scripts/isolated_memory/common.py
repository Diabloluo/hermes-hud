"""Portable contracts. Importing this module does not start processes or read data."""
import hashlib
import json
import math
from pathlib import Path
import re
import time

HERE = Path(__file__).resolve().parent
FILES = ('protocol.json', 'common.py', 'fixture.py', 'observer.py', 'runner.py', 'analyze.py',
         'test_contract.py', 'PROTOCOL.md')
HEX = re.compile(r'^[0-9a-f]{64}$')
SHA = re.compile(r'^[0-9a-f]{40}$')
LABELS = ('baseline', 'cooldown-1', 'cooldown-2', 'cooldown-3', 'cooldown-4')
METRICS = ('rss_bytes', 'resident_size', 'phys_footprint', 'compressed',
           'traced_current_bytes', 'trace_metadata_bytes', 'threads', 'fds',
           'snapshot_cache', 'db_cache', 'diagnostic_cache')


class Refused(ValueError):
    """Only enumerated messages are serialized; never exception repr/traceback."""


def require(ok, code):
    if ok is not True:
        raise Refused(code)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def digest(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'file_boundary')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic(path, value):
    path = Path(path)
    require(not path.is_symlink() and path.parent.resolve() == path.parent, 'file_boundary')
    tmp = path.with_suffix(path.suffix + '.pending')
    with tmp.open('x') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')
    tmp.replace(path)


def read(path, maximum=32 * 1024 * 1024):
    path = Path(path)
    require(path.parent.resolve() == path.parent and not path.is_symlink()
            and path.is_file() and path.stat().st_size <= maximum,
            'file_boundary')
    return json.loads(path.read_text())


def protocol():
    p = read(HERE / 'protocol.json')
    require(p['schema'] == 'hud_remote_finite_memory_v1' and p['rounds'] == 4
            and p['arms'] == ['sham', 'snapshot'] and p['trace_depth'] == 1
            and p['runs'] == 1 and p['retry'] is False and p['forced_gc'] is False
            and p['allocator_trim'] is False and p['vmmap'] is False
            and p['growth_acceptance_budget'] is None
            and p['memory_risk'] == 'WARN_NOT_ACCEPTED' and p['public_release'] == 'BLOCK',
            'protocol')
    # All protocol bytes are bound by the review freeze; the runtime cannot tune them.
    return p


def frozen():
    names = list(FILES) + ['../../.github/workflows/fresh-install.yml']
    return {name: digest(HERE / name) for name in names}


def schedule(p):
    values = [('warmup', p['warmup_seconds'], True),
              ('baseline', p['baseline_seconds'], False)]
    for n in range(1, 5):
        values.extend([(f'load-{n}', p['load_seconds'], True),
                       (f'cooldown-{n}', p['cooldown_seconds'], False)])
    return values + [('final', p['final_seconds'], False)]


def coverage(samples, phase, p):
    rows = [s for s in samples if s['phase'] == phase['label']
            and phase['start'] <= s['at'] <= phase['end']]
    expected = phase['seconds'] / p['sample_seconds']
    tail = [s for s in rows if s['at'] >= phase['end'] - min(p['tail_seconds'], phase['seconds'])]
    tail_expected = min(p['tail_seconds'], phase['seconds']) / p['sample_seconds']
    times = [phase['start']] + [s['at'] for s in rows] + [phase['end']]
    require(all(number(x) for x in times) and all(b > a for a, b in zip(times, times[1:])),
            'sample_order')
    ratio, tail_ratio = len(rows) / expected, len(tail) / tail_expected
    require(ratio >= p['coverage_minimum'] and tail_ratio >= p['coverage_minimum'], 'coverage')
    return {'phase': phase['label'], 'coverage': ratio, 'tail_coverage': tail_ratio,
            'maximum_gap_seconds': max(b-a for a, b in zip(times, times[1:])),
            'tail_count': len(tail)}, tail


def live_identity(proc):
    import psutil
    obj = psutil.Process(proc.pid)
    return {'pid': proc.pid, 'birth': obj.create_time(), 'cwd': obj.cwd(), 'argv': obj.cmdline()}


def identity_matches(saved, actual):
    return (set(actual) == {'pid', 'birth', 'cwd', 'argv'}
            and type(saved.get('pid')) is int and type(saved.get('birth')) is float
            and saved['pid'] == actual['pid'] and saved['birth'] == actual['birth']
            and saved['cwd'] == actual['cwd'] and saved['argv'] == actual['argv'])


def cleanup(proc, saved, inspect=live_identity):
    """Signals require PID+birth+cwd+full argv, rechecked before TERM and KILL."""
    result = {'identity_matched': False, 'alive': None, 'exit_code': None, 'error': None}
    try:
        # A natural exit is observed, but is not fabricated into identity-matched cleanup.
        code = proc.poll()
        if code is not None:
            return dict(result, alive=False, exit_code=code, error='unexpected_exit')
        require(identity_matches(saved, inspect(proc)), 'cleanup_identity')
        result['identity_matched'] = True
        proc.terminate()
        try:
            code = proc.wait(timeout=15)
        except TimeoutError:
            require(identity_matches(saved, inspect(proc)), 'cleanup_identity')
            proc.kill()
            code = proc.wait(timeout=5)
        except __import__('subprocess').TimeoutExpired:
            require(identity_matches(saved, inspect(proc)), 'cleanup_identity')
            proc.kill()
            code = proc.wait(timeout=5)
        return dict(result, alive=False, exit_code=code)
    except BaseException:
        # No follow-up signal after an unknown identity. No raw exception content.
        return dict(result, error='cleanup_failed')


def deadline(now, pair_start, arm_start, p):
    require(number(now) and now >= pair_start and now >= arm_start, 'clock')
    require(now < pair_start+p['pair_seconds']-p['cleanup_reserve_seconds'], 'pair_budget')
    require(now < arm_start+p['arm_seconds']-p['cleanup_reserve_seconds'], 'arm_budget')


def workflow_authority(env, expected, grant):
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == 'Diabloluo/hermes-hud'
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_RUN_ATTEMPT') == '1'
            and env.get('GITHUB_REF') == 'refs/heads/test/v2-isolated-memory-20261003'
            and SHA.fullmatch(expected) is not None and env.get('GITHUB_SHA') == expected
            and re.fullmatch(r'[0-9a-f]{32}', grant) is not None, 'authority')


def endpoint(port, route):
    require(type(port) is int and 1024 <= port <= 65535 and port != 9119, 'port')
    require(route in ('', 'snapshot?locale=zh', 'snapshot?locale=en', 'snapshot?locale=fr',
                      'snapshot?locale=ar', 'timeline?limit=100', 'usage?days=30',
                      'skills?locale=en', 'events?locale=en'), 'route')
    return f'http://127.0.0.1:{port}/' + ('api/plugins/hermes-hud/'+route if route else '')
