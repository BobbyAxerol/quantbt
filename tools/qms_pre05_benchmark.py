"""Source-bound before/after public workloads; no release or economic claims."""

import argparse
import cProfile
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import pstats
import subprocess
import sys
from time import perf_counter, process_time

import optuna

from tools.qms_pre05_workloads import (
    ROOT,
    ENTRY,
    cells,
    execute,
    prepare,
    semantic,
    export_history,
    metadata,
)
from tools.qms_pre05_profile import PublicCostProfile
from tools.qms_pre05_reference import baseline_blocks


def write_once(path, value):
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        f.write(encoded)


def register(lane):
    fs = os.statvfs(ROOT)
    if fs.f_bavail * fs.f_frsize < 6 * 1024**3:
        raise ValueError("insufficient registered scratch/safety budget")
    names = subprocess.check_output(
        ["git", "ls-files", "--", "src", "rust"], cwd=ROOT, text=True
    ).splitlines()
    manifest = dict(
        schema="pre05-cost-registration-v1",
        entry=ENTRY,
        cells=[dict(id=c.identity, **asdict(c)) for c in cells()],
        warm_repeats=21,
        cold_repeats=1,
        numeric_threads=1,
        disabled_budget=dict(p50_pct=3, p95_pct=5, owner_approved=True),
        profile_separate_from_uninstrumented_timing=True,
        economic_claim=False,
        peak_incremental_budget_bytes=1024**3,
        safety_bytes=5 * 1024**3,
        available_bytes=fs.f_bavail * fs.f_frsize,
        free_inodes=fs.f_favail,
        source_sha256={n: sha256((ROOT / n).read_bytes()).hexdigest() for n in names},
    )
    write_once(lane / "registration.json", manifest)
    return dict(cells=len(cells()), available_bytes=manifest["available_bytes"])


def profile(cell, lane, label, *, warm=False, reference=False):
    with baseline_blocks(optimized=not reference):
        return _profile(cell, lane, label, warm=warm)


def _profile(cell, lane, label, *, warm=False):
    if warm:
        execute(prepare(cell, lane), cell)
    bt, data, ctx, ranges = prepare(cell, lane)
    prof = cProfile.Profile()
    path = lane / "profiles" / (label + "-" + cell.identity)
    if path.with_suffix(".json").exists():
        raise ValueError("profile already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    t, cpu = perf_counter(), process_time()
    with PublicCostProfile() as stages:
        prof.enable()
        result = execute((bt, data, ctx, ranges), cell)
        prof.disable()
    wall = perf_counter() - t
    prof.dump_stats(str(path.with_suffix(".pstats")))
    key, work = semantic(result, cell, ctx)
    stats = pstats.Stats(prof)
    hot = sorted(stats.stats.items(), key=lambda p: p[1][3], reverse=True)[:60]
    value = dict(
        cell=asdict(cell),
        instrumented_wall_seconds=wall,
        cpu_seconds=process_time() - cpu,
        components=stages.report(wall),
        semantic_sha256=key,
        work=work,
        model_shapes=[
            dict(
                N=m.diagnostics["rows"],
                d=m.diagnostics["dimension"],
                origins=m.origin_count,
                P=len(r["proposal"].predictions),
            )
            for m, r in zip(
                metadata(result, cell)
                .get("meta_selection", {})
                .get("models", {})
                .values(),
                metadata(result, cell).get("meta_selection", {}).get("records", ()),
                strict=True,
            )
        ],
        hot=[
            dict(
                file=k[0],
                line=k[1],
                function=k[2],
                primitive=v[0],
                calls=v[1],
                own_seconds=v[2],
                cumulative_seconds=v[3],
            )
            for k, v in hot
        ],
    )
    write_once(path.with_suffix(".json"), value)
    return {
        k: value[k]
        for k in ("cell", "instrumented_wall_seconds", "semantic_sha256", "components")
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=("register", "history", "history-all", "profile", "sample", "matrix"),
    )
    p.add_argument("--lane", type=Path, default=ROOT / ".maturin/qms08/pre-e06-05")
    p.add_argument("--cell", type=int, default=8)
    p.add_argument("--group", choices=("domain", "nested"), default="domain")
    p.add_argument("--route", default="pct_equity")
    p.add_argument("--label", default="before")
    p.add_argument("--warm", action="store_true")
    p.add_argument("--reference", action="store_true")
    args = p.parse_args()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    lane = args.lane.resolve()
    if args.lane.is_symlink() or not lane.is_relative_to(ROOT / ".maturin/qms08"):
        raise ValueError("unreviewed cost lane")
    if args.action == "register":
        value = register(lane)
    elif args.action == "history":
        value = export_history(lane, group=args.group, route=args.route)
    elif args.action == "history-all":
        from tests.meta_selection import (
            pre_e06_02_support as ordinary,
            pre_e06_03_support as nested,
        )

        value = []
        for group, routes in (("domain", ordinary.ROUTES), ("nested", nested.ROUTES)):
            for route in routes:
                if (lane / "history" / (group + "-" + route + ".json")).exists():
                    continue
                row = export_history(lane, group=group, route=route)
                value.append(row)
                print(json.dumps(row, sort_keys=True), flush=True)
    elif args.action == "sample":
        from tools.qms_pre05_sampling import sample

        value = sample(cells()[args.cell], lane, args.label)
    elif args.action == "matrix":
        values = []
        for i, cell in enumerate(cells()):
            if (
                lane / "samples" / (args.label + "-" + cell.identity + ".json")
            ).exists():
                continue
            command = [
                sys.executable,
                "-m",
                "tools.qms_pre05_benchmark",
                "sample",
                "--cell",
                str(i),
                "--lane",
                str(lane),
                "--label",
                args.label,
            ]
            completed = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True
            )
            log = lane / "logs" / (args.label + "-" + cell.identity + ".log")
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("x") as f:
                f.write(completed.stdout + completed.stderr)
            if completed.returncode:
                raise RuntimeError("matched worker failed: " + str(log))
            row = json.loads(completed.stdout.splitlines()[-1])
            values.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
        write_once(lane / (args.label + "-matrix.json"), values)
        value = dict(completed=len(values))
    else:
        value = profile(
            cells()[args.cell],
            lane,
            args.label,
            warm=args.warm,
            reference=args.reference,
        )
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
