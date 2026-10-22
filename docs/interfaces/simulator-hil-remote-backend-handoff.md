# 模拟器/HIL 异机后端两圈联调交接单

## 已就绪的模拟器/HIL 接口

外部调用应使用[四旋翼 HIL/模拟器最小联调固定配置](quadrotor-hil-external-integration-config.md)
及其完整 JSON；该文件是本轮唯一的创建参数来源。

目标机是 `192.168.100.165`。本次由模拟器/HIL 侧提供三个入口：

| 用途 | 调用方 | 地址 |
|---|---|---|
| 第一圈 HIL 准备 | 3.6 后端 | `http://192.168.100.165:18081/api/hil/preparation/commands` |
| 第二圈模拟器管理 | 3.3 后端 | `http://192.168.100.165:18080/api/simulator/commands` |
| 实时状态遥测 | 3.6 后端 | `ws://192.168.100.165:8765/ws/hil` |

无需由后端启动目标机进程。模拟器/HIL 侧在联调前启动 `hil-core@current`、`hil-prepare`、`hil-gateway`、`input-simulator`、`hil-preparation` 和 `hil-telemetry` 服务。

`8765` 只向 3.6 推送 `STATE_TELEMETRY`，拒绝 `INITIALIZE`、`START` 和 `STOP`。
第一圈唯一由 18081 的 `hil_prepare` 执行；控制请求只按下述两圈路径处理。模拟器记录也不是高频遥测替代品。

## 责任边界

模拟器/HIL 负责固定快照的实际准备、第二圈正式链路执行、HIL 回执/状态/证据和状态遥测输出。3.6 负责业务 Run、第一圈编排、准备上下文持久化、遥测归属和前端发布；3.3 负责第二圈命令入口、准备核验、调用模拟器、轮询记录，以及与 3.6 保存执行关联和回传结果。后端的 REST、数据库、鉴权、页面和 STOMP 实现不在本仓库范围。

共同基线：

```text
baseline_version = HIL-ICD-1.0
baseline_sha256 = 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27
model_id        = quadrotor_hil
```

## 完整两圈流程

1. 3.6 创建业务 `runId`，调用第一圈 [HTTP `hil_prepare`](hil-preparation-management-v1.md)。
2. 3.6 仅在 HIL 返回 `CONFIGURED`、`control_source=NONE`、完整固定快照哈希匹配时，持久化 `runId`、`prepareId`、`configSha256` 和准备结果，并允许进入第二圈。
3. 前端以同一业务 `runId` 向 3.3 发 START。3.3 先向 3.6 查询准备上下文，核对模型、基线和配置快照；不满足时不调用模拟器。
4. 3.3 用当前固定 CANT CreateParams 调用 `simulator_run_create`，保存模拟器 `run_id`、`revision`、后端命令 ID 和管理 `request_id`，并向 3.6 登记同一业务 Run 的执行关联。
5. 登记成功后，3.3 调用 `simulator_run_control/START`。模拟器对 HIL 只核对第一圈已准备的同一配置，再发送正式 Lifecycle START 和固定场景输入。
6. 3.3 每秒调用 `simulator_run_get` 与 `simulator_records_list`；3.6 同时订阅 8765 的新鲜 `STATE_TELEMETRY`，并用已登记关联归入同一业务 `runId`。
7. 前端 STOP 经 3.3 调用 `simulator_run_control/STOP`。模拟器停止本 Run 的场景调度后，对仍在运行的 HIL 发送 Lifecycle `STOP`，并在同一会话读回 `STOPPED`、`control_source=NONE`。3.3 轮询到该真实停止证据后回传给 3.6；3.6 统一发布业务终态。随后 HIL 侧再次执行第一圈准备，恢复 `CONFIGURED`，供下一次业务 Run 使用。

不把 HTTP 202/`ACCEPTED`、报文 `RECEIVED`、WebSocket 已连接或单帧旧遥测当作实际运行成功。实际 START 以 HIL Lifecycle 应用回执或同次运行的新鲜推进状态确认；实际 STOP 以 `HIL_STOP_APPLIED` 和安全状态读回确认。

### STOP 的服务边界

