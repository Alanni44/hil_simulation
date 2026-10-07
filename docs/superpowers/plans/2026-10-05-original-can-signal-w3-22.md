# Original CAN Signal Sender W3.22 Implementation Plan

> Use executing-plans and TDD in the existing common checkout; independent read-only review at the end. No commits, branches, frozen baseline changes or Windows backend substitutes.

**Goal:** 继续原W3 CANT分支，把原cantools/python-can准备结果接到实际原库发送与CANFD标准反馈，不启动新增自生数据入口。

**Architecture:** 新增CANSignalSender消费同一LiveToolInputBuilder拥有的CANT plan、opaque SEND预约和明确CANFD_n/interface；会话与全局Header继续由原SourceSession管理。默认只打开python-can Bus(interface=socketcan, fd=True, ignore_config=True)，不回退其他后端；实际CAN收发采用原can.Message/BusABC、WireCodec和Reassembler，130/131按原请求与同一实际SID/sequence/transaction关联，不转中央UDP。测试显式注入原VirtualBus仅算库级软件证据。

**Tech Stack:** 现有Python3.12/cantools40.7.1/python-can4.6.1、原LiveToolInputBuilder/SourceSession/ProtocolParser与冻结ICD；无新依赖或OS分支。

## Constraints And Interfaces

- 新增input_simulator/can_signal.py与tests/icd_gateway/test_can_signal.py；默认产品后端始终SocketCAN。当前Windows不安装WSL/驱动/新SDK，不声称物理FD/BRS/仲裁/电气/RT资格。
- 构造CANSignalSender(builder, reservation, binding, bus=None, max_records=4096, max_bytes=16MiB, max_pending=64)。同本簿CANT SEND单接口预约、实际builder/完整parsed protocol、同一冻结channel/binding及真实live SourceSession必须在TX前校核；准备与本地预约均不是线上授权。
- send(plan, timeout=0.01)一次发送完整原组，不重试周期输入或修改原包；发送前预留整个有限组和完成上下文，20ms CAN重组组期限、发前发后当前租期/角色/型号/能力/原拥有bytes验证。后端send返回None只表示原API完成，不能视为网卡送出/3.6接收或应用；异常可能部分送达，保存完整原尝试及未知结果。
- receive_for(plan, timeout=0.2)只接受同一已完整TX组的CANFD标准130/131；保存原RX元数据/字节/本机时间，原20ms重组、标准关联和全局feedback去重/高水位不改。其他消息/错SID/错ACK/CRC/FD/DLC/ESI/错误帧、反馈超时均保留原失败，不制造终态或续租。仅完整关联的新鲜131对原Heartbeat从原TX起算续租。
- 所有操作由原session/builder和本发送器串行；不能绕过dispatcher独占或持续证据owner。记录有界不可变、满池不驱逐；drain不清发送上下文/序号/预约，retire(plan)显式释放本地反馈上下文，不冒充远端close。close只停本地真实bus并保留记录/预约/授权，不执行或声称九项远端清理。
- 原ChannelReservations另持有有界native CAN owner，同一预约/接口/实际bus只能有一个反馈持有者；撤销预约不提前释放仍开启的后端，原bus实际关闭成功才退休该本地owner。SourceSession持有CAN首次尝试sequence与Heartbeat transaction高水位，不随builder/发送器替换、drain/discard/retire/close重置。131没有request_sequence，故同SID心跳事务不能复用；原Header/ICD不改。
- 实际发送前预留完整组、原上下文及FAILED槽；中途发前/发后到期、撤权、native TX/RX错误和反馈超时保存原请求。有效新鲜131在验收时从原TX起算续租，取走缓存不二次续租；阻塞recv后与重组前再次校核当前授予。异常native时间戳以原IEEE位留证并拒绝，不丢收到的wire bytes。
- pending计划已从builder/source丢弃后，仍可凭发送器原保留group.plan对象身份本地retire；等值复制不能清理。close失败保留同一实际bus，重试原periodic/BCM/raw完整库清理，不只关闭raw socket。
- 11 CAN输入/2 CAN反馈与4正式CANFD通道必须软件覆盖；1ms正负10us/80ms正负1ms、真实发送顺序/跨链并发/目标clock/probe与3.6消费者仍需后续共用执行器和Linux实测。本包不是完整生产ScenarioDriver/Report，原CAN记录的持续持久化继续共用后续。

## Tasks

- [x] 先RED：缺原CANT实际发送器；真实VirtualBus完整FD/BRS原组、所有11输入/4通道、负零、真实标准反馈、旧SID/无能力/角色/伪plan/预约、无SocketCAN后端、发包/关闭失败、有界记录/上下文、原租期/组超时及所有权。
- [x] 实现单共用CANSignalSender，原builder/Session/协议复用并补实际会话/后端拥有状态；默认原SocketCAN Bus、完整实际TX/RX记录、130/131原关联/去重、有限容量与本地关闭/退休。
- [x] 跑专项、原CAN准备/协议/会话/Scapy和固定全共用回归；保留14源/663引用、34既有静态与独立复核，记录实际源码hash。
- [x] 只向linux-development-backlog.md追加原SocketCAN权限/FD/BRS/四通道/实际peer/负载/原证据持久化与停止安全要求，保存w3-22-validation.json并更新整体进度，不勾选完整W3。

## Remaining Original W3

本包不替代CUTIL/SAVVY/CANREPLAY/ETHGEN/ETHREPLAY，不移除Linux门禁；全部原工具生命周期/生产场景driver/完整三回放/重复与RESET/initial_inputs/暂停恢复/负例/真实采样/九项安全清理/完整持久Run报告继续同一代码。原W3完成前新增数据发生器保持搁置。
