"""Hermes HUD — 数据采集器。

每个 collector 都是独立的函数：内部 try/except，单项失败返回
{"error": "..."} 而绝不抛出 —— 采集器崩溃不能让 Dashboard 或 Gateway
受影响。所有对 state.db 的查询都走只读连接（mode=ro）+ 短超时，
不锁住正在写入的 Gateway。

路径解析全部基于 $HERMES_HOME（默认 ~/.hermes）。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import psutil  # 系统指标
except Exception:  # pragma: no cover
    psutil = None

import sys

from .redaction import redact_line, sanitize_cmdline, sanitize_path

# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def get_hud_timezone() -> timezone:
    """统计时区：HUD_TIMEZONE > 系统本地时区 > UTC。"""
    tz_name = os.environ.get("HUD_TIMEZONE", "").strip()
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)  # type: ignore[return-value]
        except Exception:
            pass
    # 系统本地时区
    try:
        return datetime.now().astimezone().tzinfo  # type: ignore[return-value]
    except Exception:
        return timezone.utc


def hud_tz_name() -> str:
    tz = get_hud_timezone()
    try:
        return str(tz)
    except Exception:
        return "UTC"


def _ro_connect(db_path: Path, timeout: float = 3.0) -> Optional[sqlite3.Connection]:
    """只读 SQLite 连接；失败返回 None。"""
    try:
        uri = f"file:{db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=timeout)
        conn.execute("PRAGMA query_only=ON")
        return conn
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _now_epoch() -> float:
    return time.time()


def _parse_ts(value: Any) -> Optional[float]:
    """兼容 ISO 字符串 / epoch float / None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    try:
        # ISO 8601，可能带 +08:00 / Z
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        try:
            return float(s)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# 1. Gateway / 渠道
# ---------------------------------------------------------------------------

def collect_gateway() -> dict:
    """gateway_state.json + 进程存活检查。"""
    out: dict[str, Any] = {"error": None, "pid": None, "alive": False,
                           "state": None, "start_time": None, "updated_at": None,
                           "active_agents": 0, "code_version": None,
                           "platforms": {}, "heartbeat_age": None}
    state = _read_json(HERMES_HOME / "gateway_state.json")
    if state is None:
        out["error"] = "gateway_state.json 不可读"
        return out
    pid = state.get("pid")
    out["pid"] = pid
    out["state"] = state.get("gateway_state")
    out["code_version"] = state.get("code_version")
    out["active_agents"] = state.get("active_agents", 0)
    st = state.get("start_time")
    out["start_time"] = st
    if pid:
        try:
            out["alive"] = psutil.pid_exists(pid) if psutil else _pid_exists_fallback(pid)
        except Exception:
            out["alive"] = False
    # 心跳新鲜度
    upd = _parse_ts(state.get("updated_at"))
    if upd is not None:
        out["heartbeat_age"] = max(0.0, _now_epoch() - upd)
        out["updated_at"] = upd
    # 渠道
    platforms = state.get("platforms") or {}
    for name, p in platforms.items():
        upd_ts = _parse_ts(p.get("updated_at"))
        out["platforms"][name] = {
            "state": p.get("state"),
            "needs_attention": bool(p.get("needs_attention")),
            "retrying_since": _parse_ts(p.get("retrying_since")),
            "error_code": p.get("error_code"),
            "error_message": redact_line(str(p.get("error_message") or ""))[:200],
            "updated_at": upd_ts,
            "heartbeat_age": max(0.0, _now_epoch() - upd_ts) if upd_ts else None,
        }
    return out


