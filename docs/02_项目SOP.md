---
title: Challenge 04 银行模型风险管理项目 SOP
created: 2026-11-05
updated: 2026-11-10
tags:
  - 黑客松
  - EXL-UCD
  - Model-Risk
  - Agentic-AI
status: v1-accepted / v2-release-blocked
release_plan: v1-prototype / v2-formal / v3-final
---

# Challenge 04：银行模型风险管理项目 SOP

> SOP = Standard Operating Procedure（标准操作流程）。本文是项目**唯一的设计主文件**。文档描述待实现的设计，不代表代码已经完成或测试已经通过。
>
> 比赛背景、官方要求原文和常见疑问见 [01_比赛背景与官方要求.md](01_比赛背景与官方要求.md)。下述实现、阈值与版本计划属于团队决策，不是额外官方要求。

## 1. 项目定位与固定边界

**一句话：分析三个预置旧 R 模型，生成可追溯档案；将其中一个逻辑回归预测流程移植到 Python，通过固定测试验证等价性，再生成包含性能、稳定性与公平性结果的人工审核报告。**

目标用户：演示中的模型审阅者。目标是能在三分钟演示中看懂、有实际运行证据、能按 README 复现的 Hackathon prototype（竞赛原型）。个人学习主线为 Python / AI Engineering（AI 工程）。

### 1.1 题意与实现的对应

| 原活动要求 | 本项目实现 |
| --- | --- |
| 3–5 个模型的文档与清单 | 三个自建 R 模型，分别建立档案、来源与未知项 |
| 一个 SAS 或 R 模型重新实现为 Python，提供等价性证明 | 选择 R 逻辑回归，保留参数与预测行为，不以重新训练代替迁移 |
| 自动生成性能、稳定性、公平性验证报告 | Python 计算指标（含校准），Agent 解释，Markdown 模板承载报告 |
| 建议的 Monitor：跟踪漂移、触发重新验证 | 模拟漂移批次与可配置 PSI 预警，置 `REVALIDATION_REQUIRED` 状态 |
| Humans review at each gate | 三道审核关卡（Gate A/B/C）；可由人工或经明确授权的代理按同一标准执行（见 7.4） |
| 公开信用数据（如 Kaggle） | UCI Default of Credit Card Clients |
| Azure ML、MLflow 等工具偏好 | 当前使用本地文件记录；MLflow/Azure 为可选后续项，不是本次三个版本的必交项 |

### 1.2 已确认约束

- 团队：两人，按第 13 节分工并互审关键产物。
- 开发日期：2026-11-08 至 11-12，11-12 Feature freeze（功能冻结）；11-13 只处理提交事项及必要阻断缺陷。
- 运行：单机本地演示，录屏备用；无公网部署、多用户认证、独立后端或云数据库。
- 模型：三个预置 R 模型建档，只迁移一个；不承诺任意 SAS/R 模型转换。
- 数据：UCI 公开数据（无直接标识，含人口属性；能否用于比赛待主办方确认）+ 少量合成样例；结果不代表真实英国银行模型表现。
- Agent：单 Agent、固定阶段、Tool calling（工具调用）、最多两轮代码修复。
- 生成代码：仅在受限 Docker container（容器）内运行；不开放任意外部代码上传。
- API：用户指定 https://sa.kaiwen.dev ，具体协议、模型和工具调用能力待接入验证（备选方案见 16.2）。
- 输出：Markdown 报告、CSV 差异、JSON 证据；自动生成 PDF 不在实现范围内。
- 只做 **v1、v2、v3**。不追加 v4，也不以"正式版"为理由扩大为生产银行平台。

## 2. 核心知识与学习顺序

| 顺序 | Knowledge（知识） | 能解释和验证的内容 |
| --- | --- | --- |
| 1 | Logistic regression（逻辑回归） | 特征、系数、截距、概率、阈值之间的关系 |
| 2 | Preprocessing（预处理） | 仅用训练集拟合填补参数，固定特征顺序、派生特征与输入规则 |
| 3 | Parity（等价性） | 相同输入的 R/Python 概率、分类、异常处理是否一致 |
| 4 | Model validation（模型验证） | 数据划分、ROC-AUC、Brier score、校准、混淆矩阵、群体错误率 |
| 5 | Evidence traceability（证据可追溯性） | 结论对应代码、文件哈希、JSON 指标与运行记录 |
| 6 | Agent workflow（智能体流程） | 工具调用、状态机、结构化输出、修复限制与失败处理 |
| 7 | Human review（人工复核） | 审核者确认事实与风险；工具不能自行宣称独立验证或监管合规 |

先完成一个模型的可验证迁移，再做自动化与界面。无需先研究复杂深度学习或完整监管体系。

## 3. 技术栈与选择依据

| 层 | 选择 | 负责内容 | 范围与取舍 |
| --- | --- | --- | --- |
| 主语言 | Python | 工作流、预测、指标、报告、运行记录 | 主体工程语言 |
| 界面 | Streamlit | 四个逻辑页面、审核按钮、结果下载 | 直接调用服务函数，不另设 FastAPI/React |
| 旧模型 | R + Rscript | 三个模型、原始参数与基准预测 | 常规 glm；树模型用 rpart；JSON 导出可用 jsonlite |
| 数据与计算 | NumPy、pandas、scikit-learn、SciPy；读取 .xls 需 xlrd | 数据加工、对齐、指标与数值计算 | 锁定实际可运行版本 |
| 数据契约 | Pydantic | 校验清单、迁移结果、指标、审核记录 | 本地校验必做；服务端结构化输出待实测 |
| 测试 | pytest | 固定契约、等价性、异常与故障测试 | 不允许 Agent 修改评分规则 |
| 执行隔离 | Docker | 执行生成 Python、隔离验证过程 | 无网络、只读根目录、资源与时间限制 |
| LLM 接入 | Provider adapter（服务适配层） | 屏蔽具体协议、记录请求和错误 | 协议确认后再选 SDK，不预设 OpenAI 兼容 |
| 状态与结果 | CSV / JSON / JSONL / Markdown | 数据、元信息、日志、报告 | 单用户本地文件，无数据库 |
| 版本管理 | Git | 代码、设计与交付版本 | v1/v2/v3 三个通过验收的 Git tags（标签） |

Docker Desktop、R 和 Python 需在开发机实际验证。依赖版本在接入与首次运行后锁定，不在设计文档里编造已验证版本。

## 4. 版本定义与发布门禁

**v1 是 Prototype（原型）；v2 是正式版；v3 是最终版。** 正式版指本次竞赛固定范围内的完整实现，不代表可直接用于银行生产。技术阶段可拆成任务，不能再衍生额外发布版本。

| 版本 | 日期目标 | 必须完成 | 放行条件 |
| --- | --- | --- | --- |
| ~~**v1 Prototype**~~ ✅ 11-09 完成 | ~~11-10 结束前~~ | API 最小验证；UCI 数据加工与划分；一个 R 基准；人工参考 Python 实现与独立等价性工具；故意错误案例；待迁移模型的 Agent 档案通过 Gate A；**一次真实 Agent 迁移**（CLI + 最小 Docker + Gate B 审批） | V1-01 至 V1-07 全满足；从数据到 Holdout 等价性结论的迁移证据链可按 README 复现；已实现与占位功能清楚区分 |
| **v2 正式版** | 11-11 结束前 | 三份 Agent 档案；三审核关卡；Docker 边界加固；四类验证（含校准表）与报告；完整运行证据与导出 | V1-01 至 V1-07 和 V2-01 至 V2-07 全部通过，且 `release-check` 对同一 run 和待发布提交返回 `APPROVED`。Streamlit 四页界面为可选演示目标 |
| **v3 最终版** | 11-12 结束前 | 集成复测、新环境复现、交付五件套（含 AI 工具声明）、三分钟视频、最终 Git 版本；不再新增功能 | V3-01 至 V3-06 全满足；全部必交文件可访问；冻结范围和已知限制写入 README |

版本失败时不得创建对应通过标签，也不得在展示中说已经完成。修复后仍归属同一版本，不新增 v1.1/v4 等计划。未完成 v2 就不能把 v3 包装为"最终通过"。

### 4.1 v1 验收标准

