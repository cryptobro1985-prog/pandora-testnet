from __future__ import annotations
import argparse, copy, gzip, json, math, random
from datetime import datetime, timezone
from pathlib import Path

from .technical import score_components

DISCOVERY=int(datetime(2026,10,11,tzinfo=timezone.utc).timestamp()*1000)
TRAIN_END=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp()*1000)
OOS=int(datetime(2026,10,27,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,11,3,tzinfo=timezone.utc).timestamp()*1000)
START_EQUITY=100.0
ROUND_TRIP_COST=0.0016
LEV_CHOICES=(3,5,8,10,15,20,25)

BASE_WEIGHTS={
 "trend_follow":{"trend":1.25,"stoch_momentum":.40,"stoch_reversal":0,"flow":.85,"book":.30,"oi_liq":.25,"local":.10,"structure":.55,"timing":.45,"quant":.85},
 "pullback":{"trend":.95,"stoch_momentum":0,"stoch_reversal":.75,"flow":.70,"book":.35,"oi_liq":.20,"local":.45,"structure":.55,"timing":.50,"quant":.80},
 "local_reversal":{"trend":-.20,"stoch_momentum":0,"stoch_reversal":1.10,"flow":.75,"book":.45,"oi_liq":.35,"local":1.30,"structure":.35,"timing":.60,"quant":.65},
 "liq_squeeze":{"trend":.35,"stoch_momentum":.15,"stoch_reversal":.35,"flow":.85,"book":.70,"oi_liq":1.30,"local":.35,"structure":.25,"timing":.40,"quant":.70},
 "absorption":{"trend":.40,"stoch_momentum":.10,"stoch_reversal":.35,"flow":1.00,"book":1.35,"oi_liq":.30,"local":.50,"structure":.35,"timing":.45,"quant":.75},
 "hybrid":{"trend":.75,"stoch_momentum":.25,"stoch_reversal":.35,"flow":.85,"book":.65,"oi_liq":.55,"local":.70,"structure":.55,"timing":.55,"quant":.90},
}

def load(path):
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():out.append(json.loads(line))
    return out

def clamp(v,a,b):return max(a,min(b,v))

def side_score(features,gene):
    c=score_components(features)
    num=0.0;den=0.0
    for k,w in gene["weights"].items():
        v=c.get(k,0.0)
        num+=w*v;den+=abs(w)
    raw=num/max(den,1e-12)
    # Trend strength gates conviction but does not force direction.
    raw*=0.55+0.45*c["strength"]
    return clamp(raw,-1,1),c

def nearest_leverage(v,maxlev):
    allowed=[x for x in LEV_CHOICES if x<=maxlev]
    return min(allowed,key=lambda x:abs(x-v)) if allowed else 3

def close_pos(pos,px,equity,ts,reason):
    r=pos["side"]*(px/pos["entry"]-1.0)
    pnl=pos["notional"]*r-pos["notional"]*ROUND_TRIP_COST
    before=equity;equity=max(0.0,equity+pnl)
    return equity,{
      "entry_ts":pos["entry_ts"],"exit_ts":ts,"side":"LONG" if pos["side"]>0 else "SHORT",
      "entry":pos["entry"],"exit":px,"leverage":pos["leverage"],"margin_fraction":pos["margin_fraction"],
      "notional":pos["notional"],"pnl":pnl,"equity_before":before,"equity_after":equity,
      "price_return":r,"mfe":pos["mfe"],"mae":pos["mae"],"reason":reason,"hold_minutes":pos["age_min"]
    }

