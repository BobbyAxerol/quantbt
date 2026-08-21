# QuantBT Portfolio Backtest — Correctness & Performance Fix Plan

## Phạm vi và contract

- Giữ kiến trúc **portfolio vectorized / close-to-close** hiện tại.
- **Không thay đổi, thay thế hoặc đổi tên endpoint portfolio hiện tại**, vì nhiều alpha đang phụ thuộc vào API này.
- Mọi sửa đổi phải ưu tiên **backward compatibility**: giữ nguyên signature, tham số mặc định, kiểu dữ liệu đầu vào/đầu ra và behavior hợp lệ hiện có.
- Nếu cần capability mới, ưu tiên bổ sung nội bộ, thêm optional parameter có default tương thích, hoặc thêm endpoint/version mới; không ép các alpha cũ migrate ngay.
- **Chưa triển khai intrabar portfolio**.
- Alpha phải tự tạo target position **causal** và align đúng thời điểm thực thi.
- Portfolio engine **không tự shift signal** và không tự suy đoán execution lag.
- Engine chỉ chịu trách nhiệm:
  - áp dụng target position đúng;
  - accounting PnL, fee, funding, margin đúng;
  - khớp rebalance theo contract;
  - report/audit đúng;
  - giữ deterministic parity giữa các backend/kernel.

> Nếu alpha dùng dữ liệu của close `t`, alpha phải tự quyết định target đó có hiệu lực từ `t+1` hay theo một contract MOC riêng. Đây là trách nhiệm của alpha, không phải kernel tự sửa ngầm.

---

## P0 — Blocker phải sửa trước khi tin kết quả Long/Short

### 1. Turnover sai khi đảo chiều vị thế

**Vấn đề**

Turnover đang có thể dựa trên chênh lệch absolute notional:

```python
abs(abs(target_position) - abs(current_position))
```

Khi đảo từ `+1` sang `-1`, turnover có thể bị ghi bằng `0`, dù thực tế đã giao dịch `2 units`.

**Sửa**

Dùng traded delta:

```python
traded_qty = abs(target_position - current_position)

turnover_notional = (
    traded_qty
    * execution_price
    * contract_size
)
```

Áp dụng thống nhất cho:

- fixed-target portfolio kernel;
- equity-sizing portfolio kernel;
- per-symbol turnover;
- total portfolio turnover;
- audit reconciliation.

**Test bắt buộc**

- `0 → +1`
- `+1 → 0`
- `+1 → -1`
- `-1 → +1`
- multi-symbol rebalance có Long và Short cùng lúc.

---

### 2. Portfolio backend chưa áp dụng slippage

**Vấn đề**

Portfolio rebalance đang dùng giá close và fee, nhưng `ExecutionConfig.slippage_bps` chưa được phản ánh đầy đủ vào execution price/cost.

Điều này làm strategy turnover cao, đặc biệt Long/Short ranking và reversal, có kết quả quá lạc quan.

**Sửa**

Tại mỗi rebalance:

```python
delta = target_position - current_position
```

- `delta > 0`: mua tại giá bất lợi hơn.
- `delta < 0`: bán tại giá bất lợi hơn.

Ví dụ:

```python
slippage_rate = slippage_bps / 10_000.0

buy_price = close * (1.0 + slippage_rate)
sell_price = close * (1.0 - slippage_rate)
```

Tách rõ:

- execution price;
- slippage cost;
- fee cost;
- traded notional.

Không thay đổi target position hoặc position path, chỉ thay đổi cash/equity accounting.

**Test bắt buộc**

- `slippage_bps=0` phải parity tuyệt đối với kernel cũ.
- Slippage dương luôn không cải thiện equity.
- Long entry, Long exit, Short entry, Short cover và reversal đều đúng dấu.

---

### 3. Buying-power gate chưa xét đầy đủ fee/slippage khi rebalance

**Vấn đề**

Nếu gross exposure không tăng, ví dụ đảo `+1 → -1`, initial margin trước và sau có thể bằng nhau nhưng traded delta, fee và slippage rất lớn.

Gate hiện có thể chấp nhận trade rồi mới phát hiện equity không đủ sau khi trừ chi phí.

**Sửa**

Gate phải đánh giá trạng thái sau giao dịch:

```text
post_trade_equity
= current_equity
- fee
- slippage_cost
```

Sau đó kiểm tra:

```text
post_trade_equity >= target_initial_margin
```

và:

```text
post_trade_equity >= target_maintenance_margin
```

Không chỉ kiểm tra khi target initial margin tăng.

**Chính sách**

Giữ atomic rebalance hiện tại:

- đủ buying power: accept toàn bộ target;
- không đủ: reject target theo policy hiện có.

Chưa cần partial fill/rebalance.

---

### 4. Execution/accounting phải dùng cùng một traded delta

**Vấn đề**

Fee, turnover, slippage và rebalance report có thể đang tính từ các biểu thức khác nhau, dẫn đến report không reconcile.

