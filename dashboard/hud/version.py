"""HUD API 版本契约（Desktop Foundation v0.1，contract D）。

统一常量：所有版本字段从这里取，禁止各 endpoint 自己硬编码。
- HUD_API_SCHEMA_VERSION：HTTP/WS API 结构版本（Desktop app 据此协商）
- plugin_version：从 dashboard/manifest.json 读取（单点真相）
"""

from __future__ import annotations

import json
from pathlib import Path

HUD_API_SCHEMA_VERSION = 1
HUD_MIN_PLUGIN_VERSION = "1.1.0"  # Desktop v0.1 支持的最低 HUD 插件版本

_MANIFEST = Path(__file__).resolve().parents[1] / "manifest.json"


def get_plugin_version() -> str:
    """读取 manifest.json 的 version（单点真相；失败返回 unknown 不崩溃）。"""
    try:
        return str(json.loads(_MANIFEST.read_text(encoding="utf-8")).get("version", "unknown"))
    except Exception:  # noqa: BLE001
        return "unknown"


def api_version_payload() -> dict:
    """统一版本响应片段（/health + /settings 复用）。"""
    return {
        "api_schema_version": HUD_API_SCHEMA_VERSION,
        "plugin_version": get_plugin_version(),
    }
