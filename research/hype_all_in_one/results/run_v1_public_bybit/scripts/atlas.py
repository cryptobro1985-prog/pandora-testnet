"""TRUE vs FALSE relationship atlas (LOW/HIGH separately) on May1..Nov3 (transfer history). Forward Nov4+ excluded."""
import pickle,json,math,collections,itertools,numpy as np
from core import *
from sklearn.metrics import roc_auc_score
KINDS=("T0","T30","T60","T180","T300","T900","T1800","A25","A30","A35","A40","A50","A70")
MONTHS=[("May","2026-05-01","2026-06-01"),("Jun","2026-06-01","2026-07-01"),("Jul","2026-07-01","2026-08-01"),
        ("Aug","2026-08-01","2026-09-01"),("Sep","2026-09-01","2026-10-01"),("Oct","2026-10-01","2026-11-04")]
def S(i):return int(datetime.fromisoformat(i).replace(tzinfo=timezone.utc).timestamp())-T0
CONSEQUENCE={"px_retrace_bps","px_max_retrace_bps","px_retrace_speed","px_age_s","px_log_age","eff_new_post","fl_post_new_notl_log",
             "fl_post_old_notl_log","fl_post_trades_log","px_giveback_bps","fl_maxtrade_post_log","oi_chg_since_ext_pct","bk_support_chg_since_ext",
             "bk_dimb50_since_ext","bk_dimb10_since_ext","bk_oppose_chg_since_ext","fl_post_imb_rev","fl_post_rate_vs_pre","eff_post_vs_pre"}
FAMILY=[("px_","price structure / retrace (ids 1,4-11,36-39)"),("h1_","H1 structure (id 7,10)"),("vol_","volatility (id 4)"),
        ("lin_","lineage: candidate survival/invalidation/prior false attempts (ids 37,40-43)"),("opp_","causal opposite swing anchor (ids 10,37)"),
        ("fl_","aggressor flow / CVD / intensity (ids 12-25,35)"),("eff_","price-response efficiency (ids 26-34)"),("burst_","aggressive burst proxy - NOT liquidation (ids 16,19)"),
        ("bk_","L50 order book (ids 44-55)"),("oi_","open interest (ids 58,59,115)"),("poi_","price/OI relationship (id 61)"),("fund_","funding (id 62)"),
        ("basis_","mark-index basis (ids 2,3,114)"),("premium_","last-mark premium (ids 1,2)"),("hold_","holder ratio (id 113)"),("reg_","market regime"),("q_","quality / freshness / continuity masks (ids 56,60,79,80,116)")]
def fam(k):
    for p,n in FAMILY:
        if k.startswith(p):return n
    return "other"
def regime(r):
    s=r["features"].get("reg_score")
    if s is None or not np.isfinite(s):return "UNKNOWN"
    return "BULL" if s>.18 else "BEAR" if s<-.18 else "TRANSITION"
def auc(t,f):
    if len(t)<5 or len(f)<5:return None
    return float(roc_auc_score([1]*len(t)+[0]*len(f),list(t)+list(f)))
def stats(rr,k):
    t=[r["features"][k] for r in rr if r["y"] and k in r["features"] and np.isfinite(r["features"][k])]
    f=[r["features"][k] for r in rr if not r["y"] and k in r["features"] and np.isfinite(r["features"][k])]
    if len(t)<8 or len(f)<20:return None
    allv=np.array(t+f);med=np.median(allv);mad=1.4826*np.median(np.abs(allv-med));sc=max(mad,1e-9,abs(med)*.02)
    a=auc(t,f)
    return {"n_true":len(t),"n_false":len(f),"median_true":float(np.median(t)),"median_false":float(np.median(f)),
            "effect_size":float((np.median(t)-np.median(f))/sc),"auc":a,"sign":"higher_in_TRUE" if a>0.5 else "higher_in_FALSE"}
