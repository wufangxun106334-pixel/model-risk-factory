# Model Risk Factory

EXL × UCD Data & AI Hackathon 2026 — Challenge 04 Agentic model risk factory。

**v1 与 v2 均已完成本地验收。** CLI 将团队自建的信用违约模型 `MDL_CREDIT_V1` 从 R 迁移到 Python，对照 R 基准逐记录验证预测概率、分类和异常处理；v2 补齐另外两个旧模型的档案、容器边界实测、四类验证指标、三道审核门禁、端到端导出与报告数值溯源。

- v1 正式 run `v1-20261109T181929Z-3fe1c7b5`：V1-01～07 全 PASS（Gate A/B 代理审核），标签 `v1`。
- v2 正式 run **`v2-20261109T203556Z-02f3834e`**：V1-01～07 与 V2-01～07 共 14 项全 PASS，`release_approved=true`，Gate A（三份档案）/ Gate B / Gate C 均为 `agent-delegated` 代理审核，标签 `v2`。

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
| v2 | 44 | `v2-20261109T203556Z-02f3834e` | v2 正式验收 run：14 项（V1-01～07 + V2-01～07）全 PASS，Holdout 与两次 v1 Holdout 重叠 0 行，报告 APPROVED，已导出证据包 |

campaign 1 的 Holdout 通过，V1-07 因命令链把首轮生成失败计入验收而失败。正式验收用 seed 43 对同一 UCI 数据集重新划分。两套 Holdout 各有 6,000 条记录，其中 1,199 条重叠。每套划分各执行一次正式 Holdout，两次结果及账本中的 `CONSUMED` 记录均已保留。

候选只按开发证据（dev parity 与行为 fixtures）筛选，Holdout 在冻结后才运行且只运行一次；没有用 Holdout 结果回调候选或提示词。

