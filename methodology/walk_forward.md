# Walk Forward Methodology

Tài liệu này tóm tắt methodology Walk Forward Optimization (WFO) trong QuantBT.
Mục tiêu không phải là tìm tham số đẹp nhất trên quá khứ, mà là chọn tham số có
khả năng sống sót tốt hơn khi regime thay đổi, giảm overfit và giữ audit trail.

Flow chung: dữ liệu được chia theo thời gian thành các fold train/test. Với bộ
tham số \( \theta \), strategy tạo signal theo đúng fold. Engine chỉ mô phỏng
signal đã có; look-ahead trong feature thuộc strategy layer. Metric cơ bản là
Sharpe:

$$
S(\theta)=\frac{\mathbb{E}[r_\theta]}{\sigma(r_\theta)}\sqrt{N}
$$

với \(N\) là số kỳ annualization, thường là 365 cho crypto. Trade-count penalty
có thể tránh alpha đánh quá ít nhưng Sharpe cao giả tạo.

## Mode 1: `mode_1_decay`

Mode này tối ưu quan hệ giữa in-sample (IS) và out-of-sample (OOS). Mỗi trial
tính \(S_{IS}\), \(S_{OOS}\), rồi đo decay:

$$
d_k(\theta)=S_{IS,k}(\theta)-S_{OOS,k}(\theta)
$$

Objective dạng:

$$
J(\theta)=\overline{S}_{OOS}
-\lambda\,\sigma(d)
-\gamma\,\max(0,\overline{d})
$$

Dụng ý là không thưởng params chỉ thắng IS; tham số tốt phải giữ hiệu năng khi
sang OOS và decay không quá bất ổn.

## Mode 2: `mode_2_sbb`

Mode này dùng Stationary Block Bootstrap trên return path của IS. Nó không gọi
endpoint scoring vì cần tạo nhiều synthetic path. Objective thưởng median/mean
Sharpe synthetic, phạt decay và phạt độ phân tán:

$$
J(\theta)=\mu(S_{boot})-\lambda\max(0,d)-\eta\sigma(S_{boot})
$$

Các biến quan trọng: `sbb_samples`, `sbb_block_length`,
`sbb_simulation=stationary|regime|stress|garch`.

## Mode 3: `mode_3_flat_minima`

Mode này lấy top trial, chuẩn hóa param space rồi tìm vùng plateau bằng clustering
DBSCAN. Thay vì chọn peak cao nhất, nó chọn medoid/centroid của cụm tốt:

$$
\theta^\*=\operatorname{medoid}(C^\*)
$$

Ý nghĩa chuẩn quỹ: ưu tiên vùng tham số phẳng, ít nhạy với nhiễu, dễ survive
out-of-sample hơn một điểm tối ưu sắc nhọn.

## Mode 4: `mode_4_is_only_robust`

Mode này tuyệt đối không dùng OOS để chọn params. Nó chia IS thành subperiods,
tính temporal robustness:

$$
T(\theta)=\operatorname{median}(S_i)-q\,Q_{25}(S_i)-m\,MAD(S_i)
$$

sau đó kết hợp plateau robustness:

$$
J(\theta)=w_TT(\theta)+w_PP(\theta)
$$

Params được chọn là bộ robust nhất trên IS để giao dịch OOS kế tiếp.

## Mode 5: `mode_5_full_robust`

Mode này là full-sample calibration, không phải validation. Toàn bộ dữ liệu được
xem là IS để tìm một bộ tham số production đi qua nhiều regime. Selector gồm
`full_robust`, `full_plateau_robust`, `full_temporal_robust`, `full_best`.
Metadata ghi rõ `validation_claim="none_full_sample_calibration"` để tránh hiểu
sai kết quả là OOS proof.
