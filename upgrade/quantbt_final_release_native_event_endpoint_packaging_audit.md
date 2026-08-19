# QuantBT Final Release Audit & Last Upgrade Guide

**Branch audited**

```text
feat/quantbt-engine-packaging
```

**Release targets**

```text
quantbt-engine 1.0.7
quantbt-native 0.4.0       # preferred if native has not been published
Native Event ABI/API 0.4
```

**Re-audit correction**

```text
pyproject.toml version: 1.0.7
src/quantbt is the wheel source
root mirror is intentionally retained for Pool Alpha/local development
upgrade/implement.md is tracked and readable
```

The remaining `.gitignore` issue is not that `implement.md` is currently missing; it is that blanket rules can hide future engineering files.

**Priority**

```text
domain correctness
→ replay-certified parity
→ stable public endpoint
→ no RSS/runtime regression
→ packaging and release
```

---

# 1. Final verdict

## 1.1. Native Event domain contract

The latest branch has substantially met the important correctness requirement.

Rust API `0.4` now advertises and tests the public Native Event V2 surface:

```text
PLACE
CANCEL
CANCEL_ALL
AMEND
REPLACE

MARKET
LIMIT
STOP_MARKET
STOP_LIMIT

GTC
GTD
IOC
FOK

reduce-only
quantity preflight
parent-child
group
OCO
expiry

funding
initial margin
maintenance margin
liquidation

single-symbol
multi-symbol
```

The committed Grid evidence also shows Python/replay/Rust fingerprint parity for the tested 2,000-bar long-only and long-short workloads.

Therefore:

```text
Python backend:
    canonical/default implementation

Rust backend:
    correctness-certified for public Native Event V2
    explicit selector

replay_certified:
    deterministic audit oracle

auto:
    remains Python for 1.0.7
```

Keeping `auto` on Python is correct. Rust is extremely effective for batched/static command tapes, but the reactive Grid benchmark remains slower because the Python strategy callback owns almost all runtime.

## 1.2. Performance and RSS

The current RSS improvement is accepted.

```text
Previous process peak: approximately 365 MB
Current accepted level: approximately 180 MB
```

Do not retain a hard “must reduce another 40%” gate.

Use:

```text
no unexplained regression above 10–15%
no positive repeated-run RSS slope
no trial-by-trial object retention
no unbounded tape/order cache
```

The final optimization pass should preserve semantics and remove obvious allocation debt. It does not need to force Rust to beat Python on every reactive strategy.

## 1.3. Release readiness

`quantbt-engine` is close to publishable, but the branch still has several final blockers.

### P0 blockers

1. Native CI still asserts API `0.3`, while the implementation and full contract are API `0.4`.
2. `docs/release_packaging.md` still describes the old R2 Rust restriction.
3. Root/`src/quantbt` mirror test remains one-directional.
4. `.gitignore` ignores all of `upgrade/` and `benchmarks/`.
5. Public endpoint usage is still too dependent on phase-specific low-level flags.
6. TestPyPI workflow builds and tests, but should clean-install the exact built artifacts before publishing.
7. Public dual-backend installation is incomplete while `[native]` remains empty.

After these are corrected and CI is green on the exact release SHA, the package is ready for TestPyPI.

---

# 2. Corrections that must be made before merge

## 2.1. Fix Native CI API mismatch

Current native workflow still checks:

```python
assert _quantbt_native.api_version() == "0.3"
```

Change to API `0.4` and verify every required capability.

```yaml
- name: Clean combined core and native wheel install smoke
  shell: bash
  run: |
    python -m venv /tmp/quantbt-native-combined-smoke
    /tmp/quantbt-native-combined-smoke/bin/python -m pip install --upgrade pip
    /tmp/quantbt-native-combined-smoke/bin/python -m pip install \
      dist/core/quantbt_engine-*.whl \
      dist/native/quantbt_native-*.whl

    cd /tmp
    /tmp/quantbt-native-combined-smoke/bin/python - <<'PY'
    from quantbt import QuantBTEndpoint
    import _quantbt_native

    assert _quantbt_native.api_version() == "0.4"

    capabilities = _quantbt_native.capabilities()

    required = {
        "native_event_v2_full_contract",
        "native_event_v2_multisymbol",
        "native_event_v2_funding",
        "native_event_v2_liquidation",
        "native_event_v2_cancel_all_oco",
        "native_event_v2_tif_expiry",
        "native_event_v2_relationships",
        "native_event_v2_quantity_preflight",
    }

    missing = {
        key
        for key in required
        if not capabilities.get(key, False)
    }

    assert not missing, sorted(missing)
    print(QuantBTEndpoint)
    PY
```

Rename the workflow and jobs away from `R0` terminology:

```text
native-r0.yml
→ native.yml

Native PyO3 Gate
→ Native Event API 0.4 Gate
```

A compatibility redirect is unnecessary for workflow filenames.

## 2.2. Add the native wheel matrix

The current native job only builds Python 3.12 on the Ubuntu host.

For a public native package, build at least:

```text
CPython 3.11
CPython 3.12
CPython 3.13
Linux x86_64 manylinux2014 / manylinux_2_17
```

Recommended job skeleton:

```yaml
strategy:
  fail-fast: false
  matrix:
    python-version: ["3.11", "3.12", "3.13"]

steps:
  - uses: actions/checkout@v4

  - uses: actions/setup-python@v5
    with:
      python-version: ${{ matrix.python-version }}

  - uses: dtolnay/rust-toolchain@stable

  - uses: PyO3/maturin-action@v1
    with:
      command: build
      args: >
        --release
        --manifest-path rust/native_event/Cargo.toml
        --interpreter python${{ matrix.python-version }}
        --out dist/native
      manylinux: "2014"
```

Each produced wheel must be installed in a fresh environment together with the core wheel and run:

```text
API/capability smoke
full Rust contract tests
Python/replay/Rust parity tests
Grid integration smoke
pip check
```

Do not use a locally built non-manylinux Ubuntu wheel as the public artifact.

## 2.3. Update stale packaging documentation

`docs/release_packaging.md` still describes the old R1/R2 boundary:

```text
one symbol
GTC only
no funding
no OCO
no liquidation
```

That now contradicts:

```text
docs/native_event_rust_full_contract.md
docs/grid_native_event_phase47c.md
docs/endpoint.md
```

Replace the old section with:

```markdown
## Native Event Rust API 0.4

The optional native package implements the public Native Event V2
contract certified by the shared Python/replay/Rust conformance suite.

`native_backend="rust"` is explicit and fail-fast.
`native_backend="auto"` remains Python in quantbt-engine 1.0.7.

See:

- `docs/native_event_rust_full_contract.md`
- `docs/grid_native_event_phase47c.md`
```

