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
only by their explicit report/adaptation path. The final sentence above
describes the Phase 53A staging state; Phase 61 promotes the certified public
static-command route below, without promoting unrelated event workloads.

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

### Phase 54B.1 versioned promotion policy

Rust availability is now separated from Rust promotion. The generated product
registry owns a policy table with ordered stages: `explicit_only`, `static_ir`,
`portfolio`, and `package`. A pure resolver evaluates the requested backend,
user policy, workload, lifecycle contract, output profile, account model,
symbol count, platform tags, extension capability snapshot, and local rollback
environment before any market preparation occurs.

`native_backend="python"` remains the oracle. `native_backend="rust"` remains
strict and fails before execution if the installed wheel is unavailable,
incompatible, non-executable, or missing a required capability. Only
`native_backend="auto"` is eligible for promotion. `backend_policy` accepts
`certified_only`, `prefer_native`, and `prefer_compatibility`; neither of the
first two can override an unpromoted registry row. The Phase 54B.1
`explicit_only` behavior was the intentional baseline before the
route-specific Phase 54B.2 evidence below.

The local emergency controls are deterministic and require no network service:
`QUANTBT_DISABLE_NATIVE=1` disables native routing, while
`QUANTBT_NATIVE_PROMOTION_MAX` caps the highest eligible stage. The result
metadata stores `native_event_promotion_v1`, including the table and registry
fingerprints, contract, matched rule, wheel/API/capability evidence when probed,
fallback code, and exact rollback state. This metadata is diagnostic only; it
does not change matching, accounting, fees, funding, margin, or liquidation.

### Phase 54B.2 static/IR/batch public promotion

The generated `native-event-promotion-v2` table now enables only Stage-B E0,
E3, and E6 rows. A public static V2/V3 command-tape request resolves
`native_backend="auto"` to Rust at 10,000 or more bars. A bounded
`NativeStrategyIR` v1 run, its shared batch scorer, or a causal
`NativeIRFold` batch resolves to Rust at 2,000 or more bars. Both routes use a
single Rust execution session and one Python-to-Rust boundary per run or batch.

The public `NativeIRExecutionRunner` and order-command facades adapt typed
Rust outputs only after execution. Score/compact paths do not create audit rows
or replay Python accounting; audit paths adapt the Rust lifecycle,
command-outcome, fill, and canonical trace buffers directly. The matching
Python route remains an explicit oracle and parity comparator.

All remaining routes are deliberately non-promoted: arbitrary callback and
reactive strategies, generic portfolio targets, generic package/arbitrage
execution, and any unsupported lifecycle/program/account/profile combination
stay Python with versioned decision metadata. The narrower explicit B3 routes
below do not change that automatic policy. `QUANTBT_DISABLE_NATIVE=1` or
`QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` supplies deterministic local
rollback without altering domain semantics.

### Phase 54B.3 bounded portfolio/package market routes

Phase 54B.3 adds two **explicit** Rust-owned market routes. They are narrow
execution contracts, not a replacement for `QuantBTEndpoint.portfolio()` or
the general basket/arbitrage endpoint:

```python
from quantbt.backends import (
    run_atomic_package_market,
    run_portfolio_target_market,
)
```

`run_portfolio_target_market(...)` accepts a bar-major `target_units` matrix
for a linear, quote-settled, gross-cross account under the V2
`event_lifecycle_v2_next_bar_close` clock. At each changed target row Rust
projects the pre-command account, validates tradeability/staleness/minimum
quantity/minimum notional, uses the canonical market fill price and one-way
fee, applies the post-cost margin gate, and either submits every target delta
or keeps every prior unit. Funding, intrabar/close liquidation, fill lifecycle,
and account paths remain in the same `FullSession`; Python does not retain a
second position or cash ledger.
The target tape must be finite and have exactly `(bars, symbols)` shape;
malformed input fails during typed-request preparation before an account is
created, rather than being treated as a zero/no-change target.

