"""Hermes HUD — 脱敏工具。

日志、错误摘要、投递目标在进入 telemetry.db / WebSocket / API 之前必须经过这里。

规则设计（顺序即安全）：
  1. 模式规则先行：Bearer/JWT/sk-*/Telegram bot token/长 hex/base64 —— 整体替换，
     确保"先匹配掉 Bearer 字样却把真正 token 留在后面"这类截断泄漏不会发生。
  2. 键值规则：
     a. 引号值（JSON quoted keys）："token":"xxxx" / 'client_secret': 'xxxx' / key="xxx"
     b. 无引号值：token=xxx / authorization: xxx（值到空白/分隔符为止）
  3. URL query 中的 token/key/secret/password/auth/ticket 参数。
  4. Authorization/Cookie 整行兜底。

不读取 .env / auth.json，只对已经拿到的字符串做替换。
"""

from __future__ import annotations

import re
from pathlib import Path

REDACTED = "[REDACTED]"

# ---------------------------------------------------------------------------
# 模式规则（整体替换，顺序在键值规则之前）
# ---------------------------------------------------------------------------

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")
_SK_RE = re.compile(r"\bsk-[a-zA-Z0-9_-]{8,}\b")
_TG_BOT_RE = re.compile(r"\b\d{8,10}:[a-zA-Z0-9_-]{30,}\b")
_LONG_HEX_RE = re.compile(r"\b[0-9a-f]{32,}\b")
_LONG_B64_RE = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")

# ---------------------------------------------------------------------------
# 键值规则
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = (
    r"api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token"
    r"|secret|secret[_-]?key|client[_-]?secret|password|passwd|pwd"
    r"|bearer|authorization|proxy-authorization|cookie|set-cookie"
    r"|session[_-]?token|webhook[_-]?url|webhook|token|ticket|auth|credential|signature"
)

# key="xxx" / "key":"xxx" / 'key': 'xxx' / key='xxx'
_QUOTED_VALUE_RE = re.compile(
    rf'(?i)(["\']?)\b({_SENSITIVE_KEYS})\b\1\s*[:=]\s*["\']([^"\']{{2,}})["\']'
)
# key=xxx / key: xxx（值到空白/引号/逗号/分号/右花括号/& 为止）
_UNQUOTED_VALUE_RE = re.compile(
    rf'(?i)\b({_SENSITIVE_KEYS})\b\s*[:=]\s*([^\s"\',;}}&]{{2,}})'
)
# 敏感键名（redact_obj 中 dict 键匹配用）
_SENSITIVE_KEY_RE = re.compile(rf"(?i)\b({_SENSITIVE_KEYS})\b")
# URL query 参数
_URI_QUERY_SECRET_RE = re.compile(
    r"([?&](?:token|key|secret|password|auth|access_token|ticket|signature|api_key)=)[^&#\s]{2,}"
)
# URL userinfo：scheme://user:pass@host —— 密码部分脱敏
_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/@\s]{0,128}:)([^@\s/]{2,})(@)")
# Authorization / Cookie 整行兜底（无论值形态如何都整行替换）
_AUTH_LINE_RE = re.compile(
    r"(?im)^\s*(authorization|proxy-authorization|cookie|set-cookie)\s*[:=].*$"
)


def _quoted_sub(m: re.Match) -> str:
    """保留 key 与分隔符，替换引号内的值（组偏移相对 group(0)）。"""
    rel = m.start(3) - m.start(0)
    return m.group(0)[:rel] + REDACTED + m.group(0)[m.end(3) - m.start(0):]


def _unquoted_sub(m: re.Match) -> str:
    """保留 key 与分隔符（含 = 或 :），替换值（组偏移相对 group(0)）。"""
    rel = m.start(2) - m.start(0)
    return m.group(0)[:rel] + REDACTED


def _url_userinfo_sub(m: re.Match) -> str:
    s2 = m.start(2) - m.start(0)
    e2 = m.end(2) - m.start(0)
    return m.group(0)[:s2] + REDACTED + m.group(0)[e2:]


