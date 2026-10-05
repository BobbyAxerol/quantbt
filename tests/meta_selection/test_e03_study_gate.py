"""Study protocol and exact source negatives; no simulated promotion receipt."""

import json
from pathlib import Path

import pytest

from tools.qms_e03_source_guard import ALLOW, ROOT, verify, without_e03_scalar
from tools.qms_e03_study import CELLS, endpoint, read_registration


def test_e03_t06_exact_reviewed_source_never_exempts_entire_engine_or_adapter():
    assert verify()["financial_numeric_source_unchanged"]
    for name in ALLOW:
        with pytest.raises(AssertionError, match="unreviewed E03"):
            without_e03_scalar((ROOT/name).read_bytes()+b"\n# extra arithmetic\n", name)


def test_e03_t05_each_cell_is_distinct_not_a_proxy_or_synthetic_real_alpha():
    assert len(CELLS) == len(set(CELLS)) == 8
    source = (ROOT/"tools/qms_e03_study.py").read_text()
    assert '"simulated_causal_mean_reversion_ladder"' in source
    assert '"previously_research_exposed_not_locked_holdout"' in source
    assert '"NO_GAIN_OR_LOW_PRECISION_NOT_PROMOTED"' in source
    assert '"SIMULATED_STRATEGY_ONLY_NOT_REAL_ALPHA_PROMOTION"' in source


@pytest.mark.parametrize("target,backend", CELLS)
def test_e03_t05_registered_account_constructs_without_conflicting_slippage_forms(target, backend):
    registration = dict(scalar_allocation_quote=10000., scalar_qty_step=.001,
                        v2_slippage_bps=1., ladder_policy={}, split_start="2022-01-01")
    bt = endpoint(lambda **kw: None, target, backend, "active", registration, "off")
    assert bt.config.v2_fee_rate == .00025
    assert (bt.config.slippage if backend == "legacy" else bt.config.execution.slippage_rate) == .0001


def test_e03_t05_private_registration_cannot_claim_changed_trial_or_rng_protocol(tmp_path, monkeypatch):
    import tools.qms_e03_study as study
    monkeypatch.setattr(study, "private_path", lambda p: Path(p))
    row = dict(schema="qms-e03-registered-study-v1", attempts_per_fold=128, seed=731, minimum_origins=12)
    file = tmp_path/"e03-registration.json"
    file.write_text(json.dumps(row))
    assert read_registration(tmp_path)[0] == row
    for field in ("attempts_per_fold", "seed", "minimum_origins"):
        file.write_text(json.dumps({**row, field:0}))
        with pytest.raises(AssertionError):
            read_registration(tmp_path)
