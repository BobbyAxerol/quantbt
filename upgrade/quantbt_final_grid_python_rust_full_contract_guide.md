# QuantBT Final Grid Integration Guide — Python Scalar v2 & Full-Contract Rust Backend

## 1. Source of truth

Guide này chỉ áp dụng cho đúng Grid module:

```python
MODULE_VERSION = "2026-07-29-phase34-prepared-native-event-v3"
```

File runtime:

```text
/root/bobby/pool_alpha/alphas_storage/TA/
dynamic_grid_quantbt_native_event.py
```

Không copy Grid vào QuantBT repo. Benchmark/test import bằng `sys.path`.

Grid hiện sử dụng thực tế:

```text
Reactive strategy callbacks
PLACE
AMEND
CANCEL
CANCEL_ALL
MARKET
LIMIT
GTC
reduce_only
OCO entry batches
OCO exit batches
active_orders snapshots
fills_this_bar
size_order
funding
initial/maintenance margin
liquidation
single symbol
```

Grid không phải toàn bộ Native Event specification, nhưng là integration test tốt cho lifecycle phức tạp.

---

# 2. Kết luận hiện tại

## Python

**Đã backtest được Grid bằng Python backend.**

Các path hiện dùng được:

```text
replay_certified → accounting/lifecycle oracle
python single_pass + minimal → public BacktestResultV2
python scalar v2 + score → optimizer/benchmark ít RAM
```

## Rust

**Chưa backtest Grid production với cùng domain contract tại thời điểm hiện tại.**

Rust reactive hiện còn từ chối hoặc chưa thực hiện đầy đủ:

```text
CANCEL_ALL
OCO
funding
maintenance-margin liquidation
full active-order metadata/snapshots
một số lifecycle/TIF/relationship semantics
```

Grid hiện bật:

```python
use_funding=True
maintenance_ratio=0.005
```

và phát:

```python
OrderAction.CANCEL_ALL
oco_group_id=...
```

Do đó không được tắt funding/OCO/liquidation chỉ để Rust chạy. Làm vậy sẽ đổi strategy domain contract và kết quả không còn là parity.

Kết luận mục tiêu:

```text
Python và Rust phải cùng hỗ trợ public Native Event V2 contract.
Grid chỉ được chạy bằng native_backend="rust"
sau khi full contract parity suite và Grid 2.000-bar parity pass.
```

---

# 3. Không thêm endpoint mới

Giữ nguyên:

```python
QuantBTEndpoint.native_event_strategy(...)
QuantBTEndpoint.prepare_native_event_strategy(...)
```

Chỉ thêm backend selector vào Grid config và forward xuống endpoint.

Không tạo:

```text
grid_python_endpoint
grid_rust_endpoint
native_event_strategy_rust
```

Backend được chọn bằng:

```python
native_backend="python"
native_backend="rust"
native_backend="auto"
native_backend="replay_certified"
```

---

# 4. Patch đúng file Grid hiện tại

## 4.1. Thêm field vào `GridExecutionConfig`

Append vào cuối nhóm execution fields:

```python
@dataclass(frozen=True)
class GridExecutionConfig:
    # Giữ nguyên toàn bộ fields hiện tại.

    native_backend: str = "python"

    reactive_execution_mode: str = "fast"
    reactive_kernel_mode: str = "replay_certified"
    report_level: str = "minimal"
    audit_sink: str = "none"
    audit_sink_path: Optional[str] = None

    def __post_init__(self) -> None:
        if self.native_backend not in {
            "python",
            "rust",
            "auto",
            "replay_certified",
        }:
            raise ValueError(
                "native_backend must be one of: "
                "python, rust, auto, replay_certified"
            )
```

Nếu class đã có `__post_init__`, chỉ append validation.

## 4.2. Forward trong `build_grid_endpoint`

Thêm đúng một kwarg:

```python
def build_grid_endpoint(
    execution: GridExecutionConfig,
) -> QuantBTEndpoint:
    return QuantBTEndpoint.native_event_strategy(
        initial_capital=execution.initial_capital,
        leverage=execution.leverage,
        maintenance_ratio=execution.maintenance_ratio,
        contract_size=execution.contract_size,
        fee_rate=execution.fee_rate,
        slippage_bps=execution.slippage_bps,
        use_funding=execution.use_funding,
        funding_rate=execution.funding_rate,
        qty_step=execution.qty_step,
        lot_size=execution.lot_size,
        slot_size=execution.slot_size,
        min_qty=execution.min_qty,
        min_notional=execution.min_notional,
        symbols=[execution.symbol],

        native_backend=execution.native_backend,

        reactive_execution_mode=execution.reactive_execution_mode,
        reactive_kernel_mode=execution.reactive_kernel_mode,
        report_level=execution.report_level,
        audit_sink=execution.audit_sink,
        audit_sink_path=execution.audit_sink_path,
    )
```

Không thay strategy callback hoặc command logic.

---

# 5. Public result và scalar score là hai path khác nhau

## 5.1. `run_grid_backtest()` chỉ dùng cho public result

Code hiện tại luôn gọi:

```python
output_frame = strategy.build_output_frame(result)
```

`build_output_frame()` cần:

```text
result.positions
result.equity
result.fills
```

Do đó `run_grid_backtest()` chỉ dùng với:

```text
report_level="minimal"
report_level="standard"
report_level="audit"
```

Không dùng wrapper này cho scalar score.

## 5.2. Scalar v2 phải dùng prepared runner

Không sửa optimizer hiện tại trong bước này.

Thêm optional helper mới:

```python
def prepare_grid_score_runner(
    *,
    df: pd.DataFrame,
    execution: GridExecutionConfig,
):
    endpoint = build_grid_endpoint(execution)

    runner = endpoint.prepare_native_event_strategy(
        data=df,
        symbols=[execution.symbol],
    )

    return endpoint, runner
```

Thêm score helper:

```python
def score_grid_params(
    *,
    prepared_runner,
    df: pd.DataFrame,
    params: Dict,
    execution: GridExecutionConfig,
    trading_days: int = 365,
):
    strategy = build_grid_strategy(
        df=df,
        params=params,
        execution=execution,
    )

    requirements = (
        NativeEventScoreRequirements
        .scalar_score_contract()
    )

    return prepared_runner.score(
        strategy,
        trading_days=trading_days,
        score_requirements=requirements,
    )
```

Cần import:

```python
from quantbt import NativeEventScoreRequirements
```

Không gọi `full_report()` trên scalar result.

---

# 6. Notebook import đúng module

```python
%load_ext autoreload
%autoreload 2

import sys
import importlib

sys.path.insert(
    0,
    "/root/bobby/pool_alpha",
)

sys.path.insert(
    0,
    "/root/bobby/pool_alpha/alphas_storage/TA",
)

import quantbt
from quantbt import (
    EndpointConfig,
    NativeEventScoreRequirements,
    NativeEventScalarScoreResult,
    PreparedNativeEventStrategyRunner,
    QuantBTEndpoint,
)

import dynamic_grid_quantbt_native_event as grid_alpha

grid_alpha = importlib.reload(grid_alpha)

EXPECTED_GRID_VERSION = (
    "2026-07-29-phase34-prepared-native-event-v3"
)

assert (
    grid_alpha.MODULE_VERSION
    == EXPECTED_GRID_VERSION
)

GridExecutionConfig = grid_alpha.GridExecutionConfig
build_grid_endpoint = grid_alpha.build_grid_endpoint
build_grid_strategy = grid_alpha.build_grid_strategy
run_grid_backtest = grid_alpha.run_grid_backtest

print("QuantBT:", quantbt.__file__)
print("Grid:", grid_alpha.__file__)
print("Grid version:", grid_alpha.MODULE_VERSION)
```

Integration gate:

```python
from dataclasses import fields

assert "native_backend" in {
    field.name
    for field in fields(GridExecutionConfig)
}

assert "native_backend" in {
    field.name
    for field in fields(EndpointConfig)
}

assert hasattr(
    NativeEventScoreRequirements,
    "scalar_score_contract",
)

assert hasattr(
    QuantBTEndpoint,
    "prepare_native_event_strategy",
)
```

---

# 7. Config chuẩn cho ba Python paths

## 7.1. Replay-certified oracle

```python
execution_oracle = GridExecutionConfig(
    **COMMON_EXECUTION,

    native_backend="replay_certified",

    reactive_execution_mode="audit",
    reactive_kernel_mode="replay_certified",

    report_level="audit",
    audit_sink="memory",
    audit_sink_path=None,
)
```

Run:

```python
oracle_run = run_grid_backtest(
    df=data_2000,
    params=best_params_long_only,
    execution=execution_oracle,
)
```

## 7.2. Python public minimal

```python
execution_python_minimal = GridExecutionConfig(
    **COMMON_EXECUTION,

    native_backend="python",

    reactive_execution_mode="fast",
    reactive_kernel_mode="single_pass",

    report_level="minimal",
    audit_sink="none",
    audit_sink_path=None,
)
```

Run:

```python
python_public_run = run_grid_backtest(
    df=data_2000,
    params=best_params_long_only,
    execution=execution_python_minimal,
)

report = python_public_run.result.full_report(
    trading_days=365,
    scope="full",
)
```

## 7.3. Python scalar v2

```python
execution_python_scalar = GridExecutionConfig(
    **COMMON_EXECUTION,

    native_backend="python",

    reactive_execution_mode="fast",
    reactive_kernel_mode="single_pass",

    report_level="score",
    audit_sink="none",
    audit_sink_path=None,
)
```

Prepare một lần:

```python
python_scalar_endpoint = build_grid_endpoint(
    execution_python_scalar
)

prepared_python_scalar = (
    python_scalar_endpoint
    .prepare_native_event_strategy(
        data=data_2000,
        symbols=[
            execution_python_scalar.symbol
        ],
    )
)
```

Fresh strategy mỗi run:

```python
python_scalar_strategy = build_grid_strategy(
    df=data_2000,
    params=best_params_long_only,
    execution=execution_python_scalar,
)

python_scalar_result = prepared_python_scalar.score(
    python_scalar_strategy,
    trading_days=365,
    score_requirements=(
        NativeEventScoreRequirements
        .scalar_score_contract()
    ),
)

print(python_scalar_result)
```

---

# 8. Rust phải được nâng lên cùng Python domain contract

Không chỉ thêm những gì Grid dùng. Target là toàn bộ public Native Event V2 contract.

## 8.1. Commands

```text
PLACE
CANCEL
CANCEL_ALL
AMEND
REPLACE
```

## 8.2. Order types

```text
MARKET
LIMIT
STOP_MARKET
STOP_LIMIT
```

## 8.3. Time in force

```text
GTC
GTD
IOC
FOK
```

## 8.4. Relationships

```text
parent_order_id
activation_policy
group_id
oco_group_id
expiry
```

## 8.5. Execution/accounting

```text
next-bar command effectiveness
same-bar command ordering
order priority
reduce-only
quantity constraints
fee
slippage
funding
initial margin
maintenance margin
liquidation priority
single-symbol
multi-symbol
```

## 8.6. Context/result

Rust phải trả cùng semantics cho:

```text
fills_this_bar
order_events_this_bar
active_orders
positions
equity
available_equity
initial_margin
maintenance_margin
liquidated
```

Không hardcode:

```python
use_funding = False
liquidated = False
```

---

# 9. File-level Rust implementation guide

## 9.1. Python adapter

File:

```text
src/quantbt/backends/_native_event_rust.py
```

Sửa:

1. Bump native API version sau khi schema command thay đổi.
2. Mở rộng command codes cho:
   - `CANCEL_ALL`;
   - TIF;
   - expiry;
   - activation policy;
   - parent/group/OCO IDs;
   - symbol index.
3. Không còn reject funding, maintenance ratio hoặc multi-symbol sau khi Rust core đã implement.
4. Không set:
   ```python
   self.use_funding = False
   ```
5. Truyền real funding arrays/masks vào Rust.
6. Decode đầy đủ active snapshots:
   - tag;
   - group/OCO;
   - parent;
   - remaining quantity;
   - activation state.
7. Decode real liquidation state/reason.
8. Explicit `native_backend="rust"` phải raise rõ nếu binary API/capability không khớp.

## 9.2. Rust modules

Tách/hoàn thiện:

```text
rust/native_event/src/
├── lib.rs
├── types.rs
├── session.rs
├── commands.rs
├── order_table.rs
├── matching.rs
├── lifecycle.rs
├── accounting.rs
└── buffers.rs
```

Không thêm actor/message bus.

## 9.3. Order table

Dùng:

```rust
struct OrderTable {
    slots: Vec<OrderSlot>,
    id_to_slot: HashMap<i64, usize>,
    active_sequence: Vec<usize>,
    free_slots: Vec<usize>,
}
```

Indexes:

```text
children_by_parent
members_by_group
members_by_oco
expiry_by_bar
```

Không `Vec.remove()` làm đổi priority.

## 9.4. Bar execution order

Copy exact order từ replay-certified oracle.

Khóa bằng test:

```text
PnL/mark update
intrabar liquidation
funding
after-funding liquidation
expiry
commands
matching/fills
parent/OCO lifecycle
after-order liquidation
state recording
```

Nếu implementation Python hiện dùng thứ tự chi tiết khác, Rust phải copy đúng code Python/replay hiện hành; không tự suy diễn lại.

---

# 10. Conformance tests trước Grid

Tạo một suite dùng chung:

```text
tests/native_event/contract/
```

Mỗi fixture chạy:

```text
replay_certified
python
rust
```

Coverage bắt buộc:

```text
command timing/order
PLACE/CANCEL/CANCEL_ALL
AMEND/REPLACE
MARKET/LIMIT/STOP
GTC/GTD/IOC/FOK
reduce-only
quantity constraints
parent activation
group/OCO
funding
margin
liquidation
multi-symbol
```

Full parity so:

```text
command tape
events/status/reject reason
fills
positions
equity
fees
funding
turnover
margin
liquidation
```

Discrete fields exact.

Numeric:

```python
np.testing.assert_array_equal(...)
```

ưu tiên; tối đa:

```python
np.testing.assert_allclose(
    ...,
    rtol=0.0,
    atol=1e-12,
)
```

---

# 11. Grid 2.000-bar integration test

## 11.1. Data

```python
data_2000 = (
    data_eth
    .sort_index()
    .iloc[-2000:]
    .copy()
)

assert len(data_2000) == 2000
assert data_2000.index.is_monotonic_increasing
assert not data_2000.index.has_duplicates
```

Chạy cả:

```text
best_params_long_only
best_params_long_short
```

## 11.2. Rust config sau khi full contract pass

```python
execution_rust_scalar = GridExecutionConfig(
    **COMMON_EXECUTION,

    native_backend="rust",

    reactive_execution_mode="fast",
    reactive_kernel_mode="single_pass",

    report_level="score",
    audit_sink="none",
    audit_sink_path=None,
)
```

Prepare:

```python
rust_endpoint = build_grid_endpoint(
    execution_rust_scalar
)

prepared_rust = (
    rust_endpoint
    .prepare_native_event_strategy(
        data=data_2000,
        symbols=[
            execution_rust_scalar.symbol
        ],
    )
)
```

Fresh strategy:

```python
rust_strategy = build_grid_strategy(
    df=data_2000,
    params=best_params_long_only,
    execution=execution_rust_scalar,
)

rust_scalar_result = prepared_rust.score(
    rust_strategy,
    trading_days=365,
    score_requirements=(
        NativeEventScoreRequirements
        .scalar_score_contract()
    ),
)
```

