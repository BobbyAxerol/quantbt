# QuantBT Phase 17 — Execution Correctness, Fast Intrabar Kernel và Audit Toàn Bộ Alpha

> **Trạng thái tài liệu:** Kế hoạch nâng cấp chính thức
> **Repository:** `BobbyAxerol/quantbt`
> **Nhánh triển khai:** `dev`
> **Ngày kiểm định:** 2026-07-26
> **Mức ưu tiên:** P0 — phải hoàn thành trước khi tiếp tục tin cậy các kết quả alpha có SL/TP/trailing nội bar
> **Mục tiêu:** Giữ tốc độ nghiên cứu gần `native_vectorized`, nhưng khóa chặt execution semantics, accounting, fill logic và audit trail để backtest đúng theo contract đã công bố.

---

## 1. Executive decision

QuantBT hiện không cần bị thay thế. Hướng kiến trúc dùng NumPy/Numba cho hot path là đúng với mục đích optimizer, walk-forward, grid search và multi-run service.

Vấn đề cốt lõi là backend `native_vectorized` hiện chỉ thực thi một execution contract hẹp:

```text
target position tại close[t]
→ mark vị thế cũ close[t-1] → close[t]
→ rebalance target tại close[t]
```

Trong khi API và tên backend chưa ngăn người dùng đưa vào các alpha có semantics khác:

```text
signal tại close[t]
→ entry tại open[t+1]
→ SL/TP/trailing trong high/low của bar t+1
→ có thể entry và exit trong cùng một bar
```

Hai mô hình này không thể được biểu diễn chính xác chỉ bằng một cột `pos_weight`.

Quyết định nâng cấp:

1. **Giữ kernel hiện tại**, nhưng đổi định danh semantics thành `close_target_v2`.
2. **Không mở rộng kernel hiện tại thành một generic engine khổng lồ.**
3. Thêm **Numba fast intrabar kernel chuyên biệt** cho nhóm alpha:
   - tín hiệu ở close;
   - khớp next open;
   - fixed SL/TP;
   - gap-aware stop;
   - trailing stop;
   - technical exit;
   - reversal;
   - entry và exit cùng bar.
4. Thêm **fast fill replay kernel** để kế thừa các alpha cũ đang tự tính entry/exit nội bar, phục vụ migration và accounting audit.
5. Tách ba cấp output:
   - `minimal`: optimizer, không materialize fill ledger;
   - `standard`: diagnostics theo bar;
   - `audit`: sparse fills/trades đầy đủ bằng deterministic second pass.
6. Mọi validation nặng chỉ chạy **một lần khi chuẩn bị market tape**, không chạy lại trong mỗi Optuna trial.
7. Dùng Python reference oracle, property tests và parity với native event/Nautilus để chứng nhận correctness.
8. Đóng băng trạng thái tin cậy của mọi alpha intrabar cũ cho đến khi được rerun bằng backend phù hợp.

---

## 2. Phán quyết về code hiện tại

### 2.1 Điều đang đúng

Kernel `_engine_units_v2` trong `core/vectorized.py` là một Numba loop nhanh, deterministic và có thể dùng hợp lệ cho target-position close-based. Nó thực hiện:

- mark PnL close-to-close;
- kiểm tra liquidation bằng high/low;
- funding;
- margin;
- rebalance target units tại close;
- fee và slippage;
- trả equity, positions, fees, turnover, funding và margin diagnostics.

Đây là một execution model hợp lệ nếu người dùng thực sự muốn:

```text
position target có hiệu lực tại close của cùng bar
```

### 2.2 Điều đang không đủ hoặc sai ở cấp framework

Các vấn đề phải xử lý:

| ID | Vấn đề | Mức độ |
|---|---|---:|
| P0-01 | `native_vectorized` không công bố/enforce rõ close-target semantics | P0 |
| P0-02 | Alpha có SL/TP nội bar có thể dùng nhầm `signal_notional` mà không bị reject | P0 |
| P0-03 | `ExecutionConfig.fill_price_policy` và `same_bar_policy` tồn tại nhưng không được mọi backend thực thi | P0 |
| P0-04 | Public reactive path không truyền đầy đủ `open` và `volume` vào `run_strategy` | P0 |
| P0-05 | Funding dictionary thiếu symbol fallback thành `0.0001` | P0 |
| P0-06 | Funding mask dựa trên exact hour có thể bỏ mất event ở timeframe lệch | P0 |
| P0-07 | Preprocessor tự sort, deduplicate và forward-fill OHLC | P0 |
| P0-08 | High/low có thể fallback về close, làm mất intrabar liquidation | P0 |
| P0-09 | `target_units[0]` không được execution nhưng không bị reject | P1 |
| P0-10 | Multi-symbol margin acceptance phụ thuộc thứ tự symbol | P1 |
| P0-11 | Portfolio intrabar liquidation dùng joint worst extreme không công bố ambiguity | P1 |
| P0-12 | Vectorized result không có fill ledger để audit entry-exit cùng bar | P1 |

### 2.3 Bằng chứng từ nhánh `dev`

Các nhận định trên dựa trên code hiện tại:

- `core/vectorized.py` mark close-to-close và execute target-unit changes tại close.
- `backends/native_vectorized.py` fallback high/low về close và trả result không có fills.
- `core/schema.py` khai báo `FillPricePolicy` và `SameBarPolicy`.
- `backends/native_event.py` market fill hiện dùng close; stop-market fill tại trigger.
- `engines.py` gọi reactive strategy nhưng chưa truyền `opens` và `volumes`.
- `core/preprocessor.py` sort/deduplicate/ffill và funding fallback `0.0001`.
- Benchmark hiện tại cho thấy pure Numba kernel chỉ chiếm một phần rất nhỏ tổng runtime; phần lớn thời gian trước đây nằm ở pandas normalization, target sizing, order compilation và report construction.

Nguồn tham chiếu được liệt kê ở cuối tài liệu.

---

## 3. Định nghĩa “đúng 100%”

Với dữ liệu OHLC, không thể khẳng định đúng 100% so với đường đi tick thật trong mọi bar.

Ví dụ:

```text
open  = 100
high  = 110
low   = 90
close = 105

SL = 95
TP = 108
```

OHLC không cho biết giá đi:

```text
100 → 110 → 90 → 105
```

hay:

```text
100 → 90 → 110 → 105
```

Do đó mục tiêu chính xác phải là:

> **Đúng 100% theo một execution contract công khai, deterministic, causal, conservative và được khóa bằng tests.**

Engine phải:

- không đọc dữ liệu tương lai;
- không im lặng suy luận semantics;
- không tự sửa dữ liệu đầu vào;
- không bỏ mất entry/exit cùng bar;
- không ghi đè nhiều fill trong cùng bar;
- đánh dấu các bar mà OHLC không xác định duy nhất đường đi;
- trả cùng kết quả cho cùng input/config/kernel version;
- có Python oracle và parity tests.

---

## 4. Mục tiêu và non-goals

## 4.1 Mục tiêu bắt buộc

1. Correctness-first nhưng không phá workflow optimizer.
2. Giữ backward compatibility có kiểm soát.
3. Backend name và metadata phải mô tả execution semantics.
4. Có fast path cho các alpha SL/TP/trailing phổ biến.
5. Không tạo Python object trong hot loop.
6. Không materialize fill DataFrame trong optimizer.
7. Data validation chạy một lần cho mỗi market tape.
8. Có migration path cho alpha cũ.
9. Có benchmark ratio so với:
   - `native_vectorized/close_target_v2`;
   - `native_event`;
   - prepared context;
   - audit mode.
10. Mọi alpha phải có execution manifest.

## 4.2 Non-goals của Phase 17 v1

Không giả vờ hỗ trợ đầy đủ những domain chưa thể đúng bằng OHLC đơn giản:

- queue priority;
- latency model;
- partial fills dựa trên L2;
- exchange-native OCO race;
- tick-level order book;
- multi-symbol cross-margin intrabar path chính xác tuyệt đối;
- inverse/quanto contract trong kernel v1;
- nhiều entry lots/DCA/grid tùy ý trong cùng một position;
- option portfolio Greeks trong kernel này.

Các use case này tiếp tục dùng:

- backend chuyên dụng DCA/grid;
- `native_event`;
- option engine;
- Nautilus;
- lower-timeframe/tick validation.

---

## 5. Nguyên tắc kiến trúc

### 5.1 Không trộn bốn domain

```text
Alpha/feature logic
Sizing logic
Execution/matching logic
Accounting/risk logic
```

Alpha chỉ được xuất **intent** hoặc **level causal**.

Engine là nguồn chân lý duy nhất cho:

- thời điểm order có hiệu lực;
- fill price;
- gap behavior;
- same-bar conflict;
- fee;
- slippage;
- quantity constraints;
- realized/unrealized PnL;
- margin;
- liquidation;
- fill/trade ledger.

