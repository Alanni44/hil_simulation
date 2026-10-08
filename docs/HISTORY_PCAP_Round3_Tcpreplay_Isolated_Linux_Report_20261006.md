# HISTORY PCAP Round 3：隔离 Linux tcpreplay TX/RX 验证报告

日期：2026-10-06  
最终状态：**PASS — ROUND3_ISOLATED_NETWORK_TX_RX_VALIDATED**  
环境资格：**WSL2_SOFTWARE_ONLY**，不代表目标麒麟系统 qualification。

## 1. Executive Summary

Round 3 已完成。

在 Windows 主机的 Ubuntu 24.04.3 WSL2 环境内，创建了完全隔离的 Linux network namespace + veth 拓扑，实际启动 `tcpreplay` 将 Round 2 的 `prepared.pcap` 发出，并由接收 namespace 中的 `tcpdump` 实际捕获为 `received.pcap`。

最终有效尝试为 `retry_2`：

- `tcpreplay` 实际启动并退出 0；
- 发送 1 packet / 114 bytes；
- successful packets = 1，failed packets = 0；
- `tcpdump` 实际捕获 1 packet，kernel drop = 0；
- 项目正式 `CaptureParser` 可读取发送前/接收后 PCAP；
- TX/RX packet count 与顺序一致；
- **TX/RX raw Ethernet frame bytes 完全一致**；
- HIL1 UDP payload bytes 完全一致；
- `WireCodec` 解码、Header、CRC 与业务 payload 均通过；
- namespace/veth/tcpdump/tcpreplay 均已清理；
- 未接入 3.6 Gateway，未验证在线 Session、APPLIED 或 CONSUMED。

因此，本轮首次可以确认：

```text
process_started = true
actual_network_tx = true
actual_network_rx = true
frame_bytes_matched = true
```

但仍必须保持：

```text
three_six_receiver_involved = false
online_session_authorized = false
received_by_3_6 = false
applied = false
consumed = false
execution_ready = false
target_kylin_qualified = false
```

## 2. Attempt History

### 2.1 Initial Blocked Attempt

最初 Codex 执行环境调用 WSL 时得到：

```text
Wsl/EnumerateDistros/Service/E_ACCESSDENIED
```

因此产生了 `LINUX_ENVIRONMENT_REQUIRED` 阻塞记录，没有实际 TX/RX。

后续通过独立主机检查确认：

```text
Ubuntu          Running    WSL2
docker-desktop  Running    WSL2
WslService      Running
```

说明该错误属于当时 Codex/执行上下文无法访问 WSL 服务，而不是主机没有 WSL。

最初阻塞记录已保留到：

```text
artifacts/history/round3/initial_blocked/
```

### 2.2 retry_1：真实网络成功，但 Capture Profile 不兼容

完成 WSL 工具安装后首次实际运行：

```text
tcpreplay → isolated veth → tcpdump
```

网络执行本身成功：

- tcpreplay：1 packet / 114 bytes，failed=0；
- tcpdump：1 packet captured，0 dropped；
- 两个进程 exit code 均为 0。

但 tcpdump 使用 `-s 0`，在当前 WSL/libpcap 上生成：

```text
snapshot length 262144
```

而项目 `CaptureParser` 冻结约束：

```text
MAX_PACKET_BYTES = 65535
1 <= snaplen <= 65535
```

因此 retry_1 的 `received.pcap` 被项目 parser 正确拒绝：

```text
RESOURCE: unsupported or inconsistent PCAP version/time/snaplen
```

该失败属于**捕获容器 profile 不兼容**，不是 tcpreplay 发送失败，也不能绕过 parser 强行判 PASS。

retry_1 证据完整保留。

### 2.3 retry_2：最终有效验证

retry_2 只修改 tcpdump snaplen：

```text
-s 0
→
-s 65535
```

tcpreplay 输入、Replay 参数、prepared.pcap bytes、namespace/veth 网络拓扑均未改变。

最终正式验证通过。

## 3. Environment

- Host：Windows 10.0.26200
- Linux：Ubuntu 24.04.3 LTS
- Kernel：Linux 6.6.87.2-microsoft-standard-WSL2
- Environment class：`WSL2_SOFTWARE_ONLY`
- iproute2：6.1.0
- tcpreplay：4.4.4
- tcpdump：4.99.4
- libpcap：1.10.4
- Target Kylin qualification：**false**

WSL 初始缺少 tcpreplay/tcpdump。

由于本机 Clash/Fake-IP DNS 将 Ubuntu 源解析到 `198.18.x.x`，WSL 无法直接通过原 apt 源安装。安装过程中仅临时：