---

# 12. Grid parity gate

Chạy theo thứ tự:

```text
1. replay-certified audit
2. Python single-pass audit/minimal
3. Python scalar v2
4. Rust reactive audit
5. Rust scalar
```

Không reuse strategy instance.

## Required equality

```text
emitted command sequence
effective command bars
order events
fills
positions
fees
funding
margin
liquidation
final equity
```

Python scalar và Rust scalar không giữ full artifacts; chứng nhận chúng bằng:

```text
audit fingerprint từ cùng backend/config
+
scalar totals/metrics
```

Không chỉ so Sharpe hoặc final equity.

---

# 13. Benchmark process

Tạo:

```text
benchmarks/native_event/benchmark_grid_2000.py
```

CLI:

```bash
uv run python \
  benchmarks/native_event/benchmark_grid_2000.py \
  --grid-module-dir \
  /root/bobby/pool_alpha/alphas_storage/TA \
  --backend python \
  --mode scalar \
  --bars 2000

uv run python \
  benchmarks/native_event/benchmark_grid_2000.py \
  --grid-module-dir \
  /root/bobby/pool_alpha/alphas_storage/TA \
  --backend rust \
  --mode scalar \
  --bars 2000
```

Mỗi backend chạy process riêng:

```text
1 warm-up
5 measured runs
median runtime
peak RSS/VmHWM
post-run RSS
full parity fingerprint
```

Accepted RSS rule:

```text
~180 MB baseline đã đạt.
Không yêu cầu giảm thêm 40%.
Không được regression > 10–15%.
Không leak hoặc tăng tuyến tính qua repeated runs.
```

---

# 14. Backend policy sau upgrade

```text
native_backend="python"
    full domain implementation
    default

native_backend="rust"
    cùng public domain contract
    explicit failure nếu binary/capability không đúng

native_backend="replay_certified"
    oracle

native_backend="auto"
    chỉ chọn Rust sau khi:
    - conformance suite pass;
    - Grid long-only pass;
    - Grid long-short pass;
    - wheel/version checks pass.
```

Không silent fallback khi user yêu cầu `"rust"`.

---

# 15. Definition of Done

Rust dual backend hoàn thành khi:

- public endpoint không đổi;
- Grid file chỉ thêm `native_backend` và scalar helpers;
- Python vẫn backtest Grid đúng;
- Rust hỗ trợ toàn bộ Native Event V2 contract, không chỉ Grid subset;
- Rust thực hiện `CANCEL_ALL`, OCO, funding, margin và liquidation đúng;
- Python và Rust pass cùng conformance suite;
- Grid 2.000 bars long-only pass full parity;
- Grid 2.000 bars long-short pass full parity;
- Python scalar v2 và Rust scalar chạy được;
- RSS không regression đáng kể so với accepted baseline;
- Rust explicit không silent fallback;
- `auto` chỉ bật Rust sau certification.

## Trạng thái chốt

```text
Python Grid:
    ĐÃ backtest được.

Rust Grid hiện tại:
    CHƯA được coi là backtest đúng cùng domain contract.

Rust Grid sau các patch trên:
    ĐƯỢC phép chạy khi full conformance
    và Grid 2.000-bar parity đều pass.
```

---

# 16. Kiểm tra chênh lệch kết quả Python mới

Quan sát hiện tại:

```text
Python single-pass/scalar mới:
    kết quả tổng thể lệch nhỏ
    num_trades tăng 2
```

Không được tự kết luận hai trade tăng thêm là đúng vì engine “tính đủ phí hơn”.

Trong QuantBT hiện tại:

```text
num_trades
=
1 initial count cho mỗi symbol
+
số lần position quantity thay đổi
```

Nó không phải số round-trip trades. Với Grid/pyramiding, scale-in, partial exit hoặc flatten đều có thể tăng `num_trades`.

Agent phải report riêng:

```text
position_transition_count
fill_count
entry_fill_count
exit_fill_count
flatten_fill_count
total_fee
total_funding
```

## 16.1. Diagnostic helper

Chạy `replay_certified` audit và Python `single_pass` public result trên cùng data, params và execution config.

```python
def _position_series(run, symbol: str) -> pd.Series:
    return (
        run.result.positions[
            f"Position_{symbol}"
        ]
        .astype(np.float64)
        .copy()
    )


def _transition_bars(
    position: pd.Series,
) -> pd.DatetimeIndex:
    values = position.to_numpy(
        dtype=np.float64,
    )

    changed = np.zeros(
        len(values),
        dtype=bool,
    )

    if len(values) > 1:
        changed[1:] = (
            np.diff(values) != 0.0
        )

    return position.index[changed]


def _fill_frame(result) -> pd.DataFrame:
    rows = []

    for fill in result.fills:
        metadata = dict(
            getattr(fill, "metadata", None)
            or {}
        )

        rows.append(
            {
                "timestamp": pd.Timestamp(
                    fill.timestamp
                ),
                "order_id": getattr(
                    fill,
                    "order_id",
                    None,
                ),
                "symbol": getattr(
                    fill,
                    "symbol",
                    None,
                ),
                "side": str(
                    getattr(fill, "side", "")
                ),
                "qty": float(fill.qty),
                "price": float(fill.price),
                "fee": float(
                    getattr(fill, "fee", 0.0)
                ),
                "role": metadata.get("role"),
                "grid_side": metadata.get(
                    "grid_side"
                ),
                "level_id": metadata.get(
                    "level_id"
                ),
            }
        )

    if not rows:
        return pd.DataFrame()

    return (
        pd.DataFrame(rows)
        .sort_values(
            ["timestamp", "order_id"],
            kind="stable",
        )
        .reset_index(drop=True)
    )
```

```python
oracle_position = _position_series(
    oracle_run,
    execution_oracle.symbol,
)

python_position = _position_series(
    python_public_run,
    execution_python_minimal.symbol,
)

position_diff = (
    python_position
    - oracle_position
)

divergent_bars = position_diff.index[
    np.abs(
        position_diff.to_numpy(
            dtype=np.float64
        )
    ) > 1e-12
]

oracle_transitions = _transition_bars(
    oracle_position
)

python_transitions = _transition_bars(
    python_position
)

oracle_fills = _fill_frame(
    oracle_run.result
)

python_fills = _fill_frame(
    python_public_run.result
)

comparison = {
    "oracle_num_trades": (
        oracle_run.result.full_report(
            trading_days=365,
            scope="full",
        )["num_trades"]
    ),
    "python_num_trades": (
        python_public_run.result.full_report(
            trading_days=365,
            scope="full",
        )["num_trades"]
    ),
    "oracle_fill_count": len(
        oracle_fills
    ),
    "python_fill_count": len(
        python_fills
    ),
    "oracle_total_fee": float(
        oracle_run.result.fees.sum()
    ),
    "python_total_fee": float(
        python_public_run.result.fees.sum()
    ),
    "oracle_total_funding": float(
        oracle_run.result.funding.sum()
    ),
    "python_total_funding": float(
        python_public_run.result.funding.sum()
    ),
    "first_divergent_bar": (
        None
        if len(divergent_bars) == 0
        else divergent_bars[0]
    ),
    "extra_python_transitions": (
        python_transitions.difference(
            oracle_transitions
        ).tolist()
    ),
    "missing_python_transitions": (
        oracle_transitions.difference(
            python_transitions
        ).tolist()
    ),
}

print(json.dumps(
    comparison,
    indent=2,
    default=str,
))
```

## 16.2. Cách xác định lỗi

