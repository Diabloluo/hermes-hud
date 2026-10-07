"""One authorized finite pair. Import inert; native methods only behind entry gates."""
import asyncio
import json
from pathlib import Path
import time
import urllib.request
from common import atomic,read,require
from lifecycle import close_owned,identity_valid,child_valid,sources_valid,transport_valid
from native_io import NativeIO,port_valid
from identity_diagnostics import observe_handle,valid as diagnostic_valid
from pair_contract import PHASES,LABELS,LIMITS,error_code,checkpoint_valid,quality
import resource_diagnostics as resources
import execution_diagnostics as execution
import fixture
from pair_record import rows,encode,publish

def request(io,route):
    require(route in ('snapshot?locale=zh','snapshot?locale=en','snapshot?locale=fr',
        'snapshot?locale=ar','timeline?limit=100','usage?days=30','skills?locale=en')
        and port_valid(io.port),'http')
    raw=None
    try:
        req=urllib.request.Request(f'http://127.0.0.1:{io.port}/api/plugins/hermes-hud/'+route,
             headers={'X-Hermes-Session-Token':io.token})
        with io.opener.open(req,timeout=10) as response:
            raw=response.read(1048577)
            require(response.status==200 and 0<len(raw)<=1048576 and type(json.loads(raw)) is dict,'http')
    finally:raw=None

async def phase_set(io,label):
    io._phase_sequence+=1;sequence=io._phase_sequence
    atomic(io.out/'phase-control.json',{'id':io.grant,'phase':label,'sequence':sequence})
    begin=time.monotonic()
    while time.monotonic()-begin<10:
        io.check(io.proc,io.saved)
        if (io.out/'phase-ack.json').exists():
            ack=read(io.out/'phase-ack.json')
            if ack.get('sequence')==sequence:
                require(set(ack)=={'id','phase','sequence','at','state'} and ack['id']==io.grant
                    and ack['phase']==label and type(ack['sequence']) is int,'phase')
                return ack
        await asyncio.sleep(.05)
    require(False,'phase')

async def phase(io,label,seconds,load):
    from websockets.asyncio.client import connect
    await phase_set(io,label)
    begin=time.monotonic();counts={'http':0,'ws':0,'handshakes':0}
    async def socket_lane():
        raw=None
        try:
            io.check(io.proc,io.saved)
            url=f'ws://127.0.0.1:{io.port}/api/plugins/hermes-hud/events?locale=en&token={io.token}'
            async with connect(url,origin=f'http://127.0.0.1:{io.port}',proxy=None,
                open_timeout=10,close_timeout=2,max_size=1048576) as ws:
                counts['handshakes']+=1
                while time.monotonic()-begin<seconds:
                    raw=await asyncio.wait_for(ws.recv(),10);value=json.loads(raw)
                    require(type(value) is dict and type(value.get('schema_version')) is int
                        and value['schema_version']==1,'ws')
                    counts['ws']+=1;raw=None
        finally:raw=None
    lane=asyncio.create_task(socket_lane()) if load else None;tick=0
    try:
        while time.monotonic()-begin<seconds:
            at=time.monotonic();io.check(io.proc,io.saved)
            if lane and lane.done():
                await lane;require(False,'ws')
            if load:
                for route in ('snapshot?locale='+('zh','en','fr','ar')[tick%4],
                        'timeline?limit=100','usage?days=30','skills?locale=en'):
                    io.check(io.proc,io.saved);counts['http']+=1
                    # Synchronous bounded 10s IO; no detached worker may outlive cleanup.
                    request(io,route)
                tick+=1
            await asyncio.sleep(max(.01,2-(time.monotonic()-at)))
    finally:
        if lane:
            if not lane.done():lane.cancel()
            try:await lane
            except asyncio.CancelledError:pass
    io.check(io.proc,io.saved)
    ack=read(io.out/'phase-ack.json')
    require(ack['phase']==label and ack['id']==io.grant,'phase')
    return {'label':label,'seconds':seconds,'start':begin,'end':time.monotonic(),
            **counts,'state':ack['state']}

