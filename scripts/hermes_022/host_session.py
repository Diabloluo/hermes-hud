"""Parent host/HTTP/WS/stop composition. No installer, grant or native CLI.

The fixed bounded_io and api_checks modules are reused, not a global-network
fallback. Import them only from the reviewed tool bundle. The resulting safe
record is NOT final acceptance: a bound child seal and source/guard records
must still be checked by the eventual top-level executor.
"""
import asyncio
import re
from bounded_io import Budget,LoopbackHTTP
from api_checks import PluginChecks
from owned_process import Refused,need


async def run(parent,port,token,deadline,source_check,request_stop,*,checks_factory=None,child_ready=None):
    row={'schema':'hermes_0222_parent_host_session_v1','result':'FAIL','error':None,
         'http':None,'ws':None,'cleanup':None,'source_unchanged':False,
         'child_seal_verified':False,'native_acceptance':False,'memory':'WARN_NOT_ACCEPTED','public_release':'BLOCK'}
    if parent.used or getattr(parent,'session_used',False):
        row['error']='consumed';return row
    parent.session_used=True
    stage='input';before=None
    try:
        need(type(port) is int and 1024<=port<=65535 and port!=9119,'plan')
        need(type(token) is str and re.fullmatch('[A-Za-z0-9_-]{32,128}',token) is not None,'plan')
        need(parent.plan['env']['HERMES_DASHBOARD_SESSION_TOKEN']==token and callable(source_check)
             and callable(request_stop),'plan')
        stage='source_start';before=source_check()
        need(type(before) is str and re.fullmatch('[a-f0-9]{64}',before) is not None,'plan')
        stage='spawn';started=parent.start(deadline)
        need(started['result']=='HANDLE_BOUND_NOT_ACCEPTANCE','spawn')
        stage='ready';ready_deadline=min(deadline,parent.clock()+60)
        while not (parent.listener(port) and (child_ready is None or child_ready())):
            parent.remaining();need(parent.clock()<ready_deadline,'budget')
            await parent.sleep(min(0.1,parent.remaining()))
        # Ownership is checked before and after each network operation by Budget.
        budget=Budget(parent.clock,deadline,lambda:parent.listener(port))
        checks=(checks_factory(port,budget) if checks_factory is not None
                else PluginChecks(port,budget,LoopbackHTTP(port,budget)))
        stage='http';row['http']=await checks.http_once('auth_ok',token)
        need(row['http']['result']=='EXPECTED_RESPONSE_ONLY','exit')
        stage='ws';row['ws']=await checks.ws_once('auth_ok',token)
        need(row['ws']['result']=='EXPECTED_RESPONSE_ONLY','exit')
        parent.check()
    except BaseException:row['error']=stage
    finally:
        # Even metadata/source failures after spawn retain and clean the handle.
        try:row['cleanup']=await parent.close(request_stop)
        except BaseException:row['cleanup']={'result':'FAIL','cleanup_error':'cleanup'}
        try:row['source_unchanged']=before is not None and source_check()==before
        except BaseException:row['source_unchanged']=False
    clean=row['cleanup']
    if row['error'] is None and (clean['result']!='EXIT_OBSERVED_NOT_ACCEPTANCE' or clean['exit_code']!=0):row['error']='cleanup'
    if row['error'] is None and not row['source_unchanged']:row['error']='source_end'
    if row['error'] is None:row['result']='HTTP_WS_AND_EXIT_OBSERVED_NOT_ACCEPTANCE'
    return row


if __name__=='__main__':raise SystemExit('FRESH_AUTHORIZED_PARENT_ASSEMBLY_REQUIRED')
