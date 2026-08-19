# QuantBT Upgrade — Domain-Agnostic Optimization Framework

> **Mục tiêu:** Chuẩn hóa toàn bộ Optuna workflow vào QuantBT để mọi alpha chỉ khai báo search space, fixed params, evaluator và objective riêng khi cần. Framework phải dùng được cho single-symbol, intrabar, portfolio, arbitrage, grid/DCA và option engine mà không ép các domain này về cùng một output schema.

---

## 1. Quyết định kiến trúc

Không xây một `IntrabarOptimizer`.

Xây một optimizer core không biết strategy output là signal, position matrix, order plan, arbitrage package hay option package:

```text
OptunaOptimizer
    + TrialEvaluator protocol
    + domain-specific evaluator adapters
    + sampler factory
    + constraint handling
    + robust candidate selection
```

Các phần dùng chung phải nằm trong QuantBT. Alpha/project chỉ giữ:

```text
strategy_func
param_ranges
fixed_params
strategy_name
optional custom score/objective
market/profile configuration
```

Không hard-code trong QuantBT:

```text
/root/bobby/pool_alpha/...
symbol cụ thể
fee/slippage của một venue cụ thể
strategy name cụ thể
```

---

## 2. Cấu trúc module

Tạo thư mục mới tại package root:

```text
optimization/
├── __init__.py
├── config.py
├── result.py
├── space.py
├── callbacks.py
├── samplers.py
├── constraints.py
├── evaluator.py
├── evaluators/
│   ├── __init__.py
│   ├── generic.py
│   ├── signal.py
│   ├── intrabar.py
│   ├── portfolio.py
│   ├── arbitrage.py
│   ├── grid_dca.py
│   └── options.py
├── candidate_selection.py
└── optimizer.py
```

Export public API trong root `__init__.py`:

```python
from .optimization import (
    OptimizationConfig,
    SamplerConfig,
    ObjectiveResult,
    OptimizationResult,
    TrialEvaluator,
    OptunaOptimizer,
    PreparedSignalEvaluator,
    PreparedIntrabarEvaluator,
    PreparedPortfolioEvaluator,
    GenericEndpointEvaluator,
)
```

Sau khi module mới ổn định, `walkforward.py` phải import lại callbacks, search-space sampling và sampler factory từ module này, không duy trì bản copy riêng.

---

## 3. Core protocol

### 3.1 `TrialEvaluator`

```python
from typing import Protocol, Any, Mapping


class TrialEvaluator(Protocol):
    def evaluate(
        self,
        params: Mapping[str, Any],
    ) -> "ObjectiveResult":
        ...
```

Optimizer chỉ được gọi:

```python
result = evaluator.evaluate(params)
```

Optimizer không được trực tiếp biết hoặc import:

```text
IntrabarIntentTape
OptionPackageIntent
BasketSpec
GridPlan
position DataFrame
```

Các dependency domain-specific chỉ nằm trong evaluator adapter tương ứng.

---

## 4. Objective result chung

Dùng một schema hỗ trợ single-objective, multi-objective và constraints:

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ObjectiveResult:
    values: tuple[float, ...]

    metrics: dict[str, float] = field(
        default_factory=dict
    )

    # Optuna convention:
    # value <= 0: feasible
    # value > 0: constraint violated
    constraints: tuple[float, ...] = ()

    metadata: dict[str, Any] = field(
        default_factory=dict
    )
