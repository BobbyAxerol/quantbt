"""Serialization and recorded-ledger parity, without financial execution."""

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json

import pytest

from quantbt.metrics.report_contracts import (
    ReportingContractV1,
    ReportingCoverageV1,
    ReportingMetricV1,
)
from quantbt.metrics.reporting.ledger import reduce_ledger
from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome
from quantbt.metrics.reporting.results import ReportingResult


def _contract(cls=ReportingContractV1, **changes):
    values = dict(scope="full", unit="account_period", currency="USDT",
                  baseline_equity=100., baseline_time_ns=10, scope_end_ns=50,
                  sampling="observed_bar", annual_periods=365., equity_clock="bar_close")
    values.update(changes)
    return cls(**values)


def _coverage(cls=ReportingCoverageV1, **changes):
    values = dict(result_identity="recorded-report", producer="parity-control",
                  profile="audit", ledger="complete", retained_rows=0, dropped_rows=0)
    values.update(changes)
    return cls(**values)


def _contract_digest(policy):
    encoded = json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("ascii")).hexdigest()


def _metric(cls=ReportingMetricV1, **changes):
    values = dict(metric_id="reporting.synthetic.net", contract_identity=_contract_digest(_contract()),
                  unit="USDT", status="valid", value=12.5, sample_count=3, coverage=_coverage())
    values.update(changes)
    return cls(**values)


def _assert_asdict_parity(value):
    expected = asdict(value)
    actual = value.to_metadata()
    assert type(actual) is dict
    assert actual == expected
    assert list(actual) == list(expected)
    assert json.dumps(actual, separators=(",", ":"), allow_nan=False) == json.dumps(
        expected, separators=(",", ":"), allow_nan=False)
    return actual


@pytest.mark.parametrize("unit", ["account_period", "closed_trade", "closed_action"])
def test_contract_metadata_matches_asdict_json_order_identity_and_roundtrip(unit):
    settings = dict(unit=unit, currency="\u20ac", scope="scoped", annual_periods=252.,
                    risk_free_per_period=-0.0, mar_per_period=.001, variance_ddof=0,
                    partial_periods="exclude_disclosed", sortino_denominator="negative_observations")
    if unit != "account_period":
        settings.update(matching="recorded_lot", ledger_scope="closed_in_scope_lifetime")
    if unit == "closed_action":
        settings["grouping"] = "authoritative_action_id"
    policy = _contract(**settings)
    expected_identity = _contract_digest(policy)
    first = _assert_asdict_parity(policy)
    assert policy.identity == expected_identity
    rebuilt = ReportingContractV1.from_metadata(json.loads(json.dumps(first, allow_nan=False)))
    assert rebuilt == policy and rebuilt.identity == expected_identity
    first["currency"] = "changed export"
    first["baseline_equity"] = -1.
    assert policy.to_metadata() == asdict(policy)
    assert policy.identity == expected_identity


@pytest.mark.parametrize("status", ["valid", "no_loss", "undefined", "unavailable", "insufficient", "invalid"])
def test_metric_metadata_matches_asdict_and_detaches_coverage_for_each_status(status):
    coverage = _coverage(ledger="truncated", retained_rows=3, dropped_rows=2,
                         reason="some recorded outcomes were not retained")
    metric = _metric(status=status, coverage=coverage, value=12.5 if status == "valid" else None,
                     reason=None if status == "valid" else "explicit declared undefined policy")
    expected = asdict(metric)
    first = _assert_asdict_parity(metric)
    second = metric.to_metadata()
    assert type(first["coverage"]) is dict
    assert list(first["coverage"]) == list(asdict(coverage))
    assert first["coverage"] is not second["coverage"]
    assert ReportingMetricV1.from_metadata(json.loads(json.dumps(first, allow_nan=False))) == metric
    first["coverage"]["reason"] = "changed export"
    first["sample_count"] = 0
    assert second == expected == metric.to_metadata()
    assert coverage.reason == "some recorded outcomes were not retained"


