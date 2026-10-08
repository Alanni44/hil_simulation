# W2.4 Retirement And Cleanup Boundary Implementation Plan

> **For agentic workers:** Execute inline with executing-plans and TDD in the current approved checkout. Read-only review required. No new branch, automatic commit, platform fork or production test consumer.

**Goal:** Make actual ingress retirement release its owned network/queue resources, preserve original discarded requests, and validate the complete nine-operation cleanup contract before real consumer integration.

**Architecture:** SessionRegistry owns one queue and exposes retirement/idle queue-maintenance APIs. Receiver coordinates the same registry and assembler without recreating model-step history. Pure cleanup decisions require a real ModelView, strict37/38 messages and target rules; local retirement is not successful wire SessionClose, actual actuator/fault/video/tool cleanup or E2.

**Tech Stack:** Common Python3.12, frozen dataclasses and unittest; existing Contract, SessionRegistry, ModelQueue and Reassembler. No dependencies or wire fields added.

## Global Constraints

- Retire only the named nonzero uint32 session; bool/float/zero/overflow areSCHEMA. Repeated retirement is safe and cannot affect other sessions.
- Return every original immutable discarded PendingInput. Preserve the existing bounded5s feedback cache for audit, but the revoked session ID must never regain writes or retry admission. Sources/executors must use freshnonce/newsession. Receiver nonce conflict detection is bounded by the existing5s cache, not a lifetime cryptographic anti-replay guarantee; after expiry an identical oldopen can create a different newSID under a still-authorized grant. No tombstone wire close-success implementation in this package.
- Tick must expire sessions, release stale queue inputs/writers even when no model steps run, release expired-session reassembly, and return immutable maintenance results. Explicit Receiver retirement releases its named fragments immediately.
- Local retirement never clears other sessions, global model step history or completed feedback; shutdown does clear all resources and permanently prevents reopening the same registry.
- Receiver tick returns cumulative immutable maintenance untildrain_maintenance(), so implicit receive/poll cannot lose records. Outbox defaults4096 original rejected inputs (local optional lower1..4096) and8192 expired-session IDs; preview all clocks/open states and required room before deletions, returnBUFFER_FULL without eviction or clock changes when full. Shutdown keeps an independent bounded64-session/4096-input result untildrain_shutdown(), including when transport/context ignoresclose return.
- Cleanup37 and SessionClose38 contain all nine true fields. Cleanup37 frozen targets name currentstep; RUNNING targets name ahead1..1000 within duration. SessionClose38 isSERVICE_BOUNDARY and uses the actual current safety boundary, not its header as a future model scheduling request. FAILED cleanup is allowed. Validation returns all obligations, not actual completion.
- Network37/38 remain fail-closed without complete actual cleanup consumers. No APPLIED/CONSUMED/probes/ready are minted; capability remainsID1. Service close cannot be made successful by deleting a session before applying required safety.
- Linux implements actual model/bus fault recovery, actuator/DA/TTL safety, video/tool/replay stop, control revocation, queue flush and final close with real probes. Common APIs are reused, not rewritten forLinux.
- Append the stage record to the single Linux ledger, retain all41 overall task responsibilities and17 unexecuted Linux items.

## Task1: Registry Retirement And Terminal Shutdown

Files:icd_gateway/session.py; tests/icd_gateway/test_retirement.py.
Interfaces:`retire(session_id)->tuple[PendingInput,...]`; `expire_model_inputs(now_ns=...)->tuple[RejectedInput,...]`; `close()->tuple[PendingInput,...]`. Existing`revoke` remains low-level authorization revocation; Receiver retirement also flushes resources.

- [x] Write failing tests for session-scoped queue cleanup, identity strictness/idempotence, retained bounded feedback/no replay after revocation, unaffected sessions, permanent registry close and original close-discard records.
- [x] Run`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_retirement.py -v`; observe missing retirement behavior.
- [x] Implement owned-queue retirement and idle expiration wrappers; terminal registry guards, no second queue or step reset.
- [x] Run focused tests and existing session/queue tests.

