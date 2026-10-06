"""Original package economics, exact observer binding and bounded route gates."""

from dataclasses import replace
from hashlib import sha256

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.schema import BasketExecutionPolicy
from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.domains import route_metadata
from quantbt.optimization.meta_selection.domains.package_contract import (
    package_execution_contract, validate_package_payload, update_package_witness)
from examples.wfo_meta_package import (SYMBOLS, PARAM_RANGES, market, strategy,
                                      make_endpoint, execute)


@pytest.fixture(scope="module", params=("basket", "basis", "stat_pair"))
def runs(request):
    return request.param, {mode: execute(mode, kind=request.param, support=1)
                          for mode in ("off", "shadow", "active")}


def side(result):
    return result.metadata["walk_forward"]["meta_selection"]


def accounts(a, b):
    for key in ("equity", "returns", "positions", "fees", "funding", "margin", "diagnostics"):
        np.testing.assert_array_equal(getattr(a, key), getattr(b, key))
    assert a.fills == b.fills


def test_e05_t01_off_shadow_exact_pool_objective_params_and_account(runs):
    _, rows = runs
    a, b = rows["off"][1], rows["shadow"][1]
    pd.testing.assert_frame_equal(a.metadata["walk_forward"]["trial_table"], b.metadata["walk_forward"]["trial_table"])
    assert a.metadata["walk_forward"]["params_by_fold"] == b.metadata["walk_forward"]["params_by_fold"]
    accounts(a, b)
    for mode in ("shadow", "active"):
        meta = side(rows[mode][1])
        adapter = meta["domain_adapter"]
        assert meta["observer_attempts"] > 0 and meta["observer_failures"] == 0
        assert adapter["financial_replays"] == 0 and adapter["closed"]
        assert adapter["metric_authority"] == "original_package_account_full_report"
        assert adapter["spread_proxy_metrics"] is adapter["empirical_promotion"] is False
        assert all(not r["current_outer_oos_used_for_selection"] for r in meta["records"])


def test_e05_t01_active_final_is_one_original_stitched_signal_account(runs):
    kind, rows = runs
    endpoint, result, _ = rows["active"]
    signal = result.metadata["walk_forward_result"].oos_output
    route = "basket" if kind == "basket" else "arbitrage"
    rebuilt = QuantBTEndpoint(replace(endpoint.config, mode=route)).backtest(data=market(), signal=signal)
    accounts(result, rebuilt)


def test_e05_t03_labels_equal_original_aggregate_reports_and_leg_reconciliation(runs):
    kind, rows = runs
    endpoint, result, context = rows["shadow"]
    cfg = replace(endpoint.config, mode="basket" if kind == "basket" else "arbitrage")
    task = side(result)["tasks"][0]
    candidate = task.candidates[0]
    train = pd.date_range(task.is_start, task.is_end, freq="D")
    data = market()
    signal = strategy(data, candidate.effective_params, train, train, None)
    original = QuantBTEndpoint(cfg).backtest(data={s: f.loc[train] for s, f in data.items()}, signal=signal)
    assert candidate.observation.raw_sharpe == original.full_report(trading_days=365, scope="full")["sharpe"]
    revision = next(r for r in context.history._revisions.values() if r.task.task_id == task.task_id)
    outcome = revision.outcomes[0]
    chosen = next(c for c in task.candidates if c.evaluation_id == outcome.evaluation_id)
    forward = pd.date_range(task.forward_start, task.forward_end, freq="D")
    signal = strategy(data, chosen.effective_params, train, forward, None)
    original = QuantBTEndpoint(cfg).backtest(data={s: f.loc[forward] for s, f in data.items()}, signal=signal)
    assert outcome.observation.raw_sharpe == original.full_report(trading_days=365, scope="full")["sharpe"]
    if kind != "basket":
        np.testing.assert_allclose(original.metadata["package_pnl_report"]["pnl_residual"], 0., atol=1e-9)


@pytest.mark.parametrize("kind", ["basket", "basis", "stat_pair"])
def test_e05_t06_prepared_prefix_witness_and_reference_are_exact(kind):
    a = execute("shadow", kind=kind, support=1)[1]
    b = execute("shadow", kind=kind, support=1, witness=False, cache=False)[1]
    accounts(a, b)
    pd.testing.assert_frame_equal(a.metadata["walk_forward"]["trial_table"], b.metadata["walk_forward"]["trial_table"])
    for x, y in zip(side(a)["tasks"], side(b)["tasks"], strict=True):
        assert replace(x, wall_generated_at=y.wall_generated_at) == y


