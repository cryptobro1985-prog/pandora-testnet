"""Small CPU nonlinear/linear alternatives with explicit missing-value schemas."""
from __future__ import annotations

import math
from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def causal_inputs(features, temporal=True):
    prefixes=("m1__", "seq__") if temporal else ("m1__",)
    # Historical-only gap feeds are audited but excluded from the fitted model:
    # publication latency and live price-reference parity are not demonstrated.
    return {str(k):float(v) for k,v in features.items()
            if str(k).startswith(prefixes) and isinstance(v,(int,float))
            and not isinstance(v,bool) and math.isfinite(v)}


@dataclass
class FrozenResearchPredictor:
    name: str
    features: list[str]
    estimator: object
    temporal: bool = True
    calibration_a: float = 1.0
    calibration_b: float = 0.0
    calibration_events: int = 0

    def matrix(self, rows):
        inputs=[causal_inputs(r.get("features",r),self.temporal) for r in rows]
        return np.asarray([[x.get(k,np.nan) for k in self.features] for x in inputs],dtype=float)

    def raw_probabilities(self, rows):
        if not rows:
            return np.array([],dtype=float)
        return np.asarray(self.estimator.predict_proba(self.matrix(rows))[:,1],dtype=float)

    def probabilities(self, rows):
        raw=np.clip(self.raw_probabilities(rows),1e-6,1-1e-6)
        return np.clip(expit(self.calibration_a*np.log(raw/(1-raw))+self.calibration_b),1e-5,1-1e-5)

    def probability(self, features):
        return float(self.probabilities([features])[0])

    def calibrate(self, rows):
        """Monotone regularized Platt fit on disjoint chronological labels."""
        if len(rows)<20 or len({bool(r["strict_true"]) for r in rows})<2:
            return
        p=np.clip(self.raw_probabilities(rows),1e-6,1-1e-6)
        logit=np.log(p/(1-p));y=np.asarray([r["strict_true"] for r in rows],dtype=float)
        weights=event_weights(rows)
        def loss(ab):
            z=ab[0]*logit+ab[1]
            return float(np.average(np.logaddexp(0,z)-y*z,weights=weights)+.005*(ab[0]-1)**2+.001*ab[1]**2)
        result=minimize(loss,[1.,0.],method="L-BFGS-B",bounds=[(0.,5.),(-6.,6.)])
        if result.success:
            self.calibration_a,self.calibration_b=map(float,result.x)
            self.calibration_events=len({r["candidate_id"] for r in rows})


def event_weights(rows):
    counts={}
    for row in rows:
        counts[row["candidate_id"]]=counts.get(row["candidate_id"],0)+1
    weights=np.asarray([1/counts[r["candidate_id"]] for r in rows],dtype=float)
    return weights/max(weights.mean(),1e-12)


def fit_predictor(name, rows, calibration):
    temporal = name in ("temporal_hist_gradient_boosting", "temporal_linear")
    features=sorted({k for r in rows for k in causal_inputs(r["features"],temporal)})
    if not features or len({bool(r["strict_true"]) for r in rows})<2:
        raise ValueError("insufficient mature labels/features for model fit")
    if "hist_gradient_boosting" in name:
        estimator=HistGradientBoostingClassifier(max_iter=100,learning_rate=.05,max_leaf_nodes=7,
                    max_depth=3,min_samples_leaf=30,l2_regularization=10.,early_stopping=False,random_state=20261107)
    elif "linear" in name:
        estimator=make_pipeline(SimpleImputer(strategy="median",add_indicator=True,keep_empty_features=True),
                               StandardScaler(),LogisticRegression(C=.05,max_iter=700,solver="lbfgs",random_state=20261107))
    else:
        raise ValueError(name)
    predictor=FrozenResearchPredictor(name,features,estimator,temporal)
    x=predictor.matrix(rows);y=np.asarray([r["strict_true"] for r in rows],dtype=int)
    weights=event_weights(rows)
    if "hist_gradient_boosting" in name:
        estimator.fit(x,y,sample_weight=weights)
    else:
        estimator.fit(x,y,logisticregression__sample_weight=weights)
    predictor.calibrate(calibration)
    return predictor


@dataclass
class FrozenEnsemble:
    first: FrozenResearchPredictor
    second: FrozenResearchPredictor
    name: str = "linear_temporal_ensemble"

    def probabilities(self, rows):
        return .5*self.first.probabilities(rows)+.5*self.second.probabilities(rows)

    def probability(self, features):
        return float(self.probabilities([features])[0])


@dataclass
class RiverResearchPredictor:
    model: object
    name: str = "causal_river_logistic"

    def probabilities(self, rows):
        return np.asarray([self.model.probability(r["side"],int(r["delay_s"]),r["features"]) for r in rows])
