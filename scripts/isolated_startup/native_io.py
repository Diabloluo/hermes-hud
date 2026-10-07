"""Remote-only fixed transport. Import is inert; constructor is still not authority."""
import asyncio
import copy
import fcntl
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

from common import atomic,atomic_bytes,bounded,read,require,digest
import fixture
import identity_contract as identity
import identity_diagnostics as diagnostics
import resource_diagnostics
from lifecycle import identity_valid,transport_valid,child_valid,GRANT,HEX
from source_contract import capture,manifest_valid

HERE=Path(__file__).resolve().parent
COUNTS={'sessions':5000,'messages':200000,'usage_rows':4900,'active_sessions':20,
        'ended_sessions':4980,'tool_messages':2000,'skill_records':1000}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        require(False,'http')


def port_valid(port):
    return type(port) is int and 1024<=port<=65535 and port!=9119


def site_root():
    spec=importlib.util.find_spec('hermes_constants')
    require(spec is not None and spec.origin is not None,'source')
    site=Path(spec.origin).resolve().parent
    require(site.is_relative_to(Path(sys.prefix).resolve()),'source')
    return site


def child_environment(home,out,repo,port,grant,freeze,start,token):
    require(port_valid(port),'identity')
    return {'HOME':str(home/'fake-user'),'HERMES_HOME':str(home),
        'HERMES_BUNDLED_SKILLS_DIR':str(home/'bundled-skills'),
        'HERMES_DISABLE_LAZY_INSTALLS':'1','HERMES_GATEWAY_LOCK_DIR':str(home/'.host-locks'),
        'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8','TZ':'UTC',
        'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(home/'tmp'),
        'HERMES_DASHBOARD_SESSION_TOKEN':token,'HUD_SHORT_CHILD':'1','HUD_GRANT':grant,
        'HUD_OUT':str(out),'HUD_REPO':str(repo),'HUD_PORT':str(port),
        'HUD_FREEZE':freeze,'HUD_BEGIN':str(start)}


