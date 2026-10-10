"""Cold selector controls: stdlib only, no conftest or financial imports."""

import ast
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
import sys


SOURCE = Path(__file__).resolve().parents[1] / "tools/mode5_research/selector_checkpoint.py"
SPEC = importlib.util.spec_from_file_location("selector_checkpoint", SOURCE)
checkpoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint)

PREFERENCES = dict(risk_drawdown_max=.5, quality_utility_strictly_greater_than=0,
    minimum_daily_count=365, activity_penalty=0, tie_break="candidate_id_lexicographic_v1")
OBJECTIVE = dict(metric="economic_utility", unit="decimal_return", quality_floor=0,
    reference_id="fixture-whole-path", reference_scale=1)


@contextmanager
def fixture_directory():
    lane = SOURCE.parents[2]/"upgrade/private/mode5_upgrade_v1/m5-11-1/attempt-01/goal-step1"
    root = lane/"cold-fixtures" if lane.is_dir() else Path(tempfile.gettempdir())/"mode5-selector-cold-fixtures"
    root.mkdir(parents=True, exist_ok=True)
    # Keep the small custody fixtures alongside their test receipt; no deletion.
    yield tempfile.mkdtemp(prefix="custody-", dir=root)


def metrics(utility, dd=.1):
    return dict(economic_utility=utility, max_drawdown=dd, daily_count=1095,
        account_mode="continuous_development_2021_2023", return_status="VALID")


def local_fixture():
    centers, neighborhoods, executions, evaluations = [], [], [], {}
    for i in range(2):
        centers.append(dict(center=i, candidate_id=f"center-{i}", panel_index=i,
            metrics=metrics(1.), covariance=dict(supported=False), cell=dict(path="fixture"), held_support={}))
        for j, role in enumerate(("selection_probe", "local_validation")):
            index = i*2+j
            neighborhoods.append(dict(center=i, role=role, seed=732+j,
                covariance_status="SCHEMA_ONLY_SPARSE_CLOUD", rows=[dict(status="READY", execution_index=index,
                    candidate_id=f"probe-{index}", direction="axis:x:-1",
                    point=dict(effective_json=json.dumps(dict(x=index))))],
                coverage=dict(status="OBSERVED_REQUIRED_RADII", uncovered_axes=[], uncovered_groups=[])))
            executions.append(dict(index=index))
            evaluations[index] = dict(index=index, center=i, role=role, candidate_id=f"probe-{index}",
                direction="axis:x:-1", metrics=metrics(.2 + i*.1), utility=.2+i*.1, status="COMPLETE",
                cell={}, paths={})
    return dict(objective=OBJECTIVE, centers=centers, neighborhoods=neighborhoods, executions=executions), evaluations


def panel_fixture():
    ids = [f"candidate-{i:03d}" for i in range(128)]
    rows = []
    for i, cid in enumerate(ids):
        for env in checkpoint.ENVIRONMENTS:
            days = 1095 if env == "whole_path" else 365
            utility = .1
            rows.append(dict(index=i, environment_id=env, calendar_days=days, actual_bar_count=24*days,
                compute_status="PASS", clean_oos=False, estimand_id="CONTINUOUS_PATH_ATTRIBUTION",
                provenance=dict(candidate_id=cid, execution_id=cid, data_role="REVIEWED_EXPLORATORY_DEVELOPMENT"),
                status="VALID_PROFITABLE", null_reasons=[], metrics=[dict(metric_id="mode5.panel."+name,
                    status="VALID", value=value, reason=None, unit="ratio" if name == "sharpe" else "decimal_return")
                    for name, value in [("economic_utility", utility), ("drawdown", .1), ("daily_loss_es", .01),
                        ("net_return", .21), ("sharpe", 1.)]]))
    return dict(candidate_ids=ids, candidate_environment_rows=rows, preferences=deepcopy(PREFERENCES))


