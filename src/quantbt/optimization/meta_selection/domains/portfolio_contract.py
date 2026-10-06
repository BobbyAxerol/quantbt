"""Bounded original shared-account admission, not another portfolio engine."""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..common import MetaRecordError, digest


@dataclass(frozen=True, slots=True)
class PortfolioExecutionContract:
    universe: tuple[str, ...]
    portfolio_mode: str
    sizing: str
    semantic_id: str
    backend: str = "native_portfolio"
    timing: str = "original_close_to_close_no_signal_shift"
    diagnostic_account: str = "reset_flat"
    final_account: str = "carry_position"


def portfolio_execution_contract(config, wf_config, *, symbols=None, require_universe=False):
    from ....core.portfolio import (normalize_portfolio_mode, normalize_portfolio_sizing_mode,
                                   NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES)
    if config.backend not in {"auto", "native_portfolio"}:
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: portfolio meta requires native_portfolio final and IS authority")
    if wf_config.metadata.get("native_prepared_wfo", "off") == "require":
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: scalar Rust prepared scorer is not a shared-account portfolio")
    mode = normalize_portfolio_mode(config.portfolio_mode)
    sizing = normalize_portfolio_sizing_mode(config.sizing)
    if sizing not in NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES:
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: unqualified portfolio mode/sizing")
    universe = tuple(symbols if symbols is not None else (config.symbols or ()))
    if (len(universe) != len(set(universe)) or any(not isinstance(s, str) or not s for s in universe)
            or (require_universe and not universe)):
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: explicit unique ordered portfolio symbols required")
    semantic = digest(dict(mode=mode, sizing=sizing,
        betas=config.betas, risk_lookback=config.risk_lookback, universe=universe,
        account_metadata=config.account.metadata, execution=config.execution))
    return PortfolioExecutionContract(universe, mode, sizing, semantic)


def validate_portfolio_payload(payload, index, symbols):
    if isinstance(payload, pd.DataFrame):
        if tuple(payload.columns) != tuple(symbols) or not payload.index.equals(index):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: exact ordered positions universe/calendar required")
        arrays = (payload.to_numpy(dtype=float),)
    elif isinstance(payload, Mapping):
        if tuple(payload) != tuple(symbols) or any(not isinstance(v, pd.Series)
                or not v.index.equals(index) for v in payload.values()):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: exact ordered position Series required")
        arrays = tuple(v.to_numpy(dtype=float) for v in payload.values())
    else:
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: portfolio requires a positions DataFrame or mapping")
    if any(not np.isfinite(a).all() for a in arrays):
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: non-finite portfolio target")


def validate_portfolio_market(data, index, symbols):
    if (not isinstance(data, Mapping) or set(data) != set(symbols)
            or not isinstance(index, pd.DatetimeIndex) or index.tz is None
            or not index.is_unique or not index.is_monotonic_increasing or len(index) < 2):
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: exact aware mapping calendar and universe required")
    for symbol in symbols:
        frame = data[symbol]
        if (not isinstance(frame, pd.DataFrame) or not frame.index.equals(index)
                or not frame.columns.is_unique or not {"close", "high", "low"}.issubset(frame)):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: caller-aligned OHLC calendar required per symbol")
        prices = frame[["high", "low", "close"]].to_numpy(dtype=float)
        observed = np.isfinite(prices[:, 2])
        if (np.isinf(prices).any() or (prices[observed] <= 0).any()
                or not np.isfinite(prices[observed]).all()
                or (prices[observed, 0] < prices[observed, 2]).any()
                or (prices[observed, 1] > prices[observed, 2]).any()):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: invalid observed portfolio OHLC")


def funding_for(config, symbol):
    rates = config.funding_rate
    if isinstance(rates, Mapping):
        if symbol not in rates:
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: missing portfolio funding symbol")
        rates = rates[symbol]
    if not isinstance(rates, pd.Series) and not np.isscalar(rates):
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: portfolio funding requires scalar or indexed Series per symbol")
    return rates


def funding_policy(config, symbols):
    return dict(use_funding=config.use_funding, sources={s: "aligned_series"
        if isinstance(funding_for(config, s), pd.Series) else float(funding_for(config, s)) for s in symbols})


def update_account_witness(witness, result):
    """Bind common original buffers; do not rebuild full reports for a label."""
    from ....core.results import BacktestResultV2
    if not isinstance(result, BacktestResultV2) or result.metadata.get("backend") != "native_portfolio":
        raise MetaRecordError("META_DOMAIN_RESULT_UNBOUND: original native portfolio V2 required")
    fields = {"fees": result.fees, "funding": result.funding, "margin": result.margin,
              "diagnostics": result.diagnostics}
    for name in ("target_units_report", "accepted_units_report", "turnover_series", "slippage_series"):
        fields[name] = result.metadata.get(name)
    if any(not isinstance(value, (pd.Series, pd.DataFrame))
           or not value.index.equals(result.equity.index) for value in fields.values()):
        raise MetaRecordError("META_DOMAIN_RESULT_UNBOUND: original portfolio accounting buffers missing")
    accepted = result.metadata["accepted_units_report"]
    if (tuple(accepted.columns) != tuple(result.symbols)
            or tuple(result.positions.columns) != tuple(f"Position_{s}" for s in result.symbols)
            or not np.array_equal(accepted.to_numpy(), result.positions.to_numpy(), equal_nan=True)):
        raise MetaRecordError("META_DOMAIN_RESULT_UNBOUND: accepted portfolio positions differ")
    for name, values in fields.items():
        array = np.ascontiguousarray(values.to_numpy(dtype=np.float64))
        witness.update(digest({"portfolio_account_v1": name, "shape": array.shape,
            "columns": list(values.columns) if isinstance(values, pd.DataFrame) else None}).encode())
        witness.update(array.tobytes())
