# Cursor 集中复审结果归档

## 归档来源与证据边界

- 来源：Cursor 桌面端既有会话 `Hermes 0222 native session review`，工作区 `hermes-0222-native-session-preparation-20261017`。
- UI 显示最终消息：2026-10-17 17:50，Worked for 10m 19s；会话状态 Completed；模型 Grok 4.7 High Fast，Ask 模式。
- 取回日期：2026-10-18，Codex 通过该会话可访问性界面读取并归档。
- 下文为完整最终回复的可见正文转录，保留内容、分层、代码名和数值，Markdown 排版由归档方重建；不是 Cursor 原生导出文件，不声明与原生消息字节相等。没有把其他会话的报告混入本件。
- 本轮仅核对当前清单与冻结自身 SHA256，均仍与送审值一致；没有重跑 349 项测试，也没有重新逐项核验 160 项文件。下文“逐项相符”等是 Cursor 本次复审陈述，不冒充本轮 Codex 的独立重算。
- 旧 `CURSOR_HANDOFF_RECEIPT.json` 保留送审时历史状态，不倒改为当时已收报告。

---

本包没有源码可证明的安全阻断，也没有可从冻结源码推出的必然运行失败。可以请求这一具体单次范围的新授权。这不是原生安装、宿主 HTTP/WS、内存接受或公开发布通过。

## 结论

离线准备链是闭合的：控制器只在新授权通过后派发；workflow 固定 SDK `d923a5eb487a17c0a68801bba9ef0f56c81040a8` 与已发布 HUD `004c18a7bc54e1297833b2ceb1aec11417bfdfe9`；入口拒绝旧 schema、旧 scope 和旧冻结；安装后由 `Backend.handoff` 独占写入链接清单，再经真实 `prepare` 与子端消费前、启动前后复核。工具包链接仍只是元数据，没有变成内容读取根。聚合要同时看到三次安装的整数 exit 0、子记录、实际进程 exit 0、邮箱关闭、HTTP 与 WS，缺任一项都不能通过。固定字段仍是内存未接受、公开发布阻断、`vm_teardown_verified=false`。

门控文件现在不存在，是当前阶段，不另计为代码缺陷。九组 349 项是离线回执，不代表原生安装或 HTTP/WS 已经通过。

## 输入核对

| 对象 | 结果 |
| --- | --- |
| 清单 SHA256 | `efa6d6a1ece148ce8ea4d71c03c621ca820542a99048c37b2f702c723e5040dd`，160 项，3,904,268 字节，逐项字节与 SHA256 均相符 |
| 运行冻结 | 33 个键，`hermes_0222_remote_freeze_v1`，SHA256 `1ffccee10de9fadbdfc6c80c6993a576b9fc8736ccddb5b012b3874391107695` |
| 入口要求集 | `remote_entry.py` 的 `required` 与冻结键集相同，并包含 `runtime_aliases.py` |
| 18 个公开源 Git blob | 与 `PUBLIC_SOURCES.json` 全部一致 |
| uv 0.12.3 `virtualenv.rs` blob | `c1422b426bce0266a16c21dbe10449582e8f55a4` |
| 35 个本地发布副本 | 与 `PUBLISH_LAYOUT.json` 逐字节相同；`contains_authorization=false`，`pushed=false` |
| 终轮回执 | 30+30+9+131+50+36+23+28+12=349，均为 exit 0、0 skipped |

未执行 `verify_package.py`，也未导入被审模块。回执只作已记录的离线结果，不重新执行。

## 链路

控制器 → workflow → 入口。`remote_controller.py` 与基线字节相同。它先校验当前冻结，再要求 `hermes_0222_remote_authorization_v1` 与 scope `one_remote_hermes_0222_install1800_host300_no_retry_no_risk_acceptance_v1`。workflow 只接受 `workflow_dispatch`、`run_attempt == 1`、Intel macOS 15，并检出上述两个固定提交。`remote_entry.py` 在授权、冻结和平台门通过前不会调用 `Backend`。

安装与交接。`remote_pm_entry.py` 跑官方 PM；宿主走 `official_entry.py`。`remote_backend.py` 第 191–205 行在 `prepare` 之前用 `write_new`（`O_EXCL|O_NOFOLLOW`）把 `tool/installed-aliases.json` 写一次。`install_completion.py` 第 22–27 行重新 `collect`，逐字节比对规范 JSON，并调用 `verify_aliases`。`test_complete_install_files.py` 第 124–140 行调用的是这个 `Backend.handoff`，解释器与依赖仍是夹具。

