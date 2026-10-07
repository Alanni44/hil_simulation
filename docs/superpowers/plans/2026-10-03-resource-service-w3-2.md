# W3.2 Standard Background Resource Service Implementation Plan

> **For agentic workers:** Use executing-plans and TDD inline in the current approved checkout. Keep independent-review gates open until actual review succeeds. No commit, new branch, platform fork or fake model consumer.

**Goal:** Connect the existing actual ResourceStore to authorized standard UDP34/141 through a bounded background worker, with original-request retries, truthful storage feedback and explicit cancellation.

**Architecture:** The main Receiver alone owns SessionRegistry/admission/feedback sequence. A single resource worker owns actual file I/O and communicates immutable requests/results through bounded queues. UDP sends asynchronous outcomes only to the request's original authorized binding. The source accepts only a correlated141 and waits for the final resource commit under the frozen10s bound. No model or video activation occurs.

**Tech Stack:** Shared Python3.12 standard-library threading/condition/socket/filesystem, existing Contract/WireCodec/ResourceStore and unittest. No new wire fields or second receiver.

## Global Constraints

- All frozen14 source files remain byte-exact. ResourceChunk34 has max32768 decoded bytes and existing required fields. ResourceAck141 identifies session/transaction in header and SHA256 in payload; complete is byte-storage completion, not APPLIED/CONSUMED/ABI/codec/configuration readiness.
- Original SID/sequence/transaction/business bytes are immutable. Duplicate while pending returns the actual RECEIVED prefix; duplicate after result returns the prefix plus real141. Different content always DUPLICATE. No second queue entry or write.
- Session feedback cache stays8192 entries; maximum64 pinned pending resources. The existing5s retry record can be pinned only until original-receive+10000ms for final commit (nonfinal max1000ms), then removed normally. Actual terminal storage feedback starts a5s retention window; late success cannot be cached as on-time completion. Only the resource-specific append method can extend a pending prefix; normal terminal records remain immutable.
- Main thread validates actual peer/role/model/admission before worker submit. Worker never calls registry clocks or invents model state. At most64 tasks/results and4MiB original pending message bytes; reserve result space on enqueue, never discard results. Receiver retains original completion records until explicit drain and stops collection at its bound.
- File I/O and content/hash checks run only on the resource worker. Resource write-start must be within34's1000ms validity and final commit within10000ms. Cancellation before start suppresses writes; cancellation during a write suppresses live-session success and cleans remaining staging at the next background boundary. Completed inactive bytes may persist, never activate a model or be erased as another owner's object. Close waits for the actual worker and preserves original unfinished requests; no forced thread termination.
- Resource-rate accounting uses actual UDP fragments plus conservative IPv4/Ethernet/FCS/preamble/IFG overhead. Source pacing and worker reservations are bounded by frozen20Mbit/s and are background work, not1ms scheduling. Target wire timestamps/utilization, priority, I/O latency and performance remain Linux qualification gates.
- Active heartbeat renewal remains explicit using the source's actual declared sender_step/last_rx_sequence. Final commit waiting does not silently fabricate heartbeat/model steps or permit stale-session writes.
- Default Receiver without a resource worker keepsID1 and34 failure. Actual installed storage worker may advertise34 only, not activation41/42, probes, qualified physical channels or ready/replacement flags. Formal deployment remains refused.
- MODEL download requires actual stopped-state/contract evidence; TERRAIN submit requires actual STOPPED/PAUSED evidence. No such consumer is installed in this phase, so standard34 MODEL/TERRAIN must fail TARGET_MISSING before claim, budget, queue or writes. Do not infer state from SessionOpen or inactive storage. The >64KiB actual UDP proof uses explicitly permitted VIDEO background byte preload, not codec/decode readiness. Five-kind standaloneStore remains an internal foundation, not five-kind wire readiness.
- Original PROTOCOL/SCENARIO/HISTORY execution, six tools, existing25-command management API and actual model/resource/video consumers remain required and are not replaced by this service.
- Append phase requirements to the same Linux ledger;41 responsibilities remain owned and17 target items unexecuted.

## Task1: Resource Feedback Correlation And Pending Cache

Files:icd_gateway/session.py,input_simulator/udp_source.py;tests/icd_gateway/test_resource_exchange.py.
Interfaces:`defer_resource_response(message,responses,*,now_ns)` pins only an originally claimed34 RECEIVED prefix;`finish_resource_response(message,reply,*,now_ns)` appends only its actual141 exactly once. Source `receive_for` accepts141 only for34, matchingSID/txn/hash and valid progress/complete relations.

- [x] Add RED tests for pending duplicate prefix, terminal append/replay, wrongID/hash/SID/txn, incomplete complete/progress, ordinary immutable terminals, pin expiry/pin count and fresh heartbeat requirements.
- [x] Run `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_resource_exchange.py -v` to RED.
- [x] Implement bounded resource-only cache extension and strict141 validation without altering other message feedback semantics.
- [x] Rerun focused tests to GREEN and existing session/UDP regressions.

Test anchor:
```python
registry.claim_admitted(request, now_ns=now)
registry.defer_resource_response(request, (received,), now_ns=now)
assert registry.accept(request, binding, now_ns=now).replay == (received,)
registry.finish_resource_response(request, resource_ack, now_ns=now+1)
assert registry.accept(request, binding, now_ns=now+2).replay == (received, resource_ack)
```

