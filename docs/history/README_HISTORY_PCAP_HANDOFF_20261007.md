# HISTORY / PCAP 阶段性交付说明

日期：2026-10-07  
项目根目录：

~~~text
E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006
~~~

交付性质：

> **3.3 → 3.6 HISTORY / PCAP 集成阶段基线交付**

本文件用于说明：已经完成什么、当前代码如何理解、哪些能力尚未完成，以及接手后应从哪里继续。

---

# 1. 当前总状态

截至本次交付：

~~~text
Round 0  交接代码审查                         ✅
Round 1  reference.pcap                      ✅
Round 2  prepared.pcap                       ✅
Round 3  tcpreplay 实际 Linux TX / RX        ✅
Round 4  PCAP → 3.6 Gateway Admission        ✅
Round 5  Model Consumer Architecture Review  ✅
Round 5A Real Model Asset + Bridge Gate       ✅
~~~

Round 5A 最终结论：

~~~text
REAL_MODEL_ASSET_GATE = NO_GO
INTERNAL_BRIDGE_CONTRACT = FROZEN
REAL_MODEL_RUNNABLE = NOT_VERIFIED
REAL_E2 = NOT_EVALUATED
5B_REAL_MODEL_ENTRY = BLOCKED_BY_REAL_ASSETS
~~~

因此：

> HISTORY / PCAP 已经真实打通到 3.6 Gateway / Session / Admission 边界。

但：

> Gateway → Real Model Consumer → C Core → Real ModelU → APPLIED 尚未完成。

---

# 2. 已完成能力

## 2.1 Round 1：Reference PCAP

已经完成：

~~~text
BusinessMessage
→ WireCodec
→ Ethernet / IPv4 / UDP
→ reference.pcap
→ CaptureParser
→ HistoryDecoder
~~~

当前基准文件：

~~~text
artifacts/history/round1/reference.pcap
~~~

已冻结业务消息：

~~~text
message_id = 7
name = FlightQuad
direction = TO_36
model = quadrotor_hil
payload = {"motor_command":[0.1,0.2,0.3,0.4]}
~~~

Reference PCAP SHA256：

~~~text
c335601a095d9baf1c093bfd195f042b5e7899c31b03071f249f26488819efb3
~~~

## 2.2 Round 2：Replay Preparation

已完成：

~~~text
reference.pcap
→ CaptureParser
→ HistoryDecoder
→ ReplayProcessor(REENCODE)
→ ReplayExporter
→ prepared.pcap
→ ToolCommandBuilder
→ tcpreplay argv
~~~

当前文件：

~~~text
artifacts/history/round2/prepared.pcap
~~~

SHA256：

~~~text
febbf0e10c98b3d4adafa7dcb5027e0e6b0f212b6828a779f404d51ddf172134
~~~

Round 2 的 session/header 仅为离线 preparation fixture，不代表真实在线授权。

## 2.3 Round 3：真实 Linux 网络 TX / RX

已在 WSL2 Ubuntu 隔离 namespace / veth 中实际执行：

~~~text
prepared.pcap
→ tcpreplay
→ Linux veth
→ tcpdump
→ received.pcap
~~~

最终有效 attempt：

~~~text
artifacts/history/round3/retry_2/
~~~

验证结果：

~~~text
tcpreplay actual TX         ✅
tcpdump actual RX           ✅
packet count                ✅
raw Ethernet frame bytes    ✅ byte-exact
UDP payload                 ✅ byte-exact
WireCodec decode            ✅
CRC                         ✅
cleanup                     ✅
~~~

Raw Ethernet frame SHA256：

~~~text
b5c0811f436742860216a520042c429b0360e39d8028071af05ea8cea76217cb
~~~

注意：

> Round 3 只证明 tcpreplay / Linux network toolchain，不证明 3.6 Gateway 或模型。

---

# 3. Round 4：已真实进入 3.6 Gateway

Round 4 已完成真实在线会话：

