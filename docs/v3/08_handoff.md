# V3 hand-off list — what only a human or the organisers can do

Owner of this list: V3 交付执行 Agent（`agent-delegated`）。每条都写清**负责人 / 所需输入 / 下一条可执行动作 / 阻塞了什么**。
本文件不替代团队决定；四项前置未齐备前，正式 run 不会启动，正式 Holdout 不会被消费。

---

## 0. 交付候选与正式发布状态

| 项 | 值 |
| --- | --- |
| 已交付候选 | `7ffc672` 已于 2026-11-10 快进至远端 `main`，含代码与五件套 |
| 正式运行 SHA | 待正式运行前确认。旧合成演练的 SHA 单独记在 `docs/v3/09_verification_of_freeze.md` |
| `v3` 标签 | **未创建** |
| 正式 run | **未启动**。本机账本无 seed 47 记录，团队权威账本确认待补 |

## 1. 必须由人处理的事项

### H-01 UCI 数据使用授权证据（阻塞 V3-06、阻塞正式 run）

> **状态：✅ 11-12 已关闭：依据官方规则原文，见 [决策记录](11_formal_run_decisions.md)**

| 字段 | 内容 |
| --- | --- |
| 负责人 | 团队负责对外沟通的成员（建议：提出主办方询问的那位） |
| 所需输入 | 主办方对「本参赛作品使用 UCI Default of Credit Card Clients」的书面确认（邮件原文或官方 FAQ 截图），以及可否随提交分发的答复 |
| 现状 | `config/data_config.json` → `uci_competition_use_approved=false`；run 内 `uci_approval.json` 只是操作者声明；仓库内无主办方书面证据；官方 PDF 只写 "public or synthetic data only" 且未指定数据集 |
| 下一条可执行动作 | 收到书面确认后：把原文存为 `docs/official/<date>_uci_permission.md`（或截图），在 `config/data_config.json` 把 `uci_competition_use_approved` 改为 `true` 并在提交信息中引用该文件 |
| 阻塞 | seed 47 正式 run、`release-check` 的 APPROVED、`v3` 标签、README/Deck 的许可表述从"待确认"改为"已确认" |

### H-02 权威账本与团队记录确认 seed 47 未消费（阻塞正式 run）

> **状态：⏳ 11-12：正式 run 改在 A 本机执行，仍待 B 书面确认 seed 47 未消费，见 [决策记录](11_formal_run_decisions.md)**

| 字段 | 内容 |
| --- | --- |
| 负责人 | 持有正式运行环境的成员（v1/v2 正式 run 的执行者） |
| 所需输入 | 权威账本文件 `runs/holdout_consumption.jsonl`（或团队约定的等价记录）的实际内容；团队对"seed 47 未被任何一次正式运行消费"的书面确认 |
| 现状 | 本机账本：seed 42–46 共 5 条 `CONSUMED`，无 seed 47。但账本不入 Git，独立检出没有记录**不能**证明未消费 |
| 下一条可执行动作 | 在正式运行机器上执行 `cat runs/holdout_consumption.jsonl \| grep -c seed-47`（期望 0）与 `python -m src.cli verify-holdout-ledger --raw-uci data/raw/default_of_credit_card_clients.zip`，把输出贴进交接记录并签字 |
| 阻塞 | 同 H-01；同时决定是否需要先把账本纳入团队的权威存储 |

### H-03 正式 run 的审批人、运行权限与标签策略（阻塞正式 run 与标签）

> **状态：✅ 11-12 已决：A 在 UI 人工审核 Gate A/B/C；只打 v3 标签，推送前再确认，见 [决策记录](11_formal_run_decisions.md)**

| 字段 | 内容 |
| --- | --- |
| 负责人 | 团队成员 A + B（共同决定，一人执行） |
| 所需输入 | ① 本次 Gate A/B/C 的审核人（人工签名，还是再次 `agent-delegated` 代理审核并在备注写授权来源）；② 谁有权限在正式环境执行 run；③ 标签策略：是否创建 `v3`、是否推送、已存在的本地 `v2` 标签（指向 `9884e3a`，在未放行情况下创建）如何处置 |
| 现状 | 仓库内无任何授权记录；`v1`/`v2` 标签仅存在于本机，`origin` 无标签 |
| 下一条可执行动作 | 在 `docs/v3/07_release_checklist.md` §3 之前，写一份决策记录（谁批准、批准的 run 范围、标签是本地还是推送），并明确 `v2` 标签"保留不动"或"经授权删除"——**不得移动它去凑提交** |
| 阻塞 | 正式 run、`v3` 标签、V3-06 |

### H-04 团队对"一次正式 run 同时承载 v2 与 v3 证据"的策略确认（阻塞正式 run）

> **状态：✅ 11-12 已决：v2 永久 BLOCKED，只发 v3；只跑一次正式 run，见 [决策记录](11_formal_run_decisions.md)**

| 字段 | 内容 |
| --- | --- |
| 负责人 | 团队成员 A + B |
| 所需输入 | 明确接受或拒绝下列策略：在**同一冻结 SHA** 上跑**一次** seed 47 正式 run，用该 run 的 14 项验收同时为 V1-01～07、V2-01～07 提供证据，再叠加 V3 材料与人工审核 |
| 现状 | 已作为建议提出（`docs/v3/03_release_readiness.md` §6），未获确认 |
| 下一条可执行动作 | 在 `docs/v3/06_final_review.md` §3 签署时一并写明；若拒绝，需给出替代方案（例如接受 v2 永久 BLOCKED 并只发布 v3 材料） |
| 阻塞 | 正式 run（禁止为了分别生成 v2/v3 记录而拆两次正式运行） |