def simulate(rows,gene):
    if not rows:return {"final":START_EQUITY,"return_pct":0,"daily_geom":0,"trades":0,"loss_rate":1,
                        "max_dd_pct":0,"profit_factor":None,"liquidations":0,"objective":-99}
    rows=sorted(rows,key=lambda r:r["ts_ms"])
    equity=START_EQUITY;peak=equity;maxdd=0.0;pos=None;trades=[];liqs=0
    prev_ts=None
    for r in rows:
        ts=int(r["ts_ms"]);px=float(r["price"]);x=r["features"]
        dt_min=0 if prev_ts is None else max(0.0,(ts-prev_ts)/60000.0);prev_ts=ts
        score,comp=side_score(x,gene)
        strength=comp["strength"];conf=comp["confidence"];adv=comp["adversary"]
        atr_pct=max(float(x.get("tech_15m_atr_pct",0) or 0),float(x.get("tech_5m_atr_pct",0) or 0),0.0005)

        if pos is not None:
            side_ret=pos["side"]*(px/pos["entry"]-1.0)
            pos["mfe"]=max(pos["mfe"],side_ret);pos["mae"]=min(pos["mae"],side_ret);pos["age_min"]+=dt_min
            adverse=max(0.0,-side_ret)
            liq_dist=max(0.001,1.0/pos["leverage"]-0.005)
            same_edge=pos["side"]*score
            giveback=max(0.0,pos["mfe"]-side_ret)
            atr_guard=gene["stop_atr"]*atr_pct
            emergency=adverse>=liq_dist*gene["liq_safety"]
            dynamic_stop=adverse>=atr_guard and same_edge<gene["hold_threshold"]
            flip=same_edge<=-gene["flip_threshold"]
            edge_lost=same_edge<gene["hold_threshold"] and (
                pos["side"]*comp["flow"]<0 or pos["side"]*comp["structure"]<0 or adv>gene["max_adversary"])
            trail=(pos["mfe"]>=gene["trail_activation_atr"]*atr_pct and
                   giveback>=gene["trail_giveback"]*max(pos["mfe"],1e-9) and
                   same_edge<gene["entry_threshold"])
            timeout=pos["age_min"]>=gene["max_hold_minutes"]
            if emergency or dynamic_stop or flip or edge_lost or trail or timeout:
                reason="emergency" if emergency else "dynamic_stop" if dynamic_stop else "flip" if flip else "edge_lost" if edge_lost else "mfe_trail" if trail else "timeout"
                if emergency and adverse>=liq_dist:
                    loss=pos["margin"]+pos["notional"]*ROUND_TRIP_COST
                    before=equity;equity=max(0.0,equity-loss);liqs+=1
                    trades.append({"entry_ts":pos["entry_ts"],"exit_ts":ts,"side":"LONG" if pos["side"]>0 else "SHORT",
                                   "entry":pos["entry"],"exit":px,"leverage":pos["leverage"],"margin_fraction":pos["margin_fraction"],
                                   "notional":pos["notional"],"pnl":equity-before,"equity_before":before,"equity_after":equity,
                                   "price_return":-adverse,"mfe":pos["mfe"],"mae":-adverse,"reason":"liquidation","hold_minutes":pos["age_min"]})
                    pos=None
                else:
                    equity,t=close_pos(pos,px,equity,ts,reason);trades.append(t);pos=None

        if pos is None and equity>0:
            direction=1 if score>0 else -1
            qualifying=(abs(score)>=gene["entry_threshold"] and strength>=gene["min_strength"] and
                        conf>=gene["min_confidence"] and adv<=gene["max_adversary"])
            if qualifying:
                conviction=clamp((abs(score)-gene["entry_threshold"])/max(1e-9,1-gene["entry_threshold"]),0,1)
                conviction*=clamp(.35+.65*conf,0,1)*(1-adv)
                lev=nearest_leverage(3+conviction*(gene["max_leverage"]-3),gene["max_leverage"])
                frac=.05+conviction*(gene["max_margin"]-.05)
                frac=clamp(frac,.05,gene["max_margin"])
                margin=equity*frac;notional=margin*lev
                pos={"side":direction,"entry":px,"entry_ts":ts,"leverage":lev,"margin_fraction":frac,
                     "margin":margin,"notional":notional,"mfe":0.0,"mae":0.0,"age_min":0.0}

        marked=equity
        if pos:
            marked=equity+pos["notional"]*pos["side"]*(px/pos["entry"]-1.0)-pos["notional"]*(ROUND_TRIP_COST/2)
        peak=max(peak,marked);maxdd=max(maxdd,(peak-marked)/peak if peak>0 else 1.0)
        if equity<=0:break

    if pos is not None:
        r=rows[-1];equity,t=close_pos(pos,float(r["price"]),equity,int(r["ts_ms"]),"period_end");trades.append(t)
    wins=sum(t["pnl"]>0 for t in trades);losses=len(trades)-wins
    gp=sum(max(0,t["pnl"]) for t in trades);gl=-sum(min(0,t["pnl"]) for t in trades)
    days=max((int(rows[-1]["ts_ms"])-int(rows[0]["ts_ms"]))/86400000.0,1/24)
    daily=-1.0 if equity<=0 else (equity/START_EQUITY)**(1/days)-1
    pf=gp/gl if gl>0 else (99.0 if gp>0 else 0.0)
    loss_rate=losses/len(trades) if trades else 1.0
    side_metrics={}
    for label in ("LONG","SHORT"):
        rr=[t for t in trades if t["side"]==label]
        sw=sum(t["pnl"]>0 for t in rr);sgp=sum(max(0,t["pnl"]) for t in rr);sgl=-sum(min(0,t["pnl"]) for t in rr)
        side_metrics[label.lower()]={"trades":len(rr),"wins":sw,"losses":len(rr)-sw,
            "win_rate":sw/len(rr) if rr else None,
            "profit_factor":(sgp/sgl if sgl>0 else (99.0 if sgp>0 else None)),
            "net_pnl":sum(t["pnl"] for t in rr)}
    objective=(-99 if equity<=0 else math.log(equity/START_EQUITY)/days)-3.5*maxdd-8*liqs-1.5*loss_rate
    if len(trades)<4:objective-=2
    return {"final":equity,"return_pct":(equity/START_EQUITY-1)*100,"daily_geom":daily,
            "trades":len(trades),"wins":wins,"losses":losses,"loss_rate":loss_rate,
            "win_rate":wins/len(trades) if trades else 0.0,"max_dd_pct":maxdd*100,
            "profit_factor":pf,"long":side_metrics["long"],"short":side_metrics["short"],
            "liquidations":liqs,"objective":objective,"detail":trades}

