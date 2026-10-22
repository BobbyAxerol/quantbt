"""Pure synthetic archive-coordinate admission; no trials or financial work."""

import ast
from collections import OrderedDict
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import json
from pathlib import Path
import random
from types import SimpleNamespace

import pandas as pd
import pytest

from quantbt.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.diagnostics.archive import ArchiveReview
from quantbt.diagnostics.archive_contracts import (
    ArchiveEvidence, ArchiveIdentity, DependencyNode, IntendedReuse,
)
from quantbt.diagnostics.calibration import donors as donor_module
from quantbt.diagnostics.calibration.donors import (
    ArchiveDonorPlan, CoordinateDonorTarget, LIMITATIONS, MAX_DONORS, MAX_PARAMS,
)
from quantbt.diagnostics.geometry.schema import EffectiveGeometry, OrderedConstraint
from quantbt.diagnostics.identity import AnalysisKey, ExecutionKey, digest
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
from quantbt.mode5.dossier.records import Record
from quantbt.optimization.parameter_space import NormalizedSearchSpace


SECRET = "PRIVATE_RESEARCHER_ALPHA_RATIONALE"
RANGES = {
    "period": {"kind": "integer", "low": 2, "high": 10, "step": 1},
    "ratio": {"kind": "float", "low": 0.25, "high": 1.0, "step": 0.25},
    "enabled": {"kind": "boolean"},
    "tag": {"kind": "fixed", "value": "v1"},
}
POINTS = (
    dict(period=3, ratio=0.5, enabled=True, tag="v1"),
    dict(period=8, ratio=1.0, enabled=False, tag="v1"),
)
BUDGET = 3


def _access(**changes):
    return replace(AccessPolicy("current-selection", ("development",),
        ("archive-manifest", "coordinate-manifest", "node-manifest"), 100, "selection"), **changes)


def _execution_target(identity, **changes):
    execution = replace(identity.execution, **changes)
    return replace(identity, execution=execution,
        analysis=replace(identity.analysis, execution=execution.identity))


def _node(evidence, kind="candidate", **changes):
    return replace(evidence, nodes=tuple(replace(n, **changes) if n.kind == kind else n
                                         for n in evidence.nodes))


