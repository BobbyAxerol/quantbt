"""Synthetic cold request custody; finance entry is mocked, never executed."""

from collections import Counter
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.mode5_research import covariance_finance as v
from tools.mode5_research.jobs import Candidate


def frozen():
    """Full-sized synthetic ledger, not a measured cloud or account evidence."""
    bundle, parents, geometries = {}, {}, {}
    fits, neighborhoods, executions = [], [], []
    for key, alpha, symbol in (("rsi", "A-RSI", "ETHUSDT"), ("sc", "A-SC", "BTCUSDT")):
        metadata = dict(parameters=[dict(name="period", kind="integer", low=1, high=10000,
            fixed=False, fixed_value=None, categories=[], active_if={})], constraints=[], inactive={})
        geometries[alpha] = metadata
        cid = lambda params: v.original.effective_id(metadata, params)
        rows = [dict(admitted=True, effective=dict(period=i+1), candidate_id=cid(dict(period=i+1))) for i in range(128)]
        parent = dict(rows=rows, schema_id=v.digest(metadata), design_id="parent-" + key)
        parents[alpha] = parent
        manifest = dict(parent_geometry_id=parent["schema_id"], recipe=deepcopy(v.original.RECIPE),
            launches_authorized=False, neighborhoods=[], executions=[], covariance_requests=[])
        bundle[key] = dict(bounded_neighborhood_manifest=manifest)
        for center, index in enumerate(v.TARGETS[key]):
            cloud_ids = [rows[i]["candidate_id"] for i in (index, 0, 1, 2, 3)]
            fit_request = dict(original_index=index, candidate_id=rows[index]["candidate_id"],
                geometry_id=parent["schema_id"], candidate_roster=[r["candidate_id"] for r in rows],
                recipe=deepcopy(v.RECIPE), status="FIT_AND_EXACT_DIRECTIONS_NOT_REGISTERED",
                financial_launch_authorized=False)
            manifest["covariance_requests"].append(fit_request)
            fit = dict(alpha=key, original_index=index, candidate_id=rows[index]["candidate_id"],
                request_identity=v.digest(fit_request), recipe=deepcopy(v.RECIPE), status="MEASURED_SUPPORTED",
                supported=True, center_quality_eligible=True, covariance_status="REGULARIZED_PROPOSALS_NOT_HESSIAN",
                distinct_cloud_count=5, cloud_ids=cloud_ids, centered_coordinate_rank=1, numeric_dimensions=1,
                numeric_names=["period"], coordinates=[[i/10] for i in range(5)], independent=False,
                clean_oos=False, launch_authorized=False)
            fits.append(fit)
            for role_number, (role, radius, seed) in enumerate((("selection_probe", .1, 732), ("local_validation", .12, 733))):
                floor_count = ((29, 31, 30, 30, 30, 29)[center*2+role_number] if key == "rsi" else 8)
                covariance_count = 16 if key == "rsi" else 6
                old_id = f"schema-{key}-{index}-{role}"
                floor = dict(neighborhood_id=old_id, original_index=index, parent_candidate_id=fit["candidate_id"],
                    role=role, radius=radius, seed=seed, center=center, rows=[])
                manifest["neighborhoods"].append(floor)
                n = dict(alpha=key, original_index=index, parent_candidate_id=fit["candidate_id"], role=role,
                    radius=radius, seed=seed, center=center, original_schema_neighborhood_id=old_id,
                    covariance_status=fit["covariance_status"], independent=False, account_evidence_available=False,
                    coverage=dict(joint_groups=[]), proposal_identity=v.digest(dict(synthetic=old_id)), rows=[])
                nid = v.digest(dict(parent_design=parent["design_id"], center=fit["candidate_id"],
                    geometry=parent["schema_id"], role=role, radius=radius, minimum_radius=.05, seed=seed,
                    joint_groups=[], cloud_ids=cloud_ids, rho=.2, tau=.001, proposal_identity=n["proposal_identity"]))
                n["neighborhood_id"] = nid
                neighborhoods.append(n)
                for row_id in range(floor_count + covariance_count):
                    is_old = row_id < floor_count
                    effective = dict(period=(2000+len(manifest["executions"]) if is_old else 6000+len(executions)))
                    direction = f"axis:period:{row_id}" if is_old else f"covariance:{row_id-floor_count}"
                    r = dict(v.original.BASE, alpha=alpha, symbol=symbol, params=effective, candidate_id=cid(effective),
                        design_id=old_id if is_old else nid, proposal_row=row_id, parent_candidate_id=fit["candidate_id"],
                        parent_design_id=parent["design_id"], parent_panel_index=index, neighborhood_center=center,
                        probe_direction=direction, probe_radius=radius, probe_seed=seed, role=role)
                    row = dict(row_id=row_id, role=role, status="READY", effective=effective, candidate_id=r["candidate_id"],
                        direction=direction, execution_index=len(executions), requested=effective,
                        requested_json=json.dumps(effective), point=dict(schema_id=parent["schema_id"], effective_json=json.dumps(effective)))
                    old = None
                    if is_old:
                        old = dict(index=len(manifest["executions"]), request=deepcopy(r), request_sha256=v.digest(r),
                            status="MISSING_ACCOUNT_EVALUATION", launch_authorized=False, compatible_coordinate_role_matches=[],
                            role=role, center=center, neighborhood_id=old_id, row_id=row_id, candidate_id=r["candidate_id"])
                        floor["rows"].append(dict(deepcopy(row), execution_index=old["index"]))
                        manifest["executions"].append(old)
                    n["rows"].append(row)
                    executions.append(dict(alpha=key, request=r, request_sha256=v.digest(r), index=len(executions),
                        source=v.PRESERVED if is_old else v.NEW, union_design_id=nid, request_design_id=r["design_id"],
                        original_index=index, center=center, role=role, row_id=row_id, candidate_id=r["candidate_id"],
                        original_schema_execution=deepcopy(old), execution_status="NOT_EXECUTED_BY_COV_FIT",
                        coordinate_role_matches=[], launch_authorized=False, reuse_authorized=False, annual_views_available=False,
                        required_annual_views=["2021", "2022", "2023"]))
        manifest["request_count"] = len(manifest["executions"])
    prior, _ = v.original.collect_missing(bundle, parents, geometries)
    base = dict(entries=prior, geometries=geometries)
    union = dict(schema="m5111_covariance_fit_and_union_v1", status="PASS", fits=fits, neighborhoods=neighborhoods,
        executions=executions, fit_requests_closed=4, launch_authorized=False, reuse_authorized=False,
        account_union_complete=False, whole_128_probe_expansion=False, annual_local_ranking_authorized=False,
        financial_executions=0, builds=0)
    return union, base, bundle, parents


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.inputs = frozen()

    def test_full_union_preserves_195_and_registers_only_108(self):
        before = deepcopy(self.inputs)
        entries = v.collect_covariance(*self.inputs)
        self.assertEqual(self.inputs, before)
        self.assertEqual(len(entries), 108)
        self.assertEqual(Counter(e["request"]["alpha"] for e in entries), {"A-RSI": 96, "A-SC": 12})
        self.assertEqual(Counter(e["request"]["role"] for e in entries), {"selection_probe": 54, "local_validation": 54})
        for entry in entries:
            self.assertTrue(entry["request"]["probe_direction"].startswith("covariance:"))
            self.assertEqual(entry["analysis_id"], v.digest(entry["analysis"]))
            self.assertNotIn("schema_floor", entry["analysis"]["scope"])
            self.assertFalse(entry["analysis"]["annual_local_ranking_authorized"])

    def reject(self, change):
        change(*self.inputs)
        with self.assertRaises((ValueError, KeyError, StopIteration)):
            v.collect_covariance(*self.inputs)

    def test_request_digest_mismatch(self):
        self.reject(lambda u, *args: u["executions"][-1]["request"].update(probe_seed=1))

    def test_sealed_195_must_not_change(self):
        def change(u, *args):
            u["executions"][0]["request"]["design_id"] = "rewritten"
            u["executions"][0]["request_sha256"] = v.digest(u["executions"][0]["request"])
        self.reject(change)

    def test_frozen_spec02_must_not_change(self):
        self.reject(lambda u, base, *args: base["entries"][0]["analysis"].update(scope="rewritten"))

    def test_cloud_fit_request_must_match(self):
        self.reject(lambda u, *args: u["fits"][0].update(request_identity="changed"))

    def test_cloud_rank_support_and_recipe(self):
        for fields in (dict(centered_coordinate_rank=0), dict(supported=False), dict(distinct_cloud_count=4),
                       dict(recipe=dict(v.RECIPE, rho=.9)), dict(center_quality_eligible=False)):
            with self.subTest(fields=fields):
                inputs = frozen()
                inputs[0]["fits"][0].update(fields)
                with self.assertRaises(ValueError):
                    v.collect_covariance(*inputs)

    def test_unknown_cloud_member(self):
        self.reject(lambda u, *args: u["fits"][0]["cloud_ids"].append("outside-parent-roster"))

    def test_role_seed_radius(self):
        for fields in (dict(role="exploration"), dict(seed=732), dict(radius=.1)):
            inputs = frozen()
            inputs[0]["neighborhoods"][1].update(fields)
            with self.assertRaises(ValueError):
                v.collect_covariance(*inputs)

    def test_domain_or_parent_coordinate(self):
        self.reject(lambda u, base, bundle, parents: parents["A-RSI"]["rows"][10]["effective"].update(period=10000))

    def test_direction_exact_ready_and_execution_index(self):
        for fields in (dict(direction="axis:period:1"), dict(status="ALIAS"), dict(execution_index=-1)):
            inputs = frozen()
            row = inputs[0]["neighborhoods"][0]["rows"][-1]
            row.update(fields)
            with self.assertRaises(ValueError):
                v.collect_covariance(*inputs)

    def test_unqualified_coordinate_match_cannot_skip_account(self):
        self.reject(lambda u, *args: u["executions"][-1].update(coordinate_role_matches=[{"unqualified": True}]))

    def test_duplicate_or_missing_ready_request(self):
        for duplicate in (True, False):
            inputs = frozen()
            if duplicate:
                inputs[0]["executions"].append(deepcopy(inputs[0]["executions"][-1]))
            else:
                inputs[0]["executions"].pop()
            with self.assertRaises(ValueError):
                v.collect_covariance(*inputs)

    def test_no_invented_authority_or_views(self):
        for field in ("launch_authorized", "whole_128_probe_expansion", "annual_local_ranking_authorized"):
            inputs = frozen()
            inputs[0][field] = True
            with self.assertRaises(ValueError):
                v.collect_covariance(*inputs)
        self.reject(lambda u, *args: u["executions"][-1].update(annual_views_available=True))

    def test_non_covariance_entry_rejected_even_with_new_source(self):
        self.reject(lambda u, *args: u["executions"][0].update(source=v.NEW, original_schema_execution=None))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "fake_owner.py"
        self.source.write_text("# fake cold owner, no account engine\n")
        self.entries = v.collect_covariance(*frozen())
        self.registry = self.root / "registration.json"
        self.request = self.root / "request.json"
        self.value = dict(schema=v.SCHEMA, status="PREPARED_NOT_LAUNCHED", entries=self.entries,
            pins=[v.file_pin(self.source)], base_driver=v.file_pin(self.source), geometries={})
        self.registry.write_text(json.dumps(self.value))
        self.pin = v.file_pin(self.registry)
        self.entry = self.entries[0]
        self.request.write_text(json.dumps(self.entry["request"]))
        self.owner = SimpleNamespace(context_factory=Mock(), qualify=Mock(), validate_context=Mock())
        self.loader = Mock(return_value=self.owner)

    def run_worker(self):
        return v.execute_registered(self.registry, self.pin, self.entry["cell_id"], request_path=self.request,
            output=self.root / "output", progress=self.root / "progress.jsonl", load_driver=self.loader)

    def test_delegates_exact_original_execution_and_three_hooks(self):
        with patch.object(v.original, "execute_one", return_value={"fake_only": True}) as execute:
            self.assertEqual(self.run_worker(), {"fake_only": True})
        args, kwargs = execute.call_args
        self.assertEqual(args[0], self.entry)
        self.assertIs(kwargs["context_factory"], self.owner.context_factory)
        self.assertIs(kwargs["qualify"], self.owner.qualify)
        context = object()
        kwargs["validate_context"](context, self.entry["request"])
        self.owner.validate_context.assert_called_once_with(context, self.entry["request"], self.value)
        self.assertEqual(kwargs["pins"][-1], self.pin)

    def test_registry_tamper_rejected_before_owner_load(self):
        self.registry.write_text("{}")
        with self.assertRaises(RuntimeError):
            self.run_worker()
        self.loader.assert_not_called()

    def test_source_tamper_rejected_before_owner_load(self):
        self.source.write_text("# changed\n")
        with self.assertRaises(RuntimeError):
            self.run_worker()
        self.loader.assert_not_called()

    def test_custody_request_mismatch_rejected_before_owner_load(self):
        self.request.write_text("{}")
        with self.assertRaises(ValueError):
            self.run_worker()
        self.loader.assert_not_called()

    def test_analysis_tamper_even_in_new_registry_rejected(self):
        self.value["entries"][0]["analysis_id"] = "changed"
        self.registry.write_text(json.dumps(self.value))
        self.pin = v.file_pin(self.registry)
        with self.assertRaises(ValueError):
            self.run_worker()
        self.loader.assert_not_called()

    def test_original_failure_propagates_without_retry(self):
        with patch.object(v.original, "execute_one", side_effect=RuntimeError("fake fault")) as execute:
            with self.assertRaisesRegex(RuntimeError, "fake fault"):
                self.run_worker()
        self.assertEqual(execute.call_count, 1)


