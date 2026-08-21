# QuantBT P0–P3 Native Rust Upgrade Blueprint

> **Mục tiêu:** hoàn thiện P0–P3 cho QuantBT, đưa Rust thành backend native ngang hàng với Python, đồng thời xây một kiến trúc Rust dùng chung để mở rộng event-driven, intrabar, portfolio và arbitrage backtest mà không tạo thêm một monolith mới.
>
> **Trạng thái tài liệu:** implementation blueprint đề xuất, chưa phải mô tả những phần đã hoàn tất.
>
> **Snapshot đánh giá:** nhánh `main` được đọc ngày **2026-08-05**. Trước khi bắt đầu triển khai, phải pin lại exact commit SHA và tạo baseline từ đúng SHA đó.
>
> **Tài liệu này không sửa `upgrade/implement.md`.** Nó kế thừa các gate và bằng chứng hiện có, sau đó đề xuất lộ trình P0–P3 tiếp theo.

---

## 0. Executive summary

QuantBT đã có nền tảng tốt hơn một PyO3 proof-of-concept thông thường:

- public facade `event_driven(input_mode, profile, backend)` đã ổn định;
- Python/replay/Rust đã có parity và capability gate đáng kể;
- Rust API 0.4 đã có prepared market ownership, full session, output mask, count-only detail sink, reusable SoA step buffers, typed result và margin cache;
- Python vẫn là fallback/oracle, `backend="rust"` là explicit và fail-fast;
- native portfolio đã có Numba kernels, report reconciliation và nhiều portfolio mode;
- arbitrage đã có domain schema, sizing policy và package planning.

Tuy nhiên, để Rust trở thành **dual native backend thực sự**, phần còn lại không thể giải quyết chỉ bằng cách “viết thêm loop Rust” hoặc đổi binding khỏi PyO3. Các blocker lớn nằm ở bốn tầng:

1. **P0 — Contract/correctness:** một số execution semantics chưa được version hóa đủ chặt; có drift giữa metadata contract và matcher thực tế; intrabar/gap/liquidation/package semantics cần trace và invariant rõ ràng.
2. **P1 — Architecture/boundary:** reactive strategy vẫn callback Python từng bar; Python adapter còn giữ shadow-state gần như một engine thứ hai; endpoint/backend/reporting còn monolithic; audit đôi khi chạy Rust rồi replay lại bằng Python.
3. **P2 — Advanced Rust:** full engine vẫn dùng `Vec<OrderState>` và scan tuyến tính cho expiry, parent, OCO, cancel-all, active output và matching; full-tape output vẫn có nested vectors/clones; score facade có đường phải materialize audit; chưa có native strategy IR và scenario batch engine.
4. **P3 — Productization/debt:** source mirror, capability schema dạng boolean phẳng, package compatibility, release matrix, module ownership, generated docs/tests và performance governance cần hoàn thiện trước khi `auto` có thể chọn Rust.

Thứ tự bắt buộc:

```text
P0: khóa semantics + trace + invariants
  ↓
P1: tách planner/backend/result + giảm Python/Rust boundary
  ↓
P2: tối ưu data structure, output, strategy IR, batch, portfolio/package core
  ↓
P3: dọn debt, đóng ABI/package/release, promote auto theo workload
```

Không được đảo thứ tự để lấy benchmark đẹp trước rồi mới sửa semantics.

---

## Navigation

