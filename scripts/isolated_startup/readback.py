"""Exact actual-file hash readback only; no authority/host/DB/production IO."""
import hashlib
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import entry
import source_contract
from common import read,digest,require

WORKSPACE=HERE.parents[1]
REPO=WORKSPACE/'work/remote-memory-identity-delivery-20261004'
SITE=WORKSPACE/'work/hermes-release-venv/lib/python3.11/site-packages'
# Manifest selection is a pre-hook fixed metadata read, not a source-tree scan.
MANIFEST=read(HERE/'SOURCE_MANIFEST.json')
require(source_contract.manifest_valid(MANIFEST),'source')
ALLOW={HERE/n for n in entry.FILES}|{HERE/'FREEZE.json'}
ALLOW|={REPO/row['name'] for row in MANIFEST['candidate']}
ALLOW|={SITE/row['name'] for row in MANIFEST['public']}
ATTEMPTS={'process':0,'network':0,'sqlite':0,'signal':0,'write':0,'outside_open':0}
OPENS=[]

def audit(event,args):
    kind=('process' if event.startswith('subprocess.') or event in
          {'os.system','os.exec','os.fork','os.posix_spawn'} else
          'network' if event.startswith('socket.') else
          'sqlite' if event.startswith('sqlite3.') else
          'signal' if event in {'os.kill','os.killpg'} else None)
    if kind:ATTEMPTS[kind]+=1;raise RuntimeError('READBACK_ONLY')
    if event=='open':
        path,mode,flags=args
        if type(path) is not str or Path(path) not in ALLOW:
            ATTEMPTS['outside_open']+=1;raise RuntimeError('READBACK_ONLY')
        if mode not in ('r','rb') or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            ATTEMPTS['write']+=1;raise RuntimeError('READBACK_ONLY')
        OPENS.append(path)

def main(expected):
    sys.addaudithook(audit)
    require(entry.freeze_check(expected) is True,'prepared')
    manifest=read(HERE/'SOURCE_MANIFEST.json')
    candidate=source_contract.group_hash(manifest['candidate'],REPO)
    public=source_contract.group_hash(manifest['public'],SITE)
    final=digest(HERE/'FREEZE.json')
    require(final==expected and not any(ATTEMPTS.values()),'prepared')
    print(json.dumps({'result':'MATCH','freeze_sha256':final,'tool_files':len(entry.FILES),
        'candidate_files':16,'public_files':5,'open_count':len(OPENS),
        'unique_open_paths':len(set(OPENS)),'allowed_paths':len(ALLOW),
        'candidate_group_sha256':candidate,'public_group_sha256':public,
        'attempts_after_preload':ATTEMPTS,'executable':sys.executable,'python_version':sys.version,
        'scope':'TRUE_FREEZE_CHECK_AND_GROUP_HASH_EXACT_FILES_ONLY',
        'preload_not_covered':True,'native_execution':'NOT_RUN',
        'authority_execution':'NOT_RUN','synthetic_home_db_read':False},sort_keys=True))

if __name__=='__main__':
    main(sys.argv[1])
