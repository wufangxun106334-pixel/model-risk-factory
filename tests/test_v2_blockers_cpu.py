"""Release blocker 4: the CPU evidence must distinguish a quota from no quota."""

from __future__ import annotations

from pathlib import Path

from src.boundary import CPU_PROBE, _probe_command, distinguishes_quota
from src.runner import hardening_flags


def test_probe_uses_parallel_load_and_reports_cgroup_evidence():
    assert "WORKERS = 4" in CPU_PROBE
    assert "os.fork()" in CPU_PROBE
    assert "cpu_ratio" in CPU_PROBE
    assert "cgroup_cpu_limit" in CPU_PROBE


def test_probe_command_keeps_the_quota_by_default_and_drops_it_on_request(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("print('x')\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    capped = _probe_command(name="cpu", probe_path=probe, output_dir=output, image="img")
    assert "--cpus" in capped and capped[capped.index("--cpus") + 1] == "1"
    control = _probe_command(name="cpu_control", probe_path=probe, output_dir=output, image="img", drop=("--cpus",))
    assert "--cpus" not in control
    assert "--memory" in control  # the rest of the hardening stays in place
    flags, _ = hardening_flags()
    assert "--cpus" in flags


def test_quota_verdict_requires_a_distinguishable_control():
    assert distinguishes_quota(1.01, 3.8)
    assert not distinguishes_quota(1.01, 1.1)      # no-quota run did not use more cores
    assert not distinguishes_quota(3.0, 3.1)      # capped run was not capped at all
    assert not distinguishes_quota(None, 3.8)     # missing capped measurement
    assert not distinguishes_quota(1.01, None)    # missing control measurement
