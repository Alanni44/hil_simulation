# W2.3 Shared Lifecycle And Control Guards Implementation Plan

> **For agentic workers:** Execute inline with executing-plans and TDD in the current approved checkout. Read-only review required. No new branch, commit, OS-specific core, or production test consumer.

**Goal:** Implement the shared semantic decisions for lifecycle, ControlOwner, and initial snapshot safety before an actual C consumer can execute them.

**Architecture:** An immutable ModelView is supplied by the actual consumer boundary, not inferred from SessionOpen, incoming requests, timers, or legacy accepted receipts. Pure guards validate full frozen business messages and return immutable required transitions/operations without mutating model state or claiming application. The existing network gateway stays fail-closed until actual consumer integration and evidence are available.

**Tech Stack:** Python3.12 common library, frozen Contract validation, dataclasses/math, unittest. No extra dependency, new ICD field or Linux/Windows fork.

## Global Constraints

- Lifecycle expected_state must match; START CONFIGURED->RUNNING, PAUSE RUNNING->PAUSED, RESUME PAUSED->RUNNING, STOP RUNNING/PAUSED/CONFIGURED->STOPPED, RESET PAUSED/STOPPED->CONFIGURED. STEP is PAUSED-only1..1000 sequential1ms, staysPAUSED, controlNONE, no physical closed loop.
- RUNNING requests target ahead1..1000, frozen lifecycle/ControlOwner requests target exactly current step. Decisions must be revalidated at the actual safety boundary, not treated as completion.
- STOP/RESET/RESUME require queue clearing; RESET restores complete initial snapshot and new session; RESUME preserves state but requires fresh session. Pause/stop/reset/control handover require actual safe outputs and control revocation as indicated, not merely local flags.
- ControlOwner producing lanes require roleCONTROLLER; INTERNAL_CONTROLLER requires a declared actual internal producer, not a STIMULUS network writer. The STIMULUS sender ofControlOwner does not gain the selected producer's role. NONE does not grant writer permission. DEMO_MISSION quad-only; declared controller/source/lane and actual capabilities must agree. Grant/switch is PAUSED,100ms, safe values and queue clear first.
- Initial snapshots must match model, have all schema fields, safe control zeros, valid quaternion norm within1e-6, consistent ground/airborne, static quad/hex. Terrain-dependent ground must come from resolver; missing resolution isRESOURCE, not implicit0. Actual resource/origin/physical/ABI readiness remains separate.
- Actual C code currently resets toRUNNING, has one replaceable pending snapshot, permits source selection outsidePAUSED, and exempts demo timeout. These are Linux fixes, not accepted aliases for this ICD.
- Decisions are not APPLIED/CONSUMED, Status or E2. No test ModelView is registered as a production consumer. CompleteW2/M2 and the full active goal stay incomplete.
- Append stage/Linux/common gaps to the single ledger, retaining41 original responsibilities.

## Task1: Lifecycle Semantic Gate

Create`icd_gateway/semantic_guards.py`, `tests/icd_gateway/test_semantic_guards.py`.
Interfaces: frozen `ModelView(model_id,state,model_step,max_duration_steps,control_source,physical_closed_loop,configured_once)`; `SemanticGuards(contract).lifecycle(message,view)` -> frozen `LifecycleDecision(next_state,target_step,steps,clear_queues,safe_outputs,revoke_control,new_session,restore_initial)`.

- [x] Write failing module availability, all action/state pairs, expected-state mismatch, frozen/running step bounds, bool/range validation, exact sequentialSTEP and physical/control restrictions tests.
- [x] Observe missing module with`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_semantic_guards.py -v`.
- [x] Implement semantic validation without storing or advancing model state; eachSTEP output tuple is exact1ms boundaries, not one large step.
- [x] Rerun focused tests and existing queue/session guards.

Test anchor:
```python
decision = guards.lifecycle(step_message, paused_view)
assert decision.steps == (11, 12, 13)
assert decision.next_state == 'PAUSED'
assert decision.safe_outputs
```

## Task2: ControlOwner Semantic Gate

Same code/tests. Interface: `control_owner(message,view,declared_controller,controller_session_roles,internal_controller_ready)` -> frozen `OwnerDecision(source,role,mode,input_lane,lease_ms,clear_queues,safe_outputs,revoke_control)`; actual producer session is supplied independently by the authorized deployment/consumer, not auto-granted by STIMULUS sender.

- [x] Add failing source/model/lane/role combinations, missing internal producer, unsupported declared source, external producer role, running handover, NONE revocation and strict complete-schema tests.
- [x] Implement decisions requiring actual safe outputs and queue clear before grant; never allocate lease/writer in this pure guard.
- [x] Verify all combinations and absence of model application/evidence behavior.

Test anchor:
```python
owner = guards.control_owner(owner_message, paused_view,
    declared_controller='PX4_SITL', controller_session_roles=('CONTROLLER',),
    internal_controller_ready=False)
assert owner.lease_ms == 100
assert owner.safe_outputs and owner.clear_queues
```

## Task3: Initial State And Configure Safety

Same code/tests. Interface: `run_configure(message,view,terrain_ground_down=None)` -> immutable canonical complete configure bytes after input safety validation. `initial_state(message,view,ground_down)` -> immutable canonical initial-state bytes. Caller must resolve actual terrain at requested point; do not mark resources/ABI/physical ready here.

- [x] Add failing cross-model initial branch, nonzero safe controls, quaternion/ground/airborne consistency, static multirotor, required terrain sample, STOPPED/initialCONFIGURED configure, initial-state state gate and explicit fixed-wing velocity preservation tests.
- [x] Implement checks without filling defaults, normalizing quaternion, clamping values or writing state outputs; preserve complete explicit initial fault/parameter/environment/system/sensor snapshots for later actual RESET.
- [x] Rerun all semantic tests, then read-only review and fix reproduced findings with red/green tests.

## Task4: Evidence And Handoff

Modify`icd_gateway/README.md`, overall progress; append`linux-development-backlog.md`; create`artifacts/icd_gateway/w2-3-validation.json`.

- [x] Run single common runner,85goldens, staticQA and34 selected existing static regressions, dependencies/compile checks.
- [x] Append L-004/L-010 precise C incompatibilities and actual consumer boundary/revalidation obligations; L-002 same-source Linux qualification remains required.
- [x] Verify41 tasks and14 exact interface sources, record exact counts and pending actual model/consumer/lease/evidence work. No automatic commit/merge or complete-goal claim.

## Scoped Result

2026-10-03:23 semantic tests pass; the single common runner passes157 tests (54 runtime,96 gateway/source,3 ledger,4 single-file contract).85 golden fragments/800RAW, staticQA10446/2427,34 selected existing static regressions, pip/compile and14 byte-exact source checks pass. Read-only review reported no actionable scoped findings; subsequent huge-integer ground input regression reproduced OverflowError and now rejects RESOURCE with red/green evidence. Report:artifacts/icd_gateway/w2-3-validation.json.

This closes only the pure semantic guard package. Actual consumer execution, fresh-boundary revalidation, lifecycle/reset/session effects, control lease/safety, resource/ABI qualification and real probes remain unimplemented or unverified.17 Linux tasks remain unexecuted; fullW2/M1/M2 and the overall goal remain incomplete.
