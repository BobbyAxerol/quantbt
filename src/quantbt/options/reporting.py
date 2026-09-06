"""Cold-path option result, report, and delta-hedge materialization."""

from __future__ import annotations

import hashlib
from typing import Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.results import OptionBacktestResult
from ..core.schema import AccountConfig
from .hedging import OptionHedgeConfig, run_delta_hedge_path
from .ledger import OptionLedger
from .margin import OptionLiquidationAudit, OptionMarginRequirement
from .schema import OptionInstrumentRegistry, OptionInstrumentSpec
from .tape import PreparedOptionTape


def snapshot_marks(tape: PreparedOptionTape, snapshot_idx: int) -> Dict[str, float]:
    rows = tape.snapshot_slice(snapshot_idx)
    return {
        tape.instrument_id[idx]: float(tape.mark_price[idx])
        for idx in range(rows.start, rows.stop)
    }


def snapshot_underlyings(tape: PreparedOptionTape, snapshot_idx: int) -> Dict[str, float]:
    rows = tape.snapshot_slice(snapshot_idx)
    out = {}
    registry = tape.registry.by_symbol
    for idx in range(rows.start, rows.stop):
        symbol = tape.instrument_id[idx]
        instrument = registry[symbol]
        price = float(
            tape.index_price[idx]
            if np.isfinite(tape.index_price[idx])
            else tape.forward_price[idx]
        )
        out[instrument.underlying_id] = price
        out[symbol] = price
    return out


