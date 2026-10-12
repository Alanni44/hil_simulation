#!/bin/sh
# Execute only in an approved maintenance window as root.  It validates the
# deployed hil-deploy helper without changing the steady-state core bytes:
# a same-byte restart is followed by an intentionally crashing replacement,
# which must be rolled back automatically.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root: sudo /bin/sh $0" >&2
    exit 2
fi

instance=current
runtime_root=/opt/hil/runtime
verified="$runtime_root/verified/${instance}_rt"
pending="$runtime_root/pending/${instance}.json"
work="$runtime_root/work/l003-systemd-$(date -u +%Y%m%dT%H%M%SZ)"
unit="hil-core@${instance}.service"
deploy_unit="hil-deploy@${instance}.service"
path_unit=hil-deploy.path
zeros=0000000000000000000000000000000000000000000000000000000000

cleanup() {
    rm -f "$pending"
    systemctl reset-failed "$deploy_unit" >/dev/null 2>&1 || true
    systemctl start "$path_unit" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

require_active() {
    systemctl is-active --quiet "$unit"
}

publish() {
    executable=$1
    sha256=$2
    printf '{"executable_path":"%s","executable_sha256":"%s"}\n' \
        "$executable" "$sha256" >"$pending"
}

expect_deploy_failure() {
    label=$1
    if systemctl start "$deploy_unit"; then
        echo "L-003 $label unexpectedly succeeded" >&2
        exit 1
    fi
    systemctl reset-failed "$deploy_unit"
    require_active
    echo "L-003 $label: rejected; current core remains active"
}

require_active
systemctl stop "$path_unit"
mkdir -p "$work"
chmod 0750 "$work"

# Wrong hash must be rejected before a replacement is installed or restarted.
same="$work/current-identical_rt"
install -m 0750 "$verified" "$same"
same_hash=$(sha256sum "$same" | awk '{print $1}')
publish "$same" "$zeros"
expect_deploy_failure wrong_hash
rm -f "$pending"

# A same-byte deployment proves the systemd deployment path and post-start
# active-window check without changing the running model revision.
publish "$same" "$same_hash"
systemctl start "$deploy_unit"
require_active
test ! -e "$pending"
test ! -e "${verified}.rollback"
echo "L-003 same_byte_deploy: active-window check passed"

# The helper must restore the predecessor after a replacement exits at once.
bad="$work/immediate_failure_rt"
printf '#!/bin/sh\nexit 1\n' >"$bad"
chmod 0750 "$bad"
bad_hash=$(sha256sum "$bad" | awk '{print $1}')
publish "$bad" "$bad_hash"
expect_deploy_failure rollback_after_failed_start
test ! -e "${verified}.rollback"
rm -f "$pending"

echo "L-003 systemd deployment and rollback verification passed"
