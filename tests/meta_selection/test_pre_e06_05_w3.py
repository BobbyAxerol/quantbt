"""The cost reader must retain W3's own params and reset-flat account contract."""

import pytest

from tools.qms_pre05_reference import baseline_blocks
from tools.qms_pre05_workloads import ROOT, Cell, execute, prepare, semantic


@pytest.mark.parametrize("mode", ("off", "shadow", "active"))
def test_actual_w3_full_work_reader_uses_typed_params_and_account(mode):
    cell = Cell("domain", "reactive_reset", mode)
    lane = ROOT / ".maturin/qms08/pre-e06-05"
    keys = []
    for optimized in (False, True):
        with baseline_blocks(optimized=optimized):
            prepared = prepare(cell, lane)
            result = execute(prepared, cell)
            key, work = semantic(result, cell, prepared[2])
            assert work["params"] == {
                str(k): dict(v) for k, v in result.params_by_fold.items()
            }
            assert work["reactive_contract"]["fold_table"]["values"]
            assert len(work["accounts"]) == len(result.fold_results)
            assert result.oos_output is None
            if mode != "off":
                meta = result.metadata["meta_selection"]
                assert meta["models"] and meta["records"][0]["matured_origins"] >= 12
                assert meta["observer_failures"] == 0
            keys.append(key)
    assert keys[0] == keys[1]
