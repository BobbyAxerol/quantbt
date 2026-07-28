# Fast Intrabar Bracket And Fill Replay

Phase 31 adds a strict single-symbol intrabar route for alphas that previously
mixed signal generation and exit-price simulation in notebook code.

The goal is not to make OHLC bars pretend to be tick data. The goal is to make
the exact assumptions explicit, deterministic, fast, and auditable.

## Fast Kernel

```python
from quantbt import QuantBTEndpoint

bt = QuantBTEndpoint.intrabar_bracket(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0002,      # one-way
    slippage_bps=1.0,
    tick_size=0.01,
    use_funding=False,
    close_on_last_bar=True,
    report_level="audit",
)

result = bt.backtest(
    data=df,
    signal_col="entry_signal",
    symbols=["ETHUSDT"],
    intent_cols={
        "stop_value": "sl_pct",
        "take_profit_value": "tp_pct",
        "trailing_value": "trail_pct",
        "exit_long": "exit_long",
        "exit_short": "exit_short",
    },
)

fills = bt.fills_report
result.show_metrics()
```

## Required Data

`data` must be a strict single-symbol OHLCV frame:

```text
DatetimeIndex or timestamp column
open
high
low
close
volume optional
```

Strict means no silent sorting, deduplication, or high/low fallback. The engine
should not “repair” an execution-sensitive tape because that can hide data
leakage and timestamp mistakes.

## Intent Columns

The minimal signal is a signed entry size:

```text
+1.0 -> open long one unit on next bar open
-1.0 -> open short one unit on next bar open
 0.0 -> no new entry
```

Optional intent columns:

```text
stop_value
take_profit_value
trailing_value
exit_long
exit_short
```

`level_mode="percent_distance"` is the default. Under this mode `0.02` means a
2 percent distance from entry price. `price_distance` and `absolute_price` are
available when the strategy emits price distances or absolute levels.

Legacy `technical_exit` is still accepted for compatibility and maps to both
long and short exits. New alphas should emit `exit_long` and `exit_short`, so an
exit signal cannot accidentally close the wrong side.

Sizing options:

```text
units
fixed_notional
pct_equity
risk_per_trade
```

After sizing, the same shared quantity constraints used by the event and
portfolio backends are applied: `qty_step`/`lot_size`/`slot_size`, `min_qty`,
and `min_notional`. If `tick_size` is provided, entry, stop, take-profit, and
trailing prices are quantized conservatively to the exchange tick.

## Execution Semantics

The engine uses this timing:

```text
entry signal known at close[t]
entry fills at open[t + 1]
stop and TP evaluated inside bar t + 1 using high/low
technical exit fills at open[t + 1]
trailing stop updates after the bar close
reversal = close old position + open new position
```

Same-bar stop/TP ambiguity is resolved conservatively by default. For a long,
if both stop and take-profit are touched in the same OHLC bar, the stop wins.
For a short, the same conservative loss-first rule applies.

Gap stops fill at the open when the open is worse than the trigger. Take-profit
uses limit-style behavior by default.

## Report Levels

| Level | Best use | Fill ledger |
|---|---|---|
| `minimal` | optimizer and WFO loops | no |
| `standard` | notebooks and normal services | no |
| `audit` | migration/certification/debugging | yes |

`audit` runs a deterministic second pass. The first pass computes accounting;
the second pass materializes sparse fill arrays sized exactly to the observed
fill count. The audit path asserts accounting parity with the first pass.

## Python Oracle

```python
ref = QuantBTEndpoint.intrabar_bracket_reference(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0002,
    slippage_bps=1.0,
)
ref_result = ref.backtest(data=df, signal_col="entry_signal")
```

Use the reference route to inspect behavior when migrating an alpha. Use the
Numba route for real sweeps after parity tests pass.

## Session-Aware Reference Mode

Phase 31H adds optional session execution state to the Python reference route.
It is for intraday alphas whose order eligibility depends on the trading
session, while the strategy still emits compact entry/exit intent.

