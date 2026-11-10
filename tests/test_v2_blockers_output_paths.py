"""Release blocker (this round): read-only commands may only create new files outside evidence.

``release-check --output`` overwrote the inspected run's ``acceptance.json`` and
``compare-command-log --save-copy`` overwrote another run's command log, or the
current run's live log through a pre-existing hard link placed outside the run.
Both options now share ``src.outputs.create_new_output``: protected roots (formal
and dev runs, delivery packages, the inspected run) are refused after resolving
symbolic links, any existing destination is refused, and the file is created with
``O_EXCL`` relative to a directory whose ancestry is re-checked by inode.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from src import cli, outputs
from src.outputs import OutputRefused, create_new_output
from src.release import compare_command_log

from test_v2_blockers_readonly import RUN_ID, make_repo, make_run

OTHER_RUN_ID = "v2-other"


def tree_hashes(*roots: Path) -> dict[str, str]:
    state: dict[str, str] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                state[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A copy of the layout: repo with dev_runs/ and delivery/, runs root with two runs."""

    repo = make_repo(tmp_path)
    run = make_run(repo, tmp_path, log_lines=4, snapshot_lines=3)
    (run / "acceptance.json").write_text('{"release_approved": true}\n', encoding="utf-8")
    other = run.parent / OTHER_RUN_ID
    other.mkdir()
    (other / "command_log.jsonl").write_text('{"run_id": "v2-other"}\n', encoding="utf-8")
    dev_runs = repo / "dev_runs"
    (dev_runs / "v2-dev").mkdir(parents=True)
    (dev_runs / "v2-dev" / "command_log.jsonl").write_text('{"run_id": "v2-dev"}\n', encoding="utf-8")
    (dev_runs / "release_check_v2.json").write_text('{"status": "BLOCKED"}\n', encoding="utf-8")
    delivery = repo / "delivery"
    delivery.mkdir()
    (delivery / f"{RUN_ID}_evidence.zip").write_bytes(b"sealed package bytes")
    (delivery / f"{RUN_ID}_acceptance.json").write_text('{"sealed": true}\n', encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(cli, "RUNS_ROOT", run.parent)
    monkeypatch.setattr(cli, "REPOSITORY", repo)
    return {"repo": repo, "run": run, "other": other, "dev_runs": dev_runs, "delivery": delivery, "outside": outside}


def run_cli(capsys, arguments: list[str]) -> tuple[int, dict]:
    capsys.readouterr()
    code = cli.main(arguments)
    return code, json.loads(capsys.readouterr().out)


def protected_targets(ws: dict) -> list[Path]:
    return [
        ws["run"] / "acceptance.json",
        ws["run"] / "command_log.jsonl",
        ws["run"] / "new_file.json",
        ws["other"] / "command_log.jsonl",
        ws["dev_runs"] / "release_check_v2.json",
        ws["dev_runs"] / "v2-dev" / "command_log.jsonl",
        ws["delivery"] / f"{RUN_ID}_evidence.zip",
        ws["delivery"] / f"{RUN_ID}_acceptance.json",
        ws["delivery"] / "fresh.json",
    ]


def assert_untouched(ws: dict, before: dict[str, str]) -> None:
    assert tree_hashes(ws["run"].parent, ws["dev_runs"], ws["delivery"]) == before


@pytest.mark.parametrize("index", range(9))
def test_release_check_output_refuses_every_protected_target(workspace, capsys, index):
    ws = workspace
    target = protected_targets(ws)[index]
    before = tree_hashes(ws["run"].parent, ws["dev_runs"], ws["delivery"])
    code, result = run_cli(capsys, ["release-check", "--run-id", RUN_ID, "--tag", "HEAD", "--output", str(target)])
    assert code == 2, result
    assert result["error_type"] == "OutputRefused"
    assert "refusing to" in result["error"]
    assert not target.exists() or str(target) in before
    assert_untouched(ws, before)


@pytest.mark.parametrize("index", range(9))
def test_save_copy_refuses_every_protected_target(workspace, capsys, index):
    ws = workspace
    target = protected_targets(ws)[index]
    before = tree_hashes(ws["run"].parent, ws["dev_runs"], ws["delivery"])
    code, result = run_cli(capsys, ["compare-command-log", "--run-id", RUN_ID, "--save-copy", str(target)])
    assert code == 2, result
    assert result["error_type"] == "OutputRefused"
    assert_untouched(ws, before)


def test_release_check_output_cannot_overwrite_this_runs_acceptance(workspace, capsys):
    """The reported counterexample, through the CLI."""

    ws = workspace
    acceptance = ws["run"] / "acceptance.json"
    before = acceptance.read_bytes()
    code, result = run_cli(capsys, ["release-check", "--run-id", RUN_ID, "--tag", "HEAD", "--output", str(acceptance)])
    assert code == 2
    assert "refusing to write inside the run directory" in result["error"]
    assert acceptance.read_bytes() == before


def test_save_copy_cannot_overwrite_another_runs_command_log(workspace, capsys):
    ws = workspace
    log = ws["other"] / "command_log.jsonl"
    before = log.read_bytes()
    code, result = run_cli(capsys, ["compare-command-log", "--run-id", RUN_ID, "--save-copy", str(log)])
    assert code == 2
    assert "refusing to write inside" in result["error"]
    assert log.read_bytes() == before


def test_save_copy_refuses_an_outside_hard_link_to_the_live_log(workspace, capsys):
    ws = workspace
    live = ws["run"] / "command_log.jsonl"
    link = ws["outside"] / "looks_harmless.jsonl"
    os.link(live, link)
    before = live.read_bytes()
    code, result = run_cli(capsys, ["compare-command-log", "--run-id", RUN_ID, "--save-copy", str(link)])
    assert code == 2
    assert "refusing to overwrite an existing path" in result["error"]
    assert live.read_bytes() == before
    assert os.stat(live).st_ino == os.stat(link).st_ino


def test_release_check_output_refuses_an_outside_hard_link_to_acceptance(workspace, capsys):
    ws = workspace
    acceptance = ws["run"] / "acceptance.json"
    link = ws["outside"] / "release.json"
    os.link(acceptance, link)
    before = acceptance.read_bytes()
    code, result = run_cli(capsys, ["release-check", "--run-id", RUN_ID, "--tag", "HEAD", "--output", str(link)])
    assert code == 2
    assert "refusing to overwrite an existing path" in result["error"]
    assert acceptance.read_bytes() == before


@pytest.mark.parametrize("command", ["release-check", "compare-command-log"])
def test_symlinked_parent_into_a_run_is_resolved_and_refused(workspace, capsys, command):
    ws = workspace
    alias = ws["outside"] / "alias"
    alias.symlink_to(ws["run"], target_is_directory=True)
    target = alias / "fresh_output.json"
    before = tree_hashes(ws["run"].parent)
    option = ["--tag", "HEAD", "--output"] if command == "release-check" else ["--save-copy"]
    code, result = run_cli(capsys, [command, "--run-id", RUN_ID, *option, str(target)])
    assert code == 2
    assert "refusing to write inside the run directory" in result["error"]
    assert not (ws["run"] / "fresh_output.json").exists()
    assert tree_hashes(ws["run"].parent) == before


@pytest.mark.parametrize("command", ["release-check", "compare-command-log"])
def test_symlink_at_the_destination_is_refused(workspace, capsys, command):
    ws = workspace
    live = ws["run"] / "command_log.jsonl"
    link = ws["outside"] / "dangling_or_not.json"
    link.symlink_to(live)
    before = live.read_bytes()
    option = ["--tag", "HEAD", "--output"] if command == "release-check" else ["--save-copy"]
    code, result = run_cli(capsys, [command, "--run-id", RUN_ID, *option, str(link)])
    assert code == 2
    assert "refusing to overwrite an existing path" in result["error"]
    assert live.read_bytes() == before


def test_a_file_appearing_after_the_check_is_not_overwritten(workspace, monkeypatch):
    """Exclusive creation closes the gap between the check and the write."""

    ws = workspace
    live = ws["run"] / "command_log.jsonl"
    target = ws["outside"] / "race.jsonl"
    original_check = outputs.check_output_destination

    def check_then_race(destination, roots):
        checked = original_check(destination, roots)
        os.link(live, target)  # an attacker plants a hard link right after the check
        return checked

    monkeypatch.setattr(outputs, "check_output_destination", check_then_race)
    before = live.read_bytes()
    with pytest.raises(OutputRefused, match="existing path"):
        create_new_output(target, b"overwrite attempt\n", [(ws["run"], "the run directory")])
    assert live.read_bytes() == before


def test_a_parent_swapped_for_a_link_after_the_check_is_refused(workspace, monkeypatch):
    ws = workspace
    parent = ws["outside"] / "swap"
    parent.mkdir()
    target = parent / "copy.jsonl"
    original_check = outputs.check_output_destination

    def check_then_swap(destination, roots):
        checked = original_check(destination, roots)
        parent.rename(ws["outside"] / "swap.moved")
        parent.symlink_to(ws["run"], target_is_directory=True)
        return checked

    monkeypatch.setattr(outputs, "check_output_destination", check_then_swap)
    before = tree_hashes(ws["run"])
    with pytest.raises(OutputRefused, match="resolved into a protected root"):
        create_new_output(target, b"payload\n", [(ws["run"], "the run directory")])
    assert tree_hashes(ws["run"]) == before
    assert not (ws["run"] / "copy.jsonl").exists()


def test_save_copy_creates_a_new_file_outside_protected_directories(workspace, capsys):
    ws = workspace
    before = tree_hashes(ws["run"].parent, ws["dev_runs"], ws["delivery"])
    target = ws["outside"] / "nested" / "snapshot.jsonl"
    code, result = run_cli(capsys, ["compare-command-log", "--run-id", RUN_ID, "--save-copy", str(target)])
    assert code == 0, result
    assert target.read_bytes() == (ws["run"] / "command_log_snapshot.jsonl").read_bytes()
    assert result["saved_copy_sha256"] == result["snapshot_sha256"]
    assert_untouched(ws, before)
    # The same destination a second time is an existing file and is refused.
    code, result = run_cli(capsys, ["compare-command-log", "--run-id", RUN_ID, "--save-copy", str(target)])
    assert code == 2 and "existing path" in result["error"]


def test_release_check_writes_a_new_output_file_outside_protected_directories(workspace, capsys):
    ws = workspace
    before = tree_hashes(ws["run"].parent, ws["dev_runs"], ws["delivery"])
    target = ws["outside"] / "release_check.json"
    code, result = run_cli(capsys, ["release-check", "--run-id", RUN_ID, "--tag", "HEAD", "--output", str(target)])
    assert result["status"] in {"APPROVED", "BLOCKED"}, result
    assert result["output"] == str(target.resolve())
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["status"] == result["status"] and written["gaps"] == result["gaps"]
    assert_untouched(ws, before)


def test_compare_command_log_api_protects_sibling_runs_by_default(workspace):
    ws = workspace
    log = ws["other"] / "command_log.jsonl"
    before = log.read_bytes()
    with pytest.raises(OutputRefused, match="runs root"):
        compare_command_log(ws["run"], save_copy=log)
    assert log.read_bytes() == before