~~~text
SessionOpen
→ SessionOpened(real SID)
→ current-session replay PCAP
→ tcpreplay
→ 3.6 UDPGateway
→ Receiver
→ SessionRegistry
→ RECEIVED / OK
→ FAILED / TARGET_MISSING
~~~

最终有效证据：

~~~text
artifacts/history/round4/retry_4/
artifacts/history/round4/round4_summary.json
~~~

当次真实 Session：

~~~text
session_id = 2017155087
role = CONTROLLER
lease = 1000 ms
implemented_message_ids = [1]
~~~

SessionOpened → tcpreplay 启动：

~~~text
约 31.7 ms
~~~

Gateway 对 ID7 返回：

~~~text
Ack #1
stage = RECEIVED
error = OK

Ack #2
stage = FAILED
error = TARGET_MISSING
~~~

这是 Round 4 的预期成功边界。

因此当前可以真实声明：

~~~text
received_by_3_6 = true
gateway_session_admitted = true
~~~

但不能声明：

~~~text
source_capability_authorized = true
applied = true
consumed = true
execution_ready = true
~~~

---

# 4. 为什么 Round 4 的 FAILED / TARGET_MISSING 是正确结果

当前默认 3.6 Gateway：

~~~text
implemented_message_ids = [1]
~~~

没有真实 ID7 Model Consumer。

因此合法 ID7 在完成 Gateway admission 后：

~~~text
RECEIVED / OK
→ FAILED / TARGET_MISSING
~~~

正好证明：

> 协议、Session、授权和 Gateway admission 已通过，但真实模型消费者不存在。

不要为了“跑通”而把 capabilities 静态修改为：

~~~text
[1,7]
~~~

只有真实 ID7 Consumer ready 后，才能诚实发布 ID7 capability。

---

# 5. Round 5 Architecture Review 结论

架构审查文件：

~~~text
docs/HISTORY_PCAP_Round5_Model_Consumer_Architecture_Review_20261007.md
~~~

当前真实断点：

~~~text
UDPGateway
→ Receiver
→ SessionRegistry.accept
→ RECEIVED
→ 【缺 Model Consumer 接线】
→ ModelQueue
→ 【缺真实模型桥】
→ C Core
→ ModelU
→ model_step
~~~

已确认：

- Receiver 当前没有生产路径调用 ModelQueue.enqueue；
- ModelBindings 是结构映射基础，不是实际 ModelU writer；
- ModelQueue 是目标步队列基础，不是实际 C Core Consumer；
- 旧 core_client / set_inputs 只是参考路径；
- 旧 C receipt accepted 不能直接作为 APPLIED；
- motor_command 可能在 model_step 前被 mission / ControlArbiter 再次覆盖；
- C Core 应作为 authoritative 1 ms model-step authority；
- Python 不应自行猜 C Core 当前模型步。

---

# 6. APPLIED / CONSUMED 当前语义

冻结 v0.3 定义：

~~~text
E0 = 实际发送
E1 = 接收 / 校验
E2 = 真实模型写入或消费者读取
E3 = 可观察业务 / 安全响应
~~~

对于当前 ID7 MVP：

~~~text
RECEIVED     ✅ 已完成
APPLIED      ❌ 尚未完成
CONSUMED     不作为当前 ID7 MVP 必需阶段
E3           ❌ 尚未验证
~~~

Round 5 Architecture Review 已明确：

> 旧 set_inputs receipt accepted ≠ APPLIED。

推荐 APPLIED 需要至少证明：

~~~text
目标 step S
→ 最终 control writer 完成
→ ModelU.motor_command 最终读回
→ 与原 ID7 request 精确关联
→ 值未被后续 writer 覆盖
~~~

---

# 7. Round 5A：真实模型资产 Gate

报告：

~~~text
docs/HISTORY_PCAP_Round5A_Real_Model_Assets_Bridge_Contract_Gate_20261007.md
~~~

内部 Bridge Contract：

~~~text
docs/internal/model_consumer_bridge_v1.md
~~~

