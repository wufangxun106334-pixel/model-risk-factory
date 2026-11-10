# V3-03 正式证据只读复核与 seed 47 前置核验

对应 `docs/02_项目SOP.md` §4.3 与 §14 第 8/10 步。执行人：V3 交付执行 Agent（`agent-delegated`）。
本轮只使用只读命令与 `release-check --output <run/delivery 之外的新文件>`，未写入任何 run 目录。

---

## 1. 执行的实际命令

```bash
RUN=v2-20261109T210903Z-3dcfab73          # runs/FORMAL_RUN_ID
REF=9884e3a                                # v2 标签指向的提交

.venv/bin/python -m src.cli verify-context --run-id "$RUN" --at 9884e3a
.venv/bin/python -m src.cli verify-context --run-id "$RUN" --at ec6077f
.venv/bin/python -m src.cli compare-command-log --run-id "$RUN"
.venv/bin/python -m src.cli release-check --run-id "$RUN" --tag "$REF" \
  --zip data/raw/default_of_credit_card_clients.zip --output /tmp/release_check_v2_v3.json
shasum -a 256 delivery/${RUN}_evidence.zip
```

输出保存：`docs/v3/logs/verify_context_v2_at_9884e3a.json`、`docs/v3/logs/verify_context_v2_at_ec6077f.json`、
`docs/v3/logs/compare_command_log_v2.json`、`docs/v3/logs/release_check_v2_blocked.json`。

## 2. 逐项对照结论

| 对照项 | 记录值 | 实测结论 |
| --- | --- | --- |
| run_id | `v2-20261109T210903Z-3dcfab73` | 与 `runs/FORMAL_RUN_ID` 一致 |
| `run_manifest.git_commit_at_init` | `ec6077f9d06ecce70b22d529329cfd00665b87f9` | **不等于发布提交** `9884e3a8…` |
| `worktree_clean_at_init` | 字段缺失（旧 schema） | **无法证明干净工作区** |
| `verify-context --at 9884e3a`（v2 标签） | `source_matches=true`、`asset_mismatches=[]`、**`tests_matches=false`** | FAIL（exit 1） |
| `verify-context --at ec6077f`（初始化提交） | `source_matches=true`、`tests_matches=true`、**`asset_mismatches=["config/data_config.json"]`** | FAIL（exit 1） |
| `compare-command-log` | `status=MATCH`，30 vs 30 行，同一 sha256 `d4ee54e0…`，`prefix_matches=true` | 快照未被改动；但 README 记载导出后曾把日志从 43 行截断到 30 行，缺失的 13 行不可恢复，故此 30 行只能证明"快照一致" |
| 验收项（`acceptance.json`，冻结快照） | 14 条，V1-01～07 与 V2-01～07 各一次，全部 PASS，`release_approved=true` | 该 run 自身的验收记录成立（历史证据） |
| 报告审批 | `report/approval.json`：`status=APPROVED`、`reviewer=agent-delegated`、`report_sha256=e7ebcfbc…`、`metrics_sha256=8867f11d…` | 审批记录存在且绑定当时的报告与指标 |
| 证据清单 | 61 个文件；`evidence_manifest.json` sha256 `9f5ba30f…`；`export_verified.verified=true` | 清单与磁盘一致（本轮未改动） |
| 证据 ZIP | `delivery/v2-20261109T210903Z-3dcfab73_evidence.zip` sha256 `c8670a0fccc7f82cefb7a362b6f39e91a08a349a3bfaacb74cb733ee1c0d942b` | 与 `export_verified.archive_sha256` 一致 |

## 3. `release-check` 结论：BLOCKED（exit 2）

`--output` 写在 `runs/`、`dev_runs/`、`delivery/` 与被检查 run 之外（`/tmp/release_check_v2_v3.json`，
后归档为 `docs/v3/logs/release_check_v2_blocked.json`）。

```text
status BLOCKED            (ref 9884e3a, run v2-20261109T210903Z-3dcfab73, 17 gaps)
- published tests/ does not match the run's trusted_tests_sha256
- run was initialised at ec6077f9…, not at the released commit 9884e3a8…
- the worktree was dirty when the run was initialised, so the evidence does not belong to any commit
- V1-01 (v1) … V2-07 (v2): recorded commit ec6077f9… does not match the released commit 9884e3a8…  (14 条)
```