def _pid_exists_fallback(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False


def _gateway_proc() -> Optional[Any]:
    """返回 gateway 主进程 psutil.Process（或 None）。"""
    if not psutil:
        return None
    try:
        state = _read_json(HERMES_HOME / "gateway_state.json")
        pid = state.get("pid") if state else None
        if not pid or not psutil.pid_exists(pid):
            return None
        proc = psutil.Process(pid)
        # 确认 cmdline 是 gateway，避免误认
        cmd = " ".join(proc.cmdline() or [])
        if "gateway" in cmd or "hermes" in cmd:
            return proc
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 2. 系统指标
# ---------------------------------------------------------------------------

def collect_system() -> dict:
    """CPU / 内存 / 磁盘 / 进程 / 负载 / uptime。"""
    out: dict[str, Any] = {"error": None}
    if psutil is None:
        out["error"] = "psutil 不可用"
        return out
    try:
        out["cpu_percent"] = psutil.cpu_percent(interval=None)
        out["cpu_count"] = psutil.cpu_count()
        vm = psutil.virtual_memory()
        out["memory"] = {"total": vm.total, "used": vm.used, "available": vm.available,
                         "percent": vm.percent}
        try:
            out["load_avg"] = [round(x, 2) for x in os.getloadavg()]
        except Exception:
            out["load_avg"] = None
        try:
            disk = psutil.disk_usage(str(HERMES_HOME))
            out["disk"] = {"total": disk.total, "used": disk.used, "free": disk.free,
                           "percent": disk.percent}
            out["disk_free_percent"] = round(100.0 - disk.percent, 1)
        except Exception:
            out["disk"] = None
            out["disk_free_percent"] = None
        out["boot_time"] = psutil.boot_time()
        out["uptime_seconds"] = int(time.time() - psutil.boot_time())
        # Gateway / Dashboard 进程
        gw = _gateway_proc()
        if gw is not None:
            out["gateway_proc"] = {
                "pid": gw.pid,
                "rss": gw.memory_info().rss,
                "cpu_percent": gw.cpu_percent(interval=None),
                "threads": gw.num_threads(),
                "started_at": gw.create_time(),
                "uptime_seconds": int(time.time() - gw.create_time()),
            }
        else:
            out["gateway_proc"] = None
    except Exception as exc:
        out["error"] = str(exc)
    return out


# ---------------------------------------------------------------------------
# 3. 数据库 / 会话
# ---------------------------------------------------------------------------

def _db_sizes() -> dict:
    out = {}
    for name in ("state.db", "cron/executions.db"):
        p = HERMES_HOME / name
        try:
            out[name] = {"bytes": p.stat().st_size}
        except Exception:
            out[name] = None
    try:
        wal = HERMES_HOME / "state.db-wal"
        out["state.db"]["wal_bytes"] = wal.stat().st_size if wal.exists() else 0
    except Exception:
        pass
    return out


def collect_db() -> dict:
    """state.db 只读统计：会话数、消息数、usage 汇总、文件体积。"""
    out: dict[str, Any] = {"error": None, "sizes": _db_sizes()}
    conn = _ro_connect(HERMES_HOME / "state.db")
    if conn is None:
        out["error"] = "state.db 只读连接失败"
        return out
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sessions")
        out["sessions_total"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM sessions WHERE started_at >= ?",
                    (_now_epoch() - 86400,))
        out["sessions_24h"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM sessions WHERE started_at >= ?",
                    (_now_epoch() - 7 * 86400,))
        out["sessions_7d"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM messages")
        out["messages_total"] = cur.fetchone()[0]
        cur.execute(
            "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
            " COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0),"
            " COALESCE(SUM(reasoning_tokens),0), COALESCE(SUM(estimated_cost_usd),0)"
            " FROM sessions WHERE input_tokens > 0 OR output_tokens > 0"
        )
        row = cur.fetchone()
        out["usage"] = {
            "input_tokens": row[0], "output_tokens": row[1],
            "cache_read_tokens": row[2], "cache_write_tokens": row[3],
            "reasoning_tokens": row[4], "estimated_cost_usd": row[5],
        }
        # 会话内模型使用（含辅助调用 task != ''）
        cur.execute(
            "SELECT COALESCE(SUM(api_call_count),0), COUNT(DISTINCT session_id),"
            " COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
            " COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(estimated_cost_usd),0)"
            " FROM session_model_usage"
        )
        row = cur.fetchone()
        out["model_usage"] = {
            "api_calls": row[0], "sessions": row[1],
            "input_tokens": row[2], "output_tokens": row[3],
            "cache_read_tokens": row[4], "estimated_cost_usd": row[5],
        }
        # 辅助调用（task != ''）
        cur.execute(
            "SELECT COALESCE(SUM(api_call_count),0), COALESCE(SUM(input_tokens),0),"
            " COALESCE(SUM(output_tokens),0), COALESCE(SUM(cache_read_tokens),0),"
            " COALESCE(SUM(estimated_cost_usd),0)"
            " FROM session_model_usage WHERE task != ''"
        )
        row = cur.fetchone()
        out["aux_usage"] = {
            "api_calls": row[0], "input_tokens": row[1], "output_tokens": row[2],
            "cache_read_tokens": row[3], "estimated_cost_usd": row[4],
        }
        # 今日（HUD statistics timezone / configured local timezone）
        tz = get_hud_timezone()
        now_local = datetime.now(tz)
        day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_epoch = day_start.astimezone(timezone.utc).timestamp()
        # C-1: header 的 cost/token 一律来自 canonical Cost Truth summary
        # （session_model_usage 单源 + pricing provenance）——禁止第二套 estimated
        # aggregation；unpriced/pricing_unknown 绝不并入估算。
        # 延迟导入：cost.py 顶层 from .collectors import get_hud_timezone，
        # 顶层 import 会形成循环依赖；函数内导入时模块已完整加载。
        from . import cost as _cost
        cost_summary = _cost.compute_summary(HERMES_HOME, "today")
        cov = cost_summary.get("coverage") or {}
        # session count 属 operational metric → 仍从 sessions 表取
        cur.execute("SELECT COUNT(*) FROM sessions WHERE started_at >= ?",
                    (day_start_epoch,))
        out["today_sessions"] = {
            "input_tokens": cost_summary.get("input_tokens"),
            "output_tokens": cost_summary.get("output_tokens"),
            "cache_read_tokens": cost_summary.get("cache_read_tokens"),
            "estimated_cost_usd": cost_summary.get("estimated_cost_usd"),
            "pricing_unknown_rows": cov.get("pricing_unknown_rows"),
            "count": cur.fetchone()[0],
        }
        # aux（task != ''）独立观测：仅供 telemetry/辅助分析，绝不参与 header 估算
        cur.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd),0), COALESCE(SUM(actual_cost_usd),0),"
            " COUNT(DISTINCT session_id) FROM session_model_usage WHERE last_seen >= ?"
            " AND task != ''",
            (day_start_epoch,),
        )
        row = cur.fetchone()
        out["today_sessions"]["aux_est_cost"] = row[0]
        out["today_sessions"]["aux_actual_cost"] = row[1]
    except Exception as exc:
        out["error"] = f"查询失败: {exc}"
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def collect_active_sessions(limit: int = 30) -> list[dict]:
    """活跃会话（ended_at IS NULL，按最近开始排序）。"""
    conn = _ro_connect(HERMES_HOME / "state.db")
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, source, user_id, model, started_at, title, message_count,"
            " tool_call_count, input_tokens, output_tokens, cwd"
            " FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        # 最近活动时间：MAX(messages.timestamp)（会话最近一条消息）
        last_active: dict[str, float] = {}
        try:
            cur.execute(
                "SELECT session_id, MAX(timestamp) FROM messages GROUP BY session_id"
            )
            for sid, ts in cur.fetchall():
                if ts:
                    last_active[sid] = ts
        except Exception:
            pass
        out = []
        for r in rows:
            sid, source, user_id, model, started_at, title, msgs, tools, itok, otok, cwd = r
            running = int(_now_epoch() - (started_at or _now_epoch()))
            last_ts = last_active.get(sid)
            idle = int(_now_epoch() - last_ts) if last_ts else None  # 无可靠数据 = null
            out.append({
                "id": sid, "source": source, "user_id": user_id, "model": model,
                "started_at": started_at, "title": title, "message_count": msgs,
                "tool_call_count": tools, "input_tokens": itok, "output_tokens": otok,
                "cwd": sanitize_path(cwd) if cwd else cwd,
                "idle_seconds": idle,
                "running_seconds": running,
            })
        return out
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def collect_recent_sessions(days: int = 7, limit: int = 100) -> list[dict]:
    """最近 N 天会话摘要（供对话记录 Tab）。"""
    conn = _ro_connect(HERMES_HOME / "state.db")
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, source, user_id, model, started_at, ended_at, title,"
            " message_count, tool_call_count, input_tokens, output_tokens,"
            " estimated_cost_usd, end_reason"
            " FROM sessions WHERE started_at >= ? ORDER BY started_at DESC LIMIT ?",
            (_now_epoch() - days * 86400, limit),
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            (sid, source, user_id, model, started_at, ended_at, title, msgs,
             tools, itok, otok, cost, end_reason) = r
            out.append({
                "id": sid, "source": source, "user_id": user_id, "model": model,
                "started_at": started_at, "ended_at": ended_at, "title": title,
                "message_count": msgs, "tool_call_count": tools,
                "input_tokens": itok, "output_tokens": otok,
                "estimated_cost_usd": cost, "end_reason": end_reason,
            })
        return out
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def collect_session_detail(session_id: str) -> Optional[dict]:
    """单会话详情（对话记录 Tab 进入详情后调用）。"""
    conn = _ro_connect(HERMES_HOME / "state.db")
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, source, user_id, model, started_at, ended_at, title,"
            " message_count, tool_call_count, input_tokens, output_tokens,"
            " cache_read_tokens, cache_write_tokens, reasoning_tokens,"
            " estimated_cost_usd, actual_cost_usd, cost_status, cost_source,"
            " end_reason, cwd, billing_provider"
            " FROM sessions WHERE id=?",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        (sid, source, user_id, model, started_at, ended_at, title, msgs, tools,
         itok, otok, cr, cw, rt, est, act, cost_status, cost_source, end_reason,
         cwd, provider) = row
        # 消息时间线（摘要：role + 长度，不直接吐全文，正文由前端按需请求）
        cur.execute(
            "SELECT role, substr(content,1,120), timestamp FROM messages"
            " WHERE session_id=? ORDER BY timestamp LIMIT 100",
            (session_id,),
        )
        msgs_rows = [{"role": m[0], "preview": redact_line(m[1] or ""), "ts": m[2]}
                     for m in cur.fetchall()]
        # 会话内模型 usage
        cur.execute(
            "SELECT model, task, api_call_count, input_tokens, output_tokens,"
            " cache_read_tokens, estimated_cost_usd, cost_status"
            " FROM session_model_usage WHERE session_id=? ORDER BY last_seen",
            (session_id,),
        )
        usage = [{"model": u[0], "task": u[1], "api_calls": u[2], "input_tokens": u[3],
                  "output_tokens": u[4], "cache_read_tokens": u[5],
                  "estimated_cost_usd": u[6], "cost_status": u[7]}
                 for u in cur.fetchall()]
        return {
            "id": sid, "source": source, "user_id": user_id, "model": model,
            "started_at": started_at, "ended_at": ended_at, "title": title,
            "message_count": msgs, "tool_call_count": tools, "input_tokens": itok,
            "output_tokens": otok, "cache_read_tokens": cr, "cache_write_tokens": cw,
            "reasoning_tokens": rt, "estimated_cost_usd": est, "actual_cost_usd": act,
            "cost_status": cost_status, "cost_source": cost_source,
            "end_reason": end_reason, "cwd": cwd, "billing_provider": provider,
            "messages": msgs_rows, "model_usage": usage,
        }
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 4. Cron
# ---------------------------------------------------------------------------

