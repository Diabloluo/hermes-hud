"""Retained-handle native host process backend, inert until explicitly called.

Not an authorization gate, installer-tree controller, or runnable entrypoint.
The caller must bind source/image bytes, consume a fresh claim, stage the child
guard/channel, and enforce the overall deadline BEFORE calling start().
"""
import asyncio
import copy
import math
import re
import signal
import socket
import subprocess
import time
from pathlib import PurePosixPath


class Refused(ValueError):
    def __init__(self,code):super().__init__(code if code in {'plan','consumed','budget','spawn','identity','exit','tree','cleanup'} else 'identity')

def need(value,code):
    if value is not True:raise Refused(code) from None

def finite(value):return type(value) in (float,int) and math.isfinite(value) and 0<=value<2**53
def path(value):return type(value) is str and value.startswith('/') and str(PurePosixPath(value))==value and '..' not in PurePosixPath(value).parts
def identity(row):
    return (type(row) is dict and set(row)=={'pid','birth','cwd','argv','exe'}
        and type(row['pid']) is int and 1<row['pid']<2**31 and finite(row['birth']) and row['birth']>0
        and path(row['cwd']) and path(row['exe']) and type(row['argv']) is list
        and 1<=len(row['argv'])<=32 and all(type(x) is str and 0<len(x)<=4096 and '\0' not in x for x in row['argv']))


class NativeInspector:
    def __init__(self):
        import psutil
        need(psutil.__version__=='7.2.2','identity');self.ps=psutil
    def capture(self,pid,birth=None):
        need(type(pid) is int and 1<pid<2**31 and (birth is None or finite(birth) and birth>0),'identity')
        p=self.ps.Process(pid);seen=p.create_time()
        need(birth is None or seen==birth,'identity')
        row={'pid':pid,'birth':seen,'cwd':p.cwd(),'argv':p.cmdline(),'exe':p.exe()}
        need(self.ps.Process(pid).create_time()==seen and identity(row),'identity');return row
    def children(self,pid,birth):
        p=self.ps.Process(pid);need(p.create_time()==birth,'identity')
        result=p.children(recursive=True)
        need(type(result) is list and len(result)<=128,'tree')
        need(self.ps.Process(pid).create_time()==birth,'identity');return [x.pid for x in result]
    def send(self,expected,signum):
        need(identity(expected) and signum in (signal.SIGTERM,signal.SIGKILL),'identity')
        # Two full observations; psutil's send_signal also checks PID reuse.
        need(self.capture(expected['pid'],expected['birth'])==expected,'identity')
        process=self.ps.Process(expected['pid'])
        need(process.create_time()==expected['birth'],'identity')
        need(self.capture(expected['pid'],expected['birth'])==expected,'identity')
        process.send_signal(signum)
    def listener(self,expected,port):
        need(identity(expected) and type(port) is int and 1024<=port<=65535 and port!=9119,'identity')
        need(self.capture(expected['pid'],expected['birth'])==expected,'identity')
        rows=self.ps.Process(expected['pid']).net_connections(kind='tcp')
        need(type(rows) is list and len(rows)<=256,'identity')
        matches=[r for r in rows if r.status==self.ps.CONN_LISTEN and r.family==socket.AF_INET
                 and r.laddr.ip=='127.0.0.1' and r.laddr.port==port and not r.raddr]
        need(self.capture(expected['pid'],expected['birth'])==expected,'identity')
        return len(matches)==1