`run_atomic_package_market(...)` accepts one ordered same-bar market package.
It implements only `AtomicBarSimulation`: every leg is preflighted for
staleness, constraints, fill cost and margin, then all legs are submitted or
none are submitted. `package_accepted`, rejection codes, reservation/release,
fee and residual-notional provenance are returned with the native audit. This
is deterministic OHLC bar-transaction atomicity, **not** exchange-native OCO
lists, partial fills, queue priority, cross-venue settlement, sequential,
best-effort, or hedge-after-primary execution.
Input legs are kept in caller order and must have nondecreasing
`venue_sequence`; QuantBT does not infer a venue precedence rule.

Both helpers use one typed Python-to-Rust call per run and support retention
without execution replay:

| `report_level` | Retention |
| --- | --- |
| `score` or `minimal` | terminal scalar accounting and final positions |
| `compact` or `standard` | scalar accounting plus dense paths |
| `audit` | dense paths plus native fill/event and target/package admission SoA |

Only `audit` can be adapted through `to_audit_result()` into a common
`BacktestResultV2` report surface. Rerun the selected score candidate with
`report_level="audit"`; QuantBT never replays Python execution to fabricate
the ledger. The direct helper is intentionally Rust explicit in this release.
Its registry row is `certified`, not auto-promoted: only a future generic
endpoint adapter with an exact Python fallback and public-result parity may
enable Stage C/D automatic routing.
Generic portfolio, risk-parity, target-weight/notional, multi-currency,
cross-margin, package policies other than atomic-bar, and arbitrage domain
plans remain on their existing Python routes until each has a separate
contract, oracle corpus, and promotion row.

### Phase 68 bounded package V2 authority

Phase 68 adds an explicit typed package companion without changing the public
generic endpoint authority:

```python
from quantbt.backends import (
    run_bounded_package_market,
    run_bounded_package_market_scenarios,
)
```

`run_bounded_package_market(...)` owns a finite tape of `PackageIntentV2`
rows over the common Rust `FullSession`. It supports only one shared, linear
quote-settled gross-cross account and `event_lifecycle_v2_next_bar_close`. The
supported policy rows are `atomic_bar_simulation`, `sequential`, `best_effort`,
and `hedge_after_primary`. A typed planner previews/reserves each package,
resolves dependent quantities, then emits only accepted market commands to the
common session. The common session remains the sole lifecycle/fill/fee/funding/
margin authority; the package planner does not keep a second account or replay
a ledger.

For `hedge_after_primary`, dependent legs use the committed primary simulated
fill, then apply their own quantity step and minimum rules. Partial/rejected
legs create explicit residual rows. `unwind_package` emits deterministic
compensation commands in reverse declared leg order; if an unwind fails, the
remaining gross residual is still visible. `atomic_bar_simulation` is all or
nothing under the declared deterministic OHLC cost model, **not** exchange-
native OCO, queue priority, L2 matching, multi-venue settlement, or
cross-currency atomicity.

`run_bounded_package_market_scenarios(...)` batches pre-built independent
package scenarios through one Python-to-Rust boundary. It retains scalar score
columns and reset-flats the account, orders, positions, and reservations before
each row. It is appropriate after package intents have been created for
candidate/fold execution, but it is not generic callback WFO. Rerun the
selected scenario through the single-package helper with `report_level="audit"`
to materialize package/leg/residual provenance. The only typed arbitrage
adapters are selected same-account linear basis, stat-pair, calendar, and
index-basket plans. Triangular and cross-exchange plans fail before execution.

### Phase 67 shared-account portfolio target authority

`run_shared_portfolio_target_market(...)` is the explicit Phase 67 companion
for a planned multi-symbol linear target matrix. Unlike the legacy
`run_portfolio_target_market(...)` all-or-none helper, it maintains one shared
Rust account and accepts a fingerprinted admission policy:

```python
from quantbt.backends import run_shared_portfolio_target_market

result = run_shared_portfolio_target_market(
    ...,  # canonical OHLCV/funding arrays and per-symbol constraints
    targets=target_matrix,  # (bars, symbols)
    target_kind="units",
    admission_policy="reduce_first_then_increase",
    report_level="audit",
)
```

