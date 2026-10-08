# Round 5 Prompt：3.6 Model Consumer Architecture Review

> 推荐模型：**GPT-6 Sol + High**
> 本轮性质：**Architecture Review / Evidence Review / Implementation Planning**
> 本轮禁止直接施工核心 Model Consumer。

项目根目录：

```text
E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006
```

当前 HISTORY / PCAP 工作线已经完成：

```text
Round 0  交接代码审查                        ✅
Round 1  reference.pcap                     ✅
Round 2  prepared.pcap                      ✅
Round 3  tcpreplay 真实 Linux TX / RX       ✅
Round 4  PCAP → 3.6 Gateway Admission       ✅
```

Round 4 最终状态：

```text
ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED
```

Round 4 已真实证明：

```text
SessionOpen
→ SessionOpened(real SID)
→ current-session REENCODE PCAP
→ tcpreplay
→ 3.6 UDPGateway
→ Receiver
→ SessionRegistry
→ Ack(RECEIVED / OK)
→ Ack(FAILED / TARGET_MISSING)
```

但仍未证明：

```text
APPLIED
CONSUMED
真实模型输入生效
模型状态变化
E2 / E3 evidence
```

Round 5 的目标不是继续研究 PCAP，而是回答：

> **3.6 Gateway 已经合法接收到 ID7 FlightQuad 后，谁负责把 motor_command 真正写入模型？什么时候可以诚实地产生 APPLIED？什么时候才可以产生 CONSUMED？现有代码离这条链还缺哪些组件？**

---

# 1. 本轮目标

请对现有代码执行一次**证据驱动的 Model Consumer 架构审查**。

最终需要冻结：

```text
Receiver
→ Model Consumer
→ ModelBindings
→ ModelQueue
→ C/Python Bridge
→ C Core
→ ModelU_t
→ 1 ms model_step
→ APPLIED
→ CONSUMED
→ E2 / E3 Evidence
```

的推荐架构。

本轮只：

- 阅读；
- 分析；
- 必要的只读验证；
- 架构设计；
- 风险评审；
- 给出实施计划。

本轮不要直接实现正式 Consumer。

---

# 2. Evidence Over Assumption

所有结论必须标记为：

```text
已确认
合理推测
待确认
```

不得把以下内容混为一谈：

```text
代码存在
≠ 已接线

结构映射存在
≠ 模型写入成功

C Core 有接口
≠ 新 ICD 已经使用该接口

UDP receipt accepted
≠ APPLIED

写入 pending snapshot
≠ model_step 已消费

model_step 已执行
≠ E3 business result 正确
```

主动寻找能够推翻初始理解的证据。

---

# 3. 已确认的当前边界

施工前请重新核对这些事实，源码冲突时以源码为准。

## 3.1 Receiver

当前：

```text
icd_gateway/receiver.py
```

只完成：

```text
Wire decode
→ Session admission
→ protocol feedback
```

普通模型消息当前返回：

```text
RECEIVED / OK
FAILED / TARGET_MISSING
```

当前没有把普通 ID7 直接送入 ModelQueue。

Round 5 不得把 Round 4 的 RECEIVED 重新解释为 APPLIED。

## 3.2 ModelBindings

当前：

```text
icd_gateway/model_bindings.py
```

职责是：

> **冻结 ICD model_bindings 与 runtime hil_contract 的结构等价检查 + BusinessMessage → target field 映射。**

已知特征：

- runtime contract version 2 / 3；
- model step 固定 0.001 s；
- root inputs：
  - flight_control
  - environment
  - fault
- parameter 为独立 live parameter bindings；
- ID 7..19 属于当前 root input / parameter package；
- ID7 FlightQuad 映射到：

```text
flight_control.motor_command
```

它当前只产生：

```text
MappedValue(
  path,
  target_field,
  value_json
)
```

它不是实际模型写入器。

必须确认：

> target_field 最终应该在哪里解析成真实生成模型字段。

## 3.3 ModelQueue

当前：

```text
icd_gateway/model_queue.py
```

已经提供较完整的目标步队列基础。

至少包括：

```text
enqueue
begin_step
expire
discard_session
clear
close
```

并已有约束：

### enqueue

要求：

```text
state == RUNNING
message 已被 SessionRegistry admission
model binding 存在
role 合法
target_step > current_step
target_step - current_step <= 1000
```

CONTROLLER 消息还必须显式提供：

```text
control_source:
  DEMO_MISSION
  PX4_SITL
  PHYSICAL_UUT

input_lane:
  FLIGHT_CONTROL
  ACTUATOR
```

