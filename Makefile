# Stable developer/CI command surface for the P3 release program.
# PYTHON may point at an activated venv, Poetry, or uv-managed interpreter.

PYTHON ?= python
PYTEST ?= $(PYTHON) -m pytest
RUST_WORKSPACE_MANIFEST ?= rust/Cargo.toml
RUST_NATIVE_MANIFEST ?= rust/native_event/Cargo.toml
CORE_DIST ?= dist/core
NATIVE_DIST ?= dist/native

.PHONY: \
	test-python-unit test-rust-unit test-contracts test-differential test-property \
	test-binding test-installed test-all fuzz-smoke bench-smoke bench-native \
	bench-facade bench-release build-core-wheel build-native-wheel stage-wheels \
	verify-wheels verify-staged-wheels supply-chain-report sbom release-manifest benchmark-governance \
	release-manifest-staged migration-audit certify-native-release \
	docs-check v1_1-baseline-check

.PHONY: v1_1-phase57-check

docs-check:
	$(PYTHON) tools/check_docs_links.py

v1_1-baseline-check:
	$(PYTHON) tools/generate_v1_1_baseline.py --check
	$(PYTEST) -q tests/test_phase56_v1_1_baseline.py

v1_1-phase57-check:
	$(PYTHON) tools/check_v1_1_phase57_foundation.py
	$(PYTEST) -q tests/test_phase57_v1_1_specs_oracle_trace.py

test-python-unit:
	$(PYTEST) -q --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py

test-rust-unit:
	cargo fmt --manifest-path $(RUST_WORKSPACE_MANIFEST) --all --check
	cargo clippy --manifest-path $(RUST_WORKSPACE_MANIFEST) --workspace --all-targets -- -D warnings
	cargo test --manifest-path $(RUST_WORKSPACE_MANIFEST) --workspace

test-contracts:
	$(PYTHON) tools/sync_source_mirror.py --check
	$(PYTHON) tools/generate_native_event_contracts.py --check
	$(PYTHON) tools/generate_product_contracts.py --check
	$(PYTHON) tools/generate_public_api_inventory.py --check
	$(PYTHON) tools/generate_v1_1_baseline.py --check
	$(PYTHON) tools/check_v1_1_phase57_foundation.py
	$(PYTHON) tools/check_module_architecture.py
	$(PYTHON) tools/check_docs_links.py
	$(PYTEST) -q tests/native_event/contract tests/test_phase56_v1_1_baseline.py tests/test_phase57_v1_1_specs_oracle_trace.py

test-differential:
	$(PYTEST) -q tests/native_event/test_reactive_lifecycle_parity.py tests/native_event/test_reactive_accounting_parity.py

test-property:
	$(PYTEST) -q tests/native_event/contract/test_phase51b_accounting_numeric.py

test-binding:
	$(PYTEST) -q tests/native_event/contract/test_phase51b_capability_wheel.py tests/native_event/contract/test_phase53a_pure_rust_core.py

test-installed:
	$(PYTHON) tools/verify_wheels.py --dist $(CORE_DIST)

test-all: test-contracts test-python-unit test-rust-unit

fuzz-smoke:
	$(PYTEST) -q tests/native_event/contract/test_phase51b_accounting_numeric.py

bench-smoke:
	$(PYTHON) benchmarks/native_event/benchmark_phase53b_native_drivers.py --help

bench-native: bench-smoke

bench-facade:
	$(PYTHON) benchmarks/native_event/benchmark_pre48e.py --help

build-core-wheel:
	rm -rf $(CORE_DIST)
	uv build --out-dir $(CORE_DIST)

build-native-wheel:
	rm -rf $(NATIVE_DIST)
	maturin build --release --manifest-path $(RUST_NATIVE_MANIFEST) --out $(NATIVE_DIST)

verify-wheels:
	$(PYTHON) tools/verify_wheels.py --dist $(CORE_DIST)

stage-wheels:
	rm -rf dist/staged
	mkdir -p dist/staged
	cp $(CORE_DIST)/*.whl $(CORE_DIST)/*.tar.gz $(NATIVE_DIST)/*.whl dist/staged/

verify-staged-wheels: stage-wheels
	$(PYTHON) tools/verify_wheels.py --dist dist/staged --require-native

migration-audit:
	$(PYTHON) tools/check_native_release_handoff.py

certify-native-release: verify-staged-wheels migration-audit
	$(PYTHON) tools/certify_native_release.py --dist dist/staged --output release-evidence/native-release-certification.json

supply-chain-report:
	$(PYTHON) tools/create_supply_chain_report.py --output release-evidence/supply-chain.json

sbom:
	$(PYTHON) tools/create_sbom.py --output release-evidence/sbom.cdx.json

release-manifest: supply-chain-report sbom
	$(PYTHON) tools/create_release_manifest.py --dist $(CORE_DIST) --output release-manifest.json --supply-chain-report release-evidence/supply-chain.json --sbom release-evidence/sbom.cdx.json --require-clean

release-manifest-staged: stage-wheels supply-chain-report sbom
	$(PYTHON) tools/create_release_manifest.py --dist dist/staged --output release-manifest-staged.json --supply-chain-report release-evidence/supply-chain.json --sbom release-evidence/sbom.cdx.json --require-clean

bench-release: bench-smoke

benchmark-governance:
	$(PYTHON) tools/check_benchmark_governance.py
