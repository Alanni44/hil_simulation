import copy
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET

import cantools

from common import EXPECTED, INTERFACES, GatewayTest, message
from test_source_inputs import resources, source_inputs


NS = "http://autosar.org/schema/r4.0"


def database():
    return cantools.database.load_string(
        (INTERFACES / "input-simulator-canfd-v0.3.dbc").read_text(encoding="utf-8"),
        database_format="dbc", strict=True)


def arxml_tree():
    # Independent AUTOSAR representation of the original transport-frame layout.
    def add(parent, name, text=None, **attrs):
        child = ET.SubElement(parent, f"{{{NS}}}{name}", attrs)
        if text is not None:
            child.text = str(text)
        return child

    root = ET.Element(f"{{{NS}}}AUTOSAR")
    package = add(add(root, "AR-PACKAGES"), "AR-PACKAGE")
    add(package, "SHORT-NAME", "HIL")
    elements = add(package, "ELEMENTS")
    cluster = add(elements, "CAN-CLUSTER")
    add(cluster, "SHORT-NAME", "CAN_NETWORK")
    channel = add(add(add(add(cluster, "CAN-CLUSTER-VARIANTS"), "CAN-CLUSTER-CONDITIONAL"),
                      "PHYSICAL-CHANNELS"), "CAN-PHYSICAL-CHANNEL")
    add(channel, "SHORT-NAME", "CAN_BUS")
    triggers = add(channel, "FRAME-TRIGGERINGS")
    for width in (8, 16, 32):
        base = add(elements, "SW-BASE-TYPE")
        add(base, "SHORT-NAME", f"U{width}")
        add(base, "BASE-TYPE-SIZE", width)
        add(base, "BASE-TYPE-ENCODING", "NONE")
        compu = add(elements, "COMPU-METHOD")
        add(compu, "SHORT-NAME", f"C{width}")
        add(compu, "CATEGORY", "LINEAR")
        scale = add(add(add(compu, "COMPU-INTERNAL-TO-PHYS"), "COMPU-SCALES"), "COMPU-SCALE")
        add(scale, "LOWER-LIMIT", 0)
        add(scale, "UPPER-LIMIT", (1 << width) - 1)
        coeffs = add(scale, "COMPU-RATIONAL-COEFFS")
        numerator = add(coeffs, "COMPU-NUMERATOR")
        add(numerator, "V", 0)
        add(numerator, "V", 1)
        add(add(coeffs, "COMPU-DENOMINATOR"), "V", 1)
    packages = add(package, "AR-PACKAGES")
    for frame in database().messages:
        child = add(packages, "AR-PACKAGE")
        add(child, "SHORT-NAME", frame.name)
        items = add(child, "ELEMENTS")
        path = f"/HIL/{frame.name}"
        trigger = add(triggers, "CAN-FRAME-TRIGGERING")
        add(trigger, "SHORT-NAME", f"TRIG_{frame.name}")
        add(trigger, "IDENTIFIER", frame.frame_id)
        add(trigger, "CAN-ADDRESSING-MODE", "STANDARD")
        add(trigger, "CAN-FRAME-RX-BEHAVIOR", "CAN-FD")
        add(trigger, "CAN-FRAME-TX-BEHAVIOR", "CAN-FD")
        add(trigger, "FRAME-REF", f"{path}/{frame.name}", DEST="CAN-FRAME")
        can_frame = add(items, "CAN-FRAME")
        add(can_frame, "SHORT-NAME", frame.name)
        add(can_frame, "FRAME-LENGTH", frame.length)
        mapping = add(add(can_frame, "PDU-TO-FRAME-MAPPINGS"), "PDU-TO-FRAME-MAPPING")
        add(mapping, "SHORT-NAME", "PDU_MAP")
        add(mapping, "PDU-REF", f"{path}/PDU", DEST="I-SIGNAL-I-PDU")
        pdu = add(items, "I-SIGNAL-I-PDU")
        add(pdu, "SHORT-NAME", "PDU")
        add(pdu, "LENGTH", frame.length)
        if frame.cycle_time:
            timing = pdu
            for name in ("I-PDU-TIMING-SPECIFICATIONS", "I-PDU-TIMING", "TRANSMISSION-MODE-DECLARATION",
                         "TRANSMISSION-MODE-TRUE-TIMING", "CYCLIC-TIMING", "TIME-PERIOD"):
                timing = add(timing, name)
            add(timing, "VALUE", frame.cycle_time / 1000)
        mappings = add(pdu, "I-SIGNAL-TO-PDU-MAPPINGS")
        for signal in frame.signals:
            mapping = add(mappings, "I-SIGNAL-TO-I-PDU-MAPPING")
            add(mapping, "SHORT-NAME", f"M_{signal.name}")
            add(mapping, "I-SIGNAL-REF", f"{path}/{signal.name}", DEST="I-SIGNAL")
            add(mapping, "START-POSITION", signal.start)
            add(mapping, "PACKING-BYTE-ORDER", "MOST-SIGNIFICANT-BYTE-LAST")
            i_signal = add(items, "I-SIGNAL")
            add(i_signal, "SHORT-NAME", signal.name)
            add(i_signal, "LENGTH", signal.length)
            add(i_signal, "SYSTEM-SIGNAL-REF", f"{path}/S_{signal.name}", DEST="SYSTEM-SIGNAL")
            props = add(add(add(i_signal, "NETWORK-REPRESENTATION-PROPS"),
                            "SW-DATA-DEF-PROPS-VARIANTS"), "SW-DATA-DEF-PROPS-CONDITIONAL")
            add(props, "BASE-TYPE-REF", f"/HIL/U{signal.length}", DEST="SW-BASE-TYPE")
            system = add(items, "SYSTEM-SIGNAL")
            add(system, "SHORT-NAME", f"S_{signal.name}")
            props = add(add(add(system, "PHYSICAL-PROPS"), "SW-DATA-DEF-PROPS-VARIANTS"),
                        "SW-DATA-DEF-PROPS-CONDITIONAL")
            add(props, "COMPU-METHOD-REF", f"/HIL/C{signal.length}", DEST="COMPU-METHOD")
    return root


