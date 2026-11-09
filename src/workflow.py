from __future__ import annotations

from pathlib import Path

from src.common import ContractError, GateError, read_json, sha256_file, utc_now, write_json
from src.context import verify_context
from src.contracts import MigrationResult
from src.holdout import consume_holdout
from src.migration import load_candidate, load_frozen, update_dev_result
from src.parity import compare_files
from src.review import require_approval
from src.runner import run_candidate

ROW_FIXTURES = ("behavior", "column_reordered", "row_reordered")
REJECTION_FIXTURES = ("duplicate_ids", "missing_column", "empty")


def _inventory_gate(run_dir: Path, run_id: str) -> None:
    require_approval(run_dir, run_id, "Gate_A", run_dir / "model_inventory.json")


def _manifest_hash(run_dir: Path, name: str) -> str:
    manifest_path = run_dir / "data" / "data_manifest.json"
    if not manifest_path.is_file():
        raise ContractError("Prepared data manifest is missing")
    expected = read_json(manifest_path).get("files", {}).get(f"{name}.csv", {}).get("sha256")
    path = run_dir / "data" / f"{name}.csv"
    if not expected or not path.is_file() or sha256_file(path) != expected:
        raise ContractError(f"{name}.csv does not match the prepared data manifest")
    return expected


def runner_image(run_dir: Path) -> str:
    config = run_dir.parent.parent / "config" / "runtime_config.json"
    image = read_json(config).get("runner_image") if config.is_file() else None
    if not image:
        raise ContractError("Runner image is not configured")
    return str(image)


def fixture_summary_path(run_dir: Path, attempt: int) -> Path:
    return run_dir / "dev" / f"attempt_{attempt:03d}" / "fixture_summary.json"


def _fixture_summary(run_dir: Path, attempt: int) -> dict:
    path = fixture_summary_path(run_dir, attempt)
    return read_json(path) if path.is_file() else {}


def _require_fixtures(run_dir: Path, run_id: str, attempt: int, candidate_sha256: str) -> None:
    summary = _fixture_summary(run_dir, attempt)
    if summary.get("run_id") != run_id or summary.get("candidate_sha256") != candidate_sha256 or summary.get("status") != "PASS":
        raise GateError("Candidate must pass the fixed behaviour fixtures in Docker before freezing, Holdout or acceptance")


def run_development(run_dir: Path, run_id: str, attempt: int) -> dict:
    repository = run_dir.parent.parent
    if not verify_context(repository, run_dir, run_id):
        raise ContractError("Development context is missing or invalidated")
    _inventory_gate(run_dir, run_id)
    _manifest_hash(run_dir, "dev")
    directory, metadata = load_candidate(run_dir, attempt)
    if metadata.get("context_sha256") != sha256_file(run_dir / "context_manifest.json"):
        raise ContractError("Candidate was generated under a different context")
    source = directory / "credit_v1.py"
    require_approval(run_dir, run_id, "Gate_B", source)
    work_dir = run_dir / "dev" / f"attempt_{attempt:03d}"
    if work_dir.exists():
        raise ContractError("Development execution for this attempt already exists")
    execution = run_candidate(
        source,
        run_dir / "reference" / "model.json",
        run_dir / "data" / "dev.csv",
        work_dir,
        image=runner_image(run_dir),
    )
    execution.update({"run_id": run_id, "context_sha256": metadata["context_sha256"]})
    write_json(work_dir / "execution.json", execution)
    parity = None
    dev_status = "FAIL"
    if execution["status"] == "PASS":
        parity = compare_files(
            run_dir / "reference" / "dev_predictions.csv",
            work_dir / "output" / "predictions.csv",
            work_dir / "parity_summary.json",
            work_dir / "parity_diff.csv",
            run_id=run_id,
            input_path=run_dir / "data" / "dev.csv",
        )
        dev_status = "PASS" if parity["status"] == "PASS" else "FAIL"
    diagnostics = {
        "schema_version": "1",
        "run_id": run_id,
        "attempt": attempt,
        "candidate_sha256": metadata["candidate_sha256"],
        "execution_status": execution["status"],
        "parity_status": parity["status"] if parity else "NOT_RUN",
        "max_abs_diff": parity.get("max_abs_diff") if parity else None,
        "mean_abs_diff": parity.get("mean_abs_diff") if parity else None,
        "classification_mismatch_count": parity.get("classification_mismatch_count") if parity else None,
        "reasons": parity.get("reasons", []) if parity else [execution.get("error") or "Candidate execution failed"],
        "contains_raw_rows": False,
        "contains_baseline_answers": False,
        "created_at": utc_now(),
    }
    diagnostics_path = work_dir / "dev_diagnostics.json"
    write_json(diagnostics_path, diagnostics)
    update_dev_result(run_dir, run_id, attempt, dev_status, str(diagnostics_path.relative_to(run_dir)))
    return {"status": dev_status, "execution": execution, "diagnostics": str(diagnostics_path)}


