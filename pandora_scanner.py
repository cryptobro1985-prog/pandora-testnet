"""Streaming all-market USDT perpetual ranking and deterministic top-five rotation."""
from collections import deque
from bisect import bisect_left
import copy
import hashlib
import json
import math
import threading
import time

import websocket


class LiveScanner:
    def __init__(self, top=5, candidate_limit=30, freshness=15):
        self.top=top; self.candidate_limit=candidate_limit; self.freshness=freshness
        self.lock=threading.RLock(); self.markets={}; self.histories={}; self.selected=[]
        self.candidates=[]; self.states={}; self.last_snapshot={}

    def ingest(self, row, exchange_ms, received=None):
        received=time.time() if received is None else float(received)
        pair=str(row.get('symbol') or '')
        if not pair.endswith('USDT') or not -1<=received-float(exchange_ms)/1000<=self.freshness:
            return False
        symbol=pair[:-4]
        with self.lock:
            prior=self.markets.get(symbol,{})
            if float(exchange_ms)<prior.get('exchange_ms',0):return False
            merged={**prior,**row,'exchange_ms':float(exchange_ms),'received':received}
            try:
                price=float(merged.get('lastPrice') or 0)
                turnover=float(merged.get('turnover24h') or 0)
                if not math.isfinite(price+turnover) or price<=0 or turnover<=0:return False
            except (ValueError,TypeError):return False
            self.markets[symbol]=merged
            history=self.histories.setdefault(symbol,deque(maxlen=600))
            # Bounded one-second samples, updated by WebSocket deltas.
            sample=(received,price,turnover)
            if history and int(history[-1][0])==int(received):history[-1]=sample
            else:history.append(sample)
            while history and received-history[0][0]>300:history.popleft()
        return True

    def rank(self, instruments, flow_getter, held=(), epoch=None):
        epoch=time.time() if epoch is None else float(epoch)
        with self.lock:
            markets=copy.deepcopy(self.markets)
            histories={s:list(h) for s,h in self.histories.items()}
            previous=list(self.selected)
        rows=[]
        for symbol,row in markets.items():
            if symbol not in instruments or not 0<=epoch-row['received']<=self.freshness:continue
            samples=histories[symbol]
            last=float(row['lastPrice']);turn=float(row['turnover24h'])
            change=float(row.get('price24hPcnt') or 0)
            def movement(seconds):
                old=next((x for x in reversed(samples) if epoch-x[0]>=seconds),samples[0])
                return last/old[1]-1
            short,minute=movement(15),movement(60)
            # Cold bootstrap uses positive daily change only until short samples exist.
            bootstrapping=epoch-samples[0][0]<15
            if not (short>0 or minute>0 or (bootstrapping and change>0)):continue
            flow=flow_getter(symbol,epoch) or {}
            windows=flow.get('windows') or {}; fast=windows.get('15',{})
            medium=windows.get('60',{})
            spread=None
            try:
                bid=float(row.get('bid1Price') or 0);ask=float(row.get('ask1Price') or 0)
                if bid>0 and ask>=bid:spread=(ask-bid)/last
            except (ValueError,TypeError):pass
            prices=[x[1] for x in samples]
            volatility=(max(prices)-min(prices))/last if prices else 0
            consistency=sum(b[1]>a[1] for a,b in zip(samples,samples[1:]))/max(1,len(samples)-1)
            elapsed=max(.001,samples[-1][0]-samples[0][0])
            turnover_velocity=max(0.,turn-samples[0][2])/elapsed
            rows.append(dict(symbol=symbol,last=last,short_return=short,minute_return=minute,
                acceleration=short-minute/4,volatility=volatility,turnover_24h=turn,
                turnover_per_minute=turnover_velocity*60,executed_volume=medium.get('buy_volume',0)+medium.get('sell_volume',0),
                volume_velocity=fast.get('volume_velocity',turnover_velocity),
                volume_change=fast.get('volume_change',0),buy_volume=fast.get('buy_volume',0),
                sell_volume=fast.get('sell_volume',0),trade_count=fast.get('trade_count',0),
                trade_velocity=fast.get('trade_velocity',0),persistence=consistency,
                liquidity=1/(1+spread) if spread is not None else 0,
                spread=spread,flow_fresh=bool(flow.get('trade_data_fresh')),
                change_24h_pct=change*100,scan_return_pct=short*100,
                range_24h_pct=volatility*100,move='PUMP',bootstrap=bootstrapping))
        # Equal cross-sectional percentile ranks: no fitted weights or indicators.
        fields=('short_return','acceleration','volatility','turnover_per_minute','turnover_24h',
                'executed_volume','volume_velocity','volume_change','buy_volume',
                'trade_count','trade_velocity','persistence','liquidity')
        for row in rows:row['pandora_win_score']=0.
        for field in fields:
            values=sorted(row[field] for row in rows)
            for row in rows:
                row['pandora_win_score']+=bisect_left(values,row[field])/max(1,len(rows)-1)/len(fields)
        rows.sort(key=lambda r:(-r['pandora_win_score'],r['symbol']))
        for rank,row in enumerate(rows,1):row['rank']=rank
        selected=rows[:self.top];symbols=[r['symbol'] for r in selected]
        events=[]
        with self.lock:
            for symbol in previous:
                if symbol not in symbols:
                    state='FADING' if symbol in held else 'ROTATE_OUT'
                    self.states[symbol]=state
                    events.append(dict(action='TOKEN_ROTATED',symbol=symbol,state=state,reason='stronger_live_candidate_or_faded_activity'))
            for symbol,state in list(self.states.items()):
                if state=='FADING' and symbol not in held and symbol not in symbols:
                    self.states[symbol]='ROTATE_OUT'
                    events.append(dict(action='ROTATE_OUT',symbol=symbol,state='ROTATE_OUT',reason='retained_position_closed'))
            for symbol in symbols:
                self.states[symbol]='SELECTED'
                if symbol not in previous:events.append(dict(action='TOKEN_SELECTED',symbol=symbol,reason='live_cross_sectional_top_five'))
            self.selected=symbols;self.candidates=[r['symbol'] for r in rows[:self.candidate_limit]]
            self.last_snapshot=dict(at=epoch,selected_symbols=symbols,selected=selected,
                top_movers=rows[:self.candidate_limit],candidate_symbols=list(self.candidates),
                retained_open_positions=[s for s in held if s not in symbols],
                states=dict(self.states),events=events,selection_frozen=False,scan_seconds=1,
                basis='streaming_tick_activity_and_executed_volume_equal_percentile_ranks')
            return copy.deepcopy(self.last_snapshot)

    def restore(self,snapshot):
        # Restored ranking is visible, but cannot create fresh live observations.
        with self.lock:
            self.last_snapshot=copy.deepcopy(snapshot or {})
            self.selected=list(self.last_snapshot.get('selected_symbols') or [])
            self.states=dict(self.last_snapshot.get('states') or {})


def ticker_worker(scanner, stop, instruments_getter, report, shard=0, shards=4,
                  url='wss://stream.bybit.com/v5/public/linear'):
    """Market-wide ticker delta stream; metadata is the subscription universe."""
    backoff=1
    while not stop.is_set():
        ws=None
        try:
            universe=set(instruments_getter())
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
                    if set(instruments_getter())!=universe:break
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
