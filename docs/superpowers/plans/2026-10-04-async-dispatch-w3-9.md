# Async UDP Dispatch W3.9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans and test-driven-development inline. Independent read-only review; no implementation delegation, commit, branch or worktree.

**Goal:** 完成共用多在途UDP反馈分发和非阻塞逐片资源发送，使等待资源提交时仍能发送显式/周期心跳，不改变ICD或建立Windows版本。

**Architecture:** 已批准同一源/接入路径下使用`UDPDispatcher(session)`单一协作式poll所有者，复用实际SourceSession授权/取号和WireCodec/Reassembler。UDPSource增加有界多请求匹配及单片实际TX入口，串行旧API保留；绑定dispatcher期间禁止串行源请求/放弃/取号争用。对比每请求线程与统一外置转发，推荐此共同所有者，不改变原六工具独立发送链路。

**Tech Stack:** 原Python3.12、标准socket/monotonic/perf_counter、原ResourceBudget/Contract，无新依赖。

## Invariants And Interfaces

- 原14冻结源、v0.3单文件契约、原C/六工具、41责任/17 Linux门禁不变。普通UDP是开发软件路径，不是原工具/设备资格。
- `UDPSource.receive_matching(requests:tuple, *, timeout=0.2, owner=None)->(index,reply)`仅匹配最多64原请求；同事务不同sequence的ACK分别关联，131/142/141沿用原约束。timeout0可非阻塞读最多256包；错SID/事务/nonce/hash/ACK、CRC、peer、旧序号不成为成功反馈。旧receive_for委托一项匹配。
- `UDPSource.prepare_transmission(message, *, owner=None)->token`严格校验实际TO_36并一次冻结编码，最多64个实际token；`transmit_fragment(token, index, *, owner=None)->bool`仅发送该已校验token的指定原片。资源预约与实际发出时间同时约束20Mbit/s，使用同一ResourceBudget/真实perf_counter，未到期返回false不sleep；`discard_transmission(token, *, owner=None)`仅释放本地准备/预约，不退款已消耗预算或伪造远端清理。无私有wire字段。
- `UDPDispatcher(session, *, capacity=64, max_records=4096, max_bytes=16MiB)`只接实际LIVE授予，不创建新传输owner。`submit(stimulus, *, target_step, transaction_id=None)->Header`统一取号并保存deepcopy业务和实际原编码；未发包也占容量，满在取号/TX前拒绝。
- `poll()->int`有界RX/TX/重试；可靠最多4次原码尝试，200ms ACK等待；周期消息不重传旧值。资源最终10s提交等待不占poll；超时/本地cancel均保留失败记录，不捏造接收端清理。
- 首次完整逻辑组按全局sequence发送完成后才发送下一组，不让较晚短报文越过未完成早组。已完成组等待反馈时其他输入仍可发送；重传保留原片/序号，真实丢包后的旧序号拒绝如实记录，不擅自改号。不能因只检查入队周期而忽略实际Heartbeat TX迟到。
- `enable_heartbeat(step_provider)`需要真实授予公布2及显式callable返回(sender_step,target_step)，20ms本地mono节拍，迟到超过冻结1ms jitter明确TIMEOUT不追赶；Status匹配才保守续租，真实receiver尚未实现2不得报就绪。测试协议peer不是真实模型/ClockSync证据。
- `drain_records()->tuple[DispatchRecord,...]`保留实际匹配反馈（包括RECEIVED/FAILED/141进度）、TX尝试、超时与取消。数据和错误不可变、有界预留，不静默淘汰；逻辑交换不是持久原始TX/RX/E2/E3。
- SUBMITTED保留实际请求canonical bytes，TX保留实际sendto成功的原wire片/attempt/index，RX保留真实匹配reply canonical bytes；本地时间异常使用null/SCHEMA，不能丢已发送/收到的事实。记录在内存有界，不代表持久证据包或物理TX硬件时间戳。每请求最多8条RX，收到第8条非终态时保留并BUFFER_FULL结束，满不能静默淘汰。
- `close()`本地取消在途请求，保留记录，解除dispatcher绑定后源可显式abandon/open；不等于37/38或RESET。64反馈SID真实退休/10000repeat、完整模型步执行/工具/场景/API仍属必做共同范围。

## Task 1: Multi-Request Actual UDP Matching

**Files:** Modify `input_simulator/udp_source.py`; create `tests/icd_gateway/test_dispatch.py`.

- [x] RED实际socket交错ACK/同事务/typed反馈以及timeout0/非法列表；新增接口缺失实际失败后实现，原归属仍复用原会话测试。
- [x] GREEN复用原接收校验和序号缓存，不按某一个等待者过滤其他已声明在途反馈，保留旧receive_for测试。

## Task 2: Actual Cooperative Dispatcher And Session Integration

**Files:** Create `input_simulator/dispatch.py`; modify `input_simulator/session.py` and `udp_source.py`; extend dispatch tests.

- [x] RED实际标准UDP资源34/141多请求完成；独立协议peer测试资源等待期间20ms心跳、同码4次重试/周期1次、容量预留/取号不耗尽、取消/租期/clock失败与串行互斥。
- [x] GREEN统一取号、逐资源片预约/期限、实际关联反馈和不可变有界记录；没有真实模型/时钟/工具的门禁不伪造。
- [x] 固定最终版本复测源会话31/原UDP14/资源UDP9/dispatcher21全部通过；匹配最多256原包、单poll最多64反馈/64实际TX，不静默丢记录。

## Task 3: Review And Cross-Environment Handoff

- [x] 独立只读复核，五项重要发现先RED后GREEN修复；最终独立21专项通过，无遗留重要scoped发现。
- [x] 固定源码后完整474共用（67协议/400网关/3台账/4汇总）、34选定静态、59/72/85/800、依赖/编译、14源/663引用与41/17守护通过。
- [x] 保存`artifacts/icd_gateway/w3-9-validation.json`，向唯一Linux台账追加实际网络/时钟/负载/C/原工具要求和共同未完，不覆盖历史。

## Full Scope

本包不会自行执行完整三模式回放/RESET/新会话/清队列或发送原工具文件，也不产生APPLIED/CONSUMED/E2/E3。共用完整回放/场景/负例/六工具/25API/控制台/Robot、真实消费者/正式发布及Linux C/RT/驱动/实体/真实3.3仍必做；完整目标保持active，不以本包替代W3/M3/M4。
