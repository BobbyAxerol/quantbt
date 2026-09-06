"""Authoritative option maintenance, settlement, fee, and snapshot helpers.

The public backend owns timeline orchestration.  This module owns the financial
state transitions which must not be duplicated by result/report construction.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd

from .capabilities import OptionCapabilityError
from .fees import OptionFeeResult, OptionFeeSchedule, calculate_option_fee
from .ledger import OptionLedger
from .lifecycle import settle_option_expiry
from .margin import OptionLiquidationAudit, OptionMarginRequirement, liquidate_option_positions
from .reporting import snapshot_marks, snapshot_underlyings
from .schema import OptionInstrumentSpec
from .tape import PreparedOptionTape


def maintenance_liquidation_if_needed(
    *,
    ledger: OptionLedger,
    margin: OptionMarginRequirement,
    tape: PreparedOptionTape,
    snapshot_idx: int,
    instruments: Mapping[str, OptionInstrumentSpec],
    config,
    conversion_rates: Mapping[str, float],
    reporting_currency: str,
    event_timestamp_ns: Optional[int] = None,
) -> Optional[OptionLiquidationAudit]:
    """Apply maintenance liquidation from observable BBO when required."""

    if not any(not position.is_flat for position in ledger.positions.values()):
        return None
    marks = snapshot_marks(tape, snapshot_idx)
    equity = ledger.equity(
        conversion_rates=dict(conversion_rates),
        marks=marks,
        instruments=dict(instruments),
        reporting_currency=reporting_currency,
    )
    if equity >= float(margin.maintenance_margin):
        return None
    if not config.liquidate_on_maintenance_breach:
        return OptionLiquidationAudit(
            breached=True,
            breach_reason="maintenance_margin_breach_unliquidated_by_config",
            equity_before=float(equity),
            maintenance_margin=float(margin.maintenance_margin),
            equity_after=float(equity),
            final_cash=dict(ledger.cash),
            final_positions={
                symbol: position.qty
                for symbol, position in ledger.positions.items()
                if not position.is_flat
            },
            liquidation_orders=pd.DataFrame(),
            metadata={"liquidation_enabled": False, "venue_exact": margin.venue_exact},
        )
    underlyings = snapshot_underlyings(tape, snapshot_idx)
    reference_prices = {
        symbol: underlyings.get(instrument.underlying_id, marks.get(symbol, 0.0))
        for symbol, instrument in instruments.items()
    }

    def fee_resolver(fill, instrument):
        return option_fee(
            fill,
            instrument,
            tape,
            config.fee_schedule,
            reference_price=reference_prices.get(instrument.symbol),
        )

    return liquidate_option_positions(
        ledger,
        dict(instruments),
        bid_prices=snapshot_bids(tape, snapshot_idx),
        ask_prices=snapshot_asks(tape, snapshot_idx),
        margin_requirement=margin,
        conversion_rates=dict(conversion_rates),
        reporting_currency=reporting_currency,
        timestamp_ns=int(
            tape.timestamp_ns[snapshot_idx]
            if event_timestamp_ns is None
            else event_timestamp_ns
        ),
        fee_rate=float(config.margin.liquidation_fee_rate),
        fee_resolver=fee_resolver,
    )


def snapshot_bids(tape: PreparedOptionTape, snapshot_idx: int) -> Dict[str, float]:
    rows = tape.snapshot_slice(snapshot_idx)
    return {
        tape.instrument_id[idx]: float(tape.bid_price[idx])
        for idx in range(rows.start, rows.stop)
    }


def snapshot_asks(tape: PreparedOptionTape, snapshot_idx: int) -> Dict[str, float]:
    rows = tape.snapshot_slice(snapshot_idx)
    return {
        tape.instrument_id[idx]: float(tape.ask_price[idx])
        for idx in range(rows.start, rows.stop)
    }


def settlement_provenance_record(
    event,
    instrument: OptionInstrumentSpec,
    *,
    fallback: bool,
) -> Dict:
    return {
        "symbol": instrument.symbol,
        "settlement_timestamp_ns": int(event.timestamp_ns),
        "expiry_timestamp_ns": int(instrument.expiry_ns),
        "last_trading_timestamp_ns": event.last_trading_timestamp_ns,
        "source": event.source or "legacy_caller_unverified",
        "source_timestamp_ns": event.source_timestamp_ns,
        "source_is_official": bool(event.source_is_official),
        "provenance_status": event.provenance_status,
        "certified_provenance": bool(event.certified_provenance and not fallback),
        "fallback": bool(fallback),
    }


def apply_legacy_last_tape_settlements(
    *,
    ledger: OptionLedger,
    tape: PreparedOptionTape,
    instruments: Mapping[str, OptionInstrumentSpec],
) -> tuple[list[Dict], list]:
    last_timestamp = int(tape.timestamp_ns[-1])
    marks = snapshot_marks(tape, tape.snapshot_count - 1)
    underlyings = snapshot_underlyings(tape, tape.snapshot_count - 1)
    records = []
    settlements = []
    for symbol, position in list(ledger.positions.items()):
        instrument = instruments[symbol]
        if (
            position.is_flat
            or int(instrument.expiry_ns) > last_timestamp
            or symbol in ledger.settled_symbols
        ):
            continue
        settlement_price = float(
            underlyings.get(instrument.underlying_id, marks.get(symbol, 0.0))
        )
        if settlement_price <= 0.0:
            raise OptionCapabilityError(
                "OPTION_LEGACY_SETTLEMENT_PRICE_MISSING",
                f"last tape snapshot has no valid settlement fallback price for {symbol!r}",
            )
        settlement = settle_option_expiry(
            ledger,
            instrument,
            timestamp_ns=last_timestamp,
            settlement_price=settlement_price,
        )
        settlements.append(settlement)
        records.append(
            {
                "symbol": symbol,
                "settlement_timestamp_ns": last_timestamp,
                "expiry_timestamp_ns": int(instrument.expiry_ns),
                "last_trading_timestamp_ns": last_timestamp,
                "source": "last_tape_mark_research_fallback",
                "source_timestamp_ns": last_timestamp,
                "source_is_official": False,
                "provenance_status": "legacy_last_tape_mark_research",
                "certified_provenance": False,
                "fallback": True,
            }
        )
    return records, settlements


def require_expired_positions_settled(
    ledger: OptionLedger,
    instruments: Mapping[str, OptionInstrumentSpec],
    last_tape_timestamp_ns: int,
) -> None:
    missing = [
        symbol
        for symbol, position in ledger.positions.items()
        if not position.is_flat
        and int(instruments[symbol].expiry_ns) <= int(last_tape_timestamp_ns)
        and symbol not in ledger.settled_symbols
    ]
    if missing:
        raise OptionCapabilityError(
            "OPTION_SETTLEMENT_EVENT_REQUIRED",
            "expired option positions require explicit settlement events under explicit_events_only policy",
            metadata={
                "symbols": sorted(missing),
                "last_tape_timestamp_ns": int(last_tape_timestamp_ns),
            },
        )


def option_fee(
    fill,
    instrument: OptionInstrumentSpec,
    tape: PreparedOptionTape,
    schedule: Optional[OptionFeeSchedule],
    *,
    reference_price: Optional[float] = None,
) -> Optional[OptionFeeResult]:
    schedule = schedule or fill.metadata.get("option_fee_schedule")
    if schedule is None or not isinstance(schedule, OptionFeeSchedule):
        return None
    row_index = int(fill.metadata.get("option_row_index", -1))
    if reference_price is None and row_index < 0:
        return None
    reference = (
        float(reference_price)
        if reference_price is not None
        else float(
            tape.index_price[row_index]
            if np.isfinite(tape.index_price[row_index])
            else tape.forward_price[row_index]
        )
    )
    return calculate_option_fee(fill, instrument, schedule, reference_price=reference)


def snapshot_state(
    tape: PreparedOptionTape,
    snapshot_idx: int,
    ledger: OptionLedger,
    instruments: Dict[str, OptionInstrumentSpec],
    conversion_rates: Dict[str, float],
    report_ccy: str,
    label: str,
    timestamp_override_ns: Optional[int] = None,
) -> Dict:
    marks = snapshot_marks(tape, snapshot_idx)
    equity = ledger.equity(
        conversion_rates=conversion_rates,
        marks=marks,
        instruments=instruments,
        reporting_currency=report_ccy,
    )
    return {
        "timestamp_ns": int(
            tape.timestamp_ns[snapshot_idx]
            if timestamp_override_ns is None
            else timestamp_override_ns
        ),
        "label": label,
        "equity": float(equity),
        "cash": dict(ledger.cash),
        "positions": {
            symbol: position.qty for symbol, position in ledger.positions.items()
        },
        "marks": marks,
    }


__all__ = [
    "apply_legacy_last_tape_settlements",
    "maintenance_liquidation_if_needed",
    "option_fee",
    "require_expired_positions_settled",
    "settlement_provenance_record",
    "snapshot_state",
]
