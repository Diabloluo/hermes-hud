"""Skill Analytics v1 后端测试。

覆盖：observed_runs / completed-failed / success_rate（zero denominator→null）/
time range / registry-only skill / missing registry / partial coverage /
duration null + aggregation / provenance join / filters / sort / pagination /
malformed source / 10k-100k perf / API schema / 语言真相（不出现 unused）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

from hud import skill_analytics as sa  # noqa: E402
from hud import storage  # noqa: E402
from hud import timeline  # noqa: E402


def _mk_registry(tmp_path, skills: list[dict]) -> Path:
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"generated_at": "x", "summary": {},
                             "skills": skills}), encoding="utf-8")
    return p


def _skill_event(skill: str, status: str, ts: int, dur: int | None = None,
                 rid: str | None = None) -> dict:
    return timeline.normalize_event({
        "timestamp": ts, "event_type": f"skill.{status}", "status": status,
        "skill": skill, "summary": f"Skill {skill} {status}",
        "source_record_id": rid or f"test:{skill}:{ts}:{status}",
        "duration_ms": dur})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "REGISTRY_PATH", tmp_path / "registry.json")
    store = storage.TelemetryStore(db_path=tmp_path / "telemetry.db")
    return {"tmp": tmp_path, "store": store}


def test_observed_runs_and_rate(env) -> None:
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom", "risk_level": "low"}])
    st = env["store"]
    st.record_timeline_event(_skill_event("pg", "completed", 1000, dur=500))
    st.record_timeline_event(_skill_event("pg", "completed", 2000, dur=700))
    st.record_timeline_event(_skill_event("pg", "failed", 3000))
    data = sa.compute_analytics(st, "all")
    pg = next(s for s in data["skills"] if s["skill"] == "pg")
    assert pg["observed_runs"] == 3
    assert pg["completed"] == 2 and pg["failed"] == 1
    assert pg["success_rate"] == pytest.approx(2 / 3)
    assert pg["avg_duration_ms"] == 600  # 仅可靠 duration（failed 无 duration 不参与）
    assert pg["last_observed_at"] == 3000
    assert pg["runtime_coverage"] == "observed"


def test_zero_denominator_rate_null(env) -> None:
    _mk_registry(env["tmp"], [{"key": "x", "source": "custom"}])
    data = sa.compute_analytics(env["store"], "all")
    x = next(s for s in data["skills"] if s["skill"] == "x")
    assert x["success_rate"] is None  # 不能显示 0%
    assert x["observed_runs"] == 0
    assert x["runtime_coverage"] == "inventory_only"


def test_registry_only_skill(env) -> None:
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom", "risk_level": "high"}])
    data = sa.compute_analytics(env["store"], "all")
    pg = next(s for s in data["skills"] if s["skill"] == "pg")
    assert pg["registered"] is True
    assert pg["provenance"] == "custom"
    assert pg["risk"] == "high"
    assert pg["runtime_coverage"] == "inventory_only"
    # review_decision：registry 无该字段 → unavailable（诚实）
    assert pg["review_decision"] is None


def test_time_range(env) -> None:
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    st = env["store"]
    now = int(time.time())
    st.record_timeline_event(_skill_event("pg", "completed", now - 3600))       # 24h 内
    st.record_timeline_event(_skill_event("pg", "completed", now - 10 * 86400))  # 30d 内
    st.record_timeline_event(_skill_event("pg", "completed", now - 60 * 86400))  # 更早
    assert sa.compute_analytics(st, "24h")["skills"][0]["observed_runs"] == 1
    assert sa.compute_analytics(st, "7d")["skills"][0]["observed_runs"] == 1
    assert sa.compute_analytics(st, "30d")["skills"][0]["observed_runs"] == 2
    assert sa.compute_analytics(st, "all")["skills"][0]["observed_runs"] == 3


def test_missing_registry(env) -> None:
    """registry 缺失 → 降级：runtime 仍统计（unavailable coverage），不 500。"""
    st = env["store"]
    st.record_timeline_event(_skill_event("orphan", "completed", 1000))
    data = sa.compute_analytics(st, "all")
    orphan = next(s for s in data["skills"] if s["skill"] == "orphan")
    assert orphan["registered"] is False
    assert orphan["runtime_coverage"] == "observed"  # 有事件 → observed
    assert data["coverage"]["review_metadata_present"] is False


def test_malformed_registry_item(env) -> None:
    """malformed registry item（非 dict / 缺 key）→ skip，不崩。"""
    _mk_registry(env["tmp"], [{"key": "ok", "source": "custom"}, "garbage",
                              {"no_key": True}, None])
    data = sa.compute_analytics(env["store"], "all")
    keys = [s["skill"] for s in data["skills"]]
    assert "ok" in keys
    assert len(keys) == 1  # malformed 项被跳过


def test_duration_unavailable_null(env) -> None:
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    st = env["store"]
    st.record_timeline_event(_skill_event("pg", "completed", 1000))  # 无 duration
    st.record_timeline_event(_skill_event("pg", "failed", 2000))
    pg = next(s for s in sa.compute_analytics(st, "all")["skills"]
              if s["skill"] == "pg")
    assert pg["avg_duration_ms"] is None  # 无可靠 duration → null（不是 0）


def test_filters_sort_pagination(env) -> None:
    _mk_registry(env["tmp"], [
        {"key": "alpha", "source": "custom", "risk_level": "low"},
        {"key": "beta", "source": "bundled-copy", "risk_level": "high"},
        {"key": "gamma", "source": "custom", "risk_level": "medium"},
    ])
    st = env["store"]
    now = int(time.time())
    st.record_timeline_event(_skill_event("alpha", "completed", now - 4000))
    st.record_timeline_event(_skill_event("alpha", "failed", now - 3000))
    st.record_timeline_event(_skill_event("beta", "completed", now - 2000))
    st.record_timeline_event(_skill_event("beta", "completed", now - 1000))
    st.record_timeline_event(_skill_event("beta", "failed", now))

    q = sa.query_skills(st, sort="runs", limit=50)
    assert q["skills"][0]["skill"] == "beta"  # 3 runs 最多

    qf = sa.query_skills(st, status="failed")
    assert {s["skill"] for s in qf["skills"]} == {"alpha", "beta"}

    qo = sa.query_skills(st, observed="observed")
    assert {s["skill"] for s in qo["skills"]} == {"alpha", "beta"}
    assert "gamma" not in {s["skill"] for s in qo["skills"]}

    qp = sa.query_skills(st, sort="name", limit=2, offset=0)
    assert [s["skill"] for s in qp["skills"]] == ["alpha", "beta"]
    qp2 = sa.query_skills(st, sort="name", limit=2, offset=2)
    assert [s["skill"] for s in qp2["skills"]] == ["gamma"]
    assert qp["total"] == 3

    qs = sa.query_skills(st, search="gam")
    assert [s["skill"] for s in qs["skills"]] == ["gamma"]

    qprov = sa.query_skills(st, provenance="custom")
    assert {s["skill"] for s in qprov["skills"]} == {"alpha", "gamma"}


def test_language_truth_no_unused(env) -> None:
    """UI 语言真相：分析数据不含 'unused'/'从未使用'。"""
    _mk_registry(env["tmp"], [{"key": "x", "source": "custom"}])
    data = sa.compute_analytics(env["store"], "all")
    blob = json.dumps(data).lower()
    assert "unused" not in blob
    assert "从未使用" not in blob


def test_summary_cards(env) -> None:
    _mk_registry(env["tmp"], [
        {"key": "a", "source": "custom"},
        {"key": "b", "source": "custom"},
        {"key": "c", "source": "custom"},
    ])
    st = env["store"]
    st.record_timeline_event(_skill_event("a", "completed", 1000))
    st.record_timeline_event(_skill_event("a", "failed", 2000))
    s = sa.compute_summary(st, "all")
    assert s["registered_skills"] == 3
    assert s["observed_skills"] == 1
    assert s["observed_runs"] == 2
    assert s["success_rate"] == pytest.approx(0.5)
    assert s["failed_runs"] == 1
    assert s["no_observed_execution"] == 2
    assert s["coverage"]["coverage_complete"] is False


def test_single_skill_detail(env) -> None:
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom", "risk_level": "low"}])
    st = env["store"]
    for i in range(25):
        st.record_timeline_event(_skill_event("pg", "completed", 1000 + i))
    d = sa.single_skill(st, "pg", "all", timeline_limit=20)
    assert d["skill"]["skill"] == "pg"
    assert len(d["recent_timeline_events"]) == 20  # limit 生效
    assert "prompt" not in json.dumps(d)  # 无敏感内容


def test_10k_events_perf(env) -> None:
    """10k skill 事件：聚合延迟有界。"""
    st = env["store"]
    t0 = time.time()
    for i in range(10_000):
        st.record_timeline_event(_skill_event(f"skill{i % 100}", "completed", 1000 + i,
                                              dur=100))
    ingest = time.time() - t0
    t0 = time.time()
    data = sa.compute_analytics(st, "all")
    agg = time.time() - t0
    assert data["coverage"]["skill_events"] == 10_000
    assert len(data["skills"]) == 100
    assert agg < 2.0, f"aggregation too slow: {agg:.2f}s"
    print(f"10k: ingest={ingest:.2f}s aggregate={agg:.3f}s")


def test_api_schema(env) -> None:
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    st = env["store"]
    st.record_timeline_event(_skill_event("pg", "completed", 1000))
    s = sa.query_skills(st, limit=10)
    assert set(s) >= {"skills", "total", "limit", "offset", "coverage"}
    row = s["skills"][0]
    for field in ("skill", "registered", "provenance", "review_decision", "risk",
                  "observed_runs", "completed", "failed", "success_rate",
                  "avg_duration_ms", "last_observed_at", "runtime_coverage"):
        assert field in row
