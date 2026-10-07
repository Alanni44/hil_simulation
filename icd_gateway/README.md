# Shared Standard UDP Ingress And Queue Primitives

本工作包是同一ICD接收路径的开发版本，不是Windows专用服务，也不是完整3.6。默认命令行仍仅ID1。2026-10-07新增显式接收验证模式和前两类源的自生数据入口，使用同一冻结ICD与Receiver；当前Windows只验证共用软件与原库对象，Linux原生通道、实际模型和正式替换资格尚未通过。下方W2/W3章节保留阶段历史，当前收发用法以本节为准。

## 2026-10-07 Reception Milestone

当前目标是自生数据、原工具发送、标准实收解码并留下记录，不以W4/W5、硬件采集、完整模型效果/断言/九项清理/RunReport为前置。HISTORY后续由接手人员负责，旧源码和历史证据保留。本批不声称三条实体链路已打通。

`config/generated-input-reception.json`是一份完整运行配置，内含原SourceInputs、真实资源指纹、完整六字段环境快照和0/80/160步的风速0/8/16波形，不是第二份ICD。原业务定义仍只看`docs/interfaces/输入模拟器完整接口定义_v0.3_单文件汇总.md`；本地运行配置与JSONL日志不增加线上字段。

在Windows的现有独立环境中生成数据，不开网络、不使用替代工具：

```powershell
& './runtime/icd-venv/Scripts/python.exe' -X utf8 -m input_simulator.send_cli --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 --run-file config/generated-input-reception.json --output artifacts/icd_gateway/new-generated-samples.jsonl --dry-run
```

输出必须使用不存在的新文件名，已有记录不能覆盖。`--dry-run`只表示产生样本，不表示发送。已执行的生成结果见`artifacts/icd_gateway/generated-input-reception-samples-20261007.jsonl`。

同一入口在Linux/实际后端使用，先按实际NIC/IP/源端口/反馈端口和MAC调整共享部署配置。默认示例是回环控制网，不能直接当作Scapy实体以太网部署。接收端使用：

```text
python -m icd_gateway --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 --deployment config/input-simulator-development.json --receive-only --received-jsonl received-new.jsonl
```

需要CAN时加`--can`，在grant中明确`can_bindings:[{"channel":"CANFD_0","interface":"can0"}]`，源和接收端必须映射同一逻辑通道/实际接口。每个CAN接口只有一个无歧义grant；不以消息自报身份共享同一物理CAN绑定。`--max-receptions 3`可让接收进程在本次3条记录写盘后退出，0表示持续接收，但有限历史满后明确拒绝，不自动驱逐。

场景样本使用原Scapy ETHGEN发送：

```text
python -m input_simulator.send_cli --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 --run-file config/generated-input-reception.json --deployment config/input-simulator-development.json --eth-interface eth0 --source-mac <actual-source-unicast-mac> --destination-mac <actual-receiver-unicast-mac> --output sent-new.jsonl
```

PROTOCOL生成时，在同一运行配置中将`source_kind`设为`PROTOCOL`，将`generation`设为完整对象，例如：

```json
{"stimuli":[{"message_id":10,"payload":{"wind_n_mps":0,"wind_e_mps":0,"wind_d_mps":0,"pressure_pa":101325,"temperature_k":288.15,"ground_height_m":0}}],"count":3,"period_steps":80,"first_step":0}
```

其发送参数使用`--can-channel CANFD_0 --can-interface can0`，接收端加`--can`，走原cantools/DBC -> python-can -> SocketCAN -> 同一Receiver。也可在SCENARIO事件中显式选择CANT；同批混合CANT/ETHGEN时必须同时配置各自参数。缺SocketCAN或Scapy L2直接TARGET_MISSING，不在Windows另造后端，也不把普通UDP当ETHGEN回退。CUTIL/SAVVY默认观察及原回放分支继续保留，但本批发送投影不运行这些服务。

本地记录格式分别为`HIL_RECEPTION_RUN_1`、`HIL_GENERATED_SAMPLE_1`、`HIL_RECEPTION_TX_1`、`HIL_RECEPTION_SESSION_1`、`HIL_RECEPTION_RX_1`与`HIL_RECEPTION_SUMMARY_1`。TX记录包括完整请求/反馈、原CAN TX/RX或Scapy L2实际尝试、原字节HEX及完成/失败/不确定结果；会话开立原请求/回执另存。`sent_fragments`仅计原native完整写入，不证明远端收到。RX保存完整解码报文、identity、实际binding和接收单调时刻；CAN反馈失败退出也保存已解码尾部。文件flush只计本地写入，不声称崩溃安全或完整证据链。

接收验证只完成冻结帧/CRC/重组、Schema、会话/角色/时效准入，标准ACK为RECEIVED -> VALIDATED且probe_id=0；不虚构Status、APPLIED/CONSUMED、模型应用或正式替换资格。默认不启用此模式，未来真实3.3仍经同一ICD和接收路径，不按模拟器/真实来源分流。

场景仅提取SEND/FAULT/WAVEFORM/PERIODIC_START/SAMPLE/STOP发送投影。完整root assertions保留并明确NOT_EVALUATED；WAIT/ASSERT/NEGATIVE_SEND/REPLAY/END_CLEANUP明确拒绝，不悄悄跳过。声明的cleanup保留在原定义，当前只关闭本地拥有对象，不把它当远端清理。`planned_target_step`是配置的目标/采样步；主机相对毫秒仅用于发送演示，不等于真实MODEL_STEP、ClockSync或实时精度。过期前显式abandon/open新SID不是模型RESET。

库级联调使用真正python-can VirtualBus、Scapy SuperSocket和本地测试NIC中继；这些不是实体工具资格。待真实3.6部署地址、Linux原生工具和第三条外部服务到位后再做目标联调，所有缺项集中唯一Linux台账。

## Run

使用独立Python3.12及`requirements-icd.txt`，不导入旧Python3.6服务或静态QA vendor。从仓库根目录使用同一入口：

```text
python -X utf8 scripts/test_icd_runtime.py
python -m icd_gateway --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 --deployment config/input-simulator-development.json
```

示例配置明确使用回环36100接收/反馈发送、36102源发送、36101源反馈接收。该配置只授权完整identity为item-01/vehicle-01/quadrotor_hil的STIMULUS，不购买/启用实物通道。合法部署端点可显式配置，不能改变业务编码或添加私有业务入口。

独立发送进程消费已经生成的完整BusinessMessage文件：

```text
python -m input_simulator --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 --source-bind 127.0.0.1:36102 --feedback-bind 127.0.0.1:36101 --receiver 127.0.0.1:36100 --message-file <business-json>
```

输入不得省字段或把资源包装当业务报文；SessionOpen必须有新128位nonce。每次新开会话使用不同transaction，避免旧SessionOpened与新的请求混淆；当前单请求源按事务和请求ID/序列关联，SessionOpened线上不回显nonce，不能据此证明加密认证。下例调用者显式构造完整输入，未静默补业务字段：

```python
import secrets
from pathlib import Path
from icd_runtime.contract import Contract
from input_simulator.udp_source import UDPSource

pin = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
contract = Contract.load(Path("docs/interfaces/baseline"), expected_sha256=pin)
opening = {
    "message_id": 1,
    "header": {"session_id": 0, "sequence": 1, "target_step": 0,
               "transaction_id": 1, "valid_for_ms": 1000},
    "payload": {
        "identity": {"run_id": "item-01", "source_id": "item-01", "vehicle_id": "vehicle-01",
                     "scenario_id": "item-01", "model_id": "quadrotor_hil", "definition_version": "HIL-ICD-1.0"},
        "roles": ["STIMULUS"], "baseline_sha256": pin,
        "nonce_hex": secrets.token_hex(16), "requested_lease_ms": 1000,
    },
}
with UDPSource(contract, source_bind=("127.0.0.1", 36102), feedback_bind=("127.0.0.1", 36101),
               receiver_endpoint=("127.0.0.1", 36100), channel="ETH_0") as source:
    opened = source.request(opening)
    session_id = opened["payload"]["session_id"]
```

