# W2.2 Model Binding And Queue Implementation Plan

> **For agentic workers:** Execute inline using executing-plans and TDD in the existing checkout and branch. The user has approved the overall design and asked to continue, retaining Linux-only work. Read-only code review is required. No automatic commit, OS fork or new worktree.

**Goal:** Implement the common structural model-binding gate and bounded, whole-message model-step queue without advertising a missing model consumer.

**Architecture:** Verify the selected actual hil_contract's declared inputs and parameters against the frozen97 bindings. Map only the thirteen existing root-input/parameter messages7..19, explicitly reject other consumers. Queue immutable admitted logical messages, reserve actual target paths for one writer, and release a sequential step batch without producing application evidence. Future actual C boundary must own business validation, lifecycle, control authorization, atomic writes and probes before enabling this library on the network.

**Tech Stack:** Existing isolated Python3.12, icd_runtime, standard-library dataclasses/hashlib/unittest. One common source and entrypoint for both hosts.

## Global Constraints

- HIL-ICD-1.0/v0.3 and all14 embedded interface sources remain unchanged.
- No actual model consumer: current gateway continues RECEIVED then FAILED/TARGET_MISSING; no new capabilities, APPLIED, CONSUMED or E2/E3.
-4096 logical messages globally, no overwrite/coalescing. Queue capacity is not reassembly's8MiB budget. Each stored payload is limited by its frozen message encoding; total canonical stored bytes are counted. Exactly one queue lifetime per registry prevents per-model/per-instance quota and writer bypass or closed-queue step reset.
- Model steps are sequential1ms, ahead1..1000, max86400000, no catch-up. Only RUNNING inputs enter this queue; frozen service-boundary updates are a separate pending package.
- Queue checks require the original live session admission and use first receiving monotonic time, not retry time. Control age100ms is checked again before release; this is not actual actuator safety execution.
- Single-writer reservations include session, role, control_source and input_lane at each actual target path. Flight/Actuator aliases share a path. Caller must authorize the actual ControlOwner before invoking enqueue; the queue cannot grant physical control.
- Port/parameter metadata compatibility is not generated ABI, behavior, initialization or subsystem qualification. No arbitrary JSON setter or output write.
- W2.2 is a bounded common package, not completeW2/M2. Append Linux L-004/L-010 transfer and common unfinished responsibilities to the single ledger. Preserve all41 plan tasks.

## Task1: Structural Bindings

Files: create`icd_gateway/model_bindings.py`, `tests/icd_gateway/test_model_bindings.py`.

Interface: `ModelBindings(contract, model_id, runtime_contract)`, `map_message(message)` -> tuple of frozen `MappedValue(path,target_field,value_json)`; value_json is canonical engineering value bytes, not a memory offset. Caller values must not alias stored metadata.

- [x] Add failing availability, all97 binding coverage, strict descriptor mismatch, missing/extra port/parameter, duplicate parameter, wrong symbol/model/step, complete snapshot/alias and existing hex gap tests.
- [x] Run`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_model_bindings.py -v`; observe missing feature.
- [x] Implement comparison of input field/unit/type/dimension/min/max (environment default also required) and parameter name/generated field/unit/type/min/max/default/exported-global binding. Reject unknown mapped consumers.
- [x] Rerun focused tests; mapping never includes state.outputs or silently fills payload fields.

Test anchor:
```python
flight = mapping.map_message(message(7))
actuator = mapping.map_message(message(14))
assert flight[0].path == actuator[0].path == 'flight_control.motor_command'
```

## Task2: Original Session Admission

Files: modify`icd_gateway/session.py`, test in`tests/icd_gateway/test_model_queue.py`.

Interface: `SessionRegistry.require_admitted(message, now_ns=...)` -> first receiving monotonic ns. Verify live identity, original canonical digest, original sequence record and nonterminal request; cannot enqueue an already FAILED/APPLIED/CONSUMED request. This is an internal common API, not a new wire field.

- [x] Add tests for never-admitted input, changed content, revoked/expired session and immutable first receive time; observe the missing queue/admission package before implementation.
- [x] Preserve `_Record` digest/cache behavior while adding first receiving time and read-only admission verification, plus one-shot queue claim.
- [x] Rerun existing session tests, including8192-entry eviction.

## Task3: Whole-Message Step Queue

Files: create`icd_gateway/model_queue.py`, `tests/icd_gateway/test_model_queue.py`.

Interfaces: `ModelQueue(contract,registry,mappings)`; `enqueue(message,state,now_ns,control_source=None,input_lane=None)`; `begin_step(model_id,step,state,now_ns)` -> frozen `StepBatch(ready,rejected)`; `discard_session(sid)`, `clear()`, `close()`. Returns immutable pending inputs/rejection reasons, never Ack or model revision. Callers serialize these operations with the real boundary.

- [x] Write failure tests for actual4096 global capacity, immutable snapshots, no overwrite/merge, same-target overlap, wrong model/lane, cross-writer alias collision, full-message rollback, step bounds/sequential release, expired controls despite heartbeat, stale session purge and close/clear. Role admission continues using the already tested SessionRegistry.
- [x] Observe missing queue; implement dictionary-bounded storage and canonical bytes, atomic reservation checks before mutation, first-receive age checks and original request IDs/hash retention.
- [x] Rerun focused tests with no model mock registered in the gateway. Same transaction across messages does not imply atomic cross-message commit.

Test anchor:
```python
pending = queue.enqueue(value, state='RUNNING', now_ns=0)
batch = queue.begin_step('quadrotor_hil', 1, state='RUNNING', now_ns=1_000_000)
assert batch.ready == (pending,)
assert not batch.rejected
```

## Task4: Verification And Append-Only Handoff

Files: append`docs/superpowers/plans/linux-development-backlog.md`; update`icd_gateway/README.md`, overall progress; create`artifacts/icd_gateway/w2-2-validation.json`.

- [x] Read-only review focused on unsafe ownership, mutation, late catch-up, cache/admission replays and false evidence; fix reproduced defects with red/green tests. Reviewer rerun35 tests confirmed the registry-lifetime ownership fix, with no important new findings.
- [x] Run common runner, golden selfcheck, staticQA and34 selected static regressions; record exact counts/host and no Linux/model claims.
- [x] Append actual-model adapter/writes/step-clock/safety responsibilities to L-004/L-010, same-source Linux testing L-002/L-017; keep common lifecycle/ControlOwner/status/evidence/extended consumers outstanding.
- [x] Verify41-task coverage and single-file exact14 source snapshots. Do not complete the overall active goal or mark fullM2 complete.

## Verified Result: 2026-10-03

Common runner134 tests passed (54 ICD,73 gateway/source including35 new model primitives,3 ledger,4 single-file), plus34 selected existing static regressions. Offline golden85 vectors/800 RAW fragments, staticQA10446 checks/2427 negatives, exact14 embedded source verification and dependency/compile checks passed. The current host isWindows AMD64/Python3.12.14; no model or Linux qualification is implied.

Read-only review's P1 multi-queue ownership/step-reset bypass was reproduced and corrected by one queue lifetime per registry; reviewer reran35 focused tests with no important new findings. Evidence is`artifacts/icd_gateway/w2-2-validation.json`. Append-only W2.2 Linux transfer exists in the single ledger and all41 plan tasks remain owned.

The branch remains in place with no automatic commit/merge. Complete lifecycle, actual consumer interface, business semantics and safety ownership are the next common package. LinuxC atomic application/step-clock/ABI/probes remainL-004/L-010; networkReceiver has not enabled this queue and still refuses missing consumers honestly. FullW2/M1/M2 and the overall active goal remain incomplete.
