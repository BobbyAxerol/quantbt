"""
quantbt.backends.native_portfolio
---------------------------------
Native portfolio backend.

Phase 11B keeps the proven `_engine_portfolio` accounting kernel as the
compatibility oracle path, but moves portfolio preparation, mode transforms, and
report construction behind an explicit backend.  This lets the native portfolio
route evolve independently from `MultiSymbolPortfolio` without changing legacy
endpoint defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from ..core.engine import _engine_portfolio, _engine_portfolio_equity_sizing
from ..core.portfolio import (
    NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES,
    PortfolioDomainSpec,
    normalize_portfolio_mode,
    normalize_portfolio_sizing_mode,
    validate_portfolio_result_contract,
)
from ..core.preprocessor import align_series, build_market_arrays, build_signal_matrix, prepare_funding, validate_datetime
from ..core.results import BacktestResultV2
from ..core.schema import AccountConfig
from ..core.schema import ExecutionConfig
from ..sizing.fast import scale_signal_notional_matrix
from ..sizing.modes import compute_target_units


@dataclass(frozen=True)
class NativePortfolioConfig:
    account: AccountConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fee_rate: float = 0.0
    use_funding: bool = True

    def __post_init__(self) -> None:
        if float(self.fee_rate) < 0.0:
            raise ValueError("fee_rate must be >= 0")


class NativePortfolioBackend:
    """
    Explicit native portfolio backend for multi-symbol position matrices.

    `fee_rate` is interpreted as a one-way rate inside this backend.  The
    `PortfolioBacktestEngine` facade keeps the legacy public convention and
    passes the already-halved one-way value for parity.
    """

    def __init__(self, config: NativePortfolioConfig):
        self.config = config

    def run_signals(
        self,
        positions: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        *,
        mode: str = "longshort",
        alloc_per_trade: Union[float, Dict[str, float]] = 100_000.0,
        contract_size: Union[float, Dict[str, float], None] = 1.0,
        hedge_type: str = "signal_notional",
        funding_rate: Union[float, Dict[str, float], pd.Series, None] = 0.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        maintenance_ratio: Optional[float] = None,
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        symbols: Optional[Sequence[str]] = None,
        use_pyramiding: bool = True,
        asset_type: str = "crypto",
        betas: Optional[Union[float, Dict[str, float]]] = None,
        risk_lookback: int = 60,
    ) -> BacktestResultV2:
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(positions.keys())
        if set(symbol_list) != set(positions.keys()) or set(symbol_list) != set(closes.keys()):
            raise ValueError("symbols, positions, and closes must contain the same keys")

        portfolio_mode = normalize_portfolio_mode(mode)
        sizing_mode = normalize_portfolio_sizing_mode(hedge_type)
        if sizing_mode not in NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES:
            raise NotImplementedError(
                f"native_portfolio does not yet support equity-dependent sizing mode {hedge_type!r}"
            )

        close_dict = align_series(closes, symbol_list, idx)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        pos_dict = align_series(positions, symbol_list, idx, fill_val=0.0)
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
        market = build_market_arrays(symbol_list, idx, close_dict, high_dict, low_dict, funding_dict)
        raw_signals = build_signal_matrix(symbol_list, idx, pos_dict)

        cs_arr = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        lev_arr = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        alloc_arr = self._per_symbol_array(alloc_per_trade, symbol_list, default=100_000.0)
        maint_ratio = self.config.account.maintenance_ratio if maintenance_ratio is None else float(maintenance_ratio)

        beta_arr = self._per_symbol_array(betas, symbol_list, default=1.0)
        risk_vol = self._risk_volatility_matrix(market.closes, lookback=int(risk_lookback))
        inv_vol = np.divide(1.0, risk_vol, out=np.ones_like(risk_vol), where=risk_vol > 0.0)
        equity_aware = sizing_mode in {"%_equity", "target_weight", "gross_exposure", "net_exposure"}

        if equity_aware:
            (
                equity_arr,
                target_units,
                pos_arr,
                sym_pnl_arr,
                fee_arr,
                turnover_arr,
                liq_flag,
                liq_idx,
            ) = _engine_portfolio_equity_sizing(
                n_bars=len(idx),
                n_syms=len(symbol_list),
                highs=market.highs,
                lows=market.lows,
                closes=market.closes,
                raw_signals=raw_signals,
                funding_rates=market.funding,
                is_funding_bar=market.is_funding_bar,
                init_capital=self.config.account.initial_capital,
                leverages=lev_arr,
                maint_ratio=maint_ratio,
                fee_rate=float(self.config.fee_rate),
                contract_sizes=cs_arr,
                use_funding=bool(self.config.use_funding),
                allocs=alloc_arr,
                sizing_mode_id=self._sizing_mode_id(sizing_mode),
                portfolio_mode_id=self._portfolio_mode_id(portfolio_mode),
                use_pyramiding=bool(use_pyramiding),
                exposure_scalar=float(np.mean(alloc_arr)) if len(alloc_arr) else 1.0,
                beta=beta_arr,
                inv_vol=inv_vol,
            )
        else:
            target_units = self._scale_target_units(
                sizing_mode=sizing_mode,
                raw_signals=raw_signals,
                closes=market.closes,
                idx=idx,
                symbols=symbol_list,
                close_dict=close_dict,
                alloc_arr=alloc_arr,
                contract_sizes=cs_arr,
                use_pyramiding=use_pyramiding,
            )
            target_units = self._apply_mode(
                mode=portfolio_mode,
                target_units=target_units,
                closes=market.closes,
                contract_sizes=cs_arr,
                betas=beta_arr,
                risk_vol=risk_vol,
            )

            (
                equity_arr,
                pos_arr,
                sym_pnl_arr,
                fee_arr,
                turnover_arr,
                liq_flag,
                liq_idx,
            ) = _engine_portfolio(
                n_bars=len(idx),
                n_syms=len(symbol_list),
                highs=market.highs,
                lows=market.lows,
                closes=market.closes,
                target_pos=target_units,
                funding_rates=market.funding,
                is_funding_bar=market.is_funding_bar,
                init_capital=self.config.account.initial_capital,
                leverages=lev_arr,
                maint_ratio=maint_ratio,
                fee_rate=float(self.config.fee_rate),
                contract_sizes=cs_arr,
                use_funding=bool(self.config.use_funding),
            )

        result = self._build_result(
            idx=idx,
            symbol_list=symbol_list,
            closes_m=market.closes,
            target_m=target_units,
            pos_arr=pos_arr,
            sym_pnl_arr=sym_pnl_arr,
            funding_m=market.funding,
            is_funding_bar=market.is_funding_bar,
            equity_arr=equity_arr,
            fee_arr=fee_arr,
            turnover_arr=turnover_arr,
            contract_sizes=cs_arr,
            leverages=lev_arr,
            betas=beta_arr,
            risk_vol=risk_vol,
            mode=portfolio_mode,
            hedge_type=sizing_mode,
            asset_type=asset_type,
            maintenance_ratio=maint_ratio,
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
        )
        spec = PortfolioDomainSpec(mode=portfolio_mode, sizing_mode=sizing_mode)
        result.metadata["portfolio_contract_report"] = validate_portfolio_result_contract(result, spec, tolerance=1e-8)
        return result

    @staticmethod
    def _scale_target_units(
        *,
        sizing_mode: str,
        raw_signals: np.ndarray,
        closes: np.ndarray,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        close_dict: Dict[str, pd.Series],
        alloc_arr: np.ndarray,
        contract_sizes: np.ndarray,
        use_pyramiding: bool,
    ) -> np.ndarray:
        if sizing_mode in ("signal_notional", "signal"):
            return scale_signal_notional_matrix(raw_signals, closes, alloc_arr, use_pyramiding=use_pyramiding)

        if sizing_mode == "target_units":
            return np.ascontiguousarray(raw_signals, dtype=np.float64)

        denom = closes * contract_sizes.reshape(1, -1)
        if sizing_mode == "target_notional":
            return np.ascontiguousarray(
                np.divide(raw_signals, denom, out=np.zeros_like(raw_signals, dtype=np.float64), where=denom != 0.0),
                dtype=np.float64,
            )

        if sizing_mode == "fixed_notional":
            sig = raw_signals if use_pyramiding else np.sign(raw_signals)
            notionals = sig * alloc_arr.reshape(1, -1)
            return np.ascontiguousarray(
                np.divide(notionals, denom, out=np.zeros_like(raw_signals, dtype=np.float64), where=denom != 0.0),
                dtype=np.float64,
            )

        out = np.zeros_like(raw_signals, dtype=np.float64)
        for j, symbol in enumerate(symbols):
            signal = pd.Series(raw_signals[:, j], index=idx)
            out[:, j] = compute_target_units(
                hedge_type=sizing_mode,
                signal=signal,
                close=close_dict[symbol],
                alloc=float(alloc_arr[j]),
                use_pyramiding=use_pyramiding,
            ).to_numpy(dtype=np.float64)
        return np.ascontiguousarray(out, dtype=np.float64)

    @staticmethod
    def _apply_mode(
        *,
        mode: str,
        target_units: np.ndarray,
        closes: np.ndarray,
        contract_sizes: np.ndarray,
        betas: np.ndarray,
        risk_vol: np.ndarray,
    ) -> np.ndarray:
        out = np.array(target_units, dtype=np.float64, copy=True, order="C")
        notional = out * closes * contract_sizes.reshape(1, -1)

        if mode == "market_neutral":
            long_sum = np.where(notional > 0.0, notional, 0.0).sum(axis=1)
            short_sum = np.where(notional < 0.0, -notional, 0.0).sum(axis=1)
            target = (long_sum + short_sum) / 2.0
            long_scale = np.divide(target, long_sum, out=np.ones_like(target), where=long_sum != 0.0)
            short_scale = np.divide(target, short_sum, out=np.ones_like(target), where=short_sum != 0.0)
            out = np.where(
                notional > 0.0,
                out * long_scale.reshape(-1, 1),
                np.where(notional < 0.0, out * short_scale.reshape(-1, 1), 0.0),
            )
        elif mode == "directional":
            dominant = np.abs(notional).argmax(axis=1)
            mask = np.zeros_like(out, dtype=bool)
            mask[np.arange(out.shape[0]), dominant] = True
            out = np.where(mask, out, 0.0)
            out = np.where(np.abs(notional).sum(axis=1).reshape(-1, 1) > 0.0, out, 0.0)
        elif mode == "equal_weight":
            active = (notional != 0.0).sum(axis=1)
            gross = np.abs(notional).sum(axis=1)
            target_abs = np.divide(gross, active, out=np.zeros_like(gross), where=active != 0)
            denom = closes * contract_sizes.reshape(1, -1)
            out = np.sign(notional) * np.divide(
                target_abs.reshape(-1, 1),
                denom,
                out=np.zeros_like(out),
                where=denom != 0.0,
            )
        elif mode == "risk_parity":
            gross = np.abs(notional).sum(axis=1)
            inv_vol = np.divide(1.0, risk_vol, out=np.ones_like(risk_vol), where=risk_vol > 0.0)
            active_inv = np.where(notional != 0.0, inv_vol, 0.0)
            denom_inv = active_inv.sum(axis=1)
            target_abs = np.divide(gross.reshape(-1, 1) * active_inv, denom_inv.reshape(-1, 1), out=np.zeros_like(out), where=denom_inv.reshape(-1, 1) != 0.0)
            denom = closes * contract_sizes.reshape(1, -1)
            out = np.sign(notional) * np.divide(target_abs, denom, out=np.zeros_like(out), where=denom != 0.0)
        elif mode == "beta_neutral":
            beta_notional = notional * betas.reshape(1, -1)
            long_beta = np.where(beta_notional > 0.0, beta_notional, 0.0).sum(axis=1)
            short_beta = np.where(beta_notional < 0.0, -beta_notional, 0.0).sum(axis=1)
            target = (long_beta + short_beta) / 2.0
            long_scale = np.divide(target, long_beta, out=np.zeros_like(target), where=long_beta != 0.0)
            short_scale = np.divide(target, short_beta, out=np.zeros_like(target), where=short_beta != 0.0)
            out = np.where(
                beta_notional > 0.0,
                out * long_scale.reshape(-1, 1),
                np.where(beta_notional < 0.0, out * short_scale.reshape(-1, 1), 0.0),
            )

        return np.ascontiguousarray(out, dtype=np.float64)

    def _build_result(
        self,
        *,
        idx: pd.DatetimeIndex,
        symbol_list: List[str],
        closes_m: np.ndarray,
        target_m: np.ndarray,
        pos_arr: np.ndarray,
        sym_pnl_arr: np.ndarray,
        funding_m: np.ndarray,
        is_funding_bar: np.ndarray,
        equity_arr: np.ndarray,
        fee_arr: np.ndarray,
        turnover_arr: np.ndarray,
        contract_sizes: np.ndarray,
        leverages: np.ndarray,
        betas: np.ndarray,
        risk_vol: np.ndarray,
        mode: str,
        hedge_type: str,
        asset_type: str,
        maintenance_ratio: float,
        liquidated: bool,
        liquidation_bar: int,
    ) -> BacktestResultV2:
        equity = pd.Series(equity_arr, index=idx, name="equity")
        close_report = pd.DataFrame({s: closes_m[:, j] for j, s in enumerate(symbol_list)}, index=idx)
        target_units_report = pd.DataFrame({s: target_m[:, j] for j, s in enumerate(symbol_list)}, index=idx)
        accepted_units_report = pd.DataFrame({s: pos_arr[:, j] for j, s in enumerate(symbol_list)}, index=idx)
        cs = pd.Series({s: float(contract_sizes[j]) for j, s in enumerate(symbol_list)})
        lev = pd.Series({s: float(leverages[j]) for j, s in enumerate(symbol_list)})
        beta_s = pd.Series({s: float(betas[j]) for j, s in enumerate(symbol_list)})
        target_notional = target_units_report.mul(close_report, axis=0).mul(cs, axis=1)
        accepted_notional = accepted_units_report.mul(close_report, axis=0).mul(cs, axis=1)
        funding_rates = pd.DataFrame({s: funding_m[:, j] for j, s in enumerate(symbol_list)}, index=idx)
        risk_vol_report = pd.DataFrame({s: risk_vol[:, j] for j, s in enumerate(symbol_list)}, index=idx)

        exposure_report = self._build_exposure_report(
            accepted_notional=accepted_notional,
            target_notional=target_notional,
            equity=equity,
            leverages=lev,
            maintenance_ratio=maintenance_ratio,
            betas=beta_s,
        )
        risk_contribution_report = accepted_notional.abs().mul(risk_vol_report, axis=0)
        exposure_report.attrs["risk_contribution_report"] = risk_contribution_report
        symbol_pnl_report = self._build_symbol_pnl_report(
            idx=idx,
            symbols=symbol_list,
            accepted_units=accepted_units_report,
            closes=close_report,
            funding_rates=funding_rates,
            is_funding_bar=pd.Series(is_funding_bar, index=idx),
            contract_sizes=cs,
            fee_rate=float(self.config.fee_rate),
            fee_arr=fee_arr,
        )
        rebalance_report = self._build_rebalance_report(
            target_units=target_units_report,
            accepted_units=accepted_units_report,
            closes=close_report,
            contract_sizes=cs,
        )

        positions = pd.DataFrame({f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbol_list)}, index=idx)
        closes = pd.DataFrame({f"Close_{s}": closes_m[:, j] for j, s in enumerate(symbol_list)}, index=idx)
        fees = pd.Series(fee_arr, index=idx, name="fees")
        turnover = pd.Series(turnover_arr, index=idx, name="turnover")
        funding_cost = symbol_pnl_report.groupby("timestamp", sort=False)["funding_cost"].sum().reindex(idx, fill_value=0.0)
        margin = exposure_report[["initial_margin", "maintenance_margin"]].copy()
        diagnostics = pd.DataFrame(
            {
                "turnover": turnover,
                "rejected_rebalances": (target_units_report - accepted_units_report).abs().sum(axis=1) > 1e-10,
            },
            index=idx,
        )

        return BacktestResultV2(
            equity=equity,
            returns=equity.pct_change().fillna(0.0),
            positions=positions,
            closes=closes,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=liquidated,
            liquidation_bar=liquidation_bar,
            fees=fees,
            funding=pd.Series(funding_cost.to_numpy(dtype=float), index=idx, name="funding"),
            margin=margin,
            diagnostics=diagnostics,
            metadata={
                "backend": "native_portfolio",
                "mode": mode,
                "asset_type": asset_type,
                "hedge_type": hedge_type,
                "engine": "native_portfolio_v1",
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "funding_rate_unit": "per_event",
                "target_units_report": target_units_report,
                "accepted_units_report": accepted_units_report,
                "target_notional_report": target_notional,
                "accepted_notional_report": accepted_notional,
                "exposure_report": exposure_report,
                "risk_volatility_report": risk_vol_report,
                "risk_contribution_report": risk_contribution_report,
                "beta": {s: float(betas[j]) for j, s in enumerate(symbol_list)},
                "symbol_pnl_report": symbol_pnl_report,
                "kernel_symbol_pnl": pd.DataFrame({s: sym_pnl_arr[:, j] for j, s in enumerate(symbol_list)}, index=idx),
                "rebalance_report": rebalance_report,
                "fee_series": fees,
                "turnover_series": turnover,
                "fee_total": float(np.sum(fee_arr)),
                "turnover_total": float(np.sum(turnover_arr)),
                "fee_rate_oneway": float(self.config.fee_rate),
                "contract_size": {s: float(contract_sizes[j]) for j, s in enumerate(symbol_list)},
            },
        )

    @staticmethod
    def _build_symbol_pnl_report(
        *,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        accepted_units: pd.DataFrame,
        closes: pd.DataFrame,
        funding_rates: pd.DataFrame,
        is_funding_bar: pd.Series,
        contract_sizes: pd.Series,
        fee_rate: float,
        fee_arr: np.ndarray,
    ) -> pd.DataFrame:
        frames = []
        funding_mask = is_funding_bar.astype(bool)
        raw_trade_notional = {}
        total_trade_notional = pd.Series(0.0, index=idx)
        for symbol in symbols:
            units = accepted_units[symbol].astype(float)
            close = closes[symbol].astype(float)
            cs = float(contract_sizes[symbol])
            trade_notional = units.diff().fillna(units).abs() * close * cs
            raw_trade_notional[symbol] = trade_notional
            total_trade_notional = total_trade_notional.add(trade_notional, fill_value=0.0)
        fee_series = pd.Series(fee_arr, index=idx, dtype=float)
        for symbol in symbols:
            units = accepted_units[symbol].astype(float)
            close = closes[symbol].astype(float)
            prev_units = units.shift(1).fillna(0.0)
            prev_close = close.shift(1).fillna(close)
            cs = float(contract_sizes[symbol])
            mark_pnl = prev_units * (close - prev_close) * cs
            funding_cost = prev_units * close * cs * funding_rates[symbol].astype(float)
            funding_cost = funding_cost.where(funding_mask, 0.0)
            share = raw_trade_notional[symbol].divide(total_trade_notional.replace(0.0, np.nan)).fillna(0.0)
            fee = fee_series * share
            total_pnl = mark_pnl - funding_cost - fee
            frames.append(
                pd.DataFrame(
                    {
                        "timestamp": idx,
                        "symbol": symbol,
                        "position_units": units.to_numpy(dtype=float),
                        "close": close.to_numpy(dtype=float),
                        "mark_pnl": mark_pnl.to_numpy(dtype=float),
                        "funding_cost": funding_cost.to_numpy(dtype=float),
                        "funding_pnl": (-funding_cost).to_numpy(dtype=float),
                        "fee": fee.to_numpy(dtype=float),
                        "fee_pnl": (-fee).to_numpy(dtype=float),
                        "total_pnl": total_pnl.to_numpy(dtype=float),
                    }
                )
            )
        return pd.concat(frames, ignore_index=True, copy=False) if frames else pd.DataFrame()

    @staticmethod
    def _build_exposure_report(
        *,
        accepted_notional: pd.DataFrame,
        target_notional: pd.DataFrame,
        equity: pd.Series,
        leverages: pd.Series,
        maintenance_ratio: float,
        betas: pd.Series,
    ) -> pd.DataFrame:
        abs_accepted = accepted_notional.abs()
        initial_margin = abs_accepted.div(leverages, axis=1).sum(axis=1)
        maintenance_margin = abs_accepted.sum(axis=1) * float(maintenance_ratio)
        beta_exposure = accepted_notional.mul(betas, axis=1).sum(axis=1)
        target_beta_exposure = target_notional.mul(betas, axis=1).sum(axis=1)
        out = pd.DataFrame(
            {
                "long_notional": accepted_notional.clip(lower=0.0).sum(axis=1),
                "short_notional": accepted_notional.clip(upper=0.0).abs().sum(axis=1),
                "gross_notional": abs_accepted.sum(axis=1),
                "net_notional": accepted_notional.sum(axis=1),
                "beta_exposure_notional": beta_exposure,
                "target_gross_notional": target_notional.abs().sum(axis=1),
                "target_beta_exposure_notional": target_beta_exposure,
                "initial_margin": initial_margin,
                "maintenance_margin": maintenance_margin,
                "equity": equity,
                "available_equity_after_im": equity - initial_margin,
                "buying_power": equity * float(np.mean(leverages.to_numpy(dtype=float))),
            },
            index=equity.index,
        )
        out["gross_leverage"] = out["gross_notional"] / out["equity"].replace(0.0, np.nan)
        out["net_exposure_pct"] = out["net_notional"] / out["equity"].replace(0.0, np.nan)
        return out.fillna(0.0)

    @staticmethod
    def _build_rebalance_report(
        *,
        target_units: pd.DataFrame,
        accepted_units: pd.DataFrame,
        closes: pd.DataFrame,
        contract_sizes: pd.Series,
    ) -> pd.DataFrame:
        diff = target_units - accepted_units
        mask = diff.abs() > 1e-10
        if not mask.to_numpy().any():
            return pd.DataFrame(
                columns=["timestamp", "symbol", "target_units", "accepted_units", "unit_diff", "notional_diff", "reason"]
            )
        notional_diff = diff.mul(closes, axis=0).mul(contract_sizes, axis=1)
        stacked = diff.where(mask).stack(future_stack=True).dropna()
        index = stacked.index
        return pd.DataFrame(
            {
                "timestamp": index.get_level_values(0),
                "symbol": index.get_level_values(1),
                "target_units": target_units.stack(future_stack=True).reindex(index).to_numpy(dtype=float),
                "accepted_units": accepted_units.stack(future_stack=True).reindex(index).to_numpy(dtype=float),
                "unit_diff": stacked.to_numpy(dtype=float),
                "notional_diff": notional_diff.stack(future_stack=True).reindex(index).to_numpy(dtype=float),
                "reason": "margin_or_portfolio_gate",
            }
        )

    @staticmethod
    def _per_symbol_array(value, symbols: List[str], default: float) -> np.ndarray:
        if value is None:
            return np.full(len(symbols), float(default), dtype=np.float64)
        if isinstance(value, dict):
            return np.array([float(value.get(symbol, default)) for symbol in symbols], dtype=np.float64)
        return np.full(len(symbols), float(value), dtype=np.float64)

    @staticmethod
    def _risk_volatility_matrix(closes: np.ndarray, lookback: int) -> np.ndarray:
        frame = pd.DataFrame(closes)
        returns = np.log(frame).diff()
        vol = returns.rolling(max(2, int(lookback)), min_periods=2).std().bfill().ffill().fillna(1.0)
        arr = vol.to_numpy(dtype=np.float64)
        arr[~np.isfinite(arr)] = 1.0
        arr[arr <= 0.0] = 1.0
        return np.ascontiguousarray(arr, dtype=np.float64)

    @staticmethod
    def _sizing_mode_id(sizing_mode: str) -> int:
        mapping = {"%_equity": 0, "target_weight": 1, "gross_exposure": 2, "net_exposure": 3}
        return mapping[sizing_mode]

    @staticmethod
    def _portfolio_mode_id(mode: str) -> int:
        mapping = {
            "longshort": 0,
            "market_neutral": 1,
            "directional": 2,
            "equal_weight": 3,
            "risk_parity": 4,
            "beta_neutral": 5,
        }
        return mapping[mode]
