#!/usr/bin/env python3
"""Hermes HUD — Dashboard 插件安全启用/禁用脚本（基于 Hermes config CLI）。

背景：Hermes 有两种插件机制——
  * 原生插件（plugin.yaml / __init__.py）由 `hermes plugins enable/disable` 管理；
  * Dashboard 插件（manifest.json + plugin_api.py）通过 config 的
    `plugins.enabled` 白名单启用。

`hermes plugins enable hermes-hud` 对 Dashboard 插件无效（会报
"Plugin not installed or bundled"）；而直接
`hermes config set plugins.enabled '["hermes-hud"]'` 会覆盖用户已有的
插件列表。本脚本通过 **Hermes 自己的 config CLI**（`hermes config get
--json plugins.enabled` 读取 → 合并/删除 → `hermes config set` 写回）完成
启用/禁用，只增删 hermes-hud，保留其他所有配置；不自行解析 YAML。

失败保护（FAIL CLOSED）：无法可靠读取现有 plugins.enabled 时退出非 0，
并提示用户，绝不假装成功、绝不覆盖为空列表。

用法：
  python3 scripts/enable_dashboard_plugin.py enable     # 追加 hermes-hud
  python3 scripts/enable_dashboard_plugin.py disable    # 仅移除 hermes-hud

环境变量：
  HERMES_HOME    Hermes home（默认 ~/.hermes）
  HUD_HERMES_CLI Hermes CLI 命令（默认 "hermes"；测试可注入 mock）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

PLUGIN = "hermes-hud"
_NOT_SET = "Config key not set"
_USE_API = False  # 读走了 Hermes config loader API（0.19.x）时置 True，写回也走 API


def _cli() -> str:
    return os.environ.get("HUD_HERMES_CLI", "hermes")


def _base_env() -> dict:
    env = dict(os.environ)
    home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
    env["HERMES_HOME"] = home
    return env


def _fail(msg: str) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    print("未做任何修改。请手动检查 config.yaml 后重试。", file=sys.stderr)
    sys.exit(1)


def _get_enabled() -> list[str]:
    """读取 plugins.enabled（JSON）。

    读取路径（按可用性降级，均为 Hermes 官方通道，不自解析 YAML）：
      1. `hermes config get --json plugins.enabled`（Hermes 0.20.5+）
      2. Hermes 官方 config loader API（hermes_cli.config.get_config_value，0.19.x）
      3. 都不可用 → FAIL CLOSED（退出非 0，绝不假装成功/覆盖为空列表）
    """
    try:
        r = subprocess.run(
            [_cli(), "config", "get", "--json", "plugins.enabled"],
            capture_output=True, text=True, timeout=60, env=_base_env())
    except Exception as exc:
        _fail(f"无法执行 hermes config get: {exc}")

    if r.returncode == 0:
        raw = r.stdout.strip()
        if not raw:
            _fail("hermes config get plugins.enabled 返回空输出，无法可靠读取")
        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            _fail(f"hermes config get 输出不是有效 JSON（{exc}）: {raw[:120]}")
        if not isinstance(items, list):
            _fail(f"hermes config get plugins.enabled 不是数组: {type(items).__name__}")
        return [str(x) for x in items]

    stderr = r.stderr.strip()
    if _NOT_SET in stderr:
        return []  # 未设置 = 可靠的空列表（全新用户）
    # CLI get 不存在（Hermes 0.19.x 无 config get）→ 回退官方 loader API
    # （已实证 0.19.0：load_config()/save_config() 数组读写正确）
    if "invalid choice" in stderr:
        global _USE_API
        _USE_API = True
        print("INFO: Hermes <0.20 检测（无 `config get`）——读写走官方 config loader API。", file=sys.stderr)
        try:
            from hermes_cli.config import load_config  # type: ignore
            cfg = load_config()
        except ImportError:
            _fail("当前 Hermes 版本无 `config get`，且无法导入 hermes_cli.config"
                  "（请用 Hermes 的 python 环境运行本脚本）")
        except Exception as exc:  # noqa: BLE001
            _fail(f"Hermes config loader 读取失败: {exc}")
        if not isinstance(cfg, dict):
            _fail(f"Hermes config loader 返回类型异常: {type(cfg).__name__}")
        items = (cfg.get("plugins") or {}).get("enabled") or []
        if not isinstance(items, list):
            _fail(f"Hermes config loader plugins.enabled 不是数组: {type(items).__name__}")
        return [str(x) for x in items]

    _fail(f"hermes config get plugins.enabled 失败 (exit {r.returncode}): {stderr or r.stdout.strip()}")


def _set_enabled(items: list[str]) -> None:
    payload = json.dumps(items, ensure_ascii=False)
    # 写回优先走官方 config API（save_config：数组语义在 0.19/0.20 一致；
    # 0.19.0 的 `config set` 实证会存字符串，不可用）
    try:
        from hermes_cli.config import load_config, save_config  # type: ignore
        cfg = load_config()
        cfg.setdefault("plugins", {})["enabled"] = items
        save_config(cfg)
    except ImportError:
        pass  # 无 hermes_cli（系统 python 场景）→ CLI set（0.20+ 语义正确）
    except Exception as exc:  # noqa: BLE001
        _fail(f"Hermes config loader 写入失败: {exc}")
    else:
        print(f"OK: 已通过官方 config API 写入 plugins.enabled（{len(items)} 个插件）")
        return
    try:
        r = subprocess.run(
            [_cli(), "config", "set", "plugins.enabled", payload],
            capture_output=True, text=True, timeout=60, env=_base_env())
    except Exception as exc:
        _fail(f"无法执行 hermes config set: {exc}")
    if r.returncode != 0:
        _fail(f"hermes config set plugins.enabled 失败 (exit {r.returncode}): {r.stderr.strip() or r.stdout.strip()}")


def _run(action: str) -> int:
    items = _get_enabled()
    had = PLUGIN in items

    if action == "enable":
        if had:
            print(f"OK: {PLUGIN} 已在 plugins.enabled 中（幂等，无变化）")
            return 0
        items.append(PLUGIN)
        _set_enabled(items)
        print(f"OK: 已追加 {PLUGIN} → plugins.enabled（保留 {len(items)} 个插件）")
        print("提示：重启 dashboard 使后端路由挂载生效。")
        return 0

    if action == "disable":
        if not had:
            print(f"OK: {PLUGIN} 不在 plugins.enabled 中（幂等，无变化）")
            return 0
        items = [i for i in items if i != PLUGIN]
        _set_enabled(items)
        print(f"OK: 已移除 {PLUGIN}（保留其他 {len(items)} 个插件）")
        print("提示：重启 dashboard 生效。")
        return 0

    print(f"用法: {sys.argv[0]} enable|disable", file=sys.stderr)
    return 2


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"用法: {sys.argv[0]} enable|disable", file=sys.stderr)
        sys.exit(2)
    sys.exit(_run(sys.argv[1]))
