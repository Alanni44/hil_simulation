# Task 3 — UE4 V2 acceleration boundary

## Status

Completed. Acceleration remains part of the fixed C-to-Python binary-state ABI,
but is no longer exposed by the generic NED-to-UE4 projection or serialized in
UE4 V2.0 `vehicle_state` JSON. The V2 packet now emits only the applicable
protocol fields: `mission_id`, `sim_time`, `position`, `attitude`, `velocity`,
and `angular_velocity`; `flight_state` remains absent for the internal lifecycle
as required by the existing runtime contract.

## TDD evidence

The V2 regression test was changed before production code. Its first run failed
as intended because `packet['data']` contained `acceleration` (along with the
non-protocol `sequence` and `rate_hz` fields). The minimal projection and
serialization removal made the test pass.

## Verification

- `python -m unittest tests.test_v2_protocol tests.test_static_contract -v` — 16 passed.
- `python -m unittest discover -s tests -v` — 43 passed.
- `git diff --check` — clean.

## Self-review

Reviewed the final diff: only `python_services/shared/state_cache.py`, the V2
regression test, and its static contract assertion changed. Binary parsing and
the fixed 100-byte state ABI are untouched.

## Concern

`docs/ubuntu-interface-acceptance.md` still describes acceleration as a V2
field. It was left unchanged because this task was limited to the review finding
and its requested code/test fix; the binding contract and implementation now
exclude it.
