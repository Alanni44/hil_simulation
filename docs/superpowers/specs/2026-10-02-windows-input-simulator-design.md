# Windows Input Simulator Development Design

日期：2026-10-02。范围：既有3.3替代方案与HIL-ICD-1.0的Windows推进边界。

## 1. 决定

推荐Windows原生开发共同协议库、资源/场景、管理面和UDP软件链路；Linux/Ubuntu RT执行SocketCAN与现有C核心验证。当前不安装WSL、不迁移操作系统、不购买硬件、不改业务ICD，先做可独立验证的共同协议库。

2026-10-03按用户要求收紧：Windows仅是当前开发/测试宿主，所有新增模块保持单一共用代码和入口；不另开发Windows专用接口、协议、服务或驱动版本。需要Linux的内容保留为待开发/未执行，不改写现有POSIX实时核心、不新增Windows计时替代、不开发Windows vendor SDK替代链。下文“Windows阶段”仅指同一代码在当前宿主执行的软件验证，不代表独立产品版本。

备选一：使用WSL补充Linux软件工具链，但需实际确认发行版、内核CAN能力及网络/设备条件，不把WSL看作硬实时目标。

备选二：直接在Ubuntu RT开发和联调，可较早接入模型，但受目标设备、依赖和部署条件约束。它是后续真实模型与实时验收路径，不阻塞Windows共同库开发。

## 2. 已核对环境

| 项目 | 当前证据 | 意义 |
|---|---|---|
| 操作系统 | Windows AMD64 | 可执行Windows原生Python单元测试和UDP通信 |
| 独立Python | Codex bundled Python 3.12.14 | 现有v0.3 QA已采用该解释器；新服务使用独立环境，不覆盖旧HIL Python |
| 系统Python | D:\Python\python.exe命令可见 | 本次未确认版本/依赖，不将其与独立环境混用 |
| Git | D:\Git\cmd\git.exe可见 | 保存和检查现有工作区；保留所有用户变更 |
| GCC | MSYS2 UCRT64 gcc命令可见 | 不代表现有Linux实时核心可直接构建或达成实时指标 |
| WSL | wsl.exe命令可见 | 未确认Linux发行版、内核模块或硬件透传，不登记为已就绪 |
| canplayer/tcpreplay | 当前命令路径未找到 | 原分支保留，不能伪称工具已运行 |
| MATLAB | matlab命令当前不在PATH | 未认定MATLAB未安装，也未验证R2018b许可证/模型构建 |
| C实时核心 | 使用sched_setscheduler、mlockall、POSIX线程/网络等接口 | 保留Linux运行目标，不用Windows计时器冒充1ms硬实时 |

上述为命令/代码检查，不是设备和运行资格确认。已有预安装QA依赖位于artifacts/interface_contract_validation/vendor与vendor_v03，只供静态校验；生产代码不得直接从QA目录导入依赖。

## 3. 架构保持

共同库icd_runtime负责v0.3基线校验、严格字段验证、PACKED_LE/JCS、CRC、分片和重组。模拟器input_simulator组织原工具、资源、场景与历史；3.6接入icd_gateway独立接收、校验、限流、路由和采集真实消费者证据。

Windows与Linux共享业务库和错误规则，操作系统差异仅存在于工具/设备后端、启动脚本和部署配置。不得按模拟器/真实3.3身份选择解码或映射路径，不设模拟器专用模型入口。

初期UDP在127.0.0.1上验证，端口仍按36100/36101/36102与相应角色使用。该回环地址是开发部署配置，不修改既定HIL1字节格式、消息ID或安全规则；不能将其登记为汽车以太网实物通过。

第一阶段不修改v0.3业务字段、原Word文档、现有C核心、Simulink模板、UE4链路或旧Python环境。发现基线矛盾时单独提出契约修订并重新计算指纹，不在Windows实现中增加私有容错。

## 4. 开发顺序

