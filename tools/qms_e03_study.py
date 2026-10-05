"""Registered scalar study on private immutable ETH inputs; never publishes alpha.

Use register before any worker. Each worker runs one full arm in a fresh process.
Summarize consumes saved original outcomes, not a second financial simulator.
"""

import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
from time import perf_counter, process_time

from tools.qms_real_review import (ACCOUNT, PRIVATE_ROOT, clean, dump, load_inputs,
                                   memory, private_path, trial_trace)

CELLS = [(target, backend) for backend in ("native_vectorized", "native_event")
         for target in ("signal_notional", "notional", "unit")]
CELLS += [("pct_equity", "legacy"), ("dca_ladder", "legacy")]


def read_registration(output):
    path = private_path(output) / "e03-registration.json"
    registration = json.loads(path.read_text())
    assert registration["schema"] == "qms-e03-registered-study-v1"
    assert registration["attempts_per_fold"] == 128 and registration["seed"] == 731
    assert registration["minimum_origins"] == 12
    return registration, sha256(path.read_bytes()).hexdigest()


def register(output):
    output = private_path(output)
    if output.exists():
        raise ValueError("registration cannot overwrite an existing study")
    original, _, _, _ = load_inputs(PRIVATE_ROOT)
    from quantbt.optimization.meta_selection.common import digest
    from tools.qms_e03_source_guard import verify
    output.mkdir(parents=True)
    registration = dict(schema="qms-e03-registered-study-v1",
        owner_approval="E03 user protocol approval: 128/731/12/3-month95%, R>0 and Q lower>=0",
        source=verify(), private_input_registration_sha256=digest(original),
        alpha_sha256=original["alpha_sha256"], market=original["market"],
        research_exposure="previously_research_exposed_not_locked_holdout",
        cells=[dict(target=t, backend=b, alpha="simulated_causal_mean_reversion_ladder"
                    if t == "dca_ladder" else "owner_selected_gradient_delta_rsi") for t, b in CELLS],
        attempts_per_fold=128, seed=731, minimum_origins=12, sampler="tpe_legacy",
        split_start="2022-01-01", split_frequency="monthly", rolling_train="365D",
        forward_end="2024-04-30", block_months=3, confidence=.95, resamples=4096,
        threshold=dict(mean_r_strictly_greater=0., lower_forward_q_at_least=0.),
        no_outcome_retuning=True, account=clean(ACCOUNT),
        scalar_allocation_quote=10000., scalar_qty_step=.001, v2_slippage_bps=1.,
        diagnostic_account="fresh_reset", final_account="existing_continuous_stitched_targets",
        ladder_policy=dict(dca_base_notional=5000., dca_safety_notional=2500.,
                           dca_step_pct=.02, dca_max_safety_orders=2, dca_take_profit_pct=.04),
        paired_arms=("off", "active"), observer_charge="separate_actual_evaluations",
        prepared_parity="additional_identical_study_only_for_supported_same_close_targets",
        cpu_policy="one_fresh_process_per_arm_single_worker_no_parallel_studies",
        runtime_budget="one frozen full study per arm; no trial increases or successful retry filtering",
        publication=False)
    dump(output / "e03-registration.json", registration)
    return registration