ID7 对应：

```text
FLIGHT_CONTROL
```

并有：

```text
100 ms control timeout
writer ownership
same-step path reservation
queue capacity = 4096
```

### begin_step

要求：

```text
step == previous_step + 1
```

也就是说它已经表达：

> **1 ms 模型边界上的 ready / rejected semantics**

但是它目前仍然只是 Queue：

```text
PendingInput
StepBatch
```

并不真正写 C Core / ModelU。

## 3.4 Python core_client

当前：

```text
python_services/core_client.py
```

提供：

```text
core_send()
core_request()
```

目标为：

```text
127.0.0.1:<local command port>
```

其中：

```text
core_send
```

是 best-effort UDP；

```text
core_request
```

等待匹配：

```text
request_id
```

的 C Core receipt。

目前没有证据证明：

> 它就是新 ICD ModelQueue → C Core 的正式 Consumer Bridge。

必须重新审查，而不是直接复用。

## 3.5 C Core Model ABI

当前：

```text
c_core/src/model_rt_wrapper.h
c_core/src/model_rt_wrapper.c
```

明确要求：

```text
MODEL_RT_BRIDGE_HEADER
```

以及生成、验证过的：

```text
ModelU_t
ModelY_t
```

没有 production fallback ABI。

提供：

```text
model_initialize()
model_step()
model_terminate()
model_get_input()
model_get_output()
model_is_loaded()
```

这意味着最终真实模型输入很可能应该落到：

```text
ModelU_t*
```

但具体写入责任仍需审查。

## 3.6 C Core main_rt

当前：

```text
c_core/src/main_rt.c
```

已经是：

```text
1 ms HIL runtime
```

并存在：

```text
pending_live
pending_reset
active_input
initial_input
active_parameters
```

以及：

```text
command_lock
generation
latency tracking
```

还存在 JSON command parsing，例如：

```text
set_inputs
```

能够依据生成的：

```text
model_contract.h
hil_contract_find_input(...)
```

检查：

```text
type
dimension
range
```

并写入 candidate / pending input。

必须进一步确认：

1. set_inputs 的完整 command schema；
2. receipt 何时发送；
3. receipt 中 effective_sequence 的真实含义；
4. pending_live 什么时候复制到 active_input；
5. active_input 什么时候写入 ModelU；
6. model_step 前后顺序；
7. generation 是 command generation 还是 model step；
8. 现有 receipt 是否足以作为 E2；
9. 哪个信号可以作为 E3。

## 3.7 Control Arbiter

当前：

```text
c_core/src/control_arbiter.*
```

支持：

```text
demo_mission
px4_sitl
physical_uut
```

并有：

```text
active_source
last_command_ns
timeout_ns
safe value
```

当前 CONTROLLER 的真正所有权语义必须与：

```text
ModelQueue.control_source
input_lane
```

对齐。

不能让 Python Queue 和 C Core ControlArbiter 各自拥有一套不一致的 owner 状态。

---

# 4. Research Scope

优先检查以下文件。

## 4.1 Gateway / Session / Queue

```text
icd_gateway/receiver.py
icd_gateway/session.py
icd_gateway/model_bindings.py
icd_gateway/model_queue.py
icd_gateway/semantic_guards.py
icd_gateway/config.py
icd_gateway/udp.py
icd_gateway/__main__.py
```

相关测试：

```text
tests/icd_gateway/test_receiver.py
tests/icd_gateway/test_session*.py
tests/icd_gateway/test_model_bindings.py
tests/icd_gateway/test_model_queue.py
tests/icd_gateway/test_semantic_guards.py
```

## 4.2 Python → C Core

```text
python_services/core_client.py
python_services/
```

检查所有调用：

```text
core_send(
core_request(
```

并找出已有 command schema 来源。

## 4.3 C Core

重点阅读：

```text
c_core/src/main_rt.c
c_core/src/model_rt_wrapper.c
c_core/src/model_rt_wrapper.h
c_core/src/control_arbiter.c
c_core/src/control_arbiter.h
c_core/src/local_udp.c
c_core/src/local_udp.h
c_core/src/flight_state.h
c_core/src/realtime.c
c_core/src/realtime.h
```

以及交接包中存在的：

```text
model_contract
hil_contract
build script
generated ABI
```

资料。

## 4.4 Frozen v0.3 Contract

检查：

```text
docs/interfaces/baseline/
docs/interfaces/输入模拟器完整接口定义_v0.3_单文件汇总.md
```

