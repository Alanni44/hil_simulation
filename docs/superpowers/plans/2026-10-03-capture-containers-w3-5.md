# Capture Container W3.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and test-driven-development. Work inline; no implementation delegation, branch, worktree or commit authorized. Independent read-only review at the checkpoint is required.

**Goal:** 实现原CAN_LOG、PCAP、PCAPNG实际捕获容器与CAN/Ethernet传输解析，保留原始字节、接口/端点、精确时间戳、分辨率及不完整性，接入三源审核，不授予历史执行资格。

**Architecture:** 新增`input_simulator/capture.py`的有界`CaptureParser.parse(raw, format) -> Capture`及不可变`CapturedPacket`；CAN日志使用原python-can CanutilsLogReader，PCAP/PCAPNG使用Scapy原reader、CAN/Ether/IP/UDP/TCP解析，前置封装边界检查防止库静默截断/忽略未知块。`SourceInputAudit`增加实际捕获描述，保持history_decoded=false，单列仍未完成的流/时钟关联与标准重组，而不是把容器解析冒充45输入/14反馈解码。

**Tech Stack:** 既有独立Python3.12/python-can4.6.1，新增锁定Scapy2.7.0（纯捕获与包库，无网卡/总线启动），标准库struct/io/Fraction/hashlib；冻结14源/C/六工具不改。

## Global Constraints

- Windows只是当前宿主，同码解析器在Linux复测；不装WSL，不开发Windows驱动/计时器/替代工具，不按模拟器/真实源分支。
- 支持CAN_LOG的candump -L普通CAN/CANFD、有界严格行；PCAP四种micro/nano endian；PCAPNG严格Section/IDB/EPB，可混CAN/Ethernet接口。未知linktype、损坏/trailing/截断容器、无时间戳SPB、无法精确整数ns的时间戳必须明确失败，不静默跳过。
- CAN保留standard/extended/RTR/error/FD/BRS/ESI/DLC及完整固定结构字节，不把普通CAN当正式CANFD消息，也不把CAN捕获作为Ethernet喷射。
- Ethernet支持单层802.1Q、IPv4 UDP/TCP；验证包长度、IP checksum、UDP/TCP非零checksum与不分片，UDP zero checksum如实保留，不冒充已验证。TCP只标分析传输，不能当HIL1 UDP会话重放；IPv6/其他网络类型本包明确unsupported而非误解析。
- 使用原容器时钟ticks/分辨率的整数或有理数，禁止float舍入Unix ns；保持捕获顺序，不排序回拨时间。PCAPNG多接口/section时钟身份显式保存，不隐式跨域对齐。
- 捕获declared loss、不完整packet/ISB丢包与无法证明的capture方向/clock保持原始证据，ONLINE不放行；实际stream关联、业务重组/模型门禁与三种回放执行继续共同后续任务。不产生APPLIED/CONSUMED/E2/E3、execution_ready=true或complete_capture=true。
- 每包完成向唯一`linux-development-backlog.md`追加Linux要求，41责任/17门禁保持；不另建第二台账或输入契约。
- 容量是部署profile而非ICD：捕获默认64MiB/100000packet、CAN行512字节；PCAPNG最多100section、每section100interface、全文件200000block、每block1024option/65536option字节。合法classic CAN len8_dlc扩展暂明确UNSUPPORTED，不能误称保留位非法或静默删除。未知元数据不获得执行资格。

## Task 1: Actual Container And Packet Parsing

**Files:** Create `input_simulator/capture.py`（原包/日志库与不可变结果）, `input_simulator/_capture_envelopes.py`（库会丢失的容器/时钟/丢包边界）, `tests/icd_gateway/test_capture.py`; Modify `requirements-icd.txt`.

**Interfaces:** frozen `Capture(format, packets:tuple, observed_truncated_packets, observed_lost_packets)`；`CapturedPacket`保存原packet bytes、timestamp_ns、time_resolution_ns(Fraction)、clock_domain、capture_interface、linktype、transport、CAN metadata或IPv4端点/端口/VLAN及传输payload，不暴露可变Scapy/python-can对象。`CaptureParser(max_bytes=64MiB,max_packets=100000).parse(raw, format)`只解析bytes，不读隐含file_name路径，不启动设备。

- [x] RED创建availability、原CAN/FD精确时戳/flags、PCAP四组合、PCAPNG多接口与timestamp、原始字节不变/immutable、Ether/VLAN UDP/TCP正常与checksum测试；运行焦点unittest确认缺实现失败。
- [x] 锁定Scapy并只安装独立runtime；用真实原reader解析；使用struct仅做标准封装长度/边界/安全投影检查，domain包与日志仍由原库解析。
- [x] GREEN：错magic/版本/linktype/长度/尾随、PCAP/NG截断与重复选项、未知无timestamp块、declared packet truncation、非整数ns/epoch溢出、CAN坏flags/DLC及不合法数据、Ether坏checksum/fragment/错误VLAN/UDP/TCP长度全部拒绝或有明确不完整证据。

## Task 2: Source Audit Integration Without False Decode Qualification

**Files:** Modify `input_simulator/source_inputs.py`, `tests/icd_gateway/test_source_inputs.py`.

- [x] RED审核真实CAN_LOG/PCAP/PCAPNG bytes得到immutable capture及CLI summary；不再留容器parser pending，但仍history_decoded=false、complete_capture=null、stream/clock/wire decoding及执行pending；坏bytes不因自声明integrity_verified=true通过。真实PCAPNG文件CLI另已验证。
- [x] GREEN实现三格式共用入口调用；actual packet truncation/loss的history与全部scenario REPLAY ONLINE拒绝，OFFLINE允许解析但不授予完整性；不将declared流计数/ID当真实业务观察结果，也不改变现有ENGINEERING_JSONL语义。

## Task 3: Review, Regression And Linux Handoff

- [x] 独立只读review，重要问题先RED/GREEN修复；完整捕获边界/时间戳/corruption及API不产生发送资格检查。四项发现：option storm、scenario ONLINE实际不完整绕过、CAN RTR/error/FD矛盾、metadata-only容量；修复后独立24捕获/37输入与CLI及原攻击探针通过，无剩余重要scoped发现。
- [x] 最新完整共用入口368条（64协议/297网关与三源捕获/3台账/4接口汇总）、codec黄金、34选定旧静态、pip check/compileall、14源逐字节/663引用、41责任/17门禁通过；实际命令/计数/源hash/依赖和未完范围记`artifacts/icd_gateway/w3-5-validation.json`。
- [x] 追加唯一Linux台账L-001/L-002/L-005/L-006/L-007/L-008/L-009/L-011/L-013/L-014/L-017：实际原工具捕获、时钟/方向/接口/linktype与文件完整性、实际发送资格/性能分别验证。本包不关闭full HISTORY/W3/M3/M4或完整目标；下一共同任务是历史stream/clock/正式逻辑帧重组、三模式执行与场景执行器。

## Closeout

本聚焦包完成的是实际捕获容器/传输分析及三源审核接入，不是完整HISTORY执行。阶段报告与Linux待办保留原范围；Windows离线reader通过但无在线libpcap provider，17 Linux门禁全部未执行。当前正式接入仍无实际模型消费者资格/APPLIED/CONSUMED，不能因捕获解析完成取得E2/E3或正式发布资格。
