#!/bin/sh
# Install the HIL systemd production boundary after /opt/hil has been synced.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root: sudo $0" >&2
    exit 1
fi

simulator_python=/opt/hil/.venv/bin/python
if [ ! -x "$simulator_python" ]; then
    echo "missing isolated Python 3.12 simulator runtime: $simulator_python" >&2
    echo "create it from /opt/hil with python3.12 -m venv .venv and install requirements-icd.txt" >&2
    exit 1
fi
simulator_base_prefix=$("$simulator_python" -c 'import sys; print(sys.base_prefix)')
case "$simulator_base_prefix" in
    /opt/hil/*) ;;
    *)
        echo "simulator virtual environment was copied from outside /opt/hil: $simulator_base_prefix" >&2
        echo "recreate it with: /opt/hil/runtime/python3.12/bin/python3.12 -m venv --clear /opt/hil/.venv" >&2
        exit 1
        ;;
esac
if ! (cd /opt/hil && "$simulator_python" -c 'import icd_gateway, icd_runtime, input_simulator, jsonschema, referencing, yaml'); then
    echo "isolated simulator runtime is missing required packages or cannot import this checkout" >&2
    exit 1
fi

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! getent group hil >/dev/null; then
    groupadd --system hil
fi
if ! id hil >/dev/null 2>&1; then
    useradd --system --gid hil --no-create-home --shell /usr/sbin/nologin hil
fi

install -d -o hil -g hil -m 0750 /opt/hil/runtime /opt/hil/runtime/work \
    /opt/hil/runtime/pending /opt/hil/artifacts /opt/hil/artifacts/acceptance \
    /opt/hil/logs /opt/hil/runtime/input-simulator-state /opt/hil/runtime/hil-gateway-resources
install -d -o root -g hil -m 0750 /opt/hil/runtime/verified
install -d -o root -g root -m 0755 /opt/hil/bin
install -d -o root -g hil -m 0750 /etc/hil
# Existing log files can have been created by an earlier root-run command.
# The long-lived unprivileged HIL services are the sole writers here.
chown -R hil:hil /opt/hil/logs

install -o root -g root -m 0755 "$source_dir/hil-deploy" /opt/hil/bin/hil-deploy
install -o root -g root -m 0755 "$source_dir/hil-vcan-setup" /opt/hil/bin/hil-vcan-setup
install -o root -g root -m 0755 "$source_dir/start-minimal-hil.sh" /opt/hil/bin/start-minimal-hil
install -o root -g root -m 0755 "$source_dir/run-minimal-full-flow.sh" /opt/hil/bin/run-minimal-full-flow
install -o root -g root -m 0644 "$source_dir/hil-python-services.service" \
    /etc/systemd/system/hil-python-services.service
install -o root -g root -m 0644 "$source_dir/input-simulator.service" \
    /etc/systemd/system/input-simulator.service
install -o root -g root -m 0644 "$source_dir/hil-vcan.service" \
    /etc/systemd/system/hil-vcan.service
install -o root -g root -m 0644 "$source_dir/hil-gateway.service" \
    /etc/systemd/system/hil-gateway.service
install -o root -g root -m 0644 "$source_dir/hil-prepare.service" \
    /etc/systemd/system/hil-prepare.service
install -o root -g root -m 0644 "$source_dir/hil-preparation.service" \
    /etc/systemd/system/hil-preparation.service
install -o root -g root -m 0644 "$source_dir/hil-telemetry.service" \
    /etc/systemd/system/hil-telemetry.service
install -o root -g root -m 0644 "$source_dir/hil-core@.service" \
    /etc/systemd/system/hil-core@.service
install -o root -g root -m 0644 "$source_dir/hil-deploy@.service" \
    /etc/systemd/system/hil-deploy@.service
install -o root -g root -m 0644 "$source_dir/hil-deploy.path" \
    /etc/systemd/system/hil-deploy.path
# /opt/hil is an editable checkout owned by the deployment user.  Although
# the runtime directories above are real directories with controlled modes,
# systemd-tmpfiles deliberately refuses paths below such a non-root-owned
# ancestor and reports them as unsafe symlinks.  Do not register a tmpfiles
# rule for this tree: this installer is the authoritative directory setup.
# Remove a rule left by an earlier installer attempt so it cannot emit the
# same error during boot-time tmpfiles processing.
rm -f /etc/tmpfiles.d/hil-runtime.conf
install -o root -g hil -m 0640 /opt/hil/config/minimal-integration-simulator.json \
    /etc/hil/minimal-integration-simulator.json
install -o root -g hil -m 0640 /opt/hil/config/minimal-integration-gateway.json \
    /etc/hil/minimal-integration-gateway.json

systemctl daemon-reload
systemctl enable --now hil-deploy.path
# The legacy monolithic service owns the same UDP/8765 sockets as the
# dedicated read-only telemetry unit.  Never leave both enabled at boot.
systemctl disable --now hil-python-services.service || true
systemctl enable input-simulator.service
systemctl enable hil-vcan.service
systemctl enable hil-gateway.service
systemctl enable hil-preparation.service
systemctl enable hil-telemetry.service
echo "HIL production systemd boundary installed. Start the minimal stack to activate preparation, gateway, simulator and telemetry."
