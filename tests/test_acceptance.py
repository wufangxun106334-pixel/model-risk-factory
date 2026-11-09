from __future__ import annotations

from pathlib import Path

from src.acceptance import SPLIT_ROWS, _command_chain, _export_evidence, evaluate_acceptance
from src.common import append_jsonl, read_json, sha256_file, write_json

RUN_ID = "run-test"
HEX = "a" * 64


def repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    write_json(repo / "config" / "data_config.json", {"seed": 42})
    return repo


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _capability(run: Path, status: str = "PASS") -> None:
    if status == "BLOCKED":
        write_json(run / "provider" / "capability_check.json", {"status": "BLOCKED", "run_id": RUN_ID})
        return
    write_json(run / "provider" / "capability_check.json", {
        "status": status,
        "run_id": RUN_ID,
        "model": "model-id",
        "request_ids": ["req-1", "req-2", "req-3"],
        "request": {"status": "PASS"},
        "tool": {"status": "PASS"},
        "output_parse": {"status": "PASS"},
    })
    if status == "PASS":
        for index, kind in enumerate(("GENERATE", "TOOL_ROUNDTRIP_REQUEST", "TOOL_ROUNDTRIP_FINAL"), start=1):
            append_jsonl(run / "provider" / "request_log.jsonl", {
                "run_id": RUN_ID,
                "request_round": "capability-check",
                "model": "model-id",
                "transport": "HTTP",
                "kind": kind,
                "request_id": f"req-{index}",
                "status": "SUCCEEDED",
            })


def _uci_data(run: Path, repo: Path) -> None:
    raw = repo / "data" / "raw" / "uci.zip"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"raw-uci-bytes")
    raw_sha = sha256_file(raw)
    files = {}
    for name, rows in SPLIT_ROWS.items():
        path = _write(run / "data" / f"{name}.csv", f"client_id,default_flag\n{name},{rows}\n")
        files[f"{name}.csv"] = {"sha256": sha256_file(path), "rows": rows, "default_rate": 0.2212}
    write_json(run / "data" / "data_manifest.json", {
        "schema_version": "1",
        "run_id": RUN_ID,
        "model_id": "MDL_CREDIT_V1",
        "data_kind": "uci",
        "synthetic": False,
        "formal_status": "APPROVED",
        "seed": 42,
        "files": files,
        "config_sha256": sha256_file(repo / "config" / "data_config.json"),
        "split_validation": {
            "valid": True,
            "row_counts": dict(SPLIT_ROWS),
            "total_rows": sum(SPLIT_ROWS.values()),
            "mutually_exclusive": True,
            "default_rates_within_tolerance": True,
        },
        "source": {
            "contains_real_data": True,
            "license": "CC BY 4.0",
            "original_sha256": raw_sha,
            "landing_url": "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients",
        },
    })
    write_json(run / "data" / "uci_approval.json", {
        "run_id": RUN_ID,
        "approved": True,
        "expected_sha256": raw_sha,
        "input_sha256": raw_sha,
        "license": "CC BY 4.0",
    })
    write_json(run / "data" / "download.json", {"run_id": RUN_ID, "sha256": raw_sha, "path": str(raw)})


def _synthetic_data(run: Path) -> None:
    write_json(run / "data" / "data_manifest.json", {
        "run_id": RUN_ID,
        "data_kind": "synthetic",
        "synthetic": True,
        "formal_status": "BLOCKED",
        "split_validation": {"valid": True},
    })


def _reference(run: Path) -> None:
    model = _write(run / "reference" / "model.json", '{"coefficients": {}}\n')
    write_json(run / "reference" / "r_execution.json", {
        "status": "PASS",
        "run_id": RUN_ID,
        "exit_code": 0,
        "network": "none",
        "r_image": "rocker/r-ver:4.4.2",
        "r_script_sha256": HEX,
        "artifacts": [{"path": "reference/model.json", "sha256": sha256_file(model)}],
    })


def _parity_summary(n: int) -> dict:
    return {
        "status": "PASS",
        "run_id": RUN_ID,
        "n": n,
        "valid_probability_pairs": n,
        "id_sets_match": True,
        "id_order_match": True,
        "classification_mismatch_count": 0,
        "behaviour_mismatch_count": 0,
        "execution_error": False,
        "max_abs_diff": 0.0,
    }


def _parity(run: Path) -> None:
    write_json(run / "parity" / "reference_dev" / "parity_summary.json", _parity_summary(6000))
    write_json(run / "parity" / "reference_holdout" / "parity_summary.json", _parity_summary(6000))
    records = []
    for name in ("behavior", "column_reordered", "row_reordered"):
        records.append({"kind": "ROW_BEHAVIOUR", "name": name, "parity_status": "PASS", "parity": _parity_summary(2)})
    for name in ("duplicate_ids", "missing_column", "empty"):
        records.append({"kind": "STRUCTURAL_REJECTION", "name": name, "parity_status": "PASS", "python_exit_code": 2, "r_exit_code": 2})
    write_json(run / "parity" / "reference_fixtures" / "fixture_summary.json", {
        "status": "PASS",
        "run_id": RUN_ID,
        "contains_synthetic_fixtures_only": True,
        "records": records,
    })


