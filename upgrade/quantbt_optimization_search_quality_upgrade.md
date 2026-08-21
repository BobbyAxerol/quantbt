# QuantBT Optimization Upgrade — Search Quality & Robust Selection

## Kết luận chẩn đoán

Optimizer cũ:

```python
optuna.samplers.TPESampler()
```

và cấu hình mới:

```python
TPESampler(
    n_startup_trials=10,
    multivariate=False,
    group=False,
)
```

về cơ bản dùng cùng chế độ TPE mặc định. Vì vậy optimizer cũ không có thuật toán tìm kiếm “mạnh hơn”.

Các khác biệt thực sự:

1. **Objective surface đã đổi** từ vectorized execution sang intrabar execution.
2. **Không warm-start** các bộ tham số tốt đã biết như `hyhy`.
3. Một run TPE đơn lẻ phụ thuộc mạnh vào random trajectory.
4. Search space có nhiều biến chỉ có tác dụng khi toggle tương ứng bật.
5. TPE hiện bắt đầu học sau chỉ 10 random trials trên không gian khoảng 20 chiều.
6. Early stopping chỉ dựa trên best-value stagnation, không có minimum trial floor.
7. Candidate cuối vẫn thiên về single best trial, chưa chọn theo plateau/stability.

`DuplicatePruner` cũ gần như không có tác dụng vì objective không gọi `trial.report()` và `trial.should_prune()`. Việc optimizer mới prune duplicate trực tiếp là đúng.

Không sampler ngẫu nhiên nào có thể bảo đảm luôn tìm global optimum. Chỉ exhaustive grid trên một finite search space đủ nhỏ mới có guarantee đó. Mục tiêu thực tế phải là:

```text
không bỏ sót baseline tốt đã biết
+ phủ search space tốt hơn
+ tìm vùng tham số ổn định
+ chọn candidate robust thay vì một lucky trial
```

---

# Phase 33A — Search Assurance

## 1. Warm-start và baseline floor

Mở rộng API:

```python
optimization = optimizer.optimize(
    param_ranges=param_ranges,
    fixed_params=fixed,
    initial_trials=[
        hyhy,
        hrhr,
        hyhy_migrate_quantbt,
    ],
    candidate_selector=selector,
)
```

Sau khi tạo study, gọi:

```python
for params in initial_trials:
    study.enqueue_trial(
        filter_search_params(
            params,
            param_ranges,
            fixed_params,
        ),
        user_attrs={
            "quantbt_source": "warm_start",
        },
        skip_if_exists=True,
    )
```

Yêu cầu:

- mọi historical champion phải được đánh giá lại qua evaluator hiện tại;
- lưu source `warm_start`, `random`, `tpe`, `refine`;
- candidate cuối không được kém best feasible baseline trên primary objective;
- nếu toàn bộ candidate mới kém baseline, trả baseline và ghi `search_regression=True`.

Đây không bảo đảm global optimum, nhưng bảo đảm framework không quên một điểm tốt đã biết.

---

## 2. Minimum trials trước early stopping

Thêm:

```python
@dataclass(frozen=True)
class OptimizationConfig:
    ...
    early_stopping_rounds: int | None = None
    early_stopping_min_trials: int = 0
```

Callback chỉ được stop khi:

```python
completed_trials >= early_stopping_min_trials
and stale_trials >= early_stopping_rounds
```

Ví dụ:

```python
early_stopping_min_trials=800
early_stopping_rounds=300
```

Không dùng `early_stopping_rounds=350` với kỳ vọng study chắc chắn chạy 600 trial.

---

## 3. Phased search orchestration

Thêm `OptimizationPlan`:

```python
OptimizationPlan(
    phases=(
        SearchPhase(
            name="explore",
            sampler="random",
            n_trials=300,
        ),
        SearchPhase(
            name="model",
            sampler="tpe",
            n_trials=1_200,
            sampler_kwargs={
                "n_startup_trials": 100,
                "multivariate": True,
                "group": True,
                "n_ei_candidates": 64,
            },
        ),
        SearchPhase(
            name="refine",
            sampler="cmaes",
            n_trials=400,
            top_k=10,
            freeze_categorical=True,
        ),
    )
)
```

