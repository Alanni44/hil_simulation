# HISTORY PCAP Round 4：在线 Session + 3.6 Gateway Admission 设计

日期：2026-10-07  
状态：DESIGN  
目标环境：WSL2 software-only isolated network  
目标：把 HISTORY PCAP 真正送入当前 3.6 Gateway，并取得真实 Gateway E1 反馈。

## 1. Round 4 目标

Round 4 首次验证：

~~~text
SessionOpen
→ SessionOpened(real session_id)
→ current-session online prepared PCAP
→ tcpreplay
→ 3.6 UDPGateway
→ Receiver / SessionRegistry
→ Ack(RECEIVED)
→ Ack(FAILED/TARGET_MISSING)
~~~

本轮验收边界固定为：

> 3.6 Gateway / Receiver 已真实收到并完成 admission。

本轮不证明 APPLIED、CONSUMED、模型真正吃到输入、真实 3.3、真实 HIL 或目标麒麟 qualification。

## 2. 已确认事实

### 2.1 当前 Gateway 是协议 / Session / Admission Boundary

当前启动入口为：

~~~text
python -m icd_gateway
~~~

实际链路：

~~~text
UDPGateway
→ Receiver
→ SessionRegistry
~~~

当前默认没有 ModelQueue、ResourceWorker 或真实 model consumer，因此它不是完整模型入口。

### 2.2 当前 SessionOpened capabilities 只发布 [1]

当前 Receiver 发布：

~~~json
"implemented_message_ids": [1]
~~~

现有测试也明确要求该值为 [1]。

因此 Round 4 不允许为了测试把它改成 [1, 7]。否则会把“Receiver 能解析并拒绝 ID7”错误表述成“3.6 已实现 ID7 consumer”。

### 2.3 SourceSession 会严格检查 capabilities

SourceSession._preview_header() 当前要求：

~~~text
message_id ∈ implemented_message_ids
~~~

所以当前真实 SourceSession：

~~~text
SessionOpen         ✅
ID7 allocate_header ❌ TARGET_MISSING
Heartbeat           ❌ TARGET_MISSING
~~~

因此 Round 4 不能声称“SourceSession-authorized replay”。

### 2.4 Receiver 能对未实现 consumer 的合法输入给出 E1 证据

当前 Receiver 对合法 session / role / model / sequence 的普通输入会返回：

~~~text
Ack(RECEIVED, OK)
Ack(FAILED, TARGET_MISSING)
~~~

所以本轮应定义为：

> Gateway Admission Probe

而不是 Production Replay Execution。

### 2.5 Round 1 / Round 2 当前 HISTORY 消息是 ID7

冻结定义：

~~~text
message_id = 7
name = FlightQuad
direction = TO_36
encoding = PACKED_LE
transports = CANFD / UDP
role = CONTROLLER
period_ms = 20
valid_for_ms = 100
application = TARGET_MODEL_STEP
model_id = quadrotor_hil
payload = motor_command[4]
~~~

Round 4 优先继续复用 ID7，保持 Round 1 → 2 → 3 → 4 同一条证据链。

## 3. 当前关键矛盾

现有 development config：

~~~json
"roles": ["STIMULUS"]
~~~

但 ID7 要求：

~~~text
role = CONTROLLER
~~~

若保持原配置，ID7 会在 Receiver.pre_authorize 阶段直接 AUTHORIZATION 失败，不会得到 RECEIVED。

## 4. 设计决策：新增 Round 4 专用 Development Config

不修改：

~~~text
config/input-simulator-development.json
~~~

新增：

~~~text
config/input-simulator-round4-development.json
~~~

建议使用最小 CONTROLLER grant：

~~~json
{
  "mode": "DEVELOPMENT",
  "channel": "ETH_0",
  "receiver_bind": {
    "ip": "10.36.0.20",
    "port": 36100
  },
  "grants": [
    {
      "identity": {
        "run_id": "item-01",
        "source_id": "item-01",
        "vehicle_id": "vehicle-01",
        "scenario_id": "item-01",
        "model_id": "quadrotor_hil",
        "definition_version": "HIL-ICD-1.0"
      },
      "roles": ["CONTROLLER"],
      "source_endpoint": {
        "ip": "10.36.0.10",
        "port": 36102
      },
      "feedback_endpoint": {
        "ip": "10.36.0.10",
        "port": 36101
      }
    }
  ]
}
~~~

原则：

