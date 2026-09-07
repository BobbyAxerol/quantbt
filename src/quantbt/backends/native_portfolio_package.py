"""Certified Rust-owned market routes for bounded portfolio/package tapes.

These helpers deliberately do not replace :class:`NativePortfolioBackend` or
the general Python package executor.  They expose exact, explicitly selected
contracts promoted by the native event runtime:

* bar-major ``target_units`` with legacy all-or-none rebalance admission;
* bar-major units/notional/weight/equity-fraction targets against one shared
  Rust-owned linear account with an explicit admission policy; and
* one same-bar all-or-none market package transaction.

Both run one typed Python-to-Rust request.  Rust owns the causal account
projection, market command generation, lifecycle, costs, funding, margin and
audit; Python only prepares immutable arrays and adapts a completed audit in
the cold path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from ..core.instrument_registry_v2 import InstrumentRegistryV2
from ..core.market_calendar_v2 import PreparedMarketHandleV2
from ..preparation.native_execution import NativeExecutionPreparationCache
from ._native_event_rust import RustFullAuditResult


_OUTPUT_PROFILES = {
    "score": 0,
    "minimal": 0,
    "compact": 1,
    "standard": 1,
    "audit": 2,
}


def _output_profile(report_level: str) -> int:
    """Map a stable public retention level to the typed native profile."""

    try:
        return _OUTPUT_PROFILES[str(report_level).lower().strip()]
    except KeyError as exc:
        allowed = ", ".join(sorted(_OUTPUT_PROFILES))
        raise ValueError(f"report_level must be one of: {allowed}") from exc


@dataclass(frozen=True, slots=True)
class RustNativeMarketExecution:
    """Completed bounded native market execution plus immutable provenance.

    ``payload`` is the direct Rust cold-path output.  It includes canonical
    fill/event columns and either ``portfolio_target_*`` or ``package_*``
    admission/audit columns.  No Python execution replay is performed.
    """

    payload: Mapping[str, object]
    request_signature: str
    workload: str
    symbols: tuple[str, ...]

    @property
    def final_equity(self) -> float:
        """Return final equity from the authoritative native result."""

        return float(self.payload["final_equity"])

    def to_audit_result(self) -> RustFullAuditResult:
        """Adapt an audit payload to the common result surface without replay."""

        if str(self.payload.get("native_execution_output_profile")) != "audit":
            raise ValueError(
                "to_audit_result() requires report_level='audit'; rerun the selected candidate "
                "with audit retention rather than replaying a score/compact execution"
            )

        identifiers: dict[int, str] = {}
        for key in ("fill_order_id", "event_order_id", "event_target_id"):
            for value in np.asarray(self.payload.get(key, ()), dtype=np.int64):
                code = int(value)
                if code >= 0:
                    identifiers[code] = str(code)
        return RustFullAuditResult.from_audit_payload(
            self.payload,
            n_bars=int(np.asarray(self.payload["equity"]).shape[0]),
            n_symbols=len(self.symbols),
            external_id_values=identifiers,
        )


def _prepare_template(
    cache: NativeExecutionPreparationCache,
    *,
    timestamps_ns: object,
    opens: object,
    highs: object,
    lows: object,
    closes: object,
    volumes: object,
    funding: object,
    funding_mask: object,
    symbols: Sequence[str],
    contract_sizes: object,
    leverages: object,
    fee_rates: object,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
):
    """Prepare one content-addressed V2 market/template pair."""

    market = cache.prepare_market(
        timestamps_ns=timestamps_ns,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        funding=funding,
        funding_mask=funding_mask,
        symbols=symbols,
    )
    return cache.prepare_template(
        market,
        contract_sizes=contract_sizes,
        leverages=leverages,
        fee_rates=fee_rates,
        initial_capital=float(initial_capital),
        maintenance_ratio=float(maintenance_ratio),
        slippage_rate=float(slippage_rate),
        use_funding=bool(use_funding),
        event_contract_code=2,
    )


def run_portfolio_target_market(
    *,
    timestamps_ns: object,
    opens: object,
    highs: object,
    lows: object,
    closes: object,
    volumes: object,
    funding: object,
    funding_mask: object,
    symbols: Sequence[str],
    contract_sizes: object,
    leverages: object,
    fee_rates: object,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    target_units: object,
    tradable: object | None = None,
    stale: object | None = None,
    min_qty: object | None = None,
    min_notional: object | None = None,
    external_id_start: int = 1,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Run the certified Rust ``target_units`` market contract.

    ``target_units``, ``tradable`` and ``stale`` must be bar-major arrays with
    shape ``(bars, symbols)``. Target values must be finite or preparation
    fails before any account state is created. Missing masks default to
    tradable/non-stale; quantity constraints default to zero. ``report_level`` selects `score`,
    `compact`/`standard`, or `audit` retention without changing execution.
    A target transition is accepted in full or left at the prior units.
    Unsupported portfolio modes, sizing,
    rebalancing policies and cross-margin semantics are intentionally outside
    this helper and remain on the Python engine.
    """

    cache = NativeExecutionPreparationCache() if cache is None else cache
    template = _prepare_template(
        cache,
        timestamps_ns=timestamps_ns,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        funding=funding,
        funding_mask=funding_mask,
        symbols=symbols,
        contract_sizes=contract_sizes,
        leverages=leverages,
        fee_rates=fee_rates,
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
    )
    targets = np.ascontiguousarray(np.asarray(target_units, dtype=np.float64))
    expected = (int(template.core.bars), len(tuple(symbols)))
    if targets.shape != expected:
        raise ValueError("target_units must have shape (bars, symbols)")
    tradable_values = (
        np.ones(expected, dtype=np.bool_)
        if tradable is None
        else np.ascontiguousarray(np.asarray(tradable, dtype=np.bool_))
    )
    stale_values = (
        np.zeros(expected, dtype=np.bool_)
        if stale is None
        else np.ascontiguousarray(np.asarray(stale, dtype=np.bool_))
    )
    min_qty_values = (
        np.zeros(expected[1], dtype=np.float64)
        if min_qty is None
        else np.ascontiguousarray(np.asarray(min_qty, dtype=np.float64))
    )
    min_notional_values = (
        np.zeros(expected[1], dtype=np.float64)
        if min_notional is None
        else np.ascontiguousarray(np.asarray(min_notional, dtype=np.float64))
    )
    request = cache.portfolio_target_market_request(
        template,
        target_units=targets,
        tradable=tradable_values,
        stale=stale_values,
        min_qty=min_qty_values,
        min_notional=min_notional_values,
        external_id_start=int(external_id_start),
        output_profile=_output_profile(report_level),
    )
    return RustNativeMarketExecution(
        payload=dict(request.core.execute()),
        request_signature=request.signature,
        workload=request.workload,
        symbols=tuple(str(symbol) for symbol in symbols),
    )


