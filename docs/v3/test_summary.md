# V3-01 测试汇总：回归与固定数据复跑

对应 `docs/02_项目SOP.md` §4.3 V3-01。执行人：V3 交付执行 Agent（`agent-delegated`）。
本文件记录**实际运行**的测试与固定数据复跑结果；数字来源为日志与本机 run，不引用历史叙述。

| 项 | 值 |
| --- | --- |
| 分支 / 提交 | `codex/v3-final`，基于 `d0210b6`（本文件记录时的 HEAD 见 §7） |
| 主机 | macOS 27.2.1 arm64（`macOS-27.2.1-arm64-arm-64bit-Mach-O`） |
| Python | 3.15.2（`.venv`，`requirements.txt` 锁定） |
| Docker | 29.9.2 |
| R 镜像 | `rocker/r-ver:4.4.2` → `sha256:df26749182af64d5263bf64149d51a427b476ed28c4e046997143be3f97fdd7c` |
| 执行镜像 | `model-risk-factory-runner:v1` → `sha256:00e23e46b27c8aefbc1f698998d4e929b2f3bb03bbe98a222c355d9d8768ab87` |
| 容器约束 | `candidate_timeout_seconds=30`、`512m`、`1` CPU、`64` PID（`config/runtime_config.json`） |
| parity 容差 | `max_abs_diff ≤ 1e-8`、`mean_abs_diff ≤ 1e-10`、分类阈值 `p ≥ 0.35`（`config/model_config.json`） |
| 数据 | **合成**演练，campaign seed 47，train/dev/holdout/shift_pool = 15,000/6,000/**1,199**/3,000 |
| 演练 run | `dev_runs/v2-20261110T182506Z-9acb1487`（`MRF_RUNS_ROOT=dev_runs`，未触碰 `runs/` 与正式账本） |
| 演练日志 | `docs/v3/logs/drill_v3.log`（逐步命令、退出码与输出） |

---

## 1. 全量自动化测试

| 时点 | 结果 | 退出码 | 日志 |
| --- | --- | --- | --- |
| 代码变更前（`d0210b6` 树） | **299 passed**, 7 subtests passed, 0 failed, 0 skipped, 24.03s | 0 | `docs/v3/logs/pytest_baseline_pre_fix.log` |
| 两个缺口最小修复后 | **333 passed**, 7 subtests passed, 0 failed, 0 skipped, 24.20s（该次为缺口修复后首次全量）；schema 补强后 **336 passed**；措辞否定感知再放宽后 **339 passed**, 0 failed, 0 skipped, 26.25s | 0 | `docs/v3/logs/pytest_post_fix.log` |

新增 40 例即为本次两个缺口的定向回归 + schema 与模型约束一致性 + 否定式免责表述（`tests/test_v3_gap_inventory_conflicts.py` 14 例、
`tests/test_v3_gap_agent_summary.py` 24 例）。历史测试计数（103 / 287 / 296）仅作参照，不作为本次结论。

### 1.1 测试分组及其验证内容