def endpoint(strategy, target, backend, arm, registration, prepared):
    from quantbt import QuantBTEndpoint
    account = dict(ACCOUNT)
    if target != "pct_equity":
        account["alloc_per_trade"] = registration["scalar_allocation_quote"]
        account["qty_step"] = registration["scalar_qty_step"]
    if backend != "legacy":
        account["slippage_bps"] = registration["v2_slippage_bps"]
    extra = dict(registration["ladder_policy"]) if target == "dca_ladder" else {}
    return QuantBTEndpoint.walk_forward(strategy_class=strategy,
        split_mode=registration["split_start"], split_frequency="monthly",
        window_mode="rolling", train_window="365D", target_mode=target,
        backend=backend, optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", optuna_trials=128,
        optuna_early_stopping=None, random_seed=731,
        target_runtime="rust" if prepared == "require" else "numba", **account, **extra,
        optimization_config=dict(sampler_config=dict(name="tpe_legacy"),
            scoring_backend="endpoint", use_scalar_trial_scoring=False,
            native_prepared_wfo=prepared, wfo_execution_reuse="off",
            top_is_fraction=.10, flat_eps=.15, flat_min_samples=3, flat_selector="medoid",
            is_subperiods=1, candidate_selection_metric="is_only_robust", scoring_trading_days=365,
            min_trades_per_year=100, trade_penalty_factor=.5,
            meta_selection=dict(mode=arm, native_batch_policy="require", label_observer=arm != "off",
                                min_matured_origins=12)))


