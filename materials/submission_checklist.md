# Submission checklist (five deliverables + acceptance material)

Challenge 04 · EXL × UCD Data & AI Hackathon 2026
Owner of the submission: the team (hand-off list in `docs/v3/08_handoff.md`).

**Candidate**: the five deliverables reached the private repository's `main` branch in `7ffc672`
on 10 November 2026. The team will record the final release SHA before the formal run. See
[the release checklist](../docs/v3/07_release_checklist.md).

Status legend: ✅ done and verifiable · ⏳ ready but needs a human/external action · ❌ not done. Judge access and paired measurements are deferred. The submission is still pending.

## 1. The five deliverables

| # | Deliverable | Official limit | Files in this repo | Length | Judge-accessible link | Source commit | Verified by | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Solution deck | ≤10 pages | `materials/solution_deck.md` (editable source), `materials/solution_deck.pptx` (editable deck), `materials/solution_deck.pdf` (print copy), builder `materials/build_deck.py` | **10 slides / 10 PDF pages** (checked with `pypdf`, `len(reader.pages)==10`) | repo only — needs upload or a shared link (H-06) | commit of this file | agent-delegated (content + build) | ✅ built, ⏳ link |
| 2 | Demo video | ≤3 minutes | `materials/demo_video.mp4`, [transcript](demo_video_script.md) | **1:51**, H.264 + AAC | On `main`, judge access pending | `7ffc672` | duration checked with ffprobe; five scenes visually inspected | ✅ built, ⏳ link (H-06) |
| 3 | Code repository + README | link + README + setup | whole repo; `README.md` (judge section, status, setup, declarations) + `docs/engineering_notes.md` (v1/v2 engineering history) | — | https://github.com/wufangxun106334-pixel/model-risk-factory (**Private**) | commit of this file | agent-delegated | ⏳ access must be verified from a judge's account (H-06) |
| 4 | Architecture diagram | 1 page | `materials/architecture.svg` (editable), `materials/architecture.png`, explanation `materials/architecture.md` | **1 page / 1 image** | repo only (H-06) | commit of this file | agent-delegated; layout checked geometrically (0 text overflow, 0 overlapping labels) | ✅ built, ⏳ link |
| 5 | Responsible AI note | 1 page | `materials/responsible_ai_note.pdf` and its Markdown source | **1 PDF page** (data, privacy, bias, limitations, safeguards) | repo only (H-06) | commit of this file | agent-delegated | ✅ written, ⏳ link |

## 2. Required declarations (README + deck)

| Item | Where it is stated | Status |
| --- | --- | --- |
| AI tools used in development | `README.md` §AI tools and existing code; deck slide 10 | ✅ |
| In-product LLM model ID | `deepseek-v4.1-flash:1017` (v1 candidate: `kimi-k2.7-code`) — README, deck slide 3/10, `materials/architecture.md` | ✅ |
| Existing code and data | R `glm`/`rpart`/`jsonlite`, Python NumPy/pandas/Pydantic/pytest/Docker/Streamlit, UCI dataset, team-built R models and notes | ✅ |
| Human reference implementation vs Agent candidate | README and deck slide 5 distinguish them explicitly | ✅ |
| Data licence and pending permission | README §Data licence; RAI note §1; `config/data_config.json` `uci_competition_use_approved=false` | ✅ stated as pending |
| Frozen scope and known limitations | README §Release status and §Declarations; RAI note §4 | ✅ |

## 3. Business-value evidence (V3-04)

| Item | File | Status |
| --- | --- | --- |
| Measurement table | `materials/impact_measurements.csv` — 6 measured Agent rows (`T01`–`T06`), 5 pending manual rows (`T11`–`T15`) | ✅ measured rows / ⏳ manual pairs (H-08) |
| Protocol and worksheet | `materials/impact_measurements_README.md` | ✅ |
| Speed-up percentage | deliberately **not** claimed (0 pairs) | ⏳ paired study deferred |

## 4. Acceptance and review material

| Item | File | Status |
| --- | --- | --- |
| V3-01 test summary | `docs/v3/test_summary.md` | ✅ |
| V3-02 new-environment record | `docs/v3/02_new_environment.md` + `docs/v3/logs/*` | ✅ |
| V3-03 release readiness | `docs/v3/03_release_readiness.md` | ✅ |
| V3-05 final review + A/B review pack | `docs/v3/06_final_review.md` | ⏳ two human signatures (H-05) |
| V3-06 freeze + release checklist | `docs/v3/07_release_checklist.md` | ⏳ tag depends on authorisation (H-03/H-04) |
| Baseline status | `docs/v3/00_baseline_status.md` | ✅ |
| Gap fixes (2 gaps, 34 regression tests) | `docs/v3/01_gap_fixes.md` | ✅ |
| Hand-off list | `docs/v3/08_handoff.md` | ✅ |

## 5. Access checks (must be done from the judge's side)

Fallback while the repository is private: `.venv/bin/python scripts/build_submission.py` builds
`dist/model-risk-factory-submission-<sha>.zip` (all five deliverables, README, evidence tables and a
MANIFEST with SHA-256 per file). It refuses to build from uncommitted files, or if a packaged text
file contains a local absolute path or something shaped like a key. Upload or attach that zip if
judges cannot be given repository access (H-06).

- [ ] Repository is visible to the judges, or they were given an explicit invite. Private repo today.
- [ ] All links in this checklist open **without** a team account.
- [ ] Video link (or attached file) plays; duration shown as ≤3:00.
- [ ] Deck opens from the shared location (PPTX or PDF); fonts do not shift.
- [ ] No secrets in any shared material (API key, tokens, email addresses, local absolute paths).

## 6. Submission logistics (to be confirmed with the organisers, not assumed)

| Item | Value | Status |
| --- | --- | --- |
| Recipient | draft: `Monika.Rawal@exlservice.com` (from the team's SOP notes) | ⏳ confirm against the organiser's actual notice |
| Subject | `EXL Hackathon | <team name> | Challenge 04` | ⏳ team name to fill |
| Sender | UCD email of the submitting member | ⏳ |
| Deadline | draft: 2026-11-13 23:59 Irish time | ⏳ confirm |
| Deadline time zone / late policy | — | ⏳ confirm |
| Format of the submission (email body vs portal upload) | — | ⏳ confirm |

The competition submission is pending. Confirm judge access and the submission details above before sending.

## 7. Machine-checkable summary

| Check | Result |
| --- | --- |
| Deck slide count ≤10 | 10 ✅ |
| PDF page count | 10 ✅ |
| Video duration ≤180 s | 1:51 ✅ locally, judge link pending |
| Every number in the deck carries a source label | yes (per-slide SOURCE footer) ✅ |
| Synthetic vs historical vs formal distinguished | yes: `SYN-SEED47`, `HIST-UCI`, `CLIENT-CONTEXT`, `PENDING` ✅ |
| Compliance overclaims absent | report conclusions are rendered from structured facts; submission materials reviewed separately ✅ |
| Local absolute paths in materials | none (paths are repo-relative) ✅ |
