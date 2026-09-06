# Walk-Forward Optimization Methodology

Tài liệu này mô tả methodology hiện tại của Walk-Forward Optimization (WFO)
trong QuantBT dưới góc nhìn toán học, thống kê và quy trình chọn tham số.

Trọng tâm không phải là cách gọi API.

Trọng tâm là câu hỏi:

```text
Làm thế nào để chọn params ít overfit hơn,
có khả năng generalize hơn,
và vẫn đo được bằng backtest thực tế?
```

---

## 1. Vì Sao Cần WFO?

Trong trading research, một alpha thường có nhiều tham số:

- lookback window;
- threshold;
- volatility band;
- z-score entry/exit;
- grid spacing;
- stop/take profit;
- holding period;
- leverage/exposure scale;
- filter regime.

Nếu ta thử nhiều tổ hợp rồi chọn tổ hợp có Sharpe cao nhất trên toàn bộ lịch sử,
ta đang tối ưu vào noise.

Bài toán này có thể viết như:

```text
theta* = argmax_theta Score(D_all, theta)
```

Trong đó:

- `theta` là bộ tham số;
- `D_all` là toàn bộ dữ liệu lịch sử;
- `Score` là Sharpe, Calmar, CAGR, hoặc objective tùy chọn.

Cách này có vấn đề lớn:

```text
D_all vừa dùng để chọn theta, vừa dùng để đánh giá theta.
```

Kết quả không còn là kiểm định độc lập.

Nó là in-sample optimization.

Nếu số lượng trial càng lớn, xác suất tìm được một `theta` may mắn càng cao.

Đây là multiple testing problem.

WFO thay bài toán trên bằng:

```text
D = {D_train^1, D_test^1, ..., D_train^K, D_test^K}
```

Mỗi fold `k` có:

```text
D_train^k < D_test^k
```

Theo thứ tự thời gian.

Ta không chọn tham số chỉ vì nó đẹp trên toàn bộ quá khứ.

Ta chọn tham số vì nó:

- học được trên train;
- không suy giảm quá mạnh trên test;
- ổn định qua nhiều fold;
- sống được dưới bootstrap/stress/synthetic regimes;
- không phải một sharp peak trong param space.

---

## 2. Bản Chất Của Look-Ahead Bias Trong Optimization

Look-ahead bias không chỉ là dùng giá tương lai trong feature.

Một dạng tinh vi hơn là:

```text
optimizer nhìn OOS nhiều lần trong quá trình tìm params.
```

Ví dụ objective của Optuna là:

```text
Objective(theta) = Sharpe_OOS(theta)
```

Mỗi trial trả Sharpe OOS về sampler.

Sampler dùng lịch sử trial để chọn trial tiếp theo.

Khi đó sampler đã học cấu trúc OOS.

OOS biến thành validation leaderboard.

Về thống kê, OOS không còn độc lập với quá trình chọn model.

QuantBT WFO tránh điều này bằng nguyên tắc:

```text
Optuna trial objective không được dùng OOS thật.
```

OOS chỉ được mở sau khi Stage 1 đã đóng băng danh sách candidate.

Đây là quyết định methodology quan trọng nhất.

---

## 3. Two-Stage Selection

QuantBT dùng two-stage selection.

Stage 1:

```text
Tìm candidate bằng IS hoặc synthetic IS.
```

Stage 2:

```text
Chỉ đánh giá OOS trên candidate đã freeze.
```

Ký hiệu:

```text
Theta = không gian tham số
T(theta) = train-only objective
C = top candidates theo T(theta)
O(theta) = OOS evaluation objective
theta* = argmax_{theta in C} O(theta)
```

Điểm chính:

```text
C được tạo mà không nhìn OOS.
```

Do đó OOS chỉ ảnh hưởng ở bước chọn cuối trong một tập nhỏ hơn.

Điều này không xóa hoàn toàn data snooping.

Nhưng nó giảm đáng kể rủi ro optimizer học trực tiếp OOS.

### 3.1. Optimization Schedule Của Phase 49A

QuantBT tách objective khỏi lifecycle bằng `optimization_schedule`.

`global` là behavior cũ: một Optuna study chạy trên aggregate train folds và
chọn một params cuối cho toàn timeline. Cách này phù hợp khi mục tiêu là tìm
một bộ tham số global mang tính retrospective calibration.

`per_fold_decay` áp dụng cho `mode_1_decay`. Mỗi outer fold có study độc lập:

