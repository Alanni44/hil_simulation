# Linux开发待办与整体覆盖台账

建立日期：2026-10-03。依据：`2026-10-02-input-simulator-overall.md`的M0至M7共41条任务、已批准推进设计及冻结v0.3契约。本文件是唯一跨环境移交台账，不是第二份ICD。

## 使用规则

1. 共用代码只有一份；Windows是当前开发/测试宿主。不得新建Windows专用协议、服务、驱动替代品或模拟器专用模型入口。
2. 每个工作包收尾时在“阶段追加记录”末尾追加日期、已验证共用内容、共用未完事项、新增/关联Linux待办编号、依赖与验收命令/证据。已有记录不得删除覆盖；同一Linux事项复用编号，不重复登记。
3. Linux事项只有在实际Linux/Ubuntu RT/设备环境执行并留存证据后才能勾选；目标硬件、实际模型和真实3.3未就绪时保持未完成。共同代码在Linux复测是必要资格验证，不是另开发一套版本。
4. 阶段完成前执行`python -X utf8 -m unittest discover -s tests -p test_development_backlog.py -v`，核对41条计划任务全部有责任归属，Linux引用均存在。计划变更时同步更新矩阵；不能删除任务取得覆盖通过。
5. 全量覆盖指每项都有共用开发与目标验证责任，并不表示已实现或已验收。必须同时完成共用工作、Linux工作、物理/模型证据和外部真实3.3门禁，才能宣称整体完成。

Linux完成后在本文件追加`Linux完成证据：L-编号 -> 仓库内相对JSON路径`再勾选。该报告必须含`execution_host`以Linux开头、`status=LINUX_TARGET_VERIFIED`、`completed_linux_items`包含该编号及非空`verification`，并记录实际测试与环境，不允许引用Windows报告。守护测试允许后续有证据地关闭Linux事项，不永久禁止勾选。

## Linux待办

- [ ] **L-001** 目标Ubuntu RT环境盘点与隔离Python3.12部署：记录Git、内核、旧Python3.6、MATLAB R2018b、模型/许可证和旧启动路径；运行独立依赖安装、`pip check`及旧目标验收，禁止覆盖系统Python。
- [ ] **L-002** 共用ICD库Linux资格：运行`python -X utf8 scripts/test_icd_runtime.py`、黄金向量自检及静态QA；记录解释器/依赖/组件哈希，比较当前宿主结果。不得重新实现编解码。
- [ ] **L-003** 正式发布门禁与目标启动验证：共用发布规则先在后续共用代码实现；Linux验证NOT_RELEASED拒绝正式启动、组件缺失/错哈希失败、部署回退，不把开发模式当正式发布。
- [ ] **L-004** 真实模型映射与缺口修复：按97条绑定实施C/Simulink输入和参数、初始化端口、完整环境/系统消费者、传感失效/陈旧与真值分离、六电机5/6和固定翼故障、真实延迟/丢包；在实际目标留下E2/E3，未知字段拒绝。
- [ ] **L-005** SocketCAN/vcan与正式CANFD驱动：共用帧库接实际python-can后端，验证标准ID/FD/BRS/DLC、通道、时间戳及断链。vcan只计软件验证，实际仲裁/负载须设备验收。
- [ ] **L-006** can-utils与SavvyCAN保留分支：Linux检测/启动/停止、默认观察、发送授权、实际后端FD/BRS/时间戳及通道能力，不以UDP替代。
- [ ] **L-007** canplayer回放：使用共用过滤/重建结果，实际执行日志发送，验证新会话/相对时序/方向/停止清理，保留工具能力边界。
- [ ] **L-008** Ostinato/Scapy原分支与真实网卡：共用构包后验证实际工具发送、收发端点/VLAN/通道及交互；socket回环不是原分支资格或汽车以太网证据。
- [ ] **L-009** tcpreplay原分支：对批准PCAP实际发送并验证方向、时序、重建、停止；不能将TCP历史直接冒充UDP会话交互。
- [ ] **L-010** C核心生命周期、队列与安全证据：接真实步时钟/写入点，验证4096队列、不覆盖/追赶、单写者、角色/控制源、100ms控制超时、租约撤销、STOP/RESET/RESUME清理、安全值及实际反馈。共用调度规则属于W2后续，不作为Linux专属重复实现。
- [ ] **L-011** 跨机/设备时钟：真实ClockSync、RS422与模型步/UTC分域，测不确定度与单向延迟适用性；未达500us保持CLOCK_UNSYNC，不相减不同主机单调时钟。
- [ ] **L-012** 视频及实体I/O完整工作包：实际H26x解码/参数集/IDR、哈希/metadata/像素关联、注入探针与同步；串口921600/8N2、AD/DA/TTL驱动、校准、安全值/电气故障及56端口资格；微秒输出能力不足则拒绝。
- [ ] **L-013** Ubuntu RT性能：实际模型与并发负载验证1ms步/±10us、80ms系统周期/±1ms、抖动、吞吐、资源和长稳；不得用Windows计时或普通vcan替代。
- [ ] **L-014** Robot及目标验收：共用用例/API编排在Linux执行L01-L09/T01-T13，分别判定E1/E2/E3、业务/安全；保存原始TX/RX、唯一证据包和失败结果，不静默跳过必选项。
- [ ] **L-015** 目标不可变发布：冻结3.6、C核心、驱动/依赖/ICD/映射/模型/测试和白名单；验证systemd启动、哈希清单、手册和回退程序。
- [ ] **L-016** 真实3.3切换：对实际真实3.3做同版符合性，停模拟器/撤权/清队列，只改批准配置；实际执行L10/T14与全部同场景，核对受保护哈希，失败回退。外部真实3.3依赖不因Windows+Linux代码齐全而免除。
- [ ] **L-017** 同一接入服务Linux网络联调：四ETH接口、实际36100/36101/36102/36110角色、双向ACL/部署授权、会话与重传、异常和撤销清理；同一代码入口，不添加模拟器私有端口。

## 全量计划责任矩阵

共用栏是后续实现责任，标注W1不意味着完整M1已验收；Linux栏为开发/联调/目标验证责任。任务文字与整体计划保持逐项一致。

| 任务 | 整体计划原项 | 共用开发责任 | Linux移交 | 当前边界 |
|---|---|---|---|---|
| M0-01 | 记录Git状态、目标工具链、旧测试结果与既有启动路径；保留未提交用户变更。 | W1及各阶段基线 | L-001 | 当前宿主已记录；目标未验 |
| M0-02 | 确认独立Python 3.12运行时在目标系统的可部署性和隔离方式；不可部署时先调整并验证新服务运行方案，不覆盖系统Python或擅自升级RT系统。 | W1独立依赖 | L-001 | 目标未验 |
| M0-03 | 已在v0.3建立45类输入、14类反馈、模型绑定、三类资源、六工具链及标书/方案覆盖对照；运行验证结果仍由后续里程碑产生。 | 已有完整定义；W1-W4实现 | L-004,L-005,L-008,L-012,L-014 | 定义已覆盖；运行未全覆盖 |
| M0-04 | 已将本项目确定的共同ICD、结构测试数据及内部接口区分；CAN ID、端口、周期和编码由v0.3明确给出，不再作为外部未确认参数。 | 已有完整定义；W1运行库 | L-002,L-017 | 定义已完成 |
| M0-05 | 为后续里程碑写聚焦实施任务及可执行测试，采用先失败测试、再实现、再回归的顺序。 | 每阶段聚焦计划/TDD/本台账 | L-014 | 持续执行 |
| M1-01 | 实现v0.3定义加载、四组件实际哈希指纹、设计/正式发布状态，以及基线文件缺失或不匹配时的启动拒绝。 | W1哈希；共用发布门禁后续 | L-002,L-003 | 部分完成 |
| M1-02 | 按已提供消息实现编解码和合法性验证，覆盖布局、类型、范围、单位和适用校验。 | W1结构；W2业务接入 | L-002,L-004 | 结构已验；业务未全验 |
| M1-03 | 共用库已按现有独立黄金向量逐字节校核编码，不以同一编码器的往返测试代替外部符合性；真实3.3程序符合性仍未执行。 | W1黄金向量 | L-002,L-016 | 共用离线已验 |
| M1-04 | 确认参数到模型契约的映射，未知字段拒绝，不覆盖模型解算输出。 | W2映射契约与拒绝 | L-004 | 未完成 |
| M2-01 | 交付模拟器与3.6接入服务的独立启动入口，建立有界队列及失败清理。 | W2服务/发送器/队列 | L-010,L-017 | 入口已验；模型队列未完 |
| M2-02 | 第一条共用软件通路使用既定UDP编码和当前宿主回环部署端点，不创建Windows专用实现；仍使用同一正式解析/校验路径。CAN在Linux使用vcan作软件验证，不将普通CAN或UDP包装成已通过CANFD实物链路。 | W2同码UDP收发 | L-005,L-017 | UDP已验；CAN未验 |
| M2-03 | 贯通资源加载、发送、3.6标准接收、映射、C核心实际应用及规定反馈。 | W2标准接入；W3资源 | L-004,L-010 | 未闭环 |
| M2-04 | 复用既有输入写入点证据；不足时在实际写入处增加有界证据通路，由非实时线程编码落盘。 | W2证据收集边界 | L-004,L-010 | 未完成 |
| M2-05 | 验证合法输入、整组拒绝、未知字段和规定超时；每次运行都能追溯原始输入与实际应用。 | W1拒绝；W2/W3追踪 | L-004,L-010,L-014 | 部分完成 |
| M2-06 | 对排队、合并或被覆盖的输入记录实际结果；不能将尚未写入模型的已接收请求标记为已应用，消息保留策略须符合该消息的正式规则。 | W2队列/反馈真实阶段 | L-004,L-010 | 未完成 |
| M3-01 | 信号链：cantools、python-can与SocketCAN/vcan，按正式DBC及目标后端校验。 | W1编解码；W3工具封装 | L-005 | 驱动未完成 |
| M3-02 | CAN工具链与GUI链：受控调用can-utils与SavvyCAN；观察默认不取得发送控制权。 | W3封装/互斥 | L-006 | 未完成 |
| M3-03 | CAN回放链：检查日志格式、方向、通道及相对时序后调用canplayer。 | W3日志解析/重建 | L-007 | 未完成 |
| M3-04 | 以太网模拟链：保留Ostinato和Scapy，按消息验证正常构包及适用交互；不默认强制新建TCP客户端。 | W1构包；W3工具封装 | L-008 | 原工具未验 |
| M3-05 | PCAP回放链：批准预处理与方向筛选后调用tcpreplay；需要工具不具备的动态交互时拒绝或转已验证实现。 | W3PCAP预处理/能力拒绝 | L-009 | 未完成 |
| M3-06 | 建立独立反馈采集器、工具进程状态、运行关联、发送互斥与停止清理。 | W2反馈；W3工具编排 | L-006,L-007,L-008,L-009,L-010,L-017 | 未完成 |
| M4-01 | 场景支持校验、启动、等待、暂停、恢复、停止及条件适用的单步/重置；按应用或状态条件推进。 | W3场景状态机 | L-010 | 未完成 |
| M4-02 | 实现正常、边界、业务异常和通信异常用例，包含批准的重复、乱序、延迟、停止发送和非法值。 | W2-W4共用用例 | L-010,L-014 | 未完成 |
| M4-03 | 区分CAN日志、以太网PCAP和工程量历史；仅按正式规则更新线上序号、会话或校验，合法原码可直放。 | W3三类资源与回放 | L-007,L-009 | 未完成 |
| M4-04 | 跨链路时钟明确单调时间、仿真时间、设备时间及同步方式；未同步主机的单调时钟不能直接相减作为链路延迟。 | W2时钟规则；W3事件步 | L-011 | 未完成 |
| M4-05 | 复用或完善控制源互斥、超时安全、有限资源及磁盘门限；证明旧队列不在恢复后意外执行。 | W2互斥/队列；W3资源门限 | L-004,L-010,L-013 | 未完成 |
| M4-06 | 为视频注入与串口/AD/DA/IO建立独立能力清单、接口测试点和条件用例，不将网络工程量作为实体证据。 | W1视频封装；W2能力；W3/W4用例 | L-012 | 实体未完成 |
| M5-01 | Robot通过工具封装与3.6标准管理API编排运行，不直接绕过正式接入写模型。 | W3工具；W4API/Robot | L-014 | 未完成 |
| M5-02 | 自动运行L01至L09及对应T01至T13；逐项声明适用性和运行环境，不以跳过必选项取得通过。 | W4自动化/报告 | L-014 | 未完成 |
| M5-03 | 每个用例分别判定接收、实际应用、业务响应和安全结果；未定义模型参考值时不声称动力学正确。 | W2证据；W4分层断言 | L-004,L-010,L-014 | 未完成 |
| M5-04 | 保存环境/依赖/ICD/模型哈希、原始TX/RX、应用证据、断言、异常和唯一结果文件；证据缺失即失败。 | W2-W4证据包 | L-011,L-014,L-015 | 未完成 |
| M5-05 | 复用既有验收风格，新增独立接口验收入口，防止覆盖或误引用旧验收结果。 | 共用单一入口/阶段报告 | L-014 | 阶段离线入口已有 |
| M6-01 | 目标硬件就绪后验证驱动、接线、通道、正式物理链路及适用同步能力；驱动缺口在此阶段关闭，不留待替换。 | 共用能力门禁 | L-005,L-008,L-012 | 未完成 |
| M6-02 | 使用实际模型及规定并发负载验证周期、抖动、延迟、反馈、资源边界和稳定运行。 | 共用负载/断言 | L-004,L-011,L-013 | 未完成 |
| M6-03 | 完成独立视频与实体I/O工作包中的全部必选项目；相关项目未就绪则不能形成完整终验结论。 | 共用用例/条件拒绝 | L-012,L-014 | 未完成 |
| M6-04 | 锁定3.6接入服务、C核心、驱动、依赖、ICD、映射、模型契约及自动化测试；签署允许配置变更的白名单。 | 共用发布门禁/白名单 | L-003,L-015 | 未完成 |
| M6-05 | 形成不可变发布包、哈希清单、部署手册及回退程序。 | 共用发布构建/清单 | L-003,L-015 | 未完成 |
| M7-01 | 真实3.3先通过同版ICD符合性检查；未就绪时仅用独立发送实现检查接口透明性，不登记真实3.3验收通过。 | 共用符合性测试 | L-016 | 外部实际源未验 |
| M7-02 | 停止模拟器、撤销授权、清理队列并进入安全状态；只修改白名单配置后接入真实3.3。 | 共用配置/授权/停止 | L-010,L-016,L-017 | 未完成 |
| M7-03 | 对比受保护文件哈希，执行L10/T14及全部必选同场景用例。 | 共用哈希/回归入口 | L-016 | 未完成 |
| M7-04 | 任一必选规则失败、证据缺失、配置越界或受保护文件变化均拒绝替换验收；按既定流程回退。 | 共用替换门禁 | L-015,L-016 | 未完成 |

## 共用未完事项

W2后续：实际消费者接入契约、目标步/状态/角色/控制源门禁、4096模型队列、真实Status/ClockStatus、完整SessionClose/Cleanup、资源/视频关联、证据包与正式发布门禁。它们不是Windows专用内容，不得全部转为Linux重写。W3三类资源/原工具封装、W4 API/控制台/Robot均继续共用开发；Linux仅承担不可在当前宿主完成的后端及目标验证。

## 阶段追加记录

### 2026-10-03 W1收尾移交

- 共用已验：50条W1、4条接口汇总、34条选定既有静态回归；85黄金片、59消息/72业务传输、800片RAW；基线未改。证据`artifacts/icd_runtime/w1-validation.json`。
- 追加Linux：L-001、L-002；关联目标后续L-003至L-017。全部未执行，不能因结构编码通过省略模型/工具/实体工作。
- 共用未完：完整M1发布门禁与映射、W2-W4；完整M1/M2没有通过。

### 2026-10-03 W2.1收尾移交

- 共用已验：完整identity/角色/端点授权、固定租约/新心跳续租、跨链路序列与真实反馈缓存、双向ACL、实际UDP与独立接入/发送进程。标准36100/36101/36102回环、原码可靠重传、周期消息不重传旧值均有真实socket测试。
- 验证：54条协议库、38条网关/源、3条台账、4条接口汇总，以及34条选定既有静态回归通过。85黄金片与14源文件未变；静态QA10446/2427。证据`artifacts/icd_gateway/w2-validation.json`。
- 本阶段追加移交：L-017需要在Linux用同一接入/源进程验证实际四ETH接口、双向ACL与部署；L-001/L-002先完成独立环境及同码资格。L-004/L-010负责实际模型消费、步时钟、安全撤销和探针；L-005/L-006/L-007/L-008/L-009继续原六工具链后端，不能以本批socket替代。
- 共用未完：W2.2的状态/目标步/控制权、4096模型队列、完整生命周期/清理、真实Status/ClockSync、资源/video关联、完整E1原码/evidence包与发布门禁。W3资源/工具封装和W4 API/Robot按原计划继续，不全部推到Linux。
- 修复：不同grant交错分片SessionOpen以本地授权命名空间隔离，预算仍共享；反馈同号异值拒绝，源端64标识容量明确返回BUFFER_FULL。未新建线上字段、Windows版、私有模型入口或替代工具链。
- 门禁：无实际模型消费者，因此只RECEIVED后FAILED/TARGET_MISSING或UNSUPPORTED；Capabilities仅ID1、实体资格/探针/ready均为空或false。Linux17项全部未执行；完整W2/M1/M2、物理验证与真实3.3替换没有通过。

### 2026-10-03 W2.2收尾移交

- 共用已验：三模型97条根输入/参数绑定的结构一致性门禁，7..19全量消息映射与Flight/Actuator同根别名；首次接收时间/原始admission校验、整组不可变队列、全局4096容量、路径单写者与同一步互斥、1ms顺序步/ahead/最长运行门限、出队前100ms控制年龄复核、会话撤销/过期拒绝记录、清队列与关闭。10条映射、25条队列专项通过；测试元数据夹具不是实际模型，出队不是APPLIED。
- 本阶段追加Linux开发要求（复用L-004）：加载实际构建的hil_contract及导出ABI，修复六电机5/6声明和实际故障行为；逐一核对97个实际输入/参数写入点与范围/单位/维度，证明整组写入与读回，保留实际模型/生成符号/文件哈希。扩展环境、系统、初始化与传感消费者仍按原必选项实现，不能用根输入子集或结构通过代替。
- 本阶段追加Linux接入要求（复用L-010）：将同一公共队列接真实C模型1ms安全边界，使用一个会话/模型控制域，禁止独立队列或第二服务绕过4096容量与写者互斥；真实边界串行进行完整业务校验、入队/出队、原子写入、探针反馈。验证实时时钟、目标步开始前的完整入队、满队列拒绝、旧值不追赶、控制100ms安全置零/撤权/SAFETY、环境240ms恢复/停机、故障保持及STOP/RESET/RESUME清理。当前Python队列不在RT线程宣称±10us，适配采用原C写入点和有界非实时证据服务，旧Python3.6不直接导入新3.12库。
- 同码资格：L-001/L-002在隔离Python3.12运行单一测试入口、黄金自检和静态QA；L-017复测实际端点/授权与C服务联调。验收必须追加实际Linux报告，包含执行命令、环境/哈希、容量/时序/清理结果以及真实E2/E3；当前17项全部未执行，不新增Windows替代驱动或C模型版本。
- 共用未完：网络Receiver尚未启用本批队列；完整实际消费者契约/逐消息业务语义、RunConfigure/生命周期、ControlOwner授权与租约、冻结步服务更新、SessionClose/Cleanup、真实Status/ClockSync、扩展消费者/资源/视频、异步真实阶段缓存与完整原码证据包、正式发布门禁仍须后续共用包。queue.close是终止对象，不是RESET；业务复位不可重建活动注册表重置步历史。W3三类资源与六原工具封装、W4管理API/Robot继续共用开发。
- 复核修复：同一注册表整个生命周期只允许一个队列，关闭后也拒绝重建，从代码上阻止多队列容量/单写者绕过与步归0；注册表关闭同时关闭其队列。35条专项经只读复核通过，无重要新增问题。阶段证据位置`artifacts/icd_gateway/w2-2-validation.json`；完整W2/M1/M2、Linux/模型/实物/真实3.3替换均未通过，现网关能力仍仅ID1且无APPLIED/CONSUMED。
- 最终回归：同一测试入口134条通过（54协议、73网关/源、3台账、4汇总）；另34条选定静态回归通过。85黄金片/800 RAW片、静态QA10446/2427、原14文件逐字节汇总、依赖与编译检查通过。41项任务责任完整覆盖、17项Linux仍未执行；报告只标共用软件验证，不标整体完成。

### 2026-10-03 W2.3收尾移交

- 共用已实现：不可变实际ModelView输入、六类生命周期状态/目标步规则、PAUSED下1..1000个顺序1ms STEP决策、清队列/安全输出/撤权/新会话/恢复初始快照义务；ControlOwner区分STIMULUS请求者与实际CONTROLLER生产者，校验声明源/模型/通道能力，活动控制固定100ms，NONE仅撤权。RunConfigure与InitialState保留完整显式快照，校验三模型分支、全控制安全零、四元数、NED地形/airborne、静止多旋翼、固定翼显式速度及GPS失效一致性。23条专项通过；超大整数地形样本已以失败用例复现并修正为RESOURCE拒绝，不截断或补默认值。
- 本阶段追加Linux开发要求（复用L-010）：修改实际C生命周期，使START/PAUSE/RESUME/STOP/RESET严格符合共同状态机；现有RESET回RUNNING、接受RUNNING复位及旧ENDED状态不能作为CONFIGURED/STOPPED的别名。接入完整配置/复位快照，真实边界完成安全置零、撤权、清队列、RESET恢复与RESET/RESUME新会话；InitialState只能进入待复位输入，不直接改输出。实际边界必须重新读取ModelView并复核决策，不能沿用接收时状态。
- 本阶段追加Linux队列/控制要求（复用L-010）：现有pending_live及LifecycleRequest可替换单槽不能冒充4096逻辑队列；保留每条原请求及实际结果，不覆盖旧请求后给出成功。现有控制源选择缺PAUSED门禁、DEMO_MISSION超时豁免、超时未撤销源和边界比较均须按100ms共同规则修正；实际授权生产者、通道资格和租约计时由实际消费者实现，不使用ControlOwner发送者的STIMULUS角色代授CONTROLLER。legacy accepted/effective_sequence不是真实模型应用探针。
- 本阶段追加Linux初始化要求（复用L-004）：把完整初始输入与参数写入实际ABI，证明初始化端口与RESET时整组生效，不使用旧默认值覆盖用户显式输入；地形采样必须关联请求初始点、origin、资源哈希和实际解析结果，不能只提供一个无来源数值。真实资源、物理链路、内部控制器及模型资格未满足时拒绝，不能因结构合法或纯规则返回而标CONFIGURED/ready。真实探针与实际反馈保留E2/E3证据。
- 同码资格：L-002在Linux执行同一语义测试及完整公共入口；L-001隔离Python3.12，L-017负责标准接入与C后端联调。没有新增Windows版C核心、驱动、私有ICD字段或替换六条原工具链。17项Linux全部未执行，仍不得勾选。
- 共用未完：实际消费者服务契约及边界事务、ControlOwner实际授权/租约/安全效果、生命周期执行和RESET步历史协调、环境240ms恢复/停机及故障保持、完整SessionClose/Cleanup、真实Status/ClockSync、异步阶段缓存、扩展消费者/资源/video关联、原码证据包与正式发布门禁。W3三类资源/原六工具封装及W4 API/控制台/Robot仍属于共用后续责任，不能全部转为Linux重写。
- 阶段证据：artifacts/icd_gateway/w2-3-validation.json。规则输出只是决策与义务，不产生APPLIED/CONSUMED、Status或实际效果证明；网络能力仍仅ID1。41项整体任务保持责任覆盖，完整W2/M1/M2、实际模型/硬件/目标性能及真实3.3替换仍未验收。
- 最终回归：单一公共入口157条通过（54协议、96网关/源、3台账、4汇总），另34条选定既有静态回归通过；85黄金片/800 RAW片、静态QA10446/2427、依赖/编译和14源文件逐字节检查通过。本记录不覆盖或改写W1/W2.1/W2.2的历史结果。

### 2026-10-03 W2.4收尾移交

- 共用已实现：指定会话内部退休、其分片/原逻辑输入/写者清理、暂停或空闲时队列过期清理、不可变原拒绝记录、所有参与者无副作用时钟/容量预检、永久关闭注册表。维护记录累计保留直到drain，默认4096条原输入拒绝与8192个到期SID，满时删除前BUFFER_FULL不覆盖；独立64会话/4096输入shutdown记录在隐式UDP/context关闭后仍可取走。不重建队列、不重置模型步、不执行实际模型或发布E2。
- 本阶段追加Linux执行要求（复用L-004/L-010）：实际消费者必须按完整九项清理完成模型Fault及SensorFault、BusFault、安全执行器、控制撤权、模型输入/接收队列清空和最终会话关闭；暂停时也由真实安全服务边界执行，不等模型推进。37按目标步、38按服务边界，不得把SessionClose排成未来模型步。必须持续drain维护/关闭原请求记录，针对每条实际失败形成对应反馈与证据；不能只做本地会话删除就发APPLIED/CONSUMED或忽略满缓冲。
- 本阶段追加Linux设备/工具要求（复用L-006/L-007/L-008/L-009/L-012）：实际停止归属本运行的周期发送、原六工具发送者、回放与视频注入/解码，清理实体总线与授权故障板；安全DA0、TTL输入/低、电气故障复位均需实测。跨源停止由共同执行器/管理面协调，不用网关凭一个本地ID假装已关闭远端源，也不随意结束其他运行的工具进程。模型Fault显式清除与RESET恢复initial_inputs须分别验证，SensorFault恢复按合同的有效/冻结/陈旧规则证明真值未污染。
- 本阶段追加Linux反馈与权限要求（复用L-010/L-017）：实际完整清理结束后再封存最终37/38关联反馈与真实探针，验证会话失效后批准重传仍取得原终态而不重复执行；当前共同会话层未实现这一终态tombstone通路。源须新nonce，现有接收端仅5s缓存冲突检测，不是永久防重放/加密认证；部署凭据/写权限撤销需真实ACL/授权服务验证，旧SID永不复用/旧输入拒绝仍是共同不变量。
- 同码资格：L-002执行同一清理/退休与真实UDP测试；L-001保证隔离运行时，L-017联调实际网络。保留原C及工具/设备后端，17项Linux全部未执行，不另开发Windows驱动、假清理消费者或专用线上字段。
- 共用未完：实际消费者接入/整组执行、控制租约/安全效果、完整九项执行协调、清理后的可靠终态缓存、真实Status/ClockSync、资源/视频/扩展消费者、原TX/RX持久证据包及正式发布门禁。W3三类资源/原六工具封装、W4管理API/控制台/Robot继续共同开发；41项整体责任仍完整覆盖，完整W2/M1/M2及真实3.3替换仍未完成。
- 阶段报告：artifacts/icd_gateway/w2-4-validation.json。线上37/38仍缺消费者明确FAILED，Capabilities仍仅ID1，规则/本地退休不产生APPLIED/CONSUMED或实物安全证明。本记录只追加，不替换前阶段证据。
- 最终回归：187条公共入口测试通过（54协议、126网关/源、3台账、4汇总），其中27退休/清理专项及13实际UDP测试；另34条选定静态回归通过。85黄金片/800RAW、静态QA10446/2427、依赖/编译和原14源逐字节检查通过。只读复核发现的隐式维护原记录丢失、后置时钟拒绝先删资源两项已红绿修复并复核；完整九项执行与目标验收不在上述通过范围。

### 2026-10-03 W3.1资源存储基础移交（完整复核未完）

