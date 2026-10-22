"""ACC-01 F03/F04/F06/F15 synthetic public and prepared-route controls."""

from dataclasses import replace

import pandas as pd
import pytest

from quantbt import (
    AccountConfig, NativeOptionBackend, NativeOptionConfig, OptionExecutionConfig,
    OptionHedgeConfig, OptionInstrumentRegistry, OptionPackageIntent, OptionPackageLeg,
    OptionPreparedRunCache, OptionSettlementEvent, PremiumConvention, QuantBTEndpoint,
    execute_option_package, prepare_option_tape,
)
from quantbt.core.schema import OrderSide


@pytest.fixture
def market(option_phase3_chain, option_phase3_registry):
    symbol = "BTC-01FEB26-100000-C.DERIBIT"
    spec = option_phase3_registry.by_symbol[symbol]
    chain = option_phase3_chain.loc[option_phase3_chain["instrument_id"] == symbol].copy()
    return chain, OptionInstrumentRegistry.from_iterable([spec]), spec


def _package(spec, timestamp, *, name="entry", side=OrderSide.BUY, quantity=1.0):
    return OptionPackageIntent(timestamp_ns=timestamp, package_id=name, quantity=quantity,
                               legs=(OptionPackageLeg(spec.symbol, side, 1.0),))


def _config(**overrides):
    values = dict(account=AccountConfig(initial_capital=20_000.0), conversion_rates={"BTC": 100_000.0})
    values.update(overrides)
    return NativeOptionConfig(**values)


@pytest.mark.parametrize("balances", [None, {}, {"USD": 1_000.0}, {"USD": 500.0, "BTC": 0.005}, {"USD": 2_000.0, "BTC": -0.01}])
@pytest.mark.parametrize("route", ["direct", "tape", "cache", "endpoint"])
def test_f03_matching_opening_wallet_has_zero_return(market, balances, route):
    chain, registry, _ = market
    config = _config(account=AccountConfig(initial_capital=1_000.0), initial_balances=balances)
    kwargs = {}
    if route == "tape":
        kwargs["prepared_tape"] = prepare_option_tape(chain, registry)
    elif route == "cache":
        kwargs["prepared_cache"] = OptionPreparedRunCache.from_chain(chain, registry)
    if route == "endpoint":
        result = QuantBTEndpoint.options(option_config=config).backtest(chain=chain, instruments=registry)
    else:
        result = NativeOptionBackend(config).run(chain=chain, instruments=registry, **kwargs)
    assert result.equity.tolist() == [1_000.0] * len(result.equity)
    assert result.full_report()["total_return_pct"] == pytest.approx(0.0)
    assert result.metadata["opening_equity"] == pytest.approx(1_000.0)


@pytest.mark.parametrize("route", ["direct", "tape", "cache", "endpoint"])
def test_f03_mismatched_wallet_rejected_before_execution(market, route, monkeypatch):
    chain, registry, spec = market
    config = _config(initial_balances={"USD": 1_000.0})
    kwargs = {}
    if route == "tape":
        kwargs["prepared_tape"] = prepare_option_tape(chain, registry)
    elif route == "cache":
        kwargs["prepared_cache"] = OptionPreparedRunCache.from_chain(chain, registry)

    def must_not_execute(*args, **kwargs):
        raise AssertionError("opening wallet must be checked before option execution")

    monkeypatch.setattr("quantbt.backends.native_option.execute_option_package", must_not_execute)
    package = _package(spec, int(chain["timestamp_ns"].min()))
    with pytest.raises(ValueError, match="must match account.initial_capital"):
        if route == "endpoint":
            QuantBTEndpoint.options(option_config=config).backtest(chain=chain, instruments=registry, packages=[package])
        else:
            NativeOptionBackend(config).run(chain=chain, instruments=registry, packages=[package], **kwargs)


def test_f03_opening_tolerance_and_run_fx_override(market):
    chain, registry, _ = market
    backend = NativeOptionBackend(_config(initial_balances={"USD": 20_000.00000001}))
    result = backend.run(chain=chain, instruments=registry)
    assert result.metadata["opening_balance_tolerance"] == {"relative": 1e-10, "absolute": 1e-8}
    backend = NativeOptionBackend(_config(initial_balances={"BTC": 0.2}))
    with pytest.raises(ValueError, match="must match"):
        backend.run(chain=chain, instruments=registry, conversion_rates={"BTC": 50_000.0})


