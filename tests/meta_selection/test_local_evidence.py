"""Independent economic decomposition and fail-closed artifact comparison."""

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from tools.qms_local_evidence import economics
from tools.qms08_gate import ROOT, verify_pair


def pair():
    return dict(native=dict(status="VALID", is_sharpe=3., forward_sharpe=-1.),
                meta=dict(status="VALID", is_sharpe=1., forward_sharpe=.5))


def test_report_separates_lower_is_from_better_forward():
    result = economics([pair()])
    assert result["native_decay"] == 4.
    assert result["meta_decay"] == .5
    assert result["r"] == 3.5
    assert result["q"] == 1.5
    assert result["is_difference"] == 2.
    assert result["decay_reduction_pct"] == 87.5


def test_invalid_pairs_are_not_fabricated_zero():
    invalid = deepcopy(pair())
    invalid["meta"] = dict(status="UNDEFINED", is_sharpe=None, forward_sharpe=None)
    result = economics([pair(), invalid])
    assert result["valid_folds"] == result["invalid_folds"] == 1
    assert economics([invalid])["r"] is None


def test_nonfinite_valid_pair_fails():
    row = pair()
    row["meta"]["forward_sharpe"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        economics([row])


def test_negative_reference_decay_has_no_misleading_percent_improvement():
    row = pair()
    row["native"]["forward_sharpe"] = 4.
    result = economics([row])
    assert result["decay_reduction_pct"] is None
    assert result["r"] < 0 and result["q"] < 0


def current_proof():
    path = Path(os.environ.get("QMS08_PACKAGE_PROOF",
        ROOT / ".maturin/qms08/local-closure-v1/cp312/proof.json"))
    return json.loads(path.read_text())


def test_followup_wheel_requires_current_source_and_actual_hashes():
    proof = current_proof()
    assert verify_pair(proof)
    with pytest.raises(ValueError, match="drift|changed"):
        verify_pair(proof, source_revision="6c0f877")


@pytest.mark.parametrize("mutation", ["artifact", "consumer", "source", "release"])
def test_followup_artifact_receipt_tampering_fails(mutation):
    proof = deepcopy(current_proof())
    if mutation == "artifact":
        proof["artifact_refs"][0]["sha256"] = "0" * 64
    elif mutation == "consumer":
        proof["consumers"]["pair"]["off_shadow_parity"] = False
    elif mutation == "source":
        proof["stage_differences"].setdefault("src/quantbt/__init__.py", {})["source"] = "0" * 64
    else:
        proof["release_authorized"] = True
    with pytest.raises(ValueError):
        verify_pair(proof)