Keep R0/R1/R2 history only under a clearly labelled historical section.

## 2.4. Upgrade mirror verification to two directions

The existing test proves:

```text
every src/quantbt Python file has an identical root counterpart
```

It does not detect an extra Python file created only in the root mirror.

Use an explicit manifest so `tests`, `tools`, and benchmark scripts are not mistaken for package files.

```python
from __future__ import annotations

import hashlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = PROJECT_ROOT / "src" / "quantbt"

MIRROR_ENTRIES = (
    "__init__.py",
    "backtester.py",
    "endpoint.py",
    "engines.py",
    "portfolio.py",
    "walkforward.py",
    "adapters",
    "backends",
    "core",
    "metrics",
    "optimization",
    "options",
    "reporting",
    "sizing",
    "viz",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_files() -> dict[Path, Path]:
    return {
        path.relative_to(CANONICAL_ROOT): path
        for path in CANONICAL_ROOT.rglob("*.py")
    }


def _mirror_files() -> dict[Path, Path]:
    files: dict[Path, Path] = {}

    for entry_name in MIRROR_ENTRIES:
        entry = PROJECT_ROOT / entry_name

        if entry.is_file() and entry.suffix == ".py":
            files[Path(entry.name)] = entry
        elif entry.is_dir():
            for path in entry.rglob("*.py"):
                files[path.relative_to(PROJECT_ROOT)] = path

    return files


def test_root_and_src_python_trees_are_byte_identical() -> None:
    canonical = _canonical_files()
    mirror = _mirror_files()

    assert canonical.keys() == mirror.keys(), (
        f"missing_from_root={sorted(canonical.keys() - mirror.keys())}; "
        f"extra_in_root={sorted(mirror.keys() - canonical.keys())}"
    )

    for relative in sorted(canonical):
        assert _sha256(canonical[relative]) == _sha256(mirror[relative]), (
            f"root/src source drift: {relative}"
        )
```

Keep:

```text
src/quantbt = wheel source of truth
root mirror = local Pool Alpha compatibility source
```

Add a one-directional sync tool with explicit direction:

```bash
uv run python tools/sync_source_mirror.py --src-to-root
uv run python tools/sync_source_mirror.py --root-to-src
uv run python tools/sync_source_mirror.py --check
```

Never merge both trees automatically.

---

# 3. Stable endpoint design

## 3.1. Current pain point

Native Event currently exposes several low-level controls:

```text
native_backend
reactive_execution_mode
reactive_kernel_mode
report_level
audit_sink
audit_sink_path
```

They are useful internally, but they should not be the normal open-source quick start.

Do not remove or rename existing methods in `1.0.7`.

Keep:

```python
QuantBTEndpoint.native_event_strategy(...)
QuantBTEndpoint.native_event_lifecycle(...)
QuantBTEndpoint.orders(...)
```

Add one canonical facade that only delegates to existing constructors.

## 3.2. Canonical public facade

```python
QuantBTEndpoint.event_driven(
    input_mode="strategy",   # strategy | orders
    profile="research",      # research | optimize | audit
    backend="auto",          # auto | python | rust
    ...
)
```

Implementation:

```python
class NativeEventProfile(str, Enum):
    RESEARCH = "research"
    OPTIMIZE = "optimize"
    AUDIT = "audit"


_NATIVE_EVENT_PROFILES = {
    NativeEventProfile.RESEARCH: {
        "reactive_execution_mode": "fast",
        "reactive_kernel_mode": "single_pass",
        "report_level": "minimal",
        "audit_sink": "none",
    },
    NativeEventProfile.OPTIMIZE: {
        "reactive_execution_mode": "fast",
        "reactive_kernel_mode": "single_pass",
        "report_level": "score",
        "audit_sink": "none",
    },
    NativeEventProfile.AUDIT: {
        "reactive_execution_mode": "audit",
        "reactive_kernel_mode": "replay_certified",
        "report_level": "audit",
        "audit_sink": "memory",
    },
}
```

```python
@classmethod
def event_driven(
    cls,
    *,
    input_mode: str = "strategy",
    profile: str = "research",
    backend: str = "auto",
    **kwargs,
) -> "QuantBTEndpoint":
    resolved = _resolve_native_event_profile(
        profile=profile,
        backend=backend,
        kwargs=kwargs,
    )

    if input_mode == "strategy":
        return cls.native_event_strategy(**resolved)

    if input_mode == "orders":
        return cls.native_event_lifecycle(**resolved)

    raise ValueError(
        "input_mode must be 'strategy' or 'orders'"
    )
```

Map:

```text
backend="auto"   → native_backend="auto"
backend="python" → native_backend="python"
backend="rust"   → native_backend="rust"
```

Do not expose `replay_certified` as a language backend through the new facade. It is validation/accounting mode, not an implementation language.

Keep the old selector accepted for backward compatibility, but document:

```text
new public API:
    backend + profile

advanced/backward-compatible API:
    native_backend
    reactive_execution_mode
    reactive_kernel_mode
    report_level
    audit_sink
```

## 3.3. Conflict rules

A user should not accidentally request contradictory policies.

Raise when profile-controlled low-level options are supplied together:

```python
QuantBTEndpoint.event_driven(
    profile="optimize",
    report_level="audit",
)
```

Error:

```text
profile='optimize' controls report_level;
use the advanced native_event_strategy constructor
for custom low-level combinations
```

Do not silently override user arguments.

## 3.4. Stable usage examples

### Simple reactive strategy

```python
endpoint = QuantBTEndpoint.event_driven(
    input_mode="strategy",
    profile="research",
    backend="auto",
    initial_capital=20_000,
    leverage=5,
    maintenance_ratio=0.005,
    fee_rate=0.0005,
    slippage_bps=2.0,
    use_funding=True,
)

result = endpoint.simulate(
    data=data,
    strategy=strategy,
    symbols=["ETHUSDT"],
)
```

### Optimization

```python
endpoint = QuantBTEndpoint.event_driven(
    input_mode="strategy",
    profile="optimize",
    backend="python",
    initial_capital=20_000,
    leverage=5,
)

prepared = endpoint.prepare_native_event_strategy(
    data=data,
    symbols=["ETHUSDT"],
)

score = prepared.score(
    fresh_strategy,
    trading_days=365,
    score_requirements=(
        NativeEventScoreRequirements
        .from_strategy(
            fresh_strategy,
            base=(
                NativeEventScoreRequirements
                .scalar_score_contract()
            ),
        )
    ),
)
```

### Final audit

```python
endpoint = QuantBTEndpoint.event_driven(
    input_mode="strategy",
    profile="audit",
    backend="python",
    initial_capital=20_000,
    leverage=5,
)

result = endpoint.simulate(
    data=data,
    strategy=fresh_strategy,
    symbols=["ETHUSDT"],
)
```

