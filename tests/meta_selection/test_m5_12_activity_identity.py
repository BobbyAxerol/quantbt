"""Accepted quantities must not inherit old requested-signal activity identity."""

from dataclasses import replace

import pytest

from quantbt.optimization.meta_selection.common import MetaRecordError
from quantbt.optimization.meta_selection.observer import (
    ResultMetricAdapter, canonical_metric_contract,
)


def test_pct_activity_changes_identity_without_changing_sharpe_or_other_domains():
    legacy = canonical_metric_contract()
    accepted = canonical_metric_contract(accepted_contract_units=True)
    assert accepted != legacy
    assert accepted.metric_id != legacy.metric_id
    assert accepted.definition_id == legacy.definition_id
    assert accepted == replace(legacy, activity_definition_id=accepted.activity_definition_id)
    assert canonical_metric_contract() == legacy
    ResultMetricAdapter(accepted)
    ResultMetricAdapter(legacy)
    with pytest.raises(MetaRecordError):
        ResultMetricAdapter(replace(accepted, activity_definition_id="unreviewed"))
    with pytest.raises(MetaRecordError, match="boolean"):
        canonical_metric_contract(accepted_contract_units="yes")
