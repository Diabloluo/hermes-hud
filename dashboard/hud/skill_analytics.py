"""Hermes HUD — Skill Analytics v1（SQL Aggregation 架构）。

把 Skill 从静态列表升级为可观测对象（observed truth only）：
没有可靠运行证据 → "未观测到执行"（绝不写"从未使用"）。

架构（SQL Aggregation Final Gate）：
  - 聚合走 storage.aggregate_skill_runtime()：SQLite 原生 GROUP BY，事件白名单
    只认 skill.completed / skill.failed（不用 skill.* 前缀猜状态）
  - 单 skill 详情走 query_skill_runtime_events()：WHERE skill=? + 白名单 +
    ORDER BY ts DESC, event_id DESC LIMIT——不扫描全量
  - 无 aggregate cache（sliding range / registry 变化 / source availability
    无法由 (total,last_ts) 完整表达 → 不修 cache invalidation，直接每轮 SQL）
  - Source truth：registry 与 timeline 分开判断 healthy/unavailable；
    partial = 任一 unavailable；timeline unavailable → 全部 runtime 字段 null、
    runtime_coverage=unavailable（不是"未观测到执行"）、
    no_observed_execution=null（UI —）
  - observed/unobserved 过滤不得返回 unavailable rows
  - 不把 session token/cost 分摊给 skill（Cost Intelligence 后置）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("hud.skill_analytics")

REGISTRY_PATH = Path.home() / ".hermes" / "skill-registry" / "registry.json"

TIME_RANGES = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "all": None}

_SKILL_TYPES = ("skill.completed", "skill.failed")  # 显式白名单（禁前缀猜）


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


def _registry_map(registry: Optional[dict]) -> dict[str, dict]:
    """registry 列表 → {key: meta}；malformed item skip（不崩）。"""
    reg_skills: dict[str, dict] = {}
    if not registry:
        return reg_skills
    for item in registry.get("skills", []):
        if not isinstance(item, dict):
            continue
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
    return reg_skills


def compute_analytics(store, time_range: str = "7d") -> dict:
    """Skill Analytics v1 主聚合：registry（inventory）× SQL 聚合（runtime）join。

    Source truth：registry 与 timeline 分开 healthy/unavailable；
    partial = 任一 unavailable；timeline unavailable → 全部 runtime 字段 null +
    runtime_coverage=unavailable（禁止显示为"未观测到执行"）。
    """
    registry = _registry_data()
    registry_ok = registry is not None
    reg_skills = _registry_map(registry)

    cutoff = _range_cutoff(time_range)
    try:
        runs = store.aggregate_skill_runtime(cutoff)
        timeline_ok = True
    except Exception as exc:  # noqa: BLE001
        log.debug("skill_analytics: timeline aggregate unavailable: %s", exc)
        runs, timeline_ok = {}, False
    timeline_unavailable = not timeline_ok

    all_keys = sorted(set(reg_skills) | set(runs))
    skills_out = []
    for key in all_keys:
        reg = reg_skills.get(key)
        rt = runs.get(key)
        if timeline_unavailable:
            # 源不可用：无法判断是否执行过 → 全部 runtime 字段 null + unavailable
            skills_out.append({
                "skill": key,
                "registered": reg is not None,
                "provenance": reg["provenance"] if reg else None,
                "review_decision": reg["review_decision"] if reg else None,
                "risk": reg["risk"] if reg else None,
                "version": reg["version"] if reg else None,
                "health": reg["health"] if reg else None,
                "observed_runs": None,
                "completed": None,
                "failed": None,
                "success_rate": None,
                "avg_duration_ms": None,
                "last_observed_at": None,
                "runtime_coverage": "unavailable",
            })
            continue
        observed_runs = rt["observed_runs"] if rt else 0
        completed = rt["completed"] if rt else 0
        failed = rt["failed"] if rt else 0
        success_rate = (completed / observed_runs) if observed_runs else None
        if reg:
            coverage = "observed" if observed_runs > 0 else "inventory_only"
        else:
            coverage = "observed" if observed_runs > 0 else "unavailable"
        skills_out.append({
            "skill": key,
            "registered": reg is not None,
            "provenance": reg["provenance"] if reg else None,
            "review_decision": reg["review_decision"] if reg else None,
            "risk": reg["risk"] if reg else None,
            "version": reg["version"] if reg else None,
            "health": reg["health"] if reg else None,
            "observed_runs": observed_runs,
            "completed": completed,
            "failed": failed,
            "success_rate": success_rate,
            "avg_duration_ms": rt["avg_duration_ms"] if rt else None,
            "last_observed_at": rt["last_observed_at"] if rt else None,
            "runtime_coverage": coverage,
        })

    observed_skills = [s for s in skills_out if (s["observed_runs"] or 0) > 0]
    coverage = {
        "registered_skills": len(reg_skills),
        "skills_with_observed_runtime": len(observed_skills),
        "skill_events": sum(s["observed_runs"] for s in skills_out if s["observed_runs"]),
        "runtime_identity_source": ["timeline_events skill.*"],
        "coverage_complete": False,
        "registry_metadata_present": registry_ok,
        "review_metadata_present": False,
        "partial": (not registry_ok) or timeline_unavailable,
        "source_status": {
            "timeline": "unavailable" if timeline_unavailable else "healthy",
            "registry": "unavailable" if not registry_ok else "healthy",
        },
    }
    return {"skills": skills_out, "coverage": coverage}


def compute_summary(store, time_range: str = "7d") -> dict:
    """Summary cards：Registered / Observed / Runs / Success Rate / Failed /
    未观测到执行（timeline unavailable → no_observed_execution=null，UI —）。"""
    data = compute_analytics(store, time_range)
    skills = data["skills"]
    tl_unavailable = data["coverage"]["source_status"]["timeline"] == "unavailable"
    if tl_unavailable:
        # 源不可用：无法区分"未观测"与"观测"→ no_observed_execution=null
        return {
            "registered_skills": data["coverage"]["registered_skills"],
            "observed_skills": None, "observed_runs": None, "success_rate": None,
            "failed_runs": None, "no_observed_execution": None,
            "coverage": data["coverage"], "time_range": time_range,
        }
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
    """过滤 + 排序 + 分页（limit ≤ 200）。

    非法 time_range → ValueError（API 层转 400，不静默退化为 all）。
    observed/unobserved 过滤不得返回 unavailable rows。
    """
    if time_range not in TIME_RANGES:
        raise ValueError(f"invalid time range: {time_range} (24h|7d|30d|all)")
    data = compute_analytics(store, time_range)
    skills = data["skills"]
    if status == "failed":
        skills = [s for s in skills if s["failed"]]
    elif status == "success":
        skills = [s for s in skills if s["completed"]]
    if provenance:
        skills = [s for s in skills if s.get("provenance") == provenance]
    if observed == "observed":
        skills = [s for s in skills if (s["observed_runs"] or 0) > 0]
    elif observed == "unobserved":
        # 未观测到执行：只含源健康且确为零运行的 skill（unavailable rows 排除）
        skills = [s for s in skills
                  if s["runtime_coverage"] != "unavailable"
                  and (s["observed_runs"] or 0) == 0]
    if search:
        q = search.lower()
        skills = [s for s in skills if q in s["skill"].lower()]
    sort_key = {
        "name": lambda s: s["skill"].lower(),
        "runs": lambda s: s["observed_runs"] or 0,
        "failures": lambda s: s["failed"] or 0,
        # 成功率最低：0%（有观测失败）排在 null/unobserved 之前 → null 用 2 垫底
        "rate": lambda s: (s["success_rate"] if s["success_rate"] is not None else 2),
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
    """单 skill 详情：registry 元数据 + 统计 + 最近运行事件。

    事件直接 SQL 查询（query_skill_runtime_events，不扫描全量）；
    统计来自 compute_analytics 的 SQL 聚合结果（不复制数据）。
    """
    data = compute_analytics(store, time_range)
    skill_data = next((s for s in data["skills"] if s["skill"] == skill), None)
    if skill_data is None:
        return {"error": f"skill not found: {skill}"}
    cutoff = _range_cutoff(time_range)
    try:
        related = store.query_skill_runtime_events(skill, cutoff, limit=timeline_limit)
    except Exception as exc:  # noqa: BLE001
        log.debug("skill_analytics: detail events unavailable: %s", exc)
        related = []
    return {"skill": skill_data, "recent_timeline_events": related}