### Explicit order tape

```python
endpoint = QuantBTEndpoint.event_driven(
    input_mode="orders",
    profile="audit",
    backend="rust",
    initial_capital=20_000,
    leverage=5,
)

result = endpoint.simulate(
    data=data,
    order_commands=commands,
    symbols=symbols,
)
```

## 3.5. Strategy protocol

Publish one documented framework instead of one endpoint per alpha.

```python
class NativeEventStrategy(Protocol):
    native_context_requirements: (
        NativeEventScoreRequirements
    )

    def initialize(
        self,
        context: NativeStrategyContext,
    ) -> Sequence[OrderCommand]:
        ...

    def on_bar_close(
        self,
        context: NativeStrategyContext,
    ) -> Sequence[OrderCommand]:
        ...

    def finalize(
        self,
        context: NativeStrategyContext,
    ) -> Sequence[OrderCommand]:
        ...
```

Document three alpha levels:

```text
1. Target/signal alpha
   → normal vectorized/intrabar endpoint

2. Precomputed explicit orders
   → event_driven(input_mode="orders")

3. Stateful reactive execution
   → event_driven(input_mode="strategy")
```

Grid belongs to level 3.

No Grid-specific endpoint is needed.

## 3.6. Endpoint tests

Add:

```text
test_event_driven_research_profile_mapping
test_event_driven_optimize_profile_mapping
test_event_driven_audit_profile_mapping
test_event_driven_strategy_delegates_without_semantic_change
test_event_driven_orders_delegates_without_semantic_change
test_profile_low_level_conflict_raises
test_existing_native_event_strategy_is_unchanged
test_existing_native_event_lifecycle_is_unchanged
```

The facade must be a configuration resolver only. It must not create a second execution implementation.

---

# 4. Python backend final optimization

## 4.1. What is already correct

The branch already has the important score-path behavior:

```text
prepared market reuse
single-pass score accounting
scalar online metrics
no public pandas result in optimizer trials
endpoint.result remains None
strategy/result not retained by evaluator
minimal context requirements
Grid diagnostics disabled in scalar trials
```

The Grid profile shows alpha preparation is a small part of total runtime; the reactive callback dominates. Do not add a large indicator cache to core QuantBT based on this workload.

## 4.2. Safe final optimizations

### Lazy context materialization

Only build these when the strategy requests them:

```text
fills_this_bar
order_events_this_bar
active_orders
positions
margin fields
```

Default requirements must preserve compatibility for strategies that do not declare a contract.

### Reusable context container

Reuse the internal context object and replace read-only views each bar instead of constructing a new graph of lists/dicts.

Do not expose mutable engine state.

### Compact active-order state

Internally retain primitive fields rather than complete `OrderCommand` objects where full commands are not needed.

Keep metadata only when requested by audit or by the strategy context contract.

### Bounded caches

Every prepared tape/market cache must have:

```text
byte or entry limit
clear() method
observable size/counters
```

No global unbounded cache.

### Score-mode terminal cleanup

After a trial:

```text
terminal orders released
temporary command batches cleared
audit buffers cleared
no endpoint.result
no evaluator.last_strategy/result when retain_last=False
```

## 4.3. Do not do in the final pass

Do not:

```text
Numba-compile arbitrary Python callbacks
change next-bar command timing
remove active-order snapshots required by Grid
reuse a stateful strategy instance across trials
cache mutable strategy state
disable funding/OCO/liquidation for speed
```

A restricted native strategy DSL could remove callback overhead later, but that is a new product/API phase and is outside `1.0.7`.

---

# 5. Python and Rust Native Event final performance pass

This section is the last optimization scope before release.

The objective is not to chase a benchmark number at the cost of semantics.

```text
written domain invariants
→ replay_certified
→ Python single-pass
→ Rust API 0.4
→ performance/RSS optimization
```

Every patch below must preserve:

```text
command effective bar
stable order priority
fills and reject reasons
parent/group/OCO lifecycle
funding
margin and liquidation ordering
positions, equity and fees
public endpoint/result contracts
```

## 5.1. Current performance interpretation

Keep two performance claims separate.

### Static/precompiled order tape

```text
Rust batched score/audit:
    strong native acceleration
    few Python↔Rust transitions
    correct place to advertise Rust speedup
```

### Arbitrary Python reactive strategy

```text
Python strategy callback:
    still executes on every required bar

Rust:
    accelerates matching/accounting/lifecycle
    cannot remove arbitrary Python callback cost
```

A reactive Rust run is allowed to be close to or slightly slower than Python when callback and Python object work dominate. The final pass should reduce bridge and allocation overhead, but it must not change callback timing or strategy behavior.

Accepted RSS baseline:

```text
approximately 180 MB for the accepted workload
```

Final gate:

```text
no unexplained runtime regression
no RSS regression above 10–15%
no positive repeated-run RSS slope
no state/cache growth proportional to trial count
```

## 5.2. Concrete hotspots in the current API 0.4 implementation

The current full-contract Rust path still has several structural costs.

### Prepared market is cloned into each full session

`FullPreparedMarketCore` owns prepared market data, but `FullSessionCore.from_prepared(...)` currently obtains the prepared market and then clones the complete `FullMarketData` value before constructing a session.

This duplicates:

```text
timestamps
OHLCV
funding
funding mask
```

for each session.

### Full session retains terminal orders

The full-contract engine stores:

```rust
orders: Vec<OrderState>
id_to_slot: HashMap<i64, usize>
```

Filled, canceled, expired and rejected orders remain in `orders`.

Consequences:

```text
RSS grows with total historical orders
bar scans become slower over long runs
active-order snapshot scans terminal state
relationship operations scan inactive orders
```

The legacy R1/R2 kernel already has a better slot/free-list order table. The API 0.4 full session should use the same general design rather than a permanently growing vector.

### Relationship and expiry operations scan all orders

The full session currently performs broad scans for:

```text
GTD expiry
parent activation
OCO sibling cancellation
CANCEL_ALL filtering
active-order snapshots
```

These operations should be indexed while preserving stable execution priority.

### Full reactive step materializes too much

Each full step currently constructs:

```text
Vec<Vec<f64>> fills
Vec<Vec<i64>> events
Vec<Vec<f64>> active_orders
positions.clone()
PyDict payload
```

This happens even when a score/optimizer path only needs scalar accounting and the strategy requests a smaller context.

Nested vectors create many heap allocations and Python conversion work.

### Full reactive command compilation lacks the reusable R1 buffer contract

The older R1/R2 Python adapter already has a capacity-managed `RustCommandBuffer`.