@dataclass
class _NestedExtra:
    labels: list = field(default_factory=lambda: ["declared"])
    options: dict = field(default_factory=lambda: {"branches": [{"weights": (1., None)}]})


@dataclass(frozen=True, kw_only=True)
class _ExtendedContract(ReportingContractV1):
    extra: _NestedExtra = field(default_factory=_NestedExtra)


@dataclass(frozen=True, kw_only=True)
class _ExtendedCoverage(ReportingCoverageV1):
    extra: _NestedExtra = field(default_factory=_NestedExtra)


@dataclass(frozen=True, kw_only=True)
class _ExtendedMetric(ReportingMetricV1):
    extra: _NestedExtra = field(default_factory=_NestedExtra)


def test_contract_subclass_retains_all_dataclass_fields_and_recursively_detaches_extras():
    policy = _contract(_ExtendedContract)
    first = _assert_asdict_parity(policy)
    expected_identity = _contract_digest(policy)
    assert list(first)[-1] == "extra"
    assert type(first["extra"]) is dict
    assert type(first["extra"]["options"]["branches"][0]["weights"]) is tuple
    assert policy.identity == expected_identity
    first["extra"]["labels"].append("changed")
    first["extra"]["options"]["branches"][0]["weights"] = (99.,)
    assert policy.extra.labels == ["declared"]
    assert policy.extra.options == {"branches": [{"weights": (1., None)}]}
    assert policy.identity == expected_identity
    _assert_asdict_parity(policy)


@pytest.mark.parametrize("extended_metric", [False, True])
def test_metric_and_coverage_subclasses_keep_extra_fields_and_asdict_alias_boundaries(extended_metric):
    shared = _NestedExtra()
    coverage = _coverage(_ExtendedCoverage, extra=shared)
    metric = (_metric(_ExtendedMetric, coverage=coverage, extra=shared) if extended_metric
              else _metric(coverage=coverage))
    first = _assert_asdict_parity(metric)
    second = metric.to_metadata()
    assert type(first["coverage"]["extra"]) is dict
    assert first["coverage"]["extra"] is not second["coverage"]["extra"]
    if extended_metric:
        assert list(first)[-1] == "extra"
        assert first["extra"] is not first["coverage"]["extra"]
        assert first["extra"]["labels"] is not first["coverage"]["extra"]["labels"]
        first["extra"]["labels"].append("metric export")
        assert first["coverage"]["extra"]["labels"] == ["declared"]
    first["coverage"]["extra"]["labels"].append("coverage export")
    assert shared.labels == ["declared"]
    assert second == asdict(metric) == metric.to_metadata()


class _PlainContract(ReportingContractV1):
    pass


class _PlainCoverage(ReportingCoverageV1):
    pass


class _PlainMetric(ReportingMetricV1):
    pass


def test_plain_subclasses_do_not_export_non_dataclass_attributes():
    policy = _contract(_PlainContract)
    coverage = _coverage(_PlainCoverage)
    metric = _metric(_PlainMetric, coverage=coverage)
    for value in (policy, coverage, metric):
        object.__setattr__(value, "non_field_note", {"private": [1, 2]})
    for value in (policy, metric):
        payload = _assert_asdict_parity(value)
        assert "non_field_note" not in payload
    assert "non_field_note" not in metric.to_metadata()["coverage"]
    assert policy.identity == _contract_digest(policy)


class _FloatWithState(float):
    def __new__(cls, value):
        result = super().__new__(cls, value)
        result.state = {"history": [1, 2]}
        return result


class _StringWithState(str):
    def __new__(cls, value):
        result = super().__new__(cls, value)
        result.state = {"history": [1, 2]}
        return result


@pytest.mark.parametrize("name", ["baseline_equity", "annual_periods", "currency"])
def test_one_non_atomic_contract_field_alone_retains_deepcopy_semantics(name):
    original = _StringWithState("USDT") if name == "currency" else _FloatWithState(100.)
    policy = _contract(**{name: original})
    payload = _assert_asdict_parity(policy)
    assert type(payload[name]) is type(original) and payload[name] is not original
    payload[name].state["history"].append("export only")
    assert original.state == policy.to_metadata()[name].state == {"history": [1, 2]}
    assert policy.identity == _contract_digest(policy)


