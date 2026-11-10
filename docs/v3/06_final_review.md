# V3-05 final review — acceptance record, A/B review pack and open signatures

Owner: V3 交付执行 Agent（`agent-delegated`）。Reviewer 字段为真实执行者标识；人工签署留空。
状态只取 `PASS` / `FAIL` / `NOT_RUN` / `BLOCKED`。

---

## 1. V3 验收记录（逐条）

`commit_sha` 记录**该条证据产出时所在提交**；最终冻结提交以本候选提交和后续正式 run 的初始化 SHA 为准。旧演练复核见 `docs/v3/09_verification_of_freeze.md`。

| acceptance_id | version | expected | actual | status | evidence_path | reviewer | timestamp | commit_sha |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V3-01 | v3 | v1/v2 必测项全通过，固定输入数值在容差内复现 | 审核修复后测试通过。旧合成 run V1-02 为 BLOCKED，seed 47 正式验收待运行 | BLOCKED | `docs/v3/10_audit_followup.md` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |
| V3-02 | v3 | 新环境与容器可复现，真实 Agent 与历史回放来源清楚 | 新环境测试与合成复现有记录。新版三份档案用真实网关生成，摘要在独立合成回放复核 | PASS | `docs/v3/02_new_environment.md；docs/v3/10_audit_followup.md` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |
| V3-03 | v3 | 五件套齐全，评委可访问 | 10 页 Deck、1:51 本地回放视频、一页架构图、一页 RAI 和 README 就绪。评委访问暂缓 | BLOCKED | `materials/submission_checklist.md` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |
| V3-04 | v3 | 同任务手工与 Agent 加人工复核配对实测 | 自动化计时可查。0 组有效配对，人工实测暂缓 | BLOCKED | `materials/impact_measurements.csv` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |
| V3-05 | v3 | 无阻断缺陷且 A/B 互审关键结果 | 审核修复已落在候选树，双人签核暂缓 | BLOCKED | `本文件 §3；docs/v3/10_audit_followup.md` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |
| V3-06 | v3 | 同一冻结提交通过正式发布检查，工作区干净且创建 v3 标签 | 旧正式证据 BLOCKED。等批准证据与审核人记录后，在最终 SHA 上跑 seed 47。未创建标签 | BLOCKED | `docs/v3/07_release_checklist.md；docs/v3/10_audit_followup.md` | Codex（技术复核） | 2026-11-10T20:09Z | 本候选提交 |

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
2. 没有 seed 47 正式 run：四项前置中 UCI 授权证据、权威账本确认、审批人与标签策略未齐备（同上 §5）。
3. 视频本地成片已就绪。评委访问、A/B 互审和配对计时按团队当前安排暂缓。
4. 人工配对业务价值测量未执行（协议已就绪）。

**清楚记录的性质与限制**

- 数据：UCI 2005 年台湾信用卡样本，CC BY 4.0，含人口属性（仅审计）；比赛使用授权仍待书面确认。
- 模型：三个旧模型与旧文档为团队自建模拟资产；只迁移 `MDL_CREDIT_V1`；迁移复用 R 系数、不重新训练。
- 指标：holdout 为同期随机留出（样本外验证）；漂移为加权抽样敏感性分析；**无跨时间回测**；公平性是审计信号，不是合规结论。
- Agent：摘要与解释由模型生成，可能出错；关键结论由指标渲染并经门禁复核；请求与重试上限、审计日志均可核对。
- 未完成可选项：SAS 解析、MLflow/Azure ML、批量化调度、跨时间回测数据、MLOps 部署。

**不得写入任何材料的表述**：生产可用、独立验证、监管认证、公平性已被证明、约 250 个模型与 8–12 周为本项目实测成果。