重点核对：

- ID7；
- ACK；
- Evidence；
- State；
- control owner；
- target_step；
- model step；
- APPLIED；
- CONSUMED；
- E0/E1/E2/E3；
- timeout；
- lifecycle；
- reset / stop；
- model binding；
- capabilities。

## 4.5 Round 4 Evidence

必须阅读：

```text
docs/HISTORY_PCAP_Round4_Online_Session_Gateway_Design_20261007.md
docs/HISTORY_PCAP_Round4_Online_Session_Gateway_Implementation_Report_20261007.md

artifacts/history/round4/round4_summary.json
artifacts/history/round4/retry_4/
```

Round 5 必须从 Round 4 的真实边界继续，不能重新解释历史证据。

---

# 5. 首要问题：当前真正断在哪里？

必须给出精确的 current architecture trace。

例如最终可能类似：

```text
UDP packet
  ↓
Receiver
  ↓
SessionRegistry.accept
  ↓
【断点 A】
ModelQueue.enqueue
  ↓
ModelQueue.begin_step
  ↓
【断点 B】
Model Consumer
  ↓
【断点 C】
C Core command / direct bridge
  ↓
pending_live
  ↓
active_input
  ↓
ModelU_t
  ↓
model_step()
```

但不要直接接受这个示意。

必须根据源码确认：

- 哪些箭头已有实现；
- 哪些只是类存在；
- 哪些根本没有调用；
- 哪些属于另一套旧 HIL 链；
- 哪些可能存在重复职责。

输出一张：

> **Current Truth Architecture**

---

# 6. 必须回答的架构问题

## Q1. Receiver 应该负责到哪里？

比较：

### A

```text
Receiver
→ ModelQueue.enqueue
```

### B

```text
Receiver
→ ModelConsumerService
→ ModelQueue
```

### C

其他更符合当前架构的方案。

分析：

- coupling；
- error propagation；
- lifecycle；
- testing；
- session cleanup；
- future CANFD support。

## Q2. ModelQueue 谁拥有？

必须明确：

```text
owner
lifetime
thread/process
startup
shutdown
reset
session expiry
```

特别是：

```text
SessionRegistry._attach_model_queue(...)
```

代表什么设计意图？

确认这是正式设计还是阶段性 scaffold。

## Q3. 谁驱动 begin_step？

ModelQueue：

```text
begin_step(model_id, step)
```

要求严格 1 ms sequential step。

必须确认未来的 authoritative model step 到底来自：

### 方案 A

Python / Gateway 自己维护。

### 方案 B

C Core 1 ms loop 通知 Python。

### 方案 C

共享时钟 / IPC。

### 方案 D

其他已有实现。

必须特别分析：

> Python 自己猜 C Core step 是否会产生双时钟问题。

## Q4. 谁负责写 ModelU_t？

比较：

### 方案 A：Python → local UDP JSON → C Core

```text
ModelQueue
→ Python consumer
→ core_request(set_inputs)
→ local UDP 9997
→ C main_rt
→ pending_live
→ ModelU_t
```

### 方案 B：Gateway / Consumer 与 C Core 进程内桥接

### 方案 C：共享内存 / binary IPC

### 方案 D：其他已有成熟机制

本轮不要因为性能直觉直接引入新 IPC。

优先判断：

> 现有 local UDP command path 是否已经足够成为 Demo / 比赛项目阶段的正式桥。

## Q5. MappedValue.target_field 与 C Core 的关系是什么？

当前 Python：

```text
target_field
```

而 C Core 有：

```text
hil_contract_find_input("flight_control.motor_command")
```

必须确认：

- Python 应发送 path？
- target_field？
- group JSON？
- generated field name？
- C Core 是否已经有唯一 Source of Truth？

避免：

> Python 和 C 两边都做一套 string → field mapping。

---

# 7. APPLIED 的严格定义

Round 5 最重要的问题之一：

> **APPLIED 到底什么时候可以发？**

必须至少比较：

### Candidate A

ModelQueue enqueue 成功。

很可能过早。

### Candidate B

C Core receipt accepted=true。

需要判断 receipt 代表：

- 命令解析成功；
- pending snapshot 写入；
- active input 生效；
- 还是 model step 已消费。

### Candidate C

目标 target_step 边界：

```text
pending
→ active_input
→ ModelU
```

完成。

### Candidate D

model_step() 已使用该输入执行一次。

必须根据代码和冻结 Evidence 定义决定。

禁止人为选择“最好实现”的定义。