class NativeIO:
    execution_kind='NATIVE'
    def __init__(self,root,repo,grant,freeze,prepared):
        self.root,self.repo=Path(root),Path(repo)
        require(self.root.name=='hud-short-startup-owned' and self.root.resolve()==self.root
                and self.repo.resolve()==self.repo and type(grant) is str
                and GRANT.fullmatch(grant) is not None and type(freeze) is str
                and HEX.fullmatch(freeze) is not None,'prepared')
        self.home,self.out=self.root/'run/synthetic-home',self.root/'run/evidence'
        self.grant,self.freeze,self._prepared=grant,freeze,prepared
        self.begin=time.monotonic();self.proc=self.saved=self.binding=self.token=None
        self._lock=None;self._calls={'http':0,'ws':0};self._transport={};self.port=None
        self.manifest=None;self.site=None
        self.argv=None
        self._claimed=False;self._spawn_wall=None
        self._first_identity_failure=None
        self._cleanup_seed=None
        self._bound_birth=None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def clock(self):return time.monotonic()
    def wall(self):return time.time()
    def prepared(self,freeze):return freeze==self.freeze and self._prepared(freeze) is True

    def no_active(self):
        # Held from BEFORE claim through final evidence publication. A stale
        # RUN_CLAIM remains consumed even after lock release; no reclaim/retry.
        require(not (self.root/'active.lock').is_symlink(),'active')
        self._lock=(self.root/'active.lock').open('a+b')
        fcntl.flock(self._lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return all(not (self.root/name).exists() and not (self.root/name).is_symlink()
                   for name in ('RUN_CLAIM.json','result.json','completion.json'))

    def release(self):
        if self._lock is not None:self._lock.close();self._lock=None
        self.token=None

    def resources(self):
        def load():
            import psutil
            return psutil
        self._resource_diagnostic = resource_diagnostics.collect(load, self.root)
        return resource_diagnostics.passed(self._resource_diagnostic)

    def resource_diagnostic(self):
        value = getattr(self, '_resource_diagnostic', None)
        return None if value is None else resource_diagnostics.snapshot(value)

    def claim(self,grant):
        require(grant==self.grant,'claim')
        with (self.root/'RUN_CLAIM.json').open('x') as stream:
            json.dump({'id':grant,'state':'CONSUMED_ONCE_NO_RETRY','max_runs':1},stream)
        self._claimed=True

    def initialize(self):
        require(self._claimed is True,'claim')
        require(importlib.metadata.version('hermes-agent')=='0.19.0'
                and importlib.metadata.version('psutil')=='7.2.2'
                and importlib.metadata.version('websockets')=='15.0.1','prepared')
        self.binding=identity.bind_parent(self.root)
        self.site=site_root()
        self.manifest=read(HERE/'SOURCE_MANIFEST.json')
        require(manifest_valid(self.manifest),'source')
        (self.root/'run').mkdir()
        self.out.mkdir()
        metadata=fixture.build(self.home,self.repo,time.time(),COUNTS)
        require(metadata['counts']==COUNTS and metadata['query_only'] is True,'source')
        atomic(self.out/'fixture.json',metadata)
        # Reserve one random non-production port. Binding race is not retried.
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as lane:
            lane.bind(('127.0.0.1',0));self.port=lane.getsockname()[1]
        require(port_valid(self.port),'identity')
        self.token=secrets.token_urlsafe(32)  # RAM/env only, not a saved real credential.
        self.argv=[sys.executable,'-I','-B',str(HERE/'observer_smoke.py'),'dashboard',
                   '--host','127.0.0.1','--port',str(self.port),'--no-open','--skip-build']
        atomic(self.out/'source-start.json',self.sources())

    def sources(self):return capture(self.manifest,self.repo,self.site,self.home)

    def spawn(self):
        require(self._claimed is True and self.proc is None and self.binding is not None
                and self.argv[0]==self.binding['launcher'],'identity')
        require(identity.revalidate_binding(self.binding,self.root) is True,'identity')
        spec=identity.direct_launch(self.argv,self.home,self.binding,self.root)
        env=child_environment(self.home,self.out,self.repo,self.port,self.grant,
                              self.freeze,self.begin,self.token)
        env['__PYVENV_LAUNCHER__']=spec['venv_launcher']
        require(0<=time.monotonic()-self.begin<280,'budget')
        self._spawn_wall=time.time()
        self.proc=subprocess.Popen(spec['argv'],executable=spec['executable'],cwd=self.home,
            env=env,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return self.proc

    def inspect(self,proc):return identity.inspect(proc)

    def _identity_note(self,site,saved=None,actual=None,code=None,inspection_error=None,birth=None):
        if self._first_identity_failure is None:
            self._first_identity_failure=diagnostics.project(site,saved,actual,code,inspection_error,birth)

    def identity_diagnostic(self):
        return diagnostics.snapshot(self._first_identity_failure)

    def expected(self,proc):
        # Birth captured once; argv0/exe authority comes from the trusted parent.
        site='initial_poll';code=None;actual=None;birth=None
        try:
            require(self.saved is None,'identity')
            code=proc.poll();require(code is None,'identity')
            site='initial_inspect';actual=self.inspect(proc)
            site='initial_schema';require(identity_valid(actual),'identity')
            site='initial_birth';birth=self._spawn_wall-1<=actual['birth']<=time.time()+1
            require(birth,'identity')
            site='initial_expected'
            self.saved=identity.expected(self.argv,self.home,proc.pid,actual['birth'],self.binding)
            # Only PID/birth are observed from the original handle. Command,
            # image and cwd remain entirely prebound; no unknown image adoption.
            if actual['pid']==proc.pid:
                self._bound_birth=actual['birth']
                self._cleanup_seed=copy.deepcopy(self.saved)
            site='initial_match';require(identity.matches(self.saved,actual),'identity')
        except BaseException as error:
            classification=identity.exception_code(error) if site=='initial_inspect' else None
            self._identity_note(site,self.saved,actual,code,classification,birth)
            raise
        atomic(self.out/'identity.json',self.saved)
        return self.saved

    def cleanup_expected(self,proc):
        # A failed expected() may not return to lifecycle. Recover only this
        # original handle's independently reconstructed prebound identity.
        seed=self._cleanup_seed
        if (proc is not self.proc or not identity.valid(seed)
                or seed['pid']!=proc.pid or self.binding is None
                or type(self._bound_birth) is not float or self._bound_birth<=0):
            return None
        bound=identity.expected(self.argv,self.home,proc.pid,self._bound_birth,self.binding)
        return copy.deepcopy(seed) if identity.matches(seed,bound) else None

    def check(self,proc,expected):
        import psutil
        require(time.monotonic()-self.begin<280,'budget')
        site='loop_poll';code=None;actual=None
        try:
            code=proc.poll();require(code is None,'identity')
            site='loop_inspect';actual=self.inspect(proc)
            site='loop_match';require(identity.matches(expected,actual),'identity')
        except BaseException as error:
            classification=identity.exception_code(error) if site=='loop_inspect' else None
            self._identity_note(site,expected,actual,code,classification)
            raise
        require(not (self.out/'observer-failure.json').exists(),'boundary')
        require(psutil.virtual_memory().available>=512*1024**2
                and psutil.disk_usage(self.out).free>=1024**3
                and psutil.Process(proc.pid).memory_info().rss<2500*1024**2,'resource')

    def ready(self,proc,expected):
        require(port_valid(self.port),'identity')
        until=min(time.monotonic()+120,self.begin+280)
        while time.monotonic()<until:
            self.check(proc,expected)
            if (self.out/'ready.json').exists():
                try:
                    with socket.create_connection(('127.0.0.1',self.port),timeout=.2):pass
                    return
                except (OSError,TimeoutError):pass  # readiness observation, not HTTP/WS retry.
            time.sleep(.05)
        require(False,'ready')

    def acknowledge(self,label):
        if label=='ready':return read(self.out/'ready.json')
        sequence={'http':1,'ws':2,'finish':3}.get(label)
        require(sequence is not None,'boundary')
        atomic(self.out/'control.json',{'id':self.grant,'label':label,'sequence':sequence})
        until=min(time.monotonic()+10,self.begin+280)
        while time.monotonic()<until:
            self.check(self.proc,self.saved)
            if (self.out/'ack.json').exists():
                ack=read(self.out/'ack.json')
                require(type(ack) is dict and set(ack)=={'id','sequence','ack'},'boundary')
                if ack['id']==self.grant and type(ack['sequence']) is int and ack['sequence']==sequence:
                    return ack['ack']
            time.sleep(.05)
        require(False,'boundary')

    def http_once(self):
        require(self._calls['http']==0 and port_valid(self.port),'http')
        self._calls['http']=1
        # One authenticated plugin API request, not a frontend HTML/token scrape.
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/plugins/hermes-hud/settings',
                         headers={'X-Hermes-Session-Token':self.token})
        raw=None
        try:
            with self.opener.open(request,timeout=10) as response:
                raw=response.read(1048577)
                require(type(response.status) is int and response.status==200 and 0<len(raw)<=1048576,'http')
                value=json.loads(raw)
                require(type(value) is dict and type(value.get('api_schema_version')) is int
                        and value['api_schema_version']==1,'http')
                self._transport.update(http_status=response.status,http_bytes=len(raw),http_schema=1)
        finally:raw=None

    async def _ws(self,connect):
        require(self._calls['ws']==0 and port_valid(self.port),'ws')
        self._calls['ws']=1
        raw=None
        try:
            url=f'ws://127.0.0.1:{self.port}/api/plugins/hermes-hud/events?locale=en&token={self.token}'
            async with connect(url,origin=f'http://127.0.0.1:{self.port}',proxy=None,
                               open_timeout=10,close_timeout=2,max_size=1048576) as lane:
                raw=await asyncio.wait_for(lane.recv(),10)
                require(type(raw) in (str,bytes),'ws')
                size=len(raw.encode() if type(raw) is str else raw)
                require(0<size<=1048576,'ws')
                value=json.loads(raw)
                require(type(value) is dict and type(value.get('schema_version')) is int
                        and value['schema_version']==1,'ws')
                self._transport.update(ws_frames=1,ws_bytes=size,ws_schema=1,handshakes=1)
        finally:raw=None

    def ws_once(self):
        from websockets.asyncio.client import connect
        asyncio.run(self._ws(connect))

    def transport(self):
        row=dict(self._transport,port=self.port)
        require(transport_valid(row),'ws')
        return row

    def request_finish(self):atomic(self.out/'finish-request.json',{'id':self.grant,'commanded_exit':True})

    def child_terminal(self):
        row=read(self.out/'child-terminal.json')
        require(child_valid(row),'finish')
        return row

    def publish_payload(self,data):atomic_bytes(self.root/'result.json',data)
    def read_payload(self):return bounded(self.root/'result.json',65536)
    def publish_completion(self,value):atomic(self.root/'completion.json',value)
