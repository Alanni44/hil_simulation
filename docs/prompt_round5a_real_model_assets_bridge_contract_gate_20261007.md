# Round 5A Prompt：真实模型资产与内部 Bridge Contract Gate

> 推荐模型：**GPT-6 Sol + High**
> 本轮性质：**Asset Gate / Contract Freeze / Architecture Validation**
> 本轮禁止直接实现正式 Model Consumer、禁止修改 C Core 运行逻辑。

项目根目录：

~~~text
E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006
~~~

前置已完成：

~~~text
Round 1  reference.pcap                         ✅
Round 2  prepared.pcap                          ✅
Round 3  tcpreplay 真实 Linux TX / RX           ✅
Round 4  PCAP → 3.6 Gateway Admission           ✅
Round 5  Model Consumer Architecture Review      ✅
~~~

Round 5 架构审查报告：

~~~text
docs/HISTORY_PCAP_Round5_Model_Consumer_Architecture_Review_20261007.md
~~~

本轮是 Round 5 实施计划中的 **5A**：

> **真实模型资产与内部 Bridge Contract Gate**

---

# 1. 本轮目标

5A 不直接施工 Model Consumer。

本轮只解决两个问题。

## A. Real Model Asset Gate

确认真正用于 quadrotor_hil 的模型资产是否存在、是否完整、是否与冻结 HIL-ICD-1.0 / ModelBindings / C Core wrapper 一致。

至少确认：

~~~text
真实 hil_contract.json
真实 model_contract.h
真实 model_rt_bridge.h
真实 build_script.m 或等价生成流程
真实 generated model ABI
真实 model executable / build target
真实 package / artifact identity
真实 model hash / contract hash
~~~

并回答：

> 当前是否已经具备“真实模型接入”的最低资产条件？

最终必须给出：

~~~text
GO
或
CONDITIONAL_GO
或
NO_GO
~~~

不能用测试 fixture、合成 metadata、默认兼容结构冒充真实模型资产。

## B. Internal Bridge Contract Freeze

在不实施代码的前提下，冻结：

~~~text
Gateway / ModelConsumer
→ loopback UDP bridge
→ C Core
~~~

之间的内部协议语义。

重点冻结：

~~~text
bridge_version
core_instance_id
run_epoch
model_id
model_package_hash
session_id
request_sequence
transaction_id
message_id
request_hash
target_step
received_ns
deadline_ns
control_source
input_lane
owner_revision
payload / path mapping
STAGED
APPLIED
REJECTED
UNKNOWN
query / retry / idempotency
final ModelU readback probe
~~~

这不是新的外部 ICD。

它只是 3.6 内部：

> **Model Consumer ↔ C Core 的受控执行桥。**

不得修改 frozen HIL-ICD-1.0。

---

# 2. Evidence Rules

所有结论必须标：

~~~text
已确认
合理推测
待确认
~~~

严禁：

~~~text
文件存在 ≠ 真实可构建
header 存在 ≠ ABI 匹配
fixture 通过 ≠ real model qualified
C set_inputs 可用 ≠ target-step bridge 已实现
receipt accepted ≠ APPLIED
sequence+1 ≠ 目标步完成
~~~

任何真实资产缺失都必须如实列为 NO-GO dependency。

---

# 3. Research First

必须先阅读：

~~~text
docs/HISTORY_PCAP_Round5_Model_Consumer_Architecture_Review_20261007.md
docs/HISTORY_PCAP_Round4_Online_Session_Gateway_Implementation_Report_20261007.md
README_代码整理.md
文件清单与SHA256.json
~~~

然后检查：

~~~text
icd_gateway/model_bindings.py
icd_gateway/model_queue.py
icd_gateway/receiver.py
icd_gateway/session.py

python_services/core_client.py

c_core/src/main_rt.c
c_core/src/model_rt_wrapper.c
c_core/src/model_rt_wrapper.h
c_core/src/control_arbiter.c
c_core/src/control_arbiter.h
c_core/src/local_udp.c
c_core/src/local_udp.h
~~~

