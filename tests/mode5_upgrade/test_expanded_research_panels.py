"""Synthetic retained schemas only; no private alpha implementation or parameters."""

from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np
import pytest

from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations, reduce_account
from quantbt.metrics.reporting.execution import ExecutionObservations, reduce_execution
from quantbt.mode5.artifacts import file_identity, write_json
from tools.mode5_diagnostics.identity import digest
from tools.mode5_research.panels import (
    DAY_NS, HOUR_NS, UtilityPolicy, _ns, continuous_annual_rows, daily_attribution, load_cell,
)
from tools.mode5_research.protocol import ResearchProtocol
from tools.mode5_selection.objectives import economic_utility

PREFERENCE = UtilityPolicy("synthetic_actual_horizon_v1", 1., 1.)


class SyntheticCell:
    def __init__(self, root, *, start="2021-01-01", stop="2024-01-01", kind="mixed", ledger=False):
        self.root = root
        root.mkdir()
        self.start, self.stop = _ns(start), _ns(stop)
        self.times = np.arange(self.start, self.stop, HOUR_NS, dtype=np.int64)
        self.days = len(self.times)//24
        self.contract = ReportingContractV1(scope="full", unit="account_period", currency="TEST",
            baseline_equity=100., baseline_time_ns=self.start-HOUR_NS, scope_end_ns=self.stop-HOUR_NS,
            sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
        marks = np.linspace(100., 130., self.days)
        if kind == "mixed":
            marks = np.r_[np.linspace(101., 200., 365), np.linspace(199., 50., 365),
                          np.linspace(51., 130., self.days-730)]
        elif kind == "no_trade":
            marks[:] = 100.
        elif kind == "negative":
            marks = np.linspace(99., 60., self.days)
        elif kind == "bankrupt":
            marks = np.r_[np.linspace(101., 120., 365), np.linspace(119., -20., self.days-365)]
        self.arrays = dict(times_ns=self.times, equity=np.repeat(marks, 24),
            positions=np.zeros(len(self.times)) if kind == "no_trade" else np.ones(len(self.times)),
            fees=np.zeros(len(self.times)))
        coverage = ReportingCoverageV1(result_identity="synthetic", producer="test", profile="compact",
            ledger="omitted", retained_rows=0, dropped_rows=0, reason="separate synthetic ledger")
        obs = AccountObservations(times_ns=self.times, equity=self.arrays["equity"], coverage=coverage)
        if kind != "bankrupt":
            obs = obs.with_derived_returns(self.contract, partial_mask=np.zeros(self.days, dtype=bool),
                                           witness="synthetic complete hourly marks")
            self.arrays["daily_returns"] = obs.returns.values.copy()
        else:
            self.arrays["daily_returns"] = np.zeros(self.days)
        report = reduce_account(obs, self.contract)
        self.metrics = {target:report.metric(source).value for target,source in
            (("total_return", "account.total_return"), ("max_drawdown", "drawdown.max_depth"),
             ("sharpe", "period.sharpe"))}
        self.metrics.update(economic_utility=-123., utility_horizon="retained actual horizon, not Sharpe",
                            account_mode="continuous_development_synthetic")
        self.protocol = ResearchProtocol(development_start=start, development_stop=stop,
                                          forward_stop=f"{int(stop[:4])+2}-01-01")
        source = root / "synthetic_source.py"
        source.write_text("# Synthetic inert provenance, never executed.\n", encoding="ascii")
        data = root / "synthetic_development.txt"
        data.write_text("synthetic frozen development witness\n", encoding="ascii")
        self.sources = {name:file_identity(source) for name in ("alpha_source", "finance_driver", "orchestrator")}
        self.request = dict(alpha="synthetic_candidate_family", params=dict(x=2), candidate_id=digest(dict(x=2)),
            proposal_row=0, design_id=digest("synthetic_design"), role="NEUTRAL_BROAD_DISCOVERY",
            start=start, stop=stop, symbol="SYNTHETIC", account_mode="continuous_development_synthetic")
        proposal = dict(row_id=0, candidate_id=self.request["candidate_id"], effective=dict(x=2),
            requested=dict(x=2.1), admitted=True, status="READY", direction="branch:0")
        design = dict(alpha=self.request["alpha"], design_id=self.request["design_id"], rows=[proposal])
        registration = dict(protocol=asdict(self.protocol), protocol_id=self.protocol.identity,
            financial_outcomes_used_to_choose_design=False, forward_selection=False,
            symbols={self.request["alpha"]:"SYNTHETIC"}, created_at="2026-10-10T14:00:00+00:00")
        resources = dict(resource_protocol=asdict(self.protocol))
        access = dict(witness=file_identity(data), allowed_stop=stop, future_tape_opened=False,
            original_contract_preserved=True, mutable_strategy_or_account_reused=False,
            finance_driver=self.sources["finance_driver"], orchestrator=self.sources["orchestrator"])
        self.pins = {}
        for name, filename, value in (("registration", "registration.json", registration),
                ("resources", "resource_registration.json", resources), ("design", "design.json", design),
                ("request", "request.json", self.request), ("access", "development_access.json", access)):
            self.write(name, filename, value)
        budget = dict(original_registration=self.pins["registration"],
            original_resource_registration=self.pins["resources"], scientific_protocol_changed=False,
            core_or_alpha_changed=False, economic_outcome_filtering=False, publication=False,
            automatic_phase_promotion=False, numeric_threads_per_worker=1, financial_workers=3,
            source=file_identity(source), created_at="2026-10-10T14:01:00+00:00")
        self.write("execution_budget", "execution_extension_01.json", budget)
        years = list(range(int(start[:4]), int(stop[:4])))
        analysis = dict(registration=self.pins["registration"], execution_budget=self.pins["execution_budget"],
            source=file_identity(source), created_at="2026-10-10T14:02:00+00:00",
            role="REVIEWED_EXPLORATORY_DEVELOPMENT", clean_independent_claim=False,
            forward_snapshot_allowed=False, incomplete_matrix_is_complete_phase=False,
            outcome_timing_disclosure="synthetic pilots exist; this analysis is not retroactive preregistration",
            alpha_roster=[self.request["alpha"]], screening=dict(exact_sobol_claim=False),
            environment_contract=dict(mode="CONTINUOUS_PATH_ATTRIBUTION", account_reset=False,
                annual_sharpe_average_is_whole_sharpe=False, overlapping_families_independent=False,
                annual_days=365, years=years))
        self.write("analysis", "analysis_registration_01.json", analysis)
        np.savez_compressed(root/"paths.npz", **self.arrays)
        self.pins["paths"] = file_identity(root/"paths.npz")
        self.cell = dict(status="PASS", request=self.request, execution_key=digest("synthetic_execution"),
            metrics=self.metrics, path=self.pins["paths"], clean_oos=False, route="synthetic retained account",
            scored_bars=len(self.times), scored_days=self.days, actual_execution_calls=2,
            visited_bars=2*len(self.times), wall_seconds=1., peak_rss_mib=1.,
            support=dict(closed_campaigns=None, open_campaigns=None, fills=None))
        if ledger:
            closed = [] if kind == "no_trade" else [dict(start="2021-12-31 23:00:00+00:00",
                end="2022-01-01 01:00:00+00:00", net_pnl=10.)]
            opened = [] if kind == "no_trade" else [dict(start="2022-01-01 02:00:00+00:00", marked_net_pnl=20.)]
            fills = [] if kind == "no_trade" else [dict(timestamp=value) for value in
                (closed[0]["start"], closed[0]["end"], opened[0]["start"])]
            self.write("campaigns", "campaigns.json", dict(closed=closed, open=opened))
            self.write("fills", "fills.json", fills)
            self.cell["support"] = dict(closed_campaigns=len(closed), open_campaigns=len(opened), fills=len(fills))
        self.write("cell", "cell.json", self.cell)

    def write(self, name, filename, value):
        path = self.root/filename
        write_json(path, value)
        self.pins[name] = file_identity(path)

    def revise(self, name, mutate):
        pin = self.pins[name]
        value = json.loads(Path(pin["path"]).read_text())
        mutate(value)
        Path(pin["path"]).write_text(json.dumps(value, allow_nan=False), encoding="ascii")
        self.pins[name] = file_identity(pin["path"])

    def load(self, **changes):
        args = dict(artifact_pins=self.pins, source_pins=self.sources, contract=self.contract,
            cutoff_ns=_ns("2026-10-11"), study_id="synthetic_study", diagnostic_revision="analysis_01")
        return load_cell(self.root/"cell.json", **(args | changes))

    def reseal_paths(self):
        coverage = ReportingCoverageV1(result_identity="synthetic_revision", producer="test", profile="compact",
            ledger="omitted", retained_rows=0, dropped_rows=0, reason="separate synthetic ledger")
        obs = AccountObservations(times_ns=self.times, equity=self.arrays["equity"], coverage=coverage)
        obs = obs.with_derived_returns(self.contract, partial_mask=np.zeros(self.days, dtype=bool),
                                      witness="synthetic revised suffix")
        self.arrays["daily_returns"] = obs.returns.values.copy()
        report = reduce_account(obs, self.contract)
        metrics = {target:report.metric(source).value for target,source in
            (("total_return", "account.total_return"), ("max_drawdown", "drawdown.max_depth"),
             ("sharpe", "period.sharpe"))}
        np.savez_compressed(self.root/"paths.npz", **self.arrays)
        self.pins["paths"] = file_identity(self.root/"paths.npz")
        self.revise("cell", lambda row:(row.update(path=self.pins["paths"]), row["metrics"].update(metrics)))


@pytest.fixture
def bundle(tmp_path):
    return SyntheticCell(tmp_path/"cell")


def test_three_year_continuous_marks_start_baselines_and_original_authority(bundle):
    cell = bundle.load()
    rows = continuous_annual_rows(cell, utility_policy=PREFERENCE)
    whole, first, second, third = rows
    assert [row.calendar_days for row in rows] == [1095, 365, 365, 365]
    assert [row.actual_bar_count for row in rows] == [26280, 8760, 8760, 8760]
    assert whole.metric("net_return").value == pytest.approx(.3)
    assert first.metric("net_return").value == pytest.approx(1.)
    assert second.metric("net_return").value == pytest.approx(-.75)
    assert third.metric("net_return").value == pytest.approx(1.6)
    assert [row.money_pnl for row in rows] == pytest.approx([30., 100., -150., 80.])
    assert sum(row.money_pnl for row in rows[1:]) == pytest.approx(whole.money_pnl)
    assert np.prod([1+row.metric("net_return").value for row in rows[1:]])-1 == pytest.approx(.3)
    assert second.raw_account_metrics.to_metadata()["provenance"]["contract"]["baseline_equity"] == 200.
    assert third.raw_account_metrics.to_metadata()["provenance"]["contract"]["baseline_equity"] == 50.
    assert whole.metric("sharpe").value == bundle.metrics["sharpe"]
    assert whole.metric("sharpe").value != pytest.approx(np.mean([row.metric("sharpe").value for row in rows[1:]]))
    assert third.metric("drawdown").value == 0.
    assert third.metric("carried_watermark_drawdown").value == pytest.approx(1-51/200)
    assert third.raw_account_metrics.metric("drawdown.max_depth").value == 0.
    daily = daily_attribution(cell)
    assert daily[0].equity_before == 100.
    assert daily[365].equity_before == 200.
    assert daily[730].equity_before == 50.
    assert whole.exposure_days == 1095 and whole.exposed_bars == 26280
    assert json.loads(cell.original_metrics_json)["economic_utility"] == -123.
    assert whole.metric("economic_utility").value != -123.
    assert whole.utility_horizon == "actual contiguous period; no duration normalization"
    assert rows[2].status == "VALID_UNPROFITABLE"


def test_leap_calendar_is_not_scaled_to_365_observations(tmp_path):
    bundle = SyntheticCell(tmp_path/"cell", start="2023-01-01", stop="2026-01-01", kind="positive")
    cell = bundle.load()
    rows = continuous_annual_rows(cell, utility_policy=PREFERENCE)
    assert [row.calendar_days for row in rows] == [1096, 365, 366, 365]
    assert rows[2].actual_bar_count == 8784
    assert _ns("2024-02-29") in {row.day_ns for row in daily_attribution(cell)}
    assert rows[2].metric("sharpe").value == rows[2].raw_account_metrics.metric("period.sharpe").value
    assert rows[2].raw_account_metrics.to_metadata()["provenance"]["contract"]["annual_periods"] == 365.


def test_censored_campaign_support_reconciles_without_discarding_mark_pnl(tmp_path):
    bundle = SyntheticCell(tmp_path/"cell", kind="positive", ledger=True)
    rows = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    assert [(row.closed_campaigns, row.open_campaigns, row.fills) for row in rows] == [
        (1, 1, 3), (0, 1, 1), (1, 1, 2), (0, 1, 0)]
    assert rows[0].money_pnl == 30.
    assert rows[3].money_pnl > 0
    assert rows[0].independent_information_count is None


def test_missing_campaign_witness_is_null_not_zero_or_fill_based_support(bundle):
    row = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)[0]
    assert row.closed_campaigns is row.open_campaigns is row.fills is None
    assert "closed_campaigns" in dict(row.null_reasons)
    assert "campaign_pf" in dict(row.null_reasons)
    assert row.metric("return_step_pf").value is not None


