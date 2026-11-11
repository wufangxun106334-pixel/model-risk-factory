# Model Risk Factory — solution deck (source)

<!--
Editable source for `materials/solution_deck.pptx` and `materials/solution_deck.pdf`.
Build: .venv/bin/python materials/build_deck.py
Structure: every slide starts with "## Slide N — Title"; "- " lines are bullets;
"IMAGE: <path>" embeds a picture; "SOURCE:" lines are rendered as a small footer.
Every figure carries its origin: SYN-SEED47 (synthetic drill), HIST-UCI (seed 46 formal
run, historical), V1-UCI, or PENDING. Client context figures are labelled CLIENT-CONTEXT.
-->

## Slide 1 — Model Risk Factory

The Agent does the reading, porting and number-crunching of a model review. Reviewers keep every decision, and every number traces to evidence.
Challenge 04 · EXL × UCD Data & AI Hackathon 2026 · competition prototype

- Document: three legacy R models inventoried from code and stale notes. Conflicts and Unknowns are kept, each with path, line and SHA-256.
- Migrate: MDL_CREDIT_V1 ported to Python by a real gateway Agent. Max |Δp| 2.220e-16 against R on 12,000 records (HIST-UCI).
- Validate: performance, calibration, drift and fairness computed by Python. 191 report values each resolve to a JSON path (HIST-UCI).
- Control: three hash-bound review gates. Any change to code, config or candidate invalidates earlier approvals.

SOURCE: results come only from runs recorded in the repository. HIST-UCI = `v2-20261109T210903Z-3dcfab73` (UCI, seed 46, historical); SYN-SEED47 = `dev_runs/v2-20261110T182506Z-9acb1487` (synthetic). Release state: slide 9.

## Slide 2 — The client problem

CLIENT-CONTEXT (from the challenge brief, not measured here): a bank runs ~250 models; documentation drifts away from code; a model review takes 8–12 weeks; PRA SS1/23 sets the expectation that models are documented, validated, monitored and independently reviewed.

What that costs in practice, and what this prototype addresses:

- The document and the code disagree, and nobody can say which one is right without reading both.
- Re-implementation is checked by eye, sampled, or "the AUC looks fine".
- Validation evidence is rebuilt per review instead of being produced by the pipeline.
- Drift is found by a spreadsheet refresh, not by a metric with a recorded threshold.

SOURCE: `docs/01_比赛背景与官方要求.md` and the official PDF. The 250-model / 8–12-week figures are client backdrop only and are never presented as this project's results.

## Slide 3 — Method and architecture

The Agent proposes artifacts, deterministic checks validate them, and reviewers record decisions at three gates.

IMAGE: materials/architecture.png

- Document → Agent returns a schema-validated inventory; Gate A approves its hash. Redevelop → Agent writes the Python candidate; Gate B approves the 64-hex source hash before anything runs.
- Validate → candidate runs in a no-network, read-only container; a trusted validator compares it with the R baseline. Monitor → drift, calibration and fairness; Gate C approves the rendered report.
- Hard boundary: Holdout inputs and answers never enter the Agent context; only aggregate, desensitised metrics do.

SOURCE: architecture detail in `materials/architecture.md`. Gate definitions: `docs/02_项目SOP.md` §7.4.

## Slide 4 — Inventory and documented gaps

Three models documented from their real code and their real (deliberately stale) notes.

- MDL_CREDIT_V1: code threshold 0.35 vs documented 0.50 — kept as a conflict, never auto-normalised; 14 verified sources.
- MDL_CREDIT_V2 and MDL_CREDIT_TREE: undocumented input limits, transformations and hyperparameters recorded as conflicts; owner and training date stay `Unknown`.
- Each confirmed conflict carries file path, line, excerpt and SHA-256. Equal code and document thresholds cannot be recorded as a conflict.
- HIST-UCI: 3 inventories, 3 Gate A approvals, 4 Unknown fields each.

IMAGE: docs/v3/ui_screens/02_model_detail.png

SOURCE: HIST-UCI `model_inventory.json`, `inventories/*.json`, `inventory_validation.json`; rule set `src/inventory.py` + `config/inventory_expectations.json`; regression `tests/test_v3_gap_inventory_conflicts.py`.

## Slide 5 — R to Python parity

The candidate reuses the exported R coefficients, medians, feature order and the 0.35 threshold. Nothing is retrained.

- HIST-UCI: 6,000 development records and 6,000 Holdout records compared one by one — max |Δp| 2.220e-16, mean |Δp| 2.707e-17, 0 classification mismatches, 0 behaviour mismatches (tolerance 1e-8 / 1e-10).
- Behaviour is tested too: missing values, imputation flags, invalid rows and rejection codes match record by record, plus row-order, column-order and structural-refusal fixtures.
- A deliberately altered coefficient (+0.001 on `delay_1`) is caught by the fixed validator; the original baseline and test hashes stay unchanged.
- The Agent never sees the Holdout: it only gets development parity summaries and aggregate diagnostics.

SOURCE: HIST-UCI `parity/*/parity_summary.json`, `mutation/mutation_summary.json`, `dev/attempt_000/fixtures/`; thresholds `config/model_config.json`.

## Slide 6 — Validation and monitoring

Python computes the metrics and renders the conclusions. The Agent selects a review focus and its structured facts are checked against the metrics.

