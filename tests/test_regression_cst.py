"""P0-2 回归测试：CST is not defined（v1.0.1 运行时 bug）。

此测试必须：
  - 在 v1.0.1 原代码上失败（collect_usage 里 datetime.now(CST) 的 NameError）
  - 在修复后通过（collectors.get_hud_timezone()）

覆盖：
  - 临时 state.db + 当天 session 行 → collect_db 的 collect_usage 路径
  - HUD_TIMEZONE=Asia/Shanghai 显式设置
  - 未设置 HUD_TIMEZONE（系统本地时区）
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.hud import collectors


def _make_state_db(path: Path) -> None:
    """构造最小 state.db：按真实 Hermes schema 建 sessions/messages/session_model_usage，含当天一条主会话。"""
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE sessions ("
        " id TEXT PRIMARY KEY, source TEXT, user_id TEXT, model TEXT, model_config TEXT,"
        " system_prompt TEXT, parent_session_id TEXT, started_at REAL, ended_at REAL,"
        " end_reason TEXT, message_count INTEGER, tool_call_count INTEGER,"
        " input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,"
        " cache_write_tokens INTEGER, reasoning_tokens INTEGER, cwd TEXT,"
        " billing_provider TEXT, billing_base_url TEXT, billing_mode TEXT,"
        " estimated_cost_usd REAL, actual_cost_usd REAL, cost_status TEXT,"
        " cost_source TEXT, pricing_version TEXT, title TEXT, api_call_count INTEGER,"
        " handoff_state TEXT, handoff_platform TEXT, handoff_error TEXT,"
        " rewind_count INTEGER, archived INTEGER, git_branch TEXT, git_repo_root TEXT,"
        " session_key TEXT, chat_id TEXT, chat_type TEXT, thread_id TEXT,"
        " display_name TEXT, origin_json TEXT, last_activity_at REAL,"
        " last_activity_description TEXT, last_activity_provenance TEXT)"
    )
    now = time.time()
    cur.execute(
        "INSERT INTO sessions (id, source, model, title, started_at, ended_at,"
        " message_count, tool_call_count, input_tokens, output_tokens,"
        " cache_read_tokens, cache_write_tokens, reasoning_tokens,"
        " estimated_cost_usd, actual_cost_usd, cost_status, billing_provider,"
        " api_call_count, last_activity_at)"
        " VALUES ('s-today', 'desktop', 'deepseek-v4-flash', 'today', ?, ?, 3, 2,"
        " 1000, 100, 500, 50, 20, 0.5, 0.4, 'actual', 'deepseek', 1, ?)",
        (now, now, now),
    )
    cur.execute(
        "CREATE TABLE messages ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
        " content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,"
        " timestamp REAL, token_count INTEGER, finish_reason TEXT,"
        " platform_message_id TEXT, active INTEGER)"
    )
    cur.execute(
        "INSERT INTO messages (session_id, role, content, timestamp, active)"
        " VALUES ('s-today', 'user', 'hi', ?, 1)",
        (now,),
    )
    cur.execute(
        "CREATE TABLE session_model_usage ("
        " session_id TEXT, model TEXT, billing_provider TEXT, billing_base_url TEXT,"
        " billing_mode TEXT, task TEXT, api_call_count INTEGER, input_tokens INTEGER,"
        " output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,"
        " reasoning_tokens INTEGER, estimated_cost_usd REAL, actual_cost_usd REAL,"
        " cost_status TEXT, cost_source TEXT, first_seen REAL, last_seen REAL)"
    )
    cur.execute(
        "INSERT INTO session_model_usage (session_id, model, billing_provider, task,"
        " api_call_count, input_tokens, output_tokens, cache_read_tokens,"
        " cache_write_tokens, reasoning_tokens, estimated_cost_usd, actual_cost_usd,"
        " cost_status, first_seen, last_seen)"
        " VALUES ('s-today', 'deepseek-v4-flash', 'deepseek', '', 1, 1000, 100, 500,"
        " 50, 20, 0.5, 0.4, 'actual', ?, ?)",
        (now, now),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """把 HERMES_HOME 指向临时目录，并放置一个含当天会话的 state.db。"""
    home = tmp_path / "home"
    home.mkdir()
    _make_state_db(home / "state.db")
    monkeypatch.setenv("HERMES_HOME", str(home))
    # 让 collectors 模块级 HERMES_HOME 指向临时 home
    monkeypatch.setattr(collectors, "HERMES_HOME", home)
    return home


def test_collect_db_with_today_session_no_cst_error(fake_home, monkeypatch) -> None:
    """必须真实触发 collect_usage 的 '今日' 路径：当天 session 行存在。"""
    monkeypatch.delenv("HUD_TIMEZONE", raising=False)
    out = collectors.collect_db()
    assert out.get("error") is None, f"collect_db error: {out.get('error')}"
    # 今日会话应被统计到
    ts = out.get("today_sessions") or {}
    assert ts.get("count", 0) >= 1, "今天应至少 1 个会话"


def test_collect_usage_hud_timezone_asia_shanghai(fake_home, monkeypatch) -> None:
    """HUD_TIMEZONE=Asia/Shanghai 时正常。"""
    monkeypatch.setenv("HUD_TIMEZONE", "Asia/Shanghai")
    out = collectors.collect_usage(days=30)
    assert out.get("error") is None, f"collect_usage error: {out.get('error')}"
    # 主会话 input 1000 应被计入
    totals = out.get("totals") or {}
    assert totals.get("input", 0) >= 1000


def test_collect_usage_without_hud_timezone(fake_home, monkeypatch) -> None:
    """未设置 HUD_TIMEZONE：系统本地时区（不得报 CST NameError）。"""
    monkeypatch.delenv("HUD_TIMEZONE", raising=False)
    out = collectors.collect_usage(days=30)
    assert out.get("error") is None, f"collect_usage error: {out.get('error')}"
    totals = out.get("totals") or {}
    assert totals.get("input", 0) >= 1000