Quy tắc:

### Explore

- Random hoặc QMC;
- phủ broad space;
- không early-stop;
- dùng nhiều fixed seeds.

### Model

- TPE multivariate;
- nhận historical baselines và top candidates từ explore;
- tối thiểu `5–10 × effective_dimension` startup/exploration trials.

### Refine

- chỉ dùng CMA-ES sau khi cố định boolean/categorical structure;
- thu hẹp numeric bounds quanh top stable regions;
- không chạy CMA-ES trực tiếp trên mixed categorical space.

---

## 4. Multi-seed search

Một study ngẫu nhiên không đủ để đánh giá chất lượng optimizer.

Public API:

```python
MultiSeedOptimization(
    seeds=(41, 42, 43, 44, 45),
    plan=plan,
)
```

Kết quả phải tổng hợp:

```text
best value mỗi seed
baseline rank mỗi seed
top parameter frequency
degree distribution
candidate overlap
objective variance giữa seeds
```

Chỉ xem một vùng là đáng tin khi nó xuất hiện hoặc hoạt động tốt ở nhiều seed.

---

## 5. Conditional search space

Thêm typed search-space API nhưng vẫn giữ dictionary legacy:

```python
SearchSpace(
    params={
        "usersi": Categorical([True, False]),

        "rsitrhs1": Int(
            10,
            40,
            active_if={"usersi": True},
        ),

        "rsitrhs2": Int(
            60,
            90,
            active_if={"usersi": True},
        ),

        "istp": Categorical([True, False]),

        "tppercent": Float(
            0.5,
            12.0,
            step=0.1,
            active_if={"istp": True},
        ),
    }
)
```

Tương tự cho:

```text
useatr  -> len_atr1, len_atr2
usevol  -> rvol, len_vol
istrailing -> trailing parameters
```

### Lưu ý legacy

Trong Delta-RSI cũ, một số length vẫn ảnh hưởng `start_idx` dù filter tắt. Không tự động loại chúng khỏi search cho đến khi strategy contract xác nhận chúng thật sự inactive.

Cho phép evaluator cung cấp:

```python
effective_params_builder(params)
```

để:

- tạo semantic duplicate key;
- báo effective dimension;
- không coi hai trial khác tên nhưng cùng behavior là hai vùng độc lập.

---

## 6. Search-space diagnostics

Trước khi optimize, framework phải in/lưu:

```text
nominal dimension
effective dimension theo branch/toggle
finite grid-size estimate
categorical count
continuous count
inactive/nuisance parameters
startup-trial recommendation
```

Sau run, lưu:

```text
coverage theo parameter
top-decile distributions
parameter importance
best-by-seed
warm-start baseline rank
duplicate/effective-duplicate count
```

---

# Phase 33B — Robust Objective & Candidate Selection

## 1. Tách objective, constraints và selection

Không trộn mọi tiêu chí thành một scalar tùy tiện.

### Single-objective mặc định

```text
maximize Sharpe
subject to:
    num_trades >= minimum
    max_drawdown_pct <= limit
```

### Multi-objective

```text
maximize Sharpe
minimize MaxDD
minimize turnover
```

Dùng:

```text
TPE multi-objective hoặc NSGA-II
```

Không chọn tự động `pareto_first`.

---

## 2. Robust candidate selector

Thêm:

```python
CandidateSelector(
    mode="robust_plateau",
    config=RobustSelectionConfig(
        top_quantile=0.10,
        min_trades=100,
        max_drawdown_pct=15.0,
        neighborhood_radius=0.10,
        min_neighbor_count=8,
        seed_consensus=3,
    ),
)
```

Quy trình:

1. Loại failed, pruned và infeasible trials.
2. Lấy top objective quantile, không chỉ trial số một.
3. Gom candidates theo parameter neighborhood.
4. Chấm điểm:
   - median objective vùng;
   - worst-neighbor objective;
   - objective variance;
   - MDD;
   - số trades;
   - consistency giữa seeds.
5. Chọn tâm plateau, không chọn isolated spike.

Suggested robust score chỉ dùng cho **candidate selection**, không làm biến dạng objective sampler:

```text
median Sharpe vùng
- instability penalty
- drawdown penalty
```

---

## 3. Validation gate

Optimization in-sample không đủ để gọi là robust.

Candidate cuối phải qua:

```text
walk-forward folds
cost stress
slippage stress
parameter-neighborhood test
subperiod/regime test
```

Final flow:

```text
search
→ feasible Pareto/top set
→ plateau selection
→ WFO validation
→ stress validation
→ production candidate
```

Nếu candidate mới không vượt historical baseline trên validation, giữ baseline.

---

## 4. Result schema bổ sung

```python
@dataclass
class OptimizationResult:
    ...
    baseline_trials: list
    phase_results: list
    seed_results: list
    robust_candidates: list

    selected_params: dict | None
    selected_validation: dict

    search_regression: bool
    search_diagnostics: dict
```

---

# Immediate Delta-RSI profile

Trong lúc chưa implement Phase 33A–33B đầy đủ, chạy:

```python
sampler_config=SamplerConfig(
    name="tpe",
    kwargs={
        "n_startup_trials": 150,
        "multivariate": True,
        "group": True,
        "n_ei_candidates": 64,
    },
)
```

```python
OptimizationConfig(
    n_trials=1_500,
    seed=42,
    early_stopping_rounds=None,
    n_jobs=1,
)
```

Và bắt buộc enqueue:

```python
initial_trials=[
    hyhy,
    hrhr,
    hyhy_migrate_quantbt,
]
```

Chạy ít nhất 3–5 seeds. Đồng thời đổi:

```python
"degree": [1, 2, 3, 4, 5, 6]
```

để biểu diễn degree như model structure categorical thay vì giả định một quan hệ smooth.

---

# Merge gates

## Phase 33A

- [ ] Warm-start trials được evaluate trước sampled trials.
- [ ] Best feasible baseline không bị mất.
- [ ] Early stopping có `min_trials`.
- [ ] Multi-phase search chạy được.
- [ ] Multi-seed aggregation chạy được.
- [ ] Conditional search-space tests pass.
- [ ] Resume giữ warm-start/source metadata.
- [ ] Search diagnostics được persist.
- [ ] Delta-RSI test chứng minh `hyhy` được đánh giá đúng objective hiện tại.

## Phase 33B

- [ ] Formal single/multi-objective tests pass.
- [ ] Robust plateau selector không chọn isolated spike.
- [ ] Feasibility được giữ trong mọi selector.
- [ ] Multi-seed consensus tests pass.
- [ ] WFO/stress validation gate chạy được.
- [ ] Candidate mới không âm thầm thay baseline tốt hơn.
- [ ] Full test suite pass.

---

# Scope sau upgrade

> QuantBT optimization không claim luôn tìm global optimum. Framework claim: đánh giá lại mọi baseline tốt đã biết, thực hiện broad-to-local multi-seed search, hỗ trợ single/multi-objective và constraints, rồi chọn candidate theo feasibility, plateau stability và out-of-sample validation thay vì một lucky best trial.

---

## References

- QuantBT current optimization core:
  `https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/optimization/optimizer.py`

- QuantBT search-space parser:
  `https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/optimization/space.py`

- QuantBT sampler factory:
  `https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/optimization/samplers.py`

- QuantBT candidate selector:
  `https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/optimization/candidate_selection.py`

- Optuna TPESampler:
  `https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.TPESampler.html`

- Optuna Study and `enqueue_trial()`:
  `https://optuna.readthedocs.io/en/stable/reference/generated/optuna.study.Study.html`
