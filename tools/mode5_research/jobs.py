"""Linux/POSIX research custody, not a financial engine or mid-account resume.

Main-owner handoff (run from the repository with the controlled Python):
  python -B -m tools.mode5_research.jobs plan --specs SPEC.json --store STORE
  python -B -m tools.mode5_research.jobs register --specs SPEC.json --store STORE \
      --lane tranche-02 --native-gate GATE.json --workers 3
  python -B -m tools.mode5_research.jobs launch --lane STORE/runs/tranche-02
  python -B -m tools.mode5_research.jobs watch --lane STORE/runs/tranche-02
  python -B -m tools.mode5_research.jobs stop --lane STORE/runs/tranche-02

SPEC.json is a list of Candidate.to_dict() records. Commands are argv arrays;
only whole-argument {output}, {request}, {progress}, {scratch} substitutions
are supported. The child receives the same paths as MODE5_JOB_* variables.
It must independently reset financial/RNG state from the exact request and
write its domain-qualified result, with that request, to result_file. The
supervisor checks custody, not financial/scientific qualification. Historical
results may be adopted only with a pre-existing manifest and qualification pin.

Use one store for all three financial slots. Detached jobs must be launched
in the same host PID namespace as their watcher. No restart on heartbeat age,
no automatic retry, no SIGKILL/power-loss promise of a synchronous final receipt.
Surviving worker sessions block new attempts; recovery is explicit and censored.
Children must not escape their private session. Resource caps are sampled, not
quotas; filesystem exhaustion can prevent further durable receipt publication.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

from tools.mode5_baseline.isolation import canonical_digest, file_identity, write_json

MIB, GIB = 1024**2, 1024**3
THREADS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMBA_NUM_THREADS", "RAYON_NUM_THREADS", "NUMEXPR_NUM_THREADS",
           "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked custody path")
    return path


def _name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise ValueError("unsafe lane/cell name")
    return value


def _relative(value):
    path = Path(value)
    if path.is_absolute() or not path.parts or any(p in {".", ".."} for p in path.parts):
        raise ValueError("output must be a relative file")
    return value


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _seal(path, value):
    """Strengthen the local exclusive JSON helper with atomic, fsynced publication."""
    path = _safe(path)
    temp = path.with_name(".pending-" + uuid.uuid4().hex)
    try:
        write_json(temp, value)
        with temp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.link(temp, path)  # Unlike replace, a collision cannot overwrite evidence.
        temp.unlink()
        _sync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def _read(path):
    path = _safe(path)
    if path.stat().st_size > 4 * MIB:
        raise ValueError("oversized custody JSON")
    return json.loads(path.read_text())


def verify_pins(pins):
    for pin in pins:
        if file_identity(_safe(pin["path"])) != pin:
            raise ValueError("registered input/manifest changed: " + pin["path"])


@dataclass(frozen=True)
class Candidate:
    cell_id: str
    request_json: str
    argv: tuple[str, ...]
    cwd: str
    pins_json: str
    required_outputs: tuple[str, ...] = ("cell.json",)
    result_file: str = "cell.json"
    success_status: str = "PASS"
    count_fields: tuple[tuple[str, str], ...] = (
        ("account_passes", "actual_execution_calls"), ("account_bars", "visited_bars"))
    env: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        _name(self.cell_id)
        request, pins = json.loads(self.request_json), json.loads(self.pins_json)
        canonical_digest(request)
        if not isinstance(request, dict) or not isinstance(pins, list) or not pins:
            raise ValueError("exact request object and source/data/artifact pins required")
        if (not isinstance(self.argv, tuple) or not self.argv or
                any(not isinstance(a, str) or not a or "\0" in a for a in self.argv)):
            raise ValueError("structured nonempty argv required")
        executable = _safe(self.argv[0])
        if not Path(self.argv[0]).is_absolute() or not executable.is_file():
            raise ValueError("absolute pinned executable required")
        paths = [p["path"] for p in pins]
        if len(set(paths)) != len(paths) or str(executable) not in paths:
            raise ValueError("executable pin missing or duplicate pins")
        for arg in self.argv[1:]:
            if Path(arg).is_absolute() and Path(arg).is_file() and str(_safe(arg)) not in paths:
                raise ValueError("command file pin missing: " + arg)
        if not Path(self.cwd).is_absolute() or not _safe(self.cwd).is_dir():
            raise ValueError("absolute working directory required")
        if not self.required_outputs or self.result_file not in self.required_outputs:
            raise ValueError("result and required evidence inventory required")
        if any(not isinstance(value, tuple) for value in (self.required_outputs, self.count_fields, self.env)):
            raise ValueError("immutable tuple inventories required")
        if any(not isinstance(pair, tuple) for pair in (*self.count_fields, *self.env)):
            raise ValueError("immutable field/environment pairs required")
        for output in self.required_outputs:
            _relative(output)
        if len(set(self.required_outputs)) != len(self.required_outputs):
            raise ValueError("duplicate required outputs")
        if not self.count_fields or len(dict(self.count_fields)) != len(self.count_fields):
            raise ValueError("duplicate count units")
        for unit, field in self.count_fields:
            _name(unit)
            _name(field)
        reserved = set(THREADS) | {"PYTHONDONTWRITEBYTECODE"}
        if len(dict(self.env)) != len(self.env) or any(
                k in reserved or k.startswith("MODE5_JOB_") or "=" in k or not k
                or "\0" in k + v for k, v in self.env):
            raise ValueError("invalid/overridden worker environment")

    @classmethod
    def create(cls, cell_id, request, argv, cwd, pins, **kwargs):
        return cls(cell_id, json.dumps(request, sort_keys=True, allow_nan=False),
                   tuple(argv), str(cwd), json.dumps(pins, sort_keys=True), **kwargs)

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        for key in ("argv", "required_outputs"):
            if key in value:
                value[key] = tuple(value[key])
        for key in ("count_fields", "env"):
            if key in value:
                value[key] = tuple(tuple(pair) for pair in value[key])
        return cls(**value)

    def to_dict(self):
        return json.loads(json.dumps(asdict(self)))

    @property
    def key(self):
        return canonical_digest(self.to_dict())

    @property
    def pins(self):
        return json.loads(self.pins_json)


@dataclass(frozen=True)
class Budget:
    scratch_bytes: int = 32 * MIB
    retained_bytes: int = 16 * MIB
    reserve_bytes: int = 5 * GIB
    free_inodes: int = 1024
    scratch_inodes: int = 4096
    retained_inodes: int = 8192
    worker_rss_bytes: int = 2 * GIB
    total_rss_bytes: int = 6 * GIB
    cell_seconds: float = 21600
    tranche_seconds: float = 21600
    poll_seconds: float = 1
    heartbeat_seconds: float = 30
    terminate_seconds: float = 5
    max_attempts: int = 3

    def __post_init__(self):
        for key, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError("positive finite budget required: " + key)
            if not key.endswith("seconds") and type(value) is not int:
                raise ValueError("integer byte/inode/attempt budget required")
        if self.reserve_bytes < 5 * GIB or self.max_attempts > 32:
            raise ValueError("5 GiB reserve and bounded attempt count required")


def _tree(path):
    path = _safe(path)
    files, size, inodes = [], 0, 0
    for item in sorted(path.rglob("*")):
        _safe(item)
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue  # Concurrent cache removal/publication is a sampled resource snapshot.
        inodes += 1
        if stat.S_ISREG(info.st_mode):
            size += info.st_size
            files.append(item)
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("special custody file")
    return files, size, inodes


def _manifest(path):
    return [file_identity(p) for p in _tree(path)[0]]


def _space(path):
    info = os.statvfs(path)
    return dict(free_bytes=info.f_bavail * info.f_frsize, free_inodes=info.f_favail)


def _preflight(path, budget):
    space = _space(path)
    if (space["free_bytes"] < budget.reserve_bytes + budget.scratch_bytes + budget.retained_bytes
            or space["free_inodes"] < budget.free_inodes + budget.scratch_inodes + budget.retained_inodes):
        raise RuntimeError("host byte/inode headroom unavailable")
    return space


class _lock:
    def __init__(self, path):
        self.path, self.fd = _safe(path), None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.__exit__(None, None, None)
            raise RuntimeError("live owner holds custody lock") from error
        return self.fd

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def process_identity(pid):
    try:
        proc = Path(f"/proc/{pid}")
        fields = (proc / "stat").read_text().rpartition(")")[2].split()
        return dict(pid=pid, start_ticks=int(fields[19]), pgid=int(fields[2]),
                    session=int(fields[3]), boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    pid_namespace=os.readlink(proc / "ns/pid"))
    except (FileNotFoundError, ProcessLookupError):
        return None


def _namespace(owner):
    current = process_identity(os.getpid())
    if owner["boot_id"] != current["boot_id"]:
        return False
    if owner["pid_namespace"] != current["pid_namespace"]:
        raise RuntimeError("ownership namespace/boot differs; host review required")
    return True


def is_live(owner):
    return _namespace(owner) and process_identity(owner["pid"]) == owner


def _members(owner):
    if not _namespace(owner):
        return []
    current = process_identity(owner["pid"])
    if current is not None and current != owner:
        return []
    if owner["pgid"] != owner["pid"] or owner["session"] != owner["pid"]:
        raise RuntimeError("worker does not own a private process session")
    members = []
    for proc in Path("/proc").iterdir():
        if proc.name.isdecimal():
            row = process_identity(int(proc.name))
            if row and row["pgid"] == owner["pid"]:
                if row["session"] != owner["pid"] or row["start_ticks"] < owner["start_ticks"]:
                    raise RuntimeError("unowned group member")
                members.append(row)
    return members


def _signal_group(owner, sig):
    if not _namespace(owner):
        return []
    current = process_identity(owner["pid"])
    if current is not None and current != owner:
        raise RuntimeError("PID reused; refusing group custody")
    members = _members(owner)
    if members:
        try:
            os.killpg(owner["pid"], sig)
        except ProcessLookupError:
            pass
    return members


class Journal:
    """Single-writer immutable event files: append-only without torn JSONL tails."""

    def __init__(self, directory):
        self.directory = _safe(directory)
        self.directory.mkdir()
        _sync_dir(self.directory.parent)
        self.seq, self.previous = 0, None

    def append(self, event, **fields):
        row = dict(seq=self.seq, previous=self.previous, event=event, time=_now()) | fields
        _seal(self.directory / f"{self.seq:08d}.json", row)
        self.previous = canonical_digest(row)
        self.seq += 1


def read_journal(directory):
    rows, previous = [], None
    for path in sorted(_safe(directory).glob("*.json")):
        row = _read(path)
        if path.name != f"{len(rows):08d}.json" or row["seq"] != len(rows) or row["previous"] != previous:
            raise ValueError("journal chain/sequence differs")
        rows.append(row)
        previous = canonical_digest(row)
    return rows


def plan(candidates, store, budget=Budget()):
    candidates = tuple(candidates)
    if not candidates or len({c.cell_id for c in candidates}) != len(candidates):
        raise ValueError("unique nonempty candidate schedule required")
    store = _safe(store)
    for candidate in candidates:
        verify_pins(candidate.pins)
    parent = next(p for p in (store, *store.parents) if p.exists())
    return dict(candidates=[c.to_dict() for c in candidates], budget=asdict(budget),
                store=str(store), space=_preflight(parent, budget), financial_executions=0)


def register(store, lane, candidates, *, native_gate, workers=1, budget=Budget()):
    if type(workers) is not int or not 1 <= workers <= 3:
        raise ValueError("one to three workers required")
    preview = plan(candidates, store, budget)
    gate = file_identity(_safe(native_gate))
    if _read(native_gate).get("status") != "PASS":
        raise ValueError("owner-supplied native gate must be PASS")
    store = Path(preview["store"])
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    runs = store / "runs"
    runs.mkdir(exist_ok=True)
    target = runs / _name(lane)
    target.mkdir(mode=0o700)
    registration = dict(schema="mode5.research.jobs.v1", created_at=_now(),
                        workers=workers, native_gate=gate, module=file_identity(Path(__file__)),
                        helper=file_identity(Path(write_json.__code__.co_filename)), **preview)
    _seal(target / "registration.json", registration)
    return target


def _result(candidate, output):
    verify_pins(candidate.pins)
    for name in candidate.required_outputs:
        file_identity(_safe(output / name))
    result = _read(output / candidate.result_file)
    if (result.get("status") != candidate.success_status
            or canonical_digest(result.get("request")) != canonical_digest(json.loads(candidate.request_json))):
        raise ValueError("domain result status/exact request differs")
    counts = {}
    for unit, field in candidate.count_fields:
        value = result.get(field)
        if type(value) is not int or value < 0:
            raise ValueError("exact completed count missing/invalid: " + field)
        counts[unit] = value
    return counts


def _checkpoint(candidate, attempt, output, counts):
    if _result(candidate, output) != counts:
        raise ValueError("result changed before checkpoint publication")
    for path in _tree(output)[0]:
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    for directory in sorted((p for p in output.rglob("*") if p.is_dir()), reverse=True):
        _sync_dir(directory)
    _sync_dir(output)
    _seal(attempt / "checkpoint.json", dict(key=candidate.key, candidate=candidate.to_dict(),
          output=str(output), artifacts=_manifest(output), exact_counts=counts,
          receipt=file_identity(attempt / "receipt.json")))


def _reuse(candidate, attempt):
    checkpoint = _read(attempt / "checkpoint.json")
    if checkpoint["key"] != candidate.key or checkpoint["candidate"] != candidate.to_dict():
        raise ValueError("completed checkpoint request identity differs")
    verify_pins(candidate.pins + checkpoint["artifacts"] + [checkpoint["receipt"]])
    receipt = _read(checkpoint["receipt"]["path"])
    if receipt["status"] != "COMPLETE":
        raise ValueError("uncompleted checkpoint receipt")
    if "qualification" in receipt:
        verify_pins([receipt["qualification"]])
    output = Path(checkpoint["output"])
    if _manifest(output) != checkpoint["artifacts"] or _result(candidate, output) != checkpoint["exact_counts"]:
        raise ValueError("completed output inventory/counts differ")
    return dict(cell_id=candidate.cell_id, status="REUSED", checkpoint=file_identity(attempt / "checkpoint.json"),
                exact_counts=checkpoint["exact_counts"], financial_executions=0)


def _candidate_dir(store, candidate):
    cells = _safe(store / "cells")
    cells.mkdir(exist_ok=True)
    cell = cells / candidate.cell_id
    cell.mkdir(exist_ok=True)
    return cell


def _reserve(store, candidate, budget):
    cell = _candidate_dir(store, candidate)
    lock = _lock(cell / "owner.lock")
    lock.__enter__()
    try:
        spec_path = cell / "candidate.json"
        if spec_path.exists():
            if _read(spec_path) != candidate.to_dict():
                raise ValueError("cell request collision; immutable candidate differs")
        else:
            _seal(spec_path, candidate.to_dict())
        attempts = sorted(cell.glob("attempt-*"))
        for attempt in attempts:
            started = attempt / "started.json"
            if started.exists() and _members(_read(started)["owner"]):
                raise RuntimeError("previous worker session is still live; no duplicate launch")
        for attempt in attempts:
            if (attempt / "checkpoint.json").exists():
                reused = _reuse(candidate, attempt)
                lock.__exit__(None, None, None)
                return None, None, reused
        if len(attempts) >= budget.max_attempts:
            raise RuntimeError("bounded attempt budget exhausted; owner investigation required")
        # A launch intent with no PID receipt is ambiguous, not proof of death.
        for attempt in attempts:
            if (attempt / "intent.json").exists() and not (attempt / "started.json").exists() and not (attempt / "receipt.json").exists():
                raise RuntimeError("unresolved launch intent; explicit host custody review required")
        attempt = cell / f"attempt-{len(attempts)+1:04d}"
        attempt.mkdir()
        _sync_dir(cell)
        _seal(attempt / "request.json", json.loads(candidate.request_json))
        return attempt, lock, None
    except BaseException:
        lock.__exit__(None, None, None)
        raise


def adopt_completed(store, candidate, output, *, manifest, qualification, budget=Budget()):
    """Cold import of an already domain-qualified candidate; zero execution.

    The main owner supplies the original sealed artifact manifest and a PASS
    qualification receipt. This never turns a censored historical cell into PASS.
    """
    plan([candidate], store, budget)
    store = _safe(store)
    store.mkdir(parents=True, exist_ok=True)
    output = _safe(output)
    qualification = file_identity(_safe(qualification))
    qualified = _read(qualification["path"])
    if (qualified.get("status") != "PASS" or qualified.get("candidate_key") != candidate.key
            or qualified.get("artifacts") != manifest):
        raise ValueError("historical qualification is not PASS")
    verify_pins(manifest + [qualification])
    if _manifest(output) != manifest:
        raise ValueError("historical output manifest differs")
    counts = _result(candidate, output)
    attempt, lock, reused = _reserve(store, candidate, budget)
    if reused:
        return reused
    try:
        _seal(attempt / "receipt.json", dict(status="COMPLETE", origin="ADOPTED_QUALIFIED_HISTORY",
              qualification=qualification, exact_counts=counts, financial_executions=0))
        _checkpoint(candidate, attempt, output, counts)
        return _reuse(candidate, attempt)
    finally:
        lock.__exit__(None, None, None)


def _subreaper():
    # Adopt session grandchildren so waitpid can reap exact owned PIDs, never -1.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot establish child subreaper")


def _progress(job):
    cursors = job.setdefault("cursors", {})
    for path in (job["progress"], job.get("log_path")):
        if path is None or not path.exists():
            continue
        cursor = cursors.setdefault(str(path), dict(offset=0, tail=b""))
        with _safe(path).open("rb") as stream:
            stream.seek(cursor["offset"])
            data = cursor["tail"] + stream.read(65536)
            cursor["offset"] = stream.tell()
        lines = data.split(b"\n")
        cursor["tail"] = lines.pop()[-65536:]
        for line in lines:
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(row, dict) or row.get("stage") != "account_complete":
                continue
            for field, unit in (("completed_passes", "account_passes"), ("completed_account_bars", "account_bars")):
                value = row.get(field)
                if type(value) is int and value >= 0:
                    job["lower_bounds"][unit] = max(job["lower_bounds"].get(unit, 0), value)


def _rss(owner):
    total = 0
    for member in _members(owner):
        try:
            for line in Path(f"/proc/{member['pid']}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
        except FileNotFoundError:
            pass
    return total


def _reap(job, budget, reason):
    members = _signal_group(job["owner"], signal.SIGTERM) if reason else _members(job["owner"])
    if not reason and job["process"].poll() is not None and members:
        # A worker is not COMPLETE while it has left a live descendant behind.
        reason = "WORKER_LEFT_DESCENDANTS"
        _signal_group(job["owner"], signal.SIGTERM)
    deadline = time.monotonic() + budget.terminate_seconds
    descendants = {row["pid"]: row for row in members if row["pid"] != job["process"].pid}
    while _members(job["owner"]) and time.monotonic() < deadline:
        job["process"].poll()
        for row in _members(job["owner"]):
            if row["pid"] != job["process"].pid:
                descendants[row["pid"]] = row
        for pid, row in descendants.items():
            if process_identity(pid) == row:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
        time.sleep(.01)
    _signal_group(job["owner"], signal.SIGKILL)
    code = job["process"].wait(timeout=budget.terminate_seconds + 1)
    deadline = time.monotonic() + budget.terminate_seconds
    while _members(job["owner"]) and time.monotonic() < deadline:
        for pid, row in descendants.items():
            if process_identity(pid) == row:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
        time.sleep(.01)
    return code, reason, not _members(job["owner"])


def _finish(job, budget, journal, reason=None):
    candidate, attempt = job["candidate"], job["attempt"]
    errors, counts = [], None
    code, reason, reaped = _reap(job, budget, reason)
    job["log"].close()
    try:
        _progress(job)
    except Exception as error:
        errors.append("progress: " + repr(error))
    status = "CENSORED" if reason else "FAILED"
    if code == 0 and reason is None and reaped and not errors:
        try:
            counts = _result(candidate, job["output"])
            status = "COMPLETE"
        except Exception as error:
            status = "VALIDATION_FAILED"
            errors.append(repr(error))
    else:
        try:
            verify_pins(candidate.pins)
        except Exception as error:
            errors.append(repr(error))
    receipt = dict(cell_id=candidate.cell_id, key=candidate.key, status=status, time=_now(),
                   exit_code=code, reason=reason, validation_errors=errors, owner=job["owner"],
                   all_owned_children_reaped=reaped, seconds=time.monotonic()-job["start"],
                   observed_peak_group_rss_bytes=job["peak"], exact_counts=counts,
                   observed_lower_bounds=job["lower_bounds"], log=file_identity(attempt / "process.log"),
                   financial_executions=1, fresh_process=True, no_mid_account_resume=True)
    _seal(attempt / "receipt.json", receipt)
    if status == "COMPLETE":
        try:
            _checkpoint(candidate, attempt, job["output"], counts)
        except Exception as error:
            # Keep the process receipt; checkpoint failure is a new, distinct fact.
            receipt = receipt | dict(status="CHECKPOINT_FAILED", checkpoint_error=repr(error))
            _seal(attempt / "checkpoint_failure.json", receipt)
    journal.append("completion" if receipt["status"] == "COMPLETE" else "interrupt" if reason else "failure",
                   receipt=file_identity(attempt / "receipt.json"), **receipt)
    job["lock"].__exit__(None, None, None)
    job["slot"].__exit__(None, None, None)
    return receipt


def _slot(store):
    for index in range(3):
        lock = _lock(store / f"slot-{index}.lock")
        try:
            lock.__enter__()
        except RuntimeError:
            continue
        return lock
    raise RuntimeError("three store-wide worker slots already occupied")


def _start(candidate, attempt, lock, slot, lane, journal, active):
    scratch = lane / "scratch" / (candidate.cell_id + "-" + attempt.name)
    scratch.mkdir()
    output = attempt / "output"
    # Leave output creation to existing no-overwrite financial drivers.
    progress = attempt / "progress.jsonl"
    substitutions = {"{output}": str(output), "{request}": str(attempt / "request.json"),
                     "{progress}": str(progress), "{scratch}": str(scratch)}
    argv = [substitutions.get(arg, arg) for arg in candidate.argv]
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL") if k in os.environ}
    env.update(dict(candidate.env))
    env.update({key: "1" for key in THREADS})
    env.update(PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(scratch), NUMBA_CACHE_DIR=str(scratch / "numba"),
               MPLCONFIGDIR=str(scratch / "mpl"), MODE5_JOB_OUTPUT=str(output),
               MODE5_JOB_REQUEST=str(attempt / "request.json"), MODE5_JOB_PROGRESS=str(progress),
               MODE5_JOB_SCRATCH=str(scratch))
    log = None
    try:
        intent = dict(candidate=candidate.to_dict(), argv=argv, env=env, scratch=str(scratch),
                      source_before=candidate.pins, lane=str(lane), fresh_process=True)
        _seal(attempt / "intent.json", intent)
        journal.append("launch", cell_id=candidate.cell_id, attempt=str(attempt), intent=file_identity(attempt / "intent.json"))
        log = (attempt / "process.log").open("xb")
        job = dict(candidate=candidate, attempt=attempt, output=output, progress=progress, lock=lock,
                   slot=slot, log=log, log_path=attempt / "process.log", start=time.monotonic(),
                   peak=0, lower_bounds={})
        process = subprocess.Popen(argv, cwd=candidate.cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                   pass_fds=(lock.fd, slot.fd))
    except Exception as error:
        if log:
            log.close()
        receipt = dict(status="LAUNCH_FAILED", cell_id=candidate.cell_id, error=repr(error),
                       exact_counts=None, observed_lower_bounds={}, financial_executions=0)
        _seal(attempt / "receipt.json", receipt)
        lock.__exit__(None, None, None)
        slot.__exit__(None, None, None)
        journal.append("failure", **receipt)
        return receipt
    job.update(process=process, owner=process_identity(process.pid))
    active.append(job)
    if job["owner"] is None:
        # A direct child remains a zombie until wait(), so disappearance is a custody fault.
        raise RuntimeError("worker PID receipt unavailable")
    _seal(attempt / "started.json", dict(owner=job["owner"], time=_now(), intent=file_identity(attempt / "intent.json")))
    journal.append("start", cell_id=candidate.cell_id, attempt=str(attempt), owner=job["owner"])
    return None


def _resource_reason(store, lane, budget, active, start):
    space = _space(store)
    scratch_bytes, scratch_inodes = 0, 0
    for scratch in (store / "runs").glob("*/scratch"):
        _, size, inodes = _tree(scratch)
        scratch_bytes += size
        scratch_inodes += inodes
    _, retained_bytes, retained_inodes = _tree(store)
    retained_bytes -= scratch_bytes
    retained_inodes -= scratch_inodes
    resources = dict(**space, scratch_bytes=scratch_bytes, retained_bytes=retained_bytes,
                     scratch_inodes=scratch_inodes, retained_inodes=retained_inodes)
    reason = None
    if space["free_bytes"] < budget.reserve_bytes or space["free_inodes"] < budget.free_inodes:
        reason = "HOST_RESERVE_CAP"
    elif scratch_bytes > budget.scratch_bytes or scratch_inodes > budget.scratch_inodes:
        reason = "SCRATCH_CAP"
    elif retained_bytes > budget.retained_bytes - 128 * 1024 or retained_inodes > budget.retained_inodes - 32:
        reason = "RETAINED_CAP"
    elif time.monotonic() - start > budget.tranche_seconds:
        reason = "TRANCHE_TIME_CAP"
    total, seen = 0, set()
    for job in active:
        rss = _rss(job["owner"])
        job["peak"] = max(job["peak"], rss)
        total += rss
        seen.add((job["owner"]["pid"], job["owner"]["start_ticks"]))
        if rss > budget.worker_rss_bytes:
            reason = "WORKER_RSS_CAP"
        elif time.monotonic() - job["start"] > budget.cell_seconds:
            reason = "CELL_TIME_CAP"
    for path in (store / "cells").glob("*/attempt-*/started.json"):
        owner = _read(path)["owner"]
        if (owner["pid"], owner["start_ticks"]) not in seen:
            total += _rss(owner)
    resources["store_group_rss_bytes"] = total
    if total > budget.total_rss_bytes:
        reason = "TOTAL_RSS_CAP"
    return reason, resources


def run(lane):
    """Blocking monitor; call in a dedicated main-thread supervisor process."""
    lane = _safe(lane)
    registration = _read(lane / "registration.json")
    store, budget = Path(registration["store"]), Budget(**registration["budget"])
    candidates = [Candidate.from_dict(c) for c in registration["candidates"]]
    if (lane.parent != store / "runs" or registration["schema"] != "mode5.research.jobs.v1"
            or type(registration["workers"]) is not int or not 1 <= registration["workers"] <= 3
            or not candidates or len({c.cell_id for c in candidates}) != len(candidates)):
        raise ValueError("invalid registered custody scope/schedule")
    with _lock(lane / "run.lock"):
        _seal(lane / "run.claim.json", dict(owner=process_identity(os.getpid()), time=_now()))
        journal = Journal(lane / "journal")
        journal.append("supervisor_start", owner=process_identity(os.getpid()), registration=file_identity(lane / "registration.json"))
        before, start = _space(store), time.monotonic()
        active, records, errors = [], {}, []
        interrupted = []

        def stop(sig, frame):
            interrupted.append(signal.Signals(sig).name)

        old_signals = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        reason, last = None, 0
        (lane / "scratch").mkdir()
        try:
            _subreaper()
            if (lane / "launch_requested.json").exists():
                verify_pins([_read(lane / "launch_requested.json")["registration"]])
            verify_pins([registration["native_gate"], registration["module"], registration["helper"]])
            _preflight(store, budget)
            pending = iter(candidates)
            exhausted = False
            while active or not exhausted:
                if interrupted:
                    reason = "SUPERVISOR_" + interrupted[0]
                    break
                reason, resources = _resource_reason(store, lane, budget, active, start)
                if reason:
                    break
                while len(active) < registration["workers"] and not exhausted:
                    if interrupted:
                        break
                    candidate = next(pending, None)
                    if candidate is None:
                        exhausted = True
                        break
                    verify_pins(candidate.pins)
                    attempt, lock, reused = _reserve(store, candidate, budget)
                    if reused:
                        records[candidate.cell_id] = reused
                        journal.append("reuse", **reused)
                        continue
                    try:
                        slot = _slot(store)
                    except Exception:
                        lock.__exit__(None, None, None)
                        raise
                    failure = _start(candidate, attempt, lock, slot, lane, journal, active)
                    if failure:
                        records[candidate.cell_id] = failure
                        reason = "TRANCHE_FAILURE_NO_RETRY"
                        break
                for job in list(active):
                    _progress(job)
                    if job["process"].poll() is not None:
                        receipt = _finish(job, budget, journal)
                        records[job["candidate"].cell_id] = receipt
                        active.remove(job)
                        if receipt["status"] != "COMPLETE":
                            reason = "TRANCHE_FAILURE_NO_RETRY"
                            break
                if reason:
                    break
                if time.monotonic() - last >= budget.heartbeat_seconds:
                    journal.append("progress", resources=resources,
                                   active=[dict(cell_id=j["candidate"].cell_id, owner=j["owner"],
                                                elapsed_seconds=time.monotonic()-j["start"],
                                                observed_lower_bounds=j["lower_bounds"]) for j in active])
                    last = time.monotonic()
                if active:
                    time.sleep(budget.poll_seconds)
        except BaseException as error:
            reason = "SUPERVISOR_FAULT"
            errors.append(repr(error))
            journal.append("failure", reason=reason, error=repr(error))
        finally:
            for job in active:
                try:
                    records[job["candidate"].cell_id] = _finish(job, budget, journal, reason or "SUPERVISOR_EXIT")
                except Exception as error:
                    errors.append("reap/receipt: " + repr(error))
            # Validation errors are data in the final receipt, never a precondition to writing it.
            for pin in [registration["native_gate"], registration["module"], registration["helper"]] + [p for c in candidates for p in c.pins]:
                try:
                    verify_pins([pin])
                except Exception as error:
                    errors.append(repr(error))
            reaped = all(r.get("all_owned_children_reaped", True) for r in records.values())
            for job in active:
                try:
                    reaped = reaped and not _members(job["owner"])
                except Exception as error:
                    reaped = False
                    errors.append("remaining custody: " + repr(error))
            protected = [p for c in candidates for p in c.pins]
            protected += [p for r in records.values() for p in
                          ([r["checkpoint"]] if r["status"] == "REUSED" else [r["log"]] if "log" in r else [])]
            for record in records.values():
                if "log" in record:
                    output = Path(record["log"]["path"]).parent / "output"
                    if output.exists():
                        try:
                            protected += _manifest(output)
                        except Exception as error:
                            errors.append("output inventory: " + repr(error))
            cleanup_errors, deleted = [], []
            try:
                verify_pins(protected)
            except Exception as error:
                cleanup_errors.append(repr(error))
            if reaped:
                for scratch in sorted((lane / "scratch").iterdir()):
                    try:
                        _tree(scratch)
                        shutil.rmtree(scratch)
                        deleted.append(str(scratch))
                    except Exception as error:
                        cleanup_errors.append(repr(error))
            try:
                verify_pins(protected)
            except Exception as error:
                cleanup_errors.append(repr(error))
            _seal(lane / "cleanup.json", dict(before=before, after=_space(store), deleted=deleted,
                  registered_scratch=str(lane / "scratch"), inactive_owned_only=reaped,
                  protected_pins=protected, hash_errors=cleanup_errors, evidence_deleted=False))
            errors.extend("cleanup: " + error for error in cleanup_errors)
            ordered = [records.get(c.cell_id, dict(cell_id=c.cell_id, status="NOT_LAUNCHED", exact_counts=None)) for c in candidates]
            complete = all(r["status"] in {"COMPLETE", "REUSED"} for r in ordered)
            final = dict(status="COMPLETE" if complete and not errors and reaped else "INCOMPLETE",
                         records=ordered, reason=reason, errors=errors, all_owned_children_reaped=reaped,
                         seconds=time.monotonic()-start, automatic_retries=0,
                         cleanup=file_identity(lane / "cleanup.json"), scientific_gate_complete=False)
            _seal(lane / "completion.json", final)
            journal.append("supervisor_completion", receipt=file_identity(lane / "completion.json"), status=final["status"])
            for sig, old in old_signals.items():
                signal.signal(sig, old)
        return final


def launch_background(lane):
    """Return a Popen handle; a fresh supervisor monitors after the launcher exits."""
    lane = _safe(lane)
    _read(lane / "registration.json")
    _seal(lane / "launch_requested.json", dict(time=_now(), registration=file_identity(lane / "registration.json")))
    argv = [sys.executable, "-B", "-m", "tools.mode5_research.jobs", "run", "--lane", str(lane)]
    root = Path(__file__).resolve().parents[2]
    with (lane / "supervisor.log").open("xb") as log:
        try:
            process = subprocess.Popen(argv, cwd=root, env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        except Exception as error:
            _seal(lane / "launch_failure.json", dict(error=repr(error), financial_executions=0))
            raise
    _seal(lane / "launched.json", dict(argv=argv, owner=process_identity(process.pid), time=_now()))
    return process


def watch(lane, *, receipt=None):
    """Read-only liveness report; heartbeat age never launches or signals work."""
    lane = _safe(lane)
    rows = read_journal(lane / "journal") if (lane / "journal").exists() else []
    supervisor = next((r["owner"] for r in rows if r["event"] == "supervisor_start"), None)
    if supervisor is None and (lane / "launched.json").exists():
        supervisor = _read(lane / "launched.json")["owner"]
    workers = []
    starts = [row for row in rows if row["event"] == "start"]
    journaled = {row["attempt"] for row in starts}
    for row in rows:
        if row["event"] == "launch" and row["attempt"] not in journaled:
            started = Path(row["attempt"]) / "started.json"
            if started.exists():
                receipt = _read(started)
                verify_pins([receipt["intent"], row["intent"]])
                starts.append(dict(cell_id=row["cell_id"], attempt=row["attempt"], owner=receipt["owner"]))
    for row in starts:
        owner, attempt = row["owner"], Path(row["attempt"])
        members = _members(owner)
        progress = attempt / "progress.jsonl"
        log_path = attempt / "process.log"
        observed = dict(progress=progress, log_path=log_path, lower_bounds={}, cursors={})
        for event in rows:
            if event["event"] == "progress":
                for active in event["active"]:
                    if active["owner"] == owner:
                        observed["lower_bounds"].update(active["observed_lower_bounds"])
        for path in (progress, log_path):
            if path.exists():
                observed["cursors"][str(path)] = dict(offset=max(0, path.stat().st_size-65536), tail=b"")
        _progress(observed)
        elapsed = None
        if members:
            elapsed = max(0, float(Path("/proc/uptime").read_text().split()[0]) -
                          owner["start_ticks"] / os.sysconf("SC_CLK_TCK"))
        process_receipt = _read(attempt / "receipt.json") if (attempt / "receipt.json").exists() else None
        workers.append(dict(cell_id=row["cell_id"], owner=owner, members=members,
                            live_elapsed_seconds=elapsed, observed_lower_bounds=observed["lower_bounds"],
                            start_journaled=row["attempt"] in journaled, receipt=process_receipt))
    completed = _read(lane / "completion.json") if (lane / "completion.json").exists() else None
    alive = is_live(supervisor) if supervisor else None
    report = dict(time=_now(), supervisor=supervisor, supervisor_live=alive, workers=workers,
                  last_event=rows[-1] if rows else None, completion=completed,
                  status="FINISHED" if completed else "LIVE" if alive else "CENSORED_OR_UNRESOLVED",
                  restart_permitted=False, financial_executions=0)
    if receipt:
        _seal(receipt, report)
    return report


def request_stop(lane):
    report = watch(lane)
    if not report["supervisor_live"]:
        raise RuntimeError("supervisor not identity-verified live; explicit worker custody review required")
    owner = report["supervisor"]
    if not is_live(owner):
        raise RuntimeError("supervisor identity changed")
    os.kill(owner["pid"], signal.SIGINT)
    return dict(signaled=owner, signal="SIGINT", financial_executions=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "register"):
        child = sub.add_parser(command)
        child.add_argument("--specs", type=Path, required=True)
        child.add_argument("--store", type=Path, required=True)
        child.add_argument("--budget", type=Path)
        if command == "register":
            child.add_argument("--lane", required=True)
            child.add_argument("--native-gate", type=Path, required=True)
            child.add_argument("--workers", type=int, default=1)
    for command in ("run", "launch", "watch", "stop"):
        child = sub.add_parser(command)
        child.add_argument("--lane", type=Path, required=True)
        if command == "watch":
            child.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.command in {"plan", "register"}:
        candidates = [Candidate.from_dict(c) for c in _read(args.specs)]
        budget = Budget(**_read(args.budget)) if args.budget else Budget()
        result = plan(candidates, args.store, budget) if args.command == "plan" else dict(
            lane=str(register(args.store, args.lane, candidates, native_gate=args.native_gate, workers=args.workers, budget=budget)))
    elif args.command == "run":
        result = run(args.lane)
    elif args.command == "launch":
        process = launch_background(args.lane)
        result = dict(pid=process.pid, lane=str(args.lane), monitored_background=True)
    elif args.command == "watch":
        result = watch(args.lane, receipt=args.receipt)
    else:
        result = request_stop(args.lane)
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
    return 1 if args.command == "run" and result["status"] != "COMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