重点搜索：

~~~text
hil_contract.json
model_contract.h
model_rt_bridge.h
build_script.m
MODEL_RT_BRIDGE_HEADER
MODEL_U_VAR
MODEL_Y_VAR
MODEL_INIT_FN
MODEL_STEP_FN
MODEL_TERM_FN
hil_contract_find_input
hil_contract_set_input
hil_contract_set_actuators
model_get_input
model_get_output
quadrotor_hil
multirotor
~~~

---

# 4. Asset Search Scope

优先搜索：

~~~text
当前 handoff root
当前 handoff root 的父目录
E:\GuoZhao\Desktop\UAVDemo\3_6
E:\GuoZhao\Desktop\UAVDemo
~~~

不要默认扫描整个磁盘。

如必须扩大搜索范围：

- 先记录理由；
- 只搜索强相关文件名；
- 不读取无关私人目录；
- 不修改找到的任何真实模型文件。

如果找到多个版本：

> 不允许自动选“最新修改时间”的那个。

必须比较：

- model_name；
- contract_version；
- build metadata；
- hash；
- step_s；
- input ports；
- generator identity；
- 与 HIL-ICD-1.0 的一致性。

---

# 5. Real Asset Gate：必须核对的资产

## 5.1 hil_contract.json

若找到真实文件，必须验证至少：

~~~text
model_name == quadrotor_hil
contract_version ∈ {2,3}
execution.step_s == 0.001
inputs roots == flight_control/environment/fault
flight_control.mode == motor_command
motor_command dimension == 4
motor_command range == 0..1
parameters structure compatible
~~~

并通过现有 ModelBindings 做结构等价验证。

不能重新写一套 checker 替代现有 ModelBindings。

## 5.2 model_contract.h

必须确认：

- 是否真实生成文件；
- 是否来自同一 quadrotor package；
- 是否含正式 getter/setter/spec；
- 是否有：

~~~text
HilInputSpec
hil_contract_find_input
hil_contract_set_input
hil_contract_set_actuators
~~~

如果没有输入 getter：

~~~text
待确认 / Blocking for final APPLIED probe
~~~

不要在本轮实现 getter。

## 5.3 model_rt_bridge.h

必须确认它真实定义：

~~~text
ModelU_t
ModelY_t
MODEL_U_VAR
MODEL_Y_VAR
MODEL_INIT_FN
MODEL_STEP_FN
MODEL_TERM_FN
~~~

并且与：

~~~text
model_rt_wrapper.h
model_rt_wrapper.c
~~~

可一致编译。

若只有测试 bridge / fake ABI：

> 标记 TEST_ONLY，不得计入 GO。

## 5.4 build_script.m / 生成流程

必须回答：

- 谁生成 model_contract.h？
- 谁生成 model_rt_bridge.h？
- 谁生成模型 C/C++ 源码？
- 输出目录是什么？
- 是否有 package manifest？
- 是否记录 MATLAB/Simulink/ERT 版本？
- 是否生成可复现 hash？
- C Core 如何 include/link？

如果 build_script 不在包内，但报告引用存在：

~~~text
待提供
~~~

不得猜。

## 5.5 executable / build target

必须确认是否存在：

- 可构建 main_rt；
- 已编译 executable；
- CMake/Make/build script；
- json-c 等依赖；
- generated model objects；
- bridge header include path。

如果只存在 main_rt.c，而没有真实 generated model：

> 不能宣称 real model runnable。

---

# 6. Asset Identity Freeze

如果真实资产存在，必须建议冻结一个最小 identity record。

例如：

~~~json
{
  "model_id": "quadrotor_hil",
  "hil_contract_sha256": "...",
  "model_contract_header_sha256": "...",
  "model_rt_bridge_header_sha256": "...",
  "generated_model_artifact_sha256": "...",
  "build_script_sha256": "...",
  "model_executable_sha256": "...",
  "solver_step_s": 0.001,
  "baseline_sha256": "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
}
~~~

