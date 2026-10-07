# 远端容量修订：Intel 平台限定离线准备

本节为当前唯一生效增量；下方旧 v2/v1 全文是历史合同，不是新授权。
状态 OFFLINE_PREPARATION_ONLY / NOT_AUTHORIZED / NOT_PUSHED / NOT_RUN。
私有工具修订 v3 不是产品 v2.0.0。MEMORY NOT CLOSED / WARN_NOT_ACCEPTED，PUBLIC RELEASE BLOCK。

## 解决的具体阻断与取舍

run37590410497 的 snapshot 臂初始可用内存 3209052160B，低于固定 3221225472B 门槛 12173312B（11.609375MiB），在宿主 spawn 前停止。该判定基于已回收的安全聚合摘要与冻结源码；原 analysis.json 尚未本地归档，不能冒称完整原件复审。第一臂及旧 FAIL 不升级，历史55.781/189.672MiB与旧根因UNKNOWN保留。

只将待部署 workflow 的 runs-on 从 macos-latest 改为 macos-15-intel；两臂仍同一新鲜 runner、顺序执行、同一追踪起点/深度/阶段/源/阈值。GitHub 官方规格将前者列为 7 GB ARM64，后者列为 14 GB Intel 标准 runner；2026-10-07 API 确认仓库 public。不是付费 larger runner，不创建账单/runner资源。标称总RAM不保证可用RAM，更不保证第二臂通过；每臂原有3GiB/5GiB准入、运行资源检查全保留。禁止降低门槛、等待资源回升后重试、GC/trim、拆臂换机器或延长实验。此次仅准备，Intel 的选择仍须在下一单次授权中显式确认。

这是实验平台更换，不是仅给原 ARM64 机器加内存。即使成功，最多是 Intel/macOS15 限定的有限实验执行证据，不能证明 Apple Silicon/原生产环境无泄漏，不能与旧ARM64绝对内存值直接比较。若用户必须验证 ARM64，应该另选受明确费用授权的同架构资源；本目录不会自动选择或付费。新标签固定OS大版本但不固定具体镜像build；Mach/依赖/psutil Intel兼容仍未实际验证，失败即停止，不回退 ARM64 或旧入口。

## 代码与门控边界

运行协议的 payload/terminal/diagnostic 仍为 v2/v2/v1，分析器逐字不变；未改变其结果语义。必须连同本次freeze/review/SHA解释，脱离绑定的泛化PASS不得称Intel平台或硬件认证。新 freeze schema hud_remote_same_trace_memory_freeze_v3，验收 schema hud_memory_pair_review_acceptance_v3；新 scope one_remote_same_trace_pair_intel_v3_100min_no_retry_no_risk_acceptance。旧授权即使未过期也被 scope/freeze 拒绝。

entry增加纯判定函数 runner_profile_valid，并在 setup/run 原生入口要求 RUNNER_OS=macOS、RUNNER_ARCH=X64、sys.platform=darwin、platform.machine()=x86_64、Python3.13严格整数元组；再保留原workflow摘要/全冻结校验。环境与进程元数据不是硬件证明；本函数模型不调用本机uname或任何Mach/psutil。平台不符在setup创建root之前拒绝。无新原生诊断程序、无资源阈值变更、无额外HTTP/WS/进程权限。platform.machine仅父入口使用，不把完整父环境传给子进程；子端原最小环境不变。

报告名 WORKBUDDY_REMOTE_FINITE_MEMORY_RUNNER_CAPACITY_REVIEW.md。未来复审通过且用户对Intel范围明确新授权后，才同名逐字复制报告到HERE、物化新acceptance/grant/SHA/freeze并单次派发。此次均不创建。失败或结果不明不重试，安装≤30min、pair≤100min、job135min不变；无需重复另做短启动。

## 验证与交付限制

新20项纯模型测试：6直接门控/范围测试+14平台负向；与原153项合计173项，实际结果以本目录回执为准。真实标准库循环16项另列，不等于OS管道/网络/原生兼容。新冻结包含30项，原29中6件改变与1新增（最终分类以机械回读为准）；测试/harness变更不扩原生路径。依赖预载与解释器启动在hook之前，禁用计数不可代替源码审读。真实prepared/read仅读精确本轮+对比源，不创建gate、不调用controller/entry.main。

旧本地artifact RAM导出会话53514的stdin曾被审批策略拒绝，未通过其它接口绕过，原件仍缺；本轮不追加artifact GET或读取ZIP/DB/home/log。回读摘要与RUN_METADATA是上轮留存，执行事实按请求方记录，不冒称此次重新从GitHub原件独立复算。只读仓库元数据与官方规格查询不等于原实验硬件取证。后续原件可由用户提供已解包analysis.json；不需要原生重跑。

