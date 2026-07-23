from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    NativeOptionBackend,
    NativeOptionConfig,
    OptionPackageIntent,
    OptionPackageLeg,
    OptionPreparedRunCache,
    OrderSide,
    QuantBTEndpoint,
    prepare_option_tape,
)


def test_phase10_prepared_cache_replay_matches_uncached(option_phase3_chain, option_phase3_registry):
    package = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="cache-long-call",
        legs=(OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", OrderSide.BUY, 1.0),),
    )
    cfg = NativeOptionConfig(
        initial_balances={"USD": 20_000.0},
        conversion_rates={"BTC": 100_000.0},
        reporting_currency="USD",
    )
    backend = NativeOptionBackend(cfg)
    cache = OptionPreparedRunCache.from_chain(option_phase3_chain, option_phase3_registry)

    uncached = backend.run(chain=option_phase3_chain, instruments=option_phase3_registry, packages=[package])
    cached = backend.run(
        chain=option_phase3_chain,
        instruments=option_phase3_registry,
        packages=[package],
        prepared_cache=cache,
    )

    assert cached.equity.equals(uncached.equity)
    assert cached.positions.equals(uncached.positions)
    assert cached.fills_report.equals(uncached.fills_report)
    assert cached.run_manifest["fidelity_manifest"]["prepared_cache_used"] is True
    assert cache.package_cache_size == 1
    cache.compile_package(package)
    assert cache.package_cache_size == 1


def test_phase10_endpoint_accepts_prepared_option_cache(option_phase3_chain, option_phase3_registry):
    package = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="endpoint-cache",
        legs=(OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", OrderSide.BUY, 1.0),),
    )
    cache = OptionPreparedRunCache.from_chain(option_phase3_chain, option_phase3_registry)
    endpoint = QuantBTEndpoint.options(
        initial_capital=20_000.0,
        initial_balances={"USD": 20_000.0},
        conversion_rates={"BTC": 100_000.0},
    )

    result = endpoint.backtest(
        chain=option_phase3_chain,
        instruments=option_phase3_registry,
        packages=[package],
        prepared_cache=cache,
    )

    assert result.metadata["prepared_cache_used"] is True
    assert result.run_manifest["data_hash"]
    assert result.run_manifest["margin_model"]
    assert result.run_manifest["pricing_model"] == "observed_chain_bid_ask_mark"


def test_phase10_prepared_tape_rejects_stale_registry_signature(option_phase3_chain, option_phase3_registry):
    cache = OptionPreparedRunCache.from_chain(option_phase3_chain, option_phase3_registry)
    shifted = option_phase3_chain.copy()
    shifted.loc[0, "strike"] = shifted.loc[0, "strike"] + 1.0
    bad_registry = option_phase3_registry

    with pytest.raises(ValueError, match="strike"):
        prepare_option_tape(shifted, bad_registry)

    with pytest.raises(ValueError, match="timestamp mismatch"):
        cache.validate(option_phase3_registry, timestamps_ns=[int(cache.tape.timestamp_ns[0])])


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda frame: frame.drop(columns=["ask_price"]), "missing"),
        (lambda frame: frame.assign(bid_size=-1.0), "bid_size"),
        (lambda frame: frame.assign(ask_price=0.0), "ask_price"),
        (lambda frame: frame.assign(timestamp_ns=0), "timestamp_ns"),
        (lambda frame: frame.assign(source_latency_ns=10_000_000_000), "stale source latency"),
    ],
)
def test_phase10_invalid_chain_rows_are_rejected(option_phase3_chain, option_phase3_registry, mutator, message):
    bad = mutator(option_phase3_chain.copy())

    with pytest.raises(ValueError, match=message):
        OptionPreparedRunCache.from_chain(
            bad,
            option_phase3_registry,
            max_source_latency_ns=1_000_000,
        )


def test_phase10_invalid_package_cache_key_rejects_mutated_ratio(option_phase3_chain, option_phase3_registry):
    cache = OptionPreparedRunCache.from_chain(option_phase3_chain, option_phase3_registry)
    package_a = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="ratio-a",
        legs=(OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", OrderSide.BUY, 1.0),),
    )
    package_b = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="ratio-a",
        legs=(OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", OrderSide.BUY, 2.0),),
    )

    assert cache.compile_package(package_a)[0].qty == 1.0
    assert cache.compile_package(package_b)[0].qty == 2.0
    assert cache.package_cache_size == 2
