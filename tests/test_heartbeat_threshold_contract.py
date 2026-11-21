"""F4: synthetic rule -> snapshot -> actual frontend functions, no live IO/DOM."""
import asyncio
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import pytest
from dashboard.hud import rules

SOURCE = Path(__file__).resolve().parents[1] / 'dashboard/dist/index.js'
SCRIPT = r'''
const fs=require('fs'),vm=require('vm');
const React={Fragment:'fragment',createElement(type,props,...children){return {type,props,children};}};
const ctx={window:{__HERMES_PLUGIN_SDK__:{React,hooks:{},components:{Card:'card',CardContent:'body',Badge:'badge'},utils:{timeAgo(){return 'synthetic';}}},__HERMES_PLUGINS__:{register(){}}},fetch(){throw Error('network forbidden');}};
const marker='window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);';
const src=fs.readFileSync(process.argv[1],'utf8');if(src.split(marker).length!==2)throw Error('binding');
vm.runInNewContext(src.replace(marker,'window.__TEST={channelView,Overview,ChannelsTab,setLocale(l){CURRENT_LOCALE=l;}};'),ctx,{timeout:1000});
const input=JSON.parse(process.argv[2]);
function freeze(x){if(x&&typeof x==='object'){Object.values(x).forEach(freeze);Object.freeze(x);}return x;}
freeze(input);ctx.window.__TEST.setLocale(input.locale||'en');
const p=input.snap.gateway.platforms.sample;
const view=ctx.window.__TEST.channelView(p,input.snap._health&&input.snap._health.thresholds);
const tree=ctx.window.__TEST[input.component||'ChannelsTab']({snap:input.snap,health:input.health||input.snap._health});
function text(n){if(n==null||typeof n==='boolean')return '';if(typeof n!=='object')return String(n);return(Array.isArray(n)?n:n.children||[]).map(text).join(' ');}
console.log(JSON.stringify({view,tree,text:text(tree)}));
'''

def platform(**kw):
    return dict(activity='current',state='connected',heartbeat_source='periodic',heartbeat_age=45,**kw)

def snapshot(p):
    return {'gateway':{'alive':True,'state':'running','heartbeat_age':0,'platforms':{'sample':p}},'system':{'disk_free_percent':20},'db':{},'cron':{'jobs':[]}}

def render(snap,component='ChannelsTab',locale='en',health=None):
    args=json.dumps(dict(snap=snap,component=component,locale=locale,health=health),allow_nan=False)
    r=subprocess.run(['node','-e',SCRIPT,str(SOURCE),args],capture_output=True,text=True,check=True,timeout=5)
    return json.loads(r.stdout)

def check(health):return next(c for c in health['checks'] if c['key']=='channel:sample')

def find_key(node,key):
    if isinstance(node,dict):
        if (node.get('props') or {}).get('key')==key:return node
        for c in node.get('children',[]):
            v=find_key(c,key)
            if v:return v
    if isinstance(node,list):
        for c in node:
            v=find_key(c,key)
            if v:return v

@pytest.mark.parametrize('threshold,age,stale',[(30,45,True),(120,90,False),(30,30,False),(30,30.01,True),(120,120,False),(120,120.01,True),(0,0,False),(0,0.01,True),(60,60,False),(60,60.01,True)])
@pytest.mark.parametrize('component',['Overview','ChannelsTab'])
@pytest.mark.parametrize('locale',['zh','en'])
def test_rule_frontend_same_threshold(monkeypatch,threshold,age,stale,component,locale):
    monkeypatch.setattr(rules,'HEARTBEAT_CRITICAL',threshold)
    p=platform();p['heartbeat_age']=age;snap=snapshot(p)
    health=rules.evaluate_snapshot(snap,locale);snap['_health']=health
    assert check(health)['severity']==('warning' if stale else 'normal')
    out=render(snap,component,locale)
    assert out['view']['stale'] is stale
    assert ('心跳陈旧' if locale=='zh' else 'Stale heartbeat') in out['text'] if stale else ('心跳陈旧' if locale=='zh' else 'Stale heartbeat') not in out['text']
    assert out['view']['dot']==('hud-dot-warn' if stale else 'hud-dot-ok')
    if component == 'Overview':
        assert out['view']['dot'] in json.dumps(find_key(out['tree'], 'sample'))
        health_row = find_key(out['tree'], 'channel:sample')
        if stale:
            assert health_row['props']['className'] == 'hud-incident warning'
            assert health_row['children'] == [check(health)['message']]
        else:
            assert 'hud-dot-ok' in json.dumps(health_row)

@pytest.mark.parametrize('threshold',[0,0.5,30,60,120])
def test_metadata_exact_redacted_and_no_input_mutation(monkeypatch,threshold):
    monkeypatch.setattr(rules,'HEARTBEAT_CRITICAL',threshold)
    snap=snapshot(platform());before=copy.deepcopy(snap)
    seen=[]
    from dashboard.hud import redaction
    original=redaction.redact_obj
    # Spy the imported binding if present; red baseline will fail the field assertion.
    if hasattr(rules,'redact_obj'):
        monkeypatch.setattr(rules,'redact_obj',lambda x:(seen.append(copy.deepcopy(x)),original(x))[1])
    health=rules.evaluate_snapshot(snap)
    assert health.get('thresholds',{}).get('heartbeat_critical_s')==threshold
    assert {'heartbeat_critical_s':threshold} in seen
    assert snap==before
    json.dumps(health,allow_nan=False)

