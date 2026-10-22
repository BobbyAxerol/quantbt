"""Synthetic cold-process orchestration only: no alpha, market, or finance imports."""

import fcntl
import gzip
import json
import os
import signal
import sys
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.mode5_research import completion_queue as queue_module
from tools.mode5_research.completion_queue import (
    ExpectedOutput,
    FilePin,
    QueueCancelled,
    QueueError,
    QueueSpec,
    ResourceLimits,
    ResourceUsage,
    Stage,
    THREAD_ENV,
    UpstreamReceipt,
    run_queue,
    sample_resources,
)


COMPLETE = "COMPLETE_REGISTERED_PRIVATE_MODE5_STUDY"
GOOD = ResourceUsage(10**9, 10**9, 0, 1)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def read(path):
    return json.loads(path.read_text())


def stage(tmp_path, name, body="", *, outputs=None, inputs=(), forecast_bytes=0):
    root = tmp_path / "retained"
    source = tmp_path / f"{name}.py"
    output = root / f"{name}.json"
    source.write_text(
        "import json, os, sys, time\nfrom pathlib import Path\n"
        "output = Path(sys.argv[1])\n"
        "with (output.parent / 'calls.log').open('a') as stream:\n"
        f"    stream.write({name!r} + '\\n')\n"
        + body + "\n"
        "with output.open('x') as stream:\n"
        "    json.dump(dict(status='DONE', cwd=os.getcwd(),\n"
        "        threads={k: os.environ.get(k) for k in " + repr(tuple(THREAD_ENV)) + "}), stream)\n"
        "print('stage output retained', flush=True)\n",
        encoding="utf-8",
    )
    return Stage(name, (sys.executable, str(source), str(output)), tmp_path,
        (FilePin.capture(source),), outputs or (ExpectedOutput(output, "DONE"),),
        inputs=inputs, forecast_bytes=forecast_bytes)


def spec(tmp_path, stages=None):
    root = tmp_path / "retained"
    root.mkdir(exist_ok=True)
    upstream = []
    for index in range(9):
        path = root / "studies" / f"{index}.json"
        write_json(path, dict(status=COMPLETE, attempts=256))
        upstream.append(UpstreamReceipt(str(index), path, COMPLETE, expected_pin=FilePin.capture(path)))
    limits = ResourceLimits(min_free_bytes=100, min_available_memory_bytes=100,
        max_retained_bytes=1024**2, max_owned_rss_bytes=10**8,
        max_wall_seconds=10, lock_timeout_seconds=2, poll_seconds=.01,
        terminate_grace_seconds=.1)
    return QueueSpec("synthetic-tail", root / "receipts", root / "queue.lock", root,
        tuple(upstream), tuple(stages or (stage(tmp_path, "winner"),)), limits,
        deadline_ns=time.time_ns() + 60_000_000_000)


def terminals(queue, name):
    return sorted(queue.receipt_dir.glob(f"{name}.*.terminal.json"))


def good_resources(_spec, _child_pid):
    return GOOD


def test_nine_upstream_receipts_then_ordered_serial_tail_and_no_rerun(tmp_path, monkeypatch):
    first = stage(tmp_path, "winners")
    second = stage(tmp_path, "synthesis", "assert (output.parent / 'winners.json').exists()")
    third = stage(tmp_path, "qualification", "assert (output.parent / 'synthesis.json').exists()")
    queue = spec(tmp_path, (first, second, third))
    monkeypatch.setenv("OMP_NUM_THREADS", "17")
    result = run_queue(queue, resources=good_resources)
    assert result["status"] == "PASS"
    assert len(result["upstream"]) == 9
    assert (queue.retained_root / "calls.log").read_text().splitlines() == [
        "winners", "synthesis", "qualification"]
    for item in queue.stages:
        data = read(item.outputs[0].path)
        assert data["cwd"] == str(tmp_path)
        assert data["threads"] == THREAD_ENV
        terminal = read(terminals(queue, item.name)[0])
        assert terminal["status"] == "PASS"
        assert terminal["exit_code"] == 0
        assert Path(terminal["log"]["path"]).read_text() == "stage output retained\n"
        FilePin(**terminal["start"]).verify()
    before = {p: p.read_bytes() for p in queue.receipt_dir.glob("*.*.json")}
    assert run_queue(queue, resources=good_resources)["outputs"] == result["outputs"]
    assert len((queue.retained_root / "calls.log").read_text().splitlines()) == 3
    assert all(p.read_bytes() == data for p, data in before.items())
    assert len(terminals(queue, "winners")) == 1


