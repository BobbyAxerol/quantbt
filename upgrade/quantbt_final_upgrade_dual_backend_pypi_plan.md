# QuantBT Final Upgrade Plan — Correctness, RSS, Dual Python/Rust Backend & PyPI Release

## 1. Kết luận hiện trạng

Branch:

```text
feat/quantbt-engine-packaging
```

đã đạt nhiều phần quan trọng:

- `quantbt-engine` dùng `src/quantbt`;
- wheel và sdist workflow đã có;
- Python 3.11–3.13 được test trong release workflow;
- clean wheel/sdist install đã được đưa vào workflow;
- PyPI Trusted Publishing/OIDC đã được thiết kế;
- Python Native Event có scalar score path và conditional artifact retention;
- Rust đã có `PreparedMarketCore`, full-tape score/audit và sparse chunk scaffold;
- Rust batched path đã nhanh hơn đáng kể trên benchmark hiện tại;
- endpoint/import public vẫn được giữ.

Tuy nhiên chưa nên coi toàn bộ branch là release-ready cho dual backend.

Hai blocker kỹ thuật lớn nhất:

```text
1. Benchmark Rust và Python chưa cùng artifact contract.
2. Peak RSS đang bị chi phối mạnh bởi Python import/package baseline,
   không chỉ bởi Native Event session.
```

Quyết định đề xuất:

```text
quantbt-engine core:
    hoàn thiện và publish độc lập

Python backend:
    full-featured, reactive, mặc định và làm canonical implementation

Rust backend:
    giữ dual backend nhưng explicit/capability-gated
    chỉ dùng cho batched explicit-order tape trong scope đã certified

auto:
    tiếp tục chọn Python trong release đầu

replay_certified:
    oracle bắt buộc cho candidate/audit certification
```

---

# 2. Correctness phải khóa trước performance

## 2.1. Python phải đúng trước khi dùng làm reference

Không chứng nhận Rust chỉ bằng cách khớp Python nếu Python chưa được chứng nhận.

Chuỗi oracle:

```text
domain specification/golden invariants
        ↓
replay_certified
        ↓
Python optimized single-pass
        ↓
Rust batched
```

Python chỉ trở thành reference performance sau khi pass:

- golden lifecycle cases;
- quantity constraints;
- fee/slippage;
- margin sequencing;
- funding;
- liquidation priority;
- effective-next-bar semantics;
- same-bar command ordering;
- parent/OCO/TIF nếu thuộc capability được quảng bá.

## 2.2. Một full parity helper duy nhất

Tạo/chuẩn hóa:

```python
assert_native_event_full_parity(
    candidate,
    oracle,
    *,
    numeric_atol=1e-12,
)
```

Phải so:

```text
command effective bar
command sequence
accepted/rejected
reject reason
order status transition
fill bar
fill symbol/side/qty/price/fee
position path
equity path
fee path
funding path
turnover path
initial/maintenance margin
parent activation
OCO cancellation
expiry
liquidation state/bar/reason
final state
```

Discrete fields phải exact.

Numeric ưu tiên:

```python
np.testing.assert_array_equal(...)
```

Chỉ dùng:

```python
np.testing.assert_allclose(..., rtol=0.0, atol=1e-12)
```

khi thứ tự floating-point khác nhưng không làm đổi bất kỳ quyết định discrete nào.

Không dùng chỉ:

```text
final_equity + fill_count
```

để gọi là full parity.

## 2.3. Capability matrix là source of truth

Rust R2 hiện chỉ được quảng bá đúng scope đã test.

Tạo file hoặc constant canonical:

```json
{
  "single_symbol": true,
  "market": true,
  "limit": true,
  "stop_market": true,
  "stop_limit": true,
  "place": true,
  "cancel": true,
  "amend": true,
  "replace": true,
  "reduce_only": true,
  "quantity_constraints": true,
  "gtc": true,
  "gtd": false,
  "ioc": false,
  "fok": false,
  "parent_child": false,
  "oco": false,
  "funding": false,
  "liquidation": false,
  "multi_symbol": false
}
```

