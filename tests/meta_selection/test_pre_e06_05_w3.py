"""The cost reader must retain W3's own params and reset-flat account contract."""

import pytest

from tests.meta_selection import pre_e06_02_support as ordinary
from tools.qms_pre05_reference import baseline_blocks
from tools.qms_pre05_workloads import ROOT, Cell, execute, prepare, semantic


@pytest.fixture(scope="module")
def current_w3_history():
    # Stored PRE05 history certifies its original source, not today's runtime.
    historical = ordinary.run(
        "reactive_reset",
        data=ordinary.tape("reactive_reset", end="2022-05-31"),
        start="2020-04-01",
        numeric="require",
    )
    assert historical.context.history._revisions
    return historical.context.history


@pytest.mark.parametrize("mode", ("off", "shadow", "active"))
def test_actual_w3_full_work_reader_uses_typed_params_and_account(mode, current_w3_history):
    cell = Cell("domain", "reactive_reset", mode)
    lane = ROOT / ".maturin/qms08/pre-e06-05"
    keys = []
    results = []
    for optimized in (False, True):
        with baseline_blocks(optimized=optimized):
            prepared = prepare(cell, lane, frozen_history=current_w3_history)
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
                assert meta["models"] and meta["records"]
                assert all(r["matured_origins"] >= 12 for r in meta["records"])
                assert meta["observer_failures"] == 0
            keys.append(key)
            results.append(result)
    assert keys[0] == keys[1]
    assert results[0].params_by_fold == results[1].params_by_fold
    for baseline, optimized in zip(results[0].fold_results, results[1].fold_results, strict=True):
        ordinary.account_equal(baseline.result, optimized.result)
