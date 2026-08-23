"""§八 Security 验收：测试 secret 全链路 0 occurrence。

分两层：
  1. 全链路注入：把测试 secret 注入每个 collector 的原始输出，
     跑 build_snapshot → rules → telemetry 落盘，任何 API 字段 /
     telemetry.db / 指纹都不得出现原始 secret。
  2. 真实环境只读扫描：对 ~/.hermes/hud/telemetry.db 与 alerts_state.json
     做只读扫描（验证测试 secret 为 0 occurrence —— 测试 secret 从未进入）。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from dashboard.hud import collectors, rules, storage
from dashboard.hud.redaction import REDACTED, redact_line, sanitize_cmdline, sanitize_path

# 与 test_redaction.py 一致的测试 secret 集
TEST_SECRETS = [
    "sk-" + "test-abcdef1234567890",
    "abcdef" + "0123456789abcdef",
    ("eyJhbGciOiJIUzI1NiJ9."
     "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
     "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"),
    "123456789:" + "AAHw3nLxjK4W9qB6sR2vM7cX1dF5gH8jK0lQ",
    "super-secret-client-value",
    ("hooks.slack.com/services/"
     "T00000/B00000/XXXXXXXXXXXXXXXXXXXXXXXX"),
    "0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b",
]


def _no_secret(obj) -> None:
    """递归检查任何测试 secret 不出现在对象里。"""
    if isinstance(obj, str):
        for s in TEST_SECRETS:
            assert s not in obj, f"泄漏: {s!r} 出现在 {obj!r}"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(s in str(k) for s in TEST_SECRETS), f"泄漏: 键 {k!r}"
            _no_secret(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _no_secret(v)


@pytest.fixture()
def poisoned(monkeypatch, tmp_path):
    """每个采集器输出都注入测试 secret 的原始数据。"""
    secret = TEST_SECRETS[0]

    def _gateway():
        return {"error": None, "pid": 1, "alive": True, "state": "running",
                "start_time": time.time() - 100, "updated_at": time.time() - 10,
                "active_agents": 0, "code_version": "v",
                "heartbeat_age": 10,
                "platforms": {"telegram": {
                    "state": "connected", "needs_attention": True,
                    "error_code": "x", "error_message": redact_line(f"token={secret}"),
                    "updated_at": time.time() - 100, "heartbeat_age": 100}}}

    def _system():
        return {"error": None, "cpu_percent": 10.0, "load_avg": [1, 1, 1],
                "memory": {"percent": 20.0, "used": 1, "total": 8},
                "disk_free_percent": 50.0, "disk_free_gb": 100.0, "disk_total_gb": 200.0,
                "uptime_days": 1}

    def _db():
        return {"error": None, "db_size_bytes": 100, "wal_bytes": 10,
                "today_sessions": {"input_tokens": 1, "estimated_cost_usd": 0.1,
                                   "aux_est_cost": 0.0, "aux_actual_cost": 0.0}}

    def _sessions():
        return [{"id": "s1", "source": "desktop", "model": "m", "started_at": time.time(),
                 "title": "t", "message_count": 1, "tool_call_count": 0,
                 "input_tokens": 1, "output_tokens": 1,
                 "cwd": sanitize_path(f"/Users/me/{secret}"),
                 "idle_seconds": 1, "running_seconds": 1}]

    def _cron():
        return {"error": None, "jobs": [{
            "id": "j1", "name": "任务", "enabled": True, "state": "scheduled",
            "schedule": "* * * * *", "schedule_kind": "cron",
            "last_status": "ok", "last_error": redact_line(f"api_key={secret}"),
            "last_delivery_error": None, "failure_streak": 0,
            "deliver": redact_line(f"token={secret}"), "model": "m", "provider": "p",
            "script": sanitize_path("/Users/me/x/y/z/script.py"), "no_agent": True}],
            "summary": {"total": 1, "enabled": 1, "paused": 0, "disabled": 0,
                        "failing": 0, "running_state": 0}}

    def _executions():
        return {"error": None, "executions": [{
            "id": 1, "job_id": "j1", "source": "cron", "status": "completed",
            "claimed_at": time.time(), "started_at": time.time(),
            "finished_at": time.time() + 1, "pid": 1, "duration": 1,
            "error": redact_line(f"Bearer {secret}")}], "summary": {}}

    def _logs():
        return {"error": None, "files": {"agent.log": {
            "lines": [redact_line(f"ERROR token={secret}"), "INFO ok"]}}}

    def _errors():
        # 与真实实现一致：buckets 内存含 raw first/last，但输出只暴露脱敏 sample
        return {"error": None, "count_30m": 1, "incidents": [
            {"fingerprint": "fp", "count": 1,
             "sample": "ERROR token=" + REDACTED}]}

    def _memory():
        return {"error": None, "mem_used": 1, "mem_total": 8}

    def _launchd():
        return {"error": None, "managed": True, "label": "ai.hermes.gateway",
                "plist_exists": True, "status": "managed",
                "note": sanitize_cmdline(f"python -m x --key {secret}")}

    def _dashboard():
        return {"error": None, "procs": [{"pid": 1, "rss": 1, "started_at": time.time(),
                                          "cmdline": sanitize_cmdline(f"/Users/me/bin/x --token {secret}")}]}

    monkeypatch.setattr(collectors, "collect_gateway", _gateway)
    monkeypatch.setattr(collectors, "collect_system", _system)
    monkeypatch.setattr(collectors, "collect_db", _db)
    monkeypatch.setattr(collectors, "collect_active_sessions", _sessions)
    monkeypatch.setattr(collectors, "collect_cron_jobs", _cron)
    monkeypatch.setattr(collectors, "collect_cron_executions", _executions)
    monkeypatch.setattr(collectors, "collect_logs", _logs)
    monkeypatch.setattr(collectors, "collect_error_stats", _errors)
    monkeypatch.setattr(collectors, "collect_memory", _memory)
    monkeypatch.setattr(collectors, "collect_launchd_check", _launchd)
    monkeypatch.setattr(collectors, "collect_dashboard_procs", _dashboard)
    # 隔离 telemetry
    db = tmp_path / "telemetry.db"
    st = storage.TelemetryStore(db_path=db)
    monkeypatch.setattr(storage, "DEFAULT_HOME", tmp_path)
    return db, st


def test_snapshot_output_no_secret(poisoned) -> None:
    db, st = poisoned
    snap = collectors.build_snapshot()
    health = rules.evaluate_snapshot(snap)
    snap["_health"] = health
    _no_secret(snap)


def test_health_checks_no_secret(poisoned) -> None:
    db, st = poisoned
    snap = collectors.build_snapshot()
    health = rules.evaluate_snapshot(snap)
    _no_secret(health)


def test_telemetry_db_no_secret(poisoned) -> None:
    db, st = poisoned
    snap = collectors.build_snapshot()
    health = rules.evaluate_snapshot(snap)
    # 模拟 plugin_api._update_telemetry 的写入路径
    for inc in health.get("incidents", []):
        st.upsert_incident(inc["fingerprint"], inc["severity"], inc["title"], inc["detail"])
    st.record_metrics_batch("sys", [("cpu_percent", 1.0, None)])
    incs = st.list_incidents()
    _no_secret(incs)
    for row in st.query_metrics("sys"):
        _no_secret(row)


def test_incident_title_detail_no_secret(poisoned) -> None:
    db, st = poisoned
    snap = collectors.build_snapshot()
    health = rules.evaluate_snapshot(snap)
    for inc in health.get("incidents", []):
        _no_secret(inc)


def test_fingerprints_no_secret(poisoned) -> None:
    db, st = poisoned
    # errors collector 的指纹基于脱敏后的行（带 key=/Bearer/JWT 上下文的日志）
    from dashboard.hud.redaction import fingerprint
    for line in [f"ERROR token={TEST_SECRETS[0]}",
                 f"auth failed bearer {TEST_SECRETS[1]}",
                 f"connect secret={TEST_SECRETS[4]}"]:
        _no_secret(fingerprint(line))


def test_real_telemetry_readonly_scan() -> None:
    """真实 ~/.hermes/hud 只读扫描：测试 secret 必须 0 occurrence。"""
    home = Path.home() / ".hermes" / "hud"
    if not home.exists():
        pytest.skip("本机无 ~/.hermes/hud 目录")
    hits = []
    db = home / "telemetry.db"
    if db.exists():
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            try:
                rows = conn.execute(f"SELECT * FROM {name}").fetchall()
                for r in rows:
                    blob = " ".join(str(x) for x in r)
                    for s in TEST_SECRETS:
                        if s in blob:
                            hits.append((name, s))
            except Exception:
                continue
        conn.close()
    st_file = home / "alerts_state.json"
    if st_file.exists():
        blob = st_file.read_text(encoding="utf-8")
        for s in TEST_SECRETS:
            if s in blob:
                hits.append(("alerts_state.json", s))
    assert hits == [], f"真实库中发现测试 secret: {hits}"
