import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest

from src import runner


class FakeSubprocess:
    def __init__(self, handler=None):
        self.handler = handler
        self.calls = []

    def run(self, command, **kwargs):
        command = list(command)
        self.calls.append((command, kwargs))
        if self.handler is not None:
            return self.handler(command, kwargs)
        if command[1:2] == ["rm"]:
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(command, 0)


def make_assets(tmp_path: Path):
    candidate = tmp_path / "candidate.py"
    model = tmp_path / "model.json"
    input_csv = tmp_path / "input.csv"
    candidate.write_text(
        "raise RuntimeError('candidate must not execute on the host')\n",
        encoding="utf-8",
    )
    model.write_text('{"intercept": 0}\n', encoding="utf-8")
    input_csv.write_text("id,value\n1,2\n", encoding="utf-8")
    return candidate, model, input_csv, tmp_path / "run"


def option(command, name):
    return command[command.index(name) + 1]


def mounts(command):
    return [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--mount"
    ]


def sha256(data: bytes):
    return hashlib.sha256(data).hexdigest()


def test_success_has_all_isolation_settings_and_evidence(tmp_path, monkeypatch):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    predictions = work_dir / "output" / "predictions.csv"
    output_data = b"id,probability\n1,0.25\n"

    def handler(command, kwargs):
        kwargs["stdout"].write(b"candidate stdout\n")
        kwargs["stderr"].write(b"candidate stderr\n")
        predictions.write_bytes(output_data)
        return subprocess.CompletedProcess(command, 0)

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)
    monkeypatch.setenv("LLM_API_KEY", "must-not-be-forwarded")
    monkeypatch.delenv("MRF_RUNNER_IMAGE", raising=False)

    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "PASS"
    assert result["exit_code"] == 0
    assert result["image"] == "model-risk-factory-runner:v1"
    assert result["timeout"] == 30
    assert result["duration_seconds"] >= 0
    assert result["candidate_sha256"] == sha256(candidate.read_bytes())
    assert result["model_sha256"] == sha256(model.read_bytes())
    assert result["input_sha256"] == sha256(input_csv.read_bytes())
    assert result["output_sha256"] == sha256(output_data)
    assert result["error"] is None

    assert len(fake.calls) == 1
    command, kwargs = fake.calls[0]
    assert command[0] == "docker"
    assert command[1] == "run"
    container_name = option(command, "--name")
    assert container_name.startswith("mrf-credit-v1-")
    assert option(command, "--network") == "none"
    assert "--read-only" in command
    assert option(command, "--user") == "65532:65532"
    assert option(command, "--cap-drop") == "ALL"
    assert option(command, "--security-opt") == "no-new-privileges"
    assert option(command, "--memory") == "512m"
    assert option(command, "--cpus") == "1"
    assert option(command, "--pids-limit") == "64"
    assert option(command, "--tmpfs") == "/tmp:rw,noexec,nosuid,size=16m"

    assert mounts(command) == [
        f"type=bind,source={candidate.resolve()},target=/candidate/credit_v1.py,readonly",
        f"type=bind,source={model.resolve()},target=/input/model.json,readonly",
        f"type=bind,source={input_csv.resolve()},target=/input/input.csv,readonly",
        f"type=bind,source={(work_dir / 'output').resolve()},target=/output",
    ]
    assert command[command.index("model-risk-factory-runner:v1") + 1 :] == [
        "python",
        "/candidate/credit_v1.py",
        "--model",
        "/input/model.json",
        "--input",
        "/input/input.csv",
        "--output",
        "/output/predictions.csv",
    ]
    assert not {"-e", "--env", "--env-file", "--privileged"}.intersection(command)
    assert all("must-not-be-forwarded" not in value for value in command)
    assert all("docker.sock" not in value for value in command)
    assert set(kwargs["env"]) == {"PATH", "HOME"}
    assert "LLM_API_KEY" not in kwargs["env"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["timeout"] == 30
    assert kwargs["check"] is False
    assert result["docker"]["environment"] == {}
    assert result["docker"]["container_name"] == container_name
    assert [mount["read_only"] for mount in result["docker"]["mounts"]] == [
        True,
        True,
        True,
        False,
    ]

    assert (work_dir / "stdout.txt").read_bytes() == b"candidate stdout\n"
    assert (work_dir / "stderr.txt").read_bytes() == b"candidate stderr\n"
    assert stat.S_IMODE((work_dir / "output").stat().st_mode) == 0o777
    execution = json.loads((work_dir / "execution.json").read_text(encoding="utf-8"))
    assert execution == result


def test_image_override_and_unique_container_names(tmp_path, monkeypatch):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    fake = FakeSubprocess()
    monkeypatch.setattr(runner.subprocess, "run", fake.run)
    monkeypatch.setenv("MRF_RUNNER_IMAGE", "registry.example/runner:test")

    first = runner.run_candidate(candidate, model, input_csv, work_dir)
    second = runner.run_candidate(
        candidate,
        model,
        input_csv,
        tmp_path / "second-run",
        image="explicit-image:v1",
        docker_binary="/custom/docker",
    )

    assert first["image"] == "registry.example/runner:test"
    assert second["image"] == "explicit-image:v1"
    assert fake.calls[0][0][0] == "docker"
    assert fake.calls[1][0][0] == "/custom/docker"
    first_name = first["docker"]["container_name"]
    second_name = second["docker"]["container_name"]
    assert first_name != second_name
    assert option(fake.calls[0][0], "--name") == first_name
    assert option(fake.calls[1][0], "--name") == second_name


def test_timeout_force_removes_same_container_before_recording(tmp_path, monkeypatch):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    execution_path = work_dir / "execution.json"
    cleanup_observations = []

    def handler(command, kwargs):
        if command[1:2] == ["rm"]:
            cleanup_observations.append(execution_path.exists())
            return subprocess.CompletedProcess(command, 0)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)

    result = runner.run_candidate(
        candidate,
        model,
        input_csv,
        work_dir,
        timeout_seconds=0.25,
    )

    assert result["status"] == "TIMEOUT"
    assert result["exit_code"] is None
    assert result["timeout"] == 0.25
    assert len(fake.calls) == 2
    run_command = fake.calls[0][0]
    cleanup_command, cleanup_kwargs = fake.calls[1]
    container_name = option(run_command, "--name")
    assert cleanup_command == ["docker", "rm", "-f", container_name]
    assert set(cleanup_kwargs["env"]) == {"PATH", "HOME"}
    assert "LLM_API_KEY" not in cleanup_kwargs["env"]
    assert cleanup_observations == [False]
    assert execution_path.is_file()
    assert json.loads(execution_path.read_text(encoding="utf-8"))["status"] == "TIMEOUT"
    assert (work_dir / "stdout.txt").is_file()
    assert (work_dir / "stderr.txt").is_file()


