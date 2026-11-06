from pathlib import Path
from types import SimpleNamespace

from research.hype_caterpillar_quant.learner import CaterpillarQuantLearner
from research.hype_quant.learner import load_config

H=3_600_000

def new():
    return CaterpillarQuantLearner(load_config(Path("research/hype_quant/config.json")))

def fake_state(side="LOW"):
    # Strict L6/K2 pivot at hour 6, available after hours 7 and 8 complete.
    candles={}
    for i in range(10):
        base=100.0+i*.15
        candles[i*H]={"start_ms":i*H,"open":base,"close":base,"high":base+1.0,"low":base-1.0}
    if side=="LOW":
        candles[6*H]["low"]=90.0
        candles[7*H]["low"]=95.0
        candles[8*H]["low"]=96.0
    else:
        candles[6*H]["high"]=112.0
        candles[7*H]["high"]=108.0
        candles[8*H]["high"]=107.0
    return SimpleNamespace(candles={"60":candles})

def x():
    return {
        "agent_consensus":0.0,
        "flow_imbalance_raw_60s":0.0,
        "book_imbalance_25":0.0,
        "micro_gap_seconds":1.0,
        "book_valid_micro":1.0,
        "raw_age_ms":10.0,
    }

def test_construct():
    q=new()
    r=q.report()
    assert r["research_only"] is True and r["real_orders"] is False
    assert q.LOCAL_STAGES==(60,180,300)
    assert set(q.candidates)=={"LOW","HIGH"}
    assert len(q.local_models)==6 and len(q.bounce_models)==6
    assert q.exit_labels==0 and q.reentry_labels==0
    assert q.policy_contract_version==7
    assert q.local_policy_version==3
    assert len(q.policy_models)==6
    assert q.report()["direct_policy"]["manual_action_thresholds"] is False
    assert q.report()["local_learning_contract"]["strict_h1_execution"] is False

def fake_provisional_low_state():
    candles={}
    for i in range(10):
        candles[i*H]={"start_ms":i*H,"open":100.0,"close":100.0,
                      "high":105.0-i*.1,"low":95.0+i*.1}
    # Within the last six completed H1s, the newest hour owns the newest low,
    # while the highest high belongs to an older hour.
    candles[9*H]["low"]=90.0
    candles[4*H]["high"]=110.0
    return SimpleNamespace(candles={"60":candles})

def test_same_h1_extremes_use_m1_order_training_only():
    q=new()
    candles60={}
    for i in range(10):
        candles60[i*H]={"start_ms":i*H,"open":100.0,"close":100.0,"high":104.0,"low":96.0}
    candles60[9*H]={"start_ms":9*H,"open":100.0,"close":99.0,"high":110.0,"low":90.0}
    candles1={}
    for j in range(60):
        st=9*H+j*60_000
        candles1[st]={"start_ms":st,"open":100.0,"close":100.0,"high":103.0,"low":97.0}
    candles1[9*H+5*60_000]["high"]=110.0
    candles1[9*H+45*60_000]["low"]=90.0
    s=SimpleNamespace(candles={"60":candles60,"1":candles1})
    ev=q._bootstrap_provisional_local(s,10*H+10*60_000,92.0,x())
    assert any(e["event"]=="PROVISIONAL_H1_LOCAL_BOOTSTRAP" and e["side"]=="LOW" for e in ev)
    assert q.bootstrap_diagnostic["resolution"]=="M1_INTRAHOUR_ORDER"
    assert q.bootstrap_diagnostic["m1_resolved_side"]=="LOW"
    assert q.last_confirmed_local is None and q.position is None

def test_provisional_low_is_training_only_not_policy():
    q=new();s=fake_provisional_low_state();ts=10*H+10*60_000
    ev=q._bootstrap_provisional_local(s,ts,92.0,x())
    assert any(e["event"]=="PROVISIONAL_H1_LOCAL_BOOTSTRAP" and e["side"]=="LOW" for e in ev)
    assert q.last_confirmed_local is None
    assert q.position is None

def promote_learned(q,side="LOW",ts=10*H,price=None):
    q._ensure_v2()
    price=float(price if price is not None else (90.0 if side=="LOW" else 110.0))
    c=q._new_candidate(side,price,ts,x())
    q.local_labels[(side,60)]=q.LOCAL_MIN_LABELS_PER_STAGE
    q._model_p=lambda model,features:.80
    ev=q._stage_candidate(c,ts+61_000,price*(1.01 if side=="LOW" else .99),x())
    q.__dict__.pop("_model_p",None)
    assert q.last_confirmed_local is c
    assert c.source=="LEARNED_CAUSAL_LOCAL"
    assert any(e["event"]=="LOCAL_STAGE" and e["policy_promoted"] for e in ev)
    return c,ev

