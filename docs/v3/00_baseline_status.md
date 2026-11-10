# V3 基线状态记录（一页）

记录时间：2026-11-10（V3 开工时实测）
记录人：V3 交付执行 Agent（`agent-delegated`）
工作分支：`codex/v3-final`（从 `main` `d0210b6` 切出，未改动 `main`、未移动任何标签）

本文件是 V3 的**状态基准**。所有结论来自本次实测命令输出，不引自 README / SOP 的历史叙述。
后续每条 V3 验收记录以 `docs/v3/` 下各文件的 `evidence_path` 为准。

---

## 1. 工作区与 Git

| 项 | 实测值 | 命令 |
| --- | --- | --- |
| 起点分支 / HEAD | `main` / `d0210b6` | `git rev-parse --short HEAD` |
| 工作区 | 干净（`## main...origin/main` 无改动） | `git status --short --branch` |
| 远端 `main` | `d0210b6a770d40c0f5e4e41dfe3f6e781d8a0c5f` | `git ls-remote --heads origin` |
| 远端其他分支 | `docs/consolidate-uci-data` `02289b90d8` | 同上 |
| 远端标签 | **无任何标签**（`git ls-remote --tags origin` 输出为空，退出码 0） | `git ls-remote --tags origin` |
| 本地标签 | `v1`（附注标签对象 `555b090` → 提交 `70858cd`）、`v2`（附注标签对象 `f4108f3` → 提交 `9884e3a`） | `git for-each-ref refs/tags` |

### 1.1 标签指向的更正（重要）

启动线索写「本地 `v2` 标签指向 `9884e3a`」。**按提交口径该说法成立**，需澄清的是 `git rev-parse v2` 返回的是附注标签**对象** SHA：

```text
v1  tag  object=555b090  ->  commit=70858cd   created 2026-11-09T18:27:06Z
v2  tag  object=f4108f3  ->  commit=9884e3a   created 2026-11-09T21:17:16Z
```

- `v1^{commit}` = `70858cd`（v1 正式 run `v1-20261109T181929Z-3fe1c7b5` 的发布提交）。
- `v2^{commit}` = `9884e3a`（`fix(v2): verify metrics inputs, unify Gate C, …`），与 README / `dev_runs/release_check_v2.json` 使用的历史发布校验目标一致。
- 两个标签都是 `main` 的祖先。

### 1.2 README / SOP 的过期陈述（本次实测推翻）

| 文档陈述 | 实测 |
| --- | --- |
| README 与 SOP §4.2.1：「本地和 `origin` 均**未发现 `v2` 标签**」「没有任何标签，`v1` 也不在其中」 | **不成立**：本地 `v1`、`v2` 两个附注标签均存在，创建于 2026-11-09。远端确实没有任何标签。 |
| SOP §4.2.1 / §16.6：「`v1` 标签只存在于创建者本机，或尚未推送」 | 前半句成立（本地有、远端无）；`v1` 的推送仍是未完成动作。 |
| README 开头：「Streamlit 界面按计划留给 v3」 | **不成立**：`app.py`（380 行）、`src/ui_data.py`、`src/ui_charts.py`、`requirements-ui.txt` 已在 `d0210b6` 提交。 |
| README「合成开发验证记录」：「当前 v1 测试结果为 103 passed」 | 过期计数，实际计数以 `docs/v3/test_summary.md` 为准。 |

`v2` 标签在 `release-check` 返回 `BLOCKED` 的情况下已被创建，违反 SOP §4.2「`release-check` 返回 `APPROVED` 后创建标签」。**本次不移动、不覆盖、不强推该标签**，只如实记录，并把处置方式列为交接项。

---

## 2. run 事实（正式 run 与关键历史 run）

只列有 `acceptance.json` 或与发布相关的 run；`runs/` 下共 38 个目录，其余为中途作废的调试 run。

| run_id | mode | `git_commit_at_init` | `worktree_clean_at_init` | 验收 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `v1-20261109T181929Z-3fe1c7b5` | uci | `37faf134` | 字段不存在（旧 schema） | 7/7 PASS，`release_approved=true` | v1 正式 run（campaign seed 43），`v1` 标签的依据 |
| `v2-20261109T203556Z-02f3834e` | uci | `25df8641` | 字段不存在 | 14/14 PASS | v2 首轮（seed 44），复盘发现阻断，仅历史回放 |
| `v2-20261109T210057Z-a715536f` | uci | `ec6077f9` | 字段不存在 | 13/14 PASS，V1-07 FAIL | v2 修复后重跑（seed 45），命令链非按序成功，保留为失败证据 |
| `v2-20261109T210903Z-3dcfab73` | uci | `ec6077f9` | **字段不存在** | 14/14 PASS，`release_approved=true` | 台账所称 v2 正式 run（seed 46）；发布校验 BLOCKED |

