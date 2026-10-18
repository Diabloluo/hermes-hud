"""Single-use installer subprocess supervision; no CLI or authority creation.

Caller supplies a reviewed immutable executable catalogue and byte verifier,
fresh consumed authority, staged child guards and a common <=1800s deadline.
Only sampled descendants are registered. This is not kernel containment and
cannot prove the absence of an orphan created and lost between observations.
"""
import asyncio
import copy
import re
import signal
import subprocess
import time
from pathlib import PurePosixPath
from owned_process import NativeInspector, finite, identity, path

CODES=frozenset(('plan','consumed','budget','source','spawn','identity','tree','image','exit','cleanup'))
class Refused(ValueError):
    def __init__(self,code):super().__init__(code if code in CODES else 'identity')
def need(ok,code):
    if ok is not True:raise Refused(code) from None
def within(p,r):return path(p) and (p==r or p.startswith(r+'/'))
def digest(s):return type(s) is str and re.fullmatch('[a-f0-9]{64}',s) is not None

class NativeInstallInspector(NativeInspector):
    def capture_live(self,pid,birth):
        try:return self.capture(pid,birth)
        except self.ps.ZombieProcess:raise Refused('identity') from None
        except self.ps.NoSuchProcess:return None
    def descendants(self,root):
        need(self.capture(root['pid'],root['birth'])==root,'identity')
        children=self.ps.Process(root['pid']).children(recursive=True)
        need(len(children)<=128,'tree')
        rows=[]
        for child in children:
            row=self.capture(child.pid)
            p=self.ps.Process(child.pid)
            need(p.create_time()==row['birth'],'identity')
            parent=p.ppid()
            need(self.capture(child.pid,row['birth'])==row and type(parent) is int and parent>0,'identity')
            rows.append({'identity':row,'parent':parent})
        need(self.capture(root['pid'],root['birth'])==root,'identity')
        return rows

