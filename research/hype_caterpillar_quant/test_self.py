from research.hype_caterpillar_quant.learner import CaterpillarQuantLearner
from research.hype_quant.learner import load_config
from pathlib import Path

def test_construct():
    q=CaterpillarQuantLearner(load_config(Path("research/hype_quant/config.json")))
    r=q.report()
    assert r["research_only"] is True
    assert r["real_orders"] is False
    assert set(q.candidates)=={"LOW","HIGH"}

def test_binary_heads_exist():
    q=CaterpillarQuantLearner(load_config(Path("research/hype_quant/config.json")))
    assert len(q.local_models)==6
    assert q.exit_labels==0