def _mutation(run: Path) -> None:
    write_json(run / "mutation" / "mutation_summary.json", {
        "status": "PASS",
        "run_id": RUN_ID,
        "mutation_detected": True,
        "original_unchanged": True,
        "original_model_sha256_before": HEX,
        "original_model_sha256_after": HEX,
        "tests_sha256_before": HEX,
        "tests_sha256_after": HEX,
    })


def base_run(tmp_path: Path, data_kind: str = "synthetic") -> tuple[Path, Path]:
    repo = repository(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    _capability(run, "BLOCKED")
    if data_kind == "uci":
        _uci_data(run, repo)
    else:
        _synthetic_data(run)
    _reference(run)
    _parity(run)
    _mutation(run)
    return repo, run


def statuses(repo: Path, run: Path) -> dict[str, str]:
    return {record["acceptance_id"]: record["status"] for record in evaluate_acceptance(repo, run, RUN_ID)}


def test_synthetic_local_evidence_never_releases_v1(tmp_path):
    repo, run = base_run(tmp_path)
    assert statuses(repo, run) == {
        "V1-01": "BLOCKED",
        "V1-02": "BLOCKED",
        "V1-03": "PASS",
        "V1-04": "PASS",
        "V1-05": "PASS",
        "V1-06": "BLOCKED",
        "V1-07": "BLOCKED",
    }


def test_valid_approved_uci_manifest_passes_data_item(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    assert statuses(repo, run)["V1-02"] == "PASS"


def test_capability_failure_is_reported_as_fail_not_blocked(tmp_path):
    repo, run = base_run(tmp_path)
    _capability(run, "FAIL")
    assert statuses(repo, run)["V1-01"] == "FAIL"


def test_capability_pass_with_missing_gateway_evidence_is_fail(tmp_path):
    repo, run = base_run(tmp_path)
    _capability(run, "PASS")
    report = read_json(run / "provider" / "capability_check.json")
    report["request_ids"] = []
    write_json(run / "provider" / "capability_check.json", report)
    assert statuses(repo, run)["V1-01"] == "FAIL"


def test_missing_uci_approval_record_fails_data_item(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    (run / "data" / "uci_approval.json").unlink()
    assert statuses(repo, run)["V1-02"] == "FAIL"


def test_tampered_split_file_fails_data_item(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    (run / "data" / "dev.csv").write_text("client_id,default_flag\n1,0\n", encoding="utf-8")
    assert statuses(repo, run)["V1-02"] == "FAIL"


def test_stale_data_manifest_from_another_run_fails(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    manifest = read_json(run / "data" / "data_manifest.json")
    manifest["run_id"] = "v1-old-run"
    write_json(run / "data" / "data_manifest.json", manifest)
    assert statuses(repo, run)["V1-02"] == "FAIL"


def test_raw_input_hash_mismatch_fails_data_item(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    download = read_json(run / "data" / "download.json")
    Path(download["path"]).write_bytes(b"replaced-raw-bytes")
    assert statuses(repo, run)["V1-02"] == "FAIL"


def test_missing_reference_holdout_parity_fails_v1_04(tmp_path):
    repo, run = base_run(tmp_path)
    (run / "parity" / "reference_holdout" / "parity_summary.json").unlink()
    assert statuses(repo, run)["V1-04"] == "FAIL"


def test_tampered_fixture_record_fails_v1_04(tmp_path):
    repo, run = base_run(tmp_path)
    path = run / "parity" / "reference_fixtures" / "fixture_summary.json"
    summary = read_json(path)
    summary["records"][0]["parity"]["classification_mismatch_count"] = 1
    write_json(path, summary)
    assert statuses(repo, run)["V1-04"] == "FAIL"


def test_stale_fixture_summary_from_another_run_fails_v1_04(tmp_path):
    repo, run = base_run(tmp_path)
    path = run / "parity" / "reference_fixtures" / "fixture_summary.json"
    summary = read_json(path)
    summary["run_id"] = "v1-old-run"
    write_json(path, summary)
    assert statuses(repo, run)["V1-04"] == "FAIL"


def test_holdout_json_alone_cannot_pass_real_migration(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    _capability(run, "PASS")
    write_json(run / "holdout" / "parity_summary.json", {"status": "PASS"})
    write_json(run / "migration_result.json", {"attempt": 0, "candidate_sha256": "0" * 64, "final_status": "PASS"})
    write_json(run / "candidates" / "attempt_000" / "candidate.json", {"generation_mode": "REAL_API"})
    result = statuses(repo, run)
    assert result["V1-06"] == "FAIL"
    assert result["V1-07"] == "NOT_RUN"


def _command_log(run: Path, entries: list[tuple[list[str], int]], record_run_id: str = RUN_ID) -> None:
    lines = []
    for argv, exit_code in entries:
        lines.append({
            "run_id": record_run_id,
            "argv": ["python", "-m", "src.cli", *argv],
            "exit_code": exit_code,
        })
    _write(run / "command_log.jsonl", "\n".join(__import__("json").dumps(line) for line in lines) + "\n")


def test_command_chain_requires_same_run_ordered_successes(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    good = [
        ["check-provider", "--run-id", RUN_ID],
        ["prepare", "--run-id", RUN_ID],
        ["baseline", "--run-id", RUN_ID],
        ["reference-parity", "--run-id", RUN_ID],
        ["fixture-parity", "--run-id", RUN_ID],
        ["mutation-check", "--run-id", RUN_ID],
        ["extract-inventory", "--run-id", RUN_ID],
        ["approve", "--run-id", RUN_ID, "--gate", "Gate_A"],
        ["generate-candidate", "--run-id", RUN_ID],
        ["approve", "--run-id", RUN_ID, "--gate", "Gate_B"],
        ["run-dev", "--run-id", RUN_ID],
        ["candidate-fixtures", "--run-id", RUN_ID],
        ["freeze", "--run-id", RUN_ID],
        ["accept", "--run-id", RUN_ID],
        ["export", "--run-id", RUN_ID],
    ]
    _command_log(run, [(item, 0) for item in good])
    assert _command_chain(run, RUN_ID) == []

    _command_log(run, [(item, 0) for item in good if item[0] != "freeze"])
    assert "freeze" in " ".join(_command_chain(run, RUN_ID))

    _command_log(run, [(item, 1 if item[0] == "accept" else 0) for item in good])
    assert "accept" in " ".join(_command_chain(run, RUN_ID))

    swapped = [item for item in good if item[0] not in {"approve"}] + [["approve", "--run-id", RUN_ID, "--gate", "Gate_A"]]
    _command_log(run, [(item, 0) for item in swapped])
    assert _command_chain(run, RUN_ID)

    _command_log(run, [(item, 0) for item in good], record_run_id="v1-other-run")
    assert "no record" in " ".join(_command_chain(run, RUN_ID))


def _manifest_and_export(run: Path, delivery: Path) -> None:
    from src import evidence

    files = []
    for relative in ("provider/capability_check.json", "data/data_manifest.json"):
        files.append({"path": relative, "sha256": sha256_file(run / relative), "bytes": (run / relative).stat().st_size})
    write_json(run / "evidence_manifest.json", {"schema_version": "1", "run_id": RUN_ID, "file_count": len(files), "files": files})
    delivery.mkdir(parents=True, exist_ok=True)
    archive = delivery / f"{RUN_ID}_evidence.zip"
    archive.write_bytes(b"zip-bytes")
    write_json(run / "export_verified.json", {
        "run_id": RUN_ID,
        "verified": True,
        "archive": str(archive),
        "archive_sha256": evidence._archive_digest(archive),
        "manifest_sha256": sha256_file(run / "evidence_manifest.json"),
        "file_count": len(files),
    })


def test_export_evidence_rejects_tampering_and_stale_manifest(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    _manifest_and_export(run, tmp_path / "delivery")
    assert _export_evidence(run, RUN_ID) == []

    (run / "data" / "data_manifest.json").write_text("{}\n", encoding="utf-8")
    assert "hash mismatch" in " ".join(_export_evidence(run, RUN_ID))

    _uci_data(run, repo)
    _manifest_and_export(run, tmp_path / "delivery")
    record = read_json(run / "export_verified.json")
    record["manifest_sha256"] = HEX
    write_json(run / "export_verified.json", record)
    assert "stale" in " ".join(_export_evidence(run, RUN_ID))

    _manifest_and_export(run, tmp_path / "delivery")
    Path(read_json(run / "export_verified.json")["archive"]).write_bytes(b"replaced")
    assert "archive hash mismatch" in " ".join(_export_evidence(run, RUN_ID))


def test_export_manifest_cannot_smuggle_line_level_files_or_duplicates(tmp_path):
    repo, run = base_run(tmp_path, "uci")
    _manifest_and_export(run, tmp_path / "delivery")
    assert _export_evidence(run, RUN_ID) == []

    manifest = read_json(run / "evidence_manifest.json")
    row_file = run / "data" / "holdout.csv"
    manifest["files"].append({"path": "data/holdout.csv", "sha256": sha256_file(row_file), "bytes": row_file.stat().st_size})
    manifest["file_count"] = len(manifest["files"])
    write_json(run / "evidence_manifest.json", manifest)
    record = read_json(run / "export_verified.json")
    record["manifest_sha256"] = sha256_file(run / "evidence_manifest.json")
    record["file_count"] = manifest["file_count"]
    write_json(run / "export_verified.json", record)
    assert "whitelist" in " ".join(_export_evidence(run, RUN_ID))

    manifest["files"].append(dict(manifest["files"][0]))
    manifest["file_count"] = len(manifest["files"])
    write_json(run / "evidence_manifest.json", manifest)
    record["manifest_sha256"] = sha256_file(run / "evidence_manifest.json")
    record["file_count"] = manifest["file_count"]
    write_json(run / "export_verified.json", record)
    assert "duplicate" in " ".join(_export_evidence(run, RUN_ID))
