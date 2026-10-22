# 模拟器与 HIL 最小联调两圈流程开发计划

> 日期：2026-10-20
> 状态：软件实现和离线回归已完成；Linux 目标机、实体 CAN FD/网卡、原工具链与外部 3.3/3.6 调用方的现场验收待执行。管理面、准备服务与安全生命周期已落地。四旋翼生成模型已具备受验证的 DWork 初始状态写入/读回 ABI；HIL 资源库已对配置所引用的 Terrain/Obstacles 做字节、哈希、原点和初始点地面取样核验，C-core 已在同一安全边界写入模型绑定输入/DWork、保留完整配置并进入 `CONFIGURED`。正式 ERT 产物已经 `PreparationService` 完成第一圈软件联调；正式网关组装、生命周期和模拟器最小执行链已通过本机软件联调，不以此替代目标物理链路资格。  
> 依据：`/home/user/下载/3.3后端与模拟器最小联调方案_两圈流程版.md`
> 实施范围：本仓库的模拟器与 HIL，不包含 3.3/3.6 后端与前端实现。

**2026-10-21 回归结论：** `runtime/python3.12/bin/python3.12 -X utf8 scripts/test_icd_runtime.py`
全绿：运行时/网关/HIL 共 1269 项、开发计划 3 项、接口汇总 4 项及单文件契约核验。
这证明仓库软件路径，不证明目标机进程、实体总线、实时网卡、原工具或外部后端已部署。

**2026-10-21 两圈联调交付补充：** 新增 HIL 第一圈远程管理入口
`hil-preparation.service`（`0.0.0.0:18081`）和只读遥测
`hil-telemetry.service`（`0.0.0.0:8765/ws/hil`）。前者执行实际 C-core 配置和
读回；后者只将 UDP 状态推给 3.6，不接受控制命令。它们的源码和单元已同步到
`/opt/hil`，仍须运行安装脚本并启动单元后才能作为异机后端的现场入口。

## 1. 目标

以一个固定模型、一个固定场景、一套已落盘资源和一个活动任务完成两圈最小联调：

1. 第一圈由 HIL 接收初始化请求，对实际模型、资源、初始状态和完整输入快照执行原子配置与读回，进入 `CONFIGURED`，不推进模型步、不发送测试激励。
2. 第二圈由模拟器接收管理 API 命令，核对第一圈快照，创建正式会话，通过 CAN FD/UDP 冻结 ICD 发送 `START`、场景激励与 `STOP`。
3. HIL 对配置、启动、输入应用和停止返回真实 Ack/Status/State/必要证据；模拟器将原始事实持久化并通过管理 API 提供查询。
4. HIL 现有遥测到 3.6 的链路保持独立；模拟器不转发页面遥测。

## 2. 范围边界

### 2.1 本计划负责

- 模拟器 HTTP 管理入口：`simulator_run_create`、`simulator_run_get`、`simulator_run_control`、`simulator_records_list`。
- 模拟器 Run 状态机、revision CAS、`request_id` 幂等、单活动任务互斥和有界记录。
- 固定模型运行模板、配置快照与资源哈希核验。
- 模拟器正式 Session、RunConfigure 同配置核对、Lifecycle START/STOP、场景执行、CAN/UDP 调度、反馈和证据。
- HIL 初始化语义、实际 `CONFIGURED` 状态、完整配置读回与准备结果。
- HIL 正式 ICD 接收、实际模型配置/生命周期/输入消费后端、安全停止及真实反馈。
- Linux 目标机的进程、SocketCAN/以太网、原工具、时钟、文件系统和证据验收。

### 2.2 本计划不负责

- 3.3 后端的 REST 路由、模板选择、命令查询编排、数据库映射和结果保存。
- 3.6 后端的 Run 创建、准备编排、遥测归属、STOMP 发布和统一终态回执。
- 前端 URL、DTO、页面、资源编辑、历史回放页面、复杂报告、暂停/恢复和事件 WebSocket。
- 消息队列、分布式事务、多活动任务、控制超时自动重发和 HIL 进程的远程开机。
- 扩展或改写 v0.3 业务报文、CAN ID、现有输入源定义和共同基线算法。

## 3. 必须保持的架构不变量

1. 第一圈成功只能得到 `CONFIGURED`；模型步不前进，控制源为 `NONE`，执行器为安全值。
2. 连接成功、HTTP 202、管理 `ACCEPTED`、报文 `RECEIVED` 均不是已运行或已应用证据。
3. 第二圈不重复初始化。相同 RunConfigure 只做完整等值核对和实际读回；字节或语义不一致必须拒绝。
4. 模拟器 `START` 只执行一次。响应超时且结果不确定时，先查 Status/Record，不自动重发。
5. 模拟器停止发送不等于 HIL 已停止；只有同一执行的 HIL 生命周期应用回执或新鲜 Status/State 可以确认停止。
6. 管理面使用 v0.3 API Schema，正式数据面使用同一 HIL-ICD-1.0，不新建模拟器专用模型写入协议。
7. 前端遥测继续由 HIL 到 3.6；模拟器 Record 只提供控制、发送、反馈和证据查询。
8. 不将测试 double、vcan、回环网口、本地退出码或 `execution_ready=false` 组件当作目标 HIL 验收。

