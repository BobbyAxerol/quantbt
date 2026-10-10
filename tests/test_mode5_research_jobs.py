"""Cold subprocess custody fixtures. No alpha, native build or account imports."""

from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from tools.mode5_research import jobs


CHILD = r'''
import json, os, pathlib, signal, subprocess, sys, time
request = json.loads(pathlib.Path(os.environ["MODE5_JOB_REQUEST"]).read_text())
mode = request["mode"]
progress = pathlib.Path(os.environ["MODE5_JOB_PROGRESS"])
output = pathlib.Path(os.environ["MODE5_JOB_OUTPUT"])
scratch = pathlib.Path(os.environ["MODE5_JOB_SCRATCH"])
with progress.open("x") as stream:
    stream.write(json.dumps({"stage":"account_complete", "completed_passes":7})+"\n")
    stream.write('{"stage":"account_complete","completed_passes":true}\n')
    stream.write('{"stage":"not_complete","completed_account_bars":9999}\n')
    stream.write('invalid JSON\n')
    stream.flush()
    os.fsync(stream.fileno())
if mode == "stdout":
    progress.unlink()
    print(json.dumps({"stage":"account_complete", "completed_passes":7}), flush=True)
if mode == "fail":
    print("deliberate failure", flush=True)
    sys.exit(9)
if mode == "signal":
    os.kill(os.getpid(), signal.SIGTERM)
if mode in ("stall", "grandchild"):
    if mode == "grandchild":
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(60)"])
        (scratch/"grandchild.json").write_text(json.dumps({"pid":child.pid}))
    time.sleep(60)
if mode == "mutation":
    pathlib.Path(request["mutate"]).write_text("changed input\n")
if mode == "rss":
    allocation = bytearray(16 * 1024**2)
    time.sleep(1)
if mode == "disk":
    (scratch/"cache").write_bytes(b"x" * (1024**2))
    time.sleep(1)
if mode == "log":
    print("x" * (1024**2), flush=True)
    time.sleep(1)
if mode == "inodes":
    for n in range(30):
        (scratch/str(n)).touch()
    time.sleep(1)
time.sleep(request.get("delay", .03))
output.mkdir()
assert sys.argv[1:] == [str(output), os.environ["MODE5_JOB_REQUEST"]]
assert all(os.environ.get(key) == "1" for key in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS",
    "RAYON_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS"))
result = dict(status="PASS", request=request, actual_execution_calls=8, visited_bars=80,
              seed=request["seed"], pid=os.getpid(), marker=os.environ.get("STATE_LEAK"))
if mode == "wrong_request":
    result["request"] = request | {"seed":123}
if mode == "bad_count":
    result["actual_execution_calls"] = True
(output/"cell.json").write_text(json.dumps(result))
(output/"evidence.txt").write_text("domain evidence\n")
(scratch/"reproducible-cache").write_text("cache\n")
'''


@pytest.fixture
def fixture(tmp_path):
    child = tmp_path / "fake_child.py"
    child.write_text(CHILD)
    data = tmp_path / "source.txt"
    data.write_text("input\n")
    gate = tmp_path / "native_gate.json"
    gate.write_text('{"status":"PASS","fixture_only":true}\n')
    python = Path(sys.executable).resolve()
    budget = jobs.Budget(poll_seconds=.02, heartbeat_seconds=.08, terminate_seconds=.15,
                         cell_seconds=3, tranche_seconds=10)
    store = tmp_path / "store"

    def candidate(cell="candidate", mode="success", **kwargs):
        request = dict(mode=mode, seed=42, initial_equity=100, role="DEVELOPMENT",
                       start="2021-01-01", stop="2024-01-01", **kwargs)
        return jobs.Candidate.create(cell, request,
                [str(python), "-B", str(child), "{output}", "{request}"], tmp_path,
                [jobs.file_identity(p) for p in (python, child, data)],
                required_outputs=("cell.json", "evidence.txt"))

    def launch(candidates, lane="test", workers=1, limits=budget):
        path = jobs.register(store, lane, candidates, native_gate=gate, workers=workers, budget=limits)
        process = jobs.launch_background(path)
        return path, process

    return dict(candidate=candidate, launch=launch, store=store, budget=budget,
                data=data, gate=gate, child=child, tmp=tmp_path)


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError("fixture deadline exceeded")