```text
Command tape khác trước fill lệch đầu tiên
→ strategy context/callback/active-order payload.

Command tape giống nhưng fills khác
→ order priority, touch, AMEND/CANCEL_ALL/OCO,
  reduce-only hoặc quantity constraints.

Fills giống nhưng positions/equity khác
→ accounting, fee, funding, margin/liquidation.

Positions giống nhưng num_trades khác
→ metric implementation.
```

Không dùng tolerance để che một fill hoặc position transition khác thật.

Chỉ chấp nhận chênh lệch tăng 2 khi chứng minh:

```text
A. Python mới khớp replay-certified và bản cũ bỏ sót
   đúng hai position transitions/fills; hoặc

B. lifecycle/fills giống nhau, chỉ metric counting sai
   và được sửa về cùng semantics.
```

---

# 17. Vì sao optimizer chưa nhanh hơn đáng kể

Prepared scalar v2 giảm:

```text
market normalization lặp lại
pandas BacktestResult materialization
equity/position/fee/funding paths
full fill/event ledgers
```

Nhưng Grid vẫn còn ba hotspot lớn.

## 17.1. Alpha tính lại toàn bộ mỗi trial

`build_grid_strategy()` gọi lại:

```python
prepare_grid_alpha_frame(
    df=df,
    params=params,
)
```

Mỗi trial vẫn thực hiện DataFrame copy, MA/ATR, 60 grid levels và diagnostic aliases.

## 17.2. Python reactive callback vẫn chạy từng bar

Mỗi bar vẫn có:

```text
alpha_frame.iloc[bar]
iterate 30 GridLegState
scan active_orders
build dictionaries
process fill metadata
construct OrderCommand objects
```

Scalar result không loại bỏ phần này.

## 17.3. Strategy vẫn allocate diagnostics trong score mode

Grid luôn giữ và ghi `_diag_*` arrays dù `report_level="score"`.

Những arrays này thuộc strategy, không thuộc engine artifact plan.

---

# 18. Gate xác nhận optimizer dùng đúng scalar path

Không benchmark bằng:

```text
grid_objective
make_grid_objective
run_grid_backtest
result.full_report
```

Optimizer mới phải dùng:

```text
PreparedNativeEventStrategyEvaluator
PreparedNativeEventStrategyRunner.score
NativeEventScalarScoreResult
```

Sau một trial:

```python
scores_before = prepared_grid.scores
runs_before = prepared_grid.runs

objective_result = evaluator.evaluate(
    best_params_long_only
)

assert (
    prepared_grid.scores
    == scores_before + 1
)

assert prepared_grid.runs == runs_before
assert prepared_grid.endpoint.result is None
assert evaluator.last_result is None
assert evaluator.last_strategy is None
```

Evaluator phải có:

```python
retain_last=False
```

---

# 19. Profile đúng một optimizer trial

```python
import time


def profile_grid_trial(
    params,
    *,
    repeats: int = 5,
):
    rows = []

    for _ in range(repeats):
        started = time.perf_counter()

        alpha_frame = (
            prepare_grid_alpha_frame(
                data_2000,
                dict(params),
            )
        )

        after_alpha = time.perf_counter()

        strategy = (
            ReactiveDynamicGridStrategy(
                alpha_frame=alpha_frame,
                params=dict(params),
                execution=(
                    execution_python_scalar
                ),
            )
        )

        after_strategy = time.perf_counter()

        requirements = (
            NativeEventScoreRequirements
            .from_strategy(
                strategy,
                base=(
                    NativeEventScoreRequirements
                    .scalar_score_contract()
                ),
            )
        )

        score = prepared_scalar.score(
            strategy,
            trading_days=365,
            score_requirements=requirements,
        )

        after_score = time.perf_counter()

        rows.append(
            {
                "alpha_seconds": (
                    after_alpha - started
                ),
                "strategy_init_seconds": (
                    after_strategy
                    - after_alpha
                ),
                "engine_score_seconds": (
                    after_score
                    - after_strategy
                ),
                "total_seconds": (
                    after_score - started
                ),
                "fill_count": int(
                    score.fill_count
                ),
                "num_trades": int(
                    score.metrics["num_trades"]
                ),
            }
        )

    return pd.DataFrame(rows)


profile = profile_grid_trial(
    best_params_long_only
)

print(profile)
print(
    profile.median(
        numeric_only=True
    )
)
```

Agent phải report tỷ trọng:

```text
alpha preparation %
strategy initialization %
engine score %
Optuna/objective overhead %
```

Nếu alpha preparation và callback chiếm đa số thời gian thì scalar v2 hoạt động đúng nhưng optimizer tổng thể chỉ cải thiện ít.

---

# 20. Safe Grid optimizer patches

Chỉ implement sau khi Section 16 parity pass.

## 20.1. Minimal context declaration

Thêm vào `ReactiveDynamicGridStrategy`:

```python
native_context_requirements = {
    "fills": True,
    "events": False,
    "active_orders": True,
    "positions": True,
    "margin": False,
}
```

Grid không đọc `order_events_this_bar` hoặc margin payload trực tiếp.

Direct score phải dùng:

```python
requirements = (
    NativeEventScoreRequirements
    .from_strategy(
        strategy,
        base=(
            NativeEventScoreRequirements
            .scalar_score_contract()
        ),
    )
)
```

Không tắt fills, active orders hoặc positions.

## 20.2. Tắt diagnostics trong score mode

Thêm:

```python
collect_diagnostics: bool = True
```

vào `GridExecutionConfig`.

Scalar/optimizer:

```python
collect_diagnostics=False
```

Khi false:

```text
không allocate _diag_* arrays
_record_diagnostics() return ngay
không gọi build_output_frame()
```

Default `True` để không đổi public/audit behavior.

## 20.3. Bỏ diagnostic alias columns trong score mode

Thêm:

```python
def prepare_grid_alpha_frame(
    df: pd.DataFrame,
    params: Dict,
    *,
    include_diagnostic_aliases: bool = True,
) -> pd.DataFrame:
```

Chỉ tạo:

```text
long_entry_*
long_exit_*
short_entry_*
short_exit_*
```

khi cần audit/plot. Strategy execution không sử dụng các aliases này.

## 20.4. Prepared Grid alpha factory

Nếu profile xác nhận alpha là hotspot, thêm bounded cache:

```text
PreparedGridAlphaFactory
```

Cache immutable components:

```text
MA:        (ma_type, ma_len)
ATR:       ma_len
EMA short: ema_len_short
```

Yêu cầu:

```text
reuse OHLC4/true-range base
bounded entries/bytes
fresh strategy state mỗi trial
clear() method
không cache vô hạn full DataFrames
```

Giữ `alpha_factory=None` làm backward-compatible fallback.

---

# 21. Performance acceptance bổ sung

Không đặt hệ số tăng tốc cứng trước khi tách hotspot.

Agent phải cung cấp:

```text
legacy public objective seconds/trial
prepared scalar seconds/trial
alpha preparation seconds/trial
engine score seconds/trial
total optimizer wall time
peak RSS
```

Acceptance:

```text
parity pass
prepared scalar không chậm hơn legacy
RSS không regression
không retain result/strategy giữa trials
diagnostic/context payload dư được loại bỏ
```

Không dùng benchmark Rust batched/static tape để claim tốc độ cho Python reactive Grid optimizer.

---

# 22. Definition of Done bổ sung

- giải thích chính xác `num_trades +2`;
- xác định đúng hai bar/transition/fill gây khác biệt;
- Python single-pass khớp replay-certified lifecycle;
- không nhầm `num_trades` với round-trip trades;
- optimizer xác nhận dùng prepared scalar evaluator;
- `scores` tăng nhưng `runs` không tăng;
- `endpoint.result` không materialize;
- có timing breakdown alpha/strategy/engine/objective;
- score mode không giữ Grid diagnostics không cần thiết;
- Grid khai báo minimal context requirements;
- mọi performance patch giữ command/fill/accounting parity.