子端与 HTTP/WS。`child_runtime.py` 第 197–200 行在消费、守卫和 SDK 导入前校验链接。第 219 行的 `verify_sources` 在守卫安装后于启动前和结束后再次执行。第 151–179 行不只重算 JSON：它重读链接原文，并 `lstat` 终点。`host_session.py` 只有 HTTP 与 WS 都是 `EXPECTED_RESPONSE_ONLY` 才继续；`sealed_session.py` 还要求终端封签与实际进程 exit 0。邮箱未关闭会把结果打成失败。

退出与聚合。`child_execution.py` 第 35 行只有无错误、描述符关闭成功且子记录为 `ENTRY_RETURNED_ZERO_NOT_ACCEPTANCE` 才返回 0。`remote_contract.py` 第 72–102 行要求三次安装命令都是整数 0、子封签完整、宿主结果为 `SEALED_SHORT_SESSION_RECORD_ONLY`、通道已关、清理整数 exit 0，且 HTTP 与 WS 同时成立。`type(...) is int` 拒绝布尔值。失败时 `http_verified` 与 `ws_verified` 都为假。聚合不带路径、异常、token、DB 或 snapshot。

## 六项重点

1. 旧 B1。旧采集只接受指向已绑定映像的直接绝对链接，工具树里的符号链接会在 `installed_closure.py` 被拒绝。现在第 102–114 行只 `readlink`，不打开目标，也不走入链接目录。`runtime_aliases.py` 第 22–58 行把展开限制在同一 `home/.hermes/tools/<包>` 内，最多 32 跳、512 个链接；绝对目标、`..` 越出包、环、悬空和“链接落在其目录终点里面”都会拒绝。终点必须已经是本次捕获的普通文件或物理目录。`ExactPolicy` 要求请求路径与规范路径相同，链接名不在 `BoundFiles` 里，因此链接路径不是读取根。`audit_adapter.py` 只拦截 `open`；`lstat`/`readlink` 只复核元数据。

2. uv 0.12.3 三名称。`upstream/uv-virtualenv.rs` 第 265–277 行是：`python` 指向已选解释器，`python3` 与 `python3.14` 指向相对名 `python`。`runtime_aliases.py` 第 92–105 行只允许这三个 `venv/bin` 名字；原文只能是这三个名字之一，或精确的 `root + '/' + interpreter`。图必须在三步内终止于该映像。悬空、缺节点、自环、其它环境文件名、相对越界和 v1 schema 都会拒绝。`pm_handoff.py` 第 174–180 行还要求 `pyvenv.cfg` 的 `uv = 0.12.3`、`version_info = 3.14.7`，且 `home` 等于该映像的父目录。`host_plan` 第 220–221 行启动的是这块映像，不是 venv 里的链接名。

3. 清单绑定。schema 为 `hermes_0222_installed_aliases_v2`。清单进入文件摘要；`prepare` 与子端都按当前链接原文重算，不信任单独保存的 JSON。`runtime_aliases.py` 在子端导入时不打开安装树，与随后的精确 `open` 和 FD 合同不冲突。

4. 0.22.2 与旧授权。workflow 与 `HOST_COMMIT` 已从 `e06df9c2...` 改为 `d923a5eb...`。`LOCK_SHA`、`PROJECT_SHA` 与当前 `uv.lock`、`pyproject.toml` 一致。锁里 psutil 7.2.2 是非 Android 的 registry 行，8.0.0 Git 行只标 Android；控制器 wheel `ed0cace9...` 与 `f7a866fb...` 都在锁内。npm 锁仍要求 registry.npmjs.org 与 sha512 integrity。PM 工具版本仍是 Python `3.14.7+20260901`、Node 26.7.0、npm 12.0.2、uv 0.12.3。旧冻结是 `hermes_022_remote_freeze_v1`、32 文件、SHA256 `71083c3d...`，对不上新入口。授权、接受、子 scope 和 claim 都改为 `0222` 全等匹配。

5. 身份、信号、清理与门槛。`owned_process.py` 的 `start/check/close/poll/send`、`install_parent.py` 的 `sample/cleanup/bind/inspect_live/poll`、`child_guard.py` 的 `check/extra`、`runtime_fence.py` 的 `writable/validate_paths`、`pm_handoff.py` 的 `_read/verify_all`，AST 与基线相同。`child_guard.checkpoint` 只把 schema 从 `hermes_022_full_guard_v1` 改为 `hermes_0222_full_guard_v1`。8192 文件、1 GiB、单文件、FD、16 映像与 128 路径上限没有放宽。

