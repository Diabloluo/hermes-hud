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
from hud.redaction import redact_line  # noqa: E402

log = logging.getLogger(__name__)

router = APIRouter()

store = storage.TelemetryStore()

# ---------------------------------------------------------------------------
# 增量事件检测（内存态）
# ---------------------------------------------------------------------------

_last_snapshot: Optional[dict] = None
_last_health: Optional[dict] = None
_last_event_emit: float = 0.0

# P1-1：共享 snapshot 缓存 + 单飞锁（REST / WebSocket 不各自重复跑 collector）
_SNAPSHOT_TTL = 2.0
_snapshot_lock = asyncio.Lock()
_snapshot_cache: dict = {"data": None, "ts": 0.0}
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

    # 健康等级变化
    if _last_health and snap.get("_health"):
        old_lvl = _last_health.get("overall")
        new_lvl = snap["_health"].get("overall")
        if old_lvl != new_lvl:
            events.append({"type": "health", "sub": "overall", "event": "change",
                           "from": old_lvl, "to": new_lvl, "ts": now})

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


async def _get_snapshot() -> dict:
    """共享快照：2 秒内复用 + 单飞锁。

    REST /snapshot 与 WebSocket /events 共用同一份快照，
    同一时间不会并发重复跑完整 collector，telemetry 落盘也由
    限频统一控制 —— 前端 2 秒级实时体验不变。
    """
    global _last_snapshot, _last_health
    cache = _snapshot_cache
    now = time.time()
    if cache["data"] is not None and now - cache["ts"] < _SNAPSHOT_TTL:
        return cache["data"]
    async with _snapshot_lock:
        # 双检：等待锁期间可能已被其他协程填充
        if cache["data"] is not None and time.time() - cache["ts"] < _SNAPSHOT_TTL:
            return cache["data"]
        snap = await asyncio.to_thread(collectors.build_snapshot)
        health = rules.evaluate_snapshot(snap)
        events = _detect_events(snap, _last_snapshot)
        snap["_health"] = health
        snap["_events"] = events
        _maybe_telemetry(snap, health)
        _last_snapshot = snap
        _last_health = health
        cache["data"] = snap
        cache["ts"] = time.time()
        return snap


# ---------------------------------------------------------------------------
# HTTP 端点
# ---------------------------------------------------------------------------

@router.get("/snapshot")
async def get_snapshot() -> dict:
    """全量快照（约 2 秒刷新频率由前端控制，共享缓存 + 单飞）。"""
    return await _get_snapshot()


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
async def get_health() -> dict:
    """只跑健康评估（轻量，不重算快照）。"""
    if _last_health is not None:
        return _last_health
    snap = await _get_snapshot()
    return snap["_health"]


@router.get("/data-quality")
async def get_data_quality() -> dict:
    """数据新鲜度与采集器健康状态。"""
    snap = await _get_snapshot()
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
async def get_skills() -> dict:
    """技能目录统计（~/.hermes/skills 元数据，只读）。"""
    return await asyncio.to_thread(collectors.collect_skills)


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
        return skill_analytics.query_skills(
            store, time_range=range, status=status, provenance=provenance,
            observed=observed, search=search, sort=sort, limit=limit, offset=offset)
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
        return skill_analytics.compute_summary(store, time_range=range)
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
        return skill_analytics.single_skill(store, skill, time_range=range,
                                            timeline_limit=timeline_limit)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/settings")
async def get_settings() -> dict:
    """HUD 自身配置/阈值（只读展示）。"""
    return {
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


# ---------------------------------------------------------------------------
# WebSocket 事件流
# ---------------------------------------------------------------------------

@router.websocket("/events")
async def stream_events(ws: WebSocket):
    """2 秒推送一次增量事件 + 健康摘要。

    鉴权委托给 dashboard 的标准 WS 门（_ws_auth_ok），兼容 loopback
    token / gated ticket / internal 三种模式。
    """
    from hermes_cli.web_server import _ws_auth_ok
    if not _ws_auth_ok(ws):
        await ws.close(code=http_status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()
    try:
        while True:
            snap = await _get_snapshot()
            health = snap["_health"]
            events = snap.get("_events", [])
            try:
                await ws.send_json({
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