```text
all trials on fold IS
-> freeze top-IS candidates
-> evaluate those candidates on the same fold OOS
-> select by existing robust_decay objective
-> emit that fold OOS target
-> create a new study for the next fold
```

OOS không được Optuna sampler nhìn trực tiếp ở trial stage, nhưng nó vẫn được
dùng ở final candidate selection. Vì vậy đây là fold-local decay calibration,
không phải untouched OOS. Nó trả lời câu hỏi: “nếu hiệu chỉnh riêng trong từng
regime, candidate nào giữ edge tốt nhất sang đoạn kế tiếp?”

`per_fold_causal` áp dụng cho `mode_4_is_only_robust` hoặc `mode_1_decay` với
nested validation. Với mode 4, mỗi fold chọn params chỉ từ IS temporal/plateau
evidence, freeze params, rồi mới chạy outer OOS đúng một lần. OOS metric chỉ là
realized audit outcome và không thể thay đổi selected params của fold đó.

Với Mode 1 causal, outer fold \(D_i, T_i\) tạo thêm các inner folds nằm hoàn
toàn trong \(D_i\). `robust_decay` vẫn dùng chênh lệch IS/OOS nhưng OOS ở đây
chỉ là inner OOS thuộc lịch sử đã biết tại thời điểm chọn params. Sau khi chọn
\(\theta_i^\star\), QuantBT mới chạy đúng một lần trên outer \(T_i\). Vì vậy
outer OOS không tham gia Optuna hay candidate selector. Cần khai báo rõ
`inner_split_frequency`, `inner_window_mode`, `inner_train_window` và
`inner_min_folds`; nếu thiếu data để tạo đủ inner folds thì engine raise, không
fallback sang `per_fold_decay`.

Trong cả hai schedule, fold sau có thể dùng dữ liệu của fold trước vì tại thời
điểm lịch sử đó dữ liệu đã tồn tại. Điều bị cấm là fold hiện tại nhìn bars sau
`test_end`, hoặc một global study dùng future folds để sửa params của fold đã
hoàn tất.

QuantBT truyền strategy một data view kết thúc đúng tại `train_end` cho IS và
`test_end` cho OOS. Target của các fold được stitch trước khi account engine
chạy một lần. `fold_boundary_position_policy="carry"` vẫn là alias legacy cho
`fold_account_policy="carry_position"`: không reset equity, không tự flatten
và không nhân đôi fee tại retraining boundary.

Từ Phase 64, WFO có `CalendarPlanV2` và contract timing/lifecycle rõ ràng.
`exact_v2` reject tape lệch timestamp dù cùng số row; `intersection_v2` chỉ
dùng clock common có observation đầy đủ. Mỗi fold audit riêng `warmup`,
`label_horizon`, `purge`, `test` và `embargo`. `close_at_boundary` chỉ hợp lệ
khi embargo tạo gap flatten cụ thể; `reset_flat` và `replay_prior_state` raise
trên stitched-target endpoint thay vì bị đổi ngầm thành carry.

`intent_contract` ghi rõ output là signal/target/position, phase quan sát,
phase hiệu lực và trạng thái lag. `StrategyLifecycleV1` cô lập mutable object
theo run/candidate/fold/cutoff qua `spawn/reset` hoặc deepcopy. Những contract
này làm rõ giới hạn engine; feature/indicator bên trong strategy vẫn phải causal
ở mức intra-fold. Với `scoring_backend="proxy"`, proxy rank có thể được audit
IS-only qua Spearman, Top-K overlap, winner regret và false-positive rate với
native scorer; `enforce` sẽ fail-closed nếu gate không đạt.

Metadata cần đọc cùng nhau là `validation_claim`, `causality_claim` và
`chronological_validation_claim`. Field cuối tách riêng để `global` vẫn giữ
backward-compatible `validation_claim="walk_forward_oos"` nhưng không thể bị
diễn giải nhầm là strict chronological validation. Nested Mode 1 còn trả về
`inner_validation` và `inner_fold_table` để audit đúng vùng dữ liệu được phép
dùng trong selection.

### 3.2. Prepared Context Và Scalar Scoring Của Phase 49B

Phase 49B không thay objective hay phương pháp chọn params. Nó thay lifecycle
tính toán: index, fold cutoffs và market signature được chuẩn bị một lần trong
`PreparedWalkForwardContext`; mỗi trial dùng integer slice thay vì tạo lại mask
pandas. Với scoring qua endpoint, kernel accounting vẫn là kernel public nhưng
metrics được tính trực tiếp từ arrays bằng cùng `compute_performance_metrics`.
Sau đó equity/position paths của trial được giải phóng thay vì dựng report.

