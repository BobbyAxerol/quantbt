"""Keep current qualification separate from historical unchanged-finance gates."""
import pytest


def current_source_rejects_historical_certificate(verify_historical):
    from tools.m5_12_source_guard import verify_current_source
    source = verify_current_source()
    assert source["current_source_qualified"] and source["historical_receipts_unchanged"]
    assert source["financial_source_changed"] and not source["financial_numeric_source_unchanged"]
    assert not source["native_artifacts_qualified"]
    with pytest.raises(AssertionError):
        verify_historical()
    return source
