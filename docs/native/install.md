# Native Companion Installation

QuantBT has one public Python API and two release artifacts:

| Distribution | Imported by users | Responsibility |
|---|---|---|
| `quantbt-engine` | `quantbt` | endpoint, Python/Numba engines, reports, compatibility oracle |
| `quantbt-native` | never directly | internal `_quantbt_native` PyO3 extension for certified workloads |

The Python core is sufficient for all public QuantBT endpoints:

```bash
pip install quantbt-engine
```

The governed public pair is `quantbt-engine==1.1.0` with
`quantbt-native==0.4.1`. The core declares the companion as a direct,
platform-marked dependency, so a normal supported consumer command remains:

```bash
pip install quantbt-engine
# or, in a fresh Poetry project:
poetry add quantbt-engine
```

On Linux x86_64 / glibc / CPython 3.11-3.13, the resolver installs a matching
**pre-built** manylinux wheel. It is not a portable blanket acceleration, and
users never need Cargo, Rust, or Maturin to install it. The required release
order and public-index proof are maintained in the
[TestPyPI release checklist](../testpypi_release_checklist.md).

ARM64/aarch64, Alpine/musl, PyPy, and 32-bit Linux remain core-only Python
installs for this release line. Their public endpoint behavior is unchanged.

| Consumer platform | Resolver behavior | Runtime policy |
| --- | --- | --- |
| Linux x86_64 glibc, CPython 3.11-3.13 | core plus exact pre-built `quantbt-native` wheel | Rust only for governed static/IR rows; Python otherwise |
| macOS, Windows, Linux ARM64/musl, PyPy, unsupported Python | core only | Python/Numba fallback |

## Verify A Consumer Install

Run this outside the repository so a local checkout cannot shadow the wheel:

```bash
python - <<'PY'
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import quantbt

print("quantbt-engine:", version("quantbt-engine"))
print("quantbt import:", Path(quantbt.__file__).resolve())
try:
    print("quantbt-native:", version("quantbt-native"))
except PackageNotFoundError:
    print("quantbt-native: not installed; Python/Numba fallback is expected")
PY
```

Supported Linux output for this release pair contains:

```text
quantbt-engine: 1.1.0
quantbt-native: 0.4.1
```

The native package being installed does not mean every endpoint executes in
Rust. Promotion is decided per workload after version, ABI, capability,
contract, and scale checks.

## Local staged verification

From a clean release ref:

```bash
make build-core-wheel
make build-native-wheel
make verify-staged-wheels
```

The verifier checks that the core wheel has byte-identical Python modules to
`src/quantbt`, creates clean temporary environments, prevents repository-path
imports, and checks the exact core/native mapping from the product registry.

## Runtime behavior

- Missing native extension: core remains fully functional.
- `backend="python"`: always selects the reference implementation.
- `backend="rust"`: verifies the extension descriptor and fails clearly when
  the pair or workload is not compatible.
- `backend="auto"`: selects Rust only for certified static command tapes at
  10,000+ bars and bounded Native Strategy IR/batch runs at 2,000+ bars; all
  other workloads stay Python with a structured decision reason.

The direct `run_portfolio_target_market(...)` and
`run_atomic_package_market(...)` helpers are separately certified bounded Rust
contracts. They remain explicit-only: installing the companion does **not**
change the generic portfolio, basket, or arbitrage endpoint route.

For a public event-driven run, inspect the routing evidence rather than
inferring the backend from package presence:

```python
decision = result.metadata.get("native_event_promotion_v1", {})
resolved = result.metadata.get("native_event_backend_resolved")
if resolved is None:
    resolved = result.metadata.get("native_strategy_ir_execution_v1", {}).get("backend")
print(resolved)
print(decision.get("reason"))
```

Set `QUANTBT_DISABLE_NATIVE=1` to force the Python route, or
`QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` to cap local automatic promotion
without changing code. Explicit `backend="rust"` remains fail-fast.

See [Capabilities](capabilities.md), the [native release handoff](../migration/native_release_handoff.md),
and [Troubleshooting](troubleshooting.md).
