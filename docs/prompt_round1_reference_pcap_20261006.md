# Round 1 Prompt：生成首份软件级 reference.pcap 并闭环验证 HISTORY 链

你现在继续无人机仿真平台 3.3 → 3.6 输入模拟器中 **HISTORY / PCAP Replay** 这条工作线。

项目根目录：

```text
E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006
```

Round 0 已完成只读交接审查。本轮开始允许做**最小必要实现**，但范围严格限定为：

> 使用现有冻结 v0.3 ICD 和正式编码器，生成第一份软件级 `reference.pcap`，再让现有 `CaptureParser → HistoryDecoder → ReplayProcessor` 重新读取并验证它。

本轮**不是**完成 tcpreplay 在线回放，不是接模型 Consumer，也不是证明 APPLIED / CONSUMED / E2 / E3。

---

## 1. 已确认基线

以下结论来自 Round 0，但你仍应在施工前快速核对对应代码，若源码与结论冲突，以源码和冻结接口为准：

1. `icd_runtime.wire.WireCodec` 已实现正式 v0.3 UDP 编码：
   - 正式 Payload 编码；
   - HIL1 UDP Header；
   - CRC32；
   - 分片；
   - 不需要另写 Demo 私有 Encoder。
2. `input_simulator.udp_source.UDPSource` 已实现正式 UDP 发送。
3. `input_simulator.scapy_source.ScapySource` 已能构造完整 Ethernet / IPv4 / UDP / HIL1 Frame，并记录 `L2Transmission.ethernet_data`。
4. 当前缺少“从零 bootstrap 第一份 reference.pcap”的直接持久化入口。
5. `CaptureParser`、`HistoryDecoder`、`ReplayProcessor`、`ReplayExporter` 已存在。
6. `ReplayExporter` 面向已有 Capture → PreparedReplay 的后续导出，不能自己 bootstrap 第一份历史 PCAP。
7. 默认 DEVELOPMENT Gateway 主要发布 ID 1；模型 Consumer 尚未接入。普通模型消息不能以 APPLIED 作为本轮验收。
8. 开发 Gateway 使用 loopback，但 HISTORY 冻结 ETH_0 profile 使用：
   - source：`10.36.0.10:36102`
   - receiver：`10.36.0.20:36100`
   - channel：`ETH_0`

本轮生成的 reference PCAP 必须按冻结 HISTORY profile 编写端点，不能把 `127.0.0.1` 抓包直接冒充正式 ETH_0 历史。

---

## 2. Research First

施工前优先读取，避免重复实现：

```text
README_代码整理.md
docs/interfaces/输入模拟器完整接口定义_v0.3_单文件汇总.md
docs/interfaces/baseline/
icd_runtime/README.md
icd_gateway/README.md

input_simulator/capture.py
input_simulator/history.py
input_simulator/replay.py
input_simulator/replay_export.py
input_simulator/scapy_source.py
input_simulator/udp_source.py

icd_runtime/contract.py
icd_runtime/payload.py
icd_runtime/wire.py

tests/icd_runtime/
tests/icd_gateway/test_capture.py
tests/icd_gateway/test_history.py
tests/icd_gateway/test_replay.py
tests/icd_gateway/test_replay_export.py
tests/icd_gateway/test_scapy_source.py
```

重点确认：

- 是否已有可复用的 PCAP writer/helper；
- `CaptureParser` 对 Ethernet、PCAP nano timestamp、端点和 linktype 的精确要求；
- `HistoryDecoder` 如何判定 ETH_0 / TO_36；
- `ReplayProcessor.prepare` 对 History definition、bindings、declared_ids、ReplayPolicy、Header allocation 的要求；
- 现有测试/golden/example 中哪一个 **UDP TO_36 BusinessMessage** 最适合作为首份 reference 样本。

不要凭记忆发明业务 payload。优先复用冻结 examples/golden/test fixture 中已经通过契约验证的字段值；运行时代码不得依赖 test-only helper。## 3. Python 环境

用户习惯使用 **Anaconda / conda** 管理 Python 虚拟环境。

