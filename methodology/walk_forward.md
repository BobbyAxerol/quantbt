# Walk Forward Methodology

Tài liệu này mô tả methodology Walk Forward Optimization (WFO) đang được
implementation trong QuantBT. Mục tiêu không phải là chọn params đẹp nhất trên
quá khứ, mà là chọn params có khả năng generalize tốt hơn, ít overfit hơn, và có
audit trail rõ ràng cho từng fold, trial, candidate và final backtest.

- `IS`: in-sample train set.
- `OOS`: out-of-sample test set.
- `theta`: một bộ tham số strategy.
- `r_theta`: return series sinh ra bởi strategy với tham số `theta`.
- `S_IS`, `S_OOS`: Sharpe trên IS và OOS.
- `J(theta)`: objective value dùng để xếp hạng params.

---

## 1. Vai Trò Của WFO Trong QuantBT

WFO nằm giữa research layer và execution/accounting backtest engine. Research
layer chịu trách nhiệm feature, alpha logic, signal và tránh look-ahead bias
trong strategy. WFO chịu trách nhiệm chia thời gian, gọi strategy theo fold,
chạy Optuna nếu cần, chọn params, stitch OOS signal, rồi gửi signal cuối vào
endpoint backtest thật.

Thiết kế này cố ý tách alpha logic khỏi engine: research alpha, model selection,
execution simulation, accounting, report và audit là các lớp riêng.

---

## 2. Time-Safe Fold Construction

Mỗi fold có `train_index`, `test_index`, `train_start`, `train_end`,
`test_start`, `test_end`. Với WFO chuẩn:

$$
\mathrm{train\_end}_{k}<\mathrm{test\_start}_{k}
$$

Tham số split: `split_mode`, `split_frequency`, `window_mode`, `train_window`,
`min_train_bars`, `min_test_bars`. `expanding` dùng toàn bộ lịch sử trước OOS;
`rolling` chỉ dùng cửa sổ train gần nhất.

### 2.1. Global Và Per-Fold Optimization Schedule

`optimization_mode` trả lời câu hỏi *chấm và chọn params như thế nào*.
`optimization_schedule` trả lời câu hỏi *khi nào tạo một study mới*.

`global` giữ behavior lịch sử: một Optuna study đánh giá toàn bộ folds và chọn
một params chung. Đây là retrospective global calibration; train window của
fold sau có thể chứa giai đoạn từng là OOS của fold trước.

`per_fold_decay` chỉ dành cho Mode 1 trong Phase 49A. Với mỗi outer fold (k),
QuantBT tạo study độc lập, rank toàn bộ trials trên (D_{\mathrm{IS},k}), freeze
top-IS candidate pool, rồi dùng chính (D_{\mathrm{OOS},k}) để đo decay và chọn
candidate của fold đó. Vì OOS tham gia selection, kết quả là
`selection_adjusted_oos`, không phải untouched holdout.

`per_fold_causal` áp dụng cho Mode 4 hoặc Mode 1 nested validation. Với Mode 4,
params được chọn hoàn toàn từ (D_{\mathrm{IS},k}), freeze trước khi outer OOS
được chạy. Với Mode 1, decay được đo bằng inner folds nằm hoàn toàn trong
(D_{\mathrm{IS},k}), rồi outer OOS mới được chạy sau khi params freeze. Cả hai
route là strict fold-local retraining nếu strategy implementation cũng causal.

Mỗi fold có study, duplicate state và deterministic seed riêng. Khi fold hoàn
tất, QuantBT stitch target OOS theo chronology và chạy account engine đúng một
lần. Policy `carry` giữ position/equity liên tục; boundary không tự reset vốn
hay tạo close/reopen.

### 2.2. Tối Ưu Lifecycle Phase 49B

