---
title: Challenge 04 银行模型风险管理项目 SOP
created: 2026-11-05
updated: 2026-11-08
tags:
  - 黑客松
  - EXL-UCD
  - Model-Risk
  - Agentic-AI
status: design-confirmed
release_plan: v1-prototype / v2-formal / v3-final
---

# Challenge 04：银行模型风险管理项目 SOP

> SOP = Standard Operating Procedure（标准操作流程）。本设计经 grill-me / grilling 分轮访谈确认，2026-11-08 收敛为三个版本。文档描述待实现的设计，不代表代码已经完成或测试已经通过。
>
> 活动依据为 EXL × UCD 的原 Programme proposal（活动方案）。Challenge 04 开放状态、报名状态和最终提交时刻仍需主办方确认。下述实现、预算、阈值与版本计划属于团队决策，不是额外官方要求。

## 1. 项目定位与固定边界

**一句话：分析三个预置旧 R 模型，生成可追溯档案；将其中一个逻辑回归预测流程移植到 Python，通过固定测试验证等价性，再生成包含性能、稳定性与公平性结果的人工审核报告。**

目标用户：演示中的模型审阅者。目标是能在三分钟演示中看懂、有实际运行证据、能按 README 复现的 Hackathon prototype（竞赛原型）。个人学习主线为 Python / AI Engineering（AI 工程）。

### 1.1 题意与实现的对应

| 原活动要求 | 本项目实现 |
| --- | --- |
| 3–5 个模型的文档与清单 | 三个自建 R 模型，分别建立档案、来源与未知项 |
| 一个 SAS 或 R 模型重新实现为 Python，提供等价性证明 | 选择 R 逻辑回归，保留参数与预测行为，不以重新训练代替迁移 |
| 自动生成性能、稳定性、公平性验证报告 | Python 计算指标，Agent 解释，Markdown 模板承载报告 |
| 建议包含监控与人工审核 | 模拟批次变化及可配置预警，三个人工审核关卡 |
| Azure ML、MLflow 等工具偏好 | 当前使用本地文件记录；MLflow 为可选后续项，不是本次三个版本的必交项 |

### 1.2 已确认约束

- 团队：两人，每人总投入 30h，合计 **60 人时**，含集成、测试、材料、录屏和缓冲。
- 开发日期：2026-11-08 至 11-12，11-12 Feature freeze（功能冻结）；11-13 只处理提交事项及必要阻断缺陷。
- 运行：单机本地演示，录屏备用；无公网部署、多用户认证、独立后端或云数据库。
- 模型：三个预置 R 模型建档，只迁移一个；不承诺任意 SAS/R 模型转换。
- 数据：全部自行生成，不使用真实个人数据；合成结果不证明真实银行预测能力。
- Agent：单 Agent、固定阶段、Tool calling（工具调用）、最多两轮代码修复。
- 生成代码：仅在受限 Docker container（容器）内运行；不开放任意外部代码上传。
- API：用户指定 https://sa.kaiwen.dev ，总预算上限 €10；具体协议、模型、能力与价格待接入验证。
- 输出：Markdown 报告、CSV 差异、JSON 证据；自动生成 PDF 不在实现范围内。
- 只做 **v1、v2、v3**。不追加 v4，也不以“正式版”为理由扩大为生产银行平台。

## 2. 核心知识与学习顺序

| 顺序 | Knowledge（知识） | 能解释和验证的内容 |
| --- | --- | --- |
| 1 | Logistic regression（逻辑回归） | 特征、系数、截距、概率、阈值之间的关系 |
| 2 | Preprocessing（预处理） | 仅用训练集拟合缺失值填补参数，固定特征顺序与输入规则 |
| 3 | Parity（等价性） | 相同输入的 R/Python 概率、分类、异常处理是否一致 |
| 4 | Model validation（模型验证） | 数据划分、ROC-AUC、Brier score、混淆矩阵、群体错误率 |
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
| 数据与计算 | NumPy、pandas、scikit-learn、SciPy | 合成数据、对齐、指标与数值计算 | 锁定实际可运行版本 |
| 数据契约 | Pydantic | 校验清单、迁移结果、指标、审核记录 | 本地校验必做；服务端结构化输出待实测 |
| 测试 | pytest | 固定契约、等价性、异常与故障测试 | 不允许 Agent 修改评分规则 |
| 执行隔离 | Docker | 执行生成 Python、隔离验证过程 | 无网络、只读根目录、资源与时间限制 |
| LLM 接入 | Provider adapter（服务适配层） | 屏蔽具体协议、记录用量和错误 | 协议确认后再选 SDK，不预设 OpenAI 兼容 |
| 状态与结果 | CSV / JSON / JSONL / Markdown | 数据、元信息、日志、报告 | 单用户本地文件，无数据库 |
| 版本管理 | Git | 代码、设计与交付版本 | v1/v2/v3 三个通过验收的 Git tags（标签） |