## 4. 现有代码基线与缺口

| 区域 | 可复用能力 | 最小联调缺口 |
|---|---|---|
| `icd_runtime` | 已验证业务 Schema、ICD、Header、payload、线上编解码 | 未加载和验证 v0.3 管理 API Schema |
| `input_simulator` | SourceInputs 审核、场景编译、Session、CAN/Scapy、反馈、场景控制和证据基础 | 无 HTTP 服务、Run 注册表、持久状态、后台 START/STOP 执行器和 RecordPage |
| `icd_gateway` | Receiver、SessionRegistry、ModelConfigurationService、ModelLifecycleService、Status 和证据抽象 | 默认 CLI 未安装真实配置/生命周期/模型后端，Capabilities 不宣告准备 |
| `c_core` | 1 ms 模型循环、本地 UDP 命令、部分输入写入和读回 | 初始状态为 RUNNING，无独立 CONFIGURED/STOPPED 语义，RESET 回 RUNNING，与冻结生命周期不等价 |
| `python_services` | HIL 进程管理、状态缓存、Spring WebSocket 和现有遥测发布 | 当前 START 同时启动进程、选控制源并运行任务，不是第一圈初始化 |
| 部署与配置 | 已有 systemd、接收端授权和开发配置 | 无固定运行模板、管理 HTTP 配置、两圈快照标识和单任务恢复策略 |

## 5. 目标运行结构

```text
第一圈：
3.6 -> HIL 准备入口 -> HIL PreparationService
    -> 实际资源/模型/初始值写入 -> 完整读回
    -> CONFIGURED + prepareId/configId/configSha256/modelId/result

第二圈：
3.3 -> POST /api/simulator/commands -> SimulatorRunService
    -> Create 校验/固化快照
    -> START 后台任务
       -> SessionOpen
       -> 同配置 RunConfigure 核对（不重新初始化）
       -> Lifecycle.START -> HIL 真实 APPLIED/Status
       -> 场景、CAN FD/UDP、工具链
       -> Ack/Status/State/Evidence -> SimulatorRecordStore
    -> STOP -> 停止调度 -> Lifecycle.STOP -> HIL 真实停止证据
```

## 6. 实施任务

### Task 0：冻结最小联调契约与样例

**目标：** 在业务代码开始前固定本仓库需实现的输入、输出和判定事实。

**计划文件：**

- 新增 `docs/interfaces/simulator-hil-minimal-integration-v1.md`。
- 新增一组不含虚假运行结果的请求/响应样例。
- 新增 `config/minimal-integration-template.json`，只引用已存在的实际资源。

**必须冻结：**

- HIL 准备请求/结果字段：`prepare_id`、`model_id`、`config_id`、`config_sha256`、`baseline_sha256`、完整 RunConfigure 快照、成功/失败、实际状态和错误原因。
- 模拟器 HTTP 地址、请求大小、超时、错误到 v0.3 `code` 的映射。
- `START` 的真实运行判定，以及 `STOP` 的真实停止判定。
- Record 中 Ack/Status/State/模型应用/安全清理的 `kind`、`reason_code`、`operation_result` 样例。

**验收：**

- [x] 所有模拟器管理样例通过 v0.3 API Schema（软件回归）。
- [x] 所有正式链路样例通过现有业务 Schema/ICD（软件回归）。
- [x] 文档明确后端是调用方，不将后端实现任务写入本计划。
- [x] 示例 ID、URL 和本地测试端口均不冒充已部署值。

### Task 1：v0.3 管理 Schema 运行时

**目标：** 使 HTTP 边界严格复用既有 v0.3 API Schema，不在处理器中手写一套宽松 DTO。

**计划代码：**

- 新增 `icd_runtime/management.py`：加载 API/package/business Schema，解析跨 Schema `$ref`，验证请求和响应。
- 扩展 `icd_runtime/contract.py` 的已验证资产访问，但不改变四组件基线指纹算法。
- 新增 `tests/icd_runtime/test_management.py`。

**测试要点：**

- 25 命令枚举仍可解析，本轮服务只开放四个命令。
- `api_version`、`request_id`、UInt64 十进制字符串、null 合法性和响应必填字段严格检查。
- 业务 Schema 与 API Schema 基线错配、缺文件和篡改必须启动失败。

**验收：**

- [x] 管理请求在进入 RunService 前完成 Schema 验证（软件回归）。
- [x] RunService 输出在写入 socket 前再次通过响应 Schema（软件回归）。
- [x] 没有改动 `docs/interfaces/baseline` 冻结文件。

### Task 2：模拟器 Run 域与 CREATE/GET

**目标：** 先建立无网络副作用的创建、查询、状态、revision 和幂等边界。

**计划代码：**

