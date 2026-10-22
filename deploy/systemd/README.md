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
keeps the transaction open until the restarted unit remains active across its
bounded health window. If restarting the new core fails, the helper restores
the previous verified executable and restarts that core before reporting failure.
The predecessor exists only during that transaction; there is no operator
rollback pointer or hot reload.

`input-simulator.service` is a separate unprivileged management endpoint on
`0.0.0.0:18080`, so a remote backend calls
`http://192.168.100.165:18080/api/simulator/commands` directly. It runs only the fixed v0.3 template and the explicit
formal UDP runtime configuration copied to
`/etc/hil/minimal-integration-simulator.json`. The configuration's source and
feedback endpoints must exactly match an authorized HIL gateway deployment;
the unit has no permission to modify the core executable or use arbitrary
network/command inputs. Its Run/Record state is atomically persisted below
`/opt/hil/runtime/input-simulator-state`. After a process restart, a Run that
was actively executing is retained as `COMPLETED/INCOMPLETE` with a recovery
record; the service never restores its source Session or replays START/STOP.
It runs with `/opt/hil/.venv/bin/python`, an isolated Python 3.12 environment;
it never uses the legacy `/opt/hil/venv/bin/python3` owned by the older HIL
service. The installer rejects a missing interpreter or missing simulator
imports before it installs/enables the unit.

`hil-preparation.service` is the first-circle HIL management endpoint on
`0.0.0.0:18081`. It accepts only the deployment-owned fixed RunConfigure
snapshot and returns an actual `CONFIGURED` readback for the 3.6 caller.
`hil-telemetry.service` owns UDP status port 9998 and publishes the fresh
C-core state to 3.6 on `0.0.0.0:8765/ws/hil`. It deliberately disables the
legacy WebSocket START/STOP path. The telemetry unit conflicts with the old
monolithic `hil-python-services.service`, so the latter must not be started
alongside it.

The deployment unit deliberately has no `Before=hil-core@%i.service` ordering
edge: the helper itself synchronously restarts that same unit, and such an edge
would make systemd wait for the helper while the helper waits for the restart.

## Install on a target

First synchronize this repository to `/opt/hil` and create
`/etc/hil/gitlab-release.env` as documented in the project README. Then run:

```bash
cd /opt/hil
/opt/hil/runtime/python3.12/bin/python3.12 -m venv --clear /opt/hil/.venv
.venv/bin/python -m pip install -r requirements-icd.txt
sudo /bin/sh /opt/hil/deploy/systemd/install-production.sh
sudo /bin/sh /opt/hil/bin/start-minimal-hil
sudo systemctl status hil-core@current.service hil-gateway.service input-simulator.service \
  hil-preparation.service hil-telemetry.service --no-pager
```

`requirements-icd.txt` also supplies PyYAML for the isolated telemetry
service. Re-run the pip command after pulling this two-circle update, before
running the installer.

The installer creates the dedicated `hil` account only when absent, installs
the service and path units, and prepares the runtime directories. No polkit or
sudo permission is granted to the Python service: systemd itself triggers the
root deployment helper only when the controlled pending descriptor appears.

`start-minimal-hil` deploys only the checked-in `quadrotor_hil_rt` asset to the
root-owned runtime location, starts the C core and starts `hil-gateway.service`.
It provisions `can0`, `can1` and `can2` as `vcan` interfaces. This is the
three-chain development topology, not a physical CAN FD qualification.

The endpoints to hand to the remote backend after the stack is active are
`http://192.168.100.165:18081/api/hil/preparation/commands` (3.6 first
circle over HTTP), `http://192.168.100.165:18080/api/simulator/commands`
(3.3 second circle), and `ws://192.168.100.165:8765/ws/hil` (3.6 telemetry
only). `hil-telemetry.service` never accepts `INITIALIZE`, `START` or `STOP`;
all first-circle writes belong exclusively to `hil-preparation.service`.

To run one bounded local full-flow smoke test (CREATE, START, the fixed ID10
scenario input, STOP and Record verification) and restore `CONFIGURED` for
the external caller afterward, run:

```bash
sudo /bin/sh /opt/hil/bin/run-minimal-full-flow
```

After a GitLab package is validated and staged, use the normal console deploy
button. Confirm both services independently:

```bash
sudo systemctl status hil-python-services.service --no-pager
sudo systemctl status hil-core@current.service --no-pager
sudo journalctl -u hil-core@current.service -n 100 --no-pager
```
