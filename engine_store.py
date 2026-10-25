"""Durable risk checkpoints and a fenced single-writer lease for paper mode."""
import datetime
import json
import uuid
from risk import risk_state, better

MIGRATIONS = (
    "ALTER TABLE open_positions ADD COLUMN IF NOT EXISTS risk_state jsonb NOT NULL DEFAULT '{}'::jsonb",
    "CREATE TABLE IF NOT EXISTS engine_lease (name text PRIMARY KEY, owner text NOT NULL, expires_at timestamptz NOT NULL, heartbeat_at timestamptz NOT NULL)",
)


class LeaseLost(RuntimeError):
    pass


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class EngineStore:
    def __init__(self, connect, fee=0.00045, reset=100.0):
        self.connect = connect
        self.owner = uuid.uuid4().hex
        self.fee, self.reset = fee, reset

    def migrate(self):
        with self.connect() as c:
            for sql in MIGRATIONS:
                c.execute(sql)

    def has_lease_record(self):
        with self.connect() as c:
            return c.execute("SELECT 1 FROM engine_lease WHERE name='paper'").fetchone() is not None

    def claim(self):
        with self.connect() as c:
            row = c.execute("""INSERT INTO engine_lease(name,owner,expires_at,heartbeat_at)
                VALUES('paper',%s,clock_timestamp()+interval '30 seconds',clock_timestamp())
                ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,
                  expires_at=excluded.expires_at,heartbeat_at=excluded.heartbeat_at
                WHERE engine_lease.owner=excluded.owner OR engine_lease.expires_at<clock_timestamp()
                RETURNING owner""", (self.owner,)).fetchone()
            return row is not None

    def fence(self, c):
        # Transactional row lock prevents ownership changing during a write.
        # Works with Neon pooled connections; no session advisory lock needed.
        row = c.execute("""SELECT owner FROM engine_lease WHERE name='paper'
            AND owner=%s AND expires_at>clock_timestamp() FOR UPDATE""", (self.owner,)).fetchone()
        if row is None:
            raise LeaseLost("paper engine lease lost")

    def release(self):
        with self.connect() as c:
            c.execute("UPDATE engine_lease SET expires_at=clock_timestamp() WHERE name='paper' AND owner=%s", (self.owner,))

    def load(self, recover_legacy=True):
        with self.connect() as c:
            account = c.execute("SELECT equity,realized_pnl FROM account_state WHERE id=1").fetchone()
            records = c.execute("SELECT * FROM open_positions").fetchall()
            positions = {}
            for row in records:
                lev = float(row["leverage"] or 25)
                pos = {"entry": float(row["entry"]), "side": int(row["side"]),
                       "notional": float(row["notional"]), "opened": row["opened"],
                       "t": float(row["opened_epoch"]), "headline": row["headline"] or "",
                       "locked": bool(row["locked"]), "stop": row["stop"], "leverage": lev,
                       "margin": float(row["margin"] or float(row["notional"])/lev),
                       "event_id": row.get("event_id")}
                state = row.get("risk_state") or {}
                pos.update({k: v for k, v in state.items() if k in
                            ("peak", "trail_armed", "trail_stop", "history", "last_price",
                             "last_evaluated_at", "last_exit_check")})
                if "peak" not in pos and recover_legacy:
                    prices = c.execute("""SELECT min(price) AS lo,max(price) AS hi
                        FROM market_context_snapshots WHERE symbol=%s AND ts>=%s""",
                        (row["symbol"], row["opened"])).fetchone()
                    extreme = prices["hi"] if pos["side"] > 0 else prices["lo"]
                    pos["peak"] = better(pos["side"], pos["entry"], extreme) if extreme else pos["entry"]
                    history = c.execute("""SELECT price FROM market_context_snapshots
                        WHERE symbol=%s AND ts>=%s ORDER BY ts DESC LIMIT 120""",
                        (row["symbol"], row["opened"])).fetchall()
                    pos["history"] = [float(x["price"]) for x in reversed(history)]
                pos.setdefault("peak", pos["entry"])
                pos.setdefault("history", [])
                positions[row["symbol"]] = pos
            return account, positions

    def save(self, symbol, position, create=False):
        p = position
        with self.connect() as c:
            with c.transaction():
                self.fence(c)
                if create:
                    row = c.execute("""INSERT INTO open_positions
                        (symbol,side,entry,notional,opened,opened_epoch,headline,locked,stop,leverage,margin,event_id,risk_state)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                        ON CONFLICT(symbol) DO NOTHING RETURNING symbol""",
                        (symbol,p["side"],p["entry"],p["notional"],p["opened"],p["t"],p["headline"],
                         p["locked"],p.get("stop"),p["leverage"],p["margin"],p.get("event_id"),json.dumps(risk_state(p)))).fetchone()
                    if row:
                        self._journal(c, "trade_opened", p.get("event_id"),
                            {"symbol": symbol,"side":p["side"],"entry":p["entry"],"notional":p["notional"],
                             "margin":p["margin"],"leverage":p["leverage"],"headline":p["headline"]})
                else:
                    # Never UPSERT a checkpoint: that could resurrect a closed trade.
                    row = c.execute("""UPDATE open_positions SET locked=%s,stop=%s,risk_state=%s::jsonb
                        WHERE symbol=%s AND opened=%s RETURNING symbol""",
                        (p["locked"],p.get("stop"),json.dumps(risk_state(p)),symbol,p["opened"])).fetchone()
                return row is not None

    def close(self, symbol, position, price, reason):
        with self.connect() as c:
            with c.transaction():
                self.fence(c)
                row = c.execute("DELETE FROM open_positions WHERE symbol=%s AND opened=%s RETURNING *",
                                (symbol,position["opened"])).fetchone()
                if row is None:
                    return None
                pnl = row["notional"] * (price/row["entry"]-1)*row["side"] - row["notional"]*self.fee*2
                closed = utcnow()
                account = c.execute("""UPDATE account_state SET
                    equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s WHERE id=1
                    RETURNING equity,realized_pnl""",(pnl,pnl,closed)).fetchone()
                if account is None:
                    raise RuntimeError("missing paper account")
                c.execute("""INSERT INTO trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,headline,event_id)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (row["opened"],closed,symbol,row["side"],row["entry"],price,pnl,reason,row["headline"],row.get("event_id")))
                self._journal(c,"trade_closed",row.get("event_id"),
                    {"symbol":symbol,"side":row["side"],"entry":row["entry"],"exit":price,
                     "notional":row["notional"],"pnl":pnl,"reason":reason,"opened":row["opened"],
                     "exit_check":position.get("last_exit_check"),"peak":position.get("peak")})
                return dict(account, pnl=pnl)

    @staticmethod
    def _journal(c, kind, event_id, payload):
        c.execute("INSERT INTO audit_journal(recorded_at,event_id,kind,payload) VALUES(%s,%s,%s,%s::jsonb)",
                  (utcnow(),event_id,kind,json.dumps(payload)))