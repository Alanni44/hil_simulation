#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${ROUND4_OUTPUT_DIR:-$ROOT/artifacts/history/round4}"
PYTHON="${ROUND4_PYTHON:-python3}"
DEPLOYMENT="$ROOT/config/input-simulator-round4-development.json"
EXPECTED_BASELINE_SHA256="22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
EXPECTED_REFERENCE_SHA256="c335601a095d9baf1c093bfd195f042b5e7899c31b03071f249f26488819efb3"
SRC_NS="uav-r4-src-$$"
GW_NS="uav-r4-gw-$$"
SRC_VETH="r4s$$"
GW_VETH="r4g$$"
SRC_CREATED=0
GW_CREATED=0
OUTPUT_CREATED=0
GW_PID=""
TXCAP_PID=""
RXCAP_PID=""
FAILURE=""
HOST_ROUTES_BEFORE=""

fail() {
  FAILURE="$*"
  echo "ROUND4_ERROR: $FAILURE" >&2
  exit 1
}

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  set +e
  for pid in "$TXCAP_PID" "$RXCAP_PID" "$GW_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    fi
  done
  [[ "$SRC_CREATED" == "1" ]] && ip netns del "$SRC_NS" 2>/dev/null
  [[ "$GW_CREATED" == "1" ]] && ip netns del "$GW_NS" 2>/dev/null
  local cleanup_ok=true host_unchanged=false namespaces=""
  if [[ "$SRC_CREATED" == "1" || "$GW_CREATED" == "1" ]]; then
    if namespaces="$(ip netns list)"; then
      if [[ "$SRC_CREATED" == "1" ]] && awk '{print $1}' <<< "$namespaces" | grep -Fxq "$SRC_NS"; then cleanup_ok=false; fi
      if [[ "$GW_CREATED" == "1" ]] && awk '{print $1}' <<< "$namespaces" | grep -Fxq "$GW_NS"; then cleanup_ok=false; fi
    else
      cleanup_ok=false
    fi
  fi
  if [[ "$OUTPUT_CREATED" == "1" && -n "$HOST_ROUTES_BEFORE" && -f "$OUTPUT_DIR/host_route_before.txt" ]]; then
    if ip route show table all > "$OUTPUT_DIR/host_route_after.txt" 2>/dev/null && \
      cmp -s "$OUTPUT_DIR/host_route_before.txt" "$OUTPUT_DIR/host_route_after.txt"; then host_unchanged=true; fi
  fi
  if [[ "$OUTPUT_CREATED" == "1" && -d "$OUTPUT_DIR" ]]; then
    printf '{"cleanup_complete":%s,"host_routes_changed":%s,"failure":"%s"}\n' \
      "$cleanup_ok" "$([[ "$host_unchanged" == "true" ]] && echo false || echo true)" \
      "${FAILURE//\"/\\\"}" > "$OUTPUT_DIR/cleanup_status.json"
  fi
  if [[ "$OUTPUT_CREATED" == "1" && "$cleanup_ok" == "true" && "$host_unchanged" == "true" && "$rc" == "0" ]]; then
    printf '{"cleanup_complete":true,"host_routes_changed":false,"failure":null}\n' > "$OUTPUT_DIR/cleanup_status.json"
    echo "ROUND4_CLEANUP_OK"
  else
    echo "ROUND4_CLEANUP_INCOMPLETE cleanup_complete=$cleanup_ok host_routes_unchanged=$host_unchanged exit=$rc" >&2
  fi
}
trap cleanup EXIT INT TERM

[[ "$(uname -s)" == "Linux" ]] || fail "Linux kernel required"
[[ "$(id -u)" == "0" ]] || fail "root required for isolated namespaces"
for cmd in ip tcpreplay tcpdump ethtool sha256sum cmp awk grep; do command -v "$cmd" >/dev/null || fail "missing tool: $cmd"; done
command -v "$PYTHON" >/dev/null || fail "Python executable not found: $PYTHON"
[[ -f "$DEPLOYMENT" ]] || fail "Round 4 deployment config missing"
[[ -f "$ROOT/artifacts/history/round1/reference.pcap" ]] || fail "Round 1 reference PCAP missing"
[[ ! -e "$OUTPUT_DIR" ]] || fail "refusing to overwrite existing Round 4 evidence: $OUTPUT_DIR"

# The isolated runtime is intentionally separate from the Windows interpreter.
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.prefix.endswith("/envs/uav-history-round4") else 1)' || \
  fail "run with the isolated WSL Conda environment uav-history-round4"
mkdir -m 700 "$OUTPUT_DIR"
OUTPUT_CREATED=1
HOST_ROUTES_BEFORE=ready
ip route show table all > "$OUTPUT_DIR/host_route_before.txt"
ACTUAL_REFERENCE_SHA256="$(sha256sum "$ROOT/artifacts/history/round1/reference.pcap" | awk '{print $1}')"
[[ "$ACTUAL_REFERENCE_SHA256" == "$EXPECTED_REFERENCE_SHA256" ]] || fail "Round 1 reference SHA256 mismatch"