def finished(lane, process, expected=0):
    try:
        code = process.wait(timeout=10)
        assert code == expected, (lane / "supervisor.log").read_text()
        receipt = jobs._read(lane / "completion.json")
        assert receipt["all_owned_children_reaped"]
        assert jobs._read(lane / "cleanup.json")["evidence_deleted"] is False
        return receipt
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=5)


def attempt(fixture, cell="candidate", number=1):
    return fixture["store"] / "cells" / cell / f"attempt-{number:04d}"


def test_success_three_fresh_workers_deterministic_order_and_reuse(fixture, monkeypatch):
    monkeypatch.setenv("STATE_LEAK", "must not propagate")
    specs = [fixture["candidate"](f"cell-{n}", delay=.25) for n in range(3)]
    lane, process = fixture["launch"](specs, workers=3)
    final = finished(lane, process)
    assert [r["cell_id"] for r in final["records"]] == [s.cell_id for s in specs]
    assert [r["exact_counts"] for r in final["records"]] == [dict(account_passes=8, account_bars=80)] * 3
    rows = jobs.read_journal(lane / "journal")
    assert {"launch", "start", "progress", "completion", "supervisor_completion"} <= {r["event"] for r in rows}
    starts = [r for r in rows if r["event"] == "start"]
    first_complete = next(i for i, r in enumerate(rows) if r["event"] == "completion")
    assert sum(r["event"] == "start" for r in rows[:first_complete]) == 3
    assert len({r["owner"]["pid"] for r in starts}) == 3
    for spec in specs:
        cell = jobs._read(attempt(fixture, spec.cell_id) / "output/cell.json")
        assert cell["seed"] == 42 and cell["marker"] is None
    cleanup = jobs._read(lane / "cleanup.json")
    assert len(cleanup["deleted"]) == 3 and not cleanup["hash_errors"]
    protected = [jobs.file_identity(p) for p in fixture["store"].glob("cells/*/attempt-*/*") if p.is_file()]
    lane2, process2 = fixture["launch"](specs, lane="resumed", workers=3)
    reused = finished(lane2, process2)
    assert [r["status"] for r in reused["records"]] == ["REUSED"] * 3
    assert not any(r["event"] == "launch" for r in jobs.read_journal(lane2 / "journal"))
    jobs.verify_pins(protected)


@pytest.mark.parametrize("mode,status", [("fail", "FAILED"), ("signal", "FAILED"),
    ("wrong_request", "VALIDATION_FAILED"), ("bad_count", "VALIDATION_FAILED")])
def test_failure_keeps_lower_bounds_unknown_exact_and_no_retry(fixture, mode, status):
    lane, process = fixture["launch"]([fixture["candidate"](mode=mode), fixture["candidate"]("pending")])
    final = finished(lane, process, 1)
    first = final["records"][0]
    assert first["status"] == status and first["exact_counts"] is None
    assert first["observed_lower_bounds"] == dict(account_passes=7)
    assert final["automatic_retries"] == 0
    assert final["records"][1]["status"] == "NOT_LAUNCHED"
    assert not (attempt(fixture) / "checkpoint.json").exists()
    assert len(list((fixture["store"] / "cells/candidate").glob("attempt-*"))) == 1
    assert any(r["event"] == "failure" for r in jobs.read_journal(lane / "journal"))