- 新增 `input_simulator/run_store.py`：单进程有界 Run/operation/request 注册表。
- 新增 `input_simulator/run_service.py`：四命令的纯业务边界，首先完成 CREATE/GET。
- 新增 `input_simulator/run_template.py`：只从允许的固定模板解析资源和链路。
- 复用 `input_simulator/source_inputs.py`、`protocol.py`、`scenario.py` 完成实际资源字节、哈希、模型分支和场景审核。
- 新增 `tests/icd_gateway/test_simulator_run_service.py`。

**CREATE 顺序：**

1. 验证 API 版本、幂等键、共同基线和参数结构。
2. 解析实际 `package_ref`、`scenario_ref`、`source_binding_ref` 和 `link_ids`，禁止路径逃逸和请求端任意文件访问。
3. 审核完整 `run_configuration` 与 `source_inputs`，核对 model/scenario/resource/baseline 一致性。
4. 生成模拟器 `run_id`，将规范化快照与资源证据固化，返回 `READY/NOT_RUN`。
5. CREATE 不打开 Session、不发 RunConfigure、不调用工具、不访问 HIL。

**幂等和竞态：**

- 相同 `request_id` 与相同规范请求返回首次响应。
- 相同 `request_id` 与不同内容返回 `IDEMPOTENCY_CONFLICT`。
- 首轮只允许一个非终态 Run；新建冲突返回 `CONTROL_CONFLICT`。
- revision 按 Schema 使用十进制 UInt64 字符串，所有状态改变递增一次。

**验收：**

- [x] CREATE 成功只证明模拟器配置和资源已通过检查（软件回归）。
- [x] 基线、模型、场景、资源、初值或链路不一致时，在任何 TX 前拒绝（软件回归）。
- [x] GET 返回完整 v0.3 Run，不删减首轮未关心但 Schema 必填的字段（软件回归）。

### Task 3：HIL 第一圈初始化与 CONFIGURED 边界

**目标：** 让 HIL 对完整快照执行一次真实初始化，并以实际读回证明 `CONFIGURED`。

**计划代码：**

- 新增 `icd_gateway/hil_backend.py`，实现同一实际模型的 `ModelConfigurationBackend`、`ModelLifecycleBackend` 与必要状态读取接口。
- 新增 `icd_gateway/preparation_service.py`，在非正式 Session 的 HIL 内部管理边界复用同一真实配置后端。
- 修改 `python_services/spring_protocol.py` 与 `spring_ws_server.py`，提供第一圈初始化消息；该消息是 HIL 内部对接协议，不是新前端 URL。
- 重构 `python_services/model_runtime.py`：将“通信进程就绪”、“模型已配置”、“模型运行”与“进程关闭”分开。
- 修改 `c_core/src/flight_state.h`、`main_rt.c`、`model_rt_wrapper.c/.h`，建立真实 STOPPED/CONFIGURED/RUNNING/PAUSED/FAILED 边界与原子初始化/读回。
- 为本地 HIL 后端增加严格有界请求/回执，不将现有自由 JSON 命令当正式网络 ICD。

**初始化原子性：**

- 写入前读当前模型、状态、资源和安全输出。
- 完整准备模型、地形/资源、初始状态和全部 `initial_inputs`，不将请求值复制为伪读回。
- 在同一安全边界内完成配置，读回实际配置、状态、初始输入、控制源、执行器和 model step。
- 只有读回与请求规范等值、步未推进、控制源 `NONE`、输出安全时才返回成功。
- 保存 `prepare_id/config_id/config_sha256/baseline/model/revision`。
- 相同快照重复请求只返回原结果或重新读回核对，不再次初始化；不同快照必须拒绝。

**当前软件联调证据：** 正式 ERT 产物经 `ResourceStore`、
`CcoreConfigurationBackend` 和 `PreparationService` 验证为
`CONFIGURED`、模型步 `0`、控制源 `NONE`、revision `1`，并对初始状态和
完整输入快照做了读回等值核对。该结果不替代目标实时/实体链路资格。

**验收：**

- [x] 初始化前后 model step 不变，无 CAN/UDP 测试激励（软件联调）。
- [x] HIL 真实状态为 `CONFIGURED`，完整读回与快照一致（软件联调）。
- [x] 资源解析、哈希/模型/初值/读回错误均在写入前或读回校验时失败（软件层）。
- [x] 第一圈不使用旧 START 来代替初始化。

### Task 4：HIL 正式网关与真实模型消费服务组装

**目标：** 把现有抽象服务组装成目标 HIL 可运行的单一生产入口。

**计划代码：**

- 新增 `icd_gateway/hil_service.py`，共享一个 Contract、SessionRegistry、ModelQueue、Receiver 和实际 HIL backend。
- 修改 `icd_gateway/__main__.py` 和 `config.py`，从明确的目标配置安装：
  - ModelConfigurationService；
  - ModelLifecycleService；
  - StatusService/真实模型视图；
  - 已有输入 ModelConsumerService；
  - UDPGateway 与 CANGateway；
  - 资源、证据和会话清理所有者。