```python
from quantbt import (
    EntryPositionPolicy,
    IntrabarSessionTape,
    ProtectiveExitReentryPolicy,
    QuantBTEndpoint,
    SessionExecutionPolicy,
)

session_policy = SessionExecutionPolicy(
    entry_position_policy=EntryPositionPolicy.FLAT_ONLY,
    max_long_entries_per_session=3,
    max_short_entries_per_session=1,
    protective_exit_reentry_policy=ProtectiveExitReentryPolicy.SUPPRESS_SIGNAL_BAR,
)

session_tape = IntrabarSessionTape.from_index(
    df.index,
    timezone="Asia/Ho_Chi_Minh",
    session_key="local_date",
    entry_windows=(("08:45", "11:30"), ("13:00", "14:20")),
    force_flat_time="14:20",
)

bt = QuantBTEndpoint.intrabar_bracket_reference(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0002,
    slippage_bps=1.0,
    session_policy=session_policy,
)

result = bt.backtest(
    data=df,
    signal_col="entry_signal",
    session_tape=session_tape,
    intent_cols={
        "stop_value": "sl_pct",
        "take_profit_value": "tp_pct",
        "exit_long": "exit_long",
        "exit_short": "exit_short",
    },
)
```

When `session_policy=None`, existing intrabar reference and fast-kernel behavior
is unchanged. When a session policy is supplied, `session_tape` is required.

Certified Phase 31H primitives:

```text
session reset
time-window entry blocking
EOD force-flat at open
flat-only / no implicit reversal
per-session long/short entry quotas
stale signal cancellation across session boundaries
protective-exit re-entry suppression
```

Phase 31I adds a separate fast Numba session kernel. The existing non-session
kernel remains unchanged; QuantBT dispatches once before execution:

```text
no session policy -> intrabar_bracket_v1
session policy    -> intrabar_session_bracket_v1
```

Use `intrabar_bracket_reference(...)` as the readable oracle for new session
semantics, then use `intrabar_bracket(...)` for sweeps after parity checks pass.
Prepared runners also include `session_policy` and `session_tape_signature` in
their frozen profile metadata to avoid cache reuse across different session
contracts.

## Prepared Runner

```python
runner = bt.prepare_intrabar(data=df, symbols=["ETHUSDT"])
result = runner.run(intent, report_level="minimal")
audit = runner.run(intent, report_level="audit")
```

The prepared runner caches strict OHLCV arrays, timestamps, funding arrays,
quantity constraints, validation certificate, data signature, and frozen profile
metadata. Use this in WFO/Optuna loops where market tape is fixed and only the
intent changes.

Funding events must align exactly to a market bar timestamp for
`POSITION_AT_EVENT` certification. Mid-bar funding events are rejected rather
than approximated from the end-of-bar position.

Timestamp semantics must also be explicit. The default
`bar_timestamp_semantics="close"` means each OHLC timestamp labels the bar
close, so funding is applied after intrabar execution on the remaining close
position. For common crypto feeds whose OHLC timestamp labels the bar open,
pass `bar_timestamp_semantics="open"`; funding is then applied after open-gap
marking and before pending orders at `open[t]`.

## Fill Replay

```python
bt = QuantBTEndpoint.fill_replay(initial_capital=20_000, leverage=5)
result = bt.backtest(data=df, fill_replay=fills_df, symbols=["ETHUSDT"])
```

`fills_df` must contain:

```text
bar_index
side
qty
price
sequence optional
fee optional
```

Fill replay is Level 1 certification: accounting is tested, but fill generation
is still owned by the alpha or external system that produced the tape.

## What This Does Not Claim

- It is not tick or L2 order-book simulation.
- It is not a multi-symbol cross-margin intrabar engine.
- It is not the DCA/grid state machine.
- It does not claim portfolio, arbitrage, grid, DCA, options, or shared
  cross-margin intrabar correctness.
- It does not make a look-ahead alpha valid.

For those cases, use native event or Nautilus package validation.
