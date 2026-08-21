# ARCHITECTURE SPECIFICATION

# NATIVE EVENT MEMORY & PERFORMANCE OPTIMIZATION — PHASE 33A → 33C

## 1. Mục tiêu

Tối ưu backend `native_event` theo ba hướng:

1. Giảm peak RAM, đặc biệt trong optimization, WFO và backtest command-heavy.
2. Giảm thời gian chuẩn bị dữ liệu, execution, replay và report construction.
3. Giữ nguyên tuyệt đối execution semantics, accounting và public API.

Public usage không được thay đổi:

```python
endpoint = QuantBTEndpoint.native_event_strategy(
    initial_capital=20_000,
    reactive_execution_mode="fast",
)

result = endpoint.simulate(
    data=data,
    strategy=strategy,
    symbols=["ETHUSDT"],
)
```

Public `standard` và `audit` tiếp tục trả:

```python
BacktestResultV2
```

`BacktestResultV2` hiện là public result contract chứa equity, returns, positions, closes, orders, fills, fees, funding, margin, diagnostics và metadata; `full_report()` được gọi trực tiếp từ result này.

---

## 2. Non-negotiable invariants

Các phase tối ưu không được thay đổi:

```text
callback on_bar_close(t)
→ command chỉ có hiệu lực từ bar t+1

PLACE / CANCEL / REPLACE / AMEND / CANCEL_ALL
→ giữ nguyên lifecycle semantics

Market / limit / stop fill
→ giữ nguyên fill policy

Parent-child / OCO / reduce-only / GTD
→ giữ nguyên activation và cancellation semantics

Fees / funding / margin / liquidation
→ giữ nguyên công thức và thứ tự xử lý

Same-bar command sequencing
→ deterministic và không đổi

Strategy API
→ initialize / on_bar_close / finalize không đổi
```

Chỉ được thay đổi:

```text
internal memory representation
artifact retention
report materialization
prepared-data reuse
execution-loop architecture
active-order indexing
audit storage
```

Phải chỉ tồn tại **một accounting source of truth**.

Không được xây:

```text
accounting riêng cho score
accounting riêng cho minimal
accounting riêng cho audit
```

---

# PHASE 33A — ARTIFACT & MEMORY CONTRACT

## 3. Mục tiêu Phase 33A

Giảm RAM ngay mà không thay đổi matching kernel hoặc accounting loop.

Phase này chủ yếu xử lý:

* `report_level` chưa được áp dụng đầy đủ cho native event;
* Python object artifacts;
* pandas materialization;
* command/fill/event ledger;
* artifact duplication;
* audit output.

---

## 4. Wire `report_level` xuyên suốt backend

Luồng bắt buộc:

```text
QuantBTEndpoint
→ EndpointConfig
→ BacktestEngineV2
→ NativeEventBackend
→ kernel artifact plan
→ result materializer
```

Các mode:

| Mode       | Mục đích            | Artifact được giữ                              |
| ---------- | ------------------- | ---------------------------------------------- |
| `score`    | Optimization nội bộ | Accounting arrays tối thiểu và metrics         |
| `minimal`  | WFO/service         | Equity, returns, positions, margin, counters   |
| `standard` | Research            | Minimal + compact fills/command summary        |
| `audit`    | Certification       | Full lifecycle ledger, command tape và reports |

`score` là internal execution mode, không cần trở thành public result mode.

Public `.simulate()` vẫn trả `BacktestResultV2`.

---

## 5. Artifact plan

Thêm contract nội bộ:

```python
@dataclass(frozen=True)
class NativeEventArtifactPlan:
    keep_equity_path: bool
    keep_position_path: bool
    keep_fee_path: bool
    keep_funding_path: bool
    keep_margin_path: bool

    keep_fill_ledger: bool
    keep_command_terminal_state: bool
    keep_event_ledger: bool
    keep_command_tape: bool

    materialize_pandas: bool
    materialize_python_objects: bool
```

Mapping mặc định:

```text
score:
    accounting paths cần cho objective
    scalar counters
    không pandas
    không Fill/OrderCommand Python objects
    không event ledger

minimal:
    equity/returns/positions
    fees/funding/margin
    compact counters
    không full lifecycle ledger

standard:
    minimal
    compact fills
    terminal command state

audit:
    toàn bộ accounting
    compact command tape
    full lifecycle events
    replay certification
```