The API 0.4 full command ABI is wider and includes:

```text
symbol
TIF
parent/group/OCO
activation
expiry
sequence
```

It needs an equivalent reusable full-contract buffer. Do not allocate new `codes`, `values` and `expiry` arrays on every callback bar.

### Full tape score does not consistently release the GIL

Long static tape and sparse chunk calls should execute outside the GIL. Per-bar reactive calls require measurement because releasing/reacquiring the GIL every bar may cost more than it saves.

## 5.3. P1 — eliminate prepared-market duplication

Change full market ownership to immutable shared ownership.

Preferred Rust shape:

```rust
pub struct FullSession {
    market: Arc<FullMarketData>,
    // mutable account/lifecycle state only
}
```

Constructor:

```rust
impl FullSession {
    pub fn new(
        market: Arc<FullMarketData>,
        contract_sizes: Box<[f64]>,
        leverages: Box<[f64]>,
        fee_rates: Box<[f64]>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage: f64,
        use_funding: bool,
    ) -> Result<Self, String> {
        // validation only; do not clone market arrays
    }
}
```

PyO3 prepared path:

```rust
let market = prepared.borrow(py).inner.clone();

let inner = FullSession::new(
    market,
    contract_sizes.as_slice()?.to_vec().into_boxed_slice(),
    leverages.as_slice()?.to_vec().into_boxed_slice(),
    fee_rates.as_slice()?.to_vec().into_boxed_slice(),
    initial_capital,
    maintenance_ratio,
    slippage_rate,
    use_funding,
)?;
```

Requirements:

```text
prepared market immutable
many sessions may share one market
session reset never mutates market
Python wrapper does not retain duplicate DataFrame/OHLC arrays
```

After constructing `FullPreparedMarketCore`, release temporary Python normalized arrays when they are not needed by the Python backend.

Tests:

```text
two sessions share one prepared market
reset does not change market
full parity is exact
prepared-session incremental RSS is near account/order state only
```

This is the highest-confidence RSS optimization still available.

## 5.4. P2 — replace the growing full order vector with an arena

Use a stable-priority slot table:

```rust
struct FullOrderArena {
    slots: Vec<FullOrderSlot>,
    id_to_slot: OrderIdMap,
    active_sequence: Vec<usize>,
    free_slots: Vec<usize>,
    tombstones: usize,
    active_count: usize,
}

struct FullOrderSlot {
    occupied: bool,
    order: OrderState,
}
```

Rules:

```text
PLACE:
    reuse a free slot or append

CANCEL/FILL/EXPIRE/REJECT:
    mark terminal
    remove active ID mapping
    return slot to free list only when safe

Priority:
    always follows active_sequence
    never depends on HashMap iteration
    never swap-remove active priority
```

A free slot must not be reused while an old slot index is still referenced by relationship indexes. Either remove those index entries at terminal transition or attach a generation number:

```rust
struct SlotRef {
    slot: usize,
    generation: u32,
}
```

Use an identity hasher for dense/interned `i64` order IDs, as the legacy session already does.

Compaction policy:

```text
compact active_sequence only when tombstones exceed:
    max(64, active_sequence.len() / 3)
```

Compaction must preserve relative order.

Tests:

```text
stable insertion/fill priority after slot reuse
replace alias resolution remains exact
100k terminal orders do not retain 100k active payloads
reset reuses capacity without retaining logical state
```

## 5.5. P3 — add relationship and expiry indexes

Do not rescan every historical order.

Maintain:

```rust
children_by_parent: HashMap<i64, Vec<SlotRef>>
members_by_oco: HashMap<i64, Vec<SlotRef>>
members_by_group: HashMap<i64, Vec<SlotRef>>
expiry_by_bar: Vec<Vec<SlotRef>>
```

For dense interned identifiers, a `Vec<Vec<SlotRef>>` may be faster and smaller than a general-purpose hash map. Choose based on actual ID density, not assumption.

### Parent activation

On a parent fill:

```text
look up children_by_parent[parent_id]
validate slot generation/status
activate only matching waiting children
```

### OCO cancellation

On fill:

```text
look up members_by_oco[oco_id]
cancel pending siblings only
preserve event ordering from replay oracle
```

### GTD expiry

At bar `b`:

```text
process expiry_by_bar[b]
do not scan all orders
```

### CANCEL_ALL

Fast indexed paths are possible for common filters:

```text
all orders
symbol
side
group
OCO
parent
```

For a rare compound filter, scan only active slots, not all historical slots.

Do not change the order in which cancellation events are emitted. The index must return slots in stable insertion order.

## 5.6. P4 — output requirements inside the Rust full session

Introduce an internal output contract aligned with `NativeEventScoreRequirements`.

```rust
#[derive(Clone, Copy)]
pub struct FullOutputRequirements {
    pub positions: bool,
    pub fills: bool,
    pub events: bool,
    pub active_orders: bool,
    pub margin: bool,
    pub audit_paths: bool,
}
```

Three internal profiles:

```text
score:
    scalar accounting/counters only

reactive_context:
    only fields requested by strategy

audit:
    complete paths and ledgers
```

The full step should not unconditionally:

```text
clone positions
create fills vectors
create event vectors
scan/materialize active orders
```

Example:

```rust
pub fn step(
    &mut self,
    bar: usize,
    codes: &[i64],
    values: &[f64],
    expiry: &[i64],
    command_count: usize,
    requirements: FullOutputRequirements,
) -> Result<FullStepResult, String>
```

Compatibility:

```text
old `step()`:
    delegates with full/default requirements

new internal `step_required()`:
    used by optimized Python adapter
```

Public Python strategy behavior remains unchanged unless it declares narrower requirements.

## 5.7. P5 — reusable structure-of-arrays result buffers

Replace nested vectors:

```rust
Vec<Vec<f64>>
Vec<Vec<i64>>
```

with reusable SoA buffers.

```rust
struct FullStepBuffers {
    fill_order_id: Vec<i64>,
    fill_symbol: Vec<i32>,
    fill_side: Vec<i8>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,

    event_kind: Vec<i16>,
    event_status: Vec<i16>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
    event_symbol: Vec<i32>,
    event_reject_code: Vec<i16>,

    active_order_id: Vec<i64>,
    active_symbol: Vec<i32>,
    active_side: Vec<i8>,
    active_type: Vec<i8>,
    active_qty: Vec<f64>,
    active_price: Vec<f64>,
    active_trigger: Vec<f64>,
    active_tif: Vec<i8>,
    active_flags: Vec<u16>,
    active_parent: Vec<i64>,
    active_group: Vec<i64>,
    active_oco: Vec<i64>,
}
```

At each step:

```rust
buffers.clear();
```