- 共用实现：实际34文件分块/原始整体SHA256、严格base64/长度/连续offset/final、唯一原块重试、活动上传会话归属与声明一致性；五种MODEL/VIDEO/TERRAIN/OBSTACLES/MISSION字节存储。地形/障碍物/任务按冻结Schema和本地矩阵长度/ID/执行索引校验，模型/视频仍为不具备ABI/codec资格的OPAQUE_BYTES。专用root/独占lock、私有暂存、原子目录发布、启动/resolve重新读取真实bytes与有限manifest、容量/磁盘余量/原请求/可drain中止记录均实现，不等同模型/业务应用。
- 本阶段追加Linux同码要求（L-002/L-017）：在隔离Python3.12用同一测试入口验证实际目标文件系统上的锁、符号链接/硬链接/目录替换拒绝、单一worker调用约束、跨进程权限隔离及无其他写者。默认32MiB/个、128MiB声明字节、8上传/128对象、8192块、64MiB自由磁盘余量、128中止预约/256MiB原请求存储属于部署门限；实际目标磁盘/内存容量需测量，不能将它们算作重组8MiB或总RSS保证。正常close释放lock；掉电/kill的旧lock、未知或未完成暂存必须按管理员授权的恢复/隔离程序处理，不能重启时自动删文件。实际fsync/原子目录rename/文件系统掉电持久性、权限失败、磁盘满/配额和进程故障需实际验证，当前host测试/故障注入不关闭此资格。
- 本阶段追加Linux模型/资源要求（L-004/L-010）：将实际已验证资源接入统一真实消费者，41/42须绑定对应种类/hash、当前Origin、实际目标步与STOPPED/PAUSED激活边界；terrain按north/east矩阵及实际位置采样、越界拒绝，障碍物/任务须完整路线/净空/地理/依赖校验。消费者读取时保留文件身份/hash和真实读取/应用探针，不能把一个Path、存储complete或DEFINED_JSON当CONSUMED/APPLIED/CONFIGURED。模型下载仍检查实际ABI/完整模型契约与停止状态；不得开发另一个Windows版加载器或模型。
- 本阶段追加Linux视频/性能要求（L-012/L-013）：视频opaque字节完成不代表H264/H265/RAW资格，需真实资源索引/帧字节/时间戳/hash、解码/实体注入及独立消费者测试。后台资源必须低于实时优先级，按20Mbit/s完整传输预算及真实CPU/磁盘/内存并发测试；存储同步API不得直接占用实时模型或入口循环。实际1ms/80ms及视频/控制并发、资源拒绝与安全恢复仍需目标报告。
- 共用未完而非Linux重写：独立有界后台服务、完整负载预算/发送互斥、标准34/141接入与SID/txn/hash关联、原序号阶段缓存、10000ms最终commit等待、过期/撤权/37/38对上传的取消协调、管理25命令的资源上传边界、正式激活/内容语义、资源持久证据/恢复入口。PROTOCOL/SCENARIO/HISTORY三类输入源、六条原工具链、场景/历史和W4 API/控制台/Robot继续原计划。当前Receiver没有安装本库消费者，网络34仍明确FAILED、能力仅ID1，无应用/实体成功。
- 复核状态：独立只读复核发现并复现了暂存同名目录被递归删除问题；该问题已用RED/GREEN收紧到只清理拥有的普通文件。后续独立复核因调用额度中断，完整复核仍待执行，不能记为全部通过。主执行者另以失败测试修复硬链接写入影响外部文件、创建失败留下活动槽、发布metadata遗漏磁盘余量；未修改冻结ICD、原C/六工具或建立平台分支。
- 阶段证据：artifacts/icd_gateway/w3-1-validation.json；只标资源存储基础的软件验证/复核待完成，不标完整W3/M2/M4/目标资格。41项责任仍完整覆盖，17项Linux均未执行。本记录追加保留全部历史。
- 最终回归：232条共用入口通过（54协议、171网关/源，其中44资源存储与14实际UDP、3台账、4汇总），另34条选定静态回归通过；85黄金片/800RAW、静态QA10446/2427、依赖/编译、原14源逐字节检查均通过。合法整数JSON的1.0表示导致文件offset变float也已失败复现并按Schema证明的整数值修复，不改字段/范围或静默补值。完整独立复核仍未完成，不以这批测试代替复核或任何Linux/模型/实体门禁。

### 2026-10-03 W3.2标准后台资源服务移交

- 共用实现：实际单一worker拥有文件Store，入口/模型线程不做文件I/O；标准34按原ACL/角色/模型/SID/序号入队，RECEIVED原前缀加真实141，关联SID/transaction/hash与进度，重复不重复写入。64任务/结果、4MiB原请求、64等待pin及64接收结果记录均有界，满时保留原记录/不淘汰；末块pin最多原接收+10000ms，非末块1000ms，完成再保留5s。空闲UDP发送实际后台结果，源逐实际UDP片按20Mbit/s完整IPv4/Ethernet开销节流，最多3次原码重传后仅等待最终提交期限。不隐式续会话或伪造sender_step，不修改任何冻结字段和100ms重组期限。显式安装worker能力[1,34]，默认CLI仍ID1；所有应用/模型/视频/替换ready未通过。
- 本阶段追加Linux同码要求（L-002/L-017）：用同一ResourceWorker/Receiver/UDPSource运行大于64KiB的真实上传及64结果/pin满、原重试/关联错hash/错事务/错SID、反向ACL、闲置反馈、主动撤权、会话到期、取消途中写入和close超时/重试。必须持续排空维护、ResourceRecord、存储中止/unfinished和shutdown记录并形成原码证据；不以结果已存缓存当实际网络已送达。独占存储所有者与原标准接入必须仍是一个会话/模型域，不能另起Linux接收版本或第二worker绕过容量。
- 本阶段追加Linux故障恢复要求（L-002/L-017）：目标文件系统执行真实磁盘满/配额、权限/锁、fsync/目录发布、掉电/kill及I/O阻塞；验证中止drain超时可重取、同hash外部过期请求不清其他拥有者、不杀服务。清理失败的原已有中止和unfinished请求必须分别保留，未知目录/文件及lock不自动删除；按管理员批准恢复流程执行实际清理/核验后才登记成功。本批有共同不可变恢复记录，但管理员恢复入口与持久原TX/RX包尚未完成，不能把后者全部转为Linux重写。正常文件完成仍不是掉电持久性资格。
- 本阶段追加Linux调度/负载要求（L-013/L-017）：实际设置和验证资源线程/进程低于C模型及实时链路优先级，核算部署实际VLAN/隧道开销及多源/链路总带宽；20Mbit/s按真实发送时间和线上字节测量，不能以本机sleep/库预约值代替。上传及内容校验/磁盘I/O与1ms模型、80ms通信、视频和控制并发压测，证明100ms重组、1s写入开始/非末块完成、10s最终提交、满缓冲拒绝、安全撤权和长期稳定；调度失约按冻结期限失败，不扩大ICD或做Windows定时替代。
- 本阶段追加Linux实际激活要求（L-004/L-010/L-012）：同一有界后台所有者把已验证资源交真实模型/地形/障碍物/任务/视频消费者；41/42按原Origin、种类/hash、STOPPED/PAUSED及目标步执行实际读取/应用，模型必须完整ABI契约、视频必须真实解码/注入资格。当前MODEL/VIDEO仍opaque bytes，TERRAIN/OBSTACLES/MISSION本地结构不是全部业务资格；141 complete只能证明存储，不产生模型APPLIED/CONSUMED/E2/E3。37/38完整九项源/模型/工具/设备安全清理仍按原要求实现，不用本地worker取消替代。
- 共用未完：25管理命令资源/配置边界、三类PROTOCOL/SCENARIO/HISTORY执行器、原六工具封装/发送互斥、显式心跳/多消息执行调度、完整消费者/资源语义/激活、Status/ClockSync、完整E1原码与持久证据/恢复入口、Robot/控制台及正式发布/替换门禁。Windows+Linux责任仍逐项覆盖原41条，没有省略任务或新增平台分支；17项Linux均未执行。
- 复核：W3.1存储及W3.2服务完整独立只读复核已完成。复核发现的同hash外部过期任务导致worker死亡/清理拥有者上传已以RED/GREEN修复；另修复中止drain超时不可恢复、非末块超时暂存残留、清理失败丢已有中止/unfinished原请求、已删字节仍报告为stored、错误反馈Python异常。无遗留重要发现，仍不代表目标性能/设备或正式发布通过。阶段报告位置artifacts/icd_gateway/w3-2-validation.json；本追加不重写W3.1报告与历史复核中断事实。
- 契约收紧复核追加（L-004/L-010）：MODEL在实际停止并验证完整模型契约前不能下载；TERRAIN提交必须有真实STOPPED/PAUSED依据，不能把SessionOpen、step0或专用未激活暂存当作门禁证据。当前worker/标准UDP对这两种资源在claim、预算、入队及I/O前TARGET_MISSING；76,800字节实际UDP验证采用VIDEO后台字节预载，不代表解码。Linux真实消费者接入时逐块/最终提交复核当前状态/身份/契约和取消，不能只用接收时快照，失败不写、不假发complete。MODEL/TERRAIN存储基础仍可复用，但线上受限种类尚未开通。末次独立复核指出的这条缺少状态前提已失败复现并修正；五种基础资源不宣称五种标准提交已全部就绪。
- 发送器失败语义追加：独立CLI收到标准141的任何非OK资源错误以BUSINESS_FAILED/exit1结束，成功字节存储仅NETWORK_EXCHANGE_COMPLETE且模型/硬件/替换未执行；真实socket与独立进程测试分别覆盖错hash和OK，不捏造存储消费者或E2。源码未新增Linux/Windows或模拟器/真实源业务分支。
- 最终回归：280条共用入口通过（54协议、219网关/源、3台账、4接口汇总），其中92资源相关测试包含44存储、15反馈、20worker/预算、9实际资源UDP、4源/CLI；标准UDP网关共23条。另34条选定静态回归、85黄金片/800RAW、静态QA10446/2427、依赖/编译、原14源逐字节检查通过。末次独立复核实际运行20worker与9资源UDP并确认缺模型状态门禁已拒绝；阶段源码哈希和未完范围在w3-2-validation.json。41条任务责任仍完整覆盖，17条Linux全未执行，完整开发目标/目标验收不因此关闭。

### 2026-10-03 W3.3三类输入审核基础移交

- 共用实现：复用冻结完整SourceInputs、三类来源及全部十种Event/45种Stimulus定义；结构缺失/未知字段拒绝，Session/Header和反馈不成为Stimulus。实际load保留四组件原文件哈希，PROTOCOL核对整体/Schema/目录指纹和原ICD_JSON/DBC字节，resource_id唯一、实际size/hash/UTF8及声明消息验证。审核使用显式ID到bytes映射；CLI用管理员显式路径，不按file_name拼路径。原输入和历史记录形成不可变规范快照，结果固定SOURCE_INPUTS_AUDITED_NOT_EXECUTABLE、execution_ready=false，没有模型/工具启动或发布VALID。
- SCENARIO基础只覆盖身份唯一性、Stimulus声明/模型资格、FAULT五种消息、非数值断言比较/容差、周期唯一start及同工具先start后stop、REPLAY引用及自身策略；不是完整场景语义通过。HISTORY核对解码基线、流ID/消息方向、重写字段唯一、ONLINE完整性和区间次序；ENGINEERING_JSONL逐行严格UTF8/封闭对象/uint64/非递减/45输入，实际计数/ID/唯一流归属、epoch加offset溢出及来源/事件回放区间均核验。工程量仅REENCODE可作本批审核，不能冒充原捕获header的RAW_VALIDATED/SESSION_REBUILD证明。其他历史只审资源字节、history_decoded=false、complete_capture=null并列出parser pending；离线不完整历史仍不能形成完整链路通过结论。
- 本阶段追加Linux同码与资源要求（L-001/L-002/L-017）：隔离Python3.12运行`python -X utf8 scripts/test_icd_runtime.py`和`python -m input_simulator.source_inputs`同一离线入口，提供实际完整source_inputs文件和管理员resource_id到路径映射。核对实际目标UTF8/路径/权限/配额及原Schema/目录/DBC组件哈希；每资源64MiB、总128MiB、输入16MiB、历史100000行/每行131072字节是本批部署门限，不是RT/总RSS保证。执行时必须使用审核原字节或重新读取核验；不能拿审核报告为已经变化的文件放行。资源审核不代表模型上传/正式ResourceChunk资源激活；不新增Linux接入实现或Windows专用工具替代。
- 本阶段追加Linux原工具与捕获资格（L-005/L-006/L-007/L-008/L-009）：保留实际cantools/python-can/SocketCAN、can-utils、SavvyCAN、canplayer、Ostinato/Scapy、tcpreplay六分支。共用后续解析器产出的FD/BRS/通道/消息/方向/时钟与原实际工具捕获/发送结果对照，CAN/以太网linktype不混用，TCP不冒充UDP会话；原文件hash、原/重建字节hash、端点与授权必须有目标证据。当前未执行这些工具，exact DBC字节核验不等于cantools解析或原分支通过。
- 本阶段追加Linux模型步/回放执行要求（L-010/L-011/L-013）：共用后续执行器接实际C安全边界/模型步和真实探针，验证(at_step,priority,event_id)顺序、跨工具同实际写目标碰撞拒绝、全部波形采样/极值、周期停止、WAIT不冻结模型、超时安全与九项结束清理。三种回放模式逐轮真实新会话/RESET/清队列；RAW当前有效SID/序列/目标/端点/CRC，SESSION_REBUILD只改准许六类元数据而payload不变。捕获单调时间、模型步、UTC不得混算，uncertainty及目标并发性能实测；本批工程量离线审核没有模型步或执行授权。
- 本阶段追加Linux验收证据要求（L-014/L-016）：Robot使用共用管理面/执行器，把资源审核、真实E1、实际E2/E3和未执行项分开判定。负例T02/T05/T06授权必须来自实际已启用测试配置，原/变异字节及must_not_apply探针由后续共用负例执行器产生，不由本批Schema通过授予发送权。实际真实3.3仍走同版ICD/同接收规则，不以本批审核或设备缺失关闭替换门禁。
- 共用未完而非Linux重写：真实DBC/cantools与ARXML字段等价导入、CAN_LOG/PCAP/PCAPNG解析/链路分流、场景全部执行语义（写目标冲突/波形/周期/WAIT/探针断言/负例授权与变异/清理）、历史三模式重建与执行、六工具封装/互斥/停止反馈、25管理API/控制台/Robot、完整消费者/资源激活/ClockSync/持久原码证据/发布门禁。基础审核恒不可执行，不缩减原W3/W4和整体41项任务；17项Linux全部未执行。
- 专项与复核：主执行者和独立只读复核分别运行29输入审核/真实文件CLI及10契约测试通过；复核发现十进制字符串尾随换行绕过uint64检查，已先失败复现，再修正共用严格ASCII全文匹配并独立复测通过。冻结14源/线上字段/原C及六工具均未改，未建立平台分支。最新完整回归和阶段源码哈希单独记录在artifacts/icd_gateway/w3-3-validation.json，不重写前阶段报告或历史。
- 最终回归：最新同一公共入口319条通过（64协议、248网关/源、3台账、4接口汇总），另34条既有选定静态回归、85黄金片/800RAW、依赖/编译检查通过；原14源逐字节一致、663引用解析、41任务责任与17门禁证据守护通过。未重新运行会写回冻结QA文件的生成脚本，历史QA结果不算本批新测试；阶段报告含实际命令/计数/源码哈希。完整W3/M3/M4、17 Linux及实际模型/实体/真实3.3仍未验收。

### 2026-10-03 W3.4真实协议解析与原CAN帧库移交

- 共用实现：新增`input_simulator/protocol.py`，实际cantools40.7.1 strict解析冻结DBC，并对13种CANFD帧全部650信号核对名称/ID/64字节/FD/标准ID/周期、位起点/宽度/端序/unsigned/identity转换/满范围及无额外信号语义。期望布局来自冻结目录，不自行解析DBC文本；ICD_JSON实际loads及原组件pin、Schema原load保持。结果为不可变tuple/frozen描述，资源ID到实际bytes显式供给；未知资源格式明确pending，全部资源未解析时禁止帧codec使用，parse失败清除旧资格。统一三源审核保存实际描述，仍恒SOURCE_INPUTS_AUDITED_NOT_EXECUTABLE、execution_ready=false。
- ARXML支持边界：只接本批严格AUTOSAR R4基线帧导入profile，必须同时提供冻结ICD_JSON/DBC，不产生第二业务基线。安全XML拒绝DTD/实体/外部解析；原XML核对整数ms的精确周期、identity系数/满unsigned闭区间、单一64字节PDU/零起点，拒绝更新位、逆向转换/额外单位；实际cantools解析结果再逐帧逐信号等价核验。不宣称任意复杂AUTOSAR或完整XSD通过。每协议资源4MiB/合计16MiB、数值文本64字符为新增导入部署边界；并非目标RSS或RT保证。
- 原帧链路保持：正式WireCodec先校验完整业务/CRC/分片/版本/方向/FD+BRS/标准ID/非remote/零padding，再与cantools真实decode/encode逐字节对照。20个原CAN黄金片、全部13消息包含反馈与多分片均对照；cantools不能替代正式接收、会话授权/队列或模型映射。解析库没有启动python-can总线或任何工具，不产生APPLIED/CONSUMED/E2/E3，也没有改原C、六工具分支、冻结14源或线上字段。
- 本阶段追加Linux隔离与同码要求（L-001/L-002）：独立Python3.12按同一`requirements-icd.txt`安装，包括cantools40.7.1/defusedxml0.7.1及锁定传递依赖；禁止升级旧HIL或系统Python。运行同一`python -X utf8 scripts/test_icd_runtime.py`、`python -m input_simulator.source_inputs`与codec自检，记录实际版本/组件哈希/资源内容和负例；不能导入静态QA vendor或重做Linux解析器。实际供应的ARXML不属支持profile时明确拒绝/补共同验证，不静默降低等价要求或把它记作已解析。
- 本阶段追加Linux原CAN工具与链路要求（L-005/L-006/L-007/L-017）：以同一冻结frame bytes接真实python-can/SocketCAN或已资格SDK，验证标准11位ID、实际FD/BRS/64字节DLC、通道、时间戳/方向/CRC/分片与捕获。can-utils/SavvyCAN保留默认观察及授权发送边界，canplayer保留严格RAW或上游重编码通路；解析描述不是工具能力/实际发送授权。vcan软件通过不能关闭实体仲裁、真实负载或硬件门禁；Ostinato/Scapy/tcpreplay仍按L-008/L-009原责任完整保留，不以本批CAN库替代。
- 本阶段追加Linux调度与证据要求（L-013/L-014）：DBC/ARXML加载、hash/XML及转换核验只在后台/配置阶段执行，不占模型实时边界；量测同码原CAN工具与1ms模型/80ms通信及并发视频/资源负载，记录CPU/RSS/吞吐/抖动/停止失败。Robot使用后续共同API/执行器区分协议导入、实际E1和真实E2/E3，保持真实原TX/RX与拒绝证据；本机黄金字节相等不算目标性能或设备安全通过。
- 共用未完而非Linux重写：CAN_LOG/PCAP/PCAPNG实际解析/方向/时钟，完整场景语义与执行器（写目标冲突/波形/周期/WAIT/探针断言/授权负例/清理），历史三模式会话重建/RESET/清队列/执行，六工具包装/互斥/停止反馈，25命令API/控制台/Robot，完整消费者/资源激活/ClockSync/持久原码与发布门禁继续原范围。支持的协议解析完成不勾选完整W3/M3/M4；41任务责任全部保持、17 Linux全未执行，真实3.3仍需原替换验收。
- 独立只读复核：发现ARXML浮点舍入抹去系数/范围漂移及解析库忽略PDU偏移/长度/更新位两项P2，均先RED实际复现再增加原XML精确校验；独立17协议/32三源与CLI测试通过，原五探针经解析器及审核入口均RESOURCE，失败后encode均STATE。没有遗留重要scoped发现；任意复杂ARXML/完整XSD和真实链路未验证。阶段新证据只存`artifacts/icd_gateway/w3-4-validation.json`，不覆盖历史报告。
- 最终回归：最新同一公共入口339条通过（64协议、268网关/源、3台账、4接口汇总），本批新增20条（17协议解析、3审核集成）；另34条选定既有静态回归、85黄金片/800RAW、依赖/编译检查通过。原14源逐字节一致、663引用解析及41任务/17门禁责任守护通过；未运行写回冻结源的QA生成脚本，历史QA不计本批。阶段报告记录实际命令/版本/源码hash，完整目标保持未完成。

### 2026-10-03 W3.5真实捕获容器与传输解析移交

- 共用实现：原python-can4.6.1 CanutilsLogReader解析candump -L普通CAN/CANFD，原Scapy2.7.0 reader与packet层解析PCAP四种endian/micro-nano、PCAPNG SHB/IDB/EPB/ISB及Ethernet单VLAN/IPv4 UDP/TCP、SocketCAN。前置封装检查修复原库EOF静默忽略、跨section接口复用及遗漏tsoffset/丢包统计的风险；保留原字节/hash、独立section/interface时钟域、整数ticks/有理数分辨率、精确uint64 ns、方向元数据、端点及CAN标志。捕获方向INBOUND/OUTBOUND不自动等同TO_36/FROM_36；TCP明确analysis-only。结果不可变，实际截断/丢包与自声明不完整对history及scenario内全部ONLINE回放拒绝，OFFLINE只分析。丢包统计仅是可观察下界，不声称全部丢包可证明。
- 支持与容量边界：默认捕获64MiB/100000packet、CAN行512字节；PCAPNG最多100section、每section100interface、200000block、每block1024option/65536option字节，防止metadata-only与Scapy选项尾slice放大。部署容量不是RT或RSS达标证明。未知block/linktype/option、无timestamp SPB、IPv6/嵌套VLAN/IP分片、非整数ns/溢出、非法CAN RTR/error/FD组合、坏checksum/长度明确失败；合法classic CAN len8_dlc扩展明确UNSUPPORTED，不静默删去。后续遇到必选真实捕获的未支持格式，应补同一共用解析器与测试，不能记工具通过、另写Linux解析器或降低ICD。
- 本阶段追加Linux同码与原工具捕获要求（L-001/L-002/L-005/L-006/L-007/L-008/L-009/L-017）：独立Python3.12按同一requirements安装并复测实际文件CLI及公共入口，保持旧HIL Python/C/六工具不变。用真实python-can/SocketCAN、can-utils/SavvyCAN/canplayer、Ostinato/Scapy/tcpreplay各原分支采集CAN与以太网文件，逐一核对linktype、ID/FD/BRS/ESI/RTR/error/DLC、接口/端点、时间戳分辨率/偏移/方向、PCAPNG多section及实际drop/truncation证据。Windows当前无libpcap provider，离线reader通过不等于在线网卡能力；Linux补实际provider/权限/驱动/抓包和原工具版本证据。软件vcan/回环与正式实体链路分别验收，禁止用解析成功冒充工具发送或真实链路通过。
- 本阶段追加Linux历史与性能资格（L-011/L-013/L-014）：共用后续HistoryDecoder/执行器与实际时钟源对照，明确CAPTURE_MONOTONIC/MODEL_STEP/UTC、epoch/uncertainty、各接口与业务流的显式关联，验证方向/通道/正式完整帧重组及模型门禁，禁止以文件名/RxTx或人工声明代替观察证据。实际RAW发送仍须当前SID/序列/目标/端点/CRC，REENCODE及SESSION_REBUILD仍须新会话/RESET/清队列及限定改写/hash，不能由本批capture对象授权。真实负载测试记录捕获解析CPU/RSS、配置期加载与RT隔离、丢包/时戳/抖动；Robot区分原文件解析、真实E1、实际E2/E3和未执行项。
- 共用未完而非Linux重写：捕获到HistoryStream的显式关联、业务方向与时钟资格、完整标准逻辑帧重组/45输入及14反馈解码、三回放模式执行、场景波形/周期/WAIT/断言/授权负例/清理、六工具包装/互斥/停止反馈、25命令API/控制台/Robot、完整消费者/资源激活/ClockSync/持久原码证据及发布门禁。审核恒SOURCE_INPUTS_AUDITED_NOT_EXECUTABLE、history_decoded=false、execution_ready=false；complete_capture未知为null，不完整为false，从不以本批container-only结果声明true。41任务责任全部保留、17 Linux全部未执行；完整W3/M3/M4、实体/实际模型及真实3.3替换尚未验收。
- 独立只读复核：四项实际问题均先RED复现再GREEN修正，分别为option storm/metadata-only容量绕过、scenario ONLINE实际丢包截断绕过、CAN raw RTR/error/FD矛盾；合法len8_dlc扩展改为明确UNSUPPORTED。独立24捕获/37审核与CLI全部通过；20000section/200000comment/200000statistics-block原探针均CAPACITY、CAN矛盾及scenario ONLINE实际loss均RESOURCE。未发现剩余重要scoped问题，无endofopt的合法block EOF仍正常解析，没有增加伪发送/执行资格。
- 最终回归：最新公共入口368条通过（64协议、297网关/源与捕获、3台账、4接口汇总），本阶段新增29条；另34条选定既有静态、85黄金片/800RAW、依赖/编译与冻结14源/663引用核验通过。阶段报告`artifacts/icd_gateway/w3-5-validation.json`记录实际命令、测试数、源码hash/版本和未完范围；未重新运行写回冻结源的QA生成脚本、未覆盖历史报告，不以本机测试时长宣称目标性能达标。

### 2026-10-03 W3.6完整业务捕获离线解码移交

- 共用实现：`input_simulator/history.py`以原CaptureParser读取并核对实际资源hash/大小，显式本地CaptureBinding关联domain/interface、冻结channel、HistoryStream和clock_id；本地绑定不是SourceInputs/线上报文字段，没有修改冻结ICD或原C/六工具。原WireCodec及Reassembler解析59业务消息/13 CANFD消息（45输入/14反馈），核对标准ID/FD+BRS/64字节/CRC/版本/分片、方向、ETH双向端点端口/无VLAN和model，逐stream检查实际逻辑计数/message_ids。每域串行重组保持原64slot/8MiB预算，拒绝残组/超时/冲突，不跨domain拼片；完整重复传输保留但不授予原session或fresh序列资格。结果保留原片索引、首次/完成offset、原message/stimulus的不可变bytes、payload hash及长度前缀原包hash，输出保留首次packet index文件顺序，不按时间重排。
- 辅助与时钟边界：普通CAN/辅助CANFD/ETH36150只转换为原RawBus44闭合Stimulus，不虚构原会话header；CAN辅助必须有显式capture point方向与实际RxTx匹配，未知方向/extended/RTR/error/非法ID或DLC拒绝。FROM_36不产生Stimulus。UTC/CAPTURE_MONOTONIC只按显式epoch作精确整数相对时间，逐domain拒绝回拨；同clock_id必须同clock/epoch，独立clock_id没有共同时间依据时拒绝窗口混算。MODEL_STEP要求明确时间域及首次片offset=target_step*1ms，不拿普通秒时戳猜模型时间。clock_id/uncertainty仍是声明，不是实际测量资格；clock_measured/execution_ready恒false。三模式正式包可离线解码但未执行/授权；辅助仅REENCODE。truncated片沿无bindings的OFFLINE容器入口分析，不能声称完整logical decode；零可见loss时complete_capture仍null，不完整为false。
- 本阶段追加Linux绑定与捕获资格（L-001/L-002/L-005/L-006/L-007/L-008/L-009/L-011/L-017）：使用同一共用Decoder/审核CLI，逐原六工具分支对照实际文件、接口/正式通道、source/receiver双向端点、原FD/BRS及真实捕获point方向。显式绑定的stream/domain/channel/clock来源必须有目标配置、原文件hash与实际原工具证据，不从文件名/网卡RxTx猜业务方向；对未带方向的辅助CAN明确拒绝而不是人工补成功。绑定配置hash纳入后续Robot/证据包。当前Decoder只支持冻结部署初值端点；实际白名单端点改变须扩展同一共同部署配置/测试，不修改wire/接收逻辑或另写Linux/Windows解码器。实体物理链路与软件vcan/回环分别验证。
- 本阶段追加Linux时钟与回放执行要求（L-010/L-011/L-013/L-014）：以实际时钟源、模型步/ClockSync测量证实epoch/clock_id与uncertainty，跨接口合并文件保留原顺序并逐域检查，不用全局排序删除问题或抹掉回拨。时钟未同步不得据解码计算跨机单向延迟/声称1ms同步。后续三模式执行器接原工具与真实C边界，独立核对RAW现SID/序列/target_step/白名单端点/CRC，REENCODE/SESSION_REBUILD每轮真实新会话/RESET/清队列及准许改写/payload不变/hash；本批original Header只是捕获证据，不是发送许可。实际CPU/RSS/吞吐与配置期加载/RT隔离需目标测量；decoder离线时间不作为±10us或完整周期通过。
- 共用未完而非Linux重写：三回放执行器/采样调度/实际恢复/会话新鲜度与反馈、显式TCP业务提取、HIV1/视频历史完整帧与metadata关联、完整场景语义与执行器、六工具封装/互斥/停止反馈、25命令API/控制台/Robot、完整消费者/资源激活/ClockSync/持久原码和发布门禁继续原责任。本包只是实际完整业务离线解码，不标完整HISTORY/W3/M3/M4或整体完成；41任务责任保留、17 Linux全部未执行，实际模型/实体/真实3.3替换仍未验收。
- 专项与只读复核：主执行者23解码及39审核/真实文件CLI通过；独立同数测试与跨接口交错probe通过。复核发现跨domain文件交错被全局时戳门禁误判回拨的P2，已先RED复现再改逐domain previous，保留offsets[100,0]/indices[(0,),(1,)]、execution_ready=false，域内真实回拨仍拒绝。没有剩余重要scoped发现；新证据存`artifacts/icd_gateway/w3-6-validation.json`，不覆盖历史记录。
- 最终回归：复核修正后重新完整运行公共入口393条通过（64协议、322网关/三源捕获历史、3台账、4接口汇总），本阶段新增25条；另34选定静态、59业务/72完成/85黄金片/800RAW、pip/编译和14逐字节源/663引用通过。最终阶段源码hash与命令记录于w3-6-validation.json；此前修正前392条运行不冒充最终393条证据。没有修改冻结源、原工具/C或线上字段，17 Linux仍全部未执行，完整目标仍active。

### 2026-10-04 W3.7三模式逐包准备核心移交

