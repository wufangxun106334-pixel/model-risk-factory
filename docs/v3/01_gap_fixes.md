# V3 判定缺口：复现、最小修复与定向回归

对应 `docs/02_项目SOP.md` §4.3 与 README「已知工具缺陷」第 7 条保留给 v3 的两项判定缺口。
执行人：V3 交付执行 Agent（`agent-delegated`）。分支：`codex/v3-final`。

结论：**两个缺口在开工时都仍然存在**（缺口一在 seed 46 的正式证据里就有实例），本次均按"先复现、再最小修复、补定向回归"处理。两处修复都只收紧**判定**，不改变流程顺序、Gate 语义、重试上限、契约字段或历史证据。

---

## 缺口一：档案把相同的代码与文档阈值记成冲突

### 1.1 开工时是否仍存在：存在

`src/inventory.py::build_inventory` 只检查 `len(conflicts) >= min_conflicts`，从不检查 `conflicts` 的内容。因此只要至少有一条记录占位，任何"冲突"都能通过 Gate A。

正式证据里的实例（`runs/v2-20261109T210903Z-3dcfab73/inventories/MDL_CREDIT_V2.json`，只读引用）：

```json
{"field": "decision_threshold",
 "code": "0.3",
 "documented": "0.3",
 "detail": "Reported separately as instructed; the two values agree (code 0.3 / documented 0.3),
            so this entry records the comparison rather than a discrepancy. ..."}
```

`config/inventory_expectations.json` 冻结的 V2 阈值对是 `0.3 / 0.3`（一致），该记录却进入 `conflicts` 并被 Gate A 接受。README 记录当时靠**人工判断**把该产物 REJECTED 后重新提取——这正是缺口：判定依赖人，不依赖确定性规则。

### 1.2 最小修复（`src/inventory.py`，新增 `validate_conflicts()`）

判定全部由冻结配置与可核验来源驱动，不引入新配置字段、不改变契约：

| 规则 | 依据 | 拒绝原因示例 |
| --- | --- | --- |
| 阈值相关条目（identity 含 `threshold`）在 `code_threshold == documented_threshold` 时一律拒绝 | `inventory_expectations.json` 冻结的阈值对 | `the frozen MDL_CREDIT_V2 code and documentation thresholds are both 0.3, so they agree; equal thresholds must not be reported as a conflict` |
| 阈值确实不一致时，必须存在阈值冲突条目，且其 `code_value`/`documented_value` 与冻结对一致（容差 1e-12） | 同上 | `reported thresholds 0.35 / 0.3 do not match the frozen MDL_CREDIT_V1 pair 0.35 / 0.5` |
| 每条 `conflicts` 必须用 `field`/`kind`/`conflict` 之一命名所争议的事实 | 档案契约 `InventoryPayload.conflicts` | `Every conflict entry must name the fact it records under one of field, kind, conflict` |
| 每条 `conflicts` 必须在条目内引用至少一个 allowlisted 来源路径（R 代码或旧文档） | `expectation["sources"]` | `Conflict field:refresh_schedule cites no allowlisted source path` |
| identity 不得重复（防止用同一条finding 凑 `min_conflicts`） | `min_conflicts` | `Conflict field:input_validity_limits is recorded more than once` |

保持不变：`sources` 的路径/行号/摘录/SHA-256 校验、`feature_order`、阈值对整体校验、四项 Unknown、`min_conflicts`、Gate A 哈希口径（`review_status` 排除）、`validate_inventory` 工具行为与"最多两次校验 + 一次格式重试"的上限。

Agent 提示词同步更新（`src/agent.py::extract_inventory`），明确"一致不是冲突"、"阈值不一致时必须有数值阈值冲突"、"每条冲突要在条目里引用 allowlisted 路径"，使新 run 能在既有重试预算内满足该门禁；拒绝原因原样回灌给模型，并写入 `agent_audit_log.jsonl` 的 `OUTPUT_REJECTED` / `TOOL_CALL(status=FAIL)`。

### 1.3 定向回归（`tests/test_v3_gap_inventory_conflicts.py`，14 例）

覆盖用户要求的四类行为：