### 5.2 Backend phải được đặt tên theo semantics

Không dùng một tên chỉ mô tả implementation như `vectorized` để suy ra execution model.

Đề xuất backend/engine IDs:

```text
close_target_v2
next_open_v1
intrabar_bracket_v1
fill_replay_v1
event_lifecycle_v2
native_portfolio_v3
```

Public alias có thể giữ:

```text
native_vectorized -> close_target_v2
native_event      -> event_lifecycle_v2
```

nhưng result metadata phải ghi engine ID thật.

### 5.3 Fail-fast thay vì silent degradation

Nếu backend không hỗ trợ một field/config:

```python
raise NotImplementedError(...)
```

Không được:

- nhận `NEXT_OPEN` rồi vẫn fill close;
- nhận `same_bar_policy` nhưng bỏ qua;
- thiếu high/low rồi dùng close;
- thiếu funding symbol rồi tạo rate mặc định;
- thiếu bar rồi forward-fill OHLC.

---

## 6. Execution contract taxonomy

## 6.1 Contract A — `close_target_v2`

Dùng cho:

- target units;
- target notional;
- signal notional;
- close-to-close research;
- không có SL/TP intrabar;
- không phụ thuộc exact fill sequence.

Timeline:

```text
bar t:
    mark carried position close[t-1] → close[t]
    funding/risk theo contract
    rebalance target tại close[t]
```

Yêu cầu:

```text
signal_phase = close
fill_phase   = same_close
intrabar_exit_model = none
```

## 6.2 Contract B — `next_open_v1`

Dùng cho:

- signal được tạo sau close;
- entry/exit market ở next open;
- không có SL/TP intrabar.

Timeline:

```text
close[t]:
    signal decision

open[t+1]:
    execute pending delta
```

## 6.3 Contract C — `intrabar_bracket_v1`

Dùng cho phần lớn alpha hiện tại có:

- next-open entry;
- initial stop;
- fixed take profit;
- trailing;
- close-based technical exit;
- reversal;
- same-bar entry/exit.

Timeline được khóa ở Section 9.

## 6.4 Contract D — `fill_replay_v1`

Dùng tạm cho alpha cũ đã tự tạo fill nội bar.

Alpha phải cung cấp explicit fills:

```text
timestamp/bar_index
sequence
side
qty
price
order_kind
reason
liquidity
```

Kernel chỉ:

- validate;
- quantize;
- account;
- apply fee;
- reconstruct equity/trades.

Certification của backend này:

```text
accounting_certified = true
execution_generation_certified = false
```

Nó là migration bridge, không phải đích cuối.

## 6.5 Contract E — `event_lifecycle_v2`

Dùng cho:

- nhiều pending orders;
- limit/stop packages;
- DCA/grid;
- basket;
- partial-fill;
- lifecycle cancel/amend;
- advanced OCO.

---

## 7. Kiến trúc mục tiêu

```text
DataFrame / ndarray
        |
        v
Strict Market Tape Preparation
        |
        +-- validation certificate
        +-- contiguous OHLCV arrays
        +-- funding events
        +-- instrument constraints
        +-- immutable data signature
        |
        v
Alpha Adapter / Intent Compiler
        |
        +-- close target tape
        +-- next-open intent tape
        +-- intrabar bracket tape
        +-- explicit fill tape
        |
        v
Kernel Registry
        |
        +-- close_target_v2
        +-- next_open_v1
        +-- intrabar_bracket_v1
        +-- fill_replay_v1
        +-- event_lifecycle_v2
        |
        v
NativeRunBuffers
        |
        +-- minimal scalar/array outputs
        +-- event flags
        +-- optional exact fill count
        |
        v
Lazy Result Materialization
        |
        +-- minimal metrics
        +-- standard BacktestResultV2
        +-- audit fills/trades/reports
```

---

## 8. Shared domain schema cần bổ sung

## 8.1 Execution contract

```python
@dataclass(frozen=True)
class ExecutionContract:
    engine_id: str

    signal_phase: SignalPhase
    entry_fill_phase: FillPhase
    market_fill_policy: MarketFillPolicy

    stop_gap_policy: StopGapPolicy
    take_profit_gap_policy: TakeProfitGapPolicy
    same_bar_policy: SameBarPolicy
    trailing_update_phase: TrailingUpdatePhase

    funding_phase: FundingPhase
    liquidation_priority: LiquidationPriority
    close_on_last_bar: bool

    ambiguity_policy: AmbiguityPolicy
    strict_data: bool = True
```

Enums đề xuất:

```python
class SignalPhase(IntEnum):
    BAR_OPEN = 1
    BAR_CLOSE = 2

class FillPhase(IntEnum):
    SAME_OPEN = 1
    SAME_CLOSE = 2
    NEXT_OPEN = 3
    NEXT_CLOSE = 4

class SameBarPolicy(IntEnum):
    CONSERVATIVE = 1
    STOP_FIRST = 2
    TP_FIRST = 3
    OHLC_PATH = 4
    OLHC_PATH = 5
    REJECT_AMBIGUOUS = 6
    LOWER_TIMEFRAME_REQUIRED = 7
```

Không truyền Enum vào Numba kernel. Compile thành integer codes trước khi gọi kernel.

## 8.2 Prepared market tape

```python
@dataclass(frozen=True)
class PreparedMarketTape:
    timestamps_ns: np.ndarray

    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray

    funding_rates: np.ndarray
    funding_event_mask: np.ndarray

    contract_sizes: np.ndarray
    leverages: np.ndarray
    fee_rates_maker: np.ndarray
    fee_rates_taker: np.ndarray

    tick_sizes: np.ndarray
    qty_steps: np.ndarray
    min_qty: np.ndarray
    min_notional: np.ndarray

    signature: str
    validation_certificate: MarketValidationCertificate
```

Quy tắc:

- C-contiguous;
- `float64` cho price/accounting;
- `int64` timestamps;
- read-only sau preparation;
- không build lại giữa các trial.

## 8.3 Intrabar intent tape

V1 tập trung vào một position aggregate cho mỗi symbol:

```python
@dataclass(frozen=True)
class IntrabarIntentTape:
    # -1 short, 0 no new entry, +1 long
    entry_side: np.ndarray

    # sizing input, interpretation fixed by sizing_code
    entry_size: np.ndarray

    # known at decision close
    stop_value: np.ndarray
    take_profit_value: np.ndarray
    trailing_value: np.ndarray

    # close-generated exit intent, effective next bar
    technical_exit: np.ndarray

    # optional reversal permission and feature flags
    flags: np.ndarray
```

Level modes:

```text
ABSOLUTE_PRICE
PRICE_DISTANCE
PERCENT_DISTANCE
ATR_DISTANCE_ALREADY_COMPUTED
```

Khuyến nghị v1:

- alpha tính ATR hoặc volatility;
- alpha xuất **distance causal** ở close;
- engine tính exact stop/TP từ actual next-open fill.

Ví dụ:

```text
signal close[t]
ATR[t] đã biết
stop_distance[t] = ATR[t] * sl_mult
tp_distance[t]   = ATR[t] * tp_mult

open[t+1] fill = actual entry
SL/TP được dựng từ actual fill
```

Cách này đúng hơn alpha tự dựng level từ close tín hiệu.

---

## 9. Timeline chuẩn của `intrabar_bracket_v1`

Mỗi bar phải xử lý theo thứ tự cố định:

```text
BAR t START

1. Validate prepared tape certificate.
   Không chạy pandas validation trong kernel.

2. Mark carried position từ close[t-1] đến open[t].

3. Xử lý gap risk/liquidation tại open[t] theo liquidation policy.

4. Execute pending commands sinh từ close[t-1]:
   - technical exit;
   - reversal close leg;
   - new entry;
   - fill tại open[t] ± slippage.

5. Sau khi entry fill:
   - tính initial stop;
   - tính take profit;
   - activate bracket ngay trong bar t.

6. Resolve intrabar:
   - stop;
   - take profit;
   - liquidation;
   - same-bar conflicts;
   - gap semantics.

7. Ghi tất cả fill events trong bar theo sequence.
   Entry và exit cùng bar không được nén thành flat.

8. Mark remaining position từ last execution reference đến close[t].

9. Apply funding event đúng timestamp/phase.

10. Tính close-based alpha state bên ngoài kernel hoặc đọc intent tape:
    - technical exit mới chỉ pending cho bar t+1;
    - reversal signal mới chỉ pending cho bar t+1.

11. Update trailing stop bằng close[t].
    Stop mới chỉ hiệu lực từ bar t+1.

12. Snapshot:
    - equity;
    - position;
    - average entry;
    - active stop;
    - active TP;
    - fee/funding;
    - margin;
    - event flags.

BAR t END
```

### 9.1 Không được phép

```text
dùng close[t] để cập nhật trailing
rồi dùng low[t]/high[t] để hit stop mới
```