def test_no_trade_is_valid_zero_outcome_with_undefined_sharpe(tmp_path):
    bundle = SyntheticCell(tmp_path/"cell", kind="no_trade", ledger=True)
    rows = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    for row in rows:
        assert row.status == "VALID_NO_TRADE"
        assert row.metric("net_return").value == row.metric("economic_utility").value == 0.
        assert row.metric("sharpe").value is None
        assert row.metric("sharpe").reason
        assert row.zero_return_days == row.calendar_days
        assert row.exposure_days == 0


def test_flat_marks_without_ledger_do_not_certify_no_trades(tmp_path):
    bundle = SyntheticCell(tmp_path/"cell", kind="no_trade")
    row = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)[0]
    assert row.status == "VALID_ZERO_RETURN"
    assert row.closed_campaigns is None


def test_losses_are_not_runtime_failures_or_filtered_environments(tmp_path):
    bundle = SyntheticCell(tmp_path/"cell", kind="negative")
    rows = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    assert len(rows) == 4
    assert all(row.status == "VALID_UNPROFITABLE" and row.compute_status == "PASS" for row in rows)
    assert rows[0].metric("net_return").value == pytest.approx(-.4)
    assert rows[0].metric("sharpe").value < 0


def test_bankruptcy_remains_adverse_and_does_not_invalidate_earlier_year(tmp_path):
    bundle = SyntheticCell(tmp_path/"cell", kind="bankrupt")
    rows = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    assert rows[0].status == "VALID_UNPROFITABLE"
    assert rows[0].metric("net_return").value < -1
    assert rows[0].metric("sharpe").value is None
    assert rows[1].metric("sharpe").value is not None
    assert rows[-1].metric("daily_loss_es").value is None


