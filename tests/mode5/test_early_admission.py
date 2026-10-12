"""Synthetic earlier formats; no private strategies or financial executions."""

from dataclasses import asdict
from importlib import import_module
from io import BytesIO
import copyreg
import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from quantbt import Fill, OrderSide, OrderType
from quantbt.core.orders import OrderCommand
from quantbt.core.results import BacktestResultV2
from quantbt.mode5.artifacts import file_identity
from tools.mode5_admission import conformance, ledger
from tools.mode5_diagnostics.identity import canonical, digest
from tools.mode5_research import early_admission as early
from tools.mode5_research.panels import UtilityPolicy, continuous_annual_rows
from tools.mode5_research.recovery_cells import RECOVERY_STATUS

from test_recovery_cells import SyntheticRecovery


class SyntheticEarly(SyntheticRecovery):
    def __init__(self, root, *, qualified=False, empty=False):
        super().__init__(root, empty=qualified or empty, control=not qualified)
        self.qualified = qualified
        self.documents["economic_config"]["account"]["leverage"] = 1.
        self.write("economic_config", root / "economic_config.json", self.documents["economic_config"])
        self.type_pins = {name: file_identity(import_module(name).__file__) for name in early._OWNER_TYPES}
        if qualified:
            self._qualified()
        else:
            self._control()

    def _control(self):
        for name, module in (("conformance", conformance), ("ledger", ledger)):
            self.approvals[name] = file_identity(module.__file__)
        worker = self.documents["worker_registration"]
        worker.pop("source_snapshots")
        worker.pop("dense_owner_retained")
        native = self.documents["native_gate"]["artifact"]
        witness = json.loads(Path(self.approvals["market_metadata"]["path"]).read_text())["development"]
        worker["pins"] = [*self.approvals.values(), native, witness,
                          *(self.pins[name] for name in early._AUTHORITIES)]
        self.write("worker_registration", self.worker / "registration.json", worker)
        index = pd.DatetimeIndex(pd.to_datetime(self.times, utc=True))
        objects = [Fill(timestamp=pd.Timestamp(row["timestamp"]), symbol=row["symbol"],
            side=OrderSide(row["side"]), qty=row["qty"], price=row["price"], fee=row["fee"],
            order_id=row["order_id"], metadata=row["metadata"]) for row in self.documents["fills"]]
        market = pd.read_csv(witness["path"], usecols=["close"])
        self.owner = BacktestResultV2(equity=pd.Series(self.arrays["equity"], index=index),
            returns=pd.Series(np.zeros(len(index)), index=index),
            positions=pd.DataFrame(self.arrays["positions"], index=index, columns=["TEST"]),
            closes=pd.DataFrame(market.close.to_numpy()[-len(index):], index=index, columns=["TEST"]),
            symbols=["TEST"], initial_capital=1000., leverage=1., fills=tuple(objects),
            fees=pd.Series(self.arrays["fees"], index=index), funding=pd.Series(self.arrays["funding"], index=index),
            margin=pd.DataFrame(self.arrays["margin"].reshape(-1, 2), index=index),
            diagnostics=pd.DataFrame(dict(turnover=self.arrays["turnover"]), index=index),
            metadata=dict(order_events=pd.DataFrame([dict(event_name="fill", timestamp=f.timestamp,
                order_id=f.order_id) for f in objects], columns=["event_name", "timestamp", "order_id"]),
                execution_contract_id="event_lifecycle_v3_next_open",
                native_event_backend_requested="rust", native_event_backend_resolved="rust"))
        self.commands = tuple(OrderCommand(timestamp=f.timestamp, symbol=f.symbol, side=f.side,
            order_type=OrderType.MARKET, qty=f.qty, order_id=f.order_id) for f in objects)
        result = self.documents["result"]
        for key in ("registration", "fills_ledger", "campaigns_ledger"):
            result.pop(key)
        result.update(result_hash=conformance.result_signature(self.owner), command_count=len(self.commands))
        self.save_owner()

    def save_owner(self, *, update_identity=True):
        path = self.worker / "actual_owner.pkl"
        path.write_bytes(pickle.dumps((self.owner, self.commands), protocol=4))
        self.pins["owner"] = file_identity(path)
        result = self.documents["result"]
        result["owner"] = self.pins["owner"]
        if update_identity:
            result["result_hash"] = conformance.result_signature(self.owner)
        self.write("result", self.worker / "result.json", result)

    def _qualified(self):
        witness = json.loads(Path(self.approvals["market_metadata"]["path"]).read_text())["development"]
        self.approvals["orchestrator"] = self.approvals["recovery_driver"]
        source = self.approvals["finance_driver"]
        self.pins["native_artifact"] = self.documents["native_gate"]["artifact"]
        self.write("resources", self.root / "resources.json", dict(resource_protocol=asdict(self.protocol)))
        budget = dict(original_registration=self.pins["original_registration"],
            original_resource_registration=self.pins["resources"], scientific_protocol_changed=False,
            core_or_alpha_changed=False, economic_outcome_filtering=False, publication=False,
            automatic_phase_promotion=False, numeric_threads_per_worker=1, financial_workers=1,
            created_at="2020-12-01T00:00:00+00:00", source=source)
        self.write("execution_budget", self.root / "budget.json", budget)
        analysis = dict(registration=self.pins["original_registration"], execution_budget=self.pins["execution_budget"],
            role="REVIEWED_EXPLORATORY_DEVELOPMENT", clean_independent_claim=False,
            forward_snapshot_allowed=False, incomplete_matrix_is_complete_phase=False,
            screening=dict(exact_sobol_claim=False), outcome_timing_disclosure="Synthetic reviewed development",
            created_at="2020-12-01T00:00:00+00:00", source=source,
            environment_contract=dict(mode="CONTINUOUS_PATH_ATTRIBUTION", account_reset=False,
                annual_sharpe_average_is_whole_sharpe=False, overlapping_families_independent=False,
                annual_days=365., years=[2021, 2022, 2023]))
        self.write("analysis", self.root / "analysis.json", analysis)
        signature = dict(economic_config=digest("synthetic economics"), market=digest("synthetic market"))
        identities = {name:digest(name) for name in
            ("qualified_recovery_identity", "qualified_empty_ledger_identity", "qualified_materialization_identity")}
        registered = dict(request=self.request, candidate_index=0, original_request_unchanged=True,
            source_schema_design_science_unchanged=True, signature=signature,
            original_finance=source, controller_source=self.approvals["orchestrator"],
            critical_sources=[*self.approvals.values(), witness, self.pins["native_artifact"],
                              *(self.pins[name] for name in early._AUTHORITIES)], **identities)
        self.write("recovery_registration", self.root / "qualified_registration.json", registered)
        access = dict(allowed_stop="2024-01-01", future_tape_opened=False,
            original_contract_preserved=True, fresh_strategy_and_account=True, mutable_strategy_or_account_reused=False,
            signature_before=signature, signature_after=signature, shared_market_hash=signature["market"],
            qualified_recovery_identity=identities["qualified_recovery_identity"],
            orchestrator=self.approvals["orchestrator"], witness=witness)
        self.write("access", self.worker / "development_access.json", access)
        self.write("request", self.worker / "request.json", self.request)
        self.write("cell", self.worker / "cell.json", dict(status="PASS", request=self.request,
            path=self.pins["paths"], clean_oos=False, scored_bars=26280, scored_days=1095,
            actual_execution_calls=3, visited_bars=3*26280, wall_seconds=1., peak_rss_mib=100.,
            metrics=self.documents["result"]["metrics"], support=dict(fills=0, closed_campaigns=0, open_campaigns=0),
            route="original_qualified_access", execution_key=digest("original execution")))
        self.write("qualified_receipt", self.root / "qualified.json", dict(
            status="PASS_CURRENT_ORIGINAL_NUMERIC_FILL_EVENT_PARITY", cell=self.pins["cell"],
            original_finance=source, source=self.approvals["orchestrator"],
            original_native_account_passes=2, original_python_account_passes=1,
            added_financial_passes_for_supplement=0, actual_account_passes=3, actual_account_bars=3*26280,
            terminal_audit_status="NOT_RUN_SEPARATE_POST_RUN_AUDIT", cold_account_verification_status="NOT_RUN",
            **identities))
        self.access_mapping = dict(finance_driver=source, orchestrator=self.approvals["orchestrator"], witness=witness)
        self.refresh_supervisor()

    def refresh_supervisor(self):
        pins = [self.pins[name] for name in ("cell", "request", "access", "paths", "campaigns", "fills")]
        self.write("supervisor_receipt", self.root / "supervisor.json", dict(status="PASS_NO_DELETION",
            fault=None, all_owned_workers_reaped=True, live_owned_financial_workers=0,
            source_market_written=False, shared_active_scratch_touched=False, deleted_paths=[], retained_manifest=pins))

    def load(self, **changes):
        args = dict(artifact_pins=self.pins, approved_source_pins=self.approvals,
            expected_candidate_index=0, contract=self.contract, cutoff_ns=self.cutoff,
            study_id="synthetic_study", diagnostic_revision="early_01")
        if self.qualified:
            return early.load_qualified_access_cell(self.pins["cell"]["path"],
                **(args | dict(access_mapping=self.access_mapping) | changes))
        return early.load_early_control_cell(self.pins["result"]["path"],
            **(args | dict(approved_owner_type_pins=self.type_pins) | changes))


class EarlyAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="mode5-early-admission-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def fixture(self, **options):
        return SyntheticEarly(self.root, **options)

    def test_early_control_has_real_schema_status_calls_and_shared_views(self):
        f = self.fixture()
        cell = f.load()
        self.assertIs(type(cell), early.EarlyCell)
        self.assertEqual(cell.reader_schema, early.EARLY_CONTROL_SCHEMA)
        self.assertEqual(cell.compute_status, RECOVERY_STATUS)
        self.assertEqual(cell.native_feedback_calls, 7)
        self.assertEqual(cell.normal_native_calls, 2)
        self.assertEqual(cell.actual_execution_calls, 10)
        self.assertEqual(cell.python_oracle_calls, 1)
        self.assertEqual(cell.visited_bars, 10*26280)
        self.assertEqual(cell.execution_work_metadata, dict(visited_bars=10*26280,
            reason="ORIGINAL_FULL_MARKET_REQUEST_BARS", full_account_passes=3,
            full_account_visited_bars=3*26280, native_feedback_calls=7,
            visited_bar_unit="submitted full market request bars, not internal kernel steps",
            internal_kernel_steps=None))
        refs = dict(cell.provenance.evidence_refs)
        self.assertEqual(refs["owner"], f.pins["owner"]["sha256"])
        self.assertEqual(refs["worker_registration"], f.pins["worker_registration"]["sha256"])
        self.assertIn("derived_campaigns", refs)
        self.assertNotIn("campaigns", refs)
        rows = continuous_annual_rows(cell, utility_policy=UtilityPolicy("synthetic", 1., 1.))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].closed_campaigns, 1)
        self.assertEqual(rows[0].open_campaigns, 1)
        self.assertIn("no retained source snapshots", cell.provenance.outcome_timing_disclosure)
        self.assertFalse(any(row.clean_oos for row in rows))

    def test_qualified_access_keeps_original_status_mapping_and_terminal_gaps(self):
        f = self.fixture(qualified=True)
        with patch.object(early, "_owner", side_effect=AssertionError("qualified empty reader cannot unpickle")):
            cell = f.load()
        self.assertEqual(cell.reader_schema, early.QUALIFIED_ACCESS_SCHEMA)
        self.assertEqual(cell.compute_status, "PASS")
        self.assertEqual(cell.provenance.data_role, "REVIEWED_EXPLORATORY_DEVELOPMENT")
        self.assertEqual(cell.actual_execution_calls, 3)
        self.assertIsNone(cell.native_feedback_calls)
        self.assertIsNone(cell.normal_native_calls)
        self.assertEqual(cell.visited_bars, 3*26280)
        self.assertEqual(cell.execution_work_metadata, dict(visited_bars=3*26280,
            reason="ORIGINAL_QUALIFIED_FULL_ACCOUNT_PASSES", full_account_passes=3,
            full_account_visited_bars=3*26280, native_feedback_calls=None,
            visited_bar_unit="submitted full market request bars, not internal kernel steps",
            internal_kernel_steps=None))
        self.assertIn("Original cold account verification: NOT_RUN", cell.source_limitations)
        self.assertNotIn("finance_driver", f.documents["access"])
        refs = dict(cell.provenance.evidence_refs)
        self.assertEqual(refs["supervisor_receipt"], f.pins["supervisor_receipt"]["sha256"])
        self.assertEqual(refs["qualified_receipt"], f.pins["qualified_receipt"]["sha256"])
        rows = continuous_annual_rows(cell, utility_policy=UtilityPolicy("synthetic", 1., 1.))
        self.assertTrue(all(row.status == "VALID_NO_TRADE" for row in rows))
        self.assertTrue(all(row.metric("sharpe").value is None for row in rows))

    def test_caller_pins_missing_tampered_or_orphan_reject(self):
        f = self.fixture()
        incomplete = dict(f.pins)
        incomplete.pop("owner")
        with self.assertRaises(ValueError):
            f.load(artifact_pins=incomplete)
        old = Path(f.pins["owner"]["path"]).read_bytes()
        Path(f.pins["owner"]["path"]).write_bytes(old+b"x")
        with self.assertRaises(ValueError):
            f.load()
        Path(f.pins["owner"]["path"]).write_bytes(old)
        alternate = dict(f.pins)
        copy = self.root / "not_original.pkl"
        copy.write_bytes(old)
        alternate["owner"] = file_identity(copy)
        with self.assertRaises(ValueError):
            f.load(artifact_pins=alternate)

    def test_unapproved_historical_source_or_type_projection_reject(self):
        f = self.fixture()
        approvals = dict(f.approvals)
        approvals.pop("recovery_driver")
        with self.assertRaises(ValueError):
            f.load(approved_source_pins=approvals)
        types = dict(f.type_pins)
        types.pop("quantbt.core.orders")
        with self.assertRaises(ValueError):
            f.load(approved_owner_type_pins=types)

    def test_later_historical_driver_change_is_disclosed_not_current_source_approval(self):
        f = self.fixture()
        Path(f.approvals["recovery_driver"]["path"]).write_text("# later unapproved helper\n")
        cell = f.load()
        self.assertIn("no retained source snapshots", " ".join(cell.source_limitations))

    def test_owner_path_different_but_each_independently_sealed_reject(self):
        f = self.fixture()
        f.owner.positions.iloc[5, 0] = 3.
        f.save_owner()
        with self.assertRaises(ValueError):
            f.load()

    def test_same_bar_fill_sequence_and_lifecycle_identity_reject(self):
        f = self.fixture()
        f.owner.metadata["order_events"] = f.owner.metadata["order_events"].iloc[::-1]
        f.save_owner()
        with self.assertRaises(ValueError):
            f.load()

    def test_support_calls_and_terminal_prefix_reject(self):
        f = self.fixture()
        result = f.documents["result"]
        for key, value in (("fills", 0), ("final_native_calls", 1), ("python_oracle_calls", 0), ("bar_steps", 3)):
            original = result[key]
            result[key] = value
            f.write("result", self.worker_path(f), result)
            with self.assertRaises(ValueError):
                f.load()
            result[key] = original
        f.write("result", self.worker_path(f), result)

    @staticmethod
    def worker_path(f):
        return f.worker / "result.json"

    def test_original_index_effective_parameters_role_and_future_reject(self):
        f = self.fixture()
        for index in (True, 1, -1):
            with self.assertRaises(ValueError):
                f.load(expected_candidate_index=index)
        request = f.documents["result"]["request"]
        for key, value in (("role", "FORWARD"), ("stop", "2025-01-01"), ("params", {"coordinate": 9.})):
            old = request[key]
            request[key] = value
            worker = f.documents["worker_registration"]
            worker["request"] = request
            f.write("worker_registration", f.worker / "registration.json", worker)
            f.write("result", self.worker_path(f), f.documents["result"])
            with self.assertRaises(ValueError):
                f.load()
            request[key] = old

    def test_current_modern_schema_is_not_silently_downgraded(self):
        f = self.fixture()
        f.documents["result"]["registration"] = f.pins["worker_registration"]
        f.write("result", self.worker_path(f), f.documents["result"])
        with self.assertRaises(ValueError):
            f.load()

    def test_failed_or_future_evidence_reject(self):
        f = self.fixture()
        (f.worker / "failure.json").write_text('{}')
        with self.assertRaises(ValueError):
            f.load()
        with self.assertRaises(ValueError):
            f.load(cutoff_ns=1)

    def test_unsupported_pickle_global_is_not_called(self):
        payload = pickle.dumps(eval, protocol=4)
        with self.assertRaises(ValueError):
            early._OwnerUnpickler(BytesIO(payload)).load()

    def test_cached_pickle_extensions_cannot_bypass_global_allowlist(self):
        for opcode, code in ((b"\x82", b"\x01"), (b"\x83", b"\x01\x00"),
                             (b"\x84", b"\x01\x00\x00\x00")):
            with self.subTest(opcode=opcode), patch.dict(copyreg._extension_cache, {1: eval}):
                payload = b"\x80\x02" + opcode + code + b"."
                with self.assertRaisesRegex(ValueError, "external original owner"):
                    early._OwnerUnpickler(BytesIO(payload)).load()

    def test_persistent_pickle_references_are_rejected_before_loading(self):
        for payload in (b"Pexternal\n.", b"\x80\x02U\x08externalQ."):
            with self.subTest(payload=payload), patch.object(early._OwnerUnpickler,
                    "persistent_load", side_effect=AssertionError("must reject before loading")):
                with self.assertRaisesRegex(ValueError, "external original owner"):
                    early._OwnerUnpickler(BytesIO(payload)).load()

    def test_allowlisted_owner_rejects_unapproved_pickle_reducer(self):
        f = self.fixture()
        f.owner.metadata["unapproved_reducer"] = eval
        f.save_owner()
        with self.assertRaisesRegex(ValueError, "unsupported original owner pickle global"):
            f.load()

    def test_trailing_owner_object_and_bad_owner_result_hash_reject(self):
        f = self.fixture()
        f.documents["result"]["result_hash"] = "0"*64
        f.write("result", self.worker_path(f), f.documents["result"])
        with self.assertRaises(ValueError):
            f.load()
        path = Path(f.pins["owner"]["path"])
        path.write_bytes(path.read_bytes()+pickle.dumps(None))
        f.pins["owner"] = file_identity(path)
        f.documents["result"]["owner"] = f.pins["owner"]
        f.write("result", self.worker_path(f), f.documents["result"])
        with self.assertRaises(ValueError):
            f.load()

    def test_nonfinite_partial_and_changed_daily_account_reject(self):
        f = self.fixture()
        for key, value in (("equity", float("nan")), ("funding", 1.), ("daily_returns", .1)):
            f.arrays[key] = f.arrays[key].copy()
            old = f.arrays[key][0]
            f.arrays[key][0] = value
            f.paths()
            with self.assertRaises(ValueError):
                f.load()
            f.arrays[key][0] = old
        f.arrays["times_ns"] = f.arrays["times_ns"][:-1]
        f.paths()
        with self.assertRaises(ValueError):
            f.load()

    def test_qualified_mapping_is_explicit_and_not_manufactured(self):
        f = self.fixture(qualified=True)
        for role in ("finance_driver", "orchestrator", "witness"):
            mapping = dict(f.access_mapping)
            mapping[role] = f.approvals["alpha_source"]
            with self.assertRaises(ValueError):
                f.load(access_mapping=mapping)
        f.documents["access"]["finance_driver"] = f.approvals["finance_driver"]
        f.write("access", f.worker / "development_access.json", f.documents["access"])
        f.refresh_supervisor()
        with self.assertRaises(ValueError):
            f.load()

    def test_qualified_sibling_pins_must_be_in_original_supervisor(self):
        f = self.fixture(qualified=True)
        f.documents["supervisor_receipt"]["retained_manifest"] = [p for p in
            f.documents["supervisor_receipt"]["retained_manifest"] if p != f.pins["fills"]]
        f.write("supervisor_receipt", self.root / "supervisor.json", f.documents["supervisor_receipt"])
        with self.assertRaises(ValueError):
            f.load()

    def test_no_status_promotion_and_public_rows_leak_no_private_payload(self):
        f = self.fixture()
        cell = f.load()
        public = canonical(asdict(cell.provenance)) + cell.fills_json + cell.campaigns_json + cell.original_metrics_json
        self.assertNotIn("coordinate", public)
        self.assertNotIn("/synthetic/private", public)
        self.assertNotIn(str(self.root), public)
        self.assertEqual(cell.compute_status, RECOVERY_STATUS)
        from tools.mode5_research.panel_admission import reader_cell_identity
        self.assertEqual(len(reader_cell_identity(cell)), 64)

    def test_empty_early_control_keeps_undefined_no_trade_semantics(self):
        cell = self.fixture(empty=True).load()
        self.assertIsNone(json.loads(cell.original_metrics_json)["sharpe"])
        self.assertEqual(json.loads(cell.original_metrics_json)["psr"]["status"], "UNDEFINED")
        self.assertEqual(json.loads(cell.fills_json), [])
        self.assertEqual(json.loads(cell.campaigns_json), {"closed": [], "open": []})
        with self.assertRaises(ValueError):
            cell.arrays()["positions"][0] = 1.


if __name__ == "__main__":
    unittest.main()
