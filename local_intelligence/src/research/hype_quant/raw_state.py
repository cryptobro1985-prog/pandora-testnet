from __future__ import annotations
from collections import deque, defaultdict
import json, math, statistics
from typing import Any

def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)

def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

class RawMarketState:
    """Causal decoder of exact Bybit raw frames into fixed online-ML features."""
    def __init__(self):
        self.bids={}; self.asks={}
        self.trades=deque(); self.liqs=deque(); self.book_changes=deque()
        self.last_ticker={}; self.last_recv={}
        self.book_seq=None; self.book_u=None; self.book_invalidations=0
        self.cum_signed_notional=0.0; self.frames=0
        self.book_valid=False; self.source_times={}; self.ticker_times={}

    def _trim(self, now_ms):
        while self.trades and self.trades[0][0] < now_ms-15*60_000: self.trades.popleft()
        while self.liqs and self.liqs[0][0] < now_ms-15*60_000: self.liqs.popleft()
        while self.book_changes and self.book_changes[0][0] < now_ms-5*60_000: self.book_changes.popleft()

    def _book_side(self, book, rows, label, now_ms):
        ch=defaultdict(float)
        for row in rows or []:
            if len(row)<2: continue
            p=num(row[0]); q=num(row[1])
            if p is None or q is None or p<=0 or q<0: continue
            old=book.get(p,0.0)
            if q==0:
                if old>0: ch[label+"_cancel_notional"] += p*old
                book.pop(p,None)
            else:
                if q>old: ch[label+"_add_notional"] += p*(q-old)
                elif q<old: ch[label+"_cancel_notional"] += p*(old-q)
                book[p]=q
        if ch: self.book_changes.append((now_ms,dict(ch)))

    def ingest_envelope(self,envelope:dict[str,Any]):
        recv=int(envelope.get("received_ts_ms") or 0)
        raw=envelope.get("raw_text")
        try: msg=json.loads(raw) if isinstance(raw,str) else raw
        except Exception: return
        if not isinstance(msg,dict): return
        self.frames+=1; self._trim(recv)
        topic=str(msg.get("topic") or "")
        source=num(msg.get("ts"))
        if not recv or (source is not None and source>recv):return
        if topic.startswith("orderbook."):
            data=msg.get("data") or {}
            snapshot=msg.get("type")=="snapshot" or data.get("u")==1
            if snapshot:
                self.bids.clear(); self.asks.clear()
                self.book_valid=True
            else:
                if not self.book_valid:return
                u=data.get("u"); seq=data.get("seq")
                if self.book_u is not None and u is not None and int(u)<=self.book_u:
                    self.book_invalidations+=1; self.book_valid=False; return
                if self.book_seq is not None and seq is not None and int(seq)<=self.book_seq:
                    self.book_invalidations+=1; self.book_valid=False; return
            prior_changes=len(self.book_changes)
            self._book_side(self.bids,data.get("b",[]),"bid",recv)
            self._book_side(self.asks,data.get("a",[]),"ask",recv)
            if snapshot:
                while len(self.book_changes)>prior_changes:self.book_changes.pop()
            self.book_u=int(data["u"]) if data.get("u") is not None else self.book_u
            self.book_seq=int(data["seq"]) if data.get("seq") is not None else self.book_seq
            self.last_recv["book"]=recv
            self.source_times["book"]=int(source) if source is not None else recv
            if self.bids and self.asks and max(self.bids)>=min(self.asks):
                self.book_valid=False;self.book_invalidations+=1
        elif topic.startswith("publicTrade."):
            for z in msg.get("data") or []:
                p=num(z.get("p")); q=num(z.get("v")); side=z.get("S")
                if p is None or q is None or p<=0 or q<=0 or side not in ("Buy","Sell"): continue
                event_ts=num(z.get("T"))
                if event_ts is not None and event_ts>recv:continue
                n=p*q; sign=1.0 if side=="Buy" else -1.0
                self.cum_signed_notional += sign*n
                self.trades.append((recv,sign,p,q,n,str(z.get("L") or ""),bool(z.get("BT")),bool(z.get("RPI"))))
            self.last_recv["trade"]=recv
            self.source_times["trade"]=int(source) if source is not None else recv
        elif topic.startswith("allLiquidation."):
            for z in msg.get("data") or []:
                p=num(z.get("p")); q=num(z.get("v")); side=z.get("S")
                if p is None or q is None or p<=0 or q<=0 or side not in ("Buy","Sell"): continue
                event_ts=num(z.get("T"))
                if event_ts is not None and event_ts>recv:continue
                self.liqs.append((recv,1.0 if side=="Buy" else -1.0,p,q,p*q))
            self.last_recv["liq"]=recv
            self.source_times["liq"]=int(source) if source is not None else recv
        elif topic.startswith("tickers."):
            d=msg.get("data") or {}
            if isinstance(d,list): d=d[0] if d else {}
            if isinstance(d,dict):
                self.last_ticker.update(d)
                for k in d:self.ticker_times[k]=(int(source) if source is not None else recv,recv)
            self.last_recv["ticker"]=recv

    def features(self,now_ms:int)->dict[str,float]:
        self._trim(now_ms); x={}; t=self.last_ticker
        for src,dst in {
            "lastPrice":"ticker_last_price","markPrice":"mark_price","indexPrice":"index_price",
            "openInterest":"ticker_open_interest","fundingRate":"funding_rate","turnover24h":"turnover_24h",
            "volume24h":"volume_24h","highPrice24h":"high_24h","lowPrice24h":"low_24h",
            "price24hPcnt":"price_change_24h_pct","bid1Price":"ticker_bid1","ask1Price":"ticker_ask1",
            "bid1Size":"ticker_bid1_size","ask1Size":"ticker_ask1_size"}.items():
            v=num(t.get(src));st,rt=self.ticker_times.get(src,(None,None))
            ttl=600_000 if src in ("fundingRate","openInterest") else 120_000
            if v is not None and st is not None and rt is not None and st<=now_ms and rt<=now_ms and now_ms-st<=ttl:x[dst]=v
        if finite(x.get("mark_price")) and finite(x.get("index_price")) and x["index_price"]!=0:
            x["basis_bps_raw"]=(x["mark_price"]/x["index_price"]-1)*10000
        for sec in (1,5,15,30,60,180,300,900):
            tr=[z for z in self.trades if now_ms-sec*1000<=z[0]<=now_ms]
            if tr:
                buy=[z for z in tr if z[1]>0]; sell=[z for z in tr if z[1]<0]
                bn=sum(z[4] for z in buy); sn=sum(z[4] for z in sell); den=bn+sn
                x[f"trade_count_{sec}s"]=float(len(tr)); x[f"buy_trade_count_{sec}s"]=float(len(buy)); x[f"sell_trade_count_{sec}s"]=float(len(sell))
                x[f"buy_notional_raw_{sec}s"]=bn; x[f"sell_notional_raw_{sec}s"]=sn
                x[f"flow_imbalance_raw_{sec}s"]=0.0 if den<=0 else (bn-sn)/den
                x[f"trade_notional_mean_{sec}s"]=den/len(tr); x[f"trade_notional_max_{sec}s"]=max(z[4] for z in tr)
                x[f"trade_qty_mean_{sec}s"]=statistics.fmean(z[3] for z in tr); x[f"trade_price_mean_{sec}s"]=statistics.fmean(z[2] for z in tr)
                x[f"block_trade_count_{sec}s"]=float(sum(z[6] for z in tr)); x[f"rpi_trade_count_{sec}s"]=float(sum(z[7] for z in tr))
                plus=sum(1 for z in tr if "Plus" in z[5]); minus=sum(1 for z in tr if "Minus" in z[5])
                x[f"tick_direction_balance_{sec}s"]=0.0 if plus+minus==0 else (plus-minus)/(plus+minus)
            li=[z for z in self.liqs if now_ms-sec*1000<=z[0]<=now_ms]
            if li:
                ln=sum(z[4] for z in li if z[1]>0); sn=sum(z[4] for z in li if z[1]<0); den=ln+sn
                x[f"liq_count_raw_{sec}s"]=float(len(li)); x[f"long_liq_raw_{sec}s"]=ln; x[f"short_liq_raw_{sec}s"]=sn
                x[f"liq_imbalance_raw_{sec}s"]=0.0 if den<=0 else (sn-ln)/den
                x[f"liq_notional_max_{sec}s"]=max(z[4] for z in li); x[f"liq_price_mean_{sec}s"]=statistics.fmean(z[2] for z in li)
        # Recompute causal CVD from retained observations rather than a total
        # already contaminated by frames received after the queried instant.
        causal_trades=[z for z in self.trades if z[0]<=now_ms]
        if causal_trades:x["cvd_notional_retained"]=sum(z[1]*z[4] for z in causal_trades)
        if causal_trades and self.last_recv.get("trade",now_ms+1)<=now_ms:
            x["cvd_notional_cumulative"]=self.cum_signed_notional
        book_ts=self.last_recv.get("book");book_source=self.source_times.get("book")
        valid=self.book_valid and book_ts is not None and book_source is not None and book_ts<=now_ms and 0<=now_ms-book_source<=60_000
        bids=sorted(self.bids.items(),reverse=True)[:50] if valid else []; asks=sorted(self.asks.items())[:50] if valid else []
        if bids and asks and bids[0][0]<asks[0][0]:
            mid=(bids[0][0]+asks[0][0])/2
            x["raw_best_bid"]=bids[0][0]; x["raw_best_ask"]=asks[0][0]; x["raw_spread_bps"]=(asks[0][0]-bids[0][0])/mid*10000
            for side,rows in (("bid",bids),("ask",asks)):
                ns=[]
                for i,(p,q) in enumerate(rows,1):
                    x[f"{side}_l{i}_dist_bps"]=(p/mid-1)*10000; x[f"{side}_l{i}_qty"]=q
                    n=p*q; ns.append(n); x[f"{side}_l{i}_notional_log"]=math.log1p(max(n,0.0))
                for n in (5,10,25,50):
                    part=ns[:n]
                    if part:
                        x[f"{side}_depth_raw_{n}"]=sum(part); x[f"{side}_depth_concentration_{n}"]=max(part)/max(sum(part),1e-12)
            for n in (5,10,25,50):
                bd=x.get(f"bid_depth_raw_{n}",0); ad=x.get(f"ask_depth_raw_{n}",0)
                if bd+ad>0: x[f"book_imbalance_raw_{n}"]=(bd-ad)/(bd+ad)
        if valid:
            if self.book_u is not None:x["book_update_id"]=float(self.book_u)
            if self.book_seq is not None:x["book_sequence"]=float(self.book_seq)
        x["book_invalidations_raw"]=float(self.book_invalidations)
        for sec in (60,300):
            rows=[c for ts,c in self.book_changes if now_ms-sec*1000<=ts<=now_ms] if valid else []
            if not rows:continue
            for side in ("bid","ask"):
                add=sum(c.get(side+"_add_notional",0.0) for c in rows); cancel=sum(c.get(side+"_cancel_notional",0.0) for c in rows)
                x[f"{side}_add_notional_raw_{sec}s"]=add; x[f"{side}_cancel_notional_raw_{sec}s"]=cancel
                if add+cancel>0: x[f"{side}_book_churn_balance_{sec}s"]=(add-cancel)/(add+cancel)
        for ch,ts in self.last_recv.items():
            if ts<=now_ms:x[f"{ch}_age_ms"]=float(now_ms-ts)
        x["raw_frame_count"]=float(self.frames)
        return x
