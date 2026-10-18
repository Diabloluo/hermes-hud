"""Remote workflow entry. Missing review/new authority is a hard refusal.

No current authorization is distributed with preparation. Inputs are public
binding metadata, not service credentials. GitHub metadata is not attestation.
"""
import asyncio
import base64
import os
from pathlib import Path
import platform
import sys
import time

HERE=str(Path(__file__).resolve().parent)
if __name__=='__main__':sys.path.insert(0,HERE)
from remote_contract import need,sha,encode,authorize,platform_gate,hexstr
from remote_files import read
from pm_handoff import decode,relative

def frozen(here,expected):
    raw=read(here+'/REMOTE_FREEZE.json');need(sha(raw)==expected)
    row=decode(raw);need(set(row)=={'schema','files'} and row['schema']=='hermes_0222_remote_freeze_v1')
    files=row['files'];need(type(files) is dict and 25<=len(files)<=64)
    required={'remote_entry.py','remote_backend.py','remote_contract.py','remote_files.py','remote_install.py',
              'remote_pm_entry.py','official_entry.py','child_runtime.py','child_guard.py','child_execution.py',
              'child_protocol.py','server_bridge.py','retained_mailbox.py','pm_handoff.py','runtime_fence.py',
              'guard_stack.py','audit_adapter.py','boundary_policy.py','optional_process.py','owned_process.py',
              'install_parent.py','host_session.py','sealed_session.py','bounded_io.py','api_checks.py',
              'installed_closure.py','plugin_handoff.py','install_completion.py','web_preparation.py','artifact_stage.py',
              'DRAFT_REMOTE_WORKFLOW.yml','remote_controller.py','runtime_aliases.py'}
    need(set(files)==required)
    for name,h in files.items():
        need(relative(name) and '/' not in name and hexstr(h,64) and sha(read(here+'/'+name))==h)
    return row

def input_json(env,name):
    text=env.get(name);need(type(text) is str and 0<len(text)<=16384)
    raw=base64.b64decode(text,validate=True);need(base64.b64encode(raw).decode()==text)
    return decode(raw)

def export_safe(row):
    """No caller-controlled artifact path, no append/overwrite, no raw records."""
    from remote_contract import validate_aggregate
    need(validate_aggregate(row) and len(encode(row))<=16384)
    path='/private/tmp/hermes-022-safe-output'
    os.mkdir(path,0o700)
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    out=None
    try:
        out=os.open('analysis.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
        data=encode(row);offset=0
        while offset<len(data):
            n=os.write(out,data[offset:]);need(n>0);offset+=n
        os.fsync(out);os.fsync(fd)
    finally:
        if out is not None:os.close(out)
        os.close(fd)

def main():
    env=dict(os.environ)
    platform_gate(env,sys.platform,platform.machine(),platform.mac_ver()[0])
    need(sys.flags.isolated==1 and sys.flags.dont_write_bytecode==1 and sys.flags.optimize==0
         and sys.version_info[:3]==(3,14,7) and os.path.realpath(__file__)==HERE+'/remote_entry.py')
    auth=input_json(env,'HUD_AUTHORIZATION_B64');accepted=input_json(env,'HUD_ACCEPTANCE_B64')
    freeze=frozen(HERE,auth['freeze_sha256']);report=read(HERE+'/REVIEW.md')
    claim=authorize(auth,accepted,auth['freeze_sha256'],sha(report),env,time.time())
    need(env.get('REVIEWED_SHA')==auth['sha'])
    root='/private/tmp/hermes-022-run-'+auth['grant']
    workspace=env.get('GITHUB_WORKSPACE');need(type(workspace) is str and workspace.startswith('/')
        and os.path.realpath(workspace)==workspace)
    need(sha(read(workspace+'/reviewed/.github/workflows/hermes-022-isolated.yml'))
         ==freeze['files']['DRAFT_REMOTE_WORKFLOW.yml'])
    from remote_backend import Backend,execute
    result=asyncio.run(execute(Backend(HERE,root,workspace,auth,freeze,report,claim)))
    export_safe(result)
    return 0 if result['result']=='PASS' else 2

if __name__=='__main__':
    try:code=main()
    except BaseException:code=2
    raise SystemExit(code)
