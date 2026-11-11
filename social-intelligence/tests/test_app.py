import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import app
from analysis import relationship_report,audience_quality,build_events

client=TestClient(app)

def test_health():
    r=client.get("/api/health")
    assert r.status_code==200
    assert r.json()["service"]=="instagram-intelligence"
    assert r.json()["version"]=="2.0.0"

def test_capabilities_instagram_only():
    r=client.get("/api/capabilities")
    assert r.status_code==200
    data=r.json()
    assert data["instagram_only"] is True
    assert "2scraper/instagram-scraper" in data["open_source_components"]
    assert "instaloader/instaloader" in data["open_source_components"]

def test_relationship_scores_and_badges():
    events=[
      {"kind":"comment_in","actor":"alice","direction":"inbound"},
      {"kind":"comment_in","actor":"alice","direction":"inbound"},
      {"kind":"like_in","actor":"bob","direction":"inbound"},
      {"kind":"mention_out","actor":"alice","direction":"outbound"},
    ]
    followers=[{"pk":"1","username":"alice"}]
    following=[{"pk":"1","username":"alice"},{"pk":"2","username":"bob"}]
    rows=relationship_report("target",events,followers,following)
    by={x["username"]:x for x in rows}
    assert by["alice"]["comments_in"]==2
    assert "mutuals" in by["alice"]["badges"]
    assert "notFollowingBack" in by["bob"]["badges"]
    assert by["alice"]["score"]>by["bob"]["score"]

def test_audience_quality():
    followers=[{"pk":"1","username":"alice"},{"pk":"2","username":"bob"}]
    events=[{"kind":"comment_in","actor":"alice","direction":"inbound"}]
    q=audience_quality(followers,events)
    assert q["status"]=="ok"
    assert q["engaged_followers"]==1
    assert q["ghost_candidates"]==1

def test_build_events_dedupes():
    posts=[{"permalink":"x","timestamp":"2026-01-01T00:00:00Z","comments_detail":[{"username":"alice","text":"hi","timestamp":"t"}],"likers":["bob"],"mentions":["carol"],"tagged_users":["dave"],"coauthors":["eve"]}]
    e=build_events("target",posts)
    kinds={x["kind"] for x in e}
    assert {"comment_in","like_in","mention_out","tag_out","coauthor_out"} <= kinds


def test_caption_mentions_fallback():
    e=build_events("target",[{"permalink":"x","timestamp":"2026-01-01T00:00:00Z","caption":"hello @alice and @bob.","comments_detail":[],"likers":[]}])
    assert {x["actor"] for x in e if x["kind"]=="mention_out"}=={"alice","bob"}