Round 5A 实际搜索范围：

~~~text
handoff root
E:\GuoZhao\Desktop\UAVDemo\3_6
E:\GuoZhao\Desktop\UAVDemo
~~~

未发现完整真实 quadrotor_hil 模型包。

缺失的关键真实资产包括：

~~~text
hil_contract.json
model_contract.h
model_rt_bridge.h
build_script.m 或等价生成流程
quadrotor_hil.slx / .mdl / 模型依赖
generated C/C++ / objects
package manifest
真实 C build target
真实 model executable
~~~

因此：

~~~text
REAL_MODEL_ASSET_GATE = NO_GO
~~~

注意：

> NO_GO 是正确的资产门禁结果，不表示 Round 5A 执行失败。

它表示：

> 在当前交付范围内，没有足够证据允许继续声称“真实模型已就绪”。

---

# 8. Internal Bridge V1 已冻结

文件：

~~~text
docs/internal/model_consumer_bridge_v1.md
~~~

该协议只用于：

~~~text
ModelConsumerService
↔
C Core
~~~

它不是新的外部 ICD，不修改 HIL-ICD-1.0。

已冻结的核心语义包括：

~~~text
core_instance_id
run_epoch
authoritative C model step
target_step
pre-stage
STAGED
APPLIED
REJECTED
UNKNOWN
request identity
request hash
idempotency
control owner
100 ms deadline
final ModelU readback probe
result query
lifecycle / restart
capacity / completion reservation
~~~

传输推荐继续复用：

~~~text
127.0.0.1 UDP
~~~

但不能直接把旧：

~~~text
set_inputs → accepted receipt
~~~

当成正式 Model Consumer Bridge。

---

# 9. 当前最重要的限制

以下能力目前没有完成：

~~~text
真实 quadrotor_hil generated model
真实 ModelU ABI qualification
真实 Model Consumer
Receiver → ModelQueue production wiring
ModelQueue → C Core production bridge
target_step → C real boundary implementation
final ModelU readback probe
ID7 APPLIED
E3 model-response evidence
Kylin qualification
真实 3.3
真实 HIL hardware
~~~

因此接手时禁止把当前代码描述为：

> “ID7 已经进入真实模型并生效”。

当前准确表述应为：

> **ID7 HISTORY replay 已通过真实在线 Session 进入 3.6 Gateway；真实 Model Consumer 尚未实施。**

---

# 10. 接手后从哪里继续

当前下一阶段：

~~~text
Round 5B
C target-step / Real Input Proof
~~~

但当前：

~~~text
5B_REAL_MODEL_ENTRY = BLOCKED_BY_REAL_ASSETS
~~~

所以第一步不是修改 C Core，而是：

~~~text
模型 / Simulink 负责人
→ 提供真实 quadrotor_hil 资产包
→ 重新执行 5A Real Asset Gate
→ GO / CONDITIONAL_GO
→ 才进入 5B
~~~

---

# 11. 建议模型同学提供的资产

建议一次性交付：

~~~text
quadrotor_hil/
├─ hil_contract.json
├─ model_contract.h
├─ model_rt_bridge.h
├─ build_script.m 或等价生成脚本
├─ *.slx / *.mdl 及依赖
├─ generated model C/C++ source
├─ generated objects / libraries（如适用）
├─ package_manifest.json
├─ build instructions
└─ 可构建 / 可执行目标
~~~

并能够回答：

~~~text
model_name 是什么？
solver step 是否固定 1 ms？
motor_command 映射到哪个真实 ModelU 字段？
这些文件是否来自同一次构建？
MATLAB / Simulink / ERT 版本是什么？
如何重新生成？
如何构建？
资产 SHA256 是什么？
~~~

不要只交几个无法关联同一构建的 header。

---

# 12. Round 5 后续计划

当前冻结计划：

~~~text
5A  Real Assets + Bridge Contract        ✅
      └─ Asset = NO_GO
      └─ Bridge V1 = FROZEN

