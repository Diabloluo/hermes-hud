"""P0-3 安装启用脚本测试：读取→合并→写回，幂等，保留已有插件。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enable_dashboard_plugin.py"

CONFIG_TEMPLATE = """model: deepseek-v4-flash
plugins:
  enabled:
    - other-plugin-a
    - other-plugin-b
platforms:
  telegram:
    enabled: true
"""


def _run(tmp_home: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(__import__("os").environ)
    env["HERMES_HOME"] = str(tmp_home)
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=env)


@pytest.fixture
def home_with_others(tmp_path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return home


def test_enable_appends_and_preserves_others(home_with_others) -> None:
    r = _run(home_with_others, "enable")
    assert r.returncode == 0
    cfg = (home_with_others / "config.yaml").read_text(encoding="utf-8")
    assert "hermes-hud" in cfg
    assert "other-plugin-a" in cfg
    assert "other-plugin-b" in cfg  # 已有插件保留


def test_enable_is_idempotent(home_with_others) -> None:
    _run(home_with_others, "enable")
    r2 = _run(home_with_others, "enable")
    assert r2.returncode == 0
    cfg = (home_with_others / "config.yaml").read_text(encoding="utf-8")
    assert cfg.count("hermes-hud") == 1  # 不重复追加


def test_disable_removes_only_hud(home_with_others) -> None:
    _run(home_with_others, "enable")
    r = _run(home_with_others, "disable")
    assert r.returncode == 0
    cfg = (home_with_others / "config.yaml").read_text(encoding="utf-8")
    assert "hermes-hud" not in cfg
    assert "other-plugin-a" in cfg
    assert "other-plugin-b" in cfg  # 其他插件不受影响


def test_disable_when_absent_is_idempotent(home_with_others) -> None:
    r = _run(home_with_others, "disable")
    assert r.returncode == 0
    cfg = (home_with_others / "config.yaml").read_text(encoding="utf-8")
    assert "other-plugin-a" in cfg


def test_config_without_plugins_section(tmp_path) -> None:
    home = tmp_path / "home2"
    home.mkdir()
    (home / "config.yaml").write_text("model: x\n", encoding="utf-8")
    r = _run(home, "enable")
    assert r.returncode == 0
    cfg = (home / "config.yaml").read_text(encoding="utf-8")
    assert "hermes-hud" in cfg
    assert "model: x" in cfg  # 其他配置保留


def test_no_config_file(tmp_path) -> None:
    home = tmp_path / "home3"
    home.mkdir()
    r = _run(home, "enable")
    assert r.returncode == 0
    cfg = (home / "config.yaml").read_text(encoding="utf-8")
    assert "hermes-hud" in cfg
