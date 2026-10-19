"""The Vercel preview must publish only self-contained static UI files."""

import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "web-mockup"


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs["href"])


def test_vercel_publishes_only_static_public_directory():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["framework"] is None
    assert config["buildCommand"] == ""
    assert config["outputDirectory"] == "public"
    public = ROOT / config["outputDirectory"]
    assert (public / "index.html").is_file()
    assert not list(public.rglob("*.py"))
    assert not list(public.rglob(".env*"))


def test_entry_page_assets_exist_without_temporary_figma_urls():
    public = ROOT / "public"
    parser = AssetParser()
    parser.feed((public / "index.html").read_text(encoding="utf-8"))
    assert len(parser.assets) == 2
    for asset in parser.assets:
        path = (public / asset).resolve()
        assert public.resolve() in path.parents
        assert path.stat().st_size > 0
    for path in public.iterdir():
        content = path.read_text(encoding="utf-8")
        assert "figma.com/api/mcp/asset" not in content
        assert "OPENROUTER_API_KEY" not in content
    assert (public / "model.js").stat().st_size > 0