def test_pretraining_confirmed_local_is_inherited_once_not_counted_as_learned():
    q=new();s=fake_state("LOW");ts=10*H
    out=q.observe(ts,100.0,x(),s)
    assert q.last_teacher_local is not None and q.last_teacher_local["side"]=="LOW"
    assert q.last_confirmed_local is not None
    assert q.last_confirmed_local.side=="LOW"
    assert q.last_confirmed_local.source=="INHERITED_CONFIRMED_LOCAL"
    assert q.last_confirmed_local.extreme_price==90.0
    assert q.learned_local_history==[]
    assert q.inherited_local_history and q.inherited_local_history[-1]["side"]=="LOW"
    assert len(q.policy_pending)==3
    assert any(e["event"]=="INHERITED_PRETRAIN_LOCAL" for e in out["events"])
    assert not any(e["event"]=="STRICT_H1_LOCAL_SYNC" for e in out["events"])
    assert q.last_policy_decision["action"]=="WAIT"
    assert q.last_policy_decision["structural_side"]=="LONG"


def fake_two_pivot_state():
    candles={}
    for i in range(14):
        base=100.0
        candles[i*H]={"start_ms":i*H,"open":base,"close":base,"high":103.0,"low":97.0}
    candles[6*H]["high"]=112.0
    candles[7*H]["high"]=105.0
    candles[8*H]["high"]=104.0
    candles[10*H]["low"]=88.0
    candles[11*H]["low"]=94.0
    candles[12*H]["low"]=95.0
    return SimpleNamespace(candles={"60":candles})


def test_pretraining_context_bootstraps_fibonacci_swing_without_faking_learning():
    q=new();s=fake_two_pivot_state();ts=14*H
    q.observe(ts,92.0,x(),s)
    report=q.report()
    assert report["active_local"]["side"]=="LOW"
    assert report["active_local"]["source"]=="INHERITED_CONFIRMED_LOCAL"
    assert report["learned_local_history"]==[]
    assert len(report["inherited_local_history"])>=2
    fib=report["fibonacci"]["current"]
    assert fib["available"] is True
    assert fib["swing_from"]["side"]=="HIGH"
    assert fib["swing_to"]["side"]=="LOW"

def test_learned_low_samples_direct_long_policy():
    q=new();ts=10*H
    c,_=promote_learned(q,"LOW",ts,90.0)
    q._sample_direct_policy(ts+62_000,91.0,x(),c,{"action":"FLAT","score":0.0})
    assert len(q.policy_pending)==3
    assert {p.side for p in q.policy_pending}=={1}
    assert {p.mode for p in q.policy_pending}=={"FLAT"}

def test_learned_high_samples_direct_short_policy():
    q=new();ts=10*H
    c,_=promote_learned(q,"HIGH",ts,110.0)
    q._sample_direct_policy(ts+62_000,109.0,x(),c,{"action":"FLAT","score":0.0})
    assert len(q.policy_pending)==3
    assert {p.side for p in q.policy_pending}=={-1}

def test_gap_censors_position_not_trade():
    q=new();ts=10*H
    c,_=promote_learned(q,"LOW",ts,90.0)
    q._open(ts,100.0,1,c,.9,{"action":"LONG"},reentry=False)
    before=len(q.trades)
    q.on_gap(ts+11_000,"TEST_GAP")
    assert q.position is None
    assert len(q.trades)==before
    assert q.censored_positions==1
    assert q.last_confirmed_local is not None
    assert q.last_confirmed_local.source=="LEARNED_CAUSAL_LOCAL"
    assert q.last_confirmed_local.side=="LOW"
    assert any(e["event"]=="CENSORED_POSITION" for e in q.actions)
    assert any(e["event"]=="LOCAL_CONTEXT_PRESERVED_ON_GAP" for e in q.actions)

def test_same_local_reentry_survives_candidate_id_change():
    q=new();ts=10*H
    c0,_=promote_learned(q,"LOW",ts,90.0)
    q._open(ts,92.0,1,c0,.9,{"action":"LONG"},reentry=False)
    assert q.position is not None
    q._close(ts+70_000,92.1,"TEST_EXIT")
    old_key=q.last_exit.get("local_key")
    assert old_key
    # Simulate restart/bootstrap regenerating a candidate id for the same H1 local.
    q.candidate_seq+=1
    old=q.last_confirmed_local
    from research.hype_caterpillar_quant.learner import Candidate
    c=Candidate(q.candidate_seq,old.side,old.extreme_price,old.extreme_ts_ms,dict(old.created_x),
                confirmed_stage=300,source=old.source,strict_hour_ms=old.strict_hour_ms)
    c.stage_conf[300]=.9
    q.last_confirmed_local=c
    assert q._same_local_episode(c) is True

def test_subcost_mfe_noise_does_not_force_bootstrap_exit():
    q=new();s=fake_state("LOW");ts=10*H
    c,_=promote_learned(q,"LOW",ts,90.0)
    q._open(ts,100.0,1,c,.9,{"action":"LONG"},reentry=False)
    assert q.position is not None and q.position.side==1
    entry=q.position.entry_price
    # Build a small MFE below round-trip costs, then give some of it back.
    q.observe(ts+70_000,entry*1.0013,{**x(),"agent_consensus":0.0,"flow_imbalance_raw_60s":0.0},s)
    out=q.observe(ts+130_000,entry*1.0004,{**x(),"agent_consensus":-0.30,"flow_imbalance_raw_60s":0.0},s)
    assert q.position is not None, out
    assert not any(e["event"]=="EXIT" for e in out["events"])

