"""Cold, serial research completion; never an optimizer/checkpoint interpreter.

The existing study owner keeps its shared flock until it exits. Construct a
QueueSpec with all expected upstream paths, then call run_queue: after acquiring
that same lock it must admit every completion before launching any tail stage.
Expected pins may be supplied up front; future receipts are pinned at admission
and included in every stage identity. No receipt is polled indefinitely.

Commands are trusted, explicitly registered subprocesses, not a sandbox. Each
must declare its source/input pins and authoritative outputs, and must not
launch detached work. Only verified PASS stages are reused. A failed/interrupted
stage needs explicit retry authorization; its own financial recovery contract,
not this helper, decides how to continue. Nothing is deleted or overwritten.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable


class QueueError(RuntimeError):
    """Admission, identity, subprocess, or resource guard failed closed."""


class QueueCancelled(QueueError):
    """An owned queue was cancelled; evidence and partial outputs remain."""


def _absolute(path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        raise ValueError(f"absolute path required: {path}")
    return path.resolve()


def _json(value) -> bytes:
    def encode(item):
        if isinstance(item, Path):
            return str(item)
        raise TypeError(type(item).__name__)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=encode).encode("utf-8")


def _identity(value) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _read(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise QueueError(f"JSON object required: {path}")
    return value


def _write(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write(_json(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@dataclass(frozen=True)
class FilePin:
    path: Path
    sha256: str
    size: int

    def __post_init__(self):
        object.__setattr__(self, "path", _absolute(self.path))
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("SHA256 required")
        if type(self.size) is not int or self.size < 0:
            raise ValueError("nonnegative file size required")

    @classmethod
    def capture(cls, path: Path) -> FilePin:
        path = _absolute(path)
        if not path.is_file():
            raise QueueError(f"missing pinned file: {path}")
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
        return cls(path, digest.hexdigest(), size)

    def verify(self) -> None:
        if self != self.capture(self.path):
            raise QueueError(f"file pin mismatch: {self.path}")


@dataclass(frozen=True)
class UpstreamReceipt:
    name: str
    path: Path
    status: str
    attempts: int = 256
    status_key: str = "status"
    attempts_key: str = "attempts"
    expected_pin: FilePin | None = None

    def __post_init__(self):
        object.__setattr__(self, "path", _absolute(self.path))
        if not self.name or not self.status or type(self.attempts) is not int or self.attempts <= 0:
            raise ValueError("named completion, explicit status, positive attempts required")
        if self.expected_pin is not None and self.expected_pin.path != self.path:
            raise ValueError("upstream pin/path mismatch")

    def admit(self) -> FilePin:
        pinned = self.expected_pin or FilePin.capture(self.path)
        pinned.verify()
        row = _read(self.path)
        attempts = row.get(self.attempts_key)
        if (row.get(self.status_key) != self.status or type(attempts) is not int
                or attempts != self.attempts):
            raise QueueError(f"upstream not complete at registered budget: {self.name}")
        pinned.verify()
        return pinned


@dataclass(frozen=True)
class ExpectedOutput:
    path: Path
    status: str | None = None
    status_key: str = "status"

    def __post_init__(self):
        object.__setattr__(self, "path", _absolute(self.path))
        if self.status is not None and not self.status:
            raise ValueError("nonempty expected status required")

    def capture(self) -> FilePin:
        pinned = FilePin.capture(self.path)
        if pinned.path != self.path:
            raise QueueError(f"output path escaped its registration: {self.path}")
        if self.status is not None and _read(self.path).get(self.status_key) != self.status:
            raise QueueError(f"output not at registered terminal status: {self.path}")
        pinned.verify()
        return pinned


@dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...]
    cwd: Path
    sources: tuple[FilePin, ...]
    outputs: tuple[ExpectedOutput, ...]
    inputs: tuple[FilePin, ...] = ()
    forecast_bytes: int = 0

    def __post_init__(self):
        for name in ("command", "sources", "inputs"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", self.name):
            raise ValueError("safe stage name required")
        if (not self.command or not all(isinstance(arg, str) and "\0" not in arg for arg in self.command)
                or not Path(self.command[0]).is_absolute()):
            raise ValueError("explicit absolute executable and string argv required")
        object.__setattr__(self, "cwd", _absolute(self.cwd))
        object.__setattr__(self, "outputs", tuple(
            p if isinstance(p, ExpectedOutput) else ExpectedOutput(p) for p in self.outputs))
        if not self.sources or not self.outputs or not self.cwd.is_dir():
            raise ValueError("source pins, authoritative outputs, and existing cwd required")
        if type(self.forecast_bytes) is not int or self.forecast_bytes < 0:
            raise ValueError("nonnegative stage forecast required")


@dataclass(frozen=True)
class ResourceLimits:
    min_free_bytes: int = 5 * 1024**3
    min_available_memory_bytes: int = 512 * 1024**2
    max_retained_bytes: int = 1024**3
    max_owned_rss_bytes: int = 1280 * 1024**2
    max_wall_seconds: float = 24 * 3600
    lock_timeout_seconds: float = 24 * 3600
    poll_seconds: float = 1.0
    terminate_grace_seconds: float = 5.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"positive finite resource limit required: {name}")


@dataclass(frozen=True)
class QueueSpec:
    name: str
    receipt_dir: Path
    shared_lock: Path
    retained_root: Path
    upstream: tuple[UpstreamReceipt, ...]
    stages: tuple[Stage, ...]
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    required_upstream_count: int = 9
    deadline_ns: int | None = None

    def __post_init__(self):
        for name in ("upstream", "stages"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in ("receipt_dir", "shared_lock", "retained_root"):
            object.__setattr__(self, name, _absolute(getattr(self, name)))
        if (not self.name or not self.stages or type(self.required_upstream_count) is not int
                or self.required_upstream_count <= 0 or len(self.upstream) != self.required_upstream_count):
            raise ValueError("explicit full upstream roster and nonempty stage queue required")
        if self.deadline_ns is not None and (type(self.deadline_ns) is not int or self.deadline_ns <= 0):
            raise ValueError("absolute original-launch deadline in unix nanoseconds required")
        for rows in ([r.name for r in self.stages], [r.name for r in self.upstream],
                     [r.path for r in self.upstream]):
            if len(rows) != len(set(rows)):
                raise ValueError("duplicate stage/upstream identity")
        protected = {r.path for r in self.upstream} | {self.shared_lock}
        for stage in self.stages:
            protected.update(p.path for p in (*stage.sources, *stage.inputs))
        outputs = [p.path for stage in self.stages for p in stage.outputs]
        if len(set(outputs)) != len(outputs) or protected.intersection(outputs):
            raise ValueError("outputs must be distinct and must not overwrite registered inputs")
        if any(p.is_relative_to(self.receipt_dir) for p in outputs):
            raise ValueError("stage outputs must be outside the queue receipt directory")
        if any(not p.is_relative_to(self.retained_root) for p in outputs):
            raise ValueError("stage outputs must count toward retained budget")
        if not self.receipt_dir.is_relative_to(self.retained_root):
            raise ValueError("queue receipts must count toward retained budget")


@dataclass(frozen=True)
class ResourceUsage:
    free_bytes: int
    available_memory_bytes: int
    retained_bytes: int
    owned_rss_bytes: int


def sample_resources(spec: QueueSpec, child_pid: int | None) -> ResourceUsage:
    """Linux sampled RSS includes this owner and current descendants, not a peak."""
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available = int(memory["MemAvailable"].split()[0]) * 1024
    processes = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            processes[int(path.parent.name)] = (int(fields[1]), int(fields[21]))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    if os.getpid() not in processes:
        raise QueueError("cannot measure owned RSS")
    owned = {os.getpid()}
    if child_pid is not None:
        owned.add(child_pid)
    while True:
        more = {pid for pid, (parent, _) in processes.items() if parent in owned}
        if more.issubset(owned):
            break
        owned.update(more)
    rss = sum(processes.get(pid, (0, 0))[1] for pid in owned) * os.sysconf("SC_PAGE_SIZE")
    retained, inodes = 0, set()
    for root, _, files in os.walk(spec.retained_root):
        for name in files:
            stat = (Path(root) / name).lstat()
            inode = (stat.st_dev, stat.st_ino)
            if inode not in inodes:
                inodes.add(inode)
                retained += stat.st_size
    return ResourceUsage(shutil.disk_usage(spec.retained_root).free, available, retained, rss)


THREAD_ENV = {name: "1" for name in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "RAYON_NUM_THREADS",
)}


@contextmanager
def _cancellation():
    def stop(signum, _frame):
        raise QueueCancelled(f"signal {signum}")
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, stop)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _stop(child: subprocess.Popen, grace: float) -> None:
    # A stage owns its process group; never signal the upstream queue or host services.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait()


class _Runner:
    def __init__(self, spec, resources, cancel):
        self.spec, self.resources, self.cancel = spec, resources, cancel
        self.begun = time.monotonic()

    def guard(self, remaining: int, child: subprocess.Popen | None = None):
        if self.cancel is not None and self.cancel.is_set():
            raise QueueCancelled("cancellation requested")
        if time.monotonic() - self.begun >= self.spec.limits.max_wall_seconds:
            raise QueueError("queue wall guard")
        if self.spec.deadline_ns is not None and time.time_ns() >= self.spec.deadline_ns:
            raise QueueError("original launch deadline guard")
        usage, limits = self.resources(self.spec, None if child is None else child.pid), self.spec.limits
        if any(type(value) is not int or value < 0 for value in asdict(usage).values()):
            raise QueueError("invalid resource telemetry")
        failures = []
        if usage.free_bytes < limits.min_free_bytes + remaining:
            failures.append("disk")
        if usage.available_memory_bytes < limits.min_available_memory_bytes:
            failures.append("RAM")
        if usage.retained_bytes + remaining > limits.max_retained_bytes:
            failures.append("retained")
        if usage.owned_rss_bytes > limits.max_owned_rss_bytes:
            failures.append("RSS")
        if failures:
            raise QueueError("resource guard: " + ", ".join(failures))
        return asdict(usage)

    def run_stage(self, stage, identity, admitted, previous_outputs, remaining):
        folder = self.spec.receipt_dir
        starts = sorted(folder.glob(f"{stage.name}.*.start.json"))
        if starts:
            terminal_path = starts[-1].with_name(starts[-1].name.replace(".start.json", ".terminal.json"))
            if not terminal_path.exists():
                raise QueueError(f"interrupted stage requires explicit recovery: {stage.name}")
            terminal = _read(terminal_path)
            if terminal.get("identity") != identity or terminal.get("status") != "PASS":
                raise QueueError(f"failed/changed stage requires explicit recovery: {stage.name}")
            for row in [terminal["start"], terminal["log"], *terminal["outputs"]]:
                FilePin(**row).verify()
            pins = tuple(FilePin(**p) for p in terminal["outputs"])
            if tuple(p.path for p in pins) != tuple(p.path for p in stage.outputs):
                raise QueueError(f"output roster mismatch: {stage.name}")
            for output in stage.outputs:
                output.capture()
            return pins
        if any(p.path.exists() for p in stage.outputs):
            raise QueueError(f"unreceipted outputs require explicit recovery: {stage.name}")
        pins = (*admitted, *previous_outputs, *stage.sources, *stage.inputs)
        for pinned in pins:
            pinned.verify()
        stem = f"{stage.name}.{time.time_ns()}"
        start, terminal_path = folder / f"{stem}.start.json", folder / f"{stem}.terminal.json"
        log_path = folder / f"{stem}.log"
        _write(start, dict(status="STARTED", identity=identity, stage=stage.name,
                           command=stage.command, cwd=stage.cwd, thread_env=THREAD_ENV,
                           resources=self.guard(remaining), time_ns=time.time_ns()))
        child, failure, outputs = None, None, ()
        try:
            with log_path.open("xb") as log:
                child = subprocess.Popen(stage.command, cwd=stage.cwd,
                    env={**os.environ, **THREAD_ENV}, stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, start_new_session=True)
                while True:
                    self.guard(remaining - stage.forecast_bytes, child)
                    try:
                        code = child.wait(timeout=self.spec.limits.poll_seconds)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if code:
                    raise QueueError(f"stage exited {code}: {stage.name}")
                try:
                    os.killpg(child.pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise QueueError(f"stage left live descendants: {stage.name}")
                for pinned in pins:
                    pinned.verify()
                outputs = tuple(output.capture() for output in stage.outputs)
                log.flush()
                os.fsync(log.fileno())
            self.guard(remaining - stage.forecast_bytes)
        except BaseException as error:
            failure = error
            if child is not None:
                _stop(child, self.spec.limits.terminate_grace_seconds)
        status = "PASS" if failure is None else (
            "CANCELLED_RETAINED" if isinstance(failure, (QueueCancelled, KeyboardInterrupt)) else "FAIL_RETAINED")
        if log_path.exists():
            with log_path.open("rb") as log:
                os.fsync(log.fileno())
        _write(terminal_path, dict(status=status, identity=identity, stage=stage.name,
            start=asdict(FilePin.capture(start)), log=asdict(FilePin.capture(log_path)) if log_path.exists() else None,
            outputs=[asdict(p) for p in outputs], exit_code=None if child is None else child.returncode,
            error=None if failure is None else f"{type(failure).__name__}: {failure}", time_ns=time.time_ns()))
        if failure is not None:
            raise failure
        return outputs

    def run(self):
        spec = self.spec
        spec.receipt_dir.mkdir(parents=True, exist_ok=True)
        if not spec.shared_lock.parent.is_dir():
            raise QueueError("shared lock parent must already exist")
        remaining = sum(stage.forecast_bytes for stage in spec.stages)
        executable_pins = [FilePin.capture(Path(stage.command[0])) for stage in spec.stages]
        config = dict(schema="mode5_completion_queue_v1", spec=asdict(spec),
                      executable_pins=[asdict(p) for p in executable_pins], thread_env=THREAD_ENV,
                      helper=asdict(FilePin.capture(Path(__file__).absolute())))
        config_path = spec.receipt_dir / "queue-spec.json"
        if config_path.exists():
            if _json(_read(config_path)) != _json(config):
                raise QueueError("registered queue configuration changed")
        else:
            _write(config_path, config)
        run_id = uuid.uuid4().hex
        start_path = spec.receipt_dir / f"queue-{run_id}.start.json"
        terminal_path = spec.receipt_dir / f"queue-{run_id}.terminal.json"
        _write(start_path, dict(status="WAITING_UPSTREAM_LOCK", config=asdict(FilePin.capture(config_path)),
                                owner_pid=os.getpid(), time_ns=time.time_ns()))
        try:
            with spec.shared_lock.open("a+b") as lock, _cancellation():
                while True:
                    self.guard(0)
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() - self.begun >= spec.limits.lock_timeout_seconds:
                            raise QueueError("upstream lock wait timeout")
                        time.sleep(spec.limits.poll_seconds)
                admitted = tuple(row.admit() for row in spec.upstream)
                invariants = (FilePin.capture(config_path), FilePin(**config["helper"]), *executable_pins)
                previous = ()
                for stage, executable in zip(spec.stages, executable_pins):
                    executable.verify()
                    if Path(stage.command[0]).resolve() != executable.path:
                        raise QueueError("executable symlink changed")
                    for pinned in (*admitted, *invariants, *stage.sources, *stage.inputs):
                        pinned.verify()
                    stage_identity = _identity(dict(config=_identity(config), stage=asdict(stage),
                        upstream=[asdict(p) for p in admitted], previous=[asdict(p) for p in previous]))
                    previous += self.run_stage(stage, stage_identity, (*admitted, *invariants), previous, remaining)
                    remaining -= stage.forecast_bytes
                result = dict(status="PASS", config=asdict(FilePin.capture(config_path)),
                              upstream=[asdict(p) for p in admitted], outputs=[asdict(p) for p in previous])
                self.guard(0)
                _write(terminal_path, {**result, "time_ns": time.time_ns()})
                return result
        except BaseException as error:
            _write(terminal_path, dict(status="CANCELLED_RETAINED" if isinstance(error, (QueueCancelled, KeyboardInterrupt))
                else "FAIL_RETAINED", config=asdict(FilePin.capture(config_path)),
                error=f"{type(error).__name__}: {error}", time_ns=time.time_ns()))
            raise


def run_queue(spec: QueueSpec, *, resources: Callable = sample_resources,
              cancel: threading.Event | None = None) -> dict:
    """Run/reuse the registered tail under the existing financial-owner lock.

    Failed or interrupted stages are deliberately not retried here. A caller
    must admit a new recovery queue/receipt directory, with the old evidence as
    pinned inputs, after validating the stage's own resumability contract.
    """
    return _Runner(spec, resources, cancel).run()
