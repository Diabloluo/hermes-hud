"""Synthetic IncidentsTab contract: inert React tree, no effects/network/DOM."""
import json
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "dashboard/dist/index.js"
SCRIPT = r'''
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(process.argv[3]);
const polls = [];
const ctx={window:{__HERMES_PLUGIN_SDK__:{
  React:{Fragment:'fragment',createElement(type,props,...children){return {type,props,children};}},
  hooks:{},
  components:{Card:'card',CardContent:'body',Badge:'badge'},utils:{timeAgo(){return 'synthetic';}},
  fetchJSON(){throw Error('network forbidden');}
},__HERMES_PLUGINS__:{register(){}}, fixturePoll(url) {
  polls.push(url);
  return {data:{incidents:input.incidents}};
}}};
const source=fs.readFileSync(process.argv[1],'utf8');
const marker='window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);';
if(source.split(marker).length!==2)throw Error('registration binding changed');
vm.runInNewContext(source.replace(marker,
  'usePoll = window.fixturePoll; window.__TEST={IncidentsTab,setLocale(l){CURRENT_LOCALE=l;}};'),
  ctx,{timeout:1000});
ctx.window.__TEST.setLocale(process.argv[2]);
function freeze(x){if(x&&typeof x==='object'){Object.values(x).forEach(freeze);Object.freeze(x);}return x;}
freeze(input);
const before=JSON.stringify(input);
const tree=ctx.window.__TEST.IncidentsTab({snap:{errors:{},_health:{incidents:input.current||[]}}});
if(JSON.stringify(input)!==before)throw Error('input changed');
if(polls.length!==1 || !polls[0].endsWith('/incidents'))throw Error('unexpected incident poll');
console.log(JSON.stringify(tree));
'''


def render(locale, incidents, current=None):
    result = subprocess.run(
        ["node", "-e", SCRIPT, str(SOURCE), locale,
         json.dumps({"incidents": incidents, "current": current or []})],
        capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []):
            yield from walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from walk(child)


def text(node):
    if node is None or isinstance(node, bool):
        return ""
    if isinstance(node, dict):
        return " ".join(text(c) for c in node.get("children", []))
    if isinstance(node, list):
        return " ".join(text(c) for c in node)
    return str(node)


def incident(status, severity="warning", key="fixture"):
    return {"id": key, "status": status, "severity": severity,
            "title": "Synthetic incident", "detail": "Synthetic detail",
            "fingerprint": "cron:fixture:failure", "first_seen": 1000,
            "last_seen": 1001, "count": 2}


def badge(tree):
    return next(n for n in walk(tree) if n.get("type") == "badge")


@pytest.mark.parametrize("locale,expected", [
    ("zh", "恢复待确认"), ("en", "Recovery pending confirmation"),
    ("fr", "Rétablissement en attente de confirmation"),
    ("ar", "التعافي بانتظار التأكيد"),
])
@pytest.mark.parametrize("severity,variant", [("warning", "warning"), ("critical", "destructive")])
def test_pending_recovery_never_claims_resolved(locale, expected, severity, variant):
    node = badge(render(locale, [incident("pending_recovery", severity)]))
    assert text(node) == expected
    assert node["props"]["tone"] == variant


@pytest.mark.parametrize("locale,active,resolved", [("zh", "进行中", "已恢复"), ("en", "Active", "Resolved")])
@pytest.mark.parametrize("severity", ["warning", "critical"])
def test_known_active_and_recovered_contract_is_preserved(locale, active, resolved, severity):
    a = badge(render(locale, [incident("active", severity)]))
    r = badge(render(locale, [incident("recovered", severity)]))
    assert text(a) == active
    assert a["props"]["tone"] == ("destructive" if severity == "critical" else "warning")
    assert text(r) == resolved
    assert r["props"]["tone"] == "secondary"


@pytest.mark.parametrize("locale,expected", [("zh", "未知"), ("en", "Unknown")])
@pytest.mark.parametrize("status", [None, "", "future_state", "RECOVERED", False, 0])
@pytest.mark.parametrize("severity", ["warning", "critical"])
def test_unknown_status_does_not_claim_recovery(locale, expected, status, severity):
    node = badge(render(locale, [incident(status, severity)]))
    assert text(node) == expected
    assert node["props"]["tone"] == ("destructive" if severity == "critical" else "warning")


@pytest.mark.parametrize("locale,title", [("zh", "活跃事故"), ("en", "Active Incidents")])
@pytest.mark.parametrize("current_count", [0, 2])
def test_pending_is_included_in_existing_stored_active_subtotal(locale, title, current_count):
    rows = [incident("active", key=1), incident("pending_recovery", key=2),
            incident("recovered", key=3), incident("unknown", key=4)]
    tree = render(locale, rows, [{"fingerprint": "synthetic:" + str(i)} for i in range(current_count)])
    card = next(n for n in walk(tree) if n.get("type") == "card" and n["props"]["key"] == title)
    # Existing current-health + stored-active aggregation is deliberately retained.
    body = card["children"][0]["children"][1]
    assert text(body) == str(2 + current_count)


@pytest.mark.parametrize("locale,expected", [("zh", "未知"), ("en", "Unknown")])
def test_missing_status_does_not_claim_recovery(locale, expected):
    item = incident("active")
    del item["status"]
    assert text(badge(render(locale, [item]))) == expected
