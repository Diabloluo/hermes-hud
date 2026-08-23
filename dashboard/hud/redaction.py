"""Hermes HUD — 脱敏工具。

日志、错误摘要、投递目标在进入 telemetry.db / WebSocket 之前必须经过这里。
规则分两类：
  1. 关键字扫描：key/token/secret/password/bearer/cookie/authorization/api_key 等
     字段名之后的引号值（单引号/双引号/冒号空格），整段替换。
  2. 模式扫描：sk-[A-Za-z0-9]、Bearer <token>、eyJ...JWT、URI 中的 query 凭据。

不读取 .env / auth.json，只对已经拿到的字符串做替换。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------

# 关键字引号值：key="xxx" / key='xxx' / key: "xxx" / key=xxx(非空白) / key:xxx
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token"
    r"|secret|secret[_-]?key|client[_-]?secret|password|passwd|pwd"
    r"|bearer|authorization|cookie|session[_-]?token|webhook[_-]?url|token)\b"
    r"\s*[:=]\s*[\"']?[^\"'\s,;}]{4,}"
)

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}", re.I)
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")
_SK_RE = re.compile(r"\bsk-[a-zA-Z0-9_-]{8,}\b")
_TG_BOT_RE = re.compile(r"\b\d{8,10}:[a-zA-Z0-9_-]{30,}\b")
_URI_QUERY_SECRET_RE = re.compile(r"([?&](?:token|key|secret|password|auth|access_token|ticket)=)[^&#\s]{4,}")
_LONG_HEX_RE = re.compile(r"\b[0-9a-f]{32,}\b")
_LONG_B64_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")

REDACTED = "[REDACTED]"


def redact_line(text: str) -> str:
    """对单行文本执行全部脱敏规则。"""
    if not text:
        return text
    out = text
    out = _KEY_VALUE_RE.sub(lambda m: m.group(0).split("=", 1)[0].split(":", 1)[0].rstrip() + "=" + REDACTED, out)
    out = _BEARER_RE.sub(REDACTED, out)
    out = _JWT_RE.sub(REDACTED, out)
    out = _SK_RE.sub(REDACTED, out)
    out = _TG_BOT_RE.sub(REDACTED, out)
    out = _URI_QUERY_SECRET_RE.sub(lambda m: m.group(1) + REDACTED, out)
    out = _LONG_HEX_RE.sub(REDACTED, out)
    out = _LONG_B64_RE.sub(REDACTED, out)
    return out


def redact_many(lines: list[str], max_lines: int = 200) -> list[str]:
    return [redact_line(x)[:500] for x in lines[:max_lines]]


# ---------------------------------------------------------------------------
# 日志指纹（事故去重用）
# ---------------------------------------------------------------------------

def fingerprint(line: str) -> str:
    """把一行日志归一化为指纹：去掉时间戳、数字、路径、行号。

    用于把“同一种异常”聚合为一条事故，而不是按每条日志铺开。
    """
    s = line.strip()
    # 去掉 ISO 时间戳
    s = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?", "", s)
    s = re.sub(r"\d{4}-\d{2}-\d{2}", "", s)
    s = re.sub(r"\d{2}:\d{2}:\d{2}", "", s)
    s = re.sub(r"\b0x[0-9a-fA-F]+\b", "", s)
    s = re.sub(r"\b\d+\b", "", s)
    s = re.sub(r"[/\\][a-zA-Z0-9._-]+(?:[/\\][a-zA-Z0-9._-]+)+", "[path]", s)
    s = re.sub(r"\s+", " ", s).strip()
    # 截断到 120 字符，超过部分丢弃（尾部通常是具体参数）
    return s[:120]