- 修改 `receiver.py` 的 Capabilities 组装：只在对应真实后端安装且通过启动自检后公布 message/probe/initialization readiness。
- 增加 `tests/icd_gateway/test_hil_service.py`、`test_hil_backend.py`和必要的 C 测试。

**核心行为：**

- 正式 SessionOpen 只授权会话，不启动模型。
- 模拟器在第二圈提交与第一圈完全相同的 RunConfigure 时，HIL 做读回核对并返回 APPLIED，但不重复初始化。
- 不同 RunConfigure 在任何模型写入前返回失败，不自动覆盖已准备环境。
- Lifecycle START 只能从 CONFIGURED 进入 RUNNING；STOP 从活动态进入 STOPPED，完成安全输出、撤权和队列处置后才返回 APPLIED。
- 输入 APPLIED/CONSUMED 必须来自实际模型边界读回，不从 Receiver 状态或成功解码推断。

**当前软件联调进度：** `CcoreHILService` 已将同一 Contract、SessionRegistry、
ResourceStore、RunConfigure backend、PreparationService 与 Lifecycle backend
组装为显式服务所有者；CLI 只有显式给出 C-core endpoint 和资源根目录时才安装。
`START`/`STOP` 已在 C 模型目标步取得应用回执和直接读回。`STEP` 因没有逐步
State132 证据而保持写前 `UNSUPPORTED`，状态/完整输入消费者与实体 CAN FD/网卡
仍待后续任务完成。

**2026-10-21 软件实测：** 使用重新生成的正式 `quadrotor_hil_rt` 进程、真实
UDP C-core endpoint 和标准 Receiver 完成首圈 `PreparationService`，随后通过
正式第二圈 SessionOpen/RunConfigure 收到 `APPLIED`（先核对 C 端冻结配置且没有
再次发送 `configure`），再由 Lifecycle.START 在模型步 0 收到 `APPLIED`。
该证据仅覆盖本机软件联调，不构成实体总线、Linux HIL 或物理对象资格。

**2026-10-21 第二圈状态实测：** 独立启动正式 C 目标、CcoreHILService UDP gateway
和 SourceSession 后，首圈准备成功；第二圈同配置 RunConfigure=`APPLIED`，随后
Lifecycle.START=`APPLIED`，ID2 Status 在模型步 37 读到 `RUNNING`，Lifecycle.STOP
在目标模型步 137 收到 `APPLIED`。该测试证明 Status 服务和同配置核对可共同工作，
仍只属于本机软件联调。

**2026-10-21 State132 配置边界修复：** 复现“先跑到模型步 256 → STOP → 再次
`configure`”后状态投影仍停在 256、正式 Lifecycle START 因 `MODEL` 被拒的问题。
C-core 的 `configure` 与 `prepare_model_snapshot` 在重置 `sequence` 时同步清除旧
有效状态并调用 `populate_state()`/`record_sensor_truth()`。重建
`quadrotor_hil_rt` 后实测重新配置读回 `sequence=0`、`model_state.model_step=0`，
同一进程再次 START 在步 0 收到 `APPLIED` 并进入 `RUNNING`；`STOPPED` 下
`prepare_model_snapshot` 同样读回 0/0。该证据仅为本机软件验证。

**2026-10-21 RUNNING 状态回执一致性修复：** `get_hil_status` 原先先读全局
`sequence`、再读 `state` 生成 `model_state`；1 ms 线程在两次读取之间推进一步时，
回执会出现 `sequence=9`、`model_state.model_step=10`，正式
`CcoreLifecycleBackend.read_context` 因此以 `MODEL` 拒绝 STOP。现将状态投影改为
一次捕获的同一份快照（`ccore_capture_model_state`），回执的 `sequence`/`sim_time_s`
与 `model_state` 均来自该快照。同一探测脚本（配置、START、600 次 RUNNING 状态轮询、
30 次正式 lifecycle 上下文读取、STOP）在修复前二进制上得到 75 次步号不一致、8 次
`MODEL` 拒绝且 STOP 无法取得上下文；修复后 0 次不一致、0 次拒绝，STOP 在目标步
909 真实应用并读回 `STOPPED 909/909`。该证据仅为本机非 RT 软件验证。

**2026-10-21 输入应用实测：** 将正式生成的 `hil_contract.json` 作为显式 runtime
contract 安装后，Session Capabilities 发布 ID10；运行中的 C 目标接收完整 Environment
风场快照（`wind_n_mps=1.0`）并在目标步 140 返回 `APPLIED`（probe 1010、revision 1）。
该回执来自 `BindingModelConsumerService -> ContractModelBridge -> C stage_icd_group`
的读回链，而非本地发送成功。

**验收：**

- [x] 默认未配置后端继续明确 `TARGET_MISSING`，不安装成功假后端（软件回归）。
- [x] 目标配置下 Capabilities 与实际已安装消费者完全一致（软件回归）。
- [ ] CAN FD 和 UDP 按 ICD 各走正式链路，不将所有报文强制改走同一通道。

### Task 5：模拟器后台 START 执行链

