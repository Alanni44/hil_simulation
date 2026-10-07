# Original Scapy Transport W3.21 Implementation Plan

> Use executing-plans and TDD in the existing common checkout. Independent read-only review at the end. No commits, branches, frozen baseline changes or Windows backend substitutes.

**Goal:** 继续原W3原ETHGEN/Scapy分支，将真实Scapy二层发送接到既有SourceSession/UDPDispatcher和标准反馈，而非新增数据发生器。

**Architecture:** UDPSource仅提取原两处UDP发包为受保护的_emit_packet，默认实现保持原socket行为。ScapySource覆盖该方法，经原ETHGEN预约/明确正式channel/interface/MAC、原会话/类型/角色/模型/已公布能力/租期检查，使用Scapy SuperSocket发送完整Ether/IP/UDP/原ICD bytes；标准反馈、重组、重试/节流/全局计数仍复用原实现，不创建新的业务接收路径。默认只打开conf.L2socket，缺失直接TARGET_MISSING，没有socket.sendto回退；测试可显式注入真实Scapy SimpleSocket连接本机帧汇，资格始终未评估。

**Tech Stack:** 现有Scapy2.7.0/Python3.12/SourceSession/UDPDispatcher/ChannelReservations/ExportBinding，无新依赖或宿主OS分支。

## Constraints

- 当前Windows只验证共用发送逻辑与原Scapy库；本机SimpleSocket帧汇只是测试传输，不是Windows硬件后端/汽车以太网/实机资格。Linux默认使用同一conf.L2socket实现，后端/接口/实物/权限验证仍留唯一待办。
- 原6工具/14源/C/ICD与标准feedback端点不变，ETHGEN不冒充其他link；基类默认UDP软件入口仍单一实现。
- 使用同簿opaque SEND/ETHGEN单接口预约、对应ETH_n冻结通道、明确非零单播MAC与IPv4单播端点；预约不是标准授权。非开会话帧必须来自同一实际SourceSession当前SID/角色/型号/能力/已分配序号，发送前后检查租期；不发反馈、不绕过缺能力或控制/目标门禁。
- 整包Scapy raw send返回必须是精确字节数；短写/异常/发送后租期失效记录真实已知字节结果，不把调用成功当网卡送出或3.6已收/应用。保留不可变完整L2尝试/结果、原UDP帧、原接口/时间，默认4096/16MiB有界，在发送前预留，不驱逐旧记录。
- SourceSession、UDPDispatcher与持续证据owner的现有互斥保持；L2记录手动drain必须经同一owner锁，附有持续recorder时不允许旁路清除。L2段还未并入正式运行持久报告，不把原三流包宣称完整L2日志。
- 关闭真实二层handle并保留L2记录/原授权/预约，close只本地关闭，不释放预约或假称远端九项清理。关闭异常保留原handle可再次close，不另开socket。

## Tasks

- [x] 先RED：缺ScapySource；真正Scapy socket输出完整原Ether/IP/UDP及原ICD、四ETH映射、无普通UDP回退、构造失败资源清理、标准实际会话反馈/分发、短写/异常/撤权/旧SID/无能力/角色/负零、资源原节流、容量与关闭记录保留。
- [x] 提取UDPSource受保护_emit_packet默认发送，保持两条原路径；实现ScapySource的标准授权/原库二层发送与有限记录/关闭。
- [x] 运行原UDP/dispatcher/source-session/工具/场景和全共用回归、原14源/663引用/34静态、独立复核与实际工具报告。
- [x] 唯一台账追加Linux原Scapy权限/实际backend/interface/L2抓包及真实3.6 ingress、目标负载/停止/证据持久化；保存w3-21-validation.json和整体进度，不勾选完整W3。

## Software Verification And Boundaries

28专项16.399s、31原会话6.512s及独立26专项15.114s/31会话6.481s通过；独立发现的会话/dispatcher旁路、事务空洞和pcap句柄关闭重试均先RED再GREEN，成功close不重复关闭pcap。SourceSession只增加实际operation线程归属、默认不允许closed的内部互斥选项和单份最近已分配(mid,Header)关联；旧输入必须保留同owner准备的原UDP字节或原transport token字节，不新增线上字段或无界序号表。

固定最终742共用（67协议/668网关386.893s/3台账/4汇总）、34选定静态、59/72/85/800离线向量、14逐字节源/663引用、pip/编译守护通过；十源码/测试hash、实际工具安装状态及未完范围见artifacts/icd_gateway/w3-21-validation.json。本机真实Scapy SimpleSocket+socketpair仅证明完整帧写入本机测试帧汇，标准反馈来自协议测试peer；失败注入pcap FD不证明实际libpcap后端已可用。原Scapy默认L2socket、真实网卡/汽车以太网、3.6业务消费、物理TX/RX/RT及L2持久报告仍未资格验证，不勾选完整W3。

## Remaining Original W3

Scapy transport不是完整生产ScenarioDriver；原CAN链/工具/GUI/replay生命周期、三模式repeat/新会话/RESET/initial_inputs、模型时钟与真实probe、暂停恢复/单步复位/负例授权/九项真实清理与完整证据终点仍须共用开发。原W3完成后才恢复新增自生数据配置入口；W4/W5延期但不取消，保持41责任/17 Linux门禁。
