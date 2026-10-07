import copy
from dataclasses import FrozenInstanceError, asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from common import EXPECTED, INTERFACES, ROOT, GatewayTest, message
from icd_runtime.json_codec import canonicalize


def source_inputs():
    return json.loads((INTERFACES / "input-simulator-v0.3.examples.json").read_bytes())["source_inputs"]


def resources():
    return {ref["resource_id"]: (INTERFACES / ref["file_name"]).read_bytes()
            for ref in source_inputs()["protocol"]["resources"]}


def stimulus(mid=10):
    return {"message_id": mid, "payload": message(mid)["payload"]}


def row(offset="0", mid=10):
    return canonicalize({"offset_ns": offset, "stimulus": stimulus(mid)}) + b"\n"


def history_input(raw=None):
    raw = row() + row("1000000") if raw is None else raw
    value = source_inputs()
    value["history"] = {
        "source_type": "HISTORY", "history_id": "capture-01",
        "resource": {"resource_id": "engineering-01", "sha256": hashlib.sha256(raw).hexdigest(),
                     "size_bytes": len(raw), "format": "ENGINEERING_JSONL", "encoding": "UTF8",
                     "media_type": "application/x-ndjson", "file_name": "engineering.jsonl"},
        "streams": [{"stream_id": "env", "direction": "TO_36", "original_channel": "CANFD",
                     "message_ids": [10], "records": 2, "clock": "CAPTURE_MONOTONIC", "epoch_ns": "0",
                     "uncertainty_us": 0, "truncated_packets": 0, "lost_packets": 0}],
        "policy": {"mode": "REENCODE", "start_offset_ns": "0", "end_offset_ns": "1000000",
                   "rate": "1X", "execution_mode": "ONLINE", "repeat_count": 1, "repeat_gap_steps": 100,
                   "session_policy": "NEW_SESSION_PER_REPEAT", "rewrite_fields": [],
                   "filter_direction": "TO_36_ONLY", "seek_policy": "OFFLINE_ONLY",
                   "restore_policy": "RESET_MODEL_AND_CLEAR_QUEUES", "incomplete_capture_policy": "REJECT_ONLINE",
                   "feedback_policy": "COLLECT_NOT_INJECT"},
        "integrity_verified": True, "decoder_baseline_sha256": EXPECTED,
    }
    return value, {**resources(), "engineering-01": raw}