5B  C Target-Step + Final Readback       ⏸ BLOCKED
5C  Lifecycle / Owner / Safety           ⏸
5D  Python ModelConsumerService          ⏸
5E  Receiver Integration / Capability    ⏸
5F  Same PCAP → Real Model → APPLIED     ⏸
~~~

5B 以后不要重新设计 HISTORY / PCAP / Session / Gateway。

这些部分已经有 Round 1～4 证据基线。

---

# 13. Source of Truth

外部正式协议 Source of Truth：

~~~text
docs/interfaces/输入模拟器完整接口定义_v0.3_单文件汇总.md
~~~

冻结 baseline：

~~~text
docs/interfaces/baseline/
~~~

HIL-ICD-1.0 v0.3 baseline SHA256：

~~~text
22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27
~~~

内部 Model Consumer Bridge：

~~~text
docs/internal/model_consumer_bridge_v1.md
~~~

注意：

> Internal Bridge V1 不是外部 ICD，也不能替代 frozen v0.3。

---

# 14. 文档索引

## Round 1

~~~text
docs/HISTORY_PCAP_Round1_Reference_PCAP_Report_20261006.md
~~~

## Round 2

~~~text
docs/HISTORY_PCAP_Round2_Prepared_PCAP_Report_20261006.md
~~~

## Round 3

~~~text
docs/HISTORY_PCAP_Round3_Tcpreplay_Isolated_Linux_Report_20261006.md
~~~

## Round 4 Design

~~~text
docs/HISTORY_PCAP_Round4_Online_Session_Gateway_Design_20261007.md
~~~

## Round 4 Implementation

~~~text
docs/HISTORY_PCAP_Round4_Online_Session_Gateway_Implementation_Report_20261007.md
~~~

## Round 5 Architecture Review

~~~text
docs/HISTORY_PCAP_Round5_Model_Consumer_Architecture_Review_20261007.md
~~~

## Round 5A Asset / Bridge Gate

~~~text
docs/HISTORY_PCAP_Round5A_Real_Model_Assets_Bridge_Contract_Gate_20261007.md
~~~

## Internal Bridge V1

~~~text
docs/internal/model_consumer_bridge_v1.md
~~~

---

# 15. HISTORY 证据索引

## Round 1

~~~text
artifacts/history/round1/
├─ reference.pcap
├─ reference_manifest.json
└─ round1_validation.json
~~~

## Round 2

~~~text
artifacts/history/round2/
├─ prepared.pcap
├─ prepared_manifest.json
├─ round2_validation.json
└─ tcpreplay_command.json
~~~

## Round 3

~~~text
artifacts/history/round3/
├─ initial_blocked/
├─ retry_1/
├─ retry_2/
├─ environment.json
├─ round3_manifest.json
└─ round3_validation.json
~~~

最终以 retry_2 为有效网络 qualification evidence。

## Round 4

~~~text
artifacts/history/round4/
├─ retry_1/
├─ retry_2/
├─ retry_3/
├─ retry_4/
├─ cleanup_status.json
└─ round4_summary.json
~~~

最终以 retry_4 与 round4_summary.json 为准。

---

# 16. 环境与主要依赖

## Windows Python

此前 HISTORY / PCAP 验证使用独立 Python 3.12 Conda 环境：

~~~text
E:\GuoZhao\Desktop\UAVDemo\.conda-envs\uav-history-pcap
~~~

依赖 Source of Truth：

~~~text
requirements-icd.txt
~~~

不要安装进旧 Python 3.6.9 HIL 环境。

## WSL2

Round 3 / Round 4 使用：

~~~text
Ubuntu 24.04.3 LTS
WSL2
tcpreplay 4.4.4
tcpdump 4.99.4
libpcap 1.10.4
~~~

Round 4 已创建 WSL Conda 环境：

~~~text
uav-history-round4
~~~

实际后续使用前请重新确认环境仍存在，不要把历史报告当作当前机器状态检查的替代。

---

# 17. 常用验证入口