```

### Single-objective Sharpe

```python
return ObjectiveResult(
    values=(sharpe,),
    metrics={
        "sharpe": sharpe,
        "max_drawdown_pct": mdd,
        "trades": trades,
    },
)
```

### Multi-objective portfolio

```python
return ObjectiveResult(
    values=(
        sharpe,
        max_drawdown_pct,
        turnover,
    ),
    metrics=metrics,
)
```

Cấu hình study:

```python
directions=(
    "maximize",
    "minimize",
    "minimize",
)
```

### Constraints

```python
return ObjectiveResult(
    values=(sharpe,),
    metrics=metrics,
    constraints=(
        margin_utilization - 0.80,
        rejection_rate - 0.02,
        abs_net_delta - delta_limit,
    ),
)
```

Không dùng penalty tùy tiện như:

```python
score = sharpe - 1000 * violation
```

khi constraint có thể biểu diễn chính thức.

---

## 5. Configuration

### 5.1 `OptimizationConfig`

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OptimizationConfig:
    study_name: str
    n_trials: int = 300

    directions: tuple[str, ...] = (
        "maximize",
    )

    seed: int = 42
    n_jobs: int = 1

    early_stopping_rounds: int | None = None
    early_stopping_min_delta: float = 1e-4

    show_progress_bar: bool = True

    storage: str | None = None
    load_if_exists: bool = True

    log_path: str | Path | None = None

    duplicate_policy: str = "prune"
    exception_policy: str = "raise"

    def __post_init__(self):
        if self.n_trials <= 0:
            raise ValueError("n_trials must be positive")

        if not self.directions:
            raise ValueError(
                "at least one direction is required"
            )

        invalid = set(self.directions) - {
            "maximize",
            "minimize",
        }
        if invalid:
            raise ValueError(
                f"invalid directions: {invalid}"
            )

        if self.n_jobs <= 0:
            raise ValueError(
                "n_jobs must be positive"
            )
```

Mặc định `n_jobs=1` để kết quả reproducible. Parallel/distributed optimization là opt-in.

### 5.2 `SamplerConfig`

```python
@dataclass(frozen=True)
class SamplerConfig:
    name: str = "tpe"
    kwargs: dict = field(
        default_factory=dict
    )
```

---

## 6. Search-space specification

Giữ tương thích với style alpha hiện tại:

```python
param_ranges = {
    "bbLen": (10, 80, 2),
    "bbMult": (1.5, 5.0, 0.1),
    "use_trailing": [True, False],
}
```

Tạo:

```python
def suggest_parameter(
    trial,
    name,
    spec,
):
    if (
        isinstance(spec, (list, tuple))
        and len(spec) == 2
        and set(spec) == {True, False}
    ):
        return trial.suggest_categorical(
            name,
            [True, False],
        )

    if (
        isinstance(spec, tuple)
        and len(spec) == 3
        and all(
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            for x in spec
        )
    ):
        low, high, step = spec

        if all(
            isinstance(x, int)
            and not isinstance(x, bool)
            for x in spec
        ):
            return trial.suggest_int(
                name,
                int(low),
                int(high),
                step=int(step),
            )

        return trial.suggest_float(
            name,
            float(low),
            float(high),
            step=float(step),
        )

    if isinstance(spec, range):
        return trial.suggest_categorical(
            name,
            list(spec),
        )

    if (
        isinstance(spec, (list, tuple))
        and len(spec) > 0
    ):
        return trial.suggest_categorical(
            name,
            list(spec),
        )

    raise ValueError(
        f"unsupported spec for {name}: {spec}"
    )
```

Fixed params luôn override:

```python
def suggest_params(
    trial,
    param_ranges,
    fixed_params=None,
):
    fixed_params = dict(
        fixed_params or {}
    )

    params = {}

    for name, spec in param_ranges.items():
        if name in fixed_params:
            params[name] = fixed_params[name]
        else:
            params[name] = suggest_parameter(
                trial,
                name,
                spec,
            )

    for name, value in fixed_params.items():
        params.setdefault(name, value)

    return params
```

Bỏ `use_fixed_params`. Có dictionary thì tự động dùng; `None` hoặc `{}` thì không override.

---

## 7. Sampler support

### 7.1 Phase 1 bắt buộc

Support chính thức:

```text
tpe
random
grid
cmaes
nsgaii
```

#### TPE — default

Phù hợp mixed/conditional spaces:

```python
SamplerConfig(
    name="tpe",
    kwargs={
        "n_startup_trials": 30,
        "multivariate": True,
        "group": True,
    },
)
```