# QuantBT pre-48E — Apples-to-Apples Native Event Performance Pass

## 1. Mục tiêu

Phase `pre-48E` được thực hiện **trước Phase 48E** để:

```text
1. Đo đúng ba workload khác nhau.
2. Tách cold compile khỏi warm execution.
3. Tối ưu fast path an toàn của Python và Rust.
4. Giữ exact domain parity với replay-certified.
5. Tạo baseline pre/post cùng commit, cùng máy, cùng artifact contract.
```

Không dùng benchmark lịch sử khác commit làm release gate. Các số cũ chỉ là tham khảo.

Phase 48C chỉ thêm facade và benchmark; không tạo execution loop thứ hai. Không tối ưu facade trước khi profiling chứng minh có overhead.

---

# 2. Ba benchmark bắt buộc

## A. Explicit Native Event

Đo engine thuần với command tape đã chuẩn bị:

```text
QuantBTEndpoint.native_event_lifecycle(...)
QuantBTEndpoint.event_driven(input_mode="orders", ...)
```

Cases:

```text
25,000 bars
low churn
high churn
Python score
Rust score
Python audit
Rust audit
cold prepare
warm prepared replay
```

Đây là benchmark đúng cho:

```text
matching
order lifecycle
quantity constraints
fees/funding/margin
Rust batched execution
```

## B. Generic Event-Driven Strategy

Dùng một callback deterministic, không tính indicator nặng:

```text
native_event_strategy
event_driven(input_mode="strategy")
Python backend
Rust backend
```

Callback phải phát cùng command sequence theo bar index để đo:

```text
context creation
callback bridge
command retime/quantize
constraints
matching/accounting
PyO3 crossing
```

## C. Reactive Grid

Chạy riêng sau A và B:

```text
2,000 bars
long_only
long_short
Python scalar
Rust scalar
audit fingerprint
```

Grid là integration/stress benchmark, không dùng để đại diện cho engine thuần.

---

# 3. Benchmark contract

Tạo:

```text
benchmarks/native_event/benchmark_pre48e.py
benchmarks/native_event/results/pre48e/baseline.json
benchmarks/native_event/results/pre48e/after.json
benchmarks/native_event/results/pre48e/report.md
```

Mỗi case chạy process riêng:

```text
1 compile/warm-up run
7 measured runs
median
p95
CPU time
VmHWM peak RSS
RSS after prepare
RSS after run
100-run RSS slope
```

Ghi environment:

```text
commit SHA
dirty status
Python/NumPy/Numba versions
Rust/native API version
CPU model
backend resolution
report profile
bars
commands
active-order peak
```

## Artifact parity

Chỉ so cùng contract:

```text
score ↔ score
minimal ↔ minimal
audit ↔ audit
```

Không so Python audit với Rust score.

Fingerprint bắt buộc:

```text
commands/effective bars
events/status/reject reason
fills
positions
fees
funding
turnover
initial/maintenance margin
liquidation
final equity
```

Discrete fields exact. Numeric:

```python
rtol = 0.0
atol <= 1e-12
```

---

# 4. Instrumentation trước khi tối ưu

Thêm counters, không đổi semantics:

```text
bars_processed
bars_with_commands
bars_with_active_orders
bars_fast_skipped
contexts_materialized
timestamp_objects_materialized
active_snapshots_materialized
constraint_preflight_calls
commands_retimed
commands_quantized
rejection_objects_created
audit_rows_created
Python↔Rust step calls
bytes copied to/from Rust
```

Output counters vào JSON benchmark.

Không kết luận nhanh hơn nếu counters cho thấy engine đã bỏ bớt công việc domain cần thiết.

---

# 5. Safe fast paths — Python backend

## P1. Cache constraint policy một lần

Tại endpoint/prepared-runner construction:

```python
constraints_enabled = constraints.enabled

has_qty_step = qty_step is not None
has_min_qty = min_qty is not None
has_min_notional = min_notional is not None
```

Tạo hai dispatch paths:

```text
_apply_commands_no_constraints
_apply_commands_with_constraints
```

Không kiểm `constraints.enabled` lặp lại trong từng bar/từng command.

Chỉ chạy quantity preflight cho:

```text
PLACE
AMEND có qty
REPLACE có qty
```

Không chạy cho:

```text
empty batch
CANCEL
CANCEL_ALL
AMEND chỉ đổi price
```

Parity tests phải khóa:

```text
quantized qty
reject reason
fee/margin result
```

## P2. Empty-command fast path

Hiện retime/quantize không được gọi khi callback trả:

```python
()
[]
None
```

Fast branch:

```python
if not emitted_commands:
    skip _retime_reactive_commands
    skip quantize_reactive_schedule
    skip command preflight
```

Dùng singleton empty tuple, không tạo list mới.

## P3. Reactive next-bar queue

Callback strategy có contract:

```text
commands emitted at bar N
become effective at bar N+1
```

Không cần chạy general schedule quantizer cho từng batch.

Dùng hai reusable buffers:

```text
commands_due_now
commands_due_next
```

Sau callback:

```text
compile directly into commands_due_next
swap buffers at next bar
```

General timestamp retime chỉ giữ cho explicit orders hoặc custom schedule path.

Đây là fast path nội bộ; public timing semantics không đổi.

## P4. Timestamp int64 và lazy `pd.Timestamp`

Prepared market lưu:

```python
timestamps_ns: np.ndarray[np.int64]
```

Context nội bộ dùng `timestamp_ns`.

Chỉ tạo:

```python
pd.Timestamp(timestamp_ns, tz="UTC")
```

khi strategy thực sự truy cập `context.timestamp`.

Không index `DatetimeIndex[bar]` trong hot loop.

Có thể dùng lazy property:

```python
@property
def timestamp(self):
    if self._timestamp_obj is None:
        self._timestamp_obj = pd.Timestamp(
            self.timestamp_ns,
            tz="UTC",
        )
    return self._timestamp_obj
```

Reset cache khi chuyển bar.

## P5. Reuse context object

Không tạo graph context mới mỗi bar.

Dùng một internal context có `slots`:

```text
bar_index
timestamp_ns
OHLCV scalars
equity
liquidated
references to requested payloads
```

Mỗi bar chỉ cập nhật primitives/references.

Giữ callback view read-only.

## P6. Lazy context payloads

Dựa trên `NativeEventScoreRequirements.from_strategy(...)`.

Không tạo nếu strategy không yêu cầu:

```text
order_events_this_bar
active_orders
positions dict
margin payload
metadata copies
```

Active-order snapshot chỉ rebuild khi:

```text
active_generation thay đổi
và strategy yêu cầu active_orders
```

Bar không có lifecycle mutation được reuse immutable tuple.

## P7. No-state bar fast path

Precompute:

```text
funding_mask[bar]
```

Nếu:

```text
no active orders
no commands due
flat position
not funding bar
```

thì chỉ cập nhật scalar bar/accounting tối thiểu; bỏ:

```text
matching
constraint processing
margin/liquidation checks
active snapshot work
```

Nếu có position nhưng không active orders/commands:

```text
vẫn mark-to-market
vẫn funding/liquidation đúng phase
```

Không được skip accounting chỉ vì không có lệnh.

## P8. Tách score khỏi audit

`report_level="score"`:

```text
online scalar metrics
terminal positions
lifecycle counters
không ledger rows
không pandas
không rejection/event object nếu không phát sinh
```

`audit` mới giữ:

```text
full fills
events
rejections
paths
command report
```

Không tạo ledger rồi bỏ đi ở cuối.

## P9. Numba compile policy

Đo riêng:

```text
prepare time
first run compile
warm run
```

Các kernel ổn định dùng:

```python
@njit(cache=True)
```

