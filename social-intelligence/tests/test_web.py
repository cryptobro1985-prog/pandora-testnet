from html.parser import HTMLParser
from pathlib import Path


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        for key, val in attrs:
            if key == "id":
                self.ids.add(val)
        if tag == "script":
            self.scripts += 1


def test_miniapp_has_controls_and_report_tabs():
    html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
    parser = Tags()
    parser.feed(html)
    assert {"search", "consent", "go", "instagram", "vk", "telegram",
            "lastName", "firstName", "middleName", "birth", "city", "phone", "photo", "report",
            "tabs", "export", "reportContent"} <= parser.ids
    assert parser.scripts == 1
    assert "localStorage" in html
    assert "social_intelligence_search_history_v1" in html
    assert "historyView" in parser.ids
    assert 'innerHTML' not in html
    assert '/api/capabilities' in html


def test_bot_configuration_does_not_embed_secret():
    script = (Path(__file__).resolve().parents[1] / "configure_telegram_menu.py").read_text(encoding="utf-8")
    assert 'os.environ.get("BOT_TOKEN"' in script
    assert "setChatMenuButton" in script
    assert "print(token)" not in script
