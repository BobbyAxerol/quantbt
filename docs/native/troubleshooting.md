# Native Companion Troubleshooting

## `poetry add quantbt-engine` did not install `quantbt-native`

The companion is intentionally platform-marked. It resolves automatically only
on Linux x86_64 glibc with CPython 3.11-3.13. Confirm the consumer environment
first:

```bash
poetry run python - <<'PY'
import importlib.metadata as metadata
from quantbt.backends._native_event_rust import probe_native_event_rust_extension

print(metadata.version("quantbt-engine"))
print(metadata.version("quantbt-native"))
print(probe_native_event_rust_extension())
PY
```

On TestPyPI, configure TestPyPI as primary and PyPI as supplemental before
running `poetry add quantbt-engine`; the full command sequence is in the
[TestPyPI release checklist](../testpypi_release_checklist.md). On unsupported
platforms, the absence of `quantbt-native` is expected and `backend="auto"`
uses Python.

## `backend="rust"` fails before execution

This is expected if the extension is missing, the core/native versions are not
an exact declared pair, or the semantic descriptor differs from the core
contract. The product descriptor also checks protocol, command/result ABI,
trace schema, strategy IR, and registry fingerprints. Use `backend="python"`
to reproduce the request with the oracle. Do not bypass the error by editing
capability flags.

## A local extension imports but a wheel does not

Run the staged verifier from a temporary directory:

```bash
python tools/verify_wheels.py --dist dist/staged --require-native
```

The check catches source-tree import leakage, incorrect package pairs, missing
Python modules in the wheel, and basic clean-install failures.

## Generated files are stale

Never hand-edit generated Python/Rust contract files. Regenerate from the
registry, then run the clean checks:

```bash
python tools/generate_native_event_contracts.py
python tools/generate_product_contracts.py
python tools/generate_public_api_inventory.py
python tools/sync_source_mirror.py --src-to-root
make test-contracts
```

## Native performance is lower than expected

Compare like for like: contract, profile, number of bars, order churn,
strategy mode, warm/cold state, and result retention. Arbitrary Python callbacks
still cross a Python boundary; native IR and batch routes have different
performance characteristics. See [Benchmarking](../performance/benchmarking.md).