- Performance (HIST-UCI Holdout, 6,000 rows): ROC-AUC 0.7529, Brier 0.1422, decile calibration table, confusion matrix at p ≥ 0.35 (TP 621 / FP 501 / FN 701 / TN 4177).
- Stability: weighted drift batch vs dev reference — prediction PSI 0.0170, worst feature PSI 0.0799 (util_1); attention 0.10 / review 0.25 are project demo rules, not a regulatory standard.
- Fairness audit: age_band 21–25 TPR 0.5477 vs reference 0.4392 (+0.1086), sex=1 TPR difference −0.0387; small groups are marked `LOW_SAMPLE` and rates are not assessable.
- Limits sit next to the numbers: same-period hold-out (not a back-test), drift is a sensitivity analysis, no cross-time back-test. Gate C re-renders and compares every cell (SYN-SEED47: 196 values, 0 unresolved).

IMAGE: docs/v3/ui_screens/04_validation_report.png

SOURCE: HIST-UCI `validation_metrics.json`, `report/validation_report.md`; SYN-SEED47 `report/values_index.csv`, `report/review_manifest.json`.

## Slide 7 — What the reviewer no longer does by hand

Each line is a task a validator normally does by hand, with the measured automated time (SYN-SEED47, gateway `deepseek-v4.1-flash:1017`).

- Read code and notes, write the inventory and list the conflicts: 12.7 s / 31.6 s / 40.3 s per model. A deterministic rule rejected one incomplete answer automatically.
- Re-implement the model in Python: 66.1 s for the candidate. Prove it matches R record by record: run by the pipeline, with no sampling or checking by eye.
- Recompute every report number and check every table cell: done at Gate C. Draft the review summary: 9.8 s.
- End to end: 29 commands and 3.49 min of automated work for 3 inventories, a migration, validation, report and export. Reviewer time is spent on the decisions at the gates.
- Not claimed yet: a speed-up percentage. The paired manual-vs-Agent study (protocol in `materials/impact_measurements_README.md`) has 0 completed pairs.

SOURCE: SYN-SEED47 `command_log.jsonl` timings, `agent_audit_log.jsonl`, `provider/request_log.jsonl`; `materials/impact_measurements.csv` + its README.

## Slide 8 — Responsible AI

- Data: UCI Default of Credit Card Clients (CC BY 4.0), a 2005 Taiwan sample; no direct identifiers but demographic attributes exist. Competition use permission is still recorded as unconfirmed (`uci_competition_use_approved=false`).
- Privacy: demographics are audit-only and never model inputs; no raw rows, labels or Holdout content are sent to the LLM — only R code, the simulated note, schemas and aggregate diagnostics; API keys live in local environment variables only.
- Bias: TPR/FPR by age_band and sex are audit signals, not a fairness verdict; small groups are marked not assessable; the model is not claimed to be fair.
- Limitations: not production-ready, not independently validated, not a regulatory certification; no cross-time back-test; report conclusions come from computed metrics and are checked again at Gate C.
- Safeguards: generated code runs only in a no-network, read-only, non-root container with memory/CPU/PID/time limits; gates A/B/C bind to hashes and invalidate on any source, config or candidate change.

SOURCE: HIST-UCI `boundary/boundary_report.json`, `review_log.json`, `report/validation_report.md`; `materials/responsible_ai_note.md`.

## Slide 9 — Prototype walkthrough and release state

Four Streamlit pages over the same CLI the pipeline uses — every button runs `python -m src.cli`, so the UI cannot bypass a gate.

IMAGE: docs/v3/ui_screens/01_inventory.png
IMAGE: docs/v3/ui_screens/03_migration.png

- Inventory, Model detail (Gate A), Migration (Gate B + Docker), Validation report (Gate C + downloads).
- The 1:51 demo replays a synthetic run. The current drill pauses at every gate for a reviewer decision.
- Release state, stated plainly: v1 accepted locally (tag `v1` → 70858cd, 7/7 PASS, not pushed). v2 BLOCKED, because its evidence matches no commit (17 gaps). The single v3 formal run (seed 47) is scripted and preflight-checked, and waits on the organiser's UCI permission, ledger confirmation and named reviewers.

SOURCE: `docs/v3/00_baseline_status.md`, `docs/v3/03_release_readiness.md`, `docs/v3/02_new_environment.md`; screenshots in `docs/v3/ui_screens/`.

## Slide 10 — Roadmap and disclosure

Why this is different: approvals bind exact hashes and expire on any change; every report number resolves to a JSON path; parity is proven record by record and mutation-tested.

- Short term: one authorised formal seed-47 run on the frozen commit, human Gate A/B/C sign-off, recorded demo of the same chain.
- Then: SAS/other formats behind the same inventory contract; batch queue across ~250 models; MLflow/Azure ML as an evidence sink, not a replacement for the gates; genuine out-of-time data for back-testing.
- AI tools used: Claude Code / Kimi Code CLI (implementation, tests, docs) and this delivery Agent; in-product gateway `sa.kaiwen.dev` with `deepseek-v4.1-flash:1017` for inventory extraction, candidate generation and report explanation (v1 candidate used `kimi-k2.7-code`).
- Existing code and data: R `glm`/`rpart`/`jsonlite`, Python NumPy/pandas/Pydantic/pytest/Docker/Streamlit, the UCI dataset, and the three team-built R models plus their simulated notes.
- What is human-written: the trusted Python reference predictor and the fixed tests. What is Agent-written: the migration candidate, the inventories and the report narrative.

SOURCE: `README.md` (AI tool and existing-code disclosure), HIST-UCI `provider/request_log.jsonl`, `agent_audit_log.jsonl`, V1-UCI `candidate.json`.