Python selector, Rust `capabilities()` và docs phải sinh hoặc đọc từ cùng một source.

Không để ba capability lists khác nhau.

Explicit Rust request với unsupported feature phải:

```text
raise clear NotImplementedError/CapabilityError
```

Không silent fallback và không silently degrade semantics.

---

# 3. Sửa benchmark trước khi tin speedup

## 3.1. Vấn đề benchmark hiện tại

Rust chạy:

```python
runner.run_tape_score(compiled)
```

và trả scalar score result.

Python chạy:

```python
backend.run_order_commands(
    ...,
    report_level="minimal",
)
```

sau đó đọc:

```python
last.equity.iloc[-1]
```

Python path vẫn dựng result/pandas nhiều hơn Rust.

Vì vậy speedup hiện tại chứng minh:

```text
Rust batched scalar
nhanh hơn
Python minimal public result
```

nhưng chưa chứng minh:

```text
Rust batched scalar
nhanh hơn
Python zero-object scalar score
```

## 3.2. Baseline công bằng bắt buộc

Thêm Python API nội bộ tương đương:

```python
backend.run_compiled_tape_score(
    index,
    compiled_commands,
    market_arrays=prepared_market,
)
```

Nó phải:

- không pandas;
- không `BacktestResultV2`;
- không full ledgers;
- không command report;
- chỉ trả cùng scalar fields như Rust.

Hai path cùng trả:

```text
final_equity
final_position
total_fee
total_turnover
fill_count
event_count
rejected_count
canceled_count
max_initial_margin
max_maintenance_margin
```

Benchmark lại:

```text
Python warmed scalar score
vs
Rust release scalar score
```

## 3.3. Tách certification và timing

Trước timing:

```text
run full audit parity once
store parity fingerprint
```

Timing:

```text
score-only path
không audit materialization
```

Benchmark JSON phải chứa:

```text
oracle_fingerprint
python_fingerprint
rust_fingerprint
full_parity_passed
```

Không tự kết luận parity chỉ từ final equity/fill count.

---

# 4. Đo RSS đúng cách

## 4.1. Total process RSS hiện chưa phản ánh riêng engine

Mỗi child process cần đo các checkpoint:

```text
rss_interpreter
rss_after_import_quantbt
rss_after_market_prepare
rss_after_command_compile
rss_after_runner_prepare
peak_rss_during_run
rss_after_run
```

Tính:

```text
import_baseline_rss =
    rss_after_import_quantbt - rss_interpreter

prepared_incremental_rss =
    rss_after_runner_prepare - rss_after_import_quantbt

execution_incremental_peak =
    peak_rss_during_run - rss_after_runner_prepare
```

Release gate nên gồm cả:

```text
absolute peak RSS
incremental prepared RSS
incremental execution RSS
```

Không chỉ dùng phần trăm total-process RSS.

## 4.2. Process isolation

Mỗi case chạy process riêng:

```text
python scalar score
rust scalar score
replay-certified audit
```

Không import/prepare hai backend trong cùng process.

Không dùng `tracemalloc` làm RSS gate chính.

Dùng:

```text
/proc/<pid>/status → VmHWM
resource.getrusage(...).ru_maxrss
memray --native
```

`tracemalloc` chỉ dùng để tìm Python-reference leak.

---

# 5. P0 RSS optimization — sửa import graph

## 5.1. Vấn đề

`quantbt/__init__.py` đang eager-import gần như toàn bộ package:

```text
walkforward
optimization/Optuna
all backends
Nautilus adapter
options
metrics
visualization
reporting
```

Nó cũng import:

```python
from .viz import quick_plot, tearsheet, apply_theme
```

Trong khi `viz` import plots/themes ngay.

`matplotlib` và `seaborn` lại đang nằm trong core dependencies.