| 要求 | 用例 |
| --- | --- |
| `0.30/0.30` 不被接受为阈值冲突 | `test_equal_frozen_thresholds_are_agreement_not_a_conflict`（复刻 seed 46 的原文）、`test_equal_thresholds_are_refused_for_the_tree_model_too` |
| 真实阈值冲突仍能正确处理 | `test_a_real_threshold_conflict_is_kept_with_its_frozen_numbers`、`test_a_threshold_conflict_must_repeat_the_frozen_pair`、`test_the_frozen_threshold_disagreement_cannot_be_dropped` |
| 其他有依据的冲突仍能正确处理 | `test_other_documented_conflicts_are_still_accepted`（V1/V2/TREE 三个模型各一次）、`test_a_conflict_without_an_allowlisted_citation_is_refused`、`test_a_conflict_without_an_identity_is_refused`、`test_one_finding_cannot_be_padded_by_repeating_it` |
| 必须保留的 Unknown 仍能正确处理 | `test_unknown_fields_stay_unknown`（owner / training_date 各一次，含 `unknowns` 列表缺失） |
| 走正常生成入口并保留拒绝原因与审计 | `test_the_agent_entry_point_refuses_the_conflict_and_keeps_the_reason`（`extract_inventory` → 两次 `OUTPUT_REJECTED`、`TOOL_CALL` FAIL、无产物写出、请求数 ≤ 8） |

红/绿证据：

```text
# 修复前（仅回退 src/inventory.py 与 src/agent.py）
8 failed, 6 passed
# 修复后
14 passed
```

### 1.4 历史证据处置

不重跑、不改写 seed 46 的产物。该档案仍按历史回放引用，其上记录的那条"一致即冲突"的条目在文档中被明确标注为已知缺陷实例；本次修复只对新的 run 生效（`build_inventory` 在 CLI、`validate_inventory` 工具与最终落库三处共用同一入口）。

---

## 缺口二：Agent 摘要可能与指标方向或状态相反

### 2.1 开工时是否仍存在：存在

修复前对 `report/agent_summary.json` 的校验只有两条：禁用合规措辞清单（子串匹配）与"不得复述数字"。`AgentSummary` 是自由文本（headline/results/limitations/evidence_gaps），**没有任何一处把文本与 `validation_metrics.json` 的方向或状态做比较**；Gate C 的 `report_content_problems()` 只做哈希绑定、逐格表格比对与整篇重渲染，摘要文本内容本身不参与事实判定。README 也记录过两次"报告解释文本偶发与指标不符，靠人工拒绝后重新生成"。

### 2.2 最小修复（`src/report.py` + `src/agent.py`）

两条独立的确定性门禁：

1. **可信模板（不可被模型影响）**：报告新增 `## Key conclusions (rendered from validation_metrics.json)` 段，由 `Renderer` 直接从 `validation_metrics.json` 渲染 parity / stability / fairness 状态与"跨时间回测不可得"。数值仍全部走 `values_index.csv` 溯源；该段随整篇重渲染在 Gate C 被逐行比对，因此无法通过改文本规避。
2. **结构化事实 + 封闭枚举声明**：新增 `derive_facts(metrics)`，从指标派生
   `parity: MATCH|MISMATCH`、`stability: STABLE|ATTENTION|REVALIDATION_REQUIRED|NOT_ASSESSABLE`、
   `fairness: AUDIT_SIGNAL_ONLY`、`cross_time_backtest: UNAVAILABLE` 与 `degraded_checks`
   （`PARITY` / `STABILITY` / `FAIRNESS_LOW_SAMPLE` / `PERFORMANCE_NOT_ASSESSABLE`）。
   摘要新增必填字段 `status_claims`，由 `SummaryClaims`（严格枚举）校验，并由 `check_summary()`
   逐项与 `derive_facts` 比对；`degraded_checks` 必须与派生集合完全一致，漏报即拒绝（"缺少依据"）。
