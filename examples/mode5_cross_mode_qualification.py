"""Opt-in synthetic Mode4 -> Mode5 mechanics; no economic hypothesis or promotion.

Dry run: python -m examples.mode5_cross_mode_qualification --workdir /tmp/xm-dry
Execute: add --run --donor-fold 0. Repeat --donor-fold to choose an ordered roster;
duplicate effective points fail, with no automatic replacement or ranking.

Two weekly Mode4 studies x two attempts, then matched four-attempt baseline and
challenger packs: 12 proposals, at most 23 original financial invocations,
including selected replays/final accounts. There are no retries, probes or fits.
The default only builds the original synthetic controls and a zero-work protocol.
Run in the parent's admitted single-worker environment; --run writes private
local configuration/evidence. Failed work is retained, never rerun or relabeled.
"""

import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import time

import pandas as pd

from examples.mode5_diagnostic_handoff import SEED, STEP_NS, build_inputs
from quantbt import QuantBTEndpoint
from quantbt.diagnostics import ArchiveReview, CalibrationRecipe, CalibrationWorksheet, Mode5RunPack
from quantbt.diagnostics.access import AccessWitness
from quantbt.diagnostics.archive_contracts import ArchiveEvidence, ArchiveIdentity, DependencyNode, IntendedReuse
from quantbt.diagnostics.calibration.donor_binding import continuous_donor_target, verify_recipe_donors
from quantbt.diagnostics.calibration.donors import ArchiveDonorPlan
from quantbt.diagnostics.identity import AnalysisKey, ExecutionKey, digest
from quantbt.diagnostics.winner import WinnerBaseline, WinnerQualificationRequest
from quantbt.endpoint import _WalkForwardEndpointScorer, _walkforward_scoring_config
from quantbt.mode5 import calibration_context
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.continuous_binding import restore_geometry
from quantbt.mode5.continuous_producer import producer_records
from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.dossier.dossier import Dossier
from quantbt.mode5.dossier.evidence import KINDS, EvidenceCatalog, Matrix, Source
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.selection.contracts import Channel, Formula
from quantbt.optimization import SamplerConfig
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from quantbt.walkforward import WalkForwardEngine


MODE4_FOLDS = 2
MODE4_TRIALS = 2
MODE5_TRIALS = 4
PROPOSALS = MODE4_FOLDS * MODE4_TRIALS + 2 * MODE5_TRIALS
# Even without exact full-IS/shard reuse: 2*(2*2+1)+1, then 2*(4+1+1).
FINANCE_CEILING = 23
ARCHIVE_SOURCE = "completed-synthetic-mode4"


def _donor_folds(values):
    if (type(values) is not tuple or not values or len(set(values)) != len(values)
            or any(type(i) is not int or i not in range(MODE4_FOLDS) for i in values)):
        raise ValueError("explicit ordered distinct donor fold tuple from (0, 1) required")
    return values


def build_demo_inputs(workdir, *, donor_folds=()):
    """Cold preparation only; do not manufacture an archive before execution."""
    if donor_folds:
        _donor_folds(donor_folds)
    inputs = build_inputs(workdir, trials=MODE5_TRIALS)
    index = inputs["data"].index
    protocol = dict(schema="quantbt.synthetic_cross_mode_protocol.v1", status="NOT_RUN",
        donor_folds=list(donor_folds), automatic_routing=False, retries=0,
        market=dict(start_ns=int(index[0].value), stop_ns=int(index[-1].value) + STEP_NS,
            bar_interval_ns=STEP_NS, interval="half_open", timezone=str(index.tz), bars=len(index),
            identity=inputs["dossier"].record.data["context"]["data"]),
        account_kwargs=inputs["account_kwargs"],
        param_ranges=NormalizedSearchSpace(inputs["param_ranges"]).portable_ranges(), seed=SEED,
        donor_rule=dict(ordered_fold_ids=list(donor_folds), registered_smoke_fold_ids=[0],
            point="Original selected COMPLETE trial of each explicitly named fold",
            roster_frozen_before_finance=True, automatic_ranking=False, score_reuse=False,
            duplicate_points="Reject without replacement; never choose another fold or trial"),
        proposal_slots=PROPOSALS, financial_invocation_ceiling=FINANCE_CEILING,
        observed_proposals=0, observed_financial_invocations=0,
        mode4=dict(folds=MODE4_FOLDS, trials_per_fold=MODE4_TRIALS, is_subperiods=1),
        mode5=dict(baseline_trials=MODE5_TRIALS, challenger_trials=MODE5_TRIALS, local_probes=0),
        claim="Synthetic mechanics only; one selected pair cannot establish economic benefit")
    write_json(inputs["workdir"] / "protocol.json", protocol)
    return {**inputs, "protocol": protocol}


