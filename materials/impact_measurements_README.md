# V3-04 business-value measurement: protocol and worksheet

`impact_measurements.csv` is the deliverable. It currently contains:

- **measured Agent rows** `T01`–`T06`, taken from real command and audit timestamps of run
  `v2-20261110T182506Z-9acb1487` (synthetic drill, seed 47);
- **pending manual rows** `T11`–`T15`, with empty timings and `status=pending`.

No speed-up percentage is claimed until the paired manual rows exist. The rows that are
already measured are **automation time only**: a delegated Agent approval is not human reading
time, so it must never be presented as "hours saved".

## 1. Why a paired measurement

The only honest way to claim that the Agent saves effort is to compare the same task, with the
same inputs and the same quality bar, done twice: once by a human, once by the Agent plus human
review. Anything else (for example comparing Agent runtime with a remembered "it usually takes
a week") is an anecdote.

## 2. Fixed task definition

Both arms of a pair must use exactly these materials and this acceptance bar:

| Field | Value |
| --- | --- |
| Task | Build the model inventory for one legacy model (`MDL_CREDIT_V1`, `MDL_CREDIT_V2`, `MDL_CREDIT_TREE`) |
| Materials | `legacy/<model>.R`, `legacy/notes/<model>.md`, `config/inventory_schema.json`, `config/inventory_expectations.json` |
| Forbidden inputs | Any previously produced inventory, `runs/*/model_inventory.json`, another person's notes |
| Quality bar | The inventory passes `src/inventory.py::build_inventory` with no relaxation: every source path/line/excerpt/SHA-256 valid, feature order correct, threshold pair preserved, required `Unknown`s listed, every conflict named and cited |
| Output | One JSON file per model, plus the fields the reviewer actually checked |
| Sample count | 0 model rows scored (inventory is a documentation task); record it as `0` and state it in the notes |

The migration pair (`T14`) and report-review pair (`T15`) follow the same idea with their own
bar: dev parity + fixtures PASS for the port, and a full Gate C check for the report review.

## 3. How to run the manual arm

1. Create a clean checkout of the frozen commit and do **not** open the Agent's artifacts.
2. Start a stopwatch when you first open the R file. Stop it when the JSON passes the validator
   locally:
   `.venv/bin/python scripts/validate_inventory.py my_inventory.json` (exit 0 = PASS; it applies
   exactly the Gate A rules of `src/inventory.py::build_inventory` and writes nothing into `runs/`).
   Write `conflicts` as `[{"field": "<finding>"}]`; the validator names any missing or invented one.
3. Record three numbers separately:
   - `automation_seconds` = 0 for a manual row (nothing was automated);
   - `manual_review_seconds` = time spent checking your own or the other arm's output;
   - `rework_seconds` = time spent after a validation rejection.
4. `total_seconds` = the wall-clock time from start to accepted output, **including** review and
   rework. Never report a subtotal as the total.
5. `misses_or_errors` = number of defects the validator caught (0 is a valid value). If you
   found a defect the validator did not catch, add a row note — that is a gate defect, not a
   speed result.
6. Fill `operator`, `familiarity` (`first-time` / `seen-the-estate` / `author-of-the-model`),
   `started_at_utc`, `finished_at_utc`, and `evidence_ref` (a file you can show: the JSON, the
   validator output, or your notes file).

## 4. Pairing and order

- Do the manual arm and the Agent arm **in the same session** or within the same day, and record
  which one came first in the `notes` column of both rows.
- Alternate the order across models (for example manual first for V1, Agent first for V2) so the
  learning effect does not systematically favour one arm.
- One operator per pair. If two people measure, keep their pairs separate and do not average
  across people without showing both.
- Minimum useful sample: **3 paired models**. With fewer, report the raw pairs and write
  "sample too small to generalise" in `final_review.md`. Do not compute an average speed-up from
  one pair, and never compute one from zero pairs.

## 5. How the delta is computed (only once pairs exist)

For each pair `i`:

```
saved_seconds_i = total_manual_i - total_agent_plus_review_i
saved_pct_i     = saved_seconds_i / total_manual_i
```

Report the per-pair values, the median (not the mean — three pairs do not support a mean), the
number of pairs, and the quality comparison (validator defects caught in each arm). If any pair
shows the Agent arm slower, report that pair as-is; it is a finding, not an error.

## 6. What is already measured (and what it means)

| Row | What it is | What it is not |
| --- | --- | --- |
| `T01`–`T03` | Wall time of `extract-inventory` per model, including one in-command rejection on V2 | Human reading/gap-analysis time |
| `T04` | Wall time of `generate-candidate` (66.1 s) | Time to write the reference implementation by hand |
| `T05` | Wall time of `agent-summary` (9.8 s) | Time for a human to interpret the metrics |
| `T06` | Whole 29-command pipeline: 200.5 s of command time, 3.49 min wall clock | End-to-end labour cost, because gate reviews are delegated here |

Source: `dev_runs/v2-20261110T182506Z-9acb1487/command_log.jsonl` (`started_at`/`finished_at`
per command) and `agent_audit_log.jsonl` (per-stage timestamps). Recompute with:

```bash
.venv/bin/python - <<'PY'
import json
from datetime import datetime
run = "dev_runs/v2-20261110T182506Z-9acb1487"
rows = [json.loads(line) for line in open(f"{run}/command_log.jsonl")]
parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
for row in rows:
    seconds = (parse(row["finished_at"]) - parse(row["started_at"])).total_seconds()
    print(f"{seconds:7.1f}s  {' '.join(row['argv'])}")
print("total", sum((parse(r["finished_at"]) - parse(r["started_at"])).total_seconds() for r in rows))
PY
```

## 7. Worksheet header (copy this for the manual rows)

```csv
task_id,model_id,mode,operator,familiarity,sample_count,started_at_utc,finished_at_utc,automation_seconds,manual_review_seconds,rework_seconds,total_seconds,misses_or_errors,evidence_ref,run_id,data_kind,status,notes
T11-manual-inventory,MDL_CREDIT_V1,manual,<name>,first-time,0,<ISO8601>,<ISO8601>,0,<seconds>,<seconds>,<seconds>,<count>,<path>,,,measured,"<order and anything surprising>"
```

Replace the corresponding `pending` row in `impact_measurements.csv`; keep `task_id` stable so the
pair stays traceable.
