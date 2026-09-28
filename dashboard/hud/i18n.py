"""Hermes HUD — backend i18n for dynamically generated health/status text.

Companion to the frontend's ``tt()`` (see ``dashboard/dist/index.js``): static
UI chrome (tab labels, table headers, card titles) is translated client-side,
but health-check / incident messages in ``rules.py`` and error strings in
``collectors.py`` are built server-side because they interpolate live values
(PIDs, percentages, counts) that only the backend has.

``zh`` is the original/default language and is left byte-for-byte unchanged.
``en``/``fr``/``ar`` are looked up by key; a locale not covered here (or a key
missing from it) falls back to ``en``, then to the raw key.

Known limitation: health checks/incidents are recomputed fresh on every
``/snapshot`` poll (~2s), so they follow whichever ``locale`` query param the
browser sent on that request — genuinely live. Incidents *persisted* to
``telemetry.db`` (see ``plugin_api._update_telemetry``) keep whatever
language was active on the server the moment they were written; switching
the Dashboard's language later does not retranslate already-stored incident
text. That would need incident storage to move from pre-rendered strings to
structured (key + args), which is a larger change than this patch makes.
"""

from __future__ import annotations

_SUPPORTED = {"zh", "en", "fr", "ar"}

TEMPLATES: dict[str, dict[str, str]] = {
    # -- rules.py: gateway --
    "gateway_alive": {
        "zh": "Gateway 运行中 (PID {pid})",
        "en": "Gateway running (PID {pid})",
        "fr": "Gateway en cours d'exécution (PID {pid})",
        "ar": "Gateway قيد التشغيل (PID {pid})",
    },
    "gateway_not_alive": {
        "zh": "Gateway 不存活! state={state}",
        "en": "Gateway is down! state={state}",
        "fr": "Gateway est arrêtée ! state={state}",
        "ar": "Gateway متوقفة! state={state}",
    },
    "gateway_not_alive_title": {
        "zh": "Gateway 不存活",
        "en": "Gateway is down",
        "fr": "Gateway est arrêtée",
        "ar": "Gateway متوقفة",
    },
    "gateway_not_alive_detail": {
        "zh": "gateway_state.json: pid={pid} state={state}",
        "en": "gateway_state.json: pid={pid} state={state}",
        "fr": "gateway_state.json : pid={pid} state={state}",
        "ar": "gateway_state.json: pid={pid} state={state}",
    },
    "gateway_heartbeat_ok": {
        "zh": "状态文件 {age}s 前更新 (进程存活)",
        "en": "State file updated {age}s ago (process alive)",
        "fr": "Fichier d'état mis à jour il y a {age}s (processus actif)",
        "ar": "تم تحديث ملف الحالة قبل {age} ث (العملية نشطة)",
    },
    "gateway_heartbeat_missing": {
        "zh": "心跳数据缺失（gateway_state.json 无 updated_at）",
        "en": "Heartbeat data missing (gateway_state.json has no updated_at)",
        "fr": "Données de pulsation manquantes (gateway_state.json sans updated_at)",
        "ar": "بيانات النبضة مفقودة (gateway_state.json بدون updated_at)",
    },
    "gateway_stale_title": {
        "zh": "Gateway 状态文件陈旧",
        "en": "Gateway state file is stale",
        "fr": "Fichier d'état Gateway obsolète",
        "ar": "ملف حالة Gateway قديم",
    },
    "gateway_stale_detail": {
        "zh": "状态文件 {age} 秒无更新（进程仍存活）",
        "en": "State file has not updated in {age} seconds (process still alive)",
        "fr": "Le fichier d'état n'a pas été mis à jour depuis {age} secondes (processus toujours actif)",
        "ar": "لم يُحدَّث ملف الحالة منذ {age} ثانية (العملية لا تزال نشطة)",
    },
    # -- rules.py: db --
    "db_ok": {
        "zh": "state.db 只读正常",
        "en": "state.db read-only OK",
        "fr": "state.db lecture seule OK",
        "ar": "state.db للقراءة فقط سليم",
    },
    "db_error": {
        "zh": "state.db 不可读: {error}",
        "en": "state.db unreadable: {error}",
        "fr": "state.db illisible : {error}",
        "ar": "تعذّرت قراءة state.db: {error}",
    },
    "db_unreadable_title": {
        "zh": "state.db 不可读",
        "en": "state.db unreadable",
        "fr": "state.db illisible",
        "ar": "تعذّرت قراءة state.db",
    },
    # -- rules.py: disk --
    "disk_low": {
        "zh": "磁盘剩余 {free:.1f}% < {threshold:.0f}%",
        "en": "Disk free {free:.1f}% < {threshold:.0f}%",
        "fr": "Espace disque libre {free:.1f}% < {threshold:.0f}%",
        "ar": "المساحة الحرة بالقرص {free:.1f}% < {threshold:.0f}%",
    },
    "disk_critical_title": {
        "zh": "磁盘空间告急",
        "en": "Disk space critical",
        "fr": "Espace disque critique",
        "ar": "مساحة القرص حرجة",
    },
    "disk_warn_title": {
        "zh": "磁盘空间偏低",
        "en": "Disk space low",
        "fr": "Espace disque faible",
        "ar": "مساحة القرص منخفضة",
    },
    "disk_free_detail": {
        "zh": "剩余 {free:.1f}%",
        "en": "Free {free:.1f}%",
        "fr": "Libre {free:.1f}%",
        "ar": "المتاح {free:.1f}%",
    },
    "disk_ok": {
        "zh": "磁盘剩余 {free:.1f}%",
        "en": "Disk free {free:.1f}%",
        "fr": "Espace disque libre {free:.1f}%",
        "ar": "المساحة الحرة بالقرص {free:.1f}%",
    },
    "disk_unavailable": {
        "zh": "磁盘数据不可用",
        "en": "Disk data unavailable",
        "fr": "Données disque indisponibles",
        "ar": "بيانات القرص غير متاحة",
    },
    # -- rules.py: memory --
    "memory_usage": {
        "zh": "内存使用 {pct:.0f}%",
        "en": "Memory usage {pct:.0f}%",
        "fr": "Utilisation mémoire {pct:.0f}%",
        "ar": "استخدام الذاكرة {pct:.0f}%",
    },
    "memory_pressure_title": {
        "zh": "内存压力",
        "en": "Memory pressure",
        "fr": "Pression mémoire",
        "ar": "ضغط الذاكرة",
    },
    "memory_pressure_detail": {
        "zh": "使用率 {pct:.0f}%",
        "en": "Usage {pct:.0f}%",
        "fr": "Utilisation {pct:.0f}%",
        "ar": "الاستخدام {pct:.0f}%",
    },
    "memory_unavailable": {
        "zh": "内存数据不可用",
        "en": "Memory data unavailable",
        "fr": "Données mémoire indisponibles",
        "ar": "بيانات الذاكرة غير متاحة",
    },
    # -- rules.py: channels --
    "channel_attention": {
        "zh": "{name}: 已连接但 needs_attention 标记",
        "en": "{name}: connected but flagged needs_attention",
        "fr": "{name} : connecté mais marqué needs_attention",
        "ar": "{name}: متصل لكن معلَّم بـ needs_attention",
    },
    "channel_attention_title": {
        "zh": "{name} 连接不稳定",
        "en": "{name} connection unstable",
        "fr": "Connexion {name} instable",
        "ar": "اتصال {name} غير مستقر",
    },
    "channel_attention_detail": {
        "zh": "connected 但带 needs_attention",
        "en": "connected but flagged needs_attention",
        "fr": "connecté mais marqué needs_attention",
        "ar": "متصل لكن معلَّم بـ needs_attention",
    },
    "channel_disconnected": {
        "zh": "{name}: 状态={state}",
        "en": "{name}: state={state}",
        "fr": "{name} : state={state}",
        "ar": "{name}: state={state}",
    },
    "channel_disconnected_title": {
        "zh": "{name} 断开",
        "en": "{name} disconnected",
        "fr": "{name} déconnecté",
        "ar": "{name} غير متصل",
    },
    "channel_disconnected_detail": {
        "zh": "state={state}",
        "en": "state={state}",
        "fr": "state={state}",
        "ar": "state={state}",
    },
    "channel_stale": {
        "zh": "{name}: connected 但心跳 {age}s 过期",
        "en": "{name}: connected but heartbeat is {age}s stale",
        "fr": "{name} : connecté mais pulsation obsolète depuis {age}s",
        "ar": "{name}: متصل لكن النبضة متأخرة {age} ث",
    },
    "channel_stale_title": {
        "zh": "{name} 心跳过期",
        "en": "{name} heartbeat stale",
        "fr": "Pulsation {name} obsolète",
        "ar": "نبضة {name} قديمة",
    },
    "channel_stale_detail": {
        "zh": "connected 但 {age}s 无更新",
        "en": "connected but no update in {age}s",
        "fr": "connecté mais aucune mise à jour depuis {age}s",
        "ar": "متصل لكن دون تحديث منذ {age} ث",
    },
    "channel_ok": {
        "zh": "{name}: connected",
        "en": "{name}: connected",
        "fr": "{name} : connecté",
        "ar": "{name}: متصل",
    },
    # -- rules.py: errors --
    "errors_log_unavailable": {
        "zh": "errors.log 不可用",
        "en": "errors.log unavailable",
        "fr": "errors.log indisponible",
        "ar": "errors.log غير متاح",
    },
    "error_burst": {
        "zh": "近30分钟 {count} 条错误 > {threshold}",
        "en": "{count} errors in the last 30 min > {threshold}",
        "fr": "{count} erreurs sur les 30 dernières minutes > {threshold}",
        "ar": "{count} خطأ في آخر 30 دقيقة > {threshold}",
    },
    "error_burst_title": {
        "zh": "错误速率升高",
        "en": "Error rate spiking",
        "fr": "Taux d'erreurs en hausse",
        "ar": "ارتفاع معدل الأخطاء",
    },
    "recent_errors_count": {
        "zh": "近30分钟 {count} 条错误",
        "en": "{count} errors in the last 30 min",
        "fr": "{count} erreurs sur les 30 dernières minutes",
        "ar": "{count} خطأ في آخر 30 دقيقة",
    },
    # -- rules.py: launchd --
    "launchd_na": {
        "zh": "launchd 不适用（非 macOS）",
        "en": "launchd not applicable (non-macOS)",
        "fr": "launchd non applicable (hors macOS)",
        "ar": "launchd غير قابل للتطبيق (خارج macOS)",
    },
    "launchd_managed": {
        "zh": "Gateway 由 launchd 托管",
        "en": "Gateway managed by launchd",
        "fr": "Gateway gérée par launchd",
        "ar": "Gateway تُدار بواسطة launchd",
    },
    "launchd_unmanaged_plist": {
        "zh": "Gateway 未由 launchd 托管（plist 存在但未加载）",
        "en": "Gateway not managed by launchd (plist exists but not loaded)",
        "fr": "Gateway non gérée par launchd (plist présent mais non chargé)",
        "ar": "Gateway غير مُدارة بواسطة launchd (يوجد plist لكنه غير محمَّل)",
    },
    "launchd_unmanaged_noplist": {
        "zh": "Gateway 未由 launchd 托管（无服务定义）",
        "en": "Gateway not managed by launchd (no service definition)",
        "fr": "Gateway non gérée par launchd (aucune définition de service)",
        "ar": "Gateway غير مُدارة بواسطة launchd (لا يوجد تعريف خدمة)",
    },
    "launchd_incident_title": {
        "zh": "Gateway 脱离 launchd 托管",
        "en": "Gateway not under launchd management",
        "fr": "Gateway hors gestion launchd",
        "ar": "Gateway خارج إدارة launchd",
    },
    "launchd_detail_plist_exists": {
        "zh": "服务定义存在但未加载",
        "en": "Service definition exists but is not loaded",
        "fr": "La définition du service existe mais n'est pas chargée",
        "ar": "تعريف الخدمة موجود لكنه غير محمَّل",
    },
    "launchd_detail_missing": {
        "zh": "服务定义缺失",
        "en": "Service definition missing",
        "fr": "Définition du service manquante",
        "ar": "تعريف الخدمة مفقود",
    },
    # -- rules.py: dashboard --
    "dashboard_running": {
        "zh": "Dashboard 运行中 ({n} 进程)",
        "en": "Dashboard running ({n} process)",
        "fr": "Dashboard en cours d'exécution ({n} processus)",
        "ar": "Dashboard قيد التشغيل ({n} عملية)",
    },
    "dashboard_not_running": {
        "zh": "Dashboard 未运行",
        "en": "Dashboard not running",
        "fr": "Dashboard arrêté",
        "ar": "Dashboard متوقف",
    },
    "dashboard_not_running_detail": {
        "zh": "无 hermes web server 进程",
        "en": "No hermes web server process",
        "fr": "Aucun processus hermes web server",
        "ar": "لا توجد عملية hermes web server",
    },
    # -- rules.py: cron --
    "cron_fail_critical": {
        "zh": "任务「{name}」连续失败 {streak} 次",
        "en": 'Job "{name}" failed {streak} times in a row',
        "fr": "La tâche « {name} » a échoué {streak} fois de suite",
        "ar": '"{name}" فشلت {streak} مرة متتالية',
    },
    "cron_fail_title": {
        "zh": "Cron 连续失败: {name}",
        "en": "Cron repeated failures: {name}",
        "fr": "Échecs répétés Cron : {name}",
        "ar": "إخفاقات Cron متكررة: {name}",
    },
    "cron_fail_detail": {
        "zh": "连续失败 {streak} 次, 最近错误: {last_error}",
        "en": "Failed {streak} times in a row, last error: {last_error}",
        "fr": "Échoué {streak} fois de suite, dernière erreur : {last_error}",
        "ar": "فشلت {streak} مرة متتالية، آخر خطأ: {last_error}",
    },
    "none_value": {
        "zh": "无",
        "en": "none",
        "fr": "aucune",
        "ar": "لا شيء",
    },
    "cron_fail_warn": {
        "zh": "任务「{name}」失败 {streak} 次",
        "en": 'Job "{name}" failed {streak} times',
        "fr": "La tâche « {name} » a échoué {streak} fois",
        "ar": '"{name}" فشلت {streak} مرة',
    },
    "cron_ok": {
        "zh": "任务「{name}」正常",
        "en": 'Job "{name}" OK',
        "fr": "Tâche « {name} » OK",
        "ar": '"{name}" سليمة',
    },
    # -- rules.py: budget --
    "budget_over": {
        "zh": "今日估算费用 ${cost:.2f} 超过日预算 ${budget:.2f} 的 {pct:.0f}%",
        "en": "Today's estimated cost ${cost:.2f} exceeds {pct:.0f}% of the ${budget:.2f} daily budget",
        "fr": "Le coût estimé du jour {cost:.2f}$ dépasse {pct:.0f}% du budget quotidien de {budget:.2f}$",
        "ar": "التكلفة المقدّرة لليوم {cost:.2f}$ تتجاوز {pct:.0f}% من الميزانية اليومية البالغة {budget:.2f}$",
    },
    "budget_incident_title": {
        "zh": "今日费用超预算 80%",
        "en": "Today's cost exceeds 80% of budget",
        "fr": "Le coût du jour dépasse 80% du budget",
        "ar": "تكلفة اليوم تتجاوز 80% من الميزانية",
    },
    "budget_incident_detail": {
        "zh": "今日估算 ${cost:.2f} / 日预算 ${budget:.2f}",
        "en": "Today's estimate ${cost:.2f} / daily budget ${budget:.2f}",
        "fr": "Estimation du jour {cost:.2f}$ / budget quotidien {budget:.2f}$",
        "ar": "تقدير اليوم {cost:.2f}$ / الميزانية اليومية {budget:.2f}$",
    },
    "budget_ok_with_budget": {
        "zh": "今日估算 ${cost:.2f} / 预算 ${budget:.2f}",
        "en": "Today's estimate ${cost:.2f} / budget ${budget:.2f}",
        "fr": "Estimation du jour {cost:.2f}$ / budget {budget:.2f}$",
        "ar": "تقدير اليوم {cost:.2f}$ / الميزانية {budget:.2f}$",
    },
    "budget_ok_no_budget": {
        "zh": "今日估算 ${cost:.2f} (未配置预算)",
        "en": "Today's estimate ${cost:.2f} (no budget configured)",
        "fr": "Estimation du jour {cost:.2f}$ (aucun budget configuré)",
        "ar": "تقدير اليوم {cost:.2f}$ (لم تُضبط ميزانية)",
    },
    # -- collectors.py: error / note strings --
    "err_gateway_state_unreadable": {
        "zh": "gateway_state.json 不可读",
        "en": "gateway_state.json unreadable",
        "fr": "gateway_state.json illisible",
        "ar": "تعذّرت قراءة gateway_state.json",
    },
    "err_psutil_unavailable": {
        "zh": "psutil 不可用",
        "en": "psutil unavailable",
        "fr": "psutil indisponible",
        "ar": "psutil غير متاح",
    },
    "err_statedb_conn_failed": {
        "zh": "state.db 只读连接失败",
        "en": "state.db read-only connection failed",
        "fr": "Échec de la connexion en lecture seule à state.db",
        "ar": "فشل الاتصال للقراءة فقط بـ state.db",
    },
    "err_query_failed": {
        "zh": "查询失败: {exc}",
        "en": "Query failed: {exc}",
        "fr": "Échec de la requête : {exc}",
        "ar": "فشل الاستعلام: {exc}",
    },
    "err_cron_jobs_unreadable": {
        "zh": "cron/jobs.json 不可读",
        "en": "cron/jobs.json unreadable",
        "fr": "cron/jobs.json illisible",
        "ar": "تعذّرت قراءة cron/jobs.json",
    },
    "err_executions_conn_failed": {
        "zh": "executions.db 只读连接失败",
        "en": "executions.db read-only connection failed",
        "fr": "Échec de la connexion en lecture seule à executions.db",
        "ar": "فشل الاتصال للقراءة فقط بـ executions.db",
    },
    "err_errorslog_missing": {
        "zh": "errors.log 不存在",
        "en": "errors.log does not exist",
        "fr": "errors.log n'existe pas",
        "ar": "errors.log غير موجود",
    },
    "note_launchd_macos_only": {
        "zh": "launchd 仅 macOS 适用",
        "en": "launchd applies to macOS only",
        "fr": "launchd s'applique uniquement à macOS",
        "ar": "launchd ينطبق على macOS فقط",
    },
    "err_skills_dir_missing": {
        "zh": "skills 目录不存在",
        "en": "skills directory does not exist",
        "fr": "le répertoire skills n'existe pas",
        "ar": "دليل skills غير موجود",
    },
    "uncategorized": {
        "zh": "未分类",
        "en": "Uncategorized",
        "fr": "Non classé",
        "ar": "غير مصنّف",
    },
}


def resolve_locale(raw: str | None) -> str:
    """Normalize a client-supplied locale string; unknown values fall back to English.

    Case-insensitive and matches on the primary language subtag (RFC 5646), so
    region/script variants (``zh-CN``, ``zh-Hant``, ``fr-FR``, ``ZH-HANT``, ...)
    resolve to their base language instead of silently falling back to English.
    """
    if not raw:
        return "zh"
    primary = raw.strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if primary in _SUPPORTED else "en"


def t(key: str, locale: str, **kwargs: object) -> str:
    """Render ``key`` in ``locale``, falling back to en then to the raw key."""
    bundle = TEMPLATES.get(key)
    if not bundle:
        return key
    tpl = bundle.get(locale) or bundle.get("en") or bundle.get("zh") or key
    try:
        return tpl.format(**kwargs)
    except Exception:
        return tpl
