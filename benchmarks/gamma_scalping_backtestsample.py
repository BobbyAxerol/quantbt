import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


PACKAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = PACKAGE_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from quantbt import (  # noqa: E402
    ExerciseStyle,
    OptionHedgeConfig,
    OptionHedgePolicyType,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    OptionPackageIntent,
    OptionPackageLeg,
    OptionPreparedRunCache,
    OrderSide,
    PremiumConvention,
    QuantBTEndpoint,
    SettlementStyle,
    run_delta_hedge_path,
)

def filter_atm_options(df: pd.DataFrame, iv_rank_threshold: float = 101.0,  # Tạm set cao để bypass IV rank check
                       use_rv_condition: bool = False,  # Thêm flag tắt RV > IV
                       rv_window: int = 20, iv_window: int = 252, min_oi: int = 50,  # Giảm OI tạm
                       min_dte: int = 2, max_dte: int = 14) -> pd.DataFrame:  # Mở rộng DTE
    df = df.copy()
    df['snapshot_time'] = pd.to_datetime(df['time']).dt.tz_localize(None).dt.normalize()
    df['expiration_date'] = pd.to_datetime(df['expiration']).dt.tz_localize(None).dt.normalize()
    df['spot_price'] = df['close']
    df['strike'] = df['strike'].astype(float).astype(int)
    df['mid_price'] = (df['bid'] + df['ask']) / 2
    df['dte'] = (df['expiration_date'] - df['snapshot_time']).dt.days

    df_sorted = df.sort_values('snapshot_time')
    df_sorted['log_return'] = np.log(df_sorted['spot_price'] / df_sorted['spot_price'].shift(1))
    df_sorted['rv'] = df_sorted['log_return'].ewm(span=rv_window).std() * np.sqrt(252)

    # IV rank chỉ tính nếu window đủ, nhưng bypass check
    df_sorted['iv_rank'] = df_sorted.groupby('snapshot_time')['implied_volatility'].transform(
        lambda x: x.rank(pct=True).iloc[-1] * 100 if len(x) > 0 else np.nan
    )  # Simple rank per day, hoặc giữ rolling nhưng skip NaN

    result_rows = []
    for (time_snapshot, underlying), group_df in df_sorted.groupby(['snapshot_time', 'underlying']):
        current_iv = group_df['implied_volatility'].mean()
        current_rv = group_df['rv'].mean() if 'rv' in group_df else np.nan  # Mean để tránh NaN
        current_iv_rank = group_df['iv_rank'].mean()

        # Bypass condition tạm
        if current_iv_rank >= iv_rank_threshold:
            continue  # Chỉ skip nếu rank cao, nhưng set threshold=101 để không skip
        if use_rv_condition and (pd.isna(current_rv) or current_rv <= current_iv):
            continue

        filtered_df = group_df[(group_df['dte'] >= min_dte) & (group_df['dte'] <= max_dte) & (group_df['open_interest'] >= min_oi)].copy()
        if filtered_df.empty:
            continue

        current_spot = filtered_df['spot_price'].iloc[0]
        paired_strikes = filtered_df.groupby(['expiration_date', 'strike']).filter(
            lambda x: set(x['type'].values) == {'call', 'put'}  # Chính xác hơn: đúng 1 call + 1 put
        )
        if paired_strikes.empty:
            continue

        paired_strikes['atm_distance'] = abs(paired_strikes['strike'] - current_spot)
        min_expiry_date = paired_strikes['dte'].min()  # Ưu tiên DTE nhỏ nhất
        best_expiry = paired_strikes[paired_strikes['dte'] == min_expiry_date]['expiration_date'].iloc[0]
        best_strikes = paired_strikes[paired_strikes['expiration_date'] == best_expiry]
        best_strike = best_strikes.loc[best_strikes['atm_distance'].idxmin(), 'strike']

        final_pair = filtered_df[
            (filtered_df['expiration_date'] == best_expiry) &
            (filtered_df['strike'] == best_strike) &
            (filtered_df['type'].isin(['call', 'put']))
        ]
        if len(final_pair) == 2:
            result_rows.append(final_pair)

    if result_rows:
        return pd.concat(result_rows, ignore_index=True)
    else:
        print("No straddle found after all filters - check data has paired call/put ATM short-dated")
        return pd.DataFrame(columns=df.columns)

