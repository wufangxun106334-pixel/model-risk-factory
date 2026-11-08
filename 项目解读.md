# EXL × UCD Data & AI Hackathon 2026 解读

> 原文：[EXL_UCD_Data_AI_Hackathon_2026.pdf](file:///Users/alex/Desktop/EXL_UCD_Data_AI_Hackathon_2026.pdf)
> 解读日期：2026-11-02。本文依据 PDF，不代表已核实的最新活动通知。
> 文件性质：Programme proposal（活动方案），部分内容仍为 Proposed（拟议）或 To be confirmed（待确认）。具体实现示例属于教学说明，不是额外官方要求。

## 1. 活动核心与参赛条件（第 1–5 页）

这是 EXL 与 UCD 的 Data & AI Hackathon（数据与人工智能限时开发竞赛），不是网络攻击比赛，也不是普通课程作业。

核心任务：2–4 名 UCD 学生组队，从四个企业问题中选择一个，用 Data & AI 构建解决方案，并用运行结果证明价值。

基本过程：理解业务问题 → Design（设计）方案 → Build（构建）原型 → Validate（验证）结果 → Present（展示）价值。

| 项目 | 文件要求 |
| --- | --- |
| 身份 | UCD 在读本科生、硕士生或博士生，专业不限 |
| 组队 | 每队 2–4 人 |
| 报名 | 使用 UCD email；可以先个人报名，再完成组队 |
| 选题 | 每队选择一个 Challenge（挑战题） |
| 提交 | 每队只提交一份作品 |
| 决赛 | 8 支队伍入围，线下展示 |
| 获奖 | 前 3 名 |

四个 Tracks（技术方向）：

- **GenAI & Agents**：生成式 AI 与智能体。
- **Predictive Analytics**：预测分析，例如信用风险预测。
- **Data Engineering**：数据工程，例如数据转换、集成与管道。
- **Responsible AI**：负责任 AI，考虑隐私、安全、偏差和限制。

Track 是技术方向，Challenge 才是需要选择的具体题目。一个 Challenge 可以涉及多个 Tracks。

**Agentic（由智能体驱动的）**：AI 根据任务调用工具、分析输入、生成代码或测试，再根据结果执行下一步。文件建议各关键阶段保留 Human review（人工审核）。

### 四个 Challenge 与四个 Track 的官方映射矩阵（第 5 页）

原文第 5 页明确每个 Challenge 均跨越多个 Tracks（包含 Primary focus 主攻方向与 Supporting 支撑方向）：

| Challenge | 客户背景与规模（Indicative 示意指标） | 关联 Tracks（技术方向） |
| --- | --- | --- |
| **01 Agentic healthcare integration** | Global healthcare client · ~45 hybrid systems（仅 ~25% 有可用 API，交付窗口 3–5 个月） | GenAI & Agents, Data Engineering, Responsible AI |
| **02 Agentic Power Platform migration** | Large UK insurer · ~30 Power Platform apps（受 FCA 与 GDPR 约束，交付窗口 2–3 个月） | GenAI & Agents, Data Engineering, Responsible AI |
| **03 Agentic data platform modernisation** | UK & Ireland insurer · ~1,200 ETL jobs, 400+ SAS programs（财务/精算/理赔报表，交付窗口 4–6 个月） | GenAI & Agents, Data Engineering, Responsible AI |
| **04 Agentic model risk factory** | Tier-1 UK retail bank · ~250 production models（受 PRA SS1/23 约束，单次验证耗时 8–12 周） | GenAI & Agents, Predictive Analytics, Responsible AI |

> 本地归档补充：桌面原 PDF 若已移动，可直接参考提取文本 [hackathon-extracted.txt](file:///Users/alex/Documents/ChatGPT/demo/hackathon-extracted.txt)。

## 2. Challenge 01：医疗系统集成（第 6 页）

**Agentic healthcare integration**：使用 AI Agents 帮助连接不同医疗系统。

### 业务问题与实际范围

企业约有 45 个系统，既包括 On-premise（本地部署），也包括 Cloud（云端）系统。只有约四分之一提供可用 API，手工开发系统连接缓慢且不一致。

比赛实际要求是集成 **3–5 个 Mock systems（模拟系统）**，不是集成全部 45 个。

### 关键概念

| 英文术语 | 中文解释 |
| --- | --- |
| Integration | 系统集成，让不同系统交换并理解数据 |
| Schema | 数据结构定义，如字段、类型和关系 |
| Adapter | 适配器，把某个系统的数据转换成统一格式 |
| HL7 v2 | 医疗信息交换消息标准 |
| FHIR | 医疗数据交换标准，按 Patient 等资源组织信息 |
| OpenAPI | 描述 HTTP API 接口的规范 |
| PHI | Protected Health Information，受保护的健康信息 |

### 实操步骤

1. **Build（搭建）** 模拟系统：例如患者 REST API、旧 SQL 数据库、CSV 文件源。
2. **Discover（识别）** 结构：让 Agent 读取字段、文档和样例。
3. **Map（映射）** 字段：例如把 `patient_id` 与 `patientId` 映射为统一字段。
4. **Generate（生成）** Adapter、API 和测试代码。
5. **Validate（验证）** 必填字段、格式、接口契约、安全和错误处理。
6. **Measure（测量）** 人工开发与 Agent 辅助开发的时间及一致性。

文件建议的流程：Discover → Design → Generate → Validate → Operate（运行维护）。

### 预期输出与常见错误

应展示可运行的集成流程、生成代码、测试结果，以及时间和质量的比较证据。可使用 Synthea synthetic FHIR data（合成医疗数据），文件偏好 Azure 与 .NET Core。

常见错误：只做医疗聊天机器人，没有展示 Agent 如何完成系统集成；仅连接接口而不检查字段含义和输出质量。

## 3. Challenge 02：Power Platform 应用迁移（第 7 页）

**Agentic Power Platform migration**：用 Agent 帮助把低代码应用迁移到 React、.NET Core 和 Azure 技术栈。

### 业务问题与实际范围

企业约有 30 个 Power Platform 应用，其业务逻辑分散在 Power Apps、Power Fx、Dataverse 和 Power Automate 中，且可能缺少文档。

比赛实际要求：迁移 **1–2 个示例 Power Apps**，其中必须至少包含 **一个 Power Automate flow（自动化工作流）**。目标包括 React、.NET Core 与 Cosmos DB。

### 关键概念

- **Migration（迁移）**：把旧系统功能和数据转移到新平台，保持业务行为正确。
- **Power Fx**：Power Apps 中的公式语言。
- **Dataverse**：Microsoft 的数据平台。
- **Behavioural parity（行为等价）**：新旧应用面对相同输入，产生相同业务行为。
- **IaC，Infrastructure as Code（基础设施即代码）**：通过代码定义和部署基础设施。

### 实操步骤

1. **Analyse（分析）** 原应用页面、公式、数据表与 Flow。
2. **Extract（提取）** Business rules（业务规则），例如不同金额对应不同审批路径。
3. **Design（设计）** React 页面、后端 API 和 Cosmos DB 数据结构。
4. 让 Agent **Generate（生成）** TypeScript、C# 和测试。
5. 使用相同输入分别运行新旧应用。
6. 比较计算结果、状态变化、流程分支与错误处理。

示例：员工提交报销 → 检查金额 → 经理审批 → 更新状态。若旧应用拒绝负数报销，新应用也必须拒绝。

### 预期输出与常见错误

输出应包括旧应用样例、迁移后的应用、业务规则说明、自动化流程和新旧行为对照测试。

常见错误：只重做 UI；遗漏 Power Automate flow；只测试成功路径，不测试无效输入与拒绝路径。

**待确认：EXL 提供的示例 Power Apps package。** 文件允许使用 Synthetic data（合成数据）或自行构建的应用。

## 4. Challenge 03：旧 ETL／SAS 迁移到 PySpark（第 8 页）

**Agentic data platform modernisation**：用 Agent 帮助迁移旧数据处理任务，并证明新旧输出一致。

### 业务问题与实际范围

保险公司约有 1,200 个旧 ETL jobs、400 多个 SAS programs。业务逻辑缺少文档，数据来源与转换关系不清楚。

比赛实际要求：迁移 **10–15 个示例旧任务**，涉及 T-SQL 和 SAS，目标为 PySpark。

### 关键概念

| 英文术语 | 中文解释 |
| --- | --- |
| ETL | Extract, Transform, Load：提取、转换、加载数据 |
| T-SQL | SQL Server 使用的 SQL 扩展语言 |
| SAS | 用于统计分析和企业数据处理的软件及语言 |
| PySpark | 使用 Python 操作 Apache Spark 的接口 |
| Lineage | 数据血缘，记录数据来源及转换关系 |
| Column-level lineage | 字段级血缘，解释每个输出字段来自哪些输入字段 |
| Reconciliation | 数据核对，证明新旧输出一致 |
| Lakehouse | 结合数据湖和数据仓库特点的数据架构 |
| Baseline | 基准结果，用于后续对照 |

### 实操步骤

1. 准备合成数据和 10–15 个旧任务。
2. 运行旧任务，保存 Baseline（基准结果）。
3. 分析每个输出字段依赖哪些输入字段和转换逻辑。
4. 让 Agent 翻译为 PySpark，并生成测试。
5. 使用同一批输入运行新任务。
6. 比较记录数、金额合计和每条记录的字段值。
7. 输出 Diff report（差异报告），解释不一致之处。

文件提到的数据分层：

- **Bronze**：原始数据。
- **Silver**：清洗和标准化后的数据。
- **Gold**：面向报表与业务分析的数据。

### 预期输出与常见错误

输出包括迁移代码、字段血缘、测试与新旧数据核对报告。可使用 Databricks Free Edition 或 PySpark。

核心是 **Record-for-record（逐记录）一致**。只证明新旧输出都是 1,000 行不够，还要检查字段值、重复记录、Null、日期转换和数值精度。

**题目状态：Proposed（拟议），仍需 EXL 确认。**

## 5. Challenge 04：银行模型风险管理（第 9 页）

**Agentic model risk factory**：建立可重复执行的模型文档化、重新实现和验证流程。

### 业务问题与实际范围

某银行约有 250 个信用、欺诈和定价模型，文档可能过期，单次验证耗时较长。

比赛要求：

1. 为 **3–5 个示例模型**生成文档与模型清单。
2. 将其中 **一个 SAS 或 R 模型重新实现为 Python**，提供等价性证明。
3. 自动生成包含性能、稳定性和公平性的验证报告。

### 关键概念

- **Model inventory（模型清单）**：记录用途、版本、输入、输出、负责人和限制。
- **Validation（验证）**：检查模型是否适合其使用场景。
- **Calibration（校准）**：预测概率与实际发生频率是否一致。
- **Fairness（公平性）**：不同群体是否存在不合理的性能差异。
- **Drift（漂移）**：数据分布或模型表现随时间变化。
- **Parity proof（等价性证明）**：证明重新实现后的模型保留原有行为。
- **Back-test（回测）**：使用历史数据检查模型表现。

### 实操步骤

1. 准备模型代码、数据和已有文档。
2. 让 Agent 提取变量、方法、假设、用途和限制。
3. 生成 3–5 份模型档案与 Inventory（清单）记录。
4. 先运行原 SAS／R 模型，保存预测 Baseline。
5. 将其中一个模型重新实现为 Python。
6. 比较原模型与 Python 模型的预测结果。
7. 生成性能、稳定性、公平性与限制报告。

文件第 9 页建议的官方五阶段 Gate（关卡）流程（每个 Gate 均保留 Human review 人工审核）：

1. **Discover（识别发现）**：Scan code and documents; build the model inventory（扫描代码与文档，构建模型清单）。
2. **Document（逆向文档化）**：Reverse-engineer methodology, variables and limits（逆向提取建模方法论、变量与模型限制）。
3. **Redevelop（重新实现）**：Re-implement SAS and R models in Python with tests（将 SAS 与 R 模型用 Python 重新实现并附带测试）。
4. **Validate（独立验证）**：Back-test, calibrate, check stability and fairness（历史回测、概率校准、检查稳定性与公平性）。
5. **Monitor（持续监控与重验证触发）**：Track drift and performance; trigger re-validation（跟踪分布漂移与性能衰减，自动触发重验证流程）。

### 预期输出与常见错误

输出包括模型档案、一个 Python 模型、等价性测试和自动验证报告。文件偏好 Azure ML 和 MLflow。

常见错误：只训练一个准确率高的模型，却没有文档化、迁移等价性和验证流程；把 Agent 生成的文字报告当成已经验证的事实。

文件提到 PRA SS1/23 作为模型风险管理背景。学生原型不等于获得监管合规认证。

**题目状态：Proposed（拟议），仍需 EXL 确认；EXL 示例模型代码也待确认。**

## 6. Timeline：时间安排（第 10–12 页）

以下均为 2026 年，依据 PDF；不是已核实的最新通知。

| 日期 | 事项 |
| --- | --- |
| 10 月 28 日 | Launch（启动），开放报名 |
| 10 月 28 日–11 月 3 日 | Registration（报名）与组队；截止日期待确认 |
| 10 月 28 日–11 月 13 日 | Build sprint（集中开发阶段） |
| 11 月 13 日 | Submission deadline（提交截止）；拟定为爱尔兰时间 23:59 |
| 11 月 14–18 日 | Pre-screening（初筛） |
| 最迟 11 月 19 日 | 公布 8 支入围队伍 |
| 11 月 23 日 11:00–13:00 | Grand finale（总决赛） |

决赛地点：**O’Connor Centre for Learning**。

PDF 将开发阶段称为“15 days”。实际工作应以最终公布的起止日期与提交截止时间为准。

以解读日期 2026-11-02 而言，如拟定日期沿用，报名窗口已经接近结束。PDF 未给出报名链接，不能把提交邮箱直接当作报名渠道。

### 决赛流程

| 时间 | 环节 |
| --- | --- |
| 11:00–11:10 | EXL 介绍 |
| 11:10–12:30 | 8 支队伍展示，每队 10 分钟 |
| 12:30–12:50 | Jury Q&A（评委问答） |
| 12:50–13:00 | 评议、公布结果与颁奖 |

每队建议分配：**7 分钟 Pitch（项目陈述）+ 3 分钟 Live demo（现场演示）**。

## 7. Submission：需要提交什么（第 13 页）

每队提交一份 Submission pack（材料包）。

| 材料 | 官方要求 | 内容重点 |
| --- | --- | --- |
| Solution deck | 最多 10 页 Slides | 问题、方法、架构、结果、Responsible AI、下一步 |
| Demo video | 最多 3 分钟，以链接提交 | 展示可运行的 Prototype（原型） |
| Code repository | GitHub 等链接 | README 与 Setup steps（启动步骤） |
| Architecture diagram | 1 页 | 组件、数据流与 AI 模型 |
| Responsible AI note | 1 页 | 数据、隐私、偏差、限制与保护措施 |

### README 应说明的内容

- 数据来源、数据性质及使用方式。
- 环境与依赖版本。
- API key 等参数的配置方式。
- Demo、测试和服务的运行命令。
- 已完成的功能与已知限制。
- 使用的 AI tools（AI 工具）及其作用。
- 使用的 Existing code（已有代码）及来源。

以下仅为 Python 项目的命令结构示例，不是官方规定，也不适用于所有题目：

```bash
git clone <repository-url>
cd <project-folder>

# Install：安装依赖
pip install -r requirements.txt

# Test：运行测试
pytest

# Run：启动项目
python app.py
```

### 提交渠道

```text
收件人：Monika.Rawal@exlservice.com

邮件主题：
EXL Hackathon | Team name | Challenge 0X
```

使用一名队员的 UCD email 发送。拟定截止时间：**2026-11-13 23:59，Irish time（爱尔兰时间）**；该具体时刻待确认。

### 数据与 AI 使用要求

- 每队只选择一个 Challenge，只提交一份作品。
- 使用 Public or synthetic data（公开或合成数据）。
- Never personal data（不得使用个人数据）。公开可下载不意味着可以忽略其中的个人信息。
- Declare（声明）使用的 AI 工具及已有代码。

## 8. Judging：评分标准（第 14 页）

| 维度 | 权重 | 核心问题 |
| --- | --- | --- |
| Business Impact，业务影响 | 30% | 为谁解决什么问题，收益如何测量？ |
| Technical approach，技术方案 | 25% | 方法是否合理，结果是否经过验证？ |
| Innovation，创新 | 20% | 相比现有做法，改进在哪里？ |
| Responsible AI，负责任 AI | 15% | 如何处理隐私、安全、偏差和限制？ |
| Presentation & Q&A，展示与问答 | 10% | 能否清楚解释，用证据支持主张？ |

每项按 1–5 分评分，再按权重计算。平分时优先比较 Business Impact。

可将总分表示为：

$$
S = 0.30B + 0.25T + 0.20I + 0.15R + 0.10P
$$

其中各项均为 1–5 分，分别对应表中的五个维度。该公式是对文件加权规则的数学表达。

项目陈述应解释：解决了什么问题，Agent 完成哪些步骤，输出如何验证，相比原流程改善多少。

例如，“用了三个 Agent”只是实现描述；“在相同样例任务上减少了多少处理时间，同时通过哪些一致性测试”才构成结果证据。所有数字都需要实际测量。

## 9. Rewards、FAQ 与待确认事项（第 15–18 页）

### 奖励与参与规则

- 前三名有奖励，具体奖品 To be confirmed（待确认）。
- 入围队伍获得认可证书，并向 EXL 领导现场展示。
- 入围者有机会被考虑用于 EXL internship（实习）招聘，不保证实习或录用。
- 可以使用任意语言或框架；文件在指定位置表达 Azure 等技术偏好。
- 可以使用 AI coding assistants（AI 编程助手），必须声明使用了什么及其作用。
- 强烈鼓励 Working prototype（可运行原型）；有充分论证的设计加部分原型，也可能得到较好评分。
- Ownership（所有权）与使用条款由正式活动条款确定，PDF 未给出最终答案。

### 双方职责

EXL 提供业务题目、起步指导、宣传材料、初筛、评委和奖励安排。UCD 负责学生宣传、报名组织、决赛场地等事项，教师联系人为可选安排。

### 待确认事项

1. 报名渠道与报名信息共享方式。
2. 报名截止日期，拟定为 11 月 3 日。
3. Challenge 03 与 Challenge 04 是否正式开放。
4. 是否向学生提供建议实现路径。
5. Challenge 02 的示例 Power Apps package。
6. 具体奖品与评委名单。
7. 决赛场地预订及 AV（视听设备）安排。
8. 正式 Ownership（所有权）及使用条款。

## 10. 交付前自查清单

以下是依据官方要求整理的核对工具，不增加官方提交项。

- [ ] 已确认参赛资格、报名方式、2–4 人队伍与所选题目。
- [ ] 已核对题目是否正式开放，尤其是 Challenge 03/04。
- [ ] 原型展示了 Agent 的实际作用。
- [ ] 已保留 Baseline（基准）与 Validation（验证）证据。
- [ ] 所有结果数字均来自实际测量。
- [ ] 数据符合 Public or synthetic data 要求，未使用个人数据。
- [ ] Solution deck 不超过 10 页。
- [ ] Demo video 不超过 3 分钟，链接可访问。
- [ ] Code repository 包含 README 与启动步骤。
- [ ] 已准备 1 页 Architecture diagram。
- [ ] 已准备 1 页 Responsible AI note。
- [ ] 已声明 AI 工具与已有代码。
- [ ] 邮件主题符合格式，并使用 UCD email。
- [ ] 已确认最终提交截止日期、时间和链接访问权限。
