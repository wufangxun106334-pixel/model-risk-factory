#!/usr/bin/env bash
# V3 正式 UCI run（seed 47，唯一一次）
#
# 只有在 docs/v3/11_formal_run_decisions.md 的 H-01～H-04 全部签署之后才可执行。
# 本脚本按 README 的正式顺序串起全部命令，并在不可逆的 accept 之前要求再次确认。
# 它不会打标签、不会推送；最后只打印 release-check 结果和打标签命令供团队决定。
#
# 用法（干净工作区，HEAD 即冻结提交；docker 已启动）：
#   export LLM_BASE_URL=... LLM_CHAT_COMPLETIONS_URL=... LLM_PROTOCOL=openai_chat_completions \
#          LLM_MODEL=deepseek-v4.1-flash:1017 LLM_TIMEOUT_SECONDS=300 LLM_MAX_OUTPUT_TOKENS=32768
#   read -rs LLM_API_KEY; export LLM_API_KEY
#   bash docs/v3/formal_run.sh
#
# 拒绝条件：设置了指向 runs/ 以外的 MRF_RUNS_ROOT；没有交互终端；formal-preflight 未全部通过。
set -uo pipefail
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
export PYTHONDONTWRITEBYTECODE=1
PY=".venv/bin/python"
UCI_ZIP="data/raw/default_of_credit_card_clients.zip"
UCI_SHA256="56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602"
MAX_ATTEMPT=2

# 1. 根目录：正式 run 只能写 runs/（drill_v3.sh 的反向检查）
if [ -n "${MRF_RUNS_ROOT:-}" ]; then
  if [ "$(cd "$MRF_RUNS_ROOT" 2>/dev/null && pwd -P)" != "$(cd runs 2>/dev/null && pwd -P)" ]; then
    echo "Refusing: MRF_RUNS_ROOT points at ${MRF_RUNS_ROOT}; the formal run must use runs/. Unset it." >&2
    exit 2
  fi
fi
unset MRF_RUNS_ROOT

# 2. 审核必须由真人在终端上逐个 Gate 决定
if ! { exec 3<> /dev/tty; } 2>/dev/null; then
  echo "Refusing: the formal run requires an interactive terminal for Gate A/B/C." >&2
  exit 2
fi

# 3. 只读前置检查：工作区干净、HEAD 固定、seed 47、UCI 批准、ZIP 与账本、seed 未消费、网关与 Docker
FROZEN=$(git rev-parse HEAD) || exit 2
if ! "$PY" -m src.cli formal-preflight --expected-sha "$FROZEN" --raw-uci "$UCI_ZIP" >&3; then
  echo "Refusing: formal-preflight did not pass. Nothing was created." >&2
  exit 2
fi

LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/mrf-v3-formal.XXXXXX") || exit 2
LOG="$LOG_DIR/formal.log"
printf 'Local formal-run log: %s\n' "$LOG" >&2

step() {
  local name="$1"; shift
  echo "=== STEP ${name} :: $*" >> "$LOG"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  echo "--- EXIT ${name} = ${rc}" >> "$LOG"
  if [ "$rc" -ne 0 ]; then
    echo "STOPPED at ${name} rc=${rc} (run ${RUN_ID:-none})" | tee -a "$LOG" >&2
    exit "$rc"
  fi
}

try_step() {
  local name="$1"; shift
  echo "=== STEP ${name} :: $*" >> "$LOG"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  echo "--- EXIT ${name} = ${rc}" >> "$LOG"
  return "$rc"
}

digest() {  # digest <gate> <path>
  "$PY" - "$1" "$2" <<'PYTHON'
import sys
from pathlib import Path
from src.review import artifact_digest
print(artifact_digest(Path(sys.argv[2]), sys.argv[1]))
PYTHON
}