网关须另一个进程已启动。关闭当前源不会伪造SessionClose，租约按接收端时间到期；不能把这个单次示例当作保持会话的场景执行器。

## Implemented Boundaries

- 实际源IP/端口/逻辑通道ACL先于解码与重组；会话绑定全部六个identity字段、明确角色和批准链路。同一identity只有一个grant，多链路在该grant下登记。CRC不是鉴权，范围限隔离实验网络。
- 64个有效会话为当前保守部署上限；session ID在进程内不回绕/复用。租约固定1000ms，只有新的授权Heartbeat续租，重复心跳不续期，普通业务不续租。未连接模型，接收端step0只表示未开始的接口时间原点，不产生真实Status/ClockStatus。
- 按会话统一输入序列、内容摘要与事务关联，跨链路冗余副本只有完整逻辑内容相同才重发原反馈。8192条/5s缓存淘汰后高水位不回退。缓存只存摘要及最多3条/4096规范字节的反馈，每组载荷仍受W1容量限制，不宣称整个Python堆只有8MiB。
- 分片SessionOpen的本地grant隔离防止不同授权来源互相拼接；仍共享每通道64槽、8MiB总重组预算。不会增加线上字段，已建立业务默认重组键不变。
- 源端校验反馈实际源端点、session/transaction、Ack.request_sequence/message_id及反馈序列；相同序列不同内容拒绝。反馈摘要缓存8192条/5s，高水位保留；单个UDPSource生命周期最多追踪64个会话标识，达到上限返回明确BUFFER_FULL，需要关闭并在新的授权周期重建对象。源端访问须串行，当前不支持多个并发未完成请求的反馈分流。
- 可靠非周期请求200ms无终态最多原码重传3次；周期消息不重传旧值。最终34在原重试次数耗尽后仅继续等待到请求开始起10000ms，不新增重发。没有隐式心跳线程，20ms心跳调度属于共用执行器后续任务；提交等待不续租、不捏造sender_step。
- 完整合法模型业务只生成真实RECEIVED后FAILED/TARGET_MISSING；不执行假模型、不生成VALIDATED/APPLIED/CONSUMED或E2/E3。未实现服务命令返回FAILED/UNSUPPORTED。Heartbeat虽可续租，但缺实际Status消费者时返回FAILED/TARGET_MISSING。
- 默认Capabilities仅ID1；显式安装实际可用存储worker时为[1,34]。所有模型/初始化/替换ready为false，qualified_channels/available_probes/supported_codecs为空。queue_capacity4096是冻结契约常量，不表示模型应用队列已接入。完整SessionClose/Cleanup尚未实现，不能把本地对象关闭当作实体清理通过。
- 接入进程独立执行空闲超时清理；关闭清空会话、组和缓存。框架不可信时丢弃并记录有界本地错误，不从损坏的头猜造线上ACK。这些错误计数不是完整E1原码证据包，更不是E2。
- 配置有未知字段、非法端点/角色/identity、组件不匹配即拒绝启动；FORMAL模式始终拒绝，因为正式发布门禁/目标资格尚未实现。DEVELOPMENT_READY不等于正式发布。

## Remaining Work

下一共用工作包：实际消费者接入契约、ControlOwner授权/100ms租约与安全执行、生命周期/完整清理、冻结步服务更新、反馈/evidence包与发布状态门禁；随后完成真实Status/ClockSync、资源/视频和W3/W4。不能将这些全部标为Linux专属重写。W2.2仅实现下述基础库，不将完整W2/M2标为完成。

Linux/实物移交与整体41项覆盖统一登记在`docs/superpowers/plans/linux-development-backlog.md`。每阶段末追加，不覆盖历史记录；缺环境保持未执行。SocketCAN、C实际写入与安全、原六工具链、实体I/O、实时指标、真实3.3切换保留原目标门禁。

## W2.2 Common Binding And Queue APIs

`ModelBindings(contract,model_id,runtime_contract)`检查实际hil_contract声明中的根输入和参数元数据与选定冻结绑定等价：名称、字段/导出符号、类型、维度、单位、范围、环境/参数初值、1ms步长、输入模式和live参数阶段。拒绝缺失/多余根输入或参数、重复参数、错模式或符号，不写`state.outputs`。`map_message`仅支持7..19这13类根输入/参数全量消息，三模型共同覆盖97条绑定；其余消费者明确TARGET_MISSING，不借自由JSON setter补齐。现有六电机文件缺5/6故障，必须拒绝，修复及行为资格归L-004。

结构检查不是完整RunConfigure：初始化、资源/原点、生成ABI/符号实际存在、环境/传感/子系统行为与实时资格尚未完成。测试的`declared_runtime`是元数据夹具，不是可登记的实际模型。未来完整消费者包需扩展已定义的环境/系统/初始化契约校验，不能用本批根输入范围替代全部能力。

`ModelQueue(contract,registry,mappings)`是同一代码的内部基础库，目前没有接入网络Receiver。同一注册表整个生命周期只能创建一个队列，覆盖其全部模型，共用4096容量与单写者域；第二实例构造即拒绝，不能按模型拆队列绕过额度，关闭后也不能重建队列将运行步归0。注册表关闭同时关闭队列；已claim请求不会复活。实际接入服务必须保留单一会话/模型控制域，不能并行启动多个独立服务同时写同一模型。本批close是终止对象，不是业务RESET；运行内重新配置/复位规则须由后续生命周期包实现，不能靠重建活动注册表绕过历史。

它要求原始、合法、仍有效的SessionRegistry admission；缓存保留第一次接收单调时间，只能claim一次。终态失败、同号异值、撤销、缓存淘汰后的请求不能随后入队。清队列不复活旧admission。

`enqueue(message,state='RUNNING',now_ns=...,control_source=...,input_lane=...)`完整检查后才提交整组值及目标路径预约。全局4096逻辑消息，不覆盖/合并旧消息；`stored_bytes`是保存的canonical消息及字段值字节数，不是进程RSS，也不是重组8MiB预算。目标步ahead1..1000，已开始步LATE，最长86400000步。各目标路径持有单写者session/role/source/lane预约；同一步跨消息目标必须互不相交，Flight/Actuator别名不能并开。STIMULUS不取得控制元数据，外部控制消息不接受INTERNAL_CONTROLLER。

`begin_step(model_id,step,state='RUNNING',now_ns=...)`只能由实际模型安全边界串行调用且每次恰好下一1ms步，不能跳步或用墙钟sleep冒充。初始队列从step0开始，运行中临时接管需额外生命周期/同步设计，不能凭调用参数重置步。返回`StepBatch.ready/rejected`，ready仅是待实际写入的不可变完整消息，不是APPLIED或E2；整组原子写入及真实探针必须由消费者实现。不同消息即使同transaction也不构成跨消息原子提交。

控制在入队与边界出队均校验首次接收起100ms上限，心跳/重传不刷新该时间。`expire(now_ns=...)`在空闲时清除已撤销/过期会话并返回原请求拒绝记录。`discard_session/clear/close`返回被清除的原消息，便于下一包形成实际反馈/证据；clear保留步高水位，RESET需后续真实模型复位和明确的运行历史/新会话处理。

