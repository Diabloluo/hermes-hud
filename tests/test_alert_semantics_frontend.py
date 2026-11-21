"""Offline Node VM, inert React trees only: no browser, effects, IO or services."""
import json
import subprocess
from pathlib import Path
import pytest

SOURCE=Path(__file__).resolve().parents[1]/"dashboard/dist/index.js"
SCRIPT=r'''
const fs=require('fs'),vm=require('vm');
const ctx={window:{__HERMES_PLUGIN_SDK__:{React:{Fragment:'fragment',createElement(type,props,...children){return {type,props,children};}},hooks:{},components:{Card:'card',CardContent:'body',Badge:'badge'},utils:{timeAgo(){return 'synthetic';}}},__HERMES_PLUGINS__:{register(){}}}};
const expose='window.__TEST={ChannelsTab,Overview,CronTab,setLocale:function(l){CURRENT_LOCALE=l;}};';
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8').replace('window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);',expose),ctx,{timeout:1000});
ctx.window.__TEST.setLocale(process.argv[2]);
const input=JSON.parse(process.argv[3]);
const tree=ctx.window.__TEST[input.component]({snap:input.snap,health:input.health});
function text(n){if(n==null||typeof n==='boolean')return '';if(typeof n!=='object')return String(n);return (Array.isArray(n)?n:n.children||[]).map(text).join(' ');}
console.log(JSON.stringify({text:text(tree),tree}));
'''
def render(locale,component,snap,health=None):
    result=subprocess.run(["node","-e",SCRIPT,str(SOURCE),locale,json.dumps({"component":component,"snap":snap,"health":health})],capture_output=True,text=True,check=True,timeout=15)
    return json.loads(result.stdout)

@pytest.mark.parametrize("locale",["zh","en"])
@pytest.mark.parametrize("component",["ChannelsTab","Overview"])
@pytest.mark.parametrize("platform,zh,en,dot",[
 ({"activity":"historical","state":"disconnected"},"历史记录","Historical record","hud-dot-mute"),
 ({"activity":"unknown","state":"connected"},"当前状态未知","Current state unknown","hud-dot-warn"),
 ({"state":"connected"},"当前状态未知","Current state unknown","hud-dot-warn"),
 ({"activity":"inactive","state":"disabled"},"已停用","Inactive","hud-dot-mute"),
 ({"activity":"current","state":"connected","needs_attention":True},"需关注","Needs Attention","hud-dot-warn"),
 ({"activity":"current","state":"degraded"},"degraded","degraded","hud-dot-bad"),
 ({"activity":"current","state":"retrying"},"retrying","retrying","hud-dot-bad"),
 ({"activity":"current","state":"connected","heartbeat_source":"periodic","heartbeat_age":61},"心跳陈旧","Stale heartbeat","hud-dot-warn"),
 ({"activity":"current","state":"connected","timestamp_semantics":"status_update","heartbeat_age":900},"报告已连接","Reports connected","hud-dot-ok"),
])
def test_channel_render_contract(locale,component,platform,zh,en,dot):
    result=render(locale,component,{"gateway":{"platforms":{"sample":platform}},"_health":{"thresholds":{"heartbeat_critical_s":60}}})
    assert (zh if locale=="zh" else en) in result["text"]
    assert dot in json.dumps(result["tree"])

@pytest.mark.parametrize("locale",["zh","en"])
@pytest.mark.parametrize("job,zh,en,variant",[
 ({"enabled":None},"启用状态未知","Enabled state unknown","warning"),
 ({},"启用状态未知","Enabled state unknown","warning"),
 ({"enabled":False,"failure_streak":26},"已禁用","Disabled","secondary"),
 ({"enabled":True,"state":"paused","failure_streak":3},"已暂停","Paused","secondary"),
 ({"enabled":True,"state":"completed","failure_streak":3},"已完成","Completed","secondary"),
 ({"enabled":None,"failure_streak":3},"启用状态未知","Enabled state unknown","destructive"),
 ({"enabled":True,"failure_streak":3,"last_status":"failed"},"失败","Failed","destructive"),
])
def test_cron_render_contract(locale,job,zh,en,variant):
    result=render(locale,"CronTab",{"cron":{"jobs":[{"id":"fixture","name":"sample",**job}]}})
    assert (zh if locale=="zh" else en) in result["text"]
    assert '"tone": "'+variant+'"' in json.dumps(result["tree"])
    if job.get("enabled") is False or job.get("state") in ("paused","completed"):
        assert ("历史连续失败" if locale=="zh" else "Historical failure streak") in result["text"]
        assert "destructive" not in json.dumps(result["tree"])