Prepared runner warm đúng signature trước measured runs.

Không tính compile time vào warm execution regression.

---

# 6. Safe fast paths — Rust backend

## R1. Không clone prepared market theo session

Session giữ:

```rust
Arc<FullMarketData>
```

Không copy lại timestamps/OHLCV/funding cho mỗi run.

Python bỏ temporary normalized arrays sau khi Rust prepared market được tạo.

## R2. Reusable full command buffer

API 0.4 cần reusable:

```text
codes
values
expiry
symbol/order/group/OCO intern IDs
```

Không `np.zeros`/`np.full` từng callback bar.

Buffer chỉ grow khi capacity thiếu; expose:

```text
capacity
growth_count
commands_compiled
```

## R3. Conditional step output

Rust step nhận output requirements:

```text
score
reactive_context
audit
```

Không unconditional:

```text
clone positions
materialize active orders
allocate fills/events nested vectors
```

Chỉ trả context fields callback yêu cầu.

## R4. Reusable SoA buffers

Dùng session-owned vectors:

```text
fill_order_id/fill_qty/fill_price/fill_fee
event_kind/event_status/event_order_id
active_order primitive fields
```

Mỗi bar:

```rust
clear()
```

giữ capacity.

Không trả `Vec<Vec<...>>` trong hot path.

## R5. Full order arena và indexes

Không giữ terminal orders trong vector tăng vô hạn.

Dùng:

```text
slot arena
id_to_slot
stable active_sequence
free_slots
```

Indexes:

```text
children_by_parent
members_by_oco
members_by_group
expiry_by_bar
```

Không scan toàn bộ historical orders cho:

```text
expiry
parent activation
OCO
CANCEL_ALL
active snapshots
```

Event ordering phải theo insertion priority, không theo HashMap.

## R6. GIL policy

Release GIL cho:

```text
run_tape_score
run_tape_audit
long run_until chunk
```

Không mặc định release/reacquire mỗi reactive bar nếu benchmark chưa chứng minh lợi ích.

## R7. Typed result boundary

Thay per-bar `PyDict` bằng typed frozen PyClass hoặc tuple-like result.

Dictionary conversion chỉ ở adapter/report layer.

---

# 7. Patch order

## pre-48E.A — Freeze baseline

Không sửa hot path.

Chạy đủ A/B/C và commit:

```text
baseline.json
report.md
parity fingerprints
```

## pre-48E.B — Python zero-work fast paths

Implement lần lượt:

```text
constraint dispatch cache
empty-command skip
next-bar queue
timestamp lazy
context reuse/lazy payload
```

Sau mỗi patch:

```text
A/B/C parity
A/B/C benchmark
```

## pre-48E.C — Score/audit separation

Loại ledger/object work khỏi score path.

Rerun full matrix.

## pre-48E.D — Rust bridge/allocation

Implement:

```text
shared prepared market
reusable command buffer
conditional output
SoA buffers
```

Rerun full matrix.

## pre-48E.E — Rust lifecycle data structures

Implement order arena và indexes.

Rerun high-churn explicit benchmark và Grid parity.

## pre-48E.F — Freeze accepted result

Commit:

```text
after.json
report.md
before/after table
exact parity result
remaining hotspots
```

Sau đó mới bắt đầu Phase 48E.

---

# 8. Acceptance

Correctness is mandatory:

```text
100% oracle/Python/Rust parity
no changed fills
no changed rejection
no changed fee/funding/margin/liquidation
```

Performance:

```text
không có hard speedup bắt buộc
không được chậm hơn baseline mới nếu không giải thích được
RSS không regression >10–15%
100-run RSS slope không dương đáng kể
```

Target mong đợi, không phải hard gate:

```text
explicit prepared score:
    Python cải thiện nhờ bỏ retime/constraint/object work
    Rust giữ lợi thế batched

generic reactive:
    giảm context và empty-bar overhead

Grid:
    cải thiện vừa phải;
    callback strategy vẫn có thể là bottleneck chính
```

Không dùng static Rust tape speedup để quảng bá reactive Grid speedup.

---

# 9. Definition of Done

`pre-48E` hoàn thành khi:

- có benchmark explicit orders riêng;
- có benchmark generic event-driven riêng;
- có benchmark Grid riêng;
- cold/warm và score/audit được tách;
- facade/direct constructor parity;
- baseline và after chạy cùng commit/environment contract;
- hotspot counters chứng minh công việc đã giảm;
- Python/replay/Rust full fingerprint vẫn bằng nhau;
- RSS plateau;
- remaining hotspot được ghi rõ cho Phase 48E.


# QuantBT Phase 48E.1 — Native Production Closure Before 48F

## 0. Mục tiêu

Phase này nằm giữa `48E` và `48F`.

```text
48E:
    reusable command/context
    prepared market sharing
    projection mask
    reset/cache
    terminal-order compaction
    local Python/Rust parity

48E.1:
    hoàn thiện Rust output/allocation path
    hoàn thiện report contract
    khóa production parity
    xác nhận native wheel behavior

48F:
    TestPyPI artifact gate
    release workflow
    final handoff
```

Không thêm endpoint mới, không đổi default backend và không thay domain formulas.

Ưu tiên tuyệt đối:

```text
domain correctness
→ oracle parity
→ report completeness
→ bounded RSS
→ runtime
```

---

# 1. Trạng thái đầu vào đã được chấp nhận

Agent phải đọc trước:

```text
upgrade/implement.md
benchmarks/native_event/results/pre48e/
benchmarks/native_event/results/phase48e/
tests/native_event/test_phase48e_reuse.py
rust/native_event/src/full.rs
rust/native_event/src/lib.rs
src/quantbt/backends/_native_event_rust.py
src/quantbt/backends/native_event.py
```

Phase 48E hiện đã có:

```text
reusable Python full command buffer
reusable Python context
Rust projection mask
Arc<FullMarketData>
terminal-order compaction
active-order snapshot cache
reset/cache counters
Python/Rust score-audit parity
```

Không viết lại những phần này nếu không có failing test hoặc profiler evidence.

---

# 2. Phạm vi bắt buộc trước 48F

## P0 — Hoàn thành conditional Rust output

Projection mask hiện không được chỉ giảm payload qua PyO3. Nó phải giảm allocation ngay trong lifecycle loop.

Score path vẫn phải thực hiện đầy đủ:

```text
matching
accept/reject
fills
fees
funding
margin
liquidation
parent/OCO/TIF
counters
```

Nhưng không được tạo các row/vector bị bỏ đi sau đó.

### Thiết kế

Thay helper nhận trực tiếp:

```rust
&mut Vec<Vec<i64>>
&mut Vec<Vec<f64>>
```

bằng output sink:

```rust
struct StepCounters {
    fill_count: u32,
    event_count: u32,
    rejected_count: u32,
    canceled_count: u32,
}

enum DetailSink<'a> {
    CountOnly(&'a mut StepCounters),
    Collect {
        counters: &'a mut StepCounters,
        buffers: &'a mut StepBuffers,
    },
}
```

Ví dụ:

```rust
impl DetailSink<'_> {
    #[inline]
    fn event(
        &mut self,
        kind: EventKind,
        status: OrderStatus,
        order_id: i64,
        target_id: i64,
        symbol: SymbolIndex,
        reject: RejectCode,
    ) {
        match self {
            DetailSink::CountOnly(counters) => {
                counters.event_count += 1;
                counters.rejected_count +=
                    u32::from(status == OrderStatus::Rejected);
                counters.canceled_count +=
                    u32::from(status == OrderStatus::Canceled);
            }
            DetailSink::Collect {
                counters,
                buffers,
            } => {
                counters.event_count += 1;
                buffers.push_event(
                    kind,
                    status,
                    order_id,
                    target_id,
                    symbol,
                    reject,
                );
            }
        }
    }
}
```

