"""Phase 77.1 public-workload and legacy percent-equity baseline locks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.native_event import benchmark_phase77_1_public_matrix as phase77_1


def _governance_module():
    path = ROOT / "tools" / "check_benchmark_governance.py"
    specification = importlib.util.spec_from_file_location("phase77_1_governance", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_phase77_1_manifest_declares_all_five_modes_and_non_promotional_scope() -> None:
    payload = json.loads(phase77_1.MANIFEST_PATH.read_text(encoding="utf-8"))

    assert payload["schema"] == "quantbt-phase77-1-public-workload-manifest-v1"
    assert payload["promotion_eligible"] is False
    assert payload["profiles"]["standard"] == {
        "bars": 10_000,
        "frequency": "1h",
        "split_mode": "2020-07-01",
        "split_frequency": "quarterly",
        "train_window": "180D",
        "trials": 64,
        "repeats": 5,
        "rows": ["mode1_global_w0_native_eligible"],
        "paired_order": "alternating_reference_native",
    }
    required = payload["required_mode_schedule_matrix"]
    assert set(required) == {
        "mode_1_decay",
        "mode_2_sbb",
        "mode_3_flat_minima",
        "mode_4_is_only_robust",
        "mode_5_full_robust",
    }
    rows = {row.identifier: row for row in phase77_1.PUBLIC_ROWS}
    assert rows["mode2_global_proxy_preserved"].expected_resolution == "proxy_preserved"
    assert rows["pct_equity_auto_fallback"].expected_resolution == "fallback"
    assert rows["mode4_per_fold_causal_w0_native_eligible"].schedule == "per_fold_causal"
    assert {entry["route"] for entry in phase77_1.SEPARATE_SCOPE_EVIDENCE} == {
        "reactive_w3",
        "direct_target_vectorized",
        "shared_account_portfolio",
        "bounded_package",
    }

    governance = _governance_module()
    assert governance.validate_manifest(phase77_1.MANIFEST_PATH) == []


def test_phase77_1_pct_equity_transition_contract_is_hand_computable() -> None:
    probe = phase77_1.pct_equity_transition_probe()

    assert probe["contract_id"] == "legacy_pct_equity_transition_sizing_v1"
    assert probe["entry_hold_reversal_equity"] == [10_000.0, 10_000.0, 11_000.0, 11_000.0, 10_450.0]
    assert probe["expected_entry_hold_reversal_equity"] == probe["entry_hold_reversal_equity"]
    assert probe["first_bar_is_snapshot"] is True
    assert probe["funding_on_carried_position"] is True
    assert probe["rejected_unchanged_signal_is_not_retried"] is True
    assert probe["alloc_fraction_and_percent_alias_match"] is True
    assert probe["reported_positions_are_raw_weights"] is True


def test_phase77_1_long_profile_is_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="allow_long"):
        phase77_1.run(profile="long")


def test_phase77_1_standard_profile_has_a_bounded_real_calendar_fold_plan() -> None:
    spec = phase77_1.PROFILE_SPECS["standard"]
    data = phase77_1._market(int(spec["bars"]), frequency=str(spec["frequency"]))
    data.attrs.update(
        {
            "phase77_1_frequency": str(spec["frequency"]),
            "phase77_1_split_mode": str(spec["split_mode"]),
            "phase77_1_split_frequency": str(spec["split_frequency"]),
            "phase77_1_train_window": str(spec["train_window"]),
        }
    )
    row = next(item for item in phase77_1.PUBLIC_ROWS if item.identifier == "mode1_global_w0_native_eligible")
    result, _ = phase77_1._run_endpoint(
        row,
        data,
        native_policy="off",
        trials=0,
        profile=False,
        params={"amplitude": 0.8, "period": 13},
    )
    assert result.metadata["walk_forward"]["n_folds"] == 3


@pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="public prepared-native measurement needs the optional native wheel",
)
def test_phase77_1_native_and_proxy_rows_record_truthful_public_resolution() -> None:
    native = phase77_1.run(
        profile="smoke",
        include_rows=["mode4_per_fold_causal_w0_native_eligible"],
    )
    native_row = native["rows"][0]
    assert native_row["status"] == "measured_pair_parity_passed"
    assert native_row["native"]["resolved_native_prepared_policy"] == "native_prepared"
    assert native_row["native"]["native_score_rows"] > 0
    assert native_row["native"]["oos_used_for_selection"] is False
    assert native_row["reference"]["fingerprint"] == native_row["native"]["fingerprint"]

    proxy = phase77_1.run(profile="smoke", include_rows=["mode2_global_proxy_preserved"])
    proxy_row = proxy["rows"][0]
    assert proxy_row["status"] == "measured_unpaired_contract_route"
    assert proxy_row["observed"]["resolved_native_prepared_policy"] == "proxy_preserved"
    assert proxy_row["observed"]["native_score_rows"] == 0
