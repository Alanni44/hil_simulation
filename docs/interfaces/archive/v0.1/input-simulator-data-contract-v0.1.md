# 输入模拟器前后端数据契约

版本：0.1。日期：2026-10-02。状态：接口评审草案，尚未实现或冻结。

## 1 范围与接口边界

本文供前端、管理后端及模拟器服务共同确定数据字段、命令、状态和错误处理。建议沿用当前WebSocket JSON命令形式，不修改现有HIL命令含义。第一版使用请求查询，不主动推送事件。

应分别维护三种契约：

| 契约 | 内容 | 冻结责任 |
|---|---|---|
| 本文管理契约 | 页面配置、资源引用、运行操作、查询与报告 | 前端、管理后端、模拟器开发方 |
| 3.3与3.6正式ICD | 正反向消息、线上编码、物理传输、时序、安全及规定反馈 | 3.3、3.6与买方共同确认 |
| 3.6模型契约 | 接收消息到模型输入、任务及控制器的映射 | 3.6与模型开发方 |

本文JSON不能直接视为CAN载荷或以太网业务报文。内部request_id、run_id、operation_id、记录游标和模型步号不自动占用正式报文字段。管理版本api_version与正式ICD版本独立。

配套文件为同目录的 `input-simulator-api-v0.1.schema.json` 和 `input-simulator-api-v0.1.examples.json`。Schema采用[JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-validation)描述数据形状；跨字段、运行状态、授权、哈希及正式ICD关联规则仍需服务端验证。Schema不是现有接口已实现的声明。

## 2 通用约定

| 项目 | 定义 |
|---|---|
| 编码 | UTF-8 JSON；字段名snake_case；枚举大写；拒绝NaN、Infinity及非有限数值 |
| 标识符 | 非空字符串，最长128字符；客户端不能自行生成服务端资源或运行标识 |
| 64位整数 | 计数、步号、微秒时间和修订号使用十进制字符串，如 `"12000"`；不能以JS浮点数解析后再发送；服务端检查范围0至18446744073709551615 |
| 常规数值 | 工程量为JSON number；页大小、毫秒超时为范围明确的integer |
| 时间 | 审计时间为UTC ISO 8601，如 `2026-10-02T02:00:00.000Z`；页面可转本地时区显示 |
| 哈希 | 服务端计算的64字符小写SHA-256；客户端提交引用，服务端核对真实内容，不相信客户端哈希声明 |
| 空值 | 只在Schema明确允许时使用null；其他可选字段未提供时省略 |
| 单位 | 信号目录逐字段定义单位；不能由页面推断角度制、坐标系或高度基准 |
| 分页 | cursor为不透明字符串；limit默认100，范围1至500；空next_cursor为null |
| 未知字段 | 新管理命令拒绝未知字段；不按默认值悄悄忽略 |
| 安全 | 身份来自认证连接；授权由服务端校验；不接收任意shell、主机路径、脚本代码或设备凭据 |

新增命令统一使用 `simulator_` 前缀。现有 `set_inputs`、`load_mission`、`tune`、`virtual_fc_*`、GitLab及UE4 V2/V3保持原格式。新增响应结构只适用于本草案命令，不强制套到旧命令上。

## 3 请求与回执

### 3.1 请求

沿用 `cmd + params`。request_id放在params内，与现有管理命令的关联方式一致。

```json
{
  "cmd": "simulator_run_control",
  "params": {
    "api_version": "0.1",
    "request_id": "ui-stop-001",
    "run_id": "run-demo-001",
    "expected_revision": "3",
    "action": "STOP"
  }
}
```

`api_version`与`request_id`必填。重试同一逻辑操作时复用request_id；服务端以认证主体、命令和request_id去重。相同键但载荷不同返回IDEMPOTENCY_CONFLICT；服务端不得对重复请求再次启动工具或再次下发输入。去重保存策略属于部署配置，能力查询声明retention_ms；过期后不可盲目重试非幂等命令，先查询状态。

### 3.2 响应

| 字段 | 类型 | 说明 |
|---|---|---|
| kind | string | 固定RESPONSE，与未来事件消息区分 |
| api_version | string | 固定0.1 |
| request_id、cmd | string | 原请求关联字段 |
| status | enum | SUCCESS、ACCEPTED、REJECTED、FAILED |
| code | string | 稳定机器码，不能依赖message文本分支 |
| message | string | 可读说明，不泄露堆栈或凭据 |
| timestamp | string | 服务端UTC审计时间 |
| operation_id | string或null | 已排队操作的服务端标识；ACCEPTED时必填，其他状态为null |
| data | object或null | 按命令返回对应DTO；拒绝或失败时为null |
| error | object或null | 成功或受理时为null；失败时包含code、retryable和字段明细 |

