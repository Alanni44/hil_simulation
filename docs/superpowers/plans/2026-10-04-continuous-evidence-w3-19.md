# Common Continuous Observation Recorder W3.19 Plan

> **For agentic workers:** Execute inline with executing-plans/TDD and independent read-only review. No commits, branches, worktrees, implementation delegation or frozen QA regeneration.

**Goal:** 按整体M5有界原始证据持久化要求，补连续采集的单任务后台写盘、成功后精确回收和多段完整性；不改变标准ICD或冒充模型/整次运行验收。

**Architecture:** 新建input_simulator/evidence_recorder.py的ObservationRecorder(dispatcher, path, *, run_id, inbox=None, max_segments=10000, max_records=100000, max_bytes=67108864, max_total_bytes=268435456)。复用W3.18原prepare/read/archive格式；flush准备当前完整段并保存同owner原record对象前缀，单个非daemon Thread只做脱离bytes写盘与commit发布。poll只在实际线程终止/成功、段/commit逐字读回且所有原前缀仍相同后原子释放三池对应记录数量/bytes，追加收报不删，watch/高水位/计数/租期/在途预约不变。原三池drain在recorder持有期间拒绝。段commit保存index/previous sha/原archive hashes和累计流计数；read_observation_chain(path,contract,*,max_segments=10000,max_records=100000,max_bytes=268435456)有限扫描/闭字段校验所有原段，缺段/错误hash/身份/计数/未提交残留明确失败。

**Tech Stack:** 原Python3.12 threading/dataclasses/pathlib/hashlib、原ObservationArchive/JSON工具，无新依赖、无OS分支、无新端口/线上字段。

## Constraints

- 原14冻结源/C/六工具不动，41责任/17 Linux保持；所有segment/chain/closeout始终NOT_EVALUATED/evidence_complete=false/ready=false。不将链内容完整性当原总线零丢包、来源签名或完整正式Report。
- 严格正整数：max_segments1..100000、max_records每段1..100000、max_bytes1..256MiB、max_total_bytes1..1GiB；单个pending原快照/线程，不静默驱逐。所有archive+commit真实bytes计总额，超过限制在启动写盘/回收之前CAPACITY。reader整链记录1..1000000，有界目录扫描用os.scandir，不调用全量Path.iterdir。
- 专用新root/segment目录与xb/fsync/readback/最后hardlink commit，失败保留原记录/已写目录和错误，不覆盖旧包/恢复或假造提交；第三方手改prefix/文件亦在回收前失败。
- recorder及原dispatcher/session锁非阻塞；snapshot后新增记录只属于下段，原prefix身份逐对象核对后一次性删除；不drain PreparedSourceInput、pending预约/watch/TX/反馈高水位，不产生RESET/九项清理。文件IO线程不持模型/运行owner锁；启用时新root创建属配置动作，不作RT证明。
- close(timeout=5)只等待同一个已启动线程，timeout严格有限0..30s，超时保持handle/owner并TIMEOUT，后续继续等同handle不重启。不丢未保存记录、不替代远端停止；线程实际终止后才detach/关闭本地recorder并报告未保存三流数量。

## Tasks

### Tail Anchor And Local Close Clarification

- read_observation_chain另支持成对expected_segments/expected_tip_sha256可信终点，严格整数与小写SHA256；无终点的活动链只验证已见前缀，不能识别整体删除末段。关闭后exclusive close.pending.json/fsync/readback/hardlink close.json保存实际提交段数/链尾/累计记录与段bytes/关闭快照未保存数；reader校验完整关闭标记并返回locally_closed，不提升evidence_complete或远端安全资格。关闭标记本身删除/重写须由未来正式Run可信元数据/权限保护检测，不能把裸hash链当来源签名。
- close检查点也计总bytes，IO不持dispatcher/source锁，失败保留原内存与未完成文件并报告RESOURCE/CAPACITY；实际线程终止后只解除本地记录器。关闭快照封存后owner忙时可重试detach，不重写检查点/新启线程。旧dispatcher关闭而recorder未detach时，禁止新dispatcher抢占原session。

### 1. Actual Background Segment And Atomic Reclaim

Create input_simulator/evidence_recorder.py, tests/icd_gateway/test_evidence_recorder.py; modify input_simulator/dispatch.py/session.py/evidence.py only recorder ownership/drain guards.

Independent review correction: evidence_archive.py extracts a private snapshot helper returning the immutable archive and original stream tuples from the same owner-lock window. Its existing public prepare API and persisted format stay unchanged; recorder never derives identity anchors from deserialized equal-value records.

- [x] 实际UDP peer与阻塞文件worker测试先RED：flush后台写盘时原dispatcher继续TX/RX，新记录保持；poll前不回收，成功仅回收旧前缀，原序号/watch/在途预约/新记录保持。
- [x] 写限额/单任务/重复owner/三池旁路drain/关闭与失败/线程启动错误测试先RED后实现；不回退序号或伪造原RX/模型成功。

```python
recorder = ObservationRecorder(dispatcher, new_root, run_id='run-01', inbox=inbox)
recorder.flush()
dispatcher.poll()
recorder.poll()
```

### 2. Original Segments And Closed Hash Chain

- [x] 连续两段真实读回及累积计数/hash测试先RED；缺段、重排序/改run/baseline/hash/计数、未提交残留/旁路回收、超限/文件/读回/发布错误均不取得成功。
- [x] 实现有界原包复核与commit链，不升格远端PASS/claim；停止等待超时只保留实际handle，完成后关闭本地并保留未保存记录。

```python
chain = read_observation_chain(new_root, contract)
assert len(chain.segments) == 2
assert chain.execution_ready is False
assert chain.evidence_complete is False
```

Run: isolated python -X utf8 -m unittest discover -s tests/icd_gateway -p test_evidence_recorder.py -v; 原20archive/25inbox/21dispatcher/31source-session；最终scripts/test_icd_runtime.py及34选定静态、59/72/85/800、pip/编译/14源/663引用、源码hash与41责任/17未执行Linux守护。

### 3. Review And Append-Only Handoff

- [x] 独立只读复核，重要发现先RED/GREEN；固定源码完整回归，保留失败而非改原测试取得通过。
- [x] 保存artifacts/icd_gateway/w3-19-validation.json，唯一Linux台账追加目标持续写盘/内核丢包/目录持久性/崩溃恢复/RT负载/失败安全工作，验证历史prefix与41/17不变。

Scoped closeout: root70 observation tests48.408s, final common682 (67/608/3/4, gateway352.521s), selected static34, codec59/72/85/800 and original14/663 checks passed. Independent25 recorder20.308s/20archive13.805s and8 originalguards plus identity/directory/budget probes passed. Review identity-window regression RED0.909s thenGREEN0.918s; same-owner archive helper fixed it without wire/public archive format changes. Six source hashes and exact historical ledger prefix verified after append,41 responsibilities/17 unexecuted Linux retained. This checks only this recorder package, not full M5/W3/overall completion.

## Full Scope Remains Required

原140 producer/qualified reader/采样值及真实event/trace身份、真实型号C/消费者/实体、完整MODEL_STEP场景与WAIT/全部handler/授权负例/九项清理、三源全回放/三模式10000repeat/RESET/initial_inputs/轮间清队列、原六工具实际发送/生命周期/SavvyCAN/Ostinato、25API/控制台/Robot、模型/工具/环境全部hash和正式结果包/RT/不可变发布与真实3.3替换仍为必做。当前多段字节链不能替代上述证据，不勾选完整M5/W3或整体完成。
