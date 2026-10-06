"""Isolated installed-package proof for the four explicit execution WFO routes."""

import importlib.metadata
import importlib.util
import json
from pathlib import Path


def prove(*, native_probe=False):
    import numpy as np
    import optuna
    import quantbt

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    root = Path(__file__).resolve().parents[1]
    origin = Path(quantbt.__file__).resolve()
    if root / "src" in origin.parents or "site-packages" not in origin.parts:
        raise AssertionError("proof requires an installed, non-editable core")
    spec = importlib.util.spec_from_file_location("synthetic_user_alpha", root / "examples/wfo_meta_execution.py")
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    routes = {}
    for route in ("intrabar", "event_driven", "order_commands", "delivery_arbitrage"):
        if native_probe:
            _, result, _ = example.execute(route, mode="active", support=1, trials=2, backend="rust")
            meta = result.metadata["walk_forward"]["meta_selection"]
            assert meta["observer_failures"] == 0 and meta["models"]
            numeric = meta["records"][-1]["numeric_backend"]
            assert numeric["selected_backend_by_block"]["gram_solve"] == "rust"
            assert numeric["selected_backend_by_block"]["rank"] == "rust" and numeric["ffi_calls"] > 0
            routes[route] = dict(explicit_rust_financial_route=True, rust_fit_rank=True,
                ffi_calls=numeric["ffi_calls"], observer_failures=0, economic_promotion=False)
            continue
        values = {mode: example.execute(route, mode=mode, support=1, trials=2)
                  for mode in ("off", "shadow", "active")}
        a, b = values["off"][1], values["shadow"][1]
        for name in ("equity", "returns", "positions", "fees", "funding", "margin"):
            np.testing.assert_array_equal(getattr(a, name), getattr(b, name))
        wa, wb = (r.metadata["walk_forward"] for r in (a, b))
        assert wa["params_by_fold"] == wb["params_by_fold"]
        assert wb["meta_selection"]["observer_failures"] == 0
        from quantbt.wfo_execution import execute_window
        endpoint, active, _ = values["active"]
        rebuilt = execute_window(endpoint.config.wfo_execution_config, example.market(route),
            active.metadata["walk_forward_result"].oos_output)
        for name in ("equity", "returns", "positions", "fees", "funding", "margin"):
            np.testing.assert_array_equal(getattr(active, name), getattr(rebuilt, name))
        routes[route] = dict(shadow_account_exact=True, active_rebuild_exact=True,
            folds=wa["n_folds"], economic_promotion=False)
    return dict(schema="qms-installed-execution-proof-v1", core_origin=str(origin),
        core=importlib.metadata.version("quantbt-engine"), native=importlib.metadata.version("quantbt-native"),
        routes=routes, publication=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-probe", action="store_true")
    print(json.dumps(prove(**vars(parser.parse_args())), sort_keys=True))