字段可以按真实资产调整。

原则：

> Round 5B 以后所有真实 E2 都必须绑定到同一组模型资产身份。

不能只记录文件名。

---

# 7. GO / NO-GO Gate

## GO

只有满足：

~~~text
真实 quad 模型资产存在
ModelBindings 对真实 hil_contract 通过
生成 ABI 可识别
C wrapper 可对应
build / executable path 可追踪
step_s = 1ms
motor_command 映射可证明
最终输入 readback 路径可设计
~~~

才能：

~~~text
REAL_MODEL_ASSET_GATE = GO
~~~

## CONDITIONAL GO

若模型资产真实存在，但仍缺少：

~~~text
input getter
build reproducibility proof
exact executable
~~~

可：

~~~text
REAL_MODEL_ASSET_GATE = CONDITIONAL_GO
~~~

但必须列出 5B 前强制补齐项。

## NO-GO

如果：

~~~text
只有 fixture
只有结构声明
没有 generated ABI
找不到真实 quad model package
无法确认 build identity
~~~

则：

~~~text
REAL_MODEL_ASSET_GATE = NO_GO
~~~

并停止把后续设计写成“真实模型已就绪”。

---

# 8. Internal Bridge Contract：设计原则

本内部桥只负责：

~~~text
ModelConsumerService
↔
C Core
~~~

不对外公开。

外部仍然只有：

~~~text
HIL-ICD-1.0
~~~

不要修改外部：

- message IDs；
- Ack stage；
- Evidence schema；
- Session；
- Wire；
- CRC。

---

# 9. Bridge Transport

优先复用现有：

~~~text
127.0.0.1 UDP
~~~

原因：

- C 已有 local_udp；
- Python stdlib 可直接使用；
- Demo / 当前工程复杂度足够；
- failure isolation 清晰；
- 不引入新框架。

但不得直接复用旧：

~~~text
set_inputs
→ accepted receipt
~~~

作为正式 bridge contract。

---

# 10. Bridge Version / Instance Identity

必须设计：

~~~text
bridge_version
core_instance_id
run_epoch
~~~

用于解决：

- C Core restart；
- Python Consumer restart；
- stale response；
- previous run result；
- old session；
- model replacement。

必须回答：

> core_instance_id 由谁生成？

> run_epoch 在什么时候改变？

至少比较：

### A

C Core 每次进程启动生成 instance id。

### B

Gateway run 创建 epoch，C 接受。

### C

两者组合。

必须选一个推荐方案。

---

# 11. Authoritative Model Step

Round 5 Review 已推荐：

> C Core 是 authoritative 1ms model boundary。

5A 必须冻结这一点的内部协议定义。

至少明确：

~~~text
C sequence = 已完成 model_step 数量
~~~

若 target_step = S：

候选语义：

~~~text
完成 S-1
→ commit target S inputs
→ final control writer
→ readback ModelU
→ model_step() #S
→ sequence becomes S
~~~

必须对照源码验证这一解释是否成立。

如果需要新 epoch 才能保证：

~~~text
sequence 0 = run step 0
~~~

必须明确 5B 要改什么。

---

# 12. Stage Timing

由于：

~~~text
Python → UDP → C
~~~

不能在收到 boundary S 后才发送再期待赶上 S。

所以 bridge 必须支持：

> **Pre-stage**

建议内部状态：

~~~text
QUEUED
→ STAGED
→ APPLIED
~~~

这些是内部状态，不是外部 Ack stage。

必须定义：

### QUEUED

Python Queue 已接受，尚未送 C。

### STAGED

C 已验证并持有该 target request，但未到 target boundary。

### APPLIED

C 在 target boundary 最终写入 ModelU，并通过真实 readback probe 证明。

---

# 13. Bridge Request Identity

