"""Real asyncio loop, synthetic connector/transport/IO only; no host, network or psutil."""
import ast
import asyncio
import contextlib
import hashlib
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch
import test_pair as models
import runner
from native_io import NativeIO
from common import require
from boundary_policy import BoundaryRefused
import execution_diagnostics as diagnostic

HERE=Path(__file__).resolve().parent
LEGACY=HERE.parent/'remote-finite-memory-integrated-preparation-20261007'/'native_io.py'
LEGACY_SHA='f4d5c033b722114b6cd601fc7f9c7b1573afcfde7a544daf582db3aa1a79645d'
raw=LEGACY.read_bytes()
if hashlib.sha256(raw).hexdigest()!=LEGACY_SHA:raise ValueError('legacy_binding')
tree=ast.parse(raw)
node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NativeIO')
method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='ws_once')
namespace={'asyncio':asyncio}
exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),
             '<bound-legacy-ws-once>','exec'),namespace)
LEGACY_WS=namespace['ws_once']
# Harness creates exactly one genuine loop before its deny hook. No fake selector/time.
LOOP=None

class Connector:
    def __init__(self,mode='ok'):
        self.mode=mode;self.calls=0;self.entered=0;self.exited=0;self.cancelled=0;self.receives=0
    def connect(self,url,**kwargs):
        self.calls+=1
        if not (kwargs=={'origin':'http://127.0.0.1:12001','proxy':None,
             'open_timeout':10,'close_timeout':2,'max_size':1048576}
             and url.startswith('ws://127.0.0.1:12001/')):raise AssertionError('synthetic_contract')
        if self.mode=='raise':raise RuntimeError('SECRET_SENTINEL')
        return self
    async def __aenter__(self):
        self.entered+=1
        await asyncio.sleep(0)
        return self
    async def __aexit__(self,*_):
        self.exited+=1
    async def recv(self):
        self.receives+=1
        if self.mode in ('hold','timeout'):
            try:await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled+=1
                raise
        await asyncio.sleep(0)
        if self.mode=='wrong':return '{"schema_version":false}'
        if self.mode=='invalid':return 'SECRET_SENTINEL'
        if self.mode=='oversize':return 'x'*1048577
        return '{"schema_version":1}'
    def module(self):return types.SimpleNamespace(connect=self.connect)

def transport_io():
    value=NativeIO.__new__(NativeIO)  # Never calls native constructor/authority/Popen.
    value._calls={'http':0,'ws':0};value.port=12001
    value.token='SYNTHETIC_NON_CREDENTIAL';value._transport={}
    return value