`runs/FORMAL_RUN_ID` = `v2-20261109T210903Z-3dcfab73`；`runs/FORMAL_V2B_RUN_ID` = `v2-20261109T210057Z-a715536f`。

### 2.1 seed 46 正式 run 的两个不可调和失配（本次实测）

`verify-context` 只读复核，两条路径不能同时满足：

| 参考提交 | `src/` | `tests/` | 18 项仓库资产 | `status` |
| --- | --- | --- | --- | --- |
| `9884e3a`（`v2` 标签 / 历史发布校验目标） | 一致 | **不一致** | 一致 | `FAIL` |
| `ec6077f`（`git_commit_at_init`） | 一致 | 一致 | **`config/data_config.json` 不一致** | `FAIL` |

命令：`python -m src.cli verify-context --run-id v2-20261109T210903Z-3dcfab73 --at <ref>`

结论：该 run 的证据树不等于任何提交的树；`run_manifest.json` 没有 `worktree_clean_at_init` 字段，**无法证明干净工作区**。这与 README 的记载一致，本次独立复现。

### 2.2 命令日志

```text
compare-command-log  status=MATCH  live_lines=30  snapshot_lines=30
live_sha256 = snapshot_sha256 = d4ee54e05385ffaeeb0ff4ca850a0a7a2e7052317e509b8f51a0b9fa0c89e7d9
```

实时日志与导出快照逐字节相同。README 已记录「2026-11-09 曾把该日志从 43 行截断到 30 行，被删的 13 行不可恢复」。因此这 30 行只能证明「导出时的快照未被改动」，不能证明导出后未再执行验证命令。

### 2.3 交付包

| 项 | 值 |
| --- | --- |
| `delivery/v2-20261109T210903Z-3dcfab73_evidence.zip` sha256 | `c8670a0fccc7f82cefb7a362b6f39e91a08a349a3bfaacb74cb733ee1c0d942b` |
| `export_verified.json` `archive_sha256` | 同上，一致 |
| `export_verified.json` `verified` / `file_count` | `true` / 63 |
| `delivery/…_acceptance.json` | `release_approved=true`，14 条记录 |

---

## 3. 正式 Holdout 账本

权威文件：`runs/holdout_consumption.jsonl`（本机正式账本，不入 Git）。

| campaign | seed | status | run_id |
| --- | --- | --- | --- |
| `MDL_CREDIT_V1:uci:seed-42` | 42 | CONSUMED | `v1-20261109T172051Z-a9bd4ef4` |
| `MDL_CREDIT_V1:uci:seed-43` | 43 | CONSUMED | `v1-20261109T181929Z-3fe1c7b5` |
| `MDL_CREDIT_V1:uci:seed-44` | 44 | CONSUMED | `v2-20261109T203556Z-02f3834e` |
| `MDL_CREDIT_V1:uci:seed-45` | 45 | CONSUMED | `v2-20261109T210057Z-a715536f` |
| `MDL_CREDIT_V1:uci:seed-46` | 46 | CONSUMED | `v2-20261109T210903Z-3dcfab73` |
| `MDL_CREDIT_V1:uci:seed-47` | 47 | **无记录（未消费）** | — |

`dev_runs/holdout_consumption.jsonl` 是独立账本，只含 synthetic campaign（seed 44/45/46），不影响正式账本；`synthetic:seed-47` 仍可用。

**边界说明**：本机看到的 5 条正式记录不能证明「全局未消费」——账本不入 Git，独立检出没有账本记录不能作为未消费的证据。seed 47 的全局状态需团队按权威记录确认（见交接项 H-02）。

`data/raw/default_of_credit_card_clients.zip` 本机存在，sha256 `56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602`，与 README / `data_manifest.json` 的 `source.original_sha256` 一致。

---

## 4. 配置口径

