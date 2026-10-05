"""Independent proposed-ledger examples; no carry/shared-account runtime claim."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_phase76_reactive_wfo import _bars, _endpoint, _config, _ReactiveFactory


@pytest.mark.parametrize("meta", [None, "shadow", "active"])
@pytest.mark.parametrize("change", ["carry", "multi_symbol", "async_frames"])
def test_c02_t06_account_preflight_before_strategy_or_native_work(meta, change, monkeypatch):
    data = _bars()
    endpoint = _endpoint(data)
    config = replace(_config(mode="mode_4_is_only_robust"), optimization_schedule="per_fold_causal",
        optuna_trials=8,
        calendar_contract="exact_v2", strategy_lifecycle_policy="isolated_v1", scoring_backend="endpoint",
        meta_selection=dict(mode=meta, native_batch_policy="reference") if meta else None)

    def forbidden(*args, **kwargs):
        raise AssertionError("unsupported accounting reached execution/preparation")

    monkeypatch.setattr(endpoint, "prepare_native_event_strategy", forbidden)
    monkeypatch.setattr(_ReactiveFactory, "prepare_reactive_wfo", forbidden)
    symbols = ["BTC"]
    if change == "carry":
        config = replace(config, fold_account_policy="carry_position", fold_boundary_position_policy="carry")
    elif change == "multi_symbol":
        symbols.append("ETH")
    else:
        data = {"BTC": data, "ETH": data.iloc[::2]}
    with pytest.raises((ValueError, NotImplementedError), match="META_|single-symbol|carry|DataFrame"):
        endpoint.prepare_reactive_walk_forward(data=data, strategy_factory=_ReactiveFactory(),
                                              walkforward_config=config, symbols=symbols)


def test_c02_t07_carry_does_not_reset_resize_charge_or_compound():
    capital, qty, entry, leverage = 20_000., 1., 100., 3.
    fee = abs(qty) * entry * .0004
    funding = qty * entry * .0001
    equity = capital + qty * (120. - entry) - fee - funding
    assert equity == pytest.approx(20_019.95)
    assert abs(qty * 120.) / leverage == 40.
    assert equity - 40. == pytest.approx(19_979.95)
    delta_qty = qty - qty
    assert abs(delta_qty * 120.) == 0.
    assert abs(delta_qty * 120.) * .0004 == 0.
    assert capital + qty * (80. - entry) - fee - funding == pytest.approx(19_979.95)


def test_c02_t07_shared_account_pnl_funding_margin_reconcile():
    capital = 1_000.
    units, entries, marks = (2., -1.), (100., 200.), (110., 190.)
    fees = sum(abs(q * p) * .0004 for q, p in zip(units, entries, strict=True))
    funding = sum(q * p * .0001 for q, p in zip(units, marks, strict=True))
    pnl = sum(q * (mark - entry) for q, entry, mark in zip(units, entries, marks, strict=True))
    equity = capital + pnl - fees - funding
    gross = sum(abs(q * p) for q, p in zip(units, marks, strict=True))
    net = sum(q * p for q, p in zip(units, marks, strict=True))
    assert pnl == 30. and fees == pytest.approx(.16) and funding == pytest.approx(.003)
    assert equity == pytest.approx(1029.837)
    assert (gross, net) == (410., 30.)
    assert gross / 3. == pytest.approx(136.6666666667)
    assert equity - gross / 3. == pytest.approx(893.1703333333)
    observed_calendar = {"A": (1, 2, 3), "B": (1, 3)}
    assert 2 not in observed_calendar["B"]  # No trade on A's fresh timestamp with stale B.


def test_c02_t07_proposals_not_activated_or_certified():
    text = Path("docs/meta_selection/W3_TRANSPORT_AND_ACCOUNT_CONTRACTS.md").read_text()
    for required in ("qms-w3-continuous-carry-v1-proposed", "qms-w3-shared-account-multisymbol-v1-proposed",
                     "preserve_positions_and_orders", "Activation: **false**", "Runtime unsupported",
                     "not activated capabilities", "different** account/calendar"):
        assert required in text
