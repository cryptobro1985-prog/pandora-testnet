"""Real saved estimator + two process boots on explicit synthetic tape."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from research.hype_local_only.reliability import CheckpointStore

ROOT = Path(__file__).resolve().parents[1]


def test_saved_model_replay_restart_and_statistical_cortex(tmp_path):
    cp, capture = tmp_path / 'checkpoint', tmp_path / 'capture'
    cp.mkdir(); capture.mkdir()
    seed = ROOT / 'artifacts/quantum_research/champion/local_only_model.pkl'
    assert seed.is_file(), 'Saved evaluated research model is required'
    for source in (seed, seed.with_suffix('.pkl.sha256')):
        shutil.copy2(source, cp / source.name)
    end = int(time.time()*1000) - 1000
    base = end - 305000
    minute = base // 60000 * 60000
    candles = [dict(start_ms=minute-i*60000, open=100., high=101., low=99., close=100.)
               for i in range(1,361)]
    def write(name, rows):
        (capture/name).write_text(''.join(json.dumps(row)+'\n' for row in rows))
    write('HYPE_market_context.jsonl', [dict(received_ts_ms=base, candles={'1':candles})])
    write('HYPE_structural_context_1m.jsonl', [dict(ts_ms=base,received_ts_ms=base,
          rolling_6h_low=99.,rolling_6h_high=101.,rolling_60m_low=99.,rolling_60m_high=101.)])
    write('HYPE_live_raw_frames.jsonl', [dict(received_ts_ms=base+1000,raw_text=json.dumps({
        'topic':'publicTrade.HYPEUSDT','ts':base+900,
        'data':[{'T':base+900,'p':'98','v':'1','S':'Sell','i':'synthetic-spike'}]}))])
    write('HYPE_live_microstructure_1s.jsonl', [dict(ts_ms=base+i*5000,mid=100.,
          best_bid=99.99,best_ask=100.01,book_valid=False) for i in range(62)])
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'CORTEX_BACKEND':'disabled',
         'LOCAL_ONLY_MONITOR_URL':'','GITHUB_TOKEN':'','GH_TOKEN':''}
    command=[sys.executable,'-m','research.hype_local_only.live_daemon',
             '--checkpoint-dir',str(cp),'--capture-root',str(capture),'--replay']
    for _ in range(2):
        result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        state=CheckpointStore(cp).load()
        assert state['learner'].live_labels==0
        assert state['runtime']['pending']
        count=len(state['runtime']['pending'])
        events=(cp/'LOCAL_EVENTS.jsonl').read_text().splitlines()
        if _==0:
            first_count,first_events=count,len(events)
        else:
            assert count==first_count and len(events)==first_events
    evidence=[json.loads(line) for line in events]
    assert any(e.get('event')=='LOCAL_STAGE' and e.get('known_training_population') for e in evidence)
    result=subprocess.run([sys.executable,'-m','research.hype_local_only.cortex_daemon',
        '--checkpoint-dir',str(cp),'--minutes','.002','--poll-seconds','.05'],
        cwd=ROOT,env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    cortex=json.loads((cp/'CORTEX_LOCAL_ONLY_STATUS.json').read_text())
    assert cortex['state']=='STATISTICAL_READY'
    assert cortex['errors']==0 and cortex['calls']==0
    assert cortex['llm']['configured_backend']=='disabled'
    assert cortex['llm']['connection_verified'] is False
