# Original Native Scenario Send Actions Implementation Plan

> **For agentic workers:** Use executing-plans, test-driven-development and requesting-code-review. Continue the original W3; do not resume the generated-data draft.

**Goal:** Implement the actual native sending part of the production ScenarioDriver using the unchanged ScenarioPlan, CANSignalSender, ScapySource and NativeToolCoordinator.

**Architecture:** NativeScenarioActions is a send handler, not another scenario scheduler or a complete ScenarioDriver. The existing plan supplies exact SEND, FAULT, WAVEFORM and PERIODIC_START/PERIODIC_SAMPLE values and PERIODIC_STOP boundaries. Explicit original CANT and ETHGEN bindings retain native bytes and standard request/feedback identity; all other event handlers remain required for the complete driver. Caller-supplied model_step and target_step are distinct; this handler does not manufacture a synchronized clock or ControlOwner authorization.

**Tech Stack:** Existing Python, dataclasses, unittest, cantools/python-can, Scapy, original standard codec and owner locks. No new dependencies, Windows backend or ICD change.

## Constraints

- Baseline 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 and the single public contract remain unchanged. Work in the existing codex/icd-runtime-w1 branch; no commits, new worktree or cleanup of unrelated files.
- NativeScenarioActions handles only native send event kinds; begin rejects WAIT/ASSERT/REPLAY/NEGATIVE_SEND/END_CLEANUP. CUTIL/SAVVY and replay branches are never silently mapped to CANT/ETHGEN. Preflight checks every native send/stop in its assigned original plan, not assertion or cleanup readiness.
- ETHGEN requires the actual original ScapySource and its SEND reservation, not plain UDP. CANT requires an explicitly selected registered sender. Scapy and CAN use the same reservation book and standard SourceSession.
- Preflight and invalid input never take counters or transmit. Runtime rechecks grant/SID/model/capability/role/lease and local backend ownership. Model control, synchronized clock, qualified probes and safety are separate required gates of the complete driver.
- Native CAN polling is bounded/nonblocking and an empty queue is not a TIMEOUT failure. Original blocking receive behavior and frozen CAN 20ms assembly/TX limits do not change.
- UDP cancellation names the exact owned original Header and cancels only that pending group locally, retaining records, counters and reservations. No remote cleanup or successful model application is implied.
- Exact original action content, opaque runtime handles, finite run record/byte budgets, no retry of begin, no skipped-step rebasing or automatic target-step selection. Original UDP retry remains authoritative; CAN is not automatically retried.
- Terminal standard feedback and local cancellation are recorded separately. COMPLETE is a transport-handler result, not E2/E3 qualification. stop is retryable local cancellation and does not close shared backends or release SEND reservations. Preserve original records; never drain to admit later work.
- Original complete ScenarioDriver, all six tools, assertions/WAIT, replay/repeat/RESET/initial_inputs, negatives, nine-part cleanup, native persistence/Run/Report and Linux target gates remain full-scope work.

## Task 1: Native Nonblocking Poll And Scoped UDP Cancel

Files: modify input_simulator/can_signal.py, native_tools.py and dispatch.py; extend tests/icd_gateway/test_native_tools.py.

Interfaces: CANSignalSender.poll_for(plan) and NativeToolCoordinator.poll_can(sender, plan) return an actual standard reply or None. UDPDispatcher.cancel(header) and NativeToolCoordinator.cancel(header) retain original CANCEL records and counters; exact pending Header identity is mandatory.

- [x] Add RED tests for repeated empty native polls without failure records, actual original feedback, local cancellation of one of two pending UDP groups, forged Header rejection and cancellation after expiry/failed closing.
- [x] Reuse the original CAN receive body with an internal empty_ok path; add strict owned-header cancellation using the original dispatcher/source cleanup locks and _finish.
- [x] Run native and original CAN/dispatch compatibility tests.