- 只用于 isolated DEVELOPMENT；
- 不扩大到 STIMULUS；
- 不替换原 development config；
- 不改变正式 capability 发布值。

## 5. Round 4 网络拓扑

沿用 Round 3 隔离拓扑：

~~~text
source namespace
uav-r4-src-*
eth0
MAC 02:00:00:00:00:01
IP  10.36.0.10/24
:36102 source
:36101 feedback
       │
       │ veth
       ▼
gateway namespace
uav-r4-gw-*
eth0
MAC 02:00:00:00:00:02
IP  10.36.0.20/24
:36100 UDPGateway
       │
       ▼
Receiver
       │
       ▼
SessionRegistry
~~~

要求：

- 无 default route；
- 无 bridge 到 Windows 物理网卡；
- 不使用 Windows Npcap；
- 不访问校园网 / Internet；
- 只使用临时 namespace / veth。

## 6. Python 环境

用户日常 Python 环境习惯为 Conda / Anaconda。

当前已确认 WSL Ubuntu 没有 conda，但有 /usr/bin/python3。

Round 4 实施时建议在 WSL 内单独建立 Conda 环境：

~~~text
uav-history-round4
~~~

不要复用 Windows Conda Python，因为 Windows python.exe 不能真正运行在 WSL network namespace 内。

环境安装仓库现有：

~~~text
requirements-icd.txt
~~~

继续与 legacy HIL Python 环境隔离。

## 7. 分阶段设计

建议拆成：

~~~text
R4-E0  Environment Gate
R4-A   Online Session
R4-B   Current-Session PCAP Preparation
R4-C   tcpreplay → 3.6 Gateway
R4-D   Feedback / Evidence Validation
R4-E   Cleanup / Regression
~~~

## 8. R4-E0：Environment Gate

先确认：

~~~text
WSL2                     ✅
Conda env                ✅
python deps              ✅
tcpreplay                ✅
tcpdump                  ✅
ip netns                 ✅
Round 1 reference input  ✅
baseline SHA256          ✅
~~~

并提前完成 namespace、veth、Gateway、tcpdump 等准备。

SessionOpen 必须最后才开始，因为 session lease 只有 1000 ms。

## 9. R4-A：Online Session

Gateway 在 gateway namespace 中绑定：

~~~text
10.36.0.20:36100
~~~

必须先出现：

~~~json
{"status":"DEVELOPMENT_READY"}
~~~

随后 source namespace 通过现有 UDPSource + SourceSession 执行真实 SessionOpen，不手工拼 UDP bytes。

SessionOpen：

~~~text
session_id = 0
sequence = 1
target_step = 0
~~~

要求真实收到 SessionOpened，并持久化：

- real session_id；
- accepted_roles；
- lease_ms；
- capabilities；
- request / response bytes；
- monotonic start/end；
- Gateway process information。

R4-A DoD：

~~~text
session_open_sent          = true
session_opened_received    = true
real_session_id_nonzero    = true
accepted_role_controller   = true
lease_ms                   = 1000
implemented_message_ids    = [1]
replacement_ready          = false
~~~

特别注意：implemented_message_ids=[1] 在 Round 4 是正确的当前能力边界，不是失败。

## 10. R4-B：Current-Session PCAP Preparation

继续从 Round 1：

~~~text
artifacts/history/round1/reference.pcap
~~~

重新经过：

~~~text
HistoryDecoder
→ ReplayProcessor
→ ReplayExporter
~~~

不直接 patch Round 2 prepared.pcap bytes。

Replay mode 建议继续使用 REENCODE，原因是 Round 2 已验证该路径。本轮只引入一个新变量：online session identity，不同时改变 replay mode、payload、transport、model 或 rate。

### 在线 Header

禁止复用 Round 2 fixture：

~~~text
session_id = 92
sequence = 102
transaction_id = 302
~~~

第一条 Round 4 replay probe 建议：

~~~text
session_id     = SessionOpened.real_session_id
sequence       = 2
transaction_id = 2
target_step    = 201
valid_for_ms   = 100
~~~

其中 target_step=201 只用于 Gateway admission，不表示已经和真实模型 step 对齐。

必须记录：

~~~text
target_step_semantically_qualified = false
~~~

### 为什么不能直接调用 SourceSession.allocate_header(7)

当前 SessionOpened 仍然只有：

~~~json
"implemented_message_ids": [1]
~~~

因此 SourceSession.allocate_header(7) 应继续 TARGET_MISSING。

本轮动态 Header 必须明确标记为：

