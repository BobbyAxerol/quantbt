"""Cost evidence cannot change scientific execution or overwrite receipts."""

from types import MappingProxyType

import pytest

from quantbt.optimization.meta_selection import common, witness
from tools.qms_pre05_benchmark import write_once
from tools.qms_pre05_reference import baseline_blocks
from tools.qms_pre05_workloads import cells


def test_registered_matrix_includes_five_modes_and_all_cost_arms():
    matrix = cells()
    assert len(matrix) == 76
    assert len({cell.identity for cell in matrix}) == 76
    assert {c.optimization for c in matrix} == {
        "mode_1_decay",
        "mode_2_sbb",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    }
    assert sum(c.mode == "off" for c in matrix) == 32
    assert sum(c.mode == "active" for c in matrix) == 22
    assert sum(c.mode == "shadow" for c in matrix) == 22


def test_reference_restores_aliases_and_owner_after_exception():
    import quantbt.optimization.meta_selection.runtime as runtime

    before = (
        common.wire,
        common.digest,
        runtime.digest,
        witness.PreparedMetricWitness.__init__,
    )
    with pytest.raises(RuntimeError, match="deliberate"):
        with baseline_blocks() as hashes:
            assert len(hashes) == 2
            assert common.wire is not before[0]
            assert common.digest is runtime.digest
            assert common.canonical(MappingProxyType({"x": [1, 2]})) == '{"x":[1,2]}'
            raise RuntimeError("deliberate")
    assert before == (
        common.wire,
        common.digest,
        runtime.digest,
        witness.PreparedMetricWitness.__init__,
    )


def test_evidence_serializes_before_creation_and_refuses_overwrite(tmp_path):
    path = tmp_path / "receipt.json"
    with pytest.raises(TypeError):
        write_once(path, {"invalid": object()})
    assert not path.exists()
    write_once(path, {"value": 1})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_once(path, {"value": 2})
    assert path.read_bytes() == before
