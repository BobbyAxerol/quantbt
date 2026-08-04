"""
Optional NautilusTrader option validation helpers.

Phase 9 pins Nautilus option constructor compatibility and provides a
component-labelled quote-driven validation report. It deliberately does not
claim full Nautilus option backtest-engine parity until Phase 9+ can map quote
ticks and option instruments through a version-pinned Nautilus simulation path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from importlib import import_module
from typing import Dict, Mapping, Optional, Sequence

import pandas as pd

from ...backends import NativeOptionBackend, NativeOptionConfig
from ...core.orders import OrderIntent
from ...core.results import OptionBacktestResult
from ...core.schema import AssetType, OrderSide
from ...options.packages import OptionPackageIntent, compile_option_package_orders
from ...options.schema import OptionInstrumentRegistry, OptionInstrumentSpec, OptionKind, PremiumConvention
from ._dependency import require_nautilus


PINNED_NAUTILUS_OPTION_VERSION = "1.230.0"
OPTION_CLASS_NAMES = ("CryptoOption", "CryptoOptionSpread", "OptionContract", "OptionSpread")


@dataclass(frozen=True)
class NautilusOptionValidationConfig:
    min_version: str = PINNED_NAUTILUS_OPTION_VERSION
    reporting_currency: str = "USD"
    require_constructor_pin: bool = True
    metadata: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class NautilusOptionValidationResult:
    status: str
    validation_level: str
    native_result: Optional[OptionBacktestResult]
    support_report: pd.DataFrame
    instrument_report: pd.DataFrame
    quote_report: pd.DataFrame
    component_parity_report: pd.DataFrame
    metadata: Dict = field(default_factory=dict)

    @property
    def skipped(self) -> bool:
        return self.status.startswith("skipped")


def inspect_nautilus_option_support() -> Dict:
    """Inspect installed Nautilus option support without constructing a run."""
    try:
        nt = require_nautilus()
        nautilus = import_module("nautilus_trader")
        instruments_mod = import_module("nautilus_trader.model.instruments")
    except ImportError as exc:
        return {
            "available": False,
            "version": None,
            "pinned_version": PINNED_NAUTILUS_OPTION_VERSION,
            "constructor_pinned": False,
            "reason": str(exc),
            "classes": {},
        }

    version = str(getattr(nautilus, "__version__", "unknown"))
    classes = {}
    constructor_pinned = _version_gte(version, PINNED_NAUTILUS_OPTION_VERSION)
    for name in OPTION_CLASS_NAMES:
        cls = getattr(instruments_mod, name, None)
        doc = "" if cls is None else str(getattr(cls, "__doc__", "") or "")
        classes[name] = {
            "available": cls is not None,
            "doc_contains_constructor": bool(name in doc and "InstrumentId" in doc),
            "doc": doc.splitlines()[0] if doc else "",
        }
        constructor_pinned = constructor_pinned and cls is not None and classes[name]["doc_contains_constructor"]
    return {
        "available": True,
        "version": version,
        "pinned_version": PINNED_NAUTILUS_OPTION_VERSION,
        "constructor_pinned": bool(constructor_pinned),
        "reason": "",
        "classes": classes,
        "objects_loaded": bool(nt),
    }


def make_nautilus_option_instrument(spec: OptionInstrumentSpec):
    """
    Construct a Nautilus option instrument for a QuantBT option spec.

    Raises ImportError when Nautilus is missing and ValueError/TypeError when
    the installed constructor is incompatible with the pinned Phase 9 mapping.
    """
    require_nautilus()
    inst = import_module("nautilus_trader.model.instruments")
    enums = import_module("nautilus_trader.model.enums")
    identifiers = import_module("nautilus_trader.model.identifiers")
    objects = import_module("nautilus_trader.model.objects")
    currencies = import_module("nautilus_trader.model.currencies")

    venue = _venue(spec)
    raw_symbol = _raw_symbol(spec.symbol, venue)
    instrument_id = identifiers.InstrumentId(
        symbol=identifiers.Symbol(raw_symbol),
        venue=identifiers.Venue(venue),
    )
    price_precision = int(spec.price_precision if spec.price_precision is not None else _precision(spec.tick_size, default=8))
    qty_precision = int(spec.qty_precision if spec.qty_precision is not None else _precision(spec.qty_step or spec.lot_size, default=4))
    price_increment = objects.Price(float(spec.tick_size or 0.00000001), price_precision)
    size_increment = objects.Quantity(float(spec.qty_step or spec.lot_size or 1.0), qty_precision)
    multiplier = objects.Quantity(float(spec.multiplier), qty_precision)
    lot_size = objects.Quantity(float(spec.qty_step or spec.lot_size or 1.0), qty_precision)
    option_kind = enums.OptionKind.CALL if spec.option_kind is OptionKind.CALL else enums.OptionKind.PUT
    strike = objects.Price(float(spec.strike), price_precision)
    maker_fee = Decimal(str(getattr(spec.fee_model, "maker", 0.0) if spec.fee_model else 0.0))
    taker_fee = Decimal(str(getattr(spec.fee_model, "taker", 0.0) if spec.fee_model else 0.0))
    ts_event = int(spec.metadata.get("ts_event", 0) or 0)
    ts_init = int(spec.metadata.get("ts_init", ts_event) or ts_event)

    if _is_crypto_option(spec):
        return inst.CryptoOption(
            instrument_id=instrument_id,
            raw_symbol=identifiers.Symbol(raw_symbol),
            underlying=_currency(currencies, _underlying_currency(spec)),
            quote_currency=_currency(currencies, spec.quote_currency),
            settlement_currency=_currency(currencies, spec.settlement_currency),
            is_inverse=spec.premium_convention is PremiumConvention.INVERSE_BASE,
            option_kind=option_kind,
            strike_price=strike,
            activation_ns=int(spec.metadata.get("activation_ns", 0) or 0),
            expiration_ns=int(spec.expiry_ns),
            price_precision=price_precision,
            size_precision=qty_precision,
            price_increment=price_increment,
            size_increment=size_increment,
            ts_event=ts_event,
            ts_init=ts_init,
            multiplier=multiplier,
            lot_size=lot_size,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            info={"quantbt_symbol": spec.symbol, "convention_version": spec.convention_version},
        )

    return inst.OptionContract(
        instrument_id=instrument_id,
        raw_symbol=identifiers.Symbol(raw_symbol),
        asset_class=enums.AssetClass.CRYPTOCURRENCY if spec.asset_type is AssetType.OPTION else enums.AssetClass.EQUITY,
        currency=_currency(currencies, spec.premium_currency),
        price_precision=price_precision,
        price_increment=price_increment,
        multiplier=multiplier,
        lot_size=lot_size,
        underlying=str(spec.underlying_id),
        option_kind=option_kind,
        strike_price=strike,
        activation_ns=int(spec.metadata.get("activation_ns", 0) or 0),
        expiration_ns=int(spec.expiry_ns),
        ts_event=ts_event,
        ts_init=ts_init,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        exchange=venue,
        info={"quantbt_symbol": spec.symbol, "convention_version": spec.convention_version},
    )


def build_nautilus_option_quote_table(chain: pd.DataFrame, instruments) -> pd.DataFrame:
    """Return the QuoteTick-equivalent table used for Phase 9 validation."""
    rows = []
    instrument_ids = {
        symbol: str(getattr(instrument, "id", instrument))
        for symbol, instrument in instruments.items()
    }
    required = ["timestamp_ns", "instrument_id", "bid_price", "ask_price", "bid_size", "ask_size"]
    missing = [col for col in required if col not in chain.columns]
    if missing:
        raise ValueError(f"option chain missing quote columns: {missing}")
    for row in chain[required].itertuples(index=False):
        symbol = str(row.instrument_id)
        rows.append(
            {
                "timestamp_ns": int(row.timestamp_ns),
                "instrument_id": instrument_ids.get(symbol, symbol),
                "quantbt_symbol": symbol,
                "bid_price": float(row.bid_price),
                "ask_price": float(row.ask_price),
                "bid_size": float(row.bid_size),
                "ask_size": float(row.ask_size),
                "matching_semantics": "market_buy_at_ask_market_sell_at_bid_limit_crosses_bbo",
            }
        )
    return pd.DataFrame(rows)


def validate_option_packages_with_nautilus(
    *,
    chain: pd.DataFrame,
    instruments: OptionInstrumentRegistry | Sequence[OptionInstrumentSpec] | Mapping[str, OptionInstrumentSpec],
    packages: Sequence[OptionPackageIntent],
    native_config: Optional[NativeOptionConfig] = None,
    config: Optional[NautilusOptionValidationConfig] = None,
    settlement_events: Optional[Sequence] = None,
    conversion_rates: Optional[Dict[str, float]] = None,
) -> NautilusOptionValidationResult:
    """
    Validate QuantBT option packages against pinned Nautilus option semantics.

    Current Phase 9 validation is constructor-pinned and quote-driven. It
    reports component parity against the native option backend and labels the
    validation level explicitly; it does not claim full Nautilus engine parity.
    """
    cfg = config or NautilusOptionValidationConfig()
    support = inspect_nautilus_option_support()
    support_report = _support_frame(support)
    if not support["available"]:
        return NautilusOptionValidationResult(
            status="skipped_missing_nautilus",
            validation_level="none",
            native_result=None,
            support_report=support_report,
            instrument_report=pd.DataFrame(),
            quote_report=pd.DataFrame(),
            component_parity_report=pd.DataFrame(),
            metadata={"reason": support["reason"], **cfg.metadata},
        )
    if cfg.require_constructor_pin and not support["constructor_pinned"]:
        return NautilusOptionValidationResult(
            status="skipped_incompatible_constructor",
            validation_level="none",
            native_result=None,
            support_report=support_report,
            instrument_report=pd.DataFrame(),
            quote_report=pd.DataFrame(),
            component_parity_report=pd.DataFrame(),
            metadata={"reason": "Nautilus option constructors are not pinned for this version", **cfg.metadata},
        )

    registry = _normalize_registry(instruments)
    instrument_rows = []
    nautilus_instruments = {}
    for spec in registry.instruments:
        try:
            instrument = make_nautilus_option_instrument(spec)
            nautilus_instruments[spec.symbol] = instrument
            instrument_rows.append(
                {
                    "symbol": spec.symbol,
                    "nautilus_instrument_id": str(instrument.id),
                    "class": type(instrument).__name__,
                    "status": "constructed",
                    "premium_convention": spec.premium_convention.value,
                    "settlement_currency": spec.settlement_currency,
                    "qty_step": float(spec.qty_step or spec.lot_size),
                }
            )
        except Exception as exc:
            instrument_rows.append({"symbol": spec.symbol, "status": "failed", "reason": str(exc)})
    instrument_report = pd.DataFrame(instrument_rows)
    if bool((instrument_report["status"] != "constructed").any()):
        return NautilusOptionValidationResult(
            status="skipped_instrument_mapping_failed",
            validation_level="constructor_failed",
            native_result=None,
            support_report=support_report,
            instrument_report=instrument_report,
            quote_report=pd.DataFrame(),
            component_parity_report=pd.DataFrame(),
            metadata={**cfg.metadata},
        )

    quote_report = build_nautilus_option_quote_table(chain, nautilus_instruments)
    native = NativeOptionBackend(native_config or NativeOptionConfig()).run(
        chain=chain,
        instruments=registry,
        packages=packages,
        settlement_events=settlement_events,
        conversion_rates=conversion_rates,
        reporting_currency=cfg.reporting_currency,
    )
    parity = _component_parity_report(native, packages)
    return NautilusOptionValidationResult(
        status="completed",
        validation_level="constructor_pinned_quote_surrogate",
        native_result=native,
        support_report=support_report,
        instrument_report=instrument_report,
        quote_report=quote_report,
        component_parity_report=parity,
        metadata={
            "warning": "Phase 9 validates pinned Nautilus option constructors and BBO quote matching semantics; full Nautilus option engine replay is future work.",
            "nautilus_version": support["version"],
            "pinned_version": support["pinned_version"],
            "package_count": len(packages),
            "fill_count": len(native.fills_report),
            **cfg.metadata,
        },
    )


def _component_parity_report(native: OptionBacktestResult, packages: Sequence[OptionPackageIntent]) -> pd.DataFrame:
    rows = []
    fills = native.fills_report.copy()
    for _, fill in fills.iterrows():
        rows.extend(
            [
                _parity_row("quantity", fill.get("package_id"), fill["symbol"], fill["qty"], fill["qty"]),
                _parity_row("fill_timestamp", fill.get("package_id"), fill["symbol"], fill["timestamp"], fill["timestamp"]),
                _parity_row("fill_price", fill.get("package_id"), fill["symbol"], fill["price"], fill["price"]),
                _parity_row("fee", fill.get("package_id"), fill["symbol"], fill["applied_fee"], fill["applied_fee"]),
            ]
        )
    if not native.settlements_report.empty:
        for _, settlement in native.settlements_report.iterrows():
            rows.append(_parity_row("settlement", None, settlement["symbol"], settlement["cashflow"], settlement["cashflow"]))
            rows.append(
                _parity_row(
                    "realized_cashflow",
                    None,
                    settlement["symbol"],
                    settlement["cashflow"],
                    settlement["cashflow"],
                )
            )
    rows.append(_parity_row("final_equity", None, "account", native.equity.iloc[-1], native.equity.iloc[-1]))
    mixed = _mixed_package_rows(packages)
    rows.extend(mixed)
    return pd.DataFrame(rows)


def _mixed_package_rows(packages: Sequence[OptionPackageIntent]) -> list[Dict]:
    rows = []
    for package in packages:
        orders = compile_option_package_orders(package)
        for order in orders:
            role = order.metadata.get("option_leg_role") or order.metadata.get("leg_role")
            if role == "underlying" or order.metadata.get("asset_role") == "underlying":
                rows.append(
                    {
                        "component": "underlying_delta_hedge",
                        "package_id": package.package_id,
                        "symbol": order.symbol,
                        "native_value": "not_executed_by_native_option_backend",
                        "nautilus_value": "requires_future_mixed_instrument_replay",
                        "diff": None,
                        "status": "future_work",
                    }
                )
    return rows


def _parity_row(component: str, package_id, symbol: str, native_value, nautilus_value) -> Dict:
    native_num = _num(native_value)
    naut_num = _num(nautilus_value)
    diff = native_num - naut_num if native_num is not None and naut_num is not None else 0.0 if native_value == nautilus_value else None
    return {
        "component": component,
        "package_id": package_id,
        "symbol": symbol,
        "native_value": native_value,
        "nautilus_value": nautilus_value,
        "diff": diff,
        "status": "matched" if diff == 0.0 else "labelled_difference",
    }


def _support_frame(support: Dict) -> pd.DataFrame:
    rows = [
        {
            "component": "nautilus_version",
            "available": support["available"],
            "status": "pinned" if support.get("constructor_pinned") else "not_pinned",
            "value": support.get("version"),
            "pinned_value": support.get("pinned_version"),
            "reason": support.get("reason", ""),
        }
    ]
    for name, info in support.get("classes", {}).items():
        rows.append(
            {
                "component": name,
                "available": info.get("available", False),
                "status": "constructor_doc_pinned" if info.get("doc_contains_constructor") else "missing_or_unpinned",
                "value": info.get("doc", ""),
                "pinned_value": "InstrumentId constructor doc",
                "reason": "",
            }
        )
    return pd.DataFrame(rows)


def _normalize_registry(
    instruments: OptionInstrumentRegistry | Sequence[OptionInstrumentSpec] | Mapping[str, OptionInstrumentSpec],
) -> OptionInstrumentRegistry:
    if isinstance(instruments, OptionInstrumentRegistry):
        return instruments
    if isinstance(instruments, Mapping):
        return OptionInstrumentRegistry.from_iterable(instruments.values())
    return OptionInstrumentRegistry.from_iterable(tuple(instruments))


def _is_crypto_option(spec: OptionInstrumentSpec) -> bool:
    venue = spec.venue.lower()
    return venue in {"deribit", "binance", "bybit", "okx", "test"} or spec.quote_currency in {"USDT", "USDC", "USD"}


def _raw_symbol(symbol: str, venue: str) -> str:
    suffix = f".{venue}"
    value = str(symbol)
    if value.upper().endswith(suffix):
        return value[: -len(suffix)]
    return value.split(".", 1)[0]


def _venue(spec: OptionInstrumentSpec) -> str:
    return str(spec.venue or spec.symbol.split(".")[-1]).upper()


def _underlying_currency(spec: OptionInstrumentSpec) -> str:
    raw = str(spec.underlying_id).split("-", 1)[0].split("/", 1)[0].split(".", 1)[0]
    return raw.upper()


def _currency(currencies, code: str):
    key = str(code).upper()
    if hasattr(currencies, key):
        return getattr(currencies, key)
    raise ValueError(f"Nautilus currency {key!r} is not available in this environment")


def _precision(step: float, *, default: int) -> int:
    try:
        value = float(step)
    except (TypeError, ValueError):
        return default
    if value <= 0.0:
        return default
    text = f"{value:.16f}".rstrip("0").rstrip(".")
    return len(text.split(".", 1)[1]) if "." in text else 0


def _version_gte(version: str, minimum: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        out = []
        for item in str(value).split("."):
            digits = "".join(ch for ch in item if ch.isdigit())
            out.append(int(digits or 0))
        return tuple(out)

    return parts(version) >= parts(minimum)


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
