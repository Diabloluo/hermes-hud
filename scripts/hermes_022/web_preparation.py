"""Single-attempt web plan and bounded built-asset verification, no execution."""
import base64
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import PurePosixPath
import re
import stat
from urllib.parse import urlsplit


class Refused(ValueError):
    def __init__(self,code):super().__init__(code if code in {'input','lock','asset','path','limit','drift'} else 'asset')
def need(ok,code):
    if ok is not True:raise Refused(code) from None
def root_ok(root):return type(root) is str and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}',root) is not None
def relative(name):return type(name) is str and 0<len(name)<=1024 and str(PurePosixPath(name))==name and name!='.' and not name.startswith('/') and '..' not in PurePosixPath(name).parts and all(32<=ord(c)<127 for c in name) and '\\' not in name
def sha(raw):return hashlib.sha256(raw).hexdigest()


def build_plan(root,node,npm_cli):
    need(root_ok(root),'input')
    prefix=root+'/home/.hermes/tools/'
    need(all(type(p) is str and p.startswith(prefix) and relative(p[len(prefix):]) for p in (node,npm_cli)),'path')
    need(node.endswith('/bin/node') and npm_cli.endswith('/bin/npm-cli.js'),'path')
    sdk=root+'/sdk'
    env={'HOME':root+'/home','HERMES_HOME':root+'/home/.hermes','TMPDIR':root+'/tmp',
         'PATH':str(PurePosixPath(node).parent)+':/usr/bin:/bin:/usr/sbin:/sbin',
         'LANG':'en_US.UTF-8','LC_CTYPE':'en_US.UTF-8','TZ':'UTC','CI':'1',
         'NODE_OPTIONS':'--max-old-space-size=1024','RAYON_NUM_THREADS':'1','HERMES_WEB_BUILD_LIGHT':'1',
         'npm_config_cache':root+'/home/.cache/npm','npm_config_userconfig':root+'/tmp/empty-npmrc',
         'npm_config_globalconfig':root+'/tmp/empty-npmrc','npm_config_fetch_retries':'0',
         'npm_config_registry':'https://registry.npmjs.org/','npm_config_update_notifier':'false'}
    return {'schema':'hermes_0222_web_plan_v1','cwd':sdk,'env':env,'commands':[
         {'stage':'npm_ci','argv':[node,npm_cli,'ci','--no-audit','--no-fund','--engine-strict','--include=dev',
          '--include=optional','--include-workspace-root=true','--workspace','web','--ignore-scripts']},
         {'stage':'web_build','argv':[node,sdk+'/scripts/build/web.mjs','--source',sdk,'--icons',sdk,'--out',sdk+'/hermes_cli/web_dist']}],
         'required_versions':{'node':'26.7.0','npm':'12.0.2'},'max_attempts_per_command':1,
         'shares_install_budget_seconds':1800,'native_ready':False}


def lock_catalog(raw):
    need(type(raw) is bytes and 0<len(raw)<=2*1024**2,'limit')
    def pairs(rows):
        out={}
        for k,v in rows:need(k not in out,'lock');out[k]=v
        return out
    try:row=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(Refused('lock')))
    except Exception:raise Refused('lock') from None
    need(type(row) is dict and type(row.get('lockfileVersion')) is int and row['lockfileVersion']==3 and type(row.get('packages')) is dict,'lock')
    need(1<=len(row['packages'])<=4096,'limit')
    archives=[];links=[]
    for path,item in row['packages'].items():
        need(path=='' or relative(path),'path');need(type(item) is dict,'lock')
        resolved=item.get('resolved')
        if item.get('link') is True:
            need(relative(resolved) and resolved in row['packages'],'lock');links.append({'path':path,'target':resolved});continue
        if resolved is None:
            need('node_modules' not in PurePosixPath(path).parts,'lock');continue
        need(type(resolved) is str and all(32<ord(c)<127 for c in resolved) and '\\' not in resolved,'lock')
        try:u=urlsplit(resolved)
        except Exception:raise Refused('lock') from None
        need(u.scheme=='https' and u.netloc=='registry.npmjs.org' and not u.query and not u.fragment and
             u.path.startswith('/') and relative(u.path[1:]) and '%' not in u.path,'lock')
        integrity=item.get('integrity')
        need(type(integrity) is str and re.fullmatch(r'sha512-[A-Za-z0-9+/]{86}==',integrity) is not None,'lock')
        try:decoded=base64.b64decode(integrity[7:],validate=True)
        except Exception:raise Refused('lock') from None
        need(len(decoded)==64 and base64.b64encode(decoded).decode('ascii')==integrity[7:],'lock')
        archives.append({'path':path,'url':resolved,'integrity':integrity})
    return {'schema':'hermes_0222_npm_catalog_v1','lock_sha256':sha(raw),'packages':len(row['packages']),
            'archives':archives,'workspace_links':links,'target_platform_resolution':'NOT_RUN','installation_verified':False}