这些API不授予控制权：传入source/lane只能来自已核验的实际ControlOwner，不允许把网络请求自报信息直接当作授权。ControlOwner切换前PAUSED/安全置零、控制租约、已应用环境240ms恢复/停机、故障保持及完整STOP/RESET/RESUME效果尚未实现。PAUSED/CONFIGURED安全服务更新不在运行队列内，不自动推进模型或丢失快照。

接入前必须补齐共用生命周期/实际消费者契约、逐消息业务语义和真实反馈缓存更新，再在Linux接C写入点/步时钟/安全设备。当前网关仍只宣告ID1并保持缺消费者明确失败；本库没有被配置为生产模型、没有发布探针或虚假E2/E3。

## W2.3 Shared Semantic Guards

`SemanticGuards`进一步实现正式生命周期/控制源/初始快照的共用校验。不可变`ModelView`必须由真实消费者读出实际模型、状态、步、最长运行步、控制源、实物闭环模式及完整配置是否已应用；不能从SessionOpen、客户端请求、墙钟或旧C的`accepted`回执猜测。测试构造的view只是规则输入，不发布真实Status或模型能力。

`lifecycle(message,view)`覆盖全部六动作及expected_state：START/PAUSE/RESUME/STOP/RESET合法状态转换，RUNNING提前1..1000目标步、冻结态当前步，STEP仅PAUSED且controlNONE/无实物闭环。STEP结果逐项列出连续1ms步，不将步数换成一个大步。STOP/RESET/RESUME要求清队列；RESET必须恢复完整初始快照并新会话，RESUME保留模型状态但重新授权新会话。结果中的safe_outputs/revoke_control是消费者必须完成的义务，不表示已执行安全置零或撤权。

`control_owner(message,view,declared_controller=...,controller_session_roles=...,internal_controller_ready=...)`校验PAUSED交接、实际声明源/型号、CONTROLLER生产角色及内部/外部消费者条件；DEMO_MISSION不能用于Hex/Fixed。ControlOwner消息的STIMULUS发送者不会因此取得实际生产者CONTROLLER权限，生产者身份/角色必须独立从授权部署解析。sourceNONE仅撤销，无有效租约；其他选择固定100ms，实际安全值和队列清理完成前不能授予控制。内部纯决策没有deadline、session新授权或实际写者注册，不是线上新字段。

外部生产者的共同接入入口为`external_control_owner(message,view,registry=...,producer_identity=...,declared_controller=...,now_ns=...)`。它用同一冻结契约的实际`SessionRegistry`检查原始已接收的6请求及STIMULUS选择者，再从完整配置身份解析唯一未到期、实际授予CONTROLLER的生产者SID；run/vehicle/scenario/model/version必须一致，source_id可以不同。`registered_controller(identity,now_ns=...)`保留完整身份、实际角色、冻结链路副本、nonce、SID、会话期限及序号；多个有效CONTROLLER明确拒绝，不按最新nonce猜选。`observe_admitted`保留原摘要/queued/terminal/缓存期限校验但不执行expire；这些读取只推进接收端单调时钟下限，不续租、不分配、不清队列或驱逐历史，调用仍须由实际接收端串行owner负责。

返回`RegisteredOwnerDecision`仍是必要授权条件和安全/清队列义务，不是安全值完成、实际100ms控制租约或APPLIED。选择的声明源与新鲜ModelView仍须从实际RunConfigure/模型消费者取得，执行前重新解析并完成原安全动作，不能把部署声明当作已应用配置。内部控制器输出不走此外部入口，缺实际reader明确TARGET_MISSING；NONE撤销无需活动生产者。旧纯规则API保留兼容，不应用调用方自报角色替代新入口。`NOT_EVALUATED`/ready=false不提升目标后端、实机或RT资格。

`run_configure(message,view,terrain_ground_down=...)`只在STOPPED或初始CONFIGURED校验；选择model与全量initial_inputs分支一致、所有初始控制零、四元数长度误差<=1e-6不自动修正、静止地面Quad/Hex、显式Fixed速度不覆盖、地形/ground_height/airborne一致、GPS无效同时NO_FIX。返回完整canonical配置快照，保留环境/故障/参数/扩展环境/系统/传感故障，而非模型CONFIGURED完成回执。地形SHA非null时必须由实际资源解析器在请求位置/原点/指定hash解析出ground_down；缺样本RESOURCE。无地形资源时使用报文明示的ground_height，不填隐式0。实际资源/障碍/ABI/物理/控制器完整资格仍需后续消费者验证，不能只传一个数就宣布资源已就绪。

`initial_state(message,view,ground_down=...)`仅CONFIGURED/PAUSED，保留显式初始化字节；必须在紧接的真实RESET生效，不写state.outputs、不立即更新动力学真值。实际初始化端口、相邻RESET义务跟踪、资源解析与所有setter/getter探针仍待实现。

这些无副作用决策须在实际执行安全边界使用新鲜view再次校验，防止排队期间状态/控制源/步改变。它们不执行生命周期、不运行模型、没有APPLIED/CONSUMED/E2，不允许凭decision.next_state提前发布Status或Capabilities。

Linux实际C接入需修正既有不等价行为：当前RESET结束为RUNNING、生命周期单槽请求/输入快照会合并替换、控制源选择未限制PAUSED、demo源超时豁免且未统一租约撤销；不能把旧receipt.accepted/effective_sequence当作新ICD真实写入探针。实际状态/原始请求关联、完整队列、初始化/安全/租约、异步证据仍按单一台账L-004/L-010开发，保持原C目标而非Windows移植版。

## W2.4 Retirement And Cleanup Boundary

`SessionRegistry.retire(session_id)`是内部接入授权/队列资源退休API：严格非零uint32，幂等撤销指定会话，释放它的队列/写者预约并返回不可变原PendingInput；不清其他会话、不改模型步、不产生线上成功。`Receiver.retire_session`同时立即释放该会话全部未完成分片。已有低层`registry.revoke`只撤授权，之后Receiver空闲维护也会清除其残留队列/分片。原反馈按既有8192条/5s窗口保留，但已撤销SID不能再入队或重放入站请求。

源/执行器须为新会话生成新nonce。接收端nonce检测只覆盖已有5s重复缓存；缓存过期后仍被部署授权的同一旧SessionOpen可以取得不同的新SID，不提供生命周期级防重放或加密鉴权保证。旧SID从不复用，旧输入始终STALE_SESSION。部署权限/凭据撤销与强认证仍需L-017及正式门禁落实，不能将CRC、nonce或来源类型当安全凭据。

`Receiver.tick(now_ns=...)`不依赖模型推进，即使PAUSED也清过期/撤销会话的队列、写者和分片；先对注册表、队列、重组器的clock/open状态及记录容量做无副作用预检，再删除资源。`SessionRegistry.preview_maintenance`和`ModelQueue.preview_expiry`只给出当前将被清除的原记录，不更新时间、步骤或会话。失败预检不删除资源、不丢原拒绝记录。

tick返回累计的不可变`MaintenanceResult(expired_sessions,rejected_inputs)`，不是每次调用的新增差值。隐式receive/UDPpoll执行维护时也保留记录，实际消费者/证据服务用`drain_maintenance()`取走一次；不取走就会继续保留，不能重复统计每次tick快照。默认最多4096条拒绝输入、8192个到期SID；内部部署可降低`maintenance_input_capacity`至1..4096，但不扩大正式模型队列4096或重组8MiB。缓冲满返回BUFFER_FULL并在删除前拒绝，不覆盖或静默丢弃；实际消费者必须持续排空并执行真实安全/反馈。该存储与原模型队列/反馈缓存分别有界，不声称全部进程RSS等于8MiB。

