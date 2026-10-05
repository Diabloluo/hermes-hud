"""In-memory lifecycle/IO/identity models. NO real pipe/psutil/socket/SQLite/host."""
import copy
import hashlib
import importlib
import io as stdio
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_repair as previous
import boundary_policy as p
import guard_stack as g
import lifecycle as l
import analyze_integration as a

F='a'*64
R='b'*64
SOURCE={'candidate':'c'*64,'public_source':p.SOURCE_SHA,'fixture':'d'*64}
IDENTITY={'pid':1234,'birth':100.0,'cwd':'/MODEL/home',
          'argv':['/MODEL/python','-I','-B','/MODEL/observer.py'], 'exe':'/MODEL/python'}
AUTH={'schema':l.SCHEMA,'id':'e'*32,'scope':l.SCOPE,'freeze_sha256':F,
      'review_sha256':R,'issued':90.0,'expires':1000.0,'max_runs':1,'owner_confirmed':True}
INPUTS={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in
        ('guard_stack.py','lifecycle.py','analyze_integration.py','test_integration.py')}
INPUTS.update(previous.INPUTS)
ATTEMPTS={'open':0,'process':0,'network':0,'sqlite':0,'signal':0}


def audit(event,args):
    kind=('open' if event=='open' else 'process' if event.startswith('subprocess.')
          or event in {'os.system','os.exec','os.fork','os.posix_spawn'} else
          'network' if event.startswith('socket.') else 'sqlite' if event.startswith('sqlite3.')
          else 'signal' if event in {'os.kill','os.killpg'} else None)
    if kind:
        ATTEMPTS[kind]+=1
        raise RuntimeError('OFFLINE_ONLY')


def stack():
    return g.GuardStack(previous.policy(), previous.BOUND,'/MODEL/home',50123)


class Process:
    def __init__(self):
        self.pid=1234
        self.code=None
        self.signals=[]
        self.timeout=False
        self.wait_error=False
    def poll(self):
        return self.code
    def terminate(self):
        self.signals.append('TERM')
        if not self.timeout:
            self.code=0
    def kill(self):
        self.signals.append('KILL')
        self.code=-9
    def wait(self,timeout):
        if self.wait_error:
            raise RuntimeError('SECRET')
        if self.code is None:
            raise TimeoutError()
        return self.code


class IO:
    def __init__(self, fail=None):
        self.calls=[]; self.fail=fail; self.at=0.0
        self.proc=Process(); self.guard=stack(); self.child= l.ChildLifecycle(self.guard,SOURCE)
        self.claimed=False; self.commanded=False; self.payload=None; self.completion=None
        self.after_seal_denial=False
    def hit(self,name):
        self.calls.append(name)
        if self.fail==name:
            raise RuntimeError('SECRET /Users/private/token')
    def clock(self): return self.at
    def wall(self): return 100.0
    def prepared(self,value): self.hit('prepared'); return value==F
    def no_active(self): self.hit('active'); return True
    def resources(self): self.hit('resource'); return True
    def claim(self,ident):
        self.hit('claim')
        if self.claimed: raise FileExistsError('SECRET')
        self.claimed=True
    def initialize(self): self.hit('initialization')
    def sources(self): self.hit('source'); return copy.deepcopy(SOURCE)
    def spawn(self): self.hit('spawn'); return self.proc
    def expected(self,proc): self.hit('expected'); return copy.deepcopy(IDENTITY)
    def check(self,proc,expected):
        self.hit('identity')
        l.require(proc.poll() is None and self.inspect(proc)==expected,'identity')
    def inspect(self,proc): self.hit('inspect'); return copy.deepcopy(IDENTITY)
    def ready(self,proc,expected): self.hit('ready')
    def acknowledge(self,label): self.hit('ack_'+label); return self.child.acknowledge(label)
    def http_once(self): self.hit('http')
    def ws_once(self): self.hit('ws')
    def request_finish(self): self.hit('finish'); self.commanded=True
    def child_terminal(self):
        self.hit('child_terminal')
        if self.after_seal_denial:
            try: self.guard.legacy_audit('os.kill',(1234,15))
            except p.BoundaryRefused: pass
        return self.child.terminal(SOURCE,self.commanded,self.proc.code)
    def publish_payload(self,payload): self.hit('payload'); self.payload=payload
    def read_payload(self): self.hit('read_payload'); return self.payload
    def publish_completion(self,row): self.hit('completion'); self.completion=row


