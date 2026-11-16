#!/usr/bin/env bash
# 在同一受控部署通道中临时验证 L-010 候选，退出时必定恢复原核心。
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "请以 root 运行：sudo /bin/bash $0 <候选模型>" >&2
    exit 2
fi
if [[ $# -ne 1 ]]; then
    echo "用法：$0 <候选 quadrotor_hil_rt 可执行文件>" >&2
    exit 2
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
CANDIDATE="$(realpath "$1")"
case "$CANDIDATE" in
    "$REPO_DIR"/artifacts/linux_target/*/bin/quadrotor_hil_rt) ;;
    *) echo "候选必须位于仓库 artifacts/linux_target/*/bin/quadrotor_hil_rt：$CANDIDATE" >&2; exit 2 ;;
esac
[[ -f "$CANDIDATE" && -x "$CANDIDATE" ]] || { echo "候选不可执行：$CANDIDATE" >&2; exit 2; }

TARGET=/opt/hil/runtime/verified/current_rt
WORK_ROOT=/opt/hil/runtime/work
DEPLOY=/opt/hil/bin/hil-deploy
SMOKE=/opt/hil/bin/run-minimal-full-flow
[[ -x "$TARGET" && -x "$DEPLOY" && -x "$SMOKE" ]] || {
    echo "目标核心、部署器或两圈入口不可用" >&2
    exit 2
}

RUN_ID="l010-two-circle-temporary-$(date +%Y%m%dT%H%M%S)"
WORK_DIR="$WORK_ROOT/$RUN_ID"
EVIDENCE_DIR="$REPO_DIR/artifacts/linux_target/$RUN_ID"
ORIGINAL="$WORK_DIR/original_rt"
CANDIDATE_COPY="$WORK_DIR/candidate_rt"
REPORT="$EVIDENCE_DIR/result.json"
mkdir -p "$EVIDENCE_DIR"
install -d -o root -g hil -m 0750 "$WORK_DIR"
install -o root -g hil -m 0750 "$TARGET" "$ORIGINAL"
install -o root -g hil -m 0750 "$CANDIDATE" "$CANDIDATE_COPY"

ORIGINAL_SHA="$(sha256sum "$ORIGINAL" | awk '{print $1}')"
CANDIDATE_SHA="$(sha256sum "$CANDIDATE_COPY" | awk '{print $1}')"
RESTORED=0
SWITCHED=0

deploy_file() {
    local executable=$1 digest=$2
    printf '{"executable_path":"%s","executable_sha256":"%s"}\n' "$executable" "$digest" \
        > /opt/hil/runtime/pending/current.json
    "$DEPLOY" current
    systemctl is-active --quiet hil-core@current.service
}

query_core() {
    local output=$1 expected_output=$2 expected_step=$3
    python3 - "$output" "$expected_output" "$expected_step" <<'PY'
import json
import socket
import sys

output, expected_output, expected_step = sys.argv[1:]
requests = (
    {"request_id": "temporary-l010-status", "cmd": "get_hil_status"},
    {"request_id": "temporary-l010-step", "cmd": "get_lifecycle_step_result", "params": {}},
)
replies = {}
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2.0)
    for request in requests:
        sock.sendto(json.dumps(request, separators=(",", ":")).encode("utf-8"), ("127.0.0.1", 9997))
        raw, _ = sock.recvfrom(65535)
        replies[request["cmd"]] = json.loads(raw.decode("utf-8"))
fields = replies["get_hil_status"].get("fields")
if not replies["get_hil_status"].get("accepted") or not isinstance(fields, dict):
    raise SystemExit("C 核心状态查询失败")
has_output = "actuator_output" in fields and "actuator_output_sequence" in fields
step_reason = replies["get_lifecycle_step_result"].get("reason", "")
step_supported = step_reason != "unsupported command for this contract"
if has_output != (expected_output == "yes"):
    raise SystemExit("执行器读回能力与预期不一致")
if step_supported != (expected_step == "yes"):
    raise SystemExit("STEP 命令能力与预期不一致")
with open(output, "w", encoding="utf-8") as target:
    json.dump({"has_actuator_output": has_output, "step_supported": step_supported,
               "status": replies["get_hil_status"], "step_query": replies["get_lifecycle_step_result"]},
              target, ensure_ascii=False, indent=2)
    target.write("\n")
PY
}

restore_original() {
    [[ $RESTORED -eq 1 ]] && return
    set +e
    deploy_file "$ORIGINAL" "$ORIGINAL_SHA"
    deploy_code=$?
    if [[ $deploy_code -eq 0 ]]; then
        query_core "$EVIDENCE_DIR/after-restore.json" no no
        query_code=$?
    else
        query_code=1
    fi
    RESTORED=1
    set -e
    return $((deploy_code || query_code))
}

finish() {
    local code=$?
    trap - EXIT
    restore_code=0
    restore_original || restore_code=$?
    python3 - "$REPORT" "$RUN_ID" "$ORIGINAL_SHA" "$CANDIDATE_SHA" "$code" "$restore_code" <<'PY'
import json
import sys

path, run_id, original, candidate, test_code, restore_code = sys.argv[1:]
with open(path, "w", encoding="utf-8") as target:
    json.dump({"format": "HIL_L010_TEMPORARY_TWO_CIRCLE_1", "run_id": run_id,
               "original_sha256": original, "candidate_sha256": candidate,
               "two_circle_exit_code": int(test_code), "restore_exit_code": int(restore_code),
               "status": "PASSED" if test_code == "0" and restore_code == "0" else "FAILED"},
              target, ensure_ascii=False, indent=2)
    target.write("\n")
PY
    chown -R user:user "$EVIDENCE_DIR"
    exit $((code || restore_code))
}
trap finish EXIT

printf 'original_sha256=%s\ncandidate_sha256=%s\n' "$ORIGINAL_SHA" "$CANDIDATE_SHA" \
    > "$EVIDENCE_DIR/hashes.txt"

deploy_file "$CANDIDATE_COPY" "$CANDIDATE_SHA"
SWITCHED=1
query_core "$EVIDENCE_DIR/candidate-capabilities.json" yes yes

# 第一圈：恢复配置准备服务；第二圈：已有的 CREATE/START/ID10/STOP 有界入口。
systemctl restart hil-prepare.service
systemctl start hil-preparation.service hil-telemetry.service
systemctl is-active --quiet hil-prepare.service hil-preparation.service hil-telemetry.service
"$SMOKE" > "$EVIDENCE_DIR/two-circle.stdout" 2> "$EVIDENCE_DIR/two-circle.stderr"
query_core "$EVIDENCE_DIR/after-two-circle.json" yes yes