@pytest.mark.parametrize("age",[None,"900",-1,False,900])
def test_no_status_timestamp_as_heartbeat(age):
    p={"activity":"current","state":"connected","heartbeat_age":age,"timestamp_semantics":"status_update","updated_at":1}
    result=render("en","ChannelsTab",{"gateway":{"platforms":{"sample":p}}})
    assert "Status update time" in result["text"]
    assert "Not independently verified" in result["text"]
    assert "Stale heartbeat" not in result["text"]

@pytest.mark.parametrize("age",[None,"900",-1,False])
def test_invalid_periodic_heartbeat_is_unverified(age):
    p={"activity":"current","state":"connected","heartbeat_source":"periodic","heartbeat_age":age}
    result=render("en","ChannelsTab",{"gateway":{"platforms":{"sample":p}}})
    assert "Not independently verified" in result["text"]
    assert "Stale heartbeat" not in result["text"]


def find_key(node,key):
    if isinstance(node,dict):
        if (node.get("props") or {}).get("key")==key:return node
        for child in node.get("children",[]):
            found=find_key(child,key)
            if found:return found
    if isinstance(node,list):
        for child in node:
            found=find_key(child,key)
            if found:return found

@pytest.mark.parametrize("activity,dot",[("historical","hud-dot-mute"),("inactive","hud-dot-mute"),("unknown","hud-dot-warn"),("current","hud-dot-bad")])
def test_health_check_icon_uses_channel_provenance(activity,dot):
    result=render("en","Overview",{"gateway":{"platforms":{"sample":{"activity":activity,"state":"disconnected"}}}}, {"checks":[{"key":"channel:sample","severity":"normal" if activity in ("historical","inactive") else "warning" if activity == "unknown" else "critical","message":"fixture"}]})
    row=find_key(result["tree"],"channel:sample")
    assert dot in json.dumps(find_key(result["tree"], "sample"))
    if activity in ("historical", "inactive"):
        assert dot in json.dumps(row)
    else:
        severity = "warning" if activity == "unknown" else "critical"
        assert row["props"]["className"] == f"hud-incident {severity}"
        assert row["children"] == ["fixture"]

@pytest.mark.parametrize("kind,expected",[("historical","hud-dot-mute"),("critical","hud-dot-bad"),("warning","hud-dot-warn")])
def test_health_check_cron_history_and_disk_keep_real_severity(kind,expected):
    key="cron:sample" if kind=="historical" else "disk"
    result=render("en","Overview",{"cron":{"jobs":[{"id":"sample","enabled":False,"failure_streak":26}]}},{"checks":[{"key":key,"severity":"normal" if kind=="historical" else kind,"message":"fixture"}]})
    row = find_key(result["tree"], key)
    if kind == "historical":
        assert expected in json.dumps(row)
    else:
        assert row["props"]["className"] == f"hud-incident {kind}"
        assert row["children"] == ["fixture"]

@pytest.mark.parametrize("updated",[None,"900",False,-1,0,1])
def test_status_time_type_boundary(updated):
    result=render("en","ChannelsTab",{"gateway":{"platforms":{"sample":{"activity":"current","state":"connected","timestamp_semantics":"status_update","updated_at":updated}}}})
    assert "Invalid Date" not in result["text"] and "NaN" not in result["text"]
    assert "Status update time" in result["text"]

@pytest.mark.parametrize("severity,dot",[("normal","hud-dot-warn"),("warning","hud-dot-warn"),("critical","hud-dot-bad")])
def test_health_check_unknown_cron_never_false_green(severity,dot):
    result=render("en","Overview",{"cron":{"jobs":[{"id":"sample","enabled":None}]}},{"checks":[{"key":"cron:sample","severity":severity,"message":"fixture"}]})
    row = find_key(result["tree"], "cron:sample")
    if severity == "normal":
        assert dot in json.dumps(row)
    else:
        assert row["props"]["className"] == f"hud-incident {severity}"
    assert "Enabled state unknown" in result["text"]

@pytest.mark.parametrize("locale,expected",[("zh","已断开"),("en","Disconnected")])
def test_current_disconnect_stays_red(locale,expected):
    result=render(locale,"ChannelsTab",{"gateway":{"platforms":{"sample":{"activity":"current","state":"disconnected","needs_attention":False}}}})
    assert expected in result["text"] and "hud-dot-bad" in json.dumps(result["tree"])

@pytest.mark.parametrize("age,stale",[(0,False),(60,False),(60.01,True)])
def test_periodic_heartbeat_boundary(age,stale):
    result=render("en","ChannelsTab",{"gateway":{"platforms":{"sample":{"activity":"current","state":"connected","heartbeat_source":"periodic","heartbeat_age":age}}},"_health":{"thresholds":{"heartbeat_critical_s":60}}})
    assert ("Stale heartbeat" in result["text"]) is stale
