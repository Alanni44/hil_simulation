# Replay Packets W3.7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans and test-driven-development inline. Independent read-only review at the checkpoint; no implementation delegation, commit or new worktree.

**Goal:** 实现三种回放模式共用的实际逐包处理核心，给后续真实会话/模型步执行器提供可追溯的包，不把离线处理或外部提供的header当作在线许可。

**Architecture:** `WireCodec.rewrite(raw, transport, header, direction=None)`校验原包与新header，只修改四个标准header字段和CRC，保留原分片业务字节/顺序/填充。`ReplayProcessor.prepare(raw, history, bindings, *, model_id, declared_ids, headers=(), destinations=(), repeat_index=0)`先调用真实HistoryDecoder，按冻结窗口提取完整TO_36逻辑组，将FROM_36仅留作反馈证据；三模式分别保留原包、重新编码或逐片改码。输入header和destination只是本地分配/部署参数，不新增ICD字段，也不证明真实会话、RESET、时钟或消费者资格。

**Tech Stack:** 原Python3.12、Contract/WireCodec/HistoryDecoder/Scapy、精确Fraction时间，无新增依赖。

## Global Constraints

- 14冻结源/单文件定义、原C与六工具不变；Windows/Linux共用一份实现。
- RAW_VALIDATED仅保留当前会话待验证的原码，禁止任何header/endpoint改写，session=0的SessionOpen不能当作当前会话原码回放。
- SESSION_REBUILD改动必须被六项rewrite_fields逐项准许；业务payload字节不变，CRC改变也须明确准许。不改payload中的sender_step/资源hash/业务状态，语义合法性由真实执行门禁验证。
- REENCODE由原闭合Stimulus和现ICD生成；辅助RawBus只能此模式，需明确选用可承载44的正式UDP输出通道。
- 每次仅处理一个repeat，不将10000轮展开到内存；新会话/复位/清队列/重复间隔是后续执行职责，本模块绝不伪造。
- 完整组必须全在窗口内；窗口截断组明确FRAGMENT。反馈不注入。保持原文件包顺序，不按时戳排序掩盖跨域交错。
- 倍率以整数Fraction精确表示，无Windows sleep/墙钟RT；ONLINE1X依原Schema，仍不可执行。零可见丢包不等同完整捕获。
- 本模块不发送、启动原工具或产生APPLIED/CONSUMED/E2/E3。完整执行器/场景/API/Robot/Linux目标资格继续整体计划。

## Task 1: Payload-Preserving Formal Rewrite

**Files:** Modify `icd_runtime/wire.py`; create `tests/icd_runtime/test_wire_rewrite.py`.

- [x] RED测试全部59UDP/13CANFD消息、新header/原payload逐字节不变、原CRC/方向/格式拒绝、冻结valid_for_ms与保留字段不变。
- [x] Run `python -X utf8 -m unittest discover -s tests/icd_runtime -p test_wire_rewrite.py -v`, 缺rewrite行为失败已确认。
- [x] GREEN实现原decode校验、严格Header、原片结构复制和原CRC算法，3专项全部通过。

## Task 2: Three-Mode Actual Capture Preparation

**Files:** Create `input_simulator/replay.py`, `tests/icd_gateway/test_replay.py`.

**Interfaces:** `ReplayHeader(record_index, header)`保存不可变本地标准header；`ReplayDestination(input_channel, output_channel, source_endpoint=None, receiver_endpoint=None)`为显式部署选择；`PreparedReplay`保存原资源hash、policy hash、repeat index、不可变逐包/反馈证据、实际改写字段与pending门禁。

