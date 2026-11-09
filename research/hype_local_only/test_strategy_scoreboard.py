import json
from pathlib import Path
from research.hype_local_only.strategy_scoreboard import build_scoreboard

def write_status(root: Path,name: str,*,episodes:int,true:int,false:int,precision:float,recall:float,passed:bool):
    (root/name).write_text(json.dumps({
        "status":"FORWARD_GATE_PASS" if passed else "ACCUMULATING_FORWARD_EVIDENCE",
        "metrics":{"episodes":episodes,"accepted_first":true+false,"true_first":true,
                   "false_first":false,"precision":precision,"recall":recall},
        "promotion_gate":{"passed":passed},
    }),encoding="utf-8")

def test_tiny_perfect_sample_cannot_beat_mature_candidate(tmp_path: Path):
    write_status(tmp_path,"TACTICAL_60S_FORWARD_STATUS.json",
                 episodes=2,true=1,false=0,precision=1.0,recall=.5,passed=False)
    write_status(tmp_path,"TACTICAL_180S_FORWARD_STATUS.json",
                 episodes=30,true=18,false=2,precision=.9,recall=.6,passed=True)
    s=build_scoreboard(tmp_path)
    assert s["winner"]["strategy"]=="TACTICAL_180S"
    assert s["winner"]["promotion_gate_passed"] is True

def test_latency_breaks_exact_metric_tie_in_favor_of_earlier_signal(tmp_path: Path):
    write_status(tmp_path,"TACTICAL_60S_FORWARD_STATUS.json",
                 episodes=30,true=18,false=2,precision=.9,recall=.6,passed=True)
    write_status(tmp_path,"TACTICAL_300S_FORWARD_STATUS.json",
                 episodes=30,true=18,false=2,precision=.9,recall=.6,passed=True)
    s=build_scoreboard(tmp_path)
    assert s["winner"]["strategy"]=="TACTICAL_60S"
