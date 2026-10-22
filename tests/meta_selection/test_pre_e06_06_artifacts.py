"""Independent failure cases for local artifact gates, not financial relaxations."""

from copy import deepcopy
from hashlib import sha256
import json
import subprocess
import tarfile
from io import BytesIO
import zipfile

import pytest

from tools import qms_pre06_contract as gate


def row():
    return dict(mode="active", semantic_sha256="exact", expected_sha256="exact",
                models=1, minimum_origins=12, observer_failures=0, skipped=0)


def test_complete_matrix():
    gate.validate_matrix({"a": row()}, {"a": "exact"})


@pytest.mark.parametrize("change", [{"models": 0}, {"minimum_origins": 11},
    {"semantic_sha256": "different"}, {"observer_failures": 1}, {"skipped": 1}])
def test_actual_fit_parity_and_skip_required(change):
    value = row()
    value.update(change)
    with pytest.raises(ValueError):
        gate.validate_matrix({"a": value}, {"a": "exact"})


@pytest.mark.parametrize("records", [{}, {"a": row(), "extra": row()}])
def test_missing_or_extra_cell(records):
    with pytest.raises(ValueError):
        gate.validate_matrix(records, {"a": "exact"})


def test_receipts_are_write_once(tmp_path):
    path = tmp_path / "receipt.json"
    gate.write_once(path, {"status": "FAILED"})
    with pytest.raises(FileExistsError):
        gate.write_once(path, {"status": "PASS"})
    assert json.loads(path.read_text()) == {"status": "FAILED"}


def test_exact_source_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    (tmp_path / "source.py").write_bytes(b"original")
    gate.checked_hashes({"source.py": sha256(b"original").hexdigest()})
    with pytest.raises(ValueError, match="drift"):
        gate.checked_hashes({"source.py": sha256(b"changed").hexdigest()})


@pytest.mark.parametrize("members", [
    {"quantbt/a.py": b"changed", "quantbt/py.typed": b""},
    {"quantbt/a.py": b"a"},
    {"quantbt/a.py": b"a", "quantbt/py.typed": b"", "private/alpha.py": b"alpha"},
    {"quantbt/a.py": b"a", "quantbt/py.typed": b"", "quantbt/extra.py": b"extra"},
])
def test_wheel_missing_drift_extra_and_private(tmp_path, members):
    path = tmp_path / "quantbt_engine-1.1.2-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    with pytest.raises(ValueError):
        gate.artifact_source(path, {"a.py": sha256(b"a").hexdigest(), "py.typed": sha256(b"").hexdigest()})


def test_sdist_strict_allowlist(tmp_path):
    path = tmp_path / "quantbt_engine-1.1.2.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("quantbt_engine-1.1.2/alpha_strategy.py")
        member.size = 1
        archive.addfile(member, BytesIO(b"a"))
    with pytest.raises(ValueError, match="non-core"):
        gate.artifact_source(path, {})


@pytest.mark.parametrize("path", ["../source", ".", "package-v1/stage", "package-v1/dist", "package-v1"])
def test_cleanup_rejects_unreviewed_paths(path):
    with pytest.raises(ValueError, match="unreviewed"):
        gate.cleanup_path(path)


def test_cleanup_rejects_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "LANE", tmp_path)
    target = tmp_path / "package-v1"
    target.mkdir()
    (target / "build-env").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        gate.cleanup_path("package-v1/build-env")


def test_predecessor_seals_and_owner_exception():
    prior_name, owner_name = (
        path.relative_to(gate.ROOT).as_posix() for path in (gate.PRE05, gate.OWNER)
    )
    receipts = {}
    for path in (gate.PRE05, gate.OWNER):
        name = path.relative_to(gate.ROOT).as_posix()
        original = subprocess.check_output(
            ["git", "show", f"{gate.ENTRY}:{name}"], cwd=gate.ROOT
        )
        assert path.read_bytes() == original
        receipts[name] = sha256(original).hexdigest()
    prior = json.loads(gate.PRE05.read_bytes())
    owner = json.loads(gate.OWNER.read_bytes())
    assert prior["schema"] == "qms-pre-e06-05-local-v1"
    assert prior["status"] == "PASS_LOCAL_PARITY_COST_DISPOSITION_OPEN"
    assert prior["full_semantic_parity"] is True
    assert prior["source_guard"]["publication"] is False
    assert owner["schema"] == "qms-pre-e06-05-owner-cost-disposition-v1"
    assert owner["status"] == "COMPLETE_LOCAL_OWNER_ACCEPTED_COST_EXCEPTION"
    assert owner["original_budget_pct"] == {"p50": 3, "p95": 5}
    assert owner["original_disabled_not_met"] == len(owner["accepted_exceptions"]) == 7
    assert owner["correctness_rng_accounting_tolerances_waived"] is False
    assert owner["inheritance_to_other_sources_or_workloads"] is False
    assert owner["guide_sha256"] == prior["guide_sha256"]
    assert owner["sealed_evidence_sha256"][prior_name] == receipts[prior_name]
    gate.checked_hashes(owner["sealed_evidence_sha256"])
    predecessor = json.loads((gate.ROOT / (
        "benchmarks/optimization/meta_selection/qms_pre_e06_06_closure.json"
    )).read_bytes())
    assert predecessor["source"]["predecessor_sha256"] == receipts[prior_name]
    assert predecessor["source"]["owner_sha256"] == receipts[owner_name]
    assert predecessor["owner_cost_acceptance_sha256"] == receipts[owner_name]


def test_old_pre06_builder_cannot_certify_current_source():
    from tests.meta_selection.current_source_assertions import current_source_rejects_historical_certificate
    from tools import qms_pre05_source_guard as legacyguard

    current_source_rejects_historical_certificate(legacyguard.verify)
    for historical in (False, True):
        with pytest.raises(AssertionError):
            gate.prerequisites(historical=historical)


def test_native_reuse_requires_exact_hash(tmp_path):
    path = tmp_path / "wrong.whl"
    path.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="identity"):
        gate.native_reuse(path)


def test_matrix_is_independent_of_status_word():
    value = deepcopy(row())
    value.update(status="PASS", models=0)
    with pytest.raises(ValueError, match="cold"):
        gate.validate_matrix({"a": value}, {"a": "exact"})


def test_cannot_self_attest_a_changed_reference():
    value = row()
    value.update(semantic_sha256="wrong", expected_sha256="wrong")
    with pytest.raises(ValueError, match="parity"):
        gate.validate_matrix({"a": value}, {"a": "exact"})


def test_checkout_module_origin_rejected():
    import quantbt
    from tools.qms_pre06_consumer import origins
    assert quantbt.__file__
    with pytest.raises(ValueError, match="substitution"):
        origins(gate.ROOT / ".maturin/not-installed/quantbt")


def test_installed_identity_rejects_checkout():
    from tools.qms_pre06_consumer import identity
    with pytest.raises(ValueError, match="noninstalled"):
        identity({})