def supplement(tree=None, raw=None, fmt="ARXML"):
    raw = ET.tostring(arxml_tree() if tree is None else tree, encoding="utf-8") if raw is None else raw
    source, blobs = source_inputs()["protocol"], resources()
    source["resources"].append({"resource_id": "supplement", "file_name": "supplement.arxml",
                                "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                                "format": fmt, "encoding": "UTF8", "media_type": "application/xml"})
    blobs["supplement"] = raw
    return source, blobs


class ProtocolTests(GatewayTest):
    def parser(self):
        from input_simulator.protocol import ProtocolParser
        return ProtocolParser(self.contract)

    def parsed(self):
        parser = self.parser()
        result = parser.parse(source_inputs()["protocol"], resources())
        return parser, result

    def test_parser_is_available(self):
        self.assertIsNotNone(importlib.util.find_spec("input_simulator.protocol"),
                             "real PROTOCOL parser has not been implemented")

    def test_actual_dbc_has_all_frozen_frames_and_signals(self):
        _, result = self.parsed()
        self.assertEqual(result.baseline_sha256, EXPECTED)
        self.assertEqual(len(result.frames), 13)
        self.assertEqual(sum(len(f.signals) for f in result.frames), 650)
        self.assertEqual(result.parsed_formats, ("ICD_JSON", "DBC"))
        self.assertEqual(result.pending_formats, ())
        for frame in result.frames:
            original = self.contract.entry(frame.message_id)
            self.assertEqual((frame.name, frame.can_id, frame.period_ms),
                             (original["name"], original["can_id"], original["period_ms"]))
            self.assertEqual(frame.length, 64)
            self.assertTrue(frame.is_fd)
            self.assertFalse(frame.is_extended_id)
            self.assertEqual(frame.signals[-1].name, "crc16")
            self.assertEqual(frame.signals[-1].start, 496)
        with self.assertRaises(FrozenInstanceError):
            result.frames[0].length = 1
        with self.assertRaises(FrozenInstanceError):
            result.frames[0].signals[0].start = 1

    def test_original_resource_pins_and_actual_bytes_are_required(self):
        from icd_runtime.contract import Contract
        unverified = Contract(self.contract._schema, self.contract.catalogue, EXPECTED)
        from input_simulator.protocol import ProtocolParser
        self.rejects("HASH", lambda: ProtocolParser(unverified).parse(source_inputs()["protocol"], resources()))
        self.rejects("RESOURCE", lambda: self.parser().parse(source_inputs()["protocol"], {}))
        source, blobs = source_inputs()["protocol"], resources()
        ref = source["resources"][1]
        blobs[ref["resource_id"]] += b" "
        ref.update(size_bytes=len(blobs[ref["resource_id"]]),
                   sha256=hashlib.sha256(blobs[ref["resource_id"]]).hexdigest())
        self.rejects("HASH", lambda: self.parser().parse(source, blobs))

    def test_component_message_and_resource_declarations_cannot_drift(self):
        for change in ("pin", "message", "duplicate", "missing", "encoding"):
            source = source_inputs()["protocol"]
            if change == "pin":
                source["business_schema_sha256"] = "0" * 64
            elif change == "message":
                source["message_ids"].append(200)
            elif change == "duplicate":
                source["resources"].append(copy.deepcopy(source["resources"][0]))
            elif change == "missing":
                source["resources"].pop()
            else:
                source["resources"][1]["encoding"] = "BINARY"
            self.rejects("HASH" if change == "pin" else "UNSUPPORTED" if change == "message" else
                         "SCHEMA" if change == "missing" else "RESOURCE",
                         lambda: self.parser().parse(source, resources()))

    def test_all_can_golden_vectors_and_wire_codec_are_byte_exact(self):
        from icd_runtime.wire import WireCodec
        parser, _ = self.parsed()
        wire = WireCodec(self.contract)
        vectors = json.loads((INTERFACES / "input-simulator-v0.3.golden.json").read_bytes())["vectors"]
        can_vectors = [v for v in vectors if v["transport"] == "CANFD"]
        self.assertTrue(can_vectors)
        for vector in can_vectors:
            value = message(vector["message_id"])
            frames = parser.encode(value)
            self.assertEqual(frames, tuple(wire.encode(value, "CANFD")))
            frame = frames[vector["fragment_index"]]
            self.assertEqual(frame.data.hex(), vector["wire_hex"])
            self.assertEqual(frame.arbitration_id, vector["can_id"])
            direction = self.contract.entry(vector["message_id"])["direction"]
            self.assertEqual(parser.decode_frame(frame, direction=direction), wire.decode(frame, "CANFD", direction=direction))

    def test_unparsed_or_failed_parser_cannot_encode_or_decode(self):
        from icd_runtime.wire import WireCodec
        frame = WireCodec(self.contract).encode(message(2), "CANFD")[0]
        parser = self.parser()
        self.rejects("STATE", lambda: parser.encode(message(2)))
        self.rejects("STATE", lambda: parser.decode_frame(frame))
        parser.parse(source_inputs()["protocol"], resources())
        self.rejects("RESOURCE", lambda: parser.parse(source_inputs()["protocol"], {}))
        self.rejects("STATE", lambda: parser.encode(message(2)))

    def test_formal_crc_direction_and_transport_rules_are_not_bypassed(self):
        parser, _ = self.parsed()
        frame = parser.encode(message(2))[0]
        self.rejects("CRC", lambda: parser.decode_frame(replace(frame, data=frame.data[:-1] + bytes([frame.data[-1] ^ 1]))))
        self.rejects("AUTHORIZATION", lambda: parser.decode_frame(frame, direction="FROM_36"))
        for change in ({"is_fd": False}, {"bitrate_switch": False}, {"is_extended_id": True}, {"is_remote_frame": True}):
            self.rejects("SCHEMA", lambda: parser.decode_frame(replace(frame, **change)))
        self.rejects("UNSUPPORTED", lambda: parser.encode(message(1)))

    def test_real_database_frame_drift_is_rejected(self):
        for field, value in (("name", "other"), ("frame_id", 0x600), ("length", 63),
                             ("is_fd", False), ("is_extended_frame", True), ("cycle_time", 21)):
            with self.subTest(field=field):
                candidate = database()
                setattr(candidate.messages[0], field, value)
                self.rejects("RESOURCE", lambda: self.parser()._describe_database(candidate))
        for action in (lambda db: db.messages.pop(), lambda db: db.messages.append(db.messages[0])):
            candidate = database()
            action(candidate)
            self.rejects("RESOURCE", lambda: self.parser()._describe_database(candidate))

    def test_every_signal_layout_property_is_verified(self):
        changes = (("name", "renamed"), ("start", 1), ("length", 7), ("byte_order", "big_endian"),
                   ("is_signed", True), ("scale", 2), ("offset", 1), ("minimum", 1), ("maximum", 254),
                   ("choices", {0: "zero"}), ("is_multiplexer", True), ("multiplexer_ids", [1]),
                   ("multiplexer_signal", "flags"), ("is_float", True))
        for field, value in changes:
            with self.subTest(field=field):
                candidate = database()
                setattr(candidate.messages[0].signals[0], field, value)
                self.rejects("RESOURCE", lambda: self.parser()._describe_database(candidate))
        candidate = database()
        candidate.messages[0].signals.pop()
        self.rejects("RESOURCE", lambda: self.parser()._describe_database(candidate))

    def test_actual_equivalent_arxml_is_parsed_by_original_library(self):
        source, blobs = supplement()
        parser = self.parser()
        result = parser.parse(source, blobs)
        self.assertIn("ARXML", result.parsed_formats)
        self.assertEqual(result.frames, self.parsed()[1].frames)
        self.assertEqual(result.pending_formats, ())
        self.assertEqual(parser.encode(message(8)), self.parsed()[0].encode(message(8)))

    def test_arxml_wire_drift_and_ignored_metadata_are_rejected(self):
        for name, value in (("IDENTIFIER", "999"), ("FRAME-LENGTH", "63"), ("START-POSITION", "1"),
                            ("PACKING-BYTE-ORDER", "typo"), ("CAN-ADDRESSING-MODE", "typo"),
                            ("CAN-FRAME-TX-BEHAVIOR", "CAN-20"), ("VALUE", "0.0209"),
                            ("UPPER-LIMIT", "254")):
            with self.subTest(name=name):
                tree = arxml_tree()
                tree.find(f".//{{{NS}}}{name}").text = value
                source, blobs = supplement(tree)
                self.rejects("RESOURCE", lambda: self.parser().parse(source, blobs))

    def test_arxml_malformed_dtd_entities_and_bounds_fail_closed(self):
        for raw in (b"<AUTOSAR/>", b"not XML", b'<!DOCTYPE AUTOSAR [<!ENTITY x "abc">]><AUTOSAR>&x;</AUTOSAR>'):
            source, blobs = supplement(raw=raw)
            self.rejects("RESOURCE", lambda: self.parser().parse(source, blobs))
        source, blobs = supplement(raw=b" " * (4 * 1024 * 1024 + 1))
        self.rejects("CAPACITY", lambda: self.parser().parse(source, blobs))

    def test_arxml_nonfinite_extreme_or_overlong_period_is_resource_failure(self):
        for value in ("NaN", "Infinity", "1e999999", "1" * 65, "0.02000000000000000000000000000001"):
            with self.subTest(value=value):
                tree = arxml_tree()
                tree.find(f".//{{{NS}}}TIME-PERIOD/{{{NS}}}VALUE").text = value
                source, blobs = supplement(tree)
                self.rejects("RESOURCE", lambda: self.parser().parse(source, blobs))

    def test_declared_message_scope_and_input_snapshot_cannot_change(self):
        from icd_runtime.wire import WireCodec
        source = source_inputs()["protocol"]
        source["message_ids"] = [2]
        parser = self.parser()
        parser.parse(source, resources())
        source["message_ids"].append(8)
        source["resources"][0]["sha256"] = "0" * 64
        self.assertEqual(len(parser.encode(message(2))), 1)
        self.rejects("RESOURCE", lambda: parser.encode(message(8)))
        frame = WireCodec(self.contract).encode(message(8), "CANFD")[0]
        self.rejects("RESOURCE", lambda: parser.decode_frame(frame))

    def test_arxml_unprojected_pdu_mapping_length_and_update_bit_are_rejected(self):
        for change in ("pdu_offset", "pdu_length", "update_bit"):
            with self.subTest(change=change):
                tree = arxml_tree()
                if change == "pdu_offset":
                    ET.SubElement(tree.find(f".//{{{NS}}}PDU-TO-FRAME-MAPPING"),
                                  f"{{{NS}}}START-POSITION").text = "8"
                elif change == "pdu_length":
                    tree.find(f".//{{{NS}}}I-SIGNAL-I-PDU/{{{NS}}}LENGTH").text = "63"
                else:
                    ET.SubElement(tree.find(f".//{{{NS}}}I-SIGNAL-TO-I-PDU-MAPPING"),
                                  f"{{{NS}}}UPDATE-INDICATION-BIT-POSITION").text = "511"
                source, blobs = supplement(tree)
                self.rejects("RESOURCE", lambda: self.parser().parse(source, blobs))

    def test_arxml_unrounded_conversion_range_and_coefficient_are_exact(self):
        for change in ("scale", "offset", "divisor", "maximum", "minimum"):
            with self.subTest(change=change):
                tree = arxml_tree()
                if change in ("scale", "offset"):
                    node = tree.findall(f".//{{{NS}}}COMPU-NUMERATOR/{{{NS}}}V")[change == "scale"]
                    node.text = "1.00000000000000001" if change == "scale" else "0.00000000000000001"
                elif change == "divisor":
                    tree.find(f".//{{{NS}}}COMPU-DENOMINATOR/{{{NS}}}V").text = "1.00000000000000001"
                else:
                    name = "UPPER-LIMIT" if change == "maximum" else "LOWER-LIMIT"
                    tree.find(f".//{{{NS}}}{name}").text = "255.00000000000001" if change == "maximum" else "0.00000000000000001"
                source, blobs = supplement(tree)
                self.rejects("RESOURCE", lambda: self.parser().parse(source, blobs))

    def test_unimplemented_resource_format_is_explicitly_pending(self):
        source, blobs = supplement(raw=b"a,b\n", fmt="CSV")
        parser = self.parser()
        result = parser.parse(source, blobs)
        self.assertEqual(result.pending_formats, ("CSV",))
        self.assertNotIn("CSV", result.parsed_formats)
        self.rejects("STATE", lambda: parser.encode(message(2)))