The planner owns the target matrix. Rust resolves units, quantizes venue lots,
commits fees/slippage/funding, admits shared margin, liquidates the whole
account, and emits dense account paths plus bounded per-symbol attribution in
compact/audit output. `pro_rata_to_available_margin` scales only increases
after reductions and uses the canonical instrument order for residual lots.
`all_or_none_rebalance` previews on a cloned account and commits nothing if
any leg fails. A zero-equity liquidation exposes a deterministic
`portfolio_symbol_liquidation_loss` residual so symbol PnL/cost attribution
reconciles to forced terminal equity.

The first certified row is target units and its prepared candidate/fold WFO
runtime. Notional, weight, and equity-fraction are available only as explicit
experimental target resolvers. Generic `QuantBTEndpoint.portfolio()`,
risk-parity/beta/covariance planning, cross-margin, packages, and arbitrage
are not rerouted or promoted by this helper.

Reproduce the bounded E4/E5 evidence after building the local wheel:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run python \
  benchmarks/native_event/benchmark_phase67_shared_portfolio.py \
  --bars 2000 --symbols 20 --candidates 16 --repeats 3
```

The artifact records preparation, score, compact retention, prepared WFO,
score/compact terminal parity, prepared/direct fold parity, no generic order
arena, zero WFO market-copy bytes, and current RSS. Its numbers are local
evidence for the explicit shared-account target contract only; they do not
generalize to the legacy portfolio engine or arbitrary multi-leg strategies.

### Phase 54B.4 installed-wheel release gate

Phase 54B.4 turns the local contract evidence into a release-candidate gate
without changing any generic endpoint default. The gate builds the core wheel,
core sdist, and matching native wheel from one ref, then proves behavior in
fresh virtual environments that have no repository `PYTHONPATH` or user-site
imports. It verifies both:

1. a core-only install, where `auto` deterministically remains Python; and
2. an exact core/native pair, where only generated Stage-B static/IR rows
   auto-promote and the bounded E4/E5 helpers remain explicit-only.

The exact-pair probe runs static public execution, IR batch/fold scoring, and
target/package helper accounting against the installed Python event oracle. It
also proves emergency disable and strict explicit-Rust failure behavior. The
certificate carries artifact checksums, product/lifecycle fingerprints,
benchmark evidence hashes, migration-audit hash, and supply-chain/SBOM
fingerprints. It is not a native publication authorization.

Use the [native release handoff](migration/native_release_handoff.md) for the
reproducible commands and release-owner process.

### Phase 54A.5.6 differential corpus and exit evidence

Phase 54A.5.6 adds a small, deterministic execution corpus rather than relying
on one happy-path benchmark. Each case is executed through four representations
of the same contract:

1. the public Python replay oracle;
2. the public API-0.4 Rust compatibility adapter;
3. a direct ABI-0.5 typed `NativeExecutionRequestCore`; and
4. the same ABI-0.5 request rebuilt from `NativeExecutionPreparationCache` and
   executed by a reusable native runner.

The checked corpus includes multi-symbol funding plus parent/OCO transitions,
and IOC/GTD/cancel-all/reduce-only rejection behavior. It locks accepted and
rejected commands, terminal reasons, fill rows, positions, equity, fee,
funding, margin, lifecycle trace, request/output provenance, reset behavior,
and result lifetime after cache cleanup. It also checks score/compact/audit
retention parity, without turning a score run into a hidden audit replay.

Canonical trace identity deliberately follows the public `1e-12` numerical
parity contract. Only the trace fingerprint projection rounds floating fields
to 12 decimal places, so harmless Python/Rust f64 accumulation-order noise
does not look like a lifecycle mismatch. Raw equity, position, fee, funding,
margin, fill, and accounting arrays are never rounded or overwritten by this
projection; their differential checks remain raw with `atol=1e-12`.

Run the differential corpus after building the local extension:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run pytest -q \
  tests/native_event/test_phase54a5_differential_corpus.py \
  tests/native_event/contract/test_phase51b_trace_replay.py
```

