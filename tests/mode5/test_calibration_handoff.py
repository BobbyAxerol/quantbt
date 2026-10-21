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