async def operation(io,label,seq):
    await phase_set(io,'checkpoint')
    begin=time.monotonic()
    atomic(io.out/'operation.json',{'id':io.grant,'label':label,'sequence':seq,'at':begin})
    done=None
    while time.monotonic()-begin<30:
        io.check(io.proc,io.saved)
        if done is None and (io.out/'operation-done.json').exists():
            ack=read(io.out/'operation-done.json')
            if ack.get('sequence')==seq:
                require(set(ack)=={'id','sequence','seconds'} and ack['id']==io.grant
                    and type(ack['sequence']) is int and type(ack['seconds']) in (int,float)
                    and 0<=ack['seconds']<30,'operation')
                done=time.monotonic()
        await asyncio.sleep(.1)
    require(done is not None and 0<=done-begin<30,'operation')
    cp=read(io.out/f'checkpoint-{seq}.json')
    require(checkpoint_valid(cp,io.arm,seq),'checkpoint')
    return {'sequence':seq,'label':label,'at':begin,'observed_seconds':done-begin,
            'window_seconds':time.monotonic()-begin,'checkpoint':cp}

async def run_arm(io):
    started=io.clock();proc=expected=None;stage='authority'
    r={'arm':io.arm,'candidate':'FAIL','error':None,'failure_diagnostic':None,
       'seconds':None,'resource':None,'identity_diagnostic':None,'cleanup':None,'handle':None,
       'child':None,'source_start':None,'source_end':None,'fixture':None,'counts_end':None,
       'phases':[],'operations':[],'samples':[],'smoke':None}
    def note(where,error):
        if r['error'] is None:
            r['error']=error_code(error)
            r['failure_diagnostic']=execution.project(where,error)
    try:
        require(io.authorized() is True,'authority')
        stage='active';require(io.no_active() is True,'active')
        stage='resource';r['resource']=None
        try:ok=io.resources()
        finally:r['resource']=io.resource_diagnostic()
        require(ok is True and resources.passed(r['resource']),'resource')
        stage='claim';io.claim(io.grant)
        stage='initialize';io.initialize()
        stage='fixture_read';r['fixture']=read(io.out/'fixture.json')
        stage='source_start';r['source_start']=io.sources()
        stage='phase_control';atomic(io.out/'phase-control.json',{'id':io.grant,'phase':'startup','sequence':0})
        io._phase_sequence=0
        stage='spawn';proc=io.spawn()
        stage='expected';expected=io.expected(proc)
        stage='identity';io.check(proc,expected)
        stage='ready';io.ready(proc,expected)
        stage='ack_ready';io.acknowledge('ready')
        stage='http_smoke';io.http_once()
        stage='ack_http';io.acknowledge('http')
        stage='ws_smoke';await io.ws_once_async()
        stage='ack_ws';io.acknowledge('ws')
        stage='transport';r['smoke']=io.transport()
        seq=0
        for label,seconds,load in PHASES:
            stage='phase';record=await phase(io,label,seconds,load);r['phases'].append(record)
            stage='phase_quality';quality(rows(io.out/'samples.jsonl'),record)
            if label in LABELS:
                seq+=1;stage='checkpoint';r['operations'].append(await operation(io,label,seq))
        stage='check_finish';io.check(proc,expected)
        stage='ack_finish';io.acknowledge('finish')
        stage='request_finish';io.request_finish()
    except BaseException as error:note(stage,error)
    finally:
        if proc is not None:
            seed=expected
            if not identity_valid(seed):
                try:seed=io.cleanup_expected(proc)
                except BaseException:seed=None
            r['cleanup']=close_owned(proc,seed,io.inspect)
        r['handle']=observe_handle(proc)
        try:r['identity_diagnostic']=io.identity_diagnostic()
        except BaseException as error:note('identity_diagnostic',error)
        for key,where,getter in (('child','child_terminal',io.child_terminal),
                ('source_end','source_end',io.sources),
                ('counts_end','counts_end',lambda:fixture.counts(io.home)),
                ('samples','samples_read',lambda:rows(io.out/'samples.jsonl'))):
            try:
                if r['source_start'] is not None:r[key]=getter()
            except BaseException as error:note(where,error)
        r['seconds']=io.clock()-started
        if r['error'] is None:
            clean=r['cleanup'];child=r['child']
            if not (clean and clean['identity_matched'] is True and clean['alive'] is False
                and type(clean['exit_code']) is int and clean['exit_code']==0 and clean['error'] is None
                and child_valid(child) and child['candidate']=='PASS' and child['exit_code']==0
                and child['commanded_exit'] is True and r['handle']=={'alive':False,'exit_code':0,'error':None}
                and r['identity_diagnostic'] is None and r['source_start']==r['source_end']==child['source_end']
                and r['counts_end']==r['fixture']['counts'] and 0<r['seconds']<3000):
                r['error']='finish';r['failure_diagnostic']=execution.contract('acceptance')
        try:io.release()
        except BaseException as error:note('release',error)
        if r['error'] is None:r['candidate']='PASS'
    return r