Docker Desktop、R 和 Python 需在开发机实际验证。依赖版本在接入与首次运行后锁定，不在设计文档里编造已验证版本。

## 4. 版本定义与发布门禁

**v1 是 Prototype（原型）；v2 是正式版；v3 是最终版。** 正式版指本次竞赛固定范围内的完整实现，不代表可直接用于银行生产。技术阶段可拆成任务，不能再衍生额外发布版本。

| 版本 | 日期目标 | 必须完成 | 放行条件 |
| --- | --- | --- | --- |
| **v1 Prototype** | 11-09 结束前 | API 最小验证；合成数据；一个 R 基准；人工参考 Python 实现；独立等价性工具；正常/故意错误案例；最小本地界面或 CLI | V1-01 至 V1-06 全满足；一条从输入到报告的窄流程可复现；已实现与占位功能清楚区分 |
| **v2 正式版** | 11-11 结束前 | 三份 Agent 档案；一个真实 API 生成/修复流程；三审核关卡；Docker；四页界面；四类验证；完整运行证据与导出 | V2-01 至 V2-09 全满足；无阻断缺陷；所有 v1 验收继续通过 |
| **v3 最终版** | 11-12 结束前 | 集成复测、新环境复现、交付五件套、三分钟视频、最终 Git 版本；不再新增功能 | V3-01 至 V3-06 全满足；全部必交文件可访问；冻结范围和已知限制写入 README |

版本失败时不得创建对应通过标签，也不得在展示中说已经完成。修复后仍归属同一版本，不新增 v1.1/v4 等计划。未完成 v2 就不能把 v3 包装为“最终通过”。

### 4.1 v1 验收标准

| ID | Test（验收动作） | Pass（通过条件） | Evidence（证据） |
| --- | --- | --- | --- |
| V1-01 | API smoke test（最小调用） | 指定网关真实请求成功；确认协议、模型 ID、工具往返及输出解析；用量和费用可核算；不能确认时阻断 Agent 接入 | 脱敏的 capability_check.json、请求 ID、用量记录 |
| V1-02 | 数据生成与划分 | 1800/600/600/1000 行，ID 唯一且主数据集互不交叉；固定种子；数据与配置哈希记录 | 数据清单、划分测试 |
| V1-03 | R 基准 | V1 模型可重跑，系数/预处理/开发预测输出有效，未把 ID 或标签当特征 | R sessionInfo、产物清单 |
| V1-04 | Python 参考实现等价性 | 主键一一对齐、概率与分类、缺失与拒绝行为满足第 8 节；不得只比较 Accuracy | parity_summary.json、parity_diff.csv |
| V1-05 | 故意错误案例 | 改变一个系数的隔离副本被固定测试发现；原始基准及测试哈希不变 | 预期失败测试与差异 |
| V1-06 | 窄流程复现 | 按 README 从预置数据到基础报告运行成功；界面/CLI 真实结果非硬编码成果 | 命令、退出码、运行日志 |

v1 的人工 Python 实现是验证工具的开发基线；v2 必须另有真实 Agent 生成的候选实现。不能把人工实现标为 Agent 自动迁移。

### 4.2 v2 验收标准

