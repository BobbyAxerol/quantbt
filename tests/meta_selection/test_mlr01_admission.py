"""MLR01-T01..04: freeze, availability, grouping and work-budget contracts."""

from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from tools.meta_model_research.admission import PUBLIC, read, verify_freeze
from tools.meta_model_research.protocol import (
    GRID, GROUPS, StudyProtocol, choose_recipe, macro_mean,
    permitted_calibration_rows, training_groups,
)


def test_frozen_baseline_source_and_settings():
    result = verify_freeze()
    assert result["source_files"] == 42 and result["receipts"] == 5
    changed = deepcopy(read(PUBLIC / "ridge_v1_freeze.json"))
    changed["ridge_settings"]["lambda_reg"] = 11
    with pytest.raises(ValueError, match="content/settings"):
        verify_freeze(manifest=changed)


def test_source_negative_copy(tmp_path):
    manifest = read(PUBLIC / "ridge_v1_freeze.json")
    from tools.meta_model_research.admission import ROOT
    for name in ("source_sha256", "existing_evidence_sha256"):
        for path in manifest[name]:
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / path).read_bytes())
    assert verify_freeze(root=tmp_path)["verified"]
    target = tmp_path / next(iter(manifest["source_sha256"]))
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="input changed"):
        verify_freeze(root=tmp_path)


def test_group_and_role_partition():
    p = StudyProtocol()
    assert len(p.acquisition_folds) == 13 and len(p.development_folds) == 12
    assert len(p.evaluation_folds) == 32
    for group in GROUPS:
        assert group not in training_groups(group)
        assert len(training_groups(group)) == 3
    with pytest.raises(ValueError):
        replace(p, min_matured_origins=1)
    with pytest.raises(ValueError):
        training_groups("sibling-unregistered")


def calibration_rows():
    return [dict(group=g, fold=fold, alpha=a, loss=1 + a / 100,
                 label_available_at="2023-12-01T00:00:00Z",
                 revision_available_at="2023-12-01T00:00:01Z")
            for g in GROUPS for fold in range(13, 25) for a in GRID]


def test_actual_availability_and_heldout_exclusion():
    rows = calibration_rows()
    cutoff = "2024-01-31T23:00:00Z"
    first = choose_recipe(rows, "A-SC", cutoff)
    mutated = deepcopy(rows)
    for r in mutated:
        if r["group"] == "A-SC":
            r["loss"] = 1e9
    mutated.append(dict(group="A-HMA", fold=24, alpha=.1, loss=-1e9,
                        label_available_at=cutoff, revision_available_at=cutoff))
    assert first == choose_recipe(mutated, "A-SC", cutoff)
    assert all(r["group"] != "A-SC" for r in permitted_calibration_rows(rows, "A-SC", cutoff))
    assert len(permitted_calibration_rows(mutated, "A-SC", cutoff)) == 3 * 12 * 6


def test_support_and_complete_blocks_cannot_be_faked_by_rows():
    rows = calibration_rows()
    assert choose_recipe(rows, "A-SC", "2024-01-31T23:00Z")["policy"] == "P2"
    rows = [r for r in rows if r["group"] != "A-VWAP" or r["fold"] == 13]
    result = choose_recipe(rows, "A-SC", "2024-01-31T23:00Z")
    assert result["policy"] == "P0" and result["alpha"] is None
    with pytest.raises(ValueError, match="duplicate"):
        choose_recipe(rows * 30, "A-SC", "2024-01-31T23:00Z")


def test_partial_blocks_are_not_intact_calibration_blocks():
    rows = [r for r in calibration_rows() if r["fold"] in (13, 16, 19, 22)]
    result = choose_recipe(rows, "A-SC", "2024-01-31T23:00Z")
    assert result["policy"] == "P0"
    assert result["reason"] == "CALIBRATION_BLOCK_SUPPORT_INSUFFICIENT"


def test_macro_group_not_candidate_row_weights():
    rows = [dict(group="a", loss=0.)] * 100 + [dict(group="b", loss=10.)]
    assert macro_mean(rows) == 5.
    assert macro_mean([dict(group="a", loss=None)]) is None
    with pytest.raises(ValueError, match="null"):
        macro_mean([dict(group="a", loss=float("nan"))])


def test_recipe_identity_restore_and_budget():
    p = StudyProtocol()
    assert p.max_fits == 4000 and p.max_cpu_seconds == 3600
    assert p.grid == GRID
    fields = json.loads(json.dumps(asdict(p)))
    for field in ("policies", "groups", "grid", "acquisition_folds", "development_folds", "evaluation_folds"):
        fields[field] = tuple(fields[field])
    assert StudyProtocol(**fields).protocol_id == p.protocol_id


def test_group_substitution_fails_before_reading_any_corpus():
    from tools.meta_model_research.admission import ROOTS, load_corpus
    swapped = dict(ROOTS, **{"A-SC": ROOTS["A-HMA"]})
    with pytest.raises(ValueError, match="substitution"):
        load_corpus("A-SC", roots=swapped)


def test_verified_bytes_and_size_budget(tmp_path):
    import gzip
    from hashlib import sha256
    from tools.meta_model_research.admission import read_verified
    path = tmp_path / "fixture.json.gz"
    raw = gzip.compress(b'{"value":"' + b"x" * 1000 + b'"}')
    path.write_bytes(raw)
    assert len(read_verified(path, expected_sha256=sha256(raw).hexdigest())["value"]) == 1000
    with pytest.raises(ValueError, match="hash/size"):
        read_verified(path, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="decoded"):
        read_verified(path, expected_sha256=sha256(raw).hexdigest(), max_bytes=100)
