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
