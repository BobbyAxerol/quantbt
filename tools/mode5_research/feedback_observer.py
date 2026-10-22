"""Durable observations around actual callbacks; no account or compiler logic."""

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter


SCHEMA = "mode5.actual_feedback_observer.v1"


def file_pin(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"regular pinned file required: {path}")
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=digest.hexdigest())


def seal_json(path, value):
    encoded = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


class PinMismatch(RuntimeError):
    pass


class FrozenPins:
    """Copy expected witnesses so callers cannot amend them after validation."""

    def __init__(self, pins):
        self._pins = deepcopy(tuple(pins))
        if not self._pins or len({p["path"] for p in self._pins}) != len(self._pins):
            raise ValueError("nonempty unique exact file pins required")
        for pin in self._pins:
            if (set(pin) != {"path", "bytes", "sha256"} or type(pin["bytes"]) is not int
                    or pin["bytes"] < 0 or not Path(pin["path"]).is_absolute()
                    or len(pin["sha256"]) != 64):
                raise ValueError("invalid file pin")

    @property
    def records(self):
        return deepcopy(self._pins)

    def verify(self):
        for pin in self._pins:
            try:
                actual = file_pin(pin["path"])
            except (OSError, ValueError) as error:
                raise PinMismatch(f"pinned file unavailable: {pin['path']}") from error
            if actual != pin:
                raise PinMismatch(f"pinned file changed: {pin['path']}")


class FeedbackObserver:
    """Single-worker journal. Returned accounts, not intentions, bill work.

    Failed/in-flight calls have unknown work. Completion is durable before a
    post-call guard can fail, so source faults do not erase completed passes.
    """

    def __init__(self, progress=None, *, guard=None, clock=perf_counter):
        self.identity = file_pin(__file__)
        self.path = Path(progress if progress is not None else os.environ["MODE5_JOB_PROGRESS"])
        self._stream = self.path.open("x", encoding="utf-8")
        self._clock = clock
        self.guard = guard
        self._started = clock()
        self._closed = False
        self._sequence = 0
        self._active = []
        self.completed_passes = 0
        self.completed_account_bars = 0
        self.attempted_calls = Counter()
        self.owner_passes = Counter()
        self.owner_bars = Counter()
        self.stage_seconds = Counter()
        self.stage_calls = Counter()
        self.stage_faults = Counter()

    def emit(self, stage, **fields):
        record = dict(fields, schema=SCHEMA, sequence=self._sequence, stage=stage,
                      elapsed_seconds=self._clock() - self._started,
                      completed_passes=self.completed_passes,
                      completed_account_bars=self.completed_account_bars)
        encoded = json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
        self._stream.write(encoded)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._sequence += 1

    def check(self):
        if self.guard is not None:
            self.guard()

    @contextmanager
    def timing(self, stage, **fields):
        started = self._clock()
        self.stage_calls[stage] += 1
        self._active.append(stage)
        self.emit(stage + "_started", **fields)
        try:
            yield
        except BaseException as error:
            seconds = self._clock() - started
            self.stage_seconds[stage] += seconds
            self.stage_faults[stage] += 1
            self.emit(stage + "_fault", seconds=seconds, error_type=type(error).__name__,
                      error=str(error), **fields)
            raise
        else:
            seconds = self._clock() - started
            self.stage_seconds[stage] += seconds
            self.emit(stage + "_complete", seconds=seconds, **fields)
        finally:
            self._active.pop()

    def call(self, stage, callback, *args, **kwargs):
        self.check()
        with self.timing(stage):
            result = callback(*args, **kwargs)
        self.check()
        return result

    def execute(self, owner, callback, *args, bars, **kwargs):
        """bars(result) supplies measured work; an exception never bills a pass."""
        if not isinstance(owner, str) or not owner:
            raise ValueError("named actual owner required")
        self.check()
        self.attempted_calls[owner] += 1
        with self.timing("execute", owner=owner):
            result = callback(*args, **kwargs)
            count = bars(result)
            if type(count) is not int or count < 0:
                raise ValueError("exact nonnegative actual account-bar count required")
            self.completed_passes += 1
            self.completed_account_bars += count
            self.owner_passes[owner] += 1
            self.owner_bars[owner] += count
            self.emit("account_complete", owner=owner, account_bars=count,
                      owner_completed_passes=self.owner_passes[owner])
        self.check()
        return result

    def summary(self):
        return dict(schema=SCHEMA, observer=deepcopy(self.identity), journal=str(self.path.resolve()),
                    actual_execution_calls=self.completed_passes,
                    visited_bars=self.completed_account_bars,
                    attempted_execution_calls=dict(self.attempted_calls),
                    completed_passes_by_owner=dict(self.owner_passes),
                    completed_account_bars_by_owner=dict(self.owner_bars),
                    stage_seconds=dict(self.stage_seconds), stage_calls=dict(self.stage_calls),
                    stage_faults=dict(self.stage_faults),
                    active_stages=list(self._active),
                    incomplete_work="UNKNOWN_NOT_ZERO", checkpoint_reuse=False)

    def fault_receipt(self, path, error, **fields):
        seal_json(path, dict(fields, status="FAULT", error_type=type(error).__name__,
                             error=str(error), work=self.summary()))

    def close(self):
        if not self._closed:
            self._stream.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
