#!/usr/bin/env python3
"""HYPE price-flow paper execution replay, MFE and leverage/margin stress V1.

Research-only. No broker access. This replays a FROZEN Jul-trained, Aug-dev
selected .80 probability threshold from causal_path_benchmark_v1. 60m future
barrier labels were used in fitting, never in runtime predictions.

Execution assumptions are deliberately conservative but still PROXIES:
next 1m OPEN after observed close, stop priority in OHLC ties, 12bps nominal
roundtrip costs with additional 8/25bps shock. Book/tick/mark-price
liquidation mechanics are NOT available across all saved history.

Historical September and October have ALREADY BEEN INSPECTED. NO promotion.
"""
from __future__ import annotations
import argparse,zipfile,json,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from research.hype_unified_intelligence.causal_path_benchmark_v1 import (
    load_period,materialize,PERIODS,TRAIN_FEATURES,FLOW_FEATURES,
)

THRESHOLD=.80
STOP=.0035
TAKE=.0050
COST_BPS=12
COOLDOWN_MS=30*60000
HOLD_MAX_MIN=120

def replay(rows,d,probs,mode):
    end=np.array([int(r["bar_end_ms"]) for r in rows],dtype=np.int64)
    o=np.array([float(r["open"]) for r in rows])
    h=np.array([float(r["high"]) for r in rows])
    l=np.array([float(r["low"]) for r in rows])
    c=np.array([float(r["close"]) for r in rows])
    gap=np.array([bool(r.get("gap",False)) for r in rows])
    buy=np.array([float(r.get("buy_notional") or 0) for r in rows])
    sell=np.array([float(r.get("sell_notional") or 0) for r in rows])
    idx=np.searchsorted(end,d["t"])
    assert np.all(end[idx]==d["t"])
    candidates={int(k):scores for k,scores in zip(idx,probs)}
    trades=[];pos=None;last_open=-10**15;last_close=-10**15
    for k in range(1,len(rows)):
        if pos is not None:
            p=pos;s=p["side"];sign=1 if s==0 else -1
            entry=p["entry"];held=k-p["k"]
            invalid=(gap[k] or end[k]-end[k-1]!=60000 or
                     o[k]<=0 or l[k]<=0)
            if invalid:
                if o[k]>0:
                    gross=sign*(o[k]/entry-1)
                    trades.append(dict(side=s,entry_ms=p["entry_ms"],
                        exit_ms=int(end[k]-60000),entry=float(entry),
                        exit=float(o[k]),gross=gross,net=gross-COST_BPS/10000,
                        mfe=p["mfe"],mae=max(p["mae"],-gross),
                        worst=p["worst"],hold_min=held,
                        reason="DATA_GAP_EXIT",unverified_fill=True))
                pos=None;last_close=int(end[k]);continue
            favorable=(h[k]/entry-1) if s==0 else (1-l[k]/entry)
            adverse=(1-l[k]/entry) if s==0 else (h[k]/entry-1)
            p["mfe"]=max(p["mfe"],favorable,0)
            p["mae"]=max(p["mae"],adverse,0)
            p["worst"]=max(p["worst"],adverse,0)
            bad_start=sign*(o[k]/entry-1)<=-STOP
            stop=adverse>=STOP
            take=favorable>=TAKE
            exit_px=None;reason=None
            if stop:
                # OHLC high/low cannot establish favorable-first same-bar.
                stop_px=entry*(1-STOP*sign)
                exit_px=min(o[k],stop_px) if s==0 else max(o[k],stop_px)
                reason="HARD_STOP"
            elif mode=="fixed" and take:
                exit_px=entry*(1+TAKE*sign)
                reason="TAKE_PROFIT"
            elif held>=HOLD_MAX_MIN:
                if k+1<len(rows) and end[k+1]-end[k]==60000 and not gap[k+1]:
                    exit_px=o[k+1]
                    reason="MAX_HOLD_NEXT_OPEN"
                else:
                    exit_px=c[k]
                    reason="MAX_HOLD_MARK_UNVERIFIED"
            elif mode=="trend_hold" and k+1<len(rows) and held>=3 and p["mfe"]>=.004:
                favor=buy[k-2:k+1] if s==0 else sell[k-2:k+1]
                oppos=sell[k-2:k+1] if s==0 else buy[k-2:k+1]
                flow=(favor-oppos)/np.maximum(1,favor+oppos)
                counter=(1-c[k]/c[k-3]) if s==0 else (c[k]/c[k-3]-1)
                recoil=p["mfe"]-sign*(c[k]/entry-1)
                if (len(flow)==3 and np.all(flow<-.10) and
                    counter>.001 and recoil>max(.0035,.4*p["mfe"]) and
                    end[k+1]-end[k]==60000 and not gap[k+1]):
                    exit_px=o[k+1]
                    reason="SUSTAINED_OPPOSING_EFFICIENCY_NEXT_OPEN"
            if exit_px is not None:
                gross=sign*(exit_px/entry-1)
                trades.append(dict(side=s,entry_ms=p["entry_ms"],
                    exit_ms=int(end[k]),entry=float(entry),exit=float(exit_px),
                    gross=float(gross),net=float(gross-COST_BPS/10000),
                    mfe=float(p["mfe"]),mae=float(p["mae"]),
                    worst=float(p["worst"]),hold_min=held,reason=reason,
                    unverified_fill=bool(bad_start or "UNVERIFIED" in reason)))
                pos=None;last_close=int(end[k]);continue
        if (pos is None and k in candidates and
            end[k]-last_open>=COOLDOWN_MS and end[k]-last_close>=COOLDOWN_MS):
            z=candidates[k];s=int(z.argmax())
            if z[s]<THRESHOLD or z[s]-z[1-s]<.08:continue
            if k+1>=len(rows) or gap[k+1] or end[k+1]-end[k]!=60000:
                continue
            px=o[k+1]
            if px<=0:continue
            pos=dict(side=s,entry=float(px),entry_ms=int(end[k]),
                     k=k+1,mfe=0.,mae=0.,worst=0.)
            last_open=int(end[k])
    if pos is not None:
        p=pos;s=p["side"];sign=1 if s==0 else -1
        gross=sign*(c[-1]/p["entry"]-1)
        trades.append(dict(side=s,entry_ms=p["entry_ms"],exit_ms=int(end[-1]),
            entry=p["entry"],exit=float(c[-1]),gross=gross,
            net=gross-COST_BPS/10000,mfe=p["mfe"],mae=p["mae"],
            worst=p["worst"],hold_min=len(rows)-1-p["k"],
            reason="END_MARK_UNVERIFIED",unverified_fill=True))
    return trades

