"""Registered sampler-helper diagnostics, private alpha inputs never enter Git.

Register before runs. Meta remains off; no publication or sampler reselection.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import resource
import subprocess
from time import perf_counter, process_time

import numpy as np
import optuna
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.optimization import NormalizedSearchSpace, SamplerConfig, prepare_sampler_space
from quantbt.optimization.space import stable_params_key
from examples.wfo_sampler_space import (ACCOUNT as PUBLIC_ACCOUNT, RANGES as PUBLIC_RANGES,
                                       endpoint, market, strategy as public_strategy)
from tools.qms_real_review import ACCOUNT as PRIVATE_ACCOUNT, PRIVATE_ROOT, clean, load_inputs


ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / ".maturin/qms08/sampler-helper-v1"
PRIVATE = PRIVATE_ROOT / "sampler-helper-v1"
SEEDS = (731, 732, 733)
TRIALS = 128
SOURCE_FILES = (
    "src/quantbt/optimization/sampler_space.py", "src/quantbt/optimization/samplers.py",
    "src/quantbt/optimization/__init__.py", "src/quantbt/optimization/parameter_space.py",
    "src/quantbt/optimization/space.py", "src/quantbt/optimization/wfo_study.py",
    "src/quantbt/endpoint.py", "src/quantbt/walkforward.py",
    "examples/wfo_sampler_space.py", "tools/qms_sampler_helper_diagnostic.py",
    "upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md",
)


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def source():
    return {name: file_hash(ROOT / name) for name in SOURCE_FILES}


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(json.dumps(clean(value), indent=2, allow_nan=False) + "\n")


def identity(value):
    return sha256(stable_params_key(clean(value)).encode()).hexdigest()


def load_case(case):
    if case == "public_ma":
        frame = market()
        ranges = dict(PUBLIC_RANGES)
        plan = prepare_sampler_space(ranges, numeric_parameters=("fast_window", "slow_window"))
        manual = {
            **ranges,
            "fast_window": {"kind": "integer", "low": 4, "high": 32, "step": 4},
            "slow_window": {"kind": "integer", "low": 40, "high": 100, "step": 10},
        }
        return frame, public_strategy, ranges, manual, plan, PUBLIC_ACCOUNT, 10
    registration, alpha, frame, ranges = load_inputs(PRIVATE_ROOT)
    frame = frame.loc[:"2022-12-31 23:59:59"]
    if len(ranges) != 8 or any(s.kind not in {"integer", "float"} for s in NormalizedSearchSpace(ranges).specs):
        raise ValueError("registered private numeric alpha schema changed")
    def strategy(data, params, train_index, test_index, fold):
        generated = alpha.generate_delta_rsi_signals(data.loc[:test_index[-1]], dict(params))
        return generated["pos_weight"].reindex(test_index).fillna(0.0).astype(float)
    plan = prepare_sampler_space(ranges)
    return frame, strategy, ranges, ranges, plan, {**PRIVATE_ACCOUNT, "target_runtime": "numba"}, 100


def register():
    registration, _alpha, _frame, ranges = load_inputs(PRIVATE_ROOT)
    plans = {}
    for case in ("delta_rsi", "public_ma"):
        data, _strategy, _old, manual, plan, _account, _trades = load_case(case)
        assert NormalizedSearchSpace(manual).identity == plan.assessment.effective_space_identity
        plans[case] = dict(bars=len(data), start=data.index[0].isoformat(), end=data.index[-1].isoformat(),
                           data_hash=sha256(pd.util.hash_pandas_object(data, index=True).to_numpy().tobytes()).hexdigest(),
                           numeric_dimensions=len(plan.assessment.static_numeric),
                           normalized_space_identity=plan.assessment.effective_space_identity)
    # A separate declared enumeration check preserves each original integer
    # support; it is not another tuned strategy or a new performance arm.
    integers = [s for s in NormalizedSearchSpace(ranges).specs if s.kind == "integer"]
    enumerated = {**ranges, **{s.name: list(range(s.low, s.high + 1, s.step or 1)) for s in integers}}
    converted = prepare_sampler_space(enumerated, numeric_parameters=[s.name for s in integers])
    assert converted.assessment.effective_space_identity == NormalizedSearchSpace(ranges).identity
    payload = dict(schema="qms-sampler-helper-diagnostic-v1", source=source(),
                   baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                   seeds=SEEDS, trials_per_fold=TRIALS, forward_folds=4,
                   split="quarterly 2022; rolling 365D IS", meta="off",
                   arms={"delta_rsi": ["manual_cma", "helper_cma", "numeric_tpe"],
                         "public_ma": ["manual_cma", "helper_cma", "numeric_tpe", "mixed_cma"]},
                   original_private_registration_hash=file_hash(PRIVATE_ROOT / "registration.json"),
                   alpha_hash=registration["alpha_sha256"], cases=plans,
                   private_integer_support_conversion="EXACT_NORMALIZED_IDENTITY",
                   versions={p: importlib.metadata.version(p) for p in ("optuna", "cmaes", "numpy", "numba", "pandas")},
                   protocol="bounded diagnostic, not twelve-fold promotion; retain all outcomes; no retune",
                   resource_budget=dict(incremental_gib=1, safety_headroom_gib=5,
                                        scratch=[], retained=[str(LANE.relative_to(ROOT)), str(PRIVATE.relative_to(ROOT))]))
    write_once(LANE / "registration.json", payload)
    print("registration sealed before study outcomes", flush=True)


def registration():
    value = json.loads((LANE / "registration.json").read_text())
    if value["source"] != source():
        raise ValueError("registered source changed; do not reuse or overwrite diagnostic outcomes")
    if value["original_private_registration_hash"] != file_hash(PRIVATE_ROOT / "registration.json"):
        raise ValueError("private inputs changed")
    return value


def capture(case, arm, seed):
    recorded = registration()
    frame, strategy, original, manual, plan, account, min_trades = load_case(case)
    actual_hash = sha256(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()).hexdigest()
    if actual_hash != recorded["cases"][case]["data_hash"]:
        raise ValueError("registered market changed")
    helper_started = perf_counter()
    if arm == "helper_cma":
        plan = prepare_sampler_space(original, numeric_parameters=("fast_window", "slow_window") if case == "public_ma" else ())
        ranges, config = plan.param_ranges, plan.optimization_config()
    else:
        ranges = original if arm == "mixed_cma" else manual
        config = dict(sampler_config=SamplerConfig(
            name="tpe_legacy" if arm == "numeric_tpe" else "cmaes",
            mixed_space_policy="explicit_independent" if arm == "mixed_cma" else "reject"))
    config_seconds = perf_counter() - helper_started
    config["min_trades_per_year"] = min_trades
    bt = endpoint(strategy, config=config, seed=seed, trials=TRIALS, account=account)
    started, cpu = perf_counter(), process_time()
    result = bt.backtest(data=frame, param_ranges=ranges)
    wall, cpu = perf_counter() - started, process_time() - cpu
    wf = result.metadata["walk_forward"]
    assert "meta_selection" not in wf and wf["n_folds"] == 4
    replay_started = perf_counter()
    stitched = result.metadata["walk_forward_result"].oos_output
    check = QuantBTEndpoint.pct_equity(**account).backtest(data=frame, signal=stitched)
    arrays = {name: getattr(result, name).to_numpy(dtype=float) for name in ("equity", "positions", "returns")}
    for name, a in arrays.items():
        np.testing.assert_array_equal(a, getattr(check, name).to_numpy(dtype=float))
    actual_folds = result.metadata["walk_forward_result"].folds
    measurements = []
    for fold in actual_folds:
        params = wf["params_by_fold"][fold.fold_id]
        report = {}
        for role, index in (("is", fold.train_index), ("forward", fold.test_index)):
            signal = strategy(frame, params, fold.train_index, index, fold)
            segment = QuantBTEndpoint.pct_equity(**account).backtest(data=frame.loc[index], signal=signal)
            observed = segment.full_report(trading_days=365)
            valid = np.isfinite(observed["sharpe"]) and float(np.std(segment.returns)) > 0
            report[role] = dict(status="VALID" if valid else "UNDEFINED", raw_sharpe=observed["sharpe"],
                                trades=observed["num_trades"], final_equity=observed["final_equity"])
        measurements.append(dict(fold_id=fold.fold_id, **report,
                                 decay=report["is"]["raw_sharpe"] - report["forward"]["raw_sharpe"]))
    studies = wf["sampler_studies"]
    counts = {key: sum(s["states"].get(key, 0) for s in studies) for key in ("COMPLETE", "PRUNED", "FAIL")}
    assert sum(s["attempts"] for s in studies) == 4 * TRIALS and counts["FAIL"] == 0
    trace = [{key: row.get(key) for key in ("trial_id", "params", "objective", "mean_is_sharpe", "pruned", "fold_id")}
             for row in wf["trial_table"].to_dict("records")]
    report = bt.full_report(trading_days=365)
    record = dict(case=case, arm=arm, seed=seed, config_seconds=config_seconds,
                  wall_seconds=wall, cpu_seconds=cpu, replay_measurement_seconds=perf_counter() - replay_started,
                  peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  rss_scope="same-process absolute peak, not isolated per-arm memory superiority",
                  attempts=4 * TRIALS, states=counts,
                  unique_candidates=sum(s["unique_effective_candidates"] for s in studies),
                  relative_proposal_trials=sum(s["relative_proposal_trials"] for s in studies),
                  independent_calls=sum(sum(s["independent_sample_calls"].values()) for s in studies),
                  sampler_seconds=sum(s["sampler_wall_seconds"] for s in studies),
                  final_equity=report["final_equity"], total_return_pct=report["total_return_pct"],
                  sharpe=report["sharpe"], max_drawdown_pct=report["max_drawdown_pct"],
                  fold_measurements=measurements, selected_params=wf["params_by_fold"], trial_trace=trace,
                  trace_hash=identity(trace), selected_hash=identity(wf["params_by_fold"]),
                  arrays_hash={name: sha256(np.ascontiguousarray(a).tobytes()).hexdigest() for name, a in arrays.items()},
                  accounting_replay="EXACT", source_identity=identity(recorded["source"]))
    output = PRIVATE if case == "delta_rsi" else LANE / "public"
    write_once(output / f"{arm}-{seed}.json", record)
    arrays_path = output / f"{arm}-{seed}.npz"
    if arrays_path.exists():
        raise FileExistsError(arrays_path)
    np.savez_compressed(arrays_path, **arrays)
    print(f"{case}/{arm}/seed={seed}: {wall:.3f}s; accounting replay exact", flush=True)


def study():
    value = registration()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    for case, arms in value["arms"].items():
        # Rotate execution order without changing any per-study RNG seed.
        for i, seed in enumerate(value["seeds"]):
            for arm in arms[i:] + arms[:i]:
                capture(case, arm, seed)


def summary():
    value = registration()
    records, parity = [], []
    for case, arms in value["arms"].items():
        root = PRIVATE if case == "delta_rsi" else LANE / "public"
        for seed in value["seeds"]:
            loaded = {arm: json.loads((root / f"{arm}-{seed}.json").read_text()) for arm in arms}
            a, b = loaded["manual_cma"], loaded["helper_cma"]
            for field in ("trace_hash", "selected_hash", "arrays_hash", "fold_measurements", "states"):
                assert a[field] == b[field], (case, seed, field)
            for name in ("equity", "positions", "returns"):
                with np.load(root / f"manual_cma-{seed}.npz") as left, np.load(root / f"helper_cma-{seed}.npz") as right:
                    np.testing.assert_array_equal(left[name], right[name])
            parity.append(dict(case=case, seed=seed, proposals_objectives_selection_account="EXACT"))
            for arm, row in loaded.items():
                fields = ("case", "arm", "seed", "config_seconds", "wall_seconds", "cpu_seconds", "sampler_seconds",
                          "peak_rss_mib", "attempts", "states", "unique_candidates", "relative_proposal_trials",
                          "independent_calls", "final_equity", "total_return_pct", "sharpe", "max_drawdown_pct",
                          "fold_measurements", "accounting_replay")
                records.append({**{k: row[k] for k in fields}, "raw_receipt_sha256": file_hash(root / f"{arm}-{seed}.json")})
    aggregate = []
    for case, arms in value["arms"].items():
        for arm in arms:
            rows = [r for r in records if r["case"] == case and r["arm"] == arm]
            metrics = [m for r in rows for m in r["fold_measurements"] if m["is"]["status"] == m["forward"]["status"] == "VALID"]
            aggregate.append(dict(case=case, arm=arm, seeds=len(rows), paired_valid_folds=len(metrics),
                                  median_equity=float(np.median([r["final_equity"] for r in rows])),
                                  median_wall_seconds=float(np.median([r["wall_seconds"] for r in rows])),
                                  mean_is_sharpe=float(np.mean([m["is"]["raw_sharpe"] for m in metrics])),
                                  mean_forward_sharpe=float(np.mean([m["forward"]["raw_sharpe"] for m in metrics])),
                                  mean_decay=float(np.mean([m["decay"] for m in metrics]))))
    write_once(LANE / "summary.json", dict(schema="qms-sampler-helper-evidence-v1", registration_sha256=file_hash(LANE / "registration.json"),
                                         source=value["source"], parity=parity, aggregate=aggregate, cells=records,
                                         claim="diagnostic only; exact helper/manual parity is not sampler superiority",
                                         privacy="private source/market/ranges/winning params excluded", publication=False))
    print(json.dumps(aggregate, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "study", "summary"))
    args = parser.parse_args()
    {"register": register, "study": study, "summary": summary}[args.command]()
