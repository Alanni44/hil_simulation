# 标书与方案输入覆盖对照 v0.3

依据原始文档和修订方案，26组需求全部给出设计定义。下表是范围/定义对照，不是运行或硬件验收证据。逐字段边界、类型、缺失、消费者与E2/E3均须单独验证，不能用某组一个样例代替整组验收。

| 编号 | 原文依据 | 需求 | 本版定义/目录 | 验收入口 |
|---|---|---|---|---|
| R01 | 标书3.3/方案10 | 模拟器仅临时代行3.3对3.6输出及反馈职责 | Identity,SessionOpen,SessionClose；所有 TO_36/FROM_36 消息 | T14 |
| R02 | 方案9.6 | 协议资源实际字段/编码/版本/哈希 | ProtocolSource,ResourceRef；全部消息目录/DBC/ICD_JSON | L01,T01 |
| R03 | 方案9.6/9.8 | 场景激励/调度/反馈等待/断言/清理 | ScenarioSource,Event,Waveform,Assertion,Cleanup；Stimulus | L05,T04,T09 |
| R04 | 方案9.6/9.9 | 历史输入类型/方向/时钟/完整性/会话重建 | HistorySource,HistoryStream,ReplayPolicy；TO_36_ONLY | L06,T05,T10 |
| R05 | 方案9.15/9.16图二 | 原六条工具分支及权限保留 | toolchains,channels；CANT,CUTIL,SAVVY,CANREPLAY,ETHGEN,ETHREPLAY | L01,L02,L03,L04,L06 |
| R06 | 标书3.3/3.6 | 全系统80ms±1ms与模型1ms±10us分层 | RunConfigure,Header；Heartbeat,Environment,Status | T01,T12,T13 |
| R07 | 方案4.3/9.11 | 控制来源/单写者/安全退出/暂停复位 | ControlOwner,Lifecycle,Cleanup；7..16,4,6,37,38 | L05,L08,T02,T04,T06,T09 |
| R08 | 标书3.6/方案4.3 | 四旋翼/六电机/固定翼全部现有输入与参数 | FlightQuad,FlightHex,FlightFixed,Environment,FaultQuad,FaultHex,FaultFixed,TuneQuad,TuneHex,TuneFixed；97模型路径含新增失效5/6 | L07,T01,T02,T03,T07,T08 |
| R09 | 标书3.6 | 起飞/着陆/悬停/加减速/姿态/手自切换 | FlightCommand；22 | L07,T03,T08 |
| R10 | 标书3.6 | 航线线段/圆/多边形/自由曲线与航点动作 | RouteGeometry,Waypoint,WaypointAction,MissionLoad；20,21 | L07,T03,T08 |
| R11 | 标书3.6 | 巡检/拍照/监测/巡航任务、时间、优先级、区域、依赖 | Task,TaskDetails,MissionControl；20,21,136 | L07,T03,T08 |
| R12 | 标书3.6 | 目标态势/地形/障碍/坐标转换 | Targets,Target,Origin,GeoPoint,Terrain,TerrainResource,Obstacles,ObstaclesResource；23,41,42 | L07,T03,T08 |
| R13 | 标书3.6 | 风/压力/温度/阵风/扫频/载荷/外界环境 | Environment,EnvironmentExt,SystemStimulus,Waveform；10,24,25 | L07,T07 |
| R14 | 标书3.6 | 初始位置/速度/姿态/角速度与传感器参数 | InitialState,SensorConfig,SensorFault；3,5,39,45 | L07,T03,T08 |
| R15 | 标书3.6 | 发动机/燃油/液压/电气/航电状态区分为观测 | SystemStimulus,State；25,132 | L07,T08 |
| R16 | 标书3.4 | 总线延迟/丢包/重复/损坏/断链/背景负载/电气故障 | BusFault,RawBus,Diagnostic,NegativeMutation；26,44,138 | L08,T02,T05,T06 |
| R17 | 标书3.6硬件表 | 4 CANFD、4 CAN、4汽车以太网 | PhysicalChannelConfig,RawBus,channels；13 CANFD报文定义及12总线端口 | L03,L04,T12,T13 |
| R18 | 标书3.6硬件表 | 4 RS232、8 RS422串口 | SerialWrite,IOStatus,PhysicalChannelConfig；27,134 | L03,T12,T13 |
| R19 | 标书3.6硬件表 | 8 AD、8 DA、16 TTL全通道索引/范围/方向/安全 | AnalogWrite,DigitalWrite,PhysicalChannelConfig,IOStatus；28,29,40,134 | L03,T12,T13 |
| R20 | 标书3.6/方案视频链路 | 视频编解码/资源/帧/PTS/触发/同步/标注 | VideoConfig,VideoControl,VideoFrameMetadata,VideoAnnotation,VIDEO codec；30,31,32,43,135 | L07,T11 |
| R21 | 标书3.6视频计算机 | 2同步RS422及2视频汽车以太接口 | PhysicalChannelConfig,VIDEO codec；CLK,ENABLE,VIDEO_ETH_0/1 | T12,T13 |
| R22 | 方案9.10/9.11 | 单正式入口/封闭字段/原子模型步应用 | BusinessInputMessage,Header,Ack,Status；1..45,130,131 | L04,L08,T01,T02 |
| R23 | 方案9.12 | E0/E1/E2/E3真实证据及请求关联 | Evidence,Ack,Diagnostic；130,138,140 | L09,T01,T03,T08,T11,T12 |
| R24 | 标书3.4/3.6 | 记录、查询、历史管理、资源上传 | RecordControl,RecordStatus,Query,ResourceChunk,ResourceAck,管理API全部25命令；34,35,36,137,141 | L06,T05,T10 |
| R25 | 方案10 | 正式3.3配置替换不改3.6代码/驱动/映射 | SessionOpen,Capabilities,release_baseline；五种部署变更白名单 | L10,T14 |
| R26 | 已批准方案范围边界 | 3.3资源池内部6席位/供电电阻等不属模拟器替代范围；3.4TSN扩展不擅改现有工具 | scope_exclusions；不替代原模块；接口总线测试、故障、原码记录仍覆盖 | T14 |