1. 使用 Cloudflare DoH 确认真实 DNS；
2. 使用清华 TUNA HTTPS Ubuntu 镜像；
3. 安装 `tcpreplay` 和 `tcpdump`；
4. 安装完成后恢复原 `ubuntu.sources`；
5. 恢复 `/etc/hosts`；
6. 删除临时安装脚本。

当前已确认原 apt 源恢复为：

```text
http://archive.ubuntu.com/ubuntu/
http://security.ubuntu.com/ubuntu/
```

未修改 sudoers，未设置永久 capability，未保留临时 DNS/hosts 配置。

## 4. Isolation Topology

最终 retry_2：

```text
TX namespace: uav-r3-tx-22451
eth0
MAC 02:00:00:00:00:01
IP  10.36.0.10/24

        tcpreplay
            │
            ▼
      isolated veth pair
            │
            ▼

RX namespace: uav-r3-rx-22451
eth0
MAC 02:00:00:00:00:02
IP  10.36.0.20/24
        │
        ▼
      tcpdump
```

TX route：

```text
10.36.0.0/24 dev eth0 proto kernel scope link src 10.36.0.10
```

RX route：

```text
10.36.0.0/24 dev eth0 proto kernel scope link src 10.36.0.20
```

两端均无 default route。

没有 bridge 到宿主物理网卡、校园网或互联网。

## 5. Input Integrity

Round 2 输入：

```text
artifacts/history/round2/prepared.pcap
```

SHA256：

```text
febbf0e10c98b3d4adafa7dcb5027e0e6b0f212b6828a779f404d51ddf172134
```

与 Round 2 manifest / command resource SHA256 一致。

Linux 仅进行路径转换：

```text
E:\GuoZhao\Desktop\UAVDemo\...
→
/mnt/e/GuoZhao/Desktop/UAVDemo/...
```

文件 bytes 未变化。

## 6. Actual Execution

### 6.1 tcpdump

retry_2 实际参数核心语义：

```text
tcpdump
-i eth0
-nn
-s 65535
-U
-c 1
-w received.pcap
udp and dst host 10.36.0.20 and dst port 36100
```

结果：

```text
1 packet captured
1 packet received by filter
0 packets dropped by kernel
exit code = 0
```

### 6.2 tcpreplay

实际命令保持 Round 2 Builder 参数语义，仅转换文件系统路径：

```text
tcpreplay
--intf1=eth0
--loop=1
--multiplier=1.0
prepared.pcap
```

结果：

```text
Actual: 1 packets (114 bytes) sent
Successful packets: 1
Failed packets: 0
Truncated packets: 0
Retried packets (ENOBUFS): 0
Retried packets (EAGAIN): 0
exit code = 0
```

## 7. Frame Comparison

接收文件：

```text
artifacts/history/round3/retry_2/received.pcap
```

received.pcap SHA256：

```text
869af54e7f3efba604ab1467d876020d29057a85e8ace43b2658e4c134fabb9c
```

注意：prepared.pcap 与 received.pcap 的**整个文件 SHA256 不应相等**，因为抓包时间戳和 PCAP container metadata 可以不同。

本轮按照要求比较每个实际 Ethernet frame 的 raw bytes。

结果：

```text
packet count: 1 == 1
packet order: equal
raw Ethernet frame bytes: equal
raw frame SHA256:
b5c0811f436742860216a520042c429b0360e39d8028071af05ea8cea76217cb
```

UDP payload SHA256：

```text
a77ecc03dbc44e35f354c739dbe0831d8ed75419663f178c39af3f1ee0a2a1c3
```

TX/RX UDP payload bytes 完全一致。

### 7.1 L2 / IPv4 / UDP

验证结果：

- source MAC：`02:00:00:00:00:01`
- destination MAC：`02:00:00:00:00:02`
- EtherType：IPv4
- source IPv4：`10.36.0.10`
- destination IPv4：`10.36.0.20`
- IP total length：100
- UDP source port：36102
- UDP destination port：36100
- UDP length：80
- IPv4 / UDP checksum 均由项目 CaptureParser 验证。

### 7.2 HIL1

正式 `WireCodec` 重读 RX payload：

```text
message_id = 7
direction = TO_36
fragment_index = 0
fragment_count = 1

session_id = 92
sequence = 102
target_step = 201
transaction_id = 302
valid_for_ms = 100
```

HIL CRC：PASS。

业务 payload：

```json
{"motor_command":[0.1,0.2,0.3,0.4]}
```

与 Round 2 PreparedReplay 业务语义一致。

## 8. Evidence Claims

| Claim | Round 3 |
|---|---|
| command_built | true |
| process_started | **true** |
| actual_network_tx | **true** |
| actual_network_rx | **true** |
| frame_bytes_matched | **true** |
| packet_order_matched | true |
| HIL1 decoded | true |
| CRC verified | true |
| cleanup_complete | true |
| three_six_receiver_involved | false |
| online_session_authorized | false |
| received_by_3_6 | false |
| applied | false |
| consumed | false |
| execution_ready | false |
| target_kylin_qualified | false |

