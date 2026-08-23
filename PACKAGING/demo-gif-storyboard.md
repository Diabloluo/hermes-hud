# Demo GIF Storyboard — assets/demo.gif

**目标**：15–25 秒循环 GIF，展示 HUD 四个核心画面。用于 README 首屏（替换/补充静态截图）。
**录制方式**：浏览器打开 `http://127.0.0.1:9119/hud`（真实数据），用 `screencapture`/OBS 录制
1680×1050 窗口，ffmpeg 转 GIF（`fps=10, scale=1200:-1`，palette 优化）。
**注意**：录制前若担心隐私，可临时用 `?tab=` 直达各页；公开素材避免出现业务 cron 名，
建议录制 Token·费用 / 技能页（无业务名）为主，Overview 只取健康区。

| 时间 | 镜头 | 画面 | 旁白/字幕 |
|---|---|---|---|
| 0.0–4.0s | 1 | **Overview 指挥中心**（`/hud`）：健康徽章、Gateway/渠道状态、今日 Token/费用、健康检查列表 | "Hermes HUD — 本地实时指挥中心" |
| 4.0–5.0s | 过渡 | 切换到 Token·费用页（`?tab=usage`） | |
| 5.0–12.0s | 2 | **Token·费用**：7/30/90 天趋势切换（点 30 天）、按模型归集表、辅助调用类型表、费用"估算"标签 | "Token / 费用 — 按模型与辅助任务归集" |
| 12.0–13.0s | 过渡 | 切换到技能页（`?tab=skills`） | |
| 13.0–18.0s | 3 | **技能**：总数/分类统计卡、分类筛选按钮点击（productivity→creative）、技能列表滚动 | "131+ 技能 — 目录统计与分类筛选"（公开文案避免写死数量，用"技能目录统计"） |
| 18.0–19.0s | 过渡 | 切换到错误·事故页（`?tab=incidents`） | |
| 19.0–25.0s | 4 | **错误·事故**：30 分钟错误数、错误指纹 TOP、事故时间线（含"已恢复"保留条目） | "异常即现 — 指纹聚合 + 事故时间线" |

**镜头清单（拍摄用）**：
1. 打开 `/hud`，等 2 秒数据加载，停留 4 秒
2. 点 Tab「Token·费用」→ 点「30 天」→ 停留 7 秒
3. 点 Tab「技能」→ 点分类「creative」→ 回「全部」→ 停留 5 秒
4. 点 Tab「错误·事故」→ 停留 6 秒
5. 循环（GIF 无缝回放，首尾均为 Overview）

**ffmpeg 转换命令**：
```bash
# 录制（OBS/screencapture）得到 demo.mov 后：
ffmpeg -i demo.mov -vf "fps=10,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" -loop 0 assets/demo.gif
```

**验收**：GIF ≤ 2MB、时长 20±5s、四画面顺序正确、无业务敏感信息。
