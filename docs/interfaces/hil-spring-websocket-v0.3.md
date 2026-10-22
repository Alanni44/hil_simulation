# HIL–Spring WebSocket V0.3（已停止作为第一圈入口）

> 当前两圈联调中，8765 仅发布 `STATE_TELEMETRY`，拒绝 `INITIALIZE`、`START` 和
> `STOP`。第一圈唯一入口是 [HIL 第一圈准备管理接口](hil-preparation-management-v1.md)。
> 下方历史 `INITIALIZE` 描述不再是可用接口，不得用于联调。

HIL Python is the WebSocket server. Spring connects to `ws://<HIL_LAN_IP>:8765/ws/hil`; the real HIL address is deployment configuration, not a source-code constant.

Each UTF-8 text frame holds exactly one JSON object. HIL publishes the latest fresh C-core NED state at the configured target rate (50 Hz by default), without a Spring `get_state` poll. The text-frame receive limit is 1 MiB, which is also the bound for `create_params_json`.

## First circle: INITIALIZE is preparation, not START

When `spring_ws.initialize.enabled` is true, 8765 accepts the first-circle
`INITIALIZE` message even though `spring_ws.allow_commands` remains false:

```json
{"type":"INITIALIZE","request_id":"6c1d0e0a-6f0e-4a0e-9d63-5a0f0e0a6f0e","data":{"model_id":"quadrotor_hil","config_id":"snapshot-20261021-01","config_sha256":"<64 lowercase hex>","create_params_json":"<complete create-params JSON text>"}}
```

`config_sha256` is SHA-256 over the UTF-8 bytes of the raw
`create_params_json` text. It is not the hash of the outer frame and it is not
a substitute for `baseline_sha256`.

HIL validates the text before preparing the actual model:

- the raw text hash must equal `config_sha256`;
- the eight `CreateParams` fields must be present and structurally valid;
- `run_configuration.model_id` must equal `data.model_id`;
- `source_inputs.baseline_sha256`, when present, must equal `baseline_sha256`;
- all-zero package/scenario resource hashes are rejected as unresolved placeholders;
- `run_configuration` must equal the fixed first-circle snapshot owned by the
  preparation service, and the declared `baseline_sha256` must equal the HIL
  contract baseline.

HIL delegates the actual configuration to the loopback preparation service
(`http://127.0.0.1:18081/api/hil/preparation/commands`, `hil_prepare`). That
service owns the single C-core configuration writer, the frozen template and
the snapshot replay rules, so INITIALIZE never performs a second configuration
write and never resets an already prepared model. The same 18081
`hil_prepare`/`hil_prepare_get` commands remain available to callers that do
not use INITIALIZE; one business Run must use one path consistently, never
both.

A successful preparation returns a live C-core readback of `CONFIGURED`,
control source `NONE`, model step unchanged and the complete configuration
read back. 8765 additionally observes telemetry after the prepare call: a
`CONFIGURED` sample confirms readiness, while a non-`CONFIGURED` lifecycle
makes readiness fail once it persists for a few publish intervals, so a
sample generated just before the configure cannot falsely fail the request.

```json
{"type":"INITIALIZE_RESULT","request_id":"6c1d0e0a-6f0e-4a0e-9d63-5a0f0e0a6f0e","data":{"ready":true,"lifecycle":"CONFIGURED","model_id":"quadrotor_hil","config_id":"snapshot-20261021-01","config_sha256":"<same verified hash>"}}
```

Failure keeps the same request identity and never carries a `CONFIGURED`
lifecycle:

```json
{"type":"INITIALIZE_RESULT","request_id":"6c1d0e0a-6f0e-4a0e-9d63-5a0f0e0a6f0e","data":{"ready":false,"model_id":"quadrotor_hil","config_id":"snapshot-20261021-01","config_sha256":"<verified hash>","reason":"REFERENCE: RunConfigure differs from the fixed first-circle snapshot"}}
```

Rules:

- A byte-identical retry of the same `request_id` replays the retained result
  without preparing again. A replay of `ready=true` first re-checks fresh
  telemetry and fails if the model has since left `CONFIGURED`, so a late
  duplicate cannot revive a stale readiness claim. The same `request_id` with
  different bytes, or an identifier already used by a `COMMAND`, is rejected
  as a conflict.
- A new request while the model is `RUNNING`, `PAUSED` or `RESETTING` is
  rejected; preparation must not reset an executing model.
- Unknown, duplicate or late results never make a new Run ready. Connection
  success, HTTP reachability and `OPERATION_RESULT.SUCCEEDED` are not
  readiness evidence.
- INITIALIZE does not advance a model step and does not send test stimulus.
  The second circle creates and starts the run through the 3.3 simulator
  management API; 3.6 does not send START/STOP on this WebSocket.

## Legacy COMMAND path

For legacy deployments that explicitly set `spring_ws.allow_commands: true`,
the old START/STOP behavior below applies. It is not the two-circle control
path; the deployed two-circle configuration keeps it false.

```json
{"type":"COMMAND","request_id":"req-start-001","data":{"action":"START"}}
```

```json
{"type":"COMMAND_RESULT","request_id":"req-start-001","data":{"accepted":true,"reason":"accepted"}}
```

`accepted: true` only means the local lifecycle request was accepted. It is not evidence that a model has started or stopped; Spring observes actual subsequent state data for that purpose.

## Telemetry

```json
{"type":"STATE_TELEMETRY","data":{"sequence":"12000","sim_time_s":12.0,"lifecycle":"RUNNING","north_m":15.2,"east_m":2.1,"down_m":-3.0}}
```

`sequence` is a decimal string so JavaScript does not lose uint64 precision.
`lifecycle` may be `RUNNING`, `PAUSED`, `RESETTING`, `ENDED`, `CONFIGURED`,
`STOPPED` or `FAILED`. After a real stop HIL publishes `STOPPED` or `ENDED`;
a control `ACCEPTED` is not a stop fact. Optional model fields are omitted
rather than synthesized. In particular V2 source frames do not gain V3
angular-acceleration or wind values. `timestamp_ms`, when present, is HIL's
real send wall-clock timestamp and is not simulation time.

`source_run_id` is an optional HIL adaptation field for deployments that have
a real mapping from the simulator execution. The current single-active
compatibility mode does not emit it and does not accept a guessed value; if a
deployment later requires it, it must come from a verified formal-session
mapping.

The pre-existing management WebSocket remains separate; it is not part of this contract.
