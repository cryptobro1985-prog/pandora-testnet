import os,json,datetime,urllib.request,math
import psycopg
from psycopg.rows import dict_row

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def epoch(x): return datetime.datetime.fromisoformat(str(x).replace("Z","+00:00")).timestamp()

def mids():
    req=urllib.request.Request(os.getenv("HYPERLIQUID_INFO_API","https://api.hyperliquid.xyz/info"),
        data=b'{"type":"allMids"}',headers={"Content-Type":"application/json","User-Agent":"PANDORA-restore/1"})
    with urllib.request.urlopen(req,timeout=8) as r:return {str(k):float(v) for k,v in json.load(r).items()}

def liq_fraction(f):
    depth=float(f.get("book_depth_usd",0) or f.get("opposing_depth_usd",0) or 0)
    day=float(f.get("day_volume_usd",0) or 0);score=max(0,min(100,float(f.get("score",0) or 0)))
    streak=max(0,float(f.get("confirmation_streak",0) or 0));conf=max(0,float(f.get("micro_confirmations",0) or 0))
    burst=max(0,float(f.get("volume_burst_ratio",0) or 0));flow=abs(float(f.get("flow_imbalance",0) or 0))
    whale=max(0,float(f.get("whale_size_usd",0) or 0));floor=max(1,float(f.get("floor_notional_usd",f.get("minimum_notional_usd",1)) or 1))
    strength=.45*(score/100)+.10*min(1,streak/3)+.10*min(1,conf/4)+.10*min(1,burst/10)+.10*min(1,flow)+.15*min(1,(whale/floor)/4 if whale else 0)
    if depth<10_000: cap=.08;q=.20
    elif depth<50_000: cap=.10;q=.35
    elif depth<250_000: cap=.13;q=.50
    elif depth<1_000_000: cap=.15;q=.68
    elif depth<5_000_000: cap=.17;q=.82
    elif depth<20_000_000: cap=.20;q=.92
    else: cap=.20;q=1
    if day>=500_000_000 and depth>=20_000_000:cap=.20
    scorecap=.05 if score<80 else .08 if score<85 else .10 if score<90 else .13 if score<94 else .16 if score<97 else .20
    raw=.05+.15*max(0,min(1,strength));frac=.05+(raw-.05)*(.55+.45*q)
    return max(.05,min(.20,frac,cap,scorecap))

def restore_whales(c,prices):
    action="restore-all-whale-original-entry-v7"
    if c.execute("select 1 from operator_actions where action_id=%s",(action,)).fetchone():return []
    events=c.execute("""select distinct on (payload->>'symbol') id,recorded_at,payload from audit_journal
        where kind='whale_liq_trade_opened' and payload ? 'symbol'
        order by payload->>'symbol',recorded_at asc,id asc""").fetchall()
    out=[];reversed_total=0.0
    with c.transaction():
        for ev in events:
            p=dict(ev["payload"] or {});sym=str(p.get("symbol") or "").upper()
            ent=float(p.get("entry") or 0);side=int(p.get("side") or 0);lev=max(1,float(p.get("leverage") or 25))
            if not sym or ent<=0 or side not in (-1,1):continue
            f=dict(p.get("features") or {});f["score"]=float(p.get("score") or f.get("score") or 0);f["side"]=side
            oldm=max(0,float(p.get("margin") or 0));oldfrac=float(f.get("allocation_margin_fraction",0) or 0)
            eq_at_entry=(oldm/oldfrac) if oldm>0 and oldfrac>0 else float(c.execute("select equity from account_state where id=1").fetchone()["equity"])
            frac=liq_fraction(f);margin=max(.01,eq_at_entry*frac);notional=margin*lev
            cur=c.execute("select * from whale_liq_positions where symbol=%s for update",(sym,)).fetchone()
            closed=c.execute("select * from trade_history where strategy='whale_liquidation' and symbol=%s order by opened::timestamptz,id for update",(sym,)).fetchall()
            if cur:opened=cur["opened"];oe=float(cur["opened_epoch"])
            elif closed:opened=closed[0]["opened"];oe=epoch(opened)
            else:continue
            reached=None;reached_mark=None
            if cur:
                cf=dict(cur.get("features") or {});reached=cf.get("liquidation_level_reached_at");reached_mark=cf.get("liquidation_level_reached_mark")
            for t in closed:
                tf=dict(t.get("features") or {})
                if tf.get("liquidation_level_reached_at") and not reached:
                    reached=tf.get("liquidation_level_reached_at");reached_mark=tf.get("liquidation_level_reached_mark")
            liq=float(f.get("liquidation_price",0) or 0);victim=str(f.get("victim_side","")).lower();mark=float(prices.get(sym,0) or 0)
            if liq>0 and mark>0 and victim in ("long","short") and not reached:
                crossed=(victim=="long" and mark<=liq) or (victim=="short" and mark>=liq)
                if crossed:reached=now();reached_mark=mark
            f["allocation_margin_fraction"]=round(frac,6);f["allocation_policy"]="signal_momentum_liquidity_5_20_paper_v4"
            f["original_entry_preserved"]=ent;f["reconstructed_sizing_at_original_entry"]=True;f["historical_strategy_reconstruction"]=True
            f["restored_all_original_entries_v7"]=True
            if reached:
                f["liquidation_level_reached_at"]=reached;f["liquidation_level_reached_mark"]=reached_mark
                f["pre_liquidation_hold_active"]=False;f["post_liq_search_started_at"]=now()
                # Reconstructed position starts a brand-new post-liquidation local
                # search now; never reuse an earlier reconstructed path.
                risk={"peak":mark or ent,"history":[mark or ent],"last_price":mark or ent,
                      "local_search_min_samples":30,"post_liq_risk_reset_done":True}
            else:
                f["pre_liquidation_hold_active"]=True
                risk={"peak":ent,"history":[],"local_search_min_samples":30}
            if liq>0 and mark>0 and victim in ("long","short"):
                rem=((mark/liq)-1)*100 if victim=="long" else ((liq/mark)-1)*100
                f["remaining_to_liquidation_pct_at_restore"]=round(rem,6)
            rp=sum(float(t.get("pnl") or 0) for t in closed);reversed_total+=rp
            c.execute("delete from whale_liq_positions where symbol=%s",(sym,))
            c.execute("delete from whale_liq_trade_history where symbol=%s",(sym,))
            if closed:c.execute("delete from trade_history where id=any(%s)",([int(t["id"]) for t in closed],))
            c.execute("delete from position_snapshots where strategy='whale_liquidation' and symbol=%s",(sym,))
            c.execute("""insert into whale_liq_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,peak_roe,score,features,risk_state)
                values(%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s::jsonb,%s::jsonb)""",
                (sym,side,ent,notional,margin,lev,opened,oe,float(p.get("score") or 0),
                 json.dumps(f,default=str),json.dumps(risk,default=str)))
            out.append({"symbol":sym,"entry":ent,"margin_fraction":round(frac,4),"margin":round(margin,4),"score":float(p.get("score") or 0),"liq_reached":bool(reached),"reversed_pnl":round(rp,6)})
        if reversed_total:c.execute("update account_state set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s where id=1",(reversed_total,reversed_total,now()))
        payload={"count":len(out),"positions":out,"reversed_realized_pnl":reversed_total,"policy":"original_entry_5_20_then_liquidation_then_fresh_local"}
        c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",(action,now(),json.dumps(payload,default=str)))
        c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'whale_original_entries_restored',%s::jsonb)",(now(),json.dumps(payload,default=str)))
    return out