Phase 49B giữ nguyên map toán học từ params đến objective. Một prepared context
run-local chuẩn hóa index, fold slices và content signature đúng một lần. Scorer
endpoint gọi cùng accounting kernel và cùng `compute_performance_metrics`, nhưng
trả scalar objective contract thay vì dựng `BacktestResult`/DataFrame đầy đủ cho
mỗi trial. Sau selection, ledger trial không được chọn chỉ giữ scalar fields cần
cho audit table; selected trial vẫn giữ fold metrics đầy đủ.

Ba invariants được khóa bằng parity tests:

$$
\theta^{*}_{\mathrm{prepared}}=\theta^{*}_{\mathrm{reference}},
\qquad
J_{\mathrm{prepared}}(\theta)=J_{\mathrm{reference}}(\theta),
\qquad
E^{\mathrm{final}}_{\mathrm{prepared}}=E^{\mathrm{final}}_{\mathrm{reference}}.
$$

QuantBT không cache arbitrary strategy output. Vì vậy cải thiện tốc độ chỉ đến
từ framework preparation/report retention, không giả định indicator của user là
deterministic hoặc causal.

---

## 3. Strategy Contract

Strategy có thể là callable, class, hoặc object có `build_signal` /
`generate_signal`. QuantBT gọi theo contract:

```python
strategy(data=data, params=params, train_index=train_index, test_index=test_index, fold=fold)
```

Output hợp lệ là `pd.Series`, `pd.DataFrame`, hoặc `dict[str, pd.Series]`, và
bắt buộc có `DatetimeIndex` để tránh reindex sai.

---

## 4. Scoring Backend

QuantBT WFO có hai scoring backend: `proxy` và `endpoint`. `proxy` tính return
proxy trực tiếp từ signal và data, nhanh hơn cho bootstrap/Optuna. `endpoint`
gọi đúng QuantBT endpoint như `pct_equity`, `signal_notional`, portfolio, basket
hoặc arbitrage, chậm hơn nhưng sát accounting thật hơn. `mode_2_sbb` bắt buộc
dùng `proxy`, vì nó cần mô phỏng nhiều synthetic paths từ IS return.

---

## 5. Metric Nền Và Annualization

Metric nền là Sharpe:

$$
\mathrm{Sharpe}(\theta)=\frac{\operatorname{mean}(r_{\theta})}{\operatorname{std}(r_{\theta})}\sqrt{N}
$$

Trong đó `N = scoring_trading_days`; crypto thường dùng `365`, equity daily
thường dùng `252`. Sharpe luôn phải được đọc cùng trade count, drawdown,
exposure và số bar.

---

## 6. Trade Frequency Penalty

Một alpha đánh quá ít có thể tạo Sharpe cao giả tạo. QuantBT có optional penalty
qua `min_trades_per_year` và `trade_penalty_factor`. Số trade yêu cầu được scale
theo thời lượng:

$$
T_{\mathrm{req}}=\mathrm{min\_trades\_per\_year}\times\frac{\mathrm{duration\_days}}{365}
$$

Penalty:

$$
\mathrm{Penalty}=\alpha\max\left(0,1-\frac{T_{\mathrm{actual}}}{T_{\mathrm{req}}}\right)
$$

Sharpe sau penalty:

$$
S_{\mathrm{penalized}}=S_{\mathrm{raw}}-\mathrm{Penalty}
$$

Nếu không khai báo penalty, hành vi cũ được giữ nguyên. Đây là guardrail chống
bẫy overfit của alpha ít giao dịch nhưng giữ position lâu để làm Sharpe đẹp.

---

## 7. Optuna Search Và Candidate Pool

Khi truyền `param_ranges`, QuantBT dùng Optuna để sample trial. Các tham số chính
là `optuna_trials`, `optuna_early_stopping`, `random_seed`, `use_numba`,
`top_is_fraction`, `top_is_k`.

Nếu `top_is_k` được khai báo, QuantBT lấy đúng top K trial. Nếu không, số
candidate được tính:

$$
K=\left\lceil n_{\mathrm{trials}}\times\mathrm{top\_is\_fraction}\right\rceil
$$