def _job_model(job: dict) -> Optional[str]:
    """任务 model 归一化：顶层 model > model_snapshot（dict{model} | str | None）。

    Hermes v0.21 起 model_snapshot 可能写为 str（'deepseek-v4-flash'），旧数据是
    dict。可选元数据解析失败一律安全回退 None——绝不因此丢任务。
    """
    top = job.get("model")
    if top:
        return str(top)
    snap = job.get("model_snapshot")
    if isinstance(snap, dict):
        return snap.get("model") or snap.get("name") or None
    if isinstance(snap, str):
        return snap.strip() or None
    return None


def _job_provider(job: dict) -> Optional[str]:
    """任务 provider 归一化（同 _job_model：dict{provider} | str | None）。"""
    top = job.get("provider")
    if top:
        return str(top)
    snap = job.get("provider_snapshot")
    if isinstance(snap, dict):
        return snap.get("provider") or None
    if isinstance(snap, str):
        return snap.strip() or None
    return None


def collect_cron_jobs() -> dict:
    """jobs.json 任务列表 + 汇总。"""
    data = _read_json(HERMES_HOME / "cron" / "jobs.json")
    if data is None:
        return {"error": "cron/jobs.json 不可读", "jobs": [], "summary": {}}
    jobs = data.get("jobs", [])
    out_jobs = []
    parse_warnings = 0
    for j in jobs:
        try:
            sched = j.get("schedule") or {}
            if isinstance(sched, dict):
                expr = sched.get("expr") or sched.get("display")
                kind = sched.get("kind", "cron")
            else:
                expr, kind = str(sched), "cron"
            out_jobs.append({
                "id": j.get("id"),
                "name": j.get("name"),
                "enabled": bool(j.get("enabled")),
                "state": j.get("state"),
                "schedule": expr,
                "schedule_kind": kind,
                "next_run_at": _parse_ts(j.get("next_run_at")),
                "last_run_at": _parse_ts(j.get("last_run_at")),
                "last_status": j.get("last_status"),
                "last_error": redact_line(str(j.get("last_error") or ""))[:200] or None,
                "last_delivery_error": redact_line(str(j.get("last_delivery_error") or ""))[:200] or None,
                "failure_streak": j.get("failure_streak", 0),
                "deliver": redact_line(str(j.get("deliver") or ""))[:200] or None,
                "model": _job_model(j),
                "provider": _job_provider(j),
                "script": sanitize_path(str(j.get("script") or "")) or None,
                "no_agent": bool(j.get("no_agent")),
                "created_at": _parse_ts(j.get("created_at")),
                "paused_at": _parse_ts(j.get("paused_at")),
                "paused_reason": j.get("paused_reason"),
            })
        except Exception:
            # MODEL METADATA FAILURE ≠ DROP TASK：任何元数据解析失败都保留任务
            # （最小可展示字段），仅计数诊断；warning 不含 secret/prompt/token。
            parse_warnings += 1
            sched = j.get("schedule") or {}
            out_jobs.append({
                "id": j.get("id"),
                "name": j.get("name"),
                "enabled": bool(j.get("enabled")),
                "state": j.get("state"),
                "schedule": (sched.get("display") if isinstance(sched, dict) else str(sched)),
                "schedule_kind": (sched.get("kind", "cron") if isinstance(sched, dict) else "cron"),
                "next_run_at": None, "last_run_at": None,
                "last_status": j.get("last_status"),
                "last_error": None, "last_delivery_error": None,
                "failure_streak": j.get("failure_streak", 0),
                "deliver": None, "model": None, "provider": None,
                "script": None, "no_agent": bool(j.get("no_agent")),
                "created_at": None, "paused_at": None, "paused_reason": None,
            })
    summary = {
        "total": len(out_jobs),
        "enabled": sum(1 for j in out_jobs if j["enabled"]),
        "paused": sum(1 for j in out_jobs if not j["enabled"] and j["paused_at"]),
        "disabled": sum(1 for j in out_jobs if not j["enabled"] and not j["paused_at"]),
        "failing": sum(1 for j in out_jobs if (j["failure_streak"] or 0) >= 1),
        "running_state": sum(1 for j in out_jobs if j["state"] in ("running", "claimed", "firing")),
        "parse_warnings": parse_warnings,
    }
    return {"jobs": out_jobs, "summary": summary}