6. 35 个副本。布局含 33 个运行文件、`runtime_aliases.py`、`REMOTE_FREEZE.json`，以及 workflow 的第二份 `.github/workflows/hermes-022-isolated.yml`。复审请求、合同和授权文件不在其中。

## 阻断

没有。没有发现可把链接元数据变成任意读取根的路径，也没有发现旧授权仍能通过新入口的路径。聚合不能靠单独的 API 确认、单独的安装成功或未关闭的邮箱通过。

## 非阻断

这些都留在真实运行里证明，不拆开复审：

- 链接与源复核是时间点观察，没有命名空间锁。`verify` 用路径字符串做 `lstat`/`readlink`，祖先必须当时是真实目录。
- 安装原生后代不在 Python audit 的完整约束内；树监控只覆盖登记后代；映像摘要是采样绑定。同步 IO 不能证明硬截止。清理失败不算成功，未知身份不会被盲目发信号。
- `vm_teardown_verified` 保持假。依赖体积、`.pth`、RECORD 和真实导入闭包不能从合成夹具推出。`validate_pth` 仍拒绝 uv 固定 shim 以外的可执行 `.pth`。
- 包根那一层（正好四个路径分量）的符号链接仍拒绝；包内链接才进入图。venv `bin` 里除三个规定名字以外的链接、site-packages 链接和 `nlink != 1` 仍拒绝。`python3.14t` 只有自由线程构建才会出现，固定的 install-only 制品名不是该构建。
- `find_base_python` 的函数体不在冻结的 `virtualenv.rs` 里。绝对链接必须正好是 `.../bin/python3.14`。PM 的 `main_bin_rel` 是这个名字，对不上时交接拒绝，而不是放行。
- `pyproject.toml` 的 `version` 字段是 `0.0.0`；本包绑定的是提交、锁哈希和 uv 0.12.3，不读取该版本字符串。
- 文件组回执的 open 计数来自新建的 owned 夹具（链接组 forbidden 为 0）。模型组的进程、网络、sqlite、ctypes 尝试为 0。`RED_*` 与 `history/pre-uv-fix` 不是当前绑定。
- 控制器在 GitHub API 接受派发时返回 0，状态是 `API_ACKNOWLEDGED_NOT_EXECUTION_PASS`，不是宿主通过。

## 实际读到的范围

全清单 160 个路径只做了哈希。完整读过的接线文件包括合同、复审请求、清单、冻结、`UV_SOURCE.json`、发布布局、`runtime_aliases.py`、`installed_closure.py`、`remote_contract.py`、`remote_entry.py`、`remote_controller.py`、`remote_pm_entry.py`、`remote_backend.py`、`remote_install.py`、`remote_files.py`、`install_completion.py`、`official_entry.py`、`child_runtime.py`、`child_guard.py`、`child_protocol.py`、`child_execution.py`、`guard_stack.py`、`audit_adapter.py`、`sealed_session.py`、`host_session.py`、`server_bridge.py`、`web_preparation.py`、`PUBLIC_SOURCES.json`、`PREPARATION_EVENTS.json`，以及旧包里的 B1 摄入记录。

分段读过 `pm_handoff.py`、`uv-virtualenv.rs` 的别名与 `pyvenv.cfg` 段、PM 的 venv 创建与工具复制段、`pyproject.toml` 的 uv 段，以及锁里的 psutil/websockets 行。`main.py`、`web_server.py`、完整 `uv.lock` 和 `package-lock.json` 只做了哈希、blob 和定点检索。基线差异用清单内旧路径直接比较；`SOURCE_DIFF.patch` 的文件集合与这些差异一致。没有列目录、没有追清单外旧链、没有改文件、没有跑 Git 或网络。

---

## 归档方注记（不属于 Cursor 原回复）

“六项重点”第 6 项原文将 `runtime_aliases.py` 在 33 个运行文件之外再次点名；这只是原文表述，不据此将总件数改算成 36。冻结的 33 件本已包含该文件；35 个发布副本的既有定义为运行件 33 + 冻结 1 + workflow 第二副本 1。本轮不为文案开启新的复审循环。

本件只归档静态复审结论，不创建授权、验收接受件、permit、claim 或派发，不提交、推送、安装、启动、部署或发布。历史内存风险仍为 `WARN_NOT_ACCEPTED`，公开发布仍为 `BLOCK`。