> Gateway Admission Probe Header

而不是：

> SourceSession-authorized production header

Manifest 必须分开记录：

~~~json
{
  "source_capability_authorized": false,
  "gateway_session_admitted": true
}
~~~

## 11. R4-C：tcpreplay → 3.6 Gateway

### Session 时间窗口

当前 lease 为 1000 ms，且 SourceSession 当前不能正式 Heartbeat。

所以 Round 4 设计成一次性短窗口 admission probe。

SessionOpen 前必须提前完成：

- Gateway ready；
- tcpdump ready；
- reference decode；
- policy load；
- ExportBinding ready；
- tcpreplay executable check；
- output path preflight；
- namespace / veth ready。

取得 SessionOpened 后只做：

~~~text
real SID
→ ReplayHeader
→ ReplayProcessor
→ ReplayExporter
→ online_prepared.pcap
→ tcpreplay
~~~

建议门禁：

~~~text
SessionOpened → tcpreplay start <= 500 ms
~~~

若超过 500 ms：

~~~text
FAIL CURRENT_SESSION_WINDOW
~~~

不得继续发送旧 SID。必须重新 SessionOpen，获得新 SID，再生成新的 online_prepared.pcap。

### 实际发送

tcpreplay：

~~~text
source namespace
eth0
--loop=1
--multiplier=1.0
online_prepared.pcap
~~~

只允许单次发送，不允许 loop > 1、speedup、arbitrary argv 或 Windows NIC fallback。

## 12. R4-D：Gateway Feedback Validation

ID7 application 为 TARGET_MODEL_STEP，而当前没有 model consumer。

因此本轮成功时预期：

~~~text
Ack #1
stage = RECEIVED
error = OK

Ack #2
stage = FAILED
error = TARGET_MISSING
~~~

这正是 Round 4 的成功结果。

两条 Ack 必须验证：

~~~text
session_id == real SID
transaction_id == replay transaction
request_sequence == replay sequence
request_message_id == 7
probe_id == 0
~~~

Feedback sequence 只要求严格递增，不硬编码具体数值。

### 反馈采集

推荐同时做两层。

原始网络证据：

~~~text
tcpdump
src 10.36.0.20:36100
dst 10.36.0.10:36101
→ gateway_feedback.pcap
~~~

正式协议证据：

~~~text
CaptureParser
→ WireCodec(direction="FROM_36")
→ Ack correlation validation
~~~

不要只依赖 stdout 或日志。

## 13. 建议证据目录

~~~text
artifacts/history/round4/
├─ environment.json
├─ session_open.json
├─ online_prepared.pcap
├─ online_prepared_manifest.json
├─ request_tx.pcap
├─ gateway_feedback.pcap
├─ gateway_feedback.json
├─ tcpreplay_stdout.txt
├─ tcpreplay_stderr.txt
├─ tcpreplay_exit_code.txt
├─ gateway_stdout.txt
├─ gateway_stderr.txt
├─ cleanup_status.json
├─ round4_manifest.json
└─ round4_validation.json
~~~

建议最终 claims：

~~~json
{
  "session_opened": true,
  "real_session_id": true,
  "source_capability_authorized": false,
  "online_pcap_prepared": true,
  "process_started": true,
  "actual_network_tx": true,
  "received_by_3_6": true,
  "gateway_session_admitted": true,
  "received_ack_observed": true,
  "failed_target_missing_observed": true,
  "applied": false,
  "consumed": false,
  "execution_ready": false,
  "target_kylin_qualified": false
}
~~~

## 14. Round 4 Definition of Done

### Session

- [ ] Gateway DEVELOPMENT_READY
- [ ] SessionOpen 真实发出
- [ ] SessionOpened 真实收到
- [ ] real SID 非 0
- [ ] accepted role 包含 CONTROLLER
- [ ] capability 仍真实记录为 [1]

### PCAP

- [ ] Round 1 reference hash 未改变
- [ ] HistoryDecoder 重新读取
- [ ] ReplayProcessor 使用 real SID
- [ ] sequence fresh
- [ ] Header 与 CRC 正式验证
- [ ] online_prepared.pcap 成功落盘
- [ ] payload 仍为原 ID7 motor_command

### Network

- [ ] tcpreplay process_started=true
- [ ] actual_network_tx=true
- [ ] Gateway 实际收到
- [ ] source peer == 10.36.0.10:36102
- [ ] receiver == 10.36.0.20:36100

