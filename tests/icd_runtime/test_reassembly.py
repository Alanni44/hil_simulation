import dataclasses
import hashlib
import importlib.util

from common import EXPECTED, INTERFACES, ICDTest, message


class ReassemblyAvailabilityTests(ICDTest):
    def test_bounded_common_reassembly_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_runtime.reassembly"), "bounded reassembly missing")


class ReassemblyTests(ICDTest):
    def setUp(self):
        from icd_runtime.contract import Contract
        from icd_runtime.wire import WireCodec
        from icd_runtime.video import VideoCodec, VideoHeader
        from icd_runtime.reassembly import Reassembler
        self.contract = Contract.load(INTERFACES, expected_sha256=EXPECTED)
        self.wire = WireCodec(self.contract)
        self.video = VideoCodec(self.contract)
        self.video_header = VideoHeader(1, 1, 0, 1000, 0, "RAW")
        self.assembler = Reassembler(self.contract)

    def fragments(self, value=None, transport="UDP"):
        value = value or message(3)
        return [self.wire.decode(p, transport) for p in self.wire.encode(value, transport)]

    def push(self, fragment, channel="ETH_0", direction="TO_36", time=0, authorized=True):
        return self.assembler.push(fragment, channel=channel, direction=direction,
                                   authorized=authorized, now_ns=time)

    def test_all_transports_reassemble_in_reverse_order(self):
        for transport, mid in (("UDP", 3), ("CANFD", 12)):
            value = message(mid)
            result = None
            for fragment in reversed(self.fragments(value, transport)):
                result = self.push(fragment, channel="CANFD_0" if transport == "CANFD" else "ETH_0")
            self.assertEqual(result.message, value)
            self.assertEqual(self.assembler.reserved_bytes, 0)
            self.assertEqual(self.assembler.pending_count, 0)

    def test_unauthorized_direction_or_channel_never_allocates(self):
        fragment = self.fragments()[0]
        self.rejects("AUTHORIZATION", lambda: self.push(fragment, authorized=False))
        self.rejects("AUTHORIZATION", lambda: self.push(fragment, authorized=1))
        self.rejects("AUTHORIZATION", lambda: self.push(fragment, direction="FROM_36"))
        self.rejects("SCHEMA", lambda: self.push(fragment, channel=""))
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_unknown_channel_and_wrong_medium_never_allocate(self):
        fragment = self.fragments()[0]
        self.rejects("AUTHORIZATION", lambda: self.push(fragment, channel="ETH_unregistered"))
        self.rejects("AUTHORIZATION", lambda: self.push(fragment, channel="CAN_0"))
        self.assertEqual(self.assembler.pending_count, 0)

    def test_channel_half_groups_cannot_be_spliced(self):
        fragments = self.fragments()
        self.assertIsNone(self.push(fragments[0], channel="ETH_0"))
        for fragment in fragments[1:]:
            self.assertIsNone(self.push(fragment, channel="ETH_1"))
        self.assertEqual(self.assembler.pending_count, 2)
        result = None
        for fragment in fragments[1:]:
            result = self.push(fragment, channel="ETH_0")
        self.assertEqual(result.message, message(3))

    def test_identical_duplicate_never_extends_fixed_deadline(self):
        fragment = self.fragments()[0]
        self.push(fragment, time=0)
        self.assertIsNone(self.push(fragment, time=99_999_999))
        self.assertEqual(len(self.assembler.expire(now_ns=100_000_000)), 1)
        self.assertEqual(self.assembler.reserved_bytes, 0)
        self.rejects("TIMEOUT", lambda: self.push(fragment, time=100_000_001))

    def test_conflict_invalidates_whole_group_and_blocks_restart(self):
        fragment = self.fragments()[0]
        self.push(fragment)
        bad = dataclasses.replace(fragment, payload=b"x" + fragment.payload[1:])
        self.rejects("FRAGMENT", lambda: self.push(bad))
        self.assertEqual(self.assembler.reserved_bytes, 0)
        self.rejects("FRAGMENT", lambda: self.push(fragment, time=1))

    def test_header_inconsistency_invalidates_group(self):
        fragments = self.fragments()
        self.push(fragments[0])
        bad = dataclasses.replace(fragments[1], header=dataclasses.replace(fragments[1].header, target_step=1001))
        self.rejects("FRAGMENT", lambda: self.push(bad))
        self.assertEqual(self.assembler.pending_count, 0)

    def test_completed_retransmission_cannot_emit_second_completion(self):
        fragment = self.fragments(message(7))[0]
        self.assertEqual(self.push(fragment).message, message(7))
        self.rejects("DUPLICATE", lambda: self.push(fragment))

    def test_can_timeout_is_20ms(self):
        fragment = self.fragments(message(12), "CANFD")[0]
        self.push(fragment, channel="CANFD_0", time=0)
        self.assertEqual(self.assembler.expire(now_ns=19_999_999), [])
        self.assertEqual(len(self.assembler.expire(now_ns=20_000_000)), 1)

    def test_64_slots_per_channel_no_eviction(self):
        for seq in range(1, 65):
            value = message(3)
            value["header"].update(sequence=seq, transaction_id=seq)
            self.assertIsNone(self.push(self.fragments(value)[0]))
        value = message(3)
        value["header"].update(sequence=65, transaction_id=65)
        fragment = self.fragments(value)[0]
        self.rejects("BUFFER_FULL", lambda: self.push(fragment))
        self.assertEqual(self.assembler.pending_count, 64)
        self.assertIsNone(self.push(fragment, channel="ETH_1"))
        self.assertEqual(self.assembler.pending_count, 65)
        self.assembler.expire(now_ns=100_000_000)
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_video_complete_frame_hash_and_four_frame_capacity(self):
        fragments = [self.video.decode(p) for p in self.video.encode(bytes(921600), self.video_header)]
        for index in range(4):
            self.push(dataclasses.replace(fragments[0], header=dataclasses.replace(self.video_header, frame_index=index)))
        fifth = dataclasses.replace(fragments[0], header=dataclasses.replace(self.video_header, frame_index=4))
        self.rejects("BUFFER_FULL", lambda: self.push(fifth))
        result = None
        for fragment in reversed(fragments[1:]):
            result = self.push(fragment)
        self.assertEqual(result.data, bytes(921600))
        self.assertEqual(result.sha256, hashlib.sha256(result.data).hexdigest())
        self.assertEqual(self.assembler.pending_count, 3)

    def test_global_8mib_reservation_is_enforced(self):
        from icd_runtime.video import VideoHeader
        frame = b"\x00\x00\x00\x01" + bytes(2097152 - 4)
        first = self.video.decode(self.video.encode(frame, VideoHeader(1, 1, 0, 1000, 0, "H264"))[0])
        for index in range(4):
            fragment = dataclasses.replace(first, header=dataclasses.replace(first.header, frame_index=index))
            self.push(fragment, channel=f"ETH_{index}")
        self.assertEqual(self.assembler.reserved_bytes, 8388608)
        self.rejects("BUFFER_FULL", lambda: self.push(self.fragments()[0]))
        self.assembler.expire(now_ns=100_000_000)
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_reassembled_invalid_payload_is_rejected_not_returned(self):
        fragment = self.fragments(message(7))[0]
        bad = dataclasses.replace(fragment, payload=b"\x00\x00\x00\x00\x00\x00\xf8\x7f" + fragment.payload[8:])
        self.rejects("SCHEMA", lambda: self.push(bad))
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_clock_cannot_go_backwards_and_terminal_entries_expire(self):
        fragment = self.fragments()[0]
        self.push(fragment, time=10)
        self.rejects("SCHEMA", lambda: self.push(fragment, time=9))
        self.assembler.expire(now_ns=5_100_000_010)
        self.assertEqual(self.assembler.terminal_count, 0)

    def test_terminal_cache_overflow_evicts_oldest_at_8192_entries(self):
        original = self.fragments(message(7))[0]
        self.assertEqual(self.contract.catalogue["policy"]["duplicate_cache_messages"], 8192)
        first = None
        for sequence in range(1, 8194):
            fragment = dataclasses.replace(original, header=dataclasses.replace(
                original.header, sequence=sequence, transaction_id=sequence))
            if first is None:
                first = fragment
            self.assertIsNotNone(self.push(fragment))
            self.assertLessEqual(self.assembler.terminal_count, 8192)
        self.assertEqual(self.assembler.terminal_count, 8192)
        self.rejects("DUPLICATE", lambda: self.push(fragment))
        # Eviction is bounded group memory, not W2's session freshness guarantee.
        self.assertIsNotNone(self.push(first))
        self.assertEqual(self.assembler.terminal_count, 8192)
        self.assertEqual(self.assembler.pending_count, 0)
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_decoded_fragment_metadata_cannot_bypass_reservation_limits(self):
        fragment = self.fragments()[0]
        self.rejects("FRAGMENT", lambda: self.push(dataclasses.replace(fragment, reservation_bytes=1)))
        self.rejects("FRAGMENT", lambda: self.push(dataclasses.replace(fragment, count=999999)))
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_explicit_session_dedup_owner_can_reassemble_complete_retries(self):
        from icd_runtime.reassembly import Reassembler
        self.assembler = Reassembler(self.contract, retain_completed=False)
        fragment = self.fragments(message(7))[0]
        self.assertEqual(self.push(fragment).message, message(7))
        self.assertEqual(self.push(fragment).message, message(7))
        self.assertEqual(self.assembler.terminal_count, 0)

    def test_session_discard_frees_only_its_groups_and_terminal_entries(self):
        value = message(3)
        self.push(self.fragments(value)[0])
        value["header"]["session_id"] = 2
        self.push(self.fragments(value)[0])
        self.push(self.fragments(message(7))[0])
        self.assembler.discard_session(1)
        self.assertEqual(self.assembler.pending_count, 1)
        self.assertEqual(self.assembler.terminal_count, 0)
        self.assembler.discard_session(2)
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_pre_session_namespaces_share_channel_capacity(self):
        opening = message(1)
        for key in ("run_id", "source_id", "vehicle_id", "scenario_id"):
            opening["payload"]["identity"][key] = "\u4e2d" * 128
        fragment = self.fragments(opening)[0]
        for namespace in range(64):
            self.assertIsNone(self.assembler.push(fragment, channel="ETH_0", direction="TO_36", authorized=True,
                                                 now_ns=0, pre_session_namespace=namespace))
        extra = dataclasses.replace(fragment, header=dataclasses.replace(fragment.header, transaction_id=2))
        self.rejects("BUFFER_FULL", lambda: self.assembler.push(extra, channel="ETH_0", direction="TO_36",
                                                               authorized=True, now_ns=0, pre_session_namespace=0))
        self.assertEqual(self.assembler.pending_count, 64)
        self.assembler.discard_session(0)
        self.assertEqual(self.assembler.reserved_bytes, 0)

    def test_pre_session_namespace_cannot_partition_established_business(self):
        fragment = self.fragments(message(7))[0]
        self.rejects("SCHEMA", lambda: self.assembler.push(fragment, channel="ETH_0", direction="TO_36",
                                                          authorized=True, now_ns=0, pre_session_namespace=0))
