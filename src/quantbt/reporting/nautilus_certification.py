"""Nautilus certification artifact helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd

from ..core.results import BacktestResultV2
from .parity import build_native_nautilus_parity_report, summarize_native_nautilus_parity_report


@dataclass(frozen=True)
class NautilusToleranceProfile:
    """Tolerance contract for native-vs-Nautilus certification artifacts."""

    fill_price_tolerance: float = 1e-9
    fee_tolerance: float = 1e-9
    position_tolerance: float = 1e-9
    equity_tolerance: float = 1e-6
    quantity_tolerance: float = 1e-9
    slippage_tolerance: float = 1e-9


def build_nautilus_certification_profile(
    native_result: Optional[BacktestResultV2],
    nautilus_result: BacktestResultV2,
    *,
    tolerance: NautilusToleranceProfile | Dict[str, float] | None = None,
    workflow: str = "nautilus",
) -> Dict[str, Any]:
    """
    Build a compact tolerance profile for a native-vs-Nautilus run.

    The profile is deliberately report-layer only. It never changes engine
    accounting and is suitable for saved stakeholder bundles.
    """
    tol = _coerce_tolerance(tolerance)
    if native_result is None:
        return {
            "workflow": workflow,
            "status": "reference_missing",
            "passed": False,
            "reason": "native reference result is required for tolerance certification",
            "tolerance": asdict(tol),
            "checks": {},
        }

    parity = build_native_nautilus_parity_report(native_result, nautilus_result)
    summary = summarize_native_nautilus_parity_report(
        parity,
        fill_price_tolerance=tol.fill_price_tolerance,
        fee_tolerance=tol.fee_tolerance,
        position_tolerance=tol.position_tolerance,
        equity_tolerance=tol.equity_tolerance,
    )
    quantity_diff = _max_abs_quantity_diff(native_result, nautilus_result)
    final_equity_diff = _final_equity_diff(native_result, nautilus_result)
    max_equity_diff = max(float(summary.get("max_abs_equity_diff", 0.0)), final_equity_diff)
    slippage_diff = float(summary.get("max_abs_fill_price_diff", 0.0))
    checks = {
        "fill_price_within_tolerance": float(summary["max_abs_fill_price_diff"]) <= tol.fill_price_tolerance,
        "fee_within_tolerance": float(summary["max_abs_fee_diff"]) <= tol.fee_tolerance,
        "position_within_tolerance": float(summary["max_abs_position_diff"]) <= tol.position_tolerance,
        "equity_within_tolerance": max_equity_diff <= tol.equity_tolerance,
        "quantity_within_tolerance": quantity_diff <= tol.quantity_tolerance,
        "slippage_within_tolerance": slippage_diff <= tol.slippage_tolerance,
    }
    passed = bool(all(checks.values()))
    status = "pass" if passed else _profile_status(checks)
    return {
        "workflow": workflow,
        "status": status,
        "passed": passed,
        "tolerance": asdict(tol),
        "checks": checks,
        "summary": summary,
        "max_abs_quantity_diff": float(quantity_diff),
        "max_abs_final_equity_diff": float(final_equity_diff),
        "max_abs_equity_diff_including_final": float(max_equity_diff),
        "max_abs_slippage_proxy_diff": float(slippage_diff),
        "rows": int(len(parity)),
    }


def write_nautilus_certification_artifacts(
    *,
    native_result: Optional[BacktestResultV2],
    nautilus_result: BacktestResultV2,
    report_dir: str | Path,
    workflow: str,
    tolerance: NautilusToleranceProfile | Dict[str, float] | None = None,
    known_differences: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Write parity, tolerance, known-difference, and summary files into a bundle.
    """
    path = Path(report_dir)
    path.mkdir(parents=True, exist_ok=True)
    tol = _coerce_tolerance(tolerance)
    parity = (
        build_native_nautilus_parity_report(native_result, nautilus_result)
        if native_result is not None
        else pd.DataFrame()
    )
    profile = build_nautilus_certification_profile(
        native_result=native_result,
        nautilus_result=nautilus_result,
        tolerance=tol,
        workflow=workflow,
    )
    differences = list(known_differences or ())
    parity_path = path / "native_vs_nautilus_parity.csv"
    profile_path = path / "tolerance_profile.json"
    known_path = path / "known_differences.md"
    summary_path = path / "certification_summary.json"

    parity.to_csv(parity_path, index=False)
    _write_json(profile_path, profile)
    known_path.write_text(_known_differences_markdown(workflow, differences), encoding="utf-8")
    summary = {
        "workflow": workflow,
        "status": profile["status"],
        "passed": profile["passed"],
        "report_dir": str(path),
        "files": {
            "native_vs_nautilus_parity": parity_path.name,
            "tolerance_profile": profile_path.name,
            "known_differences": known_path.name,
        },
        "known_differences_count": len(differences),
    }
    _write_json(summary_path, summary)
    return {
        **summary,
        "tolerance_profile": profile,
        "artifact_files": [parity_path.name, profile_path.name, known_path.name, summary_path.name],
    }


