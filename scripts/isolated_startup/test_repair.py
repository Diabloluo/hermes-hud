"""Offline definitions and in-memory models; NOT real OS audit/pipe/host execution."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boundary_policy as p
import audit_adapter as a
import failure_projection as f
PUBLIC = HERE.parent/'hermes-release-venv/lib/python3.11/site-packages/hermes_constants.py'
PUBLIC_DATA = PUBLIC.read_bytes()
BOUND = p.bind_public_source(str(PUBLIC), PUBLIC_DATA)
TREE = ast.parse(PUBLIC_DATA)
CONTAINER = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'is_container')
INPUTS = {str(PUBLIC): hashlib.sha256(PUBLIC_DATA).hexdigest()}
for name in ('boundary_policy.py', 'audit_adapter.py', 'failure_projection.py', 'test_repair.py'):
    INPUTS[name] = hashlib.sha256((HERE/name).read_bytes()).hexdigest()
# Hooks installed after preloads, four own-source reads and one public-source read.
ATTEMPTS = {'open': 0, 'process': 0, 'network': 0, 'sqlite': 0, 'signal': 0}
def audit(event, args):
    kind = ('open' if event == 'open' else 'process' if event.startswith('subprocess.')
            or event in {'os.system', 'os.exec', 'os.fork', 'os.posix_spawn'} else
            'network' if event.startswith('socket.') else 'sqlite' if event.startswith('sqlite3.')
            else 'signal' if event in {'os.kill', 'os.killpg'} else None)
    if kind:
        ATTEMPTS[kind] += 1
        raise RuntimeError('OFFLINE_BOUNDARY')

def policy(platform='darwin'):
    return p.FilePolicy('/MODEL/home', '/MODEL/evidence', ('/MODEL/code', '/System', '/usr/lib'), platform)
def caller(line=1161):
    return {'frames': [{'source_sha256': p.SOURCE_SHA, 'line': line}],
            'unknown_frames': 1, 'truncated': False}
def request(obj, path='/proc/1/cgroup', mode='r', flags=0, line=1161, canonical=None, stack=None, immediate=None):
    stack = caller(line) if stack is None else stack
    return obj.check(path, canonical or path, mode, flags, stack,
                     stack['frames'][0] if immediate is None and stack['frames'] else immediate)
def frame(filename, line=1161, back=None):
    return SimpleNamespace(f_code=SimpleNamespace(co_filename=filename), f_lineno=line, f_back=back)

class PolicyTests(unittest.TestCase):
    def test_fixed_cgroup_absent_without_open(self):
        obj = policy()
        self.assertRaises(FileNotFoundError, request, obj)
        self.assertEqual(obj.state()['missing'], {'cgroup': 1, 'mountinfo': 0})
        self.assertEqual(obj.state()['denied_count'], 0)
    def test_fixed_mountinfo_absent_without_open(self):
        obj = policy()
        self.assertRaises(FileNotFoundError, request, obj, '/proc/self/mountinfo', line=1172)
        self.assertTrue(p.state_valid(obj.state()))
    def test_repeat_probe_denied_no_retry(self):
        obj = policy()
        self.assertRaises(FileNotFoundError, request, obj)
        self.assertRaises(p.BoundaryRefused, request, obj)
        self.assertEqual(obj.state()['denied_count'], 1)
    def test_wrong_platform_is_denial(self):
        self.assertRaises(p.BoundaryRefused, request, policy('linux'))
    def test_wrong_site_is_denial(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), line=1162)
    def test_bool_line_is_denial(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), line=True)
    def test_alias_to_probe_denied(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), '/MODEL/alias', canonical='/proc/1/cgroup')
    def test_probe_canonical_alias_denied(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), canonical='/MODEL/home/cgroup')
    def test_probe_write_denied(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), mode='w')
    def test_unbound_caller_denied(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), stack={'frames': [], 'unknown_frames': 1, 'truncated': False})
    def test_wrong_digest_denied(self):
        c = caller(); c['frames'][0]['source_sha256'] = 'b'*64
        self.assertRaises(p.BoundaryRefused, request, policy(), stack=c)
    def test_truncated_caller_denied(self):
        c = {'frames': [], 'unknown_frames': 128, 'truncated': True}
        self.assertRaises(p.BoundaryRefused, request, policy(), stack=c)
    def test_unrelated_immediate_caller_denied(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), immediate={'source_sha256': p.SOURCE_SHA, 'line': 1172})
    def test_unknown_proc_path_not_guessed(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), '/proc/OTHER')
    def test_public_read_allowed(self):
        self.assertIsNone(request(policy(), '/MODEL/code/module.py'))
    def test_public_write_denied(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), '/MODEL/code/module.py', mode='w')
    def test_owned_read_write_allowed(self):
        obj = policy()
        request(obj, '/MODEL/home/config.yaml'); request(obj, '/MODEL/evidence/new', mode='w')
        self.assertIsNone(obj.ensure_clean())
    def test_outside_read_denied(self):
        self.assertRaises(p.BoundaryRefused, request, policy(), '/MODEL/foreign/SECRET_SENTINEL')
    def test_caught_denial_stays_fatal(self):
        obj = policy()
        try: request(obj, '/MODEL/foreign/SECRET_SENTINEL')
        except Exception: pass
        self.assertRaises(p.BoundaryRefused, obj.ensure_clean)
    def test_source_drift_rejected(self):
        self.assertRaises(p.BoundaryRefused, p.bind_public_source, str(PUBLIC), PUBLIC_DATA+b' ')
    def test_public_container_function_with_real_ast_and_fake_open(self):
        obj = policy()
        def fake_open(path, mode, **kwargs):
            # Cooperative model: real in-memory AST caller, no real open/audit event.
            origin = sys._getframe(1)
            obj.check(path, path, mode, 0, BOUND.collect(origin), BOUND.immediate(origin))
            self.fail('probe was allowed instead of modelled absent')
        builtins = dict(vars(__builtins__) if not isinstance(__builtins__, dict) else __builtins__)
        builtins['open'] = fake_open
        ns = {'__builtins__': builtins, '_container_detected': None,
              'os': SimpleNamespace(path=SimpleNamespace(exists=lambda _: False), environ={})}
        exec(compile(ast.Module(body=[CONTAINER], type_ignores=[]), str(PUBLIC), 'exec'), ns)
        self.assertFalse(ns['is_container']())
        self.assertEqual(obj.state()['missing'], {'cgroup': 1, 'mountinfo': 1})
        self.assertIsNone(obj.ensure_clean())
        # Cache avoids repeated model consumption.
        self.assertFalse(ns['is_container']())

class AdapterTests(unittest.TestCase):
    def test_exact_bound_frame_reaches_model_absence(self):
        adapter = a.OpenAuditAdapter(policy(), BOUND)
        with patch.object(a.sys, '_getframe', return_value=frame(str(PUBLIC))), \
             patch.object(a.Path, 'resolve', return_value=Path('/proc/1/cgroup')):
            self.assertRaises(FileNotFoundError, adapter, 'open', ('/proc/1/cgroup', 'r', 0))
    def test_failed_resolution_is_sticky_denial(self):
        adapter = a.OpenAuditAdapter(policy(), BOUND)
        with patch.object(a.Path, 'resolve', side_effect=RuntimeError('SECRET_SENTINEL')):
            self.assertRaises(p.BoundaryRefused, adapter, 'open', ('/MODEL/foreign', 'r', 0))
        self.assertRaises(p.BoundaryRefused, a.checkpoint_before_success, adapter)
    def test_malformed_audit_arguments_denied(self):
        adapter = a.OpenAuditAdapter(policy(), BOUND)
        self.assertRaises(p.BoundaryRefused, adapter, 'open', ('/MODEL/home/x',))
        self.assertRaises(p.BoundaryRefused, adapter.policy.ensure_clean)
    def test_nonfile_event_not_a_sandbox_claim(self):
        self.assertIsNone(a.OpenAuditAdapter(policy(), BOUND)('socket.connect', None))
    def test_fd_boundary_unchanged_not_containment_proof(self):
        self.assertIsNone(a.OpenAuditAdapter(policy(), BOUND)('open', (3, 'r', 0)))
    def test_frame_output_has_bound_content_hash_not_path(self):
        c = BOUND.collect(frame('/Users/SECRET_SENTINEL', back=frame(str(PUBLIC))))
        self.assertEqual(c['frames'], [{'source_sha256': p.SOURCE_SHA, 'line': 1161}])
        self.assertEqual(c['unknown_frames'], 1)
        self.assertNotIn('SECRET_SENTINEL', json.dumps(c))
    def test_frame_overflow_discards_bound_frames(self):
        item = None
        for _ in range(129): item = frame(str(PUBLIC), back=item)
        c = BOUND.collect(item)
        self.assertTrue(c['truncated']); self.assertEqual(c['frames'], [])
    def test_frame_retention_max_four(self):
        item = None
        for _ in range(10): item = frame(str(PUBLIC), back=item)
        self.assertEqual(len(BOUND.collect(item)['frames']), 4)

class ProjectionTests(unittest.TestCase):
    def row(self):
        obj = policy()
        try: request(obj, '/MODEL/foreign/SECRET_SENTINEL')
        except p.BoundaryRefused as error: return f.make_failure(error, 'host_main', obj)
    def test_unknown_exception_text_not_exported(self):
        row = f.make_failure(RuntimeError('/Users/SECRET_SENTINEL'), 'host_main', policy())
        self.assertTrue(f.failure_valid(row)); self.assertNotIn('SECRET_SENTINEL', json.dumps(row))
    def test_no_pass_from_failure_projection(self):
        self.assertEqual(f.analyze_failure(self.row())['result'], 'DIAGNOSTIC_ONLY_NOT_VERIFIED')
    def test_denied_input_not_in_output(self):
        self.assertNotIn('SECRET_SENTINEL', json.dumps(self.row()))
    def test_state_and_caller_mutation_cannot_backfill(self):
        obj = policy(); c = caller()
        self.assertRaises(p.BoundaryRefused, request, obj, '/MODEL/foreign', stack=c)
        c['frames'][0]['source_sha256'] = 'SECRET_SENTINEL'
        r = obj.state(); r['last_denial']['caller']['frames'].append({'raw':'SECRET_SENTINEL'})
        self.assertTrue(p.state_valid(obj.state()))
        self.assertNotIn('SECRET_SENTINEL', json.dumps(obj.state()))

BAD_MODES = [True, [], 'SECRET_SENTINEL_w', 'rZ']
BAD_FLAGS = [True, -1, 2**31, 'SECRET_SENTINEL', 1 << 29]
for i, value in enumerate(BAD_MODES):
    def test(self, value=value): self.assertRaises(p.BoundaryRefused, request, policy(), '/MODEL/home/x', mode=value)
    setattr(PolicyTests, 'test_invalid_mode_'+str(i), test)
for i, value in enumerate(BAD_FLAGS):
    def test(self, value=value): self.assertRaises(p.BoundaryRefused, request, policy(), '/MODEL/home/x', flags=value)
    setattr(PolicyTests, 'test_invalid_flags_'+str(i), test)
MUTATIONS = {
    'raw': lambda r: r.update(raw='SECRET_SENTINEL'),
    'pass': lambda r: r.update(result='PASS'),
    'stage': lambda r: r.update(stage='SECRET_SENTINEL'),
    'schema': lambda r: r.update(schema='hud_remote_observer_failure_v2'),
    'raw_bool': lambda r: r.update(raw_persisted=0),
    'denied_bool': lambda r: r['boundary'].update(denied_count=True),
    'count_underflow': lambda r: r['boundary'].update(denied_count=-1),
    'count_overflow': lambda r: r['boundary'].update(denied_count=2**31),
    'counter_bool': lambda r: r['boundary']['missing'].update(cgroup=True),
    'counter_extra': lambda r: r['boundary']['missing'].update(raw='SECRET_SENTINEL'),
    'contradiction': lambda r: r.update(error='internal'),
    'caller_raw': lambda r: r['boundary']['last_denial']['caller'].update(raw='SECRET_SENTINEL'),
    'frame_path': lambda r: r['boundary']['last_denial']['caller']['frames'][0].update(filename='/Users/SECRET_SENTINEL'),
    'frame_hash': lambda r: r['boundary']['last_denial']['caller']['frames'][0].update(source_sha256='SECRET_SENTINEL'),
    'frame_bool': lambda r: r['boundary']['last_denial']['caller']['frames'][0].update(line=True),
    'truncation_contradiction': lambda r: r['boundary']['last_denial']['caller'].update(truncated=True),
}
for label, mutation in MUTATIONS.items():
    def test(self, mutation=mutation):
        row = self.row(); mutation(row)
        self.assertFalse(f.failure_valid(row)); self.assertIsNone(f.analyze_failure(row)['failure'])
        self.assertNotIn('SECRET_SENTINEL', json.dumps(f.analyze_failure(row)))
    setattr(ProjectionTests, 'test_reject_'+label, test)

if __name__ == '__main__':
    sys.addaudithook(audit)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(json.dumps({'tests': result.testsRun, 'success': result.wasSuccessful(), 'inputs': INPUTS,
          'attempts_after_preload': ATTEMPTS, 'scope': 'OFFLINE_POLICY_ADAPTER_AST_AND_COOPERATIVE_FRAME_MODELS_ONLY',
          'native_execution': 'NOT_RUN', 'runtime_host_integration': 'NOT_IMPLEMENTED',
          'memory_risk': 'WARN_NOT_ACCEPTED', 'public_release': 'BLOCK'}, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(ATTEMPTS.values()) else 2)
