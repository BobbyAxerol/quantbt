# QuantBT Engine — Packaging, PyPI, Native Event & PyO3 Final Plan

## 1. Mục tiêu và nguyên tắc bắt buộc

### Mục tiêu

Chuẩn hóa QuantBT thành package có thể:

- cài độc lập;
- dùng trong `pool_alpha` dưới dạng dependency;
- publish lên PyPI;
- giữ nguyên API/import hiện tại;
- tối ưu Native Event về tốc độ, RSS và throughput;
- bổ sung Rust/PyO3 như optional accelerator;
- giữ Python/Numba làm fallback và accounting oracle.

### Nguyên tắc không được phá

```text
Không đổi import hiện tại:
from quantbt import QuantBTEndpoint

Không đổi endpoint hiện tại.

Không buộc alpha cũ migrate.

Không đổi domain semantics để lấy tốc độ.

Không merge tối ưu nếu parity fail.

Không viết lại source khi chuyển package layout nếu có thể copy/move an toàn.
```

Mọi thay đổi phải giữ:

```text
same inputs
→ same command timing
→ same lifecycle
→ same fills
→ same positions
→ same fees/funding/margin
→ same liquidation result
→ same final equity
```

---

# 2. Tên package và import

## PyPI distribution chính

```text
quantbt-engine
```

Cài:

```bash
pip install quantbt-engine
```

Import vẫn giữ nguyên:

```python
from quantbt import QuantBTEndpoint
```

PyPI distribution name và Python import name không bắt buộc giống nhau.

## Rust accelerator

```text
PyPI distribution: quantbt-native
Python module:      _quantbt_native
```

Cài riêng:

```bash
pip install quantbt-native
```

Hoặc qua extra của package chính:

```bash
pip install "quantbt-engine[native]"
```

Alpha không import `_quantbt_native`.

QuantBT tự phát hiện và dùng accelerator nội bộ:

```python
try:
    import _quantbt_native
except ImportError:
    _quantbt_native = None
```

---

# 3. Runtime architecture

## Khi chỉ cài `quantbt-engine`

```text
quantbt-engine
└── Native Event Python/Numba backend
```

QuantBT vẫn chạy đầy đủ như hiện tại.

## Khi cài thêm `quantbt-native`

```text
quantbt-engine
├── public Python API
├── strategy protocol
├── reporting/optimization
├── Python fallback
├── Numba replay-certified oracle
└── Rust/PyO3 single-pass accelerator
```

Người dùng vẫn gọi:

```python
from quantbt import QuantBTEndpoint

endpoint = QuantBTEndpoint.native_event_strategy(...)
result = endpoint.simulate(...)
```

Bên trong:

```python
if rust_backend_available_and_certified:
    use_rust_single_pass()
else:
    use_python_single_pass()
```

Result vẫn là public `BacktestResultV2`.

---

# 4. Backend selection

Internal config đề xuất:

```text
auto
python
rust
replay_certified
```

Semantics:

```text
auto:
    Rust có sẵn và certified → Rust
    không → Python fallback

python:
    ép dùng Python single-pass

rust:
    ép dùng Rust
    thiếu extension hoặc uncertified → raise rõ ràng

replay_certified:
    dùng canonical replay/accounting oracle
```

Ban đầu không cần public hóa endpoint parameter mới.

Có thể dùng environment variable cho development:

```bash
QUANTBT_NATIVE_BACKEND=auto
QUANTBT_NATIVE_BACKEND=python
QUANTBT_NATIVE_BACKEND=rust
QUANTBT_NATIVE_BACKEND=replay_certified
```

Không thay endpoint cũ.

---

# 5. Tooling

## Lựa chọn

```text
uv        → Python dependencies, environment, lockfile, commands
PEP 621   → project metadata trong pyproject.toml
Maturin   → build Rust/PyO3 wheels
Cargo     → Rust dependencies/build/tests
```

Không cần chuyển `pool_alpha` sang UV ngay.

Có thể dùng:

```text
pool_alpha → Poetry hiện tại
quantbt    → UV + Maturin
```

`pool_alpha` tiếp tục dùng QuantBT bằng editable/path dependency trong giai đoạn migration.

---

# 6. Cấu trúc repository mục tiêu

```text
quantbt/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── src/
│   └── quantbt/
│       ├── __init__.py
│       ├── endpoint.py
│       ├── engines.py
│       ├── backends/
│       ├── core/
│       ├── optimization/
│       ├── reporting/
│       ├── metrics/
│       ├── adapters/
│       ├── options/
│       ├── sizing/
│       ├── viz/
│       └── py.typed
├── tests/
├── benchmarks/
├── docs/
└── rust/
    └── native_event/
        ├── pyproject.toml
        ├── Cargo.toml
        └── src/
            └── lib.rs
```

---

# 7. Quy tắc migration sang `src/quantbt`

## Không viết lại code

Khi chuyển source hiện tại vào `src/quantbt`:

```text
ưu tiên copy nguyên file/thư mục
→ chạy import/test
→ verify parity
→ chỉ sửa path/import thật sự cần thiết
```

Không yêu cầu agent tái tạo source bằng tay.

## Quy trình an toàn

1. Tạo branch packaging riêng.
2. Tạo `src/quantbt`.
3. Copy nguyên:
   - `__init__.py`;
   - `endpoint.py`;
   - `engines.py`;
   - `backends/`;
   - `core/`;
   - `optimization/`;
   - các modules còn lại.
4. Giữ nguyên relative imports nếu đang đúng.
5. Không xóa source root ngay.
6. Cài editable package:
   ```bash
   uv sync --all-extras
   ```
7. Chạy:
   ```bash
   uv run pytest
   ```
8. Chạy smoke import từ ngoài repository root.
9. Chạy pool_alpha compatibility tests.
10. Chỉ xóa source cũ sau khi wheel install và parity pass.

## Không dùng compatibility shim lâu dài

Có thể giữ shim ngắn hạn ở root nếu cần migration:

```python
from quantbt import *
```

Nhưng final package phải import từ `src/quantbt`, tránh tồn tại hai source of truth.

---

# 8. `pyproject.toml` package chính

Ví dụ:

```toml
[build-system]
requires = ["uv_build>=0.8,<1"]
build-backend = "uv_build"

[project]
name = "quantbt-engine"
version = "0.1.0"
description = "High-performance quantitative backtesting engine"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [
    { name = "BobbyAxerol" }
]

dependencies = [
    "numpy>=1.26",
    "pandas>=2.1",
    "numba>=0.59",
]

[project.optional-dependencies]
optimization = [
    "optuna>=4",
]

reports = [
    "quantstats",
]

viz = [
    "matplotlib",
    "seaborn",
]

validation = [
    "nautilus-trader",
]

native = [
    "quantbt-native>=0.3,<0.4",
]

all = [
    "optuna>=4",
    "quantstats",
    "matplotlib",
    "seaborn",
    "nautilus-trader",
    "quantbt-native>=0.3,<0.4",
]

[dependency-groups]
dev = [
    "pytest",
    "pytest-cov",
    "hypothesis",
    "ruff",
    "mypy",
    "build",
    "twine",
    "maturin>=1.9,<2",
]

[tool.uv]
package = true

[tool.uv.build-backend]
module-name = "quantbt"
module-root = "src"
```

