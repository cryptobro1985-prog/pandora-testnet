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
from pandora_flow_v2_live import enabled as v2_enabled, MIN_TURNOVER_24H, EXPERIMENT as ACTIVE_FLOW_EXPERIMENT


class LiveScanner:
    def __init__(self, top=5, candidate_limit=30, freshness=15):
        if not 1<=int(top)<=5 or not int(top)<=int(candidate_limit)<=128 or not 0<float(freshness)<=60:raise ValueError('invalid scanner bounds')
        self.top=int(top); self.candidate_limit=int(candidate_limit); self.freshness=float(freshness)
        self.lock=threading.RLock(); self.markets={}; self.histories={}; self.selected=[]
        self.candidates=[]; self.states={}; self.last_snapshot={}; self.flow_samples={}; self.pump_context=set()
        self.selected_since={};self.candidate_since={};self.fade_since={}

    @staticmethod
    def _stable_top(rows, previous, limit, since, epoch):
        """Warm actual tape before marginal rank noise churns subscriptions.

        A clearly stronger challenger can replace a warmed incumbent. Invalid
        tickers/faded rows are excluded by the caller, even during warmup.
        """
        by_symbol={row['symbol']:row for row in rows}
        chosen=[by_symbol[s] for s in previous if s in by_symbol][:limit]
        for challenger in rows:
            if any(row['symbol']==challenger['symbol'] for row in chosen):continue
            if len(chosen)<limit:chosen.append(challenger);continue
            replaceable=[row for row in chosen if epoch-since.get(row['symbol'],epoch)>=15]
            if not replaceable:continue
            weakest=min(replaceable,key=lambda row:(row['pandora_win_score'],row['symbol']))
            if challenger['pandora_win_score']>weakest['pandora_win_score']+.05:
                chosen.remove(weakest);chosen.append(challenger)
        return sorted(chosen,key=lambda row:(-row['pandora_win_score'],row['symbol']))

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

    def _rank_v2(self,instruments,held,epoch):
        """Hourly rising Bybit USDT perpetual TOP-5; no intrahour rotations."""
        with self.lock:
            saved=copy.deepcopy(self.last_snapshot or {})
            markets=copy.deepcopy(self.markets)
            prior=list(saved.get("selected_symbols") or [])
            refresh=float(saved.get("next_refresh_at") or 0)
            if refresh and epoch<refresh and saved.get("experiment")==ACTIVE_FLOW_EXPERIMENT:
                # A restart can freeze a restored hourly selection before
                # ticker subscriptions are fresh. Recover readiness without
                # rotating the selected five before their scheduled refresh.
                verified=bool(prior) and all(
                    sym in instruments and sym in markets and
                    0<=epoch-float(markets[sym].get("price_received") or 0)<=self.freshness
                    for sym in prior)
                saved.update(at=epoch,events=[],
                    selection_frozen=not verified,
                    observations_ready=verified,
                    retained_open_positions=sorted(set(held)-set(prior)))
                self.selected=prior
                self.last_snapshot=copy.deepcopy(saved)
                return saved
        fresh=[(s,r) for s,r in markets.items() if s in instruments and
               0<=epoch-float(r.get("price_received") or 0)<=self.freshness]
        if not fresh:
            frozen={**saved,"at":epoch,"events":[],"selection_frozen":True,
                "observations_ready":False,"selected_symbols":prior,
                "retained_open_positions":sorted(set(held)-set(prior)),
                "reason":"fresh_bybit_tickers_required_for_hourly_top5",
                "experiment":ACTIVE_FLOW_EXPERIMENT}
            with self.lock:self.last_snapshot=copy.deepcopy(frozen)
            return frozen
        rows=[]
        for symbol,row in fresh:
            try:
                if float(row.get("turnover24h") or 0)<MIN_TURNOVER_24H:continue
                change=float(row.get("price24hPcnt") or 0)
                price=float(row.get("lastPrice") or 0)
                turnover=float(row.get("turnover24h") or 0)
                if not math.isfinite(change+price+turnover) or price<=0 or change<=0:continue
            except (TypeError,ValueError,OverflowError):continue
            rows.append(dict(symbol=symbol,rank=0,last=price,
               price_received=row.get("price_received"),change_24h_pct=change*100,
               turnover_24h=turnover,turnover_per_minute=0,move="PUMP",
               pandora_win_score=change,flow_fresh=False,eligible=True))
        rows.sort(key=lambda r:(-r["change_24h_pct"],-r["turnover_24h"],r["symbol"]))
        for i,r in enumerate(rows):r["rank"]=i+1
        selected=rows[:self.top];symbols=[r["symbol"] for r in selected]
        events=[]
        for symbol in prior:
            if symbol not in symbols:
                events.append(dict(action="TOKEN_ROTATED",symbol=symbol,
                                   state="FADING" if symbol in held else "ROTATE_OUT",
                                   reason="hourly_top5_refresh"))
        for symbol in symbols:
            if symbol not in prior:events.append(dict(action="TOKEN_SELECTED",symbol=symbol,
                                     reason="hourly_rising_top5_min_1m_turnover"))
        snapshot=dict(at=epoch,selected_at=epoch,next_refresh_at=epoch+3600,
            experiment=ACTIVE_FLOW_EXPERIMENT,selected_symbols=symbols,
            selected=selected,top_movers=rows[:self.candidate_limit],
            candidate_symbols=[r["symbol"] for r in rows[:self.candidate_limit]],
            retained_open_positions=sorted(set(held)-set(symbols)),
            states={s:"SELECTED" for s in symbols},events=events,
            selection_frozen=False,observations_ready=True,scan_seconds=3600,
            min_turnover_24h_usdt=MIN_TURNOVER_24H,
            missing_candidates=max(0,self.top-len(symbols)),
            basis="hourly_bybit_24h_positive_price_change_and_min_1m_usdt_turnover")
        with self.lock:
            self.selected=symbols
            self.candidates=snapshot["candidate_symbols"]
            self.states=snapshot["states"]
            self.last_snapshot=copy.deepcopy(snapshot)
        return snapshot

    def rank(self, instruments, flow_getter, held=(), epoch=None):
        epoch=time.time() if epoch is None else float(epoch)
        if v2_enabled():return self._rank_v2(instruments,held,epoch)
        with self.lock:
            markets=copy.deepcopy(self.markets)
            histories={s:list(h) for s,h in self.histories.items()}
            previous=list(self.selected)
            previous_candidates=list(self.candidates)
            retained_snapshot=copy.deepcopy(self.last_snapshot)
            prior_flow=copy.deepcopy(self.flow_samples)
            pump_context=set(self.pump_context)|set(previous)|set(held)
        fresh={s for s,r in markets.items() if s in instruments and 0<=epoch-r.get('price_received',0)<=self.freshness and s in histories}
        if not instruments or not fresh:
            # Absence of restored observations is an outage, not proof of fading.
            snapshot={**retained_snapshot,'at':epoch,'selected_symbols':previous,
                'selected':retained_snapshot.get('selected',[]),'events':[],
                'selection_frozen':True,'observations_ready':False,
                'reason':'waiting_for_current_universe_and_selected_tickers',
                'states':dict(self.states),'candidate_symbols':retained_snapshot.get('candidate_symbols',[]),
                'retained_open_positions':[s for s in held if s not in previous]}
            with self.lock:self.last_snapshot=copy.deepcopy(snapshot)
            return snapshot
        rows=[];flow_samples={}
        for symbol,row in markets.items():
            if symbol not in instruments or not 0<=epoch-row.get('price_received',0)<=self.freshness or symbol not in histories:continue
            samples=histories[symbol]
            last=float(row['lastPrice']);turn=float(row['turnover24h'])
            change=float(row.get('price24hPcnt') or 0)
            def movement(seconds):
                old=next((x for x in reversed(samples) if epoch-x[0]>=seconds),samples[0])
                return last/old[1]-1
            short,minute=movement(15),movement(60)
            # A correction in a previously active pump remains interesting for
            # SHORT while executed participation persists. A stopped tape does
            # not stay selected merely because its old daily return is positive.
            bootstrapping=epoch-samples[0][0]<15
            raw_flow=flow_getter(symbol,epoch) or {}
            prior=prior_flow.get(symbol,{})
            known=bool(prior.get('known') or raw_flow.get('latest_trade_epoch') is not None or raw_flow.get('windows'))
            flow=raw_flow if raw_flow.get('trade_data_fresh') else {}
            windows=flow.get('windows') or {}; fast=windows.get('15',{})
            rapid=windows.get('5',fast);medium=windows.get('60',{})
            recent_prices=[x[1] for x in samples if epoch-x[0]<=15]
            short_volatility=(max(recent_prices)-min(recent_prices))/last if recent_prices else 0.
            rapid_volume=float(rapid.get('buy_volume',0))+float(rapid.get('sell_volume',0))
            quiet=bool(windows and (rapid_volume<=0 or int(rapid.get('trade_count',0))==0))
            velocity=float(fast.get('volume_velocity',0));rapid_velocity=float(rapid.get('volume_velocity',0))
            # A tiny one-second decline is ordinary market variation. Keep the
            # pre-decline reference while confirming material loss of activity.
            reference=float(prior.get('fade_reference_velocity',prior.get('velocity',0)))
            volume_faded=bool(reference>0 and velocity<reference*.5 and rapid_velocity<=float(prior.get('rapid_velocity',0)))
            movement_faded=bool(prior and abs(short)<=float(prior.get('movement',0)) and short_volatility<=float(prior.get('short_volatility',0)))
            current_control=int(flow.get('fast_control_side') or flow.get('sustained_control_side') or 0)
            # Tiny sample-to-sample declines are not a fade while executions
            # still drive price. Relative ranking can replace it with a stronger
            # market; forced removal requires lost control or a quiet tape.
            warming=bool(symbol in previous and epoch-self.selected_since.get(symbol,epoch)<15)
            declining=bool(known and (not flow or (volume_faded and movement_faded and not current_control)))
            if declining:self.fade_since.setdefault(symbol,epoch)
            else:self.fade_since.pop(symbol,None)
            fading=bool(known and not warming and (quiet or (declining and epoch-self.fade_since[symbol]>=15)))
            flow_samples[symbol]=dict(known=known,velocity=velocity,rapid_velocity=rapid_velocity,
                movement=abs(short),short_volatility=short_volatility,
                fade_reference_velocity=reference if declining else velocity)
            current_pump=short>0 or minute>0 or (bootstrapping and change>0)
            if current_pump:pump_context.add(symbol)
            active_correction=bool(symbol in pump_context and known and flow and not fading and (short<0 or minute<0))
            if not (current_pump or active_correction):continue
            eligible=not fading
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
            rows.append(dict(symbol=symbol,last=last,price_received=row.get('price_received'),
                exchange_ms=row.get('exchange_ms'),short_return=short,minute_return=minute,
                movement_strength=abs(short),dominant_volume=max(fast.get('buy_volume',0),fast.get('sell_volume',0)),
                eligible=eligible,fading=fading,short_volatility=short_volatility,active_correction=active_correction,
                acceleration=short-minute/4,volatility=volatility,turnover_24h=turn,
                turnover_per_minute=turnover_velocity*60,executed_volume=medium.get('buy_volume',0)+medium.get('sell_volume',0),
                volume_velocity=fast.get('volume_velocity',turnover_velocity),
                volume_change=fast.get('volume_change',0),buy_volume=fast.get('buy_volume',0),
                sell_volume=fast.get('sell_volume',0),trade_count=fast.get('trade_count',0),
                trade_velocity=fast.get('trade_velocity',0),persistence=consistency,
                liquidity=1/(1+spread) if spread is not None else 0,
                spread=spread,flow_fresh=bool(flow.get('trade_data_fresh')),
                change_24h_pct=change*100,scan_return_pct=short*100,
                range_24h_pct=volatility*100,move='CORRECTION' if active_correction else 'PUMP',bootstrap=bootstrapping))
        # Equal cross-sectional percentile ranks: no fitted weights or indicators.
        fields=('movement_strength','acceleration','volatility','turnover_per_minute','turnover_24h',
                'executed_volume','volume_velocity','volume_change','dominant_volume',
                'trade_count','trade_velocity','persistence','liquidity')
        for row in rows:row['pandora_win_score']=0.
        for field in fields:
            values=sorted(row[field] for row in rows)
            for row in rows:
                row['pandora_win_score']+=bisect_left(values,row[field])/max(1,len(rows)-1)/len(fields)
        rows.sort(key=lambda r:(-r['pandora_win_score'],r['symbol']))
        for rank,row in enumerate(rows,1):row['rank']=rank
        eligible=[r for r in rows if r['eligible']]
        selected=self._stable_top(eligible,previous,self.top,self.selected_since,epoch)
        symbols=[r['symbol'] for r in selected]
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
            self.flow_samples.update(flow_samples);self.pump_context=pump_context
            candidates=self._stable_top(eligible,previous_candidates,self.candidate_limit,self.candidate_since,epoch)
            self.selected_since={s:self.selected_since.get(s,epoch) for s in symbols}
            self.selected=symbols;self.candidates=[r['symbol'] for r in candidates]
            self.candidate_since={s:self.candidate_since.get(s,epoch) for s in self.candidates}
            self.last_snapshot=dict(at=epoch,selected_symbols=symbols,selected=selected,
                top_movers=rows[:self.candidate_limit],candidate_symbols=list(self.candidates),
                retained_open_positions=[s for s in held if s not in symbols],
                states=dict(self.states),events=events,selection_frozen=False,observations_ready=True,scan_seconds=1,
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