- [x] RED三模式实际PCAP/CAN_LOG、逆序片/重复片、反馈隔离、辅助44、窗口/倍率、header覆盖/序号/事务关联、端点白名单配置选择、未知字段与容量/无伪执行资格测试。
- [x] Run `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_replay.py -v`，缺模块失败已确认。
- [x] GREEN实现prepare，真实Decoder作为入口；输出原码/重建码hash、payload hash、原索引，重建Ethernet使用原Scapy重算IP/UDP checksum，不造另一个协议或sender。
- [x] 26专项通过：44个可回放正式UDP输入与13CANFD输入各三模式、三辅助分支、实际checksum/完整重组、窗口/倍率/顺序/重传/容量；SessionOpen由正式握手执行器负责，不能当作已授予repeat会话。

## Task 3: Review, Regression And Handoff

- [x] 独立只读review并RED/GREEN处理未指定/广播端点P2；复审26回放/3改码全部通过，无剩余重要scoped发现。signed-zero冲突原重传及实际保留payload哈希问题也已RED/GREEN修正。
- [x] 运行完整`scripts/test_icd_runtime.py`，422共用测试通过（67协议/348网关与三源/3台账/4汇总）；34选定静态、59消息/85黄金片/800RAW、pip/compile、14逐字节源/663引用均通过。目标资格未验证。
- [x] 2026-10-04收尾保存实际验证报告`artifacts/icd_gateway/w3-7-validation.json`，追加唯一Linux台账及整体计划阶段记录，不覆盖旧证据。

## Remaining Full Scope

本阶段为逐包处理核心，不是完整三回放执行器。实际SessionGranted/序号分配/角色/新鲜度、RAW当前SID与target、每轮RESET初态/清队列、新会话、模型步调度/反馈/取消、原工具停止反馈/互斥、真实ClockSync/RT均继续共用执行器和Linux门禁；还包括ENGINEERING_JSONL回放、重建CAN_LOG/PCAP文件导出及原工具生命周期、TCP/视频历史、完整场景、25API/控制台/Robot与真实3.3替换。整体目标保持active。

## Output Semantics

`ReplayHeader`包含原DecodedHistory.records索引与原标准不可变Header；`ReplayDestination`包含输入/输出通道及一对显式UDP端点（或都None采用冻结部署初值）。它们是本地准备参数，不是ICD字段，不证明目标白名单已安装。任何新会话分配必须排除整个捕获的SID（包括窗口外记录）；同一原请求的完整重传使用同一个新Header，原payload hash也须相同，非零原事务必须一对一映射，避免分裂/合并。所有业务语义及真正会话期限仍待真实执行验证。

`ReplayPacket.original_sha256`为该原捕获包/日志行原bytes的SHA256；`rebuilt_sha256`只在存在完整capture_bytes时有值。原码完整保留原容器包bytes；重建Ethernet保留原L2/IP字段并重算长度/校验；重建CAN_LOG尚无完整日志行导出，capture_bytes/对应hash为None，不用CAN业务帧哈希冒充日志文件哈希。`original_wire_sha256/rebuilt_wire_sha256`始终针对业务UDP原bytes或CAN_ID两字节LE加CAN data，彼此可比较；整个原文件hash保留在decoded.capture.source_sha256，尚未生成整份重建文件hash。

`original_payload_sha256`保留原完整业务payload或辅助raw数据hash；`payload_sha256`为输出完整标准业务payload。RAW/SESSION_REBUILD直接保留原payload hash（包括IEEE754 signed-zero）；REENCODE按闭合Stimulus重新编码计算hash，辅助44的raw数据hash与正式44结构hash不能混称相同。时间为精确Fraction，保留文件索引顺序，初始配置窗口不是运行中的seek，当前没有运行游标/动态seek API，也不声明ONLINE发送。

默认单轮最多100000输出包、64MiB计费输出bytes；不展开10000repeat、不修改原8MiB重组预算，不把此门限声称为总RSS。新增依赖为零。PreparedReplay.execution_ready恒false，require_execution_ready明确STATE拒绝；缺真实消费者、会话/时钟/工具资格时不会产生TX/APPLIED/CONSUMED或E2/E3。
