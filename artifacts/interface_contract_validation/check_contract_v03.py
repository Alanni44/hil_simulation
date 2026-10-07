"""Static QA for the author-defined ICD. No service/device acceptance implied."""

import base64
import binascii
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOCS = ROOT / "docs/interfaces/baseline"
sys.path.insert(0, str(HERE / "vendor"))
sys.path.insert(0, str(HERE / "vendor_v03"))
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import cantools
import jcs
from crccheck.crc import Crc16CcittFalse, Crc32IsoHdlc


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key: " + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("Nonfinite JSON: " + value)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"),
                      object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


business = read(DOCS / "input-simulator-business-v0.3.schema.json")
api = read(DOCS / "input-simulator-api-v0.3.schema.json")
package = read(DOCS / "input-simulator-package-v0.2.schema.json")
catalog = read(DOCS / "input-simulator-icd-v0.3.json")
coverage = read(DOCS / "input-simulator-coverage-v0.3.json")
defs = business["$defs"]
schemas = [business, api, package]
registry = Registry().with_resources([
    (schema["$id"], Resource.from_contents(schema)) for schema in schemas
])
checker = FormatChecker()
checks = 0
negative = 0


def check(condition, label):
    global checks
    checks += 1
    assert condition, label


def validator(definition, schema=business):
    return Draft202012Validator({"$ref": schema["$id"] + "#/$defs/" + definition},
                               registry=registry, format_checker=checker)


def reject(value, definition, label, schema=business):
    global negative
    check(not validator(definition, schema).is_valid(value), label)
    negative += 1


catalog_hash = digest(DOCS / "input-simulator-icd-v0.3.json")
schema_hash = digest(DOCS / "input-simulator-business-v0.3.schema.json")
dbc_hash = digest(DOCS / "input-simulator-canfd-v0.3.dbc")
components = {"business_schema_sha256": schema_hash, "wire_catalog_sha256": catalog_hash,
              "canfd_dbc_sha256": dbc_hash,
              "contract_doc_sha256": digest(DOCS / "input-simulator-data-contract-v0.3.md")}
baseline_hash = hashlib.sha256(jcs.canonicalize(components)).hexdigest()


def example(node):
    if "$ref" in node:
        return example(defs[node["$ref"].split("/")[-1]])
    if "const" in node:
        return node["const"]
    if "oneOf" in node:
        return example(node["oneOf"][0])
    if "properties" in node:
        return {key: baseline_hash if key == "baseline_sha256" else example(value)
                for key, value in node["properties"].items()}
    if "default" in node:
        return copy.deepcopy(node["default"])
    if node.get("type") == "array":
        return [example(node["items"]) for _ in range(node.get("minItems", 0))]
    if node.get("type") == "null":
        return None
    if node.get("pattern") == "^[0-9a-f]{64}$":
        return catalog_hash
    if node.get("pattern") == "^[0-9a-f]{32}$":
        return hashlib.sha256(b"static-qa-nonce").hexdigest()[:32]
    if node.get("type") == "string":
        return "value-01"
    raise AssertionError("No fixture recipe: " + repr(node))


for schema in schemas:
    Draft202012Validator.check_schema(schema)
    check(True, "meta schema " + schema["$id"])

fields = (DOCS / "input-simulator-fields-v0.3.md").read_text(encoding="utf-8")


