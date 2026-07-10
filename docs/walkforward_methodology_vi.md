# Walk-Forward Optimization Methodology

Tài liệu này giải thích methodology hiện tại của Walk-Forward Optimization
(WFO) trong QuantBT.

Mục tiêu của WFO không phải là tìm bộ tham số có backtest đẹp nhất.

Mục tiêu là chọn tham số theo một quy trình có thể tin hơn:

- chống overfit;
- giảm look-ahead bias;
- tách rõ train và test;
- có metadata để audit;
- chạy final backtest bằng engine thật;
- dùng được cho nhiều nhóm alpha.

Trong QuantBT, WFO là một lớp research protocol.

Nó không thay thế engine khớp lệnh, fee, slippage, margin, funding hay
liquidation.

Nó chỉ trả lời câu hỏi:

```text
Tham số nào có khả năng generalize tốt hơn khi đi qua nhiều giai đoạn thị trường?
```

Sau khi WFO tạo ra OOS signal/position, QuantBT stitch toàn bộ OOS thành một
timeline liên tục rồi chạy một backtest cuối cùng.

Điểm này rất quan trọng.

Nếu mỗi fold tự tính equity rồi lấy trung bình, kết quả dễ sai vì:

- fee ở ranh giới fold bị bỏ qua;
- position bị reset giả tạo;
- funding không nối tiếp;
- margin không nối tiếp;
- exposure thực tế bị đứt đoạn.

QuantBT tránh lỗi đó bằng cách để final endpoint xử lý accounting thật.

---

## 1. Bài Toán Chính

Trong research trading, chọn tham số là một nguồn overfit rất lớn.

Ví dụ:

```text
thử 500 bộ params
chọn bộ Sharpe cao nhất
báo cáo kết quả trên cùng lịch sử
```

Kết quả như vậy thường là curve fitting.

Nó đo khả năng khớp quá khứ, không đo khả năng sống trong tương lai.

Nếu dùng Optuna, rủi ro còn lớn hơn.

Optuna học từ kết quả trial trước.

Nếu objective của từng trial có dùng OOS, thì Optuna gián tiếp học OOS.

Khi đó OOS không còn độc lập.

Đây là look-ahead bias dạng quy trình.

Nó không phải lỗi dùng giá tương lai trực tiếp.

Nó là lỗi dùng OOS như leaderboard để tối ưu nhiều lần.

QuantBT WFO được thiết kế để giảm bias này.

---

## 2. Flow Tổng Quát

Flow hiện tại:

```text
raw data
  -> normalize datetime index
  -> build chronological folds
  -> train/IS nằm trước test/OOS
  -> optimize params trên IS hoặc synthetic IS
  -> freeze candidate set
  -> evaluate candidate đã freeze trên OOS
  -> chọn params robust
  -> gọi strategy theo từng fold
  -> stitch OOS outputs
  -> chạy final QuantBT backtest
  -> lưu metrics + metadata audit
```

Invariant cốt lõi:

```text
max(train_index) < min(test_index)
```

Nếu invariant này sai, WFO mất ý nghĩa.

QuantBT cũng align data đưa vào strategy theo UTC fold index.

Điều này tránh lỗi phổ biến:

```text
data index tz-naive
fold index UTC
series.reindex(test_index) -> toàn NaN
```

Lỗi này rất nguy hiểm vì có thể tạo ra OOS all-zero mà không báo lỗi.

---

## 3. Split Frequency

QuantBT hỗ trợ:

- `yearly`;
- `semi_yearly`;
- `quarterly`;
- `monthly`;
- `weekly`.

Split dài phù hợp alpha chậm.

Split ngắn phù hợp alpha intraday hoặc short-horizon.

Nhưng split càng ngắn thì mỗi fold càng ít dữ liệu.

Vì vậy cần dùng:

- `min_train_bars`;
- `min_test_bars`.

Một fold quá ít bar không có ý nghĩa thống kê.

WFO tốt không chỉ là chia được fold.

WFO tốt là chia fold sao cho metric vẫn meaningful.

---

## 4. Strategy Contract

Strategy nhận:

```python
def strategy(data, params, train_index, test_index, fold):
    return oos_signal_or_positions
```

Strategy chỉ nên fit hoặc tính tham số dựa trên `train_index`.

Strategy phải trả về output cho `test_index`.

Output có thể là:

- `pd.Series` cho single-symbol;
- `pd.DataFrame` cho portfolio;
- `{symbol: pd.Series}` cho multi-symbol.

WFO sau đó slice output đúng OOS window.

Các timestamp thiếu phải được phát hiện sớm.

