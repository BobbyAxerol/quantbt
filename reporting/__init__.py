"""Reporting helpers for QuantBT result artifacts."""

from .arbitrage_audit import build_arbitrage_domain_audit, compare_native_arbitrage_results
from .nautilus_bundle import export_nautilus_report_bundle
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
    "build_portfolio_domain_audit",
    "build_portfolio_nautilus_position_report",
    "build_portfolio_nautilus_validation_report",
    "compare_native_arbitrage_results",
    "export_nautilus_report_bundle",
    "summarize_native_nautilus_parity_report",
]
