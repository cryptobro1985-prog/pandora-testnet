import gzip,json,glob,numpy as np
A=glob.glob('/workspace/proj_art/HYPE-LOCAL-HISTORICAL-GAPS-*/candidate_snapshots_enriched.jsonl.gz')[0]
art=[json.loads(l) for l in gzip.open(A,'rt')]
mine=[json.loads(l) for l in gzip.open('/workspace/data/p116/candidate_snapshots_enriched.jsonl.gz','rt')]
end=max(r['snapshot_ts_ms'] for r in art)
key=lambda r:(r['candidate_id'],r['delay_s'])
am={key(r):r for r in art}; mm={key(r):r for r in mine if r['candidate_ts_ms']<=max(x['candidate_ts_ms'] for x in art)}
common=set(am)&set(mm)
diffs=[];labdiff=0
for k in common:
    a=am[k]['features'];b=mm[k]['features']
    for f in a:
        if f in b and np.isfinite(a[f]) and np.isfinite(b[f]): diffs.append(abs(a[f]-b[f])/(abs(a[f])+1e-9))
    if am[k].get('strict_true')!=mm[k].get('strict_true'): labdiff+=1
res={'artifact_rows':len(art),'rebuilt_rows_same_period':len(mm),'common_keys':len(common),'only_artifact':len(set(am)-set(mm)),'only_rebuilt':len(set(mm)-set(am)),
     'feature_rel_diff_p50':float(np.median(diffs)),'feature_rel_diff_p99':float(np.percentile(diffs,99)),'frac_features_exact_1e-6':float(np.mean(np.array(diffs)<1e-6)),'strict_true_mismatch':labdiff,
     'forward_rows_after_artifact_end':sum(1 for r in mine if r['candidate_ts_ms']>max(x['candidate_ts_ms'] for x in art))}
print(res); json.dump(res,open('/workspace/data/p116_alignment.json','w'),indent=1)
print(list(art[0].keys()))