Không truyền các Optuna arguments đã deprecated.

#### Random — baseline

Dùng để:

```text
smoke test
search-space audit
baseline so với TPE
reproducible exploration
```

#### Grid — exhaustive finite space

Chỉ dùng khi Cartesian product nhỏ. Factory phải estimate grid size và warning/reject nếu vượt threshold.

#### CMA-ES — continuous refinement

Chỉ dùng khi search space không còn categorical/conditional params.

Recommended workflow:

```text
TPE mixed global search
→ cố định categorical structure
→ CMA-ES refine continuous params
```

Nếu chọn CMA-ES với boolean/string categorical params, phải raise trước khi tạo study.

#### NSGA-II — Pareto optimization

Dùng cho:

```text
maximize Sharpe
minimize MaxDD
minimize turnover
```

và constrained portfolio/options optimization.

### 7.2 Phase 2

Thêm sau:

```text
qmc
gp
nsgaiii
```

- QMC: phủ đều continuous space ban đầu.
- GP: trial đắt, số chiều thấp, option/high-fidelity validation.
- NSGA-III: chỉ cho many-objective use cases.

### 7.3 Sampler factory

```python
def build_sampler(
    sampler_config,
    *,
    seed,
    search_space,
    objective_count,
    constraints_func=None,
):
    ...
```

Factory phải validate compatibility:

```text
CMA-ES + categorical -> reject
Grid + dynamic space -> reject
single-objective callback + multi-objective -> reject
unsupported constraints sampler -> reject
```

---

## 8. Callbacks và state

### 8.1 Single-objective early stopping

Dùng best-value stagnation:

```python
class SingleObjectiveEarlyStopping:
    def __init__(
        self,
        patience,
        direction,
        min_delta=1e-4,
    ):
        ...
```

Không tính failed/pruned trials vào patience.

Chỉ bật khi:

```text
objective_count == 1
early_stopping_rounds < n_trials
```

### 8.2 Multi-objective

Phase 1:

```text
không early-stop multi-objective
```

Không dùng `study.best_value`, vì multi-objective có Pareto front.

Phase 2 mới thêm hypervolume-stagnation callback.

### 8.3 Logging

Dùng JSONL:

```json
{
  "trial": 41,
  "values": [1.93],
  "params": {},
  "metrics": {},
  "constraints": [],
  "duration_seconds": 0.18
}
```

Single objective:

```text
log khi best trial thay đổi
```

Multi-objective:

```text
log completed trials
và snapshot Pareto front định kỳ
```

Đường dẫn log được truyền qua config, không hard-code.

### 8.4 Duplicate handling

Không dùng `DuplicatePruner` dựa trên `BasePruner`.

Xử lý trực tiếp trước evaluator:

```python
key = stable_params_key(params)

if key in seen_params:
    raise optuna.TrialPruned(
        "duplicate parameter set"
    )

seen_params.add(key)
```

Với persistent/distributed storage, in-memory set không đủ. Phase 1 hỗ trợ process-local duplicate detection; persistent duplicate detection phải dùng study storage/user attrs hoặc canonical trial lookup.

---

## 9. Domain-specific evaluators

### 9.1 `PreparedSignalEvaluator`

Dùng cho single-symbol close-target/vectorized:

```text
strategy_func(params) -> signal
prepared signal context -> result
metric extractor -> ObjectiveResult
```

### 9.2 `PreparedIntrabarEvaluator`

Dùng cho:

```text
entry
SL
TP
trailing
exit_long
exit_short
```

Flow:

```python
alpha_frame = strategy_func(
    data,
    params,
)

intent = intent_builder(
    alpha_frame,
)

result = runner.run(
    intent,
    report_level="minimal",
)

return objective_builder(
    result,
    params,
)
```

`IntrabarIntentTape.from_frame()` nên được thêm để bỏ adapter lặp ở mỗi alpha.

### 9.3 `PreparedPortfolioEvaluator`

Dùng prepared native-portfolio context:

```text
strategy_func(params) -> positions/weights matrix
prepared context -> portfolio result
metrics -> ObjectiveResult
```

Metrics tùy chọn:

```text
Sharpe
MaxDD
turnover
gross/net exposure
concentration
beta drift
margin utilization
```

### 9.4 `ArbitrageEvaluator`

Không ép arbitrage về portfolio output.

Evaluator nhận output/domain adapter riêng:

```python
@dataclass(frozen=True)
class ArbitrageTrialOutput:
    signal: object
    hedge_ratios: object | None = None
    run_overrides: dict = field(
        default_factory=dict
    )
```

Metrics:

```text
package PnL
hedge drift
leg imbalance
package rejection rate
funding carry
margin utilization
```

Schema-only arbitrage specs phải fail-fast hoặc route sang specialized evaluator.

### 9.5 `GridDCAEvaluator`

Dùng structural levels/order plan, không target weights.

Metrics:

```text
grid fills
safety-order count
inventory duration
capital utilization
liquidation
turnover
```

### 9.6 `OptionPackageEvaluator`

Không import option package types vào optimizer core.

Evaluator riêng quản lý:

```text
chain
instrument registry
package builder
option prepared cache
hedging
settlement
margin
Greeks
multi-currency ledger
```

Metrics/constraints có thể gồm:

```text
Sharpe
MaxDD
margin utilization
package rejection rate
delta/vega/gamma exposure
hedging turnover
settlement PnL
liquidity violations
```

### 9.7 `GenericEndpointEvaluator`

Bắt buộc có để không chặn backend/branch mới:

```python
class GenericEndpointEvaluator:
    def __init__(
        self,
        build_run_inputs,
        run_func,
        objective_builder,
    ):
        ...
```

Flow:

```python
run_inputs = build_run_inputs(params)
result = run_func(**run_inputs)
return objective_builder(
    result,
    params,
)
```

Các domain chưa có prepared fast evaluator vẫn chạy được qua generic fallback.

---

## 10. Constraints

Tạo helper:

```python
CONSTRAINTS_USER_ATTR = (
    "quantbt_constraints"
)
```

Trong objective wrapper:

```python
trial.set_user_attr(
    CONSTRAINTS_USER_ATTR,
    result.constraints,
)
```

Sampler factory truyền:

```python
def constraints_func(
    frozen_trial,
):
    return frozen_trial.user_attrs.get(
        CONSTRAINTS_USER_ATTR,
        (),
    )
```

Các evaluator tự định nghĩa constraint values; optimizer chỉ lưu/chuyển tiếp.

Không prune trial chỉ vì infeasible nếu sampler hỗ trợ constrained optimization. Vẫn lưu trial để sampler học feasible region.

---

## 11. Pruning

### Full-history evaluator

Default:

```text
NopPruner
```

Một backtest chỉ có final metric, không tạo intermediate values giả.

### Walk-forward evaluator

Có thể report sau từng fold:

```python
trial.report(
    cumulative_score,
    step=fold_index,
)

if trial.should_prune():
    raise optuna.TrialPruned()
```

Support:

```text
MedianPruner
SuccessiveHalvingPruner
HyperbandPruner
```

Chỉ bật khi evaluator implements intermediate reporting.

### Option/scenario evaluator

Có thể report sau:

```text
expiry bucket
regime
stress scenario
```

nhưng phải chứng minh intermediate score có ý nghĩa so sánh.

---

## 12. Candidate selection

Không đồng nhất:

```text
Optuna best trial
```

với:

```text
production parameter set
```

Tách:

```text
Sampler
→ trial records
→ feasibility filter
→ robust candidate selector
→ final selected params
```

Tái sử dụng logic robust selection hiện có trong walk-forward:

```text
plateau robustness
temporal consistency
minimum trades
fold stability
cost robustness
parameter-neighborhood stability
```

Public interface:

```python
selector = CandidateSelector(
    mode="plateau_robust",
    config=...,
)

selected = selector.select(
    optimization_result,
)
```

