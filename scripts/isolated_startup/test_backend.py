"""Offline real-function tests with modeled OS/transport. Never boots a host."""
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch,MagicMock

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import test_integration as regression
import lifecycle as l
import analyze_integration as a
import native_io as n
import source_contract as s
import entry as e
import controller as c
import observer_smoke as o

# All dependencies and exact source reads precede the audit hook. No ctypes
# attestation: hook attempt counts alone are not proof of complete containment.
SOURCES={name:(HERE/name).read_bytes() for name in
 ('common.py','fixture.py','identity_contract.py','source_contract.py','native_io.py',
  'observer_smoke.py','entry.py','controller.py','test_backend.py','SOURCE_MANIFEST.json','DRAFT_WORKFLOW.yml','PROTOCOL.json')}
MANIFEST=json.loads(SOURCES['SOURCE_MANIFEST.json'])
INPUTS={name:hashlib.sha256(data).hexdigest() for name,data in SOURCES.items()}
INPUTS.update(regression.INPUTS)
ATTEMPTS={'open':0,'process':0,'network':0,'sqlite':0,'signal':0}
ROOT=Path('/MODEL/hud-short-startup-owned');REPO=Path('/MODEL/repo')
SOURCE=regression.SOURCE;F=regression.F;R=regression.R;AUTH=regression.AUTH


def audit(event,args):
    kind=('open' if event=='open' else 'process' if event.startswith('subprocess.')
          or event in {'os.system','os.exec','os.fork','os.posix_spawn'} else
          'network' if event.startswith('socket.') else 'sqlite' if event.startswith('sqlite3.')
          else 'signal' if event in {'os.kill','os.killpg'} else None)
    if kind:
        ATTEMPTS[kind]+=1;raise RuntimeError('OFFLINE_ONLY')


def native():
    with patch.object(n.Path,'resolve',lambda x:x):
        obj=n.NativeIO(ROOT,REPO,'e'*32,F,lambda x:True)
    obj.port=50123;obj.token='SYNTHETIC_SECRET';obj._claimed=True
    obj._spawn_wall=100.0
    obj.argv=[str(ROOT/'venv/bin/python'),'-I','-B',str(HERE/'observer_smoke.py'),'dashboard',
              '--host','127.0.0.1','--port','50123','--no-open','--skip-build']
    obj.binding={'schema':'hud_remote_interpreter_v3','launcher':obj.argv[0],
                 'prefix':str(ROOT/'venv'),'argv0':'/MODEL/python','exe':'/MODEL/python',
                 'launcher_sha256':'1'*64,'exe_sha256':'2'*64}
    return obj


class Response:
    def __init__(self,data=b'{"api_schema_version":1}',status=200):self.data,self.status=data,status
    def read(self,limit):return self.data[:limit]
    def __enter__(self):return self
    def __exit__(self,*args):pass


class Lane:
    def __init__(self,data='{"schema_version":1}'):self.data=data
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def recv(self):return self.data


async def immediate(awaitable,timeout):return await awaitable
def drive(coroutine):
    # Cooperative immediate awaits, NOT a real event loop/socketpair/OS pipe.
    try:coroutine.send(None)
    except StopIteration as stopped:return stopped.value
    raise AssertionError('unexpected suspension')


