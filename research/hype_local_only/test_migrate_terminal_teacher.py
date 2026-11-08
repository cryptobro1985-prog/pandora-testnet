import pickle
from pathlib import Path

from research.hype_local_only.migrate_terminal_teacher import (
    MIGRATION_ID,
    already_migrated,
    sanitize_model,
    sanitize_runtime,
)
from research.hype_local_only.model import LocalOnlyModel


def train_marker(m,internal=False):
    x={"x":1.0}
    if internal:
        for i in range(20):m.learn_internal("LOW",60,x,i<4,source="live")
    else:
        for i in range(5):m.learn("LOW",60,x,i==0,source="live")


def test_sanitize_replaces_strict_but_preserves_internal():
    cur=LocalOnlyModel();clean=LocalOnlyModel()
    train_marker(cur,False);train_marker(cur,True)
    for i in range(3):clean.learn("HIGH",60,{"z":2.0},i==0)
    clean.history_meta={"teacher":"strict_true"}

    old=sanitize_model(cur,clean)
    assert old["strict_live_labels_discarded"]==5
    assert cur.live_labels==0
    assert cur.labels==clean.labels
    assert cur.positive==clean.positive
    assert cur.internal_labels[("LOW",60)]==20
    assert cur.internal_positive[("LOW",60)]==4
    assert cur.h1_shadow=={}
    assert cur.last_signal is None
    assert already_migrated(cur)
    assert cur.history_meta["terminal_teacher_migration"]["id"]==MIGRATION_ID


def test_runtime_structural_anchor_is_cleared_without_dropping_pending(tmp_path: Path):
    p=tmp_path/"runtime.pkl"
    rt={"expected_side":"HIGH","last_teacher_local":{"side":"LOW"},
        "structure_48h":{"locals":[1]},"candidates":{"LOW":"x"},"pending":[1,2]}
    with p.open("wb") as f:pickle.dump(rt,f)
    out=sanitize_runtime(p)
    assert out["structural_anchor_cleared"]
    with p.open("rb") as f:new=pickle.load(f)
    assert new["expected_side"] is None
    assert new["last_teacher_local"] is None
    assert new["structure_48h"]=={}
    assert new["pending"]==[1,2]
    assert new["candidates"]=={"LOW":"x"}
