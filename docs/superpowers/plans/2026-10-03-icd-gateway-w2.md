# W2 Shared Session And UDP Implementation Plan

> **For agentic workers:** Execute inline using executing-plans and TDD. The user authorized continuation of the approved design on 2026-10-03. Reuse the existing checkout; no new OS implementation, worktree, automatic commit or merge. Review is read-only.

**Goal:** Start W2 with W2.1: a common bounded session/authorization layer, actual UDP gateway and source, and correctly associated cached failure feedback without a model consumer.

**Architecture:** Exact deployment grants bind complete identity, roles and ingress links. ACL and session checks precede reassembly. Complete logical messages share session-wide sequence/digest/response state across links. Gateway uses the W1 codec and reports unavailable consumers explicitly. The source uses separate TX/feedback sockets and the same wire bytes.

**Tech Stack:** Existing isolated Python3.12, pinned W1 dependencies, standard-library socket/selectors/time/secrets/unittest. No Linux-only driver substitution or new dependency.

## Scope And Gates

- HIL-ICD-1.0/v0.3 and the four-component hash stay unchanged. No mock/real dispatch.
- Deployment configuration contains explicit IPv4/port, channel and grants; formal defaults remain36100/36101/36102. Tests may use explicitly registered ephemeral deployment endpoints, not a new protocol/port.
- SessionOpen grants only configured identity/roles; lease1000ms, only a fresh authorized Heartbeat renews. Session IDs do not wrap/reuse in a process. Bounded64 live sessions is a conservative local deployment resource limit, not a new ICD field.
- Strict increasing input sequence per session; redundant complete copies must have the same canonical message hash. Cache8192 messages/5s and immutable real feedback; eviction never resets the high-water mark.
- Reassembly retries must be completed and compared by session layer. W1 default completed-group suppression remains unchanged; add an explicit caller option plus session cleanup API and tests.
- No actual model/status/physical consumer: capability readiness and qualified/probe lists remain false/empty. Heartbeat lease behavior is implemented but absent model Status returnsFAILED/TARGET_MISSING. Model messages do not enter a fake applied queue and cannot returnAPPLIED/CONSUMED.
- W2.1 is not complete W2/M2: actual step/state/control-owner checks,4096 model queue, full cleanup/lifecycle/clock/resource/video handling, E2/E3 and formal release gating remain the next common/target packages, tracked inlinux-development-backlog.md.
- Any phase closeout appends Linux responsibilities and common gaps to that single ledger.41 original plan items must stay covered.

## Task1: Full-Plan Ledger

Files: create`docs/superpowers/plans/linux-development-backlog.md`, test`tests/test_development_backlog.py`.

- [x] Write a test extracting M0-M7 tasks from the overall plan and requiring exact task text/unique IDs in the matrix; verify all L references exist and W1 migration record is present.
- [x] Observe failure for a removed/duplicated matrix row in an in-memory mutation; run actual41-item coverage. Establish append-only closeout policy.

## Task2: Bounded Shared Sessions

Files: create`icd_gateway/session.py`, `tests/icd_gateway/common.py`, `tests/icd_gateway/test_session.py`.

Interfaces: `PeerBinding(channel, transport, peer)`, `SourceGrant(identity, roles, bindings)`, `SessionRegistry(contract, grants, max_sessions=64)`. `preauthorize(message_id, session_id, binding, now_ns)` before allocation; `accept(message,binding,now_ns)` returns`Decision(session_id,replay)`; `record_response(message,responses,now_ns)`, `next_feedback_sequence(session_id)`, `expire(now_ns)`, `revoke(session_id)`.

- [x] Write tests for identity/role binding, immutable caller values, fixed lease/heartbeat renewal, expiry/closed session, nonreuse/capacity, cross-link exact duplicate versus changed value, old sequence after cache expiry, feedback counter and bounds.
- [x] Run`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_session.py -v`; observe missing module before implementation.
- [x] Implement authorization and bounded digest/feedback state. Store only canonical digest plus at most3 feedback messages/4096 canonical bytes per record; cache limit does not bound entire process RSS.
- [x] Rerun focused tests and verify expiry rejects writing regardless of transport.

Test anchor:
```python
decision = registry.accept(open_message, binding, now_ns=0)
heartbeat['header'].update(session_id=decision.session_id, sequence=2)
registry.accept(heartbeat, binding, now_ns=20_000_000)
assert registry.expire(now_ns=1_020_000_000) == [decision.session_id]
```

## Task3: Receive/Reassembly/Feedback Boundary

