"""Diagnostic-only witness profile; same real alpha, no method/budget changes."""

import cProfile
import json
from pathlib import Path
import pstats
from time import perf_counter

from qms_real_review import PRIVATE_ROOT, dump, endpoint_for, load_inputs, memory


def main():
    import optuna
    import quantbt
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory

    if "site-packages" not in str(Path(quantbt.__file__).resolve()):
        raise ValueError("profile must use installed candidate")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _, alpha, frame, ranges = load_inputs(PRIVATE_ROOT)
    frame = frame.loc[:"2022-02-28 23:59:59"]

    def strategy(data, params, train_index, test_index, fold):
        history = data.loc[:test_index[-1]]
        generated = alpha.generate_delta_rsi_signals(history, dict(params))
        return generated["pos_weight"].reindex(test_index).fillna(0.0).astype(float)

    endpoint = endpoint_for(strategy, "shadow", "tpe_legacy", 32)
    context = MetaHistoryContext(
        history=MetaHistory(), corpus_id="gradient-eth-profile",
        instrument_id="ETHUSDT-linear-perpetual", timeframe="1h", run_id="qms-real-profile",
    )
    # Alpha JIT/import warmup is not included in this diagnostic span.
    alpha.generate_delta_rsi_signals(frame.iloc[:9000], {k: v[0] for k, v in ranges.items()})
    profiler = cProfile.Profile()
    started = perf_counter()
    profiler.enable()
    result = endpoint.backtest(data=frame, param_ranges=ranges, meta_history=context)
    profiler.disable()
    wall = perf_counter() - started
    profiler.dump_stats(PRIVATE_ROOT / "witness_profile.prof")
    stats = pstats.Stats(profiler)
    functions = [
        dict(file=file, line=line, function=name, primitive_calls=cc, total_calls=nc,
             exclusive_seconds=tt, inclusive_seconds=ct)
        for (file, line, name), (cc, nc, tt, ct, _) in sorted(
            stats.stats.items(), key=lambda item: -item[1][3]
        )[:100]
    ]
    wf = result.metadata["walk_forward"]
    baseline = json.loads((PRIVATE_ROOT / "sampler_off_tpe_legacy.json").read_text())["samples"][0]
    assert {str(k): v for k, v in wf["params_by_fold"].items()} == baseline["params"]
    evidence = dict(
        scope="profiled diagnostic only; not a timing median or another economic sample",
        wall_seconds=wall, memory=memory(), functions=functions,
        meta_elapsed=wf["meta_selection"]["elapsed_seconds"],
        observer_attempts=wf["meta_selection"]["observer_attempts"],
        original_native_params_preserved=True,
    )
    dump(PRIVATE_ROOT / "witness_profile.json", evidence)
    print(json.dumps({k: evidence[k] for k in (
        "scope", "wall_seconds", "meta_elapsed", "observer_attempts"
    )}), flush=True)


if __name__ == "__main__":
    main()
