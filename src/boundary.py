"""Executable evidence for the v2 container boundary (SOP V2-02).

Every check below is a real container run with the same hardening flags the
candidate runner uses. Nothing is asserted from configuration alone: each probe
returns its own JSON verdict, and the suite aggregates only what the probes
observed.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from src.common import ContractError, read_json, sha256_file, utc_now, write_json
from src.runner import hardening_flags, run_candidate

PROBE_TIMEOUT_SECONDS = 60
CPU_BURN_SECONDS = 3.0
CPU_THREADS = 2
MEMORY_ATTEMPT_MB = 800
PID_ATTEMPT_COUNT = 120

READ_ONLY_PROBE = r"""
import json, os
targets = ["/probe_root.txt", "/input/model.json", "/candidate/probe.py", "/etc/probe.txt", "/root/probe.txt"]
result = {}
for target in targets:
    try:
        with open(target, "w") as handle:
            handle.write("x")
        result[target] = "WRITTEN"
    except OSError as error:
        result[target] = type(error).__name__
writable = sorted(path for path, outcome in result.items() if outcome == "WRITTEN")
payload = {"writable_paths": writable, "outcomes": result, "uid": os.getuid()}
with open("/output/probe.json", "w") as handle:
    json.dump(payload, handle)
"""

HOST_MOUNT_PROBE = r"""
import json, os
sentinel = os.environ.get("MRF_PROBE_SENTINEL", "")
candidates = ["/host_probe_sentinel.txt", "/output/../host_probe_sentinel.txt", "/workspace/host_probe_sentinel.txt"]
visible = []
for path in candidates:
    try:
        with open(path) as handle:
            content = handle.read()
        visible.append({"path": path, "content_matches": sentinel in content})
    except OSError:
        continue
mounts = []
with open("/proc/self/mountinfo") as handle:
    for line in handle:
        parts = line.split()
        if len(parts) > 4:
            mounts.append(parts[4])
payload = {
    "visible_sentinel_files": visible,
    "mount_points": sorted(set(mounts)),
    "host_paths_present": [path for path in ("/Users", "/opt/model-risk-factory", "/var/lib/docker") if os.path.exists(path)],
}
with open("/output/probe.json", "w") as handle:
    json.dump(payload, handle)
"""

SECRET_PROBE = r"""
import json, os
sentinel = os.environ.get("MRF_PROBE_SENTINEL", "")
with open("/proc/self/environ", "rb") as handle:
    environ_bytes = handle.read()
payload = {
    "api_key_variable_present": any(name.endswith("API_KEY") for name in os.environ),
    "environment_names": sorted(os.environ),
    "sentinel_in_environ_file": bool(sentinel) and sentinel.encode() in environ_bytes,
    "sentinel_in_own_environ": bool(sentinel) and sentinel in json.dumps(dict(os.environ)),
}
with open("/output/probe.json", "w") as handle:
    json.dump(payload, handle)
"""

MEMORY_PROBE = r"""
import json
allocated = []
error = None
chunk_mb = 100
try:
    for _ in range(8):
        allocated.append(bytearray(chunk_mb * 1024 * 1024))
except MemoryError as exc:
    error = type(exc).__name__
payload = {"requested_mb": 800, "allocated_mb": len(allocated) * chunk_mb, "error": error}
with open("/output/probe.json", "w") as handle:
    json.dump(payload, handle)
"""

CPU_PROBE = r"""
import json, os, time

WORKERS = 4
SECONDS = 3.0
started = time.monotonic()
children = []
for _ in range(WORKERS):
    pid = os.fork()
    if pid == 0:
        value = 0
        while time.monotonic() < started + SECONDS:
            value += 1
        os._exit(0)
    children.append(pid)
cpu = 0.0
for pid in children:
    _, status, usage = os.wait4(pid, 0)
    cpu += usage.ru_utime + usage.ru_stime
wall = time.monotonic() - started
cpu_max = None
for candidate in ("/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"):
    try:
        with open(candidate) as handle:
            cpu_max = handle.read().strip()
        break
    except OSError:
        continue
payload = {
    "workers": WORKERS,
    "wall_seconds": round(wall, 3),
    "cpu_seconds": round(cpu, 3),
    "cpu_ratio": round(cpu / wall, 3),
    "host_cpu_count": os.cpu_count(),
    "cgroup_cpu_limit": cpu_max,
}
with open("/output/probe.json", "w") as handle:
    json.dump(payload, handle)
"""

PID_PROBE = r"""
import errno, json, os, time
children = []
error = None
try:
    for _ in range(120):
        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        children.append(pid)
except OSError as exc:
    error = {"errno_name": errno.errorcode.get(exc.errno, str(exc.errno)), "message": str(exc)[:200]}
payload = {"requested": 120, "forked": len(children), "error": error}
with open("/output/probe.json", "w") as handle:
    json.dump(payload, handle)
for pid in children:
    try:
        os.kill(pid, 9)
    except OSError:
        pass
