# Common Scenario Timeline W3.15 Implementation Plan

> **For agentic workers:** Use executing-plans/TDD inline. Independent read-only review is required; no implementation delegation, commits, branches, worktrees or frozen QA generation.

**Goal:** 继续已批准W3场景设计，将全部十类Event编译为不可变、可排序的共用惰性时间表，真正拒绝已注册完整消息的同端口同一步碰撞，保留真实WAIT/反馈/授权/清理执行边界。

**Architecture:** 新增scenario.py的ScenarioPlan.compile(contract,scenario,*,model_id,history_id=None,max_collision_checks=100000)，从原绑定解析完整Stimulus写入集合，保存原类型快照、WaveformSampler及有限等差流。iter_actions(start_step=0,end_step=UINT32_MAX,max_actions=100000)先核对精确区间数量再惰性合并，不展开1000000次周期或86400000步波形。全部十类事件均保存；WAIT/ASSERT/REPLAY/NEGATIVE_SEND/END_CLEANUP是明确待真实handler处理的控制请求，不作为已执行结果。原三源审核暴露scenario_plan，仍不可执行。

**Tech Stack:** 现有Python3.12、dataclasses/json/math/heapq、Contract、WaveformSampler、SourceInputAuditor；不增加依赖。

## Global Constraints

- 单一Windows/Linux代码，冻结14源、原C和六工具不动；41责任/17未执行Linux保留，不勾选完整W3/M4。
- 按(at_step,priority,event_id)升序。重复event/sender/assertion命名空间拒绝；PERIODIC_STOP须对应先前同链路START；FAULT只限11/12/13/26/45。整数不能用浮点或bool归一化。
- SEND/FAULT/WAVEFORM/PERIODIC_START/NEGATIVE_SEND的合法Stimulus保留完整payload和原数值类型/负零；负例仍未变异、未授权、未发送。只接受定义的T02/T05/T06 case名称不意味着case已启用。
- 根7..19依原ModelBindings分组及target_field展开完整消息写入集合，数组逐元素、bool也计写入。两波形即使修改不同字段也发送完整消息，仍可能碰撞；不同工具/消息ID映射同实际字段也拒绝。其他消费者/REPLAY实际端口尚未接入，明确pending而非虚构无碰撞或执行ready。
- 周期START第一份在at_step，其后按period/count；STOP在同一步按排序键截断尚未到达的周期份。波形从起点按sample_period采样，外层末步补一次精确终值（若不整除），之后由模型保持，不无限发送。END_CLEANUP应为最后静态事件，按键截断所有未来流；不编造已完成九项清理。无显式END时root cleanup仍须真实执行器在终态执行。
- 有限等差流碰撞用gcd/模逆计算交点、按实际端口去重比较；最多100000次比较，超限CAPACITY而非忽略。所有末步uint32检查；有限输出容量先验检查，不能产出有成功外观的截断计划。
- 原快照总上限16MiB；待执行动作无Header/sequence/标准授予/E1/E2/E3。离线时间表不是推进模型或运行WAIT；实际执行器须在WAIT阻塞后续、保留实际模型运行，禁止将iter_actions直接发送。

## Tasks

### 1. Frozen Event Compilation And Lazy Expansion

Files: create input_simulator/scenario.py, tests/icd_gateway/test_scenario.py.

- [x] RED缺少ScenarioPlan；十事件排序、快照不变、全部完整payload/负零、严格型号/整数/命名空间/FAULT/STOP/REPLAY引用与负例case规则。
- [x] RED周期计数/STOP同一步次序、波形精确末步、END截断/非最后拒绝；百万周期和最长波形不展开，输出预检CAPACITY及uint32溢出。
- [x] GREEN不可变ScheduledAction/等差stream/ScenarioPlan；控制动作needs_runtime_handler=true，execution_ready恒false。

```python
plan = ScenarioPlan.compile(contract, scenario, model_id='quadrotor_hil')
actions = tuple(plan.iter_actions(start_step=0, end_step=1000, max_actions=100))
assert all(not action.execution_ready for action in actions)
```

Run: `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_scenario.py -v`.

### 2. Complete Snapshot Target Collisions And Source Integration

Files: same scenario.py/tests; modify input_simulator/source_inputs.py and valid nonoverlapping fixture in test_waveform.py.

- [x] RED SEND同一步跨工具、7/14同端口、波形不同修改字段、周期/静态及两个互质周期后续交点均拒绝；不相交等差流/STOP截断可通过；比较预算不静默跳过。
- [x] GREEN完整root绑定target_field集合及算术有限流相交，不把link_id/message_id/被修改单字段当互斥键；未解析consumer目标明确pending。
- [x] RED原审核入口拒绝完整消息碰撞且暴露不可变scenario_plan；GREEN保持原资源/Protocol/History审核和compiled waveforms，无wire/ready变化。

```python
audit = SourceInputAuditor(contract).audit(inputs, resources, model_id='quadrotor_hil')
assert audit.scenario_plan is not None
assert audit.report()['scenario_compiled'] is True
assert audit.execution_ready is False
```

Run: 当前专项、14波形、39源专项和完整公共入口。

### 3. Review, Verification And Append-Only Handoff

- [x] 独立只读复核；必要问题先RED再GREEN；固定最终版完整公共入口、34选定静态、14源/663引用、41责任/17 Linux、pip/编译/同代码守护。
- [x] 新建独立artifacts/icd_gateway/w3-15-validation.json，源码/测试hash与准确命令/范围；追加唯一linux-development-backlog.md和整体进度，核对历史prefix不改写。
- [x] 追加Linux真实端口身份/跨工具、真实模型步/晚步策略/周期负载、WAIT不冻结模型/真实反馈、全清理与同代码资格至L-002/L-004/L-010/L-011/L-013/L-014/L-017。完整执行器/全部实际消费者/工具/API/Robot/发布依旧继续共同开发，不全部推到Linux重写。

## Verified Closeout

21专项11.932s、14旧波形8.775s、39旧三源34.253s通过；根97绑定/105元素覆盖和38416组枚举交点一致。独立21专项11.874s、50000随机有限交点/10000截断与严格变异数值等探针通过，无剩余必须修复scoped问题。负例变异的五个整数值接受1.0问题明确RED后修正，合法PATCH_VALUE浮点仍保留；两处新测试夹具参数/故障字段数量及旧重叠波形有效夹具已按冻结契约校正。

固定版公共入口596通过（67协议27.716s/522网关296.879s/3台账/4汇总），另34选定静态、59/72/85/800、pip/编译、14逐字节源/663引用及台账守护通过；独立报告保存四源码/测试hash。全部运行结果只是共用软件证据，prepared时间表不是实际场景执行、模型作用或RT/发布资格；全目标继续active。

## Requirements Not Closed By A Prepared Timeline

真实场景状态机/模型步时钟、启动/暂停/恢复/停止、标准授权/取号/发送顺序、真实探针断言/WAIT超时及清理、负例变异与case启用检查、REPLAY实际完整资源展开/每轮新SID和复位、其他消费者实际端口碰撞、六工具执行资格及持久E1/E2/E3均必须继续实现。此基础模块提供后续同一执行器使用的可验证数据，不重新定义整个目标为离线计划。
