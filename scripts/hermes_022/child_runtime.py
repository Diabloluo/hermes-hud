"""Independent host child assembly. Installation is deliberately a different role.

No argument, environment variable or fallback enables execution without all
fresh parent-consumed bindings. This file defines the mechanism; no current
authorization/claim or installed runtime is supplied by this preparation.
"""
import hashlib
import importlib
import json
import os
from pathlib import PurePosixPath
import platform
import stat
import sys
import time
from child_protocol import require, hex_value, finite
from pm_handoff import BoundFiles, decode, file_stamp, HOST_COMMIT, HUD_COMMIT, RELEASE_JS_SHA
from official_entry import layout, environment, dispatch
from child_guard import FullGuard,PLATFORM_SHA
from retained_mailbox import RetainedMailbox
from server_bridge import ServerBridge
from child_execution import execute
from runtime_aliases import NAME as ALIASES, verify as verify_aliases

SCOPE='one_hermes_0222_owned_host_300s_no_retry_no_risk_acceptance'
WEB_SERVER_SHA='bd14c619166da6534b94d0a6e802c6da3711f9738dc80747c17f85af2e71af0b'
MAIN_SHA='88a7fc166d3bfaac082d44bbfc36c93b53c50f7508ca96e32206dc3f1edfaa82'
UV_PATCH_SHA='cfb3db86aaa53bb62b5ff764970bec2d71c9228590a0ebec57f6ec926cc0bf1a'

def canonical_json(row):return (json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()

def read_fixed(root,name,limit=2*1024**2):
    """Bootstrap only: exact relative name, no-follow every ancestor, bounded."""
    layout(root);require(name in ('tool/child-bootstrap.json','evidence/CLAIM.json',
        'tool/AUTHORIZATION.json','tool/REVIEW_ACCEPTANCE.json','tool/REVIEW.md'))
    descriptors=[];fd=None;result=None;failed=False
    try:
        d=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);descriptors.append(d)
        parts=PurePosixPath(root+'/'+name).parts[1:]
        for part in parts[:-1]:
            d=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=d);descriptors.append(d)
        fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=d)
        a=os.fstat(fd);require(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and 0<a.st_size<=limit)
        data=b''
        while len(data)<a.st_size:
            block=os.read(fd,min(65536,a.st_size-len(data)));require(bool(block));data+=block
        require(os.read(fd,1)==b'' and file_stamp(a)==file_stamp(os.fstat(fd))==file_stamp(os.stat(parts[-1],dir_fd=d,follow_symlinks=False)))
        result=data
    except BaseException:failed=True
    finally:
        for owned in ([fd] if fd is not None else [])+list(reversed(descriptors)):
            try:os.close(owned)
            except BaseException:failed=True
    require(not failed);return result

def validate(config,root,now):
    require(type(config) is dict and set(config)=={'schema','scope','grant','root','role','port','source',
        'files','paths','bindings','selected_environment','interpreter','host_commit','hud_commit'})
    layout(root);require(config['schema']=='hermes_0222_child_bootstrap_v1' and config['scope']==SCOPE
                        and config['root']==root and config['role']=='host')
    require(hex_value(config['grant'],32) and hex_value(config['source'],64) and finite(now))
    require(type(config['port']) is int and 1024<=config['port']<=65535 and config['port']!=9119)
    require(config['host_commit']==HOST_COMMIT and config['hud_commit']==HUD_COMMIT)
    catalog=BoundFiles(root,config['files']) # validates every row without opening it
    require(digest(canonical_json(config['files']))==config['source'])
    exact={root+'/'+r['path']:r for r in config['files']}
    required={'tool/official_entry.py','tool/child_runtime.py','tool/child_guard.py','tool/child_execution.py',
              'tool/child_protocol.py','tool/server_bridge.py','tool/retained_mailbox.py','tool/pm_handoff.py',
              'tool/runtime_fence.py','tool/guard_stack.py','tool/audit_adapter.py','tool/boundary_policy.py',
              'tool/optional_process.py','tool/runtime_aliases.py','tool/installed-aliases.json',
              'sdk/hermes_cli/main.py','sdk/hermes_cli/web_server.py',
              'sdk/hermes_platform/host/runtime.py','product/dashboard/dist/index.js'}
    require({root+'/'+p for p in required}<=exact.keys())
    require(WEB_SERVER_SHA is not None and exact[root+'/sdk/hermes_cli/web_server.py']['sha256']==WEB_SERVER_SHA
            and exact[root+'/sdk/hermes_cli/main.py']['sha256']==MAIN_SHA
            and exact[root+'/sdk/hermes_platform/host/runtime.py']['sha256']==PLATFORM_SHA
            and exact[root+'/product/dashboard/dist/index.js']['sha256']==RELEASE_JS_SHA)
    require(type(config['paths']) is list and config['paths'] and config['paths'][0]==root+'/sdk')
    require(type(config['selected_environment']) is str)
    require(len(config['paths'])>=2 and config['paths'][1]==config['selected_environment']+'/lib/python3.14/site-packages')
    approved_roots=(root+'/sdk',root+'/tool',root+'/home/.hermes/tools',config['selected_environment'])
    require(len(config['paths'])<=128 and len(set(config['paths']))==len(config['paths'])
            and all(type(p) is str and any(p==r or p.startswith(r+'/') for r in approved_roots)
                    and (p in exact or any(q.startswith(p+'/') for q in exact)) for p in config['paths']))
    require(type(config['bindings']) is dict and len(config['bindings'])<=8
            and all(p in exact and exact[p]['sha256']==h for p,h in config['bindings'].items()))
    require(config['bindings'].get(root+'/sdk/hermes_platform/host/runtime.py')==PLATFORM_SHA)
    require(type(config['interpreter']) is str and config['interpreter'] in exact
            and config['interpreter'].startswith(root+'/home/.hermes/tools/'))
    # Full path syntax/selected-generation checks also happen in HostBoundary.
    return catalog

