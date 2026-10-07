# Generated Data Dispatch W3.20 Implementation Plan

**Status (2026-10-05): DEFERRED_USER_ORDER_ORIGINAL_W3_FIRST.** 用户要求先完成原有第三阶段，再开发新增自生数据入口。本文件是未完成草案，不是原W3完成记录，不占用下一正式工作包编号。未验证代码和测试保存在`docs/superpowers/drafts/2026-10-05-generated-data/`，不在运行包/默认测试发现路径中。最后一次19项测试17通过、2失败（租期失效未转FAILED；部分提交失败未本地取消），尚未修复，后续必须重新先验证测试。

> **For agentic workers:** Use executing-plans and TDD inline with independent read-only review. No commits, branches, worktrees or frozen baseline edits.

**Goal:** 将模拟器本身的完整常量/波形数据生成接到原标准会话与实际UDP发送，W4/W5保留延期，不依赖硬件采集输入。

**Architecture:** 新增generator.py的不可变GenerationProgram与有界GeneratedDataRun。程序从严格内部配置编译完整Stimulus及有限流，复用WaveformSampler纯采样器；运行只接受原live UDPDispatcher和显式generation_step/target_step，预检全部角色/实际授予/完整模板，保存原Header关联，实际poll观察终态失败，stop只本地取消并保留记录。不把源采样步/软件时钟当真实模型步或原六工具资格。

**Tech Stack:** 原Python3.12/dataclasses/JSON/heapq/原Contract/WaveformSampler/SourceSession/UDPDispatcher，无新依赖或平台分支。

## Global Constraints

- 整体当前终点是可配置自动运行的自生数据模拟器；本包是实际生成/发送联动，不把它替代完整结束条件。自动入口/运行配置、证据收尾仍须后续接通。W4/W5暂停开发但不删除原41任务/17 Linux门禁。
- 线上ICD、硬件接口和原六分支冻结不改；当前直接软件UDP入口不宣称调用ETHGEN、SocketCAN、tcpreplay或实际硬件。
- 常量完整Stimulus覆盖所有非SessionOpen/Heartbeat TO_36消息；SessionOpen与Heartbeat由原会话/心跳器管理，不能将模板当动态授予或自动续租。所有model/type/range/完整字段与PACKED_LE负零保留。
- 内部配置闭字段format=HIL_GENERATION_PROGRAM_1,model_id,streams；每流闭字段stream_id,start_step,period_steps,count,stimulus,waveform。waveform为null常量，或冻结WAVEFORM Event且at_step/start、sample_period/period、duration=period*(count-1)、stimulus一致。生成步显式uint32独立于实际模型步，target_step显式单独uint32，无墙钟替代。
- 默认100000动作/16MiB原快照，最大1000000动作/64MiB，最多64流；启动时预检实际capabilities/model/角色、消息固定周期、流碰撞和原dispatcher空闲，不先分配/发部分不合格组。
- 每次advance(generation_step,*,target_step)只发送恰到当前步的完整值；跨过未发动作TIMEOUT，不追赶、不静默丢样；重复步可仅poll原在途不重复取号，严格不回退。所有due先原完整预检/可用在途容量，再依(start_step,stream_id)取号；提交异常记录实际已分配前缀、转FAILED并本地取消，计数不回滚。
- 本包不关闭remote Session/执行九项安全清理，停止状态明确LOCAL_STOPPED；远端失败/超时为FAILED，保留原RX/错误，不将COMPLETE原报升格模型资格。运行完成只表示全部生成输入获标准终态反馈，qualification始终NOT_EVALUATED。

## Task 1: Compile Complete Generation Streams

Files: create input_simulator/generator.py; create tests/icd_gateway/test_generator.py. Reads original waveform.py/contract.py only.

- [ ] 先写缺模块RED测试：完整常量、五波形、三型号、未知/缺字段、bool/float计数、全部合法TO_36模板、源快照负零及容量/周期/相同完整写集合碰撞。
- [ ] 实现GenerationProgram.compile(contract,config,*,max_actions=100000,max_bytes=16777216)，不可变快照与惰性有限流，不展开百万动作。sample(stream_id,index)产生脱离完整值，不分配Header或触网。

```python
program = GenerationProgram.compile(contract, config)
stimulus = program.sample('environment', 0)
contract.validate_stimulus(stimulus, model_id=program.model_id)
```

Run: python -X utf8 -m unittest discover -s tests/icd_gateway -p test_generator.py -v. Expected initial missing-module failure, final pass.

## Task 2: Actual Standard Dispatch And Local Stop

- [ ] 先RED真实UDP peer接收生成值/全局取号/反馈、重复步、失步、旧SID/缺能力/角色、负反馈/超时、固定容量、停止取消与原记录不丢测试。
- [ ] 实现GeneratedDataRun(dispatcher,program).advance(generation_step,*,target_step)、poll()、stop()；跟踪原opaque Header与终态，preflight使用原授权/类型规则，保留同一标准通路。不mock真实C消费者、不以prepared当发送成功。

```python
run = GeneratedDataRun(dispatcher, program)
run.advance(0, target_step=100)
run.poll()
run.stop()
assert run.qualification_status == 'NOT_EVALUATED'
```

## Task 3: Review, Verification And Append-Only Handoff

- [ ] 独立只读复核，重要问题先RED/GREEN；原dispatcher/source-session/waveform回归和固定源码scripts/test_icd_runtime.py、34选定静态及14源/663引用/codec/依赖/编译守护。
- [ ] 保存artifacts/icd_gateway/w3-20-validation.json，并在唯一linux-development-backlog.md追加当前范围优先级/W4W5延期、生成目标步/真实授予/负载与实际停止验证，不删除历史或原责任。
- [ ] 整体计划记录当前进度与尚未接通自动入口，不勾选完整W3/当前生成器任务结束。

## Next Required Deliverables

可配置自动运行入口、实际SessionOpen及有限运行/清晰目标步策略、数据示例/使用文档、连续证据段/最终未保存记录收尾、原反馈结果与失败退出仍须交付，方可结束当前自生数据模拟器任务。原三源/完整场景handler/原六工具与正式消费者能力按保留责任，W4/W5是延期不是取消。