Đó là look-ahead intrabar.

### 9.2 Entry và exit cùng bar

Ví dụ:

```text
open[t] entry long = 100
low[t] hits stop = 95
close[t] = 103
```

Kết quả bắt buộc:

```text
fill 1: BUY  @ 100
fill 2: SELL @ 95
position EOB = 0
realized PnL < 0
2 fee legs
```

Không được chỉ xuất:

```text
pos_weight[t] = 0
```

---

## 10. Fill semantics chuẩn

## 10.1 Market next-open

Buy:

$$
P_{\text{fill}} = O_t \times (1 + s)
$$

Sell:

$$
P_{\text{fill}} = O_t \times (1 - s)
$$

Trong đó:

- $O_t$ là open;
- $s$ là slippage rate.

## 10.2 Stop-market gap-aware

Long position có sell stop $S$:

```text
nếu open[t] <= S:
    fill = open[t] với adverse slippage
elif low[t] <= S:
    fill = S với adverse slippage
```

Short position có buy stop $S$:

```text
nếu open[t] >= S:
    fill = open[t] với adverse slippage
elif high[t] >= S:
    fill = S với adverse slippage
```

Không được luôn fill tại trigger khi gap qua stop.

## 10.3 Take-profit limit

Long TP sell limit $T$:

```text
nếu open[t] >= T:
    conservative: fill = T
    price_improvement: fill = open[t]
elif high[t] >= T:
    fill = T
```

Default Phase 17:

```text
take_profit_gap_policy = LIMIT_PRICE_CONSERVATIVE
```

Có thể thêm opt-in:

```text
OPEN_PRICE_IMPROVEMENT
```

nhưng metadata phải ghi rõ.

## 10.4 Same-bar SL và TP cùng chạm

Default:

```text
CONSERVATIVE -> adverse exit first
```

Long:

```text
SL first
```

Short:

```text
SL first
```

Engine phải tăng:

```text
ambiguous_bar_count
```

và set event flag.

## 10.5 Technical exit

Technical exit sinh tại close:

```text
không fill tại close vừa dùng để phát hiện
fill tại next open
```

Trừ khi strategy contract explicitly là same-close và alpha không dùng close để quyết định.

## 10.6 Reversal

Reversal phải là hai legs:

```text
1. close/reduce old position
2. open new opposite position
```

Fee và slippage áp cho cả hai.

Không được chỉ thay dấu position rồi tính một fee mơ hồ.

---

## 11. Accounting chuẩn

V1 hỗ trợ linear contracts.

### 11.1 Price PnL

$$
\Delta PnL_t = q_{t^-} \times (P_b - P_a) \times C
$$

Trong đó:

- $q$ là signed quantity;
- $C$ là contract size;
- $P_a, P_b$ là hai mark/execution references liên tiếp.

### 11.2 Fee

$$
Fee = |q_{\text{fill}}| \times P_{\text{fill}} \times C \times f
$$

Maker/taker phải tách riêng nếu backend công bố liquidity side.

### 11.3 Equity identity

Mỗi bar phải thỏa trong tolerance:

$$
Equity_t =
Equity_{t-1}
+ PricePnL_t
- Fees_t
- Funding_t
- LiquidationCosts_t
$$

Nếu có deposits/withdrawals sau này thì thêm explicit cash-flow term.

### 11.4 Reversal accounting

Từ long $+q$ sang short $-q$:

```text
sell q để flat
sell q để short
```

Turnover:

$$
Turnover = 2q \times P_{\text{fill}} \times C
$$

### 11.5 End-of-backtest

Config:

```python
close_on_last_bar=True
```

Default cho trade statistics/audit.

Nếu false:

- equity giữ unrealized;
- open trade phải xuất trong report;
- trade count và closed-trade metrics phải phân biệt.

---

## 12. Margin và liquidation

## 12.1 Initial margin

$$
IM = \frac{|q| \times P \times C}{L}
$$

## 12.2 Maintenance margin

$$
MM = |q| \times P \times C \times m
$$

## 12.3 Single-symbol v1

Phase 17 intrabar kernel nên chứng nhận single-symbol linear contract trước.

Lý do:

- dễ xác định path policy;
- không có joint cross-symbol high/low ambiguity;
- phù hợp đa số alpha SL/TP hiện tại;
- giảm scope và rủi ro implementation.

## 12.4 Multi-symbol independent accounts

Có thể thêm sau khi single-symbol pass:

```text
mỗi symbol có cash/equity/margin riêng
```

Có thể parallel theo symbol.

## 12.5 Shared cross-margin portfolio

Không đưa vào intrabar v1 như một claim “exact”.

OHLC của nhiều symbol không cho biết các extremes xảy ra cùng thời điểm. Cần explicit policy:

```text
CONSERVATIVE_JOINT_EXTREME
SEQUENTIAL_SYMBOL
CLOSE_ONLY
LOWER_TIMEFRAME_REQUIRED
```

Result phải ghi:

```text
portfolio_intrabar_path_is_ambiguous = true
```

## 12.6 Liquidation vs protective stop

Đây là venue/risk semantics, không nên hard-code ngầm.

Config:

```text
LIQUIDATION_FIRST
USER_STOP_FIRST
VENUE_MARK_PRICE_MODEL
```

Default derivatives conservative:

```text
LIQUIDATION_FIRST_AT_GAP
```

Nhưng phải có golden tests và docs.

---

## 13. Funding đúng domain

### 13.1 Không dùng default giả

Sửa:

```python
fr_input.get(symbol, 0.0001)
```

thành strict behavior:

```python
if symbol not in fr_input:
    raise KeyError(...)
```

hoặc explicit:

```python
missing_funding_policy="zero"
```

Default production:

```text
raise
```

Default khi `use_funding=False`:

```text
zero
```

### 13.2 Dùng funding event timestamps

Không chỉ kiểm tra exact `hour in {0, 8, 16}`.

Chuẩn:

```text
previous_bar_timestamp < funding_event_timestamp <= current_bar_timestamp
```

Input:

```python
funding_event_times_ns
funding_event_rates
```

Preprocessor compile thành:

```python
funding_event_mask
funding_rate_matrix
```

### 13.3 Funding position phase

Phải công bố position nào chịu funding:

```text
POSITION_BEFORE_EVENT
POSITION_AFTER_OPEN_FILL
POSITION_AT_CLOSE
```

Đối với venue perpetual, mô hình nên bám exact event timestamp nếu có.

---

## 14. Strict market-data preparation

## 14.1 Không tự sửa OHLC

Default strict:

- duplicate timestamp -> error;
- unsorted -> error;
- timezone missing -> require explicit timezone hoặc normalize có log;
- missing OHLC -> error;
- NaN/inf -> error;
- invalid OHLC invariant -> error;
- missing symbol bar -> error;
- zero/negative price -> error;
- negative volume -> error.

Không được:

```text
sort silently
drop duplicate silently
ffill OHLC
bfill OHLC
fallback high/low=open/close
```

## 14.2 Vectorized validation

Các check phải chạy bằng NumPy reductions, không Python loop trên bar:

```python
finite_ok = np.isfinite(ohlcv).all()

ohlc_ok = (
    (lows <= opens)
    & (lows <= closes)
    & (highs >= opens)
    & (highs >= closes)
    & (highs >= lows)
).all()
```

Timestamp:

```python
is_strictly_increasing = np.all(ts[1:] > ts[:-1])
```

Chi phí này chạy một lần khi build tape.

## 14.3 Validation modes

```text
strict
trusted_prepared
debug
```

- `strict`: full validation, tạo certificate.
- `trusted_prepared`: chỉ nhận `PreparedMarketTape` đã có certificate/signature.
- `debug`: thêm internal assertions và parity diagnostics.

Không nên public `off` trong production endpoint.

## 14.4 Validation certificate

```python
@dataclass(frozen=True)
class MarketValidationCertificate:
    signature: str
    row_count: int
    symbol_count: int
    timezone: str
    first_timestamp: int
    last_timestamp: int

    finite_ok: bool
    ohlc_ok: bool
    monotonic_ok: bool
    unique_ok: bool
    alignment_ok: bool

    validator_version: str
```

---

## 15. Cách giữ tốc độ gần `native_vectorized`

Đây là phần bắt buộc của thiết kế, không phải tối ưu sau cùng.

## 15.1 Thực tế profiling hiện tại

Benchmark hiện tại cho workload 25,000 bars x 20 symbols ghi nhận:

- full `native_vectorized`: khoảng `0.463s`;
- pure `_engine_units_v2`: khoảng `0.006s` trong profiling cũ;
- trước tối ưu, phần lớn thời gian nằm ở:
  - data normalization;
  - target sizing;
  - pandas-to-ndarray;
  - report construction.

Điều này có nghĩa:

> Thêm logic intrabar vào Numba loop không nhất thiết làm full endpoint chậm theo cùng tỷ lệ với số branch trong kernel.

