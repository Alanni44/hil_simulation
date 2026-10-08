# 输入模拟器完整输入契约 v0.3

日期：2026-10-02。业务基线：HIL-ICD-1.0。定义权：本项目，依据用户明确授权。状态：完整设计定义，尚非服务实现或硬件验收结论。

## 1. 本次收紧

本版不是继续补通用表单，而是直接确定模拟器和未来正式3.3共同遵守的业务输入、线上编码、时序、映射、安全和反馈。标书没有给出的参数由本项目确定，不再写“待3.3确认”。源文件哈希、模型契约哈希及真实设备校准值来自实际文件/测量，不得伪造为固定常数。

定义齐全与实现齐全分开：REQUIRED_IMPLEMENTATION 表示字段和责任已确定，但代码尚须实现；不表示输入字段未确认。没有消费者或探针时必须拒绝 UNSUPPORTED/TARGET_MISSING，不得返回假成功、静默丢字段或补零。所有适用必选项完成后才能进入替换验收。

完整性范围是标书3.3与3.6间的数据交换、方案图二的三类输入与六条保留工具链，以及3.6仿真、任务、视频和配置控制。不是对所有未来未知型号的任意端口作无限扩展承诺。

## 2. 文件与优先级

1. 本文：语义、跨字段约束、状态机、链路和验收。
2. input-simulator-business-v0.3.schema.json：45类TO_36输入、14类FROM_36反馈、资源输入和逐层封闭字段。
3. input-simulator-icd-v0.3.json：实际消息ID、CAN ID、类型/偏移、周期/超时、56个物理逻辑端口、97条模型输入/参数绑定。
4. input-simulator-fields-v0.3.md：所有Schema分支的逐字段索引，引用展开时必须读取对应定义。
5. input-simulator-canfd-v0.3.dbc：13类CAN FD传输帧。只负责帧内字段，不代替分片重组/CRC/会话/业务校验。
6. input-simulator-api-v0.3.schema.json：25个管理命令，新增实际运行配置与业务消息强类型约束。
7. input-simulator-coverage-v0.3.json：26组需求对照和测试入口；input-simulator-v0.3.qa.json记录实际静态校验范围。
8. input-simulator-v0.3.manifest.json：由QA对本版实际文件计算SHA256；不写不存在的运行程序发布哈希。

baseline_sha256不是单独目录哈希。统一算法为SHA256(RFC8785规范化对象)：对象恰含business_schema_sha256、wire_catalog_sha256、canfd_dbc_sha256、contract_doc_sha256四键，分别取四个对应原始文件SHA256。input-simulator-v0.3.baseline.json给出实际四个组件哈希和计算结果，SessionOpen/SourceInputs/管理API使用同一结果；ProtocolSource.wire_catalog_sha256仍是目录自身哈希。这样字段Schema或语义正文改变也会改变共同基线，不能只比消息ID。

v0.1/v0.2保留为历史。v0.3的业务字段/线上目录覆盖旧版未落实的业务定义；v0.2 package Schema仅继续承载资源索引、工具运行声明、规则资源、测试包和发布管理元数据，不再拥有业务字段/编码决定权。正式执行的Profile必须逐项等价于本版目录且全部实际规则已确认；拒绝任何旧演示资源、未落实wire/timing/feedback、与本版不一致的编码或映射。

JSON Schema可验证结构，无法独立验证所有时间关系、实际资源哈希、控制权限和模型消费者。本文的语义规则属于同等强制的运行时校验，不得以Schema通过代替。

## 3. 来源与范围

标书规定：3.3经CANFD/汽车以太网与3.6交换测试与仿真数据；全系统稳定通信80ms±1ms；模型计算1ms±10us；3.6任务/航线/控制/视频/记录/回放/物理HIL能力。方案规定：共同ICD、单正式接收路径、三类资源、原六工具链、E0至E3证据、仅部署配置切换。

本项目确定：HIL-ICD-1.0全部消息ID和字节布局、20ms控制周期、100ms控制超时、IP/UDP端口、CRC、容量、坐标/高度基准、字段范围和初值。这些数值不是标书指定值。传输性能必须在目标设备测量，不以软件文档保证实机满足。

不纳入临时替代：3.3内部资源池B/S、6席位工作流、自动测试报表管理、供电5V/±12V/28V、程控电阻等模块内部能力；3.4专用仪器内部驱动和TSN扩展不由模拟器重建。保留其外部总线刺激、故障、采集、记录与诊断职责。标书提供的GCS继续使用，不另造一套GCS。未因排除内部实现而删去3.3对3.6的输入消息。

## 4. 三类输入资源

### 4.1 PROTOCOL

ProtocolSource指定baseline_version、业务Schema实际哈希、ICD目录实际哈希、ResourceRef和消息ID清单。ResourceRef必须给出实际ID、SHA256、字节数、格式、编码、媒体类型与文件名。至少包含本版ICD_JSON和CANFD DBC；ARXML可作为导入资源，但解析结果必须与本版消息目录逐字段等价，不拥有另一个协议版本。

协议定义不是运行激励，不能把DBC本身当CAN数据发送。cantools按本版DBC处理帧字段；分片重组、CRC、会话、模型映射由共同执行器和3.6正式接收器处理。

### 4.2 SCENARIO

ScenarioSource含版本、模型步时钟、随机种子、完整Event、断言和Cleanup。SEND/FAULT引用Stimulus（消息ID+严格payload）；不预填运行session/sequence。执行器从当前正式会话分配header，记录E0，再进入对应工具链。

