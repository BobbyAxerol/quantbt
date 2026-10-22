"""Run with -I outside checkout; prove installed helper and public account parity."""

from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import sys
import sysconfig

import numpy as np
import optuna
import pandas as pd

import quantbt
from quantbt.optimization import NormalizedSearchSpace, SamplerConfig, prepare_sampler_space

ROOT = Path(__file__).resolve().parents[1]


def main(registration):
    config = json.loads(Path(registration).read_text())
    origin = Path(quantbt.__file__).resolve().parent
    if origin != (Path(sysconfig.get_path("purelib")) / "quantbt").resolve():
        raise ValueError("consumer loaded checkout instead of installed package")
    installed = {p.relative_to(origin).as_posix(): sha256(p.read_bytes()).hexdigest()
                 for p in origin.rglob("*") if p.is_file()
                 and (p.suffix == ".py" or p.name == "py.typed")}
    if installed != config["core_inventory"]:
        raise ValueError("installed complete source inventory differs from artifact registration")
    if version("quantbt-engine") != config["core"] or version("quantbt-native") != config["native"]:
        raise ValueError("installed core/native pair differs")
    import _quantbt_native
    native = Path(_quantbt_native.__file__).resolve().parent
    binaries = [p for p in native.glob("*.so")]
    if len(binaries) != 1 or sha256(binaries[0].read_bytes()).hexdigest() != config["native_reuse"]["extension_sha256"]:
        raise ValueError("installed native bytes differ from reused artifact")
    # Only public fixture helpers come from checkout, never quantbt runtime.
    sys.path.insert(0, str(ROOT))
    from examples.wfo_sampler_space import RANGES, endpoint, market, strategy
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    plan = prepare_sampler_space(RANGES, numeric_parameters=("fast_window", "slow_window"))
    manual = {**RANGES,
              "fast_window": {"kind": "integer", "low": 4, "high": 32, "step": 4},
              "slow_window": {"kind": "integer", "low": 40, "high": 100, "step": 10}}
    if NormalizedSearchSpace(manual).identity != plan.assessment.effective_space_identity:
        raise ValueError("installed numeric declaration expanded support")
    results = []
    for ranges, sampler in [(manual, SamplerConfig(name="cmaes")), (plan.param_ranges, plan.sampler_config)]:
        bt = endpoint(strategy, config={"sampler_config": sampler}, seed=731, trials=16)
        results.append(bt.backtest(data=market(), param_ranges=ranges))
    for key in ("equity", "positions", "returns"):
        np.testing.assert_array_equal(getattr(results[0], key), getattr(results[1], key))
    a, b = [r.metadata["walk_forward"] for r in results]
    pd.testing.assert_frame_equal(a["trial_table"], b["trial_table"], check_exact=True)
    assert a["params_by_fold"] == b["params_by_fold"]
    assert "meta_selection" not in a and "meta_selection" not in b
    assert plan.optimization_config({"meta_selection": {"mode": "active"}})["meta_selection"] == {"mode": "active"}
    chosen = next(iter(a["params_by_fold"].values()))
    assert type(plan.decode(chosen)["fast_window"]) is int
    recommended = prepare_sampler_space({"x": (1, 10), "label": ["a", "b"]}, on_incompatible="recommend")
    assert recommended.sampler_config.name == "tpe_legacy"
    proof = dict(schema="qms-sampler-helper-installed-consumer-v1", status="PASS",
                 core_origin=str(origin), native_origin=str(native), modules=len(installed),
                 helper_origin=str(origin / "optimization/sampler_space.py"),
                 native_extension_sha256=config["native_reuse"]["extension_sha256"],
                 core=config["core"], native=config["native"],
                 exact_proposals_objectives_selection_account=True,
                 original_param_types=True, meta_optional=True,
                 trials=128, source_checkout_not_runtime=True,
                 fixture_sha256=sha256((ROOT / "examples/wfo_sampler_space.py").read_bytes()).hexdigest(),
                 consumer_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), publication=False)
    print(json.dumps(proof, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
