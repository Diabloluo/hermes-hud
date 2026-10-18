"""Pinned source projection and fixed diagnostics, never SDK execution or I/O."""
from pathlib import PurePosixPath
import re
from pm_handoff import HOST_COMMIT, Refused as HandoffRefused, decode, need, relative
from artifact_stage import Refused as ArtifactRefused
from remote_contract import Refused as RemoteRefused

ROOTS=('acp_adapter','agent','tools','hermes_cli','gateway','tui_gateway','cron',
       'plugins','providers','hermes_platform','pm','scripts','web','apps/shared',
       'assets','skills','locales','native')
REQUIRED=frozenset(('pyproject.toml','uv.lock','setup.py','README.md','LICENSE',
    'package.json','package-lock.json','pm/cli.py','hermes_cli/main.py',
    'hermes_cli/web_server.py','hermes_platform/host/runtime.py','web/package.json',
    'scripts/build/web.mjs','scripts/build/frontend-common.mjs','scripts/build/freshness.mjs',
    'web/public/favicon.ico','apps/shared/package.json'))
SITES=frozenset(('phase','root','claim','npm_config','synthetic_config','sdk_catalog',
    'sdk_checkout','sdk_stage','product_checkout','product_stage','tool_read',
    'tool_stage','plugin_projection','plugin_write','source_verify','complete'))
KINDS=frozenset(('refused','io','internal'))

def selected(name):
    parts=name.split('/')
    return ('/' not in name or any(name.startswith(r+'/') for r in ROOTS)
        or (len(parts)==3 and parts[0]=='apps' and parts[2]=='package.json')
        or name in ('ui-tui/package.json','tests-js/package.json')
        or (len(parts)==4 and parts[:2]==['ui-tui','packages'] and parts[3]=='package.json'))

def catalog(raw):
    c=decode(raw)
    need(type(c) is dict and set(c)=={'schema','commit','pathspecs','files'} and
         c['schema']=='hermes_0222_sdk_source_selection_v1' and c['commit']==HOST_COMMIT,'schema')
    rows=c['files'];need(type(rows) is list and 1<=len(rows)<=4096,'schema')
    names=set();folded=set();total=0
    for r in rows:
        need(type(r) is dict and set(r)=={'path','mode','blob','bytes'},'schema')
        n=r['path'];need(relative(n) and '\\' not in n and '.git' not in PurePosixPath(n).parts
                        and selected(n) and n.casefold() not in folded,'path')
        need(r['mode'] in ('100644','100755') and type(r['blob']) is str
             and re.fullmatch('[a-f0-9]{40}',r['blob']) is not None and
             type(r['bytes']) is int and 0<=r['bytes']<=512*1024**2,'schema')
        names.add(n);folded.add(n.casefold());total+=r['bytes'];need(total<=1024**3,'schema')
    need(REQUIRED<=names and [r['path'] for r in rows]==sorted(names),'binding')
    need(all(any(n.startswith(root+'/') for n in names) for root in ROOTS),'binding')
    specs=set(ROOTS)
    specs.update(n for n in names if not any(n.startswith(r+'/') for r in ROOTS))
    need(type(c['pathspecs']) is list and c['pathspecs']==sorted(specs)
         and len(specs)<=256 and all(re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',x) is not None for x in specs),'binding')
    return c

def listing(raw, c=None):
    """Validate the whole selected listing before any working-file open.

    Metadata is capped at the existing 4 MiB and 8192-file limits. Literal Git
    pathspecs are used by the caller, never a permissive glob/fallback scan.
    """
    need(type(raw) is bytes and len(raw)<=4*1024**2,'schema')
    records=raw.split(b'\0');need(records[-1]==b'' and 0<len(records)-1<=8192,'schema')
    result=[];seen=set()
    for record in records[:-1]:
        meta,name=record.split(b'\t',1);mode,kind,h=meta.decode('ascii').split();name=name.decode('utf-8')
        need(relative(name) and '\\' not in name and '.git' not in PurePosixPath(name).parts
             and kind=='blob' and mode in ('100644','100755','120000')
             and re.fullmatch('[a-f0-9]{40}',h) is not None and name.casefold() not in seen,'path')
        seen.add(name.casefold());result.append((name,mode,h))
    if c is not None:
        expected={r['path']:(r['mode'],r['blob']) for r in c['files']}
        need({n:(m,h) for n,m,h in result}==expected,'binding')
    return result

def diagnostic(site, exc):
    site=site if type(site) is str and site in SITES else 'phase'
    kind='refused' if isinstance(exc,(HandoffRefused,ArtifactRefused,RemoteRefused)) else ('io' if isinstance(exc,OSError) else 'internal')
    return {'version':1,'site':site,'kind':kind}

def valid_diagnostic(row):
    return (type(row) is dict and set(row)=={'version','site','kind'} and
            type(row['version']) is int and row['version']==1 and type(row['site']) is str and
            row['site'] in SITES and type(row['kind']) is str and row['kind'] in KINDS)