- 共用实现：`replay.py`先由真实HistoryDecoder校验原CAN_LOG/PCAP/PCAPNG资源与显式关联，再处理单轮完整TO_36组，FROM_36保留为反馈不注入。RAW_VALIDATED保留原包和业务原码且拒绝header/端点改写；REENCODE由闭合Stimulus和原WireCodec生成；SESSION_REBUILD用公共WireCodec.rewrite校验原包后仅改标准session/sequence/target_step/transaction和CRC，逐片保留业务字节/索引/填充/重复片及文件顺序。实际改动逐项对照六种rewrite_fields，Ethernet使用原Scapy重算长度/checksum；配置端点禁止未指定/广播/多播。Header只是本地分配，不是授予；SID排除整个捕获SID，每轮一个SID，同请求重传保留同Header与payload hash，非零原事务一对一映射不分裂/合并。
- 证据与边界：每包保留原索引、精确Fraction时间、原/重建业务帧hash、原捕获包hash和存在时的完整重建捕获包hash；整个原文件hash由Decoder提供。重建CAN尚未导出完整日志行，对应capture_bytes/hash为null，不以CANFrame/hash冒充完整CAN_LOG/重建文件。原辅助数据hash和正式RawBus44 payload hash分开记录；RAW/SESSION保留signed-zero原字节，REENCODE按工程值编码。切断逻辑组拒绝FRAGMENT，初始窗口不是动态seek，当前没有游标/seek API。单轮默认100000包/64MiB计费输出，不展开10000repeat；这些不是总RSS/RT保证。
- 本阶段追加Linux原工具要求（L-001/L-002/L-005/L-006/L-007/L-008/L-009/L-011/L-017）：用同一核心核对每条原工具分支实际原码/重建码、真实通道/端点/CRC/payload hash；CANFD原FD/BRS/ESI与驱动行为保留独立原捕获证据，不把应用CANFrame当物理控制器资格。canplayer/tcpreplay只发送正式执行器许可的文件，不能猜新SID/target/事务；完整CAN_LOG/PCAP导出及原工具启动/互斥/停止回执需共用实现与真实Linux验证，禁止Windows克隆工具或强制外置汇聚器。
- 本阶段追加Linux会话/恢复/时钟要求（L-010/L-011/L-013/L-014）：真实标准SessionGranted/角色/白名单与全局取号服务必须在发送前证明RAW当前SID未过期、序号新鲜、target有效，不能从捕获/本地Header自签授权。REENCODE/SESSION每轮真实新会话、RESET恢复initial_inputs（含故障/传感/控制）、清队列并核对旧会话退休/资源取消；repeat_gap_steps由真实模型步推进。实际ClockSync、不确定度、片/组期限、ONLINE1X、控制超时/迟到与跨机同步均测量；离线Fraction/Windows测试不是1ms/80ms或±10us证据。业务payload内sender_step/状态/hash不改，若不满足真实语义就拒绝，不扩展SESSION允许改写字段。
- 共用未完而非Linux重写：完整三模式执行器/授权/模型步调度/反馈/取消/清理、ENGINEERING_JSONL回放、重建资源导出、六工具生命周期、场景波形/周期/WAIT/断言/负例、TCP与视频历史、25API/控制台/Robot、真实消费者/资源激活与发布门禁继续原任务。PreparedReplay.execution_ready恒false，require_execution_ready以STATE拒绝，无TX/APPLIED/CONSUMED/E2/E3；不标完整HISTORY/W3/M3/M4或整体完成，41责任保留、17 Linux全部未执行。
- 专项/复核与回归：26回放和3改码通过，覆盖44可回放UDP输入及13CANFD输入各三模式、三个辅助分支、实际checksum/完整重组与反馈隔离。SessionOpen由正式握手执行器负责，不当已授予会话回放。独立端点P2已RED/GREEN修复，signed-zero冲突重传/实际payload hash及原/正式辅助hash也已失败复现修正，复审无重要scoped发现。完整422共用（67协议/348网关三源/3台账/4汇总）及34静态、59业务/72完成/85黄金片/800RAW、依赖/编译与14逐字节源/663引用通过；`artifacts/icd_gateway/w3-7-validation.json`保存实际命令/hash，不覆盖旧报告或写回冻结QA。

### 2026-10-04 W3.8实际源会话与统一取号移交

- 共用实现：SourceSession发送原标准SessionOpen/新nonce，只用实际匹配129取得SID、角色/模型/公布能力；核对两层baseline、SID/header及唯一accepted_roles。统一跨输入全局sequence、事务预约与显式target_step；计数不回绕，失败/不足能力在TX前拒绝。UDPSource按原ICD接Heartbeat2的Status131和ClockSync33的ClockStatus142，142关联原nonce，不把其他反馈当ACK。Heartbeat只用调用者显式sender_step，保守租期从原请求前本地mono起算，失败/普通反馈不续租。
- 归属与证据：同一传输生命周期仅一个取号管理器，绑定前手工TX事务号保留为下界，绑定后send/request/receive_for只由owner使用；本地close不释放归属，abandon不是实际38/RESET/清队列。owner只属本地API，不改ICD。请求deepcopy保持原业务值和signed-zero；真实反馈在时钟读取前保存为不可变canonical记录，时钟失败保留实际未获资格反馈/错误，不制造完成时间。记录默认64条/4MiB、发送前预留反馈空间、满时BUFFER_FULL并显式drain；不是原始TX片持久证据/E2/E3。
- 本阶段追加Linux同码网络资格（L-001/L-002/L-017）：隔离Python3.12运行同一公共入口和31会话专项，在实际四ETH/双向ACL下验证真实129拒绝/授予、两层pin、能力/角色/模型、源端点、原码重试、序号/事务关联与租期。实测延迟/乱序/重复旧grant、错误身份、反馈断链、计数耗尽和满记录；新管理器/手工插入开会话不得复用旧授权。不得复制源端实现、增模拟器端口或把Windows回环当实际目标资格。
- 本阶段追加Linux模型与时钟资格（L-004/L-010/L-011/L-013）：真实消费者提供准确模型步、Status、ClockStatus和实际探针；完整双向时钟测量及500us不确定度、租期/周期/负载在目标实测，不用本机mono或测试peer证明。每轮回放的新SID必须由真实标准授予，RESET/initial_inputs/清队列/安全值/旧会话退休由真实C边界及原工具完成，不能以取号/本地abandon替代。实际141.complete只证明后台字节存储，不等于视频解码/模型激活/应用反馈。
- 本阶段追加Linux原工具与验收资格（L-005/L-006/L-007/L-008/L-009/L-012/L-014）：原六工具发送分支由同一共用所有者分配实际SID/Header并保留各自CAN/以太网/文件链路，验证实际互斥、停止/撤权、反馈关联和原TX/RX；设备/视频仍有独立消费者及实体门禁。Robot分开判定实际交换、存储、模型应用、业务与安全，不把Header接ReplayProcessor或execution_ready=false的包准备记作已执行。
- 共用未完而非Linux重写：当前源适配器串行阻塞，最长10s资源提交时不能同时满足冻结Heartbeat周期。后续共同异步反馈分发/多在途请求及模型步调度器必须处理心跳、反馈/超时、撤权/清理和64反馈SID有界退休，不能清缓存伪造新鲜度以跑10000repeat。完整三模式执行器、工程量JSONL/TCP/完整视频历史、重建日志/PCAP导出、场景波形/周期/WAIT/断言/负例、六工具生命周期、25API/控制台/Robot、消费者/持久原码证据及发布门禁继续原范围。41任务责任保留、17 Linux全未执行，完整W3/M3/M4和真实3.3替换未验收。
- 专项与复核：31专项通过，包含真实socket授予/拒绝/手工归属/旧反馈隔离、实际资源34/141及真实Header接原回放准备；后者仍execution_ready=false。独立发现两种旧grant授权混淆路径，均先RED复现再以传输生命周期唯一owner、原手工事务下界及实际TX/RX入口归属检查修复；独立31专项及最终资源等待分支实际TIMEOUT复测无遗留重要scoped发现。阶段完整回归、命令/源码hash与未完范围仅存`artifacts/icd_gateway/w3-8-validation.json`，不重写原14源/历史报告或运行冻结QA写回脚本。
- 最终回归：固定修正版本完整453共用通过（67协议/379网关三源/3台账/4汇总），另34静态、59业务/72完成/85黄金片/800RAW、pip/编译与14逐字节源/663引用通过；41责任与17未勾选Linux门禁守护通过。修改中的混合版本运行exit1不计验收，已等待结束并完整重跑，报告保留该事实。完整开发目标仍active，本批真实授权及存储不关闭模型/工具/目标或正式替换门禁。

### 2026-10-04 W3.9共用异步UDP调度移交

- 共用实现：UDPDispatcher绑定实际LIVE SourceSession，统一有界多在途请求、原标准反馈关联和非阻塞逐片发送；原串行API保留但绑定期间不能争用源所有者。每个实际发送token只编码一次，首次完整逻辑组按全局sequence发完才允许后组，可靠最多4次原码尝试、周期消息不重传旧值，资源最终提交等待10s不阻塞poll。实际TX时刻同时约束20Mbit/s，预约到期不能挤成突发；没有新增wire字段、Windows分支或原工具替代品。
- 证据与期限：SUBMITTED保存实际请求，TX保存sendto成功的原片/尝试号，RX保存实际匹配反馈，失败/取消不静默丢记录；默认64在途、4096记录/16MiB，先预留再取号，单请求最多8条RX。实际发送后时钟异常仍保留TX及null/SCHEMA，不编造时间。每次TX前后与RX后复查租期；资源提交10s后到达的反馈保留但判TIMEOUT，节流重试期间原反馈仍可正确关联。记录只是有界内存证据，不是持久E1或模型E2/E3，本地close不等于远端38/RESET/清队列。
- 本阶段追加Linux同码网络与容量资格（L-001/L-002/L-017/L-013）：在隔离Python3.12、实际四ETH与双向ACL下运行同一dispatcher和公共入口，实测多请求/多分片交错、200ms重试/10s提交、延迟/丢包/乱序/重复/断链、64在途及记录/字节容量、取消和租期跨界。测实际资源TX间隔与20Mbit/s预算，保留真实网卡原TX/RX；Windows回环和人工perf_counter测试不是网卡吞吐/硬件时间戳或RT证据，不复制另一调度器。
- 本阶段追加Linux真实心跳与时钟资格（L-004/L-010/L-011/L-013）：实际C消费者提供Status/ClockStatus和准确sender_step/target_step，授予能力公布2后才启用20ms心跳。在32KiB逻辑组、多请求/资源负载和1ms模型步并发时，测实际Heartbeat TX的1ms jitter、100ms重组期限、租期及跨机同步；晚到明确失败、不补发追赶或放宽冻结期限。单协作式poll不承诺所有负载组合满足RT，若实际测量不达标必须在同一架构内调整有界工作/调用调度并重验，不能用测试peer续租冒充真实模型服务。当前真实Receiver能力仍为[1]，安装实际资源worker仅[1,34]，自动心跳在其上TARGET_MISSING。
- 原序列与丢包边界（L-010/L-014/L-017）：最早组未被接收且后续组已接收时，旧序号原码重试可能被正式全局新鲜度规则拒绝OUT_OF_ORDER。实际入口丢包负例已经保留该失败和相同原重试片，不改号或声称必然恢复。Linux必须验证业务结果/安全策略与调用侧并发许可；若场景必须保证顺序完成，调用方须按正式反馈限制在途，不得私改ICD、可靠重试字节或接收端规则。
- 本阶段追加Linux原工具与验收资格（L-005/L-006/L-007/L-008/L-009/L-012/L-014）：六原工具保留各自CAN/以太网/文件通路，后续共用封装接统一实际授予/取号与独立反馈关联；Linux验证真实进程启动/互斥/停止/撤权、设备与视频消费者。实际34/141只证明后台VIDEO字节存储，不代表模型激活/视频解码；protocol peer的131仅为规则测试，不计真实Status或E2/E3。
- 共用未完而非Linux重写：64反馈SID真实退休及10000repeat、完整三模式回放授权/模型步/RESET/initial_inputs/清队列与每轮结束清理、工程量JSONL/TCP/完整视频历史、重建日志/PCAP导出、场景波形/周期/WAIT/断言/负例、六工具生命周期、25API/控制台/Robot、真实消费者、持久原码证据及正式发布仍属原任务。PreparedReplay.execution_ready仍false，41任务责任与17未执行Linux门禁不变，不标完整W3/M3/M4或整体完成。
- 专项与复核：21专项已通过，包括真实原资源worker的34/141存储、较大先组不被短后组超越，以及实际入口丢包后的原序列失败。独立只读复核的五个问题均先RED后GREEN修正：预约突发、晚提交反馈越过期限、post-TX时钟异常丢事实、节流重试空deadline及poll内租期跨界；最终独立21专项无遗留重要scoped发现。阶段全量结果和源码哈希待固定版本回归结束后保存到独立`artifacts/icd_gateway/w3-9-validation.json`，不改14冻结源、历史报告或冻结QA输出。
- 最终回归：固定版本单一公共入口474共用通过（67协议/400网关/3台账/4汇总），网关实际耗时606.039s；另34既有静态、31源会话/14原UDP/9资源UDP/21调度器专项、59业务/72完成/85黄金片/800RAW、pip/编译及14逐字节源/663引用通过。41责任/17未勾选Linux守护通过，实际命令及四个源码/测试哈希已保存`artifacts/icd_gateway/w3-9-validation.json`。测试耗时不是RT性能或目标验收；完整目标仍active。

### 2026-10-04 W3.10原工具完整捕获资源导出移交

- 共用实现：ReplayExporter将既有PreparedReplay导出为逐通道完整CAN_LOG或纳秒PCAP，复用原WireCodec/CaptureParser/python-can/Scapy。明确本地接口绑定，辅助CAN到正式UDP须提供两项实际单播MAC，原Ethernet不得重写MAC/TTL/VLAN等；保留业务字节、Header/CRC、原包/重复片顺序、FD/BRS/ESI、源/输出hash及整数时间。原CAN/以太网链路和六工具保留，不创建转发中心或Windows驱动版本。输出是预处理资源，execution_ready恒false，不证明发送或模型应用。
- 模式与完整性：PreparedReplay只新增内部不可变policy_json，未改调用者参数或wire。导出核对完整冻结policy/hash/mode/repeat/gap、实际捕获/窗口/倍率，拒绝分数ns、整组选中记录遗漏、缺片/额外片/混合Header/布局/通道、错误端点、RAW改帧/换通道/端点、SESSION复用捕获SID、虚假changed_fields或未许可改写。FROM_36单独计数不进入发送文件；每轮一个资源包，不自动工具循环10000次代替新会话/RESET。
- 有界持久化：最多100000片、64MiB文件+manifest、56显式绑定（实际本批正式CANFD/ETH通道共8）；不可变bytes和逐片索引，最终原解析器读回核对。独占新目录及xb写入，fsync/逐文件hash读回后写入并验证manifest.pending.json，最后用不覆盖的硬链接发布manifest.json；保留pending链接，不在发布后进行可能失败的清理。既有目录/文件不覆盖，发布前失败保留未完成目录且没有完整manifest，不删除用户文件。不支持硬链接的实际文件系统明确失败，不静默退化；此策略不等于目录断电持久性、正式发布或持久E1。
- 本阶段追加Linux原回放工具文件资格（L-001/L-002/L-005/L-007/L-008/L-009/L-017）：用同一导出器/文件包，锁定实际canplayer/tcpreplay/python-can/Scapy/libpcap版本及哈希，在vcan/真实CANFD和真实网卡逐项确认文件读取、通道映射、FD/BRS/ESI、完整逻辑组/原码重试/双向ACL与反馈。vcan、文件解析和Windows回环均不是物理资格；实际工具输入只来自通过授权和执行器检查的资源，不能因manifest存在绕过当前SID/角色/序号/target/模型/状态。
- 本阶段追加Linux时序与调用约束（L-007/L-009/L-010/L-011/L-013）：实际canplayer主线调度对9位时间截到微秒，文件仍保留准确ns；相对间隔不能精确表示为微秒或同文件时间倒退时tool_timing_compatible=false，不能按原时序直接运行、不能排序/四舍五入/忽略时间冒充合格。标true只表明文件时间可表达，不是目标周期/抖动通过；tcpreplay实际构建的纳秒读取/调度未测为unknown。Linux需测20ms心跳、100ms组期限、20Mbit/s资源与1ms模型步并发、跨机时钟、各通道起始对齐/负载/停止；达不到冻结时序就拒绝该工具分支/用例，不改契约或私换工具。
- 本阶段追加Linux持久化与安全验收（L-003/L-013/L-014/L-015）：实际文件系统硬链接/fsync/权限/磁盘门限、失败目录/缺manifest/文件篡改/崩溃恢复及完整包验证必须独立实测。正式证据仍须包含实际TX/RX、消费者探针、业务/安全与停止/撤权/清理，不把导出hash当E1/E2/E3或发布ready。消费者接口和工具生命周期的共同校验继续共用代码，不推到Linux重写。
- 统计口径校正：冻结目录13类CANFD消息实际为11条TO_36输入+Ack/Status两条FROM_36反馈。本包19专项覆盖全部11输入完整日志重组，以及44条非SessionOpen输入的三模式UDP文件；独立另做33次CANFD导出覆盖11输入三模式/ESI。历史记录中“13 CANFD输入”或测试名的13应理解为目录总数，不能把两个反馈当输入发送，也不修改冻结目录取得数量一致。
- 共用未完而非Linux重写：完整工程量JSONL/TCP/视频历史提取与执行、完整三模式真实授权/模型步/RESET/initial_inputs/队列/轮间清理、64反馈SID真实退休及10000repeat、六工具能力探测/真实进程/互斥/停止/独立反馈、场景波形/周期/WAIT/断言/负例、25API/既有控制台/Robot、实际消费者及持久TX/RX/发布门禁仍必做。此包只关闭完整捕获资源导出这一缺口，41任务责任与17未执行Linux保留，不标完整W3/M3/M4或整体完成。
- 专项/复核：19导出专项、26原回放与23解码专项通过，包含真实目录写入/读取和注入fsync失败后的实际文件保留。独立重要发现均先RED后GREEN修正：时间/policy不一致、整条记录遗漏、RAW L2/通道篡改、SESSION旧SID/虚假改写、非法UDP端点、清单缺完整policy及倒退CAN时间误判兼容；另修复同组Header混入。最终独立19专项9.564s及33 CANFD输出通过，无遗留重要scoped发现。固定版全量回归正在运行，结束后仅保存独立`artifacts/icd_gateway/w3-10-validation.json`，不改14冻结源、原C/六工具、历史报告或冻结QA输出。
- 最终回归：固定版本公共入口493共用通过（67协议/419网关/3台账/4汇总），网关实际262.646s；另34选定静态、19导出/26原回放/23解码专项、59业务/72完成/85黄金片/800RAW、pip/编译、14逐字节源/663引用与41责任/17未勾选Linux守护通过。阶段命令、三个源码/测试哈希和未完范围已保存独立`artifacts/icd_gateway/w3-10-validation.json`，不覆盖历史报告。测试时长不作为工具/硬件/RT资格；17 Linux仍全部未执行，完整目标仍active。

### 2026-10-04 W3.11原工具安装证据与共用生命周期移交

- 共用实现：`tools.py`核对冻结六分支CANT/CUTIL/SAVVY/CANREPLAY/ETHGEN/ETHREPLAY及其管理API名称，读取实际distribution版本、模块origin/RECORD归属与PATH绝对可执行文件SHA256，不导入工具或启动GUI/版本命令。安装、可运行、目标资格分别记录；当前库cantools40.7.1/python-can4.6.1/Scapy2.7.0实际存在，但六分支在当前宿主均UNAVAILABLE，不以库安装或诊断进程标AVAILABLE、SocketCAN/网卡ready。API行保持冻结branch_id/status/reason三字段，扩展诊断只属内部证据。
- 本地预约：共用ChannelReservations默认/最大64个run、最多56接口，跨原分支以实际物理接口为互斥键，多个接口先全部检查再预约；OBSERVE不持发送预约，可以与SEND预约共存。run重复/容量满/接口冲突不删除既有owner，释放仅接受本簿实际opaque对象，伪造/外簿/旧token拒绝。SEND预约仍authorized_to_transmit=false，不能替代真实SessionGranted、ControlOwner、执行器预检或进程树/模型安全清理；正式执行器必须在确认实际停止与安全后才决定释放，不能自动按诊断退出码撤权。
- 共用真实进程核心：`tool_process.py`以可信内部literal argv/绝对native executable/明确cwd、shell=False及DEVNULL stdin启动直接子进程；不用shell字符串/批处理、没有Windows后端旗标或工具克隆，不向管理API暴露任意exec。两个reader保存原二进制stdout/stderr并共用默认1MiB/最大64MiB额度，超限即明确BUFFER_FULL、终止直接子进程并保留有界前缀及观察byte计数，不能静默截断为成功。实际PID/returncode/启动与完成本地主机mono/错误/直接子进程终态及EOF分别记录；非零/超时/读失败/停止失败均不冒充完成。Popen创建阶段不可硬限时，合作式poll需要实际调用，整个核心不承诺RT。
- 停止与证据边界：实际terminate→有限wait→kill→有限wait，停止/close永久禁止重启但保留原数据；系统wait/kill异常保留FAILED/STATE与实际handle，允许后续重试。超过原期限后才观察退出为TIMEOUT，而不是成功；自然退出但EOF晚到保留EXITED，不能编造成主动STOPPED。直接子进程退出不代表孙进程、GUI/drone/设备、安全值或远端九项清理完成，tree_cleanup_verified恒false；持pipe的子孙未到EOF时明确失败，不能释放实际发送/设备授权。stdout/stderr只是诊断，不是ICD反馈、原TX/RX或E1/E2/E3。
- 本阶段追加Linux安装与分支资格（L-001/L-002/L-005/L-006/L-007/L-008/L-009）：在隔离同版Python运行同一inventory和生命周期测试，锁定实际六工具/bin/library/driver/libpcap版本、path/hash与安装来源；验证SocketCAN/vcan与真实CANFD分开、SavvyCAN实际GUI/后端及Ostinato GUI/drone/Scapy原网卡分开。库metadata只证明安装文件来源，不证明依赖完整/模块可导入/实际driver/FD+BRS/纳秒调度或车辆网链路；真实版本与后端缺失仍拒绝必选分支，不静默切到UDP或Windows SDK。
- 本阶段追加Linux进程树/停止/安全资格（L-003/L-006/L-007/L-008/L-009/L-010/L-013/L-017）：实际工具参数应来自同一可信adapter与审核资源，不接受前端任意argv。部署组/服务/cgroup或适用POSIX后端须证明直接子进程、子孙、GUI/drone、worker及管道均停止，实际权限/TERM无响应/KILL失败/进程重用/日志超限/断链分别验证；树清理在目标实现，不使用Windowstaskkill/Job Object复制版本。收到停止/到期/撤权时同时保留标准反馈采集、原TX/RX、控制安全值、周期/回放发送停止和队列/资源取消，完成后才可释放本地预约/切换真实3.3；进程退出0不足以证明实际授予/业务/安全完成。满诊断失败和stop错误必须保留而不是删除记录获得通过。
- 共用未完而非Linux重写：六工具可信command builder/能力资格/当前标准授予取号/反馈关联与预约联动、完整三模式/工程量/TCP/视频执行器、64 SID真实退休/10000repeat、场景/波形/周期/WAIT/断言/负例、25API/控制台/Robot、真实消费者/ClockSync/持久原TX/RX和正式发布继续原完整计划。此包实现共享生命周期基础，不标完整M3/M4/W3或六分支业务可用；41责任、17未执行Linux、原C/六工具和14源保持。
- 专项/复核：9工具安装/预约及18实际进程专项通过，包括双流327680byte无死锁、实际超限/超时/主动停止/非零、真实创建失败、持pipe后代及系统异常注入后实际handle重试。重要问题先RED后GREEN：迟观察退出误判成功、自然退出误判STOPPED、影子模块套distribution版本、第二次wait的OSError逃逸；独立复核已指出等待异常，修正后再次只读核验中。固定版全量回归正在运行，最终命令/hash与未完范围保存独立`artifacts/icd_gateway/w3-11-validation.json`，不覆盖历史或重写冻结QA。
- 后续复核补充：独立发现自然退出后等待EOF跨过原执行期限仍报EXITED，已以真实后代持pipe负例RED复现，再将自然完成的join等待压到原期限并在终态前复核，结果FAILED/TIMEOUT且不虚构输出完整。最终主执行19进程/9工具专项通过，独立19进程2.829s/9工具5.650s通过，无剩余重要scoped发现。先前全量入口启动后修正了此问题，须等待该具体进程终态后再对固定最终版本完整重跑，混合版本不计验收证据。
- 全量守护补充：首轮具体进程已终态exit1（446网关/270.832s），发现安装报告按宿主OS判断状态违反既有共用不分流守护。已保留原守护不变，删除该判断；状态只依实际依赖存在性，安装完整为UNVERIFIED、缺依赖为UNAVAILABLE，目标后端/权限/时序/授予仍单独未验证，绝不自动AVAILABLE。当前SIGNAL_CAN/ETHERNET_GENERATOR的库安装证据为UNVERIFIED，其余四分支缺工具为UNAVAILABLE；先前本批“六分支均UNAVAILABLE”为修正前安装报告，不能当最终状态。新增真实Python可执行文件读取hash测试只验证探测，不冒充工具安装。最终固定版本需完整重跑，首轮不计验收。
- 最终只读复核补充：修正后独立10工具安装/预约6.058s及6原CLI/共用不分流守护5.110s通过，原19进程2.829s的源码未再改变，无剩余重要scoped发现。固定最终全量入口已经启动并沿同一具体handle观察；不在运行中修改业务/测试源码或把首轮结果冒充最终证明。
- 最终回归：固定最终公共入口522共用通过（67协议/448网关/3台账/4汇总），网关实际357.666s；本批29新增专项，另34选定静态、6原CLI、59业务/72完成/85黄金片/800RAW、pip/编译及14逐字节源/663引用与41责任/17未勾选Linux守护通过。阶段命令、四个源码/测试SHA256、实际安装版本/最终状态、只读复核及首轮失败/混合版本不计验收事实均保存独立`artifacts/icd_gateway/w3-11-validation.json`。未改原工具/C/冻结ICD，17 Linux仍全部未执行；工具启动/进程树/实际链路/授予与消费者资格并未因此完成，测试耗时不是RT性能，完整目标继续active。

### 2026-10-04 W3.12受控观察与回放参数移交

- 共用实现：`tool_commands.py`仅准备原CUTIL/candump观察、CANREPLAY/canplayer和ETHREPLAY/tcpreplay固定literal参数。本簿opaque预约在构建前和完整导出后核验，绑定仅四CANFD或四ETH正式通道的一一显式接口，未知/重复/额外接口、any、失效/伪造/外簿token拒绝，预约验证不释放owner也不授予线上发送权。CANT/cansend实时发送、SavvyCAN GUI/backend及Ostinato/Scapy仍保留，不用三个参数builder替代六原工具。
- 观察与回放边界：candump只用日志stdout/纳秒/RxTx及13正式双向标准非RTR ID过滤，13含11输入+Ack/Status两反馈；不是全总线或实际零丢包/硬件纳秒时钟证明。回放经现有ReplayExporter重新核验完整PreparedReplay、原policy/源/hash/时序/限定改写，反馈不注入，输出逐通道完整CAN_LOG或PCAP、文件hash、原准确首次offset和固定单轮。canplayer显式write=log映射，不能忽略时间/跳gap/无限循环；tcpreplay使用单轮与倍率1.0，已批准rate在上游处理，不二次缩放。CAN相对时间不可微秒表达或倒退仍UNSUPPORTED，不排序/四舍五入；PCAP纳秒调度资格仍unknown。
- 不可执行与持久化：参数包execution_ready/authorized_to_transmit恒false，require_execution_ready明确STATE；本批不启动原工具、不写资源、不产生实际TX/RX/APPLIED/CONSUMED或E1/E2/E3。返回资源仍由原独占write_new_directory持久化；真实文件路径/bytes/hash的专项通过不等于后续启动前复核、当前SID/角色/全局序号/target/模型/状态/RESET与轮间清理通过。逐通道首包相对offset原值保留，由共用执行器承担实际起始协调，不能把四个独立工具首包立即发送当同步。basename argv不是已锁定绝对可执行文件，不直接接进程监督器或公开任意exec。
- 本阶段追加Linux安装与参数资格（L-001/L-002/L-005/L-006/L-007/L-008/L-009）：同一隔离Python和builder/导出器/预约代码复测，按实际工具版本/bin/hash/SocketCAN/网卡权限核对参数支持；分别用原candump观察、canplayer和tcpreplay执行批准完整资源，保留实际bus/网卡TX及标准反馈，不能拿stdout/stderr或退出0当发送。canplayer上游stdout是特殊打印目标，本批已明确拒绝该伪接口；真实设备名/ifindex/FD+BRS/DLC与通道映射仍需实测。SavvyCAN、CANT、Ostinato/Scapy的受控后端及实际资格继续原责任，不另写Windows工具克隆。
- 本阶段追加Linux时序/权限/安全资格（L-003/L-007/L-009/L-010/L-011/L-013/L-014/L-015/L-017）：实际canplayer微秒截断和调度、tcpreplay纳秒PCAP读取/调度须用锁定版本测试，time-compatible不能代替1ms模型步/20ms心跳/100ms组期限与真实并发抖动通过。四通道首offset协调、跨机时钟、设备队列与工具启动延迟、实际标准授予/撤权/角色/序号、每轮新SID/RESET/initial_inputs/清队列均须完整执行器加真实C目标验证。目标目录/权限/防篡改、启动前实际文件与可执行hash复核、进程树/GUI/drone停止、有限日志/失败保留及安全值仍必做；完成实际停止和安全清理后才可释放预约或替换真实3.3。
- 共用未完而非Linux重写：CANT/cansend实时合法组参数、SavvyCAN和ETHGEN受控原后端、预约与真实SourceSession取号/发送/反馈联动、模型步/多通道起始调度、完整三模式10000repeat和64 SID真实退休、工程量JSONL/TCP/视频历史执行、场景波形/周期/WAIT/断言/授权负例、25管理API/既有控制台/Robot、真实消费者/ClockSync/资源激活/持久原TXRX及正式发布继续整体计划。本批只完成三个原工具分支的参数准备部分，不勾选完整M3/M4/W3；41责任和17未执行Linux全部保留。
- 专项/复核与最终回归：首批12测试在模块/validate缺失时明确RED后实现；补四CANFD/四PCAPNG通道、真实目录/bytes/hash和上游2X/10000repeat不二次改速或工具多轮测试。独立发现canplayer stdout打印钩子被当发送接口，17专项先RED（未抛ICDError）后GREEN拒绝。最终根执行17专项1.638s，独立17专项1.698s/19原导出9.715s与未审核/时间policy源hash篡改、导出期间撤销预约探针通过，无剩余重要scoped问题。固定版公共入口539共用（67协议/465网关/3台账/4汇总，网关270.316s）及34选定静态、6原CLI、10原工具、59/72/85/800、pip/编译、14逐字节源/663引用守护通过，独立阶段报告`artifacts/icd_gateway/w3-12-validation.json`记录命令、三源码/测试SHA256和未完范围。不重写冻结QA、不覆盖历史报告；当前宿主无实际libpcap/六工具/模型资格，测试耗时不是目标RT证据。

