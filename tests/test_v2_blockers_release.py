"""Release blockers 1-2 (this round): release-check must bind 14 records and the ZIP itself.

A tag may only claim a release when the acceptance evidence names every required
item exactly once, on the released commit, and when the exported archive really
contains the files its manifest claims.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from src.common import sha256_file, tree_records, write_json
from src.context import _combined
from src.release import release_check

RUN_ID = "v2-release"
PASSING_TEST = "def test_ok():\n    assert True\n"
FAILING_TEST = "def test_bad():\n    assert False\n"
RECORD_IDS = [f"V1-{index:02d}" for index in range(1, 8)] + [f"V2-{index:02d}" for index in range(1, 8)]
EVIDENCE_MEMBER = "report/validation_report.md"


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=dev@example.com", "-c", "user.name=dev", *arguments],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()


def records_for(commit: str, *, run_id: str = RUN_ID) -> list[dict]:
    return [
        {
            "acceptance_id": acceptance_id,
            "version": "v1" if acceptance_id.startswith("V1") else "v2",
            "status": "PASS",
            "commit_sha": commit,
            "evidence_path": EVIDENCE_MEMBER,
            "run_id": run_id,
        }
        for acceptance_id in RECORD_IDS
    ]


def build_zip(run: Path, run_id: str, members: dict[str, bytes] | None = None) -> Path:
    manifest = json.loads((run / "evidence_manifest.json").read_text())
    if members is None:
        members = {f"{run_id}/{record['path']}": (run / record["path"]).read_bytes() for record in manifest["files"]}
        members[f"{run_id}/evidence_manifest.json"] = (run / "evidence_manifest.json").read_bytes()
    archive = run / "delivery" / f"{run_id}_evidence.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in members.items():
            bundle.writestr(name, payload)
    return archive


def build(
    tmp_path: Path,
    *,
    failing: bool = False,
    dirty_at_init: bool = False,
    commit_override: str | None = None,
) -> tuple[Path, Path, str]:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "config").mkdir()
    (repo / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_smoke.py").write_text(FAILING_TEST if failing else PASSING_TEST, encoding="utf-8")
    (repo / "config" / "settings.json").write_text('{"seed": 46}\n', encoding="utf-8")
    (repo / "data" / "raw").mkdir(parents=True)
    approved_zip = repo / "data" / "raw" / "default_of_credit_card_clients.zip"
    approved_zip.write_bytes(b"approved dataset bytes")
    (repo / "config" / "holdout_ledger.json").write_text(
        json.dumps({"schema_version": "1", "dataset": {"zip_sha256": sha256_file(approved_zip)}, "campaigns": []}),
        encoding="utf-8",
    )
    (repo / "tests" / "test_data_ready.py").write_text(
        "import hashlib, json, pathlib\n"
        "import pytest\n"
        "\n"
        "def test_approved_dataset_is_provisioned():\n"
        "    zip_path = pathlib.Path('data/raw/default_of_credit_card_clients.zip')\n"
        "    if not zip_path.is_file():\n"
        "        pytest.skip('approved dataset is not provisioned')\n"
        "    ledger = json.loads(pathlib.Path('config/holdout_ledger.json').read_text())\n"
        "    assert hashlib.sha256(zip_path.read_bytes()).hexdigest() == ledger['dataset']['zip_sha256']\n",
        encoding="utf-8",
    )
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "release")
    git(repo, "tag", "-a", "v2", "-m", "release tag")
    commit = git(repo, "rev-parse", "HEAD")

    run = tmp_path / "runs" / RUN_ID
    (run / "report").mkdir(parents=True)
    (run / "report" / "validation_report.md").write_text("# report\n", encoding="utf-8")
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
    write_json(run / "acceptance.json", {
        "schema_version": "1",
        "run_id": RUN_ID,
        "release_approved": True,
        "records": records_for(commit),
    })
    write_json(run / "evidence_manifest.json", {
        "schema_version": "1",
        "run_id": RUN_ID,
        "file_count": 1,
        "files": [{"path": EVIDENCE_MEMBER, "sha256": sha256_file(run / EVIDENCE_MEMBER)}],
    })
    archive = build_zip(run, RUN_ID)
    write_json(run / "export_verified.json", {
        "run_id": RUN_ID,
        "verified": True,
        "archive": str(archive),
        "archive_sha256": sha256_file(archive),
        "manifest_sha256": sha256_file(run / "evidence_manifest.json"),
        "file_count": 1,
    })
    return repo, run, commit


def refresh_export(run: Path) -> None:
    record = json.loads((run / "export_verified.json").read_text())
    record["archive_sha256"] = sha256_file(record["archive"])
    record["manifest_sha256"] = sha256_file(run / "evidence_manifest.json")
    write_json(run / "export_verified.json", record)


def set_records(run: Path, records: list[dict]) -> None:
    acceptance = json.loads((run / "acceptance.json").read_text())
    acceptance["records"] = records
    write_json(run / "acceptance.json", acceptance)


def gaps_of(result: dict) -> str:
    return " | ".join(result["gaps"])


def test_release_check_approves_a_complete_bound_run(tmp_path):
    repo, run, commit = build(tmp_path)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "APPROVED", result["gaps"]
    assert result["commit"] == commit
    assert result["new_commit_checks"]["tests_on_published_tree"]["passed"] is True
    assert result["historical_evidence"]["acceptance_release_approved"] is True


def test_missing_record_blocks(tmp_path):
    repo, run, commit = build(tmp_path)
    set_records(run, [record for record in records_for(commit) if record["acceptance_id"] != "V2-07"])
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "missing acceptance record V2-07 (v2)" in gaps_of(result), result["gaps"]


def test_duplicate_record_blocks(tmp_path):
    repo, run, commit = build(tmp_path)
    records = records_for(commit)
    records.append(dict(records[2]))
    set_records(run, records)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "duplicate acceptance record V1-03 (v1) (2 occurrences)" in gaps_of(result), result["gaps"]


def test_wrong_acceptance_run_id_blocks(tmp_path):
    repo, run, commit = build(tmp_path)
    acceptance = json.loads((run / "acceptance.json").read_text())
    acceptance["run_id"] = "some-other-run"
    write_json(run / "acceptance.json", acceptance)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "does not match the target run" in gaps_of(result), result["gaps"]


def test_record_on_another_commit_blocks(tmp_path):
    repo, run, _commit = build(tmp_path)
    set_records(run, records_for("0" * 40))
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "does not match the released commit" in gaps_of(result), result["gaps"]


def test_evidence_path_outside_the_run_blocks(tmp_path):
    repo, run, commit = build(tmp_path)
    records = records_for(commit)
    records[0]["evidence_path"] = "../outside.md"
    set_records(run, records)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "escapes the run" in gaps_of(result), result["gaps"]


def test_fake_archive_blocks(tmp_path):
    repo, run, _commit = build(tmp_path)
    archive = Path(json.loads((run / "export_verified.json").read_text())["archive"])
    archive.write_bytes(b"not a zip at all")
    refresh_export(run)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "not a readable ZIP" in gaps_of(result), result["gaps"]


def test_archive_missing_a_member_blocks(tmp_path):
    repo, run, _commit = build(tmp_path)
    export = json.loads((run / "export_verified.json").read_text())
    manifest_bytes = (run / "evidence_manifest.json").read_bytes()
    archive = build_zip(run, RUN_ID, {f"{RUN_ID}/evidence_manifest.json": manifest_bytes})
    export["archive"] = str(archive)
    write_json(run / "export_verified.json", export)
    refresh_export(run)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "missing members" in gaps_of(result), result["gaps"]


def test_archive_member_content_change_blocks(tmp_path):
    repo, run, _commit = build(tmp_path)
    manifest_bytes = (run / "evidence_manifest.json").read_bytes()
    archive = build_zip(run, RUN_ID, {
        f"{RUN_ID}/{EVIDENCE_MEMBER}": b"# tampered report\n",
        f"{RUN_ID}/evidence_manifest.json": manifest_bytes,
    })
    export = json.loads((run / "export_verified.json").read_text())
    export["archive"] = str(archive)
    write_json(run / "export_verified.json", export)
    refresh_export(run)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "member content changed" in gaps_of(result), result["gaps"]


def test_archive_extra_member_blocks(tmp_path):
    repo, run, _commit = build(tmp_path)
    manifest_bytes = (run / "evidence_manifest.json").read_bytes()
    archive = build_zip(run, RUN_ID, {
        f"{RUN_ID}/{EVIDENCE_MEMBER}": (run / EVIDENCE_MEMBER).read_bytes(),
        f"{RUN_ID}/evidence_manifest.json": manifest_bytes,
        f"{RUN_ID}/injected/extra.json": b"{}",
    })
    export = json.loads((run / "export_verified.json").read_text())
    export["archive"] = str(archive)
    write_json(run / "export_verified.json", export)
    refresh_export(run)
    result = release_check(repo, "v2", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert "unexpected members" in gaps_of(result), result["gaps"]


def test_release_check_blocks_when_the_run_belongs_to_another_commit(tmp_path):
    repo, run, _commit = build(tmp_path, commit_override="0" * 40)
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


def test_release_check_blocks_an_unknown_ref(tmp_path):
    repo, run, _commit = build(tmp_path)
    result = release_check(repo, "no-such-tag", run, RUN_ID)
    assert result["status"] == "BLOCKED"
    assert any("cannot resolve" in gap for gap in result["gaps"])
