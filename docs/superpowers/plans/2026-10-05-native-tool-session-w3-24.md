# Original W3 Native Tool Session Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans, test-driven-development and requesting-code-review. Do not resume the generated-data draft.

**Goal:** Let original CANT senders and the actual UDP/Scapy dispatcher operate under one standard SourceSession for the production scenario driver.

**Architecture:** NativeToolCoordinator coordinates the existing dispatcher and one to four explicit original CANSignalSender instances, without forwarding CAN bytes over UDP. Private thread-local scope permits only the selected original builder/sender while all original locks are held. Direct CAN and builder APIs continue to reject dispatcher ownership. SourceSession tracks first managed TX sequence across original links; retries of an already admitted original UDP pending group do not claim a new first sequence.

**Tech Stack:** Existing Python, ContextVar, ExitStack, python-can/Scapy, standard WireCodec and unittest. No additional dependency or Windows backend.

## Constraints

- Frozen baseline 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27; no ICD/C/six-tool rewrite or branch split.
- Attach at a genuine fresh LIVE grant before source input allocation/TX. All original senders use the same SourceSession and reservation book; distinct explicit formal CANFD channels/interfaces and actual buses.
- Preparation does not transmit; no fallback, local grant, arbitrary callbacks or public owner-override argument. The coordinator never chooses model steps or retimes missed events.
- Native CAN original backend ownership, whole-group authorization, heartbeat attempt floors, byte evidence, bounded queues and retryable actual shutdown remain authoritative.
- Original observation recorder does not yet persist native CAN records: do not bypass its guard or claim complete evidence. Preserve SOURCE/DISPATCH/INBOX formats.
- Close only the supplied CAN backends locally, retaining SEND reservations, standard session/dispatcher and remote nine-operation cleanup responsibility. Failed close leaves the same handles and coordinator bound for retry; other sends remain stopped.
- This enables one original Ethernet dispatcher plus up to four original CAN channels. Multiple Ethernet dispatchers, six-tool GUI/replay lifecycle, production ScenarioDriver, clocks and full native persistence remain original work.

## Task 1: Shared Original Tool Owner And First-TX Order

Create input_simulator/native_tools.py and input_simulator/_native_scope.py; modify input_simulator/session.py, live_tool_input.py, can_signal.py and dispatch.py. Create tests/icd_gateway/test_native_tools.py and minimally expose the actual socket peer in test_can_signal.py's fixture.

Interfaces: NativeToolCoordinator(dispatcher, senders: tuple). prepare_can(sender, stimulus, target_step, transaction_id=None), send_can(sender, plan, timeout=0.01), receive_can(sender, plan, timeout=0.01), retire_can(sender, plan), drain_can(sender), discard_can(sender, plan), close_can(sender), submit(stimulus, target_step, transaction_id=None), poll(), close(). Only registered original instances are accepted. execution_ready and safety_verified stay false.

- [x] Write and observe RED tests for shared actual CAN+UDP SID/sequence, original bytes/feedback, direct-call rejection, forged/foreign instances, fresh grant/book/channel constraints, older unsent group rejection, cross-link heartbeat transaction reuse, model Status observation, reentry/thread serialization, recorder guard, four CAN channels and retryable close with reservation/session preservation.
- [x] Implement the private scoped lock delegation and actual native coordinator; preserve all non-coordinated APIs and original constructor behavior.
- [x] Implement first managed TX SID/sequence floor in SourceSession for serial request, dispatcher first attempt and CAN first attempt. Keep allocation-only preparation and legitimate original UDP retries unchanged.
- [x] Run focused and compatibility tests, request read-only independent review, fix important findings using RED/GREEN.

```powershell
& './runtime/icd-venv/Scripts/python.exe' -X utf8 -m unittest discover -s tests/icd_gateway -p test_native_tools.py -v
```

## Task 2: Full Regression And Sole Ledger

- [x] Run fixed final code through scripts/test_icd_runtime.py to terminal exit; compare source/test hashes before/after.
- [x] Verify frozen 14 sources/663 references, pip, compilation and 41 plan/17 unchecked Linux responsibilities.
- [x] Append shared-owner, cross-link sequence/feedback, real Linux timing and native persistence requirements to linux-development-backlog.md; preserve its historical prefix. Save w3-24-validation.json and update overall progress, not W3 completion.

```powershell
& './runtime/icd-venv/Scripts/python.exe' -X utf8 scripts/test_icd_runtime.py
& './runtime/icd-venv/Scripts/python.exe' -m pip check
& './runtime/icd-venv/Scripts/python.exe' -m compileall -q input_simulator tests/icd_gateway
```

## Reviewed Boundaries

The final focused suite passed 23 tests in 28.155 s. Review findings were reproduced before repair: stale copied scopes and direct public reentry bypassing native locks; failed shutdown permitting direct UDP sends; dispatcher replacement stranding native cleanup; discarding a retained attempt. Additional RED/GREEN tests cover premature source-owner release after dispatcher close and another channel discarding a shared-builder plan.

Delegation now requires the exact current scope object and a single consumed public entry. Shutdown retains original ownership until actual native cleanup detaches the coordinator; replacement and transmit-capable dispatcher operations cannot bypass it. Discard checks the exact sender reservation/binding and requires retained attempts to be retired. The original UDP retry remains the original admitted group, not a new first attempt. Test feedback waits explicitly use 0.2 s like the original CAN fixture; runtime defaults and frozen 20 ms assembly/TX deadlines are unchanged.

Read-only final review found no remaining actionable P1/P2 issue in this scope; three boundary tests passed in 3.655 s and the original two-sender copied-context reproduction rejected STATE. An earlier concurrent test run had a 0.01 s feedback TIMEOUT, followed by an exact-default passing rerun; it is not physical timing qualification. Fixed final full regression passed 829 tests (67 runtime, 755 gateway in 468.652 s, 3 ledger, 4 single-file); eight source/test hashes remained unchanged. The 34 selected static regressions, offline 59/72/85/800 vectors, pip and compilation passed. Append-only handoff and validation report are saved; original W3 is still incomplete.
