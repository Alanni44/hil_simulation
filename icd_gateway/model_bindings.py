"""Structural hil_contract equivalence, not generated ABI or behavior qualification."""

from dataclasses import dataclass

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, check_json_domain


@dataclass(frozen=True, slots=True)
class MappedValue:
    path: str
    target_field: str
    value_json: bytes


def _equal(actual, expected):
    if type(expected) in (int, float):
        return type(actual) in (int, float) and actual == expected
    return type(actual) is type(expected) and actual == expected


class ModelBindings:
    def __init__(self, contract, model_id, runtime_contract):
        self.contract = contract
        self.model_id = model_id
        self.baseline_sha256 = contract.baseline_sha256
        self._groups = {}
        rows = [row for row in contract.catalogue["model_bindings"] if row["model_id"] == model_id]
        if not rows:
            raise ICDError("MODEL", "model has no frozen bindings")
        for row in rows:
            group, name = row["path"].split(".")
            self._groups.setdefault(group, {})[name] = row
        try:
            check_json_domain(runtime_contract)
            if (type(runtime_contract) is not dict or runtime_contract["model_name"] != model_id
                    or type(runtime_contract["contract_version"]) is not int
                    or runtime_contract["contract_version"] not in (2, 3)
                    or not _equal(runtime_contract["execution"]["step_s"], 0.001)):
                raise ValueError("model/version/step")
            if set(runtime_contract["inputs"]) != {"flight_control", "environment", "fault"}:
                raise ValueError("unmapped root input group")
            expected_mode = "axis_command" if model_id == "fixed_wing_hil" else "motor_command"
            if runtime_contract["inputs"]["flight_control"]["mode"] != expected_mode:
                raise ValueError("flight input mode differs")
            for group in ("flight_control", "environment", "fault"):
                ports = runtime_contract["inputs"][group]["ports"]
                if type(ports) is not dict or set(ports) != set(self._groups[group]):
                    raise ValueError("missing or extra root input")
                for name, row in self._groups[group].items():
                    descriptor = ports[name]
                    expected = {"field": row["target_field"],
                                **{key: row[key] for key in ("type", "unit", "dimension", "min", "max")}}
                    if group == "environment":
                        expected["default"] = row["default"]
                    if type(descriptor) is not dict or any(
                            not _equal(descriptor.get(key), value) for key, value in expected.items()):
                        raise ValueError("input descriptor differs: " + row["path"])
            parameters = runtime_contract["parameters"]
            if type(parameters) is not list:
                raise ValueError("parameter list required")
            by_name = {item["name"]: item for item in parameters}
            if len(by_name) != len(parameters) or set(by_name) != set(self._groups["parameters"]):
                raise ValueError("missing, extra or duplicate parameter")
            for name, row in self._groups["parameters"].items():
                descriptor = by_name[name]
                expected = {"generated_field": row["target_field"], "class": "live",
                            **{key: row[key] for key in ("type", "unit", "min", "max", "default")}}
                if (any(not _equal(descriptor.get(key), value) for key, value in expected.items())
                        or not _equal(descriptor.get("dimension", 1), 1)
                        or descriptor.get("binding") != {"kind": "exported_global", "symbol": row["target_field"]}
                        or type(descriptor.get("allowed_phases")) is not list
                        or not {"RUNNING", "PAUSED"} <= set(descriptor["allowed_phases"])):
                    raise ValueError("parameter descriptor differs: " + row["path"])
        except (ICDError, KeyError, TypeError, ValueError, AttributeError) as error:
            raise ICDError("MODEL", "runtime hil_contract is not structurally equivalent: " + str(error)) from error

    def map_message(self, message):
        self.contract.validate_message(message, direction="TO_36", model_id=self.model_id)
        mid = message["message_id"]
        if mid not in range(7, 20):
            raise ICDError("TARGET_MISSING", "consumer outside root input/parameter binding package")
        group = ("flight_control" if mid in (7, 8, 9, 14, 15, 16) else
                 "environment" if mid == 10 else "fault" if mid in (11, 12, 13) else "parameters")
        payload = message["payload"]
        if set(payload) != set(self._groups[group]):
            raise ICDError("MODEL", "message is not a complete mapped snapshot")
        return tuple(MappedValue(row["path"], row["target_field"], canonicalize(payload[name]))
                     for name, row in self._groups[group].items())
