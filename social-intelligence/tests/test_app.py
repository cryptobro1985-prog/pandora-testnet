from fastapi.testclient import TestClient
from app import app, score

client=TestClient(app)

def test_health():
    r=client.get("/api/health")
    assert r.status_code==200
    assert r.json()["service"]=="instagram-intelligence"

def test_capabilities_instagram_only():
    r=client.get("/api/capabilities")
    assert r.status_code==200
    assert r.json()["instagram_only"] is True

def test_score_orders_activity():
    rows=score("target",[
        {"kind":"comment_in","actor":"alice"},
        {"kind":"comment_in","actor":"alice"},
        {"kind":"like_in","actor":"bob"},
    ])
    assert rows[0]["username"]=="alice"
    assert rows[0]["comments_in"]==2