### 2026-10-04 W3.13当前标准授予与原工具输入准备移交

- 共用实现：SourceSession新增有界不可变完整PreparedSourceInput，与原exchange共享数量/字节额度，仍是唯一全局sequence/transaction取号者，既有dispatcher独占时不允许旁路。按当前标准SID/lease/角色/模型/已公布消息能力检查，预检/编码/容量/到期失败不消耗计数；完整取号后工具异常/预约撤销保留原组、不回号、不虚构TX。drain_records不丢输入，discard只回收本地证据，abandon/close只清本地准备池，不代替真实RESET/停止/撤权/队列清理。
- 原工具链保留：live_tool_input.py仅准备CANT原cantools+python-can标准FD+BRS/DLC64完整对象组、CUTIL逐片literal cansend及ETHGEN原Scapy Ether/IP/UDP完整组。不启动Bus/sendp/SocketCAN/工具进程，不增加中央转发路径或Windows专用后端。绑定明确正式通道/本簿有效SEND预约/单物理接口；ETH限定当前实际会话transport通道与实际部署端点、显式非零单播MAC，不以冻结初始化端点或本地预约冒充线上授权。SavvyCAN/Ostinato受控后端及实际能力仍保留后续。
- 字节与授权边界：先按原始类型校验，再分别保存canonical证据与原值input_json快照，两者均计容量；线上ICD不增字段，PACKED_LE负零符号位与原工具二次编码保持。可变python-can Message每次新建，不作为证据存储。核验只接受本owner实际opaque对象，伪造/外簿/discard/旧SID/到期对象明确拒绝；execution_ready与authorized_to_transmit恒false，完整组不等于实际ControlOwner/target_step/模型状态、backend资格或原TX/RX/E1/E2/E3。
- 本阶段追加Linux后端与部署验证（L-001/L-002/L-005/L-006/L-008/L-017）：用同版隔离Python和本次同一代码/专项复测，锁定cantools40.7.1/python-can4.6.1/Scapy2.7.0及实际can-utils、驱动、SocketCAN、网卡/libpcap版本、可执行与依赖hash。原CANT/cansend分别验证实际标准ID/FD/BRS/DLC/完整组/通道/反馈；vcan不计物理资格。原Scapy/Ostinato验证实际接口/ifindex、source/destination MAC、IP/UDP端口、路由/网段广播判定、校验和、ACL/部署grant及qualified_channels；prepared L2 bytes和回环SID不证明正式网卡发送。不同原通道须证明真实 ingress 与当前授予一致，不静默换UDP或Windows SDK。
- 本阶段追加Linux时序/当前授权/安全验证（L-003/L-010/L-011/L-013/L-014/L-015/L-017）：完整共用执行器在实际启动/每次发送前结合当前标准SID/角色/ControlOwner、真实模型状态/target_step、全局首次TX顺序和租期，不能只调用validate即发送。原cansend逐片进程成本、python-can/Scapy backend的20ms心跳/100ms输入组、20Mbit/s资源/1ms模型步并发及跨机时钟必须实测，不将测试耗时、构造64字节对象或安装库当RT资格。取消/撤权/到期时证明原进程树/GUI/drone/设备和发送队列停止，保留独立标准反馈/原TXRX及安全值、九项清理后才可释放预约和切换真实3.3；准备组discard与直接子进程退出不构成上述证据。
- 覆盖与未完：协议peer结构专项覆盖全部11类CAN TO_36输入与44类非SessionOpen UDP输入；冻结13类CAN含Ack/Status两反馈，不当发送输入。另实际接收服务授予[1,34]，在真实SID下准备34 VIDEO资源组且确认没有额外工具TX/admission；它不是视频解码/激活/模型应用。共用未完仍包括实际授权/工具生命周期/全局TX调度/标准反馈联动、SavvyCAN/Ostinato后端、完整三模式10000repeat/64 SID真实退休/RESET/initial_inputs/轮间队列清理、工程量JSONL/TCP/视频历史执行、场景波形/周期/WAIT/断言/负例、25API/控制台/Robot、真实消费者/ClockSync/持久证据/发布与真实3.3门禁。这些继续一份共同代码开发，不全部推到Linux重写；41责任与17未执行Linux保持，不勾选完整M3/M4/W3或整体目标。
- 专项/复核与最终回归：首批12项明确缺接口/模块RED后实现；补容量/非法对象/原库故障等20专项后，浮点message_id归一化误接受和PACKED_LE负零丢位两个用例先RED，再改原类型校验及双快照，22专项4.998s通过。独立修复复核2回归/22专项/31原会话及共享精确bytes/lease/owner/部署端点/原库预检探针通过，无剩余必须修复scoped问题。固定版公共入口561共用（67协议27.976s/487网关272.513s/3台账/4汇总）及34选定静态、59业务/72完成/85黄金片/800RAW、pip/编译、14逐字节源/663引用守护通过，三源码/测试hash及完整剩余范围记录独立`artifacts/icd_gateway/w3-13-validation.json`。14冻结源/原C/六工具/历史报告不改；测试不是目标RT或发布证据，整体目标继续active。

### 2026-10-04 W3.14冻结波形语义与原三源审核移交

- 共用实现：waveform.py按冻结97条model_bindings中的83数值绑定编译CONSTANT/STEP/RAMP/SINE/CHIRP，覆盖三个型号91个标量/固定数组元素。field_path只能是原完整Stimulus.payload已注册数值字段及数组明确索引；bool/enum、输出/反馈、未知/无根写入绑定或错误型号拒绝，不推断新端口、不修改原C/六工具/14冻结源。每次sample(step)返回重新验证的完整脱离副本，不分配Header/sequence、不发送，不生成E1/E2/E3。
- 数学与保真：显式整数MODEL_STEP，STEP.change_step为相对起点；RAMP/CHIRP内部duration和事件外层duration均限幅时间而非修改数值，结束保持实际终值。SINE/CHIRP以实际单调相位区间解析峰谷，整段越界即拒绝，不只看采样点、不用保守全包络误拒绝短片段；实际区间最高频率须有至少10倍采样。起点/持续溢出拒绝，不枚举86400000步。原数值类型与PACKED_LE负零保留，RAMP显式起止值不重新算成正零；数学采样满足不代表消息周期/网络负载/RT合格。
- 原三源审核：SourceInputAuditor编译所有WAVEFORM事件，原文档先保持原始类型校验再保存canonical证据与原值快照，两者共同计16MiB；不借canonical归一化浮点message_id或丢未修改字段负零。原资源审核/线上Schema/ICD/六工具链不变；compiled waveforms和源审核execution_ready仍false，不当作实际授权或完整场景执行。场景顺序/同目标跨工具碰撞/WAIT/断言/负例/结束九项清理继续原共用执行器，不在本阶段伪造完成。
- 本阶段追加Linux同代码与真实模型绑定开发验证（L-001/L-002/L-004/L-014/L-017）：同版隔离Python复测本次共用采样器与原三源审核；三个型号83数值绑定/91元素的实际C端口、固定数组索引、单位/量纲、范围和运行时map完整性须逐一核对，不能用冻结表/结构单测代替实际写入和业务作用。原hil_contract/消费者按标准消息应用完整字段，以真实输入探针和模型输出证明E2/E3，布尔/输出/未登记消费者仍不允许波形写入；其他正式消息/设备/视频消费者继续全计划，不因本批数值覆盖声明全部45输入已生效。
- 本阶段追加Linux模型步与时序/负载验证（L-002/L-010/L-011/L-013/L-017）：实际MODEL_STEP来自目标模型，不用宿主sleep、墙钟或虚拟计数替代；验证1ms模型步±10us、80ms系统±1ms、20ms心跳、控制100ms有效期及资源20Mbit/s并发。采样器的1000/sample_period_steps和10倍频率只是数学条件，正式消息自身周期、CANFD/ETH逐片/队列与带宽/丢包预算须独立满足；共用调度器须明确采样步、目标步、首次TX顺序/截止、跨机ClockSync/时钟回拨和过期策略，不通过改契约、静默丢样或私换原工具取得通过。
- 本阶段追加Linux当前授权、终值与安全验证（L-004/L-010/L-013/L-014/L-017）：实际应用前结合当前标准SID/角色/ControlOwner、真实型号状态/target_step及标准反馈，不以本地waveforms、source audit或预约当授予。证明控制年龄/迟到旧值拒绝、内部/外层结束后终值保持及真实END_CLEANUP/安全值接管，撤权/到期/故障时停止周期/回放/原进程树/GUI/drone/设备队列并执行九项清理；真实fault reset/消费者恢复/安全探针成功后才可释放预约或替换真实3.3。采样sample/end hold及本地丢弃不能冒充上述事实。
- 共用未完而非Linux重写：完整MODEL_STEP场景调度/全部事件/碰撞/WAIT/断言/授权负例/九项结束清理、原工具当前标准授予/全局TX/生命周期/独立反馈联动、SavvyCAN/Ostinato原后端、完整三模式10000repeat/64 SID真实退休/RESET/initial_inputs/轮间队列清理、工程量JSONL/TCP/视频历史执行、25管理API/既有控制台/Robot、实际消费者/ClockSync/资源激活/持久原TXRX/正式发布和真实3.3门禁均继续同一代码和原责任。仅关闭冻结波形采样与审核缺口，41责任及17未执行Linux不删除、不勾选完整W3/M4或整体完成。
- 专项/复核与最终回归：缺少采样器/审核编译明确RED后实现，显式型号缺失及RAMP负零端点再RED后修正；14波形专项9.056s、39旧三源34.426s通过。独立14专项8.932s及短扫频最高频/内部峰谷/内部duration保持/严格bool与float步/未修改字段负零/精确双快照容量探针通过，无剩余必须修复scoped问题。固定版公共入口575共用（67协议28.333s/501网关285.452s/3台账/4汇总）及34选定静态、59业务/72完成/85黄金片/800RAW、pip/编译、14逐字节源/663引用守护通过，三源码/测试hash与范围保存独立artifacts/icd_gateway/w3-14-validation.json。历史报告不覆盖，测试耗时不是RT或硬件资格，17 Linux仍全部未执行，整体目标继续active。

### 2026-10-04 W3.15共用场景编译与惰性时间表移交

- 共用实现：scenario.py按冻结十类Event编译不可变原值快照与有限等差流，依(at_step,priority,event_id)惰性合并完整Stimulus。SEND/FAULT/周期/波形仍走原工具和正式ICD，准备不分配Header/sequence/SID、不启动或发送；WAIT/ASSERT/REPLAY/NEGATIVE_SEND/END_CLEANUP保持完整待执行请求，不编造真实反馈、模型写入或完成清理。模型步为显式离线参数而非宿主时钟，plan/action execution_ready恒false。
- 完整写入集合与碰撞：根7..19复用原ModelBindings分组，按冻结model_id/target_field和数组逐元素定位，三个型号97绑定/105目标包含bool，不能将工具、message_id或被波形修改的单字段当互斥键。7/14等别名、两个波形即使不同field_path、周期后续交点及非整除波形最终采样的同端口同一步均拒绝，不用last-write-wins。有限等差流用gcd/模逆相交，不展开百万周期或86400000模型步；默认100000/最大1000000比较，超限CAPACITY而非忽略。其他正式消费者及REPLAY实际写集合尚未接入，明确pending，不把元数据根绑定覆盖说成全部45输入消费者合格。
- 排序与有界证据：周期首份在START步，其余依period/count；同一步STOP按原排序键截断尚未到达份。波形非整除duration补精确末步值，之后由实际模型保持；最后END标记按键截断未来流，但不等于九项清理已执行。整数原类型/uint32末步、独立event/sender/assertion命名空间、FAULT/REPLAY引用和T02/T05/T06负例case名称校验；case名称合法不代表实际启用或有权变异。原值/canonical/event/波形快照合计16MiB，输出窗口先验计数后才yield，默认100000/最大1000000动作，不静默截断。原三源审核暴露scenario_plan及pending，原资源/历史/协议保留。
- 本阶段追加Linux真实端口与跨工具碰撞开发验证（L-002/L-004/L-010/L-014/L-017）：同一隔离Python和编译/采样/审核代码复测；实际三个型号97绑定/105元素的C端口/数组、7/14等别名和完整快照写集合须逐一与运行时hil_contract核对，不能用冻结target_field字符串或软件spy当E2/E3。扩展环境/系统/物理I/O/视频/故障等消费者及原REPLAY资源逐项接真实写入身份/通道/目标步，再完成跨工具/链路冲突检查；明确拒绝缺绑定，不另建Linux场景协议或模拟器私有入口。
- 本阶段追加Linux模型步、周期与负载验证（L-002/L-010/L-011/L-013/L-017）：真实执行器从目标模型步驱动，证明START首份、STOP同一步排序、准确末步/保持、暂停/恢复/晚步无追赶或覆盖、全局首次TX序号及各原通道起始offset。离线iter_actions只供检查，不能直接发送或把区间跳步当运行；实际1ms±10us/80ms±1ms、20ms心跳、100ms控制有效期、20Mbit/s资源和并发总线/队列/分片负载须实测，跨机ClockSync/未同步/时钟回拨保持正式拒绝。数学无碰撞不等于实际时序、网络或模型合格。
- 本阶段追加LinuxWAIT/探针与安全验收（L-004/L-010/L-013/L-014/L-017）：共用运行状态机必须在WAIT冻结后续场景事件而不冻结模型，实际E1/E2/E3探针/时限/连续样本支持ASSERT/EVENTUALLY、超时进入失败并发起九项清理，不接受准备动作、诊断输出或模型spy冒充探针。NEGATIVE_SEND须实际已启用T02/T05/T06授权/原码及变异码/标准预期拒绝且无实际写入；REPLAY须完整资源、实际新SID/RESET/initial_inputs/轮间清队列及安全恢复。撤权/停止/到期时证明原进程树/GUI/drone/设备发送停止、消费者安全值、故障恢复/队列清理/控制释放/会话关闭，完成后才释放预约或切换真实3.3。
- 共用未完而非Linux重写：实际场景状态机/启动暂停恢复停止/全部事件handler与真实模型步、WAIT/断言/负例变异授权/九项清理、其他消费者与REPLAY完整目标扩展、原六工具当前标准授予/全局发送/生命周期/独立反馈联动、SavvyCAN/Ostinato后端、完整三模式10000repeat/64 SID真实退休及复位、工程量JSONL/TCP/视频历史执行、25API/既有控制台/Robot、实际消费者/ClockSync/持久原TXRX/发布与真实3.3均继续原共同计划。此包关闭编译/离线时间表与根完整消息碰撞缺口，不以更小离线目标替代整个方案；41责任与17未执行Linux完整保留，不勾选完整W3/M4或整体完成。
- 专项/复核与最终回归：17专项在模块/审核计划缺失时明确RED后实现，补97绑定/105元素、38416枚举交点、精确快照容量和变异整数后21专项；五种变异整数接受1.0明确RED后修，21专项11.932s、14旧波形8.775s/39旧三源34.253s通过。独立21专项11.874s、50000随机交点/10000随机截断及同一步END/容量/严格边界等探针通过，无遗留必须修复scoped问题。固定版公共入口596共用（67协议27.716s/522网关296.879s/3台账/4汇总）、34选定静态、59业务/72完成/85黄金片/800RAW、pip/编译、14逐字节源/663引用守护通过，四源码/测试hash与范围保存独立artifacts/icd_gateway/w3-15-validation.json；历史报告/14源/C/六工具不改，测试不是RT/硬件或发布证据，整体目标继续active。

### 2026-10-04 W3.16共用断言比较窗口与冻结探针定义移交

- 共用实现：assertion.py按冻结Assertion/probe_catalog落实EQ/NE/LT/LE/GT/GE/WITHIN/EVENTUALLY，numeric/bool/string明确不混用，只有WITHIN/数值EVENTUALLY使用tolerance；finite、原始类型/负零、同型号/消息/probe/target和固定数组唯一索引检查。三个型号97路径/105标量与数组元素定义得到覆盖，E2拒绝NO_PROBE。root/WAIT/ASSERT全部编译保存spec并计入原16MiB快照预算，原三源report追加计数，资源/历史/协议和14冻结源/C/六工具不改。
- 窗口规则与证据边界：期限为[start,start+timeout)显式模型步，uint32溢出拒绝；普通ASSERT不满足即MISMATCH，WAIT/EVENTUALLY允许等待并在不满足时重置连续计数。sample_sequence必须严格递增，步不可回退，poll不创造样本；同一步的新样本允许，到期值不记录不计数。默认4096/4MiB、最大1000000/64MiB，容量失败原子，drain只释放记录而不重置序号/步/连续计数/终态，公开规则/起点/模式/期限不可重赋值。本地MATCHED仍evidence_status=NOT_EVALUATED、execution_ready=false，不签PASS、不发140、不分配Header/SID/sequence、不冻结或启动模型。
- 本阶段追加Linux真实探针与标准证据开发验证（L-002/L-004/L-014/L-017）：同一编译/比较/审核代码复测，实际C消费者与三个型号97绑定/105元素接真实reader和setter/readback，Capabilities.available_probes只公布实际已实现资格，不把冻结路径匹配或软件候选值当E2。消息消费者的field_path当前只校验安全语法/消息身份，reader_path_pending明确保留；实际字段采集路径须按原消费者实现核对，不新增ICD字段。模型输入读取与E3可观测业务响应分别取证，不能用输入回显或本地比较替代业务作用。140标准Evidence不含probe value；真实采集值/原TXRX作为受控证据记录关联，不能私加线上value字段。
- 本阶段追加Linux采样新鲜度与关联开发验证（L-004/L-010/L-011/L-014/L-017）：实际采集器核验真实probe来源、标准SID/request_sequence/transaction、trace_id/payload_sha256/message/stage/model_step及当前授权，不把孤立候选值或重复缓存读算连续新样本；暂停模型时可有同一步新采集，但sample_sequence必须由真实采集器产生并严格前进。标准140/130和原收发证据须独立关联、保留失败/缺证据，不将数学MATCHED提升业务PASS。实际available_probes/reader资格、消费者path解析、原码采集与持久证据仍属同一共用后续，不单独建Linux协议或模拟器私有探针接口。
- 本阶段追加Linux模型步、WAIT与安全验收（L-002/L-010/L-011/L-013/L-014/L-017）：真实步时钟驱动半开期限，验证截止前/截止步、空样本、暂停/恢复、时钟回拨及跨机同步，不能以宿主sleep或测试耗时替代1ms±10us/80ms±1ms、20ms心跳/100ms有效期、20Mbit/s并发资源与实际队列资格。真实WAIT必须冻结后续事件但不冻结模型，持续收样/标准反馈并在超时转失败，执行九项清理和安全值/故障恢复/控制释放/会话关闭；只有实际原工具进程树/GUI/drone/设备队列停止、消费者恢复和独立证据齐全后才释放预约或切换真实3.3。本地TIMED_OUT或drain不是上述执行证明。
- 共用未完而非Linux重写：真实reader/available_probes/消费者采集路径、标准140与原TXRX关联/持久证据、实际MODEL_STEP状态机/启动暂停恢复停止/全部handler、WAIT运行阻塞/超时失败/九项清理、其他消费者与REPLAY完整目标、授权负例、原六工具当前授予/全局TX/生命周期/独立反馈/SavvyCAN/Ostinato后端、完整三模式10000repeat/64 SID真实退休/RESET/initial_inputs/轮间队列清理、工程量JSONL/TCP/视频执行、25管理API/既有控制台/Robot、实际消费者/ClockSync/激活/发布与真实3.3均继续完整原计划。本阶段关闭断言比较与定义编译缺口，不以候选数学窗口替代整个运行方案；41责任/17未执行Linux全部保留，不勾选完整W3/M4或整体完成。
- 专项/复核与最终回归：缺少Spec/Window/审核接入先RED后实现，公开配置可重赋值回归先RED后只读修正；16专项8.884s、21旧场景12.029s、14波形8.834s、39三源34.844s通过。独立16专项9.038s/21场景12.175s及精确截止/18字节记录/容量原子/drain/终态/严格类型/有限值/路径/整数精度/孤立代理项探针通过，无遗留必须修复scoped问题。固定版公共入口612共用（67协议/538网关305.372s/3台账/4汇总）及34选定静态、59/72/85/800、pip/编译、14逐字节源/663引用守护通过；五源码/测试hash与完整未完范围记录独立artifacts/icd_gateway/w3-16-validation.json。14源/C/原六工具和历史报告不改，测试不是目标RT/模型/硬件或替换验收证据，整体目标继续active。

### 2026-10-04 W3.17实际UDP原收报与标准Evidence关联移交

- 共用实现：evidence.py接现有SourceSession/UDPDispatcher/UDPSource唯一实际socket读者，保存全部14反馈的原datagram、实际peer/channel/本机monotonic收时刻，包含非法peer/CRC/超长原码；标准140独立原Reassembler重组。watch只能绑定本dispatcher首次TX前原opaque Header，保存原请求/实际PayloadCodec hash，完整实际逐片TX后才关联。SID/transaction/request_sequence/message/event/trace/hash/stage/闭模型步窗口、实际grant的probe/型号/完整group一一检查，不加端口/线上字段、不改原C/六工具/14冻结源。
- 反馈与证据边界：终态ACK后watch继续保留并实际poll，140不结束pending、不免重试、不作131续租或141commit。共享原UDP高水位/64SID/8192缓存，重复不重复接受、冲突/回退保留失败；原值类型/PACKED_LE负零、失败claim的原请求与收报保留。对端标准business_result原样保存，但correlation_matched只证明软件关联，qualification_status恒NOT_EVALUATED、execution_ready=false；现有正式接收服务尚不产生模型140，测试实际UDP peer不是合格消费者或模型。
- 本阶段追加Linux原四ETH与采集开发验证（L-002/L-011/L-014/L-017）：同一代码在原四ETH部署路径复测实际peer ACL、原码/CRC/分片乱序/组超时、140先后与ACK后继续收报、重复/冲突/缓存期限/会话退休；标准14反馈不能只采130或只按当前pending过滤。核对实际socket内核队列/网卡丢包与应用容量背压，分别保留完整原RX和真实TX，不把本机回环、记录存在或sequence关联当零丢包/E1/物理资格。SocketCAN和六工具独立反馈扩展继续原责任，不换中央UDP路径或私建Windows后端。
- 本阶段追加Linux真实探针与140 producer开发验证（L-002/L-004/L-010/L-014/L-017）：实际C/设备消费者在真实接收、setter/readback及可观测业务处产生标准E1/E2/E3；只公布实际实现available_probes，三个型号97绑定/105元素及消费者field_path须接真实reader。标准140没有probe value，真实采样值、新鲜sample_sequence、原TXRX及元数据需在受控证据包中准确关联；不能私加线上value、拿模型输入回显当E3或以远端PASS签本地资格。当前watch的event/trace是显式预期，真实运行须由既有管理/场景上下文建立同一身份，不把调用者填字符串当接收端已经知道或业务证据。
- 本阶段追加Linux当前授权、时钟与负载验证（L-004/L-010/L-011/L-013/L-014/L-017）：本批已修正解码期间租期到期/monotonic回拨误接受，匹配使用新鲜本机clock，失败原报/请求保留而不推进高水位。目标须验证到期/撤权/旧SID、原完整TX与实际模型步/ControlOwner、ACK与140异步顺序及真实ClockSync；异机mono_ns不与本机相减。1ms±10us/80ms±1ms、20ms心跳/控制100ms有效期、20Mbit/s资源和并发队列必须实测，测试耗时或原码采集不等于RT资格。
- 本阶段追加Linux容量、持久证据与安全验收（L-002/L-010/L-013/L-014/L-017）：上下文/记录共同计bytes，收报前保守预留完整UDP+最大逻辑回复+原请求/元数据和两条记录；实际配置max_records至少2，合法值1明确BUFFER_FULL且不先消费。drain只释放记录，不清watch/TX身份/高水位，需共用持久写出后显式unwatch/上下文退休及64SID完整repeat管理。证明磁盘/日志满、内核RX丢失、时钟/心跳失败、撤权/关闭时失败证据不丢；public close只脱离本地采集，九项清理、原进程树/GUI/drone/设备停止、安全值/故障恢复/控制释放/会话关闭必须真实执行后才释放预约或切换真实3.3。
- 共用未完与最终回归：真实140 producer/qualified reader/采样绑定、完整持久原TXRX包、实际MODEL_STEP状态机/所有handler/WAIT/负例/九项清理、其他消费者/REPLAY目标、原六工具授权发送/生命周期/SavvyCAN/Ostinato、三模式完整10000repeat/RESET/initial_inputs/轮间清队列、工程量JSONL/TCP/视频、25API/控制台/Robot、消费者/ClockSync/激活/发布/真实3.3仍由同一共同代码继续，非推到Linux重写。25专项15.058s、21原dispatcher13.769s/31原会话6.455s/16断言8.774s与独立25专项15.458s/租期边界复核通过，重要发现先RED/GREEN。固定版637共用（67协议27.772s/563网关321.779s/3台账/4汇总）、34静态、59/72/85/800、pip/编译/14逐字节源/663引用通过，四源码/测试hash记录独立artifacts/icd_gateway/w3-17-validation.json。41责任/17未执行Linux不删不勾，历史报告不覆盖，不勾选完整M3/M4/W3或整体目标。

### 2026-10-04 W3.18共用原始观察证据段持久化移交

- 共用实现：evidence_archive.py从同一dispatcher/session序列化owner快照当前SourceExchange/DispatchRecord/EvidenceRecord，实际TX/RX/原请求回复/失败bytes全部base64保真，uint64本机时间用规范十进制字符串，原PACKED_LE负零不重新规范化。快照完整计数量/整个JSONL及manifest字节，默认100000记录/64MiB、最大256MiB，严格拒绝bool/float限额和超限；snapshot不更新clock/sequence/transaction/lease/state，不drain或清watch，保存IO只用脱离不可变bytes，不持模型/运行owner锁。
- 持久化与资格边界：只写独占新目录，xb/fsync/逐字节读回后最后硬链接公布manifest，不覆盖旧包；fsync/readback/link失败保留未完成目录及原内存记录。读回核对完整基线/四组件、原文件hash/size、实际行/流数量、闭字段/原base64及JSON/类型范围，缺manifest/额外文件/符号链接/篡改或资格提升拒绝；os.scandir实际惰性扫描首个未知或第四项即拒绝。包始终NOT_EVALUATED/evidence_complete=false/ready=false，只保存当前保留观察段，不证明来源签名、完整运行或真实E2/E3；没有早期原socket RX不补造，远端PASS原样保存但不升格。
- 本阶段追加Linux文件系统与故障开发验证（L-002/L-003/L-014/L-015/L-017）：同版Python和同一writer/reader在实际部署文件系统验证xb/hardlink/fsync/读回、权限/符号链接/目录替换/磁盘满/配额/短写/IO错误、崩溃与掉电一致性。当前文件内容fsync不证明目录metadata持久或网络文件系统/挂载支持；Linux须核验目录同步/原子发布所需目标实现与恢复策略，不能改成覆盖旧manifest或删除失败证据获得通过。冻结baseline/组件和最终发布文件hash、实际工具/模型/环境hash必须完整收齐，未具资格不能形成发布包。
- 本阶段追加Linux非实时写盘与持续完整性开发验证（L-002/L-010/L-011/L-013/L-014/L-017）：共用持续采集器须显式协调snapshot、后台保存成功后的排空、段身份/连续计数/原RX与TX和缺证据，失败保留原队列并明确失败，不自动drain使尚未持久的记录丢失。模型线程不做编码/文件IO；证明队列/内存/磁盘背压和真实内核/设备RX丢包分别可追溯，不能拿可读包或本地dropped_feedback代替全链路零丢包。1ms±10us/80ms±1ms、20ms心跳、控制100ms有效期、20Mbit/s资源及四ETH/CANFD并发和跨机ClockSync需真实负载资格；snapshot的显式时间不是RT时钟或异机延迟证明。
- 本阶段追加Linux失败与安全证据验收（L-004/L-010/L-013/L-014/L-017）：真实消费者/140 producer/reader/available_probes及采样值关联继续实现，event/trace按实际管理运行身份建立。保存租期/撤权/时钟/传输/模型/工具失败、ACK后140、原进程树/GUI/drone/设备停止、安全值/故障恢复/队列清理/控制释放/会话关闭各自证据，只有实际九项清理完成才可释放预约或替换真实3.3。当前close/段写盘/读回不冒充上述执行，磁盘异常仍须安全停止并保留完整诊断。
- 共用未完与最终回归：多段持续writer/完整性、运行工具/模型/环境hash、断言/业务/安全结果与正式Report/25API/控制台/Robot、真实探针/采样及140、实际场景MODEL_STEP/全部handler/WAIT/授权负例/清理、三源完整回放/10000repeat/RESET/initial_inputs/轮间队列、原六工具/SavvyCAN/Ostinato实际生命周期、全部消费者/ClockSync/激活、Linux模型/设备/RT/发布与真实3.3仍按完整原计划共用开发，非另造Linux协议或Windows版本。14缺模块先RED、目录扫描两次RED/GREEN；首轮583网关334.409s的1项原守护失败因sys.platform metadata，改无分支platform.platform且原测试不动。最终20专项12.734s/25原inbox15.508s/21dispatcher13.914s及独立20专项12.731s/原守护和11类型范围/远端PASS/十次只读snapshot探针通过；固定657共用（67协议/583网关330.976s/3台账/4汇总）、34静态、59/72/85/800、pip/编译/14逐字节源/663引用通过，两源码/测试hash与失败/剩余范围保存artifacts/icd_gateway/w3-18-validation.json。41责任/17 Linux未执行不删不勾，不覆盖历史报告，不勾选完整M5/W3或整体完成。

