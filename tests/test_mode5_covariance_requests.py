"""Synthetic cold geometry contracts; no account execution or financial imports."""

from copy import deepcopy
from dataclasses import asdict
import importlib
import sys
import unittest
from unittest.mock import patch

from tools.mode5_research import covariance_requests as v


owner = v.numeric_owner()
from quantbt.mode5.geometry.schema import EffectiveGeometry
from tools.mode5_geometry.design import design_identity


def geometry():
    return EffectiveGeometry.from_ranges(dict(x=(0., 1.), y=(0., 1.), category=[False, True]))


def point(g, x=.5, y=.5, category=True):
    return g.resolve(dict(x=x, y=y, category=category))


def cloud(g):
    return tuple(point(g, x, y) for x, y in ((.5, .5), (.4, .5), (.6, .5), (.5, .4), (.5, .6)))


def neighborhood(g, points=(), role="selection_probe", seed=732):
    return owner.active_neighbors(g, point(g), radius=.1 if role == "selection_probe" else .12,
        seed=seed, role=role, minimum_radius=.05, cloud=points, rho=.2, tau=.001, minimum_cloud=5, cloud_radius=.25)


def sealed_floor(g):
    n = neighborhood(g)
    rows = [v.serialize(r) for r in n.rows]
    floor = dict(rows=rows, neighborhood_id="original-schema-id", role="selection_probe", radius=.1,
                 seed=732, parent_candidate_id=point(g).identity)
    template = dict(alpha="SYNTHETIC", role="selection_probe", params=point(g).params, candidate_id=point(g).identity,
        start="2021-01-01", stop="2024-01-01", account_mode="continuous_development_2021_2023",
        design_id="original-schema-id", parent_design_id="original-parent", parent_candidate_id=point(g).identity)
    requests = []
    for row in rows:
        if row["status"] == "READY":
            request = template | dict(params=row["effective"], candidate_id=row["candidate_id"], proposal_row=row["row_id"],
                probe_direction=row["direction"], probe_seed=732, probe_radius=.1, parent_panel_index=10, neighborhood_center=0)
            requests.append(dict(row_id=row["row_id"], neighborhood_id="original-schema-id", request=request,
                                 request_sha256=v.custody.digest(request)))
    return floor, requests, template


class OriginalOwnerTests(unittest.TestCase):
    def test_original_files_and_algorithm_owner(self):
        self.assertEqual(owner.active_neighbors.__module__, "tools.mode5_geometry.neighborhoods")
        for path, sha in v.ORIGINAL_SOFTWARE.items():
            self.assertEqual(v.custody.pin(v.ROOT / path)["sha256"], sha)

    def test_exact_geometry_metadata_round_trip(self):
        g = geometry()
        hydrated = v.load_geometry(g.metadata(), g.identity)
        self.assertEqual(hydrated.identity, g.identity)
        self.assertEqual(hydrated.resolve(point(g).params), point(g))

    def test_changed_geometry_identity_rejects(self):
        g = geometry()
        with self.assertRaises(ValueError):
            v.load_geometry(g.metadata(), "unsealed")

    def test_no_cloud_is_explicit(self):
        self.assertEqual(neighborhood(geometry()).covariance_status, "SCHEMA_ONLY_NO_CLOUD")

    def test_sparse_cloud_measured_by_original_owner(self):
        g = geometry()
        n = neighborhood(g, cloud(g)[:4])
        self.assertEqual(n.covariance_status, "SCHEMA_ONLY_SPARSE_CLOUD")
        self.assertFalse(any(r.direction.startswith("covariance:") for r in n.rows))

    def test_singular_cloud_not_regularized_into_fake_support(self):
        g = geometry()
        points = tuple(point(g, x, x) for x in (.4, .45, .5, .55, .6))
        n = neighborhood(g, points)
        self.assertEqual(n.covariance_status, "SCHEMA_ONLY_SINGULAR_CLOUD")
        self.assertFalse(any(r.direction.startswith("covariance:") for r in n.rows))

    def test_supported_cloud_exact_covariance_directions(self):
        g = geometry()
        n = neighborhood(g, cloud(g))
        self.assertEqual(n.covariance_status, "REGULARIZED_PROPOSALS_NOT_HESSIAN")
        self.assertEqual([r.direction for r in n.rows if r.direction.startswith("covariance:")],
                         ["covariance:0", "covariance:1", "covariance:2", "covariance:3"])

    def test_same_seed_original_direction_identity(self):
        g = geometry()
        first, second = neighborhood(g, cloud(g)), neighborhood(g, cloud(g))
        self.assertEqual(first.rows, second.rows)
        self.assertEqual(design_identity(first.rows, method="active_neighbors_v1", seed=732, schema_id=g.identity),
                         design_identity(second.rows, method="active_neighbors_v1", seed=732, schema_id=g.identity))

    def test_validation_seed_and_radius_produce_separate_directions(self):
        g = geometry()
        first = neighborhood(g, cloud(g))
        second = neighborhood(g, cloud(g), role="local_validation", seed=733)
        self.assertNotEqual(first.rows[-1].requested_json, second.rows[-1].requested_json)
        self.assertEqual(second.role, "local_validation")

    def test_duplicate_cloud_does_not_reach_minimum_five(self):
        g = geometry()
        n = neighborhood(g, (point(g),)*10)
        self.assertEqual(n.covariance_status, "SCHEMA_ONLY_SPARSE_CLOUD")

    def test_original_owner_rejects_cross_branch(self):
        g = geometry()
        with self.assertRaises(ValueError):
            neighborhood(g, cloud(g)+(point(g, category=False),))

    def test_original_owner_rejects_outside_local_radius(self):
        g = geometry()
        far = g.resolve(dict(x=1., y=1., category=True))
        with self.assertRaises(ValueError):
            neighborhood(g, cloud(g)+(far,))


