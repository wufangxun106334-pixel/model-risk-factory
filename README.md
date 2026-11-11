# Model Risk Factory

**An Agent-assisted model-risk pipeline for a bank's legacy model estate.** It documents legacy R models from their code and stale notes, migrates one model to Python with record-by-record parity proof, and produces a validation report in which every number traces back to a metrics file. A reviewer decision, bound to the exact artifact hash, sits at each of the three gates.

EXL × UCD Data & AI Hackathon 2026 · Challenge 04 *Agentic model risk factory* · competition prototype.

## For judges

**The problem.** The client brief describes ~250 production models, documentation that has drifted from the code, and 8–12 weeks per validation under PRA SS1/23 *(client context from the brief, not measured here)*. This prototype automates the mechanical part: reading code and notes, porting the model, proving equivalence, computing the metrics. Reviewers keep the decisions.

**Headline results** (each figure names the run it comes from)

| What | Result | Source run |
| --- | --- | --- |
| Inventory | 3 R models documented; MDL_CREDIT_V1 keeps the 0.35 (code) vs 0.50 (note) threshold conflict; owner and training date stay `Unknown`; every fact carries path, line range, excerpt and SHA-256 | HIST-UCI seed 46 |
| R → Python parity | max \|Δp\| 2.220e-16 on 6,000 dev + 6,000 Holdout rows, 0 classification and 0 behaviour mismatches (tolerance 1e-8 / 1e-10) | HIST-UCI seed 46 |
| Bug detection | A +0.001 change to one coefficient is caught by the fixed validator | every run (`mutation-check`) |
| Validation | Holdout ROC-AUC 0.7529, Brier 0.1422; prediction PSI 0.0170, worst feature PSI 0.0799; fairness audit by age band and sex | HIST-UCI seed 46 |
| Traceability | 191 report values each resolve to a JSON path (0 unresolved); Gate C re-renders and compares every table cell | HIST-UCI seed 46 |
| Automation time | Full chain (3 inventories, migration, validation, report, export): 29 commands, 3.49 min wall clock. No speed-up percentage is claimed, because the manual comparison has not been run yet | SYN-SEED47 synthetic drill |
| Tests | 358 passed, 0 failed, 0 skipped (with the verified UCI ZIP present) | this commit |

HIST-UCI is the historical formal run `v2-20261109T210903Z-3dcfab73` (UCI data, seed 46). SYN-SEED47 is the synthetic drill `v2-20261110T182506Z-9acb1487`.

**Status, stated plainly.** v1 is accepted locally: tag `v1` → `70858cd`, not pushed. The v2 run passed all 14 checks, but its evidence was produced on a dirty worktree, so `release-check` blocks it. The single formal v3 run (UCI, seed 47) is scripted and checked by `formal-preflight`. It waits on three things: the organiser's written data permission, confirmation of the team ledger, and named reviewers. See [Release status](#发布状态).

**Everything here is a competition prototype**: not production-ready, not independently validated, not a regulatory certification, and the data is a 2005 Taiwan credit-card sample, not a UK portfolio.

**What is actually implemented and demonstrated**

1. **Inventory with gaps preserved** — three team-built R models documented by an Agent from their real code and real (deliberately stale) notes; every fact carries path, line range, verbatim excerpt and SHA-256; `owner` and `training date` stay `Unknown`; the 0.35-vs-0.50 threshold conflict is kept, never normalised. Gate A approves the artifact hash.
2. **R → Python migration** — the Agent writes the candidate from the exported R coefficients/medians/feature order and the 0.35 threshold (no retraining). Gate B approves the exact 64-hex source hash *before* execution. Record-by-record parity against the R baseline: max |Δp| 2.220e-16 on 6,000 dev and 6,000 holdout rows, 0 classification mismatches, tolerance 1e-8/1e-10 (historical UCI run, seed 46).
3. **Validation and monitoring** — performance with a decile calibration table, PSI drift with configurable attention/review lines, TPR/FPR fairness audit with small-sample states; deterministic Python computes, the Agent only explains, Gate C re-renders and compares every table cell.
4. **Evidence and release discipline** — every number in the report resolves to a JSON path; one-time Holdout consumption; whitelisted evidence ZIP; `release-check` re-runs the full suite on the tag tree and refuses to approve evidence that does not belong to the released commit.

**Reproduce it (new environment, ~5 minutes plus dependency download)**

```bash
git clone <repo> && cd model-risk-factory
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt      # locked versions
python -m pytest -q                            # 8 UCI-dependent tests skip without the verified ZIP
export MRF_RUNS_ROOT=dev_runs                  # synthetic drill stays out of runs/
RUN_ID=$(python -m src.cli init-run --mode synthetic | python -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
SEED=$(python -c 'import json;from pathlib import Path;print(json.loads(Path("config/data_config.json").read_text())["seed"])')
python -m src.cli prepare --run-id "$RUN_ID" --synthetic --seed "$SEED"
for step in baseline reference-parity fixture-parity mutation-check docker-boundary; do
  python -m src.cli $step --run-id "$RUN_ID" || break
done
```

