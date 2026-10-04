"""Exact derived material reuse is independent of financial execution."""

from dataclasses import replace
from types import SimpleNamespace
import hashlib

import numpy as np
import pandas as pd
import pytest

from quantbt.optimization.meta_selection.common import digest, utc, MetaRecordError
from quantbt.optimization.meta_selection.observer import market_signature
from quantbt.optimization.meta_selection.witness import PreparedMetricWitness
from tests.meta_selection.test_qms05_public import public_endpoint, context, RANGES, native_digest
from tools.qms01_baseline import market


@pytest.mark.parametrize("funding", [False, True])
@pytest.mark.parametrize("stop", [3, 21, 40])
def test_market_and_headers_exact(funding, stop):
    frame = market().iloc[:40]
    config = SimpleNamespace(funding_rate=pd.Series(np.arange(len(frame)) * .001,
                                                    index=frame.index) if funding else .001)
    owner = PreparedMetricWitness(frame, config=config)
    prefix, index = frame.iloc[:stop], frame.index[1:stop]
    old = market_signature(prefix, index, config=config)
    assert owner.market_signature(prefix, index) == old
    assert owner.market_signature(prefix, index) == old
    assert owner.market_signature(prefix.copy(), index) == old
    kwargs = dict(initial_capital=20000.0, economics_id="e", metric_id="m", input_signature=old)
    header = hashlib.sha256(digest(dict(index=[utc(t).isoformat() for t in index],
        initial_capital=20000.0, economics="e", metric="m", input=old)).encode())
    for _ in range(2):
        actual = owner.header(index, **kwargs)
        actual.update(b"original-result")
        expected = header.copy()
        expected.update(b"original-result")
        assert actual.hexdigest() == expected.hexdigest()
    assert owner.stats["header_hits"] == owner.stats["market_hits"] == 1
    owner.validate_source()
    owner.close()
    assert owner.metadata["retained_bytes"] == owner.metadata["owned_row_hash_bytes"] == 0
    with pytest.raises(MetaRecordError, match="CLOSED"):
        owner.header(index, **kwargs)


@pytest.mark.parametrize("change", ["volume", "funding", "schema", "index"])
def test_mutation_guard(change):
    frame = market().iloc[:40].copy()
    config = SimpleNamespace(funding_rate=pd.Series(.001, index=frame.index))
    owner = PreparedMetricWitness(frame, config=config)
    if change == "funding":
        config.funding_rate.iloc[1] += .01
    elif change == "schema":
        frame.rename(columns={"close": "other"}, inplace=True)
    elif change == "index":
        frame.index = frame.index + pd.Timedelta(seconds=1)
    else:
        frame["volume"] = np.arange(len(frame))
    with pytest.raises(MetaRecordError, match="MUTATED"):
        owner.validate_source()


def test_bounded_timezone_precision_capital_input_and_result_calendar():
    frame = market().iloc[:40]
    owner = PreparedMetricWitness(frame, config=SimpleNamespace(funding_rate=0), max_entries=2, max_bytes=512)
    index = frame.index[:3] + pd.Timedelta(nanoseconds=7)
    kwargs = dict(initial_capital=20., economics_id="e", metric_id="m", input_signature="a")
    a = owner.header(index, **kwargs).hexdigest()
    assert owner.header(index.tz_convert("Asia/Saigon"), **kwargs).hexdigest() == a
    assert owner.header(index[:-1], **kwargs).hexdigest() != a
    assert owner.header(index, **{**kwargs, "initial_capital": 21.}).hexdigest() != a
    assert owner.header(index, **{**kwargs, "input_signature": "b"}).hexdigest() != a
    assert owner.metadata["entries"] <= 2 and owner.metadata["retained_bytes"] <= 512
    assert owner.stats["evictions"] > 0


def test_full_shadow_reference_pool_hash_decision_account_parity():
    runs = []
    for enabled in (False, True):
        endpoint = public_endpoint("shadow", observer=True, native_batch_policy="reference")
        cfg = endpoint.config.walkforward_config
        endpoint.config = replace(endpoint.config, walkforward_config=replace(cfg,
            metadata={**cfg.metadata, "use_prepared_meta_witness": enabled}))
        result = endpoint.backtest(data=market(), param_ranges=RANGES, meta_history=context())
        runs.append(result)
    assert native_digest(runs[0]) == native_digest(runs[1])
    a, b = (r.metadata["walk_forward"]["meta_selection"] for r in runs)
    for ta, tb in zip(a["tasks"], b["tasks"]):
        assert [(c.effective_params, c.observation) for c in ta.candidates] == [
            (c.effective_params, c.observation) for c in tb.candidates]
    for sa, sb in zip(a["records"], b["records"]):
        for key in ("selected_evaluation_id", "native_selected_evaluation_id", "meta_proposed_evaluation_id"):
            assert sa[key] == sb[key]
    cache = runs[1].metadata["walk_forward"]["prepared_scoring_cache"]["meta_witness"]
    assert cache["header_hits"] > 0 and cache["market_hits"] > 0 and cache["closed"]
