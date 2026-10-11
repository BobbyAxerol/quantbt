"""Synthetic cold recovery evidence only; no strategies or financial engines."""

from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from time import time_ns
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from quantbt import Fill, OrderSide
from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations, reduce_account
from quantbt.mode5.artifacts import file_identity
from tools.mode5_admission.ledger import reconcile_fills
from tools.mode5_diagnostics.identity import canonical, digest
from tools.mode5_research.panels import HOUR_NS, DAY_NS, VerifiedCell, UtilityPolicy, _ns, continuous_annual_rows
from tools.mode5_research.protocol import ResearchProtocol
from tools.mode5_research.recovery_cells import load_recovery_cell, RECOVERY_STATUS, RECOVERY_SCHEMA
from tools.mode5_statistics.moments import classical_psr, moments


class SyntheticRecovery:
    def __init__(self, root, *, empty=False, control=False):
        self.root, self.worker = root, root / "worker"
        self.worker.mkdir()
        (self.worker / "sources").mkdir()
        self.pins, self.documents, self.approvals = {}, {}, {}
        self.cutoff = time_ns() + 60_000_000_000
        self.protocol = ResearchProtocol()
        start, stop = _ns("2021-01-01"), _ns("2024-01-01")
        self.times = np.arange(start, stop, HOUR_NS, dtype=np.int64)
        index = pd.DatetimeIndex(pd.to_datetime(self.times, utc=True))
        self.contract = ReportingContractV1(scope="full", unit="account_period", currency="TEST",
            baseline_equity=1000., baseline_time_ns=start-HOUR_NS, scope_end_ns=stop-HOUR_NS,
            sampling="observed_daily_utc", annual_periods=365., equity_clock="bar_close")
        self.request = dict(alpha="SYNTHETIC", params={"coordinate": 2.}, candidate_id=digest("candidate"),
            design_id=digest("design"), proposal_row=0, role="NEUTRAL_BROAD_DISCOVERY",
            start="2021-01-01", stop="2024-01-01", symbol="TEST", max_feedback_runs=4096,
            account_mode="continuous_development_2021_2023")
        original = dict(protocol=asdict(self.protocol), protocol_id=self.protocol.identity,
            financial_outcomes_used_to_choose_design=False, forward_selection=False,
            symbols={"SYNTHETIC": "TEST"}, created_at="2020-12-01T00:00:00+00:00")
        design = dict(alpha="SYNTHETIC", design_id=self.request["design_id"], rows=[dict(
            row_id=0, candidate_id=self.request["candidate_id"], requested={"coordinate": 2.1},
            effective={"coordinate": 2.}, direction="branch:0", role="exploration",
            admitted=True, status="READY", duplicate_of=None)])
        config = dict(account=dict(initial_capital=1000., contract_size=1., fee_rate=0., use_funding=False),
            execution_contract="event_lifecycle_v3_next_open", timeframe="1h",
            terminal_policy="mark_only_no_hidden_flatten",
            score_start="2024-01-01", score_stop_exclusive="2024-04-01")
        for name, value in (("original_registration", original), ("design", design), ("economic_config", config)):
            self.write(name, root / (name + ".json"), value)
        artifact = root / "synthetic_native.bin"
        artifact.write_bytes(b"inert native identity, never loaded\n")
        native = file_identity(artifact)
        self.write("native_gate", root / "gate.json", dict(status="PASS", artifact=native))
        calendar = pd.date_range("2020-01-01", "2024-01-01", freq="h", inclusive="left", tz="UTC")
        close = np.full(len(calendar), 100.)
        if not empty:
            close[calendar.get_loc(index[25]):] = 110.
            close[calendar.get_loc(index[100]):] = 120.
        market = root / "synthetic_market.csv.gz"
        pd.DataFrame(dict(datetime=calendar, symbol="TEST", close=close)).to_csv(
            market, index=False, compression="gzip")
        witness = file_identity(market)
        source_pins = []
        for role in ("alpha_source", "finance_driver", "recovery_driver"):
            path = root / (role + ".py")
            path.write_text("# Inert synthetic source identity; never executed.\n", encoding="ascii")
            pin = file_identity(path)
            self.approvals[role] = pin
            source_pins.append(pin)
        metadata = root / "synthetic_market.json"
        metadata.write_text(canonical(dict(development=witness)), encoding="ascii")
        self.approvals["market_metadata"] = file_identity(metadata)
        source_pins.append(self.approvals["market_metadata"])
        source_pins.extend(self.pins[name] for name in ("original_registration", "design", "economic_config"))
        snapshots = []
        for number, pin in enumerate(source_pins):
            path = self.worker / "sources" / f"{number:02d}-snapshot"
            path.write_bytes(Path(pin["path"]).read_bytes())
            snapshots.append(dict(original=pin, retained=file_identity(path)))
        worker = dict(request=self.request, pins=source_pins + [native, witness],
            native_gate=self.pins["native_gate"], source_snapshots=snapshots,
            guard_policy="boundary_full_hash_v1", methodology_changed=False,
            control=control, dense_owner_retained=control, python_oracle_calls_planned=int(control),
            cap_seconds=900., reserve_bytes=5*1024**3, retained_limit_bytes=256*1024**2, scratch=[])
        self.write("worker_registration", self.worker / "registration.json", worker)
        objects = [] if empty else [
            Fill(timestamp=index[1], symbol="TEST", side=OrderSide.BUY, qty=1., price=100., fee=0., order_id="entry"),
            Fill(timestamp=index[25], symbol="TEST", side=OrderSide.SELL, qty=1., price=110., fee=0., order_id="exit"),
            Fill(timestamp=index[100], symbol="TEST", side=OrderSide.BUY, qty=1., price=120., fee=0., order_id="open"),
        ]
        ledger = reconcile_fills(index, close[-len(self.times):], objects, initial_capital=1000., fee_rate=0.)
        fills = [dict(timestamp=str(fill.timestamp), symbol=fill.symbol, side=fill.side.value,
            qty=fill.qty, price=fill.price, fee=fill.fee, order_id=fill.order_id, liquidity="taker",
            metadata=dict(private_coordinate=2., source_path="/synthetic/private/source.py")) for fill in objects]
        self.write("fills", self.worker / "fills.json", fills)
        self.write("campaigns", self.worker / "campaigns.json", dict(closed=ledger.closed_campaigns, open=ledger.open_campaigns))
        coverage = ReportingCoverageV1(result_identity="synthetic", producer="test", profile="compact",
            ledger="omitted", retained_rows=0, dropped_rows=0, reason="separate synthetic ledgers")
        obs = AccountObservations(times_ns=self.times, equity=ledger.equity, coverage=coverage)
        obs = obs.with_derived_returns(self.contract, partial_mask=np.zeros(1095, dtype=bool), witness="synthetic marks")
        report = reduce_account(obs, self.contract, backend="python")
        self.arrays = dict(times_ns=self.times, equity=ledger.equity, positions=ledger.positions,
            fees=ledger.fees, funding=np.zeros(len(index)), turnover=ledger.turnover,
            margin=np.zeros(2*len(index)), daily_returns=obs.returns.values)
        self.paths()
        metrics = {target: report.metric(source).value for source, target in
            (("account.total_return", "total_return"), ("drawdown.max_depth", "max_drawdown"), ("period.sharpe", "sharpe"))}
        metrics.update(daily_count=1095, account_mode=self.request["account_mode"],
            psr=classical_psr(moments(obs.returns.values)).to_metadata(),
            private_payload=dict(coordinate=2., path="/synthetic/private/source.py"))
        owner = None
        if control:
            path = self.worker / "actual_owner.pkl"
            path.write_bytes(b"inert pickle placeholder; reader must never load it")
            owner = file_identity(path)
        self.write("result", self.worker / "result.json", dict(status=RECOVERY_STATUS,
            request=self.request, typed_lifecycle_terminal_parity=True, original_compiler_parity=True,
            future_tape_opened=False, clean_oos=False, panel_complete=False,
            registration=self.pins["worker_registration"], paths=self.pins["paths"],
            fills_ledger=self.pins["fills"], campaigns_ledger=self.pins["campaigns"],
            native_feedback_calls=1 if empty else 7, final_native_calls=2 if control else 1,
            python_oracle_calls=int(control), owner=owner, bar_steps=26280, bar_retries=0,
            fills=len(fills), closed_campaigns=len(ledger.closed_campaigns), open_campaigns=len(ledger.open_campaigns),
            accounting_residual=0., wall_seconds=1., peak_rss_mib=100., metrics=metrics))

    def write(self, name, path, value):
        self.documents[name] = json.loads(canonical(value))
        path.write_text(canonical(value), encoding="ascii")
        self.pins[name] = file_identity(path)

    def revise(self, name, mutate):
        value = self.documents[name]
        mutate(value)
        self.write(name, Path(self.pins[name]["path"]), value)
        links = dict(worker_registration="registration", paths="paths", campaigns="campaigns_ledger", fills="fills_ledger")
        if name in links:
            result = self.documents["result"]
            result[links[name]] = self.pins[name]
            self.write("result", Path(self.pins["result"]["path"]), result)

    def paths(self):
        path = self.worker / "paths.npz"
        np.savez_compressed(path, **self.arrays)
        self.pins["paths"] = file_identity(path)
        if "result" in self.documents:
            self.revise("result", lambda row: row.update(paths=self.pins["paths"]))

    def load(self, **changes):
        arguments = dict(artifact_pins=self.pins, approved_source_pins=self.approvals,
            contract=self.contract, cutoff_ns=self.cutoff, study_id="synthetic_study", diagnostic_revision="cold_01")
        return load_recovery_cell(self.pins["result"]["path"], **(arguments | changes))


class RecoveryCellsTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="mode5-recovery-cells-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def fixture(self, **kwargs):
        return SyntheticRecovery(self.root, **kwargs)

    def test_completed_bulk_account_reuses_shared_reducers_and_preserves_coverage(self):
        fixture = self.fixture()
        cell = fixture.load()
        self.assertIsInstance(cell, VerifiedCell)
        self.assertEqual(cell.compute_status, RECOVERY_STATUS)
        self.assertEqual(cell.recovery_schema, RECOVERY_SCHEMA)
        self.assertEqual(cell.actual_execution_calls, 8)
        self.assertEqual(cell.visited_bars, 8*26280)
        self.assertEqual(cell.python_oracle_calls, 0)
        self.assertIn("NO_FRESH_PYTHON_ORACLE", cell.oracle_coverage)
        rows = continuous_annual_rows(cell, utility_policy=UtilityPolicy("synthetic_preference", 1., 1.))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].closed_campaigns, 1)
        self.assertEqual(rows[0].open_campaigns, 1)
        self.assertTrue(all(not row.clean_oos for row in rows))
        self.assertIn("Not historical", cell.provenance.outcome_timing_disclosure)

    def test_fresh_control_keeps_real_call_counts_and_never_unpickles(self):
        fixture = self.fixture(control=True)
        with patch("pickle.load", side_effect=AssertionError("unsafe owner load")):
            cell = fixture.load()
        self.assertEqual(cell.actual_execution_calls, 10)
        self.assertEqual(cell.oracle_coverage, "FRESH_ORIGINAL_PYTHON_CONTROL")

    def test_no_trade_is_real_empty_support_and_undefined_sharpe(self):
        cell = self.fixture(empty=True).load()
        self.assertIsNone(json.loads(cell.original_metrics_json)["sharpe"])
        self.assertEqual(json.loads(cell.original_metrics_json)["psr"]["status"], "UNDEFINED")
        self.assertIsNone(json.loads(cell.original_metrics_json)["psr"]["value"])
        rows = continuous_annual_rows(cell, utility_policy=UtilityPolicy("synthetic_preference", 1., 1.))
        self.assertTrue(all(row.status == "VALID_NO_TRADE" for row in rows))
        self.assertTrue(all(row.closed_campaigns == row.open_campaigns == row.fills == 0 for row in rows))

    def test_returned_account_contains_no_parameters_source_or_private_paths(self):
        fixture = self.fixture()
        cell = fixture.load()
        public = canonical(asdict(cell.provenance)) + cell.fills_json + cell.campaigns_json + cell.original_metrics_json
        self.assertNotIn("coordinate", public)
        self.assertNotIn("source_path", public)
        self.assertNotIn("/synthetic/private", public)
        self.assertNotIn(str(self.root), public)

    def test_source_snapshots_survive_later_live_source_changes(self):
        fixture = self.fixture()
        Path(fixture.approvals["recovery_driver"]["path"]).write_text("# later unapproved revision\n")
        fixture.load()

    def test_missing_external_pin_and_unapproved_source_fail_closed(self):
        fixture = self.fixture()
        missing = dict(fixture.pins)
        missing.pop("fills")
        with self.assertRaises(ValueError):
            fixture.load(artifact_pins=missing)
        approvals = dict(fixture.approvals)
        approvals["recovery_driver"] = approvals["finance_driver"]
        with self.assertRaises(ValueError):
            fixture.load(approved_source_pins=approvals)

    def test_result_and_snapshot_tampering_fail_closed(self):
        fixture = self.fixture()
        path = Path(fixture.pins["result"]["path"])
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaises(ValueError):
            fixture.load()
        path.write_bytes(original)
        snapshot = fixture.documents["worker_registration"]["source_snapshots"][0]["retained"]
        Path(snapshot["path"]).write_bytes(b"tampered retained source")
        with self.assertRaises(ValueError):
            fixture.load()

    def test_censored_status_or_failure_sibling_is_not_legacy_pass(self):
        fixture = self.fixture()
        for status in ("CENSORED", "FAIL_OR_CENSORED", "PASS"):
            with self.subTest(status=status):
                fixture.revise("result", lambda row: row.update(status=status))
                with self.assertRaises(ValueError):
                    fixture.load()
        fixture.revise("result", lambda row: row.update(status=RECOVERY_STATUS))
        (fixture.worker / "failure.json").write_text("{}")
        with self.assertRaises(ValueError):
            fixture.load()

    def test_missing_file_and_orphan_paths_are_rejected(self):
        fixture = self.fixture()
        pin = fixture.pins["fills"]
        original = Path(pin["path"]).read_bytes()
        Path(pin["path"]).unlink()
        with self.assertRaises(ValueError):
            fixture.load()
        Path(pin["path"]).write_bytes(original)
        alternate = self.root / "orphan.npz"
        alternate.write_bytes(Path(fixture.pins["paths"]["path"]).read_bytes())
        pins = fixture.pins | dict(paths=file_identity(alternate))
        with self.assertRaises(ValueError):
            fixture.load(artifact_pins=pins)

    def test_parameter_role_and_range_mismatch_are_rejected_even_with_new_seals(self):
        fixture = self.fixture()
        original = json.loads(canonical(fixture.request))
        for update in (dict(params={"coordinate": True}), dict(params={"coordinate": 3.}),
                       dict(params={"coordinate": 2}),
                       dict(proposal_row=1), dict(role="FORWARD_SELECTION"), dict(start="2022-01-01")):
            with self.subTest(update=update):
                request = original | update
                fixture.revise("worker_registration", lambda row: row.update(request=request))
                fixture.revise("result", lambda row: row.update(request=request))
                with self.assertRaises(ValueError):
                    fixture.load()

    def test_future_data_artifact_and_wrong_report_contract_fail_closed(self):
        fixture = self.fixture()
        with self.assertRaises(ValueError):
            fixture.load(data_cutoff_ns=_ns("2023-01-01"))
        with self.assertRaises(ValueError):
            fixture.load(contract=replace(fixture.contract, baseline_equity=2000.))
        with self.assertRaises(ValueError):
            fixture.load(contract=replace(fixture.contract, annual_periods=365.25))
        with self.assertRaises(ValueError):
            fixture.load(contract=replace(fixture.contract, risk_free_per_period=.01))
        with self.assertRaises(ValueError):
            fixture.load(contract=replace(fixture.contract, variance_ddof=0))
        path = Path(fixture.pins["result"]["path"])
        os.utime(path, ns=(fixture.cutoff+DAY_NS, fixture.cutoff+DAY_NS))
        with self.assertRaises(ValueError):
            fixture.load()

    def test_native_artifact_must_be_exact_and_still_available(self):
        fixture = self.fixture()
        path = Path(fixture.documents["native_gate"]["artifact"]["path"])
        path.write_bytes(b"unapproved native artifact")
        with self.assertRaises(ValueError):
            fixture.load()

    def test_full_finite_calendar_and_daily_returns_are_required(self):
        fixture = self.fixture()
        original = {name: values.copy() for name, values in fixture.arrays.items()}
        for key, change in (("times_ns", lambda a: a.__setitem__(1, a[0])),
                            ("equity", lambda a: a.__setitem__(5, np.nan)),
                            ("daily_returns", lambda a: a.__setitem__(0, .5))):
            with self.subTest(key=key):
                fixture.arrays = {name: values.copy() for name, values in original.items()}
                change(fixture.arrays[key])
                fixture.paths()
                with self.assertRaises(ValueError):
                    fixture.load()

    def test_metric_and_actual_call_coverage_mismatch_are_rejected(self):
        fixture = self.fixture()
        fixture.revise("result", lambda row: row["metrics"].update(total_return=.5))
        with self.assertRaises(ValueError):
            fixture.load()
        fixture.revise("result", lambda row: row["metrics"].update(total_return=.01))
        fixture.revise("result", lambda row: row.update(python_oracle_calls=1))
        with self.assertRaises(ValueError):
            fixture.load()

    def test_dated_campaign_support_and_fill_arithmetic_must_reconcile(self):
        fixture = self.fixture()
        original = json.loads(canonical(fixture.documents["campaigns"]))
        fixture.revise("campaigns", lambda row: row["closed"][0].update(net_pnl=50.))
        with self.assertRaises(ValueError):
            fixture.load()
        fixture.revise("campaigns", lambda row: row.update(original))
        fixture.revise("fills", lambda rows: rows[0].update(qty=2.))
        with self.assertRaises(ValueError):
            fixture.load()

    def test_duplicate_json_and_false_support_counts_are_rejected(self):
        fixture = self.fixture()
        fixture.revise("result", lambda row: row.update(fills=99))
        with self.assertRaises(ValueError):
            fixture.load()
        path = Path(fixture.pins["result"]["path"])
        data = b'{"status":"PASS","status":"CENSORED"}'
        path.write_bytes(data)
        fixture.pins["result"] = dict(path=str(path), bytes=len(data), sha256=sha256(data).hexdigest())
        with self.assertRaises(ValueError):
            fixture.load()

    def test_missing_dense_control_owner_is_not_oracle_coverage(self):
        fixture = self.fixture(control=True)
        Path(fixture.documents["result"]["owner"]["path"]).unlink()
        with self.assertRaises(ValueError):
            fixture.load()

    def test_orphan_source_snapshot_is_rejected(self):
        fixture = self.fixture()
        fixture.revise("worker_registration", lambda row: row["source_snapshots"].pop())
        with self.assertRaises(ValueError):
            fixture.load()

    def test_known_metric_fields_cannot_smuggle_parameters_or_paths(self):
        fixture = self.fixture()
        fixture.revise("result", lambda row: row["metrics"].update(fees={"private_parameter": 2.}))
        with self.assertRaises(ValueError):
            fixture.load()
        fixture.revise("result", lambda row: row["metrics"].update(fees=0.))
        fixture.revise("result", lambda row: row["metrics"]["psr"].update(
            components=[["private_parameter", "/synthetic/private/source.py"]]))
        with self.assertRaises(ValueError):
            fixture.load()


if __name__ == "__main__":
    unittest.main()
