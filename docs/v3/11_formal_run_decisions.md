# V3 正式 run 决策记录（H-01～H-04）

记录日期：2026-11-12。决定人：成员 A（fangxunwu，25208508）。成员 B（kaiwenyao，25202665）的确认栏见文末。
本文件回应 [交接清单](08_handoff.md) H-01～H-04，是正式 run 的执行依据。

| 编号 | 决定 | 依据与约束 |
| --- | --- | --- |
| H-01 UCI 使用授权 | **已关闭。** 以官方规则原文作为使用依据，`uci_competition_use_approved` 改为 `true` | [docs/official/2026-11-12_uci_permission.md](../official/2026-11-12_uci_permission.md)：官方 PDF p.9 与 FAQ 写明 "public or synthetic data only"，UCI 为 CC BY 4.0 公开数据。这不是主办方的单独邮件；如主办方另有指示，以主办方为准 |
| H-02 seed 47 未被消费 | **已确认（11-12）。** 正式 run 在 A 的本机执行；A 与 B 为同一操作者，由 fangxunwu 确认 seed 47 从未在任何机器上执行过正式 `accept` | 本机没有 `runs/holdout_consumption.jsonl`。历史排除依靠已提交的 `config/holdout_ledger.json`（seed 42–46）重建，仍然有效。B 须在其机器上执行 `grep -c seed-47 runs/holdout_consumption.jsonl`（期望 `0`），并把输出贴到下方确认栏。**确认之前不得执行 `accept`** |
| H-03 审核人、执行人与标签策略 | Gate A/B/C 由 **A 本人在 Streamlit UI 中人工审核**，`reviewer` 填 `fangxunwu`，不用 `agent-delegated`。执行人：A，在本机执行 | 只创建 `v3` 标签，而且只能在 `release-check` 返回 `APPROVED` 后创建；**推送前须 A 再次确认**。不在本机创建或推送 `v1`、`v2` 标签；B 本机的 `v2` 标签（`9884e3a`，未经放行）不得推送，也不得移动 |
| H-04 v2 与 v3 的证据策略 | **v2 永久 BLOCKED，只发布 v3** | 只跑**一次** seed 47 正式 run（1,199 行 Holdout）。`release-check` 仍要求同一 run 含 V1-01～07、V2-01～07 共 14 项 PASS，这些记录只作为 v3 的发布证据，**不据此创建 `v2` 标签**。禁止为拿到多套记录而拆成多次正式 run，也禁止换 seed 或清理账本 |

## 正式 run 前置条件

1. 本记录与 H-01 配置改动已提交并推送，工作区干净，`FROZEN=$(git rev-parse HEAD)`。
2. B 完成 H-02 确认。
3. 本机网关、Docker 可用，UCI ZIP 哈希为 `56c885f8…`。

## 成员 B 确认

11-12 记录：成员 B（kaiwenyao）为组队登记，项目实际由 fangxunwu 一人操作。H-01～H-04 与 H-02 的确认均由 fangxunwu 作出，不再另设 B 签字；下表保留作说明。

## 原 B 确认栏（不再使用）

| 字段 | 内容 |
| --- | --- |
| 是否同意 H-01～H-04 | |
| H-02：`grep -c seed-47 runs/holdout_consumption.jsonl` 的输出 | |
| 签名与时间（UTC） | |
