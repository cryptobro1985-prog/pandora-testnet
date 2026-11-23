#!/usr/bin/env python3
"""Research-only frozen D250 identity and raw-byte gate. NOT a trade replay."""
import argparse,csv,hashlib,json,pathlib

def digest(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for chunk in iter(lambda:f.read(1048576),b""):h.update(chunk)
    return h.hexdigest()

def verify(cohort,manifest,root):
    root=pathlib.Path(root).resolve()
    with open(cohort,newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    with open(manifest,encoding="utf-8") as f: m=json.load(f)
    ids=[r.get("signal_id","").strip() for r in rows]
    problems=[]
    if len(ids)!=71: problems.append("NOT_71_SIGNALS")
    if not all(ids) or len(set(ids))!=len(ids): problems.append("DUPLICATE_OR_EMPTY_ID")
    frozen=m.get("signal_ids")
    if not isinstance(frozen,list) or len(frozen)!=71 or len(set(frozen))!=71:
        problems.append("FROZEN_ID_LIST_MISSING_OR_INVALID")
    elif sorted(ids)!=sorted(frozen): problems.append("COHORT_MEMBERSHIP_MISMATCH")
    sources=m.get("source_files")
    if not isinstance(sources,list) or not sources:
        problems.append("NO_RAW_SOURCE_FILES");sources=[]
    for i,src in enumerate(sources):
        if not isinstance(src,dict): problems.append(f"BAD_SOURCE_RECORD_{i}");continue
        name=src.get("path"); expected=src.get("sha256")
        if not isinstance(name,str) or not name or not isinstance(expected,str) or len(expected)!=64:
            problems.append(f"BAD_SOURCE_METADATA_{i}");continue
        p=(root/name).resolve()
        if not p.is_relative_to(root): problems.append(f"PATH_ESCAPE_{i}");continue
        if not p.is_file(): problems.append(f"MISSING_SOURCE_{i}");continue
        if digest(p)!=expected.lower(): problems.append(f"HASH_MISMATCH_{i}")
    return {"gate":"BLOCKED" if problems else "IDENTITY_AND_BYTES_ONLY",
            "rows":len(rows),"source_files_checked":len(sources),"issues":problems,
            "warning":"No quote continuity, fills, stop gaps, liquidation, MTM or net PnL validated"}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        r=pathlib.Path(td);t=r/"tape.bin";t.write_bytes(b"raw tape")
        ids=[f"s{i:03}" for i in range(71)]
        c=r/"signals.csv"
        with c.open("w",newline="") as f:
            w=csv.writer(f);w.writerow(["signal_id"]);w.writerows([[x] for x in ids])
        m={"signal_ids":ids[:],"source_files":[{"path":"tape.bin","sha256":digest(t)}]}
        p=r/"manifest.json";p.write_text(json.dumps(m))
        assert verify(c,p,r)["gate"]=="IDENTITY_AND_BYTES_ONLY"
        t.write_bytes(b"altered")
        assert "HASH_MISMATCH_0" in verify(c,p,r)["issues"]
        t.write_bytes(b"raw tape")
        m["signal_ids"][0]="substituted";p.write_text(json.dumps(m))
        assert "COHORT_MEMBERSHIP_MISMATCH" in verify(c,p,r)["issues"]
        m["signal_ids"][0]=ids[0];m["source_files"][0]["path"]="../escape";p.write_text(json.dumps(m))
        assert "PATH_ESCAPE_0" in verify(c,p,r)["issues"]
    print("PASS 4 synthetic integrity checks; no Bybit replay")

if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("cohort",nargs="?");a.add_argument("manifest",nargs="?");a.add_argument("--root",default=".");a.add_argument("--self-test",action="store_true");v=a.parse_args()
    if v.self_test:selftest()
    elif v.cohort and v.manifest:print(json.dumps(verify(v.cohort,v.manifest,v.root),indent=2))
    else:a.error("cohort and manifest required")
