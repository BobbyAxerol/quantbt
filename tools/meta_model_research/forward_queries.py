"""Bounded ML07 queries through the unchanged original financial observer."""

from pathlib import Path
import signal
import time

from .admission import pin, read, save_new
from .decision_queries import OriginalQueries
from .decision_value import DEFAULT as PREVIOUS
from .protocol import GROUPS
from .forward_study import DEFAULT, existing_queries, guard, verify


def register_queries(output=DEFAULT):
    verify(output)
    rows = read(output / "sealed.json")["rows"]
    existing = existing_queries()
    ids = {r["request"]["query_id"] for r in existing}
    pending = [
        r
        for r in rows
        if r["policy"] in ("QD", "QF")
        and r["witness_status"] == "MISSING_EXECUTION"
        and r["query_id"] not in ids
    ]
    pending.sort(
        key=lambda r: (
            ("QF", "QD").index(r["policy"]),
            r["fold"],
            GROUPS.index(r["group"]),
        )
    )
    seen = set()
    unique = []
    for r in pending:
        if r["query_id"] in seen:
            continue
        seen.add(r["query_id"])
        unique.append(
            {k: r[k] for k in ("group", "fold", "policy", "winner", "query_id")}
            | dict(kind="missing")
        )
    controls = [
        next(
            r["request"]
            for r in existing
            if r["request"]["kind"] == "control" and r["request"]["group"] == g
        )
        for g in GROUPS
    ]
    queue = controls + unique[:28]
    pilot = controls[:]
    for g in GROUPS:
        request = next((r for r in unique[:28] if r["group"] == g), None)
        if request:
            pilot.append(request)
    value = dict(
        schema="m4.ml07.query-roster.v1",
        all_winners_sealed=True,
        seal=pin(output / "sealed.json"),
        source=pin(Path(__file__)),
        reused=[pin(p) for p in sorted((PREVIOUS / "queries").glob("*.json"))],
        admitted=queue,
        pilot=pilot,
        outside_budget=unique[28:],
        missing_distinct=len(unique),
        new_call_cap=32,
        max_cpu_seconds=900,
        priority="QF,QD; fold then fixed group; no outcome selection",
    )
    return save_new(output / "query-roster.json", value)


def execute(stage, output=DEFAULT):
    verify(output)
    roster = read(output / "query-roster.json")
    for ref in roster["reused"] + [roster["seal"], roster["source"]]:
        if pin(ref["path"]) != ref:
            raise ValueError("ML07 query source/custody changed")
    if (
        stage == "remaining"
        and read(output / "pilot-result.json")["admission"] != "ADMITTED"
    ):
        raise ValueError("ML07 pilot not admitted")
    calls = roster["pilot"] if stage == "pilot" else roster["admitted"]
    started, wall = time.process_time(), time.perf_counter()
    earlier = (
        0.0 if stage == "pilot" else read(output / "pilot-result.json")["cpu_seconds"]
    )
    save_new(
        output / f"{stage}-registration.json",
        dict(
            source=pin(Path(__file__)),
            roster=pin(output / "query-roster.json"),
            stage=stage,
            max_cpu_seconds=900,
        ),
    )
    runner = OriginalQueries(output)
    try:
        for request in calls:
            dest = output / "queries" / f"{request['kind']}-{request['query_id']}.json"
            if dest.exists():
                old = read(dest)
                if (
                    old["request"] != request
                    or old["status"] != "PASS_ORIGINAL_FORWARD"
                ):
                    raise ValueError("ML07 incompatible query resume")
                continue
            guard(output)
            if earlier + time.process_time() - started >= 900:
                raise RuntimeError("ML07 financial CPU cap")
            remaining = max(1, 900 - earlier - time.process_time() + started)
            signal.signal(
                signal.SIGALRM,
                lambda *_: (_ for _ in ()).throw(
                    TimeoutError("ML07 financial wall guard")
                ),
            )
            signal.setitimer(signal.ITIMER_REAL, remaining)
            try:
                result = runner.run(request)
                save_new(dest, result)
                print(
                    dict(
                        group=request["group"],
                        fold=request["fold"],
                        kind=request["kind"],
                        seconds=round(result["wall_seconds"], 3),
                        status=result["observation"]["status"],
                    ),
                    flush=True,
                )
            except BaseException as exc:
                save_new(
                    output / f"{stage}-failure.json",
                    dict(
                        status="FAIL_RETAINED",
                        request=request,
                        type=type(exc).__name__,
                        error=str(exc),
                        cpu_seconds=time.process_time() - started,
                    ),
                )
                raise
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        runner.close()
    files = sorted((output / "queries").glob("*.json"))
    results = [read(p) for p in files]
    seconds = time.process_time() - started
    left = len(roster["admitted"]) - len(files)
    forecast = earlier + seconds + max(r["cpu_seconds"] for r in results) * left
    value = dict(
        schema="m4.ml07.query-stage.v1",
        status="PASS",
        stage=stage,
        cpu_seconds=seconds,
        wall_seconds=time.perf_counter() - wall,
        completed_calls=len(files),
        projected_cpu_seconds=forecast,
        admission="ADMITTED" if forecast <= 900 else "NOT_ADMITTED",
        control_exact=sum(r.get("known_witness_exact") is True for r in results),
        query_pins=[pin(p) for p in files],
        new_optimizer_proposals=0,
    )
    return save_new(output / f"{stage}-result.json", value)
