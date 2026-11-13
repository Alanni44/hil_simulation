#!/bin/sh
# Deploy the explicitly selected local quadrotor target, then start the HIL
# gateway and its bounded development CAN topology.  This does not enable a
# formal-release claim: can0..can2 are vcan interfaces.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root: sudo /bin/sh $0" >&2
    exit 1
fi

model_source=/opt/hil/artifacts/z_mission/bin/quadrotor_hil_rt
runtime_contract=/opt/hil/artifacts/z_mission/model/hil_contract.json
work_root=/opt/hil/runtime/work/current
work_model=$work_root/quadrotor_hil_rt
pending=/opt/hil/runtime/pending/current.json
gateway_resource_root=/opt/hil/runtime/hil-gateway-resources
status_archive_root=/opt/hil/runtime/hil-gateway-resources-status-evidence
legacy_status_archive=$gateway_resource_root/status-evidence

[ -x "$model_source" ] || { echo "missing executable model: $model_source" >&2; exit 1; }
[ -r "$runtime_contract" ] || { echo "missing model runtime contract: $runtime_contract" >&2; exit 1; }
[ -x /opt/hil/bin/hil-deploy ] || { echo "run install-production.sh first" >&2; exit 1; }

# Older gateway versions placed retained status evidence inside the strict
# ResourceStore root.  That makes all subsequent starts reject the directory
# as an unknown resource-store entry.  Stop the sole writer, then move the
# retained evidence without deleting or merging it.
if [ -e "$legacy_status_archive" ]; then
    systemctl stop hil-gateway.service || true
    if [ -e "$status_archive_root" ]; then
        if [ ! -d "$status_archive_root" ] || [ -L "$status_archive_root" ]; then
            echo "current gateway status archive is not a safe directory: $status_archive_root" >&2
            exit 1
        fi
        if [ -n "$(find "$status_archive_root" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
            echo "both legacy and current gateway status archives contain evidence; refusing to merge" >&2
            exit 1
        fi
        rmdir "$status_archive_root"
    fi
    if [ ! -d "$legacy_status_archive" ] || [ -L "$legacy_status_archive" ]; then
        echo "legacy gateway status archive is not a safe directory: $legacy_status_archive" >&2
        exit 1
    fi
    mv "$legacy_status_archive" "$status_archive_root"
    chown -R hil:hil "$status_archive_root"
fi
install -d -o hil -g hil -m 0750 "$gateway_resource_root" "$status_archive_root"

install -d -o hil -g hil -m 0750 "$work_root"
install -o hil -g hil -m 0750 "$model_source" "$work_model"
model_sha256=$(sha256sum "$work_model" | awk '{print $1}')
printf '{"executable_path":"%s","executable_sha256":"%s"}\n' "$work_model" "$model_sha256" > "$pending"

/opt/hil/bin/hil-deploy current
systemctl restart hil-vcan.service
systemctl restart hil-prepare.service
systemctl restart hil-gateway.service
systemctl start input-simulator.service
systemctl start hil-preparation.service
systemctl start hil-telemetry.service
systemctl is-active --quiet hil-core@current.service
systemctl is-active --quiet hil-prepare.service
systemctl is-active --quiet hil-gateway.service
systemctl is-active --quiet input-simulator.service
systemctl is-active --quiet hil-preparation.service
systemctl is-active --quiet hil-telemetry.service
echo "minimal HIL stack is active: preparation=0.0.0.0:18081, simulator=0.0.0.0:18080, telemetry=0.0.0.0:8765, CAN=vcan can0/can1/can2"
