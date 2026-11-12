"""Build causal decision-point dataset of H1 Local candidates (lineage members).

Every 6h-trailing-extreme print (second resolution) is a lineage member; a more
extreme same-side print supersedes (resets) it. Each member gets causal decision
points: +0/10/30/60/180/300s and first retrace anchors 15..100 bps, only while it
has not been superseded. Labels (TRUE = member is the strict H1 L6/K2 terminal
pivot of its episode) are attached AFTER features, from offline labels.
"""
from __future__ import annotations
import math,pickle,sys,time
import numpy as np
from core import *

TIME_PTS=(0,10,30,60,180,300,600,900,1800,3600,7200,10800)
ANCHORS=(15,20,25,30,35,40,50,70,100)
HORIZON=6*3600

def rolling_min_prior(x,w):
    """out[m]=min(x[m-w:m]) (prior w completed), nan if insufficient."""
    from numpy.lib.stride_tricks import sliding_window_view
    out=np.full(len(x),np.nan)
    v=sliding_window_view(x,w).min(1)  # v[k]=min(x[k:k+w])
    out[w:]=v[:len(x)-w]
    return out

def make_members(tp,side):
    rev=1 if side=="LOW" else -1
    L=tp.low if side=="LOW" else -tp.high  # work in "low space" (smaller = more extreme)
    mL=tp.m_low if side=="LOW" else -tp.m_high
    prior=rolling_min_prior(mL,360)
    N=tp.nm*60
    Lm=L[:N].reshape(tp.nm,60)
    # running min within minute before second s
    cm=np.minimum.accumulate(Lm,axis=1)
    before=np.concatenate([np.full((tp.nm,1),np.inf),cm[:,:-1]],axis=1)
    thr=np.minimum(prior[:,None],before)
    mask=(Lm<thr)&~np.isnan(thr)
    g=np.nonzero(mask.ravel())[0]
    p=L[g]
    # supersede: first later member with lower price (stack)
    sup=np.full(len(g),-1,dtype=np.int64);stack=[]
    for i in range(len(g)-1,-1,-1):
        while stack and p[stack[-1]]>=p[i]:stack.pop()
        sup[i]=g[stack[-1]] if stack else tp.N
        stack.append(i)
    price=p if side=="LOW" else -p
    return g,price,sup

def episodes_from_labels(labels):
    labs=sorted([x for x in labels if x.get("reference_finalized")],key=lambda x:int(x["extreme_interval_start_ms"]))
    eps=[]
    for j in range(1,len(labs)-1):
        prev,t,n=labs[j-1],labs[j],labs[j+1]
        eps.append({"episode_id":int(t["label_id"]),"side":t["side"],
            "start_s":int(prev["extreme_interval_start_ms"])//1000-T0,"tmin_s":int(t["extreme_interval_start_ms"])//1000-T0,
            "tend_s":int(t["extreme_interval_end_ms"])//1000-T0,"deadline_s":int(n["extreme_interval_start_ms"])//1000-T0,
            "target_price":float(t["extreme_price"]),"next_price":float(n["extreme_price"]),
            "next_tmin_s":int(n["extreme_interval_start_ms"])//1000-T0,
            "finalized_s":int(t["reference_finalized_ms"])//1000-T0 if t.get("reference_finalized_ms") else None,
            "prev_price":float(prev["extreme_price"])})
    return eps

