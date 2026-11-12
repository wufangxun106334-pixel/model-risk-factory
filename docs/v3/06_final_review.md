# V3-05 final review — acceptance record, A/B review pack and open signatures

Owner: V3 交付执行 Agent（`agent-delegated`）。Reviewer 字段为真实执行者标识；人工签署留空。
状态只取 `PASS` / `FAIL` / `NOT_RUN` / `BLOCKED`。

---

## 1. V3 验收记录（逐条）

交付候选 `7ffc672` 已推送至 `main`。下表记录该候选的验收状态，证据对应的运行 SHA 见引用记录。正式发布以日后选定的冻结 SHA 和同一 SHA 上的正式 run 为准。

| acceptance_id | version | expected | actual | status | evidence_path | reviewer | timestamp | commit_sha |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V3-01 | v3 | v1/v2 必测项全通过，固定输入数值在容差内复现 | 审核修复后测试通过。旧合成 run V1-02 为 BLOCKED，seed 47 正式验收待运行 | BLOCKED | `docs/v3/10_audit_followup.md` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |
| V3-02 | v3 | 新环境与容器可复现，真实 Agent 与历史回放来源清楚 | 新环境全量回归通过。候选树上的真实网关合成演练停在 Gate A 待审，26 项资产复核通过。完整合成链路为历史回放 | PASS | [新环境记录](02_new_environment.md)、[审核修复记录](10_audit_followup.md) | Codex（技术复核） | 2026-11-10T20:09Z | `7ffc672` |
| V3-03 | v3 | 五件套齐全，评委可访问 | 10 页 Deck、1:51 回放视频、一页架构图、一页 RAI 和 README 已入库。评委访问暂缓 | BLOCKED | `materials/submission_checklist.md` | Codex（技术复核） | 2026-11-10T20:09Z | `7ffc672` |
| V3-04 | v3 | 同任务手工与 Agent 加人工复核配对实测 | 自动化计时可查。0 组有效配对，人工实测暂缓 | BLOCKED | `materials/impact_measurements.csv` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |
| V3-05 | v3 | 无阻断缺陷且关键结果经人工复核（11-12 改为单人操作，见 §3 披露） | seed 47 正式 run 中 fangxunwu 在 UI 完成 Gate A（3 份）、Gate B、Gate C 人工审核；存在检查器缺陷 D-01，见 [seed 47 正式 run 记录](12_formal_run_seed47.md) | PASS（人工复核）；阻断缺陷 D-01 已披露 | `docs/v3/12_formal_run_seed47.md` | fangxunwu | 2026-11-12 | `21c3235` |
| V3-06 | v3 | 同一冻结提交通过正式发布检查，工作区干净且创建 v3 标签 | 正式 run 完成，13/14 PASS；V1-07 因检查器缺陷 D-01 FAIL；`release-check` BLOCKED（2 条缺口均来自 V1-07）；未创建标签；UCI 无剩余独立 Holdout | BLOCKED | `docs/v3/12_formal_run_seed47.md`；`docs/v3/logs/release_check_v3_seed47.json` | automated release-check | 2026-11-12 | `21c3235` |

## 2. A/B 互审材料（V3-05 的可执行部分）

两名成员各审一半，交叉覆盖。审阅只需只读命令与下列文件，不需要重跑正式流程。

### 2.1 待核对的提交与数据口径

