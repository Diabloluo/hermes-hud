"""Hermes HUD — 健康规则引擎。

输入 build_snapshot() 的原始采集结果，输出：
  - overall: normal / warning / critical
  - checks:  每条规则的明细（status, severity, message, key）
  - incidents: 本次触发的活跃事故（供落盘/时间线）

规则分三级：
  critical: Gateway 不存活 / 心跳>60s / DB 不可读 / 磁盘<5% / cron 连续失败>=3
  warning : 渠道抖动 / 错误速率升高 / launchd 脱管 / 磁盘<15% / 内存压力 / 预算>80%

预算与阈值集中在这里，后续可改为从 config 读取（当前 MVP 用常量 + 环境变量覆盖）。
"""

from __future__ import annotations

import os
import time
from typing import Any

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


def evaluate_snapshot(snap: dict) -> dict:
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
        "message": ("Gateway 运行中 (PID %s)" % gw.get("pid"))
        if gw_alive else ("Gateway 不存活! state=%s" % gw.get("state")),
    })
    if not gw_alive:
        incidents.append({
            "fingerprint": "gateway:not-alive",
            "severity": "critical",
            "title": "Gateway 不存活",
            "detail": "gateway_state.json: pid=%s state=%s" % (gw.get("pid"), gw.get("state")),
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
            "message": "状态文件 %ds 前更新 (进程存活)" % int(hb_age),
        })
        if not hb_ok:
            incidents.append({
                "fingerprint": "gateway:stale-state-file",
                "severity": "warning",
                "title": "Gateway 状态文件陈旧",
                "detail": "状态文件 %d 秒无更新（进程仍存活）" % int(hb_age),
            })
    else:
        checks.append({"key": "gateway_heartbeat", "status": "warning", "severity": "warning",
                       "message": "心跳数据缺失（gateway_state.json 无 updated_at）"})

    # ---- critical: DB 可读 ----
    db = snap.get("db") or {}
    db_ok = db.get("error") is None
    checks.append({
        "key": "db_readable",
        "status": _sev("normal" if db_ok else "critical"),
        "severity": "critical" if not db_ok else "normal",
        "message": "state.db 只读正常" if db_ok else ("state.db 不可读: %s" % db.get("error")),
    })
    if not db_ok:
        incidents.append({
            "fingerprint": "db:unreadable",
            "severity": "critical",
            "title": "state.db 不可读",
            "detail": str(db.get("error"))[:200],
        })

    # ---- critical/warning: 磁盘 ----
    disk_free = (snap.get("system") or {}).get("disk_free_percent")
    if disk_free is not None:
        if disk_free < DISK_FREE_CRITICAL:
            checks.append({"key": "disk", "status": "critical", "severity": "critical",
                           "message": "磁盘剩余 %.1f%% < %.0f%%" % (disk_free, DISK_FREE_CRITICAL)})
            incidents.append({"fingerprint": "disk:critical", "severity": "critical",
                              "title": "磁盘空间告急",
                              "detail": "剩余 %.1f%%" % disk_free})
        elif disk_free < DISK_FREE_WARN:
            checks.append({"key": "disk", "status": "warning", "severity": "warning",
                           "message": "磁盘剩余 %.1f%% < %.0f%%" % (disk_free, DISK_FREE_WARN)})
            incidents.append({"fingerprint": "disk:warn", "severity": "warning",
                              "title": "磁盘空间偏低", "detail": "剩余 %.1f%%" % disk_free})
        else:
            checks.append({"key": "disk", "status": "normal", "severity": "normal",
                           "message": "磁盘剩余 %.1f%%" % disk_free})
    else:
        checks.append({"key": "disk", "status": "warning", "severity": "warning",
                       "message": "磁盘数据不可用"})

    # ---- warning: 内存压力 ----
    mem = (snap.get("system") or {}).get("memory") or {}
    if mem.get("percent") is not None:
        mem_ok = mem["percent"] < MEM_PRESSURE_WARN
        checks.append({
            "key": "memory",
            "status": _sev("normal" if mem_ok else "warning"),
            "severity": "warning" if not mem_ok else "normal",
            "message": "内存使用 %.0f%%" % mem["percent"],
        })
        if not mem_ok:
            incidents.append({"fingerprint": "mem:pressure", "severity": "warning",
                              "title": "内存压力", "detail": "使用率 %.0f%%" % mem["percent"]})
    else:
        checks.append({"key": "memory", "status": "warning", "severity": "warning",
                       "message": "内存数据不可用"})

    # ---- warning: 渠道抖动 / 异常 ----
    platforms = gw.get("platforms") or {}
    for name, p in platforms.items():
        state = p.get("state")
        age = p.get("heartbeat_age")
        needs_attn = p.get("needs_attention")
        if state == "connected" and needs_attn:
            checks.append({"key": f"channel:{name}", "status": "warning", "severity": "warning",
                           "message": f"{name}: 已连接但 needs_attention 标记"})
            incidents.append({"fingerprint": f"channel:{name}:attention", "severity": "warning",
                              "title": f"{name} 连接不稳定", "detail": "connected 但带 needs_attention"})
        elif state != "connected":
            checks.append({"key": f"channel:{name}", "status": "critical", "severity": "critical",
                           "message": f"{name}: 状态={state}"})
            incidents.append({"fingerprint": f"channel:{name}:{state}", "severity": "critical",
                              "title": f"{name} 断开", "detail": "state=%s" % state})
        elif age is not None and age > HEARTBEAT_CRITICAL:
            checks.append({"key": f"channel:{name}", "status": "warning", "severity": "warning",
                           "message": f"{name}: connected 但心跳 {int(age)}s 过期"})
            incidents.append({"fingerprint": f"channel:{name}:stale", "severity": "warning",
                              "title": f"{name} 心跳过期", "detail": "connected 但 %ds 无更新" % int(age)})
        else:
            checks.append({"key": f"channel:{name}", "status": "normal", "severity": "normal",
                           "message": f"{name}: connected"})

    # ---- warning: 错误速率 ----
    err = snap.get("errors") or {}
    err_count = err.get("count_30m", 0)
    if err.get("error"):
        checks.append({"key": "error_burst", "status": "warning", "severity": "warning",
                       "message": "errors.log 不可用"})
    elif err_count > ERROR_BURST_WARN:
        checks.append({"key": "error_burst", "status": "warning", "severity": "warning",
                       "message": f"近30分钟 {err_count} 条错误 > {ERROR_BURST_WARN}"})
        incidents.append({"fingerprint": "logs:error-burst", "severity": "warning",
                          "title": "错误速率升高", "detail": f"近30分钟 {err_count} 条错误"})
    else:
        checks.append({"key": "error_burst", "status": "normal", "severity": "normal",
                       "message": f"近30分钟 {err_count} 条错误"})

    # ---- warning: launchd 脱管 ----
    ld = snap.get("launchd") or {}
    if ld.get("status") == "not_applicable":
        # 非 macOS：launchd 概念不适用，不算告警
        checks.append({"key": "launchd", "status": "normal", "severity": "normal",
                       "message": "launchd 不适用（非 macOS）"})
    elif ld.get("managed"):
        checks.append({"key": "launchd", "status": "normal", "severity": "normal",
                       "message": "Gateway 由 launchd 托管"})
    else:
        checks.append({"key": "launchd", "status": "warning", "severity": "warning",
                       "message": "Gateway 未由 launchd 托管"
                                   + ("（plist 存在但未加载）" if ld.get("plist_exists") else "（无服务定义）")})
        incidents.append({"fingerprint": "launchd:not-managed", "severity": "warning",
                          "title": "Gateway 脱离 launchd 托管",
                          "detail": "服务定义 %s" % ("存在但未加载" if ld.get("plist_exists") else "缺失")})

    # ---- warning: Dashboard 未常驻 ----
    dash = snap.get("dashboard") or {}
    dash_procs = dash.get("procs") or []
    if dash_procs:
        checks.append({"key": "dashboard", "status": "normal", "severity": "normal",
                       "message": f"Dashboard 运行中 ({len(dash_procs)} 进程)"})
    else:
        checks.append({"key": "dashboard", "status": "warning", "severity": "warning",
                       "message": "Dashboard 未运行"})
        incidents.append({"fingerprint": "dashboard:not-running", "severity": "warning",
                          "title": "Dashboard 未运行",
                          "detail": "无 hermes web server 进程"})

    # ---- critical: Cron 连续失败 ----
    cron = snap.get("cron") or {}
    for j in cron.get("jobs", []):
        streak = j.get("failure_streak") or 0
        if streak >= CYCLE_FAIL_CRITICAL:
            checks.append({"key": f"cron:{j['id']}", "status": "critical", "severity": "critical",
                           "message": f"任务「{j['name']}」连续失败 {streak} 次"})
            # 指纹稳定：不随 streak 变化（cron:<id>:fail），同一任务连续失败
            # 保持同一条事故生命周期；streak 放进 detail
            incidents.append({"fingerprint": f"cron:{j['id']}:fail", "severity": "critical",
                              "title": f"Cron 连续失败: {j['name']}",
                              "detail": "连续失败 %d 次, 最近错误: %s" % (streak, j.get("last_error") or j.get("last_delivery_error") or "无")})
        elif streak >= 1:
            checks.append({"key": f"cron:{j['id']}", "status": "warning", "severity": "warning",
                           "message": f"任务「{j['name']}」失败 {streak} 次"})
    # 有失败 streak 的任务若没有其他检查项，给个兜底 normal（避免空）
    for j in cron.get("jobs", []):
        key = f"cron:{j['id']}"
        if not any(c["key"] == key for c in checks):
            checks.append({"key": key, "status": "normal", "severity": "normal",
                           "message": f"任务「{j['name']}」正常"})

    # ---- warning: 预算 ----
    today = (snap.get("db") or {}).get("today_sessions") or {}
    today_cost = (today.get("estimated_cost_usd") or 0) + (today.get("aux_est_cost") or 0)
    if DAILY_BUDGET_USD > 0 and today_cost > DAILY_BUDGET_USD * BUDGET_WARN_RATIO:
        checks.append({"key": "budget", "status": "warning", "severity": "warning",
                       "message": "今日估算费用 $%.2f 超过日预算 $%.2f 的 %.0f%%"
                       % (today_cost, DAILY_BUDGET_USD, BUDGET_WARN_RATIO * 100)})
        incidents.append({"fingerprint": "budget:daily", "severity": "warning",
                          "title": "今日费用超预算 80%",
                          "detail": "今日估算 $%.2f / 日预算 $%.2f" % (today_cost, DAILY_BUDGET_USD)})
    else:
        checks.append({"key": "budget", "status": "normal", "severity": "normal",
                       "message": "今日估算 $%.2f%s" % (today_cost,
                       " / 预算 $%.2f" % DAILY_BUDGET_USD if DAILY_BUDGET_USD > 0 else " (未配置预算)")})

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
