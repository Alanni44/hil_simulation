# Round 3 Prompt：Linux 隔离网络中实际运行 tcpreplay 并完成 TX/RX 字节级验证

> 推荐模型：GPT-6 Luna + High  
> 任务类型：明确规格下的 Linux 网络环境审计、隔离拓扑搭建、真实工具执行、抓包比对与证据固化。

你现在继续无人机仿真平台 3.3 → 3.6 输入模拟器中 **HISTORY / PCAP Replay** 工作线。

项目根目录（Windows 交接包）：

```text
E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006
```

Round 1 已完成：

```text
formal BusinessMessage
→ WireCodec
→ reference.pcap
→ CaptureParser
→ HistoryDecoder
→ ReplayProcessor
```

Round 2 已完成：

```text
reference.pcap
→ HistoryDecoder
→ ReplayProcessor(REENCODE)
→ PreparedReplay
→ ReplayExporter
→ prepared.pcap
→ ToolCommandBuilder
→ tcpreplay argv
```

Round 2 冻结产物：

```text
artifacts/history/round2/prepared.pcap
artifacts/history/round2/prepared_manifest.json
artifacts/history/round2/round2_validation.json
artifacts/history/round2/tcpreplay_command.json
docs/HISTORY_PCAP_Round2_Prepared_PCAP_Report_20261006.md
```

Round 2 prepared PCAP SHA256：

```text
febbf0e10c98b3d4adafa7dcb5027e0e6b0f212b6828a779f404d51ddf172134
```

本轮目标严格限定为：

> **在一个完全隔离的 Linux 网络环境中，实际执行 tcpreplay，把 Round 2 的 prepared.pcap 从发送端 namespace 发到接收端 namespace，再用 tcpdump 抓回 received.pcap，并对发送前文件与实际接收帧进行字节级验证。**

本轮验证的是：

```text
tcpreplay / libpcap / Linux veth / tcpdump
实际 TX → 实际 RX
```

本轮**不接 3.6 Gateway，不验证在线 Session，不验证 APPLIED/CONSUMED，不接真实网卡，不接真实 3.3/HIL。**

---

## 1. Research First

施工前必须阅读：

```text
docs/HISTORY_PCAP_Round2_Prepared_PCAP_Report_20261006.md

artifacts/history/round2/prepared_manifest.json
artifacts/history/round2/round2_validation.json
artifacts/history/round2/tcpreplay_command.json

input_simulator/capture.py
input_simulator/tool_commands.py
input_simulator/replay_export.py
input_simulator/replay_process.py
input_simulator/tool_process.py

tests/icd_gateway/test_capture.py
tests/icd_gateway/test_tool_commands.py
tests/icd_gateway/test_replay_process.py
```

重点确认：

1. Round 2 prepared.pcap 当前 hash；
2. Round 2 argv 的语义：
   - `--loop=1`
   - `--multiplier=1.0`
   - interface；
   - input file；
3. 当前 CaptureParser 对 PCAP/Ethernet/UDP 的读取规则；
4. 当前 Round 2 prepared frame 的 MAC/IP/UDP/HIL1 Header；
5. 不要把 `ReplayProcessAuthority` 缺失误当成本轮阻塞：本轮做的是底层工具链资格验证，不是正式业务 ReplayProcessRun。

---

## 2. Environment Gate

### 2.1 必须运行在 Linux 内核环境

优先级：

1. 原生 Linux；
2. WSL2，前提是当前实例真实支持：
   - network namespace；
   - veth；
   - raw packet injection；
   - tcpdump；
   - tcpreplay。

如果是 WSL2，报告必须标记：

```text
environment_class = WSL2_SOFTWARE_ONLY
target_kylin_qualified = false
```

不能把 WSL2 成功写成麒麟/目标机 qualification。

如果当前只在 Windows 原生 Python/PowerShell 环境中，且没有可用 Linux 环境：

> 停止真实发送阶段，报告 `LINUX_ENVIRONMENT_REQUIRED`，不要降级到 Windows Npcap 或真实 Windows 网卡。

### 2.2 工具检查

施工前执行并记录：

```bash
uname -a
cat /etc/os-release || true
ip -Version
tcpreplay --version
tcpdump --version
python3 --version
```

并检查：

```bash
command -v ip
command -v tcpreplay
command -v tcpdump
```

若缺少系统工具：

