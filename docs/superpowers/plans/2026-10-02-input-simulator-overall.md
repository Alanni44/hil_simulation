# 3.3 Input Simulator Overall Development Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan milestone-by-milestone. Steps use checkbox (`- [ ]`) syntax for tracking. This is an overall plan; create and review a focused implementation plan for each milestone before editing its business code. No subagents or commits are authorized by this plan alone.

**Goal:** 实现开发阶段3.3输入模拟器和3.6标准接入，以同一正式ICD覆盖必选业务，最终用同一3.6发布包接受真实3.3，仅通过批准的部署与授权配置切换。

**Architecture:** 在现有HIL仓库增量实现独立模拟器和独立的3.6标准接入服务，复用共同ICD运行库。原工具通过各自正式通道收发，场景调度只负责授权、编排与记录，不强制汇聚转发全部报文字节。3.6完成统一解析、验证、冻结映射和实际应用证据；模拟器与真实3.3均经过该路径。

**Tech Stack:** 现有C实时核心、Ubuntu RT目标环境、MATLAB R2018b模型工具链、Python服务与unittest；新增模拟器和ICD服务使用独立Python 3.12运行时，按需锁定cantools、python-can和原工具依赖。不覆盖现有Python 3.6.9环境，不默认启用所有工具。

## Global Constraints

- 设计依据为V1.4《3.6系统输入数据模拟与3.3替代方案 原工具链保留与选型评估版》，尤其第4.7、8、9.15、9.16及10章。
- 保留六条工具分支和Robot Framework职责；原工具可保留、限用途或在缺口得到证明后替换。
- 协议定义、场景脚本、历史记录是输入资源，不是三种固定线上报文。canplayer消费CAN日志，tcpreplay消费批准的PCAP。
- 同一正式ICD、同一接收路径、同一业务规则；不增加mock/real业务分支或模拟器专用模型写入口。
- 现有UE4 V2/V3、MAVLink和本地UDP命令接口分别保留原职责，不自动认定为3.3与3.6正式ICD。
- 正式传输、消息、周期、鉴权、反馈、CRC、会话、重组和同步均按逐消息适用性实现；不预设全部消息采用UDP、TCP或SOME/IP。
- 外部协议到模型的映射属于3.6开发工作，须在发布冻结前完成；未来替换时不新增映射或转换器。
- 接收成功不等于输入已应用，输入应用不等于模型结果正确；三者分别留下证据和判定。
- 硬件选型讨论暂不展开，软件开发不依赖其结论；实体验证门禁保留，不能以vcan或普通网口结果代替。
- 当前共同业务定义已由本项目确定为HIL-ICD-1.0，阅读入口为docs/interfaces中的完整接口单文件汇总，程序使用的v0.3契约、业务Schema、ICD目录和基线指纹收拢于docs/interfaces/baseline，不再等待未来3.3提供参数。AUTHOR_DEFINED_DESIGN不等于实现、实机资格确认或正式发布；这些验收仍不得提前通过。
- 不改动用户已有无关变更；不覆盖既有模型、GitLab发布与渲染链路。
- 用户2026-10-03要求每阶段向`linux-development-backlog.md`追加Linux移交和共用缺口；该文件逐项覆盖本计划41条M0-M7任务。收尾执行责任矩阵及目标证据守护，禁止以当前宿主通过删除Linux/实体/真实3.3门禁。

## Scope And Assumptions

### 2026-10-07 最新收发目标覆盖

用户已恢复开发并收紧当前目标：模拟器自产数据，经各自原工具链和冻结ICD到3.6标准接入实收、解码并留下收发记录。本节优先于下文历史中“完成完整原W3后再自生数据”的顺序及20至33工作日估算；撤回该估算对当前收发目标的适用性，不删除历史记录。W4/W5、硬件采集、实际模型效果、完整断言、九项远端清理、完整RunReport与正式替换资格保留但不作为本轮前置。

本批负责PROTOCOL与SCENARIO以及必要共用接收/会话/日志。新增显式ReceptionService、同Receiver的SocketCAN适配及原CANT/Scapy生成发送入口；默认接入行为保持，接收验证仅E1/probe0，不能以VALIDATED当模型应用。完整ScenarioSource不缺字段：root assertions保留且NOT_EVALUATED，非发送事件缺对应真实服务时明确TARGET_MISSING，未改冻结定义。具体源码/测试结果、原工具库级联调与失败尾部留存集中`artifacts/icd_gateway/reception-transmission-progress.json`，操作入口见`icd_gateway/README.md`。

HISTORY由外部人员继续开发，其旧代码/资源/测试/历史记录和REPLAY边界保留。当前库级原CANT/Scapy路径可生成并被共用Receiver接收，但Windows VirtualBus/测试NIC中继不是Linux SocketCAN、真实以太网或目标3.6实机通过；三条目标链路仍待Linux原生联调与第三条外部交付，不更新原正式验收0/2、历史0/3。原41责任和17未执行Linux门禁保持，剩余收发补全与历史全面验收分开登记，不能把任务重新扩成完整W3。

### 2026-10-06 最新开发责任调整

2026-10-07 本轮在途收尾：原W3 Task 2增加前两条共用的运行会话分组退休，以完整可信上下文定位所有旧来源/控制者，删除前有限保留原队列输入与分片，隔离其他运行。重入和错误资源线程绑定两处重要问题已复现并修正，部分失败留存、旧操作不重启、不接管新SID；不改变模型步，不发APPLIED、不代替实际RESET/RESUME。固定158源码下460项/23相关非空套件通过，第三条20个留存hash一致。结果与Linux实际C epoch/九项清理/新SID等要求追加原W3计划和唯一台账，不关闭W3或Tasks 2/3/4，不提升两链0/2、历史0/3或17个Linux门禁。本轮后只开发PROTOCOL、SCENARIO与必要公共逻辑；第三条后续由接手人员开发，既有代码、测试、资源、方案和历史记录原位保留供查阅，REPLAY服务边界不删，缺实际外部服务仍TARGET_MISSING。

2026-10-07 再次确认责任范围：本轮后只继续 PROTOCOL、SCENARIO 及其必要共同逻辑；第三条全部既有内容继续留存，后续开发由接手人员负责。本批补齐显式 RunConfigure 公共接收适配，强制后端先读取本次请求的真实安全/地形上下文，写后完整配置、初始状态及全部 initial_inputs 读回一致才发标准 APPLIED；不装成功默认后端，不改冻结 ICD 或 C。最终容量/类型封边后，固定157源码的290项/16相关套件通过；之前完整1209项为封边前源码历史，不冒称最终全gateway。第三条20个留存hash均未变；Linux实际模型、资源/地形解析、初始化/原子安全写入/真实读回仍须目标开发与验证。原Tasks 2/3/4、九项清理、完整服务/报告和两链端到端继续未完，0/2、历史0/3、17个Linux门禁不提升。结果及新增Linux要求集中原W3计划和唯一台账。

2026-10-07 本批仅推进前两条共用证据归档：原 ObservationRecorder 显式固定同计划目标授权器，以本地格式5/6保存完整成功/失败授权及首个原模型会话退休收据，原格式1至4和线上ICD不变。成功控制输入的原租约、请求/回执关联与期限必须可核验，写盘期间新记录及写盘失败前原历史不丢失；源关闭后仍可归档首个退休收据。18项新增测试及573项相关回归通过，155固定源码与第三条20留存文件哈希未变；不是本版本全gateway回归或端到端完成。一次限定复核的租约校验不足已由反例RED/GREEN修正，Linux文件系统/并发/时序要求追加唯一台账。原W3 Tasks 2/3/4、完整生产服务/报告、实际模型与九项清理、前两条端到端仍未完成，当前负责0/2、整体历史0/3。第三条由接手人员开发，其代码/测试/资源/方案/历史证据保留，不改写历史结论。

本轮生命周期收尾已完成相关软件验证：前两条共用发送授权接入六种原生命周期规则、实际载荷与批准内容绑定、旧模型时钟退休原事务收尾。435项/21非空套件通过，153固定源hash及第三条20留存文件hash核对一致；此为相关回归，不把上一批1149完整回归结果复用于新源码。实际模型效果、九项清理、完整服务/报告和前两条端到端仍未完成。后续只开发前两条及必要公共逻辑，第三条代码/测试/资源/历史记录原位保留，待接手人员查阅；本批结果与Linux追加集中原W3.26 Task 2和唯一台账。

用户已明确第三条链路由别人接手。本轮在途工作收尾后，本线程只继续第一条 PROTOCOL（协议定义）与第二条 SCENARIO（场景脚本）的开发，以及二者必需的共同 ICD、标准接收、授权、模型读取、反馈、清理与报告逻辑。第三条 HISTORY（历史记录/回放）的后续实现和目标验证交由接手人员；这条最新责任约定优先于下文历史记录中的“继续完整回放”安排。

