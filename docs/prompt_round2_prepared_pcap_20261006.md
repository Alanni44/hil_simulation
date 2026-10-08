# Round 2 Prompt：从 reference.pcap 生成 prepared.pcap 并完成 tcpreplay 命令离线闭环

你现在继续无人机仿真平台 3.3 → 3.6 输入模拟器中 **HISTORY / PCAP Replay** 工作线。

项目根目录：

```text
E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006
```

Round 1 已完成，并已冻结以下软件级 reference 产物：

```text
artifacts/history/round1/reference.pcap
artifacts/history/round1/reference_manifest.json
artifacts/history/round1/round1_validation.json
docs/HISTORY_PCAP_Round1_Reference_PCAP_Report_20261006.md
```

Round 1 已确认：

- reference.pcap 使用冻结 v0.3 ICD；
- 业务 UDP bytes 来自正式 `WireCodec`；
- PCAP 为 ETH_0 / TO_36；
- `CaptureParser → HistoryDecoder → ReplayProcessor` round-trip 已通过；
- `PreparedReplay` 非空；
- `execution_ready=false`；
- 未执行真实网络发送、tcpreplay、Linux qualification、模型 APPLIED/CONSUMED。

本轮目标严格限定为：

> **从 Round 1 的落盘 reference.pcap 出发，完成 ReplayProcessor → ReplayExporter → prepared.pcap → tcpreplay command 的纯离线闭环。**

本轮不真正执行 tcpreplay。

---

## 1. Research First

施工前先阅读并核对现有实现，优先复用，不新增第二套逻辑：

```text
docs/HISTORY_PCAP_Round1_Reference_PCAP_Report_20261006.md

input_simulator/replay.py
input_simulator/replay_export.py
input_simulator/tool_commands.py
input_simulator/replay_process.py
input_simulator/history.py
input_simulator/capture.py
input_simulator/reference_pcap.py

icd_runtime/wire.py
icd_runtime/contract.py

tests/icd_gateway/test_replay.py
tests/icd_gateway/test_replay_export.py
tests/icd_gateway/test_tool_commands.py
tests/icd_gateway/test_replay_process.py
tests/icd_gateway/test_reference_pcap.py
```

重点确认：

1. `ReplayProcessor.prepare` 的正式输入；
2. `SESSION_REBUILD / REENCODE / RAW_VALIDATED` 三种 mode 的限制；
3. `ReplayExporter.export` 所需 `ExportBinding`；
4. `ReplayExporter` 导出 PCAP 后自身如何 reparse/校验；
5. `ToolCommandBuilder.replay` 对 tcpreplay 参数的约束；
6. 当前项目规定 ONLINE / OFFLINE replay rate；
7. 当前 reference.pcap 的单条 ID 7 TO_36 记录最适合使用哪种 replay mode。

如果发现 Round 1 的 `REENCODE` 不是当前 Round 2 最合理模式，可以调整 Round 2 的准备方式，但不得修改 Round 1 reference 文件。

---

## 2. 环境

继续使用 Round 1 已建立的 conda Python 3.12 环境：

```text
E:\GuoZhao\Desktop\UAVDemo\.conda-envs\uav-history-pcap
```

优先使用：

```powershell
conda run --no-capture-output -p E:\GuoZhao\Desktop\UAVDemo\.conda-envs\uav-history-pcap ...
```

不要新建另一套 Python 环境，除非该环境损坏且有明确证据。

依赖仍以 `requirements-icd.txt` 为 Source of Truth。

---

## 3. 本轮强约束

### 3.1 不修改 Round 1 reference

禁止修改：

```text
artifacts/history/round1/reference.pcap
artifacts/history/round1/reference_manifest.json
artifacts/history/round1/round1_validation.json
```

Round 1 产物是本轮输入基线。

### 3.2 不执行 tcpreplay

本轮可以：

- 生成 tcpreplay argv；
- 校验 argv；
- 校验 prepared.pcap；
- 保存 manifest/report。

本轮禁止：

- 真正调用 tcpreplay；
- 向物理/虚拟网卡发送 prepared.pcap；
- 修改 NIC/IP/MAC；
- 使用 raw socket 发包；
- Linux qualification；
- 模型 APPLIED/CONSUMED。

