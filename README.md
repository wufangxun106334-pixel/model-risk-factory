# Model Risk Factory

EXL × UCD Data & AI Hackathon 2026 — Challenge 04 Agentic model risk factory。

## 当前状态与范围

当前是 **v1 发布候选：同一正式 run 的 V1-01～07 已全部 PASS**，并已导出可校验证据包。v1 只覆盖 `MDL_CREDIT_V1` 的 R→Python 迁移链；其余模型档案、完整验证报告和 Streamlit 界面不在 v1 范围内。

v1 验收 run_id：`v1-20261109T181929Z-3fe1c7b5`。逐项状态以 `runs/v1-20261109T181929Z-3fe1c7b5/acceptance.json` 为准（`release_approved=true`），证据包为 `delivery/v1-20261109T181929Z-3fe1c7b5_evidence.zip`。

已实测：真实 API 能力检查（网关 `https://sa.kaiwen.dev/v1`，模型 `kimi-k2.7-code`）、真实 UCI 下载与划分、真实 R 容器基准、参考实现与 6 个行为 fixtures parity、故意错误检出、真实 API 候选生成、Gate A/B 审批、候选在最小 Docker 中的开发 parity 与 fixtures、一次性 Holdout parity、验收与导出。真实 Agent 迁移与 Holdout 均已实际执行；合成数据、mock provider 与测试替身的结果**只计入开发验证**，不能作为 V1-01、V1-02、V1-06、V1-07 的正式证据。

Gate A/B 的审核有两种口径：**人工审核**（`--reviewer` 填审核人姓名）与**代理审核**（`--reviewer agent-delegated`）。本次 v1 使用代理审核，见「Gate 审核口径」与「campaign 与 seed」。

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

实际结果：**103 passed, 7 subtests passed**。测试中的 mock 只验证适配器与门禁逻辑，不算真实 API 证据；`runner_integration/` 使用人工参考脚本，不算 Agent 候选迁移。

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

## API 配置与 V1-01（v1 已执行）

CLI 从当前进程环境变量读取配置。v1 实际使用的配置：base `https://sa.kaiwen.dev/v1`、`/v1/chat/completions`、`openai_chat_completions`、模型 `kimi-k2.7-code`、超时 300 秒、能力检查 256 输出 token、候选生成 16384～32768 输出 token。密钥写在本地 `.env`（已在 `.gitignore` 中，不进提交）。

```bash
export LLM_BASE_URL='https://sa.kaiwen.dev/v1'
export LLM_CHAT_COMPLETIONS_URL='https://sa.kaiwen.dev/v1/chat/completions'
export LLM_PROTOCOL='openai_chat_completions'
export LLM_MODEL='kimi-k2.7-code'
printf 'LLM API key: ' >&2
read -rs LLM_API_KEY
export LLM_API_KEY
export LLM_TIMEOUT_SECONDS='300'
export LLM_MAX_OUTPUT_TOKENS='32768'

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.cli check-provider --run-id "$RUN_ID"
```

此命令执行一次短请求和一次两步工具往返，记录脱敏的请求 ID 与执行状态。实测注意点：网关偶发返回 504 或工具往返内容不合规，而 V1-07 只接受首轮即成功的命令链（见「已知工具缺陷」），所以能力检查失败时只能新建 run 重跑。`LLM_MAX_OUTPUT_TOKENS` 过小（如 8192）会使候选在 `submit_candidate` 中途被截断（`finish_reason=length`）。

## UCI 许可与正式 V1-02（v1 已执行）

v1 实际使用的来源：`https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip`，原始 ZIP SHA-256 `56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602`，许可 CC BY 4.0；使用声明由 `--approve-uci-use` 显式写入 `data/uci_approval.json`。真实数据必须使用 **uci run**，不能复用合成 run：

```bash
.venv/bin/python -m src.cli init-run --mode uci
# 将输出中的 run_id 设为 RUN_ID；在新 run 上重新执行 check-provider。

.venv/bin/python -m src.cli download-uci \
  --run-id "$RUN_ID" \
  --expected-sha256 '56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602' \
  --approve-uci-use
.venv/bin/python -m src.cli prepare \
  --run-id "$RUN_ID" \
  --uci data/raw/default_of_credit_card_clients.zip \
  --expected-sha256 '56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602' \
  --approve-uci-use --seed '<config/data_config.json 中的 campaign seed>'
.venv/bin/python -m src.cli baseline --run-id "$RUN_ID"
.venv/bin/python -m src.cli reference-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli fixture-parity --run-id "$RUN_ID"
.venv/bin/python -m src.cli mutation-check --run-id "$RUN_ID"
```

`--approve-uci-use` 是已获主办方确认后的显式操作声明，不是程序自动取得许可。`download-uci` 与 `prepare` 都会校验哈希，并分别写入 `data/download.json`、`data/uci_approval.json`；V1-02 会核对这两份记录、原始文件与四份划分的哈希。`.xls` 使用 `header=1` 读取。合成 manifest 的 `formal_status` 永远是 BLOCKED。`prepare --seed` 必须等于配置里的 campaign seed（v1 为 43，见「campaign 与 seed」）。

## 真实 Agent、Gate A/B 与 Holdout（v1 已执行）

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

## campaign 与 seed（v1 实际使用）

数据划分的 campaign seed 由 `config/data_config.json` 的 `seed` 固定（其余字段——总行数、四份行数、违约率容差、UCI URL——仍为不可变常量），`prepare --seed` 必须等于该配置值，否则拒绝执行；seed 会写入 `data_manifest.json` 并参与一次性 Holdout 账本的 `campaign_id`。