class CloudPolicyTests(unittest.TestCase):
    def row(self, **metrics):
        return dict(status="PASS", metrics=dict(daily_count=1095, economic_utility=.1, max_drawdown=.2) | metrics,
                    support=dict(fills=None, closed_campaigns=None))

    def test_original_quality_floor_is_inclusive_zero(self):
        self.assertTrue(v.qualify(self.row(economic_utility=0.), v.QUALIFICATION))
        self.assertFalse(v.qualify(self.row(economic_utility=-.00001), v.QUALIFICATION))

    def test_original_dd_days_and_undefined_gates(self):
        for metrics in (dict(max_drawdown=.50001), dict(daily_count=364), dict(economic_utility=None),
                        dict(economic_utility=float("nan"))):
            self.assertFalse(v.qualify(self.row(**metrics), v.QUALIFICATION))

    def test_available_ledger_support_not_fabricated(self):
        row = self.row()
        self.assertTrue(v.qualify(row, v.QUALIFICATION))
        row["support"] = dict(fills=29, closed_campaigns=20)
        self.assertFalse(v.qualify(row, v.QUALIFICATION))
        row["support"] = dict(fills=30, closed_campaigns=19)
        self.assertFalse(v.qualify(row, v.QUALIFICATION))
        row["support"] = dict(fills=30, closed_campaigns=20)
        self.assertTrue(v.qualify(row, v.QUALIFICATION))

    def test_gate_threshold_changes_reject(self):
        with self.assertRaises(ValueError):
            v.qualify(self.row(), v.QUALIFICATION | dict(quality_floor=-1.))

    def test_cloud_filter_preserves_input_order_and_branch(self):
        g = geometry()
        ranked = [dict(point=p) for p in (point(g, .6), point(g, category=False), point(g, .4), point(g, 1., 1.))]
        got = v.cloud_for(g, point(g), ranked, v.RECIPE)
        self.assertEqual(got, (ranked[0]["point"], ranked[2]["point"]))

    def test_recipe_changes_reject(self):
        g = geometry()
        for key, val in dict(rho=.3, tau=.01, cloud_radius=.5, minimum_cloud=4, selection_seed=1).items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                v.cloud_for(g, point(g), [], v.RECIPE | {key: val})


