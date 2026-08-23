#!/usr/bin/env python3
"""Hermes HUD — Dashboard 插件安全启用/禁用脚本。

背景：Hermes 有两种插件机制——
  * 原生插件（plugin.yaml / __init__.py）由 `hermes plugins enable/disable` 管理；
  * Dashboard 插件（manifest.json + plugin_api.py）通过 config 的
    `plugins.enabled` 白名单启用。

`hermes plugins enable hermes-hud` 对 Dashboard 插件无效（会报
"Plugin not installed or bundled"）；而直接
`hermes config set plugins.enabled '["hermes-hud"]'` 会覆盖用户已有的
插件列表。本脚本采用 读取 → 合并 → 写回 的方式，只增删 hermes-hud，
保留其他所有插件，幂等执行。

用法：
  python3 scripts/enable_dashboard_plugin.py enable     # 追加 hermes-hud
  python3 scripts/enable_dashboard_plugin.py disable    # 仅移除 hermes-hud

支持 HERMES_HOME 环境变量（默认 ~/.hermes）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PLUGIN = "hermes-hud"


def _config_path() -> Path:
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    return home / "config.yaml"


def _read_config(path: Path) -> list[str]:
    """读取 plugins.enabled 列表；无配置/无键时返回空列表。"""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^plugins:\s*\n(\s+enabled:\s*\n((?:\s+-[ \t]*[\w.-]+\n?)*))", text, re.M)
    if not m:
        # plugins 段存在但无 enabled 键
        return []
    items = re.findall(r"^\s+-\s+[\"']?([\w.-]+)[\"']?", m.group(2), re.M)
    return items


def _write_config(path: Path, items: list[str]) -> None:
    """把 plugins.enabled 写回 config.yaml（保留文件中其他所有内容）。"""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    yaml_items = "\n".join(f"    - {i}" for i in items)
    new_block = f"plugins:\n  enabled:\n{yaml_items}\n"
    if re.search(r"^plugins:\s*\n\s+enabled:", text, re.M):
        # 替换现有 plugins.enabled 块
        text = re.sub(
            r"^plugins:\s*\n\s+enabled:\s*\n((?:\s+-[ \t]*[\w.-]+\n?)*)",
            new_block, text, count=1, flags=re.M)
    elif re.search(r"^plugins:\s*\n", text, re.M):
        # plugins 段存在但无 enabled：插入 enabled
        text = re.sub(
            r"^plugins:\s*\n",
            f"plugins:\n  enabled:\n{yaml_items}\n", text, count=1, flags=re.M)
    else:
        text = (new_block + "\n" + text) if text.strip() else new_block
    path.write_text(text, encoding="utf-8")


def _run(action: str) -> int:
    path = _config_path()
    items = _read_config(path)
    had = PLUGIN in items

    if action == "enable":
        if had:
            print(f"OK: {PLUGIN} 已在 plugins.enabled 中（幂等，无变化）")
            return 0
        items.append(PLUGIN)
        _write_config(path, items)
        print(f"OK: 已追加 {PLUGIN} → plugins.enabled（保留 {len(items)} 个插件）")
        print("提示：重启 dashboard 使后端路由挂载生效。")
        return 0

    if action == "disable":
        if not had:
            print(f"OK: {PLUGIN} 不在 plugins.enabled 中（幂等，无变化）")
            return 0
        items = [i for i in items if i != PLUGIN]
        _write_config(path, items)
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