class Feat:
    def __init__(self,tp):
        self.tp=tp
        # H1 bars
        nh=tp.nm//60
        self.h_high=tp.m_high[:nh*60].reshape(nh,60).max(1);self.h_low=tp.m_low[:nh*60].reshape(nh,60).min(1)
        self.h_close=tp.m_close[:nh*60].reshape(nh,60)[:,-1];self.h_open=tp.m_open[:nh*60].reshape(nh,60)[:,0]
        # 1m log returns
        self.m_ret=np.concatenate([[0],np.diff(np.log(tp.m_close))])
        self.cr2=np.concatenate([[0],np.cumsum(self.m_ret**2)])
        self.notl=(tp.buy+tp.sell).astype(np.float64)
        self.cs=tp.cbuy+tp.csell
    def mrange(self,a,b,side_hi):
        a=max(0,a);b=max(a+1,b)
        return (self.tp.m_high[a:b].max() if side_hi else self.tp.m_low[a:b].min())

    def features(self,side,g,p,t,ctx):
        tp=self.tp;rev=1 if side=="LOW" else -1;f={}
        c=tp.closef[t-1]
        retr=rev*(c/p-1)*1e4
        age=t-(g+1)
        f["px_retrace_bps"]=retr;f["px_age_s"]=age;f["px_log_age"]=math.log1p(age)
        if t-1>g:
            seg_h=tp.high[g+1:t] if side=="LOW" else tp.low[g+1:t]
            best=seg_h.max() if side=="LOW" else seg_h.min()
            mx=rev*(best/p-1)*1e4
        else:mx=0.0
        f["px_max_retrace_bps"]=mx;f["px_giveback_bps"]=mx-retr;f["px_retrace_speed"]=retr/math.sqrt(age+1)
        m=g//60
        for w,name in ((60,"60"),(180,"180"),(360,"360")):
            if m-w>=0:
                opp=tp.m_high[m-w:m].max() if side=="LOW" else tp.m_low[m-w:m].min()
                f[f"px_premove_{name}m_bps"]=rev*(opp/p-1)*1e4
        for w in (60,300,900):
            if g-w>=0:f[f"px_approach_{w}s_bps"]=rev*(tp.closef[g-w]/p-1)*1e4
        mt=(t-1)//60  # minute of last known bar
        if mt-1440>=0:
            lo=min(tp.m_low[mt-1440:mt].min(),tp.low[mt*60:t].min());hi=max(tp.m_high[mt-1440:mt].max(),tp.high[mt*60:t].max())
            f["px_pos_24h"]=(c-lo)/max(hi-lo,EPS);f["px_range_24h_bps"]=(hi/lo-1)*1e4
            f["px_pos_24h_rev"]=f["px_pos_24h"] if side=="LOW" else 1-f["px_pos_24h"]
        h=t//3600;hc=h  # completed hours < h
        if hc>=14:
            hh=self.h_high[hc-14:hc];hl=self.h_low[hc-14:hc];hcl=self.h_close[hc-14:hc];ho=self.h_open[hc-14:hc]
            f["h1_atr14_bps"]=float(np.mean((hh-hl)/hcl))*1e4
            f["h1_dir3_rev"]=rev*(hcl[-1]/ho[-3]-1)*1e4;f["h1_dir6_rev"]=rev*(hcl[-1]/ho[-6]-1)*1e4
            struct=hl[-6:].min() if side=="LOW" else hh[-6:].max()
            f["h1_beyond_struct_bps"]=rev*(struct/p-1)*1e4
            f["h1_ext_vs_atr"]=f["h1_beyond_struct_bps"]/max(f["h1_atr14_bps"],1e-6)
        f["h1_hour_frac_t"]=(t%3600)/3600.0;f["h1_hour_frac_ext"]=(g%3600)/3600.0
        hs=h*3600
        if t>hs:
            cur_hi=tp.high[hs:t].max();cur_lo=tp.low[hs:t].min();f["h1_cur_range_bps"]=(cur_hi/cur_lo-1)*1e4
        if mt>=61:
            f["vol_rv60m"]=math.sqrt(max(0,(self.cr2[mt]-self.cr2[mt-60])/60))*1e4
            f["vol_rv15m"]=math.sqrt(max(0,(self.cr2[mt]-self.cr2[mt-15])/15))*1e4
            f["vol_ratio_15_60"]=f["vol_rv15m"]/max(f["vol_rv60m"],1e-9)
        # lineage context (causal: only members strictly before this member)
        f.update(ctx)
        if "opp_swing_bps" in ctx and "h1_atr14_bps" in f:f["opp_swing_vs_atr"]=ctx["opp_swing_bps"]/max(f["h1_atr14_bps"],1e-6)
        # ---- flow ----
        for w in (10,30,60,300,900):
            b,s,n=tp.flow(t-w,t);tot=b+s
            f[f"fl_imb_{w}s_rev"]=rev*(b-s)/tot if tot>0 else np.nan
            f[f"fl_notl_{w}s_log"]=math.log1p(tot)
        b1,s1,n1=tp.flow(t-3600,t);rate_h=(b1+s1)/3600
        b6,s6,_=tp.flow(t-60,t);f["fl_intensity_60s_vs_1h"]=((b6+s6)/60)/max(rate_h,1e-6)
        for w in (60,300):
            b,s,n=tp.flow(g+1-w,g+1);tot=b+s
            f[f"fl_pre_imb_{w}s_rev"]=rev*(b-s)/tot if tot>0 else np.nan
            f[f"fl_pre_notl_{w}s_log"]=math.log1p(tot)
        b,s,n=tp.flow(g+1,t);tot=b+s
        new=b if side=="LOW" else s;old=s if side=="LOW" else b
        f["fl_post_imb_rev"]=rev*(b-s)/tot if tot>0 else np.nan
        f["fl_post_new_notl_log"]=math.log1p(new);f["fl_post_old_notl_log"]=math.log1p(old);f["fl_post_trades_log"]=math.log1p(n)
        bp,sp,_=tp.flow(g+1-300,g+1);oldpre=sp if side=="LOW" else bp
        appr=f.get("px_approach_300s_bps",np.nan)
        f["eff_old_pre300"]=appr/(oldpre/1e6+0.05) if not np.isnan(appr) else np.nan
        f["eff_new_post"]=max(retr,0)/(new/1e6+0.05)
        f["eff_post_vs_pre"]=f["eff_new_post"]/(abs(f["eff_old_pre300"])+1e-3) if not np.isnan(f["eff_old_pre300"]) else np.nan
        f["fl_post_rate_vs_pre"]=(tot/max(age,1))/((bp+sp)/300+1e-6)
        for w in (900,3600):
            b,s,_=tp.flow(t-w,t);tot=b+s
            f[f"fl_cvd_{w//60}m_rev"]=rev*(b-s)/tot if tot>0 else np.nan
        if t-900>=0:
            pr=rev*(c/tp.closef[t-901]-1)*1e4;f["fl_price_15m_rev"]=pr
            f["fl_cvd_price_div_15m"]=f["fl_cvd_15m_rev"]*np.sign(-pr) if not np.isnan(f["fl_cvd_15m_rev"]) else np.nan
        # burst proxy (aggressive 5s burst, NOT liquidation data)
        a0=g+1-300
        if a0-3600>=0:
            cs=self.cs
            pre5=cs[a0+5:g+2:5]-cs[a0:g-3:5] if g+1-a0>=5 else np.array([0.0])
            base=cs[a0-3600+5:a0+1:5]-cs[a0-3600:a0-4:5]
            f["burst_pre300_vs_1h"]=float(pre5.max())/max(float(np.median(base)),1.0)
        f["fl_maxtrade_pre300_log"]=math.log1p(float(tp.maxn[max(0,g-299):g+1].max()))
        f["fl_maxtrade_post_log"]=math.log1p(float(tp.maxn[g+1:t].max())) if t-1>g else 0.0
        f["q_notrade_frac_60s"]=(tp.cnotrade[t]-tp.cnotrade[max(0,t-60)])/60.0
        # ---- book (L50) ----
        bk=tp.book_at(t);bk_ext=tp.book_at(g+1);bk_pre=tp.book_at(g+1-300)
        f["q_book_valid"]=1.0 if bk is not None else 0.0
        if bk is not None:
            # cols: t,bb,ba,b5,a5,b50,a50,b10bps,a10bps,b25bps,a25bps,b50_last,a50_last,spread,nupd,snaps
            def imb(x,i,j):return rev*(x[i]-x[j])/max(x[i]+x[j],1e-9)
            f["bk_imb50_rev"]=imb(bk,5,6);f["bk_imb5_rev"]=imb(bk,3,4);f["bk_imb10bps_rev"]=imb(bk,7,8);f["bk_imb25bps_rev"]=imb(bk,9,10)
            f["bk_spread_bps"]=bk[13]
            sup=bk[5] if side=="LOW" else bk[6];opp=bk[6] if side=="LOW" else bk[5]
            f["bk_support50_log"]=math.log1p(sup);f["bk_oppose50_log"]=math.log1p(opp)
            sup10=bk[7] if side=="LOW" else bk[8];opp10=bk[8] if side=="LOW" else bk[7]
            f["bk_support10bps_log"]=math.log1p(sup10);f["bk_oppose10bps_log"]=math.log1p(opp10)
            f["bk_l50_span_bps"]=((bk[12]/bk[11])-1)*1e4
            if bk_ext is not None:
                f["bk_dimb50_since_ext"]=f["bk_imb50_rev"]-imb(bk_ext,5,6)
                f["bk_dimb10_since_ext"]=f["bk_imb10bps_rev"]-imb(bk_ext,7,8)
                se=bk_ext[5] if side=="LOW" else bk_ext[6];oe=bk_ext[6] if side=="LOW" else bk_ext[5]
                f["bk_support_chg_since_ext"]=math.log((sup+1)/(se+1));f["bk_oppose_chg_since_ext"]=math.log((opp+1)/(oe+1))
                if bk_pre is not None:
                    sp_=bk_pre[5] if side=="LOW" else bk_pre[6]
                    f["bk_support_withdraw_pre300"]=math.log((se+1)/(sp_+1))
                    f["bk_dimb50_pre300_to_ext"]=imb(bk_ext,5,6)-imb(bk_pre,5,6)
        # ---- OI / price-OI ----
        oi,age_oi=tp.step_val(tp.oi_t,tp.oi_v,t)
        if age_oi is not None and age_oi<=900:
            f["q_oi_age_s"]=age_oi;f["oi_notional_log"]=math.log1p(oi*c)
            for w in (900,3600,10800):
                o2,a2=tp.step_val(tp.oi_t,tp.oi_v,t-w)
                if a2 is not None and a2<=900:f[f"oi_chg_{w//60}m_pct"]=(oi/o2-1)*100
            oe,ae=tp.step_val(tp.oi_t,tp.oi_v,g+1)
            if ae is not None and ae<=900:f["oi_chg_since_ext_pct"]=(oi/oe-1)*100
            op,ap_=tp.step_val(tp.oi_t,tp.oi_v,g+1-3600)
            if ap_ is not None and ap_<=900 and ae is not None and ae<=900:
                f["oi_chg_into_ext_60m_pct"]=(oe/op-1)*100
            if "oi_chg_60m_pct" in f and t-3601>=0:
                pr=(c/tp.closef[t-3601]-1)*1e4
                f["poi_rel_60m"]=np.sign(pr)*f["oi_chg_60m_pct"]  # >0: OI grows with price direction
                f["poi_rev_60m"]=rev*np.sign(pr)*f["oi_chg_60m_pct"]
        # funding / basis / holders
        fr,fa=tp.step_val(tp.fu_t,tp.fu_v,t)
        if fa is not None and fa<=9*3600:f["fund_rate"]=fr*1e4;f["fund_rate_rev"]=-rev*fr*1e4
        mk,ma=tp.step_val(tp.mk_t,tp.mk_c,t);ix,ia=tp.step_val(tp.ix_t,tp.ix_c,t)
        if ma is not None and ia is not None and ma<=180 and ia<=180:
            f["basis_bps"]=(mk/ix-1)*1e4;f["basis_rev_bps"]=rev*f["basis_bps"];f["premium_last_mark_bps"]=rev*(c/mk-1)*1e4
        br,ba_=tp.step_val(tp.ra_t,tp.ra_v,t)
        if ba_ is not None and ba_<=900:
            f["hold_buy_ratio"]=br
            b2,a2=tp.step_val(tp.ra_t,tp.ra_v,t-3600)
            if a2 is not None and a2<=900:f["hold_buy_ratio_chg_60m"]=br-b2
            f["hold_crowd_rev"]=(br-0.5)*(-rev)  # crowd positioned against reversal side
        # regime (completed minutes)
        for w in (15,60,360,480):
            if mt-w>=0:
                f[f"reg_ret_{w}m"]=(tp.m_close[mt-1]/tp.m_close[mt-1-w]-1)*1e4 if mt-1-w>=0 else np.nan
        if all(f"reg_ret_{w}m" in f for w in (15,60,360,480)):
            r15,r60,r360,r480=(f[f"reg_ret_{w}m"]/1e4 for w in (15,60,360,480))
            sc=.35*math.tanh(r15*80)+.30*math.tanh(r60*35)+.20*math.tanh(r360*12)+.15*math.tanh(r480*10)
            f["reg_score"]=sc;f["reg_score_rev"]=rev*sc
            for w in (15,60,360,480):f[f"reg_ret_{w}m_rev"]=rev*f[f"reg_ret_{w}m"]
        return f