class ColdTests(unittest.TestCase):
    def test_conflicting_pin_never_overrides_original(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "source.py"
            path.write_text("# source\n")
            pin = v.file_pin(path)
            self.assertEqual(v.unique_pins([pin, pin]), [pin])
            with self.assertRaises(ValueError):
                v.unique_pins([pin, dict(pin, sha256="0"*64)])

    def test_exact_accepted_union_seal_required(self):
        with patch.object(v, "file_pin", return_value=dict(path="unused", bytes=1, sha256="0"*64)):
            with self.assertRaises(ValueError):
                v.sealed_input("cov-fit01/union_01.json")

    def test_specs_bounded_and_wrapper_request_ids_unchanged(self):
        entries = v.collect_covariance(*frozen())
        with TemporaryDirectory() as root:
            root = Path(root)
            registry, driver = root / "registration.json", root / "driver.py"
            registry.write_text("{}")
            driver.write_text("# fake driver, not executable finance\n")
            python = Path(sys.executable).resolve()
            groups = v.original.job_specs(entries, driver=driver, registration=registry, executable=python,
                cwd=root, pins=[v.file_pin(p) for p in (python, driver)], env=(("PYTHONNOUSERSITE", "1"),))
            specs = [Candidate.from_dict(c) for group in groups.values() for c in group]
            self.assertEqual([json.loads(c.request_json) for c in specs], [e["request"] for e in entries])
            for values in groups.values():
                self.assertLessEqual(len(json.dumps(values, sort_keys=True, indent=2))+1, 3*1024**2)
            self.assertTrue(all(c.cell_id.startswith("cov-") for c in specs))
            self.assertTrue(all(c.argv[0] == str(python) and c.argv[2] == str(driver) for c in specs))

    def test_fresh_process_adapter_and_private_hooks_import_no_runtime(self):
        code = """import importlib.util, sys
from tools.mode5_research import covariance_finance as v
spec = importlib.util.spec_from_file_location('cov_cold_driver', v.DRIVER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
owner = module.load_driver(v.file_pin(v.BASE_DRIVER))
assert callable(owner.context_factory) and callable(owner.validate_context) and callable(owner.qualify)
assert not any(n.startswith(('quantbt', '_quantbt_native', 'numpy', 'pandas', 'numba', 'scipy')) or n in {'finance', 'prepared'} for n in sys.modules)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=v.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preparation_rejects_wrong_or_existing_lane(self):
        with self.assertRaises(ValueError):
            v.prepare(v.STEP / "not-owned")
        with patch.object(Path, "exists", return_value=True):
            with self.assertRaises(ValueError):
                v.prepare()


if __name__ == "__main__":
    unittest.main()