The reproducible performance artifact keeps engine time separate from explicit
cold Python adaptation time (`as_dict`, report construction), records current
and process-peak RSS, boundary/callback/copy counters, and output
fingerprints. It measures only the current one-boundary native paths:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run python \
  benchmarks/native_event/benchmark_phase54a5_exit_gate.py \
  --bars 2000 --scenarios 64 --repeats 5
```

E0 static command tapes, E3 bounded native strategy IR, and E6 shared-market
batch/WFO are measured. E1 arbitrary callbacks, E2 sparse reactive callbacks,
E4 full portfolio endpoints, and E5 full package endpoints are explicitly
recorded as non-promotion scope rather than being given misleading synthetic
speed claims. The artifact is machine-specific evidence only: Phase 54A.5.6
does not change `backend="auto"`, remove the Python oracle, or promote Rust as
the default public backend. Those require the workload-specific Phase 54B
parity, installed-wheel, RSS, rollback, and public-endpoint gates.

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

## Phase 61 Static Event Rust-Primary Closure

Phase 61 promotes one deliberately narrow public capability: a prepared,
static `OrderCommand` tape resolved to the Rust backend. For that capability,
`native_static_abi="0.5"` is the default and uses one Rust-owned
`NativeExecutionRequestCore`/`FullSession` execution per run. The historical
API 0.4 wire route remains available only through the explicit rollback flag
`native_static_abi="0.4_compat"`; QuantBT never selects it automatically.

```python
bt = QuantBTEndpoint.event_driven(
    input_mode="orders",
    backend="rust",                 # strict: fail if the matching wheel cannot run
    execution_contract="event_lifecycle_v3_next_open",
    native_static_abi="0.5",        # default; shown for provenance
    initial_capital=20_000,
)
result = bt.simulate(data=frame, order_commands=commands, symbols=["BTCUSDT"])

# Compatibility-only rollback for an investigation or controlled comparison.
compat = QuantBTEndpoint.event_driven(
    input_mode="orders", backend="rust", native_static_abi="0.4_compat"
)
```

The typed route prepares immutable market/instrument state and the command
tape once, then Rust owns market access, order lifecycle, fills, fees, funding,
margin, liquidation, trace, and online metrics for the run. It returns typed
SoA `NativeResultV2` output directly. Python adapts that result only after
execution to preserve the existing `BacktestResultV2` report surface; it does
not replay market/accounting state. Result metadata records
`native_static_abi_requested`, `native_static_abi_resolved`,
`native_static_execution_boundary_calls`, `native_result_v2`, and
`native_metric_v2` for auditability.

For `event_lifecycle_v3_next_open`, a prepared score request must supply the
actual `open` array. The low-level
`NativeEventBackend.run_compiled_tape_score(...)` fails closed without it;
using close as a substitute would change the execution clock. V2 close-timing
score requests may use close as their immutable open-equivalent because that is
their declared clock.

Three retention choices share the same Rust execution and accounting path:

| Route | Retention | Appropriate use |
| --- | --- | --- |
| Typed `score` | terminal scalar state only | native batch/scoring internals |
| Typed `compact` | dense account paths, no audit rows | prepared score/metrics adapter |
| Typed `audit` | compact paths plus bounded fill/lifecycle SoA | evidence, reconciliation, reports |

On the Phase 61 10,000-bar static V3 fixture, the prepared ABI-0.5 compact
score route measured `1.34M bars/s` versus `56.5k bars/s` for the Python
prepared comparator (`23.74x`), with no measured score-run RSS growth. These
are local release-gate measurements, not a claim about callback, portfolio,
arbitrage, grid, options, or full pandas-report workloads. The public
`BacktestResultV2` facade necessarily includes pandas/result adaptation and may
be slower than the low-retention score route; it is reported separately rather
than hidden inside the kernel claim.

The automatic A4 rule remains governed by the product registry: supported
installed Linux x86_64 CPython wheels may auto-select this exact static V2/V3
route at its certified workload threshold. Arbitrary Python callbacks,
reactive strategies, generic portfolio/basket/arbitrage, options, vectorized,
intrabar, and WFO orchestration are not promoted by Phase 61.

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

## Phase 62 Reactive Numeric Co-runtime R1

Phase 62 introduces an **explicit hybrid** reactive runtime. It is not an
alternate Python account engine and it is not a claim that arbitrary Python
strategy logic has become Rust. One `ReactiveNumericRunnerCore` owns the full
market timeline, `FullSession`, order arena, matching, fees, funding, margin,
liquidation, and dense native result buffers. Rust calls a declared Python
numeric strategy once at each required bar; the strategy writes primitive rows
into the persistent `ReactiveCommandBufferV2`.

```text
one Python -> Rust run entry
  -> Rust advances the bar and owns accounting
  -> Rust refreshes one ephemeral numeric context
  -> Python decides and writes primitive command rows
  -> Rust validates/quantizes/ingests rows for t + 1
  -> Rust continues the same session
  -> Python adapts the final typed result only after execution
