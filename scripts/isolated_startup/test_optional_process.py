"""Bound optional diagnostic cooperative tests. NO native process/audit tuple."""
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
import test_config_probe as previous
regression=previous.regression;full=previous.full;old=previous.old
g=previous.g;l=previous.l;a=previous.a;p=previous.p
import optional_process as o
COLLECTOR=HERE.parent/'remote-memory-identity-delivery-20261004/dashboard/hud/collectors.py'
DATA=COLLECTOR.read_bytes()
if hashlib.sha256(DATA).hexdigest()!=o.COLLECTORS_SHA:raise RuntimeError('SOURCE_BINDING')
TREE=ast.parse(DATA)
FUNCTION=next(x for x in TREE.body if isinstance(x,ast.FunctionDef) and x.name=='collect_launchd_check')
LAMBDA=next(x for x in ast.walk(TREE) if isinstance(x,ast.Lambda) and x.lineno==397)
QUERY=next(x for x in ast.walk(FUNCTION) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute)
           and isinstance(x.func.value,ast.Name) and x.func.value.id=='subprocess' and x.func.attr=='run')
if QUERY.lineno!=933:raise RuntimeError('SOURCE_BINDING')
BOUND=p.BoundFrames({str(COLLECTOR):o.COLLECTORS_SHA})
INPUTS=dict(previous.INPUTS)
for name in full.e.FILES:INPUTS[name]=hashlib.sha256((HERE/name).read_bytes()).hexdigest()
INPUTS[str(COLLECTOR)]=o.COLLECTORS_SHA

def caller():
    return {'frames':[{'source_sha256':o.COLLECTORS_SHA,'line':933},
                      {'source_sha256':o.COLLECTORS_SHA,'line':397}],
            'unknown_frames':3,'truncated':False}

def args():return ('launchctl',['launchctl','print','gui/4242'],None,None)

def stack(frames=None,uid=4242,platform='darwin'):
    return g.GuardStack(regression.previous.policy(),
        frames or SimpleNamespace(collect=lambda _:caller()),'/MODEL/home',50123,uid,platform)

def invoke(q,event='subprocess.Popen',values=None):
    q.legacy_audit(event,args() if values is None else values)

def namespace(q):
    class FakePath:
        @staticmethod
        def home():return FakePath()
        def __truediv__(self,_):return self
        def exists(self):return False
    def run(argv,**kwargs):
        if argv!=args()[1] or kwargs!={'capture_output':True,'text':True,'timeout':5}:
            raise AssertionError('AST_ARGV_CONTRACT')
        q.legacy_audit('subprocess.Popen',('launchctl',argv,None,None))
        raise AssertionError('NO_REAL_PROCESS_ALLOWED')
    builtin=dict(__builtins__ if isinstance(__builtins__,dict) else vars(__builtins__))
    original=builtin['__import__']
    def fake_import(name,*extra,**kw):
        if name=='subprocess':return SimpleNamespace(run=run)
        return original(name,*extra,**kw)
    builtin['__import__']=fake_import
    ns={'__builtins__':builtin,'sys':SimpleNamespace(platform='darwin'),
        'os':SimpleNamespace(getuid=lambda:4242),'Path':FakePath,'Any':object,
        't':lambda key,locale:key,'launchd_fn':None}
    exec(compile(ast.Module(body=[FUNCTION],type_ignores=[]),str(COLLECTOR),'exec'),ns)
    ns['launchd_fn']=ns['collect_launchd_check']
    return ns

class OptionalTests(unittest.TestCase):
    def test_exact_absence_is_not_real_spawn_and_not_denial(self):
        q=stack();self.assertRaises(FileNotFoundError,invoke,q)
        self.assertEqual(q.state()['launchctl_missing'],1)
        self.assertEqual(q.state()['other_denials'],0);self.assertTrue(g.clean_state(q.checkpoint()))
    def test_exact_design_cap_then_sticky_refusal(self):
        q=stack()
        for _ in range(16):self.assertRaises(FileNotFoundError,invoke,q)
        self.assertRaises(p.BoundaryRefused,invoke,q)
        self.assertEqual(q.state()['launchctl_missing'],16)
        self.assertRaises(p.BoundaryRefused,q.checkpoint)
    def test_actual_bound_function_lambda_frames_fall_back_unavailable(self):
        q=stack(BOUND);ns=namespace(q)
        result=eval(compile(ast.Expression(body=LAMBDA),str(COLLECTOR),'eval'),ns)()
        self.assertEqual({k:result[k] for k in ('managed','status','error_key')},
            {'managed':None,'status':'unavailable','error_key':'err_diagnostic_query'})
        self.assertEqual(q.state()['launchctl_missing'],1);self.assertTrue(g.clean_state(q.checkpoint()))
    def test_wrong_direct_ast_caller_caught_by_host_remains_sticky(self):
        q=stack(BOUND);result=namespace(q)['collect_launchd_check']()
        self.assertEqual(result['status'],'unavailable');self.assertEqual(q.state()['launchctl_missing'],0)
        self.assertEqual(q.state()['other_denials'],1);self.assertRaises(p.BoundaryRefused,q.checkpoint)
    def test_default_offline_constructor_cannot_enable_absence(self):
        q=regression.stack();self.assertRaises(p.BoundaryRefused,invoke,q)
    def test_returned_diagnostic_is_detached(self):
        q=stack();self.assertRaises(p.BoundaryRefused,invoke,q,'os.system',('SECRET',))
        row=q.state();row['last_other_denial']['caller']['frames'].clear();row['other_denials']=0
        self.assertEqual(q.state()['other_denials'],1);self.assertEqual(len(q.state()['last_other_denial']['caller']['frames']),2)
    def test_duplicate_install_has_distinct_fixed_label(self):
        q=stack();q.install(register=lambda _:None)
        self.assertRaises(p.BoundaryRefused,q.install,lambda _:None)
        self.assertEqual(q.state()['last_other_denial']['event'],'duplicate_install')
    def test_ast_query_is_only_the_bound_site(self):
        self.assertEqual(QUERY.lineno,933);self.assertEqual(LAMBDA.lineno,397)
        self.assertEqual(o.COLLECTORS_SHA,hashlib.sha256(DATA).hexdigest())

