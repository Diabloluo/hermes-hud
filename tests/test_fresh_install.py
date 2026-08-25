"""Fresh Install CI 辅助脚本测试（scripts/fresh_install_check.py）。

覆盖：health polling success / polling timeout / owned-process cleanup /
no broad kill / log redaction / check-json / check-no-cst。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fresh_install_check as fic  # noqa: E402


# ---------- health polling ----------

def test_wait_http_success(fixture_server) -> None:
    ok, last = fic.wait_http(f"http://127.0.0.1:{fixture_server}", timeout_s=10, interval_s=0.2)
    assert ok is True
    assert "HTTP" in last


def test_wait_http_timeout() -> None:
    t0 = time.time()
    ok, last = fic.wait_http("http://127.0.0.1:1/none", timeout_s=1.5, interval_s=0.2)
    assert ok is False
    assert time.time() - t0 < 6  # 有界轮询，不无限等待
    assert last  # 有状态摘要


@pytest.fixture
def fixture_server():
    """临时 HTTP 服务器（200 on /health）。"""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *a):  # noqa: D102
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield port
    srv.shutdown()


# ---------- check-json ----------

def test_check_json_ok(tmp_path) -> None:
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"generated_at_iso": "x", "tz": "Asia/Shanghai", "db": {}}))
    ok, msg = fic.check_json_file(str(p), ["generated_at_iso", "tz", "db"])
    assert ok is True
    assert "字段齐全" in msg


def test_check_json_missing_field(tmp_path) -> None:
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"generated_at_iso": "x"}))
    ok, msg = fic.check_json_file(str(p), ["generated_at_iso", "db"])
    assert ok is False
    assert "db" in msg


def test_check_json_invalid(tmp_path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    ok, msg = fic.check_json_file(str(p), ["a"])
    assert ok is False


# ---------- check-no-cst（回归守卫） ----------

def test_check_no_cst_pass_and_fail(tmp_path) -> None:
    p = tmp_path / "log.txt"
    p.write_text("dashboard started OK")
    ok, _ = fic.check_no_cst(str(p))
    assert ok is True
    # 真实 NameError 格式（带引号）
    p.write_text("state.db unreadable: name 'CST' is not defined")
    ok, msg = fic.check_no_cst(str(p))
    assert ok is False
    assert "CST" in msg


# ---------- owned-process cleanup ----------

_spawned: list[subprocess.Popen] = []


def _spawn_sleeper() -> int:
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _spawned.append(p)
    return p.pid


@pytest.fixture(autouse=True)
def _reap_spawned():
    yield
    for p in _spawned:
        if p.poll() is None:
            p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:  # noqa: BLE001
            pass
    _spawned.clear()


def test_cleanup_owned_process(tmp_path) -> None:
    pid = _spawn_sleeper()
    assert fic._proc_alive(pid)
    fic.cleanup_owned([pid])
    time.sleep(0.5)
    assert not fic._proc_alive(pid)  # owned 进程被精确回收（僵尸视为已退出）


def test_cleanup_ignores_unrelated_process() -> None:
    """只清理传入的 owned PID；未传入的无关进程绝不触碰。"""
    owned = _spawn_sleeper()      # 传入 cleanup → 应被回收
    unrelated = _spawn_sleeper()  # 不传入 → 必须存活
    fic.cleanup_owned([owned])
    time.sleep(0.5)
    assert not fic._proc_alive(owned)
    assert fic._proc_alive(unrelated)  # 无关进程未受影响


def test_cleanup_nonexistent_pid_ok() -> None:
    fic.cleanup_owned([99999999])  # 不存在的 PID 不崩溃


def test_no_broad_kill_in_tool() -> None:
    """工具代码不得调用 killall / pkill（文档说明文字除外）。"""
    import re as _re
    src = Path(fic.__file__).read_text(encoding="utf-8")
    # 命令调用模式（killall / pkill 后随空格或引号）——docstring 的 "killall/pkill" 不算
    assert not _re.search(r"\bkillall[\s\"']", src)
    assert not _re.search(r"\bpkill[\s\"']", src)


# ---------- log redaction ----------

def test_redact_config_removes_secrets(tmp_path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "plugins:\n  enabled: [hermes-hud]\n"
        "telegram:\n  bot_token: 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef\n"
        "api_key: sk-live-abcdefghijklmnopqrstuvwxyz123456\n"
        "url: https://user:pass@example.com/x\n", encoding="utf-8")
    out = fic.redact_config(str(cfg))
    assert "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef" not in out
    assert "sk-live-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "user:pass@" not in out
    assert "[REDACTED]" in out
    assert "hermes-hud" in out  # 非敏感内容保留


def test_redact_config_writes_out_file(tmp_path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("token: abcdef123456\n", encoding="utf-8")
    out_file = tmp_path / "redacted.yaml"
    fic.redact_config(str(cfg), str(out_file))
    assert "abcdef123456" not in out_file.read_text(encoding="utf-8")
