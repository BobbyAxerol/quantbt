"""Verify saved real selections by regenerating signals without optimization/meta."""

import json

from qms_real_review import (
    ACCOUNT, PRIVATE_ROOT, dump, endpoint_for, load_inputs,
)


def main():
    import numpy as np
    import pandas as pd
    from quantbt import QuantBTEndpoint
    from quantbt.walkforward import WalkForwardEngine

    _, alpha, frame, _ = load_inputs(PRIVATE_ROOT)
    config = endpoint_for(lambda *a: None, "off", "tpe_legacy", 128).config.walkforward_config

    def no_scoring(*args, **kwargs):
        raise AssertionError("fixed replay must not search or score candidates")

    folds = WalkForwardEngine(strategy=no_scoring, config=config, scorer=no_scoring).build_folds(frame.index)
    checks = {}
    for arm in ("off", "active_rust"):
        saved = json.loads((PRIVATE_ROOT / f"meta_{arm}_tpe_legacy.json").read_text())["samples"][0]
        signal = pd.Series(0.0, index=frame.index)
        for fold in folds:
            params = saved["params"][str(fold.fold_id)]
            generated = alpha.generate_delta_rsi_signals(frame.loc[:fold.test_index[-1]], params)
            signal.loc[fold.test_index] = generated["pos_weight"].reindex(fold.test_index).fillna(0.0)
        endpoint = QuantBTEndpoint.pct_equity(target_runtime="numba", **ACCOUNT)
        replay = endpoint.backtest(data=frame, signal=signal)
        differences = {}
        with np.load(PRIVATE_ROOT / f"meta_{arm}_tpe_legacy_0.npz") as original:
            for name in original.files:
                actual = getattr(replay, name).to_numpy(dtype=float)
                np.testing.assert_allclose(actual, original[name], rtol=1e-10, atol=1e-10)
                differences[name] = float(np.max(np.abs(actual - original[name])))
        for row in saved["records"]:
            assert row["selected_params"] == saved["params"][str(row["fold_id"])]
        checks[arm] = dict(maximum_differences=differences, regenerated_folds=len(folds),
                           params_actually_applied=True, optimization_attempts=0, meta_fit_calls=0)
    dump(PRIVATE_ROOT / "fixed_replay.json", checks)
    print(json.dumps(checks), flush=True)


if __name__ == "__main__":
    main()
