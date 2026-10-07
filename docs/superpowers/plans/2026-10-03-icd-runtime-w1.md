# W1 Common ICD Runtime Implementation Plan

> **For agentic workers:** Use executing-plans inline, task by task. The user approved the Windows design and requested implementation on 2026-10-03. Do not delegate or create another checkout for this work package.

**Goal:** Implement one common, source-independent HIL-ICD-1.0 v0.3 validation and wire library; use the current Windows host for offline tests without creating an OS-specific version.

**Architecture:** Read the existing frozen business Schema, ICD catalogue, DBC and semantic document; verify their four-component fingerprint against an externally supplied expected hash. Separate payload validation/encoding, transport framing and bounded reassembly. Neither the encoder nor receiver selects a simulator/real implementation path.

**Tech Stack:** Isolated Python 3.12, jsonschema 4.26.0, jcs 0.2.1, standard-library struct/binascii/unittest. No imports from static-QA vendor directories or changes to legacy requirements.

## Global Constraints

- Baseline: HIL-ICD-1.0; document version 0.3; no changes to frozen interface files.
- 45 input and 14 feedback messages; 13 PACKED_LE messages; offsets and enum codes come from the verified catalogue.
- CANFD: standard ID, FD/BRS, 64-byte frames, 38-byte chunks, 7 fragments maximum, 20ms reassembly deadline.
- UDP: HIL1, 40-byte header, 1160-byte chunks, 1200-byte datagrams, 65536-byte logical limit, 57 fragments maximum, 100ms deadline.
- VIDEO: HIV1, 48-byte header, 1152-byte chunks, 2MiB frames, 1821 fragments maximum, 4 queued frames, 100ms deadline.
- Business reassembly: 64 slots per channel and 8MiB total; duplicates do not extend deadlines; conflicting duplicates invalidate the group.
- Reject unknown IDs/fields, wrong type/range, NaN/Infinity, duplicate JSON keys, BOM, isolated surrogates, invalid CRC/padding/version/fragment layout. Do not fill defaults or clamp.
- Authorization must be checked before reassembly allocation. Session permissions, sequence freshness, lifecycle/model application and E2/E3 belong to W2/target integration, not this library's acceptance claim.
- No original-tool-chain removal, hardware SDK claims, realtime claims or C/Simulink changes.
- User constraint on 2026-10-03: no Windows-specific implementation, platform-dependent business branch or driver replacement. Linux-only work remains pending; the same Python test entry is used on both hosts.

## Files and Interfaces

- `requirements-icd.txt`: isolated runtime dependency pins.
- `icd_runtime/errors.py`: `ICDError(code, detail)`; catalogue-compatible rejection codes.
- `icd_runtime/json_codec.py`: strict JSON parsing and RFC8785 bytes.
- `icd_runtime/contract.py`: `Contract.load(directory, expected_sha256)`; verified catalog and `validate_message(message, direction=None, model_id=None)`.
- `icd_runtime/payload.py`: `PayloadCodec.encode(message_id, payload)` / `decode(message_id, raw)`.
- `icd_runtime/wire.py`: immutable CAN frame/fragment types, CRC and `WireCodec.encode(message, transport)` / `decode(raw, transport, direction)`.
- `icd_runtime/video.py`: `VideoCodec.encode(frame, header)` / `decode(datagram)`; framing only, no pixel decoder/consumer.
- `icd_runtime/reassembly.py`: `Reassembler.push(fragment, channel, direction, authorized, now_ns=None)` / `expire(now_ns=None)`; application owns ACL and serializes access.
- `icd_runtime/__main__.py`: offline frozen-fixture/golden-vector verification; never reports runtime/hardware acceptance.
- `tests/icd_runtime/`: isolated unittest suite; reads fixtures, never rewrites baseline.
- `scripts/test_icd_runtime.py`: common offline test entry, exits nonzero on test failure; no platform branching or automatic dependency installation.
- `icd_runtime/README.md`: setup, public API and explicit remaining gates, not another interface definition.

## Task 1: Verified Baseline and Payloads

- [x] Write `tests/icd_runtime/test_contract_payload.py`: load the actual four-component baseline; mutate each component and expected hash; cover all 59 fixtures and packed enum/boolean/array layouts; reject invalid JSON and field values.
- [x] Run `runtime/icd-venv/Scripts/python.exe -m unittest discover -s tests/icd_runtime -p test_contract_payload.py -v`; observe missing runtime failure before implementation.
- [x] Implement strict parsing, pinned dependencies, hash loading and schema validators; encode only payload, never the BusinessMessage wrapper. Supplement Schema with JSON-domain, uint64-string and immutable header rules.
- [x] Rerun focused tests; verify caller objects and input files unchanged.

