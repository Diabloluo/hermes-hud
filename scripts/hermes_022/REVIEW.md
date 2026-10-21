# Cursor 完整集中复审报告 — Hermes 0.22.2 checkout 修正版 v3

归档说明：由 Codex 从 Cursor Agents「Hermes SDK static review」最终回复的可见界面及 Copy message 文本取回并转录，恢复 Markdown 表格和代码块排版；不是 Cursor 原生文件导出，不宣称与原生导出逐字节相同。Ask 模式，界面模型标签 Grok 4.7 High Fast；界面显示完成时间 2026-10-18 19:15（Asia/Shanghai），Worked for 16m 44s。复制内容仅在未发送的临时输入框中展开读取，随后已清空，未发送额外消息。

受审清单：REVIEW_INPUT_MANIFEST.json，60,561 B / SHA-256 61d9fdd299a2b20bf93d3a0ba67934fe059a91e72750deed23c8e94be9c4a04d；202 项，5,305,080 B。以下保留报告全部结论、限制、表格与代码摘录，代码出处行号保留。原回复表格首行的“14,421 等待”亦原样保留，未静默改写；该行后半部明确的实际旧/新大小为 15,402 → 16,413 B，另由 SOURCE_COMPARISON.json 与归档接收记录核对，不以残留文字作为数值依据。

---

阻断：无。最高结论只到离线准备完成，可以另行请求一个新的具体运行范围。历史 run `39118974049` 的最早真实条件仍是 **UNKNOWN**。合成的 Git 所有者拒绝在其声明的测试钩子内有代码与当前回执支持，不能外推成远端归因。

**MEMORY：WARN_NOT_ACCEPTED。PUBLIC：BLOCK。** 本会话没有创建授权、claim、推送或调度。

## 分层结论

当前候选是 Hermes 0.22.2 `sdk_checkout` 集中修正版 v3。冻结包可以进入“请求一次新的具体运行”这一步；该请求现在还不存在。

精确的命令级 `safe.directory=<canonical checkout>` 没有扩到 `*`、父目录或全局 Git 配置。它只取消这一个已经选定的目录上的 Git 所有者拒绝。这不是 UID 证明，也不是操作系统沙箱。固定 HEAD、清单元数据、工作文件的 nofollow、stamp、nlink、字节长度和 Git blob SHA1 都还在。

旧聚合仍是 v2、`version: 1`、`site: sdk_checkout`、`kind: refused`。新代码在原有效时刻拒绝这份旧授权和旧聚合，没有回填旧 FAIL。`kind: refused` 只表示某次 `need()` 拒绝，不能区分所有者检查、HEAD、清单或内容哈希。因此合成复现保持 **PLAUSIBLE**，不是实证。

## 独立核对

清单自身 **60,561 B**，SHA256 `61d9fdd299a2b20bf93d3a0ba67934fe059a91e72750deed23c8e94be9c4a04d`。202 项、**5,305,080 B**，逐项字节与 SHA256 均为 0 漂移，无重复路径，路径都在清单给出的三个目录内。

`PACKAGE_READBACK.json` 的 `files` 是其中 **199** 项，这 199 项也是 0 漂移。另外 3 项不在该字典里，但已按清单单独核对通过：回读文件自身、`FINAL_OFFLINE_SUMMARY.json`、`WORKTREE_PROBE_RECEIPT.json`。

`SOURCE_DIFF.patch` 为 17,790 B，SHA256 `37c7aa3e4fcb9023d029eb283e105848d1da3a1aeb1a4688758d7d6086f0ada2`。6 个文件均从 sources v2 基线在内存中重放，并与当前文件逐字节相同：

| 文件 | 结果 |
|---|---|
| `remote_backend.py` | 14,421 等待，实际旧文件 15,402 B → 16,413 B，等于当前 `d54ff52d…` |
| `remote_contract.py` | 8,373 → 8,371，相等 |
| `remote_entry.py` | 4,042 → 4,042，相等 |
| `source_selection.py` | 4,633 → 5,184，相等 |
| `test_remote.py` | 13,032 → 13,032，相等 |
| `test_sources.py` | 17,648 → 17,939，相等 |

旧 `remote_backend.py` 的 Git 调用没有 `safe.directory`。`SOURCE_COMPARISON.json` 的 47 项共享记录与磁盘一致；`new_runtime_files` 为空，新增测试只有 `test_checkout_git.py`。

当前包 52 个 Python 文件 AST 解析全部通过。解析时没有导入这些模块。