def run(obj=None,authority=None):
    obj=obj or IO()
    row,seal=l.execute_model_io(obj,copy.deepcopy(AUTH) if authority is None else authority,F,R)
    return obj,row,seal,a.analyze(obj.payload,seal,F,R)


class GuardTests(unittest.TestCase):
    def test_hooks_are_separate_adapter_object(self):
        s=stack(); hooks=[]; s.install(hooks.append)
        self.assertEqual(len(hooks),2)
        self.assertIs(hooks[1],s._adapter)
        self.assertEqual(hooks[0].__self__,s)
        self.assertTrue(g.clean_state(s.checkpoint()))
    def test_double_install_fail_closed(self):
        s=stack(); s.install(lambda x: None)
        self.assertRaises(p.BoundaryRefused,s.install,lambda x: None)
        self.assertRaises(p.BoundaryRefused,s.checkpoint)
    def test_install_failure_no_retry(self):
        s=stack()
        def bad(x): raise RuntimeError('SECRET')
        self.assertRaises(RuntimeError,s.install,bad)
        self.assertRaises(p.BoundaryRefused,s.install,lambda x: None)
    def test_legacy_does_not_handle_open(self):
        s=stack(); s.legacy_audit('open',('/FOREIGN','rb',0))
        self.assertTrue(g.clean_state(s.checkpoint()))
    def test_exact_local_network_is_allowed(self):
        s=stack()
        for event in ('socket.bind','socket.connect'):
            s.legacy_audit(event,(None,('127.0.0.1',50123)))
            s.legacy_audit(event,(None,('::1',50123,0,0)))
        self.assertTrue(g.clean_state(s.checkpoint()))
    def test_owned_sql_model_allowed(self):
        s=stack()
        with patch.object(g.Path,'resolve',lambda self:self):
            s.legacy_audit('sqlite3.connect',('file:/MODEL/home/state.db?mode=ro',))
        self.assertTrue(g.clean_state(s.checkpoint()))
    def test_swallowed_unknown_open_remains_sticky(self):
        s=stack()
        self.assertRaises(p.BoundaryRefused,previous.request,s._adapter.policy,'/SECRET/path')
        self.assertRaises(p.BoundaryRefused,s.checkpoint)
        self.assertNotIn('SECRET',json.dumps(s.state()))


DENIALS=[('network_external','socket.connect',(None,('example.com',443))),
         ('network_production','socket.connect',(None,('127.0.0.1',9119))),
         ('network_other_port','socket.bind',(None,('127.0.0.1',0))),
         ('network_bool','socket.bind',(None,('127.0.0.1',True))),
         ('network_malformed','socket.connect',()),
         ('sql_external','sqlite3.connect',('/SECRET/db',)),
         ('sql_bool','sqlite3.connect',(True,))]
DENIALS += [(event.replace('.','_'),event,()) for event in sorted(g.EXEC_EVENTS|g.SIGNAL_EVENTS)]
for name,event,args in DENIALS:
    def case(self,event=event,args=args):
        s=stack()
        with patch.object(g.Path,'resolve',lambda self:self):
            self.assertRaises(p.BoundaryRefused,s.legacy_audit,event,args)
        self.assertRaises(p.BoundaryRefused,s.checkpoint)
        self.assertEqual(s.state()['other_denials'],1)
        self.assertNotIn('SECRET',json.dumps(s.state()))
    setattr(GuardTests,'test_sticky_'+name,case)


class ChildTests(unittest.TestCase):
    def test_all_success_checks_same_policy(self):
        s=stack(); c=l.ChildLifecycle(s,SOURCE)
        for label in l.CHECKPOINTS:
            self.assertEqual(c.acknowledge(label)['label'],label)
        self.assertTrue(l.child_valid(c.terminal(SOURCE,True,0)))
    def test_source_mutation_terminal_fail(self):
        c=l.ChildLifecycle(stack(),SOURCE)
        for label in l.CHECKPOINTS:c.acknowledge(label)
        x=dict(SOURCE,fixture='0'*64)
        self.assertEqual(c.terminal(x,True,0)['candidate'],'FAIL')
    def test_uncommanded_exit_fail(self):
        c=l.ChildLifecycle(stack(),SOURCE)
        for label in l.CHECKPOINTS:c.acknowledge(label)
        self.assertEqual(c.terminal(SOURCE,False,0)['candidate'],'FAIL')
    def test_bool_exit_not_int(self):
        c=l.ChildLifecycle(stack(),SOURCE)
        for label in l.CHECKPOINTS:c.acknowledge(label)
        self.assertEqual(c.terminal(SOURCE,True,False)['candidate'],'FAIL')
    def test_wrong_order_sets_failure_even_if_caught(self):
        c=l.ChildLifecycle(stack(),SOURCE)
        self.assertRaises(p.BoundaryRefused,c.acknowledge,'ws')
        for label in l.CHECKPOINTS:c.acknowledge(label)
        self.assertEqual(c.terminal(SOURCE,True,0)['candidate'],'FAIL')


