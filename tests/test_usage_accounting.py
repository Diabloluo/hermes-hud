"""P1-3 Token/Cost 口径测试（fixture 手工对账）。

fixture 设计：
  1. 一个主会话（sessions 表）        input=1000 output=100 est=0.5 actual=0.4
  2. 同 session 的 task='' usage 行    input=1000 output=100 api_call_count=1
                                       （主会话重复记账，必须被排除）
  3. 两个不同 auxiliary tasks:
     - compression  input=200 output=50  api_call_count=2 est=0.1
     - vision       input=300 output=60  api_call_count=3 est=0.2

手工预期：
  by_day 今日: input = 1000+200+300 = 1500
               output = 100+50+60 = 210
               api_calls = 0(主会话无 api_call_count 列，不虚构) + 2 + 3 = 5
               est_cost = 0.5+0.1+0.2 = 0.8
               actual_cost = 0.4
  by_task:  compression {input:200, api_calls:2}
            vision      {input:300, api_calls:3}
  by_model: A {input:1500, api_calls:5, est:0.8}
  totals:   est_cost 0.8, actual_cost 0.4, api_calls 5
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.hud import collectors

TODAY = int(time.time())


def _build_fixture_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY, started_at REAL, ended_at REAL, title TEXT,
        model TEXT, input_tokens INTEGER, output_tokens INTEGER,
        cache_read_tokens INTEGER, cache_write_tokens INTEGER,
        reasoning_tokens INTEGER, estimated_cost_usd REAL, actual_cost_usd REAL,
        cost_status TEXT, billing_provider TEXT
    );
    CREATE TABLE session_model_usage (
        session_id TEXT, model TEXT, billing_provider TEXT, billing_mode TEXT,
        task TEXT, api_call_count INTEGER, input_tokens INTEGER, output_tokens INTEGER,
        cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER,
        estimated_cost_usd REAL, actual_cost_usd REAL, first_seen REAL, last_seen REAL
    );
    """)
    # 主会话
    cur.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", TODAY, TODAY + 100, "主会话", "modelA",
         1000, 100, 500, 0, 0, 0.5, 0.4, "estimated", "providerX"),
    )
    # 同 session task='' —— 主会话重复记账（应排除）
    cur.execute(
        "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", "modelA", "providerX", "", "", 1, 1000, 100, 500, 0, 0, 0.5, 0.4, TODAY, TODAY),
    )
    # compression 辅助
    cur.execute(
        "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", "modelA", "providerX", "", "compression", 2, 200, 50, 100, 0, 0, 0.1, 0.0, TODAY, TODAY),
    )
    # vision 辅助
    cur.execute(
        "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", "modelA", "providerX", "", "vision", 3, 300, 60, 150, 0, 0, 0.2, 0.0, TODAY, TODAY),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def usage_db(tmp_path, monkeypatch):
    db = tmp_path / "state.db"
    _build_fixture_db(db)
    monkeypatch.setattr(collectors, "HERMES_HOME", tmp_path)
    return db


def test_usage_accounting(usage_db) -> None:
    """代码计算结果必须与手工预期完全一致。"""
    r = collectors.collect_usage(days=30)
    assert "error" not in r, r

    # by_day（今天）
    today_agg = next(d for d in r["by_day"] if d["day"] != "unknown")
    assert today_agg["input"] == 1500, today_agg["input"]
    assert today_agg["output"] == 210, today_agg["output"]
    assert today_agg["api_calls"] == 5, today_agg["api_calls"]
    assert abs(today_agg["est_cost"] - 0.8) < 1e-9
    assert abs(today_agg["actual_cost"] - 0.4) < 1e-9

    # by_task（task='' 被排除）
    tasks = {t["task"]: t for t in r["by_task"]}
    assert set(tasks) == {"compression", "vision"}
    assert tasks["compression"]["input"] == 200
    assert tasks["compression"]["api_calls"] == 2
    assert tasks["vision"]["input"] == 300
    assert tasks["vision"]["api_calls"] == 3

    # by_model（主 + 辅合并，不重复计数）
    models = {m["model"]: m for m in r["by_model"]}
    assert models["modelA"]["input"] == 1500
    assert models["modelA"]["api_calls"] == 5
    assert abs(models["modelA"]["est_cost"] - 0.8) < 1e-9

    # totals
    t = r["totals"]
    assert t["input"] == 1500
    assert t["output"] == 210
    assert t["api_calls"] == 5
    assert abs(t["est_cost"] - 0.8) < 1e-9
    assert abs(t["actual_cost"] - 0.4) < 1e-9


def test_usage_excludes_empty_task_rows(usage_db) -> None:
    """task='' 的 usage 行绝不进入统计（否则主会话翻倍）。"""
    r = collectors.collect_usage(days=30)
    # 若把 task='' 的 1000 input 重复计入，input 会变成 2500
    assert r["totals"]["input"] == 1500