`clear()` retains capacity.

Do not shrink buffers every bar. Add an explicit maintenance method for services that want to return oversized buffers:

```rust
session.release_excess_capacity(max_bytes)
```

Audit output may convert each vector to NumPy once at the boundary.

Reactive context should decode only arrays requested by the strategy.

## 5.8. P6 — typed PyO3 step and sparse results

`PyDict` is acceptable for infrequent audit setup, but it should not be the default per-bar hot result.

Add frozen typed classes:

```rust
#[pyclass(frozen)]
struct FullStepResultCore {
    #[pyo3(get)]
    equity: f64,
    #[pyo3(get)]
    fee: f64,
    #[pyo3(get)]
    turnover: f64,
    #[pyo3(get)]
    funding: f64,
    #[pyo3(get)]
    initial_margin: f64,
    #[pyo3(get)]
    maintenance_margin: f64,
    #[pyo3(get)]
    liquidated: bool,
    #[pyo3(get)]
    liquidation_bar: i64,
    #[pyo3(get)]
    liquidation_reason: i16,
    // optional arrays/views
}
```

Also replace sparse `run_until()` dictionaries with:

```rust
#[pyclass(frozen)]
struct SparseChunkResultCore
```

Benefits:

```text
fewer hash lookups
clear ABI fields
less Python allocation
easier version compatibility testing
```

Keep dictionary conversion in the Python adapter only for backward-compatible metadata/results where needed.

## 5.9. P7 — full-contract reusable Python command buffer

Add:

```python
@dataclass
class RustFullCommandBuffer:
    codes: np.ndarray
    values: np.ndarray
    expiry: np.ndarray
    capacity: int = 0

    def reserve(
        self,
        size: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        ...
```

The full ABI widths must be canonical constants exported by the extension or a shared Python ABI module.

Do not duplicate integer layouts in multiple files.

Suggested single source:

```python
from quantbt.backends._native_event_abi import (
    FULL_COMMAND_CODE_WIDTH,
    FULL_COMMAND_VALUE_WIDTH,
    NativeEventAbiVersion,
)
```

Compiler behavior:

```text
reuse arrays
fill only [:n]
do not tuple-copy commands unless audit requires originals
intern symbol/order/group/OCO IDs once
reuse stable enum→integer tables
```

Avoid calling `np.full`/`np.zeros` for every reactive bar.

Expose counters:

```text
command_buffer_capacity
command_buffer_growth_count
commands_compiled
ID table size
```

## 5.10. P8 — Python context reuse and lazy projections

The Python backend and Rust adapter should share one context requirements model.

For each strategy:

```python
requirements = (
    NativeEventScoreRequirements
    .from_strategy(
        strategy,
        base=NativeEventScoreRequirements.scalar_score_contract(),
    )
)
```

Internal context should reuse one container:

```python
@dataclass(slots=True)
class _MutableNativeContext:
    bar_index: int
    timestamp: object
    equity: float
    liquidated: bool
    # references replaced per bar
```

Public callback receives read-only tuple/array views.

Do not construct when not requested:

```text
order event objects
active-order objects
positions dictionaries
margin dictionaries
metadata copies
```

### Active-order generation cache

Maintain:

```text
active_generation
cached_snapshot_generation
cached_snapshot
```

Only rebuild a Python active-order snapshot when:

```text
an order lifecycle mutation occurred
and the strategy requested active_orders
```

A bar with no lifecycle change may reuse the immutable snapshot tuple.

### Metadata

For score mode:

```text
preserve only metadata fields requested by the strategy contract
```

For audit:

```text
preserve full metadata
```

Default behavior for an undeclared strategy remains full compatibility.

## 5.11. P9 — remove duplicate Python retention

Prepared Rust runners must not retain:

```text
original DataFrame
normalized Python market arrays
Rust-owned market arrays
```

at the same time unless Python fallback is explicitly requested.

Use separate prepared types:

```text
PreparedPythonNativeEventMarket
PreparedRustNativeEventMarket
```

`backend="rust"`:

```text
normalize temporary arrays
create Rust prepared market
drop temporary DataFrame/arrays
retain only index/symbol metadata required for result adaptation
```

`backend="auto"` remains Python in `1.0.7`, so it should not eagerly prepare both.

## 5.12. P10 — session reset and bounded retention

Session reuse is useful only with exact reset semantics.

`reset()` must clear logical state:

```text
positions/equity
liquidation
active orders
ID mappings
parent/group/OCO/expiry indexes
scheduled commands
per-bar payload maps
audit counters
last bar
```

It may retain allocated capacity.

Add tests:

```text
fresh session vs reset session exact parity
100 repeated runs produce identical fingerprint
post-run RSS reaches a plateau
terminal order count returns to zero
cache sizes remain bounded
```

Expose:

```python
prepared.clear_caches()
prepared.cache_info()
session.capacity_info()
```

No hidden global cache.

## 5.13. P11 — GIL policy

Use `py.detach(...)` around long Rust-only operations:

```text
run_tape_score
run_tape_audit
long run_until chunks
full static tape
```

For per-bar reactive `step`:

```text
benchmark both modes
do not detach/reacquire automatically if the call is very short
```

A practical rule:

```text
static/chunk call:
    release GIL

single reactive bar:
    keep GIL by default
    only enable detach after measured benefit
```

No Python callback may execute while detached.

## 5.14. P12 — Rust release profile

Portable public wheels:

```toml
[profile.release]
opt-level = 3
lto = "thin"
codegen-units = 1
strip = "symbols"
debug = 0
overflow-checks = false
```

Do not use:

```text
target-cpu=native
```

for public wheels because it may produce binaries that fail on other machines.

`target-cpu=native` is acceptable only for a separate local benchmark build.

Do not use `panic = "abort"` merely for speed in this release. A panic should not terminate a research service process; keep errors converted to Python exceptions.

## 5.15. P13 — code structure and legacy isolation

The Python adapter is currently very large and contains legacy R1/R2 plus API 0.4 paths.

Split without changing imports:

```text
_native_event_rust.py
    compatibility exports and backend selector

_native_event_rust_probe.py
    binary/API/capability detection

_native_event_rust_abi.py
    shared ABI constants and integer layouts

_native_event_rust_legacy.py
    API 0.3 R1/R2 compatibility

_native_event_rust_full.py
    API 0.4 compiler, session and result adapter

_native_event_rust_batched.py
    static tape and sparse chunk runner
```

`_native_event_rust.py` re-exports every existing public/internal name used by tests.

Rust source:

```text
full.rs
    should be split only after performance/correctness patches stabilize

later:
    full/order_arena.rs
    full/relationships.rs
    full/accounting.rs
    full/output.rs
```

