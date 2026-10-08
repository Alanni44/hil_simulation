# Common Observation Archive W3.18 Implementation Plan

> **For agentic workers:** Execute inline with executing-plans/TDD and independent read-only review. No commits, branches, worktrees, implementation delegation or frozen QA regeneration.

**Goal:** 按整体M5原始TX/RX与失败证据保存要求，将当前真实会话/dispatcher/inbox记录形成同代码、有限、不可覆盖且可读回核验的持久证据段，为后续完整运行包提供真实原码，不冒充运行结果或模型资格。

**Architecture:** 新建input_simulator/evidence_archive.py。prepare_evidence_archive(dispatcher, *, run_id, inbox=None, max_records=100000, max_bytes=67108864)在原dispatcher和session单owner锁下取得完整当前记录快照，不drain/取号/发送/复位。返回不可变ObservationArchive(records_jsonl, manifest_json)；JSONL将原bytes显式base64、uint64本机时间十进制字符串保存，恢复原SourceExchange/DispatchRecord/EvidenceRecord类型，不把PACKED_LE原json重新规范化。write_new_directory(path)采用现有ReplayExport的独占目录/xb/fsync/逐字节读回/最后manifest硬链接发布模式，失败保留未完成目录与原内存记录。read_evidence_archive(path,contract,*,max_records=100000,max_bytes=67108864)有界读取，逐文件hash/闭结构/行计数/基线检查，拒绝不完整、篡改或提升资格的包。

**Tech Stack:** 原Python3.12标准库dataclasses/base64/hashlib/pathlib/os/platform/sys及原JSON工具；无新依赖、无OS分支、无ICD字段更改。

## Global Constraints

- 14冻结源、原C、六工具、标准ICD保持；41责任/17 Linux待办保持。只新增内部证据存储格式，不替代正式Report/API或扩展线上Evidence140。
- 所有准备/保存/读回execution_ready=false、qualification_status=NOT_EVALUATED、evidence_complete=false；原远端PASS/FAIL声明只保真。早于inbox开启的原socket RX不存在则不补造，snapshot不是整次运行完整性证据。
- 明确run_id非空1..128字符；max_records严格整数1..100000，max_bytes严格整数1..256MiB，准备/读回均计manifest及整个JSONL字节，超限CAPACITY。原有记录不删除，不自动drain/unwatch/关闭会话，不动高水位。
- 并发snapshot在原dispatcher/session锁下失败STATE，持久化只处理脱离不可变bytes不持锁做IO，不阻塞真实RT模型；准备后到保存期间新增记录不混进旧段，调度器不得用该段声明完整运行。
- 文件仅records.jsonl/manifest.pending.json/manifest.json；新目录不可覆盖，缺manifest/多余或符号链接文件、篡改hash/计数/基线/结构、非法base64/原JSON及资格提升拒绝。读回验证是内容一致性，不是签名或来源证明。

## Tasks

### 1. Immutable Original Snapshot

Files: create input_simulator/evidence_archive.py and tests/icd_gateway/test_evidence_archive.py; reuse original records without modifying their owners.

- [x] 写真实UDP peer测试：原SessionOpen/实际TX/ACK后140/非法CRC原码保留，prepare前后原内存记录/请求/序号不变；无模块时RED。
- [x] 实现同owner锁下的完整有限快照，原时间字符串及bytes base64，恢复原记录/opaque Header字段值，原负零与错误标志完整保真。

```python
archive = prepare_evidence_archive(dispatcher, run_id='run-01', inbox=inbox)
assert archive.execution_ready is False
assert archive.manifest['evidence_complete'] is False
assert len(archive.records) == len(session.records) + len(dispatcher.records) + len(inbox.records)
```

### 2. Exclusive Durable Persistence And Readback

- [x] 写新目录真实保存/读回、已有目录不覆盖、篡改/缺manifest/超限/非法字段及模拟fsync/readback/link故障测试，先观察RED。
- [x] 实现写后读回与最后manifest发布；故障不删未完成文件/原内存记录，不公布成功，不使用rename覆盖旧包。
- [x] 实现读回闭结构/当前冻结基线/每行原始bytes与时间/计数校验，拒绝资格提升，读回不授予当前会话/执行能力。

```python
manifest = archive.write_new_directory(new_directory)
saved = read_evidence_archive(manifest.parent, contract)
assert saved.records_jsonl == archive.records_jsonl
assert saved.records == archive.records
```

Run: isolated python -X utf8 -m unittest discover -s tests/icd_gateway -p test_evidence_archive.py -v; 原25inbox/21dispatcher回归；最终scripts/test_icd_runtime.py及34选定静态、pip/编译/14源/663引用，四源码/测试hash视实际改动记录。

### 3. Review And Append-Only Handoff

- [x] 独立只读复核，重要发现RED/GREEN；固定源码完整回归。
- [x] 保存独立artifacts/icd_gateway/w3-18-validation.json，追加唯一linux-development-backlog.md并验证历史prefix、41责任/17待执行；追加目标文件系统/磁盘背压/非实时写盘/多段完整性及安全资格。

## Full Scope Remains Required

当前段保存不是最终完整运行包；真实140 producer/reader/采样值与元数据关联、多段持续排空与连续完整性、运行环境/工具/模型全部hash、断言/安全结果与正式Report、真实模型步场景/全部handler/WAIT/负例/九项清理、三源/三模式回放与六工具实际执行、25API/控制台/Robot、Linux模型/驱动/设备/RT/不可变发布及真实3.3替换继续完整原计划。

## Verified Closeout

2026-10-04固定最终源码657共用通过（67协议/583网关330.976s/3台账/4汇总），34选定静态、59业务/72完成/85黄金片/800RAW、pip/编译/14逐字节源/663引用守护通过。20专项12.734s、25原inbox15.508s、21原dispatcher13.914s和共用源码守护1项0.713s通过。独立最终20专项12.731s/源码守护0.687s及11种重哈希类型/范围错误、远端PASS保真但不提升资格、重复snapshot不改时钟/计数/租期/上下文探针通过。

14缺模块用例先RED后实现；目录有界扫描先RED后提前拒绝，独立确认Python3.12 Path.iterdir底层listdir仍全量分配，再以真实os.scandir primitive测试RED/GREEN修正。首轮完整回归583网关334.409s中1项原守护失败，原因仅宿主metadata使用sys.platform；改用无分支platform.platform，原守护不改，修后固定源码完整回归通过。独立报告artifacts/icd_gateway/w3-18-validation.json记录两源码/测试hash、首轮失败与最终结果；本阶段不涉及原dispatcher/inbox/session源码修改。

文件fsync和读回通过不等于目录元数据掉电一致性、来源签名或完整运行资格；本段标志始终NOT_EVALUATED/evidence_complete=false/ready=false。多段连续性、非实时持续写盘与安全背压、真实消费者及正式Report继续原责任，不勾选完整M5/W3或整个方案。

追加后复核台账旧55224个归一化UTF16字符prefix的UTF8 SHA256仍为2ce0349613e19c6e3ab5cf3e8d7b782dde9c8c18b29e40b709df740a124dab6e；历史逐字保持，41责任/17 Linux/0完成不变。两源码hash及657总数复核通过；3台账0.008s/4单文件契约0.156s/git diff --check再次通过，仅关闭本聚焦证据段工作包。
