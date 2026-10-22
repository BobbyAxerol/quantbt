"""Requested, observed-equity plots. Matplotlib is loaded only inside the call."""

from dataclasses import replace

from .public import _build_completed_report


def plot_reporting_account(result, request, *, scope="auto", theme="dark", figsize=(14, 6)):
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    if theme not in {"dark", "light"}:
        raise ValueError("theme must be dark or light")
    request = replace(request, retain_episodes=True)
    report, obs = _build_completed_report(result, request, scope=scope)
    account = dict(report.groups).get("account_period")
    if account is None:
        raise LookupError(dict(report.unavailable)["account_period"])
    times = pd.to_datetime(obs.times_ns, utc=True)
    # Include the declared starting equity; first-bar fees are not erased.
    plot_times = times.insert(0, pd.Timestamp(request.account.baseline_time_ns, tz="UTC"))
    values = np.r_[request.account.baseline_equity, obs.equity]
    high = np.maximum.accumulate(values)
    drawdown = 100 * (1 - values / high)
    with plt.style.context("dark_background" if theme == "dark" else "default"):
        fig, (equity_ax, dd_ax) = plt.subplots(2, 1, sharex=True, figsize=figsize,
            layout="constrained", gridspec_kw={"height_ratios": [2, 1]})
        equity_ax.plot(plot_times, values, color="#25a5a1", linewidth=1.3, label="Observed equity")
        dd_ax.fill_between(plot_times, 0, drawdown, color="#d45165", alpha=.3, label="Observed drawdown")
        dd_ax.plot(plot_times, drawdown, color="#d45165", linewidth=1)
        for row in account.episodes.to_rows():
            if not row["recovered"]:
                start = pd.Timestamp(row["peak_time_ns"], tz="UTC")
                end = pd.Timestamp(row["end_time_ns"], tz="UTC")
                dd_ax.axvspan(start, end, color="#d99b31", alpha=.12, label="Open / censored episode")
        equity_ax.set_ylabel(f"Equity ({request.account.currency})")
        dd_ax.set_ylabel("Drawdown (%)")
        dd_ax.invert_yaxis()
        dd_ax.set_xlabel("Recorded time (UTC)")
        equity_ax.set_title(f"{request.account.scope.title()} | {request.account.equity_clock} | observed extrema only", fontsize=12)
        for ax in (equity_ax, dd_ax):
            ax.grid(alpha=.2)
            handles, labels = ax.get_legend_handles_labels()
            unique = dict(zip(labels, handles))
            ax.legend(unique.values(), unique.keys(), loc="upper left", fontsize=9)
        fig.set_layout_engine("constrained")
    return fig
