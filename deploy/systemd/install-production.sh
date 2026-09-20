#!/bin/sh
# Install the HIL systemd production boundary after /opt/hil has been synced.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root: sudo $0" >&2
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
    /opt/hil/logs
install -d -o root -g hil -m 0750 /opt/hil/runtime/verified
install -d -o root -g root -m 0755 /opt/hil/bin

install -o root -g root -m 0755 "$source_dir/hil-deploy" /opt/hil/bin/hil-deploy
install -o root -g root -m 0644 "$source_dir/hil-python-services.service" \
    /etc/systemd/system/hil-python-services.service
install -o root -g root -m 0644 "$source_dir/hil-core@.service" \
    /etc/systemd/system/hil-core@.service
install -o root -g root -m 0644 "$source_dir/hil-deploy@.service" \
    /etc/systemd/system/hil-deploy@.service
install -o root -g root -m 0644 "$source_dir/hil-deploy.path" \
    /etc/systemd/system/hil-deploy.path
install -o root -g root -m 0644 "$source_dir/hil-runtime.conf" \
    /etc/tmpfiles.d/hil-runtime.conf

systemctl daemon-reload
systemd-tmpfiles --create /etc/tmpfiles.d/hil-runtime.conf
systemctl enable --now hil-deploy.path
systemctl enable hil-python-services.service
echo "HIL production systemd boundary installed. Restart hil-python-services when ready."