Test/API anchor:

```python
contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
codec = PayloadCodec(contract)
for fixture in fixtures:
    message = fixture["value"]
    contract.validate_message(message)
    assert codec.decode(message["message_id"], codec.encode(message["message_id"], message["payload"])) == message["payload"]
```

## Task 2: Business Wire Frames

- [x] Write `test_wire.py`: compare every CANFD/UDP golden fragment byte for byte; decode all messages; corrupt CRC/version/length/flags/ID/padding/DLC; test canonical non-last and last chunk sizes.
- [x] Run focused tests and observe missing wire implementation.
- [x] Implement `CANFrame`, `Fragment`, CRC16/32, `WireCodec`, exact catalogue payload lengths and valid-for checks. Decode rejects direction mismatch without business application.
- [x] Rerun focused tests and all earlier tests.

```python
frames = wire.encode(fixture["value"], "UDP")
assert frames[golden["fragment_index"]].hex() == golden["wire_hex"]
fragment = wire.decode(frames[0], "UDP", direction="TO_36")
```

## Task 3: Video Framing

- [x] Write `test_video.py`: RAW 921600-byte/800-fragment coverage, three existing golden fragments, max frame and header/codec/CRC failures, exact RAW size, frame identity.
- [x] Run focused tests and observe missing video implementation.
- [x] Implement framing for RAW/H264/H265 with uint64 PTS, exact count/length and CRC. Actual H26x decoding, metadata association and stream authorization remain W2/video integration gates.
- [x] Rerun video and earlier tests.

```python
packets = video.encode(bytes(921600), header)
assert len(packets) == 800
assert packets[400].hex() == video_golden["wire_hex"]
```

## Task 4: Bounded Reassembly

- [x] Write `test_reassembly.py`: reversed order, missing/duplicate/conflicting fragments, authorization, per-channel/direction isolation, fixed monotonic deadlines, 64/4 slot and 8MiB boundaries, complete logical payload validation.
- [x] Run focused tests and observe missing reassembly implementation.
- [x] Implement capacity reservation before allocation, consistent-header comparison, group removal on failure/completion/expiry, exact total-length verification and hash of complete video bytes. No allocation for unauthorized senders.
- [x] Rerun all W1 tests.

```python
assert assembler.push(fragment, channel="ETH_0", direction="TO_36", authorized=True, now_ns=0) is None
expired_keys = assembler.expire(now_ns=100_000_000)
assert len(expired_keys) == 1
assert assembler.reserved_bytes == 0
```

## Task 5: Common Entry, Evidence and Review

- [x] Write CLI/self-check tests before implementing CLI; require all 85 golden fragments, 59 logical messages and static-only boundary in output.
- [x] Add a single Python entry and usage doc; isolate dependencies in ignored `runtime/icd-venv`, not old Python environment. Do not create separate PowerShell/Bash product implementations.
- [x] Run all W1 tests, offline CLI, existing static contract QA, and compatible existing Python tests. Preserve original input hashes and distinguish preexisting/environment failures.
- [x] Inspect new source for QA imports, mock/real branching, unbounded storage and protocol changes; document exact test counts and unexecuted gates.
- [x] Update plan checkboxes from actual results only. Leave W2-W5 pending. No automatic commit/merge; changes stay available for user review.

## Review Checkpoints

Each task has its own red/green cycle. W1 is complete only when all task deliverables and verification commands succeed. This plan does not claim a service receiver, actual UDP network transport, three-source executor, E2/E3 consumer, tool qualification or real3.3 replacement.

## Execution Result: 2026-10-03

W1 offline deliverables are verified on the current Windows host using one common implementation. All 50 W1 tests, 4 single-file contract tests and 34 selected existing static regressions passed; v0.3 static QA reported 10446 checks including 2427 negative checks. Offline codec self-check verified 59 messages, 72 transport combinations, 85 independently pinned golden fragments and an 800-fragment RAW frame. The four-component baseline and all 14 embedded contract sources remain unchanged.

Read-only review found an offline fixture/manifest trust gap. A failing regression reproduced empty, missing and duplicated golden vectors; independent raw fixture pins and exact unique fragment coverage now reject these alterations. Actual 8193-message completion traffic also verified the 8192-entry terminal-cache bound and oldest-entry eviction. Review found no remaining important W1 issue after the fix.

Evidence: `artifacts/icd_runtime/w1-validation.json`. This completes only W1, not the entire M1 or M2. Linux execution, formal release gating, session service, network sockets, model consumption, original-tool qualification, hardware and real3.3 replacement remain unverified. No Windows-specific driver or substitute toolchain was implemented, and no commit or merge was made.