SUCCESS表示查询、保存或创建已完成；ACCEPTED仅表示控制或输入更新已排队。ACCEPTED不能表示已发送、已接收、已应用或测试通过。实际结果通过run_get及records_list确认。

异步操作失败不修改历史ACCEPTED回执，而在运行状态、operation_id关联记录及报告中体现。run_create只创建VALIDATING运行并返回SUCCESS，不自动取得发送控制权或启动发送。

### 3.3 错误

错误结构：`code`、`retryable`、`details[]`。error.code必须与响应code一致；details成员为 `path`（JSON Pointer，如 `/params/values/wind_n_mps`）、`code`、`message`。拒绝时不得部分保存场景或部分下发一组值。

| code | 含义 |
|---|---|
| INVALID_REQUEST | JSON、字段类型、长度或必填字段不合法 |
| UNSUPPORTED_VERSION | 管理版本不支持 |
| UNAUTHORIZED / FORBIDDEN | 未认证或无对应操作权限 |
| NOT_FOUND | 引用的资源、场景或运行不存在 |
| VERSION_CONFLICT / IDEMPOTENCY_CONFLICT | 修订冲突或重复标识对应不同请求 |
| ICD_NOT_FROZEN / PROFILE_MISMATCH | 正式模式未冻结，或版本/哈希不匹配 |
| MODEL_MAPPING_MISSING | 未定义合法模型/任务映射 |
| RESOURCE_INVALID / TOOL_UNAVAILABLE | 资源不可用或选定工具不具备能力 |
| STATE_CONFLICT / CONTROL_CONFLICT | 状态不允许或发送权冲突 |
| VALUE_OUT_OF_RANGE / OPERATION_NOT_ALLOWED | 工程量或操作不被批准 |
| TIMEOUT / EVIDENCE_INCOMPLETE / INTERNAL_ERROR | 执行超时、证据缺失或内部故障 |

FAILED用于同步操作实际执行失败，REJECTED用于执行前拒绝。retryable不授权浏览器自动重发非幂等动作。未知错误码显示失败并保留原码，不能按成功处理。

## 4 数据对象

### 4.1 ProfileRef与ScenarioRef

ProfileRef：`profile_id`、`version`、`profile_hash`。用于固定正式或示例接口配置，不能仅按名称加载最新版。

ScenarioRef：`scenario_id`、`revision`、`scenario_hash`。每次保存形成不可变修订；运行绑定指定修订，不随后续页面编辑变化。

### 4.2 Profile接口配置与信号目录

Profile包含 `ref`、`name`、`approval`（DRAFT/FROZEN）、`transports[]`、`messages[]`。profile_hash是配置内容哈希，不是审批签名；FORMAL必须同时核对有效冻结批准记录。

MessageDefinition包含 `message_id`、`name`、`direction`（TO_36/FROM_36）、`category`、`transport`、`wire_definition_ref`、`mapping_ref`、`signals[]`。其中两个ref为受控服务端标识，不是任意文件路径。

SignalDefinition包含 `signal_id`、`name`、`value_type`（NUMBER/INTEGER/BOOLEAN/STRING/NUMBER_VECTOR）、`unit`、`minimum`、`maximum`、`dimension`、`writable`。NUMBER_VECTOR必须有dimension；数字类型的minimum/maximum可以为null，表示目录未给数值边界而非无限授权。最终范围仍由正式ICD和模型契约共同决定。

前端依据信号目录生成表单。`values`为signal_id到工程量的对象；服务端验证键名、类型、单位、维度、范围和writable。JSON Schema无法单独验证某运行动态绑定的信号目录。

### 4.3 Resource资源

| 字段 | 定义 |
|---|---|
| resource_id、name | 服务端资源标识及显示名 |
| kind | PROTOCOL、SCENARIO、HISTORY |
| format | DBC、ARXML、ICD_JSON、SCENARIO_JSON、SCENARIO_YAML、CAN_LOG、PCAP、ENGINEERING_JSONL |
| size_bytes、sha256 | 十进制字符串大小和内容哈希 |
| validation_status | PENDING、VALID、INVALID |
| validation_errors | ErrorDetail数组 |