Multi-objective:

```text
Pareto front
→ feasibility
→ normalization
→ domain policy/selector
```

Không tự động chọn một Pareto trial khi chưa có selection policy.

---

## 13. `OptunaOptimizer`

Core flow:

```python
class OptunaOptimizer:
    def __init__(
        self,
        *,
        evaluator,
        config,
        sampler_config,
    ):
        ...

    def optimize(
        self,
        *,
        param_ranges,
        fixed_params=None,
        candidate_selector=None,
    ) -> OptimizationResult:
        ...
```

Objective wrapper phải:

1. Suggest params.
2. Merge fixed params.
3. Detect duplicate.
4. Call evaluator.
5. Validate finite objective values.
6. Validate objective count.
7. Save metrics, constraints, metadata.
8. Return float hoặc tuple cho Optuna.

Không catch generic exceptions rồi return 0.

Policies:

```text
raise: code bug dừng study
fail_trial: selected known exceptions become failed trial
prune: only explicit invalid candidate conditions
```

---

## 14. Result schema

```python
@dataclass
class OptimizationResult:
    study: object

    best_params: dict | None
    best_values: tuple[float, ...] | None

    pareto_trials: list
    trials: list
    trials_frame: object

    selected_params: dict | None = None
    selection_metadata: dict = field(
        default_factory=dict
    )
```

Single objective:

```text
best_params/best_values available
```

Multi-objective:

```text
pareto_trials available
best_params remains None
until CandidateSelector selects one
```

---

## 15. Public usage

### Intrabar single-objective

```python
evaluator = PreparedIntrabarEvaluator(
    data=data_eth,
    runner=runner,
    strategy_func=(
        generate_bollinger_squeeze_signals
    ),
    objective_builder=(
        SharpeObjective(
            trading_days=365,
            min_trades=100,
        )
    ),
)

optimizer = OptunaOptimizer(
    evaluator=evaluator,
    config=OptimizationConfig(
        study_name=strategy_name,
        n_trials=600,
        directions=("maximize",),
        early_stopping_rounds=100,
        storage="sqlite:///optuna.db",
        log_path="logs/strategy.jsonl",
    ),
    sampler_config=SamplerConfig(
        name="tpe",
        kwargs={
            "n_startup_trials": 30,
            "multivariate": True,
            "group": True,
        },
    ),
)

optimization = optimizer.optimize(
    param_ranges=param_ranges,
    fixed_params=fixed,
)
```

### Portfolio multi-objective

```python
optimizer = OptunaOptimizer(
    evaluator=portfolio_evaluator,
    config=OptimizationConfig(
        study_name="vn_portfolio",
        n_trials=1000,
        directions=(
            "maximize",
            "minimize",
            "minimize",
        ),
    ),
    sampler_config=SamplerConfig(
        name="nsgaii",
    ),
)
```

### Custom alpha objective

Alpha chỉ override objective builder:

```python
def custom_objective(
    result,
    params,
):
    report = result.full_report(
        trading_days=365
    )

    return ObjectiveResult(
        values=(
            float(report["sharpe"])
            - 0.02
            * float(
                report[
                    "max_drawdown_pct"
                ]
            ),
        ),
        metrics={
            "sharpe": report["sharpe"],
            "max_drawdown_pct": (
                report[
                    "max_drawdown_pct"
                ]
            ),
        },
    )
```

Optimizer/evaluator infrastructure không thay đổi.

---

## 16. Performance requirements

1. Prepared evaluator phải prepare market data đúng một lần.
2. Mỗi trial không rebuild funding masks, instrument profiles hoặc OHLCV arrays.
3. `report_level="minimal"` trong optimization.
4. Không tạo fill ledger/trade DataFrame trừ objective thật sự cần.
5. Thêm fast metrics path sau:

```python
runner.run_metrics(
    intent,
    metrics=(
        "sharpe",
        "max_drawdown_pct",
        "number_of_trades",
    ),
)
```