```powershell
& './runtime/icd-venv/Scripts/python.exe' -X utf8 -m unittest discover -s tests/icd_gateway -p test_native_tools.py -v
```

## Task 2: Original Native Send Handler

Files: create input_simulator/native_scenario_actions.py and tests/icd_gateway/test_native_scenario_actions.py. Use the actual standard-grant Scapy frame-sink fixture and original python-can VirtualBus peers only as library-level software evidence.

Interfaces: NativeScenarioActions(contract, plan, coordinator, *, can_sender=None, max_pending=64, max_records=4096, max_bytes=16777216). An actual standalone UDPDispatcher is also accepted for an original Scapy-only run; no unrelated CAN backend is required. preflight(), begin(action, *, model_step, target_step), poll(handle, *, model_step) -> original ActionProgress, stop(*, model_step), records/pending_count/pending_local_cleanup. No launch API or alternate public wire fields.

- [x] Write RED tests for original CAN/Scapy bytes and shared SID/counters, complete constant/waveform/periodic/fault values, exact action membership, strict steps/handles, all missing or revoked bindings/capabilities, finite budgets and no plain-UDP fallback.
- [x] Implement finite native action ownership, side-effect-free assigned-handler preflight, actual original sends, standard terminal/error feedback and elapsed original request validity; preserve intermediate feedback without claiming completion.
- [x] Implement local PERIODIC_STOP semantics from the original compiled schedule and permanent local stop of owned pending groups only; preserve shared unrelated traffic, backends, counters, reservations and remote cleanup responsibility.
- [x] Run focused tests; request read-only review and close important findings with RED/GREEN tests.

```powershell
& './runtime/icd-venv/Scripts/python.exe' -X utf8 -m unittest discover -s tests/icd_gateway -p test_native_scenario_actions.py -v
```

## Task 3: Verification And Existing Ledger

- [x] Run scripts/test_icd_runtime.py to terminal exit on the fixed final code; compare source/test hashes before and after. Verify selected existing static tests, pip, compilation and frozen14/663.
- [x] Append this send-handler scope, actual Linux native tool/timing/authorization/feedback/stop checks and remaining complete-driver requirements to the sole linux-development-backlog.md, preserving its historical prefix and 41 responsibilities/17 unchecked Linux gates.
- [x] Save artifacts/icd_gateway/w3-25-validation.json and update the overall plan without marking original W3 complete or resuming the new generator.

## Focused Implementation Evidence

The first 17 action tests were RED for the missing module, then passed after implementation. Review regression tests reproduced missing selected-protocol preflight, CAN-only reservation-book mismatch and blocked closing/detached cleanup before fixes. Another actual post-allocation failure reproduced lost cleanup identity; FailedToolPreparation now captures an opaque original source input inside builder/source owner locks, retains request bytes and consumed counters, and shares plan count/byte limits. It is not a successful LiveToolInput. Only its original sender can reclaim it; no scan of unrelated source inputs or counter rollback is used.

Final focused runs: 28 native action tests in 36.654 s and 27 native coordinator tests in 33.066 s passed. Independent read-only review reran seven important cases, all exit 0, with no remaining important scoped finding. Fixed-code full regression passed 862 tests (67 runtime, 788 gateway in 498.227 s, 3 ledger, 4 single-file), with ten source/test hashes unchanged. The 34 selected static regressions, offline 59/72/85/800 vectors, dependencies and compilation passed. The ledger's previous 70807 normalized UTF16 characters remain byte-exact as normalized UTF8 SHA256 788f0dfdca9b2cc25691cdcd1c6ef65adcc487179d945b0c66c13c2c52f5db15; all 41 responsibilities and 17 unchecked Linux gates remain. Post-save 3 ledger/4 single-file tests and 14-source/663-reference verification passed; the validation report is saved. This work package is complete, not original W3: the production ScenarioDriver and all other Original W3 Finish Gate requirements remain incomplete.