常规第二圈 STOP **不停止** `hil-core@current`、`hil-gateway` 或
`hil-telemetry` 服务进程；它停止的是 HIL 模型生命周期。成功 STOP 后模型步、
`sim_time_s` 和持续 `STATE_TELEMETRY` 不得继续递增，但遥测服务仍可保留 WebSocket
连接、健康日志及最终 `STOPPED` 状态。停止核心进程仅用于维护或紧急隔离，不是 3.3/3.6
联调接口的一部分；那种操作会令下一轮必须重新启动服务并重新执行第一圈准备。

## 3.3 调用模拟器的约定

结构定义是 `docs/interfaces/baseline/input-simulator-api-v0.3.schema.json`。当前部署唯一接受的完整 CreateParams 是 [`config/quadrotor_hil.external.json`](../../config/quadrotor_hil.external.json) 的整个 JSON 对象；历史 `management_create_schema_fixture` 仅是 schema fixture，不得用于本次部署。当前只有四类命令：

| 命令 | 用途 |
|---|---|
| `simulator_run_create` | 校验并固化第二圈固定快照，不启动 HIL |
| `simulator_run_control` / `START` | 异步开始正式执行 |
| `simulator_run_control` / `STOP` | 安全停止正式执行 |
| `simulator_run_get`、`simulator_records_list` | 查询状态、修订号与事实证据 |

`params.api_version` 必须是 `"0.3"`，`request_id` 是幂等键。CREATE 的其余八个字段必须逐字段采用 `quadrotor_hil.external.json` 的完整内容，不得使用旧 fixture、旧 ETHGEN 值或候选文件的哈希。响应中的模拟器 `run_id` 与业务 `runId` 不同，必须由 3.3 保存映射。

固定场景会向 HIL 应用 ID 10 Environment 输入（`wind_n_mps=1`）。3.3 应在 Records 中观察 `APPLIED/SCENARIO_INPUT_APPLIED` 和 `message_id="10"`，随后使用最新 revision 发 STOP。最小 smoke 的 `result=INCOMPLETE` 表示没有完整业务断言裁决，不等同链路失败或业务 PASS。

## 联调前检查与可见结果

模拟器/HIL 侧执行：

```bash
sudo systemctl is-active hil-core@current.service hil-prepare.service hil-gateway.service \
  input-simulator.service hil-preparation.service hil-telemetry.service
sudo ss -ltnup | rg ':(18080|18081|8765|9998)'
sudo journalctl -fu hil-preparation.service -u input-simulator.service \
  -u hil-gateway.service -u hil-telemetry.service
```

后端可见的交付事实是：第一圈 JSON 回执、第二圈 CREATE/GET/Records JSON、8765 上的 `STATE_TELEMETRY`，以及 3.3/3.6 自己保存的业务 Run/命令关联。问题定位时双方按 `runId`、`prepareId`、模拟器 `run_id`、`operation_id`、`request_id` 和 Record cursor 交叉检索。

当前联调固定使用 Linux C-core、UDP 与三条 `vcan` CAN 链路；本轮不要求实体 CAN FD、真实网卡或物理设备资格。

## 固定配置来源与对齐

本轮唯一生效的固定配置由以下文件组成，部署时它们必须与仓库同字节一致：

| 用途 | 权威文件 | 已固定的联调值 |
|---|---|---|
| CREATE 快照（完整 CreateParams） | [`config/quadrotor_hil.external.json`](../../config/quadrotor_hil.external.json) | `quadrotor-minimal-canfd-v1`、`quadrotor-ground-link-v1`、`CANT`、`CANFD_0` |
| 模板选择与资源根 | `config/minimal-integration-template.json` | 只允许上述完整外部 JSON 和 `docs/interfaces/baseline` 下的冻结资源 |
| 模拟器 UDP/CAN 运行参数 | `config/minimal-integration-simulator.json` | 本机 UDP 36100/36101/36102 用于管理/生命周期；场景输入固定 `CANFD_0 -> can0` |
| HIL 网关授权与 CAN 绑定 | `config/minimal-integration-gateway.json` | 相同身份，`CANFD_0/1/2 -> can0/1/2` |

不得使用 `docs/interfaces/baseline/input-simulator-v0.3.examples.json` 的
`management_create_schema_fixture`：它含旧的 `ETHGEN`/`ETH_0`、包/场景引用，必然被
当前部署以 `REFERENCE_INVALID` 拒绝。唯一权威值为上述完整外部 JSON；候选文件中的
全零哈希或 `00f84f99…f1a8` 基线同样不能混入请求。