async def pair(root,repo,authority,freeze,review,prepared,sha,run_id):
    import os
    from entry import workflow_authority
    from lifecycle import authority_valid
    started_wall=time.time()
    require(authority_valid(authority,started_wall,freeze,review),'authority')
    workflow_authority(os.environ,sha,authority['id'],authority['issued'],authority['expires'],review,started_wall)
    require(root==Path(os.environ['RUNNER_TEMP']).resolve()/'hud-finite-attribution-owned'
        and repo==Path(os.environ['GITHUB_WORKSPACE']).resolve() and run_id==os.environ['GITHUB_RUN_ID'],'authority')
    require(prepared(freeze) is True,'prepared')
    begin=time.monotonic()
    with (root/'PAIR_CLAIM.json').open('x') as f:
        json.dump({'id':authority['id'],'state':'CONSUMED_ONCE_NO_RETRY','max_runs':1,
            'started_wall':started_wall,'sha':sha,'freeze':freeze,'review':review,'run_id':run_id},f)
    r={'schema':'hud_finite_attribution_pair_v2','result':'PENDING_TERMINAL_SEAL','candidate':'FAIL',
       'error':None,'failure_diagnostic':None,'grant':authority['id'],'sha':sha,'run_id':run_id,'execution_kind':NativeIO.execution_kind,
       'freeze_start':freeze,'freeze_end':None,'review':review,'arms':[],'seconds':None,
       'limits':LIMITS[:],'growth_acceptance_budget':None,'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK'}
    stage='pair_budget'
    try:
        epoch=int(time.time())-7200
        for arm in ('sham','snapshot'):
            stage='pair_budget';require(time.monotonic()-begin<5980,'budget')
            stage='arm_directory';(root/arm).mkdir()
            stage='arm_initialize';io=NativeIO(root,repo,authority['id'],freeze,prepared,arm,epoch,begin)
            require(io.execution_kind==r['execution_kind'] and r['execution_kind'] in ('MODEL','NATIVE'),'prepared')
            stage='arm_execute';value=await run_arm(io);r['arms'].append(value)
            if value['candidate']=='FAIL':break
        stage='freeze_end';require(prepared(freeze) is True,'prepared')
        r['freeze_end']=freeze
        stage='pair_acceptance';require(len(r['arms'])==2 and all(x['candidate']=='PASS' for x in r['arms']),'finish')
        stage='pair_sources';require(r['arms'][0]['fixture']==r['arms'][1]['fixture']
            and r['arms'][0]['source_start']==r['arms'][1]['source_start'],'source')
        stage='pair_finish';require(time.monotonic()-begin<6000,'budget');r['candidate']='PASS'
    except BaseException as error:
        r['error']=error_code(error);r['failure_diagnostic']=execution.project(stage,error)
    r['seconds']=time.monotonic()-begin
    payload=encode(r);publish(root/'result.json',payload)
    require((root/'result.json').read_bytes()==payload and prepared(freeze) is True,'seal')
    elapsed=time.monotonic()-begin
    require(0<=elapsed<6000,'budget')
    from hashlib import sha256
    atomic(root/'completion.json',{'schema':'hud_memory_pair_completion_v2','payload_sha256':sha256(payload).hexdigest(),
        'verdict':r['candidate'],'freeze_sha256':freeze,'review_sha256':review,'seconds_at_seal':elapsed})
    return r['candidate']=='PASS'
