"""formal-preflight: every precondition of the formal run is checked, read-only."""

import json
import subprocess
from pathlib import Path

import pytest

from src import cli
from src.common import sha256_bytes
from src.preflight import run_preflight

REPO = Path(__file__).resolve().parents[1]
LLM_ENV = {
    "LLM_BASE_URL": "https://gateway.invalid/v1",
    "LLM_CHAT_COMPLETIONS_URL": "https://gateway.invalid/v1/chat/completions",
    "LLM_PROTOCOL": "openai_chat_completions",
    "LLM_MODEL": "test-model",
    "LLM_API_KEY": "test-key-not-real",
    "LLM_TIMEOUT_SECONDS": "300",
    "LLM_MAX_OUTPUT_TOKENS": "32768",
}
ZIP_BYTES = b"approved-zip-stand-in"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    config = json.loads((REPO / "config" / "data_config.json").read_text())
    config["uci_competition_use_approved"] = True
    (root / "config" / "data_config.json").write_text(json.dumps(config))
    ledger = json.loads((REPO / "config" / "holdout_ledger.json").read_text())
    ledger["dataset"]["zip_sha256"] = sha256_bytes(ZIP_BYTES)
    (root / "config" / "holdout_ledger.json").write_text(json.dumps(ledger))
    (root / "data" / "raw").mkdir(parents=True)
    (root / "data" / "raw" / "default_of_credit_card_clients.zip").write_bytes(ZIP_BYTES)
    (root / ".gitignore").write_text("data/\nruns/\n")
    (root / "runs").mkdir()
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", ".")
    _git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return root


def _ok_ledger(_repository: Path, _zip: Path) -> dict:
    return {"campaigns": [{}] * 5}


def _run(repo: Path, **overrides):
    options = {
        "runs_root": repo / "runs",
        "environ": dict(LLM_ENV),
        "runner": lambda command: 0,
        "verify_ledger": _ok_ledger,
    }
    options.update(overrides)
    runs_root = options.pop("runs_root")
    return run_preflight(repo, runs_root, **options)


def _status(result: dict, name: str) -> str:
    return next(check["status"] for check in result["checks"] if check["check"] == name)


def test_all_checks_pass_on_a_ready_tree(repo: Path):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    result = _run(repo, expected_sha=head)
    assert result["status"] == "PASS", result["failed_checks"]
    assert result["campaign_id"] == "MDL_CREDIT_V1:uci:seed-47"


def test_dirty_tree_fails(repo: Path):
    (repo / "stray.txt").write_text("x")
    assert _status(_run(repo), "worktree_clean") == "FAIL"


def test_head_mismatch_fails(repo: Path):
    assert _status(_run(repo, expected_sha="0" * 40), "head_matches_expected") == "FAIL"


def test_dev_runs_root_fails(repo: Path):
    (repo / "dev_runs").mkdir()
    assert _status(_run(repo, runs_root=repo / "dev_runs"), "formal_runs_root") == "FAIL"


def _edit_config(repo: Path, **values) -> None:
    path = repo / "config" / "data_config.json"
    config = json.loads(path.read_text())
    config.update(values)
    path.write_text(json.dumps(config))


def test_wrong_seed_fails(repo: Path):
    _edit_config(repo, seed=46)
    assert _status(_run(repo), "campaign_seed") == "FAIL"


@pytest.mark.parametrize("value", [False, None, "true"])
def test_uci_permission_must_be_literally_true(repo: Path, value):
    _edit_config(repo, uci_competition_use_approved=value)
    assert _status(_run(repo), "uci_use_approved") == "FAIL"


def test_zip_hash_mismatch_fails_and_skips_rebuild(repo: Path):
    (repo / "data" / "raw" / "default_of_credit_card_clients.zip").write_bytes(b"other")
    result = _run(repo)
    assert _status(result, "uci_zip_hash") == "FAIL"
    assert all(check["check"] != "holdout_ledger_rebuild" for check in result["checks"])


