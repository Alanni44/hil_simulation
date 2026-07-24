# HIL Full Pipeline Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Make the supported HIL model build through MATLAB R2018b ERT, GCC, the C core, Python services, and UDP integration while rejecting unsupported interfaces clearly.

**Architecture:** \`build_script.m\` owns generated-code discovery and a strict C-source manifest. Generated ERT types are exposed only through bridge headers and safe macros. \`main_rt.c\` is the only executable entry and consumes lock-free published command state.

**Tech Stack:** MATLAB R2018b/Embedded Coder ERT, GCC 7.x, GNU \`__sync\` primitives, Python 3.6.9, json-c, Bash.

## Global Constraints

- Ubuntu 18.04, MATLAB R2018b with Embedded Coder, Python 3.6.9, GCC 7.x.
- Scalar numeric/boolean root I/O only; \`pos_x\`, \`pos_y\`, \`pos_z\` mandatory.
- Keep command publication lock-free; do not add a mutex to the 1 ms loop.
- Exclude ERT \`ert_main.c\`; \`c_core/src/main_rt.c\` is the sole executable entry.
- Windows validates statically; \`bash scripts/integration_test.sh\` on Ubuntu is final proof.

---

### Task 1: Deterministic ERT GCC source manifest

**Files:** Modify \`matlab_scripts/build_script.m\`, \`scripts/integration_test.sh\`, \`tests/test_static_contract.py\`.

**Interfaces:** Consume ERT \`*.c\` sources; produce one GCC command containing model algorithms plus one project main.

- [ ] Write these failing tests:

\`\`\`python
def test_build_excludes_ert_example_main(self):
    source = read('matlab_scripts/build_script.m')
    self.assertIn("excluded_sources = {'ert_main.c'}", source)
    self.assertIn('any(strcmp(c_files(i).name, excluded_sources))', source)

def test_integration_executable_matches_build_output(self):
    self.assertIn('EXE="$ROOT/executables/hil_test_model_rt"',
                  read('scripts/integration_test.sh'))
\`\`\`

- [ ] Run the tests with \`python -m unittest tests.test_static_contract.ModelContractStaticTests.test_build_excludes_ert_example_main tests.test_static_contract.ModelContractStaticTests.test_integration_executable_matches_build_output\`; expected result: assertions fail.
- [ ] Change \`gen_c_flags\` to skip exactly \`ert_main.c\`:

\`\`\`matlab
excluded_sources = {'ert_main.c'};
for i = 1:length(c_files)
    if any(strcmp(c_files(i).name, excluded_sources))
        continue;
    end
    flags = [flags ' "' fullfile(code_dir, c_files(i).name) '"'];
end
\`\`\`

- [ ] Set integration \`EXE\` to \`$ROOT/executables/hil_test_model_rt\`, matching current \`build_script.m\` output for \`$ROOT/test_output\`.
- [ ] Run \`python -m unittest tests.test_static_contract\`; expected exit code 0.
- [ ] Commit: \`git add matlab_scripts/build_script.m scripts/integration_test.sh tests/test_static_contract.py && git commit -m "fix: exclude ERT example main from core build"\`.

### Task 2: Complete ERT ABI extraction and bridge inclusion

**Files:** Modify \`matlab_scripts/build_script.m\`, \`c_core/src/model_rt_wrapper.c\`, \`c_core/src/model_rt_wrapper.h\`, \`tests/test_static_contract.py\`.

**Interfaces:** Consume ERT \`ExtU_*\` and \`ExtY_*\` typedefs; produce complete mapping and bridge headers.

- [ ] Write failing tests requiring \`regexprep(inner, '/\\*[\\s\\S]*?\\*/', '')\`, \`regexprep(inner, '//[^\\r\\n]*', '')\`, \`bridge_header_name = 'model_rt_bridge.h';\`, and \`-DMODEL_RT_BRIDGE_HEADER=%s\`.
- [ ] Run the two targeted tests and verify pre-fix assertion failure.
- [ ] Remove C block/line comments before declaration splitting. Pass only the unquoted \`model_rt_bridge.h\` token through the macro and locate it with \`-I"<code_dir>"\`; stringify it once in the C wrappers.
- [ ] Run \`python -m unittest tests.test_static_contract\`; expected exit code 0. Target log requirement: \`ModelU_t fields (6)\` and \`ModelY_t fields (10)\`.
- [ ] Commit: \`git add matlab_scripts/build_script.m c_core/src/model_rt_wrapper.c c_core/src/model_rt_wrapper.h tests/test_static_contract.py && git commit -m "fix: compile generated ERT bridge headers"\`.

### Task 3: Lock-free command and mission publication

**Files:** Modify \`c_core/src/main_rt.c\`, \`tests/test_static_contract.py\`.

**Interfaces:** Consume JSON command datagrams; produce stable \`ModelU_t\` input and a model-thread-owned active waypoint plan before \`model_step()\`.

- [ ] Write a failing test requiring \`PendingCommandState_t pending_command\`, \`adopt_pending_command_state()\`, and absence of \`static int _cmd_mode_snapshot\`.
- [ ] Run \`python -m unittest tests.test_static_contract.ModelContractStaticTests.test_core_publishes_mission_metadata_with_the_input_snapshot\`; expected assertion failure.
- [ ] Define \`PendingCommandState_t\` with \`ModelU_t input\`, full waypoint plan, mission id, command-mode marker, and monotonic plan generation. The command thread edits only pending state between odd/even sequence increments. The model thread copies stable state, applies input, adopts plans only on generation changes, and exclusively owns progress.
- [ ] Run \`python -m unittest tests.test_static_contract\`; expected exit code 0 and no command-thread write to active waypoint globals.
- [ ] Commit: \`git add c_core/src/main_rt.c tests/test_static_contract.py && git commit -m "fix: publish mission state with command snapshot"\`.

### Task 4: Malformed command and process lifecycle hardening

**Files:** Modify \`c_core/src/main_rt.c\`, \`scripts/integration_test.sh\`, \`scripts/start_all.sh\`, \`tests/test_static_contract.py\`.

**Interfaces:** Consume arbitrary UDP JSON and process IDs; produce rejected malformed commands and reliable phase failure output.

- [ ] Write a failing test requiring \`json_object_get_type(wps_obj) != json_type_array\` before waypoint-array use.
- [ ] Run its targeted test; expected assertion failure.
- [ ] Add this guard before \`json_object_array_length\`:

\`\`\`c
if (!params_obj || !json_object_object_get_ex(params_obj, "waypoints", &wps_obj) ||
        json_object_get_type(wps_obj) != json_type_array) {
    json_object_put(root);
    return -1;
}
\`\`\`

- [ ] Keep \`kill -0\` service checks and explicit \`sudo "$EXE"\` / \`sudo "$EXE_PATH"\` paths.
- [ ] Run \`python -m unittest tests.test_static_contract && git diff --check\`; expected exit code 0.
- [ ] Commit: \`git add c_core/src/main_rt.c scripts/integration_test.sh scripts/start_all.sh tests/test_static_contract.py && git commit -m "fix: validate mission commands before publication"\`.

### Task 5: Python 3.6 service and binary-frame audit

**Files:** Modify \`python_services/shared/state_cache.py\`, \`python_services/udp_forwarder.py\`, \`python_services/shared/flight_state.py\`, \`tests/test_static_contract.py\`.

**Interfaces:** Consume C \`FlightState_t\` frames; produce synchronized Python state dictionaries.

- [ ] Write a failing test that requires \`_latest_raw\`, \`_sim_time\`, and \`_frame\` assignments inside one \`with _lock:\` block.
- [ ] Run its targeted test; expected assertion failure.
- [ ] Move metadata updates into the existing lock:

\`\`\`python
with _lock:
    _latest_raw = s
    _sim_time = s['timestamp_us'] / 1000000.0
    _frame = s.get('mission_id', 0)
\`\`\`

- [ ] Keep \`shared/flight_state.py\` as the canonical binary layout and import \`FLIGHT_STATE_SIZE\` from it in consumers.
- [ ] Run \`python -c "import ast,pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3,6)) for p in pathlib.Path('.').rglob('*.py')]; print('Python 3.6 grammar OK')"\` and \`python -m unittest tests.test_static_contract\`; expected exit code 0.
- [ ] Commit: \`git add python_services/shared/state_cache.py python_services/udp_forwarder.py python_services/shared/flight_state.py tests/test_static_contract.py && git commit -m "fix: synchronize Python flight-state metadata"\`.

### Task 6: Self-review and target acceptance handoff

**Files:** Modify \`README.md\`, \`tests/test_static_contract.py\`.

**Interfaces:** Consume all preceding changes; produce a reproducible Ubuntu acceptance command.

- [ ] Add a final test that requires \`excluded_sources = {'ert_main.c'}\`.
- [ ] Document the target commands:

\`\`\`bash
sudo apt install -y build-essential libjson-c-dev python3 python3-pip
python3 -m pip install -r requirements.txt
bash scripts/integration_test.sh
\`\`\`

Document the Embedded Coder requirement and expected six-input, ten-output ERT log.
- [ ] Run \`git diff --check && python -m unittest tests.test_static_contract && python -c "import ast,pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3,6)) for p in pathlib.Path('.').rglob('*.py')]; print('Python 3.6 grammar OK')"\`; expected exit code 0.
- [ ] Self-review all GCC arguments, bridge macros, seqlock writer/reader paths, Python metadata assignments, and executable paths against Global Constraints.
- [ ] Commit: \`git add README.md tests/test_static_contract.py && git commit -m "docs: document full pipeline acceptance checks"\`.

## Target Verification

After pushing commits, run on Ubuntu:

\`\`\`bash
git pull --ff-only origin main
bash scripts/integration_test.sh
\`\`\`

Acceptance requires an executable, three live services, and a final summary of zero failed tests. Windows checks alone are not MATLAB R2018b or GCC 7.x evidence.