**目标：** 把现有一次性发送组件组装为可查询、可停止、不重放副作用的后台执行。

**计划代码：**

- 新增 `input_simulator/run_executor.py`，单工作线程、有界命令队列和显式取消标记。
- `FormalHILExecutionBackend` 已实现最小第二圈：每次操作创建一个 SourceSession，
  在同一会话中取得 RunConfigure、Lifecycle.START、ID2 Status 和 Lifecycle.STOP
  的正式回执；没有实际场景执行器时 STOP 只产生 `INCOMPLETE`，不伪造 PASS。
- 新增 `input_simulator/runtime_factory.py`，从固定模板构建 SourceSession、UDPDispatcher、CANSignalSender、ScapySource、NativeToolCoordinator、ScenarioDriver 和证据记录器。
- 扩展 `run_service.py` 实现 `simulator_run_control.START`。
- 复用而不改写 `scenario_execution.py`、`scenario_driver.py`、`native_scenario_actions.py`、`model_clock.py`、`evidence_recorder.py`。
- 对 `send_run.py` 只抽取可复用的发送/反馈映射；不将其阻塞式 `run()` 直接放入 HTTP 请求线程。

**START 顺序：**

1. 校验 `expected_revision`、Run=READY、可用动作、单任务互斥和快照未变。
2. 预留全程记录/证据空间并创建 operation，将管理请求返回 `ACCEPTED`。
3. 建立正式 SourceSession，核对授权身份、模型、基线、链路和 Capabilities。
4. 发送完整相同 RunConfigure，只接受 HIL 的真实等值读回/APPLIED；不同配置立即失败。
5. 发送 Lifecycle.START，保存会话、sequence、transaction、request_id 和原始 TX/RX。
6. 只在 START APPLIED 或同一执行的新鲜 RUNNING Status/State 到达后将 Run 转为 RUNNING。
7. 在真实 model step 上执行固定场景，保留 CAN/UDP 原链路、反馈关联、断言与清理语义。
8. 成功、断言失败、链路失败和证据不足分别映射 Run result，不把 FAIL 断言自动当作 HIL 运行故障。

当前最小执行后端已覆盖步骤 3--7 中冻结的直接 ETHGEN/ID10 场景：它在实际
模型步调度该输入、保留 TX/APPLIED 事实并由 C 模型边界读回。CAN/Scapy 原生
动作、场景断言及完整证据归档仍须由原有 runtime factory 接入；这些缺口存在时
不得宣告 PASS。

实现约束：固定场景的目标步可能超过单个 UDP 业务请求的 ACK 等待窗口，不能把
`SourceSession.request()` 直接作为场景调度器，否则会把传输重试误当成新的模型
写入。场景动作必须通过现有 `ScenarioExecution` / `RuntimeTargetAuthorizer` /
`UDPDispatcher` 的原始分配、TX/RX 关联和 APPLIED 证据路径接入；在该路径完成前，
最小执行器只可安全运行至 START/STOP 并报告 `INCOMPLETE`。

**2026-10-21 最小场景实测：** `FormalHILExecutionBackend` 在真实 C 目标上完成
START，按固定 ScenarioSource 在模型步 250 调度唯一的 ETHGEN/ID10 风场事件，并从
C 绑定消费者取得 APPLIED；随后 STOP。执行结果保留为 `INCOMPLETE`，证据引用包含
`scenario-wind-step-01-applied` 与 `lifecycle-stop-applied`，因为断言、完整清理与
CAN/Scapy 原生动作尚未作为此最小路径的一部分。

最小 STOP 还会在 Lifecycle.STOP 的 APPLIED 后，以同一 Session 的 ID2 直接核对
`state=STOPPED`、`control_source=NONE` 和返回模型步等于 STOP target；该读回缺失或
不一致时 Run 不得结束。真实软件联调已获得 `status-stopped-safe` 证据。

最小 UDP 场景路径会为每个已允许的输入保留独立管理 Record：发送前为 `TX`，C 端
目标步读回后为 `APPLIED`。APPLIED Record 保留 event ID、模型 step、sim time、完整
应用值、绑定 mapping IDs 与 C 回执证据引用，最终 OPERATION_RESULT 不再是唯一的
场景证据载体。

在 START 改变 Run 状态、创建 SourceSession 或发送任何 HIL 请求之前，RunStore 会
预留 START/RUNNING/本地 STOP/HIL STOP/terminal 和每个允许场景事件的 TX/APPLIED
记录空间；容量不足明确返回 `QUOTA_EXCEEDED` 并保持 READY，终态释放未使用的预留空间。

**超时规则：**

- START 发送后超时，Run 进入 WAITING/不确定记录，保留原请求并继续读 Status/Record，不生成新 transaction 重发。
- Session 到期、时钟不新鲜、Capabilities 变化或控制权变化时立即停止新激励分配，保留已发生事实。
- 后台工作线程异常必须落为 FAILED/INCOMPLETE 记录，不导致 HTTP 服务静默丢任务。

**验收：**

