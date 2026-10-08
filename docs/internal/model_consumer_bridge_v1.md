# Model Consumer ↔ C Core：INTERNAL Bridge V1

日期：2026-10-07（Asia/Shanghai）。范围：quadrotor_hil / ID7 MVP，单 Gateway、单 Core、单 run、单 FLIGHT_CONTROL 写者。

**合理推测（本轮冻结的规范性设计）**：`INTERNAL_BRIDGE_CONTRACT = FROZEN`。FROZEN 表示本文件已选定精确语义，可用于后续实现与评审，不表示双方实现、真实模型或部署已通过。实现中的任何语义变更须重新评审并提高 bridge_version，不能静默改变 V1。**已确认**：当前代码没有本桥；真实资产门禁 NO_GO。**待确认**：真实生成 getter、构建、配置初态和同机时钟证明；均为实施/验收门禁，不以设计文档代替。

权威文件：本文件内嵌 JSON Schema 与紧接的语义约束共同定义 INTERNAL V1，5A 报告只引用，不另维护一套接口。外部权威仍为 [冻结 v0.3](../interfaces/baseline/input-simulator-data-contract-v0.3.md) 与 [目录/probes](../interfaces/baseline/input-simulator-icd-v0.3.json)。不改变 HIL-ICD-1.0 的消息、Wire、Session、CRC、Ack、Evidence 或 error 枚举。

消费者：Gateway 内唯一串行 ModelConsumerService，负责 admission、单 Queue、授权决策、反馈与归档。提供者：C Core，负责 OwnerRecord、真实步边界、最终 writer、ModelU 读回与有界结果。后续变更须由 Consumer/C 集成负责人及模型构建负责人核对；姓名/组织待项目指定，不猜测。

## 1. 运输、解析与最小命令集

以下均为**合理推测（冻结设计）**。单数据报 UTF-8 JSON、无 BOM，无重复 key、NaN/Infinity、未知字段；最大 **8192 bytes**，最大嵌套深度16。超限/截断整包拒绝，禁止分片拼接。C 非 RT 线程用严格 parser、RFC8785 canonicalizer 及 SHA256 做检查；RT 不解析 JSON、不收发 UDP、不阻塞等待、不分配内存。复用 `127.0.0.1:9997` 命令传输；Gateway 固定回环 ephemeral socket，每进程保持，不为每条请求重新建 socket。双方验证实际 peer，C 回应从9997，Gateway 仅接收该地址。收包缓冲需以8193字节/MSG_TRUNC辨识超限；旧main_rt缓冲不能当成已满足。

| operation | 作用 | 响应 body |
|---|---|---|
| bridge_hello | 只读握手、启动身份/时钟/容量/状态 | status |
| open_model_run | CONFIGURED、step0、验证真实包与显式初态后绑定新epoch | status；完成绑定才OK |
| stage_model_input | 提前暂存不可变ID7并预留结果槽 | result |
| get_input_result | 无执行副作用、按全部身份/hash查询 | result |
| get_model_status | C一致快照，含已完成步及当前边界 | status |
| bridge_control | 闭集授权/续租/生命周期/撤权屏障 | control_result + status |

`revoke_control` 是 `bridge_control(action=REVOKE_CONTROL)`；`clear_epoch` 是 `CLOSE_EPOCH`，不增加重复命令。只用五个候选只读/数据命令无法真正登记owner或创建epoch，因此必须加open_model_run及闭集bridge_control。不得透传旧cmd、shell、文件路径、任意内存offset；初始化快照由可信启动装配预先校验加载，本命令只核对hash，不能通过hash假装恢复完毕。缺真实初态入口则TARGET_MISSING。

## 2. 身份、run与authoritative step

**已确认（源码）**：`main_rt.c:1048` 在wrapper model_step返回后sequence++，而wrapper loaded=false可无操作返回；现状只有完成调用次数，没有真实运行资格。旧reset不归零且直接RUNNING，不能复用其语义。

**合理推测（冻结设计）**：选择方案C（A+B组合）。C每次进程启动用OS随机源生成128位 `core_instance_id`；Gateway每次进程启动生成gateway_instance_id，每次完整新模型run或RESET生成新的128位run_epoch。C只在step0 CONFIGURED安全屏障验证并接受新epoch。实例随机源失败则不可ready；不可仅用pid/时间戳。model_id固定quadrotor_hil，真实package/contract/baseline/build_identity hash一致；build_identity_sha256为真实资产identity record（不含本字段）的RFC8785 SHA256，包含contract/header/generated artifact/build script/executable/工具链/step/基线全部身份；model_package_hash沿用model_package.py:69–91既有算法，不与此复合hash混用。同一实例不得热换模型，换包停止进程并新instance。Gateway重启禁止接管旧epoch，先撤权STOP/CLOSE_EPOCH；需要RESET或重启至step0后创建新epoch。任何操作不得从旧status猜当前步。

`current_step/sequence` = 本epoch已完成的**真实生成model_step**次数，初态0；S边界定义为完成S−1之后、执行第S次model_step之前。C独占并串行闭合边界；闭合前完成STAGED发布才可参与S。即使sequence仍S−1，边界已闭合也须LATE。stage要求1≤S≤86400000、1≤S−current_step≤1000，0迟到容忍，无追赶。`boundary_step` 在闭合至step返回之间为S，其他时候null。loaded=false时禁止执行/递增；step返回后sequence=S、模拟时间S×1ms。PAUSED不推进；RESUME保留步与模型状态，清旧stage、旧SID退休，新SID重新授权，不能归零。RESET在旧epoch封存后恢复全部显式initial state/inputs/parameters，新epoch step0 CONFIGURED；C确认后Python才初始化其唯一Queue的epoch步计数，不能重建Registry逃避原记录。

## 3. Hash、幂等与Schema语义约束

以下为**合理推测（冻结设计）**，JSON Schema无法表达的等式必须执行：

