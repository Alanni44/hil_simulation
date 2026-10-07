# Source Session W3.8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans and test-driven-development inline. Independent read-only review; no implementation delegation, branch, worktree or commit.

**Goal:** 将实际标准会话授予接入源端统一取号/发送，为回放执行器提供真实SID与角色/能力约束，不从原捕获或本地Header自签会话。

**Architecture:** `SourceSession(transport, identity, roles, *, clock=time.monotonic_ns, max_records=64, max_record_bytes=4MiB)`拥有同一源会话的全局序号/事务、保守本地租期与有界实际交换记录。`open()`由原UDPSource.request发送新nonce/标准SessionOpen，只有实际匹配129建立会话；`allocate_header(message_id, target_step, transaction_id=None)`返回原Header用于ReplayHeader，先校验当前SID/角色/模型/公布能力再取号。`request(stimulus, *, target_step, transaction_id=None)`发送现ICD输入并记录真实反馈，不把网络完成当模型应用。`heartbeat(sender_step, *, target_step)`只使用显式真实调用者模型步，完整匹配Status后才保守续租；`abandon()`只是本地停止，绝不等于真实38/RESET或清队列。

**Tech Stack:** 原Python3.12、UDPSource/Contract/标准monotonic与secrets，无新增依赖或平台分支。

## Global Constraints

- 原14冻结源、单文件契约、59消息/45输入/14反馈、原C与全部六工具不变；41责任/17 Linux门禁保留。
- 传输请求是现有正式ICD；生产SourceSession不发布能力或安装spy消费者。测试代用peer只验证协议规则，不是C/模型/硬件/E2/E3。
- 129两层baseline、SID/header关联、accepted_roles唯一且不超请求、当前model能力均校验。新nonce/事务不复用，有限SID历史拒绝重复；重试交给原request保持原字节，不另取号。
- 本地租期从第一次open/heartbeat调用前的真实本地mono起算，不从延迟反馈收到后起算，不混接收端mono。失败/缓存/普通反馈不能续租。
- 取号不能回绕；明确事务复用供同一事务组使用，不自动将两类事务合并。target必须显式整数且符合标准范围，结构/取号不代表模型状态/目标步语义已通过。
- 未公布能力/角色、错误model、未开/过期/关闭会话在发包前拒绝；默认接收端目前只有ID1（资源worker安装时ID34），绝不伪造模型/Heartbeat/ClockSync就绪。
- UDPSource.receive_for只新增原131对2及142对33，保留现SID/transaction/序号/CRC/反向ACL，142还核对原nonce。不接收任意反馈当匹配结果。
- 有界记录含原request/reply不可变canonical bytes、本地起止mono与错误；满时发送前拒绝，显式drain后才能继续，不静默丢证据。本批记录是本机网络交换，不是持久TX片/目标E2/E3。
- 每个传输生命周期只允许一个SourceSession，close也不释放归属。绑定前原手工发送的事务号作为取号下界；绑定后send/request/receive_for只接受该owner，避免手工开会话与管理器争用反馈和取号。owner是本地API参数，不是线上字段，不改变ICD或六工具链。
- 请求deepcopy固定原业务输入（保留IEEE signed-zero）；反馈先保存独立canonical快照再读取时钟。时钟失败保留未获资格的实际反馈/错误，不建立会话或制造完成时刻。close在同一操作锁中本地放弃并关闭。

## Task 1: Standard Feedback Correlation

**Files:** Modify `input_simulator/udp_source.py`; create `tests/icd_gateway/test_source_session.py`.

- [x] RED实际UDP注入标准Status/ClockStatus：仅匹配request2/33，142错nonce、SID/事务/CRC/foreign peer/序号仍拒绝，原129/130/141行为不变。
- [x] Run `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_source_session.py -v`确认新增反馈测试失败，再实现两个标准分支。

## Task 2: Actual Source Session And Allocation

**Files:** Create `input_simulator/session.py`; extend `tests/icd_gateway/test_source_session.py`.

**Interfaces:** `open()->dict`、`allocate_header(mid, target_step, transaction_id=None)->Header`、`request(stimulus, *, target_step, transaction_id=None)->dict`、`heartbeat(sender_step, *, target_step)->dict`、`abandon()`、`close()`、`drain_records()->tuple[SourceExchange,...]`；properties session_id/roles/capabilities/last_rx_sequence与records均脱离调用方可变对象。

- [x] RED真实UDP接原Receiver的授予/拒绝/能力不足，单位测试租期起点/过期/失败heartbeat/重复SID/nonce/序号与事务/错误授予/关闭/证据容量/不可变。
- [x] GREEN依原Contract和实际transport.request实现统一会话与取号；没有APPLIED/CONSUMED/ClockSync/RESET消费者的路径保持明确失败。
- [x] 将真实授予Header接ReplayProcessor测试；这只证明真实SID来源，不关闭其模型复位/调度/工具门禁。

## Task 3: Review, Regression And Linux Handoff

- [x] 独立只读复核，重要问题先RED再GREEN修复。两种实际旧grant授权混淆分别失败复现后修复；最后独立31会话/14原UDP及实际资源TIMEOUT路径通过，无剩余重要scoped发现。
- [x] 完整`scripts/test_icd_runtime.py`453条（67协议/379网关三源/3台账/4汇总）、34静态、59消息/85黄金片/800RAW、pip/compile、14源/663引用与41/17门禁核验。修改过程中启动的混合版本运行不计通过，最终固定源码全量重跑exit0。
- [x] 保存`artifacts/icd_gateway/w3-8-validation.json`并追加唯一Linux台账/整体计划，不覆盖旧证据。

## Full Scope Retained

完整三模式模型步执行器、每轮真实RESET/初态/清队列/37/38反馈、原工具互斥/生命周期/重建文件导出、完整场景及ENGINEERING_JSONL/TCP/视频历史、25API/控制台/Robot与Linux目标/真实3.3替换仍必做。SourceSession的真实授予/取号不代表目标语义、时钟测量或执行资格。当前UDPSource最多跟踪64个反馈SID，10000repeat还需共用实际退休/有界保留策略，不能清缓存伪造序号新鲜度；这一完整执行器职责继续原计划，不标W3/M3/M4或整体完成。

当前request是串行阻塞适配器：10s资源提交等待会占用该操作，不能宣称与此同时按冻结周期持续Heartbeat。后续共用异步反馈分发/调度器必须统一取号、跟踪多个在途请求与心跳，处理真实反馈/超时/撤权/旧SID退休，再接三模式执行与原工具。真实模型边界、驱动和目标定时留Linux，但该调度器仍是一份共用实现，不能以本批串行测试代替或全部移交Linux重写。
