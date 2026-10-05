"""E01-T01/T02: actual selection roles, including fixed and SBB selectors."""

from dataclasses import replace

import pytest

from quantbt import QuantBTEndpoint
from tools import qms01_baseline as baseline
from tools.qms_e01_source_guard import NAME, ROOT, without_e01_provenance, verify


@pytest.mark.parametrize("mode", ["mode_1_decay", "mode_2_sbb", "mode_3_flat_minima"])
@pytest.mark.parametrize("metric,uses_oos", [
    ("robust_decay", True), ("mean_oos_sharpe", True),
    ("mean_is_sharpe", False), ("is_plateau_robust", False),
])
def test_e01_t01_global_provenance_follows_actual_reranker(mode, metric, uses_oos):
    endpoint = baseline.endpoint(mode, "global")
    config = replace(endpoint.config.walkforward_config, candidate_selection_metric=metric)
    endpoint = QuantBTEndpoint(replace(endpoint.config, walkforward_config=config))
    result = endpoint.backtest(data=baseline.market(), param_ranges={"fast": (4, 8), "slow": (12, 20)})
    wf = result.metadata["walk_forward"]
    selected = wf["best_trial"]["selection_metadata"]
    assert selected["stage"] == "oos_candidate_selection"
    assert selected["selected_by"] == metric
    assert selected["oos_seen_by_optuna"] is False
    assert wf["oos_used_for_selection"] is uses_oos
    assert wf["chronological_validation_claim"] == "not_causal_multi_fold_global_calibration"


@pytest.mark.parametrize("mode", ["mode_1_decay", "mode_2_sbb", "mode_3_flat_minima"])
def test_e01_t01_fixed_params_diagnostics_are_not_selection(mode):
    result = baseline.endpoint(mode, "global").backtest(data=baseline.market(), params={"fast": 6, "slow": 16})
    wf = result.metadata["walk_forward"]
    assert wf["n_studies"] == 0
    assert wf["oos_used_for_selection"] is False
    assert wf["best_trial"]["params"] == {"fast": 6, "slow": 16}
    assert not wf["best_trial"].get("selection_metadata", {}).get("candidate_selection_complete", False)


def test_e01_t02_exact_reporting_allowance_rejects_other_source_changes():
    assert verify()["search_account_rng_source_exact"]
    source = (ROOT / NAME).read_bytes()
    without_e01_provenance(source, NAME)
    for tampered in (source + b"\n# unrelated arithmetic\n", source.replace(b'"mean_oos_sharpe"}', b'"mean_is_sharpe"}')):
        with pytest.raises(AssertionError, match="unapproved E01"):
            without_e01_provenance(tampered, NAME)
