#!/usr/bin/env bash
# 仅用于 L-008 的临时双 netns/veth Scapy ETHGEN 软件验证。
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ATTEMPT="${L008_ATTEMPT:?set L008_ATTEMPT to a new evidence directory name}"
OUTPUT="$ROOT/artifacts/linux_target/$ATTEMPT"
PYTHON="$ROOT/runtime/python3.12/bin/python3.12"
SRC_NS="hil-l008-src-$$"
RX_NS="hil-l008-rx-$$"
SRC_VETH="l8s$$"
RX_VETH="l8r$$"
SRC_PID=""
RX_PID=""
REQUEST_PID=""
FEEDBACK_PID=""
SRC_CREATED=0
RX_CREATED=0

fail() { echo "L008_ERROR: $*" >&2; exit 1; }
cleanup() {
  local status=$?
  set +e
  for pid in "$SRC_PID" "$RX_PID" "$REQUEST_PID" "$FEEDBACK_PID"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null
  done
  [[ "$SRC_CREATED" == 1 ]] && ip netns del "$SRC_NS" 2>/dev/null
  [[ "$RX_CREATED" == 1 ]] && ip netns del "$RX_NS" 2>/dev/null
  if [[ -d "$OUTPUT" ]]; then
    if ! ip netns list | awk '{print $1}' | grep -Eq "^(${SRC_NS}|${RX_NS})$"; then
      printf '{"cleanup_complete":true,"exit_code":%s}\n' "$status" > "$OUTPUT/cleanup.json"
    fi
    [[ -n "${SUDO_USER:-}" ]] && chown -R "$SUDO_USER":"$(id -gn "$SUDO_USER")" "$OUTPUT"
  fi
}
trap cleanup EXIT INT TERM

[[ "$(id -u)" == 0 ]] || fail "root is required"
[[ -x "$PYTHON" ]] || fail "isolated Python runtime missing"
for command in ip tcpdump; do command -v "$command" >/dev/null || fail "missing $command"; done
[[ ! -e "$OUTPUT" ]] || fail "refusing to overwrite evidence directory"
mkdir -m 700 "$OUTPUT"

ip netns add "$SRC_NS"; SRC_CREATED=1
ip netns add "$RX_NS"; RX_CREATED=1
ip link add "$SRC_VETH" type veth peer name "$RX_VETH"
ip link set "$SRC_VETH" netns "$SRC_NS"
ip link set "$RX_VETH" netns "$RX_NS"
for ns in "$SRC_NS" "$RX_NS"; do ip netns exec "$ns" ip link set lo up; done
ip netns exec "$SRC_NS" ip link set "$SRC_VETH" name eth0
ip netns exec "$RX_NS" ip link set "$RX_VETH" name eth0
ip netns exec "$SRC_NS" ip link set eth0 address 02:00:00:00:00:01
ip netns exec "$RX_NS" ip link set eth0 address 02:00:00:00:00:02
ip netns exec "$SRC_NS" ip addr add 10.36.0.10/24 dev eth0
ip netns exec "$RX_NS" ip addr add 10.36.0.20/24 dev eth0
ip netns exec "$SRC_NS" ip link set eth0 up
ip netns exec "$RX_NS" ip link set eth0 up
ip netns exec "$SRC_NS" ip route show > "$OUTPUT/source_route.txt"
ip netns exec "$RX_NS" ip route show > "$OUTPUT/receiver_route.txt"
! ip netns exec "$SRC_NS" ip route show default | grep -q . || fail "source has a default route"
! ip netns exec "$RX_NS" ip route show default | grep -q . || fail "receiver has a default route"

ip netns exec "$RX_NS" env PYTHONPATH="$ROOT" "$PYTHON" "$ROOT/scripts/verify_l008_scapy_veth.py" receiver \
  --output "$OUTPUT/receiver.jsonl" > "$OUTPUT/receiver.stdout" 2> "$OUTPUT/receiver.stderr" & RX_PID=$!
ip netns exec "$RX_NS" tcpdump -i eth0 -nn -s 65535 -U -c 4 -w "$OUTPUT/requests.pcap" \
  'udp and src host 10.36.0.10 and dst host 10.36.0.20 and dst port 36100' > "$OUTPUT/request_tcpdump.stdout" 2> "$OUTPUT/request_tcpdump.stderr" & REQUEST_PID=$!
ip netns exec "$SRC_NS" tcpdump -i eth0 -nn -s 65535 -U -c 7 -w "$OUTPUT/feedback.pcap" \
  'udp and src host 10.36.0.20 and dst host 10.36.0.10 and dst port 36101' > "$OUTPUT/feedback_tcpdump.stdout" 2> "$OUTPUT/feedback_tcpdump.stderr" & FEEDBACK_PID=$!
sleep 0.5
kill -0 "$RX_PID" 2>/dev/null || fail "receiver exited before source start"
kill -0 "$REQUEST_PID" 2>/dev/null || fail "request capture exited before source start"
kill -0 "$FEEDBACK_PID" 2>/dev/null || fail "feedback capture exited before source start"

ip netns exec "$SRC_NS" env PYTHONPATH="$ROOT" "$PYTHON" "$ROOT/scripts/verify_l008_scapy_veth.py" source \
  --output "$OUTPUT/source.jsonl" > "$OUTPUT/source.stdout" 2> "$OUTPUT/source.stderr" & SRC_PID=$!
wait "$SRC_PID"; SRC_PID=""
wait "$RX_PID"; RX_PID=""
wait "$REQUEST_PID"; REQUEST_PID=""
wait "$FEEDBACK_PID"; FEEDBACK_PID=""
[[ -s "$OUTPUT/requests.pcap" && -s "$OUTPUT/feedback.pcap" ]] || fail "missing packet capture"
printf '{"status":"L008_SCAPY_VETH_TX_RX_COMPLETED","physical_tool_qualification":"NOT_EVALUATED"}\n' > "$OUTPUT/summary.json"
echo "L008_SCAPY_VETH_TX_RX_COMPLETED"
