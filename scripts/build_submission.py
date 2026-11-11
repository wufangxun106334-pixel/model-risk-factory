"""Build the offline judge package: the five deliverables in one zip.

The repository is private, so judges may not be able to open it. This bundles
the committed deliverables (no run artifacts, no data, no secrets) into
``dist/model-risk-factory-submission-<sha>.zip`` with a MANIFEST.md listing each
file's SHA-256 and the source commit.

Usage:
    .venv/bin/python scripts/build_submission.py [--allow-dirty]

It refuses to build if a packaged file has uncommitted changes (unless
--allow-dirty), if a file is missing, or if a text file contains something that
looks like a secret or a local absolute path.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]

# (path in repo, deliverable it belongs to)
FILES = [
    ("materials/solution_deck.pdf", "1 Solution deck"),
    ("materials/solution_deck.pptx", "1 Solution deck"),
    ("materials/demo_video.mp4", "2 Demo video"),
    ("materials/demo_video_script.md", "2 Demo video"),
    ("README.md", "3 Code repository + README"),
    ("docs/v3/test_summary.md", "3 Code repository + README"),
    ("materials/architecture.png", "4 Architecture diagram"),
    ("materials/architecture.svg", "4 Architecture diagram"),
    ("materials/architecture.md", "4 Architecture diagram"),
    ("materials/responsible_ai_note.pdf", "5 Responsible AI note"),
    ("materials/responsible_ai_note.md", "5 Responsible AI note"),
    ("materials/impact_measurements.csv", "Supporting: business-value evidence"),
    ("materials/impact_measurements_README.md", "Supporting: business-value evidence"),
    ("materials/submission_checklist.md", "Supporting: submission checklist"),
]

TEXT_SUFFIXES = {".md", ".csv", ".svg"}
FORBIDDEN = [
    (re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"), "local absolute path"),
    (re.compile(r"/private/tmp/"), "local absolute path"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub token"),
    (re.compile(r"(?i)\b(?:api_key|apikey|secret|password)\s*[=:]\s*['\"]?[A-Za-z0-9/+_-]{12,}"), "credential assignment"),
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPOSITORY, check=True, capture_output=True, text=True).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan(path: Path) -> list[str]:
    if path.suffix not in TEXT_SUFFIXES:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return [f"{label}: {match.group(0)[:40]!r}" for pattern, label in FORBIDDEN for match in pattern.finditer(text)]


def build(allow_dirty: bool) -> Path:
    problems: list[str] = []
    for name, _ in FILES:
        if not (REPOSITORY / name).is_file():
            problems.append(f"missing: {name}")
    if problems:
        raise SystemExit("\n".join(problems))

    dirty = git("status", "--porcelain", "--", *[name for name, _ in FILES])
    if dirty and not allow_dirty:
        raise SystemExit(f"packaged files have uncommitted changes:\n{dirty}")
    for name, _ in FILES:
        problems += [f"{name}: {finding}" for finding in scan(REPOSITORY / name)]
    if problems:
        raise SystemExit("refusing to package:\n" + "\n".join(problems))

    commit = git("rev-parse", "HEAD")
    short = commit[:7] + ("-dirty" if dirty else "")
    rows = "\n".join(
        f"| {group} | `{name}` | {(REPOSITORY / name).stat().st_size:,} | `{sha256(REPOSITORY / name)}` |"
        for name, group in FILES
    )
    manifest = f"""# Model Risk Factory: offline submission package

Challenge 04 · EXL × UCD Data & AI Hackathon 2026

- Source commit: `{commit}`{" (with uncommitted changes)" if dirty else ""}
- Repository: https://github.com/wufangxun106334-pixel/model-risk-factory
  (private; this package lets judges review the deliverables without repository access)
- Start with `README.md`, then `materials/solution_deck.pdf` and `materials/demo_video.mp4`.
- Every number is labelled with its source (`SYN-SEED47`, `HIST-UCI`, `CLIENT-CONTEXT`, `PENDING`).
  Paired manual timings (T11–T15) are still pending, so no speed-up percentage is claimed.

| Deliverable | File | Bytes | SHA-256 |
| --- | --- | ---: | --- |
{rows}

Verify a file: `shasum -a 256 <file>` should print the value above.
"""
    out_dir = REPOSITORY / "dist"
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"model-risk-factory-submission-{short}.zip"
    root = "model-risk-factory-submission"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(f"{root}/MANIFEST.md", manifest)
        for name, _ in FILES:
            bundle.write(REPOSITORY / name, f"{root}/{name}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--allow-dirty", action="store_true", help="package uncommitted versions of the files")
    target = build(parser.parse_args().allow_dirty)
    print(f"{target.relative_to(REPOSITORY)}  {target.stat().st_size:,} bytes  sha256={sha256(target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
