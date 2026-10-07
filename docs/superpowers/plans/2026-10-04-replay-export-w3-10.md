# Original Tool Replay Export W3.10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans and test-driven-development inline. Independent read-only review only; no implementation delegation, commit, branch or worktree.

**Goal:** 将既有三模式PreparedReplay导出为逐通道完整CAN_LOG/纳秒PCAP和有界可验证文件包，为原canplayer/tcpreplay提供正式预处理产物，不代替实际授权、工具生命周期或完整执行器。

**Architecture:** 延续批准的工具前编码/重建与各自原发送通路。新增共用`replay_export.py`，消费真实PreparedReplay，重新核对原捕获、方向、报文/CRC、包顺序、hash和端点；逐通道导出bytes，再以独占新目录持久化并最后写manifest。优先同一离线导出器，避免让各工具自行重建ICD或新建转发中心。直接把PreparedReplay当可执行授权、以及在每个工具里复制重建逻辑均不采用。

**Tech Stack:** 现有Python3.12、WireCodec/CaptureParser、python-can CAN定义、Scapy RawPcapWriter、hashlib/pathlib；不安装目标工具或新依赖。

## Global Constraints And Interfaces

- 原14冻结源、v0.3业务/目录、原C及六工具不变；唯一台账41责任/17 Linux门禁保留。窗口/方向筛选由既有ReplayProcessor完成，FROM_36只分析不导出发送。
- `ExportBinding(channel_id:str, interface:str, source_mac:str|None=None, destination_mac:str|None=None)`是本地部署元数据，完整匹配导出通道、最多56；不在wire增加字段。同一输出接口不能混合不同通道。无原Ethernet帧的辅助CAN到正式UDP必须显式提供两个有效单播MAC，不能猜L2；已有原Ethernet帧不得重写MAC。
- `ReplayExporter(contract, *, max_packets=100000, max_bytes=64MiB).export(prepared, bindings:tuple, *, epoch_ns:int)->ReplayExport`产生逐通道CAN_LOG/PCAP文件bytes、原/重建hash和精确时间索引。严格整型epoch且PCAP秒字段不溢出；Fraction非整数ns明确UNSUPPORTED。保持原文件包顺序、重复片、CAN FD/BRS/ESI、原业务字节/真实header；不把独立时钟排序成同一时间轴。
- 原PCAP帧沿用已重建Ethernet bytes并验证UDP payload/端点/checksum；辅助CAN生成Ethernet时只使用显式MAC和已确定标准UDP端点。Scapy以整数sec/subsec写纳秒PCAP，不用浮点时间或墙钟默认值。CAN_LOG用精确整数9位小数，重新经原CaptureParser/python-can读取核对。
- canplayer实际源码支持6/9位时间但调度截为微秒，因此文件保留ns并单独声明`tool_timing_compatible=false`时不可直接按原时序发；不四舍五入、降精度或放宽期限。tcpreplay实际版本/libpcap时序资格尚未测，标unknown而不是true。文件是预处理资源，不是目标时序或E1/E2/E3。
- `ReplayExport.execution_ready`恒false；`write_new_directory(path)->Path`仅独占新目录，逐文件xb/fsync，全部hash读回一致后写/fsync/读回`manifest.pending.json`，最后用不覆盖硬链接发布`manifest.json`；保留pending链接，不在发布后进行可能失败的清理。既有目录拒绝，不支持硬链接的文件系统明确失败不静默降级。发布前I/O失败保留独占目录内未完成事实、不删除/覆盖用户文件，缺manifest不是完整包；未承诺目录断电持久性或正式发布资格。manifest含同版baseline、捕获hash、完整policy、mode/repeat/gap、接口、文件hash/size、精确逐片索引及pending checks。
- 限制总文件bytes+manifest bytes和包数；不可变export数据，不静默截断/反馈混入/自动循环10000轮。完整实时执行器、授权/RESET/初始输入/清理、SID退休、六工具进程与后端、场景/API/Robot继续原完整范围。

## Task 1: Complete Per-Channel Export

**Files:** Create `input_simulator/replay_export.py`; create `tests/icd_gateway/test_replay_export.py` using existing replay fixture helpers without duplicate suite discovery.

补充内部证据：`PreparedReplay.policy_json:bytes`保留原canonical ReplayPolicy，导出核对policy hash/mode/repeat与实际捕获/窗口/倍率的精确时间；这不是新增线上字段。修改`input_simulator/replay.py`构造该不可变内部证据，原回放接口不增加调用者参数。

- [x] RED完整三模式UDP PCAP、11条CANFD输入完整重组与原码重复顺序、反馈隔离、多通道接口、精确大epoch/ns/倍率、明确MAC辅助转换及非法/篡改PreparedReplay拒绝。目录共13 CANFD消息=11输入+2反馈，反馈不导出发送。

```python
bundle = ReplayExporter(contract).export(prepared, (ExportBinding("ETH_0", "eth0"),), epoch_ns=1770000000000000001)
captured = CaptureParser().parse(bundle.files[0].data, "PCAP")
assert captured.packets[0].payload == prepared.packets[0].wire_data
assert captured.packets[0].timestamp_ns == 1770000000000000001
assert not bundle.execution_ready
```

- [x] 执行`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_replay_export.py -v`，先观察导出模块缺失导致明确断言失败。
- [x] GREEN实现严格绑定/原码校验、整数CAN日志/Scapy PCAP和只分析元数据；19专项通过，原回放26及解码23专项通过。

## Task 2: Exclusive Persistent Package And Closeout

**Files:** Extend above module/tests; append sole Linux ledger and overall record; create `artifacts/icd_gateway/w3-10-validation.json`.

- [x] RED真实临时目录写出、全部文件hash/manifest读回、既有目录/文件保护、失败后无完整manifest、容量在写入前拒绝和immutable输出。

```python
manifest = bundle.write_new_directory(new_path)
report = json.loads(manifest.read_text(encoding="utf-8"))
assert report["execution_ready"] is False
assert hashlib.sha256((new_path / report["files"][0]["name"]).read_bytes()).hexdigest() == report["files"][0]["sha256"]
```

- [x] GREEN独占持久化/读回，失败不掩盖且不删除原文件；独立只读复核19专项通过，另33次CANFD输出覆盖11输入三模式/ESI；重要发现先RED后GREEN修复，无遗留重要scoped发现。
- [x] 固定源码运行完整`python -X utf8 scripts/test_icd_runtime.py`，493共用通过（67协议/419网关/3台账/4汇总），网关262.646s；另34选定静态、59/72/85/800、pip/编译、14源/663引用、41/17守护通过。
- [x] 保存独立阶段报告`artifacts/icd_gateway/w3-10-validation.json`，追加Linux原工具实际文件/调度精度/多通道/停止/授予/模型/设备要求及共用未完，不覆盖历史或勾选目标项。耗时不是RT或目标性能证据。

## Source References And Qualification Boundary

- canplayer upstream timestamp parsing: `https://github.com/linux-can/can-utils/blob/master/canplayer.c`, lines427-445/520-538 as inspected2026-10-04; target版本须独立锁定并复测，主线源码不是部署资格。
- Scapy installed RawPcapWriter inspected: explicit `sec`/`usec`, `nano=True`, linktype1; installeddependency is original library, not QA vendor import.
- 本包实现完整导出而非完整运行。真实grant/header已可由SourceSession提供，但离线文件本身不能证明当前会话/target/状态/工具/clock就绪。