def mutate_weights(base,rng,scale=.35):
    return {k:clamp(v+rng.gauss(0,scale),-1.5,1.8) for k,v in base.items()}

def random_gene(family,rng,seed=None):
    base=copy.deepcopy(seed) if seed else {}
    weights=mutate_weights(base.get("weights",BASE_WEIGHTS[family]),rng,.22 if seed else .38)
    def pick(name,lo,hi):
        if seed and name in seed:
            span=(hi-lo)*.15;return clamp(rng.gauss(float(seed[name]),span),lo,hi)
        return rng.uniform(lo,hi)
    return {
      "family":family,"weights":weights,
      "entry_threshold":pick("entry_threshold",.18,.78),
      "hold_threshold":pick("hold_threshold",-0.10,.35),
      "flip_threshold":pick("flip_threshold",.10,.65),
      "min_strength":pick("min_strength",.15,.70),
      "min_confidence":pick("min_confidence",.35,.82),
      "max_adversary":pick("max_adversary",.25,.85),
      "max_leverage":int(rng.choice([8,10,15,20,25]) if not seed else min([8,10,15,20,25],key=lambda z:abs(z-pick("max_leverage",8,25)))),
      "max_margin":rng.choice([.10,.15,.20]) if not seed else min([.10,.15,.20],key=lambda z:abs(z-pick("max_margin",.10,.20))),
      "stop_atr":pick("stop_atr",.8,3.2),
      "liq_safety":pick("liq_safety",.45,.78),
      "trail_activation_atr":pick("trail_activation_atr",.5,3.0),
      "trail_giveback":pick("trail_giveback",.20,.80),
      "max_hold_minutes":pick("max_hold_minutes",30,480),
    }

def strip(m):
    return {k:v for k,v in m.items() if k!="detail"}