支持固定、阶跃、斜坡、正弦、线性扫频；周期启动/停止、反馈等待、回放、故障、断言和结束清理。所有事件按(at_step,priority,event_id)升序；同一步写同一实际目标端口的两个事件即使来自不同工具也拒绝，不能靠最后写入者获胜。event_id、sender_id、assertion_id在各自命名空间唯一。

NEGATIVE_SEND用于明确授权的负例用例：先校验合法Stimulus，再在发送工具前按NegativeMutation改值/删字段/加未知字段/改CRC/改序列/改session/改目标步/截断。改业务payload后重算分片长度和CRC，仅CRC_XOR或TRUNCATE保留故意损坏的校验。field_path为相对payload的点路径，数组用[i]，必须唯一命中；ADD_UNKNOWN_FIELD仅新增末级键，禁止覆盖已知字段。mutation只许一项，需authorization_case_id匹配已启用的T02/T05/T06负例测试，记录原码/改后码、预期拒绝码和must_not_apply=true；普通运行与任意未授权测试均禁止。负例绕过的是发送端第二次工程值校验，不绕过3.6正式接收/权限/Schema/映射检查。反馈必须为预期FAILED/REJECTED且无模型写入探针；否则该用例失败，不伪造APPLIED。此事件不是新的3.6私有入口。

波形仅写已有可写数值标量或固定数组的明确索引，禁止输出状态、字符串、bool和未注册路径。波形数值单位为目标字段单位；整段理论极值/每次采样均须符合目标范围，采样频率至少为最高信号频率的10倍，否则拒绝。ramp线性插值，sine为offset+A*sin(2*pi*f*t+phase)，chirp相位为2*pi*(f0*t+(f1-f0)*t*t/(2*T))+phase。t=(当前step-起始step)*0.001，终点后保持最后值，直到结束清理。

WAIT冻结该场景后续事件，不冻结模型；必须配置真实探针、时限和期望。超时失败并执行清理。ASSERT的WITHIN等价abs(actual-expected)<=tolerance；EVENTUALLY在时限内满足连续sample_count个样本；其余比较操作同名数学意义。非数值不允许tolerance非0，字符串/bool只允许EQ/NE/EVENTUALLY。FAULT事件只允许11/12/13/26/45，不能借其绕过发送权限。NEGATIVE_SEND.F64_BITS仅改PACKED_LE的明确f64字段（数组须给索引），8字节小端原码由bits_hex_le确定，用于NaN/Infinity负例并重算CRC；JSON非法数值不允许通过常规PATCH_VALUE伪装。BusFault.REORDER以window_frames或window_ms先到者收集一组，按原接收顺序反向发送，记录原/改后顺序；不超过既定有限队列，超时值照样触发正式迟到/安全规则。

### 4.3 HISTORY

HistorySource包含实际资源、各HistoryStream、解码基线哈希、捕获完整性和ReplayPolicy。CAN_LOG包括普通CAN和CANFD；PCAP/PCAPNG须按链路类型分出CAN或Ethernet，不能把CAN捕获当Ethernet帧喷射。ENGINEERING_JSONL每行是{offset_ns:十进制uint64字符串,stimulus:Stimulus}，只允许非递减offset_ns，不含反馈对象。

TO_36流才能注入；FROM_36只用于分析/断言。未识别方向或无法解码直接拒绝。truncated_packets/lost_packets非0的捕获禁止ONLINE，OFFLINE可分析但不能形成完整链路通过结论。

ONLINE固定1X；0.5X/2X/4X与seek仅OFFLINE。start_offset_ns<=end_offset_ns且落在捕获范围。REENCODE/SESSION_REBUILD重复次数1..10000，每轮新会话、清空接收队列并恢复初始状态。REENCODE从工程值按本版编码；RAW_VALIDATED仅repeat_count=1、session_policy=CURRENT_VALID_SESSION、rewrite_fields为空，原session仍合法、序列新鲜、目标步有效、白名单源/目的有效且CRC正确，跨新会话不能照搬旧包；SESSION_REBUILD仅允许所列六类会话/序列/目标步/事务/部署端点/CRC重写，业务payload不变，保存原始和重写哈希。

TCP抓包不可直接成为本版UDP业务。交互TCP历史必须先解析为Stimulus并由正式会话执行器重建，不允许tcpreplay假冒会话交互。

## 5. 管理面与正式数据面

Web管理API版本0.3，共25命令，资源上传/读取/分页/运行/报告的已有字段见v0.3 API Schema；api_version和request_id仍位于params。包资源与规则元数据引用v0.2 package Schema，不能把它解释为业务协议回退。管理列表validation_status采用NOT_CHECKED/VALID/INVALID，前者是尚未执行校验的生命周期状态，不是未确定输入字段；原ICD_PENDING错误改为BASELINE_MISMATCH。本版examples均标为Schema测试数据，不是具有真实测试包/场景引用和已资格确认端口的可执行发布包。

simulator_run_create新增三个必填：baseline_sha256、run_configuration:RunConfigure、source_inputs:SourceInputs。仍须提供package_ref、scenario_ref、mode、source_binding_ref、link_ids；它们与source_inputs身份、版本、实际哈希必须一致。protocol必有，scenario/history至少一个非null。创建只完成配置和资源校验，不隐式开始模型。

simulator_run_update_inputs不再接收自由values字典：params含api_version、request_id、run_id、expected_revision、link_id、message:BusinessInputMessage。反馈消息129..142在此API一律拒绝。expected_revision按uint64实际值检查并做CAS；成功改变运行对象后加1。前端按模型选择Quad/Hex/Fixed分支，不得把hex向量截成4维。

