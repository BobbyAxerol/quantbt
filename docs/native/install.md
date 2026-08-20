# Native Companion Installation

The Python core is sufficient for all public QuantBT endpoints:

```bash
pip install quantbt-engine
```

`quantbt-native` is currently a staged, unpublished companion. It is built and
verified from the exact release source only. A locally compiled extension is
eligible for `backend="auto"` only for the certified Stage-B rows in the
generated compatibility table; it is not a portable blanket acceleration.

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

Set `QUANTBT_DISABLE_NATIVE=1` to force the Python route, or
`QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` to cap local automatic promotion
without changing code. Explicit `backend="rust"` remains fail-fast.

See [Capabilities](capabilities.md) and [Troubleshooting](troubleshooting.md).
