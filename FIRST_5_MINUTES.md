# 上手 5 分钟（First 5 Minutes）

安装完成后（见 [INSTALL.md](INSTALL.md)），用 5 分钟熟悉 HUD 怎么看、怎么用。

## 第 0 分钟：打开

浏览器打开 **http://127.0.0.1:9119** → 侧边栏点 **Hermes HUD**。
页面顶部状态条：健康徽章（绿=正常 / 黄=警告 / 红=故障）+ 今日费用 + 模式（WS 实时）。

## 第 1 分钟：指挥中心（默认页）

从上到下扫一遍：

1. **健康徽章**——总览级告警（`0红 / N黄`）。黄/红看健康检查列表定位
2. **健康检查**（约 30 项）——Gateway 存活、渠道心跳、磁盘/内存、state.db 只读、launchd 托管、今日预算
3. **事故时间线**——最近事故（含已恢复的保留——你能看到"这周到底出过什么问题"）

> 黄/红不全是坏事：它说明 HUD 的告警在正常工作。

## 第 2 分钟：Token·费用页

- **7/30/90 天**趋势切换
- **按模型**归集：主会话 + 辅助任务分开
- 费用三类口径：**估算 / 实际 / 未计价**（别拿估算当实际）

> 数据口径说明：辅助调用只统计 `task != ''` 的行（v1.0.1 修复），API 次数用库内累计值。

## 第 3 分钟：错误·事故页

- **近 30 分钟错误数** + 异常**指纹聚合**（同类错误合并，显示脱敏后的样本）
- **事故时间线**——每次事故的首次/末次/观测次数

> 错误页的样本已脱敏（token/路径不出现），可放心截图分享。

## 第 4 分钟：设置页（可选）

- 切换 Dashboard 菜单语言（中文 / English）
- 查看采集器数据质量（哪个采集器失败、为什么）
- 阈值/预算/保留期可按需调整

## 第 5 分钟：告警推送（可选，非安装必需）

想让"新事故/升级/恢复"实时推送到手机：

```bash
# 1. 确认 Telegram/飞书机器人凭据已在 ~/.hermes/.env（或环境）
# 2. 用 cron 挂告警脚本（示例）：
hermes cron add --script ~/.hermes/plugins/hermes-hud/scripts/hud_alert.py --no-agent --schedule "*/5 * * * *" --name "HUD 事故告警"
```

> 不配置告警不影响 HUD 使用——Dashboard 本身就是监控入口。

## 常见问题速查

| 问题 | 答案 |
|---|---|
| 侧边栏没有 HUD？ | 重启 Dashboard（见 INSTALL.md 故障排查） |
| 健康检查一片红？ | 先看 Gateway 是否运行（`hermes gateway status`）——隔离环境无 Gateway 时红是预期 |
| 费用显示为 0？ | 全新环境无历史数据正常；有数据后自动累计 |
| 想换统计时区？ | 设置 `HUD_TIMEZONE`（如 `Asia/Shanghai`），默认取系统本地时区 |

## 下一步

- [INSTALL.md](INSTALL.md) —— 完整安装/卸载/故障排查
- [ROADMAP.md](ROADMAP.md) —— 规划中的能力
- 遇到问题 → [Issues](https://github.com/Diabloluo/hermes-hud/issues/new?template=bug_report.yml)