def restore_btc(c,prices):
    action="restore-btc-short-80524-v6"
    if c.execute("select 1 from operator_actions where action_id=%s",(action,)).fetchone():
        return None
    cur=c.execute("select * from open_positions where symbol='BTC' for update").fetchone()
    if cur:
        if abs(float(cur["entry"])-80524.5)>=.01:
            return None
        mark=float(prices.get("BTC",cur["entry"]) or cur["entry"])
        state=dict(cur.get("risk_state") or {})
        state.update({"peak":mark,"history":[mark],"last_price":mark,"local_search_min_samples":30})
        payload={"symbol":"BTC","entry":float(cur["entry"]),"opened":cur["opened"],
                 "margin":float(cur["margin"] or 0),"notional":float(cur["notional"] or 0),
                 "leverage":float(cur["leverage"] or 25),"already_open":True,
                 "fresh_local_window_reset":True,"restore_mark":mark,
                 "local_search_min_samples":30}
        with c.transaction():
            c.execute("update open_positions set risk_state=%s::jsonb where symbol='BTC'",
                      (json.dumps(state,default=str),))
            c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                      (action,now(),json.dumps(payload,default=str)))
            c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,'btc_short_restore_window_reset',%s::jsonb)",
                      (now(),cur.get("event_id"),json.dumps(payload,default=str)))
        return payload
    t=c.execute("""select * from trade_history where symbol='BTC' and side=-1 and abs(entry-80524.5)<.01
        order by opened::timestamptz desc limit 1 for update""").fetchone()
    if not t:return None
    s=c.execute("select * from position_snapshots where strategy='news' and symbol='BTC' and opened=%s order by ts::timestamptz desc limit 1",(t["opened"],)).fetchone()
    lev=max(1,float((s or {}).get("leverage") or 25))
    margin=max(.01,float((s or {}).get("margin") or 0))
    notional=max(.01,float((s or {}).get("notional") or margin*lev))
    pnl=float(t.get("pnl") or 0)
    mark=float(prices.get("BTC",t["entry"]) or t["entry"])
    state={"peak":mark,"history":[mark],"last_price":mark,"local_search_min_samples":30}
    payload={"symbol":"BTC","entry":float(t["entry"]),"opened":t["opened"],"margin":margin,
             "notional":notional,"leverage":lev,"reversed_realized_pnl":pnl,
             "restore_mark":mark,"local_search_min_samples":30}
    with c.transaction():
        c.execute("""insert into open_positions(symbol,side,entry,notional,opened,opened_epoch,headline,locked,stop,leverage,margin,event_id,risk_state)
            values('BTC',-1,%s,%s,%s,%s,%s,false,null,%s,%s,%s,%s::jsonb)""",
            (float(t["entry"]),notional,t["opened"],epoch(t["opened"]),t.get("headline"),lev,margin,t.get("event_id"),
             json.dumps(state,default=str)))
        c.execute("update account_state set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s where id=1",(pnl,pnl,now()))
        c.execute("delete from trade_history where id=%s",(t["id"],))
        c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                  (action,now(),json.dumps(payload,default=str)))
        c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,'btc_short_original_restored',%s::jsonb)",
                  (now(),t.get("event_id"),json.dumps(payload,default=str)))
    return payload

def main():
    try:prices=mids()
    except Exception as e:
        print(json.dumps({"kind":"restore_positions","ok":False,"error":"mids:"+str(e)[:160]}),flush=True);return
    with psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row,connect_timeout=8) as c:
        c.execute("create table if not exists operator_actions(action_id text primary key,completed_at text not null,payload jsonb not null)")
        whales=restore_whales(c,prices);btc=restore_btc(c,prices)
    print(json.dumps({"kind":"restore_positions","ok":True,"whales":whales,"btc":btc},default=str),flush=True)
if __name__=="__main__":main()