Trial ledger compact chỉ bỏ fold-level payload lặp lại sau khi selector đã hoàn
tất. `best_trial` vẫn giữ evidence đầy đủ; `trial_table`, `candidate_table`, seed,
objective và candidate order không đổi. Context chỉ sống trong một WFO run,
signature hash toàn bộ timestamp và cột dữ liệu, và QuantBT không cache output
indicator/signal của strategy. Do đó tối ưu này giảm framework overhead mà không
biến strategy thành black box hoặc tạo cache xuyên lần chạy.

---

## 4. Fold-Level Metrics

Với mỗi fold `k`, ta tính:

```text
S_IS^k(theta)
S_OOS^k(theta)
```

Trong đó `S` thường là Sharpe hoặc proxy score dựa trên return series.

Sharpe cơ bản:

```text
Sharpe = mean(r) / std(r) * sqrt(N)
```

`N` là số kỳ annualization:

- crypto thường dùng 365;
- equity daily thường dùng 252;
- intraday có thể cần quy ước riêng.

Với nhiều fold:

```text
Mean_IS(theta)  = mean_k S_IS^k(theta)
Mean_OOS(theta) = mean_k S_OOS^k(theta)
```

Decay từng fold:

```text
Decay^k(theta) = S_IS^k(theta) - S_OOS^k(theta)
```

Decay trung bình:

```text
Mean_Decay(theta) = mean_k Decay^k(theta)
```

Độ bất ổn decay:

```text
Std_Decay(theta) = std_k Decay^k(theta)
```

Một tham số tốt không chỉ có OOS cao.

Nó còn phải có decay thấp và ít dao động giữa fold.

---

## 5. Candidate Ranking Objective

Objective chọn candidate mặc định:

```text
Score(theta) =
    Mean_OOS(theta)
    - lambda * Std_Decay(theta)
    - gamma  * max(0, Mean_Decay(theta))
```

Ý nghĩa:

```text
Mean_OOS(theta)
```

Reward performance ngoài mẫu.

```text
Std_Decay(theta)
```

Phạt tham số có độ generalization không ổn định.

```text
max(0, Mean_Decay(theta))
```

Chỉ phạt nếu IS tốt hơn OOS.

Nếu OOS tốt hơn IS, không phạt decay trung bình.

`lambda` kiểm soát penalty cho instability.

`gamma` kiểm soát penalty cho overfit IS.

Về mặt phương pháp, đây là một robust model-selection objective.

Nó không chọn:

```text
theta có OOS cao nhất đơn thuần.
```

Nó chọn:

```text
theta có OOS tốt, decay thấp, decay ổn định.
```

---

## 6. Optuna Kernel Trong QuantBT WFO

Optuna là search engine.

Nó không phải methodology tự thân.

Trong QuantBT, Optuna được bọc bởi các guardrail:

- objective train-only;
- duplicate pruning;
- early stopping;
- seeded sampler;
- param range validation;
- candidate freeze;
- metadata audit.

Không gian tham số có thể gồm:

- integer range;
- float range;
- categorical choices;
- fixed values.

Một trial của Optuna:

```text
theta_i = sampler.suggest(...)
score_i = TrainObjective(theta_i)
```

Sampler học từ các cặp:

```text
(theta_i, score_i)
```

Vì `score_i` không dùng OOS thật, sampler không leak OOS.

Duplicate pruning loại các trial lặp lại cùng `theta`.

Early stopping dừng khi không còn cải thiện.

Mục tiêu là tiết kiệm compute mà không đổi bản chất thống kê.

---

## 7. Mode 1: `mode_1_decay`

Mode 1 là mode nền tảng nhất.

Nó dùng IS-only Optuna search.

Stage 1 objective:

```text
T_1(theta) = Mean_IS(theta) - Penalty_trade(theta)
```

Trong đó:

```text
Mean_IS(theta) = mean_k S_IS^k(theta)
```

`Penalty_trade` là optional.

Nó phạt các tham số gần như không giao dịch nhưng có Sharpe cao ảo.

Sau khi chạy Optuna, QuantBT lấy top candidates:

```text
C = TopK({theta_i}, key=T_1(theta_i))
```