## Task2: Bounded Actual Background Worker

Files:icd_gateway/resource_worker.py,icd_gateway/resources.py,icd_runtime/resource_budget.py;tests/icd_gateway/test_resource_worker.py.
Interfaces:`ResourceWorker(contract,registry,store,capacity=64,max_pending_bytes=4194304)` owns one actualStore and one registry lifetime. `submit(message,binding,now_ns=...)` claims original admission after capacity/budget preflight. `synchronize_sessions(session_ids,now_ns=...)` cancels old identities without doing file I/O on caller. `peek_results()/release_result(key)` provide immutable original canonical requests,bindings and actual receipt/error; `close()` joins real work and returns preserved shutdown/abort outcomes. Rate reservations cover actual encoded packets, not decoded data only.

- [x] Add RED tests with actual temp files/threads for successful chunks, nonblocking submit, original ownership, duplicate absence, queue/result byte capacity, future budget validity, session cancellation and terminal join/cleanup.
- [x] Implement single-owner worker and conservative budget. All actualStore work stays in worker; model/application evidence remains absent.
- [x] Run focused tests to GREEN. Controlled I/O gates may be used only to expose thread/cancellation timing, never as a production consumer.

Test anchor:
```python
worker.submit(request, binding, now_ns=time.monotonic_ns())
wait_until(lambda: worker.peek_results())
outcome = worker.peek_results()[0]
assert loads(outcome.request_bytes) == request
assert outcome.resource_payload['complete'] is True
# resolve must run on the owning worker; the caller can verify actual test files, not bypass ownership.
assert (actual_store.root / 'objects' / sha / 'data.bin').read_bytes() == data
```

## Task3: Standard UDP And Source Commit Waiting

Files:icd_gateway/receiver.py,icd_gateway/udp.py,input_simulator/udp_source.py;tests/icd_gateway/test_resource_udp.py.
Interfaces:optional actual `resource_worker` Receiver parameter, `resource_feedback(now_ns=...)->tuple[(binding,reply),...]`, `drain_resource_records()` and retained shutdown records. UDP poll delivers ready background outcomes on idle as well as ingress. Source `.request` keeps exactly at most3 original retries and final10s waiting, never extends session by itself.

- [x] Add RED actual socket tests for complete>64KiB file transfer, correct141/source filters, pending and terminal duplicates, hash rejection, capacity refusal, idle feedback, cancel/close records and default fail-closed behavior.
- [x] Implement authorized background routing and truthful configured capabilities. Preserve existing registry/queue/maintenance invariants and all other failure behavior.
- [x] Add source packet pacing/10s final wait tests; physical timing is not claimed from host sleeps.
- [x] Run real UDP and all common tests to GREEN.

## Task4: Evidence And Linux Handoff

Files:icd_gateway/README.md,docs/superpowers/plans/linux-development-backlog.md,docs/superpowers/plans/2026-10-02-input-simulator-overall.md,artifacts/icd_gateway/w3-2-validation.json.

- [x] Obtain full read-only review for W3.1 storage and W3.2 service; preserve pending gate if the tool remains unavailable.
- [x] Run common232+new tests,34 selected existing static regressions,85 goldens/800RAW,staticQA,pip/compile and14 embedded source/41 ownership checks.
- [x] Append same-code worker/priority/disk/cancellation/pacing tests and actual activation requirements to existingLinux entries, not a new platform implementation.
- [x] Record common management/three-source/tool/model/consumer/evidence work still required. Overall goal remains active until complete target evidence exists.

## Scoped Result

Final common runner280 tests passed:54 protocol,219 gateway/source,3 ownership ledger,4 single-file contract. Resource suites92 total include44 storage,15 exchange,20 worker/budget,9 actual resourceUDP and4 source/CLI;48 are new service tests.23 UDPGateway tests preserve the default34 failure.34 selected existing static regressions,85 golden/800RAW fragments,staticQA10446/2427,pip/compile and14 byte-exact embedded sources passed. Evidence:artifacts/icd_gateway/w3-2-validation.json.

Full independent read-only W3.1/W3.2 review completed, including final20 worker,9 resourceUDP,15 exchange and4 source tests. Reproduced failures fixed through RED/GREEN:foreign expired same-SHA ownership cascade,cleanup failure losing prior abort/active originals,drain timeout recovery,nonfinal timeout cleanup/post-abort progress,malformed prefix Schema handling,CLI ResourceAck false success and absent actual MODEL/TERRAIN state gate. No unresolved actionable findings in the latest reviewed code. Actual large-file network proof is76800 VIDEO bytes only, not codec or model activation.

This focused service package is software-verified, not the complete W3/M2/M3/M4 or a formal release. DefaultCLI remains without a worker; explicit installed worker advertises storage34 but MODEL/TERRAIN currently fail TARGET_MISSING before writes. Existing25-command management integration,three source executors,six original tools,actual model/resource/video consumers,full E1 persistent evidence/clock/release gates and all17 Linux targets remain required. The overall objective remains active and is not redefined as this package.