@pytest.mark.parametrize("name", [
    "value", "metric_id", "unit", "reason", "coverage.result_identity",
    "coverage.producer", "coverage.profile", "coverage.reason",
])
def test_one_non_atomic_metric_or_coverage_field_alone_retains_deepcopy_semantics(name):
    spelling = "reporting.synthetic.net" if name == "metric_id" else "USDT"
    original = _FloatWithState(12.5) if name == "value" else _StringWithState(spelling)
    changes = {}
    if name.startswith("coverage."):
        coverage_changes = {name.split(".", 1)[1]: original}
        if name == "coverage.reason":
            coverage_changes.update(ledger="truncated", retained_rows=1, dropped_rows=1)
        changes["coverage"] = _coverage(**coverage_changes)
    else:
        changes[name] = original
        if name == "reason":
            changes.update(status="undefined", value=None)
    metric = _metric(**changes)
    payload = _assert_asdict_parity(metric)
    exported = payload["coverage"][name.split(".", 1)[1]] if name.startswith("coverage.") else payload[name]
    assert type(exported) is type(original) and exported is not original
    exported.state["history"].append("export only")
    assert original.state == {"history": [1, 2]}
    fresh = metric.to_metadata()
    repeated = fresh["coverage"][name.split(".", 1)[1]] if name.startswith("coverage.") else fresh[name]
    assert repeated.state == {"history": [1, 2]}


def test_contract_float_and_string_subclasses_preserve_deepcopy_not_isinstance_fastpath():
    number, word = _FloatWithState(100.), _StringWithState("USDT")
    policy = _contract(baseline_equity=number, annual_periods=number, currency=word)
    first = _assert_asdict_parity(policy)
    second = policy.to_metadata()
    for name, original in (("baseline_equity", number), ("annual_periods", number), ("currency", word)):
        assert type(first[name]) is type(original)
        assert first[name] is not original and first[name] is not second[name]
        assert first[name].state is not original.state
        assert first[name].state["history"] is not original.state["history"]
        first[name].state["history"].append(name)
        assert original.state == {"history": [1, 2]}
        assert second[name].state == {"history": [1, 2]}
    assert first["baseline_equity"] is not first["annual_periods"]
    assert first["baseline_equity"].state is not first["annual_periods"].state
    assert policy.identity == _contract_digest(policy)


@pytest.mark.parametrize("valid", [False, True])
def test_metric_float_string_and_nested_coverage_subclasses_preserve_deepcopy(valid):
    number, word = _FloatWithState(12.5), _StringWithState("USDT")
    metric_id = _StringWithState("reporting.synthetic.net")
    reason = None if valid else _StringWithState("not enough observations")
    coverage = _coverage(result_identity=word, producer=word)
    metric = _metric(metric_id=metric_id, unit=word, coverage=coverage,
                     status="valid" if valid else "insufficient", value=number if valid else None, reason=reason)
    first = _assert_asdict_parity(metric)
    second = metric.to_metadata()
    pairs = [(first["metric_id"], second["metric_id"], metric_id),
             (first["unit"], second["unit"], word),
             (first["coverage"]["producer"], second["coverage"]["producer"], word),
             (first["coverage"]["result_identity"], second["coverage"]["result_identity"], word)]
    pairs.append((first["value"], second["value"], number) if valid else (first["reason"], second["reason"], reason))
    for exported, repeated, original in pairs:
        assert type(exported) is type(original)
        assert exported is not original and exported is not repeated
        assert exported.state["history"] is not original.state["history"]
        exported.state["history"].append("changed")
        assert original.state == repeated.state == {"history": [1, 2]}
    assert first["coverage"]["producer"] is not first["coverage"]["result_identity"]
    assert second == asdict(metric)


