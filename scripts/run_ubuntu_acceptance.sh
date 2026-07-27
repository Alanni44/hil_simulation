#!/usr/bin/env bash
# One-command functional acceptance for the fixed Ubuntu HIL target.
# It intentionally skips the long real-time gate.  That gate is a separate
# future procedure and must not be claimed by this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_ROOT="${REPO_ROOT}/artifacts/acceptance"
UNIT_LOG="${LOG_ROOT}/ubuntu-functional-unit-tests.log"
INTEGRATION_LOG="${LOG_ROOT}/ubuntu-functional-integration.log"

fail() {
    echo "[验收失败] $*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "缺少命令：$1"
}

require_target_environment() {
    [[ -r /etc/os-release ]] || fail "无法读取 /etc/os-release；本脚本仅支持 Ubuntu 18.04 RT"
    # shellcheck disable=SC1091
    . /etc/os-release
    [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "18.04" ]] || \
        fail "当前不是 Ubuntu 18.04：${PRETTY_NAME:-unknown}"
    uname -a | grep -qi 'rt' || fail "当前内核不是 RT 内核：$(uname -a)"
    require_command gcc
    gcc --version | head -n 1 | grep -Eq '(^gcc .* 7\.|gcc \(.* 7\.)' || \
        fail "GCC 必须为 7.x：$(gcc --version | head -n 1)"
    require_command python3
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:3] == (3, 6, 9) else 1)' || \
        fail "Python 必须为 3.6.9：$(python3 --version)"
    [[ -x /usr/local/MATLAB/R2018b/bin/matlab || -x /usr/local/bin/matlab ]] || \
        fail "未找到可执行的 MATLAB R2018b"
}

main() {
    [[ $# -eq 0 ]] || fail "本脚本不接受参数；实时测试按项目计划另行执行"
    cd "${REPO_ROOT}"
    require_command git
    [[ -z "$(git status --porcelain)" ]] || \
        fail "工作区不干净；请在干净的 Git 检出目录运行本脚本"
    mkdir -p "${LOG_ROOT}"

    echo "[1/4] 检查 Ubuntu 18.04 RT、MATLAB R2018b、GCC 7.x、Python 3.6.9"
    require_target_environment
    echo "[2/4] 运行模型合同、UE4 V2.0 和静态测试"
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
        tests.test_model_registry \
        tests.test_v2_protocol \
        tests.test_static_contract 2>&1 | tee "${UNIT_LOG}"

    echo "[3/4] 运行 MATLAB ERT/GCC、运行时和本地 UE4 协议集成验收（跳过实时门槛）"
    HIL_DEPLOY_MODE=development HIL_SKIP_REALTIME_GATE=1 \
        python3 scripts/accept_runtime_contract.py 2>&1 | tee "${INTEGRATION_LOG}"

    echo "[4/4] 汇总证据"
    latest_evidence="$(find "${LOG_ROOT}" -mindepth 1 -maxdepth 1 -type d -name '*-runtime-contract' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
    [[ -n "${latest_evidence}" && -f "${latest_evidence}/result.json" ]] || \
        fail "未找到验收证据 result.json"
    status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "${latest_evidence}/result.json")"
    [[ "${status}" == "passed" ]] || fail "集成验收结果不是 passed：${latest_evidence}/result.json"

    echo "[验收通过] 功能验收完成；实时门槛按当前约定未执行"
    echo "证据目录：${latest_evidence}"
    echo "单元测试日志：${UNIT_LOG}"
    echo "集成验收日志：${INTEGRATION_LOG}"
}

main "$@"
