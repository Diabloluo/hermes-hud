"""Offline/model tests only: no host, real pipe, Mach, network, signal or DB call."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import analyze
import observer
import runner
import fixture
import psutil
from types import SimpleNamespace

ATTEMPTS = {'process': 0, 'network': 0, 'sqlite': 0, 'signal': 0}


def audit(event, args):
    kind = None
    if event in ('subprocess.Popen', 'os.system', 'os.fork', 'os.exec', 'os.posix_spawn'):
        kind = 'process'
    elif event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
        kind = 'network'
    elif event == 'sqlite3.connect':
        kind = 'sqlite'
    elif event in ('os.kill', 'os.killpg'):
        kind = 'signal'
    if kind:
        ATTEMPTS[kind] += 1
        raise PermissionError('offline_forbidden')


class Proc:
    pid = 456
    def __init__(self, early=False, timeout=False):
        self.signals, self.early, self.timeout = [], early, timeout
    def poll(self):
        return 0 if self.early else None
    def terminate(self):
        self.signals.append('TERM')
    def kill(self):
        self.signals.append('KILL')
    def wait(self, timeout):
        if self.timeout and len(self.signals) == 1:
            raise TimeoutError
        return -15 if len(self.signals) == 1 else -9


class PureContract(unittest.TestCase):
    def setUp(self):
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'Diabloluo/hermes-hud',
                    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
                    'GITHUB_REF': 'refs/heads/test/v2-isolated-memory-20261003', 'GITHUB_SHA': 'a'*40}
        self.saved = {'pid': 456, 'birth': 1.0, 'cwd': '/synthetic/home', 'argv': ['fixed-entry', '1234']}

    def test_authority_exact(self):
        common.workflow_authority(self.env, 'a'*40, 'b'*32)

    def test_schedule_four_rounds_and_no_gc(self):
        p = common.protocol()
        self.assertEqual(len(common.schedule(p)), 11)
        self.assertEqual(sum(x[1] for x in common.schedule(p)), 2220)
        self.assertEqual(p['growth_acceptance_budget'], None)
        self.assertFalse(p['forced_gc'])

    def test_endpoint_no_production(self):
        self.assertRaises(common.Refused, common.endpoint, 9119, '')
        self.assertRaises(common.Refused, common.endpoint, True, '')
        self.assertRaises(common.Refused, common.endpoint, 1234, '../token')

    def test_pair_and_arm_budgets(self):
        p = common.protocol()
        common.deadline(2979, 0, 0, p)
        self.assertRaises(common.Refused, common.deadline, 2980, 0, 0, p)
        self.assertRaises(common.Refused, common.deadline, 5980, 0, 3001, p)
        self.assertRaises(common.Refused, common.deadline, -1, 0, 0, p)

    def test_unknown_identity_no_signal(self):
        proc = Proc()
        r = common.cleanup(proc, self.saved, lambda _: dict(self.saved, birth=2.0))
        self.assertEqual(proc.signals, [])
        self.assertFalse(r['identity_matched'])
        self.assertEqual(r['error'], 'cleanup_failed')

    def test_term_full_identity(self):
        proc = Proc()
        r = common.cleanup(proc, self.saved, lambda _: self.saved)
        self.assertEqual(proc.signals, ['TERM'])
        self.assertTrue(r['identity_matched'])
        self.assertFalse(r['alive'])

    def test_recheck_before_kill(self):
        proc = Proc(timeout=True)
        calls = iter([self.saved, dict(self.saved, argv=['different'])])
        r = common.cleanup(proc, self.saved, lambda _: next(calls))
        self.assertEqual(proc.signals, ['TERM'])
        self.assertEqual(r['error'], 'cleanup_failed')

    def test_kill_matching_only(self):
        proc = Proc(timeout=True)
        r = common.cleanup(proc, self.saved, lambda _: self.saved)
        self.assertEqual(proc.signals, ['TERM', 'KILL'])
        self.assertEqual(r['exit_code'], -9)

    def test_early_exit_not_identity_match(self):
        proc = Proc(early=True)
        r = common.cleanup(proc, self.saved, lambda _: self.fail('must not inspect recycled PID'))
        self.assertFalse(r['identity_matched'])
        self.assertEqual(r['error'], 'unexpected_exit')

    def test_no_true_as_integer(self):
        self.assertFalse(common.identity_matches(dict(self.saved, pid=True), self.saved))
        self.assertFalse(common.number(True))
        self.assertFalse(common.number(float('nan')))

    def test_ols_descriptive(self):
        self.assertAlmostEqual(analyze.slope([(0, 1), (1, 2), (2, 3), (3, 4)]), 3600)
        self.assertRaises(common.Refused, analyze.slope, [(0, 1)]*4)

    def test_checkpoint_no_raw_path(self):
        class Frame:
            filename = '/SECRET_SENTINEL/hidden/path'
            lineno = 7
        class Stat:
            traceback = [Frame()]
            size, count, size_diff = 10, 2, 1
        class Snapshot:
            traces = [1]
            def statistics(self, _): return [Stat()]
            def compare_to(self, other, _): return [Stat()]
        class Trace:
            def take_snapshot(self): return Snapshot()
        row, baseline = observer.checkpoint(Trace(), None)
        self.assertNotIn('SECRET_SENTINEL', json.dumps(row))
        self.assertEqual(row['interpretation'], 'filename_provenance_only_not_ownership')
        row2, retained = observer.checkpoint(Trace(), baseline)
        self.assertIs(retained, baseline)
        self.assertEqual(row2['net_delta_bytes'], 1)

    def test_frozen_real_file_read_only(self):
        values = common.frozen()
        self.assertEqual(len(values), 9)
        self.assertTrue(all(common.HEX.fullmatch(x) for x in values.values()))

    def test_invalid_authorization_strings(self):
        self.assertRaises(common.Refused, common.workflow_authority, self.env, 'not-a-sha', 'b'*32)
        self.assertRaises(common.Refused, common.workflow_authority, self.env, 'a'*40, '')

    def test_child_environment_no_inherited_credentials(self):
        host = runner.Host('sham', Path('/synthetic/home'), Path('/synthetic/evidence'), Path('/public/repo'), 1234)
        self.assertNotIn('GITHUB_TOKEN', host.env)
        self.assertNotIn('OPENAI_API_KEY', host.env)
        self.assertNotIn('SSH_AUTH_SOCK', host.env)
        self.assertNotIn('HTTPS_PROXY', host.env)
        self.assertNotIn('token', ' '.join(host.argv))


class GuardModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hud-guard-model-')
        self.out = Path(self.tmp.name).resolve()
        self.host = runner.Host('sham', self.out/'synthetic-home', self.out, Path('/public/repo'), 1234)
        self.host.proc = Proc()
        self.host.identity = {'pid': 456, 'birth': 1., 'cwd': '/synthetic/home', 'argv': ['entry']}
        self.p = common.protocol()
        self.available = 4*1024**3
        self.free = 6*1024**3
        self.rss = 1
        self.patches = [patch.object(runner, 'live_identity', return_value=self.host.identity),
            patch.object(runner.time, 'monotonic', return_value=100.),
            patch.object(psutil, 'virtual_memory', side_effect=lambda: SimpleNamespace(available=self.available)),
            patch.object(psutil, 'disk_usage', side_effect=lambda _: SimpleNamespace(free=self.free)),
            patch.object(psutil, 'Process', side_effect=lambda _: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=self.rss)))]
        for mock in self.patches:
            mock.start()
        self.latest = {'at': 99., 'phys_footprint': 1}
        common.atomic(self.out/'latest.json', self.latest)

    def tearDown(self):
        for mock in reversed(self.patches):
            mock.stop()
        self.tmp.cleanup()

    def test_valid_guard(self):
        self.host.check(self.p, 0., 0.)

    def test_unknown_identity_guard(self):
        with patch.object(runner, 'live_identity', return_value={}):
            self.assertRaises(common.Refused, self.host.check, self.p, 0., 0.)
        self.assertEqual(self.host.proc.signals, [])

    def test_memory_resource_guard(self):
        self.available = 1
        self.assertRaises(common.Refused, self.host.check, self.p, 0., 0.)

    def test_disk_resource_guard(self):
        self.free = 1
        self.assertRaises(common.Refused, self.host.check, self.p, 0., 0.)

    def test_rss_ceiling(self):
        self.rss = self.p['process_ceiling_bytes']
        self.assertRaises(common.Refused, self.host.check, self.p, 0., 0.)

    def test_footprint_ceiling(self):
        self.latest['phys_footprint'] = self.p['process_ceiling_bytes']
        common.atomic(self.out/'latest.json', self.latest)
        self.assertRaises(common.Refused, self.host.check, self.p, 0., 0.)

    def test_stale_sampler(self):
        self.latest['at'] = 90.
        common.atomic(self.out/'latest.json', self.latest)
        self.assertRaises(common.Refused, self.host.check, self.p, 0., 0.)

    def test_operation_32s_tolerance_not_extended_deadline(self):
        self.latest['at'] = 71.
        common.atomic(self.out/'latest.json', self.latest)
        self.host.check(self.p, 0., 0., operation=71.)
        self.assertRaises(common.Refused, self.host.check, self.p, 0., 0., 70.)

    def test_observer_failure(self):
        common.atomic(self.out/'observer-failure.json', {'error': 'observer_failed'})
        self.assertRaises(common.Refused, self.host.check, self.p, 0., 0.)


for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'other/repo'),
                   ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_RUN_ATTEMPT', '2'),
                   ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_SHA', 'c'*40)]:
    def reject(self, key=key, value=value):
        env = dict(self.env, **{key: value})
        self.assertRaises(common.Refused, common.workflow_authority, env, 'a'*40, 'b'*32)
    setattr(PureContract, 'test_authority_reject_'+key.lower(), reject)


class EvidenceModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hud-offline-evidence-')
        self.root = Path(self.tmp.name).resolve()/'hud-finite-owned'
        self.root.mkdir()
        self.p = common.protocol()
        self.tools = common.frozen()
        self.pair = {'schema': 'hud_remote_pair_v1', 'sha': 'a'*40, 'candidate': self.p['candidate'],
                     'grant': 'b'*32, 'run_id': '1', 'result': 'EXECUTION_COMPLETE_PENDING_ANALYSIS',
                     'arms': [{'arm': a, 'result': 'EXECUTION_COMPLETE_PENDING_ANALYSIS'} for a in self.p['arms']],
                     'tool_start': self.tools, 'tool_end': self.tools, 'seconds': 4800,
                     'environment': {'python': '3.13.1', 'platform': 'darwin', 'distributions':
                        {'hermes-agent': '0.19.0', 'psutil': '7.2.2', 'websockets': '15.0.1',
                         'fastapi': '1', 'uvicorn': '1', 'starlette': '1'}},
                     'memory_risk': 'WARN_NOT_ACCEPTED', 'public_release': 'BLOCK',
                     'public_source_start': {'count': 1, 'sha256': 'a'*64},
                     'public_source_end': {'count': 1, 'sha256': 'a'*64}}
        self.arms = {}
        for arm in self.p['arms']:
            out = self.root/arm/'evidence'
            out.mkdir(parents=True)
            at, phases, rows, ops = 1., [], [], []
            for label, seconds, load in common.schedule(self.p):
                phase = {'label': label, 'seconds': seconds, 'start': at, 'end': at+seconds,
                         'http': 4 if load else 0, 'ws': 1 if load else 0, 'handshakes': int(load)}
                phases.append(phase)
                for n in range(seconds//2):
                    rows.append({'at': at+n*2+.5, 'phase': label, **{k: 100 for k in common.METRICS}})
                at += seconds+1
                if label in common.LABELS:
                    seq = len(ops)+1
                    ops.append({'sequence': seq, 'label': label, 'at': at,
                                'observed_seconds': 1., 'window_seconds': 30.})
                    value = None if arm == 'sham' else {'trace_records': 1, 'snapshot_bytes': 10,
                        'delta_rows': 0 if seq == 1 else 1, 'net_delta_bytes': 0, 'top': [],
                        'interpretation': 'filename_provenance_only_not_ownership'}
                    common.atomic(out/f'checkpoint-{seq}.json', {'sequence': seq, 'label': label,
                        'compare_to': None if seq == 1 else 1, 'snapshot_count': int(arm == 'snapshot'),
                        'gc_count': 0, 'seconds': 1., 'values': value})
                    at += 30
            identity = {'pid': 1 if arm == 'sham' else 2, 'birth': 1.,
                'cwd': str(self.root/arm/'synthetic-home'),
                'argv': [str(self.root/'venv/bin/python'), '-I', '-B', str(common.HERE/'observer.py'),
                         'dashboard', '--host', '127.0.0.1', '--port', '1234', '--no-open', '--skip-build']}
            common.atomic(out/'identity.json', identity)
            r = {'schema': 'hud_remote_arm_v1', 'arm': arm, 'result': 'EXECUTION_COMPLETE_PENDING_ANALYSIS',
                 'error': None, 'phases': phases, 'operations': ops,
                 'cleanup': {'identity_matched': True, 'alive': False, 'exit_code': -15, 'error': None},
                 'fixture': {'counts': self.p['fixture_counts'], 'schema_source_sha256': 'd'*64,
                    'source_hashes': {'state.db': 'e'*64, 'job-ledger/jobs.jsonl': 'f'*64},
                    'query_only': True, 'native_ddl': 'fresh pinned distribution SCHEMA_SQL; required fields not patched',
                    'timeline_total': None}, 'sources_end': {'state.db': 'e'*64, 'job-ledger/jobs.jsonl': 'f'*64},
                 'counts_end': self.p['fixture_counts'], 'tool_end': self.tools,
                 'start': 0., 'seconds': 2500., 'identity': identity}
            self.arms[arm] = r
            common.atomic(out/'result.json', r)
            (out/'samples.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        common.atomic(self.root/'result.json', self.pair)

    def tearDown(self):
        self.tmp.cleanup()

    def seal(self):
        common.atomic(self.root/'result.json', self.pair)
        for arm, r in self.arms.items():
            common.atomic(self.root/arm/'evidence/result.json', r)

    def test_valid_finite_only(self):
        r = analyze.analyze(self.root)
        self.assertEqual(r['result'], 'VERIFIED_REMOTE_FINITE_EXECUTION_ONLY')
        self.assertEqual(r['memory_risk'], 'WARN_NOT_ACCEPTED')
        self.assertEqual(r['public_release'], 'BLOCK')
        self.assertEqual(r['absolute_between_arm_memory_comparison'], 'FORBIDDEN')
        self.assertEqual(r['arms'][0]['within_arm_changes']['phys_footprint']['final_minus_baseline'], 0)

    def test_missing_checkpoint(self):
        (self.root/'snapshot/evidence/checkpoint-5.json').unlink()
        self.assertRaises(Exception, analyze.analyze, self.root)

    def test_sham_snapshot_rejected(self):
        path = self.root/'sham/evidence/checkpoint-1.json'
        r = common.read(path)
        r['snapshot_count'] = 1
        common.atomic(path, r)
        self.assertRaises(common.Refused, analyze.analyze, self.root)

    def test_unknown_source_no_path_export(self):
        path = self.root/'snapshot/evidence/checkpoint-1.json'
        r = common.read(path)
        r['values']['top'] = [{'file_sha256': '/SECRET_SENTINEL', 'line': 1, 'bytes': 1, 'blocks': 1}]
        common.atomic(path, r)
        self.assertRaises(common.Refused, analyze.analyze, self.root)

    def test_no_invented_growth_threshold(self):
        rows = self.root/'snapshot/evidence/samples.jsonl'
        values = [json.loads(s) for s in rows.read_text().splitlines()]
        for row in values:
            row['phys_footprint'] += int(row['at'])*10000
        rows.write_text(''.join(json.dumps(row)+'\n' for row in values))
        r = analyze.analyze(self.root)
        self.assertGreater(r['arms'][1]['within_arm_changes']['phys_footprint']['final_minus_baseline'], 0)
        self.assertEqual(r['memory_risk'], 'WARN_NOT_ACCEPTED')

    def test_low_tail_coverage(self):
        path = self.root/'sham/evidence/samples.jsonl'
        rows = [json.loads(s) for s in path.read_text().splitlines()]
        phase = self.arms['sham']['phases'][0]
        rows = [s for s in rows if not (s['phase'] == 'warmup' and s['at'] > phase['end']-20)]
        path.write_text(''.join(json.dumps(s)+'\n' for s in rows))
        self.assertRaises(common.Refused, analyze.analyze, self.root)

    def test_extra_sample_raw_rejected(self):
        path = self.root/'sham/evidence/samples.jsonl'
        rows = [json.loads(s) for s in path.read_text().splitlines()]
        rows[0]['raw'] = 'SECRET_SENTINEL'
        path.write_text(''.join(json.dumps(s)+'\n' for s in rows))
        self.assertRaises(common.Refused, analyze.analyze, self.root)

    def test_bool_sample_rejected(self):
        path = self.root/'sham/evidence/samples.jsonl'
        rows = [json.loads(s) for s in path.read_text().splitlines()]
        rows[0]['fds'] = True
        path.write_text(''.join(json.dumps(s)+'\n' for s in rows))
        self.assertRaises(common.Refused, analyze.analyze, self.root)

    def test_duplicate_sample_rejected(self):
        path = self.root/'sham/evidence/samples.jsonl'
        rows = path.read_text().splitlines()
        rows.insert(1, rows[0])
        path.write_text('\n'.join(rows)+'\n')
        self.assertRaises(common.Refused, analyze.analyze, self.root)


MUTATIONS = {
    'fail_never_upgrade': lambda s: s.pair.update(result='FAIL'),
    'pair_budget': lambda s: s.pair.update(seconds=6000),
    'public_risk_acceptance': lambda s: s.pair.update(memory_risk='PASS'),
    'tool_drift': lambda s: s.pair.update(tool_end={}),
    'public_source_drift': lambda s: s.pair.update(public_source_end={'count': 1, 'sha256': 'b'*64}),
    'extra_pair_raw': lambda s: s.pair.update(raw='SECRET_SENTINEL'),
    'early_cleanup': lambda s: s.arms['sham']['cleanup'].update(identity_matched=False),
    'cleanup_bool_exit': lambda s: s.arms['sham']['cleanup'].update(exit_code=True),
    'cleanup_error': lambda s: s.arms['sham']['cleanup'].update(error='cleanup_failed'),
    'extra_arm_raw': lambda s: s.arms['sham'].update(raw='SECRET_SENTINEL'),
    'counts_change': lambda s: s.arms['sham'].update(counts_end={}),
    'fixture_change': lambda s: s.arms['snapshot']['fixture'].update(schema_source_sha256='c'*64),
    'source_change': lambda s: s.arms['sham'].update(sources_end={}),
    'missing_http': lambda s: s.arms['sham']['phases'][0].update(http=0),
    'missing_ws': lambda s: s.arms['sham']['phases'][0].update(ws=0),
    'extra_phase_raw': lambda s: s.arms['sham']['phases'][0].update(raw='SECRET_SENTINEL'),
    'phase_short': lambda s: s.arms['sham']['phases'][0].update(end=2),
    'missing_phases': lambda s: s.arms['sham'].update(phases=[]),
    'missing_operations': lambda s: s.arms['sham'].update(operations=[]),
    'late_operation': lambda s: s.arms['sham']['operations'][0].update(observed_seconds=30),
    'short_window': lambda s: s.arms['sham']['operations'][0].update(window_seconds=29),
    'wrong_label': lambda s: s.arms['sham']['operations'][0].update(label='wrong'),
    'production_port': lambda s: s.arms['sham']['identity']['argv'].__setitem__(8, '9119'),
}
for name, mutate in MUTATIONS.items():
    def reject(self, mutate=mutate):
        mutate(self)
        self.seal()
        self.assertRaises(Exception, analyze.analyze, self.root)
    setattr(EvidenceModel, 'test_reject_'+name, reject)


if __name__ == '__main__':
    # Preload above; this is not interpreter-startup or ctypes containment proof.
    sys.addaudithook(audit)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'audit_attempts': ATTEMPTS, 'tests_run': result.testsRun,
                      'success': result.wasSuccessful(), 'native_run': False,
                      'audit_scope': 'after imports; excludes interpreter startup and ctypes'}))
    raise SystemExit(0 if result.wasSuccessful() and not any(ATTEMPTS.values()) else 2)
