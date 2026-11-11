# V3 优化计划

> 状态（2026-11-11）：已收敛并执行能在无授权下完成的部分，见文末「执行记录」。
> 下面「实测现状」是草稿时的快照，其中演练一条已被更正。

## Context

V3 交付候选已经推到 `main`，但正式验收是 **BLOCKED**：V3-01/03/04/05/06 五项都没过，
只有 V3-02（新环境复现）是 PASS。`v3` 标签未创建，`release-check` 对旧证据返回 17 条缺口。
比赛截止 2026-11-13，评分权重 Business Impact 30% / Technical 25% / Innovation 20% / RAI 15% / Presentation 10%。

"优化 v3" 可能指四种完全不同的目标，所需动作差别很大：

| 目标 | 判据 | 谁来判定 |
| --- | --- | --- |
| A 提分 | 按 §7 权重表逐项加分的材料/证据 | 评委 |
| B 解除阻塞拿 `v3` 标签 | `release-check` APPROVED + 6 条验收全 PASS | 仓库门禁 + 人 |
| C 工程质量 | 代码、测试、可复现性 | 自己 |
| D 材料打磨 | deck / README / 视频 / 架构图 / RAI | 自己 |

## 实测现状（本轮只读核对）

- 分支 `codex/v3-delivery`，HEAD `62b87fd`，与 `origin/main` 完全一致（0/0）。
- 本地标签只有 `v1`(→`70858cd`)、`v2`(→`9884e3a`)，远端无任何标签，`v3` 未创建。
- `pytest --collect-only` = **337 项**；`data/raw/default_of_credit_card_clients.zip` 在本地（5.5 MB）。
- `.env` 只有 `BASE_URL` / `API_KEY`，`.env.example` 用的是 `LLM_*` 六个变量 —— 名不对齐，真跑 Agent 前要确认。
- 演练进度：~~停在 Gate A~~ **更正**：仓库已有三次 29 步全 exit 0 的合成演练日志 —— `drill_v3.log`（`182506Z`，@`d0210b6`，修复前）、`drill_v3_clean_env.log`（`183352Z`，@`6f33b2c`）、`drill_v3_frozen_sha.log`（`191501Z`，@`e298d23`）。`dev_runs-v3-candidate` 那次只是废弃的半程尝试。
- 配对实测：`materials/impact_measurements.csv` 6 条 Agent 行已测，T11–T15 **5 条人工行仍是 pending**（0 组配对）。
- 视频 `materials/demo_video.mp4` 1:51，是历史合成 run 的 Streamlit 回放 + 合成英文配音，画面标 `SYNTHETIC REPLAY`。
- 评委访问：仓库私有，五件套只在 repo 里，没有对外可打开的链接。

## 阻塞项分类（决定哪些我能做、哪些必须人做）

只能由人/主办方给的输入（`docs/v3/08_handoff.md` H-01～H-08）：

- H-01 主办方 UCI 书面许可（`uci_competition_use_approved=false`）
- H-02 权威账本确认 seed 47 未消费（账本不入 Git）
- H-03 正式 run 审批人 / 运行权限 / 标签策略
- H-04 "一次正式 run 同时承载 v2+v3 证据" 的策略确认
- H-05 A/B 两名成员互审签字
- H-06 仓库对评委可见（**这一条其实可以由仓库所有者立刻解决**）
- H-07 视频分享链接
- H-08 人工配对计时（T11–T15，需要真人按协议操作）

我可以在无授权下推进的：

- 端到端合成 run（`dev_runs` 下，不消费正式 Holdout）→ 补 V3-01/V3-02 的证据完整度
- 配对测量的**协议、模板、脚本化计时/校验工具**（人只需执行）
- 材料打磨：deck / README / 架构图 / RAI / 视频脚本与重录（若授权）
- 提交包（离线 zip / 静态页面），使评委无需仓库权限也能看到五件套
- 代码与测试补强（是否允许改代码待定）

## 待选的五条工作流（按评分杠杆排序，待选）

### W1 评委可达性（硬阻塞，收益最高，成本最低）
- 选项：仓库转 public / 给评委发邀请 / 生成 `submission/` 离线包（含 deck、视频、架构图、RAI、README 快照）。
- 现在五件套全在私有仓库里，评委打不开 = V3-03 直接 FAIL。

