"""Bounded, content-pinned metadata reads for an immutable archive snapshot."""

from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON key in source evidence")
        result[name] = value
    return result


def _nonfinite(value):
    raise ValueError("non-finite JSON evidence is not a measured value: " + value)


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        _nonfinite(value)
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class FilePin:
    path: str
    bytes: int
    sha256: str


class ArchiveReader:
    """One owner, bounded JSON only; a pin is integrity, not economic truth."""

    def __init__(self, root, *, max_document_bytes=16 * 1024**2):
        self.root = Path(root).resolve(strict=True)
        if type(max_document_bytes) is not int or max_document_bytes <= 0:
            raise ValueError("positive explicit document budget required")
        self.max_document_bytes = max_document_bytes
        self.pins = {}
        self.reads = 0

    def path(self, name):
        raw = Path(name)
        path = (raw if raw.is_absolute() else self.root / raw).resolve(strict=True)
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("archive source must be a regular file inside its root")
        return path

    @staticmethod
    def _stat(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def pin(self, name):
        path = self.path(name)
        before = path.stat()
        hasher = hashlib.sha256()
        with path.open("rb") as source:
            if self._stat(os.fstat(source.fileno())) != self._stat(before):
                raise ValueError("archive changed before pin")
            for block in iter(lambda: source.read(1024**2), b""):
                hasher.update(block)
            if self._stat(os.fstat(source.fileno())) != self._stat(before):
                raise ValueError("archive changed while pinning")
        if self._stat(path.stat()) != self._stat(before):
            raise ValueError("archive replaced while pinning")
        row = FilePin(str(path.relative_to(self.root)), before.st_size, hasher.hexdigest())
        old = self.pins.get(row.path)
        if old is not None and old != row:
            raise ValueError("source changed within the frozen inventory")
        self.pins[row.path] = row
        return row

    def read(self, name, *, expected=None):
        path = self.path(name)
        before = self.pin(path)
        if expected is not None:
            if before.bytes != expected["bytes"] or before.sha256 != expected["sha256"]:
                raise ValueError("source differs from its retained receipt")
            if "path" in expected and self.path(expected["path"]) != path:
                raise ValueError("retained receipt refers to a different file")
        with path.open("rb") as stream:
            opened = self._stat(os.fstat(stream.fileno()))
            stored = stream.read(self.max_document_bytes + 1)
            if self._stat(os.fstat(stream.fileno())) != opened:
                raise ValueError("archive changed during the decoding read")
        if (len(stored) != before.bytes or hashlib.sha256(stored).hexdigest() != before.sha256):
            raise ValueError("decoded source bytes differ from the pinned payload")
        if path.suffix == ".gz":
            with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
                raw = stream.read(self.max_document_bytes + 1)
        else:
            raw = stored
        if len(raw) > self.max_document_bytes:
            raise MemoryError("archive JSON exceeds the declared decoded-byte budget")
        result = json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite, parse_float=_float)
        if not isinstance(result, (dict, list)):
            raise ValueError("structured archive document required")
        if self.pin(path) != before:
            raise ValueError("archive changed while decoding")
        self.reads += 1
        return result

    def verify(self):
        frozen = tuple(self.pins.values())
        for row in frozen:
            if self.pin(row.path) != row:
                raise ValueError("frozen source changed")
        return len(frozen)


class SnapshotWriter:
    """Append-only compact outputs; no source replacement or implicit cleanup."""

    def __init__(self, root, *, max_bytes=64 * 1024**2):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("positive explicit retention budget required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    def _used(self):
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())

    def save(self, name, value):
        raw = canonical(value).encode()
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("output outside the registered snapshot")
        if path.suffix == ".gz":
            raw = gzip.compress(raw, mtime=0)
        if self._used() + len(raw) > self.max_bytes:
            raise MemoryError("compact snapshot retention budget exceeded")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        return FilePin(str(path.relative_to(self.root)), len(raw), hashlib.sha256(raw).hexdigest())


def coverage(rows):
    """Count observed dispositions without imputing values or sample independence."""
    counts = {}
    seen = set()
    for row in rows:
        key = row["cell_id"]
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("distinct explicit archive cell IDs required")
        seen.add(key)
        state = row["status"]
        if state not in {"VALID", "NO_TRADE", "UNDEFINED", "FAILED", "PRUNED", "PENDING", "MISSING", "INCOMPLETE", "UNVERIFIED"}:
            raise ValueError("explicit known evidence disposition required")
        value = row.get("value")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("finite measured value or null required")
        if state == "VALID" and value is None:
            raise ValueError("VALID measured coverage requires a finite value")
        if state in {"FAILED", "PRUNED", "PENDING", "MISSING", "INCOMPLETE", "UNVERIFIED", "UNDEFINED"} and value is not None:
            raise ValueError("missing/invalid evidence cannot carry a successful sentinel")
        counts[state] = counts.get(state, 0) + 1
    return dict(total=len(seen), dispositions=counts, independent_repetitions=None)
