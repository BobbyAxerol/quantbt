"""Installed original shared-account proof; no repository quantbt imports."""

import argparse
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path


def _installed_pair(quantbt, native, *, core_version=None, native_version=None):
    from quantbt.core.generated_product_contracts import (
        NATIVE_EVENT_CORE_PACKAGE_VERSION, NATIVE_EVENT_NATIVE_PACKAGE_VERSION,
    )

    if (core_version is None) != (native_version is None):
        raise ValueError("both expected core/native versions are required together")
    if core_version is None:
        core_version, native_version = NATIVE_EVENT_CORE_PACKAGE_VERSION, NATIVE_EVENT_NATIVE_PACKAGE_VERSION
    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert metadata.version("quantbt-engine") == quantbt.__version__ == core_version
    assert metadata.version("quantbt-native") == native.version() == native_version
    return quantbt.__version__, native.version()


def consume(example, *, core_version=None, native_version=None):
    import numpy as np
    import optuna
    import quantbt
    import _quantbt_native as native

    core_version, native_version = _installed_pair(quantbt, native,
        core_version=core_version, native_version=native_version)
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
    return dict(schema="qms-e04-installed-portfolio-v1", core=core_version, native=native_version,
        origin=str(Path(quantbt.__file__).resolve()), cells=rows,
        synthetic_demo=True, publication=False, empirical_promotion=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    parser.add_argument("--core-version")
    parser.add_argument("--native-version")
    args = parser.parse_args()
    print(json.dumps(consume(args.example, core_version=args.core_version,
        native_version=args.native_version), sort_keys=True))
