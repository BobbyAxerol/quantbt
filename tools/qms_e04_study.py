"""Frozen private portfolio diagnostic, not owner-approved economic promotion.

Prepare via the existing loader environment; worker via exact installed E05
consumer. Never execute notebook cells or change the original alpha/account.
"""

import argparse
from hashlib import sha256
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess
from time import perf_counter, process_time

from tools.qms_real_review import (PRIVATE_ROOT, dump, load_inputs, memory,
                                   private_path, trial_trace, validate_market)

SYMBOLS = ("ETHUSDT", "BTCUSDT")
ACCOUNT = dict(initial_capital=20000., leverage=1., maintenance_ratio=.005,
    contract_size=1., alloc_per_trade=.25, fee_rate=.00025, slippage_bps=1.,
    use_funding=True, funding_rate=.0001, use_pyramiding=False)


def register(output):
    import pandas as pd
    import sys
    from tools.qms_e05_source_guard import verify

    output = private_path(output)
    if output.exists():
        raise ValueError("never overwrite a registered study or failed input lane")
    source = verify()
    original, _, eth, ranges = load_inputs(PRIVATE_ROOT)
    output.mkdir(parents=True)
    sys.path.insert(0, "/root/bobby/pool_alpha/alphas_storage/_get_data")
    from data_loader import CryptoBinance1m

    started = perf_counter()
    btc = CryptoBinance1m().load_resampled("BTCUSDT", timeframe="1h",
        start_date="2020-01-01", end_date="2024-04-30 23:59:59", check_val=True)
    btc = btc.sort_values("time").rename(columns={"time": "datetime"}).set_index("datetime")
    btc.index = pd.DatetimeIndex(btc.index)
    btc.index = (btc.index.tz_localize("UTC") if btc.index.tz is None
                 else btc.index.tz_convert("UTC"))
    btc = btc.loc["2020-01-01":"2024-04-30 23:59:59"]
    if not btc.index.equals(eth.index):
        raise ValueError("exact ETH/BTC calendar required; no synthetic repair")
    btc_market = validate_market(btc)
    btc.to_csv(output / "btc.csv.gz", compression="gzip", index_label="datetime")
    receipt = dict(schema="qms-e04-private-diagnostic-v1", source=source,
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        authorization="owner requested real portfolio run; new formal universe/protocol approval pending",
        empirical_promotion=False, locked_holdout=False, research_exposed=True,
        input_registration_sha256=sha256((PRIVATE_ROOT / "registration.json").read_bytes()).hexdigest(),
        alpha_sha256=original["alpha_sha256"], symbols=list(SYMBOLS),
        market={"ETHUSDT": original["market"], "BTCUSDT": btc_market},
        btc_file_sha256=sha256((output / "btc.csv.gz").read_bytes()).hexdigest(),
        load_seconds=perf_counter()-started, ranges=ranges, account=ACCOUNT,
        strategy="unchanged Gradient/Delta RSI independently per symbol; shared params",
        financial_authority="original_native_portfolio_shared_account_full_report",
        portfolio_mode="longshort", sizing="%_equity", final_account="carry_position",
        diagnostic_account="fresh_reset", paired_arms=["off", "active"],
        attempts_per_fold=128, seed=731, minimum_origins=12, sampler="tpe_legacy",
        split_start="2022-01-01", frequency="monthly", train_window="365D",
        forward_end="2024-04-30", expected_folds=28, warm_start=False, early_stopping=None,
        block_months=3, confidence=.95, resamples=4096,
        diagnostic_threshold=dict(mean_r_strictly_greater=0., lower_forward_q_at_least=0.),
        no_outcome_retuning=True, no_runtime_scientific_changes=True,
        cpu_policy="one fresh process per arm; single worker and one numeric thread",
        budget="two frozen full arms; one GiB outputs; no successful retry filtering",
        publication=False)
    dump(output / "registration.json", receipt)
    return receipt


def read_registration(output):
    path = private_path(output) / "registration.json"
    record = json.loads(path.read_text())
    if (record["schema"] != "qms-e04-private-diagnostic-v1" or
            record["attempts_per_fold"] != 128 or record["seed"] != 731 or
            record["symbols"] != list(SYMBOLS) or record["empirical_promotion"]):
        raise ValueError("frozen diagnostic contract changed")
    return record, sha256(path.read_bytes()).hexdigest()


