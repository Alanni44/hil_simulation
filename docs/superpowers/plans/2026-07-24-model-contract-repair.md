# HIL Model Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the HIL build pipeline reject unsupported Simulink interfaces deterministically and generate a C adapter that uses the actual ERT ABI.

**Architecture:** MATLAB emits a compact model ABI contract after code generation. The C wrapper includes a generated bridge before generated configuration, while `main_rt.c` consumes generated, safe accessor and writer macros. Python static tests protect the source-level contract on Windows; the shell integration test remains the final target-machine acceptance check.

**Tech Stack:** MATLAB R2018b/Embedded Coder, ERT C output, GCC 7, C11/POSIX, Python 3.6 `unittest`, Bash.

## Global Constraints

- Target runtime is Ubuntu 18.04, MATLAB R2018b, Python 3.6.9 and GCC 7.x.
- Models must expose scalar numeric root ports; Bus, vector, matrix, fixed-point and enum ports are rejected.
- `pos_x`, `pos_y`, and `pos_z` are mandatory output mappings.
- No claim of target runtime success may be made from this Windows workspace.

---

### Task 1: Add Windows-runnable static regression checks

**Files:**
- Create: `tests/test_static_contract.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: source text in `matlab_scripts/`, `c_core/src/`, and `scripts/`.
- Produces: `python -m unittest discover -s tests -v` regression command.

- [ ] **Step 1: Write failing tests**

Create tests that assert the GCC command does not use `-include`, `adapt_model.m` declares the three mandatory position outputs, `main_rt.c` uses generated safe accessors, and integration test indexes remain in the unpacked `FlightState_t` range.

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m unittest discover -s tests -v`

Expected: failures identifying the current forced include, missing strict output declarations, unsafe accessor implementation, or invalid UDP indexes.

- [ ] **Step 3: Add reproducible Python dependency declaration**

Create `requirements.txt` containing `PyYAML==6.0.1`.

- [ ] **Step 4: Re-run static tests after each later task**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass only after Tasks 2-4.

### Task 2: Define strict interface analysis and generated configuration

**Files:**
- Modify: `matlab_scripts/adapt_model.m`
- Modify: `matlab_scripts/build_script.m`

**Interfaces:**
- Consumes: root port metadata and optional `field_mapping.json` aliases.
- Produces: `field_mapping.json`, `model_rt_bridge.h`, and `model_config.h` with mandatory output validation and type-safe generated macros.

- [ ] **Step 1: Add failing MATLAB contract cases**

Add local MATLAB helper checks in `build_script.m` that return a failure result when `pos_x`, `pos_y`, or `pos_z` lacks a mapped scalar numeric Outport; reject all non-scalar or non-numeric root ports before GCC runs.

- [ ] **Step 2: Replace topology rewriting with analysis only**

Make `adapt_model.m` retain the original model and emit mapping metadata. Remove Constant/Step/Scope/ToWorkspace substitution; change `isKey(std_inputs, name)` to `isfield(std_inputs, name)`.

- [ ] **Step 3: Parse generated ERT ABI from the model header**

Read `<model>.h`, locate the `ExtU` and `ExtY` typedefs and `<model>_U`/`<model>_Y` declarations, then write bridge aliases using the discovered names. If discovery fails, write an explicit build failure.

- [ ] **Step 4: Generate safe C configuration**

Emit one accessor macro per known state field. Emit direct default expressions for absent optional outputs and reject absent position outputs. Emit typed writable-field table entries only for scalar numeric input fields.

- [ ] **Step 5: Verify static test progress**

Run: `python -m unittest discover -s tests -v`

Expected: interface-contract source checks pass; C-core and shell checks may still fail before Tasks 3-4.

### Task 3: Make the C adapter type-safe and race-free

**Files:**
- Modify: `c_core/src/model_rt_wrapper.h`
- Modify: `c_core/src/model_rt_wrapper.c`
- Modify: `c_core/src/main_rt.c`

**Interfaces:**
- Consumes: generated bridge/configuration headers from Task 2.
- Produces: a process that accesses only generated members and applies UDP updates at model-step boundaries.

- [ ] **Step 1: Include generated ABI before fallback declarations**

Update `model_rt_wrapper.h` to include `MODEL_RT_BRIDGE_H` when defined, then retain fallback structs only for manual development builds.

- [ ] **Step 2: Replace unsafe generic C macros**

Remove `MODEL_Y_GET` and `MODEL_U_SET`; use Task 2 generated `MODEL_READ_*` and `MODEL_WRITE_*` macros. The macros must not mention missing model members.

- [ ] **Step 3: Add typed tune dispatch**

Use a generated enum in each table entry and write through `double*`, `float*`, integer pointer, or boolean pointer as appropriate. Reject non-finite values and unknown entries.

- [ ] **Step 4: Apply command snapshots in the real-time loop**

Guard pending command state with `pthread_mutex_t`; the UDP thread updates the pending state and main loop applies it once before `model_step()`.

- [ ] **Step 5: Verify static checks**

Run: `python -m unittest discover -s tests -v`

Expected: all C-source contract checks pass.

### Task 4: Repair target validation and startup reproducibility

**Files:**
- Modify: `scripts/integration_test.sh`
- Modify: `scripts/start_all.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: `FlightState_t` layout and generated executable.
- Produces: correct Bash exit status and documented target-machine commands.

- [ ] **Step 1: Correct integration assertions**

Pass explicit `0` or `1` to `check`; use unpacked indexes `2,3,4,27,28,29`; make T5/T6 pass only when polling receives a valid state; and initialize cleanup PID variables safely.

- [ ] **Step 2: Require explicit model path and prerequisites**

Require `SLX_PATH` when no project-local model exists. Document `Embedded Coder`, `libjson-c-dev`, pinned PyYAML, and the target acceptance command.

- [ ] **Step 3: Run static regression suite and shell syntax check**

Run: `python -m unittest discover -s tests -v` and `bash -n scripts/integration_test.sh scripts/start_all.sh` on a Bash-capable host.

Expected: source regression suite passes and Bash parser reports no syntax error.

- [ ] **Step 4: Commit implementation**

Run: `git add matlab_scripts c_core scripts README.md requirements.txt tests docs && git commit -m "fix: enforce generated model contract"`

### Target-machine acceptance

Run on Ubuntu 18.04 with MATLAB R2018b + Embedded Coder and GCC 7.x:

```bash
python3 -m pip install -r requirements.txt
chmod +x scripts/integration_test.sh scripts/start_all.sh scripts/stop_all.sh
./scripts/integration_test.sh
```

Expected: MATLAB creates the test model, ERT generation and GCC compilation complete, the test reports zero failed checks, and exits `0`.
