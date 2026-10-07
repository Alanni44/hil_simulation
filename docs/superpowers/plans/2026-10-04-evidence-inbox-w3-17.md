# Common Evidence Inbox W3.17 Implementation Plan

> **For agentic workers:** Use executing-plans/TDD inline and independent read-only review. No implementation delegation, commits, branches, worktrees or frozen QA generation.

**Goal:** 按已批准M3反馈采集/冻结第11章，让同一实际UDPSource/Dispatcher保存原收报并关联标准140，终态ACK后仍可收证据，不让Evidence替代事务终态或签模型成功。

**Architecture:** 新建evidence.py的EvidenceInbox(session,*,max_requests=4096,max_records=4096,max_bytes=16777216)；由UDPDispatcher.enable_evidence_collection建立并由现有UDPSource唯一读者持有。watch_evidence(header,*,event_id,trace_id,min_step,max_step,stages=('E1','E2','E3'))只绑定本dispatcher原pending opaque Header、当前实际SID/capabilities/model及原完整请求/标准payload编码hash。实际逐片TX标记完成后才接受140关联；上下文留到显式unwatch/close，不随ACK或drain清空。已有socket入口保存实际datagram/peer/channel/本机收时刻，140走独立原Reassembler，普通反馈仍走原匹配路径。

**Tech Stack:** 原Python3.12、dataclasses/hashlib/json、PayloadCodec/WireCodec/Reassembler；无新依赖、无新端口或Windows后端。

## Constraints

- 单一代码，14源/原C/六工具/41责任/17未执行Linux不改。原130/131/141/142事务语义、重试/取号/全局TX顺序不变。
- max_requests/max_records正整数1..65536，max_bytes正整数1..128MiB；上下文及记录共享字节限制，预留最坏一帧+一份完整逻辑记录后再recv，满时明确BUFFER_FULL不先消费socket。drain只释放记录，不复位上下文/已TX身份或UDP原64SID/8192序列缓存。
- 绑定先严格原类型/Schema、同当前SID/实际pending原Header、TO_36/model检查；明确uint32 min/max闭区间，event/trace为冻结128字符非空字符串，stage闭集合。保留原类型/负零，hash取实际PayloadCodec bytes，不取JCS归一化后的PACKED_LE值。
- 收报先保存实际原码、peer、channel和本机monotonic_ns；不把异机mono_ns相减，不把原码存在等价E1。错误peer/CRC/未关联/非法140亦保留DATAGRAM，不静默删除已有记录。
- 140分别核验标准SID/transaction/request_sequence/message、event/trace/hash、声明stage/model_step范围、probe冻结归属/型号；E2/E3必须非NO_PROBE且在当前实际grant.available_probes，consumer必须同消息，模型路径必须原完整消息group和本型号。模型输入probe不得被包装为E3业务响应。
- Evidence是独立观察，不作为131心跳租约/普通ACK/141commit，不关闭pending、不免重试。完整记录保存对端business_result/error而不本地篡改，qualification_status恒NOT_EVALUATED、execution_ready=false；真正采集器/reader资格和关联样本/持久包继续共同后续。
- 140重复/冲突/回退沿同一UDPSource实际高水位/缓存规则，不另建序列域。绑定后未实际完整TX、旧SID/到期、缺probe或错误业务声明拒绝；ACK结束后绑定仍存在并能实际收140。关闭只停本地采集，不冒充远端RESET/九项清理。

## Tasks

### 1. Bound Actual Requests And Records

Files: create input_simulator/evidence.py, tests/icd_gateway/test_evidence.py; modify input_simulator/dispatch.py and udp_source.py.

- [x] RED缺模块/enable/watch；GREEN实际session唯一owner inbox、有界不可变上下文/原码记录、严格绑定参数与原payload hash。
- [x] RED没有实际TX/错SID/transaction/sequence/message/event/trace/hash/step/stage/probe和错误型号；GREEN只有完整原TX后允许关联，对端声明仍NOT_EVALUATED。

```python
inbox = dispatcher.enable_evidence_collection()
header = dispatcher.submit(stimulus, target_step=100)
dispatcher.watch_evidence(header, event_id='send-01', trace_id='run-01', min_step=0, max_step=1100)
assert inbox.execution_ready is False
```

### 2. Actual Socket And Completion Independence

- [x] RED实际socket收140被丢/终态ACK后不poll；GREEN旁路140重组/关联/普通ACK继续，同一reader可无pending但有watch时采集。
- [x] RED所有原反馈datagram/非法peer/CRC需保留、重复冲突/到期/容量满/drain/unwatch/close；GREEN容量前置、同一高水位、显式移除上下文与关闭保留记录，不提升标准能力。

```python
dispatcher.poll()
# A real UDP protocol peer emits the unchanged 140; it is not a qualified model.
dispatcher.poll()
assert dispatcher.pending_count == 1
assert inbox.records[-1].qualification_status == 'NOT_EVALUATED'
```

Run: python -X utf8 -m unittest discover -s tests/icd_gateway -p test_evidence.py -v; 原21dispatcher/31source-session/16assertion，最终scripts/test_icd_runtime.py与34选定静态、14源/663引用、pip/编译/台账/源码hash。

### 3. Review And Handoff

- [x] 独立只读复核，重要发现先RED再修；固定源码完整回归，不以测试peer冒充正式消费者。
- [x] 新建artifacts/icd_gateway/w3-17-validation.json；唯一Linux台账仅追加并核对历史prefix。L-002/L-004/L-010/L-011/L-014/L-017接真实探针/原四ETH反馈/授权时钟/终态后证据/并发背压/持久包/安全；原41/17与完整目标保持。

## Full Scope Remains Required

本包补实际收报与关联，不完成真实reader/available_probes资格、样本与140绑定、持久TXRX证据包、真实场景状态机/WAIT/全部事件/负例/清理、六工具实际授权生命周期、完整回放、25API/控制台/Robot、全部C/设备消费者/RT/发布与真实3.3替换。已批准整个方案不缩小，也不另建Linux实现。

## Verified Closeout

2026-10-04固定源码最终入口637共用通过（67协议27.772s/563网关321.779s/3台账/4汇总）；另34选定静态、原59业务/72完成/85黄金片/800RAW、pip/编译/14逐字节源/663引用通过。25新专项15.058s、21原dispatcher13.769s、31原会话6.455s、16原断言8.774s通过。独立25专项15.458s及租期解码边界复核无剩余重要问题；原租期缓存误接受先RED后修，回拨/失败claim保留原请求和收报、不推进高水位。

运行容量须至少两个record slots，并容纳保守完整65536字节UDP、最大逻辑回复、原请求与元数据；max_records=1虽为合法配置，但收报预检明确BUFFER_FULL且不消费socket。逻辑bytes账不是实际RSS/RT资格。原socket全部14反馈原码、非法peer/CRC/超长报、乱序分片140、ACK后独立证据、全组实际TX、原PACKED_LE负零与同一序号域已覆盖；qualification恒NOT_EVALUATED，实际接收服务尚不产生真实模型140。独立报告artifacts/icd_gateway/w3-17-validation.json保存四源码/测试hash和完整剩余责任。

追加后复核：台账原52723个归一化UTF16字符prefix的UTF8 SHA256仍为9e3647059acb3f62c316646c4baff9c7d383e4fbf0faf33b7702dbad6fde165a，历史逐字保持；41责任/17 Linux/0完成不变。四源码hash及637总数核对通过，3台账0.008s、4单文件契约0.158s和git diff --check再次通过。只关闭本聚焦包，不勾选完整M3/M4/W3或整个方案完成。
