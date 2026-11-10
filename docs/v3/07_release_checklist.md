# V3-06 release checklist — freeze, verification and tag criteria

Owner: V3 交付执行 Agent（`agent-delegated`）。本文件是「能不能打 `v3` 标签」的唯一判定清单。
当前结论：**不满足，`v3` 标签未创建**（原因见 §5）。四项前置的负责人与下一条动作见 `docs/v3/08_handoff.md`。

---

## 1. 冻结前的必交项（全部完成才可以定 SHA）

| # | 检查 | 期望 | 状态 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | 代码改动只限授权范围 | 判定门禁、真实审核暂停、导出和演示材料 | ✅ | `git diff d0210b6..<frozen> --stat` |
| 2 | 全量测试 | 0 failed / 0 skipped / exit 0 | ✅ 见审核修复记录 | `docs/v3/10_audit_followup.md` |
| 3 | 两处缺口的定向回归 | 修复前红、修复后绿 | ✅ | `docs/v3/10_audit_followup.md` |
| 4 | 新环境复现 | 干净检出 + 全新 venv 跑通全量测试 | ✅ | `docs/v3/02_new_environment.md` |
| 5 | 端到端演练 | 独立合成目录；审核人实际决定；export 为最后一步 | 旧演练仅供回放；修复后 Gate A 前已复测 | `docs/v3/10_audit_followup.md` |
| 6 | 四页界面 | 有数据/空状态、Gate 状态、图表与来源表、下载、状态徽标、UI 不绕过门禁 | ✅ | `docs/v3/ui_screens/`、`docs/v3/02_new_environment.md` §5 |
| 7 | 五件套 | deck ≤10 页、视频 ≤3 分钟、README、1 页架构图、1 页 RAI note | 本地就绪，评委访问待验证 | `materials/submission_checklist.md` |
| 8 | 验收材料 | test_summary、新环境记录、final_review、release_checklist、impact CSV | ✅ | `docs/v3/`、`materials/` |
| 9 | 历史标签未被移动 | `v1` → `70858cd`、`v2` → `9884e3a` 保持不变 | ✅ | `docs/v3/00_baseline_status.md` §1 |
| 10 | 正式 Holdout 未被消费 | 账本无 seed 47 | ✅（本机） | `runs/holdout_consumption.jsonl` |

## 2. 冻结步骤（在授权后执行，一步不多）

```bash
# 0. 确认工作区干净，HEAD 即冻结提交
git status --porcelain               # 必须为空
FROZEN=$(git rev-parse HEAD)

# 1. 在同一 SHA 上、干净树里初始化正式 run（只做一次）
export LLM_BASE_URL=... LLM_CHAT_COMPLETIONS_URL=... LLM_PROTOCOL=openai_chat_completions \
       LLM_MODEL=deepseek-v4.1-flash:1017 LLM_TIMEOUT_SECONDS=300 LLM_MAX_OUTPUT_TOKENS=32768
read -rs LLM_API_KEY; export LLM_API_KEY
RUN_ID=$(python -m src.cli init-run --mode uci | python -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
python -m src.cli check-provider --run-id "$RUN_ID"
python -m src.cli download-uci  --run-id "$RUN_ID" --expected-sha256 56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602 --approve-uci-use
python -m src.cli prepare --run-id "$RUN_ID" --uci data/raw/default_of_credit_card_clients.zip \
       --expected-sha256 56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602 --approve-uci-use
# 2. 后续步骤完全按 README「v2 正式 run 的实际命令」顺序，唯一一次 accept，最后 export；随后只读取 delivery 的验收 JSON
# 3. 发布校验（输出必须写到 run/与 delivery 之外）
python -m src.cli release-check --run-id "$RUN_ID" --tag "$FROZEN" \
       --zip data/raw/default_of_credit_card_clients.zip --output ~/release_check_v3.json
```

放行判定（全部满足才可打标签）：

- `release-check` 返回 `APPROVED`（不是 BLOCKED），且
- `acceptance.json` 恰好含 V1-01～07 与 V2-01～07 各一次、全部 `PASS`、`commit_sha == $FROZEN`，且
- 隔离标签树内全量测试 `0 failed / 0 skipped`，`verify_context` 通过，导出 ZIP 逐成员哈希一致。

## 3. 打标签（仅在 §2 全部通过后）

```bash
git tag -a v3 -m "v3 final: <run_id> on $FROZEN" "$FROZEN"
git tag -n | grep '^v3'
git rev-parse v3^{commit}     # 必须等于 $FROZEN
git ls-remote --tags origin   # 推送前为空；推送需授权
```

- **禁止**移动、覆盖、强推既有 `v1`/`v2` 标签。
- 推送 `v3`（以及历史遗留的 `v1`/`v2`）需要团队明确授权；本次**未推送任何标签**。

## 4. 本次冻结的实际结果

| 项 | 结果 |
| --- | --- |
| 冻结提交 | 见 `docs/v3/09_verification_of_freeze.md` §1（该文件只记录对冻结提交的只读复核结果） |
| 冻结时工作区 | 干净（`git status --short` 为空），提交后无改动 |
| 冻结提交上跑的全量测试 | 见 §1 第 2 行与 `09_verification_of_freeze.md` |
| 冻结提交上的端到端演练 | 见 `09_verification_of_freeze.md`（绑定该 SHA 的 synthetic run，`verify-context --at <frozen>` 通过） |
| `release-check`（现有正式证据） | **BLOCKED**（17 条缺口，`docs/v3/logs/release_check_v2_blocked.json`） |
| `v3` 标签 | **未创建** |

## 5. 为什么没有打标签（逐条阻断）

| # | 阻断 | 判定依据 | 解除条件 |
| --- | --- | --- | --- |
| B1 | 没有 seed 47 正式 run | 四项前置 P1/P2/P4 缺失（`docs/v3/03_release_readiness.md` §5） | 交接 H-01/H-02/H-03 齐备后按 §2 执行一次 |
| B2 | 现有正式证据不可放行 | `release-check` BLOCKED、`verify-context` 两个 ref 均 FAIL | 用 B1 的新 run 提供与 `$FROZEN` 绑定的证据 |
| B3 | V3-05 人工互审未签 | `docs/v3/06_final_review.md` §3 签署栏为空 | 成员 A/B 签字并记录时间与决定 |
| B4 | 视频分享链接待验证 | 本地 MP4 时长 1:51 | 评委访问恢复后核对链接和播放 |
| B5 | 评委访问未验证 | 仓库私有、无上传 | 交接 H-06 |

**明确禁止的"解法"**：移动 `v2` 标签去凑提交、回退测试去凑 `tests_matches`、截断或改写 `command_log.jsonl`、
为了分别拿到 v2/v3 记录而拆成两次正式 run、换目录/换 seed/清账本、把合成数据说成正式结果。

## 6. 若最终仍无法获得正式放行

按 SOP 交付：候选提交 + 完整材料 + 本清单的 BLOCKED 记录 + 交接清单，并明确
「V3 候选已交付，最终验收仍为 BLOCKED」。逐项状态见 [最终审核表](06_final_review.md)。
