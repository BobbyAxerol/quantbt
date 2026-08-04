"""
Data and instrument helpers for NautilusTrader adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd


@dataclass(frozen=True)
class BinancePerpSpec:
    raw_symbol: str
    base_currency: str
    price_precision: int
    price_increment: str
    size_precision: int
    size_increment: str
    max_quantity: str
    min_quantity: str
    max_price: str
    min_price: str
    margin_init: str = "0.0500"
    margin_maint: str = "0.0250"
    maker_fee: str = "0.0002"
    taker_fee: str = "0.0004"


SUPPORTED_BINANCE_PERP_SPECS = {
    "BTCUSDT": BinancePerpSpec(
        raw_symbol="BTCUSDT",
        base_currency="BTC",
        price_precision=1,
        price_increment="0.1",
        size_precision=3,
        size_increment="0.001",
        max_quantity="1000.000",
        min_quantity="0.001",
        max_price="809484.0",
        min_price="261.1",
        maker_fee="0.000200",
        taker_fee="0.000180",
    ),
    "ETHUSDT": BinancePerpSpec(
        raw_symbol="ETHUSDT",
        base_currency="ETH",
        price_precision=2,
        price_increment="0.01",
        size_precision=3,
        size_increment="0.001",
        max_quantity="10000.000",
        min_quantity="0.001",
        max_price="152588.43",
        min_price="29.91",
    ),
    "BNBUSDT": BinancePerpSpec(
        raw_symbol="BNBUSDT",
        base_currency="BNB",
        price_precision=2,
        price_increment="0.01",
        size_precision=2,
        size_increment="0.01",
        max_quantity="100000.00",
        min_quantity="0.01",
        max_price="100000.00",
        min_price="1.00",
    ),
    "SOLUSDT": BinancePerpSpec(
        raw_symbol="SOLUSDT",
        base_currency="SOL",
        price_precision=3,
        price_increment="0.001",
        size_precision=2,
        size_increment="0.01",
        max_quantity="100000.00",
        min_quantity="0.01",
        max_price="100000.000",
        min_price="0.100",
    ),
    "DOGEUSDT": BinancePerpSpec(
        raw_symbol="DOGEUSDT",
        base_currency="DOGE",
        price_precision=5,
        price_increment="0.00001",
        size_precision=0,
        size_increment="1",
        max_quantity="100000000",
        min_quantity="1",
        max_price="1000.00000",
        min_price="0.00010",
    ),
    "ARBUSDT": BinancePerpSpec(
        raw_symbol="ARBUSDT",
        base_currency="ARB",
        price_precision=4,
        price_increment="0.0001",
        size_precision=1,
        size_increment="0.1",
        max_quantity="10000000.0",
        min_quantity="0.1",
        max_price="10000.0000",
        min_price="0.0001",
    ),
    "LINKUSDT": BinancePerpSpec(
        raw_symbol="LINKUSDT",
        base_currency="LINK",
        price_precision=3,
        price_increment="0.001",
        size_precision=2,
        size_increment="0.01",
        max_quantity="1000000.00",
        min_quantity="0.01",
        max_price="100000.000",
        min_price="0.001",
    ),
}

_ALIASES = {
    "BTC": "BTCUSDT",
    "BTCUSDT-PERP": "BTCUSDT",
    "BTCUSDT-PERP.BINANCE": "BTCUSDT",
    "ETH": "ETHUSDT",
    "ETHUSDT-PERP": "ETHUSDT",
    "ETHUSDT-PERP.BINANCE": "ETHUSDT",
    "BNB": "BNBUSDT",
    "BNBUSDT-PERP": "BNBUSDT",
    "BNBUSDT-PERP.BINANCE": "BNBUSDT",
    "SOL": "SOLUSDT",
    "SOLUSDT-PERP": "SOLUSDT",
    "SOLUSDT-PERP.BINANCE": "SOLUSDT",
    "DOGE": "DOGEUSDT",
    "DOGEUSDT-PERP": "DOGEUSDT",
    "DOGEUSDT-PERP.BINANCE": "DOGEUSDT",
    "ARB": "ARBUSDT",
    "ARP": "ARBUSDT",
    "ARBUSDT-PERP": "ARBUSDT",
    "ARBUSDT-PERP.BINANCE": "ARBUSDT",
    "ARPUSDT": "ARBUSDT",
    "ARPUSDT-PERP": "ARBUSDT",
    "ARPUSDT-PERP.BINANCE": "ARBUSDT",
    "LINK": "LINKUSDT",
    "LINKUSDT-PERP": "LINKUSDT",
    "LINKUSDT-PERP.BINANCE": "LINKUSDT",
}

_TIMEFRAME_MAP = {
    "1min": "1-MINUTE",
    "1m": "1-MINUTE",
    "5min": "5-MINUTE",
    "5m": "5-MINUTE",
    "15min": "15-MINUTE",
    "15m": "15-MINUTE",
    "30min": "30-MINUTE",
    "30m": "30-MINUTE",
    "1h": "1-HOUR",
    "2h": "2-HOUR",
    "4h": "4-HOUR",
    "6h": "6-HOUR",
    "12h": "12-HOUR",
    "1d": "1-DAY",
    "1w": "1-WEEK",
}


def supported_binance_perpetuals() -> list[str]:
    return [f"{symbol}-PERP.BINANCE" for symbol in SUPPORTED_BINANCE_PERP_SPECS]


def normalize_binance_perp_symbol(instrument_id: str) -> str:
    key = str(instrument_id).upper().strip().replace("/", "")
    if key in _ALIASES:
        return _ALIASES[key]
    if key.endswith(".BINANCE"):
        key = key.removesuffix(".BINANCE")
    if key.endswith("-PERP"):
        key = key.removesuffix("-PERP")
    if key in SUPPORTED_BINANCE_PERP_SPECS:
        return key
    raise ValueError(
        f"Unsupported Nautilus Binance perpetual {instrument_id!r}. "
        f"Supported: {', '.join(supported_binance_perpetuals())}"
    )


def make_binance_perpetual(instrument_id: str, nt):
    """
    Return a Nautilus Binance USDT perpetual test/synthetic instrument.

    BTC and ETH use Nautilus test-kit providers. Other liquid symbols are
    synthetic `CryptoPerpetual` definitions suitable for external OHLCV bars.
    """
    raw_symbol = normalize_binance_perp_symbol(instrument_id)
    if raw_symbol == "BTCUSDT":
        return nt.TestInstrumentProvider.btcusdt_perp_binance()
    if raw_symbol == "ETHUSDT":
        return nt.TestInstrumentProvider.ethusdt_perp_binance()

    from nautilus_trader.model import currencies
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import CryptoPerpetual
    from nautilus_trader.model.objects import Money, Price, Quantity

    spec = SUPPORTED_BINANCE_PERP_SPECS[raw_symbol]
    base_currency = getattr(currencies, spec.base_currency)
    return CryptoPerpetual(
        instrument_id=InstrumentId(
            symbol=Symbol(f"{raw_symbol}-PERP"),
            venue=Venue("BINANCE"),
        ),
        raw_symbol=Symbol(raw_symbol),
        base_currency=base_currency,
        quote_currency=currencies.USDT,
        settlement_currency=currencies.USDT,
        is_inverse=False,
        price_precision=spec.price_precision,
        price_increment=Price.from_str(spec.price_increment),
        size_precision=spec.size_precision,
        size_increment=Quantity.from_str(spec.size_increment),
        max_quantity=Quantity.from_str(spec.max_quantity),
        min_quantity=Quantity.from_str(spec.min_quantity),
        max_notional=None,
        min_notional=Money(10.00, currencies.USDT),
        max_price=Price.from_str(spec.max_price),
        min_price=Price.from_str(spec.min_price),
        margin_init=Decimal(spec.margin_init),
        margin_maint=Decimal(spec.margin_maint),
        maker_fee=Decimal(spec.maker_fee),
        taker_fee=Decimal(spec.taker_fee),
        ts_event=1646199312128000000,
        ts_init=1646199342953849862,
    )


def timeframe_to_nautilus(timeframe: str) -> str:
    try:
        return _TIMEFRAME_MAP[timeframe.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe {timeframe!r}") from exc


def ensure_utc_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    """
    Return Nautilus-compatible OHLCV data.

    Required output columns are lowercase: open, high, low, close, volume.
    Index is a UTC DatetimeIndex.
    """
    df = data.copy()
    rename = {
        "Date": "timestamp",
        "Datetime": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("data must have a DatetimeIndex or timestamp column")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"missing OHLCV columns: {missing}")
    return df[required].sort_index()
