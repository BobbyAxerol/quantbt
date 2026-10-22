"""Frozen train risk calibration and paired fixed-path transfer uncertainty."""
from dataclasses import asdict, dataclass
import math

import numpy as np

from tools.mode5_diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_diagnostics.identity import digest
from tools.mode5_statistics.contracts import vector
from tools.mode5_statistics.moments import moments
from tools.mode5_statistics.uncertainty import BlockPolicy


@dataclass(frozen=True)
class RiskCalibration:
    train_execution_id: str
    witness: AccessWitness
    train_volatility: float
    target_volatility: float
    scale_cap: float
    scale: float
    version: str = "train_volatility_actual_resimulation_v1"

    def __post_init__(self):
        if (not self.train_execution_id or self.version!="train_volatility_actual_resimulation_v1"
                or not isinstance(self.witness,AccessWitness) or any(not math.isfinite(v) or v<=0 for v in
                    (self.train_volatility,self.target_volatility,self.scale_cap,self.scale))
                or self.scale!=min(self.scale_cap,self.target_volatility/self.train_volatility)):
            raise ValueError("positive frozen train calibration required")

    @classmethod
    def fit(cls,values,*,train_execution_id,witness,policy,target_volatility,scale_cap):
        if not isinstance(policy,AccessPolicy) or policy.purpose!="selection":
            raise ValueError("train-only calibration rights required")
        policy.require(witness)
        values=vector(values)
        if len(values)<32 or not np.isfinite(values).all() or np.any(values<=-1):
            raise ValueError("adequate finite train return path required")
        sigma=float(np.std(values,ddof=1))
        if not math.isfinite(sigma) or sigma<=0 or np.ptp(values)==0:
            raise ValueError("zero/nonfinite train volatility is not a favorable scale")
        return cls(train_execution_id,witness,sigma,target_volatility,scale_cap,min(scale_cap,target_volatility/sigma))

    @property
    def identity(self):
        return digest(asdict(self))

    def require_forward(self,witness):
        if witness.start_ns<self.witness.end_ns or witness.ready_ns<self.witness.ready_ns:
            raise PermissionError("forward execution must follow frozen train calibration")
        return dict(calibration_identity=self.identity,scale=self.scale,
                    required_method="ACTUAL_ACCOUNT_RESIMULATION",ex_post_path_scaling_allowed=False)


def _sharpe(values):
    observed=moments(values)
    return observed.sharpe_period if observed.status=="VALID" else None


def paired_transfer(is_control,is_treatment,forward_control,forward_treatment,*,policy=BlockPolicy()):
    paths=tuple(vector(x) for x in (is_control,is_treatment,forward_control,forward_treatment))
    if any(not np.isfinite(x).all() for x in paths) or any(np.any(x<=-1) for x in paths):
        raise ValueError("finite solvent actual daily account paths required")
    if len(paths[0])!=len(paths[1]) or len(paths[2])!=len(paths[3]):
        raise ValueError("paired candidate paths require common scored calendars")
    base=dict(version="paired_block_transfer_v1",policy=asdict(policy),
              interval_scope="FIXED_PATH_NOT_WHOLE_RECIPE_UNCERTAINTY",daily_sharpe_units="original_period_ratio",
              origins=1,independent_origins_claim=False,invalid_draws=0)
    observed=tuple(_sharpe(x) for x in paths)
    if min(map(len,paths))<max(32,2*policy.block_length) or any(x is None for x in observed):
        return base|dict(status="INSUFFICIENT",reason="short/zero-variance or undefined actual daily path",estimate=None,intervals=None)
    def contrast(sr):
        a,b,c,d=sr
        return (b-a,d-c,(b-d)-(a-c))
    point=contrast(observed)
    rng=np.random.default_rng(policy.seed)
    samples=[]
    invalid=0
    offsets=np.arange(policy.block_length)
    for _ in range(policy.draws):
        resampled=[]
        for start in (0,2):
            n=len(paths[start]); blocks=(n+policy.block_length-1)//policy.block_length
            ids=((rng.integers(0,n,size=blocks)[:,None]+offsets)%n).reshape(-1)[:n]
            resampled.extend(_sharpe(paths[start+i][ids]) for i in (0,1))
        if any(v is None for v in resampled):
            invalid+=1
        else:
            samples.append(contrast(resampled))
    names=("is_quality_change","forward_quality_change","decay_change")
    estimate=dict(zip(names,point))
    if invalid:
        return base|dict(status="UNAVAILABLE",reason="invalid draws retained; no survivor conditioning",estimate=estimate,
                         intervals=None,invalid_draws=invalid)
    q=np.quantile(samples,[(1-policy.confidence)/2,(1+policy.confidence)/2],axis=0,method="linear")
    return base|dict(status="VALID",reason=None,estimate=estimate,
        intervals={name:tuple(float(v) for v in q[:,i]) for i,name in enumerate(names)},
        interpretation="negative decay change alone is not improved forward quality")