Hệ quả:

```text
import quantbt
```

có thể kéo nhiều module/dependency nặng trước khi Native Event chạy.

Điều này làm cả Python và Rust child process có RSS floor cao.

## 5.2. Giữ public names bằng lazy imports

Không xóa các public names hiện tại.

Refactor `src/quantbt/__init__.py`:

```python
from importlib import import_module
from typing import TYPE_CHECKING

from .endpoint import QuantBTEndpoint, EndpointConfig

_LAZY_EXPORTS = {
    "OptunaOptimizer": ("quantbt.optimization", "OptunaOptimizer"),
    "NautilusBacktestEngine": (
        "quantbt.adapters.nautilus",
        "NautilusBacktestEngine",
    ),
    "quick_plot": ("quantbt.viz", "quick_plot"),
    "tearsheet": ("quantbt.viz", "tearsheet"),
    # toàn bộ public exports không thuộc minimal core
}

def __getattr__(name: str):
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

if TYPE_CHECKING:
    from .optimization import OptunaOptimizer
```

Giữ eager imports tối thiểu cho:

```text
QuantBTEndpoint
EndpointConfig
các schema/result/core types thật sự luôn cần
```

## 5.3. Tests bắt buộc

```text
test_import_quantbt_does_not_import_matplotlib
test_import_quantbt_does_not_import_seaborn
test_import_quantbt_does_not_import_optuna
test_import_quantbt_does_not_import_nautilus
test_all_public_exports_remain_accessible
test_from_quantbt_import_quantbt_endpoint
test_lazy_export_identity_matches_direct_import
test_lazy_import_thread_safety_smoke
```

Đo:

```bash
python -X importtime -c "import quantbt"
```

và fresh-process RSS trước/sau refactor.

## 5.4. Dependency metadata

Sau khi lazy import pass:

```toml
dependencies = [
    "numpy...",
    "pandas...",
    "numba...",
]

[project.optional-dependencies]
viz = [
    "matplotlib...",
    "seaborn...",
]
```

Không để matplotlib/seaborn vừa là core dependency vừa là extra.

Tương tự:

```text
Optuna → optimization extra
Nautilus → validation extra
QuantStats → reports extra
```

Core import phải hoạt động khi các extras không được cài.

Đây có thể là cải tiến RSS lớn nhất còn lại trong toàn process.

---

# 6. P0 RSS optimization — không giữ hai market copies

## 6.1. Vấn đề

`PreparedMarketCore` hiện copy NumPy arrays sang Rust `Vec` bằng `.to_vec()`.

Benchmark fixture đồng thời giữ:

```text
index
closes/highs/lows
Python market arrays
commands
compiled command object
Rust runner/PreparedMarketCore
```

Do đó Rust process vẫn giữ Python market representation cùng Rust-owned market.

## 6.2. Tách fixture theo backend

Python child:

```text
PreparedPythonMarket
compiled Python tape
Python scalar runner
```

Rust child:

```text
temporary NumPy input
→ PreparedMarketCore copy một lần
→ del DataFrame/Series/Python market arrays
→ gc.collect()
→ bắt đầu RSS checkpoint/timing
```

Không trả một `_fixture()` chứa cả Python và Rust prepared objects.

## 6.3. Production ownership

Tạo hai explicit prepared containers:

```text
PreparedPythonNativeEventMarket
PreparedRustNativeEventMarket
```

Không tạo cả hai trong `auto`.

Rust runner chỉ giữ:

```text
DatetimeIndex hoặc timestamps tối thiểu cho report adapter
symbols metadata
PreparedMarketCore
compact command arrays
```

Không giữ DataFrame và duplicated OHLC arrays.

## 6.4. Rust market storage

Sau copy:

```rust
Box<[f64]>
```

hoặc:

```rust
Arc<[f64]>
```

phù hợp hơn `Vec<f64>` nếu arrays immutable và không cần capacity.