- 不静默修改 sudoers；
- 不授予永久 capabilities；
- 不自动切到真实物理接口；
- 如需系统包安装，只能在当前执行环境明确获得用户/终端授权后进行；
- 若无法获得权限，报告缺失工具和建议安装命令，停止本轮真实 TX。

---

## 3. 权限边界

Round 3 可能需要 root/CAP_NET_ADMIN/CAP_NET_RAW 来创建 namespace/veth 和运行抓包/回放。

允许的高权限操作仅限：

- 创建本轮临时 network namespace；
- 创建本轮临时 veth pair；
- 设置这些临时 veth 的 MAC/IP/up；
- 在这些临时 veth 上必要时调整 offload；
- 在 namespace 内执行 tcpdump/tcpreplay；
- 删除本轮自己创建的 namespace/veth。

禁止：

- 修改 sudoers；
- 给 tcpreplay/tcpdump 永久 setcap；
- 修改宿主机默认路由；
- 修改真实物理 NIC 的 IP/MAC/MTU/offload；
- 修改宿主防火墙；
- 开启 bridge 到真实网络；
- 使用校园网/互联网/物理以太网接口；
- 将 namespace 接到宿主默认 namespace 的物理网络。

如果权限不足：

```text
status = PRIVILEGE_REQUIRED
```

停止，不要绕过。

---

# 4. 隔离网络拓扑

本轮建议创建两个临时 network namespace：

```text
uav-r3-tx-<run>
uav-r3-rx-<run>
```

使用一对 veth：

```text
TX namespace                      RX namespace

eth0  --------------------------  eth0
MAC 02:00:00:00:00:01            MAC 02:00:00:00:00:02
IP  10.36.0.10/24                 IP  10.36.0.20/24

        tcpreplay  →  tcpdump
```

要求：

- 两个 namespace 只通过这一对 veth 互联；
- namespace 内不得存在 default route；
- 不连接 bridge；
- 不连接宿主物理网卡；
- 两端接口名称均可在各自 namespace 中叫 `eth0`；
- MAC/IP 与 prepared.pcap 的冻结 ETH_0 profile 一致；
- interface 必须 `UP`。

建立后记录：

```bash
ip netns list
ip netns exec <tx> ip -details link show
ip netns exec <tx> ip addr show
ip netns exec <tx> ip route show

ip netns exec <rx> ip -details link show
ip netns exec <rx> ip addr show
ip netns exec <rx> ip route show
```

验收前必须确认两边都**没有 default route**。

---

## 5. Namespace 安全创建/清理

不要使用一个可能已经属于用户的固定 namespace 名然后无条件删除。

要求：

1. 使用本轮唯一名称；
2. 创建前检查名称不存在；
3. 记录哪些对象由本轮创建；
4. cleanup 只能删除本轮自己创建的对象；
5. 使用 `trap/finally` 保证异常时也尝试清理；
6. 如果清理失败，报告残留对象名称，不伪装 CLEAN。

不要删除任何预先存在的 namespace、veth、bridge 或 route。

---

# 6. Round 2 prepared.pcap 输入完整性

真实执行前必须重新计算：

```bash
sha256sum prepared.pcap
```

要求严格等于：

```text
febbf0e10c98b3d4adafa7dcb5027e0e6b0f212b6828a779f404d51ddf172134
```

并与：

```text
prepared_manifest.json
tcpreplay_command.json
```

一致。

如果 Linux 环境通过 WSL2/共享目录/复制获取文件：

- 允许 Linux 路径与 Windows 路径不同；
- 不允许内容变化；
- 必须用 SHA256 证明字节相同。

Round 2 的 Windows argv 中最后一个路径不能直接作为 Linux 路径使用。

本轮允许做：

> **filesystem path translation only**

例如：

```text
E:\...\prepared.pcap
→
/mnt/e/.../prepared.pcap
```

或复制到一个临时 Linux 目录。

但：

- tcpreplay 参数语义不能改变；
- prepared.pcap bytes 不能改变；
- Linux 实际使用的文件必须再次 hash；
- 在 Round 3 evidence 中记录 `path_translation_only=true`。

---

# 7. tcpreplay 命令

Round 2 Builder 生成的语义基线：

```text
tcpreplay
--intf1=eth0
--loop=1
--multiplier=1.0
prepared.pcap
```

Round 3 不重新设计 Replay 参数。

Linux 中实际 argv 必须保持：

- `--intf1=eth0`
- `--loop=1`
- `--multiplier=1.0`
- 输入为同 hash 的 prepared.pcap。

只允许最后一个 filesystem path 根据 Linux 环境变化。

