"""Self-contained synthetic handoff mechanics, with no economic claim.

The default CLI only builds fixture evidence and prints an unchosen worksheet.
Only --run calls backtest: four attempts, one selected replay and one final
account, with no diagnostic financial executions or local probes.
"""

import argparse
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from quantbt import QuantBTEndpoint
from quantbt.diagnostics import (
    ArchiveReview, CalibrationRecipe, CalibrationWorksheet, Mode5RunPack,
)
from quantbt.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.diagnostics.archive_contracts import (
    ArchiveEvidence, ArchiveIdentity, DependencyNode, IntendedReuse,
)
from quantbt.diagnostics.identity import AnalysisKey, ExecutionKey, digest
from quantbt.endpoint import _walkforward_scoring_config
from quantbt.mode5 import CalibrationWindow, calibration_context
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.continuous_binding import continuous_calibration_binding
from quantbt.mode5.continuous_producer import producer_records
from quantbt.mode5.dossier.dossier import AXES, Dossier, radar_point
from quantbt.mode5.dossier.evidence import KINDS, EvidenceCatalog, Matrix, Source
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.geometry.schema import EffectiveGeometry
from quantbt.mode5.runtime import Mode5NoSelectionError
from quantbt.mode5.selection.contracts import Channel, Formula
from quantbt.mode5.statistics.tails import FrozenReference
from quantbt.optimization import SamplerConfig
from quantbt.optimization.parameter_space import NormalizedSearchSpace


SEED = 731
STEP_NS = 3_600_000_000_000
OPTION_ID = "synthetic-annual-floor-mean"


def synthetic_strategy(data, params, train_index, test_index, fold):
    signal = pd.Series(
        np.sign(np.sin(np.arange(len(data)) / params["period"])), index=data.index,
    )
    return signal.reindex(test_index)


def _missing_archive(context, source, execution, witness, account_kwargs):
    """A metadata-only absence control, not a retained financial observation."""
    execution_key = ExecutionKey(
        alpha_code=context.data["alpha"],
        effective_params=digest(dict(status="SYNTHETIC_CONTROL", coordinate=None)),
        market_snapshot=context.data["data"],
        initial_state=digest(execution.data["initial_state"]),
        clock=digest(execution.data["clock"]),
        instrument=digest(account_kwargs["symbols"]),
        costs=context.data["economics"],
        funding=digest(dict(use_funding=account_kwargs["use_funding"])),
        account="CONTINUOUS_PATH_ATTRIBUTION",
        terminal=digest(execution.data["terminal_policy"]),
        warmup="synthetic-no-preload", scenario_seed=SEED,
        source_backend=source.identity,
    )
    identity = ArchiveIdentity(
        execution=execution_key,
        analysis=AnalysisKey(execution_key.identity, context.data["roles"],
            context.data["metrics"], context.data["references"]),
        parameter_schema=context.data["schema"], timeframe="1h",
        route=execution.data["route"], start_ns=witness.start_ns,
        end_ns=witness.end_ns, metric_unit="decimal_return",
    )
    # All DAG clocks and nodes are synthetic controls, not historical receipts.
    nodes = tuple(DependencyNode(
        node_id=kind, kind=kind, witness=witness,
        source_cutoff_ns=witness.end_ns,
        proposal_available_ns=witness.ready_ns,
        revision_available_ns=witness.ready_ns,
        publication_ns=witness.ready_ns, actual_execution_ns=witness.ready_ns,
        dependencies=dependencies, purposes=("diagnostic", "selection"),
        backdating="NOT_BACKDATABLE",
    ) for kind, dependencies in (
        ("source", ()), ("candidate", ("source",)),
        ("outcome", ("candidate",)), ("revision", ("outcome",)),
    ))
    reason = "Synthetic absence control: no original account execution or measurements were retained"
    return ArchiveEvidence(
        evidence_id="synthetic-missing-account", identity=identity,
        candidate_id="synthetic-unmeasured-candidate",
        execution_id="synthetic-not-executed", state_id="synthetic-no-account-state",
        content_digest=digest(dict(status="MISSING", reason=reason)),
        roots=("revision",), nodes=nodes, status="MISSING", reason=reason,
        retained_inputs=(), readbacks=(),
    )


