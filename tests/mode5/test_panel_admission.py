"""Public synthetic typed accounts only; no files, alpha imports or executions."""

from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import numpy as np

from quantbt.metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from quantbt.metrics.reporting import AccountObservations
from tools.mode5_diagnostics.evidence import FrozenBuffer
from tools.mode5_diagnostics.identity import canonical, digest
from tools.mode5_research import panel_admission as a, panels, selector_checkpoint
from tools.mode5_research.recovery_cells import RecoveryCell, RECOVERY_SCHEMA, RECOVERY_STATUS
from tools.mode5_research.early_admission import (EarlyCell, EARLY_CONTROL_SCHEMA, QUALIFIED_ACCESS_SCHEMA,
                                                OWNER_LIMITATIONS, ACCESS_LIMITATIONS)

CUTOFF = panels._ns("2026-10-12")
UTILITY = panels.UtilityPolicy("public_cold_fixture", 1., 1.)
ALPHA_SOURCE = digest("public_alpha_source")
ECONOMICS = digest("public_economic_config")


def synthetic_panel():
    rows = []
    for i in range(256):
        admitted = i % 2 == 0
        effective = {"synthetic_coordinate": float(i)}
        rows.append(dict(row_id=i, admitted=admitted, status="READY", role="exploration",
            candidate_id=digest(effective), requested={"synthetic_coordinate": float(i)+.5},
            effective=effective, direction="branch:0", duplicate_of=None))
    design = dict(alpha="PUBLIC_SYNTHETIC", design_id=digest("public_design"), rows=rows)
    times = np.arange(a.START, a.STOP, panels.HOUR_NS, dtype=np.int64)
    paths = digest("public_path")
    contract = ReportingContractV1(scope="full", unit="account_period", currency="TEST",
        baseline_equity=1000., baseline_time_ns=a.START-panels.HOUR_NS,
        scope_end_ns=a.STOP-panels.HOUR_NS, sampling="observed_daily_utc",
        annual_periods=365., equity_clock="bar_close")
    coverage = ReportingCoverageV1(result_identity=paths, producer="public synthetic",
        profile="compact", ledger="omitted", retained_rows=0, dropped_rows=0, reason="synthetic empty ledgers")
    observations = AccountObservations(times_ns=times, equity=np.full(26280, 1000.), coverage=coverage)
    observations = observations.with_derived_returns(contract, partial_mask=np.zeros(1095, dtype=bool),
        witness="public synthetic complete daily calendar")
    buffers = tuple(FrozenBuffer.from_array(k, np.zeros(26280)) for k in ("positions", "fees", "funding", "turnover"))
    common = {k: digest("public_"+k) for k in ("design", "development_data")}
    common["paths"] = paths
    cells = []
    for index, proposal in enumerate(r for r in rows if r["admitted"]):
        recovery = index % 2 == 1
        keys = ("result", "worker_registration", "original_registration", "economic_config", "native_gate",
                "campaigns", "fills", "approved_source_0") if recovery else (
                "cell", "request", "registration", "resources", "analysis", "execution_budget", "access",
                "source.alpha_source", "source.finance_driver")
        refs = common | {k: digest("public_"+k+str(index)) for k in keys}
        if recovery:
            refs.update(approved_source_0=ALPHA_SOURCE, economic_config=ECONOMICS)
        else:
            refs["source.alpha_source"] = ALPHA_SOURCE
        execution = refs["result"] if recovery else digest("public_execution"+str(index))
        provenance = panels.CandidateProvenance("public_study", "cold_01", design["alpha"],
            proposal["candidate_id"], digest(proposal["requested"]), digest(proposal["effective"]),
            proposal["direction"], (proposal["row_id"],), execution, design["design_id"], "PUBLIC_MARKET",
            a._SCHEMAS[RECOVERY_SCHEMA if recovery else a.ORIGINAL_SCHEMA][1],
            "Public current-knowledge retrospective fixture, not historical or independent OOS",
            panels._ns("2020-01-01"), a.STOP, CUTOFF, CUTOFF,
            "incremental_actual_feedback_boundary_full_hash_v1" if recovery else "public_callback",
            tuple(sorted(refs.items())))
        args = (provenance, a.START, a.STOP, contract, observations, buffers,
                canonical(dict(closed=[], open=[])), "[]", "{}", RECOVERY_STATUS if recovery else "PASS", None)
        python = int(index == 1)
        cells.append(RecoveryCell(*args, index+1, 1+python, python) if recovery else panels.VerifiedCell(*args))
    certificates = {c.provenance.candidate_id: certificate(c) for c in cells}
    return design, tuple(cells), certificates


