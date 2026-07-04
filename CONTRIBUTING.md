# Contributing to QuantBT

Thanks for helping make QuantBT faster, clearer, and easier to trust.

QuantBT is a research-first backtesting package, but changes must still be
reviewable and reproducible. The most valuable contributions are precise bug
reports, parity tests, execution-model improvements, documentation, examples,
and small well-tested engine changes.

## Branch Policy

- Use `dev` for all active work.
- Do not commit directly to `main`.
- Open pull requests into `dev`.
- `main` is reserved for protected, reviewed releases.
- Keep pull requests focused. Avoid mixing engine logic, docs, notebooks, and
  formatting-only changes in one PR.

## Development Setup

Clone the repository and work from the QuantBT root:

```bash
git clone https://github.com/BobbyAxerol/quantbt.git
cd quantbt
git checkout dev
```

Install the core development dependencies:

```bash
python -m pip install -U pip
python -m pip install numpy pandas numba matplotlib seaborn pytest
```

Optional Nautilus validation support:

```bash
python -m pip install nautilus-trader
```

When working inside the broader research workspace, use the parent environment
and set `PYTHONPATH` so imports resolve consistently:

```bash
PYTHONPATH=/path/to/pool_alpha pytest quantbt/tests
```

## Contribution Workflow

1. Create a feature branch from `dev`.

```bash
git checkout dev
git pull
git checkout -b feature/clear-short-name
```

2. Make the smallest coherent change.
3. Add or update tests for behavior changes.
4. Update docs or examples when the public API, sizing semantics, margin model,
   or fill policy changes.
5. Run the relevant test set.
6. Open a pull request into `dev`.

## Testing Expectations

Use the smallest test set that proves the change, then expand when touching
shared engine behavior.

```bash
pytest tests/test_endpoint.py
pytest tests/test_phase2_native_vectorized.py
pytest tests/test_phase3_native_event.py
pytest tests/test_phase5_nautilus_adapter.py
```

For changes to accounting, sizing, margin, liquidation, fees, funding, or
Nautilus parity, include at least one deterministic test with a small synthetic
dataset. Real-data tests are useful for smoke checks, but they should not be the
only proof.

## Backtest Engine Rules

Please make assumptions explicit. A good engine change should document:

- signal contract: raw weight, target unit, target notional, structural ladder,
  or explicit order intent;
- execution timing: close fill, next-bar fill, high/low limit touch, or
  event-driven order fill;
- cost model: fee convention, slippage, funding, borrow, spread, and turnover;
- account model: cash, equity, initial margin, buying power, leverage,
  maintenance margin, and liquidation;
- position model: one-way/netting, long-short, pyramiding, portfolio netting, or
  market-neutral constraints.

If two engines intentionally differ, add a parity note or test that explains
why.

## Code Style

- Prefer clear, small functions over clever abstractions.
- Keep vectorized/Numba kernels deterministic and allocation-light.
- Avoid hidden global state in engines and adapters.
- Keep public endpoint behavior stable unless the PR is explicitly a breaking
  change.
- Add comments only where they clarify non-obvious domain logic.

## Pull Request Checklist

Before opening a PR, confirm:

- The PR targets `dev`.
- The change is scoped to one topic.
- Tests were run and the command is included in the PR.
- New behavior is documented.
- Engine assumptions are explicit.
- No unrelated dirty files are included.

## Commit Messages

Use concise imperative commit messages:

```text
fix: align nautilus pct equity sizing
feat: add dca ladder limit fill audit
docs: explain margin buying power
test: cover portfolio netting modes
```

## Reporting Backtest Differences

When reporting that two backtests differ, include:

- data range, timeframe, symbol, and row count;
- endpoint/backend used;
- sizing mode and `use_pyramiding`;
- initial capital, leverage, margin settings;
- fee, slippage, funding configuration;
- expected vs actual metrics;
- first timestamp where equity, position, fill, or cash diverges.

This makes the difference debuggable instead of mysterious.