def annual_fixture():
    result = panel_fixture()
    settings = [("environment_floor_mean_v1", dict(mean=.25), .125),
        ("environment_lower_tail_v2", dict(alpha=.25, floor=1, tail=.5, dispersion=.2), .15),
        ("pareto_chebyshev_v1", dict(rho=.01), -.309)]
    result["preferences"].update(formulas=[dict(version=v, coefficients=p) for v, p, _ in settings],
        pareto=dict(ideal=.25, worst=-.25, directions=1, weights=1))
    result["selector_diagnostics"] = dict(canonical_comparison=dict(decisions=[dict(formula_version=v,
        compared_candidate_ids=result["candidate_ids"], chosen_candidate="candidate-000",
        pareto_candidate_ids=list(result["candidate_ids"]) if v == "pareto_chebyshev_v1" else [],
        component_rows=[dict(candidate_id=c, eligible=True, score=score, values=[.1]*3)
            for c in result["candidate_ids"]]) for v, _, score in settings]))
    return result


class LocalControls(unittest.TestCase):
    def test_gamma_one_is_minimum_center_plus_selection_only(self):
        reg, evaluations = local_fixture()
        decision = checkpoint.local_comparison(reg, evaluations, PREFERENCES)
        self.assertEqual(decision["chosen_candidate"], "center-1")
        self.assertAlmostEqual(decision["component_rows"][1]["score"], .3)
        self.assertAlmostEqual(decision["component_rows"][1]["components"]["max_downside"], .7)
        self.assertEqual(decision["full_panel_local_status"], "NOT_EVALUABLE")
        self.assertEqual(decision["annual_local_status"], "NOT_EVALUABLE")

    def test_validation_outcomes_cannot_change_selection(self):
        reg, evaluations = local_fixture()
        before = checkpoint.local_comparison(reg, evaluations, PREFERENCES)
        for index in (1, 3):
            evaluations[index]["utility"] = -100 - index
            evaluations[index]["metrics"]["economic_utility"] = -100 - index
        after = checkpoint.local_comparison(reg, evaluations, PREFERENCES)
        for key in ("chosen_candidate", "component_rows", "pre_quality_numeric_best", "status"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["validation_post_decision"][0]["status"], "FRAGILE_CENTER")

    def test_losing_neighbor_is_retained_and_rejects_center(self):
        reg, evaluations = local_fixture()
        evaluations[2]["utility"] = -.4
        evaluations[2]["metrics"]["economic_utility"] = -.4
        decision = checkpoint.local_comparison(reg, evaluations, PREFERENCES)
        self.assertEqual(decision["chosen_candidate"], "center-0")
        self.assertEqual(decision["component_rows"][1]["score"], -.4)
        self.assertEqual(decision["component_rows"][1]["quality_survival_fraction"], 0)

    def test_all_fragile_is_no_selection_not_best_of_bad(self):
        reg, evaluations = local_fixture()
        for i in (0, 2):
            evaluations[i]["utility"] = -.1
            evaluations[i]["metrics"]["economic_utility"] = -.1
        decision = checkpoint.local_comparison(reg, evaluations, PREFERENCES)
        self.assertIsNone(decision["chosen_candidate"])
        self.assertEqual(decision["status"], "NO_SELECTION")
        self.assertEqual(decision["pre_quality_numeric_best"], "center-0")

    def test_missing_probe_does_not_rank_survivors(self):
        reg, evaluations = local_fixture()
        del evaluations[0]
        decision = checkpoint.local_comparison(reg, evaluations, PREFERENCES)
        self.assertIsNone(decision["chosen_candidate"])
        self.assertEqual(decision["status"], "NOT_EVALUABLE")
        self.assertIsNone(decision["component_rows"][0]["score"])
        self.assertEqual(decision["component_rows"][0]["missing"], [0])

    def test_runtime_failure_is_incomplete_not_economic_loss(self):
        reg, evaluations = local_fixture()
        evaluations[0]["status"] = "FAILED"
        row = checkpoint.local_comparison(reg, evaluations, PREFERENCES)["component_rows"][0]
        self.assertEqual(row["failed"], [0])
        self.assertIsNone(row["score"])

    def test_role_mismatch_is_rejected(self):
        reg, evaluations = local_fixture()
        evaluations[0]["role"] = "local_validation"
        with self.assertRaisesRegex(ValueError, "role/direction"):
            checkpoint.local_comparison(reg, evaluations, PREFERENCES)

    def test_duplicate_neighborhood_is_rejected(self):
        reg, evaluations = local_fixture()
        reg["neighborhoods"].append(deepcopy(reg["neighborhoods"][0]))
        with self.assertRaisesRegex(ValueError, "roster"):
            checkpoint.local_comparison(reg, evaluations, PREFERENCES)

    def test_uncovered_axis_is_incomplete(self):
        reg, evaluations = local_fixture()
        reg["neighborhoods"][0]["coverage"]["uncovered_axes"] = ["y"]
        self.assertEqual(checkpoint.local_comparison(reg, evaluations, PREFERENCES)["status"], "NOT_EVALUABLE")

    def test_covariance_blind_direction_detected_by_schema_union(self):
        reg, evaluations = local_fixture()
        n = reg["neighborhoods"][0]
        # Covariance cloud with y=0 misses f=1-x^2-10000*y^2's transverse loss.
        n["rows"].append(dict(status="READY", execution_index=4, candidate_id="transverse",
            direction="axis:y:1", point=dict(effective_json='{"x":0,"y":0.011}')))
        reg["executions"].append(dict(index=4))
        adverse = 1 - 10000*.011**2
        evaluations[4] = dict(index=4, center=0, role="selection_probe", candidate_id="transverse",
            direction="axis:y:1", metrics=metrics(adverse), utility=adverse, status="COMPLETE", cell={}, paths={})
        row = checkpoint.local_comparison(reg, evaluations, PREFERENCES)["component_rows"][0]
        self.assertAlmostEqual(row["score"], -.21)
        self.assertFalse(row["eligible"])

    def test_overlap_is_dependent_not_independent_confirmation(self):
        reg, evaluations = local_fixture()
        reg["neighborhoods"][1]["rows"][0]["point"] = deepcopy(reg["neighborhoods"][0]["rows"][0]["point"])
        row = checkpoint.local_comparison(reg, evaluations, PREFERENCES)["overlap"][0]
        self.assertEqual(row["overlapping_effective"], 1)
        self.assertEqual(row["held_distinct"], 0)
        self.assertFalse(row["independent_overlaps"])
        self.assertFalse(row["temporal_oos"])

    def test_annual_metrics_cannot_impersonate_whole_path_probe(self):
        reg, evaluations = local_fixture()
        evaluations[0]["metrics"]["daily_count"] = 365
        with self.assertRaisesRegex(ValueError, "whole-path probe"):
            checkpoint.local_comparison(reg, evaluations, PREFERENCES)

    def test_reference_units_and_scale_are_frozen(self):
        for key, value in (("unit", "ratio"), ("reference_scale", 10), ("quality_floor", -1)):
            reg, evaluations = local_fixture()
            reg["objective"] = {**OBJECTIVE, key: value}
            with self.assertRaisesRegex(ValueError, "reference"):
                checkpoint.local_comparison(reg, evaluations, PREFERENCES)

    def test_risk_breach_rejects_even_profitable_neighbor(self):
        reg, evaluations = local_fixture()
        evaluations[0]["metrics"]["max_drawdown"] = .6
        row = checkpoint.local_comparison(reg, evaluations, PREFERENCES)["component_rows"][0]
        self.assertFalse(row["eligible"])
        self.assertGreater(row["score"], 0)