def collect_cron_executions(limit: int = 60) -> dict:
    """executions.db 执行历史。"""
    conn = _ro_connect(HERMES_HOME / "cron" / "executions.db")
    if conn is None:
        return {"error": "executions.db 只读连接失败", "executions": [], "summary": {}}
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, job_id, source, status, claimed_at, started_at, finished_at,"
            " pid, error FROM executions ORDER BY claimed_at DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            eid, job_id, source, status, claimed_at, started_at, finished_at, pid, error = r
            st = _parse_ts(started_at) or _parse_ts(claimed_at)
            ft = _parse_ts(finished_at)
            out.append({
                "id": eid, "job_id": job_id, "source": source, "status": status,
                "claimed_at": _parse_ts(claimed_at), "started_at": st,
                "finished_at": ft, "pid": pid,
                "duration": (ft - st) if (ft and st) else None,
                "error": redact_line(str(error or ""))[:200] or None,
            })
        # 任务成功率统计（最近 30 天）
        cutoff = time.time() - 30 * 86400
        cur.execute(
            "SELECT job_id, status, COUNT(*),"
            " SUM(CASE WHEN started_at IS NOT NULL AND finished_at IS NOT NULL"
            "     THEN (finished_at - started_at) END)"
            " FROM executions WHERE claimed_at >= ? GROUP BY job_id, status",
            (cutoff,),
        )
        stats: dict[str, dict] = {}
        for job_id, status, cnt, dur_sum in cur.fetchall():
            s = stats.setdefault(job_id, {"ok": 0, "completed": 0, "failed": 0,
                                          "unknown": 0, "total_seconds": 0.0, "runs": 0})
            s[status if status in ("completed", "failed", "unknown") else "unknown"] += cnt
            s["runs"] += cnt
            if dur_sum:
                s["total_seconds"] += dur_sum
        return {"executions": out, "summary": stats}
    except Exception as exc:
        return {"error": str(exc), "executions": [], "summary": {}}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 5. 日志（增量）