| ID | Test（验收动作） | Pass（通过条件） | Evidence（证据） |
| --- | --- | --- | --- |
| ~~V1-01~~ | ~~API smoke test（最小调用）~~ | 指定网关真实请求成功；确认协议、模型 ID、工具往返及输出解析；不能确认时当天按 16.2 决策 | ✅ PASS · 脱敏的 capability_check.json、请求 ID、脱敏请求日志 |
| ~~V1-02~~ | ~~数据加工与划分~~ | 原始 UCI 文件 SHA-256 与记录一致；30,000 行按 15,000/6,000/6,000/3,000 分层划分，ID 唯一且互不交叉；各子集违约率与总体相差 ≤1 个百分点；未文档化编码按数据字典处理；固定种子；配置与产物哈希记录 | ✅ PASS · data_manifest.json、数据字典、划分测试 |
| ~~V1-03~~ | ~~R 基准~~ | V1 模型可重跑，系数/预处理/开发预测输出有效；未把 ID、标签或人口属性当特征 | ✅ PASS · R sessionInfo、产物清单 |
| ~~V1-04~~ | ~~Python 参考实现等价性~~ | 主键一一对齐、概率与分类、缺失与拒绝行为满足第 8 节；不得只比较 Accuracy | ✅ PASS · parity_summary.json、parity_diff.csv |
| ~~V1-05~~ | ~~故意错误案例~~ | 改变一个系数的隔离副本被固定测试发现；原始基准及测试哈希不变 | ✅ PASS · 预期失败测试与差异 |
| ~~V1-06~~ | ~~真实 Agent 迁移~~ | Agent 为 MDL_CREDIT_V1 提取档案，经 Gate A 审核通过后，才由实际 API 生成 credit_v1 候选；执行前经 Gate B 批准代码哈希（两道关卡均可通过 CLI 审核）；只在最小 Docker（`--network none`、只读挂载、非 root、超时）中运行；最多初始生成 + 两次修复；测试代码与基准不可写；候选冻结后才评估 Holdout，结果符合第 8 节，失败则状态为 FAILED | ✅ PASS · model_inventory.json、review_log.json、agent_audit_log.jsonl、代码及测试哈希、Holdout parity_summary.json |
| ~~V1-07~~ | ~~迁移证据链复现~~ | 按 README 用 CLI 从预置数据跑到 Holdout 等价性结论；结果为真实运行而非硬编码 | ✅ PASS · 命令、退出码、运行日志 |

人工 Python 实现是等价性工具的开发基线，不能标为 Agent 自动迁移；V1-06 的候选必须由真实 API 生成。

> **v1 验收记录（2026-11-09）**：正式 run `v1-20261109T181929Z-3fe1c7b5`（campaign 2，seed 43）V1-01～07 全部 PASS，Gate A/B 为代理审核，证据包 `delivery/v1-20261109T181929Z-3fe1c7b5_evidence.zip`，对应提交 `70858cd`；`v1` Git tag 尚未创建。另有本机复现 run `v1-20261109T195940Z-3fa02654`：按 §12.1 从新环境跑通 check-provider → candidate-fixtures 共 12 条命令（全部 exit 0），Gate A/B 由人工（alex）审核，Agent 候选 dev parity PASS（6,000 行，max_abs_diff 2.2e-16）；依 §7.5 未重复消费 campaign 2 Holdout，`final_status=NOT_RUN`。

### 4.2 v2 验收标准

| ID | 验收动作 | 通过条件 | 证据 |
| --- | --- | --- | --- |
| V2-01 | 三模型建档 | 补齐其余两个模型的档案；三份档案均符合 Schema 并通过 Gate A；发现预设阈值矛盾；负责人等未知项保留 Unknown；关键事实含来源 | model_inventory.json、来源校验结果、review_log.json |
| V2-02 | 容器执行边界 | 在 v1 最小隔离基础上：容器无法写基准/宿主目录；内存、CPU、PID 与超时边界可触发；容器内无 API key | 容器配置及边界测试结果 |
| V2-03 | 四类验证 | 等价性、性能（含十分位校准表）、稳定性、公平性结果均来自程序；缺标签/单类/分母为零/小样本时明确状态 | validation_metrics.json、指标测试 |
| V2-04 | 审核关卡 | 待迁移模型的档案通过 Gate A 后，Agent 才能生成迁移候选；每个新代码哈希执行前需 Gate B 批准；报告未经 Gate C 审阅不标记 APPROVED | review_log.json、关卡测试 |
| V2-05 | 端到端及导出 | 清单→档案→迁移→验证报告可通过 CLI 或界面走通；MD/CSV/JSON 导出且 run_id 一致 | 端到端检查记录 |
| V2-06 | 故障处理 | API 请求失败、解析失败、超时、请求上限和修复耗尽均保留失败记录 | 故障测试和请求日志 |
| V2-07 | 报告来源与限制 | 每个数值引用指标 JSON 路径；引用存在不等于语义真实，关键事实需人工复核；无合规认证措辞 | 报告、审核意见 |

### 4.2.1 v2 实现状态（2026-11-10 复核）