`Receiver.close()`返回剩余原输入，并另存有界`ShutdownResult(closed_sessions,discarded_inputs)`直到`drain_shutdown()`；即使UDP/context忽略返回值也不丢记录，旧维护记录另行保留可取。关闭清空全部分片（包括早已撤销SID及SessionOpen0）、队列和注册表缓存，随后注册表永久拒绝复用；这不是RESET。UDPGateway.close返回同一原输入，重复关闭不覆盖第一份shutdown。单个内部退休API的返回记录仍需调用者保存，不是自动持久化证据包。

`SemanticGuards.cleanup(message,view)`完整校验37/38的九个必填true项：停止周期发送、回放、视频、安全执行器、释放控制、清接收队列、清模型/总线故障、关闭会话。37是TARGET_MODEL_STEP，RUNNING提前1..1000/冻结当前步；38是SERVICE_BOUNDARY，决策取实际current step，不等待header的未来步。FAILED也允许安全清理；reason保留NORMAL/ABORT/RESET/REPLACE_SOURCE。返回九项义务，不执行任何实际模型/设备/源工具清理。

线上37/38没有完整实际消费者时仍RECEIVED后FAILED（TARGET_MISSING/UNSUPPORTED），不因本地资源可释放而提前撤销合法业务会话或返回APPLIED/CONSUMED。能力仍仅ID1。真实清理须覆盖模型及SensorFault、BusFault/电气故障、DA0/TTL安全、视频与原工具/回放/周期发送者、控制撤权、模型队列和最后会话关闭；终态反馈须在安全清理后保持可靠关联/重传。Linux按L-004/L-010/L-012/L-017接实际消费者和探针；共用异步阶段缓存与原码持久证据包仍待后续实现。

## W3.1 Common Resource Storage Foundation

`ResourceStore(contract,root,...)`是串行调用的实际文件存储基础库，尚未接入Receiver/UDP或管理API。`accept(message,now_ns=...)`只接受冻结34完整对象；检查所有必填字段、严格base64和解码长度、实际块SHA256、连续offset、final恰好在末块、整文件原始字节SHA256。它不是授权服务，调用者仍须接入原始SessionRegistry admission与实际角色/端点，不能以一个自报SID绕过正式接收路径。重复块仅接受原边界/内容；活动上传的跨会话接管、改类型/总长度及不同重复块拒绝。

它使用专用目录、独占锁、私有暂存和按SHA256命名的完整对象；不接受客户端路径/文件名，不覆盖未登记对象。已完成对象重启后重新校验，`resolve(sha,kind=...)`重新读实际字节及有界manifest，不凭文件名信任。已完成字节持久保留；`abort_session`只清该会话未完成上传，`close`终止存储器并清未完成上传。清理拒绝未知内容、目录或符号链接，不删除其他运行/用户文件；写入/读取拒绝硬链接。该检查不是抵御具有本地目录写权限的并发攻击者的完整沙箱，部署必须隔离写权限，目标Linux仍须资格确认。

默认资源容量32MiB/个、总声明字节128MiB、8个活动上传、128个完整/活动对象、8192块/资源，实际数据与发布metadata均检查64MiB磁盘余量；可在同一构造函数显式配置有界部署限制。原唯一块请求以不可变canonical字节保留，活动上传+待drain中止记录共用256MiB evidence上限、128个中止/活动预约；空间不足先拒绝，不淘汰。它们不是重组8MiB预算或进程RSS承诺，也不改变业务字段上限。`drain_aborted()`取走不可变原请求/原因，失败创建、fsync、最终校验不会静默占槽或发布完成。管理员故障恢复与证据持久包尚未实现；忙/残留lock或放弃暂存均失败关闭，不自动删除。

MODEL和VIDEO目前仅为`OPAQUE_BYTES`，不证明ABI、编译/加载或视频解码资格。TERRAIN/OBSTACLES/MISSION使用冻结TerrainResource/ObstaclesResource/MissionLoad定义，标`DEFINED_JSON`；另外检查地形rows*columns、障碍物ID唯一、任务执行索引实际存在。此标记只表示结构和上述资源本地不变量，不能代替实际Origin/地理转换/路线/任务依赖/控制器/模型状态检查。原始JSON字节不重排再计算资源hash；非规范排列但合法的资源文件仍按原字节存储。已完成文件在真正消费者读取时仍须保持相同身份和内容，不能用resolve返回的路径代替消费者实际读取/应用探针。

`ResourceReceipt.payload()`形状严格匹配141，但本库不发送ResourceAck，也没有wire header/E1/E2。资源文件完成不代表41/42已激活、模型已CONFIGURED或消费者已读取。当前实际UDP对34仍RECEIVED后FAILED/TARGET_MISSING，Capabilities仍仅ID1，无APPLIED/CONSUMED/ready提升。

下一共用包必须加入独立低优先级后台服务、20Mbit/s完整线上预算/发送互斥、有界任务与会话取消、141关联及真实阶段缓存、最终commit10000ms等待，并接25命令的既有管理资源接口；不能直接在实时receive/poll内同步做文件写入/整文件解析。PROTOCOL/SCENARIO/HISTORY三类输入源及原六工具链的完整解析/编排仍要继续，这三类源不能与本库的五类ResourceChunk内容混称“已全部实现”。Linux移交始终在单一台账中追加。

## W3.2 Standard Background Resource Service

W3.2完成W3.1中后台线程、预算、标准34/141和最终等待这部分后续工作；25命令资源管理入口、完整内容语义、激活和三类源/工具执行仍未完成。使用同一实际注册表安装服务，不建立第二模型/授权域：

```python
from icd_gateway.resources import ResourceStore
from icd_gateway.resource_worker import ResourceWorker
from icd_gateway.receiver import Receiver

store = ResourceStore(contract, dedicated_resource_root)
worker = ResourceWorker(contract, registry, store)
receiver = Receiver(contract, registry, resource_worker=worker)
# Pass receiver to the existing UDPGateway with explicit authorized feedback routes.
```

`dedicated_resource_root`须为本服务专用目录。当前CLI不自动启用存储，不把空路径或库存在当能力。worker启动后独占Store文件操作，主线程不能再调用accept/resolve/drain绕过它；后续真实解析/激活服务须通过同一有界后台所有者扩展，不能从实时模型线程读文件或重建worker绕过额度。一个注册表/存储器只有一次worker生命周期。

主线程完成实际ACL、完整Schema、角色/模型和原admission检查后，将规范原请求及实际binding送入worker。64个任务/结果共用预约、最多4MiB原请求，不覆盖。提交时先检查预算、结果容量和64个待终态反馈pin，再claim并固定RECEIVED；同SID/序号重试只返回原前缀或前缀+实际141，不入第二次队列、不重复写入。不同原内容仍DUPLICATE。普通终态不允许追加；仅34的受控异步反馈可追加一次，141严格关联SID/transaction/hash、实际进度和complete关系，没有私有字段或模型探针。

冻结契约要求MODEL下载前停止并核对实际模型契约，TERRAIN提交须实际STOPPED/PAUSED。当前没有真实模型状态/契约消费者，因此worker对这两种标准34请求在claim、预约、入队及文件I/O前明确TARGET_MISSING；入口返回RECEIVED后FAILED，不发送存储完成141。不会用SessionOpen、静止的接口step0、调用者自报状态或专用暂存目录推断这些条件成立。存储基础库五种字节能力不等同五种线上提交已完整就绪；VIDEO可后台预载字节，OBSTACLES/MISSION存储后仍须真实激活/业务消费者验证。Capabilities的34表示安装了有界存储服务，模型/初始化/替换ready仍false，不能据此开启受限种类。