```

The route requires all of the following:

- `native_backend="rust"` with a matching extension exposing
  `reactive_numeric_coruntime_r1`;
- `reactive_runtime="numeric_every_bar_v1"` and
  `reactive_kernel_mode="single_pass"`;
- `quantbt_reactive_numeric_v1 = True` and
  `StrategyContextRequirements(context_mode="numeric")` on the strategy;
- an every-bar callback schedule; and
- `audit_sink="memory"` or `"none"`.

The persistent context exposes only declared OHLCV/account fields, positions,
new fill/event deltas, and optional active-order data. It has no pandas,
dictionary, or dataclass projection in the callback path. The command writer
has bounded growth, numeric symbol/order handles, immediate Rust validation,
and deterministic stale/capacity errors. Both wrappers are invalid outside a
callback generation.

### PERF-03 callback boundary contract

Reactive callback lookup is compatible by default. Without an explicit marker,
the co-runtime resolves a Python lifecycle method at each required boundary;
this preserves a strategy that changes an instance method while it is running.
A strategy whose lifecycle methods are immutable for one run may set:

```python
quantbt_reactive_callback_binding_v1 = "run_stable"
```

Rust then pins the available `initialize`, `on_bar_close`, `on_wake`,
`next_block`, and `finalize` methods once at run start. The marker is scoped to
one native session and never carries state across reset/fold/candidate. A
strategy that mutates callbacks must use the default dynamic route. This is an
access optimization only: callback ordering, data availability, command
effective times, fills, fees, funding, margin, and liquidation remain the
same contract.

The numeric context is projected only after a live callback is known to exist.
That avoids unused snapshots for absent optional lifecycle hooks but does not
skip an every-bar decision callback. The command writer owns one primitive
staging region per callback. A callback exception, invalid return value, or
invalid command envelope discards every row not yet admitted to Rust and
poisons the reusable session until reset. A successful callback still applies
business admission independently per row, so one legitimate min-quantity or
post-cost rejection does not turn its whole batch into an all-or-none package.

`reactive_numeric_observability` exposes the boundary ledger:
`callback_binding_mode`, callback-plan/lookup time and counts, context
projection and getter counts, writer calls, completed command callbacks, and
discarded staged rows. These counters are observability only; they do not
participate in strategy decisions or account state.

R1 deliberately rejects hidden second execution: oracle-audit mode, sidecar
audit sinks, and sparse schedules are not accepted by the every-bar runtime.
Phase 75 adds a distinct prepared **scalar-score** surface for R1/R2/R3. It is
not a second execution or replay: the same Rust `FullSession` streams returns,
drawdown, trade/cost counters, final account state, and canonical metrics while
retaining no account path, command rows, callback trace, or terminal active
orders. A path/ledger score request fails before simulation; the selected
candidate must be rerun once through the public minimal/standard/audit path.

The independent certification protocol remains A/B/C/D:

```text
A  Python callback + independent Python execution oracle
B  Python callback + existing Rust per-bar bridge
C  Python callback + R1 Rust-led co-runtime
D  captured C command tape + static Rust replay
```

The Phase 62 fixture compares callback inputs, emitted commands, canonical
execution/account traces, strategy-state fingerprint, fills, equity,
positions, fees, funding, margin, and reset behavior. It also covers stale
handles, callback/command errors, cancellation, quantity quantization, and
command-capacity exhaustion. `tests/test_phase62_reactive_numeric_coruntime.py`
is the focused conformance suite.

Run the reproducible end-to-end benchmark with:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase62_reactive_coruntime.py \
  --bars 10000 --repeats 3 --concurrent-sessions 2
```

