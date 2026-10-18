# Cursor 完整集中复审报告 — Hermes 0.22.2 sources 修正版

归档说明：本文件由 Codex 从 Cursor Agents 可见会话的完整最终回复转录，恢复标题、表格、代码与内联文件名的 Markdown 排版；不是 Cursor 原生文件导出，不是新一轮自审，不改变受审输入。来源会话为「Hermes 0.22.2 static review」，模式 Ask，界面模型标签 Grok 4.7 High Fast；界面显示回复时间 2026-10-18 18:03（Asia/Shanghai），Worked for 13m 59s。取回时间 2026-10-18T10:12:05Z。受审目录为本文件同目录。

受审清单：REVIEW_INPUT_MANIFEST.json，55,151 B，SHA-256 f076d455a87e334a2f7ec60fc1ad706ebef88bd42d3bf8346ffcffbb9fd343f8，184 项，4,768,094 B。报告正文起止对应 Cursor 最终回复从「无真实安全或正确性阻断」至「也不是内存风险接受或公开发布」。代码块保留可见代码内容，不将格式恢复声称为逐字节原生导出。

---

无真实安全或正确性阻断。离线准备与有限模型完整性成立，只到可以请求一份新的投影源原生范围为止。MEMORY 维持 WARN_NOT_ACCEPTED，公开状态维持 BLOCK。这次不授权原生，也不把准备结果当成 SDK 安装、HTTP/WS、CI 或 HUD 2.0 上线通过。

## 分层判定

| 层 | 判定 |
| --- | --- |
| 旧 checkout_files 对 8192 的计数拒绝 | 代码顺序独立成立。18605 与 1,848,170 字节是请求方执行记录。两者合在一起，才得到“若该记录为真，则全树清单在内容读取前被计数拒绝”。 |
| 历史 run 39113826866 的首次抛错点 | 仍是 UNKNOWN。547 字节导出不能反填。 |
| 3185 文件投影 | 目录内部闭合、字面 pathspec、读前精确匹配，独立成立。与公开全树逐行相等，按记录接收。 |
| sources 60 与 local Git 5 | 源码缝独立成立。463 的执行通过是 Codex 回执，本复审未重跑。 |
| 远端合同 v2 | 三键、接收前拒绝非法 FAIL、PASS 为 null、旧授权/范围/freeze 不能升级，由源码结构成立。 |
| 19 份关键文件与原门槛 | 逐字未动。8192、1GiB、4MiB、2MiB、512MiB、4096、内存门槛未提高。 |
| 35 项 freeze、37 份本地 payload、12 份 FINAL | 闭合。当前清单内没有新 grant、claim 或 acceptance。这不是缺件。 |

## 独立可算与按记录接收

独立重算：

- 清单自身 55,151 字节，SHA256 f076d455a87e334a2f7ec60fc1ad706ebef88bd42d3bf8346ffcffbb9fd343f8。184 条路径互异，声明总字节 4,768,094，逐项大小与 SHA256 全部相符。
- 当前 freeze 文件 3,328 字节，SHA256 f12dce30344c5b4c7902aa65fc36f09f0a415e1d7e0ceee9aafb1d1bf10d4e04，schema hermes_0222_remote_freeze_v2，35 个键与 remote_entry.frozen 的要求集合相同，并与工作区及 repository-payload/scripts/hermes_022/ 逐字相同。
- 旧 freeze 3,132 字节，1ffccee10de9fadbdfc6c80c6993a576b9fc8736ccddb5b012b3874391107695，v1，33 项。
- SDK_SOURCE_SELECTION.json 395,939 字节，SHA256 cfea0a9d3da0cd91ca961c01d9156a3d2047119a66204086fb99a10f9a5b098f。3,185 行，字节和 67,016,450，120 个 pathspec。
- 由目录本身算出的 ls-tree -z 尺寸是 274,637 字节。3,185 ≤ 8192，274,637 ≤ 4,194,304，67,016,450 ≤ 1GiB，单文件最大 1,430,925 字节，没有任何选中文件超过 2MiB。
- PROTECTED_BYTES.json 的 19 个文件与旧目录逐字相同。
- SOURCE_DIFF.patch 21,450 字节，SHA256 0485d6e8bf67d85ae7f16a10d4a020c58bf57bdfcb2c31b0da392acf6eebe9e7。在内存中应用到 11 个旧文件后，与当前文件逐字相同。
- 已归档的 18 个公开 blob：文件字节、Git blob SHA1、目录中的 blob 与字节数一致。uv-virtualenv.rs 的 blob c1422b426bce0266a16c21dbe10449582e8f55a4 与 UV_SOURCE.json 一致；该文件不在 SDK 目录内。
- 12 份 FINAL 回执的全部 input 哈希与当前文件一致，tests_run 之和为 463，failures、errors、skipped 都是 0。

