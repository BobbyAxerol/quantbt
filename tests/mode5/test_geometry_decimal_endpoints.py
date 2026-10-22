"""Public synthetic reproduction of valid endpoints rejected after decoding."""

import math

import pytest

from quantbt.mode5.geometry.schema import EffectiveGeometry
from quantbt.diagnostics.geometry.design import neutral_coverage


@pytest.mark.parametrize('low,high,step', [(.2,.9,.05), (.2,3.,.1), (.1,.3,.1)])
def test_decoded_decimal_endpoint_is_in_original_schema(low, high, step):
    geometry = EffectiveGeometry.from_ranges(dict(x=(low,high,step)))
    value = geometry.decode('x', 1.)
    assert value == high
    assert geometry.resolve(dict(x=value)).params['x'] == high


def test_unaligned_upper_bound_stays_on_original_grid():
    geometry = EffectiveGeometry.from_ranges(dict(x=(.2,.96,.1)))
    assert geometry.decode('x',1.) == pytest.approx(.9)
    assert geometry.decode('x',1.) != .96
    geometry.resolve(dict(x=geometry.decode('x',1.)))


def test_original_input_validation_is_not_relaxed():
    geometry = EffectiveGeometry.from_ranges(dict(x=(.2,.9,.05)))
    with pytest.raises(ValueError):
        geometry.resolve(dict(x=math.nextafter(.9, math.inf)))
    with pytest.raises(ValueError):
        geometry.resolve(dict(x=.225))
    for z in (-.01,1.01,float('nan')):
        with pytest.raises(ValueError):
            geometry.decode('x', z)


def test_neutral_design_keeps_all_declared_feasible_decimal_endpoints():
    geometry = EffectiveGeometry.from_ranges(dict(x=(.2,.9,.05), y=(.2,3.,.1), period=(2,128)))
    ledger = neutral_coverage(geometry,branches=(({},128),),seed=731)
    assert len(ledger.rows) == 128
    assert all(row.status == 'READY' for row in ledger.rows)
    for row in ledger.rows:
        geometry.resolve(row.point.params)


def test_integer_and_interior_values_keep_the_same_quantization():
    geometry = EffectiveGeometry.from_ranges(dict(period=(2,20,2), scale=(.2,.9,.05)))
    for z in (.01,.15,.38,.63,.82):
        spec = geometry.specs[1]
        before = spec.low+math.floor((spec.low+z*(spec.high-spec.low)-spec.low)/spec.step+.5)*spec.step
        assert geometry.decode('scale',z) == before
    assert geometry.decode('period',.15) == 4
