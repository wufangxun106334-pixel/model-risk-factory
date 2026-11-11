from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from src.common import current_git_commit, read_json, read_jsonl, sha256_file, utc_now, write_json
from src.contracts import AcceptanceRecord
from src.evidence import is_allowed
from src.review import current_decision

EXPECTED = {
    "V1-01": "Real configured gateway request, tool roundtrip and output parsing pass.",
    "V1-02": "Approved UCI raw SHA-256 and exact 15000/6000/1199/3000 stratified mutually exclusive splits pass.",
    "V1-03": "MDL_CREDIT_V1 R glm baseline, preprocessing and predictions are reproducible.",
    "V1-04": "Trusted Python reference parity meets probability, classification and behavioural contracts.",
    "V1-05": "An isolated coefficient mutation is detected without changing baseline or test hashes.",
    "V1-06": "Real API inventory/candidate migration passes human Gate A/B, Docker dev, freeze and Holdout parity.",
    "V1-07": "The same run_id reproduces the evidence chain and exports verifiable actual command evidence.",
}

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SPLIT_ROWS = {"train": 15000, "dev": 6000, "holdout": 1199, "shift_pool": 3000}
TOTAL_ROWS = sum(SPLIT_ROWS.values())
FIXTURE_NAMES = (
    "behavior",
    "column_reordered",
    "row_reordered",
    "duplicate_ids",
    "missing_column",
    "empty",
)
ROW_BEHAVIOUR_FIXTURES = {"behavior", "column_reordered", "row_reordered"}
COMMAND_CHAIN = (
    ("check-provider", None),
    ("prepare", None),
    ("baseline", None),
    ("reference-parity", None),
    ("fixture-parity", None),
    ("mutation-check", None),
    ("extract-inventory", None),
    ("approve", "Gate_A"),
    ("generate-candidate", None),
    ("approve", "Gate_B"),
    ("run-dev", None),
    ("candidate-fixtures", None),
    ("freeze", None),
    ("accept", None),
)
# `export` is proven by export_verified.json (written only by a verified export) because the
# CLI appends its own command_log entry after the command returns.
EVIDENCE_MANIFEST = "evidence_manifest.json"
EXPORT_RECORD = "export_verified.json"
EXPORT_EXCLUDED = {EVIDENCE_MANIFEST, EXPORT_RECORD, "acceptance.json"}


def _hashlike(value: object) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _status(path: Path) -> str | None:
    return read_json(path).get("status") if path.is_file() else None


def _hash_matches(path: Path, expected: object) -> bool:
    return path.is_file() and _hashlike(expected) and sha256_file(path) == expected


