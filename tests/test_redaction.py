"""P0-1/P0-2 脱敏与指纹测试。

验收标准：任何测试 secret 均不得出现在 redact_line() 输出中；
fingerprint 必须先脱敏再归一化，secret 不得进入指纹。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.hud.redaction import fingerprint, redact_line, redact_obj, redact_many

# ---------------------------------------------------------------------------
# 测试 secret 集合（审计要求逐一覆盖）
# ---------------------------------------------------------------------------

BEARER_TOKEN = "ab" * 10  # 低熵重复模式（避免 secret 扫描误报）
SK_SECRET = "sk-" + "test-" + "aaaabbbb"
JWT_SECRET = ("eyJ" + "aaa" * 6 + "." + "bbb" * 6 + "." + "ccc" * 6)
TG_BOT_SECRET = "123456789:" + "A" * 35
API_KEY_SECRET = "aaabbbccc"
ACCESS_TOKEN_SECRET = "aaaabbbbcccc"
CLIENT_SECRET_SECRET = "aaaabbbb"
WEBHOOK_URL = ("https://" + "hooks.slack.com/services/"
              "T" + "0" * 8 + "/B" + "0" * 8 + "/X" + "X" * 24)
LONG_HEX_SECRET = "aabbccdd" * 8
LONG_B64_SECRET = ("QUJDRA" * 9) + "="
COOKIE_SECRET = "session=" + "aaaabbbbcccc"
QUERY_SECRETS = ("?token=aaaa&key=bbbb&secret=cccc&"
                "pass" + "word=dddd&auth=eeee&ticket=ffff")
HOST_SECRET = "https://user:abcd@example.com/api"

# 断言中出现的所有 secret 字符串（用于"0 occurrence"检查）
ALL_SECRETS = [
    BEARER_TOKEN, SK_SECRET, JWT_SECRET, TG_BOT_SECRET, API_KEY_SECRET,
    ACCESS_TOKEN_SECRET, CLIENT_SECRET_SECRET, WEBHOOK_URL, LONG_HEX_SECRET,
    LONG_B64_SECRET, COOKIE_SECRET, "aaaabbbbcccc", "aaaa", "bbbb",
    "cccc", "dddd", "eeee", "ffff", "abcd",
]


def assert_no_secret(text: str) -> None:
    for s in ALL_SECRETS:
        assert s not in text, f"泄漏: {s!r} 出现在输出中: {text!r}"


# ---------------------------------------------------------------------------
# P0-1 基础规则
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    f"Authorization: Bearer {BEARER_TOKEN}",
    f"authorization=Bearer {BEARER_TOKEN}",
    f"X-Auth: bearer {BEARER_TOKEN}",
    f'Authorization: Bearer {BEARER_TOKEN} done',
])
def test_bearer(line: str) -> None:
    out = redact_line(line)
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_bearer_token_not_left_behind() -> None:
    """审计核心：不能先吃掉 Bearer 字样却把 token 留在后面。"""
    line = f"Authorization: Bearer {BEARER_TOKEN}"
    out = redact_line(line)
    assert BEARER_TOKEN not in out
    assert "Bearer" not in out or "Bearer " not in out  # Bearer 字样不得单独残留
    assert out.count("[REDACTED]") >= 1


@pytest.mark.parametrize("line", [
    f'"token":"{ACCESS_TOKEN_SECRET}"',
    f'"api_key":"{API_KEY_SECRET}"',
    f'"access_token":"{ACCESS_TOKEN_SECRET}"',
    f"'client_secret': '{CLIENT_SECRET_SECRET}'",
    f'client_secret="{CLIENT_SECRET_SECRET}"',
    f"token='{ACCESS_TOKEN_SECRET}'",
    f'secret_key: "{CLIENT_SECRET_SECRET}"',
])
def test_json_quoted_keys(line: str) -> None:
    out = redact_line(line)
    assert_no_secret(out)
    assert "[REDACTED]" in out


@pytest.mark.parametrize("line", [
    f"token={ACCESS_TOKEN_SECRET}",
    f"api_key={API_KEY_SECRET}",
    f"access_token: {ACCESS_TOKEN_SECRET}",
    f"pass" + f"word={API_KEY_SECRET}",
    f"client_secret={CLIENT_SECRET_SECRET}",
    f"webhook_url={WEBHOOK_URL}",
])
def test_unquoted_values(line: str) -> None:
    out = redact_line(line)
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_sk_pattern() -> None:
    out = redact_line(f"model key is {SK_SECRET} here")
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_jwt_pattern() -> None:
    out = redact_line(f"payload {JWT_SECRET} end")
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_telegram_bot_pattern() -> None:
    out = redact_line(f"bot {TG_BOT_SECRET} sendMessage")
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_cookie_header() -> None:
    out = redact_line(f"cookie: {COOKIE_SECRET}; path=/; HttpOnly")
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_uri_query_secrets() -> None:
    out = redact_line(f"https://example.com/api{QUERY_SECRETS}")
    assert_no_secret(out)
    assert out.count("[REDACTED]") >= 6


def test_webhook_url_key() -> None:
    out = redact_line(f'webhook_url: "{WEBHOOK_URL}"')
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_long_hex() -> None:
    out = redact_line(f"hash {LONG_HEX_SECRET} tail")
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_long_base64() -> None:
    out = redact_line(f"token {LONG_B64_SECRET} tail")
    assert_no_secret(out)
    assert "[REDACTED]" in out


def test_url_userinfo() -> None:
    """URL user:pass@ 形式的凭据。"""
    out = redact_line(f"conn {HOST_SECRET}")
    assert "abcd" not in out


def test_redact_many() -> None:
    lines = [f"INFO ok", f"ERROR token={API_KEY_SECRET}", f"WARN x"]
    out = redact_many(lines)
    assert_no_secret("\n".join(out))
    assert len(out) == 3


def test_redact_obj() -> None:
    obj = {
        "token": ACCESS_TOKEN_SECRET,
        "nested": {"api_key": API_KEY_SECRET},
        "list": [f"Bearer {BEARER_TOKEN}", "plain"],
        "num": 42,
    }
    out = redact_obj(obj)
    flat = str(out)
    assert_no_secret(flat)
    assert "[REDACTED]" in flat
    assert out["num"] == 42  # 非字符串保持


def test_redact_obj_does_not_mutate() -> None:
    obj = {"token": ACCESS_TOKEN_SECRET}
    redact_obj(obj)
    assert obj["token"] == ACCESS_TOKEN_SECRET  # 原对象不变


# ---------------------------------------------------------------------------
# P0-2 fingerprint 必须在脱敏后生成
# ---------------------------------------------------------------------------

def test_fingerprint_contains_no_secret() -> None:
    line = f"2026-08-23 12:00:00 ERROR Lark connect failed token={ACCESS_TOKEN_SECRET}"
    fp = fingerprint(line)
    assert_no_secret(fp)


def test_fingerprint_stable_after_redaction() -> None:
    """同一类错误（不同 secret 值）应得到同一指纹。"""
    fp1 = fingerprint(f"ERROR request failed token={API_KEY_SECRET}")
    fp2 = fingerprint(f"ERROR request failed token={ACCESS_TOKEN_SECRET}")
    assert fp1 == fp2


def test_fingerprint_strips_timestamps_and_numbers() -> None:
    fp = fingerprint("2026-08-23 12:34:56 ERROR boom 12345")
    assert "2026" not in fp
    assert "12:34" not in fp
    assert "12345" not in fp


def test_fingerprint_paths_normalized() -> None:
    fp1 = fingerprint("ERROR open /Users/alice/.hermes/x failed")
    fp2 = fingerprint("ERROR open /Users/bob/.hermes/y failed")
    assert fp1 == fp2
