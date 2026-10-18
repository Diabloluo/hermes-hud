"""Concrete remote staging/install/handoff/host adapters. Never invoked on import.

Only remote_entry may assemble this backend after the remote authority gate.
SDK calls run in the owned PM/host children, not in the controller interpreter.
"""
import asyncio
import hashlib
import io
import os
from pathlib import Path,PurePosixPath
import secrets
import stat
import subprocess
import sys
import time
import zipfile
from artifact_stage import download,unpack,stage
from remote_contract import need,encode,sha,child_bindings
from remote_files import read,write_new,verify_rows
from pm_handoff import decode,HOST_COMMIT,HUD_COMMIT,host_plan,relative
from official_entry import environment
from installed_closure import TEXT,TEXT_NAMES
from plugin_handoff import projection,CONFIG

PYTHON_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.14.7+20260901-x86_64-apple-darwin-install_only.tar.gz'
PYTHON_SHA='dd8841a2e8ef94bd1a02b52f92843120942140f112145d4e0199abab56f120b1'
WHEELS=(
 ('https://files.pythonhosted.org/packages/e7/36/5ee6e05c9bd427237b11b3937ad82bb8ad2752d72c6969314590dd0c2f6e/psutil-7.2.2-cp36-abi3-macosx_10_9_x86_64.whl','ed0cace939114f62738d808fdcecd4c869222507e266e574799e9c0faa17d486'),
 ('https://files.pythonhosted.org/packages/fa/a8/5b41e0da817d64113292ab1f8247140aac61cbf6cfd085d6a0fa77f4984f/websockets-15.0.1-py3-none-any.whl','f7a866fbc1e97b5c617ee4116daaa09b722101d4a3c170c787450ba409f9736f'))

def row(name,raw):
    kind='text' if PurePosixPath(name).suffix in TEXT or PurePosixPath(name).name in TEXT_NAMES else 'binary'
    return {'path':name,'bytes':len(raw),'sha256':sha(raw),'kind':kind}

def checkout_files(checkout,commit,env):
    """Read only tracked bytes at the fixed commit; never recurse into .git.

    Checkout action supplies Git objects. Every selected working file is checked
    against its Git blob. Internal source links are copied as bytes, not links.
    """
    need(os.path.realpath(checkout)==checkout and len(commit)==40)
    def git(args):
        r=subprocess.run(['/usr/bin/git','-C',checkout,*args],env=env,stdin=subprocess.DEVNULL,
              stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=30,check=False)
        need(r.returncode==0 and len(r.stdout)<=4*1024**2);return r.stdout
    need(git(['rev-parse','HEAD']).decode().strip()==commit)
    records=git(['ls-tree','-rz','--full-tree',commit]).split(b'\0');objects={};total=0
    need(records[-1]==b'' and 0<len(records)-1<=8192)
    for item in records[:-1]:
        meta,name=item.split(b'\t',1);mode,kind,h=meta.decode('ascii').split();name=name.decode('utf-8')
        need(relative(name) and '\\' not in name and kind=='blob' and mode in ('100644','100755','120000')
             and name.casefold() not in {n.casefold() for n in objects})
        path=checkout+'/'+name
        if mode=='120000':
            need(stat.S_ISLNK(os.lstat(path).st_mode));raw=os.readlink(path).encode()
        else:raw=read(path,512*1024**2)
        need(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==h)
        total+=len(raw);need(total<=1024**3);objects[name]=(mode,raw)
    def resolve(name,seen):
        need(name in objects and name not in seen and len(seen)<64)
        mode,raw=objects[name]
        if mode!='120000':return mode,raw
        target=raw.decode('utf-8');need(not target.startswith('/') and '\\' not in target)
        parts=list(PurePosixPath(name).parent.parts)
        for part in target.split('/'):
            if part in ('','.'):continue
            if part=='..':need(bool(parts));parts.pop()
            else:parts.append(part)
        return resolve('/'.join(parts),seen|{name})
    files=[];total=0
    for name in sorted(objects):
        mode,raw=resolve(name,set());total+=len(raw);need(total<=1024**3)
        files.append({'path':name,'data':raw,'sha256':sha(raw),'mode':0o755 if mode=='100755' else 0o644,
                      'materialized_link':objects[name][0]=='120000'})
    return files

