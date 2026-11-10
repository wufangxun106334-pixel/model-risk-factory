# V3-02 新环境复现记录

对应 `docs/02_项目SOP.md` §4.3 V3-02。执行人：V3 交付执行 Agent（`agent-delegated`）。
所有数字来自本次实际运行；日志与截图路径附在每条结论后面。

---

## 1. 干净检出与全新虚拟环境

| 项 | 值 |
| --- | --- |
| 检出方式 | `git worktree add /tmp/mrf-v3-clean 6f33b2c`（独立工作树，无未提交改动、无本地缓存与 runs/） |
| 检出提交 | `6f33b2c`（两处缺口修复 + 测试）；界面徽标提交 `7157295` 在主工作树验证，见 §5 |
| 工作树状态 | 检出时 `git status --short` 为空 |
| Python | 3.15.2（`/opt/homebrew/bin/python3`，与主环境同版本） |
| 虚拟环境 | `python3 -m venv .venv`（全新，未复用主环境） |
| 依赖安装 | `pip install -r requirements.txt` → exit 0；`pip install -r requirements-ui.txt` → exit 0 |
| 安装包数 | 43（`pip freeze`，含 streamlit 及其传递依赖） |
| 关键版本 | numpy 2.5.4、pandas 3.1.1、pydantic 2.14.3、pytest 9.2.0、xlrd 2.0.2、streamlit 1.67.0（全部等于锁定值） |
| Docker | 29.9.2（`docker version --format {{.Server.Version}}`，exit 0） |
| R 镜像 | `rocker/r-ver:4.4.2` → `sha256:df26749182af64d5263bf64149d51a427b476ed28c4e046997143be3f97fdd7c` |
| 执行镜像 | `model-risk-factory-runner:v1` → `sha256:00e23e46b27c8aefbc1f698998d4e929b2f3bb03bbe98a222c355d9d8768ab87` |
| 宿主机 Rscript | 无（R 只在容器内运行，与 README 口径一致） |
| 平台 | macOS 27.2.1 arm64（`macOS-27.2.1-arm64-arm-64bit-Mach-O`） |

`git ls-files data` 为空：原始数据与处理产物按设计不入 Git。因此新检出默认没有
`data/raw/default_of_credit_card_clients.zip`，这一点直接决定了下面两组测试结果。

## 2. 新环境全量测试

| 场景 | 命令 | 结果 | 退出码 |
| --- | --- | --- | --- |
| 干净检出（无原始 UCI ZIP，默认状态） | `.venv/bin/python -m pytest -q` | **325 passed, 8 skipped, 7 subtests passed**, 14.12s | 0 |
| 放入已获准 ZIP 后（`data/raw/` 由 gitignore 忽略，工作树仍干净） | `.venv/bin/python -m pytest -q` | **333 passed, 0 skipped, 7 subtests passed**, 26.08s | 0 |

8 个跳过全部来自 `tests/test_v2_blockers_dataprep.py`，跳过原因原样为
`approved UCI ZIP is not on this machine` —— 这些用例要用获准 ZIP 重建五份历史划分并逐字节校验。
这与 `release-check` 的做法一致：它在隔离标签树里先用账本哈希校验并复制本机已获准 ZIP，再跑全量测试，
并把 skip 计为发布缺口。放入 ZIP 后 333 项全通过、0 跳过，与主工作树结果一致。

日志：`docs/v3/logs/pytest_clean_env_without_uci.log`、`docs/v3/logs/pytest_clean_env_with_uci.log`；
依赖清单：`docs/v3/logs/pip_freeze_clean_env.txt`（42 行）。
ZIP 哈希：`56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602`（与 `data_manifest.json`
的 `source.original_sha256` 一致）。

## 3. 新环境端到端合成演练

命令：`bash docs/v3/drill_v3.sh dev_runs`（`MRF_RUNS_ROOT=dev_runs`，独立于 `runs/`；合成数据；
`export` 为链路最后一步；随后 `acceptance` 读取其产物）。

| 项 | 值 |
| --- | --- |
| run_id | `v2-20261110T183352Z-5e6a48b0` |
| 数据 | synthetic，campaign seed 47，train/dev/holdout/shift_pool = 15,000/6,000/1,199/3,000 |
| 步骤 | check-provider → prepare → baseline → reference-parity → fixture-parity → mutation-check → docker-boundary → 3×（extract-inventory → Gate A）→ generate-candidate → show-candidate → Gate B → run-dev → candidate-fixtures → freeze → accept → validation-metrics → agent-summary → report → Gate C → approve-report → report-status → failure-drills → **export** → acceptance |
| 退出码 | 全部 0（逐步记录见 `docs/v3/logs/` 的演练日志） |
| 真实网关 | 全部 Agent 阶段走真实网关，模型 `deepseek-v4.1-flash:1017`（`provider/request_log.jsonl`、`capability_check.json`） |
| 审核 | Gate A ×3、Gate B、Gate C 均 `agent-delegated` / `APPROVED`（`review_log.json`） |
| 验收 | 14 条：V1-01/03/04/05/06/07 PASS，**V1-02 BLOCKED**（合成数据永不满足正式口径），V2-01～07 PASS |
| 导出 | 61 个白名单文件，ZIP 62 条目，`verified=true` |

`V1-02 BLOCKED` 与 `release_approved=false` 是合成演练的**正确**结果：它证明正式口径没有被合成数据绕过。

## 4. 跨环境数值一致性（同一 seed、同一配置、同一镜像）

