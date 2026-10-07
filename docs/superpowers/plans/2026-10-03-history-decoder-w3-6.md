# History Decoder W3.6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans and test-driven-development inline. No implementation delegation, branch, worktree or commit. Independent read-only review is required at the checkpoint.

**Goal:** 将实际CAN_LOG/PCAP/PCAPNG捕获关联到冻结HistoryStream，解码完整标准业务消息与闭合RawBus工程量，保留原片字节/顺序/时钟来源，为三模式执行器提供输入，不伪造会话/实际时钟或模型应用资格。

**Architecture:** 新增`input_simulator/history.py`，`HistoryDecoder(contract).decode(raw, history, bindings, *, model_id, declared_ids) -> DecodedHistory`。`CaptureBinding(stream_id, channel_id, clock_domain, capture_interface, clock_id, raw_to36_capture_direction=None)`是本地部署关联，不是ICD字段；stream_id引用原HistoryStream，clock_id显式标识同一时钟来源，不靠文件名/网卡RxTx猜业务方向。每个捕获时钟域串行使用原WireCodec/Reassembler，独立处理并清除域状态，保持原8MiB/64-slot边界与不跨域拼片；输出按原逻辑传输首次packet index排序，不按时间排序。`SourceInputAuditor.audit(..., capture_bindings=None)`默认容器分析行为不变；提供显式绑定时解码，CLI `--capture-bindings`只读取本地关联文件。

**Tech Stack:** 原Python3.12/Scapy/python-can、Contract/WireCodec/Reassembler/json_codec，新增无外部依赖。

## Global Constraints

- 保持14冻结源/单文件完整输入契约、59消息/45输入/14反馈、原C与六工具；Windows当前宿主，共用代码Linux复测。
- Binding是现有部署白名单中通道/接口/时钟的本地选择，不新增业务字段、私有报文或模拟器专用接收规则。严格未知键拒绝，显式CLI不从ResourceRef.file_name推断路径。
- 正式CANFD由应用ID和正式CRC/版本/方向/标准FD+BRS/64字节判定；原channel必须CANFD。ETH正式UDP同时核对实际双向端点/端口/无tag与应用方向，缺/错方向拒绝；本包使用冻结部署初值，实际白名单端点变更须后续共同部署配置扩展，不静默放行。
- 普通CAN和辅助CANFD仅冻结RawBus44闭合ID/DLC/非RTR规则；CAN辅助方向必须有显式capture point方向绑定且实际RxTx符合，未知方向拒绝。ETH辅助36150仅同channel源/接收端点与TTL/长度的RawBus Stimulus。RawBus工程量不虚构原正式Header，RAW_VALIDATED/SESSION_REBUILD不能拿它当已捕获正式包。
- FROM_36记录只有message，绝不产生Stimulus；TO_36完整消息提取Stimulus并执行原model gate。全部59业务对象都按原Schema/packed/JCS等解码，不改变帧格式。
- Capture原整数ns减显式HistoryStream.epoch_ns，域内不回拨、不负数；同clock_id的clock/epoch必须一致，不同clock_id不能混算时间窗。MODEL_STEP只有显式模型步时间且offset与target_step*1ms一致才可解码，不拿普通PCAP秒时戳猜模型步。声明clock/uncertainty不代表实际测量或ClockSync通过。
- 同一逻辑消息以首次观察片的offset为起点，保留全部原packet indices/frames，完成offset独立保存。完整重复传输保留，不授权其session或fresh sequence；残组/过期/冲突拒绝。不同domain绝不拼成同组，不重排原片。
- 完整logical解码要求全部packet可识别并完整，truncated片继续用无bindings的OFFLINE容器入口分析，不冒充完整解码。完整逻辑记录计数/实际message_ids必须匹配每个声明stream。捕获loss下界或声明不完整在任何ONLINE policy拒绝，OFFLINE完整可读片仍可解码但complete_capture=false。零loss不证明完整capture，complete_capture保持null。
- 新代码只离线解码：execution_ready=false、CLOCK_MEASUREMENT/SESSION/TOOL_CONSUMER仍pending，不产生APPLIED/CONSUMED/E2/E3。三种执行器、完整视频流/TCP业务提取和场景执行继续原共用责任，不标完整W3/M3/M4完成。

