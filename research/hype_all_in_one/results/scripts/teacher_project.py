"""Teacher V1 replay on the PROJECT's own compact M1 artifacts (alignment proof v2)."""
import gzip,json,glob,sys
from core import *
from teacher import replay_period,summarize
A='/workspace/proj_art'
M=glob.glob(A+'/HYPE-HISTORY-20260712-20261103-MASTER-*')[0]
SRC={"May":glob.glob(A+'/HYPE-MAY-SEALED-TAPE-*/compact_1m.jsonl.gz')[0],
     "Jul":M+'/01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz',"Aug":M+'/02_AUG08_SEP01/compact_1m.jsonl.gz',
     "Sep":M+'/03_SEP01_OCT01/compact_1m.jsonl.gz',"Oct":M+'/04_OCT04_NOV03/compact_1m.jsonl.gz'}
def load(p): return [json.loads(l) for l in gzip.open(p,'rt')]
if __name__=="__main__":
    out={};allrows=[];proj_labels={}
    for name,p in SRC.items():
        bars=load(p)
        labels,_=structural_labels(bars,6,2)
        lp=p.replace('compact_1m.jsonl.gz','labels.json.gz')
        try:
            pl=json.load(gzip.open(lp,'rt')); pli=pl.get('internal',pl) if isinstance(pl,dict) else pl
            mine={(x['side'],x['extreme_interval_start_ms']) for x in labels if x.get('reference_finalized')}
            theirs={(x['side'],x['extreme_interval_start_ms']) for x in pli if x.get('reference_finalized')}
            proj_labels[name]={'mine':len(mine),'artifact':len(theirs),'common':len(mine&theirs)}
        except Exception as e: proj_labels[name]={'err':str(e)}
        rows=replay_period(bars,labels)
        for r in rows:r["period"]=name
        allrows+=rows
        out[name]={s:summarize([r for r in rows if r["side"]==s]) for s in ("LOW","HIGH")}
        out[name]['bars']=len(bars); out[name]['first']=bars[0]['start_ms']; out[name]['last']=bars[-1]['bar_end_ms']
        print(name,len(bars),{s:(out[name][s]['episodes'],out[name][s]['accepted'],out[name][s]['true_first']) for s in ('LOW','HIGH')},proj_labels[name],flush=True)
    out["ALL"]={s:summarize([r for r in allrows if r["side"]==s]) for s in ("LOW","HIGH")}
    out["ALL"]["COMBINED"]=summarize(allrows)
    print(json.dumps(out["ALL"],indent=1))
    json.dump({"summary":out,"label_compare":proj_labels,"rows":allrows},open("/workspace/data/teacher_project_repro.json","w"))