---

## 6. Compact struct-of-arrays ledger

Không lưu event/fill/order chính bằng:

```text
list[OrderCommand]
tuple[Fill]
list[NativeOrderEvent]
DataFrame tạo ngay sau kernel
```

Thay bằng contiguous arrays:

```python
@dataclass
class CompactFillLedger:
    bar: np.ndarray
    order_id_code: np.ndarray
    symbol_code: np.ndarray
    side: np.ndarray
    qty: np.ndarray
    price: np.ndarray
    fee: np.ndarray
    liquidity: np.ndarray


@dataclass
class CompactOrderLedger:
    bar: np.ndarray
    command_id: np.ndarray
    order_id_code: np.ndarray
    event_type: np.ndarray
    status: np.ndarray
    reason_code: np.ndarray
    related_order_id_code: np.ndarray
```

Strings như:

```text
order_id
tag
campaign_id
level_id
oco_group_id
parent_order_id
```

được dictionary-encode một lần thành integer code.

Chỉ decode thành Python objects hoặc DataFrame khi accessor được gọi:

```python
result.fills_report()
result.command_report()
result.order_events()
```

---

## 7. Lazy public result artifacts

Public `BacktestResultV2` vẫn được giữ.

Các field bắt buộc:

```text
equity
returns
positions
closes
fees
funding
margin
```

vẫn có giá trị đúng.

Các artifact nặng:

```text
fills
orders
trades
diagnostics
command_report
order_events
active_orders
```

được:

* để trống trong `minimal`;
* materialize lazily trong `standard`;
* materialize đầy đủ hoặc stream trong `audit`.

Không lưu trùng:

```text
order_report
command_report
```

thành hai nguồn riêng.

Chỉ giữ một canonical ledger và backward-compatible alias.

---

## 8. Audit sink

Thêm:

```python
audit_sink = (
    "none"
    | "memory"
    | "parquet"
    | "jsonl"
)
```

Khuyến nghị:

```text
score/minimal:
    audit_sink="none"

audit ngắn:
    audit_sink="memory"

audit dài:
    audit_sink="parquet"
```

Parquet/JSONL phải ghi theo chunk, không write từng event.

---

## 9. Phase 33A parity tests

Cùng một command tape phải chạy qua:

```text
current full path
minimal path
standard path
audit path
```

Và phải đạt:

```python
np.testing.assert_array_equal(
    result_a.equity,
    result_b.equity,
)

np.testing.assert_array_equal(
    result_a.positions,
    result_b.positions,
)

np.testing.assert_array_equal(
    result_a.fees,
    result_b.fees,
)

np.testing.assert_array_equal(
    result_a.funding,
    result_b.funding,
)

np.testing.assert_array_equal(
    result_a.margin,
    result_b.margin,
)
```

Exact equality cho:

```text
fill count
rejected count
canceled count
expired count
liquidation bar/reason
terminal order status
```

`report_level` chỉ được phép thay đổi artifact retention, không được thay đổi accounting.

---

## 10. Phase 33A benchmark gate

Trên workload dynamic grid thực tế:

```text
~60.000 bars
1 symbol
15 entry + 15 exit levels
command-heavy AMEND/CANCEL
```

Acceptance target:

```text
minimal peak RSS:
    giảm ít nhất 35%

minimal report-construction time:
    giảm ít nhất 70%

audit with parquet sink:
    RAM không tăng tuyến tính theo toàn bộ event history
```

---

# PHASE 33B — PREPARED OPTIMIZATION SCORE PATH

## 11. Mục tiêu Phase 33B

Tạo optimization path nhanh và memory-lean nhưng phải dùng:

* cùng market arrays;
* cùng execution kernel;
* cùng accounting arrays;
* cùng metric implementation;

với public `BacktestResultV2`.

Không được tạo một backtester hoặc metric implementation thứ hai.

---

## 12. Prepared reactive runner

Thêm API mới nhưng không thay API cũ:

```python
prepared = endpoint.prepare_native_event_strategy(
    data=data,
    symbols=["ETHUSDT"],
)
```

Prepared runner giữ và reuse:

```text
DatetimeIndex / timestamp int64
OHLCV arrays
funding arrays
symbol map
instrument constraints
contract sizes
fee/leverage arrays
quantity constraints
data signature
```

Optimization:

```python
score_result = prepared.score(
    strategy=strategy,
)
```

Public audit:

```python
result = prepared.run(
    strategy=strategy,
    report_level="audit",
)
```

---

## 13. `NativeEventScoreResult`

Internal optimization result:

```python
@dataclass(frozen=True)
class NativeEventScoreResult:
    timestamps: np.ndarray
    equity: np.ndarray
    returns: np.ndarray
    positions: np.ndarray

    fees: np.ndarray
    funding: np.ndarray
    initial_margin: np.ndarray
    maintenance_margin: np.ndarray

    final_positions: np.ndarray

    fill_count: int
    rejection_count: int
    cancellation_count: int

    liquidated: bool
    liquidation_bar: int

    metrics: Mapping[str, float]
    metadata: Mapping[str, Any]
```

Nó không được giữ:

```text
pandas Series/DataFrame
Fill Python objects
OrderCommand objects
full event ledger
full command tape
```

### Quy tắc quan trọng

`NativeEventScoreResult` không có accounting riêng.

Nó chỉ là một lightweight view của cùng:

```text
NativeAccountingArrays
```

được public result sử dụng.

Kiến trúc:

```text
Native execution/accounting kernel
              │
              ▼
     NativeAccountingArrays
          ┌───┴───────────────┐
          ▼                   ▼
NativeEventScoreResult   BacktestResultV2
optimization view        public materializer
```

---

## 14. Shared canonical metric engine

Hiện optimization mặc định có thể yêu cầu:

```text
sharpe
max_drawdown_pct
num_trades
turnover
profit_factor
margin_utilization
rejection_rate
```

`ReportMetricObjective` lấy objective và constraint metrics từ `full_report()`, metadata, margin hoặc rejection counters.

Current report semantics gồm:

* Sharpe và profit factor được tính từ daily returns nếu có, nếu không mới fallback về bar returns.
* Max drawdown được tính từ equity path.
* `num_trades` hiện được tính từ số lần position thay đổi.
* Hit rate cũng phụ thuộc position path và returns.

Do đó score path phải giữ đủ:

```text
timestamps
equity path
returns path
position path
margin path
execution counters
```

Không được chỉ giữ final equity và vài scalar counters.

### Refactor metric architecture

Tách metric core thành pure array functions:

```python
metrics = compute_performance_metrics(
    timestamps=timestamps,
    equity=equity,
    returns=returns,
    positions=positions,
    initial_capital=initial_capital,
    trading_days=365,
)
```

Sau đó:

```text
BacktestResultV2.full_report()
NativeEventScoreResult.full_report()
```

đều gọi cùng `compute_performance_metrics()`.

Không copy công thức Sharpe/MDD/profit factor sang một module optimizer riêng.

---

## 15. Score/public parity release gate

Cùng một:

```text
data
params
strategy
execution config
seed
```

chạy:

```python
score = prepared.score(strategy)
full = prepared.run(
    strategy,
    report_level="audit",
)
```

Phải đạt:

```python
score.metrics["sharpe"] \
    == full.full_report()["sharpe"]

score.metrics["max_drawdown_pct"] \
    == full.full_report()["max_drawdown_pct"]

score.metrics["profit_factor"] \
    == full.full_report()["profit_factor"]

score.metrics["num_trades"] \
    == full.full_report()["num_trades"]
```

Đối với toàn bộ optimizer metrics:

```text
metric_diff == 0.0
```

Không chỉ “gần bằng”.

Điều này khả thi vì cả hai path phải dùng:

* cùng accounting arrays;
* cùng timestamps;
* cùng metric functions;
* cùng dtype;
* cùng evaluation order.

Các metric bổ sung:

```text
turnover
margin_utilization
rejection_rate
final_equity
liquidated
```

cũng phải exact equality.

Nếu metric parity chưa bằng `0.0`, score path chưa được phép dùng làm default optimizer evaluator.