worker仅做真实文件写入/读取/校验。非末块写入开始和完成按原1000ms；末块须1000ms内开始、10000ms内结束，pin最多保留至原最终期限，普通已结束反馈再保留5s。原资源结果的实际完成时间独立保存；过期、撤权或发布太晚不能发送成功。资源pin和请求重试不续会话，调用者须显式维护新心跳及真实sender_step。源对象收反馈仍串行，只有一个未完成request；它不会在等待中自动发心跳或生成模型时间。

`UDPGateway.poll()`在空闲及入站前收集已完成结果，发往原授权反向路由。`Receiver.resource_feedback(now_ns=...)`生成标准141，另存不可变`ResourceRecord(outcome,reply_bytes,error)`直到`drain_resource_records()`；默认64记录，可降低不扩大。记录满时不取走worker结果，也不删除原请求；恢复drain后再收集，若期间超过期限则只保留本地失败记录，不发迟到成功。网络发送失败也保留原终态缓存/本地记录供批准重试，不表示已送达。维护、存储中止和关闭记录分别有界，调用者须持续drain和持久记录；本批不是完整原始TX/RX证据包。

SessionRegistry到期/revoke/retire立即取消对应worker SID；后台在边界清理其未完成暂存，不删除其他会话或已完成未激活对象。写入途中取消不会强杀线程，完成结果不能伪装有效会话成功。超时只中止该SID拥有的该SHA，不因同hash的他人过期请求终止服务或清掉实际拥有者。`drain_abort_records(timeout=...)`超时后保留同一排空命令，允许重试取回原记录，不创建无界命令队列。

`Receiver.close()`实际等待worker终止；join超时明确失败并允许再次close，不声称线程已停。`ShutdownResult.resource_shutdown`保留原任务结果、中止记录和error；清理失败另存`unfinished_resources`的原请求和已写字节，保留lock及未知文件待显式恢复，不把它们说成已清理。取走正常中止记录不清掉未完成清理记录。已显式drain的ResourceRecord由调用者保存，不会在shutdown里重复生成。37/38仍缺完整消费者，不因本地取消能力提前返回业务清理成功。

源34按每个实际UDP包计算20Mbit/s上限，包括IPv4/UDP、Ethernet/FCS/preamble/IFG，无初始突发；使用各平台共同的高分辨单调计时进行本地pacing。100ms UDP重组期限不变，宿主调度使分片超时则明确失败；不靠扩大ICD计时绕过。worker另有同上限后台预约，不能把它说成实时优先级已部署。额外VLAN/隧道开销、总链路并发/RT优先级和物理发送时间必须在Linux按实际部署核算；Python sleep结果不是1ms或80ms实时资格。

76,800字节VIDEO真实UDP多块上传、实际文件/hash、空闲反馈、重复/错hash/容量拒绝、撤权与阻塞I/O、清理失败保留已有中止及未完成原请求均有测试。底层MODEL/VIDEO仍OPAQUE_BYTES，线上MODEL/TERRAIN缺真实门禁即拒绝；存储complete不是41/42激活、CONFIGURED/APPLIED/CONSUMED或ABI/codec ready。默认负例继续测试34没有worker时FAILED/TARGET_MISSING；独立发送CLI收到141非OK资源错误以BUSINESS_FAILED/exit1结束，不以报文到达当业务成功。原六工具、三类源和Linux目标条件继续按整体41项与唯一台账推进。

## Original Native Observation Recording

The existing recorder can explicitly retain the original CAN/Scapy observations alongside SOURCE/DISPATCH/INBOX:

```python
from input_simulator.evidence_recorder import ObservationRecorder, read_observation_chain

recorder = ObservationRecorder(
    dispatcher, new_recording_directory, run_id=run_id,
    native=True, coordinator=actual_native_coordinator,
)
recorder.flush()  # One bounded detached snapshot; actual disk IO is in the existing worker.
committed = recorder.poll()  # False while that same worker is live.
closeout = recorder.close(timeout=5)
chain = read_observation_chain(new_recording_directory, contract)
```

For a standalone actual ScapySource, omit coordinator; for CAN, supply its original same-session NativeToolCoordinator. No alternate transport or backend is opened. Native SEGMENT_2/CHAIN_LINK_2/CLOSE_2 retains all five streams; native=False keeps the legacy format and CAN fail-closed behavior. `prepare_native_evidence_archive` provides a non-draining standalone snapshot through the same owner checks. Native rows retain original immutable bytes, frame flags, channels/interfaces, decimal uint64 times, failures and exact IEEE754 timestamp bits (including failed NaN metadata and negative zero).

One background save may be in flight. Only verified persistent readback permits atomic record-prefix reclamation, independently per CAN sender; ongoing sends and newly appended observations remain intact. Pending input/feedback contexts, reservations, sequence floors, control/session leases and device handles are not reclaimed. All side record drains are blocked until recorder detachment. A busy/replaced owner, capacity exhaustion or disk/readback failure is explicit, never a successful fallback. `close` waits for the original worker and saves a local checkpoint; it does not flush unsaved tail records automatically, close the native tools, or perform remote cleanup. Check `closeout.error` and all five `unpersisted_counts` explicitly.

This is original observation persistence, not the full Run/Report. Scenario/service/action/cleanup records and terminal assertions still require integration; execution_ready/evidence_complete remain false and qualification_status remains NOT_EVALUATED. Library VirtualBus, Scapy frame-sink and protocol peers do not qualify SocketCAN, physical Ethernet, actual C model consumers, safety or RT. The ICD and all six original tool branches are unchanged.

## Original Scenario Observation Recording

Bind original scenario owners explicitly, in addition to the existing native owners:

```python
recorder = ObservationRecorder(
    dispatcher, new_recording_directory, run_id=run_id,
    native=True, coordinator=actual_native_coordinator,
    native_actions=original_native_actions, execution=original_scenario_execution,
)
```

`execution` is optional for a standalone original native action handler. When present, it must use the actual same-plan OriginalScenarioDriver and source, not an arbitrary record provider. Explicit SEGMENT/CHAIN_LINK/CLOSE_3 adds PLAN/NATIVE_ACTION/SCENARIO to the five native streams. Formats 1 and 2 are unchanged. The original plan bytes, source identity, model and granted SID are saved once; action/controller rows retain typed handles, original Header/request/reply bytes, errors and named cleanup progress. Finite action/controller histories remain in their original owners for handle/index semantics; identity cursors persist only unseen prefixes.

After disk readback, `poll()` may still return False if a pending original ETH action needs terminal feedback from the saved raw dispatcher prefix. Poll that original action/controller; then retry the same recorder job. Do not call flush again or substitute a completed action result. `close()` returns STATE without detaching when such a job is pending. Verified reclamation moves the native action anchors to the actual remaining raw records, so later original actions continue without treating legitimate persistence as an unauthorized drain. New partial PENDING cleanup receipts are recorded once per newly observed field set, with all nine possible increments reserved before execution.

This remains local observation persistence, not complete production services, actual model application, real cleanup qualification or the full Run/Report. Check all eight unpersisted counts and the close error. Additional service/assertion evidence and the unchanged-plan three-source end-to-end acceptances remain required; qualification flags stay false/NOT_EVALUATED.