本项目交接要求 Python 3.12。不要使用当前系统 Python 3.14 直接施工，也不要默认改用 `venv`。

先检查 conda 是否可用以及是否已经存在合适的 Python 3.12 环境。

若没有，优先建立独立环境，例如：

```powershell
conda create -n uav-history-pcap python=3.12 -y
conda activate uav-history-pcap
python --version
```

依赖 Source of Truth 仍然是仓库现有：

```text
requirements-icd.txt
```

安装依赖时优先使用中国大陆可用的可信 PyPI 镜像，例如：

```powershell
python -m pip install -r requirements-icd.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

若镜像缺包、版本滞后、哈希/完整性异常或依赖解析失败，回退官方 PyPI，并在报告中说明原因。

不要修改全局 conda 配置，不污染其他项目环境。

如果 conda 本身不可用，不要静默切到 venv；明确记录环境阻塞。

---

## 4. Baseline Verification

在修改代码前，先建立当前代码基线。

至少执行：

```powershell
python -X utf8 scripts/test_icd_runtime.py
```

并根据项目已有测试组织方式运行与本任务最相关的测试：

```text
tests/icd_runtime/
tests/icd_gateway/test_capture.py
tests/icd_gateway/test_history.py
tests/icd_gateway/test_replay.py
tests/icd_gateway/test_replay_export.py
tests/icd_gateway/test_scapy_source.py
```

不要为了绿色结果修改已有失败测试。

记录：

- Python 版本；
- 依赖版本；
- 实际执行命令；
- 通过/失败数量；
- 失败原因；
- 修改前基线。

如果全套测试耗时/依赖范围明显超出本轮，应优先跑项目已有官方脚本 + 聚焦测试，并说明未跑范围。

---

# 5. Round 1 目标

实现一个**最小、可追溯、可测试的软件级 reference PCAP bootstrap 能力**。

目标链路：

```text
Validated BusinessMessage
        ↓
Contract / PayloadCodec / WireCodec
        ↓
formal HIL1 UDP bytes
        ↓
Ethernet / IPv4 / UDP serialization
        ↓
PCAP Writer
        ↓
reference.pcap
        ↓
CaptureParser
        ↓
HistoryDecoder
        ↓
ReplayProcessor
        ↓
