"""V2 acceptance checks (SOP §4.2 V2-01 … V2-07).

Same shape as the v1 checks: every record names the artifact a reviewer can open
and the concrete reason for the verdict. Nothing here is satisfied by a file
merely existing; each check re-reads hashes, run ids and gate decisions.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.acceptance import (
    COMMAND_CHAIN,
    _argv_option,
    _chain_binding_problems,
    _expected_attempt,
    _export_evidence,
    _frozen_candidate_sha256,
    _valid_execution,
)
from src.common import current_git_commit, read_json, read_jsonl, sha256_file, utc_now
from src.contracts import AcceptanceRecord
from src.inventory import expected_model_ids, inventory_path, load_inventory, model_expectation
from src.report import check_wording, report_status, verify_provenance
from src.review import current_decision
from src.workflow import verified_split_hash

EXPECTED_V2 = {
    "V2-01": "Three model inventories pass schema, source and Gate A review, with Unknowns and conflicts preserved.",
    "V2-02": "The container boundary is proven by execution: no writes, no host mounts, no key, and all four limits fire.",
    "V2-03": "Parity, performance, calibration, stability and fairness are computed by code with explicit edge states.",
    "V2-04": "Gate A precedes candidate generation, Gate B precedes execution, and Gate C precedes report approval.",
    "V2-05": "One CLI run carries onboarding, migration, freeze, Holdout, metrics, report and export with a single run_id.",
    "V2-06": "API error, parse failure, timeout, request limit and repair exhaustion keep real failure evidence.",
    "V2-07": "Every reported number resolves to a metrics JSON path and limitations are stated without compliance claims.",
}

V2_CHAIN = (
    ("docker-boundary", None),
    ("extract-inventory", "MDL_CREDIT_V2"),
    ("extract-inventory", "MDL_CREDIT_TREE"),
    ("approve", "Gate_A"),
    ("validation-metrics", None),
    ("agent-summary", None),
    ("report", None),
    ("approve", "Gate_C"),
    ("approve-report", None),
)

BOUNDARY_CHECKS = (
    "read_only_root_and_inputs",
    "no_host_or_baseline_mount",
    "api_key_not_visible",
    "memory_limit_triggered",
    "cpu_limit_triggered",
    "pid_limit_triggered",
    "timeout_triggered",
)

DRILL_NAMES = ("api_error", "parse_failure", "timeout", "request_limit", "repair_exhausted")


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _v2_01(repository: Path, run_dir: Path, run_id: str) -> tuple[str, str]:
    problems: list[str] = []
    for model_id in expected_model_ids(repository):
        path = inventory_path(run_dir, model_id)
        if not path.is_file():
            problems.append(f"{model_id}: inventory missing")
            continue
        try:
            inventory = load_inventory(path, run_id)
        except Exception as error:  # noqa: BLE001 - any validation failure is a FAIL record
            problems.append(f"{model_id}: {str(error)[:120]}")
            continue
        expectation = model_expectation(repository, model_id)
        for source in inventory["sources"]:
            target = repository / source["path"]
            if not target.is_file() or sha256_file(target) != source["sha256"]:
                problems.append(f"{model_id}: source hash mismatch {source['path']}")
                continue
            lines = target.read_text(encoding="utf-8").splitlines()
            if source["line_end"] > len(lines) or source["excerpt"] not in "\n".join(lines[source["line_start"] - 1 : source["line_end"]]):
                problems.append(f"{model_id}: source excerpt or range invalid {source['path']}")
        if {source["path"] for source in inventory["sources"]} < set(expectation["sources"]):
            problems.append(f"{model_id}: not every configured source was cited")
        if current_decision(run_dir, run_id, "Gate_A", path) != "APPROVED":
            problems.append(f"{model_id}: Gate_A is not APPROVED for the current hash")
        for field in expectation["unknown_fields"]:
            if inventory.get(field) != "Unknown" or field not in inventory["unknowns"]:
                problems.append(f"{model_id}: {field} was invented instead of kept Unknown")
        if len(inventory["conflicts"]) < int(expectation["min_conflicts"]):
            problems.append(f"{model_id}: documented conflict missing")
        if inventory["feature_order"] != expectation["feature_order"]:
            problems.append(f"{model_id}: feature order drifted")
    if problems:
        return "FAIL", "inventory problems: " + "; ".join(problems[:6])
    return "PASS", f"models={len(expected_model_ids(repository))}; schema+sources+Gate_A verified per model"


def _v2_02(repository: Path, run_dir: Path, run_id: str) -> tuple[str, str]:
    path = run_dir / "boundary" / "boundary_report.json"
    if not path.is_file():
        return "NOT_RUN", "boundary/boundary_report.json missing"
    report = read_json(path)
    problems: list[str] = []
    if report.get("run_id") != run_id:
        problems.append("run_id mismatch")
    if report.get("status") != "PASS":
        problems.append(f"status={report.get('status')}")
    checks = {check.get("name"): check for check in report.get("checks", [])}
    for name in BOUNDARY_CHECKS:
        if name not in checks:
            problems.append(f"{name} missing")
        elif checks[name].get("status") != "PASS":
            problems.append(f"{name}={checks[name].get('status')}")
    hardening = report.get("hardening", {})
    if hardening.get("network") != "none" or hardening.get("read_only") is not True:
        problems.append("hardening flags are not network-none/read-only")
    if hardening.get("user") in {None, "0", "0:0", "root"}:
        problems.append("container user is root")
    runtime = read_json(repository / "config" / "runtime_config.json")
    if report.get("image") != runtime.get("runner_image"):
        problems.append("boundary image differs from the configured runner image")
    if problems:
        return "FAIL", "boundary problems: " + "; ".join(problems[:6])
    return "PASS", f"image={report.get('image')}; checks={len(checks)} PASS; hardening verified by execution"


def _index_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [{"json_path": row["json_path"], "text": row["text"]} for row in csv.DictReader(handle)]


def _v2_03(repository: Path, run_dir: Path, run_id: str) -> tuple[str, str]:
    path = run_dir / "validation_metrics.json"
    if not path.is_file():
        return "NOT_RUN", "validation_metrics.json missing"
    metrics = read_json(path)
    frozen_path = run_dir / "frozen" / "frozen.json"
    frozen = read_json(frozen_path) if frozen_path.is_file() else {}
    problems: list[str] = []
    if metrics.get("run_id") != run_id:
        problems.append("run_id mismatch")
    if frozen and metrics.get("candidate_sha256") != frozen.get("candidate_sha256"):
        problems.append("metrics belong to another candidate")
    if metrics.get("parity", {}).get("status") != "PASS":
        problems.append(f"parity={metrics.get('parity', {}).get('status')}")
    for dataset in ("dev", "holdout", "shifted"):
        entry = metrics.get("performance", {}).get(dataset)
        if not isinstance(entry, dict):
            problems.append(f"performance.{dataset} missing")
            continue
        for key in ("rows", "positive_rows", "negative_rows", "roc_auc", "brier_score", "confusion_matrix", "calibration"):
            if key not in entry:
                problems.append(f"performance.{dataset}.{key} missing")
        deciles = (entry.get("calibration") or {}).get("value")
        if key == "calibration" and isinstance(deciles, list) and len(deciles) != 10:
            problems.append(f"performance.{dataset} calibration is not a decile table")
        if (entry.get("roc_auc") or {}).get("status") not in ("OK", "NOT_ASSESSABLE", "SINGLE_CLASS", "MISSING_LABELS"):
            problems.append(f"performance.{dataset}.roc_auc has no explicit state")
    stability = metrics.get("stability", {})
    if stability.get("reference") != "dev" or stability.get("scenario") != "A":
        problems.append("stability is not dev-referenced scenario A")
    if not stability.get("features") or "value" not in (stability.get("prediction") or {}):
        problems.append("stability PSI missing")
    fairness = metrics.get("fairness", {})
    for attribute in ("age_band", "sex"):
        entry = (fairness.get("attributes") or {}).get(attribute)
        if not isinstance(entry, dict) or not entry.get("groups"):
            problems.append(f"fairness.{attribute} missing")
            continue
        if not entry.get("reference_group"):
            problems.append(f"fairness.{attribute} has no reference group")
        for group, rates in entry["groups"].items():
            for key in ("rows", "positive_rows", "tpr", "fpr"):
                if key not in rates:
                    problems.append(f"fairness.{attribute}.{group}.{key} missing")
            for key in ("tpr", "fpr"):
                if rates.get(key, {}).get("status") is None:
                    problems.append(f"fairness.{attribute}.{group}.{key} has no state")
    for name, entry in (metrics.get("datasets") or {}).items():
        if name == "shifted":
            continue
        try:
            if entry.get("sha256") != verified_split_hash(run_dir, name):
                problems.append(f"datasets.{name} hash mismatch")
        except Exception:  # noqa: BLE001
            problems.append(f"datasets.{name} cannot be verified")
    if not (run_dir / "report" / "validation_tables.md").is_file() and not (run_dir / "validation" / "metrics_tables.md").is_file():
        problems.append("readable metric tables missing")
    if problems:
        return "FAIL", "metrics problems: " + "; ".join(problems[:6])
    return "PASS", "parity+performance+calibration+stability(A)+fairness computed; edge states recorded"


def _v2_chain(run_dir: Path, run_id: str) -> list[str]:
    """Order-flexible checks for the v2 steps.

    Per-model inventory approval may be interleaved with the next extraction, so
    the v2 tail is checked as a partial order instead of one fixed sequence.
    """

    path = run_dir / "command_log.jsonl"
    if not path.is_file():
        return ["command_log missing"]
    events = [event for event in read_jsonl(path) if event.get("run_id") == run_id]
    expected_attempt = _expected_attempt(run_dir)
    context_path = run_dir / "context_manifest.json"
    context_sha256 = sha256_file(context_path) if context_path.is_file() else None
    frozen_sha256 = _frozen_candidate_sha256(run_dir)

    def successful(command: str, **options) -> list[tuple[int, dict]]:
        found = []
        for index, event in enumerate(events):
            argv = event.get("argv") or []
            if len(argv) < 4 or argv[:3] != ["python", "-m", "src.cli"] or argv[3] != command:
                continue
            if event.get("exit_code") != 0:
                continue
            if any(_argv_option(argv, name) != value for name, value in options.items()):
                continue
            found.append((index, event))
        return found

    problems: list[str] = []
    first: dict[str, int] = {}
    for model in ("MDL_CREDIT_V2", "MDL_CREDIT_TREE"):
        extractions = successful("extract-inventory", **{"--model": model})
        approvals = successful("approve", **{"--gate": "Gate_A", "--model": model})
        if not extractions:
            problems.append(f"extract-inventory --model {model} has no successful attempt")
        if not approvals:
            problems.append(f"approve Gate_A --model {model} has no successful attempt")
        if extractions and approvals and approvals[0][0] < extractions[0][0]:
            problems.append(f"approve Gate_A --model {model} ran before its extraction")
        if extractions:
            first[f"extract {model}"] = extractions[0][0]
        for index, event in approvals:
            problems.extend(_chain_binding_problems(event, f"approve Gate_A {model}", "approve", run_id, expected_attempt, context_sha256, frozen_sha256))
    for index, event in successful("docker-boundary"):
        problems.extend(_chain_binding_problems(event, "docker-boundary", "docker-boundary", run_id, expected_attempt, context_sha256, frozen_sha256))
    if not successful("docker-boundary"):
        problems.append("docker-boundary has no successful attempt")

    sequence = [
        ("validation-metrics", {}),
        ("agent-summary", {}),
        ("report", {}),
        ("approve", {"--gate": "Gate_C"}),
        ("approve-report", {}),
    ]
    position = -1
    accepts = successful("accept")
    if accepts:
        position = accepts[0][0]
    for command, options in sequence:
        matches = [item for item in successful(command, **options) if item[0] > position]
        label = f"{command} {options.get('--gate', '')}".strip()
        if not matches:
            problems.append(f"{label} record missing or out of order")
            continue
        index, event = matches[0]
        position = index
        problems.extend(_chain_binding_problems(event, label, command, run_id, expected_attempt, context_sha256, frozen_sha256))
    return problems


def _frozen_attempt(run_dir: Path) -> tuple[int | None, dict]:
    path = run_dir / "frozen" / "frozen.json"
    if not path.is_file():
        return None, {}
    frozen = read_json(path)
    attempt = frozen.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool):
        return None, frozen
    return attempt, frozen


def _v2_04(repository: Path, run_dir: Path, run_id: str) -> tuple[str, str]:
    problems: list[str] = []
    context_sha256 = sha256_file(run_dir / "context_manifest.json") if (run_dir / "context_manifest.json").is_file() else None
    reviews = read_json(run_dir / "review_log.json").get("reviews", []) if (run_dir / "review_log.json").is_file() else []
    approved = [entry for entry in reviews if entry.get("decision") == "APPROVED" and entry.get("context_sha256") == context_sha256]
    gate_a_times = [entry["timestamp"] for entry in approved if entry.get("gate") == "Gate_A"]

    # The gate chain must be checked on the attempt that was actually frozen and
    # passed, not on attempt_000: a first-attempt failure followed by a successful
    # repair is legal and covered by tests/test_v2_blockers.py.
    attempt, frozen = _frozen_attempt(run_dir)
    if attempt is None:
        problems.append("no frozen candidate with a recorded attempt")
    else:
        directory = run_dir / "candidates" / f"attempt_{attempt:03d}"
        metadata_path = directory / "candidate.json"
        if not metadata_path.is_file():
            problems.append(f"frozen attempt {attempt} has no candidate metadata")
        else:
            metadata = read_json(metadata_path)
            if metadata.get("attempt") != attempt:
                problems.append("frozen attempt and candidate metadata disagree")
            if metadata.get("model_id") != "MDL_CREDIT_V1":
                problems.append("migration scope is not limited to MDL_CREDIT_V1")
            if metadata.get("candidate_sha256") != frozen.get("candidate_sha256"):
                problems.append("frozen hash is not the candidate hash")
            if not gate_a_times or metadata.get("created_at", "") < min(gate_a_times):
                problems.append("candidate was generated before Gate A approval")
            source = directory / "credit_v1.py"
            if not source.is_file() or sha256_file(source) != metadata.get("candidate_sha256"):
                problems.append(f"candidate source for attempt {attempt} does not match its metadata")
            if current_decision(run_dir, run_id, "Gate_B", source) != "APPROVED":
                problems.append("Gate_B is not APPROVED for the frozen candidate hash")
            gate_b_times = [
                entry["timestamp"]
                for entry in approved
                if entry.get("gate") == "Gate_B" and entry.get("reviewed_artifact_sha256") == metadata.get("candidate_sha256")
            ]
            execution = run_dir / "dev" / f"attempt_{attempt:03d}" / "execution.json"
            if not gate_b_times:
                problems.append("no Gate B approval for the executed candidate hash")
            elif execution.is_file():
                started = read_json(execution).get("started_at")
                if started and started < min(gate_b_times):
                    problems.append("development execution started before Gate B")
            if not _valid_execution(execution):
                problems.append("frozen attempt's development execution does not satisfy the isolation contract")
            parity = run_dir / "dev" / f"attempt_{attempt:03d}" / "parity_summary.json"
            if not parity.is_file() or read_json(parity).get("status") != "PASS":
                problems.append(f"frozen attempt {attempt} has no passing development parity")
            fixtures = run_dir / "dev" / f"attempt_{attempt:03d}" / "fixture_summary.json"
            if not fixtures.is_file():
                problems.append(f"frozen attempt {attempt} has no behaviour fixture summary")
            else:
                summary = read_json(fixtures)
                if summary.get("status") != "PASS" or summary.get("candidate_sha256") != frozen.get("candidate_sha256"):
                    problems.append(f"frozen attempt {attempt} did not pass the behaviour fixtures")
        migration_path = run_dir / "migration_result.json"
        if not migration_path.is_file():
            problems.append("migration result missing")
        else:
            migration = read_json(migration_path)
            if migration.get("attempt") != attempt or migration.get("candidate_sha256") != frozen.get("candidate_sha256"):
                problems.append("migration result does not describe the frozen attempt")
            if migration.get("dev_status") != "PASS":
                problems.append("migration result does not record a passing development run")

    manifest_path = run_dir / "report" / "review_manifest.json"
    if not manifest_path.is_file():
        problems.append("report review manifest missing")
    else:
        if current_decision(run_dir, run_id, "Gate_C", manifest_path) != "APPROVED":
            problems.append("Gate_C is not APPROVED for the current report manifest")
        gate_c_times = [entry["timestamp"] for entry in approved if entry.get("gate") == "Gate_C"]
        approval_path = run_dir / "report" / "approval.json"
        if not approval_path.is_file():
            problems.append("report approval record missing")
        elif gate_c_times and read_json(approval_path).get("approved_at", "") < min(gate_c_times):
            problems.append("report was approved before Gate C")
    if problems:
        return "FAIL", "gate problems: " + "; ".join(problems[:6])
    return "PASS", (
        "Gate A -> candidate -> Gate B -> execution -> Gate C -> approval order and hashes verified "
        f"on the frozen attempt {attempt}"
    )


def _v2_05(repository: Path, run_dir: Path, run_id: str) -> tuple[str, str]:
    problems = _v2_chain(run_dir, run_id)
    problems.extend(_export_evidence(run_dir, run_id))
    for relative in ("validation_metrics.json", "report/validation_report.md", "report/values_index.csv", "report/review_manifest.json"):
        if not (run_dir / relative).is_file():
            problems.append(f"{relative} missing")
    run_ids = {}
    for label, path in (
        ("metrics", run_dir / "validation_metrics.json"),
        ("review_manifest", run_dir / "report" / "review_manifest.json"),
        ("data_manifest", run_dir / "data" / "data_manifest.json"),
        ("export", run_dir / "export_verified.json"),
        ("acceptance", run_dir / "acceptance.json"),
    ):
        if path.is_file():
            run_ids[label] = read_json(path).get("run_id")
    mismatched = [label for label, value in run_ids.items() if value != run_id]
    if mismatched:
        problems.append("run_id mismatch in " + ",".join(mismatched))
    if problems:
        return "FAIL", "end-to-end problems: " + "; ".join(problems[:6])
    return "PASS", "CLI chain complete in one run; MD/CSV/JSON exported; run_id consistent; evidence hashes verified"


def _v2_06(repository: Path, run_dir: Path, run_id: str) -> tuple[str, str]:
    path = run_dir / "failures" / "failure_drills.json"
    if not path.is_file():
        return "NOT_RUN", "failures/failure_drills.json missing"
    report = read_json(path)
    problems: list[str] = []
    if report.get("format_version") != "2":
        problems.append("drill report format_version is not 2 (v1 failures are not enough)")
    drills = {drill.get("name"): drill for drill in report.get("drills", [])}
    for name in DRILL_NAMES:
        drill = drills.get(name)
        if not drill:
            problems.append(f"{name} missing")
            continue
        if drill.get("status") != "OBSERVED":
            problems.append(f"{name} status={drill.get('status')}")
        if not drill.get("error"):
            problems.append(f"{name} recorded no error text")
        if drill.get("mode") not in {"REAL_API", "LOCAL_INJECTED"}:
            problems.append(f"{name} has no honest mode label")
    if problems:
        return "FAIL", "drill problems: " + "; ".join(problems[:6])
    modes = sorted({drill.get("mode") for drill in drills.values()})
    return "PASS", f"drills={len(drills)}; modes={modes}; failure text preserved"


def _v2_07(repository: Path, run_dir: Path, run_id: str) -> tuple[str, str]:
    report_path = run_dir / "report" / "validation_report.md"
    index_path = run_dir / "report" / "values_index.csv"
    if not report_path.is_file() or not index_path.is_file():
        return "NOT_RUN", "report or values index missing"
    text = report_path.read_text(encoding="utf-8")
    rows = _index_rows(index_path)
    problems: list[str] = []
    unresolved = verify_provenance(text, rows)
    if unresolved:
        problems.append(f"numbers without a JSON path: {unresolved[:5]}")
    if len(rows) < 20:
        problems.append("values index is too small to cover the report")
    status = report_status(run_dir, run_id)
    if status["status"] != "APPROVED":
        problems.append("report status=" + ",".join(status["reasons"][:3]))
    summary_path = run_dir / "report" / "agent_summary.json"
    if not summary_path.is_file():
        problems.append("agent summary missing")
    else:
        summary = read_json(summary_path)
        if not summary.get("request_id") or not summary.get("request_event_id"):
            problems.append("agent summary has no gateway request id")
        if summary.get("run_id") != run_id:
            problems.append("agent summary run_id mismatch")
        try:
            check_wording(" ".join([summary.get("headline", "")] + summary.get("results", []) + summary.get("limitations", [])))
        except Exception as error:  # noqa: BLE001
            problems.append(str(error)[:120])
    required_phrases = ("same-period", "drift batch", "back-test")
    for phrase in required_phrases:
        if phrase not in text:
            problems.append(f"report does not distinguish {phrase}")
    if "audit signals, not proof" not in text:
        problems.append("report does not bound the fairness claim")
    if problems:
        return "FAIL", "report problems: " + "; ".join(problems[:6])
    return "PASS", f"value paths={len(rows)}; unresolved=0; Gate_C APPROVED; limitations stated"


def evaluate_v2_acceptance(repository: Path, run_dir: Path, run_id: str) -> list[dict]:
    checks = {
        "V2-01": _v2_01,
        "V2-02": _v2_02,
        "V2-03": _v2_03,
        "V2-04": _v2_04,
        "V2-05": _v2_05,
        "V2-06": _v2_06,
        "V2-07": _v2_07,
    }
    evidence_paths = {
        "V2-01": "inventories/MDL_CREDIT_V2.json",
        "V2-02": "boundary/boundary_report.json",
        "V2-03": "validation_metrics.json",
        "V2-04": "review_log.json",
        "V2-05": "evidence_manifest.json",
        "V2-06": "failures/failure_drills.json",
        "V2-07": "report/validation_report.md",
    }
    timestamp = utc_now()
    commit = current_git_commit(repository)
    records = []
    for acceptance_id, function in checks.items():
        status, actual = function(repository, run_dir, run_id)
        records.append(AcceptanceRecord(
            acceptance_id=acceptance_id,
            version="v2",
            expected=EXPECTED_V2[acceptance_id],
            actual=actual,
            status=status,
            evidence_path=evidence_paths[acceptance_id],
            reviewer="automated-cli-check",
            timestamp=timestamp,
            commit_sha=commit,
        ).model_dump())
    return records
