"""Regression tests for the tooling defects that blocked the v2 release.

These cover the four v1 defects recorded in README "已知工具缺陷":
1. a fixture FAIL could not enter the repair loop;
2. any retry inside a run permanently invalidated the acceptance chain;
3. the CLI `prepare --seed` default disagreed with the campaign config;
4. an 8192-token ceiling truncated `submit_candidate` mid-JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import cli, workflow
from src.acceptance import _command_chain
from src.agent import _require_output_budget, _run_stage, repair_diagnostics
from src.common import ContractError, GateError, append_jsonl, create_run, read_json, sha256_file, write_json
from src.provider import ProviderResponse

RUN_ID = "v2-20261110T000000Z-aaaaaaaa"


# --------------------------------------------------------------------------
# 3. prepare --seed default follows the campaign config
# --------------------------------------------------------------------------


def _repository(tmp_path: Path, seed: int = 43) -> Path:
    repository = tmp_path / "repo"
    write_json(repository / "config" / "data_config.json", {"seed": seed})
    write_json(repository / "config" / "provider_config.json", {"min_candidate_output_tokens": 16384})
    return repository


def test_prepare_seed_defaults_to_the_configured_campaign_seed(tmp_path):
    repository = _repository(tmp_path, seed=43)
    arguments = cli._parser().parse_args(["prepare", "--run-id", RUN_ID, "--synthetic"])
    assert arguments.seed is None
    assert cli.resolve_campaign_seed(arguments.seed, repository) == 43


def test_explicit_seed_that_contradicts_the_config_is_rejected(tmp_path):
    repository = _repository(tmp_path, seed=43)
    with pytest.raises(ContractError, match="43"):
        cli.resolve_campaign_seed(42, repository)
    assert cli.resolve_campaign_seed(43, repository) == 43


def test_prepare_without_seed_uses_the_config_value_end_to_end(tmp_path, monkeypatch):
    repository = _repository(tmp_path, seed=43)
    runs_root = tmp_path / "runs"
    monkeypatch.setattr(cli, "REPOSITORY", repository)
    monkeypatch.setattr(cli, "RUNS_ROOT", runs_root)
    manifest = create_run(runs_root, repository, "synthetic")
    run_id = manifest["run_id"]
    result = cli.main(["prepare", "--run-id", run_id, "--synthetic"])
    assert result == 0
    data_manifest = read_json(runs_root / run_id / "data" / "data_manifest.json")
    assert data_manifest["seed"] == 43

    # The same run must still refuse an explicit seed that disagrees with the config.
    other = create_run(runs_root, repository, "synthetic")["run_id"]
    assert cli.main(["prepare", "--run-id", other, "--synthetic", "--seed", "42"]) == 2


# --------------------------------------------------------------------------
# 2. Retries inside one run keep failure evidence and still verify
# --------------------------------------------------------------------------


def _log(run_dir: Path, entries: list[tuple[list[str], int]], *, run_id: str = RUN_ID, context: str | None = None) -> None:
    path = run_dir / "command_log.jsonl"
    path.unlink(missing_ok=True)
    for argv, exit_code in entries:
        event = {"run_id": run_id, "argv": ["python", "-m", "src.cli", *argv], "exit_code": exit_code}
        if context is not None:
            event["context_sha256"] = context
        append_jsonl(path, event)


def _chain(argv: list[str]) -> list[str]:
    return [*argv]


def _good_chain(attempt: int = 1) -> list[list[str]]:
    base = ["--run-id", RUN_ID]
    return [
        _chain(["check-provider", *base]),
        _chain(["prepare", *base]),
        _chain(["baseline", *base]),
        _chain(["reference-parity", *base]),
        _chain(["fixture-parity", *base]),
        _chain(["mutation-check", *base]),
        _chain(["extract-inventory", *base]),
        _chain(["approve", *base, "--gate", "Gate_A", "--sha256", "a" * 64]),
        _chain(["generate-candidate", *base, "--attempt", str(attempt)]),
        _chain(["approve", *base, "--gate", "Gate_B", "--attempt", str(attempt), "--sha256", "b" * 64]),
        _chain(["run-dev", *base, "--attempt", str(attempt)]),
        _chain(["candidate-fixtures", *base, "--attempt", str(attempt)]),
        _chain(["freeze", *base, "--attempt", str(attempt)]),
        _chain(["accept", *base]),
    ]


def _bound_run(tmp_path: Path, attempt: int = 1) -> tuple[Path, str]:
    run_dir = tmp_path / "run"
    write_json(run_dir / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    context = sha256_file(run_dir / "context_manifest.json")
    write_json(run_dir / "frozen" / "frozen.json", {
        "run_id": RUN_ID,
        "attempt": attempt,
        "candidate_sha256": "b" * 64,
        "context_sha256": context,
    })
    write_json(run_dir / "migration_result.json", {
        "run_id": RUN_ID,
        "attempt": attempt,
        "candidate_sha256": "b" * 64,
        "dev_status": "PASS",
        "final_status": "PASS",
        "context_sha256": context,
    })
    return run_dir, context


def test_failed_step_followed_by_success_in_the_same_run_verifies(tmp_path):
    run_dir, context = _bound_run(tmp_path)
    good = _good_chain(1)
    entries: list[tuple[list[str], int]] = []
    for argv in good:
        if argv[0] in {"generate-candidate", "candidate-fixtures"}:
            entries.append((argv, 2))  # first attempt fails (truncated / fixture FAIL)
        entries.append((argv, 0))  # then the legal retry succeeds
    _log(run_dir, entries, context=context)
    assert _command_chain(run_dir, RUN_ID) == []
    # Both the failure and the retry stay in the log as evidence.
    events = [json.loads(line) for line in (run_dir / "command_log.jsonl").read_text().splitlines()]
    assert sum(1 for event in events if event["argv"][3] == "generate-candidate") == 2
    assert any(event["exit_code"] == 2 for event in events if event["argv"][3] == "generate-candidate")


def test_step_that_only_ever_failed_is_reported(tmp_path):
    run_dir, context = _bound_run(tmp_path)
    good = _good_chain(1)
    entries = [(argv, 1 if argv[0] == "accept" else 0) for argv in good]
    _log(run_dir, entries, context=context)
    problems = _command_chain(run_dir, RUN_ID)
    assert any("accept" in problem and "no successful attempt" in problem for problem in problems)


def test_chain_rejects_a_success_on_the_wrong_attempt(tmp_path):
    run_dir, context = _bound_run(tmp_path, attempt=1)
    good = _good_chain(1)
    entries = [
        (argv, 0)
        for argv in good
        if argv[0] not in {"generate-candidate"}
    ]
    # The surviving generate-candidate success belongs to attempt 0, not the frozen attempt 1.
    entries.insert(8, (["generate-candidate", "--run-id", RUN_ID, "--attempt", "0"], 0))
    _log(run_dir, entries, context=context)
    problems = _command_chain(run_dir, RUN_ID)
    assert any("frozen attempt 1" in problem for problem in problems)


def test_chain_rejects_a_gate_b_approval_of_another_hash(tmp_path):
    run_dir, context = _bound_run(tmp_path)
    entries = [(argv, 0) for argv in _good_chain(1)]
    _log(run_dir, entries, context=context)
    assert _command_chain(run_dir, RUN_ID) == []
    entries[9] = (["approve", "--run-id", RUN_ID, "--gate", "Gate_B", "--attempt", "1", "--sha256", "c" * 64], 0)
    _log(run_dir, entries, context=context)
    assert any("expected the frozen candidate" in problem for problem in _command_chain(run_dir, RUN_ID))


def test_chain_rejects_a_stale_context_and_a_foreign_run_id(tmp_path):
    run_dir, context = _bound_run(tmp_path)
    entries = [(argv, 0) for argv in _good_chain(1)]
    _log(run_dir, entries, context=context)
    assert _command_chain(run_dir, RUN_ID) == []

    stale = "0" * 64
    _log(run_dir, entries, context=stale)
    assert any("stale context" in problem for problem in _command_chain(run_dir, RUN_ID))

    _log(run_dir, entries, context=context)
    events = [json.loads(line) for line in (run_dir / "command_log.jsonl").read_text().splitlines()]
    events[11]["argv"][5] = "v2-other-run"
    (run_dir / "command_log.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")
    assert any("does not match" in problem for problem in _command_chain(run_dir, RUN_ID))


# --------------------------------------------------------------------------
# 1. A fixture FAIL authorises the next repair attempt
# --------------------------------------------------------------------------


def _candidate_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    write_json(run_dir / "migration_result.json", {
        "run_id": RUN_ID,
        "attempt": 0,
        "candidate_sha256": "a" * 64,
        "dev_status": "PASS",
        "fixture_status": "FAIL",
        "final_status": "NOT_RUN",
        "diagnostics_ref": "dev/attempt_000/fixture_diagnostics.json",
    })
    write_json(run_dir / "dev" / "attempt_000" / "fixture_diagnostics.json", {
        "run_id": RUN_ID,
        "attempt": 0,
        "fixture_status": "FAIL",
        "failing_cases": [{"name": "behavior", "parity_status": "FAIL"}],
        "contains_raw_rows": False,
        "contains_baseline_answers": False,
    })
    return run_dir


def test_fixture_fail_enters_the_repair_loop(tmp_path):
    run_dir = _candidate_run(tmp_path)
    diagnostics = repair_diagnostics(run_dir, 1)
    assert diagnostics["fixture_status"] == "FAIL"
    assert diagnostics["failing_cases"][0]["name"] == "behavior"
    assert repair_diagnostics(run_dir, 0) is None


def test_repair_is_refused_without_a_recorded_fail(tmp_path):
    run_dir = _candidate_run(tmp_path)
    result = read_json(run_dir / "migration_result.json")
    result["fixture_status"] = "PASS"
    write_json(run_dir / "migration_result.json", result)
    with pytest.raises(GateError):
        repair_diagnostics(run_dir, 1)
    with pytest.raises(GateError):
        repair_diagnostics(run_dir, 2)


def test_unsafe_fixture_diagnostics_never_reach_the_agent(tmp_path):
    run_dir = _candidate_run(tmp_path)
    write_json(run_dir / "dev" / "attempt_000" / "fixture_diagnostics.json", {
        "contains_raw_rows": True,
        "contains_baseline_answers": False,
    })
    with pytest.raises(ContractError):
        repair_diagnostics(run_dir, 1)


def test_fixture_run_records_an_aggregate_diagnostics_reference(tmp_path, monkeypatch):
    run_dir = _candidate_run(tmp_path)
    (run_dir / "data").mkdir(parents=True, exist_ok=True)
    (run_dir / "data" / "dev.csv").write_text("client_id\n1\n", encoding="utf-8")
    manifest = {"files": {"dev.csv": {"sha256": sha256_file(run_dir / "data" / "dev.csv")}}}
    write_json(run_dir / "data" / "data_manifest.json", manifest)
    source = run_dir / "candidates" / "attempt_000" / "credit_v1.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('candidate')\n", encoding="utf-8")
    digest = sha256_file(source)
    write_json(run_dir / "context_manifest.json", {"run_id": RUN_ID, "assets": []})
    write_json(source.parent / "candidate.json", {
        "run_id": RUN_ID,
        "attempt": 0,
        "candidate_sha256": digest,
        "context_sha256": sha256_file(run_dir / "context_manifest.json"),
    })
    write_json(run_dir / "reference" / "model.json", {})
    (run_dir / "data" / "fixtures").mkdir(parents=True, exist_ok=True)
    for name in ("behavior", "column_reordered", "row_reordered", "duplicate_ids", "missing_column", "empty"):
        (run_dir / "data" / "fixtures" / f"{name}.csv").write_text("client_id\n1\n", encoding="utf-8")
        reference = run_dir / "fixtures" / name / "r" / "dev_predictions.csv"
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_text("client_id,probability,classification\n1,0.1,0\n", encoding="utf-8")

    monkeypatch.setattr(workflow, "verify_context", lambda *args, **kwargs: True)
    monkeypatch.setattr(workflow, "require_approval", lambda *args, **kwargs: digest)
    monkeypatch.setattr(workflow, "runner_image", lambda run_dir: "image")
    monkeypatch.setattr(workflow, "run_candidate", lambda *args, **kwargs: {"status": "PASS", "exit_code": 0})
    monkeypatch.setattr(workflow, "compare_files", lambda *args, **kwargs: {"status": "FAIL", "reasons": ["probability mismatch"], "max_abs_diff": 1.0})

    summary = workflow.run_candidate_fixtures(run_dir, RUN_ID, 0)
    assert summary["status"] == "FAIL"
    result = read_json(run_dir / "migration_result.json")
    assert result["fixture_status"] == "FAIL"
    assert result["dev_status"] == "PASS"
    diagnostics = read_json(run_dir / result["diagnostics_ref"])
    assert diagnostics["contains_raw_rows"] is False
    assert diagnostics["failing_cases"]
    assert repair_diagnostics(run_dir, 1)["fixture_status"] == "FAIL"


# --------------------------------------------------------------------------
# 4. The token ceiling that truncated submit_candidate
# --------------------------------------------------------------------------


class _BudgetProvider:
    def __init__(self, max_output_tokens: int):
        self.config = type("Config", (), {"max_output_tokens": max_output_tokens})()


def test_candidate_stage_refuses_a_truncating_token_ceiling(tmp_path):
    repository = _repository(tmp_path)
    with pytest.raises(ContractError, match="LLM_MAX_OUTPUT_TOKENS"):
        _require_output_budget(repository, _BudgetProvider(8192), "Candidate stage 0")
    _require_output_budget(repository, _BudgetProvider(16384), "Candidate stage 0")
    _require_output_budget(repository, _BudgetProvider(32768), "Candidate stage 0")


def test_stages_without_a_config_object_are_not_blocked(tmp_path):
    repository = _repository(tmp_path)
    _require_output_budget(repository, object(), "inventory")


class _TruncatingProvider:
    def __init__(self):
        self.calls = 0

    def generate(self, messages, tools=None):
        self.calls += 1
        return ProviderResponse(None, (), "length", "req-truncated", "event-truncated")


def test_truncated_output_is_reported_as_truncation_not_as_a_silent_retry(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    provider = _TruncatingProvider()
    with pytest.raises(ContractError, match="finish_reason=length"):
        _run_stage(provider, run_dir, RUN_ID, "candidate-0", [{"role": "user", "content": "go"}], [], lambda name, args: {})
    assert provider.calls == 1
    events = [json.loads(line) for line in (run_dir / "agent_audit_log.jsonl").read_text().splitlines()]
    assert any(event["event"] == "OUTPUT_TRUNCATED" for event in events)
