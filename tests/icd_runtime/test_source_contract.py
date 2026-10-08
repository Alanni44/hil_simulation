import copy

from common import EXPECTED, INTERFACES, ICDTest, data, message
from icd_runtime.contract import Contract


class SourceContractTests(ICDTest):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.inputs = data("input-simulator-v0.3.examples.json")["source_inputs"]

    def test_source_validation_entry_points_exist(self):
        self.assertTrue(callable(getattr(self.contract, "validate_source_definition", None)),
                        "frozen source definition validator is missing")
        self.assertTrue(callable(getattr(self.contract, "validate_stimulus", None)))

    def test_complete_source_structure_is_unchanged(self):
        value = copy.deepcopy(self.inputs)
        self.contract.validate_source_definition("SourceInputs", value)
        self.assertEqual(value, self.inputs)

    def test_each_source_required_field_and_unknown_key_are_rejected(self):
        for name, value in (("SourceInputs", self.inputs), ("ProtocolSource", self.inputs["protocol"]),
                            ("ScenarioSource", self.inputs["scenario"]),
                            ("ResourceRef", self.inputs["protocol"]["resources"][0])):
            for key in value:
                bad = copy.deepcopy(value)
                del bad[key]
                with self.subTest(definition=name, field=key):
                    self.rejects("SCHEMA", lambda: self.contract.validate_source_definition(name, bad))
            bad = {**value, "private": True}
            self.rejects("SCHEMA", lambda: self.contract.validate_source_definition(name, bad))

    def test_definition_names_are_a_closed_allowlist(self):
        for name in ("Header", "../Header", None, ["SourceInputs"]):
            self.rejects("UNSUPPORTED", lambda: self.contract.validate_source_definition(name, {}))

    def test_component_hashes_are_actual_read_only_copies(self):
        hashes = self.contract.component_hashes
        self.assertEqual(hashes, data("input-simulator-v0.3.baseline.json")["components"])
        hashes["wire_catalog_sha256"] = "0" * 64
        self.assertNotEqual(hashes, self.contract.component_hashes)

    def test_all_45_input_stimuli_and_model_gate(self):
        for mid in range(1, 46):
            value = {"message_id": mid, "payload": message(mid)["payload"]}
            self.contract.validate_stimulus(value)
        value = {"message_id": 8, "payload": message(8)["payload"]}
        self.rejects("MODEL", lambda: self.contract.validate_stimulus(value, model_id="quadrotor_hil"))

    def test_stimulus_cannot_include_session_header_or_feedback(self):
        value = {"message_id": 10, "payload": message(10)["payload"], "header": message(10)["header"]}
        self.rejects("SCHEMA", lambda: self.contract.validate_stimulus(value))
        self.rejects("AUTHORIZATION", lambda: self.contract.validate_stimulus(
            {"message_id": 130, "payload": message(130)["payload"]}))
        self.rejects("SCHEMA", lambda: self.contract.validate_stimulus({"message_id": True, "payload": {}}))

    def test_decimal_uint64_limit_is_preserved_for_replay(self):
        policy = {"mode": "REENCODE", "start_offset_ns": "0", "end_offset_ns": "18446744073709551616",
                  "rate": "1X", "execution_mode": "ONLINE", "repeat_count": 1, "repeat_gap_steps": 0,
                  "session_policy": "NEW_SESSION_PER_REPEAT", "rewrite_fields": [],
                  "filter_direction": "TO_36_ONLY", "seek_policy": "OFFLINE_ONLY",
                  "restore_policy": "RESET_MODEL_AND_CLEAR_QUEUES", "incomplete_capture_policy": "REJECT_ONLINE",
                  "feedback_policy": "COLLECT_NOT_INJECT"}
        self.rejects("SCHEMA", lambda: self.contract.validate_source_definition("ReplayPolicy", policy))

    def test_decimal_time_cannot_use_trailing_newline_to_bypass_range(self):
        for value in ("18446744073709551616\n", "1\n", "0\n", "18446744073709551615\n"):
            payload = message(33)["payload"]
            payload["sender_mono_ns"] = value
            self.rejects("SCHEMA", lambda: self.contract.validate_payload(33, payload))
            stream = {"stream_id": "s", "direction": "TO_36", "original_channel": "CANFD",
                      "message_ids": [10], "records": 1, "clock": "CAPTURE_MONOTONIC", "epoch_ns": value,
                      "uncertainty_us": 0, "truncated_packets": 0, "lost_packets": 0}
            self.rejects("SCHEMA", lambda: self.contract.validate_source_definition("HistoryStream", stream))

    def test_all_ten_event_branches_use_frozen_closed_definitions(self):
        base = {"event_id": "e", "at_step": 1, "priority": 1, "link_id": "ETHGEN"}
        stimulus = {"message_id": 10, "payload": message(10)["payload"]}
        assertion = self.inputs["scenario"]["assertions"][0]
        policy = {"mode": "REENCODE", "start_offset_ns": "0", "end_offset_ns": "1", "rate": "1X",
                  "execution_mode": "ONLINE", "repeat_count": 1, "repeat_gap_steps": 0,
                  "session_policy": "NEW_SESSION_PER_REPEAT", "rewrite_fields": [],
                  "filter_direction": "TO_36_ONLY", "seek_policy": "OFFLINE_ONLY",
                  "restore_policy": "RESET_MODEL_AND_CLEAR_QUEUES", "incomplete_capture_policy": "REJECT_ONLINE",
                  "feedback_policy": "COLLECT_NOT_INJECT"}
        branches = (
            {"type": "SEND", "stimulus": stimulus},
            {"type": "WAVEFORM", "stimulus": stimulus, "field_path": "wind_n_mps",
             "waveform": {"kind": "CONSTANT", "value": 0}, "duration_steps": 10, "sample_period_steps": 1},
            {"type": "PERIODIC_START", "sender_id": "p", "stimulus": stimulus, "period_steps": 80, "count": 1},
            {"type": "PERIODIC_STOP", "sender_id": "p"},
            {"type": "WAIT", "assertion": assertion},
            {"type": "REPLAY", "history_id": "h", "policy": policy},
            {"type": "FAULT", "stimulus": {"message_id": 11, "payload": message(11)["payload"]}},
            {"type": "ASSERT", "assertion": assertion},
            {"type": "END_CLEANUP", "cleanup": self.inputs["scenario"]["cleanup"]},
            {"type": "NEGATIVE_SEND", "stimulus": stimulus, "mutation": {"kind": "CRC_XOR", "xor_mask": 1},
             "expected_error": "CRC", "must_not_apply": True, "authorization_case_id": "T02"},
        )
        for branch in branches:
            value = {**base, **branch}
            with self.subTest(event_type=branch["type"]):
                self.contract.validate_source_definition("Event", value)
                self.rejects("SCHEMA", lambda: self.contract.validate_source_definition("Event", {**value, "private": 1}))
                for key in value:
                    bad = dict(value)
                    del bad[key]
                    self.rejects("SCHEMA", lambda: self.contract.validate_source_definition("Event", bad))


if __name__ == "__main__":
    import unittest
    unittest.main()