冻结文件 `REMOTE_FREEZE.json` 为 3,328 B，SHA256 `a66ff19a664d001ff48ed50ff4057fa6d75e03b58e77dc6bddbe0c31c2decb27`，schema 为 `hermes_0222_remote_freeze_v3`。内部 35 个哈希与磁盘一致，且与 `remote_entry.py` 的必需集合相同。相对 sources v2：**31 个运行文件逐字节未变**，改变的是 `remote_backend.py`、`remote_contract.py`、`remote_entry.py`、`source_selection.py`。`install_parent.py` 仍是 `bf26879d…`。

37 份 `repository-payload` 与根上对应文件逐字节相同，包括两份 2,171 B 的 workflow。workflow SHA256 仍是 `4b04def7ca3dd9fb2eccdddab7b9f49afa37bebd197b238a56490d993ddc79f3`。

`SDK_SOURCE_SELECTION.json` 为 395,939 B，SHA256 `cfea0a9d3da0cd91ca961c01d9156a3d2047119a66204086fb99a10f9a5b098f`。独立计数为 **3,185** 个文件、**67,016,450** B、**120** 个 pathspec，路径已排序且唯一。模式只有 `100644` 3,128 个和 `100755` 57 个。commit `d923a5eb487a17c0a68801bba9ef0f56c81040a8` 等于 `HOST_COMMIT`，也等于 workflow 的 `sdk-source` ref。`HUD_COMMIT` `004c18a7bc54e1297833b2ceb1aec11417bfdfe9` 等于 `hud-source` ref。`uv.lock`、`pyproject.toml`、`released-v1.2.1-index.js`、`hermes_platform/host/runtime.py` 的固定 SHA256 与清单文件一致。

历史聚合 `analysis.json` 为 **693 B**，SHA256 `825e2fe3bf4d74da3579af407725ba4d2ef927f1d2d14f3d24aee54036f8117e`。内容仍是 schema v2、`result: FAIL`、`stage: sources`、`grant: 7a152c67c6ad4c34becbc852baaaf024`、诊断 `{version:1, site:sdk_checkout, kind:refused}`。旧授权与旧 acceptance 仍是 v2，绑定 head `6cab12bb409e1af6574db7568c951d3b85392a98` 和旧 freeze `f12dce30…`。当前目录没有新的授权或 claim。

## 回执计数

13 份当前 FINAL 均为 failures 0、errors 0、skipped 0、exit 0。合计 **516 = 463 + 53**。

| 回执 | 测试 |
|---|---|
| FINAL_ALIAS / FINAL_INVENTORY | 30 + 30 |
| FINAL_FULL_FILE_CHAIN | 9 |
| FINAL_CHILD | 131 |
| FINAL_REMOTE | 50 |
| FINAL_PARENT | 36 |
| FINAL_COMPLETION_MODEL | 23 |
| FINAL_SOURCE | 28 |
| FINAL_REMOTE_FILES | 12 |
| FINAL_ARTIFACT | 49 |
| FINAL_SOURCES | 60 |
| FINAL_GIT_FORMAT | 5 |
| FINAL_CHECKOUT_GIT | 53 |

`FINAL_GIT_FORMAT_RECEIPT.json` 记录 13 个本地 Git 进程。`FINAL_CHECKOUT_GIT_RECEIPT.json` 记录 `git_processes: 92`、`forbidden: 0`、`outside_open: 0`、`pending: 0`、事件循环已关闭。两者合计 **105**。这是这两个最终组的记录，不是整轮进程总数。

92 与测试结构的静态分解一致：16 个 Checkout 用例各 4 次建仓调用，共 64；其余成功、失败和产品仓调用合计 28。格式组是 9 次对象准备加 4 次 `ls-tree`。这是算术核对，不是本轮重新启动的 Git。

53 的结构是 16 个真实 Git/checkout 用例，加 3 个固定诊断用例，再加 17×2 个 schema 用例。回执中的 unittest 输出列出这些用例且全部为 ok。

`FINAL_REMOTE` 与 `FINAL_REMOTE_FILES` 用文件名作输入键。其中改变过的 `remote_backend.py`、`remote_contract.py`、`remote_entry.py`、`source_selection.py`、`test_remote.py` 绑定的是当前新哈希，不是 v2 旧哈希。`FINAL_CHECKOUT_GIT` 的绝对路径输入与磁盘一致；它同时绑定当前候选 `d54ff52d…` 和基线 `02b9d0c9…`，后者只用于旧实现的拒绝对照。

以下记录不是当前通过结果：

