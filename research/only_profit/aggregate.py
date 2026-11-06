from __future__ import annotations
import argparse,json,math
from pathlib import Path

FAMILIES=("trend_follow","pullback","local_reversal","liq_squeeze","absorption","hybrid")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--round",type=int,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    fam={};all_top=[]
    for f in FAMILIES:
        matches=list(args.root.rglob(f+".json"))
        if not matches:continue
        d=json.loads(matches[0].read_text());fam[f]=d
        for z in d.get("top",[]):all_top.append((f,z))
    all_top.sort(key=lambda p:p[1].get("search_score",-999),reverse=True)
    sanity=[(f,z) for f,z in all_top if z.get("sanity_pass")]
    provisional=[(f,z) for f,z in sanity if z.get("provisional_50pct_daily")]
    zero_loss=[(f,z) for f,z in sanity if z.get("zero_loss_target")]
    best=all_top[0] if all_top else (None,None)
    best_sanity=sanity[0] if sanity else (None,None)
    state={"round":args.round,"families":{}}
    for f,d in fam.items():
        state["families"][f]={"seed_genes":d.get("seed_genes_next",[])}
    summary={
      "name":"Only Profit","round":args.round,"research_only":True,"real_orders":False,
      "families_completed":sorted(fam),
      "candidate_top_count":len(all_top),
      "sanity_pass_count":len(sanity),
      "provisional_50pct_daily_count":len(provisional),
      "zero_loss_target_count":len(zero_loss),
      "best_family":best[0],"best":best[1],
      "best_sanity_family":best_sanity[0],"best_sanity":best_sanity[1],
      "target_daily_return":0.50,
      "target_status":"PROVISIONAL_NEEDS_FRESH_FORWARD" if provisional else "NOT_MET",
      "stop_rule":"Do not stop search merely on historical/holdout success. Freeze candidate and require fresh live-forward evidence.",
      "risk_rule":"No candidate with simulated liquidation is eligible; max-DD and both long/short behavior remain promotion gates.",
      "next_action":"continue_search" if not provisional else "freeze_provisional_and_continue_shadow_forward"
    }
    (args.output/"ONLY_PROFIT_SUMMARY.json").write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+"\n")
    (args.output/"SEARCH_STATE.json").write_text(json.dumps(state,indent=2,sort_keys=True,allow_nan=False)+"\n")
    if provisional:
        f,z=provisional[0]
        (args.output/"PROVISIONAL_CHAMPION.json").write_text(json.dumps({"family":f,**z},indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("ONLY_PROFIT_AGG="+json.dumps({
      "round":args.round,"families":len(fam),"sanity":len(sanity),"provisional50":len(provisional),"zero_loss":len(zero_loss),
      "best_family":best[0],"best_score":None if best[1] is None else best[1].get("search_score"),
      "target_status":summary["target_status"]},separators=(",",":")))

if __name__=="__main__":
    main()