6. Benchmark optimizer overhead riêng khỏi backtest runtime.
7. Sampler overhead phải được ghi trong benchmark với fast kernels.
8. Không `n_jobs>1` mặc định; benchmark parallel riêng.

---

## 17. Tests bắt buộc

### Core

```text
test_single_objective_result
test_multi_objective_result
test_constraint_storage
test_fixed_params_override
test_search_space_specs
test_duplicate_pruning
test_nonfinite_objective_pruned
test_exception_policy_raise
```

### Samplers

```text
test_tpe_factory
test_random_factory
test_grid_factory
test_cmaes_rejects_categorical
test_nsgaii_multiobjective
test_constraints_func_propagation
test_sampler_seed_reproducibility
```

### Callbacks

```text
test_single_objective_early_stopping
test_pruned_trials_do_not_consume_patience
test_multiobjective_rejects_single_best_callback
test_jsonl_logger
```

### Evaluators

```text
test_prepared_signal_evaluator
test_prepared_intrabar_evaluator
test_prepared_portfolio_evaluator
test_generic_endpoint_evaluator
test_arbitrage_adapter
test_grid_dca_adapter
test_option_adapter_contract
```

### Parity

```text
normal endpoint == prepared evaluator
minimal == audit core accounting
old walkforward sampling == new search-space sampling
existing robust candidate selection preserved
```

### Integration

```text
single-symbol TPE optimization
intrabar TPE optimization
portfolio NSGA-II optimization
constrained optimization
persistent SQLite resume
custom objective override
```

---

## 18. Migration plan

### Phase A — Core extraction

1. Create `optimization/`.
2. Move/copy shared utilities from `walkforward.py`.
3. Add compatibility imports.
4. Keep existing WFO behavior unchanged.

### Phase B — Core optimizer

1. Implement config/result/search space.
2. Implement TPE and Random.
3. Implement single-objective flow.
4. Add JSONL logging and early stopping.

### Phase C — Evaluators

1. Generic endpoint.
2. Prepared signal.
3. Prepared intrabar.
4. Prepared portfolio.

### Phase D — Multi-objective/constraints

1. Extend `ObjectiveResult`.
2. Add NSGA-II.
3. Add constrained sampling.
4. Add Pareto result handling.

### Phase E — Additional samplers

1. Grid.
2. CMA-ES.
3. Compatibility validation.
4. Optional QMC/GP later.

### Phase F — Domain adapters

1. Arbitrage.
2. Grid/DCA.
3. Options.
4. Specialized branch adapters through generic fallback first.

### Phase G — Walk-forward consolidation

1. Replace duplicate utilities in `walkforward.py`.
2. Keep anti-leakage folds and robust selectors there.
3. Reuse new optimizer core.
4. Verify historical WFO regression tests.

---

## 19. Merge gates

Chỉ merge khi:

- [ ] Existing walk-forward tests pass.
- [ ] Existing endpoint tests pass.
- [ ] Single and multi-objective studies pass.
- [ ] Constraint semantics pass.
- [ ] TPE, Random, Grid, CMA-ES and NSGA-II factory tests pass.
- [ ] CMA-ES rejects incompatible mixed spaces.
- [ ] Prepared signal/intrabar/portfolio parity passes.
- [ ] Generic evaluator can run arbitrage/options fallback.
- [ ] No generic exception is silently converted to score 0.
- [ ] Multi-objective does not use `study.best_value`.
- [ ] JSONL logs are reproducible and parseable.
- [ ] SQLite resume test passes.
- [ ] Optimizer overhead benchmark is recorded.
- [ ] Documentation and examples are updated.

---

## 20. Scope statement

Phase 1 certification:

> **Domain-agnostic Optuna orchestration with prepared evaluators for signal, intrabar and portfolio; generic fallback for other QuantBT endpoints; single/multi-objective studies, constraints and robust candidate selection.**

Do not claim every domain has the same prepared performance path. Arbitrage, grid/DCA and options may initially use `GenericEndpointEvaluator`, then receive specialized prepared evaluators independently without changing optimizer core.

