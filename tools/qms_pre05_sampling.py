"""Uninstrumented paired public timing, with full semantic proof retained."""

import gc
from hashlib import sha256
import resource
from time import perf_counter, process_time

import numpy as np

from tools.qms_pre05_reference import baseline_blocks
from tools.qms_pre05_workloads import (
    execute,
    metadata,
    prepare,
    semantic,
    load_history,
    history_path,
)
from tools.qms01_baseline import resource_snapshot
from quantbt.optimization.meta_selection.common import wire


def sample(cell, lane, label):
    from tools.qms_pre05_benchmark import write_once

    path = lane / "samples" / (label + "-" + cell.identity + ".json")
    if path.exists():
        raise ValueError("refuse to overwrite cost evidence")
    rows = []
    canonical = None
    canonical_work = None
    history_t = perf_counter()
    frozen = None if cell.mode == "off" else load_history(history_path(lane, cell))
    history_load_seconds = perf_counter() - history_t
    for repeat in range(-1, 21):
        order = (
            ("reference", "optimized")
            if repeat % 2 == 0
            else ("optimized", "reference")
        )
        for arm in order:
            with baseline_blocks(optimized=arm == "optimized"):
                fixture_t = perf_counter()
                prepared = prepare(cell, lane, frozen_history=frozen)
                fixture_seconds = perf_counter() - fixture_t
                gc.collect()
                before = resource_snapshot()
                wall, cpu = perf_counter(), process_time()
                result = execute(prepared, cell)
                elapsed, used_cpu = perf_counter() - wall, process_time() - cpu
                after = resource_snapshot()
                key, work = semantic(result, cell, prepared[2])
                if canonical is None:
                    canonical = key
                    canonical_work = work
                if key != canonical:
                    write_once(
                        path.with_suffix(".failure.json"),
                        dict(
                            cell=cell.identity,
                            repeat=repeat,
                            arm=arm,
                            expected_sha256=canonical,
                            actual_sha256=key,
                            expected_work=canonical_work,
                            work=work,
                        ),
                    )
                    raise AssertionError("full work/decision/account mismatch")
                wf = metadata(result, cell)
                meta = wf.get("meta_selection", {})
                r = meta.get("records", [{}])[0]
                row = dict(
                    repeat=repeat,
                    arm=arm,
                    cold=repeat == -1 and arm == order[0],
                    warmup=repeat == -1,
                    wall_seconds=elapsed,
                    cpu_seconds=used_cpu,
                    fixture_prepare_seconds=fixture_seconds,
                    before=before,
                    after=after,
                    semantic_sha256=key,
                    observer_attempts=meta.get("observer_attempts", 0),
                    observer_failures=meta.get("observer_failures", 0),
                    auxiliary_outer_is_evaluations=r.get(
                        "auxiliary_outer_is_evaluations", 0
                    ),
                    auxiliary_outer_is_seconds=r.get("auxiliary_outer_is_seconds", 0.0),
                    numeric=wire(r.get("numeric_backend", {})),
                    meta_seconds=wire(meta.get("elapsed_seconds", {})),
                    observer_label_available_at=r.get("observer_label_available_at"),
                    prepared_cache=wire(wf.get("prepared_scoring_cache", {})),
                    sampler_wall_seconds=[
                        s["sampler_wall_seconds"]
                        for s in wf.get("sampler_studies", ())
                        if "sampler_wall_seconds" in s
                    ],
                )
                rows.append(row)
                del result, prepared
            gc.collect()
    payload = dict(
        schema="pre05-paired-cell-v1",
        cell=cell.identity,
        warm_repeats=21,
        cold_pair_shared_worker_order=rows[0]["arm"],
        rows=rows,
        work=work,
        semantic_sha256=canonical,
        numeric_threads=1,
        profiled=False,
        economic_claim=False,
        history_load_seconds=history_load_seconds,
        process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / 1024.0,
    )
    write_once(path, payload)
    warm = {
        a: np.array(
            [r["wall_seconds"] for r in rows if r["arm"] == a and not r["warmup"]]
        )
        for a in ("reference", "optimized")
    }
    ratio = np.array([warm["optimized"][i] / warm["reference"][i] for i in range(21)])
    return dict(
        cell=cell.identity,
        p50_ms={a: float(np.median(v) * 1000) for a, v in warm.items()},
        p95_ms={a: float(np.quantile(v, 0.95) * 1000) for a, v in warm.items()},
        median_paired_ratio=float(np.median(ratio)),
        max_rss_mib=payload["process_peak_rss_mib"],
        sample_sha256=sha256(path.read_bytes()).hexdigest(),
        semantic_sha256=canonical,
    )
