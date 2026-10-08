import copy
import importlib.util
import math
import shutil
import struct
import tempfile
from pathlib import Path

from common import EXPECTED, FIXTURES, INTERFACES, ICDTest, message


class AvailabilityTest(ICDTest):
    def test_runtime_is_a_real_separate_package(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_runtime"),
                             "W1 common runtime has not been implemented")


class ContractPayloadTests(ICDTest):
    @classmethod
    def setUpClass(cls):
        from icd_runtime.contract import Contract
        from icd_runtime.payload import PayloadCodec
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.codec = PayloadCodec(cls.contract)

    def test_baseline_and_all_59_fixtures_without_mutation(self):
        self.assertEqual(self.contract.baseline_sha256, EXPECTED)
        self.assertEqual(len(self.contract.messages), 59)
        for mid, original in FIXTURES.items():
            with self.subTest(message_id=mid):
                value = copy.deepcopy(original)
                self.contract.validate_message(value)
                raw = self.codec.encode(mid, value["payload"])
                self.assertEqual(self.codec.decode(mid, raw), value["payload"])
                self.assertEqual(value, original)

    def test_external_expected_hash_is_mandatory_and_not_trusted_from_file(self):
        from icd_runtime.contract import Contract
        self.rejects("HASH", lambda: Contract.load(INTERFACES, expected_sha256="0" * 64))

    def test_each_frozen_component_tamper_is_rejected(self):
        from icd_runtime.contract import Contract
        for name in ("input-simulator-business-v0.3.schema.json", "input-simulator-icd-v0.3.json",
                     "input-simulator-canfd-v0.3.dbc", "input-simulator-data-contract-v0.3.md"):
            with self.subTest(component=name), tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                for source in INTERFACES.glob("*v0.3*"):
                    shutil.copy2(source, folder / source.name)
                # Test-only fixture corruption; production baseline is read-only.
                target = folder / name
                target.write_bytes(target.read_bytes() + b" ")
                self.rejects("HASH", lambda: Contract.load(folder, expected_sha256=EXPECTED))

    def test_missing_unknown_types_arrays_and_nonfinite_rejected(self):
        for mid in FIXTURES:
            original = message(mid)
            for key in original["payload"]:
                value = copy.deepcopy(original)
                del value["payload"][key]
                with self.subTest(message_id=mid, missing=key):
                    self.rejects("SCHEMA", lambda: self.contract.validate_message(value))
            value = copy.deepcopy(original)
            value["payload"]["unregistered"] = 1
            self.rejects("SCHEMA", lambda: self.contract.validate_message(value))
        for values in ([0, 0, 0], [0, 0, 0, 0, 0], [True, 0, 0, 0],
                       [math.nan, 0, 0, 0], [math.inf, 0, 0, 0], [-1, 0, 0, 0]):
            self.rejects("SCHEMA", lambda: self.codec.encode(7, {"motor_command": values}))

    def test_unknown_id_direction_and_wrong_model_rejected(self):
        self.rejects("UNSUPPORTED", lambda: self.codec.encode(46, {}))
        self.rejects("MODEL", lambda: self.contract.validate_message(message(8), model_id="quadrotor_hil"))
        self.rejects("AUTHORIZATION", lambda: self.contract.validate_message(message(130), direction="TO_36"))
        value = message(1)
        value["message_id"] = True
        self.rejects("SCHEMA", lambda: self.contract.validate_message(value))

    def test_session_open_and_nonzero_session_header_rules(self):
        for key, invalid in (("session_id", 1), ("sequence", 2), ("target_step", 1)):
            value = message(1)
            value["header"][key] = invalid
            self.rejects("SCHEMA", lambda: self.contract.validate_message(value))
        value = message(7)
        value["header"]["session_id"] = 0
        self.rejects("STALE_SESSION", lambda: self.contract.validate_message(value))
        value = message(7)
        value["header"]["valid_for_ms"] = 101
        self.rejects("SCHEMA", lambda: self.contract.validate_message(value))
        value = message(130)
        value["header"]["session_id"] = 0
        value["payload"].update(request_message_id=1, stage="FAILED", error="AUTHORIZATION")
        self.contract.validate_message(value)

    def test_packed_layout_offsets_boolean_and_enum_codes(self):
        value = message(12)["payload"]
        value["motor_5_failed"] = True
        value["motor_6_failed"] = True
        raw = self.codec.encode(12, value)
        self.assertEqual(len(raw), 78)
        self.assertEqual(raw[76:78], b"\x01\x01")
        bad = bytearray(raw)
        bad[48] = 2
        self.rejects("SCHEMA", lambda: self.codec.decode(12, bytes(bad)))
        self.rejects("SCHEMA", lambda: self.codec.decode(12, raw + b"\x00"))
        bad = bytearray(self.codec.encode(130, message(130)["payload"]))
        bad[6] = 255
        self.rejects("SCHEMA", lambda: self.codec.decode(130, bytes(bad)))
        self.rejects("SCHEMA", lambda: self.codec.decode(7, struct.pack("<4d", math.nan, 0, 0, 0)))

    def test_strict_json_rejects_ambiguous_and_noncanonical_input(self):
        from icd_runtime.json_codec import loads, canonicalize
        for raw in (b'\xef\xbb\xbf{}', b'{"x":1,"x":2}', b'{"x":NaN}',
                    b'{"x":Infinity}', b'{"x":1e999}', b'{"x":"\\ud800"}', b'\xff', b'{} trailing'):
            self.rejects("SCHEMA", lambda: loads(raw))
        self.assertEqual(canonicalize({"b": 1e-7, "a": 1.0}), b'{"a":1,"b":1e-7}')
        self.rejects("SCHEMA", lambda: self.codec.decode(4, b'{ "action":"START", "expected_state":"CONFIGURED", "reset_policy":"NOT_APPLICABLE" }'))

    def test_uint64_string_overflow_is_rejected(self):
        value = message(33)["payload"]
        value["sender_mono_ns"] = "18446744073709551615"
        self.codec.encode(33, value)
        value["sender_mono_ns"] = "18446744073709551616"
        self.rejects("SCHEMA", lambda: self.codec.encode(33, value))

    def test_ieee754_exact_large_numbers_are_not_uint64_fields(self):
        from icd_runtime.json_codec import canonicalize
        self.assertEqual(canonicalize({"value": 100000000000000000000}), b'{"value":100000000000000000000}')
        self.rejects("SCHEMA", lambda: canonicalize({"value": 9007199254740993}))

    def test_date_time_fields_reject_invalid_calendar_values(self):
        for text in ("garbageZ", "2026-02-30T12:00:00Z", "2026-10-03T99:00:00Z"):
            value = message(33)["payload"]
            value["utc_time"] = text
            self.rejects("SCHEMA", lambda: self.codec.encode(33, value))
