import numpy as np
from research.hype_local_only.candidate_memory import CausalExtremeTracker,HOUR,MINUTE
from research.hype_local_only.full_history_data import DenseLocalData
from research.hype_local_v5.labels import structural_labels

def minutes(hours=24):
    result=[]
    for hour in range(hours):
        for m in range(60):
            start=hour*HOUR+m*MINUTE;high=100.;low=90.
            if hour==6:low=91.;high=120. if m==30 else 100.
            if hour==12:high=99.;low=70. if m==30 else 90.
            if hour==18:low=91.;high=130. if m==30 else 100.
            result.append(dict(start_ms=start,ts_ms=start+MINUTE,bar_end_ms=start+MINUTE,
                open=95.,close=95.,high=high,low=low,high_ts_ms=start+MINUTE-1000,
                low_ts_ms=start+MINUTE-1000))
    return result

def test_stream_does_not_peek_and_retains_only_received_extremes():
    source=minutes();tracker=CausalExtremeTracker();snap=None
    for r in source[:6*60+31]:snap=tracker.step(r)
    candidate=snap['candidates']['HIGH'];assert candidate['extreme_price']==120
    assert candidate['candidate_ts_ms']<=snap['as_of_ms']
    for r in source[6*60+31:7*60]:snap=tracker.step(r)
    assert snap['candidates']['HIGH'] is None

def test_lower_high_is_proposed_after_old_peak_leaves_past_six_hours():
    source=minutes();source[13*60+30]['high']=110.
    tracker=CausalExtremeTracker()
    for r in source[:13*60+31]:snap=tracker.step(r)
    assert snap['candidates']['HIGH']['extreme_price']==110.
    assert snap['candidates']['HIGH']['hour_ms']==13*HOUR

def test_dense_teachers_mature_after_opposite_and_terminal_is_censored():
    source=minutes();teachers,_=structural_labels(source);data=DenseLocalData(source,teachers)
    positives=[r for i,r in enumerate(data.meta['HIGH']) if data.y['HIGH'][i]==1]
    assert positives and all(r['label_mature_ms']>=15*HOUR for r in positives)
    assert all(r['snapshot_ts_ms']>=r['candidate_ts_ms'] for r in positives)
    assert np.sum(data.y['HIGH'][:6*60]>=0)==0
    tail=[r for r in data.meta['HIGH'] if r.get('hour_ms')==18*HOUR and 'censor_reason' in r]
    assert any(r['censor_reason'].startswith('UNFINISHED') for r in tail)