def run_candidate_fixtures(run_dir: Path, run_id: str, attempt: int) -> dict:
    repository = run_dir.parent.parent
    if not verify_context(repository, run_dir, run_id):
        raise ContractError("Fixture context is missing or invalidated")
    _inventory_gate(run_dir, run_id)
    directory, metadata = load_candidate(run_dir, attempt)
    if metadata.get("context_sha256") != sha256_file(run_dir / "context_manifest.json"):
        raise ContractError("Candidate was generated under a different context")
    source = directory / "credit_v1.py"
    require_approval(run_dir, run_id, "Gate_B", source)
    work_dir = run_dir / "dev" / f"attempt_{attempt:03d}" / "fixtures"
    if work_dir.exists():
        raise ContractError("Candidate fixture execution for this attempt already exists")
    image = runner_image(run_dir)
    records: list[dict] = []
    for name in ROW_FIXTURES:
        input_path = run_dir / "data" / "fixtures" / f"{name}.csv"
        reference = run_dir / "fixtures" / name / "r" / "dev_predictions.csv"
        case_dir = work_dir / name
        execution = run_candidate(source, run_dir / "reference" / "model.json", input_path, case_dir, image=image)
        execution.update({"run_id": run_id, "context_sha256": metadata["context_sha256"]})
        write_json(case_dir / "execution.json", execution)
        parity = None
        if execution.get("status") == "PASS" and reference.is_file():
            parity = compare_files(
                reference,
                case_dir / "output" / "predictions.csv",
                case_dir / "parity_summary.json",
                case_dir / "parity_diff.csv",
                run_id=run_id,
                input_path=input_path,
            )
        records.append({
            "kind": "ROW_BEHAVIOUR",
            "name": name,
            "candidate_sha256": metadata["candidate_sha256"],
            "execution_status": execution.get("status"),
            "parity_status": (parity or {}).get("status", "NOT_RUN"),
            "max_abs_diff": (parity or {}).get("max_abs_diff"),
            "classification_mismatch_count": (parity or {}).get("classification_mismatch_count"),
            "behaviour_mismatch_count": (parity or {}).get("behaviour_mismatch_count"),
        })
    for name in REJECTION_FIXTURES:
        input_path = run_dir / "data" / "fixtures" / f"{name}.csv"
        case_dir = work_dir / name
        execution = run_candidate(source, run_dir / "reference" / "model.json", input_path, case_dir, image=image)
        execution.update({"run_id": run_id, "context_sha256": metadata["context_sha256"]})
        write_json(case_dir / "execution.json", execution)
        rejected = execution.get("status") != "PASS" and execution.get("exit_code") == 2
        records.append({
            "kind": "STRUCTURAL_REJECTION",
            "name": name,
            "candidate_sha256": metadata["candidate_sha256"],
            "execution_status": execution.get("status"),
            "exit_code": execution.get("exit_code"),
            "parity_status": "PASS" if rejected else "FAIL",
        })
    status = "PASS" if all(record["parity_status"] == "PASS" for record in records) else "FAIL"
    summary = {
        "schema_version": "1",
        "run_id": run_id,
        "attempt": attempt,
        "candidate_sha256": metadata["candidate_sha256"],
        "context_sha256": metadata["context_sha256"],
        "image": image,
        "status": status,
        "records": records,
        "created_at": utc_now(),
    }
    write_json(fixture_summary_path(run_dir, attempt), summary)
    # A fixture FAIL is a first-class repair trigger: record an aggregate-only
    # diagnostics payload (never raw rows or baseline answers) so the next attempt
    # can be generated without invalidating the run.
    fixture_diagnostics = {
        "schema_version": "1",
        "run_id": run_id,
        "attempt": attempt,
        "candidate_sha256": metadata["candidate_sha256"],
        "fixture_status": status,
        "failing_cases": [
            {
                "name": record["name"],
                "kind": record["kind"],
                "parity_status": record.get("parity_status"),
                "execution_status": record.get("execution_status"),
                "exit_code": record.get("exit_code"),
                "max_abs_diff": record.get("max_abs_diff"),
                "classification_mismatch_count": record.get("classification_mismatch_count"),
                "behaviour_mismatch_count": record.get("behaviour_mismatch_count"),
            }
            for record in records
            if record.get("parity_status") != "PASS"
        ],
        "contains_raw_rows": False,
        "contains_baseline_answers": False,
        "created_at": utc_now(),
    }
    fixture_diagnostics_path = run_dir / "dev" / f"attempt_{attempt:03d}" / "fixture_diagnostics.json"
    write_json(fixture_diagnostics_path, fixture_diagnostics)
    existing_result_path = run_dir / "migration_result.json"
    existing = read_json(existing_result_path) if existing_result_path.is_file() else {}
    dev_status = existing.get("dev_status") or "NOT_RUN"
    diagnostics_ref = existing.get("diagnostics_ref") if dev_status == "FAIL" else str(fixture_diagnostics_path.relative_to(run_dir))
    update_dev_result(run_dir, run_id, attempt, dev_status, diagnostics_ref, fixture_status=status)
    return summary


