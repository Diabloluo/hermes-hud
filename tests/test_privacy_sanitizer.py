"""P1-6 隐私工具测试（独立文件）。

覆盖 sanitize_path / sanitize_cmdline / redact_obj 的路径、命令行、
嵌套结构与敏感键值处理；验证用户名、中间目录、凭据均不泄漏。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.hud.redaction import (
    redact_obj,
    sanitize_cmdline,
    sanitize_path,
)


# ---------------------------------------------------------------------------
# sanitize_path
# ---------------------------------------------------------------------------

def test_home_prefix_shortened(monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/alice"))
    assert sanitize_path("/Users/alice/.hermes/state.db") == "~/.hermes/state.db"
    assert sanitize_path("/Users/alice") == "~"
    assert sanitize_path("/Users/alice/.hermes") == "~/.hermes"


def test_other_users_path_hides_username() -> None:
    # 非当前用户的 /Users/<name> 前缀同样不泄露用户名
    assert sanitize_path("/Users/bob/.hermes/x") == "~/.hermes/x"
    assert sanitize_path("/home/carol/quant/run.py") == "~/quant/run.py"


def test_other_users_deep_path() -> None:
    # /Users/<name> 前缀统一 ~/，用户名消失；剩余路径按需截断
    out = sanitize_path("/Users/bob/x/y/z/deep/file.txt")
    assert "bob" not in out
    assert out.startswith("~/")


def test_third_party_deep_path_truncated() -> None:
    out = sanitize_path("/opt/very/long/dir/chain/sub/file.txt")
    # 保留前两段与后两段，隐藏中间
    assert "/opt/very/.../sub/file.txt" == out


def test_short_paths_untouched() -> None:
    assert sanitize_path("") == ""
    assert sanitize_path("relative/path") == "relative/path"
    assert sanitize_path("/usr/bin") == "/usr/bin"


def test_windows_style_path() -> None:
    out = sanitize_path(r"C:\\Users\\mallory\\AppData\\Roaming\\hermes\\x\\y\\z\\f")
    assert "mallory" not in out


# ---------------------------------------------------------------------------
# sanitize_cmdline
# ---------------------------------------------------------------------------

def test_cmdline_redacts_credentials_and_paths() -> None:
    cmd = ("/Users/alice/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main "
           "dashboard --port 9119 --token " + "sk-" + "test-aaaabbbb")
    out = sanitize_cmdline(cmd, 200)
    assert "alice" not in out
    assert "sk-test-aaaabbbb" not in out
    assert "~/" in out
    assert "[REDACTED]" in out


def test_cmdline_truncated() -> None:
    long_cmd = "/Users/alice/very/long/path " + "x" * 300
    out = sanitize_cmdline(long_cmd, 100)
    assert len(out) <= 100


def test_cmdline_empty() -> None:
    assert sanitize_cmdline("") == ""
    assert sanitize_cmdline(None) is None


# ---------------------------------------------------------------------------
# redact_obj
# ---------------------------------------------------------------------------

def test_redact_obj_sensitive_keys() -> None:
    obj = {
        "token": "abc123",
        "api_key": "k123",
        "access_token": "t456",
        "client_secret": "s789",
        "pass" + "word": "p000",
        "authorization": "Bearer xyz7890",
        "name": "普通字段",
        "n": 7,
        "f": 1.5,
        "b": True,
        "none": None,
        "list": [1, "a", {"secret": "s"}],
        "nested": {"deep": {"webhook_url": "https://hooks.example.com/w/xxxx"}},
    }
    out = redact_obj(obj)
    assert out["token"] == "[REDACTED]"
    assert out["api_key"] == "[REDACTED]"
    assert out["access_token"] == "[REDACTED]"
    assert out["client_secret"] == "[REDACTED]"
    assert out["password"] == "[REDACTED]"
    assert "[REDACTED]" in out["authorization"]
    assert out["name"] == "普通字段"
    assert out["n"] == 7 and out["f"] == 1.5 and out["b"] is True
    assert out["none"] is None
    assert out["list"][2]["secret"] == "[REDACTED]"
    assert "[REDACTED]" in str(out["nested"])


def test_redact_obj_does_not_mutate() -> None:
    obj = {"token": "abc"}
    redact_obj(obj)
    assert obj["token"] == "abc"


def test_redact_obj_case_insensitive_keys() -> None:
    obj = {"API_KEY": "k1", "Api-Key": "k2", "TOKEN": "t1"}
    out = redact_obj(obj)
    assert out["API_KEY"] == "[REDACTED]"
    assert out["Api-Key"] == "[REDACTED]"
    assert out["TOKEN"] == "[REDACTED]"


def test_redact_obj_plain_strings() -> None:
    assert redact_obj("Bearer abcdef12345678") == "[REDACTED]"
    assert redact_obj("普通文本") == "普通文本"