@pytest.mark.parametrize(
    ("returncode", "output_data", "expected_exit_code"),
    [
        (0, None, 0),
        (0, b"", 0),
        (9, b"id,probability\n1,0.9\n", 9),
    ],
)
def test_missing_empty_or_failed_output_is_execution_error(
    tmp_path,
    monkeypatch,
    returncode,
    output_data,
    expected_exit_code,
):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    predictions = work_dir / "output" / "predictions.csv"

    def handler(command, kwargs):
        if output_data is not None:
            predictions.write_bytes(output_data)
        return subprocess.CompletedProcess(command, returncode)

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)

    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert result["exit_code"] == expected_exit_code
    assert result["error"] is not None
    if output_data is None:
        assert result["output_sha256"] is None
    else:
        assert result["output_sha256"] == sha256(output_data)
    assert json.loads((work_dir / "execution.json").read_text()) == result


def test_stale_output_cannot_turn_no_output_run_into_pass(tmp_path, monkeypatch):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    predictions = work_dir / "output" / "predictions.csv"
    predictions.parent.mkdir(parents=True)
    predictions.write_bytes(b"stale predictions\n")
    fake = FakeSubprocess()
    monkeypatch.setattr(runner.subprocess, "run", fake.run)

    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert result["output_sha256"] is None
    assert not predictions.exists()


def test_docker_unavailable_is_recorded_as_execution_error(tmp_path, monkeypatch):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)

    def handler(command, kwargs):
        raise FileNotFoundError(2, "docker not found")

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)

    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert result["exit_code"] is None
    assert "docker not found" in result["error"]
    assert result["output_sha256"] is None
    assert len(fake.calls) == 1
    assert json.loads((work_dir / "execution.json").read_text()) == result


