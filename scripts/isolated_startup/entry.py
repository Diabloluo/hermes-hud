"""Remote-only single setup/run; inert on import. No retry, production or release."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import venv

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import require,read,digest,atomic,HEX
from lifecycle import authority_valid,execute_model_io,SCHEMA,SCOPE
from native_io import NativeIO

HERE=Path(__file__).resolve().parent
FILES=('boundary_policy.py','audit_adapter.py','failure_projection.py','guard_stack.py',
       'lifecycle.py','analyze_integration.py','common.py','fixture.py','identity_contract.py',
       'source_contract.py','native_io.py','observer_smoke.py','entry.py','controller.py',
       'SOURCE_MANIFEST.json','PROTOCOL.json','PROTOCOL.md','DRAFT_WORKFLOW.yml',
       'test_repair.py','test_integration.py','test_backend.py','readback.py',
       'test_exit_status.py','EXIT_STATUS_REPAIR.md')


def freeze_check(expected):
    require(type(expected) is str and HEX.fullmatch(expected) is not None
            and digest(HERE/'FREEZE.json')==expected,'prepared')
    value=read(HERE/'FREEZE.json')
    require(type(value) is dict and set(value)=={'schema','files'}
            and value['schema']=='hud_remote_short_tool_freeze_v1'
            and type(value['files']) is dict and set(value['files'])==set(FILES),'prepared')
    require(all(digest(HERE/n)==value['files'][n] for n in FILES),'prepared')
    return True


def workflow_authority(env,sha,grant,issued,expires,review,now):
    require(env.get('GITHUB_ACTIONS')=='true' and env.get('GITHUB_REPOSITORY')=='Diabloluo/hermes-hud'
            and env.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and env.get('GITHUB_RUN_ATTEMPT')=='1'
            and env.get('GITHUB_REF')=='refs/heads/test/v2-isolated-memory-20261003'
            and type(sha) is str and re.fullmatch('[a-f0-9]{40}',sha) is not None
            and env.get('GITHUB_SHA')==sha and re.fullmatch('[a-f0-9]{32}',grant) is not None
            and HEX.fullmatch(review) is not None,'authority')
    probe={'schema':SCHEMA,'id':grant,'scope':SCOPE,'freeze_sha256':'0'*64,
           'review_sha256':review,'issued':issued,'expires':expires,'max_runs':1,'owner_confirmed':True}
    require(authority_valid(probe,now,'0'*64,review),'authority')


def remote_gate(args):
    workflow_authority(os.environ,args.sha,args.grant,args.issued,args.expires,args.review,time.time())
    require(sys.platform=='darwin' and sys.version_info[:2]==(3,13),'prepared')
    require(Path(os.environ['GITHUB_WORKSPACE']).resolve()==HERE.parents[1],'prepared')
    require(digest(HERE.parents[1]/'.github/workflows/fresh-install.yml')==digest(HERE/'DRAFT_WORKFLOW.yml'),'prepared')
    return freeze_check(args.freeze)


def setup(args):
    remote_gate(args)
    begun=time.monotonic()
    root=Path(os.environ['RUNNER_TEMP']).resolve()/'hud-short-startup-owned'
    require(not root.exists() and not root.is_symlink(),'claim')
    root.mkdir()
    # Distinct fresh grant. Setup failure still consumes; this directory is not
    # an old pair root and cannot be repaired or reused for a second attempt.
    with (root/'SETUP_CLAIM.json').open('x') as stream:
        json.dump({'id':args.grant,'state':'CONSUMED_ONCE_NO_RETRY','sha':args.sha,
                   'freeze':args.freeze,'review':args.review},stream)
    authority={'schema':SCHEMA,'id':args.grant,'scope':SCOPE,'freeze_sha256':args.freeze,
               'review_sha256':args.review,'issued':args.issued,'expires':args.expires,
               'max_runs':1,'owner_confirmed':True}
    atomic(root/'authority.json',authority)
    try:
        venv.EnvBuilder(with_pip=True).create(root/'venv')
        remaining=1800-(time.monotonic()-begun)
        require(remaining>0,'budget')
        env={'HOME':str(root),'TMPDIR':str(root),'PATH':'/usr/bin:/bin:/usr/sbin:/sbin',
             'LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1','PIP_DISABLE_PIP_VERSION_CHECK':'1'}
        subprocess.run([str(root/'venv/bin/python'),'-I','-B','-m','pip','install',
                        'hermes-agent==0.19.0','psutil==7.2.2','websockets==15.0.1'],
                       env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       timeout=remaining,check=True)
        require(time.monotonic()-begun<1800,'budget')
        atomic(root/'setup.json',{'result':'PASS','id':args.grant,'sha':args.sha,
              'freeze':args.freeze,'review':args.review,'seconds':time.monotonic()-begun})
    except BaseException:
        atomic(root/'setup.json',{'result':'FAIL','error':'setup_failed','retry':False})
        raise SystemExit(2) from None


def run(args):
    remote_gate(args)
    root=Path(os.environ['RUNNER_TEMP']).resolve()/'hud-short-startup-owned'
    setup_record=read(root/'setup.json');claim=read(root/'SETUP_CLAIM.json')
    require(setup_record.get('result')=='PASS' and setup_record.get('id')==args.grant
            and setup_record.get('sha')==args.sha and setup_record.get('freeze')==args.freeze
            and setup_record.get('review')==args.review and claim=={'id':args.grant,
            'state':'CONSUMED_ONCE_NO_RETRY','sha':args.sha,'freeze':args.freeze,'review':args.review},'authority')
    authority=read(root/'authority.json')
    require(authority_valid(authority,time.time(),args.freeze,args.review)
            and authority['id']==args.grant,'authority')
    io=NativeIO(root,HERE.parents[1],args.grant,args.freeze,freeze_check)
    try:
        payload,seal=execute_model_io(io,authority,args.freeze,args.review)
        return 0 if seal is not None and seal['verdict']=='PASS' else 2
    finally:io.release()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('setup','run'))
    for name in ('sha','freeze','grant','review'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--issued',type=float,required=True)
    parser.add_argument('--expires',type=float,required=True)
    args=parser.parse_args()
    return setup(args) if args.mode=='setup' else run(args)


if __name__=='__main__':
    try:raise SystemExit(main())
    except SystemExit:raise
    except BaseException:
        # Fixed console fallback. Never print authority/token/stack/env/path.
        print('{"result":"FAIL","scope":"DIAGNOSTIC_ONLY_NOT_VERIFIED","retry":false}')
        raise SystemExit(2) from None
