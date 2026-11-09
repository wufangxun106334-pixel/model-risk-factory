# Model Risk Factory

EXL × UCD Data & AI Hackathon 2026 — Challenge 04 Agentic model risk factory。

## 当前状态与范围

当前是 **v1 开发原型，尚未通过 v1 发布验收**。本轮只实现 `MDL_CREDIT_V1` 的 R 逻辑回归迁移链与 CLI；其余模型档案、完整验证报告和 Streamlit 界面不在 v1 范围内。

已实测：合成数据加工、真实 R 容器基准、独立 Python 参考预测、逐记录 parity、故意错误检测、人工参考脚本的受限 Docker 集成、验收判定与证据导出的全部阻断/通过路径。**未实测：真实 API、真实 Agent 候选、用户 Gate A/B、真实候选开发执行与 Holdout。** 正式 UCI 数据许可未确认，因此未下载或使用 UCI 数据。

本轮开发 run_id：`v1-20261109T160955Z-c4e69c96`。逐项状态以 `runs/v1-20261109T160955Z-c4e69c96/acceptance.json` 为准；当前 `release_approved=false`，未创建 `v1` 标签。

合成数据、mock provider、测试替身与人工参考脚本的结果**只计入开发验证**，不能作为 V1-01、V1-02、V1-06、V1-07 的正式证据。

## 环境与准备（实际执行）

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker pull rocker/r-ver:4.4.2
docker build -t model-risk-factory-runner:v1 docker
```

实测环境：Python 3.15.2、Docker 29.9.2（macOS arm64）；宿主无 `Rscript`，R 4.4.2 使用 `rocker/r-ver:4.4.2` 容器实际运行。镜像摘要：R `sha256:df26749182af64d5263bf64149d51a427b476ed28c4e046997143be3f97fdd7c`，候选运行镜像 `sha256:00e23e46b27c8aefbc1f698998d4e929b2f3bb03bbe98a222c355d9d8768ab87`。依赖版本与镜像实测记录见运行目录的 `environment.json`。

## 已实际运行的本地 CLI

```bash
RUN_ID=v1-20261109T160955Z-c4e69c96
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli init-run --mode synthetic
# 新 run 由 init-run 生成；下面命令均在该 run 上执行，stdout 重定向到 runs/$RUN_ID/cli_output/。

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli check-provider --run-id "$RUN_ID"
# 实际退出码 2：当前 shell 未设置网关配置和密钥；未发请求，状态 BLOCKED。

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli prepare --run-id "$RUN_ID" --synthetic --seed 42
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli baseline --run-id "$RUN_ID"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli reference-parity --run-id "$RUN_ID"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli fixture-parity --run-id "$RUN_ID"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli mutation-check --run-id "$RUN_ID"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli acceptance --run-id "$RUN_ID"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli export --run-id "$RUN_ID"
```

实际退出码依次为 `2, 0, 0, 0, 0, 0, 0, 0`（第 1 条是 `check-provider`）。**`export` 会封印该 run**：它写入 `evidence_manifest.json`、`export_verified.json`、证据 ZIP 与最终 `acceptance.json`。封印后不要再向运行目录写文件，否则 manifest 哈希会失配。

固定测试实际命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

实际结果：**104 passed, 7 subtests passed**。测试中的 mock 只验证适配器与门禁逻辑，不算真实 API 证据；`runner_integration/` 使用人工参考脚本，不算 Agent 候选迁移。

新一轮开发可创建独立 run：

```bash
.venv/bin/python -m src.cli init-run --mode synthetic
```

## 实测结果

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

## 需要你处理：API 配置与 V1-01

CLI 从当前进程环境变量读取配置。密钥请通过终端静默输入。先在 `sa.kaiwen.dev` 控制台确认实际协议、完整请求端点和模型 ID，再对新建的 run 执行能力检查。

```bash
export LLM_BASE_URL='https://sa.kaiwen.dev'
export LLM_CHAT_COMPLETIONS_URL='<实际完整 chat completions 端点>'
export LLM_PROTOCOL='<实际协议；当前适配器仅实现 openai_chat_completions>'
export LLM_MODEL='<实际模型 ID>'
printf 'LLM API key: ' >&2
read -rs LLM_API_KEY
export LLM_API_KEY
printf '\n' >&2
export LLM_TIMEOUT_SECONDS='60'
export LLM_MAX_OUTPUT_TOKENS='<已核实的输出上限>'

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli check-provider --run-id "$RUN_ID"
```

此命令执行一次短请求和一次两步工具往返，记录脱敏的请求 ID 与执行状态。通过能力检查后才能进入 Agent 阶段。切换供应商须先确认。

## 需要你处理：UCI 许可与正式 V1-02

主办方确认前不要执行下列真实数据命令。确认可用于比赛后，从可信来源取得预期 SHA-256，并**新建 uci run**，不要复用合成 run：

```bash
.venv/bin/python -m src.cli init-run --mode uci
# 将输出中的 run_id 设为 RUN_ID；在新 run 上重新执行 check-provider。