class ExecutorTests(unittest.TestCase):
    def test_complete_model_lifecycle(self):
        obj,row,seal,analysis=run()
        self.assertEqual(analysis['result'],'VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY')
        self.assertEqual(row['result'],'PENDING_TERMINAL_SEAL')
        self.assertEqual(row['http_calls'],1);self.assertEqual(row['ws_calls'],1)
        self.assertEqual(obj.proc.signals,['TERM'])
        self.assertLess(obj.calls.index('claim'),obj.calls.index('initialization'))
        self.assertLess(obj.calls.index('initialization'),obj.calls.index('spawn'))
        self.assertEqual(analysis['native_execution'],'NOT_VERIFIED')
    def test_no_authority_does_not_claim_or_spawn(self):
        obj,row,seal,analysis=run(authority={})
        self.assertNotIn('claim',obj.calls);self.assertNotIn('spawn',obj.calls)
        self.assertEqual(row['error'],'authority')
    def test_replay_does_not_initialize_spawn_or_delete_claim(self):
        obj=IO();obj.claimed=True
        _,row,_,_=run(obj)
        self.assertEqual(row['error'],'claim');self.assertTrue(obj.claimed)
        self.assertNotIn('initialization',obj.calls)
    def test_identity_binding_failure_retains_handle_zero_signals(self):
        obj,row,_,_=run(IO('expected'))
        self.assertEqual(row['error'],'spawn')
        self.assertEqual(obj.proc.signals,[])
        self.assertEqual(row['cleanup_error'],'cleanup')
    def test_past_budget_no_spawn(self):
        obj=IO()
        def init():obj.at=280.0
        obj.initialize=init
        # At this point init has finished: must check BEFORE spawn as well.
        _,row,seal,_=run(obj)
        self.assertEqual(row['error'],'budget')
        self.assertNotIn('spawn',obj.calls)
    def test_post_finish_swallowed_denial_blocks_seal(self):
        obj=IO();obj.after_seal_denial=True
        _,row,seal,analysis=run(obj)
        self.assertEqual(row['candidate'],'FAIL')
        self.assertNotEqual(analysis['result'],'VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY')
    def test_completion_write_failure_no_authoritative_pass(self):
        obj,row,seal,analysis=run(IO('completion'))
        self.assertIsNone(seal)
        self.assertEqual(analysis['error'],'evidence_invalid')
    def test_payload_readback_drift_no_completion(self):
        obj=IO();obj.read_payload=lambda:b'DRIFT'
        _,row,seal,_=run(obj)
        self.assertIsNone(seal);self.assertIsNone(obj.completion)
    def test_seal_time_rechecked_after_write(self):
        obj=IO()
        def write(payload):obj.payload=payload;obj.at=300.0
        obj.publish_payload=write
        _,_,seal,_=run(obj)
        self.assertIsNone(seal)
    def test_source_end_drift_fail(self):
        obj=IO();n=[0]
        def src():
            n[0]+=1
            return dict(SOURCE,fixture=('d' if n[0]==1 else 'a')*64)
        obj.sources=src
        _,row,_,_=run(obj)
        self.assertEqual(row['error'],'source')
    def test_invalid_source_never_persisted(self):
        obj=IO();obj.sources=lambda:dict(SOURCE,raw='SECRET')
        _,row,_,_=run(obj)
        self.assertIsNone(row['source_start'])
        self.assertNotIn('SECRET',obj.payload.decode())
    def test_invalid_child_fail_body_never_persisted(self):
        obj=IO('http')
        obj.child_terminal=lambda:{'candidate':'FAIL','raw':'SECRET'}
        _,row,_,_=run(obj)
        self.assertIsNone(row['child']);self.assertNotIn('SECRET',obj.payload.decode())
    def test_invalid_source_end_never_persisted(self):
        obj=IO();n=[0]
        def src():
            n[0]+=1
            return SOURCE if n[0]==1 else dict(SOURCE,raw='SECRET')
        obj.sources=src
        _,row,_,_=run(obj)
        self.assertIsNone(row['source_end']);self.assertNotIn('SECRET',obj.payload.decode())