Nếu pure kernel tăng 3–4 lần nhưng facade được prepare/cache tốt, total runtime vẫn có thể thấp hơn rất nhiều so với `native_event`.

## 15.2 Không tạo fill objects trong hot loop

Tuyệt đối không:

```python
fills.append(Fill(...))
```

trong bar loop.

Kernel chỉ ghi primitive arrays và counters.

## 15.3 Ba report levels

### `minimal`

Dùng cho Optuna/WFO:

- equity array hoặc returns;
- final equity;
- fees/funding aggregate;
- trade count;
- max drawdown helper inputs;
- event count;
- rejected count;
- ambiguity count.

Không có:

- fill DataFrame;
- order objects;
- trade objects;
- pandas report.

### `standard`

Thêm:

- position EOB;
- active stop/TP nếu cần;
- fee/funding per bar;
- event flags;
- margin diagnostics.

### `audit`

Thêm:

- exact sparse fills;
- exact trades;
- sequence;
- exit reason;
- order/fill reports;
- parity bundle.

## 15.4 Two-pass sparse fill ledger

Đây là lựa chọn khuyến nghị.

### Pass 1 — accounting/minimal

Kernel chạy một lần:

- tính toàn bộ equity/accounting;
- đếm exact `fill_count`;
- ghi event flags;
- không allocate fill arrays lớn.

### Pass 2 — audit replay

Chỉ khi `report_level="audit"`:

1. allocate arrays đúng bằng `fill_count`;
2. replay cùng deterministic state machine;
3. ghi fill records;
4. assert core outputs parity với pass 1.

Ưu điểm:

- optimizer không chịu chi phí ledger;
- audit không dùng worst-case dense allocation;
- không cần dynamic Python list;
- memory tỷ lệ với fills thật;
- exact sequence được giữ.

Audit mode có thể gần 2x kernel runtime, nhưng không làm chậm hàng nghìn trial.

## 15.5 Compact event flags luôn bật

Có thể giữ một `uint16` cho mỗi bar-symbol:

```text
ENTRY_FILLED
EXIT_FILLED
STOP_FILLED
TP_FILLED
TECH_EXIT
REVERSAL
LIQUIDATION
AMBIGUOUS
REJECTED
FUNDING
```

Memory:

```text
2 bytes × bars × symbols
```

Rất nhỏ so với nhiều float64 matrices.

## 15.6 Prepared context mở rộng

Mở rộng `prepare_service_context(...)` thành:

```python
ctx = endpoint.prepare_service_context(
    data=df,
    execution_contract=contract,
    instruments=instruments,
    strict=True,
)
```

Context cache:

- UTC index;
- OHLCV arrays;
- funding events;
- instrument arrays;
- data signature;
- validation certificate;
- compiled scalar config;
- reusable output buffers khi an toàn.

Trong mỗi trial chỉ truyền:

- signal/intent arrays;
- stop/tp/trailing arrays;
- sizing parameters.

## 15.7 Lazy result materialization

Tạo internal result:

```python
NativeRunBuffers
```

Không build pandas ngay.

```python
buffers.metrics()
buffers.to_backtest_result_v2()
buffers.to_audit_bundle()
```

Optuna chỉ gọi `metrics()`.

Normal endpoint vẫn materialize `BacktestResultV2` để tương thích.

## 15.8 Kernel specialization có giới hạn

Không tạo một generic kernel với hàng chục branch.

Các kernel variants:

```text
_engine_next_open_v1
_engine_intrabar_fixed_bracket_v1
_engine_intrabar_trailing_v1
_engine_fill_replay_v1
```

Mỗi variant có logic đủ hẹp để branch predictor và Numba tối ưu tốt.

Không nên tạo hàng trăm JIT combinations.

## 15.9 Feature bitmask

Các feature nhỏ dùng bitmask:

```python
USE_SL       = 1 << 0
USE_TP       = 1 << 1
USE_TRAILING = 1 << 2
USE_TECH     = 1 << 3
ALLOW_REVERSAL = 1 << 4
```

Flags ổn định trong cả run, branch prediction tốt hơn per-bar dynamic enum.

## 15.10 Data layout

- OHLCV: C-contiguous `[n_bars, n_symbols]`;
- inner loop theo symbol;
- state arrays theo symbol;
- integer codes `int8/int16`;
- timestamps `int64`;
- prices/accounting `float64`;
- không object dtype;
- không dict lookup trong kernel.

## 15.11 Fastmath

Correctness kernel mặc định:

```python
@njit(cache=True, nogil=True, fastmath=False)
```

Chỉ xem xét `fastmath=True` sau:

- parity đầy đủ;
- NaN đã bị reject;
- benchmark chứng minh lợi ích đáng kể;
- accounting tolerance không drift.

Không đổi correctness lấy vài phần trăm runtime khi chưa có bằng chứng.

## 15.12 Parallelization đúng chỗ

Một account path-dependent không nên `prange` theo bar.

Parallel phù hợp:

- nhiều parameter candidates độc lập;
- nhiều symbols với independent accounts;
- nhiều WFO folds độc lập;
- nhiều datasets độc lập.

Đề xuất thêm batched kernel:

```python
_engine_intrabar_batch_v1(
    intents_3d,  # candidate x bar x symbol
    ...
)
```

`prange` theo candidate axis.

Không parallel shared cross-margin symbols nếu làm thay đổi order/margin sequence.

## 15.13 Không chuyển sang Cython/C++ quá sớm

Repo hiện đã có profiling chứng minh facade/report overhead từng là bottleneck lớn hơn pure kernels.

Thứ tự tối ưu:

```text
prepared tape
→ ndarray intent compiler
→ lazy result
→ two-pass audit
→ batch trials
→ profile pure kernel
→ chỉ sau đó mới cân nhắc Cython/C++
```

---

## 16. Performance targets

Các target phải đo trên cùng machine, cùng data, warm JIT, cùng report level.

### 16.1 Kernel-only ratio

So với `close_target_v2` pure kernel:

| Kernel | Target |
|---|---:|
| `next_open_v1` | <= 1.75x |
| fixed SL/TP intrabar | <= 3.0x |
| SL/TP + trailing | <= 4.0x |
| fill replay | <= 2.0x |
| audit second pass total | <= 2.2x cùng kernel minimal |

Các ratio này là gate ban đầu, có thể siết sau profiling.

### 16.2 Prepared endpoint ratio

So với prepared close-target:

| Route | Target |
|---|---:|
| next-open minimal | <= 1.5x |
| fixed bracket minimal | <= 2.0x |
| trailing minimal | <= 2.5x |
| audit full | <= 4.0x |

### 16.3 So với `native_event`

Với single-position fixed bracket:

```text
native_intrabar minimal phải nhanh hơn native_event prepared ít nhất 5x
```

Mục tiêu tốt:

```text
10x+
```

### 16.4 Memory

Minimal mode:

- không sparse fill arrays;
- không Python Fill/Trade objects;
- event flags nhỏ;
- peak memory không quá 1.5x close-target cho cùng tape.

Audit mode:

- memory tỷ lệ với actual fills;
- không preallocate `2 * bars * symbols` float64 records nếu không cần.

---

## 17. Pseudocode fast intrabar kernel

```python
@njit(cache=True, nogil=True)
def _engine_intrabar_fixed_bracket_v1(
    opens,
    highs,
    lows,
    closes,

    entry_side,
    entry_size,
    stop_value,
    tp_value,
    technical_exit,

    funding_rates,
    funding_mask,

    initial_capital,
    leverage,
    maintenance_ratio,
    contract_size,
    taker_fee,
    slippage,

    level_mode,
    same_bar_policy,
    close_on_last_bar,

    record_fills,
    fill_bar_idx,
    fill_side,
    fill_qty,
    fill_price,
    fill_fee,
    fill_reason,
):
    n = len(closes)

    equity = initial_capital
    position = 0.0
    avg_entry = 0.0

    active_stop = 0.0
    active_tp = 0.0

    pending_side = 0
    pending_size = 0.0
    pending_stop_value = 0.0
    pending_tp_value = 0.0
    pending_exit = False

    fill_n = 0

    for t in range(1, n):
        # A. mark previous close -> current open
        if position != 0.0:
            equity += position * (opens[t] - closes[t - 1]) * contract_size

        # B. pending exit/reversal/new entry at open
        #    record each leg separately

        # C. build bracket from actual entry fill

        # D. intrabar stop/tp resolution
        #    gap-aware
        #    same-bar policy
        #    ambiguity flag

        # E. mark remaining position to close
        #    use last fill reference correctly

        # F. funding event

        # G. close-generated intents become pending for t+1

        # H. trailing update for next bar only

        # I. snapshot arrays

    # optional close on final bar

    return core_outputs, fill_n
```