def _capability(run_dir: Path, run_id: str) -> tuple[str, str]:
    path = run_dir / "provider" / "capability_check.json"
    if not path.is_file():
        return "NOT_RUN", "capability_check=NOT_RUN"
    report = read_json(path)
    status = report.get("status")
    if status == "BLOCKED":
        return "BLOCKED", "capability_check=BLOCKED"
    if status != "PASS":
        return ("FAIL" if status == "FAIL" else "NOT_RUN"), f"capability_check={status}"
    request_ids = report.get("request_ids")
    request_kinds = ("GENERATE", "TOOL_ROUNDTRIP_REQUEST", "TOOL_ROUNDTRIP_FINAL")
    requests = {
        (event.get("kind"), event.get("request_id"))
        for event in read_jsonl(run_dir / "provider" / "request_log.jsonl")
        if event.get("run_id") == run_id
        and event.get("request_round") == "capability-check"
        and event.get("model") == report.get("model")
        and event.get("transport") == "HTTP"
        and event.get("status") == "SUCCEEDED"
    }
    checks = {
        "run_id": report.get("run_id") == run_id,
        "request_log": isinstance(request_ids, list)
        and len(request_ids) == len(request_kinds)
        and all(isinstance(request_id, str) and request_id for request_id in request_ids)
        and all(request in requests for request in zip(request_kinds, request_ids)),
        "request": report.get("request", {}).get("status") == "PASS",
        "tool": report.get("tool", {}).get("status") == "PASS",
        "output_parse": report.get("output_parse", {}).get("status") == "PASS",
        "model": bool(report.get("model")),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        return "FAIL", "capability_check=PASS but inconsistent: " + ",".join(failed)
    return "PASS", f"capability_check=PASS; requests={len(report['request_ids'])}"


def _data(run_dir: Path, run_id: str, repository: Path) -> tuple[str, str]:
    path = run_dir / "data" / "data_manifest.json"
    if not path.is_file():
        return "NOT_RUN", "data_manifest=NOT_RUN"
    manifest = read_json(path)
    if manifest.get("synthetic") is True or manifest.get("data_kind") != "uci":
        return "BLOCKED", f"data_kind={manifest.get('data_kind', 'NOT_RUN')}; formal_status={manifest.get('formal_status', 'NOT_RUN')}; synthetic data never satisfies V1-02"
    problems: list[str] = []
    if manifest.get("run_id") != run_id:
        problems.append("manifest run_id mismatch")
    if manifest.get("formal_status") != "APPROVED":
        problems.append(f"formal_status={manifest.get('formal_status')}")
    source = manifest.get("source", {})
    original = source.get("original_sha256")
    if source.get("contains_real_data") is not True:
        problems.append("source.contains_real_data is not true")
    if not source.get("license"):
        problems.append("source license missing")
    if not _hashlike(original):
        problems.append("source original_sha256 invalid")
    config_path = repository / "config" / "data_config.json"
    if not config_path.is_file() or manifest.get("config_sha256") != sha256_file(config_path):
        problems.append("data config hash mismatch")
    approval_path = run_dir / "data" / "uci_approval.json"
    if not approval_path.is_file():
        problems.append("uci_approval missing")
    else:
        approval = read_json(approval_path)
        if approval.get("run_id") != run_id:
            problems.append("uci_approval run_id mismatch")
        if approval.get("approved") is not True:
            problems.append("uci_approval not approved")
        if not _hashlike(approval.get("expected_sha256")):
            problems.append("uci_approval expected_sha256 invalid")
        if approval.get("input_sha256") != original or approval.get("expected_sha256") != original:
            problems.append("uci_approval hash does not match raw input hash")
        if not approval.get("license"):
            problems.append("uci_approval license missing")
    download_path = run_dir / "data" / "download.json"
    if not download_path.is_file():
        problems.append("download record missing")
    else:
        download = read_json(download_path)
        if download.get("run_id") != run_id:
            problems.append("download record run_id mismatch")
        if download.get("sha256") != original:
            problems.append("download sha256 does not match raw input hash")
        raw_path = Path(download.get("path", ""))
        if not raw_path.is_absolute():
            raw_path = repository / raw_path
        if not raw_path.is_file():
            problems.append("raw input file missing")
        elif sha256_file(raw_path) != original:
            problems.append("raw input file hash mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict):
        problems.append("split files missing")
    else:
        for name, rows in SPLIT_ROWS.items():
            entry = files.get(f"{name}.csv")
            if not isinstance(entry, dict):
                problems.append(f"{name}.csv entry missing")
                continue
            if entry.get("rows") != rows:
                problems.append(f"{name}.csv rows={entry.get('rows')}")
            split_path = run_dir / "data" / f"{name}.csv"
            if not _hash_matches(split_path, entry.get("sha256")):
                problems.append(f"{name}.csv hash mismatch")
    validation = manifest.get("split_validation", {})
    if validation.get("valid") is not True:
        problems.append("split_validation invalid")
    if validation.get("row_counts") != SPLIT_ROWS:
        problems.append("split row_counts mismatch")
    if validation.get("total_rows") != TOTAL_ROWS:
        problems.append("split total_rows mismatch")
    if validation.get("mutually_exclusive") is not True:
        problems.append("splits are not mutually exclusive")
    if validation.get("default_rates_within_tolerance") is not True:
        problems.append("default rate tolerance not met")
    if problems:
        return "FAIL", "uci data evidence invalid: " + "; ".join(problems[:6])
    return "PASS", f"uci data sha256={(original or '')[:12]}…; splits={SPLIT_ROWS}; split_valid=True"


def _r_baseline(run_dir: Path, run_id: str) -> tuple[str, str]:
    path = run_dir / "reference" / "r_execution.json"
    if not path.is_file():
        return "NOT_RUN", "r_execution=NOT_RUN"
    execution = read_json(path)
    problems: list[str] = []
    if execution.get("status") != "PASS":
        problems.append(f"status={execution.get('status')}")
    if execution.get("run_id") != run_id:
        problems.append("run_id mismatch")
    if execution.get("exit_code") != 0:
        problems.append("exit_code is not 0")
    if execution.get("network") != "none":
        problems.append("R container did not run with network none")
    if not _hashlike(execution.get("r_script_sha256")):
        problems.append("r_script_sha256 invalid")
    artifacts = execution.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        problems.append("artifact list missing")
    else:
        for artifact in artifacts:
            relative = artifact.get("path", "")
            if not _hash_matches(run_dir / relative, artifact.get("sha256")):
                problems.append(f"artifact hash mismatch: {relative}")
    if not (run_dir / "reference" / "model.json").is_file():
        problems.append("model.json missing")
    if problems:
        return "FAIL", "r baseline invalid: " + "; ".join(problems[:6])
    return "PASS", f"r_execution=PASS; image={execution.get('r_image')}"


def _parity_problems(summary: dict, run_id: str, row_behaviour: bool) -> list[str]:
    problems: list[str] = []
    if summary.get("status") != "PASS":
        problems.append(f"status={summary.get('status')}")
    if summary.get("run_id") != run_id:
        problems.append("run_id mismatch")
    if summary.get("execution_error") is not False:
        problems.append("execution_error is not false")
    if summary.get("id_sets_match") is not True:
        problems.append("id sets do not match")
    if summary.get("classification_mismatch_count") != 0:
        problems.append("classification mismatch")
    if summary.get("behaviour_mismatch_count") != 0:
        problems.append("behaviour mismatch")
    if row_behaviour or summary.get("n", 0) > 0:
        if not isinstance(summary.get("valid_probability_pairs"), int) or summary.get("valid_probability_pairs", 0) <= 0:
            problems.append("no valid probability pairs")
    return problems


def _reference_parity(run_dir: Path, run_id: str) -> tuple[str, str]:
    dev_path = run_dir / "parity" / "reference_dev" / "parity_summary.json"
    holdout_path = run_dir / "parity" / "reference_holdout" / "parity_summary.json"
    fixture_path = run_dir / "parity" / "reference_fixtures" / "fixture_summary.json"
    if not any(path.is_file() for path in (dev_path, holdout_path, fixture_path)):
        return "NOT_RUN", "reference parity=NOT_RUN"
    problems: list[str] = []
    for label, path in (("reference_dev", dev_path), ("reference_holdout", holdout_path)):
        if not path.is_file():
            problems.append(f"{label} summary missing")
            continue
        problems.extend(f"{label}: {item}" for item in _parity_problems(read_json(path), run_id, True))
    if not fixture_path.is_file():
        problems.append("reference_fixtures summary missing")
    else:
        fixtures = read_json(fixture_path)
        if fixtures.get("status") != "PASS":
            problems.append(f"fixtures status={fixtures.get('status')}")
        if fixtures.get("run_id") != run_id:
            problems.append("fixtures run_id mismatch")
        if fixtures.get("contains_synthetic_fixtures_only") is not True:
            problems.append("fixtures are not marked synthetic-only")
        records = fixtures.get("records")
        if not isinstance(records, list):
            problems.append("fixture records missing")
        else:
            names = [record.get("name") for record in records if isinstance(record, dict)]
            missing = [name for name in FIXTURE_NAMES if name not in names]
            if missing:
                problems.append("fixture cases missing: " + ",".join(missing))
            for record in records:
                if not isinstance(record, dict):
                    problems.append("invalid fixture record")
                    continue
                if record.get("parity_status") != "PASS":
                    problems.append(f"fixture {record.get('name')} parity_status={record.get('parity_status')}")
                if record.get("kind") == "ROW_BEHAVIOUR":
                    if record.get("name") not in ROW_BEHAVIOUR_FIXTURES:
                        problems.append(f"unexpected row fixture {record.get('name')}")
                    if not isinstance(record.get("parity"), dict):
                        problems.append(f"fixture {record.get('name')} parity payload missing")
                        continue
                    problems.extend(f"fixture {record.get('name')}: {item}" for item in _parity_problems(record["parity"], run_id, True))
                elif record.get("kind") == "STRUCTURAL_REJECTION":
                    if record.get("python_exit_code") != 2 or record.get("r_exit_code") != 2:
                        problems.append(f"fixture {record.get('name')} rejection exit codes")
                else:
                    problems.append(f"fixture {record.get('name')} unknown kind")
    if problems:
        return "FAIL", "reference parity invalid: " + "; ".join(problems[:6])
    return "PASS", "reference_dev=PASS; reference_holdout=PASS; fixtures=PASS"


def _mutation(run_dir: Path, run_id: str) -> tuple[str, str]:
    path = run_dir / "mutation" / "mutation_summary.json"
    if not path.is_file():
        return "NOT_RUN", "mutation=NOT_RUN"
    summary = read_json(path)
    problems: list[str] = []
    if summary.get("status") != "PASS":
        problems.append(f"status={summary.get('status')}")
    if summary.get("run_id") != run_id:
        problems.append("run_id mismatch")
    if summary.get("mutation_detected") is not True:
        problems.append("mutation not detected")
    if summary.get("original_unchanged") is not True:
        problems.append("original model changed")
    if not _hashlike(summary.get("original_model_sha256_before")):
        problems.append("original hash invalid")
    if summary.get("original_model_sha256_before") != summary.get("original_model_sha256_after"):
        problems.append("original hash changed")
    if summary.get("tests_sha256_before") != summary.get("tests_sha256_after"):
        problems.append("test hash changed")
    if problems:
        return "FAIL", "mutation evidence invalid: " + "; ".join(problems[:4])
    return "PASS", "mutation_detected=True; original_unchanged=True"


def _valid_execution(path: Path) -> bool:
    if not path.is_file():
        return False
    execution = read_json(path)
    docker = execution.get("docker", {})
    return (
        execution.get("status") == "PASS"
        and execution.get("exit_code") == 0
        and docker.get("network") == "none"
        and docker.get("read_only") is True
        and docker.get("user") not in {None, "0", "0:0", "root"}
        and docker.get("cap_drop") == ["ALL"]
        and docker.get("security_opt") == ["no-new-privileges"]
    )


def _trusted_migration_chain(run_dir: Path, run_id: str, candidate: dict) -> bool:
    try:
        attempt = candidate["attempt"]
        directory = run_dir / "candidates" / f"attempt_{attempt:03d}"
        metadata = read_json(directory / "candidate.json")
        source = directory / "credit_v1.py"
        digest = metadata["candidate_sha256"]
        if metadata.get("run_id") != run_id:
            return False
        if metadata.get("generation_mode") != "REAL_API" or sha256_file(source) != digest or candidate.get("candidate_sha256") != digest:
            return False
        if metadata.get("context_sha256") != sha256_file(run_dir / "context_manifest.json"):
            return False
        if current_decision(run_dir, run_id, "Gate_A", run_dir / "model_inventory.json") != "APPROVED":
            return False
        if current_decision(run_dir, run_id, "Gate_B", source) != "APPROVED":
            return False
        frozen = read_json(run_dir / "frozen" / "frozen.json")
        if frozen.get("candidate_sha256") != digest or sha256_file(run_dir / "frozen" / "credit_v1.py") != digest:
            return False
        if frozen.get("run_id") != run_id:
            return False
        if _status(run_dir / "dev" / f"attempt_{attempt:03d}" / "parity_summary.json") != "PASS":
            return False
        fixtures = read_json(run_dir / "dev" / f"attempt_{attempt:03d}" / "fixture_summary.json")
        if fixtures.get("run_id") != run_id or fixtures.get("candidate_sha256") != digest or fixtures.get("status") != "PASS":
            return False
        if not _valid_execution(run_dir / "dev" / f"attempt_{attempt:03d}" / "execution.json") or not _valid_execution(run_dir / "holdout" / "execution.json"):
            return False
        evidence = metadata.get("api_evidence", {})
        if not evidence.get("generation_request_id") or not evidence.get("generation_request_event_id") or not evidence.get("capability_check_sha256"):
            return False
        audit = read_jsonl(run_dir / "agent_audit_log.jsonl")
        inventory_request = next(
            ((event["request_id"], event["request_event_id"]) for event in audit
             if event.get("event") == "INVENTORY_VALIDATED" and event.get("stage") == "inventory"
             and event.get("request_id") and event.get("request_event_id")),
            None,
        )
        if not inventory_request:
            return False
        if not any(event.get("event") == "CANDIDATE_SAVED" and event.get("candidate_sha256") == digest and event.get("request_id") for event in audit):
            return False
        if not any(event.get("event") == "MODEL_RESPONSE" and event.get("stage") == f"candidate-{attempt}" and "submit_candidate" in event.get("tool_names", []) and event.get("request_id") for event in audit):
            return False
        requests = {
            (event.get("request_round"), event.get("request_id"), event.get("event_id"))
            for event in read_jsonl(run_dir / "provider" / "request_log.jsonl")
            if event.get("run_id") == run_id
            and event.get("status") == "SUCCEEDED"
            and event.get("transport") == "HTTP"
        }
        candidate_request = (f"candidate-{attempt}", evidence["generation_request_id"], evidence["generation_request_event_id"])
        return ("inventory", *inventory_request) in requests and candidate_request in requests
    except (OSError, KeyError, TypeError, ValueError):
        return False


def _argv_option(argv: list[str], name: str) -> str | None:
    for index, token in enumerate(argv):
        if token == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _expected_attempt(run_dir: Path) -> int | None:
    for relative in ("frozen/frozen.json", "migration_result.json"):
        path = run_dir / relative
        if path.is_file():
            attempt = read_json(path).get("attempt")
            if isinstance(attempt, int) and not isinstance(attempt, bool):
                return attempt
    return None


def _frozen_candidate_sha256(run_dir: Path) -> str | None:
    path = run_dir / "frozen" / "frozen.json"
    if not path.is_file():
        return None
    value = read_json(path).get("candidate_sha256")
    return value if isinstance(value, str) else None


def _chain_context(run_dir: Path) -> tuple[int | None, str | None, str | None]:
    """Expected attempt, context-manifest hash and frozen candidate hash every chain record binds to."""

    context_path = run_dir / "context_manifest.json"
    context_sha256 = sha256_file(context_path) if context_path.is_file() else None
    return _expected_attempt(run_dir), context_sha256, _frozen_candidate_sha256(run_dir)


def _cli_command(event: dict) -> str | None:
    """The ``src.cli`` subcommand a command-log event ran, or None for anything else."""

    argv = event.get("argv") or []
    return argv[3] if len(argv) > 3 and argv[:3] == ["python", "-m", "src.cli"] else None


ATTEMPT_SCOPED = {"generate-candidate", "run-dev", "candidate-fixtures", "freeze"}


def _chain_binding_problems(
    event: dict,
    label: str,
    command: str,
    run_id: str,
    expected_attempt: int | None,
    context_sha256: str | None,
    frozen_sha256: str | None,
) -> list[str]:
    """Check that a successful chain step belongs to this run, attempt and context."""

    problems: list[str] = []
    argv = event.get("argv") or []
    recorded_run_id = _argv_option(argv, "--run-id")
    if recorded_run_id is not None and recorded_run_id != run_id:
        problems.append(f"{label} argv --run-id={recorded_run_id} does not match {run_id}")
    attempt_scoped = command in ATTEMPT_SCOPED or (command == "approve" and _argv_option(argv, "--gate") == "Gate_B")
    if expected_attempt is not None and attempt_scoped:
        recorded_attempt = _argv_option(argv, "--attempt")
        if recorded_attempt is None:
            problems.append(f"{label} has no --attempt but the run froze attempt {expected_attempt}")
        elif not recorded_attempt.isdigit() or int(recorded_attempt) != expected_attempt:
            problems.append(
                f"{label} ran on attempt {recorded_attempt}, expected the frozen attempt {expected_attempt}"
            )
    if command == "approve" and _argv_option(argv, "--gate") == "Gate_B":
        recorded_sha256 = _argv_option(argv, "--sha256")
        if frozen_sha256 is not None and recorded_sha256 != frozen_sha256:
            problems.append(f"{label} approved {recorded_sha256}, expected the frozen candidate {frozen_sha256}")
    if context_sha256 is not None:
        recorded_context = event.get("context_sha256")
        if recorded_context is not None and recorded_context != context_sha256:
            problems.append(f"{label} ran under a stale context")
    return problems


def _command_chain(run_dir: Path, run_id: str) -> list[str]:
    path = run_dir / "command_log.jsonl"
    if not path.is_file():
        return ["command_log missing"]
    events = [event for event in read_jsonl(path) if event.get("run_id") == run_id]
    if not events:
        return ["command_log has no record for this run"]
    expected_attempt, context_sha256, frozen_sha256 = _chain_context(run_dir)
    if expected_attempt is not None and context_sha256 is None:
        return ["context_manifest missing for a run that produced a candidate"]
    problems: list[str] = []
    position = 0
    for command, gate in COMMAND_CHAIN:
        label = f"{command} {gate}" if gate else command
        # Failures inside a run are legal retries as long as a later success of the
        # same step follows: the failed records stay in the log as evidence.
        failures: list[object] = []
        success: dict | None = None
        while position < len(events):
            event = events[position]
            position += 1
            argv = event.get("argv") or []
            if _cli_command(event) != command:
                continue
            if command == "approve" and _argv_option(argv, "--gate") != gate:
                continue
            if event.get("exit_code") != 0:
                failures.append(event.get("exit_code"))
                continue
            success = event
            break
        if success is None:
            if failures:
                problems.append(f"{label} has no successful attempt (failed exit codes: {failures})")
            else:
                problems.append(f"{label} record missing or out of order")
            continue
        problems.extend(
            _chain_binding_problems(success, label, command, run_id, expected_attempt, context_sha256, frozen_sha256)
        )
    return problems


def _export_evidence(run_dir: Path, run_id: str) -> list[str]:
    manifest_path = run_dir / EVIDENCE_MANIFEST
    if not manifest_path.is_file():
        return ["evidence_manifest missing"]
    manifest = read_json(manifest_path)
    problems: list[str] = []
    if manifest.get("run_id") != run_id:
        problems.append("evidence_manifest run_id mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return ["evidence_manifest has no files"]
    if manifest.get("file_count") != len(files):
        problems.append("evidence_manifest file_count mismatch")
    seen: set[str] = set()
    for record in files:
        relative = record.get("path", "")
        if relative in EXPORT_EXCLUDED or not relative:
            problems.append(f"forbidden manifest entry: {relative}")
            continue
        if relative in seen:
            problems.append(f"duplicate manifest entry: {relative}")
            continue
        seen.add(relative)
        if not is_allowed(PurePosixPath(relative)):
            problems.append(f"manifest entry outside the evidence whitelist: {relative}")
            continue
        path = run_dir / relative
        if not _hash_matches(path, record.get("sha256")):
            problems.append(f"evidence hash mismatch: {relative}")
    record_path = run_dir / EXPORT_RECORD
    if not record_path.is_file():
        problems.append("export_verified missing")
        return problems
    record = read_json(record_path)
    if record.get("run_id") != run_id:
        problems.append("export_verified run_id mismatch")
    if record.get("verified") is not True:
        problems.append("export was not verified")
    if record.get("manifest_sha256") != sha256_file(manifest_path):
        problems.append("export_verified manifest hash is stale")
    if record.get("file_count") != len(files):
        problems.append("export_verified file_count mismatch")
    archive = Path(record.get("archive", ""))
    if not archive.is_absolute():
        archive = run_dir / archive
    if not _hash_matches(archive, record.get("archive_sha256")):
        problems.append("export archive hash mismatch")
    return problems


def evaluate_acceptance(repository: Path, run_dir: Path, run_id: str) -> list[dict]:
    v1_01, actual_01 = _capability(run_dir, run_id)
    v1_02, actual_02 = _data(run_dir, run_id, repository)
    v1_03, actual_03 = _r_baseline(run_dir, run_id)
    v1_04, actual_04 = _reference_parity(run_dir, run_id)
    v1_05, actual_05 = _mutation(run_dir, run_id)

    candidate = read_json(run_dir / "migration_result.json") if (run_dir / "migration_result.json").is_file() else {}
    holdout_status = _status(run_dir / "holdout" / "parity_summary.json")
    real_api = False
    if candidate:
        attempt_dir = run_dir / "candidates" / f"attempt_{candidate['attempt']:03d}" / "candidate.json"
        real_api = attempt_dir.is_file() and read_json(attempt_dir).get("generation_mode") == "REAL_API"
    trusted_chain = bool(candidate) and _trusted_migration_chain(run_dir, run_id, candidate)
    if holdout_status == "PASS" and real_api and candidate.get("final_status") == "PASS" and trusted_chain:
        v1_06 = "PASS"
    elif holdout_status == "FAIL" or candidate.get("final_status") == "FAIL" or (holdout_status == "PASS" and not trusted_chain):
        v1_06 = "FAIL"
    elif v1_01 == "BLOCKED" or v1_02 == "BLOCKED":
        v1_06 = "BLOCKED"
    else:
        v1_06 = "NOT_RUN"
    actual_06 = f"holdout_parity={holdout_status or 'NOT_RUN'}; real_api_candidate={real_api}; trusted_chain={trusted_chain}; migration={candidate.get('final_status', 'NOT_RUN')}"

    export_problems = _export_evidence(run_dir, run_id)
    chain_problems = _command_chain(run_dir, run_id)
    reproduction_problems = [*chain_problems, *export_problems]
    if not reproduction_problems:
        v1_07 = "PASS"
    elif v1_06 == "PASS":
        v1_07 = "FAIL"
    elif v1_01 == "BLOCKED" or v1_02 == "BLOCKED" or v1_06 == "BLOCKED":
        v1_07 = "BLOCKED"
    elif export_problems and (run_dir / EVIDENCE_MANIFEST).is_file():
        v1_07 = "FAIL"
    else:
        v1_07 = "NOT_RUN"
    actual_07 = "reproduction chain verified" if v1_07 == "PASS" else "blocking issues: " + "; ".join(reproduction_problems[:6])

    statuses = [v1_01, v1_02, v1_03, v1_04, v1_05, v1_06, v1_07]
    evidence = [
        run_dir / "provider" / "capability_check.json",
        run_dir / "data" / "data_manifest.json",
        run_dir / "reference" / "r_execution.json",
        run_dir / "parity" / "reference_dev" / "parity_summary.json",
        run_dir / "mutation" / "mutation_summary.json",
        run_dir / "holdout" / "parity_summary.json",
        run_dir / EVIDENCE_MANIFEST,
    ]
    actual = [actual_01, actual_02, actual_03, actual_04, actual_05, actual_06, actual_07]
    timestamp = utc_now()
    commit = current_git_commit(repository)
    records = []
    for index, (acceptance_id, status) in enumerate(zip(EXPECTED, statuses)):
        evidence_path = evidence[index]
        relative = evidence_path.relative_to(run_dir).as_posix() if evidence_path.is_relative_to(run_dir) else str(evidence_path)
        record = AcceptanceRecord(
            acceptance_id=acceptance_id,
            expected=EXPECTED[acceptance_id],
            actual=actual[index],
            status=status,
            evidence_path=relative,
            reviewer="automated-cli-check",
            timestamp=timestamp,
            commit_sha=commit,
        )
        records.append(record.model_dump())
    return records


def write_acceptance(repository: Path, run_dir: Path, run_id: str) -> dict:
    from src.acceptance_v2 import evaluate_v2_acceptance

    records = evaluate_acceptance(repository, run_dir, run_id)
    v2_records = evaluate_v2_acceptance(repository, run_dir, run_id)
    v1_approved = all(item["status"] == "PASS" for item in records)
    v2_approved = all(item["status"] == "PASS" for item in v2_records)
    payload = {
        "schema_version": "1",
        "run_id": run_id,
        "version": "v2",
        "v1_release_approved": v1_approved,
        "v2_release_approved": v2_approved,
        "release_approved": v1_approved and v2_approved,
        "records": [*records, *v2_records],
    }
    write_json(run_dir / "acceptance.json", payload)
    return payload