`TopK` có thể được điều khiển bằng:

```text
top_is_fraction
top_is_k
```

Sau khi `C` được freeze, QuantBT mới tính:

```text
S_OOS^k(theta), theta in C
```

Candidate cuối được chọn bằng robust decay objective.

### Ý nghĩa của Mode 1

Mode 1 trả lời câu hỏi:

```text
Trong các params học tốt trên IS,
params nào suy giảm ít nhất và ổn định nhất trên OOS?
```

Nó phù hợp khi:

- cần baseline nhanh;
- số lượng params vừa phải;
- alpha không quá nhạy với sharp peak;
- muốn chống OOS leakage rõ ràng.

### Rủi ro còn lại

Mode 1 vẫn có thể chọn nhầm nếu:

- IS quá ngắn;
- OOS quá ít fold;
- regime shift quá mạnh;
- strategy feature tự leak tương lai;
- param space quá rộng.

Vì vậy Mode 1 là nền tảng, không phải điểm kết thúc.

---

## 8. Mode 2: `mode_2_sbb`

Mode 2 là robustness simulation mode.

Nó không hỏi:

```text
theta tốt nhất trên IS là gì?
```

Nó hỏi:

```text
Nếu IS bị resample, stress hoặc simulate,
theta còn giữ được edge không?
```

Stage 1 objective:

```text
Synthetic(theta) = {S_syn^1(theta), ..., S_syn^B(theta)}
```

Với `B = sbb_samples`.

Objective:

```text
T_2(theta) =
    mean(Synthetic(theta))
    - sbb_decay_lambda * max(0, S_IS(theta) - mean(Synthetic(theta)))
    - sbb_std_penalty  * std(Synthetic(theta))
```

Thành phần thứ nhất reward synthetic performance.

Thành phần thứ hai phạt nếu synthetic thấp hơn IS.

Thành phần thứ ba phạt synthetic instability.

Mode 2 vẫn train-only.

Synthetic samples được tạo từ IS return proxy.

OOS thật vẫn không được Optuna nhìn.

---

## 9. Mode 2 Kernel: Stationary Bootstrap

`sbb_simulation="stationary"` là default.

Nó tạo synthetic path bằng block bootstrap.

Cho chuỗi return IS:

```text
r_1, r_2, ..., r_T
```

Ta tạo index synthetic:

```text
i_1, i_2, ..., i_T
```

Tại mỗi bước:

```text
P(restart block) = p = 1 / block_length
```

Nếu restart:

```text
i_t ~ Uniform(1, T)
```

Nếu không restart:

```text
i_t = i_{t-1} + 1 mod T
```

Synthetic returns:

```text
r_syn_t = r_{i_t}
```

Ưu điểm:

- không giả định phân phối normal;
- giữ một phần autocorrelation;
- giữ một phần volatility clustering;
- nhanh;
- dễ kiểm định;
- phù hợp numba.

So với random shuffle từng bar, stationary bootstrap hợp lý hơn cho market data.

---

## 10. Mode 2 Kernel: Regime Bootstrap

`sbb_simulation="regime"` thêm điều kiện regime.

Trước hết, QuantBT gán nhãn regime cho IS returns.

Ví dụ 3 regime:

```text
0 = low volatility
1 = medium volatility
2 = high volatility
```

Regime được ước lượng từ trailing volatility proxy.

Sau đó bootstrap chỉ lấy block theo regime được chọn.

Người dùng có thể truyền:

```python
regime_weights = {"high": 0.7, "low": 0.3}
```

Nghĩa là synthetic path sẽ có nhiều high-vol block hơn.

Về mặt toán học, sampling distribution được đổi từ empirical distribution gốc:

```text
P(regime = j) = empirical_weight_j
```

sang distribution có chủ đích:

```text
P(regime = j) = user_weight_j
```

Ý nghĩa:

```text
Kiểm tra theta dưới OOS giả định có regime mix khác IS.
```

Đây là robustness test cho regime shift.

Nó không dự báo tương lai.

Nó kiểm tra tính chịu đựng của params.

---

## 11. Mode 2 Kernel: Stress Volatility

`sbb_simulation="stress"` scale volatility của IS returns.

Công thức:

```text
r_stress_t = mean(r) + (r_t - mean(r)) * m
```

Trong đó:

```text
m = stress_vol_multiplier
```

Nếu `m = 1`:

```text
r_stress_t = r_t
```

Nếu `m > 1`, volatility tăng.

