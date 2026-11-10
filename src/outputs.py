"""Exclusive creation of files written by read-only commands.

``release-check --output`` and ``compare-command-log --save-copy`` exist to inspect
sealed evidence, so the files they write must never land on top of evidence:

* the destination's parent is resolved (symbolic links included) and must lie
  outside every protected root: formal and dev run directories, the delivery
  directory that holds sealed packages, and the run being inspected;
* the check is repeated on the opened directory itself, by walking its ``..``
  chain by device and inode, so swapping a path component for a link after the
  first check does not move the write into a protected root;
* the file is created with ``O_CREAT | O_EXCL | O_NOFOLLOW`` relative to that
  directory, so an existing file, a hard link to evidence or a symbolic link at
  the destination is refused even if it appears between the check and the write.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class OutputRefused(ValueError):
    """The destination is protected or already exists."""


def _absolute(path: Path) -> Path:
    path = Path(path).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _describe(root: Path, labels: dict[Path, str]) -> str:
    return labels.get(root, str(root))


def _protected(roots: Iterable[Path | tuple[Path, str]]) -> dict[Path, str]:
    resolved: dict[Path, str] = {}
    for entry in roots:
        root, label = entry if isinstance(entry, tuple) else (entry, None)
        target = _absolute(Path(root)).resolve()
        resolved.setdefault(target, label or f"protected directory {target}")
    return resolved


def check_output_destination(destination: Path, protected_roots: Iterable[Path | tuple[Path, str]]) -> Path:
    """Validate a destination before any work is done; return its resolved path."""

    destination = _absolute(Path(destination))
    name = destination.name
    if name in {"", ".", ".."}:
        raise OutputRefused(f"refusing to write {destination}: the destination must name a new file")
    parent = destination.parent.resolve()
    roots = _protected(protected_roots)
    for root, label in roots.items():
        if _inside(parent, root):
            raise OutputRefused(f"refusing to write inside {label}: {parent / name} (choose a new file outside run, dev-run and delivery directories)")
    target = parent / name
    if os.path.lexists(target):
        raise OutputRefused(f"refusing to overwrite an existing path: {target} (outputs are only created as new files)")
    return target


def _directory_identities(roots: dict[Path, str]) -> dict[tuple[int, int], str]:
    identities: dict[tuple[int, int], str] = {}
    for root, label in roots.items():
        try:
            status = os.stat(root)
        except FileNotFoundError:
            continue
        identities[(status.st_dev, status.st_ino)] = label
    return identities


def _refuse_if_under_protected(directory_fd: int, identities: dict[tuple[int, int], str], target: Path) -> None:
    current = os.dup(directory_fd)
    try:
        while True:
            status = os.fstat(current)
            label = identities.get((status.st_dev, status.st_ino))
            if label is not None:
                raise OutputRefused(f"refusing to write inside {label}: {target} (the directory resolved into a protected root)")
            parent = os.open("..", _DIRECTORY_FLAGS, dir_fd=current)
            parent_status = os.fstat(parent)
            if (parent_status.st_dev, parent_status.st_ino) == (status.st_dev, status.st_ino):
                os.close(parent)
                return
            os.close(current)
            current = parent
    finally:
        try:
            os.close(current)
        except OSError:
            pass


def create_new_output(destination: Path, payload: bytes, protected_roots: Iterable[Path | tuple[Path, str]]) -> Path:
    """Create ``destination`` exclusively and write ``payload``; never overwrite."""

    roots = _protected(protected_roots)
    target = check_output_destination(destination, roots.items())
    target.parent.mkdir(parents=True, exist_ok=True)
    directory_fd = os.open(target.parent, _DIRECTORY_FLAGS)
    try:
        _refuse_if_under_protected(directory_fd, _directory_identities(roots), target)
        try:
            handle = os.open(target.name, _CREATE_FLAGS, 0o644, dir_fd=directory_fd)
        except FileExistsError as error:
            raise OutputRefused(f"refusing to overwrite an existing path: {target} (outputs are only created as new files)") from error
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            os.unlink(target.name, dir_fd=directory_fd)
            raise
    finally:
        os.close(directory_fd)
    return target