### Gateway Feedback

- [ ] RECEIVED / OK
- [ ] FAILED / TARGET_MISSING
- [ ] SID 关联正确
- [ ] sequence 关联正确
- [ ] transaction 关联正确
- [ ] message_id=7
- [ ] probe_id=0

### Boundary

- [ ] APPLIED=false
- [ ] CONSUMED=false
- [ ] execution_ready=false
- [ ] source_capability_authorized=false
- [ ] target_kylin_qualified=false

### Cleanup

- [ ] Gateway stopped
- [ ] tcpdump stopped
- [ ] tcpreplay stopped
- [ ] namespace deleted
- [ ] veth deleted
- [ ] no residual process
- [ ] no host route changes

## 15. Fail-Closed Rules

以下任意情况停止本次 attempt：

~~~text
SessionOpen failed
SessionOpened missing
role != CONTROLLER
SID == 0
lease window exceeded
old SID reused
sequence <= 1
captured SID reused
CRC failed
payload changed
AUTHORIZATION before RECEIVED
OUT_OF_ORDER
STALE_SESSION
DUPLICATE
MODEL
Ack correlation mismatch
~~~

尤其：

> 如果 Round 4 出现 APPLIED 或 CONSUMED，不视为“超额成功”。

因为当前 Gateway 没有 model consumer。出现这种结果反而意味着边界和当前实现不一致，应立即停止并审查。

## 16. Round 4 不做的事情

不要：

1. 修改 implemented_message_ids 为 [1,7]；
2. 给当前 Receiver 伪造 model consumer；
3. 修改 Round 1 reference.pcap；
4. 修改 Round 2 prepared.pcap；
5. 直接 patch PCAP bytes；
6. 手工拼 HIL1 UDP packet；
7. 手工改 CRC；
8. 伪造 Heartbeat；
9. 放宽 1000 ms lease；
10. 把 RECEIVED 当 APPLIED；
11. 接 Windows 物理网卡；
12. 顺便做麒麟 qualification。

## 17. 建议新增代码边界

优先新增：

~~~text
scripts/
  validate_history_round4_gateway.py
  validate_history_round4_linux.sh
~~~

必要时增加纯证据模块：

~~~text
input_simulator/
  replay_gateway_evidence.py
~~~

该模块只能比较 persisted PCAP、解码 Gateway feedback、校验 correlation。

原则上不修改：

~~~text
icd_runtime/
icd_gateway/
input_simulator/session.py
input_simulator/replay.py
~~~

如果实施过程中必须修改这些核心模块，应停止 Round 4 并单独评审。

## 18. 测试策略

至少覆盖：

### Online Preparation

- real SID 写入 replay Header；
- captured SID 不得复用；
- sequence 必须 fresh；
- payload 不变；
- CRC 正确。

### Gateway Evidence

- RECEIVED → FAILED/TARGET_MISSING 合法；
- AUTHORIZATION 不得误判 PASS；
- APPLIED / CONSUMED 必须 fail closed；
- wrong SID / sequence / transaction / message_id 均失败。

### Lease

- session age 在门限内可执行；
- 超过门限 fail closed；
- 不自动复用旧 SID。

### Cleanup

- Gateway failure 后仍清理；
- tcpreplay failure 后仍清理；
- feedback timeout 后仍清理。

## 19. Round 4 成功状态名称

推荐：

~~~text
ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED
~~~

含义：

> HISTORY replay 使用真实在线 Session 身份，真实进入 3.6 Gateway，并取得 Receiver Admission 的 E1 证据。

它不等于：

~~~text
ROUND4_MODEL_APPLICATION_VALIDATED
~~~

后者当前不成立。

## 20. Round 5

如果 Round 4 成功，Round 5 才进入：

~~~text
真实 model consumer
→ Gateway admission
→ ModelQueue
→ APPLIED
→ CONSUMED
→ 模型状态变化
→ E2 / E3 evidence
~~~

届时 implemented_message_ids 是否包含 ID7，应由真实 consumer 能力决定，而不是为了测试改出来。

## 21. 当前推荐结论

Round 4 推荐：

~~~text
真实 Session
+
单次 current-session PCAP
+
3.6 Gateway Admission
+
RECEIVED → FAILED/TARGET_MISSING
~~~

而不是：

~~~text
假装 ID7 已实现
+
强行让 SourceSession authorize
+
伪造 production replay success
~~~

这是当前代码能力边界下最严格、最可解释、风险最小的下一步。
