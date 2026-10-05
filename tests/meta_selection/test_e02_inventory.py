from tools.qms_e02_inventory import verify
from quantbt.optimization.meta_selection.common import MetaRecordError
import pytest


def test_e02_t05_actual_dispatch_and_discovery_have_registered_or_pending_adapters():
    assert verify()["pending_routes_not_activated"]


def test_e02_t05_future_dispatch_omitted_from_matrix_cannot_escape_conformance():
    with pytest.raises(MetaRecordError, match="unregistered"):
        verify("def dispatch(target_mode):\n    if target_mode == 'new_financial_domain': pass\n")
    with pytest.raises(ValueError, match="discovery"):
        verify("def dispatch(target_mode):\n    if target_mode == 'intrabar': pass\n")
