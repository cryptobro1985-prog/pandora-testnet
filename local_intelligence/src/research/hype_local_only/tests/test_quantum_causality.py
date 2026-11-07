import copy
import gzip
import json
from pathlib import Path

import pytest

from research.hype_local_only.temporal import causal_completed_minute_features,candidate_temporal_features
from research.hype_local_only.evaluation import purged_partition,event_metrics,paired_day_bootstrap
from research.hype_local_only.model import LocalOnlyModel,clean


def bar(start,close=100,**extra):
    return dict(start_ms=start,bar_end_ms=start+60_000,ts_ms=start+60_000,
                open=100.,high=max(101.,close),low=min(99.,close),close=float(close),**extra)


def test_future_bar_and_delayed_receipt_cannot_change_current_features():
    known=[bar(i*60_000,100+i*.1) for i in range(5)]
    expected=causal_completed_minute_features('LOW',60,99,known,300_000)
    future=bar(300_000,10000)
    delayed=bar(240_000,20000,received_ts_ms=400_000)
    assert causal_completed_minute_features('LOW',60,99,known+[future,delayed],300_000)==expected
    # A source timestamp by itself is an availability constraint.
    only=bar(0);only['ts_ms']=120_000
    assert 'm1__retrace_bps' not in causal_completed_minute_features('LOW',60,99,[only],60_000)
    assert 'm1__retrace_bps' in causal_completed_minute_features('LOW',60,99,[only],120_000)


def test_missing_minute_breaks_window_and_stale_data_abstains():
    rows=[bar(0),bar(120_000),bar(180_000)]
    result=causal_completed_minute_features('LOW',60,99,rows,240_000)
    assert 'm1__rev_ret_3m_bps' not in result
    assert 'm1__retrace_bps' not in causal_completed_minute_features('LOW',60,99,rows,340_000)


def test_temporal_state_uses_only_previous_candidate_stages():
    current={'m1__age_s':180.,'m1__retrace_bps':3.}
    history={60:{'m1__retrace_bps':1.},180:{'m1__retrace_bps':100.},300:{'m1__retrace_bps':999.}}
    before=copy.deepcopy(history)
    assert candidate_temporal_features(current,history)['seq__delta_retrace_bps']==2.
    assert before==history


def test_purged_split_removes_unmatured_labels_and_overlapping_candidate():
    hour=3_600_000
    def row(cid,t,mature):
        return dict(candidate_id=cid,candidate_ts_ms=t,snapshot_ts_ms=t,label_mature_ms=mature)
    rows=[row('old',hour,2*hour),row('future-label',hour,20*hour),
          row('cal',12*hour,13*hour),row('eval',24*hour,30*hour)]
    train,cal,evaluation=purged_partition(rows,10*hour,20*hour,24*hour,36*hour)
    assert [r['candidate_id'] for r in train]==['old']
    assert [r['candidate_id'] for r in cal]==['cal']
    assert [r['candidate_id'] for r in evaluation]==['eval']
    assert purged_partition(rows,10*hour,20*hour,24*hour,30*hour)[2]==[]


def test_event_recall_denominator_includes_teacher_without_proposal():
    teachers=[dict(label_id=i,reference_finalized=True,extreme_interval_start_ms=i*1000,
                   extreme_interval_end_ms=i*1000+60_000,side='LOW') for i in (1,2)]
    rows=[dict(candidate_id='a',event_key='LOW:0',side='LOW',candidate_ts_ms=1000,
               snapshot_ts_ms=61_000,strict_true=True,strict_label_id=1),
          dict(candidate_id='a',event_key='LOW:0',side='LOW',candidate_ts_ms=1000,
               snapshot_ts_ms=181_000,strict_true=True,strict_label_id=1)]
    result=event_metrics(rows,[.9,.95],.5,teachers,0,3_600_000)
    assert result['accepted']==1 and result['true_events']==1
    assert result['teacher_events']==2 and result['recall']==.5


def test_future_targets_and_metadata_do_not_enter_clean_inputs():
    result=clean({'m1__side':1,'strict_true':1,'future_return':2,'eval_precision':3,
                  '87':4,'live__strict_label_id':5,'x':float('nan')})
    assert result=={'m1__side':1.}


class BrokenPredictor:
    def probability(self,x):raise RuntimeError('broken inference')


def test_model_failure_and_missing_history_cannot_be_accepted():
    model=LocalOnlyModel();model.frozen_predictor=BrokenPredictor()
    p,accepted=model.predict('LOW',60,{'m1__retrace_bps':2.,'m1__bar_age_s':0.})
    assert p==.5 and not accepted and model.inference_errors==1
    assert model.predict('LOW',60,{})==(.5,False)


def test_cold_start_and_invalid_threshold_abstain():
    model=LocalOnlyModel();features={'m1__retrace_bps':2.,'m1__bar_age_s':0.}
    assert model.predict('LOW',60,features)==(.5,False)
    model.learn('LOW',60,features,True)
    model.thresholds[('LOW',60)]=float('nan')
    assert not model.predict('LOW',60,features)[1]


class NaNPredictor:
    def probability(self,x):return float('nan')


def test_invalid_model_probability_cannot_signal():
    model=LocalOnlyModel();model.frozen_predictor=NaNPredictor()
    assert model.predict('LOW',60,{'m1__retrace_bps':2.,'m1__bar_age_s':0.})==(.5,False)


def test_live_labels_deduplicate_and_never_repeat_positive_weight():
    model=LocalOnlyModel();features={'m1__side':1.,'m1__retrace_bps':2.}
    assert model.learn('LOW',60,features,True,source='live',repeat=8,event_id='a')
    assert not model.learn('LOW',60,features,True,source='live',event_id='a')
    assert model.labels[('LOW',60)]==1 and model.live_labels==1
    challenger=model.make_online_challenger()
    assert challenger.model_version_id!=model.model_version_id
    assert challenger.models[('LOW',60)] is not model.models[('LOW',60)]


def test_checkpoint_corruption_is_detected(tmp_path):
    model=LocalOnlyModel();path=tmp_path/'model.pkl';model.save(path)
    assert LocalOnlyModel.load(path).model_version_id==model.model_version_id
    with path.open('ab') as handle:handle.write(b'bad')
    with pytest.raises(ValueError,match='SHA256'):LocalOnlyModel.load(path)


def test_actual_archive_repair_has_no_future_source_and_terminal_teacher_is_censored():
    root=Path(__file__).resolve().parents[4]
    path=root/'artifacts/quantum_research/causal_candidates.jsonl.gz'
    if not path.exists():pytest.skip('run historical benchmark to create causal artifact')
    with gzip.open(path,'rt') as handle:rows=[json.loads(line) for line in handle]
    assert rows and all(r['feature_source_max_end_ms']<=r['snapshot_ts_ms'] for r in rows)
    assert all(r['label_mature_ms']>=r['candidate_ts_ms'] for r in rows)
    assert all(k.startswith(('m1__','seq__')) for r in rows for k in r['features'])
    assert len({r['strict_label_id'] for r in rows if r['strict_true']})==76
