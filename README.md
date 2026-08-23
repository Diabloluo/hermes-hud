# Hermes HUD 🛰️

> 本地实时监控指挥中心 —— 把 Hermes Agent 的运行状态、Token/费用、模型、记忆、会话、定时任务、渠道、错误和机器健康完整摊开，异常发生时立即看见。

一个**用户级 Hermes Dashboard 插件**：不修改 `~/.hermes/hermes-agent` 核心代码，Hermes 升级不覆盖，可一键禁用/回滚。

![tabs](https://img.shields.io/badge/10%20Tabs-全中文-4ade80) ![license](https://img.shields.io/github/license/Diabloluo/hermes-hud) ![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)

## ✨ 功能

| Tab | 内容 |
|---|---|
| ◉ 指挥中心 | 健康分（正常/警告/故障）、Gateway/渠道/Cron 状态、今日 Token/费用、30 项健康检查、事故时间线、系统迷你卡 |
| ⚡ 实时活动 | 活跃会话、2 秒增量事件流（WebSocket + 轮询兜底）、最近工具调用 |
| ¥ Token·费用 | 7/30/90 天趋势、按模型/辅助任务归集、费用明确标注"估算/实际/未计价" |
| ☰ 对话记录 | 搜索、分页、会话详情（消息预览 + model usage） |
| 🧠 记忆 | MEMORY.md/USER.md 元数据、锁文件健康 |
| ⚒ 技能 | 技能目录统计、分类分布、131+ 技能列表 |
| ⏱ 定时任务 | 任务启停/排程/失败次数 + 执行历史（claimed→running→completed/failed） |
| ⇄ 渠道 | Telegram/飞书等"已连接但持续抖动"正确标黄（不再被 connected 掩盖） |
| ⚠ 错误·事故 | 30 分钟错误数、异常指纹聚合、事故时间线（含已恢复保留）、脱敏日志尾部 |
| ▤ 系统·存储 | CPU/内存/磁盘/进程、launchd 托管状态、telemetry 趋势图 |
| ⚙ 设置 | 阈值/预算/保留期、采集器数据质量、安全边界、一键切换 Dashboard 菜单语言 |

**附带**：`scripts/hud_alert.py` —— 事故主动推送告警（Telegram + 飞书），检测到新事故/升级/恢复时自动推送，带防抖去重。

## 📦 安装

```bash
# 1. 克隆到用户插件目录
git clone https://github.com/Diabloluo/hermes-hud ~/.hermes/plugins/hermes-hud

# 2. 加入 plugins.enabled 白名单（后端 API 载入门槛）
hermes config set plugins.enabled '["hermes-hud"]'

# 3. 构建 Dashboard Web UI（首次）
cd ~/.hermes/hermes-agent && npm run install:web
cd web && npm run build

# 4. 启动 Dashboard
hermes dashboard --host 127.0.0.1 --port 9119 --no-open
# 浏览器打开 http://127.0.0.1:9119 → 侧边栏 "Hermes HUD"
```

### 告警推送（可选）

```bash
# 需要 .env 里有：
#   TELEGRAM_BOT_TOKEN + TELEGRAM_HOME_CHANNEL
#   FEISHU_APP_ID + FEISHU_APP_SECRET + FEISHU_ALLOWED_USERS（open_id）
cp scripts/hud_alert.py ~/.hermes/scripts/hud_alert.py
# 测试
python3 ~/.hermes/scripts/hud_alert.py --dry-run
# 挂 cron（每 5 分钟，Hermes 内）：
hermes cron add --script hud_alert.py --schedule '*/5 * * * *' --no-agent
```

## 🏗 架构

```
Hermes 现有数据源（只读）
  ├─ state.db / session_model_usage     ← SQLite 只读连接 (mode=ro)
  ├─ cron/jobs.json / executions.db
  ├─ gateway_state.json / 进程存活
  ├─ memories/ (MEMORY.md / USER.md)
  ├─ logs/ (agent.log / errors.log)
  └─ ~/.hermes/skills/                  ← SKILL.md 元数据扫描
                 │
                 ▼
       hermes-hud plugin_api.py
  collectors → normalizer → rules engine（健康规则）
                 │
        ┌────────┴────────┐
        ▼                 ▼
 snapshot REST       authenticated WebSocket
        │                 │
        └────────┬────────┘
                 ▼
        Hermes HUD 中文 Tab 界面
                 │
                 ▼
      ~/.hermes/hud/telemetry.db
   （分钟级指标 / 事故指纹 / 短摘要）
```

- 插件 API 挂 `/api/plugins/hermes-hud/`，复用 Dashboard 标准 session-token 鉴权
- WebSocket 走 Dashboard 标准鉴权门（`_ws_auth_ok`），不发明第二套 token
- telemetry.db 独立于 state.db，可整体删除重建

## 🔒 安全边界

- 默认只监听 `127.0.0.1`，无任何 outbound 遥测
- 不读取/返回 `.env`、`auth.json`、完整 token
- 日志/对话/记忆先脱敏（key/token/secret/bearer/JWT/长 hex/base64）
- 对话与记忆正文不进事件流，详情按需加载且只给短预览
- telemetry.db 只存聚合、异常指纹与短摘要
- 全部操作只读；安装/删除跳转现有 Dashboard 受保护页面

## 📊 数据口径

- **费用三类分开**：`实际`（provider 账单）/ `估算`（按模型价表）/ `未计价`。无账单数据时一律标"本地估算"
- **主/辅不重复计数**：主会话读 `sessions`，辅助调用读 `session_model_usage.task != ''`，按 (session, model, task) 去重
- **日界线 Asia/Shanghai**，DB 的 UTC epoch 仅查询时转换
- **state.db 全程只读**：`mode=ro` + 短超时 + `query_only`，不锁 Gateway

## 🩺 健康规则（阈值可用 `HUD_*` 环境变量覆盖）

| 级别 | 规则 |
|---|---|
| 🔴 critical | Gateway 进程不存活；state.db 不可读；磁盘 < 5%；Cron 连续失败 ≥ 3 |
| 🟡 warning | 渠道 connected 但心跳 > 60s（抖动）；近 30 分钟错误 > 20；磁盘 < 15%；内存 > 85%；launchd 脱管；今日费用超日预算 80% |

> 实测经验：`gateway_state.json` 是"状态变化写盘"不是周期心跳（可能 60+ 分钟不更新但进程正常），因此**进程存活才是 critical 依据**，状态文件陈旧只给 warning。

## ❓ 常见问题

- **Dashboard 打开是桌面引导页（"Desktop boot failed"）**：从 Hermes 桌面 App 的 shell 里启动时继承了 `HERMES_DESKTOP=1` + `HERMES_WEB_DIST`，用 `env -u HERMES_WEB_DIST -u HERMES_DESKTOP -u HERMES_SERVE_HEADLESS hermes dashboard ...` 启动
- **菜单语言重启后变英文**：菜单语言存浏览器 localStorage（`hermes-locale`），与服务器重启无关；HUD 设置页有一键"固定为中文菜单"
- **插件不显示**：确认 `hermes config set plugins.enabled '["hermes-hud"]'` 后重启 dashboard
- **后端 401**：loopback 模式 token 注入在页面 HTML，前端自动携带；curl 需抓取

## 🧩 兼容性

- Hermes v0.20+（Dashboard 插件 SDK：manifest.json + plugin_api.py + IIFE bundle）
- 升级 Hermes 后重新 `npm run build`（web UI），插件本体无需改动
- 完整卸载：`hermes config set plugins.enabled '[]'` + 删除插件目录

## 📄 License

MIT
