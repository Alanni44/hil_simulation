# Task 3 re-review acceptance fix

## Scope

Corrected the UE4 V2 acceptance contract only. Internal acceleration remains
required by the C/Python model ABI and is not part of `vehicle_state.data`.

## TDD evidence

- Added `test_ue4_acceptance_contract_excludes_internal_acceleration_and_rate`.
- RED: the focused test failed because the harness accessed
  `ue4['acceleration']` (and also accessed `ue4['rate_hz']`).
- GREEN: the acceptance harness now requires the mandatory V2 fields and
  rejects keys outside the allowed V2 set. Its existing 10-second stream check
  remains the 50 Hz validation.

## Documentation

The Ubuntu acceptance guide now limits `vehicle_state.data` to mission ID,
simulation time, position, attitude, and optional velocity, angular velocity,
and flight state. It explicitly excludes `acceleration` and `rate_hz`, retains
acceleration in the internal C/Python ABI, and validates 50 Hz through
`hello.data.state_rate_hz` plus the state stream frequency.

## Verification

- `python -m unittest tests.test_static_contract tests.test_v2_protocol tests.test_quadrotor_model_contract` — 23 tests passed.
- `python -m unittest discover -s tests -p 'test_*.py'` — 44 tests passed.

The full suite emitted pre-existing `ResourceWarning` messages from
`tests/test_model_registry.py` for unclosed temporary files; it had no test
failures. MATLAB/Ubuntu runtime acceptance was not run on this Windows
workstation.
