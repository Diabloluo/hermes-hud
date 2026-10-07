"""Cooperative models only; no real pipe, Mach, psutil, fixture DB, network or host."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import pair_contract as c
import analyze as a
import runner
import memory_sampling
import lifecycle
import controller
import entry
from guard_stack import GuardStack,stack_valid
from boundary_policy import FilePolicy,BoundFrames,BoundaryRefused
from optional_process import missing_allowed,COLLECTORS_SHA
from pair_record import encode
from common import require

def state(n=0):
    return {'schema':'hud_memory_guard_stack_v1','file':{'schema':'hud_startup_boundary_state_v2',
      'scope':'RESTRICTED_SYNTHETIC_ENVIRONMENT_NOT_NATIVE_HOST_COMPATIBILITY',
      'missing':{'cgroup':1,'mountinfo':1},'config_missing':1,'denied_count':0,'last_denial':None},
      'other_denials':0,'last_error':None,'last_other_denial':None,'launchctl_missing':n}
def resource():
    return {'schema':'hud_initial_resource_diagnostic_v1','dependency_status':'PASS',
      'memory_status':'PASS','disk_status':'PASS','available_memory_bytes':4*1024**3,
      'free_disk_bytes':6*1024**3,'memory_min_bytes':3*1024**3,'disk_min_bytes':5*1024**3,'error':None}
def source():return dict.fromkeys(('candidate','public_source','fixture'),'a'*64)
def sample(at,label):return dict(at=at,phase=label,**{k:1000 for k in c.METRICS})
def cp(seq,arm):
    value={'trace_records':1,'snapshot_bytes':10,'delta_rows':0,'net_delta_bytes':0,
      'top':[],'interpretation':'filename_provenance_only_not_ownership'}
    return {'sequence':seq,'label':c.LABELS[seq-1],'compare_to':None if seq==1 else 1,
      'snapshot_count':int(arm=='snapshot'),'gc_count':0,'seconds':.1,
      'values':value if arm=='snapshot' else None,'state':state()}
def fixture():
    return {'counts':a.COUNTS.copy(),'schema_source_sha256':'b'*64,
      'source_hashes':{'state.db':'c'*64,'job-ledger/jobs.jsonl':'d'*64},'query_only':True,
      'native_ddl':'fresh pinned distribution SCHEMA_SQL; required fields not patched','timeline_total':None}
def arm(name):
    phases=[];samples=[];operations=[];at=100.;seq=0
    for label,seconds,load in c.PHASES:
        phases.append({'label':label,'seconds':seconds,'start':at,'end':at+seconds,
             'http':4 if load else 0,'ws':1 if load else 0,'handshakes':1 if load else 0,'state':state()})
        samples.extend(sample(at+i,label) for i in range(1,seconds,2));at+=seconds
        if label in c.LABELS:
            seq+=1;operations.append({'sequence':seq,'label':label,'at':at,
              'observed_seconds':.2,'window_seconds':30,'checkpoint':cp(seq,name)});at+=30
    return {'arm':name,'candidate':'PASS','error':None,'seconds':2400,'resource':resource(),
      'identity_diagnostic':None,'cleanup':{'identity_matched':True,'alive':False,'exit_code':0,'error':None},
      'handle':{'alive':False,'exit_code':0,'error':None},
      'child':{'schema':'hud_memory_child_terminal_v1','candidate':'PASS','source_end':source(),
          'state':state(),'commanded_exit':True,'exit_code':0},
      'source_start':source(),'source_end':source(),'fixture':fixture(),'counts_end':a.COUNTS.copy(),
      'phases':phases,'operations':operations,'samples':samples,
      'smoke':{'port':12001,'http_status':200,'http_bytes':100,'http_schema':1,
              'ws_frames':1,'ws_bytes':100,'ws_schema':1,'handshakes':1}}
def pair(kind='MODEL'):
    return {'schema':'hud_finite_attribution_pair_v1','result':'PENDING_TERMINAL_SEAL','candidate':'PASS',
      'error':None,'grant':'e'*32,'sha':'f'*40,'run_id':'123','execution_kind':kind,
      'freeze_start':'a'*64,'freeze_end':'a'*64,'review':'b'*64,'arms':[arm('sham'),arm('snapshot')],
      'seconds':4900,'limits':c.LIMITS[:],'growth_acceptance_budget':None,
      'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK'}
def analyzed(x,verdict='PASS'):
    payload=encode(x);seal={'schema':'hud_memory_pair_completion_v1',
      'payload_sha256':hashlib.sha256(payload).hexdigest(),'verdict':verdict,'freeze_sha256':'a'*64,
      'review_sha256':'b'*64,'seconds_at_seal':4901}
    return a.analyze(payload,seal,'a'*64,'b'*64)

class ContractTests(unittest.TestCase):
    def test_complete_model(self):
        result=analyzed(pair());self.assertEqual(result['result'],'VERIFIED_OFFLINE_PAIR_MODEL_ONLY')
        self.assertEqual(len(result['arms']),2);self.assertEqual(result['memory_risk'],'WARN_NOT_ACCEPTED')
    def test_injected_native_record_only(self):
        self.assertEqual(analyzed(pair('NATIVE'))['result'],'VERIFIED_REMOTE_SAME_TRACE_FINITE_PAIR_ONLY')
    def test_coverage(self):
        row={'label':'baseline','start':0,'end':120,'seconds':120}
        q,m=c.quality([sample(t,'baseline') for t in range(1,120,2)],row)
        self.assertEqual(q['coverage'],1);self.assertEqual(m['fds'],1000)
    def test_gap_rejected(self):
        row={'label':'baseline','start':0,'end':120,'seconds':120}
        with self.assertRaises(BoundaryRefused):c.quality([sample(t,'baseline') for t in range(1,120,2) if not 50<t<65],row)
    def test_slope(self):self.assertEqual(c.slope([(0,0),(1,1),(2,2),(3,3)]),3600)
    def test_three_points(self):
        with self.assertRaises(BoundaryRefused):c.slope([(0,0),(1,1),(2,2)])
    def test_order(self):
        with self.assertRaises(BoundaryRefused):c.quality([sample(4,'baseline'),sample(2,'baseline')],
             {'label':'baseline','start':0,'end':120,'seconds':120})
    def test_counter_reset(self):self.assertFalse(c.monotonic_states([state(2),state(1)]))
    def test_unknown_exception_no_text(self):self.assertEqual(c.error_code(ValueError('resource')),'internal')
    def test_launch_bound(self):
        caller={'frames':[{'source_sha256':COLLECTORS_SHA,'line':933},
           {'source_sha256':COLLECTORS_SHA,'line':397}],'unknown_frames':0,'truncated':False}
        args=('launchctl',['launchctl','print','gui/501'],None,None)
        self.assertTrue(missing_allowed('subprocess.Popen',args,caller,'darwin',501,127))
        self.assertFalse(missing_allowed('subprocess.Popen',args,caller,'darwin',501,128))
    def test_unknown_exec_sticky(self):
        stack=GuardStack(FilePolicy('/synthetic/home','/synthetic/out',('/synthetic/public',),'darwin'),
               BoundFrames({}),'/synthetic/home',12001,501,'darwin')
        with self.assertRaises(BoundaryRefused):stack.legacy_audit('subprocess.Popen',('SECRET',[],None,None))
        self.assertEqual(stack.state()['other_denials'],1)
        with self.assertRaises(BoundaryRefused):stack.checkpoint()
    def test_schema_old_rejected(self):
        x=state();x['schema']='hud_smoke_guard_stack_v3';self.assertFalse(stack_valid(x))

class SampleTests(unittest.TestCase):pass
def sample_bad(key,value):
    def test(self):
        x=sample(1,'baseline');x[key]=value;self.assertFalse(c.sample_valid(x))
    return test
for key in c.METRICS:
    for label,value in [('bool',True),('negative',-1),('overflow',2**63)]:
        setattr(SampleTests,'test_'+key+'_'+label,sample_bad(key,value))

MUTATIONS=[
 ('nonzero_actual_exit',lambda x:x['arms'][0]['handle'].update(exit_code=2)),
 ('nonzero_cleanup_exit',lambda x:x['arms'][0]['cleanup'].update(exit_code=2)),
 ('nonzero_child_exit',lambda x:x['arms'][0]['child'].update(exit_code=2)),
 ('fake_clean',lambda x:x['arms'][0]['cleanup'].update(identity_matched=False)),
 ('natural_exit',lambda x:x['arms'][0]['cleanup'].update(error='unexpected_exit')),
 ('missing_arm',lambda x:x['arms'].pop()),
 ('reversed_arms',lambda x:x['arms'].reverse()),
 ('missing_cooldown',lambda x:x['arms'][0]['phases'].pop(3)),
 ('missing_operation',lambda x:x['arms'][0]['operations'].pop()),
 ('sham_snapshot',lambda x:x['arms'][0]['operations'][0]['checkpoint'].update(values=cp(1,'snapshot')['values'])),
 ('wrong_compare',lambda x:x['arms'][1]['operations'][2]['checkpoint'].update(compare_to=2)),
 ('gc',lambda x:x['arms'][1]['operations'][4]['checkpoint'].update(gc_count=1)),
 ('operation_timeout',lambda x:x['arms'][1]['operations'][1].update(observed_seconds=30)),
 ('window_short',lambda x:x['arms'][0]['operations'][1].update(window_seconds=29)),
 ('sample_gap',lambda x:x['arms'][0].update(samples=x['arms'][0]['samples'][40:])),
 ('boundary_denial',lambda x:x['arms'][0]['child']['state']['file'].update(denied_count=1)),
 ('source_changed',lambda x:x['arms'][1]['source_end'].update(fixture='f'*64)),
 ('fixture_changed',lambda x:x['arms'][1]['fixture']['counts'].update(messages=1)),
 ('bool_counts',lambda x:x['arms'][1]['counts_end'].update(active_sessions=True)),
 ('resource_not_pass',lambda x:x['arms'][0]['resource'].update(memory_status='FAIL')),
 ('secret_extra',lambda x:x['arms'][0].update(raw='SECRET_SENTINEL')),
 ('secret_phase',lambda x:x['arms'][0]['phases'][0].update(raw='SECRET_SENTINEL')),
 ('secret_sample',lambda x:x['arms'][0]['samples'][0].update(raw='SECRET_SENTINEL')),
 ('unknown_error',lambda x:x.update(error='SECRET_SENTINEL')),
 ('wrong_schema',lambda x:x.update(schema='hud_short_startup_backend_v6')),
 ('wrong_freeze',lambda x:x.update(freeze_end='f'*64)),
 ('risk_accept',lambda x:x.update(memory_risk='ACCEPTED')),
 ('public_pass',lambda x:x.update(public_release='PASS')),
 ('posthoc_budget',lambda x:x.update(growth_acceptance_budget=100000)),
 ('out_of_budget',lambda x:x.update(seconds=6000)),
 ('bool_time',lambda x:x.update(seconds=True)),
 ('counter_reset',lambda x:x['arms'][0]['phases'][0].update(state=state(2))),
 ('cooldown_load',lambda x:x['arms'][0]['phases'][3].update(http=4)),
 ('handshake_twice',lambda x:x['arms'][0]['phases'][0].update(handshakes=2)),
 ('op_out_of_phase',lambda x:x['arms'][0]['operations'][0].update(at=0)),
 ('old_child',lambda x:x['arms'][0]['child'].update(schema='hud_short_child_terminal_v3')),
]
class MutationTests(unittest.TestCase):pass
def mutated(fn):
    def test(self):
        x=pair();fn(x);r=analyzed(x)
        self.assertEqual(r['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
        self.assertEqual(r['ols_status'],'INCOMPLETE_NO_SLOPE')
        self.assertNotIn('SECRET_SENTINEL',json.dumps(r))
    return test
for name,fn in MUTATIONS:setattr(MutationTests,'test_'+name,mutated(fn))

class SealTests(unittest.TestCase):
    def test_fail_never_upgrade(self):
        x=pair();x['candidate']='FAIL';x['error']='resource'
        r=analyzed(x,'FAIL');self.assertEqual(r['error'],'execution_failed');self.assertEqual(r['ols_status'],'INCOMPLETE_NO_SLOPE')
    def test_fail_with_invalid_nested_discarded(self):
        x=pair();x['candidate']='FAIL';x['arms'][0]['samples'][0]['raw']='SECRET_SENTINEL'
        self.assertEqual(analyzed(x,'FAIL')['arms'],[])
    def test_no_seal(self):self.assertEqual(a.analyze(encode(pair()),None,'a'*64,'b'*64)['arms'],[])
    def test_wrong_payload_digest(self):
        self.assertEqual(a.analyze(b'{}',{},'a'*64,'b'*64)['result'],'DIAGNOSTIC_ONLY_NOT_VERIFIED')
    def test_duplicate_fields(self):
        self.assertRaises(BoundaryRefused,json.loads,'{"x":1,"x":2}',object_pairs_hook=__import__('common').object_pairs)

class GateTests(unittest.TestCase):
    def grant(self):
        return {'schema':lifecycle.SCHEMA,'id':'a'*32,'scope':lifecycle.SCOPE,'freeze_sha256':'b'*64,
          'review_sha256':'c'*64,'issued':100.,'expires':200.,'max_runs':1,'owner_confirmed':True}
    def test_no_gate(self):
        with self.assertRaises(BoundaryRefused):controller.gates({}, {},'b'*64,'c'*64,101)
    def test_old_scope(self):
        g=self.grant();g['scope']='one_owned_resource_diagnostic_startup_300s_http1_ws1_no_retry_no_risk_acceptance'
        self.assertFalse(lifecycle.authority_valid(g,101,'b'*64,'c'*64))
    def test_expired(self):self.assertFalse(lifecycle.authority_valid(self.grant(),200,'b'*64,'c'*64))
    def test_future(self):self.assertFalse(lifecycle.authority_valid(self.grant(),99,'b'*64,'c'*64))
    def test_bool_runs(self):
        g=self.grant();g['max_runs']=True;self.assertFalse(lifecycle.authority_valid(g,101,'b'*64,'c'*64))
    def test_workflow_replay(self):
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'Diabloluo/hermes-hud','GITHUB_EVENT_NAME':'workflow_dispatch',
          'GITHUB_RUN_ATTEMPT':'2','GITHUB_REF':'refs/heads/test/v2-isolated-memory-20261003','GITHUB_SHA':'f'*40}
        with self.assertRaises(BoundaryRefused):entry.workflow_authority(env,'f'*40,'a'*32,100.,200.,'c'*64,101)
    def test_direct_pair_no_authority(self):
        coroutine=runner.pair(Path('/synthetic'),Path('/synthetic/repo'),{},'a'*64,'b'*64,lambda _:True,'f'*40,'123')
        with self.assertRaises(BoundaryRefused):coroutine.send(None)

class CleanupTests(unittest.TestCase):
    def proc(self,code=None,wait=0):
        class P:
            def __init__(self):self.signals=[]
            def poll(self):return code
            def terminate(self):self.signals.append('TERM')
            def kill(self):self.signals.append('KILL')
            def wait(self,timeout):return wait
        return P()
    def identity(self):
        return {'pid':1,'birth':100.,'cwd':'/synthetic/home','argv':['/synthetic/python'],'exe':'/synthetic/python'}
    def test_unknown_zero_signal(self):
        p=self.proc();r=lifecycle.close_owned(p,None,lambda _:self.identity())
        self.assertEqual(p.signals,[]);self.assertEqual(r['error'],'identity')
    def test_identity_race(self):
        p=self.proc();x=self.identity();x['birth']=101.
        r=lifecycle.close_owned(p,self.identity(),lambda _:x)
        self.assertEqual(p.signals,[]);self.assertFalse(r['identity_matched'])
    def test_natural_exit_not_matched(self):
        p=self.proc(0);r=lifecycle.close_owned(p,self.identity(),lambda _:self.identity())
        self.assertEqual(p.signals,[]);self.assertFalse(r['identity_matched']);self.assertEqual(r['error'],'unexpected_exit')
    def test_nonzero_exit_retained(self):
        p=self.proc(wait=2);r=lifecycle.close_owned(p,self.identity(),lambda _:self.identity())
        self.assertEqual(r['exit_code'],2);self.assertEqual(p.signals,['TERM'])
    def test_normal_exit(self):
        p=self.proc();r=lifecycle.close_owned(p,self.identity(),lambda _:self.identity())
        self.assertEqual(r,{'identity_matched':True,'alive':False,'exit_code':0,'error':None})

class SnapshotTests(unittest.TestCase):
    def test_first_snapshot_baseline_retained(self):
        calls=[]
        class Snapshot:
            traces=[1]
            def statistics(self,_):return []
            def compare_to(self,baseline,_):calls.append(baseline);return []
        class Trace:
            def take_snapshot(self):return Snapshot()
        value,baseline=memory_sampling.checkpoint(Trace(),None)
        for _ in range(4):
            value,next_baseline=memory_sampling.checkpoint(Trace(),baseline);self.assertIs(next_baseline,baseline)
        self.assertEqual(calls,[baseline]*4)
    def test_filename_never_resolved(self):
        class Snapshot:
            traces=[1]
            def statistics(self,_):return [types.SimpleNamespace(size=5,count=1,
              traceback=[types.SimpleNamespace(filename='/SECRET_SENTINEL',lineno=1)])]
        value,_=memory_sampling.checkpoint(types.SimpleNamespace(take_snapshot=lambda:Snapshot()),None)
        self.assertNotIn('SECRET_SENTINEL',json.dumps(value));self.assertEqual(value['top'][0]['bytes'],5)

class WiringTests(unittest.TestCase):
    def test_workflow_root_and_budget(self):
        b=(Path(__file__).parent/'DRAFT_WORKFLOW.yml').read_text()
        self.assertEqual(b.count('hud-finite-attribution-owned'),3)
        self.assertNotIn('hud-short-startup-owned',b);self.assertIn('timeout-minutes: 100',b)
        self.assertIn('timeout-minutes: 30',b);self.assertIn('timeout-minutes: 135',b)
    def test_sampler_real_newline(self):
        tree=ast.parse((Path(__file__).parent/'observer_smoke.py').read_text())
        values=[n.value for n in ast.walk(tree) if isinstance(n,ast.Constant)]
        self.assertIn('\n',values)
    def test_no_returncode(self):
        self.assertNotIn('.returncode',(Path(__file__).parent/'lifecycle.py').read_text())
    def test_same_trace_single_start(self):
        b=(Path(__file__).parent/'observer_smoke.py').read_text()
        self.assertEqual(b.count('tracemalloc.start(1)'),1);self.assertNotIn('gc.collect',b)
    def test_no_raw_artifact(self):
        b=(Path(__file__).parent/'DRAFT_WORKFLOW.yml').read_text()
        self.assertIn('/aggregate-artifact/analysis.json',b);self.assertNotIn('logs/',b)

class ExecutionModelTests(unittest.TestCase):
    def execute(self,failure=None,exit_code=0):
        template=arm('sham')
        class P:
            def __init__(self):self.pid=1;self.code=None;self.signals=[]
            def poll(self):return self.code
            def terminate(self):self.signals.append('TERM')
            def kill(self):self.signals.append('KILL')
            def wait(self,timeout):self.code=exit_code;return self.code
        proc=P()
        ident={'pid':1,'birth':100.,'cwd':'/synthetic/home','argv':['/synthetic/python'],'exe':'/synthetic/python'}
        class IO:
            arm='sham';grant='a'*32;out=Path('/synthetic/evidence');home=Path('/synthetic/home')
            def __init__(self):self.proc=None;self.saved=None;self.calls=[];self.tick=0
            def clock(self):self.tick+=1;return 0 if self.tick==1 else 2400
            def authorized(self):self.calls.append('authority');return failure!='authority'
            def no_active(self):self.calls.append('active');return failure!='active'
            def resources(self):self.calls.append('resource');return failure!='resource'
            def resource_diagnostic(self):
                r=resource()
                if failure=='resource':r.update(memory_status='FAIL',disk_status='NOT_CHECKED',
                    free_disk_bytes=None,available_memory_bytes=0)
                return r
            def claim(self,_):self.calls.append('claim')
            def initialize(self):self.calls.append('initialize')
            def sources(self):return source()
            def spawn(self):
                self.calls.append('spawn')
                if failure=='spawn':raise RuntimeError('SECRET_SENTINEL')
                self.proc=proc;return proc
            def expected(self,_):self.saved=ident;return ident
            def check(self,*_):return None
            def ready(self,*_):return None
            def acknowledge(self,label):self.calls.append(label);return None
            def http_once(self):self.calls.append('http_call')
            def ws_once(self):self.calls.append('ws_call')
            def transport(self):return template['smoke']
            def request_finish(self):self.calls.append('finish_request')
            def inspect(self,_):
                r=ident.copy()
                if failure=='cleanup':r['birth']=101.
                return r
            def identity_diagnostic(self):return None
            def child_terminal(self):return template['child']
            def release(self):self.calls.append('release')
        io=IO()
        async def phase_model(_,label,seconds,load):
            if failure=='phase':raise BoundaryRefused('phase')
            return next(x for x in template['phases'] if x['label']==label)
        async def operation_model(_,label,seq):
            if failure=='operation':raise BoundaryRefused('operation')
            return template['operations'][seq-1]
        with patch.object(runner,'phase',phase_model),patch.object(runner,'operation',operation_model),\
             patch.object(runner,'read',return_value=fixture()),patch.object(runner,'atomic'),\
             patch.object(runner,'rows',return_value=template['samples']),\
             patch.object(runner.fixture,'counts',return_value=a.COUNTS.copy()):
            coroutine=runner.run_arm(io)
            try:coroutine.send(None)
            except StopIteration as stop:return stop.value,io,proc
            self.fail('Model unexpectedly suspended; no real event loop permitted')
    def test_actual_runner_model(self):
        r,io,p=self.execute()
        self.assertEqual(r['candidate'],'PASS');self.assertEqual(len(r['phases']),11)
        self.assertEqual(len(r['operations']),5);self.assertEqual(io.calls.count('spawn'),1)
        self.assertEqual(io.calls.count('http_call'),1);self.assertEqual(io.calls.count('ws_call'),1)
        self.assertEqual(p.signals,['TERM'])
        self.assertLess(io.calls.index('claim'),io.calls.index('spawn'))
    def test_denied_authority_no_spawn(self):
        r,io,p=self.execute('authority')
        self.assertEqual(r['error'],'authority');self.assertNotIn('claim',io.calls);self.assertEqual(p.signals,[])
    def test_resource_stop_no_spawn(self):
        r,io,p=self.execute('resource')
        self.assertEqual(r['error'],'resource');self.assertNotIn('spawn',io.calls)
    def test_spawn_exception_no_cleanup_signal(self):
        r,io,p=self.execute('spawn');self.assertEqual(r['error'],'internal');self.assertEqual(p.signals,[])
    def test_phase_stop_cleanup(self):
        r,io,p=self.execute('phase');self.assertEqual(r['error'],'phase');self.assertEqual(p.signals,['TERM'])
    def test_operation_stop_cleanup(self):
        r,io,p=self.execute('operation');self.assertEqual(r['error'],'operation');self.assertEqual(p.signals,['TERM'])
    def test_nonzero_actual_exit_fail(self):
        r,io,p=self.execute(exit_code=2);self.assertEqual(r['candidate'],'FAIL');self.assertEqual(r['cleanup']['exit_code'],2)
    def test_unknown_cleanup_zero_signal(self):
        r,io,p=self.execute('cleanup');self.assertEqual(r['candidate'],'FAIL');self.assertEqual(p.signals,[])

class PairLifecycleModelTests(unittest.TestCase):
    def run_pair(self,fail_first=False,reuse=False):
        import io as memory_io
        data={};claims=[]
        class VirtualPath:
            def __init__(self,value):self.value=str(value)
            def __truediv__(self,name):return VirtualPath(self.value+'/'+name)
            def __eq__(self,other):return isinstance(other,VirtualPath) and self.value==other.value
            def resolve(self):return self
            def mkdir(self,*args,**kwargs):return None
            def open(self,mode):
                if mode=='x' and self.value in claims:raise FileExistsError()
                claims.append(self.value);return memory_io.StringIO()
            def read_bytes(self):return data[self.value]
        root=VirtualPath('/synthetic/hud-finite-attribution-owned');repo=VirtualPath('/synthetic/repo')
        calls=[]
        class ModelFactory:
            execution_kind='MODEL'
            def __init__(self,root,repo,grant,freeze,prepared,name,epoch,begin):self.arm=name
        async def modeled_arm(io):
            calls.append(io.arm);r=arm(io.arm)
            if fail_first and io.arm=='sham':r.update(candidate='FAIL',error='resource')
            return r
        authority={'schema':lifecycle.SCHEMA,'id':'a'*32,'scope':lifecycle.SCOPE,
           'freeze_sha256':'a'*64,'review_sha256':'b'*64,'issued':100.,'expires':200.,
           'max_runs':1,'owner_confirmed':True}
        env={'RUNNER_TEMP':'/synthetic','GITHUB_WORKSPACE':'/synthetic/repo','GITHUB_RUN_ID':'123'}
        with patch.object(runner,'Path',VirtualPath),patch.dict(__import__('os').environ,env),\
             patch.object(entry,'workflow_authority'),patch.object(runner.time,'time',return_value=150.),\
             patch.object(runner.time,'monotonic',return_value=100.),patch.object(runner,'NativeIO',ModelFactory),\
             patch.object(runner,'run_arm',modeled_arm),patch.object(runner,'publish',side_effect=lambda p,b:data.update({p.value:b})),\
             patch.object(runner,'atomic',side_effect=lambda p,b:data.update({p.value:b})):
            def once():
                coroutine=runner.pair(root,repo,authority,'a'*64,'b'*64,lambda _:True,'f'*40,'123')
                try:coroutine.send(None)
                except StopIteration as stop:return stop.value
            result=once()
            if reuse:
                with self.assertRaises(FileExistsError):once()
        return result,calls,claims,data
    def test_complete_pair_model(self):
        result,calls,claims,data=self.run_pair()
        self.assertTrue(result);self.assertEqual(calls,['sham','snapshot']);self.assertEqual(len(claims),1)
        payload=next(v for k,v in data.items() if k.endswith('/result.json'))
        self.assertEqual(json.loads(payload)['execution_kind'],'MODEL')
    def test_first_fail_stops_second(self):
        result,calls,claims,data=self.run_pair(True)
        self.assertFalse(result);self.assertEqual(calls,['sham']);self.assertEqual(len(claims),1)
    def test_replay_before_new_arm(self):
        result,calls,claims,data=self.run_pair(reuse=True)
        self.assertTrue(result);self.assertEqual(calls,['sham','snapshot']);self.assertEqual(len(claims),1)