BAD={
 'other_event':lambda v:v.update(event='os.system'),
 'other_platform':lambda v:v.update(platform='linux'),
 'uid_bool':lambda v:v.update(owner_uid=True),
 'uid_negative':lambda v:v.update(owner_uid=-1),
 'uid_overflow':lambda v:v.update(owner_uid=2**31),
 'uid_mismatch':lambda v:v.update(owner_uid=4243),
 'used_bool':lambda v:v.update(used=False),
 'used_negative':lambda v:v.update(used=-1),
 'used_exhausted':lambda v:v.update(used=16),
 'args_list':lambda v:v.update(args=list(args())),
 'args_short':lambda v:v.update(args=args()[:3]),
 'executable_absolute':lambda v:v.update(args=('/bin/launchctl',args()[1],None,None)),
 'argv_tuple':lambda v:v.update(args=('launchctl',tuple(args()[1]),None,None)),
 'argv_string':lambda v:v.update(args=('launchctl','launchctl print gui/4242',None,None)),
 'argv_extra':lambda v:v.update(args=('launchctl',args()[1]+['SECRET'],None,None)),
 'cwd':lambda v:v.update(args=('launchctl',args()[1],'/SECRET',None)),
 'env':lambda v:v.update(args=('launchctl',args()[1],None,{'SECRET':'TOKEN'})),
 'wrong_command':lambda v:v.update(args=('launchctl',['launchctl','list','gui/4242'],None,None)),
 'caller_truncated':lambda v:v['caller'].update(truncated=True),
 'caller_short':lambda v:v['caller'].update(frames=caller()['frames'][:1]),
 'caller_extra':lambda v:v['caller'].update(raw='SECRET'),
 'line':lambda v:v['caller']['frames'][0].update(line=934),
 'lambda':lambda v:v['caller']['frames'][1].update(line=398),
 'source':lambda v:v['caller']['frames'][0].update(source_sha256='0'*64),
 'reversed':lambda v:v['caller']['frames'].reverse()}
class OptionalRejectTests(unittest.TestCase):pass
for name,mutate in BAD.items():
    def case(self,mutate=mutate):
        v=dict(event='subprocess.Popen',args=args(),caller=caller(),platform='darwin',owner_uid=4242,used=0)
        mutate(v);self.assertFalse(o.missing_allowed(**v))
    setattr(OptionalRejectTests,'test_reject_'+name,case)

class ProjectionTests(unittest.TestCase):
    def test_raw_arguments_and_uid_are_not_exported(self):
        q=stack();self.assertRaises(p.BoundaryRefused,invoke,q,'subprocess.Popen',('SECRET',))
        text=json.dumps(q.state());self.assertNotIn('SECRET',text);self.assertNotIn('4242',text)
        self.assertEqual(q.state()['last_other_denial']['event'],'subprocess_popen')
    def test_invalid_caller_is_empty_truncated(self):
        row=o.project('child_process_boundary','subprocess.Popen',{'raw':'SECRET'})
        self.assertTrue(o.denial_valid(row));self.assertEqual(row['caller'],{'frames':[],'unknown_frames':0,'truncated':True})
        self.assertNotIn('SECRET',json.dumps(row))
for event,label in o.LABELS.items():
    def case(self,event=event,label=label):
        code=next(k for k,v in o.BY_ERROR.items() if label in v)
        row=o.project(code,event,caller());self.assertEqual(row['event'],label);self.assertTrue(o.denial_valid(row))
    setattr(ProjectionTests,'test_fixed_event_'+label,case)

