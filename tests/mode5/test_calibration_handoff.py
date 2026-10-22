"""M5H-001..016: cold handoff contracts; no optimizer or account executions."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from quantbt.diagnostics import CalibrationRecipe, CalibrationWorksheet, Mode5RunPack
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.plans import FIELDS
from quantbt.mode5.dossier.records import Record
from quantbt.mode5.selection.contracts import Channel, Formula
from test_continuous_runtime import continuous_setup


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    endpoint, frame, ranges, calibration = continuous_setup(tmp_path_factory.mktemp("handoff"), trials=4)
    recipe = CalibrationRecipe.from_spec(option_id="explicit-floor", binding=calibration.binding,
        spec={**calibration.plan.record.data["recipe"], "search_budget": 4},
        reason="Synthetic handoff mechanics; not an economic recommendation",
        field_origins={name: "explicit synthetic preference" for name in (*FIELDS, "search_budget")})
    return endpoint, frame, ranges, calibration, recipe


def worksheet(inputs, *, options=None):
    calibration = inputs[3]
    return CalibrationWorksheet.create(dossier=calibration.dossier, catalog=calibration.catalog,
        options=options or (inputs[4],))


def compile_pack(inputs):
    c = inputs[3]
    chosen = worksheet(inputs).choose("explicit-floor", researcher="test", reason="Explicit mechanics choice")
    return Mode5RunPack.compile(chosen, dossier=c.dossier, catalog=c.catalog, access=c.access)


def test_no_archive_is_an_executable_choice_not_an_implicit_optimizer(inputs):
    report = worksheet(inputs)
    assert report.to_dict(private=True)["archive"] is None
    assert report.to_dict(private=True)["cards"][0]["readiness"] == "READY_FOR_PREFLIGHT"
    assert report.to_dict()["authority"]["optimizer_started"] is False
    with pytest.raises(PermissionError, match="choice"):
        c = inputs[3]
        Mode5RunPack.compile(report, dossier=c.dossier, catalog=c.catalog, access=c.access)


def test_builder_resolves_existing_identifiers_without_changing_preferences(inputs):
    _, _, ranges, c, _ = inputs
    original = c.plan.record.data["recipe"]
    formula = Formula(original["objective"]["version"], Channel(**original["objective"]["channel"]),
        tuple(original["objective"]["coefficients"].items()))
    recipe = CalibrationRecipe.continuous(c.dossier, option_id="builder", binding=c.binding,
        param_ranges=ranges, formula=formula, selector_id=original["selector"]["id"],
        search_budget=4, seed=731, access=c.access, validation=original["validation"],
        failure_policy="raise", reason="Explicit builder preference")
    plan, binding = recipe.resolve(c.dossier)
    assert plan.record.data["recipe"]["objective"] == original["objective"]
    assert binding == c.binding
    assert plan.record.data["recipe"]["retention"]["runtime_binding_identity"] == binding.identity


def test_unsupported_research_option_never_gets_an_executable_alias(inputs):
    proposal = CalibrationRecipe.research_only(option_id="quarterly-regret", reason="Further research only",
        missing_contracts=["No current quarterly public ranking binding"])
    report = worksheet(inputs, options=(inputs[4], proposal))
    assert report.to_dict(private=True)["cards"][1]["readiness"] == "NOT_EXECUTABLE"
    chosen = report.choose("quarterly-regret", researcher="test", reason="Record intent, not activation")
    c = inputs[3]
    with pytest.raises(NotImplementedError, match="NOT_EXECUTABLE"):
        Mode5RunPack.compile(chosen, dossier=c.dossier, catalog=c.catalog, access=c.access)


def test_immutable_override_keeps_parent_and_does_not_mutate_old_evidence(inputs):
    report = worksheet(inputs)
    first = report.choose("explicit-floor", researcher="one", reason="Original preference")
    second = first.choose("explicit-floor", researcher="two", reason="Explicit revised preference")
    assert report.record.data["selection"] is None
    assert second.record.data["selection"]["parent_worksheet_id"] == first.identity
    assert second.record.data["selection"]["previous_choice"] == first.record.data["selection"]
    assert deepcopy(second).identity == second.identity
    assert CalibrationWorksheet.from_json(second.to_json(private=True)) == second


@pytest.mark.parametrize("change", ["binding", "budget", "objective", "schema", "origin"])
def test_stale_or_unbound_recipe_is_not_ready(inputs, change):
    original = inputs[4].record.data
    d = deepcopy(original)
    if change == "binding":
        d["binding"]["metrics"]["max_drawdown"] = .123
    elif change == "budget":
        d["spec"]["search_budget"] = 0
    elif change == "objective":
        d["spec"]["objective"]["version"] = "unregistered-method"
    elif change == "schema":
        d["spec"]["domain"]["schema_id"] = "other"
    else:
        d["field_origins"] = {}
    report = worksheet(inputs, options=(CalibrationRecipe(Record.of(d)),))
    assert report.to_dict(private=True)["cards"][0]["readiness"] == "NOT_EXECUTABLE"


def test_selection_rights_are_explicit_and_narrowed_access_is_not_ignored(inputs):
    c = inputs[3]
    chosen = worksheet(inputs).choose("explicit-floor", researcher="test", reason="Test")
    for access in (replace(c.access, cutoff_ns=c.access.cutoff_ns-1), replace(c.access, policy_id="narrower")):
        with pytest.raises(PermissionError, match="rights"):
            Mode5RunPack.compile(chosen, dossier=c.dossier, catalog=c.catalog, access=access)


def test_export_requires_private_opt_in_and_uses_fixed_runner(inputs, tmp_path):
    pack = compile_pack(inputs)
    with pytest.raises(PermissionError, match="private"):
        pack.export(tmp_path / "refused")
    path = pack.export(tmp_path / "pack", private=True)
    assert Mode5RunPack.read(path, expected_identity=pack.identity) == pack
    manifest = json.loads((path.parent / "manifest.json").read_text())
    assert manifest["source_files_bundled"] is False
    assert "eval(" not in (path.parent / "run_mode5.py").read_text()
    with pytest.raises(FileExistsError):
        pack.export(path.parent, private=True)
    with pytest.raises(ValueError, match="identity"):
        Mode5RunPack.read(path, expected_identity="wrong")


@pytest.mark.parametrize("what", ["binding", "plan", "worksheet", "promotion"])
def test_run_pack_tampering_fails_before_preflight(inputs, what):
    d = compile_pack(inputs).record.data
    if what == "promotion":
        d["deployment_authorized"] = True
    else:
        d[what]["forged"] = True
    with pytest.raises(ValueError):
        Mode5RunPack(Record.of(d))


def test_source_mutation_invalidates_existing_compile_without_finance(inputs, monkeypatch):
    c = inputs[3]
    def changed():
        raise ValueError("source changed since snapshot")
    monkeypatch.setattr(c.catalog, "verify_current", changed)
    with pytest.raises(ValueError, match="source changed"):
        compile_pack(inputs)


def test_preflight_uses_existing_endpoint_without_calling_alpha_or_optimizer(inputs, tmp_path, monkeypatch):
    from quantbt.walkforward import WalkForwardEngine
    from quantbt.optimization.study_schedule import run_ordered_study
    del run_ordered_study
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected financial/strategy call")
    monkeypatch.setattr(WalkForwardEngine, "_call_strategy", forbidden)
    old, data, ranges, c, _ = inputs
    endpoint = compile_pack(inputs).prepare(dossier=c.dossier, catalog=c.catalog,
        journal=GovernanceLog(tmp_path / "journal"), access=c.access, data=data,
        strategy=old.config.strategy_class, param_ranges=ranges,
        account_kwargs=dict(initial_capital=20000., fee=.0005, slippage=.0001,
            alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["ETHUSDT"]))
    assert endpoint.config.walkforward_config.optimization_mode == "mode_5_full_robust"
    assert endpoint.config.walkforward_config.fold_account_policy == "carry_position"


def test_changed_actual_account_rejected_before_journal_seal(inputs, tmp_path):
    old, data, ranges, c, _ = inputs
    journal = GovernanceLog(tmp_path / "journal")
    with pytest.raises(ValueError):
        compile_pack(inputs).prepare(dossier=c.dossier, catalog=c.catalog, journal=journal,
            access=c.access, data=data, strategy=old.config.strategy_class, param_ranges=ranges,
            account_kwargs=dict(initial_capital=19000., fee=.0005, slippage=.0001,
                alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["ETHUSDT"]))
    assert journal.history() == ()


def test_generated_pack_has_no_source_paths_or_bundled_financial_arrays(inputs):
    pack = compile_pack(inputs)
    assert all("path" not in row for row in pack.record.data["external_sources"])
    def keys(value):
        if isinstance(value, dict):
            return set(value).union(*(keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(v) for v in value))
        return set()
    assert "daily_returns" not in keys(pack.record.data)
    public = worksheet(inputs).to_json()
    assert "explicit-floor" not in public
    assert "synthetic preference" not in public


def test_five_readable_views_and_machine_values_share_same_owner(inputs):
    report = worksheet(inputs).choose("explicit-floor", researcher="test", reason="Bound preference")
    rendered = report.to_markdown(private=True)
    for section in ("Decision Summary", "Alpha Behavior", "Recipe Comparison", "Run Configuration", "Post-Run Qualification"):
        assert "## " + section in rendered
    assert "NOT_RUN" in rendered
    assert report.record.data["cards"][0]["recipe"]["spec"]["search_budget"] == 4


def test_forged_rehashed_choice_cannot_fabricate_its_parent(inputs):
    d = worksheet(inputs).choose("explicit-floor", researcher="test", reason="Actual choice").record.data
    d["selection"]["reason"] = "Forged revision"
    d["selection"]["parent_worksheet_id"] = "f" * 64
    with pytest.raises(ValueError, match="parent"):
        CalibrationWorksheet(Record.of(d))


@pytest.mark.parametrize("private", [1, "yes", None])
def test_private_disclosure_requires_a_boolean(inputs, private):
    with pytest.raises(ValueError, match="boolean"):
        worksheet(inputs).to_json(private=private)


@pytest.mark.parametrize("mutation", ["future", "prices", "clock", "attributes"])
def test_mutated_actual_market_fails_before_search_and_seal(inputs, tmp_path, mutation):
    import pandas as pd
    old, data, ranges, c, _ = inputs
    changed = data.copy(deep=True)
    if mutation == "future":
        changed = pd.concat([changed, changed.iloc[-1:].set_axis(
            pd.DatetimeIndex([changed.index[-1] + pd.Timedelta(hours=1)]))])
    elif mutation == "clock":
        changed.index = changed.index.tz_localize(None)
    elif mutation == "attributes":
        changed.attrs["qty_step"] = 1
    else:
        changed.iloc[-1, changed.columns.get_loc("close")] += 5
    journal = GovernanceLog(tmp_path / "journal")
    with pytest.raises((ValueError, PermissionError, NotImplementedError)):
        compile_pack(inputs).prepare(dossier=c.dossier, catalog=c.catalog, journal=journal,
            access=c.access, data=changed, strategy=old.config.strategy_class, param_ranges=ranges,
            account_kwargs=dict(initial_capital=20000., fee=.0005, slippage=.0001,
                alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["ETHUSDT"]))
    assert not journal.history()


def test_duplicate_json_keys_and_symlinked_pack_paths_are_rejected(inputs, tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema": "one", "schema": "two"}')
    with pytest.raises(ValueError, match="duplicate"):
        Mode5RunPack.read(path, expected_identity=compile_pack(inputs).identity)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="symlink"):
        Mode5RunPack.read(alias, expected_identity="unused")


def test_choice_revision_changes_plan_seal_even_for_the_same_recipe(inputs):
    c = inputs[3]
    one = worksheet(inputs).choose("explicit-floor", researcher="one", reason="first")
    two = one.choose("explicit-floor", researcher="two", reason="second")
    left = Mode5RunPack.compile(one, dossier=c.dossier, catalog=c.catalog, access=c.access)
    right = Mode5RunPack.compile(two, dossier=c.dossier, catalog=c.catalog, access=c.access)
    assert left.record.data["plan_id"] != right.record.data["plan_id"]
    assert left.record.data["plan"]["recipe"] == right.record.data["plan"]["recipe"]


def test_forged_reconciliation_and_public_count_payloads_fail_closed():
    from quantbt.diagnostics import CalibrationRunReport
    base = dict(schema="quantbt.calibration_run_report.v1", pack_id="pack", worksheet_id="worksheet",
        plan_id="plan", binding_id="binding", status="FAILED_UNVERIFIED", mismatches=[],
        actual_decision=None, final_account={"status": "NOT_AVAILABLE"}, limitations=[],
        partial_work=dict(producer_status="FAILED_CLOSED", error_type="InterruptedError",
            retained_trial_rows=0, trial_dispositions=[]))
    assert CalibrationRunReport(Record.of(base)).to_dict()["retained_trial_rows"] == 0
    bad = deepcopy(base)
    bad["partial_work"]["retained_trial_rows"] = "private-content"
    with pytest.raises(ValueError, match="counts"):
        CalibrationRunReport(Record.of(bad))
    for status in ("RECONCILED_RETAINED_RUN", "NO_SELECTION"):
        with pytest.raises(ValueError):
            CalibrationRunReport(Record.of({**base, "status": status}))
    with pytest.raises(ValueError):
        CalibrationRunReport(Record.of({**base, "final_account": {"status": "MATCHED_ORIGINAL_MARKS"}}))


def test_reloaded_foreign_archive_context_cannot_be_compiled(inputs):
    from quantbt.diagnostics import ArchiveReview
    from quantbt.mode5.diagnostics.identity import digest
    c = inputs[3]
    original = worksheet(inputs).record.data
    original["archive"] = ArchiveReview.empty("other-context", c.access).record.data
    report = CalibrationWorksheet(Record.of(original))
    assert digest(c.dossier.record.data["context"]) != "other-context"
    with pytest.raises(ValueError, match="archive context"):
        report.verify(dossier=c.dossier, catalog=c.catalog, archive_access=c.access)


def attachment(inputs, tmp_path, *, extra_dependency=False):
    from quantbt.diagnostics import AlphaDiagnostics, AlphaDiagnosticReport, DiagnosticContext
    from quantbt.mode5.artifacts import file_identity, write_json
    from quantbt.mode5.dossier.dossier import Dossier
    from quantbt.mode5.dossier.evidence import EvidenceCatalog, KINDS, Matrix, Source
    from quantbt.mode5.diagnostics.access import AccessWitness
    c = inputs[3]
    context = c.dossier.record.data["context"]
    policy = replace(c.catalog.policy, manifests=("development-1", "extra-dependency"))
    owner = AlphaDiagnostics(inputs[2], context=DiagnosticContext(context["alpha"], context["data"],
        context["economics"], "pct_equity", (("utility", "decimal_return"),),
        "utility", "maximize", "synthetic_unmeasured"), access=policy)
    report = owner.analyze(())
    if extra_dependency:
        d = report.record.data
        from dataclasses import asdict
        d["source_witnesses"].append(asdict(AccessWitness("extra-dependency", "synthetic", 0, 8, 9)))
        report = AlphaDiagnosticReport(Record.of(d))
    path = tmp_path / "diagnostic-source.json"
    write_json(path, report.record.data)
    pin = file_identity(path)
    old = c.catalog.manifest.data["sources"]
    sources = [Source(**{**row, "witness": AccessWitness(**row["witness"])}) for row in old]
    sources.append(Source("report", str(path), pin["sha256"], pin["bytes"], AccessWitness("development-1", "synthetic", 0, 8, 9)))
    catalog = EvidenceCatalog(sources, policy)
    d = c.dossier.record.data
    dossier = Dossier.create(context=Record.of(context),
        matrices=tuple(Matrix(Record.of(d["matrices"][k])) for k in KINDS),
        rosters=tuple(Record.of(d["matrices"][k]["roster"]) for k in KINDS),
        inventory=Record.of(catalog.require_ref(d["inventory_ref"])), inventory_ref=d["inventory_ref"],
        catalog=catalog, axes=d["axes"], radar=d["radar"], batteries=d["batteries"],
        assessments=d["recommendations"]["recipes"], limitations=d["limitations"], compute_bill=d["compute_bill"])
    return report, dossier, catalog


def test_shared_report_attachment_is_source_bound_on_reload(inputs, tmp_path):
    report, dossier, catalog = attachment(inputs, tmp_path)
    view = report.mode5_worksheet(dossier=dossier, catalog=catalog, options=(inputs[4],),
        diagnostic_report_ref=catalog.ref("report"))
    view.verify(dossier=dossier, catalog=catalog)
    d = view.record.data
    d["diagnostic"]["coverage"]["evaluations"] = 999
    with pytest.raises(ValueError, match="attachment"):
        CalibrationWorksheet(Record.of(d)).verify(dossier=dossier, catalog=catalog)


def test_attachment_dependencies_are_rechecked_for_actual_selection(inputs, tmp_path):
    report, dossier, catalog = attachment(inputs, tmp_path, extra_dependency=True)
    view = report.mode5_worksheet(dossier=dossier, catalog=catalog, options=(inputs[4],),
        diagnostic_report_ref=catalog.ref("report")).choose("explicit-floor", researcher="test", reason="Test dependency narrowing")
    with pytest.raises(PermissionError, match="manifest"):
        Mode5RunPack.compile(view, dossier=dossier, catalog=catalog, access=inputs[3].access)


def test_public_synthetic_builder_and_dry_run_do_not_execute_finance(tmp_path, monkeypatch):
    from examples.mode5_diagnostic_handoff import build_inputs
    from quantbt import QuantBTEndpoint
    import optuna
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run started financial or optimizer work")
    monkeypatch.setattr(QuantBTEndpoint, "backtest", forbidden)
    monkeypatch.setattr(optuna, "create_study", forbidden)
    built = build_inputs(tmp_path / "dry-run", optional_archive=True)
    assert built["worksheet"].record.data["selection"] is None
    assert built["archive"].record.data["rows"][0]["disposition"] == "TARGETED_EXECUTION_REQUIRED"


def test_compile_and_preflight_leave_global_rng_unchanged(inputs, tmp_path):
    import numpy as np
    import random
    old, data, ranges, c, _ = inputs
    before_np, before_py = np.random.get_state(), random.getstate()
    pack = compile_pack(inputs)
    pack.prepare(dossier=c.dossier, catalog=c.catalog, journal=GovernanceLog(tmp_path / "journal"),
        access=c.access, data=data, strategy=old.config.strategy_class, param_ranges=ranges,
        account_kwargs=dict(initial_capital=20000., fee=.0005, slippage=.0001,
            alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["ETHUSDT"]))
    after = np.random.get_state()
    assert before_np[0] == after[0]
    np.testing.assert_array_equal(before_np[1], after[1])
    assert before_np[2:] == after[2:]
    assert before_py == random.getstate()


def test_reloaded_source_bound_foreign_diagnostic_context_is_rejected(inputs, tmp_path):
    from quantbt.mode5.artifacts import file_identity, write_json
    from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
    from quantbt.mode5.diagnostics.access import AccessWitness
    from quantbt.diagnostics import AlphaDiagnosticReport
    report, dossier, catalog = attachment(inputs, tmp_path)
    original = report.record.data
    original["context"]["market_id"] = "foreign-market"
    from quantbt.mode5.diagnostics.identity import digest
    original["context_id"] = digest({"schema": "quantbt.diagnostic_context.v1", **original["context"]})
    foreign = AlphaDiagnosticReport(Record.of(original))
    path = tmp_path / "foreign-report.json"
    write_json(path, foreign.record.data)
    pin = file_identity(path)
    sources = [Source(**{**row, "witness": AccessWitness(**row["witness"])})
               for row in catalog.manifest.data["sources"]]
    sources.append(Source("foreign", str(path), pin["sha256"], pin["bytes"],
                          AccessWitness("development-1", "synthetic", 0, 8, 9)))
    # Both reports belong to the catalog, but only the first matches the dossier.
    expanded = EvidenceCatalog(sources, catalog.policy)
    # A forged rehashed worksheet cannot bypass the context check by embedding
    # a valid report/ref/summary from a different market.
    d = CalibrationWorksheet.create(dossier=dossier, catalog=catalog, options=(inputs[4],)).record.data
    d["catalog_id"] = expanded.manifest.identity
    d["diagnostic"] = dict(identity=foreign.identity, ref=expanded.ref("foreign"),
        **{k: original[k] for k in ("coverage", "activity", "sampler_compatibility")})
    # The existing dossier pins the original catalog. Isolate the subsequent
    # attachment check; current-source/catalog verification itself is tested above.
    from unittest.mock import patch
    with patch.object(type(dossier), "verify", return_value=dossier):
        with pytest.raises(ValueError, match="report context"):
            CalibrationWorksheet(Record.of(d)).verify(dossier=dossier, catalog=expanded)


def policy_metadata(pack):
    from types import SimpleNamespace
    import pandas as pd
    from quantbt.diagnostics.calibration.verification import expected_selection
    from quantbt.optimization import SamplerConfig
    from quantbt.optimization.wfo_study import WfoSamplerStudy
    from quantbt.diagnostics.calibration.worksheet import selection_access
    d = pack.record.data
    recipe, binding = d["plan"]["recipe"], d["binding"]
    ranges = {s["name"]: recipe["domain"]["ranges"][s["name"]]
              for s in binding["continuous"]["geometry"]["parameters"]}
    bridge = WfoSamplerStudy(SamplerConfig(**binding["sampler"]), ranges,
        seed=recipe["sampler"]["seeds"][0], budget=d["plan"]["search_budget"],
        cutoff=pd.Timestamp(selection_access(recipe["reuse"]["selection_policy"]).cutoff_ns, tz="UTC"),
        strategy_identity=d["worksheet"]["context"]["alpha"], stage="is_search")
    bridge.sampler(result_constraints=False)
    sampler = bridge.metadata(SimpleNamespace(get_trials=lambda deepcopy=False: []))
    sampler.update(rows=[], warm_start_attempts=0)
    plan = expected_selection(pack)
    decision = dict(plan_identity=plan.identity, formula_identity=plan.formula.identity,
        formula_version=plan.formula.version, formula_coefficients=[list(v) for v in plan.formula.coefficients],
        minimum_improvement=binding["selection"]["minimum_improvement"], reference=binding["reference"],
        requested_selector=binding["selection"]["requested_selector"], resolved_selector=recipe["selector"]["id"])
    return dict(sampler=sampler, decision=decision, optimizer_schedule=recipe["sampler"]["schedule"],
        batch_size=binding["batch_size"], eligibility_policy=binding["continuous"].get("eligibility_policy"))


@pytest.mark.parametrize("field", ["formula_identity", "formula_version", "formula_coefficients"])
def test_no_selection_formula_fields_cannot_hide_behind_a_valid_plan_id(inputs, field):
    from quantbt.diagnostics.calibration.verification import policy_mismatches
    pack = compile_pack(inputs)
    metadata = policy_metadata(pack)
    metadata.update(status="NO_SELECTION", error_type="Mode5NoSelectionError")
    assert not policy_mismatches(pack, metadata)
    metadata["decision"][field] = "wrong-formula"
    assert any("selection plan" in v for v in policy_mismatches(pack, metadata))


def test_warm_start_actual_effective_coordinates_are_checked_not_only_requested(inputs):
    from quantbt.diagnostics.calibration.verification import policy_mismatches
    pack = compile_pack(inputs)
    d = pack.record.data
    params = {"period": 6}
    d["binding"]["warm_start"] = [dict(params=params)]
    d["binding_id"] = Record.of(d["binding"]).identity
    # A policy-verifier unit control, not a compiled executable warm-start pack.
    edited = Mode5RunPack(Record.of(d))
    metadata = policy_metadata(edited)
    metadata["sampler"].update(warm_start_attempts=1,
        rows=[dict(source="warm_start", requested_params=params, effective_params=params)])
    assert not policy_mismatches(edited, metadata)
    metadata["sampler"]["rows"][0]["effective_params"] = {"period": 24}
    assert any("effective coordinates" in v for v in policy_mismatches(edited, metadata))


@pytest.mark.parametrize("mutation", ["attributes", "clock"])
def test_prepare_does_not_allow_changed_execution_time_clock_or_attributes(inputs, tmp_path, monkeypatch, mutation):
    import optuna
    from quantbt import QuantBTEndpoint
    old, data, ranges, c, _ = inputs
    pack = compile_pack(inputs)
    endpoint = pack.prepare(dossier=c.dossier, catalog=c.catalog, journal=GovernanceLog(tmp_path / "journal"),
        access=c.access, data=data, strategy=old.config.strategy_class, param_ranges=ranges,
        account_kwargs=dict(initial_capital=20000., fee=.0005, slippage=.0001,
            alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["ETHUSDT"]))
    changed = data.copy(deep=True)
    if mutation == "attributes":
        changed.attrs["qty_step"] = 1
    else:
        changed.index = changed.index.tz_localize(None)
    def forbidden(*args, **kwargs):
        raise AssertionError("mutated input reached finance or an optimizer ask")
    monkeypatch.setattr(QuantBTEndpoint, "_run_single", forbidden)
    monkeypatch.setattr(optuna.study.Study, "ask", forbidden)
    with pytest.raises((NotImplementedError, ValueError)):
        endpoint.backtest(data=changed, param_ranges=ranges)