按记录接收，本复审没有原始响应可以重算：

- PUBLIC_TREE_PROOF.json：公开元数据 5,174,151 字节，SHA256 750082fb1bc40d61de7978d721a819508048fb557fba91d8d5324e9013fa9097，全记录 19,838，blob 18,605，ls-tree -z blob 字节 1,848,170，重建 1,234 个树对象且与 commit tree 5a064077e8d1de9fc7a4b27efc04f0caa2cb06c0 相符。
- 这些数字内部自洽：19,838 − 18,605 = 1,233 个非 blob 记录，加上根树正好是 1,234。按这份记录，公开响应里没有 gitlink。生成器哈希等于清单内的 read_public_selection.py。原始响应未归档。
- 18,605 − 3,185 = 15,420 只在接受上述 blob 计数时成立。
- 历史 547 字节聚合、FOLLOWUP 中的 run 元数据、以及“未推送”都是包内声明。没有做 Git 或网络核对。

## 旧计数拒绝与历史抛错点

旧 checkout_files 先取全树，再检查条数，然后才读工作文件：

旧目录 remote_backend.py Ln 47–56：

```python
records = git(['ls-tree','-rz','--full-tree',commit]).split(b'\0');objects = {};total = 0
need(records[-1]==b'' and 0<len(records)-1<=8192)
# ... metadata parse ...
else:raw = read(path,512*1024**2)
```

git() 同时拒绝超过 4MiB 的标准输出。记录中的 1,848,170 字节低于 4MiB，18,605 高于 8192。因此若这份 ls-tree -rz 记录为真，触发的是计数守卫，而且发生在任何选中文件的内容读取之前。

历史 analysis.json 只有 547 字节，SHA256 6d6cba42fc0839cd2158591c64eb45f8b274ebeaf88353e081f646bd792ec489。它是 v1，result=FAIL，stage=sources，没有 source_diagnostic，没有 site，也没有异常文本。FOLLOWUP 自己写的根因是 UNKNOWN_SAFE_AGGREGATE_HAS_NO_SUBSTAGE_OR_EXCEPTION_DETAIL。sources 在到达 ls-tree 之前还有 root、claim、配置和 rev-parse。这份导出不能证明历史第一次抛错就是第 48 行。

包内另外两个 18605 是合成量，不能代替公开树：test_sources.py 的 FakeGit 直接拼出 18605 条记录；test_git_format.py 用 18,600 个合成 blob 加 5 个选中路径造了一个本地 bare 仓。

## 投影与读前闭合

HOST_COMMIT 是 d923a5eb487a17c0a68801bba9ef0f56c81040a8，与目录 commit、workflow 的 sdk checkout ref 相同。HUD commit 004c18a7bc54e1297833b2ceb1aec11417bfdfe9 与 workflow 的 hud-source ref 相同。

120 个 pathspec 由三部分组成，没有第四种：

- 18 个目录根：acp_adapter、agent、tools、hermes_cli、gateway、tui_gateway、cron、plugins、providers、hermes_platform、pm、scripts、web、apps/shared、assets、skills、locales、native。
- 97 个仓库根级精确文件。
- 5 个精确工作区清单：apps/bootstrap-installer/package.json、apps/desktop/package.json、tests-js/package.json、ui-tui/package.json、ui-tui/packages/hermes-ink/package.json。

18 + 97 + 5 = 120。正则只允许字母、数字、_、.、- 和斜杠。没有 *?[]{}:!，没有 :(glob)，也没有 ..。pathspec 放在 -- 之后。source_selection.selected 与准备用的 read_public_selection.selected 在 AST 上相同；后者不在 35 项 freeze 里，运行时不会调用它。

目录根会让 Git 列出该目录下的全部 blob，这是投影本身，不是通配回退。多出的、缺少的或 blob 不同的记录在 listing() 里与钉死的 path/mode/blob 集合比较，失败即拒绝。SDK 槽位始终传入这份目录；没有失败后退回全仓的分支。5 个精确文件 pathspec 不会把 apps/desktop、ui-tui 或 tests-js 的其余树带进来。

当前目录 remote_backend.py Ln 50–60：

