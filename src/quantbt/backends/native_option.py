"""
Native option backend facade.

This backend wires the Phase 1-6 option components into the common QuantBT
result contract. It does not attempt to be a venue-exact options exchange; the
venue-specific gaps stay explicit in reports and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.results import OptionBacktestResult
from ..core.schema import AccountConfig, ExecutionConfig
from ..options.cache import OptionPreparedRunCache
from ..options.capabilities import (
    OptionCapabilityError,
    OptionSettlementPolicy,
    validate_option_capabilities,
)
from ..options.execution import OptionExecutionConfig, execute_option_package
from ..options.authority import (
    apply_legacy_last_tape_settlements as _apply_legacy_last_tape_settlements,
    maintenance_liquidation_if_needed as _maintenance_liquidation_if_needed,
    option_fee as _option_fee,
    require_expired_positions_settled as _require_expired_positions_settled,
    settlement_provenance_record as _settlement_provenance_record,
    snapshot_state as _snapshot_state,
)
from ..options.fees import OptionFeeSchedule
from ..options.hedging import OptionHedgeConfig
from ..options.ledger import OptionLedger
from ..options.lifecycle import OptionSettlementRepresentation, settle_option_expiry
from ..options.margin import (
    ExternalOptionMarginValidator,
    OptionLiquidationAudit,
    OptionMarginConfig,
    OptionMarginRequirement,
    calculate_option_margin,
)
from ..options.packages import OptionPackageIntent
from ..options.reporting import (
    attach_delta_hedge_contract as _attach_delta_hedge_contract,
    build_option_result as _build_result,
    concat_reports as _concat,
    snapshot_marks as _snapshot_marks,
    snapshot_underlyings as _snapshot_underlyings,
)
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
    # ``settle_expired`` remains a legacy alias.  The effective policy is
    # recorded in every result so a last-tape price can never masquerade as an
    # official settlement event.
    settle_expired: bool = False
    settlement_policy: Optional[OptionSettlementPolicy | str] = None
    allow_future_then_cash_research: bool = False
    require_venue_exact_margin: bool = False
    external_margin_validator: Optional[ExternalOptionMarginValidator] = None
    liquidate_on_maintenance_breach: bool = True
    max_spread_bps: Optional[float] = None
    max_source_latency_ns: Optional[int] = None
    random_seed: Optional[int] = 42
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reporting_currency", str(self.reporting_currency).upper())
        if self.account.initial_capital <= 0.0:
            raise ValueError("account.initial_capital must be > 0")
        policy = self.settlement_policy
        if policy is None:
            policy = (
                OptionSettlementPolicy.LEGACY_LAST_TAPE_MARK_RESEARCH
                if self.settle_expired
                else OptionSettlementPolicy.EXPLICIT_EVENTS_ONLY
            )
        else:
            try:
                policy = policy if isinstance(policy, OptionSettlementPolicy) else OptionSettlementPolicy(str(policy))
            except ValueError as exc:
                raise ValueError("invalid option settlement_policy") from exc
        if self.settle_expired and policy is not OptionSettlementPolicy.LEGACY_LAST_TAPE_MARK_RESEARCH:
            raise ValueError("settle_expired=True requires legacy_last_tape_mark_research settlement_policy")
        object.__setattr__(self, "settlement_policy", policy)
        object.__setattr__(
            self,
            "settle_expired",
            policy is OptionSettlementPolicy.LEGACY_LAST_TAPE_MARK_RESEARCH,
        )


@dataclass(frozen=True)
class OptionSettlementEvent:
    symbol: str
    timestamp_ns: int
    settlement_price: float
    representation: Optional[OptionSettlementRepresentation] = None
    source: str = ""
    source_timestamp_ns: Optional[int] = None
    last_trading_timestamp_ns: Optional[int] = None
    expiry_timestamp_ns: Optional[int] = None
    source_is_official: bool = False
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("settlement event symbol is required")
        if int(self.timestamp_ns) <= 0:
            raise ValueError("settlement event timestamp_ns must be > 0")
        if float(self.settlement_price) <= 0.0:
            raise ValueError("settlement event settlement_price must be > 0")
        object.__setattr__(self, "timestamp_ns", int(self.timestamp_ns))
        object.__setattr__(self, "settlement_price", float(self.settlement_price))
        object.__setattr__(self, "source", str(self.source).strip())
        for field_name in ("source_timestamp_ns", "last_trading_timestamp_ns", "expiry_timestamp_ns"):
            value = getattr(self, field_name)
            if value is not None and int(value) <= 0:
                raise ValueError(f"settlement event {field_name} must be > 0")
            if value is not None:
                object.__setattr__(self, field_name, int(value))

    @property
    def provenance_status(self) -> str:
        if self.source and self.source_timestamp_ns is not None and self.source_is_official:
            return "official_source"
        if self.source and self.source_timestamp_ns is not None:
            return "declared_source"
        return "legacy_unverified"

    @property
    def certified_provenance(self) -> bool:
        return self.provenance_status == "official_source"


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
        instrument_map = registry.by_symbol
        capability_assessments = validate_option_capabilities(
            registry.instruments,
            margin=self.config.margin,
            execution=self.config.option_execution,
            allow_future_then_cash_research=self.config.allow_future_then_cash_research,
            require_venue_exact_margin=self.config.require_venue_exact_margin,
            external_margin_validator=self.config.external_margin_validator,
        )
        packages_sorted = tuple(sorted(packages or (), key=lambda package: (int(package.timestamp_ns), package.package_id)))
        settlement_events_normalized = _normalize_settlement_events(settlement_events)
        _validate_option_requests(
            packages_sorted,
            settlement_events_normalized,
            instrument_map,
            settlement_policy=self.config.settlement_policy,
        )
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
        _validate_tape_coverage(packages_sorted, tape)
        rates = {**self.config.conversion_rates, **(conversion_rates or {})}
        report_ccy = str(reporting_currency or self.config.reporting_currency).upper()
        if report_ccy not in rates:
            rates[report_ccy] = 1.0

        ledger = OptionLedger.from_cash(self.config.initial_balances or {report_ccy: self.config.account.initial_capital})
        order_reports = []
        package_reports = []
        applied_fills = []
        snapshots = []
        settlements = []
        settlement_records = []
        margin_timeline = []
        liquidation_audits: list[OptionLiquidationAudit] = []
        liquidated = False
        account_closed = False
        last_margin: Optional[OptionMarginRequirement] = None

        packages_by_timestamp = _events_by_timestamp(packages_sorted)
        settlements_by_timestamp = _events_by_timestamp(settlement_events_normalized)
        timeline = sorted(
            {int(timestamp) for timestamp in tape.timestamp_ns}
            | set(packages_by_timestamp)
            | set(settlements_by_timestamp)
        )
        quote_config = replace(self.config.option_execution, enforce_package_cash_guard=False)
        snapshots.append(_snapshot_state(tape, 0, ledger, instrument_map, rates, report_ccy, "initial"))

        for timestamp_ns in timeline:
            snapshot_idx = _snapshot_index_at_or_before(tape, timestamp_ns)
            for package in packages_by_timestamp.get(timestamp_ns, ()):
                pkg_result = execute_option_package(
                    package,
                    tape,
                    config=quote_config,
                    positions={symbol: position.qty for symbol, position in ledger.positions.items()},
                    compiled_orders=prepared_cache.compile_package(package) if prepared_cache is not None else None,
                )
                if account_closed:
                    admitted = _reject_quoted_package(pkg_result, package, "LIQUIDATED_ACCOUNT", report_ccy)
                else:
                    admitted = _admit_option_package(
                        package=package,
                        quote_result=pkg_result,
                        ledger=ledger,
                        tape=tape,
                        snapshot_idx=snapshot_idx,
                        instruments=instrument_map,
                        account=self.config.account,
                        margin_config=self.config.margin,
                        fee_schedule=self.config.fee_schedule,
                        conversion_rates=rates,
                        reporting_currency=report_ccy,
                        external_margin_validator=self.config.external_margin_validator,
                        require_venue_exact_margin=self.config.require_venue_exact_margin,
                    )
                order_reports.append(admitted["order_report"])
                package_reports.append(admitted["package_report"])
                if admitted["accepted"]:
                    applied_fills.extend(admitted["fills_with_fees"])
                    last_margin = admitted["margin"]
                last_margin = _record_margin_state(
                    margin_timeline,
                    ledger=ledger,
                    tape=tape,
                    snapshot_idx=snapshot_idx,
                    instruments=instrument_map,
                    config=self.config,
                    conversion_rates=rates,
                    reporting_currency=report_ccy,
                    label=f"package:{package.package_id}",
                    timestamp_override_ns=int(package.timestamp_ns),
                )
                liquidation = _maintenance_liquidation_if_needed(
                    ledger=ledger,
                    margin=last_margin,
                    tape=tape,
                    snapshot_idx=snapshot_idx,
                    instruments=instrument_map,
                    config=self.config,
                    conversion_rates=rates,
                    reporting_currency=report_ccy,
                    event_timestamp_ns=int(package.timestamp_ns),
                )
                if liquidation is not None:
                    liquidation_audits.append(liquidation)
                    if liquidation.breached and self.config.liquidate_on_maintenance_breach:
                        applied_fills.extend(liquidation.fills_with_fees)
                        liquidated = True
                        account_closed = True
                        last_margin = _record_margin_state(
                            margin_timeline,
                            ledger=ledger,
                            tape=tape,
                            snapshot_idx=snapshot_idx,
                            instruments=instrument_map,
                            config=self.config,
                            conversion_rates=rates,
                            reporting_currency=report_ccy,
                            label=f"liquidation:{package.package_id}",
                            timestamp_override_ns=int(package.timestamp_ns),
                        )

            for event in settlements_by_timestamp.get(timestamp_ns, ()):
                instrument = instrument_map[event.symbol]
                settlement = settle_option_expiry(
                    ledger,
                    instrument,
                    timestamp_ns=int(event.timestamp_ns),
                    settlement_price=float(event.settlement_price),
                    representation=event.representation,
                )
                settlements.append(settlement)
                settlement_records.append(_settlement_provenance_record(event, instrument, fallback=False))
                last_margin = _record_margin_state(
                    margin_timeline,
                    ledger=ledger,
                    tape=tape,
                    snapshot_idx=snapshot_idx,
                    instruments=instrument_map,
                    config=self.config,
                    conversion_rates=rates,
                    reporting_currency=report_ccy,
                    label=f"settlement:{event.symbol}",
                    timestamp_override_ns=int(event.timestamp_ns),
                )
                liquidation = _maintenance_liquidation_if_needed(
                    ledger=ledger,
                    margin=last_margin,
                    tape=tape,
                    snapshot_idx=snapshot_idx,
                    instruments=instrument_map,
                    config=self.config,
                    conversion_rates=rates,
                    reporting_currency=report_ccy,
                    event_timestamp_ns=int(event.timestamp_ns),
                )
                if liquidation is not None:
                    liquidation_audits.append(liquidation)
                    if liquidation.breached and self.config.liquidate_on_maintenance_breach:
                        applied_fills.extend(liquidation.fills_with_fees)
                        liquidated = True
                        account_closed = True

            last_margin = _record_margin_state(
                margin_timeline,
                ledger=ledger,
                tape=tape,
                snapshot_idx=snapshot_idx,
                instruments=instrument_map,
                config=self.config,
                conversion_rates=rates,
                reporting_currency=report_ccy,
                label="mark_to_market",
                timestamp_override_ns=int(timestamp_ns),
            )
            liquidation = _maintenance_liquidation_if_needed(
                ledger=ledger,
                margin=last_margin,
                tape=tape,
                snapshot_idx=snapshot_idx,
                instruments=instrument_map,
                config=self.config,
                conversion_rates=rates,
                reporting_currency=report_ccy,
                event_timestamp_ns=int(timestamp_ns),
            )
            if liquidation is not None:
                liquidation_audits.append(liquidation)
                if liquidation.breached and self.config.liquidate_on_maintenance_breach:
                    applied_fills.extend(liquidation.fills_with_fees)
                    liquidated = True
                    account_closed = True
                    last_margin = _record_margin_state(
                        margin_timeline,
                        ledger=ledger,
                        tape=tape,
                        snapshot_idx=snapshot_idx,
                        instruments=instrument_map,
                        config=self.config,
                        conversion_rates=rates,
                        reporting_currency=report_ccy,
                        label="liquidation:mark_to_market",
                        timestamp_override_ns=int(timestamp_ns),
                    )
            snapshots.append(
                _snapshot_state(
                    tape,
                    snapshot_idx,
                    ledger,
                    instrument_map,
                    rates,
                    report_ccy,
                    "mark_to_market",
                    timestamp_override_ns=int(timestamp_ns),
                )
            )

        if self.config.settlement_policy is OptionSettlementPolicy.LEGACY_LAST_TAPE_MARK_RESEARCH:
            fallback_records, fallback_settlements = _apply_legacy_last_tape_settlements(
                ledger=ledger,
                tape=tape,
                instruments=instrument_map,
            )
            settlement_records.extend(fallback_records)
            settlements.extend(fallback_settlements)
            if fallback_settlements:
                last_margin = _record_margin_state(
                    margin_timeline,
                    ledger=ledger,
                    tape=tape,
                    snapshot_idx=tape.snapshot_count - 1,
                    instruments=instrument_map,
                    config=self.config,
                    conversion_rates=rates,
                    reporting_currency=report_ccy,
                    label="legacy_last_tape_settlement",
                    timestamp_override_ns=int(tape.timestamp_ns[-1]),
                )
                snapshots.append(
                    _snapshot_state(
                        tape,
                        tape.snapshot_count - 1,
                        ledger,
                        instrument_map,
                        rates,
                        report_ccy,
                        "legacy_last_tape_settlement",
                    )
                )
        else:
            _require_expired_positions_settled(ledger, instrument_map, int(tape.timestamp_ns[-1]))

        final_snapshot_idx = tape.snapshot_count - 1
        final_timestamp_ns = max(
            int(tape.timestamp_ns[-1]),
            max((int(event.timestamp_ns) for event in settlement_events_normalized), default=int(tape.timestamp_ns[-1])),
        )
        margin = _record_margin_state(
            margin_timeline,
            ledger=ledger,
            tape=tape,
            snapshot_idx=final_snapshot_idx,
            instruments=instrument_map,
            config=self.config,
            conversion_rates=rates,
            reporting_currency=report_ccy,
            label="final",
            timestamp_override_ns=final_timestamp_ns,
        )
        final_snapshot = _snapshot_state(
            tape,
            final_snapshot_idx,
            ledger,
            instrument_map,
            rates,
            report_ccy,
            "final",
            timestamp_override_ns=final_timestamp_ns,
        )
        if snapshots and int(snapshots[-1]["timestamp_ns"]) == final_timestamp_ns:
            snapshots[-1] = final_snapshot
        else:
            snapshots.append(final_snapshot)

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
            settlement_records=settlement_records,
            margin=margin,
            margin_timeline=margin_timeline,
            liquidation_audits=liquidation_audits,
            liquidated=liquidated,
            metadata={
                "backend": "native_option",
                "engine": "native_option",
                "phase": "phase70_options_p0_containment",
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
                "accounting_authority": "option_ledger_preview_commit_v1",
                "capability_assessments": [assessment.as_dict() for assessment in capability_assessments],
                "settlement_policy": self.config.settlement_policy.value,
                "settlement_certified": bool(
                    all(record["certified_provenance"] for record in settlement_records)
                    and not any(record["fallback"] for record in settlement_records)
                ),
                "settlement_fallback_used": bool(any(record["fallback"] for record in settlement_records)),
                "margin_validation_status": "venue_exact" if margin.venue_exact else "approximation",
                "maintenance_breach_count": int(sum(1 for audit in liquidation_audits if audit.breached)),
                "liquidation_count": int(sum(1 for audit in liquidation_audits if audit.fills_with_fees)),
                "liquidated_from_timeline": bool(liquidated),
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
                    source=str(event.get("source", "")),
                    source_timestamp_ns=event.get("source_timestamp_ns"),
                    last_trading_timestamp_ns=event.get("last_trading_timestamp_ns"),
                    expiry_timestamp_ns=event.get("expiry_timestamp_ns"),
                    source_is_official=bool(event.get("source_is_official", False)),
                    metadata=dict(event.get("metadata", {})),
                )
            )
    return tuple(sorted(out, key=lambda item: (int(item.timestamp_ns), item.symbol)))


def _events_by_timestamp(events: Sequence) -> Dict[int, tuple]:
    grouped: Dict[int, list] = {}
    for event in events:
        grouped.setdefault(int(event.timestamp_ns), []).append(event)
    return {timestamp: tuple(items) for timestamp, items in grouped.items()}


def _validate_option_requests(
    packages: Sequence[OptionPackageIntent],
    settlement_events: Sequence[OptionSettlementEvent],
    instruments: Mapping[str, OptionInstrumentSpec],
    *,
    settlement_policy: OptionSettlementPolicy,
) -> None:
    """Reject unsupported lifecycle shapes before preparing the chain tape."""

    seen_settlements = set()
    for event in settlement_events:
        instrument = instruments.get(event.symbol)
        if instrument is None:
            raise OptionCapabilityError(
                "OPTION_SETTLEMENT_UNKNOWN_INSTRUMENT",
                f"settlement event references unknown instrument {event.symbol!r}",
            )
        if event.symbol in seen_settlements:
            raise OptionCapabilityError(
                "OPTION_SETTLEMENT_DUPLICATE_EVENT",
                f"only one settlement event is allowed for {event.symbol!r}",
            )
        seen_settlements.add(event.symbol)
        if int(event.timestamp_ns) < int(instrument.expiry_ns):
            raise OptionCapabilityError(
                "OPTION_SETTLEMENT_BEFORE_EXPIRY",
                f"settlement for {event.symbol!r} precedes its expiry timestamp",
            )
        if event.expiry_timestamp_ns is not None and int(event.expiry_timestamp_ns) != int(instrument.expiry_ns):
            raise OptionCapabilityError(
                "OPTION_SETTLEMENT_EXPIRY_MISMATCH",
                f"settlement expiry provenance does not match instrument expiry for {event.symbol!r}",
            )
        if event.last_trading_timestamp_ns is not None and int(event.last_trading_timestamp_ns) > int(instrument.expiry_ns):
            raise OptionCapabilityError(
                "OPTION_SETTLEMENT_LAST_TRADING_AFTER_EXPIRY",
                f"last trading timestamp exceeds expiry for {event.symbol!r}",
            )
    for package in packages:
        for leg in package.legs:
            instrument = instruments.get(leg.instrument_id)
            if instrument is None:
                raise OptionCapabilityError(
                    "OPTION_PACKAGE_UNKNOWN_INSTRUMENT",
                    f"package {package.package_id!r} references unknown instrument {leg.instrument_id!r}",
                )
            if int(package.timestamp_ns) >= int(instrument.expiry_ns):
                raise OptionCapabilityError(
                    "OPTION_EXPIRED_INSTRUMENT_ORDER",
                    f"package {package.package_id!r} is at/after expiry for {instrument.symbol!r}",
                )
    if settlement_policy is OptionSettlementPolicy.EXPLICIT_EVENTS_ONLY:
        return
    if settlement_policy is not OptionSettlementPolicy.LEGACY_LAST_TAPE_MARK_RESEARCH:
        raise OptionCapabilityError("OPTION_SETTLEMENT_POLICY_UNSUPPORTED", "unsupported settlement policy")


def _validate_tape_coverage(packages: Sequence[OptionPackageIntent], tape: PreparedOptionTape) -> None:
    first_timestamp = int(tape.timestamp_ns[0])
    last_timestamp = int(tape.timestamp_ns[-1])
    for package in packages:
        if not first_timestamp <= int(package.timestamp_ns) <= last_timestamp:
            raise OptionCapabilityError(
                "OPTION_PACKAGE_TIMESTAMP_OUTSIDE_TAPE",
                f"package {package.package_id!r} timestamp is outside the prepared market tape",
            )


def _snapshot_index_at_or_before(tape: PreparedOptionTape, timestamp_ns: int) -> int:
    return min(
        tape.snapshot_count - 1,
        max(0, int(np.searchsorted(tape.timestamp_ns, int(timestamp_ns), side="right") - 1)),
    )


def _resolve_authoritative_fills(
    fills: Sequence,
    *,
    tape: PreparedOptionTape,
    instruments: Mapping[str, OptionInstrumentSpec],
    fee_schedule: Optional[OptionFeeSchedule],
) -> tuple[tuple, ...]:
    out = []
    for quoted_fill in fills:
        instrument = instruments[quoted_fill.symbol]
        fee = _option_fee(quoted_fill, instrument, tape, fee_schedule)
        applied_fee = float(fee.fee if fee is not None else quoted_fill.fee)
        applied_fill = replace(
            quoted_fill,
            fee=applied_fee,
            metadata={
                **quoted_fill.metadata,
                "quoted_execution_fee": float(quoted_fill.fee),
                "applied_fee": applied_fee,
                "fee_currency": fee.currency if fee is not None else instrument.premium_currency,
                "fee_authority": "option_ledger",
                "contract_multiplier": float(instrument.multiplier),
            },
        )
        out.append((applied_fill, fee))
    return tuple(out)


def _apply_fills_to_ledger(
    ledger: OptionLedger,
    fills_with_fees: Sequence[tuple],
    instruments: Mapping[str, OptionInstrumentSpec],
) -> None:
    for fill, fee in fills_with_fees:
        ledger.apply_fill(fill, instruments[fill.symbol], fee=fee, timestamp_ns=int(fill.timestamp))


def _cash_delta_in_reporting(
    before: Mapping[str, float],
    after: Mapping[str, float],
    conversion_rates: Mapping[str, float],
    reporting_currency: str,
) -> float:
    currencies = set(before).union(after)
    delta = 0.0
    for currency in currencies:
        amount = float(after.get(currency, 0.0)) - float(before.get(currency, 0.0))
        delta += amount * _conversion_rate_to_reporting(currency, conversion_rates, reporting_currency)
    return float(delta)


def _conversion_rate_to_reporting(currency: str, conversion_rates: Mapping[str, float], reporting_currency: str) -> float:
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


def _margin_at_snapshot(
    ledger: OptionLedger,
    tape: PreparedOptionTape,
    snapshot_idx: int,
    instruments: Mapping[str, OptionInstrumentSpec],
    *,
    config: NativeOptionConfig,
    conversion_rates: Mapping[str, float],
    reporting_currency: str,
) -> tuple[OptionMarginRequirement, float]:
    marks = _snapshot_marks(tape, snapshot_idx)
    underlyings = _snapshot_underlyings(tape, snapshot_idx)
    margin = calculate_option_margin(
        ledger,
        dict(instruments),
        marks,
        underlyings,
        config=config.margin,
        reporting_currency=reporting_currency,
        conversion_rates=dict(conversion_rates),
        external_validator=config.external_margin_validator,
    )
    if config.require_venue_exact_margin and not margin.venue_exact:
        raise OptionCapabilityError(
            "OPTION_VENUE_EXACT_MARGIN_VALIDATION_FAILED",
            "external margin validator did not return venue_exact=True",
        )
    equity = ledger.equity(
        conversion_rates=dict(conversion_rates),
        marks=marks,
        instruments=dict(instruments),
        reporting_currency=reporting_currency,
    )
    return margin, float(equity)


def _record_margin_state(
    timeline: list[Dict],
    *,
    ledger: OptionLedger,
    tape: PreparedOptionTape,
    snapshot_idx: int,
    instruments: Mapping[str, OptionInstrumentSpec],
    config: NativeOptionConfig,
    conversion_rates: Mapping[str, float],
    reporting_currency: str,
    label: str,
    timestamp_override_ns: Optional[int] = None,
) -> OptionMarginRequirement:
    margin, equity = _margin_at_snapshot(
        ledger,
        tape,
        snapshot_idx,
        instruments,
        config=config,
        conversion_rates=conversion_rates,
        reporting_currency=reporting_currency,
    )
    required = float(margin.initial_margin) + float(config.account.margin_buffer)
    timeline.append(
        {
            "timestamp_ns": int(
                tape.timestamp_ns[snapshot_idx] if timestamp_override_ns is None else timestamp_override_ns
            ),
            "label": label,
            "equity": float(equity),
            "initial_margin": float(margin.initial_margin),
            "maintenance_margin": float(margin.maintenance_margin),
            "available_collateral": float(equity - required),
            "margin_model": margin.model.value,
            "venue_exact": bool(margin.venue_exact),
            "maintenance_breached": bool(equity < margin.maintenance_margin),
        }
    )
    return margin


def _admit_option_package(
    *,
    package: OptionPackageIntent,
    quote_result,
    ledger: OptionLedger,
    tape: PreparedOptionTape,
    snapshot_idx: int,
    instruments: Mapping[str, OptionInstrumentSpec],
    account: AccountConfig,
    margin_config: OptionMarginConfig,
    fee_schedule: Optional[OptionFeeSchedule],
    conversion_rates: Mapping[str, float],
    reporting_currency: str,
    external_margin_validator: Optional[ExternalOptionMarginValidator],
    require_venue_exact_margin: bool,
) -> Dict:
    """Preview fees/cash/positions/margin, then commit the exact same fills once."""

    if quote_result.package_report.empty:
        return _reject_quoted_package(quote_result, package, "PACKAGE_QUOTE_REPORT_MISSING", reporting_currency)
    quoted_status = str(quote_result.package_report.iloc[0].get("status", "rejected"))
    if not quote_result.fills:
        return _annotate_option_package_result(
            quote_result,
            package,
            accepted=False,
            reason=str(quote_result.package_report.iloc[0].get("reject_reason", "NO_EXECUTABLE_FILL")) or "NO_EXECUTABLE_FILL",
            reporting_currency=reporting_currency,
            financial_admission="not_applicable",
        )
    guard_currency = str(package.metadata.get("guard_currency", reporting_currency)).upper()
    if guard_currency != str(reporting_currency).upper():
        return _reject_quoted_package(quote_result, package, "OPTION_GUARD_CURRENCY_UNSUPPORTED", reporting_currency)

    fills_with_fees = _resolve_authoritative_fills(
        quote_result.fills,
        tape=tape,
        instruments=instruments,
        fee_schedule=fee_schedule,
    )
    preview = ledger.clone()
    _apply_fills_to_ledger(preview, fills_with_fees, instruments)
    preview_config = NativeOptionConfig(
        account=account,
        margin=margin_config,
        fee_schedule=fee_schedule,
        reporting_currency=reporting_currency,
        conversion_rates=dict(conversion_rates),
        external_margin_validator=external_margin_validator,
        require_venue_exact_margin=require_venue_exact_margin,
    )
    margin, equity_after = _margin_at_snapshot(
        preview,
        tape,
        snapshot_idx,
        instruments,
        config=preview_config,
        conversion_rates=conversion_rates,
        reporting_currency=reporting_currency,
    )
    net_cash_delta = _cash_delta_in_reporting(ledger.cash, preview.cash, conversion_rates, reporting_currency)
    debit = max(-net_cash_delta, 0.0)
    credit = max(net_cash_delta, 0.0)
    required = float(margin.initial_margin) + float(account.margin_buffer)
    available = float(equity_after - required)
    rejection = ""
    if package.max_debit is not None and debit > float(package.max_debit) + 1e-12:
        rejection = "MAX_DEBIT_EXCEEDED"
    elif package.min_credit is not None and credit + 1e-12 < float(package.min_credit):
        rejection = "MIN_CREDIT_NOT_MET"
    elif available < -1e-12:
        rejection = "POST_COST_MARGIN"
    if rejection:
        return _reject_quoted_package(
            quote_result,
            package,
            rejection,
            reporting_currency,
            preflight={
                "net_cash_delta": net_cash_delta,
                "debit": debit,
                "credit": credit,
                "equity": equity_after,
                "initial_margin": float(margin.initial_margin),
                "maintenance_margin": float(margin.maintenance_margin),
                "available_collateral": available,
                "guard_currency": reporting_currency,
            },
        )
    _apply_fills_to_ledger(ledger, fills_with_fees, instruments)
    return _annotate_option_package_result(
        quote_result,
        package,
        accepted=True,
        reason="",
        reporting_currency=reporting_currency,
        fills_with_fees=fills_with_fees,
        instruments=instruments,
        financial_admission="accepted",
        preflight={
            "net_cash_delta": net_cash_delta,
            "debit": debit,
            "credit": credit,
            "equity": equity_after,
            "initial_margin": float(margin.initial_margin),
            "maintenance_margin": float(margin.maintenance_margin),
            "available_collateral": available,
            "guard_currency": reporting_currency,
            "quoted_status": quoted_status,
        },
        margin=margin,
    )


def _reject_quoted_package(quote_result, package: OptionPackageIntent, reason: str, reporting_currency: str, *, preflight: Optional[Dict] = None) -> Dict:
    order_report = quote_result.order_report.copy()
    if not order_report.empty:
        order_report["status"] = "rejected"
        order_report["reject_reason"] = reason
        order_report["filled_qty"] = 0.0
        order_report["residual_qty"] = order_report["requested_qty"]
        order_report["fee"] = 0.0
        order_report["cash_delta"] = 0.0
    return _annotate_option_package_result(
        quote_result,
        package,
        accepted=False,
        reason=reason,
        reporting_currency=reporting_currency,
        order_report=order_report,
        financial_admission="rejected",
        preflight=preflight,
    )


def _annotate_option_package_result(
    quote_result,
    package: OptionPackageIntent,
    *,
    accepted: bool,
    reason: str,
    reporting_currency: str,
    order_report: Optional[pd.DataFrame] = None,
    fills_with_fees: Sequence[tuple] = (),
    instruments: Optional[Mapping[str, OptionInstrumentSpec]] = None,
    financial_admission: str,
    preflight: Optional[Dict] = None,
    margin: Optional[OptionMarginRequirement] = None,
) -> Dict:
    order_report = quote_result.order_report.copy() if order_report is None else order_report
    unmatched_fills = list(fills_with_fees)
    if not order_report.empty:
        order_report["applied_fee"] = 0.0
        order_report["fee_currency"] = ""
        order_report["financial_authority"] = "option_ledger_preview_commit_v1"
        for row_index, row in order_report.iterrows():
            item_index = next(
                (
                    index
                    for index, (fill, _) in enumerate(unmatched_fills)
                    if fill.symbol == str(row.get("symbol"))
                    and fill.side.value == str(row.get("side"))
                    and (
                        fill.order_id == row.get("order_id")
                        or fill.order_id is None
                        or pd.isna(row.get("order_id"))
                    )
                ),
                None,
            )
            item = None if item_index is None else unmatched_fills.pop(item_index)
            if item is None:
                continue
            fill, fee = item
            instrument_multiplier = float(instruments[fill.symbol].multiplier) if instruments is not None else 1.0
            order_report.at[row_index, "fee"] = float(fill.fee)
            order_report.at[row_index, "applied_fee"] = float(fill.fee)
            order_report.at[row_index, "fee_currency"] = fee.currency if fee is not None else ""
            premium = float(fill.qty) * float(fill.price) * instrument_multiplier
            order_report.at[row_index, "cash_delta"] = premium - float(fill.fee) if fill.side.value == "sell" else -(premium + float(fill.fee))
    package_report = quote_result.package_report.copy()
    if package_report.empty:
        package_report = pd.DataFrame([{"package_id": package.package_id}])
    package_report["status"] = "filled" if accepted and str(package_report.iloc[0].get("status", "")) == "filled" else (
        "partial" if accepted else "rejected"
    )
    package_report["reject_reason"] = reason
    package_report["financial_admission"] = financial_admission
    package_report["financial_authority"] = "option_ledger_preview_commit_v1"
    package_report["guard_currency"] = str(reporting_currency).upper()
    for key, value in (preflight or {}).items():
        package_report[f"preflight_{key}"] = value
    if preflight is not None:
        for key in ("net_cash_delta", "debit", "credit"):
            if key in preflight:
                package_report[key] = preflight[key]
    if margin is not None:
        package_report["preflight_margin_model"] = margin.model.value
        package_report["preflight_venue_exact"] = bool(margin.venue_exact)
    return {
        "accepted": bool(accepted),
        "fills_with_fees": tuple(fills_with_fees),
        "order_report": order_report,
        "package_report": package_report,
        "margin": margin,
    }