Lợi ích:

```text
không giữ spare capacity
ownership immutable rõ
share giữa sessions
```

Không dùng unsafe borrow từ NumPy trong giai đoạn này; one-time copy rồi release Python input an toàn hơn cho correctness.

---

# 7. P1 Rust R2 optimization — order table

## 7.1. Vấn đề hiện tại

Rust session còn:

```text
Vec<ActiveOrder>
iter().position()
iter_mut().find()
Vec.remove(position)
drain toàn active orders
rebuild active_orders Vec<Vec<f64>> mỗi bar
allocate fills/events Vec mới mỗi step
```

Đây là O(active orders) scan và tạo object/heap churn.

## 7.2. Cấu trúc thay thế

```rust
struct OrderTable {
    slots: Vec<OrderSlot>,
    id_to_slot: HashMap<i64, usize>,
    active_sequence: Vec<usize>,
    free_slots: Vec<usize>,
}
```

`OrderSlot` chỉ giữ primitives.

PLACE:

```text
reuse free slot hoặc push
id_to_slot.insert
active_sequence.push
```

CANCEL/AMEND/REPLACE:

```text
O(1) lookup qua id_to_slot
```

Terminal:

```text
mark inactive
remove id mapping
không Vec.remove làm shift
```

Cuối bar/chunk:

```text
compact active_sequence nếu tombstone ratio vượt threshold
```

Giữ priority bằng `active_sequence`, không swap-remove.

## 7.3. Alias resolution

Replacement alias chain hiện giới hạn 64 lookup.

Có thể path-compress:

```text
old ID → final active ID
```

sau resolve để giảm repeated lookup.

Phải test cycle/replacement chain chính xác.

---

# 8. P1 Rust R2 optimization — reusable SoA buffers

## 8.1. Step path cũ

Per-bar scaffold còn tạo:

```text
Vec<Vec<f64>> fills
Vec<Vec<i64>> events
Vec<Vec<f64>> active_orders
PyDict
```

Giữ path này chỉ cho debug compatibility.

Không dùng làm performance backend.

## 8.2. Batched score

`run_tape_score()` không cần tạo:

```text
equity Vec
positions Vec
fees Vec
turnover Vec
fill/event ledgers
```

Chỉ giữ scalars.

Thay `PyDict` bằng typed PyClass:

```rust
#[pyclass(frozen)]
struct BatchedScoreResultCore {
    #[pyo3(get)]
    final_equity: f64,
    #[pyo3(get)]
    final_position: f64,
    #[pyo3(get)]
    total_fee: f64,
    #[pyo3(get)]
    total_turnover: f64,
    #[pyo3(get)]
    fill_count: u64,
    #[pyo3(get)]
    event_count: u64,
    // ...
}
```

Một `PyDict` cuối run không phải bottleneck lớn, nhưng typed result giảm lookup, allocation và contract ambiguity.

## 8.3. Audit path

Dùng SoA Rust vectors:

```text
fill_bar
fill_order_id
fill_side
fill_qty
fill_price
fill_fee

event_bar
event_kind
event_status
event_order_id
event_target_id
```

Convert mỗi vector một lần thành NumPy.

Không nested lists.

## 8.4. Reuse buffers

Session giữ reusable capacity:

```rust
struct AuditBuffers {
    fill_bar: Vec<i64>,
    // ...
}
```

Mỗi run:

```rust
clear()
```

không free capacity.

Chỉ áp dụng session reuse sau khi có:

```text
reset parity test
100 repeated-run memory plateau test
```

Fresh session vẫn là default correctness path cho tới khi reset được chứng nhận.

---

# 9. P1 command tape memory

## 9.1. Không giữ ba representations

Tránh đồng thời giữ:

```text
list[OrderCommand]
CompiledOrderCommandArrays object
Rust numeric arrays/cache
```

Sau compile cho score, giữ:

```text
command_ptr
command_codes
command_values
command_expiry
minimal ID/metadata side table nếu audit cần
```

