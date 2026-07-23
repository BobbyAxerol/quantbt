"""
Native option backend facade.

This backend wires the Phase 1-6 option components into the common QuantBT
result contract. It does not attempt to be a venue-exact options exchange; the
venue-specific gaps stay explicit in reports and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.results import OptionBacktestResult
from ..core.schema import AccountConfig, ExecutionConfig
from ..options.cache import OptionPreparedRunCache
from ..options.execution import OptionExecutionConfig, execute_option_package
from ..options.fees import OptionFeeResult, OptionFeeSchedule, calculate_option_fee
from ..options.hedging import OptionHedgeConfig, run_delta_hedge_path
from ..options.ledger import OptionLedger
from ..options.lifecycle import OptionSettlementRepresentation, settle_option_expiry
from ..options.margin import OptionMarginConfig, OptionMarginRequirement, calculate_option_margin
from ..options.packages import OptionPackageIntent
from ..options.schema import OptionInstrumentRegistry, OptionInstrumentSpec
from ..options.tape import PreparedOptionTape, prepare_option_tape


@dataclass(frozen=True)
class NativeOptionConfig:
    account: AccountConfig = field(default_factory=lambda: AccountConfig(initial_capital=100_000.0))
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    option_execution: OptionExecutionConfig = field(default_factory=OptionExecutionConfig)
    margin: OptionMarginConfig = field(default_factory=OptionMarginConfig)
    fee_schedule: Optional[OptionFeeSchedule] = None
    reporting_currency: str = "USD"
    initial_balances: Optional[Dict[str, float]] = None
    conversion_rates: Dict[str, float] = field(default_factory=dict)
    settle_expired: bool = False
    max_spread_bps: Optional[float] = None
    max_source_latency_ns: Optional[int] = None
    random_seed: Optional[int] = 42
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reporting_currency", str(self.reporting_currency).upper())
        if self.account.initial_capital <= 0.0:
            raise ValueError("account.initial_capital must be > 0")


@dataclass(frozen=True)
class OptionSettlementEvent:
    symbol: str
    timestamp_ns: int
    settlement_price: float
    representation: Optional[OptionSettlementRepresentation] = None


class NativeOptionBackend:
    """Array-first native option backend returning `OptionBacktestResult`."""

    def __init__(self, config: Optional[NativeOptionConfig] = None):
        self.config = config or NativeOptionConfig()

    def run(
        self,
        *,
        chain: pd.DataFrame,
        instruments: OptionInstrumentRegistry | Sequence[OptionInstrumentSpec] | Mapping[str, OptionInstrumentSpec],
        packages: Sequence[OptionPackageIntent] = (),
        prepared_tape: Optional[PreparedOptionTape] = None,
        prepared_cache: Optional[OptionPreparedRunCache] = None,
        underlying: Optional[pd.DataFrame | pd.Series] = None,
        hedge_policy: Optional[OptionHedgeConfig] = None,
        net_option_delta: Optional[pd.Series] = None,
        settlement_events: Optional[Sequence[OptionSettlementEvent | Mapping]] = None,
        conversion_rates: Optional[Dict[str, float]] = None,
        reporting_currency: Optional[str] = None,
    ) -> OptionBacktestResult:
        registry = _normalize_registry(instruments)
        if prepared_cache is not None:
            prepared_cache.validate(registry)
            tape = prepared_cache.tape
        else:
            tape = prepared_tape or prepare_option_tape(
                chain,
                registry,
                max_spread_bps=self.config.max_spread_bps,
                max_source_latency_ns=self.config.max_source_latency_ns,
            )
        tape.validate_compatible(registry_signature=registry.signature)
        rates = {**self.config.conversion_rates, **(conversion_rates or {})}
        report_ccy = str(reporting_currency or self.config.reporting_currency).upper()
        if report_ccy not in rates:
            rates[report_ccy] = 1.0

        ledger = OptionLedger.from_cash(self.config.initial_balances or {report_ccy: self.config.account.initial_capital})
        instrument_map = registry.by_symbol
        packages_sorted = tuple(sorted(packages or (), key=lambda package: int(package.timestamp_ns)))
        order_reports = []
        package_reports = []
        applied_fills = []
        snapshots = []

        snapshots.append(_snapshot_state(tape, 0, ledger, instrument_map, rates, report_ccy, "initial"))
        for package in packages_sorted:
            pkg_result = execute_option_package(
                package,
                tape,
                config=self.config.option_execution,
                positions={symbol: position.qty for symbol, position in ledger.positions.items()},
                compiled_orders=prepared_cache.compile_package(package) if prepared_cache is not None else None,
            )
            order_reports.append(pkg_result.order_report)
            package_reports.append(pkg_result.package_report)
            for fill in pkg_result.fills:
                instrument = instrument_map[fill.symbol]
                fee = _option_fee(fill, instrument, tape, self.config.fee_schedule)
                ledger.apply_fill(fill, instrument, fee=fee, timestamp_ns=int(fill.timestamp))
                applied_fills.append((fill, fee))
            snap_idx = tape.snapshot_index_at_or_before(int(package.timestamp_ns))
            snapshots.append(_snapshot_state(tape, snap_idx, ledger, instrument_map, rates, report_ccy, package.package_id))

        settlements = []
        for event in _normalize_settlement_events(settlement_events):
            instrument = instrument_map[event.symbol]
            settlement = settle_option_expiry(
                ledger,
                instrument,
                timestamp_ns=int(event.timestamp_ns),
                settlement_price=float(event.settlement_price),
                representation=event.representation,
            )
            settlements.append(settlement)
            snap_idx = min(tape.snapshot_count - 1, max(0, np.searchsorted(tape.timestamp_ns, int(event.timestamp_ns), side="right") - 1))
            snapshots.append(_snapshot_state(tape, int(snap_idx), ledger, instrument_map, rates, report_ccy, f"settlement:{event.symbol}"))

        if self.config.settle_expired:
            last_ts = int(tape.timestamp_ns[-1])
            marks = _snapshot_marks(tape, tape.snapshot_count - 1)
            underlyings = _snapshot_underlyings(tape, tape.snapshot_count - 1)
            for symbol, position in list(ledger.positions.items()):
                instrument = instrument_map[symbol]
                if position.is_flat or int(instrument.expiry_ns) > last_ts:
                    continue
                settlement = settle_option_expiry(
                    ledger,
                    instrument,
                    timestamp_ns=last_ts,
                    settlement_price=underlyings.get(instrument.underlying_id, marks.get(symbol, 0.0)),
                )
                settlements.append(settlement)
            snapshots.append(_snapshot_state(tape, tape.snapshot_count - 1, ledger, instrument_map, rates, report_ccy, "auto_settlement"))

        final_snapshot_idx = tape.snapshot_count - 1
        final_marks = _snapshot_marks(tape, final_snapshot_idx)
        final_underlyings = _snapshot_underlyings(tape, final_snapshot_idx)
        margin = calculate_option_margin(
            ledger,
            instrument_map,
            final_marks,
            final_underlyings,
            config=self.config.margin,
            reporting_currency=report_ccy,
            conversion_rates=rates,
        )
        snapshots.append(_snapshot_state(tape, final_snapshot_idx, ledger, instrument_map, rates, report_ccy, "final"))

        result = _build_result(
            tape=tape,
            registry=registry,
            ledger=ledger,
            account=self.config.account,
            report_ccy=report_ccy,
            conversion_rates=rates,
            snapshots=snapshots,
            fills_with_fees=applied_fills,
            order_report=_concat(order_reports),
            package_report=_concat(package_reports),
            settlements=settlements,
            margin=margin,
            metadata={
                "backend": "native_option",
                "engine": "native_option",
                "phase": "phase7_backend_endpoint_result",
                "package_count": len(packages_sorted),
                "fill_count": len(applied_fills),
                "settlement_count": len(settlements),
                "venue_exact_margin": bool(margin.venue_exact),
                "reporting_currency": report_ccy,
                "prepared_cache_used": prepared_cache is not None,
                "package_cache_size": 0 if prepared_cache is None else prepared_cache.package_cache_size,
                "fee_schedule_id": "execution_fee_rate"
                if self.config.fee_schedule is None
                else self.config.fee_schedule.schedule_id,
                "limit_fidelity": self.config.option_execution.limit_fidelity.value,
                "depth_fidelity": self.config.option_execution.depth_fidelity.value,
                "random_seed": self.config.random_seed,
                **self.config.metadata,
            },
        )
        if hedge_policy is not None:
            result = _attach_delta_hedge_contract(
                result,
                tape=tape,
                registry=registry,
                underlying=underlying,
                hedge_policy=hedge_policy,
                net_option_delta=net_option_delta,
                account=self.config.account,
                report_ccy=report_ccy,
            )
        return result


def _normalize_registry(
    instruments: OptionInstrumentRegistry | Sequence[OptionInstrumentSpec] | Mapping[str, OptionInstrumentSpec],
) -> OptionInstrumentRegistry:
    if isinstance(instruments, OptionInstrumentRegistry):
        return instruments
    if isinstance(instruments, Mapping):
        return OptionInstrumentRegistry.from_iterable(instruments.values())
    return OptionInstrumentRegistry.from_iterable(tuple(instruments))


def _normalize_settlement_events(events: Optional[Sequence[OptionSettlementEvent | Mapping]]) -> tuple[OptionSettlementEvent, ...]:
    if not events:
        return ()
    out = []
    for event in events:
        if isinstance(event, OptionSettlementEvent):
            out.append(event)
        else:
            out.append(
                OptionSettlementEvent(
                    symbol=str(event["symbol"]),
                    timestamp_ns=int(event["timestamp_ns"]),
                    settlement_price=float(event["settlement_price"]),
                    representation=event.get("representation"),
                )
            )
    return tuple(out)


def _option_fee(fill, instrument: OptionInstrumentSpec, tape: PreparedOptionTape, schedule: Optional[OptionFeeSchedule]) -> Optional[OptionFeeResult]:
    schedule = schedule or fill.metadata.get("option_fee_schedule")
    if schedule is None:
        return None
    if not isinstance(schedule, OptionFeeSchedule):
        return None
    row_index = int(fill.metadata.get("option_row_index", -1))
    if row_index < 0:
        return None
    reference = float(tape.index_price[row_index] if np.isfinite(tape.index_price[row_index]) else tape.forward_price[row_index])
    return calculate_option_fee(fill, instrument, schedule, reference_price=reference)


def _snapshot_state(
    tape: PreparedOptionTape,
    snapshot_idx: int,
    ledger: OptionLedger,
    instruments: Dict[str, OptionInstrumentSpec],
    conversion_rates: Dict[str, float],
    report_ccy: str,
    label: str,
) -> Dict:
    marks = _snapshot_marks(tape, snapshot_idx)
    equity = ledger.equity(conversion_rates=conversion_rates, marks=marks, instruments=instruments, reporting_currency=report_ccy)
    return {
        "timestamp_ns": int(tape.timestamp_ns[snapshot_idx]),
        "label": label,
        "equity": float(equity),
        "cash": dict(ledger.cash),
        "positions": {symbol: position.qty for symbol, position in ledger.positions.items()},
        "marks": marks,
    }


def _snapshot_marks(tape: PreparedOptionTape, snapshot_idx: int) -> Dict[str, float]:
    rows = tape.snapshot_slice(snapshot_idx)
    return {tape.instrument_id[idx]: float(tape.mark_price[idx]) for idx in range(rows.start, rows.stop)}


def _snapshot_underlyings(tape: PreparedOptionTape, snapshot_idx: int) -> Dict[str, float]:
    rows = tape.snapshot_slice(snapshot_idx)
    out = {}
    registry = tape.registry.by_symbol
    for idx in range(rows.start, rows.stop):
        symbol = tape.instrument_id[idx]
        instrument = registry[symbol]
        price = float(tape.index_price[idx] if np.isfinite(tape.index_price[idx]) else tape.forward_price[idx])
        out[instrument.underlying_id] = price
        out[symbol] = price
    return out


def _build_result(
    *,
    tape: PreparedOptionTape,
    registry: OptionInstrumentRegistry,
    ledger: OptionLedger,
    account: AccountConfig,
    report_ccy: str,
    conversion_rates: Dict[str, float],
    snapshots: Sequence[Dict],
    fills_with_fees: Sequence[tuple],
    order_report: pd.DataFrame,
    package_report: pd.DataFrame,
    settlements: Sequence,
    margin: OptionMarginRequirement,
    metadata: Dict,
) -> OptionBacktestResult:
    index = pd.DatetimeIndex(pd.to_datetime([snap["timestamp_ns"] for snap in snapshots], utc=True)).tz_convert(None)
    equity = pd.Series([snap["equity"] for snap in snapshots], index=index, name="equity")
    if len(equity.index) != len(set(equity.index)):
        offsets = pd.to_timedelta(np.arange(len(equity)), unit="ns")
        equity.index = pd.DatetimeIndex(equity.index + offsets)
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    symbols = list(registry.symbols)
    positions = pd.DataFrame(
        [{f"Position_{symbol}": snap["positions"].get(symbol, 0.0) for symbol in symbols} for snap in snapshots],
        index=equity.index,
        columns=[f"Position_{symbol}" for symbol in symbols],
    )
    closes = pd.DataFrame(
        [{f"Close_{symbol}": snap["marks"].get(symbol, np.nan) for symbol in symbols} for snap in snapshots],
        index=equity.index,
        columns=[f"Close_{symbol}" for symbol in symbols],
    ).ffill()
    cash_report = _cash_report(snapshots, equity.index)
    marks_report = _marks_report(tape)
    greeks_report = _greeks_report(tape)
    fills_report = _fills_report(fills_with_fees)
    settlements_report = _settlements_report(settlements)
    attribution_report = _attribution_report(ledger, account, equity.iloc[-1], report_ccy, conversion_rates)
    run_manifest = {
        "backend": "native_option",
        "result_contract": "OptionBacktestResult",
        "symbols": symbols,
        "snapshot_count": int(tape.snapshot_count),
        "row_count": int(tape.row_count),
        "initial_capital": float(account.initial_capital),
        "final_equity": float(equity.iloc[-1]),
        "reporting_currency": report_ccy,
        "data_hash": _chain_data_hash(marks_report),
        "registry_signature_hash": _stable_hash(repr(registry.signature.signature)),
        "convention_versions": sorted(
            {instrument.convention_version for instrument in registry.instruments if instrument.convention_version}
        ),
        "fee_schedule": metadata.get("fee_schedule_id", "execution_fee_rate"),
        "margin_model": str(getattr(margin.model, "value", margin.model)),
        "pricing_model": "observed_chain_bid_ask_mark",
        "deterministic_replay": True,
        "random_seed": metadata.get("random_seed"),
        "fidelity_manifest": {
            "tape": "prepared_csr_option_chain",
            "execution": "top_of_book_bbo",
            "limit_fidelity": metadata.get("limit_fidelity"),
            "depth_fidelity": metadata.get("depth_fidelity"),
            "margin": str(getattr(margin.model, "value", margin.model)),
            "venue_exact_margin": bool(margin.venue_exact),
            "prepared_cache_used": bool(metadata.get("prepared_cache_used", False)),
        },
        "option_reports": [
            "fills_report",
            "packages_report",
            "cash_report",
            "marks_report",
            "greeks_report",
            "settlements_report",
            "margin_report",
            "attribution_report",
        ],
    }
    result_metadata = {
        **metadata,
        "order_report": order_report,
        "fills_report": fills_report,
        "packages_report": package_report,
        "cash_report": cash_report,
        "marks_report": marks_report,
        "greeks_report": greeks_report,
        "settlements_report": settlements_report,
        "margin_report": margin.detail_report,
        "attribution_report": attribution_report,
        "run_manifest": run_manifest,
        "ledger_event_report": ledger.event_report(),
        "equity_identity": ledger.equity_identity_report(
            conversion_rates=conversion_rates,
            marks=_snapshot_marks(tape, tape.snapshot_count - 1),
            instruments=registry.by_symbol,
            reporting_currency=report_ccy,
        ),
    }
    fees = pd.Series(0.0, index=equity.index, name="fees")
    if len(fees) > 0:
        fees.iloc[-1] = float(sum((fee.fee if fee is not None else fill.fee) for fill, fee in fills_with_fees))
    return OptionBacktestResult(
        equity=equity,
        returns=returns,
        positions=positions,
        closes=closes,
        symbols=symbols,
        initial_capital=float(account.initial_capital),
        leverage=float(account.leverage),
        liquidated=False,
        fills=tuple(fill for fill, _ in fills_with_fees),
        fees=fees,
        margin=margin.detail_report,
        diagnostics=package_report,
        metadata=result_metadata,
        fills_report=fills_report,
        packages_report=package_report,
        cash_report=cash_report,
        marks_report=marks_report,
        greeks_report=greeks_report,
        settlements_report=settlements_report,
        margin_report=margin.detail_report,
        attribution_report=attribution_report,
        run_manifest=run_manifest,
    )


def _concat(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    items = [frame for frame in frames if frame is not None and not frame.empty]
    return pd.concat(items, ignore_index=True) if items else pd.DataFrame()


def _chain_data_hash(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "0"
    hashed = pd.util.hash_pandas_object(frame.sort_index(axis=1), index=False).to_numpy(dtype="uint64")
    return str(int(hashed.sum(dtype="uint64")))


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _attach_delta_hedge_contract(
    result: OptionBacktestResult,
    *,
    tape: PreparedOptionTape,
    registry: OptionInstrumentRegistry,
    underlying: Optional[pd.DataFrame | pd.Series],
    hedge_policy: OptionHedgeConfig,
    net_option_delta: Optional[pd.Series],
    account: AccountConfig,
    report_ccy: str,
) -> OptionBacktestResult:
    path_timestamps = np.concatenate((np.array([int(tape.timestamp_ns[0]) - 1], dtype=np.int64), tape.timestamp_ns.astype(np.int64)))
    index = _datetime_index_from_ns(path_timestamps)
    option_equity, positions, closes, fees = _linear_quote_option_path(
        result,
        tape,
        registry,
        account,
        report_ccy,
        index,
        path_timestamps,
    )
    deltas = _normalize_net_delta(net_option_delta, result.greeks_report, positions, registry, index)
    prices, underlying_source = _normalize_underlying_prices(underlying, tape, index)

    hedge = run_delta_hedge_path(
        timestamps_ns=list(path_timestamps),
        underlying_prices=prices.to_numpy(dtype=np.float64),
        net_option_deltas=deltas.to_numpy(dtype=np.float64),
        config=hedge_policy,
    )
    hedge_report = hedge.hedge_report.copy()
    hedge_report.index = index
    cumulative_hedge = pd.Series(
        hedge_report["cumulative_hedge_pnl"].to_numpy(dtype=np.float64),
        index=index,
        name="hedge_pnl",
    )
    combined = (option_equity + cumulative_hedge).rename("equity")
    combined_returns = combined.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    result.option_equity = option_equity
    result.hedge_report = hedge_report
    result.combined_equity = combined
    result.combined_returns = combined_returns
    result.equity = combined
    result.returns = combined_returns
    result.positions = positions
    result.closes = closes
    result.fees = fees
    result.metadata["option_equity"] = option_equity
    result.metadata["hedge_report"] = hedge_report
    result.metadata["combined_equity"] = combined
    result.metadata["combined_returns"] = combined_returns
    result.metadata["delta_hedge_contract"] = {
        "enabled": True,
        "underlying_source": underlying_source,
        "policy": hedge_policy.policy.value,
        "target_delta": float(hedge_policy.target_delta),
        "final_hedge_qty": float(hedge.final_hedge_qty),
        "hedge_pnl": float(hedge.hedge_pnl),
        "hedge_rebalances": int(hedge_report["should_rebalance"].sum()) if not hedge_report.empty else 0,
        "option_path_method": result.metadata.get("option_path_method", "linear_quote_replay"),
    }
    result.run_manifest["delta_hedge"] = result.metadata["delta_hedge_contract"]
    result.run_manifest["final_equity"] = float(combined.iloc[-1])
    result.metadata["run_manifest"] = result.run_manifest
    return result


def _linear_quote_option_path(
    result: OptionBacktestResult,
    tape: PreparedOptionTape,
    registry: OptionInstrumentRegistry,
    account: AccountConfig,
    report_ccy: str,
    index: pd.DatetimeIndex,
    path_timestamps: np.ndarray,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame, pd.Series]:
    symbols = list(registry.symbols)
    linear_quote_exact = all(
        instrument.premium_currency.upper() == report_ccy and instrument.settlement_currency.upper() == report_ccy
        for instrument in registry.instruments
    )
    if not linear_quote_exact:
        option_equity = result.equity.reindex(index).ffill().bfill().rename("option_equity")
        positions = result.positions.reindex(index).ffill().fillna(0.0)
        closes = result.closes.reindex(index).ffill().bfill()
        fees = result.fees.reindex(index).fillna(0.0)
        result.metadata["option_path_method"] = "event_equity_reindexed_non_quote_currency"
        return option_equity, positions, closes, fees

    cash = float(account.initial_capital)
    pos = {symbol: 0.0 for symbol in symbols}
    fills = result.fills_report.sort_values("timestamp") if not result.fills_report.empty else pd.DataFrame()
    fill_idx = 0
    equity_rows = []
    position_rows = []
    close_rows = []
    fee_values = []
    mark_by_ts_symbol = _mark_lookup(tape)

    for ts, dt in zip(path_timestamps, index):
        snap_idx = max(0, int(np.searchsorted(tape.timestamp_ns, int(ts), side="right") - 1))
        fee_at_ts = 0.0
        while not fills.empty and fill_idx < len(fills) and int(fills.iloc[fill_idx]["timestamp"]) <= int(ts):
            row = fills.iloc[fill_idx]
            qty = float(row["qty"])
            price = float(row["price"])
            fee = float(row.get("applied_fee", row.get("execution_fee", 0.0)))
            symbol = str(row["symbol"])
            side = str(row["side"]).lower()
            if side == "buy":
                cash -= qty * price + fee
                pos[symbol] = pos.get(symbol, 0.0) + qty
            else:
                cash += qty * price - fee
                pos[symbol] = pos.get(symbol, 0.0) - qty
            fee_at_ts += fee
            fill_idx += 1
        mark_ts = int(tape.timestamp_ns[snap_idx])
        marks = {symbol: mark_by_ts_symbol.get((mark_ts, symbol), np.nan) for symbol in symbols}
        marked_value = sum(pos.get(symbol, 0.0) * marks[symbol] for symbol in symbols if np.isfinite(marks[symbol]))
        equity_rows.append(cash + marked_value)
        position_rows.append({f"Position_{symbol}": pos.get(symbol, 0.0) for symbol in symbols})
        close_rows.append({f"Close_{symbol}": marks[symbol] for symbol in symbols})
        fee_values.append(fee_at_ts)

    option_equity = pd.Series(equity_rows, index=index, name="option_equity")
    positions = pd.DataFrame(position_rows, index=index).fillna(0.0)
    closes = pd.DataFrame(close_rows, index=index).ffill().bfill()
    fees = pd.Series(fee_values, index=index, name="fees")
    result.metadata["option_path_method"] = "linear_quote_replay"
    return option_equity, positions, closes, fees


def _normalize_net_delta(
    net_option_delta: Optional[pd.Series],
    greeks_report: pd.DataFrame,
    positions: pd.DataFrame,
    registry: OptionInstrumentRegistry,
    index: pd.DatetimeIndex,
) -> pd.Series:
    if net_option_delta is not None:
        series = _coerce_series_index(net_option_delta, "net_option_delta")
        return series.reindex(index).ffill().bfill().fillna(0.0).rename("net_option_delta")
    if greeks_report.empty:
        return pd.Series(0.0, index=index, name="net_option_delta")
    greeks = greeks_report.copy()
    greeks["datetime"] = pd.to_datetime(greeks["timestamp_ns"], utc=True).dt.tz_convert(None)
    delta = greeks.pivot_table(index="datetime", columns="instrument_id", values="delta", aggfunc="last").reindex(index).ffill()
    total = pd.Series(0.0, index=index, name="net_option_delta")
    instruments = registry.by_symbol
    for symbol in registry.symbols:
        pos_col = f"Position_{symbol}"
        if pos_col not in positions or symbol not in delta:
            continue
        multiplier = float(instruments[symbol].multiplier)
        contribution = pd.Series(
            positions[pos_col].to_numpy(dtype=np.float64) * delta[symbol].fillna(0.0).to_numpy(dtype=np.float64) * multiplier,
            index=index,
        )
        total = total.add(contribution, fill_value=0.0)
    return total.fillna(0.0).rename("net_option_delta")


def _normalize_underlying_prices(
    underlying: Optional[pd.DataFrame | pd.Series],
    tape: PreparedOptionTape,
    index: pd.DatetimeIndex,
) -> tuple[pd.Series, str]:
    if underlying is None:
        tape_index = _datetime_index_from_ns(tape.timestamp_ns.astype(np.int64))
        base = pd.Series(
            [_snapshot_underlying_price(tape, i) for i in range(tape.snapshot_count)],
            index=tape_index,
            name="underlying_price",
        )
        return _align_price_series(base, index), "option_chain_index_price"
    if isinstance(underlying, pd.Series):
        series = _coerce_series_index(underlying, "underlying_price")
        return _align_price_series(series, index), "underlying_series"
    if not isinstance(underlying, pd.DataFrame):
        raise TypeError("underlying must be a pandas Series or DataFrame")
    frame = underlying.copy()
    if "timestamp_ns" in frame.columns:
        idx = pd.to_datetime(frame["timestamp_ns"].astype("int64"), utc=True).dt.tz_convert(None)
    elif "time" in frame.columns:
        idx = pd.to_datetime(frame["time"], utc=True, errors="coerce").dt.tz_convert(None)
    elif isinstance(frame.index, pd.DatetimeIndex):
        idx = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True)).tz_convert(None)
    else:
        raise ValueError("underlying DataFrame requires timestamp_ns, time, or DatetimeIndex")
    column = "close" if "close" in frame.columns else ("price" if "price" in frame.columns else None)
    if column is None:
        raise ValueError("underlying DataFrame requires close or price column")
    series = pd.Series(pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=np.float64), index=idx, name="underlying_price")
    return _align_price_series(series, index), f"underlying_dataframe:{column}"


def _align_price_series(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    out = series.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.reindex(index).ffill().bfill()
    if out.isna().any() or bool((out <= 0.0).any()):
        raise ValueError("underlying prices must align to option tape and be finite > 0")
    return out.rename("underlying_price")


def _coerce_series_index(series: pd.Series, name: str) -> pd.Series:
    out = series.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True)
    else:
        out.index = pd.DatetimeIndex(pd.to_datetime(out.index, utc=True))
    out.index = out.index.tz_convert(None)
    out = pd.to_numeric(out, errors="raise").astype("float64")
    out.name = name
    return out


def _datetime_index_from_ns(timestamps_ns: np.ndarray) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(timestamps_ns, utc=True)).tz_convert(None)


def _mark_lookup(tape: PreparedOptionTape) -> Dict[tuple[int, str], float]:
    out: Dict[tuple[int, str], float] = {}
    for snap_idx, ts in enumerate(tape.timestamp_ns):
        slc = tape.snapshot_slice(snap_idx)
        for idx in range(slc.start, slc.stop):
            out[(int(ts), tape.instrument_id[idx])] = float(tape.mark_price[idx])
    return out


def _snapshot_underlying_price(tape: PreparedOptionTape, snapshot_idx: int) -> float:
    rows = tape.snapshot_slice(snapshot_idx)
    for idx in range(rows.start, rows.stop):
        price = tape.index_price[idx] if np.isfinite(tape.index_price[idx]) else tape.forward_price[idx]
        if np.isfinite(price) and price > 0.0:
            return float(price)
    raise ValueError("option tape snapshot has no finite underlying/index price")


def _cash_report(snapshots: Sequence[Dict], index: pd.DatetimeIndex) -> pd.DataFrame:
    currencies = sorted({currency for snap in snapshots for currency in snap["cash"]})
    return pd.DataFrame(
        [{currency: snap["cash"].get(currency, 0.0) for currency in currencies} for snap in snapshots],
        index=index,
        columns=currencies,
    )


def _marks_report(tape: PreparedOptionTape) -> pd.DataFrame:
    rows = []
    for snap_idx, ts in enumerate(tape.timestamp_ns):
        slc = tape.snapshot_slice(snap_idx)
        for idx in range(slc.start, slc.stop):
            rows.append(
                {
                    "timestamp_ns": int(ts),
                    "instrument_id": tape.instrument_id[idx],
                    "bid_price": float(tape.bid_price[idx]),
                    "ask_price": float(tape.ask_price[idx]),
                    "mark_price": float(tape.mark_price[idx]),
                    "index_price": float(tape.index_price[idx]),
                    "forward_price": float(tape.forward_price[idx]),
                    "bid_size": float(tape.bid_size[idx]),
                    "ask_size": float(tape.ask_size[idx]),
                }
            )
    return pd.DataFrame(rows)


def _greeks_report(tape: PreparedOptionTape) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_ns": np.repeat(tape.timestamp_ns, np.diff(tape.row_ptr)),
            "instrument_id": tape.instrument_id,
            "mark_iv": tape.mark_iv,
            "bid_iv": tape.bid_iv,
            "ask_iv": tape.ask_iv,
            "delta": tape.delta,
            "gamma": tape.gamma,
            "vega": tape.vega,
            "theta": tape.theta,
        }
    )


def _fills_report(fills_with_fees: Sequence[tuple]) -> pd.DataFrame:
    rows = []
    for fill, fee in fills_with_fees:
        rows.append(
            {
                "timestamp": fill.timestamp,
                "symbol": fill.symbol,
                "side": fill.side.value,
                "qty": float(fill.qty),
                "price": float(fill.price),
                "notional": float(fill.notional),
                "execution_fee": float(fill.fee),
                "applied_fee": float(fee.fee if fee is not None else fill.fee),
                "fee_currency": fee.currency if fee is not None else "",
                "liquidity": fill.liquidity.value,
                "order_id": fill.order_id,
                "package_id": fill.metadata.get("package_id"),
            }
        )
    return pd.DataFrame(rows)


def _settlements_report(settlements: Sequence) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp_ns": item.timestamp_ns,
                "symbol": item.symbol,
                "settlement_price": item.settlement_price,
                "payoff_per_unit": item.payoff_per_unit,
                "cashflow": item.cashflow,
                "settlement_currency": item.settlement_currency,
                "representation": item.representation.value,
                "itm": item.itm,
                "position_closed": item.position_closed,
            }
            for item in settlements
        ]
    )


def _attribution_report(
    ledger: OptionLedger,
    account: AccountConfig,
    final_equity: float,
    report_ccy: str,
    conversion_rates: Dict[str, float],
) -> pd.DataFrame:
    rows = []
    for currency, amount in ledger.cash.items():
        rate = 1.0 if currency == report_ccy else float(conversion_rates.get(currency, np.nan))
        rows.append({"bucket": "cash", "currency": currency, "amount": float(amount), "reporting_value": float(amount) * rate})
    for currency, fee in ledger.fees.items():
        rate = 1.0 if currency == report_ccy else float(conversion_rates.get(currency, np.nan))
        rows.append({"bucket": "fees", "currency": currency, "amount": -float(fee), "reporting_value": -float(fee) * rate})
    rows.append(
        {
            "bucket": "total",
            "currency": report_ccy,
            "amount": float(final_equity - account.initial_capital),
            "reporting_value": float(final_equity - account.initial_capital),
        }
    )
    return pd.DataFrame(rows)
