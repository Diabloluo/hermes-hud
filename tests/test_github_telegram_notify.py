"""GitHub 社区通知 → Telegram 单元测试。

在测试进程内 import 脚本并调用 main()（不 subprocess），mock
urllib.request.urlopen —— 零真实网络访问。
覆盖：Star / Issue / Fork / workflow_dispatch / HTML 转义 /
缺失字段降级 / Secret 缺失 / Telegram 失败（timeout、重试有界）。
"""

from __future__ import annotations

import json
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import github_telegram_notify as gtn  # noqa: E402

REPO = "Diabloluo/hermes-hud"


def _payload_star(login="alice", stars=12, with_stars=True, with_url=True) -> dict:
    d = {
        "action": "started",
        "sender": {"login": login, "html_url": f"https://github.com/{login}" if with_url else None},
        "repository": {"full_name": REPO},
    }
    if with_stars:
        d["repository"]["stargazers_count"] = stars
    return d


def _payload_issue(num=7, title="Dashboard fails on Ubuntu 24.04", login="bob") -> dict:
    return {
        "action": "opened",
        "sender": {"login": login, "html_url": f"https://github.com/{login}"},
        "issue": {
            "number": num,
            "title": title,
            "html_url": f"https://github.com/{REPO}/issues/{num}",
        },
    }


def _payload_fork(login="carol", full_name="carol/hermes-hud") -> dict:
    return {
        "sender": {"login": login, "html_url": f"https://github.com/{login}"},
        "forkee": {"full_name": full_name,
                   "html_url": f"https://github.com/{full_name}"},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    ev = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token-123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    calls: list = []

    def fake_urlopen(req, timeout=15):
        calls.append(json.loads(req.data.decode("utf-8")))
        resp = mock.MagicMock()
        resp.status = 200
        resp.__enter__.return_value = resp
        return resp

    monkeypatch.setattr(gtn.urllib.request, "urlopen", fake_urlopen)
    return {"ev": ev, "calls": calls, "mp": monkeypatch}


def _run_main(env, payload, event) -> int:
    env["ev"].write_text(json.dumps(payload), encoding="utf-8")
    env["mp"].setenv("GITHUB_EVENT_NAME", event)
    try:
        gtn.main()
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)


# ---- Star ----

def test_star_message_contents(env) -> None:
    assert _run_main(env, _payload_star(), "watch") == 0
    assert len(env["calls"]) == 1  # 一次 run 至多一条消息
    text = env["calls"][0]["text"]
    assert "⭐ New Star — Hermes HUD" in text
    assert "@alice starred Diabloluo/hermes-hud" in text
    assert "⭐ Total stars: 12" in text
    assert "https://github.com/alice" in text


def test_star_missing_stars_count(env) -> None:
    assert _run_main(env, _payload_star(with_stars=False), "watch") == 0
    assert "Total stars: unavailable" in env["calls"][0]["text"]


def test_star_missing_sender_url(env) -> None:
    assert _run_main(env, _payload_star(with_url=False), "watch") == 0
    assert "GitHub:" not in env["calls"][0]["text"]


# ---- Issue ----

def test_issue_message_contents(env) -> None:
    assert _run_main(env, _payload_issue(), "issues") == 0
    text = env["calls"][0]["text"]
    assert "🐛 New Issue #7 — Hermes HUD" in text
    assert "Dashboard fails on Ubuntu 24.04" in text
    assert "Opened by: @bob" in text
    assert "https://github.com/Diabloluo/hermes-hud/issues/7" in text


def test_issue_title_html_escaped(env) -> None:
    assert _run_main(env, _payload_issue(title='Error <script> & "token"'), "issues") == 0
    text = env["calls"][0]["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "&amp;" in text
    assert "&quot;token&quot;" in text or "&#34;token&#34;" in text


# ---- Fork ----

def test_fork_message_contents(env) -> None:
    assert _run_main(env, _payload_fork(), "fork") == 0
    text = env["calls"][0]["text"]
    assert "🍴 New Fork — Hermes HUD" in text
    assert "@carol forked the project" in text
    assert "carol/hermes-hud" in text
    assert "https://github.com/carol/hermes-hud" in text


# ---- workflow_dispatch ----

def test_workflow_dispatch_test_message(env) -> None:
    assert _run_main(env, {}, "workflow_dispatch") == 0
    text = env["calls"][0]["text"]
    assert "🧪 Hermes HUD notification test" in text
    assert "GitHub → Telegram connection is working." in text
    assert "Diabloluo/hermes-hud" in text


# ---- Secret 缺失 ----

def test_missing_bot_token(env, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    with mock.patch("sys.stderr") as _:
        code = _run_main(env, {}, "workflow_dispatch")
    assert code != 0


def test_missing_chat_id(env, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    code = _run_main(env, {}, "workflow_dispatch")
    assert code != 0


# ---- Telegram 失败（有界重试后退出非 0）----

def test_telegram_timeout_fails(env, monkeypatch) -> None:
    def timeout_urlopen(req, timeout=15):
        raise TimeoutError("timed out")
    monkeypatch.setattr(gtn.urllib.request, "urlopen", timeout_urlopen)
    code = _run_main(env, {}, "workflow_dispatch")
    assert code != 0


def test_telegram_retry_bounded(env, monkeypatch) -> None:
    n = {"calls": 0}

    def flaky_urlopen(req, timeout=15):
        n["calls"] += 1
        raise TimeoutError("timed out")
    monkeypatch.setattr(gtn.urllib.request, "urlopen", flaky_urlopen)
    code = _run_main(env, {}, "workflow_dispatch")
    assert code != 0
    assert n["calls"] == 2  # 恰好 2 次尝试


def test_telegram_retry_then_success(env, monkeypatch) -> None:
    n = {"calls": 0}

    def flaky_urlopen(req, timeout=15):
        n["calls"] += 1
        if n["calls"] == 1:
            raise TimeoutError("timed out")
        resp = mock.MagicMock()
        resp.status = 200
        resp.__enter__.return_value = resp
        return resp
    monkeypatch.setattr(gtn.urllib.request, "urlopen", flaky_urlopen)
    code = _run_main(env, {}, "workflow_dispatch")
    assert code == 0
    assert n["calls"] == 2


def test_http_error_fails(env, monkeypatch) -> None:
    def http_error(req, timeout=15):
        raise gtn.urllib.error.HTTPError(
            "https://api.telegram.org", 500, "Server Error", {}, None)
    monkeypatch.setattr(gtn.urllib.request, "urlopen", http_error)
    code = _run_main(env, {}, "workflow_dispatch")
    assert code != 0