| 组 | 用例数 | 验证什么 |
| --- | ---: | --- |
| `test_reference_parity.py` | 26 | 人工参考预测器与 R 基准的逐记录概率/分类/行为 parity；容差、ID 对齐、缺失与拒绝行为 |
| `test_v2_blockers_output_paths.py` | 31 | 只读命令的输出路径白名单（9 类受保护目标 × 2 个选项、硬链接、符号链接、父目录替换、`O_EXCL`） |
| `test_v2_blockers_release.py` | 21 | `release-check`／`acceptance` 完整性：缺项、重复、错误 run_id/提交、路径越界、伪 ZIP、成员被改、多余成员 |
| `test_v3_gap_agent_summary.py` | 24 | Agent 摘要不得与指标方向/状态相反；`status_claims` 必须等于派生事实；缺依据、错误合规表述被拒；正确免责表述通过 |
| `test_v2_blockers_gfm_rows.py` | 16 | 报告表格按 GFM 渲染语义解析（短行补空、宽行截断、转义竖线、引用块内表格） |
| `test_provider.py` | 16 | 网关适配层：请求/响应解析、重试、超时、请求上限、错误分类 |
| `test_v2_validation.py` | 15 | 四类验证指标的边界状态：缺标签、单类、分母为零、小样本、PSI 分箱与平滑 |
| `test_v2_tooling.py` | 15 | CLI 命令注册与参数契约 |
| `test_acceptance.py` | 15 | V1-01～07 判定逻辑（含"测试替身候选永不通过 V1-06"） |
| `test_v3_gap_inventory_conflicts.py` | 14 | 档案冲突的确定性判定：0.30/0.30 不是冲突、真实阈值冲突保留、有依据冲突通过、Unknown 保留、拒绝原因入审计 |
| `test_v2_blockers_readonly.py` | 14 | 只读命令不写 run 目录（字节级不变）、日志只比对不改写 |
| `test_runner.py` | 14 | 容器执行器：隔离参数、超时、越界写、输出解析 |
| `test_v2_blockers.py` | 13 | V2 首轮阻断的回归（指标输入校验、attempt 绑定、Gate C 路径统一、来源追溯、CPU 配额、干净检出取数） |
| `test_ui_data.py` | 12 | Streamlit 只读视图层：状态标签、Gate 状态、数据源区分、空状态 |
| `test_gates.py` / `test_v2_gates.py` | 17 | Gate A/B/C 顺序、哈希、失效与重审；跳步被拒 |
| `test_v2_blockers_provenance.py` | 8 | 报告数值溯源：伪路径、对调数值、篡改索引、矛盾重复行 |
| `test_v2_blockers_dataprep.py` | 8 | 历史划分从账本重建、零重叠、seed 47 的 1,199 行取数后耗尽 |
| `test_v2_report.py` | 6 | 报告渲染、数值索引、Gate C 审批与哈希失效 |
| `test_v2_blockers_context.py` | 6 | context 绑定 18 项仓库资产；`verify-context --at <ref>` 只读复核 |
| `test_v2_blockers_cells_unique.py` | 6 | 表/行身份唯一性（重复表、重复行标签被定位报出） |
| `test_v2_blockers_markdown_tables.py` / `..._cells.py` | 10 | 逐单元格与可信重渲染比较：对调、单格改动、改行名、删表 |
| `test_evidence.py` | 5 | 证据白名单导出、符号链接/FIFO 拒绝、逐行数据不出包 |
| `test_agent_security.py` | 5 | Agent 不执行候选、无数据集产物、Gate A 前不发请求、不安全诊断被拦 |
| `test_v2_blockers_gate_c.py` | 4 | 生成/审批/状态检查同路径；缺失绑定退回 DRAFT |
| `test_v2_blockers_cpu.py` | 3 | CPU 配额证据（4 进程探针 + 无配额对照） |
| `test_provider_rounds.py` / `test_download.py` | 4 | 每轮请求上限按轮而非按 run；下载前先校验许可与哈希 |

---

## 2. R / Python parity（固定资产复跑）

同一次演练 run 内的四组比较，比较口径各不相同，分开记录：

| 比较 | 比较对象 | 样本 | 最大绝对误差 | 平均绝对误差 | 分类差异 | 行为差异 | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 参考 dev parity | 人工参考预测器 vs R 基准 | 6,000 | `2.220446049250313e-16` | `2.465620300521702e-18` | 0 | 0 | PASS |
| 参考 Holdout parity | 人工参考预测器 vs R 基准 | 1,199 | `2.220446049250313e-16` | `2.060255404329419e-18` | 0 | 0 | PASS |
| 候选 dev parity | 冻结的 Agent 候选 vs R 基准 | 6,000 | `5.551115123125783e-17` | `6.938893903907229e-20` | 0 | 0 | PASS |
| **候选 Holdout parity** | 冻结的 Agent 候选 vs R 基准 | **1,199** | `5.551115123125783e-17` | `9.259574850918736e-20` | 0 | 0 | PASS |

