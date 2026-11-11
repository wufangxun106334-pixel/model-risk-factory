# Demo video transcript and source

[Local MP4](demo_video.mp4) · 1:51 · English synthetic narration · 1440 × 1000 · H.264 / AAC.

The screen recording shows a real Streamlit instance playing back synthetic run `v2-20261110T191501Z-fed1c652` from `e298d23`. The video labels the recorded approvals as historical scripted records and explains the current review pauses. The read-only playback did not call the model gateway, write to the original run or consume the formal Holdout.

| Time | Scene | Evidence shown |
| --- | --- | --- |
| 0:00 | Model inventory | Three documented models and one migration target |
| 0:19 | Source review | Threshold discrepancy, Unknown fields, cited source lines |
| 0:41 | Migration parity | 1,199 synthetic Holdout rows, zero classification mismatches |
| 1:07 | Validation | Performance and calibration, with the other audit dimensions explained in narration |
| 1:29 | Evidence | Exports, release requirement and synthetic run status |

The recorded deliberate-error result is from the same run's `mutation/mutation_summary.json`. It reports a detected coefficient change, with maximum absolute error above tolerance. The video remains local until a judge-accessible link is provided.

## Earlier storyboard

> **Superseded pre-recording plan, kept for reference.** The recorded video above is 1:51 and replays synthetic run `v2-20261110T191501Z-fed1c652` only (1,199 synthetic Holdout rows). It does not show the HIST-UCI clips, the 6,000-row parity or the 61-file ZIP planned below. Approvals in the recorded runs were scripted `agent-delegated` records, not a person at each gate.

Deliverable for V3-03. Target length **2:55**, hard limit 3:00.
Recorded material must be **real screen captures** of this repository. Any step that was
pre-computed (the Agent calls take ~1–2 minutes) is shown from its recorded run and labelled
`REPLAY` on screen — a live call is never faked.

Recording status at planning time: not recorded yet. The video has since been recorded; see the
transcript at the top of this file. This script is the final, read-aloud version; the timings below are the
edit plan, and the narration is written to be spoken at a normal pace.

## What to record, once

| Need | Command / file |
| --- | --- |
| UI pages (all four) | `.venv/bin/streamlit run app.py` → `http://localhost:8501`, `dev_runs` root, run `v2-20261110T182506Z-9acb1487` |
| Gate A on screen | page 2 · Model detail — shows `Gate A: ✅ APPROVED`, code 0.35 vs documented 0.50, `Unknown` owner/training date, the conflicts table |
| Candidate + parity | page 3 · Migration (source, 64-hex hash, Gate B form) and its "Results: R vs Python parity" section |
| Four metrics | page 4 · Validation report (ROC-AUC/Brier cards, calibration, confusion matrix, PSI, fairness) |
| Deliberate error | terminal: `python -m src.cli mutation-check --run-id <run>` on the drill run, showing `mutation_summary.json` `status=PASS` and the mutant max |Δp| |
| Gate C + export | page 4 top (`Gate C: ✅ APPROVED`) + terminal `python -m src.cli export --run-id <run>` output |
| Run badges | any page, top of the main area: `SYNTHETIC · REPLAY · ACCEPTANCE NOT PASSED · COMMIT …` |

## Storyboard and narration

