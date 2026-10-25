import os,json,datetime,urllib.request
import psycopg
from psycopg.rows import dict_row

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def hyperliquid_mids():
    req=urllib.request.Request(
        os.getenv("HYPERLIQUID_INFO_API","https://api.hyperliquid.xyz/info"),
        data=json.dumps({"type":"allMids"}).encode(),
        headers={"Content-Type":"application/json","User-Agent":"PANDORA-paper-restore/1"}
    )
    with urllib.request.urlopen(req,timeout=8) as resp:
        data=json.load(resp)
    return {str(k):float(v) for k,v in data.items()}

def purge_bch(c):
    symbol=(os.getenv("PANDORA_PURGE_PUMP_SYMBOL","BCH").strip().upper() or "BCH")
    action_id=(os.getenv("PANDORA_PURGE_ACTION_ID","exclude-bch-pump-2026-10-25-v2").strip()
               or "exclude-bch-pump-2026-10-25-v2")
    if c.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():
        return
    with c.transaction():
        opened=c.execute("select * from pump_positions where symbol=%s for update",(symbol,)).fetchone()
        trades=c.execute("""select * from trade_history
            where strategy='pump_dump' and symbol=%s
            order by id for update""",(symbol,)).fetchall()
        removed_pnl=sum(float(t.get("pnl") or 0) for t in trades)
        payload={"action":"exclude_bad_pump_test_all_history","symbol":symbol,
                 "removed_closed_trades":len(trades),"reversed_realized_pnl":removed_pnl,
                 "removed_open_position":dict(opened) if opened else None}
        c.execute("delete from pump_positions where symbol=%s",(symbol,))
        c.execute("delete from trade_history where strategy='pump_dump' and symbol=%s",(symbol,))
        c.execute("delete from pump_trade_history where symbol=%s",(symbol,))
        c.execute("delete from pump_signal_journal where symbol=%s",(symbol,))
        c.execute("delete from position_snapshots where strategy='pump_dump' and symbol=%s",(symbol,))
        if removed_pnl:
            c.execute("""update account_state
                set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s
                where id=1""",(removed_pnl,removed_pnl,now()))
        c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                  (action_id,now(),json.dumps(payload,default=str)))
        c.execute("""insert into audit_journal(recorded_at,event_id,kind,payload)
                     values(%s,null,'operator_trade_excluded',%s::jsonb)""",
                  (now(),json.dumps(payload,default=str)))

