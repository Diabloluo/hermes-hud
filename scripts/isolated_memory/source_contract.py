"""Exact candidate/public/owned-seed digests; no recursive source-tree scan."""
import hashlib
import json
from pathlib import Path,PurePosixPath

from common import require,bounded,HEX

FIXTURE_FILES=('state.db','job-ledger/jobs.jsonl','config.yaml','cron/jobs.json')
PUBLIC_NAMES={'hermes_constants.py','hermes_cli/main.py','hermes_cli/config.py',
              'hermes_cli/web_server.py','hermes_state.py'}


def manifest_valid(value):
    if not(type(value) is dict and set(value)=={'schema','candidate_commit','candidate','public','public_version','scope'}
           and value['schema']=='hud_short_source_manifest_v1'
           and value['candidate_commit']=='c9f90b3ca0559221859f26bb2e35da9c2e72116d'
           and value['public_version']=='0.19.0'
           and value['scope']=='EXACT_CANDIDATE_RUNTIME_AND_FIVE_PUBLIC_FILES_NOT_FULL_DEPENDENCY_CLOSURE'):
        return False
    for group,count in (('candidate',16),('public',5)):
        rows=value[group]
        if type(rows) is not list or len(rows)!=count:return False
        seen=set()
        for row in rows:
            if not(type(row) is dict and set(row)=={'name','bytes','sha256'}
                   and type(row['name']) is str and len(row['name'])<=200
                   and not PurePosixPath(row['name']).is_absolute()
                   and '..' not in PurePosixPath(row['name']).parts
                   and str(PurePosixPath(row['name']))==row['name']
                   and type(row['bytes']) is int and 0<=row['bytes']<=2*1024*1024
                   and type(row['sha256']) is str and HEX.fullmatch(row['sha256'])):return False
            if row['name'] in seen:return False
            if group=='candidate' and not row['name'].startswith('dashboard/'):return False
            seen.add(row['name'])
        if group=='public' and seen!=PUBLIC_NAMES:return False
    return True


def group_hash(rows,root):
    rows_out=[]
    for row in rows:
        p=root/row['name']
        require(p.is_relative_to(root),'source')
        data=bounded(p)
        value=hashlib.sha256(data).hexdigest()
        require(len(data)==row['bytes'] and value==row['sha256'],'source')
        rows_out.append({'name':row['name'],'bytes':len(data),'sha256':value})
    return hashlib.sha256(json.dumps(sorted(rows_out,key=lambda x:x['name']),sort_keys=True).encode()).hexdigest()


def capture(manifest,repo,site,home):
    require(manifest_valid(manifest),'source')
    require(all(p.is_absolute() and p.resolve()==p for p in (repo,site,home)),'source')
    seed=[]
    for name in FIXTURE_FILES:
        data=bounded(home/name,64*1024*1024)
        seed.append({'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    return {'candidate':group_hash(manifest['candidate'],repo),
            'public_source':group_hash(manifest['public'],site),
            'fixture':hashlib.sha256(json.dumps(seed,sort_keys=True).encode()).hexdigest()}