@pytest.mark.parametrize('threshold',[float('nan'),float('inf'),-1])
def test_invalid_config_metadata_is_json_safe_unknown(monkeypatch,threshold):
    # Do not claim to repair legacy backend invalid-config policy. No periodic input here.
    monkeypatch.setattr(rules,'HEARTBEAT_CRITICAL',threshold)
    p=platform();p['heartbeat_source']=None
    health=rules.evaluate_snapshot(snapshot(p))
    assert health.get('thresholds')=={'heartbeat_critical_s':None}
    json.dumps(health,allow_nan=False)

@pytest.mark.parametrize('metadata',[None,{}, {'heartbeat_critical_s':None},{'heartbeat_critical_s':'120'},{'heartbeat_critical_s':False},{'heartbeat_critical_s':-1}])
@pytest.mark.parametrize('age',[45,90])
def test_missing_invalid_metadata_never_guesses_sixty(metadata,age):
    p=platform();p['heartbeat_age']=age;snap=snapshot(p)
    snap['_health']={'thresholds':metadata,'checks':[]}
    out=render(snap)
    assert out['view']['stale'] is False
    assert out['view']['dot']=='hud-dot-warn'
    assert 'Heartbeat threshold unknown' in out['text']
    assert 'Stale heartbeat' not in out['text']
    assert out['view']['heartbeat']==str(age)+'s'

@pytest.mark.parametrize('meta,dot',[
 ({'activity':'historical'},'hud-dot-mute'),({'activity':'inactive'},'hud-dot-mute'),({'activity':'unknown'},'hud-dot-warn'),({'state':'disconnected'},'hud-dot-bad'),({'needs_attention':True},'hud-dot-warn'),({'heartbeat_source':None},'hud-dot-ok'),({'heartbeat_source':'status_update'},'hud-dot-ok'),({'heartbeat_age':None},'hud-dot-ok'),({'heartbeat_age':'90'},'hud-dot-ok'),({'heartbeat_age':-1},'hud-dot-ok'),({'heartbeat_age':False},'hud-dot-ok')])
def test_provenance_failure_attention_and_age_boundaries(meta,dot):
    p=platform();p.update(meta);snap=snapshot(p)
    out=render(snap)
    assert out['view']['dot']==dot
    if p.get('activity')!='current' or p.get('state')!='connected':assert 'Heartbeat threshold unknown' not in out['text']
    assert 'Stale heartbeat' not in out['text']

@pytest.mark.parametrize('severity', ['critical', 'warning'])
def test_health_severity_not_hidden_by_threshold_unknown(severity):
    snap=snapshot(platform());snap['_health']={'checks':[{'key':'channel:sample','severity':severity,'message':'synthetic'}]}
    out=render(snap,'Overview')
    alert = find_key(out['tree'], 'channel:sample')
    assert alert['props']['className'] == f'hud-incident {severity}'
    assert alert['children'] == ['synthetic']

@pytest.mark.parametrize('threshold',[30,120])
def test_matching_snapshot_not_other_health_threshold(threshold):
    snap=snapshot(platform());snap['_health']={'thresholds':{'heartbeat_critical_s':threshold},'checks':[]}
    other={'thresholds':{'heartbeat_critical_s':120 if threshold==30 else 30},'checks':[{'key':'channel:sample','severity':'normal','message':'synthetic'}]}
    out=render(snap,'Overview',health=other)
    assert out['view']['stale'] is (threshold==30)
    assert ('hud-dot-warn' if threshold==30 else 'hud-dot-ok') in json.dumps(find_key(out['tree'],'channel:sample'))

@pytest.mark.parametrize('threshold',[30,120])
def test_actual_snapshot_health_route_and_settings_in_isolation(monkeypatch,threshold):
    from dashboard import plugin_api as api
    monkeypatch.setattr(api.rules,'HEARTBEAT_CRITICAL',threshold)
    monkeypatch.setattr(api,'_snapshot_cache',{})
    monkeypatch.setattr(api,'_snapshot_lock',asyncio.Lock())
    monkeypatch.setattr(api,'_last_snapshot',None)
    monkeypatch.setattr(api,'_last_overall',None)
    monkeypatch.setattr(api.collectors,'build_snapshot',lambda locale:snapshot(platform()))
    monkeypatch.setattr(api,'_maybe_telemetry',lambda *args:None)
    async def run():
        snap=await api.get_snapshot('en');health=await api.get_health('en');settings=await api.get_settings()
        assert snap['_health'].get('thresholds')=={'heartbeat_critical_s':threshold}
        assert health['thresholds']['heartbeat_critical_s']==settings['thresholds']['heartbeat_critical_s']==threshold
        assert render(snap)['view']['stale'] is (threshold==30)
    asyncio.run(run())

@pytest.mark.parametrize('threshold',['30','120'])
def test_real_env_override_import(threshold):
    env=dict(os.environ,HUD_HEARTBEAT_CRITICAL=threshold)
    code='from dashboard.hud import rules; import json; print(json.dumps(rules.evaluate_snapshot({})["thresholds"]))'
    r=subprocess.run([sys.executable,'-B','-c',code],env=env,capture_output=True,text=True,timeout=5,check=True)
    assert json.loads(r.stdout)=={'heartbeat_critical_s':float(threshold)}
