"""Loss-visible, asynchronous recorder for accepted Bybit publicTrade executions.

Only accepted, deduplicated market observations are persisted. This recorder
never influences order sizing, direction, exits, fees, or the PAPER ledger.
Gaps/DB failure/queue overflow are explicitly flagged; no tick reconstruction.
"""
import collections
import datetime as dt
import json
import math
import os
import queue
import threading
import time

EXPERIMENT="PANDORA_FLOW_V2_400"

class RawFlowRecorder:
    def __init__(self, connect, *, capacity=30000, batch_size=250):
        self.connect=connect
        self.queue=queue.Queue(maxsize=max(1,int(capacity)))
        self.events=queue.Queue(maxsize=2000)
        self.batch_size=max(1,min(500,int(batch_size)))
        self.lock=threading.RLock()
        self.received=0
        self.stored=0
        self.duplicates=0
        self.dropped=0
        self.event_dropped=0
        self.event_stored=0
        self.db_errors=0
        self.last_error=None
        self.last_persist_epoch=None
        self.last_received_epoch=None
        self.last_drop_epoch=None
        self.schema_ready=False
        self.last_event_by_symbol={}
        self.last_persist_by_symbol={}
        self.last_db_check=0

    @staticmethod
    def _event_row(trade, received_at, worker, sequence=None):
        """Adapt an existing accepted RollingMarketData observation."""
        symbol=str(trade['coin'])
        ident=str(trade['tid'])
        ts=int(trade['time'])
        px=float(trade['px']); qty=float(trade['sz'])
        side=str(trade['side'])
        seq=None if sequence is None else int(sequence)
        if not symbol or not ident or side not in ('B','A') or ts<=0 or not all(
                math.isfinite(x) and x>0 for x in (px,qty,px*qty)):
            raise ValueError("invalid_accepted_trade")
        return (symbol,ident,ts,int(float(received_at)*1000),side,px,qty,px*qty,
                seq,str(worker))

    def migrate(self):
        # Migration is additive and cannot reset account, positions, or flow.
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pandora_flow_raw_trades(
                id bigserial PRIMARY KEY, symbol text NOT NULL, trade_id text NOT NULL,
                exchange_epoch_ms bigint NOT NULL, received_epoch_ms bigint NOT NULL,
                side char(1) NOT NULL CHECK(side in ('B','A')),
                price double precision NOT NULL, quantity double precision NOT NULL,
                notional double precision NOT NULL, sequence bigint, worker text NOT NULL,
                persisted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                UNIQUE(symbol,trade_id))""")
            db.execute("""CREATE INDEX IF NOT EXISTS pandora_flow_raw_exchange_idx
                ON pandora_flow_raw_trades(exchange_epoch_ms DESC)""")
            db.execute("""CREATE INDEX IF NOT EXISTS pandora_flow_raw_symbol_exchange_idx
                ON pandora_flow_raw_trades(symbol,exchange_epoch_ms DESC)""")
            db.execute("""CREATE TABLE IF NOT EXISTS pandora_flow_capture_events(
                id bigserial PRIMARY KEY, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
                event text NOT NULL, worker text, symbol text,
                details jsonb NOT NULL DEFAULT '{}'::jsonb)""")
            db.execute("""CREATE INDEX IF NOT EXISTS pandora_flow_capture_events_at_idx
                ON pandora_flow_capture_events(recorded_at DESC)""")
        with self.lock:self.schema_ready=True

    def ingest(self, rows, received_at, worker, sequences=None):
        """Non-blocking fast path; never synchronously writes PostgreSQL."""
        sequences=sequences or {}
        for trade in rows:
            try:
                key=(str(trade['coin']),str(trade['tid']),int(trade['time']))
                row=self._event_row(trade,received_at,worker,sequences.get(key))
            except (KeyError,TypeError,ValueError,OverflowError):
                self.notice("capture_invalid_accepted_row",worker,details={})
                continue
            with self.lock:
                self.received+=1
                self.last_received_epoch=float(received_at)
                self.last_event_by_symbol[row[0]]=row[2]
            try:self.queue.put_nowait(row)
            except queue.Full:
                with self.lock:
                    self.dropped+=1
                    self.last_drop_epoch=time.time()
                # Explicitly record lost coverage. DB may be unavailable.
                self.notice("capture_queue_overflow",worker,row[0],
                            dict(exchange_epoch_ms=row[2],trade_id=row[1]),quiet=True)

    def notice(self,event,worker=None,symbol=None,details=None,quiet=False):
        record=(str(event),str(worker) if worker is not None else None,
                str(symbol) if symbol is not None else None,
                json.dumps(details or {},default=str))
        try:self.events.put_nowait(record)
        except queue.Full:
            with self.lock:
                self.event_dropped+=1
                self.last_drop_epoch=time.time()

    def _persist(self, rows):
        # One INSERT for whole batch. Unique exchange IDs remove overlapping
        # websocket/reconnect deliveries, including across application restarts.
        size=len(rows)
        fields="symbol,trade_id,exchange_epoch_ms,received_epoch_ms,side,price,quantity,notional,sequence,worker"
        clause="("+",".join(["%s"]*10)+")"
        sql=("INSERT INTO pandora_flow_raw_trades("+fields+") VALUES "+
             ",".join([clause]*size)+" ON CONFLICT(symbol,trade_id) DO NOTHING RETURNING symbol,exchange_epoch_ms")
        with self.connect() as db:
            with db.transaction():
                stored=db.execute(sql,tuple(item for row in rows for item in row)).fetchall()
        with self.lock:
            self.stored+=len(stored)
            self.duplicates+=size-len(stored)
            self.last_persist_epoch=time.time()
            for r in stored:
                self.last_persist_by_symbol[r['symbol']]=max(
                    self.last_persist_by_symbol.get(r['symbol'],0),int(r['exchange_epoch_ms']))

    def _persist_events(self, rows):
        clause="(%s,%s,%s,%s::jsonb)"
        sql="INSERT INTO pandora_flow_capture_events(event,worker,symbol,details) VALUES "+",".join([clause]*len(rows))
        with self.connect() as db:
            db.execute(sql,tuple(item for row in rows for item in row))
        with self.lock:self.event_stored+=len(rows)

    def run(self,stop):
        pending=[]
        failed_events=[]
        while not stop.is_set() or pending or failed_events or not self.queue.empty() or not self.events.empty():
            try:
                if not pending:
                    try:pending.append(self.queue.get(timeout=.25))
                    except queue.Empty:pass
                while len(pending)<self.batch_size:
                    try:pending.append(self.queue.get_nowait())
                    except queue.Empty:break
                if pending:
                    self._persist(pending)
                    pending=[]
                if not failed_events:
                    while len(failed_events)<100:
                        try:failed_events.append(self.events.get_nowait())
                        except queue.Empty:break
                if failed_events:
                    self._persist_events(failed_events)
                    failed_events=[]
                with self.lock:self.last_error=None
            except Exception as exc:
                with self.lock:
                    self.db_errors+=1
                    self.last_error=type(exc).__name__+":"+str(exc)[:160]
                # Don't lose pending batch in transient failures. Backpressure
                # will be observable as queue overflow, not silently ignored.
                if stop.wait(1):
                    # Service termination is bounded; a failed final flush must
                    # be reported as unconfirmed durability, not success.
                    break

    def status(self):
        with self.lock:
            now=time.time()
            return dict(schema_ready=self.schema_ready,received=self.received,
                saved=self.stored,db_duplicates=self.duplicates,
                dropped=self.dropped,event_dropped=self.event_dropped,
                queued=self.queue.qsize(),event_queue=self.events.qsize(),
                capture_complete=(self.schema_ready and self.dropped==0
                    and self.event_dropped==0 and not self.last_error),
                last_error=self.last_error,db_errors=self.db_errors,
                last_persist_epoch=self.last_persist_epoch,
                persist_age_seconds=round(now-self.last_persist_epoch,2) if self.last_persist_epoch else None,
                last_receive_epoch=self.last_received_epoch,
                last_drop_epoch=self.last_drop_epoch,
                latest_by_symbol=dict(self.last_event_by_symbol),
                persisted_by_symbol=dict(self.last_persist_by_symbol),
                retention="append_only_no_auto_delete",
                note="Coverage only since recorder enabled; DB rows are accepted trades, not all exchange trades.")

def raw_trade_page(connect,*,symbol=None,before_id=None,limit=100):
    n=max(1,min(500,int(limit)))
    clauses=[];args=[]
    if symbol:
        if len(symbol)>32 or not symbol.replace("_","").isalnum():raise ValueError("invalid_symbol")
        clauses.append("symbol=%s");args.append(symbol.upper())
    if before_id is not None:
        value=int(before_id)
        if value<=0:raise ValueError("invalid_cursor")
        clauses.append("id<%s");args.append(value)
    where="WHERE "+" AND ".join(clauses) if clauses else ""
    with connect() as db:
        rows=db.execute("SELECT id,symbol,trade_id,exchange_epoch_ms,received_epoch_ms,"
          "side,price,quantity,notional,sequence,worker,persisted_at "
          "FROM pandora_flow_raw_trades "+where+" ORDER BY id DESC LIMIT %s",
          tuple(args+[n])).fetchall()
    return {"trades":rows,"next_before_id":rows[-1]["id"] if len(rows)==n else None,
            "limit":n,"coverage":"recorded_accepted_bybit_public_trades_only"}

def capture_event_page(connect,*,before_id=None,limit=100):
    n=max(1,min(200,int(limit)))
    where="WHERE id<%s" if before_id else ""
    params=(int(before_id),n) if before_id else (n,)
    with connect() as db:
        rows=db.execute("SELECT id,recorded_at,event,worker,symbol,details "
           "FROM pandora_flow_capture_events "+where+" ORDER BY id DESC LIMIT %s",params).fetchall()
    return {"events":rows,"next_before_id":rows[-1]["id"] if len(rows)==n else None}
