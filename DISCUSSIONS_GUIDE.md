# 开启 GitHub Discussions 指引

> 本文件是给**仓库维护者**的指引，说明如何开启 Discussions 并按社区最佳实践组织分类。
> 当前仓库状态：Discussions **未启用**（`has_discussions: false`，2026-08-23 确认）。
> 是否开启由维护者决定——HUD 本身不依赖 Discussions 运行。

## 为什么建议开启

- **Issues 留给 Bug / 兼容性**（有模板），讨论、提问、想法走 Discussions，互不干扰
- 潜在贡献者可以先提问再动手，降低 PR 摩擦
- "Show and Tell" 分类给社区晒配置/用法，自然形成口碑传播

## 开启步骤（维护者手动，2 分钟）

1. 打开仓库 **Settings → General**
2. 滚到 **Features** 区块，勾选 **Discussions**
3. 点 **Set up discussions**，按下方建议创建分类（或先默认再改）

> GitHub API 不支持程序化开启 Discussions（`PATCH /repos/{owner}/{repo}` 无此字段），
> 必须 Web UI 手动操作。

## 建议分类

| 分类 | 用途 | 备注 |
|---|---|---|
| **General** | 公告、杂项、仓库级话题 | 默认存在 |
| **Installation Help** | 安装/启用/卸载问题 | 引用 [INSTALL.md](INSTALL.md) |
| **Compatibility** | Linux/Windows/其他环境实测报告 | 与 [Compatibility 模板](.github/ISSUE_TEMPLATE/compatibility_report.yml) 互补 |
| **Ideas** | 功能想法、改进建议 | 对应 ROADMAP 的 Exploring |
| **Show and Tell** | 用户晒 HUD 配置、告警玩法、二次开发 | 传播价值高 |

## 使用约定（建议写入分类描述）

- **Bug 一律走 Issues**（模板含 Hermes/HUD 版本、平台、复现步骤）——Discussions 里的 Bug 讨论请转移到 Issues
- 安装问题先看 **INSTALL.md** 故障排查表再提问
- 提功能想法时说明：想解决什么场景，而不是只给方案
- 保持礼貌；HUD 是个人开源项目，维护者按自己的节奏响应

## 分类创建操作

1. **Settings → Discussions → Edit**（或首次 setup 时）
2. 对每个分类：名称、描述、表情符号
3. 示例配置（YAML 描述文本）：

```text
Installation Help — 安装/启用/卸载相关问题。先看 INSTALL.md 再提问。
Compatibility — Linux / Windows / 其他环境实测结果报告。
Ideas — 功能想法与改进建议（说明你想解决的场景）。
Show and Tell — 晒出你的 HUD 配置、告警玩法、二次开发。
```

## 开启后的 README 联动

开启后把 README「🤝 社区」段的 Discussions 占位文案替换为真实链接：

```markdown
- **Discussions**：[提问 / 想法 / 安装帮助](https://github.com/Diabloluo/hermes-hud/discussions)
```

（当前 README 保留占位建议——未开启时不放失效链接。）