Silent missing data là một nguồn sai backtest rất lớn.

---

## 5. Two-Stage Selection

Điểm quan trọng nhất của methodology là two-stage selection.

Stage 1:

```text
Optuna chỉ nhìn IS hoặc synthetic IS.
```

Stage 2:

```text
Chỉ candidate đã freeze mới được đo OOS.
```

Lý do:

Nếu optimizer nhìn OOS ở từng trial, OOS sẽ bị tối ưu hóa gián tiếp.

QuantBT tránh bằng cách:

- `trial_table` ghi lại search IS;
- `candidate_table` ghi lại candidate được phép nhìn OOS;
- `best_trial` ghi lại params cuối;
- `oos_seen_by_optuna=false` để audit anti-leakage.

Đây là điểm đưa methodology lên mức nghiêm túc hơn backtest retail thông thường.

---

## 6. Công Thức Decay

Decay đo mức suy giảm từ IS sang OOS:

```text
decay = IS_sharpe - OOS_sharpe
```

Nếu decay lớn, params có thể đã overfit IS.

Nếu decay không ổn định giữa các fold, params phụ thuộc regime quá mạnh.

Ranking candidate mặc định:

```text
score = mean_oos_sharpe
        - lambda * std(IS_sharpe - OOS_sharpe)
        - gamma * max(0, mean(IS_sharpe - OOS_sharpe))
```

Ý nghĩa:

```text
mean_oos_sharpe
```

Đo performance OOS trung bình.

```text
std(IS - OOS)
```

Phạt decay không ổn định giữa các fold.

```text
max(0, mean_decay)
```

Chỉ phạt decay dương.

Nếu OOS tốt hơn IS, thành phần này không phạt.

`lambda` kiểm soát penalty cho instability.

`gamma` kiểm soát penalty cho degradation trung bình.

Đây là chọn params theo robust generalization, không chỉ chọn Sharpe cao nhất.

---

## 7. Mode 1: `mode_1_decay`

Mode 1 là baseline robust selection.

Stage 1 objective:

```text
objective_IS = mean(IS_sharpe_after_penalties)
```

Optuna chỉ optimize IS.

Sau đó QuantBT lấy top candidates bằng:

- `top_is_fraction`;
- `top_is_k`.

Ví dụ:

```text
top_is_fraction = 0.10
```

nghĩa là chỉ top 10% trial IS được vào Stage 2.

Stage 2 mới evaluate OOS.

Mode này phù hợp khi:

- cần baseline nhanh;
- muốn giảm leak;
- param space không quá nhiều sharp peak;
- cần một quy trình dễ giải thích.

Mode 1 trả lời:

```text
Params nào học tốt trên IS và decay ít khi sang OOS?
```

---

## 8. Mode 2: `mode_2_sbb`

Mode 2 là robustness simulation.

Nó vẫn dùng public mode là `mode_2_sbb`, nhưng bên trong có nhiều simulation:

- `stationary`;
- `regime`;
- `stress`;
- `garch`.

Stage 1 objective:

```text
synthetic = simulate(IS_return_proxy)

objective = mean(synthetic_sharpe)
            - sbb_decay_lambda * max(0, IS_sharpe - mean(synthetic_sharpe))
            - sbb_std_penalty * std(synthetic_sharpe)
```

Ý nghĩa:

```text
Nếu IS bị resample, stress hoặc simulate thành nhiều path khác,
params này còn giữ được performance không?
```

Mode 2 vẫn không optimize trực tiếp trên OOS thật.

Nó dùng synthetic IS như một bài kiểm tra robustness trước khi OOS được mở.

---

## 9. Stationary Bootstrap

`sbb_simulation="stationary"` là default.

Nó lấy mẫu block từ IS returns.

Khác với shuffle từng bar, block bootstrap giữ lại một phần sequence structure.

Công thức xác suất restart block:

```text
p = 1 / block_length
```

Mỗi bước:

- với xác suất `p`, bắt đầu block mới;
- nếu không, lấy điểm kế tiếp trong block.

Ưu điểm:

- không giả định normal distribution;
- giữ một phần autocorrelation;
- nhanh;
- dễ kiểm tra;
- phù hợp numba.

---

## 10. Regime Bootstrap

`sbb_simulation="regime"` chia IS returns thành các volatility regime.

Ví dụ:

```text
0 = low volatility
1 = normal volatility
2 = high volatility
```

Sau đó bootstrap block theo regime.

Người dùng có thể stress trọng số:

```python
regime_weights = {"high": 0.7, "low": 0.3}
```

Ý nghĩa:

```text
Synthetic OOS chứa nhiều high-vol regime hơn lịch sử gốc.
```

Điều này kiểm tra alpha có quá phụ thuộc vào môi trường volatility thấp hay không.

---

## 11. Stress Simulation

`sbb_simulation="stress"` scale volatility:

```text
r_stress = mean(r) + (r - mean(r)) * stress_vol_multiplier
```

Nếu multiplier = 1:

```text
r_stress = r
```

Nếu multiplier = 2:

```text
deviation quanh mean tăng gấp đôi
```

Đây không phải forecast.

Đây là stress test.

Nó giúp tránh chọn params chỉ sống được trong thị trường quá êm.

---

## 12. GARCH Simulation

`sbb_simulation="garch"` fit GARCH(p, q) trên IS returns.

Công thức cơ bản:

```text
r_t = mu + epsilon_t
epsilon_t = sigma_t * z_t
sigma_t^2 = omega
          + alpha * epsilon_{t-1}^2
          + beta  * sigma_{t-1}^2
```

GARCH mô phỏng volatility clustering.

High-vol thường đi thành cụm.

Low-vol cũng thường đi thành cụm.

GARCH không default vì:

- chậm hơn bootstrap;
- cần đủ train bars;
- fit có thể unstable nếu sample quá ngắn.

Nó nên dùng khi alpha nhạy với volatility regime.

---

## 13. Mode 3: `mode_3_flat_minima`

Mode 3 giải quyết sharp-peak overfit.

Sharp peak là trường hợp:

```text
window = 17 -> Sharpe rất cao
window = 16 -> Sharpe thấp
window = 18 -> Sharpe thấp
```

Điểm như vậy thường là noise.

Flat minima tìm vùng tham số ổn định.

Flow:

- optimize IS;
- lấy top trials;
- chuẩn hóa param space;
- cluster bằng DBSCAN hoặc fallback numpy;
- chọn cluster dày;
- lấy medoid hoặc centroid snapped về grid;
- sau đó mới evaluate OOS.

Mode này phù hợp khi strategy nhạy với:

- window;
- threshold;
- z-score band;
- volatility filter;
- grid spacing.

Nó trả lời:

```text
Vùng params nào ổn định, không phải một điểm may mắn?
```

---

## 14. Trade-Frequency Penalty

Một bẫy phổ biến:

```text
alpha đánh rất ít
ăn may vài lệnh
Sharpe rất cao
```

Đây là sparse-trading overfit.

Penalty:

```text
required_trades = min_trades_per_year * years_in_fold
shortfall = max(0, required_trades - actual_trades)
penalty = trade_penalty_factor * shortfall / required_trades
```

Penalty này optional.

Nó không cấm alpha ít lệnh.

Nó chỉ giúp optimizer không chọn params gần như không giao dịch chỉ vì Sharpe đẹp.

---

## 15. Level Trên Thị Trường

Methodology này cao hơn backtest retail thông thường.

Retail thường:

- optimize toàn lịch sử;
- chọn best Sharpe;
- ít metadata;
- không chống OOS leakage;
- không stitch OOS để accounting thật.

QuantBT WFO hiện tại thuộc mức:

```text
research-grade đến pre-production institutional
```

Lý do:

- có chronological folds;
- có anti-leakage two-stage selection;
- có robust decay objective;
- có bootstrap/stress/GARCH simulation;
- có flat-minima selection;
- có metadata audit;
- có final endpoint backtest thật;
- có seed/config/data hash để reproducibility.

Nó chưa phải guarantee live performance.

Vẫn cần:

- paper trading;
- live shadow validation;
- data quality audit;
- exchange microstructure validation;
- latency/slippage validation;
- strategy-specific review.

Nhưng về methodology chọn params, đây là nền tảng nghiêm túc.

Nó phù hợp để dùng làm shared research engine cho nhiều alpha.

---

## 16. Kết Luận

QuantBT WFO không hỏi:

```text
Params nào đẹp nhất trên quá khứ?
```

Nó hỏi:

```text
Params nào học tốt trên IS,
decay ít trên OOS,
ổn định qua nhiều fold,
và còn sống được dưới synthetic/stress scenarios?
```

Đây là hướng chọn params conservative.

Nó có thể bỏ qua một vài backtest rất đẹp.

Nhưng nó giảm xác suất chọn nhầm params do noise.

Trong quant research, đó là trade-off đúng.

Backtest đáng tin không phải backtest có Sharpe cao nhất.

Backtest đáng tin là backtest có quy trình chọn params minh bạch, ít leak,
có robustness check, và có thể audit lại.

