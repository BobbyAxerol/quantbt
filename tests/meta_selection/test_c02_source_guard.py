"""Historical receipts and current C02 financial/scientific source scope."""

import pytest

from tools.qms_c02_source_guard import ROOT, ENTRY, TOKEN_GETTER, validate_changes, validate_rust_control, verify
import subprocess


def test_c02_t08_current_source_guard():
    assert verify()["financial_rust_unchanged"] is True


@pytest.mark.parametrize("name", ["src/quantbt/walkforward.py", "src/quantbt/metrics/performance.py",
                                  "src/quantbt/optimization/meta_selection/ridge.py",
                                  "rust/crates/quantbt-engine/src/account.rs"])
def test_c02_t08_guard_rejects_scope_expansion(name):
    with pytest.raises(AssertionError, match="unapproved"):
        validate_changes([name])


def test_c02_t08_rust_getter_is_additive_only():
    original = subprocess.check_output(["git", "show", f"{ENTRY}:rust/native_event/src/reactive_numeric.rs"], cwd=ROOT)
    source = (ROOT / "rust/native_event/src/reactive_numeric.rs").read_bytes()
    validate_rust_control(source, original)
    for invalid in (source + b"\n// other change\n", source.replace(TOKEN_GETTER, b""),
                    source.replace(b".map(|candidate| candidate.core.cancellation_token(py))",
                                   b".map(|candidate| candidate.core.reset())")):
        with pytest.raises(AssertionError, match="unapproved"):
            validate_rust_control(invalid, original)