def _coerce_tolerance(value: NautilusToleranceProfile | Dict[str, float] | None) -> NautilusToleranceProfile:
    if value is None:
        return NautilusToleranceProfile()
    if isinstance(value, NautilusToleranceProfile):
        return value
    return NautilusToleranceProfile(**{key: float(val) for key, val in dict(value).items()})


def _profile_status(checks: Dict[str, bool]) -> str:
    if not checks.get("fill_price_within_tolerance", True) or not checks.get("quantity_within_tolerance", True):
        return "execution_diff"
    if not checks.get("position_within_tolerance", True):
        return "position_diff"
    if not checks.get("fee_within_tolerance", True) or not checks.get("equity_within_tolerance", True):
        return "accounting_diff"
    return "diff"


def _max_abs_quantity_diff(native_result: BacktestResultV2, nautilus_result: BacktestResultV2) -> float:
    native_qty = _fill_quantities(native_result)
    nautilus_qty = _fill_quantities(nautilus_result)
    n = max(len(native_qty), len(nautilus_qty))
    if n == 0:
        return 0.0
    left = np.zeros(n, dtype=float)
    right = np.zeros(n, dtype=float)
    left[: len(native_qty)] = native_qty
    right[: len(nautilus_qty)] = nautilus_qty
    return float(np.max(np.abs(left - right)))


def _final_equity_diff(native_result: BacktestResultV2, nautilus_result: BacktestResultV2) -> float:
    if len(native_result.equity) == 0 or len(nautilus_result.equity) == 0:
        return 0.0
    return float(abs(float(native_result.equity.iloc[-1]) - float(nautilus_result.equity.iloc[-1])))


def _fill_quantities(result: BacktestResultV2) -> np.ndarray:
    report = _frame((result.metadata or {}).get("fills_report"))
    if report.empty:
        report = _frame((result.metadata or {}).get("orders_report"))
    if not report.empty:
        if "status" in report:
            report = report[report["status"].astype(str).str.upper().eq("FILLED")]
        for col in ("filled_qty", "quantity", "qty"):
            if col in report:
                return pd.to_numeric(report[col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    fills = getattr(result, "fills", ())
    if fills:
        return np.asarray([float(getattr(fill, "qty", 0.0)) for fill in fills], dtype=float)
    return np.asarray([], dtype=float)


def _frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if value is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(value).copy()
    except Exception:
        return pd.DataFrame()


def _known_differences_markdown(workflow: str, differences: Sequence[str]) -> str:
    lines = [f"# Known Differences - {workflow}", ""]
    if differences:
        for item in differences:
            lines.append(f"- {item}")
    else:
        lines.append("- None recorded for this certification run.")
    lines.extend(
        [
            "",
            "These notes describe known adapter or venue-model differences. They do not override tolerance failures.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