review() {
  local gate="$1" artifact="$2" hash reviewer comment decision
  shift 2
  hash=$(digest "$gate" "$artifact") || exit 2
  printf '\n%s — review this artifact before continuing:\n%s\nSHA-256 %s\n' "$gate" "$artifact" "$hash" >&3
  if [ "$gate" = Gate_B ]; then
    printf 'Review the complete candidate and its adjacent diff before recording a decision.\n' >&3
  fi
  printf 'Reviewer name (agent-delegated only with the delegation recorded in 11_formal_run_decisions.md): ' >&3
  IFS= read -r reviewer <&3 || exit 2
  printf 'Decision (APPROVED or REJECTED): ' >&3
  IFS= read -r decision <&3 || exit 2
  printf 'Checks actually performed and delegation source if applicable: ' >&3
  IFS= read -r comment <&3 || exit 2
  if [[ -z "${reviewer//[[:space:]]/}" || -z "${comment//[[:space:]]/}" || ! "$decision" =~ ^(APPROVED|REJECTED)$ ]]; then
    echo "No review recorded. Run ${RUN_ID} is kept; see $LOG." >&2
    exit 2
  fi
  step "review-$gate" "$PY" -m src.cli approve --run-id "$RUN_ID" --gate "$gate" \
    --sha256 "$hash" --reviewer "$reviewer" --decision "$decision" --comment "$comment" "$@"
  if [ "$decision" = REJECTED ]; then
    echo "Review rejected. Stopped at $gate for $RUN_ID." >&2
    exit 1
  fi
}

confirm_run_id() {  # confirm_run_id <message>
  local typed
  printf '\n%s\nType the run id (%s) to continue, anything else stops: ' "$1" "$RUN_ID" >&3
  IFS= read -r typed <&3 || exit 2
  if [ "$typed" != "$RUN_ID" ]; then
    echo "Not confirmed. Stopped before an irreversible step; run ${RUN_ID} is kept." | tee -a "$LOG" >&2
    exit 2
  fi
}

echo "frozen_sha=${FROZEN}" >> "$LOG"

RUN_ID=$("$PY" -m src.cli init-run --mode uci | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["run_id"])') || {
  echo "STOPPED at init-run" | tee -a "$LOG" >&2; exit 1; }
echo "=== RUN_ID ${RUN_ID}" >> "$LOG"
printf 'Run ID: %s\n' "$RUN_ID" >&2

# 0. 网关能力检查；只允许在下一步之前于同一 run 内重试一次
try_step check-provider "$PY" -m src.cli check-provider --run-id "$RUN_ID" || {
  echo "=== RETRY check-provider in the same run (allowed only before the next step)" >> "$LOG"
  step check-provider-retry "$PY" -m src.cli check-provider --run-id "$RUN_ID"
}

# 1. 已批准的 UCI 数据（seed 由 config/data_config.json 决定）
step download-uci "$PY" -m src.cli download-uci --run-id "$RUN_ID" \
  --expected-sha256 "$UCI_SHA256" --approve-uci-use
step prepare "$PY" -m src.cli prepare --run-id "$RUN_ID" --uci "$UCI_ZIP" \
  --expected-sha256 "$UCI_SHA256" --approve-uci-use

# 2. R 基准、参考 parity、行为 fixtures、故意错误检测、容器检查
step baseline "$PY" -m src.cli baseline --run-id "$RUN_ID"
step reference-parity "$PY" -m src.cli reference-parity --run-id "$RUN_ID"
step fixture-parity "$PY" -m src.cli fixture-parity --run-id "$RUN_ID"
step mutation-check "$PY" -m src.cli mutation-check --run-id "$RUN_ID"
step docker-boundary "$PY" -m src.cli docker-boundary --run-id "$RUN_ID"

# 3. 三份档案与 Gate A
inventory_artifact() {
  if [ "$1" = "MDL_CREDIT_V1" ]; then echo "model_inventory.json"; else echo "inventories/$1.json"; fi
}
for MODEL in MDL_CREDIT_V1 MDL_CREDIT_V2 MDL_CREDIT_TREE; do
  step "extract-inventory-${MODEL}" "$PY" -m src.cli extract-inventory --run-id "$RUN_ID" --model "$MODEL"
  review Gate_A "runs/$RUN_ID/$(inventory_artifact "$MODEL")" --model "$MODEL"