def restore_whale_liquidations(c,mids):
    lookback=max(0.25,min(24.0,float(os.getenv("LIQ_WHALE_RESTORE_LOOKBACK_HOURS","12"))))
    default_hold=max(0.10,min(1.50,float(os.getenv("LIQ_WHALE_HOLD_DISTANCE_PCT","0.75"))))
    rows=c.execute("""select distinct on (t.symbol)
        t.id,t.opened,t.closed,t.symbol,t.side,t.entry,t.exit,t.pnl,t.score,t.features,
        p.margin,p.notional,p.leverage
      from trade_history t
      left join lateral (
        select margin,notional,leverage from position_snapshots
        where strategy='whale_liquidation' and symbol=t.symbol
          and ts::timestamptz<=t.closed::timestamptz
        order by ts::timestamptz desc limit 1
      ) p on true
      where t.strategy='whale_liquidation'
        and t.reason='local_extreme_weakening'
        and t.closed::timestamptz >= now()-(%s * interval '1 hour')
      order by t.symbol,t.closed::timestamptz desc""",(lookback,)).fetchall()
    restored=[]
    for row in rows:
        sym=str(row["symbol"])
        mark=float(mids.get(sym,0) or 0)
        if mark<=0:
            continue
        if c.execute("""select 1 where exists(select 1 from open_positions where symbol=%s)
                       or exists(select 1 from pump_positions where symbol=%s)
                       or exists(select 1 from whale_liq_positions where symbol=%s)""",(sym,sym,sym)).fetchone():
            continue
        features=dict(row.get("features") or {})
        liq=float(features.get("liquidation_price",0) or 0)
        victim=str(features.get("victim_side","")).lower()
        if liq<=0 or victim not in ("long","short"):
            continue
        reached=(victim=="long" and mark<=liq) or (victim=="short" and mark>=liq)
        if reached:
            # The target already printed after the old close; reopening after the
            # liquidation event would manufacture a new entry, so keep it closed.
            continue
        remaining=((mark/liq)-1.0)*100.0 if victim=="long" else ((liq/mark)-1.0)*100.0
        if remaining<0:
            continue
        action_id="restore-whale-trade-v2-"+str(row["id"])
        if c.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():
            continue

        account=c.execute("select equity from account_state where id=1").fetchone()
        equity=max(0.01,float(account["equity"]))
        old_margin=max(0.0,float(row.get("margin") or 0))
        lev=max(1.0,float(row.get("leverage") or 25.0))
        old_notional=max(0.0,float(row.get("notional") or (old_margin*lev)))
        stored_frac=float(features.get("allocation_margin_fraction",0) or 0)
        if not 0.05<=stored_frac<=0.20:
            stored_frac=0.05
        old_frac=(old_margin/equity) if equity>0 else 0.0
        target_frac=max(0.05,min(0.20,max(stored_frac,old_frac)))
        target_margin=equity*target_frac
        target_notional=target_margin*lev
        entry=float(row["entry"])
        if old_notional>0 and target_notional>old_notional:
            added=target_notional-old_notional
            entry=(old_notional*entry+added*mark)/target_notional
        elif old_notional<=0:
            entry=mark

        hold_limit=max(default_hold,min(1.50,float(features.get("dynamic_entry_distance_pct",default_hold) or default_hold)))
        features["restored_after_premature_local_exit"]=True
        features["restored_trade_id"]=int(row["id"])
        features["remaining_to_liquidation_pct_at_restore"]=round(remaining,6)
        features["pre_liquidation_hold_limit_pct"]=round(hold_limit,6)
        features["pre_liquidation_hold_active"]=True
        features["allocation_margin_fraction"]=round(target_frac,4)
        # Force the live market loop to run the canonical 5-20% sizing function
        # again immediately; any extra size is filled at the then-current mark.
        features["allocation_policy"]="restored_pending_reconcile_5_20"
        opened_epoch=datetime.datetime.fromisoformat(str(row["opened"]).replace("Z","+00:00")).timestamp()
        with c.transaction():
            c.execute("""insert into whale_liq_positions
              (symbol,side,entry,notional,margin,leverage,opened,opened_epoch,peak_roe,score,features)
              values(%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s::jsonb)""",
              (sym,int(row["side"]),entry,target_notional,target_margin,lev,row["opened"],opened_epoch,
               float(row.get("score") or 0),json.dumps(features,default=str)))
            pnl=float(row.get("pnl") or 0)
            c.execute("""update account_state set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s
                         where id=1""",(pnl,pnl,now()))
            c.execute("delete from whale_liq_trade_history where symbol=%s and opened=%s and closed=%s",
                      (sym,row["opened"],row["closed"]))
            c.execute("delete from trade_history where id=%s",(row["id"],))
            payload={"strategy":"whale_liquidation","symbol":sym,"restored_trade_id":int(row["id"]),
                     "original_close":row["closed"],"reversed_realized_pnl":pnl,"mark":mark,
                     "liquidation_price":liq,"remaining_to_liquidation_pct":remaining,
                     "target_margin_fraction":target_frac,"target_margin":target_margin,
                     "policy":"hold_until_liquidation_then_local_extreme"}
            c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                      (action_id,now(),json.dumps(payload,default=str)))
            c.execute("""insert into audit_journal(recorded_at,event_id,kind,payload)
                         values(%s,null,'whale_liq_premature_exit_restored',%s::jsonb)""",
                      (now(),json.dumps(payload,default=str)))
        restored.append({"symbol":sym,"remaining_pct":round(remaining,4),"liq":liq,"mark":mark,
                         "margin_fraction":round(target_frac,4)})
    return restored

def main():
    mids={}
    try:
        mids=hyperliquid_mids()
    except Exception as exc:
        print(json.dumps({"kind":"operator_cleanup","warning":"mids_unavailable","error":str(exc)[:180]}),flush=True)
    with psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row,connect_timeout=8) as c:
        c.execute("create table if not exists operator_actions (action_id text primary key, completed_at text not null, payload jsonb not null)")
        purge_bch(c)
        restored=restore_whale_liquidations(c,mids) if mids else []
    print(json.dumps({"kind":"operator_cleanup","bch_cleanup":True,"restored_whale_positions":restored,"ok":True}),flush=True)

if __name__=="__main__":
    main()