def redact_line(text: str) -> str:
    """对单行文本执行全部脱敏规则。

    顺序安全论证：
      - 模式规则先于键值规则，因此 `Authorization: Bearer <token>` 会先被
        _BEARER_RE 整体替换，键值规则不可能先吃掉 "Bearer" 字样而留下 token。
      - 引号值规则先于无引号值规则，JSON `"token":"xxxx"` 不会因无引号规则
        只替换一半。
      - 键值规则不可能破坏模式规则的结果（REDACTED 不含可再匹配的内容）。
    """
    if not text:
        return text
    out = text
    out = _BEARER_RE.sub(REDACTED, out)
    out = _JWT_RE.sub(REDACTED, out)
    out = _SK_RE.sub(REDACTED, out)
    out = _TG_BOT_RE.sub(REDACTED, out)
    out = _LONG_HEX_RE.sub(REDACTED, out)
    out = _LONG_B64_RE.sub(REDACTED, out)
    out = _QUOTED_VALUE_RE.sub(_quoted_sub, out)
    out = _UNQUOTED_VALUE_RE.sub(_unquoted_sub, out)
    out = _URI_QUERY_SECRET_RE.sub(lambda m: m.group(1) + REDACTED, out)
    out = _URL_USERINFO_RE.sub(_url_userinfo_sub, out)
    out = _AUTH_LINE_RE.sub(lambda m: m.group(1) + ": " + REDACTED, out)
    return out


def redact_many(lines: list[str], max_lines: int = 200) -> list[str]:
    """批量脱敏（每个输出行截断到 500 字符）。"""
    return [redact_line(x)[:500] for x in lines[:max_lines]]


def redact_obj(obj):
    """递归脱敏 dict / list / str 中的全部字符串（不修改原始对象）。

    - dict：敏感键名（token/api_key/secret/password/...）的值整体替换为
      REDACTED（无论值形态，孤立字符串值不依赖模式匹配）；
      其余键递归处理。
    - list/tuple：逐项递归。
    - str：redact_line。
    - 其他类型原样返回。
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SENSITIVE_KEY_RE.search(k):
                out[k] = REDACTED if v is not None else v
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact_line(obj)
    return obj


# ---------------------------------------------------------------------------
# 隐私工具：本地路径 / 命令行摘要
# ---------------------------------------------------------------------------

def sanitize_path(path: str) -> str:
    """本地绝对路径 → 脱敏形式。

    /Users/<username>/... 与 $HOME 前缀 → ~/...
    第三方路径保留必要尾部（隐藏中间目录名）。
    """
    if not path:
        return path
    s = str(path)
    try:
        home = str(Path.home())
        if s.startswith(home):
            return "~" + s[len(home):]
    except Exception:
        pass
    # 任何 /Users/<name> 或 /home/<name> 开头 → ~/（不泄露用户名）
    s = re.sub(r"^/(Users|home)/[^/]+", "~", s)
    # 第三方绝对路径：只留前两段和后两段
    tilde = s.startswith("~")
    body = s[2:] if tilde else s
    parts = [p for p in body.replace("\\", "/").split("/") if p]
    if len(parts) > 5:
        head = ("~/" if tilde else "/") + "/".join(parts[:2])
        s = head + "/.../" + "/".join(parts[-2:])
    # 路径内嵌凭据（如 cwd 含 token）也要脱敏
    return redact_line(s)


def sanitize_cmdline(cmd: str, max_len: int = 200) -> str:
    """命令行摘要：先脱敏路径 + 凭据，再截断。"""
    if not cmd:
        return cmd
    return redact_line(sanitize_path(cmd))[:max_len]


# ---------------------------------------------------------------------------
# 日志指纹（事故去重用）—— 必须在脱敏之后生成
# ---------------------------------------------------------------------------

def fingerprint(line: str) -> str:
    """把一行日志归一化为指纹（先脱敏再指纹）。

    调用方必须保证输入 raw line，本函数内部先 redact_line：
      raw line → redact_line → 归一化（去时间戳/数字/路径/行号）→ 指纹
    这样任何 secret 都不会进入 fingerprint / incident 聚合。
    """
    s = redact_line(line).strip()
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
