import json
import zipfile
from pathlib import Path

import pytest

from src import environment, evidence
from src.common import sha256_file


def make_run(tmp_path: Path):
    run_dir = tmp_path / "runs" / "run-test"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        '{"run_id": "run-test"}\n', encoding="utf-8"
    )
    return run_dir, tmp_path / "delivery"


def disable_metadata_collection(monkeypatch, calls=None):
    def capture(run_dir):
        if calls is not None:
            calls.append("capture")

    monkeypatch.setattr(environment, "capture_environment", capture)


def test_export_rejects_symlink_without_reading_host_placeholder(
    tmp_path, monkeypatch
):
    run_dir, delivery_dir = make_run(tmp_path)
    secret = tmp_path / "host_secret_placeholder.txt"
    secret.write_text("HOST_SECRET_PLACEHOLDER\n", encoding="utf-8")
    output = run_dir / "output"
    output.mkdir()
    link = output / "leak.bin"
    link.symlink_to(secret)
    calls = []
    disable_metadata_collection(monkeypatch, calls)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path in {link, secret}:
            raise AssertionError("export attempted to read a symlink target")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    with pytest.raises(ValueError, match="symbolic link"):
        evidence.export_evidence(run_dir, "run-test", delivery_dir)

    assert calls == []
    assert not (delivery_dir / "run-test_evidence.zip").exists()


def test_export_rejects_directory_symlink(tmp_path, monkeypatch):
    run_dir, delivery_dir = make_run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "host_secret_placeholder.txt").write_text(
        "HOST_SECRET_PLACEHOLDER\n", encoding="utf-8"
    )
    (run_dir / "linked-directory").symlink_to(outside, target_is_directory=True)
    disable_metadata_collection(monkeypatch)

    with pytest.raises(ValueError, match="symbolic link"):
        evidence.export_evidence(run_dir, "run-test", delivery_dir)

    assert not (delivery_dir / "run-test_evidence.zip").exists()


def test_export_rejects_fifo_without_opening_it(tmp_path, monkeypatch):
    import os

    run_dir, delivery_dir = make_run(tmp_path)
    os.mkfifo(run_dir / "blocking-fifo")
    disable_metadata_collection(monkeypatch)

    with pytest.raises(ValueError, match="unsupported file type"):
        evidence.export_evidence(run_dir, "run-test", delivery_dir)

    assert not (delivery_dir / "run-test_evidence.zip").exists()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_export_whitelists_summaries_and_keeps_line_level_evidence_local(tmp_path, monkeypatch):
    run_dir, delivery_dir = make_run(tmp_path)
    allowed = {
        "agent_audit_log.jsonl",
        "command_log_snapshot.jsonl",
        "context_manifest.json",
        "cli_output/acceptance.json",
        "data/data_manifest.json",
        "data/data_dictionary.json",
        "data/SOURCE.md",
        "data/uci_approval.json",
        "dev/attempt_000/execution.json",
        "dev/attempt_000/parity_summary.json",
        "frozen/frozen.json",
        "holdout/execution.json",
        "holdout/parity_summary.json",
        "model_inventory.json",
        "mutation/mutation_summary.json",
        "parity/reference_dev/parity_summary.json",
        "parity/reference_fixtures/fixture_summary.json",
        "parity/reference_holdout/parity_summary.json",
        "provider/capability_check.json",
        "provider/request_log.jsonl",
        "reference/model.json",
        "reference/r_execution.json",
        "review_log.json",
        "run_manifest.json",
        "runner_integration/handwritten_reference_fixture/execution.json",
        "runner_integration/handwritten_reference_fixture/integration_summary.json",
        "runner_integration/handwritten_reference_fixture/parity_summary.json",
    }
    local_only = {
        "data/train.csv",
        "data/dev.csv",
        "data/holdout.csv",
        "data/shift_pool.csv",
        "data/fixtures/behavior.csv",
        "data/raw/default_of_credit_card_clients.zip",
        "reference/train_predictions.csv",
        "reference/dev_predictions.csv",
        "reference/holdout_predictions.csv",
        "reference/r_stdout.txt",
        "reference/r_stderr.txt",
        "parity/reference_dev/python_predictions.csv",
        "parity/reference_dev/parity_diff.csv",
        "parity/reference_fixtures/behavior/parity_diff.csv",
        "dev/attempt_000/python_predictions.csv",
        "dev/attempt_000/stdout.txt",
        "holdout/parity_diff.csv",
        "mutation/parity_diff.csv",
        "mutation/mutant_predictions.csv",
        "mutation/mutant_model.json",
        "candidates/attempt_000/credit_v1.py",
        "candidates/attempt_000/candidate.diff",
        "frozen/credit_v1.py",
        "runner_integration/handwritten_reference_fixture/output/predictions.csv",
        "runner_integration/handwritten_reference_fixture/stdout.txt",
        "runner_integration/handwritten_reference_fixture/parity_diff.csv",
        "notes.txt",
        "debug.log",
    }
    for relative in allowed:
        _write(run_dir / relative, json.dumps({"path": relative, "run_id": "run-test"}) + "\n")
    _write(run_dir / "acceptance.json", '{"release_approved": false}\n')
    _write(run_dir / "command_log.jsonl", '{"run_id": "run-test", "exit_code": 0}\n')
    for relative in local_only:
        _write(run_dir / relative, "SYNTHETIC_MARKER_HOLDOUT_LABEL=1\n")
    disable_metadata_collection(monkeypatch)

    result = evidence.export_evidence(run_dir, "run-test", delivery_dir)

    manifest = json.loads((run_dir / "evidence_manifest.json").read_text())
    paths = {record["path"] for record in manifest["files"]}
    assert paths == allowed
    assert manifest["file_count"] == len(allowed)
    assert result["file_count"] == len(allowed)
    for relative in local_only:
        assert relative not in paths
    assert "acceptance.json" not in paths
    assert "command_log.jsonl" not in paths
    with zipfile.ZipFile(result["archive"]) as bundle:
        names = set(bundle.namelist())
        assert names == {*(f"run-test/{path}" for path in allowed), "run-test/evidence_manifest.json"}
        for name in names:
            assert b"SYNTHETIC_MARKER_HOLDOUT_LABEL" not in bundle.read(name)
    record = json.loads((run_dir / "export_verified.json").read_text())
    assert record["verified"] is True
    assert record["run_id"] == "run-test"
    assert record["file_count"] == len(allowed)
    assert record["manifest_sha256"] == sha256_file(run_dir / "evidence_manifest.json")
    assert record["archive_sha256"] == evidence._archive_digest(Path(result["archive"]))


def test_export_manifest_hash_matches_every_exported_file(tmp_path, monkeypatch):
    run_dir, delivery_dir = make_run(tmp_path)
    _write(run_dir / "provider" / "capability_check.json", '{"status": "BLOCKED"}\n')
    _write(run_dir / "reference" / "model.json", '{"coefficients": {}}\n')
    disable_metadata_collection(monkeypatch)
    result = evidence.export_evidence(run_dir, "run-test", delivery_dir)
    manifest = json.loads((run_dir / "evidence_manifest.json").read_text())
    for record in manifest["files"]:
        path = run_dir / record["path"]
        assert sha256_file(path) == record["sha256"]
        assert path.stat().st_size == record["bytes"]
    with zipfile.ZipFile(result["archive"]) as bundle:
        assert bundle.testzip() is None