done

# 4. 候选、Gate B、开发验证；开发失败时最多修复两次，每个新候选重新 Gate B
ATTEMPT=0
while :; do
  step "generate-candidate-${ATTEMPT}" "$PY" -m src.cli generate-candidate --run-id "$RUN_ID" --attempt "$ATTEMPT"
  review Gate_B "runs/$RUN_ID/candidates/$(printf 'attempt_%03d' "$ATTEMPT")/credit_v1.py" --attempt "$ATTEMPT"
  if try_step "run-dev-${ATTEMPT}" "$PY" -m src.cli run-dev --run-id "$RUN_ID" --attempt "$ATTEMPT" \
     && try_step "candidate-fixtures-${ATTEMPT}" "$PY" -m src.cli candidate-fixtures --run-id "$RUN_ID" --attempt "$ATTEMPT"; then
    break
  fi
  if [ "$ATTEMPT" -ge "$MAX_ATTEMPT" ]; then
    echo "Development failed after ${MAX_ATTEMPT} repairs. Stopped before freeze; FAILED evidence kept in ${RUN_ID}." | tee -a "$LOG" >&2
    exit 1
  fi
  ATTEMPT=$((ATTEMPT + 1))
  echo "=== REPAIR attempt ${ATTEMPT}" >> "$LOG"
done

# 5. 冻结与唯一一次 Holdout 消费
step freeze "$PY" -m src.cli freeze --run-id "$RUN_ID" --attempt "$ATTEMPT"
confirm_run_id "accept consumes the seed 47 Holdout irreversibly (attempt ${ATTEMPT} frozen). There is no retry."
step accept "$PY" -m src.cli accept --run-id "$RUN_ID"

# 6. 指标、Agent 摘要、报告与 Gate C
step validation-metrics "$PY" -m src.cli validation-metrics --run-id "$RUN_ID"
step agent-summary "$PY" -m src.cli agent-summary --run-id "$RUN_ID"
step report "$PY" -m src.cli report --run-id "$RUN_ID"
review Gate_C "runs/$RUN_ID/report/review_manifest.json"
step approve-report "$PY" -m src.cli approve-report --run-id "$RUN_ID"
step report-status "$PY" -m src.cli report-status --run-id "$RUN_ID"

# 7. 故障演练与导出（export 是最后一次写入该 run）
step failure-drills "$PY" -m src.cli failure-drills --run-id "$RUN_ID"
step export "$PY" -m src.cli export --run-id "$RUN_ID"

# 8. 只读发布校验，输出写到 run/ 与 delivery/ 之外
RELEASE_OUT="${HOME}/release_check_v3_${RUN_ID}.json"
try_step release-check "$PY" -m src.cli release-check --run-id "$RUN_ID" --tag "$FROZEN" \
  --zip "$UCI_ZIP" --output "$RELEASE_OUT"
RELEASE_STATUS=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status"))' "$RELEASE_OUT" 2>/dev/null || echo UNKNOWN)

printf '\nrun_id=%s frozen=%s release-check=%s (%s)\n' "$RUN_ID" "$FROZEN" "$RELEASE_STATUS" "$RELEASE_OUT" >&2
printf 'Acceptance: %s/delivery/%s_acceptance.json\n' "$REPO_ROOT" "$RUN_ID" >&2
if [ "$RELEASE_STATUS" = APPROVED ]; then
  printf 'Only after H-03 authorises tagging, run:\n  git tag -a v3 -m "v3 final: %s on %s" %s\n' "$RUN_ID" "$FROZEN" "$FROZEN" >&2
else
  printf 'Do not tag: release-check is not APPROVED.\n' >&2
fi
echo "DONE run_id=${RUN_ID} release=${RELEASE_STATUS}" >> "$LOG"
echo "$RUN_ID"