kind/format必须对应：PROTOCOL只用DBC/ARXML/ICD_JSON；SCENARIO只用SCENARIO_JSON/SCENARIO_YAML；HISTORY只用CAN_LOG/PCAP/ENGINEERING_JSONL。

本文第一版定义资源查询与已有资源引用，不定义二进制上传或文件下载。上传/审批入口须在管理后端确定后另行补充；不能让前端向执行服务提交本机路径或直接启动canplayer。

### 4.4 ScenarioDraft与Scenario

ScenarioDraft包含 `name`、`profile_ref`、`model_binding_ref`、`resource_ids[]`、`steps[]`。步骤按有序数组执行，每项有唯一step_id和at_sim_time_us。

| kind | 步骤字段 | 含义 |
|---|---|---|
| INPUT | message_id、values | 经批准工具和正式ICD发送工程量，不能直接写C模型 |
| WAIT | input_step_id、stage、timeout_ms | 等待此前INPUT步骤的RECEIVED/APPLIED/RESPONSE证据 |
| REPLAY | resource_id、replay_policy_ref | 按后台批准的方向、时序和重建策略回放 |
| FAULT | fault_case_ref | 调用预先批准、声明支持范围的异常用例 |

at_sim_time_us采用运行仿真时钟，必须非递减，同一时刻按数组顺序执行。WAIT仅暂停后续场景步骤，不自动暂停模型或心跳；其timeout_ms按本服务单调时钟计算。等待结束后若下一个步骤已经超过批准调度迟到阈值，则失败停止，不能集中补发旧指令。暂停/恢复如何影响仿真时钟，必须遵循当前profile和模型能力。

保存返回Scenario：`ref`、`definition`、`validation_status`、`validation_errors`。保存成功不表示可运行；只有VALID且全部依赖可用时运行才进入READY。接口配置、resource_ids与replay引用必须一致，服务端检查资源审批、哈希、模型和信号映射。

### 4.5 Run运行

| 字段 | 定义 |
|---|---|
| run_id、revision | 服务端运行标识；revision为单调递增十进制字符串，用于操作并发检查；仅管理状态变更或控制操作受理时递增，不因统计计数刷新或查询递增 |
| mode | EXPLORE或FORMAL，仅影响准入及报告资格，不改变线上编码或3.6业务路径 |
| profile_ref、scenario_ref | 实际绑定的不可变版本 |
| source_binding_ref | 批准的设备/部署/发送授权绑定，不包含mock/real业务开关 |
| toolchain_ids | 服务端批准工具分支标识；不接收shell命令 |
| state | VALIDATING、BLOCKED、READY、RUNNING、WAITING、PAUSED、STOPPING、COMPLETED、FAILED |
| result | NOT_RUN、RUNNING、PASS、FAIL、INCOMPLETE |
| available_actions | 服务端当前允许的START/PAUSE/RESUME/STOP/RESET/STEP集合 |
| stats | tx_frames、rx_frames、received_inputs、applied_inputs、rejected_inputs，均为十进制字符串 |
| evidence_complete | 原始数据与应用记录完整性，不能仅由前端勾选 |
| last_error | Error或null |
| created_at、updated_at | UTC时间 |

典型转换：VALIDATING进入READY或BLOCKED；READY经START进入RUNNING；运行可进入WAITING/PAUSED；STOP进入STOPPING，确认安全停止后进入COMPLETED；执行失败进入FAILED。COMPLETED表示运行结束，不表示PASS，用户中止未覆盖的必选用例时result应为INCOMPLETE。VALIDATING/BLOCKED/READY的result为NOT_RUN，RUNNING/WAITING/PAUSED/STOPPING为RUNNING；COMPLETED只允许PASS/FAIL/INCOMPLETE；FAILED为FAIL且last_error必填。PASS必须同时证据完整。

RESET和STEP仅在后端能力及正式规则允许时提供。RESET先完成旧运行安全停止，再建立新的run_id和初始状态，不能清除旧证据或在同一记录域伪装时间未回退；排队回执引用旧运行，最终新run_id由operation_id关联记录返回。revision冲突返回VERSION_CONFLICT，不执行控制。STOP在RUNNING、WAITING、PAUSED可用；安全停止请求不应因为其他工具占用发送权而被阻止。