- [x] START HTTP 处理在受理后及时返回，不阻塞到场景结束（软件回归）。
- [x] 同一 START 重试不会创建第二个会话或重复激励（软件回归）。
- [x] Run 只在真实 HIL 证据后标记 RUNNING（软件回归）。

### Task 6：STOP、安全清理和记录查询

**目标：** 提供可靠停止路径，并将真实控制/反馈事实转换为 v0.3 RecordPage。

**计划代码：**

- 扩展 `run_executor.py` 和 `run_service.py` 实现 STOP。
- 新增 `input_simulator/record_store.py`，以单调 cursor 保存管理操作、TX/RX、RECEIVED/APPLIED/REJECTED、SAFETY、TOOL_ERROR 和 OPERATION_RESULT。
- 连接 `evidence_recorder.py` 的持久化段，保存完整原始证据；Record 只存索引和必要摘要，不复制无界原包。
- 新增 STOP/records 单元、竞态、容量和恢复测试。

**STOP 顺序：**

1. 用当前 revision 做 CAS，将 Run 转为 STOPPING，禁止新场景动作和周期发送。
2. 停止本 Run 拥有的工具和调度器，保留停止失败证据，不影响其他进程。
3. 发送一次 Lifecycle.STOP，不因超时自动重发。
4. 等待 HIL 实际停止、安全输出、控制撤权和必要队列清理的关联证据。
5. 证据完整后进入 COMPLETED；结果不确定时保留 STOPPING/INCOMPLETE 及安全补救入口，不伪造已停止。

**记录规则：**

- `after_cursor` 只返回新记录，`next_cursor` 单调递增。
- 容量不足时在产生新副作用前失败；不静默覆盖。
- 如果按策略删除旧记录，`retention_gap=true`，不返回伪连续游标。
- 服务重启后不自动恢复未完成激励。持久证据可重建为 INCOMPLETE/不确定 Run，但不重放 START/STOP。

**验收：**

- [x] STOP 的本地发送停止、HIL 应用停止和最终任务结束是三条独立记录（软件回归）。
- [x] RecordPage 通过 v0.3 Schema，每条记录可追溯到同一 simulator run/session/transaction（软件回归）。
- [x] 断言 FAIL、证据不足、HIL 故障和工具故障不被合并为同一结果（软件回归）。

### Task 7：模拟器 HTTP 服务、配置与部署

**目标：** 提供一个稳定、有界、可运维的模拟器服务入口。

**计划代码：**

- 新增 `input_simulator/api_server.py`，仅暴露 `POST /api/simulator/commands`。
- 新增 `input_simulator/service_main.py`，启动时完成基线、模板、目录、端口、网卡/通道和依赖自检。
- 新增 `config/minimal-integration-simulator.yaml` 与 HIL 目标配置，配置绑定地址、请求上限、连接/启动/停止超时、1 s 建议查询间隔、模板路径、证据目录和基线指纹。
- 新增 `deploy/systemd/input-simulator.service` 及运维说明；HIL 网关服务同样以明确配置启动。
- 新增 API 端到端测试：真实 TCP socket、JSON 大小上限、错误 Content-Type、断开连接、并发冲突和服务关闭。

当前实现提供 `config/minimal-integration-simulator.json` 和
`input_simulator.manage --runtime-config --state-dir`：运行配置严格固定 Source 身份、角色、UDP
源/反馈/HIL 地址及 Stop lead；只有显式给出该文件才会安装正式执行 backend，默认
服务仍是无网络副作用的 CREATE/GET/查询入口。生产 unit 同时传入一个由 `hil`
拥有的 state directory；Run、幂等响应和 Records 原子落盘。进程重新启动时，只有
原先的活动 Run 会被归档为 `COMPLETED/INCOMPLETE`，不会恢复 SourceSession、后台线程
或 START/STOP 副作用。

生产 unit 以 `/opt/hil/.venv/bin/python` 运行模拟器，并在安装任何 unit 前验证这是能导入
本仓库、`jsonschema` 和 `referencing` 的隔离 Python 3.12 环境。它不得使用旧 HIL 服务的
`/opt/hil/venv/bin/python3`（Python 3.6）；缺少独立运行时或依赖时安装脚本直接失败，
不会留下一套可被误启用的部分部署。

**HTTP 边界：**

- 限制请求头和 body 大小，只接受 UTF-8 JSON object。
- 不向请求方暴露任意文件路径、命令行、进程参数或 shell 执行。
- HTTP 运输错误与 v0.3 管理错误分开；业务失败返回完整管理响应。
- 停服时先停接新请求，再执行已知安全清理；无法确认 HIL 停止时明确留存未完成事实。

**验收：**

- [ ] 从新环境按文档可启动 HIL 网关与模拟器服务。
- [ ] 端口冲突、配置错误、基线错误和目录不可写时启动失败，不局部运行。
- [ ] 服务账户、目录权限、网卡访问和日志/证据上限已配置。

### Task 8：两圈端到端验收