## Original Replay Process Wiring

`input_simulator.replay_process.ReplayProcessRun` joins the original PreparedReplay, ReplayExporter, ToolCommandPlan, ChannelReservations and ProcessSupervisor. Supply the original export bindings/reservation and an explicit `ReplayProcessAuthority` bound to the actual same SourceSession. There is no production default authority: missing integration fails TARGET_MISSING before writing files or allocating children. An authority must establish actual endpoint/device, allocated headers/per-packet ordering, model/control targets, observations and stop readiness; validation returns None or raises, not a success boolean. No complete authority/service is currently installed.

The runner rebuilds the original export, checks exact persistent files/manifests and literal canplayer/tcpreplay flags, and rechecks source SID/model/grant/role/implemented messages and authority before launch and during polling. Configured absolute executable paths replace only argv[0]. One to four channels use the original source monotonic epoch and first-offset metadata; model steps are not inferred from elapsed time, and missed start windows fail LATE without catch-up. Poll the runner frequently enough for the configured finite start window.

Start is attempted once. Failure/stop retains all original child handles, bounded output, metadata and errors, continues stopping other children, and never releases the reservation or substitutes native send. Inspect the returned snapshot: stop-returned TIMEOUT and other errors remain FAILED. A failed Popen with no PID/readers has no nonexistent child to wait for, but retains its failure and original supervisor. Live children/readers still block close and require recovery using the same owner. LOCAL_EXITED is only local direct-child completion; it proves neither TX, APPLIED, per-packet global ordering nor process-tree/remote cleanup. All qualification flags remain false.

Windows tests separate actual ProcessSupervisor failure/timeout paths from explicit coordination doubles; Python used as a failing test executable is not an approved replay backend. Actual canplayer/tcpreplay, device timing, observed TX/feedback, repeat RESET/new SID/initial_inputs, full six-tool services and complete scenario/Run/Report integration remain required. See the original W3 plan and sole Linux backlog, not a separate Windows implementation.

## Original Status Assertion Recording

Pass `assertions=original_status_assertions` to the same native/scenario ObservationRecorder above. It requires the actual same-plan StatusScenarioAssertions, its original StatusObservationReader/source/contract, and the same service binding when `execution` is supplied. No arbitrary observation provider or successful default is installed. Explicit SEGMENT/CHAIN_LINK/CLOSE_4 adds STATUS_SAMPLE/STATUS_FAILURE/ASSERTION/ASSERTION_LIFECYCLE to the original eight streams; formats 1/2/3 remain unchanged.

Samples retain original correlated request/reply bytes, model/SID/step/sequence, medium/channel and lossless uint64 times. Comparisons retain original opaque handles and results. Each actual begin reserves bounded STARTED and RESULT metadata before allocation; only an actual terminal poll emits RESULT, once. Original handle/sample count limits remain, with at most two lifecycle rows per bounded handle and their byte reservation included. First sampling overflow is retained as BUFFER_FULL with original sequence/time; transport RX is not hidden.

The recorder pins original owner identities and takes the assertion handler lock before native/source locks. Snapshots call no runtime preflight, poll or getter, allocate no Header, renew no lease and drain no sample/handle history. Only unseen identity prefixes are saved after verified readback; ongoing samples/comparisons remain intact. While an explicitly bound recorder is attached to a live source, `reader.close()` fails STATE to prevent silent sampling loss. Detach the recorder first, or close the original source before post-close tail archival. Inspect all twelve closeout unpersisted counts and its error: close does not create terminal assertion results or finish remote cleanup.

This covers actual E1 Status scalar observations only, not actual C model getters/E2/E3 association, complete service evidence, full Run/Report, safety/RT or end-to-end acceptance. All qualification flags stay false/NOT_EVALUATED. Windows libpcap/SocketCAN limitations remain explicit, not an alternate backend.

## Current Development Ownership

Per the user's 2026-10-06 instruction, this thread continues PROTOCOL and SCENARIO only, plus required common ICD/ingress/services/evidence. HISTORY and original canplayer/tcpreplay replay development are owned by another developer. Existing code, tests, plans and logs are retained in place; the overall plan's latest scope section is the handoff index. SCENARIO REPLAY declarations and existing service boundaries stay unchanged: missing external service fails explicitly, not skip or native fallback. Handoff does not qualify the third path or erase its remaining gates.

## Original Negative Wire Preparation

`input_simulator.negative.prepare_negative_input(source, owned_input, event, enabled_cases=('T02',))` prepares the frozen NEGATIVE_SEND bytes only. Supply the original live SourceSession, its actually owned PreparedSourceInput and the exact legal Stimulus in the original Event. Explicit distinct enabled T02/T05/T06 cases are mandatory; this argument does not establish production run authorization. CANT/CUTIL/SAVVY retain CANFD, ETHGEN retains UDP. Replay branches are not handled here.

| Mutation | Frozen applicability |
|---|---|
| PATCH_VALUE | Unique JSON scalar/container or packed scalar/explicit array element; packed values must fit the original wire type |
| DROP_FIELD / ADD_UNKNOWN_FIELD | JSON structural deletion or new final dictionary key; packed layouts return UNSUPPORTED |
| F64_BITS | Original packed f64 scalar/array element, exactly eight little-endian bytes; JSON returns UNSUPPORTED |
| SEQUENCE_OVERRIDE / SESSION_OVERRIDE / TARGET_STEP_OVERRIDE | Original uint32 header field on every fragment |
| CRC_XOR | XOR the first original fragment's CRC byte only |
| TRUNCATE | Remove an explicit tail from the last original frame, leaving it nonempty |

Payload/header mutations use the original layouts, group limits and recomputed CRC. Only CRC_XOR/TRUNCATE deliberately preserve corruption. Structural paths use literal dictionaries/lists, never expressions; no-op changes, mismatched/forged/discarded input, stale grants, incompatible tool medium and excessive evidence bytes fail explicitly. Immutable original/mutated groups and event/header/payload bytes are retained. The helper takes no new sequence/transaction, sends nothing and renews no lease. `stored_bytes` includes both groups and finite metadata; callers must also reserve their aggregate runtime evidence budget before preparing/allocating inputs.

This is not a sender or a complete negative service. Before actual input allocation/TX, the production runtime still needs approved enabled-case/run authorization, actual model-step/control target approval and an actual must_not_apply reader/probe. It must use the original tool path and correlate the expected standard rejection, not infer success from a local codec error. Real Receiver integration tests show invalid packed payloads rejected before admission on UDP/CANFD. CRC corruption currently raises during decoding without a correlated ACK; absence of ACK/APPLIED is not no-write proof, and no fabricated ACK is added. The same boundary must be resolved for actual negative execution. `execution_ready` and `authorized_to_transmit` remain false; qualification stays NOT_EVALUATED. See the original W3 Task 3 and sole Linux backlog.

## Explicit Model-Backed Heartbeat Status

`icd_gateway.status_service.ModelStatusService(contract, registry, original_backend)` can be explicitly passed as `Receiver(..., status_service=service)`. The mandatory `ModelStatusBackend` is bound to the same verified contract and explicit supported models. Its `read_status(identity, now_ns=...)` must read an actual coherent model snapshot, not copy requested steps or manufacture lifecycle/phase/safety/counters. Return an immutable `ModelStatusSample(identity_json, payload_json, sampled_ns, deadline_ns)` with the complete twelve frozen Status fields and the actual authorized run context. Backend bytes are bounded at 4096 per identity/payload; uint64 times use the receiver's same monotonic clock domain. Cross-host times need actual approved synchronization, not direct subtraction.