def build_option_result(
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
    settlement_records: Sequence[Mapping],
    margin: OptionMarginRequirement,
    margin_timeline: Sequence[Mapping],
    liquidation_audits: Sequence[OptionLiquidationAudit],
    liquidated: bool,
    metadata: Dict,
) -> OptionBacktestResult:
    index = pd.DatetimeIndex(
        pd.to_datetime([snap["timestamp_ns"] for snap in snapshots], utc=True)
    ).tz_convert(None)
    equity = pd.Series(
        [snap["equity"] for snap in snapshots], index=index, name="equity"
    )
    if len(equity.index) != len(set(equity.index)):
        values = equity.index.view("int64").copy()
        for index_position in range(1, len(values)):
            if values[index_position] <= values[index_position - 1]:
                values[index_position] = values[index_position - 1] + 1
        equity.index = pd.DatetimeIndex(values)
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    symbols = list(registry.symbols)
    positions = pd.DataFrame(
        [
            {
                f"Position_{symbol}": snap["positions"].get(symbol, 0.0)
                for symbol in symbols
            }
            for snap in snapshots
        ],
        index=equity.index,
        columns=[f"Position_{symbol}" for symbol in symbols],
    )
    closes = pd.DataFrame(
        [
            {
                f"Close_{symbol}": snap["marks"].get(symbol, np.nan)
                for symbol in symbols
            }
            for snap in snapshots
        ],
        index=equity.index,
        columns=[f"Close_{symbol}" for symbol in symbols],
    ).ffill()
    cash_report = _cash_report(snapshots, equity.index)
    marks_report = _marks_report(tape)
    greeks_report = _greeks_report(tape)
    fills_report = _fills_report(fills_with_fees)
    settlements_report = _settlements_report(settlements, settlement_records)
    margin_timeline_report = pd.DataFrame(margin_timeline)
    liquidation_report = _liquidation_report(liquidation_audits)
    attribution_report = _attribution_report(
        ledger, account, equity.iloc[-1], report_ccy, conversion_rates
    )
    accounting_reconciliation = _accounting_reconciliation(
        fills_report, ledger, conversion_rates, report_ccy
    )
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
            {
                instrument.convention_version
                for instrument in registry.instruments
                if instrument.convention_version
            }
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
            "settlement_policy": metadata.get("settlement_policy"),
            "settlement_certified": bool(
                metadata.get("settlement_certified", False)
            ),
            "accounting_authority": metadata.get("accounting_authority"),
        },
        "option_reports": [
            "fills_report",
            "packages_report",
            "cash_report",
            "marks_report",
            "greeks_report",
            "settlements_report",
            "margin_report",
            "margin_timeline_report",
            "liquidation_report",
            "accounting_reconciliation",
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
        "margin_timeline_report": margin_timeline_report,
        "liquidation_report": liquidation_report,
        "accounting_reconciliation": accounting_reconciliation,
        "attribution_report": attribution_report,
        "run_manifest": run_manifest,
        "ledger_event_report": ledger.event_report(),
        "equity_identity": ledger.equity_identity_report(
            conversion_rates=conversion_rates,
            marks=snapshot_marks(tape, tape.snapshot_count - 1),
            instruments=registry.by_symbol,
            reporting_currency=report_ccy,
        ),
    }
    fees = pd.Series(0.0, index=equity.index, name="fees")
    if len(fees) > 0:
        fees.iloc[-1] = float(
            sum(
                (fee.fee if fee is not None else fill.fee)
                for fill, fee in fills_with_fees
            )
        )
    return OptionBacktestResult(
        equity=equity,
        returns=returns,
        positions=positions,
        closes=closes,
        symbols=symbols,
        initial_capital=float(account.initial_capital),
        leverage=float(account.leverage),
        liquidated=bool(liquidated),
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


def concat_reports(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    items = [frame for frame in frames if frame is not None and not frame.empty]
    return pd.concat(items, ignore_index=True) if items else pd.DataFrame()


def attach_delta_hedge_contract(
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
    path_timestamps = np.concatenate(
        (
            np.array([int(tape.timestamp_ns[0]) - 1], dtype=np.int64),
            tape.timestamp_ns.astype(np.int64),
        )
    )
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
    deltas = _normalize_net_delta(
        net_option_delta, result.greeks_report, positions, registry, index
    )
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
    combined_returns = (
        combined.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    )

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
        "hedge_rebalances": int(hedge_report["should_rebalance"].sum())
        if not hedge_report.empty
        else 0,
        "option_path_method": result.metadata.get(
            "option_path_method", "linear_quote_replay"
        ),
    }
    result.run_manifest["delta_hedge"] = result.metadata["delta_hedge_contract"]
    result.run_manifest["final_equity"] = float(combined.iloc[-1])
    result.metadata["run_manifest"] = result.run_manifest
    return result


def _chain_data_hash(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "0"
    hashed = pd.util.hash_pandas_object(
        frame.sort_index(axis=1), index=False
    ).to_numpy(dtype="uint64")
    return str(int(hashed.sum(dtype="uint64")))


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


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
        instrument.premium_currency.upper() == report_ccy
        and instrument.settlement_currency.upper() == report_ccy
        for instrument in registry.instruments
    )
    if not linear_quote_exact:
        option_equity = result.equity.reindex(index).ffill().bfill().rename(
            "option_equity"
        )
        positions = result.positions.reindex(index).ffill().fillna(0.0)
        closes = result.closes.reindex(index).ffill().bfill()
        fees = result.fees.reindex(index).fillna(0.0)
        result.metadata["option_path_method"] = (
            "event_equity_reindexed_non_quote_currency"
        )
        return option_equity, positions, closes, fees

    cash = float(account.initial_capital)
    pos = {symbol: 0.0 for symbol in symbols}
    fills = (
        result.fills_report.sort_values("timestamp")
        if not result.fills_report.empty
        else pd.DataFrame()
    )
    fill_idx = 0
    equity_rows = []
    position_rows = []
    close_rows = []
    fee_values = []
    mark_by_ts_symbol = _mark_lookup(tape)

    for ts, _dt in zip(path_timestamps, index):
        snap_idx = max(
            0, int(np.searchsorted(tape.timestamp_ns, int(ts), side="right") - 1)
        )
        fee_at_ts = 0.0
        while (
            not fills.empty
            and fill_idx < len(fills)
            and int(fills.iloc[fill_idx]["timestamp"]) <= int(ts)
        ):
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
        marks = {
            symbol: mark_by_ts_symbol.get((mark_ts, symbol), np.nan)
            for symbol in symbols
        }
        marked_value = sum(
            pos.get(symbol, 0.0) * marks[symbol]
            for symbol in symbols
            if np.isfinite(marks[symbol])
        )
        equity_rows.append(cash + marked_value)
        position_rows.append(
            {f"Position_{symbol}": pos.get(symbol, 0.0) for symbol in symbols}
        )
        close_rows.append(
            {f"Close_{symbol}": marks[symbol] for symbol in symbols}
        )
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
        return (
            series.reindex(index)
            .ffill()
            .bfill()
            .fillna(0.0)
            .rename("net_option_delta")
        )
    if greeks_report.empty:
        return pd.Series(0.0, index=index, name="net_option_delta")
    greeks = greeks_report.copy()
    greeks["datetime"] = pd.to_datetime(
        greeks["timestamp_ns"], utc=True
    ).dt.tz_convert(None)
    delta = (
        greeks.pivot_table(
            index="datetime",
            columns="instrument_id",
            values="delta",
            aggfunc="last",
        )
        .reindex(index)
        .ffill()
    )
    total = pd.Series(0.0, index=index, name="net_option_delta")
    instruments = registry.by_symbol
    for symbol in registry.symbols:
        pos_col = f"Position_{symbol}"
        if pos_col not in positions or symbol not in delta:
            continue
        multiplier = float(instruments[symbol].multiplier)
        contribution = pd.Series(
            positions[pos_col].to_numpy(dtype=np.float64)
            * delta[symbol].fillna(0.0).to_numpy(dtype=np.float64)
            * multiplier,
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
            [
                _snapshot_underlying_price(tape, i)
                for i in range(tape.snapshot_count)
            ],
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
        idx = pd.to_datetime(
            frame["timestamp_ns"].astype("int64"), utc=True
        ).dt.tz_convert(None)
    elif "time" in frame.columns:
        idx = pd.to_datetime(
            frame["time"], utc=True, errors="coerce"
        ).dt.tz_convert(None)
    elif isinstance(frame.index, pd.DatetimeIndex):
        idx = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True)).tz_convert(None)
    else:
        raise ValueError(
            "underlying DataFrame requires timestamp_ns, time, or DatetimeIndex"
        )
    column = (
        "close"
        if "close" in frame.columns
        else ("price" if "price" in frame.columns else None)
    )
    if column is None:
        raise ValueError("underlying DataFrame requires close or price column")
    series = pd.Series(
        pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=np.float64),
        index=idx,
        name="underlying_price",
    )
    return _align_price_series(series, index), f"underlying_dataframe:{column}"


def _align_price_series(
    series: pd.Series, index: pd.DatetimeIndex
) -> pd.Series:
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


def _snapshot_underlying_price(
    tape: PreparedOptionTape, snapshot_idx: int
) -> float:
    rows = tape.snapshot_slice(snapshot_idx)
    for idx in range(rows.start, rows.stop):
        price = (
            tape.index_price[idx]
            if np.isfinite(tape.index_price[idx])
            else tape.forward_price[idx]
        )
        if np.isfinite(price) and price > 0.0:
            return float(price)
    raise ValueError("option tape snapshot has no finite underlying/index price")


def _cash_report(
    snapshots: Sequence[Dict], index: pd.DatetimeIndex
) -> pd.DataFrame:
    currencies = sorted(
        {currency for snap in snapshots for currency in snap["cash"]}
    )
    return pd.DataFrame(
        [
            {currency: snap["cash"].get(currency, 0.0) for currency in currencies}
            for snap in snapshots
        ],
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
                "contract_notional": float(fill.qty)
                * float(fill.price)
                * float(fill.metadata.get("contract_multiplier", 1.0)),
                "execution_fee": float(
                    fill.metadata.get("quoted_execution_fee", fill.fee)
                ),
                "applied_fee": float(fee.fee if fee is not None else fill.fee),
                "fee_currency": fee.currency
                if fee is not None
                else str(fill.metadata.get("fee_currency", "")),
                "liquidity": fill.liquidity.value,
                "order_id": fill.order_id,
                "package_id": fill.metadata.get("package_id"),
                "fee_authority": fill.metadata.get(
                    "fee_authority", "execution_quote"
                ),
                "liquidation": bool(fill.metadata.get("liquidation", False)),
            }
        )
    return pd.DataFrame(rows)


