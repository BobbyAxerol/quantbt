"""Reviewed static calibration rights never become causal warm-start rights."""
from dataclasses import replace

import pandas as pd
import pytest

from quantbt.core.wfo_contracts import strategy_fingerprint
from quantbt.mode5 import Mode5Calibration
from quantbt.mode5.diagnostics.access import AccessPolicy
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.plans import CalibrationPlan
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from public_fixtures import public_setup, alpha


def setup(tmp_path):
    ranges = {"period": (6, 24, 1)}
    warm = ({"params": {"period": 10}, "available_at": "2026-01-01T00:00:00Z",
        "space_identity": NormalizedSearchSpace(ranges).identity, "strategy_identity": strategy_fingerprint(alpha)},)
    endpoint, frame, _, original = public_setup(tmp_path, ranges=ranges, trials=1, warm_start=warm)
    access = AccessPolicy("retrospective-2026", original.access.roles, original.access.manifests,
        int(pd.Timestamp("2026-10-10",tz="UTC").value), "selection")
    specification = {**original.plan.record.data["recipe"], "search_budget": 1}
    from dataclasses import asdict
    specification["reuse"]["selection_policy"] = asdict(access)
    plan = CalibrationPlan.search(original.dossier, specification, "sealed reviewed full-sample calibration, not causal")
    journal = GovernanceLog(tmp_path / "retrospective-journal")
    journal.seal_dossier(original.dossier, original.catalog)
    journal.seal_plan(original.dossier, plan, original.catalog, researcher="test author", reason=plan.record.data["reason"])
    calibration = Mode5Calibration(original.dossier, plan, original.catalog, journal, original.binding)
    endpoint.config = replace(endpoint.config, walkforward_config=replace(endpoint.config.walkforward_config,
        mode5_calibration=calibration))
    return endpoint, frame, ranges


def test_reviewed_coordinates_use_explicit_selection_clock_not_market_end(tmp_path):
    endpoint, frame, ranges = setup(tmp_path)
    result = endpoint.backtest(data=frame, param_ranges=ranges)
    metadata = result.metadata["walk_forward"]
    assert metadata["validation_claim"] == "none_full_sample_calibration"
    assert metadata["mode5_diagnostics_first"]["selected_params_digest"]
    assert metadata["mode5_diagnostics_first"]["trial_ledger"][0]["effective_params"] == {"period": 10}
    sampler = metadata["mode5_diagnostics_first"]["sampler"]
    assert sampler["cutoff_authority"] == "sealed_mode5_selection_policy"
    assert pd.Timestamp(sampler["is_cutoff"]).year == 2023
    assert pd.Timestamp(sampler["warm_start_cutoff"]).year == 2026


def test_unsealed_legacy_mode5_keeps_historical_is_cutoff(tmp_path):
    endpoint, frame, ranges = setup(tmp_path)
    endpoint.config = replace(endpoint.config, walkforward_config=replace(endpoint.config.walkforward_config,
        mode5_calibration=None))
    with pytest.raises(ValueError, match="before the IS cutoff|rights differ from sealed binding"):
        endpoint.backtest(data=frame, param_ranges=ranges)


def test_coordinate_after_sealed_selection_clock_is_rejected(tmp_path):
    endpoint, frame, ranges = setup(tmp_path)
    cfg = endpoint.config.walkforward_config
    warm = ({**cfg.sampler_warm_start[0], "available_at": "2027-01-01T00:00:00Z"},)
    endpoint.config = replace(endpoint.config, walkforward_config=replace(cfg, sampler_warm_start=warm))
    with pytest.raises(ValueError, match="rights differ from sealed binding"):
        endpoint.backtest(data=frame, param_ranges=ranges)


def test_mode4_causal_schedule_keeps_historical_coordinate_rights(tmp_path):
    endpoint, frame, ranges = setup(tmp_path)
    cfg = endpoint.config.walkforward_config
    cfg = replace(cfg, mode5_calibration=None, optimization_mode="mode_4_is_only_robust",
        optimization_schedule="per_fold_causal", candidate_selection_metric="is_only_robust")
    from types import SimpleNamespace
    from quantbt.optimization.wfo_study import prepare_wfo_studies
    with pytest.raises(ValueError, match="before the IS cutoff"):
        prepare_wfo_studies(cfg, ranges, [(0, (SimpleNamespace(train_end=frame.index[-1]),))],
            strategy_identity=strategy_fingerprint(alpha), derive_seed=lambda seed, study: seed)