1. 持久执行key `K=(core_instance_id,run_epoch,model_id,model_package_hash,session_id,request_sequence)`。transaction_id/message_id不进入可变索引，存在record里且必须相等，否则DUPLICATE_CONFLICT。request_id只关联一次RPC，可在查询/重传时重新随机生成，不影响执行key。
2. `canonical_request_sha256 = SHA256(RFC8785(canonical_request))`，完全沿用Queue/Session原logical message digest，不哈希PCAP、不使用普通json.dumps。canonical_request是重组后的原完整BusinessMessage，仅ID7；C核对其全部header/payload与input_request以及request_key相同。
3. `request_sha256 = SHA256(RFC8785({"identity": identity, "input_request": input_request}))`，覆盖epoch、所有owner/time/mapping字段，不包含RPC request_id/operation或hash本身。同K同两hash返回原状态，绝不重写或延长期限；同K异任一hash、原transaction/message/mapping不同整条拒绝（拒绝本次冲突RPC，不将原执行record改成REJECTED），不last-write-wins。重传原stage body必须字节语义不变，不能更新时间或target。
4. C不能盲信Python的hash；两种hash与原请求交叉验证都在非RT线程重算。C RFC8785可用性/实现与黄金向量是5B依赖，不能把Python散列字符串当成完整性验证。
5. 所有ns/revision/control_sequence均十进制字符串，规范ASCII、无前导0，解析后≤18446744073709551615；有效owner revision/control_sequence需≥1；expected_owner_revision在初始NONE状态可0，model_revision可0，绝不回绕。JSON数值整型不接受bool；u32范围按Schema，原transaction_id与冻结Header一致为1..UINT32_MAX。
6. response operation/request_id必须等于请求，instance/identity必须匹配；RESET响应顶层identity关联旧请求，status.identity报告新epoch；hello/open返回当前/新绑定身份；stage/query返回selector必须等于请求。身份不符响应只作异常，不匹配当前请求；此类失败顶层core_instance_id/identity报告C实际instance及当前identity（未绑定为null），result.selector只回显可合法解析的原查询selector，不把它当成C持有该请求的证据。epoch未绑定hello/status identity=null，model_ready=false；其它读写身份非null。status只能证明观测时事实，不能替代目标提交结果。
7. operation→body严格匹配上表，response顶层error等于result/control_result的error，status成功为OK。stage/query身份不符/坏schema的拒绝可用body.result，target_step=0、accepted_at_ns/applied_step/model_revision/probe=null、terminal_at_ns为本次拒绝时刻、effects=NOT_COMMITTED，仅在请求提供合法selector时回显；无法解析selector的报文不回应，计有界诊断，Consumer按超时处理。
8. STAGED: error=OK、accepted_at_ns非null、target_step≥1、applied_step/terminal_at_ns/model_revision/probe=null、effects=NOT_COMMITTED。APPLIED: error=OK、applied_step=target_step≥1，accepted/terminal/model_revision/probe非null、effects=COMMITTED。REJECTED: error不得OK/UNKNOWN_RESULT，applied_step=null、probe=null、terminal_at_ns非null；effects=NOT_COMMITTED或WRITE_UNVERIFIED，不将所有reject称为未写。UNKNOWN: error=UNKNOWN_RESULT、applied_step/probe/terminal_at_ns=null、effects=UNKNOWN；缺记录时accepted_at_ns/model_revision=null。
9. probe readback_sha256=SHA256(RFC8785(readback))，readback是从最终**真实ModelU**读取的4个double；checked_at_ns=terminal_at_ns，owner_revision与请求相等。APPLIED时model_revision为C epoch内成功整条commit单调递增计数，可映射到外部u32时不得溢出，否则停止run。不是generation或request_sequence。
10. Control RPC幂等key=(instance,epoch,control_sequence)，hash=SHA256(RFC8785({identity,body}))；同key同hash原样返回，同key异hash拒绝；递增、不回绕。管理RPC超时用原bridge_control body/同control_sequence重放查询原record，不重复执行；未知/已回收只返回UNKNOWN，不再次执行。open_model_run同instance/gateway/epoch同body可重放当前status，不重置；同epoch不同body拒绝。响应COMPLETED仅在安全屏障/读回/生命周期效果完成后，非排队receipt；UNKNOWN不保证未执行。

## 4. Payload authority、OwnerRecord与精确时间

**合理推测（冻结设计）**：Python只发送 `payload.flight_control.motor_command` 完整四值组JSON。path固定 `flight_control.motor_command`；C用同包生成 `HilInputSpec / hil_contract_find_input / hil_contract_set_input / hil_contract_set_actuators`确认并映射到ModelU。Python不能发送target_field/memory offset或任意path。generated contract是唯一ABI mapping authority。最终writer按OwnerRecord.input_lane选取；即使source=DEMO_MISSION，只要lane=FLIGHT_CONTROL，本目标仍由原ID7四值写入，不能转回旧mission控制器。V1不stage环境、故障、参数或其它message；非控制初态由配置安全屏障处理，不从ID7偷偷引入。

OwnerRecord由C维护，不由stage自报覆盖：session_id为实际producer CONTROLLER SID，source/lane与当前记录相同，revision一致，session和owner期限都活。SET_OWNER仅PAUSED、冻结expected_step、expected_owner_revision CAS匹配：Gateway先使用实际SessionRegistry、RegisteredController及SemanticGuards核对selector STIMULUS和producer配置身份、run/model/roles/lane；可信supervisor通道提交决策摘要；C复核绑定run/模型、PAUSED、旧revision、旧stage全取消、safe0读回，才增加revision并登记producer。authorization_decision_sha256用于审计，**不是认证凭据**。该登记入口仅可信Gateway peer可用；本地信任模型见第9节。stage不能调用SET_OWNER或取得控制权。

OwnerRecord grant lease固定100ms。有效且完整验证通过的新控制原请求在STAGE更新last_valid_received_ns、expires_at_ns=received_ns+100000000，不改owner revision；重复/失败/Heartbeat不延长control租约。延迟stage不把accepted_at_ns当received_ns。C保留各请求deadline并单独维护当前已应用命令deadline与model TTL，新future command即使续owner也不能延长旧电机值。RENEW_SESSION只由真实已验证Heartbeat更新session_expires_at_ns=heartbeat_received_ns+1000000000，不能改变control期限或复活已过期SID/owner；续租迟到就新Session。

Python与C必须同一Linux kernel boot及同一time namespace，使用可比 `time.monotonic_ns / CLOCK_MONOTONIC`；握手clock_domain=UNVERIFIED则所有write拒绝STATE并不发布ready。部署核查boot/time namespace是启动资格，hello里的声明本身不是证明。WindowsPython→WSL C跨域不直接比较；本轮只在Windows审查，无时钟资格。

