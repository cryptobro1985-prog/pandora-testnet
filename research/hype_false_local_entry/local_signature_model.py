from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Optional

from river import compose, linear_model, preprocessing

from research.hype_quant.feature_contract import INPUT_IDS


def _clean(features: dict[str, float]) -> dict[str, float]:
    out={}
    for k,v in features.items():
        if isinstance(v,(int,float)) and isfinite(float(v)):
            out[str(k)]=max(-1e12,min(1e12,float(v)))
    return out


def _classifier():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        linear_model.LogisticRegression(l2=0.001),
    )


@dataclass
class SignatureDecision:
    side: str
    ts_ms: int
    candidate_id: str
    extreme_price: float
    mark_price: float
    score: float
    threshold: float
    state: str
    enter: bool
    target_side: Optional[str]
    input_coverage: float
    seen_input_count: int
    quality_ok: bool
    decisive_evidence: dict[str, float] = field(default_factory=dict)


class LocalSignatureModel:
    """Event-driven terminal Local head.

    This head is deliberately NOT indexed by elapsed time.  It sees the current
    causal market state and answers one question:

        Has the market state transitioned far enough that the running extreme
        is now likely to be the terminal Local LOW/HIGH?

    The 116-point contract remains canonical.  Only INPUT_* points are legal
    predictors; TARGET_EVAL and METADATA are teacher/evaluation information and
    are never fed into the model.
    """

    VERSION="HYPE-LOCAL-SIGNATURE-v1-EVENT-DRIVEN"

    def __init__(self, low_threshold: float=0.985, high_threshold: float=0.985):
        self.models={"LOW":_classifier(),"HIGH":_classifier()}
        self.thresholds={"LOW":float(low_threshold),"HIGH":float(high_threshold)}
        self.labels={"LOW":0,"HIGH":0}
        self.positive={"LOW":0,"HIGH":0}
        self.live_labels={"LOW":0,"HIGH":0}
        self.last_decision={"LOW":None,"HIGH":None}
        self.history_bootstrap={}

    def learn(self, side: str, features: dict[str,float], y: bool, *, live: bool=True):
        side=str(side).upper()
        xx=_clean(features)
        if not xx:
            return
        self.models[side].learn_one(xx,bool(y))
        self.labels[side]+=1
        self.positive[side]+=int(bool(y))
        if live:
            self.live_labels[side]+=1

    def probability(self, side: str, features: dict[str,float]) -> float:
        side=str(side).upper()
        xx=_clean(features)
        if not xx:
            return 0.0
        p=self.models[side].predict_proba_one(xx)
        return float(p.get(True,0.0) or 0.0)

    def decide(
        self,
        *,
        side: str,
        ts_ms: int,
        candidate_id: str,
        extreme_price: float,
        mark_price: float,
        features: dict[str,float],
        seen_input_ids: set[int],
        quality_ok: bool,
        decisive_evidence: dict[str,float],
        invalidated: bool=False,
    ) -> SignatureDecision:
        side=str(side).upper()
        coverage=len(set(seen_input_ids)&set(INPUT_IDS))/max(1,len(INPUT_IDS))
        score=0.0 if invalidated else self.probability(side,features)
        threshold=self.thresholds[side]
        if invalidated:
            state="INVALIDATED"; enter=False
        elif not quality_ok:
            state="WATCH_QUALITY"; enter=False
        elif score>=threshold:
            state="LOCAL_CONFIRMED"; enter=True
        elif score>=max(0.50,threshold-0.10):
            state="LOCAL_FORMING"; enter=False
        else:
            state="CANDIDATE"; enter=False
        d=SignatureDecision(
            side=side,ts_ms=int(ts_ms),candidate_id=str(candidate_id),
            extreme_price=float(extreme_price),mark_price=float(mark_price),
            score=float(score),threshold=float(threshold),state=state,enter=enter,
            target_side=("LONG" if side=="LOW" else "SHORT") if enter else None,
            input_coverage=float(coverage),seen_input_count=len(set(seen_input_ids)&set(INPUT_IDS)),
            quality_ok=bool(quality_ok),decisive_evidence=dict(decisive_evidence),
        )
        self.last_decision[side]=d
        return d

    def report(self) -> dict[str,Any]:
        return {
            "version":self.VERSION,
            "thresholds":dict(self.thresholds),
            "labels":dict(self.labels),
            "positive":dict(self.positive),
            "live_labels":dict(self.live_labels),
            "input_contract_count":len(INPUT_IDS),
            "time_gated":False,
            "decision_contract":"CURRENT_CAUSAL_SIGNATURE_ONLY",
            "history_bootstrap":dict(getattr(self,"history_bootstrap",{}) or {}),
            "real_orders":False,
        }