@pytest.mark.parametrize("problem", ("missing", "status", "attempts", "bool-attempts", "pin"))
def test_upstream_owner_has_stopped_but_one_receipt_invalid_fails_closed(tmp_path, problem):
    queue = spec(tmp_path)
    owner = queue.upstream[-1]
    if problem == "missing":
        owner.path.unlink()
    elif problem == "pin":
        owner.path.write_text(owner.path.read_text() + "\n")
    else:
        write_json(owner.path, dict(status="FAIL_RETAINED" if problem == "status" else COMPLETE,
            attempts=True if problem == "bool-attempts" else 255 if problem == "attempts" else 256))
        queue = replace(queue, upstream=(*queue.upstream[:-1], replace(owner, expected_pin=None)))
    with pytest.raises(QueueError):
        run_queue(queue, resources=good_resources)
    assert not (queue.retained_root / "calls.log").exists()
    assert len(list(queue.receipt_dir.glob("queue-*.terminal.json"))) == 1
    assert not terminals(queue, "winner")


def test_future_receipts_are_pinned_after_shared_lock_is_released(tmp_path):
    queue = spec(tmp_path)
    late = queue.upstream[-1]
    late.path.unlink()
    queue = replace(queue, upstream=(*queue.upstream[:-1], replace(late, expected_pin=None)))
    lock = queue.shared_lock.open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    outcome = []

    def run():
        try:
            outcome.append(run_queue(queue, resources=good_resources))
        except BaseException as error:
            outcome.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 2
        while not list(queue.receipt_dir.glob("queue-*.start.json")) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not (queue.retained_root / "calls.log").exists()
        write_json(late.path, dict(status=COMPLETE, attempts=256))
    finally:
        lock.close()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert outcome[0]["status"] == "PASS"
    assert FilePin(**outcome[0]["upstream"][-1]) == FilePin.capture(late.path)


def test_shared_lock_has_bounded_wait_and_never_signals_upstream(tmp_path):
    queue = spec(tmp_path)
    queue = replace(queue, limits=replace(queue.limits, lock_timeout_seconds=.035))
    with queue.shared_lock.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(QueueError, match="lock wait timeout"):
            run_queue(queue, resources=good_resources)
    assert not (queue.retained_root / "calls.log").exists()


@pytest.mark.parametrize("field,value,match", (
    ("free_bytes", 99, "disk"),
    ("available_memory_bytes", 99, "RAM"),
    ("retained_bytes", 1024**2 + 1, "retained"),
    ("owned_rss_bytes", 10**8 + 1, "RSS"),
    ("owned_rss_bytes", -1, "telemetry"),
))
def test_resource_guards_do_not_start_any_stage(tmp_path, field, value, match):
    queue = spec(tmp_path)
    with pytest.raises(QueueError, match=match):
        run_queue(queue, resources=lambda *_: replace(GOOD, **{field: value}))
    assert not (queue.retained_root / "calls.log").exists()


def test_remaining_forecast_is_reserved_before_launch(tmp_path):
    queue = spec(tmp_path, (stage(tmp_path, "winner", forecast_bytes=1000),))
    with pytest.raises(QueueError, match="disk"):
        run_queue(queue, resources=lambda *_: replace(GOOD, free_bytes=500))
    assert not (queue.retained_root / "calls.log").exists()


def test_inflight_guard_reaps_only_owned_child_and_retains_partial_outputs(tmp_path):
    job = stage(tmp_path, "winner", "output.with_suffix('.partial').write_text(str(os.getpid()))\ntime.sleep(10)")
    queue = spec(tmp_path, (job,))

    def resources(_spec, child_pid):
        partial = queue.retained_root / "winner.partial"
        if child_pid is not None and partial.exists():
            return replace(GOOD, available_memory_bytes=1)
        return GOOD

    with pytest.raises(QueueError, match="RAM"):
        run_queue(queue, resources=resources)
    partial = queue.retained_root / "winner.partial"
    assert partial.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(partial.read_text()), 0)
    terminal = read(terminals(queue, "winner")[0])
    assert terminal["status"] == "FAIL_RETAINED"
    assert terminal["exit_code"] is not None
    assert Path(terminal["log"]["path"]).exists()


@pytest.mark.parametrize("failure", ("nonzero", "missing-output", "bad-status", "source-write"))
def test_stage_failure_blocks_dependent_stages_and_cannot_autoretry(tmp_path, failure):
    body = {
        "nonzero": "print('retained failure', flush=True)\nsys.exit(7)",
        "missing-output": "sys.exit(0)",
        "bad-status": "output.write_text('{\"status\": \"NOT_DONE\"}')\nsys.exit(0)",
        "source-write": "Path(__file__).write_text('mutated')",
    }[failure]
    first = stage(tmp_path, "winner", body)
    second = stage(tmp_path, "synthesis")
    queue = spec(tmp_path, (first, second))
    with pytest.raises(QueueError):
        run_queue(queue, resources=good_resources)
    assert not second.outputs[0].path.exists()
    terminal = read(terminals(queue, "winner")[0])
    assert terminal["status"] == "FAIL_RETAINED"
    before = (queue.retained_root / "calls.log").read_bytes()
    with pytest.raises(QueueError):
        run_queue(queue, resources=good_resources)
    assert (queue.retained_root / "calls.log").read_bytes() == before