Test anchor:
```python
removed = registry.retire(sid)
assert removed == (original_pending,)
assert registry.retire(sid) == ()
assert other_sid in registry.session_ids
```

## Task2: Receiver Maintenance And Complete Cleanup Decisions

Files:icd_gateway/receiver.py,icd_gateway/semantic_guards.py,icd_runtime/reassembly.py; tests/icd_gateway/test_retirement.py. Reassembler`discard_inactive_sessions(tuple_of_live_uint32_ids)` releases stale nonzero sessions while preserving pre-session0; `clear()` releases all groups/terminals without rewinding its clock.
Interfaces:frozen`MaintenanceResult(expired_sessions,rejected_inputs)` returned cumulatively by`Receiver.tick`, consumed once by`drain_maintenance()`; `Receiver.retire_session(session_id)` returns original removed inputs and clears its fragments; `Receiver.close` returns remaining removed inputs and retains frozen`ShutdownResult(closed_sessions,discarded_inputs)` until`drain_shutdown()`. `SessionRegistry.preview_maintenance(now_ns=...)` and`ModelQueue.preview_expiry(active_sessions,now_ns=...)` perform read-only previews. All three participants expose`check_clock(now_ns)` for side-effect-free preflight. Frozen`CleanupDecision(session_id,target_step,reason,operations)` via`SemanticGuards.cleanup(message,view)` lists all nine obligations, does not execute them.

- [x] Add RED tests for explicit fragment cleanup, idle expired/revoked queues, immutable results, preserved step/writer domains, every cleanup field false/missing/extra/wrong-type, all close reasons, lifecycle target/state limits and no consumer wire failure.
- [x] Implement real common resource release and pure cleanup validation. Return records to the actual maintenance caller; transport with no model consumer cannot claim complete safety.
- [x] Rerun focused tests, realUDP regressions and read-only review; fix reproduced findings using RED/GREEN tests.

Test anchor:
```python
maintenance = receiver.tick(now_ns=1000000000)
assert maintenance.expired_sessions == (sid,)
assert maintenance.rejected_inputs[0].pending == original_pending
assert maintenance.rejected_inputs[0].error == 'STALE_SESSION'
assert queue.count == 0
assert receiver.drain_maintenance() == maintenance
```

## Task3: Verification And Linux Handoff

Files:icd_gateway/README.md; docs/superpowers/plans/linux-development-backlog.md; docs/superpowers/plans/2026-10-02-input-simulator-overall.md; artifacts/icd_gateway/w2-4-validation.json.

- [x] Run common entry,85golden/800RAW checks, staticQA,34 selected static regressions, dependency andcompile checks.
- [x] Append Linux actual nine-operation cleanup and reliable terminal close-feedback obligations toL-004/L-010/L-012/L-017, plus same-sourceL-002 qualification; do not close target items from host evidence.
- [x] Verify41 ownership rows,14 byte-exact source snapshots and report test counts, no activated production consumer, overall goal still incomplete.

## Scoped Result

2026-10-03:27 retirement/cleanup tests and13 actualUDP tests pass in the final common runner.187 total (54runtime,126gateway/source,3ledger,4single-file),34 selected existing static regressions,85goldens/800RAW, staticQA10446/2427 andpip/compile checks pass.14 byte-exact embedded sources remain unchanged. Phase report:artifacts/icd_gateway/w2-4-validation.json.

Read-only review reproduced two record-loss/clock-order bugs; RED/GREEN tests now prove cumulative drainable bounded maintenance and pre-deletion clock/capacity validation. Review followup independently passed23 retirement/12UDP tests and the8192-session outbox probe, no new actionable findings; final expanded27/13 coverage passes the full runner. SessionClose service-boundary distinction has its ownRED/GREEN test.

Only common internal retirement and pure full-cleanup decisions are closed here. Actual nine effects, reliable terminal close-feedback after session invalidation, consumer execution, raw persistent evidence, Linux/physical qualification and fullW2/M2 remain incomplete.17Linux tasks are unexecuted; the overall goal remainsactive.
