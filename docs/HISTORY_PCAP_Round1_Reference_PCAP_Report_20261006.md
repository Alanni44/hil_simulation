# HISTORY PCAP Round 1 实施报告

日期：2026-10-06  
范围：首份软件级 reference PCAP bootstrap，以及正式 HISTORY / Replay 离线闭环。

## 1. Executive Summary

已从冻结 v0.3 示例构造一条 UDP `TO_36` 软件参考帧，写入 `artifacts/history/round1/reference.pcap`，并让正式 `CaptureParser → WireCodec/Reassembler → HistoryDecoder → ReplayProcessor` 从落盘文件重新解析、解码和准备回放。`PreparedReplay` 非空，且 `execution_ready=false`。

本轮未执行网络发送、tcpreplay、模型 Consumer 或真实飞行/HIL 验证。`TRANSMITTED / RECEIVED / APPLIED / CONSUMED` 均为 false。官方完整回归命令以失败结束，但失败数和具体失败与实施前基线相同；新增及相关聚焦测试通过。

## 2. Environment

- Conda 独立环境：`E:\GuoZhao\Desktop\UAVDemo\.conda-envs\uav-history-pcap`；Python 3.12.15。
- 依赖 Source of Truth：`requirements-icd.txt`。使用 `python -m pip install -r requirements-icd.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` 安装成功，没有改全局 conda 配置。
- 环境中的关键包版本包括 `jsonschema 4.26.0`、`cantools 40.7.1`、`python-can 4.6.1`、`scapy 2.7.0`；完整解析结果由该环境的 `pip freeze` 确认。
- PCAP 和报告均位于交接包目录。该交接目录没有 Git 元数据，因此不能提供该子目录的 Git diff；以文件清单和冻结 baseline SHA 作为核对证据。

## 3. Implementation

- `input_simulator/reference_pcap.py`：增加薄 reference bootstrap。使用正式 `Contract`、`PayloadCodec`、`WireCodec` 验证并编码消息；只负责确定性 Ethernet/IPv4/UDP 封装、nano-PCAP 持久化、manifest 和生产解析链 round-trip。未调用 socket、Scapy send 或 ReplayExporter。
- `scripts/generate_reference_pcap.py`：可重复调用的生成入口；默认写到 Round 1 artifact 目录，存在目标目录时拒绝覆盖。
- `tests/icd_gateway/test_reference_pcap.py`：覆盖确定性、解析器/原始帧和 WireCodec 一致性、冻结端点、History/Replay 闭环、落盘哈希、loopback 拒绝及坏输入失败。
- 生成物：`artifacts/history/round1/reference.pcap`、`reference_manifest.json`、`round1_validation.json`。
- 冻结 v0.3 baseline 未修改；HIL1 header、CRC、Payload 和 UDP 分片均由正式 WireCodec 处理，没有新增业务 Encoder。ScapySource、ReplayExporter 未改。

## 4. Selected Reference Message

- `message_id=7`，`TO_36`，UDP，来自冻结 `examples` 中的既有合法样例；生成前经 `Contract.validate_message` 验证。
- Payload：`{"motor_command":[0.1,0.2,0.3,0.4]}`。样例为单分片，降低首次 bootstrap 的复杂度，同时保持完整业务组。
- Header：捕获消息 `session_id=1, sequence=7, target_step=1000, transaction_id=7, valid_for_ms=100`。不是 SessionOpen。
- History 绑定明确将该记录作为 TO_36；Replay 使用 `REENCODE` 和显式新 Header `session_id=91, sequence=101, target_step=200, transaction_id=301, valid_for_ms=100`，未复用捕获 session。Replay window 选取该 TO_36 业务记录。

## 5. reference.pcap Metadata

- Profile：`ETH_0`，Ethernet / IPv4 / UDP，无 VLAN；`10.36.0.10:36102 → 10.36.0.20:36100`。
- MAC：`02:00:00:00:00:01 → 02:00:00:00:00:02`。这是确定性软件参考 L2 identity，不代表实际部署硬件 MAC。
- Linktype 1，1 帧 / 1 个逻辑消息；software reference fixture epoch `1760000000` Unix 秒，帧相对偏移 0 ns（PCAP timestamp `1760000000000000000` ns），不是实际抓包时间。
- PCAP SHA256：`c335601a095d9baf1c093bfd195f042b5e7899c31b03071f249f26488819efb3`。
- 帧 SHA256：`3fbc31052e4a388ba84db61f003d7082e73576f5c7c844b30f1fd68072a08f1a`；UDP payload SHA256：`da27493fcd5ebf77603a9f58c062462d18b68758f1879f0d6ea27badcb447479`。
- 冻结 baseline SHA256：`22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27`。
- Manifest 明确记录 `synthetic_reference=true`、`actual_network_tx=false`、`model_applied=false`、`execution_ready=false`。

## 6. Validation Chain

