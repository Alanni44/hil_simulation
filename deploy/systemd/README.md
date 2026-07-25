# Production service deployment

Install the project under `/opt/hil`, create a non-login `hil` account, and
install the Python dependencies in `/opt/hil/venv`.  Give that account write
access only to the model registry and runtime handoff directory:

```bash
sudo useradd --system --home /nonexistent --shell /usr/sbin/nologin hil
sudo install -d -o hil -g hil -m 0750 /opt/hil/models/registry /opt/hil/models/active /opt/hil/models/locks
```

Copy both unit files to
`/etc/systemd/system/` and copy `deploy/tmpfiles.d/hil.conf` to
`/etc/tmpfiles.d/hil.conf`.  The core unit is a template: replace
`my_model` below with the model name.  It starts the executable selected by
`models/active/my_model`, so activating or rolling back a build changes the
next service start without copying binaries.
Then run:

```bash
sudo systemctl daemon-reload
sudo systemd-tmpfiles --create /etc/tmpfiles.d/hil.conf
sudo systemctl enable --now hil-python-services.service hil-core@my_model.service
sudo systemctl status hil-python-services.service hil-core@my_model.service
```

Build the initial active model before starting its core instance.  The build
is archived, checksummed, and activated atomically:

```bash
cd /opt/hil
sudo -u hil HIL_MODEL_READY_DIR=/run/hil ./scripts/build_model.py /secure/inbox/my_model.slx my_model
sudo systemctl start hil-core@my_model.service
```

The core runs as `hil`, not root.  The unit grants only `CAP_SYS_NICE` and
`CAP_IPC_LOCK`, allowing the existing real-time scheduler and memory-locking
calls without an interactive `sudo` prompt.  Inspect logs with:

```bash
journalctl -u 'hil-core@*.service' -u hil-python-services.service -f
```

The Python service deliberately disables remote model build/list/activation
commands unless `HIL_ENABLE_REMOTE_MODEL_ADMIN=1`.  Enable it only in a
separately authenticated Spring Boot management route, and set a strict
`HIL_MODEL_DOWNLOAD_ALLOWLIST`; the service otherwise has no basis to decide
which WebSocket client may compile and execute a model.

For development and CI, `scripts/integration_test.sh` deliberately starts the
core without privileges.  To exercise the local sudo launch explicitly, run
`HIL_USE_SUDO=1 ./scripts/integration_test.sh` from an interactive terminal.