每条内部 request 至少必须绑定：

~~~text
bridge_version
core_instance_id
run_epoch
model_id
model_package_hash

session_id
request_sequence
transaction_id
message_id

canonical_request_sha256

target_step
received_ns
deadline_ns
valid_for_ms

control_source
input_lane
owner_revision

payload
~~~

不一定全部使用 JSON 顶层平铺。

必须设计 exact schema。

但不要把 target_field / memory offset 作为外部任意可写字段暴露给 Python。

---

# 14. Payload / Path Mapping

Python ModelBindings 当前有：

~~~text
path
target_field
value_json
~~~

C Core 现有生成契约通过：

~~~text
hil_contract_find_input(path)
hil_contract_set_input(...)
~~~

5A 必须冻结：

> Python Bridge 应发送 **contract path/group JSON**，而不是 raw target field / memory offset。

例如 ID7：

~~~json
{
  "flight_control": {
    "motor_command": [0.1,0.2,0.3,0.4]
  }
}
~~~

C 再根据生成 contract：

~~~text
flight_control.motor_command
~~~

映射到真实 ModelU。

这样：

> C generated contract 是真实 ABI mapping authority。

---

# 15. Control Owner Contract

必须解决 Python / C 两边控制权一致性。

Bridge request 至少考虑：

~~~text
control_source
input_lane
owner_revision
~~~

但不能让 Python 自报即成为 C 的最终 authority。

需要设计：

~~~text
Python authorization decision
→ C verifies current OwnerRecord
~~~

建议 C 侧 OwnerRecord 至少考虑：

~~~text
session_id
control_source
input_lane
revision
expires_at
~~~

5A 只冻结语义，不实现。

---

# 16. 100ms Control Deadline

冻结 v0.3：

> 控制命令不得超过 100ms 接收端单调时间超时。

Bridge 必须携带：

~~~text
received_ns
deadline_ns
~~~

C 在：

- STAGE；
- APPLY；

两个阶段都要 fail closed。

必须明确边界：

~~~text
age < 100ms
~~~

或：

~~~text
age <= 100ms
~~~

以冻结协议和现有 ModelQueue 代码为准。

Round 5 Review 已指出重点边界：

~~~text
99,999,999 ns
100,000,000 ns
~~~

5A 必须冻结 exact rule。

---

# 17. Idempotency

内部 bridge key 应至少绑定：

~~~text
run_epoch
session_id
request_sequence
~~~

或更强 tuple。

必须定义：

### 同 key + 同 hash

~~~text
idempotent replay/query
~~~

不得二次应用。

### 同 key + 不同 hash

~~~text
reject
~~~

不得 last-write-wins。

---

# 18. STAGED Result

首次 stage 成功只能证明：

~~~text
C accepted immutable request for future step
~~~

不能证明：

~~~text
APPLIED
~~~

Stage response 至少考虑：

~~~json
{
  "bridge_version": 1,
  "core_instance_id": "...",
  "run_epoch": "...",
  "request_key": {},
  "request_sha256": "...",
  "state": "STAGED",
  "target_step": 123,
  "accepted_at_ns": "...",
  "error": "OK"
}
~~~

Exact fields 由本轮冻结。

---

# 19. APPLIED Result

APPLIED 必须建立在真实 C Core 边界事件上。

必须至少证明：

~~~text
same request identity
same request hash
same run epoch
target_step == actual applied step
owner still valid
deadline still valid
final writer did not overwrite ID7
final ModelU readback == expected motor_command
~~~

然后才能内部：

~~~text
state = APPLIED
~~~

再由 Python Consumer 映射为 frozen Ack(APPLIED)。

---

# 20. Final ModelU Readback Probe

这是 5A 必须冻结的核心。

Round 5 Review 已确认：

> 旧 apply_live_update 后 motor_command 可能被 mission / arbiter 覆盖。

所以最终 probe 必须发生在：

