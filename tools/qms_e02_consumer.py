"""Installed E02 admission/lifecycle proof; explicit public example, no repo imports."""

import argparse
from hashlib import sha256
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path


def consume(example):
    import numpy as np
    import optuna
    import quantbt
    import _quantbt_native as native
    from quantbt import walkforward_support_matrix
    from quantbt.optimization.meta_selection.common import MetaRecordError
    from quantbt.optimization.meta_selection.domains import DOMAIN_ABI, capability

    origin = Path(quantbt.__file__).resolve()
    assert "site-packages" in origin.parts
    assert metadata.version("quantbt-engine") == quantbt.__version__ == "1.1.2"
    assert metadata.version("quantbt-native") == native.version() == "0.4.3"
    assert "site-packages" in Path(native.__file__).resolve().parts
    spec = importlib.util.spec_from_file_location("public_e02_example", example)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _, off, _ = demo.run_demo("off", observer=False)
    _, shadow, _ = demo.run_demo("shadow", observer=True, min_origins=1, native_module=native)
    _, active, _ = demo.run_demo("active", observer=True, min_origins=1, native_module=native)
    assert off.metadata["walk_forward"]["params_by_fold"] == shadow.metadata["walk_forward"]["params_by_fold"]
    for name in ("equity", "returns", "positions", "fees", "funding", "margin"):
        np.testing.assert_array_equal(getattr(off, name), getattr(shadow, name))
    telemetry = active.metadata["walk_forward"]["meta_selection"]["domain_adapter"]
    attempts = active.metadata["walk_forward"]["meta_selection"]["observer_attempts"]
    assert attempts > 0
    assert telemetry["financial_delegate_calls"] == telemetry["original_observations"] == attempts
    assert telemetry["closed"] and telemetry["domain"] == "scalar"
    assert telemetry["market_binding"]["compatibility"]["final_account"] == "carry_position"
    assert all(telemetry[key] == 0 for key in ("financial_replays", "adapter_market_array_copies",
        "adapter_owned_market_bytes", "adapter_pyo3_calls"))
    rows = walkforward_support_matrix(False)
    assert len(rows) == 9
    assert all(row["meta_adapter_abi"] == DOMAIN_ABI for row in rows)
    rejected = []
    for route in ("portfolio", "basket", "intrabar", "order_commands", "options", "nautilus_validation"):
        try:
            capability(route, require_active=True)
        except MetaRecordError:
            rejected.append(route)
        else:
            raise AssertionError("pending domain unexpectedly activated")
    return dict(schema="qms-e02-installed-adapter-v1", core="1.1.2", native="0.4.3",
        installed_origin=str(origin), example_sha256=sha256(example.read_bytes()).hexdigest(),
        abi=DOMAIN_ABI, off_shadow_account_exact=True, observer_attempts=attempts,
        telemetry=telemetry, pending_routes_rejected=rejected, publication=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example", type=Path, required=True)
    print(json.dumps(consume(parser.parse_args().example), sort_keys=True))