It measures lightweight, low-churn, high-churn, and two-session workloads
across Python R0, the old Rust per-bar bridge, R1 held-GIL, and R1
release-between-callbacks. Timing includes callback dispatch and public result
adaptation. RSS reports both one retained public result and the post-release
allocator plateau. On the recorded local 10,000-bar fixture, held-R1 was
`150.8k bars/s` low-churn versus Python R0 `46.2k bars/s`; this is
workload- and machine-specific evidence, not an automatic routing rule.

R1 remains A3 explicit. `backend="auto"` continues to use the Python callback
route. Sparse wakes, block intent, candidate batches, and any general reactive
auto-promotion are later contracts, not fallbacks hidden inside R1.

### Phase 75 Reactive Scalar Retention And Rust Hot State

The prepared scalar surface applies the same retention policy to R1 every-bar,
R2 sparse-wake, and R3 block-intent sessions. Rust keeps O(symbols) account and
metric state instead of O(bars x symbols) financial paths; per-bar execution,
funding, matching, margin, liquidation, wake evaluation, and Python decision
semantics are unchanged. Final margin values come from the live account state,
not the last element of a removed path. The reducer receives the full market
tape start/end timestamps and Python-equivalent bar annualization so short
tapes and early liquidation retain exact CAGR/Sharpe-family semantics.

`ReactiveNumericRunnerCore.from_prepared(...)` has backward-compatible public
retention defaults. The scalar profile explicitly sets all four retained
artifacts false: `account_paths`, `command_rows`, `callback_trace`, and
`terminal_active_orders`. `run_scalar(...)` rejects a non-scalar runner and
verifies that Rust did not return a retained artifact. Public `run(...)` remains
the cold result adapter and still supports minimal/standard/audit reports.

On the recorded warmed 10,000-bar fixture, scalar score measured `548.8k`,
`661.8k`, and `510.3k bars/s` for R1/R2/R3 versus public-minimal `263.1k`,
`330.1k`, and `261.2k bars/s` respectively (`2.09x`, `2.00x`, `1.95x`). These
are end-to-end prepared measurements including the declared Python callbacks;
they are not a generic callback or auto-promotion claim. The same-process RSS
delta is reported as an incremental warm allocation, not a cold peak-RSS claim.
See `benchmarks/native_event/results/phase75_reactive_scalar_retention.md`.

### Phase 76 Reactive Walk-Forward And Sparse Candidate Scheduling

Phase 76 makes the W3 reactive route public through
`QuantBTEndpoint.prepare_reactive_walk_forward(...)`. It reuses the established
`WalkForwardEngine` fold/selector mathematics and replaces only candidate
scoring with prepared Rust-owned dynamic account runs. A candidate/fold window
uses the full prepared tape's absolute clock but starts a fresh flat account;
the output is consequently a set of auditable OOS account segments, never a
synthetic continuous equity curve or a `pos_weight` stitch.

The sequential schedule retains one Optuna ask/evaluate/tell at a time and can
use the declared global or per-fold WFO schedules. Modes 4 and 5 never score
OOS for selection. Modes 1 and 3 score all candidates on IS first and only run
OOS for the resulting IS shortlist. R3B adds a separately declared
`throughput_batch_v1` ask-B/score-B/tell-B schedule for global WFO only; it is
deterministic for its configured seed/batch size but does not claim sequential
TPE equivalence.

For a heavy Python alpha, the sequential route may use one persistent Linux
fork/COW worker. The parent must have exactly one kernel thread before fork;
otherwise the route fails closed and callers use the in-process runtime or a
dedicated constrained worker. The prepared market is inherited COW, while IPC
contains only task markers and scalar rows. Worker metadata records PSS/RSS and
shared/private memory separately so shared tape pages are not double counted.