received_inputs表示标准接入接受的输入事件，applied_inputs表示实际消费/写入事件，不是CAN帧数。多帧组、去重、合并和输入覆盖均可能使计数不相等，不用减法推断丢包率。

### 4.6 Record记录

Record包含 `record_id`、`cursor`、`run_id`、`input_event_id`、`operation_id`、`kind`、`timestamp`、`clock_domain`、`monotonic_us`、`message_id`、`reason_code`、`evidence_refs[]`。

kind为TX/RX/RECEIVED/APPLIED/REJECTED/RESPONSE/SAFETY/TOOL_ERROR/OPERATION_RESULT。input_event_id是内部输入链路关联，不等同管理request_id或线上请求字段；跨帧关联按ICD规定处理。

APPLIED记录必须包含 `step_index`、`sim_time_us`、`applied_values`和至少一条evidence_ref，由真实模型输入写入点或任务消费点产生，不能由接入服务按待提交值提前生成。OPERATION_RESULT必须包含 `operation_result`（SUCCEEDED/FAILED）；RESET成功还包含 `new_run_id`。原码保存在受控证据文件中，列表只给引用，不通过WebSocket大量返回整份PCAP或凭据。

after_cursor查询服务端排序的增量记录；响应next_cursor用于下一次读取。记录顺序不等于不同主机物理时间顺序，未同步时钟不能直接计算跨设备单程延迟。运行结束、游标失效及保留期限以查询结果说明，不能静默漏掉历史记录。

### 4.7 Report报告

Report包含 `run_id`、`mode`、`profile_ref`、`scenario_ref`、`overall_result`、`evidence_complete`、`cases[]`、`artifact_refs[]`。

TestCaseResult包含 `case_id`、`required`、`result`（PASS/FAIL/NOT_RUN/NOT_APPLICABLE/INCOMPLETE）、`reason_code`、`evidence_refs[]`。PASS用例至少有一条真实证据引用。必选且适用用例只有全部PASS、证据完整时overall_result才为PASS；FAIL优先，否则缺项为INCOMPLETE。required=true不允许标为NOT_APPLICABLE，非适用性必须在冻结覆盖矩阵中先明确为非必选。EXPLORE的PASS只表示示例软件用例通过，不表示正式ICD、硬件或真实3.3验收。

## 5 命令目录

所有params均包含api_version与request_id，下表仅列业务参数。

| cmd | 业务参数 | SUCCESS/ACCEPTED时data |
|---|---|---|
| simulator_capabilities_get | 无 | Capabilities |
| simulator_profiles_list | cursor、limit | ProfilePage |
| simulator_profile_get | profile_ref | Profile |
| simulator_resources_list | kind、cursor、limit | ResourcePage |
| simulator_scenarios_list | cursor、limit | ScenarioPage |
| simulator_scenario_get | scenario_ref | Scenario |
| simulator_scenario_save | definition；更新时含base_ref | Scenario |
| simulator_run_create | scenario_ref、mode、source_binding_ref、toolchain_ids | Run；SUCCESS，不自动开始 |
| simulator_run_control | run_id、expected_revision、action | Run；ACCEPTED，operation_id必填 |
| simulator_run_update_inputs | run_id、expected_revision、message_id、values | Run；ACCEPTED，实际应用查记录 |
| simulator_run_get | run_id | Run |
| simulator_runs_list | cursor、limit | RunPage |
| simulator_records_list | run_id、after_cursor、limit | RecordPage |
| simulator_report_get | run_id | Report |

scenario_save无base_ref表示新场景；有base_ref表示在该不可变修订上提交新修订，若已存在更新则VERSION_CONFLICT。profile、model_binding及resource引用也参与内容校验。删除场景、资源上传、报告下载、实时订阅和正式profile审批不在本版命令集合中。

run_update_inputs只能更新批准的TO_36消息和writable信号，仅在允许状态下排队，整组验证失败时整组拒绝。不能伪装模型输出、任意切换控制源或绕过正式通道。

Capabilities返回 `api_version`、`supported_commands[]`、`supported_actions[]`、`modes[]`、`toolchains[]`、`bindings[]`、`idempotency_retention_ms` 和 `subscriptions_supported=false`。工具分支分别列branch_id、status（AVAILABLE/UNAVAILABLE/UNVERIFIED/OUT_OF_SCOPE）、reason。AVAILABLE仅指部署可调用，正式业务适用性仍由profile覆盖验证决定。

