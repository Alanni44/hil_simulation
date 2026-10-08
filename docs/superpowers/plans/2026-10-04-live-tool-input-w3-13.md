# Live Original Tool Input W3.13 Implementation Plan

> **For agentic workers:** Execute inline with executing-plans/TDD. Independent read-only review only; no implementation delegation, commits, branches, worktrees or frozen QA generation.

**Goal:** 沿批准设计接真实标准会话与本地工具预约，准备原CANT/python-can、CUTIL/cansend、ETHGEN/Scapy完整输入组，不创建Windows发送后端或冒充Linux实际执行。

**Architecture:** SourceSession唯一全局取号者提供不可变PreparedSourceInput（canonical记录、保留原类型/浮点负零的内部input_json快照、原WireCodec完整分片、实际SID与本地分配时间）。先按原类型校验再序列化；message从原值快照返回脱离副本，canonical与原值快照均计入容量，线上格式不变。同一有界证据池保留exchange和prepared input；预检/编码/容量/租期失败不消耗计数。LiveToolInputBuilder持单owner锁，与SourceSession同一operation内完成本地预约、消息/介质/协议/L2/容量检查及取号，CAN复用已解析原ProtocolParser/cantools和真实python-can Message，CUTIL仅构建逐片literal cansend，ETHGEN用实际会话transport端点与显式MAC构建Scapy完整Ether/IP/UDP。OPAQUE输入与计划对象可核验/丢弃，丢弃不回退计数或释放物理预约。

**Tech Stack:** 现有Python3.12、SourceSession、ProtocolParser、WireCodec、python-can4.6.1、Scapy2.7.0与ChannelReservations；不增加依赖或驱动。

## Constraints And Interfaces

- 14冻结源/v0.3/原C/六原工具保持；41责任、17未执行Linux保持，不勾选完整M3/M4/W3或整体完成。
- SourceSession新增prepare_input(stimulus,transport,*,target_step,transaction_id=None)、verify_input(input)、discard_input(input)、prepared_inputs。输入只接受当前标准授予、适用角色/模型/消息能力、CANFD或UDP，live SessionOpen/反馈不能准备。既有dispatcher持exclusive owner时不得旁路。
- prepare_input先完整检查再推进全局sequence/transaction。PreparedSourceInput immutable bytes/tuple，message返回脱离副本；本簿身份验证拒绝伪造/外簿/旧对象，到期拒绝。容量与旧exchange共享max_records/max_record_bytes，drain_records不丢prepared inputs。discard不返还序号；abandon只取消本地prepared，不代替真实RESET/清队列/关闭。
- LiveToolInputBuilder(reservations,session,*,protocol=None,capacity=64,max_bytes=8MiB).prepare(token,stimulus,binding,*,target_step,transaction_id=None)支持CANT/CUTIL/ETHGEN SEND，只选一物理接口与一正式通道，OBSERVE/其他分支/unknown/any拒绝。
- CAN必须原ProtocolParser已完整parse且同冻结组件，正式标准FD+BRS/64字节，全部片成组准备；python-can对象每次新建，mutable工具对象不作为存储快照。cansend argv不接受用户附加参数/生成器随机值，不能用逐片进程证明周期达标。
- ETH必须同实际SourceSession transport channel、实际明确非广播/非unspecified UDP端点及非零unicast显式MAC。不伪装其他通道授权；MAC/接口/backend/qualified_channels仍需目标部署证明。
- verify/validate只验证本地对象与当前lease，不等于实际ControlOwner/target/model state/TX全局顺序/backend资格；execution_ready与authorized_to_transmit恒false，未启动Bus/sendp/原工具。post-allocation原工具异常或预约撤销时，SourceSession保留原输入组，计数不回滚，待显式检查/discard。
- Builder最多64计划/8MiB，满不驱逐，成功计划后核验预约/租期。validate只接受该builder实际对象；discard丢本地准备组，不释放物理预约，不生成标准清理反馈。实际授权/发送/反馈/时钟/步骤调度、SavvyCAN与Ostinato仍按整体计划继续。

## Tasks

### 1. Current Grant Input Groups

Files: modify `input_simulator/session.py`; create `tests/icd_gateway/test_live_tool_input.py`。
- [x] RED完整UDP/CAN输入组、正确当前SID/连续全局序号/txn、深拷贝/不可变、原帧重组；未开/到期/角色/模型/能力/反馈/live open/unsupported/非法值和capacity失败不取号。
- [x] RED共享证据容量、drain不丢输入、伪造/外簿/已discard、abandon/reopen/close、counter exhaustion、dispatcher exclusive owner保护。
- [x] GREEN peek/commit唯一取号与有界输入组，不做实际TX或应用证明。

### 2. Original Tool Input Preparation

Files: create `input_simulator/live_tool_input.py`; same test file。
- [x] RED CANT真实原库对象/FD+BRS/64bytes完整组、CUTIL literal cansend、ETHGEN显式MAC/当前部署端点/正式分片及Scapy原校验。
- [x] RED本地预约与源授予独立、未知/观察/介质/绑定/未parse协议/L2/容量拒绝；预检失败不耗序号，post-allocation失败保留原组，计划opaque/expiry/release/discard。
- [x] GREEN共享原库预检/编码，不开SocketCAN/网卡或替代后端。
- [x] 验证全部11 CAN输入与44可授予UDP输入（协议peer只作结构测试），实际UDP SessionGranted+已发布34能力准备完整视频资源组；不把peer/CAN对象/L2 bytes计实际消费者或实体发送。

### 3. Closeout

- [x] 独立只读复核、先RED再修重要发现；固定版公共入口及34选定静态、14源/663引用、41/17与不分宿主守护通过。
- [x] 写独立`artifacts/icd_gateway/w3-13-validation.json`；向唯一Linux台账追加目标授权/原库/backend/FD/L2/时序/停止及共用未完事项，完整目标保持active。

## Verified Closeout

首批12项因缺接口/模块RED后实现；后续非法对象与伪造对象入口修正。两个保真负例先RED：浮点message_id经canonical往返被接受，以及PACKED_LE负零符号位丢失；改为原类型校验与双快照后22专项4.998s通过。独立重新复核2负例/22专项/31原会话全部通过，无剩余必须修复项。固定版本公共入口561项通过（67协议27.976s、487网关272.513s、3台账、4汇总），另34选定静态、59业务/72完成/85黄金片/800RAW、pip/编译与14源/663引用通过。未启动原Bus/sendp/工具，不将测试耗时当RT资格。共用完整执行器、场景/API/Robot、实际消费者和17 Linux门禁仍未完成，不勾选完整M3/M4/W3或整体目标。

## Primary Sources

https://python-can.readthedocs.io/en/v4.6.1/message.html
https://raw.githubusercontent.com/linux-can/can-utils/master/cansend.c
https://scapy.readthedocs.io/en/latest/usage.html

以上用来核对原库构造与工具参数，不将主线文档或安装证据当Linux锁定版本/物理资格。CANT仍按原链使用cantools/python-can/SocketCAN，ETHGEN保留Scapy/Ostinato，SavvyCAN继续默认观察与受控后端后续，不新增报文转发中心。
