# Model packages

`models/` is not a registry and must not contain an active-model symlink,
build history, rollback metadata or downloaded SLX files. Put immutable,
externally approved packages below the configured controlled package root
(default: `packages/`). The external model-management system owns upload,
versioning, approval and history.

Each package contains `package_manifest.json`, one top-level `.slx`,
`hil_contract.json`, and any declared dependencies. The HIL executor verifies
all declared file hashes and the package hash before MATLAB/GCC build.