**提交与 run 的对应关系**：`run_manifest.git_commit_at_init` 记录的是 run 初始化时的 HEAD（`37faf13`）。campaign 2 的 seed 配置变更与文档更新是在 run 执行后提交的（提交本身不改 `src/`、`tests/`、`config/` 之外的验收依据）。因此 `v1` 标签指向的提交，其 `src/`（23 个 `.py`）与 `tests/`（10 个 `.py`）树的 sha256 必须分别等于 `context_manifest.json` 的 `trusted_source_sha256` = `f0c61259…`、`trusted_tests_sha256` = `2eb8a756…`，且 9 个 repository asset（legacy/config/requirements）逐字节等于 context 记录。以 `context_manifest.json` 为权威凭证，而不是 `git_commit_at_init` 的字面值。核验命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import pathlib;from src.context import verify_context;print(verify_context(pathlib.Path('.').resolve(), pathlib.Path('runs/v1-20261109T181929Z-3fe1c7b5'), 'v1-20261109T181929Z-3fe1c7b5'))"
git rev-parse v1^{commit}   # 应为被标记的发布提交
```

## v2 正式验收（run `v2-20261109T203556Z-02f3834e`）

v2 在 `main`（基线 `c848f14`）上新建分支 `v2/formal`，先修工具、后跑证据，再合回 `main` 并打 `v2` 标签。数据划分在正式 run 之前冻结：`config/data_config.json` 的 campaign seed 44，Holdout 只从**历史已消费 Holdout 未覆盖的行**中抽取（`holdout_exclusion`），因此与 v1 的两次正式 Holdout 重叠 **0 行**（记录在 `data/data_manifest.json` 的 `holdout_exclusion.overlap`）。

| 项 | 结果 | 证据（`runs/v2-20261109T203556Z-02f3834e/`） |
| --- | --- | --- |
| V2-01 三模型建档 | PASS：三份档案 Schema/来源/哈希通过，Gate A 逐份 `agent-delegated`；V1 保留 0.35 与 0.50 的阈值矛盾与 7 条代码/文档差异，V2/TREE 各 4 条；owner 与 training_date 保持 Unknown | `model_inventory.json`、`inventories/MDL_CREDIT_V2.json`、`inventories/MDL_CREDIT_TREE.json`、`review_log.json` |
| V2-02 容器边界 | PASS：7 项实跑检查（只读根与输入、无宿主/基准挂载、容器内无 API key、内存、CPU、PID、超时）；`--memory-swap` 与 `--memory` 同值 | `boundary/boundary_report.json`（含每个探针的原始 payload） |
| V2-03 四类验证 | PASS：parity 2.22e-16（dev/holdout 各 6000 行、0 分类差异）、holdout ROC-AUC 0.7463 / Brier 0.1417、十分位校准表、场景 A 漂移 PSI（最大 0.0814 < 0.10 提示线）、age_band 与 sex 的 TPR/FPR 与参考组差异 | `validation_metrics.json`、`report/validation_tables.md`、`validation/shifted_manifest.json` |
| V2-04 三道审核 | PASS：Gate A → 生成候选 → Gate B → 容器执行 → Gate C → 报告 APPROVED 的顺序与哈希全部核对；跳过审批、篡改、上下文失效的阻断由 `tests/test_v2_gates.py` 覆盖 | `review_log.json`、`report/approval.json` |
| V2-05 端到端 | PASS：同一 run 内 CLI 走通建档→迁移→开发验证→冻结→Holdout→指标→报告→审核，导出 MD/CSV/JSON，`run_id` 与证据哈希一致 | `evidence_manifest.json`（63 个文件）、`export_verified.json` |
| V2-06 故障处理 | PASS：真实 404、真实 1 ms 超时、真实 8 次请求上限、真实非 JSON 解析失败 + 一次格式重试，以及本地注入的修复耗尽，全部保留错误原文 | `failures/failure_drills.json`、`failures/drills/*.json` |
| V2-07 报告溯源 | PASS：报告 191 个数值全部由程序按 JSON path 渲染，索引可逐行解析（0 未解析）；Agent 只收到脱敏汇总且不重述数字；报告区分同期留出、漂移敏感性分析、缺失的跨时间回测，无合规措辞 | `report/validation_report.md`、`report/values_index.csv`、`report/agent_summary.json` |

正式 Holdout 只执行一次：冻结后 `accept` 在 `holdout.csv`（6000 行，sha256 `5ecf7d0e…`）上运行，parity PASS 后账本写入 `runs/holdout_consumption.jsonl` 的 `MDL_CREDIT_V1:uci:seed-44` 记录，未重跑、未换 seed。

### v2 正式 run 的实际命令（按执行顺序）

```bash
export LLM_BASE_URL=https://sa.kaiwen.dev
export LLM_CHAT_COMPLETIONS_URL=https://sa.kaiwen.dev/v1/chat/completions
export LLM_PROTOCOL=openai_chat_completions
export LLM_MODEL=deepseek-v4.1-flash:1017
export LLM_TIMEOUT_SECONDS=300
export LLM_MAX_OUTPUT_TOKENS=32768
export LLM_API_KEY=...            # 仅本机进程环境变量，不写入仓库
RUN_ID=$(.venv/bin/python -m src.cli init-run --mode uci | .venv/bin/python -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
.venv/bin/python -m src.cli check-provider --run-id "$RUN_ID"
.venv/bin/python -m src.cli download-uci --run-id "$RUN_ID" --expected-sha256 56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602 --approve-uci-use
.venv/bin/python -m src.cli prepare --run-id "$RUN_ID" --uci data/raw/default_of_credit_card_clients.zip --expected-sha256 56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602 --approve-uci-use
.venv/bin/python -m src.cli baseline --run-id "$RUN_ID"
.venv/bin/python -m src.cli reference-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli fixture-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli mutation-check --run-id "$RUN_ID"
.venv/bin/python -m src.cli docker-boundary --run-id "$RUN_ID"
for M in MDL_CREDIT_V1 MDL_CREDIT_V2 MDL_CREDIT_TREE; do
  .venv/bin/python -m src.cli extract-inventory --run-id "$RUN_ID" --model $M
  # 审阅完整档案、复核来源哈希与行号后逐份签署 Gate A
  .venv/bin/python -m src.cli approve --run-id "$RUN_ID" --gate Gate_A --model $M --sha256 <artifact_sha256> --reviewer agent-delegated --comment '<授权来源与逐项核对内容>'
done
.venv/bin/python -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 0
# 实读全部候选源码、核对 64 位哈希后签署 Gate B
.venv/bin/python -m src.cli approve --run-id "$RUN_ID" --gate Gate_B --attempt 0 --sha256 <candidate_sha256> --reviewer agent-delegated --comment '<授权来源与逐项核对内容>'
.venv/bin/python -m src.cli run-dev --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli candidate-fixtures --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli freeze --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli accept --run-id "$RUN_ID"          # 唯一一次正式 Holdout
.venv/bin/python -m src.cli validation-metrics --run-id "$RUN_ID"
.venv/bin/python -m src.cli agent-summary --run-id "$RUN_ID"
.venv/bin/python -m src.cli report --run-id "$RUN_ID"
# 复核报告、指标与 191 行数值索引后签署 Gate C（见下方缺陷 5）
.venv/bin/python -m src.cli approve --run-id "$RUN_ID" --gate Gate_C --sha256 <report_review_sha256> --reviewer agent-delegated --comment '<授权来源与逐项核对内容>'
.venv/bin/python -m src.cli approve-report --run-id "$RUN_ID"
.venv/bin/python -m src.cli failure-drills --run-id "$RUN_ID"
.venv/bin/python -m src.cli export --run-id "$RUN_ID"
.venv/bin/python -m src.cli acceptance --run-id "$RUN_ID"
```

开发与重试用 `MRF_RUNS_ROOT=dev_runs` + `prepare --synthetic` 的独立 dry run（合成数据，独立账本），不触碰 `runs/` 与正式 Holdout。

## 已知工具缺陷

v1 记录的 4 条缺陷已在 v2 修复（`tests/test_v2_tooling.py` 覆盖）：

1. `candidate-fixtures` FAIL 现在写出聚合诊断（`dev/attempt_NNN/fixture_diagnostics.json`）并授权下一轮修复；development FAIL 仍优先。
2. 命令链改为"同 run 内允许重试"：每一步允许先失败后成功，失败记录全部保留，成功步必须绑定同一 `run_id`、正确的冻结 attempt、Gate B 批准的哈希与当前 context 哈希。
3. 候选/档案阶段在发送请求前检查 `min_candidate_output_tokens`（16384），并把 `finish_reason=length` 直接报为截断错误。
4. `prepare --seed` 默认值改为读取 `config/data_config.json`，不再硬编码 42。

v2 自身新发现、**未在本次 sealed run 内修复**的缺陷（按"先定标准、后跑证据"的次序保留）：

5. `approve --gate Gate_C` 把 Gate C 产物路径写死为 `report/report_review.json`，而 `report_status` 读取的是 `report/review_manifest.json`。正式 run 用**逐字节相同**的副本（sha256 `c9e0c881…`）满足该路径，审批摘要因此在 `review_log.json` 中显式记录了这条工具 caveat 与副本哈希；修复属于 v3 范围，因为改动 `src/` 会使已封存 run 的 context 失效（缺陷 4 的同一机制）。
6. `context_manifest.json` 的 repository 资产清单仍只列 v1 资产（`legacy/credit_v1.R` 等），v2 新增的 R 资产与配置文件不在 context 中；它们由三份档案记录的来源哈希与 V2-01 校验固定。v3 应把 v2 资产并入 context 清单。

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

同一正式 run `v1-20261109T181929Z-3fe1c7b5` 的七项全部 PASS（`release_approved=true`），因此为对应本地提交创建了 `v1` 标签。v2 正式 run `v2-20261109T203556Z-02f3834e` 的 14 项全部 PASS（`v1_release_approved=true`、`v2_release_approved=true`、`release_approved=true`），因此为合回 `main` 的发布提交创建了 `v2` 标签。`runs/` 与 `delivery/` 不进 Git，标签指向的是源码与文档提交；run 上下文由 `context_manifest.json` 的 `trusted_source_sha256` / `trusted_tests_sha256` 固定，tag 提交的 `src/`、`tests/`、`config/` 必须与之逐字节一致（验收后不得再改）。

### 复核 v2 正式 run

```bash
RUN=v2-20261109T203556Z-02f3834e
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import pathlib;from src.context import verify_context;print(verify_context(pathlib.Path('.').resolve(), pathlib.Path('runs/$RUN'), '$RUN'))"   # True
cat runs/$RUN/acceptance.json | .venv/bin/python -c 'import json,sys;d=json.load(sys.stdin);print(d["release_approved"], [(r["acceptance_id"], r["status"]) for r in d["records"]])'
shasum -a 256 delivery/$RUN_evidence.zip runs/$RUN/export_verified.json   # 与 export_verified.json 的 archive_sha256 对照
.venv/bin/python -m src.cli report-status --run-id $RUN                     # status: APPROVED
git rev-parse v2^{commit}                                                   # 应为被标记的发布提交
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