def test_source_mutation_still_writes_final_and_child_receipt(fixture):
    spec = fixture["candidate"](mode="mutation", mutate=str(fixture["data"]))
    lane, process = fixture["launch"]([spec])
    final = finished(lane, process, 1)
    assert final["records"][0]["status"] == "VALIDATION_FAILED"
    assert final["errors"] and jobs._read(lane / "cleanup.json")["hash_errors"]
    assert jobs._read(attempt(fixture) / "receipt.json")["exact_counts"] is None
    assert not (attempt(fixture) / "checkpoint.json").exists()
    assert (attempt(fixture) / "output/evidence.txt").exists()


@pytest.mark.parametrize("mode,limit,reason", [
    ("stall", dict(cell_seconds=.15), "CELL_TIME_CAP"),
    ("rss", dict(worker_rss_bytes=1), "WORKER_RSS_CAP"),
    ("rss", dict(total_rss_bytes=1), "TOTAL_RSS_CAP"),
    ("disk", dict(scratch_bytes=128), "SCRATCH_CAP"),
    ("log", dict(retained_bytes=512*1024), "RETAINED_CAP"),
    ("inodes", dict(scratch_inodes=5), "SCRATCH_CAP"),
    ("stall", dict(tranche_seconds=.15), "TRANCHE_TIME_CAP"),
])
def test_safety_caps_censor_without_economic_result(fixture, mode, limit, reason):
    budget = replace(fixture["budget"], **limit)
    lane, process = fixture["launch"]([fixture["candidate"](mode=mode)], limits=budget)
    final = finished(lane, process, 1)
    assert final["reason"] == reason
    assert final["records"][0]["status"] == "CENSORED"
    assert final["records"][0]["exact_counts"] is None


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_supervisor_interrupt_records_inflight_and_reaps_grandchild(fixture, sig):
    lane, process = fixture["launch"]([fixture["candidate"](mode="grandchild")])
    try:
        started = wait_for(lambda: (attempt(fixture) / "started.json").exists())
        assert started
        grandchild = wait_for(lambda: list((lane / "scratch").glob("*/grandchild.json")))
        descendant = jobs.process_identity(jobs._read(grandchild[0])["pid"])
        process.send_signal(sig)
        final = finished(lane, process, 1)
        assert final["records"][0]["status"] == "CENSORED"
        assert final["records"][0]["observed_lower_bounds"] == dict(account_passes=7)
        assert jobs.process_identity(descendant["pid"]) != descendant
        assert any(r["event"] == "interrupt" for r in jobs.read_journal(lane / "journal"))
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=5)


def test_readonly_watcher_stale_heartbeat_and_live_candidate_collision(fixture):
    spec = fixture["candidate"](mode="stall")
    lane, process = fixture["launch"]([spec])
    try:
        wait_for(lambda: (attempt(fixture) / "started.json").exists())
        # Stopping the live supervisor freezes heartbeat age without changing PID/start.
        process.send_signal(signal.SIGSTOP)
        time.sleep(.15)
        before = list(fixture["store"].rglob("*"))
        first = jobs.watch(lane)
        assert first["supervisor_live"] and not first["restart_permitted"]
        assert before == list(fixture["store"].rglob("*"))
        assert first["workers"][0]["live_elapsed_seconds"] >= .1
        assert first["workers"][0]["observed_lower_bounds"] == dict(account_passes=7)
        assert jobs.watch(lane)["status"] == "LIVE"
        lane2, process2 = fixture["launch"]([spec], lane="collision")
        collided = finished(lane2, process2, 1)
        assert "live owner" in str(collided["errors"])
        assert not attempt(fixture, number=2).exists()
        with pytest.raises(FileExistsError):
            jobs.launch_background(lane)
    finally:
        process.send_signal(signal.SIGCONT)
        jobs.request_stop(lane)
        finished(lane, process, 1)