## 必选实现差距

| 模块 | 已确定定义 | 必须实现/验证 |
|---|---|---|
| INITIAL_STATE | InitialState / model_adapter.initialize_state | Initialization getters match all position/velocity/quaternion/rate fields at first step within 1e-9; airborne consistent with ground and model. |
| EXTENDED_ENVIRONMENT | EnvironmentExt / environment_adapter | Each nonzero field has actual consumer and E2 probe; gravity/forces/air-density impact E3, weather/illumination visible in video. |
| SYSTEM_STIMULUS | SystemStimulus / plant_subsystems_and_payload_adapter | All fields connected to subsystem equations and response probes; no fabricated observations. |
| HEX_MOTOR_FAULTS | FaultHex / generated_model_contract_and_plant | Six independent faults and clear tested; generated contract and getter include fields 5,6. |
| MISSION_CONTROLLER | MissionLoad / declared_controller_or_provided_GCS | All task/geometry/waypoint actions consumed by selected controller and independently observed; cannot return model APPLIED for forwarding only. |
| FAULT_SEMANTICS | FaultQuad / sensor_adapter_and_plant | True state and faulted sensor channels separately probed; initial simplistic model approximations replaced before acceptance. |
| PHYSICAL_IO | PhysicalChannelConfig / qualified_device_driver | Hardware loopback/calibration/safety/electrical isolation required; capability false until qualified. |
| VIDEO | VideoConfig / video_service_and_injection_device | Frame consume probe and real output captured, phase/events synchronized within configured threshold. |
| EVIDENCE_AND_FORMAL_RECEIVER | Evidence / common_formal_receiver | Per-message sequence/transaction/E0..E3 tests plus unchanged code hash replacement. |
| SENSOR_VALIDITY_AND_STALE | SensorFault / sensor_adapter | T08 proves UUT sees NO_FIX/invalid and stale sample timestamps, and actual failsafe response. |

## 完整性的判定

45类输入、14类反馈，三类资源、六工具链、97条模型输入/参数路径和56端口均有明确设计。GPS无效/IMU陈旧、六电机5/6失效、STEP、目标高度/速度/航向、受控非法值/缺字段/CRC/时序负例也已定义，不能只做前端拒绝而省略正式入口验证。

资源hash、随机nonce、会话ID、校准测量、运行身份是实际运行值，其类型、约束和取得规则已确定，不是待外部确认的字段。REQUIRED_IMPLEMENTATION指代码和消费者未实现，不能忽略其验收。正式3.3对标同一基线，替换时不得新增接收代码。