`deadline_ns = received_ns + 100000000`，valid_for_ms固定100。STAGE、最终commit前读回判定均要求 **received_ns ≤ now_ns < deadline_ns**、now<owner expires、now<session expires；恰100000000ns EXPIRED，99999999ns仅在其它条件均合格时允许。checked_at_ns若已到deadline则禁止APPLIED，safe/revoke并留WRITE_UNVERIFIED记录。时间加法溢出拒绝BAD_SCHEMA。时钟未来/回拨fail closed，不能容忍负age。每次重传不得续received/deadline。

模型TTL自target模型时刻起计：APPLIED于S后可保持模型区间[S,S+100)，在边界S+100写safe0；单调100ms期限可能更早，取先到者。PAUSED/STOP立即安全，不能等待模型TTL。无新有效实际控制接收，C独立watchdog在下一running边界safe0/revoke；暂停亦在安全服务边界safe0，Heartbeat不续控制。过期owner revision递增，相关stage终结。fault派生的有效执行器与ModelU原输入证据分开；64/1007只证ModelU完整输入，不能伪称电机物理读回。

## 5. QUEUED / STAGED / APPLIED与最终probe

**合理推测（冻结设计）**：QUEUED是Python已接受但C未暂存；STAGED是C已完成验证并持有不可变目标请求、路径预约和预留completion，仍未写真实ModelU。C不得合并两条ID7或覆盖未决值；同target同path整条OWNER_MISMATCH，Python亦沿用现有单writer预约。STAGED只能转APPLIED或REJECTED；UNKNOWN是查询者对不可知事实的观察，不撤销C状态，也不是允许再次执行的状态。

选择**方案A：APPLIED=目标S的最终ModelU原子commit/readback事件，发生在model_step前**。冻结E2是实际写入，等step返回才APPLIED会错误混同模型执行结果，暂停态其它实际setter/getter也不需动力学推进。精确顺序：

```text
完成S−1 → C关闭S边界，选本步已STAGED请求 → 再检state/epoch/owner/age
→ 在candidate整组校验、apply非控制快照（V1只来自已确认配置）
→ 选唯一final control owner → 写完整四值ModelU → 所有control writer结束
→ 真实ModelU getter读回/比对4值 → 再检期限/owner → 预留槽写入APPLIED记录
→ 紧邻model_step() #S，无其它writer → 返回后sequence=S
```

RT内边界、owner撤销、safe与final writer串行；操作顺序决定冲突胜负，不靠两个线程读sequence猜测。成功4值采用与生成double相同binary64、数值精确相等（+0/-0规范为0），无clamp/容差。旧`write_actuator_command(float*)`会float舍入后再转double，不能直接复用作ID7精确写；5B必须保留binary64请求值。最终getter必须来自同生成ABI的contract-backed getter或经同构建证明的typed accessor；wrapper `model_get_input()`指针本身不证明field getter。缺getter是Blocking dependency，本轮不实现、不靠Python记忆值替代。

probe路径64（四值字段证据）及consumer1007（完整ID7事务）使用冻结目录，不新编编号。校验失败：未commit则NOT_COMMITTED；已经写但probe失败/过期则WRITE_UNVERIFIED，REJECTED/PROBE_MISMATCH或EXPIRED，进入safe/revoke，不能声称负例must_not_apply已满足。若真实commit/probe已成功后model_step失败，保留APPLIED事实，生命周期FAILED/业务证据另报；不能改写成未应用。C在记录前崩溃或重启丢失内存记录时只能UNKNOWN，不能从新sequence倒推应用。

`ID7_CONSUMED = NOT_IMPLEMENTED / NOT_REQUIRED_FOR_MVP`。model_step不是consumer-read probe，不发ID7 CONSUMED。

## 6. 查询、retry、UNKNOWN、wire封存

**合理推测（冻结设计）**：get_input_result无二次执行，核对instance/epoch/K/两hash；已知record返回STAGED/APPLIED/REJECTED，同K异hash冲突；在当前epoch查无记录返回UNKNOWN_RESULT，**查无记录不证明未写**。已结束旧epoch的只读查询在5秒保留窗口允许用原身份查原record，不能stage；若请求的是另一instance，返回CORE_INSTANCE_MISMATCH，不能把新实例UNKNOWN当旧实例未应用。

Consumer用绝对 `query_deadline_ns=received_ns+100000000`（冻结目录model_apply_ack_timeout_ms=100）；此为本桥本地结果确认窗口，不延长控制deadline、不替代外部传输ack_timeout_ms=200。尚未到期时发同原stage/同key query，推荐轮询间隔5ms，无新的request_sequence、不改target；每次socket recv仅剩绝对窗口，不被无关包重置。迟到的STAGED仍须按原期限处理。

到期未有可靠terminal result：内部台账UNKNOWN、E2 NOT_EVALUATED，停止新ID7stage、REVOKE_CONTROL/安全屏障并查询原key。wire仅能一次 `FAILED/TIMEOUT`，probe_id=0/applied_step=0不能被解读为确知未写。不得向其后追加同请求APPLIED/CONSUMED或改写原FAILED；迟到C真实结果作为本地late E2/异常归档，标记该用例FAIL，不重发成功终态。已发APPLIED后safe/step失败也只追加独立Safety/Status/Evidence，绝不另一请求terminal Ack。

尚无wire terminal且窗口内收到有效APPLIED：验证全部身份/hash/target/owner/deadline/probe后，Python映射冻结Ack(APPLIED/OK, applied_step=S, model_revision, probe_id=1007)，保存已发生阶段；正常前缀RECEIVED→VALIDATED，VALIDATED必须实际校验完成。SID已失效不复活：有预留tombstone与反馈路由可发真实缓存阶段（需要5D实现），无可用路由则只归档。不得利用当前Session.record_response放宽其防伪限制直接造Ack。

## 7. Lifecycle / 重启屏障

以下均为**合理推测（冻结设计）**；control的expected_state/step/revision在C安全边界CAS校验，失败无副作用。成功control COMMITTED记录/安全probe预留后才执行，COMPLETED表示效果完成。设置owner/Heartbeat续租是管理内部桥，不能作为外部ID6/2已实现的声明。

