"""Hermes HUD — 健康规则引擎。

输入 build_snapshot() 的原始采集结果，输出：
  - overall: normal / warning / critical
  - checks:  每条规则的明细（status, severity, message, key）
  - incidents: 本次触发的活跃事故（供落盘/时间线）

规则分三级：
  critical: Gateway 不存活 / 心跳>60s / DB 不可读 / 磁盘<5% / cron 连续失败>=3
  warning : 渠道抖动 / 错误速率升高 / launchd 脱管 / 磁盘<15% / 内存压力 / 预算>80%

预算与阈值集中在这里，后续可改为从 config 读取（当前 MVP 用常量 + 环境变量覆盖）。

i18n: checks[].message 按 locale 渲染（zh 原文不变，en/fr/ar 见 i18n.py）。
locale 由调用方（plugin_api.py，读取请求的 locale query param）传入，
默认 "zh" 保持历史行为不变。

事故文案分两套（见 _inc_text）：incidents[].title/detail 恒为 zh —— 它们
是落盘 telemetry.db、state_changes 判定与 hud_alert 的 canonical 依据，
不能随请求语言漂移；incidents[].display_title/display_detail 才按 locale
渲染，仅供当前响应展示（不落盘）。
"""

from __future__ import annotations

import os
import time
from typing import Any

from .i18n import t

# 阈值（可被 HUD_* 环境变量覆盖）
DISK_FREE_CRITICAL = float(os.environ.get("HUD_DISK_CRITICAL", "5"))
DISK_FREE_WARN = float(os.environ.get("HUD_DISK_WARN", "15"))
MEM_PRESSURE_WARN = float(os.environ.get("HUD_MEM_WARN", "85"))
HEARTBEAT_CRITICAL = float(os.environ.get("HUD_HEARTBEAT_CRITICAL", "60"))
ERROR_BURST_WARN = int(os.environ.get("HUD_ERROR_BURST", "20"))  # 30min 错误数
CYCLE_FAIL_CRITICAL = int(os.environ.get("HUD_CYCLE_FAIL", "3"))
DAILY_BUDGET_USD = float(os.environ.get("HUD_DAILY_BUDGET", "0"))  # 0 = 未配置
BUDGET_WARN_RATIO = 0.8


def _sev(level: str) -> str:
    return level  # "normal" / "warning" / "critical"


def _inc_text(title_key: str, detail_key: str | None, locale: str, *,
              detail_raw: str | None = None, **kwargs: Any) -> dict:
    """Incident title/detail: canonical zh (persisted to telemetry.db, drives
    state_changes and hud_alert) plus display_title/display_detail rendered
    for the request locale (presentation only, never persisted).

    ``detail_raw`` bypasses the template lookup for text that isn't
    translated to begin with (e.g. a raw DB error string) — canonical and
    display detail are then the same value.
    """
    title_zh = t(title_key, "zh", **kwargs)
    title_disp = t(title_key, locale, **kwargs)
    if detail_raw is not None:
        detail_zh = detail_disp = detail_raw
    else:
        detail_zh = t(detail_key, "zh", **kwargs)
        detail_disp = t(detail_key, locale, **kwargs)
    return {"title": title_zh, "detail": detail_zh,
            "display_title": title_disp, "display_detail": detail_disp}


