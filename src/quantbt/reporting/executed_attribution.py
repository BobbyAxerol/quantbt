"""Cold leg reports from recorded costs and accepted position marks."""

import numpy as np
import pandas as pd


def executed_leg_pnl_report(idx, symbols, roles, result, closes, contract_sizes):
    costs = result.metadata.pop("_executed_account_attribution", None)
    if costs is None or costs.shape != (len(idx), len(symbols), 4):
        raise ValueError("leg report requires authoritative executed account attribution")
    rows = []
    for j, symbol in enumerate(symbols):
        units = result.positions[f"Position_{symbol}"].to_numpy(dtype=float)
        prices = closes[symbol].to_numpy(dtype=float)
        size = float(contract_sizes[symbol])
        pnl = np.zeros(len(idx))
        pnl[1:] = units[:-1] * np.diff(prices) * size
        fee, slippage, funding, liquidation = costs[:, j].T
        net = pnl - fee - slippage - funding - liquidation
        rows.append(pd.DataFrame(dict(timestamp=idx, symbol=symbol, role=roles.get(symbol, "leg"),
            units=units, close=prices, notional=np.abs(units) * prices * size,
            price_pnl=pnl, fill_pnl=-slippage, fee=fee, funding_pnl=-funding,
            liquidation_pnl=-liquidation, total_pnl=net, cumulative_pnl=np.cumsum(net))))
    report = pd.concat(rows, ignore_index=True).sort_values("timestamp", kind="stable").reset_index(drop=True)
    actual = result.equity.to_numpy(dtype=float)
    expected = np.r_[actual[0] - result.initial_capital, np.diff(actual)]
    observed = report.groupby("timestamp", sort=True).total_pnl.sum().reindex(idx).to_numpy()
    if not np.allclose(observed, expected, rtol=1e-10, atol=1e-8):
        raise ValueError("executed leg attribution does not reconcile to account equity")
    return report
