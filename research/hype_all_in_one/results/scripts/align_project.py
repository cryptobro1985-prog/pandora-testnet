"""Minute-level alignment: project compact M1 vs Bybit-rebuilt tape."""
import gzip,json,glob,numpy as np
from core import *
from teacher_project import SRC,load
tp=Tape();res={}
for name,p in SRC.items():
    pb=load(p); a=int((pb[0]['start_ms']/1000-T0)//60); b=a+len(pb)
    mb=tp.m1_rows(a,b+5); md={int(x['start_ms']):x for x in mb}
    n=0;eq_h=eq_l=eq_c=0;dh=[];vol=[];gp=0;miss=0
    for x in pb:
        y=md.get(int(x['start_ms']))
        if y is None or x.get('gap'): miss+=1;continue
        n+=1
        eq_h+=abs(x['high']-y['high'])<1e-9;eq_l+=abs(x['low']-y['low'])<1e-9;eq_c+=abs(x['close']-y['close'])<1e-9
        dh.append(max(abs(x['high']/y['high']-1),abs(x['low']/y['low']-1))*1e4)
        if x.get('volume') and y.get('volume'): vol.append(y['volume']/x['volume'])
    res[name]={'project_minutes':len(pb),'compared':n,'missing_or_gap':miss,'high_exact':eq_h/n,'low_exact':eq_l/n,'close_exact':eq_c/n,
               'p99_hl_diff_bps':float(np.percentile(dh,99)),'max_hl_diff_bps':float(max(dh)),'median_volume_ratio':float(np.median(vol)) if vol else None}
    print(name,res[name],flush=True)
json.dump(res,open('/workspace/data/align_project_vs_bybit.json','w'),indent=1)
