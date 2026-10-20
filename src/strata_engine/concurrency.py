"""Coarse database serialization and exclusive local-directory ownership.

One reentrant operation lock is shared by engine, catalog, tables, indexes and
services. Raw page/buffer APIs require an enclosing engine.operation() context.
This is deadlock prevention, not transactions or a deadlock detector.
"""

from functools import wraps
import os
from pathlib import Path
from threading import RLock


class DatabaseBusyError(RuntimeError):
    """The database operation lock could not be acquired within its deadline."""


class DatabaseInUseError(RuntimeError):
    """Another catalog/engine already owns this database directory."""


class DatabaseLock:
    """Bounded, reentrant serialization; no independent table/page locks."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._mutex = RLock()
        self.timeout = timeout

    def _is_owned(self) -> bool:
        """Diagnostic parity with RLock; never use this to authorize access."""
        return self._mutex._is_owned()

    def __enter__(self):
        if not self._mutex.acquire(timeout=self.timeout):
            raise DatabaseBusyError("Database is busy; retry the operation.")
        return self

    def __exit__(self, *_):
        self._mutex.release()


def synchronized(method):
    """Protect a complete eager operation with the object's database lock.

    Do not use on generators: materialize their snapshot under the lock instead.
    """
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return guarded


class DirectoryLease:
    """Fail fast on a second opener, including another local process.

    The OS releases this advisory lock when the handle/process closes. Keep the
    lock file permanently: unlinking it would let another opener lock a new inode.
    Only local filesystems and cooperating Strata catalogs are supported.
    """

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._file = (directory / ".strata.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            raise DatabaseInUseError(
                f"Database directory '{directory}' is already in use. "
                "Run one backend worker and close other engines before reopening."
            ) from exc

    def close(self) -> None:
        if self._file.closed:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
