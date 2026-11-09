from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from src.acceptance import write_acceptance
from src.agent import check_provider, extract_inventory, generate_candidate, summarize_validation
from src.baseline import run_r_baseline
from src.behavior import run_fixture_parity
from src.boundary import run_boundary_suite
from src.context import create_context
from src.common import (
    ContractError,
    append_jsonl,
    create_run,
    current_git_commit,
    load_run,
    read_json,
    redact_arguments,
    sha256_file,
    source_snapshot,
    update_run_state,
    utc_now,
    write_json,
)
from src.data import download_uci, prepare_synthetic, prepare_uci
from src.evidence import export_evidence
from src.failures import run_failure_drills
from src.fixtures import write_fixtures
from src.local_checks import run_mutation_check, run_reference_parity
from src.inventory import expected_model_ids, inventory_path
from src.migration import candidate_dir, freeze_candidate, load_candidate
from src.report import render_report, report_status, write_approval
from src.review import artifact_digest, current_decision, record_review
from src.validation import compute_validation_metrics
from src.workflow import run_candidate_fixtures, run_development, run_holdout

REPOSITORY = Path(__file__).resolve().parents[1]
# Dev dry runs can point at a sibling directory so the sealed runs/ artifacts and
# the Holdout consumption ledger of released campaigns are never touched.
RUNS_ROOT = Path(os.environ.get("MRF_RUNS_ROOT") or (REPOSITORY / "runs")).resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="Model Risk Factory v1 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init-run")
    init.add_argument("--mode", choices=["synthetic", "uci"], default="synthetic")

    for name in [
        "check-provider", "prepare", "baseline", "reference-parity", "fixture-parity", "mutation-check",
        "extract-inventory", "generate-candidate", "run-dev", "candidate-fixtures", "freeze", "accept", "acceptance", "export", "status",
        "docker-boundary", "validation-metrics", "agent-summary", "report", "approve-report", "report-status", "failure-drills",
    ]:
        command = subparsers.add_parser(name)
        command.add_argument("--run-id", required=True)

    prepare = subparsers.choices["prepare"]
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", action="store_true")
    source.add_argument("--uci", type=Path)
    # The campaign seed is owned by config/data_config.json. Leaving --seed unset must
    # therefore resolve to that value, never to a hard-coded literal that can drift
    # from the configuration (v2 defect: the CLI default was frozen at 42 while the
    # campaign config moved to 43).
    prepare.add_argument("--seed", type=int, default=None)
    prepare.add_argument("--expected-sha256")
    prepare.add_argument("--approve-uci-use", action="store_true")

    download = subparsers.add_parser("download-uci")
    download.add_argument("--run-id", required=True)
    download.add_argument("--output", type=Path, default=REPOSITORY / "data" / "raw" / "default_of_credit_card_clients.zip")
    download.add_argument("--expected-sha256", required=True)
    download.add_argument("--approve-uci-use", action="store_true")

    approve = subparsers.add_parser("approve")
    approve.add_argument("--run-id", required=True)
    approve.add_argument("--gate", choices=["Gate_A", "Gate_B", "Gate_C"], required=True)
    approve.add_argument("--model", default="MDL_CREDIT_V1", choices=["MDL_CREDIT_V1", "MDL_CREDIT_V2", "MDL_CREDIT_TREE"])
    approve.add_argument("--sha256", required=True)
    approve.add_argument("--decision", choices=["APPROVED", "REJECTED"], default="APPROVED")
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--comment", default="")
    approve.add_argument("--attempt", type=int)

    for name in ("generate-candidate", "run-dev", "candidate-fixtures", "freeze"):
        subparsers.choices[name].add_argument("--attempt", type=int, required=True)
    subparsers.choices["extract-inventory"].add_argument(
        "--model", default="MDL_CREDIT_V1", choices=["MDL_CREDIT_V1", "MDL_CREDIT_V2", "MDL_CREDIT_TREE"]
    )
    show = subparsers.add_parser("show-candidate")
    show.add_argument("--run-id", required=True)
    show.add_argument("--attempt", type=int, required=True)
    return parser


