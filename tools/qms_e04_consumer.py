"""Installed original shared-account proof; no repository quantbt imports."""

import argparse
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path


def consume(example):
    import numpy as np
    import optuna
    import quantbt
    import _quantbt_native as native

    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert metadata.version("quantbt-engine") == quantbt.__version__ == "1.1.2"
    assert metadata.version("quantbt-native") == native.version() == "0.4.3"
    spec = importlib.util.spec_from_file_location("portfolio_example", example)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rows = []
    for sizing in ("target_units", "%_equity"):
        results = {mode: demo.execute(mode, sizing=sizing, support=1, policy="require",
                   native_module=native)[1] for mode in ("off", "shadow", "active")}
        off, shadow, active = (results[m] for m in ("off", "shadow", "active"))
        assert off.metadata["walk_forward"]["params_by_fold"] == shadow.metadata["walk_forward"]["params_by_fold"]
        for key in ("equity", "returns", "positions", "fees", "funding", "margin", "diagnostics"):
            np.testing.assert_array_equal(getattr(off, key), getattr(shadow, key))
        side = active.metadata["walk_forward"]["meta_selection"]
        adapter = side["domain_adapter"]
        assert side["observer_failures"] == 0
        assert adapter["metric_authority"] == "original_aggregate_shared_account_full_report"
        assert adapter["financial_replays"] == 0 and not adapter["symbol_average_metrics"]
        assert not adapter["empirical_promotion"]
        assert all(c.observation.verification == "original_result" for t in side["tasks"] for c in t.candidates)
        rows.append(dict(sizing=sizing, off_shadow_account_exact=True,
                         active_original_witness=True, observer_attempts=side["observer_attempts"]))
    return dict(schema="qms-e04-installed-portfolio-v1", core="1.1.2", native="0.4.3",
        origin=str(Path(quantbt.__file__).resolve()), cells=rows,
        synthetic_demo=True, publication=False, empirical_promotion=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    print(json.dumps(consume(parser.parse_args().example), sort_keys=True))