def test_interrupted_start_and_orphan_outputs_require_explicit_recovery(tmp_path):
    queue = spec(tmp_path)
    queue.receipt_dir.mkdir()
    write_json(queue.receipt_dir / "winner.123.start.json", dict(status="STARTED"))
    with pytest.raises(QueueError, match="interrupted stage"):
        run_queue(queue, resources=good_resources)
    assert not (queue.retained_root / "calls.log").exists()


def test_unreceipted_authoritative_output_is_never_overwritten(tmp_path):
    queue = spec(tmp_path)
    output = queue.stages[0].outputs[0].path
    output.write_text("old evidence")
    with pytest.raises(QueueError, match="unreceipted outputs"):
        run_queue(queue, resources=good_resources)
    assert output.read_text() == "old evidence"


@pytest.mark.parametrize("changed", ("output", "log", "source", "input", "upstream", "command", "cwd"))
def test_successful_stage_never_reused_or_rerun_with_stale_identity(tmp_path, changed):
    source_input = tmp_path / "frozen-input.json"
    write_json(source_input, dict(value=1))
    job = stage(tmp_path, "winner", inputs=(FilePin.capture(source_input),))
    queue = spec(tmp_path, (job,))
    run_queue(queue, resources=good_resources)
    if changed == "output":
        job.outputs[0].path.write_text('{"status":"DONE","changed":true}')
    elif changed == "log":
        terminal = read(terminals(queue, "winner")[0])
        Path(terminal["log"]["path"]).write_text("changed log")
    elif changed == "source":
        job.sources[0].path.write_text("changed source")
    elif changed == "input":
        write_json(source_input, dict(value=2))
    elif changed == "upstream":
        upstream = queue.upstream[0]
        write_json(upstream.path, dict(status=COMPLETE, attempts=256, changed=True))
        queue = replace(queue, upstream=(replace(upstream, expected_pin=None), *queue.upstream[1:]))
    elif changed == "command":
        queue = replace(queue, stages=(replace(job, command=(*job.command, "changed")),))
    else:
        cwd = tmp_path / "other-cwd"
        cwd.mkdir()
        queue = replace(queue, stages=(replace(job, cwd=cwd),))
    with pytest.raises(QueueError):
        run_queue(queue, resources=good_resources)
    assert len((queue.retained_root / "calls.log").read_text().splitlines()) == 1


def test_downstream_failure_reuses_verified_previous_pass_without_optimizer_reexecution(tmp_path):
    first = stage(tmp_path, "winner")
    second = stage(tmp_path, "synthesis", "sys.exit(3)")
    queue = spec(tmp_path, (first, second))
    for _ in range(2):
        with pytest.raises(QueueError):
            run_queue(queue, resources=good_resources)
    assert (queue.retained_root / "calls.log").read_text().splitlines() == ["winner", "synthesis"]
    assert len(terminals(queue, "winner")) == len(terminals(queue, "synthesis")) == 1


def test_original_absolute_deadline_not_reset_by_new_tail_invocation(tmp_path):
    queue = replace(spec(tmp_path), deadline_ns=time.time_ns() - 1)
    with pytest.raises(QueueError, match="original launch deadline"):
        run_queue(queue, resources=good_resources)
    assert not (queue.retained_root / "calls.log").exists()


def test_monotonic_wall_guard_during_child_retains_failure(tmp_path, monkeypatch):
    queue = spec(tmp_path, (stage(tmp_path, "winner", "time.sleep(10)"),))
    clock = [time.monotonic()]
    monkeypatch.setattr(queue_module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time_ns=time.time_ns, sleep=time.sleep))

    def resources(_spec, child_pid):
        if child_pid is not None:
            clock[0] += 11
        return GOOD

    with pytest.raises(QueueError, match="wall guard"):
        run_queue(queue, resources=resources)
    assert read(terminals(queue, "winner")[0])["status"] == "FAIL_RETAINED"


def test_downstream_cannot_modify_preceding_pinned_outputs(tmp_path):
    first = stage(tmp_path, "winner")
    second = stage(tmp_path, "synthesis", "(output.parent / 'winner.json').write_text('changed')")
    queue = spec(tmp_path, (first, second))
    with pytest.raises(QueueError, match="file pin mismatch"):
        run_queue(queue, resources=good_resources)
    assert read(terminals(queue, "winner")[0])["status"] == "PASS"
    assert read(terminals(queue, "synthesis")[0])["status"] == "FAIL_RETAINED"


