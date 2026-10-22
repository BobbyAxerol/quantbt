"""Small, self-contained mechanics demo, not an economic study or recipe router.

Run with --workdir pointing to a new disposable directory. The example retains
its measured diagnostic inputs and seals before search. Missing batteries are
explicit nulls; neither eight diagnostic points nor six trials certify edge.
"""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import argparse

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.endpoint import _walkforward_scoring_config
from quantbt.mode5 import (
    CalibrationWindow, DecisionReport, Mode5Calibration,
    calibration_binding, calibration_context,
)
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.dossier.dossier import AXES, Dossier, radar_point
from quantbt.mode5.dossier.evidence import KINDS, EvidenceCatalog, Matrix, Source
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.plans import FIELDS, CalibrationPlan
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.evaluation import Mode5MetricPolicy
from quantbt.mode5.runtime import Mode5NoSelectionError
from quantbt.mode5.selection.contracts import Channel
from quantbt.mode5.statistics.tails import FrozenReference
from quantbt.optimization import SamplerConfig
from quantbt.optimization.parameter_space import NormalizedSearchSpace


ACCOUNT = dict(initial_capital=20_000., leverage=1., alloc_per_trade=.5,
               fee_rate=.0005, slippage=.0001, use_funding=False, symbols=["DEMO"])
RANGES = {"period": (6, 24, 1)}
DIAGNOSTIC_PERIODS = (6, 8, 10, 12, 15, 18, 21, 24)


def synthetic_inputs():
    index = pd.date_range("2023-01-01", periods=32*24, freq="h", tz="UTC")
    x = np.arange(len(index))
    close = 100 + .012*x + 3*np.sin(x/17) + .4*np.sin(x/2.3)
    return pd.DataFrame(dict(open=close-.05, high=close+1, low=close-1,
                             close=close, volume=100.), index=index)


def strategy(data, params, train_index, test_index, fold):
    signal = pd.Series(np.sign(np.sin(np.arange(len(data))/params["period"])), index=data.index)
    return signal.reindex(test_index)