| ID | 验收动作 | 通过条件 | 证据 |
| --- | --- | --- | --- |
| V2-01 | 三模型建档 | 三份档案符合 Schema；发现预设阈值矛盾；负责人等未知项保留 Unknown；关键事实含来源 | model_inventory.json、来源校验结果 |
| V2-02 | 真实 Agent 迁移 | 由实际 API 生成 credit_v1 候选；最多初始生成 + 两次修复；测试代码与基准不可写；最终保留集只在候选冻结后评估 | agent_audit_log.jsonl、代码及测试哈希 |
| V2-03 | 等价性验收 | 最终保留集全部符合第 8 节；失败则状态为 FAILED，不生成通过结论 | 保留集 parity_summary.json |
| V2-04 | 容器执行边界 | 容器无法联网和写基准/宿主目录；超时与资源边界可触发；容器内无 API key | 容器配置及边界测试结果 |
| V2-05 | 四类验证 | 等价性、性能、稳定性、公平性结果均来自程序；缺标签/单类/分母为零时明确状态 | validation_metrics.json、指标测试 |
| V2-06 | 审核状态机 | 未确认档案不能进入迁移；每个新代码哈希执行前需批准；报告未审阅不标记 APPROVED | review_log.json、关卡测试 |
| V2-07 | 四页闭环及导出 | 清单→详情→迁移→验证报告走通；MD/CSV/JSON 可下载且 run_id 一致 | 端到端检查记录 |
| V2-08 | 失败和预算处理 | API/解析/超时/修复耗尽/预算不足均保留失败记录，不伪造成功；累计成本不超过 €10 | 故障测试和用量账本 |
| V2-09 | 报告来源与限制 | 每个数值引用指标 JSON 路径；引用存在不等于语义真实，关键事实需人工复核；无合规认证措辞 | 报告、审核意见 |

### 4.3 v3 验收标准

| ID | 验收动作 | 通过条件 | 证据 |
| --- | --- | --- | --- |
| V3-01 | 回归与固定数据复跑 | v1/v2 必测项全部通过；数值产物在声明容差内可复现；LLM 文本不要求逐字相同 | test_summary.md |
| V3-02 | 新环境复现 | 新虚拟环境、锁定依赖及容器按 README 跑通；费用允许时另跑一次真实 Agent；历史回放明确标注 | 环境、命令、版本与执行日志 |
| V3-03 | 五件套交付 | ≤10 页 Slides、≤3 分钟视频、README 代码仓库、1 页架构图、1 页 Responsible AI note | 提交材料清单与访问检查 |
| V3-04 | 业务价值证据 | 同一任务的手工/Agent 耗时含人工审核；记录样本数、操作者、费用，不预设加速百分比 | impact_measurements.csv |
| V3-05 | 最终审核 | 无阻断缺陷；限制、未完成可选项、模型/数据性质清楚；两名成员互审关键结果 | final_review.md |
| V3-06 | 版本冻结 | 所有必交代码/材料对应唯一提交；工作区干净；验收通过后创建 v3 标签 | commit SHA、tag、release_checklist.md |

阻断缺陷：无法运行、误标通过、证据串用、测试泄露给 Agent、基准被改、代码越界执行、预算无法控制或必交材料不可访问。外观优化、MLflow、额外图表不阻断既定范围。

## 5. API 接入与费用关卡

指定服务：https://sa.kaiwen.dev 。公开首页标识为 Sub2API — AI API Gateway，设计确认时未取得可验证的接口/模型/计费文档。主页能打开不等于 API 能用。

1. 从服务控制台取得实际 API base URL、协议、模型 ID、认证方式和费率；不要凭主页推断 `/v1` 或某种兼容协议。
2. Key 仅配置在开发机环境变量；不写入 Git、日志、报告、截图或 Docker 测试容器。
3. 发一次简短请求，验证响应和错误类型。
4. 验证完整 Tool calling 往返：模型请求工具→本地调度固定工具→返回结果→模型完成回答。无原生支持时不得假称已支持；先停止并明确方案变更。
5. 若服务端支持 JSON Schema 则使用；无原生结构化输出时，本地 Pydantic 校验仍必做。解析失败最多一次格式重试，纳入成本；不得以字符串抽取伪造合法结果。
6. 记录 usage、币种、实际费率、兑换依据和累计 EUR 成本。仅有 token 数不能直接等于欧元费用。
7. 每次请求前预留输入与最大输出费用，累计已用 + 预留不得超过 €10；无法获得价格或控制上界时停止付费请求，先核实。
8. Agent 每轮最多 8 次模型请求（含重试），每次输出上限按实测可用范围设置，代码修复最多两次；默认超时、退避和重试次数写入配置并冻结。€8 开发、€2 最终演示为内部预留，不增加总预算。
9. API 不可用时页面可以展示清楚标识的历史运行；不能伪装现场成功，不能静默更换服务商。

