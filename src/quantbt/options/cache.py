"""
Prepared option run cache.

The cache is explicit and signature-checked. It is designed for service/WFO
loops where the same option chain tape is replayed with many package choices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pandas as pd

from ..core.orders import OrderIntent
from .packages import OptionPackageIntent, compile_option_package_orders
from .schema import OptionInstrumentRegistry
from .tape import PreparedOptionTape, prepare_option_tape


@dataclass
class OptionPreparedRunCache:
    tape: PreparedOptionTape
    package_orders: Dict[Tuple, Tuple[OrderIntent, ...]] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    @classmethod
    def from_chain(
        cls,
        chain: pd.DataFrame,
        registry: OptionInstrumentRegistry,
        *,
        max_spread_bps: Optional[float] = None,
        max_source_latency_ns: Optional[int] = None,
        convention_signature: Optional[Tuple] = None,
    ) -> "OptionPreparedRunCache":
        tape = prepare_option_tape(
            chain,
            registry,
            max_spread_bps=max_spread_bps,
            max_source_latency_ns=max_source_latency_ns,
            convention_signature=convention_signature,
        )
        return cls(
            tape=tape,
            metadata={
                "cache_type": "OptionPreparedRunCache",
                "snapshot_count": int(tape.snapshot_count),
                "row_count": int(tape.row_count),
                "registry_symbols": tuple(registry.symbols),
                "convention_signature": tape.signature.convention_signature,
            },
        )

    def validate(
        self,
        registry: OptionInstrumentRegistry,
        *,
        timestamps_ns=None,
        convention_signature: Optional[Tuple] = None,
    ) -> None:
        self.tape.validate_compatible(
            registry_signature=registry.signature,
            timestamps_ns=timestamps_ns,
            convention_signature=convention_signature,
        )

    def compile_package(self, package: OptionPackageIntent) -> Tuple[OrderIntent, ...]:
        key = option_package_cache_key(package)
        cached = self.package_orders.get(key)
        if cached is None:
            cached = compile_option_package_orders(package)
            self.package_orders[key] = cached
        return cached

    @property
    def package_cache_size(self) -> int:
        return len(self.package_orders)


def option_package_cache_key(package: OptionPackageIntent) -> Tuple:
    """Return a deterministic key for compiled option package order leaves."""
    return (
        int(package.timestamp_ns),
        str(package.package_id),
        float(package.quantity),
        package.execution_policy.value,
        None if package.max_debit is None else float(package.max_debit),
        None if package.min_credit is None else float(package.min_credit),
        tuple(
            (
                leg.instrument_id,
                leg.side.value,
                float(leg.ratio),
                leg.order_type.value,
                None if leg.limit_price is None else float(leg.limit_price),
                leg.tif.value,
                leg.role,
                leg.tag,
                tuple(sorted((str(k), _stable_value(v)) for k, v in leg.metadata.items())),
            )
            for leg in package.legs
        ),
        package.tag,
        tuple(sorted((str(k), _stable_value(v)) for k, v in package.metadata.items())),
    )


def _stable_value(value):
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        return tuple(sorted((str(k), _stable_value(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_stable_value(item) for item in value)
    return repr(value)