MUTATIONS={
 'bool':lambda r:r.update(launchctl_missing=True),
 'negative':lambda r:r.update(launchctl_missing=-1),
 'cap':lambda r:r.update(launchctl_missing=17),
 'float':lambda r:r.update(launchctl_missing=1.0),
 'missing':lambda r:r.pop('last_other_denial'),
 'raw':lambda r:r.update(raw='SECRET'),
 'old_schema':lambda r:r.update(schema='hud_smoke_guard_stack_v2'),
 'wrong_event':lambda r:r['last_other_denial'].update(event='os_kill'),
 'raw_event':lambda r:r['last_other_denial'].update(event='SECRET'),
 'error_mismatch':lambda r:r['last_other_denial'].update(error='signal_boundary'),
 'extra_diag':lambda r:r['last_other_denial'].update(raw='SECRET'),
 'bool_line':lambda r:r['last_other_denial']['caller']['frames'][0].update(line=True),
 'no_count':lambda r:r.update(other_denials=0),
 'no_diag':lambda r:r.update(last_other_denial=None)}
class SchemaTests(unittest.TestCase):
    def test_counter_bounds_and_clean_missing(self):
        row=stack().state()
        for count in (0,1,15,16):row['launchctl_missing']=count;self.assertTrue(g.clean_state(row))
for name,mutate in MUTATIONS.items():
    def case(self,mutate=mutate):
        q=stack();self.assertRaises(p.BoundaryRefused,invoke,q,'os.system',('SECRET',))
        row=q.state();mutate(row);self.assertFalse(g.stack_valid(row))
    setattr(SchemaTests,'test_schema_'+name,case)

class TerminalTests(unittest.TestCase):
    def row(self):return regression.run()[1]
    def test_monotonic_new_counter_keeps_model_only(self):
        row=self.row()
        for ack,count in zip(row['checkpoints'],(0,1,1,2)):ack['state']['launchctl_missing']=count
        row['child']['state']['launchctl_missing']=2
        self.assertTrue(a.pass_conditions(row))
        payload=l.encode(row);seal={'schema':'hud_short_completion_v5','payload_sha256':l.sha(payload),
            'verdict':'PASS','freeze_sha256':regression.F,'review_sha256':regression.R,'seconds_at_seal':100.}
        self.assertEqual(a.analyze(payload,seal,regression.F,regression.R)['result'],'VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY')
    def test_checkpoint_reset_rejected(self):
        row=self.row();row['checkpoints'][0]['state']['launchctl_missing']=1;self.assertFalse(a.valid(row))
    def test_child_reset_rejected(self):
        row=self.row();row['checkpoints'][-1]['state']['launchctl_missing']=1;self.assertFalse(a.valid(row))
    def test_old_backend_rejected(self):
        row=self.row();row['schema']='hud_short_startup_backend_v4';self.assertFalse(a.valid(row))
    def test_old_child_rejected(self):
        row=self.row();row['child']['schema']='hud_short_child_terminal_v2';self.assertFalse(a.valid(row))
    def test_old_scope_rejected(self):
        row=copy.deepcopy(regression.AUTH)
        row['scope']='one_owned_config_probe_startup_300s_http1_ws1_no_retry_no_risk_acceptance'
        self.assertFalse(l.authority_valid(row,100.,regression.F,regression.R))
    def test_old_seal_rejected(self):
        row=self.row();payload=l.encode(row)
        seal={'schema':'hud_short_completion_v4','payload_sha256':l.sha(payload),
            'verdict':'PASS','freeze_sha256':regression.F,'review_sha256':regression.R,'seconds_at_seal':100.}
        self.assertEqual(a.analyze(payload,seal,regression.F,regression.R)['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
    def test_actual_nonzero_cannot_pass_with_absence_counter(self):
        row=self.row();row['child']['state']['launchctl_missing']=1
        row['handle_observation']['exit_code']=2;row['cleanup']['exit_code']=2
        self.assertFalse(a.pass_conditions(row))

if __name__=='__main__':
    sys.addaudithook(full.audit)
    groups=[regression.previous,regression,full,old.prior,old,previous.previous,previous,sys.modules[__name__]]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in groups)
    result=unittest.TextTestRunner(verbosity=2,resultclass=old.prior.NoSourceTracebackResult).run(suite)
    print(json.dumps({'tests':result.testsRun,'success':result.wasSuccessful(),'inputs':INPUTS,
        'attempts_after_preload':full.ATTEMPTS,'python_version':sys.version,'executable':sys.executable,
        'scope':'COOPERATIVE_BOUND_COLLECTOR_AST_OPTIONAL_ABSENCE_AND_SCHEMA_MODELS_PLUS_PRIOR510',
        'native_execution':'NOT_RUN','real_event_loop':'NOT_RUN','real_pipes_psutil':'NOT_RUN',
        'real_popen_audit_tuple':'NOT_RUN','preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(full.ATTEMPTS.values()) else 1)
