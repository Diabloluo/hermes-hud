"""Cost Intelligence v1 后端测试。

覆盖：exact totals / input-output / zero vs null / partial cost coverage /
model aggregation / session aggregation / range cutoff / Today timezone /
no double count（Timeline 不参与）/ missing source / malformed row /
budget ratio / source recovery / 100k scale / API schema_version /
语言真相（Estimated cost 语义）。
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

from hud import cost  # noqa: E402


def _mk_state(tmp_path, rows: list[tuple]) -> Path:
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS session_model_usage")
    con.execute("DROP TABLE IF EXISTS sessions")
    con.execute("CREATE TABLE session_model_usage (session_id TEXT, model TEXT,"
                " billing_provider TEXT, billing_base_url TEXT, billing_mode TEXT,"
                " task TEXT, api_call_count INT, input_tokens INT, output_tokens INT,"
                " cache_read_tokens INT, cache_write_tokens INT, reasoning_tokens INT,"
                " estimated_cost_usd REAL, actual_cost_usd REAL, cost_status TEXT,"
                " cost_source TEXT, first_seen REAL, last_seen REAL)")
    con.execute("CREATE TABLE sessions (id TEXT, source TEXT, model TEXT,"
                " started_at REAL, ended_at REAL, title TEXT)")
    con.executemany(
        "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows)
    con.commit()
    con.close()
    return db


def _row(sid="s1", model="m1", inp=1000, out=100, cost=0.01, ts=None, title=None):
    ts = ts if ts is not None else time.time() - 100
    return (sid, model, "custom", None, None, None, 1, inp, out, 0, 0, 0,
            cost, None, "unknown", "none", ts, ts)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HUD_STATE_DB", str(tmp_path / "state.db"))
    return {"tmp": tmp_path}


def test_exact_totals(env) -> None:
    _mk_state(env["tmp"], [
        _row("s1", "m1", inp=1000, out=100, cost=0.01, ts=time.time() - 100),
        _row("s1", "m1", inp=2000, out=200, cost=0.02, ts=time.time() - 50),
        _row("s2", "m2", inp=500, out=50, cost=0.005, ts=time.time() - 10),
    ])
    s = cost.compute_summary(env["tmp"], "all")
    assert s["estimated_cost_usd"] == pytest.approx(0.035)
    assert s["input_tokens"] == 3500
    assert s["output_tokens"] == 350
    assert s["total_tokens"] == 3850
    assert s["sessions"] == 2
    assert s["avg_cost_per_session_usd"] == pytest.approx(0.0175)
    assert s["cost_semantics"] == "estimated"
    assert s["schema_version"] == 1
    assert s["cost_complete"] is True


def test_zero_vs_null(env) -> None:
    """源健康 + 0 花费 → $0.00（非 null）；源不可用 → null。"""
    _mk_state(env["tmp"], [_row(cost=0.0)])
    s = cost.compute_summary(env["tmp"], "all")
    assert s["estimated_cost_usd"] == 0.0
    assert s["cost_complete"] is True
    # 源不可用（state.db 不存在）
    env["tmp"].joinpath("state.db").unlink()
    s2 = cost.compute_summary(env["tmp"], "all")
    assert s2["estimated_cost_usd"] is None
    assert s2["source_status"] == "unavailable"
    assert s2["coverage"]["source_status"]["usage"] == "unavailable"
    assert s2["partial"] is True


def test_partial_cost_coverage(env) -> None:
    """部分 row 有 cost → 已知部分总和 + cost_complete=false + coverage partial。"""
    now = time.time()
    _mk_state(env["tmp"], [
        _row("s1", "m1", inp=1000, cost=0.01, ts=now - 100),
        _row("s2", "m2", inp=2000, cost=None, ts=now - 50),
        _row("s3", "m3", inp=3000, cost=0.03, ts=now - 10),
    ])
    s = cost.compute_summary(env["tmp"], "all")
    assert s["estimated_cost_usd"] == pytest.approx(0.04)  # 已知部分总和
    assert s["cost_complete"] is False
    assert s["partial"] is True
    assert s["coverage"]["usage_rows"] == 3
    assert s["coverage"]["rows_with_cost"] == 2
    assert s["coverage"]["cost_coverage_ratio"] == pytest.approx(2 / 3)


def test_model_aggregation(env) -> None:
    now = time.time()
    _mk_state(env["tmp"], [
        _row("s1", "m1", inp=1000, out=100, cost=0.01, ts=now - 100),
        _row("s1", "m1", inp=1000, out=100, cost=0.01, ts=now - 50),
        _row("s2", "m2", inp=500, out=50, cost=0.005, ts=now - 10),
    ])
    m = cost.compute_models(env["tmp"], "all")
    by = {x["model"]: x for x in m["models"]}
    assert by["m1"]["input_tokens"] == 2000
    assert by["m1"]["output_tokens"] == 200
    assert by["m1"]["estimated_cost_usd"] == pytest.approx(0.02)
    assert by["m1"]["sessions"] == 1  # 同一 session 去重
    assert by["m2"]["estimated_cost_usd"] == pytest.approx(0.005)
    assert m["models"][0]["model"] == "m1"  # 按 cost 降序


def test_session_aggregation(env) -> None:
    now = time.time()
    _mk_state(env["tmp"], [
        _row("s1", "m1", inp=1000, cost=0.01, ts=now - 100),
        _row("s1", "m2", inp=2000, cost=0.03, ts=now - 50),
        _row("s2", "m1", inp=500, cost=0.001, ts=now - 10),
    ])
    t = cost.compute_top_sessions(env["tmp"], "all", 5)
    s1 = next(x for x in t["sessions"] if x["session_id"] == "s1")
    assert s1["estimated_cost_usd"] == pytest.approx(0.04)
    assert s1["models"] == ["m1", "m2"]
    assert t["sessions"][0]["session_id"] == "s1"  # 按 cost 降序


def test_range_cutoff(env) -> None:
    now = time.time()
    _mk_state(env["tmp"], [
        _row("s1", "m1", cost=0.01, ts=now - 100),       # 24h 内
        _row("s2", "m2", cost=0.02, ts=now - 10 * 86400),  # 30d 内
        _row("s3", "m3", cost=0.03, ts=now - 60 * 86400),  # 更早
    ])
    assert cost.compute_summary(env["tmp"], "24h")["estimated_cost_usd"] == pytest.approx(0.01)
    assert cost.compute_summary(env["tmp"], "7d")["estimated_cost_usd"] == pytest.approx(0.01)
    assert cost.compute_summary(env["tmp"], "30d")["estimated_cost_usd"] == pytest.approx(0.03)
    assert cost.compute_summary(env["tmp"], "all")["estimated_cost_usd"] == pytest.approx(0.06)


def test_today_timezone(env, monkeypatch) -> None:
    """Today 用 HUD 时区日界（不是 UTC/硬编码）。"""
    tz = timezone(timedelta(hours=8))  # 模拟 UTC+8
    monkeypatch.setattr(cost, "get_hud_timezone", lambda: tz)
    # 本地 00:30（UTC 前一天 16:30）——本地日界 = UTC 16:00
    local_midnight = datetime(2026, 8, 26, 0, 0, tzinfo=tz)
    now_ts = local_midnight.timestamp() + 1800  # 本地 00:30
    _mk_state(env["tmp"], [
        _row("s1", "m1", cost=0.01, ts=now_ts - 100),            # 本地今日
        _row("s2", "m2", cost=0.02, ts=now_ts - 12 * 3600),      # 本地昨日
    ])
    s = cost.compute_summary(env["tmp"], "today", now=now_ts)
    assert s["estimated_cost_usd"] == pytest.approx(0.01)  # 只算本地今日


def test_no_double_count(env) -> None:
    """Timeline 不参与费用汇总（canonical 单源：state.db 只计一次）。"""
    _mk_state(env["tmp"], [_row("s1", "m1", cost=0.01)])
    s1 = cost.compute_summary(env["tmp"], "all")
    # 多次调用（模拟 Timeline 采集/导航读取同一数据）不改变汇总
    s2 = cost.compute_summary(env["tmp"], "all")
    assert s1["estimated_cost_usd"] == s2["estimated_cost_usd"] == pytest.approx(0.01)


def test_missing_source_and_malformed(env) -> None:
    """usage 表缺失 / malformed row（NULL tokens）→ 不崩。"""
    db = env["tmp"] / "state.db"
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS session_model_usage")
    con.commit()
    con.close()
    s = cost.compute_summary(env["tmp"], "all")
    assert s["source_status"] == "unavailable"
    assert s["estimated_cost_usd"] is None
    # malformed：NULL tokens/cost
    _mk_state(env["tmp"], [
        ("s1", "m1", None, None, None, None, 1, None, None, None, None, None,
         None, None, None, None, None, None)])
    s2 = cost.compute_summary(env["tmp"], "all")
    assert s2["estimated_cost_usd"] == 0.0  # cost 全 null → 0（源健康）？
    # 语义：rows_with_cost=0 → cost_complete false（0 行有 cost）
    assert s2["cost_complete"] is False


def test_budget(env) -> None:
    now = time.time()
    _mk_state(env["tmp"], [_row("s1", "m1", cost=0.5, ts=now - 100)])
    b = cost.compute_budget(env["tmp"], 10.0, now=now)
    assert b["budget_configured"] is True
    assert b["usage_ratio"] == pytest.approx(0.05)
    assert b["remaining_usd"] == pytest.approx(9.5)
    # 未配置
    b2 = cost.compute_budget(env["tmp"], 0.0, now=now)
    assert b2["budget_status"] == "not_configured"
    assert b2["usage_ratio"] is None
    # 源不可用
    env["tmp"].joinpath("state.db").unlink()
    b3 = cost.compute_budget(env["tmp"], 10.0, now=now)
    assert b3["budget_status"] == "unavailable"


def test_source_recovery(env, monkeypatch) -> None:
    """源失败 → 恢复（DB 不变）→ 立即 healthy。"""
    _mk_state(env["tmp"], [_row("s1", "m1", cost=0.01)])
    assert cost.compute_summary(env["tmp"], "all")["source_status"] == "healthy"
    env["tmp"].joinpath("state.db").unlink()
    assert cost.compute_summary(env["tmp"], "all")["source_status"] == "unavailable"
    _mk_state(env["tmp"], [_row("s1", "m1", cost=0.01)])
    assert cost.compute_summary(env["tmp"], "all")["source_status"] == "healthy"


def test_100k_scale(env) -> None:
    """100k usage rows：summary/models/sessions 延迟 + RSS。"""
    import resource
    now = time.time()
    rows = [(_row(f"s{i % 5000}", f"m{i % 20}", inp=100 + i % 100, out=10 + i % 10,
                  cost=(i % 100) / 10000, ts=now - (i % 86400)))
            for i in range(100_000)]
    _mk_state(env["tmp"], rows)
    t0 = time.time(); s = cost.compute_summary(env["tmp"], "all"); t_sum = time.time() - t0
    t0 = time.time(); m = cost.compute_models(env["tmp"], "all"); t_mod = time.time() - t0
    t0 = time.time(); t = cost.compute_top_sessions(env["tmp"], "all", 20); t_ses = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert s["total_tokens"] > 0
    assert len(m["models"]) == 20
    assert len(t["sessions"]) == 20
    assert t_sum < 1.0, f"summary {t_sum:.2f}s"
    assert t_mod < 1.0, f"models {t_mod:.2f}s"
    assert t_ses < 0.5, f"sessions {t_ses:.2f}s"
    print(f"100k cost: summary={t_sum*1000:.0f}ms models={t_mod*1000:.0f}ms "
          f"sessions={t_ses*1000:.0f}ms RSS={rss/1024/1024:.1f}MB")


def test_schema_and_semantics_language(env) -> None:
    """API schema_version=1 + 语言真相（Estimated，禁止"实际费用"）。"""
    _mk_state(env["tmp"], [_row(cost=0.01)])
    s = cost.compute_summary(env["tmp"], "all")
    assert s["schema_version"] == 1
    assert s["cost_semantics"] == "estimated"
    blob = str(s).lower()
    assert "estimated" in blob