class TransportTests(unittest.TestCase):
    def test_http_once_native_function_fixed_url_header_and_bound(self):
        obj=native();opener=MagicMock();opener.open.return_value=Response();obj.opener=opener
        obj.http_once()
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'http://127.0.0.1:50123/api/plugins/hermes-hud/settings')
        self.assertIn('SYNTHETIC_SECRET',request.headers.values())
        self.assertEqual(opener.open.call_args.kwargs,{'timeout':10})
        self.assertEqual(obj._transport,{'http_status':200,'http_bytes':24,'http_schema':1})
        self.assertRaises(l.BoundaryRefused,obj.http_once)
        self.assertEqual(opener.open.call_count,1)
    def test_http_exception_not_retried(self):
        obj=native();obj.opener=MagicMock();obj.opener.open.side_effect=OSError('SECRET')
        self.assertRaises(OSError,obj.http_once);self.assertRaises(l.BoundaryRefused,obj.http_once)
        self.assertEqual(obj.opener.open.call_count,1)
    def test_production_port_no_http(self):
        obj=native();obj.port=9119;obj.opener=MagicMock()
        self.assertRaises(l.BoundaryRefused,obj.http_once);obj.opener.open.assert_not_called()
    def test_redirect_refused(self):
        self.assertRaises(l.BoundaryRefused,n.NoRedirect().redirect_request,None,None,None,None,None)
    def test_ws_fixed_url_origin_no_proxy_one_frame(self):
        obj=native();calls=[]
        def connect(url,**kwargs):calls.append((url,kwargs));return Lane()
        with patch.object(n.asyncio,'wait_for',immediate):drive(obj._ws(connect))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],'ws://127.0.0.1:50123/api/plugins/hermes-hud/events?locale=en&token=SYNTHETIC_SECRET')
        self.assertEqual(calls[0][1],{'origin':'http://127.0.0.1:50123','proxy':None,
            'open_timeout':10,'close_timeout':2,'max_size':1048576})
        self.assertEqual(obj._transport,{'ws_frames':1,'ws_bytes':20,'ws_schema':1,'handshakes':1})
        with patch.object(n.asyncio,'wait_for',immediate):self.assertRaises(l.BoundaryRefused,drive,obj._ws(connect))
        self.assertEqual(len(calls),1)
    def test_ws_production_port_no_connect(self):
        obj=native();obj.port=9119;connect=MagicMock()
        self.assertRaises(l.BoundaryRefused,drive,obj._ws(connect));connect.assert_not_called()
    def test_token_not_in_transport_projection(self):
        obj=native();obj._transport={'http_status':200,'http_bytes':24,'http_schema':1,
            'ws_frames':1,'ws_bytes':20,'ws_schema':1,'handshakes':1}
        self.assertTrue(l.transport_valid(obj.transport()))
        self.assertNotIn('SECRET',json.dumps(obj.transport()))
HTTP_BAD=[('status',Response(status=403)),('bool_status',Response(status=True)),
 ('invalid_json',Response(b'SECRET')),('bool_schema',Response(b'{"api_schema_version":true}')),
 ('wrong_schema',Response(b'{"api_schema_version":2}')),('list',Response(b'[]')),
 ('empty',Response(b'')),('over_limit',Response(b'a'*1048577))]
for name,response in HTTP_BAD:
    def case(self,response=response):
        obj=native();obj.opener=MagicMock();obj.opener.open.return_value=response
        self.assertRaises(Exception,obj.http_once)
        self.assertEqual(obj._calls['http'],1);self.assertEqual(obj._transport,{})
    setattr(TransportTests,'test_http_reject_'+name,case)
WS_BAD=[('list','[]'),('empty',''),('invalid_json','SECRET'),('wrong_schema','{"schema_version":2}'),
        ('bool_schema','{"schema_version":true}'),('over_limit','a'*1048577),('object',{'raw':'SECRET'})]
for name,value in WS_BAD:
    def case(self,value=value):
        obj=native();connect=lambda *args,**kwargs:Lane(value)
        with patch.object(n.asyncio,'wait_for',immediate):self.assertRaises(Exception,drive,obj._ws(connect))
        self.assertEqual(obj._calls['ws'],1);self.assertEqual(obj._transport,{})
    setattr(TransportTests,'test_ws_reject_'+name,case)


