"""Same-contract retained journal/reconstruction costs, not economic evidence."""

from dataclasses import replace
import json
from pathlib import Path
import statistics
import tempfile
from time import perf_counter

from quantbt.optimization.continuation import ExactStudySession
from quantbt.optimization.continuation.contract import digest
from tools.qms_c04_consumer import example_module
from tools.qms_c04_source_guard import ROOT, verify


def measure(example):
    module = example_module(example)
    cells = []
    with tempfile.TemporaryDirectory(prefix="qms-c04-cost-") as directory:
        directory = Path(directory)
        for recipe in module.RECIPES:
            for history in (32, 128):
                cfg = replace(module.configuration(recipe), budget=160)
                samples = []
                for repeat in range(4):
                    full = ExactStudySession(cfg, binding=module.BINDING)
                    start = perf_counter()
                    module.advance(full, history)
                    own_ms = (perf_counter() - start) * 1000
                    path = directory / f"{recipe}-{history}-{repeat}.json"
                    start = perf_counter()
                    sha = full.save(path)
                    save_ms = (perf_counter() - start) * 1000
                    start = perf_counter()
                    restored = ExactStudySession.load(path, config=cfg, binding=module.BINDING, expected_digest=sha)
                    restore_ms = (perf_counter() - start) * 1000
                    assert full.witness() == restored.witness()
                    module.advance(full, 8)
                    module.advance(restored, 8)
                    assert full.witness() == restored.witness()
                    if repeat:
                        samples.append(dict(owned_search_ms=own_ms, save_fsync_ms=save_ms,
                                            restore_ms=restore_ms, bytes=path.stat().st_size,
                                            continued_witness_digest=digest(full.witness()),
                                            replay_account_evaluator_calls=0))
                assert len({s["continued_witness_digest"] for s in samples}) == 1
                cells.append(dict(recipe=recipe, history_attempts=history, samples=samples,
                                  median={key: statistics.median(s[key] for s in samples)
                                          for key in ("owned_search_ms", "save_fsync_ms", "restore_ms", "bytes")}))
    return dict(schema="qms-c04-continuation-cost-v1", source_guard=verify(), cells=cells,
                seed=731, threads=1, warmups=1, retained=3, full_budget=160,
                fixture="toy-2D-median-pruner-constraints-v1", future_checks=8,
                timing_scope="owned sampler plus journal; no financial evaluator",
                rss_gate="NOT_MEASURED_NOT_CLAIMED", economic_claim=False,
                endpoint_wfo_speedup_claim=False, publication=False)


if __name__ == "__main__":
    import argparse
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("cost evidence path exists; preserve historical samples")
    result = measure(ROOT / "examples/optimization_exact_continuation.py")
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"cells": len(result["cells"]), "parity": True, "publication": False}))