R3B candidate command/wake errors are candidate-local pruned records. A shared
Python callback exception fails the batch closed. Cancellation, failed workers,
and callback errors discard mutable session state before reuse. The complete
public API, scope, metadata, and benchmark contract are in
[Reactive Walk-Forward (W3)](reactive_wfo.md).

### Phase 77.3 Reactive Hot-State And Resource Closure

R2/R3 now pass the typed `quantbt-wake-wire-v1` tuple directly to Rust when a
strategy exposes `WakePlanV1.as_native_wire()`. The legacy payload adapter is
retained for older strategies, but the optimized path no longer builds or
parses a Python dictionary at each wake. Two symbol-sized observations refresh
in place while Rust advances no-decision bars, so a sparse/block gap does not
allocate a market/account snapshot per bar.

`RuntimeBudgetV1.max_wall_time_ms` and cancellation are active-work controls,
not metadata. R1 checks after each completed account bar. R2/R3 detached
native gaps check at most every 64 completed account bars and again before a
wake/end return. Rust never aborts inside a bar/accounting step or a Python
callback; it raises at the next certified boundary, discards the scalar output,
and requires/reset-clears state before an independent score. W3 propagates a
deadline as `RuntimeBudgetError(code="MAX_WALL_TIME")`, including the COW
process worker and R3B candidate-batch path.

The current-candidate artifact
`benchmarks/native_event/results/phase77_3_reactive_closure.{json,md}` records
R1/R2/R3 retention, W3 schedules, cross-route controls, and source/native
identity. It remains a development evidence artifact until the separate Phase
78 promotion/release gate.

## Phase 63 Sparse Wake, Block Intent, And Candidate Batch R2/R3/R3B

Phase 63 extends the explicit reactive co-runtime without creating a second
Python state machine. `ReactiveNumericRunnerCore` remains the sole authority
for prepared market data, event clock, active-order lifecycle, matching, fees,
funding, margin, liquidation, command retention, and compact native output.
Only the Python decision boundary changes:

```text
R2  Rust advances bars -> evaluates WakePlanV1 -> coalesces reasons -> Python once
R3  Rust advances a bounded command block -> invalidation/end -> Python once
R3B Rust advances independent candidate sessions -> groups same-bar wakes -> Python once
```

`WakePlanV1` contains only engine-observable conditions: time/timestamp, fill,
order event, liquidation, funding, price cross, position threshold, equity
threshold, and margin threshold. It replaces the prior plan in full. Rust
rejects inexact timestamps, unsupported rows, and non-finite levels. Same-bar
reasons are coalesced after market observation, funding, matching/fills,
lifecycle, and condition evaluation; `wake_trace` preserves the bit mask.

`BlockPlanV1` owns a half-open effective-bar range. The provider writes only
within `[start_bar, stop_bar)` and declares fill/reject/margin invalidation.
Rust removes only future unexecuted rows, labels them
`invalidated_before_execution`, and asks for a replacement block. It never
relabels invalidation as an exchange rejection.

R3B uses a shared immutable market tape for `1..64` independent `FullSession`
instances. Python receives a short-lived numeric batch context and a
candidate-scoped writer. Candidate failures are typed and local; malformed
batch callbacks fail deterministically. Results are flat SoA payloads per
candidate. This is intentionally a prepared primitive, not a hidden WFO or
Optuna loop.

All R2/R3/R3B routes are A3 explicit-only: matching capability marker,
`native_backend="rust"`, numeric context, and `reactive_kernel_mode="single_pass"`
are mandatory. R2/R3 require an independent every-bar shadow declaration;
`certify_reactive_shadow_v1` compares decision-boundary inputs, commands,
canonical execution/account trace, and optional strategy fingerprint. Auto
continues to use the conservative Python callback route.

Focused conformance coverage is in `tests/test_phase63_sparse_block_reactive.py`:
typed conditions, coalescing, plan replacement, timestamp rejection,
fill/reject/margin invalidation, cancellation provenance, candidate
isolation/order/capacity, stale handles, and reset. Reproduce the evidence:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase63_sparse_block_batch.py \
  --bars 10000 --cadence 32 --candidates 16 --repeats 3
