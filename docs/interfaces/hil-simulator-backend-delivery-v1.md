# HIL/模拟器两圈联调后端交付单 v1

状态：已部署并实测（2026-10-25）。本文件是 3.6/3.3 后端对接 HIL 与输入模拟器的
可执行交付说明；固定创建参数的权威来源仍是
[`config/quadrotor_hil.external.json`](../../config/quadrotor_hil.external.json)。

## 1. 地址、角色与边界

| 调用方 | 用途 | 地址 | 操作 |
|---|---|---|---|
| 3.6 | 第一圈：实时状态、复位、准备 | `POST http://192.168.100.165:18081/api/hil/preparation/commands` | `hil_status_get`、`hil_reset`、`hil_prepare`、`hil_prepare_get` |
| 3.3 | 第二圈：创建、启动、停止、证据查询 | `POST http://192.168.100.165:18080/api/simulator/commands` | `simulator_run_create`、`simulator_run_get`、`simulator_run_control`、`simulator_records_list` |
| 3.6 | 只读实时遥测 | `ws://192.168.100.165:8765/ws/hil` | `STATE_TELEMETRY` |

请求和响应均为 UTF-8 JSON，`Content-Type: application/json`。8765 只读，不能发送
START、STOP、RESET 或初始化指令。后端不得直接访问 C-core UDP `9997`。

术语：3.6 的业务 `run_id` 与 3.3/模拟器返回的 `run_id` 不是同一个值，必须持久化映射。

## 2. 固定配置与不可变约束

第二圈 CREATE 必须使用 `config/quadrotor_hil.external.json` 的**整个 JSON 对象**；不得
复制历史 fixture、补默认字段或混入候选配置。当前固定身份：

```text
model_id        = quadrotor_hil
baseline_sha256 = 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27
input channel   = CANFD_0
link            = CANT（既有 vcan can0）
```

第一圈 `hil_prepare.params.run_configuration` 仅取该 JSON 的 `run_configuration` 完整对象。
配置快照哈希为 RFC8785/JCS 规范化后的 SHA-256：

```text
5220aa06d6ddb3948bfdda76a91d6ebda4c3550436cbbb6c6da78f39ffa3ca8f
```

## 3. 第一圈：3.6 调用规范

### 3.1 实时状态查询：`hil_status_get`

该命令每次读取 C-core 当前状态；不能用 `hil_prepare_get` 的冻结结果替代。

```json
{
  "cmd": "hil_status_get",
  "params": {
    "api_version": "1.0",
    "request_id": "3.6-status-001"
  }
}
```

成功示例：

```json
{
  "kind": "HIL_PREPARATION_RESPONSE",
  "api_version": "1.0",
  "request_id": "3.6-status-001",
  "cmd": "hil_status_get",
  "status": "SUCCESS",
  "code": "OK",
  "message": "HIL current status",
  "timestamp": "2026-10-25T10:17:02.011Z",
  "data": {
    "model_id": "quadrotor_hil",
    "model_revision": "2",
    "state": "STOPPED",
    "control_source": "NONE",
    "model_step": "44348",
    "sim_time_us": "44348000",
    "fresh": true
  },
  "error": null
}
```

`model_revision`、`model_step`、`sim_time_us` 均为 JSON string。只有
`fresh=true` 且 `status=SUCCESS` 才是当前状态事实。

### 3.2 明确复位：`hil_reset`

STOP 不清零步数；上一 Run 成功停止但 `model_step != "0"` 时，必须先 RESET。

```json
{
  "cmd": "hil_reset",
  "params": {
    "api_version": "1.0",
    "request_id": "3.6-reset-request-001",
    "reset_id": "3.6-reset-001",
    "run_id": "已停止的3.6业务RunId"
  }
}
```

调用前条件：实时 C-core 状态必须为 `STOPPED` 且 `control_source="NONE"`。模型为
`RUNNING`、`PAUSED`、`RESETTING`、控制权未释放、状态不完整或复位失败时，接口返回
HTTP `409`、`code="STATE"`；后端不得继续准备或启动。

成功响应要求：顶层 `request_id`、`data.reset_id`、`data.run_id` 三者均与本次请求相同，
且必须同时满足 `state="STOPPED"`、`control_source="NONE"`、`model_step="0"`、
`sim_time_us="0"`、`reset=true`。RESET 真实恢复最近一次成功 RunConfigure 的初始输入、
参数和初始状态，清空控制权、任务与待执行输入；旧 Run 的证据和遥测历史不删除。

### 3.3 配置准备：`hil_prepare`

仅在实时状态已经 `STOPPED/NONE/model_step=0` 时调用：

```json
{
  "cmd": "hil_prepare",
  "params": {
    "api_version": "1.0",
    "request_id": "3.6-prepare-request-001",
    "prepare_id": "3.6-prepare-001",
    "run_id": "新的3.6业务RunId",
    "run_configuration": "完整读取 quadrotor_hil.external.json.run_configuration"
  }
}
```

后端必须验证：

```text
status=SUCCESS
data.configured=true
data.state=CONFIGURED
data.control_source=NONE
data.model_step="0"
data.model_id=quadrotor_hil
data.config_sha256=5220aa06…ffa3ca8f
data.baseline_sha256=22163dc…4fe8a27
```

成功后持久化：业务 `run_id`、`prepare_id`、请求/响应全文、`config_sha256`、
`baseline_sha256`、`model_revision`。`hil_prepare_get` 只能查询同一服务进程保存的准备结果，
不能作为实时状态来源。

### 3.4 第一圈幂等与错误处理

