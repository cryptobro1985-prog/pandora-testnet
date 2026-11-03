"""Public Bybit REST and the existing ACK/freshness-aware websocket transport."""
from collections import deque
import json
import math
import queue
import time
import urllib.parse
import urllib.request

from bybit_market_stream import run_bybit_stream


def get_json(path, **params):
    url='https://api.bybit.com'+path+'?'+urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Pandora-Caterpillar-PAPER/1'}),timeout=20) as r:
        data=json.load(r)
    if data.get('retCode')!=0:
        raise RuntimeError('Bybit public request failed: '+str(data.get('retCode')))
    return data['result']


def instruments():
    result={}; cursor=''; seen=set()
    for _ in range(30):
        data=get_json('/v5/market/instruments-info',category='linear',limit=1000,cursor=cursor)
        for row in data['list']:
            pair=row.get('symbol','')
            if (pair.endswith('USDT') and row.get('quoteCoin')=='USDT' and row.get('settleCoin')=='USDT'
                    and row.get('contractType')=='LinearPerpetual' and row.get('status')=='Trading'):
                result[pair[:-4]]={'status':'Trading','pair':pair,
                    'max_leverage':float(row['leverageFilter']['maxLeverage']),
                    'lot_size':row.get('lotSizeFilter',{}),'price_filter':row.get('priceFilter',{}),
                    'observed_at':time.time()}
        cursor=data.get('nextPageCursor') or ''
        if not cursor:return result
        if cursor in seen:raise RuntimeError('Bybit pagination cursor repeated')
        seen.add(cursor)
    raise RuntimeError('Incomplete instrument pagination')


def h1_history(symbol, now=None):
    now=time.time() if now is None else now
    rows=get_json('/v5/market/kline',category='linear',symbol=symbol+'USDT',interval=60,limit=200)['list']
    out=[]
    for r in reversed(rows):
        start=int(r[0])/1000
        if start+3600>now:continue
        out.append(dict(open_ts=start,available_ts=start+3600,open=float(r[1]),high=float(r[2]),
                        low=float(r[3]),close=float(r[4]),volume=float(r[5]),timeframe='1h',interval_minutes=60))
    if not out or out[-1]['open_ts']+3600!=math.floor(now/3600)*3600:
        raise RuntimeError('Latest closed H1 is missing')
    return out


class Scanner:
    def __init__(self,config):
        self.config=config; self.history={}

    def rank(self, rows, universe, now):
        candidates=[]; excluded={}
        for row in rows:
            pair=row.get('symbol',''); symbol=pair[:-4] if pair.endswith('USDT') else ''
            if symbol not in universe:continue
            try:
                price=float(row['lastPrice']); turnover=float(row['turnover24h'])
                bid=float(row['bid1Price']); ask=float(row['ask1Price'])
                if not all(math.isfinite(v) and v>0 for v in (price,turnover,bid,ask)) or ask<bid:
                    raise ValueError()
                spread=(ask-bid)/((ask+bid)/2)*10000
            except (KeyError,TypeError,ValueError,OverflowError):
                excluded[symbol]='INVALID_OR_MISSING_QUOTE'; continue
            history=self.history.setdefault(symbol,deque(maxlen=12))
            prior=history[-1] if history else None
            history.append((now,price,turnover))
            if turnover<self.config.minimum_turnover:excluded[symbol]='LOW_TURNOVER'; continue
            if spread>self.config.maximum_spread_bps:excluded[symbol]='WIDE_SPREAD'; continue
            if prior is None or now-prior[0]<1 or now-prior[0]>2*self.config.scanner_seconds+15:
                excluded[symbol]='NEED_RECENT_OBSERVATION_PAIR'; continue
            # Rolling 24h turnover delta is an activity proxy, not exact traded notional.
            delta=turnover-prior[2]
            if delta<=0:excluded[symbol]='NO_OBSERVED_RECENT_TURNOVER_GROWTH'; continue
            move=(price/prior[1]-1)*10000
            if move==0:excluded[symbol]='NO_CURRENT_PRICE_DISPLACEMENT'; continue
            oldmove=(prior[1]/history[-3][1]-1)*10000 if len(history)>=3 else None
            candidates.append({'symbol':symbol,'mark':price,'recent_move_bps':move,'spread_bps':spread,
                'turnover24h':turnover,'turnover_delta_proxy':delta,
                'movement_acceleration_bps':None if oldmove is None else abs(move)-abs(oldmove),
                'observed_at':now,'reason':'RECENT_ABSOLUTE_MOVE_LIQUID_FRESH_QUOTE',
                'ranking_components':{'absolute_recent_move_bps':abs(move),'turnover_delta_proxy':delta,'spread_bps':spread}})
        candidates.sort(key=lambda r:(abs(r['recent_move_bps']),r['turnover_delta_proxy'],-r['spread_bps']),reverse=True)
        for i,row in enumerate(candidates):row['rank']=i+1
        return {'observed_at':now,'status':'OK' if candidates else 'WARMUP','candidates':candidates[:30],
                'universe_count':len(universe),'excluded':excluded,'selection_frozen_for_session':True,
                'method':'lexicographic recent absolute move, recent turnover proxy, spread; not an entry signal'}


class StreamBridge:
    """Queue adapter for the project's transport; all decisions run on the main thread."""
    def __init__(self, messages):
        self.messages=messages; self.symbols=set(); self.accepted=0; self.trade_ready=False; self.generation=0

    def send(self,kind,data):
        # A full queue forces the stream to reconnect and clear strategy buffers.
        self.messages.put((kind,data),timeout=2)

    def mark_connected(self,epoch=None,symbols=None,owner=None):
        self.generation+=1
        self.trade_ready=False
        self.symbols=set(symbols or ()); self.send('connection',(list(self.symbols),True,epoch or time.time()))

    def mark_disconnected(self,epoch=None,owner=None):
        self.generation+=1
        self.trade_ready=False
        try:self.send('connection',(list(self.symbols),False,epoch or time.time()))
        except queue.Full:pass

    def set_subscriptions(self,symbols,epoch=None,owner=None):
        ready=self.trade_ready
        self.mark_connected(epoch,symbols,owner)
        self.trade_ready=ready

    def heartbeat(self,epoch=None,owner=None):pass

    def ingest_trades(self,rows,received_at=None,owner=None,accepted_rows=None):
        if not self.trade_ready:return 0
        for row in rows:self.send('trade',(row,received_at or time.time(),self.generation))
        self.accepted+=len(rows)
        if accepted_rows is not None:accepted_rows.extend(rows)
        return len(rows)

    def stats(self):return {'queued_trades':self.accepted,'queue_depth':self.messages.qsize()}

    def run(self,stop,symbols_provider,url=None):
        kwargs={} if url is None else {'url':url}
        def report(data):
            try:self.messages.put_nowait(('transport',data))
            except queue.Full:pass
        run_bybit_stream(self,stop,symbols_provider,report,worker_name='caterpillar-paper',
                         on_subscription=lambda ready:setattr(self,'trade_ready',ready),**kwargs)