@pytest.mark.parametrize("kind", ["basket", "basis", "stat_pair"])
def test_e05_t04_future_funding_market_mutation_does_not_change_first_selection(kind):
    data = market()
    index = data[SYMBOLS[0]].index
    rates = {s: pd.Series(.0001, index=index) for s in SYMBOLS}
    a = execute("active", kind=kind, support=1, use_funding=True, funding_rate=rates)[1]
    for s in SYMBOLS:
        data[s].loc[index >= "2021-04-01", ["open", "high", "low", "close", "volume"]] *= 2
    rates2 = {s: r.where(index < "2021-04-01", r*3) for s, r in rates.items()}
    b = execute("active", data=data, kind=kind, support=1, use_funding=True, funding_rate=rates2)[1]
    assert side(a)["tasks"][0].candidates == side(b)["tasks"][0].candidates
    for key in ("family_id", "selected_params", "selected_evaluation_id", "training_snapshot_id"):
        assert side(a)["records"][0][key] == side(b)["records"][0][key]


@pytest.mark.parametrize("knob", ["qty_step", "lot_size", "slot_size", "min_qty", "min_notional"])
def test_e05_t02_unthreaded_quantity_knobs_fail_before_optuna(knob, monkeypatch):
    import optuna
    calls = []
    monkeypatch.setattr(optuna, "create_study", lambda *a, **k: calls.append(True))
    with pytest.raises(MetaRecordError, match="quantity knobs"):
        execute("shadow", **{knob: .01})
    assert not calls


@pytest.mark.parametrize("change", ["atomic_basket", "dynamic", "margin_offset", "symbols", "scalar_rust", "backend"])
def test_e05_t02_unqualified_contracts_fail_closed(change):
    cfg = make_endpoint().config
    wf = cfg.walkforward_config
    if change == "atomic_basket": cfg = replace(cfg, basket=replace(cfg.basket, execution_policy=BasketExecutionPolicy.ALL_OR_NONE))
    if change == "dynamic": cfg = replace(cfg, basket=replace(cfg.basket, freeze_hedge=False))
    if change == "margin_offset": cfg = replace(cfg, basket=replace(cfg.basket, hedged_margin_offset=.1))
    if change == "symbols": cfg = replace(cfg, symbols=list(reversed(SYMBOLS)))
    if change == "scalar_rust": wf = replace(wf, metadata={**wf.metadata, "native_prepared_wfo": "require"})
    if change == "backend": cfg = replace(cfg, backend="native_vectorized")
    with pytest.raises(MetaRecordError): package_execution_contract(cfg, wf)


@pytest.mark.parametrize("change", ["missing", "async", "extra", "nan"])
def test_e05_t04_missing_or_async_tapes_are_not_silently_repaired(change, monkeypatch):
    import optuna
    calls = []
    monkeypatch.setattr(optuna, "create_study", lambda *a, **k: calls.append(True))
    data = market()
    if change == "missing": del data[SYMBOLS[1]]
    if change == "extra": data["EXTRA"] = data[SYMBOLS[0]]
    if change == "async": data[SYMBOLS[1]] = data[SYMBOLS[1]].iloc[1:]
    if change == "nan": data[SYMBOLS[1]].iloc[5, 0:4] = np.nan
    with pytest.raises(ValueError): execute("shadow", data=data)
    assert not calls


def test_e05_t04_spec_families_and_external_hedge_are_bound():
    ids = {package_execution_contract(make_endpoint(kind=k).config,
        make_endpoint(kind=k).config.walkforward_config).semantic_id for k in ("basket", "basis", "stat_pair")}
    assert len(ids) == 3
    cfg = make_endpoint("shadow", kind="stat_pair").config
    _, _, context = execute("shadow", kind="stat_pair")
    with pytest.raises(ValueError, match="external dynamic hedge"):
        QuantBTEndpoint(cfg).backtest(data=market(), param_ranges=PARAM_RANGES,
            hedge_ratios={s: market()[s].close for s in SYMBOLS}, meta_history=context)


@pytest.mark.parametrize("change", ["frame", "calendar", "nan"])
def test_e05_t01_signal_is_exact_typed_not_position_proxy(change):
    index = market()[SYMBOLS[0]].index[:3]
    values = pd.Series([0., 1., -1.], index=index)
    if change == "frame": values = values.to_frame()
    if change == "calendar": values = values.iloc[::-1]
    if change == "nan": values.iloc[1] = np.nan
    with pytest.raises(MetaRecordError): validate_package_payload(values, index)


def test_e05_t03_original_cost_buffer_changes_witness_but_missing_buffer_rejected(runs):
    _, rows = runs
    result = rows["off"][1]
    a, b = sha256(), sha256()
    update_package_witness(a, result)
    altered = replace(result, fees=result.fees+1)
    update_package_witness(b, altered)
    assert a.hexdigest() != b.hexdigest()
    with pytest.raises(MetaRecordError): update_package_witness(sha256(), replace(result, fees=None))