def lineage_context(g,price,sup,mxr,i,gi,p,rev,opp):
    """Causal lineage context at member i (time gi): uses only prior members and supersede events <= gi."""
    lo=np.searchsorted(g,gi-21600);prior=np.arange(lo,i)
    ctx={"lin_members_6h":float(len(prior)),
         "lin_members_1h":float((g[prior]>=gi-3600).sum()) if len(prior) else 0.0}
    if len(prior):
        ctx["lin_drop_from_first_bps"]=rev*(price[prior[0]]/p-1)*1e4
        ctx["lin_time_since_prev_s"]=float(gi-g[prior[-1]])
        done=prior[sup[prior]<=gi]
        fb=mxr[done]
        ctx["lin_failed_bounces_25bps"]=float((fb>=25).sum());ctx["lin_failed_bounces_40bps"]=float((fb>=40).sum())
        ctx["lin_max_failed_bounce_bps"]=float(fb.max()) if len(fb) else 0.0
    sg,sp,ss,known=opp
    j=np.searchsorted(known,gi,side="right")-1
    if j>=0:
        ctx["opp_swing_bps"]=rev*(sp[j]/p-1)*1e4;ctx["opp_swing_age_s"]=float(gi-sg[j])
        ctx["opp_intact"]=float(ss[j]>gi)
    return ctx