def make_endpoint(strategy, arm, record):
    from quantbt import QuantBTEndpoint

    return QuantBTEndpoint.walk_forward(strategy_class=strategy, symbols=list(SYMBOLS),
        target_mode="portfolio", backend="native_portfolio", sizing=record["sizing"],
        portfolio_mode=record["portfolio_mode"], split_mode=record["split_start"],
        split_frequency=record["frequency"], window_mode="rolling", train_window=record["train_window"],
        optimization_mode="mode_4_is_only_robust", optimization_schedule="per_fold_causal",
        optuna_trials=record["attempts_per_fold"], optuna_early_stopping=None,
        random_seed=record["seed"], **record["account"],
        optimization_config=dict(sampler_config=dict(name="tpe_legacy"),
            scoring_backend="endpoint", use_scalar_trial_scoring=False,
            native_prepared_wfo="off", wfo_execution_reuse="off", top_is_fraction=.10,
            flat_eps=.15, flat_min_samples=3, flat_selector="medoid", is_subperiods=1,
            candidate_selection_metric="is_only_robust", scoring_trading_days=365,
            min_trades_per_year=100, trade_penalty_factor=.5,
            meta_selection=dict(mode=arm, label_observer=arm != "off",
                min_matured_origins=record["minimum_origins"], native_batch_policy="require")))


