# Dutybook 产品策略备忘

日期：2026-08-30
仓库：https://github.com/Diabloluo/hermes-hud（暂不改名）
产品名：Dutybook（值班本）
范围：只谈方向、节奏、命名、对外话术。不改代码。

---

## TL;DR

有前途的是品类，不是现在这个壳。

- **Hermes 专用 Dashboard 插件**：天花板低。Hermes 用户多，但 Dashboard 插件是生态里的缝，而且已经有一堆 WebUI / TUI 抢注意力。
- **跨 Codex / Claude Code 的本地观测**：是真品类，也是已经被占的路。做成「第三个 token 面板」会输在覆盖面上。
- **Dutybook 该打的**：always-on 的账本 + 事故。估算 / 实际 / 未计价分开；渠道抖动、Cron 连续失败、事故指纹。本机只读。
- **已拍板**：产品名 Dutybook。GitHub 仓库本周仍是 `hermes-hud`。插件在官方 Dashboard 里仍可叫 HUD。
- **节奏**：先把 Hermes 打透到有真实用户，再接 **一个** 第二 adapter（Codex 或 Claude Code，选你自己天天用的那个）。不要四个半成品并行。

一句话：做成「Hermes 专用的可靠账本，再挂 adapter」，有位置；做成「又一个 TokenTelemetry」，没有。

---

## 1. 现在这个产品是什么

本地、只读、挂在官方 `hermes dashboard` 上的用户级插件，外加已签名公证的 macOS Desktop Alpha。

它看的是运营，不是聊天：

- 花费：估算 / 实际 / 未计价，三类分开，主辅调用不重复计数
- 健康：Gateway / 飞书 / Telegram 是真活着，还是 connected 但在抖
- Cron 连续失败
- 事故指纹：新事故 vs 同一类错误在刷
- 约束：`127.0.0.1`，无出站遥测，`state.db` 只读，日志先脱敏再指纹

**不是**：独立 WebUI、agent workspace、多 agent IDE、聊天客户端。

这个楔子是对的。错的是把未来押在「Hermes 插件」这个壳上，或押在「接入所有 coding agent 的 session 列表」上。

---

## 2. Hermes 单点：有用，但长不大

Hermes Agent 本身盘子大。可是：

- 用户要的「更好的界面」已经被 hermes-studio、hermes-workspace、joeynyc/hermes-hud（TUI）、hudui 占了。
- 搜 `hermes-hud` 会先撞到别人。README 已经加了声明，冲突不会消失。
- Dashboard 插件的分发绑定官方插件机制和 `hermes dashboard` 的打开率。不用官方 Dashboard 的人，根本看不到你。
- 星数和讨论会停在 Hermes 插件爱好者，而不是「跑多个 agent 的人月底对账」那个更大的池子。

结论：Hermes 是最好的 **第一个 adapter**，不是产品的永久边界。

---

## 3. 跨 agent 观测：品类真，赛道挤

人同时开 Hermes / Codex / Claude Code，月底不知道钱花哪了。这件事会变成刚需。

但这条路 **2026 年已经有人在铺**：