def test_cancel_event_preserves_evidence_and_does_not_launch_following_stage(tmp_path):
    event = threading.Event()
    queue = spec(tmp_path, (stage(tmp_path, "winner", "time.sleep(10)"), stage(tmp_path, "synthesis")))

    def resources(_spec, child_pid):
        if child_pid is not None:
            event.set()
        return GOOD

    with pytest.raises(QueueCancelled):
        run_queue(queue, resources=resources, cancel=event)
    assert read(terminals(queue, "winner")[0])["status"] == "CANCELLED_RETAINED"
    assert not queue.stages[1].outputs[0].path.exists()


def test_sigterm_reaps_owned_child_and_restores_prior_handler(tmp_path):
    queue = spec(tmp_path, (stage(tmp_path, "winner", "time.sleep(10)"),))
    previous = signal.getsignal(signal.SIGTERM)
    sent = False

    def resources(_spec, child_pid):
        nonlocal sent
        if child_pid is not None and not sent:
            sent = True
            os.kill(os.getpid(), signal.SIGTERM)
        return GOOD

    with pytest.raises(QueueCancelled, match="signal"):
        run_queue(queue, resources=resources)
    assert signal.getsignal(signal.SIGTERM) == previous
    assert read(terminals(queue, "winner")[0])["status"] == "CANCELLED_RETAINED"


def test_gzip_outputs_and_explicit_custom_status_fields(tmp_path):
    job = stage(tmp_path, "winner", "import gzip\n"
        "with gzip.open(output.with_suffix('.json.gz'), 'wt') as stream:\n"
        "    json.dump({'disposition':'QUALIFIED'}, stream)\nsys.exit(0)",
        outputs=(ExpectedOutput(tmp_path / "retained/winner.json.gz", "QUALIFIED", "disposition"),))
    queue = spec(tmp_path, (job,))
    assert run_queue(queue, resources=good_resources)["status"] == "PASS"
    with gzip.open(job.outputs[0].path, "rt") as stream:
        assert json.load(stream)["disposition"] == "QUALIFIED"


def test_new_output_cannot_escape_retained_budget_through_symlink(tmp_path):
    elsewhere = tmp_path / "elsewhere.json"
    write_json(elsewhere, dict(status="DONE"))
    job = stage(tmp_path, "winner", f"output.symlink_to({str(elsewhere)!r})\nsys.exit(0)")
    queue = spec(tmp_path, (job,))
    with pytest.raises(QueueError, match="escaped its registration"):
        run_queue(queue, resources=good_resources)
    assert elsewhere.exists()
    assert read(terminals(queue, "winner")[0])["status"] == "FAIL_RETAINED"


def test_spec_rejects_incomplete_roster_duplicates_relative_paths_and_overwrites(tmp_path):
    queue = spec(tmp_path)
    with pytest.raises(ValueError, match="full upstream"):
        replace(queue, upstream=queue.upstream[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        replace(queue, upstream=(*queue.upstream[:-1], queue.upstream[0]))
    with pytest.raises(ValueError, match="distinct"):
        replace(queue, stages=(queue.stages[0], replace(queue.stages[0], name="other")))
    with pytest.raises(ValueError, match="overwrite"):
        replace(queue, stages=(replace(queue.stages[0], outputs=(queue.upstream[0].path,)),))
    with pytest.raises(ValueError, match="absolute executable"):
        replace(queue.stages[0], command=("python", "file.py"))
    with pytest.raises(ValueError, match="absolute path"):
        replace(queue.stages[0], cwd=Path("."))
    with pytest.raises(ValueError, match="count toward retained"):
        replace(queue, stages=(replace(queue.stages[0], outputs=(tmp_path / "outside.json",)),))
    with pytest.raises(ValueError, match="receipt directory"):
        replace(queue, stages=(replace(queue.stages[0], outputs=(queue.receipt_dir / "overwrite.json",)),))


def test_real_resource_reader_uses_only_synthetic_retained_files(tmp_path):
    queue = spec(tmp_path)
    shared = queue.retained_root / "one-copy"
    shared.write_bytes(b"synthetic" * 100)
    os.link(shared, shared.with_name("same-inode"))
    usage = sample_resources(queue, None)
    assert usage.free_bytes > 0
    assert usage.available_memory_bytes > 0
    assert usage.owned_rss_bytes > 0
    assert usage.retained_bytes == shared.stat().st_size + sum(row.path.stat().st_size for row in queue.upstream)
    assert asdict(usage).keys() == {"free_bytes", "available_memory_bytes", "retained_bytes", "owned_rss_bytes"}
