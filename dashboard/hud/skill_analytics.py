"""Hermes HUD — Skill Analytics v1。

把 Skill 从静态列表升级为可观测对象（observed truth only）：
没有可靠运行证据 → "未观测到执行"（绝不写"从未使用"）。

数据真相（Phase 1 Source Matrix 结论）：
  - Skill Registry（~/.hermes/skill-registry/registry.json）= inventory 元数据
  - timeline_events 的 skill.* = 唯一 first-class skill runtime identity
  - Job Ledger / state.db 无可靠 skill identity → 不猜、不制造 telemetry
  - Review Gate 结果未写回 registry → review_decision = unavailable（诚实）

合约：observed_runs = completed + failed；success_rate = completed/observed_runs
（denominator=0 → null，绝不显示 0%）；avg_duration_ms 仅可靠 duration_ms 参与；
不把 session token/cost 分摊给 skill。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("hud.skill_analytics")

REGISTRY_PATH = Path.home() / ".hermes" / "skill-registry" / "registry.json"

TIME_RANGES = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "all": None}

_SKILL_TYPES = ("skill.completed", "skill.failed")


def _registry_data() -> Optional[dict]:
    """读 Skill Registry；缺失/损坏 → None（调用方降级，不 500）。"""
    try:
        if not REGISTRY_PATH.exists():
            return None
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
            return None
        return data
    except Exception as exc:  # noqa: BLE001
        log.debug("skill_analytics: registry unreadable: %s", exc)
        return None


def _range_cutoff(time_range: str, now: Optional[int] = None) -> Optional[int]:
    import time as _t
    secs = TIME_RANGES.get(time_range)
    if secs is None:
        return None  # all
    return int(now if now is not None else _t.time()) - secs


def _skill_events(store, cutoff: Optional[int]) -> list[dict]:
    """timeline_events 的 skill.* 事件（唯一可靠 skill runtime 来源）。"""
    try:
        events = []
        # 分页取全量（indexed ts 查询）
        before = None
        while True:
            rows = store.query_timeline(
                limit=500, event_type="skill.", before=before)
            if not rows:
                break
            events.extend(rows)
            if len(rows) < 500:
                break
            before = rows[-1]["timestamp"]
        if cutoff is not None:
            events = [e for e in events if (e.get("timestamp") or 0) >= cutoff]
        return events
    except Exception as exc:  # noqa: BLE001
        log.debug("skill_analytics: timeline unavailable: %s", exc)
        return []


def compute_analytics(store, time_range: str = "7d") -> dict:
    """Skill Analytics v1 主聚合：inventory（registry）× runtime（timeline）join。

    返回 {skills: [...], coverage: {...}}；任一源失败 → partial（不 500）。
    """
    registry = _registry_data()
    reg_skills: dict[str, dict] = {}
    if registry:
        for item in registry.get("skills", []):
            if not isinstance(item, dict):
                continue  # malformed registry item → skip，不崩
            key = item.get("key")
            if not key:
                continue
            reg_skills[str(key)] = {
                "registered": True,
                "provenance": item.get("source") or item.get("source_confidence") or "unknown",
                "review_decision": None,  # Review Gate 未写回 registry → unavailable
                "risk": item.get("risk_level"),
                "version": item.get("version"),
                "author": item.get("author"),
                "health": item.get("health"),
                "has_tests": item.get("has_tests"),
                "fingerprint": item.get("fingerprint"),
            }

    cutoff = _range_cutoff(time_range)
    events = _skill_events(store, cutoff)

    # runtime join（仅可靠 skill.* 事件）
    runs: dict[str, dict[str, Any]] = {}
    for ev in events:
        skill = ev.get("skill")
        if not skill:
            continue
        r = runs.setdefault(str(skill), {"completed": 0, "failed": 0,
                                         "duration_total": 0, "duration_n": 0,
                                         "last_observed": 0})
        status = ev.get("status")
        if status == "failed":
            r["failed"] += 1
        else:
            r["completed"] += 1
        dur = ev.get("duration_ms")
        if isinstance(dur, (int, float)) and dur > 0:
            r["duration_total"] += dur
            r["duration_n"] += 1
        ts = ev.get("timestamp") or 0
        if ts > r["last_observed"]:
            r["last_observed"] = ts

    all_keys = sorted(set(reg_skills) | set(runs))
    skills_out = []
    for key in all_keys:
        reg = reg_skills.get(key)
        rt = runs.get(key)
        observed = rt is not None and (rt["completed"] + rt["failed"]) > 0
        observed_runs = (rt["completed"] + rt["failed"]) if rt else 0
        completed = rt["completed"] if rt else 0
        failed = rt["failed"] if rt else 0
        success_rate = (completed / observed_runs) if observed_runs else None
        avg_dur = (rt["duration_total"] / rt["duration_n"]
                   if rt and rt["duration_n"] else None)
        if reg:
            coverage = "observed" if observed else "inventory_only"
            review_decision = reg["review_decision"]  # None → unavailable
        else:
            coverage = "observed" if observed else "unavailable"
            review_decision = None
        skills_out.append({
            "skill": key,
            "registered": reg is not None,
            "provenance": reg["provenance"] if reg else None,
            "review_decision": review_decision,
            "risk": reg["risk"] if reg else None,
            "version": reg["version"] if reg else None,
            "health": reg["health"] if reg else None,
            "observed_runs": observed_runs,
            "completed": completed,
            "failed": failed,
            "success_rate": success_rate,
            "avg_duration_ms": avg_dur,
            "last_observed_at": rt["last_observed"] if rt and rt["last_observed"] else None,
            "runtime_coverage": coverage,
        })

    # coverage object（Phase 11）
    observed_skills = [s for s in skills_out if s["observed_runs"] > 0]
    coverage = {
        "registered_skills": len(reg_skills),
        "skills_with_observed_runtime": len(observed_skills),
        "skill_events": len(events),
        "runtime_identity_source": ["timeline_events skill.*"],
        "coverage_complete": False,  # 无权威证据 → 恒 false（Phase 11）
        "review_metadata_present": bool(registry),
    }
    return {"skills": skills_out, "coverage": coverage}


def compute_summary(store, time_range: str = "7d") -> dict:
    """Summary cards：Registered / Observed / Runs / Success Rate / Failed / 未观测到。"""
    data = compute_analytics(store, time_range)
    skills = data["skills"]
    observed = [s for s in skills if s["observed_runs"] > 0]
    total_runs = sum(s["observed_runs"] for s in skills)
    completed = sum(s["completed"] for s in skills)
    failed = sum(s["failed"] for s in skills)
    rate = (completed / total_runs) if total_runs else None
    return {
        "registered_skills": sum(1 for s in skills if s["registered"]),
        "observed_skills": len(observed),
        "observed_runs": total_runs,
        "success_rate": rate,
        "failed_runs": failed,
        "no_observed_execution": len([s for s in skills if s["observed_runs"] == 0]),
        "coverage": data["coverage"],
        "time_range": time_range,
    }


def query_skills(store, time_range: str = "7d", status: str | None = None,
                 provenance: str | None = None, observed: str | None = None,
                 search: str | None = None, sort: str = "name",
                 limit: int = 50, offset: int = 0) -> dict:
    """过滤 + 排序 + 分页（limit ≤ 200）。"""
    data = compute_analytics(store, time_range)
    skills = data["skills"]
    if status == "failed":
        skills = [s for s in skills if s["failed"] > 0]
    elif status == "success":
        skills = [s for s in skills if s["completed"] > 0]
    if provenance:
        skills = [s for s in skills if s.get("provenance") == provenance]
    if observed == "observed":
        skills = [s for s in skills if s["observed_runs"] > 0]
    elif observed == "unobserved":
        skills = [s for s in skills if s["observed_runs"] == 0]
    if search:
        q = search.lower()
        skills = [s for s in skills if q in s["skill"].lower()]
    sort_key = {
        "name": lambda s: s["skill"].lower(),
        "runs": lambda s: s["observed_runs"],
        "failures": lambda s: s["failed"],
        "rate": lambda s: (s["success_rate"] if s["success_rate"] is not None else -1),
        "recent": lambda s: (s["last_observed_at"] or 0),
    }.get(sort, lambda s: s["skill"].lower())
    skills.sort(key=sort_key, reverse=(sort in ("runs", "failures", "recent")))
    limit = max(1, min(int(limit), 200))
    total = len(skills)
    page = skills[offset: offset + limit]
    return {"skills": page, "total": total, "limit": limit, "offset": offset,
            "coverage": data["coverage"]}


def single_skill(store, skill: str, time_range: str = "7d",
                 timeline_limit: int = 20) -> dict:
    """单 skill 详情：registry 元数据 + 统计 + 最近 timeline 事件（直接引用，不复制）。"""
    data = compute_analytics(store, time_range)
    skill_data = next((s for s in data["skills"] if s["skill"] == skill), None)
    if skill_data is None:
        return {"error": f"skill not found: {skill}"}
    cutoff = _range_cutoff(time_range)
    events = _skill_events(store, cutoff)
    related = [e for e in events if e.get("skill") == skill]
    related = related[:timeline_limit]
    return {"skill": skill_data, "recent_timeline_events": related}