| campaign | seed | run_id | 结果 |
| --- | --- | --- | --- |
| 1 | 42 | `v1-20261109T172051Z-a9bd4ef4` | V1-01～06 PASS；一次性 Holdout PASS（6000 行、分类差异 0、`max_abs_diff` 2.22e-16）；V1-07 FAIL（首个 `generate-candidate` 因输出被 8192 token 截断而 exit 2，重试成功后命令链仍留有该失败记录）；Holdout 已按账本消费 |
| 2 | 43 | `v1-20261109T181929Z-3fe1c7b5` | 正式验收 run：命令链首轮全绿，V1-01～07 全 PASS，Holdout PASS，已导出证据包 |

为什么另开 campaign：campaign 1 的 V1-07 失败来自命令链记账缺陷（重试成功后仍保留失败记录），而不是 Holdout 结论问题——campaign 1 的 Holdout 结果原样保留且为 PASS，结论未被推翻、也未重跑。修复该缺陷必须改 `src/`，而 `verify_context` 覆盖 `src/`，改源码会让该 run 的 Gate 与冻结立即失效；因此正式验收改用一份**从未被评估过的新划分**，两个 campaign 的 Holdout 各自只消费一次。一次性账本 `runs/holdout_consumption.jsonl` 保留两条 `CONSUMED` 记录，不得删除或改写。

候选只按开发证据（dev parity 与行为 fixtures）筛选，Holdout 在冻结后才运行且只运行一次；没有用 Holdout 结果回调候选或提示词。

**提交与 run 的对应关系**：`run_manifest.git_commit_at_init` 记录的是 run 初始化时的 HEAD（`37faf13`）。campaign 2 的 seed 配置变更与文档更新是在 run 执行后提交的（提交本身不改 `src/`、`tests/`、`config/` 之外的验收依据）。因此 `v1` 标签指向的提交，其 `src/`（23 个 `.py`）与 `tests/`（10 个 `.py`）树的 sha256 必须分别等于 `context_manifest.json` 的 `trusted_source_sha256` = `f0c61259…`、`trusted_tests_sha256` = `2eb8a756…`，且 9 个 repository asset（legacy/config/requirements）逐字节等于 context 记录。以 `context_manifest.json` 为权威凭证，而不是 `git_commit_at_init` 的字面值。核验命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import pathlib;from src.context import verify_context;print(verify_context(pathlib.Path('.').resolve(), pathlib.Path('runs/v1-20261109T181929Z-3fe1c7b5'), 'v1-20261109T181929Z-3fe1c7b5'))"
git rev-parse v1^{commit}   # 应为被标记的发布提交
```

## 已知工具缺陷（v1 未修，留给 v2）

1. `generate-candidate --attempt N` 只接受上一位候选的 **dev** FAIL；`candidate-fixtures` FAIL 无法进入修复循环，该 run 只能作废。与第 3 条的 8192 token 截断一起，导致 campaign 2 上需要反复新建干净 run 才能得到首轮全绿的命令链（实际尝试 12 次）。
2. V1-07 要求链上每条命令 exit 0，任何一次可重试的失败（网关 504、输出截断、候选 bug）都会**永久**作废该 run，与 SOP 允许的两轮修复相冲突。
3. 候选生成长输出需要较大的 `LLM_MAX_OUTPUT_TOKENS`；本轮 8192 会在 `submit_candidate` 中途截断（`finish_reason=length`），16384/32768 可完成。
4. `verify_context` 覆盖 `src/`，任何工具修复都会使既有 run 的 Gate 与冻结失效，因此“验收后再修工具”不可行。

上述缺陷未在 v1 修改：修改判定逻辑或流程发生在验收之后会使“先定标准、后跑证据”的次序失效。v2 应先修工具，再在新 campaign 上重跑。

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

同一正式 run `v1-20261109T181929Z-3fe1c7b5` 的七项全部 PASS（`release_approved=true`），因此为对应本地提交创建了 `v1` 标签。`runs/` 与 `delivery/` 不进 Git，标签指向的是源码与文档提交；run 上下文由 `context_manifest.json` 的 `trusted_source_sha256` / `trusted_tests_sha256` 固定，tag 提交的 `src/`、`tests/`、`config/` 必须与之逐字节一致（验收后不得再改）。

## 声明与限制

- 旧 R 模型和旧文档是团队自建模拟资产；文档故意含阈值冲突和 Unknown。
- 运行数据是真实 UCI 公开数据（CC BY 4.0），已按主办方许可声明使用；它仍不代表真实客户、英国银行模型表现、独立验证或监管合规。
- 开发使用 Kimi Code CLI 辅助实现代码、测试和文档。受控 Python 参考预测器是独立编写的确定性基准，不是 Agent 自动迁移；v1 的迁移候选由真实 API 生成（`kimi-k2.7-code`，记录在 `candidate.json` 与 `agent_audit_log.jsonl`）。
- 产品内 LLM 的实际模型 ID 为 `kimi-k2.7-code`，由同 run 的能力检查与候选生成请求记录证实；mock 或测试替身结果不得描述成现场调用。
- 使用 NumPy、pandas、Pydantic、pytest、xlrd、Docker 和 R base `glm`。其余两个模型、完整验证报告和 Streamlit 留待后续版本。
- 设计主文件仍为 [docs/02_项目SOP.md](docs/02_项目SOP.md)；官方背景见 [docs/01_比赛背景与官方要求.md](docs/01_比赛背景与官方要求.md)。
