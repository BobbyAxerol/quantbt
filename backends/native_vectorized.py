"""
quantbt.backends.native_vectorized
----------------------------------
V2 backend facade over Numba vectorized kernels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from ..core.preprocessor import align_series, build_arrays, prepare_funding, validate_datetime
from ..core.results import BacktestResultV2
from ..core.schema import AccountConfig, ExecutionConfig
from ..core.vectorized import _engine_units_v2
from ..sizing.modes import compute_target_units


@dataclass(frozen=True)
class NativeVectorizedConfig:
    account: AccountConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fee_rate: float = 0.0
    use_funding: bool = True

    def __post_init__(self) -> None:
        if self.fee_rate < 0.0:
            raise ValueError("fee_rate must be >= 0")


class NativeVectorizedBackend:
    """
    Fast vectorized backend returning BacktestResultV2 diagnostics.

    This initial Phase 2 backend consumes pre-scaled target units. Sizing modes
    remain in the existing public wrappers and will be migrated onto this backend
    incrementally.
    """

    def __init__(self, config: NativeVectorizedConfig):
        self.config = config

    def run_target_units(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        target_units: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
    ) -> BacktestResultV2:
        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(target_units.keys())
        if set(symbol_list) != set(target_units.keys()) or set(symbol_list) != set(closes.keys()):
            raise ValueError("symbols, target_units, and closes must contain the same keys")

        close_dict = align_series(closes, symbol_list, idx)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        target_dict = align_series(target_units, symbol_list, idx, fill_val=0.0)
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)

        closes_m, highs_m, lows_m, target_m, funding_m, is_funding = build_arrays(
            symbols=symbol_list,
            idx=idx,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            signals_dict=target_dict,
            funding_dict=funding_dict,
        )

        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        leverages = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )

        (
            equity_arr,
            pos_arr,
            fee_arr,
            turnover_arr,
            funding_arr,
            init_margin_arr,
            maint_margin_arr,
            rejected_arr,
            reject_code_arr,
            liq_flag,
            liq_idx,
            liq_reason,
        ) = _engine_units_v2(
            n_bars=len(idx),
            n_syms=len(symbol_list),
            highs=highs_m,
            lows=lows_m,
            closes=closes_m,
            target_units=target_m,
            funding_rates=funding_m,
            is_funding_bar=is_funding,
            init_capital=self.config.account.initial_capital,
            leverages=leverages,
            maint_ratio=self.config.account.maintenance_ratio,
            fee_rate=self.config.fee_rate,
            contract_sizes=contract_sizes,
            slippage=self.config.execution.slippage_rate,
            use_funding=bool(self.config.use_funding),
        )

        equity = pd.Series(equity_arr, index=idx, name="equity")
        returns = equity.pct_change().fillna(0.0)
        positions = pd.DataFrame(
            {f"Position_{s}": pos_arr[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        close_df = pd.DataFrame(
            {f"Close_{s}": closes_m[:, j] for j, s in enumerate(symbol_list)},
            index=idx,
        )
        fees = pd.Series(fee_arr, index=idx, name="fees")
        funding = pd.Series(funding_arr, index=idx, name="funding")
        margin = pd.DataFrame(
            {
                "initial_margin": init_margin_arr,
                "maintenance_margin": maint_margin_arr,
            },
            index=idx,
        )
        diagnostics = pd.DataFrame(
            {
                "turnover": turnover_arr,
                "rejected_orders": rejected_arr,
                "reject_code": reject_code_arr,
            },
            index=idx,
        )

        return BacktestResultV2(
            equity=equity,
            returns=returns,
            positions=positions,
            closes=close_df,
            symbols=symbol_list,
            initial_capital=self.config.account.initial_capital,
            leverage=float(np.mean(leverages)),
            liquidated=bool(liq_flag),
            liquidation_bar=int(liq_idx),
            fees=fees,
            funding=funding,
            margin=margin,
            diagnostics=diagnostics,
            metadata={
                "backend": "native_vectorized",
                "engine": "units_v2",
                "fee_rate_oneway": self.config.fee_rate,
                "slippage_bps": self.config.execution.slippage_bps,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
            },
        )

    def run_signals(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        positions: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        alloc_per_trade: Union[float, Dict[str, float]] = 100_000.0,
        hedge_type: str = "signal_notional",
        use_pyramiding: bool = True,
        symbols: Optional[List[str]] = None,
    ) -> BacktestResultV2:
        """
        Scale raw position signals into target units, then run the V2 kernel.

        Phase 2 supports target-unit sizing modes here. `%_equity` and
        `dca_ladder` remain on the legacy kernels until their V2 diagnostics
        kernels are added.
        """
        ht = hedge_type.lower().strip()
        if ht in ("%_equity", "pct_equity", "dca_ladder", "dca"):
            raise NotImplementedError(f"NativeVectorizedBackend.run_signals does not yet support hedge_type={hedge_type!r}")

        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(positions.keys())
        pos_dict = align_series(positions, symbol_list, idx, fill_val=0.0)
        close_dict = align_series(closes, symbol_list, idx)
        alloc = self._per_symbol_mapping(alloc_per_trade, symbol_list, default=100_000.0)

        target_units = {
            s: compute_target_units(
                hedge_type=hedge_type,
                signal=pos_dict[s],
                close=close_dict[s],
                alloc=alloc[s],
                use_pyramiding=use_pyramiding,
            )
            for s in symbol_list
        }

        return self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=funding_rate,
            contract_size=contract_size,
            leverage=leverage,
            symbols=symbol_list,
        )

    @staticmethod
    def _per_symbol_array(value, symbols: List[str], default: float) -> np.ndarray:
        if isinstance(value, dict):
            return np.array([float(value.get(s, default)) for s in symbols], dtype=np.float64)
        return np.full(len(symbols), float(value), dtype=np.float64)

    @staticmethod
    def _per_symbol_mapping(value, symbols: List[str], default: float) -> Dict[str, float]:
        if isinstance(value, dict):
            return {s: float(value.get(s, default)) for s in symbols}
        return {s: float(value) for s in symbols}
