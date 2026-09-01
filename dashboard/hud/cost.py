"""Hermes HUD — Cost Intelligence v1。

回答：Hermes 花了多少钱？花在哪？数据有多可信？
坚持 measured/recorded truth > estimated inference。

Canonical source（Phase 1）：Hermes state.db / session_model_usage（唯一计费源）。
Timeline session.completed 只是同一数据的派生副本 → 只用于导航，不参与汇总。
cost_semantics = "estimated"（estimated_cost_usd 是估算，不是 provider invoice；
UI/API 一律称"估算费用 / Estimated cost"）。
Phase 13：不按网上最新价格重算历史费用——信任 Hermes 已记录值。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("hud.cost")

from .collectors import get_hud_timezone  # noqa: E402
from .redaction import redact_line  # noqa: E402

TIME_RANGES = {"today": None, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400,
               "all": -1}  # today 由时区日界处理；all 无界

_USAGE_COLS = ("session_id", "model", "input_tokens", "output_tokens",
               "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
               "estimated_cost_usd", "actual_cost_usd", "cost_status",
               "cost_source", "first_seen", "last_seen")


def _pricing_known(cost_status: Any, cost_source: Any) -> bool:
    """Provenance contract（依据真实 Hermes 语义，不猜）：

    known pricing provenance：
      cost_status='estimated' 且 cost_source 非空且 != 'none'
      （真实分布：estimated + official_docs_snapshot = 1034 行）
    unknown pricing provenance：
      cost_status='unknown' 且 cost_source='none'
    legacy metadata missing：
      cost_status/cost_source IS NULL（unverifiable——不算 known）

    estimated_cost_usd NOT NULL DEFAULT 0 → 数值存在 ≠ 定价来源可靠。
    """
    if cost_status == "estimated" and cost_source and str(cost_source) != "none":
        return True
    return False


def _state_conn(home: Path):
    db = Path(os.environ.get("HUD_STATE_DB", str(home / "state.db")))
    uri = f"file:{db}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def _rows(home: Path, cutoff: Optional[float], today_start: Optional[float] = None,
          limit: Optional[int] = None) -> tuple[list[tuple], bool]:
    """读 session_model_usage（只读 SQL，cutoff 下推）。返回 (rows, source_ok)。"""
    try:
        con = _state_conn(home)
        where, params = [], []
        if cutoff is not None:
            where.append("last_seen >= ?")
            params.append(cutoff)
        if today_start is not None:
            where.append("last_seen >= ?")
            params.append(today_start)
        sql = f"SELECT {', '.join(_USAGE_COLS)} FROM session_model_usage"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY last_seen DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = con.execute(sql, params).fetchall()
        con.close()
        return rows, True
    except Exception as exc:  # noqa: BLE001
        log.debug("cost: usage unavailable: %s", exc)
        return [], False


def _session_count(home: Path, cutoff: Optional[float]) -> Optional[int]:
    try:
        con = _state_conn(home)
        if cutoff is not None:
            n = con.execute(
                "SELECT COUNT(DISTINCT session_id) FROM session_model_usage"
                " WHERE last_seen >= ?", (cutoff,)).fetchone()[0]
        else:
            n = con.execute(
                "SELECT COUNT(DISTINCT session_id) FROM session_model_usage").fetchone()[0]
        con.close()
        return n
    except Exception:  # noqa: BLE001
        return None


def _cutoff(time_range: str, now: Optional[int] = None) -> tuple[Optional[float], Optional[float]]:
    """返回 (cutoff_epoch, today_start_epoch)；today 用 HUD 时区日界。"""
    import time as _t
    now_ = now if now is not None else _t.time()
    if time_range == "today":
        tz = get_hud_timezone()
        local_now = datetime.fromtimestamp(now_, tz=tz)
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), start.timestamp()
    secs = TIME_RANGES.get(time_range)
    if secs is None or secs < 0:
        return None, None  # all
    return now_ - secs, None


def _sanitize_title(title: Any) -> Optional[str]:
    if not title:
        return None
    return redact_line(str(title))[:120]


def _window_attrs(time_range: str) -> dict:
    """Window attribution truth：Hermes 只存累计 usage row（无 per-call delta）。

    All = lifetime cumulative（window_exact=true）；其他范围 = last_seen 归属
    （window_exact=false——不得声称是 range 内 exact spend）。
    """
    if time_range == "all":
        return {"window_exact": True, "window_attribution": "lifetime_cumulative",
                "window_semantics": "lifetime_cumulative"}
    return {"window_exact": False, "window_attribution": "last_seen",
            "window_semantics": "cumulative usage rows attributed by last activity"}


def compute_summary(home: Path, time_range: str = "7d",
                    now: Optional[int] = None) -> dict:
    """Cost summary（canonical：session_model_usage 单源）。

    Null/Zero truth：源健康+0 花费 → $0.00；源不可用 → null/partial。
    Provenance truth：cost coverage 基于 cost_status/cost_source（pricing
    provenance），禁止用 estimated_cost_usd IS NOT NULL 判断（schema NOT NULL
    DEFAULT 0——数值存在 ≠ 定价可靠）。
    Upstream limitation（Phase 11）：Hermes 当前无 timestamped per-call usage
    events——exact arbitrary-window cost attribution 不可用；非 All 范围是
    last_seen 归属估算。
    """
    cutoff, today_start = _cutoff(time_range, now)
    rows, source_ok = _rows(home, cutoff, today_start)
    usage_rows = len(rows)
    input_tok = output_tok = cache_tok = 0
    cost_total = 0.0
    pricing_known = 0
    for r in rows:
        input_tok += (r[2] or 0)
        output_tok += (r[3] or 0)
        cache_tok += (r[4] or 0)
        if _pricing_known(r[9], r[10]):
            pricing_known += 1
            cost_total += float(r[7] or 0)
        else:
            # unknown / legacy-missing 定价：费用不计入可信总额（不冒充 $0）
            pass
    total_tokens = input_tok + output_tok
    sessions = _session_count(home, cutoff) if source_ok else None
    # cost_complete：0 行（healthy zero）或全部行 pricing known
    cost_complete = bool(source_ok and (usage_rows == 0 or pricing_known == usage_rows))
    ratio = (pricing_known / usage_rows) if usage_rows else (1.0 if source_ok else None)
    if not source_ok:
        cost_total = input_tok = output_tok = total_tokens = cache_tok = None
        pricing_known = usage_rows = None
        ratio = None
    elif usage_rows == 0:
        cost_total = 0.0  # source healthy + 0 spend → $0.00（非 null）
        ratio = 1.0
    coverage = {
        "usage_rows": usage_rows,
        "pricing_known_rows": pricing_known,
        "pricing_unknown_rows": (usage_rows - pricing_known) if usage_rows is not None else None,
        "pricing_coverage_ratio": ratio,
        "cost_complete": bool(cost_complete),
        "source_status": {"usage": "healthy" if source_ok else "unavailable"},
    }
    # Average truth：global cost_complete=false → avg=null（禁止 known/全部 sessions 冒充）
    avg_cost = None
    if cost_complete and sessions:
        avg_cost = cost_total / sessions
    out = {
        "schema_version": 1,
        "range": time_range,
        "estimated_cost_usd": cost_total,
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cache_read_tokens": cache_tok,
        "total_tokens": total_tokens,
        "sessions": sessions,
        "avg_cost_per_session_usd": avg_cost,
        "cost_complete": cost_complete,
        "source_status": "healthy" if source_ok else "unavailable",
        "cost_semantics": "estimated",
        "coverage": coverage,
        "partial": (not source_ok) or (not cost_complete),
    }
    out.update(_window_attrs(time_range))
    return out


def compute_timeseries(home: Path, time_range: str = "7d",
                       now: Optional[int] = None) -> dict:
    """Daily estimated cost 趋势（按 HUD 时区日界分组，Python 侧分组）。"""
    cutoff, today_start = _cutoff(time_range, now)
    rows, source_ok = _rows(home, cutoff, today_start)
    tz = get_hud_timezone()
    days: dict[str, dict[str, float | int]] = {}
    pricing_known_total = 0
    for r in rows:
        ts = r[12] or 0  # last_seen（统一归属约定；禁止 first_seen 分组）
        day = datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")
        d = days.setdefault(day, {"estimated_cost_usd": 0.0, "input_tokens": 0,
                                  "output_tokens": 0})
        if _pricing_known(r[9], r[10]):
            pricing_known_total += 1
            d["estimated_cost_usd"] += float(r[7] or 0)
        d["input_tokens"] += (r[2] or 0)
        d["output_tokens"] += (r[3] or 0)
    series = [{"date": k, **v} for k, v in sorted(days.items())]
    usage_rows = len(rows)
    out = {
        "schema_version": 1, "range": time_range, "points": series,
        "source_status": "healthy" if source_ok else "unavailable",
        "pricing_coverage": {
            "usage_rows": usage_rows,
            "pricing_known_rows": pricing_known_total,
            "pricing_coverage_ratio": (pricing_known_total / usage_rows) if usage_rows else (1.0 if source_ok else None),
            "partial": bool(source_ok and usage_rows and pricing_known_total < usage_rows),
        },
    }
    out.update(_window_attrs(time_range))
    return out


def compute_models(home: Path, time_range: str = "7d",
                   now: Optional[int] = None) -> dict:
    """By-model 聚合。"""
    cutoff, today_start = _cutoff(time_range, now)
    rows, source_ok = _rows(home, cutoff, today_start)
    models: dict[str, dict[str, Any]] = {}
    for r in rows:
        model = r[1] or "unknown"
        m = models.setdefault(model, {"model": model, "input_tokens": 0,
                                      "output_tokens": 0, "total_tokens": 0,
                                      "estimated_cost_usd": 0.0, "sessions": set(),
                                      "pricing_known_rows": 0, "pricing_unknown_rows": 0,
                                      "rows_total": 0})
        m["input_tokens"] += (r[2] or 0)
        m["output_tokens"] += (r[3] or 0)
        m["total_tokens"] += (r[2] or 0) + (r[3] or 0)
        m["rows_total"] += 1
        if _pricing_known(r[9], r[10]):
            m["estimated_cost_usd"] += float(r[7] or 0)
            m["pricing_known_rows"] += 1
        else:
            m["pricing_unknown_rows"] += 1
        m["sessions"].add(r[0])
    out = []
    for m in models.values():
        m["sessions"] = len(m["sessions"])
        m["pricing_coverage_ratio"] = (m["pricing_known_rows"] / m["rows_total"]) if m["rows_total"] else 1.0
        m["cost_complete"] = m["rows_total"] == 0 or m["pricing_known_rows"] == m["rows_total"]
        out.append(m)
    out.sort(key=lambda x: x["estimated_cost_usd"], reverse=True)
    resp = {"schema_version": 1, "range": time_range, "models": out,
            "source_status": "healthy" if source_ok else "unavailable"}
    resp.update(_window_attrs(time_range))
    return resp


def compute_top_sessions(home: Path, time_range: str = "7d", limit: int = 20,
                         now: Optional[int] = None) -> dict:
    """Top sessions by estimated cost（title 走 redaction）。"""
    cutoff, today_start = _cutoff(time_range, now)
    rows, source_ok = _rows(home, cutoff, today_start)
    limit = max(1, min(int(limit), 100))
    sess: dict[str, dict[str, Any]] = {}
    for r in rows:
        sid = r[0]
        s = sess.setdefault(sid, {"session_id": sid, "models": set(),
                                  "estimated_cost_usd": 0.0, "input_tokens": 0,
                                  "output_tokens": 0, "first_seen": None,
                                  "last_seen": None, "title": None,
                                  "pricing_known_rows": 0, "pricing_unknown_rows": 0,
                                  "rows_total": 0})
        s["models"].add(r[1] or "unknown")
        if _pricing_known(r[9], r[10]):
            s["estimated_cost_usd"] += float(r[7] or 0)
            s["pricing_known_rows"] += 1
        else:
            s["pricing_unknown_rows"] += 1
        s["rows_total"] += 1
        s["input_tokens"] += (r[2] or 0)
        s["output_tokens"] += (r[3] or 0)
        if s["first_seen"] is None or r[11] < s["first_seen"]:
            s["first_seen"] = r[11]
        if s["last_seen"] is None or r[12] > s["last_seen"]:
            s["last_seen"] = r[12]
    # 标题（sanitized）——只读 sessions join
    try:
        con = _state_conn(home)
        for sid in sess:
            row = con.execute("SELECT title FROM sessions WHERE id = ?",
                              (sid,)).fetchone()
            if row:
                sess[sid]["title"] = _sanitize_title(row[0])
        con.close()
    except Exception:  # noqa: BLE001
        pass
    out = []
    for s in sess.values():
        s["models"] = sorted(s["models"])
        s["pricing_coverage_ratio"] = (s["pricing_known_rows"] / s["rows_total"]) if s["rows_total"] else 1.0
        s["cost_complete"] = s["rows_total"] == 0 or s["pricing_known_rows"] == s["rows_total"]
        out.append(s)
    out.sort(key=lambda x: x["estimated_cost_usd"], reverse=True)
    resp = {"schema_version": 1, "range": time_range,
            "sessions": out[:limit], "source_status": "healthy" if source_ok else "unavailable"}
    resp.update(_window_attrs(time_range))
    return resp


def compute_budget(home: Path, daily_budget_usd: float, now: Optional[int] = None) -> dict:
    """Budget view：只读复用 daily_budget_usd。

    Budget truth：Today 基于 last_seen 归属（window_exact=false）——累计 usage
    row 无法精确拆分跨天调用 → 不给精确 usage_ratio/remaining；
    budget_status="attribution_uncertain"（等 Hermes 有 per-call 事件再恢复）。
    """
    summary = compute_summary(home, "today", now=now)
    today_cost = summary["estimated_cost_usd"]
    base = {"budget_usd": daily_budget_usd, "today_estimated_cost_usd": today_cost,
            "budget_configured": daily_budget_usd > 0}
    if today_cost is None:
        return {**base, "usage_ratio": None, "remaining_usd": None,
                "budget_status": "unavailable"}
    if daily_budget_usd <= 0:
        return {**base, "usage_ratio": None, "remaining_usd": None,
                "budget_status": "not_configured"}
    # Today 窗口非 exact（累计归属）→ 精确预算比例不可用
    return {**base, "usage_ratio": None, "remaining_usd": None,
            "budget_status": "attribution_uncertain"}
