"""The one-page homepage Caddy serves at the root of the relay server (relay/site/)."""

import re
from html.parser import HTMLParser
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "relay" / "site"
PAGE = SITE / "index.html"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.anchors, self.local, self.scripts = set(), [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "script":
            self.scripts.append(a.get("src", "inline"))
        for key in ("href", "src"):
            value = a.get(key) or ""
            if value.startswith("#"):
                self.anchors.append(value[1:])
            elif value.startswith("/") and value != "/":
                self.local.append(value.lstrip("/"))
            elif value.startswith("./"):
                self.local.append(value[2:])


def _parse():
    links = _Links()
    links.feed(PAGE.read_text(encoding="utf-8"))
    return links


def test_page_is_korean_and_has_every_section():
    text = PAGE.read_text(encoding="utf-8")
    assert '<html lang="ko">' in text
    ids = _parse().ids
    for section in ("what", "install", "key", "privacy"):
        assert section in ids


def test_in_page_links_point_at_real_sections():
    links = _parse()
    assert links.anchors
    assert set(links.anchors) <= links.ids


def test_local_files_the_page_uses_are_in_the_folder():
    # Caddy serves only this folder; a missing file would be a 404 on the live page.
    links = _parse()
    assert links.local
    for name in links.local:
        assert (SITE / name).is_file(), name


def test_page_loads_nothing_from_other_sites():
    # The privacy section says the server keeps no access log; third-party fonts or scripts
    # would hand visitors' addresses to someone else.
    text = PAGE.read_text(encoding="utf-8")
    assert _parse().scripts == []
    assert not re.search(r'(src|href)="https?://[^"]+\.(js|css|woff2?)', text)
    assert "@import" not in text


def test_page_does_not_point_at_the_private_repository():
    # The code repository is private until the CBT; the page offers e-mail instead.
    text = PAGE.read_text(encoding="utf-8").lower()
    assert "github.com" not in text
    assert "git clone" not in text


def test_server_pulls_this_folder():
    # The server's site-pull.sh fetches exactly relay/site/ from main; renaming the folder
    # without updating the script would silently stop homepage updates.
    sync = SITE.parent / "site-sync"
    script = (sync / "site-pull.sh").read_text(encoding="utf-8")
    assert "sparse-checkout set relay/site" in script
    assert "FETCH_HEAD:relay/site" in script
    assert "User=site" in (sync / "site-pull.service").read_text(encoding="utf-8")