Nếu `0 < m < 1`, volatility giảm.

Stress kernel thường dùng với `m > 1`.

Ý nghĩa:

- kiểm tra params khi biến động mạnh hơn;
- phạt params quá nhạy với calm market;
- giúp chọn cấu hình ít fragile hơn.

Đây là simple parametric stress.

Nó không mô hình hóa đầy đủ tail risk.

Nhưng nó rõ ràng, nhanh và dễ audit.

---

## 12. Mode 2 Kernel: GARCH Simulation

`sbb_simulation="garch"` dùng GARCH(p, q).

Mô hình cơ bản:

```text
r_t = mu + epsilon_t
epsilon_t = sigma_t * z_t
sigma_t^2 = omega
          + sum_i alpha_i * epsilon_{t-i}^2
          + sum_j beta_j  * sigma_{t-j}^2
```

GARCH mô phỏng volatility clustering.

Market returns thường có đặc điểm:

- volatility cao đi thành cụm;
- volatility thấp đi thành cụm;
- shock lớn ảnh hưởng đến variance tương lai.

GARCH kernel phù hợp khi:

- alpha nhạy với volatility;
- cần synthetic path có volatility dynamics;
- muốn kiểm tra under clustered risk.

Nó không default vì:

- fit chậm hơn bootstrap;
- cần nhiều train bars;
- parameter estimation có thể unstable;
- dễ tạo cảm giác chính xác giả nếu sample ngắn.

Do đó GARCH trong QuantBT là optional robustness kernel, không phải oracle.

---

## 13. Mode 3: `mode_3_flat_minima`

Mode 3 giải quyết sharp-peak overfit.

Một param peak đáng nghi:

```text
theta = 17  -> Sharpe 3.0
theta = 16  -> Sharpe 0.2
theta = 18  -> Sharpe -0.1
```

Nếu một điểm rất tốt nhưng lân cận rất xấu, khả năng cao đó là noise.

Flat-minima methodology tìm vùng ổn định hơn.

Stage 1 vẫn là IS-only search.

Sau đó QuantBT lấy top trials và đưa vào normalized param space.

Với mỗi param:

```text
x_norm = (x - low) / (high - low)
```

Categorical/fixed param được xử lý theo representation phù hợp.

Sau đó clustering bằng DBSCAN hoặc fallback density clustering.

Mục tiêu:

```text
tìm cụm top trials dày và ổn định
```

Candidate có thể là:

- medoid của cluster;
- centroid snapped về grid hợp lệ.

Sau đó candidate mới được evaluate OOS.

### Ý nghĩa toán học

Mode 3 thêm một prior hình học:

```text
robust params thường nằm trong plateau,
không nằm ở peak cô lập.
```

Nó không chỉ nhìn score.

Nó nhìn local geometry của param space.

Mode này rất hữu ích cho:

- moving average windows;
- threshold;
- z-score bands;
- grid spacing;
- stop/take profit levels;
- volatility filters.

---

## 14. Trade-Frequency Penalty

Một alpha có thể Sharpe cao vì nó gần như không giao dịch.

Ví dụ:

```text
3 lệnh trong 5 năm
2 lệnh thắng lớn
Sharpe rất đẹp
```

Đây là sparse-trading overfit.

QuantBT có optional penalty:

```text
required_trades = min_trades_per_year * years_in_fold
shortfall = max(0, required_trades - actual_trades)
penalty = trade_penalty_factor * shortfall / required_trades
```

Score sau penalty:

```text
S_adjusted = S_raw - penalty
```

Ý nghĩa:

- không cấm alpha ít lệnh;
- chỉ phạt nếu ít hơn mức kỳ vọng;
- giúp optimizer không chọn params flat/near-flat.

Đây là một regularization term.

Nó giống tư duy model complexity penalty trong machine learning.

---

## 15. Vì Sao Đây Là Methodology Cấp Cao Hơn Retail?

Backtest retail thường:

- optimize toàn lịch sử;
- chọn best Sharpe;
- không tách rõ IS/OOS;
- không kiểm decay;
- không audit candidate;
- không stress path;
- không kiểm flat-minima;
- không stitch OOS để chạy accounting thật.

QuantBT WFO hiện tại có:

- chronological folds;
- strict train-before-test;
- Optuna train-only objective;
- two-stage candidate selection;
- robust decay scoring;
- bootstrap/stress/GARCH synthetic kernels;
- flat-minima geometry;
- trade-frequency regularization;
- metadata audit;
- final endpoint backtest.