def resolve_campaign_seed(requested: int | None, repository: Path) -> int:
    """Resolve ``prepare --seed`` against the frozen campaign configuration.

    ``None`` means "use the configured campaign seed"; an explicit value that
    disagrees with the configuration is rejected instead of silently reseeding.
    """

    campaign_seed = int(read_json(repository / "config" / "data_config.json")["seed"])
    if requested is None:
        return campaign_seed
    if requested != campaign_seed:
        raise ContractError(
            f"Seed {requested} does not match the configured campaign seed {campaign_seed}"
        )
    return campaign_seed


def _status(repository: Path, run_dir: Path, run_id: str) -> dict:
    inventory_path = run_dir / "model_inventory.json"
    inventory = None
    if inventory_path.is_file():
        inventory = {
            "path": str(inventory_path),
            "artifact_sha256": artifact_digest(inventory_path, "Gate_A"),
            "review": current_decision(run_dir, run_id, "Gate_A", inventory_path),
            "approval_command": f"python -m src.cli approve --run-id {run_id} --gate Gate_A --sha256 {artifact_digest(inventory_path, 'Gate_A')} --reviewer YOUR_NAME --comment 'Reviewed inventory sources, Unknown fields and threshold conflict'",
        }
    candidates = []
    candidates_root = run_dir / "candidates"
    if candidates_root.is_dir():
        for path in sorted(candidates_root.glob("attempt_*")):
            metadata = read_json(path / "candidate.json")
            source = path / "credit_v1.py"
            candidates.append({
                "attempt": metadata["attempt"],
                "candidate_sha256": metadata["candidate_sha256"],
                "source": str(source),
                "diff": str(path / "candidate.diff"),
                "review": current_decision(run_dir, run_id, "Gate_B", source),
                "approval_command": f"python -m src.cli approve --run-id {run_id} --gate Gate_B --attempt {metadata['attempt']} --sha256 {metadata['candidate_sha256']} --reviewer YOUR_NAME --comment 'Reviewed candidate diff and hash'",
            })
    return {"run_id": run_id, "manifest": read_json(run_dir / "run_manifest.json"), "inventory": inventory, "candidates": candidates}