~~~text
所有 control writer 完成后
model_step() 前
~~~

推荐时序：

~~~text
apply staged non-control inputs
→ select final control owner
→ final write_actuator_command
→ read ModelU.motor_command
→ compare / hash / probe
→ APPLIED event
→ model_step()
~~~

如果真实 generated contract 没有 getter：

~~~text
Blocking dependency
~~~

不能改用 Python 自己记得“我发送了什么”作为 probe。

---

# 21. APPLIED 与 model_step

5A 必须明确选择：

### 方案 A

APPLIED = final ModelU commit/readback 在 model_step 前。

### 方案 B

APPLIED = model_step 执行返回后。

冻结 v0.3 定义：

~~~text
E2 = 真实模型写入或消费者读取
~~~

因此需要根据：

- target step；
- logical message applied atomically；
- probe catalog；

给出推荐。

不要为了少改代码随意决定。

---

# 22. CONSUMED

本轮继续冻结：

> ID7 MVP 不发送 CONSUMED。

除非源码/冻结契约明确给出一个“控制输入实际消费者读取”的正式 consumer probe。

不要把：

~~~text
model_step()
~~~

自动改名为：

~~~text
CONSUMED
~~~

5A 报告必须保留：

~~~text
ID7_CONSUMED = NOT_IMPLEMENTED / NOT_REQUIRED_FOR_MVP
~~~

---

# 23. Result Query

UDP 可能丢包。

因此 bridge 不能只有：

~~~text
send request
wait one receipt
~~~

必须冻结：

~~~text
get_input_result
~~~

或等价查询语义。

Query 必须：

- 不二次执行；
- 返回原 request 当前状态；
- 校验 instance/epoch/key/hash；
- 可返回：

~~~text
STAGED
APPLIED
REJECTED
UNKNOWN
~~~

---

# 24. UNKNOWN / Timeout

必须解决最危险的情况：

> Python 超时，但 C 实际可能已经 APPLIED。

所以：

~~~text
TIMEOUT
≠ definitely not applied
~~~

本轮必须冻结：

- query deadline；
- tombstone；
- late result；
- unknown handling；
- 是否允许后续追加 Ack；
- 已发送 wire terminal feedback 后如何处理迟到 C evidence。

不能实现后再讨论。

---

# 25. Completion Record Capacity

不能发生：

~~~text
C 已写 ModelU
但 completion buffer 满
导致无 E2 证据
~~~

所以必须设计：

> completion slot must be reserved before request becomes executable.

至少定义：

~~~text
staged_capacity
completion_capacity
retention
cleanup
~~~

以及与 Python Queue 总 4096 的关系。

不要形成两个独立无限队列。

---

# 26. Lifecycle / Epoch

必须冻结内部 bridge 在以下事件中的行为：

~~~text
START
PAUSE
RESUME
STOP
RESET
session expiry
C restart
Gateway restart
~~~

尤其：

### STOP

- 不再 APPLY staged；
- control safe；
- pending/staged clear or terminal reject；
- epoch 是否结束？

### RESET

- 恢复 initial snapshot；
- 旧 stage 无效；
- old epoch invalid；
- sequence / model step 的规则是什么？

### RESUME

冻结 v0.3 要求：

> 清旧队列，以新 session 重新授权。

所以 internal bridge 不得恢复旧 stage。

---

# 27. Core Instance / Epoch Restart Protection

必须防止：

~~~text
C process restart
→ sequence 从新进程状态开始
→ Python 仍认为旧 epoch 有效
~~~

建议 handshake 返回：

~~~text
core_instance_id
run_epoch
model identity
current_step
lifecycle
owner state
~~~

如果任一身份不匹配：

~~~text
old staged requests invalid
~~~

---

# 28. Bridge Command Set

至少比较是否需要这些最小内部命令：

~~~text
bridge_hello
stage_model_input
get_input_result
get_model_status
revoke_control
~~~

可能需要：

~~~text
clear_epoch
~~~

