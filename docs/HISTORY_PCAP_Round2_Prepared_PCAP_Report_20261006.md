# HISTORY PCAP Round 2：Prepared PCAP 实施报告

日期：2026-10-06  
范围：从 Round 1 落盘 `reference.pcap` 出发，使用现有 HISTORY 解码、ReplayProcessor、ReplayExporter 和 ToolCommandBuilder，生成离线 `prepared.pcap` 与 tcpreplay argv。没有启动回放进程。

## 1. Executive Summary

- `artifacts/history/round2/prepared.pcap` 已生成并通过 CaptureParser/WireCodec 重读。
- V1 replay mode：`REENCODE`。Header 由离线 fixture 显式分配；正式业务 bytes 和 CRC 由 WireCodec 生成。
- `ToolCommandBuilder` 已生成 tcpreplay argv，命令资源 SHA256 与 `prepared.pcap` 一致。
- `command_built=true`；`process_started=false`；`actual_network_tx=false`；`execution_ready=false`。
- 六个指定测试模块 110 项通过；新增 Round 2 端到端测试 2 项通过。完整脚本 995 项中有 1 failure、3 errors，与 Round 1 已记录的同四个基线问题相同，没有新增回归。

## 2. Input Baseline

- Round 1 PCAP：`artifacts/history/round1/reference.pcap`
- Round 1 SHA256：`c335601a095d9baf1c093bfd195f042b5e7899c31b03071f249f26488819efb3`
- Baseline：`HIL-ICD-1.0`，SHA256 `22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27`
- Round 1 `reference_manifest.json` 声明 `synthetic_reference=true`。施工前与施工后重新计算的 reference PCAP SHA256 均为上述值；没有覆盖 Round 1 三个冻结文件。

## 3. Replay Preparation

`HistoryDecoder` 从实际落盘 PCAP 读取一条 `ETH_0 / TO_36 / message_id=7` 记录，业务 payload 为 `motor_command=[0.1,0.2,0.3,0.4]`。

选用 `REENCODE` 的依据：

- `RAW_VALIDATED` 不适用：捕获 session `1` 来自 synthetic reference，没有在线 SessionOpen、当前 session 有效性和新鲜 sequence 证明；此模式也不接受 Header 分配。
- `SESSION_REBUILD` 不适用当前 history fixture：Round 1 policy 为 `REENCODE`，`rewrite_fields=[]`。切换到 SESSION_REBUILD 并授权 Header/CRC 字段将改变本轮 policy 语义；当前 fixture 不允许这些改写。
- `REENCODE` 符合 synthetic reference 的用途：复用解码得到的业务 stimulus，使用新 Header 通过正式 `WireCodec` 重编码，并校验原业务 payload 语义保持不变。

Header：

| 字段 | 捕获 Header | Round 2 分配 Header |
|---|---:|---:|
| `session_id` | 1 | 92 |
| `sequence` | 7 | 102 |
| `target_step` | 1000 | 201 |
| `transaction_id` | 7 | 302 |
| `valid_for_ms` | 100 | 100 |

`changed_fields` 与 ReplayProcessor 实际证据一致：`SESSION`、`SEQUENCE`、`TARGET_STEP`、`TRANSACTION`、`CRC`。session 92 是离线 replay preparation fixture，不代表在线获批 SessionOpen。History policy 为 `OFFLINE / 1X`、`repeat_count=1`；冻结规则为 ONLINE 固定 1X，0.5X/2X/4X 只用于 OFFLINE。

## 4. Replay Export

- 文件：`artifacts/history/round2/prepared.pcap`
- ReplayExporter：`ETH_0`，Ethernet PCAP，linktype 1，1 帧。
- Endpoint：`10.36.0.10:36102 → 10.36.0.20:36100`。
- MAC：`02:00:00:00:00:01 → 02:00:00:00:00:02`。Exporter 保留 Round 1 原帧的 L2 identity；它拒绝对已有 Ethernet 帧再次覆盖 MAC。
- PCAP SHA256：`febbf0e10c98b3d4adafa7dcb5027e0e6b0f212b6828a779f404d51ddf172134`
- 帧 SHA256：`b5c0811f436742860216a520042c429b0360e39d8028071af05ea8cea76217cb`
- HIL1 UDP payload SHA256：`a77ecc03dbc44e35f354c739dbe0831d8ed75419663f178c39af3f1ee0a2a1c3`
- 相对偏移为 0 ns。ToolCommandBuilder 通过现有 Exporter 以 `epoch_ns=0` 输出，相应 PCAP 时间戳为 0 ns；它保留/映射相对时间，不声称这是实测时间。
- Exporter 的内部重读校验通过；脚本又从持久化文件重读，验证 PCAP、Ethernet/UDP endpoint、WireCodec CRC、Header、payload 语义及哈希。

