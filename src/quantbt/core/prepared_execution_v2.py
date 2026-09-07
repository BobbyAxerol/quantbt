"""Typed preparation plan joining one V2 market and instrument registry."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping, Optional

from .instrument_registry_v2 import InstrumentRegistryV2
from .market_calendar_v2 import PreparedMarketHandleV2


PREPARED_EXECUTION_V2_SCHEMA = "prepared-execution-v2"


@dataclass(frozen=True, slots=True)
class PreparedExecutionPlanV2:
    """Immutable compatibility-checked execution request preparation.

    This is intentionally a preparation contract, not another engine.  Current
    public endpoints may lower it through legacy adapters while later Rust
    phases can consume the same fingerprints without reconstructing Python
    state or inferring constraints independently.
    """

    market: PreparedMarketHandleV2
    instruments: InstrumentRegistryV2
    account_contract: str
    timing_contract: str
    execution_model: Mapping[str, object]
    metric_contract: str
    fingerprint: str

    def require_open(self) -> None:
        self.market.require_open()

    def metadata(self) -> dict[str, object]:
        self.require_open()
        return {
            "schema": PREPARED_EXECUTION_V2_SCHEMA,
            "fingerprint": self.fingerprint,
            "market_fingerprint": self.market.fingerprint,
            "instrument_fingerprint": self.instruments.fingerprint,
            "account_contract": self.account_contract,
            "timing_contract": self.timing_contract,
            "execution_model": dict(self.execution_model),
            "metric_contract": self.metric_contract,
        }


def prepare_execution_plan_v2(
    *,
    market: PreparedMarketHandleV2,
    instruments: InstrumentRegistryV2,
    account_contract: str = "linear_gross_cross_v1",
    timing_contract: str = "event_lifecycle_v3_next_open",
    execution_model: Optional[Mapping[str, object]] = None,
    metric_contract: str = "standard_daily_v2",
) -> PreparedExecutionPlanV2:
    """Bind V2 handles only when their canonical symbol layouts match exactly."""
    market.require_open()
    if market.symbols != instruments.symbols:
        raise ValueError(
            "prepared execution plan market/instrument symbols differ: "
            f"market={market.symbols} instruments={instruments.symbols}"
        )
    execution = dict(execution_model or {})
    payload = {
        "schema": PREPARED_EXECUTION_V2_SCHEMA,
        "market": market.fingerprint,
        "instruments": instruments.fingerprint,
        "account_contract": str(account_contract),
        "timing_contract": str(timing_contract),
        "execution_model": execution,
        "metric_contract": str(metric_contract),
    }
    fingerprint = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    return PreparedExecutionPlanV2(
        market=market,
        instruments=instruments,
        account_contract=str(account_contract),
        timing_contract=str(timing_contract),
        execution_model=execution,
        metric_contract=str(metric_contract),
        fingerprint=fingerprint,
    )


__all__ = [
    "PREPARED_EXECUTION_V2_SCHEMA",
    "PreparedExecutionPlanV2",
    "prepare_execution_plan_v2",
]