Production implementation phải tách helper logic vừa đủ để Python oracle và Numba dùng cùng semantics specification, nhưng không gọi Python object trong kernel.

---

## 18. Fast fill replay backend

## 18.1 Mục đích

Nhiều alpha hiện tại đã tự tính:

- entry at open;
- stop/tp;
- trailing;
- `exit_price`;
- `exit_type`.

Không thể tái tạo chính xác trade chỉ từ:

```text
pos_weight
exit_price
exit_type
```

vì có thể thiếu:

- entry price;
- quantity;
- multiple fills;
- reversal legs;
- sequence;
- same-bar entry/exit.

Adapter migration phải yêu cầu alpha xuất explicit fill tape.

## 18.2 Compact fill tape

```python
@dataclass(frozen=True)
class CompactFillTape:
    bar_index: np.ndarray      # int32
    sequence: np.ndarray       # int8
    side: np.ndarray           # int8
    qty: np.ndarray            # float64
    price: np.ndarray          # float64
    reason: np.ndarray         # int16
    liquidity: np.ndarray      # int8
```

## 18.3 Validation

Fill replay kiểm tra:

- bar index tăng theo `(bar, sequence)`;
- qty > 0;
- price finite;
- tick/lot constraints;
- sell/buy direction hợp lệ với position;
- reduce-only không tăng exposure;
- fill price hợp lệ với order type và OHLC policy;
- không fill trước signal effective phase;
- cash/margin không âm ngoài policy;
- final position continuity.

## 18.4 Certification label

Result metadata:

```json
{
  "engine": "fill_replay_v1",
  "accounting_certified": true,
  "execution_generated_by_engine": false,
  "causality_certified": false
}
```

Sau khi alpha được migrate sang engine-owned intrabar intent, label có thể thành:

```json
{
  "engine": "intrabar_bracket_v1",
  "accounting_certified": true,
  "execution_generated_by_engine": true,
  "causality_certified": true
}
```

---

## 19. Backward compatibility

## 19.1 Không xóa `native_vectorized`

Giữ:

```python
backend="native_vectorized"
```

nhưng map rõ:

```text
native_vectorized -> close_target_v2
```

Metadata:

```json
{
  "backend_alias": "native_vectorized",
  "engine": "close_target_v2",
  "signal_phase": "bar_close",
  "fill_phase": "same_close",
  "intrabar_exit_model": "none"
}
```

## 19.2 Phased strictness

### Release A

- thêm metadata;
- thêm docs;
- warning khi tên column gợi ý intrabar:
  - `exit_price`;
  - `stop_loss`;
  - `take_profit`;
  - `exit_type`;
  - `trailing`.
- warning không đủ để certification.

### Release B

Public endpoint mới mặc định strict:

```python
execution_contract=ExecutionContract.close_target()
```

Nếu alpha khai báo intrabar nhưng chọn close-target:

```python
raise ExecutionContractError
```

### Release C

Bắt buộc `execution_contract` cho WFO/optimizer mới.

Legacy runs vẫn tái tạo qua:

```python
compatibility_mode="legacy_close_target"
```

## 19.3 Không auto-convert `pos_weight` intrabar

Không thể tự động chuyển chính xác.

Phải:

- sửa alpha xuất intent/levels;
- hoặc xuất explicit fill tape;
- hoặc giữ result cũ là uncertified.

---

## 20. Public API đề xuất

## 20.1 Close-target

```python
bt = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    execution_contract=ExecutionContract.close_target(),
    report_level="minimal",
    ...
)
```

## 20.2 Fast intrabar

```python
bt = QuantBTEndpoint.intrabar(
    execution_contract=ExecutionContract.next_open_bracket(
        same_bar_policy="conservative",
        stop_gap_policy="open_worse_than_trigger",
        take_profit_gap_policy="limit_price",
        trailing_update_phase="next_bar",
        close_on_last_bar=True,
    ),
    initial_capital=100_000.0,
    leverage=1.0,
    fee_rate=0.0004,
    slippage_bps=2.0,
    report_level="minimal",
)

result = bt.backtest(
    data=df,
    entry_signal=entry_signal,
    entry_size=entry_size,
    stop_distance=stop_distance,
    take_profit_distance=tp_distance,
    trailing_distance=trailing_distance,
    technical_exit=technical_exit,
)
```

## 20.3 Prepared optimization

```python
ctx = bt.prepare_service_context(
    data=df,
    strict=True,
)

for params in candidates:
    intent = strategy.generate_intent_arrays(ctx.market, params)

    score = ctx.run_intrabar(
        intent=intent,
        report_level="minimal",
    ).metrics()["sharpe"]
```

## 20.4 Audit rerun

```python
audit_result = ctx.run_intrabar(
    intent=best_intent,
    report_level="audit",
)

audit_result.export_fills("fills.csv")
audit_result.export_trades("trades.csv")
```

## 20.5 Fill replay

```python
bt = QuantBTEndpoint.fill_replay(
    execution_contract=legacy_contract,
    report_level="audit",
)

result = bt.backtest(
    data=df,
    fills=compact_fill_tape,
)
```

---

## 21. File-by-file implementation plan

## 21.1 New files

```text
core/execution_contract.py
core/market_tape.py
core/intrabar.py
core/intrabar_reference.py
core/fill_replay.py
core/event_flags.py
core/native_buffers.py

backends/native_intrabar.py
backends/native_fill_replay.py

tests/test_phase17_execution_contract.py
tests/test_phase17_market_tape_strict.py
tests/test_phase17_intrabar_reference.py
tests/test_phase17_intrabar_kernel.py
tests/test_phase17_intrabar_property.py
tests/test_phase17_fill_replay.py
tests/test_phase17_endpoint.py
tests/test_phase17_backward_compat.py
tests/test_phase17_performance_guards.py

benchmarks/run_phase17_intrabar.py
benchmarks/profile_phase17_intrabar.py
benchmarks/phase17_thresholds.json

docs/execution_contracts.md
docs/fast_intrabar.md
docs/alpha_certification.md

upgrade/phase17_execution_correctness_fast_intrabar.md
```

## 21.2 Sửa `core/schema.py`

- giữ enums cũ để compatibility;
- thêm execution contract enums;
- deprecate fields không được thực thi hoặc enforce chúng;
- thêm `__post_init__` validation;
- không cho config unsupported đi qua im lặng.

## 21.3 Sửa `core/preprocessor.py`

- tách:
  - strict OHLC preparation;
  - factor alignment;
  - funding alignment.
- bỏ default funding `0.0001`;
- không ffill OHLC;
- funding dùng event crossing;
- tạo `PreparedMarketTape`.

## 21.4 Sửa `core/vectorized.py`

- giữ `_engine_units_v2`;
- đổi metadata/registry ID thành `close_target_v2`;
- xử lý rõ first bar;
- thêm optional atomic/proportional margin policy;
- không nhận intrabar config;
- thêm invariant helpers.

## 21.5 Sửa `backends/native_vectorized.py`

- fail nếu high/low thiếu khi liquidation enabled;
- không fallback OHLC;
- dùng prepared tape;
- lazy result;
- metadata execution contract;
- warnings/errors cho intrabar misuse;
- không tạo fills giả.

## 21.6 Sửa `backends/native_event.py`

- thực thi thật `FillPricePolicy`;
- thực thi thật `SameBarPolicy`;
- market next-open/open/close đúng config;
- gap-aware stop;
- truyền open/volume vào static replay;
- parity với Python oracle cho shared scenarios.

## 21.7 Sửa `engines.py`

- truyền `opens`, `volumes`;
- route theo engine ID;
- không suy luận contract từ backend name;
- prepared context support cho intrabar/fill replay.

## 21.8 Sửa `endpoint.py`

Thêm:

```text
QuantBTEndpoint.intrabar(...)
QuantBTEndpoint.fill_replay(...)
```

Mở rộng:

```text
prepare_service_context(...)
```

Thêm:

- `execution_contract`;
- `report_level`;
- `validation_mode`;
- `certification_mode`.

## 21.9 Sửa `core/results.py`

Thêm metadata bắt buộc:

```text
engine_id
kernel_version
execution_contract
data_signature
validation_certificate
report_level
ambiguity_count
fill_count
certification_status
```

Hỗ trợ lazy fill/trade construction.

---

## 22. P0 fixes phải làm trước kernel mới

Commit riêng, không chờ intrabar engine:

1. Funding missing symbol không còn fallback `0.0001`.
2. Strict duplicate/unsorted handling.
3. Không ffill/bfill OHLC mặc định.
4. Không fallback high/low về close khi liquidation.
5. `ExecutionConfig` unsupported phải raise.
6. `engines.py` truyền open/volume cho reactive path.
7. First-bar target policy rõ ràng.
8. Metadata ghi close-target semantics.
9. Result ghi data signature/kernel version.
10. Test mọi fix trước khi refactor lớn.

---

## 23. Python reference oracle