@pytest.mark.parametrize("status", ["STRUCTURAL_INVALID", "RUNTIME_FAILED"])
def test_declared_failures_have_reasons_not_economic_sentinels(bundle, status):
    bundle.revise("cell", lambda row:row.update(status=status, reason="synthetic explicit failure", metrics={}))
    rows = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    assert len(rows) == 1 and rows[0].status == status
    assert rows[0].money_pnl is None and not rows[0].metrics
    assert rows[0].reason == "synthetic explicit failure"


def test_altered_path_rejected_even_when_metadata_hash_is_unchanged(bundle):
    bundle.arrays["equity"][0] += 10
    np.savez_compressed(bundle.root/"paths.npz", **bundle.arrays)
    with pytest.raises(ValueError, match="identity mismatch"):
        bundle.load()


def test_unsealed_cell_metadata_rejected(bundle):
    path = bundle.root/"cell.json"
    path.write_text(path.read_text()+" ", encoding="ascii")
    with pytest.raises(ValueError, match="identity mismatch"):
        bundle.load()


def test_original_source_and_development_bytes_are_checked(bundle):
    path = Path(bundle.sources["alpha_source"]["path"])
    original = path.read_text()
    path.write_text("changed source\n", encoding="ascii")
    with pytest.raises(ValueError, match="source identity mismatch"):
        bundle.load()
    path.write_text(original, encoding="ascii")
    (bundle.root/"synthetic_development.txt").write_text("changed data\n", encoding="ascii")
    with pytest.raises(ValueError, match="data identity mismatch"):
        bundle.load()