def normalize_greeks(df_straddle: pd.DataFrame) -> pd.DataFrame:
    """
    Chuẩn hóa dựa vendor: delta/gamma *100 (per $1), theta per day USD, vega *100 (per 1.0 IV).
    """
    df = df_straddle.copy()
    df['delta_norm'] = df['delta'] * 100
    df['gamma_norm'] = df['gamma'] * 100
    df['theta_norm'] = df['theta']
    df['vega_norm'] = df['vega'] * 100
    return df

def aggregate_straddle_greeks(df: pd.DataFrame, position_type: str = 'long', notional: int = 100) -> pd.DataFrame:
    """
    Aggregate Greeks, scale by notional và sign.
    """
    sign = 1 if position_type == 'long' else -1
    df['time'] = pd.to_datetime(df['time'])
    df = df.set_index('time').sort_index()

    straddle_df = df.groupby(level=0).agg({
        'spot_price': 'first',
        'delta_norm': 'sum',
        'gamma_norm': 'sum',
        'theta_norm': 'sum',
        'vega_norm': 'sum',
        'implied_volatility': 'mean',
        'mid_price': 'sum',
        'dte': 'first'
    })

    for col in ['delta_norm', 'gamma_norm', 'theta_norm', 'vega_norm', 'mid_price']:
        straddle_df[col] *= sign * notional

    straddle_df.rename(columns={'implied_volatility': 'iv_straddle'}, inplace=True)
    return straddle_df

def simulate_paths(S0: float, mu: float, sigma_rv: float, T: float, dt: float, n_paths: int = 1000) -> np.ndarray:
    """GBM paths for backtest."""
    n_steps = int(T / dt)
    paths = np.zeros((n_paths, n_steps + 1))
    paths[:, 0] = S0
    for t in range(1, n_steps + 1):
        Z = np.random.standard_normal(n_paths)
        paths[:, t] = paths[:, t-1] * np.exp((mu - 0.5 * sigma_rv**2) * dt + sigma_rv * np.sqrt(dt) * Z)
    return paths

def gamma_pnl_factor(gamma_norm: float, S: float, rv: float, iv: float, dt: float, notional: int = 100) -> float:
    """Gamma P&L attribution."""
    return 0.5 * gamma_norm * S**2 * (rv**2 - iv**2) * dt * notional