## 23.1 Mục đích

`intrabar_reference.py` phải:

- Python thuần;
- code dễ đọc;
- không tối ưu;
- không dùng Numba;
- explicit state transitions;
- explicit fills;
- là nguồn chân lý nội bộ.

## 23.2 Parity

Mọi Numba run phải so được với oracle:

```text
equity
position
average entry
active stop
active TP
fees
funding
margin
fill count
fill side
fill qty
fill price
fill reason
ambiguity flags
liquidation state
```

Tolerance:

```python
atol = 1e-10
rtol = 1e-10
```

Có thể nới cho long cumulative series nhưng phải ghi lý do.

## 23.3 Property tests

Dùng Hypothesis hoặc deterministic randomized generator:

- random valid OHLC;
- random signals;
- random stop/tp distance;
- random gaps;
- random reversals;
- random fee/slippage;
- long/short symmetry.

Mỗi seed:

```text
reference == Numba
```

---

## 24. Golden scenario matrix

## 24.1 Timeline

- signal close -> entry next open;
- no same-close execution;
- first bar signal handling;
- last bar close;
- missing next bar.

## 24.2 Entry

- long;
- short;
- gap favorable;
- gap adverse;
- quantity rounding;
- min notional reject;
- insufficient margin reject.

## 24.3 Stop loss

- wick touch;
- exact touch;
- gap through stop;
- no touch;
- long/short symmetry.

## 24.4 Take profit

- wick touch;
- exact touch;
- favorable gap;
- conservative limit fill;
- price-improvement policy.

## 24.5 Same-bar

- entry + SL;
- entry + TP;
- entry + both SL/TP;
- carried position + both;
- ambiguous reject policy;
- OHLC/OLHC path policies.

## 24.6 Trailing

- update at close;
- new stop effective next bar;
- stop only tightens;
- long/short symmetry;
- trailing plus TP;
- trailing after gap.

## 24.7 Technical exit

- close signal;
- next-open fill;
- technical exit vs reversal;
- technical exit after intrabar stop should not double exit.

## 24.8 Reversal

- long -> short;
- short -> long;
- two fee legs;
- reversal then SL same bar;
- reversal margin rejection behavior.

## 24.9 Funding

- exact event bar;
- timeframe skips exact hour;
- multiple funding events crossed by coarse bar;
- missing symbol;
- position opened before/after event.

## 24.10 Accounting

- equity identity;
- turnover;
- realized/unrealized split;
- fee per leg;
- final flatten;
- open trade report.

## 24.11 Data

- duplicate timestamp;
- unsorted timestamp;
- missing OHLC;
- invalid high/low;
- NaN/inf;
- missing symbol bar;
- timezone conversion.

## 24.12 Invariants

- deterministic;
- no future reads;
- symbol/order permutation invariance where contract requires;
- Python/Numba parity;
- minimal/audit core parity;
- prepared/non-prepared parity.

---

## 25. Benchmark design

## 25.1 Workloads

### Standard

```text
25,000 bars x 20 symbols
```

Giữ để so với Phase 7.

### Long single-symbol

```text
1,000,000 bars x 1 symbol
```

Đại diện crypto/VN futures intraday.

### Low-turnover

```text
1% bars có signal transition
```

### High-turnover

```text
30–50% bars có transition
```

### Stop-heavy

```text
nhiều bar hit SL/TP
```

### Ambiguous-heavy

```text
10% active bars chạm cả SL/TP
```

### WFO replay

```text
1 prepared tape
500–5,000 candidate intent tapes
```

## 25.2 Đo riêng

- cold compile time;
- warm kernel runtime;
- endpoint runtime;
- preparation runtime;
- result materialization;
- audit second pass;
- peak memory;
- bars/s;
- bar-symbols/s;
- fills/s;
- candidates/s.

## 25.3 Benchmark modes

```text
close_target minimal
next_open minimal
intrabar fixed minimal
intrabar trailing minimal
intrabar audit
fill replay minimal
native_event prepared
```

## 25.4 Không trộn tracemalloc với runtime gate

- runtime benchmark không tracemalloc;
- memory benchmark chạy riêng;
- cả hai lưu JSON/Markdown.

---

## 26. Audit toàn bộ alpha hiện tại

## 26.1 Inventory scanner

Tạo script:

```text
tools/audit_alpha_execution_contracts.py
```

Quét:

```bash
rg -n \
  "native_vectorized|signal_notional|BacktestEngineV2|QuantBTEndpoint" \
  /path/to/alphas
```

Quét intrabar markers:

```bash
rg -n \
  "exit_price|exit_type|stop_loss|take_profit|trailing|use_sl|use_tp|high\[|low\[" \
  /path/to/alphas
```

## 26.2 Registry

```yaml
alpha_id: bollinger_squeeze
version: v1
current_backend: native_vectorized

signal_phase: close
entry_phase: next_open

uses_intrabar_high_low: true
uses_stop: true
uses_take_profit: true
uses_trailing: true
uses_custom_exit_price: true
allows_same_bar_entry_exit: true

required_engine: intrabar_bracket_v1
current_status: invalid_backend
certification_status: uncertified
```

## 26.3 Classification

| Nhóm | Required engine |
|---|---|
| Pure close target | `close_target_v2` |
| Close signal, next-open only | `next_open_v1` |
| Single-position SL/TP/trailing | `intrabar_bracket_v1` |
| Alpha tự tạo explicit fills | `fill_replay_v1` tạm thời |
| Multi-order/grid/DCA | specialized/event |
| Shared cross-margin intrabar | audit/deferred contract |

## 26.4 Audit workflow

```text
1. Snapshot code hash và result cũ.
2. Gắn status UNCERTIFIED.
3. Xác định execution contract thật.
4. Nếu có đủ entry/exit events:
      chạy fill_replay để audit accounting.
5. Sửa alpha xuất intents/levels.
6. Rerun intrabar minimal.
7. Rerun best params bằng audit mode.
8. So sánh:
      trades
      fills
      fees
      return
      Sharpe
      MaxDD
      liquidation
9. Ghi migration report.
10. Chỉ promote khi pass certification.
```

## 26.5 Không giữ best params cũ một cách mù quáng

Do execution semantics thay đổi:

- params tối ưu cũ có thể không còn tối ưu;
- cần rerun optimization;
- so sánh result cũ chỉ để đo drift, không dùng làm truth.

---

## 27. Certification levels

```text
LEVEL 0 — Legacy
Chạy được nhưng execution contract không xác định.

LEVEL 1 — Accounting Replay
Explicit fills được account đúng, nhưng fill generation do alpha chịu trách nhiệm.

LEVEL 2 — Engine-Causal
Intent causal, engine-owned next-open/intrabar execution, Python parity pass.

LEVEL 3 — Cross-Backend
Native intrabar parity với native event trên golden scenarios.

LEVEL 4 — External Validation
Subset parity/known differences với Nautilus hoặc lower timeframe.
```

Production alpha tối thiểu:

```text
LEVEL 2
```

Alpha vốn phụ thuộc execution mạnh:

```text
LEVEL 3 hoặc LEVEL 4
```

---

## 28. Rollout phases và commit boundaries

Tuân thủ `AGENTS.md`: làm trên `dev`, giữ unrelated dirty changes, commit sau mỗi coherent verified change.

## Phase 17A — Freeze semantics và P0 safety

Deliverables:

- execution metadata;
- strict P0 data/funding fixes;
- unsupported config raises;
- open/volume plumbing;
- tests.

Acceptance:

- không đổi intentional close-target PnL;
- các silent errors trở thành explicit failures;
- legacy reproduction có compatibility flag.

## Phase 17B — Execution contract schema

Deliverables:

- contract dataclass/enums;
- registry;
- endpoint routing;
- docs.

Acceptance:

- mọi result có engine/contract ID;
- backend không thể nhận unsupported semantics.

## Phase 17C — Prepared market tape

Deliverables:

- strict validation;
- cached arrays/signature;
- prepared context parity.

Acceptance:

- normal/prepared parity;
- validation chỉ chạy một lần.

## Phase 17D — Python intrabar oracle

Deliverables:

- full single-symbol semantics;
- fills/trades;
- golden scenarios.

Acceptance:

- toàn bộ domain tests pass.

## Phase 17E — Numba intrabar minimal kernel

Deliverables:

- next open;
- SL/TP;
- gap;
- reversal;
- technical exit;
- trailing variant;
- event flags.

Acceptance:

- exact parity với oracle;
- performance gates pass.

## Phase 17F — Two-pass audit ledger

Deliverables:

- exact sparse fills;
- exact trades;
- audit result;
- minimal/audit parity.

Acceptance:

- core equity identical;
- no fill loss/overwrite.

## Phase 17G — Fill replay migration backend

Deliverables:

- compact tape;
- validation;
- accounting kernel;
- certification metadata.

Acceptance:

- existing alpha adapters có thể migrate từng bước.

## Phase 17H — Alpha audit tooling

Deliverables:

- scanner;
- registry;
- migration reports;
- status dashboard.

Acceptance:

- mọi alpha intrabar được inventory.

## Phase 17I — Native event contract fixes

Deliverables:

- FillPricePolicy thực thi;
- SameBarPolicy thực thi;
- gap-aware stop;
- open/volume replay;
- parity tests.

Acceptance:

- native intrabar/native event known cases agree.

## Phase 17J — Benchmark/certification

Deliverables:

- Phase 17 benchmark reports;
- thresholds;
- docs;
- upgrade report.

Acceptance:

- correctness gates pass;
- speed targets đạt hoặc có profile rõ;
- không claim production nếu threshold miss chưa giải thích.

---

## 29. Acceptance gates cuối cùng

Không merge/promote Phase 17 nếu thiếu bất kỳ mục sau.

### Correctness

- [ ] Python oracle hoàn chỉnh.
- [ ] Numba parity.
- [ ] Minimal/audit parity.
- [ ] No-lookahead timeline tests.
- [ ] Same-bar ambiguity tests.
- [ ] Gap stop tests.
- [ ] Reversal tests.
- [ ] Funding crossing tests.
- [ ] Accounting identity.
- [ ] Strict data tests.
- [ ] Result metadata đầy đủ.

### Performance

- [ ] Prepared tape cache.
- [ ] No pandas in hot trial.
- [ ] No Python fill objects in kernel.
- [ ] Minimal mode không tạo fill ledger.
- [ ] Audit two-pass sparse.
- [ ] Kernel ratio gates.
- [ ] Prepared endpoint ratio gates.
- [ ] Native event speed comparison.
- [ ] Memory gate.

### Compatibility

- [ ] Legacy alias chạy.
- [ ] Legacy result reproduction documented.
- [ ] Warnings/errors rõ.
- [ ] Existing endpoint imports không vỡ.
- [ ] BacktestResultV2 consumers tiếp tục hoạt động.

### Audit

- [ ] Alpha scanner.
- [ ] Alpha registry.
- [ ] Certification statuses.
- [ ] Migration report template.
- [ ] Old intrabar results marked uncertified.

---

## 30. Các quyết định không được thay đổi tùy tiện trong implementation

1. Không dùng `pos_weight` để biểu diễn entry và exit cùng bar.
2. Không dùng close làm fallback cho open/high/low trong strict mode.
3. Không ffill OHLC.
4. Không tạo funding rate giả.
5. Không nhận config mà backend không thực thi.
6. Không update trailing rồi apply ngược vào cùng bar.
7. Không để thứ tự list quyết định SL hay TP.
8. Không materialize full fills trong optimizer.
9. Không dùng Python object trong Numba hot loop.
10. Không claim exact cross-margin intrabar nếu chỉ có multi-symbol OHLC.
11. Không optimize trước khi oracle/tests đúng.
12. Không chuyển Cython/C++ trước khi profile chứng minh pure kernel là bottleneck.

---

## 31. Mẫu migration cho Bollinger Squeeze

Alpha hiện tại nên bỏ phần account/position simulation khỏi signal generator.

Thay vì trả:

```text
pos_weight
exit_type
exit_price
```

nó trả:

```text
entry_side[t]
stop_distance[t]
tp_distance[t]
trailing_distance[t]
technical_exit[t]
```

Ví dụ:

```python
entry_side[t] = 1 if long_cond else -1 if short_cond else 0

stop_distance[t] = atr[t] * sl_mult
tp_distance[t] = atr[t] * tp_mult

technical_exit[t] = (
    current_signal_state == 1 and close[t] < bb_mid[t]
) or (
    current_signal_state == -1 and close[t] > bb_mid[t]
)
```

Engine:

```text
close[t] decision
→ open[t+1] entry
→ bracket dựng từ actual fill
→ intrabar resolution
→ trailing update close
```

Nếu chưa sửa alpha ngay, alpha phải xuất explicit fill tape để chạy `fill_replay_v1`.

---

## 32. Kết luận triển khai

Giải pháp tốt nhất không phải:

- tiếp tục dùng close-target kernel cho mọi alpha;
- hoặc chuyển mọi optimizer sang Python event engine;
- hoặc thêm fill DataFrame vào mọi trial;
- hoặc viết C++ ngay.

Giải pháp đúng là:

```text
giữ close_target kernel
+
thêm fast specialized intrabar Numba kernel
+
prepared immutable market tape
+
minimal optimizer pass
+
two-pass sparse audit ledger
+
Python reference oracle
+
explicit execution contracts
+
alpha certification registry
```

Cách này đạt đồng thời:

- đúng domain backtest;
- causal;
- có fill/trade audit;
- giữ tính kế thừa;
- không buộc rewrite mọi alpha cùng lúc;
- tốc độ gần fast path hiện tại;
- nhanh hơn event backend nhiều lần cho nhóm SL/TP phổ biến;
- có con đường kiểm tra lại toàn bộ alpha cũ một cách có hệ thống.

---

## 33. Source references — nhánh `dev` tại thời điểm kiểm định

- Repository dev:
  https://github.com/BobbyAxerol/quantbt/tree/dev

- Current close-target Numba kernel:
  https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/core/vectorized.py

- Native vectorized backend:
  https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/backends/native_vectorized.py

- Native event backend:
  https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/backends/native_event.py

- Shared schema:
  https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/core/schema.py

- Preprocessor/funding/alignment:
  https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/core/preprocessor.py

- Engine routing:
  https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/engines.py

- Public endpoint:
  https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/endpoint.py

- Backend selection docs:
  https://github.com/BobbyAxerol/quantbt/blob/dev/docs/backend_selection.md

- Fill policy docs:
  https://github.com/BobbyAxerol/quantbt/blob/dev/docs/order_fill_policies.md

- Vectorized vs event-driven docs:
  https://github.com/BobbyAxerol/quantbt/blob/dev/docs/vectorized_vs_event_driven.md

- Current vectorized tests:
  https://github.com/BobbyAxerol/quantbt/blob/dev/tests/test_phase2_native_vectorized.py

- Native event lifecycle tests:
  https://github.com/BobbyAxerol/quantbt/blob/dev/tests/test_phase30b_native_event_lifecycle_kernel.py

- Existing upgrade plan:
  https://github.com/BobbyAxerol/quantbt/blob/dev/upgrade/implement.md

- Phase 7 profiling:
  https://github.com/BobbyAxerol/quantbt/blob/dev/benchmarks/phase7_profile_report.md

- Phase 9 optimization report:
  https://github.com/BobbyAxerol/quantbt/blob/dev/benchmarks/phase9_optimization_report.md

- Phase 16 prepared context/performance report:
  https://github.com/BobbyAxerol/quantbt/blob/dev/benchmarks/phase16_performance_debt.md



# PHẦN UPDATE BỔ SUNG:
# Nâng cấp QuantBT Intrabar với Session Execution State

## 1. Mục tiêu

Bổ sung khả năng quản lý execution state theo từng phiên giao dịch cho intrabar engine, phục vụ các alpha như:

* Initial Balance / Opening Range Breakout;
* VWAP intraday;
* session breakout;
* giới hạn số lệnh mỗi ngày;
* flat-only, no-reversal;
* EOD force-close;
* no-reentry-after-stop.

Đây phải là **phần mở rộng opt-in**, không thay đổi contract, execution semantics, kết quả hay hiệu năng của các alpha intrabar hiện tại.

---

## 2. Nguyên tắc tương thích ngược

API mới:

```python
session_policy: SessionExecutionPolicy | None = None
session_tape: IntrabarSessionTape | None = None
```

Khi:

```python
session_policy is None
```

QuantBT phải:

* sử dụng nguyên kernel hiện tại;
* giữ nguyên reversal, fill, SL/TP, trailing và reporting semantics;
* không thêm branch session vào hot loop cũ;
* cho kết quả bit-for-bit giống trước nâng cấp.

Session feature chỉ hoạt động khi người dùng chủ động truyền cả `session_policy` và `session_tape`.

---

## 3. Tách đúng trách nhiệm

### `ExecutionContract`

Tiếp tục quản lý:

* signal timing;
* next-open execution;
* same-bar SL/TP;
* gap fill;
* trailing phase;
* close-on-last-bar.

Không thay đổi cấu trúc hiện tại.

### `SessionExecutionPolicy`

Quản lý:

* entry có được phép khi đang có position hay không;
* quota entry theo session;
* reset counters;
* pending intent qua session boundary;
* EOD force-flat;
* re-entry sau protective exit.

### `IntrabarSessionTape`

Cung cấp dữ liệu session đã được chuẩn hóa thành arrays, không để Numba kernel tự xử lý datetime hoặc timezone.

---

## 4. Cấu hình mới