## 5. Command Build

保存于 `artifacts/history/round2/tcpreplay_command.json` 的 Builder 原始 argv：

```text
tcpreplay --intf1=eth0 --loop=1 --multiplier=1.0 E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006\artifacts\history\round2\prepared.pcap
```

argv 由 `ToolCommandBuilder.replay` 生成，`resource_sha256` 指向 `prepared.pcap`。Builder 使用本地 ChannelReservations 结构校验参数；该 reservation 不是发送授权。实现没有调用 Popen、ProcessSupervisor、ReplayProcessRun、shell 或 subprocess，也没有启动/探测 tcpreplay 可执行文件。

## 6. Validation Chain

```text
Round 1 reference.pcap
→ CaptureParser / HistoryDecoder
→ ReplayProcessor (REENCODE)
→ PreparedReplay
→ ReplayExporter
→ prepared.pcap
→ CaptureParser / WireCodec decode and payload check
→ ToolCommandBuilder
→ tcpreplay argv
```

`round2_validation.json` 记录各阶段 PASS；`prepared_manifest.json` 包含输入与输出哈希、baseline/policy 哈希、Header 前后值、实际变化字段、endpoint/MAC、帧哈希、相对偏移、rate/repeat 和全部 execution 状态。Exporter 同时保留其原生 `manifest.json` 与同内容的 `manifest.pending.json` 硬链接。

## 7. Test Results

环境：Round 1 已建立的 Conda Python 3.12 环境 `E:\GuoZhao\Desktop\UAVDemo\.conda-envs\uav-history-pcap`；未创建新环境。

| 验证 | 结果 |
|---|---:|
| 修改前六个聚焦模块基线 | 109 tests passed |
| 修改后 `test_reference_pcap.py` | 6 passed |
| 修改后 `test_history.py` | 23 passed |
| 修改后 `test_replay.py` | 26 passed |
| 修改后 `test_replay_export.py` | 20 passed |
| 修改后 `test_tool_commands.py` | 17 passed |
| 修改后 `test_replay_process.py` | 18 passed |
| 新增 `test_round2_prepared_pcap.py` | 2 passed |
| 官方完整脚本 `python -X utf8 scripts/test_icd_runtime.py` | 995 tests；1 failure、3 errors；与 Round 1 报告记录的同四个问题一致 |

完整脚本的既有问题：缺少 `artifacts/generic_models/multirotor_6/hil_contract.json`；UDP 与 CANFD 的 `SEQUENCE_OVERRIDE` 两个子用例被冻结 Header 最小值校验拒绝；`test_no_op_and_unknown_field_overwrite_are_not_negative_evidence` 预期异常未抛出。Round 1 已记录完整基线为 992 tests、同样 1 failure/3 errors；本轮多出的 3 项是本轮新增测试。

## 8. Review Findings

- **Correctness**：实际 Round 1 文件进入 HistoryDecoder 和 ReplayProcessor；导出经 ReplayExporter 完成；HIL1 ID 7、TO_36、分配 Header、CRC 与原业务 payload 均通过重读校验。ToolCommandBuilder 的资源哈希匹配 PCAP。
- **Regression**：六个指定模块全绿；三项新增测试全绿；完整脚本失败/错误的名称和类别与 Round 1 基线一致。Round 1 PCAP SHA256 未变。
- **Safety**：未调用 tcpreplay、未启动进程、未访问/修改网卡或本机网络、未产生真实 TX；`actual_network_tx=false`。没有 APPLIED/CONSUMED 证据。
- **Maintainability**：复用了 HistoryDecoder、ReplayProcessor、ReplayExporter、ToolCommandBuilder 和 WireCodec。ReplayExporter 仅新增受限可选 `output_name`，默认命名行为不变；Round 2 业务准备逻辑封装在离线脚本，没有侵入 runtime replay 处理器。
- 交接目录没有 Git 元数据，因此变更审查以文件列表、内容、SHA256 和测试结果为依据。

## 9. Remaining Gates

- tcpreplay process 未启动；actual network TX 未发生。
- Linux qualification 未验证；3.6 Receiver 未参与。
- SessionOpen/Heartbeat 在线协同未验证；APPLIED/CONSUMED 未验证。
- 真实 3.3/HIL 和物理链路未验证。
- 完整脚本仍保留已知的 1 failure、3 errors；本轮没有扩展范围去修复它们。

## 10. Recommended Round 3

在隔离且受控的 Linux 网络环境中，先审核目标 interface、端点和操作授权，再启动 tcpreplay 并独立确认 TX/RX 网络层事实；完成后再决定是否接入 3.6 Receiver。不要从命令构建或 TX/RX 推断模型 APPLIED。