def robust_score(train,val,cal):
    if train["liquidations"] or val["liquidations"] or cal["liquidations"]:return -999
    growth=min(val["daily_geom"],cal["daily_geom"])
    dd=max(val["max_dd_pct"],cal["max_dd_pct"])/100
    loss=max(val["loss_rate"],cal["loss_rate"])
    pf=min(val["profit_factor"],cal["profit_factor"])
    count_pen=1.0 if min(val["trades"],cal["trades"])<4 else 0.0
    return growth-1.8*dd-.75*loss+.08*math.log(max(pf,.01))-count_pen

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset-root",type=Path,required=True)
    ap.add_argument("--family",choices=sorted(BASE_WEIGHTS),required=True)
    ap.add_argument("--round",type=int,default=1)
    ap.add_argument("--state",type=Path)
    ap.add_argument("--candidates",type=int,default=192)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    hist=load(args.dataset_root/"historical.jsonl.gz")
    cal=load(args.dataset_root/"calibration.jsonl.gz")
    hold=load(args.dataset_root/"holdout.jsonl.gz")
    train=[r for r in hist if DISCOVERY<=r["ts_ms"]<TRAIN_END]
    val=[r for r in hist if TRAIN_END<=r["ts_ms"]<OOS]
    oos=[r for r in hist if OOS<=r["ts_ms"]<END]
    seeds=[]
    if args.state and args.state.exists():
        try:
            st=json.loads(args.state.read_text())
            seeds=st.get("families",{}).get(args.family,{}).get("seed_genes",[])[:8]
        except Exception:pass
    rng=random.Random((hash(args.family)&0xffffffff)+args.round*1000003)
    rows=[]
    for i in range(args.candidates):
        seed=seeds[i%len(seeds)] if seeds and i<int(args.candidates*.7) else None
        gene=random_gene(args.family,rng,seed)
        tr=simulate(train,gene);va=simulate(val,gene);ca=simulate(cal,gene)
        rs=robust_score(tr,va,ca)
        rows.append({"gene":gene,"search_score":rs,"train":strip(tr),"validation":strip(va),"calibration":strip(ca)})
    rows.sort(key=lambda z:z["search_score"],reverse=True)
    top=rows[:12]
    for z in top:
        oo=simulate(oos,z["gene"]);ho=simulate(hold,z["gene"])
        z["historical_oos"]=strip(oo);z["live_holdout"]=strip(ho)
        both_sides_ok=True
        for mm in (oo,ho):
            for side in ("long","short"):
                sm=mm.get(side,{})
                if sm.get("trades",0)>=3 and (sm.get("profit_factor") is None or sm.get("profit_factor")<.90):
                    both_sides_ok=False
        z["sanity_pass"]=(
            oo["final"]>START_EQUITY and ho["final"]>START_EQUITY and
            oo["liquidations"]==0 and ho["liquidations"]==0 and
            oo["max_dd_pct"]<=35 and ho["max_dd_pct"]<=35 and
            oo["profit_factor"]>1.05 and ho["profit_factor"]>1.05 and both_sides_ok
        )
        z["zero_loss_target"]=z["sanity_pass"] and oo["losses"]==0 and ho["losses"]==0
        z["provisional_50pct_daily"]=(
            z["sanity_pass"] and min(oo["daily_geom"],ho["daily_geom"])>=.50 and
            max(oo["loss_rate"],ho["loss_rate"])<=.20
        )
    out={"family":args.family,"round":args.round,"evaluated":len(rows),"top":top,
         "best_search":top[0] if top else None,
         "seed_genes_next":[z["gene"] for z in top[:6]],
         "target_note":"50%/day is an aspirational research threshold, never a guaranteed return",
         "promotion_note":"holdout is a sanity gate; real promotion still requires fresh live forward after freeze"}
    (args.output/f"{args.family}.json").write_text(json.dumps(out,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("ONLY_PROFIT_FAMILY="+json.dumps({"family":args.family,"round":args.round,
          "best_score":top[0]["search_score"] if top else None,
          "best_oos":top[0].get("historical_oos") if top else None,
          "best_holdout":top[0].get("live_holdout") if top else None,
          "any_sanity":any(z.get("sanity_pass") for z in top),
          "any_50pct":any(z.get("provisional_50pct_daily") for z in top)},separators=(",",":")))

if __name__=="__main__":
    main()