def test_result_metadata_detaches_metrics_shared_coverage_and_nested_provenance():
    coverage = _coverage()
    metrics = (_metric(coverage=coverage), _metric(metric_id="reporting.synthetic.count", value=3., coverage=coverage))
    provenance = {"contract": asdict(_contract()), "nested": {"rows": [{"values": [1, 2]}]}}
    report = ReportingResult(contract_identity=_contract_digest(_contract()), input_identity="a" * 64,
                             metrics=metrics, provenance_json=json.dumps(provenance))
    expected = dict(contract_identity=report.contract_identity, input_identity=report.input_identity,
                    metrics=[asdict(metric) for metric in metrics], provenance=provenance)
    first, second = report.to_metadata(), report.to_metadata()
    assert first == second == expected
    assert json.dumps(first, allow_nan=False) == json.dumps(expected, allow_nan=False)
    assert first["metrics"][0]["coverage"] is not first["metrics"][1]["coverage"]
    assert first["metrics"][0]["coverage"] is not second["metrics"][0]["coverage"]
    first["metrics"][0]["coverage"]["producer"] = "changed"
    first["provenance"]["nested"]["rows"][0]["values"].append(99)
    assert first["metrics"][1]["coverage"]["producer"] == coverage.producer
    assert second == report.to_metadata() == expected


def _ledger_contract(unit):
    return _contract(unit=unit, matching="position_episode", ledger_scope="closed_in_scope_lifetime",
                     grouping="authoritative_action_id" if unit == "closed_action" else "none")


def _outcome(trade_id, *, closed_at_ns=20, close_sequence=0, close_reason=None, **changes):
    values = dict(trade_id=trade_id, symbol="ETH", side="long", currency="USDT",
                  opened_at_ns=0, closed_at_ns=closed_at_ns, close_sequence=close_sequence,
                  close_reason=close_reason, net_pnl=1., allocated_fee=0.,
                  allocated_funding_cost=0., allocated_slippage_cost=0.)
    values.update(changes)
    return RecordedOutcome(**values)


@pytest.mark.parametrize(
    ("reasons", "expected"),
    [
        ((), {}),
        ((None, None), {}),
        (("take_profit", "stop", None, "take_profit", "roll_close"),
         {"roll_close": 1, "stop": 1, "take_profit": 2}),
        (("zeta", "", "alpha", "zeta", None, ""), {"": 2, "alpha": 1, "zeta": 2}),
    ],
)
def test_reason_histogram_counts_multiple_none_and_empty_recorded_reasons(reasons, expected):
    rows = tuple(_outcome(f"t{n}", close_sequence=n, close_reason=reason) for n, reason in enumerate(reasons))
    observations = LedgerObservations(records=tuple(reversed(rows)), matching="position_episode",
                                      coverage=_coverage(retained_rows=len(rows)), valuation_time_ns=50)
    before = asdict(observations)
    report = reduce_ledger(observations, _ledger_contract("closed_trade"), backend="python", retain_population=True)
    metadata = json.loads(report.provenance_json)
    assert metadata["population_reason_counts"] == expected
    assert list(metadata["population_reason_counts"]) == list(expected)
    assert metadata["closed_population_ids"] == [[row.trade_id] for row in rows]
    assert report.metric("closed_trade.closed_count").value == len(rows)
    assert asdict(observations) == before


