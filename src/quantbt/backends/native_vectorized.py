"""
quantbt.backends.native_vectorized
----------------------------------
V2 backend facade over Numba vectorized kernels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from typing import Any, Dict, List, Optional, Union
import warnings

import numpy as np
import pandas as pd

from ..core.preprocessor import (
    PreparedMarketArrays,
    align_series,
    build_arrays,
    build_market_arrays,
    build_signal_matrix,
    market_data_signature,
    prepare_funding,
    validate_datetime,
)
from ..core.constraints import build_quantity_constraints, quantize_target_units_matrix
from ..core.results import BacktestResultV2, BacktestScalarScoreResult
from ..core.schema import (
    AccountConfig,
    BasketLegSpec,
    BasketSpec,
    ExecutionConfig,
    FillPricePolicy,
    InstrumentSpec,
    SameBarPolicy,
)
from ..core.vectorized import _engine_units_v2
from ..core.arbitrage import (
    ArbitrageSpec,
    ArbitragePlan,
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    CrossExchangeArbSpec,
    FundingArbitrageSpec,
    IndexBasketArbSpec,
    OptionsVolArbSpec,
    PackageExecutionKind,
    PackageRejection,
    SizingPolicyKind,
    SpotPerpCashCarrySpec,
    StatArbPairSpec,
    TriangularArbSpec,
    build_arbitrage_order_plan,
)
from ..core.basket import build_frozen_basket_orders
from ..core.orders import OrderIntent
from ..core.preprocessor import make_funding_mask
from ..core.schema import OrderSide
from ..core.target_intents import StaticDcaTargetStepV1, StaticTargetTapeV1, compile_static_dca_target_tape
from ..preparation.native_execution import NativeExecutionPreparationCache
from ..sizing.fast import scale_signal_notional_matrix
from ..sizing.modes import compute_target_units


@dataclass(frozen=True)
class NativeVectorizedConfig:
    account: AccountConfig
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    fee_rate: Union[float, Dict[str, float]] = 0.0
    use_funding: bool = True
    # Explicit Rust promotion for the close_target_v2 direct-target route.
    # ``auto`` intentionally remains Numba until target-score/WFO promotion
    # receives a separate compatibility lock; old endpoints stay unchanged.
    target_runtime: str = "numba"

    def __post_init__(self) -> None:
        if isinstance(self.fee_rate, dict):
            if any(float(rate) < 0.0 for rate in self.fee_rate.values()):
                raise ValueError("fee_rate must be >= 0")
        elif float(self.fee_rate) < 0.0:
            raise ValueError("fee_rate must be >= 0")
        unsupported = []
        if self.execution.fill_price_policy is not FillPricePolicy.CLOSE:
            unsupported.append(f"fill_price_policy={self.execution.fill_price_policy.value!r}")
        if self.execution.same_bar_policy is not SameBarPolicy.CONSERVATIVE:
            unsupported.append(f"same_bar_policy={self.execution.same_bar_policy.value!r}")
        if self.execution.allow_partial_fill:
            unsupported.append("allow_partial_fill=True")
        if self.execution.min_order_notional > 0.0:
            unsupported.append("min_order_notional")
        if not self.execution.reject_on_insufficient_margin:
            unsupported.append("reject_on_insufficient_margin=False")
        if unsupported:
            raise NotImplementedError(
                "native_vectorized is the close_target_v2 contract and does not support "
                + ", ".join(unsupported)
            )
        runtime = str(self.target_runtime).strip().lower()
        if runtime not in {"numba", "rust", "auto"}:
            raise ValueError("target_runtime must be 'numba', 'rust', or 'auto'")
        object.__setattr__(self, "target_runtime", runtime)


class NativeVectorizedBackend:
    """
    Fast vectorized backend returning BacktestResultV2 diagnostics.

    This initial Phase 2 backend consumes pre-scaled target units. Sizing modes
    remain in the existing public wrappers and will be migrated onto this backend
    incrementally.
    """

    def __init__(self, config: NativeVectorizedConfig):
        self.config = config
        self._rust_target_preparation: Optional[NativeExecutionPreparationCache] = None

    def _use_rust_target_runtime(self, target_kind: str = "units") -> bool:
        """Resolve the direct-target runtime without implicit fallback.

        ``auto`` deliberately remains on the established Numba route during
        Phase 66. An explicit ``rust`` request either runs the direct target
        kernel or raises a capability error; it never quietly changes backends.
        """

        if self.config.target_runtime != "rust":
            return False
        try:
            native = importlib.import_module("_quantbt_native")
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "target_runtime='rust' requires an installed compatible quantbt-native wheel"
            ) from exc
        if not hasattr(native, "NativeTargetExecutionRequestCore"):
            raise RuntimeError(
                "installed quantbt-native wheel does not support direct close-target execution"
            )
        from ._native_event_rust import probe_native_event_rust_extension

        status = probe_native_event_rust_extension(module=native)
        required_capability = {
            "units": "rust_direct_target_units_v1",
            "notional": "rust_direct_target_notional_v1",
            "weight": "rust_direct_target_weight_v1",
            "equity_fraction": "rust_direct_target_equity_fraction_v1",
            "pct_equity_transition": "rust_direct_target_pct_equity_transition_v1",
        }.get(str(target_kind).strip().lower())
        required = ("rust_direct_target_v1", required_capability)
        missing = [name for name in required if name and not status.capabilities.get(name, False)]
        if not status.available or not status.compatible or missing:
            detail = ", ".join(missing) if missing else str(status.reason or "descriptor mismatch")
            raise RuntimeError(
                "installed quantbt-native wheel lacks a compatible direct target capability: " + detail
            )
        return True

    def _rust_target_payload(
        self,
        *,
        idx: pd.DatetimeIndex,
        symbol_list: List[str],
        closes_m: np.ndarray,
        highs_m: np.ndarray,
        lows_m: np.ndarray,
        target_m: np.ndarray,
        funding_m: np.ndarray,
        is_funding: np.ndarray,
        contract_sizes: np.ndarray,
        leverages: np.ndarray,
        fee_rates: np.ndarray,
        constraints,
        target_kind: str,
        equity_fraction: np.ndarray,
        output_profile: int,
    ) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        """Run one prepared Rust direct-target pass without a legacy dict hop.

        The close-target contract does not consume open or volume. They are
        still supplied to the canonical Rust market owner as deterministic
        close/zero placeholders so the prepared signature remains complete.
        """

        if self._rust_target_preparation is None:
            self._rust_target_preparation = NativeExecutionPreparationCache()
        cache = self._rust_target_preparation
        closes_array = np.ascontiguousarray(closes_m, dtype=np.float64)
        highs_array = np.ascontiguousarray(highs_m, dtype=np.float64)
        lows_array = np.ascontiguousarray(lows_m, dtype=np.float64)
        funding_array = np.ascontiguousarray(funding_m, dtype=np.float64)
        target_array = np.ascontiguousarray(target_m, dtype=np.float64)
        timestamps = np.ascontiguousarray(idx.view("int64"), dtype=np.int64)
        market = cache.prepare_market(
            timestamps_ns=timestamps,
            opens=closes_array,
            highs=highs_array,
            lows=lows_array,
            closes=closes_array,
            volumes=np.zeros_like(closes_array),
            funding=funding_array,
            funding_mask=np.ascontiguousarray(is_funding, dtype=np.bool_),
            symbols=symbol_list,
        )
        # The direct target request has its own frozen timing identifier. The
        # template event code remains a compatibility/provenance field only;
        # no FullSession/event lifecycle is instantiated by this route.
        template = cache.prepare_template(
            market,
            contract_sizes=np.ascontiguousarray(contract_sizes, dtype=np.float64),
            leverages=np.ascontiguousarray(leverages, dtype=np.float64),
            fee_rates=np.ascontiguousarray(fee_rates, dtype=np.float64),
            initial_capital=float(self.config.account.initial_capital),
            maintenance_ratio=float(self.config.account.maintenance_ratio),
            slippage_rate=float(self.config.execution.slippage_rate),
            use_funding=bool(self.config.use_funding),
            event_contract_code=2,
        )
        request = cache.direct_target_request(
            template,
            targets=target_array,
            target_kind=target_kind,
            timing="close_target_v2_same_close",
            invalid_target_policy="reject_run",
            qty_step=np.ascontiguousarray(constraints.qty_step, dtype=np.float64),
            min_qty=np.ascontiguousarray(constraints.min_qty, dtype=np.float64),
            min_notional=np.ascontiguousarray(constraints.min_notional, dtype=np.float64),
            equity_fraction=np.ascontiguousarray(equity_fraction, dtype=np.float64),
            output_profile=int(output_profile),
        )
        typed_output = request.core.execute_typed()
        execution_metadata = self._rust_target_execution_metadata(
            typed_output,
            target_kind=target_kind,
            request_bytes=int(request.request_bytes),
            constraints=constraints,
        )
        return typed_output, execution_metadata, dict(cache.diagnostics)

    @staticmethod
    def _rust_target_execution_metadata(
        typed_output: Any,
        *,
        target_kind: str,
        request_bytes: int,
        constraints: Any,
    ) -> dict[str, Any]:
        """Adapt scalar provenance only; retain Rust SoA buffers untouched.

        ``NativeCompactOutputV1.as_dict()`` is a compatibility adapter.  The
        public close-target result already needs a handful of arrays and a
        small metadata mapping, so converting the entire typed result into a
        second Python mapping is unnecessary allocation and RSS pressure.
        """

        intent_kind = {
            "units": "target_units_v1",
            "notional": "target_notional_v1",
            "weight": "target_weight_v1",
            "equity_fraction": "equity_fraction_v1",
            "pct_equity_transition": "pct_equity_transition_v1",
        }[target_kind]
        unconstrained_units = bool(
            target_kind == "units"
            and np.all(np.asarray(constraints.qty_step, dtype=np.float64) == 0.0)
            and np.all(np.asarray(constraints.min_qty, dtype=np.float64) == 0.0)
            and np.all(np.asarray(constraints.min_notional, dtype=np.float64) == 0.0)
        )
        metrics = dict(getattr(typed_output, "metrics", {}))
        return {
            "native_direct_target": True,
            "native_target_no_order_arena": True,
            "native_target_specialization": (
                "units_unconstrained_delta_skip_v1" if unconstrained_units else "general_target_resolution_v1"
            ),
            "direct_target_kind": intent_kind,
            "direct_target_timing": "close_target_v2_same_close",
            "direct_target_invalid_target_policy": "reject_run",
            "native_target_request_bytes": int(request_bytes),
            "native_result_version": int(typed_output.native_result_version),
            "native_execution_account_authority": str(typed_output.account_authority),
            "native_execution_buffer_transfer": "rust_vec_to_numpy_zero_copy",
            "native_execution_command_count": int(typed_output.command_count),
            "native_execution_contract_bundle_hash": str(typed_output.contract_bundle_hash),
            "native_execution_detail_truncated": bool(typed_output.detail_truncated),
            "native_execution_dropped_rows": int(typed_output.dropped_rows),
            "native_execution_generation": int(typed_output.execution_generation),
            "native_execution_model_id": str(typed_output.execution_model_id),
            "native_execution_output_bytes": int(typed_output.output_bytes),
            "native_execution_output_profile": str(typed_output.output_profile),
            "native_execution_output_version": int(typed_output.output_version),
            "native_execution_passes": 1,
            "native_execution_protocol_version": int(typed_output.protocol_version),
            "native_execution_request_fingerprint": str(typed_output.fingerprint),
            "native_execution_request_version": int(typed_output.request_version),
            "native_execution_retained_rows": int(typed_output.retained_rows),
            "native_execution_runner_run_count": int(typed_output.runner_run_count),
            "native_execution_runtime_class": str(typed_output.runtime_class),
            "native_execution_template_fingerprint": str(typed_output.template_fingerprint),
            "native_execution_terminal_fingerprint": str(typed_output.terminal_fingerprint),
            "native_execution_workload": str(typed_output.workload_kind),
            "python_callbacks": 0,
            "boundary_calls": 1,
            **metrics,
        }

    @staticmethod
    def _close_target_metadata(
        *,
        symbol_list: List[str],
        idx: pd.DatetimeIndex,
        high_low_source: str,
        first_bar_policy: str,
    ) -> Dict:
        signature = market_data_signature(idx, symbol_list)
        return {
            "backend": "native_vectorized",
            "backend_alias": "native_vectorized",
            "engine": "close_target_v2",
            "engine_id": "close_target_v2",
            "kernel_version": "units_v2",
            "execution_contract": {
                "engine_id": "close_target_v2",
                "signal_phase": "bar_close",
                "fill_phase": "same_close",
                "intrabar_exit_model": "none",
                "market_fill_policy": "close",
                "timeline": "mark close[t-1]->close[t], rebalance target at close[t]",
                "accounting_certified": True,
                "execution_generated_by_engine": True,
            },
            "signal_phase": "bar_close",
            "fill_phase": "same_close",
            "intrabar_exit_model": "none",
            "first_bar_target_policy": first_bar_policy,
            "high_low_source": high_low_source,
            "data_signature": signature,
        }

    @staticmethod
    def _high_low_source(highs, lows) -> str:
        if highs is None and lows is None:
            return "close_fallback_uncertified_intrabar_risk"
        if highs is None:
            return "high_close_fallback_uncertified_intrabar_risk"
        if lows is None:
            return "low_close_fallback_uncertified_intrabar_risk"
        return "provided"

    @staticmethod
    def _warn_high_low_fallback(high_low_source: str) -> None:
        if high_low_source != "provided":
            warnings.warn(
                "native_vectorized close_target_v2 received missing high/low data and will use close fallback; "
                "intrabar liquidation/risk is uncertified for this run. Pass explicit highs/lows for certified risk.",
                RuntimeWarning,
                stacklevel=3,
            )

    def prepare_market_arrays(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        symbols: Optional[List[str]] = None,
    ) -> PreparedMarketArrays:
        """
        Normalize single-symbol or multi-symbol market data once for repeated
        signal-notional scoring loops.

        The prepared object is a copied ndarray snapshot plus an explicit
        datetime/symbol signature. `run_signals` rejects it when reused against
        a different index or symbol layout.
        """
        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(closes.keys())
        close_dict = align_series(closes, symbol_list, idx)
        high_low_source = self._high_low_source(highs, lows)
        self._warn_high_low_fallback(high_low_source)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
        market = build_market_arrays(
            symbols=symbol_list,
            idx=idx,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            funding_dict=funding_dict,
        )
        return market

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
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        symbols: Optional[List[str]] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        _target_kind: str = "units",
        _equity_fraction: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        idx = validate_datetime(datetime_index)
        symbol_list = symbols or list(target_units.keys())
        if set(symbol_list) != set(target_units.keys()) or set(symbol_list) != set(closes.keys()):
            raise ValueError("symbols, target_units, and closes must contain the same keys")

        target_kind = str(_target_kind).strip().lower()
        if target_kind not in {"units", "notional", "weight", "equity_fraction", "pct_equity_transition"}:
            raise ValueError(
                "_target_kind must be units, notional, weight, equity_fraction, or pct_equity_transition"
            )
        rust_target_requested = self.config.target_runtime == "rust"
        if target_kind != "units" and not rust_target_requested:
            raise NotImplementedError(
                f"native_vectorized {target_kind!r} targets require target_runtime='rust'; "
                "Numba remains the frozen target-units compatibility route"
            )

        close_dict = align_series(closes, symbol_list, idx)
        high_low_source = self._high_low_source(highs, lows)
        self._warn_high_low_fallback(high_low_source)
        high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
        low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
        target_dict = align_series(
            target_units,
            symbol_list,
            idx,
            fill_val=np.nan if rust_target_requested else 0.0,
        )
        funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)

        closes_m, highs_m, lows_m, target_m, funding_m, is_funding = build_arrays(
            symbols=symbol_list,
            idx=idx,
            closes_dict=close_dict,
            highs_dict=high_dict,
            lows_dict=low_dict,
            signals_dict=target_dict,
            funding_dict=funding_dict,
            preserve_signal_nan=rust_target_requested,
        )

        return self._run_target_arrays(
            idx=idx,
            symbol_list=symbol_list,
            closes_m=closes_m,
            highs_m=highs_m,
            lows_m=lows_m,
            target_m=target_m,
            funding_m=funding_m,
            is_funding=is_funding,
            contract_size=contract_size,
            leverage=leverage,
            fee_rate=fee_rate,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
            high_low_source=high_low_source,
            _target_kind=_target_kind,
            _equity_fraction=_equity_fraction,
        )

    def run_target_notionals(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        target_notionals: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        **kwargs,
    ) -> BacktestResultV2:
        """Run signed quote-notional targets through explicit Rust authority.

        Each matrix value is quote-currency notional at the same-close price
        before quantity constraints. This target contract is intentionally not
        lowered to the historical Numba units engine.
        """

        return self.run_target_units(
            datetime_index=datetime_index,
            target_units=target_notionals,
            closes=closes,
            _target_kind="notional",
            **kwargs,
        )

    def run_target_weights(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        target_weights: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        **kwargs,
    ) -> BacktestResultV2:
        """Run signed targets as fractions of pre-rebalance close equity.

        All symbols use the same immutable equity snapshot for a bar. Leverage
        changes buying power/margin only and never multiplies a target weight.
        """

        return self.run_target_units(
            datetime_index=datetime_index,
            target_units=target_weights,
            closes=closes,
            _target_kind="weight",
            **kwargs,
        )

    def run_equity_fraction_targets(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        target_fractions: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        *,
        equity_fraction: Union[float, Dict[str, float]],
        **kwargs,
    ) -> BacktestResultV2:
        """Run target fractions with an explicit per-symbol capital cap.

        Unlike weight targets, the raw matrix is multiplied by the separately
        declared ``equity_fraction`` before conversion to units. No implicit
        leverage multiplier is applied.
        """

        return self.run_target_units(
            datetime_index=datetime_index,
            target_units=target_fractions,
            closes=closes,
            _target_kind="equity_fraction",
            _equity_fraction=equity_fraction,
            **kwargs,
        )

    def run_pct_equity_transition_targets(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        target_weights: Dict[str, pd.Series],
        closes: Dict[str, pd.Series],
        *,
        equity_fraction: Union[float, Dict[str, float]],
        **kwargs,
    ) -> BacktestResultV2:
        """Run the legacy `%_equity` transition-sized target contract.

        A weight is converted to units only when its processed value changes.
        It is therefore intentionally distinct from
        :meth:`run_equity_fraction_targets`, which rebalances each bar.
        Rust authority is explicit via ``target_runtime='rust'``.
        """

        return self.run_target_units(
            datetime_index=datetime_index,
            target_units=target_weights,
            closes=closes,
            _target_kind="pct_equity_transition",
            _equity_fraction=equity_fraction,
            **kwargs,
        )

    def run_static_dca_schedule(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        *,
        symbol: str,
        closes: pd.Series,
        schedule: Union[
            Dict[object, float],
            pd.Series,
            List[StaticDcaTargetStepV1],
            List[tuple[object, float]],
        ],
        initial_target_units: float = 0.0,
        **kwargs,
    ) -> BacktestResultV2:
        """Execute a predeclared DCA schedule as a typed close-target tape.

        This is intentionally limited to absolute targets known before the
        run. It does not lower price-triggered safety orders or fill-driven
        ladder state into a static matrix; use ``event_driven`` for reactive
        grid/DCA strategies.
        """

        tape: StaticTargetTapeV1 = compile_static_dca_target_tape(
            validate_datetime(datetime_index),
            schedule,
            initial_target_units=initial_target_units,
        )
        declared_symbols = kwargs.pop("symbols", None)
        if declared_symbols is not None and list(declared_symbols) != [str(symbol)]:
            raise ValueError("run_static_dca_schedule supports exactly its declared single symbol")
        result = self.run_target_units(
            datetime_index=datetime_index,
            target_units={str(symbol): tape.target_units},
            closes={str(symbol): closes},
            symbols=[str(symbol)],
            **kwargs,
        )
        result.metadata.update({"static_target_tape": tape.metadata()})
        return result

    def _run_target_arrays(
        self,
        idx: pd.DatetimeIndex,
        symbol_list: List[str],
        closes_m: np.ndarray,
        highs_m: np.ndarray,
        lows_m: np.ndarray,
        target_m: np.ndarray,
        funding_m: np.ndarray,
        is_funding: np.ndarray,
        contract_size: Union[float, Dict[str, float]] = 1.0,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        fee_rate: Optional[Union[float, Dict[str, float]]] = None,
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
        raw_signal_matrix: Optional[np.ndarray] = None,
        high_low_source: str = "provided",
        _scalar_score_trading_days: Optional[int] = None,
        _target_kind: str = "units",
        _equity_fraction: Optional[Union[float, Dict[str, float]]] = None,
    ) -> Union[BacktestResultV2, BacktestScalarScoreResult]:
        target_kind = str(_target_kind).strip().lower()
        if target_kind not in {"units", "notional", "weight", "equity_fraction", "pct_equity_transition"}:
            raise ValueError(
                "_target_kind must be units, notional, weight, equity_fraction, or pct_equity_transition"
            )
        contract_sizes = self._per_symbol_array(contract_size, symbol_list, default=1.0)
        constraints = build_quantity_constraints(
            symbol_list,
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )
        leverages = self._per_symbol_array(
            self.config.account.leverage if leverage is None else leverage,
            symbol_list,
            default=self.config.account.leverage,
        )
        fee_rates = self._per_symbol_array(
            self.config.fee_rate if fee_rate is None else fee_rate,
            symbol_list,
            default=0.0,
        )
        equity_fraction = self._per_symbol_array(
            1.0 if _equity_fraction is None else _equity_fraction,
            symbol_list,
            default=1.0,
        )
        rust_payload: Optional[Any] = None
        rust_execution_metadata: Optional[dict[str, Any]] = None
        rust_preparation: Optional[dict[str, Any]] = None
        use_rust_target = self._use_rust_target_runtime(target_kind)
        if target_kind != "units" and not use_rust_target:
            raise NotImplementedError(
                f"native_vectorized {target_kind!r} targets require target_runtime='rust'; "
                "Numba remains the frozen target-units compatibility route"
            )
        if use_rust_target:
            # Compact retains only the canonical accounting arrays needed by
            # the existing public result/score facades. Rust performs all
            # target resolution, quantity rounding, fills and account state;
            # Python never replays execution.
            rust_payload, rust_execution_metadata, rust_preparation = self._rust_target_payload(
                idx=idx,
                symbol_list=symbol_list,
                closes_m=closes_m,
                highs_m=highs_m,
                lows_m=lows_m,
                target_m=target_m,
                funding_m=funding_m,
                is_funding=is_funding,
                contract_sizes=contract_sizes,
                leverages=leverages,
                fee_rates=fee_rates,
                constraints=constraints,
                target_kind=target_kind,
                equity_fraction=equity_fraction,
                output_profile=1,
            )
            equity_arr = np.ascontiguousarray(rust_payload.equity, dtype=np.float64)
            pos_arr = np.ascontiguousarray(rust_payload.positions, dtype=np.float64).reshape(
                len(idx), len(symbol_list)
            )
            fee_arr = np.ascontiguousarray(rust_payload.fees, dtype=np.float64)
            turnover_arr = np.ascontiguousarray(rust_payload.turnover, dtype=np.float64)
            funding_arr = np.ascontiguousarray(rust_payload.funding, dtype=np.float64)
            init_margin_arr = np.ascontiguousarray(rust_payload.initial_margin, dtype=np.float64)
            maint_margin_arr = np.ascontiguousarray(
                rust_payload.maintenance_margin, dtype=np.float64
            )
            rejected_arr = np.ascontiguousarray(
                rust_payload.direct_target_rejected_by_bar,
                dtype=np.int64,
            )
            reject_code_arr = np.ascontiguousarray(
                rust_payload.direct_target_reject_code_by_bar,
                dtype=np.int64,
            )
            liq_flag = bool(rust_payload.liquidated)
            liq_idx = int(rust_payload.liquidation_bar)
            liq_reason = int(rust_payload.liquidation_reason)
        else:
            target_m = quantize_target_units_matrix(target_m, closes_m, contract_sizes, constraints)
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
                fee_rates=fee_rates,
                contract_sizes=contract_sizes,
                slippage=self.config.execution.slippage_rate,
                use_funding=bool(self.config.use_funding),
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
                    "backend": "native_vectorized",
                    "score_scalar": True,
                    "score_pandas_materialized": False,
                    "trading_days": int(_scalar_score_trading_days),
                    "target_runtime": "rust_direct_target_v1" if rust_payload is not None else "numba_units_v2",
                    "target_intent_kind": target_kind,
                    "native_target_execution": rust_execution_metadata,
                },
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

        metadata = self._close_target_metadata(
            symbol_list=symbol_list,
            idx=idx,
            high_low_source=high_low_source,
            first_bar_policy="target_units[0]_not_executed; first executable rebalance occurs at bar index 1",
        )
        metadata.update(
            {
                "fee_rate_oneway": self._fee_rate_metadata(fee_rates, symbol_list),
                "slippage_bps": self.config.execution.slippage_bps,
                "initial_buying_power": self.config.account.initial_capital * float(np.mean(leverages)),
                "liquidation_reason": int(liq_reason),
                "quantity_constraints": constraints.as_dict(),
                "target_runtime": "rust_direct_target_v1" if rust_payload is not None else "numba_units_v2",
                "target_intent_kind": target_kind,
            }
        )
        if rust_payload is not None:
            metadata.update(
                {
                    "native_target_execution": rust_execution_metadata,
                    "native_target_preparation": rust_preparation,
                }
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
            metadata=metadata,
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
        instruments: Optional[Union[Dict[str, InstrumentSpec], List[InstrumentSpec]]] = None,
        qty_step: Optional[Union[float, Dict[str, float]]] = None,
        lot_size: Optional[Union[float, Dict[str, float]]] = None,
        slot_size: Optional[Union[float, Dict[str, float]]] = None,
        min_qty: Optional[Union[float, Dict[str, float]]] = None,
        min_notional: Optional[Union[float, Dict[str, float]]] = None,
        market_arrays: Optional[PreparedMarketArrays] = None,
        raw_signal_matrix: Optional[np.ndarray] = None,
        _scalar_score_trading_days: Optional[int] = None,
    ) -> Union[BacktestResultV2, BacktestScalarScoreResult]:
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
        pos_dict = None if raw_signal_matrix is not None else align_series(positions, symbol_list, idx, fill_val=0.0)
        close_dict = None if market_arrays is not None else align_series(closes, symbol_list, idx)
        high_low_source = "prepared_market_arrays" if market_arrays is not None else self._high_low_source(highs, lows)
        if market_arrays is None:
            self._warn_high_low_fallback(high_low_source)
        alloc = self._per_symbol_mapping(alloc_per_trade, symbol_list, default=100_000.0)

        if ht in ("signal_notional", "signal"):
            if market_arrays is None:
                high_dict = align_series(highs, symbol_list, idx, fallback=close_dict)
                low_dict = align_series(lows, symbol_list, idx, fallback=close_dict)
                funding_dict = prepare_funding(funding_rate if self.config.use_funding else 0.0, symbol_list, idx)
                closes_m, highs_m, lows_m, signals_m, funding_m, is_funding = build_arrays(
                    symbols=symbol_list,
                    idx=idx,
                    closes_dict=close_dict,
                    highs_dict=high_dict,
                    lows_dict=low_dict,
                    signals_dict=pos_dict,
                    funding_dict=funding_dict,
                )
            else:
                if market_arrays.signature != market_data_signature(idx, symbol_list):
                    raise ValueError("prepared market arrays do not match datetime_index/symbols")
                closes_m = market_arrays.closes
                highs_m = market_arrays.highs
                lows_m = market_arrays.lows
                funding_m = market_arrays.funding
                is_funding = market_arrays.is_funding_bar
                if raw_signal_matrix is None:
                    signals_m = build_signal_matrix(symbol_list, idx, pos_dict)
                else:
                    signals_m = np.ascontiguousarray(raw_signal_matrix, dtype=np.float64)
                    if signals_m.shape != closes_m.shape:
                        raise ValueError("raw_signal_matrix shape does not match prepared market arrays")
            allocs = np.array([alloc[s] for s in symbol_list], dtype=np.float64)
            target_m = scale_signal_notional_matrix(
                signals=signals_m,
                closes=closes_m,
                allocs=allocs,
                use_pyramiding=use_pyramiding,
            )
            return self._run_target_arrays(
                idx=idx,
                symbol_list=symbol_list,
                closes_m=closes_m,
                highs_m=highs_m,
                lows_m=lows_m,
                target_m=target_m,
                funding_m=funding_m,
                is_funding=is_funding,
                contract_size=contract_size,
                leverage=leverage,
                instruments=instruments,
                qty_step=qty_step,
                lot_size=lot_size,
                slot_size=slot_size,
                min_qty=min_qty,
                min_notional=min_notional,
                high_low_source=high_low_source,
                _scalar_score_trading_days=_scalar_score_trading_days,
            )

        if close_dict is None:
            close_dict = {
                symbol: pd.Series(market_arrays.closes[:, j], index=idx, name=symbol)
                for j, symbol in enumerate(symbol_list)
            }
        if pos_dict is None:
            pos_dict = {
                symbol: pd.Series(raw_signal_matrix[:, j], index=idx, name=symbol)
                for j, symbol in enumerate(symbol_list)
            }
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
            instruments=instruments,
            qty_step=qty_step,
            lot_size=lot_size,
            slot_size=slot_size,
            min_qty=min_qty,
            min_notional=min_notional,
        )

    def score_signals(self, *, trading_days: int = 365, **kwargs) -> BacktestScalarScoreResult:
        """Score prepared signal-notional targets without pandas report paths."""
        hedge_type = str(kwargs.get("hedge_type", "signal_notional")).lower().strip()
        if hedge_type not in {"signal_notional", "signal"}:
            raise NotImplementedError(
                "native_vectorized scalar scoring currently supports signal_notional only"
            )
        result = self.run_signals(
            **kwargs,
            _scalar_score_trading_days=int(trading_days),
        )
        if not isinstance(result, BacktestScalarScoreResult):  # pragma: no cover - guarded above
            raise RuntimeError("native_vectorized scalar score unexpectedly materialized a public result")
        return result

    def run_basis_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: BasisArbitrageSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
    ) -> BacktestResultV2:
        if not isinstance(spec, BasisArbitrageSpec):
            raise TypeError("run_basis_arbitrage requires a BasisArbitrageSpec")
        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        basis_funding = self._funding_for_spec(spec, funding_rate)
        target_units = {symbol: plan.target_units[symbol] for symbol in symbols}

        result = self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=basis_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )
        funding_dict = prepare_funding(basis_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles={leg.symbol: leg.role for leg in spec.legs},
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        result.metadata.update(
            {
                "backend": "native_vectorized",
                "engine": "units_v2_basis_arbitrage",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "package_rejection_report": plan.rejection_report,
                "spread_report": self._basis_spread_report(idx, spec, close_dict, plan.target_units),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    def run_stat_arb_pair_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: StatArbPairSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        if not isinstance(spec, StatArbPairSpec):
            raise TypeError("run_stat_arb_pair_arbitrage requires a StatArbPairSpec")
        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        basket = self._stat_arb_basket_from_spec(spec)
        rebalance_threshold = spec.hedge_policy.rebalance_threshold
        if not spec.hedge_policy.freeze_on_entry and rebalance_threshold is None:
            rebalance_threshold = 0.0
        plan = build_frozen_basket_orders(
            datetime_index=idx,
            basket=basket,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
            rebalance_threshold=rebalance_threshold,
        )
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        stat_funding = self._funding_for_spec(spec, funding_rate)
        arb_plan = self._apply_atomic_package_margin_policy(
            idx=idx,
            plan=ArbitragePlan(
                spec=spec,
                orders=plan.orders,
                target_units=plan.target_units,
                signals=plan.signals,
                entry_ratios=plan.entry_ratios,
                rejections=(),
                metadata=plan.metadata,
            ),
            closes=close_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
            leverage=leverage,
        )
        target_units = {symbol: arb_plan.target_units[symbol] for symbol in symbols}

        result = self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=stat_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )
        funding_dict = prepare_funding(stat_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles=self._stat_arb_roles(spec),
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        result.metadata.update(
            {
                "backend": "native_vectorized",
                "engine": "units_v2_stat_arb_pair",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": arb_plan,
                "package_target_units": arb_plan.target_units,
                "package_rejection_report": arb_plan.rejection_report,
                "basket_plan": plan,
                "basket_target_units": arb_plan.target_units,
                "beta_drift_report": self._stat_arb_beta_drift_report(idx, spec, arb_plan, rebalance_threshold),
                "spread_report": self._stat_arb_spread_report(idx, spec, close_dict, arb_plan),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "rebalance_threshold": rebalance_threshold,
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

    def run_package_arbitrage(
        self,
        datetime_index: Union[pd.DatetimeIndex, pd.Series],
        spec: ArbitrageSpec,
        signal: pd.Series,
        closes: Dict[str, pd.Series],
        highs: Optional[Dict[str, pd.Series]] = None,
        lows: Optional[Dict[str, pd.Series]] = None,
        hedge_ratios: Optional[Dict[str, pd.Series]] = None,
        funding_rate: Union[float, pd.Series, Dict] = 0.0,
        contract_size: Optional[Union[float, Dict[str, float]]] = None,
        leverage: Optional[Union[float, Dict[str, float]]] = None,
    ) -> BacktestResultV2:
        unsupported = (CrossExchangeArbSpec, TriangularArbSpec, OptionsVolArbSpec)
        if isinstance(spec, unsupported):
            raise NotImplementedError(
                f"{type(spec).__name__} is schema-validated but requires a specialized arbitrage engine; "
                "do not route it through generic package execution. "
                "Use QuantBTEndpoint.arbitrage_support_matrix() to inspect supported routes."
            )
        supported = (CalendarSpreadSpec, FundingArbitrageSpec, SpotPerpCashCarrySpec, IndexBasketArbSpec)
        if not isinstance(spec, supported):
            raise TypeError("run_package_arbitrage requires a Phase G package-style arbitrage spec")

        idx = validate_datetime(datetime_index)
        symbols = [leg.symbol for leg in spec.legs]
        close_dict = align_series(closes, symbols, idx)
        plan = build_arbitrage_order_plan(
            datetime_index=idx,
            spec=spec,
            signal=signal,
            closes=close_dict,
            hedge_ratios=hedge_ratios,
        )
        contract_sizes = self._contract_size_for_spec(spec, contract_size)
        fee_rates = self._fee_rate_for_spec(spec)
        plan = self._apply_atomic_package_margin_policy(idx, plan, close_dict, contract_sizes, fee_rates, leverage)
        package_funding = self._funding_for_spec(spec, funding_rate)
        target_units = {symbol: plan.target_units[symbol] for symbol in symbols}

        result = self.run_target_units(
            datetime_index=idx,
            target_units=target_units,
            closes=close_dict,
            highs=highs,
            lows=lows,
            funding_rate=package_funding,
            contract_size=contract_sizes,
            leverage=leverage,
            fee_rate=fee_rates,
            symbols=symbols,
        )
        funding_dict = prepare_funding(package_funding if self.config.use_funding else 0.0, symbols, idx)
        leg_pnl_report = self._leg_pnl_report(
            idx=idx,
            symbols=symbols,
            roles={leg.symbol: leg.role for leg in spec.legs},
            result=result,
            closes=close_dict,
            funding=funding_dict,
            contract_sizes=contract_sizes,
            fee_rates=fee_rates,
        )
        package_report = self._package_pnl_report(idx, result, leg_pnl_report)
        result.metadata.update(
            {
                "backend": "native_vectorized",
                "engine": f"units_v2_{spec.arb_type.value}",
                "arb_id": spec.arb_id,
                "arb_type": spec.arb_type.value,
                "arbitrage_plan": plan,
                "package_target_units": plan.target_units,
                "package_rejection_report": plan.rejection_report,
                "spread_report": self._basis_spread_report(idx, spec, close_dict, plan.target_units),
                "leg_pnl_report": leg_pnl_report,
                "package_pnl_report": package_report,
                "carry_report": self._carry_report(idx, spec, result, close_dict, funding_dict, contract_sizes),
                "fee_rate_oneway": fee_rates,
                "contract_size": contract_sizes,
            }
        )
        return result

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

    def _apply_atomic_package_margin_policy(
        self,
        idx: pd.DatetimeIndex,
        plan: ArbitragePlan,
        closes: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
        leverage: Optional[Union[float, Dict[str, float]]],
    ) -> ArbitragePlan:
        spec = plan.spec
        if spec.execution_policy.kind not in (PackageExecutionKind.ATOMIC_ALL_OR_NONE, PackageExecutionKind.BEST_EFFORT):
            return plan

        symbols = [leg.symbol for leg in spec.legs]
        current_units = {symbol: 0.0 for symbol in symbols}
        equity = float(self.config.account.initial_capital)
        target_rows = []
        orders = []
        rejections = list(plan.rejections)
        leverages = self._leverage_mapping(leverage, symbols)
        slippage = self.config.execution.slippage_rate

        for i, ts in enumerate(idx):
            if i > 0:
                prev_ts = idx[i - 1]
                for symbol in symbols:
                    units = current_units[symbol]
                    if units != 0.0:
                        equity += units * (
                            float(closes[symbol].loc[ts]) - float(closes[symbol].loc[prev_ts])
                        ) * float(contract_sizes[symbol])

            original_desired = {symbol: float(plan.target_units.loc[ts, symbol]) for symbol in symbols}
            changed_symbols = [
                symbol for symbol in symbols
                if abs(original_desired[symbol] - current_units[symbol]) > 1e-12
            ]
            if changed_symbols:
                if spec.execution_policy.kind is PackageExecutionKind.ATOMIC_ALL_OR_NONE:
                    allowed, details = self._atomic_package_has_margin(
                        ts=ts,
                        symbols=symbols,
                        current_units=current_units,
                        desired_units=original_desired,
                        closes=closes,
                        contract_sizes=contract_sizes,
                        fee_rates=fee_rates,
                        leverages=leverages,
                        equity=equity,
                        slippage=slippage,
                    )
                    if not allowed:
                        rejections.append(
                            PackageRejection(
                                timestamp=ts,
                                arb_id=spec.arb_id,
                                reason="insufficient_margin_atomic",
                                failed_legs=tuple(changed_symbols),
                                metadata={"details": details, "policy": spec.execution_policy.kind.value},
                            )
                        )
                    else:
                        self._append_package_orders(orders, ts, spec, symbols, current_units, original_desired)
                        equity -= float(details.get("cost", 0.0))
                        current_units = original_desired
                else:
                    for symbol in symbols:
                        if abs(original_desired[symbol] - current_units[symbol]) <= 1e-12:
                            continue
                        candidate_units = dict(current_units)
                        candidate_units[symbol] = original_desired[symbol]
                        allowed, details = self._atomic_package_has_margin(
                            ts=ts,
                            symbols=symbols,
                            current_units=current_units,
                            desired_units=candidate_units,
                            closes=closes,
                            contract_sizes=contract_sizes,
                            fee_rates=fee_rates,
                            leverages=leverages,
                            equity=equity,
                            slippage=slippage,
                        )
                        if not allowed:
                            rejections.append(
                                PackageRejection(
                                    timestamp=ts,
                                    arb_id=spec.arb_id,
                                    reason="insufficient_margin_best_effort",
                                    failed_legs=(symbol,),
                                    metadata={"details": details, "policy": spec.execution_policy.kind.value},
                                )
                            )
                            continue
                        self._append_package_orders(orders, ts, spec, [symbol], current_units, candidate_units)
                        equity -= float(details.get("cost", 0.0))
                        current_units = candidate_units

            target_rows.append({symbol: current_units[symbol] for symbol in symbols})

        return ArbitragePlan(
            spec=spec,
            orders=tuple(orders),
            target_units=pd.DataFrame(target_rows, index=idx),
            signals=plan.signals,
            entry_ratios=plan.entry_ratios,
            rejections=tuple(rejections),
            metadata={**plan.metadata, "execution_margin_policy": "package_preflight"},
        )

    @staticmethod
    def _append_package_orders(
        orders: List[OrderIntent],
        ts,
        spec: ArbitrageSpec,
        symbols: List[str],
        current_units: Dict[str, float],
        desired_units: Dict[str, float],
    ) -> None:
        for symbol in symbols:
            delta = desired_units[symbol] - current_units[symbol]
            if abs(delta) <= 1e-12:
                continue
            side = OrderSide.BUY if delta > 0.0 else OrderSide.SELL
            orders.append(
                OrderIntent(
                    timestamp=ts,
                    symbol=symbol,
                    side=side,
                    order_type=spec.execution_policy.order_type,
                    qty=abs(delta),
                    tif=spec.execution_policy.tif,
                    tag=spec.arb_id,
                    metadata={
                        "arb_id": spec.arb_id,
                        "arb_type": spec.arb_type.value,
                        "package_policy": spec.execution_policy.kind.value,
                        "hedge_policy": spec.hedge_policy.kind.value,
                        "sizing_policy": spec.sizing_policy.kind.value,
                        "target_units": desired_units[symbol],
                        "previous_units": current_units[symbol],
                    },
                )
            )

    def _atomic_package_has_margin(
        self,
        ts,
        symbols: List[str],
        current_units: Dict[str, float],
        desired_units: Dict[str, float],
        closes: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
        leverages: Dict[str, float],
        equity: float,
        slippage: float,
    ) -> tuple[bool, Dict[str, float]]:
        cur_im = 0.0
        margin_delta_sum = 0.0
        cost_sum = 0.0
        for symbol in symbols:
            close_price = float(closes[symbol].loc[ts])
            cs = float(contract_sizes[symbol])
            lev = float(leverages[symbol])
            current = float(current_units[symbol])
            target = float(desired_units[symbol])
            cur_im += abs(current) * close_price * cs / lev
            delta = target - current
            if abs(delta) <= 1e-12:
                continue
            exec_price = close_price * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)
            old_im = abs(current) * close_price * cs / lev
            new_im = abs(target) * exec_price * cs / lev
            margin_delta_sum += new_im - old_im
            cost_sum += abs(delta) * exec_price * cs * float(fee_rates[symbol])
            cost_sum += abs(delta) * abs(exec_price - close_price) * cs

        available = max(0.0, float(equity) - cur_im)
        required = cost_sum + max(0.0, margin_delta_sum)
        return required <= available + 1e-12, {
            "available": available,
            "required": required,
            "current_initial_margin": cur_im,
            "margin_delta": margin_delta_sum,
            "cost": cost_sum,
        }

    def _leverage_mapping(self, leverage, symbols: List[str]) -> Dict[str, float]:
        default = float(self.config.account.leverage)
        if isinstance(leverage, dict):
            return {symbol: float(leverage.get(symbol, default)) for symbol in symbols}
        if leverage is None:
            return {symbol: default for symbol in symbols}
        return {symbol: float(leverage) for symbol in symbols}

    @staticmethod
    def _fee_rate_metadata(fee_rates: np.ndarray, symbols: List[str]):
        if len(fee_rates) == 0:
            return 0.0
        if np.allclose(fee_rates, fee_rates[0]):
            return float(fee_rates[0])
        return {symbol: float(fee_rates[i]) for i, symbol in enumerate(symbols)}

    def _fee_rate_for_spec(self, spec: ArbitrageSpec) -> Dict[str, float]:
        default_rates = self.config.fee_rate
        out: Dict[str, float] = {}
        for leg in spec.legs:
            if leg.fee_rate is not None:
                out[leg.symbol] = float(leg.fee_rate)
            elif isinstance(default_rates, dict):
                out[leg.symbol] = float(default_rates.get(leg.symbol, 0.0))
            else:
                out[leg.symbol] = float(default_rates)
        return out

    @staticmethod
    def _contract_size_for_spec(
        spec: ArbitrageSpec,
        contract_size: Optional[Union[float, Dict[str, float]]],
    ) -> Dict[str, float]:
        out = {leg.symbol: float(leg.contract_size) for leg in spec.legs}
        if contract_size is None:
            return out
        if isinstance(contract_size, dict):
            out.update({symbol: float(value) for symbol, value in contract_size.items()})
            return out
        return {leg.symbol: float(contract_size) for leg in spec.legs}

    @staticmethod
    def _funding_for_spec(spec: ArbitrageSpec, funding_rate: Union[float, pd.Series, Dict]):
        funding_symbols = {leg.symbol for leg in spec.legs if leg.funding_enabled}
        if isinstance(funding_rate, dict):
            return {
                leg.symbol: funding_rate.get(leg.symbol, 0.0) if leg.symbol in funding_symbols else 0.0
                for leg in spec.legs
            }
        return {leg.symbol: funding_rate if leg.symbol in funding_symbols else 0.0 for leg in spec.legs}

    @staticmethod
    def _stat_arb_roles(spec: StatArbPairSpec) -> Dict[str, str]:
        symbols = [leg.symbol for leg in spec.legs]
        roles = {leg.symbol: str(leg.role or "leg") for leg in spec.legs}
        if len(symbols) >= 2 and len(set(roles.values())) == 1:
            roles[symbols[0]] = "leg"
            roles[symbols[1]] = "hedge"
        return roles

    @staticmethod
    def _stat_arb_spread_report(
        idx: pd.DatetimeIndex,
        spec: StatArbPairSpec,
        closes: Dict[str, pd.Series],
        plan,
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        leg_symbol = symbols[0]
        hedge_symbol = symbols[1] if len(symbols) > 1 else symbols[0]
        leg_close = closes[leg_symbol].astype(float)
        hedge_close = closes[hedge_symbol].astype(float)
        ref_ratio = plan.entry_ratios[leg_symbol].replace(0.0, np.nan).astype(float)
        hedge_ratio = (plan.entry_ratios[hedge_symbol].astype(float) / ref_ratio).fillna(0.0)
        spread = leg_close + hedge_ratio * hedge_close
        return pd.DataFrame(
            {
                "leg_symbol": leg_symbol,
                "hedge_symbol": hedge_symbol,
                "leg_close": leg_close,
                "hedge_close": hedge_close,
                "hedge_ratio_to_leg": hedge_ratio,
                "spread": spread,
                "abs_spread": spread.abs(),
            },
            index=idx,
        )

    @staticmethod
    def _stat_arb_basket_from_spec(spec: StatArbPairSpec) -> BasketSpec:
        if spec.sizing_policy.kind is not SizingPolicyKind.TARGET_GROSS_NOTIONAL:
            raise NotImplementedError("Phase E StatArbPairSpec requires target_gross_notional sizing")
        return BasketSpec(
            basket_id=spec.arb_id,
            legs=tuple(BasketLegSpec(symbol=leg.symbol, ratio=float(leg.ratio)) for leg in spec.legs),
            gross_notional=float(spec.sizing_policy.notional),
            freeze_hedge=bool(spec.hedge_policy.freeze_on_entry),
            hedged_margin_offset=float(spec.margin_model.hedged_margin_offset),
            metadata={
                "arb_type": spec.arb_type.value,
                "hedge_policy": spec.hedge_policy.kind.value,
                "sizing_policy": spec.sizing_policy.kind.value,
            },
        )

    def _leg_pnl_report(
        self,
        idx: pd.DatetimeIndex,
        symbols: List[str],
        roles: Dict[str, str],
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
        fee_rates: Dict[str, float],
    ) -> pd.DataFrame:
        funding_mask = make_funding_mask(idx)
        cumulative = {symbol: 0.0 for symbol in symbols}
        rows = []
        slippage = self.config.execution.slippage_rate
        for i, ts in enumerate(idx):
            for symbol in symbols:
                cs = float(contract_sizes[symbol])
                close_price = float(closes[symbol].iloc[i])
                prev_units = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                units = float(result.positions[f"Position_{symbol}"].iloc[i])
                delta = units - prev_units
                price_pnl = 0.0
                if i > 0:
                    price_pnl = prev_units * (close_price - float(closes[symbol].iloc[i - 1])) * cs
                exec_price = close_price * (1.0 + slippage if delta > 0.0 else 1.0 - slippage)
                fee = abs(delta) * exec_price * cs * float(fee_rates[symbol]) if abs(delta) > 1e-12 else 0.0
                slippage_cost = abs(delta) * abs(exec_price - close_price) * cs if abs(delta) > 1e-12 else 0.0
                funding_cost = 0.0
                if self.config.use_funding and funding_mask[i]:
                    funding_cost = prev_units * close_price * cs * float(funding[symbol].iloc[i])
                total_pnl = price_pnl - fee - slippage_cost - funding_cost
                cumulative[symbol] += total_pnl
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": roles.get(symbol, "leg"),
                        "units": units,
                        "close": close_price,
                        "notional": abs(units) * close_price * cs,
                        "price_pnl": price_pnl,
                        "fill_pnl": -slippage_cost,
                        "fee": fee,
                        "funding_pnl": -funding_cost,
                        "total_pnl": total_pnl,
                        "cumulative_pnl": cumulative[symbol],
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _package_pnl_report(idx: pd.DatetimeIndex, result: BacktestResultV2, leg_pnl_report: pd.DataFrame) -> pd.DataFrame:
        grouped = leg_pnl_report.groupby("timestamp", sort=False)
        package_pnl = grouped["total_pnl"].sum().reindex(idx, fill_value=0.0)
        price_pnl = grouped["price_pnl"].sum().reindex(idx, fill_value=0.0)
        fill_pnl = grouped["fill_pnl"].sum().reindex(idx, fill_value=0.0)
        fees = grouped["fee"].sum().reindex(idx, fill_value=0.0)
        funding_pnl = grouped["funding_pnl"].sum().reindex(idx, fill_value=0.0)
        role_pnl = leg_pnl_report.pivot_table(
            index="timestamp",
            columns="role",
            values="total_pnl",
            aggfunc="sum",
            fill_value=0.0,
        ).reindex(idx, fill_value=0.0)
        leg_pnl = role_pnl["leg"] if "leg" in role_pnl else pd.Series(0.0, index=idx)
        hedge_pnl = role_pnl["hedge"] if "hedge" in role_pnl else pd.Series(0.0, index=idx)
        report = pd.DataFrame(
            {
                "price_pnl": price_pnl,
                "fill_pnl": fill_pnl,
                "fees": fees,
                "funding_pnl": funding_pnl,
                "leg_pnl": leg_pnl,
                "hedge_pnl": hedge_pnl,
                "spread_pnl": leg_pnl + hedge_pnl,
                "package_pnl": package_pnl,
                "equity_delta": result.equity.diff().fillna(0.0),
            },
            index=idx,
        )
        report["pnl_residual"] = report["equity_delta"] - report["package_pnl"]
        return report

    @staticmethod
    def _basis_spread_report(
        idx: pd.DatetimeIndex,
        spec: ArbitrageSpec,
        closes: Dict[str, pd.Series],
        target_units: pd.DataFrame,
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        base_symbol = spec.spread_formula.base_symbol
        quote_symbol = spec.spread_formula.quote_symbol
        if base_symbol is None:
            base_symbol = next((leg.symbol for leg in spec.legs if leg.ratio < 0.0), symbols[0])
        if quote_symbol is None:
            quote_symbol = next((leg.symbol for leg in spec.legs if leg.ratio > 0.0), symbols[-1])
        base_close = closes[base_symbol].astype(float)
        quote_close = closes[quote_symbol].astype(float)
        spread = quote_close - base_close
        ratio_spread = quote_close / base_close.replace(0.0, np.nan) - 1.0
        expiry = next((leg.expiry for leg in spec.legs if leg.symbol == quote_symbol and leg.expiry is not None), None)
        if expiry is None:
            expiry = next((leg.expiry for leg in spec.legs if leg.expiry is not None), None)
        if expiry is None:
            annualized = pd.Series(np.nan, index=idx, dtype=float)
        else:
            days_to_expiry = pd.Series(
                [(expiry - ts).total_seconds() / 86_400.0 for ts in idx],
                index=idx,
                dtype=float,
            )
            annualized = ratio_spread * (365.0 / days_to_expiry.where(days_to_expiry > 0.0))
        report = pd.DataFrame(
            {
                "base_symbol": base_symbol,
                "quote_symbol": quote_symbol,
                "base_close": base_close,
                "quote_close": quote_close,
                "spread": spread,
                "ratio_spread": ratio_spread,
                "annualized_basis": annualized,
            },
            index=idx,
        )
        for symbol in symbols:
            report[f"target_units_{symbol}"] = target_units[symbol]
        return report

    @staticmethod
    def _carry_report(
        idx: pd.DatetimeIndex,
        spec: ArbitrageSpec,
        result: BacktestResultV2,
        closes: Dict[str, pd.Series],
        funding: Dict[str, pd.Series],
        contract_sizes: Dict[str, float],
    ) -> pd.DataFrame:
        rows = []
        funding_mask = make_funding_mask(idx)
        for i, ts in enumerate(idx):
            for leg in spec.legs:
                symbol = leg.symbol
                prev_units = 0.0 if i == 0 else float(result.positions[f"Position_{symbol}"].iloc[i - 1])
                close_price = float(closes[symbol].iloc[i])
                notional = abs(prev_units) * close_price * float(contract_sizes[symbol])
                funding_cost = 0.0
                if funding_mask[i] and leg.funding_enabled:
                    funding_cost = prev_units * close_price * float(contract_sizes[symbol]) * float(funding[symbol].iloc[i])
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "role": leg.role,
                        "funding_enabled": bool(leg.funding_enabled),
                        "borrow_rate": float(spec.carry_model.borrow_rate),
                        "cash_yield": float(spec.carry_model.cash_yield),
                        "notional": notional,
                        "funding_cost": funding_cost,
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _stat_arb_beta_drift_report(
        idx: pd.DatetimeIndex,
        spec: StatArbPairSpec,
        plan,
        rebalance_threshold: Optional[float],
    ) -> pd.DataFrame:
        symbols = [leg.symbol for leg in spec.legs]
        reference_symbol = symbols[0]
        rows = []
        for ts in idx:
            ref_units = float(plan.target_units.loc[ts, reference_symbol])
            ref_ratio = float(plan.entry_ratios.loc[ts, reference_symbol])
            active = abs(ref_units) > 1e-12 and abs(ref_ratio) > 1e-12
            for symbol in symbols:
                units = float(plan.target_units.loc[ts, symbol])
                current_ratio = float(plan.entry_ratios.loc[ts, symbol])
                if active:
                    frozen_ratio_to_ref = units / ref_units
                    current_ratio_to_ref = current_ratio / ref_ratio
                    abs_drift = abs(current_ratio_to_ref - frozen_ratio_to_ref)
                    rel_drift = abs_drift / max(abs(frozen_ratio_to_ref), 1e-12)
                else:
                    frozen_ratio_to_ref = 0.0
                    current_ratio_to_ref = 0.0
                    abs_drift = 0.0
                    rel_drift = 0.0
                rows.append(
                    {
                        "timestamp": ts,
                        "symbol": symbol,
                        "reference_symbol": reference_symbol,
                        "target_units": units,
                        "frozen_ratio_to_ref": frozen_ratio_to_ref,
                        "current_ratio_to_ref": current_ratio_to_ref,
                        "abs_beta_drift": abs_drift,
                        "rel_beta_drift": rel_drift,
                        "rebalance_threshold": rebalance_threshold,
                        "breached": (
                            rebalance_threshold is not None
                            and rel_drift > rebalance_threshold
                            and symbol != reference_symbol
                        ),
                    }
                )
        return pd.DataFrame(rows)
