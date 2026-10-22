"""XMR-001..009: independent cold identity, missingness and permission negatives."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, fields, replace
import json
from pathlib import Path
import random

import pytest

from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.diagnostics.identity import AnalysisKey, ExecutionKey, digest
from tools.mode5_research.cross_mode.contracts import (
    ArchiveEvidence, ArchiveIdentity, DependencyNode, DerivedReadback, IntendedReuse,
    assess_reuse, candidate_alias_key,
)


def identity(**changes):
    execution = ExecutionKey("source-v1", "params-v1", "market-v1", "flat-v1", "close-next-open-v1",
                             "BTCUSDT-venue-v1", "fee-slip-v1", "funding-v1", "continuous-v1",
                             "liquidate-v1", "history-v1", 17, "native-artifact-v1")
    analysis = AnalysisKey(execution.identity, "calendar-v1", "net-utility-v1", "reference-v1")
    return replace(ArchiveIdentity(execution, analysis, "schema-v1", "1h", "event-v1", 20, 40,
                                   "decimal_return"), **changes)


def execution_target(original, **changes):
    execution = replace(original.execution, **changes)
    return replace(original, execution=execution, analysis=replace(original.analysis, execution=execution.identity))


def archive():
    witness = AccessWitness("reviewed-market", "development", 0, 40, 45)
    nodes = tuple(DependencyNode(kind, kind, witness, 20, 25, 60, 55, 1_000_000,
                                deps, ("selection", "diagnostic", "independent_validation"), "PREFIX_SAFE")
                  for kind, deps in (("source", ()), ("candidate", ("source",)),
                                     ("outcome", ("candidate",)), ("revision", ("outcome",))))
    return ArchiveEvidence("receipt-row", identity(), "logical-a", "physical-execution-1", "account-state-1",
                           "a" * 64, ("revision",), nodes, "COMPLETE", None,
                           ("marked_observations", "metric_support"), ())


def policy(**changes):
    return replace(AccessPolicy("as-of", ("development",), ("reviewed-market",), 100, "selection"), **changes)


def use(evidence, **changes):
    return replace(IntendedReuse(evidence.identity, "MODE4_PREFIX"), **changes)


def changed_node(evidence, node_id="candidate", **changes):
    return replace(evidence, nodes=tuple(replace(n, **changes) if n.node_id == node_id else n
                                          for n in evidence.nodes))


def test_xmr001_exact_is_metadata_only_and_binds_canonical_analysis():
    evidence = archive()
    result = assess_reuse(evidence, use(evidence), policy())
    assert result.disposition == "EXACT_REUSE"
    assert result.missing_inputs == ()
    assert "accounting truth not certified" in result.reasons[0]
    assert {f.name for f in fields(result)} == {"disposition", "reasons", "missing_inputs"}
    with pytest.raises(ValueError, match="execution-bound"):
        replace(evidence.identity, analysis=replace(evidence.identity.analysis, execution="other-execution"))


@pytest.mark.parametrize("field,value", [("alpha_code", "other-source"), ("market_snapshot", "other-market"),
    ("instrument", "ETHUSDT-venue-v1"), ("costs", "other-fees"), ("funding", "other-funding"),
    ("clock", "other-clock"), ("effective_params", "other-parameters"), ("scenario_seed", 18),
    ("source_backend", "other-artifact")])
def test_xmr001_wrong_financial_identity_is_incompatible(field, value):
    evidence = archive()
    target = execution_target(evidence.identity, **{field: value})
    result = assess_reuse(evidence, use(evidence, identity=target), policy())
    assert result.disposition == "INCOMPATIBLE"
    assert "identity mismatch: execution." + field in result.reasons


@pytest.mark.parametrize("changes", [{"parameter_schema": "other-schema"}, {"timeframe": "4h"},
                                     {"route": "other-route"}, {"metric_unit": "dollars"}])
def test_xmr001_schema_route_timeframe_and_units_are_not_display_names(changes):
    evidence = archive()
    result = assess_reuse(evidence, use(evidence, identity=replace(evidence.identity, **changes)), policy())
    assert result.disposition == "INCOMPATIBLE"


def test_xmr001_derived_requires_complete_target_and_declared_original_inputs():
    evidence = archive()
    target = replace(evidence.identity, analysis=replace(evidence.identity.analysis, metric_statistics="tail-net-v2"))
    request = use(evidence, identity=target)
    assert assess_reuse(evidence, request, policy()).disposition == "INCOMPATIBLE"
    readback = DerivedReadback(target, ("marked_observations", "metric_support"), "original-tail-reducer-v2")
    evidence = replace(evidence, readbacks=(readback,))
    assert assess_reuse(evidence, request, policy()).disposition == "DERIVED_READBACK_ALLOWED"
    sparse = replace(evidence, retained_inputs=("metric_support",))
    result = assess_reuse(sparse, request, policy())
    assert result.disposition == "TARGETED_EXECUTION_REQUIRED"
    assert result.missing_inputs == ("marked_observations",)
    different = replace(target, analysis=replace(target.analysis, normalization_reference="moving-reference"))
    assert assess_reuse(evidence, use(evidence, identity=different), policy()).disposition == "INCOMPATIBLE"


@pytest.mark.parametrize("status", ["PENDING", "PARTIAL_INTERRUPTED", "MISSING", "UNAVAILABLE", "UNDEFINED",
                                    "INVALID", "PRUNED", "FAILED"])
def test_xmr002_nonmeasurements_remain_explicit_even_with_retained_paths(status):
    evidence = replace(archive(), status=status, reason="original disposition retained")
    result = assess_reuse(evidence, use(evidence), policy())
    assert result.disposition == "TARGETED_EXECUTION_REQUIRED"
    assert status in result.reasons[0]
    assert result.missing_inputs == ("measurement:receipt-row",)
    assert evidence.status == status and evidence.reason == "original disposition retained"
    with pytest.raises(ValueError, match="reason"):
        replace(evidence, reason=None)


def test_xmr002_exact_scalar_does_not_satisfy_requested_richer_inputs():
    evidence = archive()
    result = assess_reuse(evidence, use(evidence, required_inputs=("fills", "daily_marks")), policy())
    assert result.disposition == "TARGETED_EXECUTION_REQUIRED"
    assert result.missing_inputs == ("daily_marks", "fills")


def test_xmr003_aliases_require_same_physical_execution_state_role_and_status():
    evidence = archive()
    alias = replace(evidence, evidence_id="alias-row", candidate_id="logical-b")
    assert candidate_alias_key(evidence) == candidate_alias_key(alias)
    for other in (replace(alias, execution_id="physical-execution-2"), replace(alias, state_id="carried-state"),
                  replace(alias, status="FAILED", reason="failed"), replace(alias, content_digest="b" * 64),
                  changed_node(alias, witness=replace(alias.nodes[1].witness, role="diagnostic_development"))):
        assert candidate_alias_key(evidence) != candidate_alias_key(other)
    assert alias.candidate_id == "logical-b" and evidence.candidate_id == "logical-a"


@pytest.mark.parametrize("kind", ["source", "candidate", "outcome", "revision"])
def test_xmr004_not_backdatable_dependencies_survive_truncating_rows(kind):
    evidence = changed_node(archive(), kind, backdating="NOT_BACKDATABLE")
    assert assess_reuse(evidence, use(evidence), policy()).disposition == "RIGHTS_FORBIDDEN"
    current = use(evidence, mode="MODE5_CALIBRATION")
    assert assess_reuse(evidence, current, policy()).disposition == "EXACT_REUSE"
    earlier = replace(evidence.identity, end_ns=30)
    result = assess_reuse(evidence, use(evidence, identity=earlier), policy())
    assert result.disposition == "RIGHTS_FORBIDDEN"
    assert any("NOT_BACKDATABLE" in reason for reason in result.reasons)


@pytest.mark.parametrize("field", ["proposal_available_ns", "revision_available_ns", "publication_ns"])
@pytest.mark.parametrize("available", [100, 101])
def test_xmr005_publication_and_candidate_equality_is_not_permission(field, available):
    evidence = changed_node(archive(), **{field: available})
    result = assess_reuse(evidence, use(evidence), policy())
    assert result.disposition == "RIGHTS_FORBIDDEN"
    assert "candidate: cutoff excludes " + field in result.reasons


def test_xmr005_source_cutoff_is_inclusive_but_actual_wall_time_is_not_simulated_time():
    evidence = changed_node(archive(), source_cutoff_ns=100)
    assert assess_reuse(evidence, use(evidence), policy()).disposition == "EXACT_REUSE"
    late = changed_node(evidence, source_cutoff_ns=101)
    assert assess_reuse(late, use(late), policy()).disposition == "RIGHTS_FORBIDDEN"
    immature = changed_node(evidence, "outcome", witness=replace(evidence.nodes[2].witness, ready_ns=101),
                            revision_available_ns=103, publication_ns=102)
    assert assess_reuse(immature, use(immature), policy()).disposition == "RIGHTS_FORBIDDEN"


@pytest.mark.parametrize("field", ["source_cutoff_ns", "proposal_available_ns", "revision_available_ns", "publication_ns"])
def test_xmr005_unknown_availability_has_explicit_missing_input(field):
    evidence = changed_node(archive(), **{field: None})
    result = assess_reuse(evidence, use(evidence), policy())
    assert result.disposition == "RIGHTS_FORBIDDEN"
    assert result.missing_inputs == ("candidate:" + field,)


@pytest.mark.parametrize("corruption", ["missing", "cycle", "omitted_edge", "absent_root", "empty_graph"])
def test_xmr005_malicious_dependency_graph_fails_closed_without_aborting_inventory(corruption):
    evidence = archive()
    if corruption == "missing":
        evidence = replace(evidence, nodes=evidence.nodes[1:])
    elif corruption == "cycle":
        evidence = changed_node(evidence, "source", dependencies=("revision",))
    elif corruption == "omitted_edge":
        evidence = changed_node(evidence, dependencies=())
    elif corruption == "absent_root":
        evidence = replace(evidence, roots=("forged-root",))
    else:
        evidence = replace(evidence, nodes=())
    result = assess_reuse(evidence, use(evidence), policy())
    assert result.disposition == "RIGHTS_FORBIDDEN"
    assert result.reasons
    if corruption != "cycle":
        assert result.missing_inputs
    good = archive()
    assert assess_reuse(good, use(good), policy()).disposition == "EXACT_REUSE"


def test_xmr005_disconnected_future_recipe_cannot_be_silently_ignored():
    evidence = archive()
    recipe = replace(evidence.nodes[0], node_id="recipe", kind="recipe", revision_available_ns=101)
    corrupt = replace(evidence, nodes=evidence.nodes + (recipe,))
    result = assess_reuse(corrupt, use(corrupt), policy())
    assert result.disposition == "RIGHTS_FORBIDDEN"
    assert "unreferenced dependency node: recipe" in result.reasons
    linked = changed_node(corrupt, dependencies=("source", "recipe"))
    result = assess_reuse(linked, use(linked), policy())
    assert result.disposition == "RIGHTS_FORBIDDEN"
    assert "recipe: cutoff excludes revision_available_ns" in result.reasons


def test_xmr006_deepcopy_and_json_reconstruction_never_carry_access_approval():
    evidence = deepcopy(archive())
    assert assess_reuse(evidence, use(evidence), policy()).disposition == "EXACT_REUSE"
    payload = json.loads(json.dumps(asdict(evidence), allow_nan=False))
    key = payload["identity"]
    payload["identity"] = ArchiveIdentity(**{**key, "execution": ExecutionKey(**key["execution"]),
                                            "analysis": AnalysisKey(**key["analysis"])})
    payload["nodes"] = tuple(DependencyNode(**{**n, "witness": AccessWitness(**n["witness"]),
        "dependencies": tuple(n["dependencies"]), "purposes": tuple(n["purposes"])}) for n in payload["nodes"])
    for name in ("roots", "retained_inputs", "readbacks"):
        payload[name] = tuple(payload[name])
    restored = ArchiveEvidence(**payload)
    assert restored == evidence and restored.identity.identity == evidence.identity.identity
    for narrower in (policy(cutoff_ns=59), policy(manifests=("different-market",)),
                     policy(roles=("diagnostic_development",)), policy(purpose="diagnostic")):
        assert assess_reuse(restored, use(restored), narrower).disposition == "RIGHTS_FORBIDDEN"
    with pytest.raises(FrozenInstanceError):
        restored.nodes[0].source_cutoff_ns = 0
    with pytest.raises(ValueError, match="tuple"):
        replace(restored, retained_inputs=["mutable-input"])


@pytest.mark.parametrize("changes", [{"account": "reset-each-fold"}, {"initial_state": "carried-position"},
                                     {"terminal": "carry-at-end"}, {"warmup": "different-history"}])
def test_xmr007_reset_carry_and_boundary_changes_require_original_execution(changes):
    evidence = archive()
    target = execution_target(evidence.identity, **changes)
    result = assess_reuse(evidence, use(evidence, identity=target), policy())
    assert result.disposition == "TARGETED_EXECUTION_REQUIRED"
    assert result.missing_inputs == ("execution:" + target.financial_identity,)
    with pytest.raises(ValueError, match="same-financial"):
        replace(evidence, readbacks=(DerivedReadback(target, ("marked_observations",), "not-a-reset-reducer"),))


def test_xmr007_matching_summary_or_paths_do_not_authorize_another_window():
    evidence = archive()
    target = replace(evidence.identity, start_ns=21)
    assert assess_reuse(evidence, use(evidence, identity=target), policy()).disposition == "TARGETED_EXECUTION_REQUIRED"


def test_xmr008_held_acquisition_purpose_and_original_role_are_independent_checks():
    evidence = archive()
    held = replace(evidence, nodes=tuple(replace(n, witness=replace(n.witness, role="holdout"),
                                               purposes=("independent_validation",)) for n in evidence.nodes))
    validation = policy(roles=("holdout",), purpose="independent_validation")
    assert assess_reuse(held, use(held, mode="HELD_ASSESSMENT"), validation).disposition == "EXACT_REUSE"
    assert assess_reuse(held, use(held), policy()).disposition == "RIGHTS_FORBIDDEN"
    probe = changed_node(evidence, "outcome", purposes=("independent_validation",))
    result = assess_reuse(probe, use(probe), policy())
    assert result.disposition == "RIGHTS_FORBIDDEN"
    assert "outcome: original purpose forbids requested use" in result.reasons


def test_xmr009_deterministic_cold_reduction_has_no_execution_imports_or_rng_consumption():
    evidence = archive()
    before = random.getstate()
    expected = assess_reuse(evidence, use(evidence), policy())
    reversed_nodes = replace(evidence, nodes=tuple(reversed(evidence.nodes)))
    assert assess_reuse(reversed_nodes, use(evidence), policy()) == expected
    assert candidate_alias_key(reversed_nodes) == candidate_alias_key(evidence)
    assert digest(asdict(expected)) == digest(asdict(assess_reuse(deepcopy(evidence), use(evidence), policy())))
    assert random.getstate() == before
    source = Path(__file__).resolve().parents[2] / "src/quantbt/diagnostics/archive_contracts.py"
    tree = ast.parse(source.read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert set(imports) == {"dataclasses", "typing", "quantbt.mode5.diagnostics.access",
                            "quantbt.mode5.diagnostics.identity"}
    assert not any(isinstance(n, ast.Import) for n in ast.walk(tree))
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id in {"open", "eval", "exec", "__import__"} for n in ast.walk(tree))