Provider adapter 至少定义 `generate()`、`tool_roundtrip()`、`usage_to_cost()`；具体 SDK 由协议验证结果决定。

## 6. 数据与模拟资产

### 6.1 数据划分

| 文件 | 数量 | 用途 | Agent 权限 |
| --- | ---: | --- | --- |
| train.csv | 1800 | 训练三个 R 模型、学习预处理参数 | 不提供给 Agent 修复流程 |
| dev.csv | 600 | 迁移调试、开发指标、固定稳定性参考 | 仅受控样例与诊断摘要 |
| holdout.csv | 600 | 候选冻结后的最终验收 | 输入及答案均不进入 Agent 上下文 |
| shifted.csv | 1000 | 独立生成的模拟变化批次 | 仅计算后指标摘要 |
| fixtures/* | 单独构造 | 缺失、非法值、边界及结构异常 | 只开放部分开发案例 |

统一 NumPy RNG seed=42，配置与数据文件保存 SHA-256。划分编号冻结；缺失填补和其他拟合参数只来自 train。Holdout 一旦用于验收，其结果不再用于 Agent 修复；失败则本轮未通过，不反复调到通过。

字段：`application_id`、`annual_income`、`loan_amount`、`debt_to_income`、`employment_years`、`age_band`、`default_flag`。ID 不入模，标签不入特征；age_band 仅用于群体审计。年龄组采用互斥区间 18–25、26–35、36–50、51+。

基础范围：收入 18,000–250,000 EUR；贷款 2,000–80,000 EUR；债务比 0.05–0.85；工作年限 0–35。具体分布、采样参数写入 `data_config.json`，不得只写范围就声称已可复现。

可采用如下模拟标签机制，参数为演示设定：

$$
\eta_i=-2.40+3.80d_i+0.000035l_i-0.000020a_i-0.10e_i
$$

$$
p_i^{\mathrm{true}}=\frac{1}{1+e^{-\eta_i}},\qquad y_i\sim\operatorname{Bernoulli}(p_i^{\mathrm{true}})
$$

其中 d/l/a/e 分别表示债务比、贷款、收入与工作年限。不得把生成标签时使用的真实概率作为模型输入。

Shifted 批次先独立生成基础特征，再将收入乘 0.82、债务比加 0.12 并截断至 0.95。若需性能比较，必须按变化后的特征重新生成模拟标签；不直接沿用原标签。改变分布不保证触发固定预警，实际结果如实报告。

固定样例至少覆盖：正常行、缺失数值、负数/越界值、阈值附近、缺列、重复 ID、行序变化、列序变化、非数值字段。列序变化是独立文件结构测试，不能在同一个 CSV 中只把某一行“列顺序打乱”。

### 6.2 三个模型

| ID | 模型 | 预设文档问题 | 迁移范围 |
| --- | --- | --- | --- |
| MDL_CREDIT_V1 | glm 逻辑回归：债务比、贷款、工作年限；训练中位数填补；阈值 0.35 | 说明写 0.50，代码为 0.35；负责人和训练日期未知 | 唯一迁移对象 |
| MDL_CREDIT_V2 | 逻辑回归：增加 log1p(annual_income)；阈值 0.30 | 缺独立说明，未写输入约束 | 建档，不自动迁移 |
| MDL_CREDIT_TREE | rpart 浅层树，maxdepth=3 | 未记录超参数与限制 | 建档，不自动迁移 |

R 基准对所有模型输入进行显式预处理和校验，避免依赖 glm 默认 NA 行为。对 V1，贷款/债务比/工作年限越界是无效输入；不把未使用的收入字段作为 V1 预测拒绝的唯一依据。JSON 系数保留足够双精度有效数字，示例值不作为真实训练结果。

## 7. 架构、状态机与隔离

### 7.1 数据流

预置 R 代码和模拟笔记 → Agent 提取档案 → Gate A 确认 → Agent 生成 Python → Gate B 批准代码哈希 → Docker 开发测试 → 最多两轮修复与重新批准 → 冻结候选 → 独立 Holdout 验收 → 四类指标 → Agent 解释 + 模板报告 → Gate C 审阅。

### 7.2 状态与工具

主状态：CREATED → INVENTORY_DRAFT → INVENTORY_REVIEWED → CODE_DRAFT → EXECUTION_APPROVED → DEV_TESTED → CANDIDATE_FROZEN → FINAL_EVALUATED → REPORT_DRAFT → REPORT_REVIEWED。

异常状态：FAILED、BLOCKED、NOT_RUN、BUDGET_EXCEEDED。拒绝审核后回到对应草稿；变更输入/代码/配置哈希时，相关下游审核失效。预测性能低不等于执行失败，报告保留警示，不擅自训练新模型。

固定工具：`read_asset`（允许列表内文件）、`validate_inventory`、`submit_candidate`、`run_dev_tests`、`read_dev_diagnostics`。Holdout 评估为验证端入口，不开放为 Agent 工具。模型只能请求工具，执行与权限检查由 Python 调度器负责。

### 7.3 Docker 边界

- `--network none`、非 root 用户、只读根文件系统、丢弃 capabilities、禁止提权。
- 初始约束：内存 512MB、1 CPU、PID 上限 64、每次候选 30 秒；超时终止整个容器，资源不够则记录后显式修改配置。
- 输入/候选只读挂载，输出到独立运行目录；不挂载宿主根目录、API 凭证或 Docker socket。
- 生成代码的执行容器只看到允许的输入与参数，不看到测试源码和基准答案。
- 受信验证器在独立进程中读取输出并比较基准，不能 import 生成代码到持有保留集的进程。
- 镜像预先构建；运行时不联网安装依赖。容器隔离适用于本地预置资产演示，不承诺抵御所有恶意代码。

## 8. 迁移与数值验收契约

逻辑回归复现：

$$
z=\beta_0+\sum_{j=1}^{k}\beta_jx_j,\qquad p=\frac{1}{1+e^{-z}}
$$

复用 R 训练的系数、特征顺序、填补参数与阈值。Python 重新训练的模型不能代替本项迁移证明。

- **记录完整性**：ID 唯一；输入/基准/候选 ID 集合完全一致，禁止仅 INNER JOIN 后丢弃记录。
- **Probability parity（概率等价）**：有效记录预测有限且在 [0,1]；最大绝对误差 ≤1e-8，平均绝对误差 ≤1e-10。均为项目阈值，正式验收前冻结。
- **Classification parity（分类等价）**：统一 `p >= 0.35` 为 1；所有有效记录分类一致。阈值附近样例单独列出，差异需查明，不能排除后标记全通过。
- **Behavioural parity（行为等价）**：缺失值填补标记、错误码和拒绝行为逐记录一致。
- 无有效记录、预测为空、少行、多行、NaN、非数值、重复 ID 均不能通过；每种错误有独立状态。

核心误差：

$$
\Delta_{\max}=\max_i|p_i^{(R)}-p_i^{(Python)}|
$$

`predict_ported` 只负责预测；`parity` 工具负责比较。退出码：0=执行成功且验收通过，1=验收失败，2=输入/配置/执行错误。故意错误测试应“成功发现失败”，因此整个 pytest 测试套件仍可以通过；不得要求总测试命令本身永久红灯。

## 9. 验证指标与解释边界

### Performance（性能）

固定阈值下输出 ROC-AUC、Brier score、混淆矩阵、类别数量。只有单一真实类别时 ROC-AUC= null 并注明 NOT_ASSESSABLE。Brier 同时反映概率预测的多个方面，不能单独当作纯校准指标；校准图作为时间允许的附加项，不要求 ECE。

$$
\operatorname{Brier}=\frac{1}{N}\sum_{i=1}^{N}(p_i-y_i)^2
$$

### Stability（稳定性）

以 dev 的固定参考分布比较 shifted 的特征和预测概率。可计算 PSI：

$$
\operatorname{PSI}=\sum_{b=1}^{B}(Q_b-P_b)\ln\left(\frac{Q_b}{P_b}\right)
$$

分箱边界仅由参考集生成，包含越界尾部；重复分位点合并。每箱计数加固定伪计数后分别重新归一化，记录实际箱数与平滑参数，避免简单截断比例后不归一化。

演示预警可配置为 0.10/0.25，对应提示/需复核；这是内部演示规则，不是通用监管标准。预警可置 `REVALIDATION_REQUIRED`（需复核验证），只显示任务状态，不执行真实银行下线或重训。不承诺模拟变化必然越过 0.25。

### Fairness（公平性）

按模拟 age_band 计算样本数、正负样本数、TPR 和 FPR：

$$
\operatorname{TPR}=\frac{TP}{TP+FN},\qquad \operatorname{FPR}=\frac{FP}{FP+TN}
$$

总样本少于 30 时整组标记低样本；正例少于 5 时 TPR 不可评估，负例少于 5 时 FPR 不可评估。阈值是项目保护规则，不是统计充分性保证。差值参考组固定为 36–50；参考组对应指标不可评估时差值也不可评估。

不加入 DI 比率及 80% 合规结论，避免把“预测违约为 1”误解为有利选择。群体差异是模拟审计信号；未触发预警不等于公平已证明。

## 10. 模块接口与运行证据

每次运行生成唯一 `run_id`，保存配置、输入 SHA-256、候选代码哈希、Git commit、模型 ID、提示词版本、时间与阶段状态。所有模块产物通过 run_id 与 manifest（清单）关联；不覆盖上一次结果。

| Contract（契约） | 必需字段 | 写入者 |
| --- | --- | --- |
| model_inventory.json | schema_version、run_id、三个模型、来源/哈希、特征、Unknown、文档矛盾、审核状态 | Agent 提取后经校验器保存 |
| migration_result.json | model_id、candidate_sha256、attempt、dev_status、final_status、diagnostics_ref | 受信调度器 |
| validation_metrics.json | dataset_sha256、阈值、样本量、parity/performance/stability/fairness、值/状态/原因/证据路径 | 受信验证程序 |
| review_log.json | gate、decision、reviewer、timestamp、comment、reviewed_artifact_sha256 | 人工审核入口 |

附属文件：`manifest.json`、`agent_audit_log.jsonl`、`usage_ledger.jsonl`、`parity_diff.csv`、`validation_report.md`。整数、空值和状态按 Schema 校验，不允许 NaN/Infinity 混入 JSON。

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
4. **Validation report（报告）**：四组指标、限制、运行来源、Gate C 审阅；下载 MD/CSV/JSON。

界面由主机可信模块控制，容器不能改审核记录。审核者字段是本地自报标识，不冒充认证身份。v1 可先用最小 CLI/单页；v2 必须四个逻辑页面完整。

API 超时、解析失败、预算不足、容器失败或修复耗尽：停止对应阶段、保存失败原因、提供明确重试入口。重试仍计费；新候选需重新审核。历史结果显示原 run_id、时间和 REPLAY（回放）标识。

## 12. 目录和计划 CLI

```text
model-risk-factory/
  README.md
  requirements.txt
  config/                  # 已冻结的阈值、数据配置与 schema
  data/synthetic/          # train/dev/holdout/shifted
  data/fixtures/
  legacy/                  # 三个 R 模型
  docs/legacy_notes/
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

以下为**待实现命令契约**，不是已存在脚本。实现后 README 必须按实测修订：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# API capability check：接入验证，可能产生少量费用
python -m src.cli check-provider

# Prepare：生成固定数据、训练 R 模型和基准
python -m src.cli prepare --seed 42

# Run：本地工作流与人工审核在界面进行
streamlit run app.py

# Test：受信测试，不把保留集答案交给 Agent
pytest

# Acceptance：对已冻结、已批准的候选执行最终验收
python -m src.cli accept --run-id <run_id>

# Export：导出同一运行的证据包
python -m src.cli export --run-id <run_id>
```

配置示例只含 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 等变量名与占位符。费用、接口路径、模型参数以接入验证为准。数据集和参考文件如何分发须在 README 说明；运行日志脱敏后再决定是否入 Git。

## 13. 分工、体量与日期

A=用户本人（AI 工程主线），B=队友（建模验证主线）。两人互审对方关键产物，但不称为银行独立验证。

| 工作包 | 总人时 | A | B | 交付 |
| --- | ---: | ---: | ---: | --- |
| 合成数据、三个 R 模型与基准 | 8 | 0 | 8 | 数据配置、R 资产、预测基准 |
| Python 参考实现、固定测试及验证指标 | 12 | 1 | 11 | parity、validation、受信测试 |
| API、Agent、结构化输出与修复循环 | 12 | 12 | 0 | provider、agent、工具日志 |
| Docker 执行器与运行记录 | 5 | 4 | 1 | runner、manifest、隔离测试 |
| Streamlit 四页与报告导出 | 7 | 6 | 1 | app、report |
| 集成与故意失败案例 | 6 | 3 | 3 | 集成检查、失败证据 |
| Slides、说明材料、录屏 | 6 | 2 | 4 | 提交五件套 |
| Buffer（缓冲） | 4 | 2 | 2 | 缺陷修复与复现 |
| **合计** | **60** | **30** | **30** | 不额外叠加任务工时 |

### 日期与版本退出条件

| 日期 | 版本任务 | A/B 各自计划 | 当天退出条件 |
| --- | --- | --- | --- |
| 11-08 | v1：接入关卡与基准资产 | A 6h：API/契约/调度；B 6h：数据/R | API 能力与计费查清；数据切分及一个 R 模型可跑 |
| 11-09 | v1：参考迁移与失败检测 | A 6h：Docker/最小入口；B 6h：参考实现/固定测试 | V1-01～06 通过，创建 v1 验收记录 |
| 11-10 | v2：Agent 与三模型档案 | A 6h：生成/工具/修复；B 6h：指标/档案资产 | 三档案、真实候选、指标程序可串联 |
| 11-11 | v2：四页、审核与集成 | A 6h：界面/报告；B 6h：验证/故障测试/材料 | V2-01～09 通过；材料初稿 |
| 11-12 | v3：新环境复现与冻结 | A 6h、B 6h：各含 2h 缓冲，其余测试/材料/录屏 | V3-01～06 通过；功能冻结、最终标签 |
| 11-13 | 提交检查 | 原则上零开发；不得默认为新增预算 | 主办方最终时间确认、访问检查、提交回执 |

日期是计划，不代表前序任务已经完成。当天可用时间不足需从剩余 60h 内重排；预计超时立即按缩减规则处理。

### 缩减与范围变更

按已确认优先级：不做 MLflow/复杂监控/装饰图表 → 修复上限两次减为一次（配置与报告说明）→ 取消可选校准图。保留真实 API 流程、单模型迁移、四类验证、审核、失败检测与提交材料。

如果仍无法满足 v2 必交项，应明确版本未通过并提出范围变更，不偷偷删验收项。React/FastAPI、数据库、云部署、任意模型上传、SAS 转换、真实数据、自动 PDF 均不在 v1/v2/v3 中新增。

## 14. 执行 SOP：从开工到最终版

1. **Prepare（准备）**：核对报名/题目/日期；检查 Python、R、Docker；确认 API 能力及费用；冻结配置与契约。
2. **Generate（生成）**：固定种子生成数据，检测 ID/划分；只在 train 学习参数；建立三个 R 模型和模拟缺口。
3. **Establish baseline（建立基准）**：B 保存基准与哈希；A 无权通过 Agent 修改基准；先完成参考预测及故意错误检测。
4. **Accept v1（验收原型）**：逐项执行 V1 检查；记录实际结果、环境和差异；通过后创建 v1 标签。
5. **Build agent（构建智能体）**：开放允许列表工具；生成三模型档案；审核 Gate A；生成代码、Gate B、容器测试与受限修复。
6. **Freeze candidate（冻结候选）**：保存代码哈希；独立运行 Holdout；失败不泄露答案后反复修复；记录失败和后续处理。
7. **Validate & review（验证与审阅）**：计算指标、生成来源可追溯报告、Gate C；测试超时、预算与无效输出。
8. **Accept v2（验收正式版）**：四页流程与导出完整，V2 全通过；创建 v2 标签。
9. **Finalize（最终交付）**：新环境复现、实测业务价值、完善五件套、录屏、两人互审。
10. **Accept v3（验收最终版）**：V3 全通过，保存最终 commit 与 v3 标签；冻结功能。11-13 核对链接和回执。

验收记录统一字段：acceptance_id、version、expected、actual、status、evidence_path、reviewer、timestamp、commit_sha。状态只允许 PASS/FAIL/NOT_RUN/BLOCKED；全部必测项 PASS 才能放行。

## 15. 交付材料与三分钟演示

### 三分钟流程

- 0:00–0:25：业务问题、三个模拟旧模型与预设文档缺口。
- 0:25–1:00：Agent 档案、来源及 Unknown；展示 Gate A。
- 1:00–1:45：候选代码、执行批准、等价性结果；耗时步骤使用明确标识的预先运行记录。
- 1:45–2:20：性能、模拟变化、公平性及限制。
- 2:20–2:45：故意错误被固定验证器发现；不能冒充 Agent 自动修复成功。
- 2:45–3:00：报告下载、人工审阅与后续路线。

### 五件套

| 材料 | 限制 | 本项目内容 |
| --- | --- | --- |
| Solution deck | 最多 10 页 | 问题、范围、架构、档案、迁移、指标、实测价值、Responsible AI、演示、后续 |
| Demo video | 最多 3 分钟，链接 | 正常与失败流程；历史回放与现场调用清晰区分 |
| Code repository | GitHub 链接和 README | 运行环境、配置、命令、测试、限制、版本 |
| Architecture diagram | 1 页 | Agent、验证器、容器、证据与审核边界 |
| Responsible AI note | 1 页 | 合成数据、来源、幻觉限制、公平性限制、代码隔离、人工责任 |

不在 Deck 写预设 AUC、误差或 100% 检出率；实际运行后再填。客户约 250 个模型及 8–12 周验证是原方案背景，不是本工具实测成果。扩展到真实银行模型只列后续路线。

业务价值对照：相同预置任务、同样文档字段和检查标准，分别记录手工与 Agent + 人工复核总耗时、费用、遗漏、返工；明确样本量及学习顺序影响。不得硬编码“人工审核 3 分钟”或把自动运行时间单独当总收益。

拟定提交地址：Monika.Rawal@exlservice.com；主题 `EXL Hackathon | Team name | Challenge 04`；用 UCD email。拟定截止 2026-11-13 23:59 Irish time 仍待确认。仓库目前私有，必须确认评委实际有访问权限；不要求自动公开整个仓库。

## 16. Git、落盘与设计决策记录

仓库：https://github.com/wufangxun106334-pixel/model-risk-factory （Private）。

本次只修订设计文档并创建本地 Commit，不 Push。通过验收后才创建 v1/v2/v3 发布标签，当前不能因为写完 SOP 就打版本标签。

项目 SOP 为本次设计主文件；同步相同内容到 Obsidian Vault/黑客松。云盘同步完成状态由 Google Drive 客户端决定，本地写入成功不等于云端已同步。

| 决策 | 结果 |
| --- | --- |
| Q1–Q5 | 竞赛原型，2×30h，本地演示，Python/AI 工程主线，允许付费 API |
| Q6–Q11 | Python/Streamlit/R/pytest/Docker，三个档案一个迁移，单 Agent，两次修复，分工，€10 |
| Q12–Q17 | 预测移植，独立固定测试，四类证据，三审核关卡，60h，缩减顺序 |
| Q18 | 指定 sa.kaiwen.dev；兼容性与价格须实测 |
| Q19–Q23 | 1800/600/600 + 1000 数据，四契约，失败停止，MD/CSV/JSON，双处落盘和本地提交 |
| 最终追加约束 | 只做 v1 原型、v2 正式版、v3 最终版；每版明确验收 |

## 17. 来源与待核实事项

- [grill-me](https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me) 与 [grilling](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md)：分轮设计访谈方法。
- [指定 API 网关](https://sa.kaiwen.dev)：用户指定服务；协议、模型、价格、工具调用支持待登录控制台核实。
- [R glm 文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/glm.html) 与 [predict.glm 文档](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/predict.glm.html)：模型与预测参考。
- 原 EXL × UCD 活动 PDF 及仓库内活动解读：官方题意与提交格式依据；不把拟定内容当最新通知。

待核实：活动报名/题目开放/截止时间；API 详细能力与成本；开发机工具可用版本；队友实际到岗与每日时间。遇到这些事实不成立，应记录 BLOCKED 并明确调整，不虚构已完成。
