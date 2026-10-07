"""Read retained paired samples; no adaptive repeats or financial execution."""

from hashlib import sha256
import json

import numpy as np

from tools.qms_pre05_workloads import cells


def distribution(rows, quantile):
    return {
        arm: float(
            np.quantile(
                [
                    r["wall_seconds"]
                    for r in rows
                    if r["arm"] == arm and not r["warmup"]
                ],
                quantile,
            )
        )
        for arm in ("reference", "optimized")
    }


def summarize(path, cell):
    value = json.loads(path.read_text())
    assert value["cell"] == cell.identity and value["warm_repeats"] == 21
    assert len(value["rows"]) == 44
    assert all(r["semantic_sha256"] == value["semantic_sha256"] for r in value["rows"])
    assert not value["profiled"]
    assert not any(r["observer_failures"] for r in value["rows"])
    if cell.mode == "off":
        assert not any(
            r["observer_attempts"] or r["auxiliary_outer_is_evaluations"]
            for r in value["rows"]
        )
    else:
        assert all(r["observer_attempts"] > 0 and r["numeric"] for r in value["rows"])
    p50, p95 = distribution(value["rows"], 0.5), distribution(value["rows"], 0.95)
    pct50 = (p50["optimized"] / p50["reference"] - 1) * 100
    pct95 = (p95["optimized"] / p95["reference"] - 1) * 100
    warm = [r for r in value["rows"] if not r["warmup"]]
    cpu = {
        arm: float(np.median([r["cpu_seconds"] for r in warm if r["arm"] == arm]))
        for arm in ("reference", "optimized")
    }
    # Descriptive dispersion, not a resampled confidence interval or a new gate.
    mad = {}
    for arm in ("reference", "optimized"):
        times = np.array([r["wall_seconds"] for r in warm if r["arm"] == arm])
        mad[arm] = float(np.median(np.abs(times - np.median(times))) / np.median(times))
    rss = [r["after"]["rss_mib"] for r in value["rows"]]
    return dict(
        cell=cell.identity,
        group=cell.group,
        route=cell.route,
        mode=cell.mode,
        optimization=cell.optimization,
        schedule=cell.schedule,
        prepared=cell.prepared,
        conditional=cell.conditional,
        p50_ms={a: v * 1000 for a, v in p50.items()},
        p95_ms={a: v * 1000 for a, v in p95.items()},
        p50_change_pct=pct50,
        p95_change_pct=pct95,
        disabled_point_budget=("PASS" if pct50 <= 3 and pct95 <= 5 else "NOT_MET")
        if cell.mode == "off"
        else "NOT_APPLICABLE",
        median_cpu_ms={a: v * 1000 for a, v in cpu.items()},
        relative_mad=mad,
        first_cold_ms=value["rows"][0]["wall_seconds"] * 1000,
        cold_arm=value["rows"][0]["arm"],
        cold_comparison_certified=False,
        worker_peak_rss_mib=value["process_peak_rss_mib"],
        rss_first_mib=rss[0],
        rss_last_mib=rss[-1],
        rss_delta_mib=rss[-1] - rss[0],
        original_label_calls=value["rows"][-1]["observer_attempts"],
        auxiliary_outer_is_calls=value["rows"][-1]["auxiliary_outer_is_evaluations"],
        numeric=value["rows"][-1]["numeric"],
        sample_sha256=sha256(path.read_bytes()).hexdigest(),
        semantic_sha256=value["semantic_sha256"],
        exact_semantic_parity=True,
    )


def collect(lane, label):
    rows = []
    for cell in cells():
        path = lane / "samples" / (label + "-" + cell.identity + ".json")
        rows.append(summarize(path, cell))
    return dict(
        schema="pre05-public-cost-v1",
        registered_cells=len(rows),
        warm_pairs_per_cell=21,
        point_budgets=dict(p50_pct=3, p95_pct=5),
        rows=rows,
        statistical_noninferiority_certified=False,
        economic_claim=False,
        meta_off_on_are_different_logical_work=True,
    )


def main():
    from tools.qms_pre05_benchmark import write_once
    from tools.qms_pre05_workloads import ROOT

    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="matched-v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = collect(ROOT / ".maturin/qms08/pre-e06-05", args.label)
    write_once(ROOT / args.output, result)
    print(
        json.dumps(
            dict(
                cells=len(result["rows"]),
                disabled_point_pass=sum(
                    r["disabled_point_budget"] == "PASS" for r in result["rows"]
                ),
            )
        )
    )


if __name__ == "__main__":
    main()