def _base_recipe(inputs):
    return inputs["worksheet"].record.data["cards"][0]["recipe"]


def mode4_endpoint(inputs):
    """Existing endpoint only; the original tape gives exactly two weekly folds."""
    binding = _base_recipe(inputs)["binding"]
    endpoint = QuantBTEndpoint.walk_forward(strategy_class=inputs["strategy"],
        target_mode="pct_equity", split_mode="2021-01-03", split_frequency="weekly",
        window_mode="expanding", optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", optuna_trials=MODE4_TRIALS, random_seed=SEED,
        optimization_config=dict(scoring_backend="endpoint", is_subperiods=1,
            min_train_bars=24, min_test_bars=24, fold_account_policy="carry_position",
            native_prepared_wfo="off", use_prepared_scoring_cache=True,
            wfo_execution_reuse="off", sampler_config=SamplerConfig(**binding["sampler"]),
            top_is_fraction=1., flat_min_samples=1, flat_eps=1., flat_selector="medoid"),
        **inputs["account_kwargs"])
    scorer = _WalkForwardEndpointScorer(endpoint.config, "pct_equity",
        wf_config=endpoint.config.walkforward_config, market_data=inputs["data"])
    try:
        folds = WalkForwardEngine(strategy=inputs["strategy"],
            config=endpoint.config.walkforward_config, scorer=scorer).build_folds(inputs["data"].index)
    finally:
        scorer.release_prepared_state()
    if len(folds) != MODE4_FOLDS:
        raise ValueError("declared Mode4 fold budget differs from the actual calendar")
    return endpoint


def selected_fold_rows(metadata, space, strategy_identity):
    """Read original selections, not a new ranking; useful for cold validation."""
    if (metadata.get("optimization_mode") != "mode_4_is_only_robust"
            or metadata.get("optimization_schedule") != "per_fold_causal"
            or metadata.get("n_folds") != MODE4_FOLDS):
        raise ValueError("actual two-fold causal Mode4 result required")
    selections = metadata["fold_selection_table"].to_dict(orient="records")
    studies = {s["study_id"]: s for s in metadata["sampler_studies"]}
    if (len(selections) != MODE4_FOLDS or len(studies) != MODE4_FOLDS
            or len(metadata["sampler_studies"]) != MODE4_FOLDS):
        raise ValueError("complete original fold selections and sampler studies required")
    rows = []
    for fold in selections:
        study = studies[fold["study_id"]]
        matches = [r for r in study["rows"] if r["trial_id"] == fold["selected_trial_id"]]
        if (study["attempts"] != MODE4_TRIALS or len(study["rows"]) != MODE4_TRIALS
                or len(matches) != 1 or matches[0]["state"] != "COMPLETE"):
            raise ValueError("selected Mode4 donor must be an original COMPLETE sampler trial")
        trial = matches[0]
        params = space.effective(fold["selected_params"])
        if (Record.of(params) != Record.of(fold["selected_params"])
                or Record.of(params) != Record.of(trial["effective_params"])
                or trial["candidate_id"] != space.candidate_key(params, strategy_identity=strategy_identity)
                or not math.isfinite(fold["selected_is_objective"])):
            raise ValueError("original selected dictionary/candidate/measurement mismatch")
        if (study["space_identity"] != space.identity
                or metadata.get("strategy_fingerprint") != strategy_identity):
            raise ValueError("original Mode4 sampler source/schema mismatch")
        clocks = {key: int(pd.Timestamp(fold[key]).value)
                  for key in ("train_start", "train_end", "test_start", "test_end")}
        rows.append(dict(fold_id=int(fold["fold_id"]), study_id=int(fold["study_id"]),
            selected_trial_id=int(fold["selected_trial_id"]), sampler_seed=int(study["seed"]),
            params=params, candidate_id=trial["candidate_id"], selected_trial=trial,
            selected_is_objective=float(fold["selected_is_objective"]), **clocks))
    if [r["fold_id"] for r in rows] != list(range(MODE4_FOLDS)):
        raise ValueError("exact original chronological fold roster required")
    return tuple(rows)