def _dispatch(arguments: argparse.Namespace) -> dict[str, Any]:
    command = arguments.command
    if command == "init-run":
        manifest = create_run(RUNS_ROOT, REPOSITORY, arguments.mode)
        return {"run_id": manifest["run_id"], "status": "INITIALIZED", "manifest": manifest}
    run_dir, manifest = load_run(RUNS_ROOT, arguments.run_id)
    run_id = arguments.run_id
    if command == "check-provider":
        return check_provider(run_dir, run_id)
    if command == "download-uci":
        result = download_uci(arguments.output, arguments.approve_uci_use, arguments.expected_sha256)
        write_json(run_dir / "data" / "download.json", {"schema_version": "1", "run_id": run_id, "approved": True, **result})
        return {"status": "PASS", **result}
    if command in {"prepare", "baseline"} and any((run_dir / name).exists() for name in ("model_inventory.json", "candidates", "frozen")):
        raise ContractError("Inputs and baseline are immutable after migration starts; create a new run")
    if command == "prepare":
        resolved_seed = resolve_campaign_seed(arguments.seed, REPOSITORY)
        if arguments.synthetic:
            result = prepare_synthetic(run_dir / "data", seed=resolved_seed)
        else:
            result = prepare_uci(arguments.uci, run_dir / "data", arguments.approve_uci_use, arguments.expected_sha256 or "", run_id=run_id)
        result["run_id"] = run_id
        write_json(run_dir / "data" / "data_manifest.json", result)
        write_fixtures(run_dir / "data" / "fixtures")
        update_run_state(run_dir, "DATA_PREPARED")
        return {"status": "PREPARED", "data_manifest": result}
    if command == "baseline":
        result = run_r_baseline(REPOSITORY, run_dir, REPOSITORY / "config" / "runtime_config.json")
        create_context(REPOSITORY, run_dir)
        update_run_state(run_dir, "REFERENCE_BASELINE_READY")
        return result
    if command == "reference-parity":
        results = run_reference_parity(run_dir)
        return {"status": "PASS" if all(item["status"] == "PASS" for item in results.values()) else "FAIL", "results": results}
    if command == "fixture-parity":
        return run_fixture_parity(REPOSITORY, run_dir)
    if command == "mutation-check":
        return run_mutation_check(REPOSITORY, run_dir)
    if command == "docker-boundary":
        report = run_boundary_suite(run_dir, REPOSITORY / "config" / "runtime_config.json")
        return {"status": report["status"], "report": str(run_dir / "boundary" / "boundary_report.json"), "checks": [check["name"] + ":" + check["status"] for check in report["checks"]]}
    if command == "extract-inventory":
        inventory = extract_inventory(REPOSITORY, run_dir, run_id, arguments.model)
        return {
            "status": "PENDING_GATE_A",
            "model_id": arguments.model,
            "inventory": inventory,
            "artifact_sha256": artifact_digest(inventory_path(run_dir, arguments.model), "Gate_A"),
        }
    if command == "approve":
        if arguments.gate == "Gate_A":
            artifact = inventory_path(run_dir, arguments.model)
        elif arguments.gate == "Gate_C":
            artifact = run_dir / "report" / "report_review.json"
        else:
            if arguments.attempt is None:
                raise ContractError("Gate B requires --attempt")
            artifact = candidate_dir(run_dir, arguments.attempt) / "credit_v1.py"
        review = record_review(run_dir, run_id, arguments.gate, artifact, arguments.sha256, arguments.decision, arguments.reviewer, arguments.comment)
        update_run_state(run_dir, "INVENTORY_REVIEWED" if arguments.gate == "Gate_A" and arguments.decision == "APPROVED" else "CANDIDATE_APPROVED" if arguments.gate == "Gate_B" and arguments.decision == "APPROVED" else "REPORT_REVIEWED" if arguments.decision == "APPROVED" else "REVIEW_REJECTED")
        return {"status": "RECORDED", "review": review}
    if command == "generate-candidate":
        metadata = generate_candidate(REPOSITORY, run_dir, run_id, arguments.attempt)
        directory = candidate_dir(run_dir, arguments.attempt)
        update_run_state(run_dir, "CANDIDATE_GENERATED")
        return {"status": "PENDING_GATE_B", **metadata, "source": str(directory / "credit_v1.py"), "diff": str(directory / "candidate.diff")}
    if command == "show-candidate":
        directory, metadata = load_candidate(run_dir, arguments.attempt)
        return {"status": "CANDIDATE", "metadata": metadata, "diff": (directory / "candidate.diff").read_text(encoding="utf-8")}
    if command == "run-dev":
        result = run_development(run_dir, run_id, arguments.attempt)
        update_run_state(run_dir, "DEV_PASSED" if result["status"] == "PASS" else "FAILED")
        return result
    if command == "candidate-fixtures":
        result = run_candidate_fixtures(run_dir, run_id, arguments.attempt)
        return {"status": result["status"], "fixture_summary": result}
    if command == "freeze":
        frozen = freeze_candidate(run_dir, run_id, arguments.attempt)
        update_run_state(run_dir, "CANDIDATE_FROZEN")
        return {"status": "FROZEN", **frozen}
    if command == "accept":
        result = run_holdout(run_dir, run_id)
        update_run_state(run_dir, "FINAL_EVALUATED" if result["status"] == "PASS" else "FAILED")
        return result
    if command == "acceptance":
        return write_acceptance(REPOSITORY, run_dir, run_id)
    if command == "failure-drills":
        report = run_failure_drills(run_dir, run_id)
        return {
            "status": report["status"],
            "report": str(run_dir / "failures" / "failure_drills.json"),
            "drills": [f"{drill['name']}:{drill['status']}" for drill in report["drills"]],
        }
    if command == "validation-metrics":
        metrics = compute_validation_metrics(
            run_dir,
            run_id,
            threshold=float(read_json(REPOSITORY / "config" / "model_config.json")["threshold"]),
            tolerances=read_json(REPOSITORY / "config" / "model_config.json"),
        )
        return {
            "status": "PASS" if metrics["parity"]["status"] == "PASS" else "FAIL",
            "validation_metrics": str(run_dir / "validation_metrics.json"),
            "parity": metrics["parity"]["status"],
            "holdout_roc_auc": metrics["performance"]["holdout"]["roc_auc"]["value"],
            "stability": metrics["stability"]["status"],
        }
    if command == "agent-summary":
        summary = summarize_validation(REPOSITORY, run_dir, run_id)
        return {"status": "PASS", "request_id": summary["request_id"], "agent_summary": str(run_dir / "report" / "agent_summary.json")}
    if command == "report":
        inventories = {
            model_id: current_decision(run_dir, run_id, "Gate_A", inventory_path(run_dir, model_id))
            for model_id in expected_model_ids(REPOSITORY)
        }
        agent_path = run_dir / "report" / "agent_summary.json"
        rendered = render_report(run_dir, run_id, agent_summary=read_json(agent_path) if agent_path.is_file() else None, inventories=inventories)
        return {"status": "PASS" if not rendered["unresolved_numbers"] else "FAIL", **rendered}
    if command == "approve-report":
        return {"status": "APPROVED", **write_approval(run_dir, run_id)}
    if command == "report-status":
        return report_status(run_dir, run_id)
    if command == "status":
        return {"status": "OK", **_status(REPOSITORY, run_dir, run_id)}
    if command == "export":
        snapshot = source_snapshot(REPOSITORY)
        write_json(run_dir / "source_snapshot.json", snapshot)
        run_manifest_path = run_dir / "run_manifest.json"
        current = read_json(run_manifest_path)
        current["source_snapshot_at_export_sha256"] = snapshot["combined_sha256"]
        current["git_commit_at_export"] = current_git_commit(REPOSITORY)
        write_json(run_manifest_path, current)
        exported = export_evidence(run_dir, run_id, REPOSITORY / "delivery")
        acceptance = write_acceptance(REPOSITORY, run_dir, run_id)
        (REPOSITORY / "delivery" / f"{run_id}_acceptance.json").write_text(
            (run_dir / "acceptance.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        return {"status": "EXPORTED", **exported, "release_approved": acceptance["release_approved"]}
    raise ContractError(f"Unknown command: {command}")


def _exit_code(result: dict) -> int:
    status = result.get("status")
    if status in {"FAIL", "FAILED", "EXECUTION_ERROR", "TIMEOUT"}:
        return 1
    if status == "BLOCKED":
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    arguments = parser.parse_args(raw_arguments)
    started = utc_now()
    run_id = getattr(arguments, "run_id", None)
    try:
        result = _dispatch(arguments)
        run_id = result.get("run_id", run_id)
        exit_code = _exit_code(result)
        error = None
    except Exception as exception:
        result = {"status": "ERROR", "error_type": type(exception).__name__, "error": str(exception)}
        exit_code = 2
        error = str(exception)
    if run_id:
        try:
            run_dir, _ = load_run(RUNS_ROOT, run_id)
            context_path = run_dir / "context_manifest.json"
            append_jsonl(run_dir / "command_log.jsonl", {
                "schema_version": "1",
                "run_id": run_id,
                "argv": redact_arguments(["python", "-m", "src.cli", *raw_arguments]),
                "context_sha256": sha256_file(context_path) if context_path.is_file() else None,
                "started_at": started,
                "finished_at": utc_now(),
                "exit_code": exit_code,
                "result_status": result.get("status", "ERROR"),
                "error": error,
            })
        except Exception:
            if arguments.command != "init-run":
                raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