Exact dependency versions phải lấy từ repo hiện tại và CI, không tự nâng major ngoài scope packaging.

---

# 9. Rust/PyO3 subpackage

## `rust/native_event/Cargo.toml`

```toml
[package]
name = "quantbt-native"
version = "0.3.0"
edition = "2024"

[lib]
name = "_quantbt_native"
crate-type = ["cdylib"]

[dependencies]
pyo3 = {
    version = "0.29",
    features = ["extension-module"]
}

numpy = "0.29"
```

## `rust/native_event/pyproject.toml`

```toml
[build-system]
requires = ["maturin>=1.9,<2"]
build-backend = "maturin"

[project]
name = "quantbt-native"
version = "0.3.0"
requires-python = ">=3.11"

[tool.maturin]
bindings = "pyo3"
module-name = "_quantbt_native"
manifest-path = "Cargo.toml"
```

Khi develop:

```bash
rustup default stable
uv tool install maturin
cd rust/native_event
maturin develop --release
```

Khi cài prebuilt wheel từ PyPI, user không cần Rust/Cargo.

---

# 10. Phạm vi Rust/PyO3

## Rust chỉ dùng ở nơi có giá trị

Rust/PyO3 không thay toàn bộ QuantBT.

Rust giữ:

- mutable Native Event runtime state;
- active order table;
- order ID lookup;
- parent/OCO/expiry indexes;
- matching hot path;
- fee/slippage;
- position/equity accounting;
- funding;
- margin/liquidation;
- compact command/fill/event buffers.

Python giữ:

- public endpoint;
- strategy callbacks;
- configs;
- data preparation;
- reporting;
- optimization;
- audit;
- Python fallback;
- replay-certified oracle.

## Boundary đúng

Một call Rust mỗi bar:

```python
fills, events, state = session.process_bar(
    bar_index,
    market_row,
    command_buffer,
)
```

Không gọi Rust riêng cho từng:

- PLACE;
- CANCEL;
- fee calculation;
- margin calculation;
- fill.

Command/fill data nên dùng contiguous numeric buffers, không dùng nhiều dict/list/string qua PyO3 boundary.

---

# 11. Native Event optimization trước Rust

Trước POC Rust, sửa các vấn đề low-risk trong Python:

1. Pop consumed queues:
   ```python
   scheduled.pop(bar, ())
   fills_by_bar.pop(bar, ())
   events_by_bar.pop(bar, ())
   ```

2. Tách active order state khỏi terminal history.

3. Score mode không giữ terminal Python objects.

4. Cache:
   - symbols tuple;
   - symbol index;
   - sizing helper;
   - margin trong bar.

5. Dùng read-only OHLCV row views trong prepared score.

6. Không materialize pandas trong `score`.

7. Bỏ repeated `tuple(self.pending)` allocations.

8. Chỉ thêm indexes có lợi rõ:
   - `active_by_id`;
   - `children_by_parent`;
   - `orders_by_oco`;
   - expiry bucket/heap.

9. Score mode chỉ giữ artifacts objective cần.

10. Selected candidate mới rerun audit/full.

Sau bước này phải profile lại để xác định phần CPU/RSS còn lại trước khi viết Rust lớn.

---

# 12. PyO3 POC

## Scope nhỏ ban đầu

Hỗ trợ:

```text
single symbol
PLACE
CANCEL
market
limit
GTC
fee
slippage
position/equity
```

Không làm ngay:

```text
parent/OCO
GTD/IOC/FOK
multi-symbol
funding
margin/liquidation
```

## Mục tiêu POC

```text
same commands
same fills
same positions
same accounting
```

Benchmark gate:

```text
median speedup       >= 1.20x
high-churn speedup   >= 1.50x
peak RSS reduction   >= 30%
parity               = 100%
```

Không đạt gate thì dừng Rust và giữ Python/Numba.

---

# 13. Mở rộng Rust sau POC

Thứ tự:

1. Stop orders.
2. Reduce-only.
3. Quantity constraints.
4. Parent-child.
5. OCO.
6. GTD.
7. IOC/FOK.
8. Funding.
9. Margin/liquidation.
10. Multi-symbol.

Mỗi bước phải có differential parity test với oracle trước khi chuyển bước sau.

---

# 14. Correctness và parity

## Oracle

```text
replay_certified = canonical domain/accounting oracle
```

Rust `single_pass` không tự trở thành source of truth.

## Lifecycle parity

So sánh exact:

```text
effective bar
order state
reject reason
fill bar
fill side
fill qty
fill price
parent activation
OCO cancellation
expiry
```

## Position/accounting parity

So sánh:

```text
positions
equity
returns
fees
slippage
funding
turnover
initial margin
maintenance margin
liquidation state/bar
```

Discrete decisions phải exact:

```text
fill/reject
order priority
liquidation
position quantity
```

Floating point:

```python
np.testing.assert_array_equal(...)
```

ưu tiên trước.

Chỉ dùng:

```python
np.testing.assert_allclose(
    ...,
    rtol=1e-12,
    atol=1e-12,
)
```

khi thứ tự floating point khác nhưng không ảnh hưởng domain decision.

## Randomized differential tests

Sinh command tapes seeded:

```text
Python single-pass
Rust single-pass
Numba replay-certified
```

và so toàn bộ lifecycle/accounting.

## Memory tests

Chạy lặp ít nhất 100 prepared score runs:

- RSS plateau sau warm-up;
- không giữ terminal order objects;
- queues rỗng sau run;
- evaluator không giữ strategy/result cũ;
- không tăng dictionary/list vô hạn.

---

# 15. Performance benchmark

Đo riêng:

```text
prepare market
strategy callback
command conversion
matching
accounting
result materialization
peak RSS
post-run RSS
```

Scenarios:

1. 100k bars, ít orders.
2. 100k bars, order churn cao.
3. Parent/OCO-heavy.
4. Funding/margin/liquidation stress.
5. Multi-symbol.
6. 100 prepared optimization trials liên tiếp.

Merge chỉ khi:

```text
parity pass
RSS không tăng tuyến tính
score throughput tăng
audit không regression quá mức cho phép
public endpoint không đổi
```

---

# 16. Versioning

Một version source of truth hoặc automated sync:

```text
pyproject.toml package chính
Cargo.toml native package
Git tag
```

Release stages:

```text
0.1.x → package hóa Python
0.2.x → Native Event Python/RSS optimization
0.3.x → PyO3 experimental accelerator
1.0.0 → API/domain contracts stable
```

Compatibility:

```toml
native = [
    "quantbt-native>=0.3,<0.4"
]
```

Major/minor phải tương thích; patch không nhất thiết giống tuyệt đối.

Workflow phải fail nếu version/tag không hợp lệ.

---

# 17. CI

## Python matrix

```text
Python 3.11
Python 3.12
Python 3.13
```

Jobs:

```text
uv sync
ruff
mypy
pytest
wheel build
clean wheel install
public import smoke
pool_alpha compatibility smoke
```

Không dùng `PYTHONPATH` để giả lập package.

## Rust jobs

```text
cargo fmt --check
cargo clippy -- -D warnings
cargo test
maturin build --release
install native wheel
Python/Rust parity suite
RSS benchmark smoke
```

## Release gate

```text
tests
parity
wheel install
version check
artifact integrity
```

