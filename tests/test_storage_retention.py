"""P1-2 retention 自动执行 + P1-8 平台检测 + P1-6 隐私工具测试。"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.hud import storage
from dashboard.hud.redaction import redact_obj, sanitize_cmdline, sanitize_path


# ---------------------------------------------------------------------------
# P1-2 retention
# ---------------------------------------------------------------------------

def _seed(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript("""
    CREATE TABLE metrics (ts INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
        value REAL NOT NULL, meta TEXT);
    CREATE TABLE incidents (id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL,
        detail TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
        count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
        observations INTEGER NOT NULL DEFAULT 1, state_changes INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    now = int(time.time())
    old = now - 40 * 86400  # 40 天前（超 30 天保留期）
    very_old = now - 100 * 86400  # 100 天前（超 90 天事故保留期）
    conn.executemany("INSERT INTO metrics(ts, kind, name, value) VALUES(?,?,?,?)",
                     [(old, "sys", "cpu", 1.0), (now, "sys", "cpu", 2.0)])
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, status) VALUES('fp:old-recovered','warning','旧','d',?,?,'recovered')", (very_old, very_old))
    conn.execute("INSERT INTO incidents(fingerprint, severity, title, detail, first_seen, last_seen, status) VALUES('fp:active','warning','活跃','d',?,?,'active')", (old, now))
    conn.commit()
    conn.close()


def test_prune_removes_expired(tmp_path) -> None:
    db = tmp_path / "telemetry.db"
    _seed(db)
    s = storage.TelemetryStore(db_path=db)
    r = s.prune()
    assert r["metrics_deleted"] == 1  # 40 天前的被删，今天的保留
    assert r["recovered_incidents_deleted"] == 1  # 100 天前的 recovered 被删
    assert s.stats()["metrics_rows"] == 1
    # 活跃事故不删
    incs = s.list_incidents()
    assert any(i["fingerprint"] == "fp:active" for i in incs)
    assert not any(i["fingerprint"] == "fp:old-recovered" for i in incs)


def test_maintenance_runs_at_most_daily(tmp_path) -> None:
    db = tmp_path / "telemetry.db"
    _seed(db)
    s = storage.TelemetryStore(db_path=db)

    r1 = s.maintenance()
    assert r1["pruned"] is True
    assert r1["metrics_deleted"] == 1
    assert s.stats()["metrics_rows"] == 1

    # 再次调用（同一天）→ 不再执行
    r2 = s.maintenance()
    assert r2["pruned"] is False
    assert "next_in_s" in r2

    # 模拟新实例（重启）也不会高频执行：meta 表记住了 last_prune
    s2 = storage.TelemetryStore(db_path=db)
    r3 = s2.maintenance()
    assert r3["pruned"] is False


def test_maintenance_prunes_after_interval(tmp_path, monkeypatch) -> None:
    db = tmp_path / "telemetry.db"
    _seed(db)
    s = storage.TelemetryStore(db_path=db)
    s.maintenance()
    # 把 last_prune 改到 25 小时前 → 允许再次执行
    old = int(time.time()) - storage.MAINTENANCE_INTERVAL_S - 3600
    conn = sqlite3.connect(db)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_prune', ?)", (str(old),))
    conn.commit()
    conn.close()
    r = s.maintenance()
    assert r["pruned"] is True


# ---------------------------------------------------------------------------
# P1-8 平台检测
# ---------------------------------------------------------------------------

def test_launchd_not_applicable_on_linux(tmp_path, monkeypatch) -> None:
    from dashboard.hud import collectors
    monkeypatch.setattr(collectors.sys, "platform", "linux")
    monkeypatch.setattr(collectors, "HERMES_HOME", tmp_path)
    r = collectors.collect_launchd_check()
    assert r["status"] == "not_applicable"
    assert r["note"] == "launchd 仅 macOS 适用"


def test_launchd_uses_current_uid(tmp_path, monkeypatch) -> None:
    """launchctl 必须用 os.getuid() 而非硬编码 gui/501。"""
    from dashboard.hud import collectors
    import subprocess
    monkeypatch.setattr(collectors.sys, "platform", "darwin")
    monkeypatch.setattr(collectors, "HERMES_HOME", tmp_path)
    import os as _os
    monkeypatch.setattr(_os, "getuid", lambda: 1234)  # 模拟非 501 的 UID
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        import types as _t
        return _t.SimpleNamespace(returncode=0, stdout="ai.hermes.gateway\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    collectors.collect_launchd_check()
    assert "gui/1234" in seen["args"], seen["args"]
    assert "gui/501" not in seen["args"]


# ---------------------------------------------------------------------------
# P1-6 隐私工具
# ---------------------------------------------------------------------------

def test_sanitize_path_home_prefix(monkeypatch) -> None:
    import os
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/alice"))
    assert sanitize_path("/Users/alice/.hermes/state.db") == "~/.hermes/state.db"
    assert sanitize_path("/Users/alice") == "~"
    # 非当前用户前缀同样脱敏用户名
    assert "bob" not in sanitize_path("/Users/bob/x/y/z/deep/file.txt")


def test_sanitize_path_relative_untouched() -> None:
    assert sanitize_path("") == ""
    assert sanitize_path("relative/path") == "relative/path"


def test_sanitize_cmdline_redacts_and_truncates() -> None:
    cmd = "/Users/alice/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main dashboard --token sk-test-abcdef123456"
    out = sanitize_cmdline(cmd, 200)
    assert "alice" not in out
    assert "sk-test-abcdef123456" not in out
    assert "~/" in out
    assert "[REDACTED]" in out


def test_redact_obj_nested() -> None:
    obj = {
        "name": "ok",
        "token": "plain-value-without-key-context",
        "nested": {"api_key": "x1y2z3", "keep": ["a", "b"]},
        "list": [{"pass" + "word": "p"}, "plain"],
        "n": 5,
        "none": None,
    }
    out = redact_obj(obj)
    assert out["name"] == "ok"
    assert out["token"] == "[REDACTED]"
    assert out["nested"]["api_key"] == "[REDACTED]"
    assert out["nested"]["keep"] == ["a", "b"]
    assert out["list"][0]["password"] == "[REDACTED]"
    assert out["list"][1] == "plain"
    assert out["n"] == 5
    assert out["none"] is None