class RealLoopTransportTests(unittest.TestCase):
    def drive(self,coro,connector):
        self.assertIsNotNone(LOOP)
        with patch.dict('sys.modules',{'websockets.asyncio.client':connector.module()}):
            return LOOP.run_until_complete(coro)
    def assert_quiet(self):
        self.assertEqual(asyncio.all_tasks(LOOP),set())
    def test_bound_legacy_nested_run_rejected(self):
        connector=Connector();value=transport_io();created=[];real_run=asyncio.run
        def capture(coro,*args,**kwargs):
            created.append(coro)
            return real_run(coro,*args,**kwargs)  # Actual stdlib running-loop refusal.
        async def invoke():
            self.assertIs(asyncio.get_running_loop(),LOOP)
            with patch.object(asyncio,'run',capture):
                with self.assertRaises(RuntimeError):LEGACY_WS(value)
            for coro in created:coro.close()  # No unawaited warning or raw error text.
        self.drive(invoke(),connector)
        self.assertEqual(len(created),1);self.assertEqual(connector.calls,0)
        self.assertEqual(value._calls['ws'],0);self.assert_quiet()
    def test_new_await_one_transport(self):
        connector=Connector();value=transport_io()
        self.drive(value.ws_once_async(),connector)
        self.assertEqual(value._calls['ws'],1);self.assertEqual(connector.receives,1)
        self.assertEqual(connector.exited,1);self.assertEqual(value._transport['handshakes'],1)
        self.assert_quiet()
    def test_second_call_refused_without_retry(self):
        connector=Connector();value=transport_io()
        self.drive(value.ws_once_async(),connector)
        with self.assertRaises(BoundaryRefused):self.drive(value.ws_once_async(),connector)
        self.assertEqual(connector.calls,1);self.assert_quiet()
    def test_connector_exception_not_retried(self):
        connector=Connector('raise');value=transport_io()
        with self.assertRaises(RuntimeError):self.drive(value.ws_once_async(),connector)
        self.assertEqual(connector.calls,1);self.assertEqual(value._calls['ws'],1)
        self.assertEqual(value._transport,{});self.assert_quiet()
    def test_invalid_json(self):
        connector=Connector('invalid');value=transport_io()
        with self.assertRaises(ValueError):self.drive(value.ws_once_async(),connector)
        self.assertEqual(connector.exited,1);self.assert_quiet()
    def test_wrong_schema(self):
        connector=Connector('wrong');value=transport_io()
        with self.assertRaises(BoundaryRefused):self.drive(value.ws_once_async(),connector)
        self.assertEqual(value._transport,{});self.assert_quiet()
    def test_oversize(self):
        connector=Connector('oversize');value=transport_io()
        with self.assertRaises(BoundaryRefused):self.drive(value.ws_once_async(),connector)
        self.assertEqual(connector.exited,1);self.assert_quiet()
    def test_cancel_closes_context(self):
        connector=Connector('hold');value=transport_io()
        async def invoke():
            task=asyncio.create_task(value.ws_once_async())
            while connector.receives==0:await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.drive(invoke(),connector)
        self.assertEqual(connector.cancelled,1);self.assertEqual(connector.exited,1)
        self.assertEqual(value._transport,{});self.assert_quiet()
    def test_actual_ten_second_timeout(self):
        connector=Connector('timeout');value=transport_io()
        begin=LOOP.time()
        with self.assertRaises(TimeoutError):self.drive(value.ws_once_async(),connector)
        self.assertGreaterEqual(LOOP.time()-begin,10)
        self.assertEqual(connector.cancelled,1);self.assertEqual(connector.exited,1)
        self.assertEqual(value._transport,{});self.assert_quiet()

