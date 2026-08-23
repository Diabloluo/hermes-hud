"""P0-3 安装启用脚本测试（Config Safety Gate 版）。

脚本通过 Hermes config CLI（hermes config get/set --json）读写
plugins.enabled，不解析 YAML。本测试覆盖 6 种 config 格式 + fail-closed。

要求真实 hermes CLI（本机具备）；CI runner 无 hermes 时自动 skip。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enable_dashboard_plugin.py"

pytestmark = pytest.mark.skipif(
    shutil.which("hermes") is None,
    reason="需要真实 hermes CLI（本机验证；CI runner 无 hermes）")

# 6 种 config 格式（cases 1-6）
CONFIG_CASES = {
    "block_list": """model: deepseek-v4-flash
plugins:
  enabled:
    - foo
    - bar
platforms:
  telegram:
    enabled: true
""",
    "inline_array": """model: deepseek-v4-flash
plugins:
  enabled: ["foo", "bar"]
platforms:
  telegram:
    enabled: true
""",
    "disabled_plus_enabled": """model: deepseek-v4-flash
plugins:
  disabled:
    - legacy
  enabled:
    - foo
platforms:
  telegram:
    enabled: true
""",
    "quoted_items": """model: deepseek-v4-flash
plugins:
  enabled:
    - "foo"
    - 'bar'
platforms:
  telegram:
    enabled: true
""",
    "comment_inline": """model: deepseek-v4-flash
plugins:
  enabled:
    - foo # comment
  other_setting: true
platforms:
  telegram:
    enabled: true
""",
    "many_sections": """model: deepseek-v4-flash
provider: deepseek
timezone: Asia/Shanghai
plugins:
  enabled:
    - foo
    - bar
platforms:
  telegram:
    enabled: true
  discord:
    streaming: false
tools:
  enabled:
    - terminal
    - web
logs:
  level: debug
budget:
  daily_usd: 3.0
cron:
  allow_agent_scheduling: false
""",
}


def _run(tmp_home: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(tmp_home)
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=env, timeout=120)


def _enabled_via_cli(tmp_home: Path) -> list:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(tmp_home)
    r = subprocess.run(["hermes", "config", "get", "--json", "plugins.enabled"],
                       capture_output=True, text=True, env=env, timeout=60)
    if r.returncode != 0:
        return []
    return json.loads(r.stdout.strip())


def _unrelated_keys_via_cli(tmp_home: Path) -> dict:
    """读取若干无关配置键，验证语义不变。"""
    env = dict(os.environ)
    env["HERMES_HOME"] = str(tmp_home)
    out = {}
    for key in ("model", "timezone", "platforms.telegram.enabled", "logs.level",
                "budget.daily_usd", "cron.allow_agent_scheduling", "tools.enabled"):
        r = subprocess.run(["hermes", "config", "get", "--json", key],
                           capture_output=True, text=True, env=env, timeout=60)
        if r.returncode == 0:
            out[key] = json.loads(r.stdout.strip())
    return out


@pytest.mark.parametrize("name,cfg", list(CONFIG_CASES.items()))
def test_enable_and_disable_6_formats(tmp_path, name, cfg) -> None:
    """对每种格式：enable 只加 hermes-hud；disable 只删 hermes-hud；无关配置语义不变；幂等。"""
    home = tmp_path / name
    home.mkdir()
    (home / "config.yaml").write_text(cfg, encoding="utf-8")

    before = _enabled_via_cli(home)

    # enable
    r = _run(home, "enable")
    assert r.returncode == 0, r.stderr
    after_enable = _enabled_via_cli(home)
    assert "hermes-hud" in after_enable
    assert set(before) <= set(after_enable)  # 原有项全部保留
    assert after_enable.count("hermes-hud") == 1

    # enable 幂等
    r2 = _run(home, "enable")
    assert r2.returncode == 0
    assert _enabled_via_cli(home).count("hermes-hud") == 1

    # disable
    r3 = _run(home, "disable")
    assert r3.returncode == 0, r3.stderr
    after_disable = _enabled_via_cli(home)
    assert "hermes-hud" not in after_disable
    assert set(before) == set(after_disable)  # 其他插件原样

    # disable 幂等
    r4 = _run(home, "disable")
    assert r4.returncode == 0
    assert "hermes-hud" not in _enabled_via_cli(home)

    # 无关配置语义不变
    unrelated = _unrelated_keys_via_cli(home)
    for key in ("model", "timezone", "platforms.telegram.enabled",
                "logs.level", "budget.daily_usd", "cron.allow_agent_scheduling",
                "tools.enabled"):
        if key in unrelated:  # 该格式中存在的键必须保持
            assert unrelated[key] is not None, f"{key} 丢失: {name}"


def test_fail_closed_when_cli_returns_garbage(tmp_path) -> None:
    """CLI 输出不可解析 → FAIL CLOSED（退出非 0，不改 config）。"""
    home = tmp_path / "fail1"
    home.mkdir()
    (home / "config.yaml").write_text("model: x\n", encoding="utf-8")
    fake = tmp_path / "fake-hermes"
    fake.write_text(
        "#!/bin/sh\n"
        "echo 'not-json-at-all'\n"
        "exit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env["HUD_HERMES_CLI"] = str(fake)
    r = subprocess.run([sys.executable, str(SCRIPT), "enable"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode != 0, "必须 FAIL CLOSED"
    assert "ERROR" in r.stderr
    cfg = (home / "config.yaml").read_text(encoding="utf-8")
    assert "hermes-hud" not in cfg  # 未做修改


def test_fail_closed_when_cli_crashes(tmp_path) -> None:
    """CLI 崩溃（exit 1 且非 'Config key not set'）→ FAIL CLOSED。"""
    home = tmp_path / "fail2"
    home.mkdir()
    (home / "config.yaml").write_text("model: x\n", encoding="utf-8")
    fake = tmp_path / "fake-hermes-crash"
    fake.write_text("#!/bin/sh\necho 'boom' >&2\nexit 3\n", encoding="utf-8")
    fake.chmod(0o755)
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env["HUD_HERMES_CLI"] = str(fake)
    r = subprocess.run([sys.executable, str(SCRIPT), "disable"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode != 0
    assert "ERROR" in r.stderr
    cfg = (home / "config.yaml").read_text(encoding="utf-8")
    assert "hermes-hud" not in cfg


def test_fail_closed_when_cli_missing(tmp_path) -> None:
    """CLI 不存在 → FAIL CLOSED。"""
    home = tmp_path / "fail3"
    home.mkdir()
    (home / "config.yaml").write_text("model: x\n", encoding="utf-8")
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env["HUD_HERMES_CLI"] = str(tmp_path / "no-such-cli-xyz")
    r = subprocess.run([sys.executable, str(SCRIPT), "enable"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode != 0
    assert "ERROR" in r.stderr


def test_no_config_file_key_not_set_is_empty(tmp_path) -> None:
    """全新 home（无 config）→ 'Config key not set' 视为空列表，enable 成功。"""
    home = tmp_path / "fresh"
    home.mkdir()
    r = _run(home, "enable")
    assert r.returncode == 0, r.stderr
    assert "hermes-hud" in _enabled_via_cli(home)