def test_strict_benchmark_cannot_override_learned_policy_local():
    q=new();ts=10*H
    learned,_=promote_learned(q,"LOW",ts,90.0)
    q.last_teacher_local={"side":"HIGH","price":112.0,"hour_ms":6*H}
    assert q.last_confirmed_local is learned
    assert q._best_local()[0] is learned
    assert q._best_local()[0].source=="LEARNED_CAUSAL_LOCAL"

def test_v3_multiwindow_extreme_proposes_candidate_without_heuristic_confirmation():
    q=new();q._ensure_v2();ts=10*H
    features={**x(),"running_low_300s":99.0,"running_low_900s":98.0,
              "running_high_300s":101.0,"running_high_900s":102.0,
              "rolling_6h_low":95.0,"rolling_6h_high":105.0}
    ev=q._update_extremes(ts,99.0,features,fake_state("LOW"))
    low=q.candidates["LOW"]
    assert low is not None
    assert low.confirmed_stage is None
    assert low.source=="LIVE_CANDIDATE"
    assert low.evidence["proposal"]=="CAUSAL_MULTIWINDOW_EXTREME_V3"
    assert low.evidence["future_used"] is False
    assert any(e["event"]=="NEW_LOCAL_CANDIDATE" and e["side"]=="LOW" for e in ev)


def test_v3_local_label_matures_on_five_minute_future_path():
    q=new();q._ensure_v2();ts=10*H
    assert q.LOCAL_LABEL_HORIZON_S==300
    c=q._new_candidate("LOW",100.0,ts,x())
    from research.hype_caterpillar_quant.learner import LocalPending
    q.local_pending.append(LocalPending(
        candidate_id=c.ident,side="LOW",stage_s=60,ts_ms=ts,price=100.0,x=x(),
        candidate_hour_ms=ts//H*H,strict_mature_ts_ms=0,
        bounce_mature_ts_ms=ts+300_000,best_favorable=0.0,worst_adverse=0.0,bounce_done=False
    ))
    q._advance_local_labels(ts+299_000,101.0,fake_state("HIGH"))
    assert q.local_labels[("LOW",60)]==0
    q._advance_local_labels(ts+301_000,101.0,fake_state("HIGH"))
    assert q.local_labels[("LOW",60)]==1
    assert q.local_pos[("LOW",60)]==1


def test_market_outcome_labels_local_not_strict_formula():
    q=new();q._ensure_v2();ts=10*H
    c=q._new_candidate("LOW",100.0,ts,x())
    from research.hype_caterpillar_quant.learner import LocalPending
    q.local_pending.append(LocalPending(
        candidate_id=c.ident,side="LOW",stage_s=60,ts_ms=ts,price=100.0,x=x(),
        candidate_hour_ms=ts//H*H,strict_mature_ts_ms=0,
        bounce_mature_ts_ms=ts+60_000,best_favorable=0.0,worst_adverse=0.0,bounce_done=False
    ))
    q._advance_local_labels(ts+61_000,101.0,fake_state("HIGH"))
    assert q.local_labels[("LOW",60)]==1
    assert q.local_pos[("LOW",60)]==1

def test_strict_benchmark_available_after_k2():
    q=new();s=fake_state("LOW")
    # Construct a live candidate inside pivot hour 6 and a 60s stage sample.
    c=q._new_candidate("LOW",90.0,6*H+30_000,x())
    p=SimpleNamespace(
        candidate_id=c.ident,side="LOW",stage_s=60,ts_ms=6*H+90_000,
        price=90.5,x=x(),candidate_hour_ms=6*H,
        strict_mature_ts_ms=9*H,bounce_mature_ts_ms=6*H+1_890_000,
        best_favorable=0.0,worst_adverse=0.0,bounce_done=False,
    )
    assert q._strict_candidate_outcome(s,p,8*H+59_999) is None
    assert q._strict_candidate_outcome(s,p,9*H) is True

def main():
    test_construct()
    test_same_h1_extremes_use_m1_order_training_only()
    test_provisional_low_is_training_only_not_policy()
    test_pretraining_confirmed_local_is_inherited_once_not_counted_as_learned()
    test_pretraining_context_bootstraps_fibonacci_swing_without_faking_learning()
    test_learned_low_samples_direct_long_policy()
    test_learned_high_samples_direct_short_policy()
    test_gap_censors_position_not_trade()
    test_same_local_reentry_survives_candidate_id_change()
    test_subcost_mfe_noise_does_not_force_bootstrap_exit()
    test_strict_benchmark_cannot_override_learned_policy_local()
    test_v3_multiwindow_extreme_proposes_candidate_without_heuristic_confirmation()
    test_v3_local_label_matures_on_five_minute_future_path()
    test_market_outcome_labels_local_not_strict_formula()
    test_strict_benchmark_available_after_k2()
    print("HYPE_CATERPILLAR_V3_SELFTEST_OK")

if __name__=="__main__":
    main()
