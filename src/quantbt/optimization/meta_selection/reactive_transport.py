"""Detached original-pass metrics, not a second execution/accounting authority."""

from dataclasses import dataclass
import math

import pandas as pd

from .common import MetaRecordError, digest, utc, wire
from .observer import ResultMetricAdapter
from .persistence import observation_from_payload
from .records import MetricObservation
from .witness import PreparedMetricWitness


SCORE_FIELDS = (
    "sharpe", "turnover", "trade_count", "mean_return", "volatility",
    "max_drawdown_pct", "profit_factor",
)


@dataclass(frozen=True, slots=True)
class ReactiveWitnessBindingV1:
    task_id: str
    params_id: str
    market_id: str
    calendar_id: str
    economics_id: str
    metric_id: str
    observer_seed: int | None
    schema: str = "quantbt-reactive-witness-binding-v1"

    @classmethod
    def prepare(cls, marker, *, index, witness, data, economics_id, metric_id,
                observer_seed=None):
        return cls(digest(marker.task), digest(marker.params),
                   witness.market_signature(data, index),
                   digest(witness.calendar_key(index)), economics_id, metric_id,
                   observer_seed)


@dataclass(frozen=True, slots=True)
class DetachedReactiveWitnessV1:
    binding: ReactiveWitnessBindingV1
    scores: tuple[float, ...]
    observation: MetricObservation
    seal: str
    schema: str = "quantbt-reactive-original-witness-v1"

    @staticmethod
    def _seal(binding, scores, observation):
        # Profit factor may be infinite. Preserve it, rather than substitute a
        # finite score for transport hashing or change objective semantics.
        return digest(dict(binding=wire(binding),
                           scores=[float(value).hex() for value in scores],
                           observation=wire(observation)))

    @classmethod
    def prepare(cls, binding, row, observation):
        if set(row) != set(SCORE_FIELDS):
            raise MetaRecordError("REACTIVE_WITNESS_INVALID: score fields")
        scores = tuple(float(row[name]) for name in SCORE_FIELDS)
        return cls(binding, scores, observation, cls._seal(binding, scores, observation))

    def validate(self, *, binding=None, index=None, initial_capital=None):
        if (self.schema != "quantbt-reactive-original-witness-v1"
                or self.binding.schema != "quantbt-reactive-witness-binding-v1"
                or len(self.scores) != len(SCORE_FIELDS)
                or any(not math.isfinite(value) for value in self.scores[:-1])
                or math.isnan(self.scores[-1])
                or self.seal != self._seal(self.binding, self.scores, self.observation)):
            raise MetaRecordError("REACTIVE_WITNESS_INVALID: schema/shape/seal")
        if binding is not None and self.binding != binding:
            raise MetaRecordError("REACTIVE_WITNESS_INVALID: request binding")
        obs = self.observation
        if (obs.verification != "original_result"
                or obs.economics_id != self.binding.economics_id
                or obs.metric_contract_id != self.binding.metric_id
                or obs.input_signature != self.binding.market_id):
            raise MetaRecordError("REACTIVE_WITNESS_INVALID: original metric provenance")
        if index is not None:
            index = pd.DatetimeIndex(index)
            if (not len(index) or obs.window_start != utc(index[0])
                    or obs.window_end != utc(index[-1])
                    or self.binding.calendar_id != digest(PreparedMetricWitness.calendar_key(index))):
                raise MetaRecordError("REACTIVE_WITNESS_INVALID: calendar/window")
        if initial_capital is not None and obs.initial_capital != float(initial_capital):
            raise MetaRecordError("REACTIVE_WITNESS_INVALID: initial account")
        return self

    def row(self):
        self.validate()
        return {**dict(zip(SCORE_FIELDS, self.scores, strict=True)),
                "meta_observation": wire(self.observation)}

    def to_payload(self):
        self.validate()
        return dict(schema=self.schema, binding=wire(self.binding),
                    scores=[float(value).hex() for value in self.scores],
                    observation=wire(self.observation), seal=self.seal)

    @classmethod
    def from_payload(cls, payload):
        try:
            if set(payload) != {"schema", "binding", "scores", "observation", "seal"}:
                raise ValueError("packet fields")
            result = cls(ReactiveWitnessBindingV1(**payload["binding"]),
                         tuple(float.fromhex(value) for value in payload["scores"]),
                         observation_from_payload(payload["observation"]),
                         payload["seal"], payload["schema"])
            return result.validate()
        except (TypeError, ValueError, KeyError) as exc:
            raise MetaRecordError("REACTIVE_WITNESS_INVALID: detached wire") from exc


class ReactiveDetachedMetricAdapter(ResultMetricAdapter):
    """Accept only a verified witness from the existing original-result reducer."""

    def observe(self, result, *, expected_index, economics_id, input_signature, **kwargs):
        if not isinstance(result, DetachedReactiveWitnessV1):
            return super().observe(result, expected_index=expected_index,
                economics_id=economics_id, input_signature=input_signature, **kwargs)
        result.validate(index=expected_index)
        if (result.binding.economics_id != economics_id
                or result.binding.market_id != input_signature
                or result.binding.metric_id != self.contract.metric_id):
            raise MetaRecordError("REACTIVE_WITNESS_INVALID: observer contract")
        return result.observation