class Backend:
    def __init__(self,here,root,workspace,auth,freeze,report,claim):
        self.here=here;self.root=root;self.workspace=workspace;self.auth=auth
        self.freeze=freeze;self.report=report;self.claim=claim;self.rows=[]
        self.installer=None;self.completion=None;self.started=time.monotonic();self.deadline=self.started+1800
        self.used=False

    def remaining(self):
        n=self.deadline-time.monotonic();need(0<n<=1800);return n

    def sources(self):
        need(os.path.realpath('/private/tmp')=='/private/tmp')
        os.mkdir(self.root,0o700)
        write_new(self.root,'evidence/REMOTE_CLAIM.json',encode(self.claim))
        write_new(self.root,'tmp/empty-npmrc',b'')
        write_new(self.root,'home/.hermes/config.yaml',CONFIG)
        env=environment(self.root,'install')
        for slot,checkout,commit in (('sdk','sdk-source',HOST_COMMIT),('product','hud-source',HUD_COMMIT)):
            self.remaining();files=checkout_files(self.workspace+'/'+checkout,commit,env)
            stage(self.root,slot,files)
            self.rows.extend(row(slot+'/'+f['path'],f['data']) for f in files)
        files=[]
        for name,h in self.freeze['files'].items():
            if not name.endswith('.py') or name.startswith('test_'):continue
            raw=read(self.here+'/'+name);need(sha(raw)==h)
            files.append({'path':name,'data':raw,'sha256':h,'mode':0o644,'materialized_link':False})
        stage(self.root,'tool',files)
        self.rows.extend(row('tool/'+f['path'],f['data']) for f in files)
        byname={r['path']:r for r in self.rows}
        def product_read(name):
            raw=read(self.root+'/'+name);need(sha(raw)==byname[name]['sha256']);return raw
        for f in projection(self.rows,product_read):write_new(self.root,f['path'],f['data'])
        self.remaining();verify_rows(self.root,self.rows)

    def bootstrap(self):
        self.remaining()
        raw=download(PYTHON_URL,PYTHON_SHA,('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'),self.deadline)
        files=unpack(raw,PYTHON_SHA,'python');stage(self.root,'bootstrap',files)
        write_new(self.root,'home/.hermes/tools/.owned-stage',b'owned\n')
        os.rename(self.root+'/bootstrap',self.root+'/home/.hermes/tools/bootstrap')
        self.rows.extend(row('home/.hermes/tools/bootstrap/'+f['path'],f['data']) for f in files)
        # Two fixed wheels for controller-only process identity and WS transport;
        # no pip resolver, setup.py, .pth execution or SDK import in controller.
        names=set()
        for url,h in WHEELS:
            data=download(url,h,('files.pythonhosted.org',),self.deadline)
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                need(len(z.infolist())<=256);expanded=0
                for i in z.infolist():
                    need(not i.flag_bits&1 and not i.is_dir() and relative(i.filename)
                         and not i.filename.endswith('.pth') and i.filename not in names
                         and stat.S_IFMT(i.external_attr>>16) in (0,stat.S_IFREG)
                         and i.file_size<=2*1024**2 and i.file_size<=max(i.compress_size,1)*200)
                    expanded+=i.file_size;need(expanded<=16*1024**2);names.add(i.filename)
                    data=z.read(i);need(len(data)==i.file_size)
                    write_new(self.root,'controller/'+i.filename,data)
        sys.path.insert(0,self.root+'/controller')
        from remote_install import RemoteInstaller,NativeInstallInspector,SYSTEM_IMAGES
        self.installer=RemoteInstaller(self.root,NativeInstallInspector(),
             system_images=tuple(os.path.realpath(p) for p in SYSTEM_IMAGES))
        # Source checks cover this bootstrap, SDK and reviewed tool code before
        # and after each command. Dynamic installer images remain observations.
        self.rows.sort(key=lambda r:r['path']);verify_rows(self.root,self.rows)
        self.source=sha(encode(self.rows))
        write_new(self.root,'evidence/install-input.json',encode({'schema':'hermes_0222_install_input_v1',
            'grant':self.auth['grant'],'scope':self.auth['scope'],'deadline_wall':time.time()+self.remaining(),
            'files':self.rows,'source':self.source,
            'interpreter':self.root+'/home/.hermes/tools/bootstrap/bin/python3.14'}))

    def source_check(self):
        self.remaining();verify_rows(self.root,self.rows)
        # Same 3 GiB available-memory admission; resource pressure never lowers it.
        from owned_process import NativeInspector
        ps=NativeInspector().ps;v=ps.virtual_memory();s=ps.swap_memory()
        need(type(v.available) is int and v.available>=3072*1024**2
             and type(s.used) is int and s.used<=512*1024**2)
        return self.source

    async def pm_install(self):
        command={'argv':[self.root+'/home/.hermes/tools/bootstrap/bin/python3.14','-I','-B',self.root+'/tool/remote_pm_entry.py'],
                 'cwd':self.root,'env':environment(self.root,'install')}
        return await self.installer.run_one('pm_install',command,self.deadline,self.source_check)

    def installed_locations(self):
        from installed_closure import selected_paths
        key=sha((self.root+'/sdk').encode())[:16]
        facts=decode(read(self.root+'/home/.hermes/installs/'+key+'/facts.json'))
        selected=facts['packages']['venv']['environment']
        need(type(selected) is str and selected.startswith(self.root+'/'))
        self.environment=selected[len(self.root)+1:];selected_paths(self.root,self.environment)
        # Derive image location from the real pyvenv.cfg, never an external HOME.
        values={}
        for line in read(selected+'/pyvenv.cfg').decode().splitlines():
            if not line.strip() or line.startswith('#'):continue
            k,v=(x.strip() for x in line.split('=',1));need(k not in values);values[k]=v
        self.python=values['home']+'/python3.14'
        need(self.python.startswith(self.root+'/home/.hermes/tools/') and os.path.realpath(self.python)==self.python)
        tools=decode(read(self.root+'/home/.hermes/tools/facts.json'))['packages']
        def entry(name,version,suffix):
            f=tools[name];need(f['version']==version and type(f['entry']) is str
                              and relative(f['entry']) and '/' not in f['entry'])
            p=self.root+'/home/.hermes/tools/'+f['entry']+suffix
            need(os.path.realpath(p)==p);read(p,512*1024**2);return p
        self.node=entry('node','26.7.0','/bin/node')
        self.npm=entry('npm','12.0.2','/lib/node_modules/npm/bin/npm-cli.js')

    async def web(self,stage_name):
        from web_preparation import build_plan
        if stage_name=='npm_ci':self.installed_locations()
        plan=build_plan(self.root,self.node,self.npm)
        command=plan['commands'][0 if stage_name=='npm_ci' else 1]
        return await self.installer.run_one(stage_name,{'argv':command['argv'],'cwd':plan['cwd'],'env':plan['env']},
                                            self.deadline,self.source_check)

    def handoff(self):
        from install_completion import prepare
        from installed_closure import collect
        from runtime_aliases import NAME as ALIASES, from_inventory
        from child_guard import PLATFORM_SHA
        self.source_check()
        observed=collect(self.root,self.environment,self.python[len(self.root)+1:])
        write_new(self.root,ALIASES,encode(from_inventory(self.root,self.environment,
                  self.python[len(self.root)+1:],observed)))
        site=self.root+'/'+self.environment+'/lib/python3.14/site-packages'
        prefix=str(PurePosixPath(self.python).parent.parent)
        paths=[self.root+'/sdk',site,self.root+'/tool',prefix+'/lib/python3.14',prefix+'/lib/python3.14/lib-dynload']
        self.port=20000+secrets.randbelow(30000)
        self.completion=prepare(self.root,self.environment,self.python[len(self.root)+1:],self.auth['grant'],self.port,
             paths,{self.root+'/sdk/hermes_platform/host/runtime.py':PLATFORM_SHA},time.time())
        self.remaining()

    async def host(self):
        from child_runtime import validate,verify_sources
        from retained_mailbox import RetainedMailbox
        from sealed_session import ChildChannel,run_sealed
        from owned_process import OwnedHost,NativeInspector
        config_raw=self.completion['child_config_bytes'];config=decode(config_raw)
        validate(config,self.root,time.time()).verify_all()
        start=time.time();a,b,c=child_bindings(config_raw,self.report,self.auth,start)
        deadline=time.monotonic()+max(0,c['deadline_wall']-time.time())
        for name,data in (('tool/child-bootstrap.json',config_raw),('tool/AUTHORIZATION.json',encode(a)),
                          ('tool/REVIEW_ACCEPTANCE.json',encode(b)),('tool/REVIEW.md',self.report),('evidence/CLAIM.json',encode(c))):
            write_new(self.root,name,data)
        token=secrets.token_urlsafe(32)
        plan=host_plan(self.completion['pm_handoff'],self.port,token)
        parent=OwnedHost({k:plan[k] for k in ('executable','argv','cwd','env')},NativeInspector())
        def checkpoint():need(time.monotonic()<deadline)
        transport=RetainedMailbox(self.root+'/evidence','parent',checkpoint).prepare(create=True)
        channel=ChildChannel(transport,self.auth['grant'],config['source'])
        return await run_sealed(parent,channel,self.port,token,deadline,
             lambda:verify_sources(self.root,config['files'],config['selected_environment'],config['interpreter']))

async def execute(backend):
    """One ordered path, with no retries and no host after install failure."""
    stage_name='sources';commands=[];host=None
    try:
        need(getattr(backend,'used',False) is False);backend.used=True
        backend.sources();stage_name='bootstrap';backend.bootstrap()
        stage_name='pm_install';commands.append(await backend.pm_install())
        stage_name='npm_ci';commands.append(await backend.web(stage_name))
        stage_name='web_build';commands.append(await backend.web(stage_name))
        stage_name='handoff';backend.handoff()
        stage_name='host';host=await backend.host();stage_name='aggregate'
    except BaseException:pass
    from remote_contract import aggregate
    return aggregate(backend.auth['grant'],stage_name,commands,host)
