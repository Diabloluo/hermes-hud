/**
 * Hermes HUD — Dashboard Plugin
 * =============================
 * 本地实时监控指挥中心（13-Tab 计划的 MVP 实现）。
 *
 * 纯 IIFE、无构建步骤。用 window.__HERMES_PLUGIN_SDK__ 提供 React /
 * hooks / 组件 / 认证 fetch；2 秒轮询 /snapshot + WebSocket 增量事件流
 * （buildWsUrl 自动带鉴权，断线指数退避并回退到轮询）。
 *
 * 数据只读：后端只查询 Hermes 现有状态文件与 SQLite，前端不做任何写操作。
 */

(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  const { React } = SDK;
  const h = React.createElement;
  const { useState, useEffect, useMemo, useRef, useCallback } = SDK.hooks;
  const { Card, CardContent, Badge, Button, Input } = SDK.components;
  const { timeAgo } = SDK.utils;

  const API = "/api/plugins/hermes-hud";

  // -------------------------------------------------------------------------
  // 格式化工具
  // -------------------------------------------------------------------------

  function fmtBytes(n) {
    if (n == null || isNaN(n)) return "-";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
    return (n / 1073741824).toFixed(2) + " GB";
  }

  function fmtTokens(n) {
    if (n == null || isNaN(n)) return "-";
    if (n < 1000) return String(Math.round(n));
    if (n < 1000000) return (n / 1000).toFixed(1) + "k";
    if (n < 1000000000) return (n / 1000000).toFixed(2) + "M";
    return (n / 1000000000).toFixed(2) + "B";
  }

  function fmtUSD(n) {
    if (n == null || isNaN(n)) return "-";
    return "$" + n.toFixed(n < 1 ? 4 : 2);
  }

  function fmtPct(n) {
    if (n == null || isNaN(n)) return "-";
    return n.toFixed(1) + "%";
  }

  function fmtTime(ts) {
    if (!ts) return "-";
    const d = new Date(ts * 1000);
    return d.toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      second: "2-digit", hour12: false,
    });
  }

  function fmtDay(day) {
    return day; // "2026-08-23"
  }

  function dotClass(ok, warn) {
    if (ok === true) return "hud-dot-ok";
    if (ok === false) return warn ? "hud-dot-warn" : "hud-dot-bad";
    return "hud-dot-mute";
  }

  function healthClass(level) {
    return "hud-health-" + (level === "critical" ? "critical" : level === "warning" ? "warning" : "normal");
  }

  function healthLabel(level) {
    return level === "critical" ? "故障" : level === "warning" ? "警告" : "正常";
  }

  /** 渠道状态 → 中文 */
  function stateZh(s) {
    if (s === "connected") return "已连接";
    if (s === "disconnected") return "已断开";
    if (s === "connecting") return "连接中";
    if (s === "reconnecting") return "重连中";
    if (s === "error") return "错误";
    return s || "未知";
  }

  /** Cron 状态 → 中文 */
  function statusZh(s) {
    if (s === "ok" || s === "completed") return "成功";
    if (s === "error" || s === "failed") return "失败";
    if (s === "running") return "运行中";
    if (s === "claimed") return "已认领";
    if (s === "unknown") return "未知";
    return s || "待运行";
  }

  function kv(k, v) {
    return h("div", { className: "hud-kv", key: k },
      h("span", { className: "k" }, k),
      h("span", { className: "v" }, v));
  }

  function card(title, body, extra) {
    return h(Card, { key: title },
      h(CardContent, { style: { padding: "12px 14px" } },
        h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 } },
          h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.75 } }, title),
          extra || null),
        body));
  }

  // 空状态
  function empty(text) {
    return h("div", { style: { padding: 18, textAlign: "center", opacity: 0.5, fontSize: 13 } }, text);
  }

  // -------------------------------------------------------------------------
  // 数据 hooks
  // -------------------------------------------------------------------------

  /** 通用轮询 hook：url 每 interval ms 拉一次，返回 {data, error, lastAt}。 */
  function usePoll(url, interval) {
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [lastAt, setLastAt] = useState(null);
    useEffect(() => {
      let alive = true;
      async function tick() {
        try {
          const d = await SDK.fetchJSON(url);
          if (!alive) return;
          setData(d);
          setError(null);
          setLastAt(Date.now());
        } catch (e) {
          if (alive) setError(String(e && e.message ? e.message : e));
        }
      }
      tick();
      const t = setInterval(tick, interval);
      return () => { alive = false; clearInterval(t); };
    }, [url, interval]);
    return { data, error, lastAt };
  }

  /** 单次 fetch（点击/搜索触发） */
  function useOnce() {
    const [state, setState] = useState({ loading: false, data: null, error: null });
    const run = useCallback(async (url) => {
      setState({ loading: true, data: null, error: null });
      try {
        const d = await SDK.fetchJSON(url);
        setState({ loading: false, data: d, error: null });
      } catch (e) {
        setState({ loading: false, data: null, error: String(e && e.message ? e.message : e) });
      }
    }, []);
    return [state, run];
  }

  /** 事件流去重键 */
  function evKey(e) {
    return e.type + ":" + e.sub + ":" + e.event + ":" + Math.round(e.ts);
  }

  // -------------------------------------------------------------------------
  // 迷你柱状图
  // -------------------------------------------------------------------------

  function MiniBars({ values, height, fmt }) {
    const max = Math.max.apply(null, values.concat([1]));
    return h("div", { className: "hud-bars", style: { height: height || 90 } },
      values.map(function (v, i) {
        const pct = Math.max(2, (v / max) * 100);
        return h("div", {
          key: i,
          className: "hud-bar",
          style: { height: pct + "%" },
          title: fmt ? fmt(v, i) : String(v),
        });
      }));
  }

  // -------------------------------------------------------------------------
  // 指挥中心
  // -------------------------------------------------------------------------

  function Overview({ snap, health }) {
    if (!snap) return empty("加载中…");
    const gw = snap.gateway || {};
    const sys = snap.system || {};
    const db = snap.db || {};
    const cron = snap.cron || {};
    const today = db.today_sessions || {};
    const mem = sys.memory || {};
    const platforms = gw.platforms || {};

    const totalCost = (today.estimated_cost_usd || 0) + (today.aux_est_cost || 0);
    const checks = (health && health.checks) || [];
    const incidents = (health && health.incidents) || [];

    return h(React.Fragment, null,
      // 快速指标行
      h("div", { className: "hud-grid hud-grid-4" },
        card("Gateway",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            h("div", { style: { fontSize: 15, fontWeight: 700 } },
              h("span", { className: "hud-dot " + dotClass(gw.alive, false) }),
              gw.alive ? "运行中" : "未运行",
              gw.pid ? h("span", { style: { opacity: 0.5, fontSize: 11, marginLeft: 6 } }, "PID " + gw.pid) : null),
            kv("状态", gw.state || "-"),
            kv("版本", gw.code_version || "-"),
            kv("活跃 Agent", String(gw.active_agents || 0)))),
        card("渠道",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            Object.keys(platforms).map(function (name) {
              const p = platforms[name];
              const ok = p.state === "connected";
              const stale = (p.heartbeat_age || 0) > 60;
              return h("div", { key: name, style: { display: "flex", alignItems: "center", gap: 8 } },
                h("span", { className: "hud-dot " + dotClass(ok, stale) }),
                h("span", { style: { fontWeight: 600, width: 70 } }, name),
                h("span", { style: { opacity: ok ? 0.85 : 1, color: ok ? undefined : "#f87171" } },
                  stateZh(p.state) + (stale ? "（心跳陈旧）" : "")),
                stale ? h(Badge, { variant: "warning" }, "抖动") : null);
            }))),
        card("今日 Token / 费用",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv("输入", fmtTokens(today.input_tokens)),
            kv("输出", fmtTokens(today.output_tokens)),
            kv("Cache 读", fmtTokens(today.cache_read_tokens)),
            h("div", { style: { display: "flex", alignItems: "baseline", gap: 6 } },
              h("span", { className: "k" }, "估算费用"),
              h("span", { className: "v", style: { fontSize: 16, fontWeight: 700 } }, fmtUSD(totalCost)),
              h(Badge, { variant: "secondary" }, "估算")))),
        card("Cron / 会话",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv("任务", cron.summary ? (cron.summary.enabled + " 启用 / " + cron.summary.total + " 总") : "-"),
            kv("执行中", String((cron.summary && cron.summary.running_state) || 0)),
            kv("失败中", String((cron.summary && cron.summary.failing) || 0)),
            kv("活跃会话", String((snap.active_sessions || []).length))))),

      // 健康检查 + 事故
      h("div", { className: "hud-grid hud-grid-2" },
        card("健康检查 (" + (checks.length) + " 项)",
          h("div", { className: "hud-scroll" },
            checks.map(function (c) {
              const sev = c.severity;
              return h("div", { key: c.key, className: "hud-check" },
                h("span", { className: "hud-dot " + dotClass(sev === "normal", sev === "warning") }),
                h("span", { style: { flex: 1 } }, c.message));
            }))),
        card("事故时间线 (最近 " + Math.min(10, incidents.length) + ")",
          incidents.length === 0
            ? h("div", { style: { padding: 10, fontSize: 13, opacity: 0.6 } }, "当前无活跃事故")
            : h("div", { className: "hud-scroll" },
              incidents.map(function (inc) {
                return h("div", { key: inc.fingerprint, className: "hud-incident " + inc.severity },
                  h("div", { style: { fontWeight: 600, fontSize: 13 } }, inc.title),
                  h("div", { style: { opacity: 0.7, fontSize: 11.5, marginTop: 2 } }, inc.detail));
              })))),

      // 系统迷你
      h("div", { className: "hud-grid hud-grid-4" },
        card("CPU", h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtPct(sys.cpu_percent))),
        card("内存", h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtPct(mem.percent),
          h("div", { style: { fontSize: 11, opacity: 0.6, marginTop: 2 } }, fmtBytes(mem.used) + " / " + fmtBytes(mem.total)))),
        card("磁盘剩余", h("div", {
          style: { fontSize: 20, fontWeight: 700, color: (sys.disk_free_percent != null && sys.disk_free_percent < 15) ? "#facc15" : undefined },
        }, fmtPct(sys.disk_free_percent))),
        card("机器运行", h("div", { style: { fontSize: 15, fontWeight: 600 } },
          sys.uptime_seconds ? Math.round(sys.uptime_seconds / 86400) + " 天" : "-"))),

      h("div", { className: "hud-footnote" },
        "采集于 " + (snap.generated_at_iso || fmtTime(snap.collected_at)) +
        " · 时区 " + (snap.tz || "-") + " · 数据为本地只读采集"));
  }

  // -------------------------------------------------------------------------
  // 实时活动
  // -------------------------------------------------------------------------

  function Live({ snap, events, wsState }) {
    if (!snap) return empty("加载中…");
    const sessions = snap.active_sessions || [];
    const gw = snap.gateway || {};
    const tools = usePoll(API + "/tool-events?limit=60", 10000).data || [];

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-2" },
        card("活跃会话 (" + sessions.length + ")",
          sessions.length === 0
            ? empty("当前无活跃会话")
            : h("div", { className: "hud-scroll" },
              h("table", { className: "hud-table" },
                h("thead", null, h("tr", null,
                  h("th", null, "标题 / ID"),
                  h("th", null, "模型"),
                  h("th", null, "来源"),
                  h("th", null, "运行"),
                  h("th", null, "Token"))),
                h("tbody", null, sessions.slice(0, 40).map(function (s) {
                  return h("tr", { key: s.id },
                    h("td", null,
                      h("div", { style: { fontWeight: 600 } }, (s.title || "(无标题)").slice(0, 46)),
                      h("div", { className: "mono", style: { opacity: 0.55, fontSize: 10.5 } }, s.id.slice(0, 20))),
                    h("td", null, s.model || "-"),
                    h("td", null, s.source || "-"),
                    h("td", { className: "num" }, s.running_seconds ? Math.round(s.running_seconds / 60) + "m" : "-"),
                    h("td", { className: "num" }, fmtTokens(s.input_tokens)));
                }))))),
        card("实时事件流" + (wsState === "connected" ? "" : " (轮询模式)"),
          events.length === 0
            ? empty("暂无事件")
            : h("div", { className: "hud-events" },
              events.slice(0, 120).map(function (e, i) {
                const label = e.type + "·" + (e.sub || "") + " " + e.event +
                  (e.to ? " → " + e.to : "") + (e.status ? " [" + e.status + "]" : "") +
                  (e.state ? " (" + e.state + ")" : "");
                return h("div", { key: evKey(e) + i, className: "hud-event" },
                  h("span", { className: "ts" }, fmtTime(e.ts).slice(11)),
                  h("span", { style: { opacity: 0.85 } }, label));
              })))),
      card("最近工具调用 (" + tools.length + ")",
        tools.length === 0 ? empty("暂无工具调用记录") :
        h("div", { className: "hud-scroll", style: { maxHeight: 300 } },
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, "时间"), h("th", null, "会话"), h("th", null, "工具"), h("th", null, "调用参数工具"))),
            h("tbody", null, tools.map(function (t, i) {
              return h("tr", { key: i },
                h("td", { className: "num", style: { fontSize: 11 } }, fmtTime(t.ts).slice(11)),
                h("td", { style: { maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, t.title),
                h("td", null, h(Badge, { variant: "secondary" }, t.tool_name)),
                h("td", { style: { fontSize: 10.5, opacity: 0.7 } },
                  (t.tool_calls || []).join(", ") || "-"));
            }))))),

      h("div", { className: "hud-footnote" },
        "事件流每秒级增量（channel/cron/session/health/gateway 状态变化）；" +
        "工具调用为轻量版（从 messages 推断），精确 tool start/end 生命周期需插件 hook（第二版）。"));
  }

  // -------------------------------------------------------------------------
  // Token 与费用
  // -------------------------------------------------------------------------

  function Usage() {
    const [days, setDays] = useState(30);
    const { data, error } = usePoll(API + "/usage?days=" + days, 30000);
    const snap = usePoll(API + "/snapshot", 30000).data;
    const totals = (data && data.totals) || {};
    const byDay = (data && data.by_day) || [];
    const byModel = (data && data.by_model) || [];
    const byTask = (data && data.by_task) || [];

    const dayLabels = byDay.map(function (d) { return d.day.slice(5); });
    const costVals = byDay.map(function (d) { return d.est_cost; });
    const inVals = byDay.map(function (d) { return d.input; });

    const db = (snap && snap.db) || {};
    const dbUsage = db.usage || {};

    return h(React.Fragment, null,
      h("div", { style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 4 } },
        h("span", { className: "k", style: { fontSize: 12, opacity: 0.6 } }, "统计窗口"),
        [7, 30, 90].map(function (d) {
          return h(Button, {
            key: d, size: "sm", variant: days === d ? "default" : "outline",
            onClick: function () { setDays(d); },
            style: { padding: "2px 10px", fontSize: 12 },
          }, d + " 天");
        }),
        h(Badge, { variant: "secondary", style: { marginLeft: 8 } }, "费用为本地估算，非账单")),

      h("div", { className: "hud-grid hud-grid-4", style: { marginTop: 8 } },
        card("输入 Token", h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtTokens(totals.input))),
        card("输出 Token", h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtTokens(totals.output))),
        card("Cache 读", h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtTokens(totals.cache_read))),
        card("估算费用", h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtUSD(totals.est_cost)),
          h(Badge, { variant: "secondary" }, "实际 $" + (totals.actual_cost || 0).toFixed(2)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card("每日估算费用 (最近 " + days + " 天)",
          costVals.length ? h("div", null,
            h(MiniBars, { values: costVals, height: 90, fmt: function (v, i) { return dayLabels[i] + " $" + v.toFixed(2); } }),
            h("div", { style: { display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 } },
              dayLabels.slice(-14).map(function (d, i) {
                return h("span", { key: d, style: { fontSize: 10, opacity: 0.6, fontVariantNumeric: "tabular-nums" } }, d.slice(5));
              })))
            : empty("无数据")),
        card("每日输入 Token",
          inVals.length ? h(MiniBars, { values: inVals, height: 90, fmt: function (v, i) { return dayLabels[i] + " " + fmtTokens(v); } }) : empty("无数据"))),

      h("div", { className: "hud-grid hud-grid-2" },
        card("按模型 (近 " + days + " 天)",
          byModel.length === 0 ? empty("无数据") : h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, "模型"), h("th", { className: "num" }, "调用"), h("th", { className: "num" }, "输入"),
              h("th", { className: "num" }, "输出"), h("th", { className: "num" }, "费用"))),
            h("tbody", null, byModel.map(function (m) {
              return h("tr", { key: m.model },
                h("td", { style: { fontWeight: 600 } }, m.model),
                h("td", { className: "num" }, String(m.api_calls || m.sessions || 0)),
                h("td", { className: "num" }, fmtTokens(m.input)),
                h("td", { className: "num" }, fmtTokens(m.output)),
                h("td", { className: "num" }, fmtUSD(m.est_cost)));
            })))),
        card("辅助调用类型 (近 " + days + " 天)",
          byTask.length === 0
            ? h("div", null,
                empty("无辅助调用数据"),
                h("div", { style: { fontSize: 11.5, opacity: 0.6, padding: "0 12px 12px" } },
                  "辅助调用 = session_model_usage.task != ''（compression / vision / title_generation / background_review 等）。主会话与辅助调用已分开归集，不重复计数。"))
            : h("table", { className: "hud-table" },
              h("thead", null, h("tr", null,
                h("th", null, "任务类型"), h("th", { className: "num" }, "调用数"),
                h("th", { className: "num" }, "输入"), h("th", { className: "num" }, "费用"))),
              h("tbody", null, byTask.map(function (t) {
                return h("tr", { key: t.task },
                  h("td", { style: { fontWeight: 600 } }, t.task),
                  h("td", { className: "num" }, String(t.api_calls)),
                  h("td", { className: "num" }, fmtTokens(t.input)),
                  h("td", { className: "num" }, fmtUSD(t.est_cost)));
              }))))),
      h("div", { className: "hud-footnote" },
        "口径：主会话读 sessions 表；辅助调用读 session_model_usage.task != ''；" +
        "按 (session, model, task) 去重后合并。日界线 Asia/Shanghai。" +
        (dbUsage.estimated_cost_usd != null
          ? " 全库累计估算 $" + dbUsage.estimated_cost_usd.toFixed(2) + "。"
          : "") +
        " actual_cost_usd 当前无账单数据，所有费用均为估算。"));
  }

  // -------------------------------------------------------------------------
  // 对话记录
  // -------------------------------------------------------------------------

  function SessionsTab() {
    const [q, setQ] = useState("");
    const [days, setDays] = useState(7);
    const { data } = usePoll(API + "/sessions?days=" + days + "&limit=100", 15000);
    const [detail, setDetail] = useState(null); // {loading, data, id}
    const [searchState, searchRun] = useOnce();

    const list = searchState.data ? searchState.data : (data || []);

    function openDetail(sid) {
      setDetail({ loading: true, data: null, id: sid });
      SDK.fetchJSON(API + "/sessions/" + encodeURIComponent(sid))
        .then(function (d) { setDetail({ loading: false, data: d, id: sid }); })
        .catch(function (e) { setDetail({ loading: false, data: null, id: sid, error: String(e) }); });
    }

    return h(React.Fragment, null,
      h("div", { style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" } },
        h(Input, {
          placeholder: "搜索标题 / ID / 用户…", value: q,
          style: { maxWidth: 300, fontSize: 13 },
          onChange: function (e) { setQ(e.target.value); },
          onKeyDown: function (e) {
            if (e.key === "Enter" && q.trim()) { searchRun(API + "/sessions/search?q=" + encodeURIComponent(q.trim())); }
          },
        }),
        h(Button, { size: "sm", variant: "outline", onClick: function () { if (q.trim()) searchRun(API + "/sessions/search?q=" + encodeURIComponent(q.trim())); } }, "搜索"),
        [3, 7, 14].map(function (d) {
          return h(Button, {
            key: d, size: "sm", variant: days === d ? "default" : "outline",
            onClick: function () { setDays(d); setSearchState ? null : null; },
            style: { padding: "2px 10px", fontSize: 12 },
          }, d + " 天");
        }),
        h(Badge, { variant: "secondary" }, searchState.data ? "搜索: " + searchState.data.length + " 条" : (data ? data.length + " 条" : "…"))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(detail && detail.data ? "会话详情" : "会话列表",
          detail && detail.data
            ? h("div", { className: "hud-detail" },
                h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 } },
                  h("div", { style: { fontWeight: 700, fontSize: 14 } }, (detail.data.title || "(无标题)").slice(0, 80)),
                  h(Button, { size: "sm", variant: "outline", onClick: function () { setDetail(null); } }, "返回列表")),
                h("div", { className: "hud-grid hud-grid-4", style: { marginBottom: 8 } },
                  kv("来源", detail.data.source || "-"), kv("模型", detail.data.model || "-"),
                  kv("消息", String(detail.data.message_count || 0)),
                  kv("工具调用", String(detail.data.tool_call_count || 0)),
                  kv("输入", fmtTokens(detail.data.input_tokens)), kv("输出", fmtTokens(detail.data.output_tokens)),
                  kv("估算费用", fmtUSD(detail.data.estimated_cost_usd)),
                  kv("开始", fmtTime(detail.data.started_at))),
                h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.7, margin: "8px 0 4px" } }, "消息预览（正文按需加载，已脱敏）"),
                h("div", { className: "hud-scroll" },
                  (detail.data.messages || []).map(function (m, i) {
                    return h("div", { key: i, className: "msg" },
                      h("span", { style: { fontWeight: 700, marginRight: 6, fontSize: 11, opacity: 0.7 } }, m.role),
                      h("span", { style: { opacity: 0.85 } }, m.preview || "(空)"));
                  })),
                (detail.data.model_usage || []).length ? h("div", null,
                  h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.7, margin: "10px 0 4px" } }, "会话内模型调用"),
                  h("table", { className: "hud-table" },
                    h("thead", null, h("tr", null, h("th", null, "模型"), h("th", null, "任务"),
                      h("th", { className: "num" }, "调用"), h("th", { className: "num" }, "Token"), h("th", { className: "num" }, "费用"))),
                    h("tbody", null, detail.data.model_usage.map(function (u, i) {
                      return h("tr", { key: i },
                        h("td", null, u.model), h("td", null, u.task || "(主)"),
                        h("td", { className: "num" }, String(u.api_calls)),
                        h("td", { className: "num" }, fmtTokens(u.input_tokens)),
                        h("td", { className: "num" }, fmtUSD(u.estimated_cost_usd)));
                    }))))
                : null)
            : detail && detail.loading
              ? empty("加载会话详情…")
              : (list.length === 0 ? empty("无会话记录") :
                h("div", { className: "hud-scroll" },
                  h("table", { className: "hud-table" },
                    h("thead", null, h("tr", null,
                      h("th", null, "标题"), h("th", null, "来源"), h("th", null, "模型"),
                      h("th", { className: "num" }, "消息"), h("th", { className: "num" }, "Token"),
                      h("th", { className: "num" }, "费用"), h("th", null, "开始"))),
                    h("tbody", null, list.map(function (s) {
                      return h("tr", {
                        key: s.id, style: { cursor: "pointer" },
                        onClick: function () { openDetail(s.id); },
                        title: "点击查看详情",
                      },
                        h("td", { style: { maxWidth: 260 } },
                          h("div", { style: { fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                            (s.title || "(无标题)").slice(0, 60)),
                          h("div", { className: "mono", style: { opacity: 0.5, fontSize: 10 } }, s.id.slice(0, 24))),
                        h("td", null, s.source || "-"),
                        h("td", null, s.model || "-"),
                        h("td", { className: "num" }, String(s.message_count || 0)),
                        h("td", { className: "num" }, fmtTokens(s.input_tokens)),
                        h("td", { className: "num" }, fmtUSD(s.estimated_cost_usd)),
                        h("td", { className: "num", style: { fontSize: 11 } }, fmtTime(s.started_at).slice(5)));
                    }))))))));
  }

  // -------------------------------------------------------------------------
  // 记忆
  // -------------------------------------------------------------------------

  function MemoryTab({ snap }) {
    if (!snap) return empty("加载中…");
    const mem = snap.memory || {};
    const files = mem.files || {};
    const locks = mem.locks || {};

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-2" },
        card("记忆文件",
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, "文件"), h("th", { className: "num" }, "大小"),
              h("th", { className: "num" }, "分节"), h("th", null, "更新"))),
            h("tbody", null, Object.keys(files).map(function (name) {
              const f = files[name];
              return h("tr", { key: name },
                h("td", { style: { fontWeight: 600 } }, name),
                h("td", { className: "num" }, f ? fmtBytes(f.bytes) : "-"),
                h("td", { className: "num" }, f ? String(f.sections) : "-"),
                h("td", { className: "num", style: { fontSize: 11 } }, f ? fmtTime(f.mtime) : "-"));
            })))),
        card("Provider 与锁",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 8, padding: 4 } },
            kv("Provider", mem.provider || "builtin"),
            kv("记忆卡片(§ 分节)", String((mem.stats && mem.stats.total_sections) || 0)),
            h("div", null,
              h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.7, marginBottom: 4 } }, "锁文件"),
              Object.keys(locks).length === 0
                ? h("div", { style: { opacity: 0.5, fontSize: 12 } }, "无锁文件")
                : Object.keys(locks).map(function (name) {
                  const l = locks[name];
                  return h("div", { key: name, style: { display: "flex", alignItems: "center", gap: 6, fontSize: 12 } },
                    h("span", { className: "hud-dot " + dotClass(!l.stale, l.stale) }),
                    name + (l.stale ? " — 锁超过 10 分钟未释放!" : " — " + Math.round(l.age) + "s"));
                })))),
      h("div", { className: "hud-footnote" },
        "记忆正文不进总览事件流；此页只展示元数据。写入失败/锁异常由健康规则上报。")));
  }

  // -------------------------------------------------------------------------
  // 定时任务 + 执行历史
  // -------------------------------------------------------------------------

  function CronTab({ snap }) {
    if (!snap) return empty("加载中…");
    const cron = snap.cron || {};
    const jobs = cron.jobs || [];
    const exec = snap.executions || {};
    const runs = exec.executions || [];
    const stats = exec.summary || {};
    const now = Date.now() / 1000;

    const sorted = jobs.slice().sort(function (a, b) { return (a.enabled ? 0 : 1) - (b.enabled ? 0 : 1); });

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-4" },
        card("任务总数", h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(cron.summary ? cron.summary.total : jobs.length))),
        card("启用", h("div", { style: { fontSize: 20, fontWeight: 700, color: "#4ade80" } }, String(cron.summary ? cron.summary.enabled : 0))),
        card("暂停/禁用", h("div", { style: { fontSize: 20, fontWeight: 700, color: "#facc15" } }, String((cron.summary ? cron.summary.paused + cron.summary.disabled : 0)))),
        card("失败中", h("div", { style: { fontSize: 20, fontWeight: 700, color: (cron.summary && cron.summary.failing) ? "#f87171" : undefined } }, String(cron.summary ? cron.summary.failing : 0)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card("任务列表 (" + jobs.length + ")",
          jobs.length === 0 ? empty("无任务") : h("div", { className: "hud-scroll" },
            h("table", { className: "hud-table" },
              h("thead", null, h("tr", null,
                h("th", null, "任务"), h("th", null, "排程"), h("th", null, "下次运行"),
                h("th", { className: "num" }, "上次"), h("th", null, "状态"), h("th", null, "投递"))),
              h("tbody", null, sorted.map(function (j) {
                const ok = j.last_status === "ok" || j.last_status === "completed";
                const bad = j.last_status === "error" || j.last_status === "failed" || (j.failure_streak || 0) > 0;
                return h("tr", { key: j.id },
                  h("td", { style: { maxWidth: 220 } },
                    h("div", { style: { fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, j.name),
                    h("div", { className: "mono", style: { opacity: 0.5, fontSize: 10 } }, j.id)),
                  h("td", { className: "mono", style: { fontSize: 11 } }, j.schedule || "-"),
                  h("td", { className: "num", style: { fontSize: 11 } },
                    j.next_run_at ? (j.next_run_at - now < 3600
                      ? h("b", { style: { color: "#facc15" } }, Math.round((j.next_run_at - now) / 60) + "m 后")
                      : fmtTime(j.next_run_at).slice(5)) : "-")),
                  h("td", { className: "num", style: { fontSize: 11 } }, j.last_run_at ? timeAgo(j.last_run_at * 1000) : "-"),
                  h("td", null,
                    h(Badge, { variant: !j.enabled ? "secondary" : bad ? "destructive" : ok ? "default" : "outline" },
                      !j.enabled ? "暂停" : bad ? (statusZh(j.last_status)) + (j.failure_streak ? "×" + j.failure_streak : "") : statusZh(j.last_status)),
                  h("td", { style: { fontSize: 10.5, opacity: 0.7, maxWidth: 130, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                    j.deliver || "-"));
              }))))),
        card("执行历史 (最近 " + runs.length + " 条)",
          runs.length === 0 ? empty("无执行记录") : h("div", { className: "hud-scroll" },
            h("table", { className: "hud-table" },
              h("thead", null, h("tr", null,
                h("th", null, "任务"), h("th", null, "状态"), h("th", { className: "num" }, "耗时"),
                h("th", null, "开始"), h("th", null, "错误"))),
              h("tbody", null, runs.slice(0, 40).map(function (r) {
                const jobName = (jobs.find(function (j) { return j.id === r.job_id; }) || {}).name || r.job_id;
                return h("tr", { key: r.id },
                  h("td", { style: { maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600 } }, jobName),
                  h("td", null, h(Badge, {
                    variant: r.status === "completed" ? "default" : r.status === "failed" ? "destructive" : "outline",
                  }, statusZh(r.status))),
                  h("td", { className: "num" }, r.duration != null ? Math.round(r.duration) + "s" : "-"),
                  h("td", { className: "num", style: { fontSize: 11 } }, r.started_at ? fmtTime(r.started_at).slice(5) : "-"),
                  h("td", { style: { fontSize: 10.5, opacity: 0.75, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                    r.error || (r.status === "unknown" ? "状态未知 / 孤儿进程" : "-")));
              }))))),

      h("div", { className: "hud-footnote" },
        "执行历史来自 cron/executions.db（claimed→running→completed/failed 状态机）。" +
        "成功率/连续失败统计见后端 rules；编辑/暂停/手动触发请跳转 Dashboard 的 Cron 页。")));
  }

  // -------------------------------------------------------------------------
  // 渠道
  // -------------------------------------------------------------------------

  function ChannelsTab({ snap }) {
    if (!snap) return empty("加载中…");
    const gw = snap.gateway || {};
    const platforms = gw.platforms || {};
    const names = Object.keys(platforms);

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-3" },
        names.length === 0
          ? card("渠道", empty("无渠道数据"))
          : names.map(function (name) {
            const p = platforms[name];
            const connected = p.state === "connected";
            const stale = (p.heartbeat_age || 0) > 60;
            const status = connected ? (stale ? "已连接 · 心跳陈旧" : "已连接") : (stateZh(p.state) || "未知");
            return card(name,
              h("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
                h("div", { style: { display: "flex", alignItems: "center", gap: 8 } },
                  h("span", { className: "hud-dot " + dotClass(connected, stale) }),
                  h("span", { style: { fontSize: 16, fontWeight: 700, color: connected ? (stale ? "#facc15" : "#4ade80") : "#f87171" } }, status)),
                h("div", { className: "hud-grid hud-grid-2" },
                  kv("更新时间", p.updated_at ? fmtTime(p.updated_at) : "-"),
                  kv("心跳龄", p.heartbeat_age != null ? Math.round(p.heartbeat_age) + "s" : "-"),
                  kv("需关注", p.needs_attention ? "是" : "否"),
                  kv("错误码", p.error_code || "-"),
                p.error_message ? h("div", { className: "hud-logline err", style: { whiteSpace: "normal" } }, p.error_message) : null,
                (connected && stale) ? h(Badge, { variant: "warning" },
                  "已连接但持续抖动：" + Math.round(p.heartbeat_age) + "s 无状态更新 — 需结合错误日志判断") : null)));})),
      h("div", { className: "hud-footnote" },
        "渠道状态来自 gateway_state.json。'connected' 是瞬时快照，" +
        "稳定性要结合心跳龄与 errors.log 判定 —— 例如飞书当前 connected 但日志每 ~2 分钟重连。" +
        "重连计数等更细的抖动指标在错误事故页。"));
  }

  // -------------------------------------------------------------------------
  // 错误与事故
  // -------------------------------------------------------------------------

  function IncidentsTab({ snap }) {
    if (!snap) return empty("加载中…");
    const errors = snap.errors || {};
    const logs = snap.logs || {};
    const errLines = ((logs.files && logs.files["errors.log"]) || {}).lines || [];
    const agentLines = ((logs.files && logs.files["agent.log"]) || {}).lines || [];
    // 事故历史来自 telemetry.db（/incidents），当前活跃事故来自健康评估
    const incPoll = usePoll(API + "/incidents", 10000);
    const incidents = (incPoll.data && incPoll.data.incidents) || [];
    const activeNow = (snap._health && snap._health.incidents) || [];

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-4" },
        card("近 30 分钟错误", h("div", {
          style: { fontSize: 20, fontWeight: 700, color: errors.count_30m > 20 ? "#f87171" : undefined },
        }, String(errors.count_30m || 0))),
        card("错误指纹", h("div", { style: { fontSize: 20, fontWeight: 700 } }, String((errors.incidents || []).length))),
        card("活跃事故", h("div", { style: { fontSize: 20, fontWeight: 700 } },
          String(activeNow.length + (incidents || []).filter(function (i) { return i.status === "active"; }).length))),
        card("事故总数", h("div", { style: { fontSize: 20, fontWeight: 700 } }, String((incidents || []).length)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card("事故时间线 (telemetry.db)",
          (incidents || []).length === 0 ? empty("暂无事故记录") :
          h("div", { className: "hud-scroll" },
            (incidents || []).map(function (inc) {
              return h("div", { key: inc.id, className: "hud-incident " + inc.severity + " " + inc.status },
                h("div", { style: { display: "flex", justifyContent: "space-between", gap: 8 } },
                  h("div", { style: { fontWeight: 600, fontSize: 13 } }, inc.title),
                  h(Badge, { variant: inc.status === "active" ? (inc.severity === "critical" ? "destructive" : "warning") : "secondary" },
                    inc.status === "active" ? "进行中" : "已恢复")),
                h("div", { style: { opacity: 0.7, fontSize: 11.5, marginTop: 2 } }, inc.detail),
                h("div", { style: { opacity: 0.55, fontSize: 10.5, marginTop: 4 } },
                  "首次 " + fmtTime(inc.first_seen) + " · 末次 " + fmtTime(inc.last_seen) +
                  " · 观测 " + (inc.observations != null ? inc.observations : inc.count) + " 次" +
                  (inc.fingerprint ? " · " + inc.fingerprint : "")));
            }))),
        card("错误指纹 TOP",
          (errors.incidents || []).length === 0 ? empty("近 30 分钟无错误") :
          h("div", { className: "hud-scroll" },
            (errors.incidents || []).map(function (e) {
              return h("div", { key: e.fingerprint, className: "hud-check" },
                h("span", { className: "hud-dot hud-dot-warn" }),
                h("div", { style: { flex: 1, minWidth: 0 } },
                  h("div", { className: "mono", style: { fontSize: 10.5, opacity: 0.6 } }, e.fingerprint),
                  h("div", { style: { fontSize: 11.5, opacity: 0.85, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, e.sample),
                  h("div", { style: { fontSize: 10.5, opacity: 0.5 } }, "×" + e.count)));
            })))),

      h("div", { className: "hud-grid hud-grid-2" },
        card("errors.log 尾部（脱敏）",
          errLines.length === 0 ? empty("无内容") :
          h("div", { className: "hud-scroll" }, errLines.slice(-40).map(function (l, i) {
            return h("div", { key: i, className: "hud-logline err" }, l);
          }))),
        card("agent.log 尾部（脱敏）",
          agentLines.length === 0 ? empty("无内容") :
          h("div", { className: "hud-scroll" }, agentLines.slice(-40).map(function (l, i) {
            const cls = /error|exception|traceback/i.test(l) ? "err" : /warn/i.test(l) ? "warn" : "info";
            return h("div", { key: i, className: "hud-logline " + cls }, l);
          })))),
      h("div", { className: "hud-footnote" },
        "日志按异常指纹去重聚合；关键字与凭据模式已脱敏；完整原始日志请到 Dashboard 的日志页查看。"));
  }

  // -------------------------------------------------------------------------
  // 系统与存储
  // -------------------------------------------------------------------------

  function SystemTab({ snap }) {
    const [hours, setHours] = useState(6);
    const metrics = usePoll(API + "/metrics?hours=" + hours, 30000).data || [];
    if (!snap) return empty("加载中…");
    const sys = snap.system || {};
    const db = snap.db || {};
    const launchd = snap.launchd || {};
    const dash = snap.dashboard || {};
    const mem = sys.memory || {};
    const sizes = db.sizes || {};

    const cpuSeries = metrics.filter(function (m) { return m.name === "cpu_percent"; }).map(function (m) { return m.value; });
    const memSeries = metrics.filter(function (m) { return m.name === "mem_percent"; }).map(function (m) { return m.value; });
    const diskSeries = metrics.filter(function (m) { return m.name === "disk_free_percent"; }).map(function (m) { return m.value; });

    const dashProcs = dash.procs || [];
    const gwProc = sys.gateway_proc;

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-3" },
        card("CPU / 负载",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv("CPU 使用", fmtPct(sys.cpu_percent)),
            kv("核心数", String(sys.cpu_count || "-")),
            kv("负载", sys.load_avg ? sys.load_avg.join(" / ") : "-"))),
        card("内存",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv("使用率", fmtPct(mem.percent)),
            kv("已用", fmtBytes(mem.used)),
            kv("总计", fmtBytes(mem.total)))),
        card("磁盘 (Hermes 目录)",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv("剩余", fmtPct(sys.disk_free_percent)),
            kv("可用", fmtBytes((sys.disk || {}).free)),
            kv("总容量", fmtBytes((sys.disk || {}).total))),
          h(Badge, { variant: sys.disk_free_percent < 15 ? "warning" : "default" },
            sys.disk_free_percent < 15 ? "磁盘压力" : "正常"))),

      h("div", { className: "hud-grid hud-grid-3" },
        card("进程",
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null, h("th", null, "进程"), h("th", { className: "num" }, "PID"),
              h("th", { className: "num" }, "RSS"), h("th", { className: "num" }, "运行"))),
            h("tbody", null,
              gwProc ? h("tr", { key: "gw" },
                h("td", { style: { fontWeight: 600 } }, "Gateway"),
                h("td", { className: "num" }, String(gwProc.pid)),
                h("td", { className: "num" }, fmtBytes(gwProc.rss)),
                h("td", { className: "num" }, gwProc.uptime_seconds ? Math.round(gwProc.uptime_seconds / 3600) + "h" : "-")) : null,
              dashProcs.map(function (p) {
                return h("tr", { key: p.pid },
                  h("td", { style: { fontWeight: 600 } }, "Dashboard (serve)"),
                  h("td", { className: "num" }, String(p.pid)),
                  h("td", { className: "num" }, fmtBytes(p.rss)),
                  h("td", { className: "num" }, "-"));
              })))),
        card("数据库",
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null, h("th", null, "文件"), h("th", { className: "num" }, "大小"))),
            h("tbody", null, Object.keys(sizes).map(function (name) {
              const s = sizes[name];
              return h("tr", { key: name },
                h("td", { className: "mono" }, name),
                h("td", { className: "num" },
                  s ? fmtBytes(s.bytes) + (s.wal_bytes ? " (+WAL " + fmtBytes(s.wal_bytes) + ")" : "") : "-"));
            })))),
        card("服务托管",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
            h("div", { style: { display: "flex", alignItems: "center", gap: 8 } },
              h("span", { className: "hud-dot " + dotClass(launchd.managed, !launchd.managed) }),
              h("span", { fontWeight: 600 }, launchd.managed ? "launchd 托管" : "未由 launchd 托管")),
            kv("服务定义", launchd.label || "无 plist"),
            launchd.note ? h("div", { className: "mono", style: { fontSize: 10.5, opacity: 0.6 } }, launchd.note) : null,
            !launchd.managed ? h(Badge, { variant: "warning" }, "Gateway 重启后可能不自启 — 建议修复") : null))),

      h("div", { className: "hud-grid hud-grid-3" },
        card("CPU 趋势 (telemetry)",
          cpuSeries.length < 2 ? empty("数据积累中（约 60s 一个点）") :
          h(MiniBars, { values: cpuSeries.slice(-60), height: 80, fmt: function (v) { return "CPU " + v.toFixed(1) + "%"; } })),
        card("内存趋势",
          memSeries.length < 2 ? empty("数据积累中") :
          h(MiniBars, { values: memSeries.slice(-60), height: 80, fmt: function (v) { return "MEM " + v.toFixed(1) + "%"; } })),
        card("磁盘剩余趋势",
          diskSeries.length < 2 ? empty("数据积累中") :
          h(MiniBars, { values: diskSeries.slice(-60), height: 80, fmt: function (v) { return "DISK " + v.toFixed(1) + "%"; } }))),

      h("div", { className: "hud-footnote" },
        "时序数据保存在 ~/.hermes/hud/telemetry.db（分钟级，保留 " +
        (window.HUD_RETENTION || "30") + " 天），不触碰 state.db。"));
  }

  // -------------------------------------------------------------------------
  // 技能
  // -------------------------------------------------------------------------

  function SkillsTab() {
    const { data } = usePoll(API + "/skills", 30000);
    const [cat, setCat] = useState("全部");
    if (!data) return empty("加载中…");
    const skills = data.skills || [];
    const summary = data.summary || {};
    const cats = Object.keys(summary.by_category || {}).sort(function (a, b) {
      return summary.by_category[b] - summary.by_category[a];
    });
    const filtered = cat === "全部" ? skills : skills.filter(function (s) { return s.category === cat; });

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-4" },
        card("技能总数", h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.total || 0))),
        card("分类数", h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.categories || 0))),
        card("近 24h 新增/修改", h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.recent_24h || 0))),
        card("近 7 天活动", h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.recent_7d || 0)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card("分类分布 (" + (summary.categories || 0) + ")",
          cats.length === 0 ? empty("无数据") : h("div", { style: { display: "flex", flexWrap: "wrap", gap: 6 } },
            cats.map(function (c) {
              return h("button", {
                key: c, className: "hud-tab" + (cat === c ? " active" : ""),
                style: { padding: "4px 10px" },
                onClick: function () { setCat(c); },
              }, c + " · " + summary.by_category[c]);
            }))),
        card("分类筛选",
          h("div", { style: { display: "flex", gap: 6, flexWrap: "wrap" } },
            h(Button, { size: "sm", variant: cat === "全部" ? "default" : "outline", onClick: function () { setCat("全部"); } }, "全部 (" + (summary.total || 0) + ")"),
            cats.slice(0, 12).map(function (c) {
              return h(Button, {
                key: c, size: "sm", variant: cat === c ? "default" : "outline",
                onClick: function () { setCat(c); }, style: { fontSize: 11.5 },
              }, c);
            })))),

      card("技能列表 (" + filtered.length + " / " + skills.length + ")",
        filtered.length === 0 ? empty("该分类下无技能") :
        h("div", { className: "hud-scroll" },
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, "技能"), h("th", null, "分类"), h("th", { className: "num" }, "版本"),
              h("th", { className: "num" }, "大小"), h("th", null, "最近修改"), h("th", null, "描述"))),
            h("tbody", null, filtered.slice(0, 150).map(function (s) {
              return h("tr", { key: s.dir },
                h("td", { style: { fontWeight: 600, whiteSpace: "nowrap" } }, s.name),
                h("td", null, s.category),
                h("td", { className: "num" }, s.version || "-"),
                h("td", { className: "num" }, fmtBytes(s.bytes)),
                h("td", { className: "num", style: { fontSize: 11 } }, timeAgo(s.mtime * 1000)),
                h("td", { style: { fontSize: 11, opacity: 0.75, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                  (s.description || "").slice(0, 60)));
            }))))),
      h("div", { className: "hud-footnote" },
        "技能目录 ~/.hermes/skills/（只读扫描 SKILL.md 元数据）。安装/删除请到 Dashboard 的 Skills 页。"));
  }

  // -------------------------------------------------------------------------
  // 设置 / 数据质量
  // -------------------------------------------------------------------------

  function SettingsTab() {
    const { data: settings } = usePoll(API + "/settings", 60000);
    const { data: quality } = usePoll(API + "/data-quality", 30000);
    // Dashboard 菜单语言（浏览器 localStorage hermes-locale，与服务器重启无关）
    const [locale, setLocale] = useState(function () {
      try { return localStorage.getItem("hermes-locale") || "en"; } catch (e) { return "en"; }
    });
    function applyLocale(code) {
      try { localStorage.setItem("hermes-locale", code); } catch (e) {}
      setLocale(code);
      setTimeout(function () { location.reload(); }, 300);
    }

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-2" },
        card("阈值与预算（rules.py）",
          settings ? h("table", { className: "hud-table" },
            h("tbody", null,
              Object.keys(settings.thresholds || {}).map(function (k) {
                return h("tr", { key: k },
                  h("td", { className: "mono", style: { fontSize: 11 } }, k),
                  h("td", { className: "num" }, String(settings.thresholds[k])));
              }),
              Object.keys(settings.retention_days || {}).map(function (k) {
                return h("tr", { key: k },
                  h("td", { className: "mono", style: { fontSize: 11 } }, "retention." + k),
                  h("td", { className: "num" }, settings.retention_days[k] + " 天"));
              })))
            : empty("加载中…")),
        card("采集器数据质量",
          quality ? h("div", { style: { display: "flex", flexDirection: "column", gap: 4 } },
            h("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 4 } },
              h(Badge, { variant: quality.overall === "ok" ? "default" : "warning" },
                quality.overall === "ok" ? "全部采集器正常" : "部分采集器异常"),
              h("span", { style: { fontSize: 11, opacity: 0.6 } }, "采集于 " + fmtTime(quality.collected_at))),
            Object.keys(quality.sections || {}).map(function (name) {
              const err = quality.sections[name];
              return h("div", { key: name, className: "hud-check" },
                h("span", { className: "hud-dot " + (err ? "hud-dot-bad" : "hud-dot-ok") }),
                h("span", { style: { fontWeight: 600, width: 90 } }, name),
                h("span", { style: { opacity: 0.8, fontSize: 11.5 } }, err || "正常"));
            }))
            : empty("加载中…")),
      h("div", { className: "hud-grid hud-grid-2" },
        card("统计时区",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            h("div", { style: { fontSize: 20, fontWeight: 700 } }, (settings && settings.tz) || "-"),
            h("div", { style: { fontSize: 11, opacity: 0.65 } },
              "HUD_TIMEZONE > 系统本地时区 > UTC；快照缓存 TTL " +
              (settings && settings.snapshot_cache_ttl_s) + "s / telemetry 落盘每 " +
              (settings && settings.telemetry_interval_s) + "s 一次"))),
        card("telemetry.db",
          settings ? h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv("指标行", String((settings.telemetry && settings.telemetry.metrics_rows) || 0)),
            kv("事故记录", String((settings.telemetry && settings.telemetry.incidents) || 0)),
            kv("活跃事故", String((settings.telemetry && settings.telemetry.active_incidents) || 0)),
            kv("库大小", fmtBytes((settings.telemetry && settings.telemetry.db_bytes) || 0)))
            : empty("加载中…")),
        card("安全边界",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6, fontSize: 12.5, opacity: 0.85 } },
            h("div", null, "• 默认仅监听 127.0.0.1，沿用 Dashboard 鉴权"),
            h("div", null, "• 不读取/返回 .env、auth.json、完整 token"),
            h("div", null, "• 日志/对话/记忆经脱敏与按需加载"),
            h("div", null, "• telemetry.db 只存聚合、指纹与短摘要"),
            h("div", null, "• 无 outbound 遥测，不自动查询外部账单"),
            h("div", null, "• HUD 纯观察；操作跳转现有 Dashboard 受保护页面")))),
      h("div", { className: "hud-grid hud-grid-2" },
        card("Dashboard 界面语言",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
            h("div", { style: { display: "flex", alignItems: "center", gap: 8 } },
              h("span", { className: "hud-dot " + (locale === "zh" ? "hud-dot-ok" : "hud-dot-warn") }),
              h("span", { style: { fontWeight: 700 } }, locale === "zh" ? "当前：中文菜单" : "当前：英文菜单"),
              h("span", { className: "mono", style: { fontSize: 10.5, opacity: 0.6 } }, "hermes-locale=" + locale)),
            h("div", { style: { display: "flex", gap: 8 } },
              h(Button, { size: "sm", variant: locale === "zh" ? "default" : "outline", onClick: function () { applyLocale("zh"); } }, "固定为中文菜单"),
              h(Button, { size: "sm", variant: locale === "en" ? "default" : "outline", onClick: function () { applyLocale("en"); } }, "固定为英文菜单")),
            h("div", { style: { fontSize: 11.5, opacity: 0.65, lineHeight: 1.5 } },
              "菜单语言保存在浏览器 localStorage，与 Dashboard/系统重启无关。" +
              "若重启后变回英文，多半是浏览器清理了站点数据、使用了无痕窗口，或在不同浏览器切换。" +
              "在此点击按钮即可一键固定（设置后自动刷新页面）。")))),
      h("div", { className: "hud-footnote" },
        "刷新频率：snapshot 2s / usage·metrics 30s / settings·quality 30-60s；" +
        "阈值可用 HUD_* 环境变量覆盖（见后端 rules.py）。")));
  }

  // -------------------------------------------------------------------------
  // 根组件
  // -------------------------------------------------------------------------

  const TABS = [
    { id: "overview", label: "指挥中心", icon: "◉" },
    { id: "live", label: "实时活动", icon: "⚡" },
    { id: "usage", label: "Token·费用", icon: "¥" },
    { id: "sessions", label: "对话记录", icon: "☰" },
    { id: "memory", label: "记忆", icon: "🧠" },
    { id: "skills", label: "技能", icon: "⚒" },
    { id: "cron", label: "定时任务", icon: "⏱" },
    { id: "channels", label: "渠道", icon: "⇄" },
    { id: "incidents", label: "错误·事故", icon: "⚠" },
    { id: "system", label: "系统·存储", icon: "▤" },
    { id: "settings", label: "设置", icon: "⚙" },
  ];

  function HudApp() {
    const [tab, setTab] = useState("overview");
    const { data: snap } = usePoll(API + "/snapshot", 2000);
    const [events, setEvents] = useState([]);
    const [wsState, setWsState] = useState("idle");
    const wsRef = useRef(null);
    const snapRef = useRef(null);
    snapRef.current = snap;

    const health = snap ? snap._health : null;

    // WebSocket 事件流（增强；断线自动退避重连，失败时轮询 snapshot 已兜底）
    useEffect(function () {
      let alive = true;
      let retry = 1000;
      let ws = null;

      function connect() {
        if (!alive) return;
        SDK.buildWsUrl(API + "/events")
          .then(function (url) {
            if (!alive) return;
            ws = new WebSocket(url);
            wsRef.current = ws;
            ws.onopen = function () { if (alive) { setWsState("connected"); retry = 1000; } };
            ws.onmessage = function (evt) {
              if (!alive) return;
              try {
                const msg = JSON.parse(evt.data);
                if (msg.events && msg.events.length) {
                  setEvents(function (prev) {
                    const merged = msg.events.concat(prev);
                    const seen = {};
                    const uniq = [];
                    for (let i = 0; i < merged.length; i++) {
                      const k = evKey(merged[i]);
                      if (!seen[k]) { seen[k] = 1; uniq.push(merged[i]); }
                      if (uniq.length >= 200) break;
                    }
                    return uniq;
                  });
                }
              } catch (e) { /* ignore */ }
            };
            ws.onclose = function () {
              if (!alive) return;
              setWsState("reconnecting");
              setTimeout(connect, retry);
              retry = Math.min(retry * 2, 30000);
            };
            ws.onerror = function () { try { ws.close(); } catch (e) {} };
          })
          .catch(function () {
            if (!alive) return;
            setWsState("fallback");
            setTimeout(connect, Math.min(retry * 2, 30000));
          });
      }
      connect();
      return function () { alive = false; if (ws) { try { ws.close(); } catch (e) {} } };
    }, []);

    // 轮询事件也合并（WS 不可用时仍能看到增量）
    useEffect(function () {
      const evs = snap && snap._events;
      if (evs && evs.length) {
        setEvents(function (prev) {
          const merged = evs.concat(prev);
          const seen = {};
          const uniq = [];
          for (let i = 0; i < merged.length; i++) {
            const k = evKey(merged[i]);
            if (!seen[k]) { seen[k] = 1; uniq.push(merged[i]); }
            if (uniq.length >= 200) break;
          }
          return uniq;
        });
      }
    }, [snap]);

    const gw = (snap && snap.gateway) || {};
    const cronSum = (snap && snap.cron && snap.cron.summary) || {};

    return h("div", { className: "hud-root" },
      // 顶部状态条
      h("div", { className: "hud-header" },
        h("span", { className: "hud-health-badge " + (health ? healthClass(health.overall) : "") },
          (health ? healthLabel(health.overall) : "加载中") +
          (health ? " · " + health.counts.critical + " 红 / " + health.counts.warning + " 黄" : "")),
        kv("Gateway", gw.alive ? "运行中" : "离线"),
        kv("活跃会话", String((snap && snap.active_sessions) ? snap.active_sessions.length : "-")),
        kv("Cron", (cronSum.enabled != null ? cronSum.enabled + " 启用" : "-")),
        kv("模式", wsState === "connected" ? "WS 实时" : (wsState === "reconnecting" ? "WS 重连中" : "轮询"))),

      // Tab 栏
      h("div", { className: "hud-tabs" },
        TABS.map(function (t) {
          return h("button", {
            key: t.id,
            className: "hud-tab" + (tab === t.id ? " active" : ""),
            onClick: function () { setTab(t.id); },
          }, t.icon + " " + t.label);
        })),

      // 内容
      tab === "overview" ? h(Overview, { snap: snap, health: health }) :
      tab === "live" ? h(Live, { snap: snap, events: events, wsState: wsState }) :
      tab === "usage" ? h(Usage, null) :
      tab === "sessions" ? h(SessionsTab, null) :
      tab === "memory" ? h(MemoryTab, { snap: snap }) :
      tab === "skills" ? h(SkillsTab, null) :
      tab === "cron" ? h(CronTab, { snap: snap }) :
      tab === "channels" ? h(ChannelsTab, { snap: snap }) :
      tab === "incidents" ? h(IncidentsTab, { snap: snap }) :
      tab === "system" ? h(SystemTab, { snap: snap }) :
      h(SettingsTab, null));
  }

  // -------------------------------------------------------------------------
  // 注册
  // -------------------------------------------------------------------------

  window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);
})();