def _mixed_ledger():
    rows = (
        _outcome("a-tp", action_id="A", closed_at_ns=30, close_sequence=1, close_reason="take_profit",
                 net_pnl=12., allocated_fee=1., allocated_funding_cost=-2., allocated_slippage_cost=.5),
        _outcome("old", action_id="old", closed_at_ns=9, close_sequence=6, close_reason="old_reason",
                 net_pnl=100., allocated_fee=50., allocated_funding_cost=50., allocated_slippage_cost=50.),
        _outcome("b-tp", action_id="B", side="short", close_sequence=4, close_reason="take_profit",
                 net_pnl=7., allocated_fee=3., allocated_funding_cost=0., allocated_slippage_cost=.75),
        _outcome("c-open", action_id="C", symbol="SOL", side="short", closed_at_ns=None,
                 close_reason="not_a_closed_reason", net_pnl=1., open_unrealized_pnl=2.),
        _outcome("a-stop", action_id="A", symbol="BTC", side="short", closed_at_ns=40, close_sequence=2,
                 close_reason="stop", net_pnl=-5., allocated_fee=2., allocated_funding_cost=1., allocated_slippage_cost=.25),
        _outcome("b-none", action_id="B", symbol="SOL", close_sequence=3,
                 net_pnl=-2., allocated_fee=4., allocated_funding_cost=3.),
        _outcome("c-closed", action_id="C", closed_at_ns=15, close_sequence=5, close_reason="roll_close",
                 net_pnl=-4., allocated_fee=5., allocated_funding_cost=-1., allocated_slippage_cost=1.),
    )
    rosters = tuple(ActionRoster(action_id=name, outcome_ids=ids, shared_net_adjustment=cost,
                                allocation_witness="recorded shared allocation") for name, ids, cost in (
        ("A", ("a-stop", "a-tp"), -1.5), ("B", ("b-none", "b-tp"), -.5),
        ("C", ("c-open", "c-closed"), -2.), ("old", ("old",), -4.),
    ))
    return LedgerObservations(records=rows, matching="position_episode", rosters=rosters,
                              coverage=_coverage(retained_rows=len(rows)), valuation_time_ns=50)


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_reason_histogram_preserves_selected_population_order_costs_and_shared_adjustments(unit):
    observations = _mixed_ledger()
    before, identity = asdict(observations), observations.identity
    contract = _ledger_contract(unit)
    detailed = reduce_ledger(observations, contract, backend="python", retain_population=True)
    compact = reduce_ledger(observations, contract, backend="python", retain_population=False)
    metadata = json.loads(detailed.provenance_json)
    expected = ({"reasons": {"roll_close": 1, "stop": 1, "take_profit": 2},
                 "ids": [["c-closed"], ["b-none"], ["b-tp"], ["a-tp"], ["a-stop"]],
                 "net": 8., "legs": 8., "shared": 0., "fee": 15., "funding": 1., "slippage": 2.5,
                 "symbols": {"BTC": -5., "ETH": 15., "SOL": -2.}, "open_realized": 1.}
                if unit == "closed_trade" else
                {"reasons": {"stop": 1, "take_profit": 2},
                 "ids": [["b-none", "b-tp"], ["a-stop", "a-tp"]],
                 "net": 10., "legs": 12., "shared": -2., "fee": 10., "funding": 2., "slippage": 1.5,
                 "symbols": {"BTC": -5., "ETH": 19., "SOL": -2.}, "open_realized": -5.})
    assert metadata["population_reason_counts"] == expected["reasons"]
    assert list(metadata["population_reason_counts"]) == list(expected["reasons"])
    assert metadata["closed_population_ids"] == expected["ids"]
    assert metadata["symbol_closed_pnl"] == expected["symbols"]
    assert metadata["leg_net_sum"] == expected["legs"]
    assert metadata["shared_net_adjustment"] == expected["shared"]
    assert metadata["population_net_sum"] == expected["legs"] + expected["shared"] == expected["net"]
    for name, value in (("closed_count", len(expected["ids"])), ("net_pnl", expected["net"]),
                        ("allocated_fee", expected["fee"]), ("allocated_funding_cost", expected["funding"]),
                        ("allocated_slippage_cost", expected["slippage"]),
                        ("open_realized_net_pnl", expected["open_realized"]), ("open_unrealized_pnl", 2.)):
        assert detailed.metric(unit + "." + name).value == value
    assert detailed.contract_identity == _contract_digest(contract)
    assert detailed.metrics == compact.metrics
    compact_metadata = json.loads(compact.provenance_json)
    assert "closed_population_ids" not in compact_metadata
    metadata.pop("closed_population_ids")
    metadata["population_detail_retained"] = False
    assert metadata == compact_metadata
    assert detailed.to_metadata()["metrics"] == [asdict(metric) for metric in detailed.metrics]
    assert observations.identity == identity and asdict(observations) == before