| event | C与Python同步规则 | epoch / step |
|---|---|---|
| START | 完整初态verified且CONFIGURED→RUNNING；不能隐式授权owner | 保持epoch，0开始递增；没有owner只safe0 |
| PAUSE | RUNNING→PAUSED；冻结模型、撤owner、safe0读回、旧stage全部REJECTED/STATE | 保持epoch/已完成步；确认前不发布PAUSED完成 |
| RESUME | PAUSED→RUNNING；先清旧stage/Queue、退休旧SID，新Session重新授权 | 保持epoch/状态/步，不catch-up；必须在PAUSED先退休旧SID、建立新Session并SET_OWNER，然后RESUME核对producer_session_id/prepared_owner_revision为本次pause屏障后登记的新owner；保留这个新owner，禁止RUNNING授权 |
| STOP | RUNNING/PAUSED/CONFIGURED→STOPPED；安全/撤权，未commit stage终结STATE | epoch结束，step冻结；只允许查询/RESET/CLOSE |
| RESET | PAUSED/STOPPED→CONFIGURED；封存旧epoch，恢复全部显式initial snapshot及model state/参数并验证 | new_run_epoch必须新，sequence=0，model_revision=0；旧SID失效 |
| session expiry | 独立mono期限到即禁止stage/apply，safe/revoke、相关stage REJECTED/OWNER_MISMATCH或EXPIRED | 不自动重启模型epoch；新SID需PAUSED授权 |
| C restart | 新instance、旧请求全部失效；未持久旧result仍UNKNOWN | 新epoch须完整初态/step0握手；不能跨实例查询成功 |
| Gateway restart | 新gateway id不热接管旧台账，safe/STOP/CLOSE旧epoch；重置或重启、重新配置会话 | 旧epoch不可写；旧证据若尚保留只读恢复 |
| CLOSE_EPOCH | STOPPED/FAILED/CONFIGURED且safe确认后关闭，所有stageterminal | step不因close偷偷归零；再open必须真正step0 |

STOP与S commit竞争按同一C串行屏障线性化：STOP先则不apply；APPLIED先则保存实际E2再safe。RESET同理，不能将既有APPLIED记取消。Owner expiry/watchdog不依赖Python轮询。FAILED恢复须明确RESET/新instance，不能自动RESUME。control_result.safe_readback仅safe动作真实getter读回才非null；COMPLETED且动作需要安全时应等于[0,0,0,0]；无法证明则不得COMPLETED。RUNNING的STOP/PAUSE在模型boundary处理，冻结态服务边界不推进模型。

## 8. 容量、completion、tombstone

**合理推测（冻结设计）**：Python全模型QUEUED+STAGED+in-flight未核销逻辑总数≤4096；C staged_capacity=4096，是同一请求执行副本，无第二独立入口/配额。C completion_capacity=8192（stage仍占一个预留slot）；执行前原子预留stage+completion+路径预约，任一不足CAPACITY，不执行、不覆盖旧结果。control记录亦占共享completion容量，最多保留8192条所有数据/管理记录，不存在无限旁路。需安全动作时即使池满也必须safe/revoke；记录不足则进入FAILED/stop admission，用预留的固定单独emergency safety状态槽保存最新安全故障计数及事实，不能承诺无槽的ID7 E2。

每终态包括REJECTED保留从terminal_at_ns起至少5000ms；stage期间不得淘汰，expiry/watchdog使其在期限终结。stage同key重发仅返回现有记录，不追加槽。completion满时背压，即使平均20ms控制负载通常可容纳也不能用负载假设代替界限。Python结果/反馈/tombstone共享8192身份记录（运行中的4096占此池的预约），TIMEOUT未决也保留至少5000ms，从wire封存时计；未归档/未安全完成的UNKNOWN不能静默淘汰，池满停止新写。不得收完结果后即释放C身份防重放。

5000ms后非RT线程只回收已terminal/已封存且未决处理满足的记录；C/Python保留每epoch/session的最大已见request_sequence、epoch闭合记录和control_sequence高水位，旧sequence不会成为fresh stage。SID不得复用，run旧epoch永不重开；旧record回收后的query=UNKNOWN，不重新执行。MVP最多64活SID，达到身份高水位容量时先安全关闭epoch，不能淘汰仍可写SID的水位。C不依赖ACK收讫来无限延长保留，也不因UDP丢包重复应用。结果不是持久磁盘日志：C崩溃可能失去E2，故重启不声明未应用，Gateway需要本地证据归档。

## 9. Errors与安全边界

**合理推测（冻结设计）**：如下仅内部码→已有wire码，wire用原枚举整数；不新增外部码。模型/身份/hash故障停止新写并安全撤权；普通未写拒绝保留真实RECEIVED前缀。

| internal | frozen wire error | 语义 |
|---|---|---|
| BAD_BRIDGE_VERSION | MODEL | bridge不兼容，未ready |
| CORE_INSTANCE_MISMATCH / EPOCH_MISMATCH | STATE | 旧run/实例，不自动重发 |
| MODEL_MISMATCH / HASH_MISMATCH | MODEL | ABI/包或canonical完整性不符 |
| DUPLICATE_CONFLICT | BUSINESS_FAILED | 同key内容改变；不覆盖原记录 |
| OWNER_MISMATCH | CONTROL_OWNER | C当前owner/SID/revision不符 |
| LATE | LATE | S已闭合，无追赶 |
| EXPIRED | EXPIRED | 100ms/session/TTL到期 |
| STATE | STATE | 生命周期/时钟/服务边界不合格 |
| CAPACITY | CAPACITY | stage/completion/台账不足 |
| TARGET_MISSING | TARGET_MISSING | 实际模型/生成映射/getter未ready |
| APPLY_FAILED | BUSINESS_FAILED | 整条事务失败，effects必须诚实 |
| PROBE_MISMATCH | SAFETY | 实际读回失配，WRITE_UNVERIFIED，safe/revoke |
| UNKNOWN_RESULT | TIMEOUT | 仅查询窗口终结后映射，非确知未应用 |
| BAD_SCHEMA | BUSINESS_FAILED | 内部adapter协议失败；不伪造原wire负例结果 |

loopback ≠ authentication。本V1安全模型是**受控主机本地trust boundary**：可信supervisor启动并绑定唯一Gateway peer（包括其ephemeral端口/instance），C只从该peer受理管理/写命令；不能以首个任意hello自动抢占控制，不能新进程hello挤掉活Gateway。loopback同用户恶意进程仍可冒充或直接触发旧cmd，必须用受控账户/namespace/进程管理并确保legacy命令在桥所有权生效时无法写同port/path；当前代码尚未做到。每条RPC验证实际peer、随机request_id、hash、instance、epoch、model identity，禁止任意路径/offset/raw command/shell/filepath、禁止绑定外网或暴露透传。随机bridge session token为**建议**的后续防注入加固，V1不声称现有密钥或密码学认证，不默认复杂密钥体系。

