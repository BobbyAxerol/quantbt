"""Public synthetic research registration; no private alpha or fake fills."""
from dataclasses import asdict

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.mode5 import CalibrationWindow, Mode5Calibration, calibration_binding, calibration_context
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.dossier.dossier import Dossier
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.dossier.plans import CalibrationPlan
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.selection.contracts import Channel
from quantbt.mode5.statistics.tails import FrozenReference
from quantbt.optimization import SamplerConfig
from quantbt.endpoint import _walkforward_scoring_config

from dossier_fixtures import fixture, spec


def market(days=32):
    idx = pd.date_range("2023-01-01", periods=days*24, freq="h", tz="UTC")
    x = np.arange(len(idx))
    close = 100 + .012*x + 3*np.sin(x/17) + .4*np.sin(x/2.3)
    return pd.DataFrame(dict(open=close-.05, high=close+1., low=close-1., close=close,
                             volume=np.full(len(x), 100.)), index=idx)


def alpha(data, params, train_index, test_index, fold):
    out = pd.Series(np.sign(np.sin(np.arange(len(data))/params["period"])), index=data.index)
    return out.reindex(test_index)


def public_setup(tmp_path, *, selector="full_dro_cvar", sampler_name="tpe_legacy",
                 batch_size=1, trials=8, frame=None, strategy=alpha, ranges=None,
                 execution_endpoint=None, target_mode="pct_equity", prepared=True,
                 min_daily=2, min_utility=-10., requested_selector=None, two_windows=False,
                 sampler_options=None, incumbent=None, warm_start=(), account_options=None,
                 market_role="synthetic"):
    frame = market() if frame is None else frame
    tmp_path.mkdir(parents=True, exist_ok=True)
    ranges = {"period": (6, 24, 1)} if ranges is None else ranges
    sampler = SamplerConfig(sampler_name, constraint_mode="post_filter", **(sampler_options or {}),
        kwargs={"n_startup_trials": 2} if sampler_name in {"tpe_legacy", "tpe_multivariate_group"} else {})
    base_options = dict(scoring_backend="endpoint", use_prepared_scoring_cache=prepared,
        native_prepared_wfo="off", is_subperiods=1)
    account = dict(initial_capital=20000., fee=.0005, slippage=.0001, alloc_per_trade=.5,
                   leverage=1., use_funding=False, symbols=["ETHUSDT"])
    account.update(account_options or {})
    args = dict(strategy_class=strategy, optimization_mode="mode_5_full_robust", target_mode=target_mode,
        split_frequency="single", random_seed=731, optuna_trials=trials)
    if execution_endpoint is not None:
        args["execution_endpoint"] = execution_endpoint
    else:
        args.update(account)
    base = QuantBTEndpoint.walk_forward(**args, optimization_config=base_options)
    execution_config = _walkforward_scoring_config(base.config, target_mode)
    dossier, catalog, kwargs = fixture(tmp_path)
    original_witness = next(iter(catalog._sources.values())).witness
    # Existing diagnostic evidence is mature; current market remains development.
    cutoff = int(frame.index[-1].value)+2*3_600_000_000_000
    access = AccessPolicy("public-selection-v1", tuple(dict.fromkeys(("synthetic", market_role))),
                         ("development-1",), cutoff, "selection")
    if two_windows:
        windows = tuple(CalibrationWindow(f"environment-{i}", int(frame.index[j].value),
            int(frame.index[k].value), AccessWitness("development-1", market_role,
                int(frame.index[j].value), int(frame.index[k].value)+1, cutoff-1))
            for i, (j, k) in enumerate(((0, len(frame)//2-1), (len(frame)//2, len(frame)-1))))
    else:
        windows = (CalibrationWindow("development", int(frame.index[0].value), int(frame.index[-1].value),
            AccessWitness("development-1", market_role, int(frame.index[0].value), int(frame.index[-1].value)+1, cutoff-1)),)
    channel = Channel("ECONOMIC_UTILITY_V1", "mode5.utility.net_v1", "decimal_return")
    reference = FrozenReference("frozen-1", tuple(w.environment_id for w in windows),
        (0.,)*len(windows), (1.,)*len(windows), channel.identity, "registered-before-search")
    versions = {"full_dro_cvar": ("environment_floor_mean_v1", {"mean": .5}),
                "full_sam_basin": ("local_downside_v1", {"gamma": 1.}),
                "full_pareto_chebyshev": ("pareto_chebyshev_v1", {"rho": .01})}
    version, coefs = versions[selector]
    local = selector == "full_sam_basin"
    preference = None
    if selector == "full_pareto_chebyshev":
        from quantbt.mode5.selection.pareto import ParetoPreference
        preference = asdict(ParetoPreference("registered-pareto-v1", reference.environment_ids,
            channel.identity, (1.,)*len(windows), (-1.,)*len(windows), (1,)*len(windows),
            (1.,)*len(windows), "allow_and_report_v1"))
    binding = calibration_binding(windows=windows, reference=reference, sampler=sampler,
        metrics=dict(bar_interval_ns=int(frame.index[1].value-frame.index[0].value), currency="USDT", annual_periods=365.,
            dd_weight=1., tail_weight=1., tail_confidence=.95, min_daily_returns=min_daily,
            min_closed_records=0, max_drawdown=1., min_utility=min_utility),
        selection=dict(requested_selector=requested_selector or selector, minimum_improvement=0.,
            incumbent_params=incumbent, local_reference_id="local-scale-v1" if local else None,
            local_reference_scale=1. if local else None, pareto_preference=preference),
        batch_size=batch_size, warm_start=warm_start, local_offsets=[dict(probe_id="left", delta={"period": -1}),
            dict(probe_id="right", delta={"period": 1})] if local else [])
    context = calibration_context(data=frame, strategy=strategy, execution_config=execution_config,
                                  param_ranges=ranges, binding=binding)
    kwargs["context"] = context
    kwargs["assessments"] = [dict(recipe_id=s+":"+v, status="CONSIDER_FINITE_PANEL", selected_decisions=1,
        reasons=["registered synthetic mechanics/math fixture, not economic evidence"],
        refs=[catalog.ref("registered", "/cells")]) for s, (v, _) in versions.items()]
    dossier = Dossier.create(**kwargs)
    recipe = spec(dossier)
    recipe["search_budget"] = trials
    from quantbt.optimization.parameter_space import NormalizedSearchSpace
    recipe["domain"].update(ranges=NormalizedSearchSpace(ranges).portable_ranges())
    recipe["sampler"].update(name=sampler_name, schedule="fixed_batch" if batch_size > 1 else "sequential_exact")
    recipe["objective"].update(version=version, coefficients=coefs, channel=asdict(channel))
    recipe["selector"]["id"] = selector
    recipe["reuse"]["selection_policy"] = asdict(access)
    recipe["retention"]["runtime_binding_identity"] = binding.identity
    recipe["probes"]["budget"] = len(binding.data["local_offsets"])*trials
    recipe["probes"]["design"] = "schema_numeric_offsets_v1" if local else "no_local_probes_v1"
    plan = CalibrationPlan.search(dossier, recipe, "owner-approved public synthetic integration, no edge claim")
    log = GovernanceLog(tmp_path / "journal")
    log.seal_dossier(dossier, catalog)
    log.seal_plan(dossier, plan, catalog, researcher="synthetic test author", reason=plan.record.data["reason"])
    calibration = Mode5Calibration(dossier, plan, catalog, log, binding)
    options = {**base_options, "sampler_config": sampler, "mode5_calibration": calibration,
               "sampler_warm_start": warm_start}
    endpoint = QuantBTEndpoint.walk_forward(**args, optimization_config=options)
    return endpoint, frame, ranges, calibration