Candidate selection không nhất thiết lấy trial tốt nhất tuyệt đối. Một số mode
ưu tiên vùng tham số robust hơn, dù objective đơn điểm thấp hơn một chút.

---

## 8. Candidate Selection Metrics

Các selector hiện có:

- `robust_decay`: chọn theo OOS Sharpe sau khi phạt decay.
- `mean_oos_sharpe`: chọn OOS Sharpe trung bình.
- `mean_is_sharpe`: chọn IS Sharpe trung bình.
- `is_plateau_robust`: chọn plateau trên train/search objective.
- `is_only_robust`: strict IS-only temporal plus plateau selector.
- `full_robust`: full-sample temporal plus plateau calibration.
- `full_plateau_robust`: full-sample plateau-only calibration.
- `full_temporal_robust`: full-sample temporal-only calibration.
- `full_best`: best full-sample objective, rủi ro overfit cao nhất.

Default mode 1 là `robust_decay`. Default mode 4 là `is_only_robust`. Default
mode 5 là `full_robust`. Config intentionally reject metric sai cho mode 4/5 để
tránh user tưởng đang chạy anti-leakage nhưng thực tế lại dùng selector khác.

---

## 9. Mode 1: `mode_1_decay`

Mode 1 là WFO decay control. Với mỗi fold, QuantBT tính Sharpe trên IS và OOS,
rồi đo decay:

$$
d_k(\theta)=S_{\mathrm{IS},k}(\theta)-S_{\mathrm{OOS},k}(\theta)
$$

Mean decay và decay volatility:

$$
\overline{d}(\theta)=\operatorname{mean}_{k}\left(d_k(\theta)\right)
$$

$$
\sigma_d(\theta)=\operatorname{std}_{k}\left(d_k(\theta)\right)
$$

Objective:

$$
J_1(\theta)=\overline{S}_{\mathrm{OOS}}(\theta)-\lambda\sigma_d(\theta)-\gamma\max\left(0,\overline{d}(\theta)\right)
$$

Tham số chính: `decay_lambda`, `decay_gamma`, `candidate_decay_lambda`,
`candidate_decay_gamma`.

Dụng ý của mode 1 là không thưởng params chỉ thắng IS. Một params tốt phải giữ
được hiệu năng khi sang OOS, và decay không được quá bất ổn giữa các fold. Mode
này phù hợp khi user chấp nhận dùng OOS như validation stage.

### 9.1. Dụng Ý Chuẩn Quỹ Của Mode 1

Mode 1 phản ánh bài toán rất thực tế trong quỹ: một alpha có thể đẹp trên train
nhưng mất edge ngay khi sang giai đoạn kế tiếp. Vì vậy objective không chỉ hỏi
OOS Sharpe cao hay không, mà còn hỏi:

- IS có đang quá đẹp so với OOS không?
- decay có ổn định giữa nhiều fold không?
- một fold thắng lớn có đang che giấu nhiều fold yếu không?

Trong research nghiêm túc, `S_IS - S_OOS` là tín hiệu quan trọng. Nếu decay luôn
dương và lớn, strategy có thể đang overfit. Nếu decay lúc rất âm, lúc rất dương,
params có thể quá nhạy regime.

### 9.2. Selection Choices Trong Mode 1

Mode 1 thường dùng `candidate_selection_metric="robust_decay"`. Đây là lựa chọn
khớp nhất với objective vì nó chọn candidate theo OOS performance sau khi phạt
decay.

Các lựa chọn phụ:

- `mean_oos_sharpe`: aggressive hơn, ưu tiên OOS cao.
- `mean_is_sharpe`: chủ yếu dùng diagnostic, dễ overfit nếu dùng làm selector.
- `is_plateau_robust`: dùng khi muốn chọn vùng IS/search ổn định trước khi nhìn
  OOS candidate.

Nếu mục tiêu là báo cáo validation, `robust_decay` hợp lý hơn `mean_oos_sharpe`
vì nó không bị một vài OOS fold đẹp làm lệch quyết định.