## 历史 v2/v1 合同逐字保留

# 同追踪双臂异步修复准备合同

本轮仅获授权集中离线修复与真实事件循环合成回归。NOT_AUTHORIZED_FOR_NATIVE_RUN、NOT_PUSHED、NOT_DISPATCHED。这是私有工具修订，不是产品版本。MEMORY NOT CLOSED / WARN_NOT_ACCEPTED，PUBLIC RELEASE BLOCK。

## 本轮生效增量

本节优先于下方逐字保留的历史 v1 合同。运行载荷 hud_finite_attribution_pair_v2、封口 hud_memory_pair_completion_v2、冻结 hud_remote_same_trace_memory_freeze_v2、验收 hud_memory_pair_review_acceptance_v2。scope 为 one_remote_same_trace_pair_async_v2_100min_no_retry_no_risk_acceptance，报告名 WORKBUDDY_REMOTE_FINITE_MEMORY_ASYNC_REPAIR_REVIEW.md。entry.FILES 精确 29 项，新增 execution_diagnostics.py、test_async_loop.py、real_loop_checks.py。旧 schema、scope、许可和已消费 claim 不能用于本修订。

run_arm 直接 await NativeIO.ws_once_async，不在已有运行循环中再调用 asyncio.run。底层 _ws 与 HTTP/WS 超时、容量、鉴权及单次调用合同不变。Python [Runner 文档](https://docs.python.org/3.13/library/asyncio-runner.html)明确同线程已有运行循环时不能调用 asyncio.run；[Task 文档](https://docs.python.org/3.13/library/asyncio-task.html)说明 await 的调度与取消行为。测试用冻结旧 native_io.py 摘要绑定并抽取原 ws_once 方法，实际进入标准库循环重现该缺陷；这不证明 run37585748951 的现场唯一原因，历史根因仍 UNKNOWN。

失败诊断只含固定 schema、stage、kind 三键。39 个阶段、9 种类别；不保存异常文字、动态类型名、路径、调用帧、token 或原始输出。首次错误保留，清理与后续检查不得覆盖；release 失败也不得保留候选 PASS。pair 和 arm 的 error 非空时必须有合法诊断，error 为空时必须为 null。分析器在 FAIL 早返回前同样检查完整 schema；未知或附加原文整体丢弃。PASS 要求诊断全空，原句柄与 child 实际 exit0、完整清理与冻结/源链等旧判据不放松。旧记录继续用旧分析器，绝不回填新字段。

## 离线证据边界

纯协作模型现有 116 项加诊断/schema/接线回归 37 项，共 153 项；另 16 项真实标准库事件循环合成回归，分为传输 9 项和 run_arm 7 项。最终执行事实以 FINAL_MODEL_RECEIPT.json、FINAL_REAL_LOOP_RECEIPT.json 的命令、cwd、实际计数、完整 unittest 输出与当前输入哈希为准。首次回执保留历史快照，不能充当当前绑定。

真实循环使用未替换的 SelectorEventLoop、任务调度、await、取消与原有 10 秒 wait_for 超时。连接器/进程/阶段/数据均为合成，测试不调用真实 websockets.connect、HTTP、宿主、psutil、Mach、SQLite 或远端 CI，不验证真实 OS 运输管道或原生超时行为。标准库循环及自身唤醒 socketpair 在安装审计 hook 前创建；依赖预载、解释器启动和冻结旧方法的定点读取也在 hook 前。hook 后所有 socket 事件、进程、信号、SQLite、ctypes 新调用、写入及白名单外内容读取均拒绝。计数为零不能代替静态边界核验，也不能称整个进程零网络基础设施。

每测试结束无遗留任务，循环最后关闭；取消被转换为固定失败诊断，合成清理不能冒充真实进程清理。10 秒测试不缩短、不改写 timeout。本地解释器版本记在回执；远端仍要求 Python3.13，跨版本运行兼容未获本轮证明。

## 保留与未来门控

下方历史合同、全部旧工具/报告/FAIL/claim保留。此次不创建 acceptance/authorization/permit/claim，不复制复审报告到 controller HERE，不执行 entry 或 controller，不查询生产或远端，不 push/main/改产品版本/release。旧失败的安全聚合仅作为历史绑定输入，不重新分析成 PASS。

复审者只读精确白名单，唯一新增复审目录的 WORKBUDDY_REMOTE_FINITE_MEMORY_ASYNC_REPAIR_REVIEW.md，不扩读保护链、不运行任何被审代码。此次只请求一个集中安全复审；低/信息备注登记，不为文字启动版本循环。后续若另获本具体远端 pair 授权，才允许同名逐字报告 HERE 副本、新验收、新授权、新 SHA/freeze 物化及单次派发。失败或不明不重试，准备通过不是运行许可，更不是风险接受或公开 PASS。

## 历史 v1 合同原文

# 有限同追踪双臂内存实验准备合同

状态：OFFLINE_PREPARATION_ONLY；NOT_AUTHORIZED、NOT_PUSHED、NOT_RUN。本目录是私有实验工具，不是产品v2.0.0。旧工具/报告/FAIL/claim全部保留。复审通过也不创建运行授权。

## 可回答的问题与不能回答的问题

拟在同一新鲜远端macOS runner上顺序执行sham、snapshot两臂，固定Hermes0.19.0/Python3.13/psutil7.2.2/websockets15.0.1。两臂都在同一宿主导入前启动tracemalloc depth1；sham零快照，snapshot五次快照始终对第一次baseline。用于观察在相同追踪设置下快照干预与各层内存变化的有限证据；不能声称历史+55.781 MiB或旧tracked +189.672 MiB已归因，不能用净traced下降排除产品/原生保留。

正常执行与数值增长接受完全分开。本协议没有增长接受预算，也没有“RSS不涨即无泄漏”合格线。执行通过仅能标VERIFIED_REMOTE_SAME_TRACE_FINITE_PAIR_ONLY；模型即使注入execution_kind=NATIVE，也只是schema合作测试，不产生真实CI证据。MEMORY NOT CLOSED / WARN_NOT_ACCEPTED，PUBLIC RELEASE BLOCK始终保留。

## 固定阶段和先验判据

每臂先做同样的ready/HTTP/WS鉴权冒烟，再执行warmup60秒、baseline120秒、四轮load300秒/cooldown180秒、final120秒。负载轮每两秒依次请求snapshot（四语言轮换）、timeline100、usage30天、skills，开一个鉴权WS连接持续接帧；冷却无HTTP/WS调用。单次HTTP读上限1MiB、超时10秒，WS同上限/10秒接收超时，连接/关闭超时10/2秒；不自动重连/重试。

baseline和每次cooldown后各保留完整30秒检查点窗口，共五个。sham作等长空操作、values=null、snapshot_count=0；snapshot各取一次snapshot_count=1，第一次保留baseline，后四次compare_to=1。无GC/trim/vmmap。主阶段2220秒（37分钟），另五窗口150秒，共2370秒（39.5分钟），不含夹具/冒烟/清理；不得把37分钟误当总时长。

采样间隔2秒，标量是psutil RSS、Mach self resident_size/phys_footprint/compressed、traced_current/trace_metadata、线程/FD及三个缓存长度。RSS与Mach resident分列，不做相减守恒推断。所有filename包括相对/伪文件只作SHA-256，不resolve、不存原文；top≤25，仅provenance非ownership。Mach结构沿用旧准备工具前缀，本轮不会调用Mach、psutil或验证本机兼容；缺字段/原生异常仍停。

每阶段及最后60秒尾窗覆盖均≥90%，阶段最大间隙≤10秒，采样全局严格单调。缺阶段/缺冷却点/错序/不完整即停止后续阶段/臂，OLS不得输出。只在双臂均零issues且四冷却点齐全时，逐臂输出final−baseline及四点描述性OLS/h；禁止跨臂绝对footprint比较，无假设检验、无因果或长期泄漏结论。检查点sample.phase=checkpoint时容许32秒采样心跳，平时10秒；覆盖门槛不放松。

单臂≤3000秒、整轮≤6000秒、安装≤1800秒；运行检查在2980/5980秒停止继续操作，留20秒清理余量。同步IO/信号/OS取消不是确定性硬截止；TERM wait15秒/KILL wait5秒，加子线程join及封口可能越过余量，此时不出权威PASS。GitHub步骤100/30/3分钟、job135分钟。许可≤1小时窗口只控制setup和pair首次启动，已获授权的固定100分钟pair不需中途续签；两臂不可拆成两个授权运行。

## 复用已跑通的启动和权限边界

专题141与run37574629966已证实一次2.882秒合成短启动，但不是本实验权限。保留直接解释器绑定、随机非9119端口、完整pid/birth/cwd/argv/exe、signal前重核、未知身份零信号、实际child与原Popen exit0一致的要求。自然退出不伪造identity_matched；非零退出绝不PASS。stdout/stderr DEVNULL，token仅RAM/env/鉴权头或WS串，子环境显式最小字典，不拷贝真实/provider/GitHub凭据。

SQLite/文件/网络/exec/signal守卫并列，未知事件仍sticky并在终局再验；Python audit不是内核沙箱，不证明元数据不可枚举/变更。两处constants一次、Config cap64合成缺席与固定源码摘要/行号合同保留。绝不读/proc或放宽任意文件、launchctl执行。

唯一次数增量：固定collector933→397、darwin、owned UID、精确四元组launchctl print gui/UID、cwd/env均None的合成缺席cap16→128；guard新schema hud_memory_guard_stack_v1，不与旧短启动v3互换。50分钟按30秒诊断周期的理论100次，加启动/边界余量后选128设计上限；这是先验预算，不是运行需求证明，实际出现更多/形状不同即sticky FAIL。此分支永远raise FileNotFoundError，绝不产生Popen。仅延长同一合成fallback次数，不扩进程权限。

夹具为全新owned合成HOME：5000sessions、200000messages、4900usage、20active、4980ended、2000tool、1000skills；真实公共发行版DDL通过AST提取，不执行schema模块、不补列。双臂使用同epoch；fixture/七counts/原native_ddl声明/四种源种子hash起止一致。产品16文件与公共5源码hash绑定，非完整传递依赖闭包；分析器不读DB/home/原日志/原snapshot，不反查filename哈希。

## 单次门控和封口

entry仅在GitHub Actions、指定repo/testref、workflow_dispatch、attempt1、reviewed SHA、冻结工作流字节一致、darwin/Python3.13时可setup或pair。私有controller先核报告/acceptance/全新授权/真实freeze，再只读远端SHA，再独占DISPATCH_CLAIM，随后唯一POST；API结果不明不重发。没有服务端全局去重声明。

setup独占新root及SETUP_CLAIM，安装失败也消费。pair入口重核同授权/claim后先独占PAIR_CLAIM（含启动窗口和冻结绑定），再逐臂RUN_CLAIM→夹具→唯一Popen。NativeIO在run_arm和spawn前重核远端上下文/PAIR_CLAIM/起点授权/当前冻结及6000秒预算，不能从“constructor成功”推导原生权限。失败停止第二臂，不删claim、不复用旧入口。共享workflow concurrency不取消已有运行。

result.json恒PENDING_TERMINAL_SEAL；completion绑定实际payload字节摘要、freeze/review、候选判定及封口取时。缺completion/非零exit/无清理证据均非PASS，失败分析仅DIAGNOSTIC_ONLY_NOT_VERIFIED、INCOMPLETE_NO_SLOPE。安全FAIL中的schema无效嵌套数据整体丢弃，不转导原文。分析器仅读取固定result/completion两文件；缺封口时仍只发布固定缺证据诊断。最大payload/聚合2MiB，样本每臂≤1600；只上传aggregate-artifact/analysis.json，ZIP/原日志/home不属于artifact。

## 离线验证和证据性质

offline_checks.py预载依赖后安装audit：禁止进程、网络、SQLite、信号、ctypes新加载/查询、所有写入、白名单外内容读取。测试为纯schema负向、合成snapshot/清理/完整run_arm协作模型、AST接线检查。异步run_arm只由不挂起的模型协程驱动，不建真实event loop/OS pipe。模型行程提供完整合成样本供判据消费，不证明真实时间、资源、EOF、Mach或CI。prepared/read另作真实hash/open组合回读，与模型事实分列；原生仍NOT_RUN。

本轮不修改产品源码/版本/main，不push/dispatch，不创建acceptance/permit/grant/claim，不运行原生。旧工具冻结保持原件，复制/声明增量通过SOURCE_DIFF.patch及MECHANICAL_READBACK核对；历史旧失败不升级。低/信息项集中登记，不因文字再开工具版本循环。

## 复审和未来物化

本轮只做一次聚焦集成工具/工作流安全复审。不得要求审查者扩读旧保护链、运行脚本/测试/探针/Git/网络、创建许可或复制报告。审查者唯一新增复审目录内WORKBUDDY_REMOTE_FINITE_MEMORY_INTEGRATION_REVIEW.md。

未来若获本具体有限pair的另行明确授权，再把已获接受报告的同名逐字副本放到controller HERE，并物化新REVIEW_ACCEPTANCE及AUTHORIZATION；controller绑定报告SHA与新freeze/SHA/scope。报告本身不是授权。安装/实验失败或不明不重试，只回收安全聚合。此时仍不得改产品版本/main/发布或代用户接受memory WARN。