---

## 16. Optimization evaluator

Thêm specialized evaluator:

```python
PreparedNativeEventStrategyEvaluator
```

hoặc:

```python
PreparedReactiveGridEvaluator
```

Luồng:

```text
OptunaOptimizer
→ prepared.score(strategy)
→ NativeEventScoreResult
→ ReportMetricObjective
→ ObjectiveResult
```

Current generic evaluator chỉ yêu cầu result-like object và objective builder; specialized evaluator có thể dùng cùng `ObjectiveResult` contract, không cần thay optimizer framework.

---

## 17. Phase 33B benchmark gate

So sánh:

```text
public audit BacktestResultV2
prepared score NativeEventScoreResult
```

Trên một trial:

```text
score peak RSS:
    giảm ít nhất 60%

score wall time:
    giảm ít nhất 35%

pandas/report construction:
    gần bằng zero
```

Trên 50/500 trials:

```text
market arrays chỉ prepare một lần
RSS không tăng theo số trial hoàn thành
không giữ last_result full artifacts
không giữ command tape giữa các trial
```

Nếu score path chỉ nhanh hơn không đáng kể, không được coi Phase 33B hoàn thành.

---

# PHASE 33C — SINGLE-PASS STATEFUL NATIVE KERNEL

## 18. Mục tiêu Phase 33C

Loại bỏ kiến trúc hai pass hiện tại:

```text
Python reactive execution
→ capture toàn command tape
→ Numba replay toàn bộ tape
→ final accounting
```

Reactive session hiện giữ Python order state để phục vụ callback, còn final accounting replay command tape qua kernel để duy trì một final source of truth.

Kiến trúc mới:

```text
stateful native kernel step
→ strategy callback
→ commands cho bar kế tiếp
→ stateful native kernel step tiếp
```

Một accounting pass duy nhất.

---

## 19. Stateful kernel API

Tách kernel thành:

```python
initialize_native_event_state(...)
apply_commands_for_bar(...)
match_active_orders(...)
apply_funding(...)
apply_margin_and_liquidation(...)
finalize_bar(...)
```

Session:

```python
session.step_bar(
    bar_index,
    compact_commands,
)
```

Context đọc trực tiếp từ kernel state:

```text
positions view
equity
margin
fills slice của bar
order-event slice của bar
active-order view
```

Không dựng lại dict/list/tuple đầy đủ mỗi bar nếu không cần.

---

## 20. Active-order indexing

Loại bỏ full scan trên toàn bộ historical commands.

Thêm:

```text
active_order_slots
active_slots_by_symbol
free_slot_stack
order_id_to_slot
expiry_buckets
parent_to_children adjacency
oco_group_to_members adjacency
```

Target complexity:

```text
Current:
O(bars × total_historical_commands)

Target:
O(total_commands + total_fills
  + bars × current_active_orders)
```

Điều này đặc biệt quan trọng với dynamic grid có ít active orders nhưng rất nhiều historical AMEND/CANCEL commands.

---

## 21. Single-pass modes

```text
score:
    single pass
    không command tape
    không replay
    không ledger ngoài counters

minimal:
    single pass
    accounting paths

standard:
    single pass
    compact fills + terminal state

audit:
    single pass
    compact full tape/events
    optional replay certification
```

Audit replay chỉ là certification tool, không còn là requirement của mọi run.

---

## 22. Safe migration

Không xóa path cũ ngay.

Thêm internal mode:

```python
reactive_kernel_mode = (
    "replay_certified"
    | "single_pass"
)
```

Rollout:

```text
Phase 33C development:
    default = replay_certified

Sau parity certification:
    fast/score = single_pass
    audit = single_pass + optional replay

Sau stabilization:
    replay_certified giữ làm oracle/debug mode
```

Public endpoint không thay đổi.

---

# 23. PARITY TEST MATRIX

## Lifecycle fixtures

Bắt buộc kiểm tra:

```text
market entry/exit
GTC limit
cancel before fill
replace
amend price/qty
stop-market
stop-limit
GTD expiry
reduce-only clipping
parent first-fill activation
parent full-fill activation
OCO sibling cancellation
same timestamp sequencing
close-and-reverse
insufficient margin
funding
intrabar liquidation
post-funding liquidation
post-order liquidation
dynamic grid amend
grid entry → exit → re-arm
regime switch cancel + flatten
multi-symbol commands
```

