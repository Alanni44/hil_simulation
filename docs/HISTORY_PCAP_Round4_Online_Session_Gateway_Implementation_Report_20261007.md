# HISTORY PCAP Round 4：在线 Session + 3.6 Gateway Admission 实施报告

日期：2026-10-07  
最终状态：**PASS — ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED**  
环境资格：**WSL2_SOFTWARE_ONLY**；不代表目标麒麟系统 qualification。  
最终证据：[`artifacts/history/round4/retry_4/round4_validation.json`](../artifacts/history/round4/retry_4/round4_validation.json)

## 1. Executive Summary

Round 4 已按[设计文档](HISTORY_PCAP_Round4_Online_Session_Gateway_Design_20261007.md)完成。最终有效尝试为 `retry_4`，在 WSL2 隔离的 Linux network namespace + veth 环境中完成真实在线 Session 建立、当前 Session PCAP 重建、一次性 `tcpreplay` 发送，以及 3.6 UDPGateway / Receiver 的 admission 验证。

实测链路：

```text
SessionOpen
→ SessionOpened(real session_id = 2017155087)
→ current-session online PCAP
→ tcpreplay（1 packet，114 bytes，exit 0）
→ 3.6 UDPGateway / Receiver
→ Ack(RECEIVED, OK)
→ Ack(FAILED, TARGET_MISSING)
```

两条 ACK 均与当前请求的 session、transaction、sequence 和 message ID 关联。第一条确认 Receiver 已接收请求；第二条符合当前没有 ID7 model consumer 的能力边界。

本轮证明范围是 **3.6 Gateway / Receiver admission**。`SessionOpened` 实际公布的 `implemented_message_ids` 仍为 `[1]`；ID7 Header 被明确标记为 `Gateway Admission Probe Header`，并非 SourceSession capability 授权的 production header。`APPLIED`、`CONSUMED`、模型状态变化、真实 3.3/HIL 和目标麒麟 qualification 均未验证。

## 2. Attempt History

各次尝试及原始记录均保留在 [`artifacts/history/round4/round4_summary.json`](../artifacts/history/round4/round4_summary.json) 所指向的证据目录下；只有 `retry_4` 作为最终 PASS 证据。

### 2.1 首次尝试：启动前阻塞

根目录 `cleanup_status.json` 记录了首次尝试因脚本把 reference PCAP SHA 与 baseline SHA 混淆而在网络执行前停止。清理成功，宿主路由未改变；该次没有发送请求，不计为网络验收。

### 2.2 retry_1：SessionOpened 后证据采集脚本失败

Gateway 返回了真实 `SessionOpened`，但证据脚本尝试从 `UDPSource.records` 读取记录；该对象没有此属性，因此在 Session 证据落盘阶段报 `AttributeError`。这次没有发送 ID7。该失败是证据采集实现问题，不是 Gateway admission 结果。

### 2.3 retry_2：修正点不完整，仍在探测前失败

下一次运行在读取 `source.records[-1].completed_ns` 时遇到同一类 `AttributeError`。请求仍未进入 ID7 探测阶段。原始输出保留在 `retry_2/source_stderr.txt`。

### 2.4 retry_3：实际发送，但校验器拒绝部分 UDP checksum

该次已执行真实网络探测并捕获到请求，但项目 `CaptureParser` 因 WSL veth TX checksum offload 导致的部分 UDP checksum 报文，按规则返回 `RESOURCE: captured UDP checksum differs`。该证据被保留为失败尝试，未被改写为通过。

### 2.5 retry_4：最终通过

仅在临时隔离 namespace 的 veth 上关闭 TX checksum offload 后重新执行。最终请求与反馈 PCAP 的校验通过；宿主网卡和路由没有修改。验证结果见 [`retry_4/round4_validation.json`](../artifacts/history/round4/retry_4/round4_validation.json)。

## 3. Environment and Qualification

- Linux：Ubuntu 24.04.3 LTS，WSL2 kernel `6.6.87.2-microsoft-standard-WSL2`。
- Python：Conda 环境 `uav-history-round4`，Python 3.12.15。
- `tcpreplay`：4.4.4；`tcpdump`：4.99.4 / libpcap 1.10.4；iproute2：6.1.0；ethtool：6.7。
- 环境类别：`WSL2_SOFTWARE_ONLY`。
- 最终隔离 veth 的 TX checksum offload 已关闭；该设置用于解决 retry_3 的捕获校验问题。
- `target_kylin_qualified = false`。