def test_missing_zip_fails(repo: Path):
    (repo / "data" / "raw" / "default_of_credit_card_clients.zip").unlink()
    assert _status(_run(repo), "uci_zip_hash") == "FAIL"


def test_ledger_rebuild_failure_fails(repo: Path):
    def broken(_repository, _zip):
        raise ValueError("rebuilt hash differs")

    assert _status(_run(repo, verify_ledger=broken), "holdout_ledger_rebuild") == "FAIL"


def test_seed_already_in_committed_ledger_fails(repo: Path):
    path = repo / "config" / "holdout_ledger.json"
    ledger = json.loads(path.read_text())
    ledger["campaigns"].append({"campaign_id": "MDL_CREDIT_V1:uci:seed-47"})
    path.write_text(json.dumps(ledger))
    assert _status(_run(repo), "seed_unused_in_committed_ledger") == "FAIL"


def test_seed_already_consumed_locally_fails(repo: Path):
    (repo / "runs" / "holdout_consumption.jsonl").write_text(
        json.dumps({"campaign_id": "MDL_CREDIT_V1:uci:seed-47", "status": "CONSUMED"}) + "\n"
    )
    assert _status(_run(repo), "seed_unused_in_local_ledger") == "FAIL"


def test_missing_llm_settings_fail_without_leaking_values(repo: Path):
    environ = dict(LLM_ENV)
    del environ["LLM_BASE_URL"]
    result = _run(repo, environ=environ)
    assert _status(result, "llm_configuration") == "FAIL"
    assert "test-key-not-real" not in json.dumps(result)


def test_docker_down_fails_daemon_and_images(repo: Path):
    result = _run(repo, runner=lambda command: 1)
    assert _status(result, "docker_daemon") == "FAIL"
    assert _status(result, "image model-risk-factory-runner:v1") == "FAIL"


def test_missing_image_fails(repo: Path):
    def runner(command):
        return 1 if command[-1] == "rocker/r-ver:4.4.2" else 0

    assert _status(_run(repo, runner=runner), "image rocker/r-ver:4.4.2") == "FAIL"


def test_cli_command_is_read_only(repo: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "REPOSITORY", repo)
    monkeypatch.setattr(cli, "RUNS_ROOT", (repo / "runs").resolve())
    monkeypatch.setattr("src.preflight._run", lambda command: 0)
    monkeypatch.setattr("src.holdout_ledger.verify_ledger", _ok_ledger)
    for name, value in LLM_ENV.items():
        monkeypatch.setenv(name, value)
    before = sorted(path.relative_to(repo) for path in repo.rglob("*") if ".git" not in path.parts)
    code = cli.main(["formal-preflight", "--raw-uci", str(repo / "data" / "raw" / "default_of_credit_card_clients.zip")])
    after = sorted(path.relative_to(repo) for path in repo.rglob("*") if ".git" not in path.parts)
    assert "formal-preflight" in cli.READ_ONLY_COMMANDS
    assert before == after
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert code == 0


SCRIPT = REPO / "docs" / "v3" / "formal_run.sh"


def _script(env_extra: dict | None = None):
    import os

    env = {key: value for key, value in os.environ.items() if key != "MRF_RUNS_ROOT"}
    env.update(env_extra or {})
    # A new session has no controlling terminal, so /dev/tty cannot be opened.
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=REPO, env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, start_new_session=True, timeout=60,
    )


def test_formal_run_script_parses():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_formal_run_script_refuses_dev_runs_root():
    result = _script({"MRF_RUNS_ROOT": str(REPO / "dev_runs")})
    assert result.returncode == 2
    assert "must use runs/" in result.stderr


def test_formal_run_script_refuses_without_terminal():
    result = _script()
    assert result.returncode == 2
    assert "interactive terminal" in result.stderr


def test_formal_run_script_runs_preflight_before_init_run():
    text = SCRIPT.read_text()
    assert text.index("formal-preflight") < text.index("init-run")
    assert text.index("confirm_run_id \"accept") < text.index("step accept")
    assert "git tag -a v3" in text and "\ngit tag" not in text