def test_missing_input_never_invokes_docker_and_still_writes_record(
    tmp_path, monkeypatch
):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    input_csv.unlink()
    fake = FakeSubprocess()
    monkeypatch.setattr(runner.subprocess, "run", fake.run)

    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert result["candidate_sha256"] == sha256(candidate.read_bytes())
    assert result["model_sha256"] == sha256(model.read_bytes())
    assert result["input_sha256"] is None
    assert result["error"] is not None
    assert fake.calls == []
    assert (work_dir / "output").is_dir()
    assert (work_dir / "stdout.txt").is_file()
    assert (work_dir / "stderr.txt").is_file()
    assert json.loads((work_dir / "execution.json").read_text()) == result


def test_extra_output_symlink_fails_without_reading_link_or_predictions(
    tmp_path, monkeypatch
):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    secret = tmp_path / "host_secret_placeholder.txt"
    secret.write_text("HOST_SECRET_PLACEHOLDER\n", encoding="utf-8")
    predictions = work_dir / "output" / "predictions.csv"
    link = work_dir / "output" / "nested" / "leak.txt"

    def handler(command, kwargs):
        predictions.write_bytes(b"id,probability\n1,0.25\n")
        link.parent.mkdir()
        link.symlink_to(secret)
        return subprocess.CompletedProcess(command, 0)

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path in {link, secret}:
            raise AssertionError("output validation attempted to read a link target")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert "symbolic link" in result["error"]
    assert result["output_sha256"] is None
    assert "HOST_SECRET_PLACEHOLDER" not in (
        work_dir / "execution.json"
    ).read_text(encoding="utf-8")


def test_predictions_symlink_is_rejected_without_reading_target(tmp_path, monkeypatch):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    secret = tmp_path / "host_secret_placeholder.txt"
    secret.write_text("HOST_SECRET_PLACEHOLDER\n", encoding="utf-8")
    predictions = work_dir / "output" / "predictions.csv"

    def handler(command, kwargs):
        predictions.symlink_to(secret)
        return subprocess.CompletedProcess(command, 0)

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path in {predictions, secret}:
            raise AssertionError("predictions symlink target must not be read")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert "symbolic link" in result["error"]
    assert result["output_sha256"] is None


def test_output_directory_symlink_is_rejected(tmp_path, monkeypatch):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "host_secret_placeholder.txt").write_text(
        "HOST_SECRET_PLACEHOLDER\n", encoding="utf-8"
    )
    predictions = work_dir / "output" / "predictions.csv"
    link = work_dir / "output" / "linked-directory"

    def handler(command, kwargs):
        predictions.write_bytes(b"id,probability\n1,0.25\n")
        link.symlink_to(outside, target_is_directory=True)
        return subprocess.CompletedProcess(command, 0)

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)
    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert "symbolic link" in result["error"]
    assert result["output_sha256"] is None


def test_output_fifo_is_rejected_without_opening_it(tmp_path, monkeypatch):
    import os

    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    predictions = work_dir / "output" / "predictions.csv"

    def handler(command, kwargs):
        predictions.write_bytes(b"id,probability\n1,0.25\n")
        os.mkfifo(work_dir / "output" / "blocking-fifo")
        return subprocess.CompletedProcess(command, 0)

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)
    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "EXECUTION_ERROR"
    assert "unsupported file type" in result["error"]
    assert result["output_sha256"] is None


def test_nested_regular_output_directories_and_files_are_allowed(
    tmp_path, monkeypatch
):
    candidate, model, input_csv, work_dir = make_assets(tmp_path)
    predictions = work_dir / "output" / "predictions.csv"
    output_data = b"id,probability\n1,0.25\n"

    def handler(command, kwargs):
        predictions.write_bytes(output_data)
        nested = work_dir / "output" / "diagnostics" / "nested"
        nested.mkdir(parents=True)
        (nested / "notes.txt").write_text("ordinary diagnostics\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    fake = FakeSubprocess(handler)
    monkeypatch.setattr(runner.subprocess, "run", fake.run)
    result = runner.run_candidate(candidate, model, input_csv, work_dir)

    assert result["status"] == "PASS"
    assert result["output_sha256"] == sha256(output_data)