## Compared paths

```text
current replay-certified audit
Phase 33A minimal
Phase 33A standard
Phase 33A audit
Phase 33B score
Phase 33C single-pass score
Phase 33C single-pass audit
audit static replay
```

## Required equality

Raw accounting:

```python
assert_array_equal(equity)
assert_array_equal(returns)
assert_array_equal(positions)
assert_array_equal(fees)
assert_array_equal(funding)
assert_array_equal(initial_margin)
assert_array_equal(maintenance_margin)
```

Lifecycle:

```text
fill count exact
fill order ID exact
fill qty exact
fill price exact
terminal status exact
rejection reason exact
liquidation exact
```

Metrics:

```text
sharpe diff = 0.0
max_drawdown_pct diff = 0.0
profit_factor diff = 0.0
num_trades diff = 0
turnover diff = 0.0
margin_utilization diff = 0.0
rejection_rate diff = 0.0
```

Optimizer parity:

```text
same fixed seed
same trial params
same objective values
same constraint values
same feasible/infeasible classification
same selected best candidate
```

---

# 24. BENCHMARK SUITE

Mỗi benchmark phải chạy trong subprocess mới để tránh CPython/Numba allocator và Jupyter giữ RSS cũ.

## Workloads

### Real dynamic grid

```text
~60.000 bars
1 symbol
15 entry + 15 exit levels
long-only và long-short
```

### One-minute stress

```text
525.600 bars
1 symbol
15–30 active orders
high AMEND/CANCEL frequency
```

### Multi-symbol

```text
25.000 bars
10 symbols
50 symbols
```

### Optimization batch

```text
50 trials
500 trials
same prepared market tape
```

## Metrics

```text
wall time
CPU time
peak RSS
Python heap peak
NumPy allocated bytes
number of Python objects
ledger bytes
command count
fill count
report construction time
```

## Stage timing

```text
data normalization
market preparation
alpha preparation
reactive execution
kernel accounting
command capture
result materialization
metric construction
report construction
garbage collection
```

---

# 25. DELIVERY ORDER

## Phase 33A

```text
33A.1 wire report_level
33A.2 artifact plan
33A.3 compact ledgers
33A.4 lazy public reports
33A.5 audit sink
33A.6 parity and benchmark suite
```

## Phase 33B

```text
33B.1 prepared reactive market state
33B.2 NativeAccountingArrays
33B.3 shared canonical metric engine
33B.4 NativeEventScoreResult
33B.5 prepared optimization evaluator
33B.6 score/full metric parity = 0
33B.7 50/500-trial memory benchmarks
```

## Phase 33C

```text
33C.1 stateful native kernel
33C.2 active-order indexes
33C.3 lightweight callback context
33C.4 single-pass score/minimal
33C.5 compact audit ledger
33C.6 optional replay certification
33C.7 full lifecycle and optimizer parity
```

---

# 26. FINAL ACCEPTANCE CRITERIA

Feature chỉ được xem là hoàn thành khi:

* Public endpoint không đổi.
* Public standard/audit vẫn trả `BacktestResultV2`.
* Strategy callback contract không đổi.
* Không có accounting implementation thứ hai.
* `NativeEventScoreResult` dùng cùng accounting arrays với public result.
* Score/full optimizer metric diff bằng `0.0`.
* Score path nhanh và memory-lean hơn đáng kể.
* Single-pass path đạt full lifecycle parity với replay oracle.
* Audit có thể giữ full trace mà không bắt optimization giữ toàn bộ artifacts.
* Prepared runner reuse market arrays xuyên nhiều trial.
* 500-trial run không tăng RAM theo số trial đã hoàn thành.
* Dynamic grid, DCA, bracket và structured orders vẫn giữ nguyên domain semantics.

Mục tiêu cuối cùng:

```text
Public API ổn định
+ một accounting engine
+ nhiều artifact policies
+ prepared optimization
+ single-pass reactive execution
+ audit replay certification
```
