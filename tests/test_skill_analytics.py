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


def test_100k_truth_benchmark(env) -> None:
    """150 skills × 100k events（bulk fixture）：aggregate/summary/detail 延迟 + RSS。

    硬断言：aggregate < 1s、detail < 500ms（本地；CI 放宽到 5s/3s）。
    """
    import os as _os
    import resource
    _mk_registry(env["tmp"], [{"key": f"s{i}", "source": "custom"} for i in range(150)])
    st = env["store"]
    events = [_skill_event(f"s{i % 150}", "completed", 1700000000 + (i % 5000),
                           dur=200 + (i % 100), rid=f"k{i}")
              for i in range(100_000)]
    t0 = time.time()
    st.bulk_record_timeline_events(events)
    ingest = time.time() - t0
    t0 = time.time(); data = sa.compute_analytics(st, "all"); t_agg = time.time() - t0
    t0 = time.time(); summ = sa.compute_summary(st, "all"); t_summary = time.time() - t0
    t0 = time.time(); d = sa.single_skill(st, "s7", "all"); t_detail = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # macOS: bytes
    assert data["coverage"]["skill_events"] == 100_000
    assert len(data["skills"]) == 150
    assert summ["observed_runs"] == 100_000
    assert d["skill"]["skill"] == "s7"
    ci = bool(_os.environ.get("CI"))
    agg_lim = 5.0 if ci else 1.0
    det_lim = 3.0 if ci else 0.5
    assert t_agg < agg_lim, f"aggregate {t_agg:.2f}s >= {agg_lim}s"
    assert t_detail < det_lim, f"detail {t_detail:.2f}s >= {det_lim}s"
    print(f"100k(bulk): ingest={ingest:.1f}s aggregate={t_agg*1000:.0f}ms "
          f"summary={t_summary*1000:.0f}ms detail={t_detail*1000:.0f}ms "
          f"RSS={rss/1024/1024:.1f}MB")


# ---------- SQL Aggregation Final Architecture Gate tests ----------

def test_sliding_window_aging_no_cache(env, monkeypatch) -> None:
    """sliding window：事件 24h 内 → 无 DB 变更 → 时钟推进超 24h →
    第二次调用 observed_runs 1→0（无缓存/无 TTL 依赖）。"""
    now = int(time.time())
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    st = env["store"]
    st.record_timeline_event(_skill_event("pg", "completed", now - 3600))  # 24h 内
    # 第一次：cutoff = now - 24h（事件在窗口内）
    monkeypatch.setattr(sa, "_range_cutoff", lambda r, now_=None: now - 86400)
    data1 = sa.compute_analytics(st, "24h")
    pg1 = next(s for s in data1["skills"] if s["skill"] == "pg")
    assert pg1["observed_runs"] == 1
    # 时钟推进超 24h（DB 零变更）：now2 = now + 86400 → 24h 前 = now
    monkeypatch.setattr(sa, "_range_cutoff", lambda r, now_=None: now)
    data2 = sa.compute_analytics(st, "24h")
    pg2 = next(s for s in data2["skills"] if s["skill"] == "pg")
    assert pg2["observed_runs"] == 0  # 1 → 0（sliding，非 TTL）


def test_registry_freshness(env) -> None:
    """registry 文件变化（2→3 skills，timeline 不变）→ 下次调用 registered=3。"""
    _mk_registry(env["tmp"], [{"key": "a", "source": "custom"},
                              {"key": "b", "source": "custom"}])
    data1 = sa.compute_analytics(env["store"], "all")
    assert data1["coverage"]["registered_skills"] == 2
    _mk_registry(env["tmp"], [{"key": "a", "source": "custom"},
                              {"key": "b", "source": "custom"},
                              {"key": "c", "source": "custom"}])
    data2 = sa.compute_analytics(env["store"], "all")
    assert data2["coverage"]["registered_skills"] == 3  # 立即反映，无 stale