# ---------------------------------------------------------------------------

def _tail_lines(path: Path, n: int = 50) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            size = f.tell()
            block = min(size, 64 * 1024)
            f.seek(max(0, size - block))
            data = f.read()
        lines = data.splitlines()
        return lines[-n:]
    except Exception:
        return []


def collect_logs(lines_per_file: int = 60) -> dict:
    """最近日志（agent.log / errors.log / gateway*.log 尾部，已脱敏）。"""
    logs_dir = HERMES_HOME / "logs"
    out: dict[str, Any] = {"files": {}}
    for name in ("agent.log", "errors.log", "gateway.log", "gateway.error.log", "desktop.log"):
        path = logs_dir / name
        if not path.exists():
            continue
        raw = _tail_lines(path, lines_per_file)
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = None
        out["files"][name] = {
            "mtime": mtime,
            "bytes": path.stat().st_size if path.exists() else 0,
            "lines": [redact_line(x) for x in raw],
        }
    return out


def collect_error_stats(minutes: int = 30) -> dict:
    """errors.log 近 N 分钟错误数 + 按指纹聚合。"""
    path = HERMES_HOME / "logs" / "errors.log"
    if not path.exists():
        return {"error": "errors.log 不存在", "count_30m": 0, "incidents": []}
    lines = _tail_lines(path, 800)
    cutoff = time.time() - minutes * 60
    recent = 0
    buckets: dict[str, dict] = {}
    for line in lines:
        ts = _extract_log_ts(line)
        if ts is not None and ts >= cutoff:
            recent += 1
        fp = _fingerprint_from_line(line)
        if not fp:
            continue
        b = buckets.setdefault(fp, {"fingerprint": fp, "count": 0, "first": line, "last": line})
        b["count"] += 1
        b["last"] = line
    incidents = []
    for b in sorted(buckets.values(), key=lambda x: -x["count"])[:15]:
        incidents.append({
            "fingerprint": b["fingerprint"],
            "count": b["count"],
            "sample": redact_line(b["last"])[:300],
        })
    return {"count_30m": recent, "incidents": incidents}


def _extract_log_ts(line: str) -> Optional[float]:
    m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def _fingerprint_from_line(line: str) -> str:
    from .redaction import fingerprint
    fp = fingerprint(line)
    if len(fp) < 12 or "error" not in line.lower() and "exception" not in line.lower():
        return ""
    return fp


# ---------------------------------------------------------------------------
# 6. 记忆
# ---------------------------------------------------------------------------

def collect_memory() -> dict:
    """MEMORY.md / USER.md 元数据 + 记忆卡片统计。"""
    memories_dir = HERMES_HOME / "memories"
    out: dict[str, Any] = {"provider": "builtin", "files": {}, "locks": {}, "stats": {}}
    for name in ("MEMORY.md", "USER.md"):
        p = memories_dir / name
        try:
            if p.exists():
                st = p.stat()
                out["files"][name] = {
                    "bytes": st.st_size, "mtime": st.st_mtime,
                    "sections": _count_md_sections(p),
                }
            else:
                out["files"][name] = None
        except Exception:
            out["files"][name] = None
    # 锁文件长期不释放检查（> 10 分钟视为异常）
    now = time.time()
    for name in ("MEMORY.md.lock", "USER.md.lock"):
        p = memories_dir / name
        try:
            if p.exists():
                age = now - p.stat().st_mtime
                out["locks"][name] = {"age": int(age), "stale": age > 600}
        except Exception:
            pass
    # 记忆卡片数（按 § 分节粗估）
    total_sections = sum((v or {}).get("sections", 0) for v in out["files"].values() if v)
    out["stats"] = {"total_sections": total_sections}
    return out


