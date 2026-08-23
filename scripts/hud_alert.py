#!/usr/bin/env python3
"""Hermes HUD — 事故主动推送告警（Telegram + 飞书）。

独立于 dashboard 进程运行：直接读 telemetry.db 的活跃事故，
检测到新事故 / 严重度升级 / 持续恶化 / 恢复时推送消息。

- 幂等：状态文件 ~/.hermes/hud/alerts_state.json 记录已推送指纹，
  同一事故默认不重复推；持续恶化（触发次数 +10）且距上次推送 > 30 分钟才再推。
- 网络：Telegram API 走 Clash 127.0.0.1:7897 代理（被墙）；飞书直连。
- 用法：
    python3 hud_alert.py            # 正常运行（推送 + 静默 stdout）
    python3 hud_alert.py --dry-run  # 只打印将推送的内容，不实际发送
    python3 hud_alert.py --once     # 强制推送当前全部活跃事故（忽略防抖）
退出码 0 = 成功；异常时非零并输出错误（供 cron 兜底告警）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
TELEMETRY_DB = HERMES_HOME / "hud" / "telemetry.db"
STATE_FILE = HERMES_HOME / "hud" / "alerts_state.json"
ENV_FILE = HERMES_HOME / ".env"

# 防抖参数
MIN_REPUSH_INTERVAL = 1800    # 30 分钟
COUNT_ESCALATION_STEP = 10    # 触发次数再增加 10 才考虑重推
MAX_PUSH_PER_RUN = 5          # 单次最多推送条数（防风暴）

PROXY = os.environ.get("HUD_TG_PROXY") or None  # 默认无代理；仅用户显式配置时启用（如 http://127.0.0.1:7897）


# ---------------------------------------------------------------------------
# 环境变量（最小权限：只加载 allowlist，不把 .env 全部变量写入进程环境）
# ---------------------------------------------------------------------------

_ENV_ALLOWLIST = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_HOME_CHANNEL",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_ALLOWED_USERS",
    "HUD_TG_PROXY",
}


def _load_env() -> None:
    """只把通知所需的 allowlisted 凭证从 .env 加载进环境，其他变量不碰。"""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k in _ENV_ALLOWLIST:
            os.environ.setdefault(k, v.strip())


def _get(key: str) -> str:
    return os.environ.get(key, "")


# ---------------------------------------------------------------------------
# telemetry 读取
# ---------------------------------------------------------------------------

def _active_incidents() -> list[dict]:
    """读 telemetry.db 活跃事故。"""
    if not TELEMETRY_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{TELEMETRY_DB}?mode=ro", uri=True, timeout=3)
        # state_changes 列在 v1.0.0 旧库可能不存在：查列后按需选择 SQL
        cols = [r[1] for r in conn.execute("PRAGMA table_info(incidents)").fetchall()]
        has_sc = "state_changes" in cols
        sel = ("fingerprint, severity, title, detail, first_seen, last_seen, count"
               + (", state_changes" if has_sc else ", 0"))
        rows = conn.execute(
            f"SELECT {sel} FROM incidents WHERE status IN ('active','pending_recovery')"
        ).fetchall()
        conn.close()
        out = []
        for r in rows:
            inc = {"fingerprint": r[0], "severity": r[1], "title": r[2], "detail": r[3] or "",
                   "first_seen": r[4], "last_seen": r[5], "count": r[6]}
            if has_sc:
                inc["state_changes"] = r[7]
            out.append(inc)
        return out
    except Exception as exc:
        print(f"ERROR: 读取 telemetry.db 失败: {exc}", file=sys.stderr)
        return []


def _all_incident_fingerprints() -> set[str]:
    """所有事故指纹（含已恢复），用于检测恢复。"""
    if not TELEMETRY_DB.exists():
        return set()
    try:
        conn = sqlite3.connect(f"file:{TELEMETRY_DB}?mode=ro", uri=True, timeout=3)
        rows = conn.execute("SELECT fingerprint FROM incidents").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# 推送（Telegram + 飞书）
# ---------------------------------------------------------------------------

def _http(url: str, data: bytes | None = None, headers: dict | None = None,
          proxy: str | None = None, timeout: float = 15) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy, "http": proxy}) if proxy else urllib.request.ProxyHandler({})
    )
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _push_telegram(text: str) -> bool:
    token = _get("TELEGRAM_BOT_TOKEN")
    chat_id = _get("TELEGRAM_HOME_CHANNEL")
    if not token or not chat_id:
        print("ERROR: 缺少 TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL", file=sys.stderr)
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    try:
        r = _http(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"},
                  proxy=PROXY)
        return bool(r.get("ok"))
    except Exception as exc:
        print(f"ERROR: Telegram 推送失败: {exc}", file=sys.stderr)
        return False


def _push_feishu(text: str) -> bool:
    app_id = _get("FEISHU_APP_ID")
    app_secret = _get("FEISHU_APP_SECRET")
    user_id = _get("FEISHU_ALLOWED_USERS")
    if not app_id or not app_secret or not user_id:
        print("ERROR: 缺少 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_ALLOWED_USERS", file=sys.stderr)
        return False
    try:
        token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        tr = _http(token_url, data=json.dumps(
            {"app_id": app_id, "app_secret": app_secret}).encode(),
            headers={"Content-Type": "application/json"})
        access_token = tr.get("tenant_access_token")
        if not access_token:
            print(f"ERROR: 飞书 token 获取失败: {tr}", file=sys.stderr)
            return False
        msg_url = ("https://open.feishu.cn/open-apis/im/v1/messages"
                   "?receive_id_type=open_id")
        payload = json.dumps({
            "receive_id": user_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }).encode()
        mr = _http(msg_url, data=payload,
                   headers={"Content-Type": "application/json",
                            "Authorization": f"Bearer {access_token}"})
        return mr.get("code") == 0
    except Exception as exc:
        print(f"ERROR: 飞书推送失败: {exc}", file=sys.stderr)
        return False


def push_all(text: str) -> tuple[bool, bool]:
    tg_ok = _push_telegram(text)
    fs_ok = _push_feishu(text)
    return tg_ok, fs_ok


# ---------------------------------------------------------------------------
# 告警决策
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as exc:
        print(f"ERROR: 状态文件写入失败: {exc}", file=sys.stderr)


def _fmt_incident(inc: dict, kind: str) -> str:
    sev = "🔴 故障" if inc["severity"] == "critical" else "🟡 警告"
    action = {"new": "新事故", "upgrade": "严重度升级", "repeat": "持续恶化", "recover": "已恢复"}.get(kind, kind)
    lines = [
        f"Hermes HUD {action}",
        f"{sev} · {inc['title']}",
    ]
    if inc.get("detail"):
        lines.append(inc["detail"])
    lines.append(f"触发 {inc.get('count', 1)} 次 · 最近 {time.strftime('%m/%d %H:%M', time.localtime(inc.get('last_seen', time.time())))}")
    return "\n".join(lines)


# push item 直接携带 fingerprint（不通过消息正文反查）：
#   {"fingerprint": ..., "kind": ..., "text": ...}
def run(dry_run: bool = False, force: bool = False) -> int:
    _load_env()
    now = int(time.time())
    active = _active_incidents()
    active_fps = {a["fingerprint"] for a in active}
    all_fps = _all_incident_fingerprints()
    state = _load_state()

    pushes: list[dict] = []  # {"fingerprint", "kind", "text"}

    for inc in active:
        fp = inc["fingerprint"]
        prev = state.get(fp)
        kind = None
        if prev is None:
            kind = "new"
        elif prev.get("status") == "recovered":
            kind = "new"  # 已恢复后再次出现 = 新事故
        elif force:
            kind = "repeat"
        elif inc["severity"] != prev.get("severity"):
            kind = "upgrade"
        elif (prev.get("state_changes") is not None
              and inc.get("state_changes", 0) - prev.get("state_changes", 0) >= 1
              and now - prev.get("last_push", 0) >= MIN_REPUSH_INTERVAL):
            # 实质状态变化（severity/title/detail 变化）且距上次推送足够久；
            # prev 无 state_changes 键（v1.0.0 旧状态文件）时不触发，避免 0→1 误判
            kind = "repeat"
        elif (inc["count"] - prev.get("count", 0) >= COUNT_ESCALATION_STEP
              and now - prev.get("last_push", 0) >= MIN_REPUSH_INTERVAL):
            kind = "repeat"
        if kind:
            pushes.append({"fingerprint": fp, "kind": kind, "text": _fmt_incident(inc, kind)})

    # 恢复状态机：active → 发送 recovery → 至少一渠道成功 → recovered
    # 所有渠道失败 → pending_recovery，下一轮继续尝试；禁止“没发出去却标已恢复”
    for fp, prev in state.items():
        if fp in active_fps:
            # 事故仍存在：pending_recovery 状态回归 active（不重复推 new）
            if prev.get("status") == "pending_recovery":
                state[fp]["status"] = "active"
            continue
        if prev.get("status") not in ("active", "pending_recovery"):
            continue  # 已 recovered 且未再现
        if fp not in all_fps:
            continue  # telemetry 里已彻底删除（超保留期），无需通知
        # 需要发恢复通知；限流：距上次尝试至少 60 秒
        if now - prev.get("last_attempt", 0) < 60:
            continue
        pushes.append({
            "fingerprint": fp, "kind": "recover",
            "text": _fmt_incident({
                "fingerprint": fp, "severity": prev.get("severity", "warning"),
                "title": prev.get("title", fp), "detail": prev.get("detail", ""),
                "count": prev.get("count", 1), "last_seen": prev.get("last_push", now)},
                "recover"),
        })

    pushes = pushes[:MAX_PUSH_PER_RUN]

    if dry_run:
        if not pushes:
            print("(无变化，无需推送)")
        for item in pushes:
            print(f"--- [{item['kind']}] {item['fingerprint']} ---\n{item['text']}\n")
        return 0

    for item in pushes:
        fp, kind, text = item["fingerprint"], item["kind"], item["text"]
        tg_ok, fs_ok = push_all(text)
        if tg_ok or fs_ok:
            # 推送成功才更新状态
            if kind == "recover":
                state[fp]["status"] = "recovered"
                state[fp]["last_push"] = now
                state[fp].pop("last_attempt", None)
            else:
                inc = next((a for a in active if a["fingerprint"] == fp), None)
                state[fp] = {
                    "severity": inc["severity"] if inc else "warning",
                    "count": inc["count"] if inc else 0,
                    "state_changes": inc.get("state_changes", 0) if inc else 0,
                    "last_push": now,
                    "status": "active",
                    "title": inc["title"] if inc else "",
                    "detail": inc["detail"] if inc else "",
                }
        else:
            # 所有渠道失败：恢复消息保持 pending_recovery（下轮重试），
            # 新事故保持未记录（下轮重推）—— 绝不写 recovered
            if kind == "recover":
                state[fp]["status"] = "pending_recovery"
                state[fp]["last_attempt"] = now
            print(f"ERROR: 推送失败（TG/飞书均失败）: {text.splitlines()[0]}", file=sys.stderr)

    _save_state(state)

    if not pushes:
        print(f"OK: 无新告警（活跃事故 {len(active)} 条）", file=sys.stderr)  # stderr 不触发 cron 投递
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes HUD 事故推送")
    ap.add_argument("--dry-run", action="store_true", help="只打印不发送")
    ap.add_argument("--once", action="store_true", help="强制推送当前全部活跃事故")
    args = ap.parse_args()
    try:
        return run(dry_run=args.dry_run, force=args.once)
    except Exception as exc:
        print(f"ERROR: 未捕获异常: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
