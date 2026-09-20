# systemd production deployment

The external model-management system places immutable packages in
`/opt/hil/packages`. The unprivileged Python service validates and builds a
requested package under `/opt/hil/runtime/work`; it cannot directly start or
stop the real-time core. It writes only a short SHA-256 descriptor to
`/opt/hil/runtime/pending/current.json`. The enabled `hil-deploy.path` unit
observes that atomic publish and requests `hil-deploy@current`.

`hil-deploy@current` runs as root but does not execute package content. It
accepts an executable only from the work root, opens it without following a
symlink, verifies its SHA-256 while copying it, then atomically places it in
the root-owned `/opt/hil/runtime/verified/current_rt` location. It restarts
`hil-core@current`, which runs the binary as `hil`. The old core remains alive
during MATLAB/GCC generation and is stopped only when the verified replacement
is ready to start. There is intentionally no rollback pointer or hot reload.

`hil-core@current` has no dependency on `hil-python-services`; restarting the
Python bridge does not stop a running core. A successful production deployment
reports `DEPLOYED` only after the existing UDP health gate receives a valid
RUNNING state.

## Install on a target

First synchronize this repository to `/opt/hil` and create
`/etc/hil/gitlab-release.env` as documented in the project README. Then run:

```bash
sudo /opt/hil/deploy/systemd/install-production.sh
sudo systemctl restart hil-python-services.service
sudo systemctl status hil-python-services.service --no-pager
```

The installer creates the dedicated `hil` account only when absent, installs
the service and path units, and prepares the runtime directories. No polkit or
sudo permission is granted to the Python service: systemd itself triggers the
root deployment helper only when the controlled pending descriptor appears.

After a GitLab package is validated and staged, use the normal console deploy
button. Confirm both services independently:

```bash
sudo systemctl status hil-python-services.service --no-pager
sudo systemctl status hil-core@current.service --no-pager
sudo journalctl -u hil-core@current.service -n 100 --no-pager
```