PreparedReplay
```

成功标准不是“文件存在”，而是：

> 新生成的 PCAP 必须被现有正式 HISTORY 解析链重新读回，并且 ReplayProcessor 可以基于它生成 `PreparedReplay`。

`PreparedReplay.execution_ready == false` 在本轮是正常且正确的，不要为了变成 true 绕过现有门禁。

---

## 6. 首份样本消息选择

不要一上来做完整：

```text
RunConfigure → START → TAKEOFF → STOP
```

Round 1 优先选择 **1 个最简单、已有冻结示例或测试夹具证明合法、且正式 transports 包含 UDP 的 TO_36 业务消息**。

选择原则：

1. 必须来自正式 v0.3 catalogue/schema；
2. 必须是 `TO_36`；
3. 必须支持 `UDP`；
4. 优先单分片或最小复杂度；
5. 必须可以由 `Contract.validate_message` 通过；
6. 不得自己猜 payload；
7. 为后续 `ReplayProcessor` 留下完整可选业务组。

如果 `SessionOpen` 被包含在参考捕获中：
- 它只作为历史来源/会话建立记录；
- 不得把 session 0 的 SessionOpen 当成普通业务 Replay 输入；
- Replay window 应能排除它，或按现有 History/Replay 规则明确处理。

如果现有验证夹具中有更适合 Replay 的非 SessionOpen UDP TO_36 消息，优先选它。

在实施报告中说明最终为何选该 message_id。

---

## 7. PCAP 内部网络 Profile

首份软件级 reference PCAP 使用冻结 ETH_0 profile：

```text
channel: ETH_0
source IPv4: 10.36.0.10
source UDP port: 36102
receiver IPv4: 10.36.0.20
business UDP port: 36100
VLAN: none
transport: Ethernet / IPv4 / UDP
direction: TO_36
```

不要把 DEVELOPMENT Gateway 的：

```text
127.0.0.1:36102 → 127.0.0.1:36100
```

写入这份 reference PCAP 后声称其通过冻结 HISTORY profile。

MAC 地址必须使用明确、合法、非零、单播的值。优先沿用项目已有测试/ExportBinding 中已经使用的 deterministic local-admin MAC，例如：

```text
02:00:00:00:00:01
02:00:00:00:00:02
```

如果源码已有更权威的软件样本 MAC 约定，以现有约定为准。

必须在 manifest/report 中明确：

> MAC 仅为软件生成 reference 样本的确定性 L2 identity，不代表真实部署硬件 MAC。## 8. Timestamp 规则

不要直接把 `time.monotonic_ns()` 当成 PCAP Unix epoch。

Round 1 应使用**显式、确定性的 PCAP epoch + 相对 offset**，保证：

- 文件可重复生成；
- 时间戳合法；
- CaptureParser 可无损读取；
- HistoryDecoder 顺序稳定；
- 后续 Replay 能保留相对时间关系。

优先使用项目已有 ReplayExporter / Capture 测试中的时间戳表示和写法。

如果需要新增固定 epoch，请：

1. 把它定义为“software reference fixture epoch”，不是实时系统时间；
2. 在 manifest 中记录；
3. 不把该绝对时间解释为真实 3.3 抓包时间。

如果只有一个逻辑消息，其第一片 relative offset 可为 0；若存在多分片，保持同一逻辑组的合法顺序和现有重组时限。

---

## 9. 实现原则

### 9.1 不重写协议

禁止重新实现：

- Payload schema；
- HIL1 Header；
- CRC32；
- UDP 分片；
- BusinessMessage 校验。

这些必须继续调用：

```text
Contract
PayloadCodec
WireCodec
```

### 9.2 PCAP Writer 只负责封装和持久化

新增代码只应承担缺失的 bootstrap 职责：

```text
formal UDP bytes
→ deterministic Ethernet frame
→ deterministic timestamp
→ PCAP file
→ metadata/manifest
```

不要在 writer 里复制业务编码逻辑。

### 9.3 优先复用现有实现

`ReplayExporter` 已有 RawPcapWriter/PCAP serialization 经验。

先判断能否抽取/复用一个**通用、无 Replay 语义污染的最小 helper**。

如果直接复用 ReplayExporter 会导致循环依赖或错误抽象：

- 不要强行复用；
- 可以新增一个非常薄的 PCAP writer；
- 但必须避免复制大量 ReplayExporter 业务验证逻辑。

### 9.4 不强行改造 ScapySource

Round 0 发现 `ScapySource._emit_packet` 同时承担：
- 构造完整帧；
- 实际 L2 send；
- 记录 `L2Transmission`。

如果为了 bootstrap 需要“只构帧、不实际发送”，优先选择：

- 提取一个纯函数/helper 来生成相同 frame bytes；或
- 新建一个明确的软件 reference frame builder；

而不是通过 mock 一个假 L2 socket 冒充真实发送成功。

必须保持：

> 软件生成样本 ≠ 实际 TX evidence。

不要改变现有 ScapySource 的安全边界和 qualification 语义。

---

# 10. 建议产物位置

不要把二进制 PCAP 放进 `docs/`。

优先创建类似：

```text
artifacts/history/round1/
```

建议输出：

```text
artifacts/history/round1/reference.pcap
artifacts/history/round1/reference_manifest.json
artifacts/history/round1/round1_validation.json
```

如果项目已有更明确的 artifact 命名约定，以现有约定为准。

manifest 至少记录：

- baseline version；
- baseline SHA256；
- generator version/entry；
- message_id；
- direction；
- channel；
- source/destination IP/port；
- source/destination MAC；
- packet count；
- logical message count；
- timestamp epoch；
- relative offsets；
- PCAP SHA256；
- 每帧 SHA256；
- UDP payload SHA256；
- synthetic/reference 标志；
- `actual_network_tx=false`；
- `model_applied=false`；
- `execution_ready=false`。

不要记录秘密、凭据或无关个人信息。

---

# 11. Round-trip 验证

生成 PCAP 后，必须使用**现有代码**重新验证。

至少做到：

### V1. CaptureParser

```text
reference.pcap
→ CaptureParser.parse(...)
```

核对：

- format；
- linktype；
- packet count；
- timestamp；
- raw Ethernet bytes；
- IPv4 endpoints；
- UDP ports；
- UDP payload；
- VLAN 状态；
- transport。

### V2. WireCodec

对 PCAP 中每个 HIL UDP payload：

```text
WireCodec.decode(...)
```

核对：

- HIL1；
- message_id；
- direction；
- header；
- fragment index/count；
- CRC；
- payload bytes。

多分片时必须经过现有 `Reassembler` 得到完整逻辑消息。

### V3. HistoryDecoder

构造符合冻结 schema 的 History definition/bindings，不要绕过验证。

```text
reference.pcap
→ HistoryDecoder.decode(...)
```

必须识别为：

```text
ETH_0
TO_36
```

并还原预期业务消息。

### V4. ReplayProcessor

基于实际 History definition 和 ReplayPolicy 调用：

```text
ReplayProcessor.prepare(...)
```

优先选择最适合本样本的正式 replay mode。

如果使用 `SESSION_REBUILD` / `REENCODE`：
- Header allocation 必须显式；
- 使用新的非零 session；
- sequence/transaction/target_step 满足现有校验；
- 不允许重用 captured session；
- 不允许放宽 policy。

验收：

```text
PreparedReplay created
execution_ready == false
packets > 0
selected records are TO_36 only
```

不要调用 `require_execution_ready()` 企图把本轮变成在线执行资格。## 12. Tests

为新增 bootstrap 能力增加**最小必要测试**，遵循现有 unittest/test 风格。

至少覆盖：

1. 同一输入重复生成得到 deterministic PCAP bytes/hash；
2. PCAP 能被现有 CaptureParser 读取；
3. raw Ethernet frame 与生成前 frame bytes 一致；
4. UDP payload 与 `WireCodec.encode` 输出一致；
5. 冻结 ETH_0 端点正确；
6. HistoryDecoder 成功识别 TO_36；
7. ReplayProcessor 成功生成 PreparedReplay；
8. manifest hash 与实际文件一致；
9. 禁止 loopback profile 被误标成冻结 ETH_0 reference；
10. malformed/unsupported input 明确失败，不静默补值。

不要删除、弱化现有测试。

若发现为了测试而需要改生产逻辑，先判断是否是真实设计缺口；不要仅为测试方便扩大公共 API。

---

## 13. 本轮明确禁止

不要执行或实现：

- 实际 tcpreplay；
- canplayer；
- SocketCAN/vcan；
- 修改物理网卡地址；
- 向 `10.36.0.20` 真实发包；
- raw socket 实机资格验证；
- 真实 3.3；
- 真实 HIL 硬件；
- 模型 APPLIED/CONSUMED；
- Vue/WebSocket/STOMP；
- Robot Framework 全链；
- Run/Report 全系统；
- 完整飞行场景；
- 新的模拟器私有 UDP 协议；
- 修改冻结 v0.3 baseline；
- 为了通过验证修改 HistoryDecoder 使其接受任意 endpoint。

特别禁止：

> 发现 loopback PCAP 不被 HistoryDecoder 接受后，直接把 HistoryDecoder 改成“什么 IP 都接受”。

本轮应该生成符合冻结 profile 的 reference，而不是放宽正式接收规则。

---

# 14. Review After Implementation

实施完成后，独立审查：

### correctness
- PCAP 是否真的是 Ethernet/IPv4/UDP；
- payload 是否真的来自 WireCodec；
- CRC 是否未被 writer 二次破坏；
- HistoryDecoder 是否真正读回；
- ReplayProcessor 是否真正处理生成文件。

### regression
- 是否改变现有 WireCodec / ScapySource / ReplayExporter 行为；
- 现有相关测试是否仍通过。

### security / safety
- 是否误发真实网络；
- 是否打开未授权 raw interface；
- 是否修改全局网络配置；
- 是否写入敏感数据。

### maintainability
- 是否出现第二套 Encoder；
- 是否复制大段 ReplayExporter 逻辑；
- helper 是否职责单一。

### evidence
严格区分：

```text
GENERATED
PARSED
DECODED
PREPARED
TRANSMITTED
RECEIVED
APPLIED
CONSUMED
```

本轮最多证明前四项。

---

# 15. 最终验证

完成后至少运行：

1. 新增/修改相关测试；
2. Capture / History / Replay 聚焦测试；
3. `python -X utf8 scripts/test_icd_runtime.py`；
4. 对生成文件重新计算 SHA256；
5. 用项目代码重新读取最终落盘的 `reference.pcap`，不是只验证内存对象。

如果完整测试因交接包缺失外部工程资料无法执行，明确列出“未验证”，不要补造成功结论。

---

# 16. 最终报告

生成一份 Markdown 报告，建议：

```text
docs/HISTORY_PCAP_Round1_Reference_PCAP_Report_20261006.md
```

报告至少包括：

## 1. Executive Summary
- 本轮完成什么；
- 未完成什么；
- reference.pcap 是否生成；
- HISTORY round-trip 是否通过；
- ReplayProcessor 是否得到 PreparedReplay。

## 2. Environment
- conda env；
- Python；
- dependency install；
- 镜像/官方源使用情况。

## 3. Implementation
列出修改文件、职责和为什么需要。

## 4. Selected Reference Message
- message_id；
- 来源；
- 为什么选择；
- transport/direction；
- 是否 SessionOpen；
- replay window 如何处理。

## 5. reference.pcap Metadata
- endpoint；
- MAC；
- timestamp；
- frame count；
- file SHA256；
- baseline SHA256。

## 6. Validation Chain

```text
BusinessMessage
→ WireCodec
→ Ethernet Frame
→ reference.pcap
→ CaptureParser
→ HistoryDecoder
→ ReplayProcessor
→ PreparedReplay
```

逐项给真实结果。

## 7. Test Results
记录实际命令和通过/失败。

## 8. Review Findings
correctness / regression / safety / maintainability。

## 9. Remaining Gates
至少明确：
- tcpreplay 未执行；
- Linux qualification 未验证；
- 真实网络 TX 未验证；
- 3.6 APPLIED/CONSUMED 未实现；
- 真实 3.3 未验证。

## 10. Recommended Round 2
只提出下一步，不提前实施。

---

# 17. Definition of Done

只有同时满足以下条件，Round 1 才可以标记完成：

- [ ] 使用 conda Python 3.12 环境；
- [ ] 没有修改冻结 v0.3 baseline；
- [ ] 没有实现第二套业务 Encoder；
- [ ] 使用正式 `WireCodec` 产生 UDP bytes；
- [ ] 生成完整 Ethernet/IPv4/UDP PCAP；
- [ ] PCAP 使用冻结 ETH_0 endpoint profile；
- [ ] 软件样本身份与真实 TX 明确区分；
- [ ] 最终文件有 SHA256 和 manifest；
- [ ] CaptureParser 能读取最终落盘文件；
- [ ] HistoryDecoder 能还原预期 TO_36 业务消息；
- [ ] ReplayProcessor 能产生非空 PreparedReplay；
- [ ] `PreparedReplay.execution_ready == false` 被保留；
- [ ] 新增测试通过；
- [ ] 相关既有测试未回归；
- [ ] 生成 Round 1 实施报告；
- [ ] 未声称 tcpreplay / APPLIED / Linux / 实机 / 真实3.3 已验证。

如果其中任何关键项受阻，保留已有正确实现，报告具体阻塞和证据，不通过放宽协议或伪造测试结果来“完成”任务。

---

## 最终原则

本轮最重要的不是“做出一个 .pcap 文件”，而是建立第一个可追溯闭环：

> **正式 ICD 编码 → 软件级 Ethernet 历史文件 → 正式 HISTORY 解码 → 正式 Replay 准备。**

优先简单、可验证、可复用。

不要把 Round 1 扩成完整 Replay 系统。
