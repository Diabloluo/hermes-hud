#!/usr/bin/env python3
"""安全的一次性 Chrome 捕获工具（Safe One-Off Chrome Launcher）。

杜绝裸启动系统 Chrome 的问题：
  - 独立临时 user-data-dir（绝不触碰用户默认 profile）
  - 动态空闲 CDP port（不固定 9222）
  - proc 句柄 + 独立进程组（PGID=pid，可精确回收 owned process group）
  - try/finally：无论成功/异常/超时，都精确清理 owned 进程组 + 删除临时 profile
  - 禁止 killall/pkill（只回收本工具创建并拥有的进程）

用法：
  python3 safe_chrome_capture.py <url>
  python3 safe_chrome_capture.py <url> --out /tmp/shot.png   # 顺便截图

启动参数（安全模板）：
  --headless=new
  --user-data-dir=<独立临时目录>
  --remote-debugging-port=<动态端口>
  --no-first-run
  --no-default-browser-check
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_READY_TIMEOUT_S = 25
TERM_GRACE_S = 6


def find_free_port() -> int:
    """让 OS 分配一个空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_cdp_ready(port: int, timeout: float = CDP_READY_TIMEOUT_S) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    return False


def terminate_owned(proc: subprocess.Popen, pgid: int,
                    grace: float = TERM_GRACE_S) -> None:
    """精确回收本工具拥有的进程组：SIGTERM → bounded wait → SIGKILL（仅 owned PGID）。"""
    if proc.poll() is not None:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def cdp_screenshot(port: int, out: str, timeout: float = 20.0) -> int:
    """通过 CDP Page.captureScreenshot 截图（需 websockets 库）。"""
    import asyncio
    import base64
    import json as _json

    import websockets

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as resp:
        pages = _json.load(resp)
    ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")

    async def snap() -> int:
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            await ws.send(_json.dumps({
                "id": 1, "method": "Page.captureScreenshot",
                "params": {"format": "png", "captureBeyondViewport": True}}))
            while True:
                msg = _json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if msg.get("id") == 1:
                    data = base64.b64decode(msg["result"]["data"])
                    with open(out, "wb") as fh:
                        fh.write(data)
                    return len(data)

    return asyncio.run(snap())


def capture(url: str, out: str | None) -> dict:
    with tempfile.TemporaryDirectory(prefix="hud-safe-chrome-") as profile:
        port = find_free_port()
        cmd = [
            CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}",
            "--no-first-run", "--no-default-browser-check",
            "--window-size=1680,1050",
        ]
        cmd.append(url)

        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)  # 新进程组：PGID == pid，便于精确回收
        pgid = proc.pid
        info = {"cdp_port": port, "pid": proc.pid, "profile": profile,
                "ready": False, "screenshot": out}
        try:
            if not wait_cdp_ready(port):
                raise RuntimeError("CDP 未在时限内就绪")
            info["ready"] = True
            if out:
                bytes_written = cdp_screenshot(port, out)
                info["screenshot_bytes"] = bytes_written
        finally:
            terminate_owned(proc, pgid)
        return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="要打开的 URL（http/https 或 file://）")
    ap.add_argument("--out", default=None, help="可选：截图输出路径（PNG）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    info = capture(args.url, args.out)
    if args.json:
        print(json.dumps(info, ensure_ascii=False))
    else:
        print(f"CDP port={info['cdp_port']} pid={info['pid']} ready={info['ready']}")
        print(f"临时 profile 已清理: {info['profile']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
