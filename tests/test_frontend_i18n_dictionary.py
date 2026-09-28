"""Check literal tt() keys in all three dictionaries without Hermes/browser."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("locale", ["en", "fr", "ar"])
def test_every_literal_ui_key_has_translation(locale):
    if not shutil.which("node"):
        pytest.skip("Node.js required for JS dictionary contract")
    source = Path(__file__).resolve().parents[1] / "dashboard/dist/index.js"
    script = r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const ctx={window:{__HERMES_PLUGIN_SDK__:{React:{createElement(){}},hooks:{},components:{},utils:{}},__HERMES_PLUGINS__:{register(){}}}};
vm.runInNewContext(source.replace('window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);','window.__DICT=HUD_DICTS;'),ctx);
const keys=[...new Set([...source.matchAll(/tt\(("(?:[^"\\]|\\.)*")/g)].map(m=>JSON.parse(m[1])))];
if(keys.length<200)throw Error('dictionary extraction failed');
console.log(JSON.stringify(keys.filter(k=>!Object.hasOwn(ctx.window.__DICT[process.argv[2]],k))));
'''
    result = subprocess.run(["node", "-e", script, str(source), locale],
                            capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout) == []


@pytest.mark.parametrize("summary", [{}, {"total": 0, "enabled": 0}])
def test_unavailable_cron_summary_never_shows_undefined(summary):
    if not shutil.which("node"):
        pytest.skip("Node.js required for JS render contract")
    source = Path(__file__).resolve().parents[1] / "dashboard/dist/index.js"
    script = r'''
const fs=require('fs'),vm=require('vm');
const ctx={window:{__HERMES_PLUGIN_SDK__:{React:{createElement(type,props,...children){return {type,props,children};}},hooks:{},components:{Card:'card',CardContent:'body',Badge:'badge'},utils:{}},__HERMES_PLUGINS__:{register(){}}}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8').replace('window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);','window.__CRON=CronTab;'),ctx);
console.log(JSON.stringify(ctx.window.__CRON({snap:{cron:{summary:JSON.parse(process.argv[2]),jobs:[]},executions:{}}})));
'''
    result = subprocess.run(["node", "-e", script, str(source), json.dumps(summary)],
                            capture_output=True, text=True, check=True, timeout=15)
    assert "undefined" not in result.stdout
    assert "NaN" not in result.stdout
    assert "—" in result.stdout
