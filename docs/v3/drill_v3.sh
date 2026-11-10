#!/usr/bin/env bash
# V3 端到端合成演练（V3-01 / V3-02）
#
# 用途：在独立的 MRF_RUNS_ROOT 上用合成数据跑完整链路，最后一步是 export。
# 不触碰 runs/ 与正式账本；不消费任何正式 Holdout。
#
# 用法：
#   export LLM_*（或 load the local gateway configuration）；docker 已启动
#   bash docs/v3/drill_v3.sh [RUNS_ROOT]
#
# 每一步都记录命令、退出码和输出；任何一步非 0 立即停止并保留现场。
set -uo pipefail
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
export PYTHONDONTWRITEBYTECODE=1
PY=".venv/bin/python"
MRF_RUNS_ROOT=$("$PY" - "$REPO_ROOT" "${1:-dev_runs}" <<'PYTHON'
import sys
from pathlib import Path

repository = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
if root.parent != repository or not (root.name == "dev_runs" or root.name.startswith("dev_runs-")):
    sys.exit("Choose an isolated dev_runs or dev_runs-* directory directly under the repository.")
print(root)
PYTHON
) || exit 2
export MRF_RUNS_ROOT
if ! { exec 3<> /dev/tty; } 2>/dev/null; then
  echo "This drill requires an interactive terminal for Gate A/B/C." >&2
  exit 2
fi

LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/mrf-v3-drill.XXXXXX") || exit 2
LOG="$LOG_DIR/drill.log"
printf 'Local drill log: %s\n' "$LOG" >&2

step() {
  local name="$1"; shift
  echo "=== STEP ${name} :: $*" >> "$LOG"
  "$@" >> "$LOG" 2>&1
  local rc=$?
  echo "--- EXIT ${name} = ${rc}" >> "$LOG"
  if [ "$rc" -ne 0 ]; then
    echo "STOPPED at ${name} rc=${rc} (run root ${MRF_RUNS_ROOT})" >> "$LOG"
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
  printf 'Reviewer name (agent-delegated only with explicit delegation): ' >&3
  IFS= read -r reviewer <&3 || exit 2
  printf 'Decision (APPROVED or REJECTED): ' >&3
  IFS= read -r decision <&3 || exit 2
  printf 'Checks actually performed and delegation source if applicable: ' >&3
  IFS= read -r comment <&3 || exit 2
  if [[ -z "${reviewer//[[:space:]]/}" || -z "${comment//[[:space:]]/}" || ! "$decision" =~ ^(APPROVED|REJECTED)$ ]]; then
    echo "No review recorded. Resume using the run ID in $LOG." >&2
    exit 2
  fi
  step "review-$gate" "$PY" -m src.cli approve --run-id "$RUN_ID" --gate "$gate" \
    --sha256 "$hash" --reviewer "$reviewer" --decision "$decision" --comment "$comment" "$@"
  if [ "$decision" = REJECTED ]; then
    echo "Review rejected. Stopped at $gate for $RUN_ID." >&2
    exit 1
  fi
}

echo "run_root=${MRF_RUNS_ROOT}" >> "$LOG"
echo "git_head=$(git rev-parse HEAD)" >> "$LOG"
echo "git_status=$(git status --porcelain | wc -l | tr -d ' ') changed paths" >> "$LOG"

RUN_ID=$("$PY" -m src.cli init-run --mode synthetic | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["run_id"])') || {
  echo "STOPPED at init-run" >> "$LOG"; exit 1; }
echo "=== RUN_ID ${RUN_ID}" >> "$LOG"
printf 'Run ID: %s\n' "$RUN_ID" >&2

SEED=$("$PY" -c 'import json; from pathlib import Path; print(json.loads(Path("config/data_config.json").read_text())["seed"])')
echo "seed=${SEED}" >> "$LOG"

# 0. 网关能力检查（V1-01）；失败时按 README 在同一 run 内立即重试一次再继续
try_step check-provider "$PY" -m src.cli check-provider --run-id "$RUN_ID" || {
  echo "=== RETRY check-provider in the same run (README: retry before continuing)" >> "$LOG"
  step check-provider-retry "$PY" -m src.cli check-provider --run-id "$RUN_ID"
}

# 1. 数据准备（合成）
step prepare "$PY" -m src.cli prepare --run-id "$RUN_ID" --synthetic --seed "$SEED"

# 2. R 基准、参考 parity、行为 fixtures、故意错误检测、容器检查
step baseline "$PY" -m src.cli baseline --run-id "$RUN_ID"
step reference-parity "$PY" -m src.cli reference-parity --run-id "$RUN_ID"
step fixture-parity "$PY" -m src.cli fixture-parity --run-id "$RUN_ID"
step mutation-check "$PY" -m src.cli mutation-check --run-id "$RUN_ID"
step docker-boundary "$PY" -m src.cli docker-boundary --run-id "$RUN_ID"

# 3. 三份档案与 Gate A（逐份审阅）
inventory_artifact() {
  if [ "$1" = "MDL_CREDIT_V1" ]; then echo "model_inventory.json"; else echo "inventories/$1.json"; fi
}
for MODEL in MDL_CREDIT_V1 MDL_CREDIT_V2 MDL_CREDIT_TREE; do
  step "extract-inventory-${MODEL}" "$PY" -m src.cli extract-inventory --run-id "$RUN_ID" --model "$MODEL"
  ARTIFACT="$MRF_RUNS_ROOT/$RUN_ID/$(inventory_artifact "$MODEL")"
  review Gate_A "$ARTIFACT" --model "$MODEL"
done

# 4. 真实候选、Gate B、开发验证
step generate-candidate "$PY" -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 0
review Gate_B "$MRF_RUNS_ROOT/$RUN_ID/candidates/attempt_000/credit_v1.py" --attempt 0
step run-dev "$PY" -m src.cli run-dev --run-id "$RUN_ID" --attempt 0
step candidate-fixtures "$PY" -m src.cli candidate-fixtures --run-id "$RUN_ID" --attempt 0

# 5. 冻结、一次性 Holdout（合成）、四类指标、Agent 摘要、报告与 Gate C
step freeze "$PY" -m src.cli freeze --run-id "$RUN_ID" --attempt 0
step accept "$PY" -m src.cli accept --run-id "$RUN_ID"
step validation-metrics "$PY" -m src.cli validation-metrics --run-id "$RUN_ID"
step agent-summary "$PY" -m src.cli agent-summary --run-id "$RUN_ID"
step report "$PY" -m src.cli report --run-id "$RUN_ID"
review Gate_C "$MRF_RUNS_ROOT/$RUN_ID/report/review_manifest.json"
step approve-report "$PY" -m src.cli approve-report --run-id "$RUN_ID"
step report-status "$PY" -m src.cli report-status --run-id "$RUN_ID"

# 6. 故障演练与导出（export 是最后一次写入该 run）
step failure-drills "$PY" -m src.cli failure-drills --run-id "$RUN_ID"
step export "$PY" -m src.cli export --run-id "$RUN_ID"
printf 'Read the exported acceptance at %s/delivery/%s_acceptance.json\n' "$REPO_ROOT" "$RUN_ID" >&2

echo "DONE run_id=${RUN_ID}" >> "$LOG"
echo "$RUN_ID"