### 9.3. Tham Số Cần Tune Cẩn Thận

`decay_lambda` càng cao thì càng phạt params có decay biến động. `decay_gamma`
càng cao thì càng phạt params có IS đẹp hơn OOS quá nhiều.

Nếu alpha có bản chất regime-following và decay tự nhiên thay đổi mạnh, đặt hai
tham số này quá cao có thể làm selector quá conservative. Nếu alpha có nhiều
params và search space rộng, nên tăng penalty để giảm data snooping.

Một cấu hình cân bằng thường bắt đầu từ:

```text
decay_lambda = 0.5
decay_gamma  = 0.5
```

Sau đó điều chỉnh theo số fold, độ dài OOS và mức noisy của strategy.

---

## 10. Mode 2: `mode_2_sbb`

Mode 2 là Synthetic Block Bootstrap robustness. Nó không dùng OOS thật trong
Optuna objective. Strategy chạy trên IS, rồi return proxy của IS được mô phỏng
thành nhiều synthetic paths. Với mỗi synthetic path, QuantBT tính synthetic
Sharpe.

Mean synthetic Sharpe:

$$
\mu_{\mathrm{boot}}(\theta)=\operatorname{mean}\left(S_{\mathrm{boot}}(\theta)\right)
$$

Synthetic dispersion:

$$
\sigma_{\mathrm{boot}}(\theta)=\operatorname{std}\left(S_{\mathrm{boot}}(\theta)\right)
$$

Synthetic decay:

$$
d_{\mathrm{boot}}(\theta)=S_{\mathrm{IS}}(\theta)-\mu_{\mathrm{boot}}(\theta)
$$

Objective:

$$
J_2(\theta)=\mu_{\mathrm{boot}}(\theta)-\lambda_{\mathrm{sbb}}\max\left(0,d_{\mathrm{boot}}(\theta)\right)-\eta_{\mathrm{sbb}}\sigma_{\mathrm{boot}}(\theta)
$$

Tham số chính: `sbb_samples`, `sbb_block_length`, `sbb_decay_lambda`,
`sbb_std_penalty`, `sbb_simulation`.

`stationary` là block bootstrap mặc định. `regime` sample theo volatility regime.
`stress` scale volatility bằng `stress_vol_multiplier`. `garch` mô phỏng
volatility clustering nếu có dependency `arch`.

Dụng ý chuẩn quỹ là kiểm tra path dependency, giữ autocorrelation cục bộ, và
stress alpha mà không mở OOS thật cho optimizer.

### 10.1. Dụng Ý Chuẩn Quỹ Của Mode 2

Mode 2 phục vụ câu hỏi khác mode 1: nếu ta giữ nguyên alpha nhưng thị trường đi
theo một đường giá hơi khác, params còn sống không?

Backtest lịch sử chỉ là một path đã xảy ra. Trong thực tế, cùng distribution có
thể sinh ra nhiều path khác nhau. Stationary Block Bootstrap cố giữ cụm return
liền kề để không phá autocorrelation ngắn hạn, đồng thời tạo nhiều biến thể
khác của train path.

Điều này đặc biệt quan trọng với:

- scalping;
- mean reversion;
- grid/DCA;
- basis hoặc spread strategy;
- alpha có stop-loss/take-profit nhạy path.

### 10.2. Simulation Choices

`stationary` là lựa chọn mặc định. Nó nhanh, ổn định, và ít giả định.

`regime` phù hợp khi user muốn stress theo volatility bucket. Ví dụ một alpha
chỉ sống trong low-vol regime thì cần xem high-vol synthetic path có làm Sharpe
sụp không.

`stress` phù hợp để kiểm tra nhanh khi volatility tăng 1.5x hoặc 2x.

`garch` phù hợp khi cần mô phỏng volatility clustering có cấu trúc hơn, nhưng
chậm hơn và phụ thuộc data đủ dài. Không nên dùng GARCH chỉ vì nghe “xịn”; nếu
train sample quá ngắn, fitted volatility process có thể không đáng tin.

