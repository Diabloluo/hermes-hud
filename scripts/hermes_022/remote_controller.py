"""Private single dispatch, inert until fresh on-disk user authorization exists.

Do not publish local authorization/claim/receipt files. This controller verifies
the remote freeze bytes before consuming its exclusive claim. API uncertainty
never causes a retry. A new GitHub dispatch by a third party is not prevented.
"""
import base64
import os
from pathlib import Path
import subprocess
import sys
import time
HERE=str(Path(__file__).resolve().parent)
if __name__=='__main__':sys.path.insert(0,HERE)
from remote_contract import need,sha,encode,authorize,REPO,BRANCH
from remote_files import read
from remote_entry import frozen
from pm_handoff import decode

def local_claim(name,data):
    # Only fixed names at this reviewed controller's HERE.
    need(name in ('REMOTE_DISPATCH_CLAIM.json','REMOTE_DISPATCH_RECEIPT.json'))
    with open(HERE+'/'+name,'xb') as stream:
        stream.write(encode(data));stream.flush();os.fsync(stream.fileno())

def main():
    need(sys.flags.isolated==1 and sys.flags.dont_write_bytecode==1 and sys.flags.optimize==0)
    auth=decode(read(HERE+'/REMOTE_AUTHORIZATION.json'))
    accepted=decode(read(HERE+'/REMOTE_REVIEW_ACCEPTANCE.json'))
    freeze_raw=read(HERE+'/REMOTE_FREEZE.json');report=read(HERE+'/REVIEW.md')
    frozen(HERE,sha(freeze_raw))
    # This is local schema/expiry validation, not a fabricated remote observation.
    context={'GITHUB_REPOSITORY':REPO,'GITHUB_REF':'refs/heads/'+BRANCH,'GITHUB_SHA':auth['sha'],
             'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'1'}
    def check():authorize(auth,accepted,sha(freeze_raw),sha(report),context,time.time())
    check()
    def get(endpoint):
        r=subprocess.run(['gh','api',endpoint],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL,timeout=30,check=False)
        need(r.returncode==0 and len(r.stdout)<=2*1024**2);return decode(r.stdout)
    need(get('repos/'+REPO+'/git/ref/heads/'+BRANCH)['object']['sha']==auth['sha'])
    remote=get('repos/'+REPO+'/contents/scripts/hermes_022/REMOTE_FREEZE.json?ref='+auth['sha'])
    need(remote['encoding']=='base64' and base64.b64decode(remote['content'],validate=False)==freeze_raw)
    workflow=get('repos/'+REPO+'/contents/.github/workflows/hermes-022-isolated.yml?ref='+auth['sha'])
    need(workflow['encoding']=='base64' and base64.b64decode(workflow['content'],validate=False)
         ==read(HERE+'/DRAFT_REMOTE_WORKFLOW.yml'))
    check()
    local_claim('REMOTE_DISPATCH_CLAIM.json',{'grant':auth['grant'],'sha':auth['sha'],
         'state':'CONSUMED_ONCE_NO_RETRY_EVEN_IF_OUTCOME_UNKNOWN','freeze_sha256':sha(freeze_raw)})
    inputs={'reviewed_sha':auth['sha'],'authorization_b64':base64.b64encode(encode(auth)).decode(),
            'acceptance_b64':base64.b64encode(encode(accepted)).decode()}
    state='OUTCOME_UNKNOWN_NO_RETRY'
    try:
        r=subprocess.run(['gh','api','--method','POST','repos/'+REPO+
             '/actions/workflows/hermes-022-isolated.yml/dispatches','--input','-'],
             input=encode({'ref':BRANCH,'inputs':inputs}),stdout=subprocess.DEVNULL,
             stderr=subprocess.DEVNULL,timeout=30,check=False)
        if r.returncode==0:state='API_ACKNOWLEDGED_NOT_EXECUTION_PASS'
    except BaseException:pass
    local_claim('REMOTE_DISPATCH_RECEIPT.json',{'grant':auth['grant'],'state':state,'retry':False,
                'memory':'WARN_NOT_ACCEPTED','public_release':'BLOCK'})
    return 0 if state=='API_ACKNOWLEDGED_NOT_EXECUTION_PASS' else 2

if __name__=='__main__':
    try:code=main()
    except BaseException:code=2
    raise SystemExit(code)
