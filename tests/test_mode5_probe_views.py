"""Public annual-view oracles and isolated cold-loader boundary contracts."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.mode5_research import probe_views as v
from tools.mode5_research import panels as p
from tests.mode5_cold_boundary import assert_cold_boundary


import numpy as np


def synthetic(kind="mixed", suffix=None):
    start, stop = p._ns("2021-01-01"), p._ns("2024-01-01")
    times = np.arange(start, stop, p.HOUR_NS, dtype=np.int64)
    marks = np.r_[np.linspace(20200., 40000., 365), np.linspace(38000., 10000., 365),
                  np.linspace(10200., 26000., 365)]
    if kind == "flat":
        marks[:] = 20000.
    elif kind == "negative":
        marks = np.linspace(19900., 10000., 1095)
    elif kind == "bankrupt":
        marks = np.r_[np.linspace(20000., 30000., 365), np.linspace(29000., -1000., 365),
                      np.linspace(-1000., -2000., 365)]
    if suffix is not None:
        marks[730:] = suffix
    contract = p.ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=20000., baseline_time_ns=start-p.HOUR_NS, scope_end_ns=stop-p.HOUR_NS,
        sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
    coverage = p.ReportingCoverageV1(result_identity="synthetic", producer="test", profile="compact",
        ledger="omitted", retained_rows=0, dropped_rows=0, reason="synthetic sealed ledger")
    obs = p.AccountObservations(times_ns=times, equity=np.repeat(marks, 24), coverage=coverage)
    if kind != "bankrupt":
        obs = obs.with_derived_returns(contract, partial_mask=np.zeros(1095, dtype=bool), witness="synthetic UTC marks")
    provenance = p.CandidateProvenance("test", "test", "A-RSI", "candidate", "raw", "effective", "axis:x:1",
        (0,), "execution", "design", "SYNTHETIC", "REVIEWED_EXPLORATORY_DEVELOPMENT", "synthetic only",
        p._ns("2020-01-01"), stop, p._ns("2026-10-10"), p._ns("2026-10-10"), "no execution", (("paths", "synthetic"),))
    arrays = dict(positions=np.zeros(len(times)) if kind == "flat" else np.ones(len(times)),
                  fees=np.ones(len(times))*.001, funding=np.ones(len(times))*.0001,
                  turnover=np.ones(len(times))*2)
    cell = p.VerifiedCell(provenance, start, stop, contract, obs,
        tuple(p.FrozenBuffer.from_array(k, a) for k, a in arrays.items()),
        json.dumps(dict(closed=[], open=[])) if kind == "flat" else None,
        "[]" if kind == "flat" else None, "{}", "PASS", None)
    rows = p.continuous_annual_rows(cell, utility_policy=p.UtilityPolicy(**v.UTILITY), backend="python")
    raw = dict(total_return=rows[0].metric("net_return").value, max_drawdown=rows[0].metric("drawdown").value,
        sharpe=rows[0].metric("sharpe").value, daily_loss_es=rows[0].metric("daily_loss_es").value,
        economic_utility=rows[0].metric("economic_utility").value)
    return replace(cell, original_metrics_json=json.dumps(raw)), rows


def metadata(rows, role="selection_probe"):
    return [v.row_metadata(r) | dict(role=role) for r in rows]


def annual_aggregate(*args, **kwargs):
    # The cold import boundary has its own subprocess test; use real public math.
    with patch.object(v, "numeric_owner", return_value=p):
        return v.annual_aggregate(*args, **kwargs)


class AnnualProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cell, cls.rows = synthetic()

    def test_exact_existing_producer_owner(self):
        self.assertEqual(p.continuous_annual_rows.__module__, "tools.mode5_research.panels")
        self.assertEqual(v.custody.pin(p.__file__)["sha256"], v.PANEL_SHA)

    def test_scope_entry_before_first_mark(self):
        self.assertEqual(self.rows[2].environment_baseline.equity, 40000.)
        self.assertEqual(self.rows[2].environment_baseline.as_of_ns, p._ns("2022-01-01")-p.HOUR_NS)
        self.assertAlmostEqual(self.rows[2].metric("net_return").value, -.75)
        self.assertNotAlmostEqual(self.rows[2].metric("net_return").value, 10000./38000.-1)

    def test_carried_account_no_annual_reset(self):
        self.assertEqual([r.environment_baseline.equity for r in self.rows[1:]], [20000., 40000., 10000.])
        self.assertEqual([r.money_pnl for r in self.rows], [6000., 20000., -30000., 16000.])
        v.verify_reconciliation(metadata(self.rows), self.cell)

    def test_watermark_is_separate_diagnostic(self):
        third = self.rows[3]
        self.assertEqual(third.metric("drawdown").value, 0.)
        self.assertAlmostEqual(third.metric("carried_watermark_drawdown").value, 1-10200./40000.)
        self.assertEqual(third.carried_watermark.equity, 40000.)
        self.assertEqual(third.raw_account_metrics.metric("drawdown.max_depth").value, 0.)

    def test_daily365_and_full_annual_metadata(self):
        for r in self.rows[1:]:
            self.assertEqual((r.calendar_days, r.actual_bar_count), (365, 8760))
            self.assertEqual(r.raw_account_metrics.metric("period.count").value, 365.)
            meta = v.row_metadata(r)
            self.assertEqual(meta["raw_account_metrics"]["provenance"]["contract"]["annual_periods"], 365.)
            json.dumps(meta, allow_nan=False)
            self.assertIn("battery_statuses", meta)

    def test_cost_streams_and_currency_preserved(self):
        for stream in ("fees", "funding", "turnover"):
            self.assertAlmostEqual(sum(r.metric(stream).value for r in self.rows[1:]), self.rows[0].metric(stream).value)
            self.assertEqual(self.rows[1].metric(stream).unit, "USDT")

    def test_utility_is_original_net_dd_es_not_sharpe(self):
        for row in self.rows:
            self.assertAlmostEqual(row.metric("economic_utility").value,
                row.metric("net_return").value-row.metric("drawdown").value-row.metric("daily_loss_es").value)
            self.assertEqual(dict(row.metric("economic_utility").components)["preference_id"], v.UTILITY["preference_id"])

    def test_daily_partitions_preserve_pre_year_close(self):
        daily = p.daily_attribution(self.cell)
        self.assertEqual(daily[365].equity_before, 40000.)
        self.assertEqual(daily[730].equity_before, 10000.)
        self.assertEqual(daily[365].observed_bars, 24)

    def test_no_future_suffix_contaminates_earlier_years(self):
        _, altered = synthetic(suffix=np.linspace(500., 900000., 365))
        for before, after in zip(self.rows[1:3], altered[1:3]):
            self.assertEqual(v.row_metadata(before), v.row_metadata(after))

    def test_no_annual_sharpe_average_as_whole_metric(self):
        self.assertNotAlmostEqual(self.rows[0].metric("sharpe").value,
                                  sum(r.metric("sharpe").value for r in self.rows[1:])/3)

    def test_no_trade_and_undefined_sharpe_stay_typed(self):
        cell, rows = synthetic("flat")
        self.assertEqual(rows[1].status, "VALID_NO_TRADE")
        self.assertIsNone(rows[1].metric("sharpe").value)
        self.assertEqual(rows[1].metric("economic_utility").value, 0.)
        v.verify_reconciliation(metadata(rows), cell)

    def test_negative_utility_is_not_replaced_by_sentinel(self):
        _, rows = synthetic("negative")
        aggregate = annual_aggregate(metadata(rows[1:]), v.COMMON, role="selection_probe")
        self.assertLess(aggregate["score"], 0.)
        self.assertFalse(aggregate["eligible"])
        self.assertEqual(aggregate["status"], "COMPLETE")

    def test_bankrupt_year_retains_explicit_undefined(self):
        _, rows = synthetic("bankrupt")
        third = rows[3]
        self.assertIsNone(third.metric("economic_utility").value)
        self.assertIsNotNone(third.metric("economic_utility").reason)
        aggregate = annual_aggregate(metadata(rows[1:]), v.COMMON, role="selection_probe")
        self.assertIsNone(aggregate["score"])
        self.assertEqual(aggregate["status"], "UNDEFINED_INPUT_RETAINED")

    def test_annual_reconciliation_rejects_wrong_entry(self):
        rows = metadata(self.rows)
        rows[2]["environment_baseline"]["equity"] = 20000.
        with self.assertRaises(ValueError):
            v.verify_reconciliation(rows, self.cell)


class CommonAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, rows = synthetic()
        cls.rows = metadata(rows[1:])

    def test_same_center_neighbor_authorization(self):
        neighbor = annual_aggregate(self.rows, v.COMMON, role="selection_probe")
        center = annual_aggregate([{k: val for k, val in r.items() if k != "role"} for r in self.rows], v.COMMON, role="center")
        self.assertEqual(center["score"], neighbor["score"])
        self.assertEqual(center["aggregate_identity"], neighbor["aggregate_identity"])
        self.assertAlmostEqual(neighbor["score"], min(neighbor["values"])+.25*sum(neighbor["values"])/3)
        self.assertFalse(neighbor["local_selection_authorized"])

    def test_not_pooled_utility_or_environment_mean(self):
        aggregate = annual_aggregate(self.rows, v.COMMON, role="selection_probe")
        self.assertNotAlmostEqual(aggregate["score"], sum(aggregate["values"])/3)
        self.assertNotAlmostEqual(aggregate["score"], synthetic()[1][0].metric("economic_utility").value)

    def test_every_unapproved_policy_change_rejects(self):
        changes = dict(version="local_downside_v1", coefficients=dict(mean=.5), weights=[1., 2., 1.],
            environment_ids=["2021", "2023"], unit="ratio", activity_penalty=.1,
            risk_drawdown_max=.6, quality_utility_strictly_greater_than=-1., minimum_daily_count=300,
            annual_periods=252., account_reset=True, utility=dict(v.UTILITY, dd_weight=2.))
        for name, value in changes.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                annual_aggregate(self.rows, deepcopy(v.COMMON) | {name: value}, role="selection_probe")

    def test_validation_cannot_be_selection_input(self):
        rows = [r | dict(role="local_validation") for r in self.rows]
        aggregate = annual_aggregate(rows, v.COMMON, role="local_validation")
        self.assertFalse(aggregate["selection_input_authorized"])
        with self.assertRaises(ValueError):
            annual_aggregate(rows, v.COMMON, role="selection_probe")

    def test_missing_or_reordered_year_rejects(self):
        for rows in (self.rows[:2], list(reversed(self.rows)), self.rows+[self.rows[0]]):
            with self.assertRaises(ValueError):
                annual_aggregate(rows, v.COMMON, role="selection_probe")

    def test_mixed_accounts_and_candidate_ids_reject(self):
        for field in ("candidate_id", "execution_id"):
            rows = deepcopy(self.rows)
            rows[1]["provenance"][field] = "other"
            with self.assertRaises(ValueError):
                annual_aggregate(rows, v.COMMON, role="selection_probe")

    def test_wrong_metric_unit_rejects(self):
        rows = deepcopy(self.rows)
        next(m for m in rows[0]["metrics"] if m["metric_id"].endswith("economic_utility"))["unit"] = "ratio"
        with self.assertRaises(ValueError):
            annual_aggregate(rows, v.COMMON, role="selection_probe")

    def test_expected_candidate_and_execution_bindings(self):
        for arg in (dict(expected_candidate="other"), dict(expected_execution="other")):
            with self.assertRaises(ValueError):
                annual_aggregate(self.rows, v.COMMON, role="selection_probe", **arg)

    def test_invalid_numeric_needs_null_reason(self):
        rows = deepcopy(self.rows)
        next(m for m in rows[0]["metrics"] if m["metric_id"].endswith("economic_utility"))["value"] = float("nan")
        with self.assertRaises(ValueError):
            annual_aggregate(rows, v.COMMON, role="selection_probe")

    def test_annual_local_policy_explicitly_missing(self):
        self.assertEqual(len(v.MISSING_LOCAL), 2)
        self.assertIn("weighted_environment_mean_v1", v.MISSING_LOCAL[0]["reason"])


class CustodyAndRequestTests(unittest.TestCase):
    def test_financial_modules_not_imported(self):
        assert_cold_boundary(v.__name__, "tools.mode5_research.panels",
            ("quantbt.core", "quantbt.endpoint", "quantbt.backtester", "_quantbt_native", "quantbt.optimization"))

    def test_sealed_bytes_and_exclusive_append(self):
        with TemporaryDirectory(prefix="probe-views-", dir=os.environ.get("PROBE_VIEW_FIXTURE_ROOT")) as root:
            path = Path(root) / "synthetic.json"
            pin = v.custody.write_new(path, dict(synthetic=True))
            self.assertEqual(v.sealed_json(pin), dict(synthetic=True))
            with self.assertRaises(FileExistsError):
                v.custody.write_new(path, dict(replaced=True))
            with self.assertRaises(ValueError):
                v.sealed_bytes(pin | dict(sha256="0"*64))

    def test_exact_request_roster_source_and_role(self):
        execution = dict(index=0, center=0, role="selection_probe", candidate_id="c", request=dict(role="selection_probe"))
        evaluation = dict(cell=dict(path="cell", bytes=1, sha256="hash"), paths=dict(path="path", bytes=2, sha256="hash"))
        requests = [dict(execution_index=0, center=0, role="selection_probe", candidate_id="c", environment_id=year,
            exact_execution_request=execution["request"], source_cell=evaluation["cell"], source_path=evaluation["paths"],
            status="MISSING_SEALED_ANNUAL_METRIC_VIEW", request_type="REDUCE_RETAINED_CONTINUOUS_PATH_NO_ACCOUNT_RERUN",
            required_metrics=["economic_utility", "net_return", "drawdown", "daily_loss_es", "daily_count"]) for year in v.ANNUAL]
        self.assertEqual(set(v.registered_request(requests, execution, evaluation)), set(v.ANNUAL))
        for key, value in ("role", "local_validation"), ("source_path", dict(path="other")), ("candidate_id", "other"):
            broken = deepcopy(requests)
            broken[0][key] = value
            with self.assertRaises(ValueError):
                v.registered_request(broken, execution, evaluation)
        with self.assertRaises(ValueError):
            v.registered_request(requests[:2], execution, evaluation)

    def test_no_rerun_or_missing_source_authorized(self):
        with self.assertRaises(ValueError):
            v.registered_request([], dict(index=0, role="selection_probe"), {})

    def test_registered_source_remains_existing_panel(self):
        with patch.object(p, "continuous_annual_rows", wraps=p.continuous_annual_rows) as producer:
            synthetic()
            producer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