class SourceInputsTests(GatewayTest):
    def audit(self, value=None, blobs=None, **limits):
        from input_simulator.source_inputs import SourceInputAuditor
        return SourceInputAuditor(self.contract, **limits).audit(
            source_inputs() if value is None else value, resources() if blobs is None else blobs,
            model_id="quadrotor_hil")

    def test_auditor_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.source_inputs"),
                             "common three-source audit has not been implemented")

    def test_real_protocol_files_and_all_three_sources_do_not_claim_execution(self):
        value, blobs = history_input()
        original = copy.deepcopy(value)
        result = self.audit(value, blobs)
        self.assertEqual(result.status, "SOURCE_INPUTS_AUDITED_NOT_EXECUTABLE")
        self.assertFalse(result.execution_ready)
        self.assertEqual(len(result.resources), 3)
        self.assertEqual(len(result.history_records), 2)
        self.assertEqual(result.input_document, original)
        self.assertEqual(value, original)
        self.assertIn("SCENARIO_EXECUTION_SEMANTICS", result.pending_checks)
        self.assertNotIn("PROTOCOL_TOOL_PARSING", result.pending_checks)
        self.assertEqual(len(result.protocol.frames), 13)
        self.assertEqual(result.protocol.pending_formats, ())
        self.assertEqual(result.report()["protocol"]["signal_count"], 650)

    def test_actual_protocol_description_is_immutable_and_not_execution_permission(self):
        result = self.audit()
        self.assertEqual(result.protocol.baseline_sha256, EXPECTED)
        self.assertEqual(result.protocol.parsed_formats, ("ICD_JSON", "DBC"))
        with self.assertRaises(FrozenInstanceError):
            result.protocol.frames[0].length = 1
        self.assertFalse(result.execution_ready)
        self.assertIn("TOOL_AND_CONSUMER_QUALIFICATION", result.pending_checks)

    def test_unknown_protocol_format_is_pending_not_parsed(self):
        from test_protocol import supplement
        source, blobs = supplement(raw=b"a,b\n", fmt="CSV")
        value = source_inputs()
        value["protocol"] = source
        result = self.audit(value, blobs)
        self.assertEqual(result.protocol.pending_formats, ("CSV",))
        self.assertIn("PROTOCOL_PARSER:CSV", result.pending_checks)
        self.assertFalse(result.execution_ready)

    def test_equivalent_arxml_is_really_parsed_and_drift_is_rejected(self):
        from test_protocol import NS, arxml_tree, supplement
        source, blobs = supplement()
        value = source_inputs()
        value["protocol"] = source
        self.assertIn("ARXML", self.audit(value, blobs).protocol.parsed_formats)
        tree = arxml_tree()
        tree.find(f".//{{{NS}}}IDENTIFIER").text = "999"
        source, blobs = supplement(tree)
        value["protocol"] = source
        self.rejects("RESOURCE", lambda: self.audit(value, blobs))

    def test_source_baseline_and_component_pins_cannot_drift(self):
        for path in (("baseline_sha256",), ("protocol", "business_schema_sha256"),
                     ("protocol", "wire_catalog_sha256")):
            bad = source_inputs()
            owner = bad if len(path) == 1 else bad[path[0]]
            owner[path[-1]] = "0" * 64
            self.rejects("HASH", lambda: self.audit(bad))

    def test_parsed_only_contract_has_no_verified_resource_authority(self):
        from input_simulator.source_inputs import SourceInputAuditor
        from icd_runtime.contract import Contract
        schema = json.loads((INTERFACES / "input-simulator-business-v0.3.schema.json").read_bytes())
        unverified = Contract(schema, self.contract.catalogue, EXPECTED)
        self.rejects("HASH", lambda: SourceInputAuditor(unverified).audit(
            source_inputs(), resources(), model_id="quadrotor_hil"))

    def test_missing_mandatory_protocol_artifact_is_rejected(self):
        for fmt in ("DBC", "ICD_JSON"):
            bad = source_inputs()
            ref = next(r for r in bad["protocol"]["resources"] if r["format"] == fmt)
            ref["format"] = "ARXML"
            self.rejects("RESOURCE", lambda: self.audit(bad))

    def test_rehashed_replacement_catalog_or_dbc_is_still_rejected(self):
        for index in (0, 1):
            bad, blobs = source_inputs(), resources()
            ref = bad["protocol"]["resources"][index]
            replacement = blobs[ref["resource_id"]] + b" "
            blobs[ref["resource_id"]] = replacement
            ref.update(sha256=hashlib.sha256(replacement).hexdigest(), size_bytes=len(replacement))
            self.rejects("HASH", lambda: self.audit(bad, blobs))

    def test_duplicate_resource_ids_and_missing_actual_bytes_fail(self):
        bad = source_inputs()
        bad["protocol"]["resources"][1]["resource_id"] = bad["protocol"]["resources"][0]["resource_id"]
        self.rejects("RESOURCE", lambda: self.audit(bad))
        self.rejects("RESOURCE", lambda: self.audit(blobs={}))

    def test_size_hash_encoding_and_resource_budgets(self):
        bad = source_inputs()
        bad["protocol"]["resources"][0]["size_bytes"] += 1
        self.rejects("RESOURCE", lambda: self.audit(bad))
        blobs = resources()
        key = next(iter(blobs))
        blobs[key] = b"x" * len(blobs[key])
        self.rejects("HASH", lambda: self.audit(blobs=blobs))
        bad = source_inputs()
        bad["protocol"]["resources"][1]["encoding"] = "BINARY"
        self.rejects("RESOURCE", lambda: self.audit(bad))
        self.rejects("CAPACITY", lambda: self.audit(max_resource_bytes=100))
        self.rejects("CAPACITY", lambda: self.audit(max_total_bytes=170000))

    def test_protocol_ids_must_be_unique_known_and_include_used_inputs(self):
        for ids, code in (([10, 10], "RESOURCE"), ([46], "UNSUPPORTED"), ([7], "RESOURCE")):
            bad = source_inputs()
            bad["protocol"]["message_ids"] = ids
            self.rejects(code, lambda: self.audit(bad))

    def test_scenario_events_and_assertions_have_unique_namespaces(self):
        for field in ("events", "assertions"):
            bad = source_inputs()
            bad["scenario"][field].append(copy.deepcopy(bad["scenario"][field][0]))
            self.rejects("RESOURCE", lambda: self.audit(bad))

    def test_fault_and_model_eligibility_are_not_bypassed(self):
        bad = source_inputs()
        bad["scenario"]["events"][0]["type"] = "FAULT"
        self.rejects("RESOURCE", lambda: self.audit(bad))
        bad = source_inputs()
        bad["scenario"]["events"][0]["stimulus"] = stimulus(8)
        self.rejects("MODEL", lambda: self.audit(bad))

    def test_nonnumeric_assertion_cannot_use_tolerance_or_order(self):
        for changes in ({"expected": True, "tolerance": 1}, {"expected": "OK", "operator": "GT"}):
            bad = source_inputs()
            bad["scenario"]["assertions"][0].update(changes)
            self.rejects("RESOURCE", lambda: self.audit(bad))

    def test_periodic_stop_requires_prior_unique_start(self):
        bad = source_inputs()
        base = bad["scenario"]["events"][0]
        stop = {k: v for k, v in base.items() if k != "stimulus"}
        stop.update(type="PERIODIC_STOP", sender_id="p")
        bad["scenario"]["events"][0] = stop
        self.rejects("RESOURCE", lambda: self.audit(bad))
        start = {**base, "type": "PERIODIC_START", "sender_id": "p", "period_steps": 80, "count": 2}
        stop.update(event_id="stop", at_step=300)
        bad["scenario"]["events"] = [stop, start]
        self.audit(bad)
        second = {**start, "event_id": "second", "at_step": 301}
        bad["scenario"]["events"].append(second)
        self.rejects("RESOURCE", lambda: self.audit(bad))

    def test_null_both_sources_and_unknown_scenario_field_fail_closed(self):
        bad = source_inputs()
        bad["scenario"] = None
        self.rejects("SCHEMA", lambda: self.audit(bad))
        bad = source_inputs()
        bad["scenario"]["events"][0]["header"] = message(10)["header"]
        self.rejects("SCHEMA", lambda: self.audit(bad))

    def test_snapshot_and_decoded_records_are_immutable(self):
        value, blobs = history_input()
        result = self.audit(value, blobs)
        value["scenario"]["seed"] = 2
        view = result.input_document
        view["scenario"]["seed"] = 3
        self.assertEqual(result.input_document["scenario"]["seed"], 1)
        decoded = result.history_records[0].stimulus
        decoded["payload"]["wind_n_mps"] = 99
        self.assertNotEqual(result.history_records[0].stimulus["payload"]["wind_n_mps"], 99)
        with self.assertRaises(FrozenInstanceError):
            result.execution_ready = True

    def test_history_only_is_allowed_and_offset_uint64_is_exact(self):
        raw = row("18446744073709551614") + row("18446744073709551615")
        value, blobs = history_input(raw)
        value["scenario"] = None
        value["history"]["policy"].update(start_offset_ns="18446744073709551614",
                                         end_offset_ns="18446744073709551615")
        result = self.audit(value, blobs)
        self.assertEqual(result.history_records[-1].offset_ns, 18446744073709551615)

    def test_history_decoder_pin_direction_and_duplicate_ids(self):
        for change, code in (("pin", "HASH"), ("direction", "AUTHORIZATION"), ("id", "RESOURCE")):
            value, blobs = history_input()
            if change == "pin":
                value["history"]["decoder_baseline_sha256"] = "0" * 64
            elif change == "direction":
                value["history"]["streams"][0].update(direction="FROM_36", message_ids=[130])
            else:
                value["history"]["streams"].append(copy.deepcopy(value["history"]["streams"][0]))
            self.rejects(code, lambda: self.audit(value, blobs))

    def test_history_rows_are_closed_valid_non_decreasing_and_bounded(self):
        invalid = (row("1000000") + row("0"), row("18446744073709551616"),
                   b'{"offset_ns":"0","stimulus":{},"private":0}\n',
                   b'{"offset_ns":"0","offset_ns":"1","stimulus":{}}\n',
                   b'\xef\xbb\xbf' + row(), b'\xff\n', row() + b'\n',
                   canonicalize({"offset_ns": "0", "stimulus": {
                       "message_id": 130, "payload": message(130)["payload"]}}) + b'\n')
        for raw in invalid:
            value, blobs = history_input(raw)
            from icd_runtime.errors import ICDError
            with self.subTest(raw=raw[:40]), self.assertRaises(ICDError):
                self.audit(value, blobs)
        value, blobs = history_input()
        self.rejects("CAPACITY", lambda: self.audit(value, blobs, max_records=1))

    def test_history_actual_counts_message_ids_and_time_window_are_verified(self):
        for change in ("count", "ids", "start", "end", "reversed"):
            value, blobs = history_input()
            if change == "count":
                value["history"]["streams"][0]["records"] = 3
            elif change == "ids":
                value["history"]["streams"][0]["message_ids"] = [7]
            elif change == "start":
                value["history"]["policy"]["start_offset_ns"] = "1000001"
            elif change == "end":
                value["history"]["policy"]["end_offset_ns"] = "1000001"
            else:
                value["history"]["policy"].update(start_offset_ns="1", end_offset_ns="0")
            self.rejects("RESOURCE", lambda: self.audit(value, blobs))

    def test_incomplete_online_rejected_offline_never_claims_complete_capture(self):
        for field in ("truncated_packets", "lost_packets"):
            value, blobs = history_input()
            value["history"]["streams"][0][field] = 1
            self.rejects("RESOURCE", lambda: self.audit(value, blobs))
            value["history"]["policy"].update(execution_mode="OFFLINE", rate="2X")
            result = self.audit(value, blobs)
            self.assertFalse(result.complete_capture)
            self.assertFalse(result.execution_ready)

    def test_jsonl_cannot_claim_raw_replay_or_original_session_rebuild(self):
        for mode in ("RAW_VALIDATED", "SESSION_REBUILD"):
            value, blobs = history_input()
            value["history"]["policy"]["mode"] = mode
            if mode == "RAW_VALIDATED":
                value["history"]["policy"]["session_policy"] = "CURRENT_VALID_SESSION"
            self.rejects("UNSUPPORTED", lambda: self.audit(value, blobs))

    def test_invalid_capture_cannot_pass_by_self_declared_integrity(self):
        value, blobs = history_input(b"not-a-capture")
        value["history"]["resource"].update(format="PCAPNG", encoding="BINARY")
        self.rejects("RESOURCE", lambda: self.audit(value, blobs))

    def test_three_actual_capture_containers_are_parsed_not_business_decoded(self):
        from test_capture import pcap, pcapng
        for fmt, raw in (("CAN_LOG", b"(1.000000001) can0 600#01\n"), ("PCAP", pcap()), ("PCAPNG", pcapng())):
            with self.subTest(fmt=fmt):
                value, blobs = history_input(raw)
                value["history"]["resource"].update(format=fmt, encoding="UTF8" if fmt == "CAN_LOG" else "BINARY")
                result = self.audit(value, blobs)
                self.assertEqual(result.capture.format, fmt)
                self.assertEqual(len(result.capture.packets), 1)
                self.assertEqual(result.report()["capture_container"]["packet_count"], 1)
                self.assertFalse(result.history_decoded)
                self.assertEqual(result.history_records, ())
                self.assertNotIn(f"HISTORY_PARSER:{fmt}", result.pending_checks)
                self.assertIn("HISTORY_STREAM_CLOCK_AND_FORMAL_WIRE_DECODING", result.pending_checks)
                self.assertIn("HISTORY_SESSION_CLOCK_RESTORE_AND_REPLAY", result.pending_checks)
                self.assertFalse(result.execution_ready)
                self.assertIsNone(result.complete_capture)
                with self.assertRaises(FrozenInstanceError):
                    result.capture.packets[0].payload = b"replacement"

    def test_actual_capture_truncation_and_loss_reject_online_without_trusting_declaration(self):
        from test_capture import ethernet, option, pcap, pcapng
        import struct
        for fmt, raw in (("PCAP", pcap([(1, 0, ethernet()[:20])], wirelen=100)),
                         ("PCAPNG", pcapng(opts=option(4, struct.pack("<Q", 1))))):
            value, blobs = history_input(raw)
            value["history"]["resource"].update(format=fmt, encoding="BINARY")
            self.rejects("RESOURCE", lambda: self.audit(value, blobs))
            value["history"]["policy"].update(execution_mode="OFFLINE", rate="2X")
            result = self.audit(value, blobs)
            self.assertFalse(result.complete_capture)
            self.assertFalse(result.execution_ready)
            self.assertFalse(result.history_decoded)

    def test_capture_packet_capacity_and_missing_can_utf8_encoding(self):
        from test_capture import ethernet, pcap
        value, blobs = history_input(pcap([(1, 0, ethernet()), (2, 0, ethernet())]))
        value["history"]["resource"].update(format="PCAP", encoding="BINARY")
        self.rejects("CAPACITY", lambda: self.audit(value, blobs, max_records=1))
        value, blobs = history_input(b"(1) can0 600#01\n")
        value["history"]["resource"].update(format="CAN_LOG", encoding="BINARY")
        self.rejects("RESOURCE", lambda: self.audit(value, blobs))

    def test_explicit_capture_bindings_enable_real_logical_decode_without_execution(self):
        from input_simulator.source_inputs import SourceInputAuditor
        from test_capture import pcap
        from test_history import history, udp_packet
        from input_simulator.history import CaptureBinding
        from icd_runtime.wire import WireCodec
        raw = pcap([(1, 0, udp_packet(WireCodec(self.contract).encode(message(7), "UDP")[0]))])
        value, blobs = history_input(raw)
        value["history"] = history(raw, [7])
        value["scenario"] = None
        binding = CaptureBinding("env", "ETH_0", "PCAP:0:0", "interface-0", "clock-0")
        audit = SourceInputAuditor(self.contract).audit(value, blobs, model_id="quadrotor_hil", capture_bindings=(binding,))
        self.assertEqual(audit.history_records[0].message, message(7))
        self.assertTrue(audit.history_decoded)
        self.assertFalse(audit.execution_ready)
        self.assertIsNone(audit.complete_capture)
        self.assertNotIn("HISTORY_STREAM_CLOCK_AND_FORMAL_WIRE_DECODING", audit.pending_checks)
        self.assertIn("HISTORY_CLOCK_MEASUREMENT_AND_REPLAY_AUTHORIZATION", audit.pending_checks)
        report = audit.report()
        self.assertTrue(report["capture_container"]["history_decoded"])
        self.assertFalse(report["decoded_capture"]["clock_measured"])
        self.assertEqual(report["decoded_capture"]["input_records"], 1)
        self.assertEqual(report["decoded_capture"]["feedback_records"], 0)
        self.assertEqual(report["capture_bindings_sha256"], hashlib.sha256(canonicalize([asdict(binding)])).hexdigest())
        self.assertNotIn("capture_bindings", audit.input_document)

    def test_online_scenario_replay_cannot_bypass_actual_incomplete_capture(self):
        from test_capture import ethernet, option, pcap, pcapng
        import struct
        for fmt, raw in (("PCAP", pcap([(1, 0, ethernet()[:20])], wirelen=100)),
                         ("PCAPNG", pcapng(opts=option(4, struct.pack("<Q", 1))))):
            value, blobs = history_input(raw)
            value["history"]["resource"].update(format=fmt, encoding="BINARY")
            online = copy.deepcopy(value["history"]["policy"])
            value["history"]["policy"].update(execution_mode="OFFLINE", rate="2X")
            value["scenario"]["events"].append({
                "event_id": "online-replay", "at_step": 1, "priority": 10,
                "link_id": "CANREPLAY", "type": "REPLAY", "history_id": "capture-01", "policy": online})
            self.rejects("RESOURCE", lambda: self.audit(value, blobs))

    def test_unrecognized_model_and_bad_audit_limits_fail(self):
        from input_simulator.source_inputs import SourceInputAuditor
        value = source_inputs()
        value["scenario"]["events"] = [value["scenario"]["events"][1]]
        self.rejects("MODEL", lambda: SourceInputAuditor(self.contract).audit(
            value, resources(), model_id="unknown"))
        for limit in (0, -1, True, 1.5):
            self.rejects("CAPACITY", lambda: SourceInputAuditor(self.contract, max_records=limit))

    def test_replay_event_policy_is_checked_against_actual_engineering_capture(self):
        value, blobs = history_input()
        event = {"event_id": "replay", "at_step": 1, "priority": 10, "link_id": "CANREPLAY",
                 "type": "REPLAY", "history_id": "capture-01", "policy": copy.deepcopy(value["history"]["policy"])}
        event["policy"]["end_offset_ns"] = "1000001"
        value["scenario"]["events"].append(event)
        self.rejects("RESOURCE", lambda: self.audit(value, blobs))
        event["policy"]["end_offset_ns"] = "1000000"
        self.audit(value, blobs)
        event["policy"]["mode"] = "SESSION_REBUILD"
        self.rejects("UNSUPPORTED", lambda: self.audit(value, blobs))

    def test_ambiguous_engineering_stream_and_epoch_overflow_are_rejected(self):
        value, blobs = history_input()
        other = copy.deepcopy(value["history"]["streams"][0])
        other["stream_id"] = "ambiguous"
        value["history"]["streams"].append(other)
        self.rejects("RESOURCE", lambda: self.audit(value, blobs))
        value["history"]["streams"].pop()
        value["history"]["streams"][0]["epoch_ns"] = "18446744073709551615"
        self.rejects("RESOURCE", lambda: self.audit(value, blobs))

    def test_history_offline_rate_and_rewrite_uniqueness_remain_frozen(self):
        value, blobs = history_input()
        value["history"]["policy"]["rate"] = "2X"
        self.rejects("SCHEMA", lambda: self.audit(value, blobs))
        value["history"]["policy"]["execution_mode"] = "OFFLINE"
        self.audit(value, blobs)
        value["history"]["policy"]["rewrite_fields"] = ["SESSION", "SESSION"]
        self.rejects("RESOURCE", lambda: self.audit(value, blobs))

    def test_file_name_is_metadata_not_a_resource_lookup_path(self):
        value = source_inputs()
        value["protocol"]["resources"][0]["file_name"] = "../../unrelated.json"
        self.audit(value)