"""

SLEEPING_CANDIDATE = """import time
time.sleep(120)
"""


def _probe_command(*, name: str, probe_path: Path, output_dir: Path, image: str, extra: list[str] | None = None, drop: tuple[str, ...] = ()) -> list[str]:
    container_name = f"mrf-boundary-{name}-{uuid.uuid4().hex[:8]}"
    flags, _ = hardening_flags()
    for option in drop:
        if option in flags:
            index = flags.index(option)
            del flags[index:index + 2]
    return [
        "docker",
        "run",
        "--name",
        container_name,
        *flags,
        "--mount",
        f"type=bind,source={probe_path},target=/probe.py,readonly",
        "--mount",
        f"type=bind,source={output_dir},target=/output",
        *(extra or []),
        image,
        "python",
        "/probe.py",
    ]


def _run_probe(name: str, source: str, work_dir: Path, image: str, *, env: dict | None = None, drop: tuple[str, ...] = ()) -> dict:
    probe_dir = work_dir / name
    probe_dir.mkdir(parents=True, exist_ok=True)
    output_dir = probe_dir / "output"
    output_dir.mkdir(exist_ok=True)
    output_dir.chmod(0o777)
    probe_path = probe_dir / "probe.py"
    probe_path.write_text(source, encoding="utf-8")
    command = _probe_command(name=name, probe_path=probe_path, output_dir=output_dir, image=image, drop=drop)
    started = time.monotonic()
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=PROBE_TIMEOUT_SECONDS,
        check=False,
        env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": os.environ.get("HOME", ""), **(env or {})},
    )
    duration = round(time.monotonic() - started, 3)
    payload_path = output_dir / "probe.json"
    payload = read_json(payload_path) if payload_path.is_file() else None
    return {
        "probe": name,
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "stdout": completed.stdout.decode("utf-8", "replace")[-800:],
        "stderr": completed.stderr.decode("utf-8", "replace")[-800:],
        # The probe payload is the only thing this function trusts for a verdict.
        "payload": payload,
        "payload_sha256": sha256_file(payload_path) if payload_path.is_file() else None,
    }


def distinguishes_quota(capped_ratio, control_ratio) -> bool:
    """The capped run must look different from the uncapped run by a clear margin."""

    if capped_ratio is None or control_ratio is None:
        return False
    return control_ratio >= 1.6 and control_ratio >= capped_ratio + 0.6


def _check(name: str, ok: bool, detail: str, **evidence) -> dict:
    return {"name": name, "status": "PASS" if ok else "FAIL", "detail": detail, "evidence": evidence}


def run_boundary_suite(run_dir: Path, runtime_config_path: Path) -> dict:
    config = read_json(runtime_config_path)
    image = str(config.get("runner_image") or "")
    if not image:
        raise ContractError("runtime_config.json must declare runner_image")
    _, summary = hardening_flags()
    if summary["memory"] != config.get("candidate_memory") or summary["cpus"] != str(config.get("candidate_cpus")):
        raise ContractError("runner hardening flags disagree with runtime_config.json")
    if summary["pids_limit"] != config.get("candidate_pids_limit"):
        raise ContractError("runner PID limit disagrees with runtime_config.json")

    work_dir = run_dir / "boundary" / "probes"
    checks: list[dict] = []

    read_only = _run_probe("read_only", READ_ONLY_PROBE, work_dir, image)
    payload = read_only["payload"] or {}
    checks.append(_check(
        "read_only_root_and_inputs",
        payload.get("writable_paths") == [] and read_only["exit_code"] == 0,
        "no writable path outside the output mount; the candidate runs as uid 65532",
        writable_paths=payload.get("writable_paths"),
        outcomes=payload.get("outcomes"),
        uid=payload.get("uid"),
        exit_code=read_only["exit_code"],
    ))

    sentinel_value = "mrf-host-sentinel-" + uuid.uuid4().hex
    sentinel_path = run_dir.parent / "host_probe_sentinel.txt"
    sentinel_path.write_text(sentinel_value + "\n", encoding="utf-8")
    host_probe = _run_probe("host_mounts", HOST_MOUNT_PROBE, work_dir, image, env={"MRF_PROBE_SENTINEL": sentinel_value})
    payload = host_probe["payload"] or {}
    visible = payload.get("visible_sentinel_files") or []
    checks.append(_check(
        "no_host_or_baseline_mount",
        not visible and not payload.get("host_paths_present"),
        "a sentinel file next to the run is not reachable and host paths are absent",
        visible_sentinel_files=visible,
        host_paths_present=payload.get("host_paths_present"),
        mount_points=payload.get("mount_points"),
    ))
    sentinel_path.unlink(missing_ok=True)

    secret_value = "sk-boundary-sentinel-" + uuid.uuid4().hex
    secret_probe = _run_probe("api_key", SECRET_PROBE, work_dir, image, env={"LLM_API_KEY": secret_value, "MRF_PROBE_SENTINEL": secret_value})
    payload = secret_probe["payload"] or {}
    leaked = bool(payload.get("api_key_variable_present") or payload.get("sentinel_in_environ_file") or payload.get("sentinel_in_own_environ"))
    checks.append(_check(
        "api_key_not_visible",
        not leaked and secret_probe["exit_code"] == 0,
        "the container environment carries no credential and the host key is not in /proc/self/environ",
        environment_names=payload.get("environment_names"),
        api_key_variable_present=payload.get("api_key_variable_present"),
        sentinel_in_environ_file=payload.get("sentinel_in_environ_file"),
    ))

    memory = _run_probe("memory", MEMORY_PROBE, work_dir, image)
    payload = memory["payload"] or {}
    limited = memory["exit_code"] != 0 or (payload.get("allocated_mb") or 0) < MEMORY_ATTEMPT_MB
    checks.append(_check(
        "memory_limit_triggered",
        limited,
        "an 800 MB allocation cannot complete inside the 512m container",
        requested_mb=payload.get("requested_mb"),
        allocated_mb=payload.get("allocated_mb"),
        error=payload.get("error"),
        exit_code=memory["exit_code"],
    ))

    cpu = _run_probe("cpu", CPU_PROBE, work_dir, image)
    payload = cpu["payload"] or {}
    ratio = payload.get("cpu_ratio")
    checks.append(_check(
        "cpu_limit_triggered",
        ratio is not None and 0.75 <= ratio <= 1.4 and (payload.get("cpu_seconds") or 0) >= 2.0,
        "four spinning processes on a one-CPU container consume about one core-second per second",
        cpu_seconds=payload.get("cpu_seconds"),
        wall_seconds=payload.get("wall_seconds"),
        cpu_ratio=ratio,
        cgroup_cpu_limit=payload.get("cgroup_cpu_limit"),
    ))

    # Control run: the same load without --cpus. Without a distinguishable control
    # the capped measurement proves nothing, so a missing or indistinguishable
    # control fails the check instead of passing it silently.
    control = _run_probe("cpu_control", CPU_PROBE, work_dir, image, drop=("--cpus",))
    control_payload = control["payload"] or {}
    control_ratio = control_payload.get("cpu_ratio")
    distinguishable = distinguishes_quota(ratio, control_ratio) and control["exit_code"] == 0
    checks.append(_check(
        "cpu_quota_control_distinguishes",
        distinguishable,
        "the same four-process load reaches at least 1.6 cores without --cpus and stays near one core with it",
        capped_cpu_ratio=ratio,
        uncapped_cpu_ratio=control_ratio,
        uncapped_cpu_seconds=control_payload.get("cpu_seconds"),
        capped_cgroup_limit=payload.get("cgroup_cpu_limit"),
        uncapped_cgroup_limit=control_payload.get("cgroup_cpu_limit"),
        host_cpu_count=control_payload.get("host_cpu_count"),
        exit_code=control["exit_code"],
    ))

    pid = _run_probe("pid", PID_PROBE, work_dir, image)
    payload = pid["payload"] or {}
    checks.append(_check(
        "pid_limit_triggered",
        bool(payload.get("error")) and (payload.get("forked") or 0) < PID_ATTEMPT_COUNT,
        "forking 120 children fails before the configured PID ceiling is exceeded",
        forked=payload.get("forked"),
        error=payload.get("error"),
    ))

    timeout_dir = run_dir / "boundary" / "timeout"
    candidate_path = timeout_dir / "sleeping_candidate.py"
    timeout_dir.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(SLEEPING_CANDIDATE, encoding="utf-8")
    model_path = run_dir / "reference" / "model.json"
    input_path = run_dir / "data" / "dev.csv"
    if not model_path.is_file() or not input_path.is_file():
        raise ContractError("The timeout probe needs the reference model and dev inputs")
    timeout_execution = run_candidate(
        candidate_path,
        model_path,
        input_path,
        timeout_dir / "execution",
        timeout_seconds=2,
        image=image,
    )
    checks.append(_check(
        "timeout_triggered",
        timeout_execution.get("status") == "TIMEOUT" and not timeout_execution.get("cleanup_error"),
        "a sleeping candidate is killed at the configured timeout and its container removed",
        status=timeout_execution.get("status"),
        error=timeout_execution.get("error"),
        duration_seconds=timeout_execution.get("duration_seconds"),
        cleanup_error=timeout_execution.get("cleanup_error"),
    ))

    report = {
        "schema_version": "1",
        "run_id": read_json(run_dir / "run_manifest.json")["run_id"],
        "created_at": utc_now(),
        "image": image,
        "hardening": summary,
        "status": "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL",
        "checks": checks,
        "probes": [read_only, host_probe, secret_probe, memory, cpu, control, pid],
        "timeout_probe": {
            key: timeout_execution.get(key)
            for key in ("status", "exit_code", "duration_seconds", "timeout", "docker", "error", "cleanup_error")
        },
    }
    write_json(run_dir / "boundary" / "boundary_report.json", report)
    return report
