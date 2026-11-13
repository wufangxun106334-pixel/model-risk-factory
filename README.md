# Model Risk Factory

EXL × UCD Data & AI Hackathon 2026 — **Challenge 04: Agentic model risk factory**.

A bank's model-risk team needs to document a legacy model estate, migrate one model from R to Python, and validate the result. Model Risk Factory does this with an LLM Agent, but a human approves every step at a hash-bound gate. Deterministic code and fixed tests check everything the Agent produces.

> **Competition prototype.** It is not production-ready, not independently validated, and not a regulatory certification. The data is a public 2005 Taiwan credit-card sample, not a UK portfolio.

## Status

| Item | Result |
| --- | --- |
| Formal v3 run (seed 47, 1,199-row Holdout, used once) | 13 of 14 acceptance checks PASS. R → Python parity max \|Δp\| 2.22e-16 with 0 classification mismatches. Holdout ROC-AUC 0.699 |
| Failed check | V1-07 (command-chain check) failed because the checker itself had a defect. The defect is now fixed, but the fix only applies to future runs |
| Release | **BLOCKED.** No `v3` tag was created. The UCI data has no unused rows left for a second formal Holdout, so this run cannot be repeated |

In short, the v3 candidate is delivered and its final acceptance is BLOCKED.

## 1. What it does

1. **Inventory with gaps kept visible.** The Agent documents three team-built R models (`legacy/`) from their code and their deliberately out-of-date notes. Every fact cites a file path, line range, excerpt and SHA-256. Fields the sources never state, such as owner and training date, stay `Unknown`. The code threshold is 0.35 and the note says 0.50; this conflict is kept, not quietly resolved. **Gate A** approves the inventory hash.
2. **R → Python migration.** The Agent writes a Python candidate from the exported R coefficients, medians, feature order and the 0.35 threshold. Nothing is retrained. **Gate B** approves the exact source hash before the candidate runs. A trusted validator then compares it with R record by record, inside a container with no network access, read-only mounts and a 30-second limit.
3. **Validation.** Deterministic Python computes performance and calibration, PSI drift, and group error rates (TPR/FPR) with small-sample warnings. The Agent only explains the numbers. **Gate C** re-renders the report and checks every table cell against the metrics.
4. **Evidence.** The Holdout can be consumed only once. Export writes an acceptance record and a whitelisted evidence ZIP that contains no data rows, labels or baseline answers. `release-check` refuses evidence that does not belong to the released commit.

## 2. Deployment

### Requirements

| Need | Version used |
| --- | --- |
| Python | 3.15 (the tested version) |
| Docker | running daemon (tested on 29.9) |
| R | not needed on the host; it runs in `rocker/r-ver:4.4.2` |
| LLM gateway | needed only for the Agent steps (an OpenAI-compatible chat-completions endpoint) |

### Install

```bash
git clone https://github.com/wufangxun106334-pixel/model-risk-factory.git
cd model-risk-factory
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-ui.txt

docker pull rocker/r-ver:4.4.2
docker build -t model-risk-factory-runner:v1 docker

python -m pytest -q      # 8 UCI-dependent tests are skipped without the verified UCI ZIP
```

### Gateway configuration (Agent steps only)

Copy `.env.example` to `.env`, fill in the values and load it into the current shell:

```bash
cp .env.example .env     # LLM_BASE_URL, LLM_CHAT_COMPLETIONS_URL, LLM_PROTOCOL, LLM_MODEL,
                         # LLM_API_KEY, LLM_TIMEOUT_SECONDS, LLM_MAX_OUTPUT_TOKENS
set -a; source .env; set +a
```

The default model is set in `config/provider_config.json`. Keep `LLM_MAX_OUTPUT_TOKENS` at 32768: smaller values (such as 8192) cut the candidate off mid-output.

## 3. Demo

Demos run on **synthetic data** under `dev_runs/`, so they never touch the formal `runs/` directory or the one-time Holdout.

```bash
export MRF_RUNS_ROOT=dev_runs
RUN_ID=$(python -m src.cli init-run --mode synthetic | python -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
SEED=$(python -c 'import json;print(json.load(open("config/data_config.json"))["seed"])')
```

### Demo A: deterministic pipeline (no API key, about 5 minutes)

```bash
python -m src.cli prepare --run-id "$RUN_ID" --synthetic --seed "$SEED"
for step in baseline reference-parity fixture-parity mutation-check docker-boundary; do
  python -m src.cli $step --run-id "$RUN_ID" || break
done
```

What to look for in `dev_runs/$RUN_ID/`:

| Step | Expected result | File |
| --- | --- | --- |
| `baseline` | R `glm` fitted inside Docker | `reference/r_execution.json` |
| `reference-parity` | max \|Δp\| about 2.2e-16 and 0 class mismatches | `parity/reference_dev/parity_summary.json` |
| `mutation-check` | one coefficient shifted by 0.001 is **detected** (status `PASS` means the error was caught) | `mutation/mutation_summary.json` |
| `docker-boundary` | no network, non-root, read-only, resource limits enforced | `runner_integration/` |

### Demo B: full Agent flow with the three gates (needs the gateway)

After Demo A, on the same `RUN_ID`:

```bash
python -m src.cli check-provider --run-id "$RUN_ID"
for m in MDL_CREDIT_V1 MDL_CREDIT_V2 MDL_CREDIT_TREE; do
  python -m src.cli extract-inventory --run-id "$RUN_ID" --model $m
done
python -m src.cli status --run-id "$RUN_ID"           # prints the exact hashes and approve commands

# Gate A: read model_inventory.json, then approve its hash
python -m src.cli approve --run-id "$RUN_ID" --gate Gate_A --sha256 '<hash from status>' \
  --reviewer '<your name>' --comment '<what you checked>'

python -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 0
python -m src.cli show-candidate     --run-id "$RUN_ID" --attempt 0   # source, diff, 64-hex hash
# Gate B: approve the candidate hash before it runs
python -m src.cli approve --run-id "$RUN_ID" --gate Gate_B --attempt 0 --sha256 '<candidate_sha256>' \
  --reviewer '<your name>' --comment '<what you checked>'

python -m src.cli run-dev            --run-id "$RUN_ID" --attempt 0
python -m src.cli candidate-fixtures --run-id "$RUN_ID" --attempt 0
python -m src.cli freeze             --run-id "$RUN_ID" --attempt 0
python -m src.cli accept             --run-id "$RUN_ID"               # one-time Holdout

python -m src.cli validation-metrics --run-id "$RUN_ID"
python -m src.cli agent-summary      --run-id "$RUN_ID"
python -m src.cli report             --run-id "$RUN_ID"
# Gate C: approve the report (easiest from UI page 4), then:
python -m src.cli approve-report     --run-id "$RUN_ID"

python -m src.cli acceptance --run-id "$RUN_ID"
python -m src.cli export     --run-id "$RUN_ID"                        # last step; seals the run
```

On synthetic data, `acceptance` reports **V1-02 BLOCKED** and `release_approved=false`. This is by design: synthetic data can never pass as formal evidence.

### Demo C: web UI

```bash
streamlit run app.py      # http://localhost:8501
```

| Page | What it shows |
| --- | --- |
| 1 · Inventory | three models, Gate A status, run history, buttons for each pipeline step |
| 2 · Model detail | cited facts, `Unknown` fields, the 0.35 vs 0.50 conflict, Gate A form |
| 3 · Migration | candidate source and hash, Gate B form, R vs Python parity scatter plot |
| 4 · Validation report | performance, calibration, drift, fairness, Gate C, downloads |

In the sidebar, choose **dev_runs** and use **New run** to start a synthetic run from the browser. Each page shows a badge such as `SYNTHETIC`, `REPLAY` (stored results) or `LIVE` (a command just ran in this session), so it is always clear what you are looking at.

### Formal run (UCI data)

A formal run uses `init-run --mode uci` from a clean commit. `download-uci` and `prepare --uci` both check the ZIP's SHA-256 (`56c885f8…7602`), and you must state `--approve-uci-use` explicitly. Each data split's Holdout can be consumed only once, recorded in `runs/holdout_consumption.jsonl`, and `release-check --tag <ref> --run-id <id>` decides APPROVED or BLOCKED.

## 4. Deliverables

| Material | File |
| --- | --- |
| Solution overview (submission template) | [Doc/Overview.pdf](Doc/Overview.pdf) |
| Solution deck | [Doc/solution_deck.pdf](Doc/solution_deck.pdf) |
| Demo video (1:51, English narration with captions, synthetic replay) | [Doc/demo_video.mp4](Doc/demo_video.mp4) |
| Architecture diagram | [Doc/architecture.png](Doc/architecture.png) |
| Responsible AI note | [Doc/responsible_note.pdf](Doc/responsible_note.pdf) |
| Official challenge brief and data-use basis | [docs/official/](docs/official/) |

The same package is shared on Google Drive: https://drive.google.com/drive/folders/1GQCx5Ga9PPDK9tbbCBb1uA5KV8qI5pIK

## 5. Repository layout

| Path | Contents |
| --- | --- |
| `app.py`, `src/ui_*.py` | Streamlit UI |
| `src/cli.py` | single entry point: `python -m src.cli <command>` |
| `src/data.py`, `baseline.py`, `reference.py`, `parity.py` | data splits, R baseline, trusted Python reference, record-by-record comparison |
| `src/provider.py`, `agent.py`, `review.py`, `workflow.py` | gateway, Agent tools, gates, dev → Holdout workflow |
| `src/validation.py`, `report.py` | metrics and report rendering (Gate C) |
| `src/acceptance.py`, `evidence.py`, `release.py` | acceptance checks, evidence export, `release-check` |
| `src/runner.py`, `docker/` | isolated candidate runner |
| `legacy/` | the three R models and their stale notes (team-built test material) |
| `config/` | seed, contracts, schemas, gateway and container settings |
| `tests/` | automated tests |

Exit codes: `0` means success, `1` means a parity or acceptance failure, and `2` means an input, config, gate or execution error.

## 6. Data, AI use and limitations

- **Data:** [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients) (ID 350), CC BY 4.0. The official rules allow public or synthetic data. The raw file is not committed.
- **AI in the product:** an LLM gateway (default `deepseek-v4.1-flash:1017`) extracts the inventories, writes the candidate and explains the report. The trusted Python reference and all fixed tests are written by people, not by the Agent.
- **AI in development:** Claude Code and Kimi Code CLI helped with code, tests and documentation.
- **Validation scope:** the Holdout is a random sample from the same period. Drift is a sensitivity analysis on a weighted resample. A cross-time back-test is not possible on this data and is listed as missing evidence. Fairness results are audit signals, not compliance conclusions.
- **Out of scope:** SAS ingestion, uploading arbitrary models, MLflow/Azure ML, cloud deployment, automatic PDF generation.