class PanelControls(unittest.TestCase):
    def test_complete_original_roster(self):
        self.assertEqual(len(checkpoint.grid_for(panel_fixture())), 512)

    def test_annual_replay_checks_all_three_fixed_recipes(self):
        result = annual_fixture()
        decisions = checkpoint.annual_replay(result, checkpoint.grid_for(result))
        self.assertEqual([d["chosen_candidate"] for d in decisions], ["candidate-000"]*3)

    def test_annual_score_mutation_rejected(self):
        result = annual_fixture()
        result["selector_diagnostics"]["canonical_comparison"]["decisions"][0]["component_rows"][0]["score"] += .001
        with self.assertRaisesRegex(ValueError, "numerical score"):
            checkpoint.annual_replay(result, checkpoint.grid_for(result))

    def test_annual_positive_quality_gate_is_strict(self):
        result = annual_fixture()
        result["candidate_environment_rows"][1]["metrics"][0]["value"] = 0
        with self.assertRaisesRegex(ValueError, "gate mismatch"):
            checkpoint.annual_replay(result, checkpoint.grid_for(result))

    def test_annual_support_gate_cannot_be_relaxed(self):
        result = annual_fixture()
        result["preferences"]["minimum_daily_count"] = 366
        with self.assertRaisesRegex(ValueError, "gate mismatch"):
            checkpoint.annual_replay(result, checkpoint.grid_for(result))

    def test_pareto_front_cannot_omit_tied_admissible_points(self):
        result = annual_fixture()
        result["selector_diagnostics"]["canonical_comparison"]["decisions"][2]["pareto_candidate_ids"].pop()
        with self.assertRaisesRegex(ValueError, "front mismatch"):
            checkpoint.annual_replay(result, checkpoint.grid_for(result))

    def test_changed_canonical_choice_rejected(self):
        result = annual_fixture()
        result["selector_diagnostics"]["canonical_comparison"]["decisions"][0]["chosen_candidate"] = "candidate-001"
        with self.assertRaisesRegex(ValueError, "selected candidate"):
            checkpoint.annual_replay(result, checkpoint.grid_for(result))

    def test_missing_annual_environment_rejects(self):
        result = panel_fixture()
        result["candidate_environment_rows"].pop()
        with self.assertRaisesRegex(ValueError, "missing candidate"):
            checkpoint.grid_for(result)

    def test_duplicate_environment_rejects(self):
        result = panel_fixture()
        result["candidate_environment_rows"].append(deepcopy(result["candidate_environment_rows"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            checkpoint.grid_for(result)

    def test_forward_role_cannot_enter_panel(self):
        result = panel_fixture()
        result["candidate_environment_rows"][0]["provenance"]["data_role"] = "FORWARD"
        with self.assertRaisesRegex(ValueError, "development"):
            checkpoint.grid_for(result)

    def test_raw_sharpe_null_and_gates_are_not_favorable_sentinels(self):
        result = panel_fixture()
        m = result["candidate_environment_rows"][0]["metrics"][-1]
        m.update(value=None, status="UNDEFINED", reason="zero variance/no trade")
        # Control annotations do not filter a raw-Sharpe candidate.
        result["candidate_environment_rows"][4]["metrics"][0]["value"] = -.2
        grid = checkpoint.grid_for(result)
        raw = checkpoint.raw_control(result, grid, dict(chosen_candidate="candidate-001"))
        self.assertEqual(raw["chosen_candidate"], "candidate-001")
        self.assertIsNone(raw["component_rows"][0]["score"])
        self.assertFalse(raw["component_rows"][1]["gates_post_choice"]["quality"])

    def test_valid_nan_and_unit_mutations_reject(self):
        for key, value in (("value", math.nan), ("unit", "USDT")):
            result = panel_fixture()
            result["candidate_environment_rows"][0]["metrics"][0][key] = value
            with self.assertRaises(ValueError):
                checkpoint.grid_for(result)

    def test_undefined_requires_reason(self):
        result = panel_fixture()
        result["candidate_environment_rows"][0]["metrics"][-1].update(status="UNDEFINED", value=None)
        with self.assertRaisesRegex(ValueError, "null and reason"):
            checkpoint.grid_for(result)

    def test_tail_mass_not_interpolated_quantile(self):
        self.assertEqual(checkpoint.lower_tail([.01, .90, .91, .92], .25), .01)
        self.assertAlmostEqual(checkpoint.lower_tail([0, 1, 2], .5), 1/3)
        self.assertEqual(checkpoint.lower_tail([1, 2, 3], 1), 2)

    def test_lexicographic_tie_break(self):
        self.assertEqual(checkpoint.best([dict(candidate_id="z", eligible=True, score=1),
            dict(candidate_id="a", eligible=True, score=1)]), "a")


class CustodyControls(unittest.TestCase):
    def test_size_and_sha_corruption_rejected(self):
        with fixture_directory() as tmp:
            path = Path(tmp)/"receipt.json"
            original = checkpoint.write_new(path, dict(status="PASS"))
            for key, value in (("bytes", 0), ("sha256", "0"*64)):
                with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                    checkpoint.checked({**original, key: value})

    def test_append_only_output(self):
        with fixture_directory() as tmp:
            path = Path(tmp)/"receipt.json"
            record = checkpoint.write_new(path, dict(status="FAIL"))
            with self.assertRaises(FileExistsError):
                checkpoint.write_new(path, dict(status="PASS"))
            self.assertEqual(checkpoint.read(record), dict(status="FAIL"))

    def test_import_surface_is_stdlib_only(self):
        allowed = {"argparse", "datetime", "hashlib", "json", "math", "os", "pathlib", "subprocess", "sys"}
        imports = [n for n in ast.walk(ast.parse(SOURCE.read_text())) if isinstance(n, (ast.Import, ast.ImportFrom))]
        names = {name.name.split(".")[0] for n in imports for name in n.names} - {"datetime", "timezone", "Path"}
        modules = {n.module.split(".")[0] for n in imports if isinstance(n, ast.ImportFrom)}
        self.assertFalse((names | modules)-allowed)

    def test_no_financial_or_numeric_runtime_modules_loaded(self):
        self.assertFalse({name.split(".")[0] for name in sys.modules} & {"quantbt", "numpy", "scipy", "numba"})

    def test_failed_hash_audit_remains_observable_without_cleanup_deletion(self):
        with fixture_directory() as tmp:
            record = checkpoint.write_new(Path(tmp)/"receipt.json", dict(status="FAIL"))
            registration = dict(protected_prior_files=[{**record, "sha256": "0"*64}])
            audit = checkpoint.verify_prior(registration, strict=False)
            self.assertEqual(audit["hash_failures"], 1)
            self.assertEqual(audit["verified"], 0)
            with self.assertRaisesRegex(ValueError, "custody"):
                checkpoint.verify_prior(registration)


class RetainedEvidenceControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lane = SOURCE.parents[2]/"upgrade/private/mode5_upgrade_v1/m5-11-1/attempt-01/goal-step1"
        if not lane.is_dir():
            raise unittest.SkipTest("private evidence lane not present in this checkout")
        cls.registration = checkpoint.read(checkpoint.pin(lane/"registration_01.json"))
        cls.report, cls.requests = checkpoint.analyze(cls.registration)

    def test_original_decisions_unchanged(self):
        for alpha, expected in (("rsi", [10, 56, 49, 56, None]), ("sc", [33, None, None, None, None])):
            self.assertEqual([r["chosen_index"] for r in self.report["reports"][alpha]["side_by_side"]], expected)

    def test_two_centers_not_full_panel_local_contest(self):
        for alpha in ("rsi", "sc"):
            local = self.report["reports"][alpha]["local"]
            self.assertEqual(len(local["compared_candidate_ids"]), 2)
            self.assertEqual(local["status"], "NO_SELECTION")
            self.assertEqual(local["full_panel_local_status"], "NOT_EVALUABLE")
            self.assertEqual(self.requests[alpha]["full_panel_unprobed_candidate_count"], 126)

    def test_exact_annual_requests_are_reduction_not_financial_launch(self):
        for alpha, count in (("rsi", 465), ("sc", 174)):
            request = self.requests[alpha]
            self.assertEqual(len(request["annual_view_requests"]), count)
            self.assertFalse(request["annual_views_available"])
            self.assertFalse(request["launches_authorized"])
            self.assertTrue(all(r["source_path"] and r["exact_execution_request"] and
                r["request_type"] == "REDUCE_RETAINED_CONTINUOUS_PATH_NO_ACCOUNT_RERUN"
                for r in request["annual_view_requests"]))

    def test_minimal_control_neighborhood_requests_are_concrete(self):
        self.assertEqual(self.requests["rsi"]["minimal_matched_control_indices"], [10, 49])
        self.assertEqual(self.requests["sc"]["minimal_matched_control_indices"], [33])
        self.assertEqual(self.requests["rsi"]["annual_local_eligible_unprobed_indices"], [49, 114])
        self.assertEqual(self.requests["sc"]["annual_local_eligible_unprobed_indices"], [])
        self.assertTrue(all(r["registered_candidate"]["candidate_id"] == r["candidate_id"]
            for r in self.requests["rsi"]["candidate_requests"]))

    def test_overlap_covariance_and_negative_outcomes_preserved(self):
        rsi = self.report["reports"]["rsi"]["local"]
        self.assertEqual(rsi["component_rows"][0]["covariance_status"], "SCHEMA_ONLY_SPARSE_CLOUD")
        self.assertEqual([r["status"] for r in rsi["component_rows"]], ["FRAGILE_CENTER"]*2)
        self.assertEqual(sum(r["overlapping_effective"] for r in rsi["overlap"]), 42)
        self.assertEqual(sum(r["held_distinct"] for r in rsi["overlap"]), 37)
        sc = self.report["reports"]["sc"]
        self.assertEqual(len(sc["inherited_annual_decisions"][2]["pareto_candidate_ids"]), 0)
        self.assertEqual(sum(r["score"] is None for r in sc["raw_sharpe"]["component_rows"]), 2)

    def test_exact_schema_floor_matches_registered_producer_coordinates(self):
        inputs, _ = checkpoint.load_inputs(self.registration)
        for _, probes, _, _ in inputs.values():
            for neighborhood in probes["neighborhoods"]:
                center = next(c for c in probes["centers"] if c["center"] == neighborhood["center"])
                generated = checkpoint.schema_floor_rows(probes["geometry_id"], probes["geometry"],
                    json.loads(center["point"]["effective_json"]), neighborhood["radius"],
                    neighborhood["coverage"]["joint_groups"])
                known = [r for r in neighborhood["rows"] if not r["direction"].startswith("covariance:")]
                self.assertEqual([(r["direction"], r["status"], r["candidate_id"]) for r in generated],
                    [(r["direction"], r["status"], r.get("candidate_id")) for r in known])

    def test_bounded_exact_requests_are_not_an_authorized_full_panel(self):
        for alpha, targets in (("rsi", [10, 49, 114]), ("sc", [33])):
            manifest = self.requests[alpha]["bounded_neighborhood_manifest"]
            self.assertEqual(manifest["targets"], targets)
            self.assertEqual(len(manifest["neighborhoods"]), 2*len(targets))
            self.assertFalse(manifest["launches_authorized"])
            self.assertTrue(manifest["executions"])
            for candidate in self.requests[alpha]["candidate_requests"]:
                if candidate["index"] in targets:
                    self.assertEqual(candidate["status"], "SCHEMA_FLOOR_REQUEST_DESIGN_REGISTERED_COVARIANCE_PENDING")
            for execution in manifest["executions"]:
                request = execution["request"]
                self.assertEqual(execution["request_sha256"], checkpoint.digest(request))
                self.assertEqual(request["role"], execution["role"])
                self.assertEqual(request["start"], "2021-01-01")
                self.assertEqual(request["stop"], "2024-01-01")
                self.assertEqual(request["alpha"], "A-" + alpha.upper())
                self.assertFalse(execution["launch_authorized"])

    def test_unsupported_schema_not_silently_repaired_for_requests(self):
        inputs, _ = checkpoint.load_inputs(self.registration)
        _, probes, _, _ = inputs["rsi"]
        geometry = deepcopy(probes["geometry"])
        geometry["constraints"] = [dict(names=["len_atr1", "len_atr2"])]
        with self.assertRaisesRegex(ValueError, "unsupported request schema"):
            checkpoint.schema_floor_rows(probes["geometry_id"], geometry,
                json.loads(probes["centers"][0]["point"]["effective_json"]), .1, [])


if __name__ == "__main__":
    unittest.main()