- `FIRST_HARNESS_FAILURE.json`：exit 1，`/dev/null` 被拒绝，初始夹具清理 UNKNOWN。
- `SECOND_GIT_HARNESS_RECEIPT.json`：53 项中 52 个错误，exit 1，Git 计数 88。
- `THIRD_GIT_HARNESS_RECEIPT.json`：17 个错误，exit 1，Git 计数 88。
- `FOURTH_GIT_HARNESS_RECEIPT.json`：1 个错误，exit 1，Git 计数 88。

`PREPARATION_EVENTS.json` 对首次失败、52/17/1、复制时去掉的末尾空行，以及随后恢复的 `install_parent.py`，有集中记录。

## 精确 Git 信任例外

旧调用是绝对路径 `/usr/bin/git`，参数为 `-C <checkout>`，环境就是传入的安装环境：

旧目录 remote_backend.py Ln 43–46：

```python
def git(args):
    r=subprocess.run(['/usr/bin/git','-C',checkout,*args],env=env,stdin=subprocess.DEVNULL,
          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=30,check=False)
    need(r.returncode==0 and len(r.stdout)<=4*1024**2);return r.stdout
```

新调用先要求 checkout 已是 canonical 路径，再只给这两条只读命令加一个命令级配置：

当前目录 remote_backend.py Ln 42–59：

```python
def mark(code):
    need(code in CHECKS)
    if checkpoint is not None:checkpoint(code)
mark('path');need(os.path.realpath(checkout)==checkout and len(commit)==40)
git_env={**env,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null',
         'GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0',
         'GIT_NO_REPLACE_OBJECTS':'1','GIT_NO_LAZY_FETCH':'1'}
def git(args,label):
    mark(label+'_run')
    r=subprocess.run(['/usr/bin/git','-C',checkout,'-c','safe.directory='+checkout,*args],env=git_env,stdin=subprocess.DEVNULL,
          stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=30,check=False)
    mark(label+'_result');need(r.returncode==0)
    mark(label+'_size');need(len(r.stdout)<=4*1024**2);return r.stdout
head=git(['rev-parse','HEAD'],'head')
mark('head_binding');need(head.decode().strip()==commit)
```

生产调用点只把这个例外用在 `workspace/sdk-source` 与 `workspace/hud-source`：

当前目录 remote_backend.py Ln 119–122：

```python
for slot,checkout,commit in (('sdk','sdk-source',HOST_COMMIT),('product','hud-source',HUD_COMMIT)):
    self.source_site=slot+'_checkout';self.remaining()
    files=checkout_files(self.workspace+'/'+checkout,commit,env,selection=selection if slot=='sdk' else None,
            checkpoint=lambda check:setattr(self,'source_site',slot+'_checkout_'+check))
```

这里的 `env` 来自封闭的安装环境，不是 `os.environ`：

official_entry.py Ln 34–44：

```python
def environment(root, role, token=None):
    p=layout(root);need(role in ("install","host"))
    env={"HOME":p["home"],"HERMES_HOME":p["hermes_home"],"TMPDIR":p["tmp"],
         "PATH":"/usr/bin:/bin:/usr/sbin:/sbin","LANG":"en_US.UTF-8","LC_CTYPE":"en_US.UTF-8",
         "TZ":"UTC","PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1",
         "XDG_CACHE_HOME":p["home"]+"/.cache","UV_CACHE_DIR":p["hermes_home"]+"/cache/uv"}
```

`subprocess` 的 `env=` 会替换子进程环境。Git 子进程因此只有这 11 个安装键，再覆盖 6 个 Git 键。其中没有 `GIT_DIR`、`GIT_CONFIG_COUNT`、调用方令牌或动态加载变量。`GIT_CONFIG_GLOBAL=/dev/null` 与 `GIT_CONFIG_NOSYSTEM=1` 使 runner 上更宽的全局 `safe.directory` 不会被继承。宿主子进程的环境集合另有精确白名单，不含这些 Git 键（`owned_process.py` 75–77 行）。

`remote_entry.py` 61 行的 `dict(os.environ)` 只用于控制器门禁。70–71 行要求 `GITHUB_WORKSPACE` 为绝对且 `realpath` 等于自身。checkout 目录若是符号链接，会在 Git 启动前拒绝；对应测试是 `test_alias_checkout_refused_before_git`。

