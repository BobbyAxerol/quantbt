from .engine       import _engine_units, _engine_pct_equity, _engine_dca_ladder, _engine_portfolio
from .types        import BacktestResult
from .preprocessor import (
    validate_datetime,
    align_series,
    prepare_funding,
    make_funding_mask,
    build_arrays,
)

__all__ = [
    "_engine_units",
    "_engine_pct_equity",
    "_engine_dca_ladder",
    "_engine_portfolio",
    "BacktestResult",
    "validate_datetime",
    "align_series",
    "prepare_funding",
    "make_funding_mask",
    "build_arrays",
]