pass hết mới publish.

---

# 18. PyPI release qua GitHub Actions

## Cơ chế chính: Trusted Publishing/OIDC

Không dùng token dài hạn làm release path chính.

PyPI:

```text
Account settings
→ Publishing
→ Add a new pending publisher
```

Package chính:

```text
Project:       quantbt-engine
Owner:         BobbyAxerol
Repository:    quantbt
Workflow:      publish.yml
Environment:   pypi
```

Native package:

```text
Project:       quantbt-native
Owner:         BobbyAxerol
Repository:    quantbt
Workflow:      publish-native.yml
Environment:   pypi
```

## Trigger

Chỉ publish khi GitHub Release được publish:

```yaml
on:
  release:
    types: [published]
```

Không publish khi push thường vào `main`.

---

# 19. GitHub Actions publish package chính

`.github/workflows/publish.yml`:

```yaml
name: Publish quantbt-engine

on:
  release:
    types: [published]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest

    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]

    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python-version }}

      - run: uv sync --all-extras --dev
      - run: uv run pytest
      - run: uv build

  build:
    needs: test
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --dev
      - run: uv build

      - uses: actions/upload-artifact@v4
        with:
          name: python-dist
          path: dist/*

  publish:
    needs: build
    runs-on: ubuntu-latest

    environment:
      name: pypi

    permissions:
      id-token: write
      contents: read

    steps:
      - uses: actions/download-artifact@v4
        with:
          name: python-dist
          path: dist

      - uses: pypa/gh-action-pypi-publish@release/v1
```

Nên thêm job cài wheel trong clean environment trước publish.

---

# 20. GitHub Actions publish native wheels

`.github/workflows/publish-native.yml`:

```yaml
name: Publish quantbt-native

on:
  release:
    types: [published]

permissions:
  contents: read

jobs:
  linux:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: PyO3/maturin-action@v1
        with:
          working-directory: rust/native_event
          command: build
          args: >
            --release
            --out dist
            --interpreter python3.11 python3.12 python3.13
            --manylinux auto

      - uses: actions/upload-artifact@v4
        with:
          name: native-wheels-linux
          path: rust/native_event/dist/*

  test-native:
    needs: linux
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"

      - uses: actions/download-artifact@v4
        with:
          name: native-wheels-linux
          path: native-dist

      - run: uv pip install dist/quantbt_engine-*.whl
      - run: uv pip install native-dist/quantbt_native-*.whl
      - run: uv run pytest tests/native_event tests/parity

  publish-native:
    needs: test-native
    runs-on: ubuntu-latest

    environment:
      name: pypi

    permissions:
      id-token: write
      contents: read

    steps:
      - uses: actions/download-artifact@v4
        with:
          name: native-wheels-linux
          path: dist

      - uses: pypa/gh-action-pypi-publish@release/v1
```

Ban đầu chỉ cần Linux x86-64 vì đó là môi trường VPS chính.

Sau khi ổn mới thêm:

```text
Linux aarch64
macOS arm64
Windows x86-64
```

---

# 21. API token PyPI

## Dùng khi nào

Chỉ dùng cho:

- manual TestPyPI;
- debug publish;
- emergency fallback.

Không dùng làm release mechanism chính.

## Tạo token

PyPI:

```text
Account settings
→ API tokens
→ Add API token
```

Sau khi project tồn tại:

```text
Scope: Project — quantbt-engine
```

hoặc:

```text
Scope: Project — quantbt-native
```

Không dùng account-wide token nếu không bắt buộc.

## Cách authenticate

```text
username = __token__
password = pypi-xxxxxxxx
```

Manual publish:

```bash
export TWINE_USERNAME="__token__"
export TWINE_PASSWORD="pypi-xxxxxxxx"

uv run twine upload dist/*
```

## GitHub secret fallback

Repository:

```text
Settings
→ Secrets and variables
→ Actions
→ New repository secret
```

Tên:

```text
PYPI_API_TOKEN
```

Workflow fallback:

```yaml
- name: Publish with token
  env:
    TWINE_USERNAME: __token__
    TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
  run: uv run twine upload dist/*
```

Sau khi OIDC hoạt động:

```text
xóa secret
revoke token trên PyPI
```

---

# 22. GitHub release procedure

Quy trình chuẩn:

1. Merge code vào `main`.
2. Update version.
3. Chạy full tests/parity/benchmark.
4. Commit release.
5. Tạo tag:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
6. Tạo GitHub Release từ tag.
7. Workflow tự:
   - test;
   - build;
   - clean-install;
   - parity;
   - publish.
8. Kiểm tra:
   ```bash
   pip install quantbt-engine==0.1.0
   ```
9. Chạy public API smoke test.

Tag `v*` và GitHub environment `pypi` nên được bảo vệ bằng reviewer.

---

# 23. Pool Alpha migration

Giai đoạn local:

```toml
quantbt = {
    path = "../quantbt",
    develop = true
}
```

Hoặc cài editable:

```bash
pip install -e /root/bobby/pool_alpha/quantbt
```

Sau khi publish:

```toml
quantbt-engine = "^0.1.0"
```

Import alpha không đổi:

```python
from quantbt import QuantBTEndpoint
```

Có thể giữ local editable override trong development.

---

# 24. Thứ tự triển khai cuối cùng

## Phase 1 — Package hóa Python

- Tạo `pyproject.toml`.
- Tạo `uv.lock`.
- Copy source sang `src/quantbt`.
- Giữ nguyên imports/endpoints.
- Chạy full tests.
- Build/install wheel.
- Test với pool_alpha.

## Phase 2 — Publish package Python

- TestPyPI.
- Clean environment smoke.
- PyPI Trusted Publisher.
- Release `quantbt-engine`.

## Phase 3 — Native Event Python optimization

- Giảm RSS/object retention.
- Score artifact minimization.
- Context/margin cache.
- Queue cleanup.
- Lifecycle indexes cần thiết.
- Benchmark/parity.

## Phase 4 — PyO3 POC

- Tạo `quantbt-native`.
- Rust session scope nhỏ.
- Differential parity.
- CPU/RSS benchmark gate.

## Phase 5 — Rust expansion

- Mở rộng lifecycle từng feature.
- Không merge feature nếu parity fail.
- Giữ Python fallback và oracle.

## Phase 6 — Release accelerator

- Build Linux wheels.
- Publish `quantbt-native`.
- `quantbt-engine[native]`.
- Auto backend selection.
- Selected candidate replay certification.

---

# 25. Definition of Done

Plan hoàn thành khi:

- `pip install quantbt-engine` chạy độc lập;
- `from quantbt import QuantBTEndpoint` không đổi;
- alpha cũ không phải sửa;
- pool_alpha chạy được bằng editable và PyPI dependency;
- package build/install sạch;
- GitHub Release tự publish qua OIDC;
- không cần API token dài hạn;
- Rust accelerator optional;
- thiếu Rust vẫn chạy Python/Numba;
- Rust path pass lifecycle/accounting parity;
- selected candidates rerun bằng replay oracle;
- benchmark chứng minh speedup;
- repeated-run RSS plateau;
- không đổi domain logic để lấy tốc độ.
---

# 26. Chiến lược branch, merge và rollback

## 26.1. Không làm trực tiếp trên `main`

Trạng thái repository hiện tại có:

```text
main → default/release branch
dev  → active integration branch
```

Không checkout `main` rồi package hóa hoặc sửa Native Event trực tiếp.

Quy ước:

```text
main
└── chỉ nhận code đã qua full test/parity/release gate

dev
└── nhánh tích hợp trước release

feature/performance branches
└── nơi agent thực hiện từng scope độc lập
```

## 26.2. Tạo baseline trước migration

Từ repository local:

```bash
git fetch --all --prune
git checkout dev
git pull --ff-only origin dev

git status
git tag pre-quantbt-engine-packaging-20260731
git push origin pre-quantbt-engine-packaging-20260731
```

Tag này chỉ là rollback/reference, không phải PyPI release.

Trước khi sửa:

```bash
uv run pytest
```

Nếu `uv` chưa tồn tại thì chạy test bằng environment hiện tại và lưu kết quả baseline.

Lưu thêm:

```text
git commit SHA
Python version
NumPy/Pandas/Numba versions
full test result
Native Event benchmark result
peak RSS
```

## 26.3. Các branch bắt buộc

### Branch 1 — package hóa, tuyệt đối không đổi behavior

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/quantbt-engine-packaging
```

Scope duy nhất:

- `pyproject.toml`;
- `uv.lock`;
- `src/quantbt`;
- copy source;
- CI build/install;
- PyPI preparation;
- pool_alpha dependency compatibility.

Không tối ưu Native Event trong branch này.

Merge gate:

```text
public imports pass
full tests pass
wheel install pass
pool_alpha smoke pass
backtest fingerprints unchanged
```

Sau khi pass:

```text
feat/quantbt-engine-packaging
→ PR
→ dev
```

### Branch 2 — tối ưu Python Native Event

Chỉ tạo sau khi Branch 1 đã merge vào `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b perf/native-event-python-hotpath
```

Scope:

- memory retention;
- score hot path;
- queue cleanup;
- context allocation;
- margin cache;
- lifecycle indexes;
- parity expansion;
- benchmarks.

Không thêm Rust trong branch này.

Merge gate:

```text
lifecycle parity 100%
accounting parity 100%
public API unchanged
RSS/runtime improvement measured
```

### Branch 3 — PyO3 accelerator

Chỉ tạo sau khi Branch 2 đã merge:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/native-event-pyo3
```

Scope:

- `quantbt-native`;
- Rust reactive session POC;
- Python adapter/backend selector;
- Rust/Python/replay differential tests;
- native wheels.

Không package lại toàn bộ repo trong branch này.

### Release branch

Khi `dev` đã đủ điều kiện release:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b release/0.1.0
```

Release branch chỉ làm:

- version;
- changelog;
- release notes;
- final lockfile;
- final wheel smoke;
- metadata corrections.

Sau đó:

```text
release/0.1.0
→ PR vào main
→ tag từ main
→ GitHub Release
→ PyPI publish
```

## 26.4. Vì sao phải tách branch

Không gộp package migration, Native Event optimization và Rust vào một PR vì khi parity fail sẽ không biết lỗi đến từ:

```text
import/layout
dependency/build
Python runtime optimization
Rust boundary
domain logic
```

Tách branch làm cho:

- diff nhỏ hơn;
- rollback rõ;
- review dễ;
- benchmark có baseline sạch;
- agent ít phải suy luận;
- không phá `pool_alpha`.

## 26.5. Merge policy

Không squash một branch lớn nếu cần giữ các checkpoint kỹ thuật.

Trong mỗi branch, nên có commit theo patch:

```text
1. tests/baseline
2. implementation
3. benchmark
4. docs
```

Không force-push `main`.

Nên bật branch protection cho `main`:

```text
Require pull request
Require status checks
Block force pushes
Require conversation resolution
```

`dev` có thể linh hoạt hơn nhưng vẫn yêu cầu CI pass trước merge.

---

# 27. Native Event — bản đồ implementation hiện tại

Sau khi package hóa, các path dưới đây được hiểu là:

```text
src/quantbt/backends/native_event.py
src/quantbt/core/reactive.py
src/quantbt/core/preprocessor.py
src/quantbt/core/orders.py
src/quantbt/core/event.py
```

Nếu chưa migrate sang `src`, agent áp dụng vào path root tương ứng rồi giữ diff dễ chuyển.

## 27.1. Public contract không được đổi

Giữ:

```python
from quantbt import QuantBTEndpoint
```

Giữ:

```python
NativeEventBackend.run_strategy(...)
NativeEventBackend.run_order_commands(...)
QuantBTEndpoint.native_event_strategy(...)
```

Giữ callback:

```python
strategy.initialize(context)
strategy.on_bar_close(context)
strategy.finalize(context)
```

Giữ:

```text
command_effective_phase = next_bar
```

Không đổi `OrderCommand`, `NativeStrategyContext`, `NativeFillEvent`,
`NativeOrderEvent`, `BacktestResultV2` ở public boundary.

## 27.2. Callback timing hiện hành phải được khóa bằng test

Agent phải giữ chính xác thứ tự:

```text
1. Process state bar 0.
2. initialize(context_bar_0).
3. Commands từ initialize có effective_bar = 1.
4. on_bar_close(context_bar_0).
5. Commands từ on_bar_close bar 0 cũng có effective_bar = 1.
6. Tại bar 1, commands initialize được apply trước commands bar 0,
   theo đúng thứ tự chúng được append.
7. Lặp cho các bar tiếp theo.
8. finalize(last_context).
9. Commands finalize có effective_bar = len(index), được ghi nhận là
   ngoài tape thực thi nếu vượt cuối dữ liệu.