- [Nguồn và phạm vi đánh giá](#1-nguồn-đã-đọc-và-phạm-vi-đánh-giá)
- [Chẩn đoán trạng thái hiện tại](#2-chẩn-đoán-trạng-thái-hiện-tại)
- [Kiến trúc đích](#3-kiến-trúc-đích)
- [Definition of Done toàn chương trình](#4-definition-of-done-toàn-chương-trình)
- [P0 — Correctness, semantics và certification](#p0--correctness-semantics-và-certification)
- [P1 — Endpoint và Python–Rust boundary](#p1--tái-kiến-trúc-endpoint-và-pythonrust-boundary)
- [P2 — Advanced Rust optimization](#p2--advanced-rust-optimization-và-native-execution-architecture)
- [P3 — Technical debt và productization](#p3--technical-debt-package-productization-và-promotion-governance)
- [Master implementation sequence](#5-master-implementation-sequence)
- [Target repository structure](#6-target-repository-structure-after-p0p3)
- [Public API shape](#7-public-api-shape-after-migration)
- [Test và CI contract](#8-test-and-ci-command-contract)
- [Benchmark report format](#9-benchmark-report-format)
- [Architecture invariants](#10-architecture-invariants-that-must-remain-true)
- [Risk register](#11-risk-register-và-mitigation)
- [Những việc không nên làm](#12-những-việc-không-nên-làm)
- [Final acceptance matrix](#15-final-acceptance-matrix)
- [Immediate implementation backlog](#17-immediate-implementation-backlog)

---

## 1. Nguồn đã đọc và phạm vi đánh giá

Các file/tài liệu chính dùng làm baseline:

- [`upgrade/implement.md`](https://github.com/BobbyAxerol/quantbt/blob/main/upgrade/implement.md)
- [`src/quantbt/endpoint.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/endpoint.py)
- [`src/quantbt/backends/native_event.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/backends/native_event.py)
- [`src/quantbt/backends/_native_event_rust.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/backends/_native_event_rust.py)
- [`src/quantbt/core/event.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/event.py)
- [`src/quantbt/core/execution_contract.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/execution_contract.py)
- [`src/quantbt/core/market_tape.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/market_tape.py)
- [`src/quantbt/core/order_compiler.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/order_compiler.py)
- [`src/quantbt/core/native_event_parity.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/native_event_parity.py)
- [`src/quantbt/core/native_event_capabilities.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/native_event_capabilities.py)
- [`src/quantbt/backends/native_portfolio.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/backends/native_portfolio.py)
- [`src/quantbt/core/portfolio.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/portfolio.py)
- [`src/quantbt/core/arbitrage.py`](https://github.com/BobbyAxerol/quantbt/blob/main/src/quantbt/core/arbitrage.py)
- [`rust/native_event/src/full.rs`](https://github.com/BobbyAxerol/quantbt/blob/main/rust/native_event/src/full.rs)
- [`rust/native_event/src/lib.rs`](https://github.com/BobbyAxerol/quantbt/blob/main/rust/native_event/src/lib.rs)
- [`pyproject.toml`](https://github.com/BobbyAxerol/quantbt/blob/main/pyproject.toml)
- [`rust/native_event/Cargo.toml`](https://github.com/BobbyAxerol/quantbt/blob/main/rust/native_event/Cargo.toml)
- [`benchmarks/`](https://github.com/BobbyAxerol/quantbt/tree/main/benchmarks)

Các nhận xét trong tài liệu được gắn một trong ba loại:

- **Confirmed:** nhìn thấy trực tiếp trong code hiện tại.
- **Must prove:** chưa khẳng định là bug, nhưng phải có test/invariant trước khi promote Rust.
- **Proposed:** kiến trúc hoặc tối ưu đề xuất.

---

## 2. Chẩn đoán trạng thái hiện tại

### 2.1 Những phần đang đúng hướng

1. **Python fallback chưa bị xóa.** Đây là quyết định đúng. Python/replay phải tiếp tục tồn tại làm oracle, fallback và reference implementation dễ đọc.
2. **Explicit Rust fail-fast.** Không silent fallback khi user yêu cầu `backend="rust"` là policy đúng và phải giữ nguyên.
3. **Prepared market ownership.** Rust đã copy market tape một lần vào `FullPreparedMarketCore` và dùng `Arc<FullMarketData>` cho session; đây là nền tốt cho batch/scenario reuse.
4. **Output mask/count-only sink.** Score không bắt buộc phải tạo fill/event rows trong Rust core; hướng này đúng.
5. **Parity ở observable artifacts.** `native_event_parity.py` đã so numeric arrays, fills, events và fingerprint; đây là nền để mở rộng thành canonical execution trace.
6. **Strict market tape riêng.** `market_tape.py` không dùng permissive legacy preprocessing cho execution-certified paths; đây là separation đúng.
7. **Portfolio và arbitrage domain đã tồn tại.** Không cần phát minh lại public schema từ đầu; cần kéo execution/account/risk primitives chung xuống pure Rust.

### 2.2 Confirmed findings cần giải quyết

#### A. Contract `next_open` đang không khớp matcher thực tế

`ExecutionContract.event_lifecycle()` khai báo:

```text
signal_phase       = BAR_CLOSE
entry_fill_phase   = NEXT_OPEN
market_fill_policy = NEXT_OPEN
```

Nhưng Python `_engine_event_v2`, Python reactive session và Rust `FullSession::fill_price()` đều dùng **close của bar thực thi** cho market order. Reactive command phát ở close bar `t`, được retime sang bar `t+1`, rồi market order fill ở **close bar `t+1`**, không phải open `t+1`.

Rust market tape đã có `opens`, nhưng `fill_price()` không dùng nó. Đây là **contract drift đã xác nhận**, không chỉ là khả năng.

Cách xử lý đúng không phải âm thầm đổi matcher:

- đóng băng hành vi hiện tại thành contract legacy có tên rõ ràng, ví dụ `event_lifecycle_v2_next_bar_close`;
- thêm contract mới `event_lifecycle_v3_next_open` dùng open/gap policy thực sự;
- kết quả cũ phải reproducible bằng contract cũ;
- `event_lifecycle_v2` alias chỉ được deprecate sau khi manifest/migration test đầy đủ.

#### B. Rust reactive vẫn là một vòng Python–Rust per bar

`RustReactiveSessionAdapter` chạy một Rust transition mỗi bar, sau đó:

- đọc result qua PyO3;
- copy/update Python arrays;
- dựng `pd.Timestamp`;
- dựng positions dict;
- loop fill/event/active rows;
- dựng Python dataclasses;
- gọi Python strategy;
- compile/quantize command trong Python;
- gọi Rust ở bar kế tiếp.

Do đó PyO3 không phải nguyên nhân duy nhất. Control plane và strategy state machine vẫn thuộc Python.

#### C. Adapter Rust giữ shadow-state lớn

Adapter hiện giữ các cấu trúc Python như:

```text
scheduled
pending
orders
fills/events
fills_by_bar/events_by_bar
current_pos/equity
paths fee/funding/margin/turnover
_commands_by_id
active snapshots
online score state
```

Trong khi Rust cũng đang giữ lifecycle/accounting state. Đây là duplication về ownership, memory và logic adaptation.

#### D. Rust full engine còn nhiều scan O(number_of_orders)

Trong `full.rs`, các operation sau vẫn scan `self.orders`:

- GTD expiry;
- `CANCEL_ALL`;
- parent child activation;
- OCO sibling cancellation;
- matching active orders;
- active-order output;
- compaction/remap.

`id_to_slot` giúp direct lookup theo ID, nhưng relationship/lifecycle indexes chưa đầy đủ.

#### E. Order storage chưa phải generation-safe arena

Current shape là:

```rust
orders: Vec<OrderState>
id_to_slot: HashMap<i64, usize>
```

Compaction tạo vector/map mới khi terminal ratio đủ lớn. Kế hoạch trước có nói đến free list, generation-safe handle và indexed lifecycle, nhưng code snapshot hiện tại chưa đạt kiến trúc đó.

#### F. Full output vẫn materialize nested rows và clone vị trí

Current full step/result có:

```rust
fills: Vec<Vec<f64>>
events: Vec<Vec<i64>>
active_orders: Vec<Vec<f64>>
positions: self.positions.clone()
```

Full-tape audit còn có nguy cơ clone position vector theo bar và giữ nested vectors trước khi chuyển sang Python. SoA buffers có tồn tại nội bộ, nhưng compatibility row materialization vẫn nằm gần hot boundary.

#### G. Một score facade của Rust đang chạy audit projection

`run_compiled_tape_score()` ở Python-side Rust branch gọi `runner.run_tape_audit()` để lấy dense equity/position arrays rồi tính metrics bằng Python. Đây là behavior hợp lệ cho compatibility, nhưng không phải scalar score fast path. Tên/API/gate phải tách rõ:

- `score_scalar_native()` — Rust online metrics, scalar output;
- `score_dense_compat()` — dense arrays, compatibility cost;
- `audit()` — full lifecycle.

#### H. Endpoint/backend đang quá lớn

Ở snapshot được đọc:

- `endpoint.py` khoảng 4.4k dòng;
- `native_event.py` khoảng 5k dòng;
- `_native_event_rust.py` khoảng 2.1k dòng;
- `full.rs` khoảng 1.5k dòng.

Kích thước không tự động là bug, nhưng ở đây mỗi file đang trộn nhiều responsibility: configuration resolution, preparation, matching, reactive orchestration, parity, result adaptation, reporting và compatibility.

#### I. Capability model dạng boolean chưa diễn đạt đủ semantics

`market=true`, `fok=true`, `multi_symbol=true` không nói rõ:

- market fill ở open hay close;
- FOK dưới infinite bar liquidity hay volume-cap model;
- stop gap policy nào;
- partial fill có hay không;
- portfolio margin hay gross cross-margin;
- package atomicity chỉ là bar-level simulation hay venue atomicity.

Dual backend production cần **versioned semantic capabilities**, không chỉ feature booleans.

### 2.3 Must-prove risks

Các mục dưới đây không nên gọi là bug trước khi test, nhưng phải nằm trong P0 gate:

- same-bar stop-loss/take-profit ambiguity;
- stop-limit trigger/touch path khi cả high và low đều xuyên qua level;
- open gap qua stop/limit;
- children activated sau parent fill có được fill cùng bar không, đặc biệt khi child đứng trước parent trong insertion order;
- liquidation dùng tổ hợp worst high/low của nhiều symbol cùng bar;
- funding và liquidation sequencing;
- reduce-only cap và reversal;
- replace alias giữ target ID trỏ sang replacement;
- cancel/amend command đang dùng terminal status `FILLED` như command outcome, dễ bị hiểu nhầm là order fill;
- FOK/IOC semantics khi không có volume/partial fill model;
- liquidation hiện có thể zero equity/position mà thiếu liquidation fill/fee attribution;
- exact handling của last bar, command phát trong `finalize`, duplicate timestamp, timezone và missing funding;
- parity hiện so observable surface nhưng chưa chắc bao phủ mọi internal transition và reason code.

---

## 3. Kiến trúc đích

### 3.1 Nguyên tắc

1. **Python và Rust dùng chung semantic contract**, không copy domain rule độc lập mà không có generated schema/conformance corpus.
2. **Pure Rust core không import PyO3.** PyO3 chỉ là adapter ở ngoài cùng.
3. **Rust là backend hoàn chỉnh**, không phải một matcher nằm dưới một Python engine giữ shadow-state.
4. **Python vẫn là first-class backend**, oracle và fallback; không bị biến thành compatibility-only dead code.
5. **Một run chỉ có một owner cho mutable execution state.** Chọn Python hoặc Rust, không cả hai.
6. **Output theo profile.** Score, research và audit là ba retention contracts khác nhau.
7. **Parallelism theo scenario/fold**, không phá tính tuần tự của một event timeline.
8. **Version semantics trước version package.** Contract/fill/accounting/trace schema đều phải có version/fingerprint.
9. **Portfolio và arbitrage dùng chung account/order/risk primitives**, không fork một engine mới.

### 3.2 Sơ đồ tổng thể

```text
                           Public Python API
                    QuantBTEndpoint / PreparedRunner
                                   |
                                   v
                       ExecutionPlan Resolver
        -------------------------------------------------
        | contract | input | output | risk | capabilities |
        -------------------------------------------------
                                   |
                     Prepared Market / Instruments
                                   |
              +--------------------+--------------------+
              |                                         |
              v                                         v
        PythonBackend                              RustBackend
    reference + fallback                     pure Rust execution core
              |                                         |
              +--------------------+--------------------+
                                   |
                          RawEngineResult
                  scalar | compact | full audit trace
                                   |
                          Result Adapter Layer
                                   |
                 BacktestResultV2 / pandas / reports
```

### 3.3 Rust workspace đề xuất

Không nên tách quá nhiều micro-crate ngay ngày đầu. Bắt đầu bằng năm crate có boundary rõ:

```text
rust/
  Cargo.toml                      # workspace
  crates/
    quantbt-domain/               # IDs, enums, contracts, trace schema, errors
    quantbt-engine/               # market, orders, matching, account, risk,
                                  # portfolio target execution, package execution
    quantbt-strategy-ir/          # validated execution program / bytecode
    quantbt-batch/                # scenario/fold runner, optional Rayon
    quantbt-py/                   # PyO3 + NumPy conversion only
```

Module bên trong `quantbt-engine`:

```text
src/
  market/
    tape.rs
    clock.rs
    validation.rs
  order/
    arena.rs
    command.rs
    indexes.rs
    lifecycle.rs
  matching/
    bar_fill.rs
    priority.rs
    ambiguity.rs
  account/
    ledger.rs
    position.rs
    fee.rs
    funding.rs
    margin.rs
    liquidation.rs
  portfolio/
    target.rs
    rebalance.rs
    exposure.rs
    attribution.rs
  package/
    plan.rs
    preflight.rs
    commit.rs
    ledger.rs
  output/
    requirements.rs
    score.rs
    compact.rs
    audit.rs
  session.rs
```

Sau khi profiling chứng minh compile boundary hoặc ownership cần tách, `portfolio`/`package` có thể thành crate riêng. Không tách chỉ để đẹp cây thư mục.

### 3.4 Python module đích

```text
src/quantbt/
  api/
    endpoint.py                   # facade mỏng
    profiles.py
  planning/
    execution_plan.py
    resolver.py
    capabilities.py
  preparation/
    market.py
    instruments.py
    commands.py
    cache.py
  backends/
    base.py
    event/
      python_backend.py
      rust_backend.py
      reactive.py
      static.py
    portfolio/
      python_backend.py
      rust_backend.py
  native/
    bridge.py                     # import/probe/handshake
    conversions.py
    errors.py
  certification/
    trace.py
    parity.py
    invariants.py
    corpus.py
  results/
    raw.py
    adapters.py
    pandas.py
  reporting/
    ...
```

`QuantBTEndpoint` vẫn giữ import/public methods cũ, nhưng method body chỉ:

1. resolve plan;
2. prepare/reuse inputs;
3. select backend;
4. execute;
5. adapt/store result.

### 3.5 Các object contract chung

#### ExecutionPlan

```python
@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    plan_version: str
    contract_id: str
    input_mode: Literal["orders", "python_strategy", "strategy_ir", "targets", "package"]
    backend_request: Literal["auto", "python", "rust"]
    backend_resolved: Literal["python", "rust"]
    profile: Literal["optimize", "research", "audit"]
    output: OutputPlan
    account: AccountPlan
    instruments: InstrumentPlan
    execution: ExecutionPolicy
    required_capabilities: CapabilityRequirement
    deterministic_seed: int | None
```

Plan phải immutable và serializable. Mọi alias/legacy option được resolve trước khi backend chạy.

#### PreparedRun

```python
@dataclass(frozen=True, slots=True)
class PreparedRun:
    market: PreparedMarketTape
    instruments: PreparedInstrumentTable
    plan: ExecutionPlan
    native_handle: object | None
    signature: str
```

#### EngineResult

```text
ScalarResult   : metrics/counters/final state only
CompactResult  : equity + selected paths + compact ledgers
AuditResult    : canonical trace + full paths + terminal states
```

Public `BacktestResultV2` được dựng ở result adapter, không trong kernel.

### 3.6 Backend selection đích

`auto` không có nghĩa “luôn Rust”. Nó phải chọn theo workload và evidence:

| Workload | Python | Rust | Auto sau certification |
|---|---:|---:|---|
| arbitrary Python callback mỗi bar | canonical | supported compatibility | chọn backend có benchmark tốt hơn; thường Python cho đến khi boundary đủ nhẹ |
| static compiled command tape | supported | preferred | Rust |
| strategy IR / signal tape + native execution program | reference | preferred | Rust |
| score batch nhiều parameter sets | fallback | preferred | Rust |
| full audit nhỏ, cần Python objects ngay | supported | supported | theo threshold |
| portfolio target matrix | current native/Numba | Rust sau parity | Rust khi certified |
| arbitrage package | Python reference | Rust sau package parity | Rust khi certified |

Rust được gọi là dual backend khi:

- explicit install hoạt động từ public wheel;
- cùng public contract;
- cùng trace semantics;
- explicit Rust fail-fast;
- `auto` có thể chọn Rust ít nhất cho static/IR/batch workloads;
- Python vẫn chạy độc lập khi native wheel không có.

---

## 4. Definition of Done toàn chương trình

### 4.1 Correctness

- Mỗi run có `contract_id`, `contract_fingerprint`, `trace_schema_version`, `backend_api_version`.
- Discrete lifecycle trace Python/Rust exact-match.
- Numeric accounting dùng `rtol=0`; tolerance mặc định không lớn hơn baseline hiện tại trừ khi có ADR giải thích.
- Không có semantic fallback ẩn.
- Market fill/gap/intrabar/liquidation/package policy được version hóa.
- Portfolio/arbitrage reconciliation pass.

### 4.2 Performance

- Static/IR/batch paths chỉ có O(1) PyO3 calls trên mỗi run/batch.
- Prepared market không copy lại theo trial.
- Score không materialize pandas, Python fills/events, dense audit paths.
- Repeated-run RSS plateau; cache có budget và release API.
- Rust gate đo end-to-end, không dùng kernel-only để quảng bá callback workload.

### 4.3 Architecture

- Mutable execution state chỉ thuộc một backend.
- Pure Rust engine không phụ thuộc Python/PyO3.
- Endpoint facade không chứa domain loop.
- Reporting không chạy trong execution kernel.
- Portfolio/package dùng chung account/order/trace primitives.

### 4.4 Package/release

- `quantbt-engine[native]` cài được core + compatible native wheel.
- clean install matrix pass trên các CPython được support.
- runtime handshake từ chối mismatch.
- native wheel có SBOM/checksum/provenance.
- `auto` promotion theo workload và có rollback flag.

---

# P0 — Correctness, semantics và certification

P0 là gate tuyệt đối. Không tối ưu data structure hoặc promote backend trước khi P0 pass. Mỗi phase P0 phải tạo fixture/trace trước hoặc cùng commit với implementation.

## P0.0 — Pin baseline và phân loại contract

### Mục tiêu

Tạo một baseline không thể tranh cãi cho hành vi hiện tại, bao gồm cả behavior đúng, legacy behavior và known discrepancy.

### Việc cần làm

1. Pin exact commit SHA của `main` làm `p0_baseline_sha`.
2. Chạy và archive:
   - full Python/replay/native-event suite;
   - Rust installed-wheel suite;
   - Grid long-only/long-short;
   - static low/high-churn score/audit;
   - portfolio reconciliation;
   - arbitrage package audit.
3. Lưu machine-readable manifest:

```json
{
  "baseline_sha": "...",
  "python": "3.12.x",
  "numpy": "...",
  "numba": "...",
  "rustc": "...",
  "native_api": "0.4",
  "contract_ids": ["..."],
  "capability_fingerprint": "...",
  "market_fixture_hashes": {"...": "..."},
  "command_fixture_hashes": {"...": "..."}
}
```

4. Tạo taxonomy:
   - `CERTIFIED_CURRENT`: behavior hiện tại đã có parity và sẽ giữ;
   - `LEGACY_FROZEN`: behavior phải reproducible nhưng không dùng cho thiết kế mới;
   - `UNSPECIFIED`: đang phụ thuộc implementation, cần contract mới;
   - `KNOWN_DRIFT`: metadata/docs không khớp implementation;
   - `FUTURE`: chưa support.

### File đề xuất

```text
docs/contracts/baseline_manifest.json
docs/contracts/contract_registry.md
tests/corpus/p0_baseline/
benchmarks/native_event/results/p0_baseline/
```

### Gate

- Baseline chạy từ clean environment.
- Mọi fixture có hash.
- Không sửa execution logic trong phase này.
- Known drift `next_open`/actual next-close được ghi rõ, không “fix” lẫn vào snapshot commit.

---

## P0.1 — Version hóa event clock và bar timeline

### Vấn đề hiện tại

Tên contract chưa đủ để quyết định chính xác:

- callback quan sát bar nào;
- command có hiệu lực khi nào;
- market fill dùng open hay close;
- expiry chạy trước hay sau command;
- funding/liquidation chạy ở phase nào;
- child activation có thể match cùng bar không;
- snapshot được lấy trước hay sau post-order liquidation.

### Thiết kế đích

Tạo một `EventClockContract` serializable, không chỉ một vài enum rời:

```python
@dataclass(frozen=True, slots=True)
class EventClockContract:
    contract_id: str
    contract_version: int
    bar_timestamp_semantics: Literal["open", "close"]
    observation_phase: Literal["bar_open", "bar_close", "post_execution"]
    command_activation_phase: Literal["same_bar", "next_bar_open", "next_bar_close"]
    mark_phase: str
    intrabar_liquidation_phase: str
    funding_phase: str
    expiry_phase: str
    command_phase: str
    matching_phase: str
    relationship_phase: str
    post_order_liquidation_phase: str
    snapshot_phase: str
    last_bar_policy: str
```

Rust dùng mirror type generated từ cùng schema hoặc fixture contract.

### Default legacy sequence cần freeze

Đối với behavior native-event v2 hiện tại, trace phase phải mô tả đúng thứ tự đang chạy:

```text
BAR_START
  1. mark position bằng close[t] - close[t-1]
  2. evaluate intrabar liquidation bằng high/low của bar t
  3. apply funding nếu funding event
  4. evaluate close-margin liquidation sau funding
  5. expire GTD
  6. apply commands effective tại bar t
  7. match active orders bằng OHLC/close policy
  8. activate parent children / cancel OCO theo fill order
  9. evaluate post-order liquidation
 10. record bar state
 11. expose post-bar callback context
BAR_END
```

Đây là freeze behavior, không phải khẳng định sequence này là venue-exact.

### Contract migration bắt buộc

Tạo ít nhất hai contract:

```text
event_lifecycle_v2_next_bar_close
    current behavior, reproducibility contract

event_lifecycle_v3_next_open
    command phát ở close t, market fill tại open t+1,
    gap policy thực sự dùng opens
```

Không đổi implementation của v2 để làm tên cũ “đúng”. V3 là route mới có parity riêng.

### Bar 0 và last bar

Phải test rõ:

- `initialize(context0)` chạy trước hay sau `on_bar_close(context0)`;
- cả hai batch command đi tới bar 1 theo thứ tự nào;
- command effective bar 0 có hợp lệ với explicit tape hay không;
- strategy finalization command sau bar cuối bị ignore, reject hay emit out-of-tape trace;
- `close_on_last_bar` có tạo fill thật, fee thật và trace thật hay chỉ sửa position path;
- tape 0 bar/1 bar behavior.

### Multi-symbol clock

Với aligned OHLC matrix, một bar là một logical timestamp. Phải định nghĩa:

- command priority giữa symbols;
- margin check theo sequence hay package;
- liquidation worst-price aggregation;
- funding events khác nhau theo symbol cùng timestamp;
- tie-break bằng `sequence_no`, không phụ thuộc hash-map iteration.

### Tests

```text
test_event_clock_bar0_initialize_order
test_event_clock_callback_observes_post_bar_state
test_event_clock_next_bar_close_legacy
test_event_clock_next_open_v3
test_event_clock_finalize_outside_tape
test_event_clock_expiry_before_commands
test_event_clock_funding_before_matching
test_event_clock_post_order_liquidation
test_multisymbol_same_timestamp_sequence
```

### Gate

- Mọi trace row có `bar`, `timestamp_ns`, `phase`, `sequence`.
- Python/Rust phase order exact-match.
- V2 result cũ không drift.
- V3 open fill có dedicated fixtures và không masquerade thành V2.

---

## P0.2 — Fill policy, gap policy và intrabar ambiguity

### Mục tiêu

Biến fill decision từ các `if high/low` phân tán thành một pure function có reason code và ambiguity diagnostics.

### API đích

Python oracle:

```python
FillDecision decide_bar_fill(
    order: WorkingOrder,
    bar: BarView,
    policy: BarFillPolicy,
) -> FillDecision
```

Rust:

```rust
pub fn decide_bar_fill(
    order: &WorkingOrderView,
    bar: BarView,
    policy: &BarFillPolicy,
) -> FillDecision
```

`FillDecision`:

```text
matched
fill_price
triggered
ambiguous
ambiguity_code
liquidity_assumption
price_reason
path_assumption
```

### Policy cần version hóa

#### Market

- same close;
- next close legacy;
- next open;
- open plus slippage;
- optional volume/participation model sau này.

#### Limit

Phải chọn rõ khi open xuyên qua limit:

- conservative fill tại limit;
- price improvement tại open;
- reject impossible nếu no-liquidity model yêu cầu.

#### Stop-market

Current code fill tại trigger ± slippage khi high/low touch, kể cả open đã gap tệ hơn trigger. Contract mới phải support:

```text
OPEN_WORSE_THAN_TRIGGER:
    buy  -> max(open, trigger) + slippage policy
    sell -> min(open, trigger) - slippage policy

TRIGGER_PRICE_LEGACY:
    giữ behavior hiện tại
```

#### Stop-limit

Không đủ điều kiện chỉ bằng:

```text
buy: high >= trigger AND low <= limit
```

vì không biết trigger xảy ra trước hay limit touch. Phải dùng same-bar path policy:

- `OHLC_PATH`;
- `OLHC_PATH`;
- `CONSERVATIVE`;
- `REJECT_AMBIGUOUS`;
- `LOWER_TIMEFRAME_REQUIRED`;
- legacy unordered range behavior.

#### Multiple contingent orders

Khi SL và TP cùng touch:

- stop-first;
- TP-first;
- conservative adverse-first;
- path-based;
- ambiguous reject/flag.

### Priority

Mỗi fill candidate phải có deterministic key:

```text
(bar, phase_priority, activation_sequence, order_sequence, tie_breaker)
```

Không dùng address, slot index sau compaction hoặc hash iteration làm priority.

### Golden matrix tối thiểu

| Case | Buy/Sell | Open | High/Low | Expected |
|---|---|---:|---:|---|
| market next-open | both | normal | any | fill open ± slip |
| market legacy next-close | both | normal | any | fill close ± slip |
| limit touched intrabar | both | not gap | touch | fill limit |
| favorable limit gap | both | beyond limit | any | policy-specific |
| adverse stop gap | both | beyond trigger | any | open-worse policy |
| stop touch no gap | both | normal | trigger touch | trigger/slip |
| stop-limit trigger then limit | both | path known | both | fill |
| stop-limit limit then trigger | both | path known | both | no fill until later |
| SL + TP same bar | long/short | any | both touch | contract-specific |
| child activated same bar | both | any | child touch | sequence-specific |

### Tests

- table-driven Python tests;
- same fixture serialized sang Rust unit tests;
- randomized OHLC satisfying invariants;
- monotonic metamorphic test: widening high/low không được biến một unambiguous fill thành impossible mà không có policy reason;
- gap policy tests dùng `opens`, chứng minh opens thực sự được đọc.

### Gate

- Không còn fill rule duplicated giữa Python reactive, Numba event-v2 và Rust full mà thiếu shared fixture.
- Mọi ambiguous case có explicit code.
- Audit metadata ghi policy ID.
- Capability không chỉ ghi `stop_limit=true`; phải ghi semantic policy versions.

---

## P0.3 — Order lifecycle state machine

### Vấn đề

Current implementation dùng status code cho cả command terminal outcome và working order state. Ví dụ cancel/amend command có thể mang `FILLED` để biểu diễn command đã thực thi, nhưng tên dễ bị hiểu là order đã trade.

### Thiết kế đích

Tách ba khái niệm:

```text
CommandOutcome:
    ACCEPTED | REJECTED | NOOP | OUTSIDE_TAPE

OrderStatus:
    CREATED | WAITING_PARENT | ACTIVE | PARTIALLY_FILLED |
    FILLED | CANCELED | EXPIRED | REJECTED | LIQUIDATED

LifecycleEventKind:
    PLACE | ACTIVATE | AMEND | REPLACE | CANCEL | EXPIRE |
    FILL | REJECT | LIQUIDATE | PACKAGE_COMMIT | PACKAGE_ABORT
```

Dù partial fill chưa public, state machine nên dự phòng status và remaining quantity; capability vẫn để false cho đến khi implementation/gate pass.

### Transition table

Tạo machine-readable table, ví dụ YAML/JSON:

```yaml
- action: PLACE
  from: NONE
  guard: valid_order
  to: ACTIVE_OR_WAITING
  outcome: ACCEPTED
- action: CANCEL
  from: [ACTIVE, WAITING_PARENT]
  to: CANCELED
  outcome: ACCEPTED
- action: CANCEL
  from: [FILLED, CANCELED, EXPIRED, REJECTED]
  to: SAME
  outcome: REJECTED_UNKNOWN_OR_TERMINAL
```

Generate test cases từ table cho cả Python/Rust.

### ID và replacement semantics

Phải quyết định, version hóa và test:

- `order_id` unique toàn run hay có thể reuse sau terminal;
- replace giữ original client ID như alias hay bắt buộc new ID;
- target ID sau replace trỏ replacement bao lâu;
- parent ID trỏ order lineage hay exact generation;
- duplicate PLACE ID reject hay replace;
- integer code overflow/negative sentinel.

Khuyến nghị:

- external `OrderId` unique trong run;
- internal `OrderHandle(slot, generation)`;
- replacement có new handle và `replaces_handle` link;
- alias behavior legacy giữ ở compatibility translator, không dùng trong core relationship.

### Parent/child

Phải test:

- activate on parent first fill;
- activate on parent full fill;
- parent reject/cancel/expire;
- child placed trước parent;
- parent ID unknown;
- nested child depth;
- child activated sau matching cursor đã đi qua;
- same-bar child fill policy.

### OCO

Phải test:

- first fill cancels all siblings exact sequence;
- sibling đã terminal;
- multiple fills trong cùng bar;
- group reused;
- parent-child + OCO kết hợp;
- cancellation emits one event/sibling và group summary nếu cần.

### TIF

- GTC;
- GTD exact expiry bar và timezone;
- IOC under infinite-liquidity bar model;
- FOK under infinite-liquidity bar model;
- khi thêm volume model, capability version phải đổi.

Không được quảng bá FOK như venue-exact nếu engine không có available quantity/partial fill model.

### Gate

- Generated transition tests pass Python/Rust.
- No invalid state transition trong fuzz corpus.
- Trace phân biệt command outcome và order status.
- Stable event sequence sau slot reuse/compaction.

---

## P0.4 — Accounting ledger và invariants

### Mục tiêu

Không chỉ so final equity. Mỗi bar/run phải reconcile được bằng ledger identities.

### Canonical components

```text
cash_or_collateral
realized_pnl
unrealized_pnl
fees
funding
borrow/carry
slippage_cost
liquidation_cost
position_qty
average_entry
mark_price
initial_margin
maintenance_margin
reserved_margin
available_equity
```

Current native-event mark-to-market method có thể tiếp tục dùng cho legacy contract, nhưng audit phải map được về canonical identity.

### Invariants bắt buộc

Với không có external cash flow:

```text
equity_t = initial_capital
         + cumulative_realized_pnl_t
         + unrealized_pnl_t
         - cumulative_fees_t
         - cumulative_funding_t
         - cumulative_borrow_t
         - cumulative_liquidation_cost_t
```

Per bar:

```text
equity_delta
= mark_pnl
+ realized_adjustment
- fee
- funding
- slippage_cost
- liquidation_cost
```

Position:

```text
position_after = position_before + signed_fill_qty
```

Notional/margin:

```text
abs_notional = abs(position) * mark_price * contract_size
initial_margin = model.initial_margin(...)
maintenance_margin = model.maintenance_margin(...)
available_equity = equity - initial_margin - reserved_margin
```

Portfolio:

```text
gross = sum(abs(symbol_notional))
net   = sum(symbol_notional)
long  = sum(max(notional, 0))
short = sum(max(-notional, 0))
gross = long + short
net   = long - short
```

Package:

```text
package_pnl = sum(leg_pnl) - package_level_cost
package_fee = sum(leg_fee)
```

### Average entry và reversal

Golden tests:

- scale-in same side;
- partial reduce;
- close exactly flat;
- cross through zero;
- long-to-short và short-to-long;
- fee on every fill;
- contract size khác 1;
- inverse/quanto phải reject nếu model chưa support, không dùng linear formula.

### Fee/funding semantics

Fee model phải xác định:

- maker/taker side;
- quote/base/settlement currency;
- fee timestamp;
- fee có làm margin rejection trước fill không;
- negative rebate có support không.

Funding model:

- position snapshot tại event phase nào;
- mark/index/close price nào;
- sign convention;
- multiple funding events;
- missing event policy.

### Liquidation

Current zero-equity behavior phải được version hóa, ví dụ:

```text
liquidation_model = "zero_equity_legacy"
```

Thêm model auditable:

```text
liquidation_model = "forced_close_bar_worst"
```

Model mới phải emit:

- liquidation decision event;
- per-symbol liquidation fill hoặc allocation rows;
- close price/reason;
- liquidation fee;
- realized loss;
- canceled active orders;
- residual equity.

Không được chỉ set positions/equity về zero mà audit không giải thích được delta.

### Multi-symbol intrabar liquidation

Current conservative aggregate có thể dùng adverse extreme của mỗi symbol cùng bar. Phải đặt tên rõ:

```text
multisymbol_intrabar_policy = simultaneous_worst_extremes
```

Đây là stress assumption, không phải path có thật. Thêm alternatives sau:

- per-symbol event order;
- deterministic path;
- lower timeframe tape.

### Tests

```text
test_accounting_equity_identity_every_bar
test_accounting_position_fill_identity
test_accounting_scale_reduce_reverse
test_accounting_fee_currency_policy
test_accounting_funding_sign_and_phase
test_margin_delta_before_fill
test_liquidation_legacy_zero_equity_reproducible
test_liquidation_forced_close_attribution
test_multisymbol_gross_net_identity
test_package_leg_pnl_reconciliation
```

### Gate

- Invariant checker chạy trên mọi golden scenario.
- Audit run không có unexplained residual lớn hơn tolerance.
- Liquidation có explicit trace/attribution.
- Python/Rust residual giống nhau.

---

## P0.5 — Instrument constraints và deterministic numeric policy

### Mục tiêu

Đóng contract quantity/price precision trước khi chuyển thêm logic sang Rust.

### Instrument table chuẩn

Compile `InstrumentSpec` thành contiguous table:

```text
symbol_code
venue_code
contract_type
tick_size
qty_step
min_qty
max_qty
min_notional
contract_size
price_scale
qty_scale
settlement_currency
fee_model_id
margin_model_id
```

### Quy tắc

- Không lookup bằng symbol string trong hot loop.
- Không dùng `symbols.index(symbol)` theo command.
- Quantize price và quantity cùng phase ở cả Python/Rust.
- Xác định rounding side-aware:
  - buy limit/stop;
  - sell limit/stop;
  - reduce-only;
  - target units.
- Recheck min-notional sau quantization.
- Reject reason exact-match.

### Numeric strategy

Giai đoạn đầu:

- giữ `f64` cho accounting để parity hiện tại;
- không bật fast-math;
- không dựa vào unordered reduction;
- `rtol=0` trong parity.

Giai đoạn Rust venue-exact:

- price/qty dùng integer ticks/lots khi instrument scale hợp lệ;
- monetary accumulator có thể dùng fixed-point theo settlement scale hoặc audited `f64`;
- convert ở boundary, không round nhiều lần.

Không migrate toàn bộ sang decimal trong một PR. Thêm integer tick path theo capability và fixture.

### Gate

- Python/Rust quantization exact-match.
- No per-command string lookup trong Rust path.
- Overflow/scale tests.
- Unsupported inverse/quanto/option model fail-fast.

---

## P0.6 — Canonical execution trace và replay fingerprint

### Vấn đề

Current parity helper đã tốt nhưng còn phụ thuộc shape của result objects và chưa phải một trace schema duy nhất cho mọi backend.

### Trace schema đề xuất

Mỗi row:

```text
trace_schema_version
run_id
bar
timestamp_ns
phase
sequence
event_kind
command_id
order_id
order_generation
parent_id
group_id
oco_id
package_id
symbol_code
venue_code
side
order_type
tif
qty_before
qty_delta
qty_after
price
fee
funding
position_before
position_after
equity_before
equity_after
initial_margin_after
maintenance_margin_after
command_outcome
order_status
reason_code
```

Không phải profile nào cũng materialize mọi field. Audit trace là full; compact trace có selected fields; score chỉ giữ rolling hash/counters.

### Rolling fingerprint

Trong score/research, Rust/Python có thể cập nhật hash online:

```text
hash = H(hash, normalized_event_record)
```

Điều này cho phép parity mà không giữ full rows. Audit corpus vẫn giữ full trace để debug.

### Normalization

- enums thành stable integer codes;
- timestamps ns UTC;
- strings interned;
- NaN canonicalization;
- float fields hash bằng bytes sau contract-defined normalization;
- metadata không deterministic không được vào fingerprint.

### Replay

Một `TraceReplayer` độc lập phải có thể:

- reconstruct final positions/equity từ fills/account deltas;
- verify transition order;
- verify order terminal states;
- verify package reconciliation.

Replay verifier không được gọi matcher lại; nó kiểm ledger/trace.

### Gate

- Python/Rust audit traces exact-match ở discrete fields.
- Score rolling fingerprints match audit fingerprint projection.
- Trace replayer reconstruct terminal state.
- Fingerprint stable qua process và installed wheel.

---

## P0.7 — Differential, property, model-based và fuzz testing

### Python property tests

Dùng Hypothesis để sinh:

- OHLC valid bars;
- command tapes;
- order IDs/relationships;
- funding masks;
- quantity constraints;
- multiple symbols;
- package plans.

Giới hạn generator để case nhỏ, shrink được và có deterministic seed.

### Rust property tests

Dùng `proptest` cho pure Rust core:

- arena insert/remove/reuse;
- index consistency;
- lifecycle transitions;
- accounting invariants;
- trace ordering;
- reset/reuse.

### Fuzz targets

Sau pure Rust extraction, thêm `cargo-fuzz`:

```text
fuzz_command_decoder
fuzz_lifecycle_state_machine
fuzz_order_arena_indexes
fuzz_trace_replay
fuzz_package_preflight_commit
```

Fuzzer không cần Python/PyO3.

### Model-based test

Tạo một slow Python model rất nhỏ, dễ đọc, không tối ưu. Mỗi generated action:

1. apply vào model;
2. apply vào Python engine;
3. apply vào Rust engine;
4. so trace/state.

### Metamorphic tests

- fee=0 không thể tạo fee;
- funding mask false => funding=0;
- empty command tape giữ initial equity;
- duplicate run cùng seed => identical trace;
- split tape + resume phải giống one-shot nếu contract cho phép;
- prepare cache on/off không đổi result;
- audit/compact/score output requirements không đổi domain decisions;
- batch scenario i phải giống single scenario i.

### Corpus governance

Mọi fuzz failure được minimize và commit vào:

```text
tests/corpus/regressions/<issue-id>/
```

Không chỉ thêm test code mà bỏ seed.

### Gate

- Không panic/UB.
- Không state/index invariant failure.
- Corpus chạy trong CI.
- Long fuzz job chạy scheduled/nightly; smoke corpus chạy PR.

---

## P0.8 — Portfolio correctness foundation

### Mục tiêu

Chuẩn hóa account/target/rebalance semantics trước khi port native portfolio sang Rust.

### Tách hai lớp

```text
Portfolio allocator:
    signals -> target weight/notional/units

Portfolio execution/accounting:
    target units -> accepted positions, costs, margin, PnL
```

Rust phase đầu chỉ cần thay execution/accounting. Risk parity/beta estimation có thể tiếp tục vectorized Python/Numba cho đến khi có lý do port.

### Contract cần khóa

- target observed phase;
- target effective phase;
- rebalance frequency;
- live-equity sizing;
- gross/net target;
- short policy;
- stale price policy;
- tradable mask;
- quantity constraints;
- per-symbol leverage;
- cross-margin vs isolated;
- margin rejection order khi nhiều symbols cùng rebalance;
- pro-rata scaling hay sequential accept;
- liquidation attribution.

### Atomic portfolio rebalance

Phải có policy:

```text
SEQUENTIAL_LEGACY
PRO_RATA_TO_AVAILABLE_MARGIN
ALL_OR_NONE_TARGET
REDUCE_FIRST_THEN_INCREASE
```

`REDUCE_FIRST_THEN_INCREASE` thường hợp lý hơn để giải phóng margin, nhưng không được đổi default legacy mà không version.

### Tests

- longshort, market-neutral, directional, equal-weight;
- risk parity/beta-neutral target input;
- target vs accepted reconciliation;
- stale symbol;
- one symbol rejects min-notional;
- reductions + increases cùng bar;
- cross-margin pressure;
- simultaneous liquidation;
- batch/single parity.

### Gate

- Existing `build_portfolio_domain_audit` pass.
- Rust target executor match Numba/Python reference.
- Per-symbol PnL/fee/funding sums match portfolio.
- Rejection reason deterministic.

---

## P0.9 — Arbitrage/package correctness foundation

### Mục tiêu

Biến package từ metadata/planning concept thành execution transaction có semantics rõ.

### Package state machine

```text
PLANNED
  -> PREFLIGHT_ACCEPTED | PREFLIGHT_REJECTED
  -> RESERVED
  -> COMMITTING
  -> FILLED | PARTIAL | ABORTED | COMPENSATING
  -> CLOSED
```

### Execution policies

#### ATOMIC_ALL_OR_NONE

Trong bar backtest, “atomic” chỉ có nghĩa:

- mọi leg pass preflight trên cùng logical timestamp;
- margin/cost được reserve trước;
- state mutation commit như một transaction;
- nếu một leg fail preflight thì không leg nào fill.

Không quảng bá đây là exchange atomicity ngoài đời.

#### BEST_EFFORT

- mỗi leg independent;
- package reports residual exposure;
- optional compensation/hedge action.

#### SEQUENTIAL

- leg order explicit;
- margin/state thay đổi sau từng leg;
- trace exact sequence.

#### HEDGE_AFTER_PRIMARY

- primary fill trước;
- hedge qty tính theo actual primary fill;
- failure tạo residual-risk event.

### Two-phase execution

```text
Phase 1 — Preflight, no mutation
    validate market touch/liquidity
    quantize
    calculate fees/slippage
    calculate margin/reservation
    calculate package constraints

Phase 2 — Commit
    apply fills in deterministic order
    update account/positions
    emit package + leg trace
```

### Cross-venue/time semantics

Mỗi market event cần:

```text
timestamp_ns
venue_code
venue_sequence
source_age_ns
```

Package policy phải có max staleness. Không align bằng forward-fill im lặng cho execution-certified route.

### Invariants

- all-or-none không có partial mutation;
- reserved margin release khi abort;
- package PnL bằng sum leg PnL;
- frozen hedge units không drift khi giá thay đổi;
- close package flatten exact intended units;
- rejection report luôn có policy/reason.

### Gate

- basis/calendar/funding/stat-arb/index basket fixtures.
- Python/Rust package trace parity.
- Intentional leg failure chứng minh rollback.
- Residual exposure visible ở best-effort.

---

## P0.10 — Capability, fallback và installed-wheel correctness

### Capability schema mới

Thay boolean-only bằng structured capability descriptor:

```json
{
  "native_api": "0.5",
  "trace_schema": "1.0",
  "contracts": [
    "event_lifecycle_v2_next_bar_close",
    "event_lifecycle_v3_next_open"
  ],
  "orders": {
    "types": ["market", "limit", "stop_market", "stop_limit"],
    "partial_fill": false,
    "volume_model": "infinite_bar_liquidity",
    "gap_policy": ["legacy_trigger", "open_worse_than_trigger"]
  },
  "account": {
    "margin_models": ["gross_cross"],
    "liquidation_models": ["zero_equity_legacy", "forced_close_bar_worst"]
  },
  "portfolio": {
    "target_execution": true,
    "package_atomicity": "bar_transaction"
  }
}
```

### Runtime handshake

Core và native phải so:

```text
native_api_version
minimum/maximum core protocol
contract schema fingerprint
trace schema version
command ABI version
build SHA/release version
feature set
```

Mismatch:

- explicit Rust => clear error;
- auto => fallback Python + metadata reason;
- không được import thành công rồi fail ở giữa run do schema drift có thể phát hiện trước.

### Installed-wheel matrix

Bắt đầu từ scope hiện tại:

- Linux manylinux x86-64;
- CPython 3.11, 3.12, 3.13;
- NumPy range trong core package;
- core wheel và native wheel từ same release ref;
- clean venv, no source tree;
- import + capability + parity + benchmark smoke.

Sau đó mới thêm aarch64/macOS/Windows theo demand.

### Gate

- `quantbt-engine` chạy không cần Rust.
- explicit Rust unavailable/mismatch fail-fast.
- auto fallback có diagnostics.
- clean installed-wheel parity pass.
- không claim dual package khi `native=[]` còn rỗng.

---

## P0.11 — P0 exit checklist

P0 chỉ hoàn tất khi tất cả đều đúng:

```text
[ ] exact baseline SHA + corpus archived
[ ] V2 actual next-bar-close contract frozen
[ ] V3 next-open contract implemented/tested hoặc explicitly deferred
[ ] bar timeline/phase trace exact Python/Rust
[ ] fill/gap/ambiguity policy versioned
[ ] order lifecycle transition table generated/tested
[ ] accounting invariants pass every golden fixture
[ ] liquidation attribution policy explicit
[ ] instrument quantization exact-match
[ ] canonical trace + rolling fingerprint pass
[ ] Hypothesis/proptest/corpus differential pass
[ ] portfolio target/rebalance semantics frozen
[ ] package atomic/best-effort semantics frozen
[ ] structured capability descriptor implemented
[ ] installed-wheel fail-fast/fallback matrix pass
```

Không merge P1 ownership rewrite nếu P0 trace không thể chỉ ra một divergence xảy ra ở phase/event nào.

---

# P1 — Tái kiến trúc endpoint và Python–Rust boundary

## P1 objective

P1 không nhắm tới micro-optimization. Mục tiêu là làm cho đường chạy có cấu trúc đủ sạch để P2 có thể tối ưu đúng tầng:

```text
Public API
  -> resolve một ExecutionPlan bất biến
  -> prepare market/strategy đúng một lần
  -> gọi một backend SPI thống nhất
  -> nhận RawEngineResult theo output projection
  -> adapt/report đúng một lần
```

Sau P1:

- Python và Rust là hai backend ngang hàng cùng thực hiện một contract;
- endpoint không chứa execution loop;
- backend không tự dựng report/pandas;
- Rust adapter không duy trì một bản sao lifecycle/accounting engine ở Python;
- số lượng Python↔Rust transition được đo và hiện rõ;
- static/IR/batch có thể đi một call per run, còn Python callback compatibility được nhận diện là một workload riêng;
- audit không mặc định chạy engine hai lần;
- mọi lựa chọn backend/output/profile được resolve trước khi vào hot path.

P1 phải giữ nguyên canonical trace của P0. Tách module mà làm thay đổi fingerprint phải bị coi là correctness regression.

---

## P1.0 — Freeze dependency rule trước khi tách code

### Quy tắc dependency mục tiêu

```text
quantbt.api / endpoint
        ↓
planning + validation
        ↓
backend protocol
   ↙             ↘
Python backend    Rust adapter
        ↓             ↓
pure Python core   PyO3 native module
        ↘             ↙
       RawEngineResult
              ↓
     result adapters/reporting
```

Không cho phép các dependency ngược sau:

- Rust adapter import endpoint để reuse logic;
- backend import report builders;
- report builder gọi lại execution;
- result adapter tự resolve capability/backend;
- strategy context trực tiếp chạm internal backend object;
- planner import PyO3 module chỉ để hỏi capability;
- Python backend gọi Rust cho một phần rồi vẫn tự giữ canonical account state;
- Rust adapter tự gọi replay oracle trong production path.

### Enforcement

Thêm import-boundary tests, ví dụ bằng `import-linter` hoặc test AST nhẹ:

```text
contract: quantbt.planning must not import quantbt.reporting
contract: quantbt.backends must not import quantbt.endpoint
contract: quantbt.results must not import quantbt.backends
contract: quantbt.backends.rust_adapter may import only protocol/domain/native binding
```

### Gate

- import graph được lưu thành artifact;
- circular import bằng 0;
- P0 corpus/fingerprint không đổi;
- import cold-time không regression quá budget đã freeze.

---

## P1.1 — Tách `QuantBTEndpoint` thành resolver, planner và executor

### Vấn đề hiện tại

`src/quantbt/endpoint.py` đang chịu quá nhiều trách nhiệm:

- public argument normalization;
- profile/backend selection;
- validation;
- market preprocessing;
- capability resolution;
- strategy wrapping;
- backend invocation;
- metadata;
- result/report adaptation;
- compatibility aliases;
- một số replay/audit behavior.

Một facade lớn khiến:

- cùng một validation có thể chạy nhiều lần;
- fast path khó chứng minh là không đi qua pandas/report logic;
- backend choice và output needs thay đổi giữa run;
- performance regression khó quy trách nhiệm;
- portfolio/arbitrage sẽ tiếp tục phình endpoint.

### Module tree đề xuất

```text
src/quantbt/
  api/
    event_driven.py
    portfolio.py
    arbitrage.py
    compatibility.py

  planning/
    models.py
    resolve.py
    capabilities.py
    validation.py
    fingerprints.py

  preparation/
    market.py
    instruments.py
    commands.py
    strategies.py
    cache.py

  engines/
    protocol.py
    python_event.py
    python_portfolio.py
    rust.py
    registry.py

  results/
    raw.py
    adapters.py
    metrics.py
    reports.py
    audit.py

  contracts/
    execution.py
    orders.py
    account.py
    portfolio.py
    packages.py
    generated/
```

Không cần đổi public import ngay. `src/quantbt/endpoint.py` có thể trở thành compatibility facade mỏng:

```python
class QuantBTEndpoint:
    def run(self, request: BacktestRequest) -> BacktestResult:
        plan = resolve_execution_plan(request)
        prepared = prepare_run(plan, request)
        raw = execute_prepared(plan, prepared)
        return adapt_public_result(plan, raw)
```

### `ExecutionPlan` bất biến

```python
@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    contract: ExecutionContractRef
    workload: WorkloadClass
    backend: BackendKind
    backend_reason: BackendDecisionReason
    strategy_mode: StrategyMode
    profile: RunProfile
    output: OutputRequirements
    trace: TraceRequirements
    numeric: NumericPolicy
    market_layout: MarketLayout
    account_model: AccountModelRef
    capability_fingerprint: str
    plan_fingerprint: str
```

`ExecutionPlan` phải chứa kết quả đã resolve, không chứa option “auto” mơ hồ. Ví dụ:

```text
request.backend = auto
plan.backend    = python
plan.reason     = PYTHON_CALLBACK_SMALL_WORKLOAD_FASTER
```

hoặc:

```text
request.backend = auto
plan.backend    = rust
plan.reason     = RUST_STATIC_TAPE_SUPPORTED_AND_PROMOTED
```

### `BacktestRequest` và `PreparedRun`

```python
@dataclass(frozen=True, slots=True)
class BacktestRequest:
    market: MarketInput
    strategy: StrategyInput
    instruments: InstrumentInput
    account: AccountInput
    config: BacktestConfig

@dataclass(slots=True)
class PreparedRun:
    market: PreparedMarket
    strategy: PreparedStrategy
    instruments: PreparedInstruments
    account: PreparedAccount
    command_tape: PreparedCommandTape | None
    cache_keys: PreparationKeys
```

`PreparedRun` được tạo một lần; backend không tự normalize lại DataFrame hay compile lại symbols.

### Migration từng bước

1. Tạo `ExecutionPlan` nhưng vẫn gọi logic cũ.
2. Snapshot plan từ mọi existing test; so metadata trước/sau.
3. Di chuyển profile/output resolution khỏi endpoint.
4. Di chuyển capability resolution khỏi backend.
5. Di chuyển preprocessing thành preparation layer.
6. Di chuyển result adaptation/reporting ra sau backend.
7. Giảm `endpoint.py` xuống facade + compatibility shims.
8. Chỉ xóa helper cũ sau khi import graph và parity pass.

### Gate

- một request chỉ có một `plan_fingerprint`;
- backend không được thay plan;
- market normalization count = 1;
- instrument normalization count = 1;
- profile/output resolution count = 1;
- P0 trace và public result parity pass.

---

## P1.2 — Thiết kế backend SPI ngang hàng

### Backend protocol

```python
class EngineBackend(Protocol):
    @property
    def descriptor(self) -> BackendDescriptor: ...

    def prepare(
        self,
        plan: ExecutionPlan,
        prepared: PreparedRun,
    ) -> "PreparedEngineSession": ...

class PreparedEngineSession(Protocol):
    def run(self, request: EngineRunRequest) -> RawEngineResult: ...
    def reset(self, reset: ResetRequest) -> None: ...
    def close(self) -> None: ...
```

`BackendDescriptor`:

```python
@dataclass(frozen=True, slots=True)
class BackendDescriptor:
    name: Literal["python", "rust"]
    implementation_version: str
    protocol_version: int
    command_abi_version: int
    result_abi_version: int
    contracts: tuple[ContractCapability, ...]
    workloads: tuple[WorkloadCapability, ...]
    build: BuildDescriptor
```

### Engine request/result không dùng pandas

```python
@dataclass(frozen=True, slots=True)
class EngineRunRequest:
    run_id: int
    seed: int | None
    parameters: ParameterVector | None
    output: OutputRequirements
    trace: TraceRequirements

@dataclass(slots=True)
class RawEngineResult:
    summary: EngineSummary
    paths: EnginePaths | None
    fills: FillBuffer | None
    events: EventBuffer | None
    active_orders: ActiveOrderBuffer | None
    positions: PositionBuffer | None
    trace: TraceBuffer | None
    diagnostics: EngineDiagnostics
```

Không cho phép:

- `pd.DataFrame` trong SPI;
- dict string-key trong hot result;
- Python dataclass per fill bắt buộc;
- report-level strings trong native core;
- backend-specific fields trôi nổi không version.

### Equal-contract requirement

Python và Rust phải cùng nhận:

- cùng `ExecutionPlan`;
- cùng prepared market/instruments;
- cùng command/strategy semantic;
- cùng output projection;
- cùng trace schema;
- cùng public error taxonomy.

Không bắt buộc cùng internal algorithm, nhưng observable trace/result phải theo contract.

### Backend registry

```python
BACKENDS: Mapping[BackendKind, EngineBackendFactory]
```

Registry không import native module ngay khi import core. Rust descriptor được lazy-load khi:

- explicit Rust;
- `auto` cần hỏi native availability;
- capability diagnostics được user yêu cầu.

### Gate

- Python and Rust backend contract tests chạy từ cùng fixture factory;
- backend-specific test chỉ dành cho internal performance/ABI;
- public endpoint không có `if backend == "rust"` ngoài registry/decision layer;
- explicit Rust fail-fast trước preparation đắt tiền khi capability chắc chắn thiếu.

---

## P1.3 — Resolve `OutputRequirements` một lần

### Vấn đề

Profile, report level, audit, score requirements và strategy context requirements có thể khiến engine materialize dữ liệu không cần. Boolean rải rác làm fast path dễ vô tình bật fills/events/positions.

### Model đề xuất

```python
@dataclass(frozen=True, slots=True)
class OutputRequirements:
    scalar_metrics: MetricMask
    dense_paths: PathMask
    fill_detail: DetailLevel
    event_detail: DetailLevel
    active_order_detail: DetailLevel
    final_positions: PositionProjection
    per_bar_positions: PositionProjection
    account_snapshots: SnapshotSchedule
    attribution: AttributionMask

@dataclass(frozen=True, slots=True)
class StrategyContextRequirements:
    market_fields: MarketFieldMask
    account_fields: AccountFieldMask
    position_fields: PositionFieldMask
    order_fields: OrderFieldMask
    fill_fields: FillFieldMask
    event_fields: EventFieldMask
    lookback: int
    callback_schedule: CallbackSchedule
```

`OutputRequirements` là union của:

```text
public profile needs
+ metric computation needs
+ audit/certification needs
+ strategy context needs
```

Nhưng phải phân biệt:

- dữ liệu strategy cần **trong run**;
- dữ liệu public result cần **sau run**;
- dữ liệu chỉ audit sink cần **stream**;
- dữ liệu chỉ metric online cần **aggregate**, không cần rows.

### Projection compiler

```python
projection = compile_projection(
    profile=plan.profile,
    public_output=request.output,
    strategy_requirements=prepared.strategy.requirements,
    metric_requirements=metric_registry.requirements(...),
    trace_requirements=plan.trace,
)
```

Projection được mã hóa thành bitmask/compact descriptor truyền sang Rust một lần.

### Fail closed

Nếu arbitrary Python callback không khai báo requirements:

- compatibility mode dùng conservative projection;
- diagnostics ghi rõ `CONTEXT_REQUIREMENTS_CONSERVATIVE`;
- benchmark không được so conservative callback với optimized declared callback như cùng workload;
- warning/dev tooling gợi ý khai báo requirement.

### Gate

- score static không allocate fill/event rows;
- `fills_count` vẫn đúng bằng counter online;
- context không yêu cầu positions thì không materialize positions dict;
- audit trace có thể stream mà không giữ toàn bộ rows trong memory;
- projection fingerprint nằm trong result metadata.

---

## P1.4 — Strategy context protocol: compatibility, view và projection

### Ba lớp context

#### Lớp A — Compatibility context

Giữ `NativeStrategyContext` hiện tại cho user code cũ, nhưng dựng thông qua adapter ngoài hot native core.

```python
compat = MaterializedStrategyContext.from_view(view)
commands = legacy_strategy(compat)
```

Đường này ưu tiên compatibility, không được quảng bá là native-fast.

#### Lớp B — Numeric context view

```python
class StrategyContextView(Protocol):
    bar_index: int
    timestamp_ns: int
    symbol_count: int
    def close(self, symbol_id: int) -> float: ...
    def position_qty(self, symbol_id: int) -> float: ...
    def equity(self) -> float: ...
    def iter_new_fills(self) -> FillView: ...
```

Đặc tính:

- numeric IDs thay string lookup;
- nanosecond integer thay `pd.Timestamp` trong hot path;
- array views thay dict;
- lazy property/projection;
- no copy cho immutable current-bar slices khi lifetime an toàn;
- command output viết vào writer, không trả list bắt buộc.

#### Lớp C — Native strategy runtime

Không tạo Python context. Rust IR/plugin đọc direct market/account/order state.

### Ephemeral lifetime guard

Nếu reuse cùng một context view mỗi bar để giảm allocation, phải ngăn user giữ reference rồi đọc ở bar sau:

```python
class StrategyContextView:
    _generation: int

    def _check(self) -> None:
        if self._generation != self._session.generation:
            raise StaleContextError(...)
```

Chỉ bật guard ở compatibility/debug nếu cost đáng kể; production view có documented ephemeral lifetime.

### Symbol interning

Preparation tạo:

```text
symbol string -> SymbolId(u32)
venue string  -> VenueId(u16)
instrument    -> InstrumentId(u32)
currency      -> CurrencyId(u16)
```

Không dùng `symbols.index(name)` trong per-command path. Python adapter giữ immutable maps; Rust chỉ nhận IDs.

### Callback requirements API

Ví dụ:

```python
@quantbt.strategy_requirements(
    market=("close", "high", "low"),
    account=("equity", "free_margin"),
    positions=("qty", "avg_entry"),
    fills="new_only",
    events="none",
    active_orders="ids_and_status",
    callback="every_bar",
)
def strategy(ctx, out):
    ...
```

Hoặc class attribute:

```python
class GridStrategy:
    quantbt_requirements = StrategyContextRequirements(...)
```

### Gate

- compatibility context parity pass;
- numeric view benchmark tách riêng;
- no `pd.Timestamp` per bar trên numeric path;
- no positions dict nếu không cần;
- stale context test pass;
- callback exception luôn kèm bar/timestamp/strategy ID nhưng không leak internal native object.

---

## P1.5 — Reusable command writer thay `list[OrderCommand]`

### Vấn đề

Arbitrary callback thường trả Python objects:

```python
[PlaceOrder(...), CancelOrder(...), AmendOrder(...)]
```

Sau đó adapter phải:

- inspect Python type;
- resolve symbol/string/enums;
- validate;
- quantize;
- append NumPy arrays;
- gọi PyO3.

### API mới

```python
class CommandWriter(Protocol):
    def market(
        self,
        symbol_id: int,
        side: SideCode,
        qty: float,
        *,
        client_tag_id: int = 0,
        reduce_only: bool = False,
    ) -> int: ...

    def limit(...): ...
    def stop(...): ...
    def cancel(self, order_handle: int) -> None: ...
    def amend(...): ...
    def finish(self) -> CommandBatchView: ...
```

Writer dùng preallocated SoA arrays:

```text
opcode[]
order_id[]
symbol_id[]
side[]
qty[]
limit_px[]
stop_px[]
tif[]
flags[]
parent_handle[]
oco_group[]
activate_bar[]
expire_bar[]
```

### Capacity policy

- initial capacity từ observed p95 commands per callback;
- geometric growth khi cần;
- giữ capacity qua bars/runs;
- hard safety limit theo config;
- high-water mark vào diagnostics;
- no shrink trong run;
- reset length về zero, không zero toàn buffer nếu Rust chỉ đọc range hợp lệ.

### Compatibility adapter

Legacy objects vẫn được chấp nhận:

```python
commands = legacy_strategy(ctx)
legacy_command_compiler.write(commands, writer)
```

Nhưng diagnostics ghi:

```text
command_path = legacy_objects
python_command_objects = N
command_buffer_reallocations = M
```

### Validation split

- schema/type validation: preparation/compile time khi có thể;
- contract validation động: Rust/Python engine cùng semantics;
- quantization: một implementation canonical hoặc generated conformance;
- không validate cùng một invariant ba lần ở endpoint, adapter và kernel.

### Static command tape

Nếu command schedule biết trước:

```python
prepared.command_tape = compile_command_tape(...)
```

Rust nhận tape một lần. Không đi qua callback/writer mỗi bar.

### Gate

- writer path không allocate Python command object;
- command arrays reuse qua bars;
- legacy and writer canonical command trace giống nhau;
- malformed command error code giống Python/Rust;
- command compile time được đo riêng khỏi kernel.

---

## P1.6 — Xóa Python shadow-state trong Rust adapter

### Ownership rule

Khi chạy Rust:

```text
Rust owns:
  order lifecycle
  active/pending/scheduled state
  positions
  cash/equity/PnL
  fees/funding/margin
  fills/events counters and selected detail
  run paths requested by projection

Python owns:
  public strategy object
  immutable symbol/metadata interner
  optional callback adapter/view
  final public result materialization
  optional external audit sink handle
```

Python không được duy trì “bản sao để tiện”. Nếu cần dữ liệu cho callback, Rust trả projection compact từ state authoritative.

### Cấu trúc adapter mục tiêu

```python
class RustPreparedSession:
    __slots__ = (
        "_native",
        "_plan",
        "_symbols",
        "_strategy_adapter",
        "_context_view",
        "_command_writer",
    )

    def run(self, request):
        if self._plan.strategy_mode is STATIC_TAPE:
            return self._native.run_tape(...)
        if self._plan.strategy_mode is NATIVE_IR:
            return self._native.run_ir(...)
        return self._run_python_callback_compat(request)
```

Không còn:

```text
Python pending orders map
Python active order lifecycle state
Python equity/position accounting arrays
Python fill/event history duplicate
Python online metric state nếu Rust đã aggregate
```

### Projection from native state

Per callback result chỉ gồm primitive compact data yêu cầu:

```text
bar_index
account scalar array
position changed rows / requested full view
new fill range
new event range
active order changed rows / requested snapshot
wake reason
```

Không gửi toàn bộ state mỗi bar nếu strategy chỉ cần equity và một symbol position.

### Delta protocol

Mỗi native step trả cursors:

```text
fill_begin, fill_end
event_begin, event_end
order_delta_begin, order_delta_end
position_delta_begin, position_delta_end
```

Python context view đọc range mới. Audit buffer vẫn ở Rust hoặc stream sink.

### Result ownership

Sau `finish()`:

- native buffers chuyển ownership/view sang result wrapper;
- session không reset/reuse buffer cho đến khi result owner release hoặc buffer được moved out;
- nếu cần reuse ngay, copy chỉ đúng requested outputs;
- lifetime contract phải test bằng GC stress.

### Migration

1. Gắn counter cho từng shadow structure và nơi đọc.
2. Xác định data nào thật sự cần cho callback/public result.
3. Thêm native projection/delta API.
4. Chuyển từng consumer sang projection.
5. Xóa shadow structure khi read count = 0.
6. Chạy memory plateau + canonical trace.

### Gate

- authoritative state count = 1;
- Python adapter không tự tính cash/equity/margin;
- Python adapter không tự quyết order status transition;
- callback projection bytes/bar được đo;
- long-run RSS plateau;
- final result/fingerprint không đổi.

---

## P1.7 — Giảm Python↔Rust transitions theo workload

### Không có một giải pháp duy nhất

Bốn workload cần bốn đường:

| Workload | Boundary hợp lý |
|---|---|
| Static compiled command tape | một call/run |
| Native strategy IR | một call/run |
| Sparse Python callback | một call/chunk hoặc wake-up |
| Arbitrary every-bar Python callback | một callback/bar; có thể Rust step/bar hoặc chunk-until-wake |

Không được claim rằng arbitrary Python callback đã “fully native”.

### Chunk-until-wake protocol

Cho strategy không cần callback mọi bar:

```python
result = native.run_until(
    max_bar=end,
    wake_mask=WAKE_ON_FILL | WAKE_ON_EVENT | WAKE_ON_SCHEDULED_BAR,
    scheduled_wake_bars=...,
)
```

Rust tự chạy nhiều bars cho tới khi:

- strategy-scheduled evaluation bar;
- fill/event cần callback;
- active order transition được strategy đăng ký;
- risk threshold/wake condition;
- end of tape.

Sau đó Python callback chạy một lần.

### Declarative wake schedule

```python
CallbackSchedule(
    every_n_bars=5,
    explicit_bars=array(...),
    on_fill=True,
    on_reject=True,
    on_liquidation=True,
    on_session_boundary=True,
)
```

Khi schedule không thể chứng minh an toàn, fallback every-bar.

### GIL policy

- static/IR/full batch: release GIL cho toàn native run;
- chunk-until-wake: release GIL trong mỗi native chunk;
- reacquire chỉ để gọi Python callback/materialize exception;
- không gọi Python C-API khi GIL đã release;
- expose counter `gil_reacquisitions`.

### Recommended metrics

```text
pyo3_calls
python_callbacks
gil_reacquisitions
native_bars_per_call
callback_projection_bytes
commands_per_callback
callback_ns
command_compile_ns
native_step_ns
```

### Gate

- static/IR: `pyo3_calls = O(1)` per run;
- sparse: median native bars/call đạt đúng schedule expected;
- arbitrary callback: không tạo thêm hidden callbacks;
- callback exceptions deterministic và clean session state;
- output projection không ép wake-up không cần thiết.

---

## P1.8 — Audit và replay không chạy production engine hai lần

### Vấn đề kiến trúc

Chạy Rust xong rồi bắt buộc replay Python để dựng audit/report:

- gấp đôi compute;
- che mất lợi ích Rust;
- có nguy cơ report lấy từ oracle, summary lấy từ native;
- làm khó xác định backend thật;
- khiến audit profile không phản ánh native implementation.

### Thiết kế mới

Ba mode khác nhau:

#### `audit=native_trace`

Rust/Python backend phát canonical trace theo P0. Public audit report dựng trực tiếp từ trace đó.

#### `audit=verify_against_oracle`

Sau primary run, chạy oracle độc lập và diff trace. Đây là certification/debug mode, không phải default runtime.

#### `audit=dual_run_sampled`

Production/research có thể sample một tỷ lệ nhỏ run để oracle verify, phục vụ promotion telemetry. Kết quả primary vẫn rõ ràng.

### Trace sink

```python
class AuditSink(Protocol):
    def write_chunk(self, schema_version: int, chunk: TraceChunk) -> None: ...
    def close(self, summary: TraceSummary) -> AuditArtifactRef: ...
```

Implementations:

- in-memory small run;
- chunked binary/Arrow/Parquet outside engine;
- hash-only certification;
- user callback sink.

### Metadata bắt buộc

```text
primary_backend
primary_contract
trace_schema
oracle_verified: bool
oracle_backend
oracle_diff_summary
trace_fingerprint
```

### Gate

- `audit=native_trace` chỉ chạy một engine;
- `verify_against_oracle` có timing tách primary/oracle/diff;
- report được dựng từ primary trace;
- no silent replacement of native result by oracle result;
- canonical trace round-trip pass.

---

## P1.9 — Prepared session, cache và reset semantics

### Cache layers

```text
L1 normalized input fingerprint
L2 prepared market tape
L3 prepared instruments/model tables
L4 prepared static command tape / strategy IR
L5 backend prepared session/template
```

### Cache keys

Không dùng object identity đơn giản. Key gồm:

```text
market content fingerprint
instrument table fingerprint
contract version
numeric policy
market layout version
backend protocol/build compatibility
output-independent preparation version
```

Output projection không nên phá prepared market cache, nhưng có thể cần session/result buffer riêng.

### Cache budget

```python
CachePolicy(
    max_bytes=...,
    max_entries=...,
    eviction="lru",
    pin_during_run=True,
    weak_result_owners=True,
)
```

Diagnostics:

```text
cache_hit/miss
prepared_bytes
resident_bytes
entry_count
eviction_count
reuse_count
```

### Reset contract

Phân biệt:

```text
RESET_ACCOUNT_ONLY
RESET_ACCOUNT_AND_ORDERS
RESET_SCENARIO_STATE
RESET_RESULT_BUFFERS
FULL_REBUILD
```

Không expose một `reset()` mơ hồ.

Reset phải:

- tăng generation;
- clear lengths/cursors;
- preserve capacity hợp lệ;
- preserve immutable market/instrument tables;
- reset RNG/state deterministically;
- không giữ reference strategy/result cũ;
- không giữ terminal order metadata ngoài policy.

### Thread safety

- prepared immutable market có thể share bằng `Arc`;
- mutable session không share giữa workers;
- Python wrapper đánh dấu non-thread-safe session;
- scenario batch tạo state per worker/scenario;
- cache lock không nằm trong event hot loop.

### Gate

- run–reset–rerun fingerprint giống fresh session;
- RSS plateau qua hàng nghìn reset;
- use-after-result/free test pass;
- no cache key collision trong generated corpus;
- concurrent scenario runs không mutate shared market.

---

## P1.10 — Error taxonomy và fail-fast boundary

### Structured error codes

```text
ConfigurationError
CapabilityError
ContractMismatchError
PreparationError
CommandValidationError
ExecutionInvariantError
StrategyCallbackError
NativeProtocolError
ResourceLimitError
AuditMismatchError
```

Rust trả structured error:

```rust
struct EngineError {
    code: EngineErrorCode,
    phase: PhaseCode,
    bar_index: Option<u32>,
    symbol_id: Option<u32>,
    order_handle: Option<OrderHandle>,
    detail_code: u32,
}
```

Python map sang exception class và enrich string metadata ngoài hot path.

### Không dùng panic cho user input

- invalid command/config => `Result::Err`;
- internal invariant => debug assertion + structured fatal error ở release;
- panic boundary tại PyO3 phải catch/unwind theo policy hoặc build panic behavior rõ ràng;
- session sau fatal invariant phải marked poisoned, không reuse.

### Fail-fast order

```text
1. package/protocol handshake
2. request schema
3. contract/capability
4. resource limits
5. market/instrument preparation
6. strategy compile
7. session run
```

Không prepare tape hàng GB rồi mới phát hiện native không support contract.

### Gate

- Python/Rust same public error class/code cho golden invalid cases;
- explicit Rust không fallback;
- auto fallback chỉ cho availability/capability policy cho phép, không fallback khi engine internal invariant fail;
- error metadata không làm nondeterministic trace.

---

## P1.11 — Observability trước P2

P2 không được bắt đầu nếu chưa đo được boundary costs.

### Counter schema tối thiểu

```text
planning_ns
market_prepare_ns
instrument_prepare_ns
strategy_prepare_ns
command_compile_ns
engine_prepare_ns
engine_run_ns
result_adapt_ns
report_build_ns
oracle_verify_ns

bars_processed
pyo3_calls
python_callbacks
gil_reacquisitions
command_rows
command_buffer_grows
market_bytes_copied
command_bytes_copied
result_bytes_copied
callback_projection_bytes

order_slots_created
active_order_peak
terminal_order_peak
order_scans
order_rows_scanned
index_lookups
expiry_checks
oco_cancellations
parent_activations
margin_recomputes
position_clones
output_rows
output_buffer_grows
```

### Timing methodology

- monotonic high-resolution clock;
- nested phases không double-count trong total;
- counters disabled/low-overhead ở production nhưng benchmark build bật đầy đủ;
- trace-level diagnostics tách khỏi standard counters;
- metadata schema versioned.

### Gate

Mỗi benchmark report phải trả lời được:

```text
Rust chậm ở Python callback, PyO3 transfer, kernel, output hay report?
```

Nếu chưa trả lời được, không chấp nhận optimization PR chỉ dựa vào total time.

---

## P1.12 — Kế hoạch tách file cụ thể từ code hiện tại

### `src/quantbt/endpoint.py`

Di chuyển lần lượt:

```text
backend/profile/capability resolution -> planning/resolve.py
input/contract validation             -> planning/validation.py
market preparation                    -> preparation/market.py
strategy preparation                  -> preparation/strategies.py
backend dispatch                      -> engines/registry.py
raw result adaptation                 -> results/adapters.py
report construction                   -> results/reports.py
```

Giữ lại:

- public constructor/method signatures;
- deprecation shims;
- docstrings;
- call vào planner/executor.

### `src/quantbt/backends/native_event.py`

Tách:

```text
Python order engine          -> engines/python/event_engine.py
Python account engine        -> engines/python/account.py
Python matching policies     -> engines/python/matching.py
Python lifecycle policies    -> engines/python/lifecycle.py
reactive strategy driver     -> strategies/python_driver.py
raw result builder           -> results/raw_builders.py
legacy compatibility         -> compatibility/native_event.py
```

Python implementation phải tiếp tục dễ đọc như oracle, không cố bắt chước layout Rust bằng mọi giá.

### `src/quantbt/backends/_native_event_rust.py`

Tách:

```text
native loading/handshake     -> engines/rust/loading.py
capability translation       -> engines/rust/capabilities.py
prepared session wrapper     -> engines/rust/session.py
callback compatibility       -> engines/rust/python_callback.py
result buffer ownership      -> engines/rust/results.py
legacy command adapter       -> engines/rust/legacy_commands.py
```

Adapter không giữ execution state.

### `src/quantbt/core/*`

- giữ domain/public contracts trong `contracts/`;
- generated enum/schema vào `contracts/generated/`;
- parity/diff vào `verification/`;
- benchmark/probe helper không nằm trong production core.

### Temporary compatibility imports

```python
# old path
from quantbt.backends.native_event import NativeEventBackend

# forwards to
from quantbt.engines.python.event_engine import PythonEventBackend
NativeEventBackend = PythonEventBackend
```

Mỗi shim có deprecation deadline, owner và test.

---

## P1.13 — P1 test plan

### Contract tests

Một fixture factory chạy cả backend:

```python
@pytest.mark.parametrize("backend", ["python", "rust"])
def test_market_order_contract(case, backend):
    result = run_case(case, backend=backend)
    assert_trace(result.trace, case.expected_trace)
```

### Architecture tests

- import boundaries;
- no pandas in engine SPI;
- backend does not mutate plan;
- one preparation call;
- lazy native import;
- one authoritative state;
- no replay on native audit unless requested.

### Boundary tests

- zero commands;
- command buffer overflow/growth;
- callback returns legacy objects;
- callback writes command buffer;
- sparse wake scheduling;
- callback exception;
- stale context;
- result survives session close;
- result release then session reset;
- Rust unavailable/mismatch.

### Performance smoke

- static tape pyo3 call count;
- declared minimal context bytes;
- legacy conservative context bytes;
- no report in optimize profile;
- no fill/event row allocations in count-only.

### Memory tests

```text
1,000 session resets
10,000 small runs using prepared market
large audit streamed to sink
result retained while new session runs
callback raises at random bars
```

Assert:

- plateau within budget;
- no stale buffer reads;
- no leaked Python strategy references;
- no terminal-order accumulation across reset.

---

## P1.14 — P1 exit checklist

```text
[ ] endpoint reduced to facade/planner/executor orchestration
[ ] immutable ExecutionPlan and fingerprint implemented
[ ] Python/Rust implement same backend SPI
[ ] RawEngineResult contains no pandas/report objects
[ ] OutputRequirements compiled once
[ ] StrategyContextRequirements explicit
[ ] numeric context view implemented
[ ] reusable command writer implemented
[ ] static command tape is one-call path
[ ] Rust adapter shadow account/order state removed
[ ] native state delta/projection protocol implemented
[ ] audit does not default to double execution
[ ] prepared cache/reset/lifetime contract proven
[ ] structured errors and runtime handshake pass
[ ] boundary/per-phase observability available
[ ] import boundaries enforced
[ ] all P0 traces/invariants unchanged
```

P1 được coi là thất bại nếu chỉ đổi tên file nhưng vẫn giữ cùng control flow và shadow-state.

---

# P2 — Advanced Rust optimization và native execution architecture

## P2 objective

P2 là tầng tối ưu triệt để, nhưng phải hiểu “triệt để” theo nghĩa kiến trúc:

- Rust sở hữu full execution/accounting state;
- static tape, strategy IR và batch đi qua PyO3 theo **run/batch**, không theo bar;
- arbitrary Python callback vẫn được support, nhưng được phân loại đúng là compatibility workload;
- hot data có layout/index phù hợp với event lifecycle;
- output không materialize rows/objects không được yêu cầu;
- score tính online trong Rust;
- portfolio và package/arbitrage dùng chung domain/account/order/risk primitives;
- parallelism nằm ở scenario/fold/package-independent layer, không phá event ordering;
- mọi optimization được chứng minh bằng profile + parity + memory gate.

Kiến trúc đích không phải “một `full.rs` lớn hơn”. Nó là một pure Rust engine có boundaries rõ và PyO3 chỉ là adapter.

---

## P2.0 — Freeze benchmark taxonomy trước khi sửa kernel

### Vì sao cần taxonomy

Hiện có thể thấy hai kết quả hoàn toàn khác:

- prepared static/full-tape Rust có thể rất nhanh;
- common reactive Python callback có thể không thắng Python do callback, context, command compile và per-bar boundary.

Nếu gom hai workload vào một benchmark “Rust backtest”, kết luận sẽ sai.

### Workload classes bắt buộc

#### E0 — Static explicit command tape

- commands đã biết trước;
- một symbol và multi-symbol;
- low/high order churn;
- score, compact, audit;
- one PyO3 call/run.

Đây là gate kernel/lifecycle/accounting thuần.

#### E1 — Arbitrary every-bar Python callback

- compatibility context;
- conservative requirements;
- legacy command objects;
- một callback/bar.

Đây là gate facade/boundary; không dùng để chứng minh native strategy speed.

#### E2 — Declared/sparse Python callback

- numeric context view;
- command writer;
- explicit requirements;
- every-N-bar hoặc wake-on-fill/event.

Đây là gate P1 boundary optimization.

#### E3 — Native strategy IR

- strategy program đã validate/compile;
- precomputed signal tape hoặc native indicators giới hạn;
- one PyO3 call/run;
- Grid/DCA/bracket/rebalance starter corpus.

Đây là gate Rust end-to-end thực tế.

#### E4 — Portfolio target tape

- target weights/units precomputed;
- multiple symbols;
- rebalance calendars;
- cross-account margin/risk;
- score/compact/audit.

#### E5 — Arbitrage package tape

- multiple legs/venues;
- package policies atomic/best-effort/sequential;
- latency/staleness scenarios;
- residual exposure attribution.

#### E6 — Batch optimizer/WFO

- N parameter sets trên shared market;
- single-thread và multi-thread;
- scalar results cho tất cả;
- audit cho selected top-K;
- reset/reuse pressure.

### Fixture matrix

Mỗi E-class có ít nhất:

```text
small:  10k bars, 1–4 symbols
medium: 250k bars, 8–32 symbols
large: 1m+ bars hoặc memory-pressure equivalent

low churn:    <0.01 order/bar/symbol
medium churn: 0.1–1 order/bar/symbol
high churn:   >2 lifecycle operations/bar/symbol

few positions / dense positions
few active orders / many active orders
no funding / scheduled funding
no liquidation / frequent margin pressure
```

### Phase timings

```text
T_import
T_plan
T_prepare_market
T_prepare_instruments
T_compile_strategy
T_compile_commands
T_native_prepare
T_boundary_in
T_engine
T_boundary_out
T_adapt
T_report
T_total
```

Ngoài wall time:

```text
CPU time
p50/p95/p99 run latency
peak RSS
steady-state RSS
allocations/bytes allocated
cache misses/branch misses khi profiler hỗ trợ
PyO3 calls
callbacks
bytes copied
output rows
```

### Benchmark discipline

- pin exact commit, Rust/Python/compiler version;
- freeze CPU governor/affinity hoặc ít nhất ghi metadata;
- warm-up riêng cho Numba/import/cache;
- cold và warm là hai report riêng;
- benchmark executable/raw native riêng nhưng không thay facade gate;
- use median + robust spread, không cherry-pick best run;
- performance PR phải kèm before/after cùng machine;
- semantics fingerprint phải giống trước/sau.

### Baseline manifest

```yaml
benchmark_schema: 1
repo_sha: ...
contract: event_lifecycle_v2_next_bar_close
python: 3.13.x
rustc: ...
pyo3: 0.29.x
numpy: ...
cpu: ...
workloads:
  - id: E0_STATIC_HIGH_CHURN_AUDIT
    fixture_sha256: ...
    bars: 250000
    symbols: 8
    commands: ...
    output: audit
```

### P2 promotion principle

Không có một tỷ lệ speedup duy nhất. Promotion là matrix theo workload:

```text
workload + contract + profile + dataset scale + platform
```

---

## P2.1 — Chuyển thành Rust workspace, PyO3 chỉ ở outer crate

### Workspace đề xuất

```text
rust/
  Cargo.toml                         # workspace

  crates/
    quantbt-domain/
      src/
        ids.rs
        enums.rs
        errors.rs
        numeric.rs
        instrument.rs
        commands.rs
        trace.rs

    quantbt-engine/
      src/
        lib.rs
        market.rs
        clock.rs
        session.rs
        orders/
          arena.rs
          indexes.rs
          lifecycle.rs
          matching.rs
        account/
          positions.rs
          pnl.rs
          fees.rs
          funding.rs
          margin.rs
          liquidation.rs
        output/
          sinks.rs
          buffers.rs
          metrics.rs

    quantbt-strategy-ir/
      src/
        bytecode.rs
        validator.rs
        runtime.rs
        registers.rs
        ops.rs
        compiler_schema.rs

    quantbt-batch/
      src/
        scenarios.rs
        runner.rs
        scheduler.rs
        reductions.rs

    quantbt-portfolio/
      src/
        targets.rs
        rebalance.rs
        allocator_contract.rs
        attribution.rs

    quantbt-package/
      src/
        packages.rs
        reservations.rs
        commit.rs
        residual.rs

    quantbt-py/
      src/
        lib.rs
        module.rs
        handshake.rs
        market.rs
        sessions.rs
        results.rs
        errors.rs
```

### Dependency direction

```text
quantbt-domain
   ↑
quantbt-engine
   ↑          ↑
strategy-ir  portfolio/package
   ↑          ↑
quantbt-batch
   ↑
quantbt-py
```

`quantbt-domain` và `quantbt-engine` không import:

- PyO3;
- NumPy crate;
- pandas concepts;
- Python strings/exceptions;
- report models.

### Lợi ích

- pure Rust unit/proptest/bench chạy không khởi động Python;
- portfolio/arbitrage reuse exact account/order lifecycle;
- native binary/service/WASM research có thể dùng sau này;
- PyO3 upgrade không chạm kernel;
- compile times và feature sets kiểm soát tốt hơn;
- fuzzing dễ hơn;
- tránh một `lib.rs` binding chứa domain logic.

### Migration không big-bang

1. Tạo workspace nhưng giữ crate cũ như wrapper.
2. Extract enums/IDs/errors không behavior.
3. Extract market/account/order types.
4. Chuyển `FullSession` sang engine crate.
5. Binding crate giữ class/API 0.4 gọi engine mới.
6. Parity/fingerprint pass ở từng extraction.
7. Sau đó mới thêm ABI 0.5 và optimized structures.

### Feature flags

Giữ ít feature, có ý nghĩa:

```toml
[features]
default = ["event"]
event = []
portfolio = []
package = []
trace = []
parallel = ["dep:rayon"]
profiling = []
```

Không dùng feature để thay execution semantics. Contract/version là runtime plan, không phải compile flag.

### Gate

- `cargo test -p quantbt-engine` không cần Python headers;
- pure Rust benchmark chạy direct;
- PyO3 crate line coverage tập trung binding/lifetime/error conversion;
- API 0.4 parity không đổi sau extraction.

---

## P2.2 — Thiết kế internal ABI 0.5: typed IDs, handles và command tape

### Không expose internal memory layout trực tiếp như public ABI

Public Python command schema có thể giữ compatibility. Internal Rust ABI nên typed và compact.

### Typed IDs

```rust
#[repr(transparent)]
#[derive(Clone, Copy, Eq, PartialEq, Hash)]
pub struct SymbolId(pub u32);

#[repr(transparent)]
pub struct InstrumentId(pub u32);

#[repr(transparent)]
pub struct VenueId(pub u16);

#[repr(transparent)]
pub struct CurrencyId(pub u16);

#[repr(transparent)]
pub struct ExternalOrderId(pub i64);
```

Không truyền `i64` cho mọi domain field trong core; compiler sẽ bắt nhầm symbol/order/group tốt hơn.

### Generation-safe order handle

```rust
#[repr(C)]
#[derive(Clone, Copy, Eq, PartialEq, Hash)]
pub struct OrderHandle {
    pub slot: u32,
    pub generation: u32,
}
```

Có thể pack thành `u64` ở binding:

```text
handle = generation << 32 | slot
```

External ID map:

```text
ExternalOrderId -> OrderHandle
```

Relationship trong core dùng direct handle:

```text
parent: Option<OrderHandle>
oco_group: Option<OcoGroupHandle>
package: Option<PackageHandle>
```

Không lặp hash lookup bằng external ID cho every relationship transition.

### Typed enums

```rust
#[repr(u8)]
enum OrderType { Market, Limit, StopMarket, StopLimit }

#[repr(i8)]
enum Side { Sell = -1, Buy = 1 }

#[repr(u8)]
enum TimeInForce { Gtc, Ioc, Fok, Gtd }

#[repr(u8)]
enum OrderStatus { Pending, Active, Filled, Canceled, Rejected, Expired }
```

Translator ABI 0.4 → internal 0.5 validate integer code một lần trước run.

### Command tape SoA

```rust
pub struct CommandTape {
    pub offsets_by_bar: Box<[u32]>,
    pub opcode: Box<[u8]>,
    pub external_id: Box<[i64]>,
    pub target_handle_or_id: Box<[u64]>,
    pub symbol: Box<[u32]>,
    pub side: Box<[i8]>,
    pub order_type: Box<[u8]>,
    pub tif: Box<[u8]>,
    pub flags: Box<[u16]>,
    pub qty: Box<[f64]>,
    pub limit_ticks: Box<[i64]>,
    pub stop_ticks: Box<[i64]>,
    pub expire_bar: Box<[u32]>,
    pub parent: Box<[u64]>,
    pub oco_group: Box<[u32]>,
    pub client_tag: Box<[u32]>,
}
```

`offsets_by_bar[bar..bar+1]` giúp direct slice command của bar, không filter scan.

### Integer ticks vs f64 prices

Internal order trigger/limit nên cân nhắc integer ticks:

```text
price_ticks = round(price / tick_size)
```

Lợi ích:

- deterministic compare;
- exact tick equality;
- hash/index theo price khả thi;
- giảm floating tolerance trong lifecycle.

Market path vẫn có thể giữ `f64` price arrays nếu source data không quantized, nhưng trước compare/fill theo instrument policy phải map sang canonical ticks hoặc exact quantized price.

Không chuyển toàn bộ PnL sang fixed-point ngay nếu multi-currency/contract-size gây overflow/complexity; làm theo domain:

```text
order prices/qty grid -> integer ticks/steps
account PnL/equity    -> deterministic f64 hoặc decimal policy versioned
```

### Alignment và layout

- dùng `#[repr(C)]` cho ABI structs khi thật sự qua FFI;
- không dùng `#[repr(packed)]` cho hot structs vì unaligned loads;
- kiểm tra size/alignment bằng compile-time tests;
- SoA cho fields đọc riêng trong loops;
- AoS nhỏ cho control records thường đọc cùng nhau;
- benchmark, không dogma.

### Translator strategy

```text
Python API 0.4
  -> Python/Rust validation translator
  -> InternalCommandTapeV5
  -> engine
```

Translator fingerprint và corpus test phải bảo đảm old public input giữ semantics.

### Gate

- stale handle bị reject, không mutate slot mới;
- external ID alias/replace semantics theo P0;
- all enum conversion xảy ra ngoài hot loop;
- command slice per bar O(number_of_commands_at_bar);
- tick/step round-trip exact;
- malformed ABI không panic/out-of-bounds.

---

## P2.3 — Market data layout và ownership

### Current good foundation

Prepared market copy một lần vào Rust-owned boxed slices + `Arc` là hướng đúng. Không cần theo đuổi unsafe zero-copy input trước khi chứng minh copy-on-prepare là bottleneck.

### Layout cho event loop

Current indexing dạng:

```rust
array[bar * n_symbols + symbol]
```

Tức bar-major, phù hợp khi mỗi bar loop qua symbols/account mark. Giữ làm default event layout.

```rust
pub struct BarMajorMarket {
    timestamps_ns: Box<[i64]>,
    open: Box<[f64]>,
    high: Box<[f64]>,
    low: Box<[f64]>,
    close: Box<[f64]>,
    volume: Box<[f64]>,
    funding: Box<[f64]>,
    flags: Box<[u16]>,
    n_bars: usize,
    n_symbols: usize,
}
```

### Market flags

Thay multiple bool arrays nếu access cùng phase bằng compact flags:

```rust
bit 0: funding_due
bit 1: session_open
bit 2: session_close
bit 3: missing_bar
bit 4: stale_quote
bit 5: corporate_action
```

Nhưng benchmark `u16 flags` vs separate dense masks; không ép bitset nếu decode cost cao hơn.

### Optional symbol-major views

Portfolio analytics/indicator precompute đôi khi thuận symbol-major. Không duplicate mặc định toàn tape. Có ba lựa chọn:

1. bar-major default;
2. optional transposed cache chỉ khi workload yêu cầu;
3. per-symbol index/view vào original layout khi sequential bars.

`ExecutionPlan.market_layout` quyết định trước run.

### Instrument table

```rust
pub struct InstrumentTable {
    tick_size: Box<[f64]>,
    qty_step: Box<[f64]>,
    contract_size: Box<[f64]>,
    leverage: Box<[f64]>,
    fee_model_id: Box<[u16]>,
    margin_model_id: Box<[u16]>,
    quote_currency: Box<[u16]>,
    venue: Box<[u16]>,
}
```

Hot loop lấy pointer/slice theo `SymbolId`; không gọi virtual Python fee/margin model.

### Copy policy

Input NumPy → Rust:

- validate dtype/contiguity once;
- copy once vào immutable owned memory;
- record copied bytes/time;
- reuse across trials/sessions;
- avoid `ascontiguousarray` nếu already exact;
- avoid hidden second copy từ temporary conversion.

### Vì sao chưa nên borrow NumPy lâu dài

Unsafe borrowed NumPy memory qua GIL-detached run có lifetime/mutation/free-threading risks. Chỉ cân nhắc experimental path khi:

- array read-only/owned/contiguous;
- owner pinned trong native object;
- no Python mutation contract enforce được;
- stress tests trên CPython free-threaded/GIL builds;
- input copy đã chứng minh là dominant cho one-shot workloads.

Prepared multi-run mục tiêu làm copy amortized gần zero, nên ownership Rust an toàn hơn.

### Prefetch và bounds checks

Trước tiên:

- hoist `bar * n_symbols`;
- lấy slice của bar một lần;
- iterator/slice indexing để compiler eliminate bounds checks;
- no manual prefetch trừ khi perf counters chứng minh memory latency;
- no `get_unchecked` nếu chưa có measurable gain và Miri/proptest proof.

### Gate

- market copy count = 1/prepared key;
- 0 market copy/trial trong batch;
- deterministic missing/stale flags;
- layout benchmark cho E0/E4;
- memory duplicate budget rõ;
- unsafe input borrowing không nằm trong default release.

---

## P2.4 — Order arena generation-safe và hot/cold split

### Vấn đề với `Vec<OrderState>` + compaction

- terminal orders giữ chỗ cho tới compaction;
- compaction O(total slots) và rebuild map;
- direct slot references có thể invalid sau compaction;
- full `OrderState` được đọc dù loop chỉ cần một số fields;
- scan toàn arena làm cost phụ thuộc lifetime orders, không phải active orders.

### Arena mục tiêu

```rust
pub struct OrderArena {
    generations: Vec<u32>,
    free_head: Option<u32>,
    next_free: Vec<u32>,
    occupied: BitSet,

    // hot SoA
    status: Vec<u8>,
    symbol: Vec<u32>,
    side: Vec<i8>,
    order_type: Vec<u8>,
    tif: Vec<u8>,
    flags: Vec<u16>,
    qty_remaining: Vec<f64>,
    limit_ticks: Vec<i64>,
    stop_ticks: Vec<i64>,
    sequence: Vec<u64>,

    // relationship/control
    parent: Vec<OrderHandle>,
    oco_group: Vec<OcoGroupHandle>,
    expire_bar: Vec<u32>,

    // cold metadata, optional or separate
    external_id: Vec<i64>,
    client_tag: Vec<u32>,
    created_bar: Vec<u32>,
    reject_code: Vec<u16>,
}
```

Alternative hybrid:

```rust
struct HotOrder { ... }
struct ColdOrderMeta { ... }
Vec<HotOrder> + Vec<ColdOrderMeta>
```

Benchmark SoA vs hybrid. Matching thường đọc symbol/type/side/price/status/sequence; report đọc metadata sau.

### Allocation/free

```rust
fn allocate(&mut self) -> OrderHandle {
    if let Some(slot) = self.free_head { reuse(slot) } else { grow() }
}

fn release(&mut self, handle: OrderHandle) {
    validate_generation(handle);
    generations[slot] += 1;
    push_free(slot);
}
```

Terminal detail cần audit có thể được append vào immutable event/output buffer trước release. Không cần giữ terminal `OrderState` trong active arena.

### Stable priority

Slot reuse không được thay insertion priority. Mỗi order có monotonic `sequence: u64`; matching tie-break theo contract:

```text
price priority
then activation/creation phase
then sequence
```

### External ID table

Options:

- standard `HashMap<ExternalOrderId, OrderHandle>` ban đầu;
- faster hasher chỉ sau profile và DoS model;
- dense generated IDs dùng `Vec<Option<OrderHandle>>` khi engine tự cấp contiguous IDs;
- hybrid: dense internal handle, hash only external arbitrary IDs.

Đừng bỏ standard hash map chỉ vì benchmark micro; correctness và adversarial IDs quan trọng.

### No hot compaction

Generational free list loại compaction khỏi event loop. Maintenance chỉ:

- shrink/rebuild giữa runs khi explicit;
- compact cold history/output ngoài hot session;
- preserve generation safety.

### Arena sizing

Preparation/static tape có thể estimate peak active orders. Reserve:

```text
initial_capacity = min(config.max_orders, estimated_peak * safety_factor)
```

Dynamic callback dùng observed high-water + geometric growth.

### Limits

```text
max_live_orders
max_total_orders_created
max_relationship_edges
max_oco_groups
max_children_per_parent
```

Limit violation trả `ResourceLimitError`, không OOM/panic.

### Gate

- no order compaction in hot loop;
- stale handles fail;
- arena capacity plateaus under churn;
- peak live slots gần active/waiting orders, không total historical orders;
- order priority fingerprint unchanged;
- high-churn E0 improves without low-churn regression beyond budget.

---

## P2.5 — Lifecycle indexes thay full scans

### Nguyên tắc

Cost phải gần với **relevant active orders**, không phải tổng order lịch sử.

### Index set tối thiểu

#### 1. Active orders per symbol

```rust
active_by_symbol: Vec<IntrusiveList<OrderHandle>>
```

Hoặc dense vectors + swap-remove + back-pointer:

```rust
active_by_symbol[symbol]: Vec<OrderHandle>
active_pos_in_symbol[slot]: u32
```

Swap-remove O(1), nhưng matching priority không được dựa vector order; dùng `sequence`/specialized buckets.

#### 2. Expiry index

Nếu `expire_bar` nằm trong tape range, dùng timing wheel/buckets:

```rust
expiry_by_bar: Vec<Vec<OrderHandle>>
```

GTD expiry bar `t` chỉ visit bucket `t`.

Cho dynamic beyond known range:

- growable buckets;
- hoặc min-heap `(expire_bar, sequence, handle)`;
- stale heap entries bỏ bằng generation/status check.

#### 3. Parent → children adjacency

```rust
children_by_parent: Vec<SmallVec<OrderHandle>>
```

Không scan tất cả orders khi parent fill. Nếu tránh dependency `smallvec` lúc đầu, dùng linked edge arena:

```text
first_child[slot]
next_sibling[child_slot]
```

#### 4. OCO group index

```rust
oco_groups: GroupArena<Vec<OrderHandle>>
```

Khi one order fill/cancel policy trigger, chỉ visit siblings trong group.

#### 5. Group/client-tag index

Chỉ build khi contract hỗ trợ cancel-by-group/tag. Structured capability quyết định index needed; static plan không sử dụng thì không allocate.

#### 6. Waiting-parent index

Waiting child không nằm trong active matcher. Nó chỉ nằm trong parent adjacency + order arena.

#### 7. Cancel-all index

- global cancel all: iterate live active handles, không full historical arena;
- per-symbol cancel all: active_by_symbol[symbol];
- per-group: group index.

### Matching index strategy

Không có một index tốt cho mọi quy mô.

#### Low active-order cardinality

Flat active vector thường nhanh nhất do cache locality và ít overhead. Dùng adaptive threshold:

```text
if active_count <= SMALL_SCAN_THRESHOLD:
    flat scan
else:
    indexed matching
```

Threshold benchmark theo CPU/workload, không hardcode từ intuition.

#### High cardinality OHLC bar matching

Với integer ticks:

- buy limits có thể index theo price;
- sell limits theo price;
- buy/sell stops theo trigger;
- current bar `[low_tick, high_tick]` query relevant range.

Candidate structures:

- sorted vectors rebuilt incrementally/batched;
- `BTreeMap<ticks, bucket>`;
- binary heap cho one-direction triggers;
- radix/sparse price buckets nếu tick domain compact;
- custom ordered slab sau profiling.

Không chọn tree chỉ vì asymptotic O(log n): low-churn cache locality có thể thua flat scan.

### Deferred mutation during matching

Không mutate active vector trong khi iterate trực tiếp. Dùng transition queue:

```rust
match candidates
  -> append FillAction/CancelAction/ActivateAction
  -> apply actions theo canonical phase/sequence
  -> update indexes
```

Điều này tránh iterator invalidation và giữ deterministic ordering.

### Index invariant checker

Debug/test build:

```text
every active order exists exactly once in active index
waiting child not in active index
terminal order in no active index
expiry bucket matches order expiry
parent adjacency points to valid generation
OCO membership bidirectional consistent
external ID resolves latest valid handle
```

Có `validate_indexes()` chạy:

- every step trong small property tests;
- sampled trong long fuzz;
- không bật production hot path.

### Gate

- expiry checks O(expiring orders at bar);
- parent activation O(children of parent);
- OCO cancel O(group size);
- cancel symbol O(active of symbol);
- no full historical order scans in normal lifecycle;
- index memory overhead đo và nằm trong budget;
- adaptive matching wins/does not regress fixture matrix.

---

## P2.6 — Specialized execution kernels, không dùng một universal hot loop

### Vấn đề universal kernel

Một kernel hỗ trợ đồng thời:

```text
score + compact + audit
static + callback + IR
single + portfolio + package
all order types
all trace levels
all margin policies
```

sẽ mang nhiều branch và output checks vào every bar/order. Capability đã resolve ở `ExecutionPlan`; hot loop không cần hỏi lại liên tục.

### Specialization axes

#### Axis A — Strategy driver

```rust
trait StrategyDriver {
    fn before_bar(&mut self, ...);
    fn emit_commands(&mut self, ..., out: &mut CommandBuffer);
    fn next_wake_bar(&self) -> Option<u32>;
}
```

Implementations:

- `StaticTapeDriver`;
- `IrDriver`;
- `PortfolioTargetDriver`;
- `PackageTapeDriver`;
- `ExternalCallbackDriver` only at binding/chunk boundary.

Trong hot native runs, compiler nên monomorphize concrete driver hoặc match mode một lần ngoài bar loop.

#### Axis B — Output sink

```rust
trait OutputSink {
    fn on_fill(&mut self, fill: FillRecordRef);
    fn on_event(&mut self, event: EventRecordRef);
    fn on_bar(&mut self, snapshot: AccountSnapshotRef);
    fn finish(self, summary: EngineSummary) -> EngineOutput;
}
```

Implementations:

- `ScoreSink`;
- `CompactSink`;
- `AuditSink`;
- `TraceHashSink`;
- `StreamingAuditSink`.

`ScoreSink` không chứa methods/data cần rows; optimizer có thể remove branches.

#### Axis C — Contract policy

```rust
trait ExecutionPolicy {
    fn market_fill_price(...);
    fn phase_order(...);
    fn gap_fill(...);
    fn intrabar_order(...);
}
```

Không dùng trait object per fill. Resolve thành enum dispatch outer loop hoặc generic concrete run:

```rust
match plan.contract {
    V2NextBarClose => run::<V2Policy, S, O>(...),
    V3NextOpen => run::<V3Policy, S, O>(...),
}
```

Số tổ hợp phải kiểm soát để tránh code bloat. Chỉ specialize axes có profile evidence; các policy model hiếm có thể enum branch ở phase boundary.

### Recommended kernel entry points

```rust
run_static_score(...)
run_static_compact(...)
run_static_audit(...)
run_ir_score(...)
run_ir_compact(...)
run_ir_audit(...)
run_portfolio_score(...)
run_package_audit(...)
run_external_chunk(...)
```

Public PyO3 có thể expose API gọn, nhưng internal entry point cụ thể.

### Branch hoisting

Resolve ngoài loop:

```text
use_funding
needs_dense_equity
needs_fills
needs_events
needs_active_orders
margin model
fee model
slippage model
contract version
```

Trong loop, dùng concrete sink/model. Không check `output_mask & ...` cho every emitted field nếu generic sink đã loại branch.

### Code size control

Đo:

```text
cargo bloat
LLVM instruction count
compile time
wheel binary size
I-cache misses
```

Nếu generic combinations bùng nổ:

- specialize top workloads;
- dùng enum for rare policies;
- split feature-gated crates;
- tránh inline mọi function lớn;
- `#[inline]` chỉ cho leaf hot functions, không blanket.

### Gate

- score binary path không gọi row-construction code;
- audit path giữ exact trace;
- contract branch count giảm theo profile;
- wheel size/code size trong budget;
- no parity divergence giữa specialized sinks.

---

## P2.7 — Tối ưu matching pipeline theo phase và candidate set

### Pipeline mục tiêu mỗi bar

```text
1. load bar slice / clock flags
2. mark account prices/dirty symbols
3. apply scheduled funding/corporate/session events
4. run pre-command risk/liquidation phase theo contract
5. fetch command slice / strategy driver commands
6. validate and apply lifecycle transitions
7. build candidate sets per symbol/order class
8. resolve fills theo intrabar policy/priority
9. apply fill deltas + relationship transitions
10. run post-fill risk/liquidation phase
11. emit requested aggregate/detail
12. advance wake/clock
```

Mỗi phase có trace code và invariant hooks từ P0.

### Candidate generation

Tách order types:

```text
market-ready
limit-buy
limit-sell
stop-buy
stop-sell
stop-limit-triggered
```

Không gọi một `fill_price(order)` branch qua tất cả types nếu candidate class đã biết type.

Ví dụ:

```rust
for handle in market_ready.drain(..) {
    execute_market::<Policy>(...);
}
for handle in touched_buy_limits(bar.low_tick) {
    execute_limit_buy::<Policy>(...);
}
```

### Trigger state cho stop-limit

Stop-limit có hai state riêng:

```text
WAITING_TRIGGER -> ACTIVE_LIMIT -> FILLED/CANCELED/EXPIRED
```

Không encode chỉ bằng ambiguous flags. Khi trigger:

- event trace emitted;
- remove từ stop index;
- insert vào limit index;
- preserve original/trigger sequence theo contract.

### FOK/IOC

OHLCV không có order book depth thật. P0 phải định nghĩa available-liquidity model. P2 chỉ tối ưu implementation:

- `FOK`: check fillable quantity before mutation;
- `IOC`: fill allowed quantity then cancel remainder;
- count-only sink vẫn emit counters/state transitions;
- no speculative account mutation rồi rollback bằng clone toàn account.

Dùng lightweight `FillPreview`:

```rust
struct FillPreview {
    executable_qty: f64,
    price: f64,
    fee: f64,
    margin_delta: f64,
    valid: bool,
    reject: RejectCode,
}
```

Commit sau validation.

### Transactional mini-commit

Để giảm rollback complexity:

```text
preview order
  -> reserve/check margin
  -> produce AccountDelta + OrderDelta
  -> commit in canonical sequence
  -> emit sink
```

Package layer sẽ mở rộng concept này cho nhiều legs.

### Reduce-only fast check

Per symbol giữ current signed qty. `reduce_only` validation O(1):

```text
position == 0 -> reject
same-direction order -> reject/clip theo contract
opposite qty > abs(position) -> clip/reject theo contract
```

Không scan fills/history.

### Slippage/fee models

Resolve function/model once. Recommended shapes:

```rust
#[derive(Clone, Copy)]
enum SlippageModel {
    None,
    FixedBps(f64),
    FixedTicks(i64),
    VolumeImpact(VolumeImpactParams),
}
```

`match` ở fill commit, không dynamic trait object. Rare venue models có function table/static enum variants.

### Gate

- candidate visits measured, not just total active count;
- stop-limit state trace exact;
- FOK no partial state mutation;
- IOC remainder deterministic;
- same fill ordering Python/Rust;
- matching branch/cache profile improves target workloads.

---

## P2.8 — Incremental account, PnL, margin và liquidation engine

### Mục tiêu

Tránh recompute toàn portfolio/order set khi chỉ một số symbol thay đổi. Tuy nhiên correctness và deterministic reduction quan trọng hơn tối ưu sớm.

### Account state đề xuất

```rust
pub struct AccountState {
    cash_by_currency: Vec<f64>,
    equity_base: f64,
    realized_pnl_base: f64,
    unrealized_pnl_base: f64,
    fees_base: f64,
    funding_base: f64,

    positions: PositionBook,
    risk: RiskState,
    dirty_symbols: BitSet,
    active_position_ids: Vec<SymbolId>,
    pos_in_active: Vec<u32>,
}
```

### Position book SoA

```rust
pub struct PositionBook {
    qty: Vec<f64>,
    avg_entry: Vec<f64>,
    mark: Vec<f64>,
    realized: Vec<f64>,
    unrealized: Vec<f64>,
    notional: Vec<f64>,
    initial_margin: Vec<f64>,
    maintenance_margin: Vec<f64>,
    flags: Vec<u8>,
}
```

Active positions vector cho loops; swap-remove khi qty về zero, với back-pointer.

### Fill delta

Một pure function/reference implementation trước:

```rust
fn preview_position_delta(
    old_qty: f64,
    old_avg: f64,
    fill_side: Side,
    fill_qty: f64,
    fill_price: f64,
    contract_size: f64,
) -> PositionDelta
```

Cases bắt buộc:

```text
open
scale in same side
partial reduce
full close
reverse
reduce-only clipped/rejected
zero normalization
```

`PositionDelta` trả:

```text
new_qty
new_avg
realized_pnl
closed_qty
opened_qty
notional_delta
margin_dirty
```

### Dirty-symbol mark-to-market

Mỗi bar giá của nhiều symbols có thể đổi; nếu equity path cần exact mỗi bar, phải update all active positions. Nhưng không update inactive symbols.

```text
O(number_of_active_positions) per bar
```

Nếu chỉ sparse score metric không cần every-bar equity, contract vẫn có thể cần margin/liquidation every bar. Không được skip mark nếu làm thay đổi liquidation. Có thể optimize:

- only active positions;
- bar slice contiguous;
- separate homogeneous numeric loop dễ auto-vectorize;
- deterministic accumulation order fixed by ascending SymbolId.

### Margin cache

Current one-bar cache là nền, nhưng cần dirty versioning:

```rust
struct RiskCache {
    state_version: u64,
    mark_version: u64,
    computed_state_version: u64,
    computed_mark_version: u64,
    initial: f64,
    maintenance: f64,
}
```

Invalidate khi:

- fill/reverse/close;
- leverage/margin model change;
- funding affects collateral;
- mark changes relevant positions;
- reservation/package change.

Không invalidate vì unrelated event/output.

### Incremental margin

Cho simple gross cross margin:

```text
IM_total += new_IM_symbol - old_IM_symbol
MM_total += new_MM_symbol - old_MM_symbol
```

Mỗi symbol giữ contribution. Cho complex portfolio margin:

- model declares incremental capability;
- nếu unsupported, recompute risk set theo model;
- diagnostics phân biệt incremental/recompute;
- semantics không đổi để đạt speed.

### Fee/funding currency

Tách model outputs:

```rust
struct MoneyDelta {
    amount: f64,
    currency: CurrencyId,
}
```

Conversion sang base currency theo versioned FX marks. Không giả định fee luôn trừ base cash nếu future multi-currency.

### Liquidation engine

```rust
trait LiquidationPolicy {
    fn detect(...)-> LiquidationDecision;
    fn build_actions(..., out: &mut LiquidationActions);
}
```

Tách:

```text
trigger detection
position selection/order
liquidation price policy
fee/penalty
partial/full liquidation
account bankruptcy handling
trace attribution
```

Không để một boolean `liquidated` thay toàn lifecycle.

### Deterministic reductions

Parallel/vectorized reductions có thể thay floating rounding. Policy:

- fixed symbol order;
- same accumulation algorithm Python/Rust reference;
- optionally compensated sum ở report/large multi-currency, nhưng version contract;
- không bật `fast-math`;
- tolerance chỉ ở public comparison khi domain cho phép, không che event-order divergence.

### Invariants trong optimized engine

Sau mỗi fill/funding/liquidation trong test build:

```text
cash + marked positions = equity theo account model
position notional/margin contributions consistent
active position index exact
risk cache version valid
no NaN/Inf unless input contract explicitly permits
reduce-only did not increase absolute exposure
reservation >= 0
```

### Gate

- margin recompute count giảm trên high-churn/multi-symbol fixtures;
- P0 accounting trace exact;
- active position loop không scan all symbols khi sparse positions;
- no full account clone for preview/rollback;
- liquidation tests include attribution and ordering, không chỉ final equity.

---

## P2.9 — Output architecture: flat SoA, online metrics và zero unnecessary materialization

### Current hotspots cần loại

Current Rust buffers đã SoA nội bộ, nhưng methods `rows()` tạo `Vec<Vec<...>>`, `FullStepResult` giữ nested rows và positions clone. Full-tape output có thể tiếp tục clone/materialize nhiều data.

### Raw output types

```rust
pub struct FillOutput {
    bar: Vec<u32>,
    order_handle: Vec<u64>,
    external_order_id: Vec<i64>,
    symbol: Vec<u32>,
    side: Vec<i8>,
    qty: Vec<f64>,
    price: Vec<f64>,
    fee: Vec<f64>,
    flags: Vec<u16>,
}

pub struct EventOutput {
    bar: Vec<u32>,
    phase: Vec<u8>,
    sequence: Vec<u64>,
    kind: Vec<u8>,
    order_handle: Vec<u64>,
    target_handle: Vec<u64>,
    symbol: Vec<u32>,
    code: Vec<u16>,
}
```

Không convert integer IDs sang `f64`.

### Buffer ownership options

#### Option A — Move `Vec<T>` into NumPy-owned array

Dùng Rust NumPy/PyO3 ownership API phù hợp version để chuyển Rust-owned vector thành NumPy array không copy payload. Wrapper Python giữ array owners.

Đây là mục tiêu tốt cho final output, nhưng phải test:

- lifetime;
- alignment;
- session reuse;
- exception midway;
- empty vectors;
- GC/free-threaded behavior.

#### Option B — Copy once into preallocated NumPy output

Đơn giản/an toàn hơn. Với output nhỏ/score, copy không đáng kể. Chọn theo benchmark.

#### Option C — Rust result object exposes buffer protocol/read-only views

Có thể dùng cho very large audit, nhưng ABI/lifetime phức tạp. Không cần cho first promotion.

### No nested rows

Binding trả tuple/typed result of arrays:

```python
NativeFillColumns(
    bar=np.ndarray[np.uint32],
    order_handle=np.ndarray[np.uint64],
    ...,
)
```

Python public adapter mới tạo records/DataFrame khi user yêu cầu.

### Final positions

- score: scalar summary + optional final position aggregates;
- compact: one final position table;
- audit: deltas/snapshots theo projection;
- không clone full `positions` per bar nếu strategy/output không cần;
- per-callback context có view/delta, không append vào final path.

### Online metric registry trong Rust

Current compatibility score path không được gọi audit rồi tính Python. Implement metric states:

```rust
trait OnlineMetric {
    fn on_start(&mut self, initial: AccountSnapshot);
    fn on_bar(&mut self, snapshot: AccountSnapshot);
    fn on_fill(&mut self, fill: FillRecordRef);
    fn finish(self) -> MetricValue;
}
```

Các metric native đầu tiên:

```text
final equity
net return
max drawdown
turnover
fees
funding
fill/reject/cancel counts
liquidation flag/bar
mean/std of returns via stable online algorithm
Sharpe-like score theo exact existing convention
```

Metric convention phải versioned:

- annualization;
- ddof;
- NaN/zero variance;
- risk-free assumption;
- timestamp frequency;
- missing bars.

### Multi-metric one pass

```rust
MetricSet<...>
```

Hoặc bitmask + concrete aggregate struct. Không allocate trait objects per bar. Top metric bundles specialize:

```text
OPTIMIZE_DEFAULT
RESEARCH_SUMMARY
PORTFOLIO_SCORE
PACKAGE_SCORE
```

### Streaming audit

Large audit không giữ all rows:

```text
Rust fills/events buffer up to chunk threshold
  -> reacquire Python only between chunks if Python sink
  -> write chunk
  -> clear/reuse
```

Tốt hơn nữa, native file sink optional viết binary/Arrow-compatible chunks không gọi Python trong run. Nhưng file schema phải stable và error-safe.

### Backpressure/resource policy

```text
max_output_rows
max_output_bytes
chunk_rows
on_limit = error | hash_only_after_limit (chỉ explicit)
```

Không silently truncate audit.

### Gate

- `rows()` nested conversion không còn trong fast result path;
- no IDs cast to f64;
- score does not invoke audit;
- final output copies/bytes measured;
- retained result lifetime safe;
- audit RSS scales by chunk size, không total event count khi streaming;
- metrics exact-match existing conventions.

---

## P2.10 — Native strategy execution hierarchy

### Mục tiêu thực tế

Không thể làm arbitrary Python callable chạy “native” chỉ bằng PyO3. Cần một hierarchy để user chọn compatibility hoặc native performance mà không mất API hoàn toàn.

### L0 — Legacy Python callback

```text
Python objects context
list[OrderCommand]
every bar by default
```

- giữ compatibility;
- backend planner có thể chọn Python nếu nhanh hơn;
- không dùng làm gate native strategy.

### L1 — Python numeric view + command writer

```text
compact context view
reusable command SoA
explicit requirements
```

- vẫn callback Python;
- giảm object/copy cost;
- tốt cho migration.

### L2 — Sparse Python callback

```text
native run-until-wake
callback schedule/wake conditions
```

- giảm callbacks/PyO3 calls;
- phù hợp rebalance, periodic Grid maintenance, event-triggered logic.

### L3 — Validated strategy IR

```text
Python declarative strategy/DSL
  -> compile/validate
  -> typed IR + parameter table
  -> Rust interpreter/specialized runtime
```

Đây là native path ưu tiên.

### L4 — Native Rust plugin/library

Cho advanced internal users sau này:

- compile strategy against stable Rust trait/version;
- static link/build wheel riêng hoặc plugin ABI;
- hiệu năng tối đa nhưng distribution/security phức tạp;
- không phải prerequisite cho P2 initial promotion.

### Strategy IR v1 scope

Không xây general Python VM. Scope tối thiểu có bounded operations:

#### Inputs

```text
OHLCV/funding field at current bar
precomputed signal tape columns
account scalars
position fields by static/dynamic symbol id
active order count/status by tag/group
new fill/event counters or selected fields
parameters/constants
```

#### Registers

```text
float registers: fixed count
int registers: fixed count
bool registers: fixed count
state registers persisted across bars
```

#### Arithmetic/comparison

```text
ADD SUB MUL DIV_SAFE MIN MAX ABS CLAMP
LT LE EQ GE GT
AND OR NOT
SELECT
IS_FINITE
```

#### State/control

```text
LOAD_STATE STORE_STATE
IF/ELSE or forward conditional jump
bounded loop only over static symbol set or prohibited v1
SCHEDULE_WAKE
HALT_BAR
```

#### Commands

```text
PLACE_MARKET
PLACE_LIMIT
PLACE_STOP
PLACE_BRACKET
CANCEL_HANDLE
CANCEL_GROUP
AMEND_QTY_PRICE
SET_TARGET_POSITION
EMIT_TAG
```

### Không support v1

- arbitrary Python calls;
- dynamic memory allocation;
- unbounded loops/recursion;
- filesystem/network;
- user pointers;
- nondeterministic time/random without explicit seeded op;
- arbitrary dataframe operations.

### IR model

```rust
pub struct StrategyProgram {
    version: u16,
    constants_f64: Box<[f64]>,
    constants_i64: Box<[i64]>,
    instructions: Box<[Instruction]>,
    state_schema: StateSchema,
    requirements: NativeRequirements,
    limits: ProgramLimits,
    fingerprint: [u8; 32],
}

#[repr(C)]
pub struct Instruction {
    opcode: u16,
    dst: u16,
    a: u16,
    b: u16,
    imm: u32,
}
```

Có thể dùng wider instruction nếu decode profile tốt hơn. Không optimize encoding trước runtime semantics.

### Validator

Compile-time validation:

```text
valid opcode/version
register bounds
type consistency
forward jump bounds
bounded instruction count
no divide without policy
symbol/field requirements declared
command limits
state initialization
contract compatibility
```

Runtime không re-check mọi instruction invariant.

### Execution model

Mỗi bar:

```text
input register projection
execute at most max_instructions_per_bar
append commands into native command buffer
apply commands in canonical phase
persist state registers
```

### Precomputed signal tape first

Để tránh biến Rust core thành indicator library ngay:

```text
Python/vectorized/Numba computes signals once
Rust IR consumes numeric signal columns across N trials
```

Điều này loại per-bar Python callback nhưng vẫn reuse ecosystem Python.

Sau đó mới native hóa indicators thật sự hot:

- rolling mean/std;
- EMA;
- ATR;
- rolling min/max;
- z-score;
- cross/threshold.

Mỗi indicator phải có exact warmup/NaN semantics.

### Starter strategies để prove IR

1. market-on-signal;
2. threshold long/short;
3. fixed bracket;
4. DCA periodic;
5. Grid state machine;
6. target rebalance;
7. two-leg spread threshold package.

Grid/DCA rất quan trọng vì có state + active orders, không chỉ toy signal.

### IR debugging

- disassembler human-readable;
- trace optional instruction/program counter at sampled bars;
- program/state dump;
- Python reference IR interpreter cho differential tests;
- versioned program fingerprint trong result.

### JIT/code generation?

Không cần ở v1. Interpreter với fixed opcodes + one call/run đã có thể thắng lớn vì loại Python callback. Sau profile:

- superinstructions/fused common op sequences;
- specialized Rust codegen/build cache;
- Cranelift/LLVM JIT chỉ khi interpreter decode thật sự dominant;
- JIT làm package/security/cache phức tạp nên không phải mặc định.

### Gate

- IR reference interpreter vs Rust exact trace;
- bounded runtime/resource use;
- one PyO3 call/run;
- no Python callback in native IR path;
- Grid/DCA/bracket parity;
- program fingerprint/reproducibility;
- E3 recommended performance promotion gate pass.

---

## P2.11 — Scenario batch engine cho optimizer và walk-forward

### Vì sao batch là leverage lớn nhất

Trong optimization, overhead lặp lại thường gồm:

- Python loop per trial;
- PyO3 call per trial;
- session allocation/reset;
- strategy compile;
- market/instrument ownership;
- result object creation.

Batch API chia sẻ immutable data và chỉ trả scalar/table compact.

### Public shape đề xuất

```python
scores = prepared.run_batch(
    parameter_matrix,
    metrics=("score", "max_drawdown", "turnover"),
    workers="auto",
    chunk_size=256,
    audit_top_k=0,
)
```

Hoặc two-phase:

```python
summary = prepared.score_batch(parameters)
audits = prepared.audit_scenarios(summary.top_ids(10))
```

### Rust data model

```rust
pub struct BatchPlan {
    scenario_count: usize,
    parameter_width: usize,
    metric_mask: MetricMask,
    worker_count: usize,
    chunk_size: usize,
    seed_policy: SeedPolicy,
    failure_policy: ScenarioFailurePolicy,
}

pub struct ScenarioTemplate {
    market: Arc<PreparedMarket>,
    instruments: Arc<InstrumentTable>,
    strategy_program: Arc<StrategyProgram>,
    account_template: AccountTemplate,
    engine_plan: Arc<NativeExecutionPlan>,
}

pub struct ScenarioState {
    account: AccountState,
    orders: OrderArena,
    indexes: LifecycleIndexes,
    strategy_state: StrategyState,
    metrics: MetricState,
    scratch: ScenarioScratch,
}
```

### Parameter matrix layout

Chọn layout theo strategy runtime:

- row-major `[scenario, parameter]` dễ API;
- Rust có thể transpose/cache column-major nếu same parameter read across vectorized scenario processing;
- v1 parallel independent scenarios, row-major đủ;
- validate finite/ranges once.

### Scenario reset/reuse

Worker giữ pool state:

```text
acquire ScenarioState
reset from template
load parameter row
run
write fixed output row
return state to worker-local pool
```

Không allocate full engine cho mỗi trial.

### Output layout

```rust
pub struct BatchResult {
    scenario_id: Vec<u32>,
    status: Vec<u16>,
    metric_columns: Vec<Vec<f64>>, // internal may be flat matrix
    final_equity: Vec<f64>,
    liquidated: BitSet,
    error_code: Vec<u16>,
    diagnostics_aggregate: BatchDiagnostics,
}
```

Binding trả fixed 2D NumPy matrix + status arrays, không list of result objects.

### Failure policy

```text
fail_fast
collect_per_scenario_errors
skip_invalid_parameters_before_run
```

Internal invariant failure không được silently convert thành bad score. User-strategy/program resource failure có structured status.

### Determinism

- scenario ID fixed theo input row;
- output sorted input order dù worker completion khác;
- RNG seed = deterministic function `(base_seed, scenario_id, fold_id)`;
- no global mutable RNG;
- floating computation inside scenario same as single-run;
- batch/single fingerprint exact for selected scenarios.

### Parallel scheduling

- fixed-size worker pool;
- chunks đủ lớn để amortize scheduling nhưng không imbalance;
- work-stealing có thể dùng, output deterministic vì write by scenario index;
- avoid one `Mutex` around shared result append; preallocate output and write disjoint slots;
- immutable `Arc` market/instruments/program;
- worker-local arena/buffers/metrics.

### NUMA/memory awareness

Cho market rất lớn và many workers:

- shared read-only tape thường tốt;
- đo memory bandwidth saturation;
- worker count auto không luôn bằng logical CPUs;
- expose `workers`, `affinity` diagnostics, không hard-bind mặc định;
- chunk parameters to keep state/output cache-friendly;
- audit rows chỉ selected scenarios.

### Walk-forward

`FoldPlan`:

```rust
struct FoldPlan {
    train_start: u32,
    train_end: u32,
    test_start: u32,
    test_end: u32,
    warmup_start: u32,
    reset_policy: FoldResetPolicy,
}
```

Batch dimensions:

```text
fold × scenario
```

Không duplicate market; use bar ranges/views. Result includes fold ID and aggregate policy outside/hybrid.

### Top-K audit

Không giữ audit mọi scenario. Flow:

1. batch score all;
2. stable select top-K theo score + scenario ID tie-break;
3. rerun selected with audit sink;
4. verify rerun scalar summary equals score run;
5. return audit refs.

### Gate

- one PyO3 call/batch or bounded calls per chunk;
- market copies = 0/trial;
- single vs batch exact parity;
- deterministic results across worker counts;
- RSS bounded by workers × scenario-state + shared market;
- parallel efficiency measured through physical-core range;
- no audit materialization for non-selected trials.

---

## P2.12 — Rust portfolio execution core dùng chung account/order engine

### Scope đúng cho first portfolio native path

Không cần port toàn bộ research stack/risk allocator sang Rust ngay. Split:

```text
Python/vectorized layer:
  signals
  forecasts
  covariance/risk estimates
  optimizer/allocator
  target weights/units

Rust execution layer:
  target interpretation
  rebalance command generation
  order lifecycle/fills
  portfolio cash/positions/margin
  fees/funding/liquidation
  turnover/attribution primitives
```

Điều này reuse native event engine và loại phần per-bar execution/accounting nặng, trong khi giữ linh hoạt Python cho research math.

### Target tape contract

```rust
pub struct TargetTape {
    offsets_by_bar: Box<[u32]>,
    symbol: Box<[u32]>,
    target_kind: Box<[u8]>, // units, weight, notional, exposure
    value: Box<[f64]>,
    rebalance_group: Box<[u32]>,
    flags: Box<[u16]>,
}
```

Policy resolve target → desired qty:

```text
target units
base/quote notional
portfolio weight using reference equity phase
risk-budget output already converted
```

### Rebalance semantics

P0 contract phải freeze:

- equity reference before/after market mark/funding;
- target rounding;
- sell-before-buy vs proportional/transactional;
- cash reservation;
- leverage cap;
- minimum trade/notional;
- partial acceptance;
- simultaneous target netting;
- target persistence vs one-shot instruction.

Rust implementation dùng `RebalancePlanner`:

```rust
fn plan_rebalance(
    targets: TargetSlice,
    account: &AccountState,
    marks: BarMarks,
    policy: &RebalancePolicy,
    out: &mut CommandBuffer,
) -> RebalanceSummary
```

### Two-phase rebalance

1. **Preview:** compute deltas, quantize, estimate fees/margin/cash.
2. **Resolve:** apply ordering/scaling/rejection policy.
3. **Commit commands:** append canonical order commands.
4. **Execute:** same event order engine.

Không mutate positions trực tiếp từ targets; luôn qua execution contract để fees/slippage/fills consistent.

### Portfolio risk models

V1 native:

- gross/net exposure;
- per-symbol/sector/venue caps từ precomputed group IDs;
- leverage and margin;
- max position/notional;
- cash buffer;
- simple concentration limits.

Complex covariance optimizer vẫn Python. Rust nhận constraints/approved targets.

### Multi-currency account foundation

Portfolio architecture cần:

```text
cash ledger per currency
FX mark table per bar/session
instrument settlement currency
fee currency
funding currency
base reporting currency
```

V1 có thể support single base currency nhưng type/layout không hardcode scalar cash. Feature capability phải honest.

### Attribution

Native counters/columns:

```text
pnl by symbol
fees by symbol/venue
funding by symbol
turnover by symbol/group
gross/net exposure path
rejected target amount/reason
execution shortfall vs target reference
```

Materialize only requested projection.

### Integration với current `native_portfolio.py`

Migration:

1. Freeze current target/reconciliation fixtures.
2. Extract target tape before Numba execution.
3. Add Rust executor accepting exact target tape.
4. Compare raw positions/cash/turnover before report.
5. Keep existing pandas report builder.
6. Promote Rust for supported simple portfolio modes.
7. Port additional constraints one by one with capabilities.

### Gate

- target tape Python/Numba vs Rust canonical trace;
- account reconciliation exact;
- rebalance ordering explicit;
- report metrics unchanged;
- unsupported allocator/risk semantics fail capability check;
- portfolio Rust reuses core account/order modules, no forked duplicate engine.

---

## P2.13 — Rust package/arbitrage execution architecture

### Core requirement

Arbitrage không chỉ là “nhiều orders cùng timestamp”. Cần package-level state, reservation, commit policy và residual exposure.

### Domain types

```rust
#[repr(transparent)]
pub struct PackageHandle(pub u64);

#[repr(u8)]
pub enum PackagePolicy {
    AtomicBar,
    BestEffort,
    Sequential,
    HedgeAfterPrimary,
}

#[repr(u8)]
pub enum PackageStatus {
    Planned,
    Reserved,
    PartiallyCommitted,
    Committed,
    Hedging,
    Completed,
    Failed,
    Unwound,
}
```

### Package tape

```rust
pub struct PackageTape {
    offsets_by_bar: Box<[u32]>,
    package_id: Box<[u64]>,
    policy: Box<[u8]>,
    leg_offsets: Box<[u32]>,
    leg_symbol: Box<[u32]>,
    leg_venue: Box<[u16]>,
    leg_side: Box<[i8]>,
    leg_qty: Box<[f64]>,
    leg_order_type: Box<[u8]>,
    leg_price_ticks: Box<[i64]>,
    hedge_ratio: Box<[f64]>,
    max_staleness_ns: Box<[i64]>,
    max_residual_notional: Box<[f64]>,
    flags: Box<[u16]>,
}
```

### Two-phase package execution

#### Phase 1 — Preflight

Per leg:

- market availability/staleness;
- quantity/price quantization;
- liquidity/fillability theo model;
- fee/funding/latency assumptions;
- margin/cash requirement;
- venue/instrument capability;
- risk/residual projection.

Aggregate:

```rust
struct PackagePreview {
    leg_previews: Range<LegPreview>,
    total_reservation: ReservationDelta,
    expected_residual: ExposureVector,
    admissible: bool,
    reject_code: PackageRejectCode,
}
```

#### Phase 2 — Reserve

Reserve collateral/cash/risk budget để leg execution không race với package khác cùng bar theo canonical ordering.

```text
available collateral
- existing order reservations
- package reservations
```

#### Phase 3 — Commit

Theo policy:

- `AtomicBar`: all legs preview fillable theo OHLC model, rồi commit all hoặc none;
- `BestEffort`: commit fillable, record residual;
- `Sequential`: execute canonical leg order;
- `HedgeAfterPrimary`: primary fills first, hedge generated from actual filled qty.

#### Phase 4 — Resolve residual/unwind

- hedge commands;
- timeout policy;
- forced unwind;
- residual exposure path;
- package PnL/fees attribution.

### Atomicity caveat

OHLC backtest atomicity là **simulation contract**, không phải bảo đảm venue thật. Metadata/report phải ghi `package_atomicity_model=bar_transaction` hoặc model tương ứng.

### Cross-venue clock

Cần shared global event clock hoặc merged tape:

```text
event timestamp
venue timestamp
symbol last update timestamp
staleness age
session/calendar flags
```

Không forward-fill quote rồi coi như current mà không staleness policy.

### Latency model

Package plan có:

```text
signal latency
routing latency per venue
exchange acknowledgement latency
fill observation latency
hedge latency
```

V1 có thể deterministic fixed bars/ns. Random latency phải seeded và traceable.

### Package indexes

```text
package -> leg handles
order handle -> package/leg
active packages by timeout bar
reservations by package
residual exposure by package
```

Không scan all orders để tìm package siblings.

### Package trace

Events:

```text
PACKAGE_PLAN
PACKAGE_REJECT
PACKAGE_RESERVE
LEG_SUBMIT
LEG_FILL
LEG_REJECT
PACKAGE_PARTIAL
HEDGE_SUBMIT
HEDGE_FILL
PACKAGE_COMPLETE
PACKAGE_TIMEOUT
PACKAGE_UNWIND
RESERVATION_RELEASE
```

Trace phase/sequence canonical.

### Starter fixtures

1. two-leg same-bar atomic success;
2. one leg unfillable atomic reject;
3. best-effort residual;
4. primary partial fill + hedge actual qty;
5. stale second venue;
6. insufficient combined margin;
7. two packages competing for collateral;
8. timeout/unwind;
9. fee makes apparent spread unprofitable;
10. funding/currency conversion across legs.

### Integration với current `core/arbitrage.py`

Current schema/planning được dùng làm public input. Thêm compiler:

```text
Python ArbitragePlan
  -> canonical PackageTape
  -> Python reference package executor
  -> Rust package engine
```

Không rewrite public planning ngay; validate parity trước.

### Gate

- package-level invariants pass;
- atomic policy all-or-none theo model;
- reservations never negative/leak;
- actual hedge qty derived from fills;
- cross-venue staleness explicit;
- package engine reuses account/order/lifecycle core;
- no “arbitrage support” claim chỉ vì multi-symbol orders chạy được.

---

## P2.14 — Parallelism: đúng tầng, deterministic và không oversubscribe

### Parallelize những gì

Ưu tiên:

1. independent scenarios/parameter sets;
2. independent walk-forward folds khi data/state contract cho phép;
3. independent audit serialization/compression chunks ngoài canonical engine;
4. precomputation theo symbol cho pure indicators;
5. selected risk calculations với deterministic reduction.

Không ưu tiên:

- một event timeline single account;
- lifecycle transitions cùng bar có ordering dependency;
- parent/OCO/package commits;
- fills/account mutation dùng shared locks.

### Rayon/work pool architecture

Rayon optional feature ở `quantbt-batch`, không trong core event engine.

```rust
scenario_chunks
    .par_iter()
    .for_each(|chunk| run_chunk_with_worker_local_state(...));
```

Tránh nested parallelism:

- nếu Python/Optuna đã parallel processes, Rust worker count phải configurable;
- default worker policy xem environment/caller hint;
- diagnostics báo actual workers;
- Numba/BLAS threads không chạy cùng native worker pool trong same phase nếu gây oversubscription.

### Deterministic output

- preallocate result rows by scenario index;
- no shared append ordering;
- no unordered hash iteration ảnh hưởng trace/result;
- stable top-K tie-break;
- fixed reduction tree nếu parallel aggregate cần exact reproducibility;
- test worker counts 1,2,4,8.

### False sharing

Worker output/state align/pad only after profile. Potential hot arrays:

```text
scenario status
metric rows
worker counters
```

Write disjoint chunks. Aggregate counters worker-local rồi reduce.

### Cancellation

Batch user interrupt/cancel:

- atomic cancellation flag checked at safe bar/chunk intervals;
- no Python C-API call from worker;
- partial result policy explicit;
- sessions cleanly dropped;
- audit chunks closed/marked incomplete.

### Free-threaded Python

PyO3 0.29/Python future free-threaded support không tự làm Python strategy callback parallel-safe. Rules:

- native pure Rust batch có thể parallel sau detach;
- Python callbacks require Python object/thread-safety policy;
- default arbitrary callback batch không parallel threads trong same interpreter nếu strategy mutability uncertain;
- process-level Python parallelism vẫn là option;
- capability descriptor báo free-threading support thực tế.

### Gate

- exact results across worker counts;
- speedup curve reported, not assumed;
- no oversubscription by default benchmark config;
- cancellation leaves no poisoned cache/session;
- ThreadSanitizer/loom-style tests where practical for shared structures.

---

## P2.15 — PyO3 boundary tối ưu đúng cách

Repo hiện dùng PyO3/numpy 0.29. Mục tiêu không phải bỏ PyO3; mục tiêu là làm binding cost amortized và data-oriented.

### Rule 1 — Call granularity

```text
static/IR single run: O(1) calls
batch: O(1) per batch/chunk
sparse callback: O(number_of_wakes)
arbitrary callback: O(number_of_bars), clearly labeled
```

### Rule 2 — Detach interpreter cho Rust-only work

Binding shape:

```rust
#[pymethods]
impl PyPreparedSession {
    fn run_ir(&mut self, py: Python<'_>, request: PyRunRequest) -> PyResult<PyRawResult> {
        let owned_request = extract_and_validate(request)?;
        let result = py.detach(|| self.inner.run_ir(owned_request));
        // `detach` reacquires the interpreter before returning.
        convert_result(py, result)
    }
}
```

Thực tế API conversion có thể khác theo ownership/lifetime, nhưng nguyên tắc:

- không mang `Bound<'py, ...>` borrowed object vào detached closure;
- extract/copy/own inputs trước detach;
- native workers không gọi Python APIs;
- convert errors/result sau attach.

### Rule 3 — Minimize Python objects crossing boundary

Input:

- typed arrays/pyclasses;
- primitive scalars;
- prepared native handles;
- no nested dict/list per bar.

Output:

- one typed result object;
- column arrays;
- scalar diagnostics struct/dict built once;
- no Python object per fill/event unless public adapter requests.

### Rule 4 — Avoid accidental copies

Instrument counters around:

```text
PyReadonlyArray -> contiguous view
view -> Vec copy
Vec -> Box/Arc
Rust Vec -> NumPy
NumPy -> pandas
```

For each array expose:

```text
input_contiguous
input_dtype_exact
copy_count
bytes_copied
copy_reason
```

### Rule 5 — Prepared handles

Python should hold:

```text
PyPreparedMarket
PyPreparedStrategyProgram
PyPreparedSessionTemplate
```

Not pass all market arrays every run.

### Rule 6 — Reference/lifetime discipline

- native state contains no `Py<PyAny>` except adapter-owned callback path;
- pure Rust session types satisfy required sendability only when true;
- result ownership explicit;
- no dropping Python objects while detached unless PyO3 contract safely handles it;
- consider PyO3 reference-pool tuning only after audit of all `Py<T>` drops and benchmark; never enable unsafe optimization blindly.

### Rule 7 — Exception cost not in normal branch

Native core returns typed `Result`. Build verbose Python message only on error. No format strings/strings per bar.

### Rule 8 — Binding compatibility

Expose:

```python
_quantbt_native.get_descriptor()
_quantbt_native.prepare_market(...)
_quantbt_native.compile_strategy_ir(...)
_quantbt_native.create_session(...)
```

All objects carry protocol/build fingerprints and reject cross-version mixing.

### Alternative binding technologies

Không đổi sang CFFI/HPy/C API chỉ vì PyO3 bị nghi “chậm”. Với one-call-per-run, PyO3 overhead thường không phải hot cost. Chỉ đánh giá alternative khi profiler cho thấy binding conversion/ABI là dominant sau P1/P2, và phải tính:

- maintainability;
- NumPy integration;
- free-threading;
- exception/lifetime safety;
- wheel build complexity.

### Gate

- detached native run verified;
- no borrowed Python refs in Rust-only closure;
- PyO3 calls/copies counters meet workload expectations;
- result lifetime/GC stress pass;
- current Python versions/wheel matrix pass.

---

## P2.16 — CPU, compiler, allocator, SIMD và profiling toolbox

### Build profiles

Current release đã có:

```toml
opt-level = 3
lto = "thin"
codegen-units = 1
strip = "symbols"
overflow-checks = false
```

Đây là baseline tốt. Thử nghiệm có kiểm soát:

```toml
[profile.release]
opt-level = 3
lto = "fat"            # benchmark against thin; not assumed better
codegen-units = 1
panic = "abort"         # only if PyO3/error policy and diagnostics allow
```

Không đổi `panic=abort` trước khi xác định cách xử lý internal panic và wheel crash semantics.

### Portable wheels vs local native builds

Public wheels:

- target baseline CPU của platform policy;
- không dùng global `-C target-cpu=native`;
- có thể runtime-dispatch selected kernels bằng `is_x86_feature_detected!`/target-feature modules sau benchmark;
- metadata ghi CPU feature path.

Local/source build:

- optional `QUANTBT_NATIVE_CPU=native`;
- user rõ rằng wheel không portable;
- benchmark report ghi flags.

### PGO

Profile-guided optimization là candidate sau khi workload corpus ổn định:

1. build instrumented native module;
2. chạy representative E0/E3/E4/E5/E6 corpus;
3. merge profile;
4. build optimized wheel;
5. compare all workloads, code size và cold start;
6. regenerate profile khi control flow lớn thay đổi.

Không train PGO chỉ trên one-symbol static tape rồi ship cho portfolio/package.

### BOLT/post-link

Chỉ cân nhắc nếu toolchain/platform release hỗ trợ ổn định và PGO chưa đủ; complexity CI/wheel phải đáng với gain.

### SIMD

Ưu tiên SIMD/auto-vectorization cho homogeneous numeric loops:

- mark-to-market active positions;
- exposure/margin contribution arrays;
- signal/indicator preprocessing;
- batch metric updates;
- target delta calculations.

Không ưu tiên first cho branchy order lifecycle/OCO/parent logic.

Portable SIMD trong standard library có thể vẫn nightly/experimental ở toolchain; public release nên giữ stable Rust. Options:

- compiler auto-vectorization với clean slices/loops;
- `std::arch` target-specific guarded kernels;
- stable SIMD crates only after dependency/security review;
- scalar fallback exact.

### Floating-point rules

- không `fast-math` cho canonical engine;
- không reassociate reductions nếu làm thay trace/accounting;
- FMA differences cần evaluate cross-platform reproducibility;
- integer ticks/steps cho compare/quantization;
- `mul_add` chỉ nếu contract/version chấp nhận rounding difference hoặc dùng consistent both backends.

### Allocator

Không đổi allocator trước profile. Candidate jemalloc/mimalloc có thể giúp batch allocation-heavy nhưng:

- wheel binary/license/platform complexity;
- interaction with Python allocator;
- RSS behavior;
- small-session performance.

Sau arena/buffer reuse, allocation pressure có thể đã thấp. Gate allocator bằng E0–E6, không microbench allocation riêng.

### Hashing

Standard `HashMap` random hashing cost có thể hot ở arbitrary external IDs. Options:

- dense internal IDs/direct handles;
- deterministic fast hasher for trusted internal keys;
- preserve DoS-safe map at untrusted boundary;
- do not let hash iteration define canonical order.

### Profiling tools

Recommended toolbox:

```text
Criterion or equivalent Rust microbench
cargo bench
Linux perf stat/record
flamegraph/samply
Valgrind/Callgrind or iai-callgrind for stable instruction counts
heaptrack/dhat for allocation
cargo bloat
llvm-lines
Miri for unsafe/lifetime tests
AddressSanitizer/UndefinedBehaviorSanitizer where compatible
ThreadSanitizer for batch/shared code where compatible
proptest/cargo-fuzz
```

Python facade:

```text
py-spy/scalene/cProfile for callback/adaptation
tracemalloc for Python allocations
RSS sampling at process level
```

### Optimization acceptance template

Mỗi Rust perf PR ghi:

```text
hypothesis
profile evidence
changed data/control flow
correctness proof/tests
before/after E-class matrix
allocation/RSS effect
code size/build time effect
platform effect
rollback switch
```

### Gate

- no compiler flag-only promotion without workload matrix;
- stable Rust public build unless explicitly approved;
- SIMD scalar parity;
- PGO profile representative;
- allocator/hash changes evidence-based;
- debug/profiling symbols artifact available privately even if release stripped.

---

## P2.17 — Unsafe policy và formalized invariants

### Default

Safe Rust trước. Unsafe chỉ được dùng khi:

1. profile xác nhận hotspot;
2. safe implementation tồn tại làm reference;
3. invariant có thể viết rõ;
4. benchmark cho gain material;
5. Miri/sanitizer/fuzz tests bao phủ;
6. owner review bắt buộc.

### Candidate unsafe zones hợp lý sau cùng

- unchecked array indexing trong proven fixed-shape inner numeric loop;
- zero-copy buffer ownership handoff;
- target-specific SIMD intrinsics;
- custom arena bitset operations.

Không dùng unsafe để:

- borrow mutable NumPy across detached execution;
- alias session/result buffers;
- bypass generation checks trong external APIs;
- mutate shared state across workers;
- cast arbitrary command bytes without validation.

### Safety comment template

```rust
// SAFETY:
// 1. `bar_base + symbol < market.len()` because ...
// 2. market dimensions are validated in PreparedMarket::new and immutable.
// 3. this loop bounds symbol to 0..n_symbols.
// 4. no mutation/reallocation occurs while the slice is borrowed.
```

### Unsafe budget

Track:

```text
unsafe blocks count
unsafe functions count
lines of unsafe
owner
covered invariant test
last audit date
```

### Gate

- `cargo miri test` for supported core tests;
- sanitizer jobs;
- fuzz corpus around boundary/arena;
- no unsafe without comment/proof/benchmark;
- Python process crash corpus = 0.

---

## P2.18 — Exact hotspot patch map từ code snapshot hiện tại

### `rust/native_event/src/full.rs`

#### Replace nested row conversion

Current:

```rust
FillBuffer::rows() -> Vec<Vec<f64>>
EventBuffer::rows() -> Vec<Vec<i64>>
ActiveOrderBuffer::rows() -> Vec<Vec<f64>>
```

Target:

- remove from fast path;
- move SoA buffers directly into typed result;
- binding converts columns once;
- keep debug row conversion only under test/helper.

#### Remove `positions.clone()` per step unless requested

Target:

- `PositionProjection::None/Changed/Full`;
- per-step view/delta for callback;
- final positions moved once;
- dense per-bar positions only explicit audit path.

#### Replace `orders: Vec<OrderState>` + compaction

Target:

- `OrderArena` generational slots;
- free list;
- no hot compaction;
- terminal state emitted then slot released.

#### Replace linear scans

Target indexes:

```text
expiry_by_bar
active_by_symbol
children_by_parent
oco_groups
group/tag index conditional
```

#### Use `opens` according to versioned policy

- V2 legacy close behavior frozen;
- V3 actual next-open uses open/gap model;
- no unused semantic field ambiguity.

#### Split monolith

Move to engine crate modules listed in P2.1.

### `rust/native_event/src/lib.rs`

Target:

- binding-only extraction/validation/ownership;
- no domain/account/matching logic;
- use `Python::detach` for full native runs;
- typed result arrays;
- protocol 0.5 descriptor;
- preserve 0.4 class adapter during migration.

### `src/quantbt/backends/_native_event_rust.py`

#### Remove shadow-state

Delete only after projection API supports consumers:

```text
scheduled/pending/order lifecycle mirrors
equity/position accounting mirrors
fill/event duplicate history
online score duplicate
```

#### Replace symbol lookup

Preparation interner:

```text
symbol -> integer ID O(1)
```

No list scan in commands.

#### Separate drivers

```text
run_static
run_ir
run_sparse_callback
run_legacy_callback
```

#### Avoid per-bar pandas/dataclasses

Numeric view path uses int timestamp/arrays; compatibility adapter materializes only when selected.

### `src/quantbt/backends/native_event.py`

- retain readable Python oracle;
- split lifecycle/accounting/matching;
- add canonical trace hooks;
- do not optimize away clarity until Rust stable;
- use same generated contracts/enums;
- support IR reference interpreter for differential tests.

### Score facade

Current score path that obtains dense/audit output then computes Python metrics must be replaced by:

```text
native ScoreSink + MetricSet
```

Compatibility check:

- same score/NaN/ddof conventions;
- score result metadata includes metric schema version;
- audit rerun optional selected scenarios only.

### Endpoint/report paths

- no forced Python replay for normal Rust audit;
- no pandas before engine finish;
- planner selects Rust only when workload path promoted.

---

## P2.19 — Recommended performance promotion gates

Các con số dưới đây là **target gate đề xuất**, phải calibrate trên frozen machine/corpus; chúng không phải claim hiện trạng.

### Correctness gate áp dụng trước mọi perf gate

```text
P0 canonical trace exact
all invariants pass
single/batch parity
worker-count determinism
installed-wheel parity
no hidden fallback
```

Không trade correctness lấy speed.

### E0 static tape

Recommended:

```text
Rust score end-to-end >= 2.0× Python standard ở medium/large
Rust compact >= 1.75×
Rust audit >= 1.5× ở large high-churn
no >10% regression ở low-churn small without documented routing
pyo3_calls <= small constant/run
```

### E1 arbitrary Python callback

Recommended:

```text
no correctness regression
no >10–15% facade regression versus current baseline
planner may choose Python when faster
metadata clearly says callback compatibility path
```

Không đặt mục tiêu Rust phải thắng mọi arbitrary callback.

### E2 sparse/numeric callback

Recommended:

```text
callback count matches wake schedule
median native bars/call materially >1 on sparse fixtures
>=1.25× over legacy callback on medium workloads
projection bytes and Python allocations reduced >=50% where requirements minimal
```

### E3 strategy IR

Recommended:

```text
one call/run
>=2× versus equivalent legacy Python callback on medium/large
>=1.5× versus optimized numeric callback
Grid/DCA/bracket exact parity
strategy execution share no longer dominated by PyO3/Python
```

### E4 portfolio

Recommended:

```text
>=1.5× current standard portfolio execution core on medium/large supported modes
report excluded and included timings both shown
no account reconciliation drift
active-position scaling close to O(active positions)
```

### E5 package

Performance secondary to correctness initially:

```text
package semantics/canonical trace pass
no full-order scans
reservations/indexes scale with active packages/legs
large package audit RSS within chunk budget
```

### E6 batch

Recommended:

```text
0 market copies/trial
O(1) boundary per batch/chunk
single-thread batch faster than Python loop by >=1.5× on N>=100
parallel efficiency >=60% through 8 physical cores on representative native workloads
results exact across worker counts
RSS plateaus at shared market + worker states + fixed outputs
```

### Memory gates

```text
no unbounded growth over 10k reset/runs
high-churn arena memory scales with peak live orders + requested history
score output memory approximately O(symbols + active state), not O(fills/events)
audit streaming memory approximately O(chunk size)
peak RSS no >10–15% regression unless justified by >material speed gain and budget
```

### Packaging gates

```text
CPython 3.11/3.12/3.13 clean wheels
manylinux supported baseline
runtime descriptor exact
native unavailable/mismatch behavior correct
portable CPU build
```

---

## P2.20 — P2 exit checklist

```text
[ ] Rust workspace extracted; engine crate has no PyO3 dependency
[ ] internal ABI 0.5 typed IDs/enums/tapes implemented
[ ] generation-safe order arena replaces hot compaction
[ ] active/expiry/parent/OCO indexes proven
[ ] adaptive matching candidate strategy benchmarked
[ ] specialized score/compact/audit kernels exist
[ ] static/IR/portfolio/package drivers separated
[ ] incremental account/margin cache correct
[ ] active-position indexing implemented
[ ] flat SoA output replaces nested rows
[ ] no per-bar position clone unless requested
[ ] native online score metrics replace audit-then-score
[ ] Rust result ownership/lifetime proven
[ ] strategy IR v1 + Python reference interpreter implemented
[ ] Grid/DCA/bracket IR fixtures pass
[ ] scenario batch runner implemented
[ ] deterministic parallel batch pass
[ ] portfolio target executor reuses core engine
[ ] package/arbitrage two-phase executor reuses core engine
[ ] PyO3 full native runs detach interpreter
[ ] boundary calls/copies meet workload contracts
[ ] profiling/unsafe policy enforced
[ ] E0–E6 benchmark and memory promotion matrix pass
```

P2 chưa hoàn tất nếu Rust chỉ nhanh trên static microbenchmark nhưng public optimize/research paths vẫn materialize audit hoặc gọi Python từng bar mà metadata không phân biệt.

---

# P3 — Technical debt, package productization và promotion governance

## P3 objective

P3 biến P0–P2 từ một engine tối ưu trong source tree thành sản phẩm có thể cài, kiểm chứng, rollback và mở rộng lâu dài.

Sau P3:

- chỉ có một source of truth cho Python package;
- execution contracts/capabilities/enums/trace schema được sinh từ một registry versioned;
- core wheel và native wheel có exact compatibility handshake;
- `auto` chọn backend theo workload + contract + promotion table, không chỉ “Rust installed”;
- CI phân biệt unit/parity/fuzz/wheel/performance/release gates;
- deprecated API có deadline/xóa thực sự;
- benchmarks reproducible và regression có owner;
- Rust supply chain/unsafe/security được quản trị;
- docs không claim capability vượt quá installed artifact.

---

## P3.0 — Một source tree Python duy nhất

### Vấn đề

Root package mirror và `src/quantbt` cùng tồn tại tạo rủi ro:

- import nhầm source tùy working directory/PYTHONPATH;
- sửa một copy nhưng test copy khác;
- wheel không giống source-tree run;
- code review khó biết source authoritative;
- duplicate files làm search/refactor sai;
- benchmark có thể chạy module không được package.

### Target

```text
src/quantbt/ = authoritative source
quantbt/ root mirror = removed
```

Nếu một tool bắt buộc root mirror trong transition, mirror phải generated/read-only và CI verify byte equality; không chấp nhận sửa tay.

### Migration plan

1. Thêm test in ra `quantbt.__file__` và fail nếu ngoài expected `src`/installed site-packages.
2. Chạy toàn test/benchmark với editable install chuẩn.
3. Inventory root-only imports/data.
4. Chuyển package data/compatibility.
5. Đánh dấu root mirror generated, CI diff.
6. Xóa root mirror trong breaking-cleanup release.
7. Add guard: repository-root direct import without install phải fail với hướng dẫn rõ, hoặc configure test runner đúng.

### Gate

- source-tree, editable install và built wheel cùng module hashes cho production files;
- no duplicate authoritative Python modules;
- benchmark metadata ghi module paths;
- release artifact test không phụ thuộc repository root.

---

## P3.1 — Module ownership và giới hạn kích thước

### Ownership map

Mỗi top-level subsystem có owner/reviewer:

```text
contracts + trace           correctness owner
Python oracle              reference semantics owner
Rust domain/engine         native core owner
strategy IR                compiler/runtime owner
portfolio                  portfolio owner
package/arbitrage          package execution owner
PyO3/package               release/native packaging owner
benchmarks                 performance owner
```

Một người có thể giữ nhiều role, nhưng trách nhiệm phải rõ.

### Module size guideline

Không dùng LOC như gate duy nhất, nhưng trigger review khi:

```text
Python module > 800–1,000 LOC
Rust module > 800–1,000 LOC
function > 100–150 LOC
public class owns > 3 architectural responsibilities
```

Exceptions phải có lý do. Mục tiêu là tránh tái tạo `endpoint.py`, `native_event.py`, `full.rs` monolith.

### Internal API visibility

Rust:

- `pub(crate)` mặc định;
- chỉ domain/protocol types thật cần mới `pub`;
- PyO3 wrapper không leak internal structs.

Python:

- public exports tập trung `quantbt.api`/package root;
- internal modules prefix/`__all__` rõ;
- type-checking imports không kéo native module.

### ADR bắt buộc cho thay đổi lớn

```text
docs/adr/
  0001-versioned-event-clock.md
  0002-backend-spi.md
  0003-rust-workspace.md
  0004-generational-order-arena.md
  0005-strategy-ir.md
  0006-batch-determinism.md
  0007-portfolio-target-contract.md
  0008-package-atomicity.md
  0009-native-wheel-compatibility.md
```

ADR ghi:

- context;
- decision;
- alternatives;
- consequences;
- migration/rollback.

### Gate

- code ownership rules in repository;
- new monolithic cross-layer imports fail review/CI;
- public API inventory generated;
- ADR linked từ implementation PR.

---

## P3.2 — Single source of truth cho schemas, enums và capabilities

### Vấn đề boolean capability phẳng

Một set như:

```text
supports_market
supports_limit
supports_funding
supports_multi_symbol
```

không đủ mô tả:

- contract version nào;
- profile/output level nào;
- strategy mode nào;
- margin/liquidation policy nào;
- package/portfolio semantics nào;
- platform/wheel nào đã promoted.

### Contract registry

Tạo machine-readable source, ví dụ YAML/TOML/JSON Schema:

```yaml
schema_version: 1
contracts:
  - id: event_v2_next_bar_close
    clock: v2
    order_types: [market, limit, stop_market, stop_limit]
    tif: [gtc, ioc, fok, gtd]
    account_models: [gross_cross_v1]
    profiles: [score, compact, audit]
    strategy_modes: [static_tape, python_callback, ir_v1]
    trace_schema: 2

backends:
  python:
    implementations: [oracle, optimized]
  rust:
    protocol: 5
```

### Generate artifacts

Từ registry sinh:

```text
Python enums/dataclasses/type literals
Rust repr enums/constants
JSON schema
capability descriptor validators
compatibility table docs
conformance test parameters
trace/event code documentation
ABI fingerprint
```

CI fail nếu generated files dirty.

### Capability descriptor dimensions

```python
@dataclass(frozen=True)
class WorkloadCapability:
    contract_id: str
    strategy_modes: frozenset[str]
    profiles: frozenset[str]
    max_symbols: int | None
    account_models: frozenset[str]
    portfolio_modes: frozenset[str]
    package_policies: frozenset[str]
    trace_schemas: frozenset[int]
    maturity: Literal["experimental", "certified", "promoted"]
    platforms: tuple[PlatformConstraint, ...]
```

### Capability resolution result

```python
BackendDecision(
    selected="rust",
    reason="PROMOTED_STATIC_TAPE_AUDIT",
    matched_capability_id="...",
    rejected_candidates=(...),
)
```

No opaque boolean.

### Versioning

- adding optional capability: compatible descriptor update;
- changing enum code/schema: protocol major/minor policy;
- removing contract: deprecation cycle;
- trace/command/result ABI fingerprints independent but bundled.

### Gate

- Python/Rust generated enum values exact;
- descriptor validates at import;
- docs table generated from same registry;
- no hand-maintained duplicate capability lists;
- package mismatch detected before run.

---

## P3.3 — API/contract deprecation matrix

### Separate versions

Không dùng một version cho mọi thứ:

```text
Python package version
native package version
native protocol version
command ABI version
result ABI version
execution contract version
trace schema version
strategy IR version
```

Release manifest map chúng lại.

### Compatibility policy example

```text
core 1.2.x supports native protocol 5.x
native 0.5.x supports core protocol range [5.0, 5.3]
command ABI 0.4 accepted through translator until core 2.0
execution contract v2 reproducible indefinitely or archived runner
trace schema n readable for at least two release lines
IR v1 stable within declared op semantics
```

### Deprecation record

```yaml
feature: NativeStrategyContext legacy materialization
introduced: 1.0
replacement: StrategyContextView
warning_from: 1.3
error_from: 2.0
removal_target: 2.1
owner: ...
migration_doc: ...
```

### Legacy ABI 0.4

- keep translator, not duplicate engine;
- conformance tests ensure translation;
- diagnostics report legacy path;
- no new features added to legacy ABI;
- remove only after public release window and clean usage data/decision.

### Historical reproducibility

Khi contract cũ deprecated:

- exact contract remains selectable if feasible;
- archive wheel/container/lockfile + corpus;
- result metadata stores contract ID;
- no alias silently points to new semantics.

### Gate

- all deprecations machine-readable;
- warnings tested;
- no permanent compatibility shim without owner/deadline;
- historical result manifests can choose correct contract/backend version.

---

## P3.4 — Dual-package architecture: core Python + native Rust

### Current state to change

Core package is `quantbt-engine`; native optional dependency is intentionally empty until wheel gates pass. Target architecture:

```text
quantbt-engine
  pure Python public API, oracle, planner, reports

quantbt-native
  PyO3 extension and native engine
```

### Dependency direction

`quantbt-native` should not require importing private implementation internals from core to initialize. Runtime handshake uses protocol descriptors.

Core optional extra after certification:

```toml
[project.optional-dependencies]
native = [
  "quantbt-native==<exact compatible release>; platform filters..."
]
```

Exact mapping can be generated. Avoid broad range that allows incompatible native ABI.

### Version strategy

Two reasonable choices:

#### Lockstep public version

```text
quantbt-engine 1.2.0
quantbt-native 1.2.0
```

Dễ hiểu/distribute. Protocol still separate internally.

#### Independent version + generated compatibility map

```text
engine 1.2.0
native 0.5.3
```

Linh hoạt nhưng user support khó hơn.

Recommendation for early dual-package: lockstep release tags/public version, internal protocol version separate.

### Import flow

```python
try:
    import _quantbt_native
except ImportError as exc:
    native_status = Unavailable(reason=...)
else:
    descriptor = _quantbt_native.get_descriptor()
    native_status = verify_descriptor(descriptor, core_descriptor)
```

Import only when needed/capability diagnostics, unless cheap lazy probe cached.

### Wheel build

Use a dedicated maturin/PyO3 workflow or equivalent native build system. Requirements:

- build from exact release tag;
- embed git SHA/dirty flag/toolchain;
- manylinux audit;
- no undeclared shared-library dependency;
- import test in minimal container;
- wheel filename/platform tags correct;
- source distribution policy explicit.

### CPython ABI strategy

Evaluate per exact PyO3/numpy constraints:

- version-specific wheels for CPython 3.11/3.12/3.13 are simplest/safest initially;
- abi3 may reduce matrix but NumPy C-API/binding constraints and performance/support need validation;
- do not switch to abi3 solely to reduce CI before installed tests.

### Clean-index tests

Test install from staged index/artifacts only:

```text
pip install quantbt-engine
pip install quantbt-engine[native]
pip install quantbt-native + quantbt-engine exact
mismatched versions intentionally
native missing
corrupt/unsupported platform simulation
```

### Runtime handshake fields

```text
core_package_version
native_package_version
protocol_min/max
command_abi_versions
result_abi_versions
contract_registry_fingerprint
trace_schema_versions
IR versions
rustc target/profile
CPU baseline/features
build SHA
```

### Gate

- native extra no longer empty only after matrix passes;
- core-only remains fully functional;
- explicit Rust mismatch fail-fast;
- auto mismatch falls back with structured reason;
- installed artifact behaves like source baseline;
- no source-tree path leakage.

---

## P3.5 — `auto` backend promotion theo workload

### Không dùng rule `native installed => Rust`

Backend decision inputs:

```text
contract
strategy mode
profile/output
symbols/bars/order churn estimate
account/portfolio/package model
native availability/certification
platform
user policy
historical performance table
```

### Promotion stages

#### Stage A — Explicit-only

```text
backend="rust" supported for certified E0 static paths
backend="auto" remains Python
```

#### Stage B — Auto static/IR

Auto selects Rust cho:

- static command tape medium/large;
- IR v1 supported strategies;
- score/compact/audit workloads vượt frozen gates.

Python cho:

- arbitrary small callbacks;
- unsupported context/model;
- native unavailable.

#### Stage C — Portfolio

Auto Rust chỉ cho target tape/account models đã certified.

#### Stage D — Package/arbitrage

Auto Rust theo package policy/venue clock models đã certified.

### Routing table

Machine-readable:

```yaml
promotions:
  - workload: event_static
    contract: event_v2_next_bar_close
    profiles: [score, compact, audit]
    backend: rust
    min_bars: 10000
    maturity: promoted

  - workload: python_callback_every_bar
    backend: python
    reason: callback_boundary_dominant
```

Thresholds không cần tự động hardware-specific v1; conservative static table + override tốt hơn hidden calibration.

### User override

```text
backend="python"
backend="rust"
backend="auto"
backend_policy="prefer_native" | "prefer_compatibility" | "certified_only"
```

Explicit choice luôn reflected metadata.

### Rollback switch

- environment variable emergency disable native;
- config flag;
- remote feature flag only nếu package/service context phù hợp, không tạo nondeterministic local behavior;
- release note/changelog;
- fallback reason observable.

Example:

```text
QUANTBT_DISABLE_NATIVE=1
QUANTBT_NATIVE_PROMOTION_MAX=static_ir
```

### Gate

- routing decision snapshot tests;
- no silent backend change between same environment/config/version;
- result metadata includes decision reason/table version;
- emergency rollback tested;
- auto only promotes workload after installed-wheel/perf/correctness gate.

---

## P3.6 — Benchmark governance và regression CI

### Three tiers

#### Tier 1 — PR smoke

- seconds/minutes;
- small deterministic fixtures;
- catches >large regression;
- call/copy/allocation counters;
- not noisy wall-time hard fail for tiny deltas.

#### Tier 2 — Nightly dedicated machine

- full E0–E6 matrix;
- medium/large;
- p50/p95, RSS, perf counters;
- compare rolling baseline;
- alert owner.

#### Tier 3 — Release certification

- frozen hardware/container;
- clean wheels;
- all Python versions/platforms;
- benchmark report artifact signed/attached;
- promotion table generated only from passed set.

### Regression budgets

Per phase/workload:

```yaml
E3_GRID_SCORE_MEDIUM:
  total: +5%
  engine: +3%
  rss: +10%
  pyo3_calls: exact <= 2
  callbacks: exact 0
```

Use statistical method and rerun policy; do not fail PR on 1% noisy drift.

### Baseline management

- baseline tied to commit/release;
- update requires explicit review and explanation;
- never overwrite historical data;
- hardware/toolchain metadata mandatory;
- results machine-readable + human summary.

### Profiling artifacts

For detected regression:

- flamegraph/perf diff;
- allocation diff;
- changed counters;
- binary size;
- commit range.

### Anti-gaming

- same semantics/fingerprint;
- same output/profile;
- include preparation/adaptation in end-to-end;
- no skipping audit fields;
- no cache warm in one backend only;
- no comparing static Rust to callback Python as equivalent;
- exact dataset manifest.

### Gate

- every promoted workload has stable benchmark ID;
- release report reproducible;
- regression waiver has owner/expiry;
- performance table feeds `auto` only after correctness certification.

---

## P3.7 — Generated conformance corpus và test matrix control

### Problem

Manual tests across Python/Rust/replay/contract versions/portfolio/package grow combinatorially.

### Declarative case schema

```yaml
id: stop_limit_gap_v3
market: ...
instruments: ...
commands: ...
contract: event_v3_next_open
expected:
  trace: ...
  invariants: ...
capabilities:
  python: required
  rust: required
```

Generate:

- Python oracle test;
- Rust engine test;
- PyO3 binding test;
- installed-wheel test;
- trace fixture;
- documentation example where relevant.

### Test layers

```text
pure domain unit tests
pure engine unit tests
state-machine property tests
Python oracle tests
cross-backend differential tests
binding/lifetime tests
public API tests
installed-wheel tests
fuzz/nightly soak
benchmark correctness precheck
```

### Corpus minimization

When fuzz finds failure:

1. minimize command/market tape;
2. store fixture with bug ID;
3. include exact contract/seed/build;
4. add regression test both Python/Rust;
5. classify root cause.

### Combinatorial strategy

Pairwise/generated coverage for broad matrix, exhaustive for small critical state machines:

```text
order type × TIF × gap/intrabar policy
parent × OCO × amend/cancel
margin × funding × liquidation phase
package policy × leg failure
```

### Gate

- same corpus drives all backends;
- every production bug becomes permanent minimized fixture;
- random seeds reproducible;
- flaky/nondeterministic tests treated as correctness bugs, not rerun-until-pass.

---

## P3.8 — Stable diagnostics và observability contract

### Result metadata

```python
result.metadata.execution = {
    "plan_fingerprint": ...,
    "backend": "rust",
    "backend_reason": ...,
    "native_protocol": 5,
    "contract": ...,
    "strategy_mode": "ir_v1",
    "profile": "score",
    "output_projection": ...,
    "trace_fingerprint": ...,
    "prepared_cache_hit": True,
}
```

### Performance diagnostics

Optional structured object, not log parsing:

```python
result.diagnostics.performance
result.diagnostics.boundary
result.diagnostics.memory
result.diagnostics.lifecycle
result.diagnostics.account
```

### Stable counters

Version counter schema. A removed/renamed counter follows deprecation, because benchmark tooling relies on it.

### Logging

- no per-bar logs by default;
- structured warning once per run;
- verbose trace through sink, not logging;
- native internal error includes IDs/codes, Python maps names;
- no sensitive strategy data dumped automatically.

### Telemetry privacy

Library default no network telemetry. User can export local benchmark/diagnostic artifacts explicitly.

### Gate

- backend/fallback never ambiguous;
- diagnostics overhead measured/disableable;
- schema versioned;
- benchmark scripts consume structured data.

---

## P3.9 — Documentation, compatibility table và user migration

### Documents required

```text
docs/architecture/execution-plan.md
docs/architecture/native-rust.md
docs/contracts/event-clock.md
docs/contracts/order-lifecycle.md
docs/contracts/accounting.md
docs/contracts/portfolio-targets.md
docs/contracts/package-execution.md
docs/performance/workload-classes.md
docs/performance/benchmarking.md
docs/native/install.md
docs/native/capabilities.md
docs/native/troubleshooting.md
docs/migration/context-writer-ir.md
```

### Capability table generated

Show exact:

```text
backend
contract
strategy mode
profile
account model
portfolio/package support
maturity
platform
```

Không dùng marketing phrase “Rust supported” chung chung.

### Migration examples

Legacy:

```python
def strategy(ctx):
    return [OrderCommand(...)]
```

Intermediate:

```python
def strategy(ctx: StrategyContextView, out: CommandWriter):
    out.market(...)
```

Native IR:

```python
program = qbt.ir.strategy(...)
prepared = qbt.prepare(..., strategy=program)
```

Batch:

```python
prepared.score_batch(parameter_matrix)
```

### Explain semantics

User-facing docs phải nói rõ:

- next-bar-close legacy vs next-open;
- OHLC intrabar approximation;
- package atomicity simulation model;
- arbitrary Python callback boundary;
- how `auto` chooses backend;
- how to reproduce historical result.

### Gate

- docs examples run in CI;
- generated table matches descriptor;
- release notes include promotion/deprecation/contract changes;
- no stale claim after capability change.

---

## P3.10 — Rust supply chain, safety và release integrity

### Dependency policy

- minimize kernel dependencies;
- pin through `Cargo.lock` for builds;
- automated vulnerability audit;
- license policy;
- dependency update PR runs correctness/perf matrix;
- avoid unmaintained crate in critical arena/serialization path.

Tools/policies can include:

```text
cargo audit
cargo deny
SBOM generation
provenance/attestation
reproducible build checks where practical
```

### Build provenance

Embed:

```text
git SHA
dirty flag
rustc version
target triple
Cargo.lock fingerprint
features
build profile
contract registry fingerprint
```

### Artifact signing

- publish through protected release workflow;
- signed/tagged source;
- checksums/provenance attached;
- PyPI publishing token scoped/OIDC if available;
- no manual local wheel promoted as release.

### Unsafe audit

P2 unsafe budget becomes release artifact:

- list blocks/functions;
- safety owner;
- tests;
- audit date.

### Fuzz/security surfaces

- malformed NumPy shapes/dtypes;
- integer overflow dimensions;
- command ABI codes;
- stale handles;
- huge declared capacities;
- adversarial external IDs;
- package relationship cycles;
- IR validation/jumps/resource limits;
- output-size denial of service.

### Gate

- no critical known vulnerability;
- license pass;
- provenance present;
- malformed inputs never cause UB/process crash;
- release built only by CI workflow.

---

## P3.11 — Cleanup/deletion plan

Performance architecture không hoàn tất nếu old paths sống vô hạn.

### Delete candidates sau migration

```text
root Python package mirror
legacy duplicate capability tables
Rust nested row result paths
hot-loop order compaction
Python Rust-adapter shadow accounting/lifecycle
forced Python replay for standard native audit
score-via-audit compatibility path
old unversioned event contract alias
unused API 0.3/0.4 implementation code after translator window
```

### Deletion checklist per path

```text
replacement shipped
migration docs
usage/internal references search
compatibility window met
tests moved
benchmark baseline moved
release note
rollback no longer required or archived
```

### Negative code goals

Track removed:

- duplicate LOC;
- duplicate state structures;
- compatibility branches;
- output conversions;
- source mirrors.

Không coi thêm crates/modules là cleanup nếu total duplicate logic không giảm.

---

## P3.12 — P3 exit checklist

```text
[ ] one authoritative Python source tree
[ ] module ownership/import boundaries enforced
[ ] contract/capability registry is single source of truth
[ ] Python/Rust schemas/enums/docs/tests generated
[ ] protocol/ABI/contract/trace/IR versions separated
[ ] deprecation matrix with deadlines exists
[ ] core/native dual package clean-install matrix passes
[ ] exact runtime handshake implemented
[ ] native extra published only after certification
[ ] workload-aware auto promotion table implemented
[ ] emergency native rollback tested
[ ] three-tier benchmark governance active
[ ] generated cross-backend corpus active
[ ] stable diagnostics/counter schema documented
[ ] docs examples/capability table generated and tested
[ ] dependency/security/provenance gates pass
[ ] obsolete shadow/row/replay/mirror paths deleted
```

---

# 5. Master implementation sequence

## 5.1 Dependency graph

```text
Baseline + observability skeleton
        ↓
P0 event/account/order contracts
        ↓
Canonical trace + differential corpus
        ↓
P1 ExecutionPlan/backend SPI/output projection
        ↓
P1 native state ownership + boundary reduction
        ↓
P2 pure Rust extraction
        ↓
P2 arena/indexes/output/accounting
        ↓
P2 IR + batch
        ↓
P2 portfolio/package execution
        ↓
P3 packaging/promotion/cleanup
```

Một số workstream có thể song song sau khi contract đã freeze:

```text
Rust arena/index design          || Python endpoint split
IR reference interpreter         || flat native output
portfolio target compiler        || batch scheduler
package fixture design           || dual-wheel CI scaffolding
```

Nhưng không merge optimized semantics trước canonical trace.

---

## 5.2 PR sizing rule

Mỗi PR nên có một invariant/architecture outcome rõ, không trộn:

- contract change;
- refactor;
- performance optimization;
- packaging promotion.

Một PR tối ưu không được đồng thời thay fill semantics. Một PR contract change không được claim speedup vì output ít hơn.

PR template:

```text
Scope
Current confirmed issue
Contract/ADR
Files changed
Observable semantics impact
Trace/fingerprint impact
Tests
Benchmark before/after
Memory/copy/call counters
Compatibility/rollback
Follow-up debt
```

---

## 5.3 Wave 0 — Baseline và guardrails

### PR-00 — Pin snapshot và executable baseline

**Objective**

- ghi exact SHA;
- freeze Python/Rust/package/toolchain;
- tạo P0 golden corpus;
- archive benchmark manifests.

**Changes**

```text
upgrade/native-rust-v2/baseline.md
benchmarks/manifests/*.yaml
tests/corpus/baseline/*
scripts/print_runtime_manifest.py
```

**Tests/gates**

- current full suite;
- current parity suite;
- installed editable/core wheel smoke;
- benchmark E0/E1 current paths.

**Rollback**

Không behavior change.

### PR-01 — Counter schema skeleton

**Objective**

Đo phase/boundary trước refactor.

**Changes**

- `EngineDiagnosticsV1` Python/Rust;
- counters cho preparation, callback, PyO3 call, copy, output rows, scans;
- no-op/low-overhead default.

**Gate**

- counters exact on tiny fixture;
- disabled overhead within frozen budget;
- no result semantic change.

---

## 5.4 Wave P0 — Freeze correctness

### PR-02 — Execution contract registry và aliases

**Objective**

Tách hành vi thực tế thành named/versioned contracts.

**Changes**

```text
contracts/registry.yaml
contracts/generated/*
execution_contract.py
Rust generated contract codes
```

Freeze:

- `event_v2_next_bar_close`;
- draft `event_v3_next_open`;
- clock/phase codes.

**Gate**

- current outputs map exact V2;
- alias warning tests;
- Python/Rust registry fingerprint exact.

### PR-03 — Event clock/market fill policy V3

**Objective**

Implement actual next-open without changing V2.

**Changes**

- open/gap policy;
- bar 0/last bar;
- signal/activation/fill phase trace;
- Python oracle first, then Rust.

**Gate**

- V2 historical corpus unchanged;
- V3 golden matrix pass;
- opens are semantically used only in V3/policies that declare them.

### PR-04 — Lifecycle state machine registry

**Objective**

One transition table, generated codes/tests.

**Changes**

- statuses/actions/reject reasons;
- parent/OCO/TIF/replace semantics;
- invalid transition error taxonomy.

**Gate**

- exhaustive small transition tests;
- Python/Rust exact trace;
- no orphan child/OCO state.

### PR-05 — Accounting ledger/invariants

**Objective**

Make cash/PnL/fees/funding/margin/liquidation independently verifiable.

**Changes**

- ledger components;
- invariant checker;
- liquidation attribution;
- exact position delta cases.

**Gate**

- every golden fixture invariant pass;
- reverse/scale/reduce/property tests;
- no tolerance-based event masking.

### PR-06 — Instrument/numeric policy

**Objective**

Canonical tick/step/min/max/contract-size behavior.

**Changes**

- prepared instrument table;
- quantization error codes;
- integer tick/step helpers;
- generated cross-language vectors.

**Gate**

- Python/Rust exact quantized commands;
- edge cases around half-step/float representation;
- invalid values fail before mutation.

### PR-07 — Canonical trace/fingerprint

**Objective**

Trace every state transition with phase/sequence.

**Changes**

- trace schema v2;
- streaming/hash sinks;
- diff tooling;
- public metadata fingerprint.

**Gate**

- same trace across oracle/optimized/Rust for corpus;
- first divergence report includes bar/phase/event;
- hash-only equals full-trace fingerprint.

### PR-08 — Property/model/fuzz corpus

**Objective**

Turn must-prove risks into continuously tested properties.

**Changes**

- Hypothesis generators;
- proptest models;
- fuzz targets;
- corpus minimization/store.

**Gate**

- fixed seed corpus pass;
- soak/nightly jobs;
- no panic/NaN/invariant breach.

### PR-09 — Portfolio/package semantic contracts

**Objective**

Freeze target rebalance and package transaction behavior before native port.

**Changes**

- Python reference target/package executors;
- reservation ledger;
- atomic/best-effort/sequential/hedge fixtures;
- cross-venue staleness clock.

**Gate**

- package/portfolio invariants;
- deterministic trace;
- no Rust implementation yet required.

### P0 release checkpoint

At this point:

- tag a correctness baseline;
- archive trace corpus;
- do not promote backend;
- only then merge structural ownership changes.

---

## 5.5 Wave P1 — Planner/backend boundary

### PR-10 — Immutable `ExecutionPlan`

**Objective**

Resolve all profile/backend/contract/output decisions once.

**Changes**

- request/plan models;
- plan fingerprint;
- existing endpoint calls old backend through plan.

**Gate**

- plan snapshots;
- one resolution per run;
- no public behavior change.

### PR-11 — Preparation layer

**Objective**

Normalize market/instruments/strategy once and expose `PreparedRun`.

**Changes**

- preparation modules;
- content fingerprints;
- cache keys;
- counters.

**Gate**

- one normalization;
- prepared reuse parity;
- no hidden DataFrame conversion in backend.

### PR-12 — Backend SPI + `RawEngineResult`

**Objective**

Python and Rust implement same protocol; backend returns no pandas/report.

**Changes**

- engine protocol;
- registry;
- result raw types;
- compatibility adapters.

**Gate**

- contract tests run both;
- endpoint has no backend-specific execution logic;
- report built once outside engine.

### PR-13 — Output/context projection compiler

**Objective**

Resolve exact data needed by strategy/metrics/public output/audit.

**Changes**

- requirement masks;
- conservative compatibility fallback;
- Rust output descriptor;
- projection fingerprint.

**Gate**

- count-only no detail allocations;
- minimal context no unused rows/dicts;
- metrics still exact.

### PR-14 — Numeric context view + command writer

**Objective**

Create migration path away from per-bar Python objects.

**Changes**

- `StrategyContextView`;
- generation/lifetime guard;
- `CommandWriter` reusable SoA;
- legacy command adapter;
- symbol interner.

**Gate**

- legacy/writer command trace exact;
- no `pd.Timestamp`/dict on numeric path;
- Python allocation/copy reduction demonstrated.

### PR-15 — Native projection/delta protocol

**Objective**

Rust authoritative state; callback sees compact deltas.

**Changes**

- fill/event/order/position cursors;
- per-step projection;
- result buffer ownership;
- adapter consumer migration.

**Gate**

- delta/full snapshot consistency;
- stale result/session tests;
- projection bytes measured.

### PR-16 — Remove Rust adapter shadow-state

**Objective**

Delete duplicate Python lifecycle/accounting.

**Changes**

- remove pending/order/equity/path mirrors;
- callback and result use native projection;
- online metric ownership explicit.

**Gate**

- one authoritative state;
- P0 trace exact;
- memory plateau improves/does not regress.

### PR-17 — Sparse run-until-wake

**Objective**

Reduce boundary calls for declarative callback schedules.

**Changes**

- wake masks/schedules;
- chunk native execution;
- GIL detach per chunk;
- callback diagnostics.

**Gate**

- same trace as every-bar evaluation for eligible strategy;
- exact wake count;
- fewer calls and measured speedup.

### PR-18 — Native audit trace, optional oracle verifier

**Objective**

Remove mandatory double execution.

**Changes**

- native trace report path;
- explicit oracle verify mode;
- sampled dual-run option;
- metadata.

**Gate**

- normal audit primary runs once;
- verifier catches injected divergence;
- report derives primary trace.

### P1 checkpoint

At this point:

```text
Python backend = complete reference backend
Rust backend   = complete authoritative backend for supported contracts
PyO3 overhead  = explicit by strategy mode
```

Do a cleanup PR to remove temporary cross-layer imports before P2.

---

## 5.6 Wave P2A — Pure Rust engine and core data structures

### PR-19 — Rust workspace extraction

**Objective**

Move domain/engine out of PyO3 crate without semantics change.

**Changes**

- workspace/crates;
- binding wrapper preserves API 0.4;
- pure Rust tests/bench.

**Gate**

- extension/public parity;
- engine tests without Python;
- no trace change.

### PR-20 — Internal ABI 0.5 translator

**Objective**

Typed IDs/enums/ticks/command offsets.

**Changes**

- generated domain types;
- 0.4 translator;
- command tape v5;
- structured errors.

**Gate**

- legacy corpus translation exact;
- invalid ABI fuzz safe;
- per-bar commands direct slice.

### PR-21 — Flat output ownership

**Objective**

Eliminate nested rows and unnecessary clones before changing arena.

**Changes**

- SoA result columns;
- typed NumPy conversion;
- no ID-as-f64;
- position projection;
- chunked sink skeleton.

**Gate**

- output parity;
- result lifetime/GC tests;
- copies/RSS measured.

### PR-22 — Generational order arena

**Objective**

Remove hot compaction and lifetime-order memory growth.

**Changes**

- handles/free list/generation;
- external ID map;
- terminal emit/release;
- stable sequence.

**Gate**

- stale handle tests;
- high-churn memory plateau;
- priority trace exact.

### PR-23 — Lifecycle indexes

**Objective**

Replace expiry/parent/OCO/cancel scans.

**Changes**

- active_by_symbol;
- expiry wheel/heap;
- child adjacency;
- OCO group arena;
- debug index validator.

**Gate**

- no full historical scan counters;
- index invariants under fuzz;
- high-churn performance.

### PR-24 — Adaptive matching candidates

**Objective**

Use flat scan for small active sets, price/type indexes for large sets.

**Changes**

- candidate partition;
- integer tick range queries;
- deferred transition queue;
- tuned threshold manifest.

**Gate**

- E0 low/high churn matrix;
- no low-cardinality regression beyond budget;
- exact fill sequence.

### PR-25 — Incremental account/risk

**Objective**

Active positions + contribution deltas + risk cache versioning.

**Changes**

- position SoA/index;
- fill deltas;
- margin contributions;
- liquidation policy module.

**Gate**

- accounting invariants;
- recompute counters reduce;
- deterministic multi-symbol reductions.

### PR-26 — Native metric sinks

**Objective**

Score without audit/materialized paths.

**Changes**

- metric registry/conventions;
- score/compact/audit sinks;
- streaming audit chunks.

**Gate**

- exact score conventions;
- score allocation/RSS O(active state);
- no audit call in score stack trace.

---

## 5.7 Wave P2B — Native strategies and batch

### PR-27 — Strategy IR schema + Python reference interpreter

**Objective**

Freeze IR v1 before optimizing Rust runtime.

**Changes**

- opcodes/register types/validator;
- Python compiler/reference runtime;
- program fingerprint/disassembler;
- starter signal/bracket fixtures.

**Gate**

- bounded validation;
- deterministic reference trace;
- malformed program corpus.

### PR-28 — Rust IR interpreter

**Objective**

One-call-per-run native strategy state machine.

**Changes**

- register/state runtime;
- native command writer;
- requirements/projection;
- Grid/DCA/bracket programs.

**Gate**

- reference/Rust exact trace;
- no callback/Python object during run;
- E3 performance gate.

### PR-29 — Scenario batch single-thread

**Objective**

Amortize boundary/session/market over N trials before parallelism.

**Changes**

- batch plan;
- worker-local reusable state;
- parameter matrix;
- fixed result matrix;
- per-scenario errors.

**Gate**

- single vs batch exact;
- zero market copy/trial;
- E6 single-thread target.

### PR-30 — Deterministic parallel batch

**Objective**

Parallelize independent scenarios.

**Changes**

- Rayon optional pool;
- chunk scheduler;
- cancellation;
- output-by-index;
- worker diagnostics.

**Gate**

- workers 1/2/4/8 exact;
- no oversubscription default;
- speedup/RSS curve;
- sanitizer/concurrency tests.

### PR-31 — WFO/top-K audit

**Objective**

Fold views and selective audit reruns.

**Changes**

- fold plan;
- deterministic seeds;
- stable top-K;
- score/audit reconciliation.

**Gate**

- no market duplicate per fold;
- selected audit scalar exact;
- memory budget.

---

## 5.8 Wave P2C — Portfolio and arbitrage/package

### PR-32 — Portfolio target tape compiler/reference

**Objective**

Extract exact targets/rebalance semantics from current portfolio backend.

**Changes**

- target tape;
- Python reference rebalance planner;
- report input boundary;
- fixtures.

**Gate**

- current portfolio result reconciliation;
- target tape stable fingerprint.

### PR-33 — Rust portfolio target executor

**Objective**

Use core event/account engine for supported portfolio modes.

**Changes**

- target driver;
- two-phase rebalance;
- constraints/cash reservation;
- attribution columns.

**Gate**

- Python reference/Rust trace exact;
- current reports unchanged;
- E4 performance.

### PR-34 — Package tape/reference executor

**Objective**

Compile current arbitrage plans into canonical package actions.

**Changes**

- package/leg IDs;
- reservation ledger;
- Python two-phase executor;
- stale clock/latency fixtures.

**Gate**

- package P0 corpus/invariants.

### PR-35 — Rust package executor

**Objective**

Native atomic/best-effort/sequential/hedge lifecycle.

**Changes**

- package arena/indexes;
- preview/reserve/commit;
- residual/unwind;
- package trace/attribution.

**Gate**

- exact reference trace;
- no reservation leak;
- E5 scaling/memory;
- explicit capability per policy.

---

## 5.9 Wave P3 — Package/release/promotion/cleanup

### PR-36 — Generated capability/contract pipeline

**Objective**

Eliminate duplicated hand-written enums/tables.

**Changes**

- registry generator;
- Python/Rust/docs/tests artifacts;
- CI dirty check.

**Gate**

- exact fingerprints;
- generated capability docs.

### PR-37 — Dual-wheel staged build

**Objective**

Build/install core + native from clean artifacts.

**Changes**

- native build workflow;
- release manifest/provenance;
- clean venv/container matrix;
- mismatch tests.

**Gate**

- CPython/platform matrix;
- manylinux audit;
- fail-fast/fallback.

### PR-38 — Publish native extra to staging

**Objective**

Wire exact native dependency only after staged certification.

**Changes**

- generated optional dependency mapping;
- staged package index tests;
- install docs.

**Gate**

- core-only and native installs;
- no dependency resolver mismatch;
- no source leakage.

### PR-39 — Auto promotion Stage B

**Objective**

Promote certified static/IR workloads.

**Changes**

- routing table;
- decision metadata;
- rollback switch;
- public docs.

**Gate**

- release E0/E3 matrix;
- installed wheels;
- no E1 forced Rust.

### PR-40 — Auto promotion portfolio/package stages

Separate PR/release per domain. Do not bundle portfolio and package promotion.

### PR-41 — Remove source mirror/shadow/legacy hot paths

**Objective**

Delete debt after compatibility windows.

**Changes**

- root mirror;
- nested rows;
- score-via-audit;
- forced replay;
- obsolete implementation duplicates.

**Gate**

- source/wheel/module path tests;
- negative LOC/duplication report;
- full release matrix.

---

# 6. Target repository structure after P0–P3

```text
quantbt/
  pyproject.toml
  Cargo.toml                       # optional workspace root link/config

  contracts/
    registry.yaml
    schemas/
    generated-manifest.json

  src/quantbt/
    __init__.py
    api/
    planning/
    preparation/
    contracts/
      generated/
    engines/
      protocol.py
      registry.py
      python/
      rust/
    strategies/
      context.py
      writer.py
      ir/
    results/
    verification/
    portfolio/
    arbitrage/
    compatibility/

  rust/
    Cargo.toml
    crates/
      quantbt-domain/
      quantbt-engine/
      quantbt-strategy-ir/
      quantbt-batch/
      quantbt-portfolio/
      quantbt-package/
      quantbt-py/

  tests/
    corpus/
      event/
      account/
      portfolio/
      package/
    contracts/
    differential/
    property/
    binding/
    installed/

  fuzz/
    command-tape/
    strategy-ir/
    arena/
    package/

  benchmarks/
    manifests/
    fixtures/
    runners/
    baselines/
    reports/

  docs/
    adr/
    architecture/
    contracts/
    native/
    performance/
    migration/
```

---

# 7. Public API shape after migration

## 7.1 Prepare once, run many

```python
import quantbt as qbt

request = qbt.BacktestRequest(
    market=market,
    instruments=instruments,
    account=qbt.AccountConfig(initial_capital=100_000),
    strategy=strategy,
    config=qbt.BacktestConfig(
        contract="event_v3_next_open",
        backend="auto",
        profile="research",
    ),
)

prepared = qbt.prepare(request)
result = prepared.run()
```

Metadata:

```python
result.metadata.execution.backend
result.metadata.execution.backend_reason
result.metadata.execution.contract
result.metadata.execution.strategy_mode
result.metadata.execution.plan_fingerprint
result.metadata.execution.trace_fingerprint
```

## 7.2 Explicit Python/Rust

```python
python_result = prepared.run(backend="python")
rust_result = prepared.run(backend="rust")
```

Explicit Rust unsupported => `CapabilityError`, không fallback.

## 7.3 Numeric callback + writer

```python
@qbt.strategy_requirements(
    market=("close", "high", "low"),
    account=("equity",),
    positions=("qty",),
    fills="new_only",
    events="rejects_only",
    callback="every_bar",
)
def strategy(ctx: qbt.StrategyContextView, out: qbt.CommandWriter) -> None:
    symbol = 0
    if ctx.position_qty(symbol) == 0 and ctx.close(symbol) > ctx.signal(0):
        out.market(symbol, qbt.Side.BUY, 1.0)
```

## 7.4 Sparse callback

```python
requirements = qbt.StrategyRequirements(
    callback=qbt.CallbackSchedule(
        every_n_bars=24,
        on_fill=True,
        on_reject=True,
    ),
    ...,
)
```

Planner chọn `python_callback_sparse`; Rust chạy tới wake point.

## 7.5 Strategy IR

Illustrative API:

```python
s = qbt.ir.Strategy("grid_v1")
price = s.market.close(symbol=0)
pos = s.position.qty(symbol=0)
anchor = s.state.float("anchor", initial=0.0)

with s.when(anchor == 0.0):
    anchor.set(price)

with s.when((pos == 0.0) & (price <= anchor * (1.0 - s.param("entry_pct")))):
    s.order.market(symbol=0, side="buy", qty=s.param("qty"))
    s.order.bracket(
        symbol=0,
        take_profit=price * (1.0 + s.param("tp_pct")),
        stop_loss=price * (1.0 - s.param("sl_pct")),
    )

program = s.compile(contract="event_v3_next_open")
prepared = qbt.prepare(request.with_strategy(program))
result = prepared.run(backend="rust")
```

Actual DSL can differ; semantic requirements remain.

## 7.6 Batch optimizer

```python
parameter_matrix = {
    "entry_pct": [0.005, 0.01, 0.015],
    "tp_pct": [0.01, 0.02],
    "sl_pct": [0.005, 0.01],
    "qty": [1.0],
}

batch = prepared.score_batch(
    parameter_matrix,
    metrics=("score", "return", "max_drawdown", "turnover"),
    workers="auto",
)

audits = prepared.audit_scenarios(batch.top_k(5))
```

## 7.7 Portfolio target tape

```python
targets = qbt.TargetTape.from_weights(
    timestamps=rebalance_dates,
    weights=weight_matrix,
    symbols=symbols,
)

result = qbt.portfolio_backtest(
    market=market,
    targets=targets,
    execution=qbt.PortfolioExecutionPolicy(
        contract="event_v3_next_open",
        rebalance_order="sell_then_buy",
        partial_acceptance="scale_pro_rata",
    ),
    backend="auto",
)
```

## 7.8 Arbitrage package

```python
package = qbt.ArbitragePackage(
    policy="hedge_after_primary",
    primary=qbt.Leg(...),
    hedges=[qbt.Leg(...)],
    max_staleness_ns=50_000_000,
    max_residual_notional=1_000,
)

result = qbt.arbitrage_backtest(
    market=multi_venue_market,
    packages=package_tape,
    backend="rust",
)
```

---

# 8. Test and CI command contract

Tên command có thể triển khai bằng `Makefile`, `just`, `nox` hoặc scripts; điều quan trọng là interface ổn định cho developer/CI.

```text
make test-python-unit
make test-rust-unit
make test-contracts
make test-differential
make test-property
make test-binding
make test-installed
make test-all

make fuzz-smoke
make fuzz-nightly

make bench-smoke
make bench-native
make bench-facade
make bench-release
make bench-compare BASE=<manifest>

make build-core-wheel
make build-native-wheel
make verify-wheels
make release-manifest
```

## 8.1 PR required jobs

```text
lint/type/static
Python unit
Rust fmt/clippy/unit
contract generation clean
small P0 corpus Python/Rust
binding lifetime/error tests
benchmark counter smoke
```

## 8.2 Merge/main jobs

```text
full differential corpus
property tests fixed budget
editable/core/native wheel tests
memory reset smoke
E0–E3 medium benchmark informational/guarded
```

## 8.3 Nightly

```text
fuzz/soak
E0–E6 matrix
sanitizers/Miri subset
large RSS plateau
all worker-count determinism
multi-version wheel clean install
```

## 8.4 Release blocking

```text
all P0 corpus exact
all promoted workload perf gates
clean staged wheels
runtime mismatch matrix
provenance/SBOM/security
rollback switch
capability docs generated
```

---

# 9. Benchmark report format

```markdown
## Workload
ID: E3_GRID_SCORE_MEDIUM
Contract: event_v3_next_open
Strategy mode: ir_v1
Profile: score
Bars/symbols/orders: ...
Fixture hash: ...

## Environment
CPU/cores/governor: ...
OS/kernel/container: ...
Python/NumPy/PyO3/Rust: ...
Wheel/source SHA: ...

## Correctness
Trace fingerprint Python: ...
Trace fingerprint Rust: ...
Invariants: PASS

## Timing
| phase | before | after | delta |
...

## Boundary
PyO3 calls: ...
Callbacks: ...
Bytes copied: ...

## Kernel
Order rows scanned: ...
Index lookups: ...
Margin recomputes: ...
Allocations: ...

## Memory
Peak/steady RSS: ...
Arena/output capacities: ...

## Decision
Gate PASS/FAIL
Tradeoffs
Rollback flag
```

---

# 10. Architecture invariants that must remain true

```text
1. Python oracle remains runnable without native wheel.
2. Explicit Rust never silently falls back.
3. Auto decision is deterministic and observable.
4. One run has one immutable ExecutionPlan.
5. A backend owns one authoritative execution/account state.
6. Public reporting never changes execution state.
7. Contract aliases never silently change semantics.
8. Static/IR/batch native paths do not call Python per bar.
9. Arbitrary callback is labeled as compatibility path.
10. Account/order/package transitions emit canonical trace.
11. Portfolio/package reuse core primitives, not forked engines.
12. Optimization cannot alter required output projection.
13. Parallelism cannot alter scenario/event ordering.
14. Native result buffers have explicit owners/lifetimes.
15. Installed wheels, not source-tree tests, determine release support.
```

---

# 11. Risk register và mitigation

| Risk | Priority | Failure mode | Mitigation | Gate/evidence |
|---|---:|---|---|---|
| Silent semantic drift | P0 | equity gần giống nhưng fill/order phase khác | versioned contract + canonical trace | exact trace corpus |
| Legacy result irreproducible | P0 | alias đổi next-close thành next-open | retain named V2; migration manifest | historical fixture rerun |
| Accounting mismatch hidden by tolerance | P0 | final PnL pass nhưng fee/funding sequence sai | ledger invariants + event attribution | per-event invariant |
| Rust/Python capability disagreement | P0/P3 | planner selects unsupported native path | generated registry + runtime fingerprint | mismatch tests |
| Installed wheel differs from source | P0/P3 | tests pass repo, user import fails | clean staged wheel matrix | release blocker |
| Shadow-state divergence | P1 | callback sees Python state khác Rust result | Rust authoritative + delta protocol | no duplicate mutation paths |
| Per-bar PyO3 remains dominant | P1/P2 | Rust kernel fast nhưng facade slow | strategy modes, sparse wake, IR | call/callback counters |
| Refactor changes semantics | P1 | module split reorders phases | P0 trace required every PR | fingerprint unchanged |
| Result buffer use-after-reset | P1/P2 | corrupted NumPy view/segfault | moved ownership/generation/GC tests | lifetime stress |
| Arena stale handle | P2 | cancel/amend mutates reused slot | generation-safe handle | proptest/fuzz |
| Index drift | P2 | active order missed/double matched | debug invariant validator | fuzz every transition |
| Index overhead hurts small runs | P2 | Rust regression on low churn | adaptive flat/index path | E0 matrix |
| Generic specialization code bloat | P2 | larger wheel/I-cache/compile | specialize only top axes | bloat + perf report |
| Native score convention drift | P2 | optimizer ranks differ | versioned metric algorithms | exact metric corpus |
| Parallel nondeterminism | P2 | results depend worker count | per-scenario state + ordered output | 1/2/4/8 exact |
| Oversubscription | P2 | Rust pool + Optuna/BLAS slower | explicit worker policy/diagnostics | thread/cpu benchmark |
| Unsafe NumPy lifetime | P2 | UB under GC/free-threading | own/copy prepared tape; no default borrow | Miri/stress/sanitizer |
| PGO overfits one workload | P2 | static improves, portfolio regresses | representative E0–E6 training | full release matrix |
| Portfolio becomes second engine | P2 | duplicate accounting/order bugs | target driver over common core | dependency/import test |
| Arbitrage “support” lacks package semantics | P2 | partial legs misreported | package state/reservation/trace | package corpus |
| Native package mismatch | P3 | import works, mid-run ABI fail | exact handshake before prepare | mismatch clean install |
| Auto routes poorly | P3 | callback slower under Rust | workload-aware promotion table | per-workload gates |
| Compatibility code never removed | P3 | permanent complexity/branches | machine-readable deprecation/deletion | deadline/owner CI report |
| Benchmark gaming/noise | P3 | false promotion | manifests, same output/trace, dedicated machine | release report review |

---

# 12. Những việc không nên làm

## 12.1 Không “bỏ PyO3” trước khi sửa call granularity

Binding overhead không phải blocker chính khi one-call-per-run. Đổi sang CFFI/HPy/raw C API mà vẫn callback Python mỗi bar sẽ không giải quyết control-plane cost và làm lifetime/package phức tạp hơn.

## 12.2 Không port toàn bộ Python sang Rust một lần

Giữ Python cho:

- oracle semantics;
- research/feature/allocator flexibility;
- public report/pandas;
- IR compiler/reference;
- unsupported/fallback workloads.

Port ownership/hot paths có contract rõ trước.

## 12.3 Không dùng static tape benchmark để quảng bá callback performance

Báo cáo phải ghi strategy mode và PyO3 call count.

## 12.4 Không thay contract để đạt speed

Ví dụ không được:

- bỏ active orders khỏi audit;
- đổi next-open/close;
- skip liquidation check;
- giảm fill/event detail;
- dùng score khác convention;
- bỏ report trong một backend nhưng tính ở backend kia;

rồi gọi đó là optimization.

## 12.5 Không parallelize một event timeline có shared account

Locks/atomics không biến dependency tuần tự thành song song an toàn. Parallelize scenario/fold/precompute.

## 12.6 Không mặc định `target-cpu=native` cho public wheel

Wheel sẽ không portable và có thể illegal instruction trên CPU khác.

## 12.7 Không bật fast-math

Backtest cần deterministic comparison/accounting. Fast-math có thể thay NaN, reassociation và ordering.

## 12.8 Không dùng `get_unchecked` tràn lan

Bounds checks thường được compiler eliminate nếu loop/layout viết đúng. Unsafe chỉ sau profile và proof.

## 12.9 Không giữ terminal orders chỉ để report

Emit immutable terminal event/output rồi release arena slot. Audit history thuộc output sink, không thuộc active execution state.

## 12.10 Không dùng `HashMap` iteration để quyết priority

Canonical order phải dựa phase/sequence/price policy, không random hash order.

## 12.11 Không dùng một universal result object

Score, compact, audit có ownership/output khác. Universal object dễ kéo rows/clones vào score.

## 12.12 Không auto-promote chỉ vì import native thành công

Availability ≠ capability ≠ certification ≠ performance promotion.

## 12.13 Không giữ forced Python replay như cách “chứng minh Rust đúng” lâu dài

Oracle verify là certification mode, không phải production output builder.

## 12.14 Không phát triển portfolio/arbitrage bằng copy `FullSession`

Phải composition/reuse domain/account/order engine. Fork sẽ tạo ba semantics khác nhau.

## 12.15 Không xây general-purpose Python VM trong IR v1

IR chỉ cần đủ express common deterministic strategy state machines. Arbitrary Python tiếp tục compatibility path.

---

# 13. Decision rules khi profile một hotspot

```text
1. Hotspot có nằm trong promoted end-to-end workload không?
   No -> ưu tiên thấp hoặc diagnostic-only.

2. Cost là Python callback/object, boundary copy, kernel, output hay report?
   Chưa biết -> instrument trước.

3. Optimization có thay contract/output không?
   Yes -> tách thành P0 contract proposal, không perf PR.

4. Có thể hoist/precompute/reuse thay vì micro-optimize không?
   Yes -> làm architecture win trước.

5. Data structure cost theo total history hay active relevant set?
   Total -> index/arena redesign.

6. Allocation có thể reuse/move/stream không?
   Yes -> làm trước allocator swap.

7. Parallel unit có độc lập không?
   No -> không parallelize.

8. SIMD loop có homogeneous arithmetic và đủ data không?
   No -> không ưu tiên SIMD.

9. Unsafe gain có material trên E-class không?
   No -> giữ safe.

10. Before/after có exact trace và memory report không?
    No -> không merge.
```

---

# 14. Definition of “dual native backend” cho QuantBT

Không nên tuyên bố Rust là dual native backend chỉ vì có `_quantbt_native.so`. Definition bắt buộc:

## Contract equality

- Python và Rust nhận cùng `ExecutionPlan`;
- cùng versioned execution/account/order semantics;
- same canonical trace cho certified corpus;
- same public error/capability model.

## Ownership equality

- Python backend sở hữu state Python khi selected;
- Rust backend sở hữu state Rust khi selected;
- không có shadow engine bắt buộc ở backend còn lại.

## Package equality

- core package chạy độc lập;
- native wheel clean-install được;
- exact runtime handshake;
- explicit backend behavior rõ;
- result metadata xác nhận backend thật.

## Profile equality

- score/compact/audit có defined output contract ở cả hai;
- Rust không cần replay Python để trả standard output;
- Python không cần native để trả same contract.

## Workload honesty

- static/IR/batch là native full-run;
- Python callback là hybrid compatibility path;
- planner có thể chọn Python cho workload callback nhỏ;
- capabilities/public docs nói rõ.

## Extensibility

- event, portfolio, package share domain/account/order primitives;
- adding a new venue/model is a policy/module/capability addition, không copy engine;
- Rust core testable without Python.

Chỉ khi các điều trên đạt mới promote documentation từ “experimental native acceleration” thành “dual backend”.

---

# 15. Final acceptance matrix

## P0 acceptance

| Area | Required evidence |
|---|---|
| Event clock | V2/V3 golden trace; bar 0/last/multi-symbol |
| Fill/gap/intrabar | exhaustive policy matrix |
| Lifecycle | generated transition tests; parent/OCO/TIF |
| Accounting | ledger invariants every fixture |
| Numeric | exact tick/step cross-language vectors |
| Trace | rolling/full fingerprint exact |
| Fuzz | minimized corpus; no panic/invariant breach |
| Portfolio | target/rebalance reference trace |
| Package | reservation/atomicity/residual reference trace |
| Wheels | explicit/fallback/mismatch clean install |

## P1 acceptance

| Area | Required evidence |
|---|---|
| Planner | immutable plan and fingerprint |
| Backend SPI | same contract tests Python/Rust |
| Preparation | one normalization/copy per prepared key |
| Projection | no unnecessary detail allocations |
| Context/writer | lower objects/copies; exact commands |
| Ownership | no Python shadow account/order state |
| Boundary | calls/callbacks/bytes reported |
| Audit | one primary run; optional verifier |
| Lifetime | reset/result/GC stress |
| Architecture | import/dependency boundaries |

## P2 acceptance

| Area | Required evidence |
|---|---|
| Workspace | engine pure Rust/no PyO3 |
| ABI | typed v5 + safe legacy translator |
| Arena | generational; no hot compaction |
| Indexes | complexity proportional relevant active sets |
| Matching | adaptive candidate benchmark + exact order |
| Account | incremental risk/margin + invariants |
| Output | flat SoA; no score-via-audit |
| IR | Grid/DCA/bracket one-call parity/perf |
| Batch | single/parallel deterministic, zero tape copy/trial |
| Portfolio | common core target execution |
| Package | two-phase native package lifecycle |
| Toolchain | profile evidence; safe portable build |
| Memory | plateau and chunk scaling |

## P3 acceptance

| Area | Required evidence |
|---|---|
| Source | one authoritative Python tree |
| Schemas | generated Python/Rust/docs/tests |
| Compatibility | protocol/ABI/contract matrix |
| Packages | clean core/native staged wheels |
| Auto | workload-aware promotion + rollback |
| CI | PR/nightly/release tiers |
| Docs | generated capability table/examples pass |
| Security | audit/license/provenance/unsafe report |
| Cleanup | old mirror/shadow/row/replay paths deleted |

---

# 16. Recommended promotion order

```text
1. Rust explicit — E0 static score/compact/audit
2. Rust explicit — E3 IR Grid/DCA/bracket
3. Rust batch — E6 optimizer/WFO
4. Auto Rust — certified static/IR medium/large
5. Rust explicit — E4 portfolio target modes
6. Auto Rust — certified portfolio modes
7. Rust explicit — E5 package policies
8. Auto Rust — certified package policies
9. Expand platforms/contracts/models one capability at a time
```

Không promote E1 arbitrary Python callback chỉ để có tỷ lệ Rust usage cao. Backend tốt nhất là backend đạt contract và end-to-end workload mục tiêu.

---

# 17. Immediate implementation backlog

Để bắt đầu từ code snapshot hiện tại, backlog đầu tiên nên đúng thứ tự:

```text
A. Pin SHA + benchmark/corpus manifest
B. Rename/freeze actual V2 next-bar-close contract
C. Implement V3 next-open in Python oracle and Rust
D. Add canonical phase/event trace and invariant checker
E. Add property/proptest differential corpus
F. Introduce immutable ExecutionPlan without behavior change
G. Compile output/context requirements once
H. Add numeric context + reusable command writer
I. Add native delta projection and remove adapter shadow state
J. Make native audit primary; oracle verifier optional
K. Extract pure Rust workspace
L. Flatten outputs and native metric sinks
M. Replace Vec/compaction with generational arena
N. Add active/expiry/parent/OCO indexes
O. Add IR v1 reference + Rust runtime
P. Add batch single-thread then deterministic parallel
Q. Add portfolio target driver
R. Add package two-phase driver
S. Close dual-wheel/handshake/promotion gates
T. Delete legacy hot paths/source mirror
```

Các item A–E là non-negotiable trước ownership/data structure rewrite. Các item K–P là nơi mang lại phần lớn native performance. Q–R bảo đảm kiến trúc không đóng cứng vào single-strategy event backtest. S–T biến implementation thành product thay vì source-tree benchmark.

---

# 18. Closing architecture statement

Kiến trúc đích của QuantBT nên được hiểu như sau:

```text
Python = public API + planning + research + oracle + reports
Rust   = deterministic execution/account/risk core + native strategy/runtime + batch
PyO3   = thin, typed, amortized transport layer
```

Rust không cần thay Python hoàn toàn. Rust cần sở hữu trọn vẹn những phần mà Rust có lợi thế:

- event/order/package state machines;
- deterministic accounting/risk transitions;
- data-oriented active state;
- one-pass metrics;
- repeated scenario execution;
- native strategy IR;
- cross-domain shared primitives.

Kết quả cuối cùng không phải một backend Rust “nhanh ở kernel” nhưng vẫn phụ thuộc Python mỗi bar. Nó là một dual-backend system có:

- semantics được version hóa;
- Python oracle đáng tin;
- Rust execution native thật cho static/IR/batch;
- callback compatibility không bị che giấu;
- portfolio/arbitrage mở rộng trên cùng engine foundation;
- package/release gates đủ để `auto` chọn Rust một cách an toàn.
