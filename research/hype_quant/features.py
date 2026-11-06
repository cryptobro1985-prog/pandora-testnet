from __future__ import annotations

from collections import deque
import json
import math
import statistics
from typing import Any

from .feature_contract import INPUT_IDS, TARGET_IDS, METADATA_IDS, contract_summary


TF_MS={"1":60_000,"3":180_000,"5":300_000,"60":3_600_000}
TF_NAME={"1":"m1","3":"m3","5":"m5","60":"h1"}


def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)


def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def sign(v,eps=1e-12):
    return 1 if v>eps else -1 if v<-eps else 0


def safe_log1p(v):
    return math.log1p(max(0.0,float(v))) if finite(v) else None


class FeatureState:
    """Causal merger for every predictive HYPE110+ source.

    Raw public trades, L50 book, liquidations and ticker frames are consumed
    directly. M1/M3/M5/H1 context is consumed only after its receipt timestamp.
    POST_ANALYSIS points 83..110 are deliberately not returned as model features:
    they are target/evaluation information and feeding them would leak future.
    """

    def __init__(self):
        self.market_context={}
        self.structural={}
        self.instrument={}
        self.account_ratio={}
        self.server_time={}
        self.ticker={}
        self.prices=deque()
        self.trades=deque()
        self.liqs=deque()
        self.oi_history=deque()
        self.book_bids={}
        self.book_asks={}
        self.book_valid=False
        self.book_update_id=None
        self.book_sequence=None
        self.book_invalidations=0
        self.book_changes=deque()
        self.latencies={"trade":deque(maxlen=1200),"book":deque(maxlen=1200),"liq":deque(maxlen=1200),"ticker":deque(maxlen=1200)}
        self.candles={k:{} for k in TF_MS}
        self.initial_backfill_seen=False
        self.last_trade=None
        self.last_liq=None
        self.last_raw_received_ts=None
        self.last_receipt_sequence=None
        self.last_receipt_sequence_by_source={}
        self.receipt_sequence_gaps=0
        self.subscription_acks=0
        self.raw_frames=0
        self.control_frames=0
        self.ws_server_ts_ms=None
        self.ws_clock_offset_ms=None
        self.last_ts_ms=None
        self.last_price=None
        self.dominance_samples=deque()
        self.point_seen=set()
        self.point_last_seen_ms={}
        self._mark_ts_ms=None
        self.feature_names_seen=set()
        self.max_feature_count=0

    def _mark(self,*ids):
        if not hasattr(self,"point_last_seen_ms"):self.point_last_seen_ms={}
        valid=[i for i in ids if i in INPUT_IDS or i in METADATA_IDS]
        self.point_seen.update(valid)
        ts=getattr(self,"_mark_ts_ms",None) or getattr(self,"last_ts_ms",None) or getattr(self,"last_raw_received_ts",None)
        if ts:
            for i in valid:self.point_last_seen_ms[i]=int(ts)

    def coverage_report(self):
        seen_inputs=sorted(self.point_seen & INPUT_IDS)
        if not hasattr(self,"point_last_seen_ms"):self.point_last_seen_ms={}
        newest=max(self.point_last_seen_ms.values(),default=(self.last_ts_ms or 0))
        ages={str(i):(None if i not in self.point_last_seen_ms or not newest else max(0.0,(newest-self.point_last_seen_ms[i])/1000.0))
              for i in sorted(INPUT_IDS)}
        return {
            **contract_summary(),
            "supported_input_ids":sorted(INPUT_IDS),
            "seen_input_ids":seen_inputs,
            "missing_seen_input_ids":sorted(INPUT_IDS-set(seen_inputs)),
            "seen_input_count":len(seen_inputs),
            "point_age_seconds":ages,
            "feature_names_seen_count":len(self.feature_names_seen),
            "max_features_in_one_state":self.max_feature_count,
            "target_eval_ids_reserved_for_post_event_labels":sorted(TARGET_IDS),
            "metadata_ids":sorted(METADATA_IDS),
        }

    def _prune(self,ts):
        cutoff=ts-30*60_000
        while self.prices and self.prices[0][0]<cutoff:self.prices.popleft()
        while self.trades and self.trades[0]["ts_ms"]<cutoff:self.trades.popleft()
        while self.liqs and self.liqs[0]["ts_ms"]<cutoff:self.liqs.popleft()
        while self.book_changes and self.book_changes[0][0]<ts-10*60_000:self.book_changes.popleft()
        while self.oi_history and self.oi_history[0][0]<ts-3*3_600_000:self.oi_history.popleft()
        while self.dominance_samples and self.dominance_samples[0][0]<cutoff:self.dominance_samples.popleft()

    def update_raw_frame(self,envelope:dict[str,Any]):
        recv=int(envelope.get("received_ts_ms") or 0)
        self._mark_ts_ms=recv or getattr(self,"_mark_ts_ms",None)
        seq=envelope.get("receipt_sequence")
        source=str(envelope.get("_source_path") or "default")
        if seq is not None:
            seq=int(seq)
            previous=self.last_receipt_sequence_by_source.get(source)
            if previous is not None and seq!=previous+1:
                self.receipt_sequence_gaps+=1
            self.last_receipt_sequence_by_source[source]=seq
            self.last_receipt_sequence=seq
        self.last_raw_received_ts=max(self.last_raw_received_ts or 0,recv)
        self.raw_frames+=1
        raw=envelope.get("raw_text")
        try:msg=json.loads(raw) if isinstance(raw,str) else raw
        except Exception:
            self.control_frames+=1
            self._mark(77,80,81,82,116)
            return
        if not isinstance(msg,dict):
            return
        server_ts=num(msg.get("ts"))
        if server_ts is not None and recv:
            self.ws_server_ts_ms=int(server_ts)
            self.ws_clock_offset_ms=float(recv-int(server_ts))
            self._mark(111)
        if msg.get("op")=="subscribe" and msg.get("success") is True:
            self.subscription_acks+=1
            self._mark(80,116)
            return
        topic=str(msg.get("topic",""))
        if topic.startswith("orderbook."):
            d=msg.get("data") or {}
            self.update_event({"kind":"orderbook","received_ts_ms":recv,"exchange_ts_ms":msg.get("ts"),
                "type":msg.get("type"),"update_id":d.get("u"),"sequence":d.get("seq"),
                "bids":d.get("b",[]),"asks":d.get("a",[])})
        elif topic.startswith("publicTrade."):
            for x in msg.get("data") or []:
                self.update_event({"kind":"trade","received_ts_ms":recv,"exchange_ts_ms":x.get("T",msg.get("ts")),
                    "sequence":x.get("seq"),"side":x.get("S"),"price":x.get("p"),"qty":x.get("v"),
                    "tick_direction":x.get("L"),"block_trade":x.get("BT"),"rpi":x.get("RPI")})
        elif topic.startswith("allLiquidation."):
            for x in msg.get("data") or []:
                self.update_event({"kind":"liquidation","received_ts_ms":recv,"exchange_ts_ms":x.get("T",msg.get("ts")),
                    "side":x.get("S"),"price":x.get("p"),"qty":x.get("v")})
        elif topic.startswith("tickers."):
            d=msg.get("data") or {}
            if isinstance(d,list):d=d[0] if d else {}
            self.update_event({"kind":"ticker","received_ts_ms":recv,"exchange_ts_ms":msg.get("ts"),"data":d})
        elif topic.startswith("kline."):
            parts=topic.split(".")
            tf=parts[1] if len(parts)>=3 else ""
            if tf in TF_MS:
                store=self.candles[tf]
                for b in msg.get("data") or []:
                    if not isinstance(b,dict): continue
                    start=int(b.get("start") or 0)
                    vals={k:num(b.get(k)) for k in ("open","high","low","close","volume","turnover")}
                    if start<=0 or not all(vals[k] is not None for k in ("open","high","low","close")): continue
                    store[start]={"start_ms":start,**vals,
                                  "confirm":1.0 if b.get("confirm") else 0.0,
                                  "received_ts_ms":recv,
                                  "source_timestamp_ms":int(b.get("timestamp") or msg.get("ts") or recv)}
                keep=600 if tf=="1" else 300 if tf=="3" else 220 if tf=="5" else 10000
                if len(store)>keep:
                    for k in sorted(store)[:-keep]:store.pop(k,None)
                self._mark({"1":4,"3":5,"5":6,"60":7}[tf],77,82,111)
        else:
            self.control_frames+=1
            self._mark(77,81,82,116)

    def update_event(self,event:dict[str,Any]):
        kind=event.get("kind")
        recv=int(event.get("received_ts_ms") or event.get("ts_ms") or 0)
        exch=int(event.get("exchange_ts_ms") or 0)
        if recv and exch and recv>=exch:
            q=self.latencies.get(kind)
            if q is not None:q.append(recv-exch)
        if kind=="trade":
            p=num(event.get("price"));q=num(event.get("qty"));side=str(event.get("side") or "")
            if not p or not q or side not in ("Buy","Sell"):return
            row={"ts_ms":recv,"exchange_ts_ms":exch,"side":1 if side=="Buy" else -1,
                 "price":p,"qty":q,"notional":p*q,
                 "block_trade":1.0 if event.get("block_trade") else 0.0,
                 "rpi":1.0 if event.get("rpi") else 0.0}
            self.trades.append(row);self.last_trade=row
            self._mark(12,13,14,15,16,17,18,19,77,82)
        elif kind=="liquidation":
            p=num(event.get("price"));q=num(event.get("qty"));side=str(event.get("side") or "")
            if not p or not q or side not in ("Buy","Sell"):return
            row={"ts_ms":recv,"exchange_ts_ms":exch,"side":1 if side=="Buy" else -1,
                 "price":p,"qty":q,"notional":p*q}
            self.liqs.append(row);self.last_liq=row
            self._mark(65,66,67,68,69,70,71,72,73,77,82)
        elif kind=="ticker":
            d=event.get("data") or {}
            if isinstance(d,dict):
                self.ticker.update(d)
                oi=num(d.get("openInterest"))
                if oi and recv:
                    if not self.oi_history or recv>self.oi_history[-1][0]:
                        self.oi_history.append((recv,oi))
                self._mark(1,2,3,58,59,60,61,62,63,64,77,82)
        elif kind=="orderbook":
            typ=event.get("type")
            if typ=="snapshot":
                self.book_bids.clear();self.book_asks.clear();self.book_valid=True
            elif not self.book_valid:
                self.book_invalidations+=1
                return
            u=event.get("update_id");seq=event.get("sequence")
            if typ!="snapshot":
                if u is not None and self.book_update_id is not None and int(u)<=int(self.book_update_id):
                    self.book_valid=False;self.book_invalidations+=1;return
                if seq is not None and self.book_sequence is not None and int(seq)<=int(self.book_sequence):
                    self.book_valid=False;self.book_invalidations+=1;return
            changes={"bid_add":0.0,"bid_cancel":0.0,"ask_add":0.0,"ask_cancel":0.0}
            for label,book,rows in (("bid",self.book_bids,event.get("bids") or []),("ask",self.book_asks,event.get("asks") or [])):
                for item in rows:
                    if len(item)<2:continue
                    p=num(item[0]);q=num(item[1])
                    if not p or q is None or q<0:continue
                    old=book.get(p,0.0)
                    if q==0:
                        if old:changes[label+"_cancel"]+=p*old
                        book.pop(p,None)
                    else:
                        if q>old:changes[label+"_add"]+=p*(q-old)
                        elif q<old:changes[label+"_cancel"]+=p*(old-q)
                        book[p]=q
            if recv:self.book_changes.append((recv,changes))
            self.book_update_id=int(u) if u is not None else self.book_update_id
            self.book_sequence=int(seq) if seq is not None else self.book_sequence
            self._mark(44,45,46,47,48,49,50,51,52,53,54,55,56,57,77,82)
        elif kind=="control":
            self.control_frames+=1
            self._mark(77,81,82,116)

    def update_market_context(self,row:dict[str,Any]):
        if not isinstance(row,dict):return
        recv=int(row.get("received_ts_ms") or row.get("ts_ms") or 0)
        self._mark_ts_ms=recv or getattr(self,"_mark_ts_ms",None)
        self.market_context=row
        self.initial_backfill_seen=self.initial_backfill_seen or bool(row.get("initial_backfill"))
        ticker=row.get("ticker") or {}
        if isinstance(ticker,dict):
            self.ticker.update(ticker)
            oi=num(ticker.get("openInterest"))
            if oi and recv and (not self.oi_history or recv>self.oi_history[-1][0]):
                self.oi_history.append((recv,oi))
        inst=row.get("instrument")
        if isinstance(inst,dict) and inst.get("ok") is True and isinstance(inst.get("value"),dict):
            inst=inst.get("value")
        if isinstance(inst,dict) and inst:self.instrument=inst
        ar=row.get("account_ratio")
        if isinstance(ar,dict):self.account_ratio=ar
        st=row.get("server_time")
        if isinstance(st,dict) and st.get("ok") is True and isinstance(st.get("value"),dict):
            st=st.get("value")
        if isinstance(st,dict):self.server_time=st
        candles=row.get("candles") or {}
        for tf,rows in candles.items():
            if tf not in TF_MS or not isinstance(rows,list):continue
            interval=TF_MS[tf]
            store=self.candles[tf]
            for b in rows:
                if not isinstance(b,dict):continue
                start=int(b.get("start_ms") or 0)
                if start<=0 or start+interval>recv:continue
                vals={k:num(b.get(k)) for k in ("open","high","low","close","volume","turnover")}
                if not all(vals[k] is not None for k in ("open","high","low","close")):continue
                store[start]={"start_ms":start,**vals}
            keep=600 if tf=="1" else 300 if tf=="3" else 220 if tf=="5" else 1000
            if len(store)>keep:
                for k in sorted(store)[:-keep]:store.pop(k,None)
        self._mark(1,2,3,4,5,6,7,8,58,62,63,64,77,82,111,112,113,114,115)

    def update_structural_context(self,row:dict[str,Any]):
        if isinstance(row,dict) and "error" not in row:
            self._mark_ts_ms=int(row.get("ts_ms") or row.get("received_ts_ms") or 0) or getattr(self,"_mark_ts_ms",None)
            self.structural=row
            self._mark(9,10,11,36,37,38,39,40,77,78,79,80,82,111,113,114,115,116)

    def _price_at_or_before(self,target_ms:int):
        for ts,p in reversed(self.prices):
            if ts<=target_ms:return p
        return None

    def _window_return(self,ts,sec,price):
        old=self._price_at_or_before(ts-sec*1000)
        return None if not old or old<=0 else price/old-1.0

    def _trade_window(self,ts,sec):
        rows=[r for r in self.trades if r["ts_ms"]>=ts-sec*1000 and r["ts_ms"]<=ts]
        buy=[r for r in rows if r["side"]>0];sell=[r for r in rows if r["side"]<0]
        bn=sum(r["notional"] for r in buy);sn=sum(r["notional"] for r in sell);den=bn+sn
        bq=sum(r["qty"] for r in buy);sq=sum(r["qty"] for r in sell)
        return {"rows":rows,"buy_notional":bn,"sell_notional":sn,"buy_qty":bq,"sell_qty":sq,
                "buy_count":len(buy),"sell_count":len(sell),"count":len(rows),
                "imbalance":None if den<=0 else (bn-sn)/den,"cvd":bn-sn}

    def _liq_window(self,ts,sec):
        rows=[r for r in self.liqs if r["ts_ms"]>=ts-sec*1000 and r["ts_ms"]<=ts]
        # Bybit stream semantics used by the collector: S=Buy => long liquidation.
        lng=sum(r["notional"] for r in rows if r["side"]>0)
        sht=sum(r["notional"] for r in rows if r["side"]<0)
        return {"rows":rows,"long":lng,"short":sht,"count":len(rows),"notional":lng+sht}

    def _oi_at(self,target):
        out=None
        for t,v in self.oi_history:
            if t<=target:out=(t,v)
            else:break
        return out

    def _add_candles(self,x,price):
        for tf,name in TF_NAME.items():
            rows=[self.candles[tf][k] for k in sorted(self.candles[tf])]
            if not rows:continue
            for lag,b in enumerate(reversed(rows[-8:])):
                prefix=f"{name}_lag{lag}_"
                for k in ("open","high","low","close"):
                    v=b.get(k)
                    if finite(v) and price>0:x[prefix+k+"_rel"]=v/price-1.0
                if finite(b.get("volume")):x[prefix+"log_volume"]=math.log1p(max(0.0,b["volume"]))
                if finite(b.get("turnover")):x[prefix+"log_turnover"]=math.log1p(max(0.0,b["turnover"]))
                if finite(b.get("high")) and finite(b.get("low")) and b["low"]>0:
                    x[prefix+"range_pct"]=b["high"]/b["low"]-1.0
                if finite(b.get("open")) and b["open"]>0 and finite(b.get("close")):
                    x[prefix+"body_pct"]=b["close"]/b["open"]-1.0
            latest=rows[-1]
            if len(rows)>=2 and rows[-2]["close"]:
                x[name+"_close_return_1bar"]=latest["close"]/rows[-2]["close"]-1.0
            x[name+"_closed_bar_count"]=float(len(rows))
        x["initial_backfill_seen"]=1.0 if self.initial_backfill_seen else 0.0

    @staticmethod
    def _flatten_numeric(prefix,obj,out,depth=0):
        if depth>4:return
        if isinstance(obj,dict):
            for k,v in obj.items():
                FeatureState._flatten_numeric(prefix+"_"+str(k),v,out,depth+1)
        elif finite(obj):
            out[prefix]=float(obj)
        elif isinstance(obj,str):
            v=num(obj)
            if v is not None:out[prefix]=v

    def update_micro(self,row:dict[str,Any])->tuple[float,dict[str,float]]:
        ts=int(row.get("ts_ms") or 0)
        self._mark_ts_ms=ts or getattr(self,"_mark_ts_ms",None)
        price=num(row.get("mid")) or num(row.get("best_bid")) or num(self.ticker.get("lastPrice")) or num(self.structural.get("last_price"))
        if not price or price<=0:raise ValueError("micro row has no valid price")
        gap_s=0.0 if self.last_ts_ms is None else max(0.0,(ts-self.last_ts_ms)/1000.0)
        self.prices.append((ts,price));self._prune(ts)
        x={"last_price":price,"log_last_price":math.log(price),"micro_gap_seconds":gap_s}

        for key in (
            "spread_bps","book_imbalance_5","book_imbalance_25","bid_depth_5","ask_depth_5",
            "bid_depth_25","ask_depth_25","flow_imbalance_5s","flow_imbalance_15s",
            "flow_imbalance_60s","buy_notional_60s","sell_notional_60s",
            "long_liq_notional_5s","short_liq_notional_5s","long_liq_notional_15s",
            "short_liq_notional_15s","long_liq_notional_60s","short_liq_notional_60s",
            "open_interest","oi_change_since_prev_poll_pct","ask_replenishment_proxy_ratio_60s",
            "bid_replenishment_proxy_ratio_60s","book_invalidations","channel_coverage_seconds"
        ):
            v=num(row.get(key))
            if v is not None:x[key]=v

        # Direct ticker / price / OI / funding / 24h context.
        for src,dst in (("lastPrice","ticker_last_price"),("markPrice","mark_price"),("indexPrice","index_price"),
                        ("openInterest","ticker_open_interest"),("fundingRate","funding_rate"),
                        ("volume24h","volume_24h"),("turnover24h","turnover_24h"),
                        ("highPrice24h","high_24h"),("lowPrice24h","low_24h"),("price24hPcnt","price_24h_pct")):
            v=num(self.ticker.get(src))
            if v is not None:x[dst]=v
        mark=x.get("mark_price");index=x.get("index_price")
        if mark and index:x["basis_bps"]=(mark/index-1.0)*10000.0

        self._add_candles(x,price)

        # Executed-trade tape: every raw trade contributes to these causal windows.
        tw={}
        for sec in (5,15,30,60,180,300,900):
            w=self._trade_window(ts,sec);tw[sec]=w
            for k in ("buy_notional","sell_notional","buy_qty","sell_qty","buy_count","sell_count","count","cvd"):
                x[f"trade_{k}_{sec}s"]=float(w[k])
            if w["imbalance"] is not None:x[f"flow_imbalance_raw_{sec}s"]=w["imbalance"]
            r=self._window_return(ts,sec,price)
            if r is not None:
                x[f"ret_{sec}s"]=r
                den=w["buy_notional"]+w["sell_notional"]
                if den>0:
                    x[f"buy_price_response_{sec}s"]=r*w["buy_notional"]/den
                    x[f"sell_price_response_{sec}s"]=-r*w["sell_notional"]/den
                if w["buy_notional"]>0:x[f"buy_efficiency_{sec}s"]=max(r,0.0)/w["buy_notional"]
                if w["sell_notional"]>0:x[f"sell_efficiency_{sec}s"]=max(-r,0.0)/w["sell_notional"]
        if self.last_trade:
            x["last_trade_side"]=float(self.last_trade["side"])
            x["last_trade_price_rel"]=self.last_trade["price"]/price-1.0
            x["last_trade_log_qty"]=math.log1p(self.last_trade["qty"])
            x["last_trade_log_notional"]=math.log1p(self.last_trade["notional"])
            x["last_trade_age_ms"]=max(0.0,ts-self.last_trade["ts_ms"])
        for side in ("buy","sell"):
            e60=x.get(f"{side}_efficiency_60s");e300=x.get(f"{side}_efficiency_300s")
            if finite(e60) and finite(e300) and e300>0:
                x[f"{side}_efficiency_decay_60v300"]=1.0-e60/e300
                x[f"{side}_efficiency_growth_60v300"]=e60/e300-1.0

        flow60=x.get("flow_imbalance_raw_60s",x.get("flow_imbalance_60s"))
        if finite(flow60):
            sg=sign(flow60)
            if not self.dominance_samples or sg!=self.dominance_samples[-1][1]:
                self.dominance_samples.append((ts,sg,abs(flow60)))
            for sec in (60,300,900):
                ds=[z for z in self.dominance_samples if z[0]>=ts-sec*1000]
                x[f"dominance_transitions_{sec}s"]=float(max(0,len(ds)-1))
                if ds:x[f"dominance_last_transition_age_{sec}s"]=float(ts-ds[-1][0])
            prior=[z[2] for z in list(self.dominance_samples)[:-1][-10:]]
            if prior:x["current_vs_prior_reversal_strength"]=abs(flow60)-statistics.median(prior)
            x["current_reversal_attempt_active"]=1.0 if finite(x.get("flow_imbalance_raw_300s")) and sign(flow60)!=sign(x["flow_imbalance_raw_300s"]) else 0.0

        # Price persistence, running extremes and retracement/survival.
        for sec in (30,60,180,300,900):
            ps=[(t,p) for t,p in self.prices if t>=ts-sec*1000]
            if len(ps)>=2:
                diffs=[b/a-1.0 for (_,a),(_,b) in zip(ps,ps[1:]) if a>0]
                if diffs:
                    x[f"positive_persistence_{sec}s"]=sum(d>0 for d in diffs)/len(diffs)
                    x[f"negative_persistence_{sec}s"]=sum(d<0 for d in diffs)/len(diffs)
                hi_t,hi=max(ps,key=lambda z:z[1]);lo_t,lo=min(ps,key=lambda z:z[1])
                x[f"running_high_{sec}s"]=hi;x[f"running_low_{sec}s"]=lo
                x[f"dist_running_high_{sec}s"]=price/hi-1.0
                x[f"dist_running_low_{sec}s"]=price/lo-1.0
                span=hi-lo
                if span>0:
                    x[f"retracement_from_high_{sec}s"]=(hi-price)/span
                    x[f"retracement_from_low_{sec}s"]=(price-lo)/span
                x[f"survival_since_high_{sec}s"]=(ts-hi_t)/1000.0
                x[f"survival_since_low_{sec}s"]=(ts-lo_t)/1000.0

        # Full L50 representation: every current level becomes a model feature.
        bids=sorted(self.book_bids.items(),reverse=True)[:50]
        asks=sorted(self.book_asks.items())[:50]
        x["book_valid_raw"]=1.0 if self.book_valid else 0.0
        x["book_bid_levels"]=float(len(bids));x["book_ask_levels"]=float(len(asks))
        if self.book_update_id is not None:x["book_update_id_raw"]=float(self.book_update_id)
        if self.book_sequence is not None:x["book_sequence_raw"]=float(self.book_sequence)
        x["book_invalidations_raw"]=float(self.book_invalidations)
        for side,levels in (("bid",bids),("ask",asks)):
            for i,(p,q) in enumerate(levels,1):
                x[f"l50_{side}_{i:02d}_dist_bps"]=(p/price-1.0)*10000.0
                x[f"l50_{side}_{i:02d}_log_qty"]=math.log1p(max(0.0,q))
        for sec in (5,15,60):
            changes=[c for t,c in self.book_changes if t>=ts-sec*1000]
            for k in ("bid_add","bid_cancel","ask_add","ask_cancel"):
                x[f"book_{k}_{sec}s"]=sum(c[k] for c in changes)
        if tw.get(60):
            badd=x.get("book_bid_add_60s",0.0);aadd=x.get("book_ask_add_60s",0.0)
            sell=tw[60]["sell_notional"];buy=tw[60]["buy_notional"]
            if sell>0:x["bid_absorption_proxy_60s"]=badd/sell
            if buy>0:x["ask_absorption_proxy_60s"]=aadd/buy

        # OI and price/OI interaction.
        current_oi=num(x.get("open_interest")) or num(self.ticker.get("openInterest"))
        oi_now=self._oi_at(ts)
        if oi_now:current_oi=oi_now[1];x["oi_age_ms"]=float(ts-oi_now[0])
        if current_oi:
            x["open_interest_full"]=current_oi
            for sec in (30,60,180,300,900):
                past=self._oi_at(ts-sec*1000)
                if past and past[1]>0:
                    d=current_oi/past[1]-1.0
                    x[f"oi_delta_{sec}s"]=d
                    r=x.get(f"ret_{sec}s")
                    if finite(r):x[f"price_oi_interaction_{sec}s"]=r*d
            x["oi_notional"]=current_oi*price
            x["log_oi_notional"]=math.log1p(max(0.0,current_oi*price))

        # Liquidation event detail, aggregates, clusters and cross-effects.
        for sec in (5,15,60,300):
            w=self._liq_window(ts,sec)
            x[f"liq_long_notional_raw_{sec}s"]=w["long"]
            x[f"liq_short_notional_raw_{sec}s"]=w["short"]
            x[f"liq_count_{sec}s"]=float(w["count"])
            x[f"liq_notional_{sec}s"]=w["notional"]
        if self.last_liq:
            x["last_liq_side"]=float(self.last_liq["side"])
            x["last_liq_price_rel"]=self.last_liq["price"]/price-1.0
            x["last_liq_log_qty"]=math.log1p(self.last_liq["qty"])
            x["last_liq_log_notional"]=math.log1p(self.last_liq["notional"])
            x["last_liq_age_ms"]=float(max(0,ts-self.last_liq["ts_ms"]))
        if x.get("liq_count_60s",0)>0:
            x["liq_cluster_ratio_5v60"]=(x.get("liq_count_5s",0)+1.0)/(x["liq_count_60s"]/12.0+1.0)
            x["liq_burst_notional_ratio_5v60"]=(x.get("liq_notional_5s",0)+1.0)/(x["liq_notional_60s"]/12.0+1.0)
            if finite(x.get("ret_60s")):x["liq_burst_x_price_60s"]=x["liq_notional_60s"]*x["ret_60s"]
            if finite(flow60):x["liq_burst_x_flow_60s"]=x["liq_notional_60s"]*flow60
            if finite(x.get("oi_delta_60s")):x["liq_burst_x_oi_60s"]=x["liq_notional_60s"]*x["oi_delta_60s"]

        # Structural rolling context and public positioning.
        c=self.structural
        for k in ("rolling_60m_high","rolling_60m_low","rolling_6h_high","rolling_6h_low","rolling_24h_high","rolling_24h_low"):
            v=num(c.get(k))
            if v is not None:
                x[k]=v;x["dist_"+k]=price/v-1.0
        for k in ("mark_price","index_price","basis_bps","funding_rate","volume_24h","turnover_24h",
                  "runner_clock_offset_ms","long_holder_ratio","short_holder_ratio","long_short_holder_ratio","oi_notional"):
            v=num(c.get(k))
            if v is not None:x["struct_"+k]=v
        ar=self.account_ratio
        for src,dst in (("buyRatio","account_buy_ratio"),("sellRatio","account_sell_ratio")):
            v=num(ar.get(src))
            if v is not None:x[dst]=v

        # Instrument contract/risk metadata is part of the 110+ state.
        if self.instrument:self._flatten_numeric("instrument",self.instrument,x)

        # Timestamp / continuity / transport quality.
        x["raw_frames_seen"]=float(self.raw_frames)
        if self.ws_server_ts_ms is not None:
            x["ws_server_ts_ms_mod_day"]=float(self.ws_server_ts_ms % 86_400_000)
        if self.ws_clock_offset_ms is not None:
            x["ws_runner_clock_offset_ms"]=float(self.ws_clock_offset_ms)
        x["receipt_sequence_gaps"]=float(self.receipt_sequence_gaps)
        x["subscription_acks"]=float(self.subscription_acks)
        x["control_frames"]=float(self.control_frames)
        if self.last_raw_received_ts is not None:x["raw_age_ms"]=float(max(0,ts-self.last_raw_received_ts))
        for kind,q in self.latencies.items():
            if q:
                x[f"{kind}_latency_last_ms"]=float(q[-1])
                x[f"{kind}_latency_mean_ms"]=statistics.fmean(q)
                if len(q)>=10:
                    z=sorted(q);x[f"{kind}_latency_p95_ms"]=float(z[min(len(z)-1,int(.95*(len(z)-1)))])
        x["book_valid_micro"]=1.0 if row.get("book_valid") else 0.0
        if isinstance(self.market_context,dict):
            x["rest_only_complete"]=1.0 if self.market_context.get("rest_only_complete") else 0.0
            x["rest_relay_configured"]=1.0 if self.market_context.get("rest_relay_configured") else 0.0

        # Log-scale the largest positive market-size fields while retaining raw.
        for k,v in list(x.items()):
            if not finite(v):continue
            if ("notional" in k or "depth" in k or k.endswith("_volume") or k in ("volume_24h","turnover_24h")) and v>=0:
                x["log_"+k]=math.log1p(v)

        # Mark only families that are actually present in this state.
        self._mark(78,79,116)
        if self.trades:
            self._mark(12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,41,42,43)
        if bids or asks:
            self._mark(44,45,46,47,48,49,50,51,52,53,54,55,56,57)
        if current_oi is not None:
            self._mark(58,59,60,61)
        if any(k in x for k in ("funding_rate","volume_24h","turnover_24h")):
            self._mark(62,63,64)
        if self.liqs or any(k.startswith("liq_") for k in x):
            self._mark(65,66,67,68,69,70,71,72,73,74,75,76)
        if self.last_raw_received_ts is not None:
            self._mark(77,80,116)
        if self.server_time or "struct_runner_clock_offset_ms" in x:
            self._mark(111)
        if self.instrument:
            self._mark(112)
        if self.account_ratio or "struct_long_short_holder_ratio" in x:
            self._mark(113)
        if "basis_bps" in x or "struct_basis_bps" in x:
            self._mark(114)
        if "oi_notional" in x or "struct_oi_notional" in x:
            self._mark(115)

        # Remove any nonfinite values before the learner sees them.
        x={k:float(v) for k,v in x.items() if finite(v)}
        self.feature_names_seen.update(x)
        self.max_feature_count=max(self.max_feature_count,len(x))
        self.last_ts_ms=ts;self.last_price=price
        return price,x