def _count_md_sections(path: Path) -> int:
    try:
        n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("§") or line.startswith("## "):
                n += 1
        return n
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# 7. 服务定义（launchd）一致性
# ---------------------------------------------------------------------------

def collect_launchd_check() -> dict:
    """检查 Gateway 是否由 launchd 托管。

    只做只读检查（launchctl print / plist 文件存在性），不修改任何东西。
    """
    out: dict[str, Any] = {"managed": False, "label": None, "plist_exists": False,
                           "note": None, "status": "managed" if False else "checked"}
    if sys.platform != "darwin":
        # 非 macOS：launchd 概念不适用，不产生告警
        out["status"] = "not_applicable"
        out["note"] = "launchd 仅 macOS 适用"
        return out
    candidates = [
        Path.home() / "Library/LaunchAgents/com.nousresearch.hermes.gateway.plist",
        Path.home() / "Library/LaunchAgents/com.hermes.gateway.plist",
        Path.home() / "Library/LaunchAgents/ai.hermes.gateway.plist",
        Path.home() / "Library/LaunchAgents/io.nous.hermes.gateway.plist",
    ]
    found = [p for p in candidates if p.exists()]
    out["plist_exists"] = bool(found)
    if found:
        out["label"] = found[0].stem
        # 读取 plist 里的 ProgramArguments 摘要（不读环境变量/凭据）
        try:
            import plistlib
            with open(found[0], "rb") as f:
                pl = plistlib.load(f)
            args = pl.get("ProgramArguments") or []
            out["note"] = sanitize_cmdline(" ".join(str(a) for a in args), 300)
        except Exception:
            pass
    # 通过 launchctl 查加载状态（只读）
    try:
        import subprocess
        r = subprocess.run(
            ["launchctl", "print", "gui/%d" % os.getuid()],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            out["managed"] = any(
                "hermes" in line.lower() and "gateway" in line.lower()
                for line in r.stdout.splitlines()
            )
    except Exception:
        pass
    out["status"] = "managed" if out["managed"] else "unmanaged"
    return out


# ---------------------------------------------------------------------------
# 8. Dashboard 进程
# ---------------------------------------------------------------------------

def _is_hermes_script_entrypoint(cmdline: list[str]) -> bool:
    """Match direct or Python-launched ``hermes`` repository scripts."""
    if not cmdline:
        return False
    executable = Path(cmdline[0]).name
    if executable == "hermes":
        return True
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", executable) is None:
        return False

    index = 1
    while index < len(cmdline):
        arg = cmdline[index]
        if arg == "--":
            index += 1
            break
        if arg in {"-c", "-m"}:
            return False
        if not arg.startswith("-") or arg == "-":
            break
        index += 2 if arg in {"-W", "-X"} else 1
    return index < len(cmdline) and Path(cmdline[index]).name == "hermes"


def collect_dashboard_procs() -> dict:
    """正在运行的 hermes web server（dashboard）进程。"""
    if psutil is None:
        return {"error": "psutil 不可用", "procs": []}
    out = []
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "memory_info"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                cmd = " ".join(cmdline)
                # ``hermes dashboard`` installed from the repository runs as
                # ``python /path/to/hermes dashboard`` and does not include
                # ``hermes_cli.main`` in its argv.  Accept both supported
                # entrypoint forms while matching command arguments exactly.
                is_module_entrypoint = any("hermes_cli.main" in arg for arg in cmdline)
                is_script_entrypoint = _is_hermes_script_entrypoint(cmdline)
                is_dashboard_command = any(
                    arg in {"dashboard", "serve"} for arg in cmdline
                )
                if (is_module_entrypoint or is_script_entrypoint) and is_dashboard_command:
                    mem = proc.info.get("memory_info")
                    out.append({
                        "pid": proc.info["pid"],
                        "rss": mem.rss if mem else None,
                        "started_at": proc.info.get("create_time"),
                        "cmdline": sanitize_cmdline(cmd, 200),
                    })
            except Exception:
                continue
    except Exception:
        pass
    return {"procs": out}


def collect_usage(days: int = 30) -> dict:
    """Token/费用聚合（按 HUD statistics timezone / configured local timezone 按天 + 按模型 + 按辅助任务类型）。

    主会话读 sessions；辅助调用读 session_model_usage.task != ''；
    两者按 (session, model, task) 去重后合并，主会话与辅助调用不重复计数。
    """
    conn = _ro_connect(HERMES_HOME / "state.db")
    if conn is None:
        return {"error": "state.db 只读连接失败"}
    try:
        cur = conn.cursor()
        # 统计时区日界线：state.db 存的是 UTC epoch，按 configured local timezone 转天
        # 简化：查询全部 usage 后按本地时区在 Python 里分组
        cur.execute(
            "SELECT started_at, input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd,"
            " cost_status, title, model, billing_provider"
            " FROM sessions WHERE started_at >= ?",
            (time.time() - days * 86400,),
        )
        sessions_rows = cur.fetchall()
        # 辅助调用只取 task != ''：task='' 的行是主会话的重复记账，
        # 不能把 sessions + 全部 session_model_usage 简单相加（否则主会话翻倍）
        cur.execute(
            "SELECT last_seen, input_tokens, output_tokens, cache_read_tokens,"
            " cache_write_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd,"
            " model, billing_provider, task, api_call_count"
            " FROM session_model_usage WHERE last_seen >= ? AND task != ''",
            (time.time() - days * 86400,),
        )
        usage_rows = cur.fetchall()

        hud_tz = get_hud_timezone()

        def _cst_day(ts: Optional[float]) -> str:
            if not ts:
                return "unknown"
            return datetime.fromtimestamp(ts, hud_tz).strftime("%Y-%m-%d")

        # 按天
        days_agg: dict[str, dict] = {}
        for r in sessions_rows:
            day = _cst_day(r[0])
            d = days_agg.setdefault(day, {"day": day, "input": 0, "output": 0,
                                          "cache_read": 0, "cache_write": 0,
                                          "reasoning": 0, "est_cost": 0.0,
                                          "actual_cost": 0.0, "sessions": 0,
                                          "api_calls": 0})
            d["input"] += r[1] or 0
            d["output"] += r[2] or 0
            d["cache_read"] += r[3] or 0
            d["cache_write"] += r[4] or 0
            d["reasoning"] += r[5] or 0
            d["est_cost"] += r[6] or 0
            d["actual_cost"] += r[7] or 0
            d["sessions"] += 1
        # 会话内 usage 行（含辅助），注意去重口径：usage 行按 session+model+task 存，
        # 直接累加即可（sessions 表与 session_model_usage 是两套，不会重复计）
        for r in usage_rows:
            day = _cst_day(r[0])
            d = days_agg.setdefault(day, {"day": day, "input": 0, "output": 0,
                                          "cache_read": 0, "cache_write": 0,
                                          "reasoning": 0, "est_cost": 0.0,
                                          "actual_cost": 0.0, "sessions": 0,
                                          "api_calls": 0})
            d["input"] += r[1] or 0
            d["output"] += r[2] or 0
            d["cache_read"] += r[3] or 0
            d["cache_write"] += r[4] or 0
            d["reasoning"] += r[5] or 0
            d["est_cost"] += r[6] or 0
            d["actual_cost"] += r[7] or 0
            d["api_calls"] += r[11] or 1
        by_day = [days_agg[k] for k in sorted(days_agg.keys())]

        # 按模型（合并 sessions + usage，按模型累计）
        by_model: dict[str, dict] = {}
        for r in sessions_rows:
            m = r[10] or "unknown"
            b = by_model.setdefault(m, {"model": m, "input": 0, "output": 0,
                                        "cache_read": 0, "est_cost": 0.0,
                                        "api_calls": 0, "sessions": 0})
            b["input"] += r[1] or 0
            b["output"] += r[2] or 0
            b["cache_read"] += r[3] or 0
            b["est_cost"] += r[6] or 0
            b["sessions"] += 1
        for r in usage_rows:
            m = r[8] or "unknown"
            b = by_model.setdefault(m, {"model": m, "input": 0, "output": 0,
                                        "cache_read": 0, "est_cost": 0.0,
                                        "api_calls": 0, "sessions": 0})
            b["input"] += r[1] or 0
            b["output"] += r[2] or 0
            b["cache_read"] += r[3] or 0
            b["est_cost"] += r[6] or 0
            b["api_calls"] += r[11] or 1
        by_model_list = sorted(by_model.values(), key=lambda x: -x["est_cost"])

        # 辅助任务类型（task != ''）
        by_task: dict[str, dict] = {}
        for r in usage_rows:
            if not r[10]:
                continue
            t = r[10]
            b = by_task.setdefault(t, {"task": t, "input": 0, "output": 0,
                                       "est_cost": 0.0, "api_calls": 0})
            b["input"] += r[1] or 0
            b["output"] += r[2] or 0
            b["est_cost"] += r[6] or 0
            b["api_calls"] += r[11] or 1
        by_task_list = sorted(by_task.values(), key=lambda x: -x["est_cost"])

        return {
            "days": days, "by_day": by_day,
            "by_model": by_model_list,
            "by_task": by_task_list,
            "totals": {
                "input": sum(d["input"] for d in by_day),
                "output": sum(d["output"] for d in by_day),
                "cache_read": sum(d["cache_read"] for d in by_day),
                "est_cost": round(sum(d["est_cost"] for d in by_day), 4),
                "actual_cost": round(sum(d["actual_cost"] for d in by_day), 4),
                "api_calls": sum(d["api_calls"] for d in by_day),
            },
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def search_sessions(q: str, limit: int = 50) -> list[dict]:
    """按标题/ID 模糊搜索会话。"""
    conn = _ro_connect(HERMES_HOME / "state.db")
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        like = f"%{q}%"
        cur.execute(
            "SELECT id, source, model, started_at, title, message_count,"
            " input_tokens, output_tokens, estimated_cost_usd, ended_at"
            " FROM sessions WHERE title LIKE ? OR id LIKE ? OR user_id LIKE ?"
            " ORDER BY started_at DESC LIMIT ?",
            (like, like, like, limit),
        )
        rows = cur.fetchall()
        return [
            {"id": r[0], "source": r[1], "model": r[2], "started_at": r[3],
             "title": r[4], "message_count": r[5], "input_tokens": r[6],
             "output_tokens": r[7], "estimated_cost_usd": r[8], "ended_at": r[9]}
            for r in rows
        ]
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def collect_skills() -> dict:
    """扫描 ~/.hermes/skills/ 下的 SKILL.md，解析元数据 + 统计。"""
    skills_root = HERMES_HOME / "skills"
    out: dict[str, Any] = {"error": None, "skills": [], "summary": {}}
    if not skills_root.is_dir():
        out["error"] = "skills 目录不存在"
        return out
    skills: list[dict] = []
    try:
        for md in skills_root.rglob("SKILL.md"):
            try:
                rel = md.relative_to(skills_root)
                parts = list(rel.parts[:-1])  # 去掉 SKILL.md
                name = parts[-1] if parts else md.parent.name
                category = parts[-2] if len(parts) >= 2 else "未分类"
                st = md.stat()
                # 解析 frontmatter
                meta: dict[str, str] = {}
                text = md.read_text(encoding="utf-8", errors="replace")[:4000]
                if text.startswith("---"):
                    end = text.find("\n---", 3)
                    if end > 0:
                        for line in text[3:end].splitlines():
                            if ":" in line:
                                k, _, v = line.partition(":")
                                meta[k.strip()] = v.strip().strip('"').strip("'")
                skills.append({
                    "name": meta.get("name", name),
                    "description": meta.get("description", ""),
                    "version": meta.get("version", ""),
                    "category": category,
                    "dir": sanitize_path(str(md.parent)),
                    "bytes": st.st_size,
                    "mtime": st.st_mtime,
                })
            except Exception:
                continue
    except Exception as exc:
        out["error"] = str(exc)
    skills.sort(key=lambda s: -s["mtime"])
    cats: dict[str, int] = {}
    for s in skills:
        cats[s["category"]] = cats.get(s["category"], 0) + 1
    out["skills"] = skills
    out["summary"] = {
        "total": len(skills),
        "categories": len(cats),
        "by_category": dict(sorted(cats.items(), key=lambda x: -x[1])),
        "total_bytes": sum(s["bytes"] for s in skills),
        "recent_24h": sum(1 for s in skills if time.time() - s["mtime"] < 86400),
        "recent_7d": sum(1 for s in skills if time.time() - s["mtime"] < 7 * 86400),
    }
    return out


def collect_tool_events(limit: int = 60) -> list[dict]:
    """最近工具调用事件（从 messages 表 tool_name/tool_calls 推断）。

    第一版轻量实现：查最近带工具调用的消息，按时间倒序。
    精确的 tool start/end 生命周期需要插件 hook（第二版）。
    """
    conn = _ro_connect(HERMES_HOME / "state.db")
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT m.session_id, m.role, m.tool_name, m.tool_calls, m.timestamp, s.title"
            " FROM messages m LEFT JOIN sessions s ON s.id = m.session_id"
            " WHERE m.tool_name IS NOT NULL AND m.tool_name != ''"
            " OR (m.tool_calls IS NOT NULL AND m.tool_calls != '')"
            " ORDER BY m.timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            sid, role, tool_name, tool_calls, ts, title = r
            # 从 tool_calls JSON 提取工具名（若有）
            names = []
            if tool_calls:
                try:
                    import json as _json
                    calls = _json.loads(tool_calls) if isinstance(tool_calls, str) else tool_calls
                    if isinstance(calls, list):
                        for c in calls:
                            fn = (c.get("function") or {}).get("name") if isinstance(c, dict) else None
                            if fn:
                                names.append(fn)
                except Exception:
                    pass
            out.append({
                "session_id": sid,
                "title": (title or sid)[:50],
                "role": role,
                "tool_name": tool_name or (names[0] if names else "unknown"),
                "tool_calls": names[:5],
                "ts": ts,
            })
        return out
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 汇总快照
# ---------------------------------------------------------------------------

def build_snapshot() -> dict:
    """一次取齐所有采集器结果（各自容错）。"""
    collected_at = _now_epoch()
    return {
        "collected_at": collected_at,
        "generated_at_iso": datetime.now(get_hud_timezone()).isoformat(timespec="seconds"),
        "tz": hud_tz_name(),
        "gateway": collect_gateway(),
        "system": collect_system(),
        "db": collect_db(),
        "active_sessions": collect_active_sessions(),
        "cron": collect_cron_jobs(),
        "executions": collect_cron_executions(),
        "logs": collect_logs(),
        "errors": collect_error_stats(),
        "memory": collect_memory(),
        "launchd": collect_launchd_check(),
        "dashboard": collect_dashboard_procs(),
    }