环境原始记录见 [`retry_4/environment.json`](../artifacts/history/round4/retry_4/environment.json)、[`retry_4/source_ethtool_features.txt`](../artifacts/history/round4/retry_4/source_ethtool_features.txt) 和 [`retry_4/gateway_ethtool_features.txt`](../artifacts/history/round4/retry_4/gateway_ethtool_features.txt)。

## 4. Isolation Topology

最终网络执行发生在临时 Linux network namespace / veth 隔离拓扑中：

```text
source namespace                         gateway namespace
10.36.0.10/24                             10.36.0.20/24
source :36102                             UDPGateway :36100
feedback :36101       ←── veth pair ──→  Receiver / SessionRegistry
```

宿主路由前后记录一致，最终 cleanup 记录 `host_routes_changed = false`。该验收不使用 Windows 物理网卡，不表示接入外部网络或目标设备。

## 5. Input Integrity and Online PCAP

本轮从 Round 1 reference 输入重新准备在线 replay，没有复用 Round 2 的离线 Session fixture，也没有直接 patch PCAP bytes。

| 项目 | 最终证据 |
|---|---|
| Round 1 reference PCAP SHA256 | `c335601a095d9baf1c093bfd195f042b5e7899c31b03071f249f26488819efb3` |
| Baseline SHA256 | `22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27` |
| Online prepared PCAP SHA256 | `a28d0bbcea894b3f46a404f3baf31bd0fe23e5621c8f8c2be3c9e6e9e4c8ed0f` |
| Message / direction | ID `7` / `TO_36` |
| Replay mode | `REENCODE` |
| Payload | `motor_command = [0.1, 0.2, 0.3, 0.4]` |
| Session / sequence / transaction | `2017155087` / `2` / `2` |
| target_step / valid_for_ms | `201` / `100` |
| Header type | `Gateway Admission Probe Header` |

在线 PCAP manifest：[`retry_4/online_prepared_manifest.json`](../artifacts/history/round4/retry_4/online_prepared_manifest.json)。`target_step = 201` 仅用于 Gateway admission probe，不代表与真实模型步进对齐；`target_step_semantically_qualified = false`。

## 6. SessionOpen and Capability Boundary

真实 `SessionOpen` 使用 `CONTROLLER` role，收到非零 SID `2017155087`。Session lease 为 `1000 ms`。`SessionOpened` 返回的关键能力如下：

```text
accepted_roles = [CONTROLLER]
implemented_message_ids = [1]
replacement_ready = false
source_capability_authorized = false
```

因此 ID7 探测不是通过修改 Receiver capability 或绕过 `SourceSession` 授权得到的。本轮在隔离 DEVELOPMENT 配置下使用显式 admission-probe Header；不能据此声称当前 SourceSession 可以为 ID7 分配正式 production Header。

Session 原始请求 / 响应及进程信息见 [`retry_4/session_open.json`](../artifacts/history/round4/retry_4/session_open.json)。

## 7. Actual Execution and Gateway Feedback

实际 replay 命令参数：

```text
tcpreplay --intf1=eth0 --loop=1 --multiplier=1.0 online_prepared.pcap
```

记录的完整 argv 和时间数据见 [`retry_4/executed_tcpreplay_command.json`](../artifacts/history/round4/retry_4/executed_tcpreplay_command.json)。进程在 SessionOpened 后 `31,660,629 ns`（约 31.7 ms）启动，小于设计门限 500 ms。tcpreplay 发送 1 packet / 114 bytes，successful=1、failed=0，exit code `0`。

本轮抓获 2 个请求数据报（SessionOpen 与 ID7），以及 3 个 Gateway feedback 数据报（SessionOpened 与两条 ACK）。ACK 关联结果：

| ACK | session_id | ACK sequence | 请求 sequence / message ID | transaction_id | stage / error |
|---|---:|---:|---|---:|---|
| 1 | 2017155087 | 2 | 2 / 7 | 2 | `RECEIVED / OK` |
| 2 | 2017155087 | 3 | 2 / 7 | 2 | `FAILED / TARGET_MISSING` |

反馈 sequence 严格递增。持久化的协议解析与关联见 [`retry_4/gateway_feedback.json`](../artifacts/history/round4/retry_4/gateway_feedback.json)；请求与反馈原始抓包分别为 [`retry_4/request_tx.pcap`](../artifacts/history/round4/retry_4/request_tx.pcap) 和 [`retry_4/gateway_feedback.pcap`](../artifacts/history/round4/retry_4/gateway_feedback.pcap)。

