# 冻结提交的只读复核记录

本文件记录对**冻结提交**执行的只读验证：全量测试、干净树端到端演练、`verify-context`、界面复核。
所有命令都是只读或写入独立演练目录（`dev_runs/`，未触碰 `runs/` 与正式账本）。

---

## 1. 冻结与交付提交

| 项 | 值 |
| --- | --- |
| 代码冻结提交 | `e298d23c3e14fd56f272c1edb29dc71a7ef5bf5e`（`codex/v3-final`） |
| 该提交包含 | 两个判定缺口的最小修复、schema/措辞的两处补充修复、40 条定向回归、全部 `docs/v3/` 验收材料与 `materials/` 五件套 |
| 冻结时工作区 | 干净（`git status --short` 为空） |
| 交付提交 | 包含本文件的提交；相对 `e298d23` 只追加了 `docs/v3/ui_screens/` 的冻结代码截图、由这些截图重建的 `materials/solution_deck.{pptx,pdf}`，以及本记录 |
| 未变更项 | `src/`、`tests/`、`config/`、`requirements*.txt` 在 `e298d23` 之后**不再改动** |

交付提交与 `e298d23` 的差异必须只有上述文档与二进制材料；可用下面这条命令核对：

```bash
git diff --stat e298d23..HEAD
```

## 2. 冻结提交上的全量测试

在**独立干净工作树** `/tmp/mrf-v3-freeze`（`git worktree add <path> e298d23`，检出时 `git status` 为空）
用全新 venv 的同一套锁定依赖执行：

```text
339 passed, 9 warnings, 7 subtests passed in 24.88s      exit code 0
```

日志：`docs/v3/logs/pytest_frozen_sha.log`。

## 3. 冻结提交上的端到端演练（绑定该 SHA）

| 项 | 值 |
| --- | --- |
| 命令 | `bash docs/v3/drill_v3.sh dev_runs`（`MRF_RUNS_ROOT=dev_runs`，日志重定向到 `/tmp` 以保持工作树干净） |
| run_id | `v2-20261110T191501Z-fed1c652` |
| `run_manifest.git_commit_at_init` | `e298d23c3e14fd56f272c1edb29dc71a7ef5bf5e` |
| `run_manifest.worktree_clean_at_init` | **`true`**（首次做到"冻结提交 + 干净树 + 完整链路"） |
| 步骤数 / 退出码 | 29 步全部 `exit 0`（check-provider → prepare → baseline → reference-parity → fixture-parity → mutation-check → docker-boundary → 3×（extract-inventory + Gate A）→ generate-candidate → show-candidate → Gate B → run-dev → candidate-fixtures → freeze → accept → validation-metrics → agent-summary → report → Gate C → approve-report → report-status → failure-drills → **export** → acceptance） |
| 数据 | synthetic，seed 47，train/dev/holdout/shift_pool = 15,000/6,000/1,199/3,000 |
| 网关 | 真实 `deepseek-v4.1-flash:1017` |
| 验收 | V1-02 `BLOCKED`（合成数据永不能满足正式口径，符合设计），其余 13 项 `PASS`；`release_approved=false` |
| 导出 | 61 个白名单文件、ZIP 62 条目、`verified=true`，archive sha256 `8cd2a8048cbd64d1…` |

日志：`docs/v3/logs/drill_v3_frozen_sha.log`。

### 3.1 `verify-context`（关键结果）

```bash
python -m src.cli verify-context --run-id v2-20261110T191501Z-fed1c652 --at e298d23
```

```json
{"asset_count": 25, "asset_mismatches": [], "missing_assets": [], "ref": "e298d23",
 "run_id": "v2-20261110T191501Z-fed1c652", "source_matches": true,
 "status": "PASS", "tests_matches": true, "verified": true}
```

即：**该 run 的 `src/`、`tests/` 与 25 项仓库资产，和冻结提交的树逐字节一致**。
这是 seed 46 历史证据做不到的事情（当时 `verify-context` 在任何提交上都 FAIL）。

## 4. 冻结提交上的界面复核

用冻结工作树的代码启动 `streamlit run app.py`（端口 8602），对 run
`v2-20261110T191501Z-fed1c652` 逐页实测，并在截图前确认页面标题：

| 页面 | 截图前的标题校验 | 截图 |
| --- | --- | --- |
| 1 · Inventory | `heading "Model inventory"` 命中 | `docs/v3/ui_screens/01_inventory.png` |
| 2 · Model detail | `heading "Model detail` 命中 | `docs/v3/ui_screens/02_model_detail.png` |
| 3 · Migration | `heading "Migration of` 命中 | `docs/v3/ui_screens/03_migration.png` |
| 4 · Validation report | `heading "Validation report` 命中 | `docs/v3/ui_screens/04_validation_report.png` |