def build(tp,labels,out_path,t_start_s,t_end_s):
    FE=Feat(tp)
    eps=episodes_from_labels(labels)
    rows=[];members_info={}
    MEM={sd:make_members(tp,sd) for sd in ("LOW","HIGH")}
    for side in ("LOW","HIGH"):
        g,price,sup=MEM[side]
        og,op,osup=MEM["HIGH" if side=="LOW" else "LOW"]
        # opposite members that survived >=2h (known at og+7200): causal swing anchors
        surv=(osup-og)>=7200
        sg=og[surv];sp=op[surv];ss=osup[surv];known=sg+7200
        sel=(g>=t_start_s)&(g<t_end_s)
        idxs=np.nonzero(sel)[0]
        eps_s=[e for e in eps if e["side"]==side]
        starts=np.array([e["start_s"] for e in eps_s]);tends=np.array([e["tend_s"] for e in eps_s])
        rev=1 if side=="LOW" else -1
        # per-member max retrace before supersede (for causal 'failed bounce' context: known only after supersede)
        mxr=np.zeros(len(g))
        for i in np.nonzero((g>=t_start_s-HORIZON)&(g<t_end_s))[0]:
            a=g[i]+1;b=min(sup[i],g[i]+HORIZON,tp.N)
            if b>a:
                best=tp.high[a:b].max() if side=="LOW" else tp.low[a:b].min()
                mxr[i]=rev*(best/price[i]-1)*1e4
        for i in idxs:
            gi=int(g[i]);p=float(price[i]);gs=int(sup[i])
            # episode assignment
            k=np.searchsorted(starts,gi,side="left")-1  # start < gi
            ep=None
            if 0<=k<len(eps_s):
                e=eps_s[k]
                if e["start_s"]<gi<e["tend_s"]+60 and gi<e["tend_s"]: ep=e
            if ep is None:continue
            is_true=(ep["tmin_s"]<=gi<ep["tend_s"]) and p==ep["target_price"]
            ctx=lineage_context(g,price,sup,mxr,i,gi,p,rev,(sg,sp,ss,known))
            # decision points
            limit=min(gs,ep["deadline_s"],tp.N-1,gi+1+HORIZON)
            pts=[]
            for d in TIME_PTS:
                t=gi+1+d
                if t<=limit:pts.append((t,f"T{d}"))
            if limit>gi+1:
                seg=tp.high[gi+1:limit] if side=="LOW" else -tp.low[gi+1:limit]
                run=np.maximum.accumulate(seg)
                for X in ANCHORS:
                    lvl=p*(1+X/1e4) if side=="LOW" else -(p*(1-X/1e4))
                    j=np.searchsorted(run,lvl,side="left")
                    if j<len(run):pts.append((gi+1+j+1,f"A{X}"))
            for t,kind in pts:
                if t>limit:continue
                f=FE.features(side,gi,p,t,ctx)
                entry=float(tp.closef[t-1])
                rows.append({"side":side,"member_g":gi,"member_price":p,"t":t,"kind":kind,"entry":entry,
                    "dist_pct":rev*(entry/p-1)*100,"dist_target_pct":rev*(entry/ep["target_price"]-1)*100,
                    "episode_id":ep["episode_id"],"y":int(is_true),"features":f})
        print(side,"members",len(idxs),"rows",len(rows),flush=True)
    pickle.dump({"rows":rows,"episodes":eps},open(out_path,"wb"))
    return rows,eps

if __name__=="__main__":
    t=time.time();tp=Tape();print("tape",time.time()-t,"book",tp.book is not None)
    m0=0;labels,_=strict_labels_for(tp,0,tp.nm)
    a=int((datetime(2026,5,1,tzinfo=timezone.utc).timestamp())-T0)
    rows,eps=build(tp,labels,DATA/"dataset.pkl",a,tp.N)
    print("done",len(rows),time.time()-t)