def certificate(cell):
    schema = a._schema(cell)
    return a.ReaderCertification(schema, a.reader_cell_identity(cell), ALPHA_SOURCE, ECONOMICS)


class PanelAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design, cls.cells, cls.certificates = synthetic_panel()
        cls.views = {}
        producer = panels.continuous_annual_rows

        def capture(cell, **kwargs):
            result = producer(cell, **kwargs)
            cls.views[cell.provenance.candidate_id] = result
            return result

        with patch.object(panels, "continuous_annual_rows", side_effect=capture) as owner:
            cls.result = a.admit_panel(cls.cells, original_design=cls.design,
                original_design_digest=digest(cls.design), certifications=cls.certificates,
                alpha_source_digest=ALPHA_SOURCE, economic_config_digest=ECONOMICS,
                utility_policy=UTILITY, cutoff_ns=CUTOFF)
        cls.actual_owner_calls = owner.call_count

    def cached_views(self, cell, **kwargs):
        return tuple(replace(r, provenance=cell.provenance, compute_status=cell.compute_status)
                     for r in self.views[cell.provenance.candidate_id])

    def admit(self, cells=None, **changes):
        arguments = dict(original_design=self.design, original_design_digest=digest(self.design),
            alpha_source_digest=ALPHA_SOURCE, economic_config_digest=ECONOMICS,
            certifications=self.certificates, utility_policy=UTILITY, cutoff_ns=CUTOFF)
        with patch.object(panels, "continuous_annual_rows", side_effect=self.cached_views):
            return a.admit_panel(self.cells if cells is None else cells, **(arguments | changes))

    def changed_cell(self, **updates):
        cells = list(self.cells)
        cells[1] = replace(cells[1], **updates)
        return cells

    def recertified(self, cells):
        return {c.provenance.candidate_id: certificate(c) for c in cells}

    def test_full128_mixed_uses_exact_shared_producer_and_four_views(self):
        self.assertEqual(self.actual_owner_calls, 128)
        self.assertEqual(len(self.result["candidate_ids"]), 128)
        rows = self.result["candidate_environment_rows"]
        self.assertEqual(len(rows), 512)
        self.assertEqual(self.result["financial_executions"], 0)
        for i, cell in enumerate(self.cells):
            views = rows[i*4:i*4+4]
            self.assertEqual([r["environment_id"] for r in views], list(a.ENVIRONMENTS))
            self.assertEqual([r["calendar_days"] for r in views], [1095, 365, 365, 365])
            self.assertTrue(all(r["index"] == i and r["compute_status"] == cell.compute_status
                                and r["analysis_compute_status"] == "PASS" for r in views))
            self.assertTrue(all(r["provenance"]["data_role"] == cell.provenance.data_role for r in views))
            self.assertTrue(all(not r["clean_oos"] and r["status"] == "VALID_NO_TRADE" for r in views))

    def test_recovery_schema_oracle_and_real_calls_not_legacy_pass(self):
        control, bulk = self.result["candidate_environment_rows"][4], self.result["candidate_environment_rows"][12]
        self.assertEqual(control["compute_status"], RECOVERY_STATUS)
        self.assertEqual(control["source_reader_schema"], RECOVERY_SCHEMA)
        self.assertEqual(control["recovery_account_calls"], [2, 2, 1])
        self.assertEqual(control["oracle_coverage"], "FRESH_ORIGINAL_PYTHON_CONTROL")
        self.assertEqual(bulk["recovery_account_calls"], [4, 1, 0])
        self.assertIn("NO_FRESH_PYTHON_ORACLE", bulk["oracle_coverage"])
        self.assertEqual(self.result["candidate_environment_rows"][0]["oracle_coverage"], a.ORIGINAL_ORACLE)

    def test_original_serialized_ordinal_not_proposal_row_or_input_order(self):
        result = self.admit(reversed(self.cells))
        self.assertEqual(result, self.result)
        self.assertEqual(result["candidate_environment_rows"][4]["provenance"]["trial_refs"], [2])
        self.assertEqual(result["candidate_environment_rows"][4]["index"], 1)

    def test_all_original_rows_work_with_unchanged_selector_grid(self):
        cells = []
        for c in self.cells:
            if type(c) is RecoveryCell:
                refs = dict(c.provenance.evidence_refs)
                refs.update({k: digest("public_"+k) for k in ("cell", "request", "registration", "resources",
                    "analysis", "execution_budget", "access", "source.alpha_source", "source.finance_driver")})
                refs["source.alpha_source"] = ALPHA_SOURCE
                p = replace(c.provenance, data_role=a._SCHEMAS[a.ORIGINAL_SCHEMA][1],
                    actual_route="public_callback", evidence_refs=tuple(sorted(refs.items())))
                c = panels.VerifiedCell(p, c.start_ns, c.stop_ns, c.contract, c.observations, c.buffers,
                    c.campaigns_json, c.fills_json, c.original_metrics_json, "PASS", None)
            cells.append(c)
        result = self.admit(cells, certifications=self.recertified(cells))
        self.assertEqual(len(selector_checkpoint.grid_for(result)), 512)
        self.assertTrue(all(a.analysis_compute_pass(r) for r in result["candidate_environment_rows"]))

    def test_selector_consumes_recovery_without_relabeling_status_or_role(self):
        before = canonical(self.result)
        grid = selector_checkpoint.grid_for(self.result)
        self.assertEqual(len(grid), 512)
        for row in grid.values():
            self.assertTrue(selector_checkpoint.compute_pass(row))
            self.assertIsNone(selector_checkpoint.metric(row, "sharpe"))
            self.assertEqual(selector_checkpoint.metric(row, "net_return"), 0.)
        self.assertEqual(before, canonical(self.result))

    def test_selector_requires_admitted_envelope_and_rejects_tamper(self):
        subject = deepcopy(self.result)
        subject.pop("schema")
        with self.assertRaises(ValueError):
            selector_checkpoint.grid_for(subject)
        for update in (dict(compute_status="PASS"), dict(analysis_compute_status="PASS_ISH"),
                       dict(reader_certification_id=digest("tampered")), dict(oracle_coverage="ALL_PYTHON_PASS")):
            subject = deepcopy(self.result)
            subject["candidate_environment_rows"][4].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                selector_checkpoint.grid_for(subject)

    def early_cell(self, schema):
        cell = self.cells[1]
        refs = dict(cell.provenance.evidence_refs)
        if schema == EARLY_CONTROL_SCHEMA:
            refs.update(owner=digest("pinned_original_owner"), derived_campaigns=digest(cell.campaigns_json),
                        derived_fills=digest(cell.fills_json))
            status, role = a._SCHEMAS[schema]
            limitations, origin, native, feedback, normal = OWNER_LIMITATIONS, "SEALED_OWNER_DERIVED", 4, 2, 2
        else:
            names = ("cell", "request", "resources", "analysis", "access", "recovery_registration",
                     "qualified_receipt", "supervisor_receipt", "native_artifact", "source.finance_driver")
            refs.update({k: digest("pinned_qualified_"+k) for k in names})
            refs["source.alpha_source"] = ALPHA_SOURCE
            status, role = a._SCHEMAS[schema]
            limitations = ACCESS_LIMITATIONS + ("Original terminal audit: NOT_CERTIFIED",
                                               "Original cold account verification: SOURCE_QUALIFIED")
            origin, native, feedback, normal = "ORIGINAL_SUPERVISOR_JSON", 2, None, None
        provenance = replace(cell.provenance, data_role=role, evidence_refs=tuple(sorted(refs.items())))
        return EarlyCell(provenance, cell.start_ns, cell.stop_ns, cell.contract, cell.observations, cell.buffers,
            cell.campaigns_json, cell.fills_json, cell.original_metrics_json, status, None,
            schema, limitations, origin, native, 1, feedback, normal)

    def test_older_readers_keep_missing_snapshot_access_and_ledger_limits(self):
        for schema in (EARLY_CONTROL_SCHEMA, QUALIFIED_ACCESS_SCHEMA):
            cells = list(self.cells)
            cells[1] = self.early_cell(schema)
            result = self.admit(cells, certifications=self.recertified(cells))
            grid = selector_checkpoint.grid_for(result)
            row = result["candidate_environment_rows"][4]
            self.assertEqual(len(grid), 512)
            self.assertEqual(row["source_reader_schema"], schema)
            self.assertEqual(row["compute_status"], cells[1].compute_status)
            self.assertEqual(row["provenance"]["data_role"], cells[1].provenance.data_role)
            self.assertIsNone(row["recovery_account_calls"])
            self.assertEqual(row["early_account_witness"]["source_limitations"], list(cells[1].source_limitations))
            self.assertEqual(row["oracle_coverage"], "RETAINED_ORIGINAL_PYTHON_CONTROL_NO_NEW_EXECUTION")

    def test_older_schema_cannot_hide_missing_snapshot_or_borrow_fresh_oracle(self):
        cells = list(self.cells)
        cells[1] = self.early_cell(EARLY_CONTROL_SCHEMA)
        result = self.admit(cells, certifications=self.recertified(cells))
        original = result["candidate_environment_rows"][4]
        for key, value in (("source_limitations", []), ("ledger_origin", "ORIGINAL_JSON"),
                           ("native_account_calls", 0), ("native_feedback_calls", None),
                           ("python_oracle_calls", 0)):
            row = deepcopy(original)
            row["early_account_witness"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                selector_checkpoint.metric(row, "net_return")
        for update in (dict(oracle_coverage="FRESH_ORIGINAL_PYTHON_CONTROL"),
                       dict(recovery_account_calls=[2, 2, 1]), dict(compute_status="PASS")):
            with self.subTest(update=update), self.assertRaises(ValueError):
                selector_checkpoint.metric(deepcopy(original) | update, "net_return")

    def test_duplicate_missing_orphan_and_untyped_cells_reject(self):
        for cells in (self.cells[:-1], self.cells[:-1]+(self.cells[0],), self.cells+(self.cells[0],), ("PASS",)*128):
            with self.subTest(count=len(cells)), self.assertRaises(ValueError):
                self.admit(cells)

    def test_missing_or_wrong_reader_certificates_reject(self):
        certificates = dict(self.certificates)
        certificates.pop(self.cells[0].provenance.candidate_id)
        with self.assertRaises(ValueError):
            self.admit(certifications=certificates)
        certificates = dict(self.certificates)
        cid = self.cells[1].provenance.candidate_id
        certificates[cid] = a.ReaderCertification(a.ORIGINAL_SCHEMA, certificates[cid].cell_identity,
                                                   ALPHA_SOURCE, ECONOMICS)
        with self.assertRaises(ValueError):
            self.admit(certifications=certificates)

    def test_changed_source_economics_and_cutoff_cannot_self_admit(self):
        c = self.cells[1]
        refs = dict(c.provenance.evidence_refs)
        for name in ("approved_source_0", "economic_config", "native_gate", "development_data"):
            with self.subTest(name=name):
                p = replace(c.provenance, evidence_refs=tuple(sorted((refs | {name: digest("changed")}).items())))
                with self.assertRaises(ValueError):
                    self.admit(self.changed_cell(provenance=p))
        with self.assertRaises(ValueError):
            self.admit(self.changed_cell(contract=replace(c.contract, baseline_equity=2000.)))
        with self.assertRaises(ValueError):
            self.admit(self.changed_cell(provenance=replace(c.provenance, knowledge_cutoff_ns=CUTOFF-1)))

    def test_future_cutoff_and_forward_or_probe_roles_reject_even_with_certificate(self):
        c = self.cells[1]
        for update in (dict(knowledge_cutoff_ns=CUTOFF+1), dict(data_cutoff_ns=a.STOP+1),
                       dict(data_role="FORWARD"), dict(data_role="local_validation"),
                       dict(data_role="REVIEWED_EXPLORATORY_DEVELOPMENT")):
            cells = self.changed_cell(provenance=replace(c.provenance, **update))
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.admit(cells, certifications=self.recertified(cells))

    def test_changed_candidate_params_branch_and_original_index_reject(self):
        c = self.cells[1]
        for update in (dict(raw_params_digest=digest("changed")), dict(effective_params_digest=digest("changed")),
                       dict(trial_refs=(1,)), dict(trial_refs=(True,)), dict(branch_id="other")):
            cells = self.changed_cell(provenance=replace(c.provenance, **update))
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.admit(cells, certifications=self.recertified(cells))

    def test_changed_buffers_ledgers_metrics_and_account_calls_reject(self):
        c = self.cells[1]
        updates = [dict(fills_json="[{}]"), dict(campaigns_json="{}"), dict(original_metrics_json="{\"sharpe\":0}"),
                   dict(native_feedback_calls=c.native_feedback_calls+1),
                   dict(buffers=c.buffers[:-1]), dict(observations=replace(c.observations, equity=c.observations.equity+1.))]
        for update in updates:
            with self.subTest(fields=tuple(update)), self.assertRaises(ValueError):
                self.admit(self.changed_cell(**update))

    def test_censored_masked_failure_and_incomplete_account_reject(self):
        for update in (dict(compute_status="CENSORED"), dict(compute_status="PASS"),
                       dict(observations=None), dict(reason="retained failure")):
            cells = self.changed_cell(**update)
            with self.subTest(fields=tuple(update)), self.assertRaises(ValueError):
                self.admit(cells, certifications=self.recertified(cells))

    def test_wrong_year_calendar_and_daily_masks_reject(self):
        c = self.cells[1]
        for update in (dict(start_ns=panels._ns("2022-01-01")), dict(stop_ns=panels._ns("2025-01-01")),
                       dict(observations=replace(c.observations, times_ns=c.observations.times_ns+panels.HOUR_NS)),
                       dict(observations=replace(c.observations, returns=replace(c.observations.returns,
                            partial_mask=np.ones(1095, dtype=bool))))):
            cells = self.changed_cell(**update)
            with self.subTest(fields=tuple(update)), self.assertRaises(ValueError):
                self.admit(cells, certifications=self.recertified(cells))

    def test_design_seal_roster_role_and_effective_uniqueness_reject(self):
        for change in (lambda d: d["rows"].pop(0), lambda d: d["rows"][0].update(role="selection_probe"),
                       lambda d: d["rows"][0].update(effective=d["rows"][2]["effective"]),
                       lambda d: d["rows"].reverse()):
            design = deepcopy(self.design)
            change(design)
            with self.assertRaises(ValueError):
                self.admit(original_design=design)
            if design["rows"][0]["role"] != "exploration" or len(design["rows"]) < 256:
                with self.assertRaises(ValueError):
                    self.admit(original_design=design, original_design_digest=digest(design))

    def test_missing_duplicate_and_wrong_annual_view_reject(self):
        def invalid(cell, **kwargs):
            views = self.cached_views(cell)
            return tuple(replace(r, environment_id="2024") if i == 3 else r for i, r in enumerate(views))
        with patch.object(panels, "continuous_annual_rows", side_effect=invalid), self.assertRaises(ValueError):
            a.admit_panel(self.cells, original_design=self.design, original_design_digest=digest(self.design),
                alpha_source_digest=ALPHA_SOURCE, economic_config_digest=ECONOMICS,
                certifications=self.certificates, utility_policy=UTILITY, cutoff_ns=CUTOFF)

    def test_undefined_zero_sentinel_wrong_unit_and_missing_reason_reject(self):
        row = self.result["candidate_environment_rows"][4]
        for update in (dict(value=0.), dict(value=float("inf")), dict(reason=None), dict(status="VALID"), dict(unit="money")):
            subject = deepcopy(row)
            metric = next(m for m in subject["metrics"] if m["metric_id"] == "mode5.panel.sharpe")
            metric.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                a.validate_panel_row(subject)

    def test_null_mask_removal_or_false_null_reject(self):
        row = deepcopy(self.result["candidate_environment_rows"][4])
        row["null_reasons"] = [pair for pair in row["null_reasons"] if pair[0] != "mode5.panel.sharpe"]
        with self.assertRaises(ValueError):
            a.validate_panel_row(row)
        row = deepcopy(self.result["candidate_environment_rows"][4])
        row["null_reasons"].append(["mode5.panel.net_return", "hidden"])
        with self.assertRaises(ValueError):
            a.validate_panel_row(row)

    def test_changed_raw_reporting_authority_reject(self):
        row = deepcopy(self.result["candidate_environment_rows"][4])
        raw = next(m for m in row["raw_account_metrics"]["metrics"] if m["metric_id"] == "reporting.period.sharpe")
        raw.update(value=0., status="valid", reason=None)
        with self.assertRaises(ValueError):
            a.validate_panel_row(row)

    def test_oracle_coverage_and_unknown_admission_status_reject(self):
        for update in (dict(oracle_coverage=a.ORIGINAL_ORACLE), dict(recovery_account_calls=[2, 1, 1]),
                       dict(compute_status="PASS"), dict(analysis_compute_status="CENSORED"),
                       dict(panel_admission_schema="unknown")):
            with self.subTest(update=update), self.assertRaises(ValueError):
                a.validate_panel_row(deepcopy(self.result["candidate_environment_rows"][4]) | update)

    def test_duplicate_and_missing_metric_contracts_reject(self):
        for change in (lambda row: row["metrics"].append(deepcopy(row["metrics"][0])),
                       lambda row: row["metrics"].pop(0)):
            row = deepcopy(self.result["candidate_environment_rows"][4])
            change(row)
            with self.assertRaises(ValueError):
                a.validate_panel_row(row)

    def test_serialized_rows_are_public_and_original_objects_unmodified(self):
        public = canonical(self.result)
        self.assertNotIn("synthetic_coordinate", public)
        self.assertNotIn("/root/", public)
        self.assertNotIn("requested", public)
        self.assertEqual(self.cells[1].compute_status, RECOVERY_STATUS)
        self.assertEqual(self.cells[1].provenance.data_role, "DEVELOPMENT_REVIEWED_RETROSPECTIVE")
        self.assertEqual(json.loads(public), self.result)

    def test_individually_admitted_changed_economics_cannot_mix_into_panel(self):
        cell = self.cells[1]
        refs = dict(cell.provenance.evidence_refs) | dict(economic_config=digest("different_costs"))
        cells = self.changed_cell(provenance=replace(cell.provenance, evidence_refs=tuple(sorted(refs.items()))))
        certificates = self.recertified(cells)
        certificates[cell.provenance.candidate_id] = replace(certificates[cell.provenance.candidate_id],
                                                           economic_config_digest=refs["economic_config"])
        with self.assertRaises(ValueError):
            self.admit(cells, certifications=certificates)

    def test_changed_serialized_source_and_certified_economics_reject(self):
        for update in (dict(alpha_source_digest=digest("changed")), dict(economic_config_digest=digest("changed"))):
            with self.assertRaises(ValueError):
                a.validate_panel_row(deepcopy(self.result["candidate_environment_rows"][4]) | update)


if __name__ == "__main__":
    unittest.main()