## Task 1: Actual Logical History Decoder

**Files:** Create `input_simulator/history.py`, `tests/icd_gateway/test_history.py`.

- [x] RED availability与全部59消息原CANFD/UDP捕获解码、实际CRC/方向/端点、RawBus三分支、immutable/原片顺序、epoch/clock/stream-count/model/容量与残组测试。运行`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_history.py -v`证明缺实现失败。
- [x] GREEN实现显式本地binding、按域串行原库重组及闭合RawBus提取。结果`HistoryRecord`保存原message/stimulus canonical bytes（属性返回副本）、capture packets索引、起始/完成offset及channel/clock；`DecodedHistory`保存真实Capture，始终不可执行。
- [x] 逐条失败复现并修复边界，不放宽原formal decoder；23专项通过（含59 UDP/13 CANFD循环、三辅助分支），模型缺失与重复rewrite字段公开入口均已RED/GREEN修正。

## Task 2: Audit And Actual File CLI Integration

**Files:** Modify `input_simulator/source_inputs.py`, `tests/icd_gateway/test_source_inputs.py`.

- [x] RED显式bindings时审核实际capture取得逻辑记录与独立report；无bindings行为保持；真实CLI显式sidecar路径、未知键/失败退出、FROM_36不变Stimulus、不产生执行资格。
- [x] GREEN `audit(..., capture_bindings=None)`及`--capture-bindings`共用HistoryDecoder；本地JSON bindings是上述六键严格数组，由同一`CaptureBinding.from_document`解析。不改SourceInputs或正式API Schema。report保存bindings实际canonical bytes hash，标clock_measured=false与输入/反馈/辅助分别计数。
- [x] 39三源与CLI测试通过；TCP/HIV1/普通未知总线明确拒绝完整业务解码而不标发送资格。

## Task 3: Review, Verification And Linux Handoff

- [x] 只读独立review，发现跨接口文件交错被全局previous误判回拨的P2，先RED复现再改逐域时钟检查；独立23解码与39审核测试通过，原probe返回原offsets[100,0]/indices[(0,),(1,)]且不可执行。同域回拨仍拒绝，无剩余重要scoped问题。
- [x] 最新完整共用入口393条（64协议/322网关三源捕获历史/3台账/4接口汇总）、codec黄金、34选定静态、pip/compile、14 byte-exact/663refs、源码hash、41责任/17 Linux门禁通过；真实证据记录`artifacts/icd_gateway/w3-6-validation.json`，不覆盖历史报告或运行写回冻结源的QA生成脚本。
- [x] 唯一Linux台账追加真实捕获/绑定/时钟源/声明uncertainty与测量、RAW/重建执行器、原工具/模型边界及性能验证；17门禁未实测不勾选，整体目标继续active。

## Closeout

本包完成完整正式CANFD/UDP业务与闭合RawBus的捕获离线解码，不是完整HISTORY/回放执行器或实际时钟资格。393共用/34选定静态回归和独立23解码/39审核复核通过，原14源/41责任/17门禁保持。下一共用任务继续三模式执行、原六工具封装、完整场景/API/Robot以及TCP/视频历史关联；真实Linux/模型消费者、实体与真实3.3替换门禁没有通过。

## Design Review

沿用已批准2026-10-02设计及冻结契约4.3，无第二ICD或平台分支。关联必须显式配置的方案优于按接口名/文件名/RxTx猜测；冻结SourceInputs没有capture物理绑定键，不能加入其中。不同域的相同clock_id是显式离线时钟来源声明，不是测量证据；实际跨机同步、在线session新鲜度与工具资格只由后续原门禁证实。