def test_source_outage_and_recovery(env, monkeypatch) -> None:
    """healthy → 聚合失败 → unavailable/partial → 恢复（DB 未变）→ 立即 healthy。"""
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    st = env["store"]
    st.record_timeline_event(_skill_event("pg", "completed", int(time.time()) - 100))
    # healthy
    d1 = sa.compute_analytics(st, "all")
    assert d1["coverage"]["source_status"]["timeline"] == "healthy"
    # 故障（单点替换，保留原方法引用用于恢复——避免 undo 撤销 fixture 的 REGISTRY_PATH）
    orig_agg = st.aggregate_skill_runtime
    monkeypatch.setattr(st, "aggregate_skill_runtime",
                        lambda cutoff: (_ for _ in ()).throw(RuntimeError("locked")))
    d2 = sa.compute_analytics(st, "all")
    assert d2["coverage"]["partial"] is True
    assert d2["coverage"]["source_status"]["timeline"] == "unavailable"
    assert all(s["runtime_coverage"] == "unavailable" for s in d2["skills"])
    # 恢复（DB 零变更）
    monkeypatch.setattr(st, "aggregate_skill_runtime", orig_agg)
    d3 = sa.compute_analytics(st, "all")
    assert d3["coverage"]["source_status"]["timeline"] == "healthy"
    assert d3["coverage"]["partial"] is False
    pg = next(s for s in d3["skills"] if s["skill"] == "pg")
    assert pg["runtime_coverage"] == "observed"  # 不 stale unavailable


def test_summary_unavailable_vs_zero(env, monkeypatch) -> None:
    """timeline unavailable → no_observed_execution=null（UI —）；
    source healthy + zero → no_observed_execution=registered count。"""
    _mk_registry(env["tmp"], [{"key": "a", "source": "custom"},
                              {"key": "b", "source": "custom"}])
    # healthy + zero
    s1 = sa.compute_summary(env["store"], "all")
    assert s1["no_observed_execution"] == 2  # registered count
    assert s1["observed_runs"] == 0
    # unavailable
    monkeypatch.setattr(env["store"], "aggregate_skill_runtime",
                        lambda cutoff: (_ for _ in ()).throw(RuntimeError("x")))
    s2 = sa.compute_summary(env["store"], "all")
    assert s2["no_observed_execution"] is None  # UI —
    assert s2["observed_runs"] is None
    assert s2["success_rate"] is None


def test_unobserved_filter_excludes_unavailable(env, monkeypatch) -> None:
    """observed/unobserved 过滤不得返回 unavailable rows。"""
    _mk_registry(env["tmp"], [{"key": "a", "source": "custom"}])
    st = env["store"]
    st.record_timeline_event(_skill_event("a", "completed", int(time.time()) - 100))
    # healthy：unobserved = 无运行 skill（a 有运行 → 空）
    q1 = sa.query_skills(st, observed="unobserved", time_range="all")
    assert all(s["runtime_coverage"] != "unavailable" for s in q1["skills"])
    # unavailable：unobserved 过滤 → 空（unavailable rows 不冒充未观测）
    monkeypatch.setattr(st, "aggregate_skill_runtime",
                        lambda cutoff: (_ for _ in ()).throw(RuntimeError("x")))
    q2 = sa.query_skills(st, observed="unobserved", time_range="all")
    assert q2["skills"] == []  # 不返回 unavailable rows


def test_exact_event_allowlist(env) -> None:
    """聚合只认 skill.completed / skill.failed（其他类型不计）。"""
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    st = env["store"]
    now = int(time.time())
    st.record_timeline_event(_skill_event("pg", "completed", now - 100))
    st.record_timeline_event(_skill_event("pg", "failed", now - 50))
    # 非白名单事件（如 skill.started 类——即使存在也不计入）
    st.record_timeline_event(timeline.normalize_event({
        "timestamp": now, "event_type": "skill.started", "status": "started",
        "skill": "pg", "summary": "x", "source_record_id": "sx"}))
    data = sa.compute_analytics(st, "all")
    pg = next(s for s in data["skills"] if s["skill"] == "pg")
    assert pg["observed_runs"] == 2  # 只 2 个白名单事件
    assert pg["completed"] == 1 and pg["failed"] == 1


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


# ---------- Truth & Scale Final Gate tests ----------