同一命令在 9884e3a 的隔离树上跑全量测试：**182 passed, 0 failed, 0 skipped**（`new_commit_checks.tests_on_published_tree`）。
即：代码本身在发布提交上是可测的，问题只在**证据与提交不绑定**。

**判定：seed 46 的证据不可作为发布依据。** 不能通过移动标签、回退测试或改写日志去"对齐"。

## 4. 本轮新增发现（如实记录）

1. **历史报告的 Gate C 在现树上已 INVALIDATED。** 本次在 `src/report.py` 增加了
   "Key conclusions" 可信模板段，渲染器输出因此变化；对 seed 46 的历史 run 运行 `report-status` 现在返回
   `DRAFT`，原因 `report Markdown differs from the generated report` / `values index differs from the generated index` /
   `Gate_C=INVALIDATED`。这是 SOP 明示的设计行为：`src/` 变化后既有审批立即失效。影响面与处置：
   - 该 run 的证据包、`acceptance.json`、ZIP 哈希是**冻结快照**，作为历史回放仍然可核验；
   - 但任何用当前代码重跑的 `report-status` / `acceptance` 都会报 DRAFT/FAIL，**不得**用来说明"现版本下 v2 已通过"；
   - 结论不变：v2 发布仍然是 BLOCKED。
2. **`compare-command-log` 的"MATCH"不等于无损。** 它比对的是导出快照与当前日志；导入前的截断不在其可见范围内。
   因此 README 的"已知缺失 13 行"必须与本次 MATCH 结论一起读。

## 5. seed 47 正式 run 的四项前置：逐项核验

| # | 前置条件 | 可查证据 | 判定 |
| --- | --- | --- | --- |
| P1 | UCI 数据本次比赛使用的**实际授权** + 原始 ZIP 哈希 | ZIP 哈希可查：`data/raw/default_of_credit_card_clients.zip` = `56c885f8…`，与 `data_manifest.json` 的 `source.original_sha256` 一致。授权侧：`config/data_config.json` 的 `uci_competition_use_approved = **false**`；run 内 `data/uci_approval.json` 是操作者声明（`--approve-uci-use`），不是主办方书面证据；仓库内没有主办方批准文件 | **缺失**（哈希齐、授权不齐） |
| P2 | 权威账本 + 团队记录确认 `seed-47` 全局未消费 | 本机正式账本 `runs/holdout_consumption.jsonl`：seed 42–46 共 5 条 `CONSUMED`，无 seed 47 记录；`dev_runs` 账本只有 `synthetic:seed-44/45/46`。但账本不入 Git，**独立检出无记录不能证明未消费** | **需团队确认** |
| P3 | 代码、测试、配置与拟冻结材料落在确定的干净提交 | 当前 `codex/v3-final` 工作树在材料写作中仍会变更；冻结提交尚未确定 | **未达成（可在冻结时达成）** |
| P4 | 本次审批人、正式运行权限、标签策略的明确授权 | 仓库内无授权记录。另有一个待决问题：本地已存在 `v2` 标签（指向 `9884e3a`，在 release-check BLOCKED 的前提下创建），团队需明确它的处置方式 | **缺失** |

四项中 P1、P2、P4 属于**只能由团队/主办方给出**的输入；P3 可在冻结时由本分支自行达成。

## 6. 本轮结论与下一步

- `release-check` → **BLOCKED**（17 条缺口）。v2 与 v3 的正式发布都不成立。
- 因 P1/P2/P4 未齐备，**本轮不启动 seed 47 正式 run，不消费正式 Holdout**（`runs/holdout_consumption.jsonl` 无 seed 47 记录，未被本次工作改动）。
- 同时按任务要求向团队提出策略建议（不替代团队决定）：
  > 若旧 v2 证据最终无法放行，可在**拟发布的同一冻结 SHA** 上安排一次正式 run：该 run 用 seed 47 的 1,199 行 Holdout
  > 同时为 V1-01～07 与 V2-01～07 的 14 项验收提供证据，再叠加 V3 的交付与人工审核；**不拆成两次正式 run**，
  > 不换目录、不换 seed、不清账本、不重用历史 Holdout。
- 需要的人工输入、负责人与下一条可执行动作见 `docs/v3/08_handoff.md`。
