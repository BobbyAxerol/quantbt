"""Actual C05 latent RNG/projection parity, with physical sampler time retained."""

import pytest

from tools.qms_pre05_reference import baseline_blocks
from tools.qms_pre05_workloads import ROOT, Cell, execute, prepare, semantic


@pytest.mark.parametrize(
    "mode,schedule",
    (("mode_4_is_only_robust", "per_fold_causal"), ("mode_5_full_robust", "global")),
)
def test_actual_conditional_sampler_work_rng_and_account_exact(mode, schedule):
    cell = Cell(
        "conditional",
        "pct_equity",
        optimization=mode,
        schedule=schedule,
        conditional=True,
    )
    keys = []
    for optimized in (False, True):
        with baseline_blocks(optimized=optimized):
            prepared = prepare(cell, ROOT / ".maturin/qms08/pre-e06-05")
            result = execute(prepared, cell)
            wf = result.metadata["walk_forward"]
            assert wf["sampler_studies"]
            assert all(s["sampler_wall_seconds"] >= 0 for s in wf["sampler_studies"])
            key, work = semantic(result, cell, prepared[2])
            assert work["sampler"] and work["accounts"] and work["trials"]
            assert all("sampler_wall_seconds" not in s for s in work["sampler"])
            keys.append(key)
    assert keys[0] == keys[1]
