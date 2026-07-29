"""
Option hedge policy primitives.

Hedge accounting is intentionally explicit about ordering: hedge PnL for a
price move is earned by the hedge quantity held before that move; rebalance
decisions are evaluated after option package fills and Greek recomputation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from .greeks import OptionGreeks
from .ledger import OptionLedger
from .schema import OptionInstrumentSpec


class OptionHedgePolicyType(str, Enum):
    FIXED_THRESHOLD = "fixed_threshold"
    HYSTERESIS_BAND = "hysteresis_band"
    TIME_BASED = "time_based"
    REALIZED_VOL_SCALED_BAND = "realized_vol_scaled_band"


@dataclass(frozen=True)
class OptionHedgeConfig:
    policy: OptionHedgePolicyType = OptionHedgePolicyType.FIXED_THRESHOLD
    target_delta: float = 0.0
    threshold: float = 0.05
    enter_band: float = 0.10
    exit_band: float = 0.03
    rebalance_interval_ns: int = 0
    realized_vol_window: int = 20
    realized_vol_multiplier: float = 1.0
    min_band: float = 0.01
    hedge_contract_multiplier: float = 1.0
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy", _coerce_policy(self.policy))
        if self.threshold < 0.0 or self.enter_band < 0.0 or self.exit_band < 0.0:
            raise ValueError("threshold and bands must be >= 0")
        if self.exit_band > self.enter_band:
            raise ValueError("exit_band must be <= enter_band")
        if self.rebalance_interval_ns < 0:
            raise ValueError("rebalance_interval_ns must be >= 0")
        if self.realized_vol_window <= 1:
            raise ValueError("realized_vol_window must be > 1")
        if self.realized_vol_multiplier < 0.0 or self.min_band < 0.0:
            raise ValueError("realized_vol_multiplier and min_band must be >= 0")
        if self.hedge_contract_multiplier <= 0.0:
            raise ValueError("hedge_contract_multiplier must be > 0")


@dataclass(frozen=True)
class HedgeDecision:
    timestamp_ns: int
    net_option_delta: float
    previous_hedge_qty: float
    target_hedge_qty: float
    trade_qty: float
    should_rebalance: bool
    reason: str
    band: float


@dataclass(frozen=True)
class HedgePathResult:
    hedge_report: pd.DataFrame
    final_hedge_qty: float
    hedge_pnl: float
    decisions: tuple[HedgeDecision, ...]
    metadata: Dict


def compute_net_option_delta(
    ledger: OptionLedger,
    greeks_by_symbol: Dict[str, OptionGreeks],
    instruments: Dict[str, OptionInstrumentSpec],
) -> float:
    """Return portfolio option delta after package fills and Greek recompute."""
    total = 0.0
    for symbol, position in ledger.positions.items():
        if position.is_flat:
            continue
        greek = greeks_by_symbol.get(symbol)
        instrument = instruments.get(symbol)
        if greek is None or instrument is None:
            raise ValueError(f"missing Greek or instrument for {symbol}")
        total += float(position.qty) * float(greek.delta) * float(instrument.multiplier)
    return float(total)


def hedge_decision(
    *,
    timestamp_ns: int,
    net_option_delta: float,
    current_hedge_qty: float,
    config: OptionHedgeConfig,
    last_rebalance_timestamp_ns: Optional[int] = None,
    underlying_prices: Optional[Sequence[float]] = None,
    currently_active: bool = False,
) -> HedgeDecision:
    """Decide whether to rebalance the hedge after Greek recomputation."""
    target_qty = (float(config.target_delta) - float(net_option_delta)) / float(config.hedge_contract_multiplier)
    trade_qty = target_qty - float(current_hedge_qty)
    band = _active_band(config, underlying_prices)
    reason = "within_band"
    should = False
    abs_trade = abs(trade_qty)
    if config.policy is OptionHedgePolicyType.FIXED_THRESHOLD:
        should = abs_trade >= config.threshold
        reason = "fixed_threshold" if should else reason
    elif config.policy is OptionHedgePolicyType.HYSTERESIS_BAND:
        threshold = config.exit_band if currently_active else config.enter_band
        should = abs_trade >= threshold
        reason = "hysteresis_exit_band" if currently_active and should else ("hysteresis_enter_band" if should else reason)
        band = threshold
    elif config.policy is OptionHedgePolicyType.TIME_BASED:
        due = last_rebalance_timestamp_ns is None or int(timestamp_ns) - int(last_rebalance_timestamp_ns) >= config.rebalance_interval_ns
        should = due and abs_trade > 1e-12
        reason = "time_based_due" if should else "time_based_not_due"
    elif config.policy is OptionHedgePolicyType.REALIZED_VOL_SCALED_BAND:
        should = abs_trade >= band
        reason = "realized_vol_scaled_band" if should else reason
    return HedgeDecision(
        timestamp_ns=int(timestamp_ns),
        net_option_delta=float(net_option_delta),
        previous_hedge_qty=float(current_hedge_qty),
        target_hedge_qty=float(target_qty),
        trade_qty=float(trade_qty if should else 0.0),
        should_rebalance=bool(should),
        reason=reason,
        band=float(band),
    )


def run_delta_hedge_path(
    timestamps_ns: Sequence[int],
    underlying_prices: Sequence[float],
    net_option_deltas: Sequence[float],
    config: OptionHedgeConfig,
    *,
    initial_hedge_qty: float = 0.0,
) -> HedgePathResult:
    """
    Simulate hedge PnL and rebalances over a path.

    At bar `t`, PnL from `price[t-1] -> price[t]` uses the hedge quantity held
    at `t-1`. Only after that move do we evaluate the new option delta and
    rebalance.
    """
    ts = np.asarray(timestamps_ns, dtype=np.int64)
    prices = np.asarray(underlying_prices, dtype=np.float64)
    deltas = np.asarray(net_option_deltas, dtype=np.float64)
    if len(ts) == 0 or len(ts) != len(prices) or len(ts) != len(deltas):
        raise ValueError("timestamps, prices and deltas must be non-empty and equal length")
    if bool((prices <= 0.0).any()) or bool((~np.isfinite(prices)).any()):
        raise ValueError("underlying prices must be finite and > 0")
    hedge_qty = float(initial_hedge_qty)
    hedge_pnl = 0.0
    last_rebalance_ts: Optional[int] = None
    active = abs(hedge_qty) > 1e-12
    rows = []
    decisions = []
    for i in range(len(ts)):
        pnl = 0.0
        if i > 0:
            pnl = hedge_qty * (prices[i] - prices[i - 1]) * config.hedge_contract_multiplier
            hedge_pnl += pnl
        decision = hedge_decision(
            timestamp_ns=int(ts[i]),
            net_option_delta=float(deltas[i]),
            current_hedge_qty=hedge_qty,
            config=config,
            last_rebalance_timestamp_ns=last_rebalance_ts,
            underlying_prices=prices[max(0, i - config.realized_vol_window + 1) : i + 1],
            currently_active=active,
        )
        if decision.should_rebalance:
            hedge_qty += decision.trade_qty
            last_rebalance_ts = int(ts[i])
            active = abs(hedge_qty) > 1e-12
        decisions.append(decision)
        rows.append(
            {
                "timestamp_ns": int(ts[i]),
                "underlying_price": float(prices[i]),
                "prior_hedge_qty": decision.previous_hedge_qty,
                "net_option_delta": decision.net_option_delta,
                "hedge_pnl_for_prior_move": float(pnl),
                "cumulative_hedge_pnl": float(hedge_pnl),
                "target_hedge_qty": decision.target_hedge_qty,
                "trade_qty": decision.trade_qty,
                "hedge_qty_after": float(hedge_qty),
                "should_rebalance": decision.should_rebalance,
                "reason": decision.reason,
                "band": decision.band,
            }
        )
    return HedgePathResult(
        hedge_report=pd.DataFrame(rows),
        final_hedge_qty=float(hedge_qty),
        hedge_pnl=float(hedge_pnl),
        decisions=tuple(decisions),
        metadata={"policy": config.policy.value, "hedge_contract_multiplier": config.hedge_contract_multiplier},
    )


def _active_band(config: OptionHedgeConfig, prices: Optional[Sequence[float]]) -> float:
    if config.policy is not OptionHedgePolicyType.REALIZED_VOL_SCALED_BAND:
        return float(config.threshold)
    if prices is None or len(prices) < 2:
        return float(config.min_band)
    arr = np.asarray(prices, dtype=np.float64)
    returns = np.diff(np.log(arr))
    realized = float(np.std(returns, ddof=1)) if len(returns) > 1 else abs(float(returns[0]))
    return max(float(config.min_band), realized * float(config.realized_vol_multiplier))


def _coerce_policy(value) -> OptionHedgePolicyType:
    if isinstance(value, OptionHedgePolicyType):
        return value
    try:
        return OptionHedgePolicyType(str(value))
    except ValueError as exc:
        raise ValueError("invalid option hedge policy") from exc