@pytest.mark.parametrize("name,change", [
    ("request", lambda row:row.update(candidate_id="other")),
    ("design", lambda row:row["rows"][0].update(effective=dict(x=3))),
    ("design", lambda row:row.update(design_id="other")),
    ("design", lambda row:row["rows"][0].update(admitted=False)),
    ("registration", lambda row:row.update(financial_outcomes_used_to_choose_design=True)),
    ("resources", lambda row:row["resource_protocol"].update(numeric_threads=2)),
    ("access", lambda row:row.update(future_tape_opened=True)),
    ("access", lambda row:row.update(mutable_strategy_or_account_reused=True)),
    ("analysis", lambda row:row.update(clean_independent_claim=True)),
    ("analysis", lambda row:row["environment_contract"].update(account_reset=True)),
    ("analysis", lambda row:row["screening"].update(exact_sobol_claim=True)),
    ("execution_budget", lambda row:row.update(scientific_protocol_changed=True)),
    ("cell", lambda row:row.update(visited_bars=1)),
    ("cell", lambda row:row["metrics"].update(sharpe=123.)),
])
def test_original_identity_resource_and_claim_mutations_rejected(bundle, name, change):
    bundle.revise(name, change)
    with pytest.raises(ValueError):
        bundle.load()


@pytest.mark.parametrize("change", ["gap", "daily_returns", "timestamp_dtype", "spliced", "nan"])
def test_even_newly_sealed_invalid_paths_are_rejected(bundle, change):
    if change == "gap":
        bundle.arrays["times_ns"][50] += HOUR_NS
    elif change == "daily_returns":
        bundle.arrays["daily_returns"][0] += .1
    elif change == "timestamp_dtype":
        bundle.arrays["times_ns"] = bundle.times.astype(float)
    elif change == "spliced":
        bundle.arrays["times_ns"][8760:] += DAY_NS
    else:
        bundle.arrays["equity"][10] = np.nan
    np.savez_compressed(bundle.root/"paths.npz", **bundle.arrays)
    bundle.pins["paths"] = file_identity(bundle.root/"paths.npz")
    bundle.revise("cell", lambda row:row.update(path=bundle.pins["paths"]))
    with pytest.raises(ValueError):
        bundle.load()


