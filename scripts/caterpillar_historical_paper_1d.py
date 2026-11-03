from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse, heapq, json, math
from research.caterpillar.caterpillar.sources import Archives
from caterpillar_paper.config import Config
from caterpillar_paper.engine import Engine
from caterpillar_paper.storage import Store, atomic_json

SYMS=("AAVE","DOGE","SUI","WLD","1000PEPE")

def h1_from_archive(src,symbol,day):
    it,_=src.trades(symbol,day); bars={}
    for t in it:
        h=math.floor(t.ts/3600)*3600
        b=bars.get(h)
        if b is None:
            bars[h]={"open_ts":h,"available_ts":h+3600,"open":t.price,"high":t.price,"low":t.price,"close":t.price,"volume":t.quantity,"timeframe":"1h","interval_minutes":60}
        else:
            b["high"]=max(b["high"],t.price); b["low"]=min(b["low"],t.price); b["close"]=t.price; b["volume"]+=t.quantity
    return bars

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--cache",type=Path,required=True)
    a=ap.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    start=datetime(2026,11,2,tzinfo=timezone.utc); prev=start-timedelta(days=1); end=start+timedelta(days=1)
    src=Archives(a.cache); h1={}; day_meta={}; streams={}
    for s in SYMS:
        h1[s]={**h1_from_archive(src,s,prev),**h1_from_archive(src,s,start)}
        streams[s],day_meta[s]=src.trades(s,start)
    cfg=Config(paper_symbols=SYMS)
    store=Store(a.output); e=Engine(cfg,store,run_id="historical-2026-11-02")
    instruments={s:{"status":"Trading","pair":s+"USDT","max_leverage":25.0,"lot_size":{},"historical_replay_note":"continuous quantity; PAPER risk/cost model unchanged"} for s in SYMS}
    e.set_active(list(SYMS),{s:{"reason":"HISTORICAL_FIXED_UNIVERSE","observed_at":start.timestamp()} for s in SYMS},instruments,start.timestamp())
    for s in SYMS:
        candles=[h1[s][k] for k in sorted(h1[s]) if prev.timestamp()<=k<start.timestamp()]
        e.seed_h1(s,candles,start.timestamp()); e._memory(s)["connected"]=True
    heap=[]
    for s,it in streams.items():
        try:t=next(it); heapq.heappush(heap,(t.ts,s,t,it))
        except StopIteration:pass
    next_boundary=start.timestamp()+3600; last_marks={}; accepted={s:0 for s in SYMS}
    while heap:
        ts,s,t,it=heapq.heappop(heap)
        while ts>=next_boundary and next_boundary<end.timestamp():
            opened=next_boundary-3600
            for sym in SYMS:
                b=h1[s].get(opened)
                if b:e.seed_h1(sym,[b],next_boundary)
            next_boundary+=3600
        e._memory(s)["connected"]=True
        if e.on_trade(s,t.ts,t.price,t.quantity,int(t.side),str(t.trade_id),t.ts,now=t.ts):
            accepted[s]+=1; last_marks[s]=(t.price,t.ts)
        try:n=next(it); heapq.heappush(heap,(n.ts,s,n,it))
        except StopIteration:pass
    # Seed the final completed H1 causally at midnight, then liquidate remaining PAPER positions at last real marks.
    for sym in SYMS:
        b=h1[s].get(end.timestamp()-3600)
        if b:e.seed_h1(sym,[b],end.timestamp())
    for sym in list(e.s["positions"]):
        mark,ts=last_marks[sym]; e._close(sym,mark,ts,"END_OF_DAY_MARK_TO_MARKET")
    e.save()
    closed=e.s["closed"]; pnl=sum(x["pnl"] for x in closed); fees=sum(x["fees"] for x in closed)
    per={}
    for s in SYMS:
        xs=[x for x in closed if x["symbol"]==s]
        per[s]={"trades":len(xs),"pnl":sum(x["pnl"] for x in xs),"fees":sum(x["fees"] for x in xs),
                "wins":sum(x["pnl"]>0 for x in xs),"losses":sum(x["pnl"]<=0 for x in xs),
                "reentries":sum(x["kind"]=="REENTRY" for x in xs),"mfe":sum(x["mfe"] for x in xs),"mae":sum(x["mae"] for x in xs)}
    report={"status":"completed","period":["2026-11-02T00:00:00Z","2026-11-03T00:00:00Z"],"symbols":list(SYMS),
      "start_equity":cfg.start_equity,"final_equity":e.s["cash"],"net_pnl":pnl,"return_pct":100*pnl/cfg.start_equity,
      "closed_trades":len(closed),"wins":sum(x["pnl"]>0 for x in closed),"losses":sum(x["pnl"]<=0 for x in closed),
      "fees":fees,"max_equity":e.s["max_equity"],"max_drawdown_pct":100*e.s["max_drawdown"],"accepted_ticks":accepted,
      "per_symbol":per,"config":{"margin_fraction":cfg.margin_fraction,"leverage":cfg.leverage,"fee_bps":cfg.fee_bps,
      "slippage_bps":cfg.slippage_bps,"block_trades":cfg.block_trades,"warmup_blocks":cfg.warmup_blocks,
      "transfer_blocks":cfg.transfer_blocks,"control_imbalance":cfg.control_imbalance,"pyramiding":cfg.pyramiding},
      "data":day_meta,"note":"Causal chronological five-symbol replay. H1 derived from executed trades and revealed only after each hour closes. Open positions are marked out at each symbol's last real trade of the UTC day."}
    atomic_json(a.output/"RESULT.json",report)
    (a.output/"TRADES.json").write_text(json.dumps(closed,allow_nan=False))
    print("CATERPILLAR_PAPER_1D_RESULT "+json.dumps(report,allow_nan=False),flush=True)

if __name__=="__main__": main()
