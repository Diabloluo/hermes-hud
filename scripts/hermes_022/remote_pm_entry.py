"""Actual PM child entry for a future authorized disposable VM, not host entry.

No Python-audit containment claim is made for installation. Native installers
are allowed only in the explicitly reviewed remote install stage. Host guards
are unchanged. This module never creates an authorization.
"""
import os
import platform
import sys
import time
from pathlib import PurePosixPath

def main(own):
    from remote_contract import need,encode,sha,SCOPE
    from remote_files import read,verify_rows,write_new
    from pm_handoff import decode
    from official_entry import environment,PM_ARGS,layout
    root=str(PurePosixPath(own).parent.parent);layout(root)
    need(own==root+'/tool/remote_pm_entry.py' and os.path.realpath(own)==own and os.getcwd()==root
         and sys.flags.isolated==1 and sys.flags.dont_write_bytecode==1 and sys.flags.optimize==0
         and sys.platform=='darwin' and platform.machine()=='x86_64' and sys.version_info[:3]==(3,14,7))
    need(dict(os.environ)==environment(root,'install'))
    config=decode(read(root+'/evidence/install-input.json'))
    claim=decode(read(root+'/evidence/REMOTE_CLAIM.json'))
    need(set(config)=={'schema','grant','scope','deadline_wall','files','source','interpreter'}
         and config['schema']=='hermes_0222_install_input_v1' and config['scope']==SCOPE
         and claim['scope']==SCOPE and claim['grant']==config['grant']
         and claim['state']=='CONSUMED_ONCE_NO_RETRY_EVEN_IF_OUTCOME_UNKNOWN'
         and time.time()<config['deadline_wall']<=time.time()+1800
         and os.path.realpath(sys.executable)==config['interpreter']
         and sha(encode(config['files']))==config['source'])
    verify_rows(root,config['files'])
    write_new(root,'evidence/PM_CONSUMED.json',encode({'grant':config['grant'],'state':'CONSUMED_ONCE_NO_RETRY'}))
    sys.path.insert(0,root+'/sdk')
    from pm.cli import main as pm_main
    code=pm_main(list(PM_ARGS))
    need(code is None or type(code) is int and code==0)
    need(time.time()<config['deadline_wall']);verify_rows(root,config['files'])
    return 0

if __name__=='__main__':
    try:
        own=os.path.abspath(__file__)
        if os.path.realpath(own)!=own:raise ValueError()
        sys.path.insert(0,str(PurePosixPath(own).parent))
        code=main(own)
    except BaseException:code=2
    raise SystemExit(code)