| 项 | 值 |
| --- | --- |
| `config/data_config.json` `seed` | `47` |
| `split_sizes` | train 15,000 / dev 6,000 / holdout **1,199** / shift_pool 3,000（合计 25,199，另有 4,801 行未使用） |
| `uci_competition_use_approved` | **`false`**（配置标记不是批准；`--approve-uci-use` 只记录已知批准） |
| `shift_scenario_a` | rows 2,000，seed 47 |
| 历史口径 | seed 42–46 用 `LEGACY_SPLIT_SIZES`（holdout 6,000 行）从账本重建校验 |

---

## 5. 发布校验的历史结论

`dev_runs/release_check_v2.json`（原运行环境记录，本次未重跑）：

```text
status BLOCKED
- published tests/ does not match the run's trusted_tests_sha256
- run was initialised at ec6077f…, not at the released commit 9884e3a…
- the worktree was dirty when the run was initialised, so the evidence does not belong to any commit
- V1-01 … V2-07 (14 条) recorded commit ec6077f… does not match the released commit 9884e3a…
```

本次 `verify-context` 两条路径均 `FAIL`，与该结论一致。`release-check` 的当轮重算见 `docs/v3/release_checklist.md`。

---

## 6. 四类状态分类

### 6.1 当前可实测（本次可实际运行并产出证据）

| 项 | 说明 |
| --- | --- |
| 全量 `pytest -q` | 本地 `.venv`（Python 3.15.2）可跑 |
| 合成演练全流程 | `MRF_RUNS_ROOT=dev_runs` + `prepare --synthetic`，synthetic seed 47 未消费 |
| R 基准 / parity / fixtures / mutation / Docker 边界 | 需 Docker Desktop + `rocker/r-ver:4.4.2` + `model-risk-factory-runner:v1` |
| Streamlit 四页 | `app.py` 已提交，可用 `dev_runs` 或 `runs` 作为数据源 |
| 只读复核 | `verify-context`、`compare-command-log`、`release-check`、`report-status`、`verify-holdout-ledger` |
| 真实网关 Agent 流程 | 依赖 `LLM_API_KEY`；不可用时按 REPLAY 标注 |

### 6.2 历史回放（只读引用，不重跑）

| 项 | 原因 |
| --- | --- |
| seed 42–46 的全部 Holdout 结果 | 已消费，禁止重跑 |
| `v2-20261109T210903Z-3dcfab73` 的 14 项 PASS | 证据树不匹配任何提交，不可作为发布依据 |
| `v1-20261109T181929Z-3fe1c7b5` 的 7 项 PASS | `v1` 标签的依据；本次不重跑 |
| seed 46 命令日志 30 行 | 已被截断，缺失 13 行不可恢复 |

### 6.3 待人工确认（本 Agent 无权限）

| ID | 事项 |
| --- | --- |
| H-01 | UCI 数据本次比赛使用的**实际授权证据**（配置里 `uci_competition_use_approved=false`） |
| H-02 | 权威账本 + 团队记录确认 `seed-47` 全局未消费 |
| H-03 | 正式 run 的审批人、正式运行权限、标签策略（含已存在的 `v2` 标签如何处置） |
| H-04 | 团队是否接受「在同一冻结 SHA 上跑一次正式 run，同时为 v2 的 14 项与 V3 交付提供证据」 |
| H-05 | A/B 两名成员互审（V3-05）的签字人、时间与决定 |
| H-06 | 私有仓库与视频对评委的可访问权限；提交邮件发件人 / 截止时间 / 递交要求 |
| H-07 | 真实网关凭据（`LLM_API_KEY`）与录屏条件 |

### 6.4 发布阻断（当前确定成立）

| ID | 阻断 | 判定依据 |
| --- | --- | --- |
| B-01 | seed 46 证据不可用于发布 | `verify-context` 对 `9884e3a` 与 `ec6077f` 均 `FAIL`；无 `worktree_clean_at_init` |
| B-02 | 无 `v2` 正式放行 | `release-check` 17 条缺口；`v2` 标签被提前创建但未放行 |
| B-03 | seed 47 正式 run 四项前置未齐备（H-01～H-04） | 见 §6.3 |
| B-04 | 既有 UCI 数据只剩 1,199 行 | `30,000 − 28,801 = 1,199`；seed 47 用完即无独立 Holdout |

---

## 7. 下一步

按 `docs/02_项目SOP.md` §4.3 顺序推进：变更前测试基线 → 两个判定缺口复现与最小修复 → V3-01/02/03 → 五件套 → 审核材料 → 条件性正式发布 → 交接。
