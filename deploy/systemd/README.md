# systemd deployment

The external model-management system places immutable packages in
`/opt/hil/packages`. The Python executor validates and builds a requested
package in its private work directory, then stops the existing core before
starting the one fully verified replacement. It does not maintain a model
registry, active symlink, rollback endpoint, remote download endpoint, or
in-process hot-reload signal.

Production sets `HIL_DEPLOY_MODE=systemd`.  The executor writes a SHA-256
descriptor to `/opt/hil/runtime/pending/current.json` and starts
`hil-deploy@current.service`; only that unit atomically installs and restarts
`hil-core@current.service`. Development uses the separate `dev_runner` helper
and reports `DEV_DEPLOYED`, never `DEPLOYED`.