Do not mix a large refactor with a domain logic rewrite in one patch.

## 5.16. Performance observability

Add counters to both backends:

```text
bars_processed
commands_emitted
commands_compiled
fills
events
active_orders_peak
order_slots_peak
terminal_slots
order_arena_compactions
command_buffer_growths
active_snapshot_materializations
positions_materializations
bytes_copied_to_rust
bytes_returned_to_python
GIL-released calls
cache bytes/entries
```

Benchmark output must include the full parity fingerprint.

Without these counters, a faster result can hide missing work.

## 5.17. Optimization patch order

### Optimization O1 — shared prepared market

```text
Arc<FullMarketData>
no session market clone
drop duplicate Python references
```

Expected:

```text
largest low-risk RSS improvement
```

### Optimization O2 — conditional outputs and SoA buffers

```text
FullOutputRequirements
no unconditional positions clone
reusable fill/event/active SoA
typed result classes
```

Expected:

```text
large reactive bridge/allocation improvement
```

### Optimization O3 — full order arena and indexes

```text
free-list slots
stable active sequence
parent/OCO/group/expiry indexes
active-only CANCEL_ALL
```

Expected:

```text
largest long-run/high-churn Rust speed and RSS improvement
```

### Optimization O4 — Python full command/context reuse

```text
RustFullCommandBuffer
lazy context fields
active snapshot generation cache
bounded metadata
```

Expected:

```text
reduces Python callback bridge overhead
```

### Optimization O5 — reset/caches and release build

```text
reset parity
capacity counters
bounded caches
thin LTO portable wheels
```

After every optimization:

```text
run golden domain fixtures
run replay/Python/Rust full parity
run Grid long-only and long-short
run repeated RSS benchmark
```

Do not combine all patches before testing.

## 5.18. Final performance acceptance

No new hard speedup ratio is required.

Required:

```text
full domain parity remains exact
Python score path does not regress materially
Rust static tape remains faster than Python scalar baseline
Rust reactive bridge/allocation improves or remains neutral
accepted RSS baseline does not regress above 10–15%
100 repeated runs plateau
```

Nice-to-have:

```text
lower command compile time
fewer active snapshot materializations
lower high-churn order scan time
lower incremental Rust session RSS
```

Reject any optimization that:

```text
changes one fill
changes command/event ordering
changes funding or liquidation timing
uses unsafe borrowed NumPy lifetimes
introduces an unbounded cache
silently falls back from explicit Rust to Python
```

# 6. Domain and parity gate

## 6.1. Oracle hierarchy

```text
written domain invariants/golden fixtures
→ replay_certified
→ Python single-pass
→ Rust
```

Do not certify Rust only against Python when Python has not passed replay parity.

## 6.2. Required comparisons

Discrete exact equality:

```text
command sequence
effective bar
accept/reject
reject reason
order status
fill/no-fill
fill bar
parent activation
OCO cancellation
expiry
liquidation decision/bar
```

Numeric path:

```text
quantity
price
fees
funding
position
equity
initial margin
maintenance margin
```

Prefer:

```python
np.testing.assert_array_equal(...)
```

Use only where unavoidable:

```python
np.testing.assert_allclose(
    ...,
    rtol=0.0,
    atol=1e-12,
)
```

A numeric tolerance cannot hide a discrete lifecycle difference.

## 6.3. Required conformance matrix

```text
single and multi-symbol
all command actions
all order types
all TIF modes
quantity constraints
reduce-only
parent/group/OCO
funding
margin
liquidation
reactive context snapshots
score and audit result contracts
```

## 6.4. Backend policy

```text
backend="python":
    full/default

backend="rust":
    explicit and fail-fast
    no silent Python fallback

backend="auto":
    Python in 1.0.7

profile="audit":
    replay-certified validation path
```

---

# 7. `.gitignore`, source visibility and secret safety

## 7.1. Current branch state

The branch currently ignores:

```gitignore
upgrade/
benchmarks/
!src/quantbt/benchmarks/
!src/quantbt/benchmarks/**
```

`upgrade/implement.md` is still readable because it was already tracked before the ignore rule. A tracked file continues to receive modifications.

The real problem is future visibility:

```text
existing tracked implement.md:
    changes remain visible

new files under upgrade/:
    may silently disappear from git status

new root benchmark scripts/evidence:
    may silently disappear from git status
```

For an open-source, agent-auditable repository, do not blanket-ignore engineering plans or accepted benchmark evidence.

## 7.2. Intended policy

Public and tracked:

```text
upgrade/implement.md
source code
tests
tools
workflows
docs
benchmark scripts
accepted benchmark summaries
parity fingerprints
small deterministic fixtures
```

Ignored:

```text
credentials and tokens
private keys
machine-local configuration
raw/private market data
virtual environments
build artifacts
native compiler output
large profiler traces
temporary/local benchmark output
private drafts
```

GitHub visibility and PyPI artifact contents are separate concerns.

```text
.gitignore:
    controls untracked local files

pyproject/setuptools/MANIFEST and artifact inspection:
    control wheel/sdist contents
```

## 7.3. Recommended `.gitignore`

Replace the blanket `upgrade/` and `benchmarks/` rules with selective patterns.

```gitignore
# ============================================================
# Python bytecode, tests and tooling caches
# ============================================================

__pycache__/
*.py[cod]
*$py.class

.pytest_cache/
.mypy_cache/
.ruff_cache/
.hypothesis/

.coverage
.coverage.*
htmlcov/


# ============================================================
# Python packaging/build output
# ============================================================

dist/
build/
*.egg-info/
*.egg
pip-wheel-metadata/


# ============================================================
# Virtual environments
# ============================================================

.venv/
venv/
env/
ENV/


# ============================================================
# Rust / PyO3 build output
# ============================================================

rust/**/target/
.maturin/

*.so
*.pyd
*.dylib


# ============================================================
# Notebook/editor/OS files
# ============================================================

.ipynb_checkpoints/
*.ipynb_checkpoints/

.vscode/
.idea/

*.swp
*.swo
*~

.DS_Store
Thumbs.db


# ============================================================
# Secrets and machine-local configuration
# ============================================================

.env
.env.*
!.env.example

.pypirc
**/.pypirc

secrets/
credentials/

credentials*.json
*_credentials.json
secrets*.json
*_secrets.json

*.pem
*.key
*.p12
*.pfx
*.jks

id_rsa
id_rsa.*
id_ed25519
id_ed25519.*


# ============================================================
# Private/local data only
# ============================================================

data/raw/
data/private/
data/local/

datasets/private/
downloads/private/

*.sqlite
*.sqlite3
*.db


# ============================================================
# Profiling, logs and local runtime output
# ============================================================

*.log
*.prof
*.lprof
*.memray
*.flamegraph.svg

artifacts/local/
artifacts/tmp/

benchmarks/**/local/
benchmarks/**/tmp/
benchmarks/**/.cache/
benchmarks/**/profiles/

.local_arbitrage_sandboxes/


# ============================================================
# Private planning only
# ============================================================

upgrade/private/
upgrade/local/
upgrade/drafts/
```