冻结协议检查：

~~~text
python -X utf8 scripts/build_contract_single_file.py --check
~~~

现有 ICD 全量回归入口：

~~~text
python -X utf8 scripts/test_icd_runtime.py
~~~

历史 Round 3 / 4 的具体执行脚本与参数，请以对应 Implementation Report / artifacts 为准，不建议绕过报告直接复用旧 SID 或旧在线 PCAP。

特别注意：

> Round 4 的 SID 2017155087 是历史证据，不可复用为新 session。

---

# 18. 当前测试基线

历史完整回归最近一次实际结果：

~~~text
1001 tests
1 failure
3 errors
~~~

这些是 Round 3 / Round 4 已知既有基线问题，并非全绿。

Round 5 Architecture Review：

~~~text
80 focused tests
79 passed
1 error
~~~

错误来自既有缺失 fixture：

~~~text
artifacts/generic_models/multirotor_6/hil_contract.json
~~~

Round 5A ModelBindings：

~~~text
10 tests
9 passed
1 error
~~~

同样是上述既有缺失 fixture。

Round 5 / 5A 没有重新执行完整 1001 项 suite，因此不要把 Round 4 的全量结果描述成本轮重新验证结果。

---

# 19. 不要擅自修改的基线

以下内容在没有正式评审前不要擅自修改：

~~~text
HIL-ICD-1.0 v0.3
docs/interfaces/baseline/
docs/interfaces/输入模拟器完整接口定义_v0.3_单文件汇总.md

Round 1 reference.pcap
Round 2 prepared.pcap
Round 3 最终 qualification evidence
Round 4 最终 admission evidence

Internal Bridge V1
~~~

特别不要为了“让 ID7 跑通”直接：

~~~text
implemented_message_ids = [1,7]
~~~

Capability 必须由真实 Consumer readiness 决定。

---

# 20. 不要重新打开已经证明的问题

接手后原则上不要重新争论：

~~~text
HISTORY 是否能生成 PCAP          ✅ 已证明
prepared replay 是否可生成       ✅ 已证明
tcpreplay 是否能实际发包          ✅ 已证明
Ethernet frame 是否原样传输       ✅ 已证明
真实 Session 是否可建立           ✅ 已证明
PCAP 是否能进入 3.6 Gateway       ✅ 已证明
Gateway 是否会 admission ID7      ✅ 已证明
~~~

当前真正要解决的是：

~~~text
Gateway
→ Model Consumer
→ C Core
→ Real ModelU
→ APPLIED
~~~

---

# 21. 当前推荐协作方式

本交付建议作为：

> **Integration Baseline V1**

后续可以并行：

~~~text
模型 / Simulink 同学：
补真实 quadrotor_hil 模型资产

接手 HISTORY / Gateway 同学：
熟悉 Round 1～5A
保持 frozen ICD / Bridge Contract

C / Model Consumer 实施：
真实资产通过 5A Gate 后继续 5B
~~~

不要把所有后续工作继续串行压在原 HISTORY 开发者一人身上。

---

# 22. 当前准确的一句话状态

对项目成员建议统一表述：

> **HISTORY / PCAP 输入链路已通过真实网络、在线 Session 和 3.6 Gateway Admission 验证；Model Consumer 架构及内部 Bridge V1 已冻结。当前真实模型资产门禁为 NO_GO，因此 ID7 的真实 Model APPLIED 尚未实施，后续从补齐 quadrotor_hil 真实模型资产并重新通过 5A Gate 后继续。**

---

# 23. 交付边界

本次交付不是：

~~~text
完整 3.6 最终验收
真实模型已全部接通
真实 3.3 替换完成
物理 HIL 完成
麒麟正式 qualification
~~~

本次交付是：

~~~text
HISTORY / PCAP → 3.6 Gateway
阶段性完整技术基线
+
Model Consumer 下一阶段冻结设计
~~~

接手人应以现有证据继续向下集成，而不是重新从通信协议开始设计。
