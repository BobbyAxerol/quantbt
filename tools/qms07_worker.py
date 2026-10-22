"""Fresh-process worker; import the chosen entry/current source before QuantBT."""

import argparse
from contextlib import nullcontext
import cProfile
from hashlib import sha256
import json
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time


def memory():
    values = {}
    for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
        if line.startswith(("Rss:", "Pss:")):
            key, value, _ = line.split()
            values[key.rstrip(":").lower() + "_mib"] = int(value) / 1024
    values["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("disabled", "meta", "prepared"), required=True
    )
    parser.add_argument("--extension", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--aggregate", type=int, default=1)
    args = parser.parse_args()
    sys.path[:0] = [str(args.source_tree / "src"), str(args.source_tree)]
    imported = perf_counter()
    import numpy as np
    import optuna
    from dataclasses import replace
    from quantbt import QuantBTEndpoint
    from quantbt.optimization.meta_selection.common import wire
    from examples.wfo_meta_selection import PARAM_RANGES, make_endpoint, market
    from tools.qms06_prepared import execute, isolated_financial_candidate

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    module = None
    if args.extension:
        from tools.build_qms04_candidate import load_candidate

        module = load_candidate(args.extension, candidate=args.version)
    import_seconds = perf_counter() - imported

    def run():
        if args.mode != "disabled":
            return execute(
                "rust" if args.mode == "prepared" else "numba",
                "require" if args.mode == "prepared" else "off",
                module if args.mode == "prepared" else None,
            )
        endpoint = make_endpoint("off", observer=False)
        wf = replace(endpoint.config.walkforward_config, meta_selection=None)
        endpoint = QuantBTEndpoint(replace(endpoint.config, walkforward_config=wf))
        result = endpoint.backtest(data=market(), param_ranges=PARAM_RANGES)
        assert "meta_selection" not in result.metadata["walk_forward"]
        return result, {"observer_attempts": 0, "models": 0, "elapsed_seconds": {}}

    with isolated_financial_candidate(module) if module else nullcontext():
        cold = perf_counter()
        run()
        cold_run_seconds = perf_counter() - cold
        before_memory = memory()
        profiler = cProfile.Profile()
        stage_profile = None
        if args.profile:
            # This helper stays current-source; all instrumented owners come from
            # the selected entry/current tree imported above.
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "qms07_profile", Path(__file__).with_name("qms07_profile.py")
            )
            helper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(helper)
            stage_profile = helper.StageProfile()
            profiler.enable()
        wall, cpu = perf_counter(), process_time()
        aggregate_samples = []
        with stage_profile if stage_profile else nullcontext():
            for _ in range(args.aggregate):
                started = perf_counter()
                result, evidence = run()
                aggregate_samples.append(perf_counter() - started)
        wall, cpu = perf_counter() - wall, process_time() - cpu
        if args.profile:
            profiler.disable()
        after_memory = memory()
    wf = result.metadata["walk_forward"]
    history_membership = []
    for view in wf.get("meta_selection", {}).get("snapshots", ()):
        history_membership.append(
            {
                "as_of": view.information_as_of,
                "corpora": view.authorized_corpora,
                "cohorts": view.outcome_origins,
                "exposures": view.research_exposures,
                "origins": [
                    {
                        "task_id": revision.task.task_id,
                        "panel": revision.panel.members,
                        "rows": [
                            (
                                row.candidate_evaluation_id,
                                row.anchor_evaluation_id,
                                row.raw_is,
                                row.raw_forward,
                                row.anchor_is,
                                row.anchor_forward,
                                row.y,
                                row.q,
                                row.origin_weight,
                            )
                            for row in revision.training_rows
                        ],
                    }
                    for revision in view.revisions
                ],
            }
        )
    profile = []
    if args.profile:
        import pstats

        stats = pstats.Stats(profiler)
        profile = [
            {
                "file": file,
                "function": name,
                "calls": nc,
                "self_seconds": tt,
                "inclusive_seconds": ct,
            }
            for (file, _, name), (_, nc, tt, ct, _) in sorted(
                stats.stats.items(), key=lambda item: -item[1][3]
            )[:70]
        ]
    plateau = []
    if args.memory:
        import gc
        from quantbt.optimization.meta_selection.numerics import NumericRuntime

        runtime = NumericRuntime(native_policy="require", native_module=module)
        rng = np.random.default_rng(731)
        v, y, w = (
            rng.normal(size=(4096, 24)),
            rng.normal(size=4096),
            np.ones(4096) / 4096,
        )
        current, delta = rng.normal(size=(600, 24)), rng.normal(size=600)
        for i in range(20):
            _, _, beta = runtime.fit(v, y, w, 10, cache_identity="fixed-snapshot-basis")
            runtime.rank(current, beta, delta, cache_identity="fixed-model-pool")
            gc.collect()
            plateau.append(
                {
                    "iteration": i,
                    **memory(),
                    "retained_cache_bytes": runtime.work_cache.retained_bytes,
                }
            )
    arrays = {}
    for name in ("positions", "equity", "returns"):
        value = np.ascontiguousarray(getattr(result, name).to_numpy(), dtype=np.float64)
        arrays[name] = sha256(value.tobytes()).hexdigest()
    trace = {
        "trials": wf["trial_table"].to_json(orient="split", date_format="iso"),
        "candidates": wf["candidate_table"].to_json(orient="split", date_format="iso"),
        "params": {str(k): v for k, v in wf["params_by_fold"].items()},
    }
    print(
        json.dumps(
            wire(
                {
                    "source": str(args.source_tree),
                    "mode": args.mode,
                    "wall_seconds": wall / args.aggregate,
                    "cpu_seconds": cpu / args.aggregate,
                    "aggregate_wall_seconds": wall,
                    "aggregate_samples": aggregate_samples,
                    "logical_runs": args.aggregate,
                    "per_run_wall_seconds": wall / args.aggregate,
                    "profiled": args.profile,
                    "import_seconds": import_seconds,
                    "cold_run_seconds": cold_run_seconds,
                    "before_memory": before_memory,
                    "after_memory": after_memory,
                    "arrays_sha256": arrays,
                    "trace": trace,
                    "sampler": wf.get("sampler_studies", ()),
                    "history_membership": history_membership,
                    "trial_rows": len(wf["trial_table"]),
                    "candidate_rows": len(wf["candidate_table"]),
                    "evidence": evidence,
                    "profile": profile,
                    "plateau": plateau,
                    "components": stage_profile.report(wall) if stage_profile else None,
                }
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