- 保留第三条现有源码、测试、资源、方案、验证 JSON 和原日志，不删除、不回滚、不改写其历史结论，不冒称整条完成或已通过验收。
- 保留 `capture.py`、`_capture_envelopes.py`、`history.py`、`replay.py`、`replay_export.py`、`replay_process.py` 及 canplayer/tcpreplay 原参数与工具分支。共同 `tool_commands.py`/`tool_process.py` 中的回放职责也保持，后续不得为前两条开发顺手重构第三条实现。
- 查阅入口：原 W3.26 计划的 Task 3、唯一 Linux 台账的 W3.5/W3.6/W3.7/W3.10/W3.12/Task 3 进度，以及 `artifacts/icd_gateway/w3-26-task3-replay-process-progress.json` 和同名 regression.log；旧阶段的 `w3-5`/`w3-6`/`w3-7`/`w3-10`/`w3-12` 验证记录原位保留。
- SCENARIO 中的 REPLAY 事件及冻结输入定义不删除、不跳过、不改成 native 发送；其运行服务由第三条接手人员提供，经既有边界集成。未提供时明确 TARGET_MISSING，不能以测试替身或退出码代替实际回放证据。
- 两条当前负责链路的端到端验收仍为 0/2；整体三源历史验收仍为 0/3，第三条接手不等于通过。41 条原责任与 17 项未执行 Linux 门禁保留，通过追加交接说明调整执行者，不修改责任矩阵历史。
- 本轮证据接线先完成；后续优先前两条实际生产服务、目标读取/反馈与完整 Run/Report。自生数据配置仍按用户此前要求等待原任务完成，W4/W5 继续暂缓。下文旧单人工期为交接前估算，不作为调整责任后的个人剩余工期或固定交期。

2026-10-06 后续进度：前两条所需 NEGATIVE_SEND 的九种冻结报文变异已实现为共用构造依赖，165 项相关测试通过。仅保存合法原码与变异后码，不发送、不取得运行权限、不证明模型未写入；真实授权/目标 getter、原工具发送与拒绝关联仍须在原 W3 Tasks 2/3/4 完成。第三条 13 个源码/测试及 7 个历史报告/log 留存哈希一致，不继续开发回放。详见原 W3 Task 3 和唯一 Linux 台账本次追加；两链 0/2、整体 0/3 及原门禁不提升。

2026-10-06 接收服务进度：原 Receiver 已可显式绑定实际模型读取后端的共用 Heartbeat/Status 响应服务，338 项相关/完整协议库测试通过。默认命令行没有安装后端，不用宿主步数或旧回执补造 Status；测试读取后端明确为替身。完整 Linux C 后端/实际 opening step、系统发布调度、控制/生命周期/九项清理、完整报告和两链验收继续原 W3，不关闭阶段；唯一台账追加目标接入和时效/证据要求。

2026-10-06 本轮会话收尾：已安装支持模型的读取后端时，SessionOpened 从完整有效快照取得真实 receiver_step，不再固定为接口原点；读后复核、有限证据和新 SID 分配接同一公共服务，原 retry 不重采样。缓存占满失败无遗留 SID，失败开会话的原错误与读取记录保留。十四非空套件 348 项相关测试通过，一次限定复核无新的重要发现；第三条 20 个源码/测试/历史证据留存哈希一致。未安装后端仍不声明模型资格，真实 C 接入、完整运行服务/报告和两链端到端继续原 W3。本轮后只开发前两条及其必要共同逻辑，第三条后续回放由接手人员推进，原记录保留查阅。

2026-10-06 当前源码整体回归：实际执行原 scripts/test_icd_runtime.py，67 协议库、1021 网关、3 台账、4 汇总测试，以及 34 项既有静态回归，共 1129 项通过；150 个源码/测试/C/MATLAB 文件哈希在运行前后保持一致。第三条只参加兼容性测试，20 个留存文件仍未变，不继续其开发。冻结、离线编解码、依赖和编译检查通过，证据记录在原 W3.26 Task 4 与唯一 Linux 台账。本批仅补全当前版本的整体验证，不新增生产功能，不关闭 W3；后续继续前两条实际配置/授权/getter/生命周期/清理与完整报告接线，不以单元测试代替端到端或目标门禁。

本计划覆盖模拟器、正式接入、工具调用、场景、回放、证据、自动化及配置替换验证。不重新开发完整3.3综合测试平台、3.4监控平台、3.7管理平台、飞行动力学模型或UE4渲染系统。

2026-10-06 前两条目标授权接线：显式完整配置/模型视图/注册生产者/实际控制者读取已接到原驱动取号前；原来源、CAN绑定、Status与控制租约在取号及发送片段前继续复核，过期拒绝发送，保留已发生的分配与失败证据。真实读取后端、完整生产服务/清理/报告尚未完成，不用软件读取替身声明目标资格。一次限定复核的两处边界反例已修正，最终回归结果集中本批进度 JSON/log。第三条后续仍由别人推进，现有源码、测试及历史结论保留，前两条0/2与整体0/3不提升。

本批最终验证：原完整入口与既有静态回归共1149项/八个非空套件通过（67协议库、1041网关含20项新授权测试、3台账、4接口汇总及34静态）；152个固定源hash未变，第三条20个留存文件与原hash一致，冻结/离线/依赖/编译和原台账历史前缀守护通过。证据为 artifacts/icd_gateway/w3-26-task2-target-authorization-progress.json 及 regression.log；不是完整W3、真实模型或两链端到端通过，后续仍按原Task 2/3/4推进前两条实际服务接入。

视频注入、串口、AD/DA/IO属于独立接口验证范围。保留与现有能力衔接及测试接口；其实际驱动、接线、视频格式和同步指标需要明确后单独执行实体工作包，不能宣称CAN/以太网闭环已完成这些交付。

当前Windows只作为共用代码的开发与测试宿主，共同协议库、三类资源、场景/回放逻辑、管理API及UDP回环维持同一实现和同一业务路径；不要求先迁移系统。按2026-10-03用户要求，需要Linux的SocketCAN/vcan、原工具链、现有Linux C核心、实时模型及正式验收留待Linux或目标Ubuntu RT执行，不开发Windows专用替代后端，不默认购买、更换驱动或安装WSL。目标环境缺失时明确报告未执行，不通过伪造设备结果或静默跳过来获得通过。分阶段说明见docs/superpowers/specs/2026-10-02-windows-input-simulator-design.md。

## Existing Baseline

以下为2026-10-02静态代码核对结果，未在本次规划中运行目标环境验收。

| 现有能力 | 复用位置 | 复用边界 |
|---|---|---|
| 实时循环、模型输入、在线参数与生命周期 | `C:\Users\裴鹏飞\Desktop\hil_simulation\c_core\src\main_rt.c` | 复用实际写入点；现有延迟统计不足以自动证明每条正式消息已应用 |
| 控制源互斥与执行器超时保护 | `C:\Users\裴鹏飞\Desktop\hil_simulation\c_core\src\control_arbiter.c` | 按业务角色接入，不能以mock/real身份选择业务路径 |
| 本机命令和回执 | `C:\Users\裴鹏飞\Desktop\hil_simulation\python_services\core_client.py` | 复用语义及调用能力，作为3.6内部接口，不公开为冻结ICD |
| 模型契约、模型包、既有控制台 | `C:\Users\裴鹏飞\Desktop\hil_simulation\python_services\shared\model_package.py` 与 `C:\Users\裴鹏飞\Desktop\hil_simulation\web\hil_console.html` | 复用契约验证与管理能力，不为本项目重新建完整管理平台 |
| 虚拟飞控与传感器闭环 | `C:\Users\裴鹏飞\Desktop\hil_simulation\python_services\hil_adapters\virtual_quad_fc.py` | 回归验证资源，不等于3.3模拟器或正式接口 |
| 验收与环境指纹 | `C:\Users\裴鹏飞\Desktop\hil_simulation\scripts\run_week1_acceptance.py` 与 `C:\Users\裴鹏飞\Desktop\hil_simulation\scripts\environment_fingerprint.py` | 保持旧验收入口，新增独立3.3接口验收，不把旧报告当新证据 |

在运行代码与测试目录中未找到完整cantools/python-can/Scapy/Ostinato/canplayer/tcpreplay/Robot工具链接入实现，因此本项目不能按“仅补配置”估算。

## Approach

推荐增量开发模拟器与标准接入，并以最小端到端链路验证各里程碑。只开发模拟器、暂时直写本地命令更快，但不能证明未来替换；强制开发统一报文转发中心会改变原工具链且增加耦合，因此不采用这两种方式。

## Planned Ownership And Files

新增路径为计划中的模块归属，并非当前已实现文件。全部位于 `C:\Users\裴鹏飞\Desktop\hil_simulation`。