3. **相反表述短语检查**：`contradiction_problems()` 只在声明指向的**相反方向**上匹配固定短语
   （例如声明说 MATCH 时禁止 "parity fails"；声明说 STABLE 时禁止 "drift exceeds"），
   并常驻禁止"公平性已被证明"一类结论。短语表刻意收窄，避免把"discrimination is stable"
   误判成 PSI 结论。
4. **合规措辞检查改为否定感知**：`check_wording()` 原来会把"没有独立验证 / 未取得监管批准"
   这类**正确的免责表述**判成违规（本次实测中 `v2-20261109T210057Z-a715536f` 与
   `v2-20261109T210903Z-3dcfab73` 的摘要都会被误拒）。修复后按同一子句内的前置/后置否定判断，
   断言式表述仍被拒绝。

保持不变：`agent-summary` 的两轮上限（1 次格式重试）与 `agent_audit_log.jsonl` 的
`MODEL_RESPONSE` / `OUTPUT_REJECTED` / `SUMMARY_ACCEPTED` 记录；`report` 的整篇重渲染校验；
Gate C 的 `report/review_manifest.json` 绑定与 `approve-report` 流程；摘要仍不得复述数字。

### 2.3 定向回归（`tests/test_v3_gap_agent_summary.py`，20 例）

| 要求 | 用例 |
| --- | --- |
| 正确结论通过生成与审批 | `test_a_correct_summary_passes_generation_and_gate_c`（`summarize_validation` → `render_report` → `Gate_C` → `approve-report` → `report-status=APPROVED`）、`test_the_report_states_the_true_status_without_asking_the_model`、`test_derived_facts_track_the_metrics`、`test_the_generation_schema_requires_the_claims` |
| 方向/状态相反被拒 | `test_a_reversed_parity_claim_is_refused_after_the_single_retry`（指标 FAIL 而声明 MATCH；两次 `OUTPUT_REJECTED`、无产物、请求数 2）、`test_the_retry_recovers_when_the_second_answer_matches_the_metrics`、`test_reversed_prose_is_refused_even_with_correct_claims` |
| 缺少依据被拒 | `test_a_summary_without_status_claims_is_refused`、`test_a_missing_degraded_check_is_refused`、`test_an_unsupported_claim_value_is_refused`、`test_an_empty_evidence_list_is_refused_by_the_schema` |
| 错误合规表述被拒 | `test_compliance_overclaims_are_refused`（4 种断言式表述） |
| 正确免责表述不被误判 | `test_a_disclaimer_about_the_absence_of_approval_is_accepted`（3 种否定式表述） |
| 历史摘要仍可读、但不能反向通过 Gate C | `test_a_legacy_summary_without_claims_is_still_rendered`、`test_a_legacy_summary_that_contradicts_the_metrics_blocks_gate_c` |

红/绿证据：回退 `src/report.py` 与 `src/agent.py` 后该文件在导入期即失败（`check_summary` 不存在，功能缺失）；修复后 20 passed。

### 2.4 历史证据处置（实测，只读）

用新校验回放四份历史摘要：

| run | 结果 |
| --- | --- |
| `v2-20261109T210903Z-3dcfab73`（seed 46 正式 run） | PASSES（方向与状态一致，未因新增门禁而追溯失效） |
| `v2-20261109T210057Z-a715536f` | PASSES（修复否定感知后才通过；此前被误判为"independent validation"合规违规） |
| `v2-20261109T203556Z-02f3834e` | PASSES |
| `dev_runs/v2-20261109T213043Z-01a954b0` | PASSES |

即：新增门禁不追溯推翻历史证据，只对未来 run 生效。

---

## 修复后的整体测试结果

| 时点 | 结果 | 日志 |
| --- | --- | --- |
| 改动前（`d0210b6`） | 299 passed, 7 subtests passed, 0 failed, 0 skipped, exit 0, 24.03s | `docs/v3/logs/pytest_baseline_pre_fix.log` |
| 改动后（含 34 条新回归） | 333 passed, 7 subtests passed, 0 failed, 0 skipped, exit 0, 24.20s | — |
| 冻结验证第一轮（含 35 条新回归，schema 与模型约束对齐后） | 336 passed, 7 subtests passed, 0 failed, 0 skipped, exit 0, 26.17s | — |
| 最终（含 40 条新回归，措辞否定感知放宽后） | 339 passed, 7 subtests passed, 0 failed, 0 skipped, exit 0, 26.25s | `docs/v3/logs/pytest_post_fix.log` |