容差：`1e-8` / `1e-10`（`config/model_config.json`），三个量级的余量。
分类口径：统一 `p ≥ 0.35`；`classification_mismatch_count` 与 `behaviour_mismatch_count` 均为 0，
即概率、分类、缺失填补标记与拒绝行为逐记录一致。
证据：`parity/reference_dev/parity_summary.json`、`parity/reference_holdout/parity_summary.json`、
`dev/attempt_000/parity_summary.json`、`holdout/parity_summary.json`。

## 3. 行为 fixtures

| 类别 | 内容 | 结果 |
| --- | --- | --- |
| 逐行行为 fixtures | 正常/缺失/非法/负账单等 11 行，`ROW_BEHAVIOUR` | PASS，`n=11`，最大与平均绝对误差 `0.0`，分类与行为差异 0 |
| 行序变化 | `row_reordered` | PASS（结果与顺序无关） |
| 列序变化 | `column_reordered` | PASS（按列名对齐） |
| 结构性拒绝 | `duplicate_ids`、`missing_column`、`empty` | PASS（R 与 Python 均以退出码 2 拒绝） |

证据：`parity/reference_fixtures/fixture_summary.json`（`contains_synthetic_fixtures_only=true`）、
`dev/attempt_000/fixtures/*/execution.json`。

## 4. 故意错误检测（mutation）

隔离副本把 `delay_1` 系数 `+= 0.001`：

| 项 | 值 |
| --- | --- |
| 变异是否被固定测试检出 | 是（`mutation_summary.status=PASS`，`original_unchanged=true`） |
| 变异后最大绝对误差 | `0.001116141636396728`（远大于 `1e-8` 容差） |
| 原始基准与测试哈希 | 前后一致 |

证据：`mutation/mutation_summary.json`、`mutation/mutant_parity_summary.json`。

## 5. 四类验证指标及各自口径

| 类别 | 指标 | 口径 | 结果（合成数据） |
| --- | --- | --- | --- |
| 等价性 | 逐记录概率/分类/行为 | 候选 vs R，见 §2 | Holdout 1,199 行全一致 |
| 性能（含校准） | ROC-AUC、Brier、十分位校准表、混淆矩阵 | 同期随机留出 Holdout，阈值 `p≥0.35` | ROC-AUC `0.6337`、Brier `0.1437`、10 组校准表、混淆矩阵（合成数据，只证明流程） |
| 稳定性 | 特征与预测 PSI | dev 固定参考分布 vs 漂移批次 A（加权抽样 2,000 行） | 预测 PSI `0.01652`，状态 `OK`（<0.10 提示线 / <0.25 复核线） |
| 公平性 | age_band、sex 的 TPR/FPR 与参考组差值 | Holdout，参考组取训练集最大组（`age_band=51+`、`sex=2`），<30 行标 `LOW_SAMPLE`，<5 正/负例不可评估 | 状态 `OK`；结果为审计信号，不构成公平性结论 |

口径边界（报告与 Deck 必须沿用）：Holdout 为**同期随机留出（样本外验证）**，漂移批次 A 为**样本构成变化的敏感性分析**，
两者都不是回测；本数据**无法做跨时间回测**，列为缺失证据。

## 6. 报告数字溯源、审核与证据导出