### 10.3. Tham Số Ảnh Hưởng Objective

`sbb_samples` càng cao thì distribution Sharpe synthetic càng ổn định nhưng
runtime tăng.

`sbb_block_length` quá ngắn sẽ phá cấu trúc path; quá dài sẽ tạo quá ít biến thể.

`sbb_std_penalty` cao làm selector tránh params có Sharpe synthetic phân tán
mạnh.

`sbb_decay_lambda` cao làm selector tránh params có IS Sharpe cao nhưng synthetic
Sharpe giảm mạnh.

Mode 2 không nên được đọc như OOS proof. Nó là train-only robustness stress.

---

## 11. Mode 3: `mode_3_flat_minima`

Mode 3 chọn vùng tham số phẳng thay vì sharp peak. Sau Optuna, QuantBT lấy top
trials theo `flat_top_fraction`, normalize param space về `[0, 1]`, rồi cluster
bằng logic DBSCAN-style với `flat_eps` và `flat_min_samples`.

Medoid của cluster:

$$
\theta_{\mathrm{medoid}}=\operatorname*{arg\,min}_{\theta_i\in C}\left\lVert x_i-\overline{x}_C\right\rVert_2
$$

Centroid được snap về grid:

$$
\theta_{\mathrm{centroid}}=\operatorname{snap}\left(\overline{x}_C\right)
$$

Tham số chính:

- `flat_top_fraction`: phần top trial đưa vào clustering.
- `flat_eps`: bán kính density.
- `flat_min_samples`: số điểm tối thiểu để thành cụm.
- `flat_selector`: `medoid` hoặc `centroid`.

`medoid` là trial thật đã chạy. `centroid` là trung tâm cụm, được snap về range
đã khai báo và có thể cần evaluate lại. Nếu không có cluster, QuantBT fallback
về best trial; đây là tín hiệu param surface có thể quá sắc hoặc rời rạc.

### 11.1. Dụng Ý Chuẩn Quỹ Của Mode 3

Mode 3 dựa trên một quan sát rất quan trọng: một tham số tốt thật sự thường có
hàng xóm cũng tương đối tốt. Nếu chỉ một điểm duy nhất trong param space thắng
lớn, còn xung quanh thua mạnh, đó thường là dấu hiệu overfit.

Trong ngôn ngữ optimization, ta muốn vùng phẳng:

$$
\left\lvert J(\theta)-J(\theta+\epsilon)\right\rvert
\text{ nhỏ với } \epsilon \text{ nhỏ}
$$

QuantBT không cần tính gradient phức tạp. Nó dùng top trials, normalize param
space, rồi tìm cụm dày. Đây là cách thực dụng, minh bạch và dễ audit.

### 11.2. Medoid Và Centroid

`flat_selector="medoid"` chọn trial thật nằm gần trung tâm cụm. Đây là lựa chọn
an toàn nhất vì params đó đã được evaluate.

`flat_selector="centroid"` lấy trung tâm cụm rồi snap về grid. Lựa chọn này có
thể tốt hơn nếu cluster bị lệch bởi noise, nhưng cần evaluate lại vì centroid
có thể là params chưa từng chạy.

Với production research, `medoid` thường là default tốt hơn. `centroid` phù hợp
khi param grid dày và chi phí evaluate lại thấp.

### 11.3. Tham Số DBSCAN-Style

`flat_eps` là bán kính để xem các params có gần nhau không. Nếu quá nhỏ, mọi
điểm thành noise. Nếu quá lớn, nhiều vùng khác nhau bị gộp sai.

`flat_min_samples` là số điểm tối thiểu để cụm có ý nghĩa. Với ít trial, giá trị
này nên nhỏ; với nhiều trial, có thể tăng để tránh cluster giả.

`flat_top_fraction` quyết định top region. Nếu quá thấp, cụm thiếu điểm; nếu quá
cao, đưa cả params trung bình vào cluster.

