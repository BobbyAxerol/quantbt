# Native Strategy IR and Scenario Batch

Native Strategy IR is the bounded, declarative route for deterministic event
strategies. Phase 54B.2 promotes the certified Stage-B subset to Rust-first
under `native_backend="auto"`: a supported IR program with at least 2,000 bars
uses one Rust-owned execution session. Python remains the public facade, the
explicit oracle (`native_backend="python"`), and the compatibility path for
arbitrary callbacks.

This promotion does **not** turn every event strategy into native code.
`QuantBTEndpoint.event_driven()` callback strategies and ordinary
`QuantBTEndpoint.walk_forward()` callbacks remain Python compatibility routes.
They may still use the normal event lifecycle engine, but they are not counted
as native-IR throughput and are never silently compiled into IR.

## Why This Route Exists

An arbitrary Python strategy callable cannot become native merely because an
event loop is implemented in Rust. Calling Python once per bar still pays the
callback, object, and GIL costs. Native IR instead takes a precomputed numeric
signal tape, compiles a small validated strategy template into the internal
ABI-0.5 command tape in Rust, and executes it through the same `FullSession`
that owns fills, fees, slippage, funding, margin, liquidation, parent/child
activation, and OCO cancellation.

The Python reference compiler and Rust compiler share a deterministic program
fingerprint. A mismatch is an error, not a fallback.

## Supported v1 Templates

| Template | Input signal meaning | Native behavior |
|---|---|---|
| `signal_target` | signed threshold signal | target `-quantity`, `0`, or `+quantity` |
| `grid_level` | structural integer level | target is `level * quantity` |
| `dca_periodic` | signed regime signal | reset on flat/side flip; add one level at each configured period up to `max_levels` |
| `fixed_bracket` | signed threshold signal | market parent plus reduce-only limit/stop OCO children |

`fixed_bracket` is an immutable transition tape: on a source-signal target
change it cancels the prior children and places the next parent/children. It is
not a general dynamic trailing-stop VM, an arbitrary order amendment engine,
or an exchange-native bracket-list claim. Unsupported strategy constructs must
continue through the existing callback/order routes.

All templates have bounded instructions and commands per bar. The signal
generator stays in the strategy/research layer, where warm-up and look-ahead
control belong. Native IR never invokes a Python callback while it runs.

## Stage-B Route Policy

Use the stable `NativeEventBackend.prepare_native_strategy_ir(...)` facade.
It resolves a typed, versioned execution plan before market execution:

| Request | Result |
|---|---|
| `native_backend="auto"`, supported v1 template, certified API-0.4 wheel, Linux local CPython evidence, `bars >= 2,000` | Rust-first |
| `native_backend="auto"` below 2,000 bars or outside the capability row | Python with a structured `native_event_promotion_v1.reason` |
| `native_backend="python"` | Python oracle explicitly |
| `native_backend="rust"` | Rust strictly, or a clear pre-execution error |

The promotion threshold is deliberately a routing/evidence threshold, not a
trading rule. It never changes a signal, fill, fee, funding, margin, or
liquidation calculation. `QUANTBT_DISABLE_NATIVE=1` forces Python; setting
`QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` caps automatic promotion locally.
Portfolio and package routes are not covered by this Stage-B policy.

## Single-Run Use

```python
from quantbt import (
    AccountConfig,
    ExecutionConfig,
    NativeEventBackend,
    NativeEventConfig,
    NativeStrategyIR,
    NativeStrategyKind,
    NativeStrategyParameters,
)

backend = NativeEventBackend(
    NativeEventConfig(
        account=AccountConfig(initial_capital=20_000, leverage=5),
        execution=ExecutionConfig(slippage_bps=2.0),
        fee_rate=0.0002,  # canonical one-way fee
        use_funding=False,
    )
)
program = NativeStrategyIR(
    NativeStrategyKind.GRID_LEVEL,
    "BTC",
    parameters=NativeStrategyParameters(quantity=0.01),
)
runner = backend.prepare_native_strategy_ir(
    frame.index,
    closes={"BTC": frame["close"]},
    highs={"BTC": frame["high"]},
    lows={"BTC": frame["low"]},
    opens={"BTC": frame["open"]},
    program=program,
    symbols=["BTC"],
)

# `grid_signal` is a finite, integer-valued structural-level Series/array.
score = runner.run_score(grid_signal)
audit = runner.backtest(grid_signal, report_level="audit")  # selected candidate only
print(score.final_equity, audit.metadata["strategy_ir_fingerprint"])
```

`run_score()` retains terminal accounting only. `run_compact()` retains dense
account paths without fill/event rows. `run_audit()` retains the typed fill and
lifecycle ledger. The execution semantics are identical; only retained output
changes.

At the lower ABI-0.5 request boundary, the same profiles are available as
`NativeScoreOutputV1`, `NativeCompactOutputV1`, and `NativeAuditOutputV1` via
`NativeExecutionRequestCore.execute_typed()`. These objects own contiguous
NumPy columns transferred from Rust and expose `as_dict()` only for an explicit
cold-path compatibility conversion. `NativeIRExecutionRunner` is the stable
public facade. It preserves the existing score/compact/audit return contracts
while routing a certified request to Rust. Neither route replays Python
accounting to construct an audit result.

