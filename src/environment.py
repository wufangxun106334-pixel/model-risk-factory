from __future__ import annotations

import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from src.common import read_json, sha256_file, utc_now, write_json


def _command(command: list[str]) -> dict:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        return {"exit_code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.SubprocessError) as error:
        return {"exit_code": None, "error": str(error)}


def capture_environment(run_dir: Path) -> dict:
    repository = run_dir.parent.parent
    requirements = []
    for line in (repository / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name, expected = line.split("==", 1)
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        requirements.append({"package": name, "expected": expected, "installed": installed, "match": installed == expected})
    images = {}
    for name in ("rocker/r-ver:4.4.2", "model-risk-factory-runner:v1"):
        images[name] = _command(["docker", "image", "inspect", name, "--format", "{{json .RepoDigests}}|{{.Id}}"])
    payload = {
        "schema_version": "1",
        "run_id": read_json(run_dir / "run_manifest.json")["run_id"] if (run_dir / "run_manifest.json").is_file() else None,
        "captured_at": utc_now(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "rscript_on_host": shutil.which("Rscript"),
        "docker_version": _command(["docker", "version", "--format", "{{.Client.Version}}|{{.Server.Version}}"]),
        "images": images,
        "requirements_sha256": sha256_file(repository / "requirements.txt"),
        "requirements": requirements,
        "environment_variables_collected": False,
    }
    write_json(run_dir / "environment.json", payload)
    return payload
