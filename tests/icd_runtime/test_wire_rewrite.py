import dataclasses
import unittest

from common import EXPECTED, INTERFACES, message
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.wire import Header, WireCodec


class RewriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        cls.wire = WireCodec(cls.contract)

    def test_rewrite_exists(self):
        self.assertTrue(callable(getattr(self.wire, "rewrite", None)), "payload-preserving rewrite missing")

    def test_every_formal_fragment_retains_payload_layout(self):
        for mid, entry in self.contract.messages.items():
            for transport in entry["transports"]:
                original = message(mid)
                header = Header(**original["header"])
                if mid != 1:
                    header = dataclasses.replace(header, session_id=91, sequence=101,
                                                 target_step=200, transaction_id=301)
                for raw in self.wire.encode(original, transport):
                    before = self.wire.decode(raw, transport)
                    rewritten = self.wire.rewrite(raw, transport, header, direction=entry["direction"])
                    after = self.wire.decode(rewritten, transport)
                    with self.subTest(mid=mid, transport=transport, index=before.index):
                        self.assertEqual(after.header, header)
                        self.assertEqual((after.payload, after.index, after.count, after.message_id),
                                         (before.payload, before.index, before.count, before.message_id))
                        if transport == "CANFD":
                            self.assertEqual(rewritten.data[:4], raw.data[:4])
                            self.assertEqual(rewritten.data[20:62], raw.data[20:62])
                            self.assertEqual(rewritten.arbitration_id, raw.arbitration_id)
                        else:
                            self.assertEqual(rewritten[:8], raw[:8])
                            self.assertEqual(rewritten[24:36], raw[24:36])
                            self.assertEqual(rewritten[40:], raw[40:])

    def test_invalid_original_or_header_never_rewritten(self):
        raw = self.wire.encode(message(7), "UDP")[0]
        header = Header(**message(7)["header"])
        for value, new, direction, code in (
                (raw[:-1] + bytes([raw[-1] ^ 1]), header, "TO_36", "CRC"),
                (raw, header, "FROM_36", "AUTHORIZATION"),
                (raw, dataclasses.replace(header, valid_for_ms=999), "TO_36", "SCHEMA"),
                (raw, dataclasses.replace(header, sequence=True), "TO_36", "SCHEMA"),
                (raw, dataclasses.asdict(header), "TO_36", "SCHEMA")):
            with self.assertRaises(ICDError) as caught:
                self.wire.rewrite(value, "UDP", new, direction=direction)
            self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