def test_fresh_attempt_after_censor_and_bounded_retry_across_runs(fixture):
    spec = fixture["candidate"](mode="stall")
    limits = replace(fixture["budget"], cell_seconds=.12, max_attempts=2)
    original_pins = []
    for n in (1, 2):
        lane, process = fixture["launch"]([spec], lane=f"tranche-{n}", limits=limits)
        final = finished(lane, process, 1)
        assert final["records"][0]["status"] == "CENSORED"
        jobs.verify_pins(original_pins)
        original_pins.extend(jobs.file_identity(p) for p in attempt(fixture, number=n).rglob("*") if p.is_file())
    assert jobs._read(attempt(fixture) / "started.json")["owner"] != jobs._read(attempt(fixture, number=2) / "started.json")["owner"]
    lane3, process3 = fixture["launch"]([spec], lane="tranche-3", limits=limits)
    final = finished(lane3, process3, 1)
    assert "attempt budget" in str(final["errors"])
    assert not attempt(fixture, number=3).exists()
    jobs.verify_pins(original_pins)


def test_censored_candidate_can_complete_in_new_attempt_with_identical_request(fixture):
    spec = fixture["candidate"](delay=.3)
    lane, process = fixture["launch"]([spec], limits=replace(fixture["budget"], cell_seconds=.12))
    assert finished(lane, process, 1)["records"][0]["status"] == "CENSORED"
    original = jobs._manifest(attempt(fixture))
    lane2, process2 = fixture["launch"]([spec], lane="resume")
    assert finished(lane2, process2)["records"][0]["status"] == "COMPLETE"
    assert jobs._read(attempt(fixture) / "request.json") == jobs._read(attempt(fixture, number=2) / "request.json")
    jobs.verify_pins(original)


def test_supervisor_sigkill_never_allows_duplicate_live_worker(fixture):
    jobs._subreaper()
    spec = fixture["candidate"](mode="stall")
    lane, process = fixture["launch"]([spec])
    owner = None
    try:
        wait_for(lambda: (attempt(fixture) / "started.json").exists())
        owner = jobs._read(attempt(fixture) / "started.json")["owner"]
        process.kill()
        assert process.wait(timeout=5) == -signal.SIGKILL
        report = jobs.watch(lane)
        assert not report["supervisor_live"] and report["workers"][0]["members"]
        assert report["completion"] is None and not report["restart_permitted"]
        lane2, process2 = fixture["launch"]([spec], lane="no-orphan-duplicate")
        final = finished(lane2, process2, 1)
        assert final["errors"] and not attempt(fixture, number=2).exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if owner:
            jobs._signal_group(owner, signal.SIGKILL)
            # The test process is a subreaper for the orphaned fixture worker.
            try:
                os.waitpid(owner["pid"], 0)
            except ChildProcessError:
                pass


def test_old_boot_is_dead_and_incorrect_namespace_is_unresolved():
    owner = jobs.process_identity(os.getpid())
    assert not jobs.is_live(owner | dict(boot_id="prior-host-boot"))
    assert jobs._members(owner | dict(boot_id="prior-host-boot")) == []
    with pytest.raises(RuntimeError, match="namespace"):
        jobs.is_live(owner | dict(pid_namespace="different-namespace"))


@pytest.mark.parametrize("change", ["request", "artifact", "extra", "receipt"])
def test_resume_rejects_request_or_manifest_collisions(fixture, change):
    spec = fixture["candidate"]()
    lane, process = fixture["launch"]([spec])
    finished(lane, process)
    if change == "request":
        spec = replace(spec, request_json=spec.request_json.replace('"seed": 42', '"seed": 43'))
    elif change == "artifact":
        (attempt(fixture) / "output/evidence.txt").write_text("mutated")
    elif change == "extra":
        (attempt(fixture) / "output/extra").touch()
    else:
        (attempt(fixture) / "receipt.json").write_text('{"status":"COMPLETE"}')
    lane2, process2 = fixture["launch"]([spec], lane="resume")
    final = finished(lane2, process2, 1)
    assert final["errors"] and not attempt(fixture, number=2).exists()