---

# 8. CONSUMED 的严格定义

同样必须回答：

> **APPLIED 和 CONSUMED 是否应该是两个不同边界？**

候选：

```text
APPLIED:
input committed at target boundary

CONSUMED:
model_step actually executed using that committed input
```

如果当前代码无法证明二者不同，则明确：

```text
当前无法产生真实 CONSUMED
```

而不是让它们同时返回。

---

# 9. E0 / E1 / E2 / E3 映射

请把当前整个链映射成正式 Evidence Stage。

至少回答：

```text
E0 = ?
E1 = ?
E2 = ?
E3 = ?
```

特别结合已经完成的 Round 4：

```text
RECEIVED / OK
```

当前能证明到哪里？

建议输出：

| Stage | 真实事件 | 当前是否已有证据 | 所需数据源 |
|---|---|---:|---|
| E0 | ... | ... | ... |
| E1 | Gateway admission | ✅ | Receiver |
| E2 | ... | ❌/部分 | ... |
| E3 | ... | ❌ | ... |

不得为了填表强行定义。

---

# 10. target_step 的权威来源

Round 4 已明确：

```text
target_step_semantically_qualified = false
```

Round 5 必须解决：

```text
target_step
```

到底如何与 C Core 真实：

```text
1 ms model sequence
```

对齐。

必须研究：

- C Core sequence；
- sim_time；
- model loop；
- status output；
- effective_sequence；
- ModelQueue _steps；
- ClockSync；
- receiver_step；
- target_step。

最后必须回答：

> **哪一个值是 authoritative model boundary？**

如果无法确认，标记：

```text
待确认
```

不要实现。

---

# 11. Control Owner 一致性

当前至少存在两套 ownership 语义：

Python：

```text
ModelQueue
control_source
input_lane
writer ownership
```

C：

```text
ControlArbiter
active_source
last_command_ns
safe value
```

必须分析：

- 谁是最终 authority；
- 两边是否需要相同状态；
- 是否可能状态漂移；
- source change 如何传播；
- 100ms timeout 在哪边执行；
- timeout 后谁发 SAFETY / FAILED；
- Python Queue 和 C Core 是否会重复做 safety。

输出：

> **Control Ownership Source of Truth**

---

# 12. Lifecycle / Reset / Stop

必须研究：

```text
START
PAUSE
RESUME
STOP
RESET
```

对：

```text
ModelQueue
pending input
writer ownership
C pending_live
active_input
ControlArbiter
session
```

的影响。

尤其回答：

### RESET

是否：

```text
queue clear
→ C pending reset
→ initial_input restored
```

### STOP

是否：

```text
queue clear
→ safe input
```

### session expiry

是否：

```text
discard_session
→ C owner revoked
→ safe value
```

不能只清 Python Queue 而让 C Core 保留旧控制量。

---

# 13. Capability 发布规则

当前：

```text
implemented_message_ids = [1]
```

Round 5 必须设计：

> **什么时候 ID7 才可以诚实加入 capabilities？**

禁止静态写死：

```text
[1, 7]
```

应考虑：

```text
runtime contract loaded
ModelBindings validated
ModelQueue available
C Core bridge available
model loaded
consumer ready
control lane ready
```

最终给出：

> Capability Readiness Rule

例如：

```text
ID7 published
iff
all required runtime dependencies are ready
```

但具体条件必须根据代码决定。

---

# 14. Consumer Failure Model

设计至少这些错误如何映射：

```text
TARGET_MISSING
MODEL
CONTROL_OWNER
LATE
EXPIRED
STALE_SESSION
STATE
TIMEOUT
SAFETY
BUSINESS_FAILED
```

并回答：

- 失败发生在 RECEIVED 前还是后？
- 是否能安全重试？
- 是否需要 terminal Ack？
- queue entry 是否保留？
- C pending state 是否需要 rollback？

---

# 15. 架构方案比较

至少给出 2~3 个可实现方案。

每个方案分析：

```text
correctness
complexity
latency
testability
maintainability
failure isolation
C/Python coupling
future CANFD support
demo suitability
production evolution
```

特别结合项目复杂度：

> 当前项目不是默认按大型生产平台设计，应优先选择“足够正确、证据清晰、实现成本可控”的方案。

不要为了“架构漂亮”引入：

- gRPC；
- Kafka；
- Redis；
- shared-memory framework；
- 新 RPC framework；
- 新消息总线；

除非有明确不可替代证据。

---

# 16. 推荐方案必须画出完整时序

