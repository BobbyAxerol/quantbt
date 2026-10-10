"""Run an already reviewed calibration; never manufacture approval or advice."""
import argparse
import importlib.util
import json
from pathlib import Path

from quantbt import QuantBTEndpoint
from quantbt.mode5 import Mode5Calibration
from quantbt.optimization import SamplerConfig


def calibrate(*, data, strategy, param_ranges, calibration, target_mode="pct_equity",
              account_kwargs=None, execution_endpoint=None, prepared=True):
    if not isinstance(calibration, Mode5Calibration):
        raise TypeError("sealed Mode5Calibration required")
    recipe = calibration.plan.record.data["recipe"]
    binding = calibration.binding.data
    options = dict(scoring_backend="endpoint", is_subperiods=1,
        native_prepared_wfo="off", use_prepared_scoring_cache=prepared,
        sampler_config=SamplerConfig(**binding["sampler"]),
        sampler_warm_start=binding["warm_start"], mode5_calibration=calibration)
    account = dict(account_kwargs or {})
    if execution_endpoint is not None:
        if account:
            raise ValueError("use the original execution endpoint or account kwargs, not both")
        account["execution_endpoint"] = execution_endpoint
    endpoint = QuantBTEndpoint.walk_forward(strategy_class=strategy,
        optimization_mode="mode_5_full_robust", optimization_schedule="global",
        target_mode=target_mode, split_frequency="single",
        optuna_trials=calibration.plan.record.data["search_budget"],
        random_seed=recipe["sampler"]["seeds"][0],
        optimization_config=options, **account)
    result = endpoint.backtest(data=data, param_ranges=param_ranges)
    return endpoint, result, result.metadata["walk_forward"]["mode5_diagnostics_first"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, required=True,
        help="external Python file exporting build_calibration_inputs()")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("external_mode5_inputs", args.adapter)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, _, audit = calibrate(**module.build_calibration_inputs())
    print(json.dumps({key: audit[key] for key in
        ("status", "validation_claim", "deployment_authorized", "compute_bill")}, indent=2))


if __name__ == "__main__":
    main()
