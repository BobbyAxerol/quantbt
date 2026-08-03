# Phase 46C: Import Graph And RSS Floor

Phase 46C makes the core `quantbt-engine` import independent from optional
visualization, optimization, reporting, and Nautilus packages. The source
layout remains `src/quantbt`, while the root compatibility mirror remains
present and is checked byte-for-byte during this packaging transition.

## Dependency contract

The core distribution contains only:

- `numpy`;
- `pandas`;
- `numba`.

Optional capabilities are owned by explicit extras:

| Extra | Capability | Main dependencies |
| --- | --- | --- |
| `viz` | `quick_plot`, `tearsheet`, themes | matplotlib, seaborn |
| `optimization` | Optuna and robust search helpers | optuna, arch, scikit-learn |
| `reports` | QuantStats report integration | quantstats |
| `validation` | Nautilus validation adapter | nautilus-trader |
| `native` | Reserved for the separately published native wheel | empty until release |

`all` is a convenience extra. It does not change the core import contract.

## Lazy public API

The package keeps core engines, schemas, execution contracts, and metrics
eagerly importable. Public optional names remain available through
`quantbt.__getattr__`, so existing imports continue to work after their
corresponding extra is installed:

```python
from quantbt import QuantBTEndpoint

# Loads visualization dependencies only when the symbol is used.
from quantbt import quick_plot

# Loads Optuna only when optimization is requested.
from quantbt import OptunaOptimizer
```

The lazy resolver caches the resolved object in the package namespace. This
preserves identity with direct module imports, for example
`quantbt.quick_plot is quantbt.viz.quick_plot`, and Python's import lock
provides safe concurrent first-load behavior.

## Fresh-process gate

Run from the repository root:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase46c_import_rss.py \
  --output benchmarks/native_event/phase46c_import_rss.json
```

The child process runs from `/tmp`, preventing the root mirror from shadowing
the distribution source. The gate records current RSS after `import quantbt`,
RSS after resolving the core `QuantBTEndpoint`, the module count, forbidden
optional modules, and `python -X importtime` summary lines. These values are
an import/process floor only; they are not a claim about prepared or execution
RSS, which remains covered by the Phase 46B staged benchmark.

The local packaging gate also builds both artifacts with the pinned build
toolchain and imports the wheel from a target directory with `--no-deps`.
The wheel metadata contains only NumPy, pandas, and Numba as unconditional
requirements; optional requirements are guarded by their extra markers. The
sdist contains the `src/quantbt` package and the same `0.1.0` metadata.

## Acceptance criteria

Phase 46C is accepted when:

1. `import quantbt` succeeds with core dependencies and does not import
   matplotlib, seaborn, Optuna, Nautilus, or QuantStats.
2. Core public exports and lazy optional exports remain accessible and retain
   direct-import identity.
3. Metadata and `uv.lock` agree that visualization/reporting/optimization/
   validation dependencies are optional.
4. The source mirror is byte-identical to `src/quantbt` for every mirrored
   module.
5. Focused import tests and the full regression suite pass.

Evidence from the current host:

```text
fresh source import: 0 forbidden optional modules
fresh source import RSS: 188,170,240 bytes
wheel import: pass, 0 forbidden optional modules
wheel: quantbt_engine-0.1.0-py3-none-any.whl
sdist: quantbt_engine-0.1.0.tar.gz
full regression: 648 passed, 3 skipped
```

The next planned phase is 46D: ownership separation for market tape memory and
Rust hot state. It is intentionally not included in this import-graph change.