def evaluate_snapshot(snap: dict, locale: str = "zh") -> dict:
    checks: list[dict] = []
    incidents: list[dict] = []
    now = time.time()

    gw = snap.get("gateway") or {}

    # ---- critical: Gateway 存活 ----
    gw_alive = bool(gw.get("alive")) and gw.get("state") == "running"
    checks.append({
        "key": "gateway_alive",
        "status": _sev("normal" if gw_alive else "critical"),
        "severity": "critical" if not gw_alive else "normal",
        "message": t("gateway_alive", locale, pid=gw.get("pid"))
        if gw_alive else t("gateway_not_alive", locale, state=gw.get("state")),
    })
    if not gw_alive:
        incidents.append({
            "fingerprint": "gateway:not-alive",
            "severity": "critical",
            **_inc_text("gateway_not_alive_title", "gateway_not_alive_detail", locale,
                        pid=gw.get("pid"), state=gw.get("state")),
        })

    # ---- warning: 状态文件陈旧（gateway_state.json 只在状态变化时写盘，
    # 不是周期心跳 —— 进程存活才是 critical 依据，实测见 2026-08-23）----
    hb_age = gw.get("heartbeat_age")
    if hb_age is not None:
        hb_ok = hb_age <= HEARTBEAT_CRITICAL
        checks.append({
            "key": "gateway_heartbeat",
            "status": _sev("normal" if hb_ok else "warning"),
            "severity": "warning" if not hb_ok else "normal",
            "message": t("gateway_heartbeat_ok", locale, age=int(hb_age)),
        })
        if not hb_ok:
            incidents.append({
                "fingerprint": "gateway:stale-state-file",
                "severity": "warning",
                **_inc_text("gateway_stale_title", "gateway_stale_detail", locale, age=int(hb_age)),
            })
    else:
        checks.append({"key": "gateway_heartbeat", "status": "warning", "severity": "warning",
                       "message": t("gateway_heartbeat_missing", locale)})

    # ---- critical: DB 可读 ----
    db = snap.get("db") or {}
    db_ok = db.get("error") is None
    checks.append({
        "key": "db_readable",
        "status": _sev("normal" if db_ok else "critical"),
        "severity": "critical" if not db_ok else "normal",
        "message": t("db_ok", locale) if db_ok else t("db_error", locale, error=db.get("error")),
    })
    if not db_ok:
        # db["error"] 已按请求语言渲染，只能进 display_detail；canonical detail
        # 由与语言无关的 error_key/error_args 按 zh 渲染（见 collectors.collect_db）。
        # 没带 error_key 的调用方沿用原始 error 文本。
        if db.get("error_key"):
            text = _inc_text("db_unreadable_title", db["error_key"], locale,
                             **(db.get("error_args") or {}))
        else:
            text = _inc_text("db_unreadable_title", None, locale, detail_raw=str(db.get("error")))
        text["detail"] = text["detail"][:200]
        text["display_detail"] = text["display_detail"][:200]
        incidents.append({
            "fingerprint": "db:unreadable",
            "severity": "critical",
            **text,
        })

    # ---- critical/warning: 磁盘 ----
    disk_free = (snap.get("system") or {}).get("disk_free_percent")
    if disk_free is not None:
        if disk_free < DISK_FREE_CRITICAL:
            checks.append({"key": "disk", "status": "critical", "severity": "critical",
                           "message": t("disk_low", locale, free=disk_free, threshold=DISK_FREE_CRITICAL)})
            incidents.append({"fingerprint": "disk:critical", "severity": "critical",
                              **_inc_text("disk_critical_title", "disk_free_detail", locale,
                                          free=disk_free)})
        elif disk_free < DISK_FREE_WARN:
            checks.append({"key": "disk", "status": "warning", "severity": "warning",
                           "message": t("disk_low", locale, free=disk_free, threshold=DISK_FREE_WARN)})
            incidents.append({"fingerprint": "disk:warn", "severity": "warning",
                              **_inc_text("disk_warn_title", "disk_free_detail", locale,
                                          free=disk_free)})
        else:
            checks.append({"key": "disk", "status": "normal", "severity": "normal",
                           "message": t("disk_ok", locale, free=disk_free)})
    else:
        checks.append({"key": "disk", "status": "warning", "severity": "warning",
                       "message": t("disk_unavailable", locale)})

    # ---- warning: 内存压力 ----
    mem = (snap.get("system") or {}).get("memory") or {}
    if mem.get("percent") is not None:
        mem_ok = mem["percent"] < MEM_PRESSURE_WARN
        checks.append({
            "key": "memory",
            "status": _sev("normal" if mem_ok else "warning"),
            "severity": "warning" if not mem_ok else "normal",
            "message": t("memory_usage", locale, pct=mem["percent"]),
        })
        if not mem_ok:
            incidents.append({"fingerprint": "mem:pressure", "severity": "warning",
                              **_inc_text("memory_pressure_title", "memory_pressure_detail", locale,
                                          pct=mem["percent"])})
    else:
        checks.append({"key": "memory", "status": "warning", "severity": "warning",
                       "message": t("memory_unavailable", locale)})

    # ---- warning: 渠道抖动 / 异常 ----
    platforms = gw.get("platforms") or {}
    for name, p in platforms.items():
        state = p.get("state")
        age = p.get("heartbeat_age")
        needs_attn = p.get("needs_attention")
        if state == "connected" and needs_attn:
            checks.append({"key": f"channel:{name}", "status": "warning", "severity": "warning",
                           "message": t("channel_attention", locale, name=name)})
            incidents.append({"fingerprint": f"channel:{name}:attention", "severity": "warning",
                              **_inc_text("channel_attention_title", "channel_attention_detail",
                                          locale, name=name)})
        elif state != "connected":
            checks.append({"key": f"channel:{name}", "status": "critical", "severity": "critical",
                           "message": t("channel_disconnected", locale, name=name, state=state)})
            incidents.append({"fingerprint": f"channel:{name}:{state}", "severity": "critical",
                              **_inc_text("channel_disconnected_title", "channel_disconnected_detail",
                                          locale, name=name, state=state)})
        elif age is not None and age > HEARTBEAT_CRITICAL:
            checks.append({"key": f"channel:{name}", "status": "warning", "severity": "warning",
                           "message": t("channel_stale", locale, name=name, age=int(age))})
            incidents.append({"fingerprint": f"channel:{name}:stale", "severity": "warning",
                              **_inc_text("channel_stale_title", "channel_stale_detail",
                                          locale, name=name, age=int(age))})
        else:
            checks.append({"key": f"channel:{name}", "status": "normal", "severity": "normal",
                           "message": t("channel_ok", locale, name=name)})

    # ---- warning: 错误速率 ----
    err = snap.get("errors") or {}
    err_count = err.get("count_30m", 0)
    if err.get("error"):
        checks.append({"key": "error_burst", "status": "warning", "severity": "warning",
                       "message": t("errors_log_unavailable", locale)})
    elif err_count > ERROR_BURST_WARN:
        checks.append({"key": "error_burst", "status": "warning", "severity": "warning",
                       "message": t("error_burst", locale, count=err_count, threshold=ERROR_BURST_WARN)})
        incidents.append({"fingerprint": "logs:error-burst", "severity": "warning",
                          **_inc_text("error_burst_title", "recent_errors_count", locale,
                                      count=err_count)})
    else:
        checks.append({"key": "error_burst", "status": "normal", "severity": "normal",
                       "message": t("recent_errors_count", locale, count=err_count)})

    # ---- warning: launchd 脱管 ----
    ld = snap.get("launchd") or {}
    if ld.get("status") == "not_applicable":
        # 非 macOS：launchd 概念不适用，不算告警
        checks.append({"key": "launchd", "status": "normal", "severity": "normal",
                       "message": t("launchd_na", locale)})
    elif ld.get("managed"):
        checks.append({"key": "launchd", "status": "normal", "severity": "normal",
                       "message": t("launchd_managed", locale)})
    else:
        checks.append({"key": "launchd", "status": "warning", "severity": "warning",
                       "message": t("launchd_unmanaged_plist" if ld.get("plist_exists")
                                    else "launchd_unmanaged_noplist", locale)})
        incidents.append({"fingerprint": "launchd:not-managed", "severity": "warning",
                          **_inc_text("launchd_incident_title",
                                      "launchd_detail_plist_exists" if ld.get("plist_exists")
                                      else "launchd_detail_missing", locale)})

    # ---- warning: Dashboard 未常驻 ----
    dash = snap.get("dashboard") or {}
    dash_procs = dash.get("procs") or []
    if dash_procs:
        checks.append({"key": "dashboard", "status": "normal", "severity": "normal",
                       "message": t("dashboard_running", locale, n=len(dash_procs))})
    else:
        checks.append({"key": "dashboard", "status": "warning", "severity": "warning",
                       "message": t("dashboard_not_running", locale)})
        incidents.append({"fingerprint": "dashboard:not-running", "severity": "warning",
                          **_inc_text("dashboard_not_running", "dashboard_not_running_detail",
                                      locale)})

    # ---- critical: Cron 连续失败 ----
    cron = snap.get("cron") or {}
    for j in cron.get("jobs", []):
        streak = j.get("failure_streak") or 0
        if streak >= CYCLE_FAIL_CRITICAL:
            checks.append({"key": f"cron:{j['id']}", "status": "critical", "severity": "critical",
                           "message": t("cron_fail_critical", locale, name=j["name"], streak=streak)})
            # 指纹稳定：不随 streak 变化（cron:<id>:fail），同一任务连续失败
            # 保持同一条事故生命周期；streak 放进 detail
            # The "no error recorded" placeholder is itself translated, so the
            # canonical and the display detail need their own rendering of it.
            raw_error = j.get("last_error") or j.get("last_delivery_error")
            incidents.append({
                "fingerprint": f"cron:{j['id']}:fail", "severity": "critical",
                "title": t("cron_fail_title", "zh", name=j["name"]),
                "detail": t("cron_fail_detail", "zh", streak=streak,
                            last_error=raw_error or t("none_value", "zh")),
                "display_title": t("cron_fail_title", locale, name=j["name"]),
                "display_detail": t("cron_fail_detail", locale, streak=streak,
                                    last_error=raw_error or t("none_value", locale)),
            })
        elif streak >= 1:
            checks.append({"key": f"cron:{j['id']}", "status": "warning", "severity": "warning",
                           "message": t("cron_fail_warn", locale, name=j["name"], streak=streak)})
    # 有失败 streak 的任务若没有其他检查项，给个兜底 normal（避免空）
    for j in cron.get("jobs", []):
        key = f"cron:{j['id']}"
        if not any(c["key"] == key for c in checks):
            checks.append({"key": key, "status": "normal", "severity": "normal",
                           "message": t("cron_ok", locale, name=j["name"])})

    # ---- warning: 预算 ----
    today = (snap.get("db") or {}).get("today_sessions") or {}
    today_cost = today.get("estimated_cost_usd") or 0  # C-1: 仅 canonical estimated，unpriced 不进入
    if DAILY_BUDGET_USD > 0 and today_cost > DAILY_BUDGET_USD * BUDGET_WARN_RATIO:
        checks.append({"key": "budget", "status": "warning", "severity": "warning",
                       "message": t("budget_over", locale, cost=today_cost, budget=DAILY_BUDGET_USD,
                                    pct=BUDGET_WARN_RATIO * 100)})
        incidents.append({"fingerprint": "budget:daily", "severity": "warning",
                          **_inc_text("budget_incident_title", "budget_incident_detail", locale,
                                      cost=today_cost, budget=DAILY_BUDGET_USD)})
    elif DAILY_BUDGET_USD > 0:
        checks.append({"key": "budget", "status": "normal", "severity": "normal",
                       "message": t("budget_ok_with_budget", locale, cost=today_cost, budget=DAILY_BUDGET_USD)})
    else:
        checks.append({"key": "budget", "status": "normal", "severity": "normal",
                       "message": t("budget_ok_no_budget", locale, cost=today_cost)})

    # ---- 汇总 ----
    severity_order = {"normal": 0, "warning": 1, "critical": 2}
    worst = max((severity_order[c["severity"]] for c in checks), default=0)
    overall = {0: "normal", 1: "warning", 2: "critical"}[worst]
    counts = {
        "critical": sum(1 for c in checks if c["severity"] == "critical"),
        "warning": sum(1 for c in checks if c["severity"] == "warning"),
        "normal": sum(1 for c in checks if c["severity"] == "normal"),
    }
    return {
        "overall": overall,
        "counts": counts,
        "checks": checks,
        "incidents": incidents,
        "evaluated_at": now,
    }
