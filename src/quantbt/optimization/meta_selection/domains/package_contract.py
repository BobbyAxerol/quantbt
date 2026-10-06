"""Bounded original package admission and account evidence, never PnL proxies."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..common import MetaRecordError, canonical, digest
from .portfolio_contract import validate_portfolio_market


@dataclass(frozen=True, slots=True)
class PackageExecutionContract:
    universe: tuple[str, ...]
    package_kind: str
    semantic_id: str
    backend: str = "native_event"
    timing: str = "original_frozen_package_execution"
    diagnostic_account: str = "reset_flat"
    final_account: str = "carry_position"


def package_execution_contract(config, wf_config, *, symbols=None):
    from ....core.schema import BasketSpec, BasketExecutionPolicy
    from ....core.arbitrage import (BasisArbitrageSpec, StatArbPairSpec, ContractType,
        SizingPolicyKind, PackageExecutionKind, OrderType, TimeInForce,
        HedgePolicyKind, MarginModelKind, LifecycleModelKind, CarryModelKind,
        CostModelKind, SignalModelKind)

    if config.backend not in {"auto", "native_event"}:
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: package final and IS authority requires native_event")
    if wf_config.metadata.get("native_prepared_wfo", "off") == "require":
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: scalar Rust prepared scorer is not a package account")
    if any(getattr(config, n) is not None for n in
           ("instruments", "qty_step", "lot_size", "slot_size", "min_qty", "min_notional")):
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: endpoint quantity knobs are not bound by original package runtime; use qualified leg constraints")
    spec = config.basket if wf_config.target_mode == "basket" else config.arbitrage_spec
    if isinstance(spec, BasketSpec) and wf_config.target_mode == "basket":
        if (not spec.freeze_hedge or spec.hedged_margin_offset != 0
                or spec.execution_policy is not BasketExecutionPolicy.BEST_EFFORT):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: basket supports frozen best-effort, no margin offset")
    elif type(spec) in {BasisArbitrageSpec, StatArbPairSpec} and wf_config.target_mode == "arbitrage":
        if (spec.hedge_policy.kind is not HedgePolicyKind.BASE_QTY_EQUAL
                or spec.margin_model.kind is not MarginModelKind.GROSS
                or spec.margin_model.hedged_margin_offset != 0
                or spec.margin_model.maintenance_ratio is not None
                or spec.lifecycle_model.kind is not LifecycleModelKind.OPEN_ENDED
                or spec.carry_model.kind not in {CarryModelKind.NONE, CarryModelKind.FUNDING}
                or spec.carry_model.borrow_rate != 0
                or spec.cost_model.kind is not CostModelKind.PER_LEG_FEE
                or any(getattr(spec.cost_model, n) != 0 for n in ("fee_bps", "slippage_bps", "spread_bps"))
                or spec.signal_model.kind is not SignalModelKind.EXTERNAL
                or any(l.tick_size != 0 for l in spec.legs)
                or (type(spec) is StatArbPairSpec and (
                    spec.sizing_policy.kind is not SizingPolicyKind.TARGET_GROSS_NOTIONAL
                    or any(any(getattr(l, n) != 0 for n in ("qty_step", "min_qty", "min_notional"))
                           for l in spec.legs)))):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: unqualified hedge, carry, margin, cost or leg constraint semantics")
        if (not spec.hedge_policy.freeze_on_entry
                or spec.hedge_policy.rebalance_interval is not None
                or spec.hedge_policy.rebalance_threshold is not None
                or any(l.contract_type is not ContractType.LINEAR or l.expiry is not None for l in spec.legs)
                or spec.sizing_policy.kind not in {SizingPolicyKind.TARGET_NOTIONAL_TO_BASE_QTY,
                                                  SizingPolicyKind.TARGET_GROSS_NOTIONAL,
                                                  SizingPolicyKind.TARGET_BASE_QTY}
                or spec.execution_policy.order_type is not OrderType.MARKET
                or spec.execution_policy.tif is not TimeInForce.IOC
                or spec.execution_policy.kind not in {PackageExecutionKind.ATOMIC_ALL_OR_NONE,
                                                       PackageExecutionKind.BEST_EFFORT}):
            raise MetaRecordError("META_ROUTE_UNSUPPORTED: bounded linear frozen non-expiring market/IOC package required")
    else:
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: unqualified package spec")
    if any(not np.isfinite(l.ratio) or l.ratio == 0 for l in spec.legs):
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: finite nonzero leg ratios required")
    universe = tuple(symbols if symbols is not None else (config.symbols or ()))
    if (not universe or universe != tuple(l.symbol for l in spec.legs)
            or len(universe) != len(set(universe))):
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: explicit ordered package leg universe required")
    semantic = digest(dict(spec=spec, universe=universe, account_metadata=config.account.metadata,
                           execution=config.execution))
    return PackageExecutionContract(universe, type(spec).__name__, semantic)


def validate_package_market(data, index, symbols):
    validate_portfolio_market(data, index, symbols)
    if any(not np.isfinite(data[s][["high", "low", "close"]].to_numpy(dtype=float)).all()
           for s in symbols):
        raise MetaRecordError("META_ROUTE_UNSUPPORTED: package missing/stale calendar policy not qualified")


def validate_package_payload(payload, index):
    if (not isinstance(payload, pd.Series) or not payload.index.equals(index)
            or not np.isfinite(payload.to_numpy(dtype=float)).all()):
        raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: exact finite package signal Series required")


def update_package_witness(witness, result):
    from ....core.results import BacktestResultV2
    if not isinstance(result, BacktestResultV2) or result.metadata.get("backend") != "native_event":
        raise MetaRecordError("META_DOMAIN_RESULT_UNBOUND: original native event package result required")
    fields = {"fees": result.fees, "funding": result.funding, "margin": result.margin,
              "diagnostics": result.diagnostics}
    witness.update(digest({"original_package_fills_v1": result.fills}).encode())
    for name in ("basket_target_units", "package_target_units", "package_rejection_report",
                 "leg_pnl_report", "package_pnl_report"):
        if name in result.metadata:
            fields[name] = result.metadata[name]
    if not any(n in fields for n in ("basket_target_units", "package_target_units")):
        raise MetaRecordError("META_DOMAIN_RESULT_UNBOUND: original package target plan missing")
    for name, value in fields.items():
        if not isinstance(value, (pd.Series, pd.DataFrame)):
            raise MetaRecordError(f"META_DOMAIN_RESULT_UNBOUND: package account buffer missing: {name}")
        witness.update(digest(dict(package_account_v1=name, shape=value.shape,
            columns=list(value.columns) if isinstance(value, pd.DataFrame) else None,
            dtypes=[str(d) for d in value.dtypes] if isinstance(value, pd.DataFrame) else [str(value.dtype)])).encode())
        hashed = value
        if isinstance(value, pd.DataFrame):
            objects = value.select_dtypes(include="object")
            if len(objects.columns):
                hashed = value.copy(deep=False)
                for column in objects.columns:
                    hashed[column] = objects[column].map(lambda cell: canonical(cell)
                        if isinstance(cell, (dict, list, tuple)) else cell)
        witness.update(pd.util.hash_pandas_object(hashed, index=True).to_numpy().tobytes())
