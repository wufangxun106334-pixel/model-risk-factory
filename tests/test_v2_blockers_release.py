"""Release blocker 3 (this round): a tag may only claim a release the evidence supports.

These tests use a throwaway git repository so the rule is checked mechanically:
the published tree must satisfy the run's context, the suite must pass there, and
the run must have been initialised on that exact commit with a clean worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.common import sha256_file, tree_records, write_json
from src.context import _combined
from src.release import release_check

RUN_ID = "v2-release"
PASSING_TEST = "def test_ok():\n    assert True\n"
FAILING_TEST = "def test_bad():\n    assert False\n"


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=dev@example.com", "-c", "user.name=dev", *arguments],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()


def build(tmp_path: Path, *, failing: bool = False, dirty_at_init: bool = False, commit_override: str | None = None) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "config").mkdir()
    (repo / "requirement.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_smoke.py").write_text(FAILING_TEST if failing else PASSING_TEST, encoding="utf-8")
    (repo / "config" / "settings.json").write_text('{"seed": 46}\n', encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release")
    git(repo, "tag", "-a", "v2", "-m", "release tag")
    commit = git(repo, "rev-parse", "HEAD")

    run = tmp_path / "runs" / RUN_ID
    run.mkdir(parents=True)
    write_json(run / "run_manifest.json", {
        "run_id": RUN_ID,
        "git_commit_at_init": commit_override or commit,
        "worktree_clean_at_init": not dirty_at_init,
    })
    write_json(run / "context_manifest.json", {
        "schema_version": "1",
        "run_id": RUN_ID,
        "assets": [{"scope": "repository", "path": "config/settings.json", "sha256": sha256_file(repo / "config" / "settings.json")}],
        "trusted_source_sha256": _combined(tree_records(repo / "src", base=repo)),
        "trusted_tests_sha256": _combined(tree_records(repo / "tests", base=repo)),
    })
    write_json(run / "acceptance.json", {"run_id": RUN_ID, "release_approved": True, "records": [{"acceptance_id": "V2-01", "status": "PASS"}]})
    evidence = run / "evidence_manifest.json"
    write_json(evidence, {"file_count": 1, "files": [{"path": "acceptance.json", "sha256": sha256_file(run / "acceptance.json")}]})
    archive = tmp_path / f"{RUN_ID}_evidence.zip"
    archive.write_bytes(b"sealed evidence")
    write_json(run / "export_verified.json", {"archive": str(archive), "archive_sha256": sha256_file(archive), "file_count": 1})
    return repo, run, commit


def test_release_check_approves_when_the_tag_tree_matches_the_run(tmp_path):
    repo, run, commit = build(tmp_path)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "APPROVED", result["gaps"]
    assert result["commit"] == commit
    assert result["context"]["verified"] is True
    assert result["new_commit_checks"]["tests_on_published_tree"]["passed"] is True
    assert result["historical_evidence"]["acceptance_release_approved"] is True


def test_release_check_blocks_when_the_run_belongs_to_another_commit(tmp_path):
    repo, run, commit = build(tmp_path, commit_override="0" * 40)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert any("not at the released commit" in gap for gap in result["gaps"]), result["gaps"]


def test_release_check_blocks_when_the_worktree_was_dirty_at_init(tmp_path):
    repo, run, _commit = build(tmp_path, dirty_at_init=True)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert any("dirty" in gap for gap in result["gaps"]), result["gaps"]


def test_release_check_blocks_when_the_published_tree_fails_its_tests(tmp_path):
    repo, run, _commit = build(tmp_path, failing=True)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert any("test suite fails" in gap for gap in result["gaps"]), result["gaps"]
    assert result["new_commit_checks"]["tests_on_published_tree"]["passed"] is False


def test_release_check_blocks_when_evidence_hash_is_stale(tmp_path):
    repo, run, _commit = build(tmp_path)
    (run / "acceptance.json").write_text('{"run_id": "x"}\n', encoding="utf-8")
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert any("evidence files changed" in gap or "acceptance" in gap for gap in result["gaps"]), result["gaps"]


def test_release_check_blocks_an_unknown_ref(tmp_path):
    repo, run, _commit = build(tmp_path)
    result = release_check(repo, "no-such-tag", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert any("cannot resolve" in gap for gap in result["gaps"])