def build():
    d=pickle.load(open(DATA/"dataset.pkl","rb"));rows=[r for r in d["rows"] if r["t"]<S("2026-11-04")]
    names=sorted({k for r in rows for k in r["features"]})
    out={"version":"HYPE-EARLY-TRUE-FALSE-ATLAS-v1","scope":"2026-05-01..2026-11-03 transfer history (forward Nov4+ excluded)",
         "teacher":"strict H1 L6/K2 terminal pivot (offline label only)","unit":"one row per lineage member per decision point kind",
         "liquidations":"UNAVAILABLE in public history (no Bybit liquidation archive) - never imputed; burst_* is an aggressive-flow proxy, not liquidation data",
         "sides":{}}
    for side in ("LOW","HIGH"):
        S_={"by_kind":{}}
        for kind in KINDS:
            rr=[r for r in rows if r["side"]==side and r["kind"]==kind]
            if not rr:continue
            feats={}
            for k in names:
                st=stats(rr,k)
                if st is None:continue
                st["family"]=fam(k);st["availability"]=float(np.mean([k in r["features"] and np.isfinite(r["features"][k]) for r in rr]))
                st["consequence_of_move"]=k in CONSEQUENCE
                ms={};signs=[]
                for mn,a,b in MONTHS:
                    sub=[r for r in rr if S(a)<=r["t"]<S(b)]
                    t=[r["features"][k] for r in sub if r["y"] and k in r["features"] and np.isfinite(r["features"][k])];f=[r["features"][k] for r in sub if not r["y"] and k in r["features"] and np.isfinite(r["features"][k])]
                    au=auc(t,f) if len(t)>=8 else None
                    ms[mn]={"auc":au,"n_true":len(t),"n_false":len(f)}
                    if au is not None:signs.append(au>0.5)
                overall=st["auc"]>0.5
                st["months"]=ms;st["month_sign_agreement"]=float(np.mean([s==overall for s in signs])) if signs else None
                st["months_evaluated"]=len(signs)
                rg={}
                for g in ("BULL","BEAR","TRANSITION"):
                    sub=[r for r in rr if regime(r)==g]
                    t=[r["features"][k] for r in sub if r["y"] and k in r["features"] and np.isfinite(r["features"][k])];f=[r["features"][k] for r in sub if not r["y"] and k in r["features"] and np.isfinite(r["features"][k])]
                    rg[g]={"auc":auc(t,f) if len(t)>=8 else None,"n_true":len(t),"n_false":len(f)}
                st["regimes"]=rg
                feats[k]=st
            stable=[(k,v) for k,v in feats.items() if v["month_sign_agreement"] is not None and v["month_sign_agreement"]>=0.83 and v["months_evaluated"]>=5]
            true_rel=sorted([x for x in stable if x[1]["auc"]>0.5],key=lambda x:-x[1]["auc"])[:15]
            false_rel=sorted([x for x in stable if x[1]["auc"]<0.5],key=lambda x:x[1]["auc"])[:15]
            unstable=sorted([(k,v) for k,v in feats.items() if v["month_sign_agreement"] is not None and v["month_sign_agreement"]<0.67 and abs(v["auc"]-.5)>0.05],key=lambda x:-abs(x[1]["auc"]-.5))[:10]
            # interaction pairs among top stable features
            top=[k for k,_ in (true_rel[:6]+false_rel[:6])]
            base=np.mean([r["y"] for r in rr]);pairs=[]
            meds={k:np.median([r["features"][k] for r in rr if k in r["features"] and np.isfinite(r["features"][k])]) for k in top}
            def ok(r,k):
                v=r["features"].get(k)
                if v is None or not np.isfinite(v):return None
                return v>meds[k] if feats[k]["auc"]>0.5 else v<meds[k]
            for a,b in itertools.combinations(top,2):
                sub=[r for r in rr if ok(r,a) and ok(r,b)]
                if len(sub)<20:continue
                p=np.mean([r["y"] for r in sub]);mstab={}
                for mn,x,y in MONTHS:
                    s2=[r for r in sub if S(x)<=r["t"]<S(y)];s3=[r for r in rr if S(x)<=r["t"]<S(y)]
                    if s2 and s3:mstab[mn]=round(float(np.mean([r["y"] for r in s2])/max(np.mean([r["y"] for r in s3]),1e-9)),3)
                pairs.append({"a":a,"b":b,"condition":f"{a} {'>' if feats[a]['auc']>0.5 else '<'} {meds[a]:.4g} AND {b} {'>' if feats[b]['auc']>0.5 else '<'} {meds[b]:.4g}",
                              "support":len(sub),"true_in_support":int(sum(r["y"] for r in sub)),"precision":float(p),"lift":float(p/max(base,1e-9)),"lift_by_month":mstab,
                              "lift_min_month":min(mstab.values()) if mstab else None})
            pairs.sort(key=lambda x:-x["lift"])
            S_["by_kind"][kind]={"rows":len(rr),"true":int(sum(r["y"] for r in rr)),"false":int(sum(1-r["y"] for r in rr)),"base_rate":float(base),
                "strongest_TRUE_relationships":[{"feature":k,**v} for k,v in true_rel],
                "strongest_FALSE_relationships":[{"feature":k,**v} for k,v in false_rel],
                "unstable_sign_rejected":[{"feature":k,"auc":v["auc"],"month_sign_agreement":v["month_sign_agreement"],"months":v["months"]} for k,v in unstable],
                "interaction_pairs":pairs[:12],
                "all_features":feats}
        # earliness map: AUC deviation by kind
        early={}
        for k in names:
            row={}
            for kind in KINDS:
                v=S_["by_kind"].get(kind,{}).get("all_features",{}).get(k)
                if v:row[kind]=round(v["auc"],3)
            if row:
                e=max([abs(row.get(x,0.5)-.5) for x in ("T0","T30","T60")]);l=max([abs(row.get(x,0.5)-.5) for x in ("A40","T300","T1800","A70")])
                early[k]={"auc_by_kind":row,"early_strength":round(e,3),"late_strength":round(l,3),
                          "timing":"EARLY (visible at extreme..+60s)" if e>=0.08 else ("LATE / consequence of move" if l>=0.08 else "weak"),
                          "consequence_of_move":k in CONSEQUENCE,"family":fam(k)}
        S_["earliness_map"]=early
        # Local-type taxonomy at A40 (rule-based physical typing; counts true/false)
        rr=[r for r in rows if r["side"]==side and r["kind"]=="A40"]
        def q(k,p):
            v=[r["features"][k] for r in rr if k in r["features"] and np.isfinite(r["features"][k])];return np.percentile(v,p) if v else np.nan
        th={"burst":q("burst_pre300_vs_1h",75),"eff_old":q("eff_old_pre300",25),"bk":q("bk_dimb50_since_ext",75),"oi":q("oi_chg_into_ext_60m_pct",25),
            "agg":q("px_retrace_speed",75),"age":q("px_age_s",75)}
        types={"liquidation_exhaustion_proxy(burst)":lambda f:f.get("burst_pre300_vs_1h",-1)>=th["burst"],
               "absorption(old-side inefficient)":lambda f:f.get("eff_old_pre300",1e9)<=th["eff_old"],
               "orderbook_control_transfer":lambda f:f.get("bk_dimb50_since_ext",-9)>=th["bk"],
               "oi_unwind_into_extreme":lambda f:f.get("oi_chg_into_ext_60m_pct",9)<=th["oi"],
               "aggressive_reversal(speed)":lambda f:f.get("px_retrace_speed",-9)>=th["agg"],
               "slow_structural_exhaustion(age)":lambda f:f.get("px_age_s",-9)>=th["age"]}
        tax={}
        base=np.mean([r["y"] for r in rr])
        for nm,fn in types.items():
            sub=[r for r in rr if fn(r["features"])]
            tax[nm]={"support":len(sub),"true":int(sum(r["y"] for r in sub)),"precision":float(np.mean([r["y"] for r in sub])) if sub else None,
                     "lift":float(np.mean([r["y"] for r in sub])/base) if sub else None}
        S_["local_type_taxonomy_A40"]={"thresholds_quantiles_pooled":{k:float(v) for k,v in th.items()},"base_rate":float(base),"types":tax}
        out["sides"][side]=S_
    return out
if __name__=="__main__":
    o=build()
    json.dump(o,open(DATA/"atlas.json","w"),default=float,indent=1)
    for side in ("LOW","HIGH"):
        for kind in ("T30","A40","T1800"):
            b=o["sides"][side]["by_kind"][kind]
            print(side,kind,"TRUE:",[(x["feature"],round(x["auc"],3)) for x in b["strongest_TRUE_relationships"][:6]])
            print(side,kind,"FALSE:",[(x["feature"],round(x["auc"],3)) for x in b["strongest_FALSE_relationships"][:6]])
        print(side,"taxonomy",o["sides"][side]["local_type_taxonomy_A40"]["types"])
