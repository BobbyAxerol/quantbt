from pathlib import Path
import runpy

import numpy as np

from public_fixtures import alpha, public_setup


def test_documented_optional_wrapper_uses_same_public_contract(tmp_path):
    original, frame, ranges, calibration = public_setup(tmp_path)
    wrapper = runpy.run_path(str(Path(__file__).resolve().parents[2] /
                                "examples/mode5_calibration_optin.py"))["calibrate"]
    endpoint, result, audit = wrapper(data=frame, strategy=alpha, param_ranges=ranges,
        calibration=calibration,
        account_kwargs=dict(initial_capital=20000., fee=.0005, slippage=.0001,
            alloc_per_trade=.5, leverage=1., use_funding=False, symbols=["ETHUSDT"]))
    assert audit["status"] == "SELECTED_REPLAY_VERIFIED"
    assert audit["deployment_authorized"] is False
    assert audit["selected_audit"]
    assert np.isfinite(result.equity).all()
    assert endpoint.config.mode == original.config.mode
