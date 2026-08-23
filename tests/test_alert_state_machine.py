"""P0-3 告警推送恢复状态机测试。

覆盖：新事故推送、推送失败不记录、恢复成功才 recovered、
所有渠道失败 → pending_recovery 下轮重试、pending_recovery 期间事故回归。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

# 加载 scripts/hud_alert.py（不执行 main）
_ALERT = Path(__file__).resolve().parents[1] / "scripts" / "hud_alert.py"
_spec = importlib.util.spec_from_file_location("hud_alert", _ALERT)
ha = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(ha)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """隔离的 telemetry.db + state 文件 + 无真实网络。"""
    monkeypatch.setattr(ha, "TELEMETRY_DB", tmp_path / "telemetry.db")
    monkeypatch.setattr(ha, "STATE_FILE", tmp_path / "alerts_state.json")

    def _seed_incidents(rows: list[tuple]) -> None:
        conn = sqlite3.connect(tmp_path / "telemetry.db")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL,
            detail TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
            observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1
        );
        """)
        for fp, sev, title, status in rows:
            conn.execute(
                "INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, count, status, observations, state_changes)"
                " VALUES(?,?,?,?,?,?,1,?,1,1)",
                (fp, sev, title, "detail", 1000, 1000, status),
            )
        conn.commit()
        conn.close()
    monkeypatch.setattr(ha, "_seed", _seed_incidents)  # 供测试用
    return tmp_path


def _read_state(tmp_path) -> dict:
    p = tmp_path / "alerts_state.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def test_new_incident_pushes_and_records(tmp_path, monkeypatch) -> None:
    """新事故 → 推送成功 → 状态记录 active。"""
    monkeypatch.setattr(ha, "TELEMETRY_DB", tmp_path / "telemetry.db")
    monkeypatch.setattr(ha, "STATE_FILE", tmp_path / "alerts_state.json")
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    conn.executescript("""CREATE TABLE incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
        severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT,
        first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
        observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1);""")
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen) VALUES('fp:new','warning','新事故','d',1,1)")
    conn.commit()
    conn.close()

    pushed: list[tuple] = []
    monkeypatch.setattr(ha, "push_all", lambda text: (True, False) if pushed.append(("tg", text)) is None else (True, False))

    ha.run(dry_run=False)
    state = _read_state(tmp_path)
    assert "fp:new" in state
    assert state["fp:new"]["status"] == "active"


def test_recovery_success_marks_recovered(tmp_path, monkeypatch) -> None:
    """事故消失 + 恢复推送成功 → recovered。"""
    monkeypatch.setattr(ha, "TELEMETRY_DB", tmp_path / "telemetry.db")
    monkeypatch.setattr(ha, "STATE_FILE", tmp_path / "alerts_state.json")
    (tmp_path / "alerts_state.json").write_text(json.dumps({
        "fp:gone": {"severity": "warning", "title": "旧事故", "detail": "d",
                    "count": 5, "last_push": 1000, "status": "active"},
    }))
    # telemetry 里没有任何活跃事故（fp:gone 已恢复但记录还在）
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    conn.executescript("""CREATE TABLE incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
        severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT,
        first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
        observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1);""")
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, status) VALUES('fp:gone','warning','旧事故','d',1,2000,'recovered')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(ha, "push_all", lambda text: (True, False))  # TG 成功

    ha.run(dry_run=False)
    state = _read_state(tmp_path)
    assert state["fp:gone"]["status"] == "recovered"


def test_recovery_failure_stays_pending(tmp_path, monkeypatch) -> None:
    """恢复推送全部渠道失败 → pending_recovery，绝不标 recovered。"""
    monkeypatch.setattr(ha, "TELEMETRY_DB", tmp_path / "telemetry.db")
    monkeypatch.setattr(ha, "STATE_FILE", tmp_path / "alerts_state.json")
    (tmp_path / "alerts_state.json").write_text(json.dumps({
        "fp:gone": {"severity": "warning", "title": "旧事故", "detail": "d",
                    "count": 5, "last_push": 1000, "status": "active"},
    }))
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    conn.executescript("""CREATE TABLE incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
        severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT,
        first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
        observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1);""")
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, status) VALUES('fp:gone','warning','旧事故','d',1,2000,'recovered')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(ha, "push_all", lambda text: (False, False))  # 全部失败

    ha.run(dry_run=False)
    state = _read_state(tmp_path)
    assert state["fp:gone"]["status"] == "pending_recovery", state
    assert state["fp:gone"].get("last_attempt") is not None


