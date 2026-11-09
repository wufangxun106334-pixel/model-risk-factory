# Model Risk Factory

EXL × UCD Data & AI Hackathon 2026 — Challenge 04 Agentic model risk factory。

**v1 与 v2 均已完成本地验收。** CLI 将团队自建的信用违约模型 `MDL_CREDIT_V1` 从 R 迁移到 Python，对照 R 基准逐记录验证预测概率、分类和异常处理；v2 补齐另外两个旧模型的档案、容器边界实测、四类验证指标、三道审核门禁、端到端导出与报告数值溯源。

- v1 正式 run `v1-20261109T181929Z-3fe1c7b5`：V1-01～07 全 PASS（Gate A/B 代理审核），标签 `v1`。
- v2 正式 run **`v2-20261109T210903Z-3dcfab73`**（campaign seed 46）：V1-01～07 与 V2-01～07 共 14 项全 PASS，`release_approved=true`，Gate A（三份档案）/ Gate B / Gate C 均为 `agent-delegated` 代理审核。

> **发布状态：BLOCKED（2026-11-09）。** 该 run 的证据内部自洽（63 个文件哈希、14/14 PASS、导出哈希全部复算一致），但**无法绑定到任何提交**：它的测试树在工作区未提交时被使用，`git_commit_at_init=ec6077f`，而 `v2` 标签指向 `9884e3a`，`config/data_config.json` 也在 run 之后才提交。UCI 数据只剩 **1,199** 行从未消费，无法再产生一份 6,000 行正式 Holdout。缺口与后续步骤见「发布状态与缺口」。`v2` 标签保持在 `9884e3a`，但**不得作为有效发布引用**。

交付物是本机的 `delivery/<run_id>_acceptance.json` 与 `delivery/<run_id>_evidence.zip`；`runs/`、`delivery/` 与原始数据不进 Git。Streamlit 界面按计划留给 v3。

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

