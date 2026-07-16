"""
Portfolio domain contracts for the native portfolio upgrade.

This module does not execute a backtest.  It defines the institutional-grade
contract that the future native portfolio engine must satisfy while legacy
portfolio behavior remains the compatibility oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Optional, Set

import numpy as np
import pandas as pd

from ..reporting.portfolio_audit import build_portfolio_domain_audit


class PortfolioMode(str, Enum):
    LONGSHORT = "longshort"
    MARKET_NEUTRAL = "market_neutral"
    DIRECTIONAL = "directional"
    EQUAL_WEIGHT = "equal_weight"
    RISK_PARITY = "risk_parity"
    BETA_NEUTRAL = "beta_neutral"


class PortfolioSizingMode(str, Enum):
    SIGNAL_NOTIONAL = "signal_notional"
    SIGNAL = "signal"
    NOTIONAL = "notional"
    UNIT = "unit"
    PCT_EQUITY = "%_equity"
    TARGET_WEIGHT = "target_weight"
    TARGET_NOTIONAL = "target_notional"
    TARGET_UNITS = "target_units"
    FIXED_NOTIONAL = "fixed_notional"
    GROSS_EXPOSURE = "gross_exposure"
    NET_EXPOSURE = "net_exposure"
    DCA_LADDER = "dca_ladder"


class PortfolioRebalancePolicy(str, Enum):
    ON_SIGNAL_CHANGE = "on_signal_change"
    EVERY_BAR = "every_bar"
    THRESHOLD = "threshold"
    SCHEDULED = "scheduled"


LEGACY_PORTFOLIO_MODES: Set[str] = {mode.value for mode in PortfolioMode}
LEGACY_COMPATIBLE_PORTFOLIO_MODES: Set[str] = {
    PortfolioMode.LONGSHORT.value,
    PortfolioMode.MARKET_NEUTRAL.value,
    PortfolioMode.DIRECTIONAL.value,
    PortfolioMode.EQUAL_WEIGHT.value,
}
LEGACY_PORTFOLIO_SIZING_MODES: Set[str] = {
    PortfolioSizingMode.SIGNAL_NOTIONAL.value,
    PortfolioSizingMode.SIGNAL.value,
    PortfolioSizingMode.NOTIONAL.value,
    PortfolioSizingMode.UNIT.value,
}
NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES: Set[str] = {mode.value for mode in PortfolioSizingMode}
NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES: Set[str] = {
    *LEGACY_PORTFOLIO_SIZING_MODES,
    PortfolioSizingMode.PCT_EQUITY.value,
    PortfolioSizingMode.TARGET_WEIGHT.value,
    PortfolioSizingMode.TARGET_NOTIONAL.value,
    PortfolioSizingMode.TARGET_UNITS.value,
    PortfolioSizingMode.FIXED_NOTIONAL.value,
    PortfolioSizingMode.GROSS_EXPOSURE.value,
    PortfolioSizingMode.NET_EXPOSURE.value,
}


@dataclass(frozen=True)
class PortfolioDomainSpec:
    """
    Declarative contract for a portfolio backtest.

    Phase 11 uses this as a validation layer around legacy portfolio results.
    Phase 11/native portfolio should use the same spec as its input contract.
    """

    mode: str = PortfolioMode.LONGSHORT.value
    sizing_mode: str = PortfolioSizingMode.SIGNAL_NOTIONAL.value
    rebalance_policy: str = PortfolioRebalancePolicy.ON_SIGNAL_CHANGE.value
    allow_short: bool = True
    require_gross_net_reports: bool = True
    require_symbol_pnl_report: bool = True
    require_margin_report: bool = True
    target_gross_exposure: Optional[float] = None
    target_net_exposure: Optional[float] = None
    max_gross_leverage: Optional[float] = None
    max_net_exposure_abs: Optional[float] = None
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        mode = normalize_portfolio_mode(self.mode)
        sizing = normalize_portfolio_sizing_mode(self.sizing_mode)
        rebalance = normalize_rebalance_policy(self.rebalance_policy)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "sizing_mode", sizing)
        object.__setattr__(self, "rebalance_policy", rebalance)

        if self.target_gross_exposure is not None and self.target_gross_exposure < 0.0:
            raise ValueError("target_gross_exposure must be >= 0")
        if self.max_gross_leverage is not None and self.max_gross_leverage < 0.0:
            raise ValueError("max_gross_leverage must be >= 0")
        if self.max_net_exposure_abs is not None and self.max_net_exposure_abs < 0.0:
            raise ValueError("max_net_exposure_abs must be >= 0")

    @property
    def legacy_compatible(self) -> bool:
        return self.mode in LEGACY_COMPATIBLE_PORTFOLIO_MODES and self.sizing_mode in LEGACY_PORTFOLIO_SIZING_MODES

    @property
    def native_planned(self) -> bool:
        return self.mode in LEGACY_PORTFOLIO_MODES and self.sizing_mode in NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES


def normalize_portfolio_mode(mode: str) -> str:
    value = str(mode).lower().strip()
    aliases = {
        "long_short": PortfolioMode.LONGSHORT.value,
        "long/short": PortfolioMode.LONGSHORT.value,
        "dollar_neutral": PortfolioMode.MARKET_NEUTRAL.value,
        "marketneutral": PortfolioMode.MARKET_NEUTRAL.value,
        "equal": PortfolioMode.EQUAL_WEIGHT.value,
        "equalweight": PortfolioMode.EQUAL_WEIGHT.value,
        "riskparity": PortfolioMode.RISK_PARITY.value,
        "inverse_vol": PortfolioMode.RISK_PARITY.value,
        "inverse_volatility": PortfolioMode.RISK_PARITY.value,
        "betaneutral": PortfolioMode.BETA_NEUTRAL.value,
        "beta_neutral_basic": PortfolioMode.BETA_NEUTRAL.value,
    }
    value = aliases.get(value, value)
    if value not in LEGACY_PORTFOLIO_MODES:
        raise ValueError(f"unsupported portfolio mode: {mode!r}")
    return value


def normalize_portfolio_sizing_mode(mode: str) -> str:
    value = str(mode).lower().strip()
    aliases = {
        "pct_equity": PortfolioSizingMode.PCT_EQUITY.value,
        "percent_equity": PortfolioSizingMode.PCT_EQUITY.value,
        "signal_notional": PortfolioSizingMode.SIGNAL_NOTIONAL.value,
        "signal": PortfolioSizingMode.SIGNAL.value,
        "units": PortfolioSizingMode.TARGET_UNITS.value,
        "target_unit": PortfolioSizingMode.TARGET_UNITS.value,
        "dollar": PortfolioSizingMode.NOTIONAL.value,
        "portfolio_target_weight": PortfolioSizingMode.TARGET_WEIGHT.value,
        "portfolio_target_notional": PortfolioSizingMode.TARGET_NOTIONAL.value,
        "portfolio_target_units": PortfolioSizingMode.TARGET_UNITS.value,
        "target_weights": PortfolioSizingMode.TARGET_WEIGHT.value,
        "target_notionals": PortfolioSizingMode.TARGET_NOTIONAL.value,
        "target_unit": PortfolioSizingMode.TARGET_UNITS.value,
        "gross": PortfolioSizingMode.GROSS_EXPOSURE.value,
        "net": PortfolioSizingMode.NET_EXPOSURE.value,
    }
    value = aliases.get(value, value)
    if value not in NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES:
        raise ValueError(f"unsupported portfolio sizing mode: {mode!r}")
    return value


def normalize_rebalance_policy(policy: str) -> str:
    value = str(policy).lower().strip()
    aliases = {
        "on_transition": PortfolioRebalancePolicy.ON_SIGNAL_CHANGE.value,
        "signal_change": PortfolioRebalancePolicy.ON_SIGNAL_CHANGE.value,
        "bar": PortfolioRebalancePolicy.EVERY_BAR.value,
    }
    value = aliases.get(value, value)
    valid = {item.value for item in PortfolioRebalancePolicy}
    if value not in valid:
        raise ValueError(f"unsupported portfolio rebalance policy: {policy!r}")
    return value


def portfolio_capability_matrix() -> pd.DataFrame:
    rows = []
    for mode in sorted(LEGACY_PORTFOLIO_MODES):
        for sizing in sorted(NATIVE_PORTFOLIO_ROADMAP_SIZING_MODES):
            rows.append(
                {
                    "mode": mode,
                    "sizing_mode": sizing,
                    "legacy_supported": mode in LEGACY_COMPATIBLE_PORTFOLIO_MODES
                    and sizing in LEGACY_PORTFOLIO_SIZING_MODES,
                    "native_supported": sizing in NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES,
                    "native_roadmap": True,
                    "nautilus_validation_phase": "phase_4",
                }
            )
    return pd.DataFrame(rows)


def validate_portfolio_result_contract(
    result,
    spec: PortfolioDomainSpec,
    *,
    tolerance: float = 1e-8,
    raise_on_fail: bool = False,
) -> Dict:
    """
    Validate a completed portfolio result against the Phase 11 domain contract.

    The report combines accounting reconciliation from
    `build_portfolio_domain_audit` with mode-specific exposure invariants.
    """
    metadata = getattr(result, "metadata", {}) or {}
    exposure = _frame(metadata.get("exposure_report"))
    accepted_notional = _frame(metadata.get("accepted_notional_report"))
    accepted_units = _frame(metadata.get("accepted_units_report"))
    symbol_pnl = _frame(metadata.get("symbol_pnl_report"))
    base_audit = build_portfolio_domain_audit(result, tolerance=tolerance, raise_on_fail=False)

    checks = {
        "base_accounting_audit": bool(base_audit.get("passed")),
        "mode_matches_spec": metadata.get("mode") == spec.mode,
        "sizing_matches_spec": metadata.get("hedge_type") == spec.sizing_mode,
        "has_exposure_report": not exposure.empty if spec.require_gross_net_reports else True,
        "has_symbol_pnl_report": not symbol_pnl.empty if spec.require_symbol_pnl_report else True,
        "has_margin_columns": _has_columns(exposure, {"initial_margin", "maintenance_margin"}) if spec.require_margin_report else True,
        "short_policy_respected": _short_policy_respected(accepted_units, spec.allow_short),
        "gross_leverage_limit_respected": _max_column(exposure, "gross_leverage") <= spec.max_gross_leverage + tolerance
        if spec.max_gross_leverage is not None and not exposure.empty
        else True,
        "net_exposure_limit_respected": _max_abs_column(exposure, "net_exposure_pct") <= spec.max_net_exposure_abs + tolerance
        if spec.max_net_exposure_abs is not None and not exposure.empty
        else True,
    }
    checks.update(_mode_specific_checks(spec.mode, exposure, accepted_notional, tolerance))

    passed = all(bool(v) for v in checks.values())
    report = {
        "status": "pass" if passed else "fail",
        "passed": passed,
        "spec": {
            "mode": spec.mode,
            "sizing_mode": spec.sizing_mode,
            "rebalance_policy": spec.rebalance_policy,
            "legacy_compatible": spec.legacy_compatible,
            "native_planned": spec.native_planned,
        },
        "checks": checks,
        "base_audit": base_audit,
    }
    if raise_on_fail and not passed:
        raise AssertionError(f"portfolio contract validation failed: {report}")
    return report


def _mode_specific_checks(mode: str, exposure: pd.DataFrame, accepted_notional: pd.DataFrame, tolerance: float) -> Dict[str, bool]:
    if exposure.empty:
        return {
            "market_neutral_balanced": mode != PortfolioMode.MARKET_NEUTRAL.value,
            "directional_single_active": mode != PortfolioMode.DIRECTIONAL.value,
            "equal_weight_balanced": mode != PortfolioMode.EQUAL_WEIGHT.value,
            "risk_parity_balanced": mode != PortfolioMode.RISK_PARITY.value,
            "beta_neutral_balanced": mode != PortfolioMode.BETA_NEUTRAL.value,
        }

    if mode == PortfolioMode.MARKET_NEUTRAL.value:
        active = exposure["gross_notional"].abs() > tolerance
        residual = (exposure.loc[active, "long_notional"] - exposure.loc[active, "short_notional"]).abs()
        return {
            "market_neutral_balanced": residual.empty or bool(residual.max() <= tolerance),
            "directional_single_active": True,
            "equal_weight_balanced": True,
            "risk_parity_balanced": True,
            "beta_neutral_balanced": True,
        }

    if mode == PortfolioMode.DIRECTIONAL.value:
        if accepted_notional.empty:
            single_active = False
        else:
            active_counts = (accepted_notional.abs() > tolerance).sum(axis=1)
            single_active = bool((active_counts <= 1).all())
        return {
            "market_neutral_balanced": True,
            "directional_single_active": single_active,
            "equal_weight_balanced": True,
            "risk_parity_balanced": True,
            "beta_neutral_balanced": True,
        }

    if mode == PortfolioMode.EQUAL_WEIGHT.value:
        balanced = _equal_weight_balanced(accepted_notional, tolerance)
        return {
            "market_neutral_balanced": True,
            "directional_single_active": True,
            "equal_weight_balanced": balanced,
            "risk_parity_balanced": True,
            "beta_neutral_balanced": True,
        }

    if mode == PortfolioMode.RISK_PARITY.value:
        risk_ok = _risk_parity_balanced(_frame_from_exposure_attr(exposure, "risk_contribution_report"), tolerance)
        return {
            "market_neutral_balanced": True,
            "directional_single_active": True,
            "equal_weight_balanced": True,
            "risk_parity_balanced": risk_ok,
            "beta_neutral_balanced": True,
        }

    if mode == PortfolioMode.BETA_NEUTRAL.value:
        if "beta_exposure_notional" in exposure:
            active = exposure["gross_notional"].abs() > tolerance
            beta_abs = exposure.loc[active, "beta_exposure_notional"].abs()
            beta_ok = beta_abs.empty or bool(beta_abs.max() <= tolerance)
        else:
            beta_ok = False
        return {
            "market_neutral_balanced": True,
            "directional_single_active": True,
            "equal_weight_balanced": True,
            "risk_parity_balanced": True,
            "beta_neutral_balanced": beta_ok,
        }

    return {
        "market_neutral_balanced": True,
        "directional_single_active": True,
        "equal_weight_balanced": True,
        "risk_parity_balanced": True,
        "beta_neutral_balanced": True,
    }


def _equal_weight_balanced(accepted_notional: pd.DataFrame, tolerance: float) -> bool:
    if accepted_notional.empty:
        return False
    abs_notional = accepted_notional.abs()
    for _, row in abs_notional.iterrows():
        active = row[row > tolerance]
        if len(active) <= 1:
            continue
        if float(active.max() - active.min()) > tolerance:
            return False
    return True


def _short_policy_respected(accepted_units: pd.DataFrame, allow_short: bool) -> bool:
    if allow_short or accepted_units.empty:
        return True
    return bool((accepted_units >= -1e-12).all().all())


def _has_columns(frame: pd.DataFrame, columns: Iterable[str]) -> bool:
    return set(columns).issubset(frame.columns)


def _max_column(frame: pd.DataFrame, column: str) -> float:
    if column not in frame:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.max()) if not values.empty else 0.0


def _max_abs_column(frame: pd.DataFrame, column: str) -> float:
    if column not in frame:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().abs()
    return float(values.max()) if not values.empty else 0.0


def _frame(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _frame_from_exposure_attr(exposure: pd.DataFrame, attr_name: str) -> pd.DataFrame:
    value = exposure.attrs.get(attr_name) if isinstance(exposure, pd.DataFrame) else None
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _risk_parity_balanced(risk_contribution: pd.DataFrame, tolerance: float) -> bool:
    if risk_contribution.empty:
        return False
    for _, row in risk_contribution.iterrows():
        active = row[row > tolerance]
        if len(active) <= 1:
            continue
        if float(active.max() - active.min()) > max(tolerance, 1e-6):
            return False
    return True
