# Native Companion Installation

The Python core is sufficient for all public QuantBT endpoints:

```bash
pip install quantbt-engine
```

`quantbt-native` is currently a staged, unpublished companion. It is built and
verified from the exact release source only. Do not assume a locally compiled
extension is portable or eligible for `backend="auto"`.

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
- `backend="auto"`: remains Python-first in version 1.0.8.

See [Capabilities](capabilities.md) and [Troubleshooting](troubleshooting.md).