**目标：** 使用实际 HIL 模型、正式 CAN FD/UDP 链路和模拟器 HTTP 服务完成方案的首轮验收。

**测试层次：**

1. 单元：Schema、快照、状态机、revision、幂等、Record cursor、配置等值核对。
2. 组件：模拟器 HTTP -> RunExecutor；Receiver -> 真实 HIL backend；本地控制 -> C 原子边界。
3. 软件联调：真实进程、回环/vcan 仅用于故障注入和回归，不算物理资格。
4. 目标联调：Linux HIL、真实 CAN FD/网卡、原工具链和实际模型。
5. 与 3.3/3.6 的联调只验证外部契约与调用结果，不修改其业务代码。

**必测正向流程：**

- [ ] 第一圈初始化成功，HIL=CONFIGURED，模型步未前进，无测试激励。
- [ ] CREATE 返回 READY，快照和资源可追溯，HIL 无副作用。
- [ ] START 经模拟器、正式链路到 HIL，取得实际 RUNNING 依据。
- [ ] 固定场景激励在目标步实际应用，模拟器保存 TX/RX/APPLIED 关联证据。
- [ ] HIL 遥测继续从既有通路发给 3.6，不经模拟器转发。
- [ ] STOP 取得 HIL 真实停止、安全输出和撤权证据，Run 后续不再发送激励。
- [ ] GET 与 records 可还原整个执行，无重复 START/重复终态/跨 Run 数据污染。

**必测负向流程：**

- [ ] 第一圈未准备、准备失败或读回不完整时，第二圈无 TX。
- [ ] `configSha256`、RunConfigure、SourceInputs、resource hash 或 baseline 任一不一致时拒绝。
- [ ] 过期 revision、重复 request_id 不同内容、双 START、双 STOP 和第二个活动 Run 均不产生重复副作用。
- [ ] START 回执丢失时不自动重发，通过 Status/Record 得出已执行或不确定结果。
- [ ] 模拟器断网、HIL 反馈断链、CAN bus-off、工具退出、证据盘满和进程重启后均不伪造 PASS/STOPPED。
- [ ] 旧 Session/旧 Run 的延迟反馈不会归入新 Run。

**证据交付：**

- 环境、软件、ICD、模型、模板和资源哈希。
- 第一圈请求、实际读回和准备结果。
- 模拟器四命令请求/响应、Run 状态轨迹和 RecordPage。
- 正式会话、原 TX/RX、HIL APPLIED/Status/State、模型读回和停止/安全证据。
- 一份明确区分软件联调、Linux 物理链路、实际模型和外部后端联调结论的验收报告。

**2026-10-21 软件层验收记录（Linux/回环 UDP/vcan，≠ 物理 CAN FD/RT 资格）：**

证据汇总见 `artifacts/icd_gateway/task8-two-circle-acceptance-20261021.json`，逐次运行证据为同目录 `task8-positive-clean-*`、`task8-positive-tuned-*`、`task8-negative-*` 和 `task8-scenario-margin-failure-*`。

- 调度参数：`config/minimal-integration-simulator.json` 由 `stop_lead_steps=100, status_poll_ms=50` 调整为 `180/20`；`tests/icd_gateway/test_management_http.py` 同步固定新值。原因是旧值下 ID10 仅在 250 步边界前约 27–35 步才进入 C，存在边界错过风险。
- 正向：新 store 空闲条件下连续 5/5 通过（run-12968b32…、run-496e4d4e…、run-873a2466…、run-ccd4e24f…、run-683cea6d…），ID10 均在 250 步实际应用且 TX=1，STOP 取得 `HIL_STOP_APPLIED`、`status-stopped-safe`，停机后 `control_source=NONE`、电机指令为零；提前期实测 113–152 步。
- 正向压力观察：同一配置在 store 增长期间 4 次通过（提前期 32–54 步），第 5 次在 1275 项回归套件并发、store≈300 请求时以 `EVIDENCE_TIMEOUT` 错过 250 步边界；抓包显示 START 回执到首次心跳耗时 261 ms，主因是 executor 通过 run store 持久化 `HIL_START_APPLIED`（整库重写 + fsync）。
- 负向（直接正式 message 3，`random_seed` 1→2）：网关语义门在 CONFIGURED 下返回 Ack 130 `stage=FAILED,error=STATE`；C 未收到 `configure`，`model_revision/sequence/lifecycle` 前后不变，通过。
- 负向（第一圈未准备）：停止 `hil-prepare` 并重启 core 后，第二圈仍由自己执行 `configure`（revision 0→1）、START、在 250 步 TX，最终 STOP 于 876 步。该必测负向**未通过**，即既有 Finding B（STOPPED-configure gap），本次未修复，保留为开放验收缺口。
- 回归：完整套件 1275 项中 1274 通过；`test_scenario_driver.ScenarioDriverTests.test_service_poll_session_change_cannot_cache_completion` 在满载运行中报 `TARGET_MISSING`，单独复跑该模块 31/31 通过，判定为负载时序抖动，与本次运行配置改动无关。管理 HTTP 聚焦测试 8/8 通过。
- 部署缺陷（未在本次修复）：run store 的 512 条请求登记无淘汰，耗尽后管理 HTTP 返回 400 `invalid_request`（已归档 `run-store-exhausted-20261021T1452Z.json`）；每条管理命令整库重写并 fsync，且该持久化位于 START 回执与首次心跳之间，造成上述提前期随 store 增长而下降（已归档 `run-store-after-run5-load-failure-20261021T1508Z.json`）。建议改为追加式日志或受限/压缩持久化，并把 RUNNING 证据写入移出 ID10 调度关键路径。