Needs Docker running (images `rocker/r-ver:4.4.2` and `model-risk-factory-runner:v1`). The Agent stages additionally need gateway credentials (`LLM_*` environment variables); without them the pipeline still runs the deterministic parts and the UI clearly labels stored results as `REPLAY`.

```bash
python -m pip install -r requirements-ui.txt
streamlit run app.py        # four pages: Inventory · Model detail · Migration · Validation report
```

**Full end-to-end drill and UI check**: [docs/v3/02_new_environment.md](docs/v3/02_new_environment.md) (clean worktree, fresh venv, real gateway, 29-step run, screenshots in [docs/v3/ui_screens/](docs/v3/ui_screens/)).

**Deliverables** (see [materials/submission_checklist.md](materials/submission_checklist.md) for length, links and status)

| Material | File |
| --- | --- |
| Solution deck (10 slides) | [materials/solution_deck.md](materials/solution_deck.md) · `.pptx` · `.pdf` |
| Demo video (1:51, synthetic replay) | [MP4](materials/demo_video.mp4) · [transcript](materials/demo_video_script.md) |
| Architecture diagram (1 page) | [materials/architecture.svg](materials/architecture.svg) · [.md](materials/architecture.md) |
| Responsible AI note (1 page) | [one-page PDF](materials/responsible_ai_note.pdf) · [source](materials/responsible_ai_note.md) |
| Business value measurements | [materials/impact_measurements.csv](materials/impact_measurements.csv) · [protocol](materials/impact_measurements_README.md) |

**Data licence**: UCI Default of Credit Card Clients (ID 350), CC BY 4.0. Written organiser confirmation for this competition entry is **still outstanding**; `config/data_config.json` records `uci_competition_use_approved=false` and every formal run needs an explicit `--approve-uci-use` declaration from an authorised operator. The raw file is not committed; a download step verifies its SHA-256.

**AI tools used**: Claude Code and Kimi Code CLI for implementation, tests and documentation; this delivery Agent for the v3 audit, fixes and materials. In the product, the gateway `https://sa.kaiwen.dev/v1` (`openai_chat_completions`) with model **`deepseek-v4.1-flash:1017`** performs inventory extraction, candidate generation and report explanation (the v1 candidate was generated by `kimi-k2.7-code`). The trusted Python reference predictor and all fixed tests are human-written, not Agent output.

**Frozen scope**: three model inventories, one migration, four metric families, three gates, evidence export, four UI pages. Out of scope and not implemented: SAS ingestion, arbitrary model upload, MLflow/Azure ML, React/FastAPI, cloud deployment, automatic PDF generation.

## 发布状态

- **v1**：本地已验收，标签 `v1` → `70858cd`，`origin` 上没有任何标签。
- **v2**：历史 run `v2-20261109T210903Z-3dcfab73` 的 14 项验收全部 PASS，但证据生成时工作区不干净，`release-check` 返回 17 条缺口，发布为 BLOCKED。
- **V3**：代码、测试和五件套已齐。唯一一次 seed 47 正式 run 还缺 [决策记录](docs/v3/11_formal_run_decisions.md) H-01～H-04 的签署。签署后的执行步骤是：

```bash
.venv/bin/python -m src.cli formal-preflight --expected-sha "$(git rev-parse HEAD)"   # 只读；任何一项 FAIL 都不能继续
bash docs/v3/formal_run.sh                                                             # 交互式三道 Gate，accept 前要再次确认
```

逐项状态见 [发布清单](docs/v3/07_release_checklist.md) 与 [交接清单](docs/v3/08_handoff.md)。v1/v2 的验收细节、阻断修复、命令记录与历史复核步骤都移到了 [工程记录](docs/engineering_notes.md)，内容没有删减。

## 工作目录

以下命令都在仓库根目录 `model-risk-factory/` 执行。应用入口是 `python -m src.cli`。

| 路径 | 内容 |
| --- | --- |
| [docs/](docs/) | 比赛背景、团队分工、版本验收标准和官方材料。设计决策以 [项目 SOP](docs/02_项目SOP.md) 为准。 |
| [legacy/](legacy/) | R 模型和模拟旧文档。阈值冲突与 Unknown 是用于检验档案提取的预设素材。 |
| [config/](config/) | 数据划分 seed、模型和候选输入输出契约、Schema、API 与容器运行参数。 |
| [src/cli.py](src/cli.py) | 命令入口，串联取数、建基准、建档、审批、迁移、验证和导出。 |
| [src/data.py](src/data.py)、[src/baseline.py](src/baseline.py)、[src/reference.py](src/reference.py)、[src/parity.py](src/parity.py) | 数据准备、R 基准、可信 Python 参考预测和逐记录比较。 |
| [src/provider.py](src/provider.py)、[src/agent.py](src/agent.py)、[src/review.py](src/review.py)、[src/workflow.py](src/workflow.py) | 网关接入、Agent 工具、档案和候选审批，以及开发测试到 Holdout 的流程。 |
| [docker/](docker/) 与 [src/runner.py](src/runner.py) | 候选执行镜像与隔离运行器。 |
| [src/acceptance.py](src/acceptance.py)、[src/evidence.py](src/evidence.py)、[tests/](tests/) | 验收判定、证据包导出和自动化测试。 |