For repeated native IR runs, `NativeExecutionPreparationCache` can reuse one
immutable `NativeExecutionTemplateCore` and cache the IR request by the full
signal/program/parameter fingerprint. `cache.strategy_ir_request(...)` keeps
market, instrument, account, and contract preparation outside each run;
`cache.new_runner(request)` creates a separate mutable Rust session whose
account/order state resets between scenarios. A template window has a local
bar clock and shares only immutable market storage, so it is suitable for
causal fold-local requests without carrying positions or orders across folds.

## Batch and Fold Use

Use batch scoring when signal rows and the four-column parameter matrix are
already available. The prepared market and immutable program are shared;
every worker has its own `FullSession`, order arena, lifecycle indexes, and
account state. The result is deterministically sorted by scenario ID.

```python
from quantbt import NativeIRFold

summary = runner.run_batch_score(
    signal_matrix,                 # shape: [scenario, prepared_market_bars]
    parameter_matrix=parameter_matrix,  # four columns: quantity, threshold, tp, sl
    workers=4,
    chunk_size=256,
)
winner_ids = summary.top_ids(10)
winner_audit = runner.run_audit(
    signal_matrix[int(winner_ids[0])],
    parameters=parameter_matrix[int(winner_ids[0])],
)

fold = NativeIRFold(
    fold_id=0,
    warmup_start=0,
    train_start=0,
    train_end=4_000,
    test_start=4_000,
    test_end=5_000,
)
oos_summary = runner.run_fold_batch_score(
    signal_matrix,
    fold,
    parameter_matrix=parameter_matrix,
    workers=4,
)
```

`NativeIRFold` validates
`warmup_start <= train_start < train_end <= test_start < test_end`. It creates one OOS market
window for the batch and starts a fresh account for every scenario. It is an
execution primitive only: it does not select parameters, alter Optuna seeds,
change a WFO objective, or make OOS observations available to a selector.

The normal `QuantBTEndpoint.walk_forward()` schedules (`global`,
`per_fold_decay`, and `per_fold_causal`) remain callback-oriented Python
orchestration routes. `NativeIRFold` is instead a Rust-first execution
primitive for a precomputed bounded IR signal matrix; it does not select
parameters or make OOS data available to a selector.

## Portfolio and Package Boundary

The Phase 53B Rust portfolio and package modules have a narrower role:

1. accept already-computed target units or package legs;
2. apply the frozen Python-reference preflight, margin/rejection, reservation,
   rollback, staleness, and residual-risk contracts;
3. compile accepted deltas/legs into an immutable ABI-0.5 tape;
4. send that tape through the shared event/account lifecycle.

This means allocation, covariance/risk estimation, and public arbitrage plan
construction remain Python research-layer concerns. It also means the current
feature is **not** a promoted general Rust portfolio/arbitrage endpoint yet.
Atomic package behavior is a deterministic OHLC bar-transaction simulation,
not a claim of exchange-native atomicity.

## Observability and Performance Contract

Native results include:

- `strategy_ir_version`, `strategy_ir_kind`, and program fingerprint;
- command count and human-readable disassembly;
- `python_callbacks=0` and `boundary_calls=1` for each native run/batch;
- batch worker diagnostics, shared-market bytes, and
  `shared_market_copies_per_scenario=0`;
- an explicit `audit_materialized` flag.

Workers are opt-in and default to `1`, preventing accidental nested
parallelism when Optuna, BLAS, Numba, or process-level WFO parallelism already
owns the machine. Exact output equality is required across worker counts before
performance is considered. Run the reproducible evidence locally with:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run python \
  benchmarks/native_event/benchmark_phase53b_native_drivers.py \
  --bars 2000 --scenarios 64 --repeats 5
```

The benchmark labels E3 and E6 only. It does not generalize its numbers to
arbitrary Python callbacks, full portfolio execution, or package/arbitrage
production certification.

### Historical Phase 53B evidence

The committed 2,000-bar Grid-level fixture at
[`native_drivers.json`](../benchmarks/native_event/results/phase53b/native_drivers.json)
used 64 scenarios and five warmed repetitions. The Python reference oracle
measured `4.778 ms` (`418,613 bars/s`); one-call Rust IR score measured
`0.333 ms` (`5.997M bars/s`) with exact audit parity, a local `14.33x`
reference-path speedup. Batch score used no audit rows and no market copy per
scenario: one worker measured `6.87M` simulated bars/s, four workers measured
`21.41M`, and eight workers dropped to `17.46M` on this host, so `workers=4`
was the measured saturation point rather than an assumed default. The local
batch RSS delta was about `1.16 MiB`; it is an incremental-process observation,
not an absolute memory guarantee.

## Validation Commands

```bash
cargo test --offline -p quantbt-engine -p quantbt-batch \
  -p quantbt-portfolio -p quantbt-package -p quantbt-native

MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run pytest -q \
  tests/native_event/contract/test_phase53b_native_drivers.py \
  tests/native_event/contract/test_phase54b2_rust_first_routes.py
```

The second suite checks Python-reference versus Rust trace/accounting parity
for signal target, Grid, DCA, and fixed bracket templates; standalone versus
batch equality; 1/2/4/8 worker determinism; selected audit rerun equality;
causal fold-window reset behavior; and Python-reference parity for portfolio
and package preflight contracts.