PYTHONPATH="$ROOT" "$PYTHON" -c 'import scapy, icd_runtime, input_simulator' || fail "required Python dependencies unavailable"
"$PYTHON" "$SCRIPT_DIR/validate_history_round4_gateway.py" environment --output-dir "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/environment_stdout.txt" 2> "$OUTPUT_DIR/environment_stderr.txt" || fail "environment evidence capture failed"
cat /etc/os-release > "$OUTPUT_DIR/os-release.txt"
ip -Version > "$OUTPUT_DIR/ip_version.txt" 2>&1
tcpreplay --version > "$OUTPUT_DIR/tcpreplay_version.txt" 2>&1
tcpdump --version > "$OUTPUT_DIR/tcpdump_version.txt" 2>&1
ethtool --version > "$OUTPUT_DIR/ethtool_version.txt" 2>&1
printf '%s\n' "python=$PYTHON" "deployment=$DEPLOYMENT" "reference_pcap_sha256=$ACTUAL_REFERENCE_SHA256" \
  > "$OUTPUT_DIR/environment.txt"

ip netns list | awk '{print $1}' | grep -Fxq "$SRC_NS" && fail "source namespace collision"
ip netns list | awk '{print $1}' | grep -Fxq "$GW_NS" && fail "gateway namespace collision"
ip netns add "$SRC_NS"
SRC_CREATED=1
ip netns add "$GW_NS"
GW_CREATED=1
ip link add "$SRC_VETH" type veth peer name "$GW_VETH"
ip link set "$SRC_VETH" netns "$SRC_NS"
ip link set "$GW_VETH" netns "$GW_NS"
ip netns exec "$SRC_NS" ip link set lo up
ip netns exec "$GW_NS" ip link set lo up
ip netns exec "$SRC_NS" ip link set "$SRC_VETH" name eth0
ip netns exec "$GW_NS" ip link set "$GW_VETH" name eth0
ip netns exec "$SRC_NS" ip link set dev eth0 address 02:00:00:00:00:01
ip netns exec "$GW_NS" ip link set dev eth0 address 02:00:00:00:00:02
ip netns exec "$SRC_NS" ip addr add 10.36.0.10/24 dev eth0
ip netns exec "$GW_NS" ip addr add 10.36.0.20/24 dev eth0
ip netns exec "$SRC_NS" ip link set eth0 up
ip netns exec "$GW_NS" ip link set eth0 up
# Disable TX checksum offload only on the temporary veth devices so tcpdump
# captures complete checksums rather than pre-offload partial checksums.
ip netns exec "$SRC_NS" ethtool -K eth0 tx off
ip netns exec "$GW_NS" ethtool -K eth0 tx off
ip netns exec "$SRC_NS" ethtool -k eth0 > "$OUTPUT_DIR/source_ethtool_features.txt"
ip netns exec "$GW_NS" ethtool -k eth0 > "$OUTPUT_DIR/gateway_ethtool_features.txt"
ip netns exec "$SRC_NS" ip addr show > "$OUTPUT_DIR/source_addr.txt"
ip netns exec "$GW_NS" ip addr show > "$OUTPUT_DIR/gateway_addr.txt"
ip netns exec "$SRC_NS" ip route show > "$OUTPUT_DIR/source_route.txt"
ip netns exec "$GW_NS" ip route show > "$OUTPUT_DIR/gateway_route.txt"
if ip netns exec "$SRC_NS" ip route show default | grep -q .; then fail "source namespace has a default route"; fi
if ip netns exec "$GW_NS" ip route show default | grep -q .; then fail "gateway namespace has a default route"; fi

ip netns exec "$GW_NS" env PYTHONPATH="$ROOT" "$PYTHON" -m icd_gateway \
  --contract-dir "$ROOT/docs/interfaces/baseline" --expected-sha256 "$EXPECTED_BASELINE_SHA256" \
  --deployment "$DEPLOYMENT" \
  > "$OUTPUT_DIR/gateway_stdout.txt" 2> "$OUTPUT_DIR/gateway_stderr.txt" &
GW_PID=$!

for _ in $(seq 1 100); do
  if grep -q '"status": "DEVELOPMENT_READY"' "$OUTPUT_DIR/gateway_stdout.txt" 2>/dev/null; then break; fi
  kill -0 "$GW_PID" 2>/dev/null || fail "Gateway exited before DEVELOPMENT_READY"
  sleep 0.05
done
grep -q '"status": "DEVELOPMENT_READY"' "$OUTPUT_DIR/gateway_stdout.txt" 2>/dev/null || fail "Gateway DEVELOPMENT_READY timeout"

printf '%s\n' "tcpdump -i eth0 -nn -s 65535 -U -c 2 -w request_tx.pcap 'udp and src host 10.36.0.10 and dst host 10.36.0.20 and dst port 36100'" \
  > "$OUTPUT_DIR/request_capture_command.txt"
printf '%s\n' "tcpdump -i eth0 -nn -s 65535 -U -c 3 -w gateway_feedback.pcap 'udp and src host 10.36.0.20 and dst host 10.36.0.10 and dst port 36101'" \
  > "$OUTPUT_DIR/feedback_capture_command.txt"
