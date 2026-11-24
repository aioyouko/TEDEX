"""Safe concurrent access to the lab metadata in data/lab/.

Several commands read data/lab/*.json and lab_metadata.md, change them, and
write them back (analyze, sync metadata, sync markdown, sync workbook, sync
fill). Run at the same time, two of them could each read the old files and
the second write would silently drop the first one's change. Two tools stop
that:

- ``lab_lock(lab_dir)`` is a cross-process lock that every read-modify-write
  holds. Other commands wait their turn (up to TE_LAB_LOCK_TIMEOUT seconds,
  default 120). The operating system releases it if the process dies, so a
  crash never leaves a stale lock. The lock lives in the system temp folder,
  keyed by the lab folder's path, so OneDrive never syncs it. It coordinates
  commands on one computer only.
- ``atomic_write_text(path, text)`` writes through a temporary file and swaps
  it in, so a command that reads without the lock (plot-te, assess) never sees
  a half-written file.

A process that holds the lock marks it in its environment, so child processes
it starts (analyze runs the Markdown sync as one) and nested calls in the
same process go straight through instead of waiting on themselves.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

HELD_ENV_VAR = "TE_LAB_LOCK_HELD"
TIMEOUT_ENV_VAR = "TE_LAB_LOCK_TIMEOUT"
DEFAULT_TIMEOUT = 120.0
POLL_SECONDS = 0.2


class LabLockTimeout(RuntimeError):
    """Another command kept data/lab locked for longer than the timeout."""


def lock_path(lab_dir: str | os.PathLike[str]) -> Path:
    key = hashlib.sha1(str(Path(lab_dir).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"te_lab_{key}.lock"


def _try_lock(handle) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def lab_lock(lab_dir: str | os.PathLike[str], timeout: float | None = None):
    """Hold the data/lab lock for the duration of the block."""
    path = lock_path(lab_dir)
    if os.environ.get(HELD_ENV_VAR) == str(path):
        yield  # this process, or the parent that started it, already holds it
        return

    if timeout is None:
        timeout = float(os.environ.get(TIMEOUT_ENV_VAR, DEFAULT_TIMEOUT))
    handle = open(path, "a+b")
    deadline = time.monotonic() + timeout
    announced = False
    while not _try_lock(handle):
        if time.monotonic() >= deadline:
            handle.close()
            raise LabLockTimeout(
                f"another command has been updating {lab_dir} for over {timeout:g} s; "
                f"try again when it finishes (lock file: {path})"
            )
        if not announced:
            print(f"Waiting for another command to finish updating {lab_dir}...", file=sys.stderr, flush=True)
            announced = True
        time.sleep(POLL_SECONDS)

    os.environ[HELD_ENV_VAR] = str(path)
    try:
        yield
    finally:
        os.environ.pop(HELD_ENV_VAR, None)
        _unlock(handle)
        handle.close()


def atomic_write_text(path: str | os.PathLike[str], text: str, encoding: str = "utf-8") -> None:
    """Replace ``path`` with ``text`` so readers see the old or the new file, never half."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        # Default newline handling, like the writers this replaces: the files
        # keep the platform's line endings (CRLF on Windows).
        with os.fdopen(handle, "w", encoding=encoding) as temp_file:
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        # On Windows the swap fails while another process (a reader, OneDrive)
        # has the target open; it is only ever briefly, so retry.
        for attempt in range(25):
            try:
                os.replace(temp_name, path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        # Still busy after ~16 s: write in place rather than lose the change.
        path.write_text(text, encoding=encoding)
        print(f"warning: wrote {path} in place; it stayed open in another program", file=sys.stderr)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)