管理面ACCEPTED只代表执行请求排队，不能等价APPLIED。后端把请求ID与真实session/sequence/transaction关联，报告真实E1/E2/E3。source_id只用于会话授权和追踪，不可触发3.6模拟/真实分支。

大文件仍走管理资源分块上传或ResourceChunk到独立资源服务，不能直接塞进模型root input。v0.2上传块上限65536不改变；正式ResourceChunk每块最大32768，二者不是同一报文。正式JSON逻辑消息上限65536字节，较大的模型/视频/地形文件上传完成、SHA256校验、内容Schema校验后再激活。MissionLoad若编码超过65536必须拒绝，不能静默裁剪任务/航点。

## 6. 消息目录

所有payload字段见逐字段定义。表中周期0表示事件触发，不表示禁止周期发送；重复计划仍须遵守容量和权限。CAN ID为空的消息只能走UDP正式链路。

| ID | 消息 | 方向 | 载荷编码 | CAN ID | 周期ms | 有效期ms | 角色 | 反馈 |
|---|---|---|---|---|---|---|---|---|
| 1 | SessionOpen | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | ANY_SESSION_ROLE | SessionOpened |
| 2 | Heartbeat | TO_36 | PACKED_LE | 0x302 | 20 | 1000 | ANY_SESSION_ROLE | Status |
| 3 | RunConfigure | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 4 | Lifecycle | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 5 | InitialState | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 6 | ControlOwner | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 7 | FlightQuad | TO_36 | PACKED_LE | 0x307 | 20 | 100 | CONTROLLER | Ack |
| 8 | FlightHex | TO_36 | PACKED_LE | 0x308 | 20 | 100 | CONTROLLER | Ack |
| 9 | FlightFixed | TO_36 | PACKED_LE | 0x309 | 20 | 100 | CONTROLLER | Ack |
| 10 | Environment | TO_36 | PACKED_LE | 0x30A | 80 | 240 | STIMULUS | Ack |
| 11 | FaultQuad | TO_36 | PACKED_LE | 0x30B | 0 | 1000 | STIMULUS | Ack |
| 12 | FaultHex | TO_36 | PACKED_LE | 0x30C | 0 | 1000 | STIMULUS | Ack |
| 13 | FaultFixed | TO_36 | PACKED_LE | 0x30D | 0 | 1000 | STIMULUS | Ack |
| 14 | ActuatorQuad | TO_36 | PACKED_LE | 0x30E | 20 | 100 | CONTROLLER | Ack |
| 15 | ActuatorHex | TO_36 | PACKED_LE | 0x30F | 20 | 100 | CONTROLLER | Ack |
| 16 | ActuatorFixed | TO_36 | PACKED_LE | 0x310 | 20 | 100 | CONTROLLER | Ack |
| 17 | TuneQuad | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 18 | TuneHex | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 19 | TuneFixed | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 20 | MissionLoad | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 21 | MissionControl | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 22 | FlightCommand | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 23 | Targets | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 24 | EnvironmentExt | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 25 | SystemStimulus | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 26 | BusFault | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 27 | SerialWrite | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 28 | AnalogWrite | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 29 | DigitalWrite | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 30 | VideoConfig | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 31 | VideoControl | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 32 | VideoAnnotation | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 33 | ClockSync | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | OBSERVER | ClockStatus |
| 34 | ResourceChunk | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | ResourceAck |
| 35 | Query | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | OBSERVER | Ack |
| 36 | RecordControl | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 37 | Cleanup | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 38 | SessionClose | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 39 | SensorConfig | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 40 | PhysicalChannelConfig | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 41 | Terrain | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 42 | Obstacles | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 43 | VideoFrameMetadata | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 129 | SessionOpened | FROM_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | RECEIVER | NONE |
| 130 | Ack | FROM_36 | PACKED_LE | 0x481 | 0 | 1000 | RECEIVER | NONE |
| 131 | Status | FROM_36 | PACKED_LE | 0x482 | 80 | 240 | RECEIVER | NONE |
| 132 | State | FROM_36 | RFC8785_JSON_UTF8 | - | 20 | 1000 | RECEIVER | NONE |
| 133 | Sensors | FROM_36 | RFC8785_JSON_UTF8 | - | 4 | 1000 | RECEIVER | NONE |
| 134 | IOStatus | FROM_36 | RFC8785_JSON_UTF8 | - | 80 | 1000 | RECEIVER | NONE |
| 135 | VideoStatus | FROM_36 | RFC8785_JSON_UTF8 | - | 80 | 1000 | RECEIVER | NONE |
| 136 | TaskStatus | FROM_36 | RFC8785_JSON_UTF8 | - | 80 | 1000 | RECEIVER | NONE |
| 137 | RecordStatus | FROM_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | RECEIVER | NONE |
| 138 | Diagnostic | FROM_36 | RFC8785_JSON_UTF8 | - | 80 | 1000 | RECEIVER | NONE |
| 139 | Capabilities | FROM_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | RECEIVER | NONE |
| 140 | Evidence | FROM_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | RECEIVER | NONE |
| 141 | ResourceAck | FROM_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | RECEIVER | NONE |
| 142 | ClockStatus | FROM_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | RECEIVER | NONE |
| 44 | RawBus | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |
| 45 | SensorFault | TO_36 | RFC8785_JSON_UTF8 | - | 0 | 1000 | STIMULUS | Ack |

## 7. 实际线上编码

### 7.1 公共逻辑消息

header固定session_id、sequence、target_step、transaction_id、valid_for_ms。sequence在每个session、每个发送方向内严格递增，不回绕；多个链路统一取号，不能各链路重复使用。transaction_id用于分片/事务关联，单逻辑消息各分片同号。除SessionOpen和其被拒绝的响应外session不得为0；接收方分配非0且不复用有效session。SessionOpen header session=0,target_step=0，sequence=1。

