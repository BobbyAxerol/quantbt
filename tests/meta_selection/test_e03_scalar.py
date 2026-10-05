"""E03 independent sizing expectations and actual original public WFO evidence."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from examples.wfo_meta_selection import market
from examples.wfo_meta_scalar import execute_scalar, make_scalar_endpoint
from quantbt import QuantBTEndpoint, walkforward_support_matrix
from quantbt.optimization.meta_selection.domains import capability, route_metadata
from quantbt.optimization.meta_selection.domains.scalar_contract import scalar_execution_contract


CELLS = [(r, "native_vectorized") for r in ("signal_notional", "notional", "unit")]
CELLS += [(r, "native_event") for r in ("signal_notional", "notional", "unit")]
CELLS += [("pct_equity", "legacy"), ("dca_ladder", "legacy")]


def meta(result):
    return result.metadata["walk_forward"]["meta_selection"]


@pytest.mark.parametrize("alias,canonical", [("single_signal", "signal_notional"), ("%_equity", "pct_equity")])
def test_e03_t01_aliases_share_canonical_finance_and_family(alias, canonical):
    _, a, _ = execute_scalar(alias, support=1)
    _, b, _ = execute_scalar(canonical, support=1)
    np.testing.assert_array_equal(a.equity, b.equity)
    assert [t.family.family_id for t in meta(a)["tasks"]] == [t.family.family_id for t in meta(b)["tasks"]]
    assert capability(alias) == capability(canonical)


@pytest.mark.parametrize("target", ["notional", "unit", "dca_ladder"])
def test_e03_t01_software_opt_in_is_not_empirical_promotion(target):
    row = route_metadata(target)
    assert row["meta_software_status"] == "SOFTWARE_VALIDATED_OPT_IN"
    assert row["meta_empirical_status"] == "OWNER_EMPIRICAL_REVIEW_PENDING"
    assert row["meta_route_activated"]
    assert row["meta_optimization_schedules"] == ("per_fold_causal",)
    assert len(walkforward_support_matrix(False)) == 9


@pytest.mark.parametrize("target,backend", CELLS)
def test_e03_t04_omitted_off_shadow_exact_search_rng_and_continuous_account(target, backend):
    bt = make_scalar_endpoint(target, backend, "off")
    assert bt.config.walkforward_config.meta_selection is None
    _, off, _ = execute_scalar(target, backend, "off")
    _, shadow, _ = execute_scalar(target, backend, "shadow", support=1)
    a, b = (r.metadata["walk_forward"] for r in (off, shadow))
    assert a["params_by_fold"] == b["params_by_fold"]
    pd.testing.assert_frame_equal(a["trial_table"], b["trial_table"])
    for name in ("equity", "returns", "positions"):
        np.testing.assert_array_equal(getattr(off, name), getattr(shadow, name))
    side = meta(shadow)
    assert side["observer_failures"] == 0
    assert side["domain_adapter"]["financial_replays"] == 0
    assert side["domain_adapter"]["empirical_promotion"] is False
    assert all(not row["current_outer_oos_used_for_selection"] for row in side["records"])
    assert all(row["selected_evaluation_id"] == row["native_selected_evaluation_id"] for row in side["records"])
    # Existing account rebuild is the authority, not concatenated fold equities.
    stitched = shadow.metadata["walk_forward_result"].oos_output
    diagnostic = QuantBTEndpoint(replace(bt.config, mode="single_signal"))
    actual = diagnostic.backtest(data=market(), signal=stitched)
    np.testing.assert_array_equal(actual.equity, shadow.equity)


@pytest.mark.parametrize("target", ["notional", "unit", "dca_ladder"])
def test_e03_t04_future_mutation_does_not_change_first_pool_or_decision(target):
    _, a, _ = execute_scalar(target, mode="active", support=1)
    changed = market()
    changed.loc[changed.index >= "2021-04-01", ["open", "high", "low", "close"]] *= 1.4
    _, b, _ = execute_scalar(target, mode="active", support=1, data=changed)
    ta, tb = (meta(r)["tasks"][0] for r in (a, b))
    assert ta.candidates == tb.candidates
    for key in ("selected_params", "selected_evaluation_id", "native_selected_evaluation_id", "training_snapshot_id"):
        assert meta(a)["records"][0][key] == meta(b)["records"][0][key]


@pytest.mark.parametrize("target,backend", [("unit", "native_event"), ("dca_ladder", "legacy")])
def test_e03_t01_guard_conflicting_sizing_cost_or_timing_before_optuna(target, backend, monkeypatch):
    import optuna
    calls = []
    monkeypatch.setattr(optuna, "create_study", lambda *a, **k: calls.append(True))
    bt = make_scalar_endpoint(target, backend)
    for changes, pattern in ((dict(sizing="notional"), "SIZING_MISMATCH"),
                             (dict(walkforward_config=replace(bt.config.walkforward_config,
                               metadata={**bt.config.walkforward_config.metadata, "native_prepared_wfo": "require"})), "META_ROUTE_UNSUPPORTED")):
        with pytest.raises(ValueError, match=pattern):
            scalar_execution_contract(replace(bt.config, **changes), changes.get("walkforward_config", bt.config.walkforward_config))
    if target == "dca_ladder":
        with pytest.raises(ValueError, match="ECONOMICS_MISMATCH"):
            scalar_execution_contract(replace(bt.config, fee_rate=.0007), bt.config.walkforward_config)
    assert not calls


def test_e03_t01_legacy_meta_off_proxy_defaults_are_preserved():
    for target in ("notional", "unit"):
        bt = QuantBTEndpoint.walk_forward(strategy_class=lambda **kw: None, target_mode=target)
        assert bt.config.walkforward_config.scoring_backend == "proxy"


@pytest.mark.parametrize("target", ["signal_notional", "notional", "unit"])
def test_e03_t04_existing_legacy_scalar_compatibility_is_not_cross_backend_empirical_evidence(target):
    _, off, _ = execute_scalar(target, "legacy", "off")
    _, shadow, _ = execute_scalar(target, "legacy", "shadow", support=1)
    assert off.metadata["walk_forward"]["params_by_fold"] == shadow.metadata["walk_forward"]["params_by_fold"]
    pd.testing.assert_frame_equal(off.metadata["walk_forward"]["trial_table"], shadow.metadata["walk_forward"]["trial_table"])
    for name in ("equity", "returns", "positions"):
        np.testing.assert_array_equal(getattr(off, name), getattr(shadow, name))
    witness = meta(shadow)
    assert witness["observer_failures"] == 0
    assert witness["domain_adapter"]["empirical_promotion"] is False
    assert witness["domain_adapter"]["scalar_execution"]["backend"] == "legacy"
    _, native, _ = execute_scalar(target, "native_vectorized", "shadow", support=1)
    assert meta(native)["tasks"][0].family.family_id != witness["tasks"][0].family.family_id


def test_e03_t03_ladder_actual_high_low_required_not_close_proxy():
    with pytest.raises(ValueError, match="actual high/low"):
        execute_scalar("dca_ladder", data=market().drop(columns=["high", "low"]))


def test_e03_t03_ladder_family_isolates_limits_and_backend():
    _, a, _ = execute_scalar("dca_ladder", support=1)
    bt = make_scalar_endpoint("dca_ladder")
    bt = QuantBTEndpoint(replace(bt.config, dca_kwargs={**bt.config.dca_kwargs, "dca_step_pct": .03}))
    from examples.wfo_meta_selection import PARAM_RANGES
    from tests.meta_selection.test_qms06_prepared import context
    b = bt.backtest(data=market(), param_ranges=PARAM_RANGES, meta_history=context())
    assert meta(a)["tasks"][0].family.family_id != meta(b)["tasks"][0].family.family_id


def short_market(close):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(dict(open=close, high=close, low=close, close=close),
                        index=pd.date_range("2024-01-01", periods=len(close), tz="UTC"))


@pytest.mark.parametrize("sizing,units", [
    ("notional", [0., 10., 1000/110, -1000/90, 0.]),
    ("unit", [0., 10., 10., -10., 0.]),
    ("signal_notional", [0., 10., 10., -1000/90, 0.])])
@pytest.mark.parametrize("slip", [0., .0002])
@pytest.mark.parametrize("backend", ["native_vectorized", "native_event"])
def test_e03_t02_independent_accepted_delta_pnl_fee_slippage_and_turnover(sizing, units, slip, backend):
    frame = short_market([100., 100., 110., 90., 100.])
    signal = pd.Series([0., 1., 1., -1., 0.], index=frame.index)
    base = QuantBTEndpoint.signal_notional(initial_capital=20000., alloc_per_trade=1000.,
        leverage=3., fee_rate=.001, slippage_bps=slip*10000, use_funding=False, backend=backend)
    result = QuantBTEndpoint(replace(base.config, mode="single_signal", sizing=sizing)).backtest(data=frame, signal=signal)
    units = np.asarray(units)
    delta = np.diff(units, prepend=0.)
    price = frame.close.to_numpy()
    execution = price * (1 + np.sign(delta)*slip)
    fees = np.abs(delta)*execution*.001
    costs = np.abs(delta)*price*slip
    mtm = np.roll(units, 1)*np.diff(price, prepend=price[0])
    expected = 20000 + np.cumsum(mtm-fees-costs)
    np.testing.assert_allclose(result.positions.iloc[:, 0], units, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.fees, fees, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result.equity, expected, rtol=1e-12, atol=1e-10)
    np.testing.assert_allclose(result.margin.iloc[:, 0], np.abs(units)*price/3., atol=1e-10)


@pytest.mark.parametrize("constraints", [dict(min_qty=20.), dict(min_notional=2000.), dict(qty_step=3.)])
def test_e03_t02_quantity_and_minimums_use_original_financial_gate(constraints):
    frame = short_market([100., 100., 100.])
    signal = pd.Series([0., 1., 1.], index=frame.index)
    base = QuantBTEndpoint.signal_notional(initial_capital=20000., alloc_per_trade=1000.,
        leverage=3., fee_rate=.001, use_funding=False, **constraints)
    result = QuantBTEndpoint(replace(base.config, mode="single_signal", sizing="unit")).backtest(data=frame, signal=signal)
    units = 9. if "qty_step" in constraints else 0.
    np.testing.assert_array_equal(result.positions.iloc[:, 0], [0., units, units])
    assert result.equity.iloc[-1] == 20000-units*.1


def test_e03_t02_leverage_margin_reject_and_liquidation_not_allocation_multiplier():
    frame = short_market([100., 100., 100.])
    signal = pd.Series([0., 1., 1.], index=frame.index)
    accepted = []
    for leverage in (1., 3.):
        base = QuantBTEndpoint.signal_notional(initial_capital=20000., alloc_per_trade=1000.,
            leverage=leverage, fee_rate=.001, use_funding=False)
        accepted.append(QuantBTEndpoint(replace(base.config, sizing="unit")).backtest(data=frame, signal=signal))
    np.testing.assert_array_equal(accepted[0].positions, accepted[1].positions)
    rejected = QuantBTEndpoint(replace(base.config, account=replace(base.config.account, leverage=1., initial_capital=1000.)))
    result = rejected.backtest(data=frame, signal=signal)
    assert np.count_nonzero(result.positions.to_numpy()) == 0  # Cost makes 1000 notional unaffordable.
    frame.loc[frame.index[-1], ["low", "close"]] = [1., 80.]
    risky = QuantBTEndpoint(replace(base.config, account=replace(base.config.account, leverage=20., initial_capital=100.)))
    result = risky.backtest(data=frame, signal=signal)
    assert result.liquidated and result.equity.iloc[-1] == 0.


@pytest.mark.parametrize("direction", [1., -1.])
def test_e03_t03_ladder_limits_manual_quantity_cost_and_same_close_exit(direction):
    frame = short_market([100.]*5)
    if direction > 0:
        frame["low"] = [100., 100., 89., 79., 100.]
        triggers = [90., 80.]
    else:
        frame["high"] = [100., 100., 111., 121., 100.]
        triggers = [110., 120.]
    base = QuantBTEndpoint.dca_ladder(initial_capital=20000., leverage=3., fee=.002,
        slippage=0., use_funding=False, qty_step=.000001,
        dca_base_notional=1000., dca_safety_notional=1000., dca_step_pct=.1,
        dca_max_safety_orders=2, dca_take_profit_pct=0.)
    result = base.backtest(data=frame, signal=pd.Series([0., 3*direction, 3*direction, 3*direction, 0.], index=frame.index))
    additions = [np.floor(1000/p/.000001)*.000001 for p in triggers]
    units = np.array([0., 10., 10+additions[0], 10+sum(additions), 0.])*direction
    np.testing.assert_allclose(result.positions.iloc[:, 0], units, atol=1e-8, rtol=0.)
    gains = sum(direction*q*(100-p) for q, p in zip(additions, triggers))
    fees = (1000 + sum(q*p for q, p in zip(additions, triggers)) + abs(units[3])*100)*.001
    assert result.equity.iloc[-1] == pytest.approx(20000+gains-fees, abs=1e-8)


def test_e03_t03_ladder_fractional_target_rejected_before_financial_delegate():
    from quantbt.optimization.meta_selection.domains.scalar_contract import validate_scalar_payload
    index = market().index[:3]
    with pytest.raises(ValueError, match="integer structural caps"):
        validate_scalar_payload(pd.Series([0., 2.5, 0.], index=index), index, "dca_ladder")


def test_e03_t02_funding_on_carried_units_and_original_fee_contract():
    frame = short_market([100., 100., 110., 90., 100.])
    frame.index = pd.date_range("2024-01-01", periods=5, freq="8h", tz="UTC")
    signal = pd.Series([0., 1., 1., -1., 0.], index=frame.index)
    base = QuantBTEndpoint.signal_notional(initial_capital=20000., alloc_per_trade=1000.,
        leverage=3., fee_rate=.001, use_funding=True, funding_rate=.001)
    result = QuantBTEndpoint(replace(base.config, mode="single_signal", sizing="unit")).backtest(data=frame, signal=signal)
    np.testing.assert_allclose(result.funding, [0., 0., 1.1, .9, -1.])
    np.testing.assert_allclose(result.equity, [20000., 19999., 20097.9, 19895.2, 19795.2])


def test_e03_t03_ladder_existing_limit_tp_precedes_flat_close_no_entry_bar_tp():
    frame = short_market([100.]*3)
    frame["high"] = [100., 120., 110.1]
    bt = QuantBTEndpoint.dca_ladder(initial_capital=20000., leverage=3., fee=.002,
        slippage=0., use_funding=False, dca_base_notional=1000.,
        dca_max_safety_orders=0, dca_take_profit_pct=.1, dca_allow_same_bar_exit=False)
    result = bt.backtest(data=frame, signal=pd.Series([0., 1., 0.], index=frame.index))
    np.testing.assert_array_equal(result.positions.iloc[:, 0], [0., 10., 0.])
    assert result.equity.iloc[-1] == pytest.approx(20097.9)


@pytest.mark.parametrize("target", ["notional", "unit"])
def test_e03_t04_prepared_original_pool_selection_and_final_account_parity(target):
    from tests.meta_selection.test_qms06_prepared import assert_pools
    _, ordinary, _ = execute_scalar(target, mode="active", support=1, runtime="rust")
    _, prepared, _ = execute_scalar(target, mode="active", support=1, prepared="require", runtime="rust")
    assert_pools(ordinary, prepared)
    np.testing.assert_allclose(ordinary.equity, prepared.equity, atol=1e-9, rtol=1e-10)