### W1 共同ICD运行库：先执行

对应整体M0/M1。建立独立依赖与Windows测试入口，先失败测试后实现。加载四组件SHA256指纹及Schema；覆盖45类输入和14类反馈的结构校验、13类PACKED_LE载荷、JCS业务载荷、CANFD/UDP/视频header、CRC与有限分片重组。

使用现有85条黄金向量作独立参考，还要新增缺片、重复冲突、错版本、错误CRC、非零padding、错误DLC、越界/NaN、超时、缓存满与未知ID测试。不得用仅一次encode/decode往返替代黄金向量。

交付是可运行的共同协议库与测试报告，不是已发布3.6服务或模型闭环。消息编码全覆盖不等于相应消费者已经实现。

### W2 UDP收发与正式接入边界

模拟器与接入进程使用标准库UDP socket的同一实现、共同库和相同正式报文；当前在Windows宿主建立会话、授权、序列与事务、去重、有界队列及反馈关联。使用回环端点，不绑定尚未配置的10.36.*地址；不存在另一套Linux/Windows接入服务。

软件接收可以产生真实E1。没有C模型/任务/视频消费者时返回对应STATE/UNSUPPORTED/TARGET_MISSING，APPLIED与CONSUMED不得伪造；用于单元测试的spy/stub不得登记为生产消费者或E2/E3证据。

整体M2要求真正C核心应用，故Windows网络验证即使通过也不能勾选完整M2门禁。目标Linux服务可用后再接入同一接收路径验证真实写入点。

### W3 三类资源与场景/回放

PROTOCOL解析真实目录、Schema与DBC；SCENARIO支持模型步事件、波形、周期、WAIT、断言、负例与清理；HISTORY按方向/时钟/完整性筛选并依既定模式重建。

PCAP解析和受控UDP重建可先在Windows实现；这不代表tcpreplay分支已验证。CAN日志可先解析/编码，实际canplayer发送另有Linux工具资格门禁。模型步时钟未接入时只跑显式离线测试，不以Windowssleep精度代表实时同步。

### W4 管理API与既有控制台

在现有Python/Web控制台上增量接入v0.3管理API，按Schema提供完整模型初始快照与强类型消息，保存请求/会话/事务关联。功能不就绪时如实显示不可用，不用自由values字典回退。

前后端使用同一契约；原25个命令、资源分块和测试包元数据需按现有服务边界接入，不另建完整管理平台。具体改动前形成该工作包的聚焦设计/测试。

### W5 Linux、模型与实物接入

目标环境就绪后验证SocketCAN/vcan、can-utils/canplayer、tcpreplay、C真实输入/参数应用及消费者探针；再执行真实CANFD/汽车以太网、视频与串口/AD/DA/TTL资格确认。

GPS无效/IMU陈旧、六电机5/6失效、真值与传感故障分离、延迟/丢包语义等已定义的实现缺口均为必做项。不能因为Windows网络测试通过就省略模型修正。

## 5. 六分支兼容边界

| 原分支 | Windows本阶段 | 后续门禁 |
|---|---|---|
| cantools→python-can→SocketCAN | DBC/载荷/帧校验可做；测试虚拟后端只计软件结果 | SocketCAN与设备资格留Linux目标，不开发Windows SDK替代链，编码不变 |
| can-utils↔SocketCAN | 保留工具封装/能力探测，不启动不可用工具 | Linux/vcan与实际CANFD分别验收 |
| SavvyCAN↔SocketCAN | 保留独立分支；GUI/驱动/后端实际检测前不报可用 | Linux实际后端证明FD/BRS/时间戳/通道能力，不新增Windows后端 |
| CAN日志→canplayer→SocketCAN | 可解析、筛选、重建合法回放日志 | canplayer与SocketCAN实际发送在Linux验证 |
| Ostinato/Scapy→Ethernet | 先做标准UDP构包与socket软件通信；工具能力单独确认 | 原工具、实际网卡、汽车以太网通道分别验证，不静默换工具 |
| PCAP→tcpreplay→Ethernet | 可解析、分流、生成已重建捕获资源 | tcpreplay实际执行与实物链路独立验证 |