for name in ('prepared','active','resource','claim','initialization','source','spawn','identity',
             'ready','http','ws','ack_ready','ack_http','ack_ws','ack_finish','finish',
             'child_terminal','inspect','payload','read_payload'):
    def case(self,name=name):
        obj,row,seal,analysis=run(IO(name))
        self.assertNotEqual(analysis['result'],'VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY')
        self.assertNotIn('SECRET',l.encode(row).decode())
        self.assertLessEqual(obj.calls.count('http'),1);self.assertLessEqual(obj.calls.count('ws'),1)
        self.assertLessEqual(obj.calls.count('spawn'),1)
        if 'claim' in obj.calls and name!='claim':self.assertTrue(obj.claimed)
    setattr(ExecutorTests,'test_injected_'+name,case)


class CleanupTests(unittest.TestCase):
    def test_term_then_verified_kill(self):
        proc=Process();proc.timeout=True;n=[0]
        def inspect(_):n[0]+=1;return copy.deepcopy(IDENTITY)
        result=l.close_owned(proc,IDENTITY,inspect)
        self.assertEqual(proc.signals,['TERM','KILL']);self.assertEqual(n[0],2)
        self.assertTrue(l.cleanup_valid(result));self.assertEqual(result['exit_code'],-9)
    def test_reused_before_term_no_signal(self):
        proc=Process()
        result=l.close_owned(proc,IDENTITY,lambda _:dict(IDENTITY,birth=101.0))
        self.assertEqual(proc.signals,[]);self.assertEqual(result['error'],'identity')
    def test_reused_before_kill_no_kill(self):
        proc=Process();proc.timeout=True;n=[0]
        def inspect(_):n[0]+=1;return dict(IDENTITY,birth=100.0 if n[0]==1 else 101.0)
        result=l.close_owned(proc,IDENTITY,inspect)
        self.assertEqual(proc.signals,['TERM']);self.assertEqual(result['error'],'identity')
    def test_natural_exit_not_matched_or_inspected(self):
        proc=Process();proc.code=0
        def inspect(_):raise AssertionError('must not inspect reused PID')
        result=l.close_owned(proc,IDENTITY,inspect)
        self.assertFalse(result['identity_matched']);self.assertEqual(result['error'],'unexpected_exit')
    def test_inspection_failure_no_followup_signal(self):
        proc=Process()
        def inspect(_):raise RuntimeError('SECRET')
        result=l.close_owned(proc,IDENTITY,inspect)
        self.assertEqual(proc.signals,[]);self.assertEqual(result['error'],'cleanup')
    def test_wait_failure_no_followup_signal(self):
        proc=Process();proc.wait_error=True
        result=l.close_owned(proc,IDENTITY,lambda _:IDENTITY)
        self.assertEqual(proc.signals,['TERM']);self.assertEqual(result['error'],'cleanup')