**Sửa**

Tạo một canonical rebalance delta:

```python
delta_qty = accepted_target_qty - previous_qty
```

Mọi accounting phải bắt nguồn từ delta này:

```text
traded quantity
traded notional
fee
slippage
turnover
cash impact
rebalance report
```

**Invariant bắt buộc**

```text
sum(symbol traded notional)
= portfolio turnover notional
```

và:

```text
gross PnL
- fees
- slippage
- funding
- liquidation costs
= net equity change
```

trong sai số số học cho phép.

---

## P1 — Cần sửa để module portfolio trustable

### 1. Bỏ look-ahead trong Risk Parity warm-up

**Vấn đề**

Rolling volatility không được phép dùng `bfill()` từ giá trị tương lai để lấp các bar đầu.

**Sửa**

- Không tạo position trước khi đủ warm-up; hoặc
- dùng causal expanding estimate có `min_periods` rõ ràng.

Trong warm-up:

```text
target position = 0
```

Không backward-fill volatility.

---

### 2. Không fill leading missing price bằng `0`

**Vấn đề**

Symbol chưa niêm yết hoặc chưa có dữ liệu đầu kỳ có thể bị biến thành giá `0`, gây sai notional, return, sizing và margin.

**Sửa**

Tạo explicit masks:

```text
price_valid
tradable
stale_bar_count
```

Quy tắc:

- leading missing: không tradable, position target phải bằng `0`;
- missing ngắn trong thời gian đang giữ: có thể mark bằng last valid price theo policy;
- không cho mở/rebalance trên stale price;
- quá `max_stale_bars`: force policy rõ ràng hoặc reject dataset.

---

### 3. Thêm tradability mask cho từng symbol/bar

**Vấn đề**

Forward-filled price có thể khiến engine rebalance trên tài sản không giao dịch.

**Sửa**

Prepared portfolio data nên chứa:

```python
tradable[symbol, bar]
```

Rebalance chỉ được phép khi:

```text
tradable == True
```

Nếu không tradable:

- giữ position cũ;
- không phát sinh traded notional;
- ghi rejection reason rõ ràng.

---

### 4. Thống nhất semantics của `market_neutral`

**Vấn đề**

Behavior có thể khác giữa fixed-target và equity-sizing route khi chỉ có một phía Long hoặc Short.

**Sửa**

Chọn một contract duy nhất:

```text
Nếu thiếu một phía:
- zero toàn bộ portfolio; hoặc
- reject rebalance; hoặc
- giữ position trước.
```

Khuyến nghị:

```text
reject rebalance + giữ accepted positions trước
```

để tránh engine tự tạo directional exposure ngoài ý alpha.

Long/Short mode thuần không cần tự neutralize.

---

### 5. Chuẩn hóa fee contract

**Vấn đề**

`fee`, `fee_rate` và round-trip/one-way convention dễ bị dùng nhầm giữa portfolio và endpoint V2 khác.

**Sửa**

Canonical:

```text
fee_rate = one-way execution fee
```

Legacy:

```text
fee = round-trip fee, deprecated
```

Metadata/report phải lưu:

```text
input fee convention
canonical one-way fee rate
```

---

### 6. Mở rộng portfolio audit

Audit cần kiểm tra thêm:

- turnover từ `abs(delta_qty)`;
- fee reconciliation;
- slippage reconciliation;
- funding reconciliation;
- rejected rebalance count và reason;
- target position so với accepted position;
- gross/net exposure;
- final equity identity;
- per-symbol PnL cộng lại bằng portfolio PnL.

---

## P2 — Cải thiện sau khi P0/P1 ổn định

### 1. Làm rõ liquidation semantics

Giữ liquidation theo High/Low hiện tại, nhưng report rõ đây là:

```text
conservative bar-level cross-asset stress
```

Không gọi là exact intrabar path.

---

### 2. Structured rejection reasons

Mỗi rebalance bị từ chối cần có reason code:

```text
INSUFFICIENT_INITIAL_MARGIN
INSUFFICIENT_POST_COST_EQUITY
NON_TRADABLE
STALE_PRICE
INVALID_TARGET
MIN_QTY
MIN_NOTIONAL
QTY_STEP
```

---

### 3. Thêm strict validation mode

Cho phép:

```python
validation_mode="strict"
```

Strict mode reject:

- non-finite target;
- price bằng hoặc nhỏ hơn `0`;
- target trên non-tradable bar;
- leverage/contract size không hợp lệ;
- position matrix lệch index/symbol;
- stale price vượt giới hạn.

Fast mode có thể bỏ một số kiểm tra lặp lại sau khi prepared data đã được certify.

---

## Tăng tốc nhưng không thay đổi position path

Mục tiêu:

```text
same inputs
→ same accepted positions
→ same PnL/accounting
→ same reports trong tolerance
→ nhanh hơn
```

### 1. Prepared portfolio cache

Chuẩn bị một lần:

- aligned close/high/low arrays;
- funding arrays;
- contract sizes;
- leverage;
- fee/slippage rates;
- quantity constraints;
- tradability masks;
- target position matrix;
- symbol mapping;
- datetime mapping.

Optimization trials chỉ thay phần thật sự phụ thuộc params.

Không lặp lại:

- DataFrame alignment;
- timezone checks;
- dtype conversion;
- symbol reindex;
- array allocation lớn.

---

### 2. Tách preprocessing và simulation kernel

Kiến trúc:

```text
prepare_portfolio(...)
→ PreparedPortfolioData

simulate_portfolio_kernel(
    prepared,
    target_positions,
    account_params,
)
```

Prepared object phải immutable/certified bằng signature.

---

### 3. Numba contiguous arrays

Đảm bảo kernel nhận:

```python
np.ascontiguousarray(..., dtype=np.float64)
```

Dùng shape thống nhất:

```text
(n_bars, n_symbols)
```

Tránh transpose/copy trong mỗi trial.

---

### 4. Preallocate toàn bộ output arrays

Preallocate:

- positions;
- equity;
- cash;
- gross/net exposure;
- turnover;
- fees;
- slippage;
- funding;
- margin;
- rejection codes.

Không append Python list trong hot loop.

---

### 5. Fast report level

Trong optimization:

```python
report_level="minimal"
```

Chỉ giữ:

- equity;
- accepted positions nếu objective cần;
- essential metrics;
- compact diagnostics.

Không dựng DataFrame chi tiết hoặc per-bar string logs trong mỗi trial.

Best candidate mới rerun với:

```python
report_level="audit"
```

---

### 6. Incremental accounting

Trong hot loop, cập nhật từ bar trước:

```text
equity
cash
gross exposure
net exposure
initial margin
maintenance margin
```

Không recompute từ DataFrame hoặc object Python.

Với symbol không đổi position và giá không đổi, có thể skip các phép tính rebalance liên quan.

---

### 7. Sparse rebalance path

Portfolio alpha thường chỉ đổi target tại ngày rebalance.

Có thể chuẩn bị:

```python
rebalance_mask[bar]
```

Nếu `False`:

- chỉ MTM;
- funding;
- margin/liquidation check;
- không chạy sizing/rounding/rebalance loop.

Điều này không thay position path.

---

### 8. Skip unchanged symbols

Tại rebalance bar:

```python
delta_qty = target_qty - current_qty
```

Chỉ xử lý symbol có:

```python
abs(delta_qty) > tolerance
```

Không tính fee, slippage, quantity constraints cho symbol không đổi.

---

### 9. Compile kernels theo feature flags

Có thể có các kernel variants:

```text
no funding / funding
no slippage / slippage
simple constraints / full constraints
fixed target / equity sizing
```

Tránh branch không cần thiết trong inner loop.

Tất cả variants phải pass cùng parity suite.

---

### 10. Không dựng pandas trong trial loop

Optimization evaluator nên trả raw arrays/result object.

Chỉ convert sang:

- DataFrame;
- attribution tables;
- detailed reports;

sau khi chọn candidate.

---

## Parity và regression gates bắt buộc

Mọi thay đổi tốc độ phải pass:

### Position parity

```text
accepted positions mới
== accepted positions baseline
```

trừ khi test đang kiểm tra một bug accounting đã được sửa có chủ đích.

### Equity parity

Với:

```text
slippage = 0
fee không đổi
same targets
same tradability
```

kernel tối ưu phải parity với corrected reference kernel trong tolerance.

### Accounting identities

```text
turnover = sum(abs(delta_qty) * execution_price * contract_size)
```

```text
net equity change
= gross PnL
- fee
- slippage
- funding cost
- liquidation cost
```

### Long/Short scenarios

- Long only.
- Short only.
- Simultaneous Long/Short across symbols.
- Long to flat.
- Short to flat.
- Long to Short reversal.
- Short to Long reversal.
- Same gross exposure, different composition.
- Rebalance rejected because post-cost equity insufficient.
- Non-tradable symbol.
- Stale price.

### Performance benchmark

Benchmark riêng:

```text
bars × symbols
10k × 10
10k × 100
100k × 100
```

So sánh:

- preparation time;
- kernel time;
- report time;
- peak memory;
- optimization trial throughput.

Không chấp nhận tăng tốc nếu position/equity parity fail.

---

## Thứ tự implementation đề xuất

1. Sửa canonical `delta_qty` và turnover reversal.
2. Thêm slippage accounting.
3. Sửa post-cost buying-power gate.
4. Thêm accounting reconciliation tests.
5. Bỏ Risk Parity `bfill`.
6. Thêm valid/tradable/stale masks.
7. Thống nhất `market_neutral`.
8. Chuẩn hóa fee convention.
9. Tách prepared portfolio cache.
10. Tối ưu Numba, sparse rebalance và minimal reports.
11. Benchmark và parity certification.
