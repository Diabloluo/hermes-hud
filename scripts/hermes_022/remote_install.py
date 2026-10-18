"""Disposable-VM installer supervision; host policy is NOT changed.

Installer native descendants are not contained by Python audit. Up to sixteen
observed executable images are hash-bound at adoption, with the inherited
identity-before-signal discipline. This is observation, not provenance or a
proof that no unseen descendant exists. Unknown images stop the sequence.
"""
import asyncio
import copy
import os
import subprocess
import time
from install_parent import InstallParent,NativeInstallInspector,need,digest
from owned_process import finite
from remote_files import read
from remote_contract import sha
from official_entry import environment,layout
from web_preparation import build_plan

SYSTEM_IMAGES=('/usr/bin/git','/usr/bin/codesign','/usr/bin/xcrun','/usr/bin/clang','/bin/sh')

class RemoteInstaller(InstallParent):
    def __init__(self,root,inspector,*,clock=time.monotonic,wall=time.time,
                 popen=subprocess.Popen,sleep=asyncio.sleep,system_images=()):
        layout(root)
        need(type(system_images) is tuple and len(system_images)<=len(SYSTEM_IMAGES),'plan')
        self.root=root;self.inspector=inspector;self.clock=clock;self.wall=wall
        self.popen=popen;self.sleep=sleep;self.images={};self.system_images=system_images
        self.verify_image=lambda p:sha(read(p,512*1024**2))
        self.used=False;self.deadline=None;self.last=None;self.handles=[];self.cleanup_phase=False
        self.error=None;self.cleanup_error=None;self.stage=None;self.records=[]

    def image(self,row):
        from owned_process import identity
        need(identity(row) and (row['cwd']==self.root or row['cwd'].startswith(self.root+'/')),'image')
        p=row['exe']
        need(os.path.realpath(p)==p and (p in self.system_images or
             p.startswith(self.root+'/home/.hermes/tools/') or
             p.startswith(self.root+'/sdk/node_modules/') or p.startswith(self.root+'/sdk/web/node_modules/')),'image')
        self.remaining();h=self.verify_image(p);need(digest(h),'image');self.remaining()
        if p not in self.images:
            need(len(self.images)<16,'image');self.images[p]=h
        need(self.images[p]==h,'image')

    async def run_one(self,stage,command,deadline,source_check):
        need(self.error is None and self.cleanup_error is None and len(self.records)<3
             and stage==('pm_install','npm_ci','web_build')[len(self.records)],'consumed')
        # Consume phase before source checks or a possibly ambiguous spawn.
        self.stage=stage;self.error='incomplete';self.deadline=deadline;entry=None
        try:
            need(self.remaining()+5<=1800 and callable(source_check),'budget')
            need(type(command) is dict and set(command)=={'argv','cwd','env'}
                 and command['cwd'] in (self.root,self.root+'/sdk'),'plan')
            argv=command['argv'];need(type(argv) is list and len(argv)>=4,'plan')
            if stage=='pm_install':
                need(argv==[self.root+'/home/.hermes/tools/bootstrap/bin/python3.14','-I','-B',self.root+'/tool/remote_pm_entry.py']
                     and command['cwd']==self.root and command['env']==environment(self.root,'install'),'plan')
            else:
                plan=build_plan(self.root,argv[0],argv[1] if stage=='npm_ci' else self.npm_cli)
                expected=plan['commands'][0 if stage=='npm_ci' else 1]['argv']
                need(argv==expected and command['cwd']==plan['cwd'] and command['env']==plan['env'],'plan')
                if stage=='npm_ci':self.npm_cli=argv[1]
            before_source=source_check();need(digest(before_source),'source')
            # Bind root image bytes before creating a process; first observation
            # after spawn must still match. Descendant images bind on adoption.
            image_hash=self.verify_image(argv[0]);need(digest(image_hash),'image')
            if argv[0] not in self.images:need(len(self.images)<16,'image');self.images[argv[0]]=image_hash
            need(self.images[argv[0]]==image_hash,'image')
            before=self.wall();need(finite(before),'budget')
            self.remaining()
            proc=self.popen(argv,executable=argv[0],cwd=command['cwd'],env=dict(command['env']),
                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                 close_fds=True,start_new_session=True)
            entry={'handle':proc,'root':None,'children':{},'signals':[],'exit_code':None}
            self.handles.append(entry)
            self.bind(entry,command,before)
            while True:
                live=self.sample(entry)
                if self.poll(entry) is not None:
                    need(type(entry['exit_code']) is int and entry['exit_code']==0 and not live,'exit');break
                await self.sleep(min(.1,self.remaining()))
            need(source_check()==before_source,'source')
            self.error=None
        except BaseException as exc:
            from install_parent import Refused
            self.error=exc.args[0] if type(exc) is Refused else 'spawn'
        finally:
            if entry is not None and (entry['exit_code'] is None or entry['children']):await self.cleanup(entry)
        row={'stage':stage,'exit_code':entry['exit_code'] if entry else None,
             'error':self.error,'cleanup_error':self.cleanup_error,
             'registered_images':len(self.images),'tree_coverage':'REGISTERED_DESCENDANTS_ONLY'}
        need(self.error is None and self.cleanup_error is None,'exit')
        self.records.append(copy.deepcopy(row));return row
