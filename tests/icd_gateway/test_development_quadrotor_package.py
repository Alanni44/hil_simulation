import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from common import EXPECTED, INTERFACES, ROOT
from icd_runtime.contract import Contract
from icd_gateway.model_bindings import ModelBindings


class DevelopmentQuadrotorPackageTests(unittest.TestCase):
    def module(self):
        path = ROOT / "scripts" / "create_development_quadrotor_package.py"
        spec = importlib.util.spec_from_file_location("development_quad_package", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_package_is_structurally_bound_and_c_model_steps_after_readback(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "quadrotor_hil"
            result = self.module().create(package, INTERFACES, EXPECTED)
            runtime_contract = json.loads((package / "hil_contract.json").read_text(encoding="utf-8"))
            bindings = ModelBindings(Contract.load(INTERFACES, expected_sha256=EXPECTED), "quadrotor_hil", runtime_contract)
            self.assertEqual(bindings.model_id, "quadrotor_hil")
            self.assertTrue(result["development_only"])
            self.assertFalse(result["model_application_qualified"])
            self.assertIn("DEVELOPMENT_ONLY", (package / "README.md").read_text(encoding="utf-8"))
            harness = package / "harness.c"
            harness.write_text("""
#include \"model_rt_wrapper.h\"
#include <stdio.h>
int main(void) {
    ModelY_t output; double motors[4]; unsigned i;
    model_initialize();
    for (i = 0; i < 4; ++i) model_get_input()->motor_command[i] = 1.0;
    development_quad_read_motor_command(motors);
    if (motors[0] != 1.0 || motors[3] != 1.0) return 2;
    for (i = 0; i < 100; ++i) model_step();
    model_get_output(&output);
    if (!model_is_loaded() || output.vd_mps >= 0.0) return 3;
    printf(\"%.12f\\n\", output.vd_mps);
    model_terminate();
    return model_is_loaded() ? 4 : 0;
}
""", encoding="utf-8")
            executable = package / "harness"
            compiled = subprocess.run(["gcc", "-std=c11", "-Wall", "-Werror", "-DMODEL_RT_BRIDGE_HEADER=model_rt_bridge.h",
                                        "-I", str(package), "-I", str(ROOT / "c_core" / "src"),
                                        str(package / "development_quad_model.c"), str(ROOT / "c_core" / "src" / "model_rt_wrapper.c"), str(harness), "-lm",
                                        "-o", str(executable)], capture_output=True, text=True, timeout=20)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertLess(float(ran.stdout), 0.0)

    def test_existing_package_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "quadrotor_hil"
            package.mkdir()
            with self.assertRaises(FileExistsError):
                self.module().create(package, INTERFACES, EXPECTED)