class OwnedHost:
    def __init__(self,plan,inspector,*,clock=time.monotonic,wall=time.time,popen=subprocess.Popen,sleep=asyncio.sleep):
        need(type(plan) is dict and set(plan)=={'executable','argv','cwd','env'},'plan')
        need(path(plan['cwd']) and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}',plan['cwd']) is not None,'plan')
        root=plan['cwd']
        need(path(plan['executable']) and plan['executable'].startswith(root+'/home/.hermes/tools/'),'plan')
        need(plan['argv']==[plan['executable'],'-I','-B',root+'/tool/official_entry.py'],'plan')
        env=plan['env']
        need(type(env) is dict and set(env)=={'HOME','HERMES_HOME','TMPDIR','PATH','LANG','LC_CTYPE','TZ',
             'PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE','XDG_CACHE_HOME','UV_CACHE_DIR',
             'HERMES_DISABLE_LAZY_INSTALLS','HERMES_DASHBOARD_SESSION_TOKEN'},'plan')
        expected={'HOME':root+'/home','HERMES_HOME':root+'/home/.hermes','TMPDIR':root+'/tmp',
             'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8','LC_CTYPE':'en_US.UTF-8','TZ':'UTC',
             'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','XDG_CACHE_HOME':root+'/home/.cache',
             'UV_CACHE_DIR':root+'/home/.hermes/cache/uv','HERMES_DISABLE_LAZY_INSTALLS':'1'}
        need(all(env[k]==v for k,v in expected.items()) and type(env['HERMES_DASHBOARD_SESSION_TOKEN']) is str
             and re.fullmatch('[A-Za-z0-9_-]{32,128}',env['HERMES_DASHBOARD_SESSION_TOKEN']) is not None,'plan')
        need(all(callable(getattr(inspector,k,None)) for k in ('capture','children','send','listener')),'plan')
        self.plan=copy.deepcopy(plan);self.inspector=inspector;self.clock=clock;self.wall=wall;self.popen=popen;self.sleep=sleep
        self.used=False;self.proc=None;self.bound=None;self.last=None;self.deadline=None;self.signals=[]
        self.exit_code=None;self.error=None;self.cleanup_error=None;self.stop_error=None
        self.cleanup_phase=False

    def remaining(self):
        now=self.clock()
        need(finite(now) and finite(self.deadline),'budget')
        limit=self.deadline if self.cleanup_phase else self.deadline-5
        need(now<limit and (self.last is None or now>=self.last),'budget')
        self.last=now;return limit-now

    def poll(self):
        need(self.proc is not None,'spawn')
        code=self.proc.poll() # exactly one handle observation, no returncode peek
        need(code is None or type(code) is int and -255<=code<=255,'exit')
        if code is not None:self.exit_code=code
        return code

    def check(self):
        self.remaining();need(self.proc is not None and self.bound is not None,'identity')
        need(self.poll() is None,'exit')
        row=self.inspector.capture(self.bound['pid'],self.bound['birth'])
        need(identity(row) and row==self.bound,'identity');self.remaining()
        children=self.inspector.children(self.bound['pid'],self.bound['birth'])
        need(type(children) is list and children==[],'tree');self.remaining()
        return True

    def start(self,deadline):
        need(not self.used,'consumed');self.used=True # also consumed if spawn raises
        self.deadline=deadline
        try:
            left=self.remaining();need(left+5<=300,'budget');before=self.wall();need(finite(before),'budget')
            p=self.plan
            self.proc=self.popen(p['argv'],executable=p['executable'],cwd=p['cwd'],env=dict(p['env']),
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                close_fds=True,start_new_session=True)
            # Retain the original handle before any post-spawn metadata call.
            self.remaining();after=self.wall();need(finite(after) and after>=before,'budget')
            need(type(self.proc.pid) is int and 1<self.proc.pid<2**31,'identity')
            need(self.poll() is None,'exit')
            row=self.inspector.capture(self.proc.pid)
            need(identity(row) and row['pid']==self.proc.pid and before-1<=row['birth']<=after
                 and row['cwd']==p['cwd'] and row['exe']==p['executable'] and row['argv']==p['argv'],'identity')
            self.bound=copy.deepcopy(row);self.check()
            return self.summary('HANDLE_BOUND_NOT_ACCEPTANCE')
        except BaseException as exc:
            self.error=exc.args[0] if type(exc) is Refused else 'spawn'
            return self.summary('FAIL')

    def listener(self,port):
        need(type(port) is int and 1024<=port<=65535 and port!=9119,'plan')
        self.check();ready=self.inspector.listener(copy.deepcopy(self.bound),port)
        need(type(ready) is bool,'identity');self.check();return ready

    async def wait_exit(self,seconds):
        until=min(self.deadline,self.clock()+seconds)
        while True:
            self.remaining()
            code=self.poll()
            if code is not None:return code
            if self.clock()>=until:return None
            await self.sleep(min(0.05,self.remaining(),max(0,until-self.clock())))

    async def close(self,request_stop):
        """Stop-channel request first, then TERM/KILL only after identity checks.

        The deadline is the SAME deadline as startup. No independent extension.
        Unknown identity or observed descendants receives no signals. Cleanup
        of an exited root does not prove that an unseen descendant never lived.
        """
        previous=self.cleanup_phase;self.cleanup_phase=True
        try:
            if self.proc is None:return self.summary('NOT_STARTED')
            self.remaining()
            if self.poll() is not None:return self.summary('EXIT_OBSERVED_NOT_ACCEPTANCE')
            need(self.bound is not None,'identity');self.check()
            need(callable(request_stop),'cleanup')
            try:await asyncio.wait_for(request_stop(),min(2,self.remaining()))
            except BaseException:self.stop_error='stop_channel'
            if await self.wait_exit(1) is not None:return self.summary('EXIT_OBSERVED_NOT_ACCEPTANCE')
            for signum,name in ((signal.SIGTERM,'TERM'),(signal.SIGKILL,'KILL')):
                self.check();self.check();self.remaining()
                self.inspector.send(copy.deepcopy(self.bound),signum);self.signals.append(name)
                if await self.wait_exit(1) is not None:return self.summary('EXIT_OBSERVED_NOT_ACCEPTANCE')
            raise Refused('cleanup')
        except BaseException as exc:
            self.cleanup_error=exc.args[0] if type(exc) is Refused else 'cleanup'
            return self.summary('FAIL')
        finally:self.cleanup_phase=previous

    def summary(self,result):
        if self.error is not None or self.cleanup_error is not None or self.stop_error is not None:result='FAIL'
        return {'schema':'hermes_0222_owned_host_v1','result':result,'error':self.error,'cleanup_error':self.cleanup_error,'stop_error':self.stop_error,
          'spawn_consumed':self.used,'handle_retained':self.proc is not None,'identity_bound':self.bound is not None,
          'exit_code':self.exit_code,'signals':list(self.signals),'tree_coverage':'OBSERVED_HOST_CHILDREN_ONLY',
          'complete_tree_proven':False,'native_acceptance':False}


if __name__=='__main__':raise SystemExit('FRESH_AUTHORIZED_PARENT_ASSEMBLY_REQUIRED')
