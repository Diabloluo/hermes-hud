"""Offline identity repair models only. Real Popen/psutil/Mach/pipes are NOT tested."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import identity_contract as ident
import runner
import analyze
import test_contract as old
import psutil
import observer  # Definitions only; boot/self_vm never called by this model suite.


def binding(launcher='/synthetic/venv/bin/python'):
    return {'schema': 'hud_remote_interpreter_v2', 'launcher': launcher,
            'prefix': '/synthetic/venv', 'argv0': '/public/Python.app/Contents/MacOS/Python',
            'exe': '/public/Python.app/Contents/MacOS/Python',
            'launcher_sha256': 'a'*64, 'exe_sha256': 'b'*64}


class ParentBinding(unittest.TestCase):
    def test_real_local_freeze_check_readonly(self):
        self.assertEqual(runner.freeze_check(common.digest(common.HERE/'FREEZE.json')),
                         common.frozen())

    def setUp(self):
        self.root = Path('/synthetic')
        self.args = ['/synthetic/venv/bin/python', '-I', '-B', '/public/runner.py', 'pair']
        self.actual = {'pid': 123, 'birth': 1., 'cwd': '/public',
                       'argv': [binding()['argv0']] + self.args[1:], 'exe': binding()['exe']}

    def call(self):
        with patch.object(ident, 'inspect', return_value=self.actual), \
             patch.object(ident.sys, 'orig_argv', self.args), \
             patch.object(ident.sys, 'executable', '/synthetic/venv/bin/python'), \
             patch.object(ident.sys, 'prefix', '/synthetic/venv'), \
             patch.object(ident, 'digest', return_value='a'*64):
            return ident.bind_parent(self.root)

    def test_framework_parent_binding_not_child_adoption(self):
        result = self.call()
        self.assertNotEqual(result['launcher'], result['argv0'])
        self.assertEqual(result['argv0'], self.actual['argv'][0])
        self.assertTrue(ident.binding_valid(result, self.root))

    def test_standard_parent_binding(self):
        self.actual['argv'][0] = self.args[0]
        self.actual['exe'] = self.args[0]
        self.assertEqual(self.call()['argv0'], self.args[0])

    def test_optimized_parent_rejected(self):
        self.args[1] = '-O'
        self.actual['argv'][1] = '-O'
        self.assertRaises(common.Refused, self.call)

    def test_parent_command_tail_mismatch(self):
        self.actual['argv'].append('foreign')
        self.assertRaises(common.Refused, self.call)

    def test_unknown_parent_shape(self):
        self.actual['raw'] = 'SECRET_SENTINEL'
        self.assertRaises(common.Refused, self.call)

    def test_binding_must_use_owned_venv(self):
        b = binding('/foreign/python')
        self.assertFalse(ident.binding_valid(b, self.root))
        b = binding()
        b['prefix'] = '/foreign/prefix'
        self.assertFalse(ident.binding_valid(b, self.root))

    def test_binding_hash_and_raw_strict(self):
        b = binding()
        b['exe_sha256'] = True
        self.assertFalse(ident.binding_valid(b, self.root))
        b = binding()
        b['raw'] = 'SECRET_SENTINEL'
        self.assertFalse(ident.binding_valid(b, self.root))


class HostIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hud-identity-model-')
        self.out = Path(self.temp.name).resolve()
        self.b = binding(sys.executable)
        self.host = runner.Host('sham', Path('/synthetic/home'), self.out, Path('/public/repo'), 1234, self.b)
        self.proc = old.Proc()
        self.actual = ident.expected(self.host.argv, self.host.home, self.proc.pid, 1., self.b)

    def tearDown(self):
        self.temp.cleanup()

    def spawn(self, observations, ticks=(100., 102.)):
        with patch.object(runner.subprocess, 'Popen', return_value=self.proc) as popen, \
             patch.object(runner, 'live_identity', side_effect=observations), \
             patch.object(runner.time, 'monotonic', side_effect=ticks), \
             patch.object(runner.time, 'sleep'):
            try:
                self.host.spawn()
            finally:
                self.assertEqual(popen.call_count, 1)

    def test_framework_argv0_passes_exact_parent_image(self):
        self.spawn([self.actual])
        self.assertEqual(self.host.identity, self.actual)
        self.assertTrue(ident.diagnostic_matched(self.host.identity_diagnostic))

    def test_launcher_settling_single_spawn(self):
        transient = copy.deepcopy(self.actual)
        transient['argv'][0] = self.host.argv[0]
        self.spawn([transient, self.actual], (100., 100.))
        self.assertEqual(self.host.identity['argv'][0], self.b['argv0'])

    def test_birth_is_captured_once_not_rebound(self):
        first = copy.deepcopy(self.actual)
        first['argv'][0] = self.host.argv[0]
        second = dict(self.actual, birth=2.)
        self.assertRaises(common.Refused, self.spawn, [first, second], (100., 100., 102.))
        self.assertEqual(self.host.identity['birth'], 1.)
        self.assertFalse(self.host.identity_diagnostic['checks']['birth'])

    def test_unknown_initial_no_birth_adoption(self):
        self.assertRaises(common.Refused, self.spawn, [{}])
        self.assertIsNone(self.host.identity)
        self.assertEqual(self.proc.signals, [])

    def test_early_exit_has_code_and_no_inspection(self):
        self.proc.early = True
        self.assertRaises(common.Refused, self.spawn, [])
        self.assertEqual(self.host.identity_diagnostic['exit_code'], 0)
        self.assertEqual(self.proc.signals, [])

    def test_loop_early_exit_separate_stage(self):
        self.host.proc, self.host.identity = self.proc, self.actual
        self.proc.early = True
        self.assertRaises(common.Refused, self.host.check_identity)
        self.assertEqual(self.host.identity_diagnostic['stage'], 'loop')
        self.assertEqual(self.host.identity_diagnostic['exit_code'], 0)

    def test_initial_inspection_exception_enumerated(self):
        self.assertRaises(common.Refused, self.spawn, [psutil.AccessDenied(pid=456)])
        self.assertEqual(self.host.identity_diagnostic['inspection_error'], 'access_denied')
        self.assertEqual(self.proc.signals, [])

    def test_loop_inspection_exception_enumerated(self):
        self.host.proc, self.host.identity = self.proc, self.actual
        with patch.object(runner, 'live_identity', side_effect=psutil.NoSuchProcess(pid=456)):
            self.assertRaises(common.Refused, self.host.check_identity)
        self.assertEqual(self.host.identity_diagnostic['inspection_error'], 'no_such_process')

    def test_cleanup_verified_after_failed_admission_stays_fail(self):
        bad = copy.deepcopy(self.actual)
        bad['argv'][0] = self.host.argv[0]
        self.assertRaises(common.Refused, self.spawn, [bad])
        record = common.cleanup(self.proc, self.host.identity, lambda _: self.actual)
        self.assertTrue(record['identity_matched'])
        self.assertEqual(self.proc.signals, ['TERM'])
        # Original admission diagnostic remains false; it cannot become a PASS.
        self.assertFalse(ident.diagnostic_matched(self.host.identity_diagnostic))


for field, mutation in (
    ('pid', lambda a: a.update(pid=999)),
    ('cwd', lambda a: a.update(cwd='/foreign/home')),
    ('exe', lambda a: a.update(exe='/foreign/Python')),
    ('argv0', lambda a: a['argv'].__setitem__(0, '/foreign/Python')),
    ('flags', lambda a: a['argv'].__setitem__(1, '-O')),
    ('entry', lambda a: a['argv'].__setitem__(3, '/foreign/observer.py')),
    ('port', lambda a: a['argv'].__setitem__(8, '9119')),
    ('extra', lambda a: a['argv'].append('SECRET_SENTINEL')),
):
    def reject(self, mutation=mutation):
        bad = copy.deepcopy(self.actual)
        mutation(bad)
        self.assertRaises(common.Refused, self.spawn, [bad])
        self.assertEqual(self.proc.signals, [])
        self.assertNotIn('SECRET_SENTINEL', json.dumps(self.host.identity_diagnostic))
    setattr(HostIdentity, 'test_initial_reject_'+field, reject)


class CleanupDiagnostic(unittest.TestCase):
    def setUp(self):
        self.saved = {'pid': 456, 'birth': 1., 'cwd': '/synthetic/home',
                      'argv': ['/public/Python', '-I'], 'exe': '/public/Python'}

    def test_unknown_executable_no_term(self):
        proc = old.Proc()
        row = common.cleanup(proc, self.saved, lambda _: dict(self.saved, exe='/foreign/Python'))
        self.assertEqual(proc.signals, [])
        self.assertFalse(row['diagnostic']['checks']['exe'])

    def test_pre_kill_unknown_no_followup_signal(self):
        proc = old.Proc(timeout=True)
        observations = iter([self.saved, dict(self.saved, birth=2.)])
        row = common.cleanup(proc, self.saved, lambda _: next(observations))
        self.assertEqual(proc.signals, ['TERM'])
        self.assertEqual(row['diagnostic']['stage'], 'pre_kill')
        self.assertFalse(row['diagnostic']['checks']['birth'])

    def test_exited_after_term_no_reused_pid_inspection(self):
        proc = old.Proc(timeout=True)
        with patch.object(proc, 'poll', side_effect=[None, 0]):
            calls = []
            row = common.cleanup(proc, self.saved, lambda _: calls.append(1) or self.saved)
        self.assertEqual(calls, [1])
        self.assertEqual(proc.signals, ['TERM'])
        self.assertEqual(row['exit_code'], 0)

    def test_natural_exit_no_identity_fabrication(self):
        proc = old.Proc(early=True)
        row = common.cleanup(proc, self.saved, lambda _: self.fail('reused PID'))
        self.assertFalse(row['identity_matched'])
        self.assertEqual(row['diagnostic']['exit_code'], 0)

    def test_psutil_child_inspection_is_mock_only(self):
        fake = type('Fake', (), {'create_time': lambda _: 1., 'cwd': lambda _: '/synthetic/home',
                    'cmdline': lambda _: ['/public/Python', '-I'], 'exe': lambda _: '/public/Python'})()
        with patch.object(psutil, 'Process', return_value=fake) as lookup:
            actual = ident.inspect(old.Proc())
        lookup.assert_called_once_with(456)
        self.assertEqual(actual, self.saved)

    def test_unknown_exception_never_exports_text(self):
        proc = old.Proc()
        def inspection(_):
            raise RuntimeError('SECRET_SENTINEL')
        row = common.cleanup(proc, self.saved, inspection)
        self.assertEqual(proc.signals, [])
        self.assertEqual(row['diagnostic']['inspection_error'], 'inspection_other')
        self.assertNotIn('SECRET_SENTINEL', json.dumps(row))


for cls, code in ((psutil.ZombieProcess, 'zombie_process'),
                  (psutil.NoSuchProcess, 'no_such_process'), (psutil.AccessDenied, 'access_denied')):
    def reject(self, cls=cls, code=code):
        proc = old.Proc()
        def inspection(_):
            raise cls(pid=456)
        row = common.cleanup(proc, self.saved, inspection)
        self.assertEqual(proc.signals, [])
        self.assertEqual(row['diagnostic']['inspection_error'], code)
    setattr(CleanupDiagnostic, 'test_enumerated_'+code, reject)


class AnalyzerRepair(unittest.TestCase):
    def setUp(self):
        self.e = old.EvidenceModel('test_valid_finite_only')
        self.e.setUp()

    def tearDown(self):
        self.e.tearDown()

    def test_framework_finite_fixture_valid_only_model(self):
        r = analyze.analyze(self.e.root)
        self.assertFalse(r['environment']['os_argv0_equals_launcher'])
        self.assertEqual(r['memory_risk'], 'WARN_NOT_ACCEPTED')

    def test_failure_diagnostic_no_raw_export(self):
        self.e.arms['sham']['result'] = 'FAIL'
        self.e.arms['sham']['error'] = 'host_identity'
        self.e.arms['sham']['identity_diagnostic']['raw'] = 'SECRET_SENTINEL'
        self.e.arms['sham']['cleanup']['diagnostic']['raw'] = 'SECRET_SENTINEL'
        self.e.seal()
        r = analyze.diagnostic(self.e.root)
        self.assertIsNone(r[0]['identity_diagnostic'])
        self.assertIsNone(r[0]['cleanup'])
        self.assertNotIn('SECRET_SENTINEL', json.dumps(r))

    def test_failure_safe_fields_are_preserved(self):
        self.e.arms['sham']['identity_diagnostic']['checks']['argv'] = False
        self.e.arms['sham']['result'] = 'FAIL'
        self.e.arms['sham']['error'] = 'host_identity'
        self.e.seal()
        r = analyze.diagnostic(self.e.root)
        self.assertFalse(r[0]['identity_diagnostic']['checks']['argv'])
        self.assertEqual(r[0]['result'], 'DIAGNOSTIC_ONLY')
        self.assertRaises(Exception, analyze.analyze, self.e.root)


MUTATIONS = {
    'binding_drift': lambda e: e.pair['interpreter_binding_end'].update(exe_sha256='c'*64),
    'binding_foreign_launcher': lambda e: e.pair['interpreter_binding'].update(launcher='/foreign/python'),
    'binding_prefix': lambda e: e.pair['interpreter_binding'].update(prefix='/foreign/prefix'),
    'identity_exe': lambda e: e.arms['sham']['identity'].update(exe='/foreign/Python'),
    'identity_argv0': lambda e: e.arms['sham']['identity']['argv'].__setitem__(0, '/foreign/Python'),
    'identity_bool_pid': lambda e: e.arms['sham']['identity'].update(pid=True),
    'identity_bool_birth': lambda e: e.arms['sham']['identity'].update(birth=True),
    'diagnostic_wrong_stage': lambda e: e.arms['sham']['identity_diagnostic'].update(stage='pre_term'),
    'diagnostic_false_check': lambda e: e.arms['sham']['identity_diagnostic']['checks'].update(argv=False),
    'diagnostic_integer_true': lambda e: e.arms['sham']['identity_diagnostic']['checks'].update(argv=1),
    'diagnostic_raw': lambda e: e.arms['sham']['identity_diagnostic'].update(raw='SECRET_SENTINEL'),
    'cleanup_false_check': lambda e: e.arms['sham']['cleanup']['diagnostic']['checks'].update(birth=False),
    'cleanup_wrong_stage': lambda e: e.arms['sham']['cleanup']['diagnostic'].update(stage='loop'),
    'cleanup_bool_exit': lambda e: e.arms['sham']['cleanup']['diagnostic'].update(exit_code=True),
    'cleanup_unknown_exception': lambda e: e.arms['sham']['cleanup']['diagnostic'].update(inspection_error='SECRET_SENTINEL'),
}
for label, mutation in MUTATIONS.items():
    def reject(self, mutation=mutation):
        mutation(self.e)
        self.e.seal()
        self.assertRaises(Exception, analyze.analyze, self.e.root)
    setattr(AnalyzerRepair, 'test_reject_'+label, reject)


class ChildFailure(unittest.TestCase):
    def record(self):
        try:
            raise RuntimeError('SECRET_SENTINEL /Users/private/raw')
        except RuntimeError as error:
            return observer.failure_record(error, 'host_import')

    def test_exception_text_not_exported(self):
        row = self.record()
        self.assertTrue(ident.failure_valid(row))
        self.assertIsNotNone(row['site'])
        self.assertNotIn('SECRET_SENTINEL', json.dumps(row))
        self.assertNotIn('/Users/', json.dumps(row))

    def test_fixed_refusal_only(self):
        row = observer.failure_record(common.Refused('file_boundary'), 'policy')
        self.assertEqual(row['error'], 'file_boundary')
        self.assertIsNone(row['site'])

    def test_unknown_refusal_folds_internal(self):
        row = observer.failure_record(common.Refused('SECRET_SENTINEL'), 'policy')
        self.assertEqual(row['error'], 'internal')

    def test_failure_projection_valid_and_never_pass(self):
        e = old.EvidenceModel('test_valid_finite_only'); e.setUp()
        try:
            e.arms['sham']['result'] = 'FAIL'; e.arms['sham']['error'] = 'host_early_exit'
            e.seal()
            common.atomic(e.root/'sham/evidence/observer-failure.json', self.record())
            row = analyze.diagnostic(e.root)[0]
            self.assertEqual(row['observer_failure']['stage'], 'host_import')
            self.assertEqual(row['result'], 'DIAGNOSTIC_ONLY')
            self.assertRaises(Exception, analyze.analyze, e.root)
        finally:
            e.tearDown()

    def test_failure_projection_injected_raw_rejected(self):
        e = old.EvidenceModel('test_valid_finite_only'); e.setUp()
        try:
            row = self.record(); row['raw'] = 'SECRET_SENTINEL'
            common.atomic(e.root/'sham/evidence/observer-failure.json', row)
            projected = analyze.diagnostic(e.root)
            self.assertIsNone(projected[0]['observer_failure'])
            self.assertNotIn('SECRET_SENTINEL', json.dumps(projected))
        finally:
            e.tearDown()


CHILD_MUTATIONS = {
    'raw': lambda r: r.update(raw='SECRET_SENTINEL'),
    'error': lambda r: r.update(error='SECRET_SENTINEL'),
    'stage': lambda r: r.update(stage='SECRET_SENTINEL'),
    'line_bool': lambda r: r['site'].update(line=True),
    'path': lambda r: r['site'].update(filename='/Users/private/raw'),
    'hash': lambda r: r['site'].update(filename_sha256='x'*64),
    'raw_flag': lambda r: r.update(raw_persisted=0),
    'semantics': lambda r: r.update(site_semantics='source_content_hash'),
}
for label, mutation in CHILD_MUTATIONS.items():
    def reject(self, mutation=mutation):
        row = self.record(); mutation(row)
        self.assertFalse(ident.failure_valid(row))
    setattr(ChildFailure, 'test_reject_'+label, reject)


if __name__ == '__main__':
    # Preloaded dependencies; audit is not interpreter-startup/ctypes containment.
    sys.addaudithook(old.audit)
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromModule(old),
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'tests_run': result.testsRun, 'success': result.wasSuccessful(),
                      'audit_attempts': old.ATTEMPTS, 'native_run': False,
                      'scope': '65 adapted regressions plus identity repair models; NOT real psutil/OS pipe/Mach/CI'}))
    raise SystemExit(0 if result.wasSuccessful() and not any(old.ATTEMPTS.values()) else 2)
