"""Reporting helpers for QuantBT result artifacts."""

from .arbitrage_audit import build_arbitrage_domain_audit, compare_native_arbitrage_results
from .nautilus_bundle import export_nautilus_report_bundle
from .nautilus_certification import (
    NautilusToleranceProfile,
    build_nautilus_certification_profile,
    write_nautilus_certification_artifacts,
)
from .nautilus_diagnostics import build_nautilus_pct_equity_diagnostic
from .parity import (
    build_native_nautilus_parity_report,
    build_nautilus_depth_execution_report,
    build_nautilus_depth_parity_summary,
    summarize_native_nautilus_parity_report,
)
from .portfolio_audit import build_portfolio_domain_audit
from .portfolio_nautilus import (
    build_portfolio_nautilus_position_report,
    build_portfolio_nautilus_validation_report,
)

__all__ = [
    "build_arbitrage_domain_audit",
    "build_native_nautilus_parity_report",
    "build_nautilus_depth_execution_report",
    "build_nautilus_depth_parity_summary",
    "build_nautilus_certification_profile",
    "build_nautilus_pct_equity_diagnostic",
    "build_portfolio_domain_audit",
    "build_portfolio_nautilus_position_report",
    "build_portfolio_nautilus_validation_report",
    "compare_native_arbitrage_results",
    "export_nautilus_report_bundle",
    "NautilusToleranceProfile",
    "summarize_native_nautilus_parity_report",
    "write_nautilus_certification_artifacts",
]
