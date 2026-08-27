# quantbt-native

`quantbt-native` is the PyO3/Rust accelerator companion to `quantbt-engine`.
The governed `0.4.1` release is a wheel-only Linux companion for
`quantbt-engine==1.1.0`. Its native-first OIDC publish flow and Poetry
consumer proof are documented in `docs/testpypi_release_checklist.md`.

## Scope

The current wheel supports governed static command tapes and bounded Native
Strategy IR/batch workloads. Python remains the canonical full-featured route
outside those promoted contracts. Unsupported features fail fast rather than
silently falling back:

- multi-symbol execution;
- funding and liquidation;
- unsupported quantity and lifecycle policies;
- reactive per-bar strategy callbacks.

The Rust distribution version and native API version are separate contracts.
The distribution is `0.4.1` and advertises Native Event API `0.4`. It targets
pre-built `manylinux_2_17_x86_64` wheels for CPython 3.11, 3.12, and 3.13 only.
It never asks an end user to compile Rust locally.

## Local build

From the repository root:

```bash
cargo fmt --check --manifest-path rust/native_event/Cargo.toml
cargo test --manifest-path rust/native_event/Cargo.toml
maturin build --release --manifest-path rust/native_event/Cargo.toml
```

Install the resulting wheel together with the matching local `quantbt-engine`
wheel, then run the focused Rust/Python parity and RSS tests. Do not enable a
native extra or `native_backend="auto"` based on a local build alone.

## Release gate

The release gate requires CPython 3.11, 3.12, and 3.13 manylinux wheels,
installed-wheel parity, fallback checks, and public Poetry consumer proof on
Ubuntu 22.04 and 24.04. The core declares the matching wheel as a Linux x86_64
runtime dependency; unsupported platforms remain Python.