不要增加：

- `--loop=0`
- `--topspeed`
- `--mbps`
- `--pps`
- `--unique-ip`
- `--enet-vlan`
- 任意 packet rewrite 参数。

Round 3 的目标是验证 Round 2 已准备好的帧，不是再加工它。

---

# 8. tcpdump 捕获

必须先启动 RX namespace 中的 tcpdump，再执行 tcpreplay。

建议捕获：

```bash
ip netns exec <rx> tcpdump \
  -i eth0 \
  -nn \
  -s 0 \
  -U \
  -c <expected_packet_count> \
  -w received.pcap
```

如果需要过滤，过滤条件只能用于缩小本轮预期流量，例如：

```text
udp and dst host 10.36.0.20 and dst port 36100
```

但优先考虑：

> namespace 内只有一条隔离 veth，本轮可以直接抓完整 eth0 流量，并通过 packet count / bytes 过滤验证。

必须保证 tcpdump 已进入捕获状态后才执行 tcpreplay。

如果需要后台进程：

- 保存 PID；
- 设置有限 timeout；
- 正常等待其因 `-c N` 退出；
- 超时则停止并记录失败；
- 不留下孤儿 tcpdump。

---

# 9. 真实执行顺序

推荐顺序：

```text
1. 环境/工具/权限检查
2. prepared.pcap SHA256 校验
3. 创建 TX/RX namespaces + veth
4. 设置 MAC/IP/interface up
5. 确认无 default route
6. 启动 RX tcpdump
7. 确认 tcpdump ready
8. 在 TX namespace 实际执行 tcpreplay
9. 等待 tcpdump 完成
10. 保存 tcpreplay stdout/stderr/exit code
11. 保存 tcpdump stdout/stderr/exit code
12. 对 received.pcap 做字节级验证
13. 固化 evidence
14. cleanup namespaces
15. 验证 cleanup 完成
```

---

# 10. Offload 处理

默认先不修改 offload。

如果实际收到的 frame 与 prepared frame 不一致，并且证据指向 veth checksum/GSO/GRO/offload：

可以只在**本轮临时 veth**上检查：

```bash
ethtool -k eth0
```

必要时只对临时 veth 关闭相关 offload，再重跑一次。

禁止修改宿主真实 NIC 的 offload。

如果系统没有 ethtool，不要因为缺它直接判失败；只有在确实出现疑似 offload 差异时才需要。

报告必须区分：

```text
FIRST_RUN
OFFLOAD_ADJUSTED_RETRY
```

不能隐藏第一次结果。

---

# 11. 字节级验收

不要直接比较：

```text
prepared.pcap file bytes == received.pcap file bytes
```

因为 PCAP 容器头和 capture timestamp 可以不同。

必须比较**每个实际 Ethernet frame 的 raw bytes**。

使用现有：

```text
input_simulator.capture.CaptureParser
```

分别读取：

```text
prepared.pcap
received.pcap
```

至少验证：

### Packet count

```text
TX packet count == RX packet count
```

### Packet order

逐索引一致，不允许排序后再比较。

### Raw Ethernet bytes

优先验收：

```text
prepared_packet.raw_bytes == received_packet.raw_bytes
```

若存在 Linux capture/offload 导致差异，不允许直接忽略；必须定位具体字段并给出证据。

### L2

- source MAC；
- destination MAC；
- EtherType。

### IPv4

- src/dst；
- protocol；
- total length；
- checksum。

### UDP

- src port 36102；
- dst port 36100；
- length；
- checksum；
- payload bytes。

### HIL1

用正式 `WireCodec.decode` 验证：

- magic；
- message_id=7；
- direction=TO_36；
- session=92；
- sequence=102；
- target_step=201；
- transaction=302；
- fragment index/count；
- CRC；
- payload semantic。

业务 payload 仍应为：

```json
{"motor_command":[0.1,0.2,0.3,0.4]}
```

---

# 12. Evidence 状态

Round 3 成功后，允许首次声明：

```text
process_started = true
actual_network_tx = true
actual_network_rx = true
frame_bytes_matched = true
```

但必须仍然保持：

```text
three_six_receiver_involved = false
online_session_authorized = false
received_by_3_6 = false
applied = false
consumed = false
execution_ready = false
target_kylin_qualified = false   # 除非真的在目标麒麟环境
```

特别注意：

> tcpdump RX ≠ 3.6 RECEIVED。

---

# 13. 不接 3.6 Gateway

本轮禁止：