def _build(tmp_path, *, points=POINTS, evidence_edit=None, intended_edit=None,
           mode="MODE5_CALIBRATION", coordinate_witness=None, archive_witness=None,
           access=None, geometry=None, ranges=None):
    """Literal metadata only; COMPLETE is a synthetic contract control."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    geometry = geometry or EffectiveGeometry.from_ranges(ranges or RANGES)
    space = NormalizedSearchSpace(ranges or RANGES)
    access = access or _access()
    node_witness = AccessWitness("node-manifest", "development", 0, 40, 45)
    nodes = tuple(DependencyNode(kind, kind, node_witness, 40, 47, 65 if kind != "revision" else 79,
        60, 1_000_000, deps, ("selection", "diagnostic"), "PREFIX_SAFE") for kind, deps in (
            ("source", ()), ("candidate", ("source",)),
            ("outcome", ("candidate",)), ("revision", ("outcome",))))
    evidence, intended = [], []
    for i, params in enumerate(points):
        execution = ExecutionKey(SECRET, digest(params), "market-v1", "flat-v1", "close-next-open-v1",
            "DEMO-venue-v1", "fee-slip-v1", "funding-v1", "reset-each-fold-v1",
            "liquidate-v1", "history-v1", 17, "native-artifact-v1")
        identity = ArchiveIdentity(execution,
            AnalysisKey(execution.identity, "calendar-v1", "utility-v1", "reference-v1"),
            space.identity, "1h", "event-v1", 20, 40, "decimal_return")
        entry = ArchiveEvidence("evidence-" + str(i), identity, "candidate-" + str(i),
            "execution-" + str(i), "state-" + str(i), "a" * 64, ("revision",), nodes,
            "COMPLETE", None, (), ())
        destination = replace(_execution_target(identity, account="fresh-continuous-v1",
            initial_state="fresh-flat-v1", terminal="current-terminal-v1"),
            start_ns=21, end_ns=80)
        request = IntendedReuse(destination, mode)
        evidence.append(evidence_edit(entry) if evidence_edit else entry)
        intended.append(intended_edit(request) if intended_edit else request)
    archive_path, coordinate_path = tmp_path / "archive.json", tmp_path / "coordinates.json"
    write_json(archive_path, {"entries": [asdict(e) for e in evidence]})
    write_json(coordinate_path, {"points": list(points), "old_objective_values": [99999, -99999]})
    sources = []
    for name, path, witness in (
        ("archive", archive_path, archive_witness or AccessWitness("archive-manifest", "development", 0, 40, 50)),
        ("coordinates", coordinate_path,
         coordinate_witness or AccessWitness("coordinate-manifest", "development", 0, 40, 55)),
    ):
        content = file_identity(path)
        sources.append(Source(name, str(path), content["sha256"], content["bytes"], witness))
    catalog = EvidenceCatalog(tuple(sources), _access(purpose="diagnostic", cutoff_ns=10**9,
        roles=("development", "diagnostic_development")))
    entries = tuple((e, request, catalog.ref("archive", "/entries/" + str(i)))
                    for i, (e, request) in enumerate(zip(evidence, intended, strict=True)))
    review = ArchiveReview.assess(entries, context_id=SECRET, access=access, catalog=catalog)
    return SimpleNamespace(review=review, catalog=catalog, access=access,
        target=CoordinateDonorTarget.from_contract(intended[0]), geometry=geometry,
        choices={e.evidence_id: catalog.ref("coordinates", "/points/" + str(i))
                 for i, e in enumerate(evidence)}, evidence=evidence, intended=intended,
        points=points, archive_path=archive_path, coordinate_path=coordinate_path)


def _create(case, **changes):
    args = dict(review=case.review, choices=case.choices, catalog=case.catalog, access=case.access,
        target=case.target, geometry=case.geometry, researcher=SECRET, reason=SECRET, budget=BUDGET)
    return ArchiveDonorPlan.create(**{**args, **changes})


def _current(case, **changes):
    return {**dict(catalog=case.catalog, access=case.access, target=case.target,
                   geometry=case.geometry, budget=BUDGET), **changes}


def test_complete_coordinates_are_researcher_ordered_and_sampler_compatible(tmp_path):
    case = _build(tmp_path)
    choices = OrderedDict(reversed(tuple(case.choices.items())))
    plan = _create(case, choices=choices)
    d = plan.to_dict()
    starts = plan.warm_start_records(**_current(case))
    assert [r["evidence_id"] for r in d["donors"]] == ["evidence-1", "evidence-0"]
    assert [r["params"] for r in starts] == list(reversed(POINTS))
    assert all(set(r) == {"params", "available_at", "space_identity", "strategy_identity"} for r in starts)
    assert all(pd.Timestamp(r["available_at"]).value == 79 for r in starts)
    assert all(r["space_identity"] == NormalizedSearchSpace(RANGES).identity for r in starts)
    assert all(r["strategy_identity"] == SECRET for r in starts)
    assert d["review"] == case.review.to_dict() and d["review_id"] == case.review.identity
    assert d["geometry_id"] == case.geometry.identity and d["target_id"] == case.target.identity
    assert d["researcher"] == d["reason"] == SECRET
    assert d["score_reuse"] is False and d["automatic_ranking"] is False
    assert all(r["review_reasons"] and r["reason"] for r in d["donors"])
    assert all(r["review_disposition"] == "TARGETED_EXECUTION_REQUIRED" for r in d["donors"])

    # Exercise the original validator, without sampler(), enqueue(), ask/tell or finance.
    from quantbt.optimization import SamplerConfig
    from quantbt.optimization.wfo_study import WfoSamplerStudy
    bridge = WfoSamplerStudy(SamplerConfig(), RANGES, seed=7, budget=BUDGET,
        cutoff=pd.Timestamp(case.access.cutoff_ns, unit="ns", tz="UTC"),
        strategy_identity=SECRET, stage="is_search")
    assert bridge.validate_warm_start(starts) == [(p, p) for p in reversed(POINTS)]


@pytest.mark.parametrize("source", ["archive", "coordinates", "node"])
def test_latest_allowed_clock_includes_both_sources_and_entire_dag(tmp_path, source):
    kwargs = {}
    if source == "archive":
        kwargs["archive_witness"] = AccessWitness("archive-manifest", "development", 0, 40, 91)
    elif source == "coordinates":
        kwargs["coordinate_witness"] = AccessWitness("coordinate-manifest", "development", 0, 40, 91)
    else:
        kwargs["evidence_edit"] = lambda e: _node(e, "source", publication_ns=91)
    case = _build(tmp_path, **kwargs)
    plan = _create(case)
    assert [r["available_ns"] for r in plan.to_dict()["donors"]] == [91, 91]
    assert all(pd.Timestamp(r["available_at"]).value == 91
               for r in plan.warm_start_records(**_current(case)))


def test_roundtrip_and_copies_are_immutable_and_public_view_is_not_reloadable(tmp_path):
    case = _build(tmp_path)
    plan = _create(case)
    assert plan.verify(**_current(case)) is plan
    assert ArchiveDonorPlan.from_json(plan.to_json(), **_current(case)) == plan
    assert ArchiveDonorPlan(Record.of(plan.to_dict())) == plan
    assert deepcopy(plan) == plan
    changed = plan.to_dict()
    changed["warm_start"][0]["params"]["period"] = 99
    starts = plan.warm_start_records(**_current(case))
    starts[0]["params"].clear()
    assert plan.to_dict()["warm_start"][0]["params"] == POINTS[0]
    with pytest.raises(FrozenInstanceError):
        plan.record = Record.of({})
    with pytest.raises(FrozenInstanceError):
        case.target.route = "other"
    public = plan.to_dict(public=True)
    assert public["donor_count"] == 2 and public["limitations"] == list(LIMITATIONS)
    assert SECRET not in plan.to_json(public=True)
    assert all(name not in public for name in ("review", "target", "geometry", "donors", "warm_start", "reason"))
    with pytest.raises(ValueError):
        ArchiveDonorPlan.from_json(plan.to_json(public=True), **_current(case))


@pytest.mark.parametrize("changes", [dict(account="different-reset-v1"), dict(initial_state="carry-v1"),
    dict(terminal="carry-terminal-v1")])
def test_only_coordinate_reuse_allows_account_reset_and_boundary_differences(tmp_path, changes):
    case = _build(tmp_path, intended_edit=lambda request:
        replace(request, identity=_execution_target(request.identity, **changes)))
    assert len(_create(case).warm_start_records(**_current(case))) == 2


@pytest.mark.parametrize("field,value", [("alpha_code", "other-strategy"), ("market_snapshot", "other-market"),
    ("instrument", "OTHER-venue-v1"), ("clock", "other-clock"), ("costs", "other-costs"),
    ("funding", "other-funding"), ("warmup", "longer-history-v1"),
    ("source_backend", "other-backend"), ("scenario_seed", 18)])
def test_coordinate_reuse_never_weakens_source_execution_compatibility(tmp_path, field, value):
    case = _build(tmp_path, intended_edit=lambda request:
        replace(request, identity=_execution_target(request.identity, **{field: value})))
    with pytest.raises(ValueError, match="incompatible donor"):
        _create(case)


@pytest.mark.parametrize("field,value", [("parameter_schema", "b" * 64), ("timeframe", "4h"), ("route", "other-route")])
def test_schema_timeframe_and_route_must_match_source(tmp_path, field, value):
    case = _build(tmp_path, intended_edit=lambda request:
        replace(request, identity=replace(request.identity, **{field: value})))
    with pytest.raises(ValueError, match="space_identity|incompatible donor"):
        _create(case)


def test_typed_target_is_bound_to_reviewed_actual_destination_not_an_opaque_label(tmp_path):
    case = _build(tmp_path)
    assert case.target == CoordinateDonorTarget.from_contract(case.intended[0])
    with pytest.raises(TypeError, match="opaque"):
        _create(case, target="chosen-destination")
    with pytest.raises(ValueError, match="declared destination"):
        _create(case, target=replace(case.target, route="other-route"))
    with pytest.raises(ValueError, match="declared destination"):
        _create(case, target=replace(case.target, mode="MODE4_PREFIX"))
    for changes in (dict(version="unknown-v2"), dict(space_identity="untyped-space"),
                    dict(scenario_seed=True), dict(costs="")):
        with pytest.raises(ValueError):
            replace(case.target, **changes)


@pytest.mark.parametrize("status", ["PENDING", "PARTIAL_INTERRUPTED", "MISSING", "UNAVAILABLE",
    "UNDEFINED", "INVALID", "PRUNED", "FAILED"])
def test_every_noncomplete_archive_status_is_rejected(tmp_path, status):
    case = _build(tmp_path, evidence_edit=lambda e: replace(e, status=status, reason="not complete"))
    with pytest.raises(ValueError, match="COMPLETE"):
        _create(case)


@pytest.mark.parametrize("field", ["source_cutoff_ns", "proposal_available_ns", "revision_available_ns", "publication_ns"])
@pytest.mark.parametrize("clock", [None, 100, 101])
def test_unknown_future_and_cutoff_equal_dag_clocks_are_never_donors(tmp_path, field, clock):
    case = _build(tmp_path, evidence_edit=lambda e: _node(e, **{field: clock}))
    with pytest.raises(PermissionError, match="forbidden donor|strictly before"):
        _create(case)


@pytest.mark.parametrize("kind", ["source", "candidate", "outcome", "revision"])
def test_full_development_dependencies_cannot_be_backdated_by_coordinate_reevaluation(tmp_path, kind):
    def edit(e):
        return _node(e, kind, backdating="NOT_BACKDATABLE")
    retrospective = _build(tmp_path / "current", evidence_edit=edit)
    assert _create(retrospective).verify(**_current(retrospective))
    prefix = _build(tmp_path / "prefix", evidence_edit=edit, mode="MODE4_PREFIX")
    with pytest.raises(PermissionError, match="NOT_BACKDATABLE"):
        _create(prefix)


def test_lawful_prefix_coordinates_still_use_prefix_access_and_clocks(tmp_path):
    case = _build(tmp_path, mode="MODE4_PREFIX")
    plan = _create(case)
    assert ArchiveDonorPlan.from_json(plan.to_json(), **_current(case)) == plan
    assert all(pd.Timestamp(r["available_at"]).value < case.access.cutoff_ns
               for r in plan.warm_start_records(**_current(case)))


def test_reload_cannot_relabel_a_full_development_plan_as_a_prefix_donor(tmp_path):
    case = _build(tmp_path, evidence_edit=lambda e: _node(e, backdating="NOT_BACKDATABLE"))
    plan = _create(case)
    prefix_target = replace(case.target, mode="MODE4_PREFIX")
    with pytest.raises(ValueError, match="declared destination"):
        ArchiveDonorPlan.from_json(plan.to_json(), **_current(case, target=prefix_target))
    data = plan.to_dict()
    data["target"] = asdict(prefix_target)
    data["target_id"] = prefix_target.identity
    with pytest.raises(ValueError, match="declared destination"):
        ArchiveDonorPlan.from_json(json.dumps(data), **_current(case, target=prefix_target))


@pytest.mark.parametrize("corruption", ["missing", "cycle", "disconnected", "forbidden-purpose"])
def test_malformed_or_wrong_purpose_dependency_graph_is_rejected(tmp_path, corruption):
    def edit(e):
        if corruption == "missing":
            return replace(e, nodes=e.nodes[1:])
        if corruption == "cycle":
            return _node(e, "source", dependencies=("revision",))
        if corruption == "disconnected":
            return replace(e, nodes=e.nodes + (replace(e.nodes[0], node_id="unlinked", kind="recipe"),))
        return _node(e, purposes=("diagnostic",))
    case = _build(tmp_path, evidence_edit=edit)
    with pytest.raises(PermissionError, match="forbidden donor"):
        _create(case)


@pytest.mark.parametrize("source", ["archive", "coordinates"])
def test_cutoff_equal_source_readiness_is_not_earlier_donor_availability(tmp_path, source):
    key = "archive_witness" if source == "archive" else "coordinate_witness"
    manifest = "archive-manifest" if source == "archive" else "coordinate-manifest"
    case = _build(tmp_path, **{key: AccessWitness(manifest, "development", 0, 40, 100)})
    with pytest.raises(PermissionError, match="strictly before"):
        _create(case)


@pytest.mark.parametrize("source", ["archive", "coordinates"])
def test_current_source_bytes_are_checked_on_create_verify_and_reload(tmp_path, source):
    case = _build(tmp_path)
    plan = _create(case)
    path = case.archive_path if source == "archive" else case.coordinate_path
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    for operation in (lambda: _create(case), lambda: plan.verify(**_current(case)),
        lambda: ArchiveDonorPlan.from_json(plan.to_json(), **_current(case)),
        lambda: plan.warm_start_records(**_current(case))):
        with pytest.raises(ValueError, match="source changed"):
            operation()


@pytest.mark.parametrize("changes", [dict(cutoff_ns=78), dict(manifests=("node-manifest",)),
    dict(roles=("diagnostic_development",)), dict(policy_id="new-policy"), dict(purpose="diagnostic")])
def test_reload_and_conversion_never_inherit_earlier_access_approval(tmp_path, changes):
    case = _build(tmp_path)
    plan = _create(case)
    current = {**_current(case), "access": replace(case.access, **changes)}
    for operation in (lambda: plan.verify(**current),
        lambda: ArchiveDonorPlan.from_json(plan.to_json(), **current),
        lambda: plan.warm_start_records(**current)):
        with pytest.raises((PermissionError, ValueError, TypeError)):
            operation()


def test_separate_coordinate_source_requires_current_selection_rights(tmp_path):
    case = _build(tmp_path, coordinate_witness=
        AccessWitness("coordinate-manifest", "diagnostic_development", 0, 40, 55))
    with pytest.raises(PermissionError, match="role/manifest"):
        _create(case)
    future = _build(tmp_path / "future", coordinate_witness=
        AccessWitness("coordinate-manifest", "development", 0, 40, 101))
    with pytest.raises(PermissionError, match="future or immature"):
        _create(future)


def test_reload_rechecks_coordinate_source_witness_even_when_bytes_are_unchanged(tmp_path):
    case = _build(tmp_path)
    plan = _create(case)
    sources = []
    for source in case.catalog.manifest.data["sources"]:
        witness = AccessWitness(**source["witness"])
        if source["source_id"] == "coordinates":
            witness = replace(witness, ready_ns=54)
        sources.append(Source(**{**source, "witness": witness}))
    current_catalog = EvidenceCatalog(tuple(sources), case.catalog.policy)
    with pytest.raises(ValueError, match="differs from current"):
        ArchiveDonorPlan.from_json(plan.to_json(), **_current(case, catalog=current_catalog))


def test_coordinate_digest_is_the_exact_canonical_archive_execution_digest(tmp_path):
    case = _build(tmp_path, evidence_edit=lambda e:
        replace(e, identity=_execution_target(e.identity, effective_params="b" * 64)))
    with pytest.raises(ValueError, match="archive execution.effective_params"):
        _create(case)


@pytest.mark.parametrize("corruption", ["wrong-point", "bad-digest", "extra-ref-field", "unknown-source", "wrapper"])
def test_coordinate_ref_must_bind_exact_archive_effective_digest(tmp_path, corruption):
    case = _build(tmp_path)
    choices = deepcopy(case.choices)
    ref = choices["evidence-0"]
    if corruption == "wrong-point":
        choices["evidence-0"] = case.catalog.ref("coordinates", "/points/1")
    elif corruption == "bad-digest":
        ref["sha256"] = "b" * 64
    elif corruption == "extra-ref-field":
        ref["score"] = 9
    elif corruption == "unknown-source":
        ref["source"] = "absent"
    else:
        choices["evidence-0"] = case.catalog.ref("coordinates", "")
    with pytest.raises(ValueError):
        _create(case, choices=choices)


@pytest.mark.parametrize("changes", [dict(period=True), dict(period="3"), dict(period=3.0),
    dict(period=11), dict(ratio=0.6), dict(ratio=float("inf")), dict(enabled=1),
    dict(tag="wrong"), dict(period=[3]), dict(unknown=7)])
def test_coordinates_are_typed_bounded_and_already_canonical(tmp_path, changes):
    points = ({**POINTS[0], **changes}, POINTS[1])
    if changes.get("ratio") == float("inf"):
        # Canonical sources themselves forbid nonfinite JSON before admission.
        with pytest.raises(ValueError):
            _build(tmp_path, points=points)
    else:
        case = _build(tmp_path, points=points)
        with pytest.raises(ValueError):
            _create(case)


@pytest.mark.parametrize("name", ["period", "tag"])
def test_missing_active_or_fixed_coordinates_are_not_silently_filled(tmp_path, name):
    params = dict(POINTS[0])
    del params[name]
    case = _build(tmp_path, points=(params, POINTS[1]))
    with pytest.raises(ValueError, match="missing active|no repair"):
        _create(case)


def test_shared_conditional_and_coupled_geometry_is_enforced(tmp_path):
    ranges = {"branch": {"kind": "boolean"},
        "low": {"kind": "integer", "low": 1, "high": 9},
        "high": {"kind": "integer", "low": 1, "high": 9},
        "extra": {"kind": "integer", "low": 1, "high": 9, "active_if": {"branch": [True]}}}
    geometry = EffectiveGeometry.from_ranges(ranges,
        constraints=(OrderedConstraint(("low", "high")),))
    points = (dict(branch=False, low=2, high=4), dict(branch=True, low=3, high=5, extra=7))
    case = _build(tmp_path / "valid", points=points, ranges=ranges, geometry=geometry)
    assert len(_create(case).warm_start_records(**_current(case))) == 2
    for name, point in (("inactive", dict(branch=False, low=2, high=4, extra=7)),
                        ("infeasible", dict(branch=True, low=6, high=4, extra=7))):
        bad = _build(tmp_path / name, points=(point,), ranges=ranges, geometry=geometry)
        with pytest.raises(ValueError, match="no repair|INFEASIBLE"):
            _create(bad)


def test_duplicate_coordinates_and_ambiguous_review_ids_are_rejected(tmp_path):
    duplicate = _build(tmp_path / "duplicate", points=(POINTS[0], POINTS[0]))
    with pytest.raises(ValueError, match="duplicate effective"):
        _create(duplicate)
    case = _build(tmp_path / "ambiguous")
    data = case.review.to_dict()
    data["rows"].append(deepcopy(data["rows"][0]))
    with pytest.raises(ValueError, match="duplicate archive"):
        _create(case, review=ArchiveReview(Record.of(data)))


def test_explicit_choices_and_budget_are_required_without_fallback_or_truncation(tmp_path):
    case = _build(tmp_path)
    for choices in ({}, None, tuple(case.choices.items()), {"absent": next(iter(case.choices.values()))}):
        with pytest.raises(ValueError, match="choices|missing explicit"):
            _create(case, choices=choices)
    with pytest.raises(ValueError, match="within trial budget"):
        _create(case, budget=1)
    for budget in (True, 0, -1, 1.5, MAX_DONORS + 1):
        with pytest.raises(ValueError, match="budget"):
            _create(case, budget=budget)
    empty = ArchiveReview.empty(SECRET, case.access)
    with pytest.raises(ValueError, match="missing explicit"):
        _create(case, review=empty)
    for changes in (dict(researcher=""), dict(reason=" "), dict(geometry={"version": "fake"})):
        with pytest.raises((TypeError, ValueError)):
            _create(case, **changes)


def test_parameter_count_and_byte_limits_fail_without_truncation(tmp_path):
    many = {"axis" + str(i): i for i in range(MAX_PARAMS + 1)}
    case = _build(tmp_path / "many", points=(many,))
    with pytest.raises(ValueError, match="bounded nonempty"):
        _create(case)
    large = _build(tmp_path / "large", points=({**POINTS[0], "tag": "x" * (65 * 1024)},))
    with pytest.raises(ValueError, match="byte budget"):
        _create(large)


def test_revised_target_geometry_or_budget_requires_new_choice_and_parent_seal(tmp_path):
    case = _build(tmp_path)
    plan = _create(case)
    cases = (dict(target=replace(case.target, costs="revised-costs")),
        dict(geometry=replace(case.geometry, weights=(("period", 2.0),))), dict(budget=BUDGET + 1))
    for changes in cases:
        with pytest.raises(ValueError):
            ArchiveDonorPlan.from_json(plan.to_json(), **{**_current(case), **changes})


@pytest.mark.parametrize("corruption", ["params", "availability", "reason", "coordinate-ref", "archive-ref",
    "review-reason", "review-snapshot", "target-id", "geometry-id", "extra-score", "duplicate-row"])
def test_private_plan_tampering_is_rejected_including_after_reload(tmp_path, corruption):
    case = _build(tmp_path)
    data = _create(case).to_dict()
    if corruption == "params":
        data["warm_start"][0]["params"]["period"] = 4
    elif corruption == "availability":
        data["warm_start"][0]["available_at"] = pd.Timestamp(50, unit="ns", tz="UTC").isoformat()
    elif corruption == "reason":
        data["donors"][0]["reason"] = "skip fresh evaluation"
    elif corruption == "coordinate-ref":
        data["donors"][0]["coordinate_ref"] = case.catalog.ref("coordinates", "/points/1")
    elif corruption == "archive-ref":
        data["donors"][0]["archive_ref"] = case.catalog.ref("archive", "/entries/1")
    elif corruption == "review-reason":
        data["donors"][0]["review_reasons"] = ["invented"]
    elif corruption == "review-snapshot":
        data["review"]["rows"][0]["declared_inputs"]["evidence"]["candidate_id"] = "forged"
    elif corruption == "target-id":
        data["target_id"] = "b" * 64
    elif corruption == "geometry-id":
        data["geometry_id"] = "b" * 64
    elif corruption == "extra-score":
        data["warm_start"][0]["score"] = 9
    else:
        data["donors"][1] = deepcopy(data["donors"][0])
        data["warm_start"][1] = deepcopy(data["warm_start"][0])
    with pytest.raises((ValueError, PermissionError)):
        ArchiveDonorPlan.from_json(json.dumps(data), **_current(case))


def test_reload_bounds_duplicate_json_keys_and_disclosure_types_are_checked(tmp_path):
    case = _build(tmp_path)
    plan = _create(case)
    for limits in (dict(max_bytes=1), dict(max_donors=1), dict(max_bytes=True), dict(max_donors=0)):
        with pytest.raises(ValueError, match="bounded"):
            ArchiveDonorPlan.from_json(plan.to_json(), **_current(case), **limits)
    with pytest.raises(ValueError, match="duplicate JSON"):
        ArchiveDonorPlan.from_json('{"donors":[],"donors":[]}', **_current(case))
    with pytest.raises(ValueError, match="disclosure"):
        plan.to_dict(public=1)


def test_cold_construction_and_reload_do_not_rank_import_scores_or_consume_rng(tmp_path):
    case = _build(tmp_path)
    state, manifest = random.getstate(), case.catalog.manifest
    plan = _create(case)
    ArchiveDonorPlan.from_json(plan.to_json(), **_current(case))
    assert random.getstate() == state and case.catalog.manifest == manifest
    assert "old_objective_values" not in plan.to_json()
    tree = ast.parse(Path(donor_module.__file__).read_text(encoding="utf-8"))
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any("wfo_study" in name or "samplers" in name or "scores" in name or "finance" in name
                   for name in imports)
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"ask", "tell", "enqueue_trial", "backtest", "fit", "sampler", "suggest"}