**CLI 功能已实现，正式发布为 `BLOCKED`。** 2026-11-10 在 `main`（`92fa3a0`）复测，全量测试 287 项通过，另有 7 个子测试通过，0 失败、0 跳过。seed 46 的历史记录显示 14 项验收均通过，但当时工作区有未提交改动，证据无法绑定到发布提交。本地和 `origin` 均未发现 `v2` 标签。账本复算确认 UCI 只剩 1,199 行未用于正式 Holdout，低于 6,000 行的要求。[发布状态与缺口](../README.md#发布状态与缺口)

重新放行须取得获准且独立的 6,000 行 Holdout，在干净的已提交版本上完成一次正式运行与证据导出，对同一提交 SHA 运行 `release-check` 并取得 `APPROVED`，再创建 `v2` 标签。数据未及时获批时，按 §13 提交范围变更供团队确认。[重新放行步骤](../README.md#v2-重新放行步骤)

当前实现口径如下。

- 三份档案的 Gate A 产物：`MDL_CREDIT_V1` 为 `model_inventory.json`，另外两个模型为 `inventories/<model_id>.json`；每个模型的内容期望（特征顺序、代码/文档阈值、必须保留的 Unknown、最少冲突数）由 `config/inventory_expectations.json` 冻结。
- Gate C 的被审产物统一为 `report/review_manifest.json`：生成、审批（`approve --gate Gate_C`）与状态检查（`report-status`）使用同一路径；该清单绑定报告、`validation_metrics.json`、数值索引、表格与 Agent 摘要的哈希，任一被绑定文件缺失或变化即退回 DRAFT，`report/approval.json` 只在 Gate C 通过后生成。
- `validation-metrics` 在执行或复用漂移批次结果前，必须先校验 context、冻结源码哈希、当前 Gate A/B 决定、frozen attempt 的开发验证与行为 fixtures、四个划分输入哈希，以及缓存执行记录的 candidate/model/input/output 哈希。
- 数据划分：历史排除集由 `config/holdout_ledger.json` 记录的 seed、算法与划分哈希，配合已获准的 UCI 原始 ZIP **可重建校验**；正式 Holdout 只从历史已消费 Holdout 未覆盖的行中抽取。五份已消费 Holdout 共占 28,801 行，剩余 1,199 行不足以构成任何新的 6,000 行正式 Holdout。
- 报告产物一致性：Gate C 用绑定的指标、Agent 摘要和档案审核状态在内存中重渲染，核对完整正文、附表和数值索引。正文与附表允许表格首尾竖线等不改变单元格的写法；额外表格、改动的正文或附表及不完整的数值索引均不得审批。
- 报告与发布：报告表格必须能由 `validation_metrics.json` 逐单元格重建并一致（`verify_report_cells`），且每张表（表头签名）与每个行身份（前导标签列）必须唯一，Gate C 审批前强制执行；表格按 GFM 渲染语义解析（表体读到空行或其他块开始为止，短行补空、宽行截断，转义竖线不切分，引用块与列表内的表也计入），解析结果必须是渲染结果的超集；证据只能来自"已提交且工作区干净"的树，`worktree_clean_at_init` 必须为真、`git_commit_at_init` 必须等于被发布提交，并由 `release-check` 在标签树上复算 `verify_context` 与全量测试（先用 ledger 哈希校验并复制本机已获准 UCI ZIP，再以 junit 结果区分 passed/failed/skipped；pytest 退出码非零、存在失败或存在跳过都算缺口）。`acceptance.json` 必须恰好包含 V1-01～07 与 V2-01～07 各一次、全部 PASS、绑定同一 run 与发布提交，导出 ZIP 必须逐个成员核对内容哈希。`verify-context`、`release-check`、`report-status`、`verify-holdout-ledger`、`compare-command-log` 为只读命令，不写 run 目录；不提供任何截断或改写审计日志的命令，查看快照只能比对或把副本另存到 run 之外。只读命令的输出文件（`release-check --output`、`compare-command-log --save-copy`）只能以 `O_EXCL` 独占新建在 `runs/`、`dev_runs/`、`delivery/`、当前 runs 根目录与被检查 run 之外：父目录先解析符号链接，再按 inode 复核已打开目录的祖先；任何已存在的目标（含硬链接、符号链接）一律拒绝。

### 4.3 v3 验收标准

| ID | 验收动作 | 通过条件 | 证据 |
| --- | --- | --- | --- |
| V3-01 | 回归与固定数据复跑 | v1/v2 必测项全部通过；数值产物在声明容差内可复现；LLM 文本不要求逐字相同 | test_summary.md |
| V3-02 | 新环境复现 | 新虚拟环境、锁定依赖及容器按 README 跑通；网关可用时另跑一次真实 Agent；历史回放明确标注 | 环境、命令、版本与执行日志 |
| V3-03 | 五件套交付 | ≤10 页 Slides、≤3 分钟视频、README 代码仓库、1 页架构图（含组件、数据流、AI 模型）、1 页 Responsible AI note（含数据、隐私、偏差、限制、保护措施）；README 与 Deck 声明使用的 AI 工具和已有代码 | 提交材料清单与访问检查 |
| V3-04 | 业务价值证据 | 同一任务的手工/Agent 耗时含人工审核；记录样本数和操作者，不预设加速百分比 | impact_measurements.csv |
| V3-05 | 最终审核 | 无阻断缺陷；限制、未完成可选项、模型/数据性质清楚；两名成员互审关键结果 | final_review.md |
| V3-06 | 版本冻结 | 所有必交代码/材料对应唯一提交；工作区干净；验收通过后创建 v3 标签 | commit SHA、tag、release_checklist.md |

阻断缺陷：无法运行、误标通过、证据串用、测试泄露给 Agent、基准被改、代码越界执行或必交材料不可访问。外观优化、MLflow、额外图表不阻断既定范围。

## 5. API 接入验证

指定服务为 https://sa.kaiwen.dev 。实际接口和模型能力通过以下步骤验证。

1. 从服务控制台取得实际 API base URL、协议、模型 ID 和认证方式。
2. Key 仅配置在开发机环境变量；不写入 Git、日志、报告、截图或 Docker 测试容器。
3. 发一次简短请求，验证响应和错误类型。
4. 验证完整 Tool calling 往返：模型请求工具→本地调度固定工具→返回结果→模型完成回答。无原生支持时不得假称已支持；先停止并按 16.2 决策。
5. 若服务端支持 JSON Schema 则使用；无原生结构化输出时，本地 Pydantic 校验仍必做。解析失败最多一次格式重试；不得以字符串抽取伪造合法结果。
6. Agent 每轮最多 8 次模型请求（含重试），每次输出上限按实测可用范围设置，代码修复最多两次；默认超时、退避和重试次数写入配置并冻结。
7. API 不可用时页面可以展示清楚标识的历史运行；不能伪装现场成功，不能静默更换服务商。
8. **数据最小化**：发送给 LLM 的只有 R 代码、模拟旧文档、Schema 和汇总诊断；不发送 UCI 原始数据行，Holdout 输入与答案均不出本机。

Provider adapter 至少定义 `generate()` 和 `tool_roundtrip()`；具体 SDK 由协议验证结果决定。

## 6. 数据与模拟资产

### 6.1 数据来源与许可

| 项目 | 内容 |
| --- | --- |
| 数据集 | Default of Credit Card Clients（UCI Machine Learning Repository，ID 350） |
| 地址 | https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients |
| 原始出处 | Yeh, I-C. & Lien, C-H. (2009). The comparisons of data mining techniques for the predictive accuracy of probability of default of credit card clients. *Expert Systems with Applications*, 36(2). |
| 内容 | 台湾某银行 2005 年 4–9 月信用卡客户，30,000 行，23 个特征 + 1 个标签（下月是否违约）；违约 6,636 条，占 22.12% |
| 许可 | CC BY 4.0：可再分发与改编，须注明出处 |
| 个人数据 | 无姓名、证件号等直接标识，但含性别、年龄、学历、婚姻等人口属性（仅用于审计）。去除直接标识不足以证明已匿名化；能否满足比赛"不得使用个人数据"的要求，使用前须向主办方确认 |
| 分发 | 主办方确认前，原始文件不入 Git：提供下载脚本，写入 `data/raw/` 后校验 SHA-256，`SOURCE.md` 记录出处、许可与下载日期。确认可分发后，再决定是否随提交包附带 |

注意事项：

- 原始文件为 `.xls`，第一行是 X1–X24 的占位表头，第二行才是字段名；读取时需 `header=1`。
- 数据时间、地区与币种（新台币）均与英国银行不同；结果只用于演示方法，不推断英国客户。
- 下载后核对行数、违约数与编码取值，以实测为准写入数据字典。

### 6.2 字段与数据字典

统一使用 snake_case；月份序号 1 = 2005 年 9 月（最近），6 = 2005 年 4 月。

| 原字段 | 项目字段 | 含义 | 用途 |
| --- | --- | --- | --- |
| ID | client_id | 行编号 | 主键，不入模 |
| LIMIT_BAL | limit_bal | 授信额度（NT$，含家庭附卡） | 特征 |
| SEX | sex | 1=男，2=女 | **仅审计** |
| EDUCATION | education | 1=研究生，2=大学，3=高中，4=其他 | **仅审计** |
| MARRIAGE | marriage | 1=已婚，2=单身，3=其他 | **仅审计** |
| AGE | age | 年龄（岁） | **仅审计**（派生 age_band） |
| PAY_0, PAY_2–PAY_6 | pay_status_1–pay_status_6 | 还款状态：-1=按时还清，1–9=逾期月数 | 特征（派生） |
| BILL_AMT1–6 | bill_amt_1–bill_amt_6 | 账单金额（NT$，可为负值，UCI 未说明成因） | 特征（派生） |
| PAY_AMT1–6 | pay_amt_1–pay_amt_6 | 实际还款金额（NT$） | 特征（派生） |
| default payment next month | default_flag | 1=下月违约 | 标签，不入特征 |

**未文档化编码**（原始说明未定义，实际数据中存在）：

| 字段 | 取值 | 处理 |
| --- | --- | --- |
| education | 0、5、6 | 归入 4（其他），在数据字典中注明 |
| marriage | 0 | 归入 3（其他） |
| pay_status_* | -2、0 | 常见解读为"无消费"与"仅还最低额/循环信用"，**非官方定义**；派生 `delay_k = max(pay_status_k, 0)` 时二者均视为未逾期 |

注意原始字段名跳过 PAY_1（PAY_0 之后是 PAY_2），重命名时需显式映射，避免错位。

派生特征（只在 train 上拟合任何参数）：

- `log_limit = log1p(limit_bal)`
- `delay_k = max(pay_status_k, 0)`
- `util_k = clip(bill_amt_k / limit_bal, 0, 2)`（负值按 0 处理）
- `log_pay_k = log1p(pay_amt_k)`
- `age_band`：互斥区间 21–25、26–35、36–50、51+（数据最小年龄为 21）

### 6.3 数据划分

| 文件 | 数量 | 用途 | Agent 权限 |
| --- | ---: | --- | --- |
| train.csv | 15,000 | 训练三个 R 模型、学习预处理参数 | 不提供给 Agent 修复流程 |
| dev.csv | 6,000 | 迁移调试、开发指标、稳定性参考分布 | 仅受控样例与诊断摘要 |
| holdout.csv | 6,000 | 候选冻结后的最终验收 | 输入及答案均不进入 Agent 上下文 |
| shift_pool.csv | 3,000 | 构造漂移批次的来源池，不参与训练和验收 | 不可见 |
| shifted.csv | 2,000 | 见 6.4 | 仅计算后指标摘要 |
| fixtures/* | 单独构造 | 缺失、非法值、边界及结构异常 | 只开放部分开发案例 |

按 `default_flag` 分层抽样，统一 NumPy RNG seed=42；配置与数据文件保存 SHA-256。划分编号冻结；缺失填补和其他拟合参数只来自 train。Holdout 一旦用于验收，其结果不再用于 Agent 修复；失败则本轮未通过，不反复调到通过。

### 6.4 漂移批次（Monitor 演示）

真实数据不能"改变特征后按公式重新生成标签"，因此分两种场景：

| 场景 | 构造 | 标签 | 可计算的指标 |
| --- | --- | --- | --- |
| A：真实子群漂移（必做） | 从 shift_pool 不放回加权抽取 2,000 行，权重偏向高 util_1 与低 limit_bal（模拟经济下行中的高负债人群） | 保留真实标签 | 特征/预测 PSI + 性能对比 |
| B：合成压力测试（可选） | 复制 shifted 场景 A 的特征，limit_bal × 0.8、bill_amt_* × 1.15 | **无有效标签** | 仅特征/预测 PSI，不计算性能 |

抽样权重与压力系数写入 `data_config.json`。改变分布不保证触发固定预警，实际结果如实报告。

### 6.5 固定样例（fixtures）

至少覆盖：正常行、缺失数值、负数/越界值（如 limit_bal ≤ 0、pay_status 超出 -2..9）、阈值附近、缺列、重复 ID、行序变化、列序变化、非数值字段、负账单（合法值，不应被拒绝）。列序变化是独立文件结构测试，不能在同一个 CSV 中只把某一行"列顺序打乱"。fixtures 为合成数据，在 README 中注明。

### 6.6 三个模型

| ID | 模型 | 预设文档问题 | 迁移范围 |
| --- | --- | --- | --- |
| MDL_CREDIT_V1 | glm 逻辑回归：`delay_1`、`log_limit`、`util_1`、`log_pay_1`；训练中位数填补；代码阈值 0.35 | 说明写 0.50，代码为 0.35；负责人和训练日期未知 | **唯一迁移对象** |
| MDL_CREDIT_V2 | 逻辑回归：V1 特征 + `delay_2`、`delay_3`、6 个月平均 util；阈值 0.30 | 缺独立说明，未写输入约束 | 建档，不自动迁移 |
| MDL_CREDIT_TREE | rpart 浅层树，maxdepth=3，输入 pay_status_1–6、limit_bal、util_1 | 未记录超参数与限制 | 建档，不自动迁移 |

R 基准对所有模型输入进行显式预处理和校验，避免依赖 glm 默认 NA 行为。对 V1，以下为无效输入：limit_bal ≤ 0 或缺失后无法填补的结构错误、pay_status_1 不是 -2..9 的整数、pay_amt_1 < 0、非数值；负 bill_amt_1 为合法输入。人口属性一律不入模。JSON 系数保留足够双精度有效数字，示例值不作为真实训练结果。特征清单为初始设定，B 建模时如调整须同步修改本节与数据字典。

（是否把 V1 改为 WoE 评分卡见 16.1，待团队确认。）

## 7. 架构、状态机与隔离

### 7.1 数据流

v1 迁移流程：待迁移模型的 R 代码和模拟旧文档 → Agent 提取该模型的档案 → Gate A 确认 → Agent 生成 Python → Gate B 批准代码哈希 → Docker 开发测试 → 最多两轮修复与重新批准 → 冻结候选 → 独立 Holdout 验收。

v2 补齐其余两个模型的档案并通过 Gate A，再计算四类指标、由 Agent 解释并生成报告，最后经 Gate C 审阅。

### 7.2 状态与工具

主状态：INVENTORY_REVIEWED → CANDIDATE_APPROVED → CANDIDATE_FROZEN → FINAL_EVALUATED → REPORT_REVIEWED。草稿、开发测试等中间过程记录在运行日志中，不单独作为状态门槛。

异常状态：FAILED、BLOCKED、NOT_RUN。拒绝审核后回到对应草稿；变更输入/代码/配置哈希时，相关下游审核失效。预测性能低不等于执行失败，报告保留警示，不擅自训练新模型。

固定工具：`read_asset`（允许列表内文件）、`validate_inventory`、`submit_candidate`、`run_dev_tests`、`read_dev_diagnostics`。Holdout 评估为验证端入口，不开放为 Agent 工具。模型只能请求工具，执行与权限检查由 Python 调度器负责。

### 7.3 Docker 边界

- `--network none`、非 root 用户、只读根文件系统、丢弃 capabilities、禁止提权。
- 初始约束：内存 512MB、1 CPU、PID 上限 64、每次候选 30 秒；超时终止整个容器，资源不够则记录后显式修改配置。
- 输入/候选只读挂载，输出到独立运行目录；不挂载宿主根目录、API 凭证或 Docker socket。
- 生成代码的执行容器只看到允许的输入与参数，不看到测试源码和基准答案。
- 受信验证器在独立进程中读取输出并比较基准，不能 import 生成代码到持有保留集的进程。
- 镜像预先构建；运行时不联网安装依赖。容器隔离适用于本地预置资产演示，不承诺抵御所有恶意代码。

### 7.4 审核执行方式：人工审核与代理审核

Gate A/B/C 的判定标准不因执行方式而变，只区分由谁执行：

- **人工审核**：`reviewer` 填审核人姓名，由审核人本人阅读档案或候选源码后签字。
- **代理审核**：`reviewer` 填 `agent-delegated`，由被明确授权的执行者代行审核。代理必须实读完整档案与候选源码（不得只看摘要），逐条核对来源行号与文件 SHA-256，核对候选完整 64 位哈希，并把授权来源与逐项核对内容写入审批备注。未实读即审批属于违规。
- 两种方式共用同一门禁：Gate A 哈希为档案内容（排除 `review_status`）的规范 JSON SHA-256，Gate B 哈希为候选源码完整 SHA-256；顺序固定为 Gate A → 生成候选 → Gate B → 容器执行，跳步或哈希不符一律拒绝。
- 输入、配置、`src/`、`tests/` 或候选哈希变化后，既有审批立即失效，须对新哈希重新审核；被拒绝的审批不算通过。
- 审批记录写入 `review_log.json`（含 reviewer、decision、reviewed_artifact_sha256、context_sha256、timestamp）与 `command_log.jsonl`，人工与代理记录可区分且可追溯。
- 代理审核不改变 V1-01～V1-07 任何判定标准；测试替身或 mock 候选仍不能通过 V1-06。

### 7.5 Holdout 单次消费与 campaign

数据划分的 campaign seed 由 `config/data_config.json` 的 `seed` 固定（总行数、四份行数、违约率容差、UCI URL 仍为不可变常量），写入 `data_manifest.json`，`prepare --seed` 必须与配置一致。一次性账本 `runs/holdout_consumption.jsonl` 以 `(model_id, campaign_id, dataset_sha256)` 记账：同一 campaign 的 Holdout 只能被消费一次，无论成功与否都不重跑、不用于调参。

seed 变更会创建新 campaign。正式 Holdout 还须通过历史排除校验，确保与已消费 Holdout 零重叠，并达到 6,000 行。变更原因写入 README 与验收记录，保留旧 campaign 的 Holdout 结果与账本。历史上 v1 的 seed 42 已消费 Holdout，V1-07 因命令链记账缺陷失败。随后 seed 43 的 Holdout 单次消费并通过，两份划分存在 1,199 行重叠，现均计入排除集。

## 8. 迁移与数值验收契约

逻辑回归复现：

$$
z=\beta_0+\sum_{j=1}^{k}\beta_jx_j,\qquad p=\frac{1}{1+e^{-z}}
$$

复用 R 训练的系数、特征顺序、派生特征公式、填补参数与阈值。Python 重新训练的模型不能代替本项迁移证明。

- **记录完整性**：ID 唯一；输入/基准/候选 ID 集合完全一致，禁止仅 INNER JOIN 后丢弃记录。
- **Probability parity（概率等价）**：有效记录预测有限且在 [0,1]；最大绝对误差 ≤1e-8，平均绝对误差 ≤1e-10。均为项目阈值，正式验收前冻结。
- **Classification parity（分类等价）**：统一 `p >= 0.35` 为 1；所有有效记录分类一致。阈值附近样例单独列出，差异需查明，不能排除后标记全通过。
- **Behavioural parity（行为等价）**：缺失值填补标记、错误码和拒绝行为逐记录一致。
- 无有效记录、预测为空、少行、多行、NaN、非数值、重复 ID 均不能通过；每种错误有独立状态。

核心误差：

$$
\Delta_{\max}=\max_i|p_i^{(R)}-p_i^{(Python)}|
$$

`predict_ported` 只负责预测；`parity` 工具负责比较。退出码：0=执行成功且验收通过，1=验收失败，2=输入/配置/执行错误。故意错误测试应"成功发现失败"，因此整个 pytest 测试套件仍可以通过；不得要求总测试命令本身永久红灯。

## 9. 验证指标与解释边界

### Performance（性能与校准）

ROC-AUC、Brier score 与十分位校准表使用原始预测概率，与分类阈值无关；混淆矩阵使用阈值 `p >= 0.35`。同时输出类别数量。只有单一真实类别时 ROC-AUC = null 并注明 NOT_ASSESSABLE。

$$
\operatorname{Brier}=\frac{1}{N}\sum_{i=1}^{N}(p_i-y_i)^2
$$

Brier 同时反映概率预测的多个方面，不能单独当作纯校准指标。**必做**十分位校准表：按预测概率等频分 10 组，列出每组样本数、平均预测概率与实际违约率（对应官方 "calibrate"）。校准图为可选。证据口径：holdout 为同一时期的随机留出集，属于**样本外验证**；漂移批次 A 为加权抽样子群，属于**样本构成变化的敏感性分析**。二者都不是 Back-test（回测）。本数据无法做跨时间（out-of-time）回测，报告须把它列为尚缺的证据。

### Stability（稳定性）

以 dev 的固定参考分布比较 shifted 的特征和预测概率。可计算 PSI：

$$
\operatorname{PSI}=\sum_{b=1}^{B}(Q_b-P_b)\ln\left(\frac{Q_b}{P_b}\right)
$$

分箱边界仅由参考集生成，包含越界尾部；重复分位点合并。每箱计数加固定伪计数后分别重新归一化，记录实际箱数与平滑参数。

演示预警可配置为 0.10/0.25，对应提示/需复核；这是内部演示规则，不是通用监管标准。预警可置 `REVALIDATION_REQUIRED`（需复核验证），只显示任务状态，不执行真实银行下线或重训。不承诺模拟变化必然越过 0.25。

### Fairness（公平性）

审计属性：age_band（21–25、26–35、36–50、51+）与 sex。按组计算样本数、正负样本数，以及阈值 `p >= 0.35` 下的 TPR 和 FPR：

$$
\operatorname{TPR}=\frac{TP}{TP+FN},\qquad \operatorname{FPR}=\frac{FP}{FP+TN}
$$

总样本少于 30 时整组标记低样本；正例少于 5 时 TPR 不可评估，负例少于 5 时 FPR 不可评估。阈值是项目保护规则，不是统计充分性保证。差值参考组取训练集中样本最多的组，数据加工后写入配置冻结；参考组对应指标不可评估时差值也不可评估。

不加入 DI 比率及 80% 合规结论，避免把"预测违约为 1"误解为有利选择。群体差异是审计信号；未触发预警不等于公平已证明。数据来自 2005 年台湾样本，群体差异不能外推到其他人群。

## 10. 模块接口与运行证据

每次运行生成唯一 `run_id`，保存配置、输入 SHA-256、候选代码哈希、Git commit、模型 ID、提示词版本、时间与阶段状态。所有模块产物通过 run_id 与 manifest（清单）关联；不覆盖上一次结果。

| Contract（契约） | 必需字段 | 写入者 |
| --- | --- | --- |
| model_inventory.json | schema_version、run_id、模型档案（v1 为 MDL_CREDIT_V1，v2 为三个模型）、来源/哈希、特征、Unknown、文档矛盾、审核状态 | Agent 提取后经校验器保存 |
| migration_result.json | model_id、candidate_sha256、attempt、dev_status、final_status、diagnostics_ref | 受信调度器 |
| validation_metrics.json | dataset_sha256、阈值、样本量、parity/performance/calibration/stability/fairness、值/状态/原因/证据路径 | 受信验证程序 |
| review_log.json | gate、decision、reviewer、timestamp、comment、reviewed_artifact_sha256 | 人工审核入口 |

附属文件：`manifest.json`、`data_manifest.json`、`agent_audit_log.jsonl`、`provider/request_log.jsonl`、`parity_diff.csv`、`validation_report.md`。整数、空值和状态按 Schema 校验，不允许 NaN/Infinity 混入 JSON。

指标示意（占位，不是运行结果）：

```json
{
  "schema_version": "1",
  "run_id": "<generated-run-id>",
  "model_id": "MDL_CREDIT_V1",
  "parity": {
    "status": "NOT_RUN",
    "max_abs_diff": null,
    "classification_mismatch_count": null,
    "reason": "Awaiting final evaluation"
  }
}
```

来源至少含文件哈希、行范围或 JSON path。程序能验证路径/行号存在、摘录匹配和数字一致性，但不能仅凭有效行号证明自然语言结论正确。关键语义及 Unknown 保留由人工确认，不声称彻底消除幻觉。

## 11. 界面与用户流程

1. **Inventory（清单）**：显示三个模型、最新 run_id、状态与历史记录。
2. **Model detail（详情）**：代码与来源、缺口、代码/文档阈值矛盾，Gate A 确认或退回。
3. **Migration（迁移）**：生成候选、显示 diff、Gate B 批准当前代码哈希、执行、修复次数、开发结果；冻结后由验证入口运行保留集。
4. **Validation report（报告）**：四组指标（含校准表）、限制、运行来源、Gate C 审阅；下载 MD/CSV/JSON。

界面由主机可信模块控制，容器不能改审核记录。审核者字段是本地自报标识，不冒充认证身份。v1、v2 的验收都可以通过 CLI 完成；Streamlit 四页是演示目标，时间不足时可减少页面，但审核关卡与导出不能省。

API 超时、解析失败、达到请求上限、容器失败或修复耗尽：停止对应阶段、保存失败原因、提供明确重试入口。重试计入请求次数；新候选需重新审核。历史结果显示原 run_id、时间和 REPLAY（回放）标识。

## 12. 目录与运行手册

```text
model-risk-factory/
  README.md
  requirements.txt
  docs/                    # 背景、SOP、官方 PDF
  config/                  # 已冻结的阈值、数据配置与 schema
  data/raw/                # 下载脚本写入 UCI 原始文件（默认不入 Git）+ SOURCE.md
  data/processed/          # train/dev/holdout/shift_pool/shifted
  data/fixtures/           # 合成异常样例
  legacy/                  # 三个 R 模型
  legacy/notes/            # 模拟旧文档（含预设缺陷）
  artifacts/reference/     # 基准参数与预测，Agent 不可写
  src/
    cli.py
    data.py
    inventory.py
    provider.py
    agent.py
    runner.py
    parity.py
    validation.py
    report.py
    contracts.py
  tests/                   # 受信测试，Agent 不可修改
  docker/
  runs/<run_id>/
  delivery/
  app.py
```

### 12.1 运行手册（v1 已实现，按 README 实测命令整理）

以下命令均在仓库根目录执行，入口为 `python -m src.cli`。CLI **只从当前 shell 的环境变量**读取网关配置，不会自动加载 `.env`，所以所有步骤必须在**同一个终端**中完成。V1-07 只接受首轮全部 exit 0 的命令链，任何一步失败都应新建 run 从第 1 步重来。

**第 0 步：前置条件。** 需要 Python 3（实测 3.15.2）、Docker（实测 29.9.2，需先启动 Docker Desktop），已获得主办方对 UCI 数据使用的确认，以及网关 API key。

**第 1 步：导入环境变量。** 复制模板，填入真实值。`.env` 已被 gitignore，不得提交。

```bash
cp .env.example .env
# 编辑 .env，推荐取值（与 v1 正式 run 一致）：
# LLM_BASE_URL=https://sa.kaiwen.dev/v1
# LLM_CHAT_COMPLETIONS_URL=https://sa.kaiwen.dev/v1/chat/completions
# LLM_PROTOCOL=openai_chat_completions
# LLM_MODEL=deepseek-v4.1-flash:1017
# LLM_API_KEY=            # 留空，下面交互式输入，避免写入磁盘
# LLM_TIMEOUT_SECONDS=300
# LLM_MAX_OUTPUT_TOKENS=32768   # 过小（如 8192）会截断候选

set -a; source .env; set +a        # 把 .env 全部 export 到当前 shell
printf 'LLM API key: ' >&2; read -rs LLM_API_KEY; export LLM_API_KEY; echo
env | grep '^LLM_' | sed 's/\(LLM_API_KEY=\).*/\1***/'   # 自查，不回显密钥
```

注意：`.env.example` 中的 `LLM_BASE_URL` 不带 `/v1`，以上述实测值为准。`LLM_MODEL` 留空时使用 `config/provider_config.json` 的 `default_model`。

**第 2 步：Python 环境与受信测试。**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q                 # 预期：103 passed, 7 subtests passed
```

**第 3 步：Docker 镜像。**

```bash
docker pull rocker/r-ver:4.4.2                          # R 基准
docker build -t model-risk-factory-runner:v1 docker     # 候选执行镜像
```

**第 4 步（可选）：合成数据冒烟测试。** 不需要 API key，只用来验证本地环境，不计入正式验收。

```bash
SEED=$(python -c 'import json; from pathlib import Path; print(json.loads(Path("config/data_config.json").read_text())["seed"])')
RUN_ID=$(python -m src.cli init-run --mode synthetic | python -c 'import json, sys; print(json.load(sys.stdin)["run_id"])')
python -m src.cli prepare --run-id "$RUN_ID" --synthetic --seed "$SEED"
for c in baseline reference-parity fixture-parity mutation-check; do python -m src.cli $c --run-id "$RUN_ID" || break; done
```

**第 5 步：创建正式 run 并检查网关（V1-01）。**

```bash
export PYTHONDONTWRITEBYTECODE=1
SEED=$(python -c 'import json; from pathlib import Path; print(json.loads(Path("config/data_config.json").read_text())["seed"])')   # 当前 campaign 为 43
RUN_ID=$(python -m src.cli init-run --mode uci | python -c 'import json, sys; print(json.load(sys.stdin)["run_id"])')
echo "$RUN_ID"
python -m src.cli check-provider --run-id "$RUN_ID"
```

网关偶尔返回 504，或工具往返内容不合规。此时不要在同一 run 中重试，而是重新执行第 5 步。

**第 6 步：UCI 数据、R 基准与参考验证（V1-02～05）。**

```bash
UCI_SHA=56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602
python -m src.cli download-uci --run-id "$RUN_ID" --expected-sha256 "$UCI_SHA" --approve-uci-use
python -m src.cli prepare --run-id "$RUN_ID" --uci data/raw/default_of_credit_card_clients.zip \
  --expected-sha256 "$UCI_SHA" --approve-uci-use --seed "$SEED"
python -m src.cli baseline --run-id "$RUN_ID"
python -m src.cli reference-parity --run-id "$RUN_ID"
python -m src.cli fixture-parity --run-id "$RUN_ID"
python -m src.cli mutation-check --run-id "$RUN_ID"
```

`--approve-uci-use` 表示操作者声明已获主办方确认，程序不会自动取得许可。`--seed` 必须等于配置中的 seed，否则会被拒绝。

**第 7 步：Agent 建档与 Gate A。**

```bash
python -m src.cli extract-inventory --run-id "$RUN_ID"
python -m src.cli status --run-id "$RUN_ID"      # 输出档案哈希与完整审批命令
python -m src.cli approve --run-id "$RUN_ID" --gate Gate_A \
  --sha256 '<status 显示的档案哈希>' --reviewer '<姓名 或 agent-delegated>' --comment '<实际核对内容>'
```

审核者需核对以下内容：来源行号与摘录、四项 Unknown、特征顺序 `delay_1,log_limit,util_1,log_pay_1`，以及代码阈值 0.35 与文档阈值 0.50 的冲突。该冲突必须保留，不得自动归一。

**第 8 步：真实候选、Gate B 与开发测试。**

```bash
python -m src.cli generate-candidate --run-id "$RUN_ID" --attempt 0
python -m src.cli show-candidate --run-id "$RUN_ID" --attempt 0     # 审阅 diff、源码、64 位哈希
python -m src.cli approve --run-id "$RUN_ID" --gate Gate_B --attempt 0 \
  --sha256 '<candidate_sha256>' --reviewer '<姓名 或 agent-delegated>' --comment '<实际核对内容>'
python -m src.cli run-dev --run-id "$RUN_ID" --attempt 0
python -m src.cli candidate-fixtures --run-id "$RUN_ID" --attempt 0
```

开发测试失败时，用 `--attempt 1`、`--attempt 2` 重复第 8 步，每个新哈希都要重新通过 Gate B，最多修复两次。（已知缺陷：修复后 V1-07 仍会因链上有失败记录而 FAIL，见 README「已知工具缺陷」，留待 v2 处理。）

**第 9 步：冻结、一次性 Holdout、验收与导出（V1-06、V1-07）。**

```bash
python -m src.cli freeze --run-id "$RUN_ID" --attempt 0     # 换成实际通过的 attempt
python -m src.cli accept --run-id "$RUN_ID"                 # Holdout 每个 campaign 只能消费一次
python -m src.cli acceptance --run-id "$RUN_ID"             # 逐项输出 V1-01～07
python -m src.cli export --run-id "$RUN_ID"                 # 最后一步，之后不再写入该 run
```

产物位置：`runs/$RUN_ID/` 为全部运行证据；`delivery/${RUN_ID}_acceptance.json` 与 `delivery/${RUN_ID}_evidence.zip` 为可分享的白名单证据包。退出码约定为：0 表示通过，1 表示验收失败，2 表示输入、配置或执行错误。

**常见错误。**

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `check-provider` 报 `LLM_*` 配置缺失（BLOCKED） | 新开了终端，或没有执行 `set -a; source .env` | 回到第 1 步 |
| `prepare` 拒绝 seed | 手写了 `--seed 42` | 从 `config/data_config.json` 读取 seed |
| 候选 `finish_reason=length` | `LLM_MAX_OUTPUT_TOKENS` 过小 | 设为 32768，并新建 run |
| `accept` 拒绝重跑 | 该 campaign 的 Holdout 已被消费 | 保留结果。新 campaign 须有 6,000 行符合历史排除规则的 Holdout，见 §7.5 |
| Gate 审批失效 | 修改了 `src/`、`tests/`、`config/` 或候选 | 对新哈希重新审批，必要时新建 run |

v2 正式验收通过 CLI 执行。Streamlit 界面留待 v3 演示。

## 13. 分工与里程碑

A=用户本人（AI 工程主线），B=队友（建模验证主线）。两人互审对方关键产物，但不称为银行独立验证。

| 工作包 | 分工 | 交付 |
| --- | --- | --- |
| UCI 数据加工、数据字典、三个 R 模型与基准 | B | 数据配置、R 资产、预测基准 |
| Python 参考实现、固定测试及验证指标 | B 主责，A 协作 | parity、validation、受信测试 |
| API、Agent、结构化输出与修复循环 | A | provider、agent、工具日志 |
| Docker 执行器与运行记录 | A 主责，B 协作 | runner、manifest、隔离测试 |
| 报告导出与 Streamlit 演示界面 | A 主责，B 协作 | report、app |
| 集成与故意失败案例 | A、B | 集成检查、失败证据 |
| Slides、说明材料、录屏 | B 主责，A 协作 | 提交五件套 |

### 日期与版本退出条件

| 日期 | 版本任务 | 分工 | 当天退出条件 |
| --- | --- | --- | --- |
| ~~11-08~~ ✅ | ~~v1：接入关卡与基准资产~~ | A 负责 API、契约与调度。B 负责 UCI 下载、数据字典、划分和 R 模型 | API 能力查清；数据划分及一个 R 模型可跑 |
| ~~11-09~~ ✅ | ~~v1：单模型建档、等价性工具与 Agent 生成~~ | A 负责档案提取、最小 Docker、CLI 与 Agent 生成/修复循环。B 先准备待迁移模型的旧文档，再负责参考实现、等价性工具与故意错误测试 | V1-01～05 通过；待迁移模型的档案先通过 Gate A，Agent 再生成候选并经 Gate B 后在容器中跑开发测试 |
| ~~11-10~~ ✅ | ~~v1：真实迁移验收~~ | A 负责候选冻结与 Holdout 验收流程。B 负责指标程序与其余两个模型的旧文档资产 | V1-01～07 通过，创建 v1 验收记录 |
| 11-11 | v2：档案、验证报告与审核 | A 负责档案提取、审核关卡、导出与界面。B 负责四类验证、故障测试与材料 | V2-01～07 通过；材料初稿 |
| 11-12 | v3：新环境复现与冻结 | A、B 共同完成复现测试、缺陷修复、材料和录屏 | V3-01～06 通过；功能冻结、最终标签 |
| 11-13 | 提交检查 | 处理提交事项及必要阻断缺陷 | 主办方最终时间确认、访问检查、提交回执 |
| 11-19 后 | 决赛准备（如入围） | 不新增功能 | 见 15.5 |

预计无法按期满足验收条件时，按下述规则缩减范围。

### 缩减与范围变更

按已确认优先级：不做 MLflow/复杂监控/装饰图表 → 减少 Streamlit 页面 → 修复上限两次减为一次（配置与报告说明）→ 取消可选校准图与漂移场景 B。保留真实 API 流程、单模型迁移、四类验证（含十分位校准表）、审核、失败检测与提交材料。

如果仍无法满足 v2 必交项，应明确版本未通过并提出范围变更，不偷偷删验收项。React/FastAPI、数据库、云部署、任意模型上传、SAS 转换、真实个人数据、自动 PDF 均不在 v1/v2/v3 中新增。

## 14. 执行 SOP：从开工到最终版

1. ~~**Prepare（准备）**：核对报名/题目/日期；检查 Python、R、Docker；确认 API 能力；冻结配置与契约。~~ ✅
2. ~~**Acquire data（取数）**：下载 UCI 原始文件，记录 SHA-256 与许可；按数据字典处理编码；固定种子分层划分；只在 train 学习参数；构造漂移批次与 fixtures；建立三个 R 模型和预设文档缺口。~~ ✅
3. ~~**Establish baseline（建立基准）**：B 保存基准与哈希；A 无权通过 Agent 修改基准；先完成参考预测及故意错误检测。~~ ✅
4. ~~**Document & migrate（单模型建档与迁移）**：开放允许列表工具；Agent 根据 R 代码和旧文档提取 MDL_CREDIT_V1 档案；Gate A 通过后才生成 credit_v1 候选；Gate B 批准代码哈希后，在最小 Docker 中执行开发测试与受限修复。~~ ✅
5. ~~**Freeze candidate（冻结候选）**：保存代码哈希；独立运行 Holdout；失败不泄露答案后反复修复；记录失败和后续处理。~~ ✅
6. ~~**Accept v1（验收原型）**：逐项执行 V1 检查；记录实际结果、环境和差异；通过后创建 v1 标签。~~ ✅
7. **Complete inventory, validate & review（补齐档案、验证与审阅）**：补齐其余两个模型的档案并经 Gate A，确认三份档案均已通过审核；计算四类指标、生成来源可追溯报告并经 Gate C；加固容器边界；测试超时、请求上限与无效输出。
8. **Accept v2（验收正式版）**。完成一次性正式 Holdout、全部 v1 与 v2 验收和证据导出。对同一提交执行 `release-check`，返回 `APPROVED` 后创建 v2 标签。
9. **Finalize（最终交付）**：新环境复现、实测业务价值、完善五件套、录屏、两人互审。
10. **Accept v3（验收最终版）**：V3 全通过，保存最终 commit 与 v3 标签；冻结功能。11-13 核对链接和回执。

验收记录统一字段：acceptance_id、version、expected、actual、status、evidence_path、reviewer、timestamp、commit_sha。状态只允许 PASS/FAIL/NOT_RUN/BLOCKED；全部必测项 PASS 才能放行。

## 15. 交付材料与演示

### 15.1 五件套

| 材料 | 官方限制 | 本项目内容 |
| --- | --- | --- |
| Solution deck | 最多 10 页 | 见 15.3 |
| Demo video | 最多 3 分钟，链接 | 正常与失败流程；历史回放与现场调用清晰区分 |
| Code repository | 链接 + README + setup steps | 运行环境、配置、命令、测试、数据来源与许可、AI 工具与已有代码声明、限制、版本 |
| Architecture diagram | 1 页：components、data flows、AI models | Agent、调度器与固定工具、Docker 执行器、受信验证器、证据存储、三道审核关卡；标出数据流向（哪些数据发给 LLM、哪些只留本机）与实际使用的 LLM 模型 ID |
| Responsible AI note | 1 页：data used、privacy、bias、limitations、safeguards | 见 15.4 |

### 15.2 AI 工具与已有代码声明（官方必需）

README 与 Deck 中列出：

- **开发阶段**：Claude Code（设计文档整理、代码辅助）、grill-me / grilling skill（设计访谈）及其他实际使用的编程助手，说明各自做了什么；
- **产品内**：通过 sa.kaiwen.dev（或最终采用的服务）调用的 LLM 模型 ID，用于档案提取、Python 候选生成与报告解释；
- **已有代码与数据**：开源库（R glm/rpart/jsonlite，Python pandas/scikit-learn/Streamlit 等）、UCI 数据集及出处；
- 哪些代码由 Agent 生成、哪些由人工编写（参考实现是人工的，不能标为 Agent 迁移）。

### 15.3 Solution deck 大纲（≤10 页，数字一律在实测后填写）

| 页 | 标题 | 内容 | 对应评分 |
| --- | --- | --- | --- |
| 1 | Title & Summary | 队名、Challenge 04、一句话价值主张、实测结果摘要 | Presentation |
| 2 | Client problem | ~250 个模型、文档过时、8–12 周验证、PRA SS1/23 背景（标注为客户示意数据） | Business Impact |
| 3 | Approach & Architecture | Discover → Document → Redevelop → Validate → Monitor，人工关卡与职责边界 | Technical |
| 4 | Inventory & gap detection | 三个模型档案、Unknown 保留、代码与文档阈值矛盾 | Innovation |
| 5 | R → Python parity | 系数级移植、逐记录对比结果、故意改错被拦截 | Technical |
| 6 | Validation & monitoring | 性能、校准表、漂移 PSI、群体差异与限制 | Technical / RAI |
| 7 | Measured business impact | 15.6 实测对比表、扩展到 250 个模型的批量化路径 | Business Impact |
| 8 | Responsible AI | 数据与隐私、溯源校验、代码隔离、人工审核、局限 | Responsible AI |
| 9 | Prototype walkthrough | 界面或 CLI 运行截图流 | Presentation |
| 10 | Roadmap | SAS 解析、MLflow/Azure ML 接入、真实历史数据回测、治理委员会流程；AI 工具声明 | Business Impact |

禁止在运行前写入 AUC、误差或"100% 检出"等数字。客户约 250 个模型及 8–12 周验证是官方题目中的客户背景，不是本工具实测成果。

### 15.4 Responsible AI note（1 页）五个模块

1. **Data used**：UCI Default of Credit Card Clients（CC BY 4.0，2005 年台湾样本，无直接标识但含人口属性，能否用于比赛待主办方确认）；fixtures 与漂移场景 B 为合成数据；三个旧模型及旧文档为团队自建。
2. **Privacy**：人口属性只用于审计、不入模；不向 LLM 发送原始数据行，只发送代码、文档和汇总诊断；API key 只在本机环境变量。
3. **Bias**：按 age_band 与 sex 审计 TPR/FPR；人口属性不入模；小样本组标记 NOT_ASSESSABLE；未触发预警不等于公平。
4. **Limitations**：结果不代表英国银行客户或真实生产模型表现；缺少跨时间回测；Agent 文本可能出错，引用存在不等于语义正确；不是独立验证或监管认证。
5. **Safeguards**：指标由确定性 Python 程序计算；生成代码只在无网络 Docker 中执行；Holdout 不进 Agent 上下文；三道审核关卡（人工或经授权的代理，见 7.4）；请求与修复次数上限；失败如实记录。

### 15.5 三分钟视频与决赛演示

视频流程：

- 0:00–0:25：业务问题、三个旧模型与预设文档缺口。
- 0:25–1:00：Agent 档案、来源及 Unknown；展示 Gate A。
- 1:00–1:45：候选代码、执行批准、等价性结果；耗时步骤使用明确标识的预先运行记录。
- 1:45–2:20：性能、校准、漂移及公平性与限制。
- 2:20–2:45：故意错误被固定验证器发现；不能冒充 Agent 自动修复成功。
- 2:45–3:00：报告下载、人工审阅与后续路线。

决赛（如入围，11-23）：每队 10 分钟，建议 7 分钟陈述 + 3 分钟现场演示，之后评委就方法、证据和 Responsible AI 提问。准备：

- 本机完整环境 + **离线回放模式**（不依赖 API 与场地 Wi-Fi，界面标注 REPLAY）；现场调用仅在网络和网关可用时进行；
- 视频作为最后备份；
- 准备 Q&A 要点：为什么用 UCI 数据、等价性阈值依据、Holdout 隔离、Agent 失败时怎么办、扩展到 250 个模型的路径。

### 15.6 业务价值实测方法（Business Impact 30%，同分决胜项）

同一预置任务、同样文档字段和检查标准，分别记录手工与 Agent + 人工复核的总耗时、遗漏和返工，写入 `impact_measurements.csv`：

| 维度 | 手工基线（实测） | Agent + 人工复核（实测） | 证据 |
| --- | --- | --- | --- |
| 单模型建档耗时 | 人工阅读 R 代码与旧文档填表 | Agent 提取 + Gate A 审核 | agent_audit_log.jsonl 时间戳、审核记录 |
| 代码与文档矛盾检出 | 人工是否发现预设矛盾 | Agent 是否发现并给出来源 | model_inventory.json |
| 迁移等价性核对粒度 | 通常抽查或只看整体指标 | 全量逐记录对比 + 异常样例 | parity_summary.json |
| 漂移发现 | 定期人工抽检 | 自动 PSI 计算与状态提示 | validation_metrics.json |

记录样本数、操作者、是否已熟悉题目等影响因素；不得硬编码"人工审核 3 分钟"，也不能把自动运行时间单独当作总收益。

### 15.7 提交与自查

拟定提交：Monika.Rawal@exlservice.com；主题 `EXL Hackathon | Team name | Challenge 04`；用 UCD email；截止 2026-11-13 23:59 Irish time 待确认。仓库目前私有，必须确认评委实际有访问权限。

- [ ] 已确认题目开放、报名状态和最终截止时间。
- [ ] 已确认 UCI 数据可用于比赛，以及能否随提交分发。
- [ ] 三个模型有档案，一个 R 模型完成 Python 移植。
- [ ] 基准结果、数据划分、预处理和阈值可复现；UCI 文件哈希一致。
- [ ] Parity 测试比较逐记录概率与分类；故意错误会触发失败。
- [ ] 性能（含校准）、稳定性、公平性结果有实际计算依据。
- [ ] 未知、未运行和无法评估状态清楚区分。
- [ ] 数据来源与许可、自建模型、合成样例已声明。
- [ ] AI 工具与已有代码已声明。
- [ ] 架构图含数据流与 AI 模型；RAI note 含隐私。
- [ ] README 命令由新环境实际验证。
- [ ] 视频和仓库链接对评委可访问。
- [ ] 未将自动报告描述为独立验证或监管认证。

## 16. 待决事项与建议（需团队确认）

| # | 事项 | 建议 | 状态 / 负责人 |
| --- | --- | --- | --- |
| 16.1 | V1 是否改为 **WoE 评分卡** | 逻辑回归迁移本质是一次点积，等价性显得过于容易，Agent 价值不明显。银行信用模型常用 WoE 评分卡（分箱 → WoE → 逻辑回归 → 分数换算），迁移时有真实易错点：R `cut()` 默认右闭区间、缺失值单独成箱、分数取整。工作量增加有限，演示说服力更强 | 待 A/B 商定；若采纳，需改 6.6、第 8 节公式与 V1-04、V1-06 |
| 16.2 | API 网关风险 | sa.kaiwen.dev 的工具调用待验证，而真实 Agent 迁移属于 v1（11-10 截止）。11-08 当天完成 V1-01；不通过则由团队确认备选 API（如 Claude API），变更写入决策记录 | ✅ 已关闭：11-09 V1-01 PASS（deepseek-v4.1-flash:1017，openai_chat_completions，工具往返正常） |
| 16.3 | EXL 示例模型代码 | 向主办方确认是否发放；若发放，评估替换或追加为第 4 个模型，评委认可度更高 | 待询问 |
| 16.4 | MLflow / Azure ML | 官方偏好但非强制；时间允许时用本地 MLflow 记录运行，否则列入 Roadmap | 可选 |

## 17. Git、落盘与设计决策记录

仓库：https://github.com/wufangxun106334-pixel/model-risk-factory （Private）。

通过验收后才创建 v1/v2/v3 发布标签，不能因为写完 SOP 就打版本标签。项目 SOP 同步到 Obsidian Vault/黑客松时，以本文件为准。

| 决策 | 结果 |
| --- | --- |
| Q1–Q5 | 竞赛原型，本地演示，Python/AI 工程主线 |
| Q6–Q11 | Python/Streamlit/R/pytest/Docker，三个档案一个迁移，单 Agent，两次修复，分工 |
| Q12–Q17 | 预测移植，独立固定测试，四类证据，三审核关卡，缩减顺序 |
| Q18 | 指定 sa.kaiwen.dev；兼容性须实测 |
| Q19–Q23 | 四契约，失败停止，MD/CSV/JSON，双处落盘和本地提交 |
| 最终追加约束 | 只做 v1 原型、v2 正式版、v3 最终版；每版明确验收 |
| Q24 | 数据使用 UCI Default of Credit Card Clients；合成数据只用于漂移压力场景与异常样例 |
| Q25 | 交付须含 AI 工具声明、架构图数据流与 AI 模型、RAI 隐私；校准表必做；规划决赛演示 |
| 审核执行方式（v1 实现） | 允许代理审核（`reviewer=agent-delegated`）；与人工审核共用哈希校验、审批顺序、失效与重审规则，备注须记录授权来源与核对内容；V1 判定标准不变（见 7.4） |
| campaign seed（v1 实现） | seed 由 `config/data_config.json` 固定，`prepare --seed` 必须一致；变更即新 campaign，Holdout 每 campaign 单次消费（见 7.5） |

## 18. 来源与待核实事项

- 官方 PDF：[docs/official/EXL_UCD_Data_AI_Hackathon_2026.pdf](official/EXL_UCD_Data_AI_Hackathon_2026.pdf)；解读见 [01_比赛背景与官方要求.md](01_比赛背景与官方要求.md)。
- [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)：数据、字段说明与许可。
- [grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me) 与 [grilling](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md)：分轮设计访谈方法；说明见 [03_grill-me方法说明.md](03_grill-me方法说明.md)。
- [指定 API 网关](https://sa.kaiwen.dev)：协议、模型及工具调用支持待核实。
- [R glm 文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/glm.html) 与 [predict.glm 文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/predict.glm.html)：模型与预测参考。

待核实：活动报名/题目开放/截止时间；UCI 数据实际行数、违约率与编码取值（下载后确认）；API 详细能力；开发机工具可用版本；队友能否按分工参与。遇到这些事实不成立，应记录 BLOCKED 并明确调整，不虚构已完成。
