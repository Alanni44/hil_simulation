#!/usr/bin/env bash
set -euo pipefail

EXPECTED_SHA256="febbf0e10c98b3d4adafa7dcb5027e0e6b0f212b6828a779f404d51ddf172134"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PREPARED="$ROOT/artifacts/history/round2/prepared.pcap"
ATTEMPT_NAME="${ROUND3_ATTEMPT:-retry_1}"
ATTEMPT_DIR="$ROOT/artifacts/history/round3/$ATTEMPT_NAME"
RECEIVED="$ATTEMPT_DIR/received.pcap"

TX_NS="uav-r3-tx-$$"
RX_NS="uav-r3-rx-$$"
TX_VETH="r3tx$$"
RX_VETH="r3rx$$"
TX_CREATED=0
RX_CREATED=0
TCPDUMP_PID=""

fail() {
  echo "ROUND3_ERROR: $*" >&2
  exit 1
}

cleanup() {
  set +e
  if [[ -n "$TCPDUMP_PID" ]] && kill -0 "$TCPDUMP_PID" 2>/dev/null; then
    kill "$TCPDUMP_PID" 2>/dev/null
    wait "$TCPDUMP_PID" 2>/dev/null
  fi
  if [[ "$TX_CREATED" == "1" ]]; then
    ip netns del "$TX_NS" 2>/dev/null
  fi
  if [[ "$RX_CREATED" == "1" ]]; then
    ip netns del "$RX_NS" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

[[ "$(uname -s)" == "Linux" ]] || fail "Linux kernel required"
[[ "$(id -u)" == "0" ]] || fail "root required"
for cmd in ip tcpreplay tcpdump sha256sum; do
  command -v "$cmd" >/dev/null || fail "missing tool: $cmd"
done

[[ -f "$PREPARED" ]] || fail "prepared.pcap missing"
ACTUAL_SHA256="$(sha256sum "$PREPARED" | awk '{print $1}')"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] || fail "prepared.pcap SHA256 mismatch"

if [[ -e "$ATTEMPT_DIR" ]]; then
  fail "refusing to overwrite existing retry_1 evidence directory"
fi
mkdir -p "$ATTEMPT_DIR"

{
  echo "environment_class=WSL2_SOFTWARE_ONLY"
  echo "target_kylin_qualified=false"
  echo "kernel=$(uname -a)"
  echo "prepared_pcap_sha256=$ACTUAL_SHA256"
  echo "path_translation_only=true"
  echo "prepared_linux_path=$PREPARED"
} > "$ATTEMPT_DIR/environment.txt"
cat /etc/os-release > "$ATTEMPT_DIR/os-release.txt"
ip -Version > "$ATTEMPT_DIR/ip_version.txt" 2>&1
tcpreplay --version > "$ATTEMPT_DIR/tcpreplay_version.txt" 2>&1
tcpdump --version > "$ATTEMPT_DIR/tcpdump_version.txt" 2>&1

ip netns list | awk '{print $1}' | grep -Fxq "$TX_NS" && fail "TX namespace already exists"
ip netns list | awk '{print $1}' | grep -Fxq "$RX_NS" && fail "RX namespace already exists"

ip netns add "$TX_NS"
TX_CREATED=1
ip netns add "$RX_NS"
RX_CREATED=1

ip link add "$TX_VETH" type veth peer name "$RX_VETH"
ip link set "$TX_VETH" netns "$TX_NS"
ip link set "$RX_VETH" netns "$RX_NS"

ip netns exec "$TX_NS" ip link set lo up
ip netns exec "$RX_NS" ip link set lo up

ip netns exec "$TX_NS" ip link set "$TX_VETH" name eth0
ip netns exec "$RX_NS" ip link set "$RX_VETH" name eth0

ip netns exec "$TX_NS" ip link set dev eth0 address 02:00:00:00:00:01
ip netns exec "$RX_NS" ip link set dev eth0 address 02:00:00:00:00:02
ip netns exec "$TX_NS" ip addr add 10.36.0.10/24 dev eth0
ip netns exec "$RX_NS" ip addr add 10.36.0.20/24 dev eth0
ip netns exec "$TX_NS" ip link set eth0 up
ip netns exec "$RX_NS" ip link set eth0 up