def test_plan_no_execution_no_writes_nooverwrite_and_pin_gate(fixture):
    spec = fixture["candidate"]()
    assert jobs.plan([spec], fixture["store"])["financial_executions"] == 0
    assert not fixture["store"].exists()
    lane = jobs.register(fixture["store"], "test", [spec], native_gate=fixture["gate"])
    with pytest.raises(FileExistsError):
        jobs.register(fixture["store"], "test", [spec], native_gate=fixture["gate"])
    with pytest.raises(ValueError):
        jobs.register(fixture["store"], "bad", [spec], native_gate=fixture["gate"], workers=4)
    fixture["data"].write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        jobs.plan([spec], fixture["store"])
    assert not (lane / "run.claim.json").exists()


def test_adopt_verified_history_requires_manifest_and_domain_qualification(fixture):
    spec = fixture["candidate"]()
    output = fixture["tmp"] / "historical"
    output.mkdir()
    (output / "cell.json").write_text(json.dumps(dict(status="PASS", request=json.loads(spec.request_json),
                                                     actual_execution_calls=3, visited_bars=30)))
    (output / "evidence.txt").write_text("retained historical evidence")
    manifest = jobs._manifest(output)
    qualification = fixture["tmp"] / "qualification.json"
    qualification.write_text(json.dumps(dict(status="PASS", candidate_key=spec.key, artifacts=manifest)))
    receipt = jobs.adopt_completed(fixture["store"], spec, output, manifest=manifest, qualification=qualification)
    assert receipt["financial_executions"] == 0 and receipt["exact_counts"]["account_passes"] == 3
    lane, process = fixture["launch"]([spec], lane="resume-history")
    assert finished(lane, process)["records"][0]["status"] == "REUSED"
    (output / "evidence.txt").write_text("changed")
    with pytest.raises(ValueError):
        jobs.adopt_completed(fixture["store"], spec, output, manifest=manifest, qualification=qualification)


def test_argv_is_not_shell_pid_reuse_and_journal_tamper_fail_closed(fixture):
    spec = fixture["candidate"]()
    shell_marker = fixture["tmp"] / "shell-executed"
    spec = replace(spec, argv=spec.argv + (f";touch {shell_marker}",))
    lane, process = fixture["launch"]([spec])
    finished(lane, process, 1)
    assert not shell_marker.exists()
    owner = jobs.process_identity(os.getpid())
    with pytest.raises(RuntimeError, match="PID reused"):
        jobs._signal_group(owner | dict(start_ticks=owner["start_ticks"]+1), signal.SIGTERM)
    event = lane / "journal/00000001.json"
    row = jobs._read(event)
    event.write_text(json.dumps(row | dict(previous="false")))
    with pytest.raises(ValueError, match="chain"):
        jobs.watch(lane)