def build_inputs(workdir, *, optional_archive=False, trials=4):
    """Build original inputs and an unchosen worksheet; never execute finance.

    workdir must be new. Written numbers are labeled SYNTHETIC_CONTROL, not
    measured utility, returns, diagnostic evidence of edge or sampler inputs.
    """
    if type(trials) is not int or not 1 <= trials <= 4:
        raise ValueError("synthetic handoff permits one to four formal attempts")
    if type(optional_archive) is not bool:
        raise TypeError("optional_archive must be an explicit boolean")
    workdir = Path(workdir).absolute()
    workdir.mkdir(parents=True, exist_ok=False, mode=0o700)

    index = pd.date_range("2020-12-16", periods=32 * 24, freq="h", tz="UTC")
    x = np.arange(len(index))
    close = 100 + .012 * x + 3 * np.sin(x / 17) + .4 * np.sin(x / 2.3)
    data = pd.DataFrame(dict(open=close - .05, high=close + 1, low=close - 1,
        close=close, volume=np.full(len(index), 100.)), index=index)
    strategy = synthetic_strategy
    param_ranges = {"period": (6, 24, 1)}
    account_kwargs = dict(initial_capital=20_000., fee=.0005, slippage=.0001,
        alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["DEMO"])
    stop_ns = int(index[-1].value) + STEP_NS
    witness = AccessWitness("synthetic-handoff-development", "synthetic",
        int(index[0].value), stop_ns, stop_ns + STEP_NS)
    access = AccessPolicy("synthetic-handoff-selection", ("synthetic",),
        (witness.manifest_id,), witness.ready_ns + STEP_NS, "selection")
    windows = tuple(CalibrationWindow(str(year),
        int(index[index.year == year][0].value),
        int(index[index.year == year][-1].value), witness)
        for year in sorted(set(index.year)))
    channel = Channel("ECONOMIC_UTILITY_V1", "mode5.utility.net_v1", "decimal_return")
    reference = FrozenReference("synthetic-zero-reference-before-search",
        tuple(window.environment_id for window in windows), (0., 0.), (1., 1.),
        channel.identity, "prospective_synthetic_control_v1")
    formula = Formula("environment_floor_mean_v1", channel, (("mean", .5),))
    sampler = SamplerConfig("tpe_legacy", constraint_mode="post_filter",
        kwargs={"n_startup_trials": 2})

    # Resolve the original financial configuration without invoking the strategy.
    original = QuantBTEndpoint.walk_forward(strategy_class=strategy,
        target_mode="pct_equity", optimization_mode="mode_5_full_robust",
        optimization_schedule="global", split_frequency="single",
        optuna_trials=trials, random_seed=SEED,
        optimization_config=dict(scoring_backend="endpoint", is_subperiods=1,
            fold_account_policy="carry_position", native_prepared_wfo="off",
            use_prepared_scoring_cache=True), **account_kwargs)
    execution_config = _walkforward_scoring_config(original.config, "pct_equity")
    source, execution = producer_records(execution_config, strategy)
    binding = continuous_calibration_binding(
        geometry=EffectiveGeometry.from_ranges(param_ranges), source=source,
        execution=execution, witness=witness, windows=windows, reference=reference,
        sampler=sampler, quality_floor_comparison="greater_or_equal_v1",
        metrics=dict(bar_interval_ns=STEP_NS, currency="USDT", annual_periods=365.,
            dd_weight=1., tail_weight=1., tail_confidence=.95, min_daily_returns=2,
            min_closed_records=0, max_drawdown=1., min_utility=-10.),
        selection=dict(requested_selector="full_dro_cvar", minimum_improvement=0.,
            incumbent_params=None, local_reference_id=None, local_reference_scale=None,
            pareto_preference=None), batch_size=1, warm_start=(), local_offsets=(),
    )
    context = calibration_context(data=data, strategy=strategy,
        execution_config=execution_config, param_ranges=param_ranges, binding=binding)
    archive_evidence = (_missing_archive(context, source, execution, witness, account_kwargs)
        if optional_archive else None)

    missing_reason = "No diagnostic financial executions or diagnostic batteries in build_inputs"
    missing = dict(value=None, status="NOT_RUN", reason=missing_reason)
    controls = [dict(status="SYNTHETIC_CONTROL", metric="synthetic.control.scalar_v1",
        unit="dimensionless_not_return", value=value,
        reason="Literal contract fixture; not a measured financial score") for value in (.2, -.3)]
    inventory = {kind: [kind + "/declared"] for kind in KINDS}
    definitions = {axis: dict(metric="unmeasured_" + axis, unit="unavailable",
        direction=1, reference_id=reference.reference_id, lower=None, upper=None)
        for axis in AXES}
    payload = dict(status="SYNTHETIC_CONTROL", context=context.data,
        synthetic_controls=controls, inventory=inventory, definitions=definitions,
        values={axis: None for axis in AXES},
        partial_year_support=dict(policy="allow_observed_complete_utc_days_only",
            days_by_year={str(year): int((index.year == year).sum()) // 24
                for year in sorted(set(index.year))},
            min_daily_returns=2, min_closed_records=0, independent_years=False),
        matrices=dict(
            parameter_representation=dict(status="DECLARED_DOMAIN",
                ranges=NormalizedSearchSpace(param_ranges).portable_ranges()),
            candidate_environment=dict(status="SYNTHETIC_CONTROL", controls=controls),
            center_neighbor_environment=missing,
            environment_environment=dict(status="DESCRIPTIVE_CALENDAR",
                windows=[asdict(window) for window in windows], independent_transfer=False),
            recipe_split_seed=missing, execution_stress=missing),
        archive=asdict(archive_evidence) if archive_evidence else None,
        archive_limit="Absence-control DAG and clocks are synthetic, not execution receipts",
    )
    source_path = workdir / "synthetic-evidence.json"
    write_json(source_path, payload)
    pin = file_identity(source_path)
    diagnostic_access = AccessPolicy("synthetic-handoff-diagnostic", access.roles,
        access.manifests, access.cutoff_ns, "diagnostic")
    catalog = EvidenceCatalog((Source("synthetic-handoff", str(source_path.resolve()),
        pin["sha256"], pin["bytes"], witness),), diagnostic_access)
    rosters = tuple(Record.of(dict(kind=kind, entries=[dict(row_id=inventory[kind][0],
        ref=catalog.ref("synthetic-handoff", "/matrices/" + kind))])) for kind in KINDS)
    matrices = tuple(Matrix.assemble(kind, roster, catalog)
        for kind, roster in zip(KINDS, rosters, strict=True))
    axes = {axis: dict(status="NOT_RUN",
        refs=[catalog.ref("synthetic-handoff", "/values/" + axis)]) for axis in AXES}
    radar = {axis: [radar_point(**definitions[axis], value=None,
        support=dict(declared_days=32, diagnostic_accounts=0), uncertainty=None,
        reason=missing_reason, ref=catalog.ref("synthetic-handoff", "/values/" + axis),
        definition_ref=catalog.ref("synthetic-handoff", "/definitions/" + axis))]
        for axis in AXES}
    dossier = Dossier.create(context=context, matrices=matrices, rosters=rosters,
        inventory=Record.of(inventory),
        inventory_ref=catalog.ref("synthetic-handoff", "/inventory"), catalog=catalog,
        axes=axes, radar=radar, batteries=dict(unmeasured=missing),
        assessments=[dict(recipe_id="full_dro_cvar:environment_floor_mean_v1",
            status="CONSIDER_FINITE_PANEL", selected_decisions=0,
            reasons=["SYNTHETIC_CONTROL contract permission only; no measured diagnostic eligibility or economic ranking"],
            refs=[catalog.ref("synthetic-handoff", "/synthetic_controls")])],
        limitations=["Synthetic controls are not financial observations or economic evidence",
            "All diagnostic axes unmeasured; recipe is an explicit mechanics preference",
            "Two partial calendar years are dependent views, not independent OOS",
            "No stress, transfer, sampler comparison, quarterly or regime qualification"],
        compute_bill=dict(diagnostic_financial_executions=0, local_probes=0))

    archive_access = access if optional_archive else None
    archive = None
    if archive_evidence is not None:
        archive = ArchiveReview.assess(((archive_evidence,
            IntendedReuse(archive_evidence.identity, "MODE5_CALIBRATION"),
            catalog.ref("synthetic-handoff", "/archive")),),
            context_id=digest(dossier.record.data["context"]),
            access=archive_access, catalog=catalog)
    recipe = CalibrationRecipe.continuous(dossier, option_id=OPTION_ID,
        binding=binding, param_ranges=param_ranges, formula=formula,
        selector_id="full_dro_cvar", search_budget=trials, seed=SEED, access=access,
        validation=dict(no_auto_deploy=True, roles=["independent_validation"],
            contamination_status="No independent validation; separate registration required"),
        failure_policy="raise",
        reason="Explicit synthetic floor plus half mean preference; not diagnostic or economic superiority")
    worksheet = CalibrationWorksheet.create(dossier=dossier, catalog=catalog,
        options=(recipe,
            CalibrationRecipe.research_only(option_id="quarterly-research-only",
                reason="Quarterly account views do not authorize quarterly public ranking",
                missing_contracts=["No quarterly continuous public selector-window binding"]),
            CalibrationRecipe.research_only(option_id="regime-research-only",
                reason="Descriptive regime labels are not independent ranking environments",
                missing_contracts=["No registered regime public ranking binding"])),
        archive=archive, archive_access=archive_access)
    return dict(data=data, strategy=strategy, param_ranges=param_ranges,
        dossier=dossier, catalog=catalog, worksheet=worksheet, access=access,
        account_kwargs=account_kwargs, archive=archive, archive_access=archive_access,
        workdir=workdir)


