"""Capacity disclosure for the existing shared gross-cross account."""

import numpy as np


def capacity_metadata(initial_capital, leverages, symbols):
    values = np.asarray(leverages, dtype=np.float64)
    homogeneous = bool(len(values) and np.all(values == values[0]))
    return {
        "initial_buying_power": float(initial_capital * values[0]) if homogeneous else None,
        "buying_power_model": "equity_times_common_leverage" if homogeneous else "allocation_dependent",
        "buying_power_reason": None if homogeneous else "heterogeneous leverage has no allocation-independent notional capacity",
        "leverage_by_symbol": {symbol: float(values[j]) for j, symbol in enumerate(symbols)},
        "result_leverage_role": "common_leverage" if homogeneous else "legacy_arithmetic_mean_summary_not_capacity",
        "margin_model": "gross_cross",
        "oms_mode": "netting",
    }
