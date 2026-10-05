# 私有短启动诊断 v2：仅离线准备

状态：NOT AUTHORIZED / NOT DISPATCHED / NOT NATIVE TESTED。旧工具、失败、授权、claim、回执均保留；不是 Hermes HUD 产品版本，不改版本/main，不接受内存风险。

## 事实和未知

run 37292689096 安全聚合记录 0.739952041 秒、identity 首因、HTTP/WS 均 0、child/transport 为空、cleanup 身份未匹配且 alive/exit_code 未知。入口 exit 2 不等于子进程 exit 2；三次历史失败不证明同一根因。旧 result/completion 未导出，不能独立重算原始封口；旧分析器 execution_failed 分支表明它接受了 FAIL 封口，不支持“没有 seal”的断言。历史根因 UNKNOWN。

## 接线和不变量

身份首条失败投影仅固定 site、pid/birth/cwd/argv/exe 五项相等性布尔或 null、原句柄当点 exit_code、固定检查异常枚举、birth_window。无实际 PID、路径、argv、出生时间、异常类型名或原文；首条锁存不覆盖。failure_stage 独立定位，旧 error 口径保留。

既有清理前身份检查只增加投影，不增加 inspect 次数或信号权限；close_owned 正文逐字不变。清理后对原 Popen 句柄额外 poll 一次，不重附加 PID、不 inspect/wait/发信号。handle_observation 不补写 cleanup.identity_matched 或 transport/cleanup.exit_code；零退出观察不能升级未知清理。

父端与分析器均要求成功诊断为空、原句柄最终观察为严格整数 0、原有完整身份/终局/HTTP/WS/源哈希/预算合同满足。非零退出不能 PASS；非法诊断不转导证据。backend/completion/freeze 为 v2，旧记录须旧分析器；新报告、新冻结与新授权绑定，不复用已消费许可。

本阶段不创建 acceptance/authorization/permit/claim，不启动原生 runner，不推送或给执行命令。

## 验证边界

继承 300 项模型回归，增加首因、异常分类、五字段差异、锁存、阶段定位、零信号/TERM 后不得 KILL、原句柄观察与 PASS/FAIL schema 负向测试。实际数/命令/cwd/exit/输入哈希见回执，不从命名推断执行。

psutil 仅预载与合成异常对象；Popen/身份/transport 为内存模型。安装 hook 后禁止 open、进程、网络、SQLite、信号；预载不覆盖，ctypes/内核隔离不保证。模型不证明真实 psutil/OS 管道/事件循环/CI。

同进程自报诊断不能重建 raw 或证明旧根因；只有未来另行授权运行可能补实证。HOST/HTTP/WS/CI NOT VERIFIED；MEMORY NOT CLOSED / WARN_NOT_ACCEPTED；PUBLIC RELEASE BLOCK。