SessionOpen绑定run/source/vehicle/scenario/model/基线版本与哈希；其余快报文用session查回全部身份。身份不变更，不从端点或文件名猜。会话lease统一1000ms；requested_lease_ms其他合法请求值只表达请求，返回值必须为1000，本基线不授权动态安全超时。20msHeartbeat即使模型暂停仍按接收机单调时钟发送。租约到期终止所有写权限、清理并触发安全；100ms控制超时独立生效，Heartbeat不能续期执行器命令。

PACKED_LE载荷仅按ICD目录fields固定顺序/偏移打包，无对齐填充；double=f64 little-endian，boolean一字节0/1，enum用目录enum_codes。只能有精确payload_bytes，禁止尾随数据。FaultHex中motor_5/6字段在末尾偏移76/77，不能推断按命名重排。

JSON消息的线上载荷仅payload对象，不发送BusinessMessage管理包装。UTF8编码，禁止BOM、重复键、NaN/Infinity/孤立代理项，按[RFC8785](https://www.rfc-editor.org/rfc/rfc8785)规范化序列化；不能用普通“sort_keys”加不同浮点格式假称规范化一致。请求ID与64位时间使用字符串。资源文件整体SHA256基于原始字节，不基于重排后的JSON；黄金向量和分片CRC基于实际线上字节。

### 7.2 CAN FD

11位标准ID，FD=1、BRS=1、64字节，标称500kbit/s、数据2Mbit/s。CAN_ID见目录，非FD、错误ID/长度/BRS拒绝。帧字段：

| 字节偏移 | 长度 | 字段 |
|---|---|---|
|0|1|major=1|
|1|1|minor=0|
|2|1|flags=0|
|3|1|本片有效payload长度1..38|
|4|4|session u32le|
|8|4|sequence u32le|
|12|4|target_step u32le|
|16|4|transaction u32le|
|20|1|fragment_index 从0开始|
|21|1|fragment_count 1..7|
|22|2|valid_for_ms u16le|
|24|38|有效片字节，尾部00补齐|
|62|2|CRC16 u16le|

CRC16_CCITT_FALSE：poly=0x1021、init=0xffff、refin/refout=false、xorout=0；输入=CAN_ID两字节小端||帧字节0..61，“123456789”校验0x29b1。它是应用校验，不替代CAN控制器物理层CRC，也不提供身份认证。

大于38字节按顺序切片，每片除chunk_length/index/片内容/CRC外全部header一致。fragment_count=ceil(精确payload_bytes/38)，非末片长度38，末片长度取剩余，padding必须0。重组键=(channel,session,direction,message_id,sequence,transaction)；必须收到全部分片并校验精确总长度，20ms未完成拒绝。相同片索引而字节不相同整组拒绝；同字节重传只记重复，不二次应用。跨CAN通道不能把半组片拼接成一组。

### 7.3 UDP

IPv4 UDP payload最大1200字节，不依赖IP分片。40字节小端header，payload片最长1160，逻辑JSON最长65536、最多57片。布局和CRC覆盖范围以ICD目录codecs.UDP为准；magic=HIL1，major=1/minor=0，flags/reserved=0。CRC32_ISO_HDLC poly=0x04c11db7、init/xorout=0xffffffff、refin/refout=true，“123456789”校验0xcbf43926；覆盖header0..35||本片实际payload，不含CRC字段。

fragment_index/count的索引规则同CAN，非末片1160，末片剩余，不加尾部padding。收到大小必须精确40+payload_length。重组键加接收接口与发送方向，100ms到期整组拒绝。未经授权的源IP/端口不建重组缓存。

UDP没有传输ACK，使用本版Ack/ResourceAck；可靠管理命令200ms无终态可按原sequence/transaction最多重传3次，接收方去重缓存8192消息/5秒并重发已有真实反馈，不重复业务。新事务必须新sequence，资源未完成的最终commit可等待10000ms。周期控制/环境报文不重传过期旧值。

跨链路同一sequence只允许完全相同的逻辑消息冗余副本，不可通过重发不同值“更新”。不同值产生DUPLICATE/BUSINESS_FAILED并记录证据。

## 8. 模型步、权限与安全

目标step单位1ms、从0开始，运行最长86400000步（24小时），在任何计数器回绕前关闭并新建会话。运行中的可写输入须在目标步开始前完成校验与入队，ahead范围1..1000步，迟到容忍0，适用步到了仍未完整重组则整组拒绝；禁止晚到追赶。valid_for_ms是从target_step对应模型时刻起可保持的最大有效时间，同时控制命令不得超过100ms接收端单调时间超时。

队列4096逻辑消息，每端口重组64槽，总重组8MiB。满时拒绝BUFFER_FULL，禁止覆盖未应用值。逻辑消息在目标模型步整体应用，不对数组/同一Fault消息逐片写入。跨消息/跨总线原子事务本版不提供：需要同步时用同一目标步且目标互不相交，或一个含全部输入的正式消息；不能误称“同一transaction_id自动跨消息原子提交”。

单写者登记model、target port、role、control_source、input_lane。INTERNAL_CONTROLLER只接收声明控制器输出；FLIGHT_CONTROL只接收7..9；ACTUATOR只接收14..16。两类消息映射到同一根输入但不能同期开启，STIMULUS不能冒充CONTROLLER。DEMO_MISSION只适用四旋翼；六电机/固定翼必须PX4_SITL或PHYSICAL_UUT/既有GCS。ControlOwner从NONE到有效源或切换源只能PAUSED，先写安全值并清队列再授权；租期固定100ms。

执行器映射：四旋翼motor_command[0..3]对应motor_01..04；六电机[0..5]对应motor_01..06；固定翼顺序throttle/roll_cmd/pitch_cmd/yaw_cmd。全部安全0；越界拒绝，不clamp。失效只改变有效执行器，不篡改收到的控制输入证据。

控制超时：100ms没有新、有效、实际被接收的控制命令，模型下一边界写安全0，撤销控制租约并发SAFETY反馈；暂停时停止推进模型但物理输出仍安全置0，不能保持危险电平等待resume。环境有效期240ms到期停止运行并恢复配置初值；模型Fault显式保持直到清理/新Fault快照，不因消息TTL到期自动假装修复。

## 9. 状态机与命令条件

SessionOpen只创建正式接口会话，不启动模型。RunConfigure只允许STOPPED或初始CONFIGURED；模型ID、原点、资源、随机种子、初始状态及物理配置必须全部准备好后返回CONFIGURED，尚未准备返回FAILED，不偷偷使用旧配置。initial_inputs给出所选模型完整的flight_control/environment/fault/parameters及扩展环境/系统刺激快照，分支model_id必须与RunConfigure.model_id相同；控制初值必须全部安全0、故障按显式初值初始化。RESET恢复这份快照，不能用上一次会话值或隐式默认代替。

START: CONFIGURED→RUNNING；PAUSE: RUNNING→PAUSED；RESUME: PAUSED→RUNNING；STOP: RUNNING/PAUSED/CONFIGURED→STOPPED；RESET: PAUSED/STOPPED→CONFIGURED。expected_state必须匹配。停止、复位、恢复均清队列，不追赶漏掉的历史报文；RESET恢复初始状态、输入和参数，关闭旧会话后重新SessionOpen。RESUME保留暂停后的模型状态，但须清旧队列、以新会话重新授权发送。暂停/配置态的生命周期与RESET_ONLY控制在服务安全边界处理，此时target_step等于冻结当前步，不要求冻结模型推进一步才能处理。

STEP只允许PAUSED，step_count=1..1000，按1ms步长顺序推进恰好该数量模型步后仍PAUSED；不得按一个大步近似。离线单步时物理输出保持安全且控制源NONE，真实硬件闭环模式禁止STEP，避免把离线时间压缩用于实物控制。反馈带实际最后应用步。管理simulator_run_control的STEP按同样语义，无额外步数字段时固定1步；多步使用Lifecycle.STEP消息明确提供step_count。

InitialState仅CONFIGURED/PAUSED并紧接RESET生效；它设置模型内部初始化条件，不写state.outputs。四元数长度误差<=1e-6，不归一化修正错误值；位置/高度、airborne必须与地形和ground_height一致。Quad/Hex初值静止在地面；Fixed初值亦由RunConfigure显式给出（既有模板默认12m/s不能隐式覆盖用户初值），因此初始化端口需实现。

TuneQuad/Hex/Fixed采用全量参数快照；字段范围与相应现有模型契约完全一致。RUNNING在目标模型步应用；PAUSED/CONFIGURED允许环境、故障、传感配置和tune在冻结当前step的安全服务边界应用到真实输入/参数快照，必须target_step等于当前step且有实际setter/getter探针，不推进模型，不声称已产生动力学响应。恢复保留已确认的快照、清空旧队列；RESET仍恢复initial_inputs。solver_step、拓扑、端口、端点禁止tune。模型载入/编译资源不是实时参数，必须停止并校验契约后下载。

FlightCommand送到选定控制器：TAKEOFF只LANDED；LAND只TAKEOFF/FLYING；HOVER只多旋翼FLYING；加减速/ATTITUDE只FLYING；MANUAL切换须合法控制源，AUTO需已装载可用任务。固定翼HOVER必拒绝UNSUPPORTED，不假装悬停。动作前验证高度、速度、控制器能力和资源。

SET_TARGET完整给出目标地理位置、离地高度、速度、航向与爬升率，只用于已授权AUTO控制器且FLYING。target_position的高度转换后须与altitude_agl_m及地形一致（<=0.1m），否则拒绝；固定翼速度为真空速且需>=该控制器声明最小空速，多旋翼为地速；heading_rad按NED北向为0，向东为正；climb_rate正值向上，与模型vd符号相反。目标交给控制器，不直接写模型位置/姿态状态。

本项目fixed_wing_hil最小目标真空速确定为12m/s（最大100m/s），不是待真实3.3提供的参数；真实飞控若无法支持该模型目标，能力验收失败而非改变3.6解码。Quad/Hex最小目标地速0，最大100m/s。Ack.request_message_id和Evidence.message_id允许0..65535，以便记录畸形/未知报文的实际ID；合法业务输入仍只允许1..45，不能因反馈字段范围更宽而开放未知输入。

MissionLoad整体校验后交给既有GCS或声明控制器；只有实际控制器读取并有探针才能CONSUMED。当前load_mission只支持简化四旋翼航点，不代表已实现Task/圆/曲线/任务依赖。其映射器在3.6内部统一实现，对模拟器和正式3.3相同，正式替换时不能再改它。

## 10. 任务、地理与资源语义

WGS84为地理基准，限制纬度±85度、经度±180度、本地NED±100km水平范围。Origin一次配置冻结；MSL转椭球高=MSL+geoid_separation，AGL转椭球高=相应点地形椭球高+AGL。AGL点无对应地形资源就拒绝RESOURCE；不能用飞行起点地面高度替代所有航点地形。转换使用标准地理坐标库并做往返误差测试（水平/垂直<=0.01m），不用经纬度线性近似偷换。

LocalPoint.down_m向下为正；ground_height_m是相对原点向上为正的地面高度，ground_down=-ground_height。姿态FRD→NED四元数qw,qx,qy,qz；角度字段有deg/rad后缀，以Schema单位为准，禁止混用。

任务task_id/route_id/waypoint_id必须唯一且引用存在；依赖图无环，start_step<end_step、end在运行范围内，任务timeout不越出计划结束。geometry决定路线形状，waypoints是该形状的离散执行点，必须验证一致性（点到线/圆/插值曲线或多边形对应边误差<=0.1m）。waypoint.order为0..N-1连续序列，execute_from_index<N。LANDING点必须安全且完成半径合法。

区域是闭合多边形（不重复末点），至少3个互异点，不自交；circle的circle center+radius+clockwise+laps具体确定；FREE_CURVE使用向心Catmull-Rom、端点重复延拓，各段按sampling_distance_m采样且最长50实际航点，超限拒绝CAPACITY，不截断。POLYGON.closed=false可作为折线但至少3顶点。路径长度、预计完成时间、创建时间、执行任务状态是3.6计算/记录的反馈，不从3.3输入强行覆盖。

Targets.REPLACE_ALL用完整targets且remove_ids为空；UPSERT用非空targets且remove_ids为空；REMOVE用非空remove_ids且targets为空；target_id唯一。目标航向NED参考北、向东为正；目标位置按速度在模型步线性推进。标注和任务引用目标前检查存在。

TerrainResource.height数组必须rows*columns，北方向索引优先：index=row*columns+column，row沿north增加、column沿east增加，资源origin等于当前Origin；缺数据和越界拒绝，不偷偷补海拔0。ObstaclesResource中CYLINDER用radius和height，BOX用width/length/height和heading，未使用尺寸仍必填但按给定初值且不参与计算；清障判定需加入clearance，路线穿过任何激活障碍拒绝。

资源激活41/42的hash必须是已完成校验的对应TerrainResource/ObstaclesResource；activate_at_step与header.target_step一致。资源原始文件可大于64KiB，不能作为41/42消息携带全部数组。ResourceChunk的base64合法且解码长度=chunk_length、offset+length<=size、每块与整体SHA256均真实一致，offset连续不重叠，final仅末块；重复块字节相同可重发，不同拒绝。资源必须在停止/暂停时提交模型/地形，视频资源允许后台预载但不能占用实时队列。

## 11. 模型输入与缺口的明确落实

现有全部根输入、参数范围/初值/导出符号均列在97条model_bindings中，不凭字段名猜内存偏移。运行时实际hil_contract必须与本版所选模型等价；contract缺字段拒绝，不能退到任意JSON内部命令。未来新增型号/端口须新基线，不能走自由扩展键。

Environment六个字段按输入名直接绑定。EnvironmentExt：IDEAL_GAS密度=pressure/(287.05*temperature)，EXPLICIT使用air_density_kg_m3；基础wind+gust+风偏置成为气动力输入，湍流/传感噪声以配置随机种子生成。gravity直接进入模型重力项，载荷质量参与总质量，FRD载荷力/力矩进入动力学，天气/光照进入视频场景；每个值都有消费者，不能“已接收但没用”。

Fault统一语义：GPS偏置只作用GPS，IMU角速率偏置只作用IMU，不污染State真值；command_delay_ms为FIFO真实命令延迟，非整数毫秒向上取整至模型步；sensor_delay_ms为传感输出缓存延迟；packet_loss_ratio按种子生成独立Bernoulli输入丢弃，不把它简化成降低电机功率。延迟后的控制仍不得突破100ms安全时限，故过大延迟可以有意触发安全测试。motor_i_failed将对应有效执行器归0。

固定翼遗留字段motor_1_failed为发动机失效；motor_2_failed为滚转通道失效、motor_3_failed为俯仰通道失效、motor_4_failed为偏航通道失效。本版保留字段名保持明确绑定，但必须实现后3个通道失效效果，不能因模板当前忽略f2/f3/f4就宣称完整。

SensorFault补齐T08：gps_valid=false须同时gps_fix_type=NO_FIX；gps_freeze保持最后有效GPS值和旧采样时间，gps_stale_ms对实际采样时间回退指定毫秒；imu_freeze/imu_stale_ms同理，imu_valid=false向飞控明确发布无效，不以全零样本替代。magnetometer_valid/barometer_valid明确控制其有效标记。duration_steps=0表示保持到显式新快照或cleanup；大于0在该模型时限结束，clear_at_end=true恢复全部valid=true、freeze=false、stale=0、GPS FIX_3D，否则保持。传感冻结/失效不冻结模型真值；Sensors内各传感器须携带实际采样step，消费端能判断陈旧，而不是只有消息发送步。此适配器是必选实现项。

既有模型还有近似实现：部分pressure/temp输入在多旋翼中未使用；command_delay曾被当一阶时间常数；packet_loss曾被当推力缩放；偏置曾直接改输出状态；六电机缺5/6失效。上述行为均不是本版通过标准，须修正实现并验证真值/传感值分离。这里只制定正确契约，不声称已经修复这些模型。

SystemStimulus给出发动机负载、供油比例、液压供给、电源电压、航电通电、载荷质量/力/矩、发动机/燃油/液压/电气故障刺激。State的RPM/剩余燃油/液压/电压/航电是独立模型输出。选用模型无相应子系统时反馈null或UNAVAILABLE且capability不能发布支持；要求这些验证的测试包启动就拒绝，不能用输入回显骗过E3。本版完整能力验收须有实际子系统消费者，不以支持基础飞行子集替代全部标书3.6能力。

SensorConfig.IMU250Hz、GPS20Hz、mag50Hz、baro50Hz；Sensors反馈在4ms定时更新，慢传感器保留上次样本，消费端按其独立频率取样，不能每4ms伪造新GPS。FRD加速度是specific force，静止水平约[0,0,-9.80665]，不是世界系运动加速度；State.ax/ay/az为现有模板输出的NED运动加速度，不可直接当作IMU比力。IMU比力须减去NED重力再由姿态旋转至FRD。

## 12. 物理通道与原工具链

56个端口目录全部明示：CANFD_0..3、CAN_0..3、ETH_0..3、RS232_0..3、RS422_0..7、AD_0..7、DA_0..7、TTL_0..15。active_channels决定启用集合，必须全在实际qualified_channels中。

每个ETH_i：source=10.36.i.10、receiver=10.36.i.20、video=10.36.i.30、/24，速率1000Mbit/s、VLAN=0（不打tag）。正式业务目的36100、反馈目的36101、源端口36102、视频36110；模拟器接收反馈需监听36101。地址是逻辑部署初值，实际网卡/端点可按白名单改变，不修改编码/接收代码。receiver反馈源36100，源与目的ACL双向登记。同一正式3.6逻辑接收器可绑定四个接口，但不能新设模拟器UDP9996入口；现有9997/9998仅内部C服务，不对3.3直接开放。

普通CAN不是本版正式业务报文承载，而是标书要求的辅助总线验证能力：RawBus限定标准ID0x600..0x6ff，不得写正式CANFD业务ID。CAN经典8字节、CANFD合法DLC；data_hex实际字节数必须等于dlc/data_length，禁止截断补齐。Ethernet辅助RawBus发到36150，与正式36100隔离，不得把raw端口包当已应用模型输入。额外UUT私有总线映射需要新的闭合正式资源基线，不能任意bytes自动写模型。

串口固定921600/8N2（本项目在标书列出的8位双停止位能力内选定）；SerialWrite长度1..1024字节，按发送顺序输出，flush仅本事务前；receive_timeout_ms到期记TIMEOUT，接收到的IOStatus不自动假装标准业务ACK。串口和raw总线消费证据来自真实驱动写入/回读探针。

AD/DA均±10V，8通道数组按0..7，AD1000Hz采集，DA按目标步更新，slew限制每步变化<=slew_v_s*0.001。TTL16通道按0..15，输入/输出方向在PhysicalChannelConfig指定，默认全部INPUT；仅OUTPUT且enabled=true可写，低0V高3.3V为项目目标电平，不是未经测量的硬件事实。pulse_width_us=0为持续电平，非0为脉冲后回安全false；物理驱动不支持所需微秒脉宽应拒绝，不能用1ms线程假称精确微秒输出。

AD/DA每通道gain/offset校准映射：physical_v=gain*engineering_v+offset；读入用逆变换；measured=false不允许启用该实际通道，初值1/0只是离线配置。gain0.5..2、offset±1V；转换结果超±10V拒绝。I/O首次通电、断链、STOP/RESET/cleanup均安全DA0、TTL输入或低、电气故障开关复位。电气故障仅授权故障板和隔离安全通道，软件不得伪称真实短路。

视频机独立VIDEO_ETH_0/1分别复用ETH_0/1网络定义的video端点，不计入3.6四端口；两个同步RS422定义为SYNC_CLK=1000Hz、SYNC_ENABLE高有效，触发在升沿，不能当8N2串口发字符串。实际引脚/驱动映射需设备qualified能力声明，未达成禁止物理用例。

六条工具链完全保留。CANT生成已确定CAN FD帧；CUTIL/SAVVY默认只观察，若获SEND授权则用同一合法会话/取号/CRC规则；CANREPLAY不能由canplayer本身猜测新会话，先验证合法原码或生成新会话回放日志；ETHGEN先生成正式UDP字节，再由Ostinato/Scapy发送；ETHREPLAY先验证/重建pcap，tcpreplay只负责发帧。SocketCAN在Linux使用，Windows仅用已资格确认的python-can/vendor SDK，不能把未实现SDK称已联通。分片/编码器与编排可位于工具前，共同解码/映射在3.6内部，不添加强制外置汇聚转发器。

## 13. 视频完整输入

VideoConfig三种闭合配置：H264 1280x720/YUV420P/30fps/12Mbit/s；H265同分辨率/30fps/8Mbit/s；RAW 640x480/BGR24/30fps/221184000bit/s。fps=30/1，H26x GOP30，RAW GOP1。资源hash和stream_id/stream_numeric_id绑定，数字ID在会话内唯一且不可更改。

MANUAL由TRIGGER一次；PERIODIC按period_ms触发；EXTERNAL来自同步使能升沿；PHASE由指定飞行阶段首次进入触发；EVENT由声明event_id触发。ANY仅非PHASE触发使用；PHASE要求非ANY，EVENT要求实际事件存在。首次触发定义t0_step，循环资源末尾回到第0帧并创建新frame_index；非循环结束STOPPED。VideoControl.SEEK仅OFFLINE/PAUSED，TRIGGER不得在未就绪资源上发生。frame_index对SEEK有效，其余动作必须0；trigger_id仅TRIGGER有效，其余为显式合法标识但不执行触发。

实际像素不塞进JSON：HIV1视频UDP48字节header，分片1152、max1821片，CRC32覆盖0..43+实际payload，布局见ICD目录。H264/H265一帧一个Annex B access unit，首个解码帧必须含参数集和IDR；RAW每帧921600字节，行优先、每像素BGR、不含行padding。VideoFrameMetadata给出资源字节区间和实际frame_sha256（触发时可用该帧资源片段），片重组后完整帧哈希须一致，metadata和像素的session/stream_numeric_id/frame_index/capture_step必须一致。

PTS以微秒uint64、第一帧0，帧k相对时间round(k*1000000/30)，取最近整数，恰半向上。capture_step=t0_step+round(PTS/1000)，不靠网络到达时刻触发。标注capture_step与像素一致，姿态/位置来自对应模型步的真实快照；无法证明对应则拒绝或记CLOCK_UNSYNC，禁止拿当前状态覆盖历史帧。VideoAnnotation由STIMULUS声明的预置资源标注不得冒充实时模型真值。

视频4帧有限队列、100ms重组期限、完整帧上限2MiB、相对模型步同步容差1000us。晚帧丢弃并报告，不累积追赶；实际设备没达到容差则测试失败，不改标记掩盖。用VideoStatus.last_consumed_frame和注入设备探针证明实际消费，last_received_frame仅E1。

## 14. 反馈与证据

Ack.request_sequence/message_id唯一关联输入，stage依次RECEIVED、VALIDATED、APPLIED/CONSUMED或FAILED。接收不等于校验；校验不等于模型应用；模型输入才有APPLIED，转发任务/视频/资源只有消费者实际读取才CONSUMED。重复请求返回缓存已发生的真实阶段，不生成第二次应用。ACK整数枚举编码见目录，无自由字符串错误码。

State真实模型输出；Sensors来自同一步真值加明确传感处理；IOStatus真实采样；TaskStatus来自控制器；VideoStatus来自解码/注入器；RecordStatus的hash只在文件实际完成后非null。状态字段超出声明范围报告失败而非裁剪显示。

E0发送计划/实际TX，E1接收/校验，E2真实模型写入或消费者读取，E3可观察业务/安全响应。Evidence关联trace/event/request/message/step/mono时间/探针/hash。对端没有E2探针必须报告NOT_EVALUATED，不能由模拟器自签E2。Status.applied_count/consumed_count只统计真实探针；合并丢弃的请求不计应用。

探针名称和数字ID由ICD目录probe_catalog统一定义：0/NO_PROBE仅未应用阶段使用；1..97是明确模型路径探针；1000+message_id是对应消息消费者探针。Ack.probe_id用数字ID，Evidence/Assertion用同表名称。Capabilities.available_probes只发布已经实现的真实探针；E2断言不得选NO_PROBE或不存在的探针。一个多字段消息的APPLIED用消息消费者探针，逐字段证据用模型路径探针，不用任意字符串或本机自增编号。Sensors各传感器sample_step为实际数据采样步，age_ms为当前step减采样步；尚无有效样本、请求回退到会话开始之前或age超过其正常周期3倍，valid必须false，不能回填“当前采样”。SensorFault也属于initial_inputs和cleanup恢复范围。

ClockSync/Status用真实双向测量；uint64字符串值不得超18446744073709551615。未达跨机时钟不确定度<=500us，禁止计算跨机单向延迟或声称满足1ms同步；可报告单机mono相对延迟、模型step一致性和CLOCK_UNSYNC。同步RS422、模型step和UTC是不同域，不混用。

## 15. 容量与验收

单通道总利用率目标<=50%。模型1ms解算不意味着所有CAN报文1ms广播；快控制20ms、环境/综合状态80ms，IMU数据反馈走Ethernet4ms、慢传感器各自更新。只选相应模型一个控制lane，不能四旋翼+六电机+固定翼控制同时发同一vehicle。视频RAW约221.2Mbit/s，加视频分片/IP/Ethernet开销后仍须实际测量1G链路裕量；不能放到100M链路宣称通过。后台资源限20Mbit/s并低于实时优先级。任何负载超预算在启动前拒绝CAPACITY。

正式替换门禁：
- 全部适用输入字段有编码/解码/映射/消费者/探针；每个字段做最小/最大/初值/缺失/错误类型/越界/错误模型测试。
- 三源组合、六工具链、L01..L10和T01..T14全部适用必选用例通过；真实CANFD与Ethernet双向闭环不能用vcan替代。
- 正常/暂停/断链/错误源/过期/乱序/分片丢失/负载过高/故障清理均有真实E0..E3证据，verify_false不能跳过。
- 真实3.3提交同一版本和实际Schema/ICD/映射/模型契约哈希，同消息ID/编码/角色/时序/反馈通过同套黄金向量和用例。
- 记录3.6程序、依赖、驱动、ICD、映射、模型契约和测试基线的实际发布哈希。替换后这些保护项完全不变。
- 只允许SOURCE_ENDPOINT、DEVICE_ID、CREDENTIAL_REF、AUTHORIZATION_REF、DEPLOYMENT_BINDING白名单部署键更改；不得新增源专用适配器、新解码器、mock/real分支或容错补丁。

输入定义现在由本项目完整确定；未来3.3实现必须对标本版，不能以其尚未开发完成为理由保留未定义字段。如果实际业务/设备无法满足本版，应在共同基线发布前修正双方设计并重新验证，不能到替换时只改3.6接收逻辑。

## 16. 当前验证边界

本次只交付接口定义和静态QA，不改应用、C运行时、Simulink模型、GCS和硬件驱动。静态通过证明结构/覆盖/编码测试数据一致，不证明1ms实时能力、真实电气安全、实际视频注入或正式3.3替换完成。

执行QA：artifacts/interface_contract_validation/check_contract_v03.py。报告区分STATIC_PASS与runtime/physical/replacement NOT_EXECUTED。现有v0.2历史示例不作为本版联调数据；本版测试数据的实际文件哈希由manifest生成。