class InstallParent:
    def __init__(self,root,commands,images,verify_image,inspector,*,clock=time.monotonic,
                 wall=time.time,popen=subprocess.Popen,sleep=asyncio.sleep):
        need(type(root) is str and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}',root) is not None,'plan')
        need(type(commands) is list and len(commands)==3 and
             [r.get('stage') for r in commands]==['pm_install','npm_ci','web_build'],'plan')
        need(type(images) is dict and 1<=len(images)<=16 and
             all(within(p,root+'/home/.hermes/tools') and digest(h) for p,h in images.items()),'plan')
        for c in commands:
            need(type(c) is dict and set(c)=={'stage','argv','cwd','env'} and c['cwd'] in (root,root+'/sdk'),'plan')
            need(type(c['argv']) is list and 3<=len(c['argv'])<=24 and c['argv'][0] in images and
                 all(type(x) is str and 0<len(x)<=4096 and '\0' not in x for x in c['argv']),'plan')
            need(type(c['env']) is dict and all(type(k) is str and type(v) is str and '\0' not in k+v for k,v in c['env'].items()),'plan')
        need(commands==installation_commands(root,commands[0]['argv'][0],commands[1]['argv'][0],commands[1]['argv'][1]),'plan')
        need(callable(verify_image) and all(callable(getattr(inspector,k,None)) for k in ('capture','capture_live','descendants','send')),'plan')
        self.root=root;self.commands=copy.deepcopy(commands);self.images=dict(images)
        self.verify_image=verify_image;self.inspector=inspector
        self.clock=clock;self.wall=wall;self.popen=popen;self.sleep=sleep
        self.used=False;self.deadline=None;self.last=None;self.handles=[];self.cleanup_phase=False
        self.error=None;self.cleanup_error=None;self.stage=None;self.records=[]
    def remaining(self):
        now=self.clock()
        need(finite(now) and finite(self.deadline),'budget')
        limit=self.deadline if self.cleanup_phase else self.deadline-5
        need(now<limit and (self.last is None or now>=self.last),'budget')
        self.last=now;return limit-now
    def image(self,row):
        need(identity(row) and row['exe'] in self.images and within(row['cwd'],self.root),'image')
        self.remaining()
        need(self.verify_image(row['exe'])==self.images[row['exe']],'image')
        self.remaining()
    def poll(self,entry):
        code=entry['handle'].poll()
        need(code is None or type(code) is int and -255<=code<=255,'exit')
        entry['exit_code']=code
        return code
    def inspect_live(self,expected):
        self.remaining();row=self.inspector.capture_live(expected['pid'],expected['birth']);self.remaining()
        if row is not None:need(row==expected and identity(row),'identity')
        return row
    def sample(self,entry):
        self.remaining();known=entry['children'];live={}
        for pid,old in known.items():
            row=self.inspect_live(old)
            if row is not None:live[pid]=row
        if self.poll(entry) is None:
            need(entry['root'] is not None,'identity')
            root=self.inspect_live(entry['root']);need(root==entry['root'],'identity')
            # The root image was byte-checked at bind; full identity is checked
            # at every sample. Rehash again before any signal, not at 10 Hz.
            rows=self.inspector.descendants(root);self.remaining()
            need(type(rows) is list and len(rows)<=128,'tree');pending={};seen=set()
            for r in rows:
                need(type(r) is dict and set(r)=={'identity','parent'} and identity(r['identity']) and type(r['parent']) is int,'tree')
                actual=r['identity'];pid=actual['pid']
                need(pid!=root['pid'] and pid not in seen and actual['birth']>=root['birth'],'identity');seen.add(pid)
                if pid in known:need(actual==known[pid],'identity')
                else:pending[pid]=r
            while pending:
                adopted=[]
                for pid,r in pending.items():
                    parent=r['parent'];old=root if parent==root['pid'] else live.get(parent)
                    if old is None:continue
                    need(r['identity']['birth']>=old['birth'] and len(known)<128,'identity')
                    self.image(r['identity'])
                    # Re-observe the parent before registration, not just its PID.
                    need(self.inspect_live(old)==old,'identity')
                    need(self.inspect_live(r['identity'])==r['identity'],'identity')
                    known[pid]=copy.deepcopy(r['identity']);live[pid]=r['identity'];adopted.append(pid)
                need(bool(adopted),'tree')
                for pid in adopted:del pending[pid]
        return live
    def bind(self,entry,command,before):
        self.remaining();after=self.wall()
        need(finite(after) and after>=before and type(entry['handle'].pid) is int and entry['handle'].pid>1,'identity')
        need(self.poll(entry) is None,'exit')
        row=self.inspector.capture(entry['handle'].pid)
        need(identity(row) and row['pid']==entry['handle'].pid and before-1<=row['birth']<=after and
             row['exe']==command['argv'][0] and row['argv']==command['argv'] and row['cwd']==command['cwd'],'identity')
        self.image(row);entry['root']=copy.deepcopy(row)
    async def cleanup(self,entry):
        previous=self.cleanup_phase;self.cleanup_phase=True
        try:
            # Unknown identity never authorizes signals, even to a retained PID.
            self.remaining()
            if entry['root'] is None:
                need(self.poll(entry) is not None,'identity');return
            for sig,name in ((signal.SIGTERM,'TERM'),(signal.SIGKILL,'KILL')):
                live=self.sample(entry)
                if self.poll(entry) is None:live[entry['root']['pid']]=entry['root']
                if not live:return
                # Every target is known; recheck image + full identity twice.
                # No process group signals. Children first, then root.
                targets=sorted(live.values(),key=lambda r:(r['pid']==entry['root']['pid'],-r['birth']))
                for expected in targets:
                    if self.inspect_live(expected) is None:continue
                    self.image(expected)
                    need(self.inspect_live(expected)==expected and self.inspect_live(expected)==expected,'identity')
                    self.remaining();self.inspector.send(copy.deepcopy(expected),sig)
                    entry['signals'].append(name)
                until=min(self.deadline,self.clock()+1)
                while self.clock()<until:
                    self.remaining()
                    live=self.sample(entry)
                    if self.poll(entry) is not None and not live:return
                    await self.sleep(min(.05,self.remaining()))
            need(self.poll(entry) is not None and not self.sample(entry),'cleanup')
        except BaseException as exc:
            self.cleanup_error=exc.args[0] if type(exc) is Refused else 'cleanup'
        finally:self.cleanup_phase=previous
    async def run(self,deadline,source_check):
        need(not self.used,'consumed');self.used=True;self.deadline=deadline
        try:
            # Five seconds belong to cleanup INSIDE the original budget.
            need(self.remaining()+5<=1800 and callable(source_check),'budget')
            initial=source_check();need(digest(initial),'source')
            for c in self.commands:
                self.stage=c['stage'];self.remaining()
                need(source_check()==initial,'source')
                need(self.verify_image(c['argv'][0])==self.images[c['argv'][0]],'image')
                self.remaining();before=self.wall();need(finite(before),'budget')
                entry={'handle':None,'root':None,'children':{},'signals':[],'exit_code':None}
                proc=self.popen(c['argv'],executable=c['argv'][0],cwd=c['cwd'],env=dict(c['env']),
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     close_fds=True,start_new_session=True)
                entry['handle']=proc;self.handles.append(entry) # retain before any metadata
                self.bind(entry,c,before)
                while True:
                    live=self.sample(entry)
                    if self.poll(entry) is not None:
                        need(entry['exit_code']==0,'exit');need(not live,'tree');break
                    await self.sleep(min(.1,self.remaining()))
                self.records.append({'stage':c['stage'],'exit_code':entry['exit_code'],
                                     'registered_children':len(entry['children'])})
                need(source_check()==initial,'source')
        except BaseException as exc:
            self.error=exc.args[0] if type(exc) is Refused else 'spawn'
        finally:
            for entry in reversed(self.handles):
                if entry['exit_code'] is None or entry['children']:
                    await self.cleanup(entry)
        return {'schema':'hermes_0222_install_parent_v1','result':'COMMANDS_EXITED_ZERO_NOT_ACCEPTANCE' if
                 self.error is None and self.cleanup_error is None and len(self.records)==3 else 'FAIL',
                'error':self.error,'cleanup_error':self.cleanup_error,'stage':self.stage,
                'spawned':len(self.handles),'commands':copy.deepcopy(self.records),
                'signals_count':sum(len(e['signals']) for e in self.handles),
                'tree_coverage':'REGISTERED_DESCENDANTS_ONLY','complete_tree_proven':False,
                'native_acceptance':False}

def installation_commands(root,python,node,npm_cli):
    # Only this fixed command composition is intended for native assembly.
    from official_entry import environment
    from web_preparation import build_plan
    web=build_plan(root,node,npm_cli)
    return [{'stage':'pm_install','argv':[python,'-I','-B',root+'/tool/official_entry.py'],
             'cwd':root,'env':environment(root,'install')}]+[
             {'stage':c['stage'],'argv':c['argv'],'cwd':web['cwd'],'env':web['env']} for c in web['commands']]

if __name__=='__main__':raise SystemExit('REVIEWED_INSTALLER_AND_FRESH_AUTHORITY_REQUIRED')

