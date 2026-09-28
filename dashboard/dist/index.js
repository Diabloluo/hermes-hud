/**
 * Hermes HUD — Dashboard Plugin
 * =============================
 * 本地实时监控指挥中心（13-Tab 计划的 MVP 实现）。
 *
 * 纯 IIFE、无构建步骤。用 window.__HERMES_PLUGIN_SDK__ 提供 React /
 * hooks / 组件 / 认证 fetch；2 秒轮询 /snapshot + WebSocket 增量事件流
 * （buildWsUrl 自动带鉴权，断线指数退避并回退到轮询）。
 *
 * 数据只读：后端只查询 Hermes 现有状态文件与 SQLite，前端不做任何写操作。
 *
 * i18n: UI 文案跟随 Dashboard 的语言（SDK.useI18n()）。中文保持原样；
 * en/fr/ar 走下面的 EN/FR/AR 字典（按原文精确匹配，缺失时回退英文，
 * 再回退中文原文）。见 tt() / dtLocale() / HudApp() 里 CURRENT_LOCALE 的更新点。
 */

(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  const { React } = SDK;
  const h = React.createElement;
  const { useState, useEffect, useMemo, useRef, useCallback } = SDK.hooks;
  const { Card, CardContent, Badge, Button, Input } = SDK.components;
  const { timeAgo } = SDK.utils;
  const useI18n = SDK.useI18n;

  const API = "/api/plugins/hermes-hud";

  // -------------------------------------------------------------------------
  // i18n
  // -------------------------------------------------------------------------

  let CURRENT_LOCALE = "zh";

  // English. Source of truth for fallback when a locale is missing a key.
  const EN = {
    "故障": "Critical", "警告": "Warning", "正常": "Normal",
    "已连接": "Connected", "已断开": "Disconnected", "连接中": "Connecting",
    "重连中": "Reconnecting", "错误": "Error", "未知": "Unknown",
    "成功": "Success", "失败": "Failed", "运行中": "Running",
    "已认领": "Claimed", "待运行": "Pending",
    "加载中…": "Loading…", "加载中": "Loading",

    // Overview
    "未运行": "Not running", "状态": "Status", "版本": "Version",
    "活跃 Agent": "Active Agents", "渠道": "Channels",
    "（心跳陈旧）": " (heartbeat stale)", "抖动": "Flapping",
    "今日 Token / 费用": "Today's Tokens / Cost", "输入": "Input", "输出": "Output",
    "Cache 读": "Cache Read", "估算费用": "Estimated Cost", "估算": "Estimated",
    "Cron / 会话": "Cron / Sessions", " 启用 / ": " enabled / ", " 总": " total",
    "执行中": "Running", "失败中": "Failing", "活跃会话": "Active Sessions",
    "健康检查 (": "Health Checks (", " 项)": ")",
    "当前无活跃事故": "No active incidents",
    "内存": "Memory", "磁盘剩余": "Disk Free", "机器运行": "Machine Uptime",
    " 天": " days",
    "采集于 ": "Collected at ", " · 时区 ": " · Timezone ",
    " · 数据为本地只读采集": " · Data is local, read-only",

    // Live
    "活跃会话 (": "Active Sessions (", "当前无活跃会话": "No active sessions",
    "标题 / ID": "Title / ID", "模型": "Model", "来源": "Source",
    "(无标题)": "(untitled)", "实时事件流": "Live Event Stream",
    " (轮询模式)": " (polling mode)", "暂无事件": "No events yet",
    "最近工具调用 (": "Recent Tool Calls (", "暂无工具调用记录": "No tool call records yet",
    "时间": "Time", "会话": "Session", "工具": "Tool", "调用参数工具": "Arguments",
    "事件流每秒级增量（channel/cron/session/health/gateway 状态变化）；工具调用为轻量版（从 messages 推断），精确 tool start/end 生命周期需插件 hook（第二版）。":
      "The event stream is second-level incremental (channel/cron/session/health/gateway state changes); tool calls are a lightweight view (inferred from messages) — precise tool start/end lifecycle needs a plugin hook (v2).",

    // Usage
    "今日": "Today", "费用数据源不可用": "Cost data source unavailable",
    "暂无费用数据": "No cost data yet", "总 Token": "Total Tokens",
    "输入 Token": "Input Tokens", "输出 Token": "Output Tokens",
    "平均每 Session": "Avg per Session", "今日归属估算费用": "Today's Attributed Est. Cost",
    "今日预算比例": "Today's Budget Ratio", "不可用（累计数据）": "Unavailable (cumulative data)",
    "今日预算使用率": "Today's Budget Usage", "已知部分 $": "Known portion $",
    "—（定价未知）": "— (pricing unknown)", "Cost Intelligence · 范围": "Cost Intelligence · Range",
    "估算费用 / Estimated cost（非账单）": "Estimated cost (not a bill)",
    "部分成本数据：仅部分 usage 记录含费用，汇总是已知部分。":
      "Partial cost data: only some usage rows include a cost; totals reflect the known portion.",
    "（Partial cost data — coverage ": " (coverage ", "%）": "%)",
    "时间范围费用为归属估算：Hermes 当前仅保存累计 usage row，跨时间边界的调用无法精确拆分。（Time-window cost is attribution-based.）":
      "Time-window costs are attribution-based estimates — Hermes currently stores only cumulative usage rows, so calls spanning a time boundary can't be split precisely.",
    "Top Sessions（估算费用 · 脱敏标题）": "Top Sessions (estimated cost · redacted titles)",
    " 会话": " sessions", "模型分布（估算费用）": "Model Distribution (estimated cost)",
    "费用为本地估算，非账单": "Cost is a local estimate, not a bill",
    "统计窗口": "Stats Window", "API 调用": "API Calls",
    "每日估算费用（": "Daily Estimated Cost (", " · canonical /cost/timeseries）": " · canonical /cost/timeseries)",
    "部分成本数据：趋势仅含定价来源已知的行。": "Partial cost data: the trend includes only rows with known pricing.",
    "每日输入 Token": "Daily Input Tokens", "无数据": "No data",
    "按模型 · 调用/Token（近 ": "By Model · Calls/Tokens (last ",
    " 天 · 费用见上方 /cost/models）": " days · cost shown above via /cost/models)",
    "调用": "Calls", "辅助调用类型（近 ": "Auxiliary Call Types (last ",
    " 天 · 仅调用数/Token）": " days · calls/tokens only)",
    "无辅助调用数据": "No auxiliary call data",
    "辅助调用 = session_model_usage.task != ''（compression / vision / title_generation / background_review 等）。主会话与辅助调用已分开归集，不重复计数。":
      "Auxiliary calls = session_model_usage.task != '' (compression / vision / title_generation / background_review, etc). Primary sessions and auxiliary calls are tallied separately — no double-counting.",
    "任务类型": "Task Type",
    "口径：主会话读 sessions 表；辅助调用读 session_model_usage.task != ''；按 (session, model, task) 去重后合并。日界线使用 HUD 配置时区。 所有费用均为估算（estimated），非账单。":
      "Methodology: primary sessions read from the sessions table; auxiliary calls read session_model_usage.task != ''; deduplicated and merged by (session, model, task). Day boundaries use the HUD's configured timezone. All costs are estimates, not bills.",

    // Sessions
    "搜索标题 / ID / 用户…": "Search title / ID / user…", "搜索": "Search",
    "搜索: ": "Search: ", " 条": " entries", "会话详情": "Session Details",
    "会话列表": "Session List", "返回列表": "Back to List", "消息": "Messages",
    "工具调用": "Tool Calls", "开始": "Started",
    "消息预览（正文按需加载，已脱敏）": "Message Preview (body loaded on demand, redacted)",
    "(空)": "(empty)", "会话内模型调用": "In-Session Model Calls",
    "费用": "Cost", "(主)": "(primary)", "加载会话详情…": "Loading session details…",
    "无会话记录": "No session records", "标题": "Title",
    "点击查看详情": "Click to view details",

    // Memory
    "记忆文件": "Memory Files", "文件": "File", "大小": "Size",
    "分节": "Sections", "更新": "Updated", "Provider 与锁": "Provider & Locks",
    "记忆卡片(§ 分节)": "Memory Cards (§ sections)", "锁文件": "Lock Files",
    "无锁文件": "No lock files", " — 锁超过 10 分钟未释放!": " — lock held for over 10 min!",
    "记忆正文不进总览事件流；此页只展示元数据。写入失败/锁异常由健康规则上报。":
      "Memory content doesn't flow into the overview event stream; this page only shows metadata. Write failures/lock anomalies are reported via health rules.",

    // Cron
    "任务总数": "Total Jobs", "启用": "Enabled", "暂停/禁用": "Paused/Disabled",
    "任务列表 (": "Job List (", "无任务": "No jobs", "任务": "Jobs",
    "排程": "Schedule", "下次运行": "Next Run", "上次": "Last", "投递": "Delivery",
    "m 后": "m left", "暂停": "Paused",
    "执行历史 (最近 ": "Execution History (last ", " 条)": ")",
    "无执行记录": "No execution records", "耗时": "Duration",
    "状态未知 / 孤儿进程": "Unknown status / orphaned process",
    "执行历史来自 cron/executions.db（claimed→running→completed/failed 状态机）。成功率/连续失败统计见后端 rules；编辑/暂停/手动触发请跳转 Dashboard 的 Cron 页。":
      "Execution history comes from cron/executions.db (claimed→running→completed/failed state machine). Success rate/consecutive-failure stats live in the backend rules; edit/pause/manual trigger from the Dashboard's Cron page.",

    // Channels
    "无渠道数据": "No channel data", "已连接 · 心跳陈旧": "Connected · heartbeat stale",
    "更新时间": "Updated At", "心跳龄": "Heartbeat Age", "需关注": "Needs Attention",
    "是": "Yes", "否": "No", "错误码": "Error Code",
    "已连接但持续抖动：": "Connected but flapping: ",
    " 无状态更新 — 需结合错误日志判断": " with no status update — check error logs to confirm",
    "渠道状态来自 gateway_state.json。'connected' 是瞬时快照，稳定性要结合心跳龄与 errors.log 判定 —— 例如飞书当前 connected 但日志每 ~2 分钟重连。重连计数等更细的抖动指标在错误事故页。":
      "Channel status comes from gateway_state.json. 'connected' is a point-in-time snapshot — judge stability from heartbeat age plus errors.log (e.g. Feishu can show connected while reconnecting roughly every ~2 minutes in the logs). Finer flapping metrics like reconnect counts live on the Errors & Incidents page.",

    // Incidents
    "近 30 分钟错误": "Errors (last 30 min)", "错误指纹": "Error Fingerprints",
    "活跃事故": "Active Incidents", "事故总数": "Total Incidents",
    "事故时间线 (telemetry.db)": "Incident Timeline (telemetry.db)",
    "暂无事故记录": "No incident records yet", "进行中": "Active", "已恢复": "Resolved",
    "首次 ": "First seen ", " · 末次 ": " · last seen ", " · 观测 ": " · ", " 次": " times",
    "错误指纹 TOP": "Top Error Fingerprints", "近 30 分钟无错误": "No errors in the last 30 min",
    "errors.log 尾部（脱敏）": "errors.log tail (redacted)", "无内容": "No content",
    "agent.log 尾部（脱敏）": "agent.log tail (redacted)",
    "日志按异常指纹去重聚合；关键字与凭据模式已脱敏；完整原始日志请到 Dashboard 的日志页查看。":
      "Logs are deduplicated and aggregated by error fingerprint; keywords and credential patterns are redacted. See the Dashboard's Logs page for the full raw logs.",

    // System
    "CPU / 负载": "CPU / Load", "CPU 使用": "CPU Usage", "核心数": "Cores",
    "负载": "Load", "使用率": "Usage", "已用": "Used", "总计": "Total",
    "磁盘 (Hermes 目录)": "Disk (Hermes dir)", "剩余": "Free", "可用": "Available",
    "总容量": "Total Capacity", "磁盘压力": "Disk Pressure", "进程": "Processes",
    "数据库": "Database", "服务托管": "Service Hosting",
    "launchd 托管": "Managed by launchd", "未由 launchd 托管": "Not managed by launchd",
    "服务定义": "Service Definition", "无 plist": "no plist",
    "Gateway 重启后可能不自启 — 建议修复": "Gateway may not auto-start after a reboot — fix recommended",
    "CPU 趋势 (telemetry)": "CPU Trend (telemetry)",
    "数据积累中（约 60s 一个点）": "Collecting data (~1 point per 60s)",
    "内存趋势": "Memory Trend", "数据积累中": "Collecting data",
    "磁盘剩余趋势": "Disk Free Trend",
    "时序数据保存在 ~/.hermes/hud/telemetry.db（分钟级，保留 ": "Time-series data is stored in ~/.hermes/hud/telemetry.db (per-minute, retained for ",
    " 天），不触碰 state.db。": " days); state.db is never touched.",

    // Skills
    "全部": "All", "技能总数": "Total Skills", "分类数": "Categories",
    "近 24h 新增/修改": "New/Modified (24h)", "近 7 天活动": "Active (7d)",
    "分类分布 (": "Category Distribution (", "分类筛选": "Category Filter",
    "技能列表 (": "Skill List (", "该分类下无技能": "No skills in this category",
    "技能": "Skill", "分类": "Category", "最近修改": "Last Modified", "描述": "Description",
    "技能目录 ~/.hermes/skills/（只读扫描 SKILL.md 元数据）。安装/删除请到 Dashboard 的 Skills 页。":
      "Skills directory ~/.hermes/skills/ (read-only scan of SKILL.md metadata). Install/remove from the Dashboard's Skills page.",

    // Settings
    "阈值与预算（rules.py）": "Thresholds & Budgets (rules.py)",
    "采集器数据质量": "Collector Data Quality", "全部采集器正常": "All collectors OK",
    "部分采集器异常": "Some collectors degraded", "统计时区": "Stats Timezone",
    "HUD_TIMEZONE > 系统本地时区 > UTC；快照缓存 TTL ": "HUD_TIMEZONE > system local timezone > UTC; snapshot cache TTL ",
    "s / telemetry 落盘每 ": "s / telemetry flushed every ", "s 一次": "s",
    "指标行": "Metric Rows", "事故记录": "Incident Records", "库大小": "DB Size",
    "安全边界": "Security Boundary",
    "• 默认仅监听 127.0.0.1，沿用 Dashboard 鉴权": "• Listens on 127.0.0.1 only by default, reuses Dashboard auth",
    "• 不读取/返回 .env、auth.json、完整 token": "• Never reads/returns .env, auth.json, or full tokens",
    "• 日志/对话/记忆经脱敏与按需加载": "• Logs/conversations/memory are redacted and loaded on demand",
    "• telemetry.db 只存聚合、指纹与短摘要": "• telemetry.db stores only aggregates, fingerprints, and short summaries",
    "• 无 outbound 遥测，不自动查询外部账单": "• No outbound telemetry; never queries external billing automatically",
    "• HUD 纯观察；操作跳转现有 Dashboard 受保护页面": "• HUD is observe-only; actions redirect to the existing protected Dashboard pages",
    "Dashboard 界面语言": "Dashboard UI Language", "当前：": "Current: ",
    "此处切换会立即应用到整个 Dashboard（含本插件），并保存在浏览器 localStorage，与系统重启无关。更多语言可在 Dashboard 顶部的语言切换器中选择。":
      "Switching here applies immediately across the whole Dashboard (including this plugin) and is saved to browser localStorage — it survives restarts. More languages are available from the language switcher at the top of the Dashboard.",
    "刷新频率：snapshot 2s / usage·metrics 30s / settings·quality 30-60s；阈值可用 HUD_* 环境变量覆盖（见后端 rules.py）。":
      "Refresh rate: snapshot 2s / usage·metrics 30s / settings·quality 30-60s; thresholds can be overridden with HUD_* environment variables (see backend rules.py).",

    // Tabs
    "指挥中心": "Command Center", "实时活动": "Live Activity", "Token·费用": "Tokens · Cost",
    "对话记录": "Conversations", "时间线": "Timeline", "记忆": "Memory", "技能分析": "Skill Analytics",
    "定时任务": "Scheduled Jobs", "错误·事故": "Errors & Incidents", "系统·存储": "System & Storage",
    "设置": "Settings",

    // Timeline
    "全部状态": "All Statuses", " 条新事件": " new events", "加载失败: ": "Failed to load: ",
    "暂无事件（全新安装的正常状态；有新活动后自动出现）": "No events yet (normal for a fresh install — appears once there's new activity)",
    "加载更多": "Load more", " 条新事件（点击载入）": " new events (click to load)",
    "Agent Timeline — 做了什么？": "Agent Timeline — What happened?", "类型": "Type",
    "时长": "Duration", "关联": "Correlation",

    // Skill Analytics
    "已观测": "Observed", "仅清单": "Inventory only", "不可用": "Unavailable",
    "已注册技能": "Registered Skills", "已观测执行": "Observed Executions",
    "观测运行次数": "Observed Runs", "成功率": "Success Rate", "失败次数": "Failed Runs",
    "未观测到执行": "No Observed Execution",
    "运行观测覆盖目前不完整；统计仅包含具有可靠身份的 Skill 执行事件。":
      "Runtime observation coverage is currently partial; stats include only Skill execution events with a reliable identity.",
    "有失败": "Has Failures", "有成功": "Has Successes",
    "搜索技能名…": "Search skill name…", "按名称": "By Name", "运行最多": "Most Runs",
    "失败最多": "Most Failures", "成功率最低": "Lowest Success Rate", "最近运行": "Recently Run",
    "覆盖": "Coverage", "风险": "Risk", "健康": "Health", "Review 决策": "Review Decision",
    "来源 / Provenance": "Source / Provenance", "平均耗时": "Avg Duration",
    "最近观测": "Last Observed",
    "最近 Timeline 事件（直接引用，不复制）": "Recent Timeline Events (referenced directly, not copied)",
    "未观测到执行（No observed executions）": "No observed executions",
    "Skill Analytics — 技能运行观测（observed truth only）": "Skill Analytics — Skill Run Observations (observed truth only)",
    "暂无技能数据（registry 或 timeline 不可用时的正常降级）": "No skill data yet (normal fallback when the registry or timeline is unavailable)",
    "共 ": "", " 个技能（分页上限 200，可搜索/过滤缩小范围）": " skills total (page limit 200; search/filter to narrow)",

    // HudApp header
    " 红 / ": " red / ", " 黄": " yellow", "离线": "Offline", " 启用": " enabled",
    "WS 实时": "WS Live", "WS 重连中": "WS Reconnecting", "轮询": "Polling", "模式": "Mode",

    // Disambiguated (context, not source text) keys — see tt(zh, key)
    "th_runtime": "Runtime", "th_runs": "Runs", "th_task": "Task",
  };

  // French
  const FR = {
    "故障": "Critique", "警告": "Avertissement", "正常": "Normal",
    "已连接": "Connecté", "已断开": "Déconnecté", "连接中": "Connexion…",
    "重连中": "Reconnexion…", "错误": "Erreur", "未知": "Inconnu",
    "成功": "Succès", "失败": "Échec", "运行中": "En cours",
    "已认领": "Pris en charge", "待运行": "En attente",
    "加载中…": "Chargement…", "加载中": "Chargement",

    "未运行": "Arrêté", "状态": "État", "版本": "Version",
    "活跃 Agent": "Agents actifs", "渠道": "Canaux",
    "（心跳陈旧）": " (pulsation obsolète)", "抖动": "Instable",
    "今日 Token / 费用": "Jetons / coût du jour", "输入": "Entrée", "输出": "Sortie",
    "Cache 读": "Lecture cache", "估算费用": "Coût estimé", "估算": "Estimé",
    "Cron / 会话": "Cron / Sessions", " 启用 / ": " activées / ", " 总": " au total",
    "执行中": "En cours", "失败中": "En échec", "活跃会话": "Sessions actives",
    "健康检查 (": "Contrôles de santé (", " 项)": ")",
    "当前无活跃事故": "Aucun incident actif",
    "内存": "Mémoire", "磁盘剩余": "Disque libre", "机器运行": "Disponibilité machine",
    " 天": " jours",
    "采集于 ": "Collecté à ", " · 时区 ": " · Fuseau horaire ",
    " · 数据为本地只读采集": " · Données locales, lecture seule",

    "活跃会话 (": "Sessions actives (", "当前无活跃会话": "Aucune session active",
    "标题 / ID": "Titre / ID", "模型": "Modèle", "来源": "Source",
    "(无标题)": "(sans titre)", "实时事件流": "Flux d'événements en direct",
    " (轮询模式)": " (mode sondage)", "暂无事件": "Aucun événement pour l'instant",
    "最近工具调用 (": "Appels d'outils récents (", "暂无工具调用记录": "Aucun appel d'outil enregistré",
    "时间": "Heure", "会话": "Session", "工具": "Outil", "调用参数工具": "Arguments",
    "事件流每秒级增量（channel/cron/session/health/gateway 状态变化）；工具调用为轻量版（从 messages 推断），精确 tool start/end 生命周期需插件 hook（第二版）。":
      "Le flux d'événements est incrémental à la seconde près (changements d'état channel/cron/session/health/gateway) ; les appels d'outils sont une vue allégée (déduite des messages) — un cycle de vie précis start/end des outils nécessite un hook de plugin (v2).",

    "今日": "Aujourd'hui", "费用数据源不可用": "Source des données de coût indisponible",
    "暂无费用数据": "Aucune donnée de coût pour l'instant", "总 Token": "Jetons totaux",
    "输入 Token": "Jetons en entrée", "输出 Token": "Jetons en sortie",
    "平均每 Session": "Moyenne par session", "今日归属估算费用": "Coût estimé attribué du jour",
    "今日预算比例": "Ratio budgétaire du jour", "不可用（累计数据）": "Indisponible (données cumulées)",
    "今日预算使用率": "Utilisation du budget du jour", "已知部分 $": "Partie connue $",
    "—（定价未知）": "— (tarification inconnue)", "Cost Intelligence · 范围": "Cost Intelligence · Plage",
    "估算费用 / Estimated cost（非账单）": "Coût estimé (non facturé)",
    "部分成本数据：仅部分 usage 记录含费用，汇总是已知部分。":
      "Données de coût partielles : seules certaines lignes d'usage incluent un coût ; les totaux reflètent la part connue.",
    "（Partial cost data — coverage ": " (couverture ", "%）": "%)",
    "时间范围费用为归属估算：Hermes 当前仅保存累计 usage row，跨时间边界的调用无法精确拆分。（Time-window cost is attribution-based.）":
      "Les coûts par fenêtre temporelle sont des estimations attribuées — Hermes ne stocke actuellement que des lignes d'usage cumulées, donc les appels à cheval sur une limite temporelle ne peuvent pas être répartis précisément.",
    "Top Sessions（估算费用 · 脱敏标题）": "Top sessions (coût estimé · titres anonymisés)",
    " 会话": " sessions", "模型分布（估算费用）": "Répartition par modèle (coût estimé)",
    "费用为本地估算，非账单": "Le coût est une estimation locale, pas une facture",
    "统计窗口": "Fenêtre statistique", "API 调用": "Appels API",
    "每日估算费用（": "Coût estimé quotidien (", " · canonical /cost/timeseries）": " · canonique /cost/timeseries)",
    "部分成本数据：趋势仅含定价来源已知的行。": "Données de coût partielles : la tendance n'inclut que les lignes dont la tarification est connue.",
    "每日输入 Token": "Jetons d'entrée quotidiens", "无数据": "Aucune donnée",
    "按模型 · 调用/Token（近 ": "Par modèle · Appels/Jetons (",
    " 天 · 费用见上方 /cost/models）": " derniers jours · coût ci-dessus via /cost/models)",
    "调用": "Appels", "辅助调用类型（近 ": "Types d'appels auxiliaires (",
    " 天 · 仅调用数/Token）": " derniers jours · appels/jetons uniquement)",
    "无辅助调用数据": "Aucune donnée d'appel auxiliaire",
    "辅助调用 = session_model_usage.task != ''（compression / vision / title_generation / background_review 等）。主会话与辅助调用已分开归集，不重复计数。":
      "Appels auxiliaires = session_model_usage.task != '' (compression / vision / title_generation / background_review, etc.). Les sessions principales et les appels auxiliaires sont comptabilisés séparément — pas de double comptage.",
    "任务类型": "Type de tâche",
    "口径：主会话读 sessions 表；辅助调用读 session_model_usage.task != ''；按 (session, model, task) 去重后合并。日界线使用 HUD 配置时区。 所有费用均为估算（estimated），非账单。":
      "Méthodologie : les sessions principales sont lues depuis la table sessions ; les appels auxiliaires lisent session_model_usage.task != '' ; dédupliqués et fusionnés par (session, modèle, tâche). Les limites de jour utilisent le fuseau horaire configuré du HUD. Tous les coûts sont des estimations, pas des factures.",

    "搜索标题 / ID / 用户…": "Rechercher titre / ID / utilisateur…", "搜索": "Rechercher",
    "搜索: ": "Recherche : ", " 条": " éléments", "会话详情": "Détails de la session",
    "会话列表": "Liste des sessions", "返回列表": "Retour à la liste", "消息": "Messages",
    "工具调用": "Appels d'outils", "开始": "Démarré",
    "消息预览（正文按需加载，已脱敏）": "Aperçu des messages (contenu chargé à la demande, anonymisé)",
    "(空)": "(vide)", "会话内模型调用": "Appels de modèle dans la session",
    "费用": "Coût", "(主)": "(principal)", "加载会话详情…": "Chargement des détails de la session…",
    "无会话记录": "Aucun enregistrement de session", "标题": "Titre",
    "点击查看详情": "Cliquer pour voir les détails",

    "记忆文件": "Fichiers de mémoire", "文件": "Fichier", "大小": "Taille",
    "分节": "Sections", "更新": "Mis à jour", "Provider 与锁": "Fournisseur et verrous",
    "记忆卡片(§ 分节)": "Fiches mémoire (§ sections)", "锁文件": "Fichiers de verrouillage",
    "无锁文件": "Aucun fichier de verrouillage", " — 锁超过 10 分钟未释放!": " — verrou détenu depuis plus de 10 min !",
    "记忆正文不进总览事件流；此页只展示元数据。写入失败/锁异常由健康规则上报。":
      "Le contenu de la mémoire n'alimente pas le flux d'événements de la vue d'ensemble ; cette page n'affiche que les métadonnées. Les échecs d'écriture/anomalies de verrou sont signalés via les règles de santé.",

    "任务总数": "Tâches au total", "启用": "Activées", "暂停/禁用": "En pause/Désactivées",
    "任务列表 (": "Liste des tâches (", "无任务": "Aucune tâche", "任务": "Tâches",
    "排程": "Planification", "下次运行": "Prochaine exécution", "上次": "Dernière", "投递": "Livraison",
    "m 后": "m restantes", "暂停": "En pause",
    "执行历史 (最近 ": "Historique d'exécution (derniers ", " 条)": ")",
    "无执行记录": "Aucun enregistrement d'exécution", "耗时": "Durée",
    "状态未知 / 孤儿进程": "État inconnu / processus orphelin",
    "执行历史来自 cron/executions.db（claimed→running→completed/failed 状态机）。成功率/连续失败统计见后端 rules；编辑/暂停/手动触发请跳转 Dashboard 的 Cron 页。":
      "L'historique d'exécution provient de cron/executions.db (machine à états claimed→running→completed/failed). Les statistiques de taux de succès/échecs consécutifs sont dans les règles backend ; modifiez/mettez en pause/déclenchez manuellement depuis la page Cron du Dashboard.",

    "无渠道数据": "Aucune donnée de canal", "已连接 · 心跳陈旧": "Connecté · pulsation obsolète",
    "更新时间": "Mis à jour à", "心跳龄": "Âge de la pulsation", "需关注": "Nécessite attention",
    "是": "Oui", "否": "Non", "错误码": "Code d'erreur",
    "已连接但持续抖动：": "Connecté mais instable : ",
    " 无状态更新 — 需结合错误日志判断": " sans mise à jour de statut — vérifier les journaux d'erreurs",
    "渠道状态来自 gateway_state.json。'connected' 是瞬时快照，稳定性要结合心跳龄与 errors.log 判定 —— 例如飞书当前 connected 但日志每 ~2 分钟重连。重连计数等更细的抖动指标在错误事故页。":
      "Le statut des canaux provient de gateway_state.json. « connected » est un instantané ponctuel — jugez la stabilité via l'âge de la pulsation et errors.log (ex : Feishu peut afficher connected tout en se reconnectant environ toutes les ~2 minutes dans les journaux). Des métriques plus fines d'instabilité (compteurs de reconnexion) sont sur la page Erreurs et incidents.",

    "近 30 分钟错误": "Erreurs (30 dernières min)", "错误指纹": "Empreintes d'erreurs",
    "活跃事故": "Incidents actifs", "事故总数": "Incidents au total",
    "事故时间线 (telemetry.db)": "Chronologie des incidents (telemetry.db)",
    "暂无事故记录": "Aucun incident enregistré pour l'instant", "进行中": "En cours", "已恢复": "Résolu",
    "首次 ": "Première fois ", " · 末次 ": " · dernière fois ", " · 观测 ": " · ", " 次": " fois",
    "错误指纹 TOP": "Top des empreintes d'erreurs", "近 30 分钟无错误": "Aucune erreur au cours des 30 dernières minutes",
    "errors.log 尾部（脱敏）": "Fin de errors.log (anonymisé)", "无内容": "Aucun contenu",
    "agent.log 尾部（脱敏）": "Fin de agent.log (anonymisé)",
    "日志按异常指纹去重聚合；关键字与凭据模式已脱敏；完整原始日志请到 Dashboard 的日志页查看。":
      "Les journaux sont dédupliqués et agrégés par empreinte d'erreur ; les mots-clés et motifs d'identifiants sont anonymisés. Consultez la page Journaux du Dashboard pour les journaux bruts complets.",

    "CPU / 负载": "CPU / Charge", "CPU 使用": "Utilisation CPU", "核心数": "Cœurs",
    "负载": "Charge", "使用率": "Utilisation", "已用": "Utilisé", "总计": "Total",
    "磁盘 (Hermes 目录)": "Disque (dossier Hermes)", "剩余": "Libre", "可用": "Disponible",
    "总容量": "Capacité totale", "磁盘压力": "Pression disque", "进程": "Processus",
    "数据库": "Base de données", "服务托管": "Hébergement du service",
    "launchd 托管": "Géré par launchd", "未由 launchd 托管": "Non géré par launchd",
    "服务定义": "Définition du service", "无 plist": "aucun plist",
    "Gateway 重启后可能不自启 — 建议修复": "La Gateway pourrait ne pas redémarrer automatiquement — correction recommandée",
    "CPU 趋势 (telemetry)": "Tendance CPU (telemetry)",
    "数据积累中（约 60s 一个点）": "Collecte de données en cours (~1 point/60 s)",
    "内存趋势": "Tendance mémoire", "数据积累中": "Collecte de données en cours",
    "磁盘剩余趋势": "Tendance de l'espace disque libre",
    "时序数据保存在 ~/.hermes/hud/telemetry.db（分钟级，保留 ": "Les données temporelles sont stockées dans ~/.hermes/hud/telemetry.db (par minute, conservées ",
    " 天），不触碰 state.db。": " jours) ; state.db n'est jamais modifié.",

    "全部": "Tous", "技能总数": "Compétences au total", "分类数": "Catégories",
    "近 24h 新增/修改": "Nouvelles/modifiées (24 h)", "近 7 天活动": "Actives (7 j)",
    "分类分布 (": "Répartition par catégorie (", "分类筛选": "Filtre par catégorie",
    "技能列表 (": "Liste des compétences (", "该分类下无技能": "Aucune compétence dans cette catégorie",
    "技能": "Compétence", "分类": "Catégorie", "最近修改": "Dernière modification", "描述": "Description",
    "技能目录 ~/.hermes/skills/（只读扫描 SKILL.md 元数据）。安装/删除请到 Dashboard 的 Skills 页。":
      "Répertoire des compétences ~/.hermes/skills/ (analyse en lecture seule des métadonnées SKILL.md). Installez/supprimez depuis la page Skills du Dashboard.",

    "阈值与预算（rules.py）": "Seuils et budgets (rules.py)",
    "采集器数据质量": "Qualité des données des collecteurs", "全部采集器正常": "Tous les collecteurs sont OK",
    "部分采集器异常": "Certains collecteurs sont dégradés", "统计时区": "Fuseau horaire des statistiques",
    "HUD_TIMEZONE > 系统本地时区 > UTC；快照缓存 TTL ": "HUD_TIMEZONE > fuseau horaire local du système > UTC ; TTL du cache de snapshot ",
    "s / telemetry 落盘每 ": "s / telemetry écrit toutes les ", "s 一次": "s",
    "指标行": "Lignes de métriques", "事故记录": "Enregistrements d'incidents", "库大小": "Taille de la base",
    "安全边界": "Limites de sécurité",
    "• 默认仅监听 127.0.0.1，沿用 Dashboard 鉴权": "• Écoute uniquement sur 127.0.0.1 par défaut, réutilise l'authentification du Dashboard",
    "• 不读取/返回 .env、auth.json、完整 token": "• Ne lit/renvoie jamais .env, auth.json, ni les tokens complets",
    "• 日志/对话/记忆经脱敏与按需加载": "• Journaux/conversations/mémoire sont anonymisés et chargés à la demande",
    "• telemetry.db 只存聚合、指纹与短摘要": "• telemetry.db ne stocke que des agrégats, empreintes et résumés courts",
    "• 无 outbound 遥测，不自动查询外部账单": "• Aucune télémétrie sortante ; n'interroge jamais automatiquement la facturation externe",
    "• HUD 纯观察；操作跳转现有 Dashboard 受保护页面": "• Le HUD est en lecture seule ; les actions redirigent vers les pages protégées existantes du Dashboard",
    "Dashboard 界面语言": "Langue de l'interface Dashboard", "当前：": "Actuel : ",
    "此处切换会立即应用到整个 Dashboard（含本插件），并保存在浏览器 localStorage，与系统重启无关。更多语言可在 Dashboard 顶部的语言切换器中选择。":
      "Changer ici s'applique immédiatement à tout le Dashboard (y compris ce plugin) et est enregistré dans le localStorage du navigateur — cela survit aux redémarrages. D'autres langues sont disponibles depuis le sélecteur de langue en haut du Dashboard.",
    "刷新频率：snapshot 2s / usage·metrics 30s / settings·quality 30-60s；阈值可用 HUD_* 环境变量覆盖（见后端 rules.py）。":
      "Fréquence de rafraîchissement : snapshot 2 s / usage·metrics 30 s / settings·quality 30-60 s ; les seuils sont modifiables via des variables d'environnement HUD_* (voir rules.py côté backend).",

    "指挥中心": "Centre de commande", "实时活动": "Activité en direct", "Token·费用": "Jetons · Coût",
    "对话记录": "Conversations", "时间线": "Chronologie", "记忆": "Mémoire", "技能分析": "Analyse des compétences",
    "定时任务": "Tâches planifiées", "错误·事故": "Erreurs et incidents", "系统·存储": "Système et stockage",
    "设置": "Paramètres",

    "全部状态": "Tous les statuts", " 条新事件": " nouveaux événements", "加载失败: ": "Échec du chargement : ",
    "暂无事件（全新安装的正常状态；有新活动后自动出现）": "Aucun événement pour l'instant (normal pour une installation neuve — apparaît dès qu'il y a de l'activité)",
    "加载更多": "Charger plus", " 条新事件（点击载入）": " nouveaux événements (cliquer pour charger)",
    "Agent Timeline — 做了什么？": "Agent Timeline — Que s'est-il passé ?", "类型": "Type",
    "时长": "Durée", "关联": "Corrélation",

    "已观测": "Observé", "仅清单": "Inventaire seulement", "不可用": "Indisponible",
    "已注册技能": "Compétences enregistrées", "已观测执行": "Exécutions observées",
    "观测运行次数": "Exécutions observées (nb)", "成功率": "Taux de succès", "失败次数": "Exécutions échouées",
    "未观测到执行": "Aucune exécution observée",
    "运行观测覆盖目前不完整；统计仅包含具有可靠身份的 Skill 执行事件。":
      "La couverture d'observation à l'exécution est actuellement partielle ; les statistiques n'incluent que les événements d'exécution de compétences avec une identité fiable.",
    "有失败": "Avec échecs", "有成功": "Avec succès",
    "搜索技能名…": "Rechercher un nom de compétence…", "按名称": "Par nom", "运行最多": "Le plus exécuté",
    "失败最多": "Le plus d'échecs", "成功率最低": "Taux de succès le plus bas", "最近运行": "Exécuté récemment",
    "覆盖": "Couverture", "风险": "Risque", "健康": "Santé", "Review 决策": "Décision de revue",
    "来源 / Provenance": "Source / Provenance", "平均耗时": "Durée moyenne",
    "最近观测": "Dernière observation",
    "最近 Timeline 事件（直接引用，不复制）": "Événements Timeline récents (référencés directement, non copiés)",
    "未观测到执行（No observed executions）": "Aucune exécution observée",
    "Skill Analytics — 技能运行观测（observed truth only）": "Skill Analytics — Observations d'exécution des compétences (vérité observée uniquement)",
    "暂无技能数据（registry 或 timeline 不可用时的正常降级）": "Aucune donnée de compétence pour l'instant (repli normal quand le registre ou la timeline est indisponible)",
    "共 ": "", " 个技能（分页上限 200，可搜索/过滤缩小范围）": " compétences au total (limite de page 200 ; recherchez/filtrez pour affiner)",

    " 红 / ": " rouge / ", " 黄": " jaune", "离线": "Hors ligne", " 启用": " activées",
    "WS 实时": "WS en direct", "WS 重连中": "WS reconnexion…", "轮询": "Sondage", "模式": "Mode",

    "th_runtime": "Durée", "th_runs": "Exécutions", "th_task": "Tâche",
  };

  // Arabic (RTL — the host flips document.dir automatically for "ar", see setLocale)
  const AR = {
    "故障": "حرج", "警告": "تحذير", "正常": "طبيعي",
    "已连接": "متصل", "已断开": "غير متصل", "连接中": "جارٍ الاتصال",
    "重连中": "جارٍ إعادة الاتصال", "错误": "خطأ", "未知": "غير معروف",
    "成功": "نجاح", "失败": "فشل", "运行中": "قيد التشغيل",
    "已认领": "مُستلمة", "待运行": "قيد الانتظار",
    "加载中…": "جارٍ التحميل…", "加载中": "جارٍ التحميل",

    "未运行": "متوقف", "状态": "الحالة", "版本": "الإصدار",
    "活跃 Agent": "الوكلاء النشطون", "渠道": "القنوات",
    "（心跳陈旧）": " (نبضة قديمة)", "抖动": "متذبذب",
    "今日 Token / 费用": "الرموز / التكلفة اليوم", "输入": "الإدخال", "输出": "الإخراج",
    "Cache 读": "قراءة التخزين المؤقت", "估算费用": "التكلفة المقدّرة", "估算": "تقديري",
    "Cron / 会话": "كرون / الجلسات", " 启用 / ": " مفعّلة / ", " 总": " إجمالي",
    "执行中": "قيد التشغيل", "失败中": "يفشل حالياً", "活跃会话": "الجلسات النشطة",
    "健康检查 (": "فحوصات السلامة (", " 项)": ")",
    "当前无活跃事故": "لا توجد حوادث نشطة حالياً",
    "内存": "الذاكرة", "磁盘剩余": "المساحة الحرة بالقرص", "机器运行": "مدة تشغيل الجهاز",
    " 天": " يوم",
    "采集于 ": "تم الجمع في ", " · 时区 ": " · المنطقة الزمنية ",
    " · 数据为本地只读采集": " · البيانات محلية وللقراءة فقط",

    "活跃会话 (": "الجلسات النشطة (", "当前无活跃会话": "لا توجد جلسات نشطة",
    "标题 / ID": "العنوان / المعرّف", "模型": "النموذج", "来源": "المصدر",
    "(无标题)": "(بدون عنوان)", "实时事件流": "تدفق الأحداث المباشر",
    " (轮询模式)": " (وضع الاستطلاع)", "暂无事件": "لا توجد أحداث بعد",
    "最近工具调用 (": "استدعاءات الأدوات الأخيرة (", "暂无工具调用记录": "لا توجد سجلات لاستدعاء الأدوات بعد",
    "时间": "الوقت", "会话": "الجلسة", "工具": "الأداة", "调用参数工具": "المعطيات",
    "事件流每秒级增量（channel/cron/session/health/gateway 状态变化）；工具调用为轻量版（从 messages 推断），精确 tool start/end 生命周期需插件 hook（第二版）。":
      "تدفق الأحداث تراكمي بدقة الثانية (تغيّرات حالة القناة/كرون/الجلسة/السلامة/البوابة)؛ استدعاءات الأدوات هي عرض مبسّط (مُستنتج من الرسائل) — دورة حياة دقيقة لبداية/نهاية الأداة تتطلب خطّاف إضافة (الإصدار الثاني).",

    "今日": "اليوم", "费用数据源不可用": "مصدر بيانات التكلفة غير متاح",
    "暂无费用数据": "لا توجد بيانات تكلفة بعد", "总 Token": "إجمالي الرموز",
    "输入 Token": "رموز الإدخال", "输出 Token": "رموز الإخراج",
    "平均每 Session": "المتوسط لكل جلسة", "今日归属估算费用": "التكلفة المقدّرة المنسوبة لليوم",
    "今日预算比例": "نسبة ميزانية اليوم", "不可用（累计数据）": "غير متاح (بيانات تراكمية)",
    "今日预算使用率": "استخدام ميزانية اليوم", "已知部分 $": "الجزء المعروف $",
    "—（定价未知）": "— (التسعير غير معروف)", "Cost Intelligence · 范围": "Cost Intelligence · النطاق",
    "估算费用 / Estimated cost（非账单）": "تكلفة مقدّرة (ليست فاتورة)",
    "部分成本数据：仅部分 usage 记录含费用，汇总是已知部分。":
      "بيانات تكلفة جزئية: بعض سجلات الاستخدام فقط تتضمن تكلفة؛ المجاميع تعكس الجزء المعروف.",
    "（Partial cost data — coverage ": " (التغطية ", "%）": "٪)",
    "时间范围费用为归属估算：Hermes 当前仅保存累计 usage row，跨时间边界的调用无法精确拆分。（Time-window cost is attribution-based.）":
      "تكاليف النافذة الزمنية هي تقديرات بالإسناد — يخزّن Hermes حاليًا صفوف الاستخدام التراكمية فقط، لذا لا يمكن تقسيم الاستدعاءات التي تتجاوز حدود الوقت بدقة.",
    "Top Sessions（估算费用 · 脱敏标题）": "أفضل الجلسات (تكلفة مقدّرة · عناوين مموَّهة)",
    " 会话": " جلسة", "模型分布（估算费用）": "توزيع النماذج (تكلفة مقدّرة)",
    "费用为本地估算，非账单": "التكلفة تقدير محلي وليست فاتورة",
    "统计窗口": "نافذة الإحصاء", "API 调用": "استدعاءات API",
    "每日估算费用（": "التكلفة المقدّرة اليومية (", " · canonical /cost/timeseries）": " · القياسي /cost/timeseries)",
    "部分成本数据：趋势仅含定价来源已知的行。": "بيانات تكلفة جزئية: يتضمن الاتجاه فقط الصفوف ذات التسعير المعروف.",
    "每日输入 Token": "رموز الإدخال اليومية", "无数据": "لا توجد بيانات",
    "按模型 · 调用/Token（近 ": "حسب النموذج · الاستدعاءات/الرموز (آخر ",
    " 天 · 费用见上方 /cost/models）": " يوم · التكلفة أعلاه عبر /cost/models)",
    "调用": "الاستدعاءات", "辅助调用类型（近 ": "أنواع الاستدعاءات المساعدة (آخر ",
    " 天 · 仅调用数/Token）": " يوم · الاستدعاءات/الرموز فقط)",
    "无辅助调用数据": "لا توجد بيانات استدعاءات مساعدة",
    "辅助调用 = session_model_usage.task != ''（compression / vision / title_generation / background_review 等）。主会话与辅助调用已分开归集，不重复计数。":
      "الاستدعاءات المساعدة = session_model_usage.task != '' (ضغط / رؤية / توليد عنوان / مراجعة خلفية، إلخ). تُحتسب الجلسات الرئيسية والاستدعاءات المساعدة بشكل منفصل — دون احتساب مزدوج.",
    "任务类型": "نوع المهمة",
    "口径：主会话读 sessions 表；辅助调用读 session_model_usage.task != ''；按 (session, model, task) 去重后合并。日界线使用 HUD 配置时区。 所有费用均为估算（estimated），非账单。":
      "المنهجية: تُقرأ الجلسات الرئيسية من جدول sessions؛ تُقرأ الاستدعاءات المساعدة من session_model_usage.task != ''؛ يتم إزالة التكرار والدمج حسب (الجلسة، النموذج، المهمة). تستخدم حدود اليوم المنطقة الزمنية المُهيّأة لـ HUD. جميع التكاليف تقديرية وليست فواتير.",

    "搜索标题 / ID / 用户…": "بحث عن العنوان / المعرّف / المستخدم…", "搜索": "بحث",
    "搜索: ": "بحث: ", " 条": " عنصر", "会话详情": "تفاصيل الجلسة",
    "会话列表": "قائمة الجلسات", "返回列表": "العودة إلى القائمة", "消息": "الرسائل",
    "工具调用": "استدعاءات الأدوات", "开始": "بدأ في",
    "消息预览（正文按需加载，已脱敏）": "معاينة الرسائل (يُحمَّل المحتوى عند الطلب، مموَّه)",
    "(空)": "(فارغ)", "会话内模型调用": "استدعاءات النموذج داخل الجلسة",
    "费用": "التكلفة", "(主)": "(رئيسي)", "加载会话详情…": "جارٍ تحميل تفاصيل الجلسة…",
    "无会话记录": "لا توجد سجلات جلسات", "标题": "العنوان",
    "点击查看详情": "انقر لعرض التفاصيل",

    "记忆文件": "ملفات الذاكرة", "文件": "الملف", "大小": "الحجم",
    "分节": "الأقسام", "更新": "آخر تحديث", "Provider 与锁": "المزوّد والأقفال",
    "记忆卡片(§ 分节)": "بطاقات الذاكرة (§ أقسام)", "锁文件": "ملفات القفل",
    "无锁文件": "لا توجد ملفات قفل", " — 锁超过 10 分钟未释放!": " — القفل محتجز منذ أكثر من 10 دقائق!",
    "记忆正文不进总览事件流；此页只展示元数据。写入失败/锁异常由健康规则上报。":
      "محتوى الذاكرة لا يدخل في تدفق أحداث النظرة العامة؛ تعرض هذه الصفحة البيانات الوصفية فقط. يتم الإبلاغ عن أخطاء الكتابة/شذوذ الأقفال عبر قواعد السلامة.",

    "任务总数": "إجمالي المهام", "启用": "مفعّلة", "暂停/禁用": "متوقفة/معطّلة",
    "任务列表 (": "قائمة المهام (", "无任务": "لا توجد مهام", "任务": "المهام",
    "排程": "الجدولة", "下次运行": "التشغيل القادم", "上次": "الأخيرة", "投递": "التسليم",
    "m 后": "د متبقية", "暂停": "متوقفة",
    "执行历史 (最近 ": "سجل التنفيذ (آخر ", " 条)": ")",
    "无执行记录": "لا توجد سجلات تنفيذ", "耗时": "المدة",
    "状态未知 / 孤儿进程": "حالة غير معروفة / عملية يتيمة",
    "执行历史来自 cron/executions.db（claimed→running→completed/failed 状态机）。成功率/连续失败统计见后端 rules；编辑/暂停/手动触发请跳转 Dashboard 的 Cron 页。":
      "يأتي سجل التنفيذ من cron/executions.db (آلة الحالات claimed→running→completed/failed). إحصاءات معدل النجاح/الإخفاقات المتتالية موجودة في قواعد الخلفية؛ للتعديل/الإيقاف المؤقت/التشغيل اليدوي انتقل إلى صفحة Cron في Dashboard.",

    "无渠道数据": "لا توجد بيانات قنوات", "已连接 · 心跳陈旧": "متصل · نبضة قديمة",
    "更新时间": "وقت التحديث", "心跳龄": "عمر النبضة", "需关注": "يحتاج انتباه",
    "是": "نعم", "否": "لا", "错误码": "رمز الخطأ",
    "已连接但持续抖动：": "متصل لكنه متذبذب: ",
    " 无状态更新 — 需结合错误日志判断": " دون تحديث للحالة — راجع سجلات الأخطاء للتأكد",
    "渠道状态来自 gateway_state.json。'connected' 是瞬时快照，稳定性要结合心跳龄与 errors.log 判定 —— 例如飞书当前 connected 但日志每 ~2 分钟重连。重连计数等更细的抖动指标在错误事故页。":
      "تأتي حالة القناة من gateway_state.json. تمثل 'connected' لقطة لحظية — احكم على الاستقرار عبر عمر النبضة مع errors.log (مثلاً قد تظهر Feishu كـ connected بينما تعيد الاتصال كل ~دقيقتين تقريبًا في السجلات). مقاييس التذبذب الأدق مثل عدد إعادة الاتصال موجودة في صفحة الأخطاء والحوادث.",

    "近 30 分钟错误": "الأخطاء (آخر 30 دقيقة)", "错误指纹": "بصمات الأخطاء",
    "活跃事故": "الحوادث النشطة", "事故总数": "إجمالي الحوادث",
    "事故时间线 (telemetry.db)": "الجدول الزمني للحوادث (telemetry.db)",
    "暂无事故记录": "لا توجد سجلات حوادث بعد", "进行中": "نشطة", "已恢复": "تم الحل",
    "首次 ": "أول ظهور ", " · 末次 ": " · آخر ظهور ", " · 观测 ": " · ", " 次": " مرة",
    "错误指纹 TOP": "أهم بصمات الأخطاء", "近 30 分钟无错误": "لا توجد أخطاء في آخر 30 دقيقة",
    "errors.log 尾部（脱敏）": "نهاية errors.log (مموَّه)", "无内容": "لا يوجد محتوى",
    "agent.log 尾部（脱敏）": "نهاية agent.log (مموَّه)",
    "日志按异常指纹去重聚合；关键字与凭据模式已脱敏；完整原始日志请到 Dashboard 的日志页查看。":
      "يتم إزالة التكرار من السجلات وتجميعها حسب بصمة الخطأ؛ يتم تمويه الكلمات المفتاحية وأنماط بيانات الاعتماد. راجع صفحة السجلات في Dashboard للاطلاع على السجلات الخام الكاملة.",

    "CPU / 负载": "المعالج / الحمل", "CPU 使用": "استخدام المعالج", "核心数": "الأنوية",
    "负载": "الحمل", "使用率": "نسبة الاستخدام", "已用": "المستخدم", "总计": "الإجمالي",
    "磁盘 (Hermes 目录)": "القرص (مجلد Hermes)", "剩余": "المتاح", "可用": "المتوفر",
    "总容量": "السعة الإجمالية", "磁盘压力": "ضغط القرص", "进程": "العمليات",
    "数据库": "قاعدة البيانات", "服务托管": "استضافة الخدمة",
    "launchd 托管": "تتم إدارته بواسطة launchd", "未由 launchd 托管": "لا تتم إدارته بواسطة launchd",
    "服务定义": "تعريف الخدمة", "无 plist": "لا يوجد plist",
    "Gateway 重启后可能不自启 — 建议修复": "قد لا تبدأ Gateway تلقائيًا بعد إعادة التشغيل — يُنصح بالإصلاح",
    "CPU 趋势 (telemetry)": "اتجاه المعالج (telemetry)",
    "数据积累中（约 60s 一个点）": "جارٍ جمع البيانات (~نقطة كل 60 ثانية)",
    "内存趋势": "اتجاه الذاكرة", "数据积累中": "جارٍ جمع البيانات",
    "磁盘剩余趋势": "اتجاه المساحة الحرة بالقرص",
    "时序数据保存在 ~/.hermes/hud/telemetry.db（分钟级，保留 ": "تُخزَّن البيانات الزمنية في ~/.hermes/hud/telemetry.db (كل دقيقة، وتُحفظ لمدة ",
    " 天），不触碰 state.db。": " يومًا)؛ لا يتم لمس state.db أبدًا.",

    "全部": "الكل", "技能总数": "إجمالي المهارات", "分类数": "الفئات",
    "近 24h 新增/修改": "جديدة/معدَّلة (24 س)", "近 7 天活动": "نشطة (7 أيام)",
    "分类分布 (": "توزيع الفئات (", "分类筛选": "تصفية حسب الفئة",
    "技能列表 (": "قائمة المهارات (", "该分类下无技能": "لا توجد مهارات ضمن هذه الفئة",
    "技能": "المهارة", "分类": "الفئة", "最近修改": "آخر تعديل", "描述": "الوصف",
    "技能目录 ~/.hermes/skills/（只读扫描 SKILL.md 元数据）。安装/删除请到 Dashboard 的 Skills 页。":
      "دليل المهارات ~/.hermes/skills/ (فحص للقراءة فقط لبيانات SKILL.md الوصفية). التثبيت/الإزالة من صفحة Skills في Dashboard.",

    "阈值与预算（rules.py）": "العتبات والميزانيات (rules.py)",
    "采集器数据质量": "جودة بيانات جامعات البيانات", "全部采集器正常": "جميع الجامعات تعمل بشكل طبيعي",
    "部分采集器异常": "بعض الجامعات متعطّلة جزئيًا", "统计时区": "المنطقة الزمنية للإحصاء",
    "HUD_TIMEZONE > 系统本地时区 > UTC；快照缓存 TTL ": "HUD_TIMEZONE > المنطقة الزمنية المحلية للنظام > UTC؛ مدة صلاحية ذاكرة اللقطة المؤقتة ",
    "s / telemetry 落盘每 ": "ث / يُكتب telemetry كل ", "s 一次": "ث",
    "指标行": "صفوف المقاييس", "事故记录": "سجلات الحوادث", "库大小": "حجم قاعدة البيانات",
    "安全边界": "الحدود الأمنية",
    "• 默认仅监听 127.0.0.1，沿用 Dashboard 鉴权": "• يستمع افتراضيًا على 127.0.0.1 فقط، ويعيد استخدام مصادقة Dashboard",
    "• 不读取/返回 .env、auth.json、完整 token": "• لا يقرأ/يعيد أبدًا .env أو auth.json أو الرموز الكاملة",
    "• 日志/对话/记忆经脱敏与按需加载": "• السجلات/المحادثات/الذاكرة تُموَّه وتُحمَّل عند الطلب",
    "• telemetry.db 只存聚合、指纹与短摘要": "• يخزّن telemetry.db فقط التجميعات والبصمات والملخصات القصيرة",
    "• 无 outbound 遥测，不自动查询外部账单": "• لا توجد قياسات صادرة؛ لا يستعلم تلقائيًا عن الفوترة الخارجية",
    "• HUD 纯观察；操作跳转现有 Dashboard 受保护页面": "• HUD للمراقبة فقط؛ الإجراءات تُوجَّه إلى صفحات Dashboard المحمية الحالية",
    "Dashboard 界面语言": "لغة واجهة Dashboard", "当前：": "الحالي: ",
    "此处切换会立即应用到整个 Dashboard（含本插件），并保存在浏览器 localStorage，与系统重启无关。更多语言可在 Dashboard 顶部的语言切换器中选择。":
      "يُطبَّق التبديل هنا فورًا على كامل Dashboard (بما في ذلك هذه الإضافة) ويُحفظ في localStorage للمتصفح — يبقى بعد إعادة التشغيل. تتوفر لغات إضافية من محوّل اللغة أعلى Dashboard.",
    "刷新频率：snapshot 2s / usage·metrics 30s / settings·quality 30-60s；阈值可用 HUD_* 环境变量覆盖（见后端 rules.py）。":
      "معدل التحديث: اللقطة 2 ث / الاستخدام والمقاييس 30 ث / الإعدادات والجودة 30-60 ث؛ يمكن تجاوز العتبات عبر متغيرات بيئة HUD_* (راجع rules.py في الخلفية).",

    "指挥中心": "مركز القيادة", "实时活动": "النشاط المباشر", "Token·费用": "الرموز · التكلفة",
    "对话记录": "المحادثات", "时间线": "الجدول الزمني", "记忆": "الذاكرة", "技能分析": "تحليلات المهارات",
    "定时任务": "المهام المجدولة", "错误·事故": "الأخطاء والحوادث", "系统·存储": "النظام والتخزين",
    "设置": "الإعدادات",

    "全部状态": "جميع الحالات", " 条新事件": " حدثًا جديدًا", "加载失败: ": "فشل التحميل: ",
    "暂无事件（全新安装的正常状态；有新活动后自动出现）": "لا توجد أحداث بعد (طبيعي في التثبيت الجديد — يظهر تلقائيًا عند وجود نشاط جديد)",
    "加载更多": "تحميل المزيد", " 条新事件（点击载入）": " حدثًا جديدًا (انقر للتحميل)",
    "Agent Timeline — 做了什么？": "Agent Timeline — ماذا حدث؟", "类型": "النوع",
    "时长": "المدة", "关联": "الارتباط",

    "已观测": "مُلاحَظ", "仅清单": "القائمة فقط", "不可用": "غير متاح",
    "已注册技能": "المهارات المسجَّلة", "已观测执行": "التنفيذات المُلاحَظة",
    "观测运行次数": "عدد مرات التشغيل المُلاحَظة", "成功率": "معدل النجاح", "失败次数": "مرات الفشل",
    "未观测到执行": "لم يُلاحَظ أي تنفيذ",
    "运行观测覆盖目前不完整；统计仅包含具有可靠身份的 Skill 执行事件。":
      "تغطية الرصد أثناء التشغيل جزئية حاليًا؛ تشمل الإحصاءات فقط أحداث تنفيذ المهارات ذات الهوية الموثوقة.",
    "有失败": "بها فشل", "有成功": "بها نجاح",
    "搜索技能名…": "البحث باسم المهارة…", "按名称": "حسب الاسم", "运行最多": "الأكثر تشغيلاً",
    "失败最多": "الأكثر فشلاً", "成功率最低": "أدنى معدل نجاح", "最近运行": "الأحدث تشغيلاً",
    "覆盖": "التغطية", "风险": "المخاطر", "健康": "السلامة", "Review 决策": "قرار المراجعة",
    "来源 / Provenance": "المصدر / الأصل", "平均耗时": "متوسط المدة",
    "最近观测": "آخر ملاحظة",
    "最近 Timeline 事件（直接引用，不复制）": "أحداث Timeline الأخيرة (بالإشارة المباشرة، دون نسخ)",
    "未观测到执行（No observed executions）": "لم يُلاحَظ أي تنفيذ",
    "Skill Analytics — 技能运行观测（observed truth only）": "Skill Analytics — رصد تشغيل المهارات (الحقيقة المُلاحَظة فقط)",
    "暂无技能数据（registry 或 timeline 不可用时的正常降级）": "لا توجد بيانات مهارات بعد (سلوك احتياطي طبيعي عند عدم توفر السجل أو Timeline)",
    "共 ": "", " 个技能（分页上限 200，可搜索/过滤缩小范围）": " مهارة إجمالاً (الحد الأقصى للصفحة 200؛ استخدم البحث/التصفية لتضييق النطاق)",

    " 红 / ": " أحمر / ", " 黄": " أصفر", "离线": "متوقف", " 启用": " مفعّلة",
    "WS 实时": "WS مباشر", "WS 重连中": "WS إعادة اتصال", "轮询": "استطلاع", "模式": "الوضع",

    "th_runtime": "المدة", "th_runs": "مرات التشغيل", "th_task": "المهمة",
  };

  const HUD_DICTS = { en: EN, fr: FR, ar: AR };

  function tt(zh, key) {
    if (CURRENT_LOCALE === "zh" || CURRENT_LOCALE === "zh-hant") return zh;
    const k = key || zh;
    const dict = HUD_DICTS[CURRENT_LOCALE] || HUD_DICTS.en;
    if (Object.prototype.hasOwnProperty.call(dict, k)) return dict[k];
    if (Object.prototype.hasOwnProperty.call(HUD_DICTS.en, k)) return HUD_DICTS.en[k];
    return zh;
  }

  /**
   * 事故文案：优先用后端按请求语言渲染的 display_*，回退到 canonical
   * title/detail（恒 zh）。/incidents 读的是 telemetry.db 历史行，只有
   * canonical 字段，回退即可；见 hud/rules.py 的 _inc_text。
   */
  function incTitle(inc) { return inc.display_title || inc.title; }
  function incDetail(inc) { return inc.display_detail || inc.detail; }

  function dtLocale() {
    if (CURRENT_LOCALE === "zh" || CURRENT_LOCALE === "zh-hant") return "zh-CN";
    if (CURRENT_LOCALE === "fr") return "fr-FR";
    if (CURRENT_LOCALE === "ar") return "ar";
    return "en-US";
  }

  /** 给后端 API 请求带上当前语言（health/收集器的动态文案由后端渲染，见 hud/i18n.py）。 */
  function withLocale(url) {
    const sep = url.indexOf("?") >= 0 ? "&" : "?";
    return url + sep + "locale=" + encodeURIComponent(CURRENT_LOCALE);
  }

  // -------------------------------------------------------------------------
  // 格式化工具
  // -------------------------------------------------------------------------

  function fmtBytes(n) {
    if (n == null || isNaN(n)) return "-";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
    return (n / 1073741824).toFixed(2) + " GB";
  }

  function fmtTokens(n) {
    if (n == null || isNaN(n)) return "-";
    if (n < 1000) return String(Math.round(n));
    if (n < 1000000) return (n / 1000).toFixed(1) + "k";
    if (n < 1000000000) return (n / 1000000).toFixed(2) + "M";
    return (n / 1000000000).toFixed(2) + "B";
  }

  function fmtUSD(n) {
    if (n == null || isNaN(n)) return "-";
    return "$" + n.toFixed(n < 1 ? 4 : 2);
  }

  function fmtPct(n) {
    if (n == null || isNaN(n)) return "-";
    return n.toFixed(1) + "%";
  }

  function fmtTime(ts) {
    if (!ts) return "-";
    const d = new Date(ts * 1000);
    return d.toLocaleString(dtLocale(), {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      second: "2-digit", hour12: false,
    });
  }

  function fmtDay(day) {
    return day; // "2026-08-23"
  }

  function dotClass(ok, warn) {
    if (ok === true) return "hud-dot-ok";
    if (ok === false) return warn ? "hud-dot-warn" : "hud-dot-bad";
    return "hud-dot-mute";
  }

  function healthClass(level) {
    return "hud-health-" + (level === "critical" ? "critical" : level === "warning" ? "warning" : "normal");
  }

  function healthLabel(level) {
    return tt(level === "critical" ? "故障" : level === "warning" ? "警告" : "正常");
  }

  /** 渠道状态 */
  function stateZh(s) {
    if (s === "connected") return tt("已连接");
    if (s === "disconnected") return tt("已断开");
    if (s === "connecting") return tt("连接中");
    if (s === "reconnecting") return tt("重连中");
    if (s === "error") return tt("错误");
    return s || tt("未知");
  }

  /** Cron 状态 */
  function statusZh(s) {
    if (s === "ok" || s === "completed") return tt("成功");
    if (s === "error" || s === "failed") return tt("失败");
    if (s === "running") return tt("运行中");
    if (s === "claimed") return tt("已认领");
    if (s === "unknown") return tt("未知");
    return s || tt("待运行");
  }

  function kv(k, v) {
    return h("div", { className: "hud-kv", key: k },
      h("span", { className: "k" }, k),
      h("span", { className: "v" }, v));
  }

  function card(title, body, extra) {
    return h(Card, { key: title },
      h(CardContent, { style: { padding: "12px 14px" } },
        h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 } },
          h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.75 } }, title),
          extra || null),
        body));
  }

  // 空状态
  function empty(text) {
    return h("div", { style: { padding: 18, textAlign: "center", opacity: 0.5, fontSize: 13 } }, text);
  }

  // -------------------------------------------------------------------------
  // 数据 hooks
  // -------------------------------------------------------------------------

  /** 通用轮询 hook：url 每 interval ms 拉一次，返回 {data, error, lastAt}。
   *  自动带上当前语言（locale 变化时 fullUrl 变化，effect 自动重新拉取）。 */
  function usePoll(url, interval) {
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [lastAt, setLastAt] = useState(null);
    const fullUrl = withLocale(url);
    useEffect(() => {
      let alive = true;
      async function tick() {
        try {
          const d = await SDK.fetchJSON(fullUrl);
          if (!alive) return;
          setData(d);
          setError(null);
          setLastAt(Date.now());
        } catch (e) {
          if (alive) setError(String(e && e.message ? e.message : e));
        }
      }
      tick();
      const t = setInterval(tick, interval);
      return () => { alive = false; clearInterval(t); };
    }, [fullUrl, interval]);
    return { data, error, lastAt };
  }

  /** 单次 fetch（点击/搜索触发），同样带上当前语言。 */
  function useOnce() {
    const [state, setState] = useState({ loading: false, data: null, error: null });
    const run = useCallback(async (url) => {
      setState({ loading: true, data: null, error: null });
      try {
        const d = await SDK.fetchJSON(withLocale(url));
        setState({ loading: false, data: d, error: null });
      } catch (e) {
        setState({ loading: false, data: null, error: String(e && e.message ? e.message : e) });
      }
    }, []);
    return [state, run];
  }

  /** 事件流去重键 */
  function evKey(e) {
    return e.type + ":" + e.sub + ":" + e.event + ":" + Math.round(e.ts);
  }

  // -------------------------------------------------------------------------
  // 迷你柱状图
  // -------------------------------------------------------------------------

  function MiniBars({ values, height, fmt }) {
    const max = Math.max.apply(null, values.concat([1]));
    return h("div", { className: "hud-bars", style: { height: height || 90 } },
      values.map(function (v, i) {
        const pct = Math.max(2, (v / max) * 100);
        return h("div", {
          key: i,
          className: "hud-bar",
          style: { height: pct + "%" },
          title: fmt ? fmt(v, i) : String(v),
        });
      }));
  }

  // -------------------------------------------------------------------------
  // 指挥中心
  // -------------------------------------------------------------------------

  function Overview({ snap, health }) {
    if (!snap) return empty(tt("加载中…"));
    const gw = snap.gateway || {};
    const sys = snap.system || {};
    const db = snap.db || {};
    const cron = snap.cron || {};
    const today = db.today_sessions || {};
    const mem = sys.memory || {};
    const platforms = gw.platforms || {};

    // C-1: 今日估算 = canonical estimated（unpriced aux 不得计入估算）
    const totalCost = today.estimated_cost_usd || 0;
    const checks = (health && health.checks) || [];
    const incidents = (health && health.incidents) || [];

    return h(React.Fragment, null,
      // 快速指标行
      h("div", { className: "hud-grid hud-grid-4" },
        card("Gateway",
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            h("div", { style: { fontSize: 15, fontWeight: 700 } },
              h("span", { className: "hud-dot " + dotClass(gw.alive, false) }),
              gw.alive ? tt("运行中") : tt("未运行"),
              gw.pid ? h("span", { style: { opacity: 0.5, fontSize: 11, marginLeft: 6 } }, "PID " + gw.pid) : null),
            kv(tt("状态"), gw.state || "-"),
            kv(tt("版本"), gw.code_version || "-"),
            kv(tt("活跃 Agent"), String(gw.active_agents || 0)))),
        card(tt("渠道"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            Object.keys(platforms).map(function (name) {
              const p = platforms[name];
              const ok = p.state === "connected";
              const stale = (p.heartbeat_age || 0) > 60;
              return h("div", { key: name, style: { display: "flex", alignItems: "center", gap: 8 } },
                h("span", { className: "hud-dot " + dotClass(ok, stale) }),
                h("span", { style: { fontWeight: 600, width: 70 } }, name),
                h("span", { style: { opacity: ok ? 0.85 : 1, color: ok ? undefined : "#f87171" } },
                  stateZh(p.state) + (stale ? tt("（心跳陈旧）") : "")),
                stale ? h(Badge, { variant: "warning" }, tt("抖动")) : null);
            }))),
        card(tt("今日 Token / 费用"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv(tt("输入"), fmtTokens(today.input_tokens)),
            kv(tt("输出"), fmtTokens(today.output_tokens)),
            kv(tt("Cache 读"), fmtTokens(today.cache_read_tokens)),
            h("div", { style: { display: "flex", alignItems: "baseline", gap: 6 } },
              h("span", { className: "k" }, tt("估算费用")),
              h("span", { className: "v", style: { fontSize: 16, fontWeight: 700 } }, fmtUSD(totalCost)),
              h(Badge, { variant: "secondary" }, tt("估算"))))),
        card(tt("Cron / 会话"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv(tt("任务"), cron.summary ? (cron.summary.enabled + tt(" 启用 / ") + cron.summary.total + tt(" 总")) : "-"),
            kv(tt("执行中"), String((cron.summary && cron.summary.running_state) || 0)),
            kv(tt("失败中"), String((cron.summary && cron.summary.failing) || 0)),
            kv(tt("活跃会话"), String((snap.active_sessions || []).length))))),

      // 健康检查 + 事故
      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("健康检查 (") + (checks.length) + tt(" 项)"),
          h("div", { className: "hud-scroll" },
            checks.map(function (c) {
              const sev = c.severity;
              return h("div", { key: c.key, className: "hud-check" },
                h("span", { className: "hud-dot " + dotClass(sev === "normal", sev === "warning") }),
                h("span", { style: { flex: 1 } }, c.message));
            }))),
        card(tt("事故时间线 (最近 ") + Math.min(10, incidents.length) + ")",
          incidents.length === 0
            ? h("div", { style: { padding: 10, fontSize: 13, opacity: 0.6 } }, tt("当前无活跃事故"))
            : h("div", { className: "hud-scroll" },
              incidents.map(function (inc) {
                return h("div", { key: inc.fingerprint, className: "hud-incident " + inc.severity },
                  h("div", { style: { fontWeight: 600, fontSize: 13 } }, incTitle(inc)),
                  h("div", { style: { opacity: 0.7, fontSize: 11.5, marginTop: 2 } }, incDetail(inc)));
              })))),

      // 系统迷你
      h("div", { className: "hud-grid hud-grid-4" },
        card("CPU", h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtPct(sys.cpu_percent))),
        card(tt("内存"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtPct(mem.percent),
          h("div", { style: { fontSize: 11, opacity: 0.6, marginTop: 2 } }, fmtBytes(mem.used) + " / " + fmtBytes(mem.total)))),
        card(tt("磁盘剩余"), h("div", {
          style: { fontSize: 20, fontWeight: 700, color: (sys.disk_free_percent != null && sys.disk_free_percent < 15) ? "#facc15" : undefined },
        }, fmtPct(sys.disk_free_percent))),
        card(tt("机器运行"), h("div", { style: { fontSize: 15, fontWeight: 600 } },
          sys.uptime_seconds ? Math.round(sys.uptime_seconds / 86400) + tt(" 天") : "-"))),

      h("div", { className: "hud-footnote" },
        tt("采集于 ") + (snap.generated_at_iso || fmtTime(snap.collected_at)) +
        tt(" · 时区 ") + (snap.tz || "-") + tt(" · 数据为本地只读采集")));
  }

  // -------------------------------------------------------------------------
  // 实时活动
  // -------------------------------------------------------------------------

  function Live({ snap, events, wsState }) {
    if (!snap) return empty(tt("加载中…"));
    const sessions = snap.active_sessions || [];
    const gw = snap.gateway || {};
    const tools = usePoll(API + "/tool-events?limit=60", 10000).data || [];

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("活跃会话 (") + sessions.length + ")",
          sessions.length === 0
            ? empty(tt("当前无活跃会话"))
            : h("div", { className: "hud-scroll" },
              h("table", { className: "hud-table" },
                h("thead", null, h("tr", null,
                  h("th", null, tt("标题 / ID")),
                  h("th", null, tt("模型")),
                  h("th", null, tt("来源")),
                  h("th", null, tt("运行", "th_runtime")),
                  h("th", null, "Token"))),
                h("tbody", null, sessions.slice(0, 40).map(function (s) {
                  return h("tr", { key: s.id },
                    h("td", null,
                      h("div", { style: { fontWeight: 600 } }, (s.title || tt("(无标题)")).slice(0, 46)),
                      h("div", { className: "mono", style: { opacity: 0.55, fontSize: 10.5 } }, s.id.slice(0, 20))),
                    h("td", null, s.model || "-"),
                    h("td", null, s.source || "-"),
                    h("td", { className: "num" }, s.running_seconds ? Math.round(s.running_seconds / 60) + "m" : "-"),
                    h("td", { className: "num" }, fmtTokens(s.input_tokens)));
                }))))),
        card(tt("实时事件流") + (wsState === "connected" ? "" : tt(" (轮询模式)")),
          events.length === 0
            ? empty(tt("暂无事件"))
            : h("div", { className: "hud-events" },
              events.slice(0, 120).map(function (e, i) {
                const label = e.type + "·" + (e.sub || "") + " " + e.event +
                  (e.to ? " → " + e.to : "") + (e.status ? " [" + e.status + "]" : "") +
                  (e.state ? " (" + e.state + ")" : "");
                return h("div", { key: evKey(e) + i, className: "hud-event" },
                  h("span", { className: "ts" }, fmtTime(e.ts).slice(11)),
                  h("span", { style: { opacity: 0.85 } }, label));
              })))),
      card(tt("最近工具调用 (") + tools.length + ")",
        tools.length === 0 ? empty(tt("暂无工具调用记录")) :
        h("div", { className: "hud-scroll", style: { maxHeight: 300 } },
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, tt("时间")), h("th", null, tt("会话")), h("th", null, tt("工具")), h("th", null, tt("调用参数工具")))),
            h("tbody", null, tools.map(function (t, i) {
              return h("tr", { key: i },
                h("td", { className: "num", style: { fontSize: 11 } }, fmtTime(t.ts).slice(11)),
                h("td", { style: { maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, t.title),
                h("td", null, h(Badge, { variant: "secondary" }, t.tool_name)),
                h("td", { style: { fontSize: 10.5, opacity: 0.7 } },
                  (t.tool_calls || []).join(", ") || "-"));
            }))))),

      h("div", { className: "hud-footnote" },
        tt("事件流每秒级增量（channel/cron/session/health/gateway 状态变化）；工具调用为轻量版（从 messages 推断），精确 tool start/end 生命周期需插件 hook（第二版）。")));
  }

  // -------------------------------------------------------------------------
  // Token 与费用
  // -------------------------------------------------------------------------

  function Usage() {
    const [days, setDays] = useState(30);
    const [ciRange, setCiRange] = useState("7d");
    const { data, error } = usePoll(API + "/usage?days=" + days, 30000);
    const snap = usePoll(API + "/snapshot", 30000).data;
    const totals = (data && data.totals) || {};
    const byDay = (data && data.by_day) || [];
    const byModel = (data && data.by_model) || [];
    const byTask = (data && data.by_task) || [];

    // —— Cost Intelligence v1（canonical = session_model_usage，估算语义）——
    const ci = usePoll(API + "/cost/summary?range=" + ciRange, 15000).data;
    const ciModels = usePoll(API + "/cost/models?range=" + ciRange, 15000).data;
    const ciSessions = usePoll(API + "/cost/sessions?range=" + ciRange + "&limit=10", 15000).data;
    const ciBudget = usePoll(API + "/cost/budget", 15000).data;
    const ciTS = usePoll(API + "/cost/timeseries?range=" + ciRange, 15000).data;  // canonical 趋势

    const ciRanges = [
      { id: "today", label: tt("今日") }, { id: "24h", label: "24h" },
      { id: "7d", label: "7d" }, { id: "30d", label: "30d" }, { id: "all", label: "All" },
    ];
    const ciFmt = function (v) {
      return (v === null || v === undefined) ? "—" : "$" + v.toFixed(2);
    };
    const ciFmtTok = function (v) {
      return (v === null || v === undefined) ? "—" : v.toLocaleString();
    };
    const ciPart = ci && (ci.partial || ci.coverage && !ci.coverage.cost_complete);
    // 非 All 范围：累计 usage row 归属估算（window_exact=false）
    const ciAttrib = ci && ci.window_exact === false;
    const ciBudgetUncertain = ciBudget && ciBudget.budget_status === "attribution_uncertain";
    // 金额显示规则（partial row truth）：complete → $X；known>0 → 已知部分；
    // known=0 → —（定价未知）；禁止 $0.000 冒充
    function ciCostCell(s) {
      if (!s) return "—";
      if (s.cost_complete) return "$" + (s.estimated_cost_usd || 0).toFixed(3);
      if (s.pricing_known_rows > 0) {
        return tt("已知部分 $") + (s.estimated_cost_usd || 0).toFixed(3) +
          " · " + Math.round((s.pricing_coverage_ratio || 0) * 100) + "%";
      }
      return tt("—（定价未知）");
    }
    const ciEmptyText = (ci && ci.source_status === "unavailable")
      ? tt("费用数据源不可用") : tt("暂无费用数据");

    const ciCards = [
      { k: tt("估算费用"), v: ciFmt(ci && ci.estimated_cost_usd) },
      { k: tt("总 Token"), v: ciFmtTok(ci && ci.total_tokens) },
      { k: tt("输入 Token"), v: ciFmtTok(ci && ci.input_tokens) },
      { k: tt("输出 Token"), v: ciFmtTok(ci && ci.output_tokens) },
      { k: "Sessions", v: (ci && ci.sessions === null || ci && ci.sessions === undefined) ? "—" : (ci ? ci.sessions : "—") },
      { k: tt("平均每 Session"), v: ciFmt(ci && ci.avg_cost_per_session_usd) },
    ];
    if (ciBudget && ciBudget.budget_configured) {
      ciCards.push({ k: tt("今日归属估算费用"), v: ciFmt(ciBudget.today_estimated_cost_usd) });
      if (ciBudgetUncertain) {
        ciCards.push({ k: tt("今日预算比例"), v: tt("不可用（累计数据）") });
      } else if (ciBudget.usage_ratio !== null && ciBudget.usage_ratio !== undefined) {
        ciCards.push({ k: tt("今日预算使用率"), v: (ciBudget.usage_ratio * 100).toFixed(1) + "%" });
      }
    }

    // canonical 趋势（/cost/timeseries，遵守 window/coverage 语义）
    const tsPoints = (ciTS && ciTS.points) || [];
    const tsVals = tsPoints.map(function (p) { return p.estimated_cost_usd; });
    const tsLabels = tsPoints.map(function (p) { return p.date.slice(5); });
    const tsPartial = ciTS && ciTS.pricing_coverage && ciTS.pricing_coverage.partial;

    const dayLabels = byDay.map(function (d) { return d.day.slice(5); });
    const inVals = byDay.map(function (d) { return d.input; });

    return h(React.Fragment, null,
      // —— Cost Intelligence 区块（Phase 10-11）——
      h("div", { style: { display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 } },
        h("span", { className: "k", style: { fontSize: 12, opacity: 0.6 } }, tt("Cost Intelligence · 范围")),
        ciRanges.map(function (r) {
          return h(Button, {
            key: r.id, size: "sm", variant: ciRange === r.id ? "default" : "outline",
            onClick: function () { setCiRange(r.id); },
            style: { padding: "2px 10px", fontSize: 12 },
          }, r.label);
        }),
        h(Badge, { variant: "secondary", style: { marginLeft: 8 } }, tt("估算费用 / Estimated cost（非账单）"))),
      ciPart ? h("div", { style: { fontSize: 12, padding: "6px 10px", background: "rgba(255,193,7,.12)", border: "1px solid rgba(255,193,7,.4)", borderRadius: 6, margin: "6px 0" } },
        tt("部分成本数据：仅部分 usage 记录含费用，汇总是已知部分。") +
        tt("（Partial cost data — coverage ") +
        (ci && ci.coverage ? Math.round((ci.coverage.pricing_coverage_ratio || 0) * 100) + tt("%）") : "—" + tt("%）"))) : null,
      ciAttrib ? h("div", { style: { fontSize: 11, padding: "4px 10px", opacity: 0.85, marginBottom: 4 } },
        tt("时间范围费用为归属估算：Hermes 当前仅保存累计 usage row，跨时间边界的调用无法精确拆分。（Time-window cost is attribution-based.）")) : null,
      h("div", { className: "hud-grid hud-grid-4", style: { marginTop: 8 } },
        ciCards.map(function (c) {
          return card(c.k, h("div", { style: { fontSize: 20, fontWeight: 700 } }, c.v));
        })),
      h("div", { className: "hud-grid hud-grid-2", style: { marginTop: 8 } },
        card(tt("Top Sessions（估算费用 · 脱敏标题）"),
          (ciSessions && ciSessions.sessions && ciSessions.sessions.length)
            ? h("div", null, ciSessions.sessions.slice(0, 8).map(function (s) {
                return h("div", { key: s.session_id, style: { display: "flex", gap: 8, alignItems: "baseline", padding: "3px 0", fontSize: 12, borderBottom: "1px solid var(--border)" } },
                  h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                    (s.title || s.session_id.slice(0, 20))),
                  h("span", { style: { opacity: 0.6, fontSize: 11 } }, s.models.join("/")),
                  h("span", { style: { fontWeight: 600, fontVariantNumeric: "tabular-nums" } }, ciCostCell(s)));
              }))
            : empty(ciEmptyText)),
        card(tt("模型分布（估算费用）"),
          (ciModels && ciModels.models && ciModels.models.length)
            ? h("div", null, ciModels.models.slice(0, 8).map(function (m) {
                return h("div", { key: m.model, style: { display: "flex", gap: 8, alignItems: "baseline", padding: "3px 0", fontSize: 12, borderBottom: "1px solid var(--border)" } },
                  h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, m.model),
                  h("span", { style: { opacity: 0.6, fontSize: 11 } }, m.sessions + tt(" 会话")),
                  h("span", { style: { fontWeight: 600, fontVariantNumeric: "tabular-nums" } }, ciCostCell(m)));
              }))
            : empty(ciEmptyText)),
        h(Badge, { variant: "secondary" }, tt("费用为本地估算，非账单"))),

      h("div", { style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 4 } },
        h("span", { className: "k", style: { fontSize: 12, opacity: 0.6 } }, tt("统计窗口")),
        [7, 30, 90].map(function (d) {
          return h(Button, {
            key: d, size: "sm", variant: days === d ? "default" : "outline",
            onClick: function () { setDays(d); },
            style: { padding: "2px 10px", fontSize: 12 },
          }, d + tt(" 天"));
        })),

      h("div", { className: "hud-grid hud-grid-4", style: { marginTop: 8 } },
        card(tt("输入 Token"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtTokens(totals.input))),
        card(tt("输出 Token"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtTokens(totals.output))),
        card(tt("Cache 读"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtTokens(totals.cache_read))),
        card(tt("API 调用"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, fmtTokens(totals.api_calls || 0)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("每日估算费用（") + ciRange + tt(" · canonical /cost/timeseries）"),
          tsVals.length ? h("div", null,
            h(MiniBars, { values: tsVals, height: 90, fmt: function (v, i) { return tsLabels[i] + " $" + v.toFixed(2); } }),
            tsPartial ? h("div", { style: { fontSize: 11, opacity: 0.75, padding: "4px 0" } },
              tt("部分成本数据：趋势仅含定价来源已知的行。")) : null,
            h("div", { style: { display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 } },
              tsLabels.slice(-14).map(function (d, i) {
                return h("span", { key: d, style: { fontSize: 10, opacity: 0.6, fontVariantNumeric: "tabular-nums" } }, d.slice(5));
              })))
            : empty(ciEmptyText)),
        card(tt("每日输入 Token"),
          inVals.length ? h(MiniBars, { values: inVals, height: 90, fmt: function (v, i) { return dayLabels[i] + " " + fmtTokens(v); } }) : empty(tt("无数据")))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("按模型 · 调用/Token（近 ") + days + tt(" 天 · 费用见上方 /cost/models）"),
          byModel.length === 0 ? empty(tt("无数据")) : h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, tt("模型")), h("th", { className: "num" }, tt("调用")), h("th", { className: "num" }, tt("输入")),
              h("th", { className: "num" }, tt("输出")))),
            h("tbody", null, byModel.map(function (m) {
              return h("tr", { key: m.model },
                h("td", { style: { fontWeight: 600 } }, m.model),
                h("td", { className: "num" }, String(m.api_calls || m.sessions || 0)),
                h("td", { className: "num" }, fmtTokens(m.input)),
                h("td", { className: "num" }, fmtTokens(m.output)));
            })))),
        card(tt("辅助调用类型（近 ") + days + tt(" 天 · 仅调用数/Token）"),
          byTask.length === 0
            ? h("div", null,
                empty(tt("无辅助调用数据")),
                h("div", { style: { fontSize: 11.5, opacity: 0.6, padding: "0 12px 12px" } },
                  tt("辅助调用 = session_model_usage.task != ''（compression / vision / title_generation / background_review 等）。主会话与辅助调用已分开归集，不重复计数。")))
            : h("table", { className: "hud-table" },
              h("thead", null, h("tr", null,
                h("th", null, tt("任务类型")), h("th", { className: "num" }, tt("调用")),
                h("th", { className: "num" }, tt("输入")))),
              h("tbody", null, byTask.map(function (t) {
                return h("tr", { key: t.task },
                  h("td", { style: { fontWeight: 600 } }, t.task),
                  h("td", { className: "num" }, String(t.api_calls)),
                  h("td", { className: "num" }, fmtTokens(t.input)));
              }))))),
      h("div", { className: "hud-footnote" },
        tt("口径：主会话读 sessions 表；辅助调用读 session_model_usage.task != ''；按 (session, model, task) 去重后合并。日界线使用 HUD 配置时区。 所有费用均为估算（estimated），非账单。")));
  }

  // -------------------------------------------------------------------------
  // 对话记录
  // -------------------------------------------------------------------------

  function SessionsTab() {
    const [q, setQ] = useState("");
    const [days, setDays] = useState(7);
    const { data } = usePoll(API + "/sessions?days=" + days + "&limit=100", 15000);
    const [detail, setDetail] = useState(null); // {loading, data, id}
    const [searchState, searchRun] = useOnce();

    const list = searchState.data ? searchState.data : (data || []);

    function openDetail(sid) {
      setDetail({ loading: true, data: null, id: sid });
      SDK.fetchJSON(API + "/sessions/" + encodeURIComponent(sid))
        .then(function (d) { setDetail({ loading: false, data: d, id: sid }); })
        .catch(function (e) { setDetail({ loading: false, data: null, id: sid, error: String(e) }); });
    }

    return h(React.Fragment, null,
      h("div", { style: { display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" } },
        h(Input, {
          placeholder: tt("搜索标题 / ID / 用户…"), value: q,
          style: { maxWidth: 300, fontSize: 13 },
          onChange: function (e) { setQ(e.target.value); },
          onKeyDown: function (e) {
            if (e.key === "Enter" && q.trim()) { searchRun(API + "/sessions/search?q=" + encodeURIComponent(q.trim())); }
          },
        }),
        h(Button, { size: "sm", variant: "outline", onClick: function () { if (q.trim()) searchRun(API + "/sessions/search?q=" + encodeURIComponent(q.trim())); } }, tt("搜索")),
        [3, 7, 14].map(function (d) {
          return h(Button, {
            key: d, size: "sm", variant: days === d ? "default" : "outline",
            onClick: function () { setDays(d); setSearchState ? null : null; },
            style: { padding: "2px 10px", fontSize: 12 },
          }, d + tt(" 天"));
        }),
        h(Badge, { variant: "secondary" }, searchState.data ? tt("搜索: ") + searchState.data.length + tt(" 条") : (data ? data.length + tt(" 条") : "…"))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(detail && detail.data ? tt("会话详情") : tt("会话列表"),
          detail && detail.data
            ? h("div", { className: "hud-detail" },
                h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 } },
                  h("div", { style: { fontWeight: 700, fontSize: 14 } }, (detail.data.title || tt("(无标题)")).slice(0, 80)),
                  h(Button, { size: "sm", variant: "outline", onClick: function () { setDetail(null); } }, tt("返回列表"))),
                h("div", { className: "hud-grid hud-grid-4", style: { marginBottom: 8 } },
                  kv(tt("来源"), detail.data.source || "-"), kv(tt("模型"), detail.data.model || "-"),
                  kv(tt("消息"), String(detail.data.message_count || 0)),
                  kv(tt("工具调用"), String(detail.data.tool_call_count || 0)),
                  kv(tt("输入"), fmtTokens(detail.data.input_tokens)), kv(tt("输出"), fmtTokens(detail.data.output_tokens)),
                  kv(tt("估算费用"), fmtUSD(detail.data.estimated_cost_usd)),
                  kv(tt("开始"), fmtTime(detail.data.started_at))),
                h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.7, margin: "8px 0 4px" } }, tt("消息预览（正文按需加载，已脱敏）")),
                h("div", { className: "hud-scroll" },
                  (detail.data.messages || []).map(function (m, i) {
                    return h("div", { key: i, className: "msg" },
                      h("span", { style: { fontWeight: 700, marginRight: 6, fontSize: 11, opacity: 0.7 } }, m.role),
                      h("span", { style: { opacity: 0.85 } }, m.preview || tt("(空)")));
                  })),
                (detail.data.model_usage || []).length ? h("div", null,
                  h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.7, margin: "10px 0 4px" } }, tt("会话内模型调用")),
                  h("table", { className: "hud-table" },
                    h("thead", null, h("tr", null, h("th", null, tt("模型")), h("th", null, tt("任务", "th_task")),
                      h("th", { className: "num" }, tt("调用")), h("th", { className: "num" }, "Token"), h("th", { className: "num" }, tt("费用")))),
                    h("tbody", null, detail.data.model_usage.map(function (u, i) {
                      return h("tr", { key: i },
                        h("td", null, u.model), h("td", null, u.task || tt("(主)")),
                        h("td", { className: "num" }, String(u.api_calls)),
                        h("td", { className: "num" }, fmtTokens(u.input_tokens)),
                        h("td", { className: "num" }, fmtUSD(u.estimated_cost_usd)));
                    }))))
                : null)
            : detail && detail.loading
              ? empty(tt("加载会话详情…"))
              : (list.length === 0 ? empty(tt("无会话记录")) :
                h("div", { className: "hud-scroll" },
                  h("table", { className: "hud-table" },
                    h("thead", null, h("tr", null,
                      h("th", null, tt("标题")), h("th", null, tt("来源")), h("th", null, tt("模型")),
                      h("th", { className: "num" }, tt("消息")), h("th", { className: "num" }, "Token"),
                      h("th", { className: "num" }, tt("费用")), h("th", null, tt("开始")))),
                    h("tbody", null, list.map(function (s) {
                      return h("tr", {
                        key: s.id, style: { cursor: "pointer" },
                        onClick: function () { openDetail(s.id); },
                        title: tt("点击查看详情"),
                      },
                        h("td", { style: { maxWidth: 260 } },
                          h("div", { style: { fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                            (s.title || tt("(无标题)")).slice(0, 60)),
                          h("div", { className: "mono", style: { opacity: 0.5, fontSize: 10 } }, s.id.slice(0, 24))),
                        h("td", null, s.source || "-"),
                        h("td", null, s.model || "-"),
                        h("td", { className: "num" }, String(s.message_count || 0)),
                        h("td", { className: "num" }, fmtTokens(s.input_tokens)),
                        h("td", { className: "num" }, fmtUSD(s.estimated_cost_usd)),
                        h("td", { className: "num", style: { fontSize: 11 } }, fmtTime(s.started_at).slice(5)));
                    }))))))));
  }

  // -------------------------------------------------------------------------
  // 记忆
  // -------------------------------------------------------------------------

  function MemoryTab({ snap }) {
    if (!snap) return empty(tt("加载中…"));
    const mem = snap.memory || {};
    const files = mem.files || {};
    const locks = mem.locks || {};

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("记忆文件"),
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, tt("文件")), h("th", { className: "num" }, tt("大小")),
              h("th", { className: "num" }, tt("分节")), h("th", null, tt("更新")))),
            h("tbody", null, Object.keys(files).map(function (name) {
              const f = files[name];
              return h("tr", { key: name },
                h("td", { style: { fontWeight: 600 } }, name),
                h("td", { className: "num" }, f ? fmtBytes(f.bytes) : "-"),
                h("td", { className: "num" }, f ? String(f.sections) : "-"),
                h("td", { className: "num", style: { fontSize: 11 } }, f ? fmtTime(f.mtime) : "-"));
            })))),
        card(tt("Provider 与锁"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 8, padding: 4 } },
            kv("Provider", mem.provider || "builtin"),
            kv(tt("记忆卡片(§ 分节)"), String((mem.stats && mem.stats.total_sections) || 0)),
            h("div", null,
              h("div", { style: { fontSize: 12, fontWeight: 600, opacity: 0.7, marginBottom: 4 } }, tt("锁文件")),
              Object.keys(locks).length === 0
                ? h("div", { style: { opacity: 0.5, fontSize: 12 } }, tt("无锁文件"))
                : Object.keys(locks).map(function (name) {
                  const l = locks[name];
                  return h("div", { key: name, style: { display: "flex", alignItems: "center", gap: 6, fontSize: 12 } },
                    h("span", { className: "hud-dot " + dotClass(!l.stale, l.stale) }),
                    name + (l.stale ? tt(" — 锁超过 10 分钟未释放!") : " — " + Math.round(l.age) + "s"));
                })))),
      h("div", { className: "hud-footnote" },
        tt("记忆正文不进总览事件流；此页只展示元数据。写入失败/锁异常由健康规则上报。"))));
  }

  // -------------------------------------------------------------------------
  // 定时任务 + 执行历史
  // -------------------------------------------------------------------------

  function CronTab({ snap }) {
    if (!snap) return empty(tt("加载中…"));
    const cron = snap.cron || {};
    const jobs = cron.jobs || [];
    const exec = snap.executions || {};
    const runs = exec.executions || [];
    const stats = exec.summary || {};
    const now = Date.now() / 1000;

    const sorted = jobs.slice().sort(function (a, b) { return (a.enabled ? 0 : 1) - (b.enabled ? 0 : 1); });

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-4" },
        card(tt("任务总数"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(cron.summary ? cron.summary.total : jobs.length))),
        card(tt("启用"), h("div", { style: { fontSize: 20, fontWeight: 700, color: "#4ade80" } }, String(cron.summary ? cron.summary.enabled : 0))),
        card(tt("暂停/禁用"), h("div", { style: { fontSize: 20, fontWeight: 700, color: "#facc15" } }, String((cron.summary ? cron.summary.paused + cron.summary.disabled : 0)))),
        card(tt("失败中"), h("div", { style: { fontSize: 20, fontWeight: 700, color: (cron.summary && cron.summary.failing) ? "#f87171" : undefined } }, String(cron.summary ? cron.summary.failing : 0)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("任务列表 (") + jobs.length + ")",
          jobs.length === 0 ? empty(tt("无任务")) : h("div", { className: "hud-scroll" },
            h("table", { className: "hud-table" },
              h("thead", null, h("tr", null,
                h("th", null, tt("任务")), h("th", null, tt("排程")), h("th", null, tt("下次运行")),
                h("th", { className: "num" }, tt("上次")), h("th", null, tt("状态")), h("th", null, tt("投递")))),
              h("tbody", null, sorted.map(function (j) {
                const ok = j.last_status === "ok" || j.last_status === "completed";
                const bad = j.last_status === "error" || j.last_status === "failed" || (j.failure_streak || 0) > 0;
                return h("tr", { key: j.id },
                  h("td", { style: { maxWidth: 220 } },
                    h("div", { style: { fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, j.name),
                    h("div", { className: "mono", style: { opacity: 0.5, fontSize: 10 } }, j.id)),
                  h("td", { className: "mono", style: { fontSize: 11 } }, j.schedule || "-"),
                  h("td", { className: "num", style: { fontSize: 11 } },
                    j.next_run_at ? (j.next_run_at - now < 3600
                      ? h("b", { style: { color: "#facc15" } }, Math.round((j.next_run_at - now) / 60) + tt("m 后"))
                      : fmtTime(j.next_run_at).slice(5)) : "-")),
                  h("td", { className: "num", style: { fontSize: 11 } }, j.last_run_at ? timeAgo(j.last_run_at * 1000) : "-"),
                  h("td", null,
                    h(Badge, { variant: !j.enabled ? "secondary" : bad ? "destructive" : ok ? "default" : "outline" },
                      !j.enabled ? tt("暂停") : bad ? (statusZh(j.last_status)) + (j.failure_streak ? "×" + j.failure_streak : "") : statusZh(j.last_status)),
                  h("td", { style: { fontSize: 10.5, opacity: 0.7, maxWidth: 130, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                    j.deliver || "-"));
              }))))),
        card(tt("执行历史 (最近 ") + runs.length + tt(" 条)"),
          runs.length === 0 ? empty(tt("无执行记录")) : h("div", { className: "hud-scroll" },
            h("table", { className: "hud-table" },
              h("thead", null, h("tr", null,
                h("th", null, tt("任务")), h("th", null, tt("状态")), h("th", { className: "num" }, tt("耗时")),
                h("th", null, tt("开始")), h("th", null, tt("错误")))),
              h("tbody", null, runs.slice(0, 40).map(function (r) {
                const jobName = (jobs.find(function (j) { return j.id === r.job_id; }) || {}).name || r.job_id;
                return h("tr", { key: r.id },
                  h("td", { style: { maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 600 } }, jobName),
                  h("td", null, h(Badge, {
                    variant: r.status === "completed" ? "default" : r.status === "failed" ? "destructive" : "outline",
                  }, statusZh(r.status))),
                  h("td", { className: "num" }, r.duration != null ? Math.round(r.duration) + "s" : "-"),
                  h("td", { className: "num", style: { fontSize: 11 } }, r.started_at ? fmtTime(r.started_at).slice(5) : "-"),
                  h("td", { style: { fontSize: 10.5, opacity: 0.75, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                    r.error || (r.status === "unknown" ? tt("状态未知 / 孤儿进程") : "-")));
              }))))),

      h("div", { className: "hud-footnote" },
        tt("执行历史来自 cron/executions.db（claimed→running→completed/failed 状态机）。成功率/连续失败统计见后端 rules；编辑/暂停/手动触发请跳转 Dashboard 的 Cron 页。"))));
  }

  // -------------------------------------------------------------------------
  // 渠道
  // -------------------------------------------------------------------------

  function ChannelsTab({ snap }) {
    if (!snap) return empty(tt("加载中…"));
    const gw = snap.gateway || {};
    const platforms = gw.platforms || {};
    const names = Object.keys(platforms);

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-3" },
        names.length === 0
          ? card(tt("渠道"), empty(tt("无渠道数据")))
          : names.map(function (name) {
            const p = platforms[name];
            const connected = p.state === "connected";
            const stale = (p.heartbeat_age || 0) > 60;
            const status = connected ? (stale ? tt("已连接 · 心跳陈旧") : tt("已连接")) : (stateZh(p.state) || tt("未知"));
            return card(name,
              h("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
                h("div", { style: { display: "flex", alignItems: "center", gap: 8 } },
                  h("span", { className: "hud-dot " + dotClass(connected, stale) }),
                  h("span", { style: { fontSize: 16, fontWeight: 700, color: connected ? (stale ? "#facc15" : "#4ade80") : "#f87171" } }, status)),
                h("div", { className: "hud-grid hud-grid-2" },
                  kv(tt("更新时间"), p.updated_at ? fmtTime(p.updated_at) : "-"),
                  kv(tt("心跳龄"), p.heartbeat_age != null ? Math.round(p.heartbeat_age) + "s" : "-"),
                  kv(tt("需关注"), p.needs_attention ? tt("是") : tt("否")),
                  kv(tt("错误码"), p.error_code || "-"),
                p.error_message ? h("div", { className: "hud-logline err", style: { whiteSpace: "normal" } }, p.error_message) : null,
                (connected && stale) ? h(Badge, { variant: "warning" },
                  tt("已连接但持续抖动：") + Math.round(p.heartbeat_age) + tt(" 无状态更新 — 需结合错误日志判断")) : null)));})),
      h("div", { className: "hud-footnote" },
        tt("渠道状态来自 gateway_state.json。'connected' 是瞬时快照，稳定性要结合心跳龄与 errors.log 判定 —— 例如飞书当前 connected 但日志每 ~2 分钟重连。重连计数等更细的抖动指标在错误事故页。")));
  }

  // -------------------------------------------------------------------------
  // 错误与事故
  // -------------------------------------------------------------------------

  function IncidentsTab({ snap }) {
    if (!snap) return empty(tt("加载中…"));
    const errors = snap.errors || {};
    const logs = snap.logs || {};
    const errLines = ((logs.files && logs.files["errors.log"]) || {}).lines || [];
    const agentLines = ((logs.files && logs.files["agent.log"]) || {}).lines || [];
    // 事故历史来自 telemetry.db（/incidents），当前活跃事故来自健康评估
    const incPoll = usePoll(API + "/incidents", 10000);
    const incidents = (incPoll.data && incPoll.data.incidents) || [];
    const activeNow = (snap._health && snap._health.incidents) || [];

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-4" },
        card(tt("近 30 分钟错误"), h("div", {
          style: { fontSize: 20, fontWeight: 700, color: errors.count_30m > 20 ? "#f87171" : undefined },
        }, String(errors.count_30m || 0))),
        card(tt("错误指纹"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, String((errors.incidents || []).length))),
        card(tt("活跃事故"), h("div", { style: { fontSize: 20, fontWeight: 700 } },
          String(activeNow.length + (incidents || []).filter(function (i) { return i.status === "active"; }).length))),
        card(tt("事故总数"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, String((incidents || []).length)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("事故时间线 (telemetry.db)"),
          (incidents || []).length === 0 ? empty(tt("暂无事故记录")) :
          h("div", { className: "hud-scroll" },
            (incidents || []).map(function (inc) {
              return h("div", { key: inc.id, className: "hud-incident " + inc.severity + " " + inc.status },
                h("div", { style: { display: "flex", justifyContent: "space-between", gap: 8 } },
                  h("div", { style: { fontWeight: 600, fontSize: 13 } }, incTitle(inc)),
                  h(Badge, { variant: inc.status === "active" ? (inc.severity === "critical" ? "destructive" : "warning") : "secondary" },
                    inc.status === "active" ? tt("进行中") : tt("已恢复"))),
                h("div", { style: { opacity: 0.7, fontSize: 11.5, marginTop: 2 } }, incDetail(inc)),
                h("div", { style: { opacity: 0.55, fontSize: 10.5, marginTop: 4 } },
                  tt("首次 ") + fmtTime(inc.first_seen) + tt(" · 末次 ") + fmtTime(inc.last_seen) +
                  tt(" · 观测 ") + (inc.observations != null ? inc.observations : inc.count) + tt(" 次") +
                  (inc.fingerprint ? " · " + inc.fingerprint : "")));
            }))),
        card(tt("错误指纹 TOP"),
          (errors.incidents || []).length === 0 ? empty(tt("近 30 分钟无错误")) :
          h("div", { className: "hud-scroll" },
            (errors.incidents || []).map(function (e) {
              return h("div", { key: e.fingerprint, className: "hud-check" },
                h("span", { className: "hud-dot hud-dot-warn" }),
                h("div", { style: { flex: 1, minWidth: 0 } },
                  h("div", { className: "mono", style: { fontSize: 10.5, opacity: 0.6 } }, e.fingerprint),
                  h("div", { style: { fontSize: 11.5, opacity: 0.85, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, e.sample),
                  h("div", { style: { fontSize: 10.5, opacity: 0.5 } }, "×" + e.count)));
            })))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("errors.log 尾部（脱敏）"),
          errLines.length === 0 ? empty(tt("无内容")) :
          h("div", { className: "hud-scroll" }, errLines.slice(-40).map(function (l, i) {
            return h("div", { key: i, className: "hud-logline err" }, l);
          }))),
        card(tt("agent.log 尾部（脱敏）"),
          agentLines.length === 0 ? empty(tt("无内容")) :
          h("div", { className: "hud-scroll" }, agentLines.slice(-40).map(function (l, i) {
            const cls = /error|exception|traceback/i.test(l) ? "err" : /warn/i.test(l) ? "warn" : "info";
            return h("div", { key: i, className: "hud-logline " + cls }, l);
          })))),
      h("div", { className: "hud-footnote" },
        tt("日志按异常指纹去重聚合；关键字与凭据模式已脱敏；完整原始日志请到 Dashboard 的日志页查看。")));
  }

  // -------------------------------------------------------------------------
  // 系统与存储
  // -------------------------------------------------------------------------

  function SystemTab({ snap }) {
    const [hours, setHours] = useState(6);
    const metrics = usePoll(API + "/metrics?hours=" + hours, 30000).data || [];
    if (!snap) return empty(tt("加载中…"));
    const sys = snap.system || {};
    const db = snap.db || {};
    const launchd = snap.launchd || {};
    const dash = snap.dashboard || {};
    const mem = sys.memory || {};
    const sizes = db.sizes || {};

    const cpuSeries = metrics.filter(function (m) { return m.name === "cpu_percent"; }).map(function (m) { return m.value; });
    const memSeries = metrics.filter(function (m) { return m.name === "mem_percent"; }).map(function (m) { return m.value; });
    const diskSeries = metrics.filter(function (m) { return m.name === "disk_free_percent"; }).map(function (m) { return m.value; });

    const dashProcs = dash.procs || [];
    const gwProc = sys.gateway_proc;

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-3" },
        card(tt("CPU / 负载"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv(tt("CPU 使用"), fmtPct(sys.cpu_percent)),
            kv(tt("核心数"), String(sys.cpu_count || "-")),
            kv(tt("负载"), sys.load_avg ? sys.load_avg.join(" / ") : "-"))),
        card(tt("内存"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv(tt("使用率"), fmtPct(mem.percent)),
            kv(tt("已用"), fmtBytes(mem.used)),
            kv(tt("总计"), fmtBytes(mem.total)))),
        card(tt("磁盘 (Hermes 目录)"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv(tt("剩余"), fmtPct(sys.disk_free_percent)),
            kv(tt("可用"), fmtBytes((sys.disk || {}).free)),
            kv(tt("总容量"), fmtBytes((sys.disk || {}).total))),
          h(Badge, { variant: sys.disk_free_percent < 15 ? "warning" : "default" },
            sys.disk_free_percent < 15 ? tt("磁盘压力") : tt("正常")))),

      h("div", { className: "hud-grid hud-grid-3" },
        card(tt("进程"),
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null, h("th", null, tt("进程")), h("th", { className: "num" }, "PID"),
              h("th", { className: "num" }, "RSS"), h("th", { className: "num" }, tt("运行", "th_runtime")))),
            h("tbody", null,
              gwProc ? h("tr", { key: "gw" },
                h("td", { style: { fontWeight: 600 } }, "Gateway"),
                h("td", { className: "num" }, String(gwProc.pid)),
                h("td", { className: "num" }, fmtBytes(gwProc.rss)),
                h("td", { className: "num" }, gwProc.uptime_seconds ? Math.round(gwProc.uptime_seconds / 3600) + "h" : "-")) : null,
              dashProcs.map(function (p) {
                return h("tr", { key: p.pid },
                  h("td", { style: { fontWeight: 600 } }, "Dashboard (serve)"),
                  h("td", { className: "num" }, String(p.pid)),
                  h("td", { className: "num" }, fmtBytes(p.rss)),
                  h("td", { className: "num" }, "-"));
              })))),
        card(tt("数据库"),
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null, h("th", null, tt("文件")), h("th", { className: "num" }, tt("大小")))),
            h("tbody", null, Object.keys(sizes).map(function (name) {
              const s = sizes[name];
              return h("tr", { key: name },
                h("td", { className: "mono" }, name),
                h("td", { className: "num" },
                  s ? fmtBytes(s.bytes) + (s.wal_bytes ? " (+WAL " + fmtBytes(s.wal_bytes) + ")" : "") : "-"));
            })))),
        card(tt("服务托管"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
            h("div", { style: { display: "flex", alignItems: "center", gap: 8 } },
              h("span", { className: "hud-dot " + dotClass(launchd.managed, !launchd.managed) }),
              h("span", { fontWeight: 600 }, launchd.managed ? tt("launchd 托管") : tt("未由 launchd 托管"))),
            kv(tt("服务定义"), launchd.label || tt("无 plist")),
            launchd.note ? h("div", { className: "mono", style: { fontSize: 10.5, opacity: 0.6 } }, launchd.note) : null,
            !launchd.managed ? h(Badge, { variant: "warning" }, tt("Gateway 重启后可能不自启 — 建议修复")) : null))),

      h("div", { className: "hud-grid hud-grid-3" },
        card(tt("CPU 趋势 (telemetry)"),
          cpuSeries.length < 2 ? empty(tt("数据积累中（约 60s 一个点）")) :
          h(MiniBars, { values: cpuSeries.slice(-60), height: 80, fmt: function (v) { return "CPU " + v.toFixed(1) + "%"; } })),
        card(tt("内存趋势"),
          memSeries.length < 2 ? empty(tt("数据积累中")) :
          h(MiniBars, { values: memSeries.slice(-60), height: 80, fmt: function (v) { return "MEM " + v.toFixed(1) + "%"; } })),
        card(tt("磁盘剩余趋势"),
          diskSeries.length < 2 ? empty(tt("数据积累中")) :
          h(MiniBars, { values: diskSeries.slice(-60), height: 80, fmt: function (v) { return "DISK " + v.toFixed(1) + "%"; } }))),

      h("div", { className: "hud-footnote" },
        tt("时序数据保存在 ~/.hermes/hud/telemetry.db（分钟级，保留 ") +
        (window.HUD_RETENTION || "30") + tt(" 天），不触碰 state.db。")));
  }

  // -------------------------------------------------------------------------
  // 技能
  // -------------------------------------------------------------------------

  function SkillsTab() {
    const { data } = usePoll(API + "/skills", 30000);
    const [cat, setCat] = useState("全部");
    if (!data) return empty(tt("加载中…"));
    const skills = data.skills || [];
    const summary = data.summary || {};
    const cats = Object.keys(summary.by_category || {}).sort(function (a, b) {
      return summary.by_category[b] - summary.by_category[a];
    });
    const filtered = cat === "全部" ? skills : skills.filter(function (s) { return s.category === cat; });

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-4" },
        card(tt("技能总数"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.total || 0))),
        card(tt("分类数"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.categories || 0))),
        card(tt("近 24h 新增/修改"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.recent_24h || 0))),
        card(tt("近 7 天活动"), h("div", { style: { fontSize: 20, fontWeight: 700 } }, String(summary.recent_7d || 0)))),

      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("分类分布 (") + (summary.categories || 0) + ")",
          cats.length === 0 ? empty(tt("无数据")) : h("div", { style: { display: "flex", flexWrap: "wrap", gap: 6 } },
            cats.map(function (c) {
              return h("button", {
                key: c, className: "hud-tab" + (cat === c ? " active" : ""),
                style: { padding: "4px 10px" },
                onClick: function () { setCat(c); },
              }, c + " · " + summary.by_category[c]);
            }))),
        card(tt("分类筛选"),
          h("div", { style: { display: "flex", gap: 6, flexWrap: "wrap" } },
            h(Button, { size: "sm", variant: cat === "全部" ? "default" : "outline", onClick: function () { setCat("全部"); } }, tt("全部") + " (" + (summary.total || 0) + ")"),
            cats.slice(0, 12).map(function (c) {
              return h(Button, {
                key: c, size: "sm", variant: cat === c ? "default" : "outline",
                onClick: function () { setCat(c); }, style: { fontSize: 11.5 },
              }, c);
            })))),

      card(tt("技能列表 (") + filtered.length + " / " + skills.length + ")",
        filtered.length === 0 ? empty(tt("该分类下无技能")) :
        h("div", { className: "hud-scroll" },
          h("table", { className: "hud-table" },
            h("thead", null, h("tr", null,
              h("th", null, tt("技能")), h("th", null, tt("分类")), h("th", { className: "num" }, tt("版本")),
              h("th", { className: "num" }, tt("大小")), h("th", null, tt("最近修改")), h("th", null, tt("描述")))),
            h("tbody", null, filtered.slice(0, 150).map(function (s) {
              return h("tr", { key: s.dir },
                h("td", { style: { fontWeight: 600, whiteSpace: "nowrap" } }, s.name),
                h("td", null, s.category),
                h("td", { className: "num" }, s.version || "-"),
                h("td", { className: "num" }, fmtBytes(s.bytes)),
                h("td", { className: "num", style: { fontSize: 11 } }, timeAgo(s.mtime * 1000)),
                h("td", { style: { fontSize: 11, opacity: 0.75, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } },
                  (s.description || "").slice(0, 60)));
            }))))),
      h("div", { className: "hud-footnote" },
        tt("技能目录 ~/.hermes/skills/（只读扫描 SKILL.md 元数据）。安装/删除请到 Dashboard 的 Skills 页。")));
  }

  // -------------------------------------------------------------------------
  // 设置 / 数据质量
  // -------------------------------------------------------------------------

  const HUD_LOCALE_OPTIONS = [
    { code: "zh", name: "简体中文" },
    { code: "en", name: "English" },
    { code: "fr", name: "Français" },
    { code: "ar", name: "العربية" },
  ];

  function SettingsTab() {
    const { data: settings } = usePoll(API + "/settings", 60000);
    const { data: quality } = usePoll(API + "/data-quality", 30000);
    // Dashboard 菜单语言：直接用 host 的 useI18n()（实时生效，无需刷新页面）
    const { locale, setLocale } = useI18n();
    const currentOpt = HUD_LOCALE_OPTIONS.find(function (o) { return o.code === locale; });

    return h(React.Fragment, null,
      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("阈值与预算（rules.py）"),
          settings ? h("table", { className: "hud-table" },
            h("tbody", null,
              Object.keys(settings.thresholds || {}).map(function (k) {
                return h("tr", { key: k },
                  h("td", { className: "mono", style: { fontSize: 11 } }, k),
                  h("td", { className: "num" }, String(settings.thresholds[k])));
              }),
              Object.keys(settings.retention_days || {}).map(function (k) {
                return h("tr", { key: k },
                  h("td", { className: "mono", style: { fontSize: 11 } }, "retention." + k),
                  h("td", { className: "num" }, settings.retention_days[k] + tt(" 天")));
              })))
            : empty(tt("加载中…"))),
        card(tt("采集器数据质量"),
          quality ? h("div", { style: { display: "flex", flexDirection: "column", gap: 4 } },
            h("div", { style: { display: "flex", alignItems: "center", gap: 8, marginBottom: 4 } },
              h(Badge, { variant: quality.overall === "ok" ? "default" : "warning" },
                quality.overall === "ok" ? tt("全部采集器正常") : tt("部分采集器异常")),
              h("span", { style: { fontSize: 11, opacity: 0.6 } }, tt("采集于 ") + fmtTime(quality.collected_at))),
            Object.keys(quality.sections || {}).map(function (name) {
              const err = quality.sections[name];
              return h("div", { key: name, className: "hud-check" },
                h("span", { className: "hud-dot " + (err ? "hud-dot-bad" : "hud-dot-ok") }),
                h("span", { style: { fontWeight: 600, width: 90 } }, name),
                h("span", { style: { opacity: 0.8, fontSize: 11.5 } }, err || tt("正常")));
            }))
            : empty(tt("加载中…"))),
      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("统计时区"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            h("div", { style: { fontSize: 20, fontWeight: 700 } }, (settings && settings.tz) || "-"),
            h("div", { style: { fontSize: 11, opacity: 0.65 } },
              tt("HUD_TIMEZONE > 系统本地时区 > UTC；快照缓存 TTL ") +
              (settings && settings.snapshot_cache_ttl_s) + tt("s / telemetry 落盘每 ") +
              (settings && settings.telemetry_interval_s) + tt("s 一次")))),
        card("telemetry.db",
          settings ? h("div", { style: { display: "flex", flexDirection: "column", gap: 6 } },
            kv(tt("指标行"), String((settings.telemetry && settings.telemetry.metrics_rows) || 0)),
            kv(tt("事故记录"), String((settings.telemetry && settings.telemetry.incidents) || 0)),
            kv(tt("活跃事故"), String((settings.telemetry && settings.telemetry.active_incidents) || 0)),
            kv(tt("库大小"), fmtBytes((settings.telemetry && settings.telemetry.db_bytes) || 0)))
            : empty(tt("加载中…"))),
        card(tt("安全边界"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 6, fontSize: 12.5, opacity: 0.85 } },
            h("div", null, tt("• 默认仅监听 127.0.0.1，沿用 Dashboard 鉴权")),
            h("div", null, tt("• 不读取/返回 .env、auth.json、完整 token")),
            h("div", null, tt("• 日志/对话/记忆经脱敏与按需加载")),
            h("div", null, tt("• telemetry.db 只存聚合、指纹与短摘要")),
            h("div", null, tt("• 无 outbound 遥测，不自动查询外部账单")),
            h("div", null, tt("• HUD 纯观察；操作跳转现有 Dashboard 受保护页面"))))),
      h("div", { className: "hud-grid hud-grid-2" },
        card(tt("Dashboard 界面语言"),
          h("div", { style: { display: "flex", flexDirection: "column", gap: 8 } },
            h("div", { style: { display: "flex", alignItems: "center", gap: 8 } },
              h("span", { className: "hud-dot hud-dot-ok" }),
              h("span", { style: { fontWeight: 700 } }, tt("当前：") + (currentOpt ? currentOpt.name : locale)),
              h("span", { className: "mono", style: { fontSize: 10.5, opacity: 0.6 } }, "hermes-locale=" + locale)),
            h("div", { style: { display: "flex", gap: 8, flexWrap: "wrap" } },
              HUD_LOCALE_OPTIONS.map(function (o) {
                return h(Button, {
                  key: o.code, size: "sm", variant: locale === o.code ? "default" : "outline",
                  onClick: function () { setLocale(o.code); },
                }, o.name);
              })),
            h("div", { style: { fontSize: 11.5, opacity: 0.65, lineHeight: 1.5 } },
              tt("此处切换会立即应用到整个 Dashboard（含本插件），并保存在浏览器 localStorage，与系统重启无关。更多语言可在 Dashboard 顶部的语言切换器中选择。"))))),
      h("div", { className: "hud-footnote" },
        tt("刷新频率：snapshot 2s / usage·metrics 30s / settings·quality 30-60s；阈值可用 HUD_* 环境变量覆盖（见后端 rules.py）。"))));
  }

  // -------------------------------------------------------------------------
  // 根组件
  // -------------------------------------------------------------------------

  const TABS = [
    { id: "overview", label: "指挥中心", icon: "◉" },
    { id: "live", label: "实时活动", icon: "⚡" },
    { id: "usage", label: "Token·费用", icon: "¥" },
    { id: "sessions", label: "对话记录", icon: "☰" },
    { id: "timeline", label: "时间线", icon: "🕒" },
    { id: "memory", label: "记忆", icon: "🧠" },
    { id: "skills", label: "技能", icon: "⚒" },
    { id: "skillanalytics", label: "技能分析", icon: "📊" },
    { id: "cron", label: "定时任务", icon: "⏱" },
    { id: "channels", label: "渠道", icon: "⇄" },
    { id: "incidents", label: "错误·事故", icon: "⚠" },
    { id: "system", label: "系统·存储", icon: "▤" },
    { id: "settings", label: "设置", icon: "⚙" },
  ];

  // -------------------------------------------------------------------------
  // Timeline（Agent Timeline v1）
  // -------------------------------------------------------------------------

  const TIMELINE_TYPES = [
    { id: "all", label: "All" },
    { id: "session.", label: "Sessions" },
    { id: "skill.", label: "Skills" },
    { id: "tool.", label: "Tools" },
    { id: "incident.", label: "Errors" },
  ];

  const TIMELINE_STATUS = [
    { id: "all", label: "全部状态" },
    { id: "success", label: "成功" },
    { id: "failed", label: "失败" },
  ];

  function tlTypeLabel(t) {
    return (t || "").split(".")[0] || "";
  }

  function tlTime(ts) {
    if (!ts) return "--:--:--";
    const d = new Date(ts * 1000);
    return d.toLocaleString(dtLocale(), { hour: "2-digit", minute: "2-digit",
      second: "2-digit", hour12: false });
  }

  function tlFmt(tokens, cost, dur) {
    const parts = [];
    if (dur !== null && dur !== undefined) parts.push((dur / 1000).toFixed(1) + "s");
    if (tokens !== null && tokens !== undefined) parts.push(tokens.toLocaleString() + " tokens");
    if (cost !== null && cost !== undefined) parts.push("$" + cost.toFixed(4));
    return parts.length ? parts.join(" · ") : "—";
  }

  function TimelineTab() {
    const [type, setType] = useState("all");
    const [status, setStatus] = useState("all");
    const [sessionId, setSessionId] = useState("");
    const [events, setEvents] = useState([]);
    const [hasMore, setHasMore] = useState(false);
    const [expanded, setExpanded] = useState(null);
    const [newCount, setNewCount] = useState(0);
    const [loadErr, setLoadErr] = useState(null);
    const listRef = useRef(null);

    function buildUrl(extra) {
      const p = new URLSearchParams({ limit: "100" });
      if (type !== "all") p.set("event_type", type);
      if (status !== "all") p.set("status", status);
      if (sessionId.trim()) p.set("session_id", sessionId.trim());
      if (extra) Object.keys(extra).forEach(function (k) { p.set(k, extra[k]); });
      return API + "/timeline?" + p.toString();
    }

    // 轮询（5s；事件进入后 prepend；用户停留在历史位置时不强制跳顶）
    const { data, error } = usePoll(buildUrl(), 5000);
    useEffect(function () {
      if (!data || !data.events) return;
      setLoadErr(null);
      setEvents(function (prev) {
        if (!prev.length) return data.events;
        const seen = {};
        prev.forEach(function (e) { seen[e.event_id] = 1; });
        const fresh = [];
        data.events.forEach(function (e) {
          if (!seen[e.event_id]) { seen[e.event_id] = 1; fresh.push(e); }
        });
        if (fresh.length) {
          const atTop = listRef.current && listRef.current.scrollTop < 30;
          if (atTop) {
            setNewCount(0);
            return fresh.concat(prev).slice(0, 300);
          }
          setNewCount(function (n) { return n + fresh.length; });
        }
        return prev;
      });
      setHasMore(!!data.has_more);
    }, [data]);
    useEffect(function () { if (error) setLoadErr(String(error)); }, [error]);

    function loadMore() {
      const last = events[events.length - 1];
      if (!last) return;
      SDK.fetchJSON(buildUrl({ before: String(last.timestamp), before_id: last.event_id }))
        .then(function (d) {
          const seen = {};
          events.forEach(function (e) { seen[e.event_id] = 1; });
          const more = (d.events || []).filter(function (e) { return !seen[e.event_id]; });
          setEvents(events.concat(more));
          setHasMore(!!d.has_more);
        })
        .catch(function (e) { setLoadErr(String(e && e.message ? e.message : e)); });
    }

    function showNew() {
      setNewCount(0);
      SDK.fetchJSON(buildUrl()).then(function (d) {
        if (d && d.events) setEvents(d.events);
      }).catch(function () {});
    }

    const filters = h("div", { style: { display: "flex", gap: 8, flexWrap: "wrap",
      alignItems: "center", marginBottom: 10 } },
      TIMELINE_TYPES.map(function (t) {
        return h("button", {
          key: t.id, className: "hud-tab" + (type === t.id ? " active" : ""),
          style: { padding: "4px 10px", fontSize: 12 },
          onClick: function () { setType(t.id); setNewCount(0); },
        }, t.label);
      }),
      h("select", {
        value: status, style: { fontSize: 12, padding: "3px 6px" },
        onChange: function (e) { setStatus(e.target.value); setNewCount(0); },
      }, TIMELINE_STATUS.map(function (s) {
        return h("option", { key: s.id, value: s.id }, tt(s.label));
      })),
      h("input", {
        placeholder: "session id…", value: sessionId, style: { fontSize: 12, padding: "3px 6px", width: 180 },
        onChange: function (e) { setSessionId(e.target.value); setNewCount(0); },
      }),
      newCount > 0 && h("button", {
        style: { fontSize: 12, padding: "4px 10px", fontWeight: 600 },
        onClick: showNew,
      }, "↓ " + newCount + tt(" 条新事件")));

    const rows = events.map(function (e, idx) {
      const ok = e.status !== "failed";
      const isInc = (e.event_type || "").indexOf("incident.") === 0;
      const title = e.summary || (e.event_type || "");
      const open = expanded === e.event_id;
      const line = h("div", {
        key: e.event_id,
        className: "hud-tl-row",
        style: { display: "flex", gap: 10, alignItems: "baseline", padding: "6px 4px",
          borderBottom: "1px solid var(--border)", cursor: "pointer", fontSize: 13 },
        onClick: function () { setExpanded(open ? null : e.event_id); },
      },
        h("span", { style: { fontFamily: "monospace", fontSize: 12, opacity: 0.7, width: 74, flexShrink: 0 } }, tlTime(e.timestamp)),
        h("span", { style: { width: 16, flexShrink: 0 } }, isInc ? (ok ? "⚠" : "✕") : (ok ? "✓" : "✕")),
        h("span", { style: { color: ok ? "var(--foreground)" : "#e5534b", width: 120, flexShrink: 0 } }, e.event_type || "—"),
        h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, title),
        h("span", { style: { fontFamily: "monospace", fontSize: 12, opacity: 0.75, flexShrink: 0 } }, tlFmt(e.tokens, e.cost_usd, e.duration_ms)));

      const detail = open ? h("div", { key: e.event_id + "-d", style: { padding: "8px 14px 10px", fontSize: 12, background: "var(--card)", borderBottom: "1px solid var(--border)" } },
        kv(tt("时间"), fmtTime(e.timestamp)),
        kv(tt("类型"), e.event_type || "—"),
        kv(tt("状态"), statusZh(e.status) || e.status || "—"),
        kv("Session", e.session_id || "—"),
        kv("Skill", e.skill || "—"),
        kv("Tool", e.tool || "—"),
        kv(tt("时长"), e.duration_ms !== null && e.duration_ms !== undefined ? (e.duration_ms / 1000).toFixed(1) + "s" : "—"),
        kv("Tokens", e.tokens !== null && e.tokens !== undefined ? e.tokens.toLocaleString() : "—"),
        kv(tt("费用"), e.cost_usd !== null && e.cost_usd !== undefined ? "$" + e.cost_usd.toFixed(4) : "—"),
        kv(tt("关联"), e.correlation_id || "—"),
        kv(tt("来源"), e.source || "—"),
        kv("Incident", e.incident_id || "—")) : null;
      return [line, detail];
    });

    return card(tt("Agent Timeline — 做了什么？"),
      h("div", { ref: listRef, style: { maxHeight: "62vh", overflowY: "auto" } },
        filters,
        loadErr && h("div", { style: { fontSize: 12, color: "#e5534b", padding: 6 } }, tt("加载失败: ") + loadErr),
        events.length === 0
          ? empty(tt("暂无事件（全新安装的正常状态；有新活动后自动出现）"))
          : rows,
        hasMore && h("div", { style: { textAlign: "center", padding: 8 } },
          h("button", { style: { fontSize: 12, padding: "4px 12px" }, onClick: loadMore }, tt("加载更多"))),
        newCount > 0 && h("div", { style: { textAlign: "center", padding: 8 } },
          h("button", { style: { fontSize: 12, padding: "4px 12px" }, onClick: showNew },
            newCount + tt(" 条新事件（点击载入）")))));
  }

  // -------------------------------------------------------------------------
  // Skill Analytics（技能分析 v1 —— observed truth only）
  // -------------------------------------------------------------------------

  const SA_RANGES = [
    { id: "24h", label: "24h" }, { id: "7d", label: "7d" },
    { id: "30d", label: "30d" }, { id: "all", label: "All" },
  ];

  function saRate(r) {
    if (r === null || r === undefined) return "—";  // denominator=0 → —（不显示 0%）
    return (r * 100).toFixed(1) + "%";
  }

  function saTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleString(dtLocale(), { month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function saDur(ms) {
    if (ms === null || ms === undefined) return "—";
    if (ms >= 1000) return (ms / 1000).toFixed(1) + "s";
    return ms + "ms";
  }

  function saNum(v) {
    // 0 是合法值（显示 0）；null/undefined 才是 unavailable（显示 —）
    return (v === null || v === undefined) ? "—" : String(v);
  }

  function saCoverageZh(c) {
    if (c === "observed") return tt("已观测");
    if (c === "inventory_only") return tt("仅清单");
    if (c === "unavailable") return tt("不可用");
    return "—";
  }

  function SkillAnalyticsTab() {
    const [range, setRange] = useState("7d");
    const [status, setStatus] = useState("all");
    const [observed, setObserved] = useState("all");
    const [search, setSearch] = useState("");
    const [sort, setSort] = useState("name");
    const [expanded, setExpanded] = useState(null);
    const [detail, setDetail] = useState(null);
    const [detailErr, setDetailErr] = useState(null);

    function qs() {
      const p = new URLSearchParams({ range: range, limit: "200", sort: sort });
      if (status !== "all") p.set("status", status);
      if (observed !== "all") p.set("observed", observed);
      if (search.trim()) p.set("search", search.trim());
      return API + "/skills/analytics?" + p.toString();
    }
    const { data } = usePoll(qs(), 8000);
    const { data: summary } = usePoll(API + "/skills/analytics/summary?range=" + range, 8000);
    const skills = (data && data.skills) || [];
    const cov = (data && data.coverage) || summary && summary.coverage;

    function openDetail(skill) {
      SDK.fetchJSON(API + "/skills/analytics/" + encodeURIComponent(skill) +
        "?range=" + range + "&timeline_limit=20")
        .then(function (d) { setDetail(d); setDetailErr(null); })
        .catch(function (e) { setDetailErr(String(e && e.message ? e.message : e)); });
    }

    // Summary cards
    const cards = [
      { k: tt("已注册技能"), v: summary ? summary.registered_skills : "—" },
      { k: tt("已观测执行"), v: summary ? summary.observed_skills : "—" },
      { k: tt("观测运行次数"), v: summary ? summary.observed_runs : "—" },
      { k: tt("成功率"), v: summary ? saRate(summary.success_rate) : "—" },
      { k: tt("失败次数"), v: summary ? summary.failed_runs : "—" },
      { k: tt("未观测到执行"), v: summary ? summary.no_observed_execution : "—" },
    ];
    const summaryRow = h("div", { style: { display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 8, marginBottom: 10 } },
      cards.map(function (c) {
        return h("div", { key: c.k, style: { background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 12px" } },
          h("div", { style: { fontSize: 11, opacity: 0.65 } }, c.k),
          h("div", { style: { fontSize: 18, fontWeight: 700, marginTop: 2 } }, c.v));
      }));

    const covNotice = cov && !cov.coverage_complete ? h("div", { style: { fontSize: 12, padding: "6px 10px", background: "rgba(255,193,7,.12)", border: "1px solid rgba(255,193,7,.4)", borderRadius: 6, marginBottom: 10 } },
      tt("运行观测覆盖目前不完整；统计仅包含具有可靠身份的 Skill 执行事件。")) : null;

    const filters = h("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 } },
      SA_RANGES.map(function (r) {
        return h("button", {
          key: r.id, className: "hud-tab" + (range === r.id ? " active" : ""),
          style: { padding: "4px 10px", fontSize: 12 },
          onClick: function () { setRange(r.id); },
        }, r.label);
      }),
      h("select", { value: status, style: { fontSize: 12, padding: "3px 6px" },
        onChange: function (e) { setStatus(e.target.value); } },
        h("option", { value: "all" }, tt("全部状态")),
        h("option", { value: "failed" }, tt("有失败")),
        h("option", { value: "success" }, tt("有成功"))),
      h("select", { value: observed, style: { fontSize: 12, padding: "3px 6px" },
        onChange: function (e) { setObserved(e.target.value); } },
        h("option", { value: "all" }, tt("全部")),
        h("option", { value: "observed" }, tt("已观测")),
        h("option", { value: "unobserved" }, tt("未观测到执行"))),
      h("input", { placeholder: tt("搜索技能名…"), value: search,
        style: { fontSize: 12, padding: "3px 6px", width: 140 },
        onChange: function (e) { setSearch(e.target.value); } }),
      h("select", { value: sort, style: { fontSize: 12, padding: "3px 6px" },
        onChange: function (e) { setSort(e.target.value); } },
        h("option", { value: "name" }, tt("按名称")),
        h("option", { value: "runs" }, tt("运行最多")),
        h("option", { value: "failures" }, tt("失败最多")),
        h("option", { value: "rate" }, tt("成功率最低")),
        h("option", { value: "recent" }, tt("最近运行"))));

    const head = [tt("技能"), tt("来源"), "Review", tt("风险"), tt("运行", "th_runs"), tt("成功"), tt("失败"), tt("成功率"), tt("平均耗时"), tt("最近观测"), tt("覆盖")];
    const headRow = h("div", { key: "head", style: { display: "grid", gridTemplateColumns: "1.4fr 1fr 0.7fr 0.6fr 0.6fr 0.6fr 0.6fr 0.8fr 0.9fr 1.2fr 0.9fr", gap: 6, padding: "6px 8px", fontSize: 11, opacity: 0.65, fontWeight: 600, borderBottom: "1px solid var(--border)" } },
      head.map(function (hcol) { return h("span", { key: hcol }, hcol); }));

    const rows = skills.map(function (s) {
      const open = expanded === s.skill;
      const line = h("div", { key: s.skill, style: { display: "grid", gridTemplateColumns: "1.4fr 1fr 0.7fr 0.6fr 0.6fr 0.6fr 0.6fr 0.8fr 0.9fr 1.2fr 0.9fr", gap: 6, padding: "6px 8px", fontSize: 12, borderBottom: "1px solid var(--border)", cursor: "pointer", alignItems: "center" },
        onClick: function () {
          setExpanded(open ? null : s.skill);
          if (!open) openDetail(s.skill);
        } },
        h("span", { style: { fontWeight: 600 } }, s.skill),
        h("span", { style: { fontSize: 11, opacity: 0.75 } }, s.provenance || "—"),
        h("span", { style: { fontSize: 11 } }, s.review_decision || "—"),
        h("span", { style: { fontSize: 11 } }, s.risk || "—"),
        h("span", { style: { textAlign: "right" } }, saNum(s.observed_runs)),
        h("span", { style: { textAlign: "right", color: "#3fb950" } }, saNum(s.completed)),
        h("span", { style: { textAlign: "right", color: s.failed ? "#e5534b" : "inherit" } }, saNum(s.failed)),
        h("span", { style: { textAlign: "right" } }, saRate(s.success_rate)),
        h("span", { style: { textAlign: "right" } }, saDur(s.avg_duration_ms)),
        h("span", { style: { textAlign: "right", fontSize: 11, opacity: 0.75 } }, saTime(s.last_observed_at)),
        h("span", { style: { fontSize: 11 } }, saCoverageZh(s.runtime_coverage)));
      const detailBlock = open && detail && detail.skill && detail.skill.skill === s.skill
        ? h("div", { key: s.skill + "-d", style: { padding: "10px 14px", fontSize: 12, background: "var(--card)", borderBottom: "1px solid var(--border)" } },
            kv(tt("技能"), s.skill),
            kv(tt("来源 / Provenance"), s.provenance || "—"),
            kv(tt("Review 决策"), s.review_decision || "—"),
            kv(tt("风险"), s.risk || "—"),
            kv(tt("版本"), s.version || "—"),
            kv(tt("健康"), s.health || "—"),
            kv(tt("观测运行"), saNum(s.observed_runs)),
            kv(tt("成功率"), saRate(s.success_rate)),
            kv(tt("平均耗时"), saDur(s.avg_duration_ms)),
            kv(tt("最近观测"), saTime(s.last_observed_at)),
            h("div", { style: { fontSize: 11, opacity: 0.65, marginTop: 8, marginBottom: 4 } }, tt("最近 Timeline 事件（直接引用，不复制）")),
            h("div", { style: { maxHeight: 220, overflowY: "auto" } },
              (detail.recent_timeline_events || []).map(function (ev) {
                return h("div", { key: ev.event_id, style: { padding: "3px 0", fontSize: 11, fontFamily: "monospace", borderBottom: "1px solid var(--border)" } },
                  saTime(ev.timestamp) + "  " + ev.event_type + "  " + (ev.status || "") + "  " + (ev.summary || ""));
              }),
              (!detail.recent_timeline_events || !detail.recent_timeline_events.length)
                ? h("div", { style: { padding: 6, opacity: 0.5 } }, tt("未观测到执行（No observed executions）")) : null))
        : null;
      return [line, detailBlock];
    });

    return card(tt("Skill Analytics — 技能运行观测（observed truth only）"),
      h("div", null,
        summaryRow,
        covNotice,
        filters,
        detailErr && h("div", { style: { fontSize: 12, color: "#e5534b", padding: 6 } }, "详情加载失败: " + detailErr),
        skills.length === 0
          ? empty(tt("暂无技能数据（registry 或 timeline 不可用时的正常降级）"))
          : [headRow, rows],
        data && data.total > 200 && h("div", { style: { textAlign: "center", padding: 8, fontSize: 12, opacity: 0.7 } },
          tt("共 ") + data.total + tt(" 个技能（分页上限 200，可搜索/过滤缩小范围）"))));
  }

  function HudApp() {
    const [tab, setTab] = useState("overview");
    const { data: snap } = usePoll(API + "/snapshot", 2000);
    const [events, setEvents] = useState([]);
    const [wsState, setWsState] = useState("idle");
    const wsRef = useRef(null);
    const snapRef = useRef(null);
    snapRef.current = snap;

    // 语言：跟随 Dashboard 的 useI18n()；写入模块级 CURRENT_LOCALE 供 tt()/dtLocale() 同步读取
    const hostI18n = useI18n();
    CURRENT_LOCALE = (hostI18n && hostI18n.locale) || CURRENT_LOCALE;

    const health = snap ? snap._health : null;

    // WebSocket 事件流（增强；断线自动退避重连，失败时轮询 snapshot 已兜底）
    useEffect(function () {
      let alive = true;
      let retry = 1000;
      let ws = null;

      function connect() {
        if (!alive) return;
        SDK.buildWsUrl(API + "/events", { locale: CURRENT_LOCALE })
          .then(function (url) {
            if (!alive) return;
            ws = new WebSocket(url);
            wsRef.current = ws;
            ws.onopen = function () { if (alive) { setWsState("connected"); retry = 1000; } };
            ws.onmessage = function (evt) {
              if (!alive) return;
              try {
                const msg = JSON.parse(evt.data);
                if (msg.events && msg.events.length) {
                  setEvents(function (prev) {
                    const merged = msg.events.concat(prev);
                    const seen = {};
                    const uniq = [];
                    for (let i = 0; i < merged.length; i++) {
                      const k = evKey(merged[i]);
                      if (!seen[k]) { seen[k] = 1; uniq.push(merged[i]); }
                      if (uniq.length >= 200) break;
                    }
                    return uniq;
                  });
                }
              } catch (e) { /* ignore */ }
            };
            ws.onclose = function () {
              if (!alive) return;
              setWsState("reconnecting");
              setTimeout(connect, retry);
              retry = Math.min(retry * 2, 30000);
            };
            ws.onerror = function () { try { ws.close(); } catch (e) {} };
          })
          .catch(function () {
            if (!alive) return;
            setWsState("fallback");
            setTimeout(connect, Math.min(retry * 2, 30000));
          });
      }
      connect();
      return function () { alive = false; if (ws) { try { ws.close(); } catch (e) {} } };
      // hostI18n.locale 依赖：语言切换时断开重连，WS 带上新语言（否则要等
      // 断线重试或刷新页面才会用上新 locale，见下方 stream_events 的说明）。
    }, [hostI18n.locale]);

    // 轮询事件也合并（WS 不可用时仍能看到增量）
    useEffect(function () {
      const evs = snap && snap._events;
      if (evs && evs.length) {
        setEvents(function (prev) {
          const merged = evs.concat(prev);
          const seen = {};
          const uniq = [];
          for (let i = 0; i < merged.length; i++) {
            const k = evKey(merged[i]);
            if (!seen[k]) { seen[k] = 1; uniq.push(merged[i]); }
            if (uniq.length >= 200) break;
          }
          return uniq;
        });
      }
    }, [snap]);

    const gw = (snap && snap.gateway) || {};
    const cronSum = (snap && snap.cron && snap.cron.summary) || {};

    return h("div", { className: "hud-root" },
      // 顶部状态条
      h("div", { className: "hud-header" },
        h("span", { className: "hud-health-badge " + (health ? healthClass(health.overall) : "") },
          (health ? healthLabel(health.overall) : tt("加载中")) +
          (health ? " · " + health.counts.critical + tt(" 红 / ") + health.counts.warning + tt(" 黄") : "")),
        kv("Gateway", gw.alive ? tt("运行中") : tt("离线")),
        kv(tt("活跃会话"), String((snap && snap.active_sessions) ? snap.active_sessions.length : "-")),
        kv("Cron", (cronSum.enabled != null ? cronSum.enabled + tt(" 启用") : "-")),
        kv(tt("模式"), wsState === "connected" ? tt("WS 实时") : (wsState === "reconnecting" ? tt("WS 重连中") : tt("轮询")))),

      // Tab 栏
      h("div", { className: "hud-tabs" },
        TABS.map(function (t) {
          return h("button", {
            key: t.id,
            className: "hud-tab" + (tab === t.id ? " active" : ""),
            onClick: function () { setTab(t.id); },
          }, t.icon + " " + tt(t.label));
        })),

      // 内容
      tab === "overview" ? h(Overview, { snap: snap, health: health }) :
      tab === "live" ? h(Live, { snap: snap, events: events, wsState: wsState }) :
      tab === "usage" ? h(Usage, null) :
      tab === "sessions" ? h(SessionsTab, null) :
      tab === "timeline" ? h(TimelineTab, null) :
      tab === "memory" ? h(MemoryTab, { snap: snap }) :
      tab === "skills" ? h(SkillsTab, null) :
      tab === "skillanalytics" ? h(SkillAnalyticsTab, null) :
      tab === "cron" ? h(CronTab, { snap: snap }) :
      tab === "channels" ? h(ChannelsTab, { snap: snap }) :
      tab === "incidents" ? h(IncidentsTab, { snap: snap }) :
      tab === "system" ? h(SystemTab, { snap: snap }) :
      h(SettingsTab, null));
  }

  // -------------------------------------------------------------------------
  // 注册
  // -------------------------------------------------------------------------

  window.__HERMES_PLUGINS__.register("hermes-hud", HudApp);
})();
