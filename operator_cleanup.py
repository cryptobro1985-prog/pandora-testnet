import os,json,datetime
import psycopg
from psycopg.rows import dict_row

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def main():
    symbol=os.getenv("PANDORA_PURGE_PUMP_SYMBOL","").strip().upper()
    action_id=os.getenv("PANDORA_PURGE_ACTION_ID","").strip()
    if not symbol or not action_id:
        return
    with psycopg.connect(os.environ["DATABASE_URL"],autocommit=True,row_factory=dict_row,connect_timeout=8) as c:
        c.execute("create table if not exists operator_actions (action_id text primary key, completed_at text not null, payload jsonb not null)")
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
    print(json.dumps({"kind":"operator_cleanup","action_id":action_id,"symbol":symbol,"ok":True}),flush=True)

if __name__=="__main__":
    main()