Files: modify`icd_runtime/reassembly.py`; test existing reassembly suite; create`icd_gateway/receiver.py`, `tests/icd_gateway/test_receiver.py`.

Interfaces: `Reassembler(contract, retain_completed=True)`, `discard_session(session_id)`; `Receiver(contract,registry).receive(packet,binding,now_ns)` returns feedback-message tuples, never model evidence. Local structured errors are bounded counters/details, not trusted E2.

- [x] Write failing tests for opt-in retry reassembly and session group/cache clearing while preserving W1 defaults.
- [x] Write receiver tests for unauthorized no allocation, authorized partial expiry, SessionOpened minimal capabilities, same-byte retry replays immutable responses, conflict/role/expired failures and absent-consumer terminalFAILED with probe0.
- [x] Run focused tests, implement real catalog-derived response headers and caps. Do not publish physical qualification or model consumers.
- [x] Rerun all W1/receiver tests; original14 source snapshots must stay byte-exact.

## Task4: Actual Common UDP Entrypoints

Files: create`icd_gateway/config.py`,`icd_gateway/udp.py`,`icd_gateway/__main__.py`,`input_simulator/udp_source.py`,`input_simulator/__main__.py`,`tests/icd_gateway/test_udp.py`,`tests/icd_gateway/test_cli.py`.

Interfaces: strict deployment JSON reader; `UDPGateway(receiver,bind,feedback_routes)` owns one AF_INET socket with bounded1201-byte reads, `poll(timeout)` and close/context-manager. `UDPSource(contract,source_bind,feedback_bind,receiver_endpoint,channel)` owns two sockets, `send(message)` and `receive_for(request,timeout)` verifies actual feedback source/transaction and request IDs. No hidden heartbeat thread or synthetic state.

- [x] Write actual socket tests for SessionOpen round-trip, fragmented input rejection/feedback association, retransmission, reverse ACL filtering and port roles. Write CLI subprocess tests for independent service/source startup, wrong hash/config startup refusal and clean process termination.
- [x] Run focused tests and observe missing UDP/CLI before implementing. Use the same Python entry on both OSs.
- [x] Implement explicit binding/close and timeout-driven expiry even when no packets arrive. Malformed/untrusted framing is dropped and locally counted, not acknowledged using guessed headers.
- [x] Rerun tests with real UDP; no in-memory transport result may be reported as network verification.

CLI anchor:
```text
python -m icd_gateway --contract-dir docs/interfaces/baseline --expected-sha256 <release-pin> --deployment <json>
python -m input_simulator --contract-dir docs/interfaces/baseline --expected-sha256 <release-pin> --source-bind 127.0.0.1:36102 --feedback-bind 127.0.0.1:36101 --receiver 127.0.0.1:36100 --message-file <business-json>
```
These are development-only entrypoints; they must not report formal release or replacement readiness.

## Task5: Evidence And Handoff

Files: create`icd_gateway/README.md`,`artifacts/icd_gateway/w2-validation.json`; extend` scripts/test_icd_runtime.py`; update overall plan and append W2.1 ledger record.

- [x] Run new unit/socket/subprocess suites, W1/goldens, ledger coverage, static QA and compatible regressions; record exact counts/host/failures.
- [x] Read-only review for ACL bypass, sequence/cache bounds, feedback lies, retry ordering and platform branches; fix verified defects via failing tests.
- [x] Append Linux transferL-017 plus linkedL-001/L-002/L-004/L-010 and explicit common gaps; never mark fullW2/M2 complete. Leave all Linux items unchecked.

## W2.1 Result: 2026-10-03

W2.1 common software package verified:38 gateway/source tests,54 ICD library tests,3 coverage-ledger guards,4 single-file tests and34 selected existing static regressions. Actual UDP tests include36100/36101/36102 and independent service/source processes; offline selfcheck still matches85 frozen vectors and14 original sources. Evidence is`artifacts/icd_gateway/w2-validation.json`.

Read-only review's important pre-session reassembly collision was reproduced and fixed with grant-local namespace restricted toSessionOpen/session0, preserving shared quotas. Source feedback sequence conflicts, tracking-capacity reporting, complete grant ambiguity and shutdown cache cleanup have regression coverage. The same code and Python runner serve both hosts; Linux remains unexecuted.

Append-only W2.1 transfer is now in`linux-development-backlog.md`. CompleteW2/M2 still requiresW2.2 common queue/state/consumer/lifecycle/evidence gates and target model/tool/device verification. No APPLIED/CONSUMED evidence or formal release was generated, and no commit/merge was made.
