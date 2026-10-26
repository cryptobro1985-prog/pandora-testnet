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

def purge_removed_strategy(c):
    action_id="remove-pump-dump-history-v1"
    if c.execute("select payload from operator_actions where action_id=%s",(action_id,)).fetchone():
        return {"already_done":True}
    with c.transaction():
        trades=c.execute("select pnl from trade_history where strategy='pump_dump' for update").fetchall()
        removed_pnl=sum(float(x.get("pnl") or 0) for x in trades)
        counts={
            "open_positions":int(c.execute("select count(*) as n from pump_positions").fetchone()["n"]),
            "closed_trades":len(trades),
            "strategy_history":int(c.execute("select count(*) as n from pump_trade_history").fetchone()["n"]),
            "signals":int(c.execute("select count(*) as n from pump_signal_journal").fetchone()["n"]),
            "learning":int(c.execute("select count(*) as n from decision_learning_log where strategy='pump_dump'").fetchone()["n"]),
        }
        c.execute("delete from pump_positions")
        c.execute("delete from pump_trade_history")
        c.execute("delete from pump_signal_journal")
        c.execute("delete from trade_history where strategy='pump_dump'")
        c.execute("delete from position_snapshots where strategy='pump_dump'")
        c.execute("delete from scanner_observations where module='pump_dump'")
        c.execute("delete from module_snapshots where module='PumpDumpScanner'")
        c.execute("delete from decision_learning_log where strategy='pump_dump'")
        c.execute("""delete from audit_journal
                     where kind ilike '%pump%'
                        or payload->>'strategy'='pump_dump'
                        or payload->>'engine'='pump_dump'""")
        c.execute("update learning_snapshots set payload=payload-'pump_score_buckets' where payload ? 'pump_score_buckets'")
        c.execute("""update account_capacity_snapshots
                     set pump_positions=0,total_positions=news_positions+whale_positions
                     where pump_positions<>0 or total_positions<>news_positions+whale_positions""")
        c.execute("alter table account_capacity_snapshots alter column pump_positions set default 0")
        if removed_pnl:
            c.execute("""update account_state
                         set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s
                         where id=1""",(removed_pnl,removed_pnl,now()))
        c.execute("""delete from operator_actions
                     where action_id<>%s and
                           (payload::text ilike '%pump_dump%' or payload::text ilike '%pump%')""",(action_id,))
        payload={"action":"removed_strategy_history","removed":counts,"reversed_realized_pnl":removed_pnl}
        c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                  (action_id,now(),json.dumps(payload,default=str)))
    return payload

