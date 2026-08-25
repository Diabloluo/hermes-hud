"""Agent Timeline v1 测试。

覆盖：normalization / deterministic id / duplicate ingestion / ordering /
pagination / filters / malformed source / missing optional fields /
redaction / retention / indexes / 10k synthetic / API schema / empty state /
collector idempotency（×10）。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

from hud import storage, timeline  # noqa: E402


@pytest.fixture
def store(tmp_path) -> storage.TelemetryStore:
    return storage.TelemetryStore(db_path=tmp_path / "telemetry.db")


@pytest.fixture
def fake_state(tmp_path) -> Path:
    """构造临时 state.db（sessions/messages/session_model_usage）。"""
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT, source TEXT, model TEXT, started_at REAL,"
                " ended_at REAL, title TEXT)")
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
                " content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,"
                " timestamp REAL, finish_reason TEXT)")
    con.execute("CREATE TABLE session_model_usage (session_id TEXT, model TEXT,"
                " input_tokens INT, output_tokens INT, estimated_cost_usd REAL)")
    con.execute("INSERT INTO sessions VALUES ('s1','chat','gpt-4o',1756000000,1756000100,'T1')")
    con.execute("INSERT INTO sessions VALUES ('s2','chat','gpt-4o',1756001000,NULL,'T2')")
    con.execute("INSERT INTO messages (session_id, role, tool_name, tool_call_id, timestamp,"
                " finish_reason) VALUES ('s1','assistant','git status','c1',1756000050,'end_turn')")
    con.execute("INSERT INTO messages (session_id, role, tool_name, tool_call_id, timestamp,"
                " finish_reason) VALUES ('s1','assistant','git push','c2',1756000060,'error')")
    con.execute("INSERT INTO session_model_usage VALUES ('s1','gpt-4o',1000,500,0.01)")
    con.commit()
    con.close()
    return db


# ---------- 1. event normalization ----------

def test_normalize_event_unknown_fields_null() -> None:
    ev = timeline.normalize_event({"timestamp": 1756000000, "event_type": "session.started",
                                   "session_id": "s1", "summary": "Session started"})
    assert ev["agent_id"] is None          # 无多 agent 数据 → null
    assert ev["skill"] is None             # 未提供 → null（禁止猜）
    assert ev["tool"] is None
    assert ev["tokens"] is None
    assert ev["cost_usd"] is None
    assert ev["duration_ms"] is None
    assert ev["correlation_id"] is None


def test_normalize_event_rejects_invalid_type() -> None:
    ev = timeline.normalize_event({"timestamp": 1, "event_type": "trace.span",
                                   "summary": "x"})
    assert ev["event_type"] is None  # 不在 v1 白名单 → null（不生成）


def test_normalize_event_bad_timestamp() -> None:
    ev = timeline.normalize_event({"timestamp": "not-a-number", "event_type": "session.started",
                                   "summary": "x"})
    assert ev["timestamp"] is None
    assert ev["event_id"] is None  # 无可靠时间 → 无 id（不可靠不写入）


# ---------- 2. deterministic event id ----------

def test_deterministic_event_id_stable() -> None:
    a = timeline.deterministic_event_id("hermes", "tool:c1:tool.completed",
                                        "tool.completed", 1756000050)
    b = timeline.deterministic_event_id("hermes", "tool:c1:tool.completed",
                                        "tool.completed", 1756000050)
    c = timeline.deterministic_event_id("hermes", "tool:c1:tool.completed",
                                        "tool.completed", 1756000051)
    assert a == b and a != c and len(a) == 24


# ---------- 3. duplicate ingestion ----------

def test_duplicate_ingestion_idempotent(store) -> None:
    ev = timeline.normalize_event({"timestamp": 1756000000, "event_type": "session.started",
                                   "session_id": "s1", "summary": "Session started",
                                   "source_record_id": "session:s1:started"})
    assert store.record_timeline_event(ev) is True
    for _ in range(10):
        assert store.record_timeline_event(ev) is False  # 重复采集不产生重复事件
    assert store.timeline_stats()["total"] == 1


def test_collector_run_x10_event_count_unchanged(tmp_path, fake_state) -> None:
    """工单 Phase 5：collector run ×10 → event count unchanged。"""
    store = storage.TelemetryStore(db_path=tmp_path / "telemetry.db")
    for _ in range(10):
        res = timeline.collect_timeline(tmp_path, store)
    # 10 次全量/增量采集后事件数稳定（幂等）
    assert store.timeline_stats()["total"] > 0
    total = store.timeline_stats()["total"]
    for _ in range(5):
        timeline.collect_timeline(tmp_path, store)
    assert store.timeline_stats()["total"] == total


# ---------- 4. ordering & 5. pagination ----------

def test_timestamp_ordering_and_pagination(store) -> None:
    for i in range(25):
        store.record_timeline_event(timeline.normalize_event({
            "timestamp": 1756000000 + i, "event_type": "session.started",
            "session_id": f"s{i}", "summary": f"E{i}",
            "source_record_id": f"e{i}:started"}))
    rows = store.query_timeline(limit=10)
    assert len(rows) == 10
    assert rows[0]["timestamp"] == 1756000024  # 倒序
    assert rows[0]["session_id"] == "s24"
    rows2 = store.query_timeline(limit=10, before=rows[-1]["timestamp"])
    assert rows2[0]["timestamp"] == 1756000014  # 分页衔接
    assert len(rows2) == 10


# ---------- 6. filters ----------

def test_filter_by_session_skill_status(store) -> None:
    evs = [
        {"timestamp": 1, "event_type": "skill.completed", "skill": "project-guard",
         "status": "completed", "session_id": "s1", "summary": "Skill project-guard completed",
         "source_record_id": "j1"},
        {"timestamp": 2, "event_type": "tool.failed", "tool": "git push", "status": "failed",
         "session_id": "s1", "summary": "Tool git push failed", "source_record_id": "t1"},
        {"timestamp": 3, "event_type": "skill.completed", "skill": "job-ledger",
         "status": "completed", "session_id": "s2", "summary": "Skill job-ledger completed",
         "source_record_id": "j2"},
    ]
    for e in evs:
        store.record_timeline_event(timeline.normalize_event(e))
    assert len(store.query_timeline(session_id="s1")) == 2
    assert len(store.query_timeline(skill="project-guard")) == 1
    assert len(store.query_timeline(status="failed")) == 1
    assert len(store.query_timeline(event_type="skill.completed")) == 2


# ---------- 7/8. malformed source & missing optional ----------

def test_malformed_source_records(store) -> None:
    bad = [
        {"timestamp": "nope", "event_type": "session.started", "summary": "x"},
        {"timestamp": None, "event_type": None, "summary": "y"},
        {},
    ]
    for b in bad:
        ev = timeline.normalize_event(b)
        if ev.get("event_id") and ev.get("timestamp"):
            store.record_timeline_event(ev)  # 不抛异常
    assert store.timeline_stats()["total"] == 0  # 不可靠记录不写入


# ---------- 9. redaction ----------

def test_summary_redaction() -> None:
    ev = timeline.normalize_event({
        "timestamp": 1, "event_type": "tool.called", "tool": "shell",
        "summary": "Tool shell called with token=sk-live-abcdefghijklmnopqrstuvwxyz123456",
        "source_record_id": "r1"})
    assert "sk-live-abcdefghijklmnopqrstuvwxyz123456" not in ev["summary"]
    assert "REDACTED" in ev["summary"] or "***" in ev["summary"] or "sk-live" not in ev["summary"]


# ---------- 10. retention ----------

def test_retention_prunes_timeline(store) -> None:
    old = time.time() - (storage.TIMELINE_RETENTION_DAYS + 1) * 86400
    store.record_timeline_event(timeline.normalize_event({
        "timestamp": int(old), "event_type": "session.started", "summary": "old",
        "source_record_id": "old1"}))
    store.record_timeline_event(timeline.normalize_event({
        "timestamp": int(time.time()), "event_type": "session.started", "summary": "new",
        "source_record_id": "new1"}))
    store.prune()
    assert store.timeline_stats()["total"] == 1  # 旧事件被清理


# ---------- 11. DB indexes ----------

def test_timeline_indexes(store) -> None:
    store.record_timeline_event(timeline.normalize_event({
        "timestamp": 1, "event_type": "session.started", "summary": "x",
        "source_record_id": "r1"}))
    with store._connect() as conn:
        idx = [r[1] for r in conn.execute("PRAGMA index_list(timeline_events)")]
    for want in ("idx_timeline_ts", "idx_timeline_session", "idx_timeline_type",
                 "idx_timeline_status", "idx_timeline_skill"):
        assert want in idx


# ---------- 12. 10k synthetic events ----------

def test_10k_synthetic_events(store) -> None:
    t0 = time.time()
    for i in range(10_000):
        store.record_timeline_event(timeline.normalize_event({
            "timestamp": 1756000000 + i, "event_type": "tool.called",
            "tool": f"tool-{i % 50}", "session_id": f"s{i % 20}",
            "summary": f"Tool tool-{i % 50} called", "source_record_id": f"t{i}"}))
    ingest_s = time.time() - t0
    t0 = time.time()
    rows = store.query_timeline(limit=100)
    q1 = time.time() - t0
    t0 = time.time()
    store.query_timeline(limit=100, session_id="s3")
    q2 = time.time() - t0
    t0 = time.time()
    store.query_timeline(limit=100, status="failed")
    q3 = time.time() - t0
    assert len(rows) == 100
    assert store.timeline_stats()["total"] == 10_000
    # 有界查询延迟（不要求极端 benchmark，但 indexed 查询必须可接受）
    assert q1 < 0.5 and q2 < 0.5 and q3 < 0.5, (q1, q2, q3)
    print(f"ingest={ingest_s:.2f}s q_all={q1:.3f}s q_session={q2:.3f}s q_status={q3:.3f}s")


# ---------- 13. API schema（查询响应结构） ----------

def test_api_response_schema(store) -> None:
    store.record_timeline_event(timeline.normalize_event({
        "timestamp": 1756000000, "event_type": "session.started", "session_id": "s1",
        "summary": "Session started", "source_record_id": "s1:started"}))
    rows = store.query_timeline(limit=100)
    ev = rows[0]
    for field in ("event_id", "timestamp", "event_type", "status", "session_id", "skill",
                  "tool", "duration_ms", "tokens", "cost_usd", "incident_id", "summary",
                  "source", "correlation_id"):
        assert field in ev


# ---------- 14. empty state ----------

def test_empty_state(store, tmp_path) -> None:
    """fresh install：无 state.db、无 job-ledger → 采集安全返回空，不 500。"""
    res = timeline.collect_timeline(tmp_path, store)
    assert res["written"] == 0
    assert store.timeline_stats()["total"] == 0
    assert store.query_timeline() == []


# ---------- 15. collector 真实源（fake state.db） ----------

def test_collectors_from_state_db(tmp_path, fake_state) -> None:
    store = storage.TelemetryStore(db_path=tmp_path / "telemetry.db")
    ses = timeline.collect_session_events(tmp_path, 0)
    tools = timeline.collect_tool_events(tmp_path, 0)
    assert any(e["event_type"] == "session.started" for e in ses)
    assert any(e["event_type"] == "session.completed" for e in ses)
    assert any(e["event_type"] == "tool.called" and e["tool"] == "git status" for e in tools)
    assert any(e["event_type"] == "tool.failed" and e["tool"] == "git push" for e in tools)
    # session.completed 带 duration/tokens/cost（可靠数据）
    comp = next(e for e in ses if e["event_type"] == "session.completed")
    assert comp["duration_ms"] == 100
    assert comp["tokens"] == 1500
    assert comp["cost_usd"] == 0.01
    # A-truth：session 级 token/cost 不复制到 tool 事件
    assert all(e["tokens"] is None and e["cost_usd"] is None for e in tools)


# ---------- B. stable pagination：同 timestamp 100 条 ----------

def test_same_timestamp_pagination_no_dup_no_miss(store) -> None:
    """100 条同 timestamp 事件，cursor 分页全部取到：unique=100, missing=0, duplicate=0。"""
    ts = 1756000000
    ids = []
    for i in range(100):
        ev = timeline.normalize_event({
            "timestamp": ts, "event_type": "tool.called", "tool": f"t{i % 10}",
            "summary": f"E{i}", "source_record_id": f"same-ts-{i}"})
        store.record_timeline_event(ev)
        ids.append(ev["event_id"])
    assert len(set(ids)) == 100  # 全部唯一
    seen: list[str] = []
    cursor_ts, cursor_id = None, None
    while True:
        rows = store.query_timeline(limit=10, before=cursor_ts, before_id=cursor_id)
        if not rows:
            break
        seen.extend(r["event_id"] for r in rows)
        last = rows[-1]
        cursor_ts, cursor_id = last["timestamp"], last["event_id"]
        if len(rows) < 10:
            break
    assert len(seen) == 100, f"漏 {100 - len(seen)}"
    assert len(set(seen)) == 100, "重复"
    assert set(seen) == set(ids), "缺事件"
    # 断言可读：unique=100 missing=0 duplicate=0
    assert len(set(seen)) == 100 and 100 - len(seen) == 0 and 100 - len(set(seen)) == 0


# ---------- C. upgrade migration ----------

def test_upgrade_migration_preserves_old_rows(tmp_path) -> None:
    """旧版 telemetry.db（无 timeline_events）→ 新 storage 启动后：旧行不变、新表+索引创建。"""
    db = tmp_path / "telemetry.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE metrics (ts INTEGER, kind TEXT, name TEXT, value REAL, meta TEXT)")
    con.execute("CREATE TABLE incidents (id INTEGER PRIMARY KEY, fingerprint TEXT,"
                " severity TEXT, title TEXT, detail TEXT, first_seen INTEGER,"
                " last_seen INTEGER, count INTEGER, status TEXT)")
    con.execute("INSERT INTO metrics VALUES (1, 'sys', 'cpu', 0.5, NULL)")
    con.execute("INSERT INTO incidents VALUES (1, 'fp1', 'warn', 'old', NULL, 100, 200, 1, 'active')")
    con.commit()
    con.close()
    before_m = sqlite3.connect(db).execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    before_i = sqlite3.connect(db).execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    store = storage.TelemetryStore(db_path=db)  # 启动即迁移
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == before_m
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == before_i
    with store._connect() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        assert "timeline_events" in tables
        idx = [r[1] for r in conn.execute("PRAGMA index_list(timeline_events)")]
        assert "idx_timeline_ts" in idx
    # 无破坏性迁移（旧数据完好 + 可写入新表）
    assert store.record_timeline_event(timeline.normalize_event({
        "timestamp": 1, "event_type": "session.started", "summary": "x",
        "source_record_id": "r1"}))


# ---------- F. incident resolved truth（显式 resolved_at 才生成） ----------

def test_incident_resolved_requires_explicit_timestamp(tmp_path) -> None:
    store = storage.TelemetryStore(db_path=tmp_path / "telemetry.db")
    # 常规表（无 resolved_at 列）：recovered 状态也不生成 resolved（不猜 last_seen）
    store.upsert_incident("fp-rec", "warn", "R", "d")
    store.recover_incident("fp-rec", now=5000)
    evs = timeline.collect_incident_events(store, 0)
    assert any(e["event_type"] == "incident.opened" for e in evs)
    assert not any(e["event_type"] == "incident.resolved" for e in evs)  # last_seen 不猜


def test_incident_resolved_from_explicit_resolved_at(tmp_path) -> None:
    """带 resolved_at 列的表：resolved 事件用显式时间生成（未来 schema/第三方源）。"""
    store = storage.TelemetryStore(db_path=tmp_path / "telemetry.db")
    with store._connect() as conn:
        conn.execute("ALTER TABLE incidents ADD COLUMN resolved_at INTEGER")
        conn.execute("INSERT INTO incidents (fingerprint, severity, title, detail,"
                     " first_seen, last_seen, status, resolved_at)"
                     " VALUES ('fp-x', 'warn', 'X', NULL, 100, 200, 'recovered', 300)")
    evs = timeline.collect_incident_events(store, 0)
    opened = next(e for e in evs if e["event_type"] == "incident.opened")
    resolved = next(e for e in evs if e["event_type"] == "incident.resolved")
    assert opened["timestamp"] == 100
    assert resolved["timestamp"] == 300  # 显式 resolved_at，非 last_seen(200)


# ---------- F. skill identity truth ----------

def test_skill_events_require_explicit_skill_field(tmp_path) -> None:
    """job-ledger 无 skill 字段 → 不生成 skill.*（project/task 不是 skill 身份）。"""
    home = tmp_path
    ledger = home / "job-ledger"
    ledger.mkdir(parents=True)
    (ledger / "jobs.jsonl").write_text(
        "{\"job_id\": \"j1\", \"project\": \"hermes-hud\", \"task\": \"T\","
        " \"started_at\": \"2026-08-25T10:00:00+08:00\", \"event\": \"finished\"}\n",
        encoding="utf-8")
    evs = timeline.collect_skill_events(home, 0)
    assert evs == []  # 无 skill 字段 → 不生成

    # 带 skill 字段 → 生成（来源标记 job-ledger，不伪装 Hermes core）
    (ledger / "jobs.jsonl").write_text(
        "{\"job_id\": \"j2\", \"skill\": \"project-guard\", \"task\": \"G\","
        " \"started_at\": \"2026-08-25T10:00:00+08:00\", \"event\": \"finished\"}\n",
        encoding="utf-8")
    evs2 = timeline.collect_skill_events(home, 0)
    assert len(evs2) == 1
    assert evs2[0]["skill"] == "project-guard"
    assert evs2[0]["source"] == "job-ledger"
    assert evs2[0]["tokens"] is None and evs2[0]["cost_usd"] is None
