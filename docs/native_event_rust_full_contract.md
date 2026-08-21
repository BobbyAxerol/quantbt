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

Reproduce the bounded E4/E5 evidence after building the local wheel:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run python \
  benchmarks/native_event/benchmark_phase54b3_portfolio_package.py \
  --bars 2000 --symbols 8 --repeats 5
```

The artifact records one same-process Python oracle parity check before timing,
engine-only versus cold adaptation time, boundaries/callbacks, retained output,
and current/peak RSS. Its numbers are local evidence for these two contracts
only; they do not generalize to the legacy portfolio engine or arbitrary
multi-leg strategies.

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
