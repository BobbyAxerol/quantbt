"""Owner-approved real-alpha review; private inputs/artifacts, no release actions.

Run prepare with the data-loader environment, then worker with the qualified
installed candidate environment. Never execute notebook tuning/display cells.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
import importlib.metadata
import importlib.util
import json
import math
from pathlib import Path
import resource
import sys
from time import perf_counter, process_time


REPO = Path(__file__).resolve().parents[1]
PRIVATE_ROOT = REPO / "data/local/qms-real-review"
NOTEBOOK = Path(
    "/root/bobby/pool_alpha/alphas_storage/TA/gradient_rsi/gradient_rsi_holdout_live.ipynb"
)
ACCOUNT = dict(
    initial_capital=20000, leverage=1, maintenance_ratio=0.005,
    contract_size=1.0, use_funding=True, funding_rate=0.0001,
    alloc_per_trade=0.5, fee=0.0005, slippage=0.0001, use_pyramiding=False,
)
RECIPES = ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol")


def private_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError("review source/raw outputs must stay in ignored private storage")
    return path


def clean(value):
    """Retain undefined/nonfinite report values explicitly, never as fake zero."""
    import numpy as np
    import pandas as pd
    from collections.abc import Mapping

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: clean(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return "UNDEFINED_NAN" if math.isnan(value) else str(value)
    return value


def dump(path, value):
    private_path(path).write_text(json.dumps(clean(value), indent=2, allow_nan=False) + "\n")


def digest(value):
    return sha256(json.dumps(clean(value), sort_keys=True).encode()).hexdigest()


def extract_alpha(notebook):
    content = json.loads(Path(notebook).read_text())
    code = "".join(content["cells"][7]["source"])
    tree = ast.parse(code)
    if any(not isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef)) for n in tree.body):
        raise ValueError("alpha cell has unexpected top-level execution")
    if "generate_delta_rsi_signals" not in {getattr(n, "name", None) for n in tree.body}:
        raise ValueError("wrong alpha cell")
    ranges = None
    for node in ast.parse("".join(content["cells"][19]["source"])).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "param_ranges" for t in node.targets
        ):
            ranges = ast.literal_eval(node.value)
    if ranges is None or len(ranges) != 8:
        raise ValueError("registered eight-dimensional search space changed")
    return code, ranges


def prepare(root):
    import pandas as pd

    root.mkdir(parents=True, exist_ok=True)
    code, ranges = extract_alpha(NOTEBOOK)
    (root / "alpha.py").write_text(code)
    sys.path.insert(0, "/root/bobby/pool_alpha/alphas_storage/_get_data")
    from data_loader import CryptoBinance1m

    started = perf_counter()
    frame = CryptoBinance1m().load_resampled(
        "ETHUSDT", timeframe="1h", start_date="2020-01-01",
        end_date="2024-04-30 23:59:59", check_val=True,
    ).sort_values("time").rename(columns={"time": "datetime"}).set_index("datetime")
    frame.index = pd.DatetimeIndex(frame.index)
    frame.index = (frame.index.tz_localize("UTC") if frame.index.tz is None
                   else frame.index.tz_convert("UTC"))
    frame = frame.loc["2020-01-01":"2024-04-30 23:59:59"]
    market = validate_market(frame)
    frame.to_csv(root / "market.csv.gz", compression="gzip", index_label="datetime")
    registration = {
        "schema": "qms-real-review-v1", "alpha": "Gradient RSI", "symbol": "ETHUSDT",
        "timeframe": "1h", "notebook_sha256": sha256(NOTEBOOK.read_bytes()).hexdigest(),
        "alpha_sha256": sha256(code.encode()).hexdigest(), "ranges": ranges,
        "account": ACCOUNT, "canonical_one_way_fee_rate": 0.00025,
        "market": market, "load_seconds": perf_counter() - started,
        "source_commit": "6c0f877", "research_exposure": "research_only",
        "calendar": "monthly 2022-01 through 2024-04; rolling 365D IS",
        "main_trials_per_fold": 128, "minimum_origins": 12, "seed": 731,
        "sampler_trials_per_fold": 32, "sampler_repeats": 3,
        "scientific_claim": "ETH functional/paired review, not primary BTC certification",
    }
    dump(root / "registration.json", registration)
    print(json.dumps(market, indent=2), flush=True)


def validate_market(frame):
    import numpy as np
    import pandas as pd

    required = ["open", "high", "low", "close", "volume"]
    if (frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing
            or frame.index.tz is None):
        raise ValueError("invalid market calendar")
    a = frame[required].to_numpy(dtype=float)
    if not np.isfinite(a).all() or (a[:, :4] <= 0).any() or (a[:, 4] < 0).any():
        raise ValueError("invalid OHLCV")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ValueError("incoherent OHLC")
    expected = pd.date_range(frame.index[0], frame.index[-1], freq="1h")
    hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
    return dict(bars=len(frame), start=frame.index[0].isoformat(),
                end=frame.index[-1].isoformat(), missing_hours=len(expected.difference(frame.index)),
                data_sha256=sha256(hashed).hexdigest(), missing_policy="no synthetic filling")


def memory():
    values = {}
    for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
        if line.startswith(("Rss:", "Pss:")):
            key, value, _ = line.split()
            values[key.rstrip(":").lower() + "_mib"] = int(value) / 1024
    values["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return values


def load_inputs(root):
    import pandas as pd

    registration = json.loads((root / "registration.json").read_text())
    alpha_path = root / "alpha.py"
    if sha256(alpha_path.read_bytes()).hexdigest() != registration["alpha_sha256"]:
        raise ValueError("private alpha identity changed")
    spec = importlib.util.spec_from_file_location("qms_private_real_alpha", alpha_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    frame = pd.read_csv(root / "market.csv.gz", index_col="datetime", parse_dates=["datetime"])
    if validate_market(frame) != registration["market"]:
        raise ValueError("private market identity changed")
    ranges = {k: tuple(v) for k, v in registration["ranges"].items()}
    return registration, module, frame, ranges


def endpoint_for(strategy, arm, recipe, trials):
    from quantbt import QuantBTEndpoint

    mode = "off" if arm == "off" else "shadow" if arm == "shadow" else "active"
    policy = "reference" if arm == "active_reference" else "require"
    return QuantBTEndpoint.walk_forward(
        strategy_class=strategy, split_mode="2022-01-01", split_frequency="monthly",
        window_mode="rolling", train_window="365D", target_mode="pct_equity",
        optimization_mode="mode_4_is_only_robust", optimization_schedule="per_fold_causal",
        optuna_trials=trials, optuna_early_stopping=None,
        random_seed=731, target_runtime="numba", **ACCOUNT,
        optimization_config=dict(
            sampler_config={"name": recipe},
            scoring_backend="endpoint", use_scalar_trial_scoring=False,
            native_prepared_wfo="off", wfo_execution_reuse="off", top_is_fraction=0.10,
            flat_eps=0.15, flat_min_samples=3, flat_selector="medoid", is_subperiods=1,
            candidate_selection_metric="is_only_robust", scoring_trading_days=365,
            min_trades_per_year=100, trade_penalty_factor=0.5,
            meta_selection=dict(mode=mode, native_batch_policy=policy,
                                label_observer=mode != "off", min_matured_origins=12),
        ),
    )


def worker(root, kind, arm, recipe):
    import numpy as np
    import optuna
    import quantbt
    from quantbt import QuantBTEndpoint
    from quantbt.optimization.meta_selection.config import MetaHistoryContext
    from quantbt.optimization.meta_selection.history import MetaHistory

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    registration, alpha, frame, ranges = load_inputs(root)
    if "site-packages" not in str(Path(quantbt.__file__).resolve()):
        raise ValueError("real review must exercise installed candidate, not a source shadow")
    baseline = {k: spec[0] for k, spec in ranges.items()}
    probe = frame.iloc[:9000].copy()
    prefix = alpha.generate_delta_rsi_signals(probe, baseline)["pos_weight"]
    mutated = probe.copy()
    mutated.loc[mutated.index[7000:], ["open", "high", "low", "close"]] *= 1.7
    mutated.loc[mutated.index[7000:], "volume"] *= 2.0
    alternate = alpha.generate_delta_rsi_signals(mutated, baseline)["pos_weight"]
    np.testing.assert_array_equal(prefix.iloc[:7000], alternate.iloc[:7000])

    def strategy(data, params, train_index, test_index, fold):
        history = data.loc[:test_index[-1]]
        generated = alpha.generate_delta_rsi_signals(history, dict(params))
        return generated["pos_weight"].reindex(test_index).fillna(0.0).astype(float)

    def execute(data, trials):
        endpoint = endpoint_for(strategy, arm, recipe, trials)
        context = MetaHistoryContext(
            history=MetaHistory(max_revisions=256), corpus_id="gradient-eth-real-review",
            instrument_id="ETHUSDT-linear-perpetual", timeframe="1h", run_id="qms-real-review",
        )
        kwargs = {} if arm == "off" else {"meta_history": context}
        result = endpoint.backtest(data=data, param_ranges=ranges, **kwargs)
        return endpoint, result, context

    data = frame.loc[:"2022-02-28 23:59:59"] if kind == "sampler" else frame
    cold = perf_counter()
    execute(frame.loc[:"2022-02-28 23:59:59"], 32)
    cold_seconds = perf_counter() - cold
    samples = []
    for repetition in range(3 if kind == "sampler" else 1):
        before = memory()
        wall, cpu = perf_counter(), process_time()
        endpoint, result, context = execute(data, 32 if kind == "sampler" else 128)
        wall, cpu = perf_counter() - wall, process_time() - cpu
        after = memory()
        wf = result.metadata["walk_forward"]
        studies = wf["sampler_studies"]
        meta = dict(wf.get("meta_selection", {}))
        if meta:
            import pandas as pd

            final_view = context.history.snapshot(
                family_id=meta["tasks"][0].family.family_id,
                authorized_corpora=context.authorized_corpora,
                outcome_origins=context.outcome_origins,
                research_exposures=context.research_exposures,
                information_as_of=pd.Timestamp("2024-05-02", tz="UTC"),
            )
            meta["_review_revisions"] = final_view.revisions
        arrays = {name: getattr(result, name).to_numpy(dtype=float)
                  for name in ("positions", "equity", "returns")}
        array_path = root / f"{kind}_{arm}_{recipe}_{repetition}.npz"
        np.savez_compressed(array_path, **arrays)
        records = meta.get("records", ())
        paired = []
        for row, task in zip(records, meta.get("tasks", ())):
            revision = context_revision(meta, row)
            if revision is None:
                raise AssertionError("observer revision missing")
            candidates = {c.evaluation_id: c for c in task.candidates}
            outcomes = {o.evaluation_id: o.observation for o in revision.outcomes}
            sides = {}
            for label, eid in (("native", task.anchor.evaluation_id),
                               ("meta", row["selected_evaluation_id"])):
                observed_is, forward = candidates[eid].observation, outcomes[eid]
                valid = observed_is.status.value == forward.status.value == "VALID"
                sides[label] = dict(status="VALID" if valid else "UNDEFINED",
                                    is_sharpe=observed_is.raw_sharpe if valid else None,
                                    forward_sharpe=forward.raw_sharpe if valid else None)
            assert not row["current_outer_oos_used_for_selection"]
            assert task.data_cutoff < task.first_forward_action_at
            snapshot = next(s for s in meta["snapshots"] if s.snapshot_id == row["training_snapshot_id"])
            assert all(r.revision_available_at < task.first_forward_action_at
                       and r.task.forward_end <= task.data_cutoff for r in snapshot.revisions)
            assert task.anchor.evaluation_id in row["panel_members"]
            assert row["selected_evaluation_id"] in row["panel_members"]
            assert clean(candidates[row["selected_evaluation_id"]].effective_params) == clean(row["selected_params"])
            paired.append(dict(fold_id=row["fold_id"], start=task.forward_start.isoformat(),
                               end=task.forward_end.isoformat(), **sides,
                               matured_origins=row["matured_origins"],
                               reason=row["final_selection_reason"]))
        full_arrays = result.metadata["walk_forward_result"].oos_output
        check = QuantBTEndpoint.pct_equity(target_runtime="numba", **ACCOUNT).backtest(
            data=data, signal=full_arrays,
        )
        for name in arrays:
            np.testing.assert_allclose(arrays[name], getattr(check, name).to_numpy(dtype=float),
                                       rtol=1e-10, atol=1e-10)
        sample = dict(
            repetition=repetition, wall_seconds=wall, cpu_seconds=cpu,
            before_memory=before, after_memory=after,
            sampler_seconds=sum(s["sampler_wall_seconds"] for s in studies),
            counts=dict(
                attempted=sum(s["attempts"] for s in studies),
                completed=sum(s["states"].get("COMPLETE", 0) for s in studies),
                failed=sum(s["states"].get("FAIL", 0) for s in studies),
                pruned=sum(s["states"].get("PRUNED", 0) for s in studies),
                unique_candidates=sum(s["unique_effective_candidates"] for s in studies),
            ),
            folds=len(wf["fold_table"]), trial_rows=len(wf["trial_table"]),
            metrics=endpoint.full_report(trading_days=365),
            params=wf["params_by_fold"], trials=wf["trial_table"].to_dict("records"),
            sampler_studies=studies, meta_elapsed=meta.get("elapsed_seconds", {}),
            observer_attempts=meta.get("observer_attempts", 0),
            observer_failures=meta.get("observer_failures", 0),
            records=records, paired=paired,
            arrays_sha256={name: sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
                           for name, a in arrays.items()},
            checks=dict(signal_future_suffix=True, stitched_account=True,
                        snapshot_availability=True, pool_panel_selection=True),
        )
        # Full original witnesses stay private; no alpha source/raw data in git.
        dump(root / f"{kind}_{arm}_{recipe}_{repetition}_witness.json",
             dict(tasks=meta.get("tasks", ()), revisions=meta.get("_review_revisions", ())))
        samples.append(sample)
        print(f"{kind}/{arm}/{recipe}: {sample['folds']} folds, {wall:.3f}s, "
              f"{sample['observer_attempts']} observer evaluations", flush=True)
    output = dict(schema="qms-real-review-worker-v1", kind=kind, arm=arm, recipe=recipe,
                  registration_digest=digest(registration), cold_warmup_seconds=cold_seconds,
                  versions={p: importlib.metadata.version(p) for p in
                            ("quantbt-engine", "quantbt-native", "optuna", "numpy", "numba")},
                  core_origin=str(Path(quantbt.__file__).resolve()), samples=samples)
    dump(root / f"{kind}_{arm}_{recipe}.json", output)


def context_revision(meta, row):
    """Final observer revision is not necessarily in any earlier decision snapshot."""
    return next((r for r in meta.get("_review_revisions", ())
                 if r.revision_id == row.get("observer_revision_id")), None)


def trial_trace(sample):
    return [{k: row.get(k) for k in (
        "trial_id", "params", "objective", "mean_is_sharpe", "pruned", "fold_id",
    )} for row in sample["trials"]]


def compare_arrays(left, right):
    import numpy as np

    differences = {}
    with np.load(left) as a, np.load(right) as b:
        assert set(a.files) == set(b.files) == {"positions", "equity", "returns"}
        for field in a.files:
            np.testing.assert_allclose(a[field], b[field], rtol=1e-10, atol=1e-10)
            differences[field] = float(np.max(np.abs(a[field] - b[field])))
    return differences


def summarize(root):
    import numpy as np
    from quantbt.optimization.meta_selection.common import wire

    # Load the existing pure saved-output decomposition, not another scorer.
    spec = importlib.util.spec_from_file_location(
        "qms_saved_output_review", REPO / "tools/qms08_research.py"
    )
    saved = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(saved)
    workers = {arm: json.loads((root / f"meta_{arm}_tpe_legacy.json").read_text())
               for arm in ("off", "shadow", "active_rust", "active_reference")}
    data_ids = {w["registration_digest"] for w in workers.values()}
    assert len(data_ids) == 1
    samples = {arm: w["samples"][0] for arm, w in workers.items()}
    for arm, sample in samples.items():
        assert sample["folds"] == 28 and sample["counts"]["attempted"] == 28 * 128
        assert sample["counts"]["failed"] == 0
        assert sample["observer_failures"] == 0
        assert all(sample["checks"].values())
        assert all(s["warm_start_attempts"] == 0 for s in sample["sampler_studies"])
    assert samples["off"]["params"] == samples["shadow"]["params"]
    assert trial_trace(samples["off"]) == trial_trace(samples["shadow"])
    assert samples["active_rust"]["params"] == samples["active_reference"]["params"]
    assert trial_trace(samples["active_rust"]) == trial_trace(samples["active_reference"])
    checks = {}
    for left, right in (("off", "shadow"), ("active_rust", "active_reference")):
        checks[f"{left}_vs_{right}"] = compare_arrays(
            root / f"meta_{left}_tpe_legacy_0.npz", root / f"meta_{right}_tpe_legacy_0.npz"
        )
    for a, b in zip(samples["active_rust"]["paired"], samples["active_reference"]["paired"]):
        assert {k: a[k] for k in ("fold_id", "matured_origins", "reason")} == {
            k: b[k] for k in ("fold_id", "matured_origins", "reason")
        }
        for side in ("native", "meta"):
            assert a[side]["status"] == b[side]["status"]
            if a[side]["status"] == "VALID":
                np.testing.assert_allclose(
                    [a[side]["is_sharpe"], a[side]["forward_sharpe"]],
                    [b[side]["is_sharpe"], b[side]["forward_sharpe"]],
                    rtol=1e-9, atol=1e-10,
                )
    pairs = samples["active_rust"]["paired"]
    fields = ("fold_id", "start", "end", "native", "meta")
    all_pairs = saved.paired_decomposition([{k: row[k] for k in fields} for row in pairs])
    supported = saved.paired_decomposition(
        [{k: row[k] for k in fields} for row in pairs if row["matured_origins"] >= 12]
    )
    confidence = dict(status="INSUFFICIENT_SUPPORTED_CONSECUTIVE_PAIRS")
    valid = [r for r in supported["rows"] if r["status"] == "VALID"]
    if len(valid) >= 12 and all(
        b["fold_id"] == a["fold_id"] + 1 for a, b in zip(valid, valid[1:])
    ):
        from arch.bootstrap import MovingBlockBootstrap

        values = np.array([[r["r"], r["q"]] for r in valid])
        bs = MovingBlockBootstrap(3, values, seed=731)
        intervals = bs.conf_int(lambda a: a.mean(axis=0), reps=4096, method="percentile", size=0.95)
        confidence = dict(status="DESCRIPTIVE_RESEARCH_ONLY", block_months=3,
                          resamples=4096, seed=731, r_95=intervals[:, 0].tolist(),
                          q_95=intervals[:, 1].tolist(), independent_market_samples=False)
    sampler_summary = {}
    for recipe in RECIPES:
        w = json.loads((root / f"sampler_off_{recipe}.json").read_text())
        assert w["registration_digest"] in data_ids
        assert len(w["samples"]) == 3
        for s in w["samples"]:
            assert s["counts"]["attempted"] == 64 and s["counts"]["failed"] == 0
            assert s["params"] == w["samples"][0]["params"]
            assert trial_trace(s) == trial_trace(w["samples"][0])
            assert s["arrays_sha256"] == w["samples"][0]["arrays_sha256"]
        sampler_summary[recipe] = dict(
            median_seconds=float(np.median([s["wall_seconds"] for s in w["samples"]])),
            median_sampler_seconds=float(np.median([s["sampler_seconds"] for s in w["samples"]])),
            samples_seconds=[s["wall_seconds"] for s in w["samples"]],
            peak_rss_mib=max(s["after_memory"]["peak_rss_mib"] for s in w["samples"]),
            counts=w["samples"][0]["counts"], cold_warmup_seconds=w["cold_warmup_seconds"],
        )
    registration = json.loads((root / "registration.json").read_text())
    summary = dict(
        schema="qms-real-review-summary-v1", registration=registration,
        versions=workers["off"]["versions"], samplers=sampler_summary,
        meta={arm: {key: s[key] for key in (
            "wall_seconds", "cpu_seconds", "sampler_seconds", "before_memory", "after_memory",
            "counts", "observer_attempts", "observer_failures", "meta_elapsed", "metrics", "checks",
        )} for arm, s in samples.items()},
        parity=checks, all_pairs=all_pairs, supported_pairs=supported, uncertainty=confidence,
        switches=sum(r["selected_params"] != r["native_selected_params"]
                     for r in samples["active_rust"]["records"]),
        learned_folds=sum(r["past_matured_forward_used_for_selection"]
                          for r in samples["active_rust"]["records"]),
        real_lineage_status="PASS_REAL_ETH", primary_BTC_certified=False, live_certified=False,
        main_timing_repeats=1,
        private_artifacts={p.name: sha256(p.read_bytes()).hexdigest()
                           for p in sorted(root.glob("*.json")) if p.name != "summary.json"},
    )
    dump(root / "summary.json", wire(summary))
    print(json.dumps(clean({k: summary[k] for k in (
        "samplers", "meta", "parity", "switches", "learned_folds", "uncertainty"
    )}), indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "worker", "summarize"))
    parser.add_argument("--root", type=Path, default=PRIVATE_ROOT)
    parser.add_argument("--kind", choices=("sampler", "meta"), default="meta")
    parser.add_argument("--arm", choices=("off", "shadow", "active_rust", "active_reference"), default="off")
    parser.add_argument("--recipe", choices=RECIPES, default="tpe_legacy")
    args = parser.parse_args()
    root = private_path(args.root)
    if args.action == "prepare":
        prepare(root)
    elif args.action == "summarize":
        summarize(root)
    else:
        worker(root, args.kind, args.arm, args.recipe)


if __name__ == "__main__":
    main()
