"""Certified Rust-owned market routes for bounded portfolio/package tapes.

These helpers deliberately do not replace :class:`NativePortfolioBackend` or
the general Python package executor.  They expose the two exact contracts that
are currently promoted by the native event runtime:

* bar-major ``target_units`` with all-or-none rebalance admission; and
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


__all__ = [
    "RustNativeMarketExecution",
    "run_atomic_package_market",
    "run_portfolio_target_market",
]