### 3.3 不把“命令已生成”写成“Replay 已执行”

严格区分：

```text
PREPARED
EXPORTED
COMMAND_BUILT
PROCESS_STARTED
TRANSMITTED
RECEIVED
APPLIED
CONSUMED
```

本轮最多证明前三项。

---

# 4. Round 2 目标链

完整目标：

```text
Round 1 reference.pcap
        ↓
CaptureParser
        ↓
HistoryDecoder
        ↓
ReplayProcessor
        ↓
PreparedReplay
        ↓
ReplayExporter
        ↓
prepared.pcap
        ↓
reparse / verify
        ↓
ToolCommandBuilder.replay
        ↓
tcpreplay argv
```

成功标准：

1. prepared.pcap 真正落盘；
2. prepared.pcap 可被项目现有 CaptureParser 重新读取；
3. 导出的 HIL1 UDP bytes 与 PreparedReplay 中的 wire_data 一致；
4. session/header/CRC 修改符合选定 replay mode；
5. tcpreplay command 由现有 ToolCommandBuilder 生成；
6. 不实际运行 tcpreplay；
7. 所有 execution/qualification 状态保持诚实。


---

# 5. Replay Mode 选择

必须根据源码和当前 reference.pcap 实际条件选择 mode，不要凭喜好。

当前 reference.pcap：

```text
message_id = 7
direction = TO_36
channel = ETH_0
captured session_id = 1
single packet
synthetic_reference = true
actual_network_tx = false
```

请比较：

### RAW_VALIDATED

仅在所有严格条件真实满足时使用：

- captured session 仍然是当前有效 session；
- sequence 新鲜；
- target_step 合法；
- endpoint 不需要改；
- repeat_count=1；
- 原始 CRC/bytes 原样有效。

对于 Round 1 synthetic captured session，预计通常不适合作为可重用 replay mode；必须以源码规则确认。

### REENCODE

使用原业务 stimulus + 新 Header 重新走正式 `WireCodec`。

优点：

- 适合 synthetic reference；
- 不依赖旧 session；
- 可显式分配新的 session/sequence/target_step/transaction。

### SESSION_REBUILD

保留历史业务 payload/wire 语义，仅按允许字段重写：

- session_id
- sequence
- target_step
- transaction_id
- endpoint
- CRC

如果当前 replay policy / history fixture 允许，需评估它是否比 REENCODE 更符合“历史原片 → 新会话可播放成片”的语义。

最终只选一个 V1 mode，并在报告中解释原因。

---

# 6. Header Allocation

如果 mode 不是 RAW_VALIDATED，必须显式分配新的 Header。

要求：

- session_id 非 0；
- 不复用 captured session；
- sequence 严格递增；
- transaction_id 不与 captured transaction 非法合并；
- target_step 满足正式 Header schema；
- valid_for_ms 不能擅自改协议值；
- 不允许通过降低校验来接受非法 Header。

本轮不声称该 session 来自真实在线 `SessionOpen`。

所以 manifest/report 必须明确：

> Round 2 header allocation 是离线 replay preparation fixture，不是已授权在线 session。

---

# 7. Export Binding

使用正式 ETH_0 输出通道。

优先复用项目已有 deterministic software MAC：

```text
source MAC       02:00:00:00:00:01
destination MAC  02:00:00:00:00:02
```

并保持冻结 ETH_0：

```text
10.36.0.10:36102
→
10.36.0.20:36100
```

如果 `ReplayExporter` 要求 interface 名：

- 只提供一个明确的逻辑/目标 interface 字符串；
- 不打开真实网卡；
- 不验证网卡存在；
- 不把它解释成 qualification。

建议：

```text
interface = eth0
```

但如果现有测试/设计已有更权威约定，以源码为准。

---

# 8. prepared.pcap 产物

优先输出：

```text
artifacts/history/round2/
  prepared.pcap
  prepared_manifest.json
  round2_validation.json
  tcpreplay_command.json
```

如果 ReplayExporter 默认输出名为 `ETH_0.pcap`，可以保留内部原名，但最终 artifact 应有一个明确的 prepared 语义名称，避免与 Round 1 reference 混淆。

