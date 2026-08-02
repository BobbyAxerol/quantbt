# Native Event Rust V2 Full Contract

Phase 47B upgrades the optional PyO3 backend from the earlier R1/R2
single-symbol slice to the public Native Event V2 contract. Python/replay
remains the correctness oracle and `auto` remains Python until the later Grid
workload and release gates pass.

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

The existing terminal-order compaction runs only after a bar lifecycle is
complete. It preserves replacement aliases, parent activation, OCO cancellation,
GTD expiry and insertion priority. Reset clears logical state while retaining
capacity, and `release_step_buffer_capacity()` is an explicit maintenance
operation rather than a per-trial shrink.

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