| 产品 | 打法 | 对你的含义 |
|---|---|---|
| [tokscale](https://github.com/junhoyeo/tokscale) | CLI，覆盖几十个 agent 的 token / 花费 | 覆盖面头部。别去拼 agent 列表长度。 |
| [TokenTelemetry](https://tokentelemetry.com/) | 本地 dashboard：Claude Code / Codex / Cursor / Hermes… 还有 Hermes Dashboard 插件 | 几乎是你「以后接 Codex」的预演。功能面重叠最大。 |
| [agent-ledger](https://github.com/zhenzhis/agent-ledger) 及若干同名仓库 | 本地 FinOps / 账本 / 预算 | **Ledger 这个词已经不能当产品名。** |
| [AgenticLedger](https://github.com/ShekharBhardwaj/AgenticLedger) / [AgentLedger](https://github.com/WDZ-Dev/agent-ledger) | 透明代理，拦 LLM 流量计费 | 另一条技术路线（代理 vs 读本地库）。不要跟他们比「拦流量」。 |
| [agentglass](https://github.com/SirAllap/agentglass) | 座舱 + workspace（diff / git / docker / 聊天） | 那是 IDE。你不要去做这个。 |
| AgentBudget / FiGuard / SpendOS | 预算 **拦截**、事前授权 | 你是只读观测。别变成断路器，除非以后单独卖。 |

共同特征：token、session、本机、多 agent。他们弱的通常是：

- 估算和账单搅在一起
- 不管 Telegram / 飞书算不算活着
- 不管 Cron 是不是在烧钱
- 不管同一类错误刷了多少次

那三块是 Hermes 给你的 fort，也是以后接别的 agent 时该 **复用的数据模型**，不是再画一套聊天页。

---

## 4. Dutybook 该成为什么

**本地 agent 的值班本。** 不是仪表盘，不是 workspace。

值班结束你要能回答：

1. 这班花了多少（估算 / 实际 / 未计价，分得开）
2. 哪个渠道或任务在抖
3. 这是新事故，还是同一类在刷
4. 数据有没有离开过这台机器

### 做

- 诚实花费（三类桶、不重复计数、不把估算写成发票）
- 事故指纹 + 恢复确认
- 渠道 / Cron / Gateway 的 always-on 健康
- 只读、脱敏、本机绑定
- Desktop 当「打开值班本」的壳（签名 macOS 已经是差异）
- 每个 agent 是 adapter：先把源映射进 **同一套** 花费桶和事故模型

### 不做

- 15 个 agent 的 session 浏览器（tokscale / TokenTelemetry 的主场）
- 聊天、diff、git、docker、多 agent IDE（agentglass / studio 的主场）
- 代理流量、硬预算熔断（AgentLedger / AgentBudget 的主场；只读是信任来源）
- 云端账号、出站遥测、「官方出品」话术
- 为了覆盖面先接四个 harness

### 和竞品的一句话差

他们数 token。你值这班。

---

## 5. 命名（已拍板）

**产品名：Dutybook**（对外中文可写「值班本」）。

弃用的名字和原因：

- **Hermes HUD**：锁死 Hermes；GitHub 搜先撞 joeynyc。
- **Ledger / Agent Ledger**：同赛道重名堆叠。
- **Accrue**：两家金融公司（byaccrue、useaccrue），`accrue.app` / `accrue.io` 已有主。会计语义对，商标风险不对。
- **Glass / HUD / Token / Telemetry**：要么撞名，要么变成他们。

备选（若以后 Dutybook 不好用再看，现在不要换）：

- Cost Truth（`costtruth`）：GitHub 零命中，楔子极准，略像口号。
- Tallybox：本机清点，适合桌面，偏软。

### 仓库先不动

Desktop 已用 Developer ID 签过，插件目录是 `hermes-hud`，Show HN 链接已经在传。

改名窗口：第二个 adapter 要上，或星过约 50。之前只改 **对外心智**：

- 产品：Dutybook
- 仓库：`Diabloluo/hermes-hud`
- Dashboard 插件显示名：可以暂时仍叫 HUD
- 副标题：local dutybook for spend and incidents

---

## 6. 节奏

| 阶段 | 目标 | 不要做什么 |
|---|---|---|
| 现在 → Show HN 后 2 周 | Hermes 打透：真实安装、费用页被用、事故页有人反馈 | 不接 Codex / Claude Code；不改仓库名；不上 Product Hunt |
| 有 10–20 个真实用户或 ~50★ | 写清 adapter 合同：花费三桶 + 事故指纹 + 只读源。接 **一个** 第二源 | 不要两个一起接 |
| 第二源能复用同一套事故/花费模型 | 再考虑改仓库名、Desktop 主品牌换成 Dutybook | 不要顺手做 workspace |

第二源怎么选：你自己天天用的那个。没有日常流量的 adapter 是展览。

跨 agent 的正确形状：

```
Dutybook 核心：花费三桶 · 事故指纹 · 值班健康 · 只读
    ├── Hermes adapter（现在，最深）
    ├── Codex adapter（第二个，候选）
    └── Claude Code adapter（第三个，或反过来）
```

每个 adapter 只负责：从本机已有日志/DB **读** 出能填进核心模型的字段。填不满的字段就标明「未知」，不要为了填满去发明聊天 UI。

---

## 7. 商业化（原则，不是定价表）

- 插件保持免费、只读、开源。这是信任和分发。
- 收费壳是 Desktop：发现本机 Dashboard、签名安装、以后的值班提醒。
- 可卖的深度：诚实对账、预算 **观察**（到点提醒，不熔断）、事故摘要。观察和熔断要分产品，熔断会改信任模型。
- 不要做云同步。本机是卖点。

现在 2 星，不要谈价格。先有人每天打开费用页。

---

## 8. 对外话术

### 一句话（中）

Dutybook 是本地 agent 值班本：花费分得清，事故分得清，渠道和 Cron 看得到，数据不出机器。Hermes 是第一个 adapter。

### 一句话（英）

Dutybook is a local, read-only duty log for agents: honest spend (estimated / actual / unbilled), incident fingerprints, and always-on health. Hermes is the first adapter — not the TUI named Hermes HUD.

### 周一 Show HN（仓库名先不动）

标题方向：

`Show HN: Hermes HUD – Dutybook for local agent spend and incidents (not the TUI)`

正文继续强调：官方 Dashboard 插件、三类花费、渠道/Cron、只读；用一句点出产品名 Dutybook，以及「以后会接别的 agent，现在只把 Hermes 做对」。

### README 副标题（以后改文案时用，本次不改仓库）

`Dutybook — local duty log for agent spend and incidents. First adapter: official Hermes Dashboard plugin.`

---

## 9. 明确的决策记录

| 决策 | 状态 |
|---|---|
| 产品名 Dutybook | 已拍板（2026-08-30） |
| 仓库仍为 Diabloluo/hermes-hud | 已拍板，暂不改 |
| 品类：值班本（账本 + 事故），不是 token 面板 / IDE | 已拍板 |
| 先深 Hermes，再接一个第二 adapter | 已拍板 |
| 不做 V2EX 付费邀请、不上 Product Hunt、不改代码扩 harness | 已拍板 |
| Show HN | 周一；标题带 Dutybook + 撞名声明 |

---

## 10. 以后若走偏，用这三句纠偏

1. 又在加第 N 个 agent 的 session 列表，而事故模型和花费三桶还没在 Hermes 上被真实用户用过？停。
2. 界面开始像聊天或 workspace？停。
3. 为了「准」去写回 agent 的库、或拦 API 做熔断？停。那是另一个产品。
