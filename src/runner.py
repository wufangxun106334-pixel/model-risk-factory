import hashlib
import json
import os
import stat
import subprocess
import time
import uuid
from pathlib import Path


DEFAULT_IMAGE = "model-risk-factory-runner:v1"
_CLEANUP_TIMEOUT_SECONDS = 10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_output_tree(output_dir: Path) -> None:
    if not stat.S_ISDIR(output_dir.lstat().st_mode):
        raise ValueError("output is not a regular directory")
    root = output_dir.resolve(strict=True)
    directories = [output_dir]
    while directories:
        directory = directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    raise ValueError(f"output contains a symbolic link: {path}")
                if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
                    raise ValueError(f"output contains an unsupported file type: {path}")
                resolved = path.resolve(strict=True)
                try:
                    resolved.relative_to(root)
                except ValueError as exc:
                    raise ValueError(
                        f"output entry resolves outside the output directory: {path}"
                    ) from exc
                if stat.S_ISDIR(mode):
                    directories.append(path)


def _mount(source: Path, target: str, read_only: bool) -> str:
    value = f"type=bind,source={source},target={target}"
    if read_only:
        value += ",readonly"
    return value


def hardening_flags() -> tuple[list[str], dict]:
    """Single source of truth for the container boundary (SOP 7.3 / V2-02).

    Both the candidate runner and the boundary probes use these flags so that a
    probe result describes the exact sandbox a candidate runs in.
    """

    flags = [
        "--network",
        "none",
        "--read-only",
        "--user",
        "65532:65532",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--pids-limit",
        "64",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
    ]
    summary = {
        "network": "none",
        "read_only": True,
        "user": "65532:65532",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "memory": "512m",
        "cpus": "1",
        "pids_limit": 64,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
    }
    return flags, summary


def run_candidate(
    candidate_path: Path,
    model_path: Path,
    input_path: Path,
    work_dir: Path,
    timeout_seconds=30,
    image=None,
    docker_binary="docker",
) -> dict:
    started = time.monotonic()
    candidate_path = Path(candidate_path).expanduser().resolve()
    model_path = Path(model_path).expanduser().resolve()
    input_path = Path(input_path).expanduser().resolve()
    work_dir = Path(work_dir).expanduser().resolve()
    output_dir = work_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o777)

    stdout_path = work_dir / "stdout.txt"
    stderr_path = work_dir / "stderr.txt"
    execution_path = work_dir / "execution.json"
    predictions_path = output_dir / "predictions.csv"
    stdout_path.write_bytes(b"")
    stderr_path.write_bytes(b"")
    execution_path.unlink(missing_ok=True)
    if predictions_path.is_symlink() or predictions_path.is_file():
        predictions_path.unlink()

    selected_image = str(image or os.environ.get("MRF_RUNNER_IMAGE") or DEFAULT_IMAGE)
    docker_binary = str(docker_binary)
    container_name = f"mrf-credit-v1-{uuid.uuid4().hex}"
    flags, hardening = hardening_flags()
    candidate_mount = _mount(candidate_path, "/candidate/credit_v1.py", True)
    model_mount = _mount(model_path, "/input/model.json", True)
    input_mount = _mount(input_path, "/input/input.csv", True)
    output_mount = _mount(output_dir, "/output", False)
    candidate_command = [
        "python",
        "/candidate/credit_v1.py",
        "--model",
        "/input/model.json",
        "--input",
        "/input/input.csv",
        "--output",
        "/output/predictions.csv",
    ]
    command = [
        docker_binary,
        "run",
        "--name",
        container_name,
        *flags,
        "--mount",
        candidate_mount,
        "--mount",
        model_mount,
        "--mount",
        input_mount,
        "--mount",
        output_mount,
        selected_image,
        *candidate_command,
    ]
    docker_summary = {
        "docker_binary": docker_binary,
        "container_name": container_name,
        **hardening,
        "mounts": [
            {
                "source": str(candidate_path),
                "target": "/candidate/credit_v1.py",
                "read_only": True,
            },
            {
                "source": str(model_path),
                "target": "/input/model.json",
                "read_only": True,
            },
            {
                "source": str(input_path),
                "target": "/input/input.csv",
                "read_only": True,
            },
            {
                "source": str(output_dir),
                "target": "/output",
                "read_only": False,
            },
        ],
        "environment": {},
        "command": candidate_command,
    }

    hashes = {
        "candidate_sha256": None,
        "model_sha256": None,
        "input_sha256": None,
    }
    status = "EXECUTION_ERROR"
    exit_code = None
    error = None
    cleanup_error = None

    try:
        for key, path in (
            ("candidate_sha256", candidate_path),
            ("model_sha256", model_path),
            ("input_sha256", input_path),
        ):
            hashes[key] = _sha256(path)
    except OSError as exc:
        error = f"input hashing failed: {exc}"

    if error is None:
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                completed = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout_seconds,
                    check=False,
                    env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", "")},
                )
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
            error = f"execution exceeded {timeout_seconds} seconds"
            try:
                cleanup = subprocess.run(
                    [docker_binary, "rm", "-f", container_name],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=_CLEANUP_TIMEOUT_SECONDS,
                    check=False,
                    env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", "")},
                )
                if cleanup.returncode != 0:
                    cleanup_error = (
                        f"docker rm -f exited with code {cleanup.returncode}"
                    )
            except (OSError, subprocess.SubprocessError) as exc:
                cleanup_error = f"docker cleanup failed: {exc}"
        except OSError as exc:
            error = f"docker execution failed: {exc}"
        else:
            exit_code = completed.returncode
            if exit_code != 0:
                error = f"candidate exited with code {exit_code}"

    output_sha256 = None
    output_size = 0
    try:
        _validate_output_tree(output_dir)
    except (OSError, ValueError) as exc:
        status = "EXECUTION_ERROR"
        error = f"unsafe output: {exc}"
    else:
        try:
            prediction_mode = predictions_path.lstat().st_mode
            if stat.S_ISREG(prediction_mode):
                output_size = predictions_path.stat().st_size
                output_sha256 = _sha256(predictions_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            if error is None:
                error = f"output inspection failed: {exc}"

    if status != "TIMEOUT" and exit_code == 0 and error is None:
        if output_sha256 is not None and output_size > 0:
            status = "PASS"
        elif output_sha256 is None:
            error = "predictions.csv is missing or not a regular file"
        else:
            error = "predictions.csv is empty"

    result = {
        "status": status,
        "exit_code": exit_code,
        "duration_seconds": round(time.monotonic() - started, 6),
        "image": selected_image,
        "timeout": timeout_seconds,
        **hashes,
        "docker": docker_summary,
        "output_sha256": output_sha256,
        "error": error,
    }
    if cleanup_error is not None:
        result["cleanup_error"] = cleanup_error
    execution_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