def expected_rows(node, path="", required=True, branch=""):
    if "$ref" in node:
        yield ["`" + path + "`", "ref:" + node["$ref"].split("/")[-1],
               "是" if required else "否", "见引用定义", "见引用", "见引用", branch or "-"]
        return
    if "oneOf" in node:
        for index, value in enumerate(node["oneOf"]):
            yield from expected_rows(value, path, required,
                branch + ("/" if branch else "") + "variant-" + str(index + 1))
        return
    if "properties" in node:
        for key, value in node["properties"].items():
            yield from expected_rows(value, path + "." + key if path else key,
                                     key in node.get("required", []), branch)
        return
    def canon(value):
        return jcs.canonicalize(value).decode("utf-8")
    if "enum" in node:
        value_range = " / ".join(str(x) for x in node["enum"])
    elif "const" in node:
        value_range = canon(node["const"])
    elif node.get("type") == "array":
        value_range = str(node["minItems"]) + ".." + str(node["maxItems"]) + " items"
    elif "minimum" in node:
        value_range = canon(node["minimum"]) + ".." + canon(node["maximum"])
    elif "pattern" in node:
        value_range = node["pattern"]
    elif "minLength" in node:
        value_range = str(node["minLength"]) + ".." + str(node["maxLength"]) + " chars"
    else:
        value_range = "-"
    default = canon(node["default"]) if "default" in node else node.get("x-default-policy", "REQUIRED_EXPLICIT_VALUE")
    yield ["`" + path + "`", node.get("type", "const"), "是" if required else "否",
           value_range, node.get("x-unit", "bool" if node.get("type") == "boolean" else "-"),
           default, branch or "-"]
    if "items" in node:
        yield from expected_rows(node["items"], path + "[]", True, branch)


dictionary_rows_checked = 0
for definition, node in defs.items():
    section = fields.split("## " + definition + "\n", 1)[1].split("\n## ", 1)[0]
    actual = []
    for line in section.splitlines():
        if line.startswith("| `"):
            actual.append([part.strip().replace("\\|", "|")
                           for part in re.split(r"(?<!\\)\|", line)[1:-1]])
    expected = list(expected_rows(node))
    check(len(actual) == len(expected), "field row count: " + definition)
    for index, (written, specified) in enumerate(zip(actual, expected)):
        if written[5] != specified[5]:
            try:
                equivalent_default = json.loads(written[5]) == json.loads(specified[5])
            except ValueError:
                equivalent_default = False
            if equivalent_default:
                written[5] = specified[5]
        check(written == specified, ("field dictionary", definition, index, written, specified))
    dictionary_rows_checked += len(expected)
check(dictionary_rows_checked == 1409, "all 1409 dictionary rows accounted for")


