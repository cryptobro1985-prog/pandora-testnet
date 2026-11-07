"""Streaming six-completed-hour extreme proposals. No teacher/future imports."""
from collections import deque
import math
MINUTE=60_000
HOUR=60*MINUTE
SIDE_COLUMNS=('candidate_present','candidate_age_s','retrace_bps','hour_progress','distance_past_extreme_bps')

class CausalExtremeTracker:
    def __init__(self):
        self.hours=deque(maxlen=6);self.hour=None;self.current=None;self.last_start=None
        self.candidates={'LOW':None,'HIGH':None}
    def step(self,row):
        start=int(row['start_ms']);end=start+MINUTE;hour=start//HOUR*HOUR
        if self.last_start is not None and start!=self.last_start+MINUTE:
            self.hours.clear();self.candidates={'LOW':None,'HIGH':None}
            if self.current:self.current['complete']=False
        if hour!=self.hour:
            if self.current and self.current['complete'] and self.current['count']==60:
                self.hours.append(self.current.copy())
            elif self.current:self.hours.clear()
            self.hour=hour;self.current={'start_ms':hour,'high':-math.inf,'low':math.inf,
                'count':0,'complete':start==hour}
        previous_high,previous_low=self.current['high'],self.current['low']
        self.current['high']=max(previous_high,float(row['high']))
        self.current['low']=min(previous_low,float(row['low']));self.current['count']+=1
        self.last_start=start
        complete=(len(self.hours)==6 and self.hours[0]['start_ms']==hour-6*HOUR and
                  self.hours[-1]['start_ms']==hour-HOUR and self.current['complete'])
        if complete:
            bounds={'HIGH':max(r['high'] for r in self.hours),'LOW':min(r['low'] for r in self.hours)}
            for side,field,previous in (('HIGH','high',previous_high),('LOW','low',previous_low)):
                price=float(row[field]);new=price>previous if side=='HIGH' else price<previous
                breaks=price>bounds[side] if side=='HIGH' else price<bounds[side]
                if new and breaks:
                    ts=int(row[field+'_ts_ms']) if field+'_ts_ms' in row else start
                    # A missing exact timestamp is interval-censored, not invented.
                    if not start<=ts<end:raise ValueError('extreme timestamp outside bar')
                    old=self.candidates[side]
                    if old is None or end-old['candidate_ts_ms']>HOUR or (price>old['extreme_price'] if side=='HIGH' else price<old['extreme_price']):
                        self.candidates[side]={'side':side,'candidate_id':f'{side}:{ts}:{price}',
                            'extreme_price':price,'candidate_ts_ms':ts,'hour_ms':hour,
                            'extreme_time_exact':field+'_ts_ms' in row,
                            'extreme_interval_start_ms':start,'extreme_interval_end_ms':end}
        active={}
        for side,c in self.candidates.items():
            if c is not None and 0<=end-c['candidate_ts_ms']<=300000:
                active[side]=dict(c,age_s=(end-c['candidate_ts_ms'])/1000)
            else:active[side]=None
        return {'as_of_ms':end,'history_complete':complete,'candidates':active}