```

It proves R1/R2/R3 accounting and canonical-trace parity on one tape before
measuring callback count, skipped bars, wake ratio, copy bytes, GIL transitions,
end-to-end timing, and RSS. R3B is reported separately as prepared
candidate-bars, not a public facade benchmark.

## Phase 65 Native WFO Runtime V2

Phase 65 adds an explicit A4 prepared WFO runtime for the bounded
single-symbol `strategy_ir_signal_target_v1` workload. Rust owns the immutable
market/fold/account plan, retained per-fold sessions, candidate x fold worker
queue, scalar metric rows, cancellation/recovery, and selected-candidate audit
rerun. Python owns W1/W2 causal signal generation and Optuna control.

This is not a promotion of generic `walk_forward()`. The W0 pandas/callback
engine remains the compatibility oracle. Target/notional/weight/order,
portfolio, and package intents remain fail-closed until their own
execution/accounting contracts exist. Reactive WFO now has its separate W3
contract through `prepare_reactive_walk_forward(...)`; it is limited to the
documented single-symbol, reset-flat lifecycle route and likewise cannot
impersonate a stitched continuous-account WFO result. See
[Reactive WFO](reactive_wfo.md) for its distinct selection, worker, and output
semantics.

The native score matrix contains no full paths or audit tables. A selected audit
replays the exact source batch fingerprint, not merely a newly generated
candidate row. `certified_sequential_v1` retains single ask/evaluate/tell
semantics; `throughput_batch_v1` is deterministic only by seed and batch size
and never claims sequential-TPE equivalence. See [Native WFO Runtime V2](native_wfo_runtime.md)
for the API and `benchmark_phase65_native_wfo.py` for reproducible parity/RSS
evidence.

## Phase 69 Rust Intrabar Authority

Phase 69 introduces `NativeIntrabarRequestCore` for one bounded strict-OHLC
symbol. It is deliberately a specialized Rust state machine rather than a
branch-heavy lowering into the generic static command engine. A prepared native
market is retained through an `Arc`; Python provides compact intent and optional
session arrays once; Rust performs the complete next-open bracket/accounting
run; only typed SoA output crosses the boundary after the run.

The frozen [`intrabar_bracket_v1` manifest](../contracts/intrabar_contract_v1.json)
defines the exact order:

```text
open gap mark -> open maintenance check -> open funding -> session control
-> stale cancellation -> technical exit/reversal -> entry -> bracket decision
-> close mark/liquidation -> trailing update -> close funding -> snapshot
```

The specialized request covers entry sizing, SL/TP level modes, stop and
target gaps, conservative/stop-first/TP-first/OHLC/OLHC ambiguity policy,
trailing updates, technical exits, session quotas and forced flat, funding,
quantity/tick constraints, margin, liquidation, and bounded audit buffers.
`reject_ambiguous` and `lower_timeframe_required` deliberately fail closed on
the Rust route. They are diagnostic/data-resolution policies, not hidden
fallbacks. The Python reference remains the readable oracle; Numba remains the
version-pinned rollback comparator for at least one stable release.

`intrabar_bracket_rust()` is explicit-only and produces the normal
`BacktestResultV2` cold-path surface for `minimal`, `standard`, and `audit`.
Audit fill rows include `ambiguity_flag` and `same_bar_policy_id`. Direct native
`score` is scalar-only by design and does not create a result/report object.
The route is not selected by `backend="auto"`, and it makes no claim for L2,
queue priority, partial-fill matching, grid/DCA state machines, multi-symbol
cross-margin, portfolio, package, or options execution.

The controlled 2,000-bar evidence records exact Python-reference/Numba/Rust
path and terminal parity, one native boundary, zero Python callbacks, bounded
audit retention, a direct score kernel of `20.90M bars/s`, and the separately
reported public adapter result of `788,099 bars/s`. See
[`phase69_rust_intrabar.md`](../benchmarks/native_event/results/phase69_rust_intrabar.md)
and [`phase69_rust_intrabar_v1.json`](../benchmarks/native_event/manifests/phase69_rust_intrabar_v1.json).
