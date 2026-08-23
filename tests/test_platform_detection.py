"""P1-8 平台检测测试（独立文件）。

覆盖：
  - 非 macOS → launchd.status = not_applicable，不产生 warning incident
  - macOS → 使用当前 UID 的 launchctl print（不硬编码 gui/501）
  - rules 引擎对 not_applicable 的处理
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from dashboard.hud import collectors, rules


@pytest.fixture()
def iso_home(tmp_path, monkeypatch):
    monkeypatch.setattr(collectors, "HERMES_HOME", tmp_path)
    return tmp_path


def test_linux_is_not_applicable(iso_home, monkeypatch) -> None:
    """Linux 上 launchd 不适用。"""
    monkeypatch.setattr(collectors.sys, "platform", "linux")
    r = collectors.collect_launchd_check()
    assert r["status"] == "not_applicable"
    assert r["managed"] is False
    assert r["note"] == "launchd 仅 macOS 适用"


def test_windows_is_not_applicable(iso_home, monkeypatch) -> None:
    monkeypatch.setattr(collectors.sys, "platform", "win32")
    r = collectors.collect_launchd_check()
    assert r["status"] == "not_applicable"


def test_darwin_uses_current_uid(iso_home, monkeypatch) -> None:
    """macOS：launchctl print 使用 os.getuid()，不是硬编码 gui/501。"""
    import os as _os
    monkeypatch.setattr(collectors.sys, "platform", "darwin")
    monkeypatch.setattr(_os, "getuid", lambda: 4242)
    seen: dict = {}

    def fake_run(args, **kw):
        seen["args"] = list(args)
        return types.SimpleNamespace(returncode=0, stdout="ai.hermes.gateway\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = collectors.collect_launchd_check()
    assert "gui/4242" in seen["args"], seen["args"]
    assert "gui/501" not in seen["args"]
    assert r["status"] == "managed"  # stdout 含 hermes.gateway


def test_darwin_unmanaged_status(iso_home, monkeypatch) -> None:
    monkeypatch.setattr(collectors.sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=0, stdout="com.apple.x\n"),
    )
    r = collectors.collect_launchd_check()
    assert r["status"] == "unmanaged"


def _snap(launchd: dict) -> dict:
    return {
        "gateway": {"alive": True, "state": "running", "pid": 1, "platforms": {}},
        "db": {}, "system": {"disk_free_percent": 50, "memory": {"percent": 30}},
        "errors": {"count_30m": 0},
        "launchd": launchd,
        "dashboard": {"procs": [{"pid": 1}]},
        "cron": {"jobs": []},
    }


def test_rules_not_applicable_no_incident() -> None:
    """not_applicable 不产生 launchd warning 事故。"""
    health = rules.evaluate_snapshot(_snap({
        "managed": False, "status": "not_applicable", "note": "launchd 仅 macOS 适用"}))
    assert not any(i["fingerprint"] == "launchd:not-managed" for i in health["incidents"])
    ld = next(c for c in health["checks"] if c["key"] == "launchd")
    assert ld["status"] == "normal"
    assert ld["severity"] == "normal"


def test_rules_unmanaged_still_warns() -> None:
    """macOS 上确实 unmanaged 才产生 warning。"""
    health = rules.evaluate_snapshot(_snap({
        "managed": False, "status": "unmanaged", "plist_exists": True}))
    assert any(i["fingerprint"] == "launchd:not-managed" for i in health["incidents"])


def test_rules_managed_normal() -> None:
    health = rules.evaluate_snapshot(_snap({
        "managed": True, "status": "managed", "plist_exists": True}))
    ld = next(c for c in health["checks"] if c["key"] == "launchd")
    assert ld["status"] == "normal"
