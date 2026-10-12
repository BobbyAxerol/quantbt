"""Source-bound continuous attribution over an already executed Mode 5 account.

The caller owns strategy invocation and the original financial scorer. This
module neither executes a financial callback nor resets an environment. V1
reset-flat bindings are unchanged; public binding-v2 admission is separate.
"""

from dataclasses import asdict, dataclass
import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..metrics.report_contracts import ReportingContractV1, ReportingCoverageV1
from ..metrics.reporting import AccountObservations, reduce_account
from ..metrics.reporting.drawdown import scan_drawdown
from ..metrics.reporting.inputs import frozen_array
from ..metrics.reporting.snapshots import SnapshotValue
from .diagnostics.access import AccessPolicy, AccessWitness
from .diagnostics.identity import digest
from .dossier.records import Record
from .evaluation import Mode5MetricPolicy, array_identity
from .geometry.schema import EffectiveGeometry, ResolvedPoint
from .selection.objectives import economic_utility
from .statistics.analysis import partition_pnl
from .statistics.contracts import MetricValue, StatisticsPolicy
from .statistics.moments import classical_psr, moments
from .statistics.tails import expected_shortfall

DAY_NS = 86_400_000_000_000
CONTINUOUS_POLICY = "CONTINUOUS_PATH_ATTRIBUTION"


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _index(index):
    if not isinstance(index, pd.DatetimeIndex) or index.hasnans or not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("complete ordered DatetimeIndex required")
    if index.tz is not None and str(index.tz) != "UTC":
        raise ValueError("UTC calendar required")
    return index.as_unit("ns").asi8