def inspect(node, path):
    if not isinstance(node, dict):
        return
    if "$ref" in node:
        uri, _, pointer = node["$ref"].partition("#")
        target = next((s for s in schemas if s["$id"] == uri), business) if uri else business
        for token in pointer.lstrip("/").split("/"):
            target = target[token.replace("~1", "/").replace("~0", "~")]
        check(True, "reference " + path)
    if node.get("type") == "object":
        if path != "ManagementUpdateParams":
            check(node.get("additionalProperties") is False, "closed object " + path)
        check(set(node.get("required", [])) == set(node.get("properties", {})),
              "complete required fields " + path)
    if "default" in node:
        check(Draft202012Validator(node, registry=registry).is_valid(node["default"]),
              "legal default " + path)
    for key, value in node.items():
        if isinstance(value, dict):
            inspect(value, path + "/" + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    inspect(item, path + "/" + key + "/" + str(index))


for name, node in defs.items():
    check("## " + name + "\n" in fields, "field dictionary " + name)
    inspect(node, name)
    if name in {"BusinessMessage", "BusinessInputMessage", "APIInput",
                "ManagementUpdateParams", "SourceInputs"}:
        continue
    samples = node.get("oneOf", [node])
    for branch_index, branch in enumerate(samples):
        value = example(branch)
        errors = list(validator(name).iter_errors(value))
        check(not errors, (name, branch_index, [e.message for e in errors[:3]]))
        if isinstance(value, dict):
            changed = copy.deepcopy(value)
            changed["unexpected_input"] = 1
            reject(changed, name, "unknown field " + name)
            for key, leaf in branch.get("properties", {}).items():
                missing = copy.deepcopy(value)
                del missing[key]
                reject(missing, name, "required " + name + "." + key)
                if "minimum" in leaf:
                    for bound in [leaf["minimum"] - 1, leaf["maximum"] + 1]:
                        wrong = copy.deepcopy(value)
                        wrong[key] = bound
                        reject(wrong, name, "range " + name + "." + key)
                    for bound in [leaf["minimum"], leaf["maximum"]]:
                        valid = copy.deepcopy(value)
                        valid[key] = bound
                        check(validator(name).is_valid(valid), "boundary " + name + "." + key)
                if leaf.get("type") in {"number", "integer", "boolean", "array"}:
                    wrong = copy.deepcopy(value)
                    wrong[key] = "wrong-type"
                    reject(wrong, name, "type " + name + "." + key)
                if leaf.get("type") == "array" and leaf["maxItems"] <= 1024:
                    wrong = copy.deepcopy(value)
                    wrong[key] = [example(leaf["items"]) for _ in range(leaf["maxItems"] + 1)]
                    reject(wrong, name, "array upper bound " + name + "." + key)

# Transport and model checks are independent of the generated dictionary.
messages = catalog["messages"]
by_id = {m["id"]: m for m in messages}
check(len(by_id) == len(messages) == 59, "unique 59 messages")
check({m["id"] for m in messages if m["direction"] == "TO_36"} == set(range(1, 46)),
      "all 45 input IDs")
check({m["id"] for m in messages if m["direction"] == "FROM_36"} == set(range(129, 143)),
      "all 14 feedback IDs")
check(len({c["id"] for c in catalog["channels"]}) == 56, "all physical channel IDs")
check(len({c["id"] for c in catalog["toolchains"]}) == 6, "all six original branches")
for group, count in {"CANFD": 4, "CAN": 4, "ETH": 4, "RS232": 4,
                     "RS422": 8, "AD": 8, "DA": 8, "TTL": 16}.items():
    check({c["index"] for c in catalog["channels"] if c["type"] == group} == set(range(count)),
          "every " + group + " channel")

for filename in ["fixed_wing", "multirotor_6"]:
    current = read(ROOT / "artifacts/generic_models" / filename / "hil_contract.json")
    bindings = {b["path"]: b for b in catalog["model_bindings"]
                if b["model_id"] == current["model_name"]}
    for group, definition in current["inputs"].items():
        for name, port in definition["ports"].items():
            binding = bindings[group + "." + name]
            for attr in ["type", "unit", "dimension", "min", "max"]:
                check(binding[attr] == port[attr], "port " + name + "/" + attr)
            check(binding["target_field"] == port["field"], "actual port binding")
    for param in current["parameters"]:
        binding = bindings["parameters." + param["name"]]
        for attr in ["type", "unit", "min", "max", "default"]:
            check(binding[attr] == param[attr], "parameter " + param["name"] + "/" + attr)
        check(binding["target_field"] == param["generated_field"], "actual parameter symbol")

quad_text = (ROOT / "matlab_scripts/create_quadrotor_contract.m").read_text(encoding="utf-8")
quad_bindings = [b for b in catalog["model_bindings"] if b["model_id"] == "quadrotor_hil"]
check(len(quad_bindings) == 32, "quad current 20 ports and 12 parameters")
for binding in quad_bindings:
    check(binding["target_field"] in quad_text, "quad template declares field")
    if binding["path"].startswith("parameters."):
        name = binding["path"].split(".", 1)[1]
        match = re.search(r"parameter\('" + name + r"',\s*'([^']+)',\s*'([^']+)',\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)", quad_text)
        check(match is not None, "quad parameter template parse")
        symbol, unit, default, minimum, maximum = match.groups()
        check((symbol, unit, float(default), float(minimum), float(maximum)) ==
              (binding["target_field"], binding["unit"], binding["default"], binding["min"], binding["max"]),
              "quad parameter exact values")
check(len(catalog["model_bindings"]) == 97, "all native bindings and hex extensions")
for motor in [5, 6]:
    check(any(b["path"] == "fault.motor_" + str(motor) + "_failed" and
              b["status"] == "REQUIRED_IMPLEMENTATION" for b in catalog["model_bindings"]),
          "explicit missing model extension")

check(Crc16CcittFalse.calc(b"123456789") == 0x29b1, "CRC16 independent reference")
check(Crc32IsoHdlc.calc(b"123456789") == 0xcbf43926, "CRC32 independent reference")
db = cantools.database.load_file(str(DOCS / "input-simulator-canfd-v0.3.dbc"), strict=True)
fast = [m for m in messages if m["encoding"] == "PACKED_LE"]
check(len(db.messages) == len(fast) == 13, "DBC covers fast messages")
check(len({m["can_id"] for m in fast}) == 13, "unique CAN IDs")
vectors = []
fixtures = []
for m in messages:
    payload = example(defs[m["payload_definition"]])
    if m["encoding"] == "PACKED_LE":
        for index, (key, leaf) in enumerate(defs[m["payload_definition"]]["properties"].items()):
            if leaf.get("type") == "number":
                payload[key] = leaf["minimum"] + (leaf["maximum"] - leaf["minimum"]) * (index + 2) / 20
            elif leaf.get("type") == "array" and leaf["items"].get("type") == "number":
                item = leaf["items"]
                payload[key] = [item["minimum"] + (item["maximum"] - item["minimum"]) * (j + 1) / 10
                                for j in range(leaf["minItems"])]
    logical = {"message_id": m["id"], "header": {"session_id": 1, "sequence": m["id"],
               "target_step": 1000, "transaction_id": m["id"], "valid_for_ms": m["valid_for_ms"]},
               "payload": payload}
    if m["name"] == "SessionOpen":
        logical["header"]["session_id"] = 0
        logical["header"]["target_step"] = 0
    check(validator("BusinessMessage").is_valid(logical), "business message " + m["name"])
    if m["direction"] == "FROM_36":
        reject(logical, "BusinessInputMessage", "feedback not an input " + m["name"])
    else:
        check(validator("BusinessInputMessage").is_valid(logical), "actual input message")
    fixtures.append({"name": m["name"], "purpose": "SCHEMA_FIXTURE_NOT_EXECUTION_SCENARIO", "value": logical})
    if m["encoding"] == "PACKED_LE":
        packed = bytearray()
        for f in m["fields"]:
            check(f["offset"] == len(packed), "no payload gaps")
            value = payload[f["name"]]
            t = f["type"]
            if t.startswith("f64le["):
                packed.extend(struct.pack("<" + "d" * len(value), *value))
            elif t == "f64le":
                packed.extend(struct.pack("<d", value))
            elif t == "u8bool":
                packed.append(int(value))
            elif t == "u8enum":
                packed.append(f["enum_codes"][value])
            else:
                packed.extend(struct.pack({"u32le": "<I", "u16le": "<H"}[t], value))
            check(len(packed) == f["offset"] + f["size"], "exact field width")
        check(len(packed) == m["payload_bytes"], "exact packed length")
        frame_definition = db.get_message_by_frame_id(m["can_id"])
        check(frame_definition.is_fd and not frame_definition.is_extended_frame and frame_definition.length == 64,
              "FD standard frame attributes")
        count = math.ceil(len(packed) / 38)
        check(count <= catalog["codecs"]["CANFD"]["max_fragments"], "CAN payload fits")
        for index in range(count):
            chunk = packed[index * 38:(index + 1) * 38]
            frame = bytearray(64)
            struct.pack_into("<BBBBIIIIBBH", frame, 0, 1, 0, 0, len(chunk), 1,
                             m["id"], 1000, m["id"], index, count, m["valid_for_ms"])
            frame[24:24 + len(chunk)] = chunk
            calculated = binascii.crc_hqx(struct.pack("<H", m["can_id"]) + frame[:62], 0xffff)
            check(calculated == Crc16CcittFalse.calc(struct.pack("<H", m["can_id"]) + frame[:62]),
                  "CRC16 stdlib vs independent library")
            struct.pack_into("<H", frame, 62, calculated)
            decoded = frame_definition.decode(frame, decode_choices=False)
            check(decoded["session"] == 1 and decoded["sequence"] == m["id"] and
                  decoded["chunk_length"] == len(chunk) and decoded["crc16"] == calculated,
                  "DBC decode matches header")
            check(frame_definition.encode(decoded) == bytes(frame), "cantools independent frame encode")
            check(bytes(decoded["chunk_" + str(j).zfill(2)] for j in range(38)) == frame[24:62],
                  "DBC chunk bytes")
            vectors.append({"message_id": m["id"], "transport": "CANFD", "can_id": m["can_id"],
                            "fragment_index": index, "fd": True, "brs": True,
                            "engineering_payload": payload, "wire_hex": frame.hex()})
        body = bytes(packed)
    else:
        body = jcs.canonicalize(payload)
        check(json.loads(body) == payload, "JCS engineering values preserved")
    count = math.ceil(len(body) / 1160)
    check(len(body) <= m["max_logical_payload_bytes"] and count <= 57, "UDP payload fits")
    for index in range(count):
        chunk = body[index * 1160:(index + 1) * 1160]
        header = struct.pack("<4sBBHIIIIHHHHHH", b"HIL1", 1, 0, 0,
                             logical["header"]["session_id"], m["id"], logical["header"]["target_step"],
                             m["id"], index, count, len(chunk), m["valid_for_ms"], m["id"], 0)
        check(len(header) == 36, "UDP pre-CRC header length")
        crc = binascii.crc32(header + chunk) & 0xffffffff
        check(crc == Crc32IsoHdlc.calc(header + chunk), "CRC32 independent implementation")
        packet = header + struct.pack("<I", crc) + chunk
        check(len(packet) <= 1200, "UDP does not depend on IP fragmentation")
        vectors.append({"message_id": m["id"], "transport": "UDP", "fragment_index": index,
                        "payload_sha256": hashlib.sha256(body).hexdigest(), "wire_hex": packet.hex()})

probe_ids = [p["id"] for p in catalog["probe_catalog"]]
probe_names = [p["name"] for p in catalog["probe_catalog"]]
check(len(set(probe_ids)) == len(probe_ids), "unique numeric probe IDs")
check(len(set(probe_names)) == len(probe_names), "unique probe names")
check(set(defs["ProbeName"]["enum"]) == set(probe_names), "probe names are fully defined")

# A real RAW BGR24 frame exercises all video fragment offsets without claiming decode hardware QA.
raw_frame = bytes(640 * 480 * 3)
raw_hash = hashlib.sha256(raw_frame).hexdigest()
video_count = math.ceil(len(raw_frame) / 1152)
check(video_count <= catalog["codecs"]["VIDEO"]["max_fragments"], "RAW video fragment count fits")
for index in range(video_count):
    chunk = raw_frame[index * 1152:(index + 1) * 1152]
    prefix = struct.pack("<4sBBHIIIIQHHIHH", b"HIV1", 1, 2, 0, 1, 1, 0, 1000, 0,
                         index, video_count, len(raw_frame), len(chunk), 0)
    check(len(prefix) == 44, "video header CRC offset")
    crc = binascii.crc32(prefix + chunk) & 0xffffffff
    check(crc == Crc32IsoHdlc.calc(prefix + chunk), "video independent CRC")
    packet = prefix + struct.pack("<I", crc) + chunk
    check(len(packet) <= 1200 and len(packet) == 48 + len(chunk), "video packet exact capacity")
    if index in {0, video_count // 2, video_count - 1}:
        vectors.append({"transport": "VIDEO", "codec": "RAW", "message_id": 43,
            "fragment_index": index, "frame_sha256": raw_hash, "frame_bytes": len(raw_frame),
            "wire_hex": packet.hex(), "purpose": "RAW_FRAME_HEADER_AND_FRAGMENT_FIXTURE"})

source = example(defs["SourceInputs"])
source["baseline_sha256"] = baseline_hash
source["protocol"]["business_schema_sha256"] = schema_hash
source["protocol"]["wire_catalog_sha256"] = catalog_hash
source["protocol"]["message_ids"] = sorted(by_id)
source["protocol"]["resources"] = []
for name, fmt in [("input-simulator-icd-v0.3.json", "ICD_JSON"), ("input-simulator-canfd-v0.3.dbc", "DBC")]:
    path = DOCS / name
    source["protocol"]["resources"].append({"resource_id": name, "sha256": digest(path),
        "size_bytes": path.stat().st_size, "format": fmt, "encoding": "UTF8",
        "media_type": "application/json" if fmt == "ICD_JSON" else "text/plain", "file_name": name})
scenario = example(defs["ScenarioSource"])
scenario["scenario_id"] = "environment-step-01"
environment = example(defs["Environment"])
environment["wind_n_mps"] = 1
event = {"event_id": "wind-step-01", "at_step": 250, "priority": 100,
         "link_id": "ETHGEN", "type": "SEND", "stimulus": {"message_id": 10, "payload": environment}}
cleanup = {"event_id": "cleanup-01", "at_step": 400, "priority": 255, "link_id": "ETHGEN",
           "type": "END_CLEANUP", "cleanup": example(defs["Cleanup"])}
scenario["events"] = [event, cleanup]
scenario["assertions"] = [{"assertion_id": "wind-model-write-01", "stage": "E2", "message_id": 10,
    "probe_id": "quadrotor_hil.input.environment.wind_n_mps", "field_path": "environment.wind_n_mps",
    "operator": "WITHIN", "expected": 1, "tolerance": 1e-9, "timeout_steps": 100, "sample_count": 1}]
source["scenario"] = scenario
source["history"] = None
check(validator("SourceInputs").is_valid(source), "three-source container")
bad = copy.deepcopy(source)
bad["scenario"] = None
reject(bad, "SourceInputs", "need scenario or history")
check(validator("HistorySource").is_valid(example(defs["HistorySource"])), "history full structure")

update = {"cmd": "simulator_run_update_inputs", "params": {"api_version": "0.3", "request_id": "input-01",
    "run_id": "run-01", "expected_revision": "1", "link_id": "ETHGEN",
    "message": {"message_id": 10, "header": {"session_id": 1, "sequence": 1, "target_step": 250,
        "transaction_id": 1, "valid_for_ms": 240}, "payload": environment}}}
check(validator("Request", api).is_valid(update), "management envelope and typed input")
check(validator("APIInput").is_valid(update), "standalone API input same envelope")
bad = copy.deepcopy(update)
bad["params"]["values"] = {"anything": 1}
reject(bad, "Request", "old arbitrary input dictionary forbidden", api)
create_params = example(defs["RunConfigure"])
create = {"cmd": "simulator_run_create", "params": {"api_version": "0.3", "request_id": "create-01",
    "package_ref": {"id": "package-01", "version": "1.0", "sha256": catalog_hash},
    "scenario_ref": {"id": "environment-step-01", "version": "1.0", "sha256": catalog_hash},
    "mode": "SCENARIO", "source_binding_ref": "source-01", "link_ids": ["ETHGEN"],
    "baseline_sha256": baseline_hash, "run_configuration": create_params, "source_inputs": source}}
# PackageRef/ScenarioRef and Mode retain their explicitly defined v0.2 metadata shapes.
mode_schema = api["$defs"]["Mode"]
create["params"]["mode"] = mode_schema.get("enum", ["SCENARIO"])[0]
for field, definition in [("package_ref", "PackageRef"), ("scenario_ref", "ScenarioRef")]:
    def sample_external(node):
        if "$ref" in node:
            uri, _, ptr = node["$ref"].partition("#")
            owner = package if uri == package["$id"] else api
            return sample_external(owner["$defs"][ptr.split("/")[-1]])
        if node.get("type") == "object":
            return {k: sample_external(v) for k, v in node["properties"].items()}
        if "const" in node:
            return node["const"]
        if "enum" in node:
            return node["enum"][0]
        if node.get("type") == "integer":
            return node.get("minimum", 1)
        if node.get("type") == "string":
            return catalog_hash if node.get("pattern") == "^[0-9a-f]{64}$" else "1"
        raise AssertionError(node)
    create["params"][field] = sample_external(api["$defs"][definition])
errors = list(validator("Request", api).iter_errors(create))
check(not errors, ("typed create API", [e.message for e in errors[:3]]))
for field in ["baseline_sha256", "run_configuration", "source_inputs"]:
    bad = copy.deepcopy(create)
    del bad["params"][field]
    reject(bad, "Request", "create must include complete " + field, api)

for raw in ['{"x":NaN}', '{"x":Infinity}', '{"x":1,"x":2}']:
    try:
        json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except ValueError:
        check(True, "strict JSON rejected malformed number/key")
    else:
        raise AssertionError(raw)

check(len(coverage["requirements"]) == 26, "tender and scheme coverage groups")
check(all(r["design_defined"] and not r["runtime_verified"] for r in coverage["requirements"]),
      "no false runtime acceptance")
for path in DOCS.glob("*v0.3*"):
    if path.suffix not in {".md", ".json", ".dbc"}:
        continue
    check(not re.search(r'"(?:PENDING|TBD|TODO|UNCONFIRMED)"|DEMO_(?!MISSION)',
                        path.read_text(encoding="utf-8")), "no unresolved design placeholder " + path.name)

documents = [Path.home() / "Desktop" / catalog["source_documents"][0]["name"],
             ROOT / "docs" / catalog["source_documents"][1]["name"]]
for path, entry in zip(documents, catalog["source_documents"]):
    check(digest(path) == entry["sha256"], "original document hash " + entry["name"])

outputs = {
    "input-simulator-v0.3.baseline.json": {"baseline_version": "HIL-ICD-1.0",
        "components": components, "baseline_sha256": baseline_hash,
        "algorithm": "SHA256_RFC8785_CANONICAL_COMPONENT_OBJECT", "status": "AUTHOR_DEFINED_DESIGN"},
    "input-simulator-v0.3.examples.json": {"baseline": "HIL-ICD-1.0",
        "purpose": "SCHEMA_FIXTURES_ONLY_NOT_EXECUTABLE_RELEASE_PACKAGE",
        "fixtures": fixtures, "source_inputs": source, "management_update_schema_fixture": update,
        "management_create_schema_fixture": create, "execution_status": "NOT_EXECUTED"},
    "input-simulator-v0.3.golden.json": {"baseline": "HIL-ICD-1.0", "generation":
        "stdlib struct/binascii cross-checked with cantools/crccheck and RFC8785 jcs",
        "actual_transport_validation": "NOT_EXECUTED", "vectors": vectors},
    "input-simulator-v0.3.qa.json": {"status": "STATIC_PASS", "checks": checks,
        "negative_checks": negative, "business_messages": len(messages),
        "input_messages": 45, "feedback_messages": 14, "definitions": len(defs),
        "dictionary_rows_checked": dictionary_rows_checked,
        "model_bindings": len(catalog["model_bindings"]), "channels": 56,
        "tool_branches": 6, "requirement_groups": 26, "golden_vectors": len(vectors),
        "video_raw_fragments_checked": video_count,
        "validator_versions": {"cantools": cantools.__version__, "jcs": "0.2.1"},
        "scope": ["Schema/reference/default checks", "branch fixtures and negative field tests",
                  "current native model ports and parameters", "DBC FD frame encode/decode",
                  "independent CRC implementations", "actual source document hashes"],
        "not_executed": ["service/runtime semantic guards", "model E2/E3 behavior",
                         "L01-L10/T01-T14 real toolchain acceptance", "physical I/O safety/calibration",
                         "1ms realtime and 80ms communication jitter", "video decode/injection",
                         "cross-host clock synchronization", "real 3.3 replacement"],
        "release_status": "DESIGN_BASELINE_ONLY"},
}
for filename, value in outputs.items():
    (DOCS / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
paths = sorted(p for p in DOCS.glob("*v0.3*") if not p.name.endswith("manifest.json"))
manifest = {"baseline": "HIL-ICD-1.0", "hash_basis": "RAW_FILE_BYTES_SHA256",
            "runtime_release_status": "NOT_RELEASED", "files": [
                {"file": p.name, "sha256": digest(p), "size_bytes": p.stat().st_size} for p in paths]}
(DOCS / "input-simulator-v0.3.manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(outputs["input-simulator-v0.3.qa.json"], ensure_ascii=False, indent=2))
