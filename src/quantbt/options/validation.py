"""Monetary admission shared by the option execution and reporting paths."""

from __future__ import annotations

from math import isfinite
from typing import Mapping


def finite_number(value: float, field: str, *, minimum: float | None = None, positive: bool = False) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field} must be finite")
    if positive and number <= 0.0:
        raise ValueError(f"{field} must be > 0")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return number


def currency_amounts(values: Mapping[str, float], field: str, *, positive: bool = False) -> dict[str, float]:
    result = {}
    for currency, amount in values.items():
        key = str(currency).strip().upper()
        if not key or key in result:
            raise ValueError(f"{field} requires unique nonempty currency codes")
        result[key] = finite_number(amount, f"{field}[{key}]", positive=positive)
    return result


def conversion_rate(currency: str, rates: Mapping[str, float], reporting_currency: str) -> float:
    ccy = str(currency).upper()
    report = str(reporting_currency).upper()
    if ccy == report:
        if ccy in rates:
            finite_number(rates[ccy], f"conversion rate for {ccy}->{report}", positive=True)
        return 1.0
    if ccy not in rates:
        raise ValueError(f"missing conversion rate for {ccy}->{report}")
    return finite_number(rates[ccy], f"conversion rate for {ccy}->{report}", positive=True)
