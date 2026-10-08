# Original W3 Standard Model Clock Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans with test-driven-development and requesting-code-review. Continue the approved original W3 before the deferred generated-data draft.

**Goal:** Provide a read-only model-step observation from actual correlated standard Status feedback for the original scenario driver's clock prerequisite.

**Architecture:** SourceSession retains one immutable latest Status observation. Its existing serial UDP exchange, UDPDispatcher and original CANSignalSender publish only already validated feedback under the actual source operation lock. ObservedModelClock reads that cache under the same owner locks, never sends or extrapolates model steps. The frozen RESET/RESUME policy requires a new SID, not an invented same-SID clock epoch.

**Tech Stack:** Existing Python 3.12, frozen v0.3 Contract, UDPSource, python-can, unittest; no new dependency or platform-specific backend.

## Global Constraints

- Preserve the baseline hash 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 and all 14 frozen sources.
- Keep original six tools, SourceExchange/archive formats, source counter ownership and Linux gates unchanged.
- Status is observation only; no ClockSync qualification, 1ms tick extrapolation, E2/E3, physical readiness or safety claim.
- Status freshness expires at original Heartbeat start plus the frozen 240ms, not latest read/arrival time. Reused or older Heartbeat transaction/sequence must not refresh it.
- Any same-SID model-step regression is rejected, even when no reader observed the earlier sample. Drain/replacing a reader does not reset this floor.
- Actual correlated fresh Lifecycle APPLIED/OK for RESET or RESUME with the published consumer.Lifecycle probe invalidates old-SID clock use. A new SessionOpen and new Status are necessary.
- Existing dirty checkout and unrelated deleted plan are preserved; no new branch, commit or worktree.

## Task 1: Standard Feedback Clock And Tests

**Files:** Create input_simulator/model_clock.py and tests/icd_gateway/test_model_clock.py. Modify input_simulator/session.py, input_simulator/dispatch.py and input_simulator/can_signal.py only at their validated feedback acceptance points.

**Interfaces:** ObservedModelClock(session).snapshot() -> immutable ModelClockSnapshot; require_step(step, required_state=None) -> same snapshot or ICDError. No public observation injection or local model-step setter. Snapshot includes original request/Status bytes, SID/model identity, reported step/state, source-domain times, transport/channel, expiry and NOT_EVALUATED qualification.

- [x] Write and run RED tests for absence, actual serial feedback, immutable provenance, no wall-time step advancement, strict uint32 step/state, conservative expiry, lease, unread regression, duplicate feedback, abandonment/new SID, successful RESET/RESUME versus failed/unpublished lifecycle feedback, and owner serialization.
- [x] Implement the bounded cache and snapshot reader; preserve original source exchange record fields. Cache only actual current validated feedback under the source operation thread.
- [x] Connect and test actual original CAN VirtualBus and UDPDispatcher standard feedback. VirtualBus/UDP protocol peers remain software test fixtures, not production model or physical qualification.
- [x] Run focused tests; request independent read-only review and close important findings using RED/GREEN tests.

```powershell
& './runtime/icd-venv/Scripts/python.exe' -X utf8 -m unittest discover -s tests/icd_gateway -p test_model_clock.py -v
```

## Task 2: Verification And Handoff

- [x] Run the fixed-source full common test entry; record actual exit status and counts, not an unfinished invocation.
- [x] Check frozen single-file reconstruction, dependency health and compileall. Append results and actual Linux clock/backend/model tests to the sole linux-development-backlog.md; preserve its prior text and all 41 responsibilities/17 unchecked gates.
- [x] Save scoped validation report and update overall Review And Execution progress without claiming original W3 complete.

```powershell
& './runtime/icd-venv/Scripts/python.exe' -X utf8 scripts/test_icd_runtime.py
& './runtime/icd-venv/Scripts/python.exe' -m pip check
& './runtime/icd-venv/Scripts/python.exe' -m compileall -q input_simulator
```

## Remaining Original W3

Scoped verification: 23 new tests plus two unchanged CAN compatibility tests passed (25 total, 17.752s); final common entry passed 806 tests (67 runtime, 732 gateway in 467.151s, 3 ledger, 4 single-file). Independent final seven focused tests passed in 6.754s. Five source/test hashes were unchanged across the final full run. Post-save three ledger/four contract tests and reconstruction passed; normalized historical ledger prefix of 66812 characters is unchanged. See artifacts/icd_gateway/w3-23-validation.json. These checked tasks close W3.23 only, not original W3.

Production ScenarioDriver handlers, coordinated original six tools, complete history execution/repeats/RESET/initial_inputs, pause/resume/conditional step, authorized negatives and qualified assertion readers, ClockSync measurements, continuous CAN/Scapy evidence and complete Run/Report remain original work. Standard Status at 80ms cannot establish a 1ms scheduler. W4/W5 remain deferred, not deleted; the new standalone generated-data entry remains deferred until original W3 is completed.
