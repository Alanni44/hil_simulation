import copy
import importlib.util
import json

from common import GatewayTest, ROOT, message


def declared_runtime(contract, model_id):
    """Metadata test fixture only; not a generated model, ABI or E2 consumer."""
    result = {"contract_version": 3, "model_name": model_id,
              "execution": {"step_s": 0.001}, "inputs": {}, "parameters": []}
    for item in contract.catalogue["model_bindings"]:
        if item["model_id"] != model_id:
            continue
        group, name = item["path"].split(".")
        if group == "parameters":
            result["parameters"].append({
                "name": name, "generated_field": item["target_field"],
                **{key: item[key] for key in ("unit", "type", "min", "max", "default")},
                "class": "live", "allowed_phases": ["RUNNING", "PAUSED"],
                "binding": {"kind": "exported_global", "symbol": item["target_field"]}})
        else:
            descriptor = {"field": item["target_field"],
                          **{key: item[key] for key in ("unit", "type", "dimension", "min", "max")}}
            if group == "environment":
                descriptor["default"] = item["default"]
            result["inputs"].setdefault(group, {"ports": {}})["ports"][name] = descriptor
    result["inputs"]["flight_control"]["mode"] = "axis_command" if model_id == "fixed_wing_hil" else "motor_command"
    return result


class BindingTests(GatewayTest):
    def create(self, model="quadrotor_hil", definition=None):
        from icd_gateway.model_bindings import ModelBindings
        return ModelBindings(self.contract, model,
                             declared_runtime(self.contract, model) if definition is None else definition)

    def test_binding_gate_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("icd_gateway.model_bindings"))

    def test_all_97_frozen_paths_are_covered_by_complete_snapshots(self):
        paths = set()
        for model, ids in (("quadrotor_hil", (7, 10, 11, 17)),
                           ("multirotor_6_hil", (8, 10, 12, 18)),
                           ("fixed_wing_hil", (9, 10, 13, 19))):
            mapping = self.create(model)
            for mid in ids:
                paths.update((model, item.path) for item in mapping.map_message(message(mid)))
        expected = {(item["model_id"], item["path"]) for item in self.contract.catalogue["model_bindings"]}
        self.assertEqual(paths, expected)
        self.assertEqual(len(paths), 97)

    def test_flight_and_actuator_are_the_same_target_not_different_lanes(self):
        mapping = self.create()
        first, second = mapping.map_message(message(7)), mapping.map_message(message(14))
        self.assertEqual([item.path for item in first], [item.path for item in second])
        self.assertEqual(first[0].path, "flight_control.motor_command")
        self.assertEqual(json.loads(first[0].value_json), message(7)["payload"]["motor_command"])

    def test_full_message_schema_and_selected_model_are_required(self):
        mapping = self.create()
        value = message(11)
        del value["payload"]["gps_bias_n_m"]
        self.rejects("SCHEMA", lambda: mapping.map_message(value))
        self.rejects("MODEL", lambda: mapping.map_message(message(8)))
        for mid in (3, 5, 24, 25, 39, 45, 129):
            self.rejects("TARGET_MISSING" if mid != 129 else "AUTHORIZATION",
                         lambda mid=mid: mapping.map_message(message(mid)))

    def test_missing_extra_ports_and_parameters_are_not_silently_accepted(self):
        definition = declared_runtime(self.contract, "quadrotor_hil")
        variants = []
        missing = copy.deepcopy(definition)
        del missing["inputs"]["fault"]["ports"]["gps_bias_n_m"]
        variants.append(missing)
        extra = copy.deepcopy(definition)
        extra["inputs"]["environment"]["ports"]["unknown"] = {}
        variants.append(extra)
        for values in (definition["parameters"][:-1], definition["parameters"] * 2,
                       definition["parameters"] + [{"name": "unknown"}]):
            variant = copy.deepcopy(definition)
            variant["parameters"] = copy.deepcopy(values)
            variants.append(variant)
        for variant in variants:
            self.rejects("MODEL", lambda variant=variant: self.create(definition=variant))

    def test_descriptor_type_dimension_unit_range_default_and_symbol_are_exact(self):
        definition = declared_runtime(self.contract, "quadrotor_hil")
        for key, invalid in (("field", "state.outputs.motor_command"), ("type", "single"),
                             ("dimension", True), ("dimension", 6), ("unit", "rpm"),
                             ("min", True), ("min", -1), ("max", 2)):
            variant = copy.deepcopy(definition)
            variant["inputs"]["flight_control"]["ports"]["motor_command"][key] = invalid
            self.rejects("MODEL", lambda variant=variant: self.create(definition=variant))
        for key, invalid in (("generated_field", "wrong_symbol"), ("default", 2),
                             ("binding", {"kind": "exported_global", "symbol": "wrong"}),
                             ("class", "restart_only"), ("allowed_phases", ["RUNNING"])):
            variant = copy.deepcopy(definition)
            variant["parameters"][0][key] = invalid
            self.rejects("MODEL", lambda variant=variant: self.create(definition=variant))
        del definition["inputs"]["environment"]["ports"]["pressure_pa"]["default"]
        self.rejects("MODEL", lambda: self.create(definition=definition))

    def test_wrong_model_version_step_and_malformed_definition_are_rejected(self):
        for field, value in (("model_name", "fixed_wing_hil"), ("contract_version", True),
                             ("contract_version", 1), ("execution", {"step_s": 0.01}),
                             ("inputs", None), ("parameters", None)):
            definition = declared_runtime(self.contract, "quadrotor_hil")
            definition[field] = value
            self.rejects("MODEL", lambda definition=definition: self.create(definition=definition))
        self.rejects("MODEL", lambda: self.create("unknown", {}))

    def test_metadata_and_mapped_values_have_no_mutable_caller_alias(self):
        definition = declared_runtime(self.contract, "quadrotor_hil")
        mapping = self.create(definition=definition)
        definition["inputs"].clear()
        value = message(7)
        result = mapping.map_message(value)
        original = result[0].value_json
        value["payload"]["motor_command"][0] = 0.9
        self.assertEqual(result[0].value_json, original)
        with self.assertRaises(AttributeError):
            result[0].path = "state.outputs.north_m"

    def test_existing_six_motor_declaration_is_not_full_v03_qualification(self):
        definition = json.loads((ROOT / "artifacts/generic_models/multirotor_6/hil_contract.json").read_bytes())
        self.rejects("MODEL", lambda: self.create("multirotor_6_hil", definition))

    def test_control_mode_extra_root_and_non_scalar_parameter_are_rejected(self):
        definition = declared_runtime(self.contract, "quadrotor_hil")
        for change in ("mode", "root", "dimension"):
            variant = copy.deepcopy(definition)
            if change == "mode":
                variant["inputs"]["flight_control"]["mode"] = "axis_command"
            elif change == "root":
                variant["inputs"]["arbitrary_input"] = {"ports": {"unknown": {}}}
            else:
                variant["parameters"][0]["dimension"] = 4
            self.rejects("MODEL", lambda variant=variant: self.create(definition=variant))