Do not add blanket ignores for:

```text
upgrade/
benchmarks/
src/
quantbt/
tests/
tools/
docs/
examples/
*.py
*.md
*.json
*.csv
*.parquet
```

A global `*.json`, `*.csv` or `*.parquet` rule can hide legitimate deterministic fixtures or accepted benchmark evidence. Ignore them only inside explicit private/local data directories.

## 7.4. Guarantee `implement.md` remains agent-visible

Add a CI gate:

```bash
git ls-files --error-unmatch \
  upgrade/implement.md

test -s upgrade/implement.md

if git check-ignore \
  --no-index \
  upgrade/implement.md
then
  echo "upgrade/implement.md must not be ignored"
  exit 1
fi
```

Python test:

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_agent_implementation_plan_is_present():
    path = (
        PROJECT_ROOT
        / "upgrade"
        / "implement.md"
    )

    assert path.is_file()
    assert path.stat().st_size > 0
```

Also keep the two-way root/`src/quantbt` byte-sync gate.

## 7.5. Secret scanning

Before every public release:

```bash
git grep -nEi \
  '(pypi-[A-Za-z0-9_-]+|api[_-]?key|secret|token|password|private[_-]?key)'

git ls-files \
  | grep -Ei \
    '(^|/)(\.env|\.pypirc|credentials|secrets?)(/|$)|(\.pem|\.key|\.p12|\.pfx)$'