def run_shared_portfolio_target_market(
    *,
    timestamps_ns: object,
    opens: object,
    highs: object,
    lows: object,
    closes: object,
    volumes: object,
    funding: object,
    funding_mask: object,
    symbols: Sequence[str],
    contract_sizes: object,
    leverages: object,
    fee_rates: object,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    targets: object,
    target_kind: str = "units",
    admission_policy: str = "sequential_legacy",
    tradable: object | None = None,
    stale: object | None = None,
    qty_step: object | None = None,
    min_qty: object | None = None,
    min_notional: object | None = None,
    equity_fraction: object | None = None,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Execute planned multi-symbol targets on one Rust-owned account.

    ``targets`` is a bar-major matrix and its meaning is declared by
    ``target_kind``: ``units``, ``notional``, ``weight``, or
    ``equity_fraction``.  The portfolio planner stays outside this helper;
    Rust resolves target deltas, quantizes them, applies the selected admission
    policy, and commits all account state in one pass.  ``admission_policy``
    is one of ``sequential_legacy``, ``reduce_first_then_increase``,
    ``pro_rata_to_available_margin``, or ``all_or_none_rebalance``.

    This is a declared linear gross-margin contract, not venue-specific
    portfolio margin or a hidden generic endpoint promotion.
    """

    cache = NativeExecutionPreparationCache() if cache is None else cache
    template = _prepare_template(
        cache,
        timestamps_ns=timestamps_ns,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        funding=funding,
        funding_mask=funding_mask,
        symbols=symbols,
        contract_sizes=contract_sizes,
        leverages=leverages,
        fee_rates=fee_rates,
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
    )
    expected = (int(template.core.bars), len(tuple(symbols)))
    target_values = np.ascontiguousarray(np.asarray(targets, dtype=np.float64))
    if target_values.shape != expected:
        raise ValueError("targets must have shape (bars, symbols)")
    tradable_values = (
        np.ones(expected, dtype=np.bool_)
        if tradable is None
        else np.ascontiguousarray(np.asarray(tradable, dtype=np.bool_))
    )
    stale_values = (
        np.zeros(expected, dtype=np.bool_)
        if stale is None
        else np.ascontiguousarray(np.asarray(stale, dtype=np.bool_))
    )
    qty_step_values = (
        np.zeros(expected[1], dtype=np.float64)
        if qty_step is None
        else np.ascontiguousarray(np.asarray(qty_step, dtype=np.float64))
    )
    min_qty_values = (
        np.zeros(expected[1], dtype=np.float64)
        if min_qty is None
        else np.ascontiguousarray(np.asarray(min_qty, dtype=np.float64))
    )
    min_notional_values = (
        np.zeros(expected[1], dtype=np.float64)
        if min_notional is None
        else np.ascontiguousarray(np.asarray(min_notional, dtype=np.float64))
    )
    equity_fraction_values = (
        np.ones(expected[1], dtype=np.float64)
        if equity_fraction is None
        else np.ascontiguousarray(np.asarray(equity_fraction, dtype=np.float64))
    )
    request = cache.shared_portfolio_target_request(
        template,
        targets=target_values,
        target_kind=target_kind,
        admission_policy=admission_policy,
        tradable=tradable_values,
        stale=stale_values,
        qty_step=qty_step_values,
        min_qty=min_qty_values,
        min_notional=min_notional_values,
        equity_fraction=equity_fraction_values,
        output_profile=_output_profile(report_level),
    )
    return RustNativeMarketExecution(
        payload=dict(request.core.execute()),
        request_signature=request.signature,
        workload=request.workload,
        symbols=tuple(str(symbol) for symbol in symbols),
    )


def run_atomic_package_market(
    *,
    timestamps_ns: object,
    opens: object,
    highs: object,
    lows: object,
    closes: object,
    volumes: object,
    funding: object,
    funding_mask: object,
    symbols: Sequence[str],
    contract_sizes: object,
    leverages: object,
    fee_rates: object,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    command_bar: int,
    package_id: int,
    order_ids: object,
    symbol_ids: object,
    signed_qty: object,
    source_age_ns: object,
    venue_codes: object,
    venue_sequence: object,
    min_qty: object | None = None,
    min_notional: object | None = None,
    max_staleness_ns: int = 0,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Run one certified same-bar all-or-none market package transaction.

    Every accepted leg is submitted in deterministic ``venue_sequence`` order
    on ``command_bar``.  If any leg is stale, invalid, below its constraint or
    fails the post-cost margin gate, no leg is submitted.  The model is a
    deterministic OHLC bar transaction, not venue-native all-or-none or L2
    queue simulation.
    """

    cache = NativeExecutionPreparationCache() if cache is None else cache
    template = _prepare_template(
        cache,
        timestamps_ns=timestamps_ns,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        funding=funding,
        funding_mask=funding_mask,
        symbols=symbols,
        contract_sizes=contract_sizes,
        leverages=leverages,
        fee_rates=fee_rates,
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
    )
    order_ids_array = np.ascontiguousarray(np.asarray(order_ids, dtype=np.int64))
    count = len(order_ids_array)
    request = cache.package_atomic_market_request(
        template,
        command_bar=int(command_bar),
        package_id=int(package_id),
        order_ids=order_ids_array,
        symbol_ids=np.ascontiguousarray(np.asarray(symbol_ids, dtype=np.uint32)),
        signed_qty=np.ascontiguousarray(np.asarray(signed_qty, dtype=np.float64)),
        source_age_ns=np.ascontiguousarray(np.asarray(source_age_ns, dtype=np.int64)),
        venue_codes=np.ascontiguousarray(np.asarray(venue_codes, dtype=np.uint16)),
        venue_sequence=np.ascontiguousarray(np.asarray(venue_sequence, dtype=np.uint32)),
        min_qty=(
            np.zeros(count, dtype=np.float64)
            if min_qty is None
            else np.ascontiguousarray(np.asarray(min_qty, dtype=np.float64))
        ),
        min_notional=(
            np.zeros(count, dtype=np.float64)
            if min_notional is None
            else np.ascontiguousarray(np.asarray(min_notional, dtype=np.float64))
        ),
        max_staleness_ns=int(max_staleness_ns),
        output_profile=_output_profile(report_level),
    )
    return RustNativeMarketExecution(
        payload=dict(request.core.execute()),
        request_signature=request.signature,
        workload=request.workload,
        symbols=tuple(str(symbol) for symbol in symbols),
    )


def run_bounded_package_market(
    *,
    timestamps_ns: object,
    opens: object,
    highs: object,
    lows: object,
    closes: object,
    volumes: object,
    funding: object,
    funding_mask: object,
    symbols: Sequence[str],
    contract_sizes: object,
    leverages: object,
    fee_rates: object,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    command_bars: object,
    package_ids: object,
    package_leg_offsets: object,
    execution_policies: object,
    residual_policies: object,
    max_staleness_ns: object,
    order_ids: object,
    symbol_ids: object,
    signed_qty: object,
    quantity_sources: object,
    source_legs: object,
    quantity_ratios: object,
    fill_fractions: object,
    qty_step: object,
    min_qty: object,
    min_notional: object,
    source_age_ns: object,
    venue_codes: object,
    venue_sequence: object,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Run typed bounded package policies on one Rust-owned linear account.

    The accepted policies are ``atomic_bar_simulation``, ``sequential``,
    ``best_effort`` and ``hedge_after_primary``. Every package uses one command
    bar and a contiguous range of legs in ``package_leg_offsets``. A non-unity
    ``fill_fractions`` value is an explicit deterministic partial-fill
    scenario; it is neither L2 depth simulation nor exchange-native package
    atomicity. The output always reports residual/reconciliation provenance.

    This helper is deliberately separate from the generic arbitrage endpoint.
    It certifies only a same-account, quote-settled linear package contract;
    cross-venue/currency-flow/option packages remain explicit Python routes.
    """

    cache = NativeExecutionPreparationCache() if cache is None else cache
    template = _prepare_template(
        cache,
        timestamps_ns=timestamps_ns,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        funding=funding,
        funding_mask=funding_mask,
        symbols=symbols,
        contract_sizes=contract_sizes,
        leverages=leverages,
        fee_rates=fee_rates,
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
    )
    request = cache.package_market_v2_request(
        template,
        command_bars=command_bars,
        package_ids=package_ids,
        package_leg_offsets=package_leg_offsets,
        execution_policies=execution_policies,
        residual_policies=residual_policies,
        max_staleness_ns=max_staleness_ns,
        order_ids=order_ids,
        symbol_ids=symbol_ids,
        signed_qty=signed_qty,
        quantity_sources=quantity_sources,
        source_legs=source_legs,
        quantity_ratios=quantity_ratios,
        fill_fractions=fill_fractions,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
        source_age_ns=source_age_ns,
        venue_codes=venue_codes,
        venue_sequence=venue_sequence,
        output_profile=_output_profile(report_level),
    )
    return RustNativeMarketExecution(
        payload=dict(request.core.execute()),
        request_signature=request.signature,
        workload=request.workload,
        symbols=tuple(str(symbol) for symbol in symbols),
    )


def run_bounded_package_market_scenarios(
    *,
    timestamps_ns: object,
    opens: object,
    highs: object,
    lows: object,
    closes: object,
    volumes: object,
    funding: object,
    funding_mask: object,
    symbols: Sequence[str],
    contract_sizes: object,
    leverages: object,
    fee_rates: object,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    scenario_package_offsets: object,
    command_bars: object,
    package_ids: object,
    package_leg_offsets: object,
    execution_policies: object,
    residual_policies: object,
    max_staleness_ns: object,
    order_ids: object,
    symbol_ids: object,
    signed_qty: object,
    quantity_sources: object,
    source_legs: object,
    quantity_ratios: object,
    fill_fractions: object,
    qty_step: object,
    min_qty: object,
    min_notional: object,
    source_age_ns: object,
    venue_codes: object,
    venue_sequence: object,
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Score isolated typed package scenarios in one Python-to-Rust call.

    Each scenario is an independent account reset selected by
    ``scenario_package_offsets``. The route retains scalar numeric result
    columns only; rerun an individual candidate with
    :func:`run_bounded_package_market` and ``report_level="audit"`` for
    package legs, residuals, and lifecycle evidence. This explicit helper is
    suitable for package candidate/fold execution after intent construction;
    it does not change generic walk-forward or arbitrage routing.
    """

    cache = NativeExecutionPreparationCache() if cache is None else cache
    template = _prepare_template(
        cache,
        timestamps_ns=timestamps_ns,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=volumes,
        funding=funding,
        funding_mask=funding_mask,
        symbols=symbols,
        contract_sizes=contract_sizes,
        leverages=leverages,
        fee_rates=fee_rates,
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
    )
    request = cache.package_market_v2_scenario_batch(
        template,
        scenario_package_offsets=scenario_package_offsets,
        command_bars=command_bars,
        package_ids=package_ids,
        package_leg_offsets=package_leg_offsets,
        execution_policies=execution_policies,
        residual_policies=residual_policies,
        max_staleness_ns=max_staleness_ns,
        order_ids=order_ids,
        symbol_ids=symbol_ids,
        signed_qty=signed_qty,
        quantity_sources=quantity_sources,
        source_legs=source_legs,
        qty_step=qty_step,
        min_qty=min_qty,
        min_notional=min_notional,
        source_age_ns=source_age_ns,
        venue_codes=venue_codes,
        venue_sequence=venue_sequence,
        quantity_ratios=quantity_ratios,
        fill_fractions=fill_fractions,
    )
    return RustNativeMarketExecution(
        payload=dict(request.core.execute()),
        request_signature=request.signature,
        workload=request.workload,
        symbols=tuple(str(symbol) for symbol in symbols),
    )


def _v2_market_registry_inputs(
    *,
    market: PreparedMarketHandleV2,
    instruments: InstrumentRegistryV2,
) -> tuple[object, dict[str, np.ndarray]]:
    """Lower an explicit V2 handle into the existing typed Rust request ABI.

    The lowering is zero-copy for the prepared array views.  It only accepts a
    fully observed execution view: current market helpers have no missing-bar
    ABI, so union/primary-clock data must remain at the V2 planning boundary
    rather than be silently forward-filled.
    """
    if market.symbols != instruments.symbols:
        raise ValueError(
            "V2 market/instrument symbols differ: "
            f"market={market.symbols} instruments={instruments.symbols}"
        )
    return market.execution_view(), instruments.arrays()


def run_portfolio_target_market_v2(
    *,
    market: PreparedMarketHandleV2,
    instruments: InstrumentRegistryV2,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    target_units: object,
    tradable: object | None = None,
    stale: object | None = None,
    external_id_start: int = 1,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Run target units using one canonical V2 market/instrument source."""
    view, arrays = _v2_market_registry_inputs(market=market, instruments=instruments)
    return run_portfolio_target_market(
        timestamps_ns=view.timestamps_ns,
        opens=view.opens,
        highs=view.highs,
        lows=view.lows,
        closes=view.closes,
        volumes=view.volumes,
        funding=view.funding_rates,
        funding_mask=view.funding_event_mask,
        symbols=view.symbols,
        contract_sizes=arrays["contract_size"],
        leverages=arrays["leverage"],
        fee_rates=arrays["fee_rate"],
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
        target_units=target_units,
        tradable=view.tradable if tradable is None else tradable,
        stale=view.stale if stale is None else stale,
        min_qty=arrays["min_qty"],
        min_notional=arrays["min_notional"],
        external_id_start=external_id_start,
        report_level=report_level,
        cache=cache,
    )


def run_shared_portfolio_target_market_v2(
    *,
    market: PreparedMarketHandleV2,
    instruments: InstrumentRegistryV2,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    targets: object,
    target_kind: str = "units",
    admission_policy: str = "sequential_legacy",
    tradable: object | None = None,
    stale: object | None = None,
    equity_fraction: object | None = None,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Run a planned shared-account portfolio from canonical V2 inputs."""

    view, arrays = _v2_market_registry_inputs(market=market, instruments=instruments)
    return run_shared_portfolio_target_market(
        timestamps_ns=view.timestamps_ns,
        opens=view.opens,
        highs=view.highs,
        lows=view.lows,
        closes=view.closes,
        volumes=view.volumes,
        funding=view.funding_rates,
        funding_mask=view.funding_event_mask,
        symbols=view.symbols,
        contract_sizes=arrays["contract_size"],
        leverages=arrays["leverage"],
        fee_rates=arrays["fee_rate"],
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
        targets=targets,
        target_kind=target_kind,
        admission_policy=admission_policy,
        tradable=view.tradable if tradable is None else tradable,
        stale=view.stale if stale is None else stale,
        qty_step=arrays["qty_step"],
        min_qty=arrays["min_qty"],
        min_notional=arrays["min_notional"],
        equity_fraction=equity_fraction,
        report_level=report_level,
        cache=cache,
    )


def run_atomic_package_market_v2(
    *,
    market: PreparedMarketHandleV2,
    instruments: InstrumentRegistryV2,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    command_bar: int,
    package_id: int,
    order_ids: object,
    symbol_ids: object,
    signed_qty: object,
    source_age_ns: object,
    venue_codes: object,
    venue_sequence: object,
    max_staleness_ns: int = 0,
    report_level: str = "audit",
    cache: NativeExecutionPreparationCache | None = None,
) -> RustNativeMarketExecution:
    """Run an atomic market package from the same V2 source-of-truth pair."""
    view, arrays = _v2_market_registry_inputs(market=market, instruments=instruments)
    symbol_ids_array = np.ascontiguousarray(np.asarray(symbol_ids, dtype=np.uint32))
    return run_atomic_package_market(
        timestamps_ns=view.timestamps_ns,
        opens=view.opens,
        highs=view.highs,
        lows=view.lows,
        closes=view.closes,
        volumes=view.volumes,
        funding=view.funding_rates,
        funding_mask=view.funding_event_mask,
        symbols=view.symbols,
        contract_sizes=arrays["contract_size"],
        leverages=arrays["leverage"],
        fee_rates=arrays["fee_rate"],
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
        command_bar=command_bar,
        package_id=package_id,
        order_ids=order_ids,
        symbol_ids=symbol_ids_array,
        signed_qty=signed_qty,
        source_age_ns=source_age_ns,
        venue_codes=venue_codes,
        venue_sequence=venue_sequence,
        min_qty=arrays["min_qty"][symbol_ids_array],
        min_notional=arrays["min_notional"][symbol_ids_array],
        max_staleness_ns=max_staleness_ns,
        report_level=report_level,
        cache=cache,
    )


def run_bounded_package_market_v2(
    *,
    market: PreparedMarketHandleV2,
    instruments: InstrumentRegistryV2,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    **package_kwargs: object,
) -> RustNativeMarketExecution:
    """Run a bounded package from the canonical V2 market/instrument pair."""

    view, arrays = _v2_market_registry_inputs(market=market, instruments=instruments)
    return run_bounded_package_market(
        timestamps_ns=view.timestamps_ns,
        opens=view.opens,
        highs=view.highs,
        lows=view.lows,
        closes=view.closes,
        volumes=view.volumes,
        funding=view.funding_rates,
        funding_mask=view.funding_event_mask,
        symbols=view.symbols,
        contract_sizes=arrays["contract_size"],
        leverages=arrays["leverage"],
        fee_rates=arrays["fee_rate"],
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
        **package_kwargs,
    )


def run_bounded_package_market_scenarios_v2(
    *,
    market: PreparedMarketHandleV2,
    instruments: InstrumentRegistryV2,
    initial_capital: float,
    maintenance_ratio: float,
    slippage_rate: float,
    use_funding: bool,
    **package_kwargs: object,
) -> RustNativeMarketExecution:
    """Run scalar package scenarios from the canonical V2 source pair."""

    view, arrays = _v2_market_registry_inputs(market=market, instruments=instruments)
    return run_bounded_package_market_scenarios(
        timestamps_ns=view.timestamps_ns,
        opens=view.opens,
        highs=view.highs,
        lows=view.lows,
        closes=view.closes,
        volumes=view.volumes,
        funding=view.funding_rates,
        funding_mask=view.funding_event_mask,
        symbols=view.symbols,
        contract_sizes=arrays["contract_size"],
        leverages=arrays["leverage"],
        fee_rates=arrays["fee_rate"],
        initial_capital=initial_capital,
        maintenance_ratio=maintenance_ratio,
        slippage_rate=slippage_rate,
        use_funding=use_funding,
        **package_kwargs,
    )


__all__ = [
    "RustNativeMarketExecution",
    "run_atomic_package_market",
    "run_atomic_package_market_v2",
    "run_bounded_package_market",
    "run_bounded_package_market_scenarios",
    "run_bounded_package_market_v2",
    "run_bounded_package_market_scenarios_v2",
    "run_portfolio_target_market",
    "run_portfolio_target_market_v2",
    "run_shared_portfolio_target_market",
    "run_shared_portfolio_target_market_v2",
]