### 2026-10-04 W3.19共用连续原始观察记录器移交

- 共用实现：evidence_recorder.py复用原三流/归档格式，单个实际非daemon线程写脱离bytes；flush不取号、不发送，poll只有实际线程终止、原段与commit逐字节读回及三流全部原对象身份/计量一致才原子回收已存前缀。写盘时新增收报保留，预约/watch/上下文/序号高水位/租期不变；三池旁路drain及旧dispatcher关闭后的新owner抢占均拒绝。独立复核发现等值对象替换可跨快照窗口取得信任，先RED后提取同锁私有snapshot helper返回原三流tuple，公共archive API与文件格式不改，三流替换均明确STATE且不部分回收。
- 多段与关闭边界：每段闭commit保存连续index、原包hash、previous SHA256、累计流计数和实际丢反馈计数；有界os.scandir扫描，不全量枚举。成对可信expected_segments/tip可检测整体末段删除；local close检查点以独占xb/fsync/readback/hardlink保存实际提交数/链尾/累计bytes/关闭快照未保存数，计入总容量，owner忙可仅重试detach不重写。close只等待原真实线程，0..30s严格有限；超时原handle/owner保留，不重启，不丢未保存内存，不执行远端停止。活动无锚链只证明已见前缀；裸关闭标记整体删除/重写与来源签名须由正式Run可信元数据和权限保护补齐，locally_closed不等于全运行完整或九项安全清理。
- 本阶段追加Linux持久性与故障开发验证（L-002/L-003/L-014/L-015/L-017）：同版Python和同一record/archive源码在实际部署文件系统验证目录同步/原子发布/硬链接/权限、配额/磁盘满/短写/IO错误/目录替换、进程崩溃及掉电恢复；失败段和close.pending必须保留可诊断，不覆盖旧包或删除残留取得通过。正式Run可信身份、外部段数/链尾及工具/模型/环境hash受保护绑定，核对删段/整锚删除/跨包拼接；当前文件fsync和本地SHA链不是目标目录持久性、来源认证或正式发布资格。
- 本阶段追加Linux持续采集与实时负载验证（L-002/L-010/L-011/L-013/L-014/L-017）：实际四ETH/CANFD与六原工具采集完整TX/RX，证明非实时writer、段轮转及应用池容量背压，分别记录内核/网卡/设备丢包与应用dropped_feedback，不能以连续commit或内存回收宣称全链路零丢包。模型RT线程不做JSON/file IO；在1ms±10us/80ms±1ms、20ms心跳/100ms控制、20Mbit/s资源及持续并发负载下测实际写盘压力、调度、关闭等待与跨机ClockSync，未达资格明确失败，不静默丢记录/降要求或另写Windows后端。
- 本阶段追加Linux失败安全与真实证据验收（L-004/L-010/L-013/L-014/L-017）：磁盘/内存/传输/租期/时钟/原工具失败时由完整共用运行状态机进入失败并执行九项清理，保留真实进程树/GUI/drone/设备发送停止、安全值/故障恢复/队列清理/控制释放/会话关闭证据，全部完成才释放预约或切换真实3.3。真实140 producer/qualified reader/available_probes、采样新鲜度与event/trace关联继续实现；原观察段/本地关闭/远端PASS始终NOT_EVALUATED、ready=false、evidence_complete=false，不冒充E2/E3或远端已停止。
- 共用未完与最终回归：正式Run身份与可信终点保护、工具/模型/环境hash/断言安全结果/完整Report、25API/既有控制台/Robot、真实采样及140、实际MODEL_STEP状态机/全部handler/WAIT/授权负例/九项清理、三源全部回放/10000repeat/真实SID退休/RESET/initial_inputs/轮间队列、原六工具授权TX/反馈/生命周期/SavvyCAN/Ostinato、完整消费者/ClockSync/激活/发布和真实3.3继续同一共同代码，不全部推到Linux重写。16初始RED后实现，补链尾/关闭/owner边界及独立等值替换RED/GREEN；根最终70证据测试48.408s、21dispatcher13.812s/31source-session6.418s及独立25专项20.308s/20archive13.805s/8原guard与探针通过，无剩余重要scoped发现。固定682共用（67协议27.576s/608网关352.521s/3台账/4汇总）、34选定静态、59/72/85/800、pip/编译/14逐字节源/663引用通过，六源码/测试hash及剩余范围保存artifacts/icd_gateway/w3-19-validation.json。41责任/17未执行Linux完整保留，不改冻结源/C/原六工具、不覆盖历史报告、不勾选完整M5/W3或整体完成。

### 2026-10-05 W3.20原场景共用运行控制器移交

- 最新执行顺序：原有第三阶段仍未完成，先完成原W3三类资源/场景/回放/六工具共用开发，再恢复新增自生数据配置入口；W4管理API/控制台和W5 Linux/模型/实物暂缓但不删除责任。提前启动的生成器草案已保存在docs/superpowers/drafts/2026-10-05-generated-data，不在运行包/测试发现路径，最后19项17通过2失败，未交付；不把该草案当原W3完成，原41责任/17未执行Linux完整保留。
- 共用实现：scenario_execution.py直接接受原ScenarioPlan，重新按同一原契约编译校核不可变资源，拒绝伪造时间表；无明确ScenarioDriver立即TARGET_MISSING，整份原link/授权/时钟/probe/根断言预检必须先于执行。按原MODEL_STEP/priority/event_id惰性启动原事件完整值，十事件内容/六link/REPLAY策略/负例/清理不改；不自己转UDP替代六工具。每条根断言独立原handle与半开期限，WAIT只阻塞该场景后续事件；绝对步漏过TIMEOUT，不改原at_step、不补发或猜测模型时钟。普通ASSERT/根断言/在途未完成时END不提前清理。
- 运行和失败边界：默认64在途/4096记录/16MiB，根断言计入在途容量；全有限运行记录/快照预算在启动前拒绝超限，不把Schema最多10000根断言或百万流当当前可同时执行容量。原handle/根assertion_id/具体begin与poll失败和终态关联保留，非ICD/未知词汇/非string错误码一律归一RESOURCE；运行首个失败与后续真实清理错误分开记录。单owner及回调重入拒绝；不重试begin、不回滚实际取号。只有同一原cleanup handle累计九项完成回执才LOCAL_STOPPED，未齐则明确SAFETY/FAILED且pending_cleanup；完成后原在途只记LOCAL_CANCELLED，不冒充远端应用/已停。所有结果qualification=NOT_EVALUATED、execution_ready=false、safety_verified=false，测试driver不是生产工具/模型。
- 本阶段追加Linux原工具/实际授权开发验证（L-002/L-003/L-004/L-011/L-013/L-017）：生产ScenarioDriver仍须同一共用模块接原CANT/CUTIL/SAVVY/CANREPLAY/ETHGEN/ETHREPLAY预约与可信builder、真实当前SID/角色/ControlOwner/target_step及完整原TX/RX；SocketCAN/vcan/原can-utils/canplayer/tcpreplay及SavvyCAN/Ostinato后端和进程树只在Linux/目标验证，不开发Windows SDK/另造转发链。安装事实、构包、prepared、handler COMPLETE或本机子进程结束均不作为工具/实体资格；此项不是将尚未实现的共用driver全部移交Linux重写。
- 本阶段追加Linux模型时钟/断言/失败清理验证（L-004/L-010/L-011/L-013/L-014/L-017）：接真实模型步/冻结步与ClockSync/Status、140 producer/qualified readers/available_probes和新样本/event/trace/原请求关联，根和事件断言只有真实值/阶段证明才执行。实测WAIT不冻结模型、同一步屏障、半开到期、未采样/缺能力/撤权/租期/磁盘/工具错误，随后九项真实停止/故障恢复/安全值/队列清理/控制释放/会话关闭各有证据，全部通过才释放预约或切换真实3.3。LOCAL_STOPPED与九字段handler回执不证明实机安全；缺模型/probe/C消费者仍明确不可用。
- 原W3共同后续：生产driver全部handler、原三回放模式及工程量输入实际发送、10000repeat与真实新SID/RESET/initial_inputs/轮间队列、暂停恢复/条件单步复位、负例授权及must_not_apply、真实探针/ClockSync、持续原始证据终点与完整运行Report仍须完成。与原W4/W5/Robot/目标消费者/发布/真实3.3责任保持区分；当前本包不关闭完整M3/M4/W3，不提前开发新增发生器。
- 验证与移交：18缺模块先RED，根/事件断言启动混淆、WAIT到期/本地取消、原handle/具体失败身份/独立根期限/清理词汇与错误归属、非string码边界均RED/GREEN；最终32专项16.996s及独立32专项16.913s/原21场景12.430s通过，无剩余重要scoped发现。第一次全量为最后类型守护修复主动中止，不计通过；固定最终714共用（67协议/640网关373.325s/3台账/4汇总）、34选定静态、59/72/85/800、pip/编译/14逐字节源/663引用通过。新旧11源码/测试hash和剩余事项保存artifacts/icd_gateway/w3-20-validation.json；未改14冻结源、C或原六工具代码，不勾选完整阶段或Linux门禁。

### 2026-10-05 W3.21原Scapy共用二层发送链移交

- 顺序与范围：原有W3仍未完整完成，本次补原ETHGEN/Scapy实际发送，不启动新增自生数据配置入口；原六工具/14冻结源/标准ICD/C/41责任/17未执行Linux门禁完整保留。ScapySource默认只使用原conf.L2socket，缺后端明确TARGET_MISSING，不回退普通UDP或引入Windows SDK。真实SimpleSocket+socketpair是本机测试帧汇，不是实体网卡、汽车以太网或替代后端。
- 共用实现：UDPSource原两处发送提取为_emit_packet，默认行为不变；Scapy继承原标准会话/反馈/重组/重试/20Mbit资源节流。原本簿opaque ETHGEN/SEND单接口预约、对应四ETH/MAC/IPv4端点、真实当前grant/SID/角色/模型/已公布能力/租期与实际已分配Header或原拥有UDP bytes校验落实。SourceSession只增加实际operation线程归属、默认closed拒绝的内部互斥选项和单份最近分配关联；Scapy直接发送/读取/准备/丢弃/close由原owner串行，不允许绕过dispatcher或其他线程会话操作。预约仍不等于线上授权，不重开socket或自动获取新预约。
- 发送与关闭证据：发送前预留完整Ether/IP/UDP和原ICD bytes，默认4096条/16MiB，最大65536条/128MiB，严格整数容量且不驱逐历史。完整写/短写/异常/发送后到期分别保留真实已知字节数、原完整尝试和本机时间，未定义返回计数不当成功；Scapy调用成功也不证明网卡送出、3.6接收或应用。L2 drain经原owner锁，附有持续recorder不旁路清除；原三流存储仍只保存原UDP，不伪称已完整持久化L2。close永久停止本地transport，保留L2记录/原授权/预约，ins/outs/pcap_fd失败保留同一实际句柄重试，成功pcap close不重复；不释放预约或制造九项远端清理完成。
- 本阶段追加Linux原Scapy后端开发验证（L-002/L-003/L-011/L-013/L-017）：同一ScapySource/conf.L2socket在实际Linux/目标Python与原Scapy版本上验证raw权限、实际backend、接口/IP/MAC/四ETH正式channel映射、MTU/校验和/真实L2抓包和完整标准UDP反馈。原conf后端选择由原Scapy库承担，不新增宿主分支；本机帧汇或失败注入pcap句柄不证明真实libpcap可用。实体汽车以太网驱动/转接/PHY/多通道与SocketCAN仍在目标门禁，不能以普通以太网或库已安装提升资格。
- 本阶段追加Linux授权、负载与清理验证（L-004/L-010/L-011/L-013/L-014/L-017）：证明实际当前SID/ControlOwner/target_step、源与目标模型时钟、标准全部反馈、当前租期/撤权/旧事务、原TX/RX及真实3.6 ingress；接收不等于应用，不公布尚未实现capability/probe。20Mbit资源100ms组期限、20ms心跳/100ms控制、1ms正负10us及80ms正负1ms和并发采集/磁盘负载须实测。本地完整send计数不证明物理无丢包或RT；源/dispatcher/transport关闭顺序、实际句柄失败/网卡离线/网络或租期故障、原工具进程树和九项安全清理须有真实证据，全部通过后才释放预约或切换真实3.3。
- 共用未完与验证：Scapy实际L2段还须接共用完整Run/持续持久报告，不能全部推给Linux重写；原CAN工具发送/原GUI生命周期、生产ScenarioDriver全handler、三回放模式/工程量/完整repeat与RESET/initial_inputs、暂停恢复/条件单步复位、负例must_not_apply、真实探针/ClockSync和完整证据终点继续原W3。11缺模块RED后实现，独立所有权旁路/事务空洞/pcap close失败重试四RED关闭，成功close重复再RED修复；最终28专项16.399s、31原会话6.512s及独立26专项15.114s/31会话6.481s通过，无剩余重要scoped发现。固定742共用（67协议/668网关386.893s/3台账/4汇总）、34选定静态、59/72/85/800向量、14逐字节源/663引用、pip/编译守护通过；十源码/测试hash与实际工具安装状态保存artifacts/icd_gateway/w3-21-validation.json。原41责任/17未执行Linux不删不勾，不关闭完整W3/里程碑或整体目标。

### 2026-10-05 W3.22原CANT共用CAN发送与标准反馈移交

- 顺序与范围：继续原W3的cantools→python-can→SocketCAN链，新增自生数据配置入口仍搁置；W4/W5暂缓而非删项。原六工具/14冻结源/ICD/C/41责任/17未执行Linux完整保留。默认只打开原SocketCAN Bus(fd=True, ignore_config=True)，缺后端TARGET_MISSING，不新增Windows SDK、模拟器私有协议或UDP替代CAN。显式VirtualBus原库peer只计软件结果，不是生产后端或3.6模型。
- 共用实现：CANSignalSender消费同一builder真实拥有的CANT/SEND预约、CANFD_n/interface、SourceSession原grant/SID/Header和cantools完整组，11类CAN TO_36及130/131标准反馈按原FD64/BRS/11bitID/20ms重组编码与关联。原ChannelReservations持有有界native owner，同预约/接口/实际bus只能一名反馈持有者，撤销token不释放仍开启后端；原bus实际关闭成功才退休本地owner，预约和远端安全另行证明。SourceSession保留首次CAN尝试sequence和心跳transaction高水位，替换builder/发送器、drain/discard/retire/close不重置，不增加引用池；131无request_sequence，同SID心跳事务不得复用以免迟到反馈错误续租。
- 原始证据与失败：发送前预留完整原组/上下文及FAILED槽，默认4096记录/16MiB/64pending，不驱逐原记录。逐帧当前授予/角色/型号/能力/租期发前发后复核，整组20ms期限不改；native send返回None只表示库调用完成，不证明物理送达/3.6应用，异常结果未知且不自动重试。原TX/RX flags/DLC/data/实际channel/本机时间与timestamp IEEE位有界不可变保存，native接收异常、超时和发前/发后失败保留原request_json，异常时间戳拒绝但保留收到的wire bytes。阻塞recv后/重组前重新校核授权，仅完整唯一关联的新鲜131在验收时从原TX起算续租；缓存取走不二次续租。保留其他在途反馈、原Source全局feedback去重/高水位，不伪造APPLIED/CONSUMED。
- 生命周期与未完：原session/builder/发送器串行，不能绕过dispatcher/持续recorder；本地drain不清上下文或序号，原pending plan从builder/source discard后可凭保留对象身份retire，等值伪造拒绝。close失败保留同一实际bus，重试原periodic tasks、BCM及raw完整清理，不只close raw socket；不执行九项远端清理、不释放SEND预约。CAN原记录仍须接共用持续Run/Report；生产ScenarioDriver全handler、六原工具/GUI/进程树、三模式全回放/工程量/10000repeat与真实新SID/RESET/initial_inputs/轮间队列、暂停恢复/条件单步复位、负例must_not_apply、真实MODEL_STEP/ClockSync/probe/消费者/证据终点继续原W3共同开发，不全推给Linux重写。
- 本阶段追加Linux原CAN链与授权开发验证（L-002/L-003/L-004/L-011/L-013/L-017）：同一SocketCAN源码验证实际内核/vcan/权限、can0..can3与四CANFD映射、nominal/data bitrate、FD64/BRS/11bitID、错误帧/ESI/bus-off及设备队列，vcan也不算物理CANFD资格。实际3.6 CAN ingress、标准grant/SID/role/ControlOwner/型号/target_step与130/131必须同源关联，证明撤权/到期/延迟旧Status/跨链feedback序号及重复拒绝；不提升未公布capability，不把库返回成功当E2/E3。原can-utils/canplayer/SavvyCAN和Ethernet工具完整生命周期保持原分支，不替换工具或契约。
- 本阶段追加Linux负载、持久证据与失败安全验证（L-004/L-010/L-011/L-013/L-014/L-017）：20ms CAN整组、20ms心跳/100ms控制、1ms正负10us/80ms正负1ms、资源20Mbit/s及四通道/采集/磁盘/跨机ClockSync并发实测，当前VirtualBus耗时不作RT证据。原TX/RX/native元数据接持续Run真实持久化，区分内核/设备与应用丢包；总线断开/bus-off/关闭periodic或BCM/raw失败、租期/权限/磁盘/模型故障需保留实际句柄和进程树并停止全部发送、执行九项清理及安全值，全部真实证据齐备才释放预约或切换3.3。native owner本地释放、retire、NOT_EVALUATED/ready=false均不证明实机安全。
- 验证与移交：原12缺模块RED后实现；部分组发前失败漏记、第二sender重复/吞反馈、缓存131延迟续租、native RX错误漏证、重组前授权、异常timestamp、periodic/BCM/raw关闭重试、discard后退休及builder替换重置sequence/心跳事务均RED/GREEN修正。最后两项发现后首轮完整回归主动中止exit1，不计通过；最终41专项29.416s、31会话7.795s、22原准备5.184s、10工具5.787s及独立11重点回归通过，无剩余重要scoped发现。固定最终783共用（67协议/709网关422.425s/3台账/4汇总）、34选定静态、59/72/85/800向量、14逐字节源/663引用、pip/编译守护通过，12源码/测试hash前后完全一致。实际命令/安装事实/边界保存artifacts/icd_gateway/w3-22-validation.json，已有历史记录不得覆盖；原41责任/17未执行Linux不删不勾，不关闭完整W3/里程碑或整体目标。

### 2026-10-05 W3.23原标准模型步观察移交

- 执行顺序：继续原W3，新增自生数据配置入口保持搁置；W4/W5暂缓不删项。共用model_clock.py通过ObservedModelClock只读取实际SourceSession的标准131 Status，原串行UDP、UDPDispatcher及CANT/python-can三处在完整验证和原owner锁内保存同一有界最新观察。保留SID/型号、完整原Heartbeat与Status bytes、正式transport/channel和源时钟域起止/期限；不改变SourceExchange/原三流archive格式，不按本机墙钟或80ms Status推算1ms模型步，不发送、取号或drain。
- 有效期与生命周期：从原Heartbeat首次开始加冻结240ms计算Status保守截止，不从到达或读取时刻续期；当前真实grant/租期/原会话owner必须仍有效。每个新鲜同SID Status提升模型步高水位，包含较旧请求交错回包；较旧请求不得替换较新缓存或改变其期限，未读样本、drain和更换reader不允许回退。RESET/RESUME实际关联的Lifecycle APPLIED/OK及已公布consumer.Lifecycle probe使旧SID观察失效；按原冻结NEW_SESSION_RESTORE_INITIAL语义，必须先退休旧会话、实际新SessionOpen授予及新Status，不虚构同SID复位epoch。失败/仅RECEIVED/未公布probe不能宣称已复位。
- 迟到反馈守护：SourceSession新增跨UDP/CAN共用、常量内存的Heartbeat发送尝试SID/事务高水位，超时/失败/ACK/本地drain/更换dispatcher或builder均不能重用同SID已尝试事务并给旧131重新计时。串行和dispatcher实际入口在计数提交前拒绝已尝试事务；原CAN仅准备/allocate不消耗尝试资格、原sender发送时仍再校核；dispatcher同一pending临时未发送仅claim一次。其他消息原事务分组和六工具通路不改。
- 本阶段追加Linux时钟与真实目标开发验证（L-002/L-004/L-010/L-011/L-013/L-014/L-017）：同一源码对实际3.6标准131及Lifecycle消费者、真实SID/授予/角色/模型、ClockSync33/142和接收端feedback序列进行验证，保留独立原TX/RX与目标时钟测量。Status80ms报告不能证明1ms正负10us模型步或80ms正负1ms系统周期；实际跨机offset/漂移、时间回拨、迟到/丢失/重排、20ms心跳/100ms控制/资源20Mbit并发须实测。不能把本机LocalClock、协议peer、VirtualBus或NOT_EVALUATED观察升级为同步/物理/安全/E2/E3资格；真实模型时钟来源与生产driver继续共同开发，不另造Windows后端。
- 本阶段追加Linux复位、恢复和停止验证（L-003/L-004/L-011/L-013/L-014/L-017）：验证实际RESET恢复initial_inputs、RESUME保留状态但清队列，九项清理、旧SID撤销及真实新grant/probe/新Status完整顺序；晚到旧Status、同事务重用、跨链重排及工具/网卡/总线/模型故障不得恢复旧会话时钟或释放未停止预约。原CAN/Scapy持续证据和可信Run终点仍须完成；本地时钟失效、库关闭或新SID观察并不证明设备安全或真实3.3可替换。
- 验证与边界：14缺模块用例先RED；测试夹具初始化/重复发包/重组时钟域和提前拒绝报文准备兼容性在最终版前修正。两项独立发现（交错Status遗漏高水位、超时事务重用给旧Status改期）分别真实UDP RED/GREEN关闭；临时未发送重复claim亦先RED后修正。最终23新专项+2未改原CAN兼容回归共25项17.752s通过，独立两实际UDP复现及最终7重点6.754s通过，无剩余重要scoped问题。固定版完整806共用（67协议/732网关467.151s/3台账/4汇总）、34选定静态、59/72/85/800向量、14逐字节源/663引用、pip/编译通过，五源码/测试hash前后相同；报告artifacts/icd_gateway/w3-23-validation.json。原41责任/17未执行Linux不删不勾；生产ScenarioDriver、完整回放/重复/initial_inputs/暂停恢复/负例/qualified readers/ClockSync、六工具完整联动和完整Run/Report仍属原W3未完，不提前开发发生器，不关闭完整阶段或整体目标。

### 2026-10-05 W3.24原CAN与Ethernet共享会话协调移交

- 共用实现：NativeToolCoordinator连接一名原UDP/Scapy dispatcher和一至四名原CANT发送器，共用实际标准SessionGranted、SID、输入序号、心跳事务高水位和预约簿。原CAN仍由cantools/python-can/SocketCAN发送，不把CAN字节转发到UDP，不新增Windows后端或私有ICD。只在真实新鲜grant且尚未分配输入时绑定；来源准备不发送，原UDP已开始分组的重试保留原码，较新跨链首次尝试之后的旧未开始分组明确STATE。
- 本地所有权：原dispatcher、native sender、builder和SourceSession锁全部保持；委托只接受当前唯一scope对象及一次公开入口，旧copy_context、回调重入和其他线程均不能复用。关闭失败保留原句柄和永久closing状态，原UDP公开操作也不得继续发送；即使dispatcher先关闭，native coordinator解绑前不能替换dispatcher或释放SourceSession所有权。实际本地总线关闭后仍保留SEND预约、原会话与远端九项清理责任。丢弃计划必须匹配实际sender预约和通道，发送上下文须先退休，不能由共用builder另一通道误删。
- 本阶段追加Linux原链路与授权验证（L-002/L-003/L-004/L-011/L-013/L-017）：同一协调模块接原SocketCAN/vcan与Scapy实际接口，验证四CANFD映射、一个当前Ethernet dispatcher、跨链标准grant/角色/型号/ControlOwner/target_step、共享首次尝试序号及130/131反馈。验证旧未发送分组拒绝、原UDP重试、迟到Status/撤权/租期/跨链重排及源与接收端高水位。显式VirtualBus和本地UDP协议peer只证明库级软件行为，不代表物理CANFD、汽车以太网或正式3.6消费者可用；不提升未公布能力。
- 本阶段追加Linux负载与失败清理验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：原CAN整组20ms、心跳20ms、控制100ms、模型1ms正负10us和系统80ms正负1ms、资源20Mbit及四CAN/以太网/采集/磁盘并发须实测。核验关闭periodic/BCM/raw失败、网卡离线/bus-off、资源满或租期失效时所有发送停止，同句柄可重试且实际清理后才释放对应所有权；保留标准远端九项清理与设备安全值证据，不把本地shutdown或STATE守护当安全验收。
- 共用未完：当前原ObservationRecorder尚未保存native CAN/L2全部流，协调模块明确拒绝附有该recorder的CAN操作，不旁路证据或宣称完整Run。生产ScenarioDriver全部handler、六工具GUI/回放生命周期、三模式完整回放与repeat/新SID/RESET/initial_inputs、暂停恢复/条件单步复位、负例must_not_apply、qualified readers/ClockSync及完整Run/Report继续原W3共同开发；多个Ethernet dispatcher协调亦未实现。原41责任和17未执行Linux门禁保持，新增自生数据入口仍搁置，W4/W5暂缓而非删除。
- 验证：原11缺模块RED后实现；原五复核问题及源所有权提前释放、跨通道误删分别RED/GREEN关闭。最终23专项28.155s通过；独立跨sender旧scope实际复现拒绝STATE，最终三边界3.655s通过，无剩余重要scoped发现。固定最终829共用（67协议27.398s/755网关468.652s/3台账/4汇总）、34选定静态、59/72/85/800向量、pip/编译及14逐字节源/663引用通过，八源码/测试hash前后相同；日志artifacts/icd_gateway/w3-24-full-regression.log和报告artifacts/icd_gateway/w3-24-validation.json。此前并发专项一次10ms反馈TIMEOUT随后原默认单项重跑通过，最终测试显式0.2s收报等待，未改变运行默认或冻结20ms重组/TX期限；不将软件耗时升级RT资格。已有记录不得删除覆盖，不关闭完整W3或整体目标。

### 2026-10-05 W3.25原场景CAN与Scapy发送组件移交