class IdentityTests(unittest.TestCase):
    def actual(self,obj,**change):
        out={'pid':1234,'birth':100.0,'cwd':str(obj.home),
             'argv':[obj.binding['argv0']]+obj.argv[1:],'exe':obj.binding['exe']}
        out.update(change);return out
    def test_parent_binding_not_child_adoption(self):
        obj=native();proc=regression.Process()
        obj.inspect=lambda _:self.actual(obj)
        with patch.object(n,'atomic'),patch.object(n.time,'time',lambda:100.5):saved=obj.expected(proc)
        self.assertEqual(saved['exe'],obj.binding['exe']);self.assertEqual(saved['argv'][0],obj.binding['argv0'])
        self.assertRaises(l.BoundaryRefused,obj.expected,proc)
    def test_mismatched_command_not_adopted(self):
        obj=native();proc=regression.Process();obj.inspect=lambda _:self.actual(obj,argv=['/EVIL'])
        with patch.object(n,'atomic'),patch.object(n.time,'time',lambda:100.5):
            self.assertRaises(l.BoundaryRefused,obj.expected,proc)
    def test_birth_outside_spawn_window_refused(self):
        obj=native();proc=regression.Process();obj.inspect=lambda _:self.actual(obj,birth=99-1.0)
        with patch.object(n,'atomic'),patch.object(n.time,'time',lambda:100.5):
            self.assertRaises(l.BoundaryRefused,obj.expected,proc)
    def test_already_exited_no_inspection(self):
        obj=native();proc=regression.Process();proc.code=2;obj.inspect=MagicMock()
        self.assertRaises(l.BoundaryRefused,obj.expected,proc);obj.inspect.assert_not_called()
    def test_one_popen_and_explicit_env(self):
        obj=native();proc=regression.Process()
        with patch.object(n.identity,'revalidate_binding',return_value=True),\
             patch.object(n.subprocess,'Popen',return_value=proc) as popen:
            self.assertIs(obj.spawn(),proc)
            self.assertRaises(l.BoundaryRefused,obj.spawn)
        self.assertEqual(popen.call_count,1)
        env=popen.call_args.kwargs['env']
        self.assertNotIn('OPENAI_API_KEY',env);self.assertNotIn('GITHUB_TOKEN',env)
        self.assertEqual(env['HERMES_DASHBOARD_SESSION_TOKEN'],'SYNTHETIC_SECRET')
        self.assertEqual(popen.call_args.kwargs['cwd'],obj.home)
    def test_unclaimed_spawn_no_popen(self):
        obj=native();obj._claimed=False
        with patch.object(n.subprocess,'Popen') as popen:
            self.assertRaises(l.BoundaryRefused,obj.spawn);popen.assert_not_called()
    def test_unknown_initialize_no_fixture(self):
        obj=native();obj._claimed=False
        with patch.object(n.fixture,'build') as build:
            self.assertRaises(l.BoundaryRefused,obj.initialize);build.assert_not_called()