保持全部六分支的原职责；Windows socket测试属于开发验证入口，不是删除或替代图二原工具。缺失/未资格确认的工具必须返回明确不可用，不跳过必选用例取得全通过。

## 6. 当前验收能说明什么

可以证明：结构与字段覆盖、编码一致、应用CRC、分片容量/边界、可重复离线调度、Windows UDP接收与合法性拒绝、资源记录与反馈关联。

不能据此证明：1ms±10us硬实时、80ms±1ms完整系统通信、实际CAN仲裁/BRS、电气安全、真实图像注入、模型实际应用、跨机同步、真实3.3平滑替换。

阶段报告独立标记WINDOWS_SOFTWARE、LINUX_SOFTWARE、TARGET_REALTIME、PHYSICAL和REAL_33_REPLACEMENT，不将未执行项合并为通过。E2/E3只由实际模型/消费者产生。

## 7. 依据

- 原工具链保留与选型评估版方案、整体开发计划、v0.3共同契约与覆盖清单。
- [Linux SocketCAN](https://docs.kernel.org/networking/can.html)：SocketCAN属于Linux CAN网络栈。
- [python-can接口](https://python-can.readthedocs.io/en/stable/interfaces.html)：后端封装设备接口，具体设备仍须按接口文档确认。
- [Microsoft WSL](https://learn.microsoft.com/en-us/windows/wsl/install)：WSL入口不等于发行版和目标工具已安装；本阶段不要求安装。

本轮仅核对环境和更新推进设计，不声称共同库、网络服务或Windows版HIL已实现。下一可执行工作包为W1共同ICD运行库。

2026-10-03执行更新：上段为原始设计时状态。W1离线库及W2.1会话/标准UDP有限软件包已经实现并验证，共用实现仍未通过Linux或完整模型/实体验收。W2.2队列/真实消费者契约、W3/W4及Linux工作继续；每包收尾追加`docs/superpowers/plans/linux-development-backlog.md`，保持41项计划完整覆盖，不拆Windows产品版本。

## 8. 2026-10-04当前交付优先级澄清

用户明确当前模拟器应自行产生数据、经冻结ICD发给3.6，不以接硬件采集输入为前提。2026-10-05最新执行顺序为：先完成原有W3三类资源、场景/回放执行和原六工具链的共用开发，再开发新增自生数据配置与自动运行入口，不把新增生成器当作原W3已完成。W4管理API/控制台与W5 Linux/真实模型/实物资格暂缓，留在唯一待办且不标通过。原41责任、17 Linux门禁、六工具/硬件接口/14冻结源完整保留，当前软件任务结束不构成完整标书或真实3.3替换验收。

源数据发生器是已批准W2标准UDP软件入口的连续使用，不冒充ETHGEN/Ostinato/Scapy或改变六工具资源链。内部生成配置只负责完整Stimulus模板、常量/波形、有限周期/次数，ICD线上无新字段；全部模板由契约验证，SessionOpen/Heartbeat仍由原会话与分发器管理。生成采样步是显式输入，用于数学值生成，不宣称来自C模型、不把宿主sleep当MODEL_STEP/RT/ClockSync。每次发送的标准target_step必须单独显式提供；后续自动运行入口需明确生成时钟和目标步来源。

软件验证以真实会话/标准能力/角色和实际UDP TX/RX为依据。缺业务能力时明确TARGET_MISSING，不私改Capabilities、不绕过原授予或伪造APPLIED/CONSUMED。当前原接收服务未实现完整模型消费者，不能将协议peer测试说成3.6真实业务已应用。完整可配置自动生成入口尚需完成，当前澄清不表示W3已结束。