@dataclass(frozen=True)
class ContinuousAccountContract:
    start_ns: int
    stop_ns: int
    geometry: EffectiveGeometry
    metrics: Record
    metric_binding_identity: str
    source: Record
    execution: Record
    access: AccessPolicy
    witness: AccessWitness
    version: str = "quantbt.mode5.continuous_account.v1"
    account_policy: str = CONTINUOUS_POLICY

    def __post_init__(self):
        if self.version != "quantbt.mode5.continuous_account.v1" or self.account_policy != CONTINUOUS_POLICY:
            raise ValueError("explicit continuous account contract required; reset-flat is not equivalent")
        if (type(self.start_ns) is not int or type(self.stop_ns) is not int
                or self.start_ns >= self.stop_ns or self.start_ns % DAY_NS or self.stop_ns % DAY_NS):
            raise ValueError("nonempty complete UTC-day development scope required")
        if (not isinstance(self.geometry, EffectiveGeometry) or not isinstance(self.metrics, Record)
                or not isinstance(self.source, Record) or not isinstance(self.execution, Record)
                or not _sha(self.metric_binding_identity)):
            raise TypeError("frozen geometry, source, execution and metric binding required")
        if not isinstance(self.access, AccessPolicy) or not isinstance(self.witness, AccessWitness):
            raise TypeError("typed data rights required")
        self.access.require(self.witness)
        if (self.access.purpose == "independent_validation" or self.witness.start_ns > self.start_ns
                or self.witness.end_ns < self.stop_ns):
            raise PermissionError("development calibration cannot consume validation or an incomplete witness")
        p = self.metrics.data
        expected = {"bar_interval_ns", "currency", "annual_periods", "dd_weight", "tail_weight",
                    "tail_confidence", "min_daily_returns", "min_closed_records", "max_drawdown", "min_utility"}
        if set(p) != expected or not p["currency"]:
            raise ValueError("complete existing Mode5 metric policy required")
        if type(p["bar_interval_ns"]) is not int or p["bar_interval_ns"] <= 0 or DAY_NS % p["bar_interval_ns"]:
            raise ValueError("exact divisor-of-day bar interval required")
        for name in ("annual_periods", "dd_weight", "tail_weight", "tail_confidence", "max_drawdown", "min_utility"):
            if isinstance(p[name], bool) or not isinstance(p[name], (int, float)) or not math.isfinite(p[name]):
                raise ValueError("finite explicit metric preferences required")
        if (p["annual_periods"] <= 0 or min(p["dd_weight"], p["tail_weight"], p["max_drawdown"]) < 0
                or not 0 <= p["tail_confidence"] < 1
                or any(type(p[n]) is not int or p[n] < 0 for n in ("min_daily_returns", "min_closed_records"))):
            raise ValueError("invalid metric/support contract")
        sources = self.source.data
        if not {"alpha", "financial_provider"} <= sources.keys() or any(not _sha(v) for v in sources.values()):
            raise ValueError("externally registered original source digests required")
        e = self.execution.data
        if (set(e) != {"route", "backend", "clock", "initial_state", "terminal_policy", "economics"}
                or not e["route"] or not e["backend"] or e["backend"] == "auto"
                or not e["clock"].get("id") or e["clock"].get("equity_clock") != "bar_close"
                or not e["terminal_policy"].get("id") or not e["economics"]):
            raise ValueError("actual backend/clock/economics/initial/terminal witnesses required")
        capital = e["initial_state"].get("equity")
        if isinstance(capital, bool) or not isinstance(capital, (int, float)) or not math.isfinite(capital) or capital <= 0:
            raise ValueError("actual positive scope-entry equity required")

    @property
    def identity(self):
        return digest(dict(version=self.version, account_policy=self.account_policy,
            start_ns=self.start_ns, stop_ns=self.stop_ns, geometry=self.geometry.identity,
            metrics=self.metrics.identity, metric_binding=self.metric_binding_identity,
            source=self.source.identity, execution=self.execution.identity,
            access=self.access.identity, witness=self.witness.identity))

    def to_metadata(self):
        return dict(version=self.version, identity=self.identity, account_policy=self.account_policy,
            start_ns=self.start_ns, stop_ns=self.stop_ns, geometry=self.geometry.metadata(),
            metrics=self.metrics.data, metric_binding_identity=self.metric_binding_identity,
            source=self.source.data, execution=self.execution.data,
            access=asdict(self.access), witness=asdict(self.witness))

    def request(self, data, params, *, role="formal_search", scenario_seed=None):
        """Seal only a supplied permitted prefix, including original preload."""
        from ..walkforward import _complete_data_hash
        if not isinstance(data, pd.DataFrame) or not len(data):
            raise TypeError("actual nonempty market prefix required")
        times = _index(data.index)
        step = self.metrics.data["bar_interval_ns"]
        if (times[0] > self.start_ns or times[0] < self.witness.start_ns
                or times[-1] != self.stop_ns - step or np.any(np.diff(times) != step)
                or (self.start_ns - int(times[0])) % step):
            raise PermissionError("market must be the exact allowed prefix; no future suffix or missing preload clock")
        if role not in {"formal_search", "selection_probe", "held_local_validation"}:
            raise ValueError("explicit registered query role required")
        if ((role == "held_local_validation") != (self.access.purpose == "diagnostic")):
            raise PermissionError("held probes cannot enter selection and selection cannot borrow held-probe rights")
        if scenario_seed is not None and type(scenario_seed) is not int:
            raise ValueError("exact scenario seed or explicit none required")
        point = self.geometry.resolve(params)
        # Existing WFO content hash plus explicit attrs: quantity constraints in
        # attrs are execution inputs too. Nonportable attrs fail closed.
        data_id = digest((_complete_data_hash(data), Record.of(dict(data.attrs)).identity))
        return ContinuousObservationRequest(self.identity, point, data_id, self.source.identity,
            int(times[0]), role, scenario_seed)


