# systemd deployment

The external model-management system places immutable packages in
`/opt/hil/packages`. The Python executor validates and builds a requested
package in its private work directory, then stops the existing core before
starting the one fully verified replacement. It does not maintain a model
registry, active symlink, rollback endpoint, remote download endpoint, or
in-process hot-reload signal.
