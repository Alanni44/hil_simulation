# Development model fixtures

This directory contains development-only C model packages used to implement
and test the 3.6 ModelConsumer bridge before an approved generated model is
available. They are not a model registry, release package source, HIL target
asset, or qualification evidence.

`quadrotor_hil-dev-v1` is generated reproducibly by:

```text
.venv/bin/python -X utf8 scripts/create_development_quadrotor_package.py --output development_models/quadrotor_hil-dev-v1
```

The output is intentionally immutable: the destination must not already
exist. Its package manifest uses `DEVELOPMENT_C_ABI_ONLY_NOT_MATLAB`, and its
`.slx` file is a sentinel rather than a Simulink model. The production MATLAB
builder therefore must reject it. Use it only to develop the Consumer-to-C ABI
and deterministic readback tests; it cannot establish `APPLIED`, real-time,
airworthiness, or replacement qualification.
