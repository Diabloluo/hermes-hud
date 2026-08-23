#!/usr/bin/env python3
"""GitHub 社区事件 → Telegram 通知（纯 Python 标准库，无第三方依赖）。

在 GitHub Actions 中由 .github/workflows/community-telegram.yml 调用。
事件从 GITHUB_EVENT_PATH（webhook payload JSON）读取；所有用户输入经
html.escape 后才进入 Telegram HTML 消息。

安全约束：
- bot token 只存在于请求 URL 与内存；任何日志/错误信息都不打印 token、
  完整 Telegram URL、请求头或 secret 环境变量。
- 一次 workflow run 至多发一条 Telegram 消息（本脚本只发送一次）。
- 失败：最多 2 次尝试、单次超时 ≤15s，仍失败则退出非 0。
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.request
from typing import NoReturn

TELEGRAM_API = "https://api.telegram.org/bot"  # 不含 token；完整 URL 永不打印


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _fail(msg: str) -> NoReturn:
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def _esc(s: str) -> str:
    """对用户可控文本做 HTML 转义（防 Telegram HTML 注入）。"""
    return html.escape(str(s), quote=True)


def _sender_login(payload: dict) -> str:
    return payload.get("sender", {}).get("login", "unknown")


def _sender_url(payload: dict) -> str:
    return payload.get("sender", {}).get("html_url", "")


def _render_star(payload: dict, repo: str) -> str:
    actor = _esc(_sender_login(payload))
    full = _esc(payload.get("repository", {}).get("full_name", repo))
    stars = payload.get("repository", {}).get("stargazers_count")
    sender_url = _sender_url(payload)

    lines = ["⭐ New Star — Hermes HUD", ""]
    lines.append(f"@{actor} starred {full}")
    lines.append("")
    lines.append(f"⭐ Total stars: {stars if stars is not None else 'unavailable'}")
    if sender_url:
        lines.append("")
        lines.append(f"GitHub: {_esc(sender_url)}")
    return "\n".join(lines)


def _render_issue(payload: dict, repo: str) -> str:
    issue = payload.get("issue", {})
    num = issue.get("number", "?")
    title = _esc(issue.get("title", "(untitled)"))
    actor = _esc(_sender_login(payload))
    url = _esc(issue.get("html_url", f"https://github.com/{repo}/issues/{num}"))
    return "\n".join([
        f"🐛 New Issue #{num} — Hermes HUD", "",
        title, "",
        f"Opened by: @{actor}", "",
        url,
    ])


def _render_fork(payload: dict, repo: str) -> str:
    actor = _esc(_sender_login(payload))
    forkee = payload.get("forkee", {})
    fname = _esc(forkee.get("full_name", f"{actor}/hermes-hud"))
    furl = _esc(forkee.get("html_url", f"https://github.com/{fname}"))
    return "\n".join([
        "🍴 New Fork — Hermes HUD", "",
        f"@{actor} forked the project", "",
        "New repository:", fname, "",
        furl,
    ])


def _render_test(repo: str) -> str:
    return "\n".join([
        "🧪 Hermes HUD notification test", "",
        "GitHub → Telegram connection is working.", "",
        f"Repository:", repo,
    ])


def _render(event: str, payload: dict, repo: str) -> str:
    if event == "watch":  # types: [started]
        return _render_star(payload, repo)
    if event == "issues":  # types: [opened]
        return _render_issue(payload, repo)
    if event == "fork":
        return _render_fork(payload, repo)
    if event == "workflow_dispatch":
        return _render_test(repo)
    _fail(f"不支持的事件类型: {event}")


def _send_telegram(text: str, bot_token: str, chat_id: str,
                   attempts: int = 2, timeout: int = 15) -> None:
    """发送消息；失败信息只含 HTTP 状态或原因类型，绝不打印 token/URL。"""
    url = f"{TELEGRAM_API}{bot_token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode("utf-8")
    last_err = "unknown"
    for _ in range(attempts):
        try:
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    return
                last_err = f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
        except TimeoutError:
            last_err = "timeout"
        except Exception as exc:  # noqa: BLE001 - 统一收敛错误描述
            last_err = type(exc).__name__
    _fail(f"Telegram send failed: {last_err}")


def main() -> int:
    bot = _env("TELEGRAM_BOT_TOKEN")
    chat = _env("TELEGRAM_CHAT_ID")
    if not bot:
        _fail("TELEGRAM_BOT_TOKEN 未设置")
    if not chat:
        _fail("TELEGRAM_CHAT_ID 未设置")

    event = _env("GITHUB_EVENT_NAME")
    event_path = _env("GITHUB_EVENT_PATH")
    repo = _env("GITHUB_REPOSITORY")
    if not event_path or not os.path.exists(event_path):
        _fail("GITHUB_EVENT_PATH 不可用")
    if not event:
        _fail("GITHUB_EVENT_NAME 不可用")

    with open(event_path, encoding="utf-8") as fh:
        payload = json.load(fh)

    text = _render(event, payload, repo)
    _send_telegram(text, bot, chat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
