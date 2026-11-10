"""Release blocker 3 (this round): v2 context coverage and read-only verification of old runs.

A run pins the exact source, test and legacy-asset tree it was produced from. Later
commits change the worktree, so verification must be possible against a published
tree rather than the current files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.common import read_json, sha256_file, tree_records, write_json
from src.context import REPOSITORY_ASSETS, _combined, materialize_tree, verify_context, verify_context_at

RUN_ID = "v2-context"
REPOSITORY = Path(__file__).resolve().parents[1]


def git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "user.email=dev@example.com", "-c", "user.name=dev", *arguments],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return completed.stdout.strip()


def test_context_assets_cover_every_cited_legacy_source():
    required = {
        "legacy/credit_v1.R",
        "legacy/credit_v2.R",
        "legacy/credit_tree.R",
        "legacy/notes/credit_v1.md",
        "legacy/notes/credit_v2.md",
        "legacy/notes/credit_tree.md",
        "config/inventory_expectations.json",
        "config/holdout_ledger.json",
    }
    assert required <= set(REPOSITORY_ASSETS)
    assert all((REPOSITORY / relative).is_file() for relative in required)


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    (repo / "legacy").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "legacy" / "a.md").write_text("legacy document\n", encoding="utf-8")
    (repo / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_module.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")

    run = tmp_path / "runs" / RUN_ID
    run.mkdir(parents=True)
    write_json(run / "run_manifest.json", {"run_id": RUN_ID})
    write_json(run / "context_manifest.json", {
        "schema_version": "1",
        "run_id": RUN_ID,
        "assets": [{"scope": "repository", "path": "legacy/a.md", "sha256": sha256_file(repo / "legacy" / "a.md")}],
        "trusted_source_sha256": _combined(tree_records(repo / "src", base=repo)),
        "trusted_tests_sha256": _combined(tree_records(repo / "tests", base=repo)),
    })
    return repo, run


def test_old_context_verifies_against_the_published_tree_but_not_a_modified_worktree(tmp_path):
    repo, run = make_repo(tmp_path)
    assert verify_context(repo, run, RUN_ID) is True

    (repo / "src" / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert verify_context(repo, run, RUN_ID) is False

    result = verify_context_at(repo, run, RUN_ID, "HEAD")
    assert result["verified"] is True
    assert result["source_matches"] is True and result["tests_matches"] is True
    assert result["asset_mismatches"] == []


def test_changing_a_reviewed_legacy_source_breaks_the_bound_context(tmp_path):
    repo, run = make_repo(tmp_path)
    assert verify_context_at(repo, run, RUN_ID, "HEAD")["verified"] is True

    (repo / "legacy" / "a.md").write_text("legacy document (revised)\n", encoding="utf-8")
    working = verify_context(repo, run, RUN_ID)
    assert working is False
    published = verify_context_at(repo, run, RUN_ID, "HEAD")
    assert published["verified"] is True  # the published tree still holds the reviewed bytes
    assert published["asset_mismatches"] == []


def test_unknown_ref_is_reported_not_silently_accepted(tmp_path):
    repo, run = make_repo(tmp_path)
    with pytest.raises(ValueError, match="Cannot read git ref"):
        materialize_tree(repo, "no-such-ref")


def test_git_archive_materialization_is_a_real_tree(tmp_path):
    repo, _run = make_repo(tmp_path)
    tree = materialize_tree(repo, "HEAD")
    try:
        root = Path(tree.name)
        assert (root / "legacy" / "a.md").read_text(encoding="utf-8") == "legacy document\n"
        assert (root / "src" / "module.py").is_file()
    finally:
        tree.cleanup()


def test_context_frozen_with_uncommitted_asset_matches_neither_release_tree(tmp_path):
    repo, run = make_repo(tmp_path)
    at_init_commit = git(repo, "rev-parse", "HEAD")
    asset = repo / "legacy" / "a.md"
    asset.write_text("asset reviewed in the worktree\n", encoding="utf-8")
    context_path = run / "context_manifest.json"
    context = read_json(context_path)
    context["assets"][0]["sha256"] = sha256_file(asset)
    write_json(context_path, context)
    assert verify_context(repo, run, RUN_ID) is True

    test_path = repo / "tests" / "test_module.py"
    test_path.write_text(test_path.read_text(encoding="utf-8") + "\n# added after the run\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release tree")

    at_tag = verify_context_at(repo, run, RUN_ID, "HEAD")
    assert at_tag["verified"] is False
    assert at_tag["source_matches"] is True
    assert at_tag["tests_matches"] is False
    assert at_tag["asset_mismatches"] == []

    at_init = verify_context_at(repo, run, RUN_ID, at_init_commit)
    assert at_init["verified"] is False
    assert at_init["source_matches"] is True and at_init["tests_matches"] is True
    assert at_init["asset_mismatches"] == ["legacy/a.md"]
