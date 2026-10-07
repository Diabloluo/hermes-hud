"""Offline config-probe and terminal-counter models; NO native IO or host."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_direct_launch as previous
old=previous.old
full=previous.full
regression=previous.regression
p=regression.p
g=regression.g
l=regression.l
a=regression.a
PUBLIC=HERE.parent/'hermes-release-venv/lib/python3.11/site-packages'
CONFIG=PUBLIC/'hermes_cli/config.py'
CONFIG_DATA=CONFIG.read_bytes()
if hashlib.sha256(CONFIG_DATA).hexdigest()!=p.CONFIG_SOURCE_SHA:
    raise RuntimeError('SOURCE_BINDING')
CONFIG_TREE=ast.parse(CONFIG_DATA)
CONFIG_FUNCTIONS=[x for x in CONFIG_TREE.body if isinstance(x,ast.FunctionDef)
                  and x.name in ('_is_container','_secure_file')]
if len(CONFIG_FUNCTIONS)!=2:
    raise RuntimeError('SOURCE_BINDING')
BOUND=p.BoundFrames({str(CONFIG):p.CONFIG_SOURCE_SHA,
                    str(regression.previous.PUBLIC):p.SOURCE_SHA})
INPUTS=dict(previous.INPUTS)
INPUTS[str(CONFIG)]=hashlib.sha256(CONFIG_DATA).hexdigest()
for name in full.e.FILES:
    INPUTS[name]=hashlib.sha256((HERE/name).read_bytes()).hexdigest()


def chain():
    return {'frames':[{'source_sha256':p.CONFIG_SOURCE_SHA,'line':868},
                      {'source_sha256':p.CONFIG_SOURCE_SHA,'line':886}],
            'unknown_frames':2,'truncated':False}


def options():
    c=chain()
    return {'requested':'/proc/1/cgroup','canonical':'/proc/1/cgroup',
            'mode':'r','flags':0,'caller':c,'immediate':copy.deepcopy(c['frames'][0])}


def config_call(policy, values=None):
    policy.check(**(options() if values is None else values))


def absence(policy, values=None):
    try:config_call(policy,values)
    except FileNotFoundError:
        return
    raise AssertionError('EXPECTED_FIXED_ABSENCE')


def ast_namespace(policy):
    # Cooperative actual AST frames/fake-open; NOT real sys.audit or filesystem.
    def fake_open(path,mode,**kwargs):
        origin=sys._getframe(1)
        policy.check(path,path,mode,0,BOUND.collect(origin),BOUND.immediate(origin))
        raise AssertionError('NO_REAL_OPEN_ALLOWED')
    def no_chmod(*args):raise AssertionError('NO_REAL_METADATA_WRITE')
    builtins=dict(vars(__builtins__) if not isinstance(__builtins__,dict) else __builtins__)
    builtins['open']=fake_open
    namespace={'__builtins__':builtins,
        'os':SimpleNamespace(environ={},path=SimpleNamespace(exists=lambda _:False),chmod=no_chmod),
        'is_managed':lambda:False,'_container_detected':None}
    exec(compile(ast.Module(body=[regression.previous.CONTAINER],type_ignores=[]),
                 str(regression.previous.PUBLIC),'exec'),namespace)
    exec(compile(ast.Module(body=CONFIG_FUNCTIONS,type_ignores=[]),str(CONFIG),'exec'),namespace)
    return namespace


class ConfigPolicyTests(unittest.TestCase):
    def test_fixed_config_chain_absence_independent_of_constants(self):
        q=regression.previous.policy();absence(q)
        self.assertEqual(q.state()['config_missing'],1)
        self.assertEqual(q.state()['missing'],{'cgroup':0,'mountinfo':0})
        self.assertTrue(p.state_valid(q.state()));self.assertIsNone(q.ensure_clean())
    def test_constants_then_config_does_not_reuse_constants_counter(self):
        q=regression.previous.policy()
        self.assertRaises(FileNotFoundError,regression.previous.request,q)
        self.assertRaises(FileNotFoundError,regression.previous.request,q,'/proc/self/mountinfo',line=1172)
        absence(q);self.assertEqual(q.state()['missing'],{'cgroup':1,'mountinfo':1})
        self.assertEqual(q.state()['config_missing'],1)
    def test_config_then_constants_are_still_single_use(self):
        q=regression.previous.policy();absence(q)
        self.assertRaises(FileNotFoundError,regression.previous.request,q)
        self.assertRaises(p.BoundaryRefused,regression.previous.request,q)
        self.assertRaises(p.BoundaryRefused,q.ensure_clean)
    def test_exact_cap_and_exhaustion_are_sticky(self):
        q=regression.previous.policy()
        for _ in range(64):absence(q)
        self.assertEqual(q.state()['config_missing'],64)
        self.assertEqual(q.state()['denied_count'],0)
        self.assertRaises(p.BoundaryRefused,config_call,q)
        self.assertEqual(q.state()['config_missing'],64)
        self.assertEqual(q.state()['denied_count'],1)
        self.assertRaises(p.BoundaryRefused,q.ensure_clean)
    def test_design_cap_literal_not_measured_demand(self):
        self.assertIs(type(p.CONFIG_PROBE_LIMIT),int);self.assertEqual(p.CONFIG_PROBE_LIMIT,64)
    def test_caught_unknown_denial_cannot_be_cleared_by_known_probe(self):
        q=regression.previous.policy()
        try:regression.previous.request(q,'/FOREIGN/SECRET_SENTINEL')
        except Exception:pass
        absence(q);self.assertRaises(p.BoundaryRefused,q.ensure_clean)
    def test_state_copy_cannot_reset_runtime_counter(self):
        q=regression.previous.policy();absence(q);row=q.state();row['config_missing']=0
        self.assertEqual(q.state()['config_missing'],1)
    def test_probe_output_does_not_export_original_path(self):
        q=regression.previous.policy();v=options();v['requested']='/proc/SECRET_SENTINEL'
        v['canonical']=v['requested'];self.assertRaises(p.BoundaryRefused,config_call,q,v)
        self.assertNotIn('SECRET_SENTINEL',json.dumps(q.state()))
    def test_public_unknown_probe_is_not_allowed_via_root(self):
        q=p.FilePolicy('/MODEL/home','/MODEL/out',('/proc','/MODEL/public'),'darwin')
        v=options();v['immediate']['source_sha256']='b'*64
        self.assertRaises(p.BoundaryRefused,config_call,q,v)
    def test_unknown_path_remains_denied_under_real_roots(self):
        q=regression.previous.policy()
        self.assertRaises(p.BoundaryRefused,regression.previous.request,q,'/proc/OTHER')


BAD_CONFIG={
 'digest':lambda v:v['immediate'].update(source_sha256='b'*64),
 'line':lambda v:v['immediate'].update(line=869),
 'bool_line':lambda v:v['immediate'].update(line=True),
 'outer_digest':lambda v:v['caller']['frames'][1].update(source_sha256='b'*64),
 'outer_line':lambda v:v['caller']['frames'][1].update(line=887),
 'outer_bool_line':lambda v:v['caller']['frames'][1].update(line=True),
 'outer_missing':lambda v:v['caller']['frames'].pop(),
 'outer_unbound':lambda v:v['caller']['frames'].pop(1),
 'first_mismatch':lambda v:v['caller']['frames'][0].update(line=869),
 'chain_reversed':lambda v:v['caller']['frames'].reverse(),
 'immediate_extra':lambda v:v['immediate'].update(raw='SECRET_SENTINEL'),
 'frame_extra':lambda v:v['caller']['frames'][0].update(raw='SECRET_SENTINEL'),
 'truncated':lambda v:v['caller'].update(frames=[],truncated=True),
 'caller_bool_unknown':lambda v:v['caller'].update(unknown_frames=True),
 'alias_requested':lambda v:v.update(requested='/MODEL/alias'),
 'alias_canonical':lambda v:v.update(canonical='/MODEL/alias'),
 'write':lambda v:v.update(mode='w'),
 'write_flag':lambda v:v.update(flags=1),
 'unknown_flag':lambda v:v.update(flags=1<<29),
 'mountinfo_not_config_site':lambda v:v.update(requested='/proc/self/mountinfo',canonical='/proc/self/mountinfo'),
 'other_proc':lambda v:v.update(requested='/proc/OTHER',canonical='/proc/OTHER'),
 'relative':lambda v:v.update(requested='proc/1/cgroup',canonical='proc/1/cgroup')}
class ConfigRejectTests(unittest.TestCase):
    def test_linux_platform_is_not_synthetic_darwin(self):
        self.assertRaises(p.BoundaryRefused,config_call,regression.previous.policy('linux'))
    def test_corrupt_private_counter_bool_is_not_permission(self):
        q=regression.previous.policy();q._config_missing=True
        self.assertRaises(p.BoundaryRefused,config_call,q)
    def test_corrupt_private_counter_overflow_is_not_permission(self):
        q=regression.previous.policy();q._config_missing=65
        self.assertRaises(p.BoundaryRefused,config_call,q)
for label,mutate in BAD_CONFIG.items():
    def case(self,mutate=mutate):
        q=regression.previous.policy();v=options();mutate(v)
        self.assertRaises(p.BoundaryRefused,config_call,q,v)
        self.assertEqual(q.state()['config_missing'],0)
        self.assertRaises(p.BoundaryRefused,q.ensure_clean)
        self.assertNotIn('SECRET_SENTINEL',json.dumps(q.state()))
    setattr(ConfigRejectTests,'test_reject_'+label,case)


class PublicASTTests(unittest.TestCase):
    def test_bound_public_ast_constants_and_config_no_filesystem(self):
        q=regression.previous.policy();namespace=ast_namespace(q)
        self.assertFalse(namespace['is_container']());self.assertFalse(namespace['is_container']())
        namespace['_secure_file']('/MODEL/nonexistent-owned')
        namespace['_secure_file']('/MODEL/nonexistent-owned')
        self.assertEqual(q.state()['missing'],{'cgroup':1,'mountinfo':1})
        self.assertEqual(q.state()['config_missing'],2);q.ensure_clean()
    def test_uncached_public_config_reaches_finite_cap(self):
        q=regression.previous.policy();namespace=ast_namespace(q)
        for _ in range(64):namespace['_secure_file']('/MODEL/nonexistent-owned')
        self.assertRaises(p.BoundaryRefused,namespace['_secure_file'],'/MODEL/nonexistent-owned')
        self.assertEqual(q.state()['config_missing'],64);self.assertEqual(q.state()['denied_count'],1)
    def test_direct_public_helper_without_secure_file_chain_denied(self):
        q=regression.previous.policy();namespace=ast_namespace(q)
        self.assertRaises(p.BoundaryRefused,namespace['_is_container'])
        self.assertEqual(q.state()['config_missing'],0)
    def test_public_open_and_caller_line_literals(self):
        container=next(x for x in CONFIG_FUNCTIONS if x.name=='_is_container')
        sites=[x for x in ast.walk(container) if isinstance(x,ast.Call)
               and isinstance(x.func,ast.Name) and x.func.id=='open']
        self.assertEqual([(x.lineno,[arg.value for arg in x.args]) for x in sites],
                         [(868,['/proc/1/cgroup','r'])])
        secure=next(x for x in CONFIG_FUNCTIONS if x.name=='_secure_file')
        self.assertEqual([x.lineno for x in ast.walk(secure) if isinstance(x,ast.Call)
            and isinstance(x.func,ast.Name) and x.func.id=='_is_container'],[886])
    def test_public_config_cache_is_not_invented(self):
        container=next(x for x in CONFIG_FUNCTIONS if x.name=='_is_container')
        self.assertFalse(any(isinstance(x,ast.Name) and x.id=='_container_detected'
                             for x in ast.walk(container)))


STATE_MUTATIONS={
 'bool':lambda r:r.update(config_missing=True),
 'false':lambda r:r.update(config_missing=False),
 'negative':lambda r:r.update(config_missing=-1),
 'overflow':lambda r:r.update(config_missing=65),
 'float':lambda r:r.update(config_missing=1.0),
 'text':lambda r:r.update(config_missing='SECRET_SENTINEL'),
 'list':lambda r:r.update(config_missing=[]),
 'null':lambda r:r.update(config_missing=None),
 'missing':lambda r:r.pop('config_missing'),
 'extra':lambda r:r.update(raw='SECRET_SENTINEL'),
 'old_schema':lambda r:r.update(schema='hud_startup_boundary_state_v1')}
class ConfigSchemaTests(unittest.TestCase):
    def test_inclusive_counter_bounds(self):
        row=regression.previous.policy().state()
        for count in (0,1,63,64):
            row['config_missing']=count;self.assertTrue(p.state_valid(row))
for label,mutate in STATE_MUTATIONS.items():
    def case(self,mutate=mutate):
        row=regression.previous.policy().state();mutate(row)
        self.assertFalse(p.state_valid(row))
    setattr(ConfigSchemaTests,'test_state_reject_'+label,case)


class ConfigTerminalTests(unittest.TestCase):
    def row(self):return regression.run()[1]
    def test_monotonic_counter_and_child_do_not_change_model_only_scope(self):
        row=self.row()
        for ack,count in zip(row['checkpoints'],(1,2,2,4)):ack['state']['file']['config_missing']=count
        row['child']['state']['file']['config_missing']=4
        self.assertTrue(a.valid(row));self.assertTrue(a.pass_conditions(row))
        result=a.analyze(l.encode(row),{'schema':'hud_short_completion_v5',
            'payload_sha256':a.hashlib.sha256(l.encode(row)).hexdigest(),'verdict':'PASS',
            'freeze_sha256':regression.F,'review_sha256':regression.R,'seconds_at_seal':100.},
            regression.F,regression.R)
        self.assertEqual(result['result'],'VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY')
        self.assertEqual(result['memory_risk'],'WARN_NOT_ACCEPTED');self.assertEqual(result['public_release'],'BLOCK')
    def test_checkpoint_counter_reset_rejected(self):
        row=self.row();row['checkpoints'][0]['state']['file']['config_missing']=2
        self.assertFalse(a.valid(row))
    def test_child_counter_reset_rejected(self):
        row=self.row()
        for ack in row['checkpoints']:ack['state']['file']['config_missing']=2
        row['child']['state']['file']['config_missing']=1
        self.assertFalse(a.valid(row))
    def test_counter_consumption_does_not_override_actual_nonzero_exit(self):
        row=self.row();row['cleanup']['exit_code']=2
        row['handle_observation']['exit_code']=2
        self.assertFalse(a.pass_conditions(row))
    def test_old_backend_v3_rejected(self):
        row=self.row();row['schema']='hud_short_startup_backend_v3'
        self.assertFalse(a.valid(row))
    def test_old_child_terminal_v1_rejected(self):
        row=self.row();row['child']['schema']='hud_short_child_terminal_v1'
        self.assertFalse(a.valid(row))
    def test_old_guard_stack_v1_rejected(self):
        row=self.row();row['checkpoints'][0]['state']['schema']='hud_smoke_guard_stack_v1'
        self.assertFalse(a.valid(row))
    def test_old_completion_v3_rejected(self):
        row=self.row();payload=l.encode(row)
        seal={'schema':'hud_short_completion_v3','payload_sha256':a.hashlib.sha256(payload).hexdigest(),
            'verdict':'PASS','freeze_sha256':regression.F,'review_sha256':regression.R,'seconds_at_seal':100.}
        self.assertEqual(a.analyze(payload,seal,regression.F,regression.R)['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
    def test_old_scope_not_new_authority(self):
        auth=copy.deepcopy(regression.AUTH)
        auth['scope']='one_owned_direct_interpreter_startup_300s_http1_ws1_no_retry_no_risk_acceptance'
        self.assertFalse(l.authority_valid(auth,100.,regression.F,regression.R))


if __name__=='__main__':
    sys.addaudithook(full.audit)
    groups=[regression.previous,regression,full,old.prior,old,previous,sys.modules[__name__]]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in groups)
    result=unittest.TextTestRunner(verbosity=2,resultclass=old.prior.NoSourceTracebackResult).run(suite)
    print(json.dumps({'tests':result.testsRun,'success':result.wasSuccessful(),'inputs':INPUTS,
        'attempts_after_preload':full.ATTEMPTS,'python_version':sys.version,'executable':sys.executable,
        'scope':'CONFIG_PROBE_POLICY_AST_AND_MONOTONIC_COUNTER_MODELS_PLUS_PRIOR449',
        'native_execution':'NOT_RUN','real_event_loop':'NOT_RUN','real_pipes_psutil':'NOT_RUN',
        'preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(full.ATTEMPTS.values()) else 1)
