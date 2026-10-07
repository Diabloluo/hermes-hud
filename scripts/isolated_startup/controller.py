"""Private single dispatch definition. No gates materialized during preparation."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import require,read,digest,atomic
from lifecycle import SCHEMA,SCOPE,authority_valid

HERE=Path(__file__).resolve().parent
REPORT='WORKBUDDY_REMOTE_SHORT_STARTUP_OPTIONAL_PROCESS_REVIEW.md'


def gates(a,accepted,freeze,report,now):
    require(type(a) is dict and set(a)=={'schema','id','scope','freeze_sha256','review_sha256',
             'issued','expires','max_runs','owner_confirmed','sha','repository','branch'},'authority')
    run={k:v for k,v in a.items() if k not in ('sha','repository','branch')}
    require(authority_valid(run,now,freeze,report) and re.fullmatch('[a-f0-9]{40}',a['sha']) is not None
            and a['repository']=='Diabloluo/hermes-hud'
            and a['branch']=='test/v2-isolated-memory-20261003','authority')
    require(accepted=={'schema':'hud_short_review_acceptance_v1','sha':a['sha'],
            'freeze_sha256':freeze,'report_sha256':report,'safety':'PASS','scope':SCOPE},'authority')


def main():
    a=read(HERE/'AUTHORIZATION.json')
    accepted=read(HERE/'REVIEW_ACCEPTANCE.json')
    freeze=digest(HERE/'FREEZE.json');report=digest(HERE/REPORT)
    gates(a,accepted,freeze,report,time.time())
    check=subprocess.run(['gh','api',f"repos/{a['repository']}/git/ref/heads/{a['branch']}",
                          '--jq','.object.sha'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                         timeout=20,check=True)
    require(check.stdout.decode().strip()==a['sha'],'authority')
    # Refresh expiry AFTER remote read; never consume/POST a grant expired in transit.
    gates(a,accepted,freeze,report,time.time())
    with (HERE/'DISPATCH_CLAIM.json').open('x') as stream:
        json.dump({'id':a['id'],'state':'CONSUMED_ONCE_NO_RETRY_EVEN_IF_OUTCOME_UNKNOWN',
                   'sha':a['sha'],'freeze':freeze},stream)
    payload={'ref':a['branch'],'inputs':{'reviewed_sha':a['sha'],'reviewed_freeze':freeze,
          'reviewed_report':report,'authorization_id':a['id'],
          'issued':str(a['issued']),'expires':str(a['expires'])}}
    status='OUTCOME_UNKNOWN_NO_RETRY'
    try:
        r=subprocess.run(['gh','api','--method','POST',
             f"repos/{a['repository']}/actions/workflows/fresh-install.yml/dispatches",'--input','-'],
             input=json.dumps(payload).encode(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
             timeout=30,check=False)
        if r.returncode==0:status='API_ACKNOWLEDGED_NOT_EXECUTION_PASS'
    except BaseException:pass
    atomic(HERE/'DISPATCH_RECEIPT.json',{'id':a['id'],'state':status,'retry':False,
                                      'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK'})
    return 0 if status=='API_ACKNOWLEDGED_NOT_EXECUTION_PASS' else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except SystemExit:raise
    except BaseException:raise SystemExit(2) from None
