# 四旋翼 HIL/模拟器最小联调固定配置

日期：2026-10-22
状态：已在当前 HIL/模拟器部署完成两圈烟测；供 3.3、3.6 调用方使用。

本文件采用《固定配置与模拟器 HIL 最小联调待确认事项》的八字段组织方式，
但其权威 JSON 是 [`config/quadrotor_hil.external.json`](../../config/quadrotor_hil.external.json)。
调用方必须原样读取该文件，不得将另一份候选文件的字段混入请求。

## 一、固定创建参数

| 字段 | 冻结值 | 说明 |
|---|---|---|
| `package_ref` | `package_id="quadrotor-minimal-canfd-v1"`、`revision="1"`、哈希 `04c911b3…4fc2` | 当前冻结的本地资源包引用 |
| `scenario_ref` | `scenario_id="quadrotor-ground-link-v1"`、`revision="1"`、哈希 `0abc2a68…4f3a` | 固定 CANT 场景快照 |
| `mode` | `EXPLORE` | 当前服务唯一允许值 |
| `source_binding_ref` | `quadrotor-canfd0-binding` | 固定 CAN FD 0 输入源绑定 |
| `link_ids` | `["CANT"]` | ID10 经 CAN FD 链路发送 |
| `baseline_sha256` | `22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27` | 必须同时出现在顶层和 `source_inputs` |
| `run_configuration` | `quadrotor_hil`、`CANFD_0`、1 ms 步长、80 ms 通信周期 | 仅第一圈允许从 STOPPED 写入 |
| `source_inputs` | `PROTOCOL + SCENARIO`，无 history | ID10 在第 2000 步置风速 1、10000 步恢复 0 |

资源为 `input-simulator-icd-v0.3.json` 与 `input-simulator-canfd-v0.3.dbc`；
完整资源标识、字节数、哈希和场景清理规则均以 JSON 内容为准。

## 二、唯一两圈入口

| 圈次 | 调用方 | 地址 | 允许操作 |
|---|---|---|---|
| 第一圈 | 3.6 | `POST http://192.168.100.165:18081/api/hil/preparation/commands` | `hil_prepare`、`hil_prepare_get` |
| 第二圈 | 3.3 | `POST http://192.168.100.165:18080/api/simulator/commands` | `simulator_run_create`、`simulator_run_get`、`simulator_run_control`、`simulator_records_list` |
| 遥测 | 3.6 | `ws://192.168.100.165:8765/ws/hil` | 只读 `STATE_TELEMETRY` |

8765 拒绝 `INITIALIZE`、`START` 和 `STOP`。第一圈只能使用 HTTP `hil_prepare`。

## 三、调用顺序

1. 3.6 从 JSON 读取完整 `run_configuration`，用同一业务 `run_id` 调用 `hil_prepare`。
2. 只在响应中 `configured=true`、`state="CONFIGURED"`、`control_source="NONE"`、模型/基线/快照哈希全部一致时，允许第二圈。
3. 3.3 使用 JSON 的全部八个字段创建 `simulator_run_create`；每次管理调用生成新的 `request_id`。
4. 3.3 使用返回的 `run_id` 和当前 `revision` 发一次 `START`。未完成第一圈时，HIL 会拒绝第二圈且不会发送 TX。
5. 记录中出现 `APPLIED/SCENARIO_INPUT_APPLIED/message_id="10"` 后，以最新 revision 发 `STOP`；须观察 `RESPONSE/HIL_STOP_APPLIED`，并确认最终 HIL 状态为 `STOPPED`、`control_source="NONE"`。

`ACCEPTED`、HTTP 成功、WebSocket 已连接和 `RECEIVED` 都不是实际运行/停止依据。

## 四、已验证范围

本部署使用既有 `can0`（当前为 `vcan`）完成 CANT/CANFD_0 输入；会话、配置、
生命周期和状态继续使用 UDP。CANT 版本须在部署后重新完成 CREATE → START → ID10
实际应用 → STOP 烟测；STOP 后模型生命周期应先为 `STOPPED`，再由下一次第一圈准备恢复
`CONFIGURED`。此过程不退出 `hil-core@current` 进程；停止后模型时间与持续状态遥测不应再
推进，遥测服务本身仍保持可连接。这不是实体 CAN FD 或物理设备资格。

不得使用候选文件中的全零哈希或 `00f84f99…f1a8` 基线；它们与当前冻结基线不一致。
候选中的场景名称、时序和 CANT 绑定已落实到本 JSON；哈希为本地冻结内容计算值。