- 共用实现：NativeScenarioActions消费原ScenarioPlan的SEND/FAULT/WAVEFORM/PERIODIC_START/PERIODIC_SAMPLE/PERIODIC_STOP，按原CANT或ETHGEN通路发送完整Stimulus、实际标准SID/全局序号与明确target_step，不转发CAN至UDP、不新增线上字段或Windows后端。Scapy-only可用实际原dispatcher，不强制创建无关CAN后端；缺原分支返回TARGET_MISSING，不能以普通UDP替代ETHGEN、以CANT替代CUTIL/SAVVY或回放工具。原时钟/ControlOwner授权由完整生产driver承担，本组件不自行生成模型时钟或同步资格。
- 预检与收尾：选中ProtocolParser须声明每条待发CAN消息且原cantools字节等于冻结wire；纯CAN场景亦核对原Scapy/CAN同预约簿。非阻塞CAN空轮询不记录TIMEOUT，原阻塞接口/20ms整组期限不变。UDP取消必须使用原Header对象且只取消所属在途组；标准终态与本地回收失败分别留证，COMPLETE不等于E2/E3。关闭失败、正常关闭或新dispatcher接管后，仅原sender可按原锁回收原上下文，不能重新发送、清空证据、回滚序号或改变新owner。PERIODIC_STOP只结束本计划已编译流，不冒称停止未启动的硬件周期任务或完成九项远端清理。
- 失败准备保留：实际Source输入已分配后工具准备异常，以原锁内的FailedToolPreparation保留精确输入、Header和请求字节；该对象不是成功LiveToolInput，不扫描共享输入猜测归属、不重发begin。失败上下文与成功计划共享count/byte上限，伪造/跨sender/重复回收拒绝，撤权后仍允许专属本地清理；handler明确pending_local_cleanup直至实际回收完成。
- 本阶段追加Linux原工具与目标开发验证（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同一组件接实际SocketCAN与Scapy backend，校核原四CANFD/四ETH部署映射、完整场景值与原码、真实grant/SID/型号/角色/ControlOwner/目标步及130/131反馈；检验所有原工具缺失、撤权、租期、反馈重排/丢失、bus-off/网卡离线和跨链预约互斥。实际C模型消费者与真实探针独立验证，不能把VirtualBus、本机帧汇或协议peer的APPLIED声称算实际应用。
- 本阶段追加Linux周期、停止与证据验证（L-004/L-010/L-011/L-013/L-014/L-017）：实测20ms CAN整组/心跳、100ms控制、1ms正负10us模型步、80ms正负1ms系统周期及资源20Mbit/s并发负载；核对原记录容量、磁盘背压、关闭失败/接管/后分配异常的同句柄回收与新owner不受扰动。原periodic/BCM/GUI/进程树和九项远端安全清理必须取得各自真实结果，全部实际停止前不释放SEND预约。CAN/L2连续证据须接共同Run/Report，局部动作记录不代替完整运行包。
- 共用未完与顺序：完整生产ScenarioDriver、WAIT/ASSERT真实reader与根断言、授权负例must_not_apply、六工具/GUI/回放完整生命周期、三回放模式与repeat/新SID/RESET/initial_inputs/轮间队列、暂停恢复/条件单步复位、九项清理、ClockSync和完整Run/Report仍须原W3共同开发，不全部移交Linux重写。三类输入的解析/编译或两种native发送不等于三链端到端完成；新增自生数据配置入口保持搁置，W4/W5暂缓不是删除。
- 验证：初始17缺模块RED，发送/失败路径实现后转GREEN；review复现所选协议漏预检、纯CAN预约簿遗漏、closing/detached清理受阻，以及后分配异常丢失回收身份，均先RED后修正。最终28场景发送36.654s、27共享协调33.066s专项通过，独立七重点全部exit0且无剩余重要scoped发现。固定版862共用（67协议27.525s/788网关498.227s/3台账/4汇总）、34选定静态、59/72/85/800向量、pip/编译与14逐字节源/663引用通过，十源码/测试hash前后相同。日志artifacts/icd_gateway/w3-25-full-regression.log和报告artifacts/icd_gateway/w3-25-validation.json保存实际命令/范围；原41责任/17未执行Linux保持，已有记录不得删除覆盖，不关闭完整W3或整体目标。

### 2026-10-05 W3.26 Task 1原场景控制器与native发送集成移交

- 共用实现：OriginalScenarioDriver连接原ScenarioExecution与实际NativeScenarioActions，后者只承接CANT/ETHGEN的原native事件，仍保留完整ScenarioPlan；CUTIL/SAVVY/Ostinato/回放及WAIT/ASSERT/NEGATIVE_SEND不改写成普通native发送。全计划服务与native预检先于发送，当前实际标准Status提供model_step，目标审批独立且执行原ahead/暂停规则；同Source/SID、有限历史、精确非空provider/wrapper句柄、begin不自动重试落实。ScenarioRuntimeServices仍为明确的抽象边界，无默认成功实现；测试服务不是实际生产消费者。
- 清理与身份：本地stop失败也发起原远端清理，有限源单调时钟期限不依赖停止后的模型步推进；已验证的分批九字段累计，已验证远端终态缓存，后续只恢复原本地资源。超时/失败历史不升级成功，回调前后不采纳新Source/SID。实际SourceSession.close在原锁内保留被关闭SID，本地ABANDONED/closed只允许原handle交付回执，必须累计九项完整COMPLETE才接受合法同步或异步关闭；close本身不证明九项安全。原接口、线上字段、C核心、六工具及单代码保持，不新增Windows后端。
- 本任务追加Linux实际集成开发验证（L-002/L-003/L-004/L-010/L-011/L-013/L-014/L-017）：同一driver接实际SocketCAN/Scapy及六原工具，验证标准grant/当前SID/角色/型号/ControlOwner与100ms控制租约、真实模型Status/ClockSync、目标步与实际APPLIED/CONSUMED探针。缺工具/reader/能力必须预检失败，不将帧汇、VirtualBus、协议peer或测试getter提升到真实模型、实体、安全或RT资格。所有权切换、晚到旧回执、新SID、正常关闭和异常恢复要分别留证。
- 本任务追加Linux停止、负载与证据验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：九项模型/设备/视频/周期/回放/控制/队列/会话实际结果必须齐备；验证本地回收延迟期间远端已经close_session时不重复轮询/发begin，不清历史、不误判新SID、不提前释放SEND预约。实测1ms正负10us模型步、80ms正负1ms系统周期、20ms心跳/CAN整组、100ms控制及资源20Mbit/s并发和磁盘背压；原TX/RX、真实采样和失败上下文接完整持续Run/Report，不以172库级测试代替目标门禁。
- 共用未完：W3.26 Tasks 2至4继续实际生产授权/生命周期/qualified reader、根及事件WAIT/ASSERT、全负例must_not_apply、三种完整回放与repeat/新SID/RESET/initial_inputs/轮间队列、原六工具GUI与进程树、九项实际清理、native连续持久流/完整Run与Report和PROTOCOL/SCENARIO/HISTORY三源验收。这些共同逻辑不全部推给Linux重写；只有原后端、真实目标与实机测量在Linux验证。新增自生数据配置入口保持搁置，W4/W5暂缓不是删除，原完整W3仍未完成。
- 验证与边界：初始缺driver及清理/身份/类型失败先RED后修正；六个复核发现（分批回执、远端终态重查、callback替换身份、空句柄、合法原SID关闭、同步清理完成）全部RED/GREEN关闭，最终独立只读复核无剩余重要scoped发现。固定四源码/测试hash下31 driver 54.761s、32原控制器16.766s、28 native动作36.035s、31会话6.401s、27协调33.318s、23时钟16.118s共172针对性测试通过，14逐字节源/663引用、59/72/85/800向量、pip/编译通过。报告artifacts/icd_gateway/w3-26-task1-validation.json保存命令、固定hash和非资格边界；本次未重跑完整scripts/test_icd_runtime.py，历史862仅属于W3.25，不声称当前全量或三链验收通过。原41责任/17未执行Linux不删不勾，已有记录不得删除覆盖，不关闭完整阶段或整体目标。

### 2026-10-05 W3.26 Task 2控制租约观察进度移交

- 共用实现：ObservedControlLease接原SourceSession的标准反馈入口，保留真实SID/型号、源/角色/lane/mode、ControlOwner与最新有效控制命令原请求/回执、通道/传输和原始收发时刻。100ms从原首次TX起算，匹配控制的VALIDATED/APPLIED有效回执才续期；Heartbeat、环境/故障、RECEIVED、普通失败、过期、重复、错误lane或未公布consumer不续期。新授予与安全生命周期实际尝试即撤销旧观察，不增加线上字段或Windows后端。
- 撤权交错修复：有限source intent由实际首次6 TX维护；权限失败、abandon及任何新鲜相关131的换源/安全/非PAUSED RUNNING均清空。撤销不依赖lease已经建立、Heartbeat请求比6晚或模型步cache更新，原模型时钟缓存规则不改；旧6 ACK和普通安全解除心跳不能恢复旧权限，必须重新标准授予。四项实际UDP交错回归先RED后GREEN，原记录/高水位/计数/容量不重置，CAN与UDP共用同一观察。
- 本进度追加Linux实际权限与消费者验证（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同代码接SocketCAN/Scapy及实际3.6消费者/consumer.ControlOwner，验证唯一配置生产者SID/型号/角色/lane、真实安全值与队列清理及100ms授予/续期。标准Status没有唯一控制者SID，source字符串和协议peer的APPLIED不能代替实际生产者reader；该reader和实际模型getter接入仍须共同开发，只有原Linux后端/目标应用效果在Linux验证。
- 本进度追加Linux交错、安全与时序验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：实测跨CAN/ETH反馈、待授予期间安全保护、早发Heartbeat晚到、缓存未更新的鲜活安全告警、重复/丢失/到期/撤权及真实重授予。核对控制100ms与心跳20ms、真实模型步及并发负载，确认撤权后停止发送且真实设备进入安全值。原VirtualBus/UDP测试peer不是硬件、C应用、安全或RT资格；本机libpcap缺失不能提升原Scapy后端资格。
- 共用未完与范围：Task 2实际配置生产者读取、目标审批、根/事件WAIT与ASSERT采样、生命周期和九项实际清理继续开发；Task 3完整三模式回放/负例/六工具生命周期，Task 4 native连续持久化/完整Run与Report和三源软件验收仍未完成，不整体移交Linux重写。新增自生数据入口继续搁置；W4/W5暂缓不是删项，41责任与17未执行Linux门禁保持。
- 验证：最终28专项20.471s通过，独立有界只读复核确认原P1关闭、无新的确定重要scoped发现。固定五源码/测试hash下921共用（67协议27.442s/847网关577.233s/3台账/4汇总）、14逐字节源/663引用、离线59/72/85/800、pip和编译通过；实际完整日志与限制保存在artifacts/icd_gateway/w3-26-task2-regression.log及w3-26-task2-progress.json。本次未重跑选定旧静态34项，不复用旧结果作为当前证据；不关闭Task 2、完整W3或整体目标，已有记录不得删除覆盖。

### 2026-10-06 W3.26 Task 2实际Status断言进度移交

- 共用实现：StatusObservationReader接原SourceSession实际owner反馈入口，保存每条新鲜相关131及原2请求、SID/型号/步/序号、传输/通道/首次TX和RX时刻，不只使用最新模型步缓存。原计数/字节容量有界且不驱逐，溢出永久保留前缀并明确失败，不吞原transport RX。StatusScenarioAssertions对原计划重新编译校验，E1 Status的12冻结字段、八算子和根/事件WAIT/ASSERT经原AssertionWindow执行；只计begin后独立序号，完整读取中间失败，保留原句柄和原ActionProgress，跨身份/过期/错步/缺公布探针拒绝。原ScenarioRuntimeServices继承实际断言转接，缺读取器不会默认成功，仍没有完整生产服务。
- 容量修正：WAIT三条未匹配样本加一个句柄占满四条历史后，第二根断言曾可绕过记录总容量。新增回归先RED，再在创建窗口/句柄与更新begun/bytes之前校验记录加句柄总量，GREEN证明拒绝后前缀、句柄、begun、字节和Source序号不变。限定只读复核确认原P2关闭，未发现新的确定重要scoped问题；不将局部复核作为W3整体验收。
- 本进度追加Linux实际采样与消费者验证（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同一reader/handler在实际SocketCAN和Scapy/3.6标准Status生产者上验证已公布consumer.Status、原SID/型号、反馈来源/通道、首TX期限、序号去重以及多条采样完整顺序。真实模型内部字段还须共同开发实际getter和140的identity/stage/hash/outcome关联，E2/E3不从ACK、Status字符串或协议peer制造值；Status字段不覆盖全部模型根探针。VirtualBus与UDP测试peer只证明库级共同软件行为，不能提升真实C消费者、实体后端或安全资格。
- 本进度追加Linux负载与失败验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：实测连续样本/中间不匹配、迟到旧样本、跨链反馈、重授予/撤权、过期、断言模型步半开期限、字节与记录耗尽及磁盘背压，溢出后不得驱逐历史再升级为通过。实测模型1ms正负10us、系统80ms正负1ms、心跳20ms/CAN整组20ms及控制100ms，在原负载下核对采样对输入与反馈的影响。实际停止/探针注销/队列和九项清理独立留证；reader.close只解除本地采样挂接，不证明模型或硬件安全。
- 共用未完与顺序：实际唯一配置生产者读取和目标审批、模型getter/全部根与事件断言/E2 E3证据关联、生命周期/九项清理继续Task 2；三模式完整回放/负例must_not_apply/六工具生命周期继续Task 3，native持续Run/Report与PROTOCOL/SCENARIO/HISTORY三源验收继续Task 4。这些共同逻辑不全部推给Linux开发。三源端到端仍0/3，原W3不关闭，新自生数据配置保持搁置，W4/W5暂缓不是删除；14源/ICD/C/原六工具/单代码/41责任/17未执行门禁完整保留，不另开Windows版本。
- 验证：固定四源码/测试hash下189针对性测试通过（28断言34.894s、16窗口8.826s、31会话6.482s、23时钟16.255s、28控制20.728s、31driver54.376s、32控制器17.055s），14逐字节源/663引用、离线59/72/85/800、pip与编译通过。实际日志artifacts/icd_gateway/w3-26-task2-assertion-regression.log和进度报告w3-26-task2-assertions-progress.json保存当前范围；本次未重跑完整scripts/test_icd_runtime.py和旧静态34项，不复用历史921或862作为当前全量证据。既有记录不得删除覆盖，不勾Linux完成、不关闭Task 2/W3/整体目标。

### 2026-10-06 W3.26 Task 2实际配置生产者解析进度移交

- 共用实现：SessionRegistry.registered_controller按完整可信配置身份解析实际唯一、未到期且确实取得CONTROLLER的SID，保留身份/实际角色/不可变链路/nonce/原会话期限/序号。配置角色不代替请求实际获授角色；STIMULUS不会因6请求取得生产权；多个活跃CONTROLLER SID明确CONTROL_OWNER，不按最新nonce猜选。external_control_owner以实际6 admission和STIMULUS选择者校验同run/vehicle/scenario/model/version，继续原源/lane/PAUSED/target及100ms义务；NONE撤销不需要live producer，内部控制器缺实际输出reader仍TARGET_MISSING。标准14源、线上ICD、原C/六工具与单代码保持，不新增Windows后端。
- 只读修正：旧require_admitted仍执行原队列维护；新增observe_admitted共享原摘要/queued/terminal校验，并核对selector自身半开会话期限及原缓存期限，查询只推进receiver时钟下限，不清会话/缓存、取消资源任务、驱逐或续期。RegisteredController重建tuple及冻结PeerBinding，旧SourceGrant可接受list也不暴露内部可变别名。两处P2原反例先RED后GREEN，限定只读复核关闭；新测试还覆盖原始receive时间、已claim、缓存/selector到期、跨模型和全部三模型外部lane。
- 本进度追加Linux实际授权接入验证（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同一receiver串行owner和实际SocketCAN/Scapy/3.6部署授予上核对真实SID/完整身份/CONTROLLER角色及链路绑定，发起6的STIMULUS与生产者独立解析。实际已应用RunConfigure声明源、ModelView/model getter、控制单写者及设备输出必须与解析结果一致；安全值和队列清理真正完成后才授予，模型控制100ms独立于1000ms会话/20ms心跳，不能把注册快照当已应用ControlOwner或续期证明。共同reader/应用状态/安全动作服务仍须开发，不全部移交Linux重写。
- 本进度追加Linux失效、时序与清理验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：验证唯一生产者同时存在多个SID、重授予/撤权/新nonce、到期半开边界、并发读取需实际owner串行、跨链晚回/身份上下文不符及已终态原请求。授权解析期间不得维护其他会话/资源/队列，实际receiver维护仍按原回收顺序留证；执行前必须再次读取实际模型和生产者，不复用过期决策。实测1ms正负10us/80ms正负1ms、20ms CAN/心跳和100ms控制负载及完整九项安全停止，不把规则测试或本机UDP当实体、安全或RT资格。
- 共用未完与范围：实际应用控制状态/配置/model getter和源目标批准、全部根/事件断言与E2/E3真实140关联、生命周期/九项清理继续Task 2；三种完整回放/repeat/新SID/RESET/initial_inputs/轮间队列、负例must_not_apply及六工具生命周期继续Task 3，native持续Run/Report和PROTOCOL/SCENARIO/HISTORY三源软件验收继续Task 4。原W3未完成，三源端到端0/3；新自生数据入口仍搁置，W4/W5暂缓不是删除，41责任/17未执行Linux门禁保持。
- 验证：固定三源码/测试hash的十个非空套件184针对性测试通过（29解析15.085s、13registry17.928s、23语义11.815s、25queue33.492s、9receiver4.859s、20worker12.904s、14UDP11.241s、27retirement14.626s、15resource exchange7.993s、9resource UDP5.939s），14逐字节源/663引用、离线59/72/85/800、pip和编译通过。初次选择test_config.py没有文件，NO TESTS RAN并非通过且中止该批，不计任何测试；随后真实test_udp.py和其余三个相关套件已在同一源码上顺序通过，原日志保留不删。证据artifacts/icd_gateway/w3-26-task2-producer-regression.log及w3-26-task2-producer-progress.json；未重跑完整scripts/test_icd_runtime.py或旧静态34项，历史921/189等不算当前全量。既有记录不得删除覆盖，不勾Linux完成，不关闭Task 2/W3/整体目标。

### 2026-10-06 W3.26 Task 4原CAN与Scapy持续观测归档进度移交

- 共用实现：原ObservationArchive新增明确SEGMENT_2，闭合SOURCE/DISPATCH/INBOX/CAN/L2五流；原默认SEGMENT_1保持三流和原格式。CANObservation/L2Transmission保存原始字节、失败、接口/通道/帧标志、十进制uint64时刻、带类型的原CAN channel及IEEE754时间戳位串；负零和失败NaN原位串不被JSON归一化。实际原dispatcher/coordinator/一至四CAN sender/builder/source/Scapy L2锁下有限快照，不取号、续期或drain，不开启另一个设备或改线上ICD。
- 持续记录：原ObservationRecorder通过显式native=True接上述真实owner，复用同一个有界后台线程写盘，新增CHAIN_LINK_2/CLOSE_2且拒绝与旧格式混用。发送在写盘期间继续；持久化读回、hash/count/link、全部流身份及字节核算成功后，按每个原CAN sender分别回收保存前缀。新增记录、原反馈context、pending/预约、输入计数、高水位和租期不变；CAN与L2侧drain被记录器拒绝。失败保留内存原记录和原工作句柄；本地close报告未保存五流计数，不自动补flush、不停止工具、不证明九项远端清理。原后端正常关闭后仍可保存原记录。
- 修正边界：替换coordinator.senders曾可漏掉已有CAN记录，现校验创建时原sender/builder/binding；记录期间替换binding亦在TX前拒绝。多CAN汇总行按sender分组，不是单一追加流：第一个sender追加新行会插在其他sender的已保存行之前，不能用汇总tuple前缀误判损坏。改为每个sender独立身份/字节校验后原子回收，四个原VirtualBus sender反例先RED后GREEN，限定只读复核关闭；不放宽真正的原记录替换或核算失配。
- 本进度追加Linux原通道和采集验证（L-002/L-003/L-011/L-013/L-017）：使用同一Python实现和实际SocketCAN/Scapy后端，以最多四CAN/原以太网通道核对发送、接收、失败、完整FD组/原Ethernet bytes、library timestamp位串与本机时钟来源。验证原can-utils/SavvyCAN/Ostinato/canplayer/tcpreplay观察来源如何接入同一完整运行证据，不能因CANT/Scapy库可归档就把另外四分支标为可执行或完整。无libpcap、无SocketCAN/BCM/CMSG_SPACE的当前Windows宿主只执行库/帧sink软件验证，不安装Windows替代后端、不提升实体资格。
- 本进度追加Linux落盘与负载验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：实际目标文件系统验证独占目录、fsync/硬链接发布/读回、磁盘耗尽、权限变化、崩溃和损坏段保留、后台线程退出/超时重试、总字节/段容量、CAN及L2缓冲背压与原pending保留；确认原实时线程不做文件I/O。实测1ms正负10us模型、80ms正负1ms系统、20ms心跳/CAN组和100ms控制租约在持续写盘/原负载下的实际指标，不以单元时间或读回hash证明安全、签名、整运行完整或RT。
- 共用未完与范围：本批完成五类原观测的共用持续落盘路径，但scenario/service/action/cleanup流、完整Run/Report终态锚点与三源软件验收仍须同代码接入；不能把local close或记录段当完整报告。Task 2实际配置/model getter/模型应用/目标授权/生命周期/九项实际清理和Task 3完整回放/负例/六工具服务保持原开发责任，不能全部推给Linux重写。PROTOCOL/SCENARIO/HISTORY端到端仍0/3，原W3不关闭，新增自生数据配置继续搁置；W4/W5暂缓不是删除，14冻结源/原C/六工具/单代码/41责任与17未执行Linux门禁保持。
- 验证：固定最终八个源码/测试hash下298相关测试在十二非空套件顺序通过（11 native archive、12 native recorder、20旧archive、25旧recorder、27 coordinator、41 CAN、28 Scapy、31 source、21 dispatcher、23 live input、31 driver、28 native actions）；3台账/4汇总、14逐字节源/663引用、离线59/72/85/800、pip与编译亦通过。实际日志artifacts/icd_gateway/w3-26-task4-native-recording-regression.log最终验证自第367行开始；此前296项属于多sender修正前历史，不计最终源码证据。进度及hash见w3-26-task4-native-recording-progress.json；本次未跑完整scripts/test_icd_runtime.py或旧静态34项。唯一台账原80435 UTF16字符的规范化历史前缀SHA256为71310a48335e8df32d8662617afb3af06bc59d267276ab67e0d2c6ffa8a4f241，逐字保持；已有记录不得删除覆盖，不勾Linux完成，不关闭完整W3/整体目标。

### 2026-10-06 W3.26 Task 4原场景记录接线进度移交

- 共用实现：原ObservationRecorder通过native_actions/execution显式绑定同计划NativeScenarioActions及ScenarioExecution/OriginalScenarioDriver，原锁顺序下将PLAN/NATIVE_ACTION/SCENARIO加入原五流，明确SEGMENT/CHAIN_LINK/CLOSE_3；旧格式1/2保持。原计划JSON与源身份字节、型号/SID只保存一次，原动作/驱动句柄、Header、请求/反馈字节、进度/错误/清理字段可读回。原有限动作和控制器历史不drain，身份游标只保存未落盘行，不破坏原句柄和行索引。
- 回收和清理边界：原ETH动作尚未消费的终态反馈必须保留，读回成功仍poll=False，同一job和owner不变；close明确STATE，实际动作poll后才允许同一job原子回收并移动原动作记录锚点。落盘后下一原动作继续使用原时间表，不重置输入计数/预约/租期，不以存盘成功制造动作完成。清理PENDING新增字段保存PROGRESS，九次增量容量在运行前预约，重复poll不追加，失败终态仍保留已完成九项字段的真实已观察集合。记录期间计划对象被替换即在取号/TX前拒绝，不接受等值新对象。
- 本进度追加Linux实际场景与原链路验证（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同一实现接实际SocketCAN/Scapy以及其余原工具运行服务，核对原场景/型号/SID/控制权/模型步和实际反馈关联；验证终态已到但场景尚未消费时的磁盘背压、后续动作、工具停止与最终会话关闭，不用协议peer或测试服务COMPLETE替代真实模型应用和九项安全清理。模型getter、完整生产服务与服务/断言证据仍须共同开发，原目标后端/实体效果留Linux验证。
- 本进度追加Linux落盘与实时验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：验证实际模型步推进、原动作/驱动/工具/source锁竞争、慢盘/容量/中止/崩溃恢复、原反馈消费等待与安全停止不能死锁；核对段读回和完整Run/Report终态锚点，不能将本地close或八流归档升格为完整运行报告。实测1ms正负10us模型、80ms正负1ms系统、20ms心跳/CAN及100ms控制在场景执行与持续落盘负载下的指标。
- 共用未完与范围：完整生产运行服务、模型字段/E2/E3读取、实际控制/生命周期/九项清理、完整回放/负例/六工具运行、服务/断言记录与完整Run/Report及三源软件验收保持原任务。端到端0/3，Task 2/3/4和原W3不关闭，新增自生数据配置继续搁置，W4/W5暂缓不是删除；14冻结源/原C/六工具/单代码/41责任与17未执行Linux门禁保持。本次追加前原82846 UTF16字符规范化历史前缀SHA256为f332816f4daaa6f49133187466176bf9b41748f10082d58c1250aa52380dc9b0，必须逐字保持；测试证据在本次顺序回归完成后追加，不复用旧298结果声称新源码通过。
- 最终验证：固定七个源码/测试hash下322相关测试在十三非空套件顺序通过（13场景记录、34控制器、31 driver、28 native动作、11 native archive、12 native recorder、20旧archive、25旧recorder、27协调、41 CAN、28 Scapy、31 source、21 dispatch）。必填型号/事件标识null问题经一次限定只读复核指出，两个子反例RED、严格必填校验GREEN；不追加复核循环。日志artifacts/icd_gateway/w3-26-task4-scenario-recording-regression.log从第398行起才是最终源码验证，前321项保留为修正前历史；hash、命令及非资格边界见w3-26-task4-scenario-recording-progress.json。14逐字节源/663引用、离线59/72/85/800、pip和编译通过；原82846字符历史前缀hash仍一致，41责任/17未执行/0完成Linux保持。本次没有完整runtime或旧静态34项回归，不关闭完整阶段或整体目标，已有记录不得删除覆盖。

### 2026-10-06 W3.26 Task 3原回放进程接线进度移交

- 共用实现：replay_process.py复用原PreparedReplay/ReplayExporter/ToolCommandPlan/ChannelReservations及ProcessSupervisor，精确三模式、canplayer/tcpreplay原参数、通道offset和持久文件读回。明确ReplayProcessAuthority必须绑定原实际SourceSession，缺服务在写文件/创建进程之前TARGET_MISSING；source当前SID/型号/grant/角色/消息能力及实际authority在启动前和运行中复核。原单调epoch只调通道偏移，不估模型步，错过窗口LATE不追赶。保留一至四子进程原句柄/有限双流/时间和错误，启动不重试，失败继续停止其他子进程，不回退native、不释放预约；LOCAL_EXITED不是TX或APPLIED。
- 收尾修正：一次限定只读复核发现停止丢失ProcessSupervisor返回的错误、Popen失败无PID却永久阻止close两处P2。实际supervisor超时及模拟Popen权限拒绝反例先RED，停止错误保留FAILED/STOP_FAILED、只等待真正创建的子进程/reader后GREEN；错误和原owner不丢弃，重复close不追加同一停止失败。停止前尚未start不能再启动、authority普通异常归冻结RESOURCE也有回归。成功协调测试明确为替身，Python接受原canplayer参数的失败/超时不算原工具资格，不增加复核循环。
- 本进度追加Linux原回放执行验证（L-002/L-003/L-004/L-007/L-009/L-010/L-011/L-013/L-017）：用真实原canplayer/tcpreplay和目标SocketCAN/网卡验证文件/manifest读回、绝对可执行文件版本/hash/权限、完整FD组/原以太网报文、actual端点与一至四通道起始窗口。actual authority需证明每包标准授予/分配、全局序号/首TX及完整组序、模型/控制目标和真实feedback，不以进程退出0或工具安装代替。多进程offset不自动保证跨通道逐包全局顺序，必须观测并按冻结规则拒绝或实现原工具可证明的调度；repeat须实际RESET、新SID、initial_inputs及轮间队列清理，不能重复本地start冒充。
- 本进度追加Linux停止与时序验证（L-003/L-004/L-007/L-009/L-010/L-011/L-013/L-014/L-017）：实际权限拒绝/创建失败/自然退出/超时/输出超限、设备断开/租期到期/撤权/文件变化、多个子进程及后代持管道时保留真实句柄并停止所有拥有者。验证实际进程树、周期发送、探针、视频、控制、队列和会话九项清理后才释放SEND预约；本地close无PID仅表示未创建direct child，不是远端安全。实测目标文件系统、跨机ClockSync、1ms正负10us/80ms正负1ms、20ms CAN组/心跳、100ms控制和资源并发，迟到不能追赶发包或用宿主sleep证明RT。
- 共用未完与范围：完整生产运行服务/authority、真实模型getter/控制/生命周期/九项清理、逐包TX/反馈/repeat/RESET/initial_inputs、负例must_not_apply、六工具服务、服务/断言证据和完整Run/Report与三源验收继续原Task 2/3/4，不全部移交Linux重写。原W3不关闭，PROTOCOL/SCENARIO/HISTORY端到端0/3，新自生数据配置仍待原任务完成，W4/W5暂缓不是删除；14冻结源/ICD/原C/六工具/单代码/41责任与17未执行门禁保持。工期粗估集中追加整体计划Sequence And Workload，不新建第二待办或修改门禁；Linux30-55人日和总59-105人日均不含环境/设备/真实3.3等待，不是固定交期。
- 验证：固定七个源码/测试hash下210相关测试在十个非空套件顺序通过（18回放进程、19原进程、17命令、26回放、19导出、24捕获、23历史、10工具、31源、23模型步）；3台账/4契约、14逐字节源/663引用、离线59/72/85/800、pip/编译通过。本次没有完整scripts/test_icd_runtime.py或旧静态34项回归。证据artifacts/icd_gateway/w3-26-task3-replay-process-regression.log及w3-26-task3-replay-process-progress.json。追加前原84771 UTF16字符规范化历史前缀SHA256为3e234e205045c7a3d9f3a474a544b3f7519b7669ac56ce2daf2840c4ded13d67，必须逐字保持；不勾Linux完成，不关闭完整阶段或整体目标，已有记录不得删除覆盖。

### 2026-10-06 W3.26 Task 4原Status断言证据与第三条交接移交