@pytest.mark.parametrize("hedged", [False, True])
@pytest.mark.parametrize("decision_offset", [0, 1_800_000_000_000])
def test_f04_f15_fee_currency_and_clock_follow_effective_event(market, hedged, decision_offset):
    chain, registry, spec = market
    quote = int(chain["timestamp_ns"].min())
    decision = quote + decision_offset
    result = NativeOptionBackend(_config(option_execution=OptionExecutionConfig(fee_rate=0.0001))).run(
        chain=chain, instruments=registry, packages=[_package(spec, decision)],
        hedge_policy=OptionHedgeConfig() if hedged else None,
    )
    event = pd.Timestamp(decision, unit="ns")
    row = result.fills_report.iloc[0]
    assert result.fills[0].timestamp == decision
    assert result.fills[0].metadata["quote_timestamp_ns"] == quote
    assert row["quote_timestamp_ns"] == quote
    assert row["decision_timestamp_ns"] == decision
    assert row["fee_conversion_timestamp_ns"] == decision
    assert row["applied_fee"] == pytest.approx(0.0000021)
    assert row["fee_currency"] == "BTC"
    assert row["fee_conversion_rate"] == 100_000.0
    assert row["fee_reporting_value"] == pytest.approx(0.21)
    assert result.fees.loc[event] == pytest.approx(0.21)
    assert result.fees.sum() == pytest.approx(0.21)
    assert result.fees.iloc[-1] == 0.0
    assert (result.positions.loc[result.positions.index < event] == 0.0).all().all()
    assert result.equity.loc[event] == pytest.approx(19_949.79)
    if decision_offset == 0 and not hedged:
        assert result.equity.index[0] == event
        assert result.returns.iloc[0] == pytest.approx(19_949.79 / 20_000.0 - 1.)
    ledger_event = result.metadata["ledger_event_report"].iloc[0]
    assert ledger_event["timestamp_ns"] == decision
    assert ledger_event["quote_timestamp_ns"] == quote
    reconciliation = result.metadata["accounting_reconciliation"]
    assert reconciliation["ledger_fee_reporting_value"] == pytest.approx(0.21)
    assert reconciliation["common_fee_reporting_value"] == pytest.approx(0.21)
    assert reconciliation["reconciled"] is True
    assert "not_full_account" in reconciliation["reconciliation_scope"]


def test_f15_hedge_cannot_backfill_future_underlying_prices(market):
    chain, registry, spec = market
    decision = int(chain.timestamp_ns.min())
    future = pd.Series([100_000.], index=pd.to_datetime([decision + 3_600_000_000_000], utc=True))
    with pytest.raises(ValueError, match="underlying prices"):
        NativeOptionBackend(_config()).run(chain=chain, instruments=registry,
            packages=[_package(spec, decision)], hedge_policy=OptionHedgeConfig(), underlying=future)


def test_f04_multiple_currencies_and_events_are_not_dumped_at_final_row(market):
    chain, _, spec = market
    linear = replace(spec, symbol="USD-C.TEST", premium_convention=PremiumConvention.LINEAR_QUOTE,
                     premium_currency="USD", settlement_currency="USD")
    linear_chain = chain.copy()
    linear_chain["instrument_id"] = linear.symbol
    linear_chain["settlement_currency"] = "USD"
    for field in ("bid_price", "ask_price", "mark_price", "last_price"):
        linear_chain[field] *= 1_000.0
    mixed = pd.concat([chain, linear_chain], ignore_index=True)
    registry = OptionInstrumentRegistry.from_iterable([spec, linear])
    first = int(chain["timestamp_ns"].min())
    second = first + 1_800_000_000_000
    result = NativeOptionBackend(_config(account=AccountConfig(initial_capital=100_000.0),
                                         option_execution=OptionExecutionConfig(fee_rate=0.0001))).run(
        chain=mixed, instruments=registry,
        packages=[_package(spec, first), _package(linear, second, name="linear")],
    )
    assert result.fees.loc[pd.Timestamp(first, unit="ns")] == pytest.approx(0.21)
    assert result.fees.loc[pd.Timestamp(second, unit="ns")] == pytest.approx(0.0021)
    assert result.fees.iloc[-1] == 0.0
    assert result.fees.sum() == pytest.approx(0.2121)
    assert result.metadata["accounting_reconciliation"]["reconciled"] is True


