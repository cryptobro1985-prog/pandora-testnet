from pathlib import Path

def test_instagram_only_ui():
    text=(Path(__file__).resolve().parents[1]/"web"/"index.html").read_text(encoding="utf-8")
    assert "Instagram Intelligence" in text
    assert "FULL SCAN" in text
    assert "VK" not in text
    assert "ВКонтакте" not in text
