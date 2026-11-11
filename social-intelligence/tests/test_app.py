import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from app import app, normalize_profile

client = TestClient(app)


@pytest.mark.parametrize("platform,url,expected", [
    ("instagram", "https://www.instagram.com/example_user/?hl=en", "https://instagram.com/example_user"),
    ("vk", "https://vk.com/public123", "https://vk.com/public123"),
    ("telegram", "https://t.me/example_channel", "https://t.me/example_channel"),
])
def test_valid_profiles(platform, url, expected):
    assert normalize_profile(platform, url) == expected


@pytest.mark.parametrize("platform,url", [
    ("instagram", "https://evil.com/username"),
    ("instagram", "http://127.0.0.1/username"),
    ("instagram", "https://instagram.com/p/ABCD"),
    ("telegram", "https://t.me/+invitehash"),
    ("telegram", "https://t.me/joinchat/secret"),
    ("vk", "https://vk.com/a/b"),
    ("vk", "https://vk.com@evil.com/username"),
    ("vk", "https://vk.com:8443/example"),
])
def test_reject_untrusted_links(platform, url):
    with pytest.raises(ValueError):
        normalize_profile(platform, url)


def test_requires_authorization():
    assert client.post("/api/analyze", json={
        "authorized": False,
        "profiles": [{"platform": "vk", "url": "https://vk.com/hello"}]
    }).status_code == 403


def test_report_does_not_fabricate_social_activity():
    r = client.post("/api/analyze", json={
        "authorized": True,
        "profiles": [{"platform": "vk", "url": "https://vk.com/public123"}],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["data_access"] == "user_supplied_links_only"
    assert data["profiles"][0]["status"] == "link_verified"
    assert "interactions" not in data
    assert "private_messages" in data["unsupported"]


def test_health():
    assert client.get("/api/health").json()["ok"] is True


def test_capabilities_endpoint_is_explicit_about_limits():
    r = client.get("/api/capabilities")
    assert r.status_code == 200
    data = r.json()["platforms"]
    assert set(data) == {"instagram", "vk", "telegram"}
    assert data["instagram"]["followers_history"] is False
    assert data["instagram"]["viewer_identity"] is False
    assert data["vk"]["private_messages"] is False
    assert data["telegram"]["all_user_groups"] is False


def test_search_empty_payload():
    r = client.post("/api/search", json={"profiles": []})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "complete"
    assert data["results"] == []


def test_search_rejects_bad_profile_without_network():
    r = client.post("/api/search", json={
        "profiles": [{"platform": "instagram", "url": "https://evil.example/user"}]
    })
    assert r.status_code == 200
    item = r.json()["results"][0]
    assert item["platform"] == "instagram"
    assert item["status"] == "invalid"


def test_search_public_collectors_shape(monkeypatch):
    import app as appmod

    async def fake_page(url):
        return {"status":"ok","url":url,"title":"x","description":"","image":"","source":"public_profile_page"}
    async def fake_tg(handle, limit=30):
        return {"status":"ok","items":[{"title":"@demo","text":"hello","when":"2026-11-10T10:00:00+00:00","url":"https://t.me/demo/1"}]}
    async def fake_vk(handle, limit=20):
        return {"status":"ok","items":[{"title":"Публикация VK","text":"post","when":"2026-11-10T10:00:00+00:00","url":"https://vk.com/wall1_1"}]}

    monkeypatch.setattr(appmod, "public_profile_page", fake_page)
    monkeypatch.setattr(appmod, "public_telegram_feed", fake_tg)
    monkeypatch.setattr(appmod, "public_vk_wall", fake_vk)

    tg = client.post("/api/search", json={"profiles":[{"platform":"telegram","url":"https://t.me/demo"}]}).json()["results"][0]
    assert tg["events"]["Публичные сообщения"][0]["text"].startswith("hello")

    vk = client.post("/api/search", json={"profiles":[{"platform":"vk","url":"https://vk.com/demo"}]}).json()["results"][0]
    assert vk["events"]["Стена"][0]["url"].endswith("wall1_1")