两条命令是 `rev-parse HEAD` 和 `ls-tree -rz --full-tree <固定 commit>`。SDK 在 `--` 之后使用目录中的字面 pathspec。没有 `git config` 写操作，没有 `safe.directory=*`，也没有把父目录放进该值。生产后缀固定为 `sdk-source` / `hud-source`，整个值不会是 `*`，也不会以 `/*` 结尾。

`runtime_fence.py` 把 `os.chown` 列为拒绝事件；清单内 Python 没有 `os.chown(` 调用，也没有 `shell=True`。

这个例外的权限边界是：它让 Git 在该精确目录上忽略所有者不匹配。操作系统仍按原权限决定能否读。随后的 HEAD、清单和 blob 哈希仍约束内容。命令行 `-c` 属于 Git 的受保护配置范围，所以它能作用于所有者检查；仓库自己的本地配置不能把自己标成 safe。

## 绑定与诊断闭包

HEAD 比较、blob 头 `blob <len>\0`、SHA1、文件字节和 1 GiB 总量都保留。普通文件仍走 `read()`：

remote_files.py Ln 10–18：

```python
def read(path,limit=2*1024**2):
    need(type(path) is str and path.startswith('/') and os.path.realpath(path)==path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd);need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<=before.st_size<=limit)
        ...
        need(os.read(fd,1)==b'' and file_stamp(before)==file_stamp(os.fstat(fd))==file_stamp(os.lstat(path)))
```

`file_stamp` 仍是设备、inode、大小、mtime_ns、ctime_ns、nlink（`pm_handoff.py` 60–61 行）。符号链接分支仍是 `lstat` 加 `readlink`。目录模式仍只接受 `100644` / `100755`；listing 仍可表示 `120000`，但 SDK 绑定必须与目录完全一致。

上限没有提高：Git 标准输出与 listing 4 MiB，listing 8,192 项，目录行 4,096，单文件 512 MiB，合计 1 GiB，pathspec 256，可用内存 3 GiB，swap used 512 MiB。3,185 与 67,016,450 都在这些上限内。

诊断键空间是 16 个原 site 加 34 个检查点，共 50。检查点 17 个，kind 仍是 `refused`、`io`、`internal`。

source_selection.py Ln 16–23：

```python
SITES=frozenset(('phase','root','claim','npm_config','synthetic_config','sdk_catalog',
    'sdk_checkout','sdk_stage','product_checkout','product_stage','tool_read',
    'tool_stage','plugin_projection','plugin_write','source_verify','complete'))
KINDS=frozenset(('refused','io','internal'))
CHECKS=frozenset(('path','head_run','head_result','head_size','head_binding','catalog',
    'listing_run','listing_result','listing_size','listing_count','listing_record',
    'listing_binding','file_read','file_size','file_hash','source_bytes','materialize'))
SITES=SITES|frozenset(slot+'_checkout_'+check for slot in ('sdk','product') for check in CHECKS)
```

`diagnostic()` 只返回 `version: 2`、`site`、`kind`（78–86 行）。site 不在封闭集合内时变成 `phase`。异常文本、路径、argv、环境和 Git stderr 不进入记录；Git stderr 被 `DEVNULL` 丢弃。

授权、acceptance、claim 与聚合分别要求 v3。聚合 schema 不在可变字段里，所以旧 v2 文档不能靠改诊断版本混入。sources 阶段的诊断还必须通过 version 2 校验。

remote_contract.py Ln 34–42：

```python
need(auth['schema']=='hermes_0222_remote_authorization_v3' and auth['scope']==SCOPE
     and hexstr(auth['grant'],32) and hexstr(auth['sha'],40)
     ...
need(type(acceptance) is dict and acceptance=={'schema':'hermes_0222_remote_acceptance_v3',
     'scope':SCOPE,'safety':'PASS','sha':auth['sha'],'freeze_sha256':freeze,'report_sha256':report})
```

新 scope 是 `one_remote_hermes_0222_exact_git_trust_v3_install1800_host300_no_retry_no_risk_acceptance`。聚合结果里的 scope 仍是两条固定结果字符串，与授权 scope 不是同一个字段。`remote_entry.py` 22 行只接受 freeze v3。

子协议、身份、信号、清理和真实 exit 0 所在文件属于那 31 个未变文件。当前文本仍要求子载荷 `ENTRY_RETURNED_ZERO_NOT_ACCEPTANCE`、父进程观察到的 exit 0（`child_protocol.py` 52–85 行），以及先核对身份再发 `SIGTERM` / `SIGKILL`（`owned_process.py` 48–55、149–181 行）。聚合仍要求三条安装命令 exit 0，且清理 exit 0（`remote_contract.py` 76–92 行）。这些记录都带 `WARN_NOT_ACCEPTED` 与 `BLOCK`，并且 `retry: False`。

