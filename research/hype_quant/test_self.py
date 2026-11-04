#!/usr/bin/env python3
from __future__ import annotations
import copy
import json
import tempfile
from pathlib import Path

from research.hype_quant.learner import OnlineQuantLearner, load_config


def main():
    cfg=load_config(Path("research/hype_quant/config.json"))
    cfg=copy.deepcopy(cfg)
    cfg["horizons_seconds"]=[1,2,3]
    cfg["champion"]["min_forward_labels_before_promotion"]=3
    cfg["pattern_memory"]["neighbors"]=3
    q=OnlineQuantLearner(cfg)
    base=100.0
    features={
        "spread_bps":1.0,
        "book_imbalance_5":0.3,
        "book_imbalance_25":0.2,
        "flow_imbalance_5s":0.4,
        "flow_imbalance_15s":0.35,
        "flow_imbalance_60s":0.2,
        "ret_5s":0.0005,
        "ret_15s":0.001,
        "vol_60s":0.0008,
        "depth_log_ratio_5":0.1,
        "depth_log_ratio_25":0.05
    }
    for i in range(12):
        ts=i*1000
        price=base*(1+0.0005*i)
        q.observe(ts,price,features)
    assert q.labels>0, q.report()
    assert q.challenger[1].n>0
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"q.pkl"
        q.save(p)
        q2=OnlineQuantLearner.load(p)
        assert q2.labels==q.labels
        assert q2.report()["research_only"] is True
    print("HYPE_QUANT_SELFTEST_OK")
    print(json.dumps(q.report(),indent=2))


if __name__=="__main__":
    main()