MUTATIONS={
 'extra_raw':lambda x:x.update(raw='SECRET'),
 'bool_http':lambda x:x.update(http_calls=True),
 'two_http':lambda x:x.update(http_calls=2),
 'bool_seconds':lambda x:x.update(seconds=True),
 'nan_seconds':lambda x:x.update(seconds=float('nan')),
 'missing_checkpoint':lambda x:x['checkpoints'].pop(),
 'out_of_order':lambda x:x['checkpoints'].reverse(),
 'dirty_ack':lambda x:x['checkpoints'][0]['state'].update(other_denials=1,last_error='network_boundary'),
 'dirty_child':lambda x:x['child']['state'].update(other_denials=1,last_error='signal_boundary'),
 'child_raw':lambda x:x['child'].update(raw='SECRET'),
 'child_fail':lambda x:x['child'].update(candidate='FAIL'),
 'child_natural':lambda x:x['child'].update(commanded_exit=False),
 'bool_child_exit':lambda x:x['child'].update(exit_code=False),
 'cleanup_bool_exit':lambda x:x['cleanup'].update(exit_code=False),
 'cleanup_not_matched':lambda x:x['cleanup'].update(identity_matched=False),
 'cleanup_error':lambda x:x['cleanup'].update(error='cleanup'),
 'source_end':lambda x:x.update(source_end=dict(SOURCE,fixture='a'*64)),
 'authority_raw':lambda x:x.update(authority_id='SECRET'),
 'risk_accept':lambda x:x.update(memory_risk='ACCEPTED'),
 'public_pass':lambda x:x.update(public_release='PASS'),
 'limits_widen':lambda x:x.update(limits=[]),
 'error_raw':lambda x:x.update(error='SECRET'),
 'candidate_fail':lambda x:x.update(candidate='FAIL'),
 'child_unknown_exit':lambda x:x['child'].update(exit_code=None),
 'missing_counter_reset':lambda x:x['checkpoints'][0]['state']['file']['missing'].update(cgroup=1),
}
class AnalyzerTests(unittest.TestCase):
    def test_missing_completion_rejected(self):
        obj,row,seal,_=run()
        self.assertIsNone(a.analyze(obj.payload,None,F,R)['evidence'])
    def test_payload_hash_drift_rejected(self):
        obj,row,seal,_=run()
        self.assertIsNone(a.analyze(obj.payload+b' ',seal,F,R)['evidence'])
    def test_duplicate_json_key_rejected(self):
        obj,row,seal,_=run(); data=obj.payload.replace(b'"schema":',b'"schema":"bad","schema":',1)
        seal['payload_sha256']=hashlib.sha256(data).hexdigest()
        self.assertIsNone(a.analyze(data,seal,F,R)['evidence'])
    def test_fail_schema_still_rejects_raw(self):
        obj,row,seal,_=run(IO('http'));row['raw']='SECRET'
        data=json.dumps(row).encode();seal['payload_sha256']=hashlib.sha256(data).hexdigest()
        self.assertIsNone(a.analyze(data,seal,F,R)['evidence'])
    def test_import_analyzer_does_not_import_runner(self):
        self.assertNotIn('runner',a.__dict__)
    def test_completion_budget_equal_300_rejected(self):
        obj,row,seal,_=run();seal['seconds_at_seal']=300.0
        self.assertIsNone(a.analyze(obj.payload,seal,F,R)['evidence'])
for name,mutate in MUTATIONS.items():
    def case(self,mutate=mutate):
        obj,row,seal,_=run();mutate(row)
        data=json.dumps(row,sort_keys=True).encode();seal['payload_sha256']=hashlib.sha256(data).hexdigest()
        result=a.analyze(data,seal,F,R)
        self.assertNotEqual(result['result'],'VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY')
        self.assertNotIn('SECRET',json.dumps(result))
    setattr(AnalyzerTests,'test_reject_'+name,case)


class AuthorityTests(unittest.TestCase):
    def test_valid_model_authority_only(self):
        self.assertTrue(l.authority_valid(AUTH,100.0,F,R))
    def test_no_native_backend_or_cli(self):
        self.assertNotIn('Popen',l.__dict__)
        self.assertNotIn('main',l.__dict__)
AUTH_MUTATIONS={'bool_max':lambda x:x.update(max_runs=True),
 'two_runs':lambda x:x.update(max_runs=2),'expired':lambda x:x.update(expires=100.0),
 'future':lambda x:x.update(issued=101.0),'too_long':lambda x:x.update(expires=4000.0),
 'no_confirm':lambda x:x.update(owner_confirmed=False),'old_scope':lambda x:x.update(scope='old'),
 'freeze':lambda x:x.update(freeze_sha256='0'*64),'review':lambda x:x.update(review_sha256='0'*64),
 'extra':lambda x:x.update(extra='SECRET'),'schema':lambda x:x.update(schema='old'),
 'id':lambda x:x.update(id='BAD'),'bool_time':lambda x:x.update(issued=True)}
for name,mutate in AUTH_MUTATIONS.items():
    def case(self,mutate=mutate):
        x=copy.deepcopy(AUTH);mutate(x)
        obj,row,seal,_=run(authority=x)
        self.assertEqual(row['error'],'authority');self.assertNotIn('claim',obj.calls)
        self.assertNotIn('spawn',obj.calls)
    setattr(AuthorityTests,'test_reject_'+name,case)


if __name__=='__main__':
    sys.addaudithook(audit)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(previous),
                             unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'inputs':INPUTS,'attempts_after_preload':ATTEMPTS,
          'python_version':sys.version,'executable':sys.executable,
          'scope':'IN_MEMORY_IO_GUARD_LIFECYCLE_NOT_NATIVE',
          'preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(ATTEMPTS.values()) else 1)