不要覆盖任何已有目录。

---

# 9. prepared_manifest.json

至少记录：

- source_reference_pcap_sha256；
- baseline_version；
- baseline_sha256；
- replay_mode；
- replay_policy_sha256；
- input_message_id；
- input_channel；
- output_channel；
- original header；
- allocated/rebuilt header；
- changed_fields；
- source/destination endpoint；
- MAC；
- packet_count；
- prepared PCAP SHA256；
- 每帧 SHA256；
- UDP payload SHA256；
- relative offsets；
- rate；
- repeat_index；
- repeat_count；
- synthetic_reference=true；
- offline_prepared=true；
- actual_network_tx=false；
- process_started=false；
- received=false；
- applied=false；
- consumed=false；
- execution_ready=false。

不要隐藏 session/header 被重写的事实。

---

# 10. ReplayExporter 验证

调用现有：

```text
ReplayExporter.export(...)
```

不要重新写另一套 exporter。

必须验证：

1. 输出为 PCAP；
2. linktype 正确；
3. 完整 Ethernet Frame；
4. timestamp 保留/转换符合现有逻辑；
5. endpoint 与 binding 一致；
6. HIL UDP payload 可由 `WireCodec.decode` 解码；
7. Header 等于 PreparedReplay 分配结果；
8. CRC 正确；
9. payload 业务语义不被非法修改；
10. exporter 自己的 reparse 校验通过。

---

# 11. ToolCommandBuilder

使用现有：

```text
input_simulator/tool_commands.py
```

生成 tcpreplay 命令。

不要直接自己拼：

```text
tcpreplay ...
```

必须通过正式 Builder，确保：

- executable；
- interface；
- one-shot/repeat；
- rate；
- 文件路径；
- 禁止任意 extra argv；
- 不绕过项目已有安全限制。

最终保存实际 Builder 生成的 argv。

---

# 12. tcpreplay command 的安全边界

本轮只验证：

```text
prepared.pcap
→ ToolCommandBuilder
→ argv
```

不能：

- Popen；
- ProcessSupervisor.start；
- ReplayProcessRun.start；
- shell execute；
- subprocess.run；
- os.system；
- 真正寻找/启动 tcpreplay。

即使系统安装了 tcpreplay，也不执行。

报告中必须写：

```text
command_built = true
process_started = false
actual_network_tx = false
```

---

# 13. Tests

新增最小必要测试。

至少覆盖：

1. Round 1 reference.pcap hash 不变；
2. reference.pcap 能被现有 HistoryDecoder 重新读取；
3. ReplayProcessor 得到 PreparedReplay；
4. chosen replay mode 正确；
5. rebuilt/allocated Header 符合预期；
6. prepared.pcap 能被 CaptureParser 重新读取；
7. prepared UDP bytes 与 PreparedReplay wire_data 一致；
8. prepared payload 业务语义与 reference 相同；
9. changed_fields 与实际变化一致；
10. prepared PCAP hash 与 manifest 一致；
11. ToolCommandBuilder 输出稳定；
12. command 只引用 Round 2 prepared.pcap；
13. process_started=false；
14. 不允许 Round 1 reference 被覆盖；
15. 不允许通过 loopback endpoint 绕过冻结 profile。

优先沿用现有 unittest 风格。


---

# 14. 回归验证

实施前先记录聚焦基线。

实施后至少运行：

```text
tests/icd_gateway/test_reference_pcap.py
tests/icd_gateway/test_history.py
tests/icd_gateway/test_replay.py
tests/icd_gateway/test_replay_export.py
tests/icd_gateway/test_tool_commands.py
tests/icd_gateway/test_replay_process.py
```

以及：

```powershell
python -X utf8 scripts/test_icd_runtime.py
```

已知 Round 1 后完整脚本存在基线：

```text
1 failure
3 errors
```

本轮不要顺手修这些与 HISTORY Round 2 无直接关系的问题。

验收标准：

> 修改后不得出现新的 failure/error；已知基线问题应保持可识别、可对比。

---

# 15. Review After Implementation

独立审查：

## correctness