最终推荐架构至少给出：

```text
3.3 / Input Simulator
        ↓
UDPGateway
        ↓
Receiver
        ↓
SessionRegistry
        ↓
Model Consumer
        ↓
ModelBindings
        ↓
ModelQueue
        ↓
C Bridge
        ↓
C Core
        ↓
pending_live
        ↓
target model boundary
        ↓
active_input / ModelU_t
        ↓
model_step()
        ↓
ModelY_t / state
        ↓
Evidence
        ↓
Ack(APPLIED / CONSUMED)
```

但最终顺序必须以源码审查结果为准。

必须分别画：

### Data Path

### Control Path

### Evidence Path

### Failure Path

---

# 17. Round 5 MVP Scope

本轮最终要给下一轮实施定义一个**最小 MVP**。

优先只考虑：

```text
model = quadrotor_hil
message_id = 7
FlightQuad
flight_control.motor_command
```

不要一上来支持：

```text
7..19 全部消息
三个模型
parameters
environment
fault
actuator
```

Round 5 implementation MVP 应尽可能回答：

> “能否让 Round 4 的同一 ID7 motor_command 真正进入 quadrotor model，并产生可证明的 APPLIED？”

CONSUMED 是否同轮实现，由架构审查决定。

---

# 18. 必须明确哪些东西暂时不要做

架构审查结束时给出 Deferred List，例如：

```text
多模型
ID8/9
environment
fault
parameters
CANFD
真实3.3
真实硬件
麒麟 qualification
性能优化
多 session
复杂 control source switching
```

不要让 Round 5 MVP 扩张成完整 3.6 产品。

---

# 19. Security / Safety Review

必须检查：

- local UDP 只绑定 127.0.0.1 是否仍成立；
- Gateway 是否可能直接暴露 C Core command port；
- 未授权 Session 是否可能进入 Queue；
- C Core 是否会保留 stale control；
- session expiry 是否能触发 safe state；
- malformed input 是否可能绕过 ModelBindings；
- receipt 是否可被伪造；
- request_id correlation 是否足够；
- process crash 后 safe behavior。

不得为了 Demo 绕过已有认证、role、control owner 或 range 校验。

---

# 20. Tests / Verification Strategy

本轮不实现，但必须设计未来测试层次。

至少包括：

### Unit

```text
ModelBindings
ModelQueue
Consumer state
Ack state machine
```

### Integration

```text
Receiver
→ Queue
→ fake deterministic C bridge
```

### C Core integration

```text
Python bridge
→ C command
→ receipt
```

### Real model integration

```text
ID7
→ ModelU
→ model_step
→ observable state
```

### End-to-end

```text
PCAP
→ Gateway
→ Model
→ APPLIED / CONSUMED
```

明确哪些测试可以用 fake，哪些证据不能用 fake。

---

# 21. 重点审查“旧链是否可复用”

不要默认：

```text
python_services/core_client.py
+
C local_udp set_inputs
```

就是最终答案。

也不要默认它必须废弃。

需要客观回答：

### 若复用

最小 adapter 是什么？

例如：

```text
PendingInput.values
→ C set_inputs JSON
```

如何保持：

- target_step；
- request correlation；
- control source；
- target field；
- receipt；
- error mapping？

### 若不复用

明确现有接口在哪个要求上无法满足：

```text
step determinism
APPLIED evidence
CONSUMED evidence
latency
atomicity
rollback
control ownership
```

必须有证据。

---

# 22. Review Existing C Receipt Semantics

详细追踪：

```text
request received
→ parse_set_inputs
→ pending_live
→ generation
→ active_input
→ ModelU
→ model_step
→ status send
```

以及：

```text
send_receipt(...)
effective_sequence
accepted
reason
fields
```

输出一张：

> **C Core Command State Transition Table**

至少包含：

| Event | Pending 已写 | Active 已写 | Model 已 step | receipt | 可否作为 APPLIED |
|---|---:|---:|---:|---|---:|

如果代码无法证明某一步，明确写“待确认”。

---

# 23. 不允许的行为

本轮禁止：

- 修改核心代码；
- 修改 frozen v0.3；
- 修改 implemented_message_ids；
- 接入假的 model consumer；
- 让 Receiver 直接返回 APPLIED；
- 把 C receipt accepted 当成 APPLIED，除非代码证据支持；
- 手工创造 E2/E3；
- 引入新 IPC framework；
- 重写 C Core；
- 扩展支持所有 message IDs；
- 修改 Round 1~4 冻结 artifacts；
- 顺手修已有 1 failure + 3 errors。