ip netns exec "$GW_NS" tcpdump -i eth0 -nn -s 65535 -U -c 2 \
  -w "$OUTPUT_DIR/request_tx.pcap" \
  'udp and src host 10.36.0.10 and dst host 10.36.0.20 and dst port 36100' \
  > "$OUTPUT_DIR/request_tcpdump_stdout.txt" 2> "$OUTPUT_DIR/request_tcpdump_stderr.txt" &
TXCAP_PID=$!
ip netns exec "$GW_NS" tcpdump -i eth0 -nn -s 65535 -U -c 3 \
  -w "$OUTPUT_DIR/gateway_feedback.pcap" \
  'udp and src host 10.36.0.20 and dst host 10.36.0.10 and dst port 36101' \
  > "$OUTPUT_DIR/feedback_tcpdump_stdout.txt" 2> "$OUTPUT_DIR/feedback_tcpdump_stderr.txt" &
RXCAP_PID=$!
sleep 0.5
kill -0 "$TXCAP_PID" 2>/dev/null || fail "request tcpdump exited before SessionOpen"
kill -0 "$RXCAP_PID" 2>/dev/null || fail "feedback tcpdump exited before SessionOpen"

ip netns exec "$SRC_NS" env PYTHONPATH="$ROOT" "$PYTHON" \
  "$SCRIPT_DIR/validate_history_round4_gateway.py" source --output-dir "$OUTPUT_DIR" --gateway-pid "$GW_PID" \
  > "$OUTPUT_DIR/source_stdout.txt" 2> "$OUTPUT_DIR/source_stderr.txt" || fail "source SessionOpen/probe failed"

for _ in $(seq 1 120); do
  TX_DONE=0; RX_DONE=0
  kill -0 "$TXCAP_PID" 2>/dev/null || TX_DONE=1
  kill -0 "$RXCAP_PID" 2>/dev/null || RX_DONE=1
  [[ "$TX_DONE" == "1" && "$RX_DONE" == "1" ]] && break
  sleep 0.1
done
if kill -0 "$TXCAP_PID" 2>/dev/null; then kill "$TXCAP_PID" 2>/dev/null || true; fi
if kill -0 "$RXCAP_PID" 2>/dev/null; then kill "$RXCAP_PID" 2>/dev/null || true; fi
set +e
wait "$TXCAP_PID"; TXCAP_RC=$?; TXCAP_PID=""
wait "$RXCAP_PID"; RXCAP_RC=$?; RXCAP_PID=""
set -e
printf '%s\n' "$TXCAP_RC" > "$OUTPUT_DIR/request_tcpdump_exit_code.txt"
printf '%s\n' "$RXCAP_RC" > "$OUTPUT_DIR/feedback_tcpdump_exit_code.txt"
[[ "$TXCAP_RC" == "0" ]] || fail "request tcpdump failed or timed out"
[[ "$RXCAP_RC" == "0" ]] || fail "feedback tcpdump failed or timed out"
[[ -s "$OUTPUT_DIR/request_tx.pcap" ]] || fail "request capture empty"
[[ -s "$OUTPUT_DIR/gateway_feedback.pcap" ]] || fail "feedback capture empty"

kill "$GW_PID" 2>/dev/null || true
wait "$GW_PID" 2>/dev/null || true
GW_PID=""
[[ ! -e "$OUTPUT_DIR/gateway_stderr.txt" ]] || true

# Cleanup occurs before validation; keep the failure trap until validation succeeds.
if [[ "$SRC_CREATED" == "1" ]]; then
  ip netns del "$SRC_NS" || fail "source namespace cleanup failed"
fi
if [[ "$GW_CREATED" == "1" ]]; then
  ip netns del "$GW_NS" || fail "gateway namespace cleanup failed"
fi
NAMESPACES_AFTER="$(ip netns list)" || fail "cannot verify namespace cleanup"
if awk '{print $1}' <<< "$NAMESPACES_AFTER" | grep -Fxq "$SRC_NS"; then fail "source namespace remains after cleanup"; fi
if awk '{print $1}' <<< "$NAMESPACES_AFTER" | grep -Fxq "$GW_NS"; then fail "gateway namespace remains after cleanup"; fi
SRC_CREATED=0
GW_CREATED=0
ip route show table all > "$OUTPUT_DIR/host_route_after.txt" || fail "cannot verify host routes"
cmp -s "$OUTPUT_DIR/host_route_before.txt" "$OUTPUT_DIR/host_route_after.txt" || fail "host route table changed"
printf '{"cleanup_complete":true,"host_routes_changed":false,"failure":null}\n' > "$OUTPUT_DIR/cleanup_status.json"

"$PYTHON" "$SCRIPT_DIR/validate_history_round4_gateway.py" validate --output-dir "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/validation_stdout.txt" 2> "$OUTPUT_DIR/validation_stderr.txt" || fail "persisted Round 4 evidence validation failed"
trap - EXIT INT TERM
echo "ROUND4_LIVE_SESSION_GATEWAY_ADMISSION_VALIDATED"
