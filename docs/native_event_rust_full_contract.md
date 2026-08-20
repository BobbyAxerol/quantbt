# Native Event Rust V2 Full Contract

Phase 47B upgrades the optional PyO3 backend from the earlier R1/R2
single-symbol slice to the public Native Event V2 contract. Python/replay
remains the correctness oracle and `auto` remains Python until the later Grid
workload and release gates pass.

## Phase 53A Pure Rust Core

Phase 53A keeps the **public** extension contract at API `0.4`, moves the full
static-tape engine into a pure Rust crate, and introduces a typed internal ABI
`0.5` alongside the P0-compatible wire-tape reader. The separation is
deliberate:

```text
quantbt-domain -> quantbt-engine -> native_event (PyO3 only)
```

`quantbt-domain` and `quantbt-engine` have no PyO3, NumPy, pandas, Python
exception, or report-model dependency. They can therefore run unit tests and
fuzz/property checks without Python headers. `quantbt-domain` owns the pure
API-0.4-to-ABI-0.5 translator; the static execution reader still consumes the
certified API-0.4 wire tape during this staged migration, so its P0 trace does
not change merely because storage moved crates. The compatibility binding owns
Python conversion and calls the pure engine.

The internal engine now uses typed IDs, generation-safe order handles, a free
list arena, lifecycle indexes for active/expiry/parent/OCO relationships, and
flat bar-major static-tape output. Terminal lifecycle events are emitted before
their slot is released; history-scaled hot compaction is no longer part of the
execution loop. API-0.4 callers still receive the same endpoint and report
surface.

The workspace also reserves pure-Rust boundaries for native strategy IR,
scenario batch/WFO, portfolio targets, and package execution. They intentionally
do not advertise execution capability yet; their executable semantics remain
Phase 53B work. See
[`phase53a/benchmark_taxonomy.json`](../benchmarks/native_event/results/phase53a/benchmark_taxonomy.json)
for the frozen E0-E6 benchmark taxonomy.

## Phase 53B Native Strategy IR and Batch Drivers

Phase 53B activates a separate, **opt-in** native execution boundary for
bounded declarative strategies. It is intentionally not an automatic
replacement for the stable event-driven facade: arbitrary Python callbacks,
current endpoint routes, and public WFO schedules retain their compatibility
behavior. The supported v1 templates are signal targets, structural Grid
levels, periodic DCA, and fixed bracket/OCO transitions. Python and Rust
compile the same immutable program fingerprint and differential tests require
exact accounting/lifecycle parity.

Batch scoring shares one immutable prepared market/program, uses worker-local
sessions, returns scalar rows in stable scenario order, and reruns audit only
for selected candidates. `NativeIRFold` creates an explicit causal OOS window
with fresh account state; it is not a hidden parameter-selection policy and
does not change `QuantBTEndpoint.walk_forward()` semantics. Portfolio targets
and package plans now compile accepted decisions into ABI-0.5 tapes which pass
through `FullSession`, but they remain narrow preflight/tape drivers rather
than a promoted general portfolio or arbitrage endpoint.

The complete API, scope boundary, and reproducible E3/E6 benchmark command are
documented in [Native strategy IR and batch](native_strategy_ir.md).

### Static output profiles and E0 evidence

The static command-tape core resolves its retention profile before execution;
the lifecycle, fill, accounting, and liquidation path is identical for all
three profiles:

| Profile | Retained result | Intended use |
| --- | --- | --- |
| `score` | scalar terminal accounting only | large optimization/scoring loops |
| `compact` | dense account/position/cost/margin paths, no fill/event rows | metrics and research paths |
| `audit` | compact paths plus typed fill/event columns | replay, reconciliation, and reporting |