def summarize(tt):
    if not tt:return {"trades":0}
    m=np.array([t["net"] for t in tt])
    win=m[m>0];lose=m[m<0]
    eq=np.cumprod(1+m);peaks=np.maximum.accumulate(np.r_[1.,eq])[1:]
    captures=[t["gross"]/t["mfe"] for t in tt if t["mfe"]>1e-6]
    return dict(trades=len(tt),long=sum(t["side"]==0 for t in tt),
        short=sum(t["side"]==1 for t in tt),wins=int(sum(m>0)),
        win_rate=float(np.mean(m>0)),
        underlying_compound_pct=float((np.prod(1+m)-1)*100),
        profit_factor=float(sum(win)/abs(sum(lose))) if len(lose) else None,
        max_drawdown_pct=float(np.max(1-eq/peaks)*100),
        median_mfe_bps=float(np.median([t["mfe"] for t in tt])*10000),
        median_mae_bps=float(np.median([t["mae"] for t in tt])*10000),
        median_capture=float(np.median(captures)) if captures else None,
        exit_reasons=dict(Counter(t["reason"] for t in tt)),
        largest_winner_pct=float(max(m)*100))

def stress(tt,L,margin,shock_bps=0,maintenance=.005):
    equity=1.;peak=1.;draw=0.;worst_open=0.;liq=0
    exposure=L*margin
    liquidation_underlying=max(0,1/L-maintenance)
    for t in tt:
        worst_open=max(worst_open,exposure*(t["mae"]+shock_bps/10000))
        crossed=t["worst"]>=liquidation_underlying
        if crossed:liq+=1;equity*=max(0,1-margin)
        else:equity*=max(0,1+exposure*(t["net"]-shock_bps/10000))
        peak=max(peak,equity)
        draw=max(draw,1-equity/peak)
    return dict(leverage=L,margin_fraction=margin,
        equity_exposure=round(exposure,3),
        equity_return_pct=round((equity-1)*100,3),
        max_dd_pct=round(100*draw,3),
        worst_open_equity_loss_pct=round(100*worst_open,3),
        approx_liquidations=liq,
        approx_liq_underlying_pct=round(100*liquidation_underlying,3))

def main(master):
    with zipfile.ZipFile(master) as z:
        rows={name:load_period(z,key) for name,key in PERIODS.items()}
    d={name:materialize(r) for name,r in rows.items()}
    features=list(range(len(TRAIN_FEATURES+FLOW_FEATURES)))
    models=[]
    for side in (0,1):
        m=make_pipeline(StandardScaler(),
             LogisticRegression(C=.2,max_iter=400,random_state=20261111))
        m.fit(d["train"]["X"][:,features],d["train"]["y"][:,side])
        models.append(m)
    probs={name:np.column_stack([m.predict_proba(v["X"][:,features])[:,1]
                               for m in models]) for name,v in d.items()}
    trades={split:{mode:replay(rows[split],d[split],probs[split],mode)
                   for mode in ("fixed","trend_hold")}
            for split in ("dev","validation","holdout")}
    summary={s:{m:summarize(t) for m,t in mm.items()} for s,mm in trades.items()}
    scenarios=[]
    for period in ("validation","holdout"):
        for mode in ("fixed","trend_hold"):
            for shock in (0,8,25):
                for L in (1,2,3,5,10,15,20,25):
                    for f in (.01,.02,.05,.10,.20):
                        scenarios.append(dict(period=period,mode=mode,
                            additional_cost_bps=shock,
                            **stress(trades[period][mode],L,f,shock)))
    return dict(version="HYPE-PAPER-RISK-REPLAY-v1",status="DIAGNOSTIC_NO_PROMOTION",
        model="price+flow frozen Jul train and Aug development threshold 0.80",
        data_sha256=hashlib.sha256(Path(master).read_bytes()).hexdigest(),
        future_labels_used_as_predictors=False,real_orders=False,
        execution={"entry":"next 1m open","stop_underlying_bps":35,
                   "fixed_take_underlying_bps":50,"roundtrip_cost_bps":COST_BPS,
                   "take_stop_same_bar":"stop wins","max_hold_mins":120,
                   "risk":"1/L minus 0.5pct approximated maintenance, NOT Bybit liquidation formula",
                   "source":"historical minute OHLC/flow, NOT executable quote/mark tick replay"},
        by_period=summary,stress_grid=scenarios,trades=trades,
        verdict="NO_PROVEN_OPTIMAL_LEVERAGE; ZERO_REAL_ORDER_FRACTION",
        warning="Validation contains only 2 trades; Oct historical OOS previously inspected; larger microstructure not yet covered")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--master",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();out=main(a.master)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"by_period":out["by_period"],"verdict":out["verdict"]}))
