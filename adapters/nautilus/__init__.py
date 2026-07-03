"""
Optional NautilusTrader backend adapter.

Importing this module does not require NautilusTrader to be installed. The
dependency is loaded lazily when a backend run is requested.
"""

from .backend import NautilusBackendConfig, NautilusBacktestEngine
from .instruments import (
    ensure_utc_ohlcv,
    make_binance_perpetual,
    normalize_binance_perp_symbol,
    supported_binance_perpetuals,
    timeframe_to_nautilus,
)
from .reports import result_from_nautilus_reports

__all__ = [
    "NautilusBackendConfig",
    "NautilusBacktestEngine",
    "ensure_utc_ohlcv",
    "make_binance_perpetual",
    "normalize_binance_perp_symbol",
    "result_from_nautilus_reports",
    "supported_binance_perpetuals",
    "timeframe_to_nautilus",
]
