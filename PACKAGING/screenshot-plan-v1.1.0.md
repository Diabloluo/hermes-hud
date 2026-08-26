# v1.1.0 Release Screenshot Plan（只准备，不伪造生产数据）

## 方案：3 张截图（真实隔离环境 + demo fixture，明确标注）

1. **Timeline**（🕒 时间线 Tab）
   - 环境：隔离 HERMES_HOME + 真实 state.db 只读（HUD_STATE_DB）或 demo fixture
   - 展示：事件流（session/tool/incident 类型混合）、✓/✕ 状态、耗时/Token 列、过滤条
   - 脱敏：summary 已 sanitized；不展开详情（避免 session id 全量）

2. **Skill Analytics**（📊 技能分析 Tab）
   - 环境：真实 registry（148 skills）+ 隔离 telemetry（demo-skill 事件，标注 demo）
   - 展示：Summary 卡（已注册/已观测/成功率）+ coverage 警告 + 表格（含"未观测到执行"）

3. **Cost Intelligence**（¥ Token·费用 Tab）
   - 环境：真实 state.db（估算费用已脱敏展示，不含任何密钥）
   - 展示：估算费用卡 + /cost/timeseries 趋势 + 模型分布 + Top Sessions（脱敏标题）

## 规则
- 全部真实数据脱敏（无 session 标题原文、无路径、无模型密钥）
- demo fixture 截图必须标注 "demo"（不冒充生产）
- 截图脚本：PACKAGING/safe_chrome_capture.py（独立 profile + CDP，零触碰用户 Chrome）
- 产出：assets/screenshot-timeline.png / assets/screenshot-skill-analytics.png / assets/screenshot-cost.png（发布前由维护者审阅）
