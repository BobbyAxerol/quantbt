# Native Release Handoff

This guide is the release-facing contract for the governed
`quantbt-native` companion. It supplements the generated
[compatibility table](../contracts/generated_product_compatibility.md); the
generated registry remains the executable source of truth.

## What Is Released

`quantbt-engine` is a complete Python package. It installs and runs every
public endpoint without native code on unsupported platforms. The governed
public pair is `quantbt-engine==1.0.10` and `quantbt-native==0.4.1`: supported
Linux x86_64 / glibc / CPython 3.11-3.13 consumers receive the exact pre-built
companion through the core's direct platform dependency. No consumer compiles
Rust during installation.

The public consumer contract is intentionally ordinary:

```bash
poetry add quantbt-engine
```

On the supported matrix this resolves the exact companion; elsewhere it keeps
the same Python endpoint surface without attempting a source build.

The root-level module/package set (`endpoint.py`, `backends/`, `core/`, and
related mirror entries) is retained as a byte-identity-gated Pool Alpha
compatibility mirror. `src/quantbt/` is the wheel source. Do not delete the
mirror, edit both trees, or treat a root-tree import as installed-wheel proof.

## Runtime Route Matrix

| Workload | `backend="auto"` with matching native wheel | Default elsewhere |
|---|---|---|
| Static V2/V3 command tape, at least 10,000 bars | Rust | Python |
| Bounded Native Strategy IR, batch, causal-fold score, at least 2,000 bars | Rust | Python |
| Direct `run_portfolio_target_market(...)` | Explicit Rust helper only | Not a generic endpoint route |
| Direct `run_atomic_package_market(...)` | Explicit Rust helper only | Not a generic endpoint route |
| Callback, reactive, generic portfolio/basket/arbitrage, unsupported account/contract | Python | Python |

The bounded E4/E5 helpers cover linear quote-settled gross-cross `target_units`
and one same-bar all-or-none market package. They do not certify target weight
or notional allocation, risk parity, cross-margin, partial fills, queue/depth,
cross-venue settlement, or general arbitrage semantics.

## Deterministic Controls

```python
# Always run the Python oracle/fallback.
QuantBTEndpoint.event_driven(backend="python", ...)

# Require a compatible native wheel and fail closed otherwise.
QuantBTEndpoint.event_driven(backend="rust", ...)
```

```bash
# Emergency local rollback for auto routing.
export QUANTBT_DISABLE_NATIVE=1

# Keep an installed companion but prohibit automatic promotion.
export QUANTBT_NATIVE_PROMOTION_MAX=explicit_only
```

Every eligible result records the resolved backend, policy-table version and
fallback reason in execution metadata. An internal Rust failure is not silently
replayed by Python.

## Reproduce A Candidate Gate

Run from the exact clean release commit. These commands build local artifacts;
they do not tag, publish, or modify public releases.

```bash
make test-contracts
make test-rust-unit
make build-core-wheel
make build-native-wheel
make migration-audit
make certify-native-release
```

`make certify-native-release` stages one core wheel, one core sdist and one
native wheel, then creates isolated core-only and exact-pair virtual
environments. It verifies source-to-wheel hashes, package versions/API
handshake, no repository import leakage, promotion/rollback decisions,
static/IR public routes, and the bounded target/package helpers against the
installed Python oracle. The JSON certificate is prerequisite evidence; public
upload still requires the trusted-publishing and Poetry consumer gates.

## Release Owner Checklist

1. Merge the verified release commit through the normal protected branch flow.
2. Create a matching `vX.Y.Z` tag from the final `main` commit.
3. Run **Publish quantbt-native** to TestPyPI, inspect its 3-wheel matrix and
   installed-pair certificate, then publish the matching core to TestPyPI.
4. Run **Public Native Consumer Proof** on TestPyPI. It must pass Ubuntu
   22.04/24.04 across CPython 3.11-3.13 before production upload.
5. Publish `quantbt-native` to protected PyPI first, then create the GitHub
   Release that triggers the protected core OIDC workflow.
6. Run and archive the PyPI consumer proof, core manifest, native matrix, and
   installed-pair certificate with the release notes.

The companion does not enable generic portfolio/package auto routing or remove
the Python oracle. Each broader route still needs its own domain contract,
installed-wheel parity corpus, benchmark/RSS evidence, migration window, and
explicit promotion decision. The exact release steps are maintained in the
[TestPyPI release checklist](../testpypi_release_checklist.md).
