#!/usr/bin/env python3
"""Three-month Pump.fun historical wallet graph crawler.

Research-only. No private keys and no order submission.

The crawler walks the Pump.fun program history backwards from "now" to
2026-08-06, derives signer-owned buy/sell balance deltas, identifies tokens
whose observed bonding-curve price proxy later reached >=2x, and retains the
earliest buyers of those pumped tokens. It then ranks wallets by repeated early
entries and builds co-entry / leader-follower relationships.

State is gzip-compressed so GitHub Actions cache can resume the crawl without
committing a huge history file into the repository.
"""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import json
import math
import os
import pathlib
import statistics
import time
import urllib.error
import urllib.request
from typing import Any

ROOT=pathlib.Path("research/solana_wallet_leaders")
ROOT.mkdir(parents=True,exist_ok=True)
STATE=ROOT/"three_month_state.json.gz"
REPORT=ROOT/"three_month_report.json"
DORADO=ROOT/"three_month_dorado_candidates.yaml"

PUMP_PROGRAM=os.getenv("PUMPFUN_PROGRAM_ID","6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
CUTOFF_ISO=os.getenv("HISTORY_START","2026-08-06T00:00:00+00:00")
CUTOFF_TS=int(dt.datetime.fromisoformat(CUTOFF_ISO.replace("Z","+00:00")).timestamp())
PUMP_THRESHOLD=max(1.25,float(os.getenv("PUMP_THRESHOLD","2.0")))
EARLY_WALLETS_PER_TOKEN=max(10,int(os.getenv("EARLY_WALLETS_PER_TOKEN","30")))
MAX_SIGNATURES=max(1000,int(os.getenv("MAX_SIGNATURES_PER_CHUNK","12000")))
BATCH_SIZE=max(5,min(40,int(os.getenv("TX_BATCH_SIZE","20"))))
MAX_RUNTIME=max(120,int(os.getenv("MAX_RUNTIME_SECONDS","3000")))
MIN_TRADE_SOL=max(0.0001,float(os.getenv("MIN_TRADE_SOL","0.002")))
WSOL="So11111111111111111111111111111111111111112"

def _rpc_urls()->list[str]:
    vals=[]
    one=(os.getenv("SOLANA_RPC_URL") or "").strip()
    if one: vals.append(one)
    many=(os.getenv("SOLANA_RPC_URLS") or "").strip()
    if many: vals.extend(x.strip() for x in many.split(",") if x.strip())
    vals += ["https://api.mainnet-beta.solana.com","https://rpc.solanatracker.io/public"]
    out=[]
    for x in vals:
        if x and x not in out: out.append(x)
    return out
RPC_URLS=_rpc_urls()
_rpc_index=0

def now_iso(): return dt.datetime.now(dt.timezone.utc).isoformat()

def load_state()->dict[str,Any]:
    try:
        with gzip.open(STATE,"rt",encoding="utf-8") as f: s=json.load(f)
        if s.get("version")==3: return s
    except Exception: pass
    return {
        "version":3,"cutoff_ts":CUTOFF_TS,"before":None,"complete":False,
        "signatures_scanned":0,"transactions_decoded":0,"trade_events":0,
        "oldest_block_time":None,"active_tokens":{},"pumped_tokens":{},
        "rpc_errors":0,"started_at":now_iso(),"updated_at":now_iso()
    }

def save_state(s):
    tmp=STATE.with_suffix(".tmp.gz")
    with gzip.open(tmp,"wt",encoding="utf-8",compresslevel=6) as f:
        json.dump(s,f,separators=(",",":"),ensure_ascii=False)
    tmp.replace(STATE)

def post_json(payload, retries=7):
    global _rpc_index
    body=json.dumps(payload,separators=(",",":")).encode()
    last=None
    for attempt in range(retries):
        url=RPC_URLS[_rpc_index%len(RPC_URLS)]
        req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json","User-Agent":"pandora-pumpfun-3m/1.0"})
        try:
            with urllib.request.urlopen(req,timeout=35) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            last=exc
            if exc.code in (401,429,403,502,503,504):
                _rpc_index+=1
                time.sleep(min(6.0,0.35*(2**attempt)))
                continue
            raise
        except Exception as exc:
            last=exc;_rpc_index+=1;time.sleep(min(5.0,0.25*(2**attempt)))
    raise RuntimeError(f"all RPC endpoints failed: {last}")

def rpc(method,params):
    data=post_json({"jsonrpc":"2.0","id":1,"method":method,"params":params})
    if isinstance(data,dict) and data.get("error"): raise RuntimeError(str(data["error"]))
    return data.get("result") if isinstance(data,dict) else None

def tx_batch(signatures:list[str])->dict[str,dict[str,Any]|None]:
    reqs=[{"jsonrpc":"2.0","id":i,"method":"getTransaction","params":[sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":1}]} for i,sig in enumerate(signatures)]
    data=post_json(reqs)
    if not isinstance(data,list): return {}
    byid={int(x.get("id")):x for x in data if isinstance(x,dict) and x.get("id") is not None}
    out={}
    for i,sig in enumerate(signatures):
        row=byid.get(i,{})
        out[sig]=None if row.get("error") else row.get("result")
    return out

def signature_page(before):
    cfg={"limit":1000}
    if before: cfg["before"]=before
    return rpc("getSignaturesForAddress",[PUMP_PROGRAM,cfg]) or []

def account_keys(msg):
    keys=[];signers=set()
    for x in msg.get("accountKeys") or []:
        if isinstance(x,dict):
            p=str(x.get("pubkey") or "")
            if p:
                keys.append(p)
                if x.get("signer"): signers.add(p)
        elif isinstance(x,str): keys.append(x)
    return keys,signers

def owner_token_deltas(meta):
    pre={};post={};decimals={}
    for row in meta.get("preTokenBalances") or []:
        owner=str(row.get("owner") or "");mint=str(row.get("mint") or "")
        if not owner or not mint: continue
        ui=row.get("uiTokenAmount") or {}
        pre[(owner,mint)]=int(ui.get("amount") or 0);decimals[mint]=int(ui.get("decimals") or 0)
    for row in meta.get("postTokenBalances") or []:
        owner=str(row.get("owner") or "");mint=str(row.get("mint") or "")
        if not owner or not mint: continue
        ui=row.get("uiTokenAmount") or {}
        post[(owner,mint)]=int(ui.get("amount") or 0);decimals[mint]=int(ui.get("decimals") or 0)
    out=collections.defaultdict(dict)
    for key in set(pre)|set(post):
        owner,mint=key;d=post.get(key,0)-pre.get(key,0)
        if d: out[owner][mint]=(d,decimals.get(mint,0))
    return out

def parse_events(sigrow,tx):
    meta=(tx or {}).get("meta") or {}
    if not meta or meta.get("err"): return []
    msg=((tx or {}).get("transaction") or {}).get("message") or {}
    keys,signers=account_keys(msg)
    if PUMP_PROGRAM not in keys: return []
    idx={k:i for i,k in enumerate(keys)}
    prebal=meta.get("preBalances") or [];postbal=meta.get("postBalances") or []
    fee=float(meta.get("fee") or 0)/1e9
    deltas=owner_token_deltas(meta)
    ts=int(sigrow.get("blockTime") or tx.get("blockTime") or 0)
    logs="\n".join(meta.get("logMessages") or [])
    is_create=("Instruction: Create" in logs or "Instruction: CreateV2" in logs)
    events=[]
    for owner,mints in deltas.items():
        if signers and owner not in signers: continue
        assets=[(m,v) for m,v in mints.items() if m.endswith("pump")]
        if not assets: continue
        oi=idx.get(owner)
        native=0.0
        if oi is not None and oi<len(prebal) and oi<len(postbal):
            native=(float(postbal[oi])-float(prebal[oi]))/1e9
        for mint,(raw,dec) in assets:
            qty=raw/(10**dec if dec>=0 else 1)
            if not qty: continue
            quote_amt=None;quote_mint="SOL"
            if WSOL in mints:
                qraw,qdec=mints[WSOL]; quote_amt=abs(qraw)/(10**qdec);quote_mint=WSOL
            if quote_amt is None:
                quote_amt=abs(native)
                if raw>0: quote_amt=max(0.0,-native-fee)
                else: quote_amt=max(0.0,native)
            if quote_amt<MIN_TRADE_SOL: continue
            side="BUY" if raw>0 else "SELL"
            price=quote_amt/abs(qty)
            if not math.isfinite(price) or price<=0: continue
            events.append({"mint":mint,"wallet":owner,"side":side,"price":price,
                           "quote_amount":quote_amt,"quote_mint":quote_mint,
                           "ts":ts,"slot":int(sigrow.get("slot") or 0),
                           "signature":sigrow.get("signature"),"is_create":is_create})
    return events

def tier(mult):
    if mult>=100:return "X100+"
    if mult>=50:return "X50+"
    if mult>=20:return "X20+"
    if mult>=10:return "X10+"
    if mult>=5:return "X5+"
    if mult>=2:return "X2+"
    return "LT_X2"

def _token_state():
    return {"max_price":0.0,"peak_ts":0,"max_multiple":1.0,"first_ts":None,"last_ts":None,
            "trade_events":0,"pumped":False,"early_wallets":{},"created_seen":False}

def update_token(state,e):
    mint=e["mint"];active=state["active_tokens"];final=state["pumped_tokens"]
    if mint in final: return
    t=active.setdefault(mint,_token_state())
    ts=e["ts"];price=e["price"]
    t["trade_events"]+=1
    t["first_ts"]=ts if t["first_ts"] is None else min(t["first_ts"],ts)
    t["last_ts"]=ts if t["last_ts"] is None else max(t["last_ts"],ts)
    if price>t["max_price"]:
        t["max_price"]=price;t["peak_ts"]=ts
    if price>0 and t["max_price"]>0:
        mult=t["max_price"]/price
        if mult>t["max_multiple"]: t["max_multiple"]=mult
        if mult>=PUMP_THRESHOLD: t["pumped"]=True
    if t["pumped"] and e["side"]=="BUY" and ts<=t["peak_ts"]:
        w=e["wallet"];row=t["early_wallets"].get(w)
        cand={"ts":ts,"price":price,"quote_amount":e["quote_amount"],"signature":e["signature"],
              "multiple_to_peak":t["max_price"]/price if price else None}
        if row is None or ts<row["ts"]: t["early_wallets"][w]=cand
        if len(t["early_wallets"])>EARLY_WALLETS_PER_TOKEN*2:
            keep=sorted(t["early_wallets"].items(),key=lambda kv:kv[1]["ts"])[:EARLY_WALLETS_PER_TOKEN]
            t["early_wallets"]=dict(keep)
    if e.get("is_create"):
        t["created_seen"]=True
        if t["pumped"]:
            t["early_wallets"]=dict(sorted(t["early_wallets"].items(),key=lambda kv:kv[1]["ts"])[:EARLY_WALLETS_PER_TOKEN])
            t["tier"]=tier(t["max_multiple"]);final[mint]=t
        active.pop(mint,None)

def build_report(s):
    pumped=s["pumped_tokens"]
    wallet=collections.defaultdict(lambda:{"tokens":[],"tiers":collections.Counter(),"entry_ranks":[],"multiples":[]})
    co=collections.Counter();lead=collections.Counter()
    tier_counts=collections.Counter()
    for mint,t in pumped.items():
        tier_counts[tier(t.get("max_multiple",1.0))]+=1
        early=sorted(t.get("early_wallets",{}).items(),key=lambda kv:kv[1]["ts"])
        for rank,(w,row) in enumerate(early,1):
            d=wallet[w];d["tokens"].append(mint);d["tiers"][tier(t.get("max_multiple",1.0))]+=1
            d["entry_ranks"].append(rank)
            if row.get("multiple_to_peak"):d["multiples"].append(float(row["multiple_to_peak"]))
        first=[w for w,_ in early[:12]]
        for i,a in enumerate(first):
            for b in first[i+1:]:
                co[tuple(sorted((a,b)))]+=1;lead[(a,b)]+=1
    rows=[]
    for w,d in wallet.items():
        n=len(d["tokens"]);medrank=statistics.median(d["entry_ranks"]) if d["entry_ranks"] else None
        medmult=statistics.median(d["multiples"]) if d["multiples"] else None
        score=min(100.0,n*9.0+(25.0 if medrank and medrank<=3 else 12.0 if medrank and medrank<=8 else 0.0)+
                  min(25.0,(medmult or 1.0)*2.5))
        conf="HIGH" if n>=8 else "MEDIUM" if n>=4 else "LOW"
        profile="INSIDER_CANDIDATE" if n>=4 and (medrank or 99)<=5 else "REPEAT_SNIPER" if n>=3 else "OBSERVED"
        rows.append({"wallet":w,"score":round(score,3),"profile":profile,"confidence":conf,
                     "pumped_tokens_entered":n,"median_early_rank":medrank,
                     "median_observed_multiple_to_peak":round(medmult,3) if medmult else None,
                     "tiers":dict(d["tiers"]),"sample_tokens":d["tokens"][:20],
                     "live_copytrade_approved":False})
    rows.sort(key=lambda x:(-x["score"],-x["pumped_tokens_entered"],x["median_early_rank"] or 999))
    pairs=[{"wallet_a":a,"wallet_b":b,"shared_pumped_tokens":n} for (a,b),n in co.most_common(100) if n>=2]
    leaders=[{"leader":a,"follower":b,"leader_before_follower_tokens":n} for (a,b),n in lead.most_common(100) if n>=2]
    progress=0.0
    if s.get("oldest_block_time"):
        start=int(dt.datetime(2026,11,6,tzinfo=dt.timezone.utc).timestamp())
        denom=max(1,start-CUTOFF_TS);progress=max(0.0,min(1.0,(start-int(s["oldest_block_time"]))/denom))
    return {"generated_at":now_iso(),"research_only":True,"history_start":CUTOFF_ISO,
            "history_end":"2026-11-06T23:59:59+00:00","pump_definition":f"observed Pump.fun bonding-curve price proxy >= {PUMP_THRESHOLD:.2f}x",
            "progress":{"complete":bool(s.get("complete")),"approx_time_coverage_pct":round(progress*100,3),
                        "oldest_block_time":s.get("oldest_block_time"),"signatures_scanned":s.get("signatures_scanned",0),
                        "transactions_decoded":s.get("transactions_decoded",0),"trade_events":s.get("trade_events",0),
                        "active_tokens":len(s.get("active_tokens",{})),"pumped_tokens_finalized":len(pumped)},
            "pump_tiers":dict(tier_counts),"top_wallets":rows[:250],
            "top_insider_candidates":[x for x in rows if x["profile"]=="INSIDER_CANDIDATE"][:100],
            "top_repeat_snipers":[x for x in rows if x["profile"]=="REPEAT_SNIPER"][:100],
            "co_entry_pairs":pairs,"leader_follower_links":leaders,
            "limitations":["Pump.fun bonding-curve program only in this pass; post-migration PumpSwap ATH is not yet used for the pump multiple.",
                           "Balance-delta price is a causal on-chain proxy and may include fee/rent noise.",
                           "Wallet relationship means repeated temporal/co-entry evidence, not proof of common ownership or privileged information.",
                           "No wallet is approved for live copy trading."]}

def write_outputs(report):
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    c=[x for x in report["top_wallets"] if x["pumped_tokens_entered"]>=3][:150]
    lines=["# Auto-generated 3-month Pump.fun research candidates","# RESEARCH ONLY — not approved for funded live copy trading.","kol_wallets: []","wallets:"]
    if not c: lines.append("  []")
    for i,x in enumerate(c,1):
        lines += [f"  - address: {x['wallet']}",f"    name: pump3m-{x['profile'].lower()}-{i:03d}",
                  "    type: smart_money",f"    priority: {1 if x['score']>=80 else 2 if x['score']>=65 else 3}",
                  f"    trust: {max(.5,min(.99,x['score']/100)):.2f}","    live_copytrade_approved: false",
                  f"    evidence_pumped_tokens: {x['pumped_tokens_entered']}"]
    DORADO.write_text("\n".join(lines)+"\n",encoding="utf-8")

def run_chunk():
    s=load_state()
    if s.get("complete"):
        r=build_report(s);write_outputs(r);return r
    t0=time.time();processed=0
    while processed<MAX_SIGNATURES and time.time()-t0<MAX_RUNTIME:
        page=signature_page(s.get("before"))
        if not page:
            s["complete"]=True;break
        eligible=[]
        reached=False
        for row in page:
            bt=int(row.get("blockTime") or 0)
            if bt and bt<CUTOFF_TS:
                reached=True;break
            if row.get("signature") and row.get("err") is None: eligible.append(row)
        for i in range(0,len(eligible),BATCH_SIZE):
            if time.time()-t0>=MAX_RUNTIME: break
            chunk=eligible[i:i+BATCH_SIZE];sigs=[x["signature"] for x in chunk]
            try: txs=tx_batch(sigs)
            except Exception:
                s["rpc_errors"]=int(s.get("rpc_errors",0))+1;time.sleep(1.0);continue
            for row in chunk:
                tx=txs.get(row["signature"])
                if tx:
                    s["transactions_decoded"]+=1
                    for e in parse_events(row,tx):
                        s["trade_events"]+=1;update_token(s,e)
                processed+=1;s["signatures_scanned"]+=1
                bt=int(row.get("blockTime") or 0)
                if bt: s["oldest_block_time"]=bt if s.get("oldest_block_time") is None else min(int(s["oldest_block_time"]),bt)
        s["before"]=page[-1].get("signature")
        if reached:
            s["complete"]=True;break
        if len(page)<1000:
            s["complete"]=True;break
        save_state(s)
        print(json.dumps({"phase":"crawl","chunk_signatures":processed,"total_signatures":s["signatures_scanned"],
                          "oldest_block_time":s.get("oldest_block_time"),"active_tokens":len(s["active_tokens"]),
                          "pumped_finalized":len(s["pumped_tokens"]),"rpc_errors":s.get("rpc_errors",0)}),flush=True)
    s["updated_at"]=now_iso();save_state(s)
    r=build_report(s);write_outputs(r)
    print("PUMPFUN_3M_RESULT="+json.dumps(r["progress"],separators=(",",":")),flush=True)
    return r

if __name__=="__main__": run_chunk()