def worker(output, target, backend, arm, prepared="off"):
    import numpy as np
    import pandas as pd
    import optuna
    import quantbt
    import _quantbt_native as native
    from quantbt import QuantBTEndpoint
    from quantbt.endpoint import _walkforward_scoring_config
    from quantbt.optimization.meta_selection.common import digest, wire
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory

    output = private_path(output)
    registration, registered_hash = read_registration(output)
    if (target, backend) not in CELLS or arm not in {"off", "active"}:
        raise ValueError("unregistered arm/cell")
    name = f"{target}-{backend}-{arm}-{prepared}"
    if (output / f"{name}.json").exists():
        raise ValueError("sealed arm; choose a new separately registered study")
    assert "site-packages" in Path(quantbt.__file__).resolve().parts
    assert quantbt.__version__ == "1.1.2" and native.version() == "0.4.3"
    installed = Path(quantbt.__file__).resolve().parent
    for source, expected in registration["source"]["source_sha256"].items():
        module = installed / source.removeprefix("src/quantbt/")
        assert sha256(module.read_bytes()).hexdigest() == expected, source
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    loading = perf_counter()
    original, alpha, data, ranges = load_inputs(PRIVATE_ROOT)
    assert digest(original) == registration["private_input_registration_sha256"]
    loading = perf_counter()-loading
    if target == "dca_ladder":
        ranges = {"window": (12, 72, 2)}

        def strategy(data, params, train_index, test_index, fold):
            history = data.loc[:test_index[-1]]
            distance = history.close / history.close.rolling(int(params["window"])).mean()-1.
            signal = np.sign(-distance).where(distance.abs() > .01, 0.)*3.
            return signal.reindex(test_index).fillna(0.).astype(float)
    else:
        def strategy(data, params, train_index, test_index, fold):
            generated = alpha.generate_delta_rsi_signals(data.loc[:test_index[-1]], dict(params))
            return generated["pos_weight"].reindex(test_index).fillna(0.).astype(float)

    bt = endpoint(strategy, target, backend, arm, registration, prepared)
    ctx = MetaHistoryContext(MetaHistory(max_revisions=256), "e03-private-cell-study",
        "ETHUSDT-linear-perpetual", "1h", "e03-cell", native_module=native)
    before = memory()
    wall, cpu = perf_counter(), process_time()
    result = bt.backtest(data=data, param_ranges=ranges,
                         **({"meta_history": ctx} if arm != "off" else {}))
    elapsed, cpu = perf_counter()-wall, process_time()-cpu
    wf = result.metadata["walk_forward"]
    studies = wf["sampler_studies"]
    assert len(wf["fold_table"]) == 28
    assert sum(s["attempts"] for s in studies) == 28*128
    assert sum(s["states"].get("FAIL", 0) for s in studies) == 0
    meta = wf.get("meta_selection", {})
    paired, witnesses = [], []
    if meta:
        assert meta["observer_failures"] == 0
        history = ctx.history.snapshot(family_id=meta["tasks"][0].family.family_id,
            authorized_corpora=ctx.authorized_corpora, outcome_origins=ctx.outcome_origins,
            research_exposures=ctx.research_exposures, information_as_of=pd.Timestamp("2024-05-02", tz="UTC"))
        revisions = {r.revision_id: r for r in history.revisions}
        for row, task in zip(meta["records"], meta["tasks"], strict=True):
            revision = revisions[row["observer_revision_id"]]
            candidates = {c.evaluation_id: c for c in task.candidates}
            outcomes = {o.evaluation_id: o.observation for o in revision.outcomes}
            sides = {}
            for label, eid in (("native", task.anchor.evaluation_id), ("meta", row["selected_evaluation_id"])):
                is_value, forward = candidates[eid].observation, outcomes[eid]
                valid = is_value.status.value == forward.status.value == "VALID"
                sides[label] = dict(status="VALID" if valid else "UNDEFINED",
                    is_sharpe=is_value.raw_sharpe if valid else None,
                    forward_sharpe=forward.raw_sharpe if valid else None)
            assert not row["current_outer_oos_used_for_selection"]
            snapshot = next(s for s in meta["snapshots"] if s.snapshot_id == row["training_snapshot_id"])
            assert all(r.task.forward_end <= task.data_cutoff and
                       r.revision_available_at <= task.data_cutoff for r in snapshot.revisions)
            assert dict(candidates[row["selected_evaluation_id"]].effective_params) == dict(row["selected_params"])
            paired.append(dict(fold_id=row["fold_id"], start=task.forward_start.isoformat(),
                end=task.forward_end.isoformat(), **sides, matured_origins=row["matured_origins"],
                selected=row["selected_evaluation_id"], anchor=task.anchor.evaluation_id))
        witnesses = wire(dict(tasks=meta["tasks"], revisions=history.revisions))
    arrays = {name: getattr(result, name).to_numpy(dtype=float) for name in ("equity", "returns", "positions")}
    np.savez_compressed(output / f"{name}.npz", **arrays)
    # This is an independent account conformance check, never an observer replay
    # or a source of learner labels. Charge its cost separately from the study.
    check_start = perf_counter()
    diagnostic = QuantBTEndpoint(_walkforward_scoring_config(bt.config, target))
    check = diagnostic.backtest(data=data, signal=result.metadata["walk_forward_result"].oos_output)
    for key in arrays:
        np.testing.assert_allclose(arrays[key], getattr(check, key).to_numpy(dtype=float), rtol=1e-10, atol=1e-8)
    if witnesses:
        dump(output / f"{name}-witness.json", witnesses)
    sample = dict(schema="qms-e03-cell-arm-v1", name=name, target=target, backend=backend,
        arm=arm, prepared=prepared, registration_sha256=registered_hash,
        source_sha256=registration["source"]["source_sha256"], core_origin=str(Path(quantbt.__file__).resolve()),
        versions={p:importlib.metadata.version(p) for p in ("quantbt-engine", "quantbt-native", "optuna", "numpy")},
        load_seconds=loading, wall_seconds=elapsed, cpu_seconds=cpu,
        account_check_seconds=perf_counter()-check_start, before_memory=before, after_memory=memory(),
        attempts=sum(s["attempts"] for s in studies),
        completed=sum(s["states"].get("COMPLETE", 0) for s in studies),
        pruned=sum(s["states"].get("PRUNED", 0) for s in studies),
        trials=wf["trial_table"].to_dict("records"), params=wf["params_by_fold"],
        full_report=bt.full_report(trading_days=365), paired=paired,
        meta_elapsed=meta.get("elapsed_seconds", {}), observer_attempts=meta.get("observer_attempts", 0),
        observer_failures=meta.get("observer_failures", 0), cache=wf.get("prepared_scoring_cache"),
        checks=dict(account_original=True, snapshot_causal=True, actual_params=True),
        witness_sha256=sha256((output / f"{name}-witness.json").read_bytes()).hexdigest() if witnesses else None)
    dump(output / f"{name}.json", wire(sample))
    print(json.dumps(dict(cell=f"{target}/{backend}", arm=arm, seconds=elapsed,
        attempts=sample["attempts"], observer=sample["observer_attempts"])), flush=True)