### H-05 A/B 两名成员互审（按团队指示暂缓）

> **状态：11-12 改为单人操作披露，不做双人签字；人工复核由正式 run 中 fangxunwu 亲自完成的 Gate A/B/C 承担，见 [最终审核](06_final_review.md) §3。H-02 已由 fangxunwu 确认。**

| 字段 | 内容 |
| --- | --- |
| 负责人 | 成员 A（Gate/提交/链接）、成员 B（数值/口径） |
| 所需输入 | 各自用只读命令实际核对 `docs/v3/06_final_review.md` §2 列出的项目 |
| 现状 | 材料已可直接审阅；两条签署栏为空 |
| 下一条可执行动作 | 按 §2.1–§2.4 逐项核对 → 在 §3.1 / §3.2 填 reviewer、核对方式、决定（APPROVED/REJECTED）与 ISO 时间 → 提交（该提交不改变代码与冻结材料） |
| 阻塞 | V3-05、`v3` 标签（SOP 要求两名成员互审关键结果） |

### H-06 评委访问权限（按团队指示暂缓）

> **状态：✅ 11-13 已完成：仓库改为 public（https://github.com/wufangxun106334-pixel/model-risk-factory），匿名访问 HTTP 200；公开前历史密钥扫描干净。视频分享链接（H-07）仍待上传。**

| 字段 | 内容 |
| --- | --- |
| 负责人 | 仓库所有者（GitHub `wufangxun106334-pixel/model-risk-factory`） |
| 所需输入 | ① 仓库是否对评委可见（当前 Private）；② deck/视频/架构图的分享链接；③ 是否需要邀请评委账号 |
| 现状 | 仓库私有，材料已在远端 `main`，评委视角暂未核验 |
| 下一条可执行动作 | 用一个非团队账号打开仓库与全部链接验证可访问，把结果填进 `materials/submission_checklist.md` §5 的勾选项 |
| 阻塞 | V3-03 的"全部必交文件可访问"、V3-06 |

### H-07 视频成片与访问验证

| 字段 | 内容 |
| --- | --- |
| 负责人 | 成员 B 主责（SOP §13），成员 A 协作 |
| 所需输入 | 评委可访问的仓库或视频分享链接 |
| 现状 | 成片已随 `main` 入库（1:51，H.264 + AAC），为历史合成回放 |
| 下一条可执行动作 | 恢复评委访问核验后，共享 `materials/demo_video.mp4`，从评委侧验证链接可播放，并记录在提交清单 |
| 阻塞 | V3-03 完成判定、提交清单 |

### H-08 人工配对业务价值测量（按团队指示暂缓）

| 字段 | 内容 |
| --- | --- |
| 负责人 | 成员 B（建模验证主线），可由成员 A 复测 |
| 所需输入 | 干净检出、`legacy/*.R` 与 `legacy/notes/*.md`、`config/inventory_schema.json`、秒表 |
| 现状 | 6 条 Agent 行已实测，5 条人工行为 `pending` |
| 下一条可执行动作 | 按 `materials/impact_measurements_README.md` §3–§4 执行 T11–T15（至少 3 对），替换 `pending` 行并记录顺序 |
| 阻塞 | V3-04；现有记录仅支持报告自动化耗时 |

## 2. 已由我完成、无需人工的部分

- 基线与标签事实、正式账本与本机状态记录（`docs/v3/00_baseline_status.md`）。
- 两个判定缺口的复现、最小修复与 34 条定向回归（`docs/v3/01_gap_fixes.md`）。
- 审核修复后全量测试 337 项和 7 个子测试通过。固定数据复跑和新候选的 Gate A 前演练见 `docs/v3/test_summary.md` 与 `docs/v3/10_audit_followup.md`。
- 新环境复现 + 端到端合成演练 + 四页界面实测（`docs/v3/02_new_environment.md`、`docs/v3/ui_screens/`）。
- 正式证据只读复核、`release-check` BLOCKED 与 seed 47 四项前置核验（`docs/v3/03_release_readiness.md`）。
- 五件套（含 1:51 视频成片）、提交清单、impact CSV 与协议、README、验收与审核材料已推送至 `main`。
- 冻结提交的确定与只读复核（`docs/v3/09_verification_of_freeze.md`）。

**没有做、也不会在未授权时做**：启动正式 run、消费 seed 47、创建或移动任何标签、推送、上传材料、发送邮件。

## 3. 建议的执行顺序（依赖关系）

```text
H-01 + H-02 + H-03 + H-04  →  一次正式 run → release-check → H-05 签署 → v3 标签（若 H-03 授权）
H-06 可与上面并行（越早越好，避免最后卡在权限）
H-07 可并行（录制不依赖正式 run，可用演练 run + REPLAY 标注）
H-08 可并行（人工测量不依赖正式 run）
```

最早可完成的完整路径：先做 H-06（权限）与 H-07（视频），同时推 H-01/H-02 的书面材料；
四项前置齐备后一次性执行正式 run，再走 H-05 签署与标签。