| 项 | 值 | 怎么核 |
| --- | --- | --- |
| 候选提交（代码+测试+配置+材料） | 冻结提交，见 `docs/v3/09_verification_of_freeze.md` §1 | `git log -1 --format=%H` |
| 本次代码改动范围 | `src/inventory.py`（冲突判定）、`src/report.py`（摘要事实与措辞）、`src/agent.py`（提示词与校验入口）、`src/ui_data.py` + `app.py`（状态徽标）、2 个新测试文件 | `git diff d0210b6..<frozen> --stat` |
| 数据口径（seed 47） | train 15,000 / dev 6,000 / holdout **1,199** / shift_pool 3,000，另有 4,801 行不使用；`config/data_config.json` `seed=47` | `python -c "import json;print(json.load(open('config/data_config.json'))['split_sizes'])"` |
| 历史口径（seed 42–46） | 6,000 行 Holdout，按 `config/holdout_ledger.json` 重建校验 | `python -m src.cli verify-holdout-ledger --raw-uci data/raw/default_of_credit_card_clients.zip`（需已获准 ZIP） |
| 正式账本 | seed 42–46 共 5 条 `CONSUMED`，无 seed 47 | `cat runs/holdout_consumption.jsonl`（本机；不入 Git） |
| 数据类别标注 | UCI（正式/历史）与 synthetic（演练）分开标注；合成 run 永不满足 V1-02 | `docs/v3/test_summary.md` §1、`docs/v3/02_new_environment.md` §3 |

### 2.2 待核对的数值结果

| 数值 | 期望 | 怎么核 |
| --- | --- | --- |
| 全量测试 | 0 failed / 0 skipped / exit 0 | `.venv/bin/python -m pytest -q` |
| 历史 UCI Holdout parity | max 2.220446049250313e-16、0 分类差异、0 行为差异、6,000 行 | `runs/v2-20261109T210903Z-3dcfab73/parity/holdout/parity_summary.json` 或 `validation_metrics.json` |
| 历史 UCI 性能 | holdout ROC-AUC 0.7528891634903521、Brier 0.14219949573466015 | 同上 `performance.holdout` |
| 漂移 | 预测 PSI 0.017012211744139933；util_1 0.07989182589304562；状态 OK | 同上 `stability` |
| 公平性 | 参考组 age_band=26-35 / sex=2；最大 TPR 差异 age_band=21-25 +0.10857519536847743 | 同上 `fairness.attributes` |
| 演练（合成，seed 47） | parity max 5.551115123125783e-17、holdout 1,199 行、196 个数值溯源 | `dev_runs/v2-20261110T182506Z-9acb1487/`（本机） |
| Deck 数字与来源一致 | 5 处抽查一致 | `docs/v3/logs/materials_verification.log` |

### 2.3 待核对的 Gate 记录

| Gate | 期望 | 怎么核 |
| --- | --- | --- |
| A（三份档案） | 每份 1 次 `APPROVED`，reviewer = `agent-delegated`，绑定 `reviewed_artifact_sha256` | `runs/…/review_log.json`；`cat review_log.json` 后核对哈希与档案内容 |
| B（候选） | 1 次 `APPROVED`，绑定 64 位源码哈希，且在容器执行之前 | 同上 + `command_log.jsonl` 顺序 |
| C（报告） | 1 次 `APPROVED`，绑定 `report/review_manifest.json` | 同上 + `report/approval.json` |
| 失效机制 | 改 `src/` 后旧审批变 `INVALIDATED` | `python -m src.cli report-status --run-id v2-20261109T210903Z-3dcfab73` 现应返回 DRAFT（设计行为） |
| 代理审核标注 | 不得写成人工审核 | 抽查 `review_log.json` 的 reviewer 与 comment |

### 2.4 待核对的交付链接

| 交付物 | 路径 | 待核 |
| --- | --- | --- |
| Deck | `materials/solution_deck.pptx` / `.pdf` / `.md` | 10 页、数字带来源 |
| 视频 | `materials/demo_video.mp4` | 本地成片 1:51，分享链接待验证 |
| 仓库 | 私有 GitHub，需从评委视角验证访问 | 见交接 H-06 |
| 架构图 | `materials/architecture.svg` / `.png` | 1 页、数据流与模型 ID |
| RAI note | `materials/responsible_ai_note.md` | 1 页、五模块齐全 |
| 证据包（历史） | `delivery/v2-20261109T210903Z-3dcfab73_evidence.zip`（sha256 `c8670a0f…`） | 仅历史回放，不得当作发布放行 |

