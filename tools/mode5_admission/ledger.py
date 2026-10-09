"""Independent fixed-fill arithmetic; never generates or executes orders."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LedgerWitness:
    initial_capital: float
    fill_count: int
    equity: np.ndarray
    positions: np.ndarray
    fees: np.ndarray
    turnover: np.ndarray
    closed_campaigns: tuple[dict, ...]
    open_campaigns: tuple[dict, ...]


def reconcile_fills(index, closes, fills, *, initial_capital, contract_size=1.0,
                    fee_rate=None, atol=1e-8) -> LedgerWitness:
    """Reconstruct linear MTM from actual fills under a no-funding contract.

    This independent reducer intentionally has no matching, signals, margin
    acceptance or liquidation logic. Its inputs are the engine's executed
    events, including terminal fills; it cannot qualify hypothetical fills.
    """
    closes = np.asarray(closes, dtype=float)
    if len(index) != len(closes) or not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("ledger requires a unique chronological price calendar")
    if not np.isfinite(closes).all() or (closes <= 0).any():
        raise ValueError("ledger prices must be finite and positive")
    if initial_capital <= 0 or contract_size <= 0:
        raise ValueError("capital and contract size must be positive")
    grouped = defaultdict(list)
    previous_bar = -1
    for fill in fills:
        bar = index.get_indexer([fill.timestamp])[0]
        if bar < 0 or bar < previous_bar:
            raise ValueError("fills must belong to the calendar in execution order")
        previous_bar = bar
        grouped[bar].append(fill)
    equity, positions, fees, turnover = (np.zeros(len(index)) for _ in range(4))
    account, position, campaign = float(initial_capital), 0., None
    closed = []
    for bar, close in enumerate(closes):
        if bar:
            account += position * (close - closes[bar - 1]) * contract_size
        for fill in grouped[bar]:
            delta = float(fill.signed_qty)
            price, fee = float(fill.price), float(fill.fee)
            if not all(np.isfinite((delta, price, fee))) or delta == 0 or price <= 0 or fee < 0:
                raise ValueError("invalid actual fill")
            notional = abs(delta) * price * contract_size
            if fee_rate is not None and not np.isclose(fee, notional * fee_rate, rtol=0, atol=atol):
                raise ValueError("one-way fill fee does not reconcile")
            account += delta * (close - price) * contract_size - fee
            fees[bar] += fee
            turnover[bar] += notional
            old_position = position
            position += delta
            # A reversal contains a closing and an opening allocation of the
            # same real fill. Costs are split by executed quantity, not labels.
            closing = min(abs(old_position), abs(delta)) if old_position * delta < 0 else 0.
            opening = abs(delta) - closing
            if closing and campaign is not None:
                campaign["cash_pnl"] -= delta / abs(delta) * closing * price * contract_size
                campaign["fees"] += fee * closing / abs(delta)
                campaign["exit_qty"] += closing
                if position == 0 or old_position * position < 0:
                    campaign["end"] = str(index[bar])
                    campaign["net_pnl"] = campaign["cash_pnl"] - campaign["fees"]
                    closed.append(campaign)
                    campaign = None
            if opening:
                if campaign is None:
                    campaign = dict(start=str(index[bar]), side=int(np.sign(delta)),
                                    cash_pnl=0., fees=0., entry_qty=0., exit_qty=0.)
                campaign["cash_pnl"] -= np.sign(delta) * opening * price * contract_size
                campaign["fees"] += fee * opening / abs(delta)
                campaign["entry_qty"] += opening
        equity[bar], positions[bar] = account, position
    opened = () if campaign is None else (campaign | {
        "remaining_qty": position,
        "marked_net_pnl": campaign["cash_pnl"] + position * closes[-1] * contract_size - campaign["fees"],
    },)
    return LedgerWitness(float(initial_capital), sum(map(len, grouped.values())),
                         equity, positions, fees, turnover, tuple(closed), opened)


def assert_accounting(result, witness: LedgerWitness, *, atol=1e-8) -> None:
    for name in ("equity", "positions", "fees"):
        observed = np.asarray(getattr(result, name), dtype=float).reshape(-1)
        np.testing.assert_allclose(observed, getattr(witness, name), rtol=0, atol=atol,
                                   err_msg=f"actual-engine {name} mismatch")
    if "turnover" not in result.diagnostics:
        raise ValueError("audit turnover path is required for admission")
    np.testing.assert_allclose(result.diagnostics["turnover"].to_numpy(), witness.turnover,
                               rtol=0, atol=atol, err_msg="actual-engine turnover mismatch")
    pnl = sum(row["net_pnl"] for row in witness.closed_campaigns)
    pnl += sum(row["marked_net_pnl"] for row in witness.open_campaigns)
    if len(witness.equity):
        np.testing.assert_allclose(witness.equity[-1] - witness.initial_capital,
                                   pnl, rtol=0, atol=atol,
                                   err_msg="campaign/account net PnL mismatch")