本轮原则上只新增：

```text
Architecture Review report
```

如果为了验证必须生成临时分析文件，最终报告说明，且不要修改生产代码。

---

# 24. 输出报告

生成：

```text
docs/HISTORY_PCAP_Round5_Model_Consumer_Architecture_Review_20261007.md
```

报告必须包含：

## 1. Executive Summary

用 5~10 条结论回答：

- 当前断点；
- 当前可复用资产；
- 当前不能声称的能力；
- 推荐架构；
- Round 5 MVP。

## 2. Current Truth Architecture

按实际调用关系画图。

标：

```text
CONNECTED
SCAFFOLD
REFERENCE_ONLY
MISSING
```

## 3. ModelBindings Review

## 4. ModelQueue Review

## 5. Receiver Integration Gap

## 6. C Core Input Path Review

## 7. Python/C Bridge Review

## 8. Model Step / target_step Analysis

## 9. Control Ownership Analysis

## 10. APPLIED / CONSUMED Semantics

## 11. E0 / E1 / E2 / E3 Mapping

## 12. Lifecycle / Reset / Session Expiry

## 13. Capability Publication Rule

## 14. Architecture Options

至少 2~3 个方案。

## 15. Recommended Architecture

说明为什么选它。

## 16. Recommended Data / Control / Evidence Flow

## 17. Round 5 MVP Scope

只聚焦：

```text
quadrotor_hil
ID7
motor_command
```

## 18. Required Code Changes

只列建议，不实施。

按文件列：

```text
file
change
reason
risk
```

## 19. Test Plan

## 20. Risks / Open Questions

每项标：

```text
已确认
合理推测
待确认
```

## 21. Round 5 Implementation Plan

拆成小轮次，例如：

```text
5A
5B
5C
...
```

每一轮都有独立 Definition of Done。

---

# 25. 最重要的审查问题

最终报告必须明确回答以下 10 个问题：

1. **ID7 从 Receiver 到 ModelQueue 当前缺哪一条实际调用？**
2. **谁拥有 ModelQueue？**
3. **谁提供 authoritative 1 ms model step？**
4. **target_step 怎样与 C Core step 对齐？**
5. **ModelQueue ready input 怎样真正进入 ModelU_t？**
6. **现有 local UDP set_inputs 是否足以作为第一版正式 Consumer Bridge？**
7. **APPLIED 在哪一个精确事件发生后才能发送？**
8. **CONSUMED 在哪一个精确事件发生后才能发送？**
9. **什么时候 implemented_message_ids 才可以诚实包含 7？**
10. **Round 5 MVP 最少需要改哪些文件，才能把 Round 4 的 ID7 真正应用到模型？**

---

# 26. Definition of Done

只有满足以下条件，本轮 Architecture Review 才算完成：

- [ ] 已读取真实 Gateway / Queue / C Core 代码；
- [ ] 已追踪当前实际调用关系；
- [ ] 已区分 scaffold 与 connected implementation；
- [ ] 已找出 Receiver → ModelQueue 断点；
- [ ] 已找出 ModelQueue → C Core 断点；
- [ ] 已审查 C Core set_inputs / pending / active / ModelU / model_step；
- [ ] 已定义 authoritative model step；
- [ ] 已定义 APPLIED；
- [ ] 已定义 CONSUMED，或明确当前无法定义；
- [ ] 已定义 E0/E1/E2/E3；
- [ ] 已解决 control ownership Source of Truth；
- [ ] 已定义 capability publication rule；
- [ ] 已比较至少 2 个架构方案；
- [ ] 已给出单一推荐方案；
- [ ] 已把 MVP 限定到 quadrotor ID7；
- [ ] 已给出文件级实施计划；
- [ ] 已给出测试计划；
- [ ] 已列出所有待确认项；
- [ ] 未修改生产核心代码；
- [ ] 已生成 Architecture Review 报告。

---

# 最终原则

Round 4 已证明：

> **HISTORY PCAP 可以通过真实在线 Session 合法进入 3.6 Gateway。**

Round 5 Architecture Review 要回答：

> **从 Gateway admission 开始，到模型真正消费输入为止，最小而诚实的 Model Consumer 应该长什么样。**

不要为了得到 APPLIED 而降低证据标准。

不要为了得到 CONSUMED 而发明不存在的模型反馈。

优先复用现有：

```text
ModelBindings
ModelQueue
C Core contract
existing local bridge
```

但只在源码证据支持时复用。
