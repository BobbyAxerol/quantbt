"""M5H-002/003/013: pure optional-archive admission, reload and disclosure."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import json
from pathlib import Path
import random

import pytest

from quantbt.diagnostics import archive as archive_module
from quantbt.diagnostics import archive_contracts
from quantbt.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.diagnostics.archive import ArchiveReview, LIMITATIONS
from quantbt.diagnostics.archive_contracts import (
    ArchiveEvidence, ArchiveIdentity, DependencyNode, DerivedReadback, IntendedReuse, assess_reuse,
)
from quantbt.diagnostics.identity import AnalysisKey, ExecutionKey
from quantbt.mode5.artifacts import file_identity, write_json
from quantbt.mode5.dossier.evidence import EvidenceCatalog, Source
from quantbt.mode5.dossier.records import Record, pointer
from tools.mode5_research.cross_mode import contracts as legacy


SECRET = "PRIVATE_ALPHA_PARAMETER_SOURCE_AND_CONTEXT"


def _evidence():
    execution = ExecutionKey(SECRET, "private-params", "market-v1", "flat-v1", "next-open-v1",
        "BTCUSDT-v1", "cost-v1", "funding-v1", "continuous-v1", "liquidate-v1", "history-v1", 17, "native-v1")
    identity = ArchiveIdentity(execution, AnalysisKey(execution.identity, "calendar-v1", "utility-v1", "ref-v1"),
        "schema-v1", "1h", "event-v1", 20, 40, "decimal_return")
    witness = AccessWitness("node-manifest", "development", 0, 40, 45)
    nodes = tuple(DependencyNode(kind, kind, witness, 20, 25, 60, 55, 1_000_000,
        deps, ("selection", "diagnostic"), "PREFIX_SAFE") for kind, deps in (
            ("source", ()), ("candidate", ("source",)), ("outcome", ("candidate",)), ("revision", ("outcome",))))
    return ArchiveEvidence(SECRET, identity, "private-candidate", "physical-execution", "account-state",
        "a" * 64, ("revision",), nodes, "COMPLETE", None, ("marks", "support"), ())


def _access(**changes):
    return replace(AccessPolicy("review-now", ("development",), ("source-manifest", "node-manifest"),
        100, "selection"), **changes)


def _catalog(tmp_path, evidence, *, source_witness=None):
    path = tmp_path / "archive.json"
    write_json(path, {"evidence": asdict(evidence), "other": {"private": SECRET}})
    content = file_identity(path)
    source = Source(SECRET, str(path), content["sha256"], content["bytes"],
        source_witness or AccessWitness("source-manifest", "development", 0, 40, 45))
    policy = _access(purpose="diagnostic", cutoff_ns=1000, roles=("development", "diagnostic_development"))
    return EvidenceCatalog((source,), policy)


def _intended(evidence, **changes):
    return replace(IntendedReuse(evidence.identity, "MODE5_CALIBRATION"), **changes)


def _review(evidence, catalog, *, intended=None, access=None):
    return ArchiveReview.assess(((evidence, intended or _intended(evidence), catalog.ref(SECRET, "/evidence")),),
        context_id=SECRET, access=access or _access(), catalog=catalog)


def _execution_target(identity, **changes):
    execution = replace(identity.execution, **changes)
    return replace(identity, execution=execution, analysis=replace(identity.analysis, execution=execution.identity))


@pytest.fixture
def retained(tmp_path):
    evidence = _evidence()
    return evidence, _catalog(tmp_path, evidence)


def test_empty_archive_is_usable_without_catalog_or_execution():
    review = ArchiveReview.empty(SECRET, _access())
    assert review.to_dict()["status"] == "NO_ARCHIVE"
    assert review.to_dict()["rows"] == []
    assert review.to_dict()["context_id"] == SECRET
    assert review.to_dict()["access_id"] == _access().identity
    assert review.verify(None, _access()) is review
    assert ArchiveReview.from_json(review.to_json(), catalog=None, access=_access()) == review
    assert review.to_dict(public=True) == dict(status="NO_ARCHIVE", status_counts={}, limitations=list(LIMITATIONS))


def test_exact_review_is_source_bound_and_keeps_all_declared_inputs(retained):
    evidence, catalog = retained
    review = _review(evidence, catalog)
    row, = review.to_dict()["rows"]
    assert row["evidence_id"] == evidence.evidence_id
    assert row["source_identity"] == row["target_identity"] == evidence.identity.identity
    assert row["disposition"] == "EXACT_REUSE"
    assert row["reasons"] == ["complete semantic metadata identity; accounting truth not certified"]
    assert row["missing_inputs"] == []
    assert row["ref"] == catalog.ref(SECRET, "/evidence")
    assert Record.of(row["declared_inputs"]) == Record.of(dict(evidence=asdict(evidence), intended=asdict(_intended(evidence))))
    assert review.verify(catalog, _access()) is review
    assert ArchiveReview.from_json(review.to_json(), catalog=catalog, access=_access()) == review
    rebound = ArchiveReview.assess(((evidence, _intended(evidence), row["ref"]),),
        context_id="another-context", access=_access(), catalog=catalog)
    assert rebound.identity != review.identity


def test_canonical_migration_preserves_compatibility_helpers():
    for name in ("ArchiveIdentity", "DependencyNode", "DerivedReadback", "ArchiveEvidence", "IntendedReuse",
                 "ReuseAssessment", "Disposition", "Status", "PURPOSES", "KINDS", "REQUIRED_KINDS",
                 "assess_reuse", "candidate_alias_key", "AccessPolicy", "AccessWitness", "AnalysisKey",
                 "ExecutionKey", "Fingerprint", "digest", "asdict", "dataclass", "Literal", "_graph", "_strings", "_text"):
        assert getattr(legacy, name) is getattr(archive_contracts, name)


@pytest.mark.parametrize("kind", ["wrong-evidence", "wrong-pointer", "wrong-hash", "extra-ref-field"])
def test_ref_must_bind_exact_evidence_not_just_a_source_hash(retained, kind):
    evidence, catalog = retained
    ref = catalog.ref(SECRET, "/evidence")
    if kind == "wrong-evidence":
        evidence = replace(evidence, candidate_id="forged-candidate")
    elif kind == "wrong-pointer":
        ref = catalog.ref(SECRET, "/other")
    elif kind == "wrong-hash":
        ref["sha256"] = "b" * 64
    else:
        ref["authority"] = "hash-only"
    with pytest.raises(ValueError):
        ArchiveReview.assess(((evidence, _intended(evidence), ref),), context_id=SECRET, access=_access(), catalog=catalog)


@pytest.mark.parametrize("field,value", [("alpha_code", "other-source"), ("market_snapshot", "other-market"),
    ("instrument", "ETHUSDT-v1"), ("clock", "other-clock"), ("costs", "other-costs")])
def test_wrong_target_context_keeps_original_incompatibility_reason(retained, field, value):
    evidence, catalog = retained
    target = _execution_target(evidence.identity, **{field: value})
    review = _review(evidence, catalog, intended=_intended(evidence, identity=target))
    row, = review.to_dict()["rows"]
    assert row["disposition"] == "INCOMPATIBLE"
    assert row["reasons"] == ["identity mismatch: execution." + field]


@pytest.mark.parametrize("field,value", [("parameter_schema", "other-schema"), ("timeframe", "4h"),
                                      ("metric_unit", "dollars")])
def test_schema_timeframe_and_metric_are_not_interchangeable(retained, field, value):
    evidence, catalog = retained
    target = replace(evidence.identity, **{field: value})
    row, = _review(evidence, catalog, intended=_intended(evidence, identity=target)).to_dict()["rows"]
    assert row["disposition"] == "INCOMPATIBLE"


def test_reset_fold_archive_cannot_supply_static_account_metrics(tmp_path):
    original = _evidence()
    evidence = replace(original, identity=_execution_target(original.identity, account="reset-each-fold"))
    catalog = _catalog(tmp_path, evidence)
    target = original.identity
    row, = _review(evidence, catalog, intended=_intended(evidence, identity=target)).to_dict()["rows"]
    assert row["disposition"] == "TARGETED_EXECUTION_REQUIRED"
    assert row["missing_inputs"] == ["execution:" + target.financial_identity]
    assert "paths cannot substitute" in row["reasons"][0]


@pytest.mark.parametrize("status", ["MISSING", "UNDEFINED", "FAILED", "PARTIAL_INTERRUPTED"])
def test_missing_archive_measurements_are_not_success_or_zero(tmp_path, status):
    evidence = replace(_evidence(), status=status, reason=SECRET)
    row, = _review(evidence, _catalog(tmp_path, evidence)).to_dict()["rows"]
    assert row["disposition"] == "TARGETED_EXECUTION_REQUIRED"
    assert row["missing_inputs"] == ["measurement:" + evidence.evidence_id]
    assert row["reasons"] == ["archive status " + status + ": " + SECRET]


@pytest.mark.parametrize("field,value", [("source_cutoff_ns", 101), ("proposal_available_ns", 100),
    ("revision_available_ns", 100), ("publication_ns", 101), ("proposal_available_ns", None)])
def test_late_or_unknown_dag_clock_preserves_canonical_rights_disposition(tmp_path, field, value):
    original = _evidence()
    evidence = replace(original, nodes=tuple(replace(n, **{field: value}) if n.kind == "candidate" else n
                                             for n in original.nodes))
    catalog = _catalog(tmp_path, evidence)
    row, = _review(evidence, catalog).to_dict()["rows"]
    expected = assess_reuse(evidence, _intended(evidence), _access())
    assert row["disposition"] == expected.disposition == "RIGHTS_FORBIDDEN"
    assert row["reasons"] == list(expected.reasons)
    assert row["missing_inputs"] == list(expected.missing_inputs)


def test_full_development_dag_is_not_backdated_to_a_prefix(tmp_path):
    original = _evidence()
    evidence = replace(original, nodes=tuple(replace(n, backdating="NOT_BACKDATABLE") if n.kind == "candidate" else n
                                             for n in original.nodes))
    row, = _review(evidence, _catalog(tmp_path, evidence), intended=_intended(evidence, mode="MODE4_PREFIX")).to_dict()["rows"]
    assert row["disposition"] == "RIGHTS_FORBIDDEN"
    assert any("NOT_BACKDATABLE" in reason for reason in row["reasons"])


def test_catalog_creation_policy_does_not_authorize_current_source_reads(tmp_path):
    evidence = _evidence()
    source_witness = AccessWitness("source-manifest", "diagnostic_development", 0, 40, 45)
    catalog = _catalog(tmp_path, evidence, source_witness=source_witness)
    with pytest.raises(PermissionError, match="role/manifest"):
        _review(evidence, catalog)


@pytest.mark.parametrize("disconnected", [False, True])
def test_all_dag_witnesses_need_current_rights_even_when_disconnected(tmp_path, disconnected):
    original = _evidence()
    forbidden = replace(original.nodes[0], node_id="forbidden-recipe", kind="recipe",
        witness=replace(original.nodes[0].witness, manifest_id="unapproved-manifest"))
    evidence = replace(original, nodes=original.nodes + (forbidden,),
        roots=original.roots if disconnected else original.roots + (forbidden.node_id,))
    catalog = _catalog(tmp_path, evidence)
    with pytest.raises(PermissionError, match="role/manifest"):
        _review(evidence, catalog)


@pytest.mark.parametrize("changes", [{"manifests": ("node-manifest",)}, {"manifests": ("source-manifest",)},
    {"roles": ("diagnostic_development",)}, {"cutoff_ns": 44}, {"cutoff_ns": 59}, {"purpose": "diagnostic"},
    {"policy_id": "different-policy"}])
def test_reload_and_verify_recheck_narrower_or_changed_access(retained, changes):
    evidence, catalog = retained
    review = _review(evidence, catalog)
    access = _access(**changes)
    with pytest.raises(PermissionError):
        review.verify(catalog, access)
    with pytest.raises(PermissionError):
        ArchiveReview.from_json(review.to_json(), catalog=catalog, access=access)


def test_same_source_hash_does_not_allow_relabelled_source_witness(retained):
    evidence, catalog = retained
    review = _review(evidence, catalog)
    source, = catalog._sources.values()
    denied_source = replace(source, witness=replace(source.witness, role="diagnostic_development"))
    denied_catalog = EvidenceCatalog((denied_source,), catalog.policy)
    assert denied_catalog.ref(SECRET, "/evidence") == catalog.ref(SECRET, "/evidence")
    with pytest.raises(PermissionError):
        review.verify(denied_catalog, _access())
    changed_source = replace(source, witness=replace(source.witness, ready_ns=44))
    changed_catalog = EvidenceCatalog((changed_source,), catalog.policy)
    with pytest.raises(ValueError, match="source-bound"):
        review.verify(changed_catalog, _access())


def test_source_file_mutation_invalidates_snapshot_assessment_verify_and_reload(retained):
    evidence, catalog = retained
    review = _review(evidence, catalog)
    source, = catalog._sources.values()
    Path(source.path).write_text('{"changed":"private"}', encoding="utf-8")
    for operation in (lambda: _review(evidence, catalog), lambda: review.verify(catalog, _access()),
                      lambda: ArchiveReview.from_json(review.to_json(), catalog=catalog, access=_access())):
        with pytest.raises(ValueError, match="source changed"):
            operation()


def test_reload_reconstructs_typed_readbacks_and_canonical_tuples(tmp_path, monkeypatch):
    original = _evidence()
    target = replace(original.identity, analysis=replace(original.identity.analysis, metric_statistics="tail-v2"))
    evidence = replace(original, readbacks=(DerivedReadback(target, ("marks",), SECRET),))
    catalog = _catalog(tmp_path, evidence)
    intended = _intended(evidence, identity=target, required_inputs=("support",))
    review = _review(evidence, catalog, intended=intended)
    observed = []
    def inspect_inputs(restored, request, access):
        assert isinstance(restored, ArchiveEvidence) and isinstance(request, IntendedReuse)
        assert type(restored.nodes) is tuple and type(restored.roots) is tuple
        assert type(restored.retained_inputs) is tuple and type(restored.readbacks) is tuple
        assert isinstance(restored.readbacks[0], DerivedReadback)
        assert isinstance(restored.identity.execution, ExecutionKey)
        assert isinstance(restored.identity.analysis, AnalysisKey)
        assert isinstance(restored.nodes[0].witness, AccessWitness)
        assert type(restored.nodes[0].dependencies) is tuple and type(restored.nodes[0].purposes) is tuple
        assert type(request.required_inputs) is tuple and type(restored.readbacks[0].required_inputs) is tuple
        observed.append(restored)
        return assess_reuse(restored, request, access)
    monkeypatch.setattr(archive_module, "assess_reuse", inspect_inputs)
    assert ArchiveReview.from_json(review.to_json(), catalog=catalog, access=_access()) == review
    assert observed and all(item == evidence for item in observed)
    assert review.to_dict()["rows"][0]["disposition"] == "DERIVED_READBACK_ALLOWED"


@pytest.mark.parametrize("field,value", [("disposition", "DERIVED_READBACK_ALLOWED"), ("reasons", ["forged permission"]),
    ("missing_inputs", ["invented"]), ("source_identity", "forged"), ("target_identity", "forged"),
    ("evidence_id", "forged")])
def test_rehashing_disposition_or_summary_is_not_verification(retained, field, value):
    evidence, catalog = retained
    review = _review(evidence, catalog)
    data = review.to_dict()
    data["rows"][0][field] = value
    forged = Record.of(data)
    assert forged.identity != review.identity
    with pytest.raises(ValueError, match="declared assessment inputs"):
        ArchiveReview.from_json(forged.payload, catalog=catalog, access=_access())


def test_well_typed_rehashed_evidence_still_must_match_current_exact_source(retained):
    evidence, catalog = retained
    data = _review(evidence, catalog).to_dict()
    data["rows"][0]["declared_inputs"]["evidence"]["candidate_id"] = "forged-candidate"
    forged = ArchiveReview(Record.of(data))
    with pytest.raises(ValueError, match="exactly match"):
        forged.verify(catalog, _access())
    with pytest.raises(ValueError, match="exactly match"):
        ArchiveReview.from_json(forged.to_json(), catalog=catalog, access=_access())


@pytest.mark.parametrize("path", ["", "/access_policy", "/rows/0", "/rows/0/declared_inputs",
    "/rows/0/declared_inputs/evidence", "/rows/0/declared_inputs/intended",
    "/rows/0/declared_inputs/evidence/identity", "/rows/0/declared_inputs/evidence/identity/execution",
    "/rows/0/declared_inputs/evidence/identity/analysis", "/rows/0/declared_inputs/evidence/nodes/0",
    "/rows/0/declared_inputs/evidence/nodes/0/witness"])
def test_reload_rejects_unknown_contract_fields_at_every_level(retained, path):
    evidence, catalog = retained
    data = _review(evidence, catalog).to_dict()
    pointer(data, path)["unknown"] = SECRET
    with pytest.raises(ValueError):
        ArchiveReview.from_json(json.dumps(data), catalog=catalog, access=_access())


@pytest.mark.parametrize("path,key,value", [
    ("/rows/0/declared_inputs/evidence/identity/execution", "scenario_seed", True),
    ("/rows/0/declared_inputs/evidence/nodes/0/witness", "start_ns", False),
    ("/rows/0/declared_inputs/evidence/nodes/0/witness", "manifest_id", 123),
    ("/rows/0/declared_inputs/evidence/nodes/0", "dependencies", "source"),
    ("/rows/0/declared_inputs/evidence", "retained_inputs", {"marks": True}),
    ("/rows/0/declared_inputs/intended", "required_inputs", "marks"),
])
def test_reload_rejects_wrong_types_instead_of_coercing_contracts(retained, path, key, value):
    evidence, catalog = retained
    data = _review(evidence, catalog).to_dict()
    pointer(data, path)[key] = value
    with pytest.raises(ValueError):
        ArchiveReview.from_json(json.dumps(data), catalog=catalog, access=_access())


def test_private_roundtrip_is_immutable_and_public_output_is_allowlisted(retained):
    evidence, catalog = retained
    review = _review(evidence, catalog)
    clone = deepcopy(review)
    clone.to_dict()["rows"][0]["declared_inputs"]["evidence"]["retained_inputs"].clear()
    assert clone == review
    with pytest.raises(FrozenInstanceError):
        review.record = Record.of({})
    public = review.to_dict(public=True)
    assert public == dict(status="REVIEWED", status_counts={"EXACT_REUSE": 1}, limitations=list(LIMITATIONS))
    assert SECRET not in review.to_json(public=True)
    assert all(token not in public for token in ("context_id", "access_id", "rows", "ref", "declared_inputs"))
    with pytest.raises(ValueError):
        ArchiveReview.from_json(review.to_json(public=True), catalog=catalog, access=_access())


def test_row_byte_and_input_bounds_fail_without_truncation(retained):
    evidence, catalog = retained
    entry = (evidence, _intended(evidence), catalog.ref(SECRET, "/evidence"))
    with pytest.raises(ValueError, match="no rows truncated"):
        ArchiveReview.assess((entry, entry), context_id=SECRET, access=_access(), catalog=catalog, max_rows=1)
    with pytest.raises(ValueError, match="immutable"):
        ArchiveReview.assess([entry], context_id=SECRET, access=_access(), catalog=catalog)
    with pytest.raises(TypeError, match="typed"):
        ArchiveReview.assess((list(entry),), context_id=SECRET, access=_access(), catalog=catalog)
    with pytest.raises(TypeError, match="EvidenceCatalog"):
        ArchiveReview.assess((entry,), context_id=SECRET, access=_access(), catalog=None)
    review = _review(evidence, catalog)
    with pytest.raises(ValueError, match="bounded"):
        ArchiveReview.from_json(review.to_json(), catalog=catalog, access=_access(), max_bytes=1)
    for invalid in (0, -1, True):
        with pytest.raises(ValueError, match="positive exact"):
            ArchiveReview.from_json(review.to_json(), catalog=catalog, access=_access(), max_rows=invalid)
    with pytest.raises(ValueError, match="duplicate JSON"):
        ArchiveReview.from_json('{"rows":[],"rows":[]}', catalog=catalog, access=_access())
    for context_id in ("", " ", 123):
        with pytest.raises(ValueError, match="nonempty"):
            ArchiveReview.empty(context_id, _access())


def test_cold_review_has_no_finance_reducer_sampler_imports_or_rng_consumption(retained):
    evidence, catalog = retained
    state = random.getstate()
    before = catalog.manifest.payload
    review = _review(evidence, catalog)
    review.verify(catalog, _access())
    ArchiveReview.from_json(review.to_json(), catalog=catalog, access=_access())
    assert random.getstate() == state and catalog.manifest.payload == before
    tree = ast.parse(Path(archive_module.__file__).read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imports == {"dataclasses", "types", "typing", "quantbt.mode5.dossier.evidence",
                       "quantbt.mode5.dossier.records", "access", "archive_contracts"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"eval", "exec", "__import__", "open"} for node in ast.walk(tree))
