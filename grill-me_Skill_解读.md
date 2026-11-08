# grill-me Skill 解读（mattpocock/skills）

> Source: https://github.com/mattpocock/skills/tree/main/skills/productivity/grill-me
> 抓取日期：2026-11-08
> 用途：黑客松项目在 coding 之前，用 grill-me 把 idea / plan 拷问 (stress-test) 清楚。

---

## 1. 一句话理解

`grill-me` = 一个 **relentless（无情的、不停歇的）interview**，Agent 不断向你提问，直到你和它对 plan 达成 **shared understanding（共识）**。
它本身只是一个 **wrapper（外壳）**，真正的逻辑在底层 primitive skill `grilling` 里。

| Skill | 谁触发 | 特点 |
| --- | --- | --- |
| `grill-me` | 只能用户手动 `/grill-me` (`disable-model-invocation: true`) | **stateless（无状态）**，不写文件，不需要 repo，任何话题都能用 |
| `grilling` | 用户或 model 都可触发 | 核心 interview 机制（primitive，原语） |
| `grill-with-docs` | 用户 | **stateful（有状态）**，读 codebase，并写 `GLOSSARY.md` 和 ADR |
| `wayfinder` | 用户 | 项目太大时，先画 map，再在每个 decision ticket 里跑 grilling |

⚠️ 只安装 `grill-me` 不够 —— 它的 body 只有一句 “Call the Skill tool with grilling”，必须同时装 `grilling`。

---

## 2. 原文文件

### 2.1 `skills/productivity/grill-me/SKILL.md`

```markdown
---
name: grill-me
description: A relentless interview to sharpen a plan or design.
disable-model-invocation: true
---

Call the Skill tool with "grilling".
```

### 2.2 `skills/productivity/grill-me/agents/openai.yaml`

```yaml
interface:
  display_name: "Grill Me"
  short_description: "Sharpen a plan through interview"
policy:
  allow_implicit_invocation: false
```

### 2.3 `skills/productivity/grilling/SKILL.md`（真正的核心）

```markdown
---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

    ❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

    ➡️ <your recommended answer>

    ---

    ❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

    ➡️ <your recommended answer>

Word each question so "yes" accepts your recommended answer.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent with a fresh context window to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.
```

---

## 3. 核心概念（Key Concepts）

### 3.1 Design Tree（设计树）
把整个 plan 建模成一棵树：每个 **decision（决策）** 下面挂着依赖它的子决策 (decisions that *hang off*（挂在…下面）it)。

### 3.2 Frontier（前沿 / 边界）
所有 **prerequisites（前置条件）** 已经 **settled（确定）** 的 decision 集合 —— 也就是"现在就能问、不用猜答案"的问题。

### 3.3 Round（轮次）
一轮 = 把整个 frontier 一次问完。用户答完后，frontier 向外推进 (push outward)，**unblock（解锁）** 新问题，再 **recompute（重新计算）** 下一轮。
- 同一轮里的问题必须 **互不依赖**；依赖本轮未决问题的，放到下一轮。
- 典型节奏：13 个问题 ≈ 3 rounds，而不是 13 rounds。

### 3.4 Question Format（问题格式）
```
❓ **Q1** - **标题**: 问题正文（可含多个选项）
➡️ 推荐答案
```
- 每题都有 **recommended answer（推荐答案）**，单独一行 `➡️`。
- 措辞要让 “yes” = 接受推荐答案 → 你可以按编号回复：“1 yes, 2 选第二个, 3 no 因为…”。
- 已知问题：推荐答案有时和问题措辞相反，这时直接回应推荐答案并说明。

### 3.5 Facts vs Decisions（事实 vs 决策）
| 类型 | 谁负责 | 做法 |
| --- | --- | --- |
| **Facts（事实）** | Agent | 能从 environment（文件系统、工具）查到的，派 **sub-agent** 去查，不要问用户；查询期间不 **block（阻塞）** 其他问题 |
| **Decisions（决策）** | 用户 | 必须交给用户，并等待回答；Agent 自问自答 = skill 跑坏了 |

### 3.6 结束条件（Termination）
frontier 为空 —— 树的每个 branch 都 visited，没有 **silently assumed（默认假设）** 的东西。
**之后不能直接开工**，必须等用户确认 “we have a shared understanding”（confirmation gate，确认关卡）。

---

## 4. 使用建议（来自官方 docs）

1. **何时用**：一有值得认真对待的 idea 就用，不要等想清楚 —— **vagueness（模糊）** 正是它要消除的。
2. **开新对话**：在 fresh conversation 里启动，不要叠在 Agent 已写好的 plan 上。
3. **关掉 plan mode**：plan mode 会让 Agent 急着出 plan，而你要的是它继续问。
4. **不要 passive（被动）**：连续 “agreed, agreed…” 40 次 = 你什么都没决定，结果只是 Agent 的 opinion。要 **push back（反驳）**、指出 scope **drifting（跑偏）**、诚实说 “I don't know”。
5. **Grillable vs Ungrillable**：
   - “一个长表单还是三页？” “交互感觉如何？” 这种 **ungrillable（聊不出来的）** 问题 → 停止 grilling，先做 throwaway **prototype（一次性原型）**，看完再回来一句话回答。
6. **问题太多（如 200 个）**：scope 太大 → 先拆小再分别 grill；也可能进入 context window 过满的 “dumb zone”。
7. **想一次只问一个问题**：在全局 `CLAUDE.md` 加
   ```
   When grilling, ask one question at a time.
   ```
   （B2 英语用户这一条可能更友好。）
8. **结束后**：不要开新 session，直接把同一段对话交给 `to-spec` 写 spec，保留已建立的 context。
9. **Model 选择**：grilling 依赖模型对 "系统如何崩坏" 的知识，用最强 model；implementation 阶段可用便宜 model。

### It's working if（成功信号）
- 你至少反驳过一次。
- 问题分少数几轮到达，后面的轮次明显基于你之前的回答。
- 你最终到达一个没预料到的结论 —— 某个问题暴露了你一直无意识在做的 decision。
- 结束时你能向不在场的人 **defend（辩护）** 每一个选择。
- 结尾它停下来请你确认，而不是自己开始写代码。

---

## 5. 黑客松中怎么用

```
/grill-me   （或 /grilling）
我们要做 Challenge04 银行模型风险管理……（贴 idea）
```
流程：`grill-me`（idea → decisions）→ `to-spec`（decisions → spec）→ 实现。
如果要对着 repo 对齐术语、留 ADR，用 `grill-with-docs`。

### 安装到 Claude Code（可选）
把 `grill-me/` 和 `grilling/` 两个文件夹复制到 `~/.claude/skills/` 下即可（两个都要装）。

---

## 生词表（Vocabulary）

| 英文 | 中文 |
| --- | --- |
| relentless | 无情的、不停歇的 |
| grill | （口语）拷问、盘问 |
| sharpen | 打磨、使更清晰 |
| prerequisite | 前置条件 |
| frontier | 前沿、边界 |
| hang off | 挂在…下面、依附于 |
| unblock | 解除阻塞 |
| dispatch | 派遣、分派 |
| silently assumed | 被默认假设的 |
| stateless / stateful | 无状态 / 有状态 |
| primitive | 原语、基础构件 |
| passivity | 被动 |
| push back | 反驳、抵制 |
| drift | 漂移、跑偏 |
| throwaway | 一次性的 |
| defend | 辩护 |
| truncate | 截断 |
