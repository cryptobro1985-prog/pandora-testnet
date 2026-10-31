"""Strategy 1.3: pure confirmed-H1 swing. No flow/M1/M3/M5/MFE/re-entry filters."""
import copy,json,math,threading,time
from h1_structure import analyze as h1_analyze

SYMBOLS=("ZEC","BTC","ETH","BEAM","LSK")

class Strategy13:
 def __init__(self,pg,store,price_getter,price_snapshot,paper_pnl,fee,now_func):
  self.pg=pg;self.store=store;self.price_getter=price_getter;self.price_snapshot=price_snapshot
  self.paper_pnl=paper_pnl;self.fee=float(fee);self.now=now_func;self.lock=threading.RLock()
  self.positions={};self.h1={};self.equity=500.;self.realized=0.
 def ensure_schema(self,marker):
  q=(
   "create table if not exists strategy13_account_state(id integer primary key,equity double precision not null,realized_pnl double precision not null,started_at text not null,updated_at text not null)",
   "create table if not exists strategy13_positions(symbol text primary key,side integer not null,entry double precision not null,notional double precision not null,margin double precision not null,leverage double precision not null,opened text not null,opened_epoch double precision not null,signal_candle_time bigint,features jsonb not null default '{}'::jsonb)",
   "create table if not exists strategy13_trade_history(id bigserial primary key,opened text,closed text,symbol text,side integer,entry double precision,exit double precision,pnl double precision,reason text,margin double precision,notional double precision,leverage double precision,features jsonb not null default '{}'::jsonb)")
  with self.pg() as db:
   with db.transaction():
    for x in q:db.execute(x)
    db.execute("insert into strategy13_account_state values(1,500,0,%s,%s) on conflict(id) do nothing",(self.now(),self.now()))
    done=db.execute("select 1 from audit_journal where event_id=%s limit 1",(marker,)).fetchone()
    if not done:
     db.execute("truncate table strategy13_positions,strategy13_trade_history restart identity")
     stamp=self.now();db.execute("update strategy13_account_state set equity=500,realized_pnl=0,started_at=%s,updated_at=%s where id=1",(stamp,stamp))
     db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,'strategy13_reset',%s::jsonb)",(stamp,marker,json.dumps({"starting_equity":500,"logic":"pure_h1_local_to_opposite_local","symbols":SYMBOLS})))
  self.restore()
 def restore(self):
  with self.pg() as db:
   a=db.execute("select * from strategy13_account_state where id=1").fetchone();p=db.execute("select * from strategy13_positions").fetchall()
  with self.lock:self.equity=float(a["equity"]);self.realized=float(a["realized_pnl"]);self.positions={r["symbol"]:{**dict(r),"t":float(r["opened_epoch"])} for r in p}
 @staticmethod
 def confirmed(a):
  try:
   side=int(a.get("entry_side") or 0);sig=int(a.get("signal_candle_time") or 0)
   expected="LOCAL_HIGH" if side==-1 else "LOCAL_LOW" if side==1 else None
   return bool(expected and a.get("ready") and a.get("h1_direction_anchor") and a.get("anchor_confirmed") and not a.get("entry_blocked") and a.get("pivot_type")==expected and sig>0)
  except Exception:return False
 def _margin(self):
  with self.lock:eq=float(self.equity);ps=copy.deepcopy(self.positions)
  prices=self.price_snapshot();un=0.
  for s,p in ps.items():
   m=prices.get(s)
   if m:
    try:un+=self.paper_pnl(float(p["notional"]),float(p["entry"]),float(m),int(p["side"]),self.fee)
    except Exception:pass
  total=max(0.,eq+un);used=sum(float(p.get("margin") or 0) for p in ps.values());return total,max(0.,total-used)
 def _open(self,symbol,side,a):
  price=self.price_getter(symbol)
  if price is None:return False
  total,free=self._margin();margin=min(total*.20,free)
  if margin<.01:return False
  lev=25.;notional=margin*lev;opened=self.now();epoch=time.time();sig=int(a.get("signal_candle_time") or 0)
  f={"strategy_name":"Strategy 1.3","logic":"pure_h1_swing","entry_side":side,"pivot_type":a.get("pivot_type"),"pivot_price":a.get("pivot_price"),"signal_candle_time":sig,"reference_margin_fraction":.20,"reference_leverage":25.}
  with self.pg() as db:
   with db.transaction():
    self.store.fence(db)
    r=db.execute("insert into strategy13_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol",(symbol,side,price,notional,margin,lev,opened,epoch,sig,json.dumps(f))).fetchone()
    if not r:return False
  with self.lock:self.positions[symbol]={"symbol":symbol,"side":side,"entry":price,"notional":notional,"margin":margin,"leverage":lev,"opened":opened,"t":epoch,"signal_candle_time":sig,"features":f}
  return True
 def _close(self,symbol,mark,reason):
  with self.lock:p=copy.deepcopy(self.positions.get(symbol))
  if not p:return False
  pnl=self.paper_pnl(p["notional"],p["entry"],mark,p["side"],self.fee);closed=self.now()
  with self.pg() as db:
   with db.transaction():
    self.store.fence(db);r=db.execute("delete from strategy13_positions where symbol=%s and opened=%s returning symbol",(symbol,p["opened"])).fetchone()
    if not r:return False
    a=db.execute("update strategy13_account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1 returning equity,realized_pnl",(pnl,pnl,closed)).fetchone()
    db.execute("insert into strategy13_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",(p["opened"],closed,symbol,p["side"],p["entry"],mark,pnl,reason,p["margin"],p["notional"],p["leverage"],json.dumps(p.get("features") or {})))
  with self.lock:self.positions.pop(symbol,None);self.equity=float(a["equity"]);self.realized=float(a["realized_pnl"])
  return True
 def scan_h1(self,symbol,rows,now_ms):
  if symbol not in SYMBOLS:return
  a=h1_analyze(rows,now_ms,symbol)
  if not self.confirmed(a):return
  side=int(a["entry_side"]);sig=int(a["signal_candle_time"])
  with self.lock:prior=copy.deepcopy(self.h1.get(symbol));pos=copy.deepcopy(self.positions.get(symbol));self.h1[symbol]=copy.deepcopy(a)
  # Only a newly confirmed opposite H1 local closes/flips the swing.
  if pos and int(pos["side"])!=side and sig>int(pos.get("signal_candle_time") or 0):
   mark=self.price_getter(symbol)
   if mark is not None and self._close(symbol,float(mark),"opposite_confirmed_h1_local"):
    self._open(symbol,side,a)
  elif not pos:
   self._open(symbol,side,a)
 def snapshot(self):
  with self.lock:ps=copy.deepcopy(self.positions);eq=self.equity;real=self.realized;h=copy.deepcopy(self.h1)
  prices=self.price_snapshot();out=[];un=0.;allm=True
  for s,p in ps.items():
   m=prices.get(s);x=self.paper_pnl(p["notional"],p["entry"],m,p["side"],self.fee) if m else None;allm=allm and x is not None
   if x is not None:un+=x
   out.append({"symbol":s,"side":"LONG" if p["side"]>0 else "SHORT","entry":p["entry"],"mark":m,"unrealized_pnl":x,"margin_usd":p["margin"],"notional_usd":p["notional"],"leverage":p["leverage"],"opened":p["opened"]})
  return {"name":"Strategy 1.3","starting_equity":500.,"realized_equity":eq,"realized_pnl":real,"unrealized_pnl":un if allm else None,"total_equity":eq+un if allm else None,"open_positions":out,"h1":h,"symbols":list(SYMBOLS),"logic":"Local Low LONG -> next Local High; Local High SHORT -> next Local Low"}