def test_path_and_budget_guards(fixture, monkeypatch):
    spec = fixture["candidate"]()
    with pytest.raises(ValueError):
        replace(spec, required_outputs=("../escape",))
    with pytest.raises(ValueError):
        replace(spec, argv="echo bad")
    with pytest.raises(ValueError):
        replace(spec, env=(("OMP_NUM_THREADS", "2"),))
    with pytest.raises(ValueError):
        replace(spec, required_outputs=["cell.json", "evidence.txt"])
    with pytest.raises(ValueError):
        jobs.Budget(reserve_bytes=1)
    with pytest.raises(ValueError):
        jobs.Budget(max_attempts=100)
    with pytest.raises(ValueError):
        jobs.Budget(poll_seconds=float("nan"))
    linked = fixture["tmp"] / "linked"
    linked.symlink_to(fixture["tmp"], target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        jobs.plan([spec], linked / "store")
    monkeypatch.setattr(jobs, "_space", lambda path: dict(free_bytes=100*jobs.GIB, free_inodes=0))
    with pytest.raises(RuntimeError, match="inode"):
        jobs.plan([spec], fixture["store"])


def test_native_gate_mutation_emits_completion_without_launch(fixture):
    spec = fixture["candidate"]()
    lane = jobs.register(fixture["store"], "test", [spec], native_gate=fixture["gate"], budget=fixture["budget"])
    fixture["gate"].write_text('{"status":"FAIL"}')
    process = jobs.launch_background(lane)
    final = finished(lane, process, 1)
    assert final["errors"] and final["records"][0]["status"] == "NOT_LAUNCHED"


def test_host_reserve_runtime_gate_and_launch_fault_receipt(fixture):
    spec = fixture["candidate"]()
    spec = replace(spec, argv=(spec.argv[0], "-B", "missing-file.py", "{output}", "{request}"))
    lane, process = fixture["launch"]([spec])
    final = finished(lane, process, 1)
    assert final["records"][0]["status"] == "FAILED"
    assert final["records"][0]["exit_code"] != 0


def test_os_launch_failure_is_a_receipted_attempt(fixture):
    spec = fixture["candidate"]()
    executable = fixture["tmp"] / "not_executable"
    executable.write_text("not an executable")
    spec = replace(spec, argv=(str(executable), "{output}", "{request}"),
                   pins_json=json.dumps(spec.pins + [jobs.file_identity(executable)]))
    lane, process = fixture["launch"]([spec])
    final = finished(lane, process, 1)
    assert final["records"][0]["status"] == "LAUNCH_FAILED"
    assert final["records"][0]["financial_executions"] == 0
    assert jobs._read(attempt(fixture) / "receipt.json")["exact_counts"] is None


def test_existing_stdout_account_progress_is_retained(fixture):
    lane, process = fixture["launch"]([fixture["candidate"](mode="stdout")])
    final = finished(lane, process)
    assert not (attempt(fixture) / "progress.jsonl").exists()
    assert final["records"][0]["observed_lower_bounds"] == dict(account_passes=7)
    assert jobs.watch(lane)["workers"][0]["observed_lower_bounds"] == dict(account_passes=7)


def test_cli_launcher_exits_while_detached_supervisor_monitors(fixture):
    jobs._subreaper()
    spec = fixture["candidate"](delay=.4)
    lane = jobs.register(fixture["store"], "cli", [spec], native_gate=fixture["gate"], budget=fixture["budget"])
    root = Path(jobs.__file__).resolve().parents[2]
    launched = subprocess.run([sys.executable, "-B", "-m", "tools.mode5_research.jobs", "launch", "--lane", str(lane)],
                              cwd=root, capture_output=True, text=True, check=True, timeout=5)
    pid = json.loads(launched.stdout)["pid"]
    try:
        assert not (lane / "completion.json").exists()
        wait_for(lambda: (attempt(fixture) / "started.json").exists())
        assert jobs.watch(lane)["supervisor_live"]
        wait_for(lambda: (lane / "completion.json").exists())
        assert jobs._read(lane / "completion.json")["status"] == "COMPLETE"
    finally:
        owner = jobs._read(lane / "launched.json")["owner"]
        if jobs.is_live(owner) and not (lane / "completion.json").exists():
            jobs.request_stop(lane)
        os.waitpid(pid, 0)


def test_watcher_receipt_nooverwrite_and_exact_terminal_counts(fixture):
    lane, process = fixture["launch"]([fixture["candidate"]()])
    final = finished(lane, process)
    path = fixture["tmp"] / "watch.json"
    report = jobs.watch(lane, receipt=path)
    assert report["completion"] == final
    assert report["workers"][0]["receipt"]["exact_counts"] == dict(account_passes=8, account_bars=80)
    assert report["workers"][0]["receipt"]["seconds"] > 0
    with pytest.raises(FileExistsError):
        jobs.watch(lane, receipt=path)
