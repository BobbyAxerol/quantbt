#!/usr/bin/env python3
"""
Run a real-data-ready parity audit for the Phase 11 native portfolio backend.

The script accepts an optional directory of OHLCV CSV/parquet files.  When no
market directory is supplied it falls back to deterministic correlated OHLCV so
the audit remains reproducible in CI and in clean workspaces.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    AccountConfig,
    LEGACY_PORTFOLIO_SIZING_MODES,
    NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES,
    PortfolioBacktestEngine,
    PortfolioDomainSpec,
    validate_portfolio_result_contract,
)


LEGACY_PARITY_MODES = ("longshort", "market_neutral", "directional", "equal_weight")
LEGACY_PARITY_SIZING = ("signal_notional", "signal", "notional", "unit")
NATIVE_ONLY_SIZING = ("target_units", "target_notional", "fixed_notional")
UNSUPPORTED_NATIVE_SIZING = (
    "%_equity",
    "pct_equity",
    "target_weight",
    "gross_exposure",
    "net_exposure",
    "dca_ladder",
)


def load_market_data(
    data_dir: Optional[Path],
    *,
    bars: int,
    symbols: Iterable[str],
    seed: int,
) -> Tuple[pd.DatetimeIndex, Dict[str, pd.Series], Dict[str, pd.Series], Dict[str, pd.Series], str]:
    if data_dir is not None:
        loaded = _load_ohlcv_directory(data_dir, bars=bars)
        if loaded is not None:
            return (*loaded, "data_dir")
    generated = _generate_realistic_ohlcv(bars=bars, symbols=tuple(symbols), seed=seed)
    return (*generated, "deterministic_mock_real")


def build_position_signals(closes: Mapping[str, pd.Series]) -> Dict[str, pd.Series]:
    close_frame = pd.DataFrame(closes).astype(float)
    common_close = close_frame.mean(axis=1)
    common_ret = np.log(common_close).diff()
    common_fast = common_ret.rolling(12, min_periods=12).mean()
    common_slow = common_ret.rolling(72, min_periods=72).mean()
    common_vol = common_ret.rolling(72, min_periods=72).std().replace(0.0, np.nan)
    common_z = ((common_fast - common_slow) / common_vol).shift(1).fillna(0.0)
    common_raw = np.where(common_z > 0.10, 1.0, np.where(common_z < -0.10, -1.0, 0.0))

    out: Dict[str, pd.Series] = {}
    for i, (symbol, close) in enumerate(closes.items()):
        scale = 1.0 + 0.25 * (i % 3)
        direction = -1.0 if i % 2 else 1.0
        out[symbol] = pd.Series(common_raw * scale * direction, index=close.index, name=symbol)
    return out


def run_suite(
    *,
    data_dir: Optional[Path] = None,
    bars: int = 2_000,
    symbols: Iterable[str] = ("BTC", "ETH", "SOL", "BNB"),
    seed: int = 42,
    initial_capital: float = 250_000.0,
    leverage: float = 5.0,
    fee_rate: float = 0.0004,
    tolerance: float = 1e-8,
) -> Dict:
    idx, closes, highs, lows, data_source = load_market_data(data_dir, bars=bars, symbols=symbols, seed=seed)
    positions = build_position_signals(closes)
    symbol_list = list(closes.keys())
    alloc = {symbol: 10_000.0 * (1.0 + 0.25 * (i % 4)) for i, symbol in enumerate(symbol_list)}
    account = AccountConfig(initial_capital=initial_capital, leverage=leverage, maintenance_ratio=0.005)

    parity_records = []
    for mode in LEGACY_PARITY_MODES:
        for sizing in LEGACY_PARITY_SIZING:
            legacy = _run_portfolio(
                positions,
                closes,
                highs,
                lows,
                idx,
                mode=mode,
                backend="legacy_portfolio",
                hedge_type=sizing,
                account=account,
                alloc_per_trade=alloc,
                fee_rate=fee_rate,
            )
            native = _run_portfolio(
                positions,
                closes,
                highs,
                lows,
                idx,
                mode=mode,
                backend="native_portfolio",
                hedge_type=sizing,
                account=account,
                alloc_per_trade=alloc,
                fee_rate=fee_rate,
            )
            contract = validate_portfolio_result_contract(
                native,
                PortfolioDomainSpec(mode=mode, sizing_mode=sizing),
                tolerance=tolerance,
                raise_on_fail=False,
            )
            record = {
                "mode": mode,
                "sizing_mode": sizing,
                "legacy_final_equity": float(legacy.equity.iloc[-1]),
                "native_final_equity": float(native.equity.iloc[-1]),
                "max_abs_equity_diff": _max_abs_series_diff(native.equity, legacy.equity),
                "max_abs_position_diff": _max_abs_frame_diff(native.positions, legacy.positions),
                "max_abs_target_units_diff": _max_abs_metadata_frame_diff(native, legacy, "target_units_report"),
                "max_abs_accepted_units_diff": _max_abs_metadata_frame_diff(native, legacy, "accepted_units_report"),
                "max_abs_accepted_notional_diff": _max_abs_metadata_frame_diff(
                    native, legacy, "accepted_notional_report"
                ),
                "contract_passed": bool(contract["passed"]),
            }
            record["passed"] = (
                record["max_abs_equity_diff"] <= tolerance
                and record["max_abs_position_diff"] <= tolerance
                and record["max_abs_target_units_diff"] <= tolerance
                and record["max_abs_accepted_units_diff"] <= tolerance
                and record["max_abs_accepted_notional_diff"] <= tolerance
                and record["contract_passed"]
            )
            parity_records.append(record)

    native_only_records = []
    native_only_positions = {
        "target_units": positions,
        "target_notional": {symbol: series * alloc[symbol] for symbol, series in positions.items()},
        "fixed_notional": positions,
    }
    for sizing in NATIVE_ONLY_SIZING:
        result = _run_portfolio(
            native_only_positions[sizing],
            closes,
            highs,
            lows,
            idx,
            mode="longshort",
            backend="native_portfolio",
            hedge_type=sizing,
            account=account,
            alloc_per_trade=alloc,
            fee_rate=fee_rate,
        )
        contract = validate_portfolio_result_contract(
            result,
            PortfolioDomainSpec(mode="longshort", sizing_mode=sizing),
            tolerance=tolerance,
            raise_on_fail=False,
        )
        native_only_records.append(
            {
                "mode": "longshort",
                "sizing_mode": sizing,
                "final_equity": float(result.equity.iloc[-1]),
                "max_gross_leverage": _safe_max(result.metadata["exposure_report"]["gross_leverage"]),
                "fee_total": float(result.metadata["fee_total"]),
                "turnover_total": float(result.metadata["turnover_total"]),
                "contract_passed": bool(contract["passed"]),
                "passed": bool(contract["passed"]),
            }
        )

    unsupported_records = []
    for sizing in UNSUPPORTED_NATIVE_SIZING:
        unsupported_records.append(_probe_unsupported_sizing(positions, closes, highs, lows, idx, sizing, account, alloc, fee_rate))

    parity_passed = all(item["passed"] for item in parity_records)
    native_only_passed = all(item["passed"] for item in native_only_records)
    unsupported_passed = all(item["rejected"] for item in unsupported_records)
    return {
        "status": "pass" if parity_passed and native_only_passed and unsupported_passed else "fail",
        "data_source": data_source,
        "bars": int(len(idx)),
        "symbols": symbol_list,
        "initial_capital": float(initial_capital),
        "leverage": float(leverage),
        "fee_rate_round_trip": float(fee_rate),
        "native_supported_modes": list(LEGACY_PARITY_MODES),
        "native_supported_sizing_modes": sorted(NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES),
        "legacy_compatible_sizing_modes": sorted(LEGACY_PORTFOLIO_SIZING_MODES),
        "native_unsupported_sizing_modes": list(UNSUPPORTED_NATIVE_SIZING),
        "parity_records": parity_records,
        "native_only_records": native_only_records,
        "unsupported_records": unsupported_records,
        "summary": {
            "legacy_parity_cases": len(parity_records),
            "legacy_parity_passed": parity_passed,
            "native_only_cases": len(native_only_records),
            "native_only_passed": native_only_passed,
            "unsupported_cases": len(unsupported_records),
            "unsupported_rejected": unsupported_passed,
            "max_abs_equity_diff": max(item["max_abs_equity_diff"] for item in parity_records),
            "max_abs_position_diff": max(item["max_abs_position_diff"] for item in parity_records),
            "max_abs_target_units_diff": max(item["max_abs_target_units_diff"] for item in parity_records),
            "max_abs_accepted_notional_diff": max(item["max_abs_accepted_notional_diff"] for item in parity_records),
        },
    }


def make_markdown_report(report: Dict) -> str:
    summary = report["summary"]
    lines = [
        "# Native Portfolio Real-Parity Audit",
        "",
        f"Status: **{report['status']}**",
        f"Data source: `{report['data_source']}`",
        f"Shape: `{report['bars']}` bars x `{len(report['symbols'])}` symbols",
        f"Symbols: `{', '.join(report['symbols'])}`",
        "",
        "## Summary",
        "",
        f"- Legacy-compatible parity cases: `{summary['legacy_parity_cases']}`",
        f"- Legacy parity passed: `{summary['legacy_parity_passed']}`",
        f"- Native-only domain cases: `{summary['native_only_cases']}`",
        f"- Native-only contract passed: `{summary['native_only_passed']}`",
        f"- Unsupported sizing rejected: `{summary['unsupported_rejected']}`",
        f"- Max abs equity diff: `{summary['max_abs_equity_diff']:.12g}`",
        f"- Max abs position diff: `{summary['max_abs_position_diff']:.12g}`",
        f"- Max abs target units diff: `{summary['max_abs_target_units_diff']:.12g}`",
        f"- Max abs accepted notional diff: `{summary['max_abs_accepted_notional_diff']:.12g}`",
        "",
        "## Supported Surface",
        "",
        f"- Modes: `{', '.join(report['native_supported_modes'])}`",
        f"- Sizing: `{', '.join(report['native_supported_sizing_modes'])}`",
        f"- Explicitly rejected: `{', '.join(report['native_unsupported_sizing_modes'])}`",
        "",
        "## Legacy-Compatible Parity",
        "",
        "| mode | sizing | legacy equity | native equity | max equity diff | max position diff | pass |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["parity_records"]:
        lines.append(
            "| {mode} | {sizing_mode} | {legacy_final_equity:.6f} | {native_final_equity:.6f} | "
            "{max_abs_equity_diff:.3g} | {max_abs_position_diff:.3g} | {passed} |".format(**item)
        )
    lines.extend(
        [
            "",
            "## Native-Only Contract Checks",
            "",
            "| mode | sizing | final equity | max gross leverage | fee total | turnover total | pass |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in report["native_only_records"]:
        lines.append(
            "| {mode} | {sizing_mode} | {final_equity:.6f} | {max_gross_leverage:.6f} | "
            "{fee_total:.6f} | {turnover_total:.6f} | {passed} |".format(**item)
        )
    return "\n".join(lines) + "\n"


def _run_portfolio(
    positions: Mapping[str, pd.Series],
    closes: Mapping[str, pd.Series],
    highs: Mapping[str, pd.Series],
    lows: Mapping[str, pd.Series],
    idx: pd.DatetimeIndex,
    *,
    mode: str,
    backend: str,
    hedge_type: str,
    account: AccountConfig,
    alloc_per_trade: Mapping[str, float],
    fee_rate: float,
):
    engine = PortfolioBacktestEngine(
        positions=dict(positions),
        closes=dict(closes),
        highs=dict(highs),
        lows=dict(lows),
        datetime_index=idx,
        mode=mode,
        backend=backend,
        account=account,
        fee_rate=fee_rate,
        alloc_per_trade=dict(alloc_per_trade),
        contract_size=1.0,
        hedge_type=hedge_type,
        asset_type="crypto",
        use_funding=False,
    )
    return engine.result


def _probe_unsupported_sizing(
    positions: Mapping[str, pd.Series],
    closes: Mapping[str, pd.Series],
    highs: Mapping[str, pd.Series],
    lows: Mapping[str, pd.Series],
    idx: pd.DatetimeIndex,
    sizing: str,
    account: AccountConfig,
    alloc_per_trade: Mapping[str, float],
    fee_rate: float,
) -> Dict:
    try:
        _run_portfolio(
            positions,
            closes,
            highs,
            lows,
            idx,
            mode="longshort",
            backend="native_portfolio",
            hedge_type=sizing,
            account=account,
            alloc_per_trade=alloc_per_trade,
            fee_rate=fee_rate,
        )
    except (NotImplementedError, ValueError) as exc:
        return {"sizing_mode": sizing, "rejected": True, "error": type(exc).__name__, "message": str(exc)}
    return {"sizing_mode": sizing, "rejected": False, "error": None, "message": "unexpectedly accepted"}


def _generate_realistic_ohlcv(
    *,
    bars: int,
    symbols: Tuple[str, ...],
    seed: int,
) -> Tuple[pd.DatetimeIndex, Dict[str, pd.Series], Dict[str, pd.Series], Dict[str, pd.Series]]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=bars, freq="1h", tz="UTC")
    market = rng.normal(0.00005, 0.010, size=bars)
    closes: Dict[str, pd.Series] = {}
    highs: Dict[str, pd.Series] = {}
    lows: Dict[str, pd.Series] = {}
    start_prices = np.linspace(32_000.0, 250.0, num=len(symbols))
    for i, symbol in enumerate(symbols):
        idio = rng.normal(0.0, 0.006 + 0.001 * i, size=bars)
        seasonal = 0.0002 * np.sin(np.linspace(0.0, 8.0 * np.pi, bars) + i)
        log_ret = 0.65 * market + 0.35 * idio + seasonal
        price = start_prices[i] * np.exp(np.cumsum(log_ret))
        spread = np.abs(rng.normal(0.0015, 0.0005, size=bars))
        close = pd.Series(price, index=idx, name=symbol)
        closes[symbol] = close
        highs[symbol] = pd.Series(price * (1.0 + spread), index=idx, name=symbol)
        lows[symbol] = pd.Series(price * (1.0 - spread), index=idx, name=symbol)
    return idx, closes, highs, lows


def _load_ohlcv_directory(
    data_dir: Path,
    *,
    bars: int,
) -> Optional[Tuple[pd.DatetimeIndex, Dict[str, pd.Series], Dict[str, pd.Series], Dict[str, pd.Series]]]:
    if not data_dir.exists():
        return None
    frames = {}
    for path in sorted([*data_dir.glob("*.csv"), *data_dir.glob("*.parquet"), *data_dir.glob("*.feather")]):
        frame = _read_ohlcv_file(path)
        if frame is None:
            continue
        frames[path.stem.upper()] = frame
    if len(frames) < 2:
        return None

    common_index = None
    for frame in frames.values():
        common_index = frame.index if common_index is None else common_index.intersection(frame.index)
    if common_index is None or len(common_index) < 50:
        return None
    common_index = common_index.sort_values()[-bars:]
    closes = {symbol: frame.reindex(common_index)["close"].ffill().dropna() for symbol, frame in frames.items()}
    valid_index = common_index
    for series in closes.values():
        valid_index = valid_index.intersection(series.index)
    valid_index = valid_index.sort_values()
    closes = {symbol: frame.reindex(valid_index)["close"].ffill() for symbol, frame in frames.items()}
    highs = {symbol: frame.reindex(valid_index)["high"].ffill() for symbol, frame in frames.items()}
    lows = {symbol: frame.reindex(valid_index)["low"].ffill() for symbol, frame in frames.items()}
    return valid_index, closes, highs, lows


def _read_ohlcv_file(path: Path) -> Optional[pd.DataFrame]:
    try:
        if path.suffix == ".parquet":
            frame = pd.read_parquet(path)
        elif path.suffix == ".feather":
            frame = pd.read_feather(path)
        else:
            frame = pd.read_csv(path)
    except Exception:
        return None

    frame = frame.copy()
    frame.columns = [str(col).lower() for col in frame.columns]
    if "close" not in frame.columns:
        return None
    if "high" not in frame.columns:
        frame["high"] = frame["close"]
    if "low" not in frame.columns:
        frame["low"] = frame["close"]

    dt_col = next((col for col in ("datetime", "timestamp", "date", "time") if col in frame.columns), None)
    if dt_col is not None:
        idx = pd.to_datetime(frame[dt_col], utc=True, errors="coerce")
    else:
        idx = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame.index = idx
    frame = frame.loc[frame.index.notna(), ["close", "high", "low"]].astype(float).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame.dropna()


def _max_abs_series_diff(left: pd.Series, right: pd.Series) -> float:
    a, b = left.align(right, join="inner")
    if len(a) == 0:
        return float("inf")
    return float(np.max(np.abs(a.to_numpy(dtype=float) - b.to_numpy(dtype=float))))


def _max_abs_frame_diff(left: pd.DataFrame, right: pd.DataFrame) -> float:
    a, b = left.align(right, join="inner", axis=None)
    if a.empty and b.empty:
        return 0.0
    if a.empty or b.empty:
        return float("inf")
    return float(np.max(np.abs(a.to_numpy(dtype=float) - b.to_numpy(dtype=float))))


def _max_abs_metadata_frame_diff(left, right, key: str) -> float:
    return _max_abs_frame_diff(left.metadata[key], right.metadata[key])


def _safe_max(series: pd.Series) -> float:
    return float(series.max()) if len(series) else 0.0


def _json_default(value):
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None, help="Directory containing OHLCV CSV/parquet files.")
    parser.add_argument("--bars", type=int, default=2_000)
    parser.add_argument("--symbols", default="BTC,ETH,SOL,BNB")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "portfolio_real_parity_report.json")
    parser.add_argument("--md-out", type=Path, default=PACKAGE_DIR / "benchmarks" / "portfolio_real_parity_report.md")
    args = parser.parse_args(argv)

    report = run_suite(
        data_dir=args.data_dir,
        bars=args.bars,
        symbols=tuple(item.strip() for item in args.symbols.split(",") if item.strip()),
        seed=args.seed,
    )
    markdown = make_markdown_report(report)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, default=_json_default) + "\n", encoding="utf-8")
    args.md_out.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
