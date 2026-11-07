import json
from pathlib import Path
import numpy as np
from research.hype_local_only.full_history_model import FullHistoryModel,Head
from research.hype_local_only.unified_local_analyzer import UnifiedLocalAnalyzer
from research.hype_local_only.event_memory import EventMemory

class ConstantEstimator:
    def predict_proba(self,x):return np.asarray([[.1,.9]]*len(x))

def test_fully_refit_score_is_not_claimed_calibrated_or_out_of_sample(tmp_path):
    model=FullHistoryModel('fixture',['candidate_present'],{'HIGH':Head(ConstantEstimator())},
        {'fit_available_until_ms':100,'threshold_selected_until_ms':120,'independently_calibrated':False,'role':'all_history'})
    assert model.predict('HIGH',{'candidate_present':1},110)['state']=='ABSTAIN'
    r=model.predict('HIGH',{'candidate_present':1,'strict_true':True,'87':1e9},130)
    assert np.isclose(r['score'],.9) and r['probability'] is None and not r['high_confidence_validated']
    path=tmp_path/'model.pkl';model.save(path)
    assert FullHistoryModel.load(path).predict('HIGH',{'candidate_present':1},130)==r

def test_authoritative_teacher_waits_persists_and_cannot_be_replaced_by_older_label(tmp_path):
    root=Path(__file__).resolve().parents[1]
    model=root/'artifacts/full_history_research/all_history/local_analyzer.pkl'
    analyzer=UnifiedLocalAnalyzer(root,model,runtime=tmp_path)
    teacher={'side':'LOW','hour_ms':10,'extreme_price':77.,'reference_finalized':True,'reference_finalized_ms':20}
    assert analyzer.accept_teacher(teacher,19)['state']=='WAITING_FOR_TEACHER'
    assert analyzer.accept_teacher(teacher,20)['expected_side']=='HIGH'
    again=UnifiedLocalAnalyzer(root,model,runtime=tmp_path)
    assert again.accept_teacher(teacher,21)['state']=='ALREADY_CONFIRMED'
    old=dict(teacher,side='HIGH',hour_ms=9,extreme_price=78.)
    assert again.accept_teacher(old,21)['expected_side']=='HIGH'

def test_actual_models_are_portable_and_full_history_contains_all_76_true_events():
    root=Path(__file__).resolve().parents[1]
    report=json.loads((root/'artifacts/full_history_research/FULL_HISTORY_RESULT.json').read_text())
    memory=EventMemory(root/'artifacts/full_history_research/event_memory')
    assert len({r['strict_label_id'] for r in memory.state['cases'] if r['local_true']})==76
    for role in ('evaluated','all_history'):
        q=FullHistoryModel.load(root/f'artifacts/full_history_research/{role}/local_analyzer.pkl')
        assert q.heads.keys()=={'LOW','HIGH'} and q.metadata['forward_validated'] is False
    assert report['full_history_fit']['all_matured_states']['LOW']>42000
    assert report['full_history_fit']['all_matured_states']['HIGH']>42000