## 变更文件

| 文件 | 变更 |
| --- | --- |
| `src/inventory.py` | 新增 `conflict_identity()`、`conflict_threshold_values()`、`validate_conflicts()`；`build_inventory()` 调用 |
| `src/agent.py` | 档案提取提示词补充冲突契约；摘要生成改用 `check_summary(..., require_claims=True)` |
| `src/report.py` | 新增 `SummaryClaims`、`derive_facts()`、`claim_problems()`、`contradiction_problems()`、`check_summary()`；`agent_summary_schema()` 增加 `status_claims`；报告新增 Key conclusions 段；`check_wording()` 改为否定感知 |
| `tests/test_v3_gap_inventory_conflicts.py` | 新增 14 例 |
| `tests/test_v3_gap_agent_summary.py` | 新增 20 例 |
| `tests/test_v2_gates.py` | 测试夹具的冲突条目改为带 identity 与来源引用的形态（不改被验逻辑） |

---

## 附加缺陷：发给模型的 JSON Schema 没有写明模型的真实约束

**如何发现**：在冻结提交 `daef46f` 上做端到端验证演练时，`agent-summary` 连续两次被拒后失败
（run `v2-20261110T190331Z-f4d3cc49`，`docs/v3/logs/verify_frozen_*.log`）：

```text
OUTPUT_REJECTED attempt 0 :: Summary contradicts the metrics: report text says 'the model is fair';
                             fairness results are audit signals, never a proof
OUTPUT_REJECTED attempt 1 :: evidence_gaps List should have at most 8 items after validation, not 9
```

即：新门禁先正确拦下了一处"公平性已证明"的越界表述（缺口二的修复在真实模型输出上生效），
但第二次回答因为 `evidence_gaps` 给了 9 条而被 `AgentSummary` 的 `max_length=8` 拒绝，
唯一一次格式重试就此用尽，整条链路停在报告前。

**根因**：`agent_summary_schema()` 生成的 JSON Schema 只写了 `{"type": "array", "items": {"type": "string"}}`，
没有 `maxItems`/`minItems`，`headline` 也没有 `maxLength`。模型看不到真实约束，就会给出超限内容，
把重试预算耗在格式细节而不是实质错误上。

**修复**：在 `agent_summary_schema()` 中把 `AgentSummary` 的约束写进 Schema
（`headline` 1–400 字符；三个列表 1–8 项），并新增
`test_the_generation_schema_states_the_model_limits`，同时断言 pydantic 模型与 Schema 的数字一致，
防止以后再次漂移。重试上限（1 次格式重试）与审计记录不变。

这条修复没有放宽任何门禁：第一次拒绝的"the model is fair"依然会被拒。

### 追加修复：否定式免责表述被误判

冻结验证第一轮（`824981a`）的演练里，`agent-summary` 的第一次回答被拒：

```text
OUTPUT_REJECTED :: Forbidden compliance claim in report text: regulatory approval
(stating the absence of approval is fine; asserting it is not)
```

重试后通过，但说明否定判断仍偏紧：正确的免责句常在名词**之后**才出现否定
（例如 "regulatory approval was not given"），而原实现只在句子前半段的 4 个词里找否定词。
这会把一次正确表述算作违规，白白消耗唯一一次重试；在正式 run 里两次踩中就会让整轮在报告前失败。

**修复**：`_negated_after()` 增加"同句内出现否定词即视为免责"的判断（`no / not / never / without / n't / 未 / 不 / 无`），
仍然以句号为界，不允许后一句的"缺失"去豁免前一句的断言。断言式表述（无否定词）照旧被拒。
新增 3 个参数化用例（`test_a_negation_after_the_claim_is_not_an_overclaim`）。

这条修改**放宽的是措辞判断，不是事实判断**：`status_claims` 必须等于 `derive_facts()` 的硬约束不变，
"the model is fair" 类表述依然被拒。
