# 安装指南（Install）

面向第一次安装 Hermes HUD 的用户。全文基于 v1.1.0 在全新隔离环境（`HERMES_HOME` 指向空目录）实测通过的路径。

## 前置要求

| 项 | 要求 |
|---|---|
| Hermes | **v0.19.0+**（CI 以 PyPI 0.19.0 全链路实测：install/enable/config-safety/dashboard/HTTP smoke 全绿；v0.19 的 `config set` 会存字符串，本仓库 enable 脚本已统一走官方 config loader API 读写，两版本数组语义一致） |
| 平台 | macOS（已验证）；Linux 预计可用；Windows experimental |
| Python | 运行 `enable_dashboard_plugin.py` 需 Python 3.8+（macOS 自带 `python3` 即可；建议用 Hermes 的 python 环境以启用官方 config API 路径） |
| 权限 | 无需 sudo；全部写入用户目录 |

> ⚠️ **Hermes 插件机制提醒**：Hermes 有两种插件——
> - **原生插件**（`plugin.yaml`/`__init__.py`）由 `hermes plugins enable/disable` 管理
> - **Dashboard 插件**（`manifest.json` + `plugin_api.py`）通过 config 的 `plugins.enabled` 白名单启用
>
> Hermes HUD 是 **Dashboard 插件**，`hermes plugins enable hermes-hud` 对它无效（会报
> "Plugin not installed or bundled"）。请使用下方仓库自带脚本。

## 安装（3 步）

### 1. 克隆到用户插件目录

```bash
git clone https://github.com/Diabloluo/hermes-hud ~/.hermes/plugins/hermes-hud
```

### 2. 启用插件（读取→合并→写回，保留你已有的其他插件）

```bash
python3 ~/.hermes/plugins/hermes-hud/scripts/enable_dashboard_plugin.py enable
```

脚本语义（幂等，可重复执行）：

- 读取 `plugins.enabled`（走 Hermes config CLI，不解析 YAML）
- 保留所有现有插件，仅追加 `hermes-hud`
- 写回

### 3. 启动 / 重启 Dashboard

```bash
hermes dashboard --host 127.0.0.1 --port 9119 --no-open
```

打开 **http://127.0.0.1:9119** → 侧边栏出现 **Hermes HUD** 即成功。

> 仓库自带预构建前端（`dashboard/dist/`），**无需**重新构建 Hermes Web UI。
> 若 Dashboard 已在运行，重启它（如 launchd 托管：`launchctl kickstart -k gui/$(id -u)/ai.hermes.dashboard`）。

## 验证安装

```bash
# 1. 插件在已启用列表
hermes config get --json plugins.enabled
#    → 应包含 "hermes-hud"

# 2. Dashboard 后端路由可访问（token 从页面 HTML 注入，前端自动携带）
#    打开 http://127.0.0.1:9119/hud 应看到 HUD 指挥中心
```

## 卸载

```bash
python3 ~/.hermes/plugins/hermes-hud/scripts/enable_dashboard_plugin.py disable
```

只移除 `hermes-hud`，其他插件全部保留。重启 Dashboard 后 HUD 消失。
彻底删除：`rm -rf ~/.hermes/plugins/hermes-hud`（可选）。

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| `hermes plugins enable hermes-hud` 报 "not installed or bundled" | 正常——HUD 是 Dashboard 插件，用 `enable_dashboard_plugin.py enable` |
| 插件已启用但侧边栏没有 HUD | 重启 Dashboard（插件在启动时挂载） |
| 后端接口 401 | loopback 模式 token 注入在页面 HTML，前端自动携带；curl 需从 `http://127.0.0.1:9119/` 提取 `window.__HERMES_SESSION_TOKEN__` |
| 想用 `hermes plugins install` 安装 | 该命令走供应链扫描且针对原生插件，**不推荐**作为 HUD 安装路径（会触发扫描告警且仍需 config 白名单）；请用上方 git clone + 脚本方式 |

## 数据与隐私

- HUD 只读 Hermes 核心数据（`state.db` 用 `mode=ro` + 短超时，不锁 Gateway）
- HUD 只写自己的本地数据：`~/.hermes/hud/`（telemetry.db、alerts_state.json）
- 无任何出站遥测；Dashboard 默认只监听 `127.0.0.1`
- 告警推送（可选）见 `scripts/hud_alert.py`，需自行配置 Telegram/飞书凭据

## 升级

```bash
cd ~/.hermes/plugins/hermes-hud && git pull
# 重启 Dashboard 生效
```

版本变化见 [CHANGELOG.md](CHANGELOG.md)。
