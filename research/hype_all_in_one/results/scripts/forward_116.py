"""Rebuild the project's local116 candidate snapshots with the project's own code (run_symbol.py),
for 2026-10-04..2026-11-12, then enrich with mark/index/OI/funding via hype_history_backfill.enrich.
Oct04..Nov03 part = alignment check vs artifact local116-HYPE / HISTORICAL-GAPS; Nov04..Nov11 = forward scoring input."""
import sys,json,gzip
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,'/workspace/pandora-testnet')
import research.local_116_30d.run_symbol as rs
from research.hype_history_backfill.run import enrich
rs.END=datetime(2026,11,12,tzinfo=timezone.utc)
out=Path('/workspace/data/p116');cache=Path('/workspace/data/p116_cache');cache.mkdir(exist_ok=True)
sec5,mins,integ=rs.aggregate_symbol('HYPE',cache)
print('agg',len(sec5),len(mins),flush=True)
strict,_=rs.structural_labels(mins,lookback=6,lookahead=2)
internal,_=rs.structural_labels(mins,lookback=3,lookahead=1)
cands=rs.build_candidates(mins,strict,internal)
h1=rs.aggregate_h1(mins)
gaps=integ["suspicious_gaps_over_300s"]
if gaps:
    cands=[x for x in cands if not any(g["from_ms"]<x["extreme_ts_ms"]+300000 and g["to_ms"]>x["extreme_ts_ms"]-300000 for g in gaps)]
recs=rs.build_snapshots('HYPE',cands,sec5,mins,h1)
print('cands',len(cands),'snaps',len(recs),flush=True)
rs.write_jsonl_gz(out/'candidate_snapshots.jsonl.gz',recs)
rs.write_jsonl_gz(out/'compact_1m.jsonl.gz',mins)
rs.write_json_gz(out/'labels.json.gz',{'strict':strict,'internal':internal}) if hasattr(rs,'write_json_gz') else None
R='/workspace/data/rest/'
L=lambda n:json.load(gzip.open(R+n+'.json.gz'))
mark=[{'ts_ms':x['ts'],'close':x['c']} for x in L('mark')];index=[{'ts_ms':x['ts'],'close':x['c']} for x in L('index')]
oi=[{'ts_ms':x['ts'],'open_interest':x['oi']} for x in L('oi')];fund=[{'ts_ms':x['ts'],'funding_rate':x['rate']} for x in L('funding')]
for a in (mark,index,oi,fund): a.sort(key=lambda r:r['ts_ms'])
print(enrich(out/'candidate_snapshots.jsonl.gz',out/'candidate_snapshots_enriched.jsonl.gz',mark,index,oi,fund),flush=True)
print('DONE')