本地生成的目录由 CLI 按需创建。Git 共享源码、配置和测试；联调时用同一个 `run_id` 对齐证据。

| 本地路径 | 怎么用 |
| --- | --- |
| `.venv/`、`.env` | 各自的 Python 环境和本地密钥。用 [.env.example](.env.example) 核对变量名，并把配置导入当前 shell。 |
| `data/raw/` | 原始 UCI ZIP，由下载命令写入。 |
| `runs/<run_id>/` | 单次运行的分区数据、R 基准、档案、候选、审批和验证结果。每人使用自己的开发 run。 |
| `delivery/` | 可分享的白名单证据 ZIP 和验收 JSON。共享时同时注明 `run_id` 和对应提交。 |

## 第一次运行

先安装依赖并跑单元测试。需要真实 Agent 迁移时再配置网关。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

启动 Docker 后，用合成数据跑一次 R 基准和 Python 参考验证。这条路径只需本地环境与 R 镜像。每次新建 run，并从当前配置读取 seed。

```bash
docker pull rocker/r-ver:4.4.2
RUN_ID=$(python -m src.cli init-run --mode synthetic | python -c 'import json, sys; print(json.load(sys.stdin)["run_id"])')
SEED=$(python -c 'import json; from pathlib import Path; print(json.loads(Path("config/data_config.json").read_text())["seed"])')
python -m src.cli prepare --run-id "$RUN_ID" --synthetic --seed "$SEED"
python -m src.cli baseline --run-id "$RUN_ID"
python -m src.cli reference-parity --run-id "$RUN_ID"
python -m src.cli fixture-parity --run-id "$RUN_ID"
python -m src.cli mutation-check --run-id "$RUN_ID"
```

首次联调可以查看 `runs/$RUN_ID/command_log.jsonl` 和 `runs/$RUN_ID/parity/reference_dev/parity_summary.json`。正式 Agent 迁移另需构建候选镜像，然后按工程记录中的 [API 配置](docs/engineering_notes.md#api-配置)、[正式 UCI 数据](docs/engineering_notes.md#正式-uci-数据) 和 [真实 Agent 迁移流程](docs/engineering_notes.md#真实-agent-迁移流程) 顺序执行。V3 正式 run 的入口见下文「发布状态」。

```bash
docker build -t model-risk-factory-runner:v1 docker
```

实测环境为 macOS arm64、Python 3.15.2、Docker 29.9.2 和容器内的 R 4.4.2。镜像摘要与依赖记录见正式 run 的 `environment.json`。

## 声明与限制

- 旧 R 模型和旧文档是团队自建模拟资产；文档故意含阈值冲突和 Unknown。
- 运行数据是真实 UCI 公开数据（CC BY 4.0）。主办方对本参赛作品使用该数据的书面确认仍待取得（`config/data_config.json` 中 `uci_competition_use_approved=false`）。它不代表真实客户、英国银行模型表现、独立验证或监管合规。
- 开发使用 Claude Code 与 Kimi Code CLI 辅助实现代码、测试和文档。受控 Python 参考预测器是独立编写的确定性基准，不是 Agent 自动迁移；v1 的迁移候选由真实 API 生成（`kimi-k2.7-code`，记录在 `candidate.json` 与 `agent_audit_log.jsonl`）。
- v2 的三份档案、迁移候选和报告解释均由真实网关 `deepseek-v4.1-flash:1017` 生成，分别记录在 `agent_audit_log.jsonl` 与 `provider/request_log.jsonl`；Gate A/B/C 由执行本任务的 Agent 按 SOP 7.4 以 `agent-delegated` 代理审核，审批备注写明授权来源与逐项核对内容。
- 已发布版本的模型 ID 以正式 run 的能力检查与候选生成记录为准。
- 使用 NumPy、pandas、Pydantic、pytest、xlrd、Docker、R base `glm` 与 `rpart`；指标计算只用 NumPy（未引入 scikit-learn）。Streamlit 四页界面（`app.py` + `src/ui_data.py` + `src/ui_charts.py`，依赖 `requirements-ui.txt`）已实现并在 v3 实测。
- 验证口径：Holdout 为同期随机留出（样本外验证）；场景 A 漂移批次为加权抽样的敏感性分析；跨时间回测在本数据上不可得，报告中列为缺失证据。公平性结果为审计信号，不构成公平性或合规结论。
- 设计主文件仍为 [docs/02_项目SOP.md](docs/02_项目SOP.md)；官方背景见 [docs/01_比赛背景与官方要求.md](docs/01_比赛背景与官方要求.md)。
