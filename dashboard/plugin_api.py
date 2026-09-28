"""Hermes HUD — dashboard 插件后端。

挂载在 /api/plugins/hermes-hud/ 下（FastAPI router）。
所有 HTTP 路由都经过 dashboard 的 session-token 鉴权中间件；
WebSocket 用 dashboard 的标准鉴权门（_ws_auth_ok）—— 不发明第二套 token。

数据流：
  collectors.build_snapshot() → rules.evaluate_snapshot() → telemetry 落盘
  → REST /snapshot /health /data-quality + WS /events 增量事件
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status as http_status

# 让同目录的 hud/ 包可导入（api 文件本身由 web_server 动态加载，
# dashboard/ 目录默认不在 sys.path 上）。
_HUD_DIR = Path(__file__).resolve().parent
if str(_HUD_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_HUD_DIR))

from hud import collectors, rules, storage  # noqa: E402
from hud.i18n import resolve_locale  # noqa: E402
from hud.redaction import redact_line  # noqa: E402

log = logging.getLogger(__name__)

router = APIRouter()

store = storage.TelemetryStore()

# ---------------------------------------------------------------------------
# 增量事件检测（内存态）
# ---------------------------------------------------------------------------

_last_snapshot: Optional[dict] = None
# overall 是 normal/warning/critical 代码（与语言无关），事件对比用它，
# 不依赖按语言分桶的快照缓存。
_last_overall: Optional[str] = None
_last_event_emit: float = 0.0

# P1-1：共享 snapshot 缓存 + 单飞锁（REST / WebSocket 不各自重复跑 collector）
_SNAPSHOT_TTL = 2.0
_snapshot_lock = asyncio.Lock()
# locale -> {"data": snap, "ts": float}：TTL 与单飞锁保持不变，只是按语言分桶，
# 两个不同语言的标签页不再互相污染。
_snapshot_cache: dict[str, dict] = {}
# P1-1：telemetry 落盘限频（最大每 60 秒一次，2 秒轮询不写库）
_TELEMETRY_INTERVAL = 60.0
_last_telemetry_ts: float = 0.0


def _detect_events(snap: dict, prev: dict) -> list[dict]:
    """对比两次快照，产出增量事件。prev 为空时只产出现状事件。"""
    events: list[dict] = []
    now = time.time()

    # 渠道状态变化
    pl_new = snap.get("gateway", {}).get("platforms", {}) or {}
    pl_old = (prev or {}).get("gateway", {}).get("platforms", {}) or {}
    for name, p in pl_new.items():
        old = pl_old.get(name)
        if old is None:
            events.append({"type": "channel", "sub": name, "event": "state",
                           "state": p.get("state"), "ts": now})
        elif old.get("state") != p.get("state"):
            events.append({"type": "channel", "sub": name, "event": "state_change",
                           "from": old.get("state"), "to": p.get("state"), "ts": now})

    # cron 状态变化
    jobs_new = {j["id"]: j for j in snap.get("cron", {}).get("jobs", [])}
    jobs_old = {j["id"]: j for j in ((prev or {}).get("cron", {}) or {}).get("jobs", [])}
    for jid, j in jobs_new.items():
        old = jobs_old.get(jid)
        if old is None:
            continue
        if old.get("state") != j.get("state"):
            events.append({"type": "cron", "sub": j.get("name", jid), "event": "state_change",
                           "from": old.get("state"), "to": j.get("state"), "ts": now})
        if (old.get("last_status") or None) != (j.get("last_status") or None):
            events.append({"type": "cron", "sub": j.get("name", jid), "event": "run_finished",
                           "status": j.get("last_status"), "ts": now})

    # 活跃会话增减
    sess_new = {s["id"] for s in snap.get("active_sessions", [])}
    sess_old = {s["id"] for s in ((prev or {}).get("active_sessions", []) or [])}
    for sid in sess_new - sess_old:
        events.append({"type": "session", "sub": sid, "event": "start", "ts": now})
    for sid in sess_old - sess_new:
        events.append({"type": "session", "sub": sid, "event": "end", "ts": now})

    # 健康等级变化（overall 与语言无关，用全局 _last_overall 比对）
    if _last_overall is not None and snap.get("_health"):
        new_lvl = snap["_health"].get("overall")
        if _last_overall != new_lvl:
            events.append({"type": "health", "sub": "overall", "event": "change",
                           "from": _last_overall, "to": new_lvl, "ts": now})

    # gateway 存活变化
    old_alive = bool((prev or {}).get("gateway", {}).get("alive"))
    new_alive = bool(snap.get("gateway", {}).get("alive"))
    if prev is not None and old_alive != new_alive:
        events.append({"type": "gateway", "sub": "gateway", "event": "alive_change",
                       "alive": new_alive, "ts": now})

    return events


def _update_telemetry(snap: dict, health: dict) -> None:
    """把分钟级指标和事故写入 telemetry.db（失败静默）。"""
    sys_ = snap.get("system") or {}
    items: list[tuple[str, float, Optional[dict]]] = []
    if sys_.get("cpu_percent") is not None:
        items.append(("cpu_percent", float(sys_["cpu_percent"]), None))
    mem = sys_.get("memory") or {}
    if mem.get("percent") is not None:
        items.append(("mem_percent", float(mem["percent"]), None))
    if sys_.get("disk_free_percent") is not None:
        items.append(("disk_free_percent", float(sys_["disk_free_percent"]), None))
    gw = snap.get("gateway") or {}
    if gw.get("heartbeat_age") is not None:
        items.append(("gateway_heartbeat_age", float(gw["heartbeat_age"]), None))
    db = snap.get("db") or {}
    today = db.get("today_sessions") or {}
    if today.get("estimated_cost_usd") is not None:
        items.append(("today_est_cost", float(today["estimated_cost_usd"]),
                      {"aux": float(today.get("aux_est_cost") or 0)}))
    if today.get("input_tokens") is not None:
        items.append(("today_input_tokens", float(today["input_tokens"]), None))
    # 渠道心跳
    for name, p in (gw.get("platforms") or {}).items():
        if p.get("heartbeat_age") is not None:
            items.append((f"channel_{name}_heartbeat_age", float(p["heartbeat_age"]), None))
    if items:
        store.record_metrics_batch("sys", items)
    # 事故
    for inc in health.get("incidents", []):
        store.upsert_incident(inc["fingerprint"], inc["severity"], inc["title"], inc["detail"])
    # 恢复不再出现的事故
    active_incs = store.list_incidents(active_only=True)
    now_fps = {i["fingerprint"] for i in health.get("incidents", [])}
    for inc in active_incs:
        if inc["fingerprint"] not in now_fps:
            store.recover_incident(inc["fingerprint"])


def _maybe_telemetry(snap: dict, health: dict) -> None:
    """telemetry 落盘：每 60 秒最多一次（P1-1 限频），并顺带执行每日 maintenance。"""
    global _last_telemetry_ts
    now = time.time()
    if now - _last_telemetry_ts < _TELEMETRY_INTERVAL:
        return
    _last_telemetry_ts = now
    try:
        _update_telemetry(snap, health)
        # P1-2：低频 maintenance（每天最多一次，meta 表记录上次时间）
        store.maintenance()
    except Exception:
        pass


async def _get_snapshot(locale: str = "zh") -> dict:
    """共享快照：2 秒内复用 + 单飞锁，按 locale 分桶。

    REST /snapshot 与 WebSocket /events 共用同一份快照，
    同一时间不会并发重复跑完整 collector，telemetry 落盘也由
    限频统一控制 —— 前端 2 秒级实时体验不变。

    缓存按 resolve_locale() 归一化后的语言分桶：两个标签页开不同语言时
    各取各的那份，不再互相污染（单飞锁仍是全局一把，TTL 仍是 2 秒）。
    落盘走 incidents[].title/detail（恒 zh，见 rules._inc_text），与触发
    本次刷新的语言无关。
    """
    global _last_snapshot, _last_overall
    cache = _snapshot_cache.setdefault(locale, {"data": None, "ts": 0.0})
    now = time.time()
    if cache["data"] is not None and now - cache["ts"] < _SNAPSHOT_TTL:
        return cache["data"]
    async with _snapshot_lock:
        # 双检：等待锁期间可能已被其他协程填充
        if cache["data"] is not None and time.time() - cache["ts"] < _SNAPSHOT_TTL:
            return cache["data"]
        snap = await asyncio.to_thread(collectors.build_snapshot, locale)
        health = rules.evaluate_snapshot(snap, locale)
        events = _detect_events(snap, _last_snapshot)
        snap["_health"] = health
        snap["_events"] = events
        _maybe_telemetry(snap, health)
        _last_snapshot = snap
        _last_overall = health.get("overall")
        cache["data"] = snap
        cache["ts"] = time.time()
        return snap


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------

@router.get("/snapshot")
async def get_snapshot(locale: str = "zh") -> dict:
    """全量快照（约 2 秒刷新频率由前端控制，共享缓存 + 单飞）。"""
    return await _get_snapshot(resolve_locale(locale))


@router.get("/timeline")
async def get_timeline(limit: int = 100, before: int | None = None,
                       before_id: str | None = None, after: int | None = None,
                       session_id: str | None = None,
                       event_type: str | None = None, status: str | None = None,
                       skill: str | None = None) -> dict:
    """Agent Timeline v1：分页查询（limit ≤ 100，limit+1 判断 has_more）。

    cursor = (before, before_id)——同 timestamp 下以 event_id 精确续页不重不漏。
    先触发增量采集（幂等），再查询——新事件进入后前端可直接 prepend。
    """
    limit = max(1, min(limit, 100))
    try:
        from hud import timeline
        home = Path(collectors.HERMES_HOME)
        timeline.collect_timeline(home, store)
    except Exception as exc:  # noqa: BLE001 采集失败不阻断查询（empty/partial 安全）
        print(f"HUD timeline collect failed: {exc}", file=sys.stderr)
    rows = store.query_timeline(
        limit=limit + 1, before=before, before_id=before_id, after=after,
        session_id=session_id, event_type=event_type, status=status, skill=skill)
    has_more = len(rows) > limit
    return {"events": rows[:limit], "has_more": has_more, "limit": limit}


@router.get("/timeline/stats")
async def get_timeline_stats() -> dict:
    """Timeline 汇总（总量 + 类型分布）。"""
    try:
        return store.timeline_stats()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/health")
async def get_health(locale: str = "zh") -> dict:
    """健康评估 + API 版本契约（Desktop 协商用）。

    直接取该 locale 的快照缓存（同一把单飞锁 + 2s TTL）：过期即重算，
    不会因为只有别的语言在轮询 /snapshot 而一直返回旧状态。
    """
    from hud import version
    snap = await _get_snapshot(resolve_locale(locale))
    out = dict(snap["_health"])
    out.update(version.api_version_payload())
    return out


@router.get("/data-quality")
async def get_data_quality(locale: str = "zh") -> dict:
    """数据新鲜度与采集器健康状态。"""
    snap = await _get_snapshot(resolve_locale(locale))
    sections = {
        "gateway": snap.get("gateway", {}).get("error"),
        "system": snap.get("system", {}).get("error"),
        "db": snap.get("db", {}).get("error"),
        "cron": snap.get("cron", {}).get("error"),
        "executions": snap.get("executions", {}).get("error"),
        "logs": snap.get("logs", {}).get("error"),
        "errors": snap.get("errors", {}).get("error"),
        "memory": snap.get("memory", {}).get("error"),
        "launchd": snap.get("launchd", {}).get("error"),
        "dashboard": snap.get("dashboard", {}).get("error"),
    }
    return {
        "collected_at": snap.get("collected_at"),
        "tz": snap.get("tz"),
        "sections": sections,
        "overall": "ok" if not any(sections.values()) else "partial",
    }


@router.get("/sessions")
async def get_sessions(days: int = Query(7, ge=1, le=90),
                       limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    """最近会话摘要。"""
    return await asyncio.to_thread(collectors.collect_recent_sessions, days, limit)


@router.get("/sessions/search")
async def search_sessions(q: str = Query(..., min_length=1),
                          limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    """按标题/ID 搜索会话。"""
    return await asyncio.to_thread(collectors.search_sessions, q, limit)


@router.get("/usage")
async def get_usage(days: int = Query(30, ge=1, le=365)) -> dict:
    """Token/费用聚合（按天/模型/辅助任务）。"""
    return await asyncio.to_thread(collectors.collect_usage, days)


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str) -> dict:
    """单会话详情（含消息摘要与 model usage）。"""
    detail = await asyncio.to_thread(collectors.collect_session_detail, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="session not found")
    return detail


@router.get("/metrics")
async def get_metrics(kind: str = Query("sys"),
                      name: Optional[str] = Query(None),
                      hours: int = Query(6, ge=1, le=24 * 30)) -> list[dict]:
    """telemetry.db 时序指标。"""
    since = int(time.time()) - hours * 3600
    return store.query_metrics(kind, name, since=since)


@router.get("/incidents")
async def get_incidents(active_only: bool = Query(False),
                        limit: int = Query(100, ge=1, le=500)) -> dict:
    """事故时间线（含已恢复）。"""
    return {
        "incidents": store.list_incidents(active_only=active_only, limit=limit),
        "stats": store.stats(),
    }


@router.get("/tool-events")
async def get_tool_events(limit: int = Query(60, ge=1, le=300)) -> list[dict]:
    """最近工具调用事件（轻量版，从 messages 推断）。"""
    return await asyncio.to_thread(collectors.collect_tool_events, limit)


@router.get("/skills")
async def get_skills(locale: str = "zh") -> dict:
    """技能目录统计（~/.hermes/skills 元数据，只读）。"""
    return await asyncio.to_thread(collectors.collect_skills, resolve_locale(locale))


@router.get("/skills/analytics")
async def get_skill_analytics(range: str = "7d", status: str | None = None,
                              provenance: str | None = None,
                              observed: str | None = None,
                              search: str | None = None, sort: str = "name",
                              limit: int = 50, offset: int = 0) -> dict:
    """Skill Analytics v1：inventory × runtime join（observed truth only）。

    任一源失败 → partial result（不 500）。limit ≤ 200、offset ≥ 0；
    非法 range → 400（不静默退化为 all）。
    """
    from hud import skill_analytics
    if range not in skill_analytics.TIME_RANGES:
        raise HTTPException(status_code=400,
                            detail=f"invalid range: {range} (24h|7d|30d|all)")
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    try:
        return await asyncio.to_thread(
            skill_analytics.query_skills, store, time_range=range, status=status,
            provenance=provenance, observed=observed, search=search, sort=sort,
            limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "skills": [], "total": 0}


@router.get("/skills/analytics/summary")
async def get_skill_analytics_summary(range: str = "7d") -> dict:
    """Summary cards 数据（非法 range → 400）。"""
    from hud import skill_analytics
    if range not in skill_analytics.TIME_RANGES:
        raise HTTPException(status_code=400,
                            detail=f"invalid range: {range} (24h|7d|30d|all)")
    try:
        return await asyncio.to_thread(
            skill_analytics.compute_summary, store, time_range=range)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/skills/analytics/{skill}")
async def get_skill_analytics_detail(skill: str, range: str = "7d",
                                     timeline_limit: int = 20) -> dict:
    """单 skill 详情（含最近 timeline 事件，直接引用不复制）。"""
    from hud import skill_analytics
    if range not in skill_analytics.TIME_RANGES:
        raise HTTPException(status_code=400,
                            detail=f"invalid range: {range} (24h|7d|30d|all)")
    timeline_limit = max(1, min(int(timeline_limit), 100))
    try:
        return await asyncio.to_thread(
            skill_analytics.single_skill, store, skill, time_range=range,
            timeline_limit=timeline_limit)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/cost/summary")
async def get_cost_summary(range: str = "7d") -> dict:
    """Cost Intelligence v1：汇总（canonical = session_model_usage 单源）。

    任一源异常 → partial/unavailable（不 500）；聚合走 to_thread 不阻塞 loop。
    """
    from hud import cost
    if range not in cost.TIME_RANGES:
        raise HTTPException(status_code=400,
                            detail=f"invalid range: {range} (today|24h|7d|30d|all)")
    home = Path(collectors.HERMES_HOME)
    return await asyncio.to_thread(cost.compute_summary, home, range)


@router.get("/cost/timeseries")
async def get_cost_timeseries(range: str = "7d") -> dict:
    """Daily estimated cost 趋势（HUD 时区日界）。"""
    from hud import cost
    if range not in cost.TIME_RANGES:
        raise HTTPException(status_code=400,
                            detail=f"invalid range: {range} (today|24h|7d|30d|all)")
    home = Path(collectors.HERMES_HOME)
    return await asyncio.to_thread(cost.compute_timeseries, home, range)


@router.get("/cost/models")
async def get_cost_models(range: str = "7d") -> dict:
    """By-model 聚合。"""
    from hud import cost
    if range not in cost.TIME_RANGES:
        raise HTTPException(status_code=400,
                            detail=f"invalid range: {range} (today|24h|7d|30d|all)")
    home = Path(collectors.HERMES_HOME)
    return await asyncio.to_thread(cost.compute_models, home, range)


@router.get("/cost/sessions")
async def get_cost_sessions(range: str = "7d", limit: int = 20) -> dict:
    """Top sessions by estimated cost（title 脱敏）。"""
    from hud import cost
    if range not in cost.TIME_RANGES:
        raise HTTPException(status_code=400,
                            detail=f"invalid range: {range} (today|24h|7d|30d|all)")
    home = Path(collectors.HERMES_HOME)
    return await asyncio.to_thread(cost.compute_top_sessions, home, range, limit)


@router.get("/cost/budget")
async def get_cost_budget() -> dict:
    """Budget view（只读复用 daily_budget_usd；不告警不修改）。"""
    from hud import cost
    home = Path(collectors.HERMES_HOME)
    return await asyncio.to_thread(cost.compute_budget, home, rules.DAILY_BUDGET_USD)


@router.get("/settings")
async def get_settings() -> dict:
    """HUD 自身配置/阈值（只读展示）+ API 版本契约。"""
    from hud import version
    out = {
        "api_schema_version": version.HUD_API_SCHEMA_VERSION,
        "plugin_version": version.get_plugin_version(),
        "thresholds": {
            "disk_free_critical": rules.DISK_FREE_CRITICAL,
            "disk_free_warn": rules.DISK_FREE_WARN,
            "mem_pressure_warn": rules.MEM_PRESSURE_WARN,
            "heartbeat_critical_s": rules.HEARTBEAT_CRITICAL,
            "error_burst_warn": rules.ERROR_BURST_WARN,
            "cycle_fail_critical": rules.CYCLE_FAIL_CRITICAL,
            "daily_budget_usd": rules.DAILY_BUDGET_USD,
            "budget_warn_ratio": rules.BUDGET_WARN_RATIO,
        },
        "retention_days": {
            "metrics": storage.METRIC_RETENTION_DAYS,
            "incidents": storage.INCIDENT_RETENTION_DAYS,
        },
        "telemetry": store.stats(),
        "env_overrides": [k for k in os.environ if k.startswith("HUD_")],
        "tz": collectors.hud_tz_name(),
        "snapshot_cache_ttl_s": _SNAPSHOT_TTL,
        "telemetry_interval_s": _TELEMETRY_INTERVAL,
    }
    return out


# ---------------------------------------------------------------------------
# WebSocket 事件流
# ---------------------------------------------------------------------------

@router.websocket("/events")
async def stream_events(ws: WebSocket):
    """2 秒推送一次增量事件 + 健康摘要。

    鉴权委托给 dashboard 的标准 WS 门（_ws_auth_ok），兼容 loopback
    token / gated ticket / internal 三种模式。

    locale：WS 推送内容本身不含翻译文案（health 只带 overall/counts 两个状态
    码，文案由前端 tt() 渲染），但 WS 和 REST /snapshot 共用同一份
    _get_snapshot() 缓存 + _maybe_telemetry() 落盘。不传 locale 会导致落盘的
    incident title/detail 用默认 zh 渲染，即使浏览器语言是别的——所以这里仍
    要从 query string 读 locale 并往下传，即便 WS 自己用不上翻译后的文本。
    """
    from hermes_cli.web_server import _ws_auth_ok
    if not _ws_auth_ok(ws):
        await ws.close(code=http_status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()
    locale = resolve_locale(ws.query_params.get("locale"))
    try:
        while True:
            snap = await _get_snapshot(locale)
            health = snap["_health"]
            events = snap.get("_events", [])
            try:
                from hud import version as _hud_version
                await ws.send_json({
                    "schema_version": _hud_version.HUD_API_SCHEMA_VERSION,
                    "ts": time.time(),
                    "health": {"overall": health["overall"], "counts": health["counts"]},
                    "events": events[-20:],
                    "gateway_alive": bool((snap.get("gateway") or {}).get("alive")),
                    "active_agents": (snap.get("gateway") or {}).get("active_agents", 0),
                    "active_sessions": len(snap.get("active_sessions", [])),
                    "platforms": {
                        k: {"state": v.get("state"), "heartbeat_age": v.get("heartbeat_age")}
                        for k, v in ((snap.get("gateway") or {}).get("platforms") or {}).items()
                    },
                    "cron_summary": (snap.get("cron") or {}).get("summary", {}),
                })
            except Exception:
                break
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