class UnionCustodyTests(unittest.TestCase):
    def test_preserved_schema_requests_are_byte_identity_equivalent(self):
        g = geometry()
        floor, old, template = sealed_floor(g)
        before = deepcopy(old)
        rows = [v.serialize(r) for r in neighborhood(g, cloud(g)).rows]
        requests = v.union_requests(rows, floor, old, template, "new-union", 0, 10)
        preserved = [r for r in requests if r["source"] == "PRESERVED_SEALED_SCHEMA_REQUEST"]
        self.assertEqual([r["request"] for r in preserved], [r["request"] for r in old])
        self.assertEqual(old, before)
        self.assertTrue(all(r["request_design_id"] == "original-schema-id" and r["union_design_id"] == "new-union" for r in preserved))

    def test_covariance_requests_are_new_role_specific_and_unexecuted(self):
        g = geometry()
        floor, old, template = sealed_floor(g)
        rows = [v.serialize(r) for r in neighborhood(g, cloud(g)).rows]
        requests = v.union_requests(rows, floor, old, template, "new-union", 0, 10)
        added = [r for r in requests if r["source"].startswith("NEW_")]
        self.assertEqual(len(added), 4)
        for r in added:
            self.assertEqual(r["request_design_id"], "new-union")
            self.assertEqual(r["role"], "selection_probe")
            self.assertEqual(r["request_sha256"], v.custody.digest(r["request"]))
            self.assertFalse(r["launch_authorized"])
            self.assertFalse(r["annual_views_available"])

    def test_schema_only_fallback_has_no_incremental_accounts(self):
        g = geometry()
        floor, old, template = sealed_floor(g)
        rows = [v.serialize(r) for r in neighborhood(g, cloud(g)[:2]).rows]
        requests = v.union_requests(rows, floor, old, template, "fallback-union", 0, 10)
        self.assertEqual(len(requests), len(old))
        self.assertTrue(all(r["source"] == "PRESERVED_SEALED_SCHEMA_REQUEST" for r in requests))

    def test_schema_prefix_change_rejects(self):
        g = geometry()
        floor, old, template = sealed_floor(g)
        rows = [v.serialize(r) for r in neighborhood(g, cloud(g)).rows]
        rows[0]["candidate_id"] = "changed"
        with self.assertRaises(ValueError):
            v.union_requests(rows, floor, old, template, "union", 0, 10)

    def test_old_request_digest_change_rejects(self):
        g = geometry()
        floor, old, template = sealed_floor(g)
        old[0]["request"]["params"] = dict(changed=True)
        with self.assertRaises(ValueError):
            v.union_requests([v.serialize(r) for r in neighborhood(g).rows], floor, old, template, "union", 0, 10)

    def test_center_and_within_role_collision_are_never_accounts(self):
        g = EffectiveGeometry.from_ranges(dict(x=(0, 2)))
        center = g.resolve(dict(x=1))
        n = owner.active_neighbors(g, center, radius=.1, seed=732, role="selection_probe", minimum_radius=.05)
        collisions = [r for r in n.rows if r.status == "COLLISION"]
        self.assertTrue(collisions)
        self.assertTrue(any(r.duplicate_of == -1 for r in collisions))

    def test_no_financial_runtime_imports(self):
        self.assertFalse(any(v.forbidden(n) for n in sys.modules))
        for name in ("quantbt.core", "quantbt.endpoint", "quantbt.backtester", "quantbt.backends", "_quantbt_native"):
            with self.subTest(name=name), self.assertRaises(ImportError):
                importlib.import_module(name)

    def test_no_replacement_rng_or_algorithm(self):
        g = geometry()
        with patch.object(owner, "active_neighbors", wraps=owner.active_neighbors) as spy:
            neighborhood(g, cloud(g))
            spy.assert_called_once()

    def test_four_targets_only_not_whole128(self):
        self.assertEqual(v.TARGETS, dict(rsi=[10, 49, 114], sc=[33]))
        self.assertEqual(sum(len(x) for x in v.TARGETS.values()), 4)


if __name__ == "__main__":
    unittest.main()
