"""Causal executed-flow observations, grouped by actual traded price levels.

No minute candles, time-window voting, invented volume or extrapolated trades.
Current and immediately preceding price-level auctions form a relative pressure
comparison. This is an explicit causal heuristic, not a calibrated profitability
or false-alarm guarantee. Transport freshness is a separate validity check.
"""
from collections import deque, OrderedDict
from pandora_flow import summarize
import copy
import math,threading,time


def _number(value):
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return None
    return value if math.isfinite(value) else None


class RollingMarketData:
    def __init__(self,max_symbols=64,max_trade_lag_seconds=60,freshness_seconds=60,max_seen_per_symbol=65536,max_events_per_symbol=8192,**unused):
        if int(max_symbols)<1 or int(max_events_per_symbol)<1:raise ValueError('invalid execution buffer capacity')
        self.max_symbols=max_symbols;self.max_trade_lag_seconds=max_trade_lag_seconds
        self.freshness_seconds=freshness_seconds;self.max_seen_per_symbol=max_seen_per_symbol
        self._lock=threading.RLock();self._owners={};self._owner_heartbeats={};self._symbols={}
        self.max_events_per_symbol=int(max_events_per_symbol)
        # Transport reconnects reset flow coverage, but never recycle execution
        # identities or sequence cursors. Heavy replay buffers use a bounded LRU.
        self._execution_streams=OrderedDict();self._execution_sequences={}
        self._counters={'accepted':0,'duplicates':0,'invalid':0,'stale':0,'out_of_order':0,'outside_subscription':0,'dedup_overflows':0}

    @staticmethod
    def _new_symbol(epoch):
        return {'since':epoch,'seen':set(),'seen_queue':deque(),'latest_trade':None,'first_trade':None,'levels':deque(maxlen=2),'trades':deque(),'overflow_until':None,'revision':0,'flow_cache':None}

    def _execution_stream(self,symbol):
        stream=self._execution_streams.get(symbol)
        if stream is None:
            stream=dict(events=deque(maxlen=self.max_events_per_symbol),seen=set(),seen_queue=deque(),overflow_until=None)
            self._execution_streams[symbol]=stream
            while len(self._execution_streams)>self.max_symbols:self._execution_streams.popitem(last=False)
        else:self._execution_streams.move_to_end(symbol)
        return stream

    @staticmethod
    def _sequence(value):
        sequence=int(value or 0)
        if sequence<0 or sequence!=float(value or 0):raise ValueError('invalid execution sequence')
        return sequence

    def execution_sequences(self):
        with self._lock:return dict(self._execution_sequences)

    def restore_execution_sequences(self,sequences):
        """Seed persisted cursors before sockets start after a process restart."""
        with self._lock:
            for symbol,value in (sequences or {}).items():
                sequence=self._sequence(value);symbol=str(symbol)
                if sequence>self._execution_sequences.get(symbol,0):
                    self._execution_sequences[symbol]=sequence
                    stream=self._execution_streams.get(symbol)
                    if stream is not None:stream['events'].clear()

    def events_after(self,symbol,sequence=0):
        """Copy accepted executions in sequence order, without consuming them."""
        sequence=self._sequence(sequence)
        with self._lock:
            stream=self._execution_streams.get(str(symbol))
            return [dict(event) for event in stream['events'] if event['sequence']>sequence] if stream else []

    def event_status(self,symbol,after_sequence=None):
        """Report replay coverage so consumers can detect a missing prefix."""
        cursor=None if after_sequence is None else self._sequence(after_sequence)
        with self._lock:
            symbol=str(symbol);stream=self._execution_streams.get(symbol)
            events=stream['events'] if stream else ()
            oldest=events[0]['sequence'] if events else None
            latest=self._execution_sequences.get(symbol,0)
            gap=cursor is not None and (cursor<oldest-1 if oldest is not None else cursor<latest)
            return dict(oldest_sequence=oldest,latest_sequence=latest,buffered_events=len(events),
                        gap=gap,latest_receive_epoch=events[-1]['received_epoch'] if events else None)

    def mark_connected(self,epoch=None,symbols=None,owner=None):
        epoch=time.time() if epoch is None else float(epoch);name='default' if owner is None else str(owner)
        with self._lock:
            selected=set(str(s) for s in (symbols or ()))
            if owner is None:self._owners.clear();self._owner_heartbeats.clear()
            other_owned=set().union(*(v for k,v in self._owners.items() if k!=name)) if any(k!=name for k in self._owners) else set()
            self._owners[name]=selected;self._owner_heartbeats[name]=epoch
            wanted=set().union(*self._owners.values())
            self._symbols={s:(self._symbols.get(s) if s in other_owned and self._symbols.get(s) is not None else self._new_symbol(epoch) if s in selected else self._symbols.get(s,self._new_symbol(epoch))) for s in wanted}

    def mark_disconnected(self,epoch=None,owner=None):
        with self._lock:
            if owner is None:self._owners.clear();self._owner_heartbeats.clear()
            else:self._owners.pop(str(owner),None);self._owner_heartbeats.pop(str(owner),None)
            wanted=set().union(*self._owners.values()) if self._owners else set()
            self._symbols={s:state for s,state in self._symbols.items() if s in wanted}

    def set_subscriptions(self,symbols,epoch=None,owner=None):
        epoch=time.time() if epoch is None else float(epoch);name='default' if owner is None else str(owner)
        with self._lock:
            self._owners[name]=set(str(s) for s in symbols)
            wanted=set().union(*self._owners.values())
            self._symbols={s:self._symbols.get(s,self._new_symbol(epoch)) for s in wanted}

    def heartbeat(self,epoch=None,owner=None):
        epoch=time.time() if epoch is None else float(epoch)
        with self._lock:
            for name in list(self._owners) if owner is None else [str(owner)]:
                if name not in self._owners:continue
                prior=self._owner_heartbeats.get(name,epoch)
                if epoch-prior>self.freshness_seconds:
                    for symbol in self._owners[name]:
                        redundant_fresh=any(other!=name and symbol in syms and epoch-self._owner_heartbeats.get(other,float('-inf'))<=self.freshness_seconds for other,syms in self._owners.items())
                        if not redundant_fresh:self._symbols[symbol]=self._new_symbol(epoch)
                self._owner_heartbeats[name]=max(epoch,prior)

    def ingest_trades(self,rows,received_at=None,owner=None,accepted_rows=None):
        received=time.time() if received_at is None else float(received_at)
        if not isinstance(rows,(list,tuple)):return 0
        with self._lock:
            if not self._owners:return 0
            self.heartbeat(received,owner=owner);accepted=0
            for row in rows:
                if not isinstance(row,dict):self._counters['invalid']+=1;continue
                symbol=str(row.get('coin',''));state=self._symbols.get(symbol)
                if state is None or (owner is not None and symbol not in self._owners.get(str(owner),set())):self._counters['outside_subscription']+=1;continue
                px,qty,millis=(_number(row.get(k)) for k in ('px','sz','time'))
                ident=row.get('tid');side=row.get('side')
                if None in (px,qty,millis) or px<=0 or qty<=0 or side not in ('B','A') or ident is None or isinstance(ident,(bool,list,dict)):
                    self._counters['invalid']+=1;continue
                stamp=millis/1000.;age=received-stamp;notional=px*qty
                if not math.isfinite(notional):self._counters['invalid']+=1;continue
                if not -1<=age<=self.max_trade_lag_seconds or stamp<state['since']:
                    self._counters['stale']+=1;continue
                if state['latest_trade'] is not None and stamp<state['latest_trade']:
                    self._counters['out_of_order']+=1;continue
                stream=self._execution_stream(symbol)
                seen=stream['seen'];queue=stream['seen_queue']
                state['seen']=seen;state['seen_queue']=queue
                trades=state['trades']
                while trades and received-trades[0][0]>610: trades.popleft()
                while queue and received-queue[0][0]>self.max_trade_lag_seconds+2:
                    _,old=queue.popleft();seen.discard(old)
                key=(millis,str(ident))
                if key in seen:self._counters['duplicates']+=1;continue
                if stream['overflow_until'] is not None:
                    state['overflow_until']=stream['overflow_until']
                    if received<=stream['overflow_until']:continue
                    stream['overflow_until']=None;seen.clear();queue.clear()
                    state=self._new_symbol(received);self._symbols[symbol]=state
                    state['seen']=seen;state['seen_queue']=queue
                if len(seen)>=self.max_seen_per_symbol:
                    state['overflow_until']=stream['overflow_until']=received+self.max_trade_lag_seconds+2
                    self._counters['dedup_overflows']+=1;continue
                seen.add(key);queue.append((received,key))
                levels=state['levels']
                if not levels or levels[-1]['price']!=px:
                    levels.append({'price':px,'buy':0.,'sell':0.,'count':0,'first_epoch':stamp})
                level=levels[-1];level['buy' if side=='B' else 'sell']+=notional;level['count']+=1
                state['latest_trade']=stamp
                previous_event=state.get('decision_epoch')
                state['decision_epoch']=stamp if previous_event is None else max(stamp,math.nextafter(previous_event,float('inf')))
                state['revision']+=1
                state['latest_receive_epoch']=received
                if state['first_trade'] is None:state['first_trade']=stamp
                trades.append((stamp,px,notional,side))
                sequence=self._execution_sequences.get(symbol,0)+1
                self._execution_sequences[symbol]=sequence
                stream['events'].append(dict(id=str(ident),sequence=sequence,
                    exchange_epoch=stamp,received_epoch=received,price=px,size=qty,
                    notional=notional,aggressor_side=side,side=side))
                accepted+=1
                if accepted_rows is not None:accepted_rows.append(row)
            self._counters['accepted']+=accepted
            return accepted

    def flow_context(self,symbol,epoch=None):
        """Fresh Bybit Public Trades with causal M1/M3/M5 executed-flow windows.

        Transport ownership/freshness remains unchanged. Windows contain only
        accepted exchange executions; no candles, interpolation or invented volume.
        """
        epoch=time.time() if epoch is None else float(epoch)
        out={'trade_data_fresh':False,'control_side':0,'pressure_phase':'NO_VALID_TAPE','price_direction':0,
             'latest_trade_age_seconds':None,'latest_trade_epoch':None,'observed_at_epoch':epoch,
             'freshness_limit_seconds':self.freshness_seconds,'volume_source':'bybit_v5_public_trade'}
        with self._lock:
            status=self.event_status(symbol)
            out.update(execution_sequence=status['latest_sequence'],latest_receive_epoch=status['latest_receive_epoch'])
            state=self._symbols.get(str(symbol))
            if state is None:return out
            fresh=any(str(symbol) in symbols and -1<=epoch-self._owner_heartbeats.get(owner,float('-inf'))<=self.freshness_seconds for owner,symbols in self._owners.items())
            latest=state['latest_trade'];age=epoch-latest if latest is not None else None
            out.update(latest_trade_epoch=latest,latest_trade_age_seconds=age,decision_event_epoch=state.get('decision_epoch'))
            if not fresh or state['overflow_until'] is not None or age is None or not 0<=age<=self.freshness_seconds:return out
            trades=state['trades']
            while trades and epoch-trades[0][0]>610: trades.popleft()
            if not trades:return out
            revision=state['revision'];bucket=int(epoch*4)
            cached=state.get('flow_cache')
            if cached and cached[0]==revision and cached[1]==bucket and epoch>=cached[2]['flow_computed_at_epoch']:
                result=copy.deepcopy(cached[2])
                result.update(latest_trade_age_seconds=age,observed_at_epoch=epoch)
                return result
            # Snapshot validated executions under the lock, then perform the
            # expensive rolling calculations without blocking the socket reader.
            trades=list(trades);since=state['since'];first_trade=state['first_trade']
        coverage=max(0.,min(epoch-since,epoch-first_trade))
        out['trade_coverage_seconds']=coverage
        def window(seconds):
            rows=[r for r in trades if 0<=epoch-r[0]<=seconds]
            buy=sum(r[2] for r in rows if r[3]=='B');sell=sum(r[2] for r in rows if r[3]=='A')
            return rows,buy,sell
        def imbalance(buy,sell): return (buy-sell)/(buy+sell) if buy+sell else 0.
        r60,b60,s60=window(60)
        if not r60 or b60+s60<=0:return out
        i60=imbalance(b60,s60)
        levels=[]
        for trade in r60:
            if not levels or levels[-1]['price']!=trade[1]:levels.append({'price':trade[1]})
        levels=levels[-2:]
        dominant=1 if b60>s60 else -1 if s60>b60 else 0
        direction=1 if len(levels)==2 and levels[-1]['price']>levels[0]['price'] else -1 if len(levels)==2 and levels[-1]['price']<levels[0]['price'] else 0
        control=dominant if direction==dominant and direction else 0
        r15,b15,s15=window(15)
        r30,b30,s30=window(30)
        out.update(trade_data_fresh=True,buy_notional=b60,sell_notional=s60,flow_imbalance=i60,
                   buy_sell_ratio=b60/s60 if s60 else None,
                   buy_trade_count=sum(r[3]=='B' for r in r60),sell_trade_count=sum(r[3]=='A' for r in r60),
                   buy_volume_15s=b15,sell_volume_15s=s15,trade_count_15s=len(r15),flow_imbalance_15s=imbalance(b15,s15),
                   buy_volume_30s=b30,sell_volume_30s=s30,trade_count_30s=len(r30),flow_imbalance_30s=imbalance(b30,s30),
                   buy_volume_60s=b60,sell_volume_60s=s60,trade_count_60s=len(r60),observed_notional_60s=b60+s60,
                   volume_window_end_epoch=epoch,
                   price_direction=direction,control_side=control,previous_price=levels[0]['price'] if len(levels)==2 else None,
                   last_price=levels[-1]['price'],pressure_phase='CONTROL_CONFIRMED' if control else 'PRESSURE_WITHOUT_PRICE_CONFIRMATION',
                   observation_basis='executed_public_trades_m1_m3_m5',price_levels=len(levels))
        out.update(summarize(list(trades),epoch,coverage))
        if coverage>=180:
            r,b,s=window(180);out.update(flow_imbalance_180s=imbalance(b,s),trade_count_180s=len(r))
        if coverage>=300:
            r,b,s=window(300);i300=imbalance(b,s);price_start=r[0][1] if r else None;price_end=r[-1][1] if r else None
            out.update(buy_volume_300s=b,sell_volume_300s=s,trade_count_300s=len(r),flow_imbalance_300s=i300,
                       flow_delta_60_300=i60-i300,price_start_300s=price_start,price_end_300s=price_end,
                       price_return_300s=(price_end/price_start-1.) if price_start and price_end else None)
        out['flow_computed_at_epoch']=epoch
        with self._lock:
            if self._symbols.get(str(symbol)) is state and state['revision']==revision:
                state['flow_cache']=(revision,bucket,copy.deepcopy(out))
            elif self._symbols.get(str(symbol)) is not state:
                out.update(trade_data_fresh=False,fast_control_side=0,sustained_control_side=0,
                           control_side=0,pressure_phase='TRANSPORT_CHANGED_DURING_CALCULATION')
        return out

    def context(self,symbol,epoch=None):return self.flow_context(symbol,epoch)

    def stats(self):
        with self._lock:return {**self._counters,'connected':bool(self._owners),'subscribed_symbols':len(self._symbols),
            'dedup_entries':sum(len(s['seen']) for s in self._symbols.values()),'dedup_capacity_per_symbol':self.max_seen_per_symbol}