def test_e05_t01_capability_is_bounded_software_not_empirical_promotion():
    for route in ("basket", "arbitrage"):
        row = route_metadata(route)
        assert row["meta_route_activated"]
        assert row["meta_empirical_status"] == "REAL_PACKAGE_ALPHA_OWNER_REVIEW_PENDING"


@pytest.mark.parametrize("field", ["margin", "carry", "cost", "tick", "stat_qty", "hedge"])
def test_e05_t02_unmodeled_spec_contracts_are_not_silent_defaults(field):
    from quantbt.core.arbitrage import (MarginModel, MarginModelKind, CarryModel, CarryModelKind,
        CostModel, HedgePolicyKind)
    cfg = make_endpoint(kind="stat_pair").config
    spec = cfg.arbitrage_spec
    if field == "margin": spec = replace(spec, margin_model=MarginModel(MarginModelKind.HEDGED_OFFSET, .5))
    if field == "carry": spec = replace(spec, carry_model=CarryModel(CarryModelKind.BORROW, borrow_rate=.01))
    if field == "cost": spec = replace(spec, cost_model=CostModel(slippage_bps=1.))
    if field == "tick": spec = replace(spec, legs=(replace(spec.legs[0], tick_size=.01), spec.legs[1]))
    if field == "stat_qty": spec = replace(spec, legs=(replace(spec.legs[0], qty_step=.01), spec.legs[1]))
    if field == "hedge": spec = replace(spec, hedge_policy=replace(spec.hedge_policy, kind=HedgePolicyKind.BETA_NEUTRAL))
    with pytest.raises(MetaRecordError, match="unqualified"):
        package_execution_contract(replace(cfg, arbitrage_spec=spec), cfg.walkforward_config)


def test_e05_t06_exact_review_guard_rejects_any_unreviewed_adapter_byte():
    from tools.qms_e05_source_guard import ROOT, verify, without_e05_package
    assert verify()["financial_numeric_source_unchanged"]
    name = "src/quantbt/optimization/meta_selection/domains/package_contract.py"
    with pytest.raises(AssertionError, match="unreviewed"):
        without_e05_package((ROOT/name).read_bytes()+b"\n# unauthorized drift\n", name)


@pytest.mark.parametrize("kind", ["basket", "basis", "stat_pair"])
def test_e05_t03_constant_price_reversal_fees_slippage_funding_are_independent(kind):
    cfg = make_endpoint(kind=kind).config
    index = pd.date_range("2024-01-01", periods=5, freq="8h", tz="UTC")
    data = {s: pd.DataFrame({c: p for c in ("open", "high", "low", "close")}, index=index)
            for s, p in zip(SYMBOLS, (100., 50.))}
    route = "basket" if kind == "basket" else "arbitrage"
    rates = {s: pd.Series(.001, index=index) for s in SYMBOLS}
    endpoint = QuantBTEndpoint(replace(cfg, mode=route, use_funding=True, funding_rate=rates))
    result = endpoint.backtest(data=data, signal=pd.Series([0., 1., 1., -1., 0.], index=index))
    assert len(result.fills) > 0
    expected_fee, fill_pnl = {}, {}
    for fill in result.fills:
        assert fill.fee == pytest.approx(fill.qty*fill.price*.0005)
        expected_fee[fill.timestamp] = expected_fee.get(fill.timestamp, 0.)+fill.fee
        price = data[fill.symbol].loc[fill.timestamp, "close"]
        fill_pnl[fill.timestamp] = fill_pnl.get(fill.timestamp, 0.)+fill.signed_qty*(price-fill.price)
    np.testing.assert_allclose(result.fees, pd.Series(expected_fee).reindex(index, fill_value=0.))
    delta_equity = result.equity.diff().fillna(result.equity.iloc[0]-result.initial_capital)
    expected = pd.Series(fill_pnl).reindex(index, fill_value=0.)-result.fees-result.funding
    np.testing.assert_allclose(delta_equity, expected, atol=1e-9)
    # Frozen units do not drift while the signal is unchanged.
    np.testing.assert_array_equal(result.positions.iloc[1], result.positions.iloc[2])


@pytest.mark.parametrize("kind", ["basis", "stat_pair"])
def test_e05_t02_original_atomic_margin_rejection_retains_rejected_package_evidence(kind):
    from quantbt.core.schema import AccountConfig
    cfg = make_endpoint(kind=kind).config
    cfg = replace(cfg, mode="arbitrage", account=AccountConfig(initial_capital=10., leverage=1.))
    index = market()[SYMBOLS[0]].index[:5]
    result = QuantBTEndpoint(cfg).backtest(data={s: f.loc[index] for s, f in market().items()},
        signal=pd.Series([0., 1., 1., -1., 0.], index=index))
    assert not result.metadata["package_rejection_report"].empty
    assert not result.fills and (result.positions == 0).all().all()
    assert (result.equity == 10.).all() and result.fees.sum() == 0.
    update_package_witness(sha256(), result)
