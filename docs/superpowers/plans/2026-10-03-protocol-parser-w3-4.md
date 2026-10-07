# Protocol Parser W3.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and test-driven-development. No implementation delegation, branch, worktree or commit is authorized.

**Goal:** 将原PROTOCOL的ICD_JSON、Schema和DBC从字节审核推进到真实解析及原工具帧编码，接入现有三源审核入口，不产生执行资格或平台分支。

**Architecture:** 新增input_simulator.protocol的ProtocolParser与不可变ProtocolDescriptor，使用独立依赖cantools解析DBC/ARXML，再按冻结CANFD目录逐字段核对；DBC只负责传输帧位布局，WireCodec仍独占CRC、分片/业务/会话校验。SourceInputAuditor调用解析并保存描述，不让可变cantools对象成为未验证协议权威。

**Tech Stack:** Python3.12、cantools40.7.1（沿用独立静态参考版本）、既有Contract/WireCodec/标准库；所有新增及传递依赖写入requirements-icd.txt，不触碰旧HIL环境或冻结14源。

## Global Constraints

- HIL-ICD-1.0/v0.3不改。13种CANFD帧、64字节、标准11位ID、FD+BRS、24字节头、38字节chunk、CRC offset62均来自原目录；每帧全部50信号必须等价（11头字段、38数据字节、1 CRC）。
- DBC/ARXML定义不作为CAN数据发送。解析不产生授权、Linux/实物资格、APPLIED/CONSUMED/E2/E3或execution_ready=true。
- 实际ICD_JSON/DBC必须匹配已验证load的原组件哈希；ARXML为补充导入，其全部解析帧必须等价，不接受另一个业务基线。XML实体/DTD拒绝、输入有界、未知资源格式不默默标解析成功。
- 可变解析器对象不能被外部修改后绕过等价检查；对外描述只用tuple/bytes/frozen dataclass。帧decode/encode通过WireCodec正式校验后再用cantools证明位布局，不把cantools.decode当正式接收。
- 原六工具和C保持；SocketCAN/can-utils/SavvyCAN/canplayer/Ostinato/Scapy/tcpreplay真实发送及RT/模型步等继续Linux移交。现阶段纯库在Windows运行不是Windows专用工具链。
- 保持整体41任务/17 Linux责任，阶段完成向唯一linux-development-backlog.md追加证据及尚未完成的共用解析器/执行器责任。

## Task 1: Actual DBC Parser And Immutable Frame Description

**Files:** requirements-icd.txt; Create input_simulator/protocol.py; Create tests/icd_gateway/test_protocol.py.

**Interfaces:** `ProtocolParser(contract).parse(protocol_source, resources) -> ProtocolDescriptor`，显式ID到原bytes映射；`ProtocolDescriptor`含原baseline_sha256、资源hash、13个不可变FrameDefinition及每帧50信号描述；解析器提供`encode(message) -> tuple[CANFrame,...]`、`decode_frame(frame,direction=None) -> Fragment`，正式规则不变。

- [x] RED: 测试真实冻结DBC解析及描述；未知/重复帧、名称/ID/周期/FD/长度/信号offset/width/order/signed/scale/offset/range/choices/multiplex漂移拒绝；CAN全部黄金向量与WireCodec逐字节一致。
- [x] 运行`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_protocol.py -v`，确认缺失实现失败。
- [x] 锁定cantools及解析器传递依赖；`python -m pip install -r requirements-icd.txt`只进入runtime/icd-venv；实现真实strict load_string和逐项对照，错误转ICDError，不自己解析DBC文本。
- [x] 同一命令GREEN；所有13消息和多分片/反馈/故障编码通过黄金及正式拒绝测试。

## Task 2: ARXML Equivalence And Source Audit Integration

**Files:** input_simulator/protocol.py; input_simulator/source_inputs.py; tests/icd_gateway/test_protocol.py; tests/icd_gateway/test_source_inputs.py.

- [x] RED: ARXML实际cantools解析后对照同一冻结帧定义；错/缺布局、XML实体/DTD、过大文件、无真实DBC、错hash明确失败，不把有效XML结构当等价通过。
- [x] RED: SourceInputAudit包含不可变真实protocol描述；基础ICD_JSON/DBC解析成功不再保留PROTOCOL_TOOL_PARSING，其他未解析格式仍明确pending且恒不可执行。
- [x] GREEN: 使用同一资源审核原bytes，不改线上输入字段；ICD_JSON真实loads+原目录等价，Schema继续由外部pin加载；ARXML解析器不是另一个业务协议入口。
- [x] 焦点测试、所有三源审核/真实CLI测试通过；原frame metadata/CRC/方向等规则不被解析器绕过。

## Task 3: Review, Full Regression And Linux Handoff

- [x] 独立只读复核新解析器、依赖、接口集成和测试，重要问题先RED/GREEN修复。
- [x] 最新`python -X utf8 scripts/test_icd_runtime.py`、原codec黄金CLI、34选定静态回归、pip check、compileall、git diff --check和14源逐字节检查通过，保存实际命令/计数/版本/源码哈希到artifacts/icd_gateway/w3-4-validation.json。
- [x] 追加唯一Linux台账L-001/L-002/L-005/L-006/L-007/L-013/L-014/L-017。仅已证明协议解析完成；CAPTURE解码、场景全部执行/三回放模式/六工具封装/管理API/Robot/真实消费者及所有目标门禁继续原范围，完整目标保持active。

## Closeout

2026-10-03：339项共用入口测试、34项选定既有静态回归及14源逐字节检查通过；独立17协议/32审核与CLI复测通过。ARXML只支持本阶段严格R4基线frame profile，不宣称完整XSD或任意复杂AUTOSAR。两项复核问题已先RED再修复原XML精确系数/范围和PDU偏移/长度/更新位校验；极高精度周期也在进入浮点投影前拒绝。未改原C/六工具或冻结输入/线上契约，未执行Linux门禁；本工作包完成不等于整个W3或完整目标完成。
