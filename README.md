# Model Risk Factory

EXL × UCD Data & AI Hackathon 2026 — Challenge 04 Agentic model risk factory。

## 项目目标

分析三个预置的旧 R 信用模型，生成可追溯的模型档案（Model inventory）；用 AI Agent 将其中一个模型移植到 Python 并证明逐记录等价；自动生成包含性能、校准、稳定性与公平性证据的验证报告，每一步保留人工审核（Human review）。

## 当前状态

Planning（规划）阶段：仓库仅包含设计文档，尚未实现可运行原型。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/01_比赛背景与官方要求.md](docs/01_比赛背景与官方要求.md) | 比赛背景、任务、交付、评分、时间线；常见疑问（模型是什么、模型治理是什么、数据从哪来、为什么用 UCI 数据） |
| [docs/02_项目SOP.md](docs/02_项目SOP.md) | 唯一设计主文件：范围、v1/v2/v3 验收标准、数据方案、架构、指标、分工日期、交付材料、待决事项 |
| [docs/03_grill-me方法说明.md](docs/03_grill-me方法说明.md) | 设计访谈方法 grill-me 的说明 |
| [docs/official/EXL_UCD_Data_AI_Hackathon_2026.pdf](docs/official/EXL_UCD_Data_AI_Hackathon_2026.pdf) | 官方活动方案原文 |

## 计划范围

- 为三个自建 R 模型建立档案（含预设文档缺陷与 Unknown 项）。
- 完成一个 R → Python 模型移植及逐记录等价性测试。
- 数据：公开数据集 [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)（CC BY 4.0）；漂移压力场景与异常样例为合成数据。
- 生成可追溯报告，保留三道人工审核关卡。

## 声明

- 旧模型与旧文档为团队自建演示素材，不代表 EXL 或任何银行的生产资产。
- 数据来自已匿名化的公开数据集，不含个人数据；结果不代表真实英国银行模型表现，也不构成独立验证或监管合规认证。
- AI 工具与已有代码的使用情况将在实现后于本 README 中完整声明（官方提交要求）。
- 活动状态、截止时间和具体规则以主办方最新通知为准。
