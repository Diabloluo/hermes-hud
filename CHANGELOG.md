# Changelog

本文件记录 Hermes HUD 的可见变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [1.0.2] - 2026-08-23

### Fixed

- **Fresh-install activation instructions for Dashboard plugins.** `hermes plugins
  enable/disable` manages *native* plugins only; Dashboard plugins (manifest.json +
  plugin_api.py) are activated via the `plugins.enabled` allowlist. Added
  `scripts/enable_dashboard_plugin.py` (read → merge → write back, idempotent) and
  corrected the install/uninstall instructions in README / FAQ / CONTRIBUTING. The
  previous `hermes plugins enable hermes-hud` instruction failed with
  "Plugin not installed or bundled".
- **Runtime timezone regression causing `CST is not defined`.** `collect_db` referenced
  the removed module-level `CST` constant after the v1.0.1 timezone refactor; now uses
  `get_hud_timezone()` (HUD_TIMEZONE > system local tz > UTC). Added regression tests
  that fail on v1.0.1 and pass on 1.0.2.

## [1.0.1] - 2026-08-23

### Security

- 重构脱敏器（`hud/redaction.py`）：模式规则（Bearer / JWT / sk-* / Telegram bot token /
  长 hex / base64）先行整体替换，杜绝"先匹配掉 Bearer 字样却把真正 token 留在后面"的截断泄漏；
  支持 JSON quoted keys（`"token":"xxx"`）、URL userinfo、Cookie/Authorization 整行兜底。
- 日志指纹改为**脱敏后生成**：`fingerprint()` 内部先 `redact_line` 再归一化，
  raw secret 不进入 fingerprint / incident / telemetry / WebSocket / REST。
- 新增统一隐私工具：`sanitize_path()`（用户名与中间目录脱敏）、`sanitize_cmdline()`、
  `redact_obj()`（dict 敏感键整体替换）；应用于 session cwd、skill dir、dashboard cmdline、
  launchd ProgramArguments、cron deliver/script。
- `hud_alert.py` 只从 `.env` 加载通知所需的 allowlisted 凭据（6 个变量），不再批量注入进程环境。

### Correctness

- 修复 Token/费用口径：辅助调用只统计 `session_model_usage.task != ''`
  （`task=''` 是主会话重复记账，此前会造成主会话翻倍）；API calls 改用数据库
  `api_call_count` 累计，不再每行 +1。
- 修复告警恢复状态机：恢复通知**至少一个渠道成功才置 recovered**；
  全部失败保持 `pending_recovery` 并下轮重试，禁止"没发出去却标已恢复"；
  push item 直接携带 fingerprint（删除按消息正文反查的设计）。
- Cron 事故指纹稳定化：`cron:<id>:fail`（不再随失败次数产生 `fail-3/fail-4/...`），
  同一任务连续失败保持同一条事故生命周期。
- 事故计数语义修正：新增 `observations`（观测次数）与 `state_changes`（实质状态变化次数）
  字段，`count` 不再被当作"触发次数"；旧 telemetry.db 自动平滑迁移（无需删库）。
- `idle_seconds` 改为基于最近活动（MAX(messages.timestamp)），无可靠数据时为 null。
- 时区公共化：`HUD_TIMEZONE` > 系统本地时区 > UTC，不再隐式固定 Asia/Shanghai。

### Performance

- Snapshot 共享缓存 + 单飞锁：REST 与 WebSocket 共用同一份快照，
  同一时间不并发重复跑完整 collector（实测 2 客户端 10 分钟：600 请求 → 约 300 次 collector）。
- telemetry 落盘限频：每 60 秒最多一次（此前每个 2 秒轮询都写库）。
- 自动 retention：`maintenance()` 每天最多一次清理过期指标（30 天）与已恢复事故（90 天），
  上次执行时间持久化在 meta 表，重启后依然低频。

### Compatibility

- launchd 检测使用当前 UID（`gui/<os.getuid()>`），不再硬编码 `gui/501`；
  非 macOS 平台 `launchd.status = not_applicable`，不再产生误导性 warning。
- 安装/卸载改用官方增量命令 `hermes plugins enable/disable hermes-hud`，
  不再覆盖用户其他插件的 enabled 状态。
- README 明确支持范围：**Tested: macOS；Linux: expected / community testing welcome；
  Windows: experimental**。

## [1.0.0] - 2026-08-23

- 首个公开版本：11 个中文 Tab（指挥中心 / 实时活动 / Token·费用 / 对话记录 / 记忆 /
  技能 / 定时任务 / 渠道 / 错误·事故 / 系统·存储 / 设置）。
- 事故主动推送告警（Telegram + 飞书）`scripts/hud_alert.py`。
- telemetry.db 分钟级时序（独立于 state.db，只读 Hermes 核心数据）。
- 健康规则引擎 + 事故生命周期（active → recovered 保留时间线）。
- 只读安全边界：不读取 .env / auth.json、无 outbound 遥测、日志先脱敏。
