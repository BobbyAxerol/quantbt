# Walk-Forward Optimization Methodology

Walk-Forward Optimization (WFO) trong QuantBT được thiết kế để chọn tham số theo cách gần với nghiên cứu quỹ hơn là chọn bộ tham số đẹp nhất trên toàn bộ lịch sử. Flow chính gồm: chia dữ liệu theo thời gian thành nhiều fold, mỗi fold có vùng train/In-Sample (IS) và vùng test/Out-of-Sample (OOS); strategy chỉ được học hoặc tối ưu trên IS; tín hiệu OOS của từng fold được stitch lại thành một chuỗi liên tục; cuối cùng QuantBT chạy một backtest thật trên chuỗi OOS đã stitch để phí, slippage, funding, margin và position boundary được tính bởi engine chuẩn.

Vấn đề WFO giải quyết là overfit và look-ahead bias. Nếu Optuna được nhìn trực tiếp Sharpe OOS ở từng trial, OOS vô tình trở thành tập train thứ hai. Vì vậy QuantBT dùng two-stage selection: Stage 1 tìm ứng viên trên IS hoặc synthetic IS; Stage 2 chỉ sau khi danh sách ứng viên bị đóng băng mới đo OOS để chọn bộ robust nhất. Công thức ranking mặc định là:

```text
score = mean_oos_sharpe
        - lambda * std(IS_sharpe - OOS_sharpe)
        - gamma * max(0, mean(IS_sharpe - OOS_sharpe))
```

`mode_1_decay` ưu tiên tham số có IS tốt nhưng bị phạt nếu decay sang OOS lớn hoặc không ổn định. `mode_2_sbb` không tối ưu trực tiếp trên OOS, mà tạo synthetic OOS từ IS bằng stationary bootstrap, regime bootstrap, stress volatility hoặc GARCH. Ý nghĩa là kiểm tra tham số dưới nhiều path giả lập nhưng vẫn không leak dữ liệu tương lai. `mode_3_flat_minima` chọn vùng tham số ổn định bằng clustering/flat-minima, tránh chọn một điểm peak sắc nhọn có thể chỉ là noise.

Các penalty như trade-frequency penalty giúp tránh alpha đánh quá ít nhưng Sharpe cao ảo. Về level thị trường, methodology này nằm ở mức research-grade đến pre-production institutional: minh bạch, chống leak, có audit metadata, phù hợp để lọc tham số robust. Nó chưa thay thế live paper trading hoặc independent validation, nhưng là nền tốt hơn nhiều so với backtest tối ưu toàn lịch sử kiểu retail.