def hedge_and_pnl(df_straddle: pd.DataFrame,
                  position_type: str = 'long',
                  notional: int = 100,
                  hedge_threshold: float = 0.05,
                  min_dte: int = 2,
                  sim_paths: bool = False,
                  option_commission_per_straddle: float = 3.0,   # USD per straddle round-trip (2 legs)
                  hedge_commission_per_unit_delta: float = 0.05  # USD per 1.0 delta rebalanced
                  ) -> pd.DataFrame:
    """
    P&L realistic với commission:
    - Option fee: khi open/rollover straddle mới
    - Hedge fee: mỗi lần re-hedge delta
    """
    df = normalize_greeks(df_straddle)
    df = aggregate_straddle_greeks(df, position_type, notional)

    df['portfolio_delta'] = df['delta_norm']
    df['pnl'] = 0.0
    df['cum_pnl'] = 0.0
    df['cum_return'] = 0.0
    df['gamma_attrib'] = 0.0
    df['hedge_pnl'] = 0.0
    df['mtm_change'] = 0.0
    df['commission'] = 0.0          # NEW: track commission
    df['commission_option'] = 0.0    # Phí từ option
    df['commission_hedge'] = 0.0     # Phí từ hedge

    if sim_paths:
        dt_base = 1/252
        T_total = len(df) * dt_base
        paths = simulate_paths(df['spot_price'].iloc[0], mu=0.1, sigma_rv=0.3, T=T_total, dt=dt_base, n_paths=1)
        df['spot_price'] = pd.Series(paths[0, :len(df)], index=df.index)

    if df.empty:
        return df

    # Initial capital = giá trị straddle khi entry (mid_price đầu tiên)
    initial_capital = abs(df.iloc[0]['mid_price'])  # abs để tránh âm nếu short
    if initial_capital == 0:
        initial_capital = 1.0  # Tránh chia 0

    current_position_value = df.iloc[0]['mid_price']
    prev_delta_for_hedge = df.iloc[0]['delta_norm']  # Để tính delta change khi hedge

    for i in range(1, len(df)):
        row_prev, row = df.iloc[i-1], df.iloc[i]

        S_prev, S = row_prev['spot_price'], row['spot_price']
        ds = S - S_prev
        dt_actual = (row.name - row_prev.name).days

        rv_actual = abs(ds / S_prev) * np.sqrt(252) if dt_actual > 0 and S_prev != 0 else 0.0

        commission_today = 0.0
        commission_option_today = 0.0
        commission_hedge_today = 0.0

        # === ROLLOVER: close old straddle, open new ===
        if row_prev['dte'] < min_dte:
            close_pnl = row_prev['mid_price'] - current_position_value
            df.at[row_prev.name, 'pnl'] += close_pnl
            df.at[row_prev.name, 'mtm_change'] = close_pnl

            # Commission khi rollover: open new straddle (2 legs)
            commission_option_today = option_commission_per_straddle * notional
            commission_today += commission_option_today

            # Reset position
            current_position_value = row['mid_price']
            prev_delta_for_hedge = row['delta_norm']  # Delta mới sau rollover
            df.at[row.name, 'portfolio_delta'] = row['delta_norm']
        else:
            current_position_value = row['mid_price']

        # === DAILY MTM CHANGE ===
        mtm_change = row['mid_price'] - row_prev['mid_price']
        df.at[row.name, 'mtm_change'] = mtm_change

        # === DISCRETE HEDGE ===
        prev_delta = row_prev['portfolio_delta']
        hedge_pnl = 0.0
        if abs(prev_delta) > hedge_threshold:
            hedge_pnl = -prev_delta * ds
            delta_change = abs(row['delta_norm'] - prev_delta)  # Amount rebalanced
            commission_hedge_today = delta_change * hedge_commission_per_unit_delta
            commission_today += commission_hedge_today

            df.at[row.name, 'portfolio_delta'] = row['delta_norm']  # Rebalanced to new delta
            prev_delta_for_hedge = row['delta_norm']

        df.at[row.name, 'hedge_pnl'] = hedge_pnl

        # === TOTAL PNL SAU COMMISSION ===
        gross_pnl = mtm_change + hedge_pnl
        net_pnl = gross_pnl - commission_today
        df.at[row.name, 'pnl'] = net_pnl


        # CUM PNL & CUM RETURN
        df.at[row.name, 'cum_pnl'] = df.at[row_prev.name, 'cum_pnl'] + net_pnl
        df.at[row.name, 'cum_return'] = df.at[row.name, 'cum_pnl'] / initial_capital  # % return

        # === COMMISSION BREAKDOWN ===
        df.at[row.name, 'commission'] = commission_today
        df.at[row.name, 'commission_option'] = commission_option_today
        df.at[row.name, 'commission_hedge'] = commission_hedge_today

        # === GAMMA ATTRIB (tạm giữ, bạn sẽ fix sau) ===
        df.at[row.name, 'gamma_attrib'] = gamma_pnl_factor(
            row_prev['gamma_norm'], S_prev, rv_actual, row_prev['iv_straddle'], dt_actual, notional
        )

    df.iloc[0]['cum_return'] = 0.0
    df.iloc[0]['cum_pnl'] = 0.0

    return df