| 指标 | 主环境 `v2-20261110T182506Z-9acb1487` | 新环境 `v2-20261110T183352Z-5e6a48b0` | 判定 |
| --- | --- | --- | --- |
| R 基准系数 / 中位数 / 阈值 | 见 `reference/model.json` | 逐值相同 | **完全一致** |
| 参考实现 dev parity 最大/平均误差 | `2.220446049250313e-16` / `2.465620300521702e-18` | 完全相同 | **完全一致** |
| 候选 dev parity 最大/平均误差 | `5.551115123125783e-17` / `6.938893903907229e-20` | `2.220446049250313e-16` / `9.617306950815418e-18` | 同为浮点末位量级，均在容差内 |
| 候选 Holdout parity 最大/平均误差 | `5.551115123125783e-17` / `9.259574850918736e-20` | `2.220446049250313e-16` / `1.0671660015683844e-17` | 同上 |
| 分类差异 / 行为差异 | 0 / 0 | 0 / 0 | **完全一致** |
| Holdout ROC-AUC | `0.6336784831912945` | 同值 | **完全一致** |
| Holdout Brier | `0.14371775107390594` | 同值 | **完全一致** |
| 预测 PSI | `0.016520262818532888` | 同值 | **完全一致** |
| 变异检出最大误差 | `0.001116141636396728` | 同值 | **完全一致** |
| 合成数据文件哈希（holdout） | `98dfb52bb5d6e6ca…` | 同值 | **完全一致** |
| 验收结论 | 14 条，V1-02 BLOCKED | 同 | **完全一致** |

候选 parity 的末位差异有确定原因：两次运行的候选代码由网关**重新生成**，不是同一个程序
（`6d6e41c378f0…` 380 行 vs `f83b821349e5…` 416 行）。R 模型、参考实现与所有判定级指标完全一致，
说明差异来自候选实现的浮点求和顺序，而不是环境或数据漂移；两者都比 `1e-8` / `1e-10` 容差低 8～10 个量级。
结论按 SOP 口径表述为**在声明容差内可复现**，不声称逐位可复现。

## 5. Streamlit 四页实测

启动方式与 README 一致：`.venv/bin/streamlit run app.py`（`--server.headless true`，本机端口
8599 为新环境、8601 为主环境）。健康检查 `/_stcore/health` 返回 200，首页返回 200。

| 页面 | 实际验证的内容 | 证据 |
| --- | --- | --- |
| 1 · Inventory | 三个模型清单（scope/inventory/Gate A/sources/conflicts/unknowns）、Run history（含 mode、commit、worktree clean、release_approved）、Pipeline steps 按钮 | `docs/v3/ui_screens/01_inventory.png` |
| 2 · Model detail | `Gate A: ✅ APPROVED`、代码阈值 0.35 vs 文档阈值 0.5、Owner/Training date = Unknown、特征顺序、Conflicts 表、Unknowns 表 | `docs/v3/ui_screens/02_model_detail.png` |
| 3 · Migration | Gate A 状态、attempt 选择、候选源码（含 Gate A 冲突处置说明）、完整 64 位候选哈希、Gate B 审批表单（Reviewer/Decision/Comment）、Docker 执行按钮 | `docs/v3/ui_screens/03_migration.png` |
| 4 · Validation report | ROC-AUC/Brier 指标卡（dev 0.6750 / holdout 0.6337 / shifted 0.6627，与 `validation_metrics.json` 一致）、校准表、混淆矩阵、PSI、公平性图与来源表、`Gate C: ✅ APPROVED`、报告与数值索引下载 | `docs/v3/ui_screens/04_validation_report.png` |

其他实测项：

| 项 | 结果 |
| --- | --- |
| 空状态 | 把 Runs root 切到 `runs`（新检出里不存在该目录）→ 页面显示 `No runs under runs/`，不报错（`docs/v3/ui_screens/empty_state_snapshot.txt`） |
| 状态标签区分 | 每个 run 顶部显示 `数据类别 | REPLAY/LIVE | 验收状态 | COMMIT`：合成演练显示 `SYNTHETIC · REPLAY · ACCEPTANCE NOT PASSED · COMMIT d0210b6a770d`；正式 seed 46 run 显示 `UCI · REPLAY · ACCEPTANCE PASSED · COMMIT ec6077f9d06e` |
| LIVE 判定 | 在 UI 里对新建的合成 run 执行 `prepare` 后，同一 run 的徽标变为 `SYNTHETIC · LIVE`；刷新页面后回到 `REPLAY`，不会凭空宣称实时结果 |
| 验收 vs 发布 | 徽标文案只写 `ACCEPTANCE PASSED / NOT PASSED`，页面另有说明「正式发布还需 `release-check` → APPROVED」，避免把 run 的验收当成发布放行 |
| UI 遵守 CLI 门禁 | 在 Gate A 仍为 `NOT_RUN` 的 run 上点「Generate candidate attempt 0」→ CLI 返回 **exit code 2** 与错误 JSON，UI 不绕过门禁 |
| 图表与来源表 | 迁移页 parity 散点图、报告页指标卡/校准/混淆矩阵/PSI/公平性图均有配套数据表（`Data table` 展开区） |

## 6. 已知限制与如实说明

1. 本轮未录制视频样片：截图与实时界面用于 Deck 与录制准备；成片属于待人工完成的交付项（见交接项）。
2. 演练全部为**合成数据**：`V1-02 BLOCKED` 是设计结果，不能作为正式证据。
3. 新环境演练运行在提交 `6f33b2c`；界面徽标改动为 `7157295`，在冻结提交上会再跑一次
   「全量测试 + 四页界面」复核（见 `docs/v3/release_checklist.md` 的最终验证条目）。
4. 新环境的工作树在演练时因写入 `docs/v3/logs/` 而不干净，因此该合成 run 的
   `worktree_clean_at_init=false`；正式 run 必须从干净树创建，`release-check` 会强制这一点。