def run_demo(workdir, *, optional_archive=False):
    """Explicitly execute one bounded handoff using the original verified inputs."""
    inputs = build_inputs(workdir, optional_archive=optional_archive, trials=4)
    worksheet = inputs["worksheet"].choose(OPTION_ID,
        researcher="synthetic handoff author",
        reason="Explicit mechanics-only choice; fixture and archive do not establish edge")
    pack = Mode5RunPack.compile(worksheet, dossier=inputs["dossier"],
        catalog=inputs["catalog"], access=inputs["access"],
        archive_access=inputs["archive_access"])
    expected_identity = pack.identity
    pack_path = pack.export(inputs["workdir"] / "run-pack", private=True)
    pack = Mode5RunPack.read(pack_path, expected_identity=expected_identity)
    endpoint = pack.prepare(dossier=inputs["dossier"], catalog=inputs["catalog"],
        journal=GovernanceLog(inputs["workdir"] / "journal"), access=inputs["access"],
        data=inputs["data"], strategy=inputs["strategy"],
        param_ranges=inputs["param_ranges"], account_kwargs=inputs["account_kwargs"],
        target_mode="pct_equity", archive_access=inputs["archive_access"])
    try:
        result = endpoint.backtest(data=inputs["data"], param_ranges=inputs["param_ranges"])
    except Mode5NoSelectionError as error:
        result = error
    report = pack.reconcile(result)
    return dict(endpoint=endpoint, result=result, report=report, pack=pack, inputs=inputs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True, type=Path,
        help="new disposable directory for original fixture evidence and any run artifacts")
    parser.add_argument("--optional-archive", action="store_true",
        help="include a source-bound synthetic MISSING archive control")
    parser.add_argument("--private", action="store_true",
        help="display private synthetic configuration instead of the redacted view")
    parser.add_argument("--run", action="store_true", help="explicitly run the bounded backtest")
    args = parser.parse_args(argv)
    if args.run:
        outcome = run_demo(args.workdir, optional_archive=args.optional_archive)
        print(outcome["report"].to_markdown(private=args.private))
    else:
        inputs = build_inputs(args.workdir, optional_archive=args.optional_archive)
        print(inputs["worksheet"].to_markdown(private=args.private))


if __name__ == "__main__":
    main()
