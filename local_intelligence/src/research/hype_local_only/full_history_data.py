"""Offline delayed targets for every retained minute, not survivor snapshots."""
import gzip,json,math
from pathlib import Path
import numpy as np
from .candidate_memory import CausalExtremeTracker,HOUR,SIDE_COLUMNS
from research.hype_local_v5.labels import completed_hours

class DenseLocalData:
    def __init__(self,minutes,teachers):
        self.minutes=minutes;self.teachers=teachers
        self.meta={'LOW':[],'HIGH':[]};self.y={s:np.full(len(minutes),-1,dtype=np.int8) for s in self.meta}
        self.state={s:np.full((len(minutes),len(SIDE_COLUMNS)),np.nan,dtype=np.float32) for s in self.meta}
        self.active={s:np.zeros(len(minutes),dtype=bool) for s in self.meta}
        hours={r['start_ms']:r for r in completed_hours(minutes)}
        truth={(t['side'],int(t['hour_ms'])):t for t in teachers};tracker=CausalExtremeTracker()
        for i,row in enumerate(minutes):
            snap=tracker.step(row);ts=snap['as_of_ms'];h=row['start_ms']//HOUR*HOUR
            for side in self.meta:
                candidate=snap['candidates'][side];field='high' if side=='HIGH' else 'low';sign=-1 if side=='HIGH' else 1
                event=dict(candidate or {},side=side,candidate_id=(candidate or {}).get('candidate_id',f'background:{side}:{ts}'),
                    candidate_ts_ms=(candidate or {}).get('candidate_ts_ms',ts),snapshot_ts_ms=ts,prediction_ts_ms=ts,
                    event_key=f"{side}:{(candidate or {}).get('hour_ms',h)}",strict_true=False,
                    strict_label_id=None,label_mature_ms=ts,delay_s=0,extreme_price=(candidate or {}).get('extreme_price'))
                x=self.state[side][i];x[0]=int(candidate is not None);x[3]=(ts-h)/HOUR
                if not snap['history_complete']:
                    event['censor_reason']='MISSING_PAST_H1_CONTEXT';self.meta[side].append(event);continue
                if candidate is None:
                    self.y[side][i]=0;self.meta[side].append(event);continue
                self.active[side][i]=True;x[1]=candidate['age_s'];x[2]=sign*(row['close']/candidate['extreme_price']-1)*10000
                past=[hours.get(candidate['hour_ms']-j*HOUR) for j in range(1,7)]
                if all(past):
                    bound=max(r[field] for r in past) if side=='HIGH' else min(r[field] for r in past)
                    x[4]=sign*(candidate['extreme_price']/bound-1)*10000
                event['delay_s']=60 if candidate['age_s']<=60 else 180 if candidate['age_s']<=180 else 300
                ch=candidate['hour_ms'];window=[hours.get(ch+j*HOUR) for j in range(-6,3)]
                if not all(window):
                    event['censor_reason']='INCOMPLETE_TEACHER_WINDOW';self.meta[side].append(event);continue
                cur=window[6];past=window[:6];future=window[7:]
                high=cur['high']>max(r['high'] for r in past) and cur['high']>=max(r['high'] for r in future)
                low=cur['low']<min(r['low'] for r in past) and cur['low']<=min(r['low'] for r in future)
                if high and low:
                    event['censor_reason']='AMBIGUOUS_H1';self.meta[side].append(event);continue
                mature=max(ch+3*HOUR,max(r['available_at_ms'] for r in window))
                raw=(high if side=='HIGH' else low)
                exact=math.isclose(cur[field],candidate['extreme_price'],rel_tol=1e-12,abs_tol=1e-10)
                target=truth.get((side,ch))
                if raw and exact:
                    opposite=next((t for t in teachers if t['side']!=side and t['hour_ms']>ch),None)
                    if opposite is None:
                        event['censor_reason']='UNFINISHED_SWING';self.meta[side].append(event);continue
                    mature=max(mature,opposite['label_available_ms'])
                if target and exact:
                    if not target.get('reference_finalized'):
                        event['censor_reason']='UNFINISHED_STRICT_REFERENCE';self.meta[side].append(event);continue
                    mature=max(mature,target['reference_finalized_ms'])
                    event['strict_true']=True;event['strict_label_id']=target['label_id']
                event['label_mature_ms']=mature;self.y[side][i]=int(event['strict_true'])
                self.meta[side].append(event)
    @classmethod
    def load(cls,root,minutes):
        with gzip.open(Path(root)/'artifacts/history_30d_local116/labels.json.gz','rt') as f:teachers=json.load(f)['strict']
        return cls(minutes,teachers)