def test_pending_recovery_retried_next_round(tmp_path, monkeypatch) -> None:
    """pending_recovery 下一轮重试；60 秒限流内跳过。"""
    monkeypatch.setattr(ha, "TELEMETRY_DB", tmp_path / "telemetry.db")
    monkeypatch.setattr(ha, "STATE_FILE", tmp_path / "alerts_state.json")
    now = int(__import__("time").time())
    (tmp_path / "alerts_state.json").write_text(json.dumps({
        "fp:gone": {"severity": "warning", "title": "旧事故", "detail": "d",
                    "count": 5, "last_push": now - 10, "status": "pending_recovery",
                    "last_attempt": now - 5},
    }))
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    conn.executescript("""CREATE TABLE incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
        severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT,
        first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
        observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1);""")
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, status) VALUES('fp:gone','warning','旧事故','d',1,2000,'recovered')")
    conn.commit()
    conn.close()

    calls = {"n": 0}

    def _push(text):
        calls["n"] += 1
        return (True, False)

    monkeypatch.setattr(ha, "push_all", _push)

    ha.run(dry_run=False)
    assert calls["n"] == 0  # 60 秒限流内不重试
    state = _read_state(tmp_path)
    assert state["fp:gone"]["status"] == "pending_recovery"

    # 超过限流后重试成功 → recovered
    (tmp_path / "alerts_state.json").write_text(json.dumps({
        "fp:gone": {"severity": "warning", "title": "旧事故", "detail": "d",
                    "count": 5, "last_push": now - 10, "status": "pending_recovery",
                    "last_attempt": now - 120},
    }))
    ha.run(dry_run=False)
    assert calls["n"] == 1
    state = _read_state(tmp_path)
    assert state["fp:gone"]["status"] == "recovered"


def test_pending_recovery_back_to_active_when_reappears(tmp_path, monkeypatch) -> None:
    """pending_recovery 期间事故重新出现 → 回到 active（不重复推 new）。"""
    monkeypatch.setattr(ha, "TELEMETRY_DB", tmp_path / "telemetry.db")
    monkeypatch.setattr(ha, "STATE_FILE", tmp_path / "alerts_state.json")
    now = int(__import__("time").time())
    (tmp_path / "alerts_state.json").write_text(json.dumps({
        "fp:x": {"severity": "warning", "title": "事故X", "detail": "d",
                 "count": 3, "last_push": now - 2000, "status": "pending_recovery",
                 "last_attempt": now - 100},
    }))
    # 事故重新活跃
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    conn.executescript("""CREATE TABLE incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
        severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT,
        first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
        observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1);""")
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen) VALUES('fp:x','warning','事故X','d',1,?)", (now,))
    conn.commit()
    conn.close()

    calls = {"n": 0}

    def _push(text):
        calls["n"] += 1
        return (True, False)

    monkeypatch.setattr(ha, "push_all", _push)

    ha.run(dry_run=False)
    assert calls["n"] == 0  # 回归不重复推
    state = _read_state(tmp_path)
    assert state["fp:x"]["status"] == "active"


def test_dry_run_pushes_nothing(tmp_path, monkeypatch) -> None:
    """dry-run 不实际推送、不写状态。"""
    monkeypatch.setattr(ha, "TELEMETRY_DB", tmp_path / "telemetry.db")
    monkeypatch.setattr(ha, "STATE_FILE", tmp_path / "alerts_state.json")
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    conn.executescript("""CREATE TABLE incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
        severity TEXT NOT NULL, title TEXT NOT NULL, detail TEXT,
        first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
        observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1);""")
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen) VALUES('fp:dry','warning','新事故','d',1,1)")
    conn.commit()
    conn.close()

    called = {"n": 0}
    monkeypatch.setattr(ha, "push_all", lambda text: (called.__setitem__("n", called["n"] + 1), True)[1])

    ha.run(dry_run=True)
    assert called["n"] == 0
    assert not (tmp_path / "alerts_state.json").exists()
