"""P1-5 / P0-2 事故生命周期 + fingerprint 测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.hud import storage
from dashboard.hud.redaction import fingerprint


def _store(tmp_path) -> storage.TelemetryStore:
    return storage.TelemetryStore(db_path=tmp_path / "telemetry.db")


def test_observations_vs_state_changes(tmp_path) -> None:
    """count/observations 每次观测 +1；state_changes 仅实质变化 +1。"""
    s = _store(tmp_path)
    t0 = 1000
    for i in range(5):
        s.upsert_incident("fp:1", "warning", "同一标题", "同一详情", now=t0 + i)
    inc = s.list_incidents()[0]
    assert inc["count"] == 5
    assert inc["observations"] == 5
    assert inc["state_changes"] == 1  # 内容无变化

    # 实质变化（severity 升级）
    s.upsert_incident("fp:1", "critical", "同一标题", "同一详情", now=t0 + 10)
    inc = s.list_incidents()[0]
    assert inc["count"] == 6
    assert inc["state_changes"] == 2
    assert inc["severity"] == "critical"


def test_recover_and_mark_pending(tmp_path) -> None:
    """恢复状态机：active → pending_recovery → recovered。"""
    s = _store(tmp_path)
    s.upsert_incident("fp:r", "warning", "事故", "detail", now=1000)
    assert s.list_incidents(active_only=True)[0]["status"] == "active"

    s.mark_pending_recovery("fp:r", now=1100)
    inc = s.list_incidents(active_only=True)[0]
    assert inc["status"] == "pending_recovery"  # 仍算活跃（未恢复）

    s.recover_incident("fp:r", now=1200)
    inc = s.list_incidents()[0]
    assert inc["status"] == "recovered"
    assert s.list_incidents(active_only=True) == []


def test_pending_recovery_not_lost_on_restart(tmp_path) -> None:
    """重启后 pending_recovery 仍在（DB 持久化）。"""
    p = tmp_path / "telemetry.db"
    s1 = storage.TelemetryStore(db_path=p)
    s1.upsert_incident("fp:p", "warning", "t", "d", now=1000)
    s1.mark_pending_recovery("fp:p", now=1100)
    # 模拟重启：新实例同一 db
    s2 = storage.TelemetryStore(db_path=p)
    inc = s2.list_incidents(active_only=True)[0]
    assert inc["status"] == "pending_recovery"


def test_schema_migration_from_v100(tmp_path) -> None:
    """v1.0.0 旧库（无 observations/state_changes 列）平滑升级。"""
    import sqlite3
    p = tmp_path / "telemetry.db"
    conn = sqlite3.connect(p)
    conn.executescript("""
    CREATE TABLE incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL,
        detail TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active'
    );
    CREATE TABLE metrics (ts INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
        value REAL NOT NULL, meta TEXT);
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, first_seen, last_seen) VALUES('fp:old','warning','旧事故',1,1)")
    conn.commit()
    conn.close()

    s = storage.TelemetryStore(db_path=p)  # 触发迁移
    inc = s.list_incidents()[0]
    assert inc["fingerprint"] == "fp:old"
    assert inc["observations"] == 1  # 迁移默认值
    assert inc["state_changes"] == 1
    # 迁移后仍可写
    s.upsert_incident("fp:old", "warning", "旧事故", "detail", now=2000)
    assert s.list_incidents()[0]["count"] == 2


def test_fingerprint_no_secret_and_stable() -> None:
    """fingerprint：先脱敏再归一化，同源错误（不同 secret）指纹一致。"""
    fp1 = fingerprint("2026-08-23 12:00:00 ERROR auth failed token=aaaabbbb")
    fp2 = fingerprint("2026-08-23 12:05:00 ERROR auth failed token=ccccdddd")
    assert "abc123def456ghi789" not in fp1
    assert "x1y2z3a4b5c6d7e8f9g0" not in fp2
    assert fp1 == fp2


def test_cron_fingerprint_stable_across_streaks() -> None:
    """P1-4：cron 指纹不随失败次数变化（fail-3/fail-4/fail-5 必须同源）。"""
    # 直接验证 rules 产出的指纹稳定
    from dashboard.hud import rules

    def _snap_with_streak(streak: int) -> dict:
        return {"gateway": {"alive": True, "state": "running", "pid": 1, "platforms": {}},
                "db": {}, "system": {"disk_free_percent": 50, "memory": {"percent": 30}},
                "errors": {"count_30m": 0},
                "launchd": {"managed": True, "status": "managed"},
                "dashboard": {"procs": [{"pid": 1}]},
                "cron": {"jobs": [{"id": "job1", "name": "任务", "failure_streak": streak}]}}

    fps = set()
    for streak in (3, 4, 5):
        health = rules.evaluate_snapshot(_snap_with_streak(streak))
        for inc in health["incidents"]:
            if inc["fingerprint"].startswith("cron:"):
                fps.add(inc["fingerprint"])
    assert fps == {"cron:job1:fail"}, fps


def test_launchd_not_applicable_no_warning() -> None:
    """P1-8：非 macOS 平台 launchd=not_applicable 不产生 warning incident。"""
    from dashboard.hud import rules
    snap = {"gateway": {"alive": True, "state": "running", "pid": 1, "platforms": {}},
            "db": {}, "system": {"disk_free_percent": 50, "memory": {"percent": 30}},
            "errors": {"count_30m": 0},
            "launchd": {"managed": False, "status": "not_applicable", "note": "launchd 仅 macOS 适用"},
            "dashboard": {"procs": [{"pid": 1}]},
            "cron": {"jobs": []}}
    health = rules.evaluate_snapshot(snap)
    assert not any(i["fingerprint"] == "launchd:not-managed" for i in health["incidents"])
    ld_check = next(c for c in health["checks"] if c["key"] == "launchd")
    assert ld_check["status"] == "normal"
