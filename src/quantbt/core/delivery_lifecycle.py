"""Bounded pre-expiry flatten/roll admission for the existing event matcher.

No cash settlement is synthesized. Explicit expiry metadata is authoritative;
native fills/fees/margin remain owned by the existing execution endpoint.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .orders import OrderAction, OrderCommand
from .schema import OrderSide, OrderType


@dataclass(frozen=True)
class DeliveryContract:
    symbol: str
    expires_at: pd.Timestamp
    flatten_at: pd.Timestamp
    source_id: str

    def __post_init__(self):
        for name in ("expires_at", "flatten_at"):
            ts = pd.Timestamp(getattr(self, name))
            if ts.tzinfo is None or pd.isna(ts):
                raise ValueError("delivery event timestamps must be explicit and aware")
            object.__setattr__(self, name, ts.tz_convert("UTC"))
        if not self.symbol or not self.source_id or self.flatten_at >= self.expires_at:
            raise ValueError("delivery requires authoritative source and flatten strictly before expiry")


@dataclass(frozen=True)
class DeliveryLifecycle:
    contracts: tuple[DeliveryContract, ...]
    expiry_policy: str = "pre_expiry_flatten_v1"
    max_close_qty: float = 1e12

    def __post_init__(self):
        object.__setattr__(self, "contracts", tuple(self.contracts))
        if self.expiry_policy != "pre_expiry_flatten_v1":
            raise NotImplementedError("delivery cash settlement is not this pre-expiry execution contract")
        if (not self.contracts or len({c.symbol for c in self.contracts}) != len(self.contracts)
                or not np.isfinite(self.max_close_qty) or self.max_close_qty <= 0):
            raise ValueError("delivery lifecycle requires unique instruments and finite closing capacity")

    def compile(self, commands, index):
        by_symbol = {c.symbol: c for c in self.contracts}
        for command in commands:
            contract = by_symbol.get(command.symbol)
            if (contract is not None and command.action in {OrderAction.PLACE, OrderAction.REPLACE}
                    and pd.Timestamp(command.timestamp) >= contract.flatten_at):
                raise ValueError("delivery order at/after pre-expiry flatten is not tradable")
        result = list(commands)
        for contract in self.contracts:
            if index[0] <= contract.flatten_at <= index[-1]:
                if contract.flatten_at not in index:
                    raise ValueError("delivery flatten timestamp is missing from exact market calendar")
                result.append(OrderCommand(contract.flatten_at, OrderAction.CANCEL_ALL, symbol=contract.symbol))
                for side in (OrderSide.BUY, OrderSide.SELL):
                    result.append(OrderCommand(contract.flatten_at, symbol=contract.symbol,
                        side=side, order_type=OrderType.MARKET, qty=self.max_close_qty,
                        reduce_only=True, order_id=f"delivery-flat:{contract.symbol}:{side.value}"))
        return tuple(sorted(result, key=lambda c: pd.Timestamp(c.timestamp)))

    def reconcile(self, result):
        for contract in self.contracts:
            positions = result.positions[f"Position_{contract.symbol}"]
            closed = positions.loc[positions.index >= contract.flatten_at]
            if len(closed) and not np.all(np.abs(closed.to_numpy()) <= 1e-12):
                raise RuntimeError("delivery pre-expiry flatten failed: account is not flat")
        result.metadata["delivery_lifecycle"] = dict(policy=self.expiry_policy,
            cash_settlement=False, symbol_inferred_expiry=False,
            financial_authority="original_event_account", expiry_flat_reconciled=True)
