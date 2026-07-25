# Model artifact registry

`models/` is an append-only build registry.  Do not place generated artifacts
directly in the repository root.

```text
models/
  registry/<model_name>/<build_id>/
    source/<model_name>.slx       # immutable uploaded source copy
    artifacts/                    # ERT code, mapping and analysis output
    executable/<model_name>_rt    # compiled core executable
    logs/matlab_build.log
    build_task.json
    build_result.json
    manifest.json
  active/<model_name> -> ../registry/<model_name>/<build_id>
  locks/<model_name>.lock
```

A build ID contains a UTC timestamp, a prefix of the source SHA-256, and a
random suffix.  `manifest.json` records the source and executable hashes,
task, toolchain details, source-tree fingerprints, Git revision/dirty state,
status, and build result.  Failed builds are retained
with `status: failed` for diagnosis, but never update `active` or
the model-ready signal (by default `/tmp/model_ready.signal`, configurable
through `HIL_MODEL_READY_SIGNAL`).  Production sets `HIL_MODEL_READY_DIR=/run/hil`:
each activation then emits `/run/hil/<model_name>.signal`, so independent
`hil-core@<model_name>` services cannot consume another model's update.

The Python build endpoint serializes builds for each model name using an
advisory lock.  Different model names may build concurrently.  Roll back by
calling the `activate_model_build` WebSocket command with a prior successful
`build_id`; it verifies the archived executable SHA-256, atomically replaces
the relevant `models/active/` symlink, then publishes the core's model-ready
signal.  Use `list_model_builds` to list build IDs and their status.  A
successful `load_model` build activates its new version automatically.

WebSocket administration payloads:

```json
{"cmd":"list_model_builds","params":{"model_name":"my_model"}}
```

```json
{"cmd":"activate_model_build","params":{"model_name":"my_model","build_id":"20260725T120000Z_a1b2c3d4e5f6_1234abcd"}}
```

## Operator and remote-administration boundary

For a controlled local build, run the repository script as the `hil` service
account:

```bash
HIL_MODEL_READY_DIR=/run/hil ./scripts/build_model.py /secure/inbox/my_model.slx my_model
```

Remote `load_model`, `list_model_builds`, and `activate_model_build` commands
are disabled by default.  They become available only with
`HIL_ENABLE_REMOTE_MODEL_ADMIN=1`; this must be set only when the upstream
Spring Boot endpoint authenticates and authorizes model administrators.  A
remote build also requires `HIL_MODEL_DOWNLOAD_ALLOWLIST` (a comma-separated
exact hostname list) and is bounded by `HIL_MODEL_DOWNLOAD_MAX_BYTES`
(default 100 MiB).  This prevents the flight-control data plane from becoming
an unauthenticated arbitrary-download-and-compile service.

For a controlled deployment acceptance test between two successful archived
builds, use the opt-in script below.  It restores the original active build in
its exit handler, including after a failed switch:

```bash
HIL_HOT_RELOAD_TEST=1 ./scripts/test_hot_reload.sh my_model CURRENT_BUILD_ID TARGET_BUILD_ID
```