def test_future_cutoff_and_first_retained_mark_as_baseline_rejected(bundle):
    with pytest.raises(PermissionError, match="future or immature"):
        bundle.load(cutoff_ns=_ns("2023-12-31"))
    with pytest.raises(ValueError, match="account contract"):
        bundle.load(contract=replace(bundle.contract, baseline_time_ns=bundle.start))
    with pytest.raises(ValueError, match="metric authority"):
        bundle.load(contract=replace(bundle.contract, baseline_equity=101.))


def test_sanitized_rows_preserve_reviewed_timing_and_pending_batteries(bundle):
    cell = bundle.load()
    row = continuous_annual_rows(cell, utility_policy=PREFERENCE)[0]
    metadata = json.dumps(asdict(row), allow_nan=False)
    assert "params" not in metadata.replace("raw_params_digest", "").replace("effective_params_digest", "")
    assert str(bundle.root) not in metadata
    assert cell.provenance.data_role == "REVIEWED_EXPLORATORY_DEVELOPMENT"
    assert "not retroactive" in cell.provenance.outcome_timing_disclosure
    assert row.clean_oos is False and dict(row.battery_statuses) == {"B4":"NOT_RUN", "B5":"NOT_RUN"}
    assert dict(cell.provenance.evidence_refs)["paths"] == bundle.pins["paths"]["sha256"]
    assert dict(cell.provenance.evidence_refs)["analysis"] == bundle.pins["analysis"]["sha256"]