- 启动 `icd_gateway` 作为目标；
- 使用 127.0.0.1 DEVELOPMENT Gateway；
- 为 session 92 人工插入 grant；
- 修改 SessionRegistry 接受离线 session；
- 通过关闭鉴权让 prepared.pcap “通过”。

原因：

Round 2 的 session 92 只是：

```text
offline replay preparation fixture
```

不是在线 `SessionOpen → SessionOpened` 分配的 session。

Round 3 只验证工具/网络，不验证业务授权。

---

# 14. 建议实现方式

优先新增一个**独立的 Round 3 integration runner**，不要侵入正式 runtime。

例如：

```text
scripts/validate_history_round3_linux.py
```

或：

```text
scripts/validate_history_round3_linux.sh
```

要求：

- Linux-only，非 Linux 明确拒绝；
- 明确 root/权限检查；
- 严格限定 namespace/veth；
- 不调用真实物理 NIC；
- 有 finally/trap cleanup；
- 每一步记录 command、exit code、stdout/stderr；
- 执行前验证 Round 2 hash；
- 执行后使用现有 Python CaptureParser/WireCodec 比对。

不要为了“通用化”写成任意接口/任意命令执行器。

---

# 15. Round 3 产物

建议：

```text
artifacts/history/round3/
  received.pcap
  round3_manifest.json
  round3_validation.json
  environment.json
  executed_tcpreplay_command.json
  tcpreplay_stdout.txt
  tcpreplay_stderr.txt
  tcpdump_stdout.txt
  tcpdump_stderr.txt
```

如果第一次执行失败后因 offload 做受控重试：

```text
artifacts/history/round3/
  first_run/
  retry_1/
  ...
```

不要覆盖失败证据。

---

# 16. round3_manifest.json

至少记录：

- source prepared.pcap path；
- source prepared.pcap SHA256；
- received.pcap SHA256；
- environment class；
- kernel；
- OS；
- tcpreplay version；
- tcpdump version；
- iproute2 version；
- namespace names；
- interface names；
- MAC/IP；
- default_route_present=false；
- actual tcpreplay argv；
- path_translation_only；
- expected packet count；
- actual packet count；
- raw frame hashes TX；
- raw frame hashes RX；
- raw_frame_bytes_equal；
- UDP payload hashes；
- HIL1 decoded Header；
- cleanup status；
- process_started；
- actual_network_tx；
- actual_network_rx；
- three_six_receiver_involved=false；
- received_by_3_6=false；
- applied=false；
- consumed=false；
- execution_ready=false；
- target_kylin_qualified。

---

# 17. Tests / Verification

新增的纯 Python 比对逻辑应该有小范围单元测试，例如：

1. prepared/received 相同 frame → PASS；
2. frame count 不同 → FAIL；
3. packet order 改变 → FAIL；
4. Ethernet byte 改变 → FAIL；
5. UDP payload 改变 → FAIL；
6. HIL1 CRC/头错误 → FAIL；
7. manifest 不允许把 tcpdump RX 标为 3.6 RECEIVED。

Linux namespace + tcpreplay 属于 integration validation，不强求在普通 Windows test suite 中执行。

现有完整测试仍有 Round 2 基线：

```text
1 failure
3 errors
```

本轮不要顺手修它们。

至少重新运行：

```text
tests/icd_gateway/test_capture.py
tests/icd_gateway/test_reference_pcap.py
tests/icd_gateway/test_round2_prepared_pcap.py
```

以及任何新增 Round 3 unit tests。

如果 Linux runner 不属于默认 Windows test suite，报告中明确说明。

---

# 18. Cleanup 验收

Round 3 不只是“包发成功”才算完成。

最后必须检查：

```bash
ip netns list
```

确认本轮创建的 namespace 已删除。

并确认：

- 没有残留 veth；
- 没有残留 tcpdump；
- 没有残留 tcpreplay；
- 没有修改宿主默认路由；
- 没有修改物理 NIC。

如果 cleanup 失败：

```text
cleanup_complete = false
status = PARTIAL_FAILURE
```

不能标记 Round 3 完成。

---

# 19. Review After Implementation

## correctness

- tcpreplay 是否真的运行；
- exit code 是否为 0；
- tcpdump 是否真的收到预期 frame；
- raw Ethernet bytes 是否一致；
- HIL1 是否仍可正式解码；
- packet count/order 是否一致。

## regression

- Round 1/2 artifact hash 是否保持；
- 没有修改 WireCodec/ReplayProcessor 正式语义。

