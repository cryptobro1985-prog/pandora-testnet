from __future__ import annotations
import argparse,gzip,json,math
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from sklearn.metrics import roc_auc_score

def finite(v):
    return isinstance(v,(int,float,np.number)) and math.isfinite(float(v))

def load(path):
    out=[]
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f:
            if line.strip(): out.append(json.loads(line))
    return out

def group_name(k):
    q=k.lower()
    if q.startswith('fullmicro_bid_') or q.startswith('fullmicro_ask_') or 'book_imbalance' in q or 'spread_bps' in q or 'book_valid' in q or 'book_gap' in q:
        return 'L50_BOOK'
    if q.startswith('fullmicro_liq') or 'liq_notional' in q: return 'LIQUIDATIONS'
    if q.startswith('fullmicro_open_interest'): return 'OPEN_INTEREST'
    if q.startswith('fullmicro_mark_price'): return 'MARK_INDEX_FUNDING'
    if q.startswith('fullmicro_ticker'): return 'TICKER_24H'
    if 'account_' in q: return 'LONG_SHORT_RATIO'
    if q.startswith(('imbalance_','rev_flow_','buy_','sell_','total_','trade_count_','max_trade_','rev_eff_','ret_','rev_ret_')):
        return 'FLOW_PRICE_RESPONSE'
    if q.startswith(('distance_','position_','retrace','age_s','directional_','reversal_attempt')): return 'STRUCTURE'
    return 'OTHER'

def side_stats(rows,side):
    rr=[r for r in rows if r['side']==side and int(r['delay_s'])==0]
    pos=[r for r in rr if r['strict_true']]
    neg=[r for r in rr if not r['strict_true']]
    features=sorted({k for r in rr for k,v in (r.get('features') or {}).items() if finite(v)})
    stats=[]
    for k in features:
        pv=[float(r['features'][k]) for r in pos if finite(r['features'].get(k))]
        nv=[float(r['features'][k]) for r in neg if finite(r['features'].get(k))]
        coverage=(len(pv)+len(nv))/max(1,len(rr))
        if coverage<.5 or len(pv)<5 or len(nv)<20: continue
        medp=float(np.median(pv)); medn=float(np.median(nv))
        y=np.asarray([1]*len(pv)+[0]*len(nv)); x=np.asarray(pv+nv)
        auc=float(roc_auc_score(y,x)) if len(set(x.tolist()))>1 else .5
        stats.append({
            'feature':k,'group':group_name(k),'coverage':coverage,
            'true_median':medp,'false_candidate_median':medn,
            'auc':auc,'directional_auc':max(auc,1-auc),
            'true_support':len(pv),'false_support':len(nv)
        })
    stats.sort(key=lambda z:z['directional_auc'],reverse=True)
    groups={}
    by=defaultdict(list)
    for z in stats: by[z['group']].append(z)
    for g,arr in by.items():
        groups[g]={
            'feature_count':len(arr),
            'best_directional_auc':max(z['directional_auc'] for z in arr),
            'top5_mean_directional_auc':float(np.mean(sorted([z['directional_auc'] for z in arr],reverse=True)[:5])),
            'top_features':arr[:10],
        }
    return {'true_count':len(pos),'hard_negative_count':len(neg),'top_features':stats[:40],'groups':groups,'all_feature_stats':stats}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--snapshots',type=Path,required=True)
    ap.add_argument('--labels',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
    rows=load(a.snapshots)
    with gzip.open(a.labels,'rt',encoding='utf-8') as f: labels=json.load(f)['strict']
    exact=[r for r in rows if int(r['delay_s'])==0]
    events=[]
    for r in sorted([r for r in exact if r['strict_true']],key=lambda x:x['candidate_ts_ms']):
        events.append({
            'label_id':r['strict_label_id'],'side':r['side'],'price':r['extreme_price'],
            'extreme_ts_utc':datetime.fromtimestamp(r['candidate_ts_ms']/1000,tz=timezone.utc).isoformat(),
            'features':r['features'],
        })
    present={e['label_id'] for e in events}
    missed=[x for x in labels if x['label_id'] not in present]
    report={
        'objective':'Study every historical strict Local LOW/HIGH at the exact extreme timestamp; teacher labels are never predictive inputs.',
        'method':'delay_s=0 exact snapshots only. True locals are compared with same-side hard-negative structural extrema only for contrast; post-extreme 60/180/300s data is excluded from the signature.',
        'strict_labels_total':len(labels),
        'exact_true_locals_in_period':len(events),
        'missed_or_outside_snapshot_period':missed,
        'LOW':side_stats(rows,'LOW'),
        'HIGH':side_stats(rows,'HIGH'),
        'events':events,
    }
    (a.out/'TRUE_LOCAL_SIGNATURES_LATEST.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
    lines=['# HYPE True Local Signatures — exact extreme timestamp','',
           'This analysis is the corrected objective: all historical strict Local LOW/HIGH are examined at the exact extreme timestamp. No +60/+180/+300 second post-extreme information is used as an input signature.','',
           f"Strict labels: {len(labels)}; exact locals inside snapshot period: {len(events)}. One warm-up label can fall outside the July-12 17:00 UTC snapshot period.",'']
    for side in ('LOW','HIGH'):
        s=report[side]
        lines += [f'## {side}',f"True locals: {s['true_count']}; hard-negative same-side extrema: {s['hard_negative_count']}.",'','Top exact-moment discriminators:','']
        for z in s['top_features'][:15]:
            lines.append(f"- {z['feature']}: true median={z['true_median']:.8g}; false median={z['false_candidate_median']:.8g}; directional AUC={z['directional_auc']:.3f}; group={z['group']}")
        lines += ['','Group strength:','']
        for g,z in sorted(s['groups'].items(),key=lambda kv:kv[1]['best_directional_auc'],reverse=True):
            lines.append(f"- {g}: best AUC={z['best_directional_auc']:.3f}; top-5 mean AUC={z['top5_mean_directional_auc']:.3f}")
        lines.append('')
    (a.out/'TRUE_LOCAL_SIGNATURES_LATEST.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:report[k] for k in ('strict_labels_total','exact_true_locals_in_period')},separators=(',',':')))

if __name__=='__main__': main()