Mode 3 không thay thế OOS validation. Nó kiểm tra hình học của param surface.

---

## 12. Plateau Robustness

Plateau score được dùng trong mode 3, mode 4 và mode 5. Với cluster `C`:

$$
P_C=Q_C+w_mM_C-w_sV_C+w_n\log\left(1+\lvert C\rvert\right)
$$

Trong đó:

$$
Q_C=\operatorname{quantile}\left(J(\theta_i),q\right),\quad M_C=\operatorname{median}\left(J(\theta_i)\right),\quad V_C=\operatorname{std}\left(J(\theta_i)\right)
$$

Tham số:

- `plateau_quantile`: lower-tail quantile.
- `plateau_median_weight`: trọng số median.
- `plateau_std_penalty`: phạt dispersion.
- `plateau_size_bonus`: thưởng cluster size.

Ý nghĩa: lower-tail tốt cho thấy cụm không mong manh; median tốt cho thấy cụm
không chỉ có một điểm thắng; std thấp cho thấy cụm ổn định; cluster lớn cho thấy
vùng tham số có độ dày.

Plateau score là phần QuantBT dùng để biến trực giác “vùng phẳng tốt hơn điểm
đơn lẻ” thành công thức. `plateau_quantile` nhìn lower-tail của cluster. Nếu
lower-tail tốt, nghĩa là ngay cả những member yếu trong cụm vẫn không quá tệ.

`plateau_median_weight` thưởng median của cụm, tránh cụm có một vài outlier đẹp.
`plateau_std_penalty` phạt cụm phân tán. `plateau_size_bonus` thưởng nhẹ cho cụm
dày bằng log-size để không làm size áp đảo chất lượng.

Vì dùng log-size, phần thưởng cụm lớn tăng chậm:

$$
\log(1+\lvert C\rvert)
$$

Điều này có ý nghĩa domain: cụm lớn là tốt, nhưng cụm lớn mà score thấp không
nên thắng cụm nhỏ hơn nhưng robust hơn.

---

## 13. Mode 4: `mode_4_is_only_robust`

Mode 4 là strict anti-leakage selection. OOS không được dùng để chọn params.
Optuna objective chỉ dùng IS. Sau đó QuantBT chia IS thành `is_subperiods`
shards và đo sự ổn định temporal.

Sharpe từng shard:

$$
S_i(\theta)=\mathrm{Sharpe}\left(r_{\theta,i}\right)
$$

Median, lower-tail và MAD:

$$
M_T(\theta)=\operatorname{median}\left(S_i(\theta)\right)
$$

$$
Q_T(\theta)=Q_{25}\left(S_i(\theta)\right)
$$

$$
D_T(\theta)=\operatorname{median}\left(\left\lvert S_i(\theta)-M_T(\theta)\right\rvert\right)
$$

Temporal score:

$$
T(\theta)=M_T(\theta)+w_qQ_T(\theta)-w_dD_T(\theta)
$$

Final IS-only robust score:

$$
J_4(\theta)=w_TT(\theta)+w_PP(\theta)-B(\theta)-C(\theta)
$$

Tham số chính:

- `is_subperiods`: số shard trong IS.
- `q25_weight`: trọng số lower-tail Sharpe.
- `dispersion_penalty`: phạt MAD.
- `temporal_weight`: trọng số temporal score.
- `plateau_weight`: trọng số plateau score.
- `use_bootstrap_penalty`, `use_complexity_penalty`: optional extension.

Hiện tại bootstrap/complexity penalty mặc định không phạt thêm. Mode 4 trả
params để giao dịch OOS fold kế tiếp. OOS chỉ được dùng sau selection để report
và stitch validation, nên đây là mode phù hợp nhất khi cần anti-leakage nghiêm.

### 13.1. Dụng Ý Chuẩn Quỹ Của Mode 4

