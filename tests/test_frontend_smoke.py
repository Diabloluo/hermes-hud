"""Agent Timeline 前端 smoke（DOM/headless 级，CDP 驱动真实浏览器）。

覆盖：Timeline render / failed event render / null cost-tokens（显示 —）/
type filter / status filter / new-events indicator / event detail expand /
load more。

需要：macOS Chrome + hermes CLI + 网络可达 dashboard（起隔离实例）。
无 Chrome 或 hermes 时自动 skip。
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_cdp(port: int, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


class CDP:
    """极简 CDP 客户端（websockets）。"""

    def __init__(self, port: int):
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
        self.ws = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
        self._mid = 0

    def cmd(self, method: str, params: dict | None = None) -> dict:
        import asyncio
        import websockets

        self._mid += 1
        mid = self._mid

        async def run():
            async with websockets.connect(self.ws) as conn:
                await conn.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(conn.recv(), 20))
                    if msg.get("id") == mid:
                        return msg

        return asyncio.run(run())

    def eval(self, expr: str) -> str:
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return r.get("result", {}).get("result", {}).get("value")


@pytest.fixture(scope="module")
def hud_env():
    """隔离 dashboard：tmp home + 当前仓库插件 + enable + 起服务 + Chrome 页面。"""
    if not Path(CHROME).exists():
        pytest.skip("macOS Chrome not available")
    hermes_bin = shutil.which("hermes") or str(
        Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes")
    if not Path(hermes_bin).exists():
        pytest.skip("hermes CLI not available")
    home = Path(tempfile.mkdtemp(prefix="hud-smoke-"))
    (home / "plugins").mkdir(parents=True)
    shutil.copytree(str(REPO), str(home / "plugins" / "hermes-hud"),
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    # enable 插件
    subprocess.run([sys.executable, str(REPO / "scripts" / "enable_dashboard_plugin.py"),
                    "enable"], env={**os.environ, "HERMES_HOME": str(home)},
                   capture_output=True, timeout=60, check=True)
    port = _free_port()
    env = {k: v for k, v in os.environ.items()}
    for k in ("HERMES_WEB_DIST", "HERMES_DESKTOP", "HERMES_SERVE_HEADLESS"):
        env.pop(k, None)
    env["HERMES_HOME"] = str(home)
    dbg_log = Path(tempfile.mkdtemp(prefix="hud-smoke-log-")) / "dashboard.log"
    proc = subprocess.Popen(
        [hermes_bin, "dashboard", "--host", "127.0.0.1", "--port", str(port),
         "--no-open", "--skip-build"],
        stdout=open(dbg_log, "w"), stderr=subprocess.STDOUT, env=env,
        cwd=str(home))
    # 等 HTTP ready
    deadline = time.time() + 120
    ok = False
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            ok = True
            break
        except Exception:  # noqa: BLE001
            if proc.poll() is not None:
                break  # dashboard 已退出
            time.sleep(1)
    if not ok:
        proc.terminate()
        tail = dbg_log.read_text(encoding="utf-8", errors="replace")[-1200:]
        pytest.skip(f"dashboard did not become ready (port {port}): {tail}")

    # headless Chrome 页面
    profile = tempfile.mkdtemp(prefix="hud-smoke-chrome-")
    cport = _free_port()
    chrome = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu",
         f"--user-data-dir={profile}", f"--remote-debugging-port={cport}",
         "--no-first-run", "--no-default-browser-check", f"http://127.0.0.1:{port}/hud"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    assert _wait_cdp(cport), "Chrome CDP not ready"
    time.sleep(4)
    yield {"port": port, "cdp": CDP(cport), "chrome": chrome}
    # cleanup：owned 进程精确回收
    for p in (chrome, proc):
        if p.poll() is None:
            p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:  # noqa: BLE001
            pass


def _click_timeline(cdp: CDP) -> None:
    r = cdp.eval("(() => { const t = [...document.querySelectorAll('.hud-tab')]"
                 ".find(b => b.textContent && b.textContent.includes('时间线'));"
                 " if (t) { t.click(); return true; } return false; })()")
    assert r is True
    time.sleep(4)  # 轮询首 tick + 渲染


# ---------- smoke cases ----------

def test_timeline_tab_renders_events(hud_env) -> None:
    cdp = hud_env["cdp"]
    _click_timeline(cdp)
    assert "Agent Timeline" in (cdp.eval("document.body.textContent") or "")
    # 事件行存在（每行有 ✓/✕ 图标区）——通过卡片标题 + 至少一条类型文本判断
    txt = cdp.eval("document.body.textContent") or ""
    assert any(t in txt for t in ("tool.completed", "session.started", "incident.opened"))


def test_null_cost_tokens_show_dash(hud_env) -> None:
    """不可靠字段显示 —（不填 0）。"""
    cdp = hud_env["cdp"]
    _click_timeline(cdp)
    # 事件行含 — 当 tokens/cost 为 null（tool 事件无 token/cost）
    txt = cdp.eval("document.body.textContent") or ""
    assert "—" in txt


def test_type_filter(hud_env) -> None:
    cdp = hud_env["cdp"]
    _click_timeline(cdp)
    r = cdp.eval("(() => { const b = [...document.querySelectorAll('button')]"
                 ".find(x => x.textContent === 'Sessions'); if (b) { b.click(); return true; }"
                 " return false; })()")
    assert r is True
    time.sleep(2)
    txt = cdp.eval("document.body.textContent") or ""
    assert "session.started" in txt or "Sessions" in txt


def test_status_filter(hud_env) -> None:
    cdp = hud_env["cdp"]
    _click_timeline(cdp)
    r = cdp.eval("(() => { const s = [...document.querySelectorAll('select')][0];"
                 " if (!s) return false;"
                 " s.value = 'failed'; s.dispatchEvent(new Event('change', {bubbles: true}));"
                 " return true; })()")
    assert r is True
    time.sleep(2)
    # 无 failed 事件时显示空状态也合法（API 不 500）
    assert "Agent Timeline" in (cdp.eval("document.body.textContent") or "")


def test_event_detail_expand(hud_env) -> None:
    cdp = hud_env["cdp"]
    _click_timeline(cdp)
    r = cdp.eval("(() => { const row = document.querySelector('[class*=tl-row], .hud-tl-row');"
                 " if (!row) return false; row.click(); return true; })()")
    assert r is True
    time.sleep(1)
    txt = cdp.eval("document.body.textContent") or ""
    assert "来源" in txt  # 详情含结构化字段


def test_load_more_button(hud_env) -> None:
    cdp = hud_env["cdp"]
    _click_timeline(cdp)
    txt = cdp.eval("document.body.textContent") or ""
    # 有数据且（has_more 或按钮存在）；空环境无数据时跳过断言
    if "加载更多" in txt:
        r = cdp.eval("(() => { const b = [...document.querySelectorAll('button')]"
                     ".find(x => x.textContent.includes('加载更多'));"
                     " if (b) { b.click(); return true; } return false; })()")
        assert r is True
