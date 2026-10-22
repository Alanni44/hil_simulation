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

[ -x "$model_source" ] || { echo "missing executable model: $model_source" >&2; exit 1; }
[ -r "$runtime_contract" ] || { echo "missing model runtime contract: $runtime_contract" >&2; exit 1; }
[ -x /opt/hil/bin/hil-deploy ] || { echo "run install-production.sh first" >&2; exit 1; }

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
