import copy,json
from dataclasses import replace,asdict
from pathlib import Path
import numpy as np
import pytest
torch=pytest.importorskip('torch')
from research.hype_local_only.jepa import (Config,MarketSequence,NumericJEPA,FEATURES,MINUTE,
    objective,representation_stats,diagnostics)
from research.hype_local_only.reliability import CheckpointStore
from research.hype_local_only.jepa_probe import compare
from research.hype_local_only.jepa_research import ShadowPolicy,ErrorMemory

def rows(n=150):
    return [dict(start_ms=i*MINUTE,ts_ms=(i+1)*MINUTE,open=100+i*.01,
        high=101+i*.01,low=99+i*.01,close=100.2+i*.01,
        flow_observed=True,flow_imbalance=0.,trade_count=5,turnover=500.) for i in range(n)]
def cfg():return replace(Config(),context=8,hidden=8,latent=4,horizons=(1,3),batch=8)

def test_target_aliases_do_not_enter_numeric_vision():
    source=rows();altered=copy.deepcopy(source)
    for r in altered:r.update(strict_true=True,future_high=1e20,target=999,**{'87':999})
    a,b=MarketSequence(source),MarketSequence(altered)
    assert np.array_equal(a.values,b.values) and np.array_equal(a.observed,b.observed)
    assert len(FEATURES)==16

def test_normalization_is_train_only_and_true_zero_differs_missing():
    source=rows();other=copy.deepcopy(source)
    for r in other[100:]:
        for k in ('open','high','low','close'):r[k]*=10
    a=MarketSequence(source).normalize(80*MINUTE);b=MarketSequence(other).normalize(80*MINUTE)
    np.testing.assert_array_equal(a.mean,b.mean);np.testing.assert_array_equal(a.x[:80],b.x[:80])
    assert a.observed[20,8] and a.values[20,8]==0
    source[20]['flow_observed']=False
    assert not MarketSequence(source).observed[20,8]

def test_incomplete_delayed_received_and_gap_windows_are_rejected():
    source=rows();data=MarketSequence(source)
    assert data.at(20*MINUTE-1,8)==18
    source[15]['received_ts_ms']=30*MINUTE
    assert MarketSequence(source).at(20*MINUTE,8) is None
    source=rows();source.pop(15)
    assert MarketSequence(source).at(20*MINUTE,8) is None

def test_future_target_never_enters_context_and_target_has_no_gradient():
    torch.set_num_threads(2);model=NumericJEPA(cfg());data=MarketSequence(rows()).normalize(80*MINUTE)
    idx=np.asarray([40,50]);x=data.batch(idx,8);future=[data.batch(idx+h,8) for h in cfg().horizons]
    encoded=model.context(x).detach().clone()
    objective(model,x,future,masked=False).backward()
    assert all(p.grad is None for p in model.target.parameters())
    assert any(p.grad is not None for p in model.context.parameters())
    changed=rows();changed[55]['close']+=.1
    later=MarketSequence(changed).normalize(80*MINUTE,data.mean,data.scale)
    assert torch.equal(encoded,model.context(later.batch(idx,8)).detach())

def test_ema_target_and_complete_checkpoint_resume(tmp_path):
    torch.manual_seed(1);model=NumericJEPA(cfg());optim=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad])
    x=torch.randn(8,8,32);y=[torch.randn_like(x) for _ in cfg().horizons]
    objective(model,x,y,False).backward();optim.step();before=[p.clone() for p in model.target.parameters()]
    model.update_target()
    for old,target,context in zip(before,model.target.parameters(),model.context.parameters()):
        assert torch.allclose(target,old*cfg().ema+context*(1-cfg().ema),atol=1e-6)
    store=CheckpointStore(tmp_path);store.save({'schema':1,'model':model.state_dict(),'optimizer':optim.state_dict(),'config':asdict(cfg()),'epoch':1})
    restored=NumericJEPA(cfg());state=store.load();restored.load_state_dict(state['model'])
    opt=torch.optim.AdamW([p for p in restored.parameters() if p.requires_grad]);opt.load_state_dict(state['optimizer'])
    assert torch.equal(model(x)[0],restored(x)[0]) and opt.state

def test_collapse_and_unmatured_forecast_error_are_explicit():
    assert representation_stats(np.zeros((10,4)))['mean_dimension_std']==0
    d=diagnostics([1,2],previous=[0,1],predictions=[[1,2],[2,3]])
    assert d['prediction_error'] is None and d['horizon_disagreement']>0

def test_failed_ssl_screen_forbids_probe_fit(tmp_path):
    (tmp_path/'JEPA_SCREEN.json').write_text(json.dumps({'screen':{'passed':False}}))
    with pytest.raises(ValueError,match='SSL screen failed'):compare(tmp_path,tmp_path)

def test_shadow_policy_distinguishes_forming_model_and_teacher():
    p=ShadowPolicy();assert p.observe(1,100,'LOW','LOCAL_FORMING',True)['decision']=='WATCH'
    assert p.observe(2,100,'LOW','LOCAL_CONFIRMED_BY_MODEL',True)['decision']=='PAPER_LONG'
    assert p.observe(3,102,'HIGH','LOCAL_FORMING',True)['decision']=='HOLD'
    assert p.observe(4,103,'HIGH','LOCAL_CONFIRMED_BY_MODEL',False)['decision']=='HOLD'
    assert p.observe(5,101,'HIGH','TEACHER_CONFIRMED',True)['decision']=='PAPER_SHORT'
    assert p.closed[0]['mfe_bps']>0 and p.closed[0]['costs_modelled'] is False