def retain_mode4_archive(inputs, endpoint, result, *, started_ns):
    """Retain real completed metadata and its actual producer/config witness."""
    if result is not endpoint.result:
        raise ValueError("original completed endpoint result required; no substitute receipt")
    metadata = result.metadata["walk_forward"]
    binding = Record.of(_base_recipe(inputs)["binding"])
    config = _walkforward_scoring_config(endpoint.config, "pct_equity")
    source, execution = producer_records(config, inputs["strategy"])
    context = calibration_context(data=inputs["data"], strategy=inputs["strategy"],
        execution_config=config, param_ranges=inputs["param_ranges"], binding=binding)
    if (context != Record.of(inputs["dossier"].record.data["context"])
            or source.data != binding.data["continuous"]["source"]
            or execution.data != binding.data["continuous"]["execution"]
            or metadata["random_seed"] != SEED):
        raise ValueError("Mode4 actual source/market/clock/composite economics differs from destination")
    rows = selected_fold_rows(metadata, NormalizedSearchSpace(inputs["param_ranges"]), source.data["alpha"])
    completed_ns = time.time_ns()
    original = AccessWitness(**binding.data["continuous"]["witness"])
    witness = AccessWitness(ARCHIVE_SOURCE, "synthetic", original.start_ns, original.end_ns, completed_ns)
    target = continuous_donor_target(inputs["dossier"], binding, seed=SEED)
    evidence = []
    for row in rows:
        key = ExecutionKey(source.data["alpha"], digest(row["params"]), context.data["data"],
            Record.of(execution.data["initial_state"]).identity, Record.of(execution.data["clock"]).identity,
            context.data["economics"], context.data["economics"], context.data["economics"],
            "original_mode4_fresh_IS_score_window", Record.of(execution.data["terminal_policy"]).identity,
            target.warmup, int(metadata["random_seed"]), source.identity)
        identity = ArchiveIdentity(key, AnalysisKey(key.identity, digest(dict(fold_id=row["fold_id"])),
            "original_mode4_selected_is_objective", "original_mode4_two_trial_pool"),
            context.data["schema"], target.timeframe, execution.data["route"],
            row["train_start"], row["train_end"] + STEP_NS, "original_IS_objective_not_mode5_utility")
        nodes = tuple(DependencyNode(kind, kind, witness, original.end_ns, completed_ns,
            completed_ns, completed_ns, completed_ns, dependencies, ("diagnostic", "selection"),
            "NOT_BACKDATABLE") for kind, dependencies in (
                ("source", ()), ("candidate", ("source",)),
                ("outcome", ("candidate",)), ("revision", ("outcome",))))
        evidence.append(ArchiveEvidence("mode4-fold-" + str(row["fold_id"]), identity,
            row["candidate_id"], digest(dict(started_ns=started_ns, fold=row)),
            digest(dict(initial_state=execution.data["initial_state"], window=[identity.start_ns, identity.end_ns])),
            digest(row), ("revision",), nodes, "COMPLETE", None,
            ("original_fold_selection", "original_sampler_trial"), ()))
    path = inputs["workdir"] / "mode4-archive.json"
    write_json(path, dict(schema="quantbt.synthetic_completed_mode4_archive.v1",
        started_ns=started_ns, completed_ns=completed_ns, context=context.data,
        clock_domains=dict(market="Synthetic 2020/2021 tape, not historical market evidence",
            execution="Observed UTC wall time", dependency_availability="Conservative actual metadata readback time",
            qualification="Retrospective synthetic mechanics, not original historical discovery"),
        source=source.data, execution=execution.data, folds=rows,
        evidence=[asdict(e) for e in evidence],
        limitations=["Actual synthetic executions, not independent accounting or economic certification",
            "Whole receipt is full-development and NOT_BACKDATABLE; old scores are not warm starts"]))
    pin = file_identity(path)
    published_ns = time.time_ns()
    source_witness = replace(witness, ready_ns=published_ns)
    access = replace(inputs["access"], manifests=(*inputs["access"].manifests, ARCHIVE_SOURCE),
        cutoff_ns=max(time.time_ns(), published_ns + 1))
    sources = [Source(**{**s, "witness": AccessWitness(**s["witness"])})
               for s in inputs["catalog"].manifest.data["sources"]]
    sources.append(Source(ARCHIVE_SOURCE, str(path), pin["sha256"], pin["bytes"], source_witness))
    catalog = EvidenceCatalog(tuple(sources), replace(access, purpose="diagnostic"))
    entries = []
    for i, e in enumerate(evidence):
        current_key = replace(e.identity.execution, account=binding.data['continuous']['account_policy'])
        destination = replace(e.identity, execution=current_key,
            analysis=AnalysisKey(current_key.identity, context.data['roles'], context.data['metrics'],
                context.data['references']),
            start_ns=binding.data['continuous']['start_ns'], end_ns=binding.data['continuous']['stop_ns'],
            metric_unit='decimal_return')
        entries.append((e, IntendedReuse(destination, 'MODE5_CALIBRATION'),
            catalog.ref(ARCHIVE_SOURCE, '/evidence/' + str(i))))
    entries = tuple(entries)
    return dict(catalog=catalog, access=access, entries=entries, rows=rows)