def worker(output, arm):
    import numpy as np
    import pandas as pd
    import optuna
    import quantbt
    import _quantbt_native as native
    from quantbt import QuantBTEndpoint
    from quantbt.endpoint import _walkforward_scoring_config
    from quantbt.optimization.meta_selection.common import wire
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory

    output = private_path(output)
    record, registered_hash = read_registration(output)
    harness_hash = sha256(Path(__file__).read_bytes()).hexdigest()
    if arm not in record["paired_arms"] or (output / f"{arm}.json").exists():
        raise ValueError("unknown or sealed arm")
    installed = Path(quantbt.__file__).resolve().parent
    assert "site-packages" in installed.parts
    assert quantbt.__version__ == "1.1.2" and native.version() == "0.4.3"
    for source, expected in record["source"]["source_sha256"].items():
        assert sha256((installed / source.removeprefix("src/quantbt/")).read_bytes()).hexdigest() == expected, source
    assert sha256((PRIVATE_ROOT / "registration.json").read_bytes()).hexdigest() == record["input_registration_sha256"]
    assert sha256((output / "btc.csv.gz").read_bytes()).hexdigest() == record["btc_file_sha256"]
    _, alpha, eth, ranges = load_inputs(PRIVATE_ROOT)
    btc = pd.read_csv(output / "btc.csv.gz", index_col="datetime", parse_dates=["datetime"])
    assert validate_market(btc) == record["market"]["BTCUSDT"]
    assert btc.index.equals(eth.index)
    assert {k: list(v) for k, v in ranges.items()} == record["ranges"]
    data = dict(zip(SYMBOLS, (eth, btc), strict=True))
    baseline = {key: spec[0] for key, spec in ranges.items()}
    for frame in data.values():
        probe = frame.iloc[:9000].copy()
        reference = alpha.generate_delta_rsi_signals(probe, baseline)["pos_weight"]
        probe.loc[probe.index[7000:], ["open", "high", "low", "close"]] *= 1.7
        changed = alpha.generate_delta_rsi_signals(probe, baseline)["pos_weight"]
        np.testing.assert_array_equal(reference.iloc[:7000], changed.iloc[:7000])
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    started, latest_fold = perf_counter(), -1

    def strategy(data, params, train_index, test_index, fold):
        nonlocal latest_fold
        if fold.fold_id > latest_fold:
            latest_fold = fold.fold_id
            row = dict(arm=arm, fold_id=latest_fold, stage="fold_started", elapsed_seconds=perf_counter()-started)
            print(json.dumps(row), flush=True)
            with (output / f"{arm}-progress.jsonl").open("a") as stream:
                stream.write(json.dumps(row)+"\n")
        return pd.DataFrame({symbol: alpha.generate_delta_rsi_signals(
            data[symbol].loc[:test_index[-1]], dict(params))["pos_weight"]
            .reindex(test_index).fillna(0.).astype(float) for symbol in SYMBOLS}, index=test_index)

    endpoint = make_endpoint(strategy, arm, record)
    context = MetaHistoryContext(MetaHistory(max_revisions=256), "e04-private-portfolio",
        "ETHUSDT-BTCUSDT-linear-perpetual", "1h", "e04-portfolio-diagnostic", native_module=native)
    before, wall, cpu = memory(), perf_counter(), process_time()
    result = endpoint.backtest(data=data, param_ranges=ranges,
        **({"meta_history": context} if arm != "off" else {}))
    elapsed, cpu, after = perf_counter()-wall, process_time()-cpu, memory()
    wf = result.metadata["walk_forward"]
    studies = wf["sampler_studies"]
    assert len(wf["fold_table"]) == record["expected_folds"]
    assert sum(s["attempts"] for s in studies) == record["expected_folds"]*record["attempts_per_fold"]
    assert sum(s["states"].get("FAIL", 0) for s in studies) == 0
    meta, paired, witnesses = wf.get("meta_selection", {}), [], None
    if meta:
        assert meta["observer_failures"] == 0
        snapshot = context.history.snapshot(family_id=meta["tasks"][0].family.family_id,
            authorized_corpora=context.authorized_corpora, outcome_origins=context.outcome_origins,
            research_exposures=context.research_exposures, information_as_of=pd.Timestamp("2024-05-02", tz="UTC"))
        revisions = {r.revision_id: r for r in snapshot.revisions}
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
            training = next(s for s in meta["snapshots"] if s.snapshot_id == row["training_snapshot_id"])
            assert all(r.task.forward_end <= task.data_cutoff and r.revision_available_at <= task.data_cutoff
                       for r in training.revisions)
            assert dict(candidates[row["selected_evaluation_id"]].effective_params) == dict(row["selected_params"])
            paired.append(dict(fold_id=row["fold_id"], start=task.forward_start.isoformat(),
                end=task.forward_end.isoformat(), **sides, matured_origins=row["matured_origins"],
                selected=row["selected_evaluation_id"], anchor=task.anchor.evaluation_id,
                fallback=row.get("fallback_reason")))
        witnesses = wire(dict(tasks=meta["tasks"], revisions=snapshot.revisions))
    keys = ("equity", "returns", "positions", "fees", "funding", "margin", "diagnostics")
    np.savez_compressed(output / f"{arm}.npz", **{k: np.asarray(getattr(result, k), dtype=float) for k in keys})
    check_start = perf_counter()
    diagnostic = QuantBTEndpoint(_walkforward_scoring_config(endpoint.config, "portfolio"))
    check = diagnostic.backtest(data=data, positions=result.metadata["walk_forward_result"].oos_output,
                               symbols=list(SYMBOLS))
    for key in keys:
        np.testing.assert_array_equal(getattr(result, key), getattr(check, key), err_msg=key)
    for key in ("target_units_report", "accepted_units_report", "turnover_series", "slippage_series"):
        np.testing.assert_array_equal(result.metadata[key], check.metadata[key], err_msg=key)
    if witnesses:
        dump(output / f"{arm}-witness.json", witnesses)
    sample = dict(schema="qms-e04-private-arm-v1", arm=arm, registration_sha256=registered_hash,
        harness_sha256=harness_hash,
        core_origin=str(installed), native_origin=native.__file__,
        versions={p:importlib.metadata.version(p) for p in ("quantbt-engine", "quantbt-native", "optuna", "numpy")},
        wall_seconds=elapsed, cpu_seconds=cpu, account_check_seconds=perf_counter()-check_start,
        before_memory=before, after_memory=after, after_export_memory=memory(),
        timing_policy="one cold public call per arm on shared VPS, not repeated median",
        attempts=sum(s["attempts"] for s in studies),
        completed=sum(s["states"].get("COMPLETE", 0) for s in studies),
        pruned=sum(s["states"].get("PRUNED", 0) for s in studies),
        trials=wf["trial_table"].to_dict("records"), params=wf["params_by_fold"],
        full_report=endpoint.full_report(trading_days=365), paired=paired,
        meta_elapsed=meta.get("elapsed_seconds", {}), observer_attempts=meta.get("observer_attempts", 0),
        observer_failures=meta.get("observer_failures", 0), cache=wf.get("prepared_scoring_cache"),
        checks=dict(original_account_exact=True, snapshot_causal=True, actual_params=True, alpha_prefix_exact=True),
        witness_sha256=sha256((output / f"{arm}-witness.json").read_bytes()).hexdigest() if witnesses else None)
    assert sha256(Path(__file__).read_bytes()).hexdigest() == harness_hash
    dump(output / f"{arm}.json", sample)
    print(json.dumps(dict(arm=arm, seconds=elapsed, attempts=sample["attempts"],
                         observer=sample["observer_attempts"])), flush=True)


