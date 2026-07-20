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
