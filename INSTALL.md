# 安装指南（Install）

面向第一次安装 Hermes HUD 的用户。安装路径最初以 HUD v1.1.0 在全新隔离环境验证；Fresh Install CI 仍固定 Hermes 0.19.0。2026-11-09 对 Hermes 0.23.0 的检查使用已有依赖环境，只覆盖隔离核心链路，不能代替全新安装验收。详见[兼容检查范围](docs/quality/HERMES_023_COMPATIBILITY_20261109.md)。

## 前置要求

| 项 | 要求 |
|---|---|
| Hermes | 既定最低版本 **v0.19.0**；Fresh Install CI 固定 PyPI 0.19.0。更新版本按已核验范围使用，不把最低版本声明当逐版兼容保证。v0.19 的 `config set` 会存字符串，启用脚本优先通过官方 config API 保留数组语义 |
| 平台 | macOS（已验证）；Linux 预计可用；Windows experimental |
| Python | 运行 `enable_dashboard_plugin.py` 需 Python 3.8+（macOS 自带 `python3` 即可；建议用 Hermes 的 python 环境以启用官方 config API 路径） |
| 权限 | 无需 sudo；全部写入用户目录 |

> ⚠️ **Hermes 插件机制提醒**：Hermes 有两种插件——
> - **原生插件命令**以 `plugin.yaml` / `plugin.yml` / `plugin.json` 等原生 manifest 发现插件
> - **Dashboard 插件**（`manifest.json` + `plugin_api.py`）通过 config 的 `plugins.enabled` 白名单启用
>
> Hermes HUD 当前只有 **Dashboard 插件** manifest。0.23.0 隔离实测中，
> `hermes plugins disable hermes-hud` 返回 `No plugin named 'hermes-hud'`，未改变配置；旧版本也可能报 "Plugin not installed or bundled"。请使用下方仓库自带脚本，不用原生插件命令替代。

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

- 通过 Hermes config CLI 读取 `plugins.enabled`；旧版 CLI 不支持读取时，回退官方 config loader API，不自行解析 YAML
- 保留现有插件，仅追加 `hermes-hud`；再次启用不重复追加
- 写回优先用官方 config API，无法导入时才回退 CLI；无法可靠读取配置时退出，不猜测空列表

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

此步骤只从 `plugins.enabled` 移除 `hermes-hud`，保留其他插件和配置；重启 Dashboard 后生效，不删除插件文件或 HUD 本地历史。

如需清理文件，先确认已禁用且运行中的 Dashboard 不再使用插件，再按自己的备份要求处理插件目录。不要仅改名为 `.bak` / `disabled` 后仍放在 `plugins/` 内：发现逻辑可能读到旧副本。HUD 历史位于 `~/.hermes/hud/`，不属于禁用步骤。若曾单独配置 `hud_alert.py` 或告警 Cron，也需另行停用；禁用 Dashboard 插件不会自动移除它们。

2026-11-09 只验收了隔离配置的启用、重复启用和禁用，未演练完整卸载或删除用户历史。

## 故障排查

| 现象 | 原因与处理 |
|---|---|
| 原生 `hermes plugins enable/disable hermes-hud` 报未安装或 `No plugin named` | 当前 HUD 包没有原生命令所需 manifest，用 `enable_dashboard_plugin.py enable/disable` |
| 插件已启用但侧边栏没有 HUD | 重启 Dashboard（插件在启动时挂载） |
| 后端接口 401 | loopback 模式 token 注入在页面 HTML，前端自动携带；curl 需从 `http://127.0.0.1:9119/` 提取 `window.__HERMES_SESSION_TOKEN__` |
| 想用 `hermes plugins install` 安装 | 未作为当前 HUD 包的安装验收路径；请用上方 git clone + 脚本方式，不据此跳过宿主安全检查 |

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