`benchmark_phase53a_e0_profiles.py` measures a prepared one-symbol explicit
command tape with one PyO3 call and no Python callback per run. On the frozen
2,000-bar fixture (median of five warm runs), all three profiles had identical
terminal accounting; `score` ran at 8.19M / 2.15M bars/s and `compact` at
1.56M / 1.04M bars/s for low/high churn respectively. `audit` retained the
requested ledger and ran at 655k / 81k bars/s. These are machine-specific E0
kernel measurements, not a claim about Python-callback, Grid IR, portfolio,
package, or WFO workloads. The complete reproducible artifact is
[`e0_profiles.json`](../benchmarks/native_event/results/phase53a/e0_profiles.json).

Reproduce the same core-level evidence with:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run python \
  benchmarks/native_event/benchmark_phase53a_e0_profiles.py \
  --bars 2000 --repeats 5
```

### ABI-0.5 typed native outputs

The additive `NativeExecutionRequestCore` boundary also exposes a typed result
route for prepared static tapes and bounded strategy IR:

```python
# Low-level ABI-0.5 / experimental surface in _quantbt_native.
typed = request.execute_typed()
```

The request profile determines the concrete result object:

| Profile | Object | Retained data |
| --- | --- | --- |
| `score` | `NativeScoreOutputV1` | scalar accounting and final positions only |
| `compact` | `NativeCompactOutputV1` | score plus flat dense account paths |
| `audit` | `NativeAuditOutputV1` | compact data plus typed `int64`/`float64` fill and lifecycle columns |

Each result carries the request fingerprint, request/protocol/output versions,
workload kind, command count, bar count, retained payload bytes, and one-pass
boundary metadata. Rust vectors move directly into NumPy-owned contiguous
arrays, so result arrays remain valid after the native request/session is
released. `score` has no `equity`, fill, or event attributes; `compact` has no
fill/event attributes. Integer identifiers remain integer arrays.

`request.execute()` is intentionally retained as the frozen compatibility
adapter and returns the historical dictionary shape. It moves the authoritative
typed output into that shape without a second engine run. Calling
`typed.as_dict()` is likewise an explicit cold-path conversion for legacy code.
Pandas, `BacktestResultV2`, plots, reports, and stakeholder tables are created
only by their explicit report/adaptation path. No endpoint is silently promoted
to this ABI-0.5 surface in the current release.

### Prepared ownership, cache, and reset

The additive ABI-0.5 preparation helper is available for static tapes and
native strategy IR:

```python
from quantbt.preparation import CachePolicy, NativeExecutionPreparationCache

cache = NativeExecutionPreparationCache(CachePolicy(max_bytes=256 * 1024 * 1024))
market = cache.prepare_market(..., symbols=["ETHUSDT"])
template = cache.prepare_template(
    market,
    contract_sizes=contract_sizes,
    leverages=leverages,
    fee_rates=fee_rates,
    initial_capital=20_000.0,
    maintenance_ratio=0.005,
    slippage_rate=0.0002,
    use_funding=True,
    event_contract_code=3,
)
request = cache.command_request(template, ... , output_profile=0)
runner = cache.new_runner(request)
score = runner.execute_typed()
```

The cache has three bounded, content-addressed tiers: L2 market (60% of the
declared budget), L3 output-independent template (15%), and L4 immutable
request tape (25%). Keys include timestamps, symbols, open/high/low/close,
volume, funding, funding mask, instrument/account values, event contract, and
all request arrays. Object identity is never a cache key. `cache.diagnostics`
reports hits, misses, resident bytes, tier budgets, ingress copies, and cache
generation; `cache.clear()` refuses a pinned active entry unless explicitly
forced.

`NativeExecutionTemplateCore.window(start, end)` creates a zero-copy causal
market view with a local bar clock. Each `NativeExecutionRunnerCore` owns one
mutable Rust session, resets account/orders/indexes before every independent
run, and exposes monotonic generation/counter diagnostics even after an
explicit `full_rebuild`. `account_only` reset is
intentionally unsupported because retaining active lifecycle state while
resetting account state would be ambiguous. `result_buffers` only releases
reusable scratch capacity; it cannot invalidate a typed output because its
NumPy columns own moved Rust buffers.

This remains an experimental lower-level preparation surface. Existing
endpoints and `backend="auto"` behavior are unchanged; higher-level
prepared-batch promotion has its own parity and release gate.

## Capability boundary

The explicit selector is:

```python
from quantbt import AccountConfig, ExecutionConfig
from quantbt.backends.native_event import NativeEventBackend, NativeEventConfig