```

Không “simplify” bằng cách cho command khớp ngay tại bar callback vừa phát.

Không đổi object ordering của commands cùng effective bar.

## 27.3. Các hotspot cần sửa đúng chỗ

Trong `NativeEventArtifactPlan` hiện tại, `score` vẫn có xu hướng giữ:

```text
equity path
position path
fee path
funding path
margin path
command terminal state
pandas materialization
```

Trong `_NativeEventReactiveSession` hiện tại:

```text
orders
pending
id_to_order
scheduled
fills_by_bar
events_by_bar
```

được giữ trong toàn run.

`context()` hiện còn:

```text
_close_margin()
positions dict construction
size helper construction
OHLCV copy
active snapshot construction
```

Các loop hiện còn scan/copy:

```python
tuple(self.pending)
```

ở:

```text
CANCEL_ALL
matching
parent activation
OCO cancellation
expiry
```

`_reactive_session_result()` luôn dựng pandas và copy full arrays.

`_assert_reactive_session_replay_parity()` hiện chủ yếu so accounting paths;
plan mới phải bổ sung lifecycle parity.

---

# 28. Native Event Phase NE-0 — đóng băng behavior trước tối ưu

## 28.1. Không sửa implementation trước khi có tests

Tạo:

```text
tests/native_event/test_reactive_callback_contract.py
tests/native_event/test_reactive_lifecycle_parity.py
tests/native_event/test_reactive_accounting_parity.py
tests/native_event/test_reactive_memory_lifetime.py
tests/native_event/test_reactive_backend_matrix.py
benchmarks/native_event/benchmark_reactive_session.py
```

Không đổi tên test hiện có; chỉ bổ sung.

## 28.2. Golden command tapes

Tạo fixtures có command tape cố định cho:

```text
market order
limit order
stop-market
stop-limit
GTC
GTD
IOC
FOK
PLACE
AMEND
REPLACE
CANCEL
CANCEL_ALL
reduce-only
parent first-fill
parent full-fill
OCO
quantity quantization
insufficient margin
funding
intrabar liquidation
after-funding liquidation
after-order liquidation
multi-symbol
```

Mỗi fixture phải lưu logical fingerprint:

```text
command effective bar
command sequence
event type
event status
reject reason
fill bar
fill symbol
fill side
fill qty
fill price
fill fee
position after each bar
equity after each bar
margin after each bar
liquidation result
```

Không dùng dataframe string representation làm fingerprint.

Dùng arrays/tuples với stable dtype/order.

## 28.3. Backend matrix

Mỗi case chạy:

```text
replay_certified
python single_pass
rust single_pass  # skip khi extension chưa có
```

Reference:

```text
replay_certified
```

Python single-pass phải pass trước khi viết Rust.

## 28.4. Baseline benchmark

Đo ít nhất:

```text
25k bars / ít orders
25k bars / order churn cao
100k bars / ít orders
100k bars / order churn cao
parent/OCO-heavy
GTD-heavy
multi-symbol
100 repeated prepared scores
```

Ghi:

```text
wall time
CPU time
peak RSS
RSS sau run
command count
event count
fill count
max active orders
```

Không so cold Numba compile với warm run trong cùng một số liệu.

---

# 29. Native Event Phase NE-1 — score retention và result path

## 29.1. Không phá `BacktestResultV2`

Không đổi public `.simulate()` hoặc `.run_strategy()` sang result type mới.

Tạo internal score path dùng cho prepared optimization:

```text
NativeEventScoreRequirements
NativeEventScoreState
NativeEventScoreResult
```

Tên có thể điều chỉnh theo conventions hiện tại, nhưng phải internal.

Public audit/result path vẫn trả `BacktestResultV2`.

## 29.2. Thêm requirements nội bộ

Ví dụ:

```python
@dataclass(frozen=True, slots=True)
class NativeEventScoreRequirements:
    need_equity_path: bool = True
    need_position_path: bool = False
    need_fee_path: bool = False
    need_funding_path: bool = False
    need_margin_path: bool = False
    need_trade_stats: bool = True
    need_terminal_commands: bool = False
    need_fill_ledger: bool = False
```

Không truyền object này qua endpoint public.

Prepared evaluator/runner tạo requirements từ objective/metric fields.

Nếu objective không khai báo requirements, dùng safe default hiện tại.

## 29.3. Session allocation phải phụ thuộc retention

Sửa constructor `_NativeEventReactiveSession`:

```python
def __init__(
    ...,
    artifact_plan: NativeEventArtifactPlan,
    score_requirements: NativeEventScoreRequirements | None = None,
):
```

Không luôn allocate:

```python
self.pos_path
self.fee_path
self.turnover_path
self.funding_path
self.initial_margin_path
self.maintenance_margin_path
self.rejected_bar
self.canceled_bar
```

Pattern:

```python
self.equity_path = (
    np.empty(n_bars, dtype=np.float64)
    if keep_equity_path
    else None
)
```

`_record_bar()` phải write có điều kiện.

Không dùng dummy zero-length/full-length arrays để lách code vì vẫn tăng complexity và có thể gây report bug.

## 29.4. Public path và prepared score path tách ở materialization

Public:

```text
run_strategy()
→ BacktestResultV2
→ pandas/report compatibility giữ nguyên
```

Prepared optimization:

```text
prepared.score()
→ internal score result/scalars
→ không gọi _reactive_session_result()
→ không materialize pandas
```

Không thay signature public của `prepared.score()` nếu đã được sử dụng.
Chỉ thay implementation bên dưới.

Nếu local code chưa có score-result class, thêm adapter để evaluator vẫn đọc được:

```text
sharpe
max_drawdown_pct
num_trades
profit_factor
final_equity
```

## 29.5. Online metrics

Session giữ:

```text
previous_equity
running_return_count
running_return_mean
running_return_m2
running_equity_peak
max_drawdown
gross_profit
gross_loss
fill_count
total_fee
total_funding
total_turnover
max_initial_margin
max_maintenance_margin
```

Dùng Welford/stable online moments.

Không thay công thức metric hiện tại.

Trước khi bỏ equity path, test:

```text
online metric
vs metric tính từ canonical equity path
```

Nếu metric hiện tại annualize hoặc xử lý zero/NaN theo rule riêng,
online implementation phải copy đúng rule đó, không dùng công thức gần giống.

---

# 30. Native Event Phase NE-2 — queue và object lifetime

## 30.1. Scheduled commands

Trong `_process_single_bar()` thay:

```python
for command in self.scheduled.get(bar, ()):
```

bằng:

```python
commands = self.scheduled.pop(bar, ())
for command in commands:
    self._apply_command(bar, command)
```

Command đã apply không được giữ trong `scheduled`.

Audit command tape vẫn là `emitted` hoặc compact ledger riêng.

## 30.2. Fill/event callback payload

Không pop trước callback.

Flow đúng:

```python
context = session.context(bar)
commands = callback(context)
session.release_bar_payload(bar)
```

`release_bar_payload(bar)`:

```python
self.fills_by_bar.pop(bar, None)
self.events_by_bar.pop(bar, None)
```

Context hiện tại vẫn giữ tuple đã materialize cho callback.

Vì `last_context` cần cho `finalize`, việc pop dictionary không được làm mất
payload đã nằm trong `last_context`.

Không giữ mọi fill/event của mọi bar trong callback dictionaries.

Audit ledger phải là cấu trúc riêng.

## 30.3. Terminal orders

Thêm:

```text
seen_order_ids
```

để kiểm duplicate ID xuyên toàn run.

`id_to_order` chỉ giữ active/waiting orders.

Khi state terminal:

```text
status update
active=False
waiting_parent=False
remove active indexes
remove id_to_order nếu mapping đang trỏ đúng state
```

Không xóa một mapping vừa được REPLACE sang state mới.

Dùng guard:

```python
if self.id_to_order.get(order_id) is state:
    self.id_to_order.pop(order_id, None)
```

`orders` chỉ giữ full history khi artifact plan yêu cầu.

Score mode không append terminal history vào `orders`.

## 30.4. Một helper terminal transition

Tạo một helper internal duy nhất, ví dụ:

```python
def _terminalize_state(
    self,
    *,
    bar: int,
    state: _ReactiveOrderState,
    status: int,
    reject_code: int = 0,
) -> None:
    ...