def run_demo(workdir):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=False)
    data = synthetic_inputs()
    step = 3_600_000_000_000
    cutoff = int(data.index[-1].value) + 2*step
    witness = AccessWitness("synthetic-development", "synthetic",
        int(data.index[0].value), int(data.index[-1].value)+step, cutoff-1)
    access = AccessPolicy("demo-selection", ("synthetic",), (witness.manifest_id,), cutoff, "selection")
    window = CalibrationWindow("development", int(data.index[0].value), int(data.index[-1].value), witness)
    channel = Channel("ECONOMIC_UTILITY_V1", "mode5.utility.net_v1", "decimal_return")
    reference = FrozenReference("demo-zero-before-search", (window.environment_id,), (0.,),
        (1.,), channel.identity, "prospective_demo_reference_v1")
    sampler = SamplerConfig("tpe_legacy", kwargs={"n_startup_trials": 2})
    binding = calibration_binding(windows=(window,), reference=reference, sampler=sampler,
        metrics=dict(bar_interval_ns=step, currency="USDT", annual_periods=365.,
            dd_weight=1., tail_weight=1., tail_confidence=.95, min_daily_returns=2,
            min_closed_records=0, max_drawdown=1., min_utility=-10.),
        selection=dict(requested_selector="full_dro_cvar", minimum_improvement=0.,
                       incumbent_params=None, local_reference_id=None, local_reference_scale=None,
                       pareto_preference=None), batch_size=1, warm_start=(), local_offsets=[])
    options = dict(scoring_backend="endpoint", native_prepared_wfo="off",
                   is_subperiods=1, use_prepared_scoring_cache=True)
    base = QuantBTEndpoint.walk_forward(strategy_class=strategy, target_mode="pct_equity",
        optimization_mode="mode_5_full_robust", split_frequency="single", optuna_trials=6,
        random_seed=731, optimization_config=options, **ACCOUNT)
    execution = _walkforward_scoring_config(base.config, "pct_equity")
    context = calibration_context(data=data, strategy=strategy, execution_config=execution,
                                   param_ranges=RANGES, binding=binding)
    policy = Mode5MetricPolicy(SimpleNamespace(binding=binding))
    rows = []
    # Execute the declared diagnostic panel before constructing its dossier.
    for period in DIAGNOSTIC_PERIODS:
        params = {"period": period}
        original = QuantBTEndpoint.pct_equity(**ACCOUNT)
        result = original.backtest(data=data, signal=strategy(data, params, data.index, data.index, None))
        rows.append(dict(params=params, observation=policy.observe(result, data.index)))
    missing = {"value": None, "status": "NOT_RUN", "reason": "outside this small mechanics demo"}
    inventory = {kind: [kind+"/declared"] for kind in KINDS}
    definitions = {axis: dict(metric="economic_utility" if axis == "mechanics_economics" else "unmeasured_axis",
        unit="decimal_return" if axis == "mechanics_economics" else "unavailable",
        direction=1, reference_id=reference.reference_id, lower=None, upper=None) for axis in AXES}
    values = {axis: rows[0]["observation"]["utility"]["value"] if axis == "mechanics_economics" else None for axis in AXES}
    payload = dict(panel=rows, definitions=definitions, values=values, inventory=inventory,
        matrices=dict(parameter_representation={"ranges": NormalizedSearchSpace(RANGES).portable_ranges()},
            candidate_environment=rows, center_neighbor_environment=missing,
            environment_environment={"environment": window.environment_id, "independent_transfer": False},
            recipe_split_seed=missing, execution_stress=missing))
    source_path = workdir / "diagnostic-inputs.json"
    write_json(source_path, payload)
    pin = file_identity(source_path)
    diagnostic_access = AccessPolicy("demo-diagnostic", access.roles, access.manifests, cutoff, "diagnostic")
    catalog = EvidenceCatalog((Source("demo", str(source_path.resolve()), pin["sha256"], pin["bytes"], witness),), diagnostic_access)
    rosters = tuple(Record.of(dict(kind=kind, entries=[dict(row_id=inventory[kind][0],
        ref=catalog.ref("demo", "/matrices/"+kind))])) for kind in KINDS)
    matrices = tuple(Matrix.assemble(kind, roster, catalog) for kind, roster in zip(KINDS, rosters, strict=True))
    axes = {axis: dict(status="DESCRIPTIVE_ONLY" if values[axis] is not None else "NOT_RUN",
        refs=[catalog.ref("demo", "/values/"+axis)]) for axis in AXES}
    radar = {axis: [radar_point(**definitions[axis], value=values[axis], support={"days": 32, "panel": 8},
        uncertainty=None, reason=None if values[axis] is not None else missing["reason"],
        ref=catalog.ref("demo", "/values/"+axis),
        definition_ref=catalog.ref("demo", "/definitions/"+axis))] for axis in AXES}
    eligible = sum(all(row["observation"][key] for key in ("support_pass", "risk_pass", "quality_pass")) for row in rows)
    dossier = Dossier.create(context=context, matrices=matrices, rosters=rosters,
        inventory=Record.of(inventory), inventory_ref=catalog.ref("demo", "/inventory"), catalog=catalog,
        axes=axes, radar=radar, batteries={"unrun_batteries": missing},
        assessments=[dict(recipe_id="full_dro_cvar:environment_floor_mean_v1",
            status="CONSIDER_FINITE_PANEL" if eligible else "NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL",
            selected_decisions=0, reasons=["Measured finite panel support; explicit demo preference, not selector superiority"],
            refs=[catalog.ref("demo", "/panel")])],
        limitations=["Synthetic 32-day mechanics demo; one environment makes floor/mean redundant",
                     "No sampler comparison, sensitivity, stress, transfer or economic inference"],
        compute_bill={"original_diagnostic_accounts": policy.evaluations})
    spec = {key: {"contract_id": "synthetic-demo-"+key} for key in FIELDS}
    spec.update(search_budget=6,
        sampler=dict(name="tpe_legacy", seeds=[731], schedule="sequential_exact", fallback="raise"),
        objective=dict(version="environment_floor_mean_v1", coefficients={"mean": .5},
            reference_id=reference.reference_id, channel=asdict(channel)),
        selector=dict(id="full_dro_cvar", tie_break="candidate_id_lexicographic_v1"),
        domain=dict(schema_id=context.data["schema"], ranges=NormalizedSearchSpace(RANGES).portable_ranges()))
    spec["probes"].update(design="no_local_probes_v1", budget=0)
    spec["validation"].update(no_auto_deploy=True, roles=["independent_validation"],
        contamination_status="No validation conducted; separate registration required")
    spec["reuse"]["selection_policy"] = asdict(access)
    spec["retention"]["runtime_binding_identity"] = binding.identity
    plan = CalibrationPlan.search(dossier, spec, "Explicit synthetic floor/mean preference for demonstrating the public workflow")
    log = GovernanceLog(workdir / "journal")
    log.seal_dossier(dossier, catalog)
    log.seal_plan(dossier, plan, catalog, researcher="synthetic demo", reason=plan.record.data["reason"])
    calibration = Mode5Calibration(dossier, plan, catalog, log, binding)
    endpoint = QuantBTEndpoint.walk_forward(strategy_class=strategy, target_mode="pct_equity",
        optimization_mode="mode_5_full_robust", split_frequency="single", optuna_trials=6,
        random_seed=731, optimization_config={**options, "sampler_config": sampler,
            "mode5_calibration": calibration}, **ACCOUNT)
    try:
        result = endpoint.backtest(data=data, param_ranges=RANGES)
    except Mode5NoSelectionError as error:
        return DecisionReport.read(error.mode5_metadata)
    wf = result.metadata["walk_forward"]
    return DecisionReport.read(wf["mode5_diagnostics_first"], selected_params=wf["best_trial"]["params"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True, help="new directory retaining demo evidence/journal")
    parser.add_argument("--private", action="store_true", help="show the synthetic selected dictionary")
    args = parser.parse_args(argv)
    print(run_demo(args.workdir).to_markdown(private=args.private))


if __name__ == "__main__":
    main()
