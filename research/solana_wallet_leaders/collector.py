#!/usr/bin/env python3
"""Research-only Solana wallet leader discovery. No orders or keys."""
import collections, datetime, json, os, pathlib, time, urllib.request
ROOT=pathlib.Path("research/solana_wallet_leaders")
ROOT.mkdir(parents=True,exist_ok=True)
STATE=ROOT/"state.json"
REPORT=ROOT/"latest_report.json"
RPC=os.getenv("SOLANA_RPC_URL","https://api.mainnet-beta.solana.com")
UA={"User-Agent":"pandora-wallet-research/0.1"}
def fetch(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=18) as r:return json.load(r)
def rpc(method,params):
    req=urllib.request.Request(RPC,data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode(),headers={"Content-Type":"application/json",**UA})
    with urllib.request.urlopen(req,timeout=22) as r:
        data=json.load(r)
    if "error" in data:raise RuntimeError(str(data["error"]))
    return data.get("result")
def load():
    try:return json.loads(STATE.read_text())
    except (FileNotFoundError,ValueError):return {"tokens":{},"observations":[]}
def discover():
    out=[]
    for url in ("https://api.dexscreener.com/token-profiles/latest/v1","https://api.dexscreener.com/token-boosts/latest/v1"):
        try:
            for item in fetch(url):
                if item.get("chainId")=="solana" and item.get("tokenAddress"):
                    out.append(item["tokenAddress"])
        except Exception as exc:print("discovery_error",str(exc))
    return list(dict.fromkeys(out))[:int(os.getenv("MAX_TOKENS","12"))]
def main():
    state=load()
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    tokens=discover()
    errors=[]
    new=0
    for mint in tokens:
        prior=set(state["tokens"].get(mint,[]))
        try:
            sigs=rpc("getSignaturesForAddress",[mint,{"limit":min(int(os.getenv("SIGNATURES_PER_TOKEN","25")),100)}]) or []
            fresh=[s for s in reversed(sigs) if s.get("signature") and s["signature"] not in prior and s.get("err") is None]
            for sig in fresh:
                signature=sig["signature"]
                try:
                    tx=rpc("getTransaction",[signature,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}])
                    if not tx or not tx.get("meta"):continue
                    message=tx["transaction"]["message"]
                    keys=message.get("accountKeys",[])
                    signers=[k["pubkey"] for k in keys if isinstance(k,dict) and k.get("signer")]
                    if not signers:continue
                    pre=collections.defaultdict(int)
                    post=collections.defaultdict(int)
                    for b in tx["meta"].get("preTokenBalances",[]):
                        if b.get("mint")==mint:pre[b.get("owner","")]+=int(b["uiTokenAmount"]["amount"])
                    for b in tx["meta"].get("postTokenBalances",[]):
                        if b.get("mint")==mint:post[b.get("owner","")]+=int(b["uiTokenAmount"]["amount"])
                    for owner in set(pre)|set(post):
                        delta=post[owner]-pre[owner]
                        if delta>0 and owner in signers:
                            state["observations"].append({"mint":mint,"wallet":owner,"signature":signature,"slot":sig.get("slot"),"block_time":sig.get("blockTime"),"token_delta_raw":str(delta)})
                            new+=1
                except Exception as exc:errors.append("transaction "+str(exc)[:160])
                time.sleep(0.12)
            state["tokens"][mint]=list(dict.fromkeys([s["signature"] for s in sigs if s.get("signature")]+list(prior)))[:250]
        except Exception as exc:errors.append("mint "+mint+" "+str(exc)[:160])
        time.sleep(0.25)
    state["observations"]=state["observations"][-25000:]
    grouped=collections.defaultdict(list)
    for o in state["observations"]:grouped[o["mint"]].append(o)
    pairs=collections.defaultdict(lambda:{"count":0,"delays":[],"examples":[]})
    for mint,obs in grouped.items():
        obs=sorted([o for o in obs if o.get("block_time")],key=lambda x:(x["block_time"],x.get("slot") or 0))
        for i,a in enumerate(obs):
            seen=set()
            for b in obs[i+1:]:
                dt=b["block_time"]-a["block_time"]
                if dt>600:break
                if dt<=0 or b["wallet"]==a["wallet"] or b["wallet"] in seen:continue
                seen.add(b["wallet"])
                p=pairs[(a["wallet"],b["wallet"])]
                p["count"]+=1;p["delays"].append(dt)
                if len(p["examples"])<4:p["examples"].append({"mint":mint,"leader_tx":a["signature"],"follower_tx":b["signature"],"delay_seconds":dt})
    leaders=[]
    for (a,b),p in pairs.items():
        if p["count"]>=2:
            leaders.append({"leader":a,"follower":b,"observed_sequences":p["count"],"median_delay_seconds":sorted(p["delays"])[len(p["delays"])//2],"examples":p["examples"],"status":"unverified_candidate"})
    leaders.sort(key=lambda x:(-x["observed_sequences"],-x["median_delay_seconds"]))
    REPORT.write_text(json.dumps({"generated_at":now,"tokens_sampled":len(tokens),"new_buy_observations":new,"total_buy_observations":len(state["observations"]),"candidate_pairs":leaders[:30],"errors":errors[:15],"limitations":["DEX Screener discovery is not exhaustive Pump.fun coverage","Mint-address RPC signatures may omit swaps","Only signer-owned positive token balance changes counted","Sequence is not proof of shared ownership or future buys","No execution price, liquidity, fees, or verified net PnL yet","No wallet is approved for copytrading"]},ensure_ascii=False,indent=2)+"\n")
    STATE.write_text(json.dumps(state,ensure_ascii=False,separators=(",",":"))+"\n")
    print(f"sampled={len(tokens)} new={new} candidates={len(leaders)} errors={len(errors)}")
if __name__=="__main__":main()