@dataclass(frozen=True)
class ContinuousObservationRequest:
    contract_identity: str
    point: ResolvedPoint
    data_identity: str
    source_identity: str
    warmup_start_ns: int
    role: str
    scenario_seed: int | None

    def __post_init__(self):
        if (not all(_sha(x) for x in (self.contract_identity, self.data_identity, self.source_identity))
                or not isinstance(self.point, ResolvedPoint) or type(self.warmup_start_ns) is not int
                or self.role not in {"formal_search", "selection_probe", "held_local_validation"}
                or self.scenario_seed is not None and type(self.scenario_seed) is not int):
            raise ValueError("complete immutable continuous request required")

    @property
    def identity(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class ContinuousExecutionWitness:
    """Original scorer invocation, not its internal native feedback passes.

    The sealed binding/current scorer supplies source, economics and clock;
    this class must not be populated from unchecked strategy/user defaults.
    Optional internal counts are retained from the actual producer separately.
    """
    request_identity: str
    source_identity: str
    data_identity: str
    effective_params_identity: str
    execution_id: str
    backend: str
    clock: Record
    initial_state: Record
    terminal_state: Record
    account_policy: str = CONTINUOUS_POLICY
    financial_execution_count: int = 1
    internal_execution_counts: Record | None = None

    def __post_init__(self):
        if (not all(_sha(x) for x in (self.request_identity, self.source_identity, self.data_identity, self.effective_params_identity))
                or not self.execution_id or not self.backend or self.backend == "auto"
                or any(not isinstance(r, Record) for r in (self.clock, self.initial_state, self.terminal_state))
                or self.account_policy != CONTINUOUS_POLICY
                or type(self.financial_execution_count) is not int or self.financial_execution_count != 1):
            raise ValueError("one actual continuous financial account and complete executed witnesses required")
        if self.internal_execution_counts is not None:
            if (not isinstance(self.internal_execution_counts, Record) or not self.internal_execution_counts.data
                    or any(type(v) is not int or v < 0 for v in self.internal_execution_counts.data.values())):
                raise ValueError("explicit actual internal execution counts or unavailable required")


@dataclass(frozen=True)
class ContinuousStream(SnapshotValue):
    name: str
    values: np.ndarray

    def __post_init__(self):
        if self.name not in {"positions", "fees", "funding", "margin", "turnover"}:
            raise ValueError("unknown actual financial stream")
        object.__setattr__(self, "values", frozen_array(self.values, np.float64))


@dataclass(frozen=True)
class ContinuousAccountEvaluation(SnapshotValue):
    request: ContinuousObservationRequest
    execution: ContinuousExecutionWitness
    observations: AccountObservations
    streams: tuple[ContinuousStream, ...]
    whole: Record
    annual_views: tuple[Record, ...]

    def __post_init__(self):
        if (not isinstance(self.request, ContinuousObservationRequest)
                or not isinstance(self.execution, ContinuousExecutionWitness)
                or not isinstance(self.observations, AccountObservations) or not isinstance(self.whole, Record)
                or type(self.streams) is not tuple or type(self.annual_views) is not tuple
                or any(not isinstance(r, Record) for r in self.annual_views)
                or any(not isinstance(s, ContinuousStream) or s.values.shape != self.observations.equity.shape for s in self.streams)
                or len({s.name for s in self.streams}) != len(self.streams)
                or self.execution.request_identity != self.request.identity):
            raise ValueError("complete detached continuous evaluation required")

    @property
    def raw_whole_sharpe(self):
        return self.whole.data["raw_sharpe"]

    @property
    def identity(self):
        return digest((self.request.identity, asdict(self.execution), self.observations.identity,
            [(s.name, array_identity(s.values)) for s in self.streams], self.whole.identity,
            [v.identity for v in self.annual_views]))

    def to_metadata(self):
        return dict(schema="quantbt.mode5.continuous_evaluation.v1", identity=self.identity,
            request_identity=self.request.identity, execution=asdict(self.execution),
            whole=self.whole.data, annual_views=[v.data for v in self.annual_views],
            raw_whole_sharpe=self.raw_whole_sharpe,
            raw_whole_sharpe_source="original Mode5MetricPolicy on one full allowed development account",
            financial_execution_count=self.execution.financial_execution_count,
            execution_count_unit="original_scorer_invocations_not_internal_native_feedback_or_owner_passes",
            internal_execution_counts=None if self.execution.internal_execution_counts is None else self.execution.internal_execution_counts.data,
            internal_execution_counts_status="UNAVAILABLE" if self.execution.internal_execution_counts is None else "RECORDED",
            annual_account_resets=0, validation_claim="none_full_sample_calibration",
            public_v1_reset_behavior_changed=False)


def _times(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is not None and str(stamp.tzinfo) != "UTC":
        raise ValueError("exact UTC ledger timestamp required")
    return int(stamp.value)


def _support(campaigns, fills, start, stop):
    closed = opened = fill_count = None
    if campaigns is not None:
        rows = campaigns.data
        closed = sum(start <= _times(r["end"]) < stop for r in rows["closed"])
        opened = sum(_times(r["start"]) < stop <= _times(r["end"]) for r in rows["closed"])
        opened += sum(_times(r["start"]) < stop for r in rows["open"])
    if fills is not None:
        fill_count = sum(start <= _times(r["timestamp"]) < stop for r in fills.data["rows"])
    return dict(closed_campaigns=closed, open_campaigns=opened, fills=fill_count,
        campaign_support_status="UNAVAILABLE" if campaigns is None else "RECORDED",
        fill_support_status="UNAVAILABLE" if fills is None else "RECORDED")


class ContinuousAccountReducer:
    """Cold reducer for an actual scorer result, never a financial registry.

    Source/request witnesses are supplied by the existing qualified scorer;
    self-asserted source hashes are not an execution qualification. Mutable
    account/strategy state is not retained or cached here.
    """

    def __init__(self, contract, metric_policy):
        if not isinstance(contract, ContinuousAccountContract) or not isinstance(metric_policy, Mode5MetricPolicy):
            raise TypeError("continuous contract and original Mode5MetricPolicy required")
        self.contract, self.metric_policy = contract, metric_policy
        self._require_policy()

    def _require_policy(self):
        p, c = self.metric_policy, self.contract
        if (Record.of(p.policy) != c.metrics or p.calibration.binding.identity != c.metric_binding_identity
                or Record.of(p.calibration.binding.data["metrics"]) != c.metrics):
            raise ValueError("original metric policy/binding changed")

    def observe(self, result, datetime_index, *, request, execution_witness,
                whole_observation=None, campaign_ledger=None, fill_ledger=None, backend="python"):
        c, p, e = self.contract, self.contract.metrics.data, self.contract.execution.data
        self._require_policy()
        if not isinstance(request, ContinuousObservationRequest) or not isinstance(execution_witness, ContinuousExecutionWitness):
            raise TypeError("typed requested and actually executed identities required")
        w = execution_witness
        if (request.contract_identity != c.identity or request.source_identity != c.source.identity
                or request.point != c.geometry.resolve(json.loads(request.point.requested_json))
                or request.warmup_start_ns < c.witness.start_ns or request.warmup_start_ns > c.start_ns
                or (request.role == "held_local_validation") != (c.access.purpose == "diagnostic")
                or w.request_identity != request.identity or w.source_identity != request.source_identity
                or w.data_identity != request.data_identity or w.effective_params_identity != request.point.identity
                or w.backend != e["backend"] or w.clock != Record.of(e["clock"])
                or w.initial_state != Record.of(e["initial_state"])):
            raise ValueError("candidate/source/data/cutoff/backend/clock/initial request mismatch")
        c.access.require(c.witness)
        times = _index(datetime_index)
        step = p["bar_interval_ns"]
        if not np.array_equal(times, np.arange(c.start_ns, c.stop_ns, step, dtype=np.int64)):
            raise ValueError("original complete scored account clock required; no missing or future marks")
        if not hasattr(result, "initial_capital") or float(result.initial_capital) != e["initial_state"]["equity"]:
            raise ValueError("original initial capital mismatch")
        accounting = getattr(result, "accounting", None)
        equity = (pd.Series(accounting.equity, index=accounting.datetime_index)
                  if accounting is not None else getattr(result, "equity", None))
        if not isinstance(equity, pd.Series) or not equity.index.equals(datetime_index):
            raise ValueError("original full executed account path required; arbitrary scalar scores are unsupported")
        metadata = getattr(result, "metadata", None)
        if not isinstance(metadata, dict):
            raise TypeError("actual result metadata required")
        if metadata.get("backend") is not None and metadata["backend"] != w.backend:
            raise ValueError("actual result backend differs from execution witness")
        actual_clock = metadata.get("execution_contract")
        if actual_clock is not None and digest(actual_clock) != digest(e["clock"].get("execution_contract", e["clock"]["id"])):
            raise ValueError("actual result clock differs from execution witness")
        if metadata.get("account_policy") in {"reset_flat", "independent_reset_flat_v1", "CONTIGUOUS_RESET_EPISODES"}:
            raise ValueError("reset account result cannot supply continuous attribution")
        if w.internal_execution_counts is not None:
            for name, count in w.internal_execution_counts.data.items():
                if name in metadata and metadata[name] != count:
                    raise ValueError("internal execution count differs from actual producer")
        coverage = ReportingCoverageV1(result_identity=w.execution_id, producer="original continuous Mode5 scorer",
            profile="compact", ledger="unsupported", retained_rows=0, dropped_rows=0,
            reason="account snapshots do not infer closed actions or campaigns")
        obs = AccountObservations(times_ns=times, equity=equity.to_numpy(dtype=float), coverage=coverage)
        terminal = w.terminal_state.data
        liquidated = bool(getattr(result, "liquidated", False))
        if (terminal.get("equity") != float(obs.equity[-1]) or terminal.get("liquidated") is not liquidated
                or terminal.get("terminal_policy") != e["terminal_policy"]):
            raise ValueError("actual terminal equity/liquidation/policy witness mismatch")
        if liquidated and (type(terminal.get("liquidated_at_ns")) is not int
                          or not c.start_ns <= terminal["liquidated_at_ns"] < c.stop_ns):
            raise ValueError("liquidation requires its actual event time; no future liquidation propagated backward")
        streams, finance = [], {"equity": array_identity(obs.equity)}
        for name in ("positions", "fees", "funding", "margin", "turnover"):
            value = getattr(result, name, None)
            if value is None:
                continue
            if isinstance(value, (pd.Series, pd.DataFrame)) and not value.index.equals(datetime_index):
                raise ValueError("financial stream calendar differs from executed account")
            array = np.asarray(value, dtype=float)
            finance[name] = array_identity(array)
            if array.ndim == 2 and array.shape[1] == 1:
                array = array[:, 0]
            stream = ContinuousStream(name, array)
            if stream.values.shape != times.shape:
                raise ValueError("financial stream not aligned with actual marks")
            streams.append(stream)
        self._require_ledgers(campaign_ledger, fill_ledger, obs)
        whole = (self.metric_policy.observe(result, datetime_index) if whole_observation is None
                 else whole_observation.data if isinstance(whole_observation, Record) else dict(whole_observation))
        self._verify_whole(whole, result, obs, finance)
        whole = dict(whole, **_support(campaign_ledger, fill_ledger, c.start_ns, c.stop_ns),
            account_policy=CONTINUOUS_POLICY, environment_id="whole_path", start_ns=c.start_ns, stop_ns=c.stop_ns)
        annual = []
        years = sorted(set(datetime_index.year))
        for year in years:
            start = max(c.start_ns, int(pd.Timestamp(f"{year}-01-01", tz="UTC").value))
            stop = min(c.stop_ns, int(pd.Timestamp(f"{year+1}-01-01", tz="UTC").value))
            lo, hi = (start-c.start_ns)//step, (stop-c.start_ns)//step
            previous = float(result.initial_capital) if lo == 0 else float(obs.equity[lo-1])
            watermark = max(float(result.initial_capital), float(obs.equity[:lo].max())) if lo else previous
            row = self._annual(result, datetime_index[lo:hi], obs, lo, hi, previous)
            carried = self._report_contract(start, stop, watermark)
            scoped = AccountObservations(times_ns=times[lo:hi], equity=obs.equity[lo:hi], coverage=coverage)
            row.update(schema="quantbt.mode5.continuous_view.v1", environment_id=str(year), start_ns=start, stop_ns=stop,
                account_policy=CONTINUOUS_POLICY, independent_information_count=None,
                baseline_equity=previous, baseline_time_ns=start-step,
                baseline_source="original_initial_capital" if lo == 0 else "prior_actual_close",
                carried_watermark_equity=watermark,
                carried_watermark_drawdown=float(scan_drawdown(scoped, carried, backend=backend)[0][0]),
                money_pnl=float(obs.equity[hi-1])-previous,
                **_support(campaign_ledger, fill_ledger, start, stop))
            row["liquidated"] = liquidated and terminal["liquidated_at_ns"] < stop
            row["stream_sums"] = {s.name: float(s.values[lo:hi].sum()) for s in streams if s.name in {"fees", "funding", "turnover"}}
            annual.append(Record.of(row))
        # Monetary attribution has one authority and the same original marks.
        partitions = partition_pnl(obs.equity, initial_equity=float(result.initial_capital),
            block_ends=tuple((r.data["stop_ns"]-c.start_ns)//step-1 for r in annual))
        for row, part in zip(annual, partitions, strict=True):
            if row.data["money_pnl"] != part["money_pnl"]:
                raise ValueError("annual monetary attribution mismatch")
        self._require_policy()
        return ContinuousAccountEvaluation(request, w, obs, tuple(streams), Record.of(whole), tuple(annual))

    def _report_contract(self, start, stop, baseline):
        p = self.contract.metrics.data
        return ReportingContractV1(scope="full" if start == self.contract.start_ns and stop == self.contract.stop_ns else "scoped",
            unit="account_period", currency=p["currency"], baseline_equity=baseline,
            baseline_time_ns=start-p["bar_interval_ns"], scope_end_ns=stop-p["bar_interval_ns"],
            sampling="observed_daily_utc", annual_periods=p["annual_periods"], equity_clock="bar_close")

    def _verify_whole(self, row, result, obs, finance):
        p, c = self.contract.metrics.data, self.contract
        expected_finance = {k: v for k, v in finance.items() if k != "turnover"}
        contract = self._report_contract(c.start_ns, c.stop_ns, float(result.initial_capital))
        if (row.get("schema") != "quantbt.mode5.observation.v1" or row.get("finance") != expected_finance
                or row.get("account_identity") != finance["equity"] or row.get("metric_contract") != contract.identity
                or row.get("initial_capital") != result.initial_capital or row.get("final_equity") != float(obs.equity[-1])):
            raise ValueError("whole observation is not bound to this actual account/metric contract")
        bankrupt = bool(np.any(obs.equity <= 0))
        closed = sum(getattr(t, "closed_at", None) is not None for t in getattr(result, "trades", ()))
        if (row.get("closed_records") != closed
                or row.get("closed_record_unit") != "engine_closed_records_not_closed_actions_or_inferred_campaigns"
                or row.get("liquidated") is not bool(getattr(result, "liquidated", False))):
            raise ValueError("actual record population/liquidation witness differs")
        if bankrupt:
            if (row.get("raw_sharpe") is not None or row.get("utility", {}).get("value") is not None
                    or row.get("utility", {}).get("status") != "BANKRUPT"
                    or row.get("risk_pass") is not False or row.get("quality_pass") is not False
                    or row.get("daily_count") != 0 or row.get("daily_returns") != []):
                raise ValueError("bankrupt account cannot carry a valid scientific return score")
            return
        days = (c.stop_ns-c.start_ns)//DAY_NS
        observed = obs.with_derived_returns(contract, partial_mask=np.zeros(days, dtype=bool), witness="complete original UTC-day account")
        values = observed.returns.values
        if (row.get("daily_count") != days or row.get("partial_days") != 0
                or np.asarray(row.get("daily_returns", ())).shape != values.shape
                or not np.allclose(row["daily_returns"], values, rtol=0, atol=1e-12)):
            raise ValueError("whole daily return witness differs from original marks")
        stats = moments(values, policy=StatisticsPolicy(annual_periods=p["annual_periods"]), backend="python")
        sharpe = stats.sharpe_period*math.sqrt(p["annual_periods"]) if stats.status == "VALID" else None
        if row.get("raw_sharpe") != sharpe and (row.get("raw_sharpe") is None or sharpe is None
                or not math.isclose(row["raw_sharpe"], sharpe, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("whole raw Sharpe is not the original account-return ratio")
        # No financial replay: verify reused public observations through the
        # same numeric authorities. Fees are already inside these net marks.
        es = expected_shortfall(-values, p["tail_confidence"])
        raw = reduce_account(observed, contract, backend="python")
        dd, ret = raw.metric("drawdown.max_depth").value, raw.metric("account.total_return").value
        metric = lambda name, v: MetricValue("mode5.public."+name, "decimal_return", days, v)
        utility = (economic_utility(metric("net_return", ret), metric("drawdown", dd), metric("es", es.value),
            dd_weight=p["dd_weight"], tail_weight=p["tail_weight"], preference_id=c.metric_binding_identity)
            if es.value is not None else MetricValue("mode5.utility.net_v1", "decimal_return", days,
                status="UNDEFINED", reason="undefined return or tail"))
        for key, value in (("net_return", ret), ("max_drawdown", dd), ("daily_loss_es", es.value)):
            if row.get(key) != value and (row.get(key) is None or value is None
                    or not math.isclose(row[key], value, rel_tol=0, abs_tol=1e-12)):
                raise ValueError("whole scientific metric differs from original shared authority")
        if (Record.of(row.get("utility", {})) != Record.of(utility.to_metadata())
                or Record.of(row.get("psr", {})) != Record.of(classical_psr(stats).to_metadata())):
            raise ValueError("whole scientific components differ from original shared authority")
        gates = dict(support_pass=days >= p["min_daily_returns"] and closed >= p["min_closed_records"],
            risk_pass=dd is not None and dd <= p["max_drawdown"],
            quality_pass=utility.value is not None and utility.value >= p["min_utility"])
        if any(row.get(name) is not value for name, value in gates.items()):
            raise ValueError("whole support/risk/quality gates differ from original metric policy")

    def _annual(self, result, index, obs, lo, hi, previous):
        if previous <= 0:
            missing = MetricValue("mode5.utility.net_v1", "decimal_return", 0,
                status="BANKRUPT", reason="nonpositive carried scope-entry mark").to_metadata()
            psr = classical_psr(moments([], backend="python")).to_metadata()
            return dict(raw_sharpe=None, utility=missing, psr=psr,
                schema="quantbt.mode5.observation.v1", account_identity=array_identity(obs.equity[lo:hi]),
                metric_contract=None, metric_contract_status="UNAVAILABLE_NONPOSITIVE_SCOPE_ENTRY",
                finance=dict(equity=array_identity(obs.equity[lo:hi])),
                initial_capital=previous, final_equity=float(obs.equity[hi-1]),
                net_return=None, max_drawdown=None, daily_loss_es=None, daily_returns=[], daily_count=missing["sample_count"],
                support_pass=False, risk_pass=False, quality_pass=False, null_reason=missing["reason"])
        trades = tuple(t for t in getattr(result, "trades", ()) if getattr(t, "closed_at", None) is not None
                       and int(index[0].value) <= _times(t.closed_at) <= int(index[-1].value))
        view = SimpleNamespace(equity=pd.Series(obs.equity[lo:hi], index=index), initial_capital=previous,
            trades=trades, metadata=result.metadata, liquidated=False)
        for name in ("positions", "fees", "funding", "margin"):
            value = getattr(result, name, None)
            if value is not None:
                setattr(view, name, value.iloc[lo:hi] if hasattr(value, "iloc") else np.asarray(value)[lo:hi])
        # This is only a cold observation view. The original policy owns the
        # formulas, including null, support and risk conventions; no engine runs.
        return Mode5MetricPolicy(self.metric_policy.calibration).observe(view, index)

    def _require_ledgers(self, campaigns, fills, obs):
        c = self.contract
        if campaigns is not None:
            if not isinstance(campaigns, Record) or set(campaigns.data) != {"closed", "open"}:
                raise TypeError("explicit actual closed/open campaign ledger required")
            rows = campaigns.data
            for row in rows["closed"] + rows["open"]:
                end = _times(row["end"]) if "end" in row else c.stop_ns-self.contract.metrics.data["bar_interval_ns"]
                if not c.start_ns <= _times(row["start"]) <= end < c.stop_ns:
                    raise ValueError("campaign outside the executed account calendar")
            pnl = sum(r["net_pnl"] for r in rows["closed"]) + sum(r["marked_net_pnl"] for r in rows["open"])
            if not math.isclose(pnl, float(obs.equity[-1])-self.contract.execution.data["initial_state"]["equity"], rel_tol=0, abs_tol=1e-8):
                raise ValueError("actual campaign PnL does not reconcile to account")
        if fills is not None:
            if not isinstance(fills, Record) or set(fills.data) != {"rows"}:
                raise TypeError("explicit accepted-fill ledger required")
            times = [_times(r["timestamp"]) for r in fills.data["rows"]]
            if any(t < c.start_ns or t >= c.stop_ns for t in times) or any(a > b for a, b in zip(times, times[1:])):
                raise ValueError("accepted fills outside chronological executed account")
