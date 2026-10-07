"""Registered actual-history portable block cost; not a full-WFO benchmark."""

from hashlib import sha256
import json
import argparse
from statistics import median
from time import perf_counter

from quantbt.optimization.meta_selection import common
from tools.qms_pre05_reference import BLOCKS, entry_module
from tools.qms_pre05_workloads import ROOT, load_history
from tools.qms_pre05_benchmark import write_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=("original", "isolated"), default="original")
    label = parser.parse_args().label
    lane = ROOT / ".maturin/qms08/pre-e06-05"
    history_path = lane / "history/domain-pct_equity.json"
    payload = tuple(load_history(history_path)._revisions.values())
    arms = {
        arm: entry_module(common, BLOCKS[0], optimized=arm == "optimized")[0]["wire"]
        for arm in ("reference", "optimized")
    }
    expected = arms["reference"](payload)
    assert arms["optimized"](payload) == expected
    rows = []
    for repeat in range(-1, 21):
        order = (
            ("reference", "optimized")
            if repeat % 2 == 0
            else ("optimized", "reference")
        )
        for arm in order:
            start = perf_counter()
            for _ in range(50):
                out = arms[arm](payload)
            elapsed = perf_counter() - start
            assert out == expected
            rows.append(
                dict(repeat=repeat, arm=arm, seconds=elapsed, warmup=repeat == -1)
            )
    seconds = {
        a: median(r["seconds"] for r in rows if r["arm"] == a and not r["warmup"])
        for a in arms
    }
    result = dict(
        schema="pre05-portable-block-cost-v1",
        history_sha256=sha256(history_path.read_bytes()).hexdigest(),
        revisions=len(payload),
        warm_pairs=21,
        calls_per_arm_sample=50,
        financial_calls=0,
        rows=rows,
        median_ms={a: v * 1000 for a, v in seconds.items()},
        median_change_pct=(seconds["optimized"] / seconds["reference"] - 1) * 100,
        exact_portable_parity=True,
        full_wfo_speed_claim=False,
        run_context=label,
    )
    suffix = "-isolated" if label == "isolated" else ""
    write_once(lane / ("portable-block-cost" + suffix + ".json"), result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, sort_keys=True))


if __name__ == "__main__":
    main()
