# Common ICD Runtime

本目录是模拟器与3.6共同使用的HIL-ICD-1.0 v0.3协议库，不是Windows版模拟器，也不是运行服务。操作系统只提供当前Python执行环境；业务、编解码、CRC和重组实现没有平台分支。Linux实时核心、SocketCAN、原六工具链进程与实物驱动不在此处重写。

## Setup And Verification

使用独立Python 3.12环境，不安装到旧HIL Python 3.6环境。以下命令从仓库根目录执行，在两种系统下使用同一入口：

```text
python -m pip install -r requirements-icd.txt
python scripts/test_icd_runtime.py
python -m icd_runtime --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27
```

指纹必须由部署/发布配置显式传入，不能仅信任目录自身声明。四组件原始文件内容与本次开发前一致。目录整理后真实组件在`docs/interfaces/baseline`；完整接口阅读文件仍是`docs/interfaces/输入模拟器完整接口定义_v0.3_单文件汇总.md`。

离线自检另外独立固定v0.3 examples/golden文件的原始SHA256，要求85个唯一黄金分片身份完整覆盖。不能通过改写同目录manifest、删除或复制测试向量获得通过。这些测试证据哈希不进入四组件业务指纹，也不是正式发布签名。

## API

```python
from pathlib import Path
from icd_runtime.contract import Contract
from icd_runtime.payload import PayloadCodec
from icd_runtime.wire import WireCodec
from icd_runtime.reassembly import Reassembler

contract = Contract.load(Path("docs/interfaces/baseline"), expected_sha256=release_fingerprint)
contract.validate_message(message, direction="TO_36", model_id="quadrotor_hil")
wire = WireCodec(contract)
packets = wire.encode(message, "UDP")
assembler = Reassembler(contract)
for packet in packets:
    fragment = wire.decode(packet, "UDP", direction="TO_36")
    result = assembler.push(fragment, channel="ETH_0", direction="TO_36",
                            authorized=acl_allows_actual_endpoint)
    if result is not None:
        validated_message = result.message
```

- `PayloadCodec.encode/decode`只处理工程载荷，不发送管理包装。
- `WireCodec.encode/decode`处理业务CAN FD或UDP帧。CANFrame携带标准ID、FD/BRS、数据帧属性；真实后端负责取得这些实际属性，不得伪造。
- `VideoCodec.encode/decode`处理HIV1。使用`VideoHeader`提供明确session/stream/frame/step/PTS/codec，RAW固定921600字节；H26x仅做Annex B字节封装检查，不证明可解码、参数集/IDR或消费。
- `Reassembler.push`只接收已通过帧校验的不可变fragment，并二次检查容量元数据；调用者须串行访问，在传入`authorized=True`前检查真实端点/会话权限。只允许目录中对应介质的逻辑通道。
- W2会话接收器显式使用`retain_completed=False`，由完整逻辑消息的会话缓存负责去重和重发反馈；默认W1行为不变。`pre_session_namespace`只允许SessionOpen/session0，按真实授权grant隔离，仍共享容量；不是新线上字段。`discard_session`释放该会话全部组/终结记录。
- 重组期限使用接收端单调时钟，重复片不续期；CAN FD20ms、UDP/视频100ms。到期、冲突、校验失败清理整组。
- 业务每通道最多64个重组组；视频全局最多4帧；总载荷预留8MiB。不将该载荷预算冒充Python进程完整堆内存上限。
- 有界终结缓存最多8192项、保留5秒，阻止同一通道/传输组再次产出完成结果。跨链路统一序列、会话过期和全局事务去重必须在W2接入服务另行执行，不能把缓存淘汰后的消息视为新鲜。
- `CompletedMessage`和`CompletedVideo`仅表示重组与内容校验完成，不表示APPLIED/CONSUMED或任何E2/E3证据。视频元数据哈希/流身份关联与同步必须由后续服务验证。

拒绝通过`ICDError.code/detail`返回，错误码遵循冻结目录；这个异常本身不是线上ACK。UTC字段格式及uint64字符串实际上限有运行校验，JSON不接收BOM、重复键、非有限数值或孤立代理项；不自动补值或截断。

## Acceptance Boundary

本次在Windows宿主执行共用代码的离线测试，Linux执行环境尚未实测；不存在另一套Linux/Windows实现。新依赖在实际Linux目标上仍须独立安装、资格确认和版本记录，不能覆盖旧环境。

离线自检覆盖59类消息的72种业务传输组合、85条黄金测试片和800片RAW重组。以下仍未执行：网络服务与会话状态机、三源执行器、前后端API、真实模型写入/消费、六工具链资格、H26x解码/视频注入、跨机时钟、Linux实时指标、物理通道与真实3.3替换。模型适用校验只是目录检查，不是模型消费者已经实现。

2026-10-03本轮验证记录：`artifacts/icd_runtime/w1-validation.json`。50条W1测试、4条接口汇总测试与34条选定既有静态回归通过；这是限定范围的离线开发证据，不是全仓库或正式系统验收报告。

同日后续W2.1扩展后的共用库为54条测试，另有38条网关/源及3条全计划台账测试；记录在`artifacts/icd_gateway/w2-validation.json`。原W1报告保留历史结果，不能用其代替目标验收。