backend = NativeEventBackend(
    NativeEventConfig(
        account=AccountConfig(
            initial_capital=20_000,
            leverage=5,
            maintenance_ratio=0.005,
        ),
        execution=ExecutionConfig(slippage_bps=2.0),
        fee_rate=0.0005,
        use_funding=True,
        native_backend="rust",
        report_level="audit",
    )
)
```

An API `0.4` wheel must advertise all full-contract capability keys before
the explicit Rust path is allowed to execute:

```text
native_event_v2_full_contract
native_event_v2_multisymbol
native_event_v2_funding
native_event_v2_liquidation
native_event_v2_cancel_all_oco
native_event_v2_tif_expiry
native_event_v2_relationships
native_event_v2_quantity_preflight
```

Older API `0.3` wheels remain readable for the historical R1/R2 adapter, but
they cannot claim the full contract. A requested `native_backend="rust"`
fails explicitly when the binary or its capability set is incomplete.

## Supported domain surface

The Rust full session receives the same primitive command tape as the Python
replay engine:

- `PLACE`, `CANCEL`, `CANCEL_ALL`, `AMEND`, and `REPLACE`;
- MARKET, LIMIT, STOP_MARKET, and STOP_LIMIT orders;
- GTC, GTD, IOC, and FOK time-in-force behavior;
- next-bar command effectiveness and stable insertion priority;
- reduce-only, exchange quantity preflight, fees, slippage, and contract size;
- parent activation, group filters, OCO sibling cancellation, and expiry;
- funding masks/rates, initial and maintenance margin, and liquidation;
- flattened multi-symbol OHLCV/funding arrays and per-symbol positions.

The Rust execution order is intentionally copied from the replay-certified
Python oracle:

```text
mark/PnL
intrabar liquidation
funding
after-funding liquidation
GTD expiry
lifecycle commands
matching/fills
parent/OCO activation
after-order liquidation
state recording
```

The adapter preserves active-order relationship metadata (`parent_order_id`,
`group_id`, `oco_group_id`, activation state, tag, campaign, cycle, and level)
for reactive contexts. Audit reports also retain event status and reject code.

## Static tape and reporting

```python
market = backend.prepare_market_arrays(
    datetime_index=index,
    closes={"A": frame_a["close"], "B": frame_b["close"]},
    highs={"A": frame_a["high"], "B": frame_b["high"]},
    lows={"A": frame_a["low"], "B": frame_b["low"]},
    funding_rate={"A": funding_a, "B": funding_b},
    symbols=["A", "B"],
)
compiled = backend.compile_order_commands(index, commands, symbols=["A", "B"])
result = backend.run_order_commands(
    datetime_index=index,
    commands=commands,
    closes={"A": frame_a["close"], "B": frame_b["close"]},
    highs={"A": frame_a["high"], "B": frame_b["high"]},
    lows={"A": frame_a["low"], "B": frame_b["low"]},
    funding_rate={"A": funding_a, "B": funding_b},
    symbols=["A", "B"],
    market_arrays=market,
    compiled_commands=compiled,
    report_level="audit",
)
```

The returned `BacktestResultV2` has the normal equity/position/fee/funding/
margin paths, fills, `fills_report`, `order_report`, and reporting helpers.
The score facade keeps pandas report construction out of the optimization
boundary; use an audit rerun for stakeholder-level ledgers and plots.

## Phase 48E.1 production-closure contract

Phase 48E.1 keeps the public command ABI and endpoint stable while closing the
native allocation/report boundary before the TestPyPI gate.

### Execution profiles

The Rust lifecycle is one implementation. Its output profile changes what is
retained, never what is executed:

| Profile | Retained output | Intended use |
|---|---|---|
| `score` | scalar accounting, terminal state, counters, liquidation | Optuna/search |
| `research` / `minimal` | dense equity, positions, fees, funding, turnover, margin | metrics and diagnostics |
| `audit` | dense paths plus fills, lifecycle events, reject codes, command metadata | stakeholder replay/export |

The score sink is count-only for fills/events and does not create nested row
vectors. Audit uses reusable Rust-owned SoA buffers and converts them at the
Python report boundary. No borrowed NumPy view is used, so Rust buffers cannot
be mutated while Python holds a view.

API 0.4 reactive callers can use the typed `FullStepResultCore` path. Scalar
fields are always present; `positions`, `fills`, `events`, and `active_orders`
are `None` unless their output-mask bit was requested. The legacy dictionary
`step()` remains available for compatibility.

### Report semantics

The reports are intentionally different:

- `command_report` is the immutable command-intent table from the compiled
  tape. It contains requested action, order identity, quantity/price/trigger,
  TIF, relationship fields, expiry and strategy metadata.
- `order_report` is the Rust lifecycle event table: event bar/type/status,
  target identity and reject code.
- `fills_report` is the execution table with bar, symbol, side, quantity,
  price, fee and enriched tag/campaign/cycle/level metadata.

`command_report` is never assigned to `order_report`. `result.orders` may stay
empty for the Rust audit adapter; reports and visualizations must use the
explicit report tables instead.

### Memory and lifecycle guarantees

Prepared market arrays use immutable fixed-length Rust storage shared through
`Arc`; account arrays use fixed boxed storage and public order identities remain
`i64`. Internal side/order-type/TIF values are validated and stored in compact
integer representations; no public command field changes.

Phase 53A replaces terminal-order compaction in the full static-tape engine
with generation-safe arena release after the terminal lifecycle event has been
emitted. Slot reuse comes from a free list, stale handles cannot alias a new
order, and active/expiry/parent/OCO indexes contain live handles only. Stable
monotonic insertion sequence preserves replacement aliases, parent activation,
OCO cancellation, GTD expiry, and matching priority. `compaction_count` remains
as a compatibility diagnostic and stays zero on the arena path. Reset clears
logical state while retaining reusable capacity, and
`release_step_buffer_capacity()` remains an explicit maintenance operation
rather than a per-trial shrink.

Close-price margin accounting uses a per-bar cache. The first lookup computes
the complete symbol aggregate; a fill then updates the affected symbol's
initial and maintenance contribution using the old and new absolute quantity.
Liquidation invalidates the cache. This is an accounting optimization only:
the original margin formulas, post-cost margin gate and liquidation ordering
remain unchanged, and the Rust/Python parity suite covers additions, reductions,
reversals and multi-fill bars.

The authoritative closure evidence is the Phase 48E.1 test and wheel matrix:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src poetry run pytest -q \
  tests/native_event/test_phase48e1_closure.py \
  tests/native_event/contract/test_phase47b_full_contract.py
```

See [`upgrade/implement.md`](../upgrade/implement.md) for the complete P0-P7
acceptance matrix, benchmark artifacts and CI wheel gate.

`prepare_rust_batched_runner(...)` retains its historical name for endpoint
compatibility, but on a full-capability wheel it returns `RustFullRunner`.
The older `RustBatchedRunner` remains a separate legacy single-symbol runner
and deliberately keeps its narrower fail-fast contract.

## Conformance evidence

The shared suite is:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=. poetry run pytest -q \
  tests/native_event/contract/test_phase47b_full_contract.py
```

The Phase 47B fixture matrix compares Python and explicit Rust on:

```text
equity, positions, fees, funding, turnover, margin, liquidation;
fills and fill prices;
event order, event status, event reject code;
parent/OCO activation and active-order metadata;
multi-symbol quantity constraints;
TIF and expiry;
replace alias resolution.
```

Current focused evidence: **13 passed** after Rust rebuild. Related R0/R1/R2,
score/RSS, and capability regression suites also pass. Grid 2,000-bar
long-only/long-short parity, isolated RSS evidence, and `auto` promotion are
Phase 47C gates and are intentionally not claimed here.
