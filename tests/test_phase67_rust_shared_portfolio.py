"""Phase 67 shared-account Rust portfolio contracts.

This module intentionally tests the explicit portfolio target request rather
than changing ``QuantBTEndpoint.portfolio``.  The legacy Numba portfolio path
remains a compatibility oracle while the shared Rust contract is certified one
target kind and admission policy at a time.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.backends.native_portfolio_package import (
    run_shared_portfolio_target_market,
    run_shared_portfolio_target_market_v2,
)
from quantbt.backends.native_strategy_ir import NativeIRFold
from quantbt.backends.native_wfo import NativeTargetWfoRuntimeV2
from quantbt.preparation.native_execution import NativeExecutionPreparationCache


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def _fixture(*, symbols: int = 2, initial_capital: float = 10_000.0):
    bars = 10
    index = pd.date_range("2025-01-01", periods=bars, freq="1h", tz="UTC")
    base = np.array([100.0, 101.0, 103.0, 99.0, 97.0, 102.0, 105.0, 101.0, 104.0, 106.0])
    closes = np.column_stack([base + column * 17.0 for column in range(symbols)]).astype(np.float64)
    highs = closes + 2.0
    lows = closes - 2.0
    funding = np.zeros_like(closes)
    funding[4, :] = 0.0001
    funding_mask = np.zeros(bars, dtype=np.bool_)
    funding_mask[4] = True
    names = tuple(f"S{column:02d}" for column in range(symbols))
    common = dict(
        timestamps_ns=np.ascontiguousarray(index.view("int64"), dtype=np.int64),
        opens=closes,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=np.ones_like(closes),
        funding=funding,
        funding_mask=funding_mask,
        symbols=names,
        contract_sizes=np.full(symbols, 1.0, dtype=np.float64),
        leverages=np.full(symbols, 3.0, dtype=np.float64),
        fee_rates=np.full(symbols, 0.0005, dtype=np.float64),
        initial_capital=initial_capital,
        maintenance_ratio=0.005,
        slippage_rate=0.0002,
        use_funding=True,
    )
    return index, closes, common


def _targets(bars: int, symbols: int) -> np.ndarray:
    target = np.zeros((bars, symbols), dtype=np.float64)
    for symbol in range(symbols):
        magnitude = 1.0 + (symbol % 3) * 0.25
        target[1:3, symbol] = magnitude if symbol % 2 == 0 else -magnitude
        target[3:5, symbol] = -magnitude if symbol % 2 == 0 else magnitude
        target[5:7, symbol] = 0.5 * magnitude
        target[7:, symbol] = 0.0
    return target


def _run(common: dict, targets: np.ndarray, **kwargs):
    return run_shared_portfolio_target_market(
        **common,
        targets=targets,
        report_level=kwargs.pop("report_level", "compact"),
        **kwargs,
    )


@pytest.mark.parametrize("symbol_count", [1, 2, 8, 20])
def test_sequential_shared_account_matches_direct_target_contract(symbol_count: int):
    _, closes, common = _fixture(symbols=symbol_count)
    targets = _targets(len(closes), symbol_count)
    cache = NativeExecutionPreparationCache()
    market = cache.prepare_market(
        timestamps_ns=common["timestamps_ns"],
        opens=common["opens"],
        highs=common["highs"],
        lows=common["lows"],
        closes=common["closes"],
        volumes=common["volumes"],
        funding=common["funding"],
        funding_mask=common["funding_mask"],
        symbols=common["symbols"],
    )
    template = cache.prepare_template(
        market,
        contract_sizes=common["contract_sizes"],
        leverages=common["leverages"],
        fee_rates=common["fee_rates"],
        initial_capital=common["initial_capital"],
        maintenance_ratio=common["maintenance_ratio"],
        slippage_rate=common["slippage_rate"],
        use_funding=common["use_funding"],
    )
    direct = dict(
        cache.direct_target_request(
            template,
            targets=targets,
            target_kind="units",
            output_profile=1,
        ).core.execute()
    )
    shared = _run(common, targets, admission_policy="sequential_legacy").payload
    for field in (
        "equity",
        "positions",
        "fees",
        "turnover",
        "funding",
        "initial_margin",
        "maintenance_margin",
    ):
        np.testing.assert_allclose(np.asarray(shared[field]), np.asarray(direct[field]), rtol=0.0, atol=1e-11)
    assert shared["native_portfolio_shared_account"] is True
    assert shared["portfolio_admission_policy"] == "sequential_legacy"


@pytest.mark.parametrize("symbol_count", [1, 2, 8, 20])
@pytest.mark.parametrize(
    "admission_policy",
    [
        "sequential_legacy",
        "reduce_first_then_increase",
        "pro_rata_to_available_margin",
        "all_or_none_rebalance",
    ],
)
def test_shared_policy_matrix_accepts_exact_targets_when_shared_margin_is_sufficient(
    symbol_count: int,
    admission_policy: str,
):
    _, closes, common = _fixture(symbols=symbol_count, initial_capital=1_000_000.0)
    common = {
        **common,
        "fee_rates": np.zeros(symbol_count, dtype=np.float64),
        "slippage_rate": 0.0,
        "use_funding": False,
    }
    targets = _targets(len(closes), symbol_count)
    payload = _run(
        common,
        targets,
        admission_policy=admission_policy,
        report_level="compact",
    ).payload
    positions = np.asarray(payload["positions"]).reshape(len(closes), symbol_count)
    np.testing.assert_allclose(positions, targets, rtol=0.0, atol=1e-12)
    assert int(payload["rejected_count"]) == 0
    assert payload["liquidated"] is False


def test_reduce_first_releases_shared_margin_before_later_increase():
    _, closes, common = _fixture(symbols=2, initial_capital=100.0)
    common = {**common, "leverages": np.ones(2), "fee_rates": np.zeros(2), "slippage_rate": 0.0, "use_funding": False}
    targets = np.zeros((len(closes), 2), dtype=np.float64)
    # Bar 1 opens one fully margined long in S01. At bar 2, S00 needs a new
    # long while S01 is flattened. Stable sequential order sees S00 first and
    # cannot fund it; reduce-first must release S01 before admitting S00.
    targets[1, 1] = 0.80
    targets[2, 0] = 0.98
    sequential = _run(common, targets, admission_policy="sequential_legacy").payload
    reduce_first = _run(common, targets, admission_policy="reduce_first_then_increase").payload
    sequential_pos = np.asarray(sequential["positions"]).reshape(len(closes), 2)
    reduce_pos = np.asarray(reduce_first["positions"]).reshape(len(closes), 2)
    assert sequential_pos[2, 0] == 0.0
    assert reduce_pos[2, 0] > 0.0
    assert reduce_pos[2, 1] == 0.0
    assert int(np.asarray(sequential["portfolio_target_rejected_by_bar"])[2]) >= 1
    assert int(np.asarray(reduce_first["portfolio_target_rejected_by_bar"])[2]) == 0


def test_pro_rata_is_deterministic_and_never_exceeds_requested_quantized_target():
    _, closes, common = _fixture(symbols=2, initial_capital=100.0)
    common = {**common, "leverages": np.ones(2), "fee_rates": np.zeros(2), "slippage_rate": 0.0, "use_funding": False}
    targets = np.zeros((len(closes), 2), dtype=np.float64)
    targets[1:4] = np.array([0.9, 0.9])
    first = _run(
        common,
        targets,
        admission_policy="pro_rata_to_available_margin",
        qty_step=np.array([0.1, 0.1]),
        report_level="audit",
    ).payload
    second = _run(
        common,
        targets,
        admission_policy="pro_rata_to_available_margin",
        qty_step=np.array([0.1, 0.1]),
        report_level="audit",
    ).payload
    first_positions = np.asarray(first["positions"]).reshape(len(closes), 2)
    second_positions = np.asarray(second["positions"]).reshape(len(closes), 2)
    np.testing.assert_array_equal(first_positions, second_positions)
    assert np.all(np.abs(first_positions[1:4]) <= targets[1:4] + 1e-12)
    assert np.any(np.asarray(first["portfolio_target_rejection_code"]) == 6)


def test_all_or_none_rebalance_has_no_partial_account_mutation():
    _, closes, common = _fixture(symbols=2, initial_capital=100.0)
    common = {**common, "leverages": np.ones(2), "fee_rates": np.zeros(2), "slippage_rate": 0.0, "use_funding": False}
    target = np.zeros((len(closes), 2), dtype=np.float64)
    target[1, 0] = 0.5
    target[2, 0] = 0.9
    target[2, 1] = 0.9  # Cannot be admitted jointly with the carried S00.
    atomic = _run(common, target, admission_policy="all_or_none_rebalance", report_level="audit").payload
    hold = target.copy()
    hold[2] = hold[1]
    baseline = _run(common, hold, admission_policy="all_or_none_rebalance", report_level="audit").payload
    atomic_positions = np.asarray(atomic["positions"]).reshape(len(closes), 2)
    baseline_positions = np.asarray(baseline["positions"]).reshape(len(closes), 2)
    np.testing.assert_allclose(atomic_positions[2], baseline_positions[2], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(np.asarray(atomic["equity"])[2], np.asarray(baseline["equity"])[2], rtol=0.0, atol=1e-12)
    assert np.count_nonzero(np.asarray(atomic["portfolio_target_rejection_code"]) == 5) >= 2


@pytest.mark.parametrize("target_kind", ["units", "notional", "weight", "equity_fraction"])
def test_all_target_kinds_share_one_account_and_compact_attribution_reconciles(target_kind: str):
    _, closes, common = _fixture(symbols=2)
    common = {**common, "fee_rates": np.zeros(2), "slippage_rate": 0.0, "use_funding": False}
    targets = np.zeros((len(closes), 2), dtype=np.float64)
    if target_kind == "units":
        targets[1:4] = [1.0, -0.5]
        kwargs = {}
    elif target_kind == "notional":
        targets[1:4] = [100.0, -100.0]
        kwargs = {}
    elif target_kind == "weight":
        targets[1:4] = [0.01, -0.01]
        kwargs = {}
    else:
        targets[1:4] = [1.0, -1.0]
        kwargs = {"equity_fraction": np.array([0.01, 0.01])}
    payload = _run(
        common,
        targets,
        target_kind=target_kind,
        admission_policy="reduce_first_then_increase",
        **kwargs,
    ).payload
    for name in (
        "portfolio_symbol_realized_pnl",
        "portfolio_symbol_unrealized_pnl",
        "portfolio_symbol_mark_to_market_pnl",
        "portfolio_symbol_fee",
        "portfolio_symbol_slippage",
        "portfolio_symbol_funding",
        "portfolio_symbol_liquidation_loss",
        "portfolio_symbol_turnover",
        "portfolio_symbol_final_exposure",
        "portfolio_symbol_final_initial_margin",
    ):
        assert np.asarray(payload[name]).shape == (2,)
    realized = np.asarray(payload["portfolio_symbol_realized_pnl"])
    unrealized = np.asarray(payload["portfolio_symbol_unrealized_pnl"])
    mark = np.asarray(payload["portfolio_symbol_mark_to_market_pnl"])
    np.testing.assert_allclose(realized + unrealized, mark, rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(np.sum(payload["portfolio_symbol_fee"]), payload["total_fee"], rtol=0.0, atol=1e-11)
    np.testing.assert_allclose(np.sum(payload["portfolio_symbol_funding"]), payload["total_funding"], rtol=0.0, atol=1e-11)
    np.testing.assert_allclose(np.sum(payload["portfolio_symbol_turnover"]), payload["total_turnover"], rtol=0.0, atol=1e-11)


def test_stale_and_nontradable_reject_without_cross_symbol_account_leakage():
    _, closes, common = _fixture(symbols=2)
    targets = _targets(len(closes), 2)
    tradable = np.ones_like(targets, dtype=bool)
    stale = np.zeros_like(targets, dtype=bool)
    tradable[1, 0] = False
    stale[3, 1] = True
    payload = _run(
        common,
        targets,
        admission_policy="reduce_first_then_increase",
        tradable=tradable,
        stale=stale,
        report_level="audit",
    ).payload
    codes = np.asarray(payload["portfolio_target_rejection_code"])
    assert 3 in codes
    assert 4 in codes
    assert payload["liquidated"] is False


def test_score_avoids_symbol_attribution_and_prepared_cache_reuses_request():
    _, closes, common = _fixture(symbols=2)
    targets = _targets(len(closes), 2)
    cache = NativeExecutionPreparationCache()
    score = _run(
        common,
        targets,
        admission_policy="sequential_legacy",
        report_level="score",
        cache=cache,
    )
    again = _run(
        common,
        targets,
        admission_policy="sequential_legacy",
        report_level="score",
        cache=cache,
    )
    assert "portfolio_symbol_fee" not in score.payload
    assert score.request_signature == again.request_signature
    assert cache.diagnostics["cache_hit"] >= 1


def _prepared_template(common: dict):
    cache = NativeExecutionPreparationCache()
    market = cache.prepare_market(
        timestamps_ns=common["timestamps_ns"],
        opens=common["opens"],
        highs=common["highs"],
        lows=common["lows"],
        closes=common["closes"],
        volumes=common["volumes"],
        funding=common["funding"],
        funding_mask=common["funding_mask"],
        symbols=common["symbols"],
    )
    return cache, cache.prepare_template(
        market,
        contract_sizes=common["contract_sizes"],
        leverages=common["leverages"],
        fee_rates=common["fee_rates"],
        initial_capital=common["initial_capital"],
        maintenance_ratio=common["maintenance_ratio"],
        slippage_rate=common["slippage_rate"],
        use_funding=common["use_funding"],
    )


def test_prepared_multisymbol_wfo_reuses_shared_account_executor_without_replay():
    _, closes, common = _fixture(symbols=2)
    cache, template = _prepared_template(common)
    folds = (
        NativeIRFold(10, 0, 0, 4, 4, 7),
        NativeIRFold(20, 0, 0, 7, 7, len(closes)),
    )
    targets = np.zeros((3, len(closes), 2), dtype=np.float64)
    targets[0, 4:7] = [1.0, -0.75]
    targets[1, 4:7] = [-0.5, 1.25]
    targets[2, 7:] = [0.75, 0.75]
    candidate_ids = np.asarray([101, 202, 303], dtype=np.uint64)
    runtime = NativeTargetWfoRuntimeV2(
        template,
        folds,
        admission_policy="reduce_first_then_increase",
    )
    try:
        score = runtime.score_shared(targets, candidate_ids=candidate_ids)
        prepared = runtime.prepare_shared(targets, candidate_ids=candidate_ids)
        repeated = runtime.score_prepared_batch(prepared)
        np.testing.assert_allclose(score.final_equity, repeated.final_equity, rtol=0.0, atol=1e-12)
        assert score.terminal_fingerprint == repeated.terminal_fingerprint
        assert score.metadata["shared_account"] is True
        assert score.metadata["portfolio_admission_policy"] == "reduce_first_then_increase"
        assert score.metadata["market_copy_bytes"] == 0
        assert score.metadata["execution_authority"] == "rust_shared_portfolio_target_v1"

        # Each fold is a fresh *shared* account over its declared OOS slice.
        # The comparison goes directly through the native request rather than
        # any callback/signal/order replay route.
        for fold in folds:
            local_template = cache.window_template(
                template,
                start=fold.test_start,
                end=fold.test_end,
            )
            for candidate_index, candidate_id in enumerate(candidate_ids):
                direct = dict(
                    cache.shared_portfolio_target_request(
                        local_template,
                        targets=targets[candidate_index, fold.test_start : fold.test_end],
                        target_kind="units",
                        admission_policy="reduce_first_then_increase",
                        output_profile=0,
                    ).core.execute()
                )
                row = (score.candidate_id == candidate_id) & (score.fold_id == fold.fold_id)
                assert int(row.sum()) == 1
                slot = int(np.flatnonzero(row)[0])
                assert score.final_equity[slot] == pytest.approx(direct["final_equity"])
                assert score.total_fee[slot] == pytest.approx(direct["total_fee"])
                assert score.total_funding[slot] == pytest.approx(direct["total_funding"])
                assert score.turnover[slot] == pytest.approx(direct["total_turnover"])
                assert score.terminal_fingerprint[slot] == direct["native_execution_terminal_fingerprint"]

        audit = runtime.audit_prepared_batch(
            prepared,
            selected_candidate_ids=np.asarray([202], dtype=np.uint64),
            expected_intent_fingerprint=score.intent_fingerprint,
        )
        audit.assert_audit_parity(score)
        cube = np.repeat(targets[np.newaxis, ...], len(folds), axis=0)
        per_fold = runtime.score_per_fold(cube, candidate_ids=candidate_ids)
        np.testing.assert_allclose(score.final_equity, per_fold.final_equity, rtol=0.0, atol=1e-12)
        assert score.terminal_fingerprint == per_fold.terminal_fingerprint
    finally:
        runtime.close()


def test_funding_and_liquidation_attribution_reconcile_to_shared_account_equity():
    _, closes, common = _fixture(symbols=2, initial_capital=100.0)
    lows = np.asarray(common["lows"], dtype=np.float64).copy()
    lows[2] = 1.0
    common = {
        **common,
        "lows": lows,
        "leverages": np.full(2, 10.0, dtype=np.float64),
        "fee_rates": np.zeros(2, dtype=np.float64),
        "slippage_rate": 0.0,
    }
    targets = np.zeros((len(closes), 2), dtype=np.float64)
    targets[1] = [4.0, 4.0]
    payload = _run(
        common,
        targets,
        admission_policy="reduce_first_then_increase",
        report_level="audit",
    ).payload
    assert payload["liquidated"] is True
    assert payload["liquidation_bar"] == 2
    positions = np.asarray(payload["positions"]).reshape(len(closes), 2)
    np.testing.assert_array_equal(positions[2:], 0.0)
    realized = np.asarray(payload["portfolio_symbol_realized_pnl"])
    unrealized = np.asarray(payload["portfolio_symbol_unrealized_pnl"])
    mark = np.asarray(payload["portfolio_symbol_mark_to_market_pnl"])
    liquidation_loss = np.asarray(payload["portfolio_symbol_liquidation_loss"])
    np.testing.assert_allclose(realized + unrealized, mark, rtol=0.0, atol=1e-10)
    np.testing.assert_allclose(
        float(common["initial_capital"])
        + float(mark.sum())
        - float(np.asarray(payload["portfolio_symbol_fee"]).sum())
        - float(np.asarray(payload["portfolio_symbol_slippage"]).sum())
        - float(np.asarray(payload["portfolio_symbol_funding"]).sum())
        - float(liquidation_loss.sum()),
        float(payload["final_equity"]),
        rtol=0.0,
        atol=1e-10,
    )


def test_funding_attribution_sums_to_portfolio_total_before_any_liquidation():
    _, closes, common = _fixture(symbols=2)
    common = {**common, "fee_rates": np.zeros(2), "slippage_rate": 0.0}
    targets = np.zeros((len(closes), 2), dtype=np.float64)
    targets[1:7] = [1.0, -0.5]
    payload = _run(
        common,
        targets,
        admission_policy="sequential_legacy",
        report_level="compact",
    ).payload
    assert payload["liquidated"] is False
    np.testing.assert_allclose(
        np.asarray(payload["portfolio_symbol_funding"]).sum(),
        payload["total_funding"],
        rtol=0.0,
        atol=1e-12,
    )


def test_shared_portfolio_audit_adapts_to_common_result_without_execution_replay():
    index, closes, common = _fixture(symbols=2)
    targets = _targets(len(closes), 2)
    execution = _run(
        common,
        targets,
        admission_policy="reduce_first_then_increase",
        report_level="audit",
    )
    audit = execution.to_audit_result()
    report = audit.to_backtest_result(
        datetime_index=index,
        closes=pd.DataFrame(closes, index=index, columns=common["symbols"]),
        symbols=common["symbols"],
        initial_capital=float(common["initial_capital"]),
        leverage=float(common["leverages"][0]),
    )

    np.testing.assert_allclose(
        report.equity.to_numpy(),
        np.asarray(execution.payload["equity"]),
        rtol=0.0,
        atol=1e-12,
    )
    assert len(report.fills) == int(execution.payload["fill_count"])
    assert report.metadata["fills_report"]["order_id"].notna().all()


def test_v2_registry_normalizes_symbol_input_order_before_shared_pro_rata_execution():
    index = pd.date_range("2025-02-01", periods=6, freq="1h", tz="UTC")

    def frame(base: float) -> pd.DataFrame:
        close = base + np.arange(len(index), dtype=np.float64)
        return pd.DataFrame(
            {
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.ones(len(index), dtype=np.float64),
            },
            index=index,
        )

    btc = frame(100.0)
    eth = frame(50.0)
    first_market = QuantBTEndpoint.prepare_market({"ETH": eth, "BTC": btc}, calendar_policy="exact")
    second_market = QuantBTEndpoint.prepare_market({"BTC": btc, "ETH": eth}, calendar_policy="exact")
    first_registry = QuantBTEndpoint.prepare_instruments(
        symbols=["ETH", "BTC"],
        contract_size={"BTC": 1.0, "ETH": 1.0},
        leverage={"BTC": 1.0, "ETH": 1.0},
        fee_rate=0.0,
        qty_step={"BTC": 0.1, "ETH": 0.1},
    )
    second_registry = QuantBTEndpoint.prepare_instruments(
        symbols=["BTC", "ETH"],
        contract_size={"BTC": 1.0, "ETH": 1.0},
        leverage={"BTC": 1.0, "ETH": 1.0},
        fee_rate=0.0,
        qty_step={"BTC": 0.1, "ETH": 0.1},
    )
    assert first_market.symbols == second_market.symbols == ("BTC", "ETH")
    assert first_registry.symbols == second_registry.symbols == ("BTC", "ETH")
    targets = np.zeros((len(index), 2), dtype=np.float64)
    targets[1:4] = [0.9, -0.9]
    first = run_shared_portfolio_target_market_v2(
        market=first_market,
        instruments=first_registry,
        initial_capital=100.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0,
        use_funding=False,
        targets=targets,
        admission_policy="pro_rata_to_available_margin",
        report_level="compact",
    ).payload
    second = run_shared_portfolio_target_market_v2(
        market=second_market,
        instruments=second_registry,
        initial_capital=100.0,
        maintenance_ratio=0.005,
        slippage_rate=0.0,
        use_funding=False,
        targets=targets,
        admission_policy="pro_rata_to_available_margin",
        report_level="compact",
    ).payload
    np.testing.assert_allclose(first["equity"], second["equity"], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(first["positions"], second["positions"], rtol=0.0, atol=1e-12)
    assert first["native_execution_terminal_fingerprint"] == second["native_execution_terminal_fingerprint"]


def test_multisymbol_wfo_requires_declared_shared_policy_and_stays_serial():
    _, _, common = _fixture(symbols=2)
    cache, template = _prepared_template(common)
    del cache
    folds = (NativeIRFold(1, 0, 0, 4, 4, 7),)

    with pytest.raises(NotImplementedError, match="admission_policy"):
        NativeTargetWfoRuntimeV2(template, folds)
    with pytest.raises(ValueError, match="workers must be 1"):
        NativeTargetWfoRuntimeV2(
            template,
            folds,
            admission_policy="sequential_legacy",
            workers=2,
        )


def test_generic_portfolio_retains_python_planning_and_numba_execution_boundary():
    index = pd.date_range("2025-03-01", periods=5, freq="1h", tz="UTC")
    data = {
        "BTC": pd.DataFrame(
            {"close": [100.0, 101.0, 99.0, 102.0, 103.0]}, index=index
        ),
        "ETH": pd.DataFrame(
            {"close": [50.0, 49.0, 51.0, 50.0, 52.0]}, index=index
        ),
    }
    positions = pd.DataFrame(
        {"BTC": [0.0, 1.0, 1.0, 0.0, 0.0], "ETH": [0.0, -1.0, -1.0, 0.0, 0.0]},
        index=index,
    )
    endpoint = QuantBTEndpoint.portfolio(
        portfolio_mode="longshort",
        hedge_type="target_units",
        initial_capital=10_000.0,
        leverage=3.0,
        fee_rate=0.0,
        use_funding=False,
    )
    result = endpoint.backtest(data=data, positions=positions)

    assert result.metadata["backend"] == "native_portfolio"
    assert result.metadata["planning_authority"] == "python_portfolio_planner_v1"
    assert result.metadata["execution_authority"] == "numba_native_portfolio_v1"
    assert result.metadata["rust_shared_portfolio_route"] == "not_requested"
