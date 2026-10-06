"""Installed bounded package cells, using only sanitized example strategies."""

import argparse
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys
import types


def consume(example):
    import numpy as np
    import optuna
    import quantbt
    import _quantbt_native as native

    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert metadata.version("quantbt-engine") == quantbt.__version__ == "1.1.2"
    assert metadata.version("quantbt-native") == native.version() == "0.4.3"
    # Load sanitized fixtures only; never put the repository source on sys.path.
    namespace = types.ModuleType("examples")
    namespace.__path__ = [str(example.resolve().parent)]
    sys.modules["examples"] = namespace
    spec = importlib.util.spec_from_file_location("examples.wfo_meta_package", example)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rows = []
    for kind in ("basket", "basis", "stat_pair"):
        results = {mode: demo.execute(mode, kind=kind, support=1, policy="require",
            native_module=native)[1] for mode in ("off", "shadow", "active")}
        off, shadow, active = (results[m] for m in ("off", "shadow", "active"))
        assert off.metadata["walk_forward"]["params_by_fold"] == shadow.metadata["walk_forward"]["params_by_fold"]
        for key in ("equity", "returns", "positions", "fees", "funding", "margin", "diagnostics"):
            np.testing.assert_array_equal(getattr(off, key), getattr(shadow, key))
        side = active.metadata["walk_forward"]["meta_selection"]
        assert side["observer_attempts"] > 0 and side["observer_failures"] == 0
        adapter = side["domain_adapter"]
        assert adapter["metric_authority"] == "original_package_account_full_report"
        assert adapter["financial_replays"] == 0 and adapter["empirical_promotion"] is False
        rows.append(dict(kind=kind, off_shadow_account_exact=True, original_witness=True,
                         observer_attempts=side["observer_attempts"]))
    return dict(schema="qms-e05-installed-package-v1", core="1.1.2", native="0.4.3",
        origin=str(Path(quantbt.__file__).resolve()), cells=rows,
        synthetic_demo=True, empirical_promotion=False, publication=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    print(json.dumps(consume(parser.parse_args().example), sort_keys=True))