## 8. Evidence Claims

| Claim | Round 4 |
|---|---|
| session_opened | **true** |
| real_session_id | **true** (`2017155087`) |
| online_pcap_prepared | **true** |
| process_started | **true** |
| actual_network_tx | **true** |
| received_by_3_6 | **true** |
| gateway_session_admitted | **true** |
| received_ack_observed | **true** (`RECEIVED / OK`) |
| failed_target_missing_observed | **true** (`FAILED / TARGET_MISSING`) |
| source_capability_authorized | **false** |
| applied | **false** |
| consumed | **false** |
| execution_ready | **false** |
| target_step_semantically_qualified | **false** |
| target_kylin_qualified | **false** |

最终汇总见 [`artifacts/history/round4/round4_summary.json`](../artifacts/history/round4/round4_summary.json)。

## 9. Cleanup

最终尝试 cleanup 状态为 PASS：

```text
cleanup_complete = true
host_routes_changed = false
failure = null
```

临时 namespace、veth、Gateway、tcpdump 和 tcpreplay 已清理；最终环境复查未见相关残留进程。清理记录见 [`retry_4/cleanup_status.json`](../artifacts/history/round4/retry_4/cleanup_status.json)。

## 10. Tests and Regression

### 10.1 Focused Validation

- Round 4 focused validator tests：**12 passed**。
- 最终证据验证：`ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED`。
- 验证器对 Session、online PCAP、网络计数、ACK 关联和 cleanup 均报告 PASS。
- `retry_4/validation_stdout.txt` 保存了最终验证输出。

### 10.2 Full Regression

完整 `scripts/test_icd_runtime.py` 回归共运行 1001 项，结果为 **1 failure、3 errors**。该失败集合与 Round 3 记录的既有基线一致，没有发现 Round 4 新增的 failure/error。既有问题包括缺少 generic model contract fixture、UDP/CANFD 的 `SEQUENCE_OVERRIDE` 被 Header minimum 校验拒绝，以及 unknown-field/no-op negative case 未抛出预期异常。Round 3 基线记录见 [`HISTORY_PCAP_Round3_Tcpreplay_Isolated_Linux_Report_20261006.md`](HISTORY_PCAP_Round3_Tcpreplay_Isolated_Linux_Report_20261006.md) 和 [`artifacts/history/round3/round3_validation.json`](../artifacts/history/round3/round3_validation.json)。

## 11. Review Findings

### Correctness

- SessionOpen / SessionOpened 通过真实 UDP 链路完成，SID 非零，role 为 CONTROLLER。
- 在线 PCAP 使用本次真实 SID，保留 ID7 payload 语义。
- tcpreplay 在 SessionOpened 后约 31.7 ms 启动并成功发送单个数据报。
- Gateway 返回并持久化与请求相关联的 `RECEIVED / OK` 和 `FAILED / TARGET_MISSING`。

### Boundary

- Receiver capability 仍为 `[1]`；SourceSession 对 ID7 的 capability 授权仍为 false。
- `RECEIVED` 证明 Gateway / Receiver admission，不等于模型消费或应用。
- 当前 Gateway 没有已验证的 ID7 model consumer；因此 `TARGET_MISSING` 是预期边界反馈。
- 本轮没有验证真实 3.3、真实 HIL、模型状态变化或麒麟目标环境。

### Safety and Cleanup

- 网络活动限制在临时 WSL2 namespace / veth 隔离拓扑。
- 宿主路由未变化；临时网络命名空间接口配置仅作用于隔离环境。
- cleanup 记录通过。

## 12. Round 5 Gate

Round 4 完成后，进入 Round 5 前仍需由真实模型 Consumer 能力决定 ID7 是否可正式授权。后续若要证明模型处理，应另行验证 consumer 接入、队列处理、`APPLIED` / `CONSUMED` 反馈及可观察的模型状态变化；不能把本轮 admission 结果外推为这些结论。

## 13. Final Conclusion

Round 4 达成了设计目标：HISTORY replay 使用真实在线 Session 身份进入当前 3.6 Gateway，并取得可关联的 E1 admission 证据。最终状态为：

```text
ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED
```

该状态只确认 Gateway / Receiver 收到并接纳请求，随后因当前缺少目标 consumer 返回 `FAILED / TARGET_MISSING`。**APPLIED、CONSUMED、execution_ready 和 target Kylin qualification 均为 false。**
