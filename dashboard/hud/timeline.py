"""Hermes HUD — Agent Timeline v1。

统一事件模型（agent-agnostic observability schema v1）：
  字段不存在 → null（禁止猜）；Hermes-specific 字段不进入核心模型。
事件类型（v1）：session.* / skill.* / tool.* / incident.*
数据源（全部只读/复用现有，绝不修改 Hermes core 数据）：
  - session.* / tool.*  ← state.db（只读查询）
  - skill.*            ← job-ledger（~/.hermes/job-ledger/jobs.jsonl，HUD 生态审计）
  - incident.*         ← telemetry.db incidents（HUD 自有）
隐私：默认不记录 prompt/response/stdout/stderr/含密钥命令行/完整路径；
      summary 只允许 sanitized 短元数据（复用 redaction.py）。
幂等：event_id = sha256(source|source_record_id|event_type|ts)[:24]，
      存储层 INSERT OR IGNORE；同源记录重复采集不产生重复事件。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .redaction import redact_line  # 复用 HUD 现有 redaction utility

log = logging.getLogger("hud.timeline")

# v1 事件类型白名单（现有数据不可靠区分的不生成）
VALID_EVENT_TYPES = {
    "session.started", "session.completed",
    "skill.completed", "skill.failed",
    "tool.called", "tool.completed", "tool.failed",
    "incident.opened", "incident.resolved",
}

STATE_DB_URI = "file:{home}/state.db?mode=ro"
JOB_LEDGER = Path.home() / ".hermes" / "job-ledger" / "jobs.jsonl"

_ALNUM = re.compile(r"[^A-Za-z0-9_./:-]+")


def deterministic_event_id(source: str, source_record_id: str, event_type: str,
                           ts: int) -> str:
    """deterministic event_id：同源同记录同类型同时刻 → 同一 id（幂等依据）。"""
    raw = f"{source}|{source_record_id}|{event_type}|{ts}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _safe_summary(parts: list[Any]) -> str:
    """summary 只允许 sanitized 短元数据。"""
    text = " ".join(str(p) for p in parts if p not in (None, ""))
    return redact_line(text)[:160]


def normalize_event(raw: dict) -> dict:
    """规范化原始记录 → 统一事件模型；未知字段一律 null，不猜。"""
    ts = raw.get("timestamp")
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        ts = None
    event_type = raw.get("event_type")
    if event_type not in VALID_EVENT_TYPES:
        event_type = None
    src = raw.get("source", "hermes")
    rec_id = raw.get("source_record_id") or raw.get("event_id")
    event = {
        "event_id": raw.get("event_id") or (
            deterministic_event_id(src, str(rec_id or ""), str(event_type or ""), ts or 0)
            if rec_id and ts else None),
        "timestamp": ts,
        "event_type": event_type,
        "status": raw.get("status") if raw.get("status") in ("success", "failed", "opened",
                                                             "resolved", "started", "called",
                                                             "completed") else "success",
        "agent_id": None,  # v1：无多 agent 数据
        "session_id": raw.get("session_id") or None,
        "skill": raw.get("skill") or None,
        "tool": raw.get("tool") or None,
        "tool_call_id": raw.get("tool_call_id") or None,
        "duration_ms": _int_or_none(raw.get("duration_ms")),
        "tokens": _int_or_none(raw.get("tokens")),
        "cost_usd": _float_or_none(raw.get("cost_usd")),
        "incident_id": raw.get("incident_id") or None,
        "summary": _safe_summary([raw.get("summary")]),
        "source": src,
        "correlation_id": raw.get("correlation_id") or None,
        "source_record_id": str(rec_id) if rec_id else None,
    }
    return event


def _int_or_none(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 采集器（增量：last_scan 记录于 telemetry meta；force=True 全量重采）
# ---------------------------------------------------------------------------

def _state_conn(home: Path):
    # HUD_STATE_DB 允许指向真实 state.db（只读演示/测试；默认 $HERMES_HOME/state.db）
    db = Path(os.environ.get("HUD_STATE_DB", str(home / "state.db")))
    uri = f"file:{db}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def collect_session_events(home: Path, after_ts: int = 0) -> list[dict]:
    """session.started / session.completed ← state.db sessions（只读）。

    增量正确性：查询按 started_at >= watermark **或** ended_at >= watermark——
    started 早于 watermark、ended 晚于 watermark 的 session 的 completed 事件
    必须能在后续扫描被发现（不能只按 started_at 过滤）。
    token/cost 真实性：started 事件恒为 null；completed 只带可靠聚合
    （无 usage row → SUM 为 NULL → null，禁止 COALESCE 0 冒充零成本）。
    duration_ms = (ended_at - started_at) × 1000（epoch 秒差换算毫秒）。
    """
    out = []
    try:
        con = _state_conn(home)
        rows = con.execute(
            "SELECT id, source, model, started_at, ended_at, title,"
            " (SELECT SUM(input_tokens+output_tokens) FROM session_model_usage"
            " WHERE session_id=sessions.id),"
            " (SELECT SUM(estimated_cost_usd) FROM session_model_usage"
            " WHERE session_id=sessions.id)"
            " FROM sessions WHERE started_at >= ? OR ended_at >= ?"
            " ORDER BY started_at",
            (after_ts, after_ts)).fetchall()
        con.close()
    except Exception as exc:  # noqa: BLE001
        log.debug("timeline: sessions unavailable: %s", exc)
        return out
    for sid, source, model, started_at, ended_at, title, tokens, cost in rows:
        started_at = int(started_at or 0)
        if started_at:
            out.append(normalize_event({
                "timestamp": started_at, "event_type": "session.started",
                "status": "started", "session_id": sid, "skill": None,
                "summary": f"Session started ({model or 'unknown'})",
                "source": "hermes", "source_record_id": f"session:{sid}:started",
                "correlation_id": f"session:{sid}",
                "tokens": None, "cost_usd": None,  # started 无时间点上的聚合
            }))
        if ended_at:
            ended_at = int(ended_at)
            out.append(normalize_event({
                "timestamp": ended_at, "event_type": "session.completed",
                "status": "completed", "session_id": sid,
                "summary": f"Session completed ({model or 'unknown'}, {title or ''})",
                "source": "hermes", "source_record_id": f"session:{sid}:completed",
                "correlation_id": f"session:{sid}",
                "duration_ms": int((ended_at - started_at) * 1000),
                "tokens": int(tokens) if tokens is not None else None,
                "cost_usd": float(cost) if cost is not None else None,
            }))
    return out


def collect_tool_events(home: Path, after_ts: int = 0) -> list[dict]:
    """tool.called / tool.completed / tool.failed ← state.db messages（只读）。

    以 messages 行的 tool_name/tool_call_id/finish_reason 为可靠依据；
    只取明确含 tool 调用的行；summary 只含 tool 名（无参数、无输出）。
    """
    out = []
    try:
        con = _state_conn(home)
        rows = con.execute(
            "SELECT session_id, tool_name, tool_call_id, timestamp, finish_reason, role"
            " FROM messages WHERE timestamp >= ? AND"
            " (tool_name IS NOT NULL AND tool_name != '' OR role = 'tool')"
            " ORDER BY timestamp", (after_ts,)).fetchall()
        con.close()
    except Exception as exc:  # noqa: BLE001
        log.debug("timeline: tools unavailable: %s", exc)
        return out
    for sid, tool_name, call_id, ts, finish_reason, role in rows:
        if not tool_name and role == "tool":
            continue  # 无工具名的 tool 消息（纯输出）不生成事件
        ts = int(ts or 0)
        if not ts:
            continue
        call_id = call_id or f"{sid}:{tool_name}:{ts}"
        if role == "tool":
            etype, status, summary = "tool.completed", "completed", f"Tool {tool_name} completed"
        elif finish_reason:
            if "error" in str(finish_reason).lower() or "fail" in str(finish_reason).lower():
                etype, status, summary = "tool.failed", "failed", f"Tool {tool_name} failed"
            else:
                etype, status, summary = "tool.called", "called", f"Tool {tool_name} called"
        else:
            etype, status, summary = "tool.called", "called", f"Tool {tool_name} called"
        out.append(normalize_event({
            "timestamp": ts, "event_type": etype, "status": status,
            "session_id": sid, "tool": tool_name, "tool_call_id": call_id,
            "summary": summary, "source": "hermes",
            "source_record_id": f"tool:{call_id}:{etype}",
            "correlation_id": f"session:{sid}",
        }))
    return out


def collect_incident_events(storage, after_ts: int = 0) -> list[dict]:
    """incident.opened / incident.resolved ← telemetry.db incidents（HUD 自有）。

    真实性：resolved 只从**显式 resolution timestamp**（记录含 resolved_at 字段）
    生成；last_seen 是最后观测时间，禁止用来猜 resolved 时间。
    当前 incidents 表无 resolved_at 列 → 常规路径只生成 incident.opened。
    """
    out = []
    try:
        con = storage._connect().__enter__()
        # 兼容未来 schema：若 incidents 表有 resolved_at 列则读取
        cols = [r[1] for r in con.execute("PRAGMA table_info(incidents)")]
        has_resolved_at = "resolved_at" in cols
        if has_resolved_at:
            rows = con.execute(
                "SELECT id, fingerprint, severity, title, first_seen, last_seen, status,"
                " resolved_at FROM incidents WHERE first_seen >= ? OR last_seen >= ?",
                (after_ts, after_ts)).fetchall()
        else:
            rows = con.execute(
                "SELECT id, fingerprint, severity, title, first_seen, last_seen, status"
                " FROM incidents WHERE first_seen >= ? OR last_seen >= ?",
                (after_ts, after_ts)).fetchall()
    except Exception as exc:  # noqa: BLE001
        log.debug("timeline: incidents unavailable: %s", exc)
        return out
    for row in rows:
        if has_resolved_at:
            iid, fp, severity, title, first_seen, last_seen, status, resolved_at = row
        else:
            iid, fp, severity, title, first_seen, last_seen, status = row
            resolved_at = None
        out.append(normalize_event({
            "timestamp": int(first_seen), "event_type": "incident.opened",
            "status": "opened", "incident_id": str(iid),
            "summary": f"Incident opened: {title}",
            "source": "hud", "source_record_id": f"incident:{fp}:opened",
            "correlation_id": f"incident:{fp}", "skill": None, "tool": None,
        }))
        if status == "recovered" and resolved_at:
            out.append(normalize_event({
                "timestamp": int(resolved_at), "event_type": "incident.resolved",
                "status": "resolved", "incident_id": str(iid),
                "summary": f"Incident resolved: {title}",
                "source": "hud", "source_record_id": f"incident:{fp}:resolved",
                "correlation_id": f"incident:{fp}", "skill": None, "tool": None,
            }))
    return out


def _parse_ts(v: Any) -> Optional[int]:
    """epoch 秒或 ISO 时间戳 → epoch 秒；无法解析 → None。"""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(str(v)).timestamp())
    except ValueError:
        return None


def collect_skill_events(home: Path, after_ts: int = 0) -> list[dict]:
    """skill.completed / skill.failed ← job-ledger（HUD 生态审计记录）。

    真实性：仅当记录含**明确 skill identity**（skill 字段）才生成 skill.*；
    project/task 不是 skill 身份，不冒充。无 job-ledger 或缺失 skill 字段
    → 不生成（合法状态）。
    """
    out = []
    ledger = Path(home) / "job-ledger" / "jobs.jsonl"
    if not ledger.exists():
        return out
    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            skill = rec.get("skill")
            if not skill:
                continue  # 无明确 skill identity → 不生成
            event = rec.get("event", "finished")
            router = str(rec.get("router", "pass"))
            guard = str(rec.get("guard", "pass"))
            failed = event == "failed" or "fail" in router or "fail" in guard
            status = "failed" if failed else "completed"
            # 完成/失败事件时间：finished_at 优先（唯一合法时间）；无对应时间 → 不生成
            ts = _parse_ts(rec.get("finished_at"))
            if ts is None:
                continue
            if ts < after_ts:
                continue
            task = rec.get("task", "")
            job_id = rec.get("job_id") or rec.get("id") or f"job:{ts}"
            out.append(normalize_event({
                "timestamp": ts, "event_type": f"skill.{status}", "status": status,
                "skill": str(skill), "summary": f"Skill {skill} {status}: {task}"[:160],
                "source": "job-ledger",
                "source_record_id": f"job:{job_id}:{status}",
                "correlation_id": rec.get("fingerprint") or job_id,
                "session_id": None, "tool": None, "tokens": None, "cost_usd": None,
            }))
    except Exception as exc:  # noqa: BLE001
        log.debug("timeline: job-ledger unavailable: %s", exc)
    return out


def collect_timeline(home: Path, storage, force: bool = False) -> dict:
    """增量采集全部事件源；返回 {written, skipped, sources}。

    last_scan 存于 telemetry meta（force=True 全量重采但 event_id 幂等去重）。
    Watermark race 防护：查询起点 = 上次 watermark - SAFETY_WINDOW_S 安全窗口
    （source write 与 scan 边界竞争时重叠段重复采集，由幂等 event_id 去重，
    保证 missing=0 / duplicates=0）。
    """
    SAFETY_WINDOW_S = 5
    last_scan = 0
    if not force:
        try:
            with storage._connect() as conn:
                row = conn.execute("SELECT value FROM meta WHERE key='timeline_last_scan'").fetchone()
            last_scan = int(row[0]) if row and row[0] else 0
        except Exception:  # noqa: BLE001
            last_scan = 0
    scan_start = max(0, last_scan - SAFETY_WINDOW_S)
    events: list[dict] = []
    events += collect_session_events(home, scan_start)
    events += collect_tool_events(home, scan_start)
    events += collect_incident_events(storage, scan_start)
    events += collect_skill_events(home, scan_start)
    written = skipped = 0
    for ev in events:
        if not ev.get("event_id") or not ev.get("timestamp"):
            skipped += 1
            continue
        if storage.record_timeline_event(ev):
            written += 1
        else:
            skipped += 1
    now = int(time.time())
    try:
        with storage._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('timeline_last_scan', ?)",
                (str(now),))
    except Exception as exc:  # noqa: BLE001
        log.debug("timeline: last_scan write failed: %s", exc)
    return {"written": written, "skipped": skipped,
            "sources": ["sessions", "tools", "incidents", "skills"]}