def summarize(output):
    import numpy as np
    from arch.bootstrap import MovingBlockBootstrap
    from tools.qms08_research import paired_decomposition

    output = private_path(output)
    registration, registered_hash = read_registration(output)
    rows = []
    for target, backend in CELLS:
        names = [f"{target}-{backend}-{arm}-off" for arm in ("off", "active")]
        if not all((output / f"{name}.json").exists() for name in names):
            rows.append(dict(target=target, backend=backend, status="NOT_EXECUTED"))
            continue
        off, active = [json.loads((output / f"{name}.json").read_text()) for name in names]
        assert off["registration_sha256"] == active["registration_sha256"] == registered_hash
        assert trial_trace(off) == trial_trace(active)
        raw = paired_decomposition([{k: r[k] for k in ("fold_id", "start", "end", "native", "meta")}
                                     for r in active["paired"]])
        supported = {r["fold_id"] for r in active["paired"] if r["matured_origins"] >= 12}
        valid = [r for r in raw["rows"] if r["status"] == "VALID" and r["fold_id"] in supported]
        intervals, passed = None, False
        if len(valid) >= 12 and all(b["fold_id"] == a["fold_id"]+1 for a,b in zip(valid,valid[1:])):
            values = np.array([[r["r"], r["q"], r["is_difference"]] for r in valid])
            bounds = MovingBlockBootstrap(3, values, seed=731).conf_int(
                lambda a:a.mean(axis=0), reps=4096, method="percentile", size=.95)
            intervals = dict(mean=values.mean(axis=0).tolist(), lower=bounds[0].tolist(), upper=bounds[1].tolist())
            passed = bool(intervals["mean"][0] > 0 and intervals["lower"][1] >= 0)
        status = "REGISTERED_R_Q_PASS_OWNER_REVIEW_PENDING" if passed else "NO_GAIN_OR_LOW_PRECISION_NOT_PROMOTED"
        if target == "dca_ladder":
            status = "SIMULATED_STRATEGY_ONLY_NOT_REAL_ALPHA_PROMOTION"
        rows.append(dict(target=target, backend=backend, status=status,
            matched_full_is_search=True, calendar_folds=raw["calendar_folds"],
            valid_folds=raw["paired_valid_folds"], supported_valid_origins=len(valid),
            all_valid_mean_r=raw["mean_fold_r"], all_valid_mean_q=raw["mean_fold_q"],
            supported_interval_r_q_is=intervals, off_report=off["full_report"], active_report=active["full_report"],
            off_seconds=off["wall_seconds"], active_seconds=active["wall_seconds"],
            off_peak_rss_mib=off["after_memory"]["peak_rss_mib"],
            active_peak_rss_mib=active["after_memory"]["peak_rss_mib"],
            observer_attempts=active["observer_attempts"], meta_elapsed=active["meta_elapsed"],
            empirical_promotion=False, owner_review_pending=True))
    receipt = dict(schema="qms-e03-saved-study-summary-v1", registration_sha256=registered_hash,
        rows=rows, research_exposed=True, locked_holdout=False, publication=False)
    dump(output / "e03-summary.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "worker", "summarize"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", choices=tuple(sorted({c[0] for c in CELLS})))
    parser.add_argument("--backend", choices=("native_vectorized", "native_event", "legacy"))
    parser.add_argument("--arm", choices=("off", "active"))
    parser.add_argument("--prepared", choices=("off", "require"), default="off")
    args = parser.parse_args()
    if args.action == "register":
        print(json.dumps(dict(registered_cells=len(register(args.output)["cells"]))))
    elif args.action == "worker":
        worker(args.output, args.target, args.backend, args.arm, args.prepared)
    else:
        print(json.dumps(summarize(args.output), sort_keys=True))
