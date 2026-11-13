# Seed 47 正式 run 记录（v3 证据）

记录日期：2026-11-12。执行与审核：fangxunwu（25208508），单人操作，见 [最终审核](06_final_review.md) §3 披露。

## 最终交付口径（11-13，A 决定）

**「V3 候选已交付，最终验收 BLOCKED」**，附全部真实结果与缺陷说明（按 [发布清单](07_release_checklist.md) §6）。不创建 `v3` 标签，不把事后复核写成发布放行。

## 结论

**正式 run 已完成，Holdout 已单次消费。14 项验收中 13 项 PASS，V1-07 FAIL；`release-check` 为 BLOCKED，`v3` 标签未创建。** UCI 已无剩余的独立 Holdout，无法再做一次正式 run。

| 项 | 值 |
| --- | --- |
| run_id | `v2-20261112T150753Z-7b6cc549`（本机 `runs/`，不入库） |
| 冻结提交 | `21c323578f041a71342ee804038dc6d08db4a4c8`（初始化时工作区干净） |
| 数据 | UCI，campaign seed 47；train/dev/holdout/shift_pool = 15,000/6,000/**1,199**/3,000，另有 4,801 行不使用 |
| Gate A（3 份档案） | APPROVED，reviewer `fangxunwu`，在 UI 中人工审核（V1 有一次重复提交，两条记录绑定同一哈希） |
| Gate B | attempt 0（`40f668e0…`）与 attempt 1（`ba64963c…`）均由 `fangxunwu` 批准；**冻结 attempt 1** |
| Gate C | APPROVED（`fcc4b6b5…`），reviewer `fangxunwu` |
| 导出 | `delivery/v2-20261112T150753Z-7b6cc549_evidence.zip`（SHA-256 前缀 `660a91ab`），本机，不入库 |
| `release-check` | **BLOCKED**，2 条缺口均来自 V1-07：[logs/release_check_v3_seed47.json](logs/release_check_v3_seed47.json) |

## 正式指标（真实 UCI 数据，seed 47）

| 指标 | 结果 |
| --- | --- |
| Parity（R 对 Python） | dev 6,000 行最大差值 2.78e-16；**holdout 1,199 行最大差值 2.22e-16**；分类与行为差异均为 0 |
| ROC-AUC / Brier | dev 0.7461 / 0.1405；**holdout 0.6988 / 0.1506**（1,199 行，264 个违约）；shifted 0.7634 / 0.1432 |
| 混淆矩阵（holdout，阈值 0.35） | TP 95、FN 169、FP 95、TN 840 |
| 漂移 PSI（dev 对 shifted 场景 A） | 6 项全部 OK；最大 `util_1` 0.0611，预测 0.0187 |
| 公平性（参考组 age 26–35、sex=2） | age 21–25 TPR 0.474 对 0.340；age 51+ 仅 83 行；sex=1 TPR 0.340 对 0.372。为审计信号，不是公平性结论 |

Holdout 只有 1,199 行，置信区间较宽；holdout AUC 低于历史 6,000 行 run 的 0.753，应按小样本解读。

## 过程中的事件（全部留在 `command_log.jsonl`，未删除或改写）

1. `baseline` 首次失败：Docker Desktop 未运行。随后在同一 run 内重试时，`rocker/r-ver:4.4.2` 镜像需要重新下载，R 容器超时；第三次通过。
2. `docker-boundary` 首次失败：本机缺 `model-risk-factory-runner:v1` 镜像，按 README 重建后通过（8/8）。
3. attempt 0 的 `run-dev` 失败：间隔约 7.5 小时后 Docker 再次退出，候选代码未实际执行；同一 attempt 不允许重跑。经 A 决定使用修复名额生成 attempt 1，A 重新审批 Gate B，之后开发测试、fixtures、冻结、Holdout 全部通过。

## V1-07 为什么 FAIL

`src/acceptance.py::_command_chain` 对每一步只取日志中**第一次成功**的记录，再要求它属于冻结的 attempt。本 run 中 attempt 0 的 `generate-candidate` 和 Gate B 审批都成功了（只是其 `run-dev` 因 Docker 失败），检查器因此拿 attempt 0 的记录比对冻结的 attempt 1，判为 FAIL。SOP 允许「初始生成 + 最多两轮修复」，所以这是检查器对合法修复路径的误判。判定发生在冻结提交的代码上，按规则不能用修改后的代码为本 run 改判。

**11-13 已修复（A 明确授权）。** `src/acceptance.py` 新增 `_superseded_attempt`：编号低于冻结 attempt 的成功记录视为已被替代的修复历史，保留为证据但不参与判定；冻结 attempt 自身缺步、或出现比冻结 attempt 更晚的 attempt，仍然报错。新增 3 项回归测试（`tests/test_v2_tooling.py`）。

**修复只对之后的 run 生效，不改变本 run 的判定。** 只读事后复核：用修复后的检查器对本 run 计算命令链，结果为 0 个问题，run 目录逐字节不变。这只说明 D-01 是 V1-07 失败的唯一原因，**不构成发布放行**；本 run 的 `release-check` 仍以冻结提交 `21c3235` 为准，结论为 BLOCKED。

## 已知缺陷（新增）

| 编号 | 缺陷 | 影响 |
| --- | --- | --- |
| D-01 | `_command_chain` 取第一次成功记录，合法修复后会误判 V1-07 | 本 run 的 V1-07 FAIL 和 `release-check` BLOCKED。**11-13 已修复**，只对之后的 run 生效 |
| D-02 | `src/baseline.py` 在 R 容器超时时把 `TimeoutExpired.stdout`（bytes）当作 str 写文件，报 `data must be str, not bytes` | 超时被报成异常，不写 `r_stdout.txt`；不影响本 run 的最终结果 |
