import json
import random

import numpy as np

from tools.meta_model_research.admission import PUBLIC, ROOT, read
from tools.meta_model_research.decision_reporting import markdown


def test_canonical_roundtrip_report_is_exact_and_rng_unchanged():
    s = read(PUBLIC / "ml06_summary.json")
    before = random.getstate()
    np_before = np.random.get_state()
    text = markdown(s)
    assert text == markdown(json.loads(json.dumps(s, sort_keys=True)))
    assert (
        text
        == (ROOT / "docs/meta_selection/M4_ML_06_DECISION_VALUE_REPORT.md").read_text()
    )
    assert random.getstate() == before
    after = np.random.get_state()
    assert np.array_equal(np_before[1], after[1]) and np_before[2:] == after[2:]


def test_public_report_keeps_units_missingness_and_private_inputs_out():
    text = markdown(read(PUBLIC / "ml06_summary.json"))
    for field in (
        "Raw-Sharpe",
        "Unknown/undefined",
        "N/A",
        "Witnessed Candidate Opportunity",
        "conditional",
    ):
        assert field in text
    for forbidden in (
        '"effective_params"',
        '"coefficients"',
        "/root/bobby",
        '"requested_params"',
    ):
        assert forbidden not in text


def test_registered_work_and_core_baseline_roster_reconcile():
    s = read(PUBLIC / "ml06_summary.json")
    assert s["baseline_retention"] == dict(
        native=228, ridge=228, zero_scored_checks=169, zero_nonanchor_effective=0
    )
    assert s["work"]["logical_fits"] == 145
    assert s["work"]["numeric_reference_qualification_charge"] == 153
    assert s["work"]["financial_calls"] == 132
    assert s["work"]["new_optimizer_proposals"] == 0
    assert s["work"]["outside_budget_by_policy"] == {"F": 26}