---

## 21. Reference sources

- QuantBT `dev` repository and current endpoint/prepared-context architecture:
  `https://github.com/BobbyAxerol/quantbt/tree/dev`

- QuantBT current walk-forward implementation:
  `https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/walkforward.py`

- QuantBT current endpoint implementation:
  `https://raw.githubusercontent.com/BobbyAxerol/quantbt/dev/endpoint.py`

- Optuna sampler reference:
  `https://optuna.readthedocs.io/en/stable/reference/samplers/index.html`

- Optuna TPE:
  `https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.TPESampler.html`

- Optuna NSGA-II:
  `https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.NSGAIISampler.html`

- Optuna multi-objective and constraints:
  `https://optuna.readthedocs.io/en/stable/tutorial/20_recipes/002_multi_objective.html`



# UPDATE Bổ sung sau phase 32C:
## Phase 32 — Final Merge Blockers

## 1. Strict objective metrics

Không được trả `0.0` khi objective hoặc constraint metric không tồn tại.

Sửa:

```text
missing Sharpe / MaxDD / turnover / margin / rejection rate
→ raise MissingOptimizationMetricError
```

Bỏ hoàn toàn fallback:

```text
turnover = num_trades
```

`turnover` chỉ được lấy từ turnover thực. Các metric chỉ dùng để hiển thị có thể optional; metric dùng làm objective hoặc constraint phải bắt buộc tồn tại.

Thêm tests:

```text
test_missing_objective_metric_raises
test_missing_constraint_metric_raises
test_turnover_does_not_fallback_to_trade_count
```

## 2. Constraint-safe candidate selection

Khi có constraints, không được tự gán:

```python
selected_params = study.best_params
```

vì raw best trial có thể infeasible.

Quy tắc:

```text
no constraints:
    selected_params = raw best

has constraints:
    selected_params = best feasible trial
    hoặc None nếu không có candidate selector
```

`pareto_first` cũng phải loại trial infeasible.

Với sampler không hỗ trợ constrained sampling (`random`, `grid`, `cmaes`), yêu cầu khai báo rõ:

```text
constraint_mode="post_filter"
```

Nếu không khai báo thì raise, không âm thầm bỏ qua constraints.

Thêm tests:

```text
test_infeasible_highest_score_not_selected
test_pareto_selector_filters_infeasible_trials
test_unsupported_constraint_sampler_requires_post_filter
test_no_feasible_trial_returns_no_selected_params
```

## 3. Parallel, resume và reproducibility safety

Phase hiện tại nên fail-fast:

```python
if n_jobs != 1:
    raise NotImplementedError(
        "parallel optimization is not certified"
    )
```

Lý do: `_seen_params` và evaluator `last_result/last_intent` là mutable state chưa thread-safe.

Ngoài ra:

* Reset `_seen_params` khi bắt đầu một study mới.
* Khi `load_if_exists=True`, preload parameter keys từ các trial cũ để duplicate detection hoạt động sau resume.
* JSONL logger phải ghi `quantbt_full_params`, bao gồm cả fixed params, không chỉ `trial.params`.

Thêm tests:

```text
test_parallel_mode_rejected_until_thread_safe
test_duplicate_detection_after_sqlite_resume
test_repeated_optimize_does_not_reuse_stale_seen_set
test_jsonl_contains_fixed_and_search_params
```

## Merge gate

Chạy:

```bash
pytest -q \
  tests/test_optimization_core.py \
  tests/test_optimization_samplers.py \
  tests/test_optimization_evaluators.py \
  tests/test_optimization_integration.py

pytest -q
```

Chỉ merge khi toàn bộ pass.

Sau các sửa trên, scope có thể được chứng nhận là:

> Domain-agnostic optimization framework trustable cho prepared signal, prepared intrabar, prepared portfolio và generic fallback; chưa claim specialized prepared evaluator cho arbitrage, grid/DCA hoặc options.
