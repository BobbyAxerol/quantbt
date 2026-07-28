# Domain-Agnostic Optimization

QuantBT exposes a domain-agnostic Optuna layer so notebooks and services can
tune parameters without rewriting optimization boilerplate for every strategy
family.

The key design rule is simple:

```text
optimizer core knows params, objectives, constraints, sampler state
domain evaluator knows signal, intrabar intent, portfolio matrix, order package
```

This prevents a single `pos_weight`-style schema from being forced onto
strategies that have different execution meaning.

## Public Objects

```python
from quantbt import (
    OptimizationConfig,
    SamplerConfig,
    OptunaOptimizer,
    ObjectiveResult,
    ReportMetricObjective,
    SharpeObjective,
    CandidateSelector,
)
```

Evaluator adapters:

```python
from quantbt import (
    GenericEndpointEvaluator,
    PreparedSignalEvaluator,
    PreparedIntrabarEvaluator,
    PreparedPortfolioEvaluator,
    ArbitrageGenericEvaluator,
    GridDCAGenericEvaluator,
    OptionPackageGenericEvaluator,
)
```

## Objective Result

Every evaluator returns:

```python
ObjectiveResult(
    values=(sharpe,),
    metrics={
        "sharpe": 1.2,
        "max_drawdown_pct": 12.5,
        "num_trades": 100,
    },
    constraints=(),
    metadata={},
)
```

For multi-objective studies:

```python
ObjectiveResult(
    values=(sharpe, max_drawdown_pct, turnover),
)
```

with:

```python
OptimizationConfig(
    directions=("maximize", "minimize", "minimize"),
)
```

## Formal Constraints

QuantBT follows Optuna convention:

```text
constraint <= 0: feasible
constraint > 0 : violated
```

Example:

```python
from quantbt import (
    ReportMetricObjective,
    min_trades_constraint,
    max_drawdown_constraint,
)

objective = ReportMetricObjective(
    value_metrics=("sharpe",),
    constraints=(
        min_trades_constraint(100),
        max_drawdown_constraint(25.0),
    ),
)
```

This is preferred over arbitrary penalties when the domain rule can be expressed
as a formal constraint.

Metrics used by objective values or formal constraints are strict. If a metric
is missing, QuantBT raises:

```python
MissingOptimizationMetricError
```

There is no silent objective fallback such as:

```text
missing sharpe -> 0.0
missing turnover -> num_trades
```

Display metrics may be omitted from `ObjectiveResult.metrics`, but objective
and constraint metrics must exist explicitly or be derivable from certified
result fields.

Samplers without native constrained sampling support require explicit
post-filter mode:

```python
SamplerConfig(
    name="grid",
    constraint_mode="post_filter",
)
```

This is required for `random`, `grid`, and `cmaes` studies returning formal
constraints. `tpe` and `nsgaii` can pass constraints into Optuna when supported
by the installed Optuna version.

## Search Space

The optimizer keeps the same parameter style used by existing alpha notebooks:

```python
param_ranges = {
    "window": (10, 80, 2),
    "threshold": (0.1, 1.0, 0.05),
    "use_filter": [True, False],
    "mode": ["fast", "slow"],
}
```

Fixed parameters are passed separately:

```python
result = optimizer.optimize(
    param_ranges=param_ranges,
    fixed_params={"issl": True},
)
```

Fixed params are preserved in `best_params`, `selected_params`, and trial
records.

## Generic Endpoint Evaluator

Use this when a domain does not yet have a prepared fast evaluator.

```python
evaluator = GenericEndpointEvaluator(
    build_run_inputs=lambda params: {
        "data": data,
        "signal": build_signal(data, params),
        "symbols": ["BTCUSDT"],
    },
    run_func=endpoint.backtest,
    objective_builder=SharpeObjective(),
)

optimizer = OptunaOptimizer(
    evaluator=evaluator,
    config=OptimizationConfig(
        study_name="generic_signal",
        n_trials=200,
        show_progress_bar=False,
    ),
    sampler_config=SamplerConfig(name="tpe"),
)

result = optimizer.optimize(param_ranges=param_ranges)
```

Set `OptimizationConfig(seed=None)` when you intentionally want Optuna's
unseeded sampler behavior, matching `optuna.samplers.TPESampler()` defaults.
This is useful for exploratory legacy-style searches. Keep an explicit integer
seed for reproducible studies and stakeholder audit runs.

This fallback is intentionally used for early arbitrage, grid/DCA, and option
package workflows until a specialized prepared evaluator is worth adding.

