"""Execute the session cost formatter with the available JS engine."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def test_session_cost_formatter(tmp_path):
    source = (Path(__file__).resolve().parents[1] / 'dashboard/dist/index.js').read_text()
    engine = shutil.which('node')
    jsc = Path('/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc')
    if not engine and jsc.exists():
        engine = str(jsc)
    if not engine:
        pytest.skip('JavaScript engine unavailable')
    functions = []
    for name in ('pricingCostCell', 'costTruth', 'fmtUSD'):
        functions.append(re.search(r'  function ' + name + r'\([^\n]+\n.*?\n  }', source, re.S).group())
    script = 'function tt(x) { return x; }\n' + '\n'.join(functions) + '''
    function check(actual, expected) {
        if (actual !== expected) throw new Error(actual + ' != ' + expected);
    }
    check(pricingCostCell({estimated_cost_usd:0, cost_complete:true}), '$0.0000 · 估算');
    check(pricingCostCell({estimated_cost_usd:.5, cost_complete:true}), '$0.5000 · 估算');
    check(pricingCostCell({estimated_cost_usd:.5, cost_complete:false,
         pricing_known_rows:1, pricing_coverage_ratio:.5}), '$0.5000 · 不完整：仅已定价部分 · 记录定价覆盖率 50%');
    check(pricingCostCell({estimated_cost_usd:0, cost_complete:false,
         pricing_known_rows:0}), '— · 价格未知，金额不可用');
    check(pricingCostCell({estimated_cost_usd:null, cost_complete:false,
         pricing_known_rows:null}), '— · 价格未知，金额不可用');
    '''
    file = tmp_path / 'formatter.js';file.write_text(script)
    subprocess.run([engine, str(file)], check=True, capture_output=True, text=True)
    # Also parse the complete IIFE; an absent SDK exits before UI initialization.
    file.write_text('var window = {};\n' + source)
    subprocess.run([engine, str(file)], check=True, capture_output=True, text=True)


def test_unknown_states_render_without_false_zero_or_stopped_service(tmp_path):
    source=(Path(__file__).resolve().parents[1]/'dashboard/dist/index.js').read_text()
    engine=shutil.which('node') or '/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc'
    if not Path(engine).exists() and not shutil.which(engine):pytest.skip('JavaScript engine unavailable')
    prelude='''
    var window = {
      __HERMES_PLUGIN_SDK__: {
        React: {Fragment:'fragment', createElement:function(type, props) {
          return {type:type, props:props, children:Array.prototype.slice.call(arguments,2)};
        }},
        hooks: {useState:function(x){return [x,function(){}];}, useEffect:function(){},
          useMemo:function(f){return f();}, useRef:function(x){return {current:x};},
          useCallback:function(f){return f;}},
        components:{Card:'card',CardContent:'content',Badge:'badge',Button:'button',Input:'input'},
        utils:{timeAgo:function(){return 'synthetic';}}
      }, __HERMES_PLUGINS__:{register:function(){}}
    };
    '''
    source=source.replace('window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);',
        'window.__REVIEW__={Overview:Overview, SystemTab:SystemTab, IncidentsTab:IncidentsTab};')
    checks='''
    function text(node) {
      if (node == null || typeof node === 'boolean') return '';
      if (typeof node !== 'object') return String(node);
      return (Array.isArray(node) ? node : node.children || []).map(text).join(' ');
    }
    function assert(x){if(!x) throw new Error('UI state contract failed');}
    var unknown=text(window.__REVIEW__.Overview({snap:{db:{today_sessions:{estimated_cost_usd:0,
      pricing_known_rows:0,cost_complete:false}}}}));
    assert(unknown.indexOf('价格未知，金额不可用')>=0 && unknown.indexOf('$0.0000')<0);
    var zero=text(window.__REVIEW__.Overview({snap:{db:{today_sessions:{estimated_cost_usd:0,cost_complete:true}}}}));
    assert(zero.indexOf('$0.0000')>=0);
    var missing=text(window.__REVIEW__.Overview({snap:{db:{error:'synthetic'}}}));
    assert(missing.indexOf('数据源不可用')>=0 && missing.indexOf('$0.0000')<0);
    var pending=text(window.__REVIEW__.SystemTab({snap:{launchd:{sample_status:'pending',managed:null},
      dashboard:{sample_status:'stale',procs:[]}}}));
    assert(pending.indexOf('未知')>=0 && pending.indexOf('Gateway 重启后可能不自启')<0);
    var refreshing=text(window.__REVIEW__.SystemTab({snap:{
      launchd:{sample_status:'refreshing',managed:true},
      dashboard:{sample_status:'refreshing',procs:[{pid:4242,rss:1024}]}}}));
    assert(refreshing.indexOf('未知')<0 && refreshing.indexOf('launchd 托管')>=0
      && refreshing.indexOf('4242')>=0 && refreshing.indexOf('Gateway 重启后可能不自启')<0);
    var na=text(window.__REVIEW__.SystemTab({snap:{
      launchd:{sample_status:'refreshing',status:'not_applicable',note:'synthetic not applicable'},
      dashboard:{sample_status:'refreshing',procs:[{pid:4242}]}}}));
    assert(na.indexOf('未知')<0 && na.indexOf('synthetic not applicable')>=0
      && na.indexOf('Gateway 重启后可能不自启')<0);
    var errors=text(window.__REVIEW__.IncidentsTab({snap:{errors:{count_30m:null}}}));
    assert(errors.indexOf('未知')>=0);
    var partial=text(window.__REVIEW__.IncidentsTab({snap:{errors:{count_30m:1,timestamp_status:'partial'}}}));
    assert(partial.indexOf('≥ 1')>=0);
    '''
    script=tmp_path/'ui-states.js';script.write_text(prelude+source+checks)
    subprocess.run([engine,str(script)],check=True,capture_output=True,text=True)


def test_budget_display_uses_its_own_pricing_coverage():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    source = Path(__file__).resolve().parents[1] / "dashboard/dist/index.js"
    script = r"""
    const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
    let budget;
    const summary = { estimated_cost_usd: 0, coverage: { cost_complete: true } };
    const window = {
      __poll: url => ({ data: url.endsWith("/cost/budget") ? budget :
        url.includes("/cost/summary?") ? summary : null }),
      __HERMES_PLUGIN_SDK__: {
        React: { Fragment: "fragment", createElement: (type, props, ...children) => ({ props, children }) },
        hooks: { useState: value => [value, () => {}] },
        components: { Card: "card", CardContent: "content", Badge: "badge", Button: "button", Input: "input" },
        utils: { timeAgo: () => "–" },
      },
    };
    vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8").replace(
      'window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);',
      "usePoll = window.__poll; window.usage = Usage; window.setLocale = l => { CURRENT_LOCALE = l; };"
    ), { window });
    function walk(node) {
      if (Array.isArray(node)) return node.flatMap(walk);
      if (!node || !node.children) return [];
      return [node, ...node.children.flatMap(walk)];
    }
    const cases = [
      ["complete zero", 0, { cost_complete: true }, "$0.0000"],
      ["complete positive", 0.004, { cost_complete: true }, "$0.0040"],
      ["unknown zero despite complete seven-day summary", 0, { pricing_known_rows: 0 }, "—（定价未知）"],
      ["partial known zero", 0, { pricing_known_rows: 1, pricing_unknown_rows: 2 }, "已知部分 $0.0000"],
      ["partial known amount", 1.23, { pricing_known_rows: 1 }, "已知部分 $1.23"],
      ["legacy zero", 0, undefined, "—（定价未知）"],
      ["legacy positive", 1.23, undefined, "已知部分 $1.23"],
      ["invalid amount", Infinity, { cost_complete: true }, "—（定价未知）"],
      ["unavailable", 5, { cost_complete: true }, "数据源不可用", "unavailable"],
      ["nested source unavailable", 0,
        { cost_complete: true, source_status: { usage: "unavailable" } }, "数据源不可用"],
    ];
    for (const [label, amount, coverage, expected, status = "attribution_uncertain"] of cases) {
      budget = { budget_configured: true, today_estimated_cost_usd: amount,
        budget_status: status, coverage };
      const card = walk(window.usage()).find(node => node.props?.key === "今日归属估算费用");
      const parts = walk(card);
      const metric = parts.find(node => node.props?.className === "hud-metric-value");
      const notes = parts.filter(node => node.props?.className === "hud-footnote")
        .flatMap(node => node.children);
      assert.equal(metric.children[0], expected, label);
      assert.equal(notes.includes("累计记录归属估算"), expected.includes("$"), label);
      assert.equal(notes.includes("未知价格记录 · 2"), label === "partial known zero", label);
    }
    budget = { budget_configured: true, today_estimated_cost_usd: 0,
      budget_status: "attribution_uncertain", coverage: { cost_complete: true } };
    for (const [locale, title, note] of [
      ["en", "Today's Attributed Est. Cost", "Attributed cumulative records"],
      ["fr", "Coût estimé attribué du jour", "Estimation par attribution des données cumulées"],
      ["ar", "التكلفة المقدّرة المنسوبة لليوم", "تقدير بإسناد السجلات التراكمية"],
    ]) {
      window.setLocale(locale);
      const card = walk(window.usage()).find(node => node.props?.key === title);
      const parts = walk(card);
      assert.equal(parts.find(node => node.props?.className === "hud-metric-value").children[0], "$0.0000");
      assert.ok(parts.some(node => node.props?.className === "hud-footnote" && node.children[0] === note), locale);
    }
    """
    result = subprocess.run([node, "-e", script, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
