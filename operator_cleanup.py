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

def purge_whale_v2(c):
    action_id="remove-whale-v2-after-ptv-unification-v1"
    if c.execute("select payload from operator_actions where action_id=%s",(action_id,)).fetchone():
        return {"already_done":True}
    with c.transaction():
        pnl_row=c.execute("""select count(*) as n,coalesce(sum(pnl),0) as pnl
                             from trade_history where strategy='whale_liquidation_v2'""").fetchone()
        removed_trades=int(pnl_row["n"] or 0)
        removed_pnl=float(pnl_row["pnl"] or 0)
        open_count=0
        try:
            open_count=int(c.execute("select count(*) as n from whale_liq_v2_positions").fetchone()["n"] or 0)
        except Exception:
            open_count=0
        c.execute("delete from trade_history where strategy='whale_liquidation_v2'")
        c.execute("delete from position_snapshots where strategy='whale_liquidation_v2'")
        c.execute("delete from scanner_observations where module='whale_liquidation_v2'")
        c.execute("delete from module_snapshots where module='WhaleLiquidationV2'")
        c.execute("delete from decision_learning_log where strategy='whale_liquidation_v2'")
        if removed_pnl:
            c.execute("""update account_state
                         set equity=equity-%s,realized_pnl=realized_pnl-%s,updated_at=%s
                         where id=1""",(removed_pnl,removed_pnl,now()))
        c.execute("drop table if exists whale_liq_v2_signal_journal")
        c.execute("drop table if exists whale_liq_v2_trade_history")
        c.execute("drop table if exists whale_liq_v2_positions")
        c.execute("drop table if exists whale_liq_v2_learning_snapshots")
        c.execute("drop table if exists whale_liq_v2_account_state")
        payload={"action":"remove_whale_v2","replacement":"price_to_value_liquidation",
                 "removed_open_positions":open_count,"removed_closed_trades":removed_trades,
                 "reversed_realized_pnl":removed_pnl}
        c.execute("insert into operator_actions(action_id,completed_at,payload) values(%s,%s,%s::jsonb)",
                  (action_id,now(),json.dumps(payload,default=str)))
    return payload

def main():
    with psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row,connect_timeout=8) as c:
        c.execute("create table if not exists operator_actions (action_id text primary key, completed_at text not null, payload jsonb not null)")
        purge_bch(c)
        removed_v2=purge_whale_v2(c)
    print(json.dumps({"kind":"operator_cleanup","bch_cleanup":True,"whale_v2_cleanup":removed_v2,"ok":True}),flush=True)

if __name__=="__main__":
    main()
