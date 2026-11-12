"""v1 (public Bybit, v1 labels) vs v2a (project-aligned M1/labels, no liquidations) vs v2 (aligned + liquidation layer) vs teacher."""
import json
from pathlib import Path
D=Path('/workspace/data')
V={'v1_public_bybit':D/'v1','v2a_aligned_no_liq':D/'v2a','v2_aligned_plus_liq':D}
CFG=['B0.4_SAFE_MAX_OOF_CAL','B0.7_SAFE_MAX_OOF_CAL','B1.0_SAFE_MAX_OOF_CAL','B99.0_SAFE_MAX_OOF_CAL','B0.4_CAL_Q99','B0.7_CAL_Q995','TEACHER_V1_same_episodes']
KEYS=['true_terminal_locals','accepted','tp','false_first','precision','coverage','median_delay_s','median_dist_pct','p90_dist_pct','median_remaining_move_pct','median_captured_mfe_ratio']
out={'transfer_Jul_Oct':{},'forward_Nov4_11':{},'fold_false_first':{},'mfe_transfer':{},'mfe_forward':{}}
for v,p in V.items():
    M=json.load(open(p/'metrics_raw.json'));MF=json.load(open(p/'mfe_raw.json'))
    for sec,src in (('transfer_Jul_Oct',M['transfer_aggregate']),('forward_Nov4_11',M['forward'])):
        out[sec][v]={c:{s:{k:src[c][s].get(k) for k in KEYS} for s in ('LOW','HIGH','COMBINED')} for c in CFG if c in src}
    out['fold_false_first'][v]={c:{fn:{s:M['folds'][fn][c][s]['false_first'] for s in ('LOW','HIGH')} for fn in ('WF_Jul','WF_Aug','WF_Sep','WF_Oct')} for c in CFG[:4]}
    out['mfe_transfer'][v]=MF['transfer_aggregate']
    out['mfe_forward'][v]=MF.get('FINAL_FORWARD',MF.get('forward'))
json.dump(out,open(D/'version_comparison.json','w'),indent=1,default=float)
for c in CFG:
    print(c)
    for v in V:
        x=out['transfer_Jul_Oct'][v].get(c,{}).get('COMBINED')
        if x: print('  %-22s acc=%s tp=%s ff=%s prec=%.3f cov=%.3f dist=%s'%(v,x['accepted'],x['tp'],x['false_first'],x['precision'] or 0,x['coverage'] or 0,x['median_dist_pct']))
