# 输入模拟器完整数据契约

版本：0.2。日期：2026-10-02。状态：开发评审草案，未实现、未签署冻结。v0.1保留作历史版本；新开发以本版本评审结果为准，不混用两个版本。

## 1 范围与唯一接口原则

本版补全设计方案第4.7、9.7至9.12及10章对应的字段结构，覆盖协议定义、场景脚本、历史记录三类输入资源，以及测试包、六条工具分支、正式链路配置、模型映射、断言、资源传输和管理回执。结构已定义不等于实际ICD参数已确认，也不等于工具链或接口服务已经实现。

模拟器与真实3.3必须使用共同确认的同一正式ICD。3.6的正式接收、解码、校验、映射、反馈及业务处理路径相同，不接受mock/real业务开关。内部JSON只管理资源和执行计划，不另造模拟器到3.6的私有报文。

三类资源的关系：协议定义提供编码与规则，不自行生成动态激励；场景脚本提供工程值、时间与条件；历史记录提供批准的原码或工程量序列。场景与历史均受同一协议目录约束。三类资源不是三条固定物理链路，也不要求把DBC、场景JSON或PCAP文件直接发给3.6。

配套文件：
- `input-simulator-package-v0.2.schema.json`：输入资源内容及交付包结构，根对象Package。
- `input-simulator-api-v0.2.schema.json`：前后端请求响应结构，引用同目录package Schema。
- `input-simulator-api-v0.2.examples.json`：25个命令的请求响应，以及三类资源、波形和测试包示例。
- `input-simulator-fields-v0.2.md`：逐对象字段索引，列明类型、必填性、枚举和格式约束。

两份Schema须同时分发，并按各自$id在校验器中本地注册；API通过package的URN引用，不依赖网络下载。不能把无法解析外部引用视为验证成功。Schema、本文业务规则和实际ICD三者共同构成开发依据；未知正式参数显式PENDING，不能用示例值或默认值补齐。

## 2 公共类型与版本

| 类型或字段 | 定义 |
|---|---|
| Id | 非空字符串，最长128字符；引用由服务器目录提供，不是路径、命令或凭据 |
| UInt64 | 十进制字符串，0至18446744073709551615；Schema只限制语法和长度，服务端必须检查上限 |
| 工程量 | 有限JSON number、boolean、string或number数组；拒绝NaN、Infinity、重复JSON键和未知字段 |
| unit / coordinate_frame | null只表示该信号不适用，不表示未确认；角度制、坐标系、高度基准不得推断 |
| ResourceRef | resource_id、sha256；绑定不可变原始文件，哈希为64字符小写SHA-256 |
| ProfileRef | profile_id、version、profile_hash；绑定ProtocolDefinition |
| ScenarioRef | scenario_id、revision、scenario_hash；绑定ScenarioDefinition |
| PackageRef | package_id、revision、package_hash；绑定PackageDefinition |
| 审计时间 | UTC ISO 8601，必须以Z结束；页面可转换显示，不修改传输值 |
| 微秒时间 | 以_us结尾均使用UInt64；业务时钟与主机单调时钟不可混算 |
| 分页 | limit默认100，范围1至500；cursor不透明，客户端不解析、不自行生成 |
| 管理版本 | api_version=0.2；protocol-0.2、scenario-0.2、package-0.2是内部结构版本，不是正式ICD版本 |

