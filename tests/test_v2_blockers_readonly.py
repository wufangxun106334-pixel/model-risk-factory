"""Release blocker 3 (this round): test completeness accounting and truly read-only checks.

Two failures motivated these tests: a run whose published-tree suite exited 0 with
seven skipped tests was reported as "passing", and the read-only verification
commands appended rows to the sealed run's command log.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from src import cli
from src.release import _provision_approved_zip, _run_tree_tests, compare_command_log, release_check

RUN_ID = "v2-readonly"
SKIP_TEST = """import pytest

def test_needs_data():
    pytest.skip("approved dataset is not provisioned")
"""


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=dev@example.com", "-c", "user.name=dev", *arguments],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()


def make_repo(tmp_path: Path, test_source: str = "def test_ok():\n    assert True\n") -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    repo.joinpath("src", "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    repo.joinpath("tests", "test_smoke.py").write_text(test_source, encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release")
    git(repo, "tag", "-a", "v2", "-m", "release tag")
    return repo


def make_run(repo: Path, tmp_path: Path, *, log_lines: int = 2, snapshot_lines: int | None = None) -> Path:
    from src.common import sha256_file, tree_records as repo_trees
    from src.context import _combined

    run = tmp_path / "runs" / RUN_ID
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text(json.dumps({"run_id": RUN_ID}) + "\n", encoding="utf-8")
    commit = git(repo, "rev-parse", "HEAD")
    (run / "context_manifest.json").write_text(json.dumps({
        "schema_version": "1",
        "run_id": RUN_ID,
        "assets": [],
        "trusted_source_sha256": _combined(repo_trees(repo / "src", base=repo)),
        "trusted_tests_sha256": _combined(repo_trees(repo / "tests", base=repo)),
    }), encoding="utf-8")
    (run / "run_manifest.json").write_text(json.dumps({"run_id": RUN_ID, "git_commit_at_init": commit, "worktree_clean_at_init": True}) + "\n", encoding="utf-8")
    lines = [
        json.dumps({"run_id": RUN_ID, "argv": ["python", "-m", "src.cli", f"step-{index}", "--run-id", RUN_ID], "exit_code": 0})
        for index in range(log_lines)
    ]
    (run / "command_log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    snapshot = lines if snapshot_lines is None else lines[:snapshot_lines]
    (run / "command_log_snapshot.jsonl").write_text("\n".join(snapshot) + ("\n" if snapshot else ""), encoding="utf-8")
    return run


def tree_state(run: Path) -> dict[str, str]:
    return {
        path.relative_to(run).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run.rglob("*"))
        if path.is_file()
    }


def test_compare_command_log_reports_extras_without_writing(tmp_path):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path, log_lines=5, snapshot_lines=3)
    before = tree_state(run)
    result = compare_command_log(run)
    assert result["status"] == "DIFFERS"
    assert result["snapshot_lines"] == 3 and result["live_lines"] == 5
    assert result["prefix_matches"] is True
    assert result["extra_live_lines"] == 2
    assert result["extra_commands"] == ["step-3", "step-4"]
    assert tree_state(run) == before
    assert len((run / "command_log.jsonl").read_text().splitlines()) == 5


def test_compare_command_log_matches_after_the_snapshot_is_authoritative(tmp_path):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path, log_lines=3, snapshot_lines=3)
    result = compare_command_log(run)
    assert result["status"] == "MATCH"
    assert result["extra_live_lines"] == 0
    assert result["live_sha256"] == result["snapshot_sha256"]


def test_compare_command_log_can_save_a_copy_outside_the_run(tmp_path):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path, log_lines=4, snapshot_lines=3)
    before = tree_state(run)
    destination = tmp_path / "copies" / "command_log_snapshot.jsonl"
    result = compare_command_log(run, save_copy=destination)
    assert destination.is_file()
    assert destination.read_bytes() == (run / "command_log_snapshot.jsonl").read_bytes()
    assert result["saved_copy_sha256"] == result["snapshot_sha256"]
    assert tree_state(run) == before


def test_compare_command_log_refuses_to_write_inside_the_run(tmp_path):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path)
    before = tree_state(run)
    with pytest.raises(ValueError, match="refusing to write inside the run"):
        compare_command_log(run, save_copy=run / "copy.jsonl")
    assert tree_state(run) == before


def test_compare_command_log_requires_the_snapshot(tmp_path):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path)
    (run / "command_log_snapshot.jsonl").unlink()
    with pytest.raises(ValueError, match="command_log_snapshot.jsonl is required"):
        compare_command_log(run)


def tree_state(run: Path) -> dict[str, str]:
    return {
        path.relative_to(run).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run.rglob("*"))
        if path.is_file()
    }


def test_compare_command_log_detects_a_diverged_live_log(tmp_path):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path, log_lines=4, snapshot_lines=3)
    log = run / "command_log.jsonl"
    log.write_text(log.read_text().replace("step-0", "tampered-0"), encoding="utf-8")
    result = compare_command_log(run)
    assert result["status"] == "DIFFERS"
    assert result["prefix_matches"] is False
    assert result["live_lines"] == 4


@pytest.mark.parametrize("command", ["verify-context", "report-status"])
def test_read_only_commands_do_not_touch_the_run(tmp_path, monkeypatch, command):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path)
    monkeypatch.setattr(cli, "RUNS_ROOT", run.parent)
    monkeypatch.setattr(cli, "REPOSITORY", repo)
    before = tree_state(run)
    log_before = (run / "command_log.jsonl").read_bytes()
    arguments = [command, "--run-id", RUN_ID] + (["--at", "HEAD"] if command == "verify-context" else [])
    cli.main(arguments)
    assert (run / "command_log.jsonl").read_bytes() == log_before
    assert tree_state(run) == before


def test_compare_command_log_via_cli_is_read_only(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path, log_lines=4, snapshot_lines=3)
    monkeypatch.setattr(cli, "RUNS_ROOT", run.parent)
    monkeypatch.setattr(cli, "REPOSITORY", repo)
    before = tree_state(run)
    cli.main(["compare-command-log", "--run-id", RUN_ID])
    assert tree_state(run) == before
    copy = tmp_path / "outside" / "snapshot.jsonl"
    cli.main(["compare-command-log", "--run-id", RUN_ID, "--save-copy", str(copy)])
    assert copy.read_bytes() == (run / "command_log_snapshot.jsonl").read_bytes()
    assert tree_state(run) == before


def test_release_check_does_not_touch_the_run(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path)
    monkeypatch.setattr(cli, "RUNS_ROOT", run.parent)
    monkeypatch.setattr(cli, "REPOSITORY", repo)
    before = tree_state(run)
    log_before = (run / "command_log.jsonl").read_bytes()
    cli.main(["release-check", "--run-id", RUN_ID, "--tag", "HEAD"])
    assert (run / "command_log.jsonl").read_bytes() == log_before
    assert tree_state(run) == before


def test_skipped_tests_are_classified_and_listed(tmp_path):
    repo = make_repo(tmp_path, test_source=SKIP_TEST)
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "tests").mkdir()
    (tree / "tests" / "test_smoke.py").write_text(SKIP_TEST, encoding="utf-8")
    result = _run_tree_tests(tree, 120)
    assert result["totals"]["skipped"] == 1
    assert result["passed"] is False
    assert any("test_needs_data" in name for name in result["skipped_tests"])


def test_skipped_test_blocks_a_release(tmp_path):
    repo = make_repo(tmp_path, test_source=SKIP_TEST)
    run = make_run(repo, tmp_path)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert any("skipped" in gap for gap in result["gaps"]), result["gaps"]
    assert any("test_needs_data" in gap for gap in result["gaps"]), result["gaps"]


def test_approved_zip_is_provisioned_only_when_the_hash_matches(tmp_path):
    tree = tmp_path / "tree"
    (tree / "config").mkdir(parents=True)
    approved = tmp_path / "approved.zip"
    approved.write_bytes(b"approved dataset bytes")
    digest = hashlib.sha256(approved.read_bytes()).hexdigest()
    (tree / "config" / "holdout_ledger.json").write_text(json.dumps({"dataset": {"zip_sha256": digest}}), encoding="utf-8")

    wrong = tmp_path / "wrong.zip"
    wrong.write_bytes(b"not the approved bytes")
    gaps = _provision_approved_zip(tmp_path / "repo", tree, tmp_path / "run", wrong)
    assert gaps and "does not match the approved ledger hash" in gaps[0]
    assert not (tree / "data" / "raw" / "default_of_credit_card_clients.zip").exists()

    gaps = _provision_approved_zip(tmp_path / "repo", tree, tmp_path / "run", approved)
    assert gaps == []
    provisioned = tree / "data" / "raw" / "default_of_credit_card_clients.zip"
    assert provisioned.is_file() and hashlib.sha256(provisioned.read_bytes()).hexdigest() == digest


def test_missing_zip_is_reported_as_a_gap_not_a_skip(tmp_path):
    tree = tmp_path / "tree"
    (tree / "config").mkdir(parents=True)
    (tree / "config" / "holdout_ledger.json").write_text(json.dumps({"dataset": {"zip_sha256": "0" * 64}}), encoding="utf-8")
    gaps = _provision_approved_zip(tmp_path / "repo", tree, tmp_path / "run", None)
    assert gaps and "not found" in gaps[0]
