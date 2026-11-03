from __future__ import annotations
import math,statistics
from collections import defaultdict
from datetime import datetime,timezone
from universal_params import Params
START=500.;FEE=.00045;SLIP=.0002

def simulate(p:Params,data,locals_,np,pd,start_ts:int,end_ts:int,record=False,symbols_subset=None):
    syms=sorted(symbols_subset or data);arr={};timeline=set()
    for s in syms:
        df=data[s];sub=df[(df.ts>=start_ts)&(df.ts<end_ts)]
        if sub.empty:continue
        side,anchor=locals_[s];ids=sub.index.to_numpy(int)
        A={k:sub[k].to_numpy(float if k!="ts" else int) for k in ("ts","open","high","low","close","imb1","imb3","imb5","ret1","ret3","activity")}
        A["side"]=side[ids];A["anchor"]=anchor[ids];A["map"]={int(t):i for i,t in enumerate(A["ts"])}
        arr[s]=A;timeline.update(map(int,A["ts"]))
    timeline=sorted(timeline)
    if not timeline:return {"score":-1e12,"final_equity":START,"trades":0}
    cash=START;pos={};watch={};pen_in={};pen_out={};rows=[];fees=0.;liqs=0;maxeq=START;maxdd=0.;daily={};realized=defaultdict(float);entries=reentries=pyramids=0
    def mark(s,t):
        A=arr.get(s);i=A["map"].get(t) if A else None
        return None if i is None else float(A["close"][i])
    def equity(t):return cash+sum(q["n"]*q["side"]*(mark(s,t)/q["entry"]-1) for s,q in pos.items() if mark(s,t) is not None)
    def used():return sum(q["m"] for q in pos.values())
    def fill(px,side,opening):return px*(1+(side if opening else -side)*SLIP)
    def close(s,px,t,reason):
        nonlocal cash,fees,liqs
        q=pos.pop(s);ex=fill(px,q["side"],False);outn=q["n"]*ex/q["entry"];fee=outn*FEE;gross=q["n"]*q["side"]*(ex/q["entry"]-1);net=gross-fee
        cash+=net;fees+=fee;realized[s]+=net;liqs+=reason=="LIQUIDATION_PROXY";cap=(q["side"]*(ex/q["entry"]-1)/q["mfe"]) if q["mfe"]>1e-9 else None
        rows.append({"symbol":s,"side":q["side"],"opened_ts":q["open_ts"],"closed_ts":t,"entry":q["entry"],"exit":ex,"margin":q["m"],"notional":q["n"],"pnl":net,"reason":reason,"mfe_move":q["mfe"],"mae_move":q["mae"],"capture_ratio":cap,"anchor":q["anchor"],"reentries":q["re"],"pyramid_adds":q["py"]})
        if reason in ("FLOW_COUNTER","MFE_RECOIL"):watch[s]={"side":q["side"],"anchor":q["anchor"],"ts":t,"corr":reason=="FLOW_COUNTER","re":q["re"]}
        else:watch.pop(s,None)
    for t in timeline:
        for s,(reason,sig) in list(pen_out.items()):
            A=arr.get(s);i=A["map"].get(t) if A else None
            if i is not None and t>sig and s in pos:close(s,float(A["open"][i]),t,reason);pen_out.pop(s,None)
        for s,(side,anchor,sig,isre) in list(pen_in.items()):
            A=arr.get(s);i=A["map"].get(t) if A else None
            if i is None or t<=sig or s in pos:continue
            if int(A["side"][i])!=side or int(A["anchor"][i])!=anchor:pen_in.pop(s,None);continue
            eq=equity(t);margin=min(eq*p.margin_fraction,max(0.,eq-used()))
            if margin<1:pen_in.pop(s,None);continue
            ep=fill(float(A["open"][i]),side,True);n=margin*p.leverage;fee=n*FEE;cash-=fee;fees+=fee
            re=(watch[s]["re"]+1) if isre and s in watch else 0;pos[s]={"side":side,"entry":ep,"open_ts":t,"m":margin,"n":n,"anchor":anchor,"re":re,"py":0,"mfe":0.,"mae":0.}
            if isre:reentries+=1;watch.pop(s,None)
            else:entries+=1
            pen_in.pop(s,None)
        for s,q in list(pos.items()):
            A=arr[s];i=A["map"].get(t)
            if i is None:continue
            hi,lo=float(A["high"][i]),float(A["low"][i]);fav=hi/q["entry"]-1 if q["side"]>0 else 1-lo/q["entry"];adv=lo/q["entry"]-1 if q["side"]>0 else 1-hi/q["entry"];q["mfe"]=max(q["mfe"],fav);q["mae"]=min(q["mae"],adv)
            liqmove=.92/p.leverage;liqpx=q["entry"]*(1-q["side"]*liqmove);stoppx=q["entry"]*(1-q["side"]*p.stop_move)
            if (lo<=liqpx if q["side"]>0 else hi>=liqpx):close(s,liqpx,t,"LIQUIDATION_PROXY");continue
            if (lo<=stoppx if q["side"]>0 else hi>=stoppx):close(s,stoppx,t,"HARD_STOP");continue
        cand=[]
        for s,A in arr.items():
            i=A["map"].get(t)
            if i is None:continue
            side=int(A["side"][i]);anchor=int(A["anchor"][i])
            if not side or not anchor:continue
            i1,i3,i5=float(A["imb1"][i]),float(A["imb3"][i]),float(A["imb5"][i]);r1,r3=float(A["ret1"][i]),float(A["ret3"][i])
            aligned=sum((side*i1>=p.entry_flow,side*i3>=p.entry_flow*.75,side*i5>=p.entry_flow*.5));priceok=side*r3>=-p.response_tol;act=float(A["activity"][i])>=p.min_activity;strength=side*i1+.7*side*i3+.4*side*i5+20*max(0,side*r3)
            if s in pos:
                q=pos[s]
                if q["anchor"]!=anchor or q["side"]!=side:pen_out[s]=("OPPOSITE_LOCAL",t);continue
                move=q["side"]*(float(A["close"][i])/q["entry"]-1);counter=q["side"]*i1<=-p.counter_flow and q["side"]*i3<=-p.counter_flow*.75 and (q["side"]*i5<0 or q["side"]*r1<0);recoil=max(0,q["mfe"]-move);weak=q["mfe"]>=p.mfe_arm and recoil>=p.mfe_recoil and q["side"]*i1<=p.weak_flow and q["side"]*r1<=0
                if counter:pen_out[s]=("FLOW_COUNTER",t);continue
                if weak:pen_out[s]=("MFE_RECOIL",t);continue
                if q["py"]<p.pyramid_adds and move>=p.pyramid_trigger and aligned==3 and priceok:
                    eq=equity(t);am=min(eq*p.margin_fraction*p.pyramid_fraction,max(0,eq-used()))
                    if am>=1:
                        ap=fill(float(A["close"][i]),q["side"],True);an=am*p.leverage;fee=an*FEE;cash-=fee;fees+=fee;q["entry"]=(q["entry"]*q["n"]+ap*an)/(q["n"]+an);q["n"]+=an;q["m"]+=am;q["py"]+=1;q["mfe"]=q["mae"]=0.;pyramids+=1
                continue
            w=watch.get(s)
            if w and (w["anchor"]!=anchor or w["side"]!=side):watch.pop(s,None);w=None
            if w:
                if side*i1<0 or side*r1<0:w["corr"]=True
                if w["corr"] and (t-w["ts"])//60>=p.reentry_cooldown and w["re"]<p.max_reentries and aligned>=p.consensus and priceok and act:cand.append((strength,s,side,anchor,True))
            elif aligned>=p.consensus and priceok and act:cand.append((strength,s,side,anchor,False))
        cand.sort(reverse=True)
        for _,s,side,anchor,isre in cand:
            if s in pos or s in pen_in:continue
            eq=equity(t);free=max(0,eq-used())
            if free>=max(1,eq*p.margin_fraction*.95):pen_in[s]=(side,anchor,t,isre)
        e=equity(t);maxeq=max(maxeq,e);maxdd=max(maxdd,1-e/maxeq if maxeq>0 else 1);daily[datetime.fromtimestamp(t,tz=timezone.utc).date().isoformat()]=e
    if timeline:
        t=timeline[-1]
        for s in list(pos):
            m=mark(s,t)
            if m is not None:close(s,m,t,"END_MARK")
    normal=[x for x in rows if x["reason"]!="END_MARK"];wins=sum(x["pnl"]>0 for x in normal);gp=sum(max(0,x["pnl"]) for x in normal);gl=-sum(min(0,x["pnl"]) for x in normal);pf=gp/gl if gl>1e-9 else (99 if gp>0 else 0);caps=[max(-2,min(2,x["capture_ratio"])) for x in normal if x["capture_ratio"] is not None and math.isfinite(x["capture_ratio"])];medcap=statistics.median(caps) if caps else 0
    vals=[];prev=START
    for d in sorted(daily):v=daily[d];vals.append(v/prev-1 if prev>0 else -1);prev=v
    pdays=sum(x>0 for x in vals);ndays=sum(x<0 for x in vals);spos=sum(v>0 for v in realized.values());sc=max(1,len(realized));final=cash
    score=5*math.log(max(final,1)/START)+.45*min(pf,5)+.8*wins/max(1,len(normal))+.6*medcap+.8*pdays/max(1,len(vals))+.6*spos/sc-3.5*maxdd-1.2*ndays/max(1,len(vals))-.05*max(0,len(normal)-250)/50-8*liqs
    if len(normal)<20:score-=4
    if final<=0:score-=50
    out={"score":score,"start_equity":START,"final_equity":final,"return_pct":(final/START-1)*100,"max_drawdown_pct":maxdd*100,"trades":len(normal),"wins":wins,"losses":len(normal)-wins,"win_rate":wins/max(1,len(normal)),"profit_factor":pf,"fees":fees,"positive_days":pdays,"negative_days":ndays,"days":len(vals),"median_mfe_capture":medcap,"entries":entries,"reentries":reentries,"pyramid_adds":pyramids,"liquidations":liqs,"symbol_realized":dict(realized),"symbol_positive_ratio":spos/sc,"daily_equity":daily}
    if record:out["trade_rows"]=rows
    return out