workflow 仍是单次 `workflow_dispatch`、`contents: read`、`persist-credentials: false`、`macos-15-intel`。它不内嵌 scope；授权来自运行输入。新的 reviewed SHA 与 v3 授权都还没有创建。

## 非阻断与证据上限

以下事项一次登记，不单独构成阻断：

1. 信任通过后，Git 仍会读取该仓库的本地配置。生产命令只有 `rev-parse` 与 `ls-tree`，并关闭了 system/global、replace 和 lazy fetch。本轮没有执行 Git，因此不能证明这两条 plumbing 在所有版本上都不会触发 fsmonitor 或 hook。内容替换仍会被后续哈希挡住。
2. `GITHUB_WORKSPACE` 只要求绝对且 canonical，没有单独拒绝换行。生产后缀使该值不能成为 `*` 或 `/*`。
3. 产品槽 `selection=None`，所以 `product_checkout_listing_binding` 在这条执行路径上不会被走到。它仍是封闭诊断键。SDK 路径会做完整清单绑定。产品的 `catalog` 检查点只标记顺序，不读取 SDK 目录。
4. `listing_size` 会在 Git 输出上限和 listing 解析处各标记一次。两次都是尺寸拒绝。
5. Python audit 不是内核沙箱。`test_checkout_git.py` 20–37 行允许精确登记的 Git、`/dev/null`、管道 FD、已绑定 root 的相对写入，以及清理期的相对遍历。159 行写明 preload 不在覆盖内。`child_guard.py` 1–4 行和 `audit_adapter.py` 13–14 行也写明 audit 不是独立沙箱。`FINAL_SOURCES` 的 `open: 3028` 是打开计数，不是 Git 进程数。
6. 完整 sources 用例实际调用 `Backend.sources()`，使用两个本地合成仓和真实文件，并核对投影后的 `index.js`。`HOST_COMMIT` / `HUD_COMMIT` 只在内存中替换为合成 commit。它不执行 SDK，`installer` 保持为空。
7. `GIT_TEST_ASSUME_DIFFERENT_OWNER=1` 只存在于测试包装器和 `probe_git_trust.py`。探针源码不写死 128；`TRUST_PROBE_RECEIPT.json` 记录 ordinary 0、假定不同所有者 128、精确目录 0。本轮没有重跑该探针。
8. `METADATA_PROBE_RECEIPT.json` 记录合成树 3,185 条、274,637 B、缺失与额外都为空。这是元数据夹具回执。`PUBLIC_TREE_PROOF.json` 另有全树 19,838 条，并声明原始全量元数据未归档，所以 19,838 与 1,234 个 tree object 不能在本轮重算。目录 JSON 的 3,185 与 67,016,450 已独立重算。
9. `WORKTREE_PROBE_RECEIPT.json` 绑定的是旧后端 `02b9d0c9…`，用于同所有者基线。它不是当前 FINAL。
10. 探索性和失败 harness 另有本地 Git 记录：元数据探针 2、信任探针 4、三次失败 harness 各 88。它们不计入 105，本轮也没有相加成“整轮总数”。
11. 初始合成夹具清理保持 UNKNOWN。最终组记录 pending 0，这仍不是内核级清理证明。
12. 本地 payload 未推送。workflow 只有在未来的 reviewed SHA 指向含该修复的提交，并且另有 v3 授权时，才会执行这版代码。当前缺授权是状态，不是缺件缺陷。
13. Git blob 身份仍是 SHA1。这是所选 Git 对象的格式，目录与冻结文件另用 SHA256。
14. 清单中还有更早的 `run-39113826866` 聚合文件。它不是 `39118974049` 的诊断记录，本轮不用它解释这次 `sdk_checkout` 拒绝。

## 本轮实际范围

做了：按清单绝对路径读取合同、请求、回读、补丁、冻结、当前与基线的相关源码、workflow、探针、历史聚合和回执；用独立 hashlib、JSON、AST 和内存补丁重放完成核对。

没做：没有修改或新增文件，没有运行被审脚本、测试、探针、SDK、安装器、host 或 verifier，没有导入被审模块，没有列目录、递归或按引用扩读，没有 Git、网络、HOME、数据库、凭据或日志查询，没有创建授权、claim 或命令。

边界：退出码 128/0 与 105 个 Git 进程来自清单内回执及与测试结构一致的静态分解。本会话没有重新观察这些进程。