但不要为了完整性膨胀协议。

本轮必须给出**最小推荐命令集**。

---

# 29. Exact Schema Freeze

本轮最终需要输出一个候选冻结版内部 Contract。

推荐：

~~~text
docs/internal/model_consumer_bridge_v1.md
~~~

如果项目不适合新增 internal docs 目录，也可把完整 schema 放进 5A 报告。

至少包括：

- request envelope；
- response envelope；
- enums；
- required fields；
- ranges；
- identity key；
- hash；
- time fields；
- stage state；
- errors；
- query semantics；
- idempotency；
- lifecycle；
- capacity；
- security boundary。

注意：

> 这是 INTERNAL V1，不是 HIL-ICD-1.0 V1.1。

---

# 30. Error Mapping

至少设计内部错误：

~~~text
BAD_BRIDGE_VERSION
CORE_INSTANCE_MISMATCH
EPOCH_MISMATCH
MODEL_MISMATCH
HASH_MISMATCH
DUPLICATE_CONFLICT
OWNER_MISMATCH
LATE
EXPIRED
STATE
CAPACITY
TARGET_MISSING
APPLY_FAILED
PROBE_MISMATCH
UNKNOWN_RESULT
~~~

再设计如何映射到 frozen ICD error：

~~~text
MODEL
CONTROL_OWNER
LATE
EXPIRED
STATE
CAPACITY
TARGET_MISSING
BUSINESS_FAILED
TIMEOUT
SAFETY
~~~

不能新增 wire error enum。

---

# 31. Security Boundary

内部 bridge：

~~~text
127.0.0.1 only
~~~

但 loopback ≠ authentication。

必须说明当前安全模型：

> 受控主机上的本地 trust boundary。

至少冻结：

- peer must be loopback；
- request_id / hash correlation；
- core_instance_id；
- epoch；
- model package identity；
- no arbitrary path/offset；
- no arbitrary command passthrough；
- no external binding；
- no raw shell / file path fields。

如果认为需要随机 bridge session token：

> 标记建议，不默认引入复杂密钥体系。

---

# 32. Real Asset vs Fixture Classification

找到的每个资产都要分类：

~~~text
REAL_DEPLOYMENT_ARTIFACT
REAL_SOURCE_ARTIFACT
GENERATED_ARTIFACT
TEST_FIXTURE
SYNTHETIC_METADATA
REFERENCE_ONLY
MISSING
~~~

输出表：

| Asset | Path | SHA256 | Classification | Can support real E2? |
|---|---|---|---|---:|

---

# 33. 5A 不允许的行为

本轮禁止：

- 修改 C Core；
- 修改 Receiver；
- 修改 ModelQueue；
- 修改 Session；
- 修改 frozen v0.3；
- 修改 Round 1~4 artifacts；
- 添加 implemented_message_ids=7；
- 实现 stage_model_input；
- 实现 getter；
- 编造真实模型文件；
- 从 fixture 生成假的 production asset；
- 运行真实 PCAP → Model；
- 发 APPLIED；
- 发 CONSUMED；
- 顺手修已有回归。

允许：

- 只读源码/资产；
- hash；
- 结构检查；
- compile feasibility inspection；
- ModelBindings against real asset；
- 如不改变项目状态的只读/临时验证；
- 新增报告；
- 新增 INTERNAL bridge contract 文档。

---

# 34. 建议输出

生成：

~~~text
docs/HISTORY_PCAP_Round5A_Real_Model_Assets_Bridge_Contract_Gate_20261007.md
~~~

可选：

~~~text
docs/internal/model_consumer_bridge_v1.md
~~~

若生成 internal contract，报告必须链接它。

---

# 35. 5A 报告结构

## 1. Executive Summary

必须直接给：

~~~text
REAL_MODEL_ASSET_GATE =
  GO / CONDITIONAL_GO / NO_GO

INTERNAL_BRIDGE_CONTRACT =
  FROZEN / BLOCKED