Không duplicate lifecycle logic thành `score_step()` và `audit_step()` riêng.

Một implementation, nhiều sinks.

### Acceptance

Score mode:

```text
fill/event counters đúng
fills/events vectors capacity không tăng
không tạo nested row allocation
```

Audit mode:

```text
đủ rows
đúng thứ tự
đúng reject/status
```

---

## P1 — Dùng reusable SoA buffers

Không dùng:

```rust
Vec<Vec<f64>>
Vec<Vec<i64>>
```

trong hot path.

### Rust structures

```rust
#[derive(Default)]
struct FillBuffer {
    order_id: Vec<i64>,
    symbol: Vec<u32>,
    side: Vec<i8>,
    qty: Vec<f64>,
    price: Vec<f64>,
    fee: Vec<f64>,
}

#[derive(Default)]
struct EventBuffer {
    kind: Vec<u8>,
    status: Vec<u8>,
    order_id: Vec<i64>,
    target_id: Vec<i64>,
    symbol: Vec<u32>,
    reject_code: Vec<i16>,
}

#[derive(Default)]
struct ActiveOrderBuffer {
    order_id: Vec<i64>,
    symbol: Vec<u32>,
    side: Vec<i8>,
    order_type: Vec<u8>,
    tif: Vec<u8>,
    flags: Vec<u16>,
    qty: Vec<f64>,
    price: Vec<f64>,
    trigger: Vec<f64>,
    parent_id: Vec<i64>,
    group_id: Vec<i64>,
    oco_id: Vec<i64>,
    expires_bar: Vec<i64>,
}

#[derive(Default)]
struct StepBuffers {
    fills: FillBuffer,
    events: EventBuffer,
    active_orders: ActiveOrderBuffer,
}
```

Mỗi bar:

```rust
buffers.clear();
```

`clear()` chỉ đặt length về 0, không shrink.

Thêm:

```rust
fn release_excess_capacity(
    &mut self,
    max_capacity: usize,
)
```

chỉ dùng thủ công/service maintenance, không gọi mỗi trial.

### Vì sao SoA phù hợp

```text
không heap allocation cho từng row
ít padding hơn
copy sang NumPy theo cột
report DataFrame dựng trực tiếp
dễ omit từng projection
RSS plateau rõ hơn
```

### Không làm

Không dùng unsafe borrowed NumPy views trong phase này.

Rust-owned buffers không được bị mutation trong khi Python đang giữ view.

Cách an toàn trước release:

```text
score:
    không return rows

reactive callback:
    convert/copy chỉ requested rows của bar hiện tại

audit:
    append vào session-owned audit SoA
    convert sang NumPy một lần khi finalize
```

---

## P2 — Tối ưu kiểu dữ liệu Rust nội bộ

Public command ABI có thể tiếp tục dùng `i64/f64` để ổn định wheel API.

Sau validation, chuyển ngay sang type nhỏ nội bộ.

### Enums

```rust
#[repr(u8)]
enum OrderAction {
    Place,
    Cancel,
    CancelAll,
    Amend,
    Replace,
}

#[repr(u8)]
enum OrderType {
    Market,
    Limit,
    StopMarket,
    StopLimit,
}

#[repr(u8)]
enum TimeInForce {
    Gtc,
    Gtd,
    Ioc,
    Fok,
}

#[repr(u8)]
enum OrderStatus {
    Pending,
    Filled,
    Canceled,
    Rejected,
    Expired,
}

#[repr(i8)]
enum Side {
    Sell = -1,
    Buy = 1,
}

#[repr(i16)]
enum RejectCode {
    None,
    InvalidOrder,
    InsufficientMargin,
    QuantityConstraint,
    ReduceOnly,
    MissingTarget,
}
```

Dùng validated decoder:

```rust
impl TryFrom<i64> for OrderType {
    type Error = String;

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        // exhaustive validation
    }
}
```

Không `transmute`.

### Index types

Dùng:

```text
symbol index: u32
slot index: usize
bar index nội bộ: usize
order ID/client ID: i64
parent/group/OCO ID: i64
```

Không ép order IDs xuống `u32`; ID là public identity, không phải array index.

### Flags

Gộp booleans nóng:

```rust
const FLAG_REDUCE_ONLY: u16 = 1 << 0;
const FLAG_ACTIVE: u16 = 1 << 1;
const FLAG_WAITING_PARENT: u16 = 1 << 2;
```

Không cần đổi tất cả booleans nếu benchmark không cho thấy lợi ích, nhưng `OrderState` mới không nên chứa nhiều `i64` cho enum/status.

### Immutable arrays

Với dữ liệu không grow sau construction:

```rust
pub struct FullMarketData {
    timestamps_ns: Box<[i64]>,
    opens: Box<[f64]>,
    highs: Box<[f64]>,
    lows: Box<[f64]>,
    closes: Box<[f64]>,
    volumes: Box<[f64]>,
    funding: Box<[f64]>,
    funding_mask: Box<[u8]>,
}
```

`Arc<FullMarketData>` giữ ownership.

`Box<[T]>` làm rõ immutable fixed-length storage và không giữ excess capacity.

`Vec<bool>` có thể tiết kiệm RAM nhưng truy cập bit proxy có thể chậm. Với `funding_mask`, benchmark:

```text
Box<[u8]>
vs
Vec<bool>
```

Chọn theo apples-to-apples result; không giả định.

### Account configuration

Các arrays fixed-length:

```rust
contract_sizes: Box<[f64]>
leverages: Box<[f64]>
fee_rates: Box<[f64]>
```

---

## P3 — Typed PyO3 result thay per-bar `dict`

Reactive step không nên tạo `PyDict` và string lookup mỗi bar.

