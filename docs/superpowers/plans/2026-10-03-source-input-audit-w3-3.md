# Source Input Audit W3.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Follow test-driven-development; no implementation delegation, branch, worktree or commit is authorized by this plan.

**Goal:** 按冻结v0.3接入三类输入的结构、基线、资源字节和工程量历史校验基础；不把基础校验包装为完整W3或可执行运行。

**Architecture:** Contract复用原Schema与已验证四组件哈希。input_simulator.source_inputs对完整SourceInputs和显式resource_id到bytes映射作无发送、副作用的离线审核，输出不可变快照。CLI只读取管理员显式资源映射，不按用户file_name拼路径，不创建会话、发数据或调用模型。

**Tech Stack:** 单一Python3.12、既有jsonschema/JCS、标准库hashlib/dataclasses/argparse；不引入Windows后端或从静态QA vendor导入依赖。

## Global Constraints

- 原14源文件和汇总不改；HIL-ICD-1.0指纹不改；不增加线上字段。
- 所有结果为SOURCE_INPUTS_AUDITED_NOT_EXECUTABLE，execution_ready=false。本包不产生VALID运行、APPLIED/CONSUMED或E2/E3。
- 原六工具链保留。实际DBC/cantools、ARXML、CAN_LOG、PCAP/PCAPNG解析、场景所有执行语义、负例授权/变异、真实时钟/会话重建/恢复/清理仍由共用后续包完成，不全部转Linux重写。
- SOURCE_INPUTS结构必须覆盖全部事件分支和资源字段；缺失/未知字段拒绝，不补默认值。
- 默认每资源64MiB、总128MiB、输入文档16MiB、JSONL最多100000行/每行131072字节为本地可配置部署门限，不改Schema容量、不宣称RSS/实时资格。
- CLI路径仅来自显式资源映射，冻结原resource_id/file_name不必同名。审核后实际执行必须使用审核字节或重新读原文件核验，不能凭报告放行变更文件。
- 每阶段追加唯一linux-development-backlog.md，保留41条责任、17条目标门禁和全部历史。

## Task 1: Contract Source Validation

**Files:** Modify icd_runtime/contract.py; Create tests/icd_runtime/test_source_contract.py.

**Interfaces:** Contract.component_hashes返回已验证load原组件哈希的副本；Contract.validate_source_definition(name,value)只允许SourceInputs、ProtocolSource、ScenarioSource、HistorySource、ResourceRef、ReplayPolicy、HistoryStream、Event、Assertion、Cleanup；Contract.validate_stimulus(value,model_id=None)验证45种TO_36 Stimulus，不接受Header/反馈。

- [x] RED: 测试公开方法存在；原SourceInputs结构通过且不变；逐必填删除/未知键/反馈Stimulus/错模型/uint64溢出拒绝；四组件哈希副本不能改内部状态。
- [x] Run `python -X utf8 -m unittest discover -s tests/icd_runtime -p test_source_contract.py -v`，确认缺方法失败。
- [x] GREEN: load保留actual哈希；按封闭白名单缓存原Schema validators；Stimulus按原分支缓存，不建立第二Schema。
- [x] 运行相同命令通过，原运行库回归通过。

## Task 2: Three-Source Byte Audit And Engineering JSONL

**Files:** Create input_simulator/source_inputs.py; Create tests/icd_gateway/test_source_inputs.py.

**Interfaces:** `SourceInputAuditor(contract,max_resource_bytes=67108864,max_total_bytes=134217728,max_records=100000).audit(inputs,resources,model_id="quadrotor_hil") -> SourceInputAudit`；resources为显式Mapping[str,bytes]，不是文件名推断。model_id可按原目录选择三模型。SourceInputAudit含不可变input_json、resource evidence、decoded engineering records、pending_checks和固定execution_ready=false；属性返回新副本。

- [x] RED: 真实原ICD/DBC资源通过字节哈希；错误整体/组件指纹、缺ICD/DBC、重复资源ID、实际size/hash、未知消息、未声明Stimulus、错模型失败；保留原源码和输入。
- [x] RED: 场景ID命名空间、FAULT限制、非数值断言、周期STOP引用校验；完整Event仍通过原Schema，高级调度/写目标冲突/波形/负例/探针语义列pending，不标执行通过。
- [x] RED: HISTORY基线、流ID、消息方向、重复重写字段、start/end及ONLINE完整性规则；ENGINEERING_JSONL真实逐行封闭对象/UTF8/uint64/非递减/完整Stimulus/实际记录数与ID、捕获范围。多流无法唯一归属拒绝，不补流ID；RAW/SESSION_REBUILD工程量资源不冒充原码重放。
- [x] Run `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_source_inputs.py -v`，确认实现不存在/行为失败。
- [x] GREEN: 完整验证后形成canonical immutable snapshot，资源默认有界；非工程量历史保留字节核验结果并明确parser pending，不能标decoded/ready。
- [x] 运行相同命令通过，补边界/资源上限/快照不可变和全三源组合测试。

## Task 3: Offline Entry, Review And Handoff

**Files:** Add CLI to input_simulator/source_inputs.py; add CLI tests in tests/icd_gateway/test_source_inputs.py; append overall plan and Linux ledger; Create artifacts/icd_gateway/w3-3-validation.json.

- [x] RED: 独立进程使用真实显式路径读取输入与资源；合法返回固定不可执行状态，缺/错资源exit1；不需要网络/会话参数、不读取file_name派生路径。
- [x] GREEN: `python -m input_simulator.source_inputs`接收必填`--contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 --model-id quadrotor_hil`及管理员提供的`--inputs-file`、`--resource-map`路径。映射严格JSON对象resource_id到显式路径，读取有界，输入/资源不写回。实际文件/独立进程验证在test_source_inputs.py的SourceInputCLITests完成。
- [x] 独立只读复核，修复重要问题后复测。
- [x] `python -X utf8 scripts/test_icd_runtime.py`、`python -m pip check`、compileall、git diff --check；运行台账41条/17条证据守护与14文件逐字节检查。
- [x] 记录实际测试计数、命令、哈希及未完边界，追加L-002/L-005..009/L-010/L-011/L-014要求，不勾选任何Linux门禁或完整M3/M4。

## Full-Scope Continuation

本包是W3输入审核基础，不缩减已批准W3：共用后续实现原DBC/ARXML及所有捕获解析器、完整场景步执行/碰撞/波形/周期/WAIT/断言/授权负例/结束清理、三种回放模式及真实会话重建、六工具封装/互斥/反馈、25管理API/控制台/Robot/证据。Linux接实际原工具/C模型/设备/时钟并验证，不开发第二版本。整体41项和17门禁必须全部实际完成，当前完整开发目标保持进行中。

## Verified Result

本包基础范围完成，不是完整W3或运行资格。最新同一公共入口319条（64运行库、248网关/源、3台账、4汇总）通过，另34条既有选定静态回归通过；39条专项经独立复测。审核器固定不可执行，实际工具/模型/资源激活及17 Linux门禁未执行。原14源逐字节一致，全部历史报告保留；报告`artifacts/icd_gateway/w3-3-validation.json`记录准确命令、计数、源码哈希及未完责任。
