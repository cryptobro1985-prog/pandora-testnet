#!/usr/bin/env python3
"""Decode/verify HYPE110 compact research packages."""
from __future__ import annotations
import argparse, hashlib, json, lzma
from pathlib import Path
import msgpack

def unpack(path:Path):
    with lzma.LZMAFile(path,"rb") as f:
        yield from msgpack.Unpacker(f,raw=False,strict_map_key=False)

def manifest(root:Path):
    return json.loads((root/"PACK_MANIFEST.json").read_text(encoding="utf-8"))

def chunk_meta(m,name):
    for c in m["chunks"]:
        if c["chunk"]==name:return c
    raise KeyError(name)

def stream_meta(c,name):
    for s in c["streams"]:
        if s["name"]==name:return s
    raise KeyError(name)

def decode_events(path:Path,meta):
    ps,qs=meta["price_scale"],meta["qty_scale"]
    pb={"recv":0,"ets":0,"u":0,"seq":0}; first_book=True; lp={"b":0,"a":0}
    pt={"recv":0,"ts":0,"seq":0}; first_trade=True
    pl={"recv":0,"ts":0}; first_liq=True
    for r in unpack(path):
        typ=r[0]
        if typ==0:
            snap,dr,de,du,ds,bids,asks=r[1:]
            if first_book: recv,ets,u,seq=dr,de,du,ds; first_book=False
            else: recv,ets,u,seq=pb["recv"]+dr,pb["ets"]+de,pb["u"]+du,pb["seq"]+ds
            pb.update(recv=recv,ets=ets,u=u,seq=seq)
            decoded=[]
            for side,rows in (("b",bids),("a",asks)):
                z=[]
                for dp,q in rows:
                    p=lp[side]+dp; lp[side]=p; z.append([p/ps,q/qs])
                decoded.append(z)
            yield {"kind":"orderbook","received_ts_ms":recv,"exchange_ts_ms":ets,
                   "type":"snapshot" if snap else "delta","update_id":u,"sequence":seq,
                   "bids":decoded[0],"asks":decoded[1]}
        elif typ==1:
            dr,dt,ds,side,p,q,tick,bt,rpi=r[1:]
            if first_trade: recv,ts,seq=dr,dt,ds; first_trade=False
            else: recv,ts,seq=pt["recv"]+dr,pt["ts"]+dt,pt["seq"]+ds
            pt.update(recv=recv,ts=ts,seq=seq)
            yield {"kind":"trade","received_ts_ms":recv,"exchange_ts_ms":ts,"sequence":seq,
                   "side":"Buy" if side else "Sell","price":p/ps,"qty":q/qs,
                   "tick_direction":tick,"block_trade":bool(bt),"rpi":bool(rpi)}
        elif typ==2:
            dr,dt,side,p,q=r[1:]
            if first_liq: recv,ts=dr,dt; first_liq=False
            else: recv,ts=pl["recv"]+dr,pl["ts"]+dt
            pl.update(recv=recv,ts=ts)
            yield {"kind":"liquidation","received_ts_ms":recv,"exchange_ts_ms":ts,
                   "side":"Buy" if side else "Sell","price":p/ps,"qty":q/qs}
        elif typ==3:
            yield {"kind":"ticker","received_ts_ms":r[1],"exchange_ts_ms":r[2],"data":r[3]}
        else:
            yield {"kind":"control","received_ts_ms":r[1],"receipt_sequence":r[2],
                   "endpoint":r[3],"data":r[4]}

def decode_table(path:Path):
    it=iter(unpack(path)); head=next(it,None)
    if not head or head[0]!="__keys__": return
    keys=head[1]
    for row in it:
        yield {k:v for k,v in zip(keys,row) if v is not None}

def verify(root:Path):
    m=manifest(root); errors=[]
    schema=json.loads((root/"SCHEMA_110.json").read_text(encoding="utf-8"))
    if len(schema.get("canonical_points",[]))!=110: errors.append("schema point count != 110")
    for c in m["chunks"]:
        cd=root/"chunks"/c["chunk"]
        for s in c["streams"]:
            p=cd/s["name"]
            if not p.exists(): errors.append("missing "+str(p)); continue
            h=hashlib.sha256()
            with p.open("rb") as f:
                for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
            if h.hexdigest()!=s["sha256"]: errors.append("checksum "+c["chunk"]+"/"+s["name"])
    return errors

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("package",type=Path)
    ap.add_argument("--verify",action="store_true"); ap.add_argument("--chunk")
    ap.add_argument("--stream",choices=["events","microstructure","market_context","structural_context"])
    ap.add_argument("--limit",type=int,default=0); args=ap.parse_args()
    if args.verify:
        e=verify(args.package); print(json.dumps({"ok":not e,"errors":e})); raise SystemExit(1 if e else 0)
    m=manifest(args.package); chunk=args.chunk or m["chunks"][0]["chunk"]; c=chunk_meta(m,chunk)
    names={"events":"events.mpk.xz","microstructure":"microstructure_1s.mpk.xz",
           "market_context":"market_context_1m.mpk.xz","structural_context":"structural_context_1m.mpk.xz"}
    name=names[args.stream or "events"]; meta=stream_meta(c,name); path=args.package/"chunks"/chunk/name
    rows=decode_events(path,meta) if name=="events.mpk.xz" else decode_table(path)
    for i,row in enumerate(rows):
        if args.limit and i>=args.limit: break
        print(json.dumps(row,separators=(",",":"),ensure_ascii=False))

if __name__=="__main__": main()