| Time | On screen | Narration (read this) | Source label to show |
| --- | --- | --- | --- |
| 0:00–0:12 | Title card: "Model Risk Factory — Challenge 04". Then the Inventory page with three models listed. | "A bank runs roughly two hundred and fifty models. Documentation drifts away from code, and a review can take eight to twelve weeks. This is Model Risk Factory: it documents a legacy estate, migrates one model, and validates it — with a recorded reviewer decision at every gate." | `CLIENT CONTEXT` (brief figures) |
| 0:12–0:25 | Page 1 · Inventory, then click into Model detail for `MDL_CREDIT_V1`. | "Three legacy R models, documented from their actual code and their actual old notes. Every fact carries a file path, a line range and a SHA-256. What the notes never said stays `Unknown`." | `SYNTHETIC DRILL · seed 47` badge visible |
| 0:25–1:00 | Page 2 · Model detail. Highlight `Code threshold 0.35` vs `Documented threshold 0.5`, the Unknowns, then the conflicts table. Then the Gate A line. | "Here is the disagreement that matters: the code scores at zero point three five, the note says zero point five zero. The system keeps that conflict — it never quietly normalises it. The Agent also cannot invent an agreement: an entry claiming a conflict between two equal thresholds is rejected by a deterministic rule, not by a reviewer's opinion. Gate A approves the inventory artifact by hash, and that approval dies the moment the inventory or the source code changes." | `Gate A: ✅ APPROVED` + inventory hash |
| 1:00–1:20 | Page 3 · Migration: candidate source, then the 64-hex hash and the Gate B form. | "Gate B approves the exact candidate source hash before anything runs. The candidate reuses the R coefficients, medians, feature order and the zero point three five threshold. Nothing is retrained." | `REPLAY — recorded run` overlay |
| 1:20–1:45 | Parity section: status, rows compared, max |Δp|, class and behaviour mismatches, then the scatter plot with its data table. | "Then the trusted validator compares it with the R baseline, record by record, in a container with no network, read-only mounts and a thirty-second limit. Six thousand development rows and six thousand holdout rows: maximum absolute probability difference two point two times ten to the minus sixteen, zero classification mismatches, zero behaviour mismatches — against a tolerance of one times ten to the minus eight." | `HIST-UCI · seed 46 · historical` |
| 1:45–2:20 | Page 4 · Validation report: metric cards, calibration table, confusion matrix, PSI chart, fairness chart, then the Key conclusions block. | "Performance, calibration, stability and fairness are computed by deterministic Python — the Agent only explains them. Holdout ROC-AUC zero point seven five two nine, Brier zero point one four two two, with a ten-decile calibration table. Drift: prediction PSI zero point zero one seven, worst feature zero point zero seven nine nine, both below the project's zero point one attention line. Fairness is an audit signal, not a verdict: TPR by age band and sex, small groups marked not assessable, and the report states plainly that a cross-time back-test is unavailable." | `HIST-UCI · seed 46 · historical` |
| 2:20–2:45 | Terminal: `mutation-check`, then open `mutation/mutation_summary.json`. Then show the report's refusal behaviour briefly (optional: the Key conclusions vs Agent text). | "Can it catch a wrong model? Take an isolated copy, shift one coefficient by zero point zero zero one, and run the same fixed test. Maximum difference: one point one times ten to the minus three — eight orders of magnitude above tolerance, caught immediately. The original baseline and the test hashes are unchanged afterwards." | `SYNTHETIC DRILL · seed 47` |
| 2:45–2:55 | Page 4 top: `Gate C: ✅ APPROVED`, download buttons. Then terminal `export` output and the ZIP hash. | "Gate C re-renders the whole report and compares every table cell; only then can the report be approved. Export produces the acceptance record and a whitelisted evidence ZIP — sixty-one files, no data rows, no labels, no baseline answers. That is the whole loop: document, migrate, validate, and prove it." | `REPLAY` + ZIP sha256 |

## Editing rules (do not break these)

1. Every clip that shows a number must also show the run label. If a clip is from the
   historical UCI run, overlay `HIST-UCI (seed 46, historical)`. If it is from the synthetic
   drill, overlay `SYNTHETIC (seed 47)`. Never let a viewer think synthetic numbers are model
   performance, or that history is today's release.
2. Steps that were pre-computed get a `REPLAY` overlay for their whole duration. Only a live
   API call (if the recording machine has the key and the gateway responds) may be shown
   without it — and then the on-screen request id must be visible.
3. Do not cut a failure out of a story: if a live step fails during recording, show the error
   and the recorded run instead. Re-recording a fake "success" is not allowed.
4. Keep the total under 3:00 including the title card; the narration above is 372 words, which
   runs about 2:30–2:45 at a normal pace.
5. Check the final file: length ≤3:00, audio audible, text legible at 1080p, no API key,
   token, or email address visible in any frame.

## Post-recording checklist

- [ ] Duration measured (`ffprobe -show_entries format=duration`) and ≤ 180 s.
- [ ] Every on-screen number matches the run it is labelled with (spot-check three).
- [ ] No secrets, no bearer tokens, no client identifiers, no raw data rows visible.
- [ ] Voice-over matches this script (small ad-libs allowed, no factual changes).
- [ ] Uploaded somewhere the judges can open without an account, or shipped as a local file
      with the link handed over by the owner named in `docs/v3/08_handoff.md`.
- [ ] Duration + link recorded in `materials/submission_checklist.md`.