def validate_pth(config,catalog,root):
    """No blanket .pth execution permission; only one fixed uv upstream shim.

    The uv shim installs a distutils meta-path finder. It is not run here; the
    official activation may import these exact bytes later under the guard.
    Other executable .pth forms remain refused, even if a package expects them.
    """
    selected=config['selected_environment']+'/lib/python3.14/site-packages'
    rows={root+'/'+r['path']:r for r in config['files']}
    for file in config['files']:
        if not file['path'].endswith('.pth'):continue
        raw=catalog.read(file['path'])
        if root+'/'+file['path']==selected+'/_virtualenv.pth' and raw==b'import _virtualenv':
            helper=rows.get(selected+'/_virtualenv.py')
            require(helper is not None and helper['sha256']==UV_PATCH_SHA and helper['kind']=='text')
            continue
        for line in raw.decode('utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            require(not line.startswith(('import ','import\t')))
            target=os.path.realpath(str(PurePosixPath(root+'/'+file['path']).parent/line))
            require(target in config['paths'])

def authority(raw,auth,acceptance,report,claim,config,now):
    require(type(auth) is dict and set(auth)=={'schema','scope','grant','config_sha256','report_sha256',
                                            'issued','expires','max_runs','owner_confirmed'})
    require(auth['schema']=='hermes_0222_child_authorization_v1' and auth['scope']==SCOPE
            and auth['grant']==config['grant'] and auth['config_sha256']==digest(raw)
            and auth['report_sha256']==digest(report) and type(auth['max_runs']) is int and auth['max_runs']==1
            and auth['owner_confirmed'] is True)
    require(all(finite(auth[k]) for k in ('issued','expires')) and auth['issued']<=now<=auth['expires']
            and 0<auth['expires']-auth['issued']<=3600)
    require(type(acceptance) is dict and acceptance=={'schema':'hermes_0222_child_acceptance_v1','safety':'PASS',
            'scope':SCOPE,'config_sha256':digest(raw),'report_sha256':digest(report)})
    require(type(claim) is dict and set(claim)=={'schema','grant','config_sha256','state','started_wall','deadline_wall'})
    require(claim['schema']=='hermes_0222_parent_claim_v1' and claim['grant']==config['grant']
            and claim['config_sha256']==digest(raw) and claim['state']=='CONSUMED_ONCE_NO_RETRY')
    start,end=claim['started_wall'],claim['deadline_wall']
    require(finite(start) and finite(end) and auth['issued']<=start<=now<end and 0<end-start<=300)
    return end-now

def consume_child(root,grant):
    """Independent second exclusive claim, before mailbox/guard/SDK imports."""
    path=root+'/evidence';require(os.path.realpath(path)==path)
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    out=None;failed=False
    try:
        out=os.open('CHILD_CONSUMED.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        data=canonical_json({'grant':grant,'state':'CONSUMED_ONCE_NO_RETRY'})
        require(os.write(out,data)==len(data));os.fsync(out);os.fsync(fd)
    except BaseException:failed=True
    finally:
        for owned in ([out] if out is not None else [])+[fd]:
            try:os.close(owned)
            except BaseException:failed=True
    require(not failed)

def verify_sources(root,files,environment=None,interpreter=None):
    """After guard: exact full-path reads, no directory-open exemption.

No-follow leaf + pre/post identity/canonical-name checks are time-of-read
observations, not an OS namespace lock. BoundFiles covers ancestors initially.
"""
    alias_raw=None
    for row in files:
        path=root+'/'+row['path'];require(os.path.realpath(path)==path)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);failed=False
        try:
            a=os.fstat(fd);require(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and a.st_size==row['bytes'])
            h=hashlib.sha256();size=0;chunks=[]
            while True:
                block=os.read(fd,min(262144,row['bytes']-size+1))
                if not block:break
                size+=len(block);require(size<=row['bytes']);h.update(block)
                if row['path']==ALIASES:chunks.append(block)
            require(size==row['bytes'] and h.hexdigest()==row['sha256'] and os.path.realpath(path)==path
                    and file_stamp(a)==file_stamp(os.fstat(fd))==file_stamp(os.stat(path,follow_symlinks=False)))
            if row['path']==ALIASES:alias_raw=b''.join(chunks)
        except BaseException:failed=True
        finally:
            try:os.close(fd)
            except BaseException:failed=True
        require(not failed)
    require(alias_raw is not None and type(environment) is str and environment.startswith(root+'/')
            and type(interpreter) is str and interpreter.startswith(root+'/'))
    verify_aliases(root,environment[len(root)+1:],interpreter[len(root)+1:],files,alias_raw)
    return digest(canonical_json(files))

def main(entry):
    channel=None;boundary=None
    try:
        root=str(PurePosixPath(entry).parent.parent);layout(root)
        require(entry==root+'/tool/official_entry.py' and os.getcwd()==root
                and sys.flags.isolated==1 and sys.flags.dont_write_bytecode==1 and sys.flags.optimize==0)
        require(sys.platform=='darwin' and platform.machine()=='x86_64' and sys.version_info[:3]==(3,14,7))
        raw=read_fixed(root,'tool/child-bootstrap.json');config=decode(raw);now=time.time()
        catalog=validate(config,root,now)
        seconds=authority(raw,decode(read_fixed(root,'tool/AUTHORIZATION.json')),
            decode(read_fixed(root,'tool/REVIEW_ACCEPTANCE.json')),read_fixed(root,'tool/REVIEW.md'),
            decode(read_fixed(root,'evidence/CLAIM.json')),config,now)
        deadline=time.monotonic()+seconds-5 # same original budget, cleanup reserve inside it
        require(deadline>time.monotonic())
        token=os.environ.get('HERMES_DASHBOARD_SESSION_TOKEN')
        require(dict(os.environ)==environment(root,'host',token) and os.path.realpath(sys.executable)==config['interpreter'])
        catalog.verify_all()
        verify_aliases(root,config['selected_environment'][len(root)+1:],
                       config['interpreter'][len(root)+1:],config['files'],catalog.read(ALIASES))
        validate_pth(config,catalog,root)
        exact={root+'/'+r['path'] for r in config['files']}
        # Already-loaded interpreter/tool sources are not exempted silently.
        for module in tuple(sys.modules.values()):
            path=getattr(module,'__file__',None)
            if path is not None:require(type(path) is str and path in exact)
        # A reviewed installed inventory supplies site-packages explicitly.
        # Never execute a .pth to discover paths and never retain ambient paths.
        require(all(os.path.realpath(p)==p for p in config['paths']))
        sys.path=list(config['paths'][1:])
        consume_child(root,config['grant'])
        # Only retained slots use this checkpoint, not the host's sticky guard.
        # They must remain able to carry a FAIL after the guard rejects I/O.
        channel=RetainedMailbox(root+'/evidence','child',lambda:require(time.monotonic()<deadline+5)).prepare()
        guard=FullGuard(root,config['files'],tuple(config['paths']),config['bindings'],config['port'],
            config['selected_environment'],platform=sys.platform,owner_uid=os.getuid())
        boundary=guard.boundary
        bridge=ServerBridge(channel,config['grant'],config['source'],boundary.checkpoint,deadline,time.monotonic)
        source_check=lambda:verify_sources(root,config['files'],config['selected_environment'],config['interpreter'])
        def importer(name):
            module=importlib.import_module(name)
            if name=='hermes_cli.main':
                server=importlib.import_module('hermes_cli.web_server')
                bridge.install(server,root+'/sdk/hermes_cli/web_server.py')
            return module
        return execute(channel,config['grant'],config['source'],bridge,boundary.checkpoint,source_check,
            lambda:dispatch(root,'host',dict(os.environ),boundary,source_check,port=config['port'],token=token,importer=importer,runtime=sys))
    except BaseException:
        if channel is not None:
            try:channel.close()
            except BaseException:pass
        return 2 # fixed exit only, no exception text/path/token output

if __name__=='__main__':raise SystemExit(2) # only the bound official_entry shim invokes main
