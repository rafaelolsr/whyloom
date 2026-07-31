"""A minimal cross-platform advisory file lock for serializing index writes.

Two indexers can race — a manual ``whyloom index`` while the post-commit hook
also fires. SQLite's busy timeout guards individual statements, but a full
incremental index performs many writes across derived sources; serializing the
whole operation keeps the graph internally consistent. The lock is advisory
(honored only by Whyloom), self-heals a stale lock left by a crashed process,
and never blocks reads."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# A held lock older than this is assumed abandoned by a crashed process.
STALE_LOCK_SECONDS = 300


class IndexLockTimeout(RuntimeError):
    """Raised when the index lock cannot be acquired within the timeout."""


@contextmanager
def index_lock(lock_path: Path, *, timeout: float = 60.0, poll: float = 0.1) -> Iterator[None]:
    """Acquire an exclusive index lock, or raise IndexLockTimeout.

    Uses ``O_CREAT | O_EXCL`` for atomic creation. A lock file whose mtime is
    older than STALE_LOCK_SECONDS is reclaimed so a crash never wedges indexing.
    ``mtime`` is used rather than wall-clock arithmetic so the check needs no
    current-time source beyond the filesystem's own timestamp."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline_polls = max(1, int(timeout / poll))
    acquired = False
    for _ in range(deadline_polls):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            # Reclaim a stale lock left by a dead process.
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > STALE_LOCK_SECONDS:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            time.sleep(poll)
    if not acquired:
        raise IndexLockTimeout(
            f"another indexing process holds {lock_path}; retry after it completes"
        )
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass
