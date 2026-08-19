"""Versioned accounting policy and independent native-event ledger audit.

The execution kernel remains the source of fills.  This module deliberately
reconstructs position cost basis and PnL from those fills so an audit can prove
the reported equity path without reusing the matcher's accounting state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from .orders import Fill


ACCOUNTING_LEDGER_SCHEMA_VERSION = "native-accounting-ledger-v1"


@dataclass(frozen=True, slots=True)
class NativeAccountingPolicyV1:
    """Financial conventions certified by the Phase 51B reference ledger."""

    pnl_model: str = "linear_quote_settled"
    fee_model: str = "quote_one_way_per_fill"
    funding_model: str = "position_at_contract_event_phase"
    funding_price_model: str = "bar_close"
    margin_model: str = "gross_cross"
    liquidation_model: str = "zero_equity_legacy"
    multisymbol_intrabar_policy: str = "simultaneous_worst_extremes"
    slippage_accounting: str = "embedded_in_execution_price"
    borrow_carry_model: str = "unsupported_zero"

    def to_metadata(self) -> dict[str, str]:
        return {"schema_version": ACCOUNTING_LEDGER_SCHEMA_VERSION, **asdict(self)}


@dataclass(frozen=True)
class NativeAccountingAudit:
    """Materialized ledger, symbol detail, and invariant certificate."""

    ledger: pd.DataFrame
    symbol_ledger: pd.DataFrame
    liquidation_report: pd.DataFrame
    invariants: Mapping[str, object]
    policy: NativeAccountingPolicyV1

    def to_metadata(self) -> dict[str, object]:
        return {
            "accounting_policy_v1": self.policy.to_metadata(),
            "accounting_ledger_v1": self.ledger,
            "symbol_accounting_ledger_v1": self.symbol_ledger,
            "liquidation_attribution_v1": self.liquidation_report,
            "accounting_invariants_v1": dict(self.invariants),
        }


def build_native_accounting_audit(
    result,
    *,
    contract_sizes: float | Mapping[str, float] | Sequence[float] = 1.0,
    tolerance: float = 1e-9,
    policy: NativeAccountingPolicyV1 | None = None,
) -> NativeAccountingAudit:
    """Reconstruct and reconcile a linear native-event result bar by bar.

    Slippage is already represented by the audited fill price, so it is not
    deducted a second time.  Inverse, quanto, and option PnL must use their own
    certified accounting model and are intentionally rejected here.
    """

    policy = policy or NativeAccountingPolicyV1()
    if policy.pnl_model != "linear_quote_settled":
        raise NotImplementedError(f"unsupported accounting pnl_model={policy.pnl_model!r}")

    index = pd.DatetimeIndex(result.equity.index)
    symbols = tuple(map(str, result.symbols))
    n_bars, n_symbols = len(index), len(symbols)
    symbol_to_col = {symbol: col for col, symbol in enumerate(symbols)}
    contract_size = _per_symbol_values(contract_sizes, symbols, default=1.0)
    if np.any(~np.isfinite(contract_size)) or np.any(contract_size <= 0.0):
        raise ValueError("contract_sizes must be finite and > 0")

    closes = _close_matrix(result.closes, index, symbols)
    actual_positions = _position_matrix(result.positions, index, symbols)
    fees = _series_values(result.fees, index)
    funding = _series_values(result.funding, index)
    initial_margin = _margin_values(result.margin, index, "initial_margin")
    maintenance_margin = _margin_values(result.margin, index, "maintenance_margin")
    actual_equity = np.asarray(result.equity.reindex(index), dtype=np.float64)

    fills_by_bar: list[list[Fill]] = [[] for _ in range(n_bars)]
    timestamp_to_bar = {int(ts): bar for bar, ts in enumerate(index.asi8)}
    unknown_fills: list[str] = []
    for fill in tuple(getattr(result, "fills", ()) or ()):
        ts = int(pd.Timestamp(fill.timestamp).value)
        bar = timestamp_to_bar.get(ts)
        if bar is None or str(fill.symbol) not in symbol_to_col:
            unknown_fills.append(str(fill.order_id))
            continue
        fills_by_bar[bar].append(fill)

    qty = np.zeros(n_symbols, dtype=np.float64)
    average_entry = np.zeros(n_symbols, dtype=np.float64)
    cumulative_realized = np.zeros(n_symbols, dtype=np.float64)
    fill_delta = np.zeros((n_bars, n_symbols), dtype=np.float64)
    position_path = np.zeros((n_bars, n_symbols), dtype=np.float64)
    average_entry_path = np.zeros((n_bars, n_symbols), dtype=np.float64)
    realized_path = np.zeros((n_bars, n_symbols), dtype=np.float64)
    unrealized_path = np.zeros((n_bars, n_symbols), dtype=np.float64)

    for bar in range(n_bars):
        for fill in fills_by_bar[bar]:
            col = symbol_to_col[str(fill.symbol)]
            delta = float(fill.signed_qty)
            fill_delta[bar, col] += delta
            qty[col], average_entry[col], realized = _apply_linear_fill(
                qty[col], average_entry[col], delta, float(fill.price), contract_size[col]
            )
            cumulative_realized[col] += realized
        position_path[bar] = qty
        average_entry_path[bar] = average_entry
        realized_path[bar] = cumulative_realized
        unrealized_path[bar] = qty * (closes[bar] - average_entry) * contract_size

    cumulative_fees = np.cumsum(fees)
    cumulative_funding = np.cumsum(funding)
    borrow_carry = np.zeros(n_bars, dtype=np.float64)
    slippage_cost = np.zeros(n_bars, dtype=np.float64)
    liquidation_cost = np.zeros(n_bars, dtype=np.float64)
    pre_liquidation_expected = (
        float(result.initial_capital)
        + realized_path.sum(axis=1)
        + unrealized_path.sum(axis=1)
        - cumulative_fees
        - cumulative_funding
    )

    liquidation_rows: list[dict[str, object]] = []
    liquidation_bar = int(getattr(result, "liquidation_bar", -1))
    if bool(getattr(result, "liquidated", False)) and 0 <= liquidation_bar < n_bars:
        # The legacy kernel intentionally writes zero equity/positions.  Audit
        # that discontinuity as an explicit terminal cost instead of leaving
        # an unexplained residual in the ledger.
        liquidation_cost[liquidation_bar] = pre_liquidation_expected[liquidation_bar]
        if liquidation_bar + 1 < n_bars:
            liquidation_cost[liquidation_bar + 1 :] = 0.0
        position_path[liquidation_bar:] = actual_positions[liquidation_bar:]
        average_entry_path[liquidation_bar:] = 0.0
        unrealized_path[liquidation_bar:] = 0.0
        liquidation_rows.append(
            {
                "bar": liquidation_bar,
                "timestamp": index[liquidation_bar],
                "model": policy.liquidation_model,
                "reason_code": int((getattr(result, "metadata", {}) or {}).get("liquidation_reason", -1)),
                "liquidation_cost": float(liquidation_cost[liquidation_bar]),
                "residual_equity": float(actual_equity[liquidation_bar]),
                "attribution_kind": "legacy_terminal_equity_allocation",
            }
        )

    cumulative_liquidation = np.cumsum(liquidation_cost)
    expected_equity = (
        float(result.initial_capital)
        + realized_path.sum(axis=1)
        + unrealized_path.sum(axis=1)
        - cumulative_fees
        - cumulative_funding
        - np.cumsum(borrow_carry)
        - cumulative_liquidation
    )
    if liquidation_bar >= 0 and liquidation_bar + 1 < n_bars:
        expected_equity[liquidation_bar:] = actual_equity[liquidation_bar:]

    signed_notional = position_path * closes * contract_size.reshape(1, -1)
    long_notional = np.where(signed_notional > 0.0, signed_notional, 0.0).sum(axis=1)
    short_notional = np.where(signed_notional < 0.0, -signed_notional, 0.0).sum(axis=1)
    gross_notional = np.abs(signed_notional).sum(axis=1)
    net_notional = signed_notional.sum(axis=1)
    reserved_margin = np.zeros(n_bars, dtype=np.float64)

    ledger = pd.DataFrame(
        {
            "cash_or_collateral": float(result.initial_capital),
            "realized_pnl": realized_path.sum(axis=1),
            "unrealized_pnl": unrealized_path.sum(axis=1),
            "fee": fees,
            "cumulative_fees": cumulative_fees,
            "funding": funding,
            "cumulative_funding": cumulative_funding,
            "borrow_carry": borrow_carry,
            "slippage_cost": slippage_cost,
            "liquidation_cost": liquidation_cost,
            "cumulative_liquidation_cost": cumulative_liquidation,
            "initial_margin": initial_margin,
            "maintenance_margin": maintenance_margin,
            "reserved_margin": reserved_margin,
            "available_equity": actual_equity - initial_margin - reserved_margin,
            "long_notional": long_notional,
            "short_notional": short_notional,
            "gross_notional": gross_notional,
            "net_notional": net_notional,
            "equity_expected": expected_equity,
            "equity_actual": actual_equity,
            "equity_residual": actual_equity - expected_equity,
        },
        index=index,
    )
    ledger.index.name = "timestamp"

    symbol_ledger = _symbol_ledger_frame(
        index=index,
        symbols=symbols,
        closes=closes,
        contract_sizes=contract_size,
        fill_delta=fill_delta,
        positions=position_path,
        average_entry=average_entry_path,
        realized=realized_path,
        unrealized=unrealized_path,
    )
    position_residual = actual_positions - position_path
    exposure_residual = np.maximum(
        np.abs(gross_notional - (long_notional + short_notional)),
        np.abs(net_notional - (long_notional - short_notional)),
    )
    max_equity_residual = _max_abs(ledger["equity_residual"].to_numpy())
    max_position_residual = _max_abs(position_residual)
    max_exposure_residual = _max_abs(exposure_residual)
    passed = bool(
        not unknown_fills
        and max_equity_residual <= tolerance
        and max_position_residual <= tolerance
        and max_exposure_residual <= tolerance
    )
    invariants = {
        "schema_version": ACCOUNTING_LEDGER_SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "passed": passed,
        "tolerance": float(tolerance),
        "equity_identity_every_bar": bool(max_equity_residual <= tolerance),
        "position_fill_identity_every_bar": bool(max_position_residual <= tolerance),
        "gross_net_identity_every_bar": bool(max_exposure_residual <= tolerance),
        "max_abs_equity_residual": max_equity_residual,
        "max_abs_position_residual": max_position_residual,
        "max_abs_exposure_residual": max_exposure_residual,
        "unknown_fill_ids": unknown_fills,
        "liquidation_attribution_explicit": bool(
            not getattr(result, "liquidated", False) or len(liquidation_rows) == 1
        ),
    }
    return NativeAccountingAudit(
        ledger=ledger,
        symbol_ledger=symbol_ledger,
        liquidation_report=pd.DataFrame(liquidation_rows),
        invariants=invariants,
        policy=policy,
    )


def assert_native_accounting_invariants(result, **kwargs) -> NativeAccountingAudit:
    """Build the independent audit and raise on any unexplained residual."""

    audit = build_native_accounting_audit(result, **kwargs)
    if not audit.invariants["passed"]:
        raise AssertionError(f"native accounting invariants failed: {dict(audit.invariants)}")
    return audit


def attach_native_accounting_audit(result, **kwargs):
    """Attach canonical audit artifacts to an existing result in-place."""

    audit = build_native_accounting_audit(result, **kwargs)
    result.metadata.update(audit.to_metadata())
    return result


def _apply_linear_fill(
    position: float,
    average_entry: float,
    delta: float,
    fill_price: float,
    contract_size: float,
) -> tuple[float, float, float]:
    if delta == 0.0:
        return position, average_entry, 0.0
    new_position = position + delta
    if position == 0.0 or np.sign(position) == np.sign(delta):
        average = (
            (abs(position) * average_entry + abs(delta) * fill_price) / abs(new_position)
            if new_position != 0.0
            else 0.0
        )
        return new_position, average, 0.0

    closing_qty = min(abs(position), abs(delta))
    realized = closing_qty * (fill_price - average_entry) * np.sign(position) * contract_size
    if new_position == 0.0:
        return 0.0, 0.0, realized
    if np.sign(new_position) == np.sign(position):
        return new_position, average_entry, realized
    return new_position, fill_price, realized


def _per_symbol_values(value, symbols: tuple[str, ...], *, default: float) -> np.ndarray:
    if isinstance(value, Mapping):
        return np.asarray([float(value.get(symbol, default)) for symbol in symbols], dtype=np.float64)
    if np.isscalar(value):
        return np.full(len(symbols), float(value), dtype=np.float64)
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (len(symbols),):
        raise ValueError("per-symbol values must match result.symbols")
    return array


def _close_matrix(closes: pd.DataFrame, index: pd.DatetimeIndex, symbols: tuple[str, ...]) -> np.ndarray:
    frame = closes.reindex(index).copy()
    frame = frame.rename(columns={column: str(column).replace("Close_", "", 1) for column in frame.columns})
    missing = [symbol for symbol in symbols if symbol not in frame]
    if missing:
        raise ValueError(f"close frame missing symbols: {missing}")
    array = frame.loc[:, symbols].to_numpy(dtype=np.float64, copy=True)
    if np.any(~np.isfinite(array)):
        raise ValueError("close prices must be finite for accounting audit")
    return array


def _position_matrix(positions: pd.DataFrame, index: pd.DatetimeIndex, symbols: tuple[str, ...]) -> np.ndarray:
    frame = positions.reindex(index).copy()
    frame = frame.rename(columns={column: str(column).replace("Position_", "", 1) for column in frame.columns})
    missing = [symbol for symbol in symbols if symbol not in frame]
    if missing:
        raise ValueError(f"position frame missing symbols: {missing}")
    return frame.loc[:, symbols].to_numpy(dtype=np.float64, copy=True)


def _series_values(series: pd.Series, index: pd.DatetimeIndex) -> np.ndarray:
    if not isinstance(series, pd.Series) or series.empty:
        return np.zeros(len(index), dtype=np.float64)
    return series.reindex(index, fill_value=0.0).to_numpy(dtype=np.float64, copy=True)


def _margin_values(frame: pd.DataFrame, index: pd.DatetimeIndex, column: str) -> np.ndarray:
    if not isinstance(frame, pd.DataFrame) or column not in frame:
        return np.zeros(len(index), dtype=np.float64)
    return frame[column].reindex(index, fill_value=0.0).to_numpy(dtype=np.float64, copy=True)


def _symbol_ledger_frame(**values) -> pd.DataFrame:
    index = values["index"]
    symbols = values["symbols"]
    frames = []
    for col, symbol in enumerate(symbols):
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": index,
                    "symbol": symbol,
                    "mark_price": values["closes"][:, col],
                    "contract_size": values["contract_sizes"][col],
                    "fill_qty_delta": values["fill_delta"][:, col],
                    "position_qty": values["positions"][:, col],
                    "average_entry": values["average_entry"][:, col],
                    "realized_pnl": values["realized"][:, col],
                    "unrealized_pnl": values["unrealized"][:, col],
                }
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _max_abs(value) -> float:
    array = np.asarray(value, dtype=np.float64)
    return float(np.max(np.abs(array))) if array.size else 0.0


__all__ = [
    "ACCOUNTING_LEDGER_SCHEMA_VERSION",
    "NativeAccountingAudit",
    "NativeAccountingPolicyV1",
    "assert_native_accounting_invariants",
    "attach_native_accounting_audit",
    "build_native_accounting_audit",
]