bindings是页面可选的受控引用目录，每项包含binding_id、kind（SOURCE/MODEL/REPLAY_POLICY/FAULT_CASE）、name、profile_ref、available。页面不得自行编造设备、模型、回放策略或故障用例标识；服务端再次校验其授权和profile兼容性。不得在绑定描述中返回凭据。

Page对象都包含 `items[]` 和 `next_cursor`，不承诺高成本的total全量计数。ProfilePage只返回ProfileSummary（ref、name、approval、transports、message_count）；ScenarioPage只返回ScenarioSummary（ref、name、profile_ref、validation_status、step_count），详情分别通过get获取，不在列表重复传全部信号和步骤。

RecordPage另包含 `run_id`、`complete`、`retention_gap`；complete表示运行已结束且没有尚未读取的记录，retention_gap=true表示保留策略导致缺失，不能据此判证据完整。增量记录的next_cursor表示最后已读取的位置，没有新记录时保持原游标；首次还没有记录时为null。它与普通列表的下一页游标语义不同，前端不能在轮询间重置已读位置。

## 6 前后端实现约束

前端通过capabilities和available_actions展示可用操作，不硬编码全部工具可用。轮询在上一次请求完成后再发出下一次，断线后停止轮询；重连先查询run状态，不能自动重新START。长操作通过ACCEPTED与后续查询反馈，不长时间阻塞WebSocket请求循环。

现有 `web/hil_api.js` 只有一个pending请求，并按下一条回复完成它。实现本契约时需增加request_id匹配、请求超时及清理，再开放并发；不能声称已有前端支持本草案。第一版仍允许串行请求，不新增未经支持的主动推送。

后端校验认证、业务权限、修订号、实际引用哈希、运行状态、发送权、工具能力和模型映射。正式执行不能仅通过JSON Schema验证就启动。服务端内部路径、凭据和源码异常细节不进入DTO。

## 7 正式ICD字段定义模板

管理profile的wire_definition_ref必须最终关联共同冻结的正式ICD。逐消息至少确认以下内容，不在本文编造具体值：

| 类别 | 必须记录的字段 |
|---|---|
| 基本信息 | 消息标识、版本、正反方向、业务用途、必选性及批准记录 |
| 物理传输 | CAN/CANFD/车载以太网等实际介质；通道、帧格式、速率和合法端点部署参数 |
| 信号编码 | 位/字节布局、数值类型、字节序、缩放、偏移、单位、坐标系、合法及无效值 |
| 时间与行为 | 周期、突发/负载、截止期、抖动、超时、同步和恢复规则 |
| 条件规则 | CRC、计数器、会话、鉴权、多帧重组及去重，只记录适用项 |
| 反馈 | 正式反馈消息、关联方式；无逐请求回执时明确周期状态及内部应用证据方案 |
| 模型映射 | 真实输入/任务/控制器目标、原子组、实际应用证据点和响应判定 |
| 验收 | 黄金向量、正常/异常用例、时序门限、正式链路与替换测试 |

只有管理契约、正式ICD及模型映射都明确，才能登记完整接口基线。前后端先确认本文DTO，并不等于3.3与3.6线上接口已经冻结。

## 8 评审确认项

需共同确认的具体选择：继续使用WebSocket命令；新增命令前缀及0.1版本；请求/操作/输入事件三个标识的分工；64位数值使用字符串；状态与结果分离；先轮询后订阅；不可变配置/场景引用；文件上传下载另行定义；实际业务信号以正式目录和模型契约为准。

本文只新增定义文件，没有修改服务、前端或正式ICD。配套示例包含有效和预期拒绝的数据，供前端模拟数据及后端契约测试使用；示例的消息名、哈希、资源名和工具绑定均为演示值，不能用于正式验收。

## 9 定义文件校验

已对Schema执行Draft 2020-12元校验，并核对14个命令与文档目录一致。35个显式示例包含27个有效示例和8个预期格式拒绝示例；另校验每个命令的响应数据类型，以及运行状态、报告和应用证据约束，共70项数据格式检查。

这不证明API已实现，也不证明正式ICD符合性。示例文件中的6项业务规则案例明确标记为服务端尚未执行；数字字符串超出uint64范围、真实哈希、动态信号目录、授权和状态转换等需要实际后端验证。