def _rebind_dossier(original, binding, catalog):
    d = original.record.data
    return Dossier.create(context=Record.of({**d["context"], "scope": binding.identity}),
        matrices=tuple(Matrix(Record.of(d["matrices"][k])) for k in KINDS),
        rosters=tuple(Record.of(d["matrices"][k]["roster"]) for k in KINDS),
        inventory=Record.of(catalog.require_ref(d["inventory_ref"])), inventory_ref=d["inventory_ref"],
        catalog=catalog, axes=d["axes"], radar=d["radar"], batteries=d["batteries"],
        assessments=d["recommendations"]["recipes"], limitations=d["limitations"], compute_bill=d["compute_bill"])


def create_recipe_inputs(inputs, *, catalog=None, access=None, entries=(), donor_choices=None):
    """Cold rebind using original matrices/null diagnostics; never infer new metrics.

    donor_choices is an explicit insertion-ordered evidence_id -> coordinate ref
    mapping. The provisional cold plan supplies starts, then a new context,
    dossier, review and plan bind the final warm-start configuration before seal.
    """
    inputs["dossier"].verify(inputs["catalog"])
    catalog, access = catalog or inputs["catalog"], access or inputs["access"]
    original = _base_recipe(inputs)
    binding = Record.of(original["binding"])

    def contracts(current_binding):
        dossier = _rebind_dossier(inputs["dossier"], current_binding, catalog)
        review = ArchiveReview.assess(entries, context_id=digest(dossier.record.data["context"]),
            access=access, catalog=catalog) if entries else None
        donors = None
        if donor_choices is not None:
            donors = ArchiveDonorPlan.create(review=review, choices=donor_choices,
                catalog=catalog, access=access, target=continuous_donor_target(dossier, current_binding, seed=SEED),
                geometry=restore_geometry(current_binding.data["continuous"]["geometry"]),
                researcher="synthetic cross-mode author", reason="Explicit fold roster; no donor ranking or old scores",
                budget=MODE5_TRIALS)
        return dossier, review, donors

    dossier, review, donors = contracts(binding)
    if donors is not None:
        starts = donors.warm_start_records(catalog=catalog, access=access,
            target=continuous_donor_target(dossier, binding, seed=SEED),
            geometry=restore_geometry(binding.data["continuous"]["geometry"]), budget=MODE5_TRIALS)
        binding = Record.of({**binding.data, "warm_start": starts})
        dossier, review, donors = contracts(binding)
    spec = original["spec"]
    objective = spec["objective"]
    option_id = "explicit-donor-challenger" if donors is not None else "matched-no-assistance-baseline"
    recipe = CalibrationRecipe.continuous(dossier, option_id=option_id, binding=binding,
        param_ranges=inputs["param_ranges"], formula=Formula(objective["version"], Channel(**objective["channel"]),
            tuple(objective["coefficients"].items())), selector_id=spec["selector"]["id"],
        search_budget=MODE5_TRIALS, seed=SEED, access=access, validation=spec["validation"],
        failure_policy="raise", reason="Matched synthetic mechanics preference; no superiority claim", donors=donors)
    verify_recipe_donors(recipe, dossier=dossier, binding=binding, catalog=catalog, access=access)
    worksheet = CalibrationWorksheet.create(dossier=dossier, catalog=catalog, options=(recipe,),
        archive=review, archive_access=access if review is not None else None)
    return {**inputs, "dossier": dossier, "catalog": catalog, "access": access,
        "binding": binding, "recipe": recipe, "worksheet": worksheet, "option_id": option_id,
        "archive": review, "archive_access": access if review is not None else None, "donors": donors}