No concrete C adapter/default model/test backend is installed in CLI. With no service, original capabilities, interface-origin opening step and Heartbeat TARGET_MISSING behavior remain. An installed service publishes only message 2 and consumer.Status for its supported models; unrelated model/initialization/phase-controller/replacement/channel qualifications stay false.

For an installed supported backend, SessionOpen first previews the original trusted identity/roles/nonce/retry/capacity rules without allocating a SID. The preview still performs original admission maintenance. A new opening reads and validates the complete actual snapshot under the same finite evidence reservation and completion clock as Heartbeat, then rechecks admission and allocates the SID at completion. SessionOpened receiver_step and Header target_step carry that snapshot's model_step and seed the same-SID model/time floor. Exact retries return the original cached grant with no resampling or lease renewal. Invalid context/types, expired snapshots/requests, getter failures and full pending retry storage cannot allocate a new SID. An attempted failed logical opening retains its original evidence/error and is not retried against the backend; a corrected operation requires a new nonce. SourceSession retains the opening floor but still requires a fresh actual Status for model-clock assertions. A new SID permits a new model epoch only with a genuine new snapshot; it does not prove RESET or initialize a model. Actual C integration, initialization and target epoch qualification remain required.

An original admitted Heartbeat obtains a standard 131 using the registry's original feedback sequence and request SID/transaction. Payload and Header target_step come from the actual snapshot. Snapshot context/types/half-open deadline/frozen 240ms age, actual post-read completion time, live original admission and same-SID model-step/sample-time floors are checked. Successful and exceptional reads both observe completion; expired grants cannot acquire a Status or stale failure ACK. Original receiver retry returns cached identical feedback without resampling/renewal; direct duplicate service calls fail. No APPLIED/E2/E3 is minted.

Finite record/byte reservation precedes the backend read. Immutable records retain request bytes, ingress/completion times, the original returned sample even on late rejection, reply bytes or failure code. Records are not evicted/drained automatically; BUFFER_FULL stops further reads. Original receiver/registry/backend replacement and reentrant close are refused before admission/destructive shutdown. Local service close retains records and does not stop the external backend or prove actuator/remote cleanup. This service history still needs complete Run/Report persistence integration.

Software tests use explicitly labeled model backend doubles through actual Receiver UDP/CANFD and actual UDP source/model-clock/Status-reader paths. These qualify the common response adapter only. Actual Linux C reads, full standard runtime services, 80ms system publication scheduling/target timing, applied control/configuration getters, all root/E2/E3 assertions, nine cleanup receipts and both owned end-to-end acceptances remain required. Missing fields/consumers must fail, never be synthesized from legacy command receipts or host elapsed time. Same common source and frozen ICD, no Windows-specific backend.

## Explicit Native Target Authorization

Create `RuntimeTargetAuthorizer(original_plan, original_source, actual_backend, ahead_steps=..., can_sender=original_selected_sender)` and explicitly bind it through `ScenarioRuntimeServices(..., targets=authorizer)`. The mandatory `RuntimeTargetBackend` must return a complete immutable `RuntimeTargetSample` containing exact identity bytes, actually applied frozen RunConfigure bytes, actual ModelView, actual registered producer and applied owner SID/lane/mode/control deadline. Times must use the original source's approved monotonic domain. No concrete backend, successful default or complete production services implementation is installed by the CLI.

Before reading, reserve finite retained record/byte capacity. Recheck original plan/source/backend/grant/Status after the getter, including exceptional completion time. Actual model/state/step/duration/configuration must agree; a current frozen target is used for PAUSED/CONFIGURED, explicit bounded lead for RUNNING. Original selected channels must be active. CONTROLLER inputs require the unique actual registered producer to be this source, matching applied configuration/owner and a fresh original standard-feedback control lease. A control_source string or Heartbeat alone is never sufficient. Original local periodic stop allocates no input.

An explicitly bound driver pins/rechecks the selected CAN sender and carries the original immutable approval, Status and control-lease objects to allocation and every native fragment. A single source scope lock protects allocation, while at most 4096 retained allocated approval entries protect delayed fragments/retries after the scope ends; capacity is checked before counters advance and entries are not automatically discarded. No new read or lease renewal is performed at these boundaries. Expiry/change before allocation consumes no counter; expiry afterwards retains the allocated sequence and actual failure, without TX or rollback. Existing unbound external-service paths remain legacy interface boundaries, not qualified defaults. These approval histories still require complete service evidence/RunReport persistence.

Software getter/capability doubles, Scapy socket peers, virtual CAN and actual session-registry tests verify common authorization behavior only. Actual coherent C configuration/model/control getters, receiver/source clock synchronization, lifecycle/nine cleanup, all assertions and complete production services/owned end-to-end acceptance remain unfinished. Qualification stays NOT_EVALUATED and execution_ready=false; third-path code and historical records remain unchanged.

## Original Lifecycle Approval And Epoch Retirement

For an explicitly installed target authorizer, Lifecycle 4 requires the published consumer.Lifecycle probe. Before allocation, the existing SemanticGuards.lifecycle validates the actual applied view and a source-owned non-allocating Header preview: expected state/transition, actual target/duration, offline STEP control-source NONE and physical-loop exclusion. The immutable LifecycleDecision is retained in RuntimeTargetRecord and checked again at allocation and fragments; STEP decision storage is included in finite record reservation. Whole-plan preflight checks declarations/capabilities without pretending future lifecycle states already exist. STOPPED permits valid lifecycle management only, not ordinary data.

An approved allocation requires the actual submitted stimulus to match the original action in canonical form; numeric representations such as 1 and 1.0 remain equivalent. Header-only allocation inside this explicit scope is refused. Lifecycle UDP/Scapy fragment bytes must also match the approved original encoding, preventing a substituted payload with the same Header. These checks read no backend, renew no lease and preserve failures/counters already allocated.

The original SourceSession feedback owner retains only the first correlated, published RESET/RESUME APPLIED/OK receipt as an immutable ModelEpochRetirement with full identity, original request/reply bytes, source-domain times and transport/channel. The old clock remains retired even after later Status; no same-SID resume or new default clock is created. OriginalScenarioDriver may finish only the exact native ETHGEN transaction with a matching retained COMPLETE dispatcher record and receipt, at its original sampled step. This consumes historical terminal evidence only, with no I/O, getter read, allocation or source/SID adoption. Other pending transactions and new actions remain stale; RECEIVED/VALIDATED or failed/unpublished feedback is not retirement proof.

The decision and terminal ACK do not execute or prove lifecycle effects. Actual C configuration/state getters, sequential 1ms STEP execution, safe outputs/control revocation/queue clearing, RESET initial_inputs restoration, genuine new-SID authorization and all nine cleanup receipts remain required. Complete runtime services and service-history Run/Report persistence remain unfinished. This common first-two-path increment does not change the third-path code or its historical verdicts; its development remains externally owned.

## Original Authorization And Epoch Recording

`ObservationRecorder(..., native=True, native_actions=original_actions, targets=original_authorizer)` explicitly binds the same original plan/source/contract and, when execution is provided, its installed original driver service. Local observation profile 5 has the original eight scenario streams plus TARGET_AUTHORIZATION/MODEL_EPOCH; adding the original assertions handler uses profile 6 with all fourteen streams. Existing formats 1/2/3/4 and the wire ICD remain unchanged. There is no automatic target backend or second writer.

