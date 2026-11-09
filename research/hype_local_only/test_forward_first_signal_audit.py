import json
from pathlib import Path

from research.hype_local_only.forward_first_signal_audit import audit


def put(path,rows):
    path.write_text("\n".join(json.dumps(x) for x in rows)+"\n",encoding="utf-8")


def test_forward_audit_penalizes_false_signal_that_arrives_before_true(tmp_path: Path):
    labels=tmp_path/"labels.jsonl"
    events=tmp_path/"events.jsonl"
    out=tmp_path/"out.json"

    label_rows=[
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L1","side":"LOW",
         "stage":60,"extreme_ts_ms":100_000,"extreme_price":10.0,"teacher_finalized_ts_ms":400_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"H1","side":"HIGH",
         "stage":60,"extreme_ts_ms":200_000,"extreme_price":12.0,"teacher_finalized_ts_ms":500_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L2","side":"LOW",
         "stage":60,"extreme_ts_ms":300_000,"extreme_price":11.0,"teacher_finalized_ts_ms":600_000},
    ]
    event_rows=[
        {"event":"INTERNAL_TACTICAL_SIGNAL","candidate_id":"F-H","side":"HIGH",
         "candidate_ts_ms":150_000,"signal_ts_ms":160_000,"stage":60,"probability":.9},
        {"event":"INTERNAL_TACTICAL_SIGNAL","candidate_id":"H1","side":"HIGH",
         "candidate_ts_ms":200_000,"signal_ts_ms":205_000,"stage":60,"probability":.95},
        {"event":"INTERNAL_TACTICAL_SIGNAL","candidate_id":"L2","side":"LOW",
         "candidate_ts_ms":300_000,"signal_ts_ms":305_000,"stage":60,"probability":.96},
    ]
    put(labels,label_rows);put(events,event_rows)
    r=audit(labels,events)
    assert r["metrics"]["episodes"]==2
    assert r["metrics"]["true_first"]==1
    assert r["metrics"]["false_first"]==1
    assert r["metrics"]["precision"]==.5
    assert not r["promotion_gate"]["passed"]


def test_old_label_rows_without_extreme_timestamp_are_not_invented(tmp_path: Path):
    labels=tmp_path/"labels.jsonl";events=tmp_path/"events.jsonl"
    put(labels,[{"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"old","side":"LOW","stage":60}])
    put(events,[])
    r=audit(labels,events)
    assert r["terminal_labels"]==0
    assert r["status"]=="ACCUMULATING_FORWARD_EVIDENCE"


def test_hard120_event_uses_actionable_deadline(tmp_path: Path):
    labels=tmp_path/"labels.jsonl";events=tmp_path/"events.jsonl"
    label_rows=[
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L1","side":"LOW",
         "stage":60,"extreme_ts_ms":100_000,"extreme_price":10.0,"teacher_finalized_ts_ms":400_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"H1","side":"HIGH",
         "stage":60,"extreme_ts_ms":200_000,"extreme_price":12.0,"teacher_finalized_ts_ms":500_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L2","side":"LOW",
         "stage":60,"extreme_ts_ms":300_000,"extreme_price":11.0,"teacher_finalized_ts_ms":600_000},
    ]
    # H1 signal arrives after the next Local's extreme, so it is too late.
    event_rows=[
        {"event":"INTERNAL_HARD120_SIGNAL","candidate_id":"H1","side":"HIGH",
         "candidate_ts_ms":200_000,"signal_ts_ms":305_000},
    ]
    put(labels,label_rows);put(events,event_rows)
    r=audit(labels,events,event_names="INTERNAL_HARD120_SIGNAL",actionable=True)
    assert r["signal_event"]=="INTERNAL_HARD120_SIGNAL"
    assert r["actionable_deadline_enabled"] is True
    assert r["metrics"]["episodes"]==1
    assert r["metrics"]["accepted_first"]==0
    assert r["metrics"]["no_signal"]==1


def test_combined_survival_ladder_scores_first_of_hard90_or_hard120(tmp_path: Path):
    labels=tmp_path/"labels.jsonl";events=tmp_path/"events.jsonl"
    label_rows=[
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L1","side":"LOW",
         "stage":60,"extreme_ts_ms":100_000,"extreme_price":10.0,"teacher_finalized_ts_ms":400_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"H1","side":"HIGH",
         "stage":60,"extreme_ts_ms":200_000,"extreme_price":12.0,"teacher_finalized_ts_ms":500_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L2","side":"LOW",
         "stage":60,"extreme_ts_ms":400_000,"extreme_price":11.0,"teacher_finalized_ts_ms":700_000},
    ]
    event_rows=[
        {"event":"INTERNAL_HARD90_SIGNAL","candidate_id":"H1","side":"HIGH",
         "candidate_ts_ms":200_000,"signal_ts_ms":250_000},
        {"event":"INTERNAL_HARD120_SIGNAL","candidate_id":"H1","side":"HIGH",
         "candidate_ts_ms":200_000,"signal_ts_ms":260_000},
    ]
    put(labels,label_rows);put(events,event_rows)
    r=audit(labels,events,event_names=["INTERNAL_HARD90_SIGNAL","INTERNAL_HARD120_SIGNAL"],actionable=True)
    assert r["signal_events"]==["INTERNAL_HARD90_SIGNAL","INTERNAL_HARD120_SIGNAL"]
    assert r["metrics"]["true_first"]==1
    assert r["metrics"]["accepted_first"]==1


def test_stage_filter_scores_60_180_300_independently(tmp_path: Path):
    labels=tmp_path/"labels.jsonl";events=tmp_path/"events.jsonl"
    label_rows=[
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L1","side":"LOW",
         "stage":60,"extreme_ts_ms":100_000,"extreme_price":10.0,"teacher_finalized_ts_ms":400_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"H1","side":"HIGH",
         "stage":60,"extreme_ts_ms":200_000,"extreme_price":12.0,"teacher_finalized_ts_ms":500_000},
        {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L2","side":"LOW",
         "stage":60,"extreme_ts_ms":400_000,"extreme_price":11.0,"teacher_finalized_ts_ms":700_000},
    ]
    event_rows=[
        {"event":"INTERNAL_TACTICAL_SIGNAL","candidate_id":"F-H","side":"HIGH",
         "candidate_ts_ms":150_000,"signal_ts_ms":151_000,"stage":60,"probability":.91},
        {"event":"INTERNAL_TACTICAL_SIGNAL","candidate_id":"H1","side":"HIGH",
         "candidate_ts_ms":200_000,"signal_ts_ms":203_000,"stage":180,"probability":.95},
        {"event":"INTERNAL_TACTICAL_SIGNAL","candidate_id":"H1","side":"HIGH",
         "candidate_ts_ms":200_000,"signal_ts_ms":205_000,"stage":300,"probability":.97},
    ]
    put(labels,label_rows);put(events,event_rows)

    r60=audit(labels,events,stages=[60])
    assert r60["signal_stages"]==[60]
    assert r60["tactical_signal_rows"]==1
    assert r60["metrics"]["false_first"]==1

    r180=audit(labels,events,stages=[180])
    assert r180["signal_stages"]==[180]
    assert r180["tactical_signal_rows"]==1
    assert r180["metrics"]["true_first"]==1
    assert r180["metrics"]["false_first"]==0

    r300=audit(labels,events,stages=[300])
    assert r300["signal_stages"]==[300]
    assert r300["tactical_signal_rows"]==1
    assert r300["metrics"]["true_first"]==1
