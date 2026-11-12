import json
from teacher import *
tp=Tape();bars=tp.m1_rows(0,tp.nm);labels,_=structural_labels(bars,6,2)
rows=replay_period(bars,labels)
json.dump(rows,open(DATA/"teacher_continuous.json","w"))
a=(datetime(2026,5,1,tzinfo=timezone.utc).timestamp())*1000
r2=[r for r in rows if r["target_ts_ms"]>=a]
print(summarize(r2))