首次联调可以查看 `runs/$RUN_ID/command_log.jsonl` 和 `runs/$RUN_ID/parity/reference_dev/parity_summary.json`。正式 Agent 迁移另需构建候选镜像，然后按 [API 配置](#api-配置)、[正式 UCI 数据](#正式-uci-数据) 和 [真实 Agent 迁移流程](#真实-agent-迁移流程) 顺序执行。

```bash
docker build -t model-risk-factory-runner:v1 docker
```

实测环境为 macOS arm64、Python 3.15.2、Docker 29.9.2 和容器内的 R 4.4.2。镜像摘要与依赖记录见正式 run 的 `environment.json`。

## 分工与交接

- **建模验证**负责数据字典、R 模型和基准、可信 Python 参考实现、固定验证样例与指标。优先看 [数据配置](config/data_config.json)、[候选契约](config/candidate_contract.json) 和 [参考等价性测试](tests/test_reference_parity.py)。
- **AI 工程**负责网关、Agent、审批、Docker 与证据导出。双方在 [候选契约](config/candidate_contract.json) 和 [SOP 验收标准](docs/02_项目SOP.md) 对齐输入输出、容差和失败状态，再并行修改各自模块。
- **联调交接**附上提交、`run_id`、复现命令、测试结果与证据路径。修改已冻结的代码、配置或测试后，用新 run 联调。候选执行走 CLI 门禁与 Docker；正式 Holdout 由冻结后的候选完成一次性验收。
- **证据交接**以 `export` 为该 run 的最后一步。共享 `delivery/` 中的白名单证据包和验收 JSON，封印后的 run 用于查阅。逐行数据、基准答案和密钥留在本机。

## 合成开发验证记录

以下是历史合成 run `v1-20261109T160955Z-c4e69c96` 的开发结果。当前 v1 测试结果为 **103 passed, 7 subtests passed**。合成数据、mock 和人工参考实现用于开发验证，正式结果见下方的逐项验收表。

- 合成数据：30,000 行；train/dev/holdout/shift_pool 分别为 15,000/6,000/6,000/3,000；ID 唯一且四集互斥；各集违约率与总体最大差约 0.00003333（比例），低于 0.01。
- R 基准：真实 `glm` 拟合，导出双精度系数、特征顺序、训练集填补参数、预测和 `sessionInfo`；不使用 ID、标签或人口属性作为特征。
- 参考 dev parity：6,000 行，最大绝对误差 `2.220446049250313e-16`，平均绝对误差 `3.14563190310461e-18`，分类和填补/拒绝行为差异均为 0。
- 参考 Holdout parity：6,000 行，最大绝对误差 `2.220446049250313e-16`；这是参考实现检查，不是已批准候选的最终验收。
- Fixtures：11 条正常/缺失/非法逐行样例、行序与列序变化均 PASS；重复 ID、缺列和空输入均由 R 与 Python 以退出码 2 拒绝；负账单合法。
- 故意错误：隔离副本将 `delay_1` 系数增加 0.001，固定 parity 检出 FAIL，最大绝对误差 `0.001187376493456127`；原模型与测试前后哈希不变，变异检查自身为 PASS。
- Docker：人工参考脚本在 `--network none`、非 root（65532:65532）、只读根目录/输入、512 MiB、1 CPU、64 PID、30 秒超时条件下实际执行并通过 parity。
- 证据包：本轮 `evidence_manifest.json` 记录 **30 个文件**，ZIP 含 manifest 共 31 个条目；不含任何逐行划分、标签、基准答案、预测明细、逐行差异、候选源码或 stdout/stderr。

证据路径：

| 用途 | 路径（相对 `runs/<run_id>/`） |
| --- | --- |
| 数据与划分 | `data/data_manifest.json`、`data/data_dictionary.json`、`data/SOURCE.md` |
| R 基准 | `reference/r_execution.json`、`reference/baseline_manifest.json`、`reference/model.json`、`reference/sessionInfo.txt` |
| 参考 parity | `parity/reference_dev/parity_summary.json`、`parity/reference_holdout/parity_summary.json`、`parity/reference_fixtures/fixture_summary.json` |
| 故意错误 | `mutation/mutation_summary.json` |
| Docker 集成 | `runner_integration/handwritten_reference_fixture/{execution,integration_summary,parity_summary}.json` |
| 验收与导出 | `acceptance.json`、`evidence_manifest.json`、`export_verified.json`、`command_log.jsonl`、`command_log_snapshot.jsonl` |
| 交付包 | `delivery/<run_id>_evidence.zip`、`delivery/<run_id>_acceptance.json` |

## 验收判定逻辑（本轮已收紧）

`python -m src.cli acceptance` 不再只看文件是否存在，而是逐项核对同一 run 的证据：

- **V1-01**：`capability_check.json` 必须是同 run 的真实 PASS，且请求 ID、工具往返、输出解析及对应的 `provider/request_log.jsonl` 记录齐全；配置缺失记为 `BLOCKED`，实际失败记为 `FAIL`。
- **V1-02**：必须是 `data_kind=uci` 且 `formal_status=APPROVED`；核对同 run 的 `uci_approval.json`、`download.json`、原始 ZIP 实际哈希、数据配置哈希、四份划分文件及其磁盘哈希、划分行数 15000/6000/6000/3000 与分层校验结果。缺项、被改写或来自其他 run 一律 `FAIL`。
- **V1-03**：R 执行状态、退出码、`network=none`、脚本哈希，以及每个产物的磁盘哈希。
- **V1-04**：参考 dev、参考 Holdout 与 6 个行为 fixtures（3 个逐行样例 + 3 个结构性拒绝）都要 PASS，且 run_id、ID 对齐、分类/行为差异、有效概率对数符合契约。
- **V1-05**：变异摘要 PASS、变异被检出、原始模型与测试哈希前后一致。
- **V1-06**：真实 API 候选（`generation_mode=REAL_API`）+ 当前 Gate A/B 审批 + 同 context + 冻结哈希 + Docker 开发 parity + 行为 fixtures PASS + 一次性 Holdout PASS，缺一即 `FAIL`；测试替身候选永远不能通过。
- **V1-07**：同一 run 的 CLI 记录必须按序为 `check-provider → prepare → baseline → reference-parity → fixture-parity → mutation-check → extract-inventory → approve(Gate_A) → generate-candidate → approve(Gate_B) → run-dev → candidate-fixtures → freeze → accept`，且每条退出码为 0；同时 `evidence_manifest.json` 中每个文件哈希与磁盘一致，`export_verified.json` 的 manifest/ZIP 哈希未过期。

证据包使用显式白名单（`src/evidence.py`）。逐行划分、标签、基准答案、预测明细、逐行差异、候选源码/diff 以及 stdout/stderr 一律留在本机。

## 迁移门禁（本轮已收紧）

- `generate-candidate` 需要 Gate A 批准与有效 context；Gate A 被撤回或档案内容变化后，Gate A 立即失效。
- `run-dev` 需要 Gate A 与 Gate B、候选 context 一致、`data/dev.csv` 哈希与 manifest 一致。
- `candidate-fixtures` 在 Docker 内用同一候选运行 3 个行为 fixtures 与 3 个结构性拒绝 fixtures。
- `freeze` 需要 Gate A/B、开发 parity PASS、fixtures PASS、候选哈希与 context 一致。
- `accept`（Holdout）额外要求：冻结候选、Gate A/B 仍有效、开发执行成功、运行镜像与开发一致、`data/holdout.csv` 哈希与 manifest 一致；一次性账本 `runs/holdout_consumption.jsonl` 记录后不可重跑。

## API 配置

CLI 从当前进程环境变量读取连接配置。新运行默认使用 [网关配置](config/provider_config.json) 中的 `deepseek-v4.1-flash:1017`，也可以通过 `LLM_MODEL` 显式指定模型。先创建正式 run，再在同一终端执行取数、迁移和验收命令。

```bash
export LLM_BASE_URL='https://sa.kaiwen.dev/v1'
export LLM_CHAT_COMPLETIONS_URL='https://sa.kaiwen.dev/v1/chat/completions'
export LLM_PROTOCOL='openai_chat_completions'
export LLM_MODEL='deepseek-v4.1-flash:1017'
printf 'LLM API key: ' >&2
read -rs LLM_API_KEY
export LLM_API_KEY
export LLM_TIMEOUT_SECONDS='300'
export LLM_MAX_OUTPUT_TOKENS='32768'

RUN_ID=$(.venv/bin/python -m src.cli init-run --mode uci | .venv/bin/python -c 'import json, sys; print(json.load(sys.stdin)["run_id"])')
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli check-provider --run-id "$RUN_ID"
```

此命令执行一次短请求和一次两步工具往返，记录脱敏的请求 ID 与执行状态。实测注意点：网关偶发返回 504 或工具往返内容不合规，而 V1-07 只接受首轮即成功的命令链（见「已知工具缺陷」），所以能力检查失败时只能新建 run 重跑。`LLM_MAX_OUTPUT_TOKENS` 过小（如 8192）会使候选在 `submit_candidate` 中途被截断（`finish_reason=length`）。

## 正式 UCI 数据

v1 使用 [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)（CC BY 4.0）。获准使用后，沿用上一步 `check-provider` 通过的 `RUN_ID`。

```bash
SEED=$(.venv/bin/python -c 'import json; from pathlib import Path; print(json.loads(Path("config/data_config.json").read_text())["seed"])')
.venv/bin/python -m src.cli download-uci \
  --run-id "$RUN_ID" \
  --expected-sha256 '56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602' \
  --approve-uci-use
.venv/bin/python -m src.cli prepare \
  --run-id "$RUN_ID" \
  --uci data/raw/default_of_credit_card_clients.zip \
  --expected-sha256 '56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602' \
  --approve-uci-use --seed "$SEED"
.venv/bin/python -m src.cli baseline --run-id "$RUN_ID"
.venv/bin/python -m src.cli reference-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli fixture-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli mutation-check --run-id "$RUN_ID"
```

`--approve-uci-use` 是已获主办方确认后的显式操作声明，不是程序自动取得许可。`download-uci` 与 `prepare` 都会校验哈希，并分别写入 `data/download.json`、`data/uci_approval.json`；V1-02 会核对这两份记录、原始文件与四份划分的哈希。`.xls` 使用 `header=1` 读取。合成 manifest 的 `formal_status` 永远是 BLOCKED。`prepare --seed` 必须等于配置里的 campaign seed（v1 为 43，见「campaign 与 seed」）。

## 真实 Agent 迁移流程

前置条件：同一 run 的 `check-provider` 为 PASS、R 基准已完成，且数据路径已确定。以下命令在 v1 正式 run `v1-20261109T181929Z-3fe1c7b5` 上实际执行。

### 1. 档案与 Gate A

```bash
.venv/bin/python -m src.cli extract-inventory --run-id "$RUN_ID"
.venv/bin/python -m src.cli status --run-id "$RUN_ID"
```

审阅 `model_inventory.json` 的来源行/摘录、四项 Unknown（Owner、Training date、Preparation records、Original approval evidence）、特征顺序 `delay_1,log_limit,util_1,log_pay_1`，以及代码 0.35 与文档 0.50 的遗留冲突（必须保留为冲突，不得自动归一）。`status` 会输出完整审批命令。Gate A 哈希是档案内容（排除随审核变化的 `review_status`）的规范 JSON SHA-256；人工审核与代理审核共用同一哈希与同一命令：

```bash
.venv/bin/python -m src.cli approve \
  --run-id "$RUN_ID" --gate Gate_A \
  --sha256 '<status 显示的档案哈希>' \
  --reviewer '<审核人姓名> 或 agent-delegated' \
  --comment '<实际核对内容>'
```

人工审核时 `--reviewer` 填审核人姓名；代理审核时填 `agent-delegated`，并在 `--comment` 写明授权来源与逐项核对结果（见「Gate 审核口径」）。

### 2. 真实候选、diff 与 Gate B

Gate A 批准后才允许真实 API 生成：

```bash
.venv/bin/python -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli show-candidate --run-id "$RUN_ID" --attempt 0
```

审阅完整 diff、源码与完整 64 位候选哈希，并确认候选按 R 导出的系数/中位数/特征顺序/0.35 阈值推理、输入输出契约与 R 一致、无网络与不写测试/基准、适合 `--network none` 只读非 root 容器。候选此时未执行。Gate B 同样区分人工与代理审核：

```bash
.venv/bin/python -m src.cli approve \
  --run-id "$RUN_ID" --gate Gate_B --attempt 0 \
  --sha256 '<candidate.json 中的 candidate_sha256>' \
  --reviewer '<审核人姓名> 或 agent-delegated' \
  --comment '<实际核对内容>'
.venv/bin/python -m src.cli run-dev --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli candidate-fixtures --run-id "$RUN_ID" --attempt 0
```

开发失败时只允许两次修复，每个新哈希重新 Gate B：

```bash
.venv/bin/python -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 1
.venv/bin/python -m src.cli show-candidate --run-id "$RUN_ID" --attempt 1
# 你对 attempt 1 执行 Gate B，再 run-dev --attempt 1 与 candidate-fixtures --attempt 1。
# 若仍失败，attempt 2 同样重新审批；之后停止修复。
```

Agent 只获得允许的模型资料、Schema 和不含原始行/基准答案的开发摘要。测试源码、基准预测和 Holdout 输入/答案不作为 Agent 工具或提示内容。

### 3. 冻结、独立 Holdout、验收与导出

```bash
.venv/bin/python -m src.cli freeze --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli accept --run-id "$RUN_ID"
.venv/bin/python -m src.cli acceptance --run-id "$RUN_ID"
.venv/bin/python -m src.cli export --run-id "$RUN_ID"
```

将 `--attempt` 换成实际通过开发的已批准编号。Holdout 只由宿主受信验证器比较，容器不接收基准答案；同一 run 已有 Holdout 结果后拒绝重复验收。失败保留 FAILED 证据，不把结果送回 Agent 调参。`export` 是最后一条命令；封印后不要再写入运行目录。

## Gate 审核口径：人工审核 vs 代理审核

两种口径共用同一道硬门禁，不能混用为“免审”：

- **哈希与顺序相同**：Gate A 用档案内容（排除 `review_status`）的规范 JSON SHA-256；Gate B 用候选源码完整 64 位 SHA-256。审批顺序仍为 Gate A → `generate-candidate` → Gate B → `run-dev`/`candidate-fixtures`，跳步会被门禁拒绝。
- **失效与重审相同**：`context_manifest.json` 或被审物品哈希变化后，之前的审批立即失效（`current_decision` 返回 `INVALIDATED`/`NOT_REVIEWED`），必须对新哈希重新审批；被拒绝的审批不算通过。
- **人工审核**：`--reviewer` 填实际审核人姓名；审核人本人阅读档案、候选源码与 diff 后签字。
- **代理审核**：`--reviewer agent-delegated`，由被授权者（本次为执行本次任务的 Agent）代行审核，并必须满足：实读完整档案与候选源码（不只读摘要）、逐条核对来源行号与文件 SHA-256、核对完整 64 位候选哈希、把授权来源与逐项核对内容写进 `--comment`。未实读即审批属于违规。
- **可追溯**：每条审批写入 `review_log.json`，含 `reviewer`、`decision`、`reviewed_artifact_sha256`、`context_sha256`、`timestamp`，并在 `command_log.jsonl` 留下 `approve` 记录。
- **不改变判定标准**：审核口径只改变“谁来按同一标准审”，不降低 V1-01～07 任何一项；测试替身候选仍然永远不能通过 V1-06。

## campaign 与 seed

数据划分的 campaign seed 由 `config/data_config.json` 的 `seed` 固定（其余字段——总行数、四份行数、违约率容差、UCI URL——仍为不可变常量），`prepare --seed` 必须等于该配置值，否则拒绝执行；seed 会写入 `data_manifest.json` 并参与一次性 Holdout 账本的 `campaign_id`。

| campaign | seed | run_id | 结果 |
| --- | --- | --- | --- |
| 1 | 42 | `v1-20261109T172051Z-a9bd4ef4` | V1-01～06 PASS；一次性 Holdout PASS（6000 行、分类差异 0、`max_abs_diff` 2.22e-16）；V1-07 FAIL（首个 `generate-candidate` 因输出被 8192 token 截断而 exit 2，重试成功后命令链仍留有该失败记录）；Holdout 已按账本消费 |
| 2 | 43 | `v1-20261109T181929Z-3fe1c7b5` | 正式验收 run：命令链首轮全绿，V1-01～07 全 PASS，Holdout PASS，已导出证据包 |
| v2 | 44 | `v2-20261109T203556Z-02f3834e` | 首个 v2 正式 run：14 项全 PASS。发布后复盘发现 5 项发布阻断（见下节），其证据作为历史保留、不再作为发布依据 |
| v2-fix | 45 | `v2-20261109T210057Z-a715536f` | 阻断修复后的重跑：V2-01～07 与 V1-01～06 全 PASS，**V1-07 FAIL** —— 首次 `check-provider` 因网关返回不可解析短回复而失败，我在 `prepare`/`baseline` 之后才原地重试成功，命令链因此不再满足「按序成功」。保留为失败证据，不换 seed 追通过 |
| v2 | 46 | `v2-20261109T210903Z-3dcfab73` | 14 项全 PASS（发布状态 BLOCKED，见下节：证据无法绑定提交），`check-provider` 首轮即通过（失败时立即原地重试再继续），Holdout 与 seed 42/43/44/45 四份已消费 Holdout 逐份重叠 0 行 |

campaign 1 的 Holdout 通过，V1-07 因命令链把首轮生成失败计入验收而失败。正式验收用 seed 43 对同一 UCI 数据集重新划分。两套 Holdout 各有 6,000 条记录，其中 1,199 条重叠。每套划分各执行一次正式 Holdout，两次结果及账本中的 `CONSUMED` 记录均已保留。

候选只按开发证据（dev parity 与行为 fixtures）筛选，Holdout 在冻结后才运行且只运行一次；没有用 Holdout 结果回调候选或提示词。

**提交与 run 的对应关系**：`run_manifest.git_commit_at_init` 记录的是 run 初始化时的 HEAD（`37faf13`）。campaign 2 的 seed 配置变更与文档更新是在 run 执行后提交的（提交本身不改 `src/`、`tests/`、`config/` 之外的验收依据）。因此 `v1` 标签指向的提交，其 `src/`（23 个 `.py`）与 `tests/`（10 个 `.py`）树的 sha256 必须分别等于 `context_manifest.json` 的 `trusted_source_sha256` = `f0c61259…`、`trusted_tests_sha256` = `2eb8a756…`，且 9 个 repository asset（legacy/config/requirements）逐字节等于 context 记录。以 `context_manifest.json` 为权威凭证，而不是 `git_commit_at_init` 的字面值。核验命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import pathlib;from src.context import verify_context;print(verify_context(pathlib.Path('.').resolve(), pathlib.Path('runs/v1-20261109T181929Z-3fe1c7b5'), 'v1-20261109T181929Z-3fe1c7b5'))"
git rev-parse v1^{commit}   # 应为被标记的发布提交
```

## v2 发布阻断修复（针对 `fd44496` 复盘）

首个 v2 发布（`fd44496`，run `v2-20261109T203556Z-02f3834e`）之后复核发现 5 项会削弱证据强度的缺陷。全部已修复并有回归测试；正式验收在 campaign 46 上重跑。

| 阻断 | 问题 | 修复 | 回归测试 |
| --- | --- | --- | --- |
| Gate B 漂移执行 | `validation-metrics` 在跑或复用漂移批次缓存前只检查 `frozen.json` 是否存在，没有校验上下文、冻结源码哈希、Gate A/B 决定、输入与输出哈希 | 新增 `verified_metric_inputs()`：复用 `verify_context`/`load_frozen`/`require_approval`/`current_decision`/`verified_split_hash`，逐项校验 context、冻结源码与副本哈希、Gate A/B、frozen attempt 的 dev parity 与行为 fixtures、四个划分输入哈希；复用缓存时重算 candidate/model/input/output 四个哈希，不一致直接失败而不静默重跑 | `tests/test_v2_blockers.py`（13 例） |
| V2-04 attempt 绑定 | 验收只看 `attempt_000`，首轮失败、后续候选成功的情况会误判 | `_v2_04` 改为读取 `frozen.json` 的 attempt，校验该 attempt 的 parity/fixtures/execution 与 migration_result | 同上（含 attempt 0 失败→attempt 1 成功的用例） |
| Gate C 正常 CLI | 生成/审批/状态检查三处路径不一致（`report_review.json` vs `review_manifest.json`），发布时只能靠逐字节副本变通 | 三处统一为 `report/review_manifest.json`；`report_status` 逐项重算报告、指标、数值索引、表格与 Agent 摘要的哈希，任一缺失或被改动即回 DRAFT 并给出具体原因 | `tests/test_v2_blockers_gate_c.py`（4 例，走真实 CLI 入口 report → approve --gate Gate_C → approve-report → report-status） |
| 报告溯源 | 验收只比对数字是否出现在索引里，伪路径、对调数值、篡改索引都能通过 | 新增 `index_mismatches()`/`index_not_in_report()`：逐行解析 JSON path、按渲染精度核对数值与格式、拒绝矛盾重复行，并要求每条索引文本真的出现在报告正文 | `tests/test_v2_blockers_provenance.py`（8 例） |
| CPU 证据 | 单容器两线程只能证明“约一核”，无法区分配额是否生效 | 探针改为 4 个并行进程并读取容器内 `cpu.max`，另跑一次**不设 `--cpus`** 的对照；有配额须稳定在 ~1 核、无配额须 ≥1.6 核且差距 ≥0.6，缺少对照或不可区分即判 FAIL | `tests/test_v2_blockers_cpu.py`（3 例）+ 实跑证据 |
| 干净检出数据准备 | 排除集读取本机 `runs/*/holdout.csv`，队友干净检出无法准备正式划分 | 新增 `config/holdout_ledger.json`（只存 seed、算法、ZIP 哈希与四个划分哈希）与 `recover_historical_splits()`：用已获准 ZIP 重建历史划分并逐字节核对哈希，重建不符即拒绝；`prepare` 改用重建结果作为排除集，新增 `verify-holdout-ledger` 命令 | `tests/test_v2_blockers_dataprep.py`（7 例，含干净检出 prepare 与 0 重叠断言） |

## v2 正式验收（run `v2-20261109T210903Z-3dcfab73`）

正式 run 在同一 CLI 链内完成：三份真实 Agent 建档与 Gate A、真实迁移候选与 Gate B、容器开发验证、冻结、唯一一次 Holdout、四类指标、Agent 摘要、报告与 Gate C、故障演练、导出。数据划分在跑前冻结：campaign seed 46，Holdout 只从**四份已消费 Holdout 未覆盖的行**中抽取，逐份重叠 0 行（证据在 `data/data_manifest.json` 的 `holdout_exclusion`，划分登记哈希与正式 run 逐字节一致）。

| 项 | 结果 | 证据（`runs/v2-20261109T210903Z-3dcfab73/`） |
| --- | --- | --- |
| V2-01 三模型建档 | PASS：三份档案 Schema/来源/哈希通过，Gate A 逐份 `agent-delegated`（V1 14 来源 4 冲突、V2 13 来源 7 冲突、TREE 16 来源 7 冲突）；owner 与 training_date 保持 Unknown；V1 保留 0.35/0.50 阈值矛盾 | `model_inventory.json`、`inventories/*.json`、`review_log.json` |
| V2-02 容器边界 | PASS：8 项实跑检查（只读根与输入、无宿主/基准挂载、容器内无 API key、内存、CPU 配额、CPU 配额对照、PID、超时）；有配额 1.02 核 / 无配额 4.0 核 | `boundary/boundary_report.json` |
| V2-03 四类验证 | PASS：parity 2.220e-16（dev/holdout 各 6000 行、0 分类差异）；holdout ROC-AUC 0.7529 / Brier 0.1422、十分位校准表、混淆矩阵；场景 A 漂移 PSI 最大 0.0799（<0.10）；age_band 与 sex 的 TPR/FPR 与参考组差异 | `validation_metrics.json`、`report/validation_tables.md`、`validation/shifted_manifest.json` |
| V2-04 三道审核 | PASS：按实际冻结的 attempt 校验 Gate A → 候选 → Gate B → 执行 → Gate C → APPROVED 的顺序与哈希 | `review_log.json`、`report/approval.json` |
| V2-05 端到端 | PASS：单 run CLI 全链，导出 MD/CSV/JSON，`run_id` 与 63 个证据文件哈希一致 | `evidence_manifest.json`、`export_verified.json` |
| V2-06 故障处理 | PASS：真实 404、真实超时、真实 8 次请求上限、真实非 JSON 解析失败、注入修复耗尽，错误原文全留 | `failures/failure_drills.json`、`failures/drills/*.json` |
| V2-07 报告溯源 | PASS：191 个数值逐条解析回 JSON path（0 不符、0 缺失、0 未解析）；Agent 只收脱敏汇总且不重述数字；报告区分同期留出/漂移敏感性/缺失的跨时间回测，无合规措辞 | `report/validation_report.md`、`report/values_index.csv`、`report/agent_summary.json` |

### v2 正式 run 的实际命令（按执行顺序）

```bash
export LLM_BASE_URL=https://sa.kaiwen.dev
export LLM_CHAT_COMPLETIONS_URL=https://sa.kaiwen.dev/v1/chat/completions
export LLM_PROTOCOL=openai_chat_completions
export LLM_MODEL=deepseek-v4.1-flash:1017
export LLM_TIMEOUT_SECONDS=300
export LLM_MAX_OUTPUT_TOKENS=32768
export LLM_API_KEY=...            # 仅本机进程环境变量，不写入仓库

# 干净检出即可校验历史排除集（只需要已获准的 UCI ZIP）
.venv/bin/python -m src.cli verify-holdout-ledger --raw-uci data/raw/default_of_credit_card_clients.zip

RUN_ID=$(.venv/bin/python -m src.cli init-run --mode uci | .venv/bin/python -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
.venv/bin/python -m src.cli check-provider --run-id "$RUN_ID"   # 失败时立即在同一 run 内重试，再继续后续步骤
.venv/bin/python -m src.cli download-uci --run-id "$RUN_ID" --expected-sha256 56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602 --approve-uci-use
.venv/bin/python -m src.cli prepare --run-id "$RUN_ID" --uci data/raw/default_of_credit_card_clients.zip --expected-sha256 56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602 --approve-uci-use
.venv/bin/python -m src.cli baseline --run-id "$RUN_ID"
.venv/bin/python -m src.cli reference-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli fixture-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli mutation-check --run-id "$RUN_ID"
.venv/bin/python -m src.cli docker-boundary --run-id "$RUN_ID"
for M in MDL_CREDIT_V1 MDL_CREDIT_V2 MDL_CREDIT_TREE; do
  .venv/bin/python -m src.cli extract-inventory --run-id "$RUN_ID" --model $M
  .venv/bin/python -m src.cli approve --run-id "$RUN_ID" --gate Gate_A --model $M --sha256 <artifact_sha256> --reviewer agent-delegated --comment '<授权来源与逐项核对内容>'
done
.venv/bin/python -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli approve --run-id "$RUN_ID" --gate Gate_B --attempt 0 --sha256 <candidate_sha256> --reviewer agent-delegated --comment '<授权来源与逐项核对内容>'
.venv/bin/python -m src.cli run-dev --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli candidate-fixtures --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli freeze --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli accept --run-id "$RUN_ID"            # 本 campaign 唯一一次正式 Holdout
.venv/bin/python -m src.cli validation-metrics --run-id "$RUN_ID"
.venv/bin/python -m src.cli agent-summary --run-id "$RUN_ID"
.venv/bin/python -m src.cli report --run-id "$RUN_ID"
.venv/bin/python -m src.cli approve --run-id "$RUN_ID" --gate Gate_C --sha256 <report/review_manifest.json 的 sha256> --reviewer agent-delegated --comment '<授权来源与逐项核对内容>'   # 与生成、状态检查同一路径
.venv/bin/python -m src.cli approve-report --run-id "$RUN_ID"
.venv/bin/python -m src.cli report-status --run-id "$RUN_ID"
.venv/bin/python -m src.cli failure-drills --run-id "$RUN_ID"
.venv/bin/python -m src.cli export --run-id "$RUN_ID"
.venv/bin/python -m src.cli acceptance --run-id "$RUN_ID"
```

开发、重试与故障演练用 `MRF_RUNS_ROOT=dev_runs` + `prepare --synthetic` 的独立 dry run（合成数据、独立账本），不触碰 `runs/` 与正式 Holdout。

## 发布状态与缺口（2026-11-09）

本轮修完 3 项发布阻断，并把"发布提交必须等于证据提交"变成可机检规则；结论是**发布仍被阻断**，原因是证据与提交不匹配且数据已耗尽。

### 已修复的 3 项阻断

| 阻断 | 问题 | 修复 | 提交 / 测试 |
| --- | --- | --- | --- |
| 逐单元格溯源 | 旧检查只问"数字是否出现在索引里"，把 Holdout 的 ROC-AUC 与 Brier 对调、索引不动、重算 manifest 哈希即可通过 | `verify_report_cells()` 用可信渲染器从 `validation_metrics.json` 重新生成 5 张表，逐格比较表头、行标签与每个单元格并报出表/行/列；接入 `report_status`、`approve --gate Gate_C`（记录审批前先校验）与 V2-07 | `492585c`，`tests/test_v2_blockers_cells.py`（5 例：对调、单格改动、改行名、删表、正常路径） |
| v2 上下文补齐 | context 只绑定 v1 资产，两个新 R 模型、三份旧文档、inventory expectations、Holdout 账本都不在 context 里 | `REPOSITORY_ASSETS` 扩到 16 项；新增 `verify-context --run-id --at <ref>` 用 `git archive` 物化标签树做只读复核，并分别报告 src/tests/资产失配 | `83e7ca6`，`tests/test_v2_blockers_context.py`（6 例，含"改受审来源→上下文失效"与"旧上下文按已发布树仍可核验"） |
| 发布与证据绑定 | 证据可以在脏工作区上生成，提交在证据之后，导致 run 与标签无法对应 | `create_run` 记录 `worktree_clean_at_init`；新增 `release-check --tag <ref> --run-id <id>`：物化标签树、在树内跑全量 pytest、复算 `verify_context`、核对 `git_commit_at_init`、acceptance 与 evidence/export 哈希，输出 APPROVED/BLOCKED + 缺口 | `src/release.py`，`tests/test_v2_blockers_release.py`（6 例） |

### 为什么仍然 BLOCKED

`release-check --tag v2` 对 seed 46 run 的输出（`dev_runs/release_check_v2.json`）：

```text
status BLOCKED
- published tests/ does not match the run's trusted_tests_sha256
- run was initialised at ec6077f…, not at the released commit 9884e3a…
- the worktree was dirty when the run was initialised, so the evidence does not belong to any commit
```

只读复核分别定位到两处不可同时满足的失配（`dev_runs/seed46_readonly_check.json`）：

| 参考提交 | src/ | tests/ | 仓库资产 | 结论 |
| --- | --- | --- | --- | --- |
| `v2`（`9884e3a`） | 一致 | **不一致**（run 之后提交了测试修正） | 一致 | 不能代表证据树 |
| `ec6077f`（`git_commit_at_init`） | 一致 | 一致 | **`config/data_config.json` 不一致**（seed 46 在 run 之后才提交） | 同上 |

即：seed 46 的证据是在**脏工作区**上生成的，任何提交都不等于它的树。按规则不能改标签去"凑"，也不能为了对齐而回退测试。

### 数据缺口（为什么不能在新提交上重跑正式验收）

`config/holdout_ledger.json` 补记 seed 46 后，5 份已消费 Holdout 全部重建校验通过（`dev_runs/holdout_coverage.json`）：

```text
30,000 - 28,801 = 1,199      # 从未消费的行
fresh_holdout_available: false
greedy_new_rows_per_campaign: seed-42 6000, seed-43 4801, seed-44 6000, seed-45 6000, seed-46 6000
```

正式验收要求 6,000 行 Holdout，剩余 1,199 行不足；本仓库不使用 1,199 行冒充正式验收，也不再换 seed。因此**在新提交上重跑 6,000 行正式 Holdout 不可行**，发布保持 BLOCKED。

### 历史证据能支持什么、不能支持什么

- **能支持**：run `v2-20261109T210903Z-3dcfab73` 自身 14 项 PASS、63 个证据文件哈希与导出 ZIP 哈希、Gate A（三份档案，含一次 REJECTED 后重新提取）/ Gate B / Gate C 的代理审核记录、单一 Holdout 与四份历史 Holdout 0 重叠、191 个数值的逐格溯源。这些是**该 run 的有效记录**。
- **不能支持**：把该 run 当作某个提交的发布证据（无法绑定）、在后续提交上宣称"已发布验收"。`v2` 标签因此不构成有效发布引用。
- **解除阻断需要**（v3 或数据授权变更时）：在干净工作区、先提交后跑证据的流程下，用**未消费数据**（重新获批的原始数据或经批准的扩展数据）产生一份 6,000 行正式 Holdout，并让 `release-check --tag <发布提交>` 返回 APPROVED。

## 已知工具缺陷

v1 记录的 4 条与首个 v2 发布发现的 2 条均已在本次修复：

1. `candidate-fixtures` FAIL 写出聚合诊断并授权下一轮修复。
2. 命令链允许同 run 内重试：失败记录全部保留，成功步绑定同一 `run_id`、冻结 attempt、Gate B 哈希与 context 哈希。注意：**被重试的步骤必须在其后续步骤之前成功**，否则链路不再“按序成功”（campaign 45 就是这样失败的，见上表）。
3. 候选/档案阶段在请求前检查 `min_candidate_output_tokens`，`finish_reason=length` 直接报截断。
4. `prepare --seed` 默认值取自 `config/data_config.json`。
5. Gate C 三处路径已统一为 `report/review_manifest.json`，`report/status` 逐项校验绑定文件；不再需要逐字节副本。
6. 历史排除集改为可重建：`config/holdout_ledger.json` + `recover_historical_splits()`，干净检出可用已获准 ZIP 重建并核对。

本轮修复：

- 报告表格改为逐单元格与指标重渲染比较（见上节），不再靠索引存在性判断。
- v2 受审来源与 `inventory_expectations`、`holdout_ledger` 已进 context；旧 run 可按标签树只读复核。
- 证据必须来自"已提交且干净"的树：`worktree_clean_at_init` 记录 + `release-check` 强制。

仍未修复（留待 v3）：

7. `context_manifest.json` 的 repository 资产清单只列 v1 资产（`legacy/credit_v1.R` 等），v2 新增的 R 资产与 `config/inventory_expectations.json`、`config/holdout_ledger.json` 不在 context 中；它们由三份档案记录的来源哈希、V2-01 校验与划分登记哈希固定。
8. Agent 档案提取有随机性：本次 V2 首次提取把“0.3/0.3 一致”记成冲突，我按实质内容 REJECTED、归档该产物并重新提取后通过；报告解释文本也会偶发与指标不符的定位性判断，本次按预置规则拒绝并重新生成，所有请求都在 `provider/request_log.jsonl`。v3 应把这类校验做成确定性门禁而不是人工判断。
9. 候选审查记录（不影响本次结果）：`--model` 在候选实现中可选并回退到与 artifact 相等的常量；十六进制字面量（如 `0x10`）被当作不可解析而拒绝，R 的 `as.numeric` 会接受。

## 退出码与验收状态

- `0`：命令执行成功且对应检查通过；`prepare --synthetic` 成功不代表正式数据通过。
- `1`：parity/验收失败；故意错误测试的内部 FAIL 是预期检出，因此 pytest 总体仍应通过。
- `2`：输入、配置、门禁或执行错误。

| 项目 | 当前状态 | 实际原因 |
| --- | --- | --- |
| V1-01 | PASS | 同 run 真实 API 能力检查 PASS：3 个请求 ID，工具往返与输出解析均 PASS，`provider/request_log.jsonl` 有对应 HTTP 记录 |
| V1-02 | PASS | `data_kind=uci`、`formal_status=APPROVED`；原始 ZIP SHA-256 `56c885f8…` 与下载记录、许可声明一致；四份划分 15000/6000/6000/3000 的磁盘哈希与分层校验通过 |
| V1-03 | PASS | `rocker/r-ver:4.4.2`、`network=none` 中 R 基准可重跑；脚本哈希与每个产物哈希齐备 |
| V1-04 | PASS | 参考 dev、参考 Holdout 与 6 个行为 fixtures parity PASS（3 逐行样例 + 3 结构性拒绝） |
| V1-05 | PASS | 隔离系数变异被固定测试检出；原模型与测试哈希前后一致 |
| V1-06 | PASS | 真实 API 候选 `906a9097…`（`generation_mode=REAL_API`）+ 代理 Gate A/B + 同 context + 冻结哈希 + Docker 开发 parity + 行为 fixtures + 一次性 Holdout PASS（6000 行、分类差异 0、`max_abs_diff` 2.22e-16） |
| V1-07 | PASS | 同 run 命令链首轮 14 步全部 exit 0 且顺序合规；`evidence_manifest.json` 43 个文件哈希与磁盘一致；`export_verified.json` 的 manifest/ZIP 哈希未过期 |

同一正式 run `v1-20261109T181929Z-3fe1c7b5` 的七项全部 PASS（`release_approved=true`），因此为对应本地提交创建了 `v1` 标签。v2 正式 run `v2-20261109T210903Z-3dcfab73` 的 14 项全部 PASS（`v1_release_approved=true`、`v2_release_approved=true`、`release_approved=true`），因此为合回 `main` 的发布提交创建了 `v2` 标签。`runs/` 与 `delivery/` 不进 Git，标签指向的是源码与文档提交；run 上下文由 `context_manifest.json` 的 `trusted_source_sha256` / `trusted_tests_sha256` 固定，tag 提交的 `src/`、`tests/`、`config/` 必须与之逐字节一致（验收后不得再改）。

### 复核 v2 正式 run

```bash
RUN=v2-20261109T210903Z-3dcfab73
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import pathlib;from src.context import verify_context;print(verify_context(pathlib.Path('.').resolve(), pathlib.Path('runs/$RUN'), '$RUN'))"   # True
cat runs/$RUN/acceptance.json | .venv/bin/python -c 'import json,sys;d=json.load(sys.stdin);print(d["release_approved"], [(r["acceptance_id"], r["status"]) for r in d["records"]])'
shasum -a 256 delivery/$RUN_evidence.zip runs/$RUN/export_verified.json   # 与 export_verified.json 的 archive_sha256 对照
.venv/bin/python -m src.cli report-status --run-id $RUN                     # status: APPROVED
git rev-parse v2^{commit}
.venv/bin/python -m src.cli verify-context --run-id $RUN --at v2            # 只读复核：src/tests/资产 分别判定
.venv/bin/python -m src.cli release-check --run-id $RUN --tag v2 --output dev_runs/release_check_v2.json   # 发布结论：当前为 BLOCKED
```

`verify_context` 覆盖 `src/`、`tests/` 与 repo 资产：发布提交一旦改动这些文件，已封存 run 的 Gate 与冻结即失效（见已知缺陷 4）。因此 v2 标签指向的提交必须与 run 的 `context_manifest.json` 逐字节一致，验收之后不再改 `src/`、`tests/`、`config/`。

## 声明与限制

- 旧 R 模型和旧文档是团队自建模拟资产；文档故意含阈值冲突和 Unknown。
- 运行数据是真实 UCI 公开数据（CC BY 4.0），已按主办方许可声明使用；它仍不代表真实客户、英国银行模型表现、独立验证或监管合规。
- 开发使用 Kimi Code CLI 辅助实现代码、测试和文档。受控 Python 参考预测器是独立编写的确定性基准，不是 Agent 自动迁移；v1 的迁移候选由真实 API 生成（`kimi-k2.7-code`，记录在 `candidate.json` 与 `agent_audit_log.jsonl`）。
- v2 的三份档案、迁移候选和报告解释均由真实网关 `deepseek-v4.1-flash:1017` 生成，分别记录在 `agent_audit_log.jsonl` 与 `provider/request_log.jsonl`；Gate A/B/C 由执行本任务的 Agent 按 SOP 7.4 以 `agent-delegated` 代理审核，审批备注写明授权来源与逐项核对内容。
- 已发布版本的模型 ID 以正式 run 的能力检查与候选生成记录为准。
- 使用 NumPy、pandas、Pydantic、pytest、xlrd、Docker、R base `glm` 与 `rpart`；v2 的指标计算只用 NumPy（未引入 scikit-learn）。Streamlit 界面留待 v3。
- 验证口径：Holdout 为同期随机留出（样本外验证）；场景 A 漂移批次为加权抽样的敏感性分析；跨时间回测在本数据上不可得，报告中列为缺失证据。公平性结果为审计信号，不构成公平性或合规结论。
- 设计主文件仍为 [docs/02_项目SOP.md](docs/02_项目SOP.md)；官方背景见 [docs/01_比赛背景与官方要求.md](docs/01_比赛背景与官方要求.md)。
