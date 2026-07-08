# WalkForwardEngine Phase Plan

Date: 2026-07-08
Branch: dev

This is the agreed implementation plan for upgrading QuantBT with an
institutional-grade, transparent WalkForwardEngine while staying compatible
with the current QuantBT endpoints.

## Design Principles

- Do not replace existing backtest engines.
- Walk-forward owns split, train/validation orchestration, OOS stitching,
  objective scoring, robustness selection, and reporting.
- Existing QuantBT endpoints own the final backtest simulation.
- OOS positions/signals must be stitched into one continuous timeline and then
  backtested once, so boundary trades, fees, slippage, funding, and margin are
  accounted for by the same engine used in normal research.
- Numba belongs in repeated numeric loops such as metrics, bootstrap,
  Monte Carlo, and simulation kernels. Config, pandas alignment, reports, and
  strategy adapters stay in Python.
- All stochastic logic must expose seed/config/data/kernel metadata for audit.

## Phase 1 - Split, Stitch, Endpoint Contract

Status: implemented.

Goal:

- Add the stable public integration surface and correctness foundation.

Scope:

- `QuantBTEndpoint.walk_forward(...)` factory.
- `WalkForwardEngine` with expanding/rolling split generation.
- Yearly, semi-yearly, and quarterly OOS windows.
- Strategy callable/class adapter returning OOS signal/position output.
- OOS stitcher for Series, DataFrame, or `{symbol: Series}` outputs.
- Final single-run backtest routing through existing QuantBT paths:
  `signal_notional`, `%_equity`, `dca_ladder`, explicit orders later,
  portfolio, basket, and supported arbitrage specs.
- Traceback-friendly fold table and metadata.

Tests:

- No lookahead split invariants.
- OOS stitch preserves fold boundaries.
- Boundary position changes are represented in the stitched signal.
- Compatibility smoke tests for `signal_notional`, `%_equity`, portfolio, and
  currently supported arbitrage package specs.

## Phase 2 - Objective Mode 1 And Optuna Basics

Status: implemented in the Phase 2 foundation.

Goal:

- Run real optimization over WFO folds with transparent decay scoring.

Scope:

- Parameter range parser and Optuna trial sampler.
- Duplicate trial pruning.
- Early stopping callback.
- `mode_1_decay` objective:
  `mean_oos_sharpe - lambda * std(decay) - gamma * max(0, mean(decay))`.
- Per-fold IS/OOS metrics.
- Trial ledger with params, objective components, data hash, config hash, seed.

Implemented notes:

- `optimization_mode="mode_1_decay"` is available through
  `QuantBTEndpoint.walk_forward(...)`.
- The optimizer uses transparent return-proxy scoring on strategy output for
  IS/OOS fold metrics, then runs the final stitched QuantBT backtest once with
  the selected params.
- `trial_table`, `best_trial`, `fold_table`, data hash, config hash, and random
  seed are exposed in `result.metadata["walk_forward"]`.
- Bootstrap/SBB and flat-minima are intentionally left for Phase 3.

Tests:

- Synthetic strategy with known robust parameter.
- Duplicate-pruner behavior.
- Early-stopping behavior.
- Objective component audit.

## Phase 3 - Robust Objectives And Numba Compute Helpers

Status: implemented in the Phase 3 foundation.

Goal:

- Add robustness tools without turning the engine into a black box.

Scope:

- `mode_2_sbb` stationary block bootstrap objective.
- `mode_3_flat_minima` top-trial clustering with centroid/medoid selection.
- Numba metric/bootstrap kernels where profiling shows repeated numeric loops.
- Seeded reproducibility for bootstrap/Monte Carlo.
- Fallback to Python/NumPy baseline for debug.

Implemented notes:

- `optimization_mode="mode_2_sbb"` runs Optuna over parameter ranges and scores
  each trial with seeded stationary block bootstrap on the train-fold return
  proxy.
- `optimization_mode="mode_3_flat_minima"` scores trials with the decay
  objective, clusters top trials in normalized parameter space, and selects the
  medoid of the densest stable cluster when available.
- Repeated score/turnover and bootstrap-Sharpe loops use optional numba kernels.
  If numba is unavailable, the Python/NumPy baseline path is used.
- `numba_enabled` and selector/bootstrap metadata are exposed in
  `result.metadata["walk_forward"]`.

Tests:

- Bootstrap reproducibility with fixed seed: implemented.
- Flat-minima selector chooses the stable cluster, not a sharp isolated peak:
  implemented.
- Numeric equivalence between Python/NumPy and numba/fallback helpers:
  implemented.

## Phase 4 - Production Hardening

Goal:

- Make WalkForwardEngine safe to use as a shared research engine.

Scope:

- Benchmark suite with cold/warm Numba timing.
- Performance regression checks.
- Full docs and examples.
- Clear error messages for strategy adapter/data/param issues.
- Compatibility matrix for all current QuantBT routes.
- Reserved hooks for future arbitrage Phase I+ and Nautilus parity upgrades.

Tests:

- Full endpoint compatibility.
- Invariant tests.
- Reproducibility tests.
- Performance baseline snapshots.

## Arbitrage Compatibility Note

Current supported arbitrage specs should be routable through walk-forward as
stitched OOS signal series. Specialized arbitrage engines that are schema-only
today should remain traceable and fail clearly until their engines are added.
