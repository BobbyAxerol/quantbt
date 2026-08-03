"""
Option-domain report helpers.

These functions summarize `OptionBacktestResult` artifacts without recomputing
ledger accounting or execution PnL.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd


def option_run_manifest(result) -> Dict:
    """Return the option run manifest stored by `NativeOptionBackend`."""
    return dict(getattr(result, "run_manifest", None) or result.metadata.get("run_manifest", {}))


def option_attribution_report(result) -> pd.DataFrame:
    """Return the option attribution table, or an empty DataFrame."""
    report = getattr(result, "attribution_report", None)
    if report is None:
        report = result.metadata.get("attribution_report")
    return report.copy() if isinstance(report, pd.DataFrame) else pd.DataFrame()


def option_report_bundle(result) -> Dict[str, pd.DataFrame]:
    """Return all standard option audit tables as a dictionary."""
    names = (
        "fills_report",
        "packages_report",
        "cash_report",
        "marks_report",
        "greeks_report",
        "settlements_report",
        "margin_report",
        "attribution_report",
    )
    out = {}
    for name in names:
        report = getattr(result, name, None)
        if report is None:
            report = result.metadata.get(name)
        out[name] = report.copy() if isinstance(report, pd.DataFrame) else pd.DataFrame()
    return out