```python
args = ['ls-tree','-rz','--full-tree',commit]
if selected is not None:args += ['--',*selected['pathspecs']]
records = source_listing(git(args),selected);objects = {};total = 0
sizes = {r['path']:r['bytes'] for r in selected['files']} if selected is not None else None
for name,mode,h in records:
    path = checkout+'/'+name
    # content read only after listing returns
```

listing() 在返回前执行 4MiB、8192、blob、以及与目录的精确相等。内容循环才调用 read()，并同时核对目录字节数和 blob <size>\0<content> 的 SHA1。产品槽位仍传 selection=None，继续受 8192 约束；本包没有 HUD 全树计数。

已归档 pyproject.toml 的 setuptools include 根是 acp_adapter、agent、cron、gateway、hermes_cli、hermes_platform、plugins、pm、providers、tools、tui_gateway，全部落在上述目录根内。package-data 模式也落在这些根里。已归档 package-lock.json 里，web 的依赖是 @hermes/shared: file:../apps/shared；apps/shared 整棵在投影内。ui-tui 另有一条指向 shared 的链接，并有 @hermes/ink: file:./packages/hermes-ink。ink 与 desktop 只保留了 package.json。当前 web 计划只对 workspace web 做 npm ci 和 web.mjs，并带 --ignore-scripts。

目录模式只有 100644 3,128 个和 100755 57 个。必需文件都在，18 个根都非空，路径已排序，casefold 无冲突，relative() 拒绝绝对路径和 ..。有一个 0 字节文件 tui_gateway/__init__.py，模式允许。

运行时不会再次列出全树，否则又会撞上 8192。因此“公开树里还有一个未写入目录的根级文件”这件事，要靠 freeze 中的目录哈希加上上述树证明，而不是靠原生 checkout 再扫描全树。

## 诊断 v2

sources 失败只产生 version、site、kind。site 16 个，kind 只有 refused、io、internal。未知 site 收成 phase。异常文本、路径和参数不进入记录。

aggregate() 在返回前要求：stage 为 sources 时诊断必须通过 valid_diagnostic，其他 stage 必须是 null。validate_aggregate() 在 export_safe() 写文件前再查一次。PASS 还要求 stage 为 aggregate、诊断为 null，以及安装、HTTP、WS、host exit、child seal、source 标志全部为真。旧聚合少了 source_diagnostic 和 source_projection，schema 仍是 v1，键集合对不上。旧授权 schema 与旧 scope 在 authorize() 被 v2 精确匹配拒绝。子授权、子 acceptance、parent claim 仍是 v1；child_bindings 不在函数差异里。

聚合模板里的 memory=WARN_NOT_ACCEPTED、public_release=BLOCK、retry=false 不是可变字段。source_projection 固定为 PINNED_INSTALL_HOST_WEB_INPUTS_NOT_FULL_REPOSITORY。

## 未改的安全边界

19 份逐字文件覆盖进程身份、信号、清理、child/host 执行、安装清单和 staging。owned_process.py 仍只接受 SIGTERM 与 SIGKILL。installed_closure.py 仍是 MAX_FILES=8192、MAX_BYTES=1GiB，文本 2MiB、二进制 512MiB。remote_files.py 的默认读取上限仍是 2MiB，行数上限 8192。

remote_backend.source_check 不在函数差异中，仍要求可用内存至少 3072*1024**2、swap used 至多 512*1024**2。新的 checkout 仍把 Git 输出限制在 4MiB，单文件读取上限 512MiB，累计 1GiB。目录条数上限是新的 4096，当前 3,185 低于它；这不是把 8192 提高了。workflow 2,171 字节，SHA256 4b04def7ca3dd9fb2eccdddab7b9f49afa37bebd197b238a56490d993ddc79f3，与旧文件、两份 payload 副本相同。plugin_handoff.py 仍要求 hermes-hud 1.2.1。

## 测试与 463 绑定

分组 30+30+9+131+50+36+23+28+12+49+60+5 = 463。前九组 349，加 artifact 49、sources 60、local Git 5。

sources 组静态方法 27+6+13，再加 14 个模块级动态否定例，等于回执 60。它调用真实 Backend.sources 和 execute，文件是合成的，subprocess.run 被 FakeGit 替换；审计钩子拒绝真实 subprocess、socket、sqlite 和 ctypes。未选中的 tests/never-open.py 被断言不进入读取列表。这不是 SDK 安装。

