# Frozen Waveform Semantics W3.14 Implementation Plan

> **For agentic workers:** Use executing-plans/TDD inline. Read-only independent review only; no implementation delegation, commits, branches, worktrees or frozen QA generation.

**Goal:** 按已批准W3及冻结契约第3章，落实五种波形的可写字段、单位/范围、整段极值、10倍采样及完整Stimulus采样，接入原三源审核，不冒充已具备实际模型步调度器。

**Architecture:** 新增waveform.py的WaveformSampler.compile(contract,event,*,model_id)，按97条冻结model_bindings及原消息完整payload解析标量/固定数组明确索引，只接受对应型号已有数值写入目标。保存不可变原值快照；sample(step)以显式MODEL_STEP计算整条脱离副本消息，并再次按完整契约验证。SourceInputAuditor在原始类型校验之后编译全部WAVEFORM事件，保留canonical与原值快照以及compiled waveforms；仍execution_ready=false，后续同一场景调度器消费，不额外建Windows后端。

**Tech Stack:** 现有Python3.12、math/json/dataclasses、Contract、SourceInputAuditor、WireCodec；不增加依赖。

## Global Constraints

- 14冻结源、同一ICD/接收路径、原C与六工具保持；41责任与17未执行Linux不删除、不以采样器勾选完整W3/M4。
- field_path采用原Stimulus.payload根字段及可选零基`[index]`，例如wind_n_mps、motor_command[3]；不接受模型输出、bool/enum、未注册字段、无限/动态数组、缺索引或越界。读取型号绑定与原payload，不用eval或任意JSON指针写内存。
- 根输入/参数消息7..19按既有ModelBindings同一映射分组：7/8/9/14/15/16→flight_control，10→environment，11/12/13→fault，17/18/19→parameters。其他消费者尚无冻结根写入绑定，拒绝TARGET_MISSING，不凭业务字段名推断新模型端口。
- 五种形状CONSTANT/STEP/RAMP/SINE/CHIRP均按冻结参数计算；STEP.change_step为自event.at_step起的相对步，t=elapsed*0.001。sample在事件开始前拒绝；事件duration结束后保持终值，RAMP/CHIRP内部duration结束后同样保持形状终值，外层较短时保持外层截取终值，不修改输入字段。
- SINE/CHIRP用单调相位区间端点及解析峰谷计算整段理论极值，不只检查采样点、不枚举86400000步、不以offset±amplitude保守包络错误拒绝有效短片段；频率取实际区间最高值，sample_rate=1000/sample_period_steps必须至少10倍。每次完整sample重新validate_stimulus，不clamp。
- model step及所有计步字段严格int，拒绝bool/浮点，不借canonical往返补合法性。起点+外层duration须uint32不溢出；原值快照保留PACKED负零，不改变RFC8785线上编码。源审核同时计canonical+原值快照总量16MiB；raw源及compiled引用不构成实际授权。
- sampler不分配header/sequence、不发送、不生成E1/E2/E3；数学采样频率通过不等于消息发送周期/总线负载/1ms RT达标。实际场景顺序、全部事件、同目标碰撞、WAIT/断言/负例/结束九项清理与25API/Robot继续原共用计划。

## Tasks

### 1. Five Shapes And Writable Targets

Files: create input_simulator/waveform.py and tests/icd_gateway/test_waveform.py.

- [x] RED缺少sampler时专项失败；CONSTANT/相对STEP/线性RAMP/SINE/升降CHIRP计算、前起点拒绝/终点保持、严格step/溢出、完整payload/负零与脱离副本。
- [x] RED三个型号已注册数值scalar与数组明确索引、未知/反馈/bool/enum/错误型号/无根映射拒绝；理论峰谷越界即拒绝，短有效波段不误拒绝，10倍采样边界与低采样拒绝。
- [x] GREEN frozen sampler，解析相位区间与原完整Stimulus再次校验，不展开长周期或启动工具。

Interface exercise:

```python
sampler = WaveformSampler.compile(contract, event, model_id='quadrotor_hil')
stimulus = sampler.sample(event['at_step'] + 20)
contract.validate_stimulus(stimulus, model_id='quadrotor_hil')
```

Run: `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_waveform.py -v`.

### 2. Common Source Audit Integration

Files: modify input_simulator/source_inputs.py; same test file.

- [x] RED原审核入口拒绝无效WAVE字段/波形范围/采样率且保留原类型/负零；成功审核提供全部compiled waveforms并保持不可执行、canonical hash和资源审核不变。
- [x] GREEN原源文档先原始类型验证再冻结；SourceInputAudit新增内部input_snapshot_json和waveforms，不改线上或外部源定义；input_document读取原值快照，report追加内部统计。
- [x] 运行旧三源39项与当前sampler专项，确认无默认值补齐或资源/发布资格提升。

### 3. Verification And Handoff

- [x] 独立只读复核并先RED再修问题；固定版公共入口、34选定静态、14源/663引用、单代码守护、41责任/17 Linux通过。
- [x] 新建artifacts/icd_gateway/w3-14-validation.json，追加唯一linux-development-backlog.md及整体进展，不覆盖历史；移交真实型号端口、单位、模型步、波形/周期/负载/探针/结束安全至L-002/L-004/L-010/L-011/L-013/L-014/L-017。全目标保持active。

## Verified Closeout

14波形专项9.056s、39旧源专项34.426s通过；覆盖三个实际型号全部83数值绑定/91标量与数组元素。独立14专项8.932s及短扫频/峰谷/内部持续/严格步/未修改字段负零/精确容量探针通过，无剩余必须修复scoped问题。显式型号缺失与RAMP负零端点先RED后修正。

固定版公共入口575通过（67协议28.333s/501网关285.452s/3台账/4汇总），另34选定静态、59/72/85/800、pip/编译及14逐字节源/663引用通过；源码hash及命令保存独立阶段报告。数学采样不是实际发送/模型步调度/RT/模型生效；完整场景及原六工具/消费者/发布仍未完成，41责任与17未执行Linux保持。

## Authority

冻结input-simulator-data-contract-v0.3.md第3/11章、业务Schema的Event/Waveform及目录97 model_bindings；原ModelBindings.map_message用于确认分组。定义可证明字段含义，不证明实际消费者已存在。