class RealLoopRunnerTests(unittest.TestCase):
    def execute(self,mode='ok',fault=None,cancel=False):
        template=models.arm('sham');connector=Connector(mode);transport=transport_io()
        ident={'pid':1,'birth':100.,'cwd':'/synthetic/home','argv':['/synthetic/python'],'exe':'/synthetic/python'}
        class Process:
            pid=1
            def __init__(self):self.code=None;self.signals=[]
            def poll(self):return self.code
            def terminate(self):self.signals.append('TERM')
            def kill(self):self.signals.append('KILL')
            def wait(self,timeout):self.code=0;return 0
        proc=Process()
        class IO:
            arm='sham';grant='a'*32;out=Path('/synthetic/evidence');home=Path('/synthetic/home')
            def __init__(self):self.proc=None;self.saved=None;self.ticks=0;self.calls=[]
            def clock(self):self.ticks+=1;return 0 if self.ticks==1 else 2400
            def authorized(self):return True
            def no_active(self):return True
            def resources(self):return True
            def resource_diagnostic(self):return models.resource()
            def claim(self,_):self.calls.append('claim')
            def initialize(self):return None
            def sources(self):return models.source()
            def spawn(self):self.calls.append('spawn');self.proc=proc;return proc
            def expected(self,_):self.saved=ident;return ident
            def check(self,*_):return None
            def ready(self,*_):return None
            def acknowledge(self,label):self.calls.append('ack_'+label)
            def http_once(self):
                self.calls.append('http')
                if fault=='http':raise ValueError('SECRET_SENTINEL')
            async def ws_once_async(self):
                self.calls.append('ws')
                await transport.ws_once_async()
            def transport(self):return template['smoke']
            def request_finish(self):self.calls.append('finish_request')
            def inspect(self,_):
                if fault=='cleanup':return dict(ident,birth=101.)
                return ident
            def identity_diagnostic(self):return None
            def child_terminal(self):return template['child']
            def release(self):
                self.calls.append('release')
                if fault=='release':raise RuntimeError('SECRET_SENTINEL')
        value=IO()
        async def phase_model(_,label,seconds,load):
            await asyncio.sleep(0)  # Genuine suspension, cooperative payload/clock.
            if fault=='phase':raise BoundaryRefused('phase')
            return next(x for x in template['phases'] if x['label']==label)
        async def operation_model(_,label,seq):
            await asyncio.sleep(0)
            return template['operations'][seq-1]
        async def invoke():
            task=asyncio.create_task(runner.run_arm(value))
            if cancel:
                while connector.receives==0:await asyncio.sleep(0)
                task.cancel()
            return await task
        with patch.dict('sys.modules',{'websockets.asyncio.client':connector.module()}),\
             patch.object(runner,'phase',phase_model),patch.object(runner,'operation',operation_model),\
             patch.object(runner,'read',return_value=models.fixture()),patch.object(runner,'atomic'),\
             patch.object(runner,'rows',return_value=template['samples']),\
             patch.object(runner.fixture,'counts',return_value=models.a.COUNTS.copy()):
            result=LOOP.run_until_complete(invoke())
        self.assertEqual(asyncio.all_tasks(LOOP),set())
        self.assertNotIn('SECRET_SENTINEL',json.dumps(result))
        self.assertIn('release',value.calls)
        return result,value,proc,connector
    def test_actual_run_arm_real_loop_synthetic_success(self):
        r,io,p,c=self.execute()
        self.assertEqual(r['candidate'],'PASS');self.assertIsNone(r['failure_diagnostic'])
        self.assertEqual(c.calls,1);self.assertEqual(len(r['operations']),5)
        self.assertEqual(p.signals,['TERM']);self.assertEqual(io.calls.count('ws'),1)
    def test_ws_runtime_failure_stage(self):
        r,io,p,c=self.execute('raise')
        self.assertEqual(r['error'],'internal')
        self.assertEqual(r['failure_diagnostic'],diagnostic.project('ws_smoke',RuntimeError()))
        self.assertEqual(r['phases'],[]);self.assertEqual(c.calls,1);self.assertEqual(p.signals,['TERM'])
    def test_http_first_cause(self):
        r,io,p,c=self.execute(fault='http')
        self.assertEqual(r['failure_diagnostic'],diagnostic.project('http_smoke',ValueError()))
        self.assertNotIn('ws',io.calls);self.assertEqual(c.calls,0)
    def test_cancel_stops_before_phases(self):
        r,io,p,c=self.execute('hold',cancel=True)
        self.assertEqual(r['candidate'],'FAIL')
        self.assertEqual(r['failure_diagnostic'],diagnostic.project('ws_smoke',asyncio.CancelledError()))
        self.assertEqual(c.exited,1);self.assertEqual(r['phases'],[])
    def test_phase_failure_label(self):
        r,io,p,c=self.execute(fault='phase')
        self.assertEqual(r['failure_diagnostic'],diagnostic.project('phase',BoundaryRefused('phase')))
        self.assertEqual(len(r['phases']),0);self.assertEqual(c.calls,1)
    def test_cleanup_does_not_overwrite_first_cause(self):
        r,io,p,c=self.execute('raise',fault='cleanup')
        self.assertEqual(r['failure_diagnostic'],diagnostic.project('ws_smoke',RuntimeError()))
        self.assertEqual(r['cleanup']['error'],'identity');self.assertEqual(p.signals,[])
    def test_release_does_not_allow_pass(self):
        r,io,p,c=self.execute(fault='release')
        self.assertEqual(r['candidate'],'FAIL')
        self.assertEqual(r['failure_diagnostic'],diagnostic.project('release',RuntimeError()))