def test_future_suffix_cannot_change_prior_annual_metrics(bundle):
    before = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    bundle.arrays["equity"][730*24:] *= 3.
    bundle.reseal_paths()
    after = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    for index in (1, 2):
        # The whole-path seal changes on a suffix edit; prior numerical metrics do not.
        values = lambda row:[(metric.metric_id, metric.unit, metric.value, metric.status, metric.reason)
                            for metric in row.metrics]
        assert values(before[index]) == values(after[index])
        assert before[index].money_pnl == after[index].money_pnl
        assert before[index].raw_account_metrics.contract_identity == after[index].raw_account_metrics.contract_identity
    assert before[0].metric("sharpe").value != after[0].metric("sharpe").value


def test_loaded_buffers_are_immutable_snapshots(bundle):
    cell = bundle.load()
    with pytest.raises(ValueError):
        cell.observations.equity[0] = 1000.
    with pytest.raises(ValueError):
        cell.arrays()["positions"][0] = 2.
    bundle.arrays["equity"][0] = 900.
    assert cell.observations.equity[0] == 101.


@pytest.mark.parametrize("name,change", [
    ("campaigns", lambda row:row["open"][0].update(marked_net_pnl=19.)),
    ("campaigns", lambda row:row["closed"][0].update(end="2025-01-01")),
    ("fills", lambda row:row.pop()),
])
def test_sealed_campaign_and_fill_support_must_reconcile(tmp_path, name, change):
    bundle = SyntheticCell(tmp_path/"cell", kind="positive", ledger=True)
    bundle.revise(name, change)
    with pytest.raises(ValueError):
        bundle.load()


def test_paths_cannot_be_relocated_by_changing_metadata(bundle):
    other = bundle.root/"other.npz"
    other.write_bytes((bundle.root/"paths.npz").read_bytes())
    bundle.pins["paths"] = file_identity(other)
    bundle.revise("cell", lambda row:row.update(path=bundle.pins["paths"]))
    with pytest.raises(ValueError, match="original cell sibling"):
        bundle.load()


def test_annual_primary_utility_uses_scope_entry_drawdown_not_carried_watermark(bundle):
    rows = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    whole, _, _, annual = rows
    assert PREFERENCE.drawdown_basis == "scope_entry"
    assert annual.metric("drawdown").value == annual.raw_account_metrics.metric("drawdown.max_depth").value == 0.
    assert annual.metric("carried_watermark_drawdown").value > 0.
    expected = economic_utility(annual.metric("net_return"), annual.metric("drawdown"),
        annual.metric("daily_loss_es"), dd_weight=PREFERENCE.dd_weight, tail_weight=PREFERENCE.tail_weight,
        preference_id=PREFERENCE.preference_id)
    alternate = economic_utility(annual.metric("net_return"), annual.metric("carried_watermark_drawdown"),
        annual.metric("daily_loss_es"), dd_weight=PREFERENCE.dd_weight, tail_weight=PREFERENCE.tail_weight,
        preference_id="synthetic_nonprimary_diagnostic")
    assert annual.metric("economic_utility").value == expected.value
    assert annual.metric("economic_utility").value != alternate.value
    assert whole.metric("drawdown").value == whole.metric("carried_watermark_drawdown").value
    assert dict(annual.metric("economic_utility").components)["drawdown_basis"] == "scope_entry"


