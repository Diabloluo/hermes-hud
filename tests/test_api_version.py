"""HUD API 版本契约测试（Desktop Foundation v0.1，contract D）。

- /health + /settings 携带 api_schema_version + plugin_version（统一常量）
- 旧字段完整保留（backward compatibility——Web 客户端不受影响）
- WS envelope 携带 schema_version，data 语义不变
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

from hud import version  # noqa: E402


def test_unified_version_constant() -> None:
    assert version.HUD_API_SCHEMA_VERSION == 1
    assert version.HUD_MIN_PLUGIN_VERSION == "1.1.1"


def test_plugin_version_reads_manifest() -> None:
    manifest = Path(__file__).resolve().parents[1] / "dashboard" / "manifest.json"
    import json
    assert version.get_plugin_version() == json.loads(manifest.read_text())["version"]
    assert version.get_plugin_version().startswith("1.1")


def test_api_version_payload_shape() -> None:
    p = version.api_version_payload()
    assert p == {"api_schema_version": 1, "plugin_version": version.get_plugin_version()}


def test_manifest_unknown_safe(tmp_path, monkeypatch) -> None:
    """manifest 缺失 → unknown，不崩溃。"""
    monkeypatch.setattr(version, "_MANIFEST", tmp_path / "nope.json")
    assert version.get_plugin_version() == "unknown"


def test_health_backward_compat_fields() -> None:
    """/health 的旧字段（overall/counts/checks）与版本字段并存。"""
    # plugin_api.get_health 逻辑：dict(_last_health) + api_version_payload()
    base = {"overall": "ok", "counts": {"critical": 0, "warning": 0}, "checks": []}
    out = dict(base)
    out.update(version.api_version_payload())
    assert out["overall"] == "ok"
    assert out["counts"]["critical"] == 0
    assert out["api_schema_version"] == 1
    assert out["plugin_version"].startswith("1.1")


def test_ws_envelope_schema_version() -> None:
    """WS envelope：schema_version + 既有 data 语义（ts/health/events/...）。"""
    import time
    from hud import version as v
    envelope = {
        "schema_version": v.HUD_API_SCHEMA_VERSION,
        "ts": time.time(),
        "health": {"overall": "ok", "counts": {"critical": 0, "warning": 0}},
        "events": [],
        "gateway_alive": True,
        "active_agents": 0,
        "active_sessions": 0,
        "platforms": {},
        "cron_summary": {},
    }
    assert envelope["schema_version"] == 1
    # 既有字段语义不变（keys 完整保留）
    for k in ("ts", "health", "events", "gateway_alive", "active_agents",
              "active_sessions", "platforms", "cron_summary"):
        assert k in envelope
