"""POSIX local-filesystem atomic checkpoints, with explicit stale-writer guards."""

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile

from .contract import MAX_BYTES, ContinuationError, decode


def read_checkpoint(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ContinuationError("checkpoint size limit exceeded")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContinuationError("checkpoint must be UTF-8 JSON") from exc


@contextmanager
def _locked(path):
    try:
        import fcntl
    except ImportError as exc:
        raise ContinuationError("atomic checkpoint writer requires POSIX local file locking") from exc
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def write_checkpoint(path, text, *, previous_digest=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(text.encode()) > MAX_BYTES:
        raise ContinuationError("checkpoint size limit exceeded")
    with _locked(path):
        if path.exists():
            if previous_digest is None:
                raise ContinuationError("checkpoint exists; previous_digest required for replace")
            decode(read_checkpoint(path), expected_digest=previous_digest)
        elif previous_digest is not None:
            raise ContinuationError("checkpoint missing; stale previous_digest")
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".qms-checkpoint-", delete=False) as stream:
                temp = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if temp is not None and temp.exists():
                temp.unlink()