class SourceTests(unittest.TestCase):
    def test_exact_frozen_manifest_structure(self):
        self.assertTrue(s.manifest_valid(MANIFEST))
    def test_source_vector_real_function_with_fake_bytes(self):
        m=copy.deepcopy(MANIFEST);data=b'synthetic public module'
        for group in ('candidate','public'):
            for row in m[group]:row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        with patch.object(s,'bounded',lambda *args,**kwargs:data),patch.object(s.Path,'resolve',lambda p:p):
            result=s.capture(m,REPO,Path('/MODEL/site'),ROOT/'home')
        self.assertTrue(l.sources_valid(result))
        seed=[{'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name in s.FIXTURE_FILES]
        self.assertEqual(result['fixture'],hashlib.sha256(json.dumps(seed,sort_keys=True).encode()).hexdigest())
    def test_source_drift_no_silent_fallback(self):
        with patch.object(s,'bounded',lambda *args,**kwargs:b'drift'):
            self.assertRaises(l.BoundaryRefused,s.group_hash,MANIFEST['public'],Path('/MODEL/site'))
    def test_no_recursive_scan_in_source_contract(self):
        tree=ast.parse(SOURCES['source_contract.py'])
        calls={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
        self.assertFalse({'rglob','glob','walk','iterdir'} & calls)
SOURCE_BAD={'dup':lambda x:x['candidate'].__setitem__(1,copy.deepcopy(x['candidate'][0])),
 'absolute':lambda x:x['public'][0].update(name='/Users/SECRET'),
 'parent':lambda x:x['candidate'][0].update(name='../SECRET'),
 'bool_size':lambda x:x['public'][0].update(bytes=True),'hash':lambda x:x['public'][0].update(sha256='SECRET'),
 'missing':lambda x:x['public'].pop(),'extra':lambda x:x.update(raw='SECRET'),
 'public_unknown':lambda x:x['public'][0].update(name='SECRET.py'),
 'candidate_unknown':lambda x:x['candidate'][0].update(name='outside.py'),
 'version':lambda x:x.update(public_version='latest')}
for name,mutate in SOURCE_BAD.items():
    def case(self,mutate=mutate):m=copy.deepcopy(MANIFEST);mutate(m);self.assertFalse(s.manifest_valid(m))
    setattr(SourceTests,'test_reject_'+name,case)


class WorkflowTests(unittest.TestCase):
    def environment(self):
        return {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'Diabloluo/hermes-hud',
         'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
         'GITHUB_REF':'refs/heads/test/v2-isolated-memory-20261003','GITHUB_SHA':'a'*40}
    def test_context_authority_real_function(self):
        self.assertIsNone(e.workflow_authority(self.environment(),'a'*40,'e'*32,90.,1000.,R,100.))
    def test_runtime_gates_not_assert(self):
        for name in ('entry.py','controller.py','native_io.py','observer_smoke.py'):
            self.assertFalse(any(isinstance(n,ast.Assert) for n in ast.walk(ast.parse(SOURCES[name]))))
    def test_fixed_workflow_readonly_no_replay(self):
        text=SOURCES['DRAFT_WORKFLOW.yml'].decode()
        self.assertIn('github.run_attempt == 1',text);self.assertIn('github.sha == inputs.reviewed_sha',text)
        self.assertIn('contents: read',text);self.assertIn('persist-credentials: false',text)
        self.assertNotIn('secrets.',text);self.assertNotIn('schedule:',text);self.assertNotIn('pull_request:',text)
        self.assertIn('timeout-minutes: 30',text);self.assertIn('timeout-minutes: 5',text)
    def test_controller_no_assert_and_one_post_site(self):
        tree=ast.parse(SOURCES['controller.py'])
        posts=[n for n in ast.walk(tree) if isinstance(n,ast.Constant) and n.value=='POST']
        self.assertEqual(len(posts),1)
ENV_BAD={'main':('GITHUB_REF','refs/heads/main'),'replay':('GITHUB_RUN_ATTEMPT','2'),
 'event':('GITHUB_EVENT_NAME','push'),'repo':('GITHUB_REPOSITORY','foreign/repo'),
 'sha':('GITHUB_SHA','b'*40),'not_ci':('GITHUB_ACTIONS','false')}
for name,(key,value) in ENV_BAD.items():
    def case(self,key=key,value=value):
        env=self.environment();env[key]=value
        self.assertRaises(l.BoundaryRefused,e.workflow_authority,env,'a'*40,'e'*32,90.,1000.,R,100.)
    setattr(WorkflowTests,'test_refuse_'+name,case)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.authority=dict(AUTH,sha='a'*40,repository='Diabloluo/hermes-hud',branch='test/v2-isolated-memory-20261003')
        self.acceptance={'schema':'hud_short_review_acceptance_v1','sha':'a'*40,'freeze_sha256':F,
                         'report_sha256':R,'safety':'PASS','scope':l.SCOPE}
    def context(self,run,claimed):
        def read(path):return self.authority if path.name=='AUTHORIZATION.json' else self.acceptance
        def digest(path):return F if path.name=='FREEZE.json' else R
        def opened(path,*args,**kwargs):claimed.append(path.name);return io.StringIO()
        return [patch.object(c,'read',read),patch.object(c,'digest',digest),patch.object(c.time,'time',lambda:100.),
                patch.object(c.subprocess,'run',run),patch.object(c.Path,'open',opened),patch.object(c,'atomic')]
    def test_ack_one_post_after_claim(self):
        events=[];claimed=[]
        def run(argv,**kwargs):
            if 'POST' in argv:
                self.assertEqual(claimed,['DISPATCH_CLAIM.json']);events.append('post')
                payload=json.loads(kwargs['input']);self.assertEqual(payload['inputs']['reviewed_report'],R)
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(stdout=('a'*40+'\n').encode())
        patches=self.context(run,claimed)
        with patches[0],patches[1],patches[2],patches[3],patches[4],patches[5]:self.assertEqual(c.main(),0)
        self.assertEqual(events,['post'])
    def test_timeout_outcome_unknown_no_retry(self):
        posts=[];claimed=[]
        def run(argv,**kwargs):
            if 'POST' in argv:posts.append(1);raise TimeoutError('SECRET')
            return SimpleNamespace(stdout=('a'*40+'\n').encode())
        patches=self.context(run,claimed)
        with patches[0],patches[1],patches[2],patches[3],patches[4],patches[5] as stored:
            self.assertEqual(c.main(),2)
            self.assertEqual(stored.call_args.args[1]['state'],'OUTCOME_UNKNOWN_NO_RETRY')
            self.assertNotIn('SECRET',json.dumps(stored.call_args.args[1]))
        self.assertEqual(len(posts),1)
    def test_missing_gate_no_network(self):
        with patch.object(c,'read',side_effect=FileNotFoundError()),patch.object(c.subprocess,'run') as run:
            self.assertRaises(FileNotFoundError,c.main);run.assert_not_called()
    def test_replay_claim_prevents_post(self):
        posts=[]
        def run(argv,**kwargs):
            if 'POST' in argv:posts.append(1)
            return SimpleNamespace(stdout=('a'*40+'\n').encode())
        patches=self.context(run,[])
        with patches[0],patches[1],patches[2],patches[3],patch.object(c.Path,'open',side_effect=FileExistsError()),patches[5]:
            self.assertRaises(FileExistsError,c.main)
        self.assertEqual(posts,[])
    def test_branch_movement_no_claim_or_post(self):
        run=lambda *args,**kwargs:SimpleNamespace(stdout=('b'*40+'\n').encode())
        claimed=[];patches=self.context(run,claimed)
        with patches[0],patches[1],patches[2],patches[3],patches[4],patches[5]:
            self.assertRaises(l.BoundaryRefused,c.main)
        self.assertEqual(claimed,[])
    def test_wrong_review_refused(self):
        self.acceptance['report_sha256']='0'*64
        self.assertRaises(l.BoundaryRefused,c.gates,self.authority,self.acceptance,F,R,100.)


class NativeEvidenceTests(unittest.TestCase):
    def value(self):
        obj,row,seal,_=regression.run()
        row['execution_kind']='NATIVE'
        row['transport']={'port':50123,'http_status':200,'http_bytes':24,'http_schema':1,
                         'ws_frames':1,'ws_bytes':20,'ws_schema':1,'handshakes':1}
        payload=l.encode(row);seal['payload_sha256']=hashlib.sha256(payload).hexdigest()
        return row,payload,seal
    def test_native_record_scope_not_risk_acceptance(self):
        row,payload,seal=self.value();result=a.analyze(payload,seal,F,R)
        self.assertEqual(result['result'],'VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY')
        self.assertEqual(result['memory_risk'],'WARN_NOT_ACCEPTED');self.assertEqual(result['public_release'],'BLOCK')
    def test_old_schema_cannot_upgrade(self):
        row,payload,seal=self.value();row['schema']='hud_short_startup_integration_v1'
        payload=l.encode(row);seal['payload_sha256']=hashlib.sha256(payload).hexdigest()
        self.assertIsNone(a.analyze(payload,seal,F,R)['evidence'])
    def test_fail_transport_extra_raw_dropped(self):
        row,payload,seal=self.value();row['candidate']='FAIL';row['transport']['raw']='SECRET'
        payload=l.encode(row);seal['payload_sha256']=hashlib.sha256(payload).hexdigest();seal['verdict']='FAIL'
        self.assertNotIn('SECRET',json.dumps(a.analyze(payload,seal,F,R)))
EVIDENCE_BAD={'port':lambda x:x['transport'].update(port=9119),
 'bool_schema':lambda x:x['transport'].update(ws_schema=True),
 'raw':lambda x:x['transport'].update(raw='SECRET'),'two_handshakes':lambda x:x['transport'].update(handshakes=2),
 'missing_transport':lambda x:x.update(transport=None),'invalid_kind':lambda x:x.update(execution_kind='PUBLIC'),
 'huge_http':lambda x:x['transport'].update(http_bytes=1048577),'extra_frame':lambda x:x['transport'].update(ws_frames=2)}
for name,mutate in EVIDENCE_BAD.items():
    def case(self,mutate=mutate):
        row,payload,seal=self.value();mutate(row);payload=l.encode(row);seal['payload_sha256']=hashlib.sha256(payload).hexdigest()
        self.assertNotEqual(a.analyze(payload,seal,F,R)['result'],'VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY')
    setattr(NativeEvidenceTests,'test_reject_'+name,case)


class ObserverTests(unittest.TestCase):
    def test_missing_authority_no_dependency_import_or_host(self):
        with patch.dict(o.os.environ,{},clear=True):self.assertRaises(l.BoundaryRefused,o.boot)
    def test_no_tracing_vmmap_gc_or_auth_monkeypatch(self):
        tree=ast.parse(SOURCES['observer_smoke.py'])
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        self.assertFalse({'tracemalloc','gc','ctypes','vmmap'}&names)
        self.assertNotIn('_ws_auth_ok',SOURCES['observer_smoke.py'].decode())
    def test_actual_loader_and_separate_stack_install_sites(self):
        tree=ast.parse(SOURCES['observer_smoke.py'])
        attrs=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertEqual(attrs.count('install'),1);self.assertEqual(attrs.count('terminal'),1)
        self.assertIn('acknowledge',attrs)


class NativeControlTests(unittest.TestCase):
    def test_ready_checks_identity_before_tcp(self):
        obj=native();events=[];obj.check=lambda *args:events.append('identity')
        def connect(*args,**kwargs):events.append('tcp');return MagicMock()
        with patch.object(n.time,'monotonic',lambda:0.),patch.object(n.Path,'exists',lambda p:True),\
             patch.object(n.socket,'create_connection',connect):obj.ready(None,None)
        self.assertEqual(events,['identity','tcp'])
    def test_ready_identity_failure_no_socket(self):
        obj=native();obj.check=MagicMock(side_effect=l.BoundaryRefused('identity'))
        with patch.object(n.time,'monotonic',lambda:0.),patch.object(n.socket,'create_connection') as connect:
            self.assertRaises(l.BoundaryRefused,obj.ready,None,None);connect.assert_not_called()
    def test_ready_timeout_no_http_ws(self):
        obj=native();obj.check=MagicMock()
        with patch.object(n.time,'monotonic',side_effect=[0.,121.]),patch.object(n.socket,'create_connection') as connect:
            self.assertRaises(l.BoundaryRefused,obj.ready,None,None);connect.assert_not_called()
        self.assertEqual(obj._calls,{'http':0,'ws':0})
    def test_ack_fixed_command_and_identity_before_read(self):
        obj=native();events=[];obj.check=lambda *args:events.append('identity')
        ack={'id':obj.grant,'sequence':1,'ack':{'label':'http','state':regression.stack().state()}}
        def read(path):events.append('read');return ack
        with patch.object(n,'atomic') as stored,patch.object(n,'read',read),\
             patch.object(n.Path,'exists',lambda p:True),patch.object(n.time,'monotonic',lambda:0.):
            self.assertEqual(obj.acknowledge('http'),ack['ack'])
        self.assertEqual(events,['identity','read'])
        self.assertEqual(stored.call_args.args[1],{'id':obj.grant,'label':'http','sequence':1})
    def test_ack_bool_sequence_cannot_succeed(self):
        obj=native();obj.check=MagicMock()
        ack={'id':obj.grant,'sequence':True,'ack':{}}
        with patch.object(n,'atomic'),patch.object(n,'read',return_value=ack),\
             patch.object(n.Path,'exists',lambda p:True),patch.object(n.time,'sleep'),\
             patch.object(n.time,'monotonic',side_effect=[0.,0.,11.]):
            self.assertRaises(l.BoundaryRefused,obj.acknowledge,'http')
    def test_unknown_ack_label_no_write(self):
        obj=native()
        with patch.object(n,'atomic') as stored:
            self.assertRaises(l.BoundaryRefused,obj.acknowledge,'SECRET');stored.assert_not_called()
    def test_initialize_version_mismatch_consumed_no_fixture(self):
        obj=native()
        with patch.object(n.importlib.metadata,'version',return_value='wrong'),patch.object(n.fixture,'build') as build:
            self.assertRaises(l.BoundaryRefused,obj.initialize);build.assert_not_called()
        self.assertTrue(obj._claimed)
    def test_release_drops_token_and_closes_lock(self):
        obj=native();lock=MagicMock();obj._lock=lock;obj.release()
        lock.close.assert_called_once();self.assertIsNone(obj._lock);self.assertIsNone(obj.token)
    def test_claim_exclusive_before_initialized(self):
        obj=native();obj._claimed=False
        def opened(path,mode):self.assertEqual(mode,'x');return io.StringIO()
        with patch.object(n.Path,'open',opened):obj.claim(obj.grant)
        self.assertTrue(obj._claimed)
        with patch.object(n.Path,'open',side_effect=FileExistsError()):
            self.assertRaises(FileExistsError,obj.claim,obj.grant)
    def test_all_direct_cli_entries_bind_local_imports_under_isolation(self):
        for name in ('controller.py','entry.py','observer_smoke.py'):
            self.assertIn('sys.path.insert(0,str(Path(__file__).resolve().parent))',SOURCES[name].decode())


class EntryTests(unittest.TestCase):
    def args(self):return SimpleNamespace(sha='a'*40,freeze=F,grant='e'*32,review=R,issued=90.,expires=1000.)
    def context(self):
        return [patch.object(e,'remote_gate',return_value=True),patch.dict(e.os.environ,{'RUNNER_TEMP':'/MODEL'}),
                patch.object(e.Path,'resolve',lambda p:p),patch.object(e.Path,'exists',lambda p:False),
                patch.object(e.Path,'is_symlink',lambda p:False),patch.object(e.Path,'mkdir'),
                patch.object(e.Path,'open',lambda *args,**kwargs:io.StringIO()),patch.object(e,'atomic'),
                patch.object(e.venv,'EnvBuilder'),patch.object(e.time,'monotonic',lambda:0.)]
    def test_setup_gate_failure_before_any_install(self):
        with patch.object(e,'remote_gate',side_effect=l.BoundaryRefused('authority')),\
             patch.object(e.venv,'EnvBuilder') as builder,patch.object(e.subprocess,'run') as run:
            self.assertRaises(l.BoundaryRefused,e.setup,self.args());builder.assert_not_called();run.assert_not_called()
    def test_setup_consumes_claim_before_install_and_installs_once(self):
        from contextlib import ExitStack
        events=[];ctx=self.context()
        def opened(path,mode):events.append('claim');self.assertEqual(mode,'x');return io.StringIO()
        ctx[6]=patch.object(e.Path,'open',opened)
        def run(argv,**kwargs):
            events.append('install');self.assertEqual(events,['claim','install'])
            self.assertEqual(argv[-3:],['hermes-agent==0.19.0','psutil==7.2.2','websockets==15.0.1'])
            self.assertNotIn('GITHUB_TOKEN',kwargs['env']);self.assertEqual(kwargs['timeout'],1800.)
        with ExitStack() as stack:
            for p in ctx:stack.enter_context(p)
            called=stack.enter_context(patch.object(e.subprocess,'run',side_effect=run));e.setup(self.args())
            self.assertEqual(called.call_count,1)
    def test_setup_failure_never_retries(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self.context():stack.enter_context(p)
            called=stack.enter_context(patch.object(e.subprocess,'run',side_effect=TimeoutError('SECRET')))
            stored=stack.enter_context(patch.object(e,'atomic'))
            self.assertRaises(SystemExit,e.setup,self.args());self.assertEqual(called.call_count,1)
            self.assertEqual(stored.call_args.args[1],{'result':'FAIL','error':'setup_failed','retry':False})
    def test_run_setup_fail_no_native_constructor(self):
        with patch.object(e,'remote_gate'),patch.dict(e.os.environ,{'RUNNER_TEMP':'/MODEL'}),\
             patch.object(e.Path,'resolve',lambda p:p),patch.object(e,'read',return_value={'result':'FAIL'}),\
             patch.object(e,'NativeIO') as backend:
            self.assertRaises(l.BoundaryRefused,e.run,self.args());backend.assert_not_called()
    def test_run_finally_releases_even_if_core_raises(self):
        args=self.args();records={'setup.json':{'result':'PASS','id':args.grant,'sha':args.sha,'freeze':F,'review':R},
            'SETUP_CLAIM.json':{'id':args.grant,'state':'CONSUMED_ONCE_NO_RETRY','sha':args.sha,'freeze':F,'review':R},
            'authority.json':copy.deepcopy(AUTH)}
        backend=MagicMock()
        with patch.object(e,'remote_gate'),patch.dict(e.os.environ,{'RUNNER_TEMP':'/MODEL'}),\
             patch.object(e.Path,'resolve',lambda p:p),patch.object(e,'read',lambda p:records[p.name]),\
             patch.object(e.time,'time',lambda:100.),patch.object(e,'NativeIO',return_value=backend),\
             patch.object(e,'execute_model_io',side_effect=RuntimeError('SECRET')):
            self.assertRaises(RuntimeError,e.run,args)
        backend.release.assert_called_once()
    def test_native_adapter_through_real_core_and_independent_analysis(self):
        model=regression.IO();model.execution_kind='NATIVE';obj=native();obj.opener=MagicMock()
        obj.opener.open.return_value=Response()
        model.http_once=obj.http_once
        def ws():
            with patch.object(n.asyncio,'wait_for',immediate):drive(obj._ws(lambda *args,**kwargs:Lane()))
        model.ws_once=ws;model.transport=obj.transport
        _,row,seal,analysis=regression.run(model)
        self.assertEqual(row['candidate'],'PASS');self.assertEqual(row['transport'],obj.transport())
        self.assertEqual(analysis['result'],'VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY')
        self.assertEqual(obj._calls,{'http':1,'ws':1});self.assertEqual(seal['verdict'],'PASS')


if __name__=='__main__':
    sys.addaudithook(audit)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(regression.previous),
        unittest.defaultTestLoader.loadTestsFromModule(regression),
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'tests':result.testsRun,'success':result.wasSuccessful(),'inputs':INPUTS,
        'attempts_after_preload':ATTEMPTS,'python_version':sys.version,'executable':sys.executable,
        'scope':'ACTUAL_BACKEND_FUNCTIONS_WITH_MODELED_OS_IO_AND_COOPERATIVE_ASYNC',
        'native_execution':'NOT_RUN','real_event_loop':'NOT_RUN','real_pipes_psutil':'NOT_RUN',
        'preload_not_covered':True},sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() and not any(ATTEMPTS.values()) else 1)