### W2 配对业务价值实测（30% 权重，当前证据为 0）
- 按 `materials/impact_measurements_README.md` 跑 T11–T15，至少 3 对，填 `impact_measurements.csv`。
- 需要一个真人 + 秒表；我可以准备工作表、校验脚本、汇总表与 deck/README 的措辞（只写实测数字）。

### W3 端到端 v3 演练补全（V3-01/V3-02/V3-06 的可核验证据）
- 在干净树上跑完整合成链路（含 Gate A/B/C 实际决定、export、`release-check`），run 落在 `dev_runs/`。
- 现状停在 Gate A，所以"v3 能端到端跑通"目前只有历史 v2 的证据支撑。

### W4 材料打磨（Presentation 10% + RAI 15%）
- 视频：现为合成回放；如能重录成真实操作 + 真人声，Presentation 分会明显不同。
- README 574 行：给评委的入口可能需要一页 30 秒 quickstart + 一张"证据在哪"索引。
- deck：Slide 7（业务价值）目前只能写"pending"，W2 完成后才有一条真正的数字。

### W5 代码/验证补强（Technical 25%，但有回归风险）
- 现状：无跨时间回测（数据不支持，已在报告里如实标注）、无 monitoring 触发器闭环。
- 候选：把"漂移越过 review 线 → 自动生成 revalidation 任务"做成可核验的产物；或补 SAS 之外的输入适配。
- 风险：动 `src/` 会让历史 Gate C 审批失效（设计行为），需重跑回归与演练。

## Files to modify（待定）

- `plans/v3-optimization.md`（本文件）
- 视方向：`materials/*`、`docs/v3/*`、`README.md`、可能 `src/*` + `tests/*`

## Reuse（已存在的可复用件）

- `docs/v3/drill_v3.sh`：合成演练脚本，要求独立 `dev_runs-*` 目录与交互终端。
- `materials/impact_measurements_README.md`：配对测量协议与工作表格式。
- `materials/build_deck.py`：从 `solution_deck.md` 重建 PPTX/PDF。
- `src/cli.py`：`init-run` / `prepare` / `baseline` / `reference-parity` / `candidate-fixtures` / `mutation-check` / `docker-boundary` / `export` / `release-check`。
- `tests/test_v3_gap_*.py`：34 条定向回归。

## 执行记录（2026-11-11）

取舍：截止 11-13，只做不动 `src/`、不需授权的部分。

- [x] W3 端到端演练：核实已完成（见上方更正），无需重跑。
- [x] W2 配对测量工具：新增 `scripts/validate_inventory.py`（T11–T13 的计时终点，规则与 Gate A 完全一致，CSV 里早已引用但文件不存在）+ 8 条测试 `tests/test_v3_manual_inventory_validator.py`。
- [x] W1 评委可达性兜底：新增 `scripts/build_submission.py`，生成 `dist/model-risk-factory-submission-<sha>.zip`（五件套 + README + 证据表 + 带 SHA-256 的 MANIFEST），打包前拒绝未提交文件、本地绝对路径和疑似密钥。
- [x] W4 材料打磨：已由 `db0a4bc` 完成（评委优先的 README 与 deck）。
- [ ] W5 代码补强：**不做**。动 `src/` 会使历史 Gate C 审批失效，需重跑回归与演练，两天内不划算。

仍需人来做：

- H-06：仓库转 public / 邀请评委，或上传离线 zip。
- H-08：真人按协议跑 T11–T15（至少 3 对）后才能写任何加速百分比。
- H-01～H-05：许可、账本、审批、互审签字。

已知注意点：`impact_measurements.csv` 的 Agent 计时取自 `182506Z`，该 run 在 V3 冲突修复之前，其 V2/TREE inventory 按现行规则会被拒（数值仍是真实耗时，但引用时应说明 run 所在 commit）。

## Verification（占位）

- 合成 run：`pytest -q` 0 failed / 0 skipped；`verify-context` 通过；`release-check` 对该 run 返回可解释的状态。
- 材料：deck ≤10 页、视频 ≤3:00、每张图带来源标签、无绝对路径与密钥。
- 交付：评委侧无账号可打开全部五件套。