class SourceInputCLITests(GatewayTest):
    def run_cli(self, folder, *, corrupt=False, inputs=None, blobs=None, bindings=None):
        inputs = source_inputs() if inputs is None else inputs
        blobs = resources() if blobs is None else blobs
        paths = {}
        for i, (key, raw) in enumerate(blobs.items()):
            path = folder / f"resource-{i}"
            path.write_bytes(raw + (b"x" if corrupt and i == 0 else b""))
            paths[key] = str(path)
        inputs["protocol"]["resources"][0]["file_name"] = "../../must-not-open.json"
        (folder / "inputs.json").write_bytes(canonicalize(inputs))
        (folder / "paths.json").write_bytes(canonicalize(paths))
        extra = []
        if bindings is not None:
            (folder / "bindings.json").write_bytes(canonicalize(bindings))
            extra = ["--capture-bindings", str(folder / "bindings.json")]
        return subprocess.run([
            sys.executable, "-X", "utf8", "-m", "input_simulator.source_inputs",
            "--contract-dir", str(INTERFACES), "--expected-sha256", EXPECTED,
            "--inputs-file", str(folder / "inputs.json"), "--resource-map", str(folder / "paths.json"),
            "--model-id", "quadrotor_hil", *extra], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")

    def test_offline_cli_reads_real_resources_without_network_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            process = self.run_cli(Path(directory))
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["status"], "SOURCE_INPUTS_AUDITED_NOT_EXECUTABLE")
        self.assertFalse(report["execution_ready"])
        self.assertEqual(len(report["resources"]), 2)

    def test_actual_resource_corruption_is_cli_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            process = self.run_cli(Path(directory), corrupt=True)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["error"], "RESOURCE")

    def test_cli_reports_actual_capture_without_granting_history_execution(self):
        from test_capture import pcapng
        inputs, blobs = history_input(pcapng())
        inputs["history"]["resource"].update(format="PCAPNG", encoding="BINARY")
        with tempfile.TemporaryDirectory() as directory:
            process = self.run_cli(Path(directory), inputs=inputs, blobs=blobs)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["capture_container"]["packet_count"], 1)
        self.assertEqual(report["capture_container"]["format"], "PCAPNG")
        self.assertFalse(report["capture_container"]["execution_ready"])
        self.assertFalse(report["history_decoded"])
        self.assertIsNone(report["complete_capture"])
        self.assertIn("HISTORY_STREAM_CLOCK_AND_FORMAL_WIRE_DECODING", report["pending_checks"])

    def test_cli_explicit_local_bindings_decode_and_reject_unknown_keys(self):
        from test_capture import pcap
        from test_history import history, udp_packet
        from input_simulator.history import CaptureBinding
        from icd_runtime.wire import WireCodec
        raw = pcap([(1, 0, udp_packet(WireCodec(self.contract).encode(message(7), "UDP")[0]))])
        inputs, blobs = history_input(raw)
        inputs["history"] = history(raw, [7])
        inputs["scenario"] = None
        bindings = [asdict(CaptureBinding("env", "ETH_0", "PCAP:0:0", "interface-0", "clock-0"))]
        with tempfile.TemporaryDirectory() as directory:
            good = self.run_cli(Path(directory), inputs=inputs, blobs=blobs, bindings=bindings)
            bindings[0]["guess_direction"] = True
            bad = self.run_cli(Path(directory), inputs=inputs, blobs=blobs, bindings=bindings)
        self.assertEqual(good.returncode, 0, good.stderr)
        report = json.loads(good.stdout)
        self.assertTrue(report["history_decoded"])
        self.assertFalse(report["execution_ready"])
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(json.loads(bad.stdout)["error"], "RESOURCE")