~~~

## 2. Search Scope

列实际搜索目录。

## 3. Asset Inventory

按真实路径和 hash。

## 4. Real vs Fixture Classification

## 5. hil_contract Validation

## 6. Generated ABI Validation

## 7. Build / Executable Trace

## 8. ModelBindings Against Real Asset

## 9. Missing Assets / Blocking Dependencies

## 10. Authoritative Model Step Decision

## 11. Epoch / Core Instance Decision

## 12. Bridge Transport Decision

## 13. Request Identity

## 14. Payload / Path Mapping

## 15. Control Ownership Contract

## 16. Deadline / Expiry Contract

## 17. Idempotency

## 18. STAGED Semantics

## 19. APPLIED Semantics

## 20. Final ModelU Readback Probe

## 21. Result Query / UNKNOWN

## 22. Lifecycle / Restart Rules

## 23. Capacity / Completion Retention

## 24. Error Mapping

## 25. Security Boundary

## 26. Internal Bridge V1 Schema

## 27. 5B Entry Gate

## 28. Risks / Open Questions

## 29. Definition of Done

---

# 36. 5B Entry Gate

必须明确：

> 什么条件满足后，才能开始修改 C Core。

建议至少：

~~~text
REAL_MODEL_ASSET_GATE != NO_GO
Bridge V1 frozen
authoritative model step frozen
epoch semantics frozen
owner semantics frozen
100ms deadline exact boundary frozen
APPLIED exact event frozen
final readback mechanism identified
query/UNKNOWN policy frozen
capacity reservation frozen
~~~

如果真实模型资产 NO-GO：

> 5B 不得以 fake model 进入“真实模型实施”。

可以另开：

~~~text
5B-TEST-HARNESS
~~~

但必须明确：

~~~text
C_TEST_ABI_ONLY
~~~

不能升级为真实 E2。

---

# 37. Definition of Done

5A 只有满足以下条件才完成：

- [ ] 已阅读 Round 5 Architecture Review；
- [ ] 已搜索约定范围内真实 quad 模型资产；
- [ ] 每个资产有分类；
- [ ] 每个真实资产记录 SHA256；
- [ ] 已确认或否定真实 hil_contract；
- [ ] 已确认或否定真实 generated ABI；
- [ ] 已确认 build / executable trace；
- [ ] 真实 hil_contract 如存在已通过 ModelBindings；
- [ ] 已给出 GO / CONDITIONAL_GO / NO_GO；
- [ ] 已冻结 authoritative model step；
- [ ] 已冻结 core_instance / epoch；
- [ ] 已冻结 bridge transport；
- [ ] 已冻结 request identity；
- [ ] 已冻结 payload/path mapping；
- [ ] 已冻结 owner contract；
- [ ] 已冻结 exact 100ms deadline；
- [ ] 已冻结 idempotency；
- [ ] 已冻结 STAGED；
- [ ] 已冻结 APPLIED；
- [ ] 已冻结 final readback probe；
- [ ] 已冻结 query/UNKNOWN；
- [ ] 已冻结 lifecycle/restart；
- [ ] 已冻结 capacity；
- [ ] 已冻结 error mapping；
- [ ] 已冻结 security boundary；
- [ ] 已给出 5B Entry Gate；
- [ ] 未修改生产核心代码；
- [ ] 未修改 Round 1~4 证据；
- [ ] 已生成 5A 报告。

---

# 最终原则

Round 5 Review 已经回答：

> **应该怎么接。**

Round 5A 要回答：

> **我们手里是否真的有可以接的模型，以及内部桥在动代码之前必须遵守什么精确契约。**

如果真实资产不存在：

> **NO-GO 是正确结果。**

不要用 fixture 把 NO-GO 美化成 GO。

如果内部 Bridge Contract 仍有关键语义未冻结：

> **BLOCKED 是正确结果。**

不要进入 5B 后边写边定协议。
