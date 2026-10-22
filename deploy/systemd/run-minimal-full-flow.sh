#!/bin/sh
# Execute one bounded two-circle smoke flow, then restore CONFIGURED readiness.
set -eu

# ``python -m input_simulator.smoke`` is a repository module, not a globally
# installed console script.  Operators invoke this file by absolute path from
# arbitrary working directories, so make the deployment root explicit before
# importing it.
cd /opt/hil

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root: sudo /bin/sh $0" >&2
    exit 1
fi

gateway_lock=/opt/hil/runtime/hil-gateway-resources/.lock
simulator_state=/opt/hil/runtime/input-simulator-state

restore_configured_hil() {
    # The resource store is exclusively owned by hil-gateway.  Stop its
    # systemd process before clearing only its exact lock file, so a previous
    # ungraceful termination cannot turn a recovery into a restart loop.
    systemctl stop hil-gateway.service || true
    rm -f "$gateway_lock"
    systemctl restart hil-core@current.service
    systemctl restart hil-prepare.service
    systemctl start hil-gateway.service
    systemctl is-active --quiet hil-prepare.service
    systemctl is-active --quiet hil-core@current.service
    systemctl is-active --quiet hil-gateway.service
}

reset_smoke_simulator_state() {
    # RunStore intentionally retains a finite durable history.  This bounded
    # smoke command must not fill that history with retry diagnostics.  Keep
    # the prior directory recoverably, then give the supervised `hil` service
    # a fresh owned store before it is started again.
    systemctl stop input-simulator.service || true
    if [ -e "$simulator_state" ]; then
        archived=${simulator_state}.before-smoke-$(date +%Y%m%dT%H%M%S)
        mv "$simulator_state" "$archived"
        echo "archived prior simulator smoke state: $archived"
    fi
    install -d -o hil -g hil -m 0750 "$simulator_state"
}

# Reconcile the target and gateway before each run.  This makes the command
# self-contained after an interrupted previous smoke run as well.
restore_configured_hil
reset_smoke_simulator_state
systemctl restart input-simulator.service
if ! /opt/hil/.venv/bin/python -m input_simulator.smoke \
    --template /opt/hil/config/minimal-integration-template.json; then
    # A failed external exchange must not leave a possibly running target for
    # the next caller. Restarting the supervised core returns it to STOPPED;
    # preparation then restores the fixed CONFIGURED snapshot.
    restore_configured_hil
    exit 1
fi
restore_configured_hil
systemctl is-active --quiet input-simulator.service
echo "full-flow smoke complete; HIL restored to CONFIGURED and ready for external callers"
