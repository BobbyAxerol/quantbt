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
from ..core.constraints import build_quantity_constraints, quantize_target_units_matrix
from ..core.portfolio import (
    NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES,
    PortfolioDomainSpec,
    normalize_portfolio_mode,
    normalize_portfolio_sizing_mode,
    validate_portfolio_result_contract,
)
from ..core.preprocessor import (
    PreparedMarketArrays,
    align_series,
    build_market_arrays,
    build_signal_matrix,
    market_data_signature,
    prepare_funding,
    validate_datetime,
)
from ..core.results import BacktestResultV2, BacktestScalarScoreResult
from ..core.schema import AccountConfig
from ..core.schema import ExecutionConfig, InstrumentSpec
from ..sizing.fast import scale_signal_notional_matrix


@dataclass(frozen=True)
class NativePortfolioConfig:
    account: AccountConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fee_rate: float = 0.0
    use_funding: bool = True
    report_level: str = "full"

    def __post_init__(self) -> None:
        if float(self.fee_rate) < 0.0:
            raise ValueError("fee_rate must be >= 0")
        object.__setattr__(self, "report_level", _normalize_report_level(self.report_level))


class NativePortfolioBackend:
    """
    Explicit native portfolio backend for multi-symbol position matrices.

    `fee_rate` is interpreted as a canonical one-way rate inside this backend.
    Legacy round-trip `fee` compatibility is handled only at facade boundaries.
    """

    def __init__(self, config: NativePortfolioConfig):
        self.config = config

    def run_signals(
        self,
        positions: Optional[Dict[str, pd.Series]],
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
        market_arrays: Optional[PreparedMarketArrays] = None,
        raw_signal_matrix: Optional[np.ndarray] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        report_level: Optional[str] = None,
        _scalar_score_trading_days: Optional[int] = None,
    ) -> Union[BacktestResultV2, BacktestScalarScoreResult]:
        idx = validate_datetime(datetime_index)
        if positions is None and raw_signal_matrix is None:
            raise ValueError("positions or raw_signal_matrix is required")
        position_keys = set(positions.keys()) if positions is not None else set()
        symbol_list = list(symbols) if symbols is not None else list(positions.keys() if positions is not None else closes.keys())
        if positions is not None and set(symbol_list) != position_keys:
            raise ValueError("symbols and positions must contain the same keys")
        if market_arrays is None and set(symbol_list) != set(closes.keys()):
            raise ValueError("symbols and closes must contain the same keys")

        portfolio_mode = normalize_portfolio_mode(mode)
        sizing_mode = normalize_portfolio_sizing_mode(hedge_type)
        if sizing_mode not in NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES:
            raise NotImplementedError(
                f"native_portfolio does not yet support equity-dependent sizing mode {hedge_type!r}"
            )

        if market_arrays is None:
            market = self.prepare_market_arrays(
                datetime_index=idx,
                closes=closes,
                highs=highs,
                lows=lows,
                funding_rate=funding_rate,
                symbols=symbol_list,
            )
        elif market_arrays.signature != market_data_signature(idx, symbol_list):
            raise ValueError("prepared market arrays do not match datetime_index/symbols")
        else:
            market = market_arrays

        if raw_signal_matrix is None:
            pos_dict = align_series(positions, symbol_list, idx, fill_val=0.0)
            raw_signals = build_signal_matrix(symbol_list, idx, pos_dict)
        else:
            raw_signals = np.ascontiguousarray(raw_signal_matrix, dtype=np.float64)
            if raw_signals.shape != market.closes.shape:
                raise ValueError("raw_signal_matrix shape does not match prepared market arrays")

        cs_arr = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        constraints = build_quantity_constraints(
            symbol_list,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        lev_arr = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        alloc_arr = self._per_symbol_array(alloc_per_trade, symbol_list, default=100_000.0)
        maint_ratio = self.config.account.maintenance_ratio if maintenance_ratio is None else float(maintenance_ratio)

        beta_arr = self._per_symbol_array(betas, symbol_list, default=1.0)
        tradable_mask = self._tradable_matrix(
            closes=closes,
            idx=idx,
            symbols=symbol_list,
            market=market,
            max_stale_bars=int(self.config.account.metadata.get("portfolio_max_stale_bars", 0)),
        )
        risk_vol = self._risk_volatility_matrix(market.closes, lookback=int(risk_lookback))
        inv_vol = np.divide(1.0, risk_vol, out=np.zeros_like(risk_vol), where=risk_vol > 0.0)
        equity_aware = sizing_mode in {"%_equity", "target_weight", "gross_exposure", "net_exposure"}
        slippage_rate = float(self.config.execution.slippage_rate)

        if equity_aware:
            (
                equity_arr,
                target_units,
                pos_arr,
                sym_pnl_arr,
                fee_arr,
                slippage_arr,
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
                slippage_rate=slippage_rate,
                contract_sizes=cs_arr,
                use_funding=bool(self.config.use_funding),
                allocs=alloc_arr,
                sizing_mode_id=self._sizing_mode_id(sizing_mode),
                portfolio_mode_id=self._portfolio_mode_id(portfolio_mode),
                use_pyramiding=bool(use_pyramiding),
                exposure_scalar=float(np.mean(alloc_arr)) if len(alloc_arr) else 1.0,
                beta=beta_arr,
                inv_vol=inv_vol,
                qty_steps=constraints.qty_step,
                min_qtys=constraints.min_qty,
                min_notionals=constraints.min_notional,
                tradable=tradable_mask,
            )
        else:
            target_units = self._scale_target_units(
                sizing_mode=sizing_mode,
                raw_signals=raw_signals,
                closes=market.closes,
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
            target_units = quantize_target_units_matrix(target_units, market.closes, cs_arr, constraints)

            (
                equity_arr,
                pos_arr,
                sym_pnl_arr,
                fee_arr,
                slippage_arr,
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
                slippage_rate=slippage_rate,
                contract_sizes=cs_arr,
                use_funding=bool(self.config.use_funding),
                tradable=tradable_mask,
            )

        if _scalar_score_trading_days is not None:
            from ..metrics.performance import compute_performance_metrics

            returns_arr = np.zeros_like(equity_arr, dtype=np.float64)
            if len(equity_arr) > 1:
                returns_arr[1:] = np.divide(
                    equity_arr[1:] - equity_arr[:-1],
                    equity_arr[:-1],
                    out=np.zeros(len(equity_arr) - 1, dtype=np.float64),
                    where=equity_arr[:-1] != 0.0,
                )
            metrics = compute_performance_metrics(
                timestamps=idx,
                equity=equity_arr,
                returns=returns_arr,
                positions=pos_arr,
                symbols=symbol_list,
                initial_capital=float(self.config.account.initial_capital),
                liquidated=bool(liq_flag),
                trading_days=int(_scalar_score_trading_days),
            )
            final_positions = (
                np.asarray(pos_arr[-1], dtype=np.float64).copy()
                if len(pos_arr)
                else np.zeros(len(symbol_list), dtype=np.float64)
            )
            return BacktestScalarScoreResult(
                final_equity=float(equity_arr[-1]),
                final_positions=final_positions,
                metrics=metrics,
                liquidated=bool(liq_flag),
                liquidation_bar=int(liq_idx),
                metadata={
                    "backend": "native_portfolio",
                    "score_scalar": True,
                    "score_pandas_materialized": False,
                    "trading_days": int(_scalar_score_trading_days),
                },
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
            slippage_arr=slippage_arr,
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
            quantity_constraints=constraints.as_dict(),
            tradable_mask=tradable_mask,
            report_level=self.config.report_level if report_level is None else report_level,
        )
        spec = PortfolioDomainSpec(mode=portfolio_mode, sizing_mode=sizing_mode)
        if result.metadata.get("report_level") == "minimal":
            result.metadata["portfolio_contract_report"] = {
                "status": "skipped",
                "passed": None,
                "reason": "report_level='minimal' omits heavy audit reports; rerun with report_level='full' for contract validation",
                "spec": {"mode": portfolio_mode, "sizing_mode": sizing_mode},
            }
        else:
            result.metadata["portfolio_contract_report"] = validate_portfolio_result_contract(result, spec, tolerance=1e-8)
        return result

    def score_signals(self, *, trading_days: int = 365, **kwargs) -> BacktestScalarScoreResult:
        """Run the portfolio accounting kernel and retain scalar metrics only."""
        result = self.run_signals(
            **kwargs,
            _scalar_score_trading_days=int(trading_days),
        )
        if not isinstance(result, BacktestScalarScoreResult):  # pragma: no cover - guarded above
            raise RuntimeError("native_portfolio scalar score unexpectedly materialized a public result")
        return result

    def prepare_market_arrays(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, Dict[str, float], pd.Series, None] = 0.0,
        symbols: Optional[Sequence[str]] = None,
    ) -> PreparedMarketArrays:
        """
        Normalize portfolio market data once for WFO/service loops.

        The returned object is immutable ndarray-backed market state with a
        datetime/symbol signature. `run_signals` rejects stale reuse against a
        different index or symbol order, avoiding identity-cache bugs.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols) if symbols is not None else list(closes.keys())
        close_dict = align_series(closes, symbol_list, idx)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
        return build_market_arrays(symbol_list, idx, close_dict, high_dict, low_dict, funding_dict)

    @staticmethod
    def prepare_signal_matrix(
        positions: Dict[str, pd.Series],
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        symbols: Sequence[str],
    ) -> np.ndarray:
        """
        Normalize a portfolio signal matrix once when replaying prepared data.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = list(symbols)
        if set(symbol_list) != set(positions.keys()):
            raise ValueError("symbols and positions must contain the same keys")
        pos_dict = align_series(positions, symbol_list, idx, fill_val=0.0)
        return build_signal_matrix(symbol_list, idx, pos_dict)

    @staticmethod
    def _scale_target_units(
        *,
        sizing_mode: str,
        raw_signals: np.ndarray,
        closes: np.ndarray,
        alloc_arr: np.ndarray,
        contract_sizes: np.ndarray,
        use_pyramiding: bool,
    ) -> np.ndarray:
        if sizing_mode in ("signal_notional", "signal"):
            return scale_signal_notional_matrix(raw_signals, closes, alloc_arr, use_pyramiding=use_pyramiding)

        sig = raw_signals if use_pyramiding else np.sign(raw_signals)
        denom = closes * contract_sizes.reshape(1, -1)

        if sizing_mode == "notional":
            notionals = sig * alloc_arr.reshape(1, -1)
            return np.ascontiguousarray(
                np.divide(notionals, denom, out=np.zeros_like(raw_signals, dtype=np.float64), where=denom != 0.0),
                dtype=np.float64,
            )

        if sizing_mode == "unit":
            first_denom = denom[0:1, :]
            scale = np.divide(
                alloc_arr.reshape(1, -1),
                first_denom,
                out=np.zeros((1, raw_signals.shape[1]), dtype=np.float64),
                where=first_denom != 0.0,
            )
            return np.ascontiguousarray(sig * scale, dtype=np.float64)

        if sizing_mode == "target_units":
            return np.ascontiguousarray(raw_signals, dtype=np.float64)

        if sizing_mode == "target_notional":
            return np.ascontiguousarray(
                np.divide(raw_signals, denom, out=np.zeros_like(raw_signals, dtype=np.float64), where=denom != 0.0),
                dtype=np.float64,
            )

        if sizing_mode == "fixed_notional":
            notionals = sig * alloc_arr.reshape(1, -1)
            return np.ascontiguousarray(
                np.divide(notionals, denom, out=np.zeros_like(raw_signals, dtype=np.float64), where=denom != 0.0),
                dtype=np.float64,
            )

        raise NotImplementedError(f"native_portfolio sizing mode {sizing_mode!r} is not vectorized")

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
            valid = (long_sum > 0.0) & (short_sum > 0.0)
            long_scale = np.divide(target, long_sum, out=np.zeros_like(target), where=valid)
            short_scale = np.divide(target, short_sum, out=np.zeros_like(target), where=valid)
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
            inv_vol = np.divide(1.0, risk_vol, out=np.zeros_like(risk_vol), where=risk_vol > 0.0)
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
        slippage_arr: np.ndarray,
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
        quantity_constraints: Dict[str, Dict[str, float]],
        tradable_mask: np.ndarray,
        report_level: str,
    ) -> BacktestResultV2:
        level = _normalize_report_level(report_level)
        equity = pd.Series(equity_arr, index=idx, name="equity")
        close_report = pd.DataFrame(closes_m, index=idx, columns=symbol_list, copy=False)
        target_units_report = pd.DataFrame(target_m, index=idx, columns=symbol_list, copy=False)
        accepted_units_report = pd.DataFrame(pos_arr, index=idx, columns=symbol_list, copy=False)
        cs = pd.Series({s: float(contract_sizes[j]) for j, s in enumerate(symbol_list)})
        lev = pd.Series({s: float(leverages[j]) for j, s in enumerate(symbol_list)})
        beta_s = pd.Series({s: float(betas[j]) for j, s in enumerate(symbol_list)})
        cs_row = contract_sizes.reshape(1, -1)
        target_notional_arr = target_m * closes_m * cs_row
        accepted_notional_arr = pos_arr * closes_m * cs_row
        target_notional = pd.DataFrame(target_notional_arr, index=idx, columns=symbol_list, copy=False)
        accepted_notional = pd.DataFrame(accepted_notional_arr, index=idx, columns=symbol_list, copy=False)

        positions = pd.DataFrame(pos_arr, index=idx, columns=[f"Position_{s}" for s in symbol_list], copy=False)
        closes = pd.DataFrame(closes_m, index=idx, columns=[f"Close_{s}" for s in symbol_list], copy=False)
        fees = pd.Series(fee_arr, index=idx, name="fees")
        slippage = pd.Series(slippage_arr, index=idx, name="slippage")
        turnover = pd.Series(turnover_arr, index=idx, name="turnover")
        prev_units = np.vstack([np.zeros((1, len(symbol_list)), dtype=np.float64), pos_arr[:-1]])
        funding_cost_arr = prev_units * closes_m * cs_row * funding_m
        funding_cost_arr = np.where(is_funding_bar.reshape(-1, 1).astype(bool), funding_cost_arr, 0.0).sum(axis=1)
        abs_accepted = np.abs(accepted_notional_arr)
        margin = pd.DataFrame(
            {
                "initial_margin": (abs_accepted / leverages.reshape(1, -1)).sum(axis=1),
                "maintenance_margin": abs_accepted.sum(axis=1) * float(maintenance_ratio),
            },
            index=idx,
        )
        diagnostics = pd.DataFrame(
            {
                "turnover": turnover_arr,
                "slippage": slippage_arr,
                "rejected_rebalances": np.abs(target_m - pos_arr).sum(axis=1) > 1e-10,
            },
            index=idx,
        )
        returns_arr = np.zeros_like(equity_arr, dtype=np.float64)
        if len(equity_arr) > 1:
            returns_arr[1:] = np.divide(
                equity_arr[1:] - equity_arr[:-1],
                equity_arr[:-1],
                out=np.zeros(len(equity_arr) - 1, dtype=np.float64),
                where=equity_arr[:-1] != 0.0,
            )

        metadata = {
            "backend": "native_portfolio",
            "mode": mode,
            "asset_type": asset_type,
            "hedge_type": hedge_type,
            "engine": "native_portfolio_v1",
            "report_level": level,
            "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
            "funding_rate_unit": "per_event",
            "target_units_report": target_units_report,
            "accepted_units_report": accepted_units_report,
            "beta": {s: float(betas[j]) for j, s in enumerate(symbol_list)},
            "fee_series": fees,
            "turnover_series": turnover,
            "slippage_series": slippage,
            "fee_total": float(np.sum(fee_arr)),
            "slippage_total": float(np.sum(slippage_arr)),
            "turnover_total": float(np.sum(turnover_arr)),
            "fee_rate_oneway": float(self.config.fee_rate),
            "canonical_one_way_fee_rate": float(self.config.fee_rate),
            "slippage_bps": float(self.config.execution.slippage_bps),
            "contract_size": {s: float(contract_sizes[j]) for j, s in enumerate(symbol_list)},
            "quantity_constraints": quantity_constraints,
        }
        omitted = []
        if level in {"full", "standard"}:
            funding_rates = pd.DataFrame(funding_m, index=idx, columns=symbol_list, copy=False)
            exposure_report = self._build_exposure_report(
                accepted_notional_arr=accepted_notional_arr,
                target_notional_arr=target_notional_arr,
                equity_arr=equity_arr,
                idx=idx,
                leverages=leverages,
                maintenance_ratio=maintenance_ratio,
                betas=betas,
            )
            symbol_pnl_report = self._build_symbol_pnl_report(
                idx=idx,
                symbols=symbol_list,
                accepted_units_arr=pos_arr,
                closes_arr=closes_m,
                funding_rates_arr=funding_m,
                is_funding_bar=is_funding_bar,
                contract_sizes=contract_sizes,
                fee_arr=fee_arr,
                slippage_arr=slippage_arr,
            )
            metadata.update(
                {
                    "target_notional_report": target_notional,
                    "accepted_notional_report": accepted_notional,
                    "exposure_report": exposure_report,
                    "funding_rates_report": funding_rates,
                    "symbol_pnl_report": symbol_pnl_report,
                }
            )
            if level == "full":
                risk_vol_report = pd.DataFrame(risk_vol, index=idx, columns=symbol_list, copy=False)
                risk_contribution_report = pd.DataFrame(np.abs(accepted_notional_arr) * risk_vol, index=idx, columns=symbol_list, copy=False)
                exposure_report.attrs["risk_contribution_report"] = risk_contribution_report
                rebalance_report = self._build_rebalance_report(
                    idx=idx,
                    symbols=symbol_list,
                    target_units_arr=target_m,
                    accepted_units_arr=pos_arr,
                    closes_arr=closes_m,
                    contract_sizes=contract_sizes,
                    tradable_mask=tradable_mask,
                    quantity_constraints=quantity_constraints,
                )
                reconciliation_report = self._build_reconciliation_report(
                    initial_capital=float(self.config.account.initial_capital),
                    equity_arr=equity_arr,
                    fee_arr=fee_arr,
                    slippage_arr=slippage_arr,
                    turnover_arr=turnover_arr,
                    positions=positions,
                    target_units_report=target_units_report,
                    accepted_units_report=accepted_units_report,
                    symbol_pnl_report=symbol_pnl_report,
                )
                metadata.update(
                    {
                        "risk_volatility_report": risk_vol_report,
                        "risk_contribution_report": risk_contribution_report,
                        "kernel_symbol_pnl": pd.DataFrame(sym_pnl_arr, index=idx, columns=symbol_list, copy=False),
                        "rebalance_report": rebalance_report,
                        "portfolio_reconciliation_report": reconciliation_report,
                    }
                )
            else:
                omitted.extend(["risk_volatility_report", "risk_contribution_report", "kernel_symbol_pnl", "rebalance_report", "portfolio_reconciliation_report"])
        else:
            omitted.extend(
                [
                    "target_notional_report",
                    "accepted_notional_report",
                    "exposure_report",
                    "funding_rates_report",
                    "risk_volatility_report",
                    "risk_contribution_report",
                    "symbol_pnl_report",
                    "kernel_symbol_pnl",
                    "rebalance_report",
                    "portfolio_reconciliation_report",
                ]
            )
        metadata["reports_omitted"] = tuple(omitted)

        return BacktestResultV2(
            equity=equity,
            returns=pd.Series(returns_arr, index=idx, name="returns"),
            positions=positions,
            closes=closes,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=liquidated,
            liquidation_bar=liquidation_bar,
            fees=fees,
            funding=pd.Series(funding_cost_arr, index=idx, name="funding"),
            margin=margin,
            diagnostics=diagnostics,
            metadata=metadata,
        )

    @staticmethod
    def _build_symbol_pnl_report(
        *,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        accepted_units_arr: np.ndarray,
        closes_arr: np.ndarray,
        funding_rates_arr: np.ndarray,
        is_funding_bar: np.ndarray,
        contract_sizes: np.ndarray,
        fee_arr: np.ndarray,
        slippage_arr: np.ndarray,
    ) -> pd.DataFrame:
        n_bars, n_syms = accepted_units_arr.shape
        if n_bars == 0 or n_syms == 0:
            return pd.DataFrame()
        prev_units = np.vstack([np.zeros((1, n_syms), dtype=np.float64), accepted_units_arr[:-1]])
        prev_close = np.vstack([closes_arr[0:1], closes_arr[:-1]])
        cs = contract_sizes.reshape(1, -1)
        mark_pnl = prev_units * (closes_arr - prev_close) * cs
        funding_cost = prev_units * closes_arr * cs * funding_rates_arr
        funding_cost = np.where(is_funding_bar.reshape(-1, 1).astype(bool), funding_cost, 0.0)
        trade_delta = np.abs(accepted_units_arr - prev_units)
        trade_notional = trade_delta * closes_arr * cs
        total_trade_notional = trade_notional.sum(axis=1, keepdims=True)
        share = np.divide(
            trade_notional,
            total_trade_notional,
            out=np.zeros_like(trade_notional),
            where=total_trade_notional != 0.0,
        )
        fee = fee_arr.reshape(-1, 1) * share
        slippage = slippage_arr.reshape(-1, 1) * share
        total_pnl = mark_pnl - funding_cost - fee - slippage

        return pd.DataFrame(
            {
                "timestamp": np.tile(np.asarray(idx, dtype=object), n_syms),
                "symbol": np.repeat(np.asarray(symbols, dtype=object), n_bars),
                "position_units": accepted_units_arr.T.reshape(-1),
                "close": closes_arr.T.reshape(-1),
                "mark_pnl": mark_pnl.T.reshape(-1),
                "funding_cost": funding_cost.T.reshape(-1),
                "funding_pnl": (-funding_cost).T.reshape(-1),
                "fee": fee.T.reshape(-1),
                "fee_pnl": (-fee).T.reshape(-1),
                "slippage_cost": slippage.T.reshape(-1),
                "slippage_pnl": (-slippage).T.reshape(-1),
                "total_pnl": total_pnl.T.reshape(-1),
            }
        )

    @staticmethod
    def _build_exposure_report(
        *,
        accepted_notional_arr: np.ndarray,
        target_notional_arr: np.ndarray,
        equity_arr: np.ndarray,
        idx: pd.DatetimeIndex,
        leverages: np.ndarray,
        maintenance_ratio: float,
        betas: np.ndarray,
    ) -> pd.DataFrame:
        abs_accepted = np.abs(accepted_notional_arr)
        gross = abs_accepted.sum(axis=1)
        net = accepted_notional_arr.sum(axis=1)
        initial_margin = (abs_accepted / leverages.reshape(1, -1)).sum(axis=1)
        maintenance_margin = gross * float(maintenance_ratio)
        beta_exposure = (accepted_notional_arr * betas.reshape(1, -1)).sum(axis=1)
        target_gross = np.abs(target_notional_arr).sum(axis=1)
        target_beta_exposure = (target_notional_arr * betas.reshape(1, -1)).sum(axis=1)
        mean_leverage = float(np.mean(leverages))
        gross_leverage = np.divide(gross, equity_arr, out=np.zeros_like(gross), where=equity_arr != 0.0)
        net_exposure_pct = np.divide(net, equity_arr, out=np.zeros_like(net), where=equity_arr != 0.0)
        return pd.DataFrame(
            {
                "long_notional": np.where(accepted_notional_arr > 0.0, accepted_notional_arr, 0.0).sum(axis=1),
                "short_notional": np.where(accepted_notional_arr < 0.0, -accepted_notional_arr, 0.0).sum(axis=1),
                "gross_notional": gross,
                "net_notional": net,
                "beta_exposure_notional": beta_exposure,
                "target_gross_notional": target_gross,
                "target_beta_exposure_notional": target_beta_exposure,
                "initial_margin": initial_margin,
                "maintenance_margin": maintenance_margin,
                "equity": equity_arr,
                "available_equity_after_im": equity_arr - initial_margin,
                "buying_power": equity_arr * mean_leverage,
                "gross_leverage": gross_leverage,
                "net_exposure_pct": net_exposure_pct,
            },
            index=idx,
        )

    @staticmethod
    def _build_rebalance_report(
        *,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        target_units_arr: np.ndarray,
        accepted_units_arr: np.ndarray,
        closes_arr: np.ndarray,
        contract_sizes: np.ndarray,
        tradable_mask: np.ndarray,
        quantity_constraints: Dict[str, Dict[str, float]],
    ) -> pd.DataFrame:
        diff = target_units_arr - accepted_units_arr
        row_idx, col_idx = np.nonzero(np.abs(diff) > 1e-10)
        if len(row_idx) == 0:
            return pd.DataFrame(
                columns=["timestamp", "symbol", "target_units", "accepted_units", "unit_diff", "notional_diff", "reason"]
            )
        unit_diff = diff[row_idx, col_idx]
        notional_diff = unit_diff * closes_arr[row_idx, col_idx] * contract_sizes[col_idx]
        symbol_arr = np.asarray(symbols, dtype=object)
        reasons = []
        for r, c in zip(row_idx, col_idx):
            symbol = symbols[int(c)]
            target = float(target_units_arr[r, c])
            close = float(closes_arr[r, c])
            cs = float(contract_sizes[c])
            constraints = quantity_constraints.get(symbol, {})
            min_qty = float(constraints.get("min_qty", 0.0) or 0.0)
            min_notional = float(constraints.get("min_notional", 0.0) or 0.0)
            abs_target = abs(target)
            notional = abs_target * close * cs if np.isfinite(close) else np.nan
            if not np.isfinite(target):
                reasons.append("INVALID_TARGET")
            elif not np.isfinite(close) or close <= 0.0:
                reasons.append("NON_TRADABLE")
            elif not bool(tradable_mask[r, c]):
                reasons.append("STALE_PRICE")
            elif min_qty > 0.0 and 0.0 < abs_target < min_qty:
                reasons.append("MIN_QTY")
            elif min_notional > 0.0 and np.isfinite(notional) and 0.0 < notional < min_notional:
                reasons.append("MIN_NOTIONAL")
            else:
                reasons.append("POST_COST_MARGIN")
        return pd.DataFrame(
            {
                "timestamp": idx.take(row_idx),
                "symbol": symbol_arr[col_idx],
                "target_units": target_units_arr[row_idx, col_idx],
                "accepted_units": accepted_units_arr[row_idx, col_idx],
                "unit_diff": unit_diff,
                "notional_diff": notional_diff,
                "reason": reasons,
            }
        )

    @staticmethod
    def _build_reconciliation_report(
        *,
        initial_capital: float,
        equity_arr: np.ndarray,
        fee_arr: np.ndarray,
        slippage_arr: np.ndarray,
        turnover_arr: np.ndarray,
        positions: pd.DataFrame,
        target_units_report: pd.DataFrame,
        accepted_units_report: pd.DataFrame,
        symbol_pnl_report: pd.DataFrame,
    ) -> Dict[str, float]:
        if symbol_pnl_report is None or symbol_pnl_report.empty:
            symbol_fee = 0.0
            symbol_slippage = 0.0
            symbol_pnl = 0.0
        else:
            symbol_fee = float(symbol_pnl_report["fee"].sum())
            symbol_slippage = float(symbol_pnl_report["slippage_cost"].sum())
            symbol_pnl = float(symbol_pnl_report["total_pnl"].sum())
        positions_values = positions.to_numpy(dtype=np.float64, copy=False)
        accepted_values = accepted_units_report.to_numpy(dtype=np.float64, copy=False)
        return {
            "fee_total": float(np.sum(fee_arr)),
            "symbol_fee_total": symbol_fee,
            "fee_diff": float(np.sum(fee_arr) - symbol_fee),
            "slippage_total": float(np.sum(slippage_arr)),
            "symbol_slippage_total": symbol_slippage,
            "slippage_diff": float(np.sum(slippage_arr) - symbol_slippage),
            "turnover_total": float(np.sum(turnover_arr)),
            "symbol_total_pnl": symbol_pnl,
            "equity_pnl": float(equity_arr[-1] - initial_capital) if len(equity_arr) else 0.0,
            "equity_symbol_pnl_diff": float((equity_arr[-1] - initial_capital) - symbol_pnl) if len(equity_arr) else 0.0,
            "max_result_position_diff": float(np.nanmax(np.abs(positions_values - accepted_values))) if positions_values.size else 0.0,
            "max_target_accepted_diff": float(np.nanmax(np.abs(target_units_report.to_numpy(dtype=np.float64, copy=False) - accepted_values))) if accepted_values.size else 0.0,
        }

    @staticmethod
    def _per_symbol_array(value, symbols: List[str], default: float) -> np.ndarray:
        if value is None:
            return np.full(len(symbols), float(default), dtype=np.float64)
        if isinstance(value, dict):
            return np.array([float(value.get(symbol, default)) for symbol in symbols], dtype=np.float64)
        return np.full(len(symbols), float(value), dtype=np.float64)

    @staticmethod
    def _risk_volatility_matrix(closes: np.ndarray, lookback: int) -> np.ndarray:
        frame = pd.DataFrame(closes).where(lambda x: x > 0.0)
        returns = np.log(frame).diff()
        window = max(2, int(lookback))
        vol = returns.rolling(window, min_periods=window).std()
        arr = vol.to_numpy(dtype=np.float64)
        arr[~np.isfinite(arr)] = 0.0
        arr[arr <= 0.0] = 0.0
        return np.ascontiguousarray(arr, dtype=np.float64)

    @staticmethod
    def _tradable_matrix(
        *,
        closes: Dict[str, pd.Series],
        idx: pd.DatetimeIndex,
        symbols: Sequence[str],
        market: PreparedMarketArrays,
        max_stale_bars: int = 0,
    ) -> np.ndarray:
        out = np.isfinite(market.closes) & (market.closes > 0.0)
        if closes is None:
            return np.ascontiguousarray(out, dtype=np.bool_)
        max_stale = max(0, int(max_stale_bars))
        for j, symbol in enumerate(symbols):
            raw = closes[symbol]
            if not isinstance(raw, pd.Series):
                raw = pd.Series(raw, index=idx)
            raw_idx = raw.index
            if isinstance(raw_idx, pd.DatetimeIndex):
                if raw_idx.tz is None:
                    raw = raw.copy()
                    raw.index = raw.index.tz_localize("UTC")
                else:
                    raw = raw.copy()
                    raw.index = raw.index.tz_convert("UTC")
            observed = raw[~raw.index.duplicated(keep="first")].reindex(idx)
            values = observed.to_numpy(dtype=np.float64)
            stale = max_stale + 1
            for i in range(len(idx)):
                if np.isfinite(values[i]) and values[i] > 0.0:
                    stale = 0
                else:
                    stale += 1
                out[i, j] = bool(out[i, j] and stale <= max_stale)
        return np.ascontiguousarray(out, dtype=np.bool_)

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


def _normalize_report_level(report_level: str) -> str:
    level = str(report_level or "full").lower().strip()
    aliases = {
        "audit": "full",
        "complete": "full",
        "default": "full",
        "lite": "standard",
        "light": "minimal",
        "optimizer": "minimal",
        "scoring": "minimal",
    }
    level = aliases.get(level, level)
    if level not in {"full", "standard", "minimal"}:
        raise ValueError("report_level must be one of 'full', 'standard', or 'minimal'")
    return level
