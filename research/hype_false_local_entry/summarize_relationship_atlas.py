#!/usr/bin/env python3
import json
from pathlib import Path

src=Path("research/hype_false_local_entry/results/HYPE_ALL_LOCAL_RELATIONSHIP_ATLAS.json")
dst=Path("research/hype_false_local_entry/results/HYPE_ALL_LOCAL_RELATIONSHIP_SUMMARY.json")
doc=json.loads(src.read_text())
out={
  "version":"HYPE-ALL-LOCAL-RELATIONSHIP-SUMMARY-v1",
  "teacher_locals":doc.get("teacher_locals"),
  "contract":doc.get("contract"),
  "by_side":{}
}
for side in ("LOW","HIGH"):
    rels=[]
    for r in doc["universal_top_relationships"][side][:30]:
        rels.append({
            "kind":r["kind"],
            "point_id":r["point_id"],
            "point_title":r["point_title"],
            "feature":r["feature"],
            "age_s":r.get("age_s"),
            "from_age_s":r.get("from_age_s"),
            "to_age_s":r.get("to_age_s"),
            "robust_score":r["robust_score"],
            "worst_auc_strength":r["worst_auc_strength"],
            "median_auc_strength":r["median_auc_strength"],
            "periods":{
                name:{
                    "auc":v["auc"],
                    "direction":v["direction"],
                    "true_median":v["true_median"],
                    "false_median":v["false_median"],
                    "median_gap_iqr":v["median_gap_iqr"],
                    "true_n":v["true_n"],
                    "false_n":v["false_n"],
                } for name,v in r["periods"].items()
            }
        })
    models=[m for m in doc["cross_period_multivariate"][side].values() if m]
    models.sort(key=lambda x:(x["worst_auc"],x["mean_auc"]),reverse=True)
    out["by_side"][side]={
        "top_relationships":rels,
        "best_cross_period_models":[{
            "age_s":m["age_s"],"mean_auc":m["mean_auc"],"worst_auc":m["worst_auc"],
            "mean_average_precision":m["mean_average_precision"],
            "feature_importance":m["feature_importance"][:12],
            "folds":m["folds"],
        } for m in models[:3]],
        "top_points":doc["point_summary"][side][:20]
    }
dst.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
print(json.dumps(out,separators=(",",":")))