```

Helper chỉ làm lifecycle storage cleanup.

Không tự phát event trong helper nếu điều đó làm thay đổi event ordering.
Caller vẫn kiểm soát thứ tự:

```text
state transition
event emission
parent activation
OCO cancellation
```

theo behavior hiện tại.

## 30.5. Pending compaction

Không tạo `tuple(self.pending)` trong mỗi hot operation.

Giữ:

```text
mark state terminal trong loop
compact đúng một lần cuối bar
```

`_compact_pending()` có thể tiếp tục dùng list comprehension.

Không swap-remove nếu có nguy cơ đổi order priority.

Order matching priority phải giữ nguyên insertion/command sequence.

---

# 31. Native Event Phase NE-3 — context allocation an toàn

## 31.1. Cache immutable helpers

Trong session constructor:

```python
self.symbols_tuple = tuple(symbols)
self.size_helper = NativeEventBackend._reactive_size_helper(...)
self.empty_fills = ()
self.empty_events = ()
self.empty_active_orders = ()
```

`context()` không dựng lại `size_helper` và `symbols tuple`.

## 31.2. OHLCV zero-copy

Prepared market arrays phải:

```python
array.flags.writeable = False
```

Áp dụng cho:

```text
opens
highs
lows
closes
volumes
funding
funding mask
```

Chỉ làm sau khi arrays đã build hoàn chỉnh.

Trong context:

```python
open_row = self.opens_arr[bar]
high_row = self.market_arrays.highs[bar]
...
```

Không `.copy()`.

Vì base arrays read-only, strategy mutate phải raise.

Không zero-copy mutable state như positions.

## 31.3. Positions phải là snapshot

Không trả live mapping tham chiếu trực tiếp `current_pos`, vì strategy có thể giữ context
và đọc lại sau khi engine đã chạy tiếp.

Giữ snapshot semantics.

Single-symbol fast path có thể tạo:

```python
{symbol: float(current_pos[0])}
```

Multi-symbol vẫn có thể dùng dict comprehension ban đầu.

Chỉ tối ưu sâu hơn nếu profiler chứng minh positions dict là hotspot.

## 31.4. Active order snapshots

Nếu không có pending orders:

```python
active_orders = self.empty_active_orders
```

Nếu có, materialize một lần cho context.

Không scan pending thêm lần nữa ở cùng bar ngoài nhu cầu callback.

Có thể cache snapshot và invalidation flag:

```text
active_snapshot_dirty = True
```

Set dirty khi:

```text
PLACE
AMEND
REPLACE
CANCEL
FILL
EXPIRE
ACTIVATE
```

Không cache qua state transition.

## 31.5. Dataclass slots

Thêm:

```python
@dataclass(slots=True)
class _ReactiveOrderState:
    ...
```

Có thể thêm `slots=True` cho internal score state/buffers.

Không đổi public dataclass layout trong cùng performance branch nếu chưa benchmark
và chưa kiểm pickle/serialization compatibility.

---

# 32. Native Event Phase NE-4 — indexes có lợi rõ ràng

Không xây generic cache/message bus.

## 32.1. Parent index

Trong session:

```python
self.children_by_parent_id: dict[str, list[_ReactiveOrderState]]
```

Khi PLACE child:

```python
children_by_parent_id.setdefault(parent_id, []).append(state)
```

Khi parent fill:

```python
for child in children_by_parent_id.get(parent_id, ()):
    ...
```

Sau khi không còn child pending:

```python
children_by_parent_id.pop(parent_id, None)
```

Giữ child order insertion order.

## 32.2. OCO index

```python
self.members_by_oco_group: dict[str, list[_ReactiveOrderState]]
```

Khi one order fills:

```python
for sibling in members_by_oco_group.get(group, ()):
    ...
```

Không scan toàn pending.

Không đổi thứ tự cancel siblings.

Sau khi group không còn active member, remove group.

## 32.3. Expiry bucket theo bar

Không convert `pd.Timestamp` trong mỗi bar.

Khi PLACE GTD:

1. Normalize expiry timezone một lần.
2. Convert thành nanoseconds.
3. Tìm bar expiry:

```python
expiry_bar = int(self.idx.searchsorted(expiry_ns, side="left"))
```

4. Register:

```python
self.expiry_by_bar.setdefault(expiry_bar, []).append(state)
```

Trong `_expire_orders(bar)` chỉ xử lý bucket của bar hiện tại.

Semantics phải đúng với rule hiện tại:

```text
expire tại bar đầu tiên có timestamp >= expires_at
```

Nếu expiry ngoài dữ liệu, không schedule bucket executable.

## 32.4. `CANCEL_ALL`

Giữ scan pending trong giai đoạn này vì filters có thể gồm:

```text
symbol
side
order type
parent
group
OCO
tag
tag prefix
metadata
```

Không xây nhiều index chỉ để tối ưu một command ít dùng.

Chỉ thêm fast path:

```text
CANCEL_ALL không filter
→ iterate current pending một lần
```

Nếu profiler chứng minh `CANCEL_ALL` là hotspot mới tối ưu tiếp.

---

# 33. Native Event Phase NE-5 — margin/accounting cache

## 33.1. Không thay công thức

Giữ đúng:

```text
PnL timing
funding sign/timing
fee application
slippage
initial margin
maintenance margin
liquidation priority
```

Không “đơn giản hóa” công thức trong performance branch.

## 33.2. Refresh close margin một lần mỗi bar

Tạo:

```python
def _refresh_close_margin(self, bar: int) -> None:
    ...
```

Nó cập nhật:

```text
last_initial_margin
last_maintenance_margin
margin_bar
```

Trong cùng bar, nếu position không đổi, `context()` và `_record_bar()` dùng cache.

## 33.3. Sau fill

Một fill làm position thay đổi.

Sau fill có thể:

- mark `margin_dirty=True`;
- refresh trước margin check tiếp theo;
- hoặc update contribution của đúng symbol.

Bước đầu ưu tiên dirty-cache vì ít rủi ro hơn.

Không giữ stale margin qua:

```text
fill
liquidation
new bar
```

## 33.4. `_margin_required`

Không gọi `_close_margin()` scan toàn symbols cho mỗi active order nếu margin cache của bar hợp lệ.

Dùng:

```python
cur_im = self.last_initial_margin
```

nhưng chỉ sau `_refresh_close_margin(bar)`.

Sau accepted fill:

```text
margin_dirty=True
```

Trước order tiếp theo cần margin:

```text
refresh nếu dirty
```

Điều này giữ sequential margin acceptance giữa nhiều orders cùng bar.

Không precompute tất cả order margin độc lập vì order trước ảnh hưởng order sau.

## 33.5. Intrabar liquidation

`_liquidated_intrabar()` vẫn tuần tự/canonical.

Chỉ vectorize hoặc Rust hóa sau parity baseline.

Không dùng `fastmath`.

---

# 34. Native Event Phase NE-6 — lifecycle parity đầy đủ

## 34.1. Không chỉ so accounting arrays

Bổ sung helper:

```python
assert_native_event_full_parity(
    candidate,
    oracle,
)
```

So exact:

```text
command count
effective command bar
command order
status
reject code
fill bar
fill qty
fill price
fill fee
active/waiting parent
parent activation
OCO cancellation
expiry
liquidation flag/bar/reason
```

Accounting:

```text
equity
positions
fees
funding
turnover
initial margin
maintenance margin
```

## 34.2. Tolerance

Ưu tiên:

```python
np.testing.assert_array_equal(...)
```

Nếu float ordering khác nhưng domain decisions identical:

```python
np.testing.assert_allclose(
    ...,
    rtol=0.0,
    atol=1e-12,
)
```

Không mặc định nới tới `1e-9` cho certification mới.

Có thể giữ helper cũ để backward compatibility, nhưng merge gate dùng helper chặt mới.

## 34.3. Discrete decisions không có tolerance

Phải exact:

```text
fill/no fill
reject/accept
order sequence
status
position quantity sau quantization
liquidation decision
liquidation bar
```

## 34.4. Fingerprint

Tạo compact deterministic fingerprint từ arrays:

```text
SHA256(
    command lifecycle arrays
    + fill arrays
    + positions float64 bytes
    + equity float64 bytes
    + fee/funding/margin bytes
    + liquidation fields
)
```

Không dùng hash Python mặc định vì seed/process-dependent.

---

# 35. Native Event Phase NE-7 — prepared runner integration

## 35.1. Prepared market data immutable

Prepared runner giữ một lần:

```text
datetime index
symbols
OHLCV arrays
funding arrays
constraints
contract sizes
leverages
fee rates
```

Mỗi trial chỉ tạo mutable session.

Không copy market arrays mỗi trial.

## 35.2. Trial reset

Mỗi score trial phải tạo session state sạch hoặc gọi reset được chứng nhận.

Không tái sử dụng mutable:

```text
orders
positions
equity
queues
indexes
metrics
```

giữa trials.

Prepared immutable arrays mới được reuse.

## 35.3. Evaluator không giữ trial trước

Không giữ:

```text
last_strategy
last_result
last_session
```

trong optimization evaluator.

Nếu debug cần, phải opt-in và không dùng trong overnight score.

## 35.4. Candidate cuối

Optimization:

```text
fast Python/Rust score
```

Candidate selected:

```text
replay_certified audit rerun
→ full parity fingerprint
→ chỉ sau đó mới accepted
```

---

# 36. PyO3 — cách tích hợp chính xác mà không đổi endpoint

## 36.1. Python files đề xuất

Thêm đúng một adapter mỏng:

```text
src/quantbt/backends/_native_event_rust.py
```

Nó chịu trách nhiệm:

```text
optional import _quantbt_native
backend availability
version compatibility
command batch compile
Rust step result → NativeStrategyContext payload
error translation
```

Không đưa domain logic mới vào adapter.

Trong `native_event.py`, thêm session factory internal:

```python
def _create_reactive_session(
    *,
    backend: str,
    ...
):
    if backend == "rust":
        return RustReactiveSessionAdapter(...)
    return _NativeEventReactiveSession(...)
