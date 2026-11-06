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

def test_strict_bootstrap_low_enters_long():
    q=new();s=fake_state("LOW");ts=10*H
    out=q.observe(ts,100.0,x(),s)
    assert q.last_confirmed_local is not None
    assert q.last_confirmed_local.side=="LOW"
    assert q.last_confirmed_local.source=="STRICT_H1_CONFIRMED"
    assert q.position is not None and q.position.side==1
    assert any(e["event"]=="STRICT_H1_LOCAL_SYNC" for e in out["events"])
    assert any(e["event"]=="ENTER" and e["side"]=="LONG" for e in out["events"])

def test_strict_bootstrap_high_enters_short():
    q=new();s=fake_state("HIGH");ts=10*H
    out=q.observe(ts,100.0,x(),s)
    assert q.last_confirmed_local is not None and q.last_confirmed_local.side=="HIGH"
    assert q.position is not None and q.position.side==-1
    assert any(e["event"]=="ENTER" and e["side"]=="SHORT" for e in out["events"])

def test_gap_censors_position_not_trade():
    q=new();s=fake_state("LOW");ts=10*H
    q.observe(ts,100.0,x(),s)
    before=len(q.trades)
    q.on_gap(ts+11_000,"TEST_GAP")
    assert q.position is None
    assert len(q.trades)==before
    assert q.censored_positions==1
    assert any(e["event"]=="CENSORED_POSITION" for e in q.actions)

def test_same_local_reentry_survives_candidate_id_change():
    q=new();s=fake_state("LOW");ts=10*H
    q.observe(ts,92.0,x(),s)
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
    q.observe(ts,100.0,x(),s)
    assert q.position is not None and q.position.side==1
    entry=q.position.entry_price
    # Build a small MFE below round-trip costs, then give some of it back.
    q.observe(ts+70_000,entry*1.0013,{**x(),"agent_consensus":0.0,"flow_imbalance_raw_60s":0.0},s)
    out=q.observe(ts+130_000,entry*1.0004,{**x(),"agent_consensus":-0.30,"flow_imbalance_raw_60s":0.0},s)
    assert q.position is not None, out
    assert not any(e["event"]=="EXIT" for e in out["events"])

def test_provisional_never_overrides_strict_structural_anchor():
    q=new()
    from research.hype_caterpillar_quant.learner import Candidate
    strict=Candidate(1,"LOW",76.211,6*H,dict(x()),confirmed_stage=300,
                     source="STRICT_H1_CONFIRMED",strict_hour_ms=6*H)
    strict.stage_conf[300]=.99
    q.last_confirmed_local=strict
    provisional=Candidate(2,"LOW",76.844,13*H,dict(x()),
                          source="PROVISIONAL_H1_EXTREME",strict_hour_ms=13*H)
    out=q._stage_candidate(provisional,14*H,77.5,x())
    assert provisional.confirmed_stage is not None
    assert q.last_confirmed_local is strict
    assert q.last_confirmed_local.extreme_price==76.211
    assert any(e["event"]=="LOCAL_STAGE" and e["accepted"] and not e["policy_promoted"] for e in out)

def test_strict_target_available_after_k2():
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
    test_strict_bootstrap_low_enters_long()
    test_strict_bootstrap_high_enters_short()
    test_gap_censors_position_not_trade()
    test_same_local_reentry_survives_candidate_id_change()
    test_subcost_mfe_noise_does_not_force_bootstrap_exit()
    test_provisional_never_overrides_strict_structural_anchor()
    test_strict_target_available_after_k2()
    print("HYPE_CATERPILLAR_V2_SELFTEST_OK")

if __name__=="__main__":
    main()