def test_source_unavailable_partial_and_unavailable_coverage(env, monkeypatch) -> None:
    """timeline 源不可用 → partial=true + runtime_coverage=unavailable
    （禁止显示为"未观测到执行"）。"""
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])

    def boom(cutoff):
        raise RuntimeError("timeline db locked")

    monkeypatch.setattr(env["store"], "aggregate_skill_runtime", boom)
    data = sa.compute_analytics(env["store"], "all")
    assert data["coverage"]["partial"] is True
    assert data["coverage"]["source_status"]["timeline"] == "unavailable"
    pg = next(s for s in data["skills"] if s["skill"] == "pg")
    assert pg["runtime_coverage"] == "unavailable"  # 不是 inventory_only / observed
    assert pg["observed_runs"] is None  # 源不可用 → runtime 字段全 null
    assert pg["success_rate"] is None
    assert pg["avg_duration_ms"] is None
    assert pg["last_observed_at"] is None


def test_source_healthy_zero_events(env) -> None:
    """source healthy + zero events → inventory_only + partial=false（区别于 unavailable）。"""
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    data = sa.compute_analytics(env["store"], "all")
    assert data["coverage"]["partial"] is False
    assert data["coverage"]["source_status"]["timeline"] == "healthy"
    pg = next(s for s in data["skills"] if s["skill"] == "pg")
    assert pg["runtime_coverage"] == "inventory_only"  # 未观测到（源健康）


def test_same_timestamp_1000_pagination(env) -> None:
    """1000 条同 timestamp skill 事件，page=500 稳定游标：observed=1000，
    missing=0, duplicates=0。"""
    st = env["store"]
    ts = 1756000000
    for i in range(1000):
        st.record_timeline_event(_skill_event("pg", "completed", ts, rid=f"t{i}"))
    data = sa.compute_analytics(st, "all")
    assert data["coverage"]["skill_events"] == 1000
    pg = next(s for s in data["skills"] if s["skill"] == "pg")
    assert pg["observed_runs"] == 1000
    assert pg["completed"] == 1000
    assert pg["failed"] == 0
    assert data["coverage"]["skills_with_observed_runtime"] == 1


def test_review_metadata_truth(env) -> None:
    """registry 有 → registry_metadata_present=true；Review Gate 未接入 →
    review_metadata_present 绝不能 true。"""
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    data = sa.compute_analytics(env["store"], "all")
    cov = data["coverage"]
    assert cov["registry_metadata_present"] is True
    assert cov["review_metadata_present"] is False  # 未接入 → 绝不 true


def test_null_rate_sort_failed_before_null(env) -> None:
    """"成功率最低"排序：0%（有观测失败）排在 null/unobserved 前。"""
    _mk_registry(env["tmp"], [
        {"key": "aa", "source": "custom"},  # 无运行 → null
        {"key": "bb", "source": "custom"},  # 0% 成功（全失败）
        {"key": "cc", "source": "custom"},  # 50%
    ])
    st = env["store"]
    now = int(time.time())
    st.record_timeline_event(_skill_event("bb", "failed", now - 3000))
    st.record_timeline_event(_skill_event("bb", "failed", now - 2000))
    st.record_timeline_event(_skill_event("cc", "completed", now - 1000))
    st.record_timeline_event(_skill_event("cc", "failed", now))
    q = sa.query_skills(st, sort="rate")
    order = [s["skill"] for s in q["skills"]]
    assert order[0] == "bb"   # 0% 最前
    assert order[1] == "cc"   # 50%
    assert order[-1] == "aa"  # null 垫底


def test_api_bounds_invalid_range(env) -> None:
    """非法 range 不得静默退化为 all。"""
    _mk_registry(env["tmp"], [{"key": "pg", "source": "custom"}])
    st = env["store"]
    st.record_timeline_event(_skill_event("pg", "completed", int(time.time()) - 100))
    # 非法 range：query_skills 校验（API 层转 400）；不静默退化为 all
    with pytest.raises(ValueError):
        sa.query_skills(st, time_range="1y")
    # 合法 range 正常
    q = sa.query_skills(st, time_range="24h")
    assert q["total"] == 1