```

Endpoint không đổi.

## 36.2. Auto backend rollout

Giai đoạn đầu:

```text
auto → Python
rust → explicit opt-in
```

Sau khi Rust pass toàn bộ certification và production soak:

```text
auto → Rust nếu installed + compatible + certified
else Python
```

Không bật Rust mặc định ngay khi POC vừa compile.

## 36.3. Rust crate tối thiểu

```text
rust/native_event/
├── Cargo.toml
├── pyproject.toml
└── src/
    ├── lib.rs
    ├── session.rs
    ├── types.rs
    ├── matching.rs
    └── accounting.rs
```

POC có thể bắt đầu trong `lib.rs`, nhưng trước khi mở rộng full lifecycle nên tách như trên.

Trách nhiệm:

```text
lib.rs       → PyO3 boundary/module/class
types.rs     → integer enums, command/fill/event structs
session.rs   → mutable state, indexes, step/reset
matching.rs  → touch/order matching rules
accounting.rs→ PnL, fee, funding, margin, liquidation
```

Không thêm message bus, actor hoặc async runtime.

## 36.4. Rust session API

Rust giữ toàn bộ prepared market arrays khi initialize.

Python không truyền OHLC row copy mỗi bar.

Đề xuất:

```python
core = _quantbt_native.ReactiveSessionCore(
    timestamps_ns,
    opens,
    highs,
    lows,
    closes,
    volumes,
    funding,
    funding_mask,
    contract_sizes,
    leverages,
    fee_rates,
    initial_capital,
    maintenance_ratio,
    slippage_rate,
    use_funding,
)
```

Mỗi bar:

```python
step = core.step(
    bar_index,
    command_codes,
    command_values,
    command_expiry,
)
```

Một call Rust mỗi bar.

`step()`:

```text
process PnL
intrabar liquidation check
funding
after-funding liquidation check
expiry
commands effective bar này
matching
after-order liquidation check
record current state
return compact fill/event/context data
```

Thứ tự phải copy đúng Python/replay oracle.

## 36.5. Bar 0 và callback flow với Rust

Không gọi `step(0)` hai lần.

Flow adapter:

```text
step(0, empty commands)
→ build context0
→ initialize(context0)
→ on_bar_close(context0)
→ concatenate commands theo thứ tự:
   initialize commands trước
   bar0 commands sau
