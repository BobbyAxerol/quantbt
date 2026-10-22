"""Cold configuration and request validation for the native option facade."""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Mapping, Sequence

from ..core.schema import AccountConfig, ExecutionConfig
from ..options.capabilities import OptionCapabilityError, OptionSettlementPolicy
from ..options.packages import OptionPackageIntent
from ..options.schema import OptionInstrumentRegistry, OptionInstrumentSpec
from ..options.tape import PreparedOptionTape

if TYPE_CHECKING:
    from .native_option import OptionSettlementEvent


def _validate_generic_option_configuration(account: AccountConfig, execution: ExecutionConfig) -> None:
    account_defaults = AccountConfig(initial_capital=account.initial_capital)
    for name in ("base_currency", "leverage", "maintenance_ratio", "margin_mode", "oms_mode"):
        if getattr(account, name) != getattr(account_defaults, name):
            raise OptionCapabilityError(
                "OPTION_GENERIC_ACCOUNT_CONFIG_UNSUPPORTED",
                f"account.{name} is inactive for options; only its compatibility default is supported",
            )
    execution_defaults = ExecutionConfig()
    for item in fields(ExecutionConfig):
        if item.name != "metadata" and getattr(execution, item.name) != getattr(execution_defaults, item.name):
            raise OptionCapabilityError(
                "OPTION_GENERIC_EXECUTION_CONFIG_UNSUPPORTED",
                f"execution.{item.name} is inactive for options; configure option_execution instead",
            )


def _normalize_registry(
    instruments: OptionInstrumentRegistry | Sequence[OptionInstrumentSpec] | Mapping[str, OptionInstrumentSpec],
) -> OptionInstrumentRegistry:
    if isinstance(instruments, OptionInstrumentRegistry):
        return instruments
    if isinstance(instruments, Mapping):
        return OptionInstrumentRegistry.from_iterable(instruments.values())
    return OptionInstrumentRegistry.from_iterable(tuple(instruments))


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
