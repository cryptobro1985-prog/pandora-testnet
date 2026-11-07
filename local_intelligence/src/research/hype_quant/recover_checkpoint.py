#!/usr/bin/env python3
from __future__ import annotations
import argparse, copy, json, pickle, time
from pathlib import Path

from research.hype_quant.learner import OnlineQuantLearner, Outcome, clean_features, load_config

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--config",type=Path,default=Path("research/hype_quant/config.json"))
    args=ap.parse_args()

    with args.source.open("rb") as f:
        old=pickle.load(f)
    cfg=load_config(args.config)
    new=OnlineQuantLearner(cfg)

    recovered={}
    total=0
    feature_names=set()
    for h in new.horizons:
        rows=list(getattr(getattr(old,"memory",None),"rows",{}).get(h,[]))
        recovered[str(h)]=len(rows)
        for x,r,u,d in rows:
            x=clean_features(dict(x))
            y=Outcome(horizon_s=h,future_return=float(r),max_up=float(u),max_down=float(d),
                      close_price=0.0,elapsed_s=float(h))
            new.challenger[h].learn(x,y,new.cost_floor)
            new.memory.add(x,y)
            feature_names.update(x)
            total+=1

    if total<=0:
        raise SystemExit("no matured causal examples recovered")

    # Historical/matured data are warm-start only. Start a fresh forward scorecard.
    new.champion=copy.deepcopy(new.challenger)
    new.champion_ready=True
    new.promotions=0
    new.labels=total
    new.pending.clear()
    new.feature_names_seen=feature_names
    new.max_feature_count=max((len(x) for h in new.horizons for x,_,_,_ in list(new.memory.rows.get(h,[]))),default=0)
    new._reset_forward_stats()
    new.last_action=None
    new.created_ts_ms=int(time.time()*1000)

    args.output.mkdir(parents=True,exist_ok=True)
    new.save(args.output/"quant_learner.pkl")
    report={
      "recovery_version":"stable-regression-warmstart-v1",
      "source_checkpoint":str(args.source),
      "source_labels_reported":int(getattr(old,"labels",0)),
      "recovered_matured_rows":total,
      "recovered_by_horizon":recovered,
      "feature_names_recovered":len(feature_names),
      "forward_stats_reset":True,
      "pending_reset":True,
      "old_predictions_reused":False,
      "old_forward_metrics_reused":False,
      "research_only":True
    }
    (args.output/"RECOVERY_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")
    (args.output/"QUANT_REPORT.json").write_text(json.dumps(new.report(),indent=2)+"\n")
    (args.output/"quant_actions.jsonl").touch()
    (args.output/"quant_gaps.jsonl").touch()
    print(json.dumps(report,indent=2))

if __name__=="__main__":
    main()