```text
Frozen validated BusinessMessage
→ WireCodec
→ Ethernet / IPv4 / UDP frame
→ reference.pcap
→ CaptureParser
→ WireCodec / Reassembler
→ HistoryDecoder
→ ReplayProcessor
→ PreparedReplay
```

最终落盘文件由生成入口重新读回验证；`round1_validation.json` 记录各阶段证据：

- `GENERATED`：成功；WireCodec HIL1 UDP bytes 封装成 1 个以太网帧。
- `PARSED`：成功；CaptureParser 识别 PCAP/linktype 1、1 帧、时间戳、MAC/IP/UDP 端点、UDP payload 和无 VLAN 状态。
- `WIRE_DECODED`：成功；`HIL1`、ID 7、`TO_36`、header、fragment 0/1、CRC 均通过；解出的 payload hash 与业务数据相符。
- `DECODED`：成功；HistoryDecoder 识别 `ETH_0 / TO_36` 并还原预期业务消息。
- `PREPARED`：成功；ReplayProcessor `REENCODE` 产出 1 个 packet，所选方向只有 `TO_36`，`execution_ready=false`。
- `TRANSMITTED / RECEIVED / APPLIED / CONSUMED`：未发生，均为 false。

## 7. Test Results

执行环境均为上述 Conda Python 3.12.15。

| 验证 | 命令/范围 | 结果 |
|---|---|---|
| 修改前官方全套基线 | `python -X utf8 scripts/test_icd_runtime.py` | 986 tests；1 failure、3 errors |
| 修改前聚焦基线 | capture/history/replay/replay_export/scapy_source | 120 tests passed |
| 修改前 runtime 子集 | `tests/icd_runtime` | 67 tests passed |
| 本轮新增测试 | `tests/icd_gateway/test_reference_pcap.py` | 6 tests passed |
| 本轮聚焦回归 | capture/history/replay/replay_export/scapy_source/reference_pcap | 126 tests passed |
| 修改后官方全套 | `conda run --no-capture-output -p E:\GuoZhao\Desktop\UAVDemo\.conda-envs\uav-history-pcap python -X utf8 scripts/test_icd_runtime.py` | 992 tests；与基线相同的 1 failure、3 errors；exit code 1 |
| 修改后 runtime | 官方脚本中的 runtime 子集 | 67 tests passed |
| 最终文件哈希 | `Get-FileHash -Algorithm SHA256 reference.pcap` | 与 manifest 完全一致：`c335601a095d9baf1c093bfd195f042b5e7899c31b03071f249f26488819efb3` |

全套基线/最终失败均为：

1. `test_existing_six_motor_declaration_is_not_full_v03_qualification`：交接包缺少 `artifacts/generic_models/multirotor_6/hil_contract.json`。
2. `test_all_header_mutations_reframe_every_fragment_and_keep_payload` 的 UDP、CANFD `SEQUENCE_OVERRIDE` 子用例：sequence 最小值被冻结 schema 拒绝。
3. `test_no_op_and_unknown_field_overwrite_are_not_negative_evidence`：预期 `ICDError` 未抛出。

这些失败在施工前基线已存在；本轮没有改动其测试或相关协议逻辑。完整命令非零，因此不能宣称全套回归全绿。

## 8. Review Findings

- **Correctness**：帧是 Ethernet/IPv4/UDP；UDP bytes 来自 WireCodec。CaptureParser 从最终文件重读，WireCodec 校验 CRC，HistoryDecoder 与 ReplayProcessor 均基于该解析结果执行。
- **Regression**：新增及相关聚焦测试通过；全套的 4 项既有问题在修改前后保持一致。未修改 WireCodec、ScapySource、ReplayExporter 或冻结 baseline。
- **Security / safety**：生成路径没有网络 socket/TX 操作，没有打开 raw interface，也没有改网络配置；只写软件参考样本和 JSON 元数据。未记录秘密或个人信息。
- **Maintainability**：新增实现仅承担 bootstrap、帧封装和确定性 PCAP 写入；不复制协议编码或 Replay 验证。输出采用独立目录并拒绝静默覆盖。

## 9. Remaining Gates

- 未执行 tcpreplay/canplayer、Linux qualification 或真实网络 TX。
- 未验证 APPLIED / CONSUMED；模型 Consumer 仍不在本轮范围。
- 未连接真实 3.3、真实 HIL 或物理设备。
- 完整测试脚本仍有与基线一致的 1 failure、3 errors，后续应在补齐交接包资料并处理既有问题后再争取全绿。

## 10. Recommended Round 2

在保持 Round 1 产物与冻结接口不变的前提下，可先审查并补齐缺失的六旋翼 HIL qualification contract，另行修复/澄清 sequence-negative 测试边界与未知字段覆盖语义；随后重新运行完整脚本。在线回放、Linux/raw-socket 和模型 Consumer qualification 应另开明确边界的阶段，不由本轮 reference PCAP 推定通过。