结构化定义按[JCS RFC 8785](https://www.rfc-editor.org/rfc/rfc8785)规范化后计算SHA-256。profile_hash仅哈希Profile.definition；scenario_hash仅哈希Scenario.definition；package_hash仅哈希Package.definition。外层审批、校验状态、服务器引用不参与各自定义哈希，避免自引用循环。文件sha256哈希原始字节，不规范化DBC/YAML/PCAP。审批绑定定义哈希，并在服务器侧核验签署人、权限及效力；哈希不是审批证明。

修改形成新修订，不覆盖已运行引用。相同逻辑操作重试复用request_id；以认证主体、cmd、request_id去重，内容不同返回IDEMPOTENCY_CONFLICT。保存响应中的引用由服务器计算生成，客户端传来的哈希不能代替真实内容检查。

## 3 协议定义资源

Profile包含ref、approval、approval_ref、definition。approval为DRAFT/FROZEN；FROZEN必须有真实共同冻结记录。普通管理保存不能给Profile或测试包授予冻结资格。

ProtocolDefinition包含schema_version、name、icd_document_ref、messages。icd_document_ref关联签署ICD资源；messages是可供页面显示和编译校验的只读目录，正式编码定义仍来自绑定的DBC/已验证ARXML/schema。

| Message字段 | 类型与含义 |
|---|---|
| message_id、name | 业务标识与显示名；message_id不等同CAN ID |
| required | 是否为冻结覆盖清单必选消息，不能由运行页面随意取消 |
| direction、category | TO_36/FROM_36；任务、控制、参数、环境、故障、传感器、执行器、状态、反馈分类 |
| transport_profile_id | 引用唯一正式传输配置，不凭category选择CAN或以太网 |
| control_role | STIMULUS/CONTROLLER/OBSERVER/FEEDBACK，按同一规则鉴权及仲裁 |
| signals | 工程量目录，每项含signal_id、name、value_type、unit、coordinate_frame、minimum、maximum、decimal_minimum、decimal_maximum、dimension、writable |
| wire | 正式编码与黄金向量，或明确PENDING |
| timing | 周期/事件、截止期、容差、有效期和超时规则，或明确PENDING |
| feedback | 正式反馈方式、反馈消息和关联机制，与内部应用证据分开 |

`wire.status=CONFIRMED`时必填：transport、definition_resource、definition_key、codec_binding_id、selector、fields、rules、golden_vectors。definition_key是资源内受控定义键，不是可执行代码；codec_binding_id由服务器批准目录解析。字段目录与资源定义不一致时拒绝，不允许页面覆盖DBC编码。

CAN selector含arbitration_id、extended_id、payload_length、fd、brs。标准ID范围0至2047，扩展ID0至536870911；经典CAN载荷0至8且禁用BRS；FD载荷为0至8、12、16、20、24、32、48、64字节。CANFD消息必须fd=true，经典CAN必须fd=false。非CAN的selector使用RESOURCE_DEFINED及定义键，按正式资源解释，不以UDP示例代替所有以太网业务。

WireField逐项定义field_id、signal_id、role、raw_type、layout、scale、offset、invalid_definition_key。role区分SIGNAL、COUNTER、CRC、SESSION、LENGTH、TIMESTAMP、DISCRIMINATOR和OTHER。固定布局提供start_bit、bit_length、byte_order、bit_numbering；复杂/变长布局通过带哈希资源与definition_key完整绑定。SIGNAL必须绑定signal_id，编码换算与工程单位目录须一致。位序按声明解释，禁止把DBC Motorola起始位当作线性网络位序。

Rule含rule_id、kind、applicability、definition_resource、definition_key、reason。REQUIRED必须指向实际规则资源；NOT_APPLICABLE必须说明依据；PENDING不得进入正式冻结。适用项包括应用CRC、计数器、会话、鉴权、多帧、去重、同步、超时和安全。规则资源记录算法、参数、覆盖范围、初始状态、恢复与失败动作，不能只给一个不可解析名称。

规则资源使用RuleResource（schema_version=rule-resource-0.2、rules数组），每条RuleDefinition包含rule_id、kind、parameters，参数按kind严格分支：

| kind | parameters完整字段 |
|---|---|
| CRC | algorithm_binding_id、field_id、width_bits、polynomial_hex、initial_hex、xor_out_hex、reflect_input、reflect_output、coverage |
| COUNTER | field_id、width_bits、initial_value、increment、rollover、max_forward_gap、repeat_action、reset |
| SESSION | state_machine_binding_id、protocol_definition_ref、handshake_timeout_us、inactivity_timeout_us、reconnect_policy、dynamic_field_ids、feedback_message_ids |
| AUTH | auth_binding_id、algorithm_definition_ref、identity_field_ids、anti_replay_rule_id、credential_scope_binding_id、session_required |
| MULTIFRAME | group_id、member_message_ids、sequence_field_id、assembly_timeout_us、missing_member_action、max_inflight_groups、commit_boundary、target_step_field_id |
| DEDUP | key_field_ids、window_us、duplicate_action、capacity |
| SYNC | clock_domain_ids、method、synchronization_binding_id、max_skew_us、on_clock_loss |
| TIMEOUT | watch_scope、watch_id、clock、timeout_us、safety_rule_id |
| SAFETY | action_binding_id、stop_message_ids、clear_queue_scope、release_authorization、confirmation_assertion_ids、deadline_us |

CRC覆盖可用FIELD_CONCAT（field_ids、include_padding、zero_crc_field）、BYTE_SPANS（start_byte/length_bytes数组、zero_crc_field）或RESOURCE_DEFINED（带哈希定义资源及键）。字段拼接仅用于定义明确的整字节字段；复杂位拼接必须绑定正式定义。多项式按省略最高次项的十六进制表示，宽度、初值、异或值、反射及覆盖范围逐项比对正式黄金向量，不能猜测算法。计数器值必须适配width_bits；MODULO按该宽度回卷，STOP不得回卷。多帧TARGET_STEP要求实际target_step_field_id，MODEL_STEP该字段为null。状态机/鉴权/同步实现必须绑定已批准、已验证实现，文件引用不等于能力已具备，也不在JSON内保存密钥。共享rule_id允许多处引用同一不可变定义，但不同内容冲突必须拒绝。

信号value_type包括NUMBER/INTEGER/BOOLEAN/STRING/NUMBER_VECTOR/INT64_DECIMAL/UINT64_DECIMAL。INTEGER限定JavaScript可精确表达的安全整数；更大的正式64位工程整数使用十进制字符串类型，并由服务端按目录校验有符号或无符号范围。64位类型使用decimal_minimum/decimal_maximum且minimum/maximum为null，其余类型decimal边界为null；NUMBER_VECTOR必须有dimension，其他类型dimension=null。值类型及实际大小属于动态目录校验，通用Values对象不能单独证明合法。

黄金向量包含vector_id、engineering_values、wire_hex、expected、reason_code。实际向量须有独立批准依据，并覆盖有效、边界、无效值及适用规则；不能用同一编码器往返结果替代独立符合性。wire_hex为小写偶数字节串，实际长度与帧/报文定义一致。

Timing CONFIRMED字段：trigger、period_us、deadline_us、jitter_tolerance_us、validity_us、max_burst、timeout_rule_id。PERIODIC要求正数period_us，EVENT必须period_us=null。deadline、周期与有效期的关系依实际ICD检查，不预设统一数值或所有接口都具有1ms周期。

Feedback字段：mode=NONE/PERIODIC/PER_REQUEST/PENDING；message_ids、correlation_rule_id、application_evidence_binding_id。有正式反馈时必须给反馈消息及关联规则；NONE须有签署依据，不能擅自省略必选反馈。没有逐请求回执时，依ICD用周期状态关联，并由真实应用点提供内部证据；总线ACK不是模型应用证明。

未确认定义使用如下结构，不能同时塞入猜测值：
```json
{"status":"PENDING","pending_fields":["selector","fields","golden_vectors"],"reason":"等待双方共同确认正式ICD"}
```

FROZEN Profile的wire、timing不得PENDING，feedback与适用规则也不得PENDING。DRAFT可用于明确隔离的探索验证，但不能发送未定义的消息。

## 4 正式传输与模型映射

Transport包含transport_profile_id、medium、configuration。configuration为PENDING或CONFIRMED；medium必须与parameters种类一致。

| 配置 | parameters字段 |
|---|---|
| CAN/CANFD | kind=CAN、driver_binding_id、channel_binding_id、nominal_bitrate、data_bitrate、fd、driver_config_ref、feedback_transport_id、synchronization_rule_id |
| ETHERNET | kind=ETHERNET、driver_binding_id、link_binding_id、stack、local_endpoint_binding_id、remote_endpoint_binding_id、feedback_transport_id、session_rule_id、synchronization_rule_id、driver_config_ref |
| SERIAL/AD/DA/IO/VIDEO | kind为对应介质、driver_binding_id、channel_binding_id、interface_definition_ref、feedback_transport_id、synchronization_rule_id |

经典CAN的data_bitrate=null；CANFD必须提供实际数据段速率。Schema的数字上限仅为结构保护，设备与标书适用性必须另验。stack为L2/UDP/TCP/SOMEIP/CUSTOM，不代表当前工具已支持。端点目录在受控部署中记录实际网卡、地址、端口、方向和白名单；管理接口不接受任意网络目标或shell。无反向业务的传输可指向同一配置，正式反馈仍按Message.feedback判定，不因此制造额外报文。

Mapping完整字段：mapping_id、message_id、signal_id、target_kind、model_contract_ref、target_path、source_unit、target_unit、source_frame、target_frame、conversion、atomic_group_id、apply_boundary、invalid_action、safe_default、evidence_binding_id。

target_kind只允许MODEL_INPUT/TASK_INPUT/PARAMETER/FAULT_INPUT/CONTROLLER_INPUT，禁止映射到模型解算输出。conversion为IDENTITY/AFFINE/APPROVED，并明确scale、offset、conversion_binding_id；IDENTITY固定scale=1、offset=0，AFFINE按target=source*scale+offset，APPROVED需实际批准转换实现。跨坐标系不得仅用标量缩放冒充转换。invalid_action为REJECT/HOLD/SAFE_DEFAULT；只有SAFE_DEFAULT能提供safe_default，其安全值必须得到批准。

apply_boundary为MODEL_STEP/TASK_COMMIT，atomic_group_id非空时必须引用ICD定义的完整组机制。全部信号校验通过后原子应用，缺帧、过期、未知信号整组拒绝。evidence_binding_id指向真实写入/消费点，不在接入排队时提前产生APPLIED。

## 5 场景脚本资源

本版统一采用ScenarioDefinition.events，取代v0.1的简化steps；不继续并行维护两种执行语义。

ScenarioDefinition含schema_version、name、profile_ref、model_binding_id、seed、resource_refs、clock_policy、readiness_assertion_ids、events、on_failure、cleanup_rule_id。Scenario外层含ref、definition、validation_status、validation_errors。

每个Event含event_id、at_sim_time_us、priority、link_id、action。按仿真时刻、priority从小到大、event_id UTF-8字节序排序；event_id唯一。数组位置不决定业务顺序。同刻或活动时间重叠的同字段写冲突在加载时拒绝，不能靠优先级偷偷覆盖。

| action.kind | 业务字段 | 规则 |
|---|---|---|
| SEND | message_id、values | 一次工程量提交，经批准原工具及正式编码，不直接写模型 |
| WAVEFORM | message_id、signal_id、unit、duration_us、update_period_us、waveform | STEP、RAMP、SINE_SWEEP，单位和边界逐点校验 |
| PERIODIC_START | schedule_id、message_id、values | 周期来自绑定Message.timing，不能任意覆写 |
| PERIODIC_STOP | schedule_id | 停止对应活动发送，不影响无关心跳 |
| WAIT | source_event_id、stage、timeout_us、assertion_ids | 等待此前事件真实RECEIVED/APPLIED/RESPONSE/SAFETY及断言 |
| REPLAY | history_id、replay_policy_id | 调用受批准回放链，不能绕过目录校验 |
| FAULT | fault_case_id、duration_us | 按批准故障实现注入，不执行任意脚本 |
| ASSERT | source_event_id或null、assertion_ids | 根据关联输入证据或明确状态窗口判定 |
| END_CLEANUP | cleanup_rule_id | 停发、清队列、撤销发送权及安全状态确认 |

SEND/WAVEFORM/PERIODIC_START/REPLAY/FAULT必须link_id非空；WAIT、ASSERT、PERIODIC_STOP、END_CLEANUP的link_id为null。STOP通过schedule_id找到原发送链；REPLAY所选链必须匹配history与policy。未选入Run.link_ids的链不能执行。

STEP字段：initial_value、final_value、step_after_us；step_after_us不大于duration_us。RAMP字段：start_value、end_value、max_slew_per_second，实际斜率不得超限。SINE_SWEEP字段：offset、amplitude、start_frequency_hz、end_frequency_hz、phase_rad；按持续时间内线性频率变化计算相位，不用简单频率切换。更新周期必须正数、不得大于持续时间；本版要求duration_us可被update_period_us整除。seed固定无符号32位，用于批准的随机故障或扩展发生器重现，不表示现有三种波形含随机噪声。

clock_policy.business_clock固定HIL_SIMULATION；pause_policy为SCENARIO_ONLY或COORDINATED。SCENARIO_ONLY暂停计划、不承诺暂停模型；COORDINATED需要模型、控制器及视频确认支持，暂停冻结业务时间，独立心跳继续。WAIT超时按本服务单调时钟计时，不能暂停模型使等待永不超时。恢复后超过max_lateness_us的旧事件SAFE_STOP，不集中补发。

进入运行前执行readiness_assertion_ids；on_failure固定SAFE_STOP，cleanup_rule_id是受控安全程序，不是代码字符串。重置产生新run_id/时间域，旧证据保留。优先级、周期、波形和延迟队列的冲突检查属于加载门禁。

## 6 历史记录与回放

History含history_id、resource_ref、format、profile_ref、origin_clock、streams、integrity、engineering_schema_version。format覆盖CAN_LOG、PCAP、PCAPNG、ENGINEERING_JSONL；canplayer不消费场景JSON，tcpreplay不消费CAN日志。

origin_clock含domain_id、kind、tick_unit=us、synchronization_ref；kind为DEVICE/HOST_MONOTONIC/UTC/SIMULATION/CAPTURE_RELATIVE。不能直接相减不同主机单调时间来报告单程延迟。

streams每项含stream_id、original_channel、direction、medium、message_ids。direction为TO_36/FROM_36/UNKNOWN；UNKNOWN不能直接注入。TO_36为输入激励，FROM_36仅用于分析或预期结果，不向3.6回放成输入。双向捕获必须明确分流，不能把3.6反馈再次灌入输入。

integrity含capture_loss=NONE/DETECTED/UNKNOWN、truncated、first_timestamp_us、last_timestamp_us。检查原始文件是否截断、接口链路类型、时间回退、丢失标记及协议版本；不能把没有丢失计数视为NONE。缺失或未知完整性只能在批准的范围内使用，否则正式准入拒绝。

ENGINEERING_JSONL逐行使用EngineeringRecord：schema_version=engineering-history-0.2、sequence、timestamp_us、stream_id、message_id、values。sequence严格递增，时间在声明域内非递减，message和signal存在且单位与profile一致。二进制原码不装入values。

| ReplayPolicy字段 | 含义 |
|---|---|
| replay_policy_id、history_id、stream_ids | 策略标识、唯一历史资源与批准输入流 |
| source_range.from_us / to_us | 捕获时钟范围，闭区间，from不得大于to且须在资源范围内 |
| clock_mode | SIM_RELATIVE；首个选中记录映射到REPLAY事件时刻 |
| rate.numerator / denominator | 正数有理速率；映射间隔=原间隔*denominator/numerator；微秒向最近整数取整，半值向上；相同时刻保持捕获记录顺序 |
| repeat_count | 正整数；重放边界及会话复位必须符合批准规则，不能无间隔补发突发 |
| repeat_gap_us、repeat_session_rule_id | 明确轮次间隔及适用会话规则；SESSION_REBUILD必须有规则引用 |
| payload_mode | RAW_VALIDATED原码验证后发送；REENCODE工程量按同ICD重编码；SESSION_REBUILD建立实际会话后重放应用业务 |
| late_action、max_lateness_us | STOP或批准的DROP_APPROVED；不隐式追赶补发 |
| channel_map | stream_id到transport_profile_id，一条输入流只能有一个明确目标 |
| rewrites | field_id、role、rule_id；仅批准COUNTER/SESSION/CRC/TIMESTAMP/ENDPOINT改写 |
| approval_ref | 服务端批准记录；正式回放与任何改写需真实核验 |

RAW_VALIDATED的rewrites必须空，不修复坏CRC再假称原码回放。ENGINEERING_JSONL不能RAW_VALIDATED。PCAP/PCAPNG的链路类型必须被锁定版本支持；不支持时采用批准、可追溯预处理，保留原始文件哈希与转换产物，禁止静默转格式。TCP或鉴权会话若需要状态重建，必须SESSION_REBUILD及已验证客户端；tcpreplay原码喷流不能代替会话。在线闭环默认1倍速，变速/重复须经模型和控制器能力准入。

每轮按选中记录的首末实际时间计算持续时间，下一轮起点为本轮起点加持续时间及repeat_gap_us。重复边界与零持续时间资源必须通过突发/会话规则验证；不允许借零间隔重复绕过max_burst。批准策略要求的会话重新建立、计数器更新和CRC重算必须有实际能力，否则拒绝。

## 7 六条工具链绑定

| branch | 原工具与用途 |
|---|---|
| SIGNAL_CAN | cantools → python-can → SocketCAN/批准SDK；协议和工程量驱动 |
| CAN_UTILS | can-utils ↔ SocketCAN；批准的收发、监听和用例 |
| SAVVYCAN | SavvyCAN ↔ SocketCAN；观察、记录或已批准人工发送 |
| CAN_REPLAY | CAN日志 → canplayer → SocketCAN |
| ETHERNET_GENERATOR | Ostinato/Scapy → 正式以太网；状态化能力按ICD验证 |
| PCAP_REPLAY | PCAP/批准PCAPNG处理 → tcpreplay → 正式以太网 |

Link字段：link_id、branch、role、transport_profile_id、message_ids、history_ids、tool_binding_ids、feedback_collector_binding_id、control_owner_ref、qualification、evidence_refs、capability_scope。

role为SEND/OBSERVE/REPLAY；发送与回放必须有控制权及反馈采集器绑定，OBSERVE没有发送权。监听工具可独立接入，不要求原始报文回送到中央分发器。每个发送事件显式link_id，编译器检查消息、传输、资源、角色和实际工具支持范围一致；同时运行的消息发送权互斥。

qualification分UNVERIFIED/SOFTWARE_VERIFIED/FORMAL_VERIFIED/REAL_SOURCE_REPLACED，后三者需真实evidence_refs及服务端核验。工具AVAILABLE只是部署可调用，不表示具备该ICD全部交互能力。六条分支保留，但不是每个场景必须全部启用；全部必选消息必须至少有一条合格正式发送链覆盖。

## 8 故障与断言

FaultCase字段：fault_case_id、scope、kind、message_ids、signal_ids、parameters、implementation_binding_id、allowed_modes、approval_ref、evidence_binding_ids。scope为APPLICATION/PHYSICAL；kind为DROP/DUPLICATE/REORDER/DELAY/INVALID_VALUE/BAD_APP_CRC/STOP_TX/GPS_LOSS/CUSTOM。parameters结构由批准实现的参数Schema进一步校验；不能接受任意代码。物理故障必须有实体设备和测量证据，不能用软件通知冒充。GPS_LOSS必须命中实际传感器故障路径。

Assertion字段：assertion_id、stage、observable_binding_id、field_path、operator、expected、lower、upper、absolute_tolerance、unit、window_us。field_path是可观测目录中的路径，不是任意表达式。EQUAL精确比较；IN_RANGE含上下界；DELTA_WITHIN是批准单位下数值/等维向量的绝对容差；COUNT_AT_LEAST比较窗口内非负整数计数；ABSENT判窗口内没有符合关联条件的记录。lower<=upper，容差必须有限非负。关联、类型和单位不成立时失败，不返回通过。

APPLIED断言从真实输入写入或任务消费证据取值。RECEIVED只证明校验接收；RESPONSE验证规定业务响应；SAFETY验证安全动作。缺少参考值或响应观测点，不能声称动力学正确。

Case字段：case_id、required、message_ids、scenario_ids、link_ids、assertion_ids、environment、reference_resource_ref、cleanup_rule_id。environment分别标WINDOWS_UNIT/LINUX_SOFTWARE/TARGET_REALTIME/PHYSICAL。实际L01至L10、T01至T14由覆盖清单登记，示例的DEMO用例不替代它们。每个必选用例需明确环境、阈值、清理和真实断言，不允许隐式跳过。

## 9 测试包与冻结基线

PackageDefinition含schema_version、name、canonicalization、manifest、profile、transports、mappings、histories、scenarios、replay_policies、fault_cases、assertions、cases、links、release_baseline。Package外层含ref、definition、qualification、approval_ref、validation_status、validation_errors。

manifest每项包含artifact_id、role、resource_ref、size_bytes。role覆盖ICD/PROTOCOL/SCENARIO/HISTORY/MODEL_CONTRACT/TRANSPORT_PROFILE/SIGNAL_MAP/CASE_SUITE/GOLDEN_VECTORS/RELEASE_BASELINE。服务器保存时生成相应内容资源并检查结构副本与文件一致；列表中的ID和哈希必须解析到实际不可变文件，不能仅检查64字符形状。SUPPORT是模型契约、通道、映射、用例等配套文件类别，不是图2第四种输入源。

所有被引用资源必须出现在manifest，全部对象ID在各自命名空间唯一；反馈消息、超时规则、目标路径、场景、历史、链路、断言、用例均可解析。协议加载器、场景解释器、回放工具不得猜测缺失项。缺失、冲突、不支持或哈希不一致时BLOCKED，不启动发送。

release_baseline为null表示尚未建立基线；非空含baseline_id、stage、approval_ref、protected_artifacts、allowed_changes。stage为TEST_CANDIDATE或RELEASED。protected_artifacts记录3.6程序、依赖、驱动、ICD、映射、模型契约与测试基线的实际资源哈希。allowed_changes只允许SOURCE_ENDPOINT/DEVICE_ID/CREDENTIAL_REF/AUTHORIZATION_REF/DEPLOYMENT_BINDING，具体配置键和范围由批准基线进一步限制，不授权更换驱动、协议栈或业务映射。

FROZEN包要求共同冻结Profile、非空发布基线、真实批准记录、全部依赖有效及覆盖完整；页面普通保存只能产生DRAFT，不能靠传入FROZEN提升资格。FORMAL运行要求已冻结包及适用正式链路能力。未来真实3.3替换只改变白名单部署/授权配置，受保护文件哈希不变；允许按流程重启，不承诺无中断热切换。

数据包冻结不等于实体链路已通过验收。首次正式链路测试可使用获批TEST_CANDIDATE，检查实际可调用及规定支持范围，不要求链路已经FORMAL_VERIFIED，否则会形成验证前置条件循环。候选基线通过全部必选正式测试后才能批准为RELEASED；该批准须关联原测试包及报告，验证实际受保护内容与发布包一致。真实3.3替换必须针对RELEASED及已完成正式验证的必选链路，并执行同版回归；不能把候选测试资格当成替换资格。

## 10 前后端管理命令

沿用WebSocket的cmd+params，params必含api_version=0.2与request_id。下表只列业务参数。所有命令均为拟定接口，不表示当前服务支持。

| cmd | 业务参数 | 成功data |
|---|---|---|
| simulator_capabilities_get | 无 | Capabilities |
| simulator_profiles_list | cursor、limit | ProfilePage摘要 |
| simulator_profile_get | profile_ref | Profile |
| simulator_resources_list | kind、cursor、limit | ResourcePage |
| simulator_resource_get | resource_ref | Resource |
| simulator_resource_import_begin | declaration | Upload |
| simulator_resource_import_chunk | upload_id、offset_bytes、data_base64、chunk_sha256 | Upload |
| simulator_resource_import_get | upload_id | Upload |
| simulator_resource_import_commit | upload_id | Resource |
| simulator_resource_import_abort | upload_id | Upload |
| simulator_resource_read_chunk | resource_ref、offset_bytes、length_bytes | ResourceChunk |
| simulator_scenarios_list | cursor、limit | ScenarioPage摘要 |
| simulator_scenario_get | scenario_ref | Scenario |
| simulator_scenario_save | definition、可选base_ref | Scenario |
| simulator_packages_list | cursor、limit | PackagePage摘要 |
| simulator_package_get | package_ref | Package |
| simulator_package_save | definition、可选base_ref | Package |
| simulator_package_validate | package_ref | Package及依赖校验结果 |
| simulator_run_create | package_ref、scenario_ref、mode、source_binding_ref、link_ids | Run，初态VALIDATING |
| simulator_run_control | run_id、expected_revision、action | Run，ACCEPTED |
| simulator_run_update_inputs | run_id、expected_revision、message_id、values、link_id | Run，ACCEPTED |
| simulator_run_get | run_id | Run |
| simulator_runs_list | cursor、limit | RunPage |
| simulator_records_list | run_id、after_cursor、limit | RecordPage |
| simulator_report_get | run_id | Report |

scenario_save/package_save无base_ref表示新建，有base_ref表示基于不可变修订创建下一版；若不是当前可编辑最新版本返回VERSION_CONFLICT。独立保存场景不会修改旧测试包；需要重新保存测试包以绑定新ScenarioRef。package_validate只做格式及依赖检查，不授予共同ICD批准、实体链路验证或冻结资格。

Run新增package_ref、link_ids、clock_domain_id、sim_time_us、step_index、active_event_id、link_stats。profile_ref及scenario_ref从绑定包核验，不加载所谓最新版。source_binding_ref仅表示部署、身份和授权，不包含模拟/真实业务分支。手动输入更新只允许批准的TO_36、writable信号及活动发送链，不能与场景周期/回放竞争写入；整组拒绝或受理，不部分下发。

Run.state：VALIDATING/BLOCKED/READY/RUNNING/WAITING/PAUSED/STOPPING/COMPLETED/FAILED；Run.result独立为NOT_RUN/RUNNING/PASS/FAIL/INCOMPLETE。完成不等于通过。READY之前禁止业务发送；ACCEPTED只表示排队。RESET先安全停止旧运行再创建新run_id，通过OPERATION_RESULT.new_run_id返回，不清除旧证据。revision只在管理状态变更或操作受理时增长，统计刷新/查询不增长。

Record沿用记录字段并新增event_id、link_id，APPLIED必须给step_index、sim_time_us、applied_values、applied_mapping_ids及非空evidence_refs。TX/RX必须有消息、链路和原码证据引用。原码分块落盘，不在常规记录查询中返回整份PCAP。operation_id关联管理排队动作，input_event_id关联实际输入，event_id关联场景事件；它们不自动占用正式报文载荷。

Report新增package_ref、qualification_level、environment_ref。qualification_level区分软件、正式链路和真实源替换；环境资源记录运行时、内核/驱动、工具、模型、同步与相关哈希。所有冻结必选Case都必须出现在报告中，不因缺记录而删掉；必选项不能NOT_APPLICABLE，证据缺失或未执行为INCOMPLETE。任何FAIL优先于缺项，否则必选均PASS且证据完整才可PASS。EXPLORE结果不得用于正式符合性或替换验收。

Page含items、next_cursor；概要中的Scenario使用event_count，Profile使用message_count，Package使用scenario_count。RecordPage另含run_id、complete、retention_gap；增量next_cursor保持最后已读位置，没新记录时不重置，retention_gap不能静默忽略。统计帧数与输入事件数不同，不直接相减推断丢包。

## 11 资源传输与安全

Resource包含resource_id、name、kind、format、size_bytes、sha256、validation_status、validation_errors、approval、approval_ref。审批APPROVED必须有服务端批准依据及VALID状态。资源格式实际支持由Capabilities声明，ARXML版本/构造与PCAP链路类型还要按锁定工具检查。

ImportDeclaration包含name、kind、format、size_bytes、sha256。begin先验证类别/格式、额度与权限，返回Upload：upload_id、state、next_offset_bytes、declaration、max_chunk_bytes、expires_at、resource_ref。upload_id绑定认证主体，不能跨用户读取或提交。state为OPEN/COMMITTED/ABORTED/EXPIRED；只有COMMITTED的resource_ref非空。

chunk采用标准带填充Base64，解码后不得超过服务端声明上限，绝对上限65536字节。offset_bytes必须等于next_offset_bytes；重发已经保存的同一offset及同一字节内容可返回当前位置，不重复追加，不同内容返回CHUNK_CONFLICT；越界或乱序拒绝。校验实际解码长度、chunk_sha256和累计大小，Base64字符串长度不是字节数。

commit要求累计大小等于declaration.size_bytes并核验真实文件SHA-256，原子形成不可变Resource；返回PENDING表示格式/依赖扫描尚未完成，资源不得运行使用。资源状态通过resource_get查询，APPROVED由独立权限工作流授予，不由客户端字段声明。abort清理本人未提交暂存；已提交资源不得因此删除，返回STATE_CONFLICT。过期清理不影响已提交引用。get支持断线恢复；不盲目重传已提交文件。

read_chunk返回resource_ref、offset_bytes、length_bytes、data_base64、chunk_sha256、eof；读取越过末尾拒绝，零字节文件通过Resource.size_bytes=0识别，不读取空chunk。客户端验证解码长度及哈希，多块读取后验证完整文件哈希。批准的资源传输走独立管理面，不改变正式3.3↔3.6报文。大文件逐块低优先级传输，不与实时反馈争抢处理；大测试包超过max_package_bytes时拒绝，第一版不引入无限长管理消息。

Capabilities保留命令、动作、模式、工具和绑定目录，新增resource_formats、schema_resources、limits。limits明确max_message_bytes、max_resource_bytes、max_chunk_bytes、max_package_bytes、upload_retention_ms。绑定种类扩展SOURCE/MODEL/REPLAY_POLICY/FAULT_CASE/CODEC/DRIVER/CHANNEL/LINK/ENDPOINT/CONVERSION/EVIDENCE/OBSERVABLE/CLEANUP/TOOL/RULE_IMPLEMENTATION/CREDENTIAL_SCOPE/SYNCHRONIZATION。所有绑定需核验profile兼容性、权限和实际能力，不把目录available当作正式符合性。

新增错误码REFERENCE_INVALID/ICD_PENDING/COVERAGE_INCOMPLETE/DIRECTION_UNKNOWN/REPLAY_UNSUPPORTED/CHUNK_CONFLICT/UPLOAD_EXPIRED/QUOTA_EXCEEDED/HASH_MISMATCH/RESOURCE_IN_USE。沿用INVALID_REQUEST、UNSUPPORTED_VERSION、鉴权、修订、运行状态、发送权、超时等错误。错误details.path为JSON Pointer；外层code与error.code一致，拒绝不产生部分业务副作用。

响应固定kind=RESPONSE，包含api_version、request_id、cmd、status、code、message、timestamp、operation_id、data、error。SUCCESS用于同步完成，ACCEPTED仅用于控制和输入更新排队，拒绝/失败data=null。第一版仅轮询，不主动推送；现有单pending前端必须先实现request_id匹配、超时及清理，才可并发。重连查询状态，不自动START。既有set_inputs、load_mission、tune、UE4等命令不改格式和职责。

拒绝回执允许回显非空、最长128字符的未知cmd；SUCCESS/ACCEPTED仍仅允许已定义命令。未知版本回执声明服务器支持的api_version=0.2，并返回UNSUPPORTED_VERSION。无法提取合法request_id或cmd、无效JSON或超过消息大小时，不伪造成功或请求关联，按连接安全策略拒绝并关闭连接；前端清理pending并显示协议错误。未认证连接不得执行任何查询或资源操作。

## 12 视频与实体I/O接口附件

三类资源与六条CAN/以太网分支不自动覆盖实体视频或I/O验收。OtherConfig.interface_definition_ref须关联以下受控附件；其内容类型在package Schema中独立定义。

SerialInterface给出串口电气标准、baud、data_bits、stop_bits、parity、flow_control、encoding_resource_ref、receive_timeout_us。IoInterface给出介质及每个通道的方向、单位、范围、采样/更新率、电气定义、校准资源、硬件和测量证据绑定。软件频率不代替AD采样率或DA转换时间。

VideoInterface给出格式、尺寸、帧率分数、pixel_format、触发模式、metadata_location、标注资源、迟到策略、同步规则和完成反馈消息。RAW必须SIDECAR，SEI只用于批准的编码流。VideoFrameMetadata逐帧绑定run_id、video_frame_id、clock_domain_id、sim_time_us、pts、pts_timebase、图像与标注资源。真实字节接收、时间关联及算法完成反馈单独验收，元数据模拟不能登记实体通过。

## 13 强制业务校验与验收清单

Schema执行结构及局部条件检查；以下跨引用/实际状态规则由服务端实现，当前未实现服务，不能用示例格式检查冒充完成：

| 规则编号 | 服务端必须验证 |
|---|---|
| B01 | 原始文件、规范化定义、引用修订、实际哈希、唯一ID及manifest闭合一致 |
| B02 | 正式运行包/Profile/资源批准有效，无PENDING，全部必选消息和适用规则明确 |
| B03 | Message与Transport介质一致；驱动、端点、codec及锁定工具真实可用并获授权 |
| B04 | 编码布局、帧长、比例、复用、校验、会话、重组和独立黄金向量实际一致 |
| B05 | 信号类型、维度、单位、坐标、范围、writable及目标模型契约一致，不能写输出 |
| B06 | 事件ID/排序/前序依赖、周期生命周期、波形参数和同字段时间区间没有冲突 |
| B07 | history时间范围、方向、链路类型、完整性及版本合法；不能重放反馈或未知方向 |
| B08 | 回放流、通道、速率、重写和会话模式获批准，原码不能暗改，在线不盲目变速 |
| B09 | 所有执行事件link均选入运行，资源/消息/角色匹配，发送权互斥且工具支持规定交互 |
| B10 | readiness/WAIT/ASSERT关联真实观测，安全停发及清队列完成，恢复不补发过期输入 |
| B11 | 报告覆盖冻结全部必选Case；接收/应用/响应证据分离，环境和测量阈值真实匹配 |
| B12 | 替换前后受保护哈希不变，配置差异全部在细化白名单，真实3.3执行同版回归 |
| B13 | 上传/下载权限、额度、偏移、解码字节数及实际哈希正确，临时文件不执行、不暴露路径 |

完成字段结构评审后，双方填入实际ICD内容并运行上述规则及正式测试，再冻结发布。当前文件不声明API、硬件、正式符合性或真实3.3替换已通过。

## 14 与v0.1的迁移

保留cmd+params、请求/操作标识、状态与结果分离、不可变引用和轮询方式。新增api_version=0.2，未知版本明确拒绝；服务端不得按v0.1猜测解析v0.2。

steps改为events；model_binding_ref改model_binding_id；resource_ids改带哈希resource_refs；step_count改event_count；toolchain_ids改link_ids，并增加package_ref。Profile变为ref/approval/approval_ref/definition，不把展示目录当完整线缆报文。新增11个管理命令、资源传输与SUPPORT文件类别。

旧草案尚未实现，因此不安排线上自动兼容转换；确需导入v0.1草案时，单独迁移并补齐优先级、断言、清理、资源哈希及链路绑定，再校验保存成DRAFT，不能直接标VALID/FROZEN。v0.2评审通过前不改现有HIL业务代码。
