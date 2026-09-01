"""v1.1.2 Compatibility Patch — F-1 / C-1 回归测试。

F-1（任务书 D 节）：Hermes v0.21 string model_snapshot 不得静默丢弃 cron/task。
  - 27 tasks 输入、其中 7 个 model_snapshot 为 str → collector 输出 27（禁止再 20/27）
  - dict / string / NULL / missing / unexpected 五类输入全部安全
  - task id / status / schedule / failure_streak 保留；model 正确解析或 unknown

C-1（任务书 G 节）：header「今日估算」必须复用 canonical Cost Truth。
  - estimated primary + estimated aux + unpriced aux + unknown pricing + actual absent
  - canonical estimated = X；header estimated = X；unpriced = Y 不得进 X
  - header estimated != X + Y（estimated label never absorbs unpriced）
  - header input/output/cache token == canonical summary 对应字段（任务书第 7 节）
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.hud import collectors  # noqa: E402
from dashboard.hud import cost  # noqa: E402

NOW = time.time()


# ---------------------------------------------------------------------------
# F-1 fixtures / helpers
# ---------------------------------------------------------------------------

def _job(id_: str, model_snapshot: Any = "__sentinel__", model: Any = None,
         **extra: Any):
    """构造单个 jobs.json 任务；model_snapshot 缺省用哨兵（= missing 场景）。"""
    job = {
        "id": id_,
        "name": f"task {id_}",
        "enabled": True,
        "state": "idle",
        "schedule": {"kind": "cron", "expr": "0 9 * * *"},
        "failure_streak": 2,
        "last_status": "ok",
    }
    job.update(extra)
    if model is not None:
        job["model"] = model
    if model_snapshot != "__sentinel__":
        job["model_snapshot"] = model_snapshot
    return job


def _mk_jobs(n: int, string_ids: set[str]) -> list[dict]:
    """n 个任务，其中 string_ids 里的 id 用 v0.21 风格 str model_snapshot。"""
    jobs = []
    for i in range(n):
        j = _job(f"job-{i:03d}")
        if j["id"] in string_ids:
            j["model_snapshot"] = "deepseek-v4-flash"  # v0.21 string 写法
        jobs.append(j)
    return jobs


@pytest.fixture
def cron_home(tmp_path, monkeypatch):
    """HERMES_HOME → 临时目录，可写 cron/jobs.json。"""
    home = tmp_path / "home"
    (home / "cron").mkdir(parents=True)
    monkeypatch.setattr(collectors, "HERMES_HOME", home)
    return home


def _write_jobs(home: Path, jobs: list[dict]) -> None:
    (home / "cron" / "jobs.json").write_text(
        json.dumps({"jobs": jobs}), encoding="utf-8")


# ---------------------------------------------------------------------------
# F-1 回归：27 任务 / 7 个 string model_snapshot → 27 输出
# ---------------------------------------------------------------------------

def test_27_tasks_with_7_string_snapshot_no_drop(cron_home) -> None:
    """防回归核心：7 个 string model_snapshot 的任务不得被丢弃（禁止 20/27）。"""
    string_ids = {f"job-{i:03d}" for i in (1, 4, 7, 10, 13, 16, 19)}
    _write_jobs(cron_home, _mk_jobs(27, string_ids))
    out = collectors.collect_cron_jobs()
    assert "error" not in out, out.get("error")
    assert out["summary"]["total"] == 27, f"任务被丢弃: {out['summary']['total']}/27"
    assert len(out["jobs"]) == 27
    got_ids = {j["id"] for j in out["jobs"]}
    assert got_ids == string_ids | {f"job-{i:03d}" for i in range(27)}
    # 7 个 string snapshot 任务仍在，且 model 正确解析
    str_jobs = {j["id"]: j for j in out["jobs"] if j["id"] in string_ids}
    assert len(str_jobs) == 7
    for j in str_jobs.values():
        assert j["model"] == "deepseek-v4-flash"
    assert out["summary"]["parse_warnings"] == 0


def test_27_tasks_enabled_summary(cron_home) -> None:
    """enabled 汇总不被 string snapshot 影响。"""
    jobs = _mk_jobs(27, {f"job-{i:03d}" for i in range(0, 27, 3)})
    for i, j in enumerate(jobs):
        j["enabled"] = (i % 4 != 0)  # 7 个 disabled（i=0,4,8,12,16,20,24）→ 20 enabled
    _write_jobs(cron_home, jobs)
    out = collectors.collect_cron_jobs()
    assert out["summary"]["total"] == 27
    assert out["summary"]["enabled"] == 20


# ---------------------------------------------------------------------------
# F-1：model_snapshot 五类输入（任务书第 5 节 A–E）
# ---------------------------------------------------------------------------

def test_model_snapshot_dict(cron_home) -> None:
    """A. dict{"model": "provider/model"} → 正确解析。"""
    _write_jobs(cron_home, [_job("a", model_snapshot={"model": "openai/gpt-4o"})])
    jobs = collectors.collect_cron_jobs()["jobs"]
    assert jobs[0]["model"] == "openai/gpt-4o"
    assert jobs[0]["provider"] is None


def test_model_snapshot_string(cron_home) -> None:
    """B. "provider/model"（v0.21）→ 原样解析。"""
    _write_jobs(cron_home, [_job("b", model_snapshot="deepseek-v4-flash")])
    jobs = collectors.collect_cron_jobs()["jobs"]
    assert jobs[0]["model"] == "deepseek-v4-flash"


def test_model_snapshot_null(cron_home) -> None:
    """C. None → model None（unknown），任务保留。"""
    _write_jobs(cron_home, [_job("c", model_snapshot=None)])
    jobs = collectors.collect_cron_jobs()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["model"] is None


def test_model_snapshot_missing(cron_home) -> None:
    """D. 字段缺失 → model None，任务保留。"""
    _write_jobs(cron_home, [_job("d")])
    jobs = collectors.collect_cron_jobs()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["model"] is None


@pytest.mark.parametrize("bad", [123, [], [1, 2], "  "])
def test_model_snapshot_unexpected_type(cron_home, bad) -> None:
    """E. 意外类型（非 dict/str）→ 安全回退 None，任务保留且不抛异常。"""
    _write_jobs(cron_home, [_job("e", model_snapshot=bad)])
    jobs = collectors.collect_cron_jobs()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["model"] is None
    assert jobs[0]["id"] == "e"


def test_job_fields_preserved(cron_home) -> None:
    """string snapshot 下 id/status/schedule/failure_streak 全部保留。"""
    j = _job("keep-1", model_snapshot="deepseek-v4-flash",
             state="firing", failure_streak=5,
             schedule={"kind": "interval", "expr": "every 30m"})
    _write_jobs(cron_home, [j])
    out = collectors.collect_cron_jobs()["jobs"][0]
    assert out["id"] == "keep-1"
    assert out["state"] == "firing"
    assert out["schedule"] == "every 30m"
    assert out["schedule_kind"] == "interval"
    assert out["failure_streak"] == 5
    assert out["enabled"] is True


def test_top_level_model_wins(cron_home) -> None:
    """顶层 model 优先于 model_snapshot。"""
    _write_jobs(cron_home, [
        _job("t1", model="top-model", model_snapshot={"model": "snap-model"})])
    jobs = collectors.collect_cron_jobs()["jobs"]
    assert jobs[0]["model"] == "top-model"


# ---------------------------------------------------------------------------
# C-1 fixtures / helpers
# ---------------------------------------------------------------------------

def _mk_state_db(path: Path) -> None:
    """最小 state.db：sessions + messages + session_model_usage（真实 schema 列）。"""
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
        " last_activity_description TEXT, last_activity_provenance TEXT)")
    cur.execute(
        "CREATE TABLE messages ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
        " content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,"
        " timestamp REAL, token_count INTEGER, finish_reason TEXT,"
        " platform_message_id TEXT, active INTEGER)")
    cur.execute(
        "CREATE TABLE session_model_usage ("
        " session_id TEXT, model TEXT, billing_provider TEXT, billing_base_url TEXT,"
        " billing_mode TEXT, task TEXT, api_call_count INTEGER, input_tokens INTEGER,"
        " output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,"
        " reasoning_tokens INTEGER, estimated_cost_usd REAL, actual_cost_usd REAL,"
        " cost_status TEXT, cost_source TEXT, first_seen REAL, last_seen REAL)")
    conn.commit()
    conn.close()


def _usage_row(sid, model, task, inp, out, cache, cost, status, source,
               actual=None):
    return (sid, model, "custom", None, None, task, 1, inp, out, cache, 0, 0,
            cost, actual, status, source, NOW, NOW)


def _seed_cost_fixture(db: Path) -> dict:
    """G 节 fixture：estimated primary/aux + unpriced aux + unknown pricing + actual absent。

    结构近似真实场景（canonical≈0.0875 / unpriced aux≈0.0348），但不硬编码生产值：
    期望值由 fixture 自身的成本字段计算得出。
    """
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    # sessions 表：一个今日主会话（operational count 用）
    cur.execute(
        "INSERT INTO sessions (id, source, model, title, started_at, ended_at,"
        " message_count, tool_call_count, input_tokens, output_tokens,"
        " cache_read_tokens, cache_write_tokens, reasoning_tokens,"
        " estimated_cost_usd, actual_cost_usd, cost_status, billing_provider,"
        " api_call_count, last_activity_at)"
        " VALUES ('s-main', 'desktop', 'deepseek-v4-flash', 'main', ?, ?, 3, 2,"
        " 1000, 100, 500, 50, 20, 0.05, 0.04, 'estimated', 'deepseek', 1, ?)",
        (NOW, NOW, NOW))
    cur.execute("INSERT INTO messages (session_id, role, content, timestamp, active)"
                " VALUES ('s-main', 'user', 'hi', ?, 1)", (NOW,))
    rows = [
        # estimated primary（主会话，pricing known）
        _usage_row("s-main", "deepseek-v4-flash", "", 1000, 100, 500, 0.05,
                   "estimated", "official_docs_snapshot", 0.04),
        # estimated aux（辅助调用，task != ''，pricing known）
        _usage_row("s-aux1", "gpt-4o", "scan", 400, 40, 200, 0.0375,
                   "estimated", "official_docs_snapshot", 0.03),
        # unpriced aux（task != ''，cost_status NULL → 不得计入 estimated）
        _usage_row("s-aux2", "deepseek-v4-flash", "watchdog", 300, 30, 100, 0.0348,
                   None, None),
        # unknown pricing（cost_status=unknown + source=none → 不得计入）
        _usage_row("s-aux3", "claude-3-5", "digest", 200, 20, 0, 0.01,
                   "unknown", "none"),
        # actual absent：所有行 actual_cost_usd 均为 NULL（除 s-main 外）
    ]
    # s-aux1/2/3 的 actual 置 NULL（上面默认 actual=None → NULL）
    cur.executemany(
        "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows)
    conn.commit()
    conn.close()
    return {"estimated": 0.05 + 0.0375, "unpriced": 0.0348 + 0.01}


@pytest.fixture
def cost_home(tmp_path, monkeypatch):
    """HERMES_HOME + HUD_STATE_DB → 同一临时 state.db。"""
    home = tmp_path / "home"
    home.mkdir()
    db = home / "state.db"
    _mk_state_db(db)
    monkeypatch.setattr(collectors, "HERMES_HOME", home)
    monkeypatch.setenv("HUD_STATE_DB", str(db))
    return home


# ---------------------------------------------------------------------------
# C-1 回归：header estimated == canonical；unpriced 不吸收
# ---------------------------------------------------------------------------

def test_header_estimated_equals_canonical(cost_home) -> None:
    """Header「今日估算」== canonical Cost Truth estimated（同源同值）。"""
    exp = _seed_cost_fixture(cost_home / "state.db")
    canonical = cost.compute_summary(cost_home, "today")
    assert canonical["estimated_cost_usd"] == pytest.approx(exp["estimated"])
    header = collectors.collect_db()["today_sessions"]
    assert header["estimated_cost_usd"] == pytest.approx(canonical["estimated_cost_usd"])
    assert header["estimated_cost_usd"] == pytest.approx(exp["estimated"])


def test_header_estimated_excludes_unpriced(cost_home) -> None:
    """unpriced aux + unknown pricing 不得进入 estimated（estimated != X + Y）。"""
    exp = _seed_cost_fixture(cost_home / "state.db")
    header = collectors.collect_db()["today_sessions"]
    est = header["estimated_cost_usd"]
    assert est == pytest.approx(exp["estimated"])
    assert est != pytest.approx(exp["estimated"] + exp["unpriced"])
    assert est < exp["estimated"] + exp["unpriced"]
    # pricing_unknown_rows 单独暴露（不并进估算）
    assert header["pricing_unknown_rows"] == 2


def test_header_tokens_from_canonical(cost_home) -> None:
    """任务书第 7 节：header token 与费用同源（== canonical summary 字段）。"""
    _seed_cost_fixture(cost_home / "state.db")
    canonical = cost.compute_summary(cost_home, "today")
    header = collectors.collect_db()["today_sessions"]
    assert header["input_tokens"] == canonical["input_tokens"]
    assert header["output_tokens"] == canonical["output_tokens"]
    assert header["cache_read_tokens"] == canonical["cache_read_tokens"]
    # canonical 期望值（已知 pricing 行 token 全计入，与费用口径一致）
    assert canonical["input_tokens"] == 1000 + 400 + 300 + 200
    assert canonical["output_tokens"] == 100 + 40 + 30 + 20


def test_header_session_count_is_operational(cost_home) -> None:
    """session count 属 operational metric，仍来自 sessions 表（今日会话数）。"""
    _seed_cost_fixture(cost_home / "state.db")
    header = collectors.collect_db()["today_sessions"]
    assert header["count"] == 1  # 仅 sessions 表里 1 条今日主会话
