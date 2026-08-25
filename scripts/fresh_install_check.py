#!/usr/bin/env python3
"""fresh_install_check — Fresh Install CI 辅助检查（纯 stdlib，可本地测试）。

子命令：
  wait-http <url> [timeout_s] [interval_s]
      HTTP ready 轮询（禁裸 sleep 作为唯一判断）；就绪返回 0
  check-json <file> <field> [field...]
      验证 JSON 文件可解析且含全部顶层字段；返回 0 否则 1
  check-no-cst <file>
      文件/日志不含 "CST is not defined"；返回 0 否则 1
  cleanup-owned <pid> [pid...]
      精确回收由调用方持有并记录的 PID（SIGTERM → bounded wait → SIGKILL）；
      禁止 killall/pkill（无宽泛杀进程）
  redact-config <file> [out_file]
      对 config 快照脱敏（token/secret/key/cookie/url 值 → [REDACTED]）；
      输出到 stdout 或 out_file
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TERM_GRACE_S = 6


def wait_http(url: str, timeout_s: float = 60, interval_s: float = 1) -> tuple[bool, str]:
    """轮询 URL 直到 HTTP 2xx/3xx 或超时。返回 (ok, 最后状态摘要)。"""
    deadline = time.time() + timeout_s
    last = "not attempted"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                last = f"HTTP {resp.status}"
                if 200 <= resp.status < 400:
                    return True, last
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if 200 <= exc.code < 400:
                return True, last
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}"
        time.sleep(interval_s)
    return False, last


def check_json_file(path: str, fields: list[str]) -> tuple[bool, str]:
    """验证 JSON 文件可解析且含全部顶层字段。"""
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except Exception as exc:  # noqa: BLE001
        return False, f"JSON 解析失败: {exc}"
    if not isinstance(data, dict):
        return False, "顶层不是对象"
    missing = [f for f in fields if f not in data]
    if missing:
        return False, f"缺少字段: {', '.join(missing)}"
    return True, f"字段齐全: {', '.join(fields)}"


def check_no_cst(path: str) -> tuple[bool, str]:
    """回归守卫：内容不得含 CST 未定义错误（覆盖带引号的 NameError 格式）。"""
    text = open(path, encoding="utf-8", errors="replace").read()
    if re.search(r"CST.*is not defined", text):
        return False, "发现 CST is not defined 回归"
    return True, "无 CST 回归"


def cleanup_owned(pids: list[int]) -> None:
    """精确回收 owned PID（由调用方记录并传入）。

    绝不使用 killall/pkill（可能误杀用户正常进程）；只处理传入的 PID。
    探活基于 ps stat（僵尸进程视为已退出）。
    """
    for pid in pids:
        if pid <= 0:
            continue
        try:
            os_kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    # bounded wait
    for pid in pids:
        if pid <= 0:
            continue
        try:
            _wait_loop(pid, TERM_GRACE_S)
        except subprocess.TimeoutExpired:
            try:
                os_kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def os_kill(pid: int, sig: int) -> None:
    import os
    os.kill(pid, sig)


def _proc_alive(pid: int) -> bool:
    """非僵尸探活：ps stat 存在且不含 Z（僵尸已不占活进程）。"""
    try:
        r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=3)
        stat = r.stdout.strip()
        return bool(stat) and "Z" not in stat
    except Exception:  # noqa: BLE001
        return False


def _wait_loop(pid: int, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _proc_alive(pid):
            return
        time.sleep(0.3)
    raise subprocess.TimeoutExpired(f"pid {pid}", timeout)


_REDACT_PATTERNS = [
    (r"(token|secret|password|passwd|api[_-]?key|apikey|authorization|cookie"
     r"|client[_-]?secret|private[_-]?key)\s*[:=]\s*\S+", r"\1: [REDACTED]"),
    (r"sk-[A-Za-z0-9_-]{16,}", "sk-[REDACTED]"),
    (r"ghp_[A-Za-z0-9]{20,}", "ghp_[REDACTED]"),
    (r"https?://[^\s\"']*:[^\s\"']*@", "https://[REDACTED]@"),
    (r"\b[0-9]{8,}:[A-Za-z0-9_-]{30,}\b", "[REDACTED]"),
]


def redact_config(path: str, out_path: str | None = None) -> str | None:
    """对 config 快照脱敏；文件不存在 → 返回 None（调用方 SKIP，不抛 traceback）。"""
    p = Path(path)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    for pat, repl in _REDACT_PATTERNS:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("wait-http")
    w.add_argument("url")
    w.add_argument("timeout", nargs="?", default="60")
    w.add_argument("interval", nargs="?", default="1")

    cj = sub.add_parser("check-json")
    cj.add_argument("file")
    cj.add_argument("fields", nargs="+")

    cc = sub.add_parser("check-no-cst")
    cc.add_argument("file")

    cl = sub.add_parser("cleanup-owned")
    cl.add_argument("pids", nargs="+", type=int)

    rc = sub.add_parser("redact-config")
    rc.add_argument("file")
    rc.add_argument("out", nargs="?", default=None)

    args = ap.parse_args()

    if args.cmd == "wait-http":
        ok, last = wait_http(args.url, float(args.timeout), float(args.interval))
        print(f"wait-http {args.url} -> {'ready' if ok else 'timeout'} ({last})")
        return 0 if ok else 1

    if args.cmd == "check-json":
        ok, msg = check_json_file(args.file, args.fields)
        print(f"check-json {args.file} -> {'PASS' if ok else 'FAIL'}: {msg}")
        return 0 if ok else 1

    if args.cmd == "check-no-cst":
        ok, msg = check_no_cst(args.file)
        print(f"check-no-cst {args.file} -> {'PASS' if ok else 'FAIL'}: {msg}")
        return 0 if ok else 1

    if args.cmd == "cleanup-owned":
        cleanup_owned(args.pids)
        print(f"cleanup-owned {args.pids} -> done (owned only, no killall/pkill)")
        return 0

    if args.cmd == "redact-config":
        out = redact_config(args.file, args.out)
        if out is None:
            print(f"SKIP: config file not present ({args.file})")
            return 0  # 可控状态，无 traceback
        print(out if not args.out else f"redacted -> {args.out}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
# PR source-under-test verification trigger (fresh-install path filter)
