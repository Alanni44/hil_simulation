# HISTORY Handoff Integration Plan

> **For agentic workers:** Execute this approved handoff integration inline with executing-plans. Do not recreate the third chain or overwrite shared newer code.

**Goal:** Merge the external HISTORY/PCAP delivery into the existing shared simulator, update current documentation, verify, and push the existing development branch.

**Architecture:** Keep the shared frozen ICD, receiver, source authorization, and PROTOCOL/SCENARIO implementation. Import the two HISTORY helper modules, six scripts, four test suites, isolated deployment configuration, historical reports, and all 200 capture/evidence files. Merge only the optional local export filename extension into the common exporter; reject channel/format mismatches and unsafe names.

**Tech Stack:** Existing Python 3.12, unittest, Scapy, cantools/python-can; Linux tcpreplay/tcpdump/iproute2/ethtool for isolated target reruns.

## Global Constraints

- Source: `C:/Users/裴鹏飞/Desktop/code_handoff_33_36_20261006`; never edit the delivered directory.
- Keep the external ICD SHA256 `22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27` and all 14 frozen sources unchanged.
- Do not copy the 22 differing shared snapshots wholesale: preserve receiver/configuration/lifecycle/authorization fixes and the append-only local ledger.
- The old delivered inventory has 237 entries, two outdated hashes, and does not cover later added files. Record actual delivery hashes rather than treating that inventory as current verification.
- Native Linux reruns are not executed on Windows. Imported WSL2 evidence is not current target qualification, actual deployed 3.6 qualification, or model APPLIED/CONSUMED.
- Keep default gateway capabilities `[1]`; the Round 4 diagnostic probe remains explicitly unauthorized by SourceSession and expects standard TARGET_MISSING after admission. Do not turn it into a production sender or silently wire SCENARIO REPLAY to it.
- Keep Linux backlog as the sole outstanding-work ledger, retain old records, leave unrelated files/deletions unstaged, and push `codex/icd-runtime-w1` without force.

## Task 1: Merge The Existing Delivery

Files: `input_simulator/reference_pcap.py`, `input_simulator/replay_network_evidence.py`, `scripts/generate_reference_pcap.py`, `scripts/prepare_history_round2.py`, `scripts/validate_history_round3_linux.sh`, `scripts/validate_history_round3_received.py`, `scripts/validate_history_round4_gateway.py`, `scripts/validate_history_round4_linux.sh`, `config/input-simulator-round4-development.json`, the four delivered HISTORY test suites, and `input_simulator/replay_export.py`.

Interfaces: `ExportBinding.output_name: str | None = None`; existing default filenames remain unchanged. Only the channel's original basename or Ethernet `prepared.pcap` is accepted; filesystem paths, mismatched channels/formats, and duplicate names are rejected. This field is local tooling metadata, not an ICD field.

- [x] Add and run the explicit prepared-filename regression before changing the exporter. Expected failure: missing `output_name` field.
- [x] Import only new delivery files, then merge the small exporter extension. Do not import older `negative.py` or replace its stronger tests.
- [x] Convert the delivered pytest-only Round 4 tests to equivalent unittest coverage so the existing runner exercises them without a new runtime dependency.
- [x] Run the delivered tests, exporter/command/process regression, and current self-generated source tests. Reject any loss of current receiver behavior.

## Task 2: Preserve Evidence And Verify The Merged Receiver

Files: `artifacts/history/round1..round4/`, external HISTORY reports under `docs/`, `docs/internal/model_consumer_bridge_v1.md`, `docs/history/README_HISTORY_PCAP_HANDOFF_20261007.md`, and `tests/icd_gateway/test_history_handoff_integration.py`.

- [x] Import all 200 historical evidence files byte-exact, including failed attempts; freeze their Git newline handling.
- [x] Preserve the external reports as historical/reference documents. The Round 5A asset NO_GO applies to the external searched snapshot, not an automatic verdict on this complete repository. The bridge document is an external design deliverable, not an implemented runtime bridge or replacement external ICD.
- [x] Test freshly reencoded HISTORY bytes with the current default Receiver and opt-in ReceptionService. Verify admission/standard missing-consumer feedback, actual full decoded payload in receive-only mode, retry deduplication, and no model application claim.
- [x] Reparse final Round 3 and Round 4 stored captures with current codecs, confirm SID/header/CRC/payload/ACK correlation, and distinguish historical evidence readback from a new native run.

## Task 3: Update Current Documentation And Publish

Files: `README.md`, `icd_gateway/README.md`, `docs/linux-input-simulator-handoff.md`, `docs/history-handoff-integration.md`, `docs/superpowers/plans/2026-10-02-input-simulator-overall.md`, append-only `docs/superpowers/plans/linux-development-backlog.md`, `.gitattributes`, `.gitignore`, and a new integration verification JSON/log.

- [x] Document current HISTORY entries, exact native-run prerequisites, the original Conda-specific Round 4 runner guard, new evidence directory requirements, and unchanged PROTOCOL/SCENARIO behavior. Do not add a Windows replay backend or claim production replay capability.
- [x] Record the imported source/evidence hashes, shared-file merge decisions, test commands/counts/results, and frozen baseline checks in the integration artifact.
- [x] Run frozen-contract, runtime, ledger, static, relevant shared gateway, and third-chain regression checks. Preserve the old progress JSON/logs as historical results, not current-source acceptance.
- [x] Commit only integration files, validate a clean checkout, push the existing branch using the machine's configured proxy if needed, and compare GitHub branch SHA with local HEAD.


## Integration Safety Fix

- [x] Reproduce failed namespace deletion and mutation of unowned existing output with isolated Bash fake functions (two RED regressions), then fix both and verify GREEN. Keep exit cleanup until validation completes; verify namespace listing and host routes rather than trusting deletion attempts. This is shared Linux diagnostic-script maintenance, not a Windows replay implementation.


Verification: full common runner passed 67 runtime + 1209 gateway + 3 ledger + 4 single-file tests; 34 static tests passed separately (1317 unique, no skips). A clean staged-tree snapshot passed all 46 handoff/export/compatibility tests and the frozen check, and generated 3 NOT_TRANSMITTED samples. Final logs and source/evidence fingerprints are in artifacts/icd_gateway/history-handoff-integration-20261008.json. Publish this verified integration on the existing branch, without staging unrelated workspace changes.
