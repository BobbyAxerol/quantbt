import numpy as np
import pytest

from tools.mode5_environments import FeatureTape
from tools.mode5_environments.manifests import calendar


def test_unpublished_unsigned_availability_cannot_wrap_into_past_timestamp():
    with pytest.raises(ValueError,match="timestamp"):
        FeatureTape.from_arrays("provider-v1",np.array([1,2,3],dtype=np.int64),[1.,2.,3.],
            np.array([1,2,2**63+100],dtype=np.uint64),np.zeros(3,dtype=np.int8))


def test_nat_calendar_sentinel_is_not_a_historical_observation():
    with pytest.raises(ValueError,match="calendar"):
        calendar(np.array([np.iinfo(np.int64).min,1,2],dtype=np.int64))


def test_nat_availability_cannot_authorize_valid_feature():
    with pytest.raises(ValueError,match="timestamp"):
        FeatureTape.from_arrays("provider-v1",np.array([1,2,3],dtype=np.int64),[1.,2.,3.],
            np.array([1,2,np.iinfo(np.int64).min],dtype=np.int64),np.zeros(3,dtype=np.int8))