ip netns exec "$TX_NS" ip -details link show > "$ATTEMPT_DIR/tx_link.txt"
ip netns exec "$RX_NS" ip -details link show > "$ATTEMPT_DIR/rx_link.txt"
ip netns exec "$TX_NS" ip addr show > "$ATTEMPT_DIR/tx_addr.txt"
ip netns exec "$RX_NS" ip addr show > "$ATTEMPT_DIR/rx_addr.txt"
ip netns exec "$TX_NS" ip route show > "$ATTEMPT_DIR/tx_route.txt"
ip netns exec "$RX_NS" ip route show > "$ATTEMPT_DIR/rx_route.txt"

if ip netns exec "$TX_NS" ip route show default | grep -q .; then
  fail "TX namespace unexpectedly has a default route"
fi
if ip netns exec "$RX_NS" ip route show default | grep -q .; then
  fail "RX namespace unexpectedly has a default route"
fi

printf '%s\n' "tcpreplay --intf1=eth0 --loop=1 --multiplier=1.0 $PREPARED" > "$ATTEMPT_DIR/executed_tcpreplay_command.txt"
printf '%s\n' "tcpdump -i eth0 -nn -s 65535 -U -c 1 -w $RECEIVED 'udp and dst host 10.36.0.20 and dst port 36100'" > "$ATTEMPT_DIR/executed_tcpdump_command.txt"

ip netns exec "$RX_NS" tcpdump \
  -i eth0 -nn -s 65535 -U -c 1 \
  -w "$RECEIVED" \
  'udp and dst host 10.36.0.20 and dst port 36100' \
  > "$ATTEMPT_DIR/tcpdump_stdout.txt" \
  2> "$ATTEMPT_DIR/tcpdump_stderr.txt" &
TCPDUMP_PID=$!

sleep 0.5
kill -0 "$TCPDUMP_PID" 2>/dev/null || fail "tcpdump exited before tcpreplay"

set +e
ip netns exec "$TX_NS" tcpreplay \
  --intf1=eth0 \
  --loop=1 \
  --multiplier=1.0 \
  "$PREPARED" \
  > "$ATTEMPT_DIR/tcpreplay_stdout.txt" \
  2> "$ATTEMPT_DIR/tcpreplay_stderr.txt"
TCPREPLAY_RC=$?
set -e
printf '%s\n' "$TCPREPLAY_RC" > "$ATTEMPT_DIR/tcpreplay_exit_code.txt"
[[ "$TCPREPLAY_RC" == "0" ]] || fail "tcpreplay exited with code $TCPREPLAY_RC"

for _ in $(seq 1 50); do
  if ! kill -0 "$TCPDUMP_PID" 2>/dev/null; then
    break
  fi
  sleep 0.1
done

if kill -0 "$TCPDUMP_PID" 2>/dev/null; then
  kill "$TCPDUMP_PID" 2>/dev/null || true
  wait "$TCPDUMP_PID" 2>/dev/null || true
  TCPDUMP_PID=""
  fail "tcpdump did not receive expected packet within timeout"
fi

set +e
wait "$TCPDUMP_PID"
TCPDUMP_RC=$?
set -e
TCPDUMP_PID=""
printf '%s\n' "$TCPDUMP_RC" > "$ATTEMPT_DIR/tcpdump_exit_code.txt"
[[ "$TCPDUMP_RC" == "0" ]] || fail "tcpdump exited with code $TCPDUMP_RC"

[[ -s "$RECEIVED" ]] || fail "received.pcap missing or empty"

cleanup
trap - EXIT INT TERM
TX_CREATED=0
RX_CREATED=0

if ip netns list | awk '{print $1}' | grep -Fxq "$TX_NS"; then
  fail "TX namespace cleanup failed"
fi
if ip netns list | awk '{print $1}' | grep -Fxq "$RX_NS"; then
  fail "RX namespace cleanup failed"
fi

echo "cleanup_complete=true" > "$ATTEMPT_DIR/cleanup_status.txt"
echo "tx_namespace=$TX_NS" >> "$ATTEMPT_DIR/environment.txt"
echo "rx_namespace=$RX_NS" >> "$ATTEMPT_DIR/environment.txt"
echo "ROUND3_NETWORK_EXECUTION_OK"