local Git 组的 5 个方法写在函数内部的类里。成功路径展开为 13 个本地 Git 进程：init、hash-object、6 次 mktree、--version、4 次 ls-tree。回执记录 allowed_local_git_processes=13，版本字符串是 git version 2.54.0 (Apple Git-157)。同文件里的 network_calls 和 sdk_processes 是字面量 0，不是审计计数。这里有 13 个明确的本地 Git 进程。准备阶段读取公开树时有网络；sources 离线 harness 才有网络拒绝钩子。

其余 FINAL 含类内动态用例。child 可见静态方法 90、回执 131；remote 可见静态方法 24、回执 50。本复审没有执行加载器，所以不用静态方法数否定这些回执，也不把回执当成自己重跑的结果。它们的 input 哈希已经与当前文件逐项对齐。

FIRST_SOURCES_RECEIPT.json 与 FIRST_REMOTE_RECEIPT.json 仍钉着旧的 source_selection.py、remote_backend.py，sources 的 FIRST 还钉着旧 test_sources.py。当前绑定只使用 12 份 FINAL。exploratory 回执不进入 463。

## freeze、payload 与授权

35 个运行输入含新的 source_selection.py 与 SDK_SOURCE_SELECTION.json。37 份本地 payload 是这 35 个文件、一份 REMOTE_FREEZE.json，以及 .github/workflows/hermes-022-isolated.yml。PUBLISH_LAYOUT.json 写明 contains_authorization=false、pushed=false。清单里的授权与 acceptance 只有旧目录中的 v1 文件，scope 仍是旧字符串，grant 25b96779c554420d945d8f647ab14320。新 scope one_remote_hermes_0222_projected_sources_v2_install1800_host300_no_retry_no_risk_acceptance 只出现在新合同里，没有配套的新授权文件。

## 非阻断与证据上限

集中登记一次：

- 公开全树原始元数据未归档。全树过滤结果等于这份目录，是 PUBLIC_TREE_PROOF.json 的执行记录。
- 历史首次抛错点未知。合成 18605 只证明守卫和 Git 对象格式。
- 未改 workflow 的 actions/checkout 仍会把完整 sdk-source 物化到 runner。控制器只在清单闭合后读取选中文件。
- 产品树仍走无 pathspec 的 8192 路径。本包没有 HUD 全树条数。
- ui-tui、desktop、hermes-ink 只保留清单，不保留实现。真实 npm 闭包未跑。
- local Git 的网络 0 与 SDK 进程 0 是源码字面量。Git 版本是本机 Apple Git，不是 CI 证明。
- test_git_format.py 没有 sources 组那种审计钩子。
- 非 pm_handoff.Refused、artifact_stage.Refused、remote_contract.Refused 的异常在 sources 中记为 internal，仍是三键枚举，不带原始文本。
- source_site=complete 设在 sources() 最后一行，正常成功不会产出诊断。
- 投影含公开根级点文件，包括 .env.example 和 .envrc。这是钉死的公开 blob，不是读取本机 HOME 或凭据。
- blob 身份是 SHA1，与这个 40 位 commit 一致。
- execute 仍吞掉 BaseException；sources 失败被收成固定诊断。
- SOURCE_COMPARISON.json 的 shared 有 42 项，没有列入已变化的 REMOTE_FREEZE.json。freeze 由自身哈希和 payload 钉住。
- FOLLOWUP 提到的 transport、job 和 fetch 文件不在本清单，未读。
- 未列目录，因此“工作区绝对没有未列入清单的文件”不是一次文件系统普查。
- 真实安装、依赖闭包、CI Git、installer 子孙的 OS sandbox、同步 IO 的硬截止、VM teardown、浏览器和长期内存接受，都没有在这次复审里变成通过。
- 旧 payload 与 seal 未随 547 字节聚合导出，也不能从该文件重算。

## 实际做了、没做、边界

做了：只读清单内绝对路径；独立哈希；JSON 与 TOML 解析；AST 比较；内存应用补丁；目录规则、pathspec、blob 与已归档锁文件的闭合；sources 与 Git fixture 的源码计数；FINAL 输入绑定。

没做：运行或导入任何被审脚本、测试、SDK、安装器、host、verifier 和公开元数据读取器；Git、网络、原生进程、资源探针；读取 DB、HOME、config、凭据或 Actions 日志；列目录、递归、glob、按引用扩链；修改文件；创建报告、授权或命令。

边界保持为：HUD 1.2.1 是固定输入。这次复审的最高结论是离线准备完成，可以据此请求新的投影源 v2 范围。它不是原生兼容通过，也不是内存风险接受或公开发布。
