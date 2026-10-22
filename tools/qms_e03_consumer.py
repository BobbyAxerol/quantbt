"""Installed scalar original-account proof, no repository package imports."""

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
    import optuna
    import numpy as np
    import quantbt
    import _quantbt_native as native

    core_version, native_version = _installed_pair(quantbt, native,
        core_version=core_version, native_version=native_version)
    spec = importlib.util.spec_from_file_location("scalar_example", example)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    cells = [(r, b) for b in ("native_vectorized", "native_event")
             for r in ("signal_notional", "notional", "unit")]
    cells += [("pct_equity", "legacy"), ("dca_ladder", "legacy")]
    rows = []
    for target, backend in cells:
        _, off, _ = demo.execute_scalar(target, backend, "off", data=demo.market(730))
        _, shadow, _ = demo.execute_scalar(target, backend, "shadow", data=demo.market(730),
            support=1, policy="require", native_module=native)
        _, active, _ = demo.execute_scalar(target, backend, "active", data=demo.market(730),
            support=1, policy="require", native_module=native)
        assert off.metadata["walk_forward"]["params_by_fold"] == shadow.metadata["walk_forward"]["params_by_fold"]
        for key in ("equity", "returns", "positions"):
            np.testing.assert_array_equal(getattr(off, key), getattr(shadow, key))
        meta = active.metadata["walk_forward"]["meta_selection"]
        assert meta["observer_failures"] == 0
        assert meta["domain_adapter"]["financial_replays"] == 0
        assert meta["domain_adapter"]["empirical_promotion"] is False
        assert meta["domain_adapter"]["scalar_execution"]["backend"] == backend
        rows.append(dict(target=target, backend=backend, off_shadow_account_exact=True,
                         observer_attempts=meta["observer_attempts"], active_original_witness=True))
    return dict(schema="qms-e03-installed-scalar-v1", core=core_version, native=native_version,
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