因此 Round 3 的证明范围仅为：

> **TOOL / NETWORK QUALIFICATION（WSL2 software-only）**

不是：

> **3.6 BUSINESS ACCEPTANCE / MODEL APPLICATION**

## 9. Cleanup

最终检查确认：

- `ip netns list` 无 Round 3 namespace 残留；
- 无 tcpreplay 进程残留；
- 无 tcpdump 进程残留；
- 无 veth 残留；
- 没有宿主 default route 修改；
- 没有物理 NIC 修改；
- Ubuntu apt 源已恢复；
- 临时 hosts 映射已移除；
- 临时安装脚本已移除。

```text
cleanup_complete = true
```

## 10. Tests

### 10.1 Focused Tests

正确使用仓库测试发现方式后：

- `test_replay_network_evidence.py`：6 passed
- `test_capture.py`：24 passed
- `test_reference_pcap.py`：6 passed
- `test_round2_prepared_pcap.py`：2 passed

合计：

```text
38 passed
```

曾有一次使用错误的 `python -m unittest tests.icd_gateway...` 启动方式导致 `common` import error；该问题属于测试启动路径错误，随后使用 `unittest discover -s tests/icd_gateway` 重跑全部通过，不计为产品回归。

### 10.2 Full Regression

命令：

```text
python -X utf8 scripts/test_icd_runtime.py
```

最终：

```text
Ran 1001 tests
FAILED (failures=1, errors=3)
```

与 Round 1 / Round 2 同一组既有基线问题：

1. 缺少 `artifacts/generic_models/multirotor_6/hil_contract.json`；
2. UDP `SEQUENCE_OVERRIDE` 被冻结 Header minimum 校验拒绝；
3. CANFD `SEQUENCE_OVERRIDE` 被冻结 Header minimum 校验拒绝；
4. unknown-field/no-op negative case 预期 ICDError 但未抛出。

Round 3 新增测试进入完整 suite 并通过，**未发现新增 failure/error**。

## 11. Review Findings

### Correctness

- 实际 tcpreplay 进程运行并发送；
- 实际 tcpdump 进程运行并接收；
- TX/RX raw Ethernet frame byte-exact；
- UDP bytes byte-exact；
- WireCodec 解码和 CRC 通过；
- Payload 业务语义保持。

### Regression

- Round 2 prepared.pcap SHA256 未改变；
- Round 1/2 正式编码与 Replay 语义未被放宽；
- 全量失败集合与基线一致。

### Security / Safety

- 只使用 WSL2 临时 namespace/veth；
- 无物理 NIC；
- namespace 无 default route；
- 未接入外部网络；
- 临时安装网络配置已恢复；
- cleanup 完成。

### Maintainability

新增网络证据比较逻辑是纯离线比较器：

```text
input_simulator/replay_network_evidence.py
```

它不发包、不打开 interface，只复用：

```text
CaptureParser
WireCodec
```

实际网络执行集中在：

```text
scripts/validate_history_round3_linux.sh
```

持久化证据验证集中在：

```text
scripts/validate_history_round3_received.py
```

没有引入第二套 Replay runtime。

## 12. Remaining Gates

Round 3 完成后仍未验证：

- 真实 3.6 Receiver；
- 在线 `SessionOpen → SessionOpened`；
- Heartbeat 与 session lease；
- 当前在线 session 的 Header / sequence / target_step 分配；
- 3.6 `RECEIVED / FAILED`；
- 模型 `APPLIED / CONSUMED`；
- 真实 3.3；
- 真实 HIL；
- 目标麒麟环境 qualification。

Round 2 / Round 3 中的：

```text
session_id = 92
```

仍只是离线 replay preparation fixture，不是正式在线 SessionOpen 获得的 session。

## 13. Recommended Round 4

下一阶段建议：

> **在线 SessionOpen 获得真实 session → 针对当前在线 session 重新准备 replay → 受控发送至 3.6 Gateway → 首先只验证 3.6 RECEIVED/FAILED 边界。**

Round 4 不应直接以 APPLIED 为目标，因为当前默认 3.6 Gateway 尚未接模型 Consumer。

建议阶段链：

```text
SessionOpen
→ SessionOpened(real session_id)
→ current replay header allocation / rebuild
→ prepared-online.pcap
→ controlled tcpreplay
→ 3.6 Gateway
→ RECEIVED
→ expected FAILED/TARGET_MISSING for unsupported model consumer
```

该阶段应单独设计 session lease / Heartbeat 与多链路时序，不从 Round 3 的网络成功推定业务授权成功。
