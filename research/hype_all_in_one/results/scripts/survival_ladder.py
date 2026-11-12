"""Earlier-checkpoint survival ladder (same family as the frozen V1 teacher: one-shot age checkpoint +
min retrace + min retrace fraction of causal pre-move-180). Zero-FP plateau selection on development
months only (all months before the test month), then frozen replay on the next month / forward."""
import pickle,json,itertools,collections
import numpy as np
from core import *
from train_walkforward import FOLDS,B,summarize
AGES={"T1800":30,"T3600":60,"T7200":120,"T10800":180}
RS=(40,50,60,70,80,100,130,160,200)
FS=(0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.2)
MONTHS=[("May","May","Jun"),("Jun","Jun","Jul"),("Jul","Jul","Aug"),("Aug","Aug","Sep"),("Sep","Sep","Oct"),("Oct","Oct","Nov4"),("Fwd","Nov4","END")]
def month_of(t):
    for n,a,b in MONTHS:
        if B[a]<=t<B[b]:return n
def run_rule(rows_by_ep,side,age_kind,R,Fr):
    res={}
    for e,rr in rows_by_ep.items():
        hits=[r for r in rr if r["kind"]==age_kind and r["features"]["px_retrace_bps"]>=R and
              r["features"].get("px_premove_180m_bps",0)>0 and r["features"]["px_retrace_bps"]/r["features"]["px_premove_180m_bps"]>=Fr]
        res[e]=min(hits,key=lambda r:r["t"]) if hits else None
    return res
def ladder_eval(rows_by_ep,eps_meta,rules):
    recs=[]
    for e,rr in rows_by_ep.items():
        cand=[]
        for (k,R,Fr) in rules:
            for r in rr:
                if r["kind"]==k and r["features"]["px_retrace_bps"]>=R and r["features"].get("px_premove_180m_bps",0)>0 and r["features"]["px_retrace_bps"]/r["features"]["px_premove_180m_bps"]>=Fr:
                    cand.append(r)
        E=eps_meta[e];rec={"episode_id":e,"side":E["side"],"accepted":bool(cand)}
        if cand:
            r=min(cand,key=lambda r:r["t"]);rec["true_first"]=bool(r["y"]);rec["kind"]=r["kind"];rec["signal_t"]=r["t"];rec["entry"]=r["entry"]
            if r["y"]:
                rev=1 if E["side"]=="LOW" else -1
                rec["dist_pct"]=rev*(r["entry"]/E["target_price"]-1)*100;rec["delay_s"]=r["t"]-(r["member_g"]+1)
                rec["remaining_move_pct"]=rev*(E["next_price"]/r["entry"]-1)*100
                rec["captured_mfe_ratio"]=max(0.0,rev*(E["next_price"]-r["entry"]))/abs(E["next_price"]-E["target_price"])
        recs.append(rec)
    return recs
if __name__=="__main__":
    d=pickle.load(open(DATA/"dataset.pkl","rb"));rows=[r for r in d["rows"] if r["kind"] in AGES];eps={e["episode_id"]:e for e in d["episodes"]}
    out={"family":"one-shot age checkpoint x min retrace x min fraction of causal pre-move-180 (V1 teacher family, earlier ages)","folds":{}}
    for fold in FOLDS:
        dev_months=[n for n,a,b in MONTHS if B[fold["train"][0]]<=B[a] and B[b]<=B[fold["cal"][1]]]
        tst=(B[fold["test"][0]],B[fold["test"][1]])
        fo={}
        for side in ("LOW","HIGH"):
            by_ep_dev=collections.defaultdict(list);by_ep_test=collections.defaultdict(list)
            for r in rows:
                if r["side"]!=side:continue
                E=eps[r["episode_id"]];m=month_of(E["tmin_s"])
                if m in dev_months and E["finalized_s"]<=B[fold["cal"][1]]:by_ep_dev[r["episode_id"]].append(r)
                if tst[0]<=E["tmin_s"]<tst[1] and E["finalized_s"]<=B["END"]:by_ep_test[r["episode_id"]].append(r)
            # per-rule dev evaluation
            table={}
            for k in AGES:
                for R in RS:
                    for Fr in FS:
                        recs=ladder_eval(by_ep_dev,eps,[(k,R,Fr)])
                        per_m=collections.defaultdict(lambda:[0,0])
                        for x in recs:
                            if x["accepted"]:per_m[month_of(eps[x["episode_id"]]["tmin_s"])][0 if x["true_first"] else 1]+=1
                        table[(k,R,Fr)]={"tp":sum(v[0] for v in per_m.values()),"fp":sum(v[1] for v in per_m.values()),"per_month":dict(per_m)}
            # plateau: rule and its next-looser neighbours in R and F must all be FP=0 on dev
            def neigh(k,R,Fr):
                i=RS.index(R);j=FS.index(Fr);n=[]
                if i>0:n.append((k,RS[i-1],Fr))
                if j>0:n.append((k,R,FS[j-1]))
                return n
            ok=[key for key,v in table.items() if v["fp"]==0 and v["tp"]>0 and all(table[n]["fp"]==0 for n in neigh(*key))]
            # best rule per age; ladder = union, must remain FP=0 on dev
            ladder=[]
            for k in AGES:
                cands=sorted([x for x in ok if x[0]==k],key=lambda x:(-table[x]["tp"],x[1],x[2]))
                if cands:
                    trial=ladder+[cands[0]]
                    recs=ladder_eval(by_ep_dev,eps,trial)
                    if all(x["true_first"] for x in recs if x["accepted"]):ladder=trial
            dev=summarize(ladder_eval(by_ep_dev,eps,ladder)) if ladder else None
            test=summarize(ladder_eval(by_ep_test,eps,ladder)) if ladder else None
            fo[side]={"dev_months":dev_months,"selected_ladder":[{"age_min":AGES[k],"min_retrace_bps":R,"min_fraction_pre180":Fr} for k,R,Fr in ladder],
                      "dev":dev,"test":test,"test_records":ladder_eval(by_ep_test,eps,ladder) if ladder else []}
            print(fold["name"],side,fo[side]["selected_ladder"],"dev",{k:dev[k] for k in ("tp","false_first","true_terminal_locals","median_dist_pct")} if dev else None,
                  "test",{k:test[k] for k in ("tp","false_first","true_terminal_locals","median_dist_pct","median_captured_mfe_ratio")} if test else None,flush=True)
        out["folds"][fold["name"]]=fo
    json.dump(out,open(DATA/"survival_ladder.json","w"),default=float,indent=1)