The closed codec retains original successful/failed target observations, nested Status/action/applied configuration/view/registered producer/bindings/control lease/LifecycleDecision and the first actual correlated retiring ACK. Raw bytes use canonical base64 and uint64 times use decimal strings. Failed raw configuration bytes are retained without pretending to validate them. Contract-backed readback requires a successful controller action's original control lease, correlated owner/renewal request/replies, matching SID/model/source/lane/mode/producer and valid half-open deadlines. Standalone structural decoding is not contract-backed provenance verification.

The Source feedback owner transfers retirement only to the exact original allocated approval's authorizer; it retains that immutable receipt through Source close/cache clearing. Snapshots acquire original controller/action/assertion/target then native/source owners without calling getters, runtime polling or transmitting/allocating/renewing. One existing worker and verified readback advance saved identity-prefix cursors without draining target/epoch history. Reads during writing survive; write/readback failure retains original history. Close reports all unsaved counts and remains NOT_EVALUATED/evidence_complete=false. Receiver/other service histories, actual production effects and complete Run/Report remain required. This is common first-two-path work only; third-path implementation and historical artifacts are retained unchanged for the new owner.

## Explicit Configuration Consumer

`Receiver(..., configuration_service=ModelConfigurationService(contract, registry, actual_backend))` requires a mandatory same-contract `ModelConfigurationBackend`. There is no CLI/default backend or Windows-specific implementation. RunConfigure 3 retains its frozen UDP-only transport. For installed supported models, only its consumer capability/probe is added; initialization/system/safety/RT/replacement qualification remains false and NOT_EVALUATED.

`read_context(identity, request_json, *, now_ns)` receives the complete canonical original request before effects. Resolve that request's terrain hash at its initial point using its origin/frame, not the previously applied terrain. Return immutable `ModelConfigurationContext` retaining identity/request bytes, actual ModelView/ground and receiver-domain sample/deadline. Canonical request/identity correlation, strict bounded metadata and half-open freshness precede the existing semantic guard and queue/feedback capacity checks. Finite worst-case record reservation precedes even this read.

`apply_configuration(request_json, context, *, now_ns)` must own the actual atomic model safety boundary, recheck the supplied context, prepare all resources/model/initial values once, then obtain genuine readback. `ModelConfigurationReceipt` retains the original request, complete applied configuration, actual initial-state/input bytes, configured view/revision and times. Every frozen field, canonical equality and actual boundary must validate before standard consumer.RunConfigure APPLIED. Ordinary registry response recording still cannot forge APPLIED; only this original completed service operation can cache its validated reply pair.

Exact retries do not reread, rewrite or renew a session. Failed/late/mismatched results retain original bounded context/receipt/error/completion and write_attempted; failure is not proof of rollback or no effects. Local close retains history and does not stop the external backend or prove physical safety; preflight both installed status/configuration service locks before receiver shutdown. Complete service-history persistence and Run/Report remain open.

Tests explicitly use model doubles through real standard Receiver/UDP/SourceSession paths, not qualified C preparation/readback. Linux still needs actual resource/terrain parsing, complete model initialization/getters, atomic safety handling, clock-domain integration, failure-after-write recovery and target validation. This increment serves only PROTOCOL/SCENARIO common needs. HISTORY/capture/replay/export/process and historical artifacts remain preserved for their external developer.

## Local Run Session Retirement

`SessionRegistry.run_session_ids(origin_session_id, *, now_ns)` resolves the original trusted run/vehicle/scenario/model/definition context across source IDs, including retained matching expired actors. The origin must still be live. Selection does not allocate, renew, expire unrelated sessions or adopt a later SID.

`Receiver.retire_run(origin_session_id, *, now_ns)` is a serial-owner administrative prerequisite, not a Lifecycle 4 consumer. It reserves finite history/byte/input capacity before deleting anything, captures original queued inputs and reassembly fragment pieces, then retires only the selected old sessions through the existing path. Pin/check the original registry, queue, reassembler and actual attached resource worker before effects and each actor; wrong, unavailable or replaced owners fail explicitly. During the operation, ingress, maintenance, independent retirement, record drains and receiver close are rejected. Only the single original selected per-session operation receives a one-use permit.

Immutable `RunRetirement` retains full origin identity, observation time, selected/actually retired SIDs, captured/actually discarded inputs/groups and partial errors. `observed_ns` precedes cleanup; it is not a completion timestamp or RT measurement. An exact local historical retry returns the original record without repeating cleanup or adopting new sessions. Partial failure is retained, not rolled back or automatically retried. History survives receiver close; capacity exhaustion never evicts evidence.

The model step and unrelated same-model runs stay unchanged. Resource cancellation only signals the original storage worker: actual abort/unfinished-resource records must separately establish file cleanup. This operation creates no new SID, APPLIED reply, model reset, control-safe output or physical-safety proof. Actual lifecycle effects/readback, C queue epoch handling, conflicting foreign-run ownership, all nine cleanup receipts, new-SID integration and service-history Run/Report persistence remain required. Qualification stays NOT_EVALUATED and execution_ready=false.

Current fixed-source verification passed 460 tests in 23 related nonempty suites, including 21 new retirement tests; it was not a full-gateway script run. The 158 source hashes and 20 retained third-path hashes were unchanged. Evidence is in `artifacts/icd_gateway/w3-26-task2-run-retirement-progress.json` and its regression log. Subsequent development remains PROTOCOL/SCENARIO plus necessary common logic; existing third-path code, tests, resources and historical records remain for its external owner.

## Explicit Lifecycle Consumer

Install `ModelLifecycleService(contract, registry, actual_backend)` explicitly through `Receiver.lifecycle_service`. The mandatory `ModelLifecycleBackend` reads a coherent complete applied configuration, State132 and all applied inputs, then owns the atomic actual model boundary for one frozen Lifecycle action. No default/CLI/Windows model backend is installed. Lifecycle 4 remains UDP-only; the consumer probe does not confer model, hardware, real-time or replacement qualification.

Immutable bounded context/receipt records retain original identity/request, actual view, configuration/state/inputs, actuator values, owner SID, C receive-queue depth, revision and receiver-domain times. Every action validates complete actuator readback; only safety actions require zero outputs and revoked control. RESET must restore the full configured initial state/inputs, RESUME must preserve paused state/inputs, and STEP needs every sequential 1000us solver-step observation, not host sleep or a single larger step. The backend must additionally preserve the full internal solver state; State132 is only its frozen projection.

Reserve finite history and original terminal ACK sequence before effects. Pin original local owners, reject a foreign run on the same global model, capture original pending inputs/fragments and verify their actual removal before APPLIED. RESET/RESUME retire all old group SIDs before caching the narrowly owned original reply; old network retries remain invalid. Exact live retries do not reread/rewrite/renew. Partial effects and failed readback retain original evidence without inferred rollback or automatic retry. Receiver ingress, maintenance, retirement, drains and close cannot reenter the active consumer. Close retains history and is not remote cleanup.

Final fixed-source verification passed 488 tests in 24 related nonempty suites, including 28 lifecycle tests and real local UDP SourceSession RESET/RESUME retirement followed by explicit abandon/open with a new SID/current model step. Model backends are labelled doubles, not C/hardware qualification. This batch did not run the full gateway suite. Evidence: `artifacts/icd_gateway/w3-26-task2-lifecycle-service-progress.json` and its regression log. All 160 source pins, 20 retained third-path pins and original ledger prefix were checked. Production C effects/getters, nine cleanup consumers, complete ScenarioRuntimeServices, service-history persistence, Run/Report and first-two-path acceptance remain open. At the user's request, development pauses after this batch; resume only PROTOCOL/SCENARIO and necessary common logic, preserving third-path work for its external owner.