def _settlements_report(
    settlements: Sequence, records: Sequence[Mapping]
) -> pd.DataFrame:
    rows = []
    for item, provenance in zip(settlements, records):
        rows.append(
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
                **dict(provenance),
            }
        )
    return pd.DataFrame(rows)


def _liquidation_report(
    audits: Sequence[OptionLiquidationAudit],
) -> pd.DataFrame:
    rows = []
    for audit in audits:
        rows.append(
            {
                "breached": bool(audit.breached),
                "breach_reason": audit.breach_reason,
                "equity_before": float(audit.equity_before),
                "maintenance_margin": float(audit.maintenance_margin),
                "equity_after": float(audit.equity_after),
                "fill_count": len(audit.fills_with_fees),
                **dict(audit.metadata),
            }
        )
    return pd.DataFrame(rows)


def _conversion_rate_to_reporting(
    currency: str,
    conversion_rates: Mapping[str, float],
    reporting_currency: str,
) -> float:
    ccy = str(currency).upper()
    report = str(reporting_currency).upper()
    if ccy == report:
        return 1.0
    if ccy not in conversion_rates:
        raise ValueError(f"missing conversion rate for {ccy}->{report}")
    rate = float(conversion_rates[ccy])
    if rate <= 0.0:
        raise ValueError(f"conversion rate for {ccy}->{report} must be > 0")
    return rate


def _accounting_reconciliation(
    fills_report: pd.DataFrame,
    ledger: OptionLedger,
    conversion_rates: Mapping[str, float],
    reporting_currency: str,
) -> Dict:
    fill_fees: Dict[str, float] = {}
    if not fills_report.empty:
        for currency, group in fills_report.groupby("fee_currency", dropna=False):
            key = str(currency or "").upper()
            if key:
                fill_fees[key] = float(group["applied_fee"].sum())
    currencies = sorted(set(fill_fees).union(ledger.fees))
    per_currency = {
        currency: {
            "fills": float(fill_fees.get(currency, 0.0)),
            "ledger": float(ledger.fees.get(currency, 0.0)),
            "difference": float(
                fill_fees.get(currency, 0.0) - ledger.fees.get(currency, 0.0)
            ),
        }
        for currency in currencies
    }
    total_fills = sum(
        values["fills"]
        * _conversion_rate_to_reporting(
            currency, conversion_rates, reporting_currency
        )
        for currency, values in per_currency.items()
    )
    total_ledger = sum(
        values["ledger"]
        * _conversion_rate_to_reporting(
            currency, conversion_rates, reporting_currency
        )
        for currency, values in per_currency.items()
    )
    return {
        "reporting_currency": str(reporting_currency).upper(),
        "per_currency": per_currency,
        "fills_fee_reporting_value": float(total_fills),
        "ledger_fee_reporting_value": float(total_ledger),
        "reconciled": bool(
            all(
                abs(values["difference"]) <= 1e-12
                for values in per_currency.values()
            )
        ),
    }


def _attribution_report(
    ledger: OptionLedger,
    account: AccountConfig,
    final_equity: float,
    report_ccy: str,
    conversion_rates: Dict[str, float],
) -> pd.DataFrame:
    rows = []
    for currency, amount in ledger.cash.items():
        rate = (
            1.0
            if currency == report_ccy
            else float(conversion_rates.get(currency, np.nan))
        )
        rows.append(
            {
                "bucket": "cash",
                "currency": currency,
                "amount": float(amount),
                "reporting_value": float(amount) * rate,
            }
        )
    for currency, fee in ledger.fees.items():
        rate = (
            1.0
            if currency == report_ccy
            else float(conversion_rates.get(currency, np.nan))
        )
        rows.append(
            {
                "bucket": "fees",
                "currency": currency,
                "amount": -float(fee),
                "reporting_value": -float(fee) * rate,
            }
        )
    rows.append(
        {
            "bucket": "total",
            "currency": report_ccy,
            "amount": float(final_equity - account.initial_capital),
            "reporting_value": float(final_equity - account.initial_capital),
        }
    )
    return pd.DataFrame(rows)


__all__ = [
    "attach_delta_hedge_contract",
    "build_option_result",
    "concat_reports",
    "snapshot_marks",
    "snapshot_underlyings",
]