## Prepared Signal Evaluator

Use this for repeated single-symbol signal-notional replays on one fixed market
tape.

```python
endpoint = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    use_funding=False,
)

prepared = endpoint.prepare_service_context(
    data=df,
    symbols=["BTCUSDT"],
)

evaluator = PreparedSignalEvaluator(
    prepared_context=prepared,
    strategy_func=lambda params: build_signal(df, params),
    objective_builder=SharpeObjective(),
)
```

Prepared contexts are run-local. They are not global caches and should not be
mutated by the strategy.

## Prepared Intrabar Evaluator

Use this for SL/TP/trailing strategies that return compact intrabar intent
columns.

```python
endpoint = QuantBTEndpoint.intrabar_bracket(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0002,
    slippage_bps=2.0,
    report_level="minimal",
)

runner = endpoint.prepare_intrabar(
    data=df,
    symbols=["BTCUSDT"],
)

def strategy(params):
    return pd.DataFrame(
        {
            "entry": signal,
            "stop_value": stop_distance,
            "take_profit_value": take_profit_distance,
            "trailing_value": trailing_distance,
        },
        index=df.index,
    )

evaluator = PreparedIntrabarEvaluator(
    runner=runner,
    strategy_func=strategy,
    objective_builder=SharpeObjective(),
    report_level="minimal",
)
```

`IntrabarIntentTape.from_frame(...)` converts the DataFrame into the certified
intrabar kernel input. It does not shift signals and does not manage strategy
look-ahead.

## Prepared Portfolio Evaluator

Use this when many position matrices are replayed against the same multi-symbol
market tape.

```python
endpoint = QuantBTEndpoint.portfolio(
    portfolio_mode="longshort",
    backend="native_portfolio",
    initial_capital=100_000,
    leverage=5,
    alloc_per_trade=1_000,
    hedge_type="signal_notional",
    fee=0.0004,
    use_funding=False,
    report_level="minimal",
)

prepared = endpoint.prepare_service_context(
    data=data_dict,
    symbols=["BTC", "ETH"],
)

evaluator = PreparedPortfolioEvaluator(
    prepared_context=prepared,
    strategy_func=lambda params: build_positions(data_dict, params),
    objective_builder=ReportMetricObjective(
        value_metrics=("sharpe", "max_drawdown_pct"),
    ),
)
```

Core accounting parity is tested against the normal endpoint path.

## Candidate Selection

Optuna's best trial is not always the production parameter set.

For single-objective constrained studies:

```python
selector = CandidateSelector(mode="feasible_best")
result = optimizer.optimize(
    param_ranges=param_ranges,
    candidate_selector=selector,
)
```

For multi-objective studies, QuantBT returns the Pareto front unless an explicit
selector is supplied. No hidden scalarization is applied.

When constraints exist and no candidate selector is supplied:

```text
result.best_params      -> raw Optuna best, useful for diagnostics
result.selected_params  -> None
```

This prevents an infeasible high-score trial from being treated as production
params. Use `CandidateSelector(mode="feasible_best")` or a domain-specific
selector when production params are required.

`CandidateSelector(mode="pareto_first")` filters infeasible Pareto trials before
selection.

## Reproducibility Safety

Phase 32 final merge rules are conservative:

```text
n_jobs must be 1
```

Parallel optimization is rejected until evaluator mutable state and duplicate
detection are certified thread-safe.

For persistent Optuna storage with `load_if_exists=True`, previous QuantBT
parameter keys are preloaded so duplicate detection still works after resume.
JSONL logs write `quantbt_full_params`, including fixed params.

## Walk-Forward Relation

Walk-forward still owns:

```text
fold generation
IS/OOS isolation
decay/SBB/flat-minima/is-only/full-sample robust selection
OOS stitching
```

Phase 32C only consolidates safe shared primitives:

```text
search-space suggestion
duplicate parameter keys
single-objective early stopping
```

Anti-leakage behavior remains locked by WFO regression tests.

## Current Scope

Supported prepared evaluators:

```text
single-symbol signal_notional native_vectorized
single-symbol intrabar bracket runner
native_portfolio prepared context
```

Generic fallback contracts:

```text
arbitrage
grid/DCA
options
any endpoint with build_run_inputs + run_func
```

Not claimed yet:

```text
specialized prepared arbitrage evaluator
specialized prepared option package evaluator
specialized prepared dynamic grid/DCA evaluator
distributed duplicate detection across independent workers
multi-objective production selector without explicit policy
```