## safety

- 只使用隔离 namespace/veth；
- 无真实 NIC；
- 无 default route；
- cleanup 完成。

## maintainability

- runner 是否仅为 Round 3 integration validation；
- 是否避免另写一个 replay runtime；
- 是否复用 CaptureParser/WireCodec。

## evidence

严格区分：

```text
COMMAND_BUILT
PROCESS_STARTED
NETWORK_TX
NETWORK_RX
3_6_RECEIVED
APPLIED
CONSUMED
```

---

# 20. 报告

生成：

```text
docs/HISTORY_PCAP_Round3_Tcpreplay_Isolated_Linux_Report_20261006.md
```

至少包含：

## 1. Executive Summary

- 是否真实执行 tcpreplay；
- 是否收到 frame；
- frame bytes 是否一致；
- cleanup 是否完成；
- 环境属于 native Linux / WSL2 / 其他。

## 2. Environment

- kernel；
- OS；
- versions；
- privilege；
- 是否目标麒麟环境。

## 3. Isolation Topology

画出：

```text
TX namespace / veth → RX namespace / veth
```

列 MAC/IP/route。

## 4. Input Integrity

- prepared.pcap path；
- expected SHA256；
- actual SHA256；
- path translation/copy 情况。

## 5. Execution

- tcpdump command；
- tcpreplay command；
- exit codes；
- stdout/stderr 摘要。

## 6. Frame Comparison

- packet count/order；
- raw frame hash；
- L2/IP/UDP/HIL1；
- payload semantic。

## 7. Evidence Claims

明确哪些 true/false。

## 8. Cleanup

说明 namespace/process/interface 是否完全清理。

## 9. Test Results

列出实际命令和结果。

## 10. Review Findings

correctness / regression / safety / maintainability。

## 11. Remaining Gates

至少包括：

- 3.6 Receiver 未参与；
- 在线 SessionOpen/Heartbeat 未验证；
- Round 2 session 92 不是正式在线 session；
- APPLIED/CONSUMED 未验证；
- 真实 3.3/HIL 未验证；
- 如非目标麒麟：目标系统 qualification 未验证。

## 12. Recommended Round 4

只提出，不提前实现。

Round 4 应围绕：

> **在线 SessionOpen 获得真实 session → 为当前在线 session 重新准备 replay → 受控发送到真实 3.6 Gateway → 只验证 3.6 RECEIVED/FAILED 边界，不直接跳到模型 APPLIED。**

---

# 21. Definition of Done

仅当全部满足时 Round 3 才完成：

- [ ] 实际运行环境是 Linux 内核环境；
- [ ] prepared.pcap SHA256 与 Round 2 一致；
- [ ] 未修改 Round 1/2 冻结 artifact；
- [ ] 使用隔离 network namespaces；
- [ ] 仅使用本轮临时 veth；
- [ ] namespace 无 default route；
- [ ] tcpdump 在 RX 端先启动；
- [ ] tcpreplay 实际启动；
- [ ] tcpreplay exit code 成功；
- [ ] tcpdump 实际捕获预期 packet count；
- [ ] TX/RX packet order 一致；
- [ ] TX/RX raw Ethernet frame bytes 一致，或任何差异均被明确定位且未被静默忽略；
- [ ] HIL1 WireCodec decode/CRC 通过；
- [ ] process_started=true；
- [ ] actual_network_tx=true；
- [ ] actual_network_rx=true；
- [ ] three_six_receiver_involved=false；
- [ ] received_by_3_6=false；
- [ ] applied=false；
- [ ] consumed=false；
- [ ] execution_ready=false；
- [ ] cleanup_complete=true；
- [ ] 无残留 namespace/veth/process；
- [ ] 生成 Round 3 报告。

如果真实 Linux 环境、权限或工具不可用：

> 输出真实阻塞证据并停止。不要使用物理接口、Windows 网卡或关闭安全边界来“完成”Round 3。

---

## 最终原则

Round 2 证明：

> **prepared.pcap 已经可以被 tcpreplay 消费。**

Round 3 要第一次证明：

> **tcpreplay 真正把 prepared.pcap 的帧发上了隔离 Linux 网络，而且接收侧真实抓回来的 Ethernet frame 与准备发送的 frame 字节一致。**

这仍然只是：

```text
TOOL / NETWORK QUALIFICATION
```

不是：

```text
3.6 BUSINESS ACCEPTANCE
MODEL APPLICATION
```