Mode 4 được thiết kế cho trường hợp user muốn selection tuyệt đối không nhìn
OOS. Đây là khác biệt quan trọng so với mode 1. Trong mode 4, OOS đóng vai trò
report/validation sau khi params đã bị freeze.

Nó trả lời câu hỏi:

```text
Chỉ nhìn train, có thể chọn params nào robust nhất để đi vào giai đoạn kế tiếp?
```

Đây là tư duy gần hơn với cách vận hành thật: tại thời điểm live, ta không biết
OOS tương lai. Ta chỉ có thể chọn params dựa trên train history và robustness
test bên trong train.

### 13.2. Temporal Robustness

Mode 4 chia IS thành nhiều shard để tránh params chỉ thắng một giai đoạn. Nếu
Sharpe chỉ cao ở một shard nhưng thấp ở các shard khác, median và Q25 sẽ yếu,
MAD có thể cao.

Temporal score dùng:

- median để đo hiệu năng trung tâm;
- Q25 để nhìn downside của subperiods;
- MAD để phạt dispersion robust hơn standard deviation.

MAD được dùng vì nó ít nhạy outlier hơn:

$$
\operatorname{MAD}(S)=\operatorname{median}\left(\left\lvert S_i-\operatorname{median}(S)\right\rvert\right)
$$

### 13.3. Selection Choices Trong Mode 4

Mode 4 bắt buộc `candidate_selection_metric="is_only_robust"`.

Selector này kết hợp:

- top IS candidates;
- temporal robustness;
- plateau robustness;
- medoid hoặc centroid.

Nếu không có cluster đủ tốt, selector fallback về best temporal record. Fallback
này không phải lỗi, nhưng là tín hiệu rằng param surface chưa đủ dày để kết luận
plateau mạnh.

### 13.4. Khi Nào Dùng Mode 4

Dùng mode 4 khi:

- muốn anti-leakage nghiêm;
- strategy có nhiều tham số;
- OOS data ít và không muốn optimizer học OOS;
- mục tiêu là chọn params cho kỳ tiếp theo.

Không nên kỳ vọng mode 4 luôn chọn params có IS cao nhất. Nó cố tình đánh đổi
một phần IS score để lấy stability.

---

## 14. Mode 5: `mode_5_full_robust`

Mode 5 là full-sample robust calibration, không phải WFO validation. QuantBT tạo
một fold duy nhất:

$$
\mathrm{train\_index}=\mathrm{test\_index}=\mathrm{full\_index}
$$

Toàn bộ dữ liệu được xem là calibration sample. Metadata ghi rõ:

```text
validation_claim = "none_full_sample_calibration"
full_sample_used_for_selection = True
```

Selector:

- `full_robust`: temporal plus plateau, mặc định.
- `full_plateau_robust`: ưu tiên plateau.
- `full_temporal_robust`: ưu tiên subperiod stability.
- `full_best`: objective cao nhất, rủi ro overfit cao nhất.

Dụng ý của mode 5 là chọn một bộ params production sau khi alpha đã qua
validation độc lập. Nó ép params sống qua toàn bộ lịch sử đã biết và nhiều
regime, nhưng không được dùng như bằng chứng OOS.

### 14.1. Dụng Ý Chuẩn Quỹ Của Mode 5

Mode 5 dành cho production calibration sau khi alpha đã qua validation bằng cách
khác. Nó không trả lời “alpha có generalize không?”. Nó trả lời:

```text
Sau khi đã tin alpha, nếu phải chọn một params để deploy,
params nào robust nhất trên toàn bộ lịch sử đã biết?
```

Nhiều workflow quỹ có bước tương tự: validate model bằng holdout/WFO trước, sau
đó refit hoặc recalibrate trên toàn bộ data trước deployment. Điểm quan trọng là
không được trộn lẫn calibration result với validation proof.

### 14.2. Selector Con Trong Mode 5

`full_robust` là default vì nó kết hợp temporal stability và plateau stability.

