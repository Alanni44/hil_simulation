# W3.1 Resource Storage Implementation Plan

> **For agentic workers:** Use executing-plans and test-driven-development inline in the approved checkout. Read-only review is required. No automatic commit, new worktree, platform fork or test model consumer.

**Goal:** Implement actual bounded file reception for frozen ResourceChunk34, with chunk/whole-file validation and reusable completed resources, before connecting the background service to UDP and management APIs.

**Architecture:** ResourceStore accepts complete validated34 objects from its serialized caller and owns a dedicated directory. It writes private staging files, verifies original bytes and defined JSON content, then atomically publishes a content-addressed directory containing bytes and bounded metadata. It returns immutable storage receipts, not wire feedback, authorization, activation or model evidence. Receiver remains fail-closed and Capabilities remains ID1 until its complete resource-service integration is implemented.

**Tech Stack:** The same Python3.12 standard library, existing Contract/json_codec and unittest. No additional dependency, OS dispatch or ICD field.

## Global Constraints

- Frozen v0.3 wire/source files remain byte-exact;34 accepts every required field and no extras. MODEL/VIDEO are opaque byte transfers, not qualified ABI/codecs. TERRAIN/OBSTACLES/MISSION use the existing respective JSON definitions; geographic/route/controller checks requiring actual configuration remain activation obligations.
- Strict canonical base64, actual decoded length, contiguous nonoverlapping offsets, final only at exact end, actual chunk/whole SHA256. Identical original chunk boundaries may retry; changed bytes, declarations or session ownership are rejected.
- Local deployment bounds:32MiB/resource,128MiB reserved total,8 incomplete transfers,128 objects,8192 chunks/resource,64MiB free-disk margin,128 abort/active reservations,256MiB original-request evidence. They are resource-service deployment limits, not extra business fields or a reduced input definition. Explicit bounded constructor settings can change these limits; no8MiB RSS claim.
- A dedicated root has one exclusive lock. Existing completed objects are rehashed and structurally inspected on open; unknown entries, symlinks, abandoned staging or stale locks fail closed. No automatic destructive crash recovery or overwrite. Completed resources persist; own incomplete resources are removed on abort/close with immutable original-request records returned.
- All clocks and limits are validated before changing transfer state. A failed final hash/content check aborts that transfer, preserves the rejection record and never publishes completion. Each successful write is flushed/fsynced; atomic directory publication is not a claim of power-loss durability on an unqualified target filesystem.
- No wire ResourceAck, Ack APPLIED/CONSUMED, actual model activation, formal capability or performance qualification in this package. The following common package must integrate background intake,20Mbit/s budgeting, session maintenance/feedback and10000ms commit waiting without blocking real-time ingress.
- Append phase-specific Linux requirements to the single linux-development-backlog.md. All41 overall responsibilities remain owned, all17 Linux items remain unexecuted.

## Task1: Storage And Byte-Level Contract

Files:icd_gateway/resources.py;tests/icd_gateway/test_resources.py.

Interfaces:`ResourceStore(contract,root,*,max_resource_bytes=33554432,max_total_bytes=134217728,max_uploads=8,max_objects=128,max_chunks=8192,min_free_bytes=67108864)`;`accept(message,*,now_ns)->ResourceReceipt`;`resolve(sha,*,kind)->StoredResource`;`abort_session(sid)->tuple[AbortedResource,...]`;`close()->tuple[AbortedResource,...]`;`drain_aborted()->tuple[AbortedResource,...]`. Receipt exposes the exact ResourceAck payload but contains no wire header. Original admitted message bytes are retained per chunk for failure/abort evidence within bounded metadata.

- [x] Add tests checking module availability, actual temporary-file storage, five kinds, multi-chunk>64KiB, canonical base64/length/final/offset/hash errors, strict session/clock, declaration conflict, exact duplicate replay, bounded bytes/slots/chunks/free disk, close/abort and no completion after failure.
- [x] Run `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_resources.py -v` and observe RED missing implementation.
- [x] Implement byte-level reception and atomic publication. Keep metadata immutable and all file names locally derived, never supplied by the request.
- [x] Run the same focused command to GREEN (initial15 tests).