- prepared.pcap 是否来自现有 ReplayProcessor + ReplayExporter；
- Header 是否按 mode 合法变化；
- payload 是否保持业务语义；
- CRC 是否由正式实现产生；
- command 是否引用正确的 prepared 文件。

## regression

- Round 1 reference 是否完全未变；
- 现有 replay/export/tool command 测试是否仍通过；
- baseline failure/error 是否没有增加。

## security / safety

- 是否意外执行 subprocess；
- 是否访问真实 interface；
- 是否修改本机网络；
- 是否调用 tcpreplay；
- 是否产生真实网络 TX。

## maintainability

- 是否重复实现 ReplayExporter；
- 是否重复实现 ToolCommandBuilder；
- 是否把 Round 2 fixture 逻辑侵入正式 runtime。

---

# 16. 报告

生成：

```text
docs/HISTORY_PCAP_Round2_Prepared_PCAP_Report_20261006.md
```

至少包括：

## 1. Executive Summary

说明：

- prepared.pcap 是否成功；
- Replay mode；
- tcpreplay command 是否成功构建；
- 是否启动进程；
- 是否发送网络。

## 2. Input Baseline

- Round 1 PCAP path；
- Round 1 SHA256；
- baseline SHA256。

## 3. Replay Preparation

- History decode；
- selected records；
- mode；
- original Header；
- allocated Header；
- changed_fields。

## 4. Replay Export

- output file；
- endpoint；
- MAC；
- packet count；
- timestamp；
- SHA256。

## 5. Command Build

记录 Builder 实际生成的 argv。

## 6. Validation Chain

```text
reference.pcap
→ CaptureParser
→ HistoryDecoder
→ ReplayProcessor
→ PreparedReplay
→ ReplayExporter
→ prepared.pcap
→ CaptureParser/WireCodec
→ ToolCommandBuilder
→ tcpreplay argv
```

## 7. Test Results

真实命令和结果。

## 8. Review Findings

correctness / regression / safety / maintainability。

## 9. Remaining Gates

明确：

- tcpreplay process 未启动；
- actual network TX 未发生；
- Linux qualification 未验证；
- 3.6 Receiver 未参与；
- SessionOpen/Heartbeat 在线协同未验证；
- APPLIED/CONSUMED 未验证；
- 真实 3.3/HIL 未验证。

## 10. Recommended Round 3

只提出下一阶段，不提前实施。

推荐方向应围绕：

> 在受控 Linux / 隔离网络环境中实际运行 tcpreplay，并先验证 TX/RX 网络层事实，不直接跳到模型 APPLIED。

---

# 17. Definition of Done

只有全部满足才可标记 Round 2 完成：

- [ ] Round 1 reference.pcap 未修改；
- [ ] 从实际 Round 1 落盘 PCAP 开始处理；
- [ ] 使用现有 HistoryDecoder；
- [ ] 使用现有 ReplayProcessor；
- [ ] 选择并解释 replay mode；
- [ ] Header allocation/rewrite 合法；
- [ ] 使用现有 ReplayExporter；
- [ ] prepared.pcap 成功落盘；
- [ ] prepared.pcap 可被 CaptureParser/WireCodec 重读；
- [ ] prepared payload 业务语义正确；
- [ ] prepared.pcap SHA256 与 manifest 一致；
- [ ] 使用现有 ToolCommandBuilder；
- [ ] tcpreplay argv 成功生成；
- [ ] 未执行 tcpreplay；
- [ ] process_started=false；
- [ ] actual_network_tx=false；
- [ ] execution_ready=false；
- [ ] 新增测试通过；
- [ ] 无新增回归；
- [ ] 生成 Round 2 实施报告。

如果关键项受阻：

- 保留已正确完成的结果；
- 明确记录阻塞；
- 不通过放宽 ICD、跳过校验、执行真实发送来强行完成。

---

## 最终原则

Round 1 证明：

> **我们能制造并理解一份正式格式的历史原片。**

Round 2 要证明：

> **我们能把这份历史原片，严格按照现有 Replay 规则加工成 tcpreplay 可消费的 prepared PCAP，并生成受控命令，但仍不真正播放。**

不要把 Round 2 扩成在线 Replay 或模型验证。
