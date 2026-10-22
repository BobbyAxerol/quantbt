"""Cold publish-safe M5-11 aggregates, never private alpha or strategy fixtures."""
import json
from hashlib import sha256
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/"docs/mode5/M5_11_ECONOMIC_REPORT.md"
EVIDENCE=ROOT/"docs/mode5/evidence/m5-11.json"


def test_registered_policy_and_scoped_disposition_are_unambiguous():
    row=json.loads(EVIDENCE.read_text())
    assert row["status"]=="COMPLETE_LOCAL_FINITE_PILOT_EXPLORATORY"
    assert row["protocol"]["family_confidence"]==.99 and row["marginal_confidence"]==.998
    assert row["protocol"]["minimum_origins"]==3
    assert row["calibration_eligible_alphas"]==2 and row["blocked_alphas"]==3
    assert not row["independent_validation"] and not row["method_superiority"]
    assert not row["deployment_authorized"] and not row["remote"] and not row["publication"]
    for alpha in row["formal"]:
        assert alpha["origin_count"]==1
        assert alpha["coordinate_diagnostic"]["status"]=="INCONCLUSIVE"
        if alpha["formal"] is not None:
            actual=alpha["formal"]
            assert actual["same_selected_vector"] and actual["accounting_max_difference"]==0
            assert actual["observed"]["decay_change"]==actual["observed"]["forward_mean_net_change"]==0
            assert actual["intervals"]["forward_mean_net_change"]==[0.,0.]


def test_safe_publication_has_no_raw_vectors_paths_or_private_alpha_values():
    text=EVIDENCE.read_text()
    assert "/root/" not in text and "upgrade/alphas/" not in text
    forbidden={"params","requested_params","effective_params","selected_params","daily_returns",
               "times_ns","equity_path","source_code","market_path"}
    def visit(item):
        if isinstance(item,dict):
            assert not forbidden.intersection(item)
            for value in item.values():visit(value)
        elif isinstance(item,list):
            for value in item:visit(value)
    visit(json.loads(text))


def test_rendered_numerics_match_full_precision_report_and_resource_units():
    row=json.loads(EVIDENCE.read_text());text=REPORT.read_text()
    for item in row["formal"]:
        d=item["coordinate_diagnostic"]
        value=d["observed"]["forward_mean_net_change"]*10000
        lo,hi=[v*10000 for v in d["intervals"]["forward_mean_net_change"]]
        assert f"{value:.4f} | [{lo:.4f}, {hi:.4f}]" in text
    bill=row["billing"]
    assert bill["cached_financial_reexecutions"]==0 and bill["all_new_actual_account_calls"]==22
    assert bill["all_new_actual_account_bars"]==22*8760
    assert not bill["speedup_claim"]
    for timing in bill["timings"].values():
        assert f"{timing['seconds']:.3f} s" in text
        assert f"{timing['peak_rss_mib']:.2f} MiB" in text


def test_source_and_available_private_receipt_hashes_are_bound():
    row=json.loads(EVIDENCE.read_text())
    source=row["source_amendment"]
    assert sha256((ROOT/source["path"]).read_bytes()).hexdigest()==source["sha256"]
    private=ROOT/"upgrade/private/mode5_upgrade_v1/m5-11/attempt-01"
    # Public consumers do not require a private research bundle. When it is
    # present locally, a mismatched source receipt must fail rather than skip.
    if private.exists():
        for receipt in row["source_bound_inputs"]:
            path=private/receipt["name"]
            assert path.stat().st_size==receipt["bytes"]
            assert sha256(path.read_bytes()).hexdigest()==receipt["sha256"]