def run_holdout(run_dir: Path, run_id: str) -> dict:
    repository = run_dir.parent.parent
    if not verify_context(repository, run_dir, run_id):
        raise ContractError("Holdout context is missing or invalidated")
    _inventory_gate(run_dir, run_id)
    _manifest_hash(run_dir, "holdout")
    frozen = load_frozen(run_dir, run_id)
    context_sha256 = sha256_file(run_dir / "context_manifest.json")
    if frozen.get("context_sha256") != context_sha256:
        raise ContractError("Frozen candidate belongs to an invalidated context")
    candidate_dir, metadata = load_candidate(run_dir, frozen["attempt"])
    if metadata["candidate_sha256"] != frozen["candidate_sha256"]:
        raise ContractError("Frozen hash is not the approved candidate hash")
    require_approval(run_dir, run_id, "Gate_B", candidate_dir / "credit_v1.py")
    attempt = frozen["attempt"]
    migration = read_json(run_dir / "migration_result.json")
    if migration.get("candidate_sha256") != frozen["candidate_sha256"] or migration.get("dev_status") != "PASS":
        raise GateError("Holdout requires a frozen candidate whose development parity passed")
    dev_execution_path = run_dir / "dev" / f"attempt_{attempt:03d}" / "execution.json"
    dev_execution = read_json(dev_execution_path) if dev_execution_path.is_file() else {}
    if dev_execution.get("status") != "PASS" or dev_execution.get("exit_code") != 0:
        raise GateError("Holdout requires a successful Docker development execution for the frozen candidate")
    image = runner_image(run_dir)
    if dev_execution.get("image") != image:
        raise ContractError("Runner image changed after the approved development execution")
    _require_fixtures(run_dir, run_id, attempt, frozen["candidate_sha256"])
    work_dir = run_dir / "holdout"
    if work_dir.exists():
        raise ContractError("Holdout evaluation has already been attempted; its result is immutable for this run")
    consume_holdout(run_dir, run_id, frozen["candidate_sha256"])
    execution = run_candidate(
        run_dir / "frozen" / "credit_v1.py",
        run_dir / "reference" / "model.json",
        run_dir / "data" / "holdout.csv",
        work_dir,
        image=image,
    )
    execution.update({"run_id": run_id, "context_sha256": context_sha256})
    write_json(work_dir / "execution.json", execution)
    parity = None
    final_status = "FAIL"
    if execution["status"] == "PASS":
        parity = compare_files(
            run_dir / "reference" / "holdout_predictions.csv",
            work_dir / "output" / "predictions.csv",
            work_dir / "parity_summary.json",
            work_dir / "parity_diff.csv",
            run_id=run_id,
            input_path=run_dir / "data" / "holdout.csv",
        )
        final_status = "PASS" if parity["status"] == "PASS" else "FAIL"
    else:
        write_json(work_dir / "parity_summary.json", {"schema_version": "1", "run_id": run_id, "status": "FAIL", "reasons": ["Candidate execution did not produce a valid prediction file"], "execution_status": execution["status"]})
    migration = read_json(run_dir / "migration_result.json")
    result = MigrationResult(
        run_id=run_id,
        model_id="MDL_CREDIT_V1",
        candidate_sha256=frozen["candidate_sha256"],
        attempt=frozen["attempt"],
        dev_status=migration["dev_status"],
        final_status=final_status,
        diagnostics_ref=migration.get("diagnostics_ref"),
        context_sha256=context_sha256,
    )
    write_json(run_dir / "migration_result.json", result.model_dump())
    return {"status": final_status, "execution_status": execution["status"], "parity": parity, "evidence": str(work_dir)}