## 7. 实施顺序与门禁

| 顺序 | 任务 | 进入条件 | 退出门禁 |
|---:|---|---|---|
| 1 | Task 0 契约冻结 | 方案已确认 | 请求/响应/错误/证据样例齐全 |
| 2 | Task 1 管理 Schema | Task 0 | v0.3 请求和响应可以程序严格验证 |
| 3 | Task 2 Run CREATE/GET | Task 1 | 无网络副作用的完整 Run 域通过测试 |
| 4 | Task 3 HIL 初始化 | Task 0 | 实际模型 CONFIGURED 读回通过 |
| 5 | Task 4 HIL 正式网关 | Task 3 | 相同配置无副作用核对，START/STOP 真实应用 |
| 6 | Task 5 START | Task 2 + Task 4 | 单次 START 到真实 RUNNING 与场景输入 |
| 7 | Task 6 STOP/Record | Task 5 | 真实停止证据与可分页记录 |
| 8 | Task 7 服务化 | Task 2/5/6 | 模拟器和 HIL 服务可部署、可运维 |
| 9 | Task 8 验收 | 全部任务 | 正向与负向两圈流程通过 |

不允许为赶联调跨过下列门禁：

- HIL 未能真实 CONFIGURED 时不得启用模拟器 START。
- HIL 只返回 RECEIVED/VALIDATED 时不得宣告模型已应用。
- STOP 无真实安全证据时不得标记完整停止。
- vcan/回环/单元测试通过时不得勾选 Linux 物理资格。

## 8. 回归策略

每个 Task 必须依次执行：

1. 新增针对本 Task 的失败测试，证明缺口存在。
2. 完成最小代码后运行聚焦测试。
3. 运行 `scripts/test_icd_runtime.py` 覆盖共同 ICD/gateway/input_simulator 回归。
4. 运行与 `c_core`、Python 3.6 旧服务、模型合同和 systemd 相关的定向回归。
5. 核对冻结基线、冻结源文件和历史交接文件未被意外修改。
6. 将 Linux/实体未执行或已执行事实追加到 `linux-development-backlog.md`，不覆盖旧记录。

高风险修改必须额外覆盖：

- 严格生命周期矩阵和非法跳转。
- 配置部分写入、写后读回不等、写入超时与不可确定效果。
- START/STOP 响应丢失、延迟、重复和乱序。
- Session 过期、旧会话反馈、序号耗尽、revision 竞态和记录背压。
- STOP 期间工具不退出、CAN bus-off、反馈断链、证据写盘失败和服务被杀。

## 9. 外部联调依赖

以下为实施/验收输入，不是本计划的后端开发任务：

- 3.6 提供实际的 HIL 准备请求样例，并保留本次 `prepare_id/config_id/config_sha256`。
- 3.3 按 v0.3 发送完整 CREATE/GET/CONTROL/RECORDS 请求，每次调用使用独立 `request_id`。
- 3.3 不要求模拟器代替 3.6 转发遥测，3.6 不再发送同一第二圈 START/STOP。
- 提供首轮实际 model/package/scenario/source binding/link/resource 值、文件和哈希。
- 目标 HIL 通信服务、CAN FD 设备、网卡、时钟源和必要原工具在联调前可用。

外部样例或设备未到位时，允许完成软件层实现与替身回归，但对应目标验收保持“未执行”，不以模拟结果代替。

## 10. 完成定义

只有同时满足以下条件，本最小联调计划才可标记完成：

- [ ] 模拟器四命令与完整响应均通过 v0.3 API Schema。
- [ ] 第一圈对实际 HIL 初始化并读回 CONFIGURED，没有提前运行或发送激励。
- [ ] 第二圈的同配置核对不会重复初始化，不一致配置在任何测试 TX 前拒绝。
- [ ] START 经模拟器、正式 CAN FD/UDP 与 HIL 实际消费后得到运行证据。
- [ ] 固定场景实际执行，真实反馈可通过 records 查询，无证据时不报 PASS。
- [ ] HIL 遥测保持直接到 3.6 的既有路径。
- [ ] STOP 后取得实际 HIL 停止和安全证据，不只是模拟器不再发送。
- [ ] 幂等、revision、超时不重发、旧会话隔离、单活动任务和唯一终态规则通过负向验收。
- [ ] 软件回归、Linux 目标机、实际链路和实际模型的结论分开记录，不提前勾选资格。
- [ ] 本计划未实现或修改 3.3/3.6 后端业务代码。