Vì vậy level methodology nằm ở:

```text
research-grade đến pre-production institutional
```

Nó chưa phải full institutional live stack.

Một full stack còn cần:

- independent validation set;
- paper trading;
- live shadow;
- exchange microstructure;
- latency model;
- liquidity/market impact;
- borrow/funding constraints;
- data quality audit;
- survivorship/delisting handling.

Nhưng riêng bài toán chọn params, QuantBT WFO đã vượt xa kiểu optimize đẹp số.

---

## 16. Khi Nào Dùng Mode Nào?

Dùng `mode_1_decay` khi:

- cần baseline robust;
- cần tốc độ;
- muốn chống leak rõ ràng;
- param space không quá gồ ghề.

Dùng `mode_2_sbb` khi:

- muốn stress robustness;
- OOS thật ít;
- alpha nhạy volatility;
- cần kiểm path dependence.

Dùng `mode_3_flat_minima` khi:

- param space có nhiều peak;
- strategy nhạy window/threshold;
- muốn chọn plateau thay vì điểm may mắn.

Workflow gợi ý:

```text
1. mode_1_decay để tìm baseline
2. mode_3_flat_minima để kiểm plateau
3. mode_2_sbb để stress robustness
4. chạy final endpoint backtest
5. validate trên real/paper/live
```

---

## 17. Kết Luận

QuantBT WFO không cố trả lời:

```text
Params nào tối đa hóa quá khứ?
```

Nó trả lời:

```text
Params nào học được trên IS,
không decay quá mạnh trên OOS,
ổn định giữa nhiều fold,
không phải sharp peak,
và còn chịu được synthetic/stress scenarios?
```

Đây là cách chọn params conservative.

Nó có thể bỏ qua một vài backtest rất đẹp.

Nhưng nó giảm xác suất chọn nhầm noise.

Trong quant research, đó là trade-off đúng.

Một backtest đáng tin không phải backtest có Sharpe cao nhất.

Một backtest đáng tin là backtest có methodology chọn params minh bạch,
ít leak, có kiểm định robustness, và có thể audit.

---

## 18. Native WFO Runtime V2 Và Methodology

`NativeWfoRuntimeV2` không thêm một optimization mode mới và không đổi ý nghĩa
thống kê của `global`, `per_fold_decay`, hoặc `per_fold_causal`. Nó chỉ là một
execution runtime A4 cho workload hẹp: signal StrategyIR một symbol, input W1/
W2 đã chuẩn bị causal, và một account reset-flat độc lập cho từng OOS fold.

Do đó phải tách hai câu hỏi:

```text
selection chronology: public WalkForwardEngine + optimization schedule
candidate/fold simulation: optional NativeWfoRuntimeV2 prepared runtime
```

Runtime native không làm Python feature trở nên causal, không tự stitch OOS
equity continuous, và không biến callback/portfolio/package thành Rust. Nó chỉ
loại bỏ repeated execution/accounting overhead sau khi alpha đã tạo một finite
numeric signal tape hợp lệ. Mỗi audit selected candidate phải tái tạo đúng
intent fingerprint của source score batch; nếu generator không deterministic
thì audit fail thay vì tạo evidence sai. Xem [Native WFO Runtime V2](native_wfo_runtime.md)
để biết contract và giới hạn kỹ thuật.

Phase 74 thêm một public scorer hẹp dưới `QuantBTEndpoint.walk_forward()`: W0
scalar callback có thể được batch score bởi Rust; W1/W2 là opt-in cache/generator
cho alpha có feature parameter-independent. Engine vẫn giữ Optuna sequence,
objective/selector từng mode và one final stitched account. Matrix chỉ gồm một
symbol OHLCV, `signal_notional`/`single_signal`/`notional`/`unit`, annualization
`365`; `mode_2_sbb` vẫn dùng proxy path. Public prepared route cũng chứng nhận
`pct_equity` transition-sized khi khai báo rõ `target_runtime="rust"` và
`native_prepared_wfo="require"`; `auto` vẫn giữ legacy. Nó không phải per-bar
equity-fraction rebalance. Với strict per-fold schedule, prepared alpha phải tự
declare `causal_cache_contract="causal_parameter_independent_v1"`; engine không
tự biến Python cache thành chứng nhận no-look-ahead. Xem
[Public prepared-native WFO scoring](native_prepared_wfo_public.md).
