"""C04-T05 byte lock is additive, not a financial-module allowlist."""

from pathlib import Path

import pytest

from tools.qms_c04_source_guard import ALLOW, validate_changes, verify


def test_c04_t05_source_gate():
    receipt = verify()
    assert receipt["financial_samplers_math_unchanged"]
    assert receipt["public_endpoints_unchanged"]
    assert set(receipt["additive_module_sha256"]) == ALLOW


@pytest.mark.parametrize("name", ["src/quantbt/walkforward.py", "src/quantbt/optimization/samplers.py",
                                 "src/quantbt/endpoint.py", "rust/native_event/src/lib.rs"])
def test_c04_t05_rejects_unapproved_source(name):
    with pytest.raises(AssertionError, match="unapproved"):
        validate_changes({name})


def test_c04_t05_no_checkpoint_pickle_or_imported_storage_system_attrs():
    root = Path(__file__).resolve().parents[2]
    for name in ALLOW:
        text = (root / name).read_text()
        assert "import pickle" not in text and "pickle.loads(" not in text
        assert "set_trial_system_attr" not in text
        assert "add_trial(" not in text and "create_trial(" not in text