Cho phép:

```python
commands = None
compiled_source = None
gc.collect()
```

trước benchmark/optimization run.

## 9.2. Cache policy

Cache bằng:

```text
stable tape fingerprint
```

Không cache cả original command objects.

Dùng LRU bounded theo bytes, không chỉ số entries.

Expose:

```python
runner.clear_tape_cache()
```

để service/optimizer kiểm soát RSS.

---

# 10. Python backend vẫn cần tối ưu

Python backend là full-featured reactive backend nên phải tiếp tục được giữ tốt.

## 10.1. Primitive active state

Internal `_ReactiveOrderState` hiện còn giữ full `OrderCommand`.

Trong score mode, chuyển dần sang:

```text
primitive order state
+
optional metadata side table
```

Không đổi public command/event types.

## 10.2. Lazy context fields

`NativeStrategyContext` nên materialize theo requirements:

```text
active_orders
order_events
fills
margin
positions
```

Default đầy đủ để giữ compatibility.

Strategy khai báo không cần field nào thì không tạo field đó.

## 10.3. Scalar static-tape Python runner

Đây vừa là:

```text
fair Rust baseline
```

vừa là:

```text
fast fallback khi Rust wheel không có
```

Nên dùng Numba/replay kernel nếu domain scope tương thích; nếu không, dùng optimized Python session không pandas.

---

# 11. Dual backend contract nên chốt như thế nào

## 11.1. Có nên giữ Rust?

Có.

Rust batched path đã chứng minh có tiềm năng rõ ràng cho:

```text
precompiled/static explicit-order tapes
high order churn
prepared repeated replays
```

Nhưng không thay Python reactive backend.

## 11.2. Public selection

Đề xuất internal/public optional config:

```text
python
rust
auto
replay_certified
```

### `python`

- full reactive strategy callback;
- full advertised Native Event feature set;
- default trong release đầu;
- Python scalar static-tape path khi phù hợp.

### `rust`

- chỉ batched tape capability đã certified;
- fail-fast nếu unsupported;
- không silent fallback;
- trả cùng result schema ở adapter boundary.

### `auto`

Release đầu:

```text
always Python
```

Sau certification:

```text
static supported tape + native installed → Rust
reactive callback/unsupported feature    → Python
```

### `replay_certified`

- oracle/audit;
- candidate cuối;
- regression certification.

## 11.3. Không dùng Rust per-bar adapter làm performance route

Giữ `ReactiveSessionCore.step()` cho:

```text
debug
R2 correctness tests
transition development
```

Không quảng bá nó là fast backend.

---

# 12. Gate mới cho Rust

Sau khi sửa benchmark công bằng và import graph:

```text
full lifecycle/accounting parity = 100%
low-churn speedup                 >= 1.50x
high-churn speedup                >= 2.00x
incremental prepared RSS          giảm >= 40%
incremental execution peak RSS    giảm >= 40%
absolute peak RSS                 dưới budget đã định
100-run RSS                       plateau
```

Không bắt buộc total-process RSS giảm 40% nếu phần lớn là interpreter/shared imports, nhưng phải:

- giảm mạnh incremental engine memory;
- hạ absolute peak bằng lazy import;
- không tăng theo repeated trials.

Ghi cả ba chỉ số, không thay gate bằng một con số dễ pass.

---

# 13. PyPI core readiness

## 13.1. Phần đã sẵn sàng về code

Core workflow hiện đã có:

- trigger khi GitHub Release được publish;
- Python 3.11–3.13 test;
- version check;
- `uv build`;
- `twine check`;
- clean wheel install;
- clean sdist install;
- artifact upload;
- OIDC `id-token: write`;
- official PyPA publish action.

Do đó release automation của core đã gần hoàn chỉnh.

## 13.2. Việc còn phải làm trước publish

### P0