```python
from dataclasses import dataclass
from enum import Enum


class EntryPositionPolicy(str, Enum):
    CURRENT_BEHAVIOR = "current_behavior"
    FLAT_ONLY = "flat_only"
    REVERSE = "reverse"


class SessionCounterBasis(str, Enum):
    FILLED_ENTRY = "filled_entry"
    ACCEPTED_ENTRY = "accepted_entry"


class ProtectiveExitReentryPolicy(str, Enum):
    ALLOW = "allow"
    SUPPRESS_SIGNAL_BAR = "suppress_signal_bar"


@dataclass(frozen=True)
class SessionExecutionPolicy:
    entry_position_policy: EntryPositionPolicy = (
        EntryPositionPolicy.CURRENT_BEHAVIOR
    )

    max_long_entries_per_session: int | None = None
    max_short_entries_per_session: int | None = None

    counter_basis: SessionCounterBasis = (
        SessionCounterBasis.FILLED_ENTRY
    )

    cancel_pending_on_session_change: bool = True
    suppress_entry_on_force_flat_bar: bool = True

    protective_exit_reentry_policy: (
        ProtectiveExitReentryPolicy
    ) = ProtectiveExitReentryPolicy.ALLOW
```

Default values phải phản ánh behavior hiện tại để không phá backward compatibility.

---

## 5. Session tape

```python
@dataclass(frozen=True)
class IntrabarSessionTape:
    session_id: np.ndarray
    entry_allowed_at_open: np.ndarray
    force_flat_at_open: np.ndarray
```

Ý nghĩa:

| Field                      | Ý nghĩa                         |
| -------------------------- | ------------------------------- |
| `session_id[t]`            | Session chứa bar `t`            |
| `entry_allowed_at_open[t]` | Có được fill entry tại open `t` |
| `force_flat_at_open[t]`    | Phải đóng position tại open `t` |

Helper đề xuất:

```python
session_tape = IntrabarSessionTape.from_index(
    data.index,
    timezone="Asia/Ho_Chi_Minh",
    session_key="local_date",
    entry_windows=(
        ("08:45", "11:30"),
        ("13:00", "14:20"),
    ),
    force_flat_time="14:20",
)
```

Datetime, timezone, lunch break và session calendar phải được xử lý trước khi vào kernel.

---

## 6. State bổ sung trong session kernel

```text
current_session_id
long_entry_count
short_entry_count
protective_exit_on_previous_bar
```

Khi `session_id` thay đổi:

```text
reset long/short counters
clear protective-exit suppression
cancel stale pending intent nếu policy yêu cầu
```

Không tự đóng position khi đổi session, trừ khi `force_flat_at_open=True`.

---

## 7. Execution order trong mỗi bar

Session kernel phải xử lý theo thứ tự:

```text
1. Mark position/account đến current open
2. Detect session boundary và reset state
3. Force-flat tại open nếu được yêu cầu
4. Xử lý technical exit
5. Kiểm tra entry eligibility
6. Fill entry và tăng session counter
7. Dựng bracket từ actual fill
8. Quét intrabar SL/TP/liquidation
9. Cập nhật trailing cho bar kế tiếp
```

Entry chỉ được chấp nhận khi:

```text
entry window cho phép
signal không đến từ session cũ
chưa đạt quota
position policy cho phép
không phải force-flat bar
không bị re-entry suppression
quantity hợp lệ và đủ margin
```

Entry bị chặn phải được ghi audit reason, không silent-ignore.

---

## 8. Flat-only và quota

### Flat-only

```python
entry_position_policy=EntryPositionPolicy.FLAT_ONLY
```

Semantics:

```text
position != 0
→ bỏ qua mọi entry pulse
→ không pyramiding
→ không implicit reversal
```

Technical exit, SL, TP và EOD exit vẫn hoạt động bình thường.

### Session quota

```python
max_long_entries_per_session=3
max_short_entries_per_session=1
```

Mặc định counter tăng khi entry thực sự fill:

```text
signal bị block/reject → không tăng
margin reject → không tăng
quantity dưới minimum → không tăng
entry fill rồi SL cùng bar → vẫn tăng
```

---

## 9. Re-entry suppression

Policy:

```python
protective_exit_reentry_policy=(
    ProtectiveExitReentryPolicy
    .SUPPRESS_SIGNAL_BAR
)
```

Ví dụ:

```text
bar t:
    position bị SL
    close[t] đồng thời tạo entry signal mới

open t+1:
    signal đó bị bỏ qua
```

Default phải là `ALLOW` để không thay đổi behavior của alpha cũ.

---

## 10. API tích hợp

```python
bt = QuantBTEndpoint.intrabar_bracket(
    execution_contract=execution_contract,
    session_policy=session_policy,
    level_mode=IntrabarLevelMode.PRICE_DISTANCE,
    ...
)
```

Prepared runner:

```python
runner = bt.prepare_intrabar(
    data=data,
    symbols=[symbol],
    session_tape=session_tape,
)
```

Backtest thông thường:

```python
result = bt.backtest(
    data=alpha_df,
    signal_col="entry_signal",
    intent_cols=INTRABAR_INTENT_COLS,
    session_tape=session_tape,
    symbols=[symbol],
)
```

`session_policy` và session-tape signature phải nằm trong prepared-context signature để không reuse nhầm runner.

---

## 11. Kernel architecture

Không sửa trực tiếp hot loop hiện tại bằng nhiều điều kiện:

```python
if session_enabled:
    ...
```

trên từng bar.

Nên giữ hai execution paths:

```text
run_intrabar_kernel_existing
run_intrabar_session_kernel
```

Dispatch một lần trước khi chạy:

```python
if session_policy is None:
    return run_intrabar_kernel_existing(...)
else:
    return run_intrabar_session_kernel(...)
```

Điều này bảo vệ:

* hiệu năng hiện tại;
* regression safety;
* khả năng benchmark riêng;
* code readability.

---

## 12. Audit events mới

Bổ sung event flags hoặc structured suppression records:

```text
SESSION_RESET
SESSION_FORCED_EXIT
ENTRY_WINDOW_BLOCKED
ENTRY_QUOTA_BLOCKED
FLAT_ONLY_BLOCKED
STALE_SESSION_SIGNAL
PROTECTIVE_REENTRY_BLOCKED
```

Metadata tổng hợp:

```text
session_reset_count
session_forced_exit_count
entry_window_blocked_count
long_quota_blocked_count
short_quota_blocked_count
flat_only_blocked_count
stale_session_signal_count
reentry_suppressed_count
```

---

## 13. Triển khai theo hai phase

### Phase A — Reference correctness

* Thêm enums và `SessionExecutionPolicy`.
* Thêm `IntrabarSessionTape`.
* Mở rộng endpoint và prepared runner bằng optional arguments.
* Implement session behavior trong reference engine.
* Thêm audit events và metadata.
* Viết regression và trace tests.
* Xác nhận `session_policy=None` cho kết quả giống tuyệt đối trước update.

### Phase B — Fast prepared kernel

* Compile policy thành integer codes.
* Tạo session-specific Numba kernel.
* Differential-test với reference engine.
* Benchmark prepared optimization.
* Xác nhận fills, equity, counters và audit events giống reference.
* Không thay đổi existing fast kernel.

---

## 14. Tests bắt buộc

```text
session_policy=None
→ golden output cũ không thay đổi

session change
→ counters reset

signal cuối session
→ không fill tại session mới

flat-only
→ opposite signal không reversal

max long entries = 3
→ long entry thứ tư bị block

margin/order reject
→ counter không tăng

entry fill rồi SL cùng bar
→ counter vẫn tăng

force-flat bar
→ đóng position và không mở entry mới

protective exit tại bar t
→ signal của bar t bị suppress tại t+1 khi policy bật

reference session engine
→ giống fast session kernel
```

---

## 15. Scope của phiên bản đầu

Session extension v1 chỉ nên hỗ trợ các primitive có tính tái sử dụng cao:

```text
session reset
time-based entry mask
EOD force-flat
flat-only/reversal policy
entry quota
stale-signal cancellation
re-entry suppression
```

Không thêm arbitrary callbacks hoặc custom mutable user state vào fast intrabar kernel.

Alpha cần logic đặc thù như:

```text
daily realized-loss lock
consecutive-loss machine
trade từng level riêng biệt
dynamic state phụ thuộc custom fills
```

tiếp tục sử dụng `native_event`.

---

## 16. Acceptance statement

> QuantBT bổ sung optional session-aware intrabar execution bằng `SessionExecutionPolicy` và `IntrabarSessionTape`. Existing intrabar path, API semantics, results và performance được giữ nguyên khi session feature không được bật. Session-aware alpha có thêm flat-only policy, per-session entry quota, entry windows, EOD force-flat, stale-intent cancellation và protective-exit re-entry suppression, với reference oracle, audit trail và fast-kernel parity đầy đủ.
