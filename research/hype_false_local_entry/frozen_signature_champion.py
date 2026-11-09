from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

import numpy as np


@dataclass
class FrozenSignatureChampion:
    """Chronologically selected frozen LOW/HIGH signature challenger."""
    feature_names: dict[str,list[str]]
    pipelines: dict[str,Any]
    thresholds: dict[str,float]
    metadata: dict[str,Any]=field(default_factory=dict)
    version: str="HYPE-LOCAL-SIGNATURE-FROZEN-CHAMPION-v1"

    def probability(self, side: str, features: dict[str,float]) -> float:
        side=str(side).upper()
        names=self.feature_names[side]
        row=np.asarray([[
            float(features.get(name,np.nan))
            if isinstance(features.get(name), (int,float)) and isfinite(float(features.get(name)))
            else np.nan
            for name in names
        ]],dtype=float)
        p=self.pipelines[side].predict_proba(row)
        return float(p[0,1])

    def threshold(self, side: str) -> float:
        return float(self.thresholds[str(side).upper()])

    def report(self) -> dict[str,Any]:
        return {
            "version":self.version,
            "thresholds":dict(self.thresholds),
            "metadata":dict(self.metadata),
            "real_orders":False,
        }