| 项 | 结果 | 证据 |
| --- | --- | --- |
| 数值溯源 | 196 个数值全部解析回 `validation_metrics.json` 路径，`unresolved_numbers=[]` | `report/values_index.csv`、`report/review_manifest.json` |
| 逐单元格校验 | 5 张表按可信重渲染逐格一致；表头/行身份唯一 | `report/validation_tables.md` + Gate C |
| Gate A | 3 份档案各 1 次 `APPROVED`（`agent-delegated`） | `review_log.json` |
| Gate B | 候选 64 位哈希批准 1 次（`agent-delegated`） | `review_log.json` |
| Gate C | 审批前重渲染与绑定校验通过，`approve-report` 后 `report-status=APPROVED` | `report/approval.json`、`report/report_audit.jsonl` |
| 真实网关 | 61 次请求，模型 `deepseek-v4.1-flash:1017`，工具往返 PASS | `provider/request_log.jsonl`、`provider/capability_check.json` |
| 重试与审计 | 2 次 `OUTPUT_REJECTED`（V2 档案缺冲突、一个多余字段），各在 1 次重试内恢复；无截断 | `agent_audit_log.jsonl` |
| 导出 | 61 个白名单文件；ZIP 62 条目；`verified=true` | `evidence_manifest.json`、`export_verified.json` |

### 6.1 导出后的只读复核（未使用任何写入命令）

日志：`docs/v3/logs/drill_v3_post_export_check.log`

```text
evidence_manifest entries  : 61 | on-disk hash mismatches: none
export_verified.manifest   : MATCH 513503539e43eaa68a3cd55c19de702320eb691445c4f812bcf024c485eb426f
export_verified.archive    : MATCH 2181a92d53c5f8e21a19c9796a163c64447be24704b5c4ec8a33746d1fbcbc8f
zip members                : 62 | member hash mismatches: none
acceptance statuses        : V1-01=PASS V1-02=BLOCKED V1-03..V1-07=PASS V2-01..V2-07=PASS
delivery acceptance copy   : statuses identical | differing fields: ['timestamp']
row-level files in package : none (whitelist by design)
command_log live vs snapshot: 29 vs 27 lines
```

两点如实记录：

1. `V1-02=BLOCKED` 是**预期**：`prepare --synthetic` 的 `formal_status` 永远是 `BLOCKED`，合成数据不可能满足 V1-02；因此本次演练 `release_approved=false`，不能当作发布证据。
2. 导出后 `command_log.jsonl` 比 `command_log_snapshot.jsonl` 多 2 行（`export`、`acceptance`）。`acceptance` 必须晚于 `export`（V1-07 要读 `export_verified.json`），而两者都会记入命令日志，所以这是合规链路的**必然状态**，`compare-command-log` 报 `prefix_matches=true` + `extra_commands=[export, acceptance]`。**不得为对齐而截断日志**（seed 46 的截断即造成不可恢复的证据缺失）。

## 7. 与历史证据的对比（仅参照，不可 1:1 比较）

| 项 | 历史（seed 46，`v2-20261109T210903Z-3dcfab73`） | 本次（seed 47 合成演练） | 说明 |
| --- | --- | --- | --- |
| dev parity 最大误差 | `2.220e-16` | `2.221e-16`（参考）/ `5.551e-17`（候选） | 不同数据集，数值量级一致（浮点表示误差） |
| Holdout 行数 | 6,000 | 1,199 | seed 47 起口径变更 |
| 变异检出最大误差 | `0.001187376493456127` | `0.001116141636396728` | 变异系数相同，输入数据不同 |
| 报告数值条目 | 191 | 196 | 新增 Key conclusions 段的索引项 |
| 环境 | 原执行机 | 本机 | 容器镜像 digest 已记录 |

历史与正式的 UCI 数字一律标为**历史回放**；本次为**合成演练**。

## 8. 本轮结论与限制

- 全量测试 0 失败、0 跳过，退出码 0；两个缺口的定向回归在修复前红、修复后绿。
- 固定资产（R 基准、参考实现、行为 fixtures、变异检测、容器镜像与约束）在同一 run 内复跑一致，误差在 `config/model_config.json` 容差内三个量级以上余量。
- 本次为**合成数据**演练：指标只证明流程与数值一致性，**不代表模型表现**，也不构成 V1-02 的正式通过。
- LLM 文本不要求逐字相同；本次的事实、数值引用与结论已由 `check_summary` 与 Key conclusions 模板逐项校验。
