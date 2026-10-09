import numpy as np

from tests.mode5.test_admission_ledger import market, order, run
from quantbt import OrderSide
from tools.mode5_geometry import EffectiveGeometry, active_neighbors, local_summary


def test_m5t_060_actual_quantbt_keeps_bad_feasible_neighbors_and_fills():
    g = EffectiveGeometry.from_ranges({"quantity": (1, 10)})
    center = g.resolve(dict(quantity=5))
    n = active_neighbors(g, center, radius=.1, minimum_radius=.05, seed=1731, role="selection_probe")
    frame = market(110.-np.arange(12))
    def execute(point):
        qty = point.params["quantity"]
        result = run(frame, (order(frame, 1, OrderSide.BUY, qty, "entry"),
            order(frame, 10, OrderSide.SELL, qty, "exit", reduce_only=True)))
        assert len(result.fills) == 2 and result.fees.sum() > 0
        return dict(status="COMPLETE", utility=float(result.equity.iloc[-1]-20000.))
    baseline = execute(center)
    evaluations = {r.point.identity: execute(r.point) for r in n.rows if r.status == "READY"}
    assert all(row["utility"] < 0 for row in evaluations.values())
    out = local_summary(baseline["utility"], n, evaluations, quality_floor=0., reference_scale=10., reference_id="money-10")
    assert out["status"] == "QUALITY_FAIL" and out["max_downside"] > 0
    assert out["valid_probes"] == n.coverage["unique_effective"]