- 共用实现：原ObservationRecorder显式assertions绑定同计划真实StatusScenarioAssertions/StatusObservationReader，以SEGMENT/CHAIN_LINK/CLOSE_4扩展十二流，新增STATUS_SAMPLE/STATUS_FAILURE/ASSERTION/ASSERTION_LIFECYCLE，旧格式1/2/3保持。采样原request/reply bytes、SID/型号/步/sequence/通道与uint64时刻、比较原handle/断言ID、STARTED/RESULT原spec/mode/sequence/错误有闭合读回校验；首个BUFFER_FULL保留实际sequence/time，不隐藏原RX。
- 生命周期和记录边界：每个handle两条元数据begin前预留，只有实际poll终态才追加RESULT且不重复。原样本/比较/handle历史不drain，原handler锁先于native/source，实际所有者/计划/contract/reader/source/service绑定固定，快照不调用运行回调、不取号或续期。游标只在读回校验后保存原身份前缀，后台写盘期间新采样/比较保留；close检查十二未保存计数，不制造终态或远端清理。记录期间等值计划替换、live记录器挂接时reader.close静默停采均先RED再GREEN，后者必须先detach记录器，原source正常关闭后仍可归档尾部。
- 本进度追加Linux实际采样与模型验证（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同代码连接实际SocketCAN/Scapy/正式3.6 Status producer，核对原SID/型号/真实模型步、十二冻结Status字段、全部八比较、连续采样/重复/过期/溢出与全部根/事件断言。实际模型root getter/E2/E3/140关联仍须实现并以目标证据证明，不能将当前协议peer、VirtualBus、frame sink或E1 Status替代模型应用/安全/全部断言；原ICD/原C/六工具分支不改。
- 本进度追加Linux文件系统与负载验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：验证原handler/native/source锁竞争、慢盘/权限/耗尽/崩溃/篡改、同worker失败恢复、identity prefix与尾部不丢、实际生产停止/九项清理在采样写盘并行时无死锁；核对十二流与完整Run/Report锚点。实测1ms正负10us模型、80ms正负1ms系统、20ms心跳/CAN与100ms控制租约负载指标，不以读回hash/单元测试时间或local close证明RT/完整报告。
- 最新用户责任调整：本轮完成后本线程只继续PROTOCOL/SCENARIO及必需共同ICD/接入/授权/目标读取/反馈/清理/报告；HISTORY第三条由别人接手。保留第三条全部已完成源码、测试、资源、方案、验证JSON及日志，已有记录不得删除覆盖，不回滚不升级结论。第三条后续完整回放/逐包TX/repeat/RESET/新SID/initial_inputs/canplayer/tcpreplay/目标验证由接手人员推进；历史台账/41责任/17 Linux门禁不删不勾，涉及共同职责的门禁仍由双方提供对应证据。
- 交接查阅：整体计划“2026-10-06 最新开发责任调整”、原W3.26 Task 3、此台账W3.5/W3.6/W3.7/W3.10/W3.12与原Task 3移交，artifacts/icd_gateway/w3-26-task3-replay-process-progress.json和同名regression.log原位保留。SCENARIO REPLAY事件和冻结契约不删除/跳过/改native，等待第三方实际服务接既有边界，缺服务明确TARGET_MISSING。当前负责两链验收0/2；整体三源历史验收0/3，移交不是通过或整体完成。
- 共用未完：实际配置/model getter/模型应用/控制目标/生命周期/九项清理、非Status断言、前两条需要的负例must_not_apply及原CUTIL/SAVVY/Ostinato服务、完整Run/Report与前两条端到端仍须共同开发，不全部推给Linux重写。原W3/Tasks 2/3/4与整体目标不关闭，新增自生数据配置仍等待原任务完成，W4/W5暂缓不是删除；旧单人工期属于交接前全范围，不作为本线程新范围承诺。
- 本批固定源验证：七个源码/测试hash在最终十八个非空套件430项中不变（13新增记录/28原断言/16窗口/31源/31driver/34控制器/28原动作/28控制租约/13原场景记录/11native archive/12native recorder/20旧archive/25旧recorder/27协调/41 CAN/28 Scapy/21dispatch/23model clock）。不存在的test_control_observation.py命令NO TESTS RAN中止批次，原日志保留、不计通过；真实test_control_lease.py及其余套件随后顺序通过，不重启或改生产源码。独立复核因额度未执行，无复核通过结论；根代理检查并闭合上述反例，不追加复核循环。日志w3-26-task4-assertion-recording-regression.log与进度JSON集中保存，未跑完整scripts/test_icd_runtime.py或旧静态34项。
- 追加前原86953 UTF16字符规范化历史前缀SHA256为e259a3fb1a3e230aba3a02cd9da799a033d028df57651352ff11adb83ff5b89c，必须逐字保持；41责任/17未执行/0完成Linux保持。本轮无第三条源码/测试/历史报告改动，留存hash由本轮进度JSON记录；冻结/台账/依赖/编译最终守护在本批记录后执行并追加结果。
- 最终守护：本批追加后3台账/4契约测试、14逐字节冻结源/663引用、59消息/72传输/85黄金片/800 RAW视频片离线、pip与compileall均已在当前源码通过。原历史前缀、第三条13源码/测试与7历史报告/log的留存hash在最终进度JSON发布前后再次核验；未完成的真实目标/整报告和端到端门禁不提升。

### 2026-10-06 W3.26 Task 3前两条负例报文构造进度移交

- 共用实现：negative.py按同一冻结Event/Stimulus、原SourceSession及其当前拥有的PreparedSourceInput构造九种NEGATIVE_SEND变异。显式distinct T02/T05/T06配置、原身份/grant/工具介质、原合法完整帧组、严格路径/类型、非空截断与非no-op校验均保留；输出不可变原码/改后码、event/header/payload及有限字节核算。构造本身不取sequence/transaction、不TX、不续期、不制造authorized/execution_ready或资格。聚合运行预约与实际preflight仍须在原输入分配之前完成，不能以此参数替代正式用例/运行授权。
- 适用性：JSON允许唯一对象/数组整体目标的替换/删除和末级新键；PACKED_LE只修改既有定长字段/明确数组叶及原f64偏移，删除/新增字段名明确UNSUPPORTED。F64_BITS准确保存八字节小端NaN/Infinity/负零，不转非法JSON；JSON F64_BITS明确UNSUPPORTED。payload/header修改重分片并按原CANFD/UDP布局重算CRC，只有CRC_XOR改首帧校验字节、TRUNCATE裁末帧且故意不修CRC/声明长度；不新增ICD编码或放宽正常WireCodec。
- 本进度追加Linux前两条实际发送验证（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同代码接实际SocketCAN/cantools/python-can、can-utils、SavvyCAN、Ostinato/Scapy原分支，证明正式用例allowlist/运行授权、角色/SID/目标步/控制来源及模型probe在取号/TX前有效。逐项验证九种适用变异的真实原工具TX、完整帧组/通道/全局序号、原码与改后码证据、标准反馈和原请求关联；不新增Windows后端或以测试UnitPeer声明的能力代替实际Capabilities/模型消费者。
- 本进度追加Linux拒绝与未写入验证（L-003/L-004/L-010/L-011/L-013/L-017）：真实模型getter/写入探针覆盖must_not_apply、异步/迟到/重复/撤权/过期和错误关联；没有APPLIED/ACK不等于没有模型写入。当前实际Receiver对超范围payload在UDP/CANFD admission前返回FAILED/SCHEMA，但CRC解码直接抛CRC、无关联ACK，须按冻结拒绝/观测边界解决并取得实际目标证据，不能虚构反馈或按本地异常算负例通过。未具备完整接收拒绝关联与no-write证据的用例不得发送，所有九项实际停止/清理保持原要求。
- 共用未完：实际启用用例/运行授权、model-step/control/原目标getters、全部root/event断言E2/E3、生命周期/九项清理、负例原工具运行服务/拒绝关联、服务观测和完整Run/Report仍须开发，不全部转交Linux重写。目标设备/原工具/权限/时序/安全与RT资格留Linux，包括1ms正负10us、80ms正负1ms、20ms心跳/CAN组及100ms控制负载验证；普通单元时间/VirtualBus/本机UDP不得替代。原W3 Tasks 2/3/4保持未完成，新自生数据配置仍等待原任务完成，W4/W5暂缓不是删除。
- 第三条边界：本批不修改HISTORY/capture/replay/export/process或其测试/历史报告；13源码/测试与7报告/log留存hash和上一批记录一致，原历史结论不提升。SCENARIO REPLAY事件保留并等第三方实际服务，缺服务TARGET_MISSING、不skip/不native回退。当前负责两链0/2、整体三源0/3，41责任/17未执行/0完成Linux保持，第三条移交不代表已验收。
- 验证：固定六源码/测试hash在九个非空套件顺序通过165项（19负例、31会话、23工具输入、21场景、9接收、17协议、12wire、21重组、12payload）。unhashable授权项和JSON整体目标反例RED/GREEN；一次限定只读复核无重要发现，提出的负零/精确字节边界补测已通过，原输入discard后拒绝亦覆盖。不追加复核循环，不复用历史430项声称全量；本次未跑完整scripts/test_icd_runtime.py或旧静态34项。证据集中artifacts/icd_gateway/w3-26-task3-negative-preparation-progress.json及regression.log；原日志223行，SHA256 dd9626e1c112e6dd121bdbe8d95ef5baaba3ae755bb79c9a7201635b946de681。
- 追加前原89787 UTF16字符规范化历史前缀SHA256为427efe373c6c747546f896098cb6cc9d83dd3a7d484af01a809b9bddab41ff78，必须逐字保持；已有记录不得删除覆盖。不关闭整体目标或完整阶段，冻结/台账/依赖/编译守护在本次追加后执行，实际结果写入本批进度JSON。

### 2026-10-06 W3.26 Task 2前两条标准Heartbeat/Status响应接线移交

- 共用实现：原Receiver显式status_service绑定同一contract/registry的ModelStatusService及强制ModelStatusBackend，按原2/131接口返回十二字段完整快照；CLI/default仍没有模型后端，不制造模型状态。不可变sample保留完整身份/payload bytes及采样/截止uint64时刻，服务记录保留原请求、入口/实际完成时刻、原返回快照、回复或错误；有限record/byte额度在实际read之前预约，不自动丢弃历史。仅声明已安装的2与consumer.Status，不提升其他模型/初始化/替换/通道资格。
- 时效与所有者：合法原admission、完整身份、精确类型、240ms快照有效性、同SID模型步/采样时刻非倒退和当前授予在读后复核；时钟与receiver同一单调域，不能相减跨机未同步值。正常/异常后端都观察真实完成时刻，反馈缓存用完成时刻，读后grant过期无Status/无旧SID ACK；已返回快照在拒绝前保留。原retry回原反馈不重采/续租，直接重调用拒绝；替换原后端/registry/receiver及读中close在admission/删除之前拒绝。close保留原记录，仅本地停止服务，不关闭外部后端或证明安全。
- 本进度追加Linux真实读取后端（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同代码接原C/Simulink实际一致快照、已应用run/config/model/场景与源身份、模型步/lifecycle/phase/control source/safety、last_applied_sequence/receive_queue_depth/missed_deadline/received/rejected/applied/consumed实际计数。现有main_rt的sequence/lifecycle/control_arbiter/FlightState和UDP状态须核对对应语义，不能把旧receipt.accepted/effective_sequence或model_get_output静态ABI当完整Status；无权威phase/计数/队列/安全字段明确TARGET_MISSING，禁止补零/TAKEOFF等默认。实际SessionOpened.receiver_step/epoch需接真实读者后再正式发布，不把接口原点0当真实模型起始证明。
- 本进度追加Linux时效/反馈与负载（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：验证真实SocketCAN与原以太网2/131路径、身份/模型/跨通道事务、慢读/读异常/读取期间租约到期、半开有效期、重复/乱序/模型RESET新SID、反馈计数器耗尽和有界证据背压。原80ms系统发布调度/正负1ms、20ms心跳/CAN组、1ms模型正负10us与100ms控制在实际后端/并发负载下验证；当前请求响应适配不等于该调度/RT资格。取得同机或批准ClockSync实际时刻来源，不能把测试controlled clock当目标同步。
- 共用未完：完整生产运行服务的实际配置/控制目标/getters、非Status根/事件断言E2/E3/140、生命周期/九项真实清理、前两条负例must_not_apply/原工具TX及标准拒绝关联、此服务历史与完整Run/Report持久化、两链端到端继续原Tasks 2/3/4，不全部移交Linux重写。新自生数据配置仍等待原任务完成，W4/W5暂缓不是删除；当前两链0/2、整体0/3，41责任/17未执行/0完成Linux不提升。
- 第三条保留：HISTORY/capture/replay/export/process及其测试/报告/log不修改，13源码/测试和7历史记录按上一批hash守护原位保留；第三方继续回放实现，SCENARIO REPLAY边界不删、不skip、不native回退。共享Receiver的Status扩展不替换第三条工具/参数或改其历史结论。
- 验证与复核：固定七源码/测试hash下十四非空套件338项通过（19新服务、9receiver、13registry、14UDP、9resource UDP、20worker、27retirement、31source、23clock、28assertions、28control lease、31driver、19negative与完整runtime67）。一次限定只读复核指出异常出口完成时间遗漏、迟到sample丢失两处P2；具体反例RED/GREEN，修正后19专项及最终固定源回归通过，不追加复核循环。真实Receiver/UDP/source/reader是软件实现路径，模型读取后端为明确替身，不能升格真实模型资格。本次未运行完整scripts/test_icd_runtime.py全gateway或旧静态34项；日志428行SHA256 688e59e62ecc2186d9c3af210e02d77b3e5a0eb95b4a3ca7bba5d4d4ef820058，证据集中artifacts/icd_gateway/w3-26-task2-status-service-progress.json及regression.log。
- 追加前原92087 UTF16字符规范化历史前缀SHA256为837602be54af41074a5d0f4d387ac824d2adb2e4b63f5802513cd228f611bb91，必须逐字保持；已有记录不得删除覆盖。后续冻结/台账/依赖/编译及第三条留存守护实际结果写本批JSON，不勾未执行Linux、不关闭原W3/完整任务或整体目标。

### 2026-10-06 W3.26 Task 2前两条开会话实际步号与本轮收尾移交

- 共用实现：已安装支持模型的ModelStatusBackend时，原Receiver先preview_open核对身份/角色/nonce/原缓存/容量，不分配新SID；preview仍运行原admission维护，不称纯只读。新开会话在有限证据预约后读完整不可变快照，按同一Status身份/类型/240ms/实际完成时刻规则验证，再复核原开会话条件并分配SID。129的receiver_step与Header target_step来自快照；分配/缓存/租约以实际完成时刻为准，Source原首TX保守租约不改。开会话快照种下同SID步号/采样时间下界；模型时钟断言仍须新鲜131，129不是完整初始化或RESET证据。
- 错误与重试：原开会话cache回原129，不重采样/分配/续租；完整字段、上下文、时效、读取失败及证据额度不足不授予SID。实际尝试失败的逻辑开会话保留原请求/返回sample/入口与完成时刻/错误，再试同一请求不重读后端，改正后发新nonce。专项反例证明pending资源占满retry缓存时原逻辑留下SID，以及payload字段循环覆盖失败key导致原EXPIRED变STATE；两处均RED后修正GREEN。preview与实际accept在新SID分配前都检查不可驱逐的pending缓存，默认无service路径也保留这项必要失败原子性修正，正常旧行为不变。
- Linux追加（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同一代码实现真实C/Simulink完整一致getter，核对开会话身份/模型步/采样时刻/已应用lifecycle、phase、control、安全和计数，实际RESET/新SID/旧会话撤销/模型epoch与初始化顺序。必须读完整实际字段后才正式发布129；接口原点0、宿主时钟、旧receipt、静态model_get_output ABI或测试替身不能作为证明。真实2/131及129在SocketCAN/以太网、原同步域、慢读/异常/过期/并发负载/容量背压/计数器耗尽下验证，原80ms发布与RT指标仍须实际调度，不由此同步读取适配推定通过。
- 本线程后续：只推进PROTOCOL与SCENARIO及必要的共同授权/配置/模型getter/控制目标、生命周期/九项实际清理、非Status断言/E2/E3、负例真实发送/拒绝/must_not_apply、原CUTIL/SAVVY/Ostinato服务、服务证据持久化与完整Run/Report及前两条端到端；不整体推给Linux重写。新自生数据配置仍待原任务完成，W4/W5暂缓不是删项。当前负责两链0/2、整体三源0/3，原Tasks 2/3/4/W3保持未完，41责任/17未执行/0完成Linux不提升。
- 第三条交接：HISTORY/capture/replay/export/process、canplayer/tcpreplay及其已完成代码、测试、资源、方案、JSON/log原位保留，不删除、不回滚、不改写历史结论。本批13源码/测试与7历史记录哈希和上一批一致；第三条后续由接手人员开发，本线程不扩展回放实现。SCENARIO REPLAY事件/冻结字段/服务边界不删不skip不native回退，第三方未提供实际服务仍TARGET_MISSING。查阅整体计划“最新开发责任调整”、原W3.26 Task 3、本台账历史W3.5/6/7/10/12与Task 3及artifacts/icd_gateway/w3-26-task3-replay-process-progress.json/log。
- 验证：固定四源码/测试hash下十四非空套件348项通过（29服务、9receiver、13registry、14UDP、9resource UDP、20worker、27retirement、31source、23clock、28assertions、28control lease、31driver、19negative、完整runtime67）；一次限定只读复核无新的重要发现。真实UDP/source/reader用于验证标准公共路径，但模型后端为明确替身，不升格真实模型资格。本次未跑完整scripts/test_icd_runtime.py全gateway或旧静态34项，不复用历史结果；证据artifacts/icd_gateway/w3-26-task2-opening-step-progress.json和424行regression.log，日志SHA256 e937ba451959db9317115480a161a8333d78d9a222c54a5b35e102956d1848c0。
- 追加前原94614 UTF16字符规范化历史前缀SHA256 ec4926eb4c9eecafd955e985cc7106e7ab10a4a8bc1b1d9d9bbcb9cf14c4b4b7，必须逐字保持；已有记录不得删除覆盖。冻结/台账/依赖/编译及第三条留存守护的实际结果在本批追加后执行，写本批JSON；不勾未执行Linux或关闭整体目标。

### 2026-10-06 W3.26 Task 4当前源码整体回归记录

- 实际验证：scripts/test_icd_runtime.py完整执行67协议库、1021网关、3台账、4接口汇总测试；另执行test_static_contract.py的20项、test_quadrotor_model_contract.py的7项、test_parameter_registry_static.py的2项、test_generic_contract_templates.py的5项，共1129项/八个非空套件全部exit0，不复用旧921/338/348结果。冻结14源/663引用与离线59消息/72传输/85黄金片/800视频片、pip check、compileall通过；实际日志1194行，SHA256 fcdc42456012111fc72794e5c8b97a08949a3be098fee60b99b21526a2139d53，证据artifacts/icd_gateway/w3-26-current-source-full-regression-progress.json及同系列log。
- 固定源与归属：运行前后150个共同源码/测试/C/MATLAB文件hash完全相同；第三条13源码/测试和7历史报告/log仍与原留存hash一致，只执行兼容性回归，不改实现、不覆盖旧结论。HISTORY后续开发仍由别人接手，本线程只继续PROTOCOL/SCENARIO及必要共同逻辑。既有第三条资源、方案、记录仍原位保留，SCENARIO REPLAY边界不删、不skip、不native回退；第三方服务缺失仍TARGET_MISSING。
- Linux门禁不提升：本批没有新增平台实现，没有C编译/真实模型/原Linux工具/实体/RT/安全/真实3.3替换证据。L-001至L-017原责任与目标验证要求保持，41责任/17未执行/0完成Linux不删不勾。静态C/MATLAB检查不是模型ABI行为或实机资格，VirtualBus/软件peer/model double不是实体设备。
- 共用后续仍为原Task 2/3/4：实际配置生产者/控制目标/getter/授权、生命周期/九项真实清理、非Status断言及E2/E3、前两条负例实际发送/标准拒绝/must_not_apply、原CUTIL/SAVVY/Ostinato服务、完整持久化Run/Report与两链端到端；不能全部推给Linux重写。当前两链0/2、整体0/3，本批仅补全当前源码整体验证，不新增生产功能或改变完成标准。完整W3/Tasks 2/3/4不关闭，自生数据配置仍待原任务完成，W4/W5暂缓不是删除；以后实际接线完成的最终源码还须重跑原验收与回归。
- 追加前原96847 UTF16字符规范化历史前缀SHA256 f49293b9349f888658017f3e734b0e8154a49aede233b81a19f40eec08eb0b2d，必须逐字保持；已有记录不得删除覆盖。此记录追加后的台账/冻结守护与最终留存检查写本批JSON，不以文档更新声称代码或门禁完成。

### 2026-10-06 W3.26 Task 2前两条实际目标授权与分配发送边界移交

- 共用实现：原驱动可显式绑定 RuntimeTargetAuthorizer 与强制同契约 RuntimeTargetBackend，读取完整已应用 RunConfigure bytes、精确身份、实际 ModelView、注册生产者及实际 owner SID/lane/mode/控制截止时刻；不装默认成功后端、不以 control_source 字符串、宿主步号或测试 provider 代替。有限证据额度在 getter 前预约；成功/失败保留原 sample、原 Status、入口与实际完成时刻、目标或错误及原控制租约字节，不自动逐出。实际模型/状态/步/时长、原 SID/角色/Capabilities 与启用的原 CAN/ETH 通道核对，RUNNING 用显式有限提前量，冻结态用实际当前边界。
- 分配与发送：Controller 输入同时要求唯一实际注册生产者就是本来源、已应用配置/owner SID/lane/mode 和原标准反馈形成的100ms租约。一次限定只读复核指出预检后切换 CAN sender 与编码过程中授权过期两处问题；原反例 RED 后修正 GREEN。原驱动每次复核选定 sender；Source 分配和每个 CAN/UDP/Scapy 发送片段复查原 approval/Status/lease 对象及半开截止期。单来源 scope lock 禁止并发替换；至多4096个已分配 guard 原位保留用于延迟发送/重试，容量在计数推进前检查。不重读/续租，不以新 lease 接管旧批准。取号前失效不消耗计数；取号后失效保留已分配序号与失败、不发TX、不回滚。本批还用反例修正异常完成时刻丢失、不可哈希输入与嵌套可变注册快照。
- Linux追加（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同一代码接真实C/Simulink完整一致已应用配置、model/state/step/duration、注册唯一生产者、控制来源/owner SID/lane/mode 与实际100ms期限；核对原C控制仲裁/配置getter和正式会话注册的原身份/通道绑定。现有 model_get_input/output ABI 和旧 command receipt 不是这份完整上下文，缺字段/消费者明确 TARGET_MISSING，不补零或反推。真实硬件接口继续冻结，不转成Windows采集后端；此读取指向3.6实际模型状态，并非让模拟器替真实3.3采集硬件。
- Linux时序验证（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：实际来源/目标单调域及批准同步、慢读/异常、模型步推进/RESET新SID、源/生产者/控制租约半开到期、原绑定撤销/切换、多来源并发、编码/分片跨截止期和证据背压，在 SocketCAN/原以太网和实际负载下证明拒绝分配/拒绝后续TX及已发生部分TX的原证据。原1ms正负10us、80ms正负1ms、20ms心跳/CAN组、100ms控制指标仍独立验证，软件受控时钟/VirtualBus/读取替身不能代替目标资格。
- 共用未完：此授权适配不等于完整 concrete ScenarioRuntimeServices；真实配置/生命周期/九项清理、全部root/event断言与E2/E3、前两条负例实际发送/标准拒绝/must_not_apply、原CUTIL/SAVVY/Ostinato服务、授权与其它服务证据持久化及完整Run/Report、两链端到端继续原Tasks 2/3/4，不全部移交Linux重写。源guard有限保留已实现，完整停止/退休/证据管理仍需真实清理服务。自生数据配置仍待原任务完成，W4/W5暂缓不是删除。
- 归属与门禁：第三条HISTORY后续开发由别人接手，本批只改前两条必要共同授权/Source/UDP/Scapy边界，不改capture/history/replay/export/process、canplayer/tcpreplay参数或其源码/测试/历史记录。原13源码/测试与7历史JSON/log留存hash守护，第三条资源与方案原位保留；SCENARIO REPLAY边界不删不skip不native回退，第三方服务缺失仍TARGET_MISSING。当前两链0/2、整体0/3，41责任/17未执行/0完成Linux保持，不关闭W3或整体目标。
- 验证收尾：最终固定源回归、冻结14/663、离线编解码、依赖/编译、原历史前缀及第三条留存结果集中 artifacts/icd_gateway/w3-26-task2-target-authorization-progress.json 与 regression.log；只按实际 terminal 输出记录计数，不复用上一批1129项证明新代码。追加前原98194 UTF16字符规范化历史前缀SHA256 03a501fc421c2a505fca8019e107536589433e662778ddc76e6679ba2f96e4ff 必须逐字保留，已有记录不得删除覆盖。读取后端/capability 为明确软件fixture，不升级真实模型/实体/安全/RT/替换资格。
- 本批最终实测：完整 scripts/test_icd_runtime.py 通过67协议库、1041网关（含20新授权）、3台账、4接口汇总；旧静态四套件20/7/2/5通过，总1149项/八个非空套件全部exit0。14/663与离线59/72/85/800、pip check、compileall通过；152个固定源码hash运行前后不变，第三条20个留存文件hash及原98194字符历史前缀一致，41责任/17未执行/0完成Linux不提升。一次限定复核两处问题由根线程按反例修正，没有追加复核循环。成功授权保留原控制租约字节；拒绝读取/配置/owner判定时保留其原sample/Status/错误，未得到有效租约时不补造记录。证据为本批JSON/log，不声明完整Task 2/W3或端到端完成。


### 2026-10-06 W3.26 Task 2前两条生命周期批准与原事务收尾移交

- 共用实现：显式 RuntimeTargetAuthorizer 在取号前复用 SemanticGuards.lifecycle 与原 Source 的非分配 Header preview，核对六动作的实际状态/expected_state/目标/时长及 STEP 的控制 NONE、物理闭环限制，保留原不可变 LifecycleDecision。whole-plan 预检只核对声明/实际发布能力，不预测未来状态；consumer.Lifecycle 必须实际发布。STOPPED 仅允许有效生命周期管理，不授权普通数据；步骤决策不等于实际推进模型。
- 分配与片段：原 Source/dispatcher 取号前比较实际提交 Stimulus 与原批准内容的规范化字节；等值 1/1.0 不误拒绝，scope 内无载荷的 header-only 分配拒绝。Lifecycle UDP/Scapy 每片实际编码还须匹配原批准内容，不允许同 Header 替换 STEP 等载荷。继续复查原 Status/sample/lease/截止期，不重读或续租。STEP 决策128+40*步数纳入有限记录核算和 getter 前预约。一次限定只读复核发现载荷绑定缺口，根线程复现实际提交与实际编码两种替换反例 RED 后修正 GREEN，不追加复核循环。
- 原会话退休：原 SourceSession 实际反馈拥有者仅保留首个已关联且已发布 RESET/RESUME APPLIED/OK 的不可变退休收据，包括完整身份/SID/型号、原请求回执 bytes、原时刻与介质/通道；沿用保守退休规则，不新增 applied_step 等于复位前 target 的约束。后到 Status/另一个回执不得复活或覆盖旧 epoch。原 driver 只可在原 sampled step 收尾恰好导致退休且 dispatcher 已 COMPLETE 的原 native ETHGEN 事务，不做 I/O/模型读取/新分配/续租或新 SID 接管；其他 pending/新动作仍 STALE_SESSION。ACK/决策不是实际模型效果、E2/E3或安全清理证明。
- Linux追加（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同代码接真实 C/Simulink 完整配置/生命周期/目标 getter 和真实 consumer.Lifecycle，验证全部三型号六动作、实际顺序1ms STEP（非宿主压缩）、NONE控制/物理闭环排除、暂停冻结边界、STOP安全输出/撤权/队列清理。RESET 须真实恢复初始状态和全部 initial_inputs，RESUME 保留暂停状态但清旧队列；两者需真实撤销旧 SID、重新开会话/授权并核对新 epoch。原事务完整回执、请求关联/晚到/重复/错误探针/缺消费者、实际原工具 TX 和实际效果读取须目标证据，不以软件 capability/getter fixture 或本地完成代替。
- Linux时序与清理追加（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：在原 SocketCAN/以太网、真实源/目标同步域与实际负载下核对载荷一致性、分配/编码/分片期限、权限/通道切换、过期/退休/并发/背压与已有部分TX失败证据。生命周期期间的控制租约、周期/探针/视频/队列/模型与总线故障/会话九项清理需真实拥有者回执。原1ms正负10us、80ms正负1ms、20ms心跳/CAN组及100ms控制指标保持独立门禁；不改 C、不安装 Windows 专用后端、不用进程退出/ACK/local close 证明目标安全或 RT。
- 共用未完与责任：完整生产 ScenarioRuntimeServices、真实配置应用与模型 getter、实际生命周期/九项清理、全部非Status断言/E2/E3、前两条负例实际TX/标准拒绝/must_not_apply、原CUTIL/SAVVY/Ostinato服务、授权/退休等服务持久化和完整Run/Report及两链端到端继续原 Tasks 2/3/4，不能全部移交Linux重写。第三条 HISTORY 及 canplayer/tcpreplay 后续由别人接手，已有源码/测试/资源/方案/历史JSON/log原位保留，不删除/回滚/改写结论；SCENARIO REPLAY边界保留，缺第三方服务仍 TARGET_MISSING、不skip、不native回退。当前两链0/2、整体0/3，41责任/17未执行/0完成Linux保持；W3不关闭，自生数据配置仍待原任务完成，W4/W5暂缓不是删除。
- 实测与留存：最终固定153源码/测试/C/MATLAB hash 的435项/21非空套件全部exit0（327相关网关、67完整协议库、3台账、4汇总及34既有静态），含13新增生命周期测试。14/663冻结、离线59/72/85/800、pip check与compileall通过，第三条20留存文件hash一致。本批未跑完整 scripts/test_icd_runtime.py 全gateway，上一批1149是历史结果，不能证明新版本整体验收。证据集中 artifacts/icd_gateway/w3-26-task2-lifecycle-authorization-progress.json 及 regression.log；文档追加后再次执行台账/契约/留存守护，重复项不累加进435。追加前原100826 UTF16字符规范化历史前缀SHA256 711a46aca48c44c2fdb5f59dcc5239c3ab4428e6bb172c3a327882dcc6e3bb62 必须逐字保持，已有记录不得删除覆盖。
### 2026-10-07 W3.26 Task 4前两条目标授权与会话退休证据移交