```

Review matches manually. Documentation may contain placeholder words such as `token`; that is not automatically a leaked credential.

Recommended GitHub protections:

```text
GitHub secret scanning
push protection
Dependabot/security updates
protected pypi/testpypi environments
```

## 7.6. PyPI artifact allowlist

The core wheel should contain:

```text
quantbt/**
quantbt_engine-*.dist-info/**
```

The sdist may additionally contain release metadata and source files required to build the wheel.

Add `MANIFEST.in` if an explicit sdist allowlist is desired:

```text
include README.md
include LICENSE
include CHANGELOG.md
include pyproject.toml

recursive-include src/quantbt *.py py.typed

global-exclude *.pem
global-exclude *.key
global-exclude .env
global-exclude .env.*
global-exclude .pypirc

prune upgrade/private
prune upgrade/local
prune upgrade/drafts
prune benchmarks
prune artifacts
prune data/raw
prune data/private
prune data/local
```

Do not rely on `MANIFEST.in` to protect a secret that has already been committed. Secrets must never enter Git history.

## 7.7. Artifact inspection gate

```bash
rm -rf /tmp/quantbt-release-dist
uv build --out-dir /tmp/quantbt-release-dist
uv run twine check /tmp/quantbt-release-dist/*

unzip -l \
  /tmp/quantbt-release-dist/quantbt_engine-*.whl

tar -tf \
  /tmp/quantbt-release-dist/quantbt_engine-*.tar.gz
```

Fail the release when a suspicious file is present:

```bash
python - <<'PY'
from pathlib import Path
import re
import tarfile
import zipfile

dist = Path("/tmp/quantbt-release-dist")

pattern = re.compile(
    r"(^|/)(\.env($|\.)|\.pypirc$|"
    r"credentials?|secrets?)(/|$)|"
    r"\.(pem|key|p12|pfx)$",
    re.IGNORECASE,
)

bad = []

for wheel in dist.glob("*.whl"):
    with zipfile.ZipFile(wheel) as archive:
        bad.extend(
            f"{wheel.name}:{name}"
            for name in archive.namelist()
            if pattern.search(name)
        )

for sdist in dist.glob("*.tar.gz"):
    with tarfile.open(sdist) as archive:
        bad.extend(
            f"{sdist.name}:{name}"
            for name in archive.getnames()
            if pattern.search(name)
        )

assert not bad, "\n".join(bad)
print("ARTIFACT SECRET-PATH GATE: PASSED")
PY
```

This preserves agent-readable source and plans while preventing local/private material from entering public artifacts.

# 8. PyPI and open-source packaging

## 8.1. Core metadata

The branch now has the correct core packaging basis:

```text
distribution: quantbt-engine
version: 1.0.7
import: quantbt
Python: 3.11–3.13
src layout
py.typed
core dependencies separated from extras
README
LICENSE
CHANGELOG
CONTRIBUTING
CODE_OF_CONDUCT
SECURITY
SUPPORT
```

This is adequate for an open-source core package.

## 8.2. TestPyPI workflow

`publish-testpypi.yml` exists and correctly uses:

```text
manual exact ref
version/tag check
regression test
uv build
twine check
OIDC environment testpypi
official PyPA publish action
```

Add artifact clean-install validation before upload:

```yaml
- name: Clean wheel and sdist install smoke
  shell: bash
  run: |
    python -m venv /tmp/quantbt-testpypi-wheel
    /tmp/quantbt-testpypi-wheel/bin/python -m pip install --upgrade pip
    /tmp/quantbt-testpypi-wheel/bin/python -m pip install dist/*.whl
    cd /tmp
    /tmp/quantbt-testpypi-wheel/bin/python -I - <<'PY'
    from quantbt import QuantBTEndpoint
    import quantbt
    print(quantbt.__file__)
    print(QuantBTEndpoint)
    PY
    /tmp/quantbt-testpypi-wheel/bin/python -m pip check

    python -m venv /tmp/quantbt-testpypi-sdist
    /tmp/quantbt-testpypi-sdist/bin/python -m pip install --upgrade pip
    /tmp/quantbt-testpypi-sdist/bin/python -m pip install dist/*.tar.gz
    cd /tmp
    /tmp/quantbt-testpypi-sdist/bin/python -I -c \
      "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
    /tmp/quantbt-testpypi-sdist/bin/python -m pip check
```

## 8.3. Production workflow

The production workflow already has the correct release-only model:

```text
GitHub Release published
Python 3.11–3.13 tests
version/tag gate
wheel and sdist build
clean-install validation
protected pypi environment
OIDC trusted publishing
```

Do not publish from normal pushes to `main` or `dev`.

## 8.4. Native distribution

Current native metadata is substantially improved, but align package and API versions before first public release.

Preferred:

```toml
[project]
name = "quantbt-native"
version = "0.4.0"
requires-python = ">=3.11,<3.14"
```

Add:

```toml
[project.urls]
Homepage = "https://github.com/BobbyAxerol/quantbt"
Repository = "https://github.com/BobbyAxerol/quantbt"
Documentation = "https://github.com/BobbyAxerol/quantbt/blob/main/docs/native_event_rust_full_contract.md"
Issues = "https://github.com/BobbyAxerol/quantbt/issues"
```

If `0.3.0` has already been published, keep it and explicitly document:

```text
distribution version: 0.3.0
native API version: 0.4
```

Do not reuse an uploaded version.

## 8.5. Make the native extra real

The core currently has:

```toml
native = []
```

That means public users cannot obtain Rust by running:

```bash
pip install "quantbt-engine[native]"
```

To claim a public dual backend, publish native first, then set:

```toml
[project.optional-dependencies]
native = [
    "quantbt-native>=0.4,<0.5",
]
```

Recommended release order:

```text
1. Build and certify quantbt-native wheels.
2. Publish quantbt-native to TestPyPI.
3. Install core + native from TestPyPI and run contract smoke.
4. Publish quantbt-native to PyPI.
5. Make quantbt-engine[native] non-empty.
6. Publish quantbt-engine 1.0.7.
```

If native wheels are not published now, release `quantbt-engine` as Python-first and clearly label Rust as local/experimental. Do not market `[native]` installation until it works from a clean public environment.

---

# 9. Documentation structure for users

Keep the README quick start short.

Recommended top-level navigation:

```text
README.md
├── Install
├── Five-minute signal backtest
├── Event-driven strategy
├── Optimization
├── Backend policy
└── Links to detailed docs
```

Detailed Native Event documents:

```text
docs/endpoint.md
    stable public profiles and examples

docs/native_event_contract.md
    language-independent domain contract

docs/native_event_rust_full_contract.md
    Rust implementation/certification

docs/grid_native_event_phase47c.md
    external integration evidence

docs/release_packaging.md
    build, TestPyPI and PyPI
```

Remove phase names from the primary quick-start path. Phase history can remain in engineering evidence documents.

The first example should not require users to understand:

```text
reactive_execution_mode
reactive_kernel_mode
report_level
audit_sink
```

Those belong in an “Advanced execution controls” section.

---

# 10. Final patch order

## Patch 1 — Correct stale release surfaces

```text
native workflow API 0.3 → 0.4
rename R0 workflow terminology
update release_packaging Rust section
update adapter docstring
```

## Patch 2 — Mirror and repository hygiene

```text
two-way manifest/hash test
sync tool
remove upgrade/ and benchmarks/ blanket ignores
add secret/cache/local-output ignores
```

## Patch 3 — Stable endpoint facade

```text
NativeEventProfile
event_driven(input_mode, profile, backend)
conflict validation
delegation tests
README quick start
```

Do not alter current endpoint execution logic.

## Patch 4 — Safe Python/Rust allocation cleanup

```text
lazy Python context payloads
bounded caches
score terminal cleanup
reusable Rust full command buffers
reusable Rust audit SoA buffers
drop duplicate Python market references
```

Rerun full parity after each internal change.

## Patch 5 — Native wheel certification

```text
cp311/cp312/cp313
manylinux x86_64
clean core+native install
API/capability smoke
full contract tests
Grid integration
RSS plateau
```

## Patch 6 — Release artifact gate

```text
core tests
mirror test
uv build
twine check
wheel clean install
sdist clean install
pip check
secret scan
TestPyPI RC
Pool Alpha wheel smoke
```

## Patch 7 — Public release

```text
merge feature → dev
rerun exact-SHA CI
merge dev → main
protected tag
GitHub Release
OIDC publish
fresh PyPI install smoke
```

---

# 11. Commands for the final local gate

```bash
git status --short
git diff --check

uv sync --all-extras --dev

uv run pytest -q
uv run pytest -q tests/test_phase45a_source_tree_sync.py
uv run pytest -q tests/native_event
uv run pytest -q -k "rust or native_event"

cargo fmt --check \
  --manifest-path rust/native_event/Cargo.toml

cargo clippy \
  --manifest-path rust/native_event/Cargo.toml \
  --all-targets \
  --all-features \
  -- -D warnings

cargo test \
  --manifest-path rust/native_event/Cargo.toml \
  --release

rm -rf /tmp/quantbt-release-dist
uv build --out-dir /tmp/quantbt-release-dist
uv run twine check /tmp/quantbt-release-dist/*
```

Wheel smoke:

```bash
python3 -m venv /tmp/quantbt-wheel-smoke
/tmp/quantbt-wheel-smoke/bin/python -m pip install --upgrade pip
/tmp/quantbt-wheel-smoke/bin/python -m pip install \
  /tmp/quantbt-release-dist/quantbt_engine-*.whl

cd /tmp
/tmp/quantbt-wheel-smoke/bin/python -I - <<'PY'
import quantbt
from quantbt import QuantBTEndpoint

print(quantbt.__file__)
print(quantbt.__version__)
print(QuantBTEndpoint)

assert "site-packages" in quantbt.__file__
PY

/tmp/quantbt-wheel-smoke/bin/python -m pip check
```

Source distribution smoke:

```bash
python3 -m venv /tmp/quantbt-sdist-smoke
/tmp/quantbt-sdist-smoke/bin/python -m pip install --upgrade pip
/tmp/quantbt-sdist-smoke/bin/python -m pip install \
  /tmp/quantbt-release-dist/quantbt_engine-*.tar.gz

cd /tmp
/tmp/quantbt-sdist-smoke/bin/python -I -c \
  "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"

/tmp/quantbt-sdist-smoke/bin/python -m pip check
```

---

# 12. Release decision

## Domain correctness

```text
PASS, subject to exact-SHA green CI.
```

The branch now has the right full Native Event V2 direction and tested Python/replay/Rust parity.

## Python performance/RSS

```text
PASS.
```

The remaining reactive callback cost is architectural, not evidence that scalar/prepared optimization failed.

## Rust performance/RSS

```text
PASS for static/batched acceleration.
PASS for reactive correctness.
No requirement that reactive Rust beat Python in 1.0.7.
```

Keep `auto=python`.

## Endpoint usability

```text
CONDITIONAL PASS.
```

Add the small `event_driven(profile=..., backend=...)` facade while retaining all current constructors.

## Core PyPI package

```text
READY AFTER P0 WORKFLOW/DOCS/MIRROR/GITIGNORE FIXES.
```

## Public dual Python/Rust installation

```text
NOT READY while native=[] and public native wheels are absent.
READY after manylinux cp311–cp313 wheels pass and the native extra is populated.
```

The final release should not chase more raw benchmark gains. It should close the stale contract surfaces, make the endpoint easy to use, ensure artifacts install cleanly, and preserve exact lifecycle/accounting parity.