def build_synthetic_gamma_scalping_case(
    *,
    snapshots: int = 90,
    seed: int = 42,
    initial_spot: float = 100_000.0,
    strike: float = 100_000.0,
) -> tuple[pd.DataFrame, OptionInstrumentRegistry, list[OptionPackageIntent]]:
    """
    Build a deterministic ATM long-straddle case for the native option engine.

    The sample intentionally keeps one listed call/put alive across the whole
    tape. This isolates option-package execution, quote-side fills, MTM,
    prepared-cache replay, and delta-hedge accounting without mixing in
    selection/rollover noise.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")
    expiry = int((start + pd.Timedelta(days=max(30, snapshots + 10))).value)
    call_id = "BTC-26MAR26-100000-C.TEST"
    put_id = "BTC-26MAR26-100000-P.TEST"
    registry = OptionInstrumentRegistry.from_iterable(
        (
            _linear_option_spec(call_id, strike, OptionKind.CALL, expiry),
            _linear_option_spec(put_id, strike, OptionKind.PUT, expiry),
        )
    )

    rows = []
    spot = float(initial_spot)
    for i in range(snapshots):
        ts = start + pd.Timedelta(days=i)
        timestamp_ns = int(ts.value)
        spot *= float(np.exp(0.0002 + rng.normal(0.0, 0.018)))
        dte = max((expiry - timestamp_ns) / (24 * 60 * 60 * 1_000_000_000), 1.0)
        time_value = max(800.0 * np.sqrt(dte / 365.0), 80.0)
        skew = np.tanh((spot - strike) / (0.08 * strike))
        call_delta = float(np.clip(0.50 + 0.35 * skew, 0.05, 0.95))
        put_delta = call_delta - 1.0

        call_mark = max(spot - strike, 0.0) + time_value
        put_mark = max(strike - spot, 0.0) + time_value * 0.98
        for sequence_id, instrument_id, option_kind, mark, delta in (
            (0, call_id, "call", call_mark, call_delta),
            (1, put_id, "put", put_mark, put_delta),
        ):
            spread = max(mark * 0.004, 2.0)
            rows.append(
                {
                    "timestamp_ns": timestamp_ns,
                    "instrument_id": instrument_id,
                    "venue": "TEST",
                    "underlying_id": "BTC-PERP.TEST",
                    "expiry_ns": expiry,
                    "strike": strike,
                    "option_kind": option_kind,
                    "bid_price": max(mark - 0.5 * spread, 0.01),
                    "bid_size": 100.0,
                    "ask_price": mark + 0.5 * spread,
                    "ask_size": 100.0,
                    "mark_price": mark,
                    "last_price": mark,
                    "index_price": spot,
                    "forward_price": spot,
                    "mark_iv": 0.55,
                    "bid_iv": 0.54,
                    "ask_iv": 0.56,
                    "delta": delta,
                    "gamma": 0.00008,
                    "vega": 90.0,
                    "theta": -8.0,
                    "open_interest": 500.0,
                    "volume": 100.0,
                    "quote_currency": "USD",
                    "settlement_currency": "USD",
                    "sequence_id": sequence_id,
                    "source_latency_ns": 1_000_000,
                }
            )

    chain = pd.DataFrame(rows)
    timestamps = sorted(chain["timestamp_ns"].unique())
    packages = [
        OptionPackageIntent(
            timestamp_ns=int(timestamps[0]),
            package_id="gamma-open-long-straddle",
            legs=(
                OptionPackageLeg(call_id, OrderSide.BUY, 1.0, role="long_call"),
                OptionPackageLeg(put_id, OrderSide.BUY, 1.0, role="long_put"),
            ),
            quantity=1.0,
            tag="gamma_scalping_entry",
            metadata={"strategy": "gamma_scalping", "action": "open"},
        ),
        OptionPackageIntent(
            timestamp_ns=int(timestamps[-1]),
            package_id="gamma-close-long-straddle",
            legs=(
                OptionPackageLeg(call_id, OrderSide.SELL, 1.0, role="close_call"),
                OptionPackageLeg(put_id, OrderSide.SELL, 1.0, role="close_put"),
            ),
            quantity=1.0,
            tag="gamma_scalping_exit",
            metadata={"strategy": "gamma_scalping", "action": "close"},
        ),
    ]
    return chain, registry, packages


def run_quantbt_gamma_scalping_sample(*, snapshots: int = 90, seed: int = 42) -> dict:
    """Run the synthetic gamma-scalping sample through the public options endpoint."""
    chain, registry, packages = build_synthetic_gamma_scalping_case(snapshots=snapshots, seed=seed)
    cache = OptionPreparedRunCache.from_chain(chain, registry)
    bt = QuantBTEndpoint.options(
        initial_capital=100_000.0,
        reporting_currency="USD",
        initial_balances={"USD": 100_000.0},
        fee_rate=0.0002,
        metadata={"sample": "gamma_scalping_backtestsample", "seed": seed},
    )
    uncached = bt.backtest(chain=chain, instruments=registry, packages=packages)
    cached = bt.backtest(chain=chain, instruments=registry, packages=packages, prepared_cache=cache)

    spots = (
        chain.sort_values(["timestamp_ns", "instrument_id"])
        .groupby("timestamp_ns", sort=True)["index_price"]
        .first()
    )
    deltas = (
        chain.assign(weighted_delta=chain["delta"])
        .groupby("timestamp_ns", sort=True)["weighted_delta"]
        .sum()
    )
    hedge = run_delta_hedge_path(
        timestamps_ns=[int(ts) for ts in spots.index],
        underlying_prices=spots.to_numpy(dtype=float),
        net_option_deltas=deltas.to_numpy(dtype=float),
        config=OptionHedgeConfig(policy=OptionHedgePolicyType.FIXED_THRESHOLD, threshold=0.05),
    )

    final_equity_diff = float(abs(uncached.equity.iloc[-1] - cached.equity.iloc[-1]))
    fills_equal = bool(uncached.fills_report.equals(cached.fills_report))
    if final_equity_diff > 1e-9 or not fills_equal:
        raise RuntimeError("prepared-cache gamma sample parity failed")

    report = {
        "status": "pass",
        "sample": "gamma_scalping_backtestsample",
        "snapshots": int(snapshots),
        "chain_rows": int(len(chain)),
        "packages": int(len(packages)),
        "fills": int(len(cached.fills_report)),
        "initial_equity": float(cached.equity.iloc[0]),
        "final_equity": float(cached.equity.iloc[-1]),
        "option_pnl": float(cached.equity.iloc[-1] - cached.equity.iloc[0]),
        "hedge_pnl": float(hedge.hedge_pnl),
        "combined_option_plus_hedge_pnl": float(cached.equity.iloc[-1] - cached.equity.iloc[0] + hedge.hedge_pnl),
        "hedge_rebalances": int(hedge.hedge_report["should_rebalance"].sum()),
        "prepared_cache_used": bool(cached.metadata.get("prepared_cache_used")),
        "package_cache_size": int(cached.metadata.get("package_cache_size", 0)),
        "parity": {
            "final_equity_abs_diff": final_equity_diff,
            "fills_equal": fills_equal,
        },
        "run_manifest": cached.run_manifest,
    }
    return report


def _linear_option_spec(symbol: str, strike: float, kind: OptionKind, expiry_ns: int) -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol=symbol,
        venue="test",
        underlying_id="BTC-PERP.TEST",
        underlying_index_id="BTC-INDEX.TEST",
        option_kind=kind,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.CASH,
        strike=strike,
        expiry_ns=expiry_ns,
        settlement_currency="USD",
        premium_currency="USD",
        quote_currency="USD",
        multiplier=1.0,
        contract_size=1.0,
        qty_step=1.0,
        tick_size=0.01,
        convention_version="gamma_scalping_synthetic_linear_v1",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a QuantBT options gamma-scalping smoke sample.")
    parser.add_argument("--snapshots", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    report = run_quantbt_gamma_scalping_sample(snapshots=args.snapshots, seed=args.seed)
    payload = json.dumps(report, indent=2, default=str)
    if args.output_json is not None:
        args.output_json.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