def restore_whale_liquidations(c,mids):
    """One-shot repair of the current PAPER hard-test history.

    For each symbol, restore the *first* whale-liquidation trade that was closed
    by local-extreme logic before its liquidation target was confirmed. Any later
    whale trades in that same symbol are removed from performance history because
    they could not have opened while the corrected original position was still open.
    """
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
        and not (coalesce(t.features,'{}'::jsonb) ? 'liquidation_level_reached_at')
      order by t.symbol,t.closed::timestamptz asc""").fetchall()
    restored=[]
    for row in rows:
        sym=str(row["symbol"])
        action_id="restore-whale-all-v3-"+sym+"-"+str(row["id"])
        if c.execute("select 1 from operator_actions where action_id=%s",(action_id,)).fetchone():
            continue
        if c.execute("select 1 from whale_liq_positions where symbol=%s",(sym,)).fetchone():
            continue
        # Respect the unified-account invariant: do not create two simultaneous
        # strategy positions in the same symbol.
        if c.execute("""select 1 where exists(select 1 from open_positions where symbol=%s)
                       or exists(select 1 from pump_positions where symbol=%s)""",(sym,sym)).fetchone():
            continue

        mark=float(mids.get(sym,0) or 0)
        if mark<=0:
            continue
        features=dict(row.get("features") or {})
        liq=float(features.get("liquidation_price",0) or 0)
        victim=str(features.get("victim_side","")).lower()
        if liq<=0 or victim not in ("long","short"):
            continue

        # Best available proof that the original liquidation target printed after
        # the erroneous close: recorded PAPER snapshots on this symbol.
        cross=c.execute("""select ts,mark from position_snapshots
            where strategy='whale_liquidation' and symbol=%s
              and ts::timestamptz>%s::timestamptz
              and ((%s='long' and mark<=%s) or (%s='short' and mark>=%s))
            order by ts::timestamptz asc limit 1""",
            (sym,row["closed"],victim,liq,victim,liq)).fetchone()
        current_reached=(victim=="long" and mark<=liq) or (victim=="short" and mark>=liq)
        if cross or current_reached:
            features["liquidation_level_reached_at"]=str(cross["ts"]) if cross else now()
            features["liquidation_level_reached_mark"]=float(cross["mark"]) if cross else mark
            features["pre_liquidation_hold_active"]=False
        else:
            features["pre_liquidation_hold_active"]=True

        remaining=((mark/liq)-1.0)*100.0 if victim=="long" else ((liq/mark)-1.0)*100.0
        hold_limit=max(default_hold,min(1.50,float(features.get("dynamic_entry_distance_pct",default_hold) or default_hold)))

        # Later same-symbol whale trades belong to the branch created by the bad
        # early exit. Remove them from PAPER performance and reverse their PnL.
        later=c.execute("""select * from trade_history
            where strategy='whale_liquidation' and symbol=%s
              and opened::timestamptz>%s::timestamptz
            order by id for update""",(sym,row["closed"])).fetchall()
        reversed_pnl=float(row.get("pnl") or 0)+sum(float(x.get("pnl") or 0) for x in later)

        account=c.execute("select equity from account_state where id=1").fetchone()
        equity=max(0.01,float(account["equity"])-reversed_pnl)
        old_margin=max(0.0,float(row.get("margin") or 0))
        lev=max(1.0,float(row.get("leverage") or 25.0))
        stored_frac=float(features.get("allocation_margin_fraction",0) or 0)
        if not 0.05<=stored_frac<=0.20:
            stored_frac=0.05
        old_frac=(old_margin/equity) if equity>0 else 0.0
        target_frac=max(0.05,min(0.20,max(stored_frac,old_frac)))
        target_margin=equity*target_frac
        target_notional=target_margin*lev
        old_notional=max(0.0,float(row.get("notional") or (old_margin*lev)))
        entry=float(row["entry"])
        if old_notional>0 and target_notional>old_notional:
            added=target_notional-old_notional
            entry=(old_notional*entry+added*mark)/target_notional
        elif old_notional<=0:
            entry=mark

        features["restored_after_premature_local_exit"]=True
        features["restored_trade_id"]=int(row["id"])
        features["restored_all_history_v3"]=True
        features["remaining_to_liquidation_pct_at_restore"]=round(remaining,6)
        features["pre_liquidation_hold_limit_pct"]=round(hold_limit,6)
        features["allocation_margin_fraction"]=round(target_frac,4)
        features["allocation_policy"]="restored_pending_reconcile_5_20"
        opened_epoch=datetime.datetime.fromisoformat(str(row["opened"]).replace("Z","+00:00")).timestamp()

        with c.transaction():
            c.execute("""insert into whale_liq_positions
              (symbol,side,entry,notional,margin,leverage,opened,opened_epoch,peak_roe,score,features)
              values(%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s::jsonb)""",
              (sym,int(row["side"]),entry,target_notional,target_margin,lev,row["opened"],opened_epoch,
               float(row.get("score") or 0),json.dumps(features,default=str)))
            c.execute("""update account_state
                set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s where id=1""",
                (reversed_pnl,reversed_pnl,now()))
            ids=[int(row["id"])]+[int(x["id"]) for x in later]
            c.execute("delete from whale_liq_trade_history where symbol=%s and opened::timestamptz>=%s::timestamptz",
                      (sym,row["opened"]))
            c.execute("delete from trade_history where id=any(%s)",(ids,))
            # Remove the branch generated after the bad close; the original
            # pre-close snapshots remain as evidence of the real paper path.
            c.execute("""delete from position_snapshots
                where strategy='whale_liquidation' and symbol=%s
                  and ts::timestamptz>%s::timestamptz""",(sym,row["closed"]))
            payload={"strategy":"whale_liquidation","symbol":sym,
                     "restored_trade_id":int(row["id"]),
                     "removed_later_trade_ids":[int(x["id"]) for x in later],
                     "reversed_realized_pnl":reversed_pnl,
                     "mark":mark,"liquidation_price":liq,
                     "liquidation_already_reached":bool(cross or current_reached),
                     "liquidation_reached_at":features.get("liquidation_level_reached_at"),
                     "remaining_to_liquidation_pct":remaining,
                     "target_margin_fraction":target_frac,"target_margin":target_margin,
                     "policy":"hold_until_liquidation_then_local_extreme"}
            c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                      (action_id,now(),json.dumps(payload,default=str)))
            c.execute("""insert into audit_journal(recorded_at,event_id,kind,payload)
                         values(%s,null,'whale_liq_all_premature_history_restored',%s::jsonb)""",
                      (now(),json.dumps(payload,default=str)))
        restored.append({"symbol":sym,"trade_id":int(row["id"]),
                         "later_removed":[int(x["id"]) for x in later],
                         "liq_reached":bool(cross or current_reached),
                         "remaining_pct":round(remaining,4),
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
        removed_strategy=purge_removed_strategy(c)
        restored=restore_whale_liquidations(c,mids) if mids else []
    print(json.dumps({"kind":"operator_cleanup","removed_strategy":removed_strategy,"restored_whale_positions":restored,"ok":True}),flush=True)

if __name__=="__main__":
    main()
