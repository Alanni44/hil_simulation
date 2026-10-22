# Simulator/HIL two-loop minimal integration v1

This document covers the simulator and HIL boundary only.  3.3 and 3.6 are
callers; they do not own any implementation described here.

For the remote-backend handoff, endpoint exposure, command sequence and
acceptance criteria, see `simulator-hil-remote-backend-handoff.md`.

Schema-only management and formal-message examples are in
`docs/interfaces/examples/simulator-hil-minimal-integration-v1.json`. They
are validated against the frozen v0.3 assets and intentionally contain no
deployment endpoint, target-session result or claimed physical execution.

## First circle: preparation

`PreparationService.prepare(prepare_id, identity, RunConfigure)` accepts the
frozen ID3 `RunConfigure` message and returns a `PreparationResult` only after
the installed `ModelConfigurationBackend` has read back all of the following:

- the exact configuration, initial state and complete initial-input snapshot;
- `state=CONFIGURED`, unchanged model step, `control_source=NONE` and safe
  outputs;
- model revision, model ID and the baseline/configuration SHA-256 values.

Equal configuration snapshots replay the retained result.  A distinct
snapshot, unavailable resource, unavailable generated state ABI or mismatched
readback is rejected.  Preparation never starts the model or emits ICD test
traffic.

## C-core boundary

The local C-core UDP boundary exposes `get_hil_status`, `start`, `stop`,
`pause`, `resume` and `reset`.  Lifecycle names are `STOPPED`, `CONFIGURED`,
`RUNNING`, `PAUSED` and `FAILED`; the process starts in `STOPPED` and a start
from that state is invalid.  At `STOPPED`/`CONFIGURED`, the active control
source is `none` and outputs are safe.

For generated contracts that declare the verified DWork state mapping, the
local-only `set_model_initial_state` diagnostic may set a complete initial
state while `STOPPED`; `get_hil_status.fields.initial_state` reads it back
directly from generated DWork.  It is not a substitute for `RunConfigure` and
does not enter `CONFIGURED`.

`prepare_model_snapshot` is a stronger local-only diagnostic boundary for the
generated model: while `STOPPED`, it resets the generated model and atomically
writes the contract-owned `flight_control`, `environment`, `fault` and
`parameters` snapshots together with the DWork initial state.  It returns the
runtime to `STOPPED`; `get_hil_status` and `get_icd_snapshot` expose direct
readback.  It deliberately does not own or accept as applied the remaining
RunConfigure extension groups, resources, origin, sensor profile or recording
configuration, so it must never be called `CONFIGURED` or treated as a
successful formal `RunConfigure`.

`get_hil_status` includes `initial_state_abi` and
`full_configuration_abi`.  An ExtU/ExtY-only generated artifact reports both
as false.  The quadrotor generator has a contract-verified DWork
initial-state setter/readback ABI and supports a local `configure` boundary:
the boundary validates the complete generated-input/parameter subset, applies
it with DWork in one stopped-model reset, retains the complete configuration,
clears control ownership and only then enters `CONFIGURED`.  The gateway
combines that retained configuration with direct DWork/status and generated
input readback before emitting an applied receipt; a command acceptance alone
is never sufficient evidence.

If the formal second circle supplies the same frozen configuration while the
target is already `CONFIGURED`, the gateway first reads C-core's retained
configuration and compares it canonically. Only an exact match is allowed;
it returns an applied receipt from direct initial state/input readback without
issuing `configure` again. A different configuration is rejected before any
target write, so the simulator hand-off cannot reset a prepared model.

For a resource-backed request, `StoredRunConfigurationResourceResolver` is
the HIL-side pre-write owner of the completed Terrain/Obstacles bytes.  It
re-hashes the stored bytes, validates their frozen content type, requires the
Terrain origin to equal RunConfigure's origin, and samples the initial N/E
point (bilinear within the declared grid).  The sampled NED ground value is
then passed to the configuration semantic guard.  This establishes a real
resource precondition, and the resolved fact is passed into the C atomic
configuration boundary together with the complete configuration.

## C-core lifecycle boundary

The formal local `stage_lifecycle` command carries an action and the exact
target model step. It is held until that 1 ms boundary and its receipt is
emitted only by the model loop after the transition.
`CcoreLifecycleBackend` uses this receipt plus direct State132/input readback
for `START`, `STOP`, `PAUSE`, `RESUME` and `RESET`; it does not infer
completion from elapsed host time. `STEP` remains `UNSUPPORTED` before any
write because the C target does not yet retain the required per-step State132
evidence. This is an explicit safe limitation, not an approximation of solver
time.

## Second circle: simulator execution

The simulator management endpoint is `/api/simulator/commands`.  The enabled
commands are `simulator_run_create`, `simulator_run_get`,
`simulator_run_control` and `simulator_records_list`.  CREATE only validates
and persists a fixed template/snapshot.  START requires an explicit
`RunExecutionBackend`; it must report `RUNNING` only after retained HIL START
evidence and must report a terminal result using retained STOP/completion
evidence.  Without that backend the public response is `TOOL_UNAVAILABLE`.

Each management response is validated against the frozen v0.3 API schema.
Record entries retain sender facts and references; they are not a telemetry
relay to 3.6.

For a STOP accepted by the minimal formal backend, records are ordered as
`SAFETY/STOP_REQUESTED`, `RESPONSE/HIL_STOP_APPLIED`, then terminal
`OPERATION_RESULT`.  The second fact is emitted only after the formal
Lifecycle STOP receipt; terminal completion also requires a direct ID2 readback
of `STOPPED`, `control_source=NONE` and the requested target model step.
This is software-chain evidence, not a claim that the physical CAN FD or
telemetry paths have been qualified.

If STOP wins before the worker has opened a formal Session, the executor emits
only the retained local `SAFETY/STOP_REQUESTED` and an `INCOMPLETE` terminal
result: it must not open a Session or transmit RunConfigure/START.  A STOP
observed during SessionOpen likewise prevents RunConfigure; one observed after
same-configuration readback prevents Lifecycle.START.  In both cases the
executor closes locally without inventing a HIL stop receipt.
`HIL_STOP_APPLIED` is reserved for the case where a running HIL execution
actually required and returned a formal Lifecycle STOP receipt.

Execution failure provenance remains explicit in the frozen Record shape:
an assertion calls the terminal `OPERATION_RESULT/EXECUTION_FAIL`; transport
or retained-evidence uncertainty is `REJECTED/EVIDENCE_*`; a model/HIL
rejection is `REJECTED/HIL_*`; and a local executor failure is
`TOOL_ERROR/TOOL_*`.  A failed worker always appends a terminal
`OPERATION_RESULT/EXECUTION_FAILED` after its origin fact.  These categories
must not be collapsed into a synthetic PASS or a stopped-target claim.

When `input_simulator.manage` is given `--state-dir`, its bounded RunStore
atomically persists the immutable CREATE snapshots, idempotency responses and
Record cursor history.  On a later process start it does not reconstruct an
old `SourceSession` or worker.  A previously active Run is instead changed to
`COMPLETED/INCOMPLETE` with `last_error.code=EVIDENCE_INCOMPLETE` and one
schema-valid `RECOVERY_INCOMPLETE` terminal record.  READY runs have never
caused HIL traffic and remain READY.
