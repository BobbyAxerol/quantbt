"""Mode-independent cold analysis, authorization and unchanged reducer oracles."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import pickle
import random
import subprocess
import sys

import numpy as np
import pytest

from quantbt.diagnostics import (AccessPolicy, AccessWitness, AlphaDiagnostics,
    DiagnosticAdvice, DiagnosticAnalysis, DiagnosticBudget, DiagnosticContext,
    DiagnosticNeeds, DiagnosticObservation, compile_plan)
from quantbt.diagnostics.geometry import EffectiveGeometry, finite_panel_screen
from quantbt.mode5.artifacts import file_identity
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
from tools.mode5_diagnostics.planner import compile_plan as legacy_plan


RANGES = {"window": (1, 12), "threshold": (0.0, 1.0)}


def context(**kwargs):
    return DiagnosticContext(**dict(dict(alpha_id="synthetic-alpha-v1", market_id="tape-v1",
        economics_id="account-clock-fee-v1", route_id="intrabar",
        metric_units=(("quality", "raw_sharpe"), ("risk", "decimal_drawdown")),
        primary_metric="quality", direction="maximize", generation_method="fixed_panel_v1",
        outcome_blind_roster=True, activity_definition="producer_entry_count_v1"), **kwargs))


def policy(cutoff=101):
    return AccessPolicy("pre-search-v1", ("development",), ("tape-v1",), cutoff, "diagnostic")


def observations(ctx=None, geometry=None):
    ctx, geometry = ctx or context(), geometry or EffectiveGeometry.from_ranges(RANGES)
    return [DiagnosticObservation.from_params(geometry=geometry,
        params={"window": i+1, "threshold": i/12},
        metrics={"quality": float(i), "risk": -float(i)},
        evaluation_id=f"trial-{i}", context_id=ctx.identity,
        witness=AccessWitness("tape-v1", "development", 0, 100, 101),
        source_ref=f"synthetic/financial-{i}", activity_count=i)
        for i in range(12)]


def owner(ctx=None, **kwargs):
    return AlphaDiagnostics(RANGES, context=ctx or context(), access=policy(), **kwargs)


@pytest.mark.parametrize("mode", ["pre_search", "mode_1_decay", "mode_2_sbb",
    "mode_3_flat_minima", "mode_4_is_only_robust", "mode_5_full_robust"])
@pytest.mark.parametrize("route", ["pct_equity", "portfolio", "basket", "arbitrage",
    "intrabar", "event_driven", "order_commands", "reactive"])
def test_any_mode_or_route_is_a_requirement_label_not_execution_or_meta_support(mode, route):
    needs = DiagnosticNeeds(objective=("return",), axes=("account_tail",), audit=("fill_audit",))
    plan = compile_plan(needs, route_id=route, backend="rust", optimization_mode=mode,
                        optimization_schedule="caller-declared-schedule")
    assert plan.optimization_mode == mode and plan.route_id == route
    assert set(plan.required_observation_kinds) == {
        "timestamps", "equity", "fill_time", "fill_qty", "fill_price", "fill_fee"}
    assert not plan.native_score_eligible


def test_legacy_mode5_plan_default_and_identity_are_unchanged():
    needs = DiagnosticNeeds(axes=("account_tail",))
    old = legacy_plan(needs, route_id="intrabar", backend="rust")
    shared = compile_plan(needs, route_id="intrabar", backend="rust",
                          optimization_mode="mode_5_full_robust")
    assert old.metadata() == shared.metadata()
    assert compile_plan(needs, route_id="intrabar", backend="rust").optimization_mode == "pre_search"


def test_promotion_keeps_one_math_and_cache_owner():
    from tools.mode5_geometry import finite_panel_screen as old
    from tools.mode5_diagnostics import DiagnosticReuse, ExecutionEvidence
    from quantbt.diagnostics import DiagnosticReuse as shared_reuse, ExecutionEvidence as shared_evidence
    assert old is finite_panel_screen
    assert DiagnosticReuse is shared_reuse and ExecutionEvidence is shared_evidence


def test_associations_match_existing_reducer_and_preserve_random_state():
    py_state, np_state = random.getstate(), np.random.get_state()
    rows = observations()
    report = owner().analyze(rows, bootstrap_resamples=16)
    data = report.to_dict()
    result = data["associations"]["result"]
    branch, values = next(iter(result["branches"].items()))
    raw = [dict(candidate_id=r.evaluation_id, branch_id=branch, status=r.status,
        parameters=r.point.params, metrics=r.metrics.data) for r in rows]
    expected = finite_panel_screen(raw, panel_id=result["panel_id"],
        axis_names=("window", "threshold"),
        active_axes_by_branch={branch: ("window", "threshold")},
        units=dict(context().metric_units), outcome_blind=True,
        bootstrap_seed=731, bootstrap_resamples=16)
    expected.pop("candidate_rows")
    assert result == expected
    assert values["associations"]["window"]["quality"]["rho"] == pytest.approx(1.)
    assert values["associations"]["window"]["risk"]["rho"] == pytest.approx(-1.)
    assert random.getstate() == py_state
    now = np.random.get_state()
    assert np_state[0] == now[0] and np_state[2:] == now[2:]
    np.testing.assert_array_equal(np_state[1], now[1])
    assert data["authority"]["automatic_routing"] is False
    assert "candidate_rows" not in result


@pytest.mark.parametrize("copy", [deepcopy, lambda r: pickle.loads(pickle.dumps(r))])
def test_report_is_immutable_and_authorization_is_not_granted_by_hash(copy):
    original = owner().analyze(observations(), bootstrap_resamples=4)
    restored = copy(original)
    restored.to_dict()["coverage"]["evaluations"] = 999
    assert restored.identity == original.identity
    assert restored.to_dict()["coverage"]["evaluations"] == 12
    restored.authorize(policy())
    with pytest.raises(PermissionError):
        restored.authorize(policy(cutoff=100))


def test_metric_changes_invalidate_report_even_on_adaptive_roster():
    ctx = context(outcome_blind_roster=False, generation_method="adaptive_tpe")
    rows = observations(ctx)
    first = owner(ctx).analyze(rows)
    from quantbt.mode5.dossier.records import Record
    rows[0] = replace(rows[0], metrics=Record.of({"quality": -999., "risk": 0.}))
    second = owner(ctx).analyze(rows)
    assert first.identity != second.identity
    assert first.to_dict()["associations"]["result"] is None
    assert "ADAPTIVE" in first.to_dict()["associations"]["status"]


@pytest.mark.parametrize("field,value", [("role", "holdout"), ("manifest_id", "unknown"),
    ("ready_ns", 102), ("end_ns", 102)])
def test_future_or_holdout_data_is_denied_before_analysis(field, value, monkeypatch):
    engine, rows = owner(), observations()
    witness = replace(rows[-1].witness, **{field: value,
        **({"ready_ns": 102} if field == "end_ns" else {})})
    rows[-1] = replace(rows[-1], witness=witness)
    monkeypatch.setattr(engine, "_associations", lambda *a: pytest.fail("analyzed forbidden evidence"))
    with pytest.raises(PermissionError):
        engine.analyze(rows)


def test_missing_negative_flat_failed_and_duplicate_measurements_are_retained():
    from quantbt.mode5.dossier.records import Record
    rows = observations()
    rows[0] = replace(rows[0], status="NO_TRADE", activity_count=0,
                      metrics=Record.of({"quality": None, "risk": 0.}))
    rows[1] = replace(rows[1], status="FAILED", activity_count=None,
                      metrics=Record.of({"quality": None, "risk": None}))
    rows[2] = replace(rows[2], metrics=Record.of({"quality": -5., "risk": 0.}))
    rows.append(replace(rows[2], evaluation_id="duplicate-effective"))
    data = owner().analyze(rows, bootstrap_resamples=4).to_dict()
    assert data["coverage"]["duplicate_effective_evaluations"] == 1
    assert data["coverage"]["missing_primary"] == 1
    assert data["coverage"]["status_counts"]["FAILED"] == 1
    assert data["activity"]["zero_activity_evaluations"] == 1
    assert data["associations"]["status"] == "NOT_ESTIMATED_DUPLICATE_EFFECTIVE_CANDIDATES"
    assert all(row["status"] == "NOT_SUPPLIED" for row in data["analyses"].values())


def test_categorical_and_conditional_geometry_never_becomes_ordinal():
    ranges = {"filter": ["on", "off"], "window": {"kind": "integer", "low": 1,
        "high": 12, "active_if": {"filter": ["on"]}}}
    ctx = context()
    engine = AlphaDiagnostics(ranges, context=ctx, access=policy())
    rows = [DiagnosticObservation.from_params(geometry=engine.geometry,
        params={"filter": "on", "window": 3}, metrics={"quality": 1., "risk": 0.},
        evaluation_id="a", context_id=ctx.identity,
        witness=AccessWitness("tape-v1", "development", 0, 100, 101), source_ref="synthetic")]
    data = engine.analyze(rows, bootstrap_resamples=4).to_dict()
    compat = {r["recipe_id"]: r["compatible"] for r in data["sampler_compatibility"]}
    assert compat == dict(tpe_legacy=True, tpe_multivariate_group=True, cmaes=False, sobol=False)
    branch = next(iter(data["associations"]["result"]["branches"].values()))
    assert "filter" not in branch["associations"]


def test_conditional_parent_order_survives_canonical_metadata():
    ranges = {"z_parent": (0, 1), "a_child": {"kind": "integer", "low": 2,
        "high": 9, "active_if": {"z_parent": [1]}}}
    engine = AlphaDiagnostics(ranges, context=context(), access=policy())
    compat = {r["recipe_id"]: r for r in engine.sampler_compatibility()}
    assert "prior parent" not in compat["cmaes"]["reason"]
    assert "prior parent" not in compat["sobol"]["reason"]
    assert "conditional" in compat["sobol"]["reason"]


def test_advice_and_override_are_traceable_but_do_not_run_anything():
    advice = (DiagnosticAdvice("sampler", "tpe_multivariate_group", "Joint search is a hypothesis",
        ("geometry",), ("matched sampler comparison",)),
        DiagnosticAdvice("selector", "is_only_robust", "Keep incumbent pending local evidence", ("coverage",)))
    report = owner().analyze(observations(), advice=advice, bootstrap_resamples=4)
    revised = report.with_choice(access=policy(), sampler_id="tpe_multivariate_group",
                                selector_id="is_only_robust", reason="Researcher protocol v1")
    assert report.to_dict()["researcher_choice"] is None
    assert revised.to_dict()["researcher_choice"]["applies_configuration"] is False
    with pytest.raises(ValueError, match="shortlist"):
        report.with_choice(access=policy(), sampler_id="cmaes", selector_id=None, reason="Override")
    for row in (DiagnosticAdvice("selector", "x", "Reason", ("unknown",)),
                DiagnosticAdvice("sampler", "tpe_legacy", "Observed", ("geometry",), basis="OBSERVED_COMPARISON")):
        with pytest.raises(ValueError):
            owner().analyze(observations(), advice=(row,), bootstrap_resamples=4)


def catalog(tmp_path, ctx, *, ready=101):
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps({"local": {"context_id": ctx.identity,
        "method": "existing_local_downside_v1", "status": "INSUFFICIENT_COVERAGE"}}))
    ident = file_identity(path)
    witness = AccessWitness("tape-v1", "development", 0, 100, ready)
    source = Source("local-source", str(path), ident["sha256"], ident["bytes"], witness)
    return EvidenceCatalog((source,), policy(cutoff=max(101, ready))), path


def test_optional_analysis_requires_matching_hash_context_and_current_permission(tmp_path):
    ctx = context()
    cat, path = catalog(tmp_path, ctx)
    analysis = DiagnosticAnalysis("fragility", ctx.identity, "local-source", "/local")
    data = owner().analyze(analyses=(analysis,), catalog=cat).to_dict()
    assert data["analyses"]["fragility"]["value"]["status"] == "INSUFFICIENT_COVERAGE"
    path.write_text("{}")
    with pytest.raises(ValueError, match="source changed"):
        owner().analyze(analyses=(analysis,), catalog=cat)
    cat, _ = catalog(tmp_path, ctx, ready=102)
    with pytest.raises(PermissionError):
        owner().analyze(analyses=(analysis,), catalog=cat)
    cat, _ = catalog(tmp_path, context(economics_id="different"))
    with pytest.raises(ValueError, match="source bytes"):
        owner().analyze(analyses=(analysis,), catalog=cat)


@pytest.mark.parametrize("change", ["context", "schema", "metrics", "duplicate_id"])
def test_input_invariants_fail_closed(change):
    from quantbt.mode5.dossier.records import Record
    rows = observations()
    if change == "context":
        rows[0] = replace(rows[0], context_id="other")
    elif change == "schema":
        rows[0] = replace(rows[0], point=replace(rows[0].point, schema_id="other"))
    elif change == "metrics":
        rows[0] = replace(rows[0], metrics=Record.of({"quality": 0.}))
    else:
        rows.append(rows[0])
    with pytest.raises(ValueError):
        owner().analyze(rows)


def test_budgets_fail_without_silent_truncation():
    with pytest.raises(ValueError, match="observation budget"):
        owner(budget=DiagnosticBudget(max_observations=2)).analyze(observations())
    with pytest.raises(ValueError, match="byte budget"):
        owner(budget=DiagnosticBudget(max_report_bytes=10)).analyze()


def test_markdown_is_useful_and_package_has_no_tools_dependency(tmp_path):
    report = owner().analyze(observations(), bootstrap_resamples=4)
    text = report.to_markdown()
    assert all(word in text for word in ("Parameter Support", "Activity", "Parameter Associations", "Recipe Options"))
    source = Path(__file__).resolve().parents[2] / "src"
    script = """
import builtins
original = builtins.__import__
def checked(name, *a, **kw):
    if name == 'tools' or name.startswith('tools.'):
        raise AssertionError('packaged diagnostics imported repository tools')
    return original(name, *a, **kw)
builtins.__import__ = checked
from quantbt.diagnostics import AlphaDiagnostics, DiagnosticNeeds, compile_plan
from quantbt.diagnostics.geometry import finite_panel_screen, estimate_saltelli
assert compile_plan(DiagnosticNeeds(), route_id='custom', backend='reference').optimization_mode == 'pre_search'
print('PACKAGED_IMPORT_PASS')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "PACKAGED_IMPORT_PASS" in result.stdout