class References(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.refs=[]
    def handle_starttag(self,tag,attrs):
        need(len({k for k,v in attrs})==len(attrs) and tag!='base','asset')
        d=dict(attrs)
        if tag=='script' and 'src' in d:self.refs.append(d['src'])
        if tag=='link' and d.get('rel') in ('stylesheet','modulepreload','icon'):self.refs.append(d.get('href',''))


def inspect_web(root):
    """Enumerate ONLY the new owned web_dist, using retained no-follow dir FDs.

    Asset presence/hash consistency is not browser execution or network safety.
    No symlinks/hardlinks, external roots, executable invocation or HTML output.
    """
    need(root_ok(root),'path');fds=[];rows=[];total=0;index=None;nodes=0;directories=0
    directory_flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    try:
        fd=os.open('/',directory_flags);fds.append(fd)
        for component in PurePosixPath(root+'/sdk/hermes_cli/web_dist').parts[1:]:
            fd=os.open(component,directory_flags,dir_fd=fd);fds.append(fd)
        def stamp(s):return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
        def walk(dfd,prefix,depth):
            nonlocal total,index,nodes,directories
            directories+=1;need(directories<=256,'limit')
            need(depth<=12,'limit');before=os.fstat(dfd)
            names=[]
            with os.scandir(dfd) as entries:
                for entry in entries:
                    names.append(entry.name);need(len(names)<=512,'limit')
            nodes+=len(names)
            need(len(names)<=512 and nodes<=1024,'limit')
            need(len({n.casefold() for n in names})==len(names),'path')
            for name in sorted(names):
                rel=prefix+name;need(relative(rel) and '/' not in name,'path')
                s=os.stat(name,dir_fd=dfd,follow_symlinks=False)
                if stat.S_ISDIR(s.st_mode):
                    child=os.open(name,directory_flags,dir_fd=dfd)
                    try:
                        need(stamp(os.fstat(child))==stamp(s),'drift');walk(child,rel+'/',depth+1)
                        need(stamp(os.fstat(child))==stamp(os.stat(name,dir_fd=dfd,follow_symlinks=False)),'drift')
                    finally:os.close(child)
                else:
                    need(stat.S_ISREG(s.st_mode) and s.st_nlink==1,'asset')
                    need(len(rows)<512 and 0<s.st_size<=32*1024**2 and total+s.st_size<=128*1024**2,'limit')
                    h=hashlib.sha256();chunks=[];size=0
                    filefd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
                    try:
                        need(stamp(os.fstat(filefd))==stamp(s),'drift')
                        while True:
                            data=os.read(filefd,min(262144,s.st_size-size+1))
                            if not data:break
                            size+=len(data);need(size<=s.st_size,'limit');h.update(data)
                            if rel=='index.html':need(size<=1024**2,'limit');chunks.append(data)
                        need(size==s.st_size and stamp(os.fstat(filefd))==stamp(s)==stamp(os.stat(name,dir_fd=dfd,follow_symlinks=False)),'drift')
                    finally:os.close(filefd)
                    total+=size;rows.append({'path':rel,'bytes':size,'sha256':h.hexdigest()})
                    if rel=='index.html':index=b''.join(chunks)
            need(stamp(os.fstat(dfd))==stamp(before),'drift')
        walk(fd,'',0)
        need(index is not None and len(rows)>=2,'asset');parser=References();parser.feed(index.decode('utf-8'));parser.close()
        byname={r['path']:r for r in rows};need(len({p.casefold() for p in byname})==len(byname),'path')
        need(1<=len(parser.refs)<=128,'asset');refs=[]
        for ref in parser.refs:
            need(type(ref) is str and not ref.startswith('//') and not any(c in ref for c in ('%',':','?','#','\\')),'path')
            name=ref[1:] if ref.startswith('/') else ref
            need(relative(name) and name in byname,'asset');refs.append(name)
        return {'schema':'hermes_0222_built_web_inventory_v1','files':rows,'total_bytes':total,'entry_references':refs,
                'browser_verified':False,'network_containment_proven':False}
    except Refused:raise
    except Exception:raise Refused('asset') from None
    finally:
        failed=False
        for fd in reversed(fds):
            try:os.close(fd)
            except BaseException:failed=True
        if failed:raise Refused('asset') from None