def _compile(inputs, arm):
    worksheet = inputs["worksheet"].choose(inputs["option_id"], researcher="synthetic cross-mode author",
        reason="Explicit matched " + arm + "; no economic promotion")
    pack = Mode5RunPack.compile(worksheet, dossier=inputs["dossier"], catalog=inputs["catalog"],
        access=inputs["access"], archive_access=inputs["archive_access"])
    path = pack.export(inputs["workdir"] / (arm + "-run-pack"), private=True)
    return Mode5RunPack.read(path, expected_identity=pack.identity)


def _prepare(inputs, pack, arm):
    return pack.prepare(dossier=inputs["dossier"], catalog=inputs["catalog"], access=inputs["access"],
        archive_access=inputs["archive_access"], journal=GovernanceLog(inputs["workdir"] / (arm + "-journal")),
        data=inputs["data"], strategy=inputs["strategy"], param_ranges=inputs["param_ranges"],
        account_kwargs=inputs["account_kwargs"], target_mode="pct_equity")


def _observed_work(result, proposals):
    meta = result.metadata["walk_forward"]
    cache = meta["prepared_scoring_cache"]
    if cache["prepared_runs"] != 0 or meta["target_mode"] != "pct_equity":
        raise ValueError("work-count witness is qualified only for original legacy pct_equity fallback")
    return dict(proposals=proposals, financial_invocations=int(cache["fallback_runs"]) + 1,
        authority="original fallback_runs plus the returned final account; no native pass-count claim")


def _completed(inputs, pack, endpoint, arm):
    result = endpoint.backtest(data=inputs["data"], param_ranges=inputs["param_ranges"])
    report = pack.reconcile(result)
    if report.record.data["status"] != "RECONCILED_RETAINED_RUN":
        raise ValueError("positive smoke requires actual reconciled selection; retained outcome is not promoted")
    path = inputs["workdir"] / (arm + "-reconciliation.json")
    write_json(path, report.record.data)
    decision = DecisionReport(Record.of(report.record.data["actual_decision"]))
    bundle = WinnerBaseline(decision, pack, inputs["dossier"], inputs["catalog"], inputs["access"],
        str(path) + "#sha256=" + file_identity(path)["sha256"], archive_access=inputs["archive_access"], result=result)
    meta = result.metadata["walk_forward"]["mode5_diagnostics_first"]
    return dict(result=result, report=report, context=bundle,
        work=_observed_work(result, int(meta["sampler"]["attempts"])), metadata=meta)