### Result class

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
    fill_count: u32,

    #[pyo3(get)]
    event_count: u32,

    #[pyo3(get)]
    rejected_count: u32,

    #[pyo3(get)]
    canceled_count: u32,

    #[pyo3(get)]
    liquidated: bool,

    #[pyo3(get)]
    liquidation_bar: i64,

    #[pyo3(get)]
    liquidation_reason: i16,

    // Optional projected payload handles.
}
```

Không đặt `positions`, fills/events/active orders thành nested lists.

Chúng phải là:

```text
None khi không requested
typed arrays/tuples khi requested
```

### Compatibility

Giữ API cũ:

```python
step(...)
```

nhưng cho adapter Python convert typed result về contract cũ khi thật sự cần.

Internal optimized path gọi:

```python
step_projected(...)
```

Không đổi public endpoint hoặc strategy protocol.

---

## P4 — Report contract đầy đủ

Tách ba profiles:

```text
score
research/minimal
audit
```

## Score

Giữ:

```text
online metrics
final equity
terminal positions
fees/funding/turnover totals
margin maxima/final
liquidation
fill/event/reject/cancel counts
parity fingerprint
```

Không giữ ledger rows.

Candidate tốt nhất phải rerun bằng audit.

## Research/minimal

Giữ dense accounting paths:

```text
equity
positions
fees
funding
turnover
initial margin
maintenance margin
liquidation
close prices
```

Đủ cho:

```text
full_report
Sharpe
drawdown
exposure
fee/funding attribution
margin utilization
```

Không bắt buộc giữ full lifecycle ledger.

## Audit

Giữ:

```text
dense accounting paths
fills
order lifecycle events
rejections
commands
parent/OCO/TIF transitions
liquidation reason
required metadata
```

### `command_report` phải độc lập

Không được gán:

```python
command_report = order_report
```

`command_report` phải lấy từ command tape/compiled side table:

```text
command index
requested/effective bar
action
order ID/target ID
symbol
side
order type
TIF
qty/price/trigger
reduce-only
parent/group/OCO
activation/expiry
tag
strategy metadata
```

`order_report` là kết quả lifecycle:

```text
event bar
event type
status
reject code
order ID/target ID
symbol
```

### Fill metadata

Rust hot path chỉ trả:

```text
order ID
symbol
side
qty
price
fee
bar
```

Python audit boundary enrich từ:

```python
command_metadata_by_order_id
```

để giữ:

```text
role
campaign_id
cycle_id
level_id
grid_side
tag
```

Không copy metadata dict mỗi bar.

### `result.orders`

Cho phiên bản này:

```text
order_report = canonical lifecycle report
result.orders có thể để rỗng
```

Nhưng phải:

```text
document rõ
Python và Rust cùng semantics
report/viz không phụ thuộc result.orders
test export bundle
```

Không để Python có một report đầy đủ nhưng Rust mất lifecycle surface.

---

## P5 — Margin/accounting cache an toàn

Current lifecycle không được gọi full-symbol margin scan nhiều lần không cần thiết.

### Cache per bar

```rust
struct MarginCache {
    bar: usize,
    initial_margin: f64,
    maintenance_margin: f64,
    valid: bool,
}
```

Đầu bar:

```text
compute close margin một lần
```

Sau fill/liquidation:

```text
mark dirty hoặc update symbol delta
```

### O(1) symbol delta

Với fill tại symbol `s`:

```text
old symbol margin
new symbol margin
delta initial
delta maintenance
```

Update totals thay vì scan toàn bộ symbols sau từng fill.

Chỉ implement delta path sau golden tests cho:

```text
long add
partial reduce
full close
reversal
reduce-only
multi-symbol
margin rejection
liquidation after order
```

Nếu parity khó khóa, giữ dirty-cache/rescan once after batch; correctness quan trọng hơn micro-optimization.

---

## P6 — Compaction production hardening

Không rewrite order arena trước 48F.

Giữ compaction hiện tại nhưng tăng test coverage.

Bắt buộc:

```text
replace alias tồn tại sau compaction
waiting parent child vẫn activate đúng
OCO siblings vẫn cancel đúng
GTD vẫn expire đúng
multi-symbol insertion priority không đổi
CANCEL/AMEND target resolution không đổi
reset fingerprint bằng fresh session
```

Compaction chỉ chạy:

```text
sau lifecycle work của bar
không chạy giữa command/fill sequence
```

Không compact bằng hash-map iteration.

Nếu high-churn benchmark vẫn cho thấy scan/compaction là hotspot lớn, ghi debt:

```text
Phase 49 — Indexed Order Arena
```

Không đưa arena rewrite lớn vào release closure.

---

## P7 — Legacy adapter isolation

Full API 0.4 không được route qua legacy adapter có assumptions:

```text
single symbol
no funding
no liquidation
old report schema
```

Selector phải:

```text
API 0.4 + full capability:
    RustFull* adapter

API cũ:
    explicit compatibility path

native_backend="rust":
    fail fast nếu full capability thiếu
```

Không silent Python fallback cho explicit Rust.

Thêm capability test kiểm class/route thật, không chỉ kiểm key dictionary.

---

# 3. Patch order cho agent

## 48E.1-A — Freeze current baseline

Commit:

```text
benchmark JSON
fingerprints
current RSS/runtime
current report schemas
```

Không sửa hot path trước baseline.

## 48E.1-B — R3 conditional allocation

Files chính:

```text
rust/native_event/src/full.rs
rust/native_event/src/lib.rs
```

Implement:

```text
StepCounters
DetailSink
no fills/events allocation in score
```

Gate parity.

## 48E.1-C — R4 SoA + typed step result

Implement:

```text
FillBuffer
EventBuffer
ActiveOrderBuffer
FullStepResultCore
```

Update adapter:

```text
src/quantbt/backends/_native_event_rust.py
root mirror equivalent
```

Gate parity và benchmark.

## 48E.1-D — Compact internal types

Implement validated enums, compact indices/flags và boxed immutable arrays.

Không đổi external command ABI.

Run:

```text
cargo fmt
clippy -D warnings
cargo test --release
Python/Rust contract tests
```

## 48E.1-E — Report closure

Implement:

```text
separate command_report
fill metadata enrichment
score/research/audit profile tests
full_report parity
export bundle
```

## 48E.1-F — Compaction/reset hardening

Thêm relationship tests và 100-run plateau.

## 48E.1-G — Installed-wheel gate

Trên CPython:

```text
3.11
3.12
3.13
```

Mỗi wheel:

```text
manylinux install
core + native clean install
API 0.4/capabilities
full contract suite
report tests
Grid smoke
pip check
RSS plateau
```

---

# 4. Tests bắt buộc

## Domain

```text
all actions
all order types
GTC/GTD/IOC/FOK
quantity constraints
reduce-only
parent
group
OCO
funding
margin
intrabar liquidation
after-funding liquidation
after-order liquidation
single/multi-symbol
```

## Output mask

Mọi tổ hợp hợp lệ:

```text
counts only
positions
fills
events
active orders
positions + fills
positions + events
full audit
```

Kết quả accounting/lifecycle phải giống nhau.

## Reports

```text
Python full_report == Rust full_report
fills report schema/value parity
order report schema/value parity
command report schema/value parity
funding survives adapter
liquidation survives adapter
metadata enrichment
audit export bundle
```

## Memory

```text
score buffers không grow
audit buffers reuse capacity
reset clears logical state
100 runs plateau
prepared market shared
no retained strategy/result
```

## Compaction

```text
replace aliases
parent waiting children
OCO
GTD
priority
multi-symbol
```

---

# 5. Benchmark matrix

Process-isolated:

```text
explicit low churn score/audit
explicit high churn score/audit
generic callback score/audit
Grid long-only/long-short
```

Mỗi case:

```text
1 warm-up
7 measured
median/p95
CPU time
VmHWM
RSS after prepare
RSS after run
100-run slope
```

Counters:

```text
events allocated
fills allocated
active snapshots
positions copies
PyO3 calls
bytes returned
buffer growths
compactions
terminal removed
margin recomputes
```

Không claim nhanh hơn nếu work counters giảm do thiếu domain work.

---

# 6. Acceptance trước Phase 48F

Bắt buộc:

```text
exact discrete lifecycle parity
numeric accounting atol <= 1e-12
full report parity
score không materialize audit rows
buffers/caches bounded
100-run RSS plateau
no explicit Rust fallback
CPython wheel matrix pass
```

Performance:

```text
không hard speedup ratio
không regression >10–15% không giải thích được
R3/R4 phải giảm allocation/copy counters
explicit Rust vẫn là native fast path
auto vẫn Python cho 1.0.7
```

---

# 7. Không làm trong Phase 48E.1

```text
không đổi public endpoint
không đổi command timing
không đổi fill/margin/liquidation formulas
không bật auto=Rust
không viết native strategy DSL
không unsafe zero-copy NumPy lifetime
không full order-arena/index rewrite
không thêm portfolio/options Rust scope
```

Những việc này chỉ được mở thành phase mới sau release.

---

# 8. Definition of Done

Phase 48E.1 hoàn thành khi agent chứng minh:

- R3 bỏ allocation thật trong score, không chỉ bỏ payload trả về;
- R4 dùng reusable SoA, không còn nested per-row vectors ở hot path;
- internal Rust types được compact nhưng external ABI không đổi;
- `command_report`, `order_report`, `fills_report` có semantics riêng và đủ;
- Python/Rust/oracle parity giữ nguyên;
- compaction/reset giữ relationships và priority;
- RSS plateau;
- native wheels 3.11–3.13 clean-install và chạy full contract;
- không còn blocker native/report nào phải sửa trong Phase 48F.

Phase 48F sau đó chỉ xử lý:

```text
artifact build/install
TestPyPI RC
release workflow
security/package inspection
final handoff
```