## 3. 分工建议（按 SOP §13）

> **11-12 单人操作披露：** 团队登记两名成员（fangxunwu 25208508、kaiwenyao 25202665），但项目实际由 **fangxunwu 一人操作**，不存在独立的第二审核人。因此**不做、也不伪造双人互审签字**。V3-05 的人工复核由 seed 47 正式 run 中 fangxunwu 在 UI 里亲自完成的 Gate A（三份档案）、Gate B（候选源码）、Gate C（报告）审核承担，证据是该 run 的 `review_log.json`（`reviewer=fangxunwu`，绑定 64 位哈希）。以下 §3.1/§3.2 签署栏不再使用。


| 审阅人 | 负责核对 | 建议理由 |
| --- | --- | --- |
| 成员 A（AI 工程主线） | §2.3 Gate 记录、§2.1 提交范围、§2.4 交付链接与访问 | 与 Agent/门禁/导出实现最熟 |
| 成员 B（建模验证主线） | §2.2 全部数值、§2.1 数据口径、公平性与校准口径 | 与 R 模型、指标定义最熟 |

两人各自在下面签署。**签署前请确认：你实际打开了对应文件并核对了数值，而不是只看本文件。**

### 3.1 成员 A 签署（留空，待人工）

| 字段 | 内容 |
| --- | --- |
| reviewer | ____________________ |
| 核对范围（勾选） | ☐ Gate 记录 ☐ 提交范围 ☐ 交付链接 ☐ 其他：______ |
| 实际核对方式与发现 | ____________________________________ |
| 决定 | ☐ APPROVED ☐ REJECTED（原因：____________） |
| 时间（ISO 8601） | ____________________ |

### 3.2 成员 B 签署（留空，待人工）

| 字段 | 内容 |
| --- | --- |
| reviewer | ____________________ |
| 核对范围（勾选） | ☐ 数值结果 ☐ 数据口径 ☐ 公平性/校准口径 ☐ 其他：______ |
| 实际核对方式与发现 | ____________________________________ |
| 决定 | ☐ APPROVED ☐ REJECTED（原因：____________） |
| 时间（ISO 8601） | ____________________ |

## 4. 阻断缺陷、限制与未完成项（V3-05 事实清单）

**阻断缺陷（存在即不得宣称已发布）**

1. v2 正式发布 BLOCKED：seed 46 证据的树不等于任何提交，`release-check` 17 条缺口（`docs/v3/03_release_readiness.md`）。
2. seed 47 正式 run 待启动。还需记录 UCI 使用批准、权威账本未消费确认和 Gate A/B/C 审核人或代理授权，再确认正式运行 SHA。
3. 五件套已入库。评委访问、A/B 互审和配对计时按团队当前安排暂缓，分别阻塞 V3-03、V3-05 和 V3-04。

**清楚记录的性质与限制**

- 数据：UCI 2005 年台湾信用卡样本，CC BY 4.0，含人口属性（仅审计）；比赛使用依据官方规则原文记录（`docs/official/2026-11-12_uci_permission.md`，不是主办方单独邮件）。
- 模型：三个旧模型与旧文档为团队自建模拟资产；只迁移 `MDL_CREDIT_V1`；迁移复用 R 系数、不重新训练。
- 指标：holdout 为同期随机留出（样本外验证）；漂移为加权抽样敏感性分析；**无跨时间回测**；公平性是审计信号，不是合规结论。
- Agent 选择审阅重点并返回结构化状态。代码对照指标校验状态，并用模板生成报告结论与审阅提示。请求、重试和审核都有日志。
- 未完成可选项：SAS 解析、MLflow/Azure ML、批量化调度、跨时间回测数据、MLOps 部署。

**不得写入任何材料的表述**：生产可用、独立验证、监管认证、公平性已被证明、约 250 个模型与 8–12 周为本项目实测成果。
