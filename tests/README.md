# Tests

Hermes HUD 测试套件（pytest，无第三方测试依赖）。

## 运行

```bash
pip install pytest
python -m pytest tests/ -q            # 全部单元测试
python -m pytest tests/ --ignore=tests/performance_verify.py   # CI 同款
```

## 覆盖范围

| 文件 | 审计项 | 内容 |
|---|---|---|
| `test_redaction.py` | P0-1/P0-2 | 脱敏规则全矩阵（Bearer/JWT/sk-/bot token/JSON quoted keys/URL userinfo/长 hex/b64）+ fingerprint 脱敏后生成 |
| `test_incident_lifecycle.py` | P1-5/P1-4/P1-8 | observations/state_changes 语义、恢复状态机、旧库 schema 平滑迁移、cron 指纹稳定、launchd not_applicable |
| `test_alert_state_machine.py` | P0-3 | 告警推送完整状态机：新事故/恢复成功/全部失败 pending/限流重试/回归 active/dry-run |
| `test_usage_accounting.py` | P1-3 | Token/费用 fixture 手工对账（task='' 排除、api_call_count 累计） |
| `test_storage_retention.py` | P1-2 | prune 清理、maintenance 每天最多一次（meta 持久化） |
| `test_platform_detection.py` | P1-8 | 非 macOS not_applicable、动态 UID、rules 处理 |
| `test_privacy_sanitizer.py` | P1-6 | sanitize_path/sanitize_cmdline/redact_obj 全矩阵 |
| `test_secrets_scan.py` | §八 | 测试 secret 全链路 0 occurrence（含真实 telemetry 只读扫描） |

## 安全约束（CI 与本地一致）

- 全部使用 tempfile / fixture / mock；**不读取真实 ~/.hermes**（仅
  `test_real_telemetry_readonly_scan` 以只读模式扫描验证，缺目录自动 skip）
- **不访问真实 Telegram / 飞书**；不发送任何网络请求
- 不修改用户环境、不写真实 state.db / telemetry.db

## 性能验收（本地手动，CI 不执行）

```bash
python tests/performance_verify.py --seconds 600 --pages-seconds 60
```

模拟 1 REST + 1 WebSocket 客户端连续 10 分钟 + 3 页面并发，
输出 snapshot 请求数 / 实际 collector 次数 / telemetry 写入周期 / DB rows 增量。