- `request_id` 是幂等键：网络超时或断连时，以**相同请求体和相同 request_id**重试。
- `reset_id` 只能关联一个业务 Run；不得以相同 ID 复用到另一 Run。
- HTTP `409/STATE`：读取 `hil_status_get`，不进入下一阶段。
- HTTP `400`：请求模式、固定配置或哈希错误，修正请求后使用新的 `request_id`。
- HTTP `422`：C-core/资源/读回无法形成可信事实，停止编排并保留响应排障。

## 4. 第二圈：3.3 调用规范

前置条件：3.6 已持久化第一圈成功事实，且模型、基线、配置哈希和 `model_step="0"`
均匹配。否则 3.3 不得调用模拟器。

1. 读取 `quadrotor_hil.external.json` 整个对象，添加：

```json
{
  "cmd": "simulator_run_create",
  "params": {
    "api_version": "0.3",
    "request_id": "3.3-create-001",
    "...": "quadrotor_hil.external.json 的全部八个固定字段"
  }
}
```

2. 轮询 `simulator_run_get`，只在 `state="READY"`、`available_actions` 含 `START` 时继续。
3. 使用 CREATE 返回的模拟器 `run_id` 与其当前 `revision` 发送：

```json
{
  "cmd": "simulator_run_control",
  "params": {
    "api_version": "0.3",
    "request_id": "3.3-start-001",
    "run_id": "模拟器run_id",
    "expected_revision": "当前revision",
    "action": "START"
  }
}
```

`ACCEPTED/QUEUED` 只说明异步操作已提交，不等于模型正在运行。3.3 必须轮询
`simulator_run_get`、`simulator_records_list`，3.6 同时消费 8765 新鲜遥测。

固定场景会在 CANT/CANFD_0 上实际应用 ID10 环境输入。成功依据是 Records 中存在：

```text
kind=APPLIED
reason_code=SCENARIO_INPUT_APPLIED
message_id="10"
```

## 5. 停止与下一轮流程

3.3 使用最新 `revision` 调用 `simulator_run_control/STOP`。实际停止仅在以下事实同时成立时确认：

```text
Records: RESPONSE / HIL_STOP_APPLIED
HIL realtime status: STOPPED / NONE
```

若 Records 标识 `HIL_EMERGENCY_STOP_APPLIED`，表示模拟器正式会话无法确认 STOP 后本机
C-core safety STOP 已读回；它仍是模型已经停止的事实，但必须保留该不同证据类型。

停止后按以下顺序启动下一轮：

```text
STOP 证据确认
→ hil_status_get
→ model_step 非零则 hil_reset
→ 确认 STOPPED / NONE / 0 / 0
→ hil_prepare
→ 确认 CONFIGURED / NONE / 0
→ simulator_run_create
→ START
```

不得通过重启 `hil-core`、直接 UDP 命令或假设 STOP 自动归零来跳过该顺序。

## 6. 本次部署实测结果

2026-10-25 已完成非零步实测：

```text
hil_status_get: STOPPED / NONE / model_step=44348 / sim_time_us=44348000
hil_reset:      STOPPED / NONE / model_step=0     / sim_time_us=0
hil_prepare:    CONFIGURED / NONE / model_step=0  / model_revision=2
```

因此当前目标已位于 `CONFIGURED/NONE/model_step=0`，可由完成第一圈上下文登记的后端发起
第二圈 CREATE/START。

## 7. 后端历史问题对照与交付附件

| 后端曾提出的问题 | 本交付中的答案 |
|---|---|
| 第一圈真实入口、请求封装、必填参数、响应与快照哈希 | 第 1、2、3 节；完整字段级定义见附件 A |
| `hil_prepare_get` 能否作为实时状态 | 不能；第 3.1 节的 `hil_status_get` 才是实时 C-core 读回 |
| STOP 后非零步导致下一轮准备失败 | 第 3.2、5 节：显式 `hil_reset` 后确认归零再准备 |
| RESET 响应如何关联本次请求 | 第 3.2 节：顶层 `request_id` 与 data 中 `reset_id`、`run_id` 三者必须匹配 |
| 固定部署模板的完整 CreateParams、CANT/CANFD_0 支持 | 第 2、4 节及附件 B；JSON 是唯一完整机器可读参数来源 |
| ICD/DBC 的文件名、资源标识、字节数和 SHA-256 | 附件 B 的 `source_inputs.protocol.resources`；资源本体见附件 C |
| 模拟器 CREATE/START/STOP 的异步完成与证据判断 | 第 4、5 节 |

发送给后端时，请同时提供以下文件，不能只复制本文中的示例片段：

| 附件 | 文件 | 用途 |
|---|---|---|
| A | [hil-preparation-management-v1.md](hil-preparation-management-v1.md) | 第一圈全部字段、HTTP 状态码、完整 `hil_prepare`/`hil_prepare_get` 示例 |
| B | [quadrotor_hil.external.json](../../config/quadrotor_hil.external.json) | 第二圈完整且唯一允许的 CreateParams；同时包含资源引用、哈希和场景输入 |
| C | [input-simulator-icd-v0.3.json](baseline/input-simulator-icd-v0.3.json) 与 [input-simulator-canfd-v0.3.dbc](baseline/input-simulator-canfd-v0.3.dbc) | JSON 中声明的 ICD/DBC 冻结资源；接收方可据 JSON 的 `size_bytes`、`sha256` 校验文件 |
| D | [simulator-hil-remote-backend-handoff.md](simulator-hil-remote-backend-handoff.md) | 双方责任边界、记录证据和异常 STOP 语义 |

附件 B 的顶层八字段和 `run_configuration` 都是契约内容：3.3 读取其整个对象创建
`simulator_run_create`；3.6 仅提取其中 `run_configuration` 发送 `hil_prepare`。附件 C 的
文件存在并不替代 HIL 侧解析/哈希核验；后端以 CREATE/prepare 的真实响应和记录为准。