`full_plateau_robust` phù hợp khi user tin rằng độ phẳng param surface quan
trọng hơn subperiod Sharpe.

`full_temporal_robust` phù hợp khi regime stability là ưu tiên số một.

`full_best` chỉ nên dùng để benchmark upper bound, không nên dùng làm production
selector nếu search space lớn.

### 14.3. Cách Đọc Metadata Mode 5

Mode 5 luôn phải được đọc cùng:

```text
validation_claim = "none_full_sample_calibration"
```

và:

```text
full_sample_used_for_selection = True
```

Nếu report dùng mode 5, cần nói rõ đây là calibration. Không nên trình bày nó
như OOS performance.

---

## 15. Operational Notes

`target_mode` quyết định OOS output được gửi vào engine nào. Các target hiện hỗ
trợ gồm `signal_notional`, `notional`, `unit`, `pct_equity`, `dca_ladder`,
`portfolio`, `basket`, và `arbitrage`. Single-symbol thường trả `pd.Series`;
portfolio trả `pd.DataFrame` hoặc `dict[str, pd.Series]`.

Nếu truyền `params`, WFO dùng params cố định. Nếu truyền `param_ranges`, WFO chạy
Optuna. Range hợp lệ gồm `(low, high)`, `(low, high, step)`, categorical list,
hoặc fixed value khác `None`. Fixed flags nên merge trong strategy, ví dụ:

```python
run_params = {"issl": True, **params}
```

Metadata lưu `optimization_mode`, `candidate_selection_metric`, `n_folds`,
`n_trials`, `n_candidates`, `data_hash`, `config_hash`, `scoring_backend`,
`scoring_trading_days`, `validation_claim`, trial table và fold metrics. Đây là
audit trail để biết params cuối cùng đến từ đâu và có dùng OOS để chọn hay không.

Nếu mode 1 tốt nhưng mode 4 xấu, params có thể đang phụ thuộc OOS selection. Nếu
mode 2 xấu, alpha có thể yếu khi return path bị perturb. Nếu mode 3 fallback
best, param surface có thể quá sắc. Nếu mode 5 đẹp, vẫn không được xem là OOS
proof; nó chỉ là câu trả lời cho production calibration trên toàn bộ lịch sử đã
biết.

Workflow khuyến nghị: research signal, chống look-ahead trong strategy, chạy
`mode_1_decay` hoặc `mode_4_is_only_robust`, stress bằng `mode_2_sbb`, kiểm tra
surface bằng `mode_3_flat_minima`, validate bằng endpoint thật, rồi dùng
`mode_5_full_robust` để chọn params production trước forward test/paper/live.

Không có mode nào đúng cho mọi alpha. Lựa chọn mode phụ thuộc vào số tham số, độ
dài data, trade frequency, regime sensitivity và mức cần anti-leakage.

### 15.1. Strict Causal Mode 1 Theo Nested Validation

`mode_1_decay + optimization_schedule="per_fold_causal"` dùng khi muốn giữ
objective decay của Mode 1 nhưng không cho outer OOS tham gia chọn params. Với
outer fold \(D_i, T_i\), engine tạo các inner folds \((d_{ij}, t_{ij})\) sao cho
mọi \(t_{ij} \subset D_i\). Optuna, top-IS candidates và `robust_decay` chỉ
được chạy trên các inner folds này. Sau khi chọn \(\theta_i^\star\), engine mới
emit signal và đo performance trên \(T_i\) đúng một lần.

Do đó, đây là strict outer-OOS protocol, nhưng không phải “free validation”:
nó tốn nhiều backtest hơn vì `optuna_trials` được áp dụng cho mỗi outer study,
và outer IS phải đủ dài để chứa `inner_min_folds`. Metadata trả về
`inner_validation`, `inner_fold_table`, `params_by_fold` và
`chronological_validation_claim="strict_outer_oos_after_frozen_selection"`.
Không đủ inner history là lỗi cấu hình/data, không phải lý do để fallback sang
schedule khác.