def test_unapproved_watermark_primary_policy_is_rejected():
    with pytest.raises(ValueError, match="separately approved scientific contract"):
        replace(PREFERENCE, drawdown_basis="carried_watermark")


def test_reporting_metadata_names_both_environment_valuations_and_contracts(bundle):
    whole, _, _, annual = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    assert annual.environment_baseline.equity == 50.
    assert annual.carried_watermark.equity == 200.
    assert annual.environment_baseline.as_of_ns == annual.carried_watermark.as_of_ns == _ns("2023-01-01")-HOUR_NS
    assert annual.environment_baseline.source_kind == "prior_actual_close"
    assert annual.environment_baseline.identity != annual.carried_watermark.identity
    metadata = annual.raw_account_metrics.to_metadata()["provenance"]
    assert metadata["environment_id"] == "2023"
    assert metadata["environment_baseline"] == annual.environment_baseline.to_metadata()
    assert metadata["carried_watermark"] == annual.carried_watermark.to_metadata()
    assert annual.environment_baseline.reporting_contract_identity == annual.raw_account_metrics.contract_identity
    assert set(annual.metric_contract_ids) == {annual.environment_baseline.reporting_contract_identity,
                                             annual.carried_watermark.reporting_contract_identity}
    assert dict(annual.metric("carried_watermark_drawdown").components)["valuation_identity"] == annual.carried_watermark.identity
    assert dict(annual.metric("economic_utility").components)["drawdown_valuation_identity"] == annual.environment_baseline.identity
    assert whole.environment_baseline.equity == whole.carried_watermark.equity == 100.


def test_turnover_is_executed_notional_in_contract_currency_not_capital_ratio(bundle):
    bundle.arrays["turnover"] = np.zeros(len(bundle.times))
    bundle.arrays["turnover"][[0, 730*24]] = [250., 75.]
    bundle.reseal_paths()
    rows = continuous_annual_rows(bundle.load(), utility_policy=PREFERENCE)
    assert [row.metric("turnover").value for row in rows] == [325., 250., 0., 75.]
    turnover = rows[0].metric("turnover")
    assert turnover.unit == bundle.contract.currency == "TEST"
    assert dict(turnover.components) == dict(measure="executed_fill_notional", aggregation="sum_actual_bars", normalization="none")
    coverage = rows[0].raw_account_metrics.metrics[0].coverage
    execution = ExecutionObservations(coverage=coverage, currency=bundle.contract.currency,
        scope_start_ns=bundle.contract.baseline_time_ns, scope_end_ns=bundle.contract.scope_end_ns,
        witness="synthetic executed-notional aggregate; native event unit",
        aggregates=(("turnover", 325.),))
    authority = reduce_execution(execution, bundle.contract).metric("execution.turnover")
    assert (turnover.value, turnover.unit) == (authority.value, authority.unit)


def test_data_and_artifact_cutoffs_are_separate_current_knowledge_claims(bundle):
    cell = bundle.load(data_cutoff_ns=bundle.stop, artifact_creation_cutoff_ns=_ns("2026-10-10T14:03:00+00:00"))
    provenance = cell.provenance
    assert provenance.data_cutoff_ns == _ns("2024-01-01")
    assert provenance.artifact_creation_cutoff_ns == _ns("2026-10-10T14:03:00+00:00")
    assert provenance.knowledge_cutoff_ns == _ns("2026-10-11")
    assert provenance.chronology_claim == "current-knowledge retrospective attribution, not historical calibration"
    assert "available_cutoff_ns" not in asdict(provenance)
    with pytest.raises(PermissionError, match="future or immature"):
        bundle.load(data_cutoff_ns=_ns("2023-12-31"))
    with pytest.raises(PermissionError, match="future or immature"):
        bundle.load(artifact_creation_cutoff_ns=_ns("2026-10-10T14:01:00+00:00"))
    with pytest.raises(PermissionError, match="future or immature"):
        bundle.load(artifact_creation_cutoff_ns=_ns("2027-01-01"))