def test_f06_supported_option_buffer_still_controls_admission(market):
    chain, registry, spec = market
    package = _package(spec, int(chain["timestamp_ns"].min()))
    admitted = NativeOptionBackend(_config(account=AccountConfig(initial_capital=20_000.0, margin_buffer=2_000.0))).run(
        chain=chain, instruments=registry, packages=[package])
    rejected = NativeOptionBackend(_config(account=AccountConfig(initial_capital=20_000.0, margin_buffer=3_000.0))).run(
        chain=chain, instruments=registry, packages=[package])
    assert len(admitted.fills) == 1
    assert len(rejected.fills) == 0
    assert rejected.packages_report.iloc[0]["reject_reason"] == "POST_COST_MARGIN"
    assert admitted.metadata["effective_generic_config"]["nondefault_inactive_policy"] == "explicitly_rejected"


def test_f15_freshness_and_same_time_package_ordering(market):
    chain, registry, spec = market
    quote = int(chain["timestamp_ns"].min())
    decision = quote + 1_800_000_000_000
    tape = prepare_option_tape(chain, registry)
    with pytest.raises(ValueError, match="quote|stale|age"):
        execute_option_package(_package(spec, decision), tape, config=OptionExecutionConfig(max_quote_age_ns=1))
    packages = [_package(spec, decision, name="a-open"), _package(spec, decision, name="b-close", side=OrderSide.SELL)]
    result = NativeOptionBackend(_config(option_execution=OptionExecutionConfig(fee_rate=0.0001))).run(
        chain=chain, instruments=registry, packages=list(reversed(packages)))
    assert [fill.side for fill in result.fills] == [OrderSide.BUY, OrderSide.SELL]
    assert [fill.timestamp for fill in result.fills] == [decision, decision]
    assert result.positions.iloc[-1, 0] == 0.0
    assert result.fees.loc[pd.Timestamp(decision, unit="ns")] == pytest.approx(0.41)
    assert result.equity.iloc[-1] == pytest.approx(19_899.59)


def test_f03_f15_matching_capital_cache_replay_retains_effective_clocks(market):
    chain, registry, spec = market
    decision = int(chain["timestamp_ns"].min()) + 1_800_000_000_000
    backend = NativeOptionBackend(_config(initial_balances={"USD": 20_000.0}))
    package = _package(spec, decision)
    direct = backend.run(chain=chain, instruments=registry, packages=[package])
    cached = backend.run(chain=chain, instruments=registry, packages=[package],
                         prepared_cache=OptionPreparedRunCache.from_chain(chain, registry))
    assert direct.equity.equals(cached.equity)
    assert direct.fills_report.equals(cached.fills_report)
    assert direct.fees.equals(cached.fees)


def test_f13_f15_hedge_consumer_keeps_settlement_and_multiplier_cash(market):
    chain, _, original = market
    spec = replace(original, multiplier=2.0, contract_size=2.0)
    registry = OptionInstrumentRegistry.from_iterable([spec])
    package = _package(spec, int(chain["timestamp_ns"].min()) + 1_800_000_000_000)
    kwargs = dict(chain=chain, instruments=registry, packages=[package], settlement_events=[
        OptionSettlementEvent(symbol=spec.symbol, timestamp_ns=spec.expiry_ns, settlement_price=125_000.0)])
    backend = NativeOptionBackend(_config(account=AccountConfig(initial_capital=100_000.0),
                                          option_execution=OptionExecutionConfig(fee_rate=0.0001)))
    direct = backend.run(**kwargs)
    hedged = backend.run(**kwargs, hedge_policy=OptionHedgeConfig())
    assert hedged.option_equity.equals(direct.equity.rename("option_equity"))
    assert hedged.positions.equals(direct.positions)
    assert hedged.fees.equals(direct.fees)
    assert hedged.option_equity.iloc[-1] == pytest.approx(135_799.58)
    assert hedged.positions.iloc[-1, 0] == 0.0
    assert hedged.fees.sum() == pytest.approx(0.42)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0])
def test_f14_per_run_invalid_fx_rejects_before_execution(market, bad, monkeypatch):
    chain, registry, spec = market

    def must_not_execute(*args, **kwargs):
        raise AssertionError("FX must be validated before execution")

    monkeypatch.setattr("quantbt.backends.native_option.execute_option_package", must_not_execute)
    with pytest.raises(ValueError):
        NativeOptionBackend(_config()).run(chain=chain, instruments=registry,
            packages=[_package(spec, int(chain["timestamp_ns"].min()))], conversion_rates={"BTC": bad})