def run_demo(workdir, *, donor_folds):
    """Execute only this explicit bounded protocol, with no retry/fallback path."""
    donor_folds = _donor_folds(donor_folds)
    inputs = build_demo_inputs(workdir, donor_folds=donor_folds)
    root, stage, work = inputs["workdir"], "mode4", {}
    try:
        endpoint = mode4_endpoint(inputs)
        started = time.time_ns()
        mode4 = endpoint.backtest(data=inputs["data"], param_ranges=inputs["param_ranges"])
        work["mode4"] = _observed_work(mode4,
            sum(s["attempts"] for s in mode4.metadata["walk_forward"]["sampler_studies"]))
        retained = retain_mode4_archive(inputs, endpoint, mode4, started_ns=started)
        choices = {"mode4-fold-" + str(fold): retained["catalog"].ref(ARCHIVE_SOURCE,
            "/folds/" + str(fold) + "/params") for fold in donor_folds}
        kwargs = {key: retained[key] for key in ("catalog", "access", "entries")}
        baseline = create_recipe_inputs(inputs, **kwargs)
        challenger = create_recipe_inputs(inputs, **kwargs, donor_choices=choices)
        if any(row['disposition'] != 'TARGETED_EXECUTION_REQUIRED'
                for row in challenger['archive'].to_dict()['rows']):
            raise ValueError('old IS paths/scores must not certify the current full Mode5 account')
        # Both choices/packs/journals are frozen before either Mode5 outcome.
        packs = {"baseline": _compile(baseline, "baseline"), "challenger": _compile(challenger, "challenger")}
        endpoints = {"baseline": _prepare(baseline, packs["baseline"], "baseline"),
            "challenger": _prepare(challenger, packs["challenger"], "challenger")}
        completed = {}
        for arm, current in (("baseline", baseline), ("challenger", challenger)):
            stage = arm
            completed[arm] = _completed(current, packs[arm], endpoints[arm], arm)
            work[arm] = completed[arm]["work"]
        a, b = completed["baseline"], completed["challenger"]
        donor_plan = challenger["donors"]
        starts = donor_plan.to_dict()["warm_start"]
        sampler = b["metadata"]["sampler"]
        if (a["metadata"]["sampler"]["warm_start_attempts"] != 0
                or sampler["warm_start_attempts"] != len(starts)
                or [r["effective_params"] for r in sampler["rows"][:len(starts)]] != [r["params"] for r in starts]
                or any(r["source"] != "warm_start" for r in sampler["rows"][:len(starts)])):
            raise ValueError("actual warm-start order/count differs from explicit donor plan")
        stage = "qualification_report"
        winner = packs["challenger"].winner_report(b["result"],
            access=replace(challenger["access"], purpose="diagnostic"),
            witness=AccessWitness(**challenger["binding"].data["continuous"]["witness"]),
            source_ref=b["context"].source_ref,
            request=WinnerQualificationRequest(baseline=a["context"], current=b["context"]))
        summary = dict(schema="quantbt.synthetic_cross_mode_run.v1", status="COMPLETED_SYNTHETIC_MECHANICS",
            work=work, observed_proposals=sum(w["proposals"] for w in work.values()),
            observed_financial_invocations=sum(w["financial_invocations"] for w in work.values()),
            financial_invocation_ceiling=FINANCE_CEILING, donor_plan_id=donor_plan.identity,
            donor_evidence_ids=[r["evidence_id"] for r in donor_plan.to_dict()["donors"]],
            mode4_candidate_ids=[r["candidate_id"] for r in retained["rows"]],
            baseline_winner_id=a["metadata"]["selected_params_digest"],
            challenger_winner_id=b["metadata"]["selected_params_digest"],
            baseline_warm_start_attempts=0, challenger_warm_start_attempts=sampler["warm_start_attempts"],
            archive_score_dispositions={row['evidence_id']: row['disposition']
                for row in challenger['archive'].to_dict()['rows']},
            challenger_attempts=sampler["attempts"], winner_report_id=winner.identity,
            sampler_cutoff_authority=sampler["cutoff_authority"],
            sampler_warm_start_cutoff=pd.Timestamp(sampler["warm_start_cutoff"]).isoformat(),
            sampler_market_cutoff=pd.Timestamp(sampler["is_cutoff"]).isoformat(),
            economic_superiority="NOT_QUALIFIED", independent_validation="NOT_PERFORMED",
            automatic_routing=False, deployment_authorized=False)
        if summary["observed_proposals"] != PROPOSALS or summary["observed_financial_invocations"] > FINANCE_CEILING:
            raise ValueError("observed work differs from bounded protocol")
        write_json(root / "winner-qualification.json", winner.to_dict(private=True))
        write_json(root / "summary.json", summary)
        return dict(summary=summary, winner=winner, baseline=baseline, challenger=challenger,
            completed=completed, packs=packs, mode4_result=mode4)
    except Exception as error:
        write_json(root / "failure.json", dict(status="FAILED_NOT_RETRIED", stage=stage,
            error_type=type(error).__name__, completed_work=work, reserved_proposals=PROPOSALS,
            reserved_financial_ceiling=FINANCE_CEILING,
            failing_stage_work="Not inferred from completed receipts; original failure retained",
            economic_superiority="NOT_QUALIFIED"))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--donor-fold", action="append", type=int, default=[])
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args(argv)
    if args.run and not args.donor_fold:
        parser.error("--run requires an explicit --donor-fold roster")
    if args.run:
        outcome = run_demo(args.workdir, donor_folds=tuple(args.donor_fold))
        print(outcome["winner"].to_json(private=True) if args.private else json.dumps(outcome["summary"], indent=2))
    else:
        print(json.dumps(build_demo_inputs(args.workdir, donor_folds=tuple(args.donor_fold))["protocol"], indent=2))


if __name__ == "__main__":
    main()
