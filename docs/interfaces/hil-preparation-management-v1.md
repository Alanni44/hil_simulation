# HIL 第一圈准备管理接口 v1

这是 3.6 后端调用 HIL 的第一圈 HTTP 接口。它只负责把已冻结的
`quadrotor_hil` 配置写入 HIL 并验证读回；不启动模型、不推进模型步、不发送
场景输入，也不替代 3.3 到输入模拟器的第二圈接口。

当前目标机：

```text
POST http://192.168.100.165:18081/api/hil/preparation/commands
Content-Type: application/json
```

没有 URL 参数、鉴权头或额外的外层包装。请求与响应均为 UTF-8 JSON，不能带
BOM，JSON 对象中不能有重复键。请求必须带 `Content-Length`，最大为 1 MiB；服务
返回 `Content-Type: application/json`、`Cache-Control: no-store`。当前部署未配置认证，
调用方应通过受控网络限制该端口访问。

第一圈的唯一写入口是本 HTTP 接口。`ws://192.168.100.165:8765/ws/hil` 只发布
`STATE_TELEMETRY`，拒绝 `INITIALIZE`、`START`、`STOP`，不能用它替代本接口。

## 固定快照与哈希

请求中的 `params.run_configuration` 必须是
[`config/quadrotor_hil.external.json`](../../config/quadrotor_hil.external.json) 中的
**完整** `run_configuration` 对象。外部配置文件的其他七个顶层业务字段由第二圈
`simulator_run_create` 使用，不能塞进第一圈的 `run_configuration`，也不能删减、
补默认值或覆盖任一字段。

当前冻结值如下：

| 项目 | 固定值 |
|---|---|
| 模型 | `quadrotor_hil` |
| 输入通道 | `CANFD_0` |
| 快照哈希算法 | `SHA-256(RFC8785(run_configuration) 的 UTF-8 字节)` |
| `config_id` / `config_sha256` | `5220aa06d6ddb3948bfdda76a91d6ebda4c3550436cbbb6c6da78f39ffa3ca8f` |
| 基线 | `22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27` |

`RFC8785` 指 JSON Canonicalization Scheme (JCS)：对象成员按 JCS 规则排序、采用其
规定的数字和字符串编码、无空白，再对结果 UTF-8 字节做 SHA-256。它不是源文件
文本的 SHA-256，也不包含 `cmd`、`request_id`、`prepare_id`、`run_id` 或 HTTP 头。
当前规范化字节长度为 `2552`。

例如，Python 调用方可用与服务端等价的算法校验：

```python
import hashlib, json, jcs

external = json.load(open("quadrotor_hil.external.json", encoding="utf-8"))
snapshot = jcs.canonicalize(external["run_configuration"])
assert hashlib.sha256(snapshot).hexdigest() == (
    "5220aa06d6ddb3948bfdda76a91d6ebda4c3550436cbbb6c6da78f39ffa3ca8f"
)
```

服务在内部将该对象封装为下列固定的 ID3 `RunConfigure`，并只接受消息号 `3`：

```json
{
  "message_id": 3,
  "header": {
    "session_id": 1,
    "sequence": 1,
    "target_step": 0,
    "transaction_id": 1,
    "valid_for_ms": 1000
  },
  "payload": "params.run_configuration 的完整对象"
}
```

调用方不要提交这层 ID3 外壳；HTTP 接口会自行生成它。

若 HIL 已处于 `CONFIGURED`，第一圈只会在 C-core 已读回并证明完整快照与本请求
规范化后完全相同的前提下成功；该路径只读回核验，不会再次写入配置或推进模型。
配置不同、HIL 正在 `RUNNING`/`PAUSED` 或读回不一致时仍会被拒绝。

## 通用报文封装

顶层对象只能有 `cmd` 与 `params` 两个键，不能有 `data`、`type`、`token` 等扩展键。
`params` 同样是封闭对象；缺字段、额外字段或 `api_version` 不等于字符串 `"1.0"`
都会被拒绝。

| 字段 | 类型 / 约束 | 含义 |
|---|---|---|
| `cmd` | string | 仅 `hil_prepare` 或 `hil_prepare_get` |
| `params.api_version` | string，固定 `"1.0"` | 接口版本 |
| `params.request_id` | 1–128 字符 string | HTTP 幂等键；一次逻辑请求固定不变 |
| `params.prepare_id` | 1–128 字符 string | 第一圈准备结果标识，由 3.6 持久化 |
| `params.run_id` | 1–128 字符 string | 仅 `hil_prepare` 必填；3.6 的业务关联 ID，原样回显 |
| `params.run_configuration` | object | 仅 `hil_prepare` 必填；上述冻结完整对象 |

同一 `request_id` 重传必须是字节语义相同的同一 JSON 请求（字段顺序无关，JSON
值必须相同），服务会返回首次保存的原响应；以同一 ID 改变任一字段会得到
`IDEMPOTENCY_CONFLICT`。服务最多保留 512 个幂等请求。网络超时或连接中断时，
应以原始请求和原 `request_id` 重试，不能生成新的 ID。

## `hil_prepare`

3.6 创建业务 `run_id` 后调用。以下是可直接生成真实请求的 JSON；其中
`run_configuration` 取自权威配置文件，而非示意字段：

```json
{
  "cmd": "hil_prepare",
  "params": {
    "api_version": "1.0",
    "request_id": "3.6-prepare-request-001",
    "prepare_id": "3.6-prepare-001",
    "run_id": "3.6-business-run-001",
    "run_configuration": "读取 config/quadrotor_hil.external.json 的 run_configuration 完整 JSON 对象"
  }
}
```