运行状态徽标实测为 `SYNTHETIC · REPLAY · ACCEPTANCE NOT PASSED · COMMIT e298d23c3e14`，
其中 commit 与该 run 的初始化提交一致。

## 5. 冻结验证过程中发现并修复的两个缺陷（如实记录）

| # | 现象 | 根因 | 修复 | 结果 |
| --- | --- | --- | --- | --- |
| 1 | 首轮冻结验证演练（`daef46f`，run `v2-20261110T190331Z-f4d3cc49`）在 `agent-summary` 连续两次被拒后失败 | 发给模型的 JSON Schema 未写 `maxItems`/`maxLength`，模型给出 9 条 `evidence_gaps`，被 pydantic 的 `max_length=8` 拒绝，唯一一次格式重试被耗尽 | `agent_summary_schema()` 写入真实约束（headline 1–400；三个列表 1–8），并加测试把 Schema 与模型绑定 | `824981a` |
| 2 | 第二轮（`824981a`，run `v2-20261110T190917Z-56b93dd3`）演练中，一次**正确的免责表述**被判成合规违规 | 否定判断只在句子前半段 4 个词里找否定词，"regulatory approval was not given" 这类后置否定被误拒 | `_negated_after()` 改为同句任意位置出现否定词即视为免责（仍以句号为界） | `e298d23` |

两处修复都**没有放宽事实判定**：第一次被拒的 "the model is fair" 仍然被拒；`status_claims` 必须等于
`derive_facts()` 的硬约束不变。修复后全量测试 339 passed。

## 6. 残留风险（未修复，交接给正式 run 的操作者）

**措辞短语检查仍可能误拒不常见的正确表述。** 在两次冻结验证演练中，`agent-summary` 各有一次被
`Forbidden compliance claim` 拦下（一次是 "regulatory approval" 出现在没有否定词的子句里），
重试后都通过。影响与处置：

- 影响：只消耗 `agent-summary` 阶段的**唯一一次格式重试**；该阶段在 Holdout 之后，但**不消费 Holdout**。
- 处置：若正式 run 中 `agent-summary` 失败，允许在同一 run 内重跑
  `python -m src.cli agent-summary --run-id <run>`（记录会留在 `command_log.jsonl` 与
  `agent_audit_log.jsonl`），且必须在 `report` / Gate C / `export` 之前成功。**不得**放宽措辞检查、不得改写审计日志。
- 长期：把短语清单换成结构化事实驱动的措辞模板（本次已把关键结论做成模板，剩余是 LLM 自由文本部分）。

## 7. 结论

| 项 | 结果 |
| --- | --- |
| 冻结提交上全量测试 | 339 passed / 0 failed / 0 skipped / exit 0 |
| 冻结提交 + 干净树的端到端演练 | 29/29 步 exit 0，export 后只读复核通过 |
| `verify-context --at e298d23` | **PASS**（src/tests/25 项资产逐字节一致） |
| 四页界面 | 四页标题与徽标实测一致，截图已更新到冻结代码 |
| 现有正式证据的 `release-check` | **BLOCKED**（17 条缺口，`docs/v3/03_release_readiness.md`） |
| seed 47 正式 run | **未启动**，正式 Holdout 未消费 |
| `v3` 标签 | **未创建** |

V3-06 因此为 `BLOCKED`：冻结提交与材料已就绪且可复核，但"验收通过后创建 v3 标签"的前提
（正式 run 的 `release-check` = APPROVED、A/B 互审签署、评委访问与视频）尚未满足。

### 1.1 交付提交上的复核（记录本文件时的实测）

交付提交（含本文件的提交）上重跑只读复核，用于确认"材料变更不影响证据绑定"：

```text
python -m src.cli verify-context --run-id v2-20261110T191501Z-fed1c652 --at <交付提交>
  -> {"asset_count": 25, "asset_mismatches": [], "source_matches": true,
      "tests_matches": true, "status": "PASS", "verified": true}

python -m pytest -q
  -> 339 passed, 7 subtests passed, 0 failed, 0 skipped, exit code 0
```

原因：`verify_context` 只绑定 `src/`、`tests/` 与 25 项仓库资产，`docs/` 与 `materials/` 不参与；
所以冻结 run 同时可由 `e298d23` 与交付提交验证通过，而交付提交相对 `e298d23` 只改文档与 deck 二进制
（`git diff --stat e298d23..<交付提交>` 中不含 `src/`、`tests/`、`config/`）。
