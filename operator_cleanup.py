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
    action_id=(os.getenv("PANDORA_PURGE_ACTION_ID","exclude-bch-pump-2026-10-25-v1").strip()
               or "exclude-bch-pump-2026-10-25-v1")
    if c.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():
        return
    with c.transaction():
        opened=c.execute("select * from pump_positions where symbol=%s for update",(symbol,)).fetchone()
        payload={"action":"exclude_bad_pump_test","symbol":symbol,"mode":"open" if opened else "closed"}
        if opened:
            payload["removed_open_position"]=dict(opened)
            c.execute("delete from pump_positions where symbol=%s",(symbol,))
            c.execute("delete from position_snapshots where strategy='pump_dump' and symbol=%s and ts>=%s",(symbol,opened["opened"]))
        else:
            trade=c.execute("""select * from trade_history
                where strategy='pump_dump' and symbol=%s
                  and closed::timestamptz >= now()-interval '6 hours'
                order by id desc limit 1 for update""",(symbol,)).fetchone()
            if trade:
                pnl=float(trade.get("pnl") or 0)
                payload["removed_closed_trade"]=dict(trade)
                c.execute("update account_state set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s where id=1",
                          (pnl,pnl,now()))
                c.execute("delete from trade_history where id=%s",(trade["id"],))
                c.execute("delete from pump_trade_history where symbol=%s and opened=%s and closed=%s",
                          (symbol,trade["opened"],trade["closed"]))
                c.execute("delete from position_snapshots where strategy='pump_dump' and symbol=%s and ts>=%s and ts<=%s",
                          (symbol,trade["opened"],trade["closed"]))
            else:
                payload["result"]="no_recent_bch_pump_trade_found"
        c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                  (action_id,now(),json.dumps(payload,default=str)))
        c.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,'operator_trade_excluded',%s::jsonb)",
                  (now(),json.dumps(payload,default=str)))

def restore_whale_liquidations(c,mids):
    lookback=max(0.25,min(12.0,float(os.getenv("LIQ_WHALE_RESTORE_LOOKBACK_HOURS","4"))))
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
            continue
        remaining=((mark/liq)-1.0)*100.0 if victim=="long" else ((liq/mark)-1.0)*100.0
        dynamic=float(features.get("dynamic_entry_distance_pct",default_hold) or default_hold)
        hold_limit=max(default_hold,min(1.50,dynamic))
        if remaining<0 or remaining>hold_limit:
            continue
        action_id="restore-whale-trade-"+str(row["id"])
        if c.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():
            continue
        margin=float(row.get("margin") or 0)
        lev=float(row.get("leverage") or 25.0)
        notional=float(row.get("notional") or 0)
        if margin<=0:
            account=c.execute("select equity from account_state where id=1").fetchone()
            frac=max(0.05,min(0.20,float(features.get("allocation_margin_fraction",0.05) or 0.05)))
            margin=max(0.01,float(account["equity"])*frac)
        if notional<=0:
            notional=margin*lev
        features["restored_after_premature_local_exit"]=True
        features["restored_trade_id"]=int(row["id"])
        features["remaining_to_liquidation_pct_at_restore"]=round(remaining,6)
        features["pre_liquidation_hold_limit_pct"]=round(hold_limit,6)
        features["pre_liquidation_hold_active"]=True
        opened_epoch=datetime.datetime.fromisoformat(str(row["opened"]).replace("Z","+00:00")).timestamp()
        with c.transaction():
            c.execute("""insert into whale_liq_positions
              (symbol,side,entry,notional,margin,leverage,opened,opened_epoch,peak_roe,score,features)
              values(%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s::jsonb)""",
              (sym,int(row["side"]),float(row["entry"]),notional,margin,lev,row["opened"],opened_epoch,
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
                     "hold_limit_pct":hold_limit}
            c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                      (action_id,now(),json.dumps(payload,default=str)))
            c.execute("""insert into audit_journal(recorded_at,event_id,kind,payload)
                         values(%s,null,'whale_liq_premature_exit_restored',%s::jsonb)""",
                      (now(),json.dumps(payload,default=str)))
        restored.append({"symbol":sym,"remaining_pct":round(remaining,4),"liq":liq,"mark":mark})
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