| 范围 | 计划路径 | 职责 |
|---|---|---|
| 共同ICD配置 | `C:\Users\裴鹏飞\Desktop\hil_simulation\config\icd\` | 示例/正式状态、消息覆盖、传输、黄金向量、冻结哈希；DBC或schema按实际接口采用 |
| 共同接口运行库 | `C:\Users\裴鹏飞\Desktop\hil_simulation\icd_runtime\` | 配置校验、正式编解码、逐消息验证；双方复用，不引入模拟专用字段 |
| 模拟器 | `C:\Users\裴鹏飞\Desktop\hil_simulation\input_simulator\` | 资源加载、场景状态机、发送授权、六类工具封装、反馈断言及记录 |
| 3.6正式接入服务 | `C:\Users\裴鹏飞\Desktop\hil_simulation\icd_gateway\` | 正式通道收发、校验、受控队列、模型/任务映射、ICD反馈及应用证据采集；随3.6发布冻结 |
| 场景与测试资源 | `C:\Users\裴鹏飞\Desktop\hil_simulation\scenarios\input_simulator\` 与 `C:\Users\裴鹏飞\Desktop\hil_simulation\tests\fixtures\input_simulator\` | 正常、边界、异常、回放及独立预期向量 |
| 新测试 | `C:\Users\裴鹏飞\Desktop\hil_simulation\tests\test_icd_*.py`、`C:\Users\裴鹏飞\Desktop\hil_simulation\tests\test_input_simulator_*.py`、`C:\Users\裴鹏飞\Desktop\hil_simulation\tests\c\test_input_evidence.c` | 单元、端到端、安全及实际应用证据验证 |
| 自动化与部署 | `C:\Users\裴鹏飞\Desktop\hil_simulation\automation\input_simulator\`、`C:\Users\裴鹏飞\Desktop\hil_simulation\deploy\systemd\` | Robot用例、独立进程部署、启动自检与停止清理 |

按实际需要修改现有C输入写入点、控制仲裁、内部通信、配置和验收脚本；不预先承诺必须修改所有现有文件。现代Python依赖只进入新服务独立锁定文件，不能直接追加到旧HIL的Python 3.6依赖环境。

## Milestones

2026-10-06本轮断言证据接线进度：原 ObservationRecorder 显式绑定实际同计划 StatusScenarioAssertions/StatusObservationReader，以 format 4 保存原采样、首个溢出、比较、STARTED/RESULT，旧格式1/2/3不变。原 handler/reader/计划/源身份及锁顺序固定，后台保存时采样与比较继续；身份游标只保存未落盘前缀，不清空原断言历史。每个 handle 两条生命周期元数据在 begin 前预留，终态实际 poll 后只记录一次，close 不制造结果，十二流未保存计数必须检查。等值计划替换与 live 记录期间 reader.close 静默停采两处反例均先 RED 后 GREEN。固定七源码/测试 hash 下十八非空套件 430 项通过；一条不存在套件的零测试命令被守护中止并原样留日志，随后真实套件在同源码完成，不计零测试通过。本轮独立复核因额度限制未执行，无复核通过结论；根代理已核查实际代码并运行回归。证据集中于 artifacts/icd_gateway/w3-26-task4-assertion-recording-progress.json 及同名 regression.log。仍仅 E1 Status 软件观测，不是完整生产服务、真实模型 E2/E3、九项清理或完整 Run/Report，原 W3 不关闭。Linux 要求追加唯一台账；本轮后按最新责任说明只推进 PROTOCOL/SCENARIO，第三条 HISTORY 代码/测试/记录留存供接手人员查阅。

2026-10-06本轮W3进度：原Task 3新增replay_process.py运行接线，复用原prepared/export/command/reservation与ProcessSupervisor，三种模式及canplayer/tcpreplay原参数保留。实际同源授权服务缺失即启动前拒绝；精确文件读回、当前grant/SID/型号/角色、通道起始偏移和迟到拒绝落实。停止返回错误丢失与未创建子进程永久待清理两处P2均RED/GREEN修正，同一原句柄保留、其他子进程继续停止，不释放预约或回退native。固定210相关测试在十个非空套件通过，3台账/4契约、14/663、59/72/85/800、pip/编译通过，证据见artifacts/icd_gateway/w3-26-task3-replay-process-progress.json。Windows协调替身与实际子进程失败/超时测试分列，均不证明原Linux工具发包或实际模型应用。完整运行授权、逐包TX/序号/反馈、repeat/RESET/新SID/initial_inputs、负例/六工具服务及完整Run/Report仍未完成；原Task 2/3/4不关闭，三源验收0/3，自生数据配置仍待原W3完成。唯一Linux台账追加要求，不新建阶段编号或Windows版本。

2026-10-06最新W3进度：原场景记录接线已接入原ObservationRecorder，显式format 3保存计划/源身份/型号/SID、原生动作与控制器记录，保留原五流和旧格式1/2。原ETH终态未被动作消费时不回收、不发布close；真实动作消费后同一job提交并修正原记录锚点，后续动作继续原时间表。清理增量回执有界保留，计划替换在取号/TX前拒绝，必填标识null反例已RED/GREEN修正。固定最终322相关测试（13非空套件）、14源663引用、59/72/85/800离线、pip/编译通过，证据为artifacts/icd_gateway/w3-26-task4-scenario-recording-progress.json；日志第398行起才是最终验证，前321项为修正前历史。唯一Linux台账追加原场景/通道/反馈消费/落盘背压和RT要求，41责任/17未执行保持。此为原Task 4部分交付，不是新增阶段；生产服务、实际模型/控制/生命周期/九项清理、完整回放/负例/六工具运行、服务/断言流与完整Run/Report仍未完成，三源端到端0/3，原W3与Task 2/3/4不关闭。下一优先项是生产运行服务与完整回放执行，不恢复自生数据配置或W4/W5。

### M0 基线与接口工作清单

- [ ] 记录Git状态、目标工具链、旧测试结果与既有启动路径；保留未提交用户变更。
- [ ] 确认独立Python 3.12运行时在目标系统的可部署性和隔离方式；不可部署时先调整并验证新服务运行方案，不覆盖系统Python或擅自升级RT系统。
- [x] 已在v0.3建立45类输入、14类反馈、模型绑定、三类资源、六工具链及标书/方案覆盖对照；运行验证结果仍由后续里程碑产生。
- [x] 已将本项目确定的共同ICD、结构测试数据及内部接口区分；CAN ID、端口、周期和编码由v0.3明确给出，不再作为外部未确认参数。
- [ ] 为后续里程碑写聚焦实施任务及可执行测试，采用先失败测试、再实现、再回归的顺序。

**交付与门禁：** 基线记录、接口矩阵、模块边界和M1实施计划。v0.3提供当前消息实现依据，可先进入Windows可移植协议库任务；现有目标软件环境与全部M0事项未被本次文档更新标记为完成。供应方确认和硬件采购不是本里程碑的展开内容。

### M1 共同ICD配置与编解码

- [ ] 实现v0.3定义加载、四组件实际哈希指纹、设计/正式发布状态，以及基线文件缺失或不匹配时的启动拒绝。
- [ ] 按已提供消息实现编解码和合法性验证，覆盖布局、类型、范围、单位和适用校验。
- [x] 共用库已按现有独立黄金向量逐字节校核编码，不以同一编码器的往返测试代替外部符合性；真实3.3程序符合性仍未执行。
- [ ] 确认参数到模型契约的映射，未知字段拒绝，不覆盖模型解算输出。

**交付与门禁：** 可测试的共同ICD库、按既定v0.3编码实现的消息、模型映射及独立黄金向量。Windows软件通过只证明相应软件行为，不登记实物通道、真实模型应用或真实3.3符合性通过。

2026-10-03进展：W1已实现共用基线/Schema加载、载荷编解码、CAN FD/UDP/HIV1字节封装及有界重组，离线自检覆盖59类消息/72种业务传输组合/85条黄金测试片/800片RAW帧。50条W1测试、4条接口汇总测试与34条选定既有静态回归通过；复核发现的离线黄金集误报已用独立样本哈希与完整唯一覆盖校验修复。不创建Windows专用实现；`scripts/test_icd_runtime.py`为单一测试入口，限定范围记录在`artifacts/icd_runtime/w1-validation.json`。正式发布状态门禁、真实模型映射/消费者和Linux目标资格仍未完成，因此不能将整个M1/M2标为通过。实际冻结组件存放于`docs/interfaces/baseline`，不另复制一份到计划中的`config/icd`。

### M2 第一条端到端链路

- [ ] 交付模拟器与3.6接入服务的独立启动入口，建立有界队列及失败清理。
- [ ] 第一条共用软件通路使用既定UDP编码和当前宿主回环部署端点，不创建Windows专用实现；仍使用同一正式解析/校验路径。CAN在Linux使用vcan作软件验证，不将普通CAN或UDP包装成已通过CANFD实物链路。
- [ ] 贯通资源加载、发送、3.6标准接收、映射、C核心实际应用及规定反馈。
- [ ] 复用既有输入写入点证据；不足时在实际写入处增加有界证据通路，由非实时线程编码落盘。
- [ ] 验证合法输入、整组拒绝、未知字段和规定超时；每次运行都能追溯原始输入与实际应用。
- [ ] 对排队、合并或被覆盖的输入记录实际结果；不能将尚未写入模型的已接收请求标记为已应用，消息保留策略须符合该消息的正式规则。

**交付与门禁：** 第一条可重复端到端软件链。内存接收器或发送计数不作为C模型真实应用证明；C/模型环境不可用时门禁保持未通过。

2026-10-03 W2.1进展（属于前述M2的部分交付）：共用会话/授权/序列缓存、实际UDP和独立源/接入进程已验证；38条新增测试及标准36100/36101/36102实际回环通过。无模型消费者时只返回真实RECEIVED与FAILED，不生成APPLIED/CONSUMED；4096模型队列、目标步/控制权、生命周期、ClockSync/Status、资源/视频与正式发布门禁仍需下一共用工作包和Linux真实目标联调。本条不将M2任何完整端到端门禁勾选。移交台账已追加W2.1记录。

2026-10-03 W2.2进展（仍为M2部分交付）：同一共用代码新增97绑定结构门禁、13类根输入/参数映射与整组4096队列基础库；35条专项覆盖不可变值、单写者/别名/同目标冲突、原始admission/首次接收时间、顺序步/ahead/控制年龄、会话清理及注册表级单队列生命周期。队列尚未接网络/实际C消费者，不授予ControlOwner、不代替真实安全执行或完整逐消息业务校验；缺模型消费者时网关仍明确FAILED，能力仅ID1。L-004/L-010实际模型映射、C步边界与安全移交已追加同一Linux台账；共用生命周期/消费者/证据、W3/W4继续开发，没有勾选完整M1/M2。

2026-10-03 W2.3进展（仍为M2部分交付）：共用生命周期、ControlOwner和完整初始快照语义门禁已实现，23条专项覆盖状态矩阵、冻结/运行目标步、顺序STEP、生产者角色/源/通道、控制安全零、四元数/地形/airborne和三模型初始化。返回不可变决策，不执行模型、不生成APPLIED或实际Status。L-004初始化/资源关联及L-010现有C生命周期、单槽覆盖、控制切换和超时差异已追加同一Linux台账；真实消费者接入/效果/证据和后续共用W3/W4保持未完成，未勾选整体里程碑。

2026-10-03 W2.4进展（仍为M2部分交付）：同一共用接入新增指定会话退休、空闲模型队列/分片清理、有界可排空维护与shutdown原记录、全部参与者clock/容量预检及永久注册表关闭；完整九项清理决策区分37目标步与38服务边界。自动receive/UDPpoll不会丢原拒绝，时钟/缓冲预检失败不先删除。实际九项模型/设备/工具安全执行及可靠最终关闭反馈仍未接通，网关37/38明确FAILED、能力仅ID1；L-004/L-010/L-012/L-017移交已追加同一台账。完整M2及后续共用资源/消费者/证据/API工作均未勾选。

### M3 六条原工具链与反馈采集

2026-10-06 W3.26 Task 4原观测持续落盘进度：原归档/记录器已明确支持SOURCE/DISPATCH/INBOX/CAN/L2五流，保留旧三流SEGMENT/CHAIN_LINK/CLOSE_1默认；native=True复用原后台线程、实际原owner和一至四CAN sender/Scapy transport，不开另一个后端或改ICD。原字节/失败/帧标志/接口/uint64时刻/IEEE时间戳位串可读回；写盘期间收发继续，读回和所有原流身份/字节校验成功才按每个CAN sender回收原保存前缀，不动pending/context/计数/租期。四CAN追加排序误判已RED/GREEN修正并限定复核关闭，替换sender/binding不能漏记录或TX；五流同一实际CAN/Scapy动作与反馈、两段持久化、失败保留、关闭后末尾保存均有库/帧sink软件证据。固定最终298相关测试（12非空套件）和3台账/4汇总、14源663引用、59/72/85/800离线、pip/编译通过，当前hash/日志范围见artifacts/icd_gateway/w3-26-task4-native-recording-progress.json；预修正296结果保留在同一日志前缀，不当最终证据。唯一Linux台账追加原设备、文件系统/磁盘背压/实时负载验证，41责任/17未执行保持。原scenario/service/action/cleanup流、完整Run/Report、生产运行服务/模型应用和三源软件验收仍未完成，端到端0/3，Task 2/3/4及原W3保持开放，不提前恢复自生数据配置或W4/W5，不将当前库级路径当实体/安全/RT资格。

2026-10-06 W3.26 Task 2配置生产者进度：接收端registered_controller从实际完整grant及已开立、未到期会话解析唯一CONTROLLER SID，保留实际角色/身份/链路/nonce/会话期限；不以STIMULUS选择者或配置角色替代已授予角色。external_control_owner检查原6 admission、同run/vehicle/scenario/model/version，保留原源/lane/PAUSED/target/100ms规则。observe_admitted不触发维护，快照链路重建为冻结副本；维护副作用和list别名两个P2先RED后GREEN，限定复核关闭。固定184针对性测试及14源663引用、59/72/85/800离线、pip/编译通过；空test_config发现不计，随后真实UDP与剩余套件通过，日志与当前hash见artifacts/icd_gateway/w3-26-task2-producer-progress.json。唯一Linux台账追加实际集成门禁，41责任/17未执行保持。该解析不是已应用控制状态、安全值、控制续租或完整生产服务；实际配置/model getter、运行服务、九项清理、完整回放/负例/六工具和持续报告/三源验收继续原W3，三源端到端仍0/3，不提前恢复新发生器或关闭W3。

2026-10-06 W3.26 Task 2断言进度：同一SourceSession实际标准反馈已接StatusObservationReader，保存全部新鲜相关131的原请求/回执、SID/型号/模型步/序号、通道和时刻；StatusScenarioAssertions执行E1 Status根及事件WAIT/ASSERT，经原ScenarioRuntimeServices边界调用，覆盖12冻结字段和八算子。连续采样不跳过中间失败，旧采样/重复poll不计数，过期/跨身份/缺探针/缺reader明确拒绝；有限历史溢出保留已知前缀，新增句柄同时检查历史总容量。该容量缺陷先RED后GREEN，限定只读复核关闭。固定版189针对性测试通过，14源663引用、59/72/85/800离线向量、pip及编译通过；本次不声称完整回归，921属于上一控制观察版本。证据artifacts/icd_gateway/w3-26-task2-assertions-progress.json；唯一Linux台账追加实际采样/消费者/时序要求，41责任和17未执行门禁保持。模型内部getter、E2/E3真实140关联、实际配置生产者授权、生命周期和九项清理仍须共同开发，不关闭Task 2或W3，三源端到端仍为0/3；不提前恢复新发生器，不改原工具/C/线上接口，不产生Windows分支。

2026-10-05 W3.26 Task 2进度：原SourceSession标准反馈入口已接有限ControlOwner租约观察，共用CAN/UDP路径保留原请求/回执与首次TX起算100ms期限，Heartbeat及环境输入不续控制租约。新增授予尝试、安全生命周期、权限失败及任何新鲜相关Status的换源/安全/状态冲突永久撤销观察；待授予ACK、早发Heartbeat晚回和未更新模型步缓存的告警不能恢复旧权限。实际UDP交错四项先RED后修复，最终28专项20.471s及固定源码921共用回归（67协议/847网关577.233s/3台账/4汇总）、14源663引用、59/72/85/800向量、依赖/编译通过，复核无剩余重要scoped发现。证据见artifacts/icd_gateway/w3-26-task2-progress.json。该观察不是唯一实际生产者SID授权；实际getter/运行服务/生命周期/九项清理仍属Task 2，完整回放/负例/六工具及持续Run/Report/三源验收仍属Tasks 3、4，不关闭W3或提前恢复新增发生器；原C、ICD、六工具与单代码不变。

2026-10-03 W3.1进展（M2资源加载和M4资源/磁盘门限的共用基础部分）：新增实际ResourceChunk文件存储库，包含五类资源原始字节分块/整体hash、连续偏移、末块、重复/声明/会话冲突、有界容量/原请求/中止记录、专用root/lock/暂存、原子发布与重启/读取时真实校验。地形、障碍物、任务采用冻结内容Schema及本地不变量，模型/视频仅完整字节。尚未接入标准UDP/管理API后台服务，不提升Capabilities，不发送141或应用反馈；20Mbit/s后台预算、10000ms commit、取消/阶段反馈、真实激活和PROTOCOL/SCENARIO/HISTORY及六工具链仍须共用后续包。Linux文件系统/权限/磁盘/崩溃及实际资源消费者资格要求已追加同一台账；独立复核中断，完整复核门禁未关闭。没有勾选完整M2/M3/M4/W3或真实替换。

2026-10-03 W3.2进展（仍为M2/M4共用资源服务部分）：同一注册表安装实际有界文件worker，主线程只管标准34 admission/反馈，后台真实写入与校验；64任务/结果、4MiB原请求、64待反馈pin/记录、原RECEIVED加实际141、固定1s/10s期限、SID/txn/hash关联、源实际分片20Mbit/s节流和最多3次原码重试后的最终等待均接通。76,800字节真实UDP上传通过专项测试；默认CLI无worker能力仍ID1，显式安装只增34，不宣告模型/视频/激活或替换ready。撤权/到期取消、超时SHA归属、原中止记录排空恢复及清理失败unfinished原请求保留已红绿修复；W3.1+W3.2独立只读复核完成，没有遗留重要发现。Linux实际文件系统/权限/崩溃恢复、优先级、物理链路预算/抖动、41/42真实激活追加同一台账。管理API25命令、三类源/原六工具、完整消费者/E1持久证据/同步与正式门禁仍须共用后续任务，不勾选完整M2/M3/M4/W3或任何Linux项。

W3.2收紧复核：上段的大文件UDP验证明确使用VIDEO后台字节预载，不是模型下载或视频解码。MODEL下载需要实际停止/模型契约验证，TERRAIN提交需要真实STOPPED/PAUSED；当前标准34缺少这两类实际门禁，在claim/入队/I/O前TARGET_MISSING，不用专用暂存或SessionOpen推断合法状态。底层五种资源存储不等于五种线上消费者就绪。独立CLI收到141资源非OK错误以失败退出，避免把网络收报当业务成功；上述共用缺口和目标门禁均仍保留。

- [ ] 信号链：cantools、python-can与SocketCAN/vcan，按正式DBC及目标后端校验。
- [ ] CAN工具链与GUI链：受控调用can-utils与SavvyCAN；观察默认不取得发送控制权。
- [ ] CAN回放链：检查日志格式、方向、通道及相对时序后调用canplayer。
- [ ] 以太网模拟链：保留Ostinato和Scapy，按消息验证正常构包及适用交互；不默认强制新建TCP客户端。
- [ ] PCAP回放链：批准预处理与方向筛选后调用tcpreplay；需要工具不具备的动态交互时拒绝或转已验证实现。
- [ ] 建立独立反馈采集器、工具进程状态、运行关联、发送互斥与停止清理。

**交付与门禁：** 六条分支均有支持范围与能力报告；未安装或不适用分支明确标记，不冒充验证通过。每条必选消息必须有可用分支覆盖，辅助工具不必参加每次验收。

### M4 场景、历史回放与安全

- [ ] 场景支持校验、启动、等待、暂停、恢复、停止及条件适用的单步/重置；按应用或状态条件推进。
- [ ] 实现正常、边界、业务异常和通信异常用例，包含批准的重复、乱序、延迟、停止发送和非法值。
- [ ] 区分CAN日志、以太网PCAP和工程量历史；仅按正式规则更新线上序号、会话或校验，合法原码可直放。
- [ ] 跨链路时钟明确单调时间、仿真时间、设备时间及同步方式；未同步主机的单调时钟不能直接相减作为链路延迟。
- [ ] 复用或完善控制源互斥、超时安全、有限资源及磁盘门限；证明旧队列不在恢复后意外执行。
- [ ] 为视频注入与串口/AD/DA/IO建立独立能力清单、接口测试点和条件用例，不将网络工程量作为实体证据。

**交付与门禁：** 场景库、受控回放、安全用例及失败记录。物理电平/仲裁错误、图像真实字节同步和实体I/O均保留独立验收状态。

### M5 Robot自动化与验收证据

- [ ] Robot通过工具封装与3.6标准管理API编排运行，不直接绕过正式接入写模型。
- [ ] 自动运行L01至L09及对应T01至T13；逐项声明适用性和运行环境，不以跳过必选项取得通过。
- [ ] 每个用例分别判定接收、实际应用、业务响应和安全结果；未定义模型参考值时不声称动力学正确。
- [ ] 保存环境/依赖/ICD/模型哈希、原始TX/RX、应用证据、断言、异常和唯一结果文件；证据缺失即失败。
- [ ] 复用既有验收风格，新增独立接口验收入口，防止覆盖或误引用旧验收结果。

**交付与门禁：** 一键软件验收、Robot报告、证据包与功能覆盖矩阵。Windows单元测试、Linux软件链路和目标实时测试分别出结果。

### M6 正式通道验证与发布冻结

- [ ] 目标硬件就绪后验证驱动、接线、通道、正式物理链路及适用同步能力；驱动缺口在此阶段关闭，不留待替换。
- [ ] 使用实际模型及规定并发负载验证周期、抖动、延迟、反馈、资源边界和稳定运行。
- [ ] 完成独立视频与实体I/O工作包中的全部必选项目；相关项目未就绪则不能形成完整终验结论。
- [ ] 锁定3.6接入服务、C核心、驱动、依赖、ICD、映射、模型契约及自动化测试；签署允许配置变更的白名单。
- [ ] 形成不可变发布包、哈希清单、部署手册及回退程序。

**交付与门禁：** 阶段D正式发布基线。当前暂不展开硬件规格争议；这不代表取消此阶段或默认达标。

### M7 真实3.3切换与同场景回归

- [ ] 真实3.3先通过同版ICD符合性检查；未就绪时仅用独立发送实现检查接口透明性，不登记真实3.3验收通过。
- [ ] 停止模拟器、撤销授权、清理队列并进入安全状态；只修改白名单配置后接入真实3.3。
- [ ] 对比受保护文件哈希，执行L10/T14及全部必选同场景用例。
- [ ] 任一必选规则失败、证据缺失、配置越界或受保护文件变化均拒绝替换验收；按既定流程回退。

**交付与门禁：** 真实3.3替换报告和回退证据。允许按部署流程重启，不承诺运行中无中断热切换。需要修改ICD或3.6发布包时，另走版本变更并重新验证，不算原基线平滑替换。

## Test Strategy And Existing Commands

所有新增代码先建立针对性的失败测试，再实现并验证；旧功能回归为每个里程碑的进入条件之一。正式测试阈值来自冻结ICD及标书，不用样例数值填补未知要求。

现有Python回归命令，在既有HIL目标环境执行：

```bash
python3 -m unittest discover -s tests -v
```

现有完整Ubuntu基线入口，仅在满足目标依赖、MATLAB许可证、模型包及干净基线条件时执行：

```bash
bash scripts/run_ubuntu_acceptance.sh
```

新服务测试与Robot需使用各自独立锁定环境；M0/M1的聚焦实施计划明确新入口及准确命令，不修改旧入口含义。计划阶段不安装依赖、不构建模型、不宣称测试通过。

## Sequence And Workload

主依赖为M0、M1、M2、M3、M4、M5、M6、M7依次通过。M2端到端最小链路是首个可演示软件版本；M5是完整软件链路验收版本；M6形成可用于真实源替换的冻结版本。

当前消息定义已由v0.3提供。在有可用目标软件环境、由一名开发者主要承担的前提下，M0至M5原初步预算为40至60人日；应结合59类消息、模型行为缺口与工具接入重新估算，不能直接作为当前固定交期。Windows可移植部分可先执行；M6/M7单独排期，取决于硬件、真实3.3与目标环境就绪，不包含在软件工期承诺中。

### 2026-10-06剩余工期估算

这是用户要求的当前粗估，不修改已批准范围、执行顺序或完成门禁，不是固定交期。按一名熟悉项目的全职开发者、每周五个有效开发日估算；包括编码、联调和回归，不包括等待Linux主机/硬件/许可证/模型/真实3.3。依据为实际receiver仍仅公布1及条件34、未安装完整ScenarioRuntimeServices/ReplayProcessAuthority、原Task 2/3/4未关闭以及唯一台账17个Linux门禁；不能按测试条数或已写文档比例折算完成率。完成首次Linux盘点和最小模型闭环后应重新估算。

| 剩余工作包 | 估计人日 | 边界 |
|---|---:|---|
| 原W3共用剩余运行服务、完整回放/负例/六工具接线、Run/Report及软件回归 | 10-18 | 不重复计入下面实际C/设备实现；原W3门禁保持 |
| W3之后配置化自生数据、连续运行入口及冻结ICD发送验证 | 3-5 | 不改线上契约，不依赖采集硬件；不能伪造3.6能力 |
| 暂缓W4管理API/控制台与自动化共用接线 | 8-12 | 仍在总范围，未经恢复不提前执行 |
| Linux补全、实际模型/原工具/通道、目标性能/证据和发布 | 30-55 | 对应L-001至L-015、L-017；不另开发Linux协议版本 |
| 全系统联合回归、缺陷修复和交付收尾 | 5-10 | 与上面工作包不重复计工 |
| 真实3.3就绪后的符合性/配置切换/同场景回归 | 3-5 | L-016；外部3.3开发与等待时间不在估算内 |

顺序单人合计59-105人日，约12-21个有效工作周；有并行人员时不能简单除以人数。若W4/W5继续搁置，只可交付当前模拟器软件范围，不能承诺完整标书/硬件/替换验收日期。硬件和真实3.3的外部等待无已确认上限，故“全部验收完成”目前不能给固定日期。

Linux的30-55人日分解为：隔离环境/启动/资格3-5，实际C/Simulink输入消费者、模型缺口及生命周期/安全12-20，原六工具/网络/CAN接入5-8，视频/实体I/O消费者与驱动5-10，时钟/RT负载/目标自动化/冻结发布5-12。假定现有驱动、可构建模型和设备接口资料可用；若须新开发驱动、修复模型生成工具链或硬件达不到指标，应新增专项估算，不能通过弱化必选项吸收风险。

数据时间点分别估算：当前已有离线编解码、波形计算和显式单次报文交换，尚无完整配置化自动发生器；它们不是用户要的持续自生数据交付。按“先完成原W3共用任务，再发生器”的既定顺序，配置化持续生成/标准发送软件预算13-23人日，约3-5个有效工作周，前提是该路径具备真实授权、能力与目标步来源。连接真实3.6业务并证明实际应用，还需最小Linux模型消费者/反馈闭环约5-10人日，总计约4-7周，且需要恢复相应暂缓任务；没有已公布真实消费者时必须拒绝业务发送或返回失败，不能拿协议peer当真实3.6。此最小闭环不等于三源/六工具/实物全部验收，也不等于完整Linux工作已完成。

优先级依次为共同契约与最小闭环、必选工具/消息覆盖、场景回放与安全、自动化证据、目标部署、真实替换。GUI操作可晚于首条闭环；新管理平台、强制报文转发中心和与当前范围无关的重构不安排。

2026-10-04 W3.11进度：共用`tools.py`完成六原分支冻结目录/API名称核对、实际模块distribution RECORD/origin/版本及可执行文件hash的安装证据；安装事实不按宿主OS分流，当前CANT/ETHGEN依赖存在为UNVERIFIED，其余四分支缺工具为UNAVAILABLE，无AVAILABLE或实际后端资格。共用本地多接口预约保留原工具独立通路，OBSERVE不持发送预约，跨分支发送接口原子互斥，opaque身份/容量/旧token保护不等于标准授予。`tool_process.py`以可信内部literal argv运行真实直接子进程，保存有界binary双流/PID/returncode/期限/错误，真实超限/超时/停止/系统异常/EOF分别记录，进程树清理仍未验证。重要期限/自然退出/影子版本/等待异常均RED/GREEN修正；独立19进程/10安装及6原CLI守护复核无剩余重要scoped发现，首轮全量发现OS诊断分流已修正并等待终态。固定最终版522共用/34静态及接口/依赖/编译/台账守护通过，实际命令、四源码/测试哈希和首轮不计验收事实保存独立`artifacts/icd_gateway/w3-11-validation.json`。单代码/14源/原C/六工具/41责任/17 Linux未执行保持，唯一台账追加实际安装/后端/进程树/权限/安全/授予与反馈要求；各工具可信builder/发送联动、完整回放/场景/API/Robot/模型/设备/发布仍属共同后续与Linux实际门禁，不勾选完整M3/M4或整体完成。

## Review And Execution

2026-10-05 W3.26 Task 1进度：原ScenarioExecution已通过OriginalScenarioDriver连接实际CANT与ETHGEN/Scapy发送组件，原完整ScenarioPlan、六工具分支、根断言及非native事件仍保留；同实际Source/SID、标准Status观察步、全计划预检、目标步审批、不可伪造非空句柄和begin不重试落实。分批九项清理回执累计、远端终态缓存、本地恢复独立重试、回调前后身份、实际原SID关闭与同步完成均RED/GREEN修正，独立复核六项重要发现关闭。固定版172针对性兼容测试通过（31 driver/32控制器/28 native动作/31会话/27协调/23时钟），14逐字节源663引用、59/72/85/800向量、pip/编译通过；不是新的完整回归，历史862仅属于W3.25。证据artifacts/icd_gateway/w3-26-task1-validation.json，唯一Linux台账追加本任务实际要求并保留41责任/17未执行门禁。W3.26只完成Task 1，实际生产服务/ControlOwner/真实reader/完整回放与负例/六工具生命周期/九项实际清理/持续Run与Report及三源验收仍按Tasks 2至4推进，不能把测试服务当实际模型，不关闭原W3，不提前恢复发生器。

2026-10-05 W3.25进度：原场景native发送组件已接CANT/cantools/python-can与ETHGEN/Scapy，支持原常量、波形、周期、故障完整Stimulus及标准反馈，Scapy-only不强制无关CAN后端，不新增ICD或Windows分支。选中协议逐消息预检、纯CAN同预约簿、closing/detached精确清理、后分配失败的opaque上下文与原请求保留均RED/GREEN关闭；空CAN poll不记录超时，UDP取消只针对原Header所属组，本地回收失败不能隐藏在远端终态中。28动作/27协调及独立七重点通过，无剩余重要scoped发现；固定862共用（788网关498.227s）、34选定静态、14源663引用及依赖/编译通过，十源码/测试hash不变，见artifacts/icd_gateway/w3-25-validation.json。唯一Linux台账追加实际授权/目标步/负载/原工具/停止/持续证据要求，41责任/17未执行门禁保持。本组件不是完整ScenarioDriver；WAIT/ASSERT/负例/完整回放及六工具生命周期、九项清理与完整Run/Report继续原W3共同开发，三类链路仍未端到端验收，新增发生器不提前恢复，不关闭原W3。

2026-10-05 W3.24进度：原CAN与UDP/Scapy共用标准会话协调已实现，一Ethernet dispatcher及最多四原CANT sender共用真实grant/SID/取号和首次尝试顺序，不转发CAN字节、不改冻结ICD。当前唯一scope与一次入口委托防止旧上下文/回调重入旁路，失败关闭停止原UDP发送并保留同句柄，dispatcher先关不提前释放源owner，计划丢弃匹配实际sender/通道且先退休在途上下文。原五复核发现及两相邻边界均RED/GREEN关闭，23专项、独立三重点及跨sender实际复现通过；固定829共用（755网关468.652s）、34选定静态和14源663引用通过，八源码/测试hash不变，见artifacts/icd_gateway/w3-24-validation.json。唯一Linux台账已追加实际跨链授权/负载/失败清理/原始证据要求，41责任/17未执行门禁保持。协议资源的原CAN/以太网软件收发更接近可用，但生产场景driver、历史回放执行与六工具生命周期、native持续证据及完整Run/Report仍未完成；不把三类资源解析当三链端到端完成，原W3未关闭，新增发生器继续搁置。

2026-10-05 W3.23进度：原共用model_clock.py从实际串行UDP/UDPDispatcher/CANT标准131观察模型步，保留原请求/反馈/SID/型号/源时钟域及原Heartbeat起算240ms期限，不推算1ms模型时钟。每个新鲜Status包含交错旧请求提升共享步数高水位；跨UDP/CAN发送尝试事务高水位防止超时/失败后旧131重计时，原仅准备和其他消息分组不变。实际已公布Lifecycle APPLIED/OK使RESET/RESUME旧SID时钟失效，新授予与新Status必需，不虚构同SIDepoch或同步/安全资格。两独立发现RED/GREEN关闭，最终23新专项+2原CAN兼容及独立7重点通过；固定806共用（732网关467.151s）、34静态及14源663引用通过，五源码/测试hash全程不变，见artifacts/icd_gateway/w3-23-validation.json。原W3仍未完整完成，生产driver/完整回放生命周期/六工具联动/qualified readers/ClockSync/完整Run与Report继续原共同开发；Linux实际要求追加唯一台账，41责任/17未执行门禁不删不勾，新增自生数据入口继续搁置。

2026-10-05 W3.22进度：继续原CANT的cantools/python-can/SocketCAN共用发送与CANFD标准130/131反馈，不启动新增发生器。11类CAN输入、四正式CANFD映射、原FD64/BRS/字节/20ms期限及当前标准grant/角色/型号/能力/租期校核落实；本簿native总线单反馈owner、SourceSession持久sequence/心跳事务高水位、缓存131验收时续租、完整TX/RX/FAILED原证据及实际periodic/BCM/raw关闭重试防止重复/迟到/吞反馈和错误释放。41专项与独立11重点、31会话/22原准备/10工具、固定783共用/34选定静态/14源663引用通过，12源码与测试hash前后一致见artifacts/icd_gateway/w3-22-validation.json；为builder替换问题中止的首轮回归不计通过。VirtualBus仅库级软件证据，缺实际SocketCAN后端不回退Windows SDK或UDP，原六工具目录和安装资格不提升。原W3仍未完成：生产ScenarioDriver、全部工具/GUI/回放联动、完整repeat/RESET/initial_inputs、暂停恢复/负例/真实probe与ClockSync、CAN/Scapy持续Run及完整Report继续原共同开发，实际Linux要求追加唯一台账。41责任与17未执行Linux保持，不勾选完整阶段或整体目标；原W3完成前新增自生数据入口继续搁置。

2026-10-05 W3.21进度：继续原ETHGEN/Scapy共用发送链，不开发新增自生数据入口。UDPSource仅提取两处_emit_packet，默认socket行为不变；ScapySource使用原库SuperSocket发送完整Ether/IP/UDP/原ICD，继承标准反馈/重试/重组/资源节流。原ETHGEN SEND预约、四ETH映射/明确MAC/IP、真实当前标准grant/角色/模型/能力/租期及已分配Header或原拥有bytes校验落实；SourceSession增加实际operation线程归属和单份最近分配关联，直接TX/close不能绕过dispatcher或并发owner。完整/短写/失败/发送后到期L2尝试不可变有界保存，pcap原句柄关闭失败可重试且成功关闭不重复，close不释放预约/假称远端清理。28专项与独立26专项/31会话、固定742共用/34选定静态及14源/663引用通过，十源码/测试hash见artifacts/icd_gateway/w3-21-validation.json。测试帧汇不是Windows硬件后端/物理资格，工具安装状态不提升；默认Scapy backend/四实机ETH、原CAN/GUI/回放工具、生产ScenarioDriver/完整回放/安全/完整L2持久报告继续原共用后续和唯一Linux台账。原W3仍未完成，新增发生器继续搁置，不勾选完整M3/M4/W3或整体目标。

2026-10-05 W3.20进度与顺序纠正：原有第三阶段尚未完成，新增自生数据发生器草案暂停且不交付，先完成原W3再恢复新增入口；W4/W5暂缓但41责任/17 Linux待办不删。原scenario_execution.py补共用单owner运行控制器，原ScenarioPlan/十事件/六link/完整Stimulus不改，整计划driver预检先于执行；独立根断言handle/半开期限、WAIT同一步屏障、不追赶漏步、原终态和具体异常关联、有界全程记录预算与九项清理回执保存落实。LOCAL_STOPPED/COMPLETE仍NOT_EVALUATED、ready=false、安全未资格确认，无生产driver即拒绝，不以测试double或UDP代替原工具/真实时钟/probe。独立发现均RED/GREEN关闭；固定32专项及714共用/34选定静态、14源/663引用通过，11源码/测试hash见artifacts/icd_gateway/w3-20-validation.json。唯一台账已追加Linux原后端/真实授权/模型时钟/采样/RT/清理开发验证；生产driver/完整回放与重复轮次/暂停恢复/条件单步复位/负例不应用证据和完整运行终点仍属原W3共用后续，不勾选完整M3/M4/W3或整体目标。

2026-10-04 W3.19进度：共用evidence_recorder.py以单实际后台线程持续保存原Source/Dispatch/Inbox段，实际线程终止、原包/commit读回与三流全部身份计量一致后才回收已存前缀，新增收报及预约/watch/序号/租期不变。三池旁路drain和旧dispatcher关闭后抢占原session被拒绝；同锁snapshot helper关闭等值替换竞态，公共archive API/文件格式不变。连续闭hash/累计counts、有界扫描、成对可信count/tip与本地关闭检查点、有限等待同handle/失败保留落实；无可信锚活动链只证明已见前缀，关闭快照不执行远端九项清理或签整体证据。70证据回归、独立25专项/20archive/8guard与边界探针通过，固定版682共用/34选定静态及14源/663引用守护通过，六源码/测试hash记录artifacts/icd_gateway/w3-19-validation.json。唯一台账追加Linux实际目录持久/崩溃恢复、连续采集背压/内核丢包、RT负载/时钟及失败安全验证；41责任/17未执行Linux保持。正式Run身份与可信终点保护、模型工具环境hash/Report/API/Robot、真实消费者/探针、完整场景/回放/六工具与Linux/RT/发布/真实3.3仍按同一完整计划完成，不勾选完整M5/W3或整体目标。

2026-10-04 W3.18进度：新增共用evidence_archive.py在原dispatcher/session owner锁下快照SourceExchange/DispatchRecord/EvidenceRecord，原TX/RX/请求/回复/失败bytes采用base64保真，uint64收时刻用原十进制字符串，不drain/取号/发送/关闭或改变租期。脱离不可变包经独占新目录、xb/fsync/逐字节读回和最后manifest硬链接发布；有界读回核对原文件hash/size、真实行与流计数、闭字段、冻结四组件及baseline，拒绝缺文件/篡改/资格提升。目录扫描问题通过底层os.scandir RED/GREEN关闭，原共用源码守护的宿主metadata问题保留首轮失败后改无分支platform.platform，测试规则不改。20专项及独立20/原守护/边界探针通过，固定最终657共用/34静态及14源/663引用守护通过；两源码/测试hash记录artifacts/icd_gateway/w3-18-validation.json。唯一台账追加目标文件系统/磁盘背压/非实时写盘/多段完整性与安全资格，41责任/17未执行Linux保持。当前证据段始终NOT_EVALUATED/evidence_complete=false/ready=false，不证明来源签名或整个运行；连续采集包、模型工具环境hash/正式Report、真实探针、场景/回放/六工具/API/Robot、Linux/RT/发布及真实3.3仍须完整同代码交付，不勾选完整M5/W3或整体完成。

2026-10-04 W3.17进度：共用evidence.py与原UDPSource/Dispatcher同一实际socket、唯一读者保存全部14类反馈原码/peer/channel/本机收时刻，140独立重组并核验原opaque请求、完整实际TX、当前标准SID/transaction/sequence/message/event/trace/原payload hash/stage/步窗口及公布probe。终态ACK后仍采集，不将Evidence当ACK、心跳续租或资源commit；原全局反馈高水位/重复冲突规则、有界共用容量、前置背压、drain不清上下文/序号、本地close脱离但保留记录落实。解码期间租期到期/时钟回拨先RED后修为使用新鲜本机clock，失败记录保留且不推进高水位。25专项及独立25复核通过，固定版637共用/34静态和14源/663引用守护通过，四源码/测试hash及未完范围记录artifacts/icd_gateway/w3-17-validation.json。唯一台账追加实际原四ETH收报/网络队列、真实消费者探针/140 producer和样本关联、当前授权/时钟/背压/九项清理与持久证据要求；41责任/17未执行Linux保持。关联远端PASS仍NOT_EVALUATED、ready=false，现有服务无实际模型140/reader；真实执行器、完整场景/回放/六工具/API/Robot/消费者/RT/发布及真实3.3继续同一代码，未勾选完整M3/M4或整体完成。

2026-10-04 W3.16进度：共用assertion.py落实八种冻结数学比较、不可变型号/probe/目标/固定数组索引/expected类型编译，覆盖97模型路径/105元素；root及WAIT/ASSERT全部接入原场景编译和三源审核，原始负零/类型与快照容量保留。半开MODEL_STEP期限、真实新样本序号/连续计数、有界记录、容量失败原子、drain不重置与只读公开配置已实现。比较MATCHED仍NOT_EVALUATED且ready=false，不生成140反馈、不签E1/E2/E3；消费者路径语法检查不是实际reader资格。16专项、21场景/14波形/39源和独立16专项/21场景及边界探针通过；固定版612共用/34选定静态及14源/663引用守护通过，五源码/测试hash与未完范围记录artifacts/icd_gateway/w3-16-validation.json。唯一台账追加真实探针/available_probes、标准Evidence关联、暂停新采样、模型步/时钟/负载及WAIT超时九项清理要求；41责任/17未执行Linux保持。实际状态机、全部handler/原工具发送/反馈采集、回放/消费者/API/Robot/发布及真实3.3仍须同一代码完成，不另建Windows版本、不勾选完整里程碑或整体完成。

2026-10-04 W3.15进度：共用scenario.py将十类Event保存为不可变离线请求，按模型步/优先级/事件ID惰性合并完整Stimulus，周期首份/次数/STOP同一步排序、波形精确末步及END标记截断已实现。完整root7..19消息按97绑定/105标量与数组目标解析写集合，含bool及7/14别名；同目标同一步跨工具/不同波形字段/周期后续交点真实拒绝，有限等差流用gcd/模逆而非百万展开。未接其他消费者/REPLAY实际端口明确pending，WAIT/ASSERT/负例/清理只是待真实handler请求，ready始终false。接入原三源审核，原类型/负零、限定快照/比较/输出容量与预先失败保留；浮点变异整数RED后修。21专项、14旧波形/39源及独立21专项/50000交点/10000截断探针通过；固定版596共用/34静态及14源/663引用/41责任/17未执行Linux守护通过，独立报告artifacts/icd_gateway/w3-15-validation.json保存四源码/测试hash。唯一台账追加真实目标身份/模型步/负载/WAIT探针/授权安全与九项清理资格；实际场景状态机、全部handler/原工具发送/消费者/API/Robot/发布和真实3.3继续共同后续，不另建Windows版本，不将离线时间表或测试通过当整体完成。

2026-10-04 W3.14进度：共用waveform.py按冻结绑定落实CONSTANT/STEP/RAMP/SINE/CHIRP，显式MODEL_STEP、相对STEP、内外duration截取/终值保持、连续理论峰谷及实际区间最高频率10倍采样校验，不展开长周期、不clamp或生成Header。覆盖三个型号全部83数值绑定/91标量与数组元素；bool/反馈/未注册/无根映射拒绝。原三源审核编译全部WAVEFORM并保留原类型/负零，canonical与原值快照共同计16MiB，不改线上ICD且execution_ready仍false。14专项/39旧源及独立14专项/边界探针通过，固定版575共用/34选定静态、14源/663引用及41责任/17未执行Linux守护通过，三源码/测试hash记录artifacts/icd_gateway/w3-14-validation.json。唯一台账追加真实型号端口/单位、实际模型步、采样与消息周期/总线负载区分、实际消费者探针和结束安全验证；完整场景调度/碰撞/WAIT/断言/负例/九项清理、原工具发送/API/Robot/消费者/发布和真实3.3仍属共同后续及Linux门禁，不另建Windows版本、不勾选完整M4或整体完成。

2026-10-04 W3.13进度：共用SourceSession提供当前标准授予下的有界不可变完整输入组，保持唯一全局取号者与既有dispatcher独占规则；先验证原类型，canonical记录与保留浮点负零的原值快照分离且共同计容量。共用live_tool_input.py准备CANT原cantools/python-can对象、CUTIL逐片literal cansend与ETHGEN原Scapy Ether/IP/UDP，明确本簿预约/正式通道/实际会话端点及MAC，准备不启动工具、不产生线上TX或模型成功。11 CAN输入及44非SessionOpen UDP输入完整组结构、实际标准授予的已公布34能力准备通过；协议peer与原库对象均非硬件资格。两个类型/负零问题先RED后修，独立2回归/22专项/31原会话复核通过；固定版561共用/34静态及14源/663引用、41责任/17未执行Linux守护通过，独立报告artifacts/icd_gateway/w3-13-validation.json保存三源码/测试hash。唯一台账追加原SocketCAN/网卡后端、当前ControlOwner/模型步/全局发送顺序、标准反馈和实际停止/安全要求；SavvyCAN/Ostinato受控后端、完整执行器/场景/API/Robot/消费者/发布及真实3.3仍属共同后续和Linux门禁，不开发Windows分支、不勾选完整里程碑或整体完成。

2026-10-04 W3.12进度：共用`tool_commands.py`补齐CUTIL/candump观察及CANREPLAY/canplayer、ETHREPLAY/tcpreplay参数准备，核对本簿有效预约和一一正式通道绑定，回放复用ReplayExporter完整核验，不接受任意argv/工具内改速/跳包/多轮。逐通道完整文件/hash/首次offset保留，参数构建不写文件或启动工具、execution_ready与authorized_to_transmit恒false；CANT实时发送、SavvyCAN、ETHGEN及全部授权/反馈/调度联动仍继续原后续。原六分支/ICD/C与单代码不变，不勾选完整M3/M4。canplayer stdout打印钩子误作物理回放接口先RED后拒绝，17专项及独立17专项/19导出复核通过；固定版539共用/34静态、14源/663引用及41责任/17未执行Linux守护通过，独立报告`artifacts/icd_gateway/w3-12-validation.json`保存三源码/测试hash。唯一台账已追加本批Linux实际工具版本/权限/原参数/微秒和纳秒时序/四通道起始对齐/标准授权反馈/停止安全验证；共用完整执行器、场景、API/控制台/Robot/消费者/发布与真实3.3门禁保持未完成。

2026-10-04 W3.10进度：`replay_export.py`完成逐通道完整CAN_LOG/纳秒PCAP及独占持久资源包，原工具前预处理架构不变。44条已授予UDP输入三模式和11条CANFD输入日志、反馈隔离、FD/BRS/ESI、原包顺序/准确时间、明确MAC辅助转换与完整policy/hash得到校验；原目录13 CANFD总数含2反馈，不计发送输入。新增PreparedReplay内部policy_json，不改ICD；独立篡改/遗漏/旧SID/端点/policy/倒退时间发现均RED/GREEN修复，19专项、26原回放/23解码及独立33 CAN输出通过。真实目录写入/fsync/读回/不覆盖与最后manifest硬链接发布已实现，不支持时失败并留存未完成目录。文件仍execution_ready=false、无实际TX/APPLIED/CONSUMED，微秒兼容只是canplayer时间可表示条件而非目标资格；真实工具/进程/时钟/模型/设备留Linux及共同后续。唯一台账已追加，41责任/17未执行Linux及14源/原C/六工具不变，不勾选完整M3/M4或整体完成；固定版493共用/34静态及接口/依赖/编译守护通过，实际命令和三个源码/测试哈希保存独立`artifacts/icd_gateway/w3-10-validation.json`。

2026-10-04 W3.9进度：共用`dispatch.py`接实际SourceSession，完成多在途标准反馈分发、一次编码token/非阻塞逐片资源TX、首次组全局序号顺序、有界记录及原码重试。实际20Mbit/s发送间隔、TX/RX期限/租期、时钟异常证据与取消已实现；五项独立发现先RED后修正，21专项及最终只读复核通过。20ms心跳要求显式模型步与实际公布能力2，实际TX迟到超过1ms明确失败；当前真实接收端未实现2，测试peer不是实际模型/RT资格。原入口丢包导致旧序号OUT_OF_ORDER如实失败，不改码或保证并发可靠恢复。唯一台账已追加本批Linux网络/负载/C/时钟/原工具要求；64反馈SID真实退休、完整回放/场景/六工具/API/Robot/持久证据继续共用后续。14源、41责任、17未执行Linux及原C/六工具不变，不勾选完整M3/M4或整体完成；固定版474共用/34静态及接口/依赖/编译守护通过，实际全量证据保存`artifacts/icd_gateway/w3-9-validation.json`。

2026-10-04 W3.8进度：`session.py`由实际标准129授予SID，校验角色/模型/两层pin与公布能力，统一跨输入序号/事务且拒绝回绕；原UDPSource新增131/142对2/33的标准关联。保守源租期、有界不可变交换记录、传输生命周期唯一owner及TX/RX入口归属检查已实现，两个实际旧grant授权混淆路径先RED后修正，31专项及独立原UDP回归通过。真实Header已接原回放准备且实际34/141存储通过，但不产生模型应用或execution_ready。串行10s资源等待不能宣称持续Heartbeat，异步反馈分发/多在途执行、64反馈SID真实退休、完整回放/场景/工具/API/Robot仍为共同后续；实际C/模型/驱动/时钟/实体及真实3.3保留Linux/目标门禁。唯一台账已追加本批Linux要求，41责任/17未执行Linux和14源/C/六工具不变；完整回归证据见`artifacts/icd_gateway/w3-8-validation.json`，不勾选完整M3/M4或整体完成。

2026-10-04 W3.7进度（10月3日开始）：`replay.py`实现RAW_VALIDATED原包保留、REENCODE标准编码、SESSION_REBUILD逐片header/CRC改码的实际捕获准备核心；保持原片顺序、业务字节/hash与重传/事务关联，FROM_36只分析，严格完整窗口/精确倍率/有界单轮。独立26回放/3改码复核与最终422共用/34静态通过，未指定/广播端点及signed-zero证据问题已RED/GREEN修正。结果仍execution_ready=false，不能把本地Header分配当SessionGranted或真实RESET；完整回放执行器、工程量JSONL回放、整份重建日志/PCAP导出、工具生命周期、场景/API/Robot及实际Linux/模型/实体/真实3.3资格继续原责任。14冻结源、41任务、17未执行Linux门禁及原C/六工具保持，台账已追加；证据`artifacts/icd_gateway/w3-7-validation.json`，不勾选完整M3/M4或整体完成。

2026-10-03 W3.6进度：`history.py`完成实际捕获到显式HistoryStream/channel/clock的关联、原WireCodec/Reassembler逻辑解码，全部59业务/13CANFD及三RawBus分支专项通过；接入原审核与显式本地bindings CLI，FROM_36只分析，辅助不虚构Header，全部结果仍不可执行/未测clock。独立23解码/39审核测试通过，跨接口交错误判回拨的P2已先RED复现后修正逐domain检查；最终393共用/34选定静态回归通过。原14源与线上字段不改，17 Linux仍未执行；三回放执行器、TCP/完整视频提取、场景执行、六工具封装、25 API/Robot及实际Linux/消费者/实体/真实3.3仍属原责任。不勾选完整M3/M4，阶段证据`artifacts/icd_gateway/w3-6-validation.json`已记录。

2026-10-03 W3.5进度：`capture.py`及`_capture_envelopes.py`使用原python-can/Scapy解析CAN_LOG/PCAP/PCAPNG实际字节，保留CAN/FD元数据、IPv4 UDP/TCP/VLAN、独立接口时钟、精确整数ns和丢包/截断证据；接入原三源审核与真实文件CLI。独立24捕获/37输入测试和复核通过，四项重要问题已RED/GREEN修复，最新368共用/34选定静态回归通过。捕获解析不等于完整HistoryDecoder，history_decoded/execution_ready保持false，流关联/方向/时钟资格、正式逻辑帧重组及三模式执行仍需后续实现。全部41任务和17 Linux门禁保持，新增Linux要求继续追加唯一台账；不勾选完整M3/M4或整体完成。阶段证据`artifacts/icd_gateway/w3-5-validation.json`已记录。

2026-10-03 W3.4进度：`input_simulator/protocol.py`真实解析冻结DBC与严格R4等价ARXML导入，13帧/650信号及20个CAN黄金片逐字节核对，接入原三源审核；独立17协议/32审核与CLI测试通过。两项ARXML有损投影复核问题均RED/GREEN修正。协议导入不授予执行资格，不标实际工具/消费者/目标通过；历史捕获解析、场景/三模式回放、六工具封装、25命令API/Robot及Linux/实体/真实3.3仍属原任务。新Linux要求继续追加唯一台账，不勾选完整M3/M4；阶段报告`artifacts/icd_gateway/w3-4-validation.json`。

2026-10-03 W3.3进度：新增`input_simulator/source_inputs.py`的三类输入结构/原资源字节审核、工程量JSONL解析和独立离线入口，39条专项及只读复核通过。结果恒不可执行；DBC/ARXML及实际捕获解析、完整场景/回放执行器、六工具、API/Robot和Linux/模型/实体/真实3.3门禁仍未完成，不勾选完整M3/M4。每包Linux要求继续追加唯一`linux-development-backlog.md`，41条责任覆盖不变；阶段证据见`artifacts/icd_gateway/w3-3-validation.json`。

- [x] 核对最新方案范围及现有仓库职责。
- [x] 区分现有实现、计划模块、示例接口与正式冻结依赖。
- [x] 保留六条工具分支、统一接入、独立实体通路和仅配置替换要求。
- [x] 分阶段设置可验证交付物，不将软件通过等同硬件或真实3.3通过。
- [x] 用户已确认推进，按聚焦W1计划开始共用协议库实现；原始本计划新增时未修改业务代码的描述不作为当前开发状态。
- [ ] 每个里程碑开始前形成聚焦实施任务，完成后报告代码范围、测试证据和未关闭依赖。

2026-10-07 本轮收尾与暂停：原W3 Task 2的公共Lifecycle消费适配已覆盖三型号六动作的完整关联读回、有限证据、原ACK缓存、实际本地清理核对及RESET/RESUME旧组会话退休；真实本机UDP测试使用明确模型替身。最终160源码固定下488项/24相关非空套件通过，未跑本批完整gateway；原20第三条留存hash和台账历史保持。实际C模型、九项清理、完整运行服务/断言/负例/工具、全部服务持久化/RunReport及前两条端到端仍未完成，不关闭W3或整体目标。按最新请求，本轮记录完成后暂停，不进入下一阶段；以后经用户恢复只开发PROTOCOL/SCENARIO及必要公共模块，第三条由外部负责人继续，既有源码/测试/资源/记录保留。Linux补全与风险继续追加唯一linux-development-backlog.md，自生数据配置仍待原W3完成，W4/W5保持暂缓。