1. Đưa `src/quantbt` thành source duy nhất; xóa root mirror.
2. Chạy full test sau khi xóa mirror.
3. Lazy import và dependency split để core wheel không bắt buộc visualization.
4. Kiểm `__version__ == pyproject version == Git tag`.
5. Thêm/hoàn thiện:
   - `CHANGELOG.md`;
   - Documentation và Changelog trong `[project.urls]`;
   - classifiers Python 3.11, 3.12, 3.13;
   - release notes cho `0.1.0`.
6. Build/install wheel và sdist từ clean checkout.
7. Test `pool_alpha` với:
   - editable install;
   - built wheel.

### Recommended

- kiểm wheel contents;
- chạy `pip check`;
- chạy import smoke khi chỉ cài core dependencies;
- chạy smoke cho từng extra riêng;
- không dùng `--all-extras` làm bằng chứng rằng core dependencies đủ.

---

# 14. PyPI account và Trusted Publishing

## 14.1. Không cần API token cho release chính

Dùng PyPI Trusted Publishing/OIDC.

Trên PyPI account:

```text
Account settings
→ Publishing
→ Add a new pending publisher
```

Khai báo core:

```text
Project:      quantbt-engine
Owner:        BobbyAxerol
Repository:   quantbt
Workflow:     publish.yml
Environment:  pypi
```

Tên workflow và environment phải khớp chính xác.

## 14.2. GitHub environment

Repository:

```text
Settings
→ Environments
→ New environment
→ pypi
```

Nên bật:

- required reviewer;
- chỉ release từ protected `main`;
- tag protection `v*`.

Workflow hiện đã dùng:

```yaml
environment:
  name: pypi

permissions:
  id-token: write
```

## 14.3. TestPyPI

Trước production:

```text
quantbt-engine 0.1.0rc1
```

Tạo Trusted Publisher tương tự trên TestPyPI với environment:

```text
testpypi
```

Cài smoke:

```bash
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  quantbt-engine==0.1.0rc1
```

## 14.4. API token chỉ là fallback

Chỉ dùng cho:

```text
manual debugging
TestPyPI fallback
emergency publish
```

Token:

```text
project-scoped
username = __token__
password = pypi-...
```

Không commit token.

Không cần tạo `PYPI_API_TOKEN` GitHub secret nếu OIDC hoạt động.

Nếu từng tạo fallback token:

```text
revoke sau khi OIDC publish thành công
```

---

# 15. Native package chưa sẵn sàng để publish

## 15.1. Thiếu release workflow production

`native-r0.yml` hiện chỉ:

- Python 3.12;
- local `maturin build`;
- combined smoke;
- parity smoke;
- RSS smoke.

Nó chưa phải production wheel workflow.

Cần:

```text
CPython 3.11
CPython 3.12
CPython 3.13
manylinux2014 x86_64
artifact install test
full parity certification
release publish job
```

Dùng `PyO3/maturin-action` với manylinux 2014 hoặc tương đương.

## 15.2. Native metadata

`rust/native_event/pyproject.toml` còn tối giản.

Bổ sung:

```toml
[project]
name = "quantbt-native"
version = "0.1.0"
description = "Optional batched Rust accelerator for quantbt-engine Native Event"
readme = "README.md"
requires-python = ">=3.11,<3.14"
license = "MIT"
authors = [{ name = "BobbyAxerol" }]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Programming Language :: Python :: 3",
    "Programming Language :: Rust",
]
```

Thêm:

```text
rust/native_event/README.md
LICENSE inclusion
Cargo.lock
native capability documentation
```

`publish = false` trong Cargo chỉ ngăn publish lên crates.io; không ngăn Maturin/PyPI wheel.

## 15.3. Versioning

Không trộn:

```text
distribution version
native API version
```

Đề xuất:

```text
quantbt-engine distribution: 0.1.0
quantbt-native distribution: 0.1.0
NATIVE_API_VERSION:          0.3
```

Compatibility:

```toml
native = [
    "quantbt-native>=0.1,<0.2",
]
```

## 15.4. Release ordering

Khi native đủ gate:

```text
1. publish quantbt-native
2. xác minh pip install quantbt-native
3. cập nhật quantbt-engine[native]
4. publish quantbt-engine patch/minor release
```

Không thêm non-empty `native` extra trước khi native distribution tồn tại.

Sau khi extra có dependency native, core CI không nên dùng `uv sync --all-extras` trước khi local native wheel được build.

Tách:

```text
core CI → exclude native
native CI → build local core + native wheels rồi install cùng nhau
```

---

# 16. File/patch order cho lần upgrade cuối

## Patch F1 — Correctness certification

- unified full parity helper;
- Python vs replay full matrix;
- Rust vs replay R2 matrix;
- seeded randomized differential tests;
- capability matrix canonical;
- bỏ mọi required `xfail`.

## Patch F2 — Fair benchmark

- Python scalar tape score;
- separate backend fixtures;
- full fingerprint before timing;
- staged RSS checkpoints;
- accepted baseline JSON mới.

## Patch F3 — Import/RSS floor

- lazy `quantbt.__init__`;
- move viz dependencies out of core;
- optional imports remain compatible;
- import-time/RSS tests.

## Patch F4 — Market/tape ownership

- Rust-only prepared fixture;
- release Python market inputs after Rust prepare;
- `Arc<[T]>`/`Box<[T]>`;
- bounded tape cache;
- no duplicate command representations.

## Patch F5 — Rust R2 hot state

- order slot table;
- O(1) ID lookup;
- tombstone compaction;
- reusable SoA buffers;
- typed score result.

## Patch F6 — Python hot state

- primitive score order state;
- lazy context payloads;
- no full command object retention when not needed.

## Patch F7 — Re-run release gate

- same artifacts;
- fresh processes;
- minimum five runs;
- low/high churn;
- 100 repeated runs;
- large-data RSS scenario.

## Patch F8 — Core PyPI finalization

- remove root mirror;
- metadata/docs/changelog;
- TestPyPI RC;
- PyPI pending Trusted Publisher;
- protected GitHub environment;
- core `0.1.0` release.

## Patch F9 — Native release decision

Nếu gate pass:

- manylinux cp311–cp313;
- native metadata/docs;
- publish `quantbt-native 0.1.0`;
- add `quantbt-engine[native]`;
- keep `auto=python` for first native release.

Nếu gate fail:

- keep Rust explicit experimental;
- publish core only;
- no native extra.

---

# 17. Chốt quyết định

## Core PyPI

```text
Chưa nên bấm publish ngay.
```

Nhưng core đã rất gần release-ready.

Cần hoàn tất:

```text
single source tree
lazy dependency/import cleanup
version/docs/changelog
TestPyPI/OIDC account setup
final clean install and pool_alpha smoke
```

Sau đó có thể public `quantbt-engine 0.1.0` mà không cần chờ Rust.

## Dual Python/Rust

```text
Nên giữ và hoàn thiện dual backend.
```

Nhưng contract phải là:

```text
Python:
    full reactive/default/canonical

Rust:
    batched explicit-order R2 only
    explicit opt-in
    capability-gated
    no silent fallback

Auto:
    Python trong release đầu

Replay:
    certification oracle
```

Rust chỉ được quảng bá là faster backend sau khi:

- benchmark được sửa thành apples-to-apples;
- full parity vượt qua;
- incremental và absolute RSS được đo đúng;
- native wheels được build portable.

## Mục tiêu RSS thực tế

Ba cải tiến có khả năng đem lại nhiều nhất:

```text
1. lazy package imports + bỏ visualization khỏi core dependency
2. không giữ NumPy market và Rust market cùng lúc
3. compact Rust/Python active-order state và bounded command caches
```

Allocator tuning chỉ làm sau ba bước trên.

Không cần nâng R4/R5 trong scope này.