例如使用 `jq` 组装请求（`run_configuration` 直接保留为完整嵌套对象）：

```sh
jq --arg request_id '3.6-prepare-request-001' \
   --arg prepare_id '3.6-prepare-001' \
   --arg run_id '3.6-business-run-001' \
   '{cmd:"hil_prepare",params:{api_version:"1.0",request_id:$request_id,prepare_id:$prepare_id,run_id:$run_id,run_configuration:.run_configuration}}' \
   config/quadrotor_hil.external.json \
| curl --fail-with-body --request POST \
    --header 'Content-Type: application/json' \
    --data-binary @- \
    http://192.168.100.165:18081/api/hil/preparation/commands
```

成功时 HTTP `200`，响应结构固定如下。这是当前冻结快照的可解析线缆示例：
`request_id`、`prepare_id`、`run_id` 由调用方决定，`timestamp` 由服务在实际处理时
生成，`model_revision` 是运行时读回值；调用方不能把这些四项与示例字面值比较。

```json
{
  "kind": "HIL_PREPARATION_RESPONSE",
  "api_version": "1.0",
  "request_id": "3.6-prepare-request-001",
  "cmd": "hil_prepare",
  "status": "SUCCESS",
  "code": "OK",
  "message": "HIL prepared",
  "timestamp": "2026-10-22T12:16:13.000Z",
  "data": {
    "run_id": "3.6-business-run-001",
    "prepare_id": "3.6-prepare-001",
    "model_id": "quadrotor_hil",
    "config_id": "5220aa06d6ddb3948bfdda76a91d6ebda4c3550436cbbb6c6da78f39ffa3ca8f",
    "config_sha256": "5220aa06d6ddb3948bfdda76a91d6ebda4c3550436cbbb6c6da78f39ffa3ca8f",
    "baseline_sha256": "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27",
    "model_revision": "1",
    "model_step": "0",
    "state": "CONFIGURED",
    "control_source": "NONE",
    "configured": true
  },
  "error": null
}
```

`model_revision` 与 `model_step` 是字符串，不能按 JSON number 处理。只有
`configured=true`、`state="CONFIGURED"`、`control_source="NONE"`，且四个固定标识
（`model_id`、`config_sha256`、`baseline_sha256`、`model_step="0"`）都符合预期，
3.6 才能记录第一圈成功并放行第二圈。

## `hil_prepare_get`

用于同一服务进程内查询已成功的 `prepare_id`，不重新写配置：

```json
{
  "cmd": "hil_prepare_get",
  "params": {
    "api_version": "1.0",
    "request_id": "3.6-prepare-query-001",
    "prepare_id": "3.6-prepare-001"
  }
}
```

成功时 HTTP `200`，`data` 与对应 `hil_prepare` 的 `data` 完全相同，其他字段为：

```json
{
  "kind": "HIL_PREPARATION_RESPONSE",
  "api_version": "1.0",
  "request_id": "3.6-prepare-query-001",
  "cmd": "hil_prepare_get",
  "status": "SUCCESS",
  "code": "OK",
  "message": "HIL preparation result",
  "timestamp": "2026-10-22T12:16:14.000Z",
  "data": "与 hil_prepare 成功响应完全相同的对象",
  "error": null
}
```

查询结果仅在本服务进程内保留。服务重启后的 `404/NOT_FOUND` 只说明该内存查询缓存
没有保留，不能据此断言 HIL 已失效；3.6 应持久化首次成功的完整 `data`，必要时以
原固定快照再次调用 `hil_prepare`。

## 失败与 HTTP 状态

业务层失败都使用 `HIL_PREPARATION_RESPONSE`：

```json
{
  "kind": "HIL_PREPARATION_RESPONSE",
  "api_version": "1.0",
  "request_id": "3.6-prepare-request-001",
  "cmd": "hil_prepare",
  "status": "REJECTED",
  "code": "REFERENCE",
  "message": "RunConfigure differs from the fixed first-circle snapshot",
  "timestamp": "2026-10-22T12:16:13.000Z",
  "data": null,
  "error": {
    "code": "REFERENCE",
    "retryable": false
  }
}
```

| HTTP 状态 | 情况 |
|---|---|
| `200` | 命令成功 |
| `400` | `SCHEMA`、`REFERENCE`、`BASELINE`、`MODEL` |
| `404` | `NOT_FOUND`（未保留的 `prepare_id`） |
| `409` | `IDEMPOTENCY_CONFLICT`、`DUPLICATE`、`STATE` |
| `422` | 其他业务拒绝，例如 `TARGET_MISSING`、`EXPIRED`、`BUSINESS_FAILED` |
| `411` / `413` / `415` | 缺 `Content-Length` / 超过 1 MiB / 非 `application/json` |

若请求甚至没有可用的 `cmd`、`params.request_id`，服务无法封装业务响应，直接返回
`400 {"error":"invalid_request","code":"SCHEMA"}`。调用方不应仅以 HTTP 成功或
WebSocket 连接成功作为第一圈就绪条件，必须检查上面的成功断言。

## 与第二圈衔接

3.6 必须持久化 `run_id`、`prepare_id`、完整成功 `data`、`config_sha256` 与
`baseline_sha256`。3.3 以同一业务 `run_id` 建立执行关联，并使用
[`quadrotor-hil-external-integration-config.md`](quadrotor-hil-external-integration-config.md)
规定的全部八字段调用第二圈。第二圈不得重新初始化或替换本快照。
