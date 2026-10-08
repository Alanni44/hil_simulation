# Common Assertion Window W3.16 Implementation Plan

> **For agentic workers:** Use executing-plans/TDD inline with independent read-only review. No implementation delegation, commits, branches, worktrees or frozen QA generation.

**Goal:** 按已批准W3与冻结契约第3/11章落实八种Assertion比较、WAIT/ASSERT窗口和原探针绑定检查，接入共用场景编译，不由本地比较自签E1/E2/E3。

**Architecture:** assertion.py提供不可变AssertionSpec.compile(contract,assertion,*,model_id)和AssertionWindow(spec,*,start_step,mode,max_records=4096,max_bytes=4194304)。observe(model_step,sample_sequence,value)只消费明确标量候选样本，保存原值/计步/序号，不解析任意内存路径；poll(model_step)推进比较期限。结果PENDING/MATCHED/MISMATCH/TIMED_OUT只属比较状态，evidence_status恒NOT_EVALUATED，真实标准Evidence关联/探针资格/采集器和场景运行状态机继续同一后续代码。

**Tech Stack:** 原Python3.12、dataclasses/json/math/re、Contract、ScenarioPlan；无新增依赖。

## Constraints

- Windows/Linux单代码；14冻结源、原C与六工具、41责任/17未执行Linux不改，不勾选完整W3/M4或整体。
- Spec先原始Schema/类型校验，显式实际三型号；probe_catalog身份匹配。模型探针必须同型号且field_path等于已登记target，固定数组须唯一明确零基索引/界限；expected类型须匹配double/bool。消费者probe须同message_id，其具体采集路径留真实reader校验；不能将语法检查当实际字段读取资格。E2不允许NO_PROBE。
- EQ/NE为严格类型对应相等/不等（int/float同属有限数值，bool不等于1），LT/LE/GT/GE为数学比较；只有WITHIN和数值EVENTUALLY使用abs(actual-expected)<=tolerance。非数值仅EQ/NE/EVENTUALLY且tolerance必须0。不补默认值、不clamp、不把NaN/Infinity或孤立代理项记为合格样本。
- 半开期限[start_step,start_step+timeout_steps)，溢出拒绝。ASSERT普通比较首个不满足即MISMATCH，满足sample_count个新样本才MATCHED；EVENTUALLY和WAIT允许在期限内等待，任一不满足重置连续计数。WAIT只提供比较窗口，冻结后续事件/模型继续由真实状态机负责，不以此模块冻结模型或发送数据。
- 显式model_step非递减；独立实际采样sample_sequence严格递增，重复/回退不能增加sample_count，同一模型步多个真实新样本合法（暂停模型的probe亦须新采集）。poll跨到期为TIMED_OUT，无样本不通过；终态不可用新样本覆写。drain只释放本地记录/字节，不重置序号/步/连续计数/终态。
- 默认4096/4MiB，最大1000000/64MiB；容量/非法值/序号/时钟预检不删除既有记录或改变计数。最大sample_count仍由调用者实际排空或提升有界容量，不 silently drop。
- ScenarioPlan保存所有root/WAIT/ASSERT编译spec，原三源report追加计数，执行准备仍false。消费者路径、available_probes资格、标准SID/request/trace/hash/140原码关联仍未完成；比较结果绝不是正式business_result PASS。

## Tasks

### 1. Compile And Compare

Files: create input_simulator/assertion.py, tests/icd_gateway/test_assertion.py.

- [x] RED缺少Spec/Window；八操作、numeric/bool/string/精确边界与有限性、原值保真/脱离副本、型号/probe/目标/数组/expected类型校验。
- [x] GREEN AssertionSpec.compile/compare；所有本地状态evidence_status=NOT_EVALUATED、execution_ready=false，不生成wire反馈。

```python
spec = AssertionSpec.compile(contract, assertion, model_id='quadrotor_hil')
assert spec.compare(1) is True
assert spec.execution_ready is False
```

### 2. Bounded Window And Common Integration

Files: same new module/tests; modify input_simulator/scenario.py and source_inputs.py.

- [x] RED ASSERT普通失败/累计成功、EVENTUALLY连续/重置、WAIT非EVENTUALLY等待、到期/无样本、严格整数/重复/回退/暂停新样本/溢出、终态和drain不重置。
- [x] GREEN有界原值Observation快照与纯比较窗口；预检原子、poll不制造样本；无实际证据生产。
- [x] RED所有root与WAIT/ASSERT spec接入原时间表/源审核，拒绝错误型号probe或路径；GREEN保存编译结果/计数，不改变原资源/回放/工具/ICD。

```python
window = AssertionWindow(spec, start_step=100, mode='WAIT')
window.observe(model_step=100, sample_sequence=1, value=0)
window.observe(model_step=101, sample_sequence=2, value=1)
assert window.status == 'MATCHED'
assert window.evidence_status == 'NOT_EVALUATED'
```

Run: `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_assertion.py -v`, 21旧场景/14波形/39源及固定最终公共入口。

### 3. Review And Append-Only Handoff

- [x] 独立只读复核/重要问题RED再修；34选定静态、14源/663引用、41责任/17Linux、pip/编译/同代码守护。
- [x] 新建artifacts/icd_gateway/w3-16-validation.json；追加唯一Linux台账及整体进展，核对旧prefix/hash与最终源码hash。Linux真实reader/available_probes/标准140关联、暂停新采样、模型步/跨机时钟、WAIT超时/九项清理移交L-002/L-004/L-010/L-011/L-013/L-014/L-017。

## Verified Closeout

2026-10-04：缺少Spec/Window及审核接入先RED后实现；公开窗口spec/start/mode/deadline可重赋值的回归先RED再改只读属性。16断言专项8.884s、21旧场景12.029s、14波形8.834s、39三源34.844s通过；独立16专项9.038s/21场景12.175s和容量/时钟/类型/路径等附加探针通过，无剩余必须修复scoped问题。固定最终源码公共入口612共用（67协议/538网关305.372s/3台账/4汇总）及34选定静态、59/72/85/800、pip/编译、14逐字节源/663引用守护通过。阶段报告保存五源码/测试hash及剩余范围；追加后旧台账50193 UTF16字符prefix与normalized UTF8 SHA256完全一致，41责任/17未执行Linux及五hash已核对，3台账/4汇总与git diff --check再次通过。本阶段不是实际Evidence/WAIT运行或完整W3/M4验收。

## Full Scope Remains Required

真实场景状态机、全部事件/原工具授权发送、已资格确认实际探针reader、标准Evidence关联/持久证据、WAIT阻塞/超时清理、负例与回放完整执行、25API/控制台/Robot、C/模型/设备/RT及真实3.3平滑替换保持完整目标。纯比较模块提供下层规则，不替换真实证据或缩小最终验收。