→ step(1, combined commands)
```

Tại bar `t > 0`:

```text
step(t, commands effective t)
→ context_t
→ on_bar_close(context_t)
→ compile commands effective t+1
```

Sau bar cuối:

```text
finalize(last_context)
```

Finalize commands ngoài range không được execute.

Giữ emitted command tape ordering để replay parity.

## 36.6. Command batch format

Không truyền list `OrderCommand` vào Rust hot path.

Python adapter compile thành:

```text
codes:  int64[:, K]
values: float64[:, V]
expiry: int64[:]
```

Ví dụ `codes` chứa:

```text
action
symbol
side
order_type
tif
order_id_code
target_id_code
parent_id_code
group_id_code
oco_id_code
activation_policy
flags
command_sequence
```

`values` chứa:

```text
qty
price
trigger_price
```

Flags:

```text
reduce_only
has_qty
has_price
has_trigger
```

Không dùng NaN để biểu diễn missing nếu Python oracle đang phân biệt rõ missing/zero.

## 36.7. ID interning

Python adapter có session-local string interner:

```text
string → int64 code
```

Interner chỉ mã hóa identity; không quyết định domain validity.

Rust vẫn kiểm:

```text
duplicate order ID
unknown target
parent lookup
OCO membership
```

Metadata dictionary không đi vào Rust matching core.

Giữ Python side table:

```text
command_sequence → original OrderCommand/metadata
```

để materialize callback/audit objects.

Score mode chỉ giữ metadata cho active/current callback needs.

## 36.8. Rust state representation

Rust dùng compact state:

```text
Vec<OrderState>
free slot stack
HashMap<order_id_code, slot>
HashMap<parent_id_code, Vec<slot>>
HashMap<oco_id_code, Vec<slot>>
Vec<Vec<slot>> expiry_by_bar
Vec<f64> positions
scalar equity
margin cache
reusable fill buffer
reusable event buffer
online metrics
```

Order slot giữ primitive fields, không giữ Python objects.

Terminal slot:

```text
remove indexes
mark inactive
push free-list khi score mode cho phép
```

Không reuse slot trước khi current callback payload đã materialize.

## 36.9. Step result

Rust trả compact arrays/scalars:

```text
equity
initial_margin
maintenance_margin
liquidated
liquidation_bar
positions snapshot
fill records
order-event records
active-order records hoặc active slots
```

Python adapter materialize:

```text
NativeFillEvent
NativeOrderEvent
NativeActiveOrderSnapshot
NativeStrategyContext
```

chỉ tại callback boundary.

Không materialize pandas trong Rust.

## 36.10. GIL

`step()` không gọi ngược Python.

Rust có thể release GIL trong pure Rust section.

Không parallelize bars.

Không dùng Rayon trong event loop.

Không dùng unsafe optimization trong POC.

Không bật fast-math.

## 36.11. Float/domain rules

Rust dùng:

```text
f64
```

Giữ chính xác thứ tự:

```text
trade notional
fee
required margin
equity update
position update
funding
liquidation
```

Không chuyển sang decimal/f32 trong performance scope.

Không “improve” rounding mà chưa có domain issue riêng.

Quantity quantization phải reuse cùng inputs/rules với Python.

---

# 37. PyO3 POC implementation slices

## Slice R0 — build/import only

- Build `_quantbt_native`.
- Expose version/capabilities.
- Wheel install smoke.
- Không route production run qua Rust.

Pass:

```text
import works
version compatibility works
Python fallback works when extension absent
```

## Slice R1 — market + limit, PLACE/CANCEL, GTC

Rust hỗ trợ:

```text
single-symbol
market
limit
PLACE
CANCEL
GTC
fee
slippage
position
equity
```

Python explicit:

```bash
QUANTBT_NATIVE_BACKEND=rust
```

`auto` vẫn Python.

## Slice R2 — stop, amend, replace, reduce-only, constraints

Thêm từng feature và test riêng.

Không gộp tất cả vào một commit.

## Slice R3 — parent/OCO/expiry/TIF

Thứ tự:

```text
parent activation
OCO
GTD
IOC
FOK
CANCEL_ALL
```

## Slice R4 — funding/margin/liquidation

Đây là slice rủi ro cao.

Phải pass:

```text
multi-order same bar
margin acceptance sequence
intrabar liquidation
after-funding liquidation
after-order liquidation
```

## Slice R5 — multi-symbol

Chỉ làm sau single-symbol full lifecycle parity.

Không đổi command ordering giữa symbols.

---

# 38. PyO3 benchmark/stop conditions

## 38.1. Đo end-to-end

Không chỉ benchmark Rust kernel.

Đo:

```text
strategy callback
Python command compile
PyO3 boundary
Rust step
Python event materialization
score metric
total run
RSS
```

## 38.2. Gate

Rust tiếp tục chỉ khi:

```text
full parity = 100%
median end-to-end speedup >= 1.20x
high-churn speedup >= 1.50x
peak RSS reduction >= 30%
repeated-run RSS plateau
```

Kernel nhanh nhưng end-to-end không đạt thì không bật mặc định.

## 38.3. Stop

Dừng mở rộng Rust nếu:

```text
boundary conversion chiếm phần lớn runtime
strategy Python là bottleneck tuyệt đối
RSS không giảm
parity phải dựa vào tolerance lớn
maintenance complexity vượt lợi ích
```

Giữ crate experimental hoặc bỏ khỏi default install.

---

# 39. Test names agent phải tạo

Tối thiểu:

```text
test_native_event_initialize_and_bar0_ordering
test_native_event_commands_effective_next_bar
test_native_event_same_bar_command_sequence
test_native_event_cancel_replace_amend_parity
test_native_event_parent_activation_parity
test_native_event_oco_parity
test_native_event_gtd_expiry_bar_parity
test_native_event_ioc_fok_parity
test_native_event_reduce_only_parity
test_native_event_quantity_constraint_parity
test_native_event_funding_parity
test_native_event_margin_sequence_parity
test_native_event_liquidation_priority_parity
test_native_event_multisymbol_parity
test_native_event_score_no_pandas_materialization
test_native_event_score_does_not_retain_terminal_orders
test_native_event_consumed_queues_are_released
test_native_event_repeated_score_rss_plateaus
test_native_event_python_vs_replay_randomized
test_native_event_rust_vs_replay_randomized
test_native_event_backend_fallback_without_extension
test_native_event_backend_version_mismatch_falls_back
```

Randomized tests phải có seed cố định và in seed khi fail.

---

# 40. File-level patch order cho agent

## PR/commit 1 — tests only

```text
tests/native_event/*
benchmarks/native_event/*
```

Không đổi source.

## PR/commit 2 — retention + queue cleanup

Sửa chủ yếu:

```text
src/quantbt/backends/native_event.py
```

Không thêm Rust.

## PR/commit 3 — context + margin cache

Sửa:

```text
src/quantbt/backends/native_event.py
src/quantbt/core/preprocessor.py
```

Chỉ set market arrays read-only sau build.

## PR/commit 4 — parent/OCO/expiry indexes

Sửa:

```text
src/quantbt/backends/native_event.py
```

Không đổi public order schema.

## PR/commit 5 — prepared score integration

Sửa đúng prepared runner/evaluator hiện hữu.

Không giữ last strategy/result.

## PR/commit 6 — Rust scaffold

Thêm:

```text
rust/native_event/*
src/quantbt/backends/_native_event_rust.py
```

Production route vẫn Python.

## PR/commit 7+ — từng Rust feature slice

Mỗi slice:

```text
feature
tests
parity output
benchmark output
```

Không merge một Rust rewrite khổng lồ.

---

# 41. Release workflow correction/addendum

Hai workflow package chính và native có thể giữ, nhưng native test job phải chắc chắn
có package chính để install.

Không tham chiếu:

```text
dist/quantbt_engine-*.whl
```

nếu workflow native chưa download/build artifact đó.

Chọn một trong hai:

## Phương án khuyến nghị — một release workflow orchestration

```text
build-core
build-native
test-core-wheel
test-core-plus-native-wheels
publish-core
publish-native
```

`publish-*` chỉ chạy sau test kết hợp.

## Phương án hai workflow

Native workflow phải:

```text
checkout
build/install quantbt-engine từ cùng tag
download native wheel
install cả hai
run parity
publish native
```

Không publish `quantbt-native` nếu core version tương thích chưa tồn tại hoặc chưa pass.

---

# 42. Main/dev release policy cuối cùng

```text
feature branches
→ dev
→ release branch
→ main
→ GitHub Release
→ PyPI
```

`main` là stable/releasable.

Không dùng `main` làm nơi thử package migration hoặc Rust.

Không tag từ `dev`.

Không publish từ uncommitted local tree.

Không bật Rust `auto` mặc định trong release đầu tiên.

Các release ban đầu:

```text
quantbt-engine 0.1.x
→ package hóa, Python behavior unchanged

quantbt-engine 0.2.x
→ Python Native Event performance improvements

quantbt-native 0.3.x
→ optional experimental Rust accelerator
```

Chỉ cân nhắc `auto → Rust` sau:

```text
full feature parity
randomized certification
production soak
wheel coverage
fallback test
RSS/runtime gate
```

---

# 43. Definition of Done bổ sung cho Native Event core

Ngoài Definition of Done đã có, Native Event/PyO3 chỉ hoàn thành khi:

- branch strategy được tuân thủ;
- `main` không nhận unverified refactor;
- callback timing không đổi;
- command next-bar semantics không đổi;
- same-bar command ordering không đổi;
- Python single-pass pass full replay parity;
- Rust single-pass pass full replay parity;
- public endpoint/import/result không đổi;
- score path không materialize pandas không cần thiết;
- consumed queues được giải phóng;
- terminal objects không tăng theo toàn history trong score;
- prepared trials không copy immutable market arrays;
- repeated-run RSS plateau;
- Python fallback hoạt động khi native wheel thiếu;
- native version mismatch không crash silent;
- candidate cuối luôn replay-certified;
- benchmark end-to-end chứng minh lợi ích trước khi bật Rust mặc định.