.venv/bin/python -m src.cli download-uci \
  --run-id "$RUN_ID" \
  --expected-sha256 '<可信来源的原始 ZIP SHA-256>' \
  --approve-uci-use
.venv/bin/python -m src.cli prepare \
  --run-id "$RUN_ID" \
  --uci data/raw/default_of_credit_card_clients.zip \
  --expected-sha256 '<同一 SHA-256>' \
  --approve-uci-use --seed 42
.venv/bin/python -m src.cli baseline --run-id "$RUN_ID"
.venv/bin/python -m src.cli reference-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli fixture-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli mutation-check --run-id "$RUN_ID"
```

`--approve-uci-use` 是你已获主办方确认后的显式操作声明，不是程序自动取得许可。`download-uci` 与 `prepare` 都会校验哈希，并分别写入 `data/download.json`、`data/uci_approval.json`；V1-02 会核对这两份记录、原始文件与四份划分的哈希。`.xls` 使用 `header=1` 读取。合成 manifest 的 `formal_status` 永远是 BLOCKED。

## 真实 Agent、Gate A/B 与 Holdout（本轮未执行）

前置条件：同一 run 的 `check-provider` 为 PASS，R 基准已完成，且你已决定数据路径。下列命令不是本轮实测结果。

### 1. 档案与 Gate A

```bash
.venv/bin/python -m src.cli extract-inventory --run-id "$RUN_ID"
.venv/bin/python -m src.cli status --run-id "$RUN_ID"
```

审阅 `model_inventory.json` 的来源行/摘录、Unknown、0.35 代码阈值与 0.50 文档冲突。`status` 会输出完整审批命令。Gate A 哈希是档案内容（排除随审核变化的 `review_status`）的规范 JSON SHA-256；只有你执行：

```bash
.venv/bin/python -m src.cli approve \
  --run-id "$RUN_ID" --gate Gate_A \
  --sha256 '<status 显示的档案哈希>' \
  --reviewer '<你的姓名>' --comment '已核对来源、Unknown 与阈值冲突'
```

### 2. 真实候选、diff 与 Gate B

Gate A 批准后才允许真实 API 生成：

```bash
.venv/bin/python -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 0
.venv/bin/python -m src.cli show-candidate --run-id "$RUN_ID" --attempt 0
```

审阅完整 diff、源码与哈希。候选此时未执行。只有你执行 Gate B：

```bash
.venv/bin/python -m src.cli approve \
  --run-id "$RUN_ID" --gate Gate_B --attempt 0 \
  --sha256 '<candidate.json 中的 candidate_sha256>' \
  --reviewer '<你的姓名>' --comment '已审阅候选 diff 与哈希'
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

## 退出码与验收状态

- `0`：命令执行成功且对应检查通过；`prepare --synthetic` 成功不代表正式数据通过。
- `1`：parity/验收失败；故意错误测试的内部 FAIL 是预期检出，因此 pytest 总体仍应通过。
- `2`：输入、配置、门禁或执行错误。

| 项目 | 当前状态 | 实际原因 |
| --- | --- | --- |
| V1-01 | BLOCKED | 当前 shell 缺少网关配置和密钥；真实请求与工具往返待运行 |
| V1-02 | BLOCKED | 合成划分契约通过；UCI 比赛许可未确认，`download.json`/`uci_approval.json` 尚未产生 |
| V1-03 | PASS | MDL_CREDIT_V1 真实 R 容器基准及产物哈希有效；范围为合成开发数据 |
| V1-04 | PASS | 参考 dev/Holdout 与 6 个行为 fixtures parity 通过；不是 Agent 候选结果 |
| V1-05 | PASS | 隔离系数变异被固定测试检出，原基准/测试哈希前后一致 |
| V1-06 | BLOCKED | 无真实 API 档案/候选，无用户 Gate A/B，无真实候选 Holdout |
| V1-07 | BLOCKED | 同一 run 的本地链与导出已校验，但真实迁移链不存在（`check-provider` 未 PASS） |

全部七项 PASS 前不会创建 `v1` 标签。

## 声明与限制

- 旧 R 模型和旧文档是团队自建模拟资产；文档故意含阈值冲突和 Unknown。
- 当前运行数据与 fixtures 均为合成开发数据，不代表真实客户、英国银行模型表现、独立验证或监管合规。
- 开发使用 Kimi Code CLI 辅助实现代码、测试和文档。受控 Python 参考预测器是独立编写的确定性基准，不是 Agent 自动迁移；本轮没有生成真实迁移候选。
- 产品内 LLM 的实际模型 ID 当前为 Unknown，因为真实 API 尚未验证；不得把 mock 或回放描述成现场调用。
- 使用 NumPy、pandas、Pydantic、pytest、xlrd、Docker 和 R base `glm`。其余两个模型、完整验证报告和 Streamlit 留待后续版本。
- 设计主文件仍为 [docs/02_项目SOP.md](docs/02_项目SOP.md)；官方背景见 [docs/01_比赛背景与官方要求.md](docs/01_比赛背景与官方要求.md)。
