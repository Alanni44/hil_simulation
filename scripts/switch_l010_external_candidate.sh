#!/usr/bin/env bash
# 临时部署 L-010 候选供外部 3.3/3.6 联调；必须显式执行 restore 才会回退。
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "请以 root 运行：sudo /bin/bash $0 activate <候选 quadrotor_hil_rt>，或 sudo /bin/bash $0 restore <会话目录>" >&2
    exit 2
fi
if [[ $# -ne 2 ]]; then
    echo "用法：$0 activate <候选 quadrotor_hil_rt> | restore <会话目录>" >&2
    exit 2
fi

ACTION=$1
ARGUMENT=$2
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET=/opt/hil/runtime/verified/current_rt
WORK_ROOT=/opt/hil/runtime/work
DEPLOY=/opt/hil/bin/hil-deploy

[[ -x "$TARGET" && -x "$DEPLOY" ]] || {
    echo "目标核心或部署器不可用" >&2
    exit 2
}

deploy_file() {
    local executable=$1 digest=$2
    printf '{"executable_path":"%s","executable_sha256":"%s"}\n' "$executable" "$digest" \
        > /opt/hil/runtime/pending/current.json
    "$DEPLOY" current
    systemctl is-active --quiet hil-core@current.service
}

verify_capabilities() {
    local executable_kind=$1
    python3 - "$executable_kind" <<'PY'
import json
import socket
import sys

kind = sys.argv[1]
expected_output = kind == "candidate"
expected_step = kind == "candidate"
requests = (
    {"request_id": "l010-external-switch-status", "cmd": "get_hil_status"},
    {"request_id": "l010-external-switch-step", "cmd": "get_lifecycle_step_result", "params": {}},
)
replies = {}
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(2.0)
    for request in requests:
        sock.sendto(json.dumps(request, separators=(",", ":")).encode("utf-8"), ("127.0.0.1", 9997))
        raw, _ = sock.recvfrom(65535)
        replies[request["cmd"]] = json.loads(raw.decode("utf-8"))
fields = replies["get_hil_status"].get("fields")
has_output = isinstance(fields, dict) and "actuator_output" in fields and "actuator_output_sequence" in fields
step_supported = replies["get_lifecycle_step_result"].get("reason") != "unsupported command for this contract"
if has_output != expected_output or step_supported != expected_step:
    raise SystemExit("已启动核心的 L-010 能力与预期不一致")
PY
}

write_state() {
    local state_file=$1 session_id=$2 original=$3 original_sha=$4 candidate=$5 candidate_sha=$6 state=$7
    python3 - "$state_file" "$session_id" "$original" "$original_sha" "$candidate" "$candidate_sha" "$state" <<'PY'
import json
import sys

path, session_id, original, original_sha, candidate, candidate_sha, state = sys.argv[1:]
with open(path, "w", encoding="utf-8") as output:
    json.dump({
        "format": "HIL_L010_EXTERNAL_CANDIDATE_SESSION_1",
        "session_id": session_id,
        "state": state,
        "original_path": original,
        "original_sha256": original_sha,
        "candidate_path": candidate,
        "candidate_sha256": candidate_sha,
    }, output, ensure_ascii=False, indent=2)
    output.write("\n")
PY
}

activate() {
    local candidate
    candidate="$(realpath "$ARGUMENT")"
    case "$candidate" in
        "$REPO_DIR"/artifacts/linux_target/*/bin/quadrotor_hil_rt) ;;
        *) echo "候选必须位于仓库 artifacts/linux_target/*/bin/quadrotor_hil_rt：$candidate" >&2; exit 2 ;;
    esac
    [[ -f "$candidate" && -x "$candidate" ]] || { echo "候选不可执行：$candidate" >&2; exit 2; }

    local session_id="l010-external-session-$(date +%Y%m%dT%H%M%S)"
    local work_dir="$WORK_ROOT/$session_id"
    local evidence_dir="$REPO_DIR/artifacts/linux_target/$session_id"
    local original="$work_dir/original_rt"
    local candidate_copy="$work_dir/candidate_rt"
    local original_sha candidate_sha
    install -d -o root -g hil -m 0750 "$work_dir"
    mkdir -p "$evidence_dir"
    install -o root -g hil -m 0750 "$TARGET" "$original"
    install -o root -g hil -m 0750 "$candidate" "$candidate_copy"
    original_sha="$(sha256sum "$original" | awk '{print $1}')"
    candidate_sha="$(sha256sum "$candidate_copy" | awk '{print $1}')"
    write_state "$evidence_dir/session.json" "$session_id" "$original" "$original_sha" "$candidate_copy" "$candidate_sha" PREPARED

    if ! deploy_file "$candidate_copy" "$candidate_sha" || ! verify_capabilities candidate; then
        echo "候选启动或能力核验失败，正在恢复原始模型" >&2
        deploy_file "$original" "$original_sha"
        verify_capabilities original
        write_state "$evidence_dir/session.json" "$session_id" "$original" "$original_sha" "$candidate_copy" "$candidate_sha" RESTORED_AFTER_FAILED_ACTIVATION
        chown -R user:user "$evidence_dir"
        exit 1
    fi
    write_state "$evidence_dir/session.json" "$session_id" "$original" "$original_sha" "$candidate_copy" "$candidate_sha" ACTIVE
    chown -R user:user "$evidence_dir"
    echo "候选模型已激活：$session_id"
    echo "回退命令：sudo /bin/bash $0 restore $evidence_dir"
}

restore() {
    local evidence_dir state_file original original_sha candidate candidate_sha session_id state
    evidence_dir="$(realpath "$ARGUMENT")"
    case "$evidence_dir" in
        "$REPO_DIR"/artifacts/linux_target/l010-external-session-*) ;;
        *) echo "会话目录必须位于仓库 artifacts/linux_target/l010-external-session-*：$evidence_dir" >&2; exit 2 ;;
    esac
    state_file="$evidence_dir/session.json"
    [[ -f "$state_file" ]] || { echo "缺少会话状态文件：$state_file" >&2; exit 2; }
    mapfile -t state_values < <(python3 - "$state_file" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
if value.get("format") != "HIL_L010_EXTERNAL_CANDIDATE_SESSION_1":
    raise SystemExit("会话状态格式不受支持")
for key in ("session_id", "state", "original_path", "original_sha256", "candidate_path", "candidate_sha256"):
    item = value.get(key)
    if not isinstance(item, str) or "\n" in item:
        raise SystemExit("会话状态缺少 " + key)
    print(item)
PY
)
    session_id=${state_values[0]}
    state=${state_values[1]}
    original=${state_values[2]}
    original_sha=${state_values[3]}
    candidate=${state_values[4]}
    candidate_sha=${state_values[5]}
    case "$original" in "$WORK_ROOT"/l010-external-session-*/original_rt) ;; *) echo "原始模型路径非法" >&2; exit 2 ;; esac
    [[ -f "$original" ]] || { echo "原始模型备份不存在：$original" >&2; exit 2; }
    [[ "$(sha256sum "$original" | awk '{print $1}')" == "$original_sha" ]] || { echo "原始模型备份哈希不匹配" >&2; exit 2; }
    deploy_file "$original" "$original_sha"
    verify_capabilities original
    write_state "$state_file" "$session_id" "$original" "$original_sha" "$candidate" "$candidate_sha" RESTORED
    chown -R user:user "$evidence_dir"
    echo "已恢复原始模型：$session_id"
}

case "$ACTION" in
    activate) activate ;;
    restore) restore ;;
    *) echo "操作必须是 activate 或 restore" >&2; exit 2 ;;
esac