def test_error_memory_waits_for_teacher_and_deduplicates(tmp_path):
    memory=ErrorMemory(tmp_path/'errors.jsonl')
    args=dict(event_id='x',as_of_ms=10,available_ms=11,truth='CONTINUATION',predicted='HIGH',extreme_ts_ms=1,first_suspected_ms=2,signal_ms=3)
    with pytest.raises(ValueError,match='not available'):memory.mature(**args)
    args['as_of_ms']=12;assert memory.mature(**args);assert not memory.mature(**args)
    assert json.loads((tmp_path/'errors.jsonl').read_text())['false_positive']

def test_incident_785515_higher_high_invalidates_signal_without_flipping_teacher(tmp_path):
    from research.hype_local_only.live_daemon import LocalRuntime
    from research.hype_local_only.model import LocalOnlyModel,Candidate
    from research.hype_quant.features import FeatureState
    root=Path(__file__).resolve().parents[1]
    source=json.loads((root/'artifacts/jepa_research/INCIDENT_SOURCE.json').read_text())
    cid=source['candidate_id'];first=source['chronology'][0];higher=source['first_higher_high'];ts=higher['ts_ms']
    state=FeatureState();runtime=LocalRuntime(tmp_path,LocalOnlyModel(),state)
    runtime.rt['expected_side']='HIGH'  # Last authoritative teacher was LOW.
    old=Candidate('HIGH',78.5515,first['ts_ms'],cid,evidence={'price_reference':'PUBLIC_TRADE','windows':['5m']})
    runtime.rt['candidates']['HIGH']=old
    runtime.champion.last_signal={'candidate_id':cid,'side':'HIGH','price':78.5515,'probability':.9971110316004237}
    # Explicit control-flow fixture uses archived prices; no synthetic inference claim.
    state.update_event({'kind':'trade','received_ts_ms':ts,'exchange_ts_ms':ts-1,
        'price':higher['price'],'qty':1,'side':'Buy'})
    runtime._propose(ts,higher['price'],{'running_high_300s':78.5515})
    assert old.invalidated and runtime.champion.last_signal['invalidated']
    assert runtime.rt['candidates']['HIGH'].extreme_price==78.5575
    assert runtime.rt['expected_side']=='HIGH'
    events=[json.loads(line) for line in (tmp_path/'LOCAL_EVENTS.jsonl').read_text().splitlines()]
    assert any(e['event']=='CANDIDATE_SUPERSEDED' and e['candidate_id']==cid for e in events)

def test_cortex_sees_only_causal_latent_diagnostics():
    from research.hype_local_only.jepa_research import causal_cortex_evidence
    raw={'prediction_ts_ms':10,'target_available_ms':30,'diagnostics':{
        'latent_norm':1.,'prediction_error':.5,'strict_true':True}}
    assert causal_cortex_evidence(raw,9)=={}
    evidence=causal_cortex_evidence(raw,20)
    assert evidence['diagnostics']['prediction_error'] is None
    assert 'strict_true' not in evidence['diagnostics']
    assert causal_cortex_evidence(raw,40)['diagnostics']['prediction_error']==.5

def test_online_challenger_waits_resumes_once_and_preserves_seed(tmp_path):
    from research.hype_local_only.jepa_online import OnlineJEPAChallenger
    torch.set_num_threads(2);model=NumericJEPA(cfg())
    seed={'schema':1,'config':asdict(cfg()),'model':copy.deepcopy(model.state_dict()),'optimizer':None,
          'normalization':{'mean':[0]*16,'scale':[1]*16},'dataset_sha256':'synthetic','promoted':False}
    x=torch.randn(4,8,32);targets=[torch.randn_like(x) for _ in cfg().horizons]
    before={k:v.clone() for k,v in seed['model'].items()}
    with OnlineJEPAChallenger(tmp_path,seed) as learner:
        assert learner.observe('minute1',x,[],10,30,20)=='WAITING_FOR_FUTURE_STATE'
        assert not learner.state['learned_ssl']
    with OnlineJEPAChallenger(tmp_path,seed) as learner:
        assert learner.observe('minute1',x,targets,10,30,31)=='CHALLENGER_UPDATED'
        assert learner.observe('minute1',x,targets,10,30,32)=='ALREADY_LEARNED'
        assert learner.state['heads_require_revalidation'] and not learner.state['promoted']
    assert all(torch.equal(before[k],seed['model'][k]) for k in before)

def test_online_cannot_pull_future_target_clock_backward(tmp_path):
    from research.hype_local_only.jepa_online import OnlineJEPAChallenger
    seed={'schema':1,'config':asdict(cfg()),'model':NumericJEPA(cfg()).state_dict(),'optimizer':None,'promoted':False}
    x=torch.randn(2,8,32)
    with OnlineJEPAChallenger(tmp_path,seed) as learner:
        assert learner.observe('x',x,[],10,30,20)=='WAITING_FOR_FUTURE_STATE'
        with pytest.raises(ValueError,match='target clock regressed'):
            learner.observe('x',x,[x,x],10,25,26)
