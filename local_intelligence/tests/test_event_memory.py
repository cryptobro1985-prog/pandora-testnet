import numpy as np
import pytest
from research.hype_local_only.event_memory import EventMemory

def case(id,hour,available,truth=True):
    return dict(id=id,event_key=f'HIGH:{hour}',side='HIGH',label_available_ms=available,
                local_true=truth,prediction_ts_ms=hour,strict_label_id=hour)

def test_memory_excludes_future_labels_and_same_event_and_deduplicates_hours(tmp_path):
    memory=EventMemory(tmp_path)
    memory.seed([case('a',1,20),case('b',1,20,False),case('c',2,40)],
        np.asarray([[1,2],[2,3],[3,4]],dtype=np.float32),['x','y'],{'source':'x'})
    assert memory.query({'x':1,'y':2},'HIGH',19)['events']==0
    assert memory.query({'x':1,'y':2},'HIGH',30)['events']==1
    assert memory.query({'x':1,'y':2},'HIGH',30,exclude_event_key='HIGH:1')['events']==0
    r=memory.query({'x':1,'y':2},'HIGH',50)
    assert r['events']==2 and r['probability'] is None

def test_mature_case_survives_restart_and_is_learned_once(tmp_path):
    m=EventMemory(tmp_path);m.seed([case('a',1,20)],np.asarray([[1,2]]),['x','y'],{'source':'x'})
    with pytest.raises(ValueError,match='not mature'):m.add(case('b',2,40),[3,4],30)
    assert m.add(case('b',2,40),[3,4],40)
    again=EventMemory(tmp_path)
    assert not again.add(case('b',2,40),[3,4],50)
    assert len(again.state['cases'])==2