Test anchor:
```python
first = store.accept(chunk(data, 0, 32768), now_ns=0)
assert first.complete is False
assert store.accept(chunk(data, 0, 32768), now_ns=1) == first
last = store.accept(chunk(data, 32768, len(data)-32768), now_ns=2)
assert last.complete is True
assert store.resolve(last.resource_sha256, kind="MODEL").path.read_bytes() == data
```

## Task2: Defined Content And Persistent Integrity

Files:icd_runtime/contract.py;icd_gateway/resources.py;tests/icd_gateway/test_resources.py.

Interfaces:`Contract.validate_resource(kind,value)` validates only TERRAIN->TerrainResource,OBSTACLES->ObstaclesResource,MISSION->MissionLoad. `StoredResource` has actual sha/kind/size/path and content status (DEFINED_JSON or OPAQUE_BYTES), not readiness. `resolve` rehashes and revalidates actual disk bytes rather than trusting a file name/manifest. Private storage manifests are not new wire fields.

- [x] Add RED tests for closed resource Schema,terrain rows*columns,duplicate obstacle IDs,mission execute index,strict JSON bytes,completed reopen/readback,metadata tamper,byte tamper,busy/stale root and bounded metadata.
- [x] Implement the public resource-definition validator and content checks before publish and on reopen/resolve.
- [x] Run focused tests to GREEN and common regressions (initial31 tests; expanded final scope recorded below).

Test anchor:
```python
terrain["heights_m"] = [0, 0, 0, 0, 0]
assert_rejected("RESOURCE", lambda: store.accept(chunk(canonicalize(terrain)), now_ns=0))
assert store.completed_count == 0
```

## Task3: Verification And Handoff

Files:icd_gateway/README.md;docs/superpowers/plans/2026-10-02-input-simulator-overall.md;docs/superpowers/plans/linux-development-backlog.md;artifacts/icd_gateway/w3-1-validation.json.

- [x] Run read-only code review and address reproduced findings through RED/GREEN tests (completed in the later W3.2 checkpoint).
- [x] Run common single test entry,34 selected static regressions,85 goldens/800RAW,static QA,pip check and compileall; verify14 source files and41 ownership rows.
- [x] Append Linux filesystem/permission/disk/crash tests and actual resource-to-model/video consumer requirements to existing L-002/L-004/L-010/L-012/L-013/L-017; do not close them from current-host evidence.
- [x] Record the remaining common background-resource integration separately from Linux target work. Software validation is complete; package review remains open rather than marking the phase fully closed.

## Scoped Result And Open Review

2026-10-03 final common runner:232 tests pass (54 runtime,171 gateway/source including44 resource storage tests and14 actualUDP tests,3 ledger,4 single-file), plus34 selected existing static regressions.85 golden fragments/800RAW,static QA10446/2427,pip/compile and14 byte-exact embedded sources pass. Phase evidence isartifacts/icd_gateway/w3-1-validation.json; Windows is only the execution host, not another product branch.

Independent read-only review reproduced the unsafe recursive deletion of a same-named staging directory; the targeted RED/GREEN test now proves refusal without deletion. The subsequent independent review was interrupted by usage limits, so Task3 review remains unchecked. Primary RED/GREEN additionally fixes hard-link external-file mutation,file-create slot leakage,metadata disk-margin omission and valid integral JSON floating representations producing noninteger file offsets. Expanded final tests pass but do not replace the missing complete independent review.

The store is implemented and software-verified, not installed as a wire consumer or formally released. Resource background integration,full content/activation semantics,three input-source execution,six tool branches,management API,actual model/video evidence and all17 Linux targets remain required. Overall goal stays active; this evidence does not close fullW3/M2/M4.

2026-10-03 W3.2 checkpoint update: the complete independent read-only review of this storage foundation and the later service is now finished. Reproduced ownership/cleanup/state-gate issues were RED/GREEN fixed and rechecked; no unresolved actionable findings remain in the latest reviewed code. The historical W3.1 report and interruption record are preserved, not rewritten as if review was complete then. See artifacts/icd_gateway/w3-2-validation.json for current service scope, target qualification gaps and actual VIDEO byte transfer; MODEL/TERRAIN wire submission remains TARGET_MISSING until actual state/contract gates exist.