## 10. Machine-checkable JSON Schema

以下Schema是本文件的唯一字段结构定义；第3节及状态/容量/时间语义约束同为规范。required列表代表必须显式发送；没有接收端静默默认；nullable字段也不可省略。未知字段一律拒绝。所有schema引用均本地$defs，不读取远端引用。示例只能是设计样本，不冒充实际结果。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:uavdemo:internal:model-consumer-bridge:v1",
  "title": "INTERNAL V1 design only; not implemented HIL-ICD extension",
  "oneOf": [
    {
      "$ref": "#/$defs/Request"
    },
    {
      "$ref": "#/$defs/Response"
    }
  ],
  "$defs": {
    "Identity": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "bridge_version",
        "core_instance_id",
        "run_epoch",
        "model_id",
        "model_package_hash",
        "hil_contract_sha256",
        "baseline_sha256",
        "build_identity_sha256"
      ],
      "properties": {
        "bridge_version": {
          "const": 1
        },
        "core_instance_id": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "run_epoch": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "model_id": {
          "const": "quadrotor_hil"
        },
        "model_package_hash": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "hil_contract_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "baseline_sha256": {
          "const": "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
        },
        "build_identity_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        }
      }
    },
    "RequestKey": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "session_id",
        "request_sequence",
        "transaction_id",
        "message_id"
      ],
      "properties": {
        "session_id": {
          "type": "integer",
          "minimum": 1,
          "maximum": 4294967295
        },
        "request_sequence": {
          "type": "integer",
          "minimum": 1,
          "maximum": 4294967295
        },
        "transaction_id": {
          "type": "integer",
          "minimum": 1,
          "maximum": 4294967295
        },
        "message_id": {
          "const": 7
        }
      }
    },
    "OriginalID7": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "message_id",
        "header",
        "payload"
      ],
      "properties": {
        "message_id": {
          "const": 7
        },
        "header": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "session_id",
            "sequence",
            "transaction_id",
            "target_step",
            "valid_for_ms"
          ],
          "properties": {
            "session_id": {
              "type": "integer",
              "minimum": 1,
              "maximum": 4294967295
            },
            "sequence": {
              "type": "integer",
              "minimum": 1,
              "maximum": 4294967295
            },
            "transaction_id": {
              "type": "integer",
              "minimum": 1,
              "maximum": 4294967295
            },
            "target_step": {
              "type": "integer",
              "minimum": 1,
              "maximum": 86400000
            },
            "valid_for_ms": {
              "const": 100
            }
          }
        },
        "payload": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "motor_command"
          ],
          "properties": {
            "motor_command": {
              "type": "array",
              "minItems": 4,
              "maxItems": 4,
              "items": {
                "type": "number",
                "minimum": 0,
                "maximum": 1
              }
            }
          }
        }
      }
    },
    "InputRequest": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "request_key",
        "canonical_request_sha256",
        "canonical_request",
        "target_step",
        "received_ns",
        "deadline_ns",
        "valid_for_ms",
        "control_source",
        "input_lane",
        "owner_revision",
        "payload"
      ],
      "properties": {
        "request_key": {
          "$ref": "#/$defs/RequestKey"
        },
        "canonical_request_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "canonical_request": {
          "$ref": "#/$defs/OriginalID7"
        },
        "target_step": {
          "type": "integer",
          "minimum": 1,
          "maximum": 86400000
        },
        "received_ns": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "deadline_ns": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "valid_for_ms": {
          "const": 100
        },
        "control_source": {
          "enum": [
            "DEMO_MISSION",
            "PX4_SITL",
            "PHYSICAL_UUT"
          ]
        },
        "input_lane": {
          "const": "FLIGHT_CONTROL"
        },
        "owner_revision": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "payload": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "flight_control"
          ],
          "properties": {
            "flight_control": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "motor_command"
              ],
              "properties": {
                "motor_command": {
                  "type": "array",
                  "minItems": 4,
                  "maxItems": 4,
                  "items": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1
                  }
                }
              }
            }
          }
        }
      }
    },
    "Selector": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "request_key",
        "canonical_request_sha256",
        "request_sha256"
      ],
      "properties": {
        "request_key": {
          "$ref": "#/$defs/RequestKey"
        },
        "canonical_request_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "request_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        }
      }
    },
    "OwnerRecord": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "session_id",
        "control_source",
        "input_lane",
        "revision",
        "expires_at_ns",
        "session_expires_at_ns",
        "last_valid_received_ns"
      ],
      "properties": {
        "session_id": {
          "type": "integer",
          "minimum": 1,
          "maximum": 4294967295
        },
        "control_source": {
          "enum": [
            "DEMO_MISSION",
            "PX4_SITL",
            "PHYSICAL_UUT"
          ]
        },
        "input_lane": {
          "const": "FLIGHT_CONTROL"
        },
        "revision": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "expires_at_ns": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "session_expires_at_ns": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "last_valid_received_ns": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^(0|[1-9][0-9]{0,19})$",
              "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
            },
            {
              "type": "null"
            }
          ]
        }
      }
    },
    "Probe": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "probe_id",
        "path_probe_id",
        "path",
        "readback",
        "readback_sha256",
        "owner_revision",
        "checked_at_ns"
      ],
      "properties": {
        "probe_id": {
          "const": 1007
        },
        "path_probe_id": {
          "const": 64
        },
        "path": {
          "const": "flight_control.motor_command"
        },
        "readback": {
          "type": "array",
          "minItems": 4,
          "maxItems": 4,
          "items": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          }
        },
        "readback_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        },
        "owner_revision": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "checked_at_ns": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        }
      }
    },
    "Result": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "selector",
        "state",
        "error",
        "target_step",
        "applied_step",
        "accepted_at_ns",
        "terminal_at_ns",
        "model_revision",
        "effects",
        "probe"
      ],
      "properties": {
        "selector": {
          "$ref": "#/$defs/Selector"
        },
        "state": {
          "enum": [
            "STAGED",
            "APPLIED",
            "REJECTED",
            "UNKNOWN"
          ]
        },
        "error": {
          "enum": [
            "OK",
            "BAD_BRIDGE_VERSION",
            "CORE_INSTANCE_MISMATCH",
            "EPOCH_MISMATCH",
            "MODEL_MISMATCH",
            "HASH_MISMATCH",
            "DUPLICATE_CONFLICT",
            "OWNER_MISMATCH",
            "LATE",
            "EXPIRED",
            "STATE",
            "CAPACITY",
            "TARGET_MISSING",
            "APPLY_FAILED",
            "PROBE_MISMATCH",
            "UNKNOWN_RESULT",
            "BAD_SCHEMA"
          ]
        },
        "target_step": {
          "type": "integer",
          "minimum": 0,
          "maximum": 86400000
        },
        "applied_step": {
          "anyOf": [
            {
              "type": "integer",
              "minimum": 0,
              "maximum": 86400000
            },
            {
              "type": "null"
            }
          ]
        },
        "accepted_at_ns": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^(0|[1-9][0-9]{0,19})$",
              "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
            },
            {
              "type": "null"
            }
          ]
        },
        "terminal_at_ns": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^(0|[1-9][0-9]{0,19})$",
              "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
            },
            {
              "type": "null"
            }
          ]
        },
        "model_revision": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^(0|[1-9][0-9]{0,19})$",
              "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
            },
            {
              "type": "null"
            }
          ]
        },
        "effects": {
          "enum": [
            "NOT_COMMITTED",
            "COMMITTED",
            "WRITE_UNVERIFIED",
            "UNKNOWN"
          ]
        },
        "probe": {
          "anyOf": [
            {
              "$ref": "#/$defs/Probe"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "allOf": [
        {
          "if": {
            "properties": {
              "state": {
                "const": "STAGED"
              }
            }
          },
          "then": {
            "properties": {
              "error": {
                "const": "OK"
              },
              "accepted_at_ns": {
                "type": "string",
                "pattern": "^(0|[1-9][0-9]{0,19})$"
              },
              "target_step": {
                "minimum": 1
              },
              "applied_step": {
                "type": "null"
              },
              "terminal_at_ns": {
                "type": "null"
              },
              "model_revision": {
                "type": "null"
              },
              "probe": {
                "type": "null"
              },
              "effects": {
                "const": "NOT_COMMITTED"
              }
            }
          }
        },
        {
          "if": {
            "properties": {
              "state": {
                "const": "APPLIED"
              }
            }
          },
          "then": {
            "properties": {
              "error": {
                "const": "OK"
              },
              "accepted_at_ns": {
                "type": "string",
                "pattern": "^(0|[1-9][0-9]{0,19})$"
              },
              "target_step": {
                "minimum": 1
              },
              "applied_step": {
                "type": "integer",
                "minimum": 1
              },
              "terminal_at_ns": {
                "type": "string",
                "pattern": "^(0|[1-9][0-9]{0,19})$"
              },
              "model_revision": {
                "type": "string",
                "pattern": "^(0|[1-9][0-9]{0,19})$"
              },
              "probe": {
                "$ref": "#/$defs/Probe"
              },
              "effects": {
                "const": "COMMITTED"
              }
            }
          }
        },
        {
          "if": {
            "properties": {
              "state": {
                "const": "REJECTED"
              }
            }
          },
          "then": {
            "properties": {
              "error": {
                "not": {
                  "enum": [
                    "OK",
                    "UNKNOWN_RESULT"
                  ]
                }
              },
              "applied_step": {
                "type": "null"
              },
              "probe": {
                "type": "null"
              },
              "terminal_at_ns": {
                "type": "string",
                "pattern": "^(0|[1-9][0-9]{0,19})$"
              },
              "effects": {
                "enum": [
                  "NOT_COMMITTED",
                  "WRITE_UNVERIFIED"
                ]
              }
            }
          }
        },
        {
          "if": {
            "properties": {
              "state": {
                "const": "UNKNOWN"
              }
            }
          },
          "then": {
            "properties": {
              "error": {
                "const": "UNKNOWN_RESULT"
              },
              "applied_step": {
                "type": "null"
              },
              "probe": {
                "type": "null"
              },
              "terminal_at_ns": {
                "type": "null"
              },
              "effects": {
                "const": "UNKNOWN"
              }
            }
          }
        }
      ]
    },
    "Status": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "identity",
        "core_instance_id",
        "model_identity_verified",
        "model_loaded",
        "clock_domain",
        "sampled_at_ns",
        "current_step",
        "boundary_step",
        "lifecycle",
        "owner",
        "model_revision",
        "initial_snapshot_sha256",
        "staged_count",
        "reserved_completion_count",
        "staged_capacity",
        "completion_capacity",
        "retention_ms",
        "result_query_timeout_ms",
        "id7_probe_ready"
      ],
      "properties": {
        "identity": {
          "anyOf": [
            {
              "$ref": "#/$defs/Identity"
            },
            {
              "type": "null"
            }
          ]
        },
        "core_instance_id": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "model_identity_verified": {
          "type": "boolean"
        },
        "model_loaded": {
          "type": "boolean"
        },
        "clock_domain": {
          "enum": [
            "LINUX_CLOCK_MONOTONIC_SAME_NAMESPACE",
            "UNVERIFIED"
          ]
        },
        "sampled_at_ns": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "current_step": {
          "type": "integer",
          "minimum": 0,
          "maximum": 86400000
        },
        "boundary_step": {
          "anyOf": [
            {
              "type": "integer",
              "minimum": 0,
              "maximum": 86400000
            },
            {
              "type": "null"
            }
          ]
        },
        "lifecycle": {
          "enum": [
            "CONFIGURED",
            "RUNNING",
            "PAUSED",
            "STOPPED",
            "FAILED"
          ]
        },
        "owner": {
          "anyOf": [
            {
              "$ref": "#/$defs/OwnerRecord"
            },
            {
              "type": "null"
            }
          ]
        },
        "model_revision": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "initial_snapshot_sha256": {
          "anyOf": [
            {
              "type": "string",
              "pattern": "^[0-9a-f]{64}$"
            },
            {
              "type": "null"
            }
          ]
        },
        "staged_count": {
          "type": "integer",
          "minimum": 0,
          "maximum": 4096
        },
        "reserved_completion_count": {
          "type": "integer",
          "minimum": 0,
          "maximum": 8192
        },
        "staged_capacity": {
          "const": 4096
        },
        "completion_capacity": {
          "const": 8192
        },
        "retention_ms": {
          "const": 5000
        },
        "result_query_timeout_ms": {
          "const": 100
        },
        "id7_probe_ready": {
          "type": "boolean"
        }
      }
    },
    "Request": {
      "oneOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "bridge_version",
            "request_id",
            "operation",
            "body"
          ],
          "properties": {
            "bridge_version": {
              "const": 1
            },
            "request_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "operation": {
              "const": "bridge_hello"
            },
            "body": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "gateway_instance_id",
                "baseline_sha256"
              ],
              "properties": {
                "gateway_instance_id": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{32}$"
                },
                "baseline_sha256": {
                  "const": "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
                }
              }
            }
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "bridge_version",
            "request_id",
            "operation",
            "identity",
            "body"
          ],
          "properties": {
            "bridge_version": {
              "const": 1
            },
            "request_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "operation": {
              "const": "stage_model_input"
            },
            "identity": {
              "$ref": "#/$defs/Identity"
            },
            "body": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "input_request",
                "request_sha256"
              ],
              "properties": {
                "input_request": {
                  "$ref": "#/$defs/InputRequest"
                },
                "request_sha256": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{64}$"
                }
              }
            }
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "bridge_version",
            "request_id",
            "operation",
            "identity",
            "body"
          ],
          "properties": {
            "bridge_version": {
              "const": 1
            },
            "request_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "operation": {
              "const": "get_input_result"
            },
            "identity": {
              "$ref": "#/$defs/Identity"
            },
            "body": {
              "$ref": "#/$defs/Selector"
            }
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "bridge_version",
            "request_id",
            "operation",
            "identity",
            "body"
          ],
          "properties": {
            "bridge_version": {
              "const": 1
            },
            "request_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "operation": {
              "const": "get_model_status"
            },
            "identity": {
              "$ref": "#/$defs/Identity"
            },
            "body": {
              "type": "object",
              "additionalProperties": false,
              "required": [],
              "properties": {}
            }
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "bridge_version",
            "request_id",
            "operation",
            "identity",
            "body"
          ],
          "properties": {
            "bridge_version": {
              "const": 1
            },
            "request_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "operation": {
              "const": "bridge_control"
            },
            "identity": {
              "$ref": "#/$defs/Identity"
            },
            "body": {
              "oneOf": [
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision"
                  ],
                  "properties": {
                    "action": {
                      "const": "START"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision"
                  ],
                  "properties": {
                    "action": {
                      "const": "PAUSE"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision",
                    "producer_session_id",
                    "prepared_owner_revision"
                  ],
                  "properties": {
                    "action": {
                      "const": "RESUME"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "producer_session_id": {
                      "type": "integer",
                      "minimum": 1,
                      "maximum": 4294967295
                    },
                    "prepared_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$"
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision"
                  ],
                  "properties": {
                    "action": {
                      "const": "STOP"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision",
                    "new_run_epoch",
                    "initial_snapshot_sha256"
                  ],
                  "properties": {
                    "action": {
                      "const": "RESET"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "new_run_epoch": {
                      "type": "string",
                      "pattern": "^[0-9a-f]{32}$"
                    },
                    "initial_snapshot_sha256": {
                      "type": "string",
                      "pattern": "^[0-9a-f]{64}$"
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision"
                  ],
                  "properties": {
                    "action": {
                      "const": "CLOSE_EPOCH"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision",
                    "producer_session_id",
                    "selector_session_id",
                    "control_source",
                    "input_lane",
                    "received_ns",
                    "session_expires_at_ns",
                    "authorization_decision_sha256"
                  ],
                  "properties": {
                    "action": {
                      "const": "SET_OWNER"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "producer_session_id": {
                      "type": "integer",
                      "minimum": 1,
                      "maximum": 4294967295
                    },
                    "selector_session_id": {
                      "type": "integer",
                      "minimum": 1,
                      "maximum": 4294967295
                    },
                    "control_source": {
                      "enum": [
                        "DEMO_MISSION",
                        "PX4_SITL",
                        "PHYSICAL_UUT"
                      ]
                    },
                    "input_lane": {
                      "const": "FLIGHT_CONTROL"
                    },
                    "received_ns": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "session_expires_at_ns": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "authorization_decision_sha256": {
                      "type": "string",
                      "pattern": "^[0-9a-f]{64}$"
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision",
                    "producer_session_id",
                    "heartbeat_received_ns",
                    "session_expires_at_ns",
                    "canonical_heartbeat_sha256"
                  ],
                  "properties": {
                    "action": {
                      "const": "RENEW_SESSION"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "producer_session_id": {
                      "type": "integer",
                      "minimum": 1,
                      "maximum": 4294967295
                    },
                    "heartbeat_received_ns": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "session_expires_at_ns": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "canonical_heartbeat_sha256": {
                      "type": "string",
                      "pattern": "^[0-9a-f]{64}$"
                    }
                  }
                },
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "action",
                    "control_sequence",
                    "expected_state",
                    "expected_step",
                    "expected_owner_revision",
                    "reason"
                  ],
                  "properties": {
                    "action": {
                      "const": "REVOKE_CONTROL"
                    },
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "expected_state": {
                      "enum": [
                        "CONFIGURED",
                        "RUNNING",
                        "PAUSED",
                        "STOPPED",
                        "FAILED"
                      ]
                    },
                    "expected_step": {
                      "type": "integer",
                      "minimum": 0,
                      "maximum": 86400000
                    },
                    "expected_owner_revision": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "reason": {
                      "enum": [
                        "OPERATOR",
                        "SESSION_EXPIRED",
                        "CONTROL_EXPIRED",
                        "BRIDGE_LOST",
                        "SHUTDOWN",
                        "RESULT_UNKNOWN"
                      ]
                    }
                  }
                }
              ]
            }
          }
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "bridge_version",
            "request_id",
            "operation",
            "body"
          ],
          "properties": {
            "bridge_version": {
              "const": 1
            },
            "request_id": {
              "type": "string",
              "pattern": "^[0-9a-f]{32}$"
            },
            "operation": {
              "const": "open_model_run"
            },
            "body": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "core_instance_id",
                "gateway_instance_id",
                "run_epoch",
                "model_id",
                "model_package_hash",
                "hil_contract_sha256",
                "baseline_sha256",
                "initial_snapshot_sha256",
                "expected_state",
                "expected_step",
                "build_identity_sha256"
              ],
              "properties": {
                "core_instance_id": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{32}$"
                },
                "gateway_instance_id": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{32}$"
                },
                "run_epoch": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{32}$"
                },
                "model_id": {
                  "const": "quadrotor_hil"
                },
                "model_package_hash": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{64}$"
                },
                "hil_contract_sha256": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{64}$"
                },
                "baseline_sha256": {
                  "const": "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
                },
                "initial_snapshot_sha256": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{64}$"
                },
                "expected_state": {
                  "const": "CONFIGURED"
                },
                "expected_step": {
                  "const": 0
                },
                "build_identity_sha256": {
                  "type": "string",
                  "pattern": "^[0-9a-f]{64}$"
                }
              }
            }
          }
        }
      ]
    },
    "Response": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "bridge_version",
        "request_id",
        "operation",
        "core_instance_id",
        "identity",
        "error",
        "responded_at_ns",
        "body"
      ],
      "properties": {
        "bridge_version": {
          "const": 1
        },
        "request_id": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "operation": {
          "enum": [
            "bridge_hello",
            "open_model_run",
            "stage_model_input",
            "get_input_result",
            "get_model_status",
            "bridge_control"
          ]
        },
        "core_instance_id": {
          "type": "string",
          "pattern": "^[0-9a-f]{32}$"
        },
        "identity": {
          "anyOf": [
            {
              "$ref": "#/$defs/Identity"
            },
            {
              "type": "null"
            }
          ]
        },
        "error": {
          "enum": [
            "OK",
            "BAD_BRIDGE_VERSION",
            "CORE_INSTANCE_MISMATCH",
            "EPOCH_MISMATCH",
            "MODEL_MISMATCH",
            "HASH_MISMATCH",
            "DUPLICATE_CONFLICT",
            "OWNER_MISMATCH",
            "LATE",
            "EXPIRED",
            "STATE",
            "CAPACITY",
            "TARGET_MISSING",
            "APPLY_FAILED",
            "PROBE_MISMATCH",
            "UNKNOWN_RESULT",
            "BAD_SCHEMA"
          ]
        },
        "responded_at_ns": {
          "type": "string",
          "pattern": "^(0|[1-9][0-9]{0,19})$",
          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
        },
        "body": {
          "oneOf": [
            {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "status"
              ],
              "properties": {
                "status": {
                  "$ref": "#/$defs/Status"
                }
              }
            },
            {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "result"
              ],
              "properties": {
                "result": {
                  "$ref": "#/$defs/Result"
                }
              }
            },
            {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "control_result",
                "status"
              ],
              "properties": {
                "control_result": {
                  "type": "object",
                  "additionalProperties": false,
                  "required": [
                    "control_sequence",
                    "control_sha256",
                    "state",
                    "error",
                    "safe_readback",
                    "effect_at_ns"
                  ],
                  "properties": {
                    "control_sequence": {
                      "type": "string",
                      "pattern": "^(0|[1-9][0-9]{0,19})$",
                      "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                    },
                    "control_sha256": {
                      "type": "string",
                      "pattern": "^[0-9a-f]{64}$"
                    },
                    "state": {
                      "enum": [
                        "COMPLETED",
                        "REJECTED",
                        "UNKNOWN"
                      ]
                    },
                    "error": {
                      "enum": [
                        "OK",
                        "BAD_BRIDGE_VERSION",
                        "CORE_INSTANCE_MISMATCH",
                        "EPOCH_MISMATCH",
                        "MODEL_MISMATCH",
                        "HASH_MISMATCH",
                        "DUPLICATE_CONFLICT",
                        "OWNER_MISMATCH",
                        "LATE",
                        "EXPIRED",
                        "STATE",
                        "CAPACITY",
                        "TARGET_MISSING",
                        "APPLY_FAILED",
                        "PROBE_MISMATCH",
                        "UNKNOWN_RESULT",
                        "BAD_SCHEMA"
                      ]
                    },
                    "safe_readback": {
                      "anyOf": [
                        {
                          "type": "array",
                          "minItems": 4,
                          "maxItems": 4,
                          "items": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1
                          }
                        },
                        {
                          "type": "null"
                        }
                      ]
                    },
                    "effect_at_ns": {
                      "anyOf": [
                        {
                          "type": "string",
                          "pattern": "^(0|[1-9][0-9]{0,19})$",
                          "description": "Canonical decimal uint64; semantic maximum 18446744073709551615; nanoseconds."
                        },
                        {
                          "type": "null"
                        }
                      ]
                    }
                  }
                },
                "status": {
                  "$ref": "#/$defs/Status"
                }
              }
            }
          ]
        }
      },
      "allOf": [
        {
          "if": {
            "properties": {
              "operation": {
                "enum": [
                  "bridge_hello",
                  "open_model_run",
                  "get_model_status"
                ]
              }
            }
          },
          "then": {
            "properties": {
              "body": {
                "required": [
                  "status"
                ]
              }
            }
          }
        },
        {
          "if": {
            "properties": {
              "operation": {
                "enum": [
                  "stage_model_input",
                  "get_input_result"
                ]
              }
            }
          },
          "then": {
            "properties": {
              "body": {
                "required": [
                  "result"
                ]
              }
            }
          }
        },
        {
          "if": {
            "properties": {
              "operation": {
                "enum": [
                  "bridge_control"
                ]
              }
            }
          },
          "then": {
            "properties": {
              "body": {
                "required": [
                  "status",
                  "control_result"
                ]
              }
            }
          }
        }
      ]
    }
  }
}
```

## 11. 5B Entry Gate与验证向量

**待确认（实施前强制补齐）**：真实同包hil_contract/headers/generated ABI/build目标及hash；ModelBindings对真实contract通过；getter位置及binary64型别可识别；真实initial snapshot恢复路径；C/Python同Linux时钟域；RFC8785 C实现/编译依赖可提供。任一真实资产NO_GO禁止5B真实模型实施，可另行授权C_TEST_ABI_ONLY harness，不能冒充real E2。

**合理推测（冻结验收规则）**：5B需用真实模型验证提前STAGED、S精确、最终writer不覆盖、4值读回及probe64/1007，源/lane/revision/session/epoch错配拒绝，99999999ns合格/100000000ns拒绝，float舍入负例，S闭合竞态，同key同hash查询与异hash拒绝，stage/terminal receipt各丢包，查询deadline精确封存与迟到结果不追加成功Ack，容量8192满时无无证据执行，PAUSE/STOP/RESET/RESUME清理、C/Gateway重启身份失效，已APPLIED后step失败仍保留E2；真实E3、LinuxRT±10us和麒麟资格分别验收，不以本文件冻结替代。

交叉参考：[5A Gate报告](../HISTORY_PCAP_Round5A_Real_Model_Assets_Bridge_Contract_Gate_20261007.md)、[Round5审查](../HISTORY_PCAP_Round5_Model_Consumer_Architecture_Review_20261007.md)。