def paired_analysis(paired, record):
    import numpy as np
    from arch.bootstrap import MovingBlockBootstrap
    from tools.qms08_research import paired_decomposition

    raw = paired_decomposition([{k: r[k] for k in ("fold_id", "start", "end", "native", "meta")} for r in paired])
    supported = {r["fold_id"] for r in paired if r["matured_origins"] >= record["minimum_origins"]}
    valid = [r for r in raw["rows"] if r["status"] == "VALID" and r["fold_id"] in supported]
    means = {key: math.fsum(r[key] for r in valid)/len(valid) for key in
             ("r", "q", "is_difference", "native_decay", "meta_decay")} if valid else None
    interval = None
    if (len(valid) >= record["minimum_origins"] and
            all(b["fold_id"] == a["fold_id"]+1 for a, b in zip(valid, valid[1:]))):
        values = np.array([[r["r"], r["q"], r["is_difference"]] for r in valid])
        bounds = MovingBlockBootstrap(record["block_months"], values, seed=record["seed"]).conf_int(
            lambda a: a.mean(axis=0), reps=record["resamples"], method="percentile", size=record["confidence"])
        interval = dict(columns=["r", "q", "is_difference"], mean=values.mean(axis=0).tolist(),
                        lower=bounds[0].tolist(), upper=bounds[1].tolist())
    threshold = bool(interval and interval["mean"][0] > 0 and interval["lower"][1] >= 0)
    return dict(calendar_folds=raw["calendar_folds"], valid_folds=raw["paired_valid_folds"],
        supported_valid_origins=len(valid), supported_means=means, interval=interval,
        changed_decisions=sum(r["selected"] != r["anchor"] for r in paired),
        diagnostic_threshold_pass=threshold, empirical_promotion=False,
        status="DIAGNOSTIC_ONLY_OWNER_PROTOCOL_AND_LOCKED_EVALUATION_PENDING", rows=raw["rows"])


def summarize(output):
    output = private_path(output)
    record, registered_hash = read_registration(output)
    off, active = [json.loads((output / f"{arm}.json").read_text()) for arm in record["paired_arms"]]
    assert off["registration_sha256"] == active["registration_sha256"] == registered_hash
    assert off["harness_sha256"] == active["harness_sha256"]
    assert trial_trace(off) == trial_trace(active)
    summary = dict(schema="qms-e04-real-portfolio-summary-v1", registration_sha256=registered_hash,
        source=record["source"], original_account=True, full_is_search_exact=True,
        **paired_analysis(active["paired"], record), off_report=off["full_report"], active_report=active["full_report"],
        off_seconds=off["wall_seconds"], active_seconds=active["wall_seconds"],
        off_peak_rss_mib=off["after_memory"]["peak_rss_mib"], active_peak_rss_mib=active["after_memory"]["peak_rss_mib"],
        meta_elapsed=active["meta_elapsed"], observer_attempts=active["observer_attempts"],
        account_checks_seconds={arm: value["account_check_seconds"] for arm, value in zip(record["paired_arms"], (off, active))},
        report_policy="continuous original account, not compounded fold equity", research_exposed=True, publication=False)
    dump(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "worker", "summarize"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arm", choices=("off", "active"))
    args = parser.parse_args()
    if args.action == "register":
        print(json.dumps(dict(registered=register(args.output)["symbols"])))
    elif args.action == "worker":
        worker(args.output, args.arm)
    else:
        print(json.dumps(summarize(args.output), sort_keys=True))