- 共用实现：原 ObservationRecorder 增加显式 targets=RuntimeTargetAuthorizer，只接实际同计划/同来源/同契约对象；存在 ScenarioExecution 时固定原 driver 已安装的 service 绑定。原同一后台 worker/readback/身份前缀链增加 TARGET_AUTHORIZATION 和 MODEL_EPOCH，本地格式5十流、组合原断言格式6十四流；旧格式1/2/3/4与冻结线上ICD不变，不增设转发中心或第二个写盘后端。
- 原证据完整性：保留成功/失败 RuntimeTargetRecord 的原 action/Status/applied config bytes/ModelView/注册生产者与绑定/控制租约/LifecycleDecision/实际入口完成时间/目标或原错误；失败配置原bytes即使不是JSON也按原bytes留存，不虚称配置有效。全部uint64时间十进制字符串、不降精度，原bytes规范base64。成功Controller动作必须带原租约并核验授予/续约请求回执关联、SID/模型/source/lane/mode/生产者与半开期限。一次限定只读复核发现成功行可丢租约或携损坏回执；根线程缺租约反例RED后修正GREEN，正常授予及实际VALIDATED/APPLIED续约保留原owner bytes专项通过，不追加复核循环。
- 原拥有者与关闭：原Source反馈操作仅把首个已关联退休收据转存到其已分配原target guard的authorizer，Source关闭清缓存之后仍可保存该不可变receipt。原执行/driver/actions/assertion/target锁先于native/source，snapshot不调用getter、运行回调/poll/TX，不分配计数、不续租。替换后端/service/recording attachment在读取或快照前拒绝；嵌套可变tuple和移除recording attachment两个根线程反例已RED/GREEN关闭。保存中新增读取保留，readback核对后仅推进已保存历史身份游标、不清空目标/退休历史；写盘异常不清除原Source/dispatch/target记录。close报告未保存计数、原RESOURCE及worker终态，不作为远端九项清理、安全或完整报告证明。
- Linux文件系统追加（L-011/L-013/L-014/L-017）：同一代码在目标实际文件系统与权限下验证独占新目录、原fsync/硬链接/完整文件readback及链格式5/6，不可用时显式RESOURCE，不另建Linux协议/Windows替代后端。覆盖慢盘/空间耗尽/权限丢失/写读异常/链尾篡改/重启崩溃/关闭期限与实际数据规模，确保失败无部分回收、原历史及未保存计数可追溯。原链完整性不是密码学签名或攻击者身份认证，完整Run/Report终态与其他服务证据仍需共用实现。
- Linux原时序追加（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：在真实getter、Source/目标同步域、实际SocketCAN/原以太网和负载下核对Controller原授予/续约/撤销/安全/换SID与APPLIED/VALIDATED关联、RESET/RESUME晚到回执、原源关闭后尾部归档、单owner锁顺序及写盘背压；不能以受控时钟、软件模型/Capability fixture或VirtualBus证明实际控制所有权、RT或安全。1ms正负10us、80ms正负1ms、20ms心跳/CAN组和100ms控制期限门禁保持，写盘不得以宿主时间补造模型步。
- 共用未完与责任：真实C/Simulink完整getter、consumer/生命周期实际六动作及九项清理、全非Status/E2/E3读取、前两条负例实际TX/标准拒绝/must_not_apply、原CUTIL/SAVVY/Ostinato运行service、接收端及其他服务历史与完整Run/Report、前两条端到端仍按原Tasks 2/3/4继续，不能整体推给Linux重写。第三条HISTORY/capture/replay/export/process与canplayer/tcpreplay后续由别人接手，其已有源码/测试/资源/方案/历史JSON/log原位保留，不删除回滚、不改写历史结论；原20文件hash与上批一致，SCENARIO REPLAY声明/服务边界保留，缺外部真实服务仍TARGET_MISSING，不skip、不native回退。当前负责两链0/2、历史整体0/3，41责任/17未执行/0完成Linux不提升，W3/Tasks 2/3/4不关闭，自生数据配置仍待原任务完成，W4/W5暂缓不是删除。
- 本批实测：固定最终155源码/测试/C/MATLAB hash下573项/27非空套件全部exit0，含18新增归档、465相关gateway、67完整协议库、3台账、4单文件汇总与34既有静态；14/663冻结、离线59/72/85/800、pip check及compileall通过。没有执行本批完整scripts/test_icd_runtime.py全gateway，435/1149仅属历史源码，不复用其结果。早期租约实现错误与fixture字段/未发布探针造成的失败在最终固定源回归前修正，不计入最终通过数。证据集中artifacts/icd_gateway/w3-26-task4-target-recording-progress.json和同系列regression.log。文档追加后再跑台账/汇总及留存守护，重复通过不累加573。
- 追加前原103337 UTF16字符规范化历史前缀SHA256 cd78a2a3928ab2ee35f56986e4cb29b60e21fcebff33cbbaca4cbf8c5352c39d 必须逐字保持；已有记录不得删除覆盖。本批源码、第三条留存和原台账前缀在最终回归后及追加后都核对，结果写本批JSON，不以文档更新勾Linux门禁。

### 2026-10-07 W3.26 Task 2前两条配置消费适配移交

- 范围再次确认：本轮后只开发PROTOCOL、SCENARIO及必要共同ICD/接收/配置/授权/反馈/清理/报告。第三条HISTORY/capture/replay/export/process和canplayer/tcpreplay由别人接手，既有源码/测试/资源/方案/JSON/log原位保留，不删除回滚、不改历史结论；20个留存hash仍一致。SCENARIO REPLAY声明和原服务边界保留，缺外部实际服务仍TARGET_MISSING，不skip、不native回退。当前两链0/2、历史整体0/3，第三条移交不是验收通过。
- 共用实现：Receiver显式安装同契约/registry的ModelConfigurationService及强制实际ModelConfigurationBackend。read_context先接完整原请求，按本次terrain hash、origin/frame和initial point读实际状态/地形；上下文保留原request bytes并核对规范化关联，不能借旧地形样本。完整原语义/安全零输入、实际冻结步、空原模型队列、反馈容量和半开时效检查先于写入。apply_configuration须真实一次准备资源/配置/模型/初值并取得完整实际读回，字段/配置/initial_state/全部initial_inputs及实际CONFIGURED视图一致才标准APPLIED；普通registry仍不能伪造消费完成。原精确retry不重读、不重写、不续租，不安装CLI或Windows成功后端，冻结3号仅UDP及线上ICD不变。
- 失败与容量：写前预约独立最大原上下文request及失败receipt的有限额度；明确字节、型号描述、枚举、uint64时刻等严格不可变边界。失败/超时/错读保留原context/receipt/error/实际完成和write_attempted，不能推断已回滚或未发生效果；close只保留本地历史、不关闭外部模型或证明远端安全。关Receiver前先检查原status/configuration操作锁，避免部分关闭。根线程地形关联/最大证据额度及超长或可变view反例先RED后GREEN；不追加复核循环。
- Linux追加（L-001/L-002/L-003/L-004/L-010/L-011/L-013/L-014/L-017）：同代码接真实C/Simulink模型安全边界、完整配置/资源/模型/initial_state/initial_inputs初始化与实际getter/revision。对本次资源hash、原点/坐标系和初始位置做真正terrain/obstacle解析、hash/完整性/有效域验证；旧配置、请求复制、旧command receipt或测试double不是读回。原子边界内复核状态/步/控制/队列和原context，验证并发状态变化、资源缺失/损坏、部分写入异常、恢复策略及实际错误证据。write_attempted后失败不得自动重试；恢复只能经已批准生命周期/清理服务，不能把Python异常当事务回滚。
- Linux时序/接收追加（L-003/L-004/L-010/L-011/L-013/L-014/L-017）：actual getter/receipt统一接收端单调域；覆盖慢读/慢写/异常完成、请求/样本/SID半开过期、计数耗尽、有限历史背压、原queue未清不得配置、同请求重发只回原回执和服务关闭竞争。实际SocketCAN/以太网/模型负载、跨机同步、1ms正负10us/80ms正负1ms等目标门禁仍单独验证；本批受控clock/model double和真实本机UDP只证明公共适配，不证明模型、实体、RT或替换资格。
- 实测与留存：最终157固定源码/测试/C/MATLAB hash下290项/16相关非空套件全部exit0，含30配置、其他152相关gateway、完整runtime67、3台账、4单文件及34既有静态；14/663冻结、离线59/72/85/800、pip及compileall通过。完整1206为地形关联前、完整1209为最后metadata封边前的历史源码回归，不冒称最终全gateway。实际耗时原样留存（最终Status套件报告6883.200s，原因本批未确定，不是RT测量）。一次限定只读复核在后续根线程封边之前结束，无新的Important/Critical且未运行测试；没有追加复核循环。证据集中artifacts/icd_gateway/w3-26-task2-configuration-service-progress.json和regression.log；重复守护不累加290。
- 未完与门禁：实际C后端、生命周期六动作/九项真实清理、完整运行services/全部断言/E2/E3、前两条负例/原工具服务、配置及其他服务持久化和完整Run/Report、两链端到端继续原Tasks 2/3/4，不整体交Linux重写。41责任/17未执行/0完成Linux保持，W3不关闭，自生数据配置仍待原任务完成，W4/W5暂缓不是删除。本批原106006 UTF16字符规范化台账前缀SHA256 51b904626bb77bd644b3d6626b627443270f0186fb976c06c9f4c49a767adf6a 必须逐字保留；已有记录不得删除覆盖，追加后再次核对源/留存/prefix并执行台账与契约守护。

### 2026-10-07 W3.26 Task 2前两条运行会话分组退休移交

- 本轮范围与留存：收尾后本线程只继续PROTOCOL、SCENARIO及必要共同ICD/接收/配置/授权/读取/反馈/清理/报告。第三条HISTORY/capture/replay/export/process和canplayer/tcpreplay已由别人接手，既有代码、测试、资源、方案、历史JSON/log原位保留，不删除回滚、不改写结论；20留存文件hash与前批一致。SCENARIO REPLAY声明及原服务边界保留，缺实际外部服务仍TARGET_MISSING，不skip、不native回退。第三条移交不是验收，当前负责0/2、整体历史0/3保持。
- 共用实现：SessionRegistry.run_session_ids以原可信run/vehicle/scenario/model/definition五字段跨source_id选择全部旧角色，原入口必须未过期，可含仍留存的同组过期者；不运行无关维护、不续租、不分配。Receiver.retire_run删除前预约有限记录/字节/输入额度，保留原完整身份、观察时刻、选中和实际退休SID、原队列输入/分片及实际删除子集。固定原registry/queue/reassembler/实际资源worker，在每次效果前和后核对；一次性选中SID许可阻止清理中重入接收、tick、无关retire、drain和close。部分失败保留原进度/错误，不推断回滚，精确本地retry只读原结果、不重启、不接管后来SID。
- 证据边界：observed_ns是效果前观察时间，不是完成时刻或RT证明；模型步和其他同模型运行不改变，不建新SID、不发APPLIED、不执行模型RESET/RESUME、不证明安全输出/控制撤权。资源cancel只通知原worker，实际原请求/abort/unfinished记录另行证明文件清理。实际ResourceWorker线程及文件测试有独立abort读回，不能由会话消失推断九项清理已完成。局部历史关闭后仍可查，容量满先拒绝删除、不驱逐证据。
- Linux模型/epoch追加（L-002/L-003/L-004/L-010/L-011/L-013/L-017）：同代码接真实C/Simulink六动作consumer及真实效果读回，先验证实际状态/安全/撤权/原队列等效果，再由原拥有者调用本地退休并核对全部选中SID及实际删除子集。RESET恢复完整初始状态与全部initial_inputs，RESUME保留暂停状态、清旧队列；真实模型步/C队列epoch与Python ModelQueue必须同步，不能把本地SID清除或原模型步未变当复位成功。同模型其他run仍有输入/租约时先验证真实独占/冲突策略，冲突须在模型写入前拒绝，不误清其他run；严禁全局清队列替代分组策略。旧SID拒绝/晚到/重复/半开期限和新SID重新开会话、配置/授权/模型读回需原标准收发证据。
- Linux资源/失败/时序追加（L-001/L-003/L-004/L-010/L-011/L-013/L-014/L-017）：实际存储线程cancel、在途写入、abort与unfinished记录需与原会话和请求关联，不能提前判文件/后台线程结束。覆盖原资源清理失败、慢盘/权限丢失、部分SID退休后异常、实际源/目标同步域、时钟回退/过期、容量背压与单拥有者串行/回调重入；失败后只允许显式原拥有者恢复，不自动重复已发生效果。九项真实清理、原实际SocketCAN/以太网与目标负载、1ms正负10us/80ms正负1ms/20ms心跳CAN组/100ms控制门禁保持独立，不用本机UDP、模型ABI声明、线程退出或local close证明模型/实体/RT资格。
- 实测：固定158源码/测试/C/MATLAB hash的460项/23相关非空套件全部exit0（352相关gateway含21新增退休、67完整runtime、3台账、4单文件及34既有静态）；14/663冻结、离线59/72/85/800、pip check和compileall通过。本批未跑完整scripts/test_icd_runtime.py全gateway，不复用上批290/1209历史源码结果。一轮限定只读复核的两处P1（重入新增未留存分片、错误worker取消其他registry）由根线程分别RED/GREEN修正；另一个效果前worker替换反例也已RED/GREEN修正，没有追加复核循环。证据集中artifacts/icd_gateway/w3-26-task2-run-retirement-progress.json和同系列regression.log，文档追加后的守护重复不累加460。
- 共用未完：真正Lifecycle消费完成/标准ACK缓存、九项清理编排/新SID与C epoch接线、完整ScenarioRuntimeServices/全字段断言/E2/E3、前两条负例及原工具service、接收端服务历史落盘与完整Run/Report、两链端到端仍在原Tasks 2/3/4继续公共开发，不能整体移交Linux重写。仅实际平台后端与目标验证追加Linux，不建Windows替代实现/分支。W3与原Tasks不关闭，41责任/17未执行/0完成Linux不提升，自生数据配置仍待原任务完成，W4/W5暂缓不是删除。
- 追加前原108370 UTF16字符规范化历史前缀SHA256 d39caad203219f389abf00ed07ca4ee5eece7f920b3f0b698933d204edc35d8b 必须逐字保持；已有记录不得删除覆盖。追加后再次核对158源、20第三条留存及原prefix，并执行台账/契约守护，实际结果写本批JSON/log。

### 2026-10-07 W3.26 Task 2前两条公共生命周期消费移交与暂停

- 范围与暂停：本轮收尾后按用户明确要求暂停，不进入下一阶段；经用户恢复后只继续PROTOCOL/SCENARIO及必要公共ICD/接收/配置/授权/读取/反馈/清理/报告。第三条HISTORY/capture/replay/export/process及canplayer/tcpreplay由别人负责，已有代码、测试、资源、方案及历史JSON/log原位保留，不删除改写；20留存hash一致。SCENARIO REPLAY冻结边界保留，缺外部实际服务仍TARGET_MISSING、不skip、不native回退。当前负责0/2、历史整体0/3不提升。
- 共用实现：强制显式同契约ModelLifecycleBackend/Service，接原Receiver及标准Lifecycle 4 UDP接口。实际完整配置、State132、全部已应用inputs、身份/原请求/实际view/时刻关联在一次效果前验证；保留原上下文/实际receipt/执行器/owner SID/C队列深度/revision及每个STEP读回。RESET核对完整初态和全部initial_inputs，RESUME核对暂停状态投影及全部inputs，STEP每个顺序1000us模型步需独立状态/安全输出/采样读回；宿主压缩时间允许离线，但不能推断RT或真实C求解。完整隐藏求解器状态仍由实际后端负责，State132不是其完整内部快照。
- 共用清理与证据：getter/效果前预约完整有限历史、原输入/分片和终结ACK序号；拒绝同型号其他run冲突，固定原拥有者。实际安全动作执行器归零/撤权/C队列空读回，选中本地输入和分片实际删除均核实后才APPLIED；START也校验完整执行器格式。RESET/RESUME退休全部旧组SID，原服务专属回执缓存不接纳旧网络SID重试。失败、过期、部分清理和已发生效果保留实际完成/原字节/删除子集，不自动重做或推断回滚。禁止活跃消费时接收/tick/无关退休/drain/close重入；local close保留历史，不证明远端安全。
- Linux追加（L-001/L-002/L-003/L-004/L-010/L-011/L-013/L-014/L-017）：同一代码接实际C/Simulink完整配置/初始化/隐藏求解器状态/全部inputs与执行器/控制owner/C队列/步/revision getter，原子边界内再核对上下文并执行六动作。RESET真正恢复初始状态及全部initial_inputs并同步C/Python queue epoch；RESUME真正保留暂停的完整内部求解器状态，清旧队列/组会话后新SID显式开会话/授权。STEP实际每次1ms求解，严禁一次大步替代，物理闭环和非NONE控制禁止。实际慢读写、部分模型效果、旧SID/晚到/重复、外国run冲突、原拥有者撤销和有限证据背压需真实读回/恢复策略；失败不等于回滚。
- Linux时序与剩余清理：接收单调域与实际跨机同步、SocketCAN/原以太网、真实模型和目标负载下验证半开TTL/SID/样本时效、每步时序、实际安全输出/撤权。资源worker cancel仍只是通知，原abort/unfinished与文件/线程清理另证；周期/探针/视频/队列/模型/总线故障/控制/会话九项清理及SessionClose真实服务仍需补齐。1ms正负10us、80ms正负1ms、20ms心跳/CAN组和100ms控制门禁保持独立；本机UDP、模型double或Python队列不证明实体/RT/替换资格。不改C、不增加Windows专属后端或分支。
- 实测：固定160源码/测试/C/MATLAB hash下488项/24相关非空套件全exit0（380相关gateway含28新生命周期、67完整runtime、3台账、4汇总、34既有静态），另14/663冻结、离线59/72/85/800、pip check及compileall通过；未执行本批全gateway，不复用旧完整结果。一轮限定只读复核的两项问题按反例RED/GREEN修正，未追加复核循环。真实本机UDP SourceSession的RESET/RESUME回执退休与显式abandon/open新SID/当前步通过，模型后端明确替身。证据集中artifacts/icd_gateway/w3-26-task2-lifecycle-service-progress.json及regression.log；文档后重复守护不累加488。
- 未完与恢复起点：实际C后端、完整ScenarioRuntimeServices/非Status E2/E3/前两条负例及原工具服务、九项清理/SessionClose、全部接收服务历史落盘/RunReport和前两条端到端继续原Tasks 2/3/4，不整体移交Linux重写。恢复时从共同运行服务与清理接线继续，先完成原W3再加模拟器自生数据配置。W3/Tasks 2/3/4不关闭，41责任/17未执行/0完成Linux不提升，W4/W5暂缓不删除。
- 剩余工期为单人、环境与模型可用前提下的初步区间，不是承诺日期：前两条共同开发约8至12工作日；Linux实际后端/原工具/平台补全约6至10工作日；联合验证/修正约4至7工作日，串行合计18至29工作日；含自生数据配置约20至33工作日，不含第三条外部开发、真实3.3/硬件采购或外部接口等待。原W3后自生数据配置另约2至4工作日，可先验证标准软件接收；真实3.6消费需实际模型后端，不能把软件ACK当业务完成。暂停时间不计入开发工期，恢复后随实际后端缺口重估。
- 追加前原110854 UTF16字符规范化历史前缀SHA256 3bfaf3c2711085820bca3d84d25049126a8cabd02155f258f2afbe0161f4e237 必须逐字保持；已有记录不得删除覆盖。追加后核对160源/20第三条留存/原prefix并重跑台账及单文件契约守护。


### 2026-10-07 收紧目标后恢复：前两条自生数据与标准实收

- 最新范围覆盖：用户已恢复开发。本轮按“三类输入源经各自原工具链、冻结ICD到3.6实收解码并留下收发记录”推进，不把完整原W3生产运行时/模型效果/全部断言/九项清理/RunReport、W4/W5或硬件采集作为前置。此前20至33工作日估算针对扩大后的全面范围，撤回其对当前收发任务的适用性；保留历史文字但不继续按旧顺序延后自生数据。当前仅开发PROTOCOL、SCENARIO和必要共同接收，HISTORY后续由外部接手。
- 共用实现：Receiver显式可选安装同契约/registry的ReceptionService，保留有限不可变完整解码报文、身份、实际binding及接收单调时刻。冻结CRC/分片/Schema/型号/会话/角色/时效和容量准入先于记录；精确retry重发原ACK、不重复记录。仅发布实际接收消息ID，反馈为RECEIVED/VALIDATED且probe0，不发假Status/APPLIED/CONSUMED、不声明模型或替换ready；已有实际模型/资源服务保持优先，默认CLI仍仅ID1。CANGateway使用原python-can/SocketCAN接同一Receiver与标准CAN反馈，部署CAN绑定必须唯一、显式且与授权一致，没有Windows或UDP替代CAN后端。
- 自生与入口：SendPlan/SendRun及send_cli使用完整SourceInputs与真实目录/DBC资源，PROTOCOL按显式完整Stimulus、次数/周期/首步生成常量快照；SCENARIO沿用原ScenarioPlan/WaveformSampler产生完整波形/周期快照，使用原CANT或Scapy ETHGEN。新运行配置集中config/generated-input-reception.json，现有共享部署加可选CAN映射，旧默认行为不改。缺原native工具或接收能力在数据TX前明确失败，不临时改能力或回退工具。源端保留统一SID/取号/事务，过期前显式abandon/open新SID不是模型RESET。
- 契约与投影：不修改14冻结源、完整输入单文件、线上布局/枚举/业务字段或C。冻结ScenarioSource要求root assertions，定义全部保留并明确NOT_EVALUATED，不删字段让发送器通过；仅提取SEND/FAULT/WAVEFORM/PERIODIC_START/SAMPLE/STOP，WAIT/ASSERT/NEGATIVE_SEND/REPLAY/END_CLEANUP仍明确TARGET_MISSING，不悄悄跳过。cleanup定义留在原输入，当前只关闭本地拥有对象，不宣称原完整场景执行或远端清理。planned_target_step是声明的样本/目标步，主机相对毫秒仅作发送演示，绝非实际MODEL_STEP、跨机时钟或RT精度证据。
- 本地收发记录：独占创建新JSONL，旧文件不能覆盖；保存完整请求/反馈、原CAN TX/RX及Scapy L2尝试的原字节HEX、native完成/失败/不确定状态，开会话原请求/回执另存，uint64时刻按十进制字符串保留。native部分发送失败据真实完成片计数，不误报0；写入完成不等于远端收到。接收CAN反馈失败退出仍刷盘已解码尾部。一次限定只读复核发现这两项问题，根线程四个真实对象/故障注入反例先RED后GREEN修正，无追加复核循环。另完整payload、signed zero、容量、授权、原工具缺失、显式新SID和CLI原记录覆盖测试；不构建完整RunReport或崩溃安全证据链。
- 已产生数据：独立CLI dry-run产生完整环境快照，wind_n_mps在0/80/160步为0/8/16，见artifacts/icd_gateway/generated-input-reception-samples-20261007.jsonl，明确NOT_TRANSMITTED。另原python-can VirtualBus路径3发/3收（风速0/0/0）、Scapy SuperSocket与本地测试NIC中继路径3发/3收（0/8/16）由真实共同Receiver解码，ACK实际关联且均RECEIVED/VALIDATED/probe0；全请求、native原字节、开会话与RX记录保存在artifacts/icd_gateway/reception-transmission-library-evidence.json。CAN的float32量化遵守冻结packed布局，请求字面值与实际解码值分别留存；不以JSON数字字面相等替代原字节核验。
- 本轮必要Linux补全（L-001/L-002/L-005/L-008/L-017，按E1判定）：同一Python环境和代码接实际SocketCAN，先vcan再批准设备，核对FD/BRS/DLC/标准ID/每通道grant、双向反馈、断链与部分native发送/反馈失败尾部；Scapy接实际L2 socket和NIC，配置真实源/接收IPv4、端口角色、单播MAC与逻辑ETH映射，原以太网/VLAN/MTU实际收发不得用测试NIC中继或普通UDP替代。部署真实3.6接收地址/授予与消息能力，逐条核对TX原请求/native字节和RX完整字段/SID/序列/事务/目标，保存接收端自己的单调时刻，不跨主机相减算单向延迟。日志磁盘失败/权限/容量及有限历史满明确拒绝；原接口冻结保持，不另做Linux版本。
- 外部交接与后置门禁：第三条既有capture/history/replay/export/process、canplayer/tcpreplay、测试/资源/方案/历史JSON与log原位保留，20留存哈希继续核对。当前入口不接管HISTORY、不宣称三条目标链路完成；待外部回放服务按既有标准边界交付后集成，不能改成原CANT/ETHGEN普通SEND。L-006观察工具、L-007/L-009外部回放以及模型/时序/硬件/正式发布/真实3.3切换要求继续留存但不扩成本轮前置。Windows库级路径可运行不等于Linux或实体通过，原完整验收0/2、历史0/3、41责任/17未执行/0完成Linux保持；完整W3仍不关闭，当前收发里程碑单独汇报。
- 最终固定源码回归、冻结/离线/依赖/编译及留存守护的具体命令、退出码、数量和原输出集中artifacts/icd_gateway/reception-transmission-progress.json及同系列regression.log，历史版本结果不得充当本版本全gateway通过。追加前原113439 UTF16字符规范化历史前缀SHA256 9a3884c1540ca0c517b1f0eb26bd3a9fd3ea95eb8448215bb1481cdac9351cf5 必须逐字保持；已有记录不得删除覆盖。追加后重新核对台账41责任、17Linux事项和完整接口单文件。

### 2026-10-08 外部 HISTORY/PCAP 交付增量合并

- 本批只合并用户指定桌面交付、更新文件与推送既有分支，不扩展 W4/W5。两份新增 HISTORY 模块、六个脚本、独立 CONTROLLER 配置、外部测试及全部 200 份抓包/失败尝试已导入；共同导出器仅增加安全本地 prepared.pcap 文件名，不用外部旧快照覆盖当前接收/配置/授权/生命周期/自生发送。原默认 ID1、完整输入定义和 14 冻结源不变，不另开发 Windows 后端。
- 本次 Windows 兼容性验证：同一冻结 HISTORY 帧在共同 Receiver 上得到真实标准缺消费者反馈；显式 ReceptionService 完整解码并给出 RECEIVED/VALIDATED/probe0，精确重试去重。原 STIMULUS/CAN 部署绑定保留；最终 Round 3 retry_2 和 Round 4 retry_4 历史抓包用当前编解码库重新校核。外部 pytest 测试转换为等价 unittest，统一测试入口覆盖新增文件。Round 4 删除失败与既有证据目录误写的两个反例先 RED 后 GREEN，保留退出清理并核对实际命名空间/路由；Bash 假命令测试不等于 Linux 原生执行。
- L-007/L-009 追加：外部历史 WSL2 netns/veth/tcpreplay/tcpdump PCAP 准入子集已有证据，可按新路径继续使用，不勾选完整 Linux 门禁。当前默认能力只有 [1]，SourceSession 不授权 ID7 常规发送；诊断探针的 RECEIVED/OK 后 FAILED/TARGET_MISSING 不证明应用。生产 ReplayRuntimeService、SCENARIO REPLAY 接线、HISTORY CAN/canplayer 及批准回放策略仍待原负责人/后续集成完成；不能用普通 UDP 或 CANT/ETHGEN SEND 替代 HISTORY，也不能改能力声明伪造完成。
- L-001/L-005/L-008/L-017 追加：在批准 Linux 与实际 3.6 部署上复跑前两条原生链路和新增 HISTORY 路径，确认真实地址/MAC/网卡/grant、当前 SID、完整 TX/RX、标准反馈与容量/断链/日志失败尾部。Round 4 原 Conda uav-history-round4 门禁和隔离 IP/MAC 保留，普通 .venv 不能直接运行；核定目标环境或后续统一修改门禁及环境证据后再跑，证据写入不存在的新目录。冻结硬件接口继续保留，不把历史 WSL2 当麒麟/实体/RT 或实际部署通过。
- 外部 Round 5/5A 及内部 bridge 文档仅为交付设计和局部资产调查，NO_GO 不扩展为整个当前仓库资产结论，未实现模型 bridge。完整模型、九项清理、正式替换资格等原责任继续保留但不是本轮合并前置；原 41 责任、17 未执行 Linux 门禁及旧验收数不改写。实时说明见 docs/history-handoff-integration.md；最新实际命令、数量和指纹集中 artifacts/icd_gateway/history-handoff-integration-20261008.json 与同名 log，不将旧源码结果充当当前全量结果。
- 追加前原 116426 UTF16 字符规范化历史前缀 SHA256 63989b68b4608c4b711c7a5934edc253c12ee509d05621ef578b5f6a0e290e4a 必须逐字保持；已有记录不得删除覆盖。
