"""Live quotes and executed flow for the user's fixed comparison cohort."""
from collections import deque
import copy
import hashlib
import json
import math
import threading
import time
import websocket

FIXED_SYMBOLS=("ARIA","LYN","ESPORTS","1000CAT","SOPH")
EXPERIMENT="PANDORA_FIXED_FIVE_20261102"
class LiveScanner:
    def __init__(self, top=5, candidate_limit=30, freshness=15):
        self.top=5;self.candidate_limit=5;self.freshness=float(freshness)
        self.lock=threading.RLock();self.markets={};self.histories={}
        self.selected=list(FIXED_SYMBOLS);self.candidates=list(FIXED_SYMBOLS)
        self.states={s:"SELECTED" for s in FIXED_SYMBOLS};self.last_snapshot={}
        self.flow_samples={};self.pump_context=set()
        self.selected_since={};self.candidate_since={};self.fade_since={}
    def ingest(self, row, exchange_ms, received=None):
        if not isinstance(row,dict):return False
        try:
            received=time.time() if received is None else float(received)
            exchange_ms=float(exchange_ms)
        except (ValueError,TypeError,OverflowError):return False
        pair=str(row.get('symbol') or '')
        if not pair.endswith('USDT') or not -1<=received-exchange_ms/1000<=self.freshness:
            return False
        symbol=pair[:-4]
        if symbol not in FIXED_SYMBOLS:return False
        with self.lock:
            prior=self.markets.get(symbol,{})
            if float(exchange_ms)<prior.get('exchange_ms',0):return False
            merged={**prior,**row,'exchange_ms':float(exchange_ms),'received':received}
            try:
                price=float(merged.get('lastPrice') or 0)
                turnover=float(merged.get('turnover24h') or 0)
                if not math.isfinite(price+turnover) or price<=0 or turnover<=0:return False
                for field in ('price24hPcnt','bid1Price','ask1Price'):
                    if merged.get(field) not in (None,'') and not math.isfinite(float(merged[field])):return False
            except (ValueError,TypeError):return False
            merged['price_received']=received if row.get('lastPrice') not in (None,'') else prior.get('price_received',0)
            self.markets[symbol]=merged
            if row.get('lastPrice') in (None,''):return True
            history=self.histories.setdefault(symbol,deque(maxlen=600))
            # Bounded one-second samples, updated by WebSocket deltas.
            sample=(received,price,turnover)
            if history and int(history[-1][0])==int(received):history[-1]=sample
            else:history.append(sample)
            while history and received-history[0][0]>300:history.popleft()
        return True


    def rank(self,instruments,flow_getter,held=(),epoch=None):
        epoch=time.time() if epoch is None else float(epoch)
        with self.lock:
            rows=[]
            for slot,symbol in enumerate(FIXED_SYMBOLS,1):
                quote=self.markets.get(symbol,{})
                price=float(quote.get("lastPrice") or 0)
                age=epoch-float(quote.get("price_received") or 0)
                fresh=symbol in instruments and price>0 and 0<=age<=self.freshness
                flow=flow_getter(symbol,epoch) or {}
                window=(flow.get("windows") or {}).get("300",{})
                rows.append(dict(symbol=symbol,slot=slot,rank=None,last=price if price>0 else None,
                    price_received=quote.get("price_received"),eligible=fresh,
                    flow_fresh=bool(flow.get("trade_data_fresh")),
                    buy_volume=window.get("buy_volume"),sell_volume=window.get("sell_volume"),
                    change_24h_pct=float(quote.get("price24hPcnt") or 0)*100,
                    turnover_24h=float(quote.get("turnover24h") or 0),
                    pandora_win_score=0.,move="FIXED",selected=True,
                    reason="fixed_user_cohort" if fresh else "waiting_for_fresh_contract_quote"))
            ready=any(r["eligible"] for r in rows)
            snapshot=dict(at=epoch,experiment=EXPERIMENT,selected_symbols=list(FIXED_SYMBOLS),
                selected=rows,top_movers=rows,candidate_symbols=list(FIXED_SYMBOLS),
                retained_open_positions=sorted(set(held)-set(FIXED_SYMBOLS)),
                states={s:"SELECTED" for s in FIXED_SYMBOLS},events=[],
                selection_frozen=not ready,observations_ready=ready,
                selected_at=self.last_snapshot.get("selected_at",epoch),
                next_refresh_at=None,selection_interval_seconds=None,scan_seconds=1,
                missing_candidates=sum(not r["eligible"] for r in rows),
                basis="fixed_user_cohort_no_ranking_no_rotation")
            self.selected=list(FIXED_SYMBOLS);self.candidates=list(FIXED_SYMBOLS)
            self.last_snapshot=copy.deepcopy(snapshot)
            return snapshot

    def restore(self,snapshot):
        with self.lock:
            self.last_snapshot={}
            self.selected=list(FIXED_SYMBOLS);self.candidates=list(FIXED_SYMBOLS)
            self.states={s:"SELECTED" for s in FIXED_SYMBOLS}

def ticker_worker(scanner, stop, instruments_getter, report, shard=0, shards=4,
                  url='wss://stream.bybit.com/v5/public/linear'):
    """Market-wide ticker delta stream; metadata is the subscription universe."""
    backoff=1
    while not stop.is_set():
        ws=None
        try:
            universe=set(instruments_getter()) & set(FIXED_SYMBOLS)
            selected={s for s in universe if int(hashlib.sha1(s.encode()).hexdigest()[:8],16)%shards==shard}
            if not selected:stop.wait(1);continue
            ws=websocket.create_connection(url,timeout=8,enable_multithread=True);ws.settimeout(2)
            pending=set();number=0
            for offset in range(0,len(selected),10):
                number+=1;req=f'scanner-{shard}-{number}';pending.add(req)
                ws.send(json.dumps(dict(op='subscribe',args=['tickers.'+s+'USDT' for s in sorted(selected)[offset:offset+10]],req_id=req)))
                if stop.wait(.05):break
            last=time.time();ping=last;started=last;refresh=last
            while not stop.is_set():
                stamp=time.time()
                if stamp-ping>=20:ws.send(json.dumps({'op':'ping'}));ping=stamp
                if stamp-last>30 or (pending and stamp-started>15):raise RuntimeError('scanner_stale_or_ack_timeout')
                if stamp-refresh>60:
                    refresh=stamp
                    if set(instruments_getter()) & set(FIXED_SYMBOLS)!=universe:break
                try:raw=ws.recv()
                except websocket.WebSocketTimeoutException:continue
                if not raw:raise RuntimeError('scanner_socket_closed')
                message=json.loads(raw);last=time.time()
                if message.get('op')=='subscribe':
                    if message.get('success') is not True:raise RuntimeError('scanner_subscription_rejected')
                    pending.discard(message.get('req_id'))
                if message.get('topic','').startswith('tickers.'):
                    row=message.get('data') or {}
                    if isinstance(row,dict):scanner.ingest(row,message.get('ts',0),last)
                report(dict(ok=not pending,connected=True,pending=len(pending),symbols=len(selected),last_received=last))
                backoff=1
        except Exception as exc:
            report(dict(ok=False,connected=False,error=type(exc).__name__+':'+str(exc)[:160]))
        finally:
            if ws is not None:
                try:ws.close()
                except Exception:pass
        stop.wait(backoff);backoff=min(30,backoff*2)
