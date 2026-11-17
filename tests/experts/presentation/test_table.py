"""The drafting table as slide material: a deck without Rhino (the scheme, the sections, the photos)."""

from __future__ import annotations

import io
import zipfile

import pytest

from sida import board
from sida.experts.presentation import deck, slides, table
from sida.experts.rhino import diagrams
from sida.experts.rhino import snapshot as snap
from tests.experts.presentation.test_slides import (  # noqa: F401  (project is a fixture)
    document,
    project,
    send,
    tiny_png,
)

PODIUM_AND_TOWER = [
    {"u": 0, "v": 0, "w": 40, "d": 30, "floors": 2},
    {"u": 5, "v": 0, "w": 15, "d": 15, "floors": 10},  # drawn through the podium
]
JPEG = bytes.fromhex(  # a real 1 x 1 JPEG
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720"
    "222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f00000105010101010101000000000000000001020304"
    "05060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f024336272"
    "82090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a929394"
    "95969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda"
    "0008010100003f00fbfcffd9")


@pytest.fixture(autouse=True)
def no_font_of_this_machine(monkeypatch):
    monkeypatch.setattr(deck, "font_files", lambda: [])


def lay(project_dir, scheme_id="mass-a", title="A안", blocks=PODIUM_AND_TOWER) -> dict:  # noqa: F811
    return board.add_paper(project_dir, {"kind": "mass", "id": scheme_id, "title": title, "floor_height": 4.0, "blocks": blocks})["paper"]


def test_a_scheme_is_read_as_a_model_whose_figures_agree_with_the_tables_own(project):  # noqa: F811
    scheme = lay(project)
    model = table.scheme_model(scheme, None)
    # two bands of storeys: the podium with the tower's foot in it, then the tower alone
    assert [(o["base"], o["height"], len(o["floors"]), o["floors"][0]["area"]) for o in model["objects"]] == [(0.0, 8.0, 2, 1200.0), (8.0, 32.0, 8, 225.0)]
    fig = snap.figures(model, 3600.0)
    own = board.mass_figures(scheme, 3600.0)
    assert (fig["footprint_m2"], fig["floor_area_m2"], fig["height_m"]) == (own["footprint_m2"], own["floor_area_m2"], own["height_m"]) == (1200.0, 4200.0, 40.0)
    assert (fig["coverage_pct"], fig["far_pct"]) == (own["coverage_pct"], own["far_pct"])
    assert fig["unmeasured"] == [] and fig["no_floor_height"] == []


def test_without_rhino_the_figures_and_diagrams_come_from_the_scheme_on_the_table(project):  # noqa: F811
    lay(project)
    lay(project, "mass-b", "B안", [{"u": 0, "v": 0, "w": 20, "d": 20, "floors": 3}])
    mats = slides.materials(project)
    assert mats["source"] == "table" and mats["snapshot"] is None and mats["scheme"] == {"id": "mass-a", "name": "A안"}
    assert mats["schemes"] == [{"id": "mass-a", "name": "A안"}, {"id": "mass-b", "name": "B안"}]
    items = mats["items"]
    assert [key for key, item in items.items() if item["ready"]] == ["diagram:floors", "diagram:stack", "diagram:site", "diagram:limits", "figures"]
    assert items["diagram:program"]["why"] == table.NO_USES
    rows = dict(slides.figure_rows(mats["figures"], mats["limits"]))
    assert rows["연면적"] == "4,200.0㎡" and rows["건폐율"] == "33.3% (조례 60%)" and "  기타 용도" not in rows
    other = slides.materials(project, "mass-b")
    assert other["scheme"]["name"] == "B안" and other["figures"]["floor_area_m2"] == 1200.0
    with pytest.raises(ValueError, match="not a massing scheme on the table"):
        slides.materials(project, "mass-x")

    made = slides.deck(project, None, mats)
    assert made["model"] == {"source": "table", "scheme": {"id": "mass-a", "name": "A안"}} and made["snapshot"] is None and made["notes"] == []
    assert [s["figure"]["key"] for s in made["slides"][1:]] == ["figures", "diagram:floors", "diagram:stack", "diagram:site", "diagram:limits"]

    floors = deck.diagram_of("floors", mats, project)
    assert not [i for i in floors["items"] if i.get("role") == "legend"]  # a scheme has no uses to name
    assert {i["color"] for i in floors["items"] if i["type"] == "slab"} == {diagrams.PLAIN}
    assert len([i for i in floors["items"] if i["type"] == "slab"]) == 10
    with pytest.raises(ValueError, match="용도가 없어"):
        deck.diagram_of("program", mats, project)

    text = slides.prompt_text(mats)
    assert "massing scheme on the drafting table" in text and f"- `diagram:program`: 프로그램 매스 (cannot be made now: {table.NO_USES})" in text

    send(project)  # once Rhino sends a model, the deck is of that model
    assert slides.materials(project)["source"] == "rhino"


def test_sections_and_photos_on_the_table_are_materials_whatever_the_model(project):  # noqa: F811
    lay(project)
    board.add_paper(project, {"kind": "section", "id": "sec-a", "title": "A", "line": [[-30, 0], [30, 0]]})
    scene = board.add_photo(project, tiny_png(16, 9), {"title": "눈높이 장면"})["paper"]
    photo = board.add_photo(project, JPEG, {"title": "대지 사진"})["paper"]
    gif = board.add_photo(project, b"GIF89a" + bytes(40), {"title": "움직이는 그림"})["paper"]
    mats = slides.materials(project)
    extra = {key: item for key, item in mats["items"].items() if item["kind"] in ("section", "photo")}
    assert list(extra) == ["section:sec-a", f"photo:{scene['id']}", f"photo:{photo['id']}", f"photo:{gif['id']}"]
    assert extra["section:sec-a"]["title"] == "단면 A–A′" and extra[f"photo:{scene['id']}"]["title"] == "눈높이 장면"
    assert extra[f"photo:{gif['id']}"]["ready"] is False and extra[f"photo:{gif['id']}"]["why"] == table.NOT_A_PICTURE

    by_rule = slides.deck(project, None, mats)
    assert [s["figure"]["key"] for s in by_rule["slides"][-3:]] == ["section:sec-a", f"photo:{scene['id']}", f"photo:{photo['id']}"]
    assert by_rule["slides"][-3]["figure"]["paper"] == "sec-a"

    listed = slides.deck(project, document([
        {"title": "단면", "figure": "section:sec-a"}, {"title": "장면", "figure": f"photo:{scene['id']}"},
        {"title": "대지", "figure": f"photo:{photo['id']}"}, {"title": "움직임", "figure": f"photo:{gif['id']}"},
    ]), mats)
    pages = deck.pages(listed, mats, project)
    (drawn,) = [e for e in pages[0]["elements"] if e["type"] == "diagram"]
    shapes = drawn["page"]["shapes"]
    assert [s for s in shapes if s["type"] == "poly" and s["fill"] == "#20262d"]  # the cut scheme, filled
    words = {s["text"] for s in shapes if s["type"] == "text"}
    assert {"A", "A′", "±0", "+8.00", "8.0m 2층"} <= words and not any(w.startswith("단면 A") for w in words)  # the slide has the title
    for page, size in ((pages[1], (16, 9)), (pages[2], (1, 1))):
        (picture,) = [e for e in page["elements"] if e["type"] == "picture"]
        assert picture["w"] / picture["h"] == pytest.approx(size[0] / size[1])
    assert [e["paras"][1] for e in pages[3]["elements"] if e["type"] == "empty"] == [table.NOT_A_PICTURE]

    assert deck.to_pptx(pages, "t").startswith(b"PK") and deck.to_pdf(pages, "t").startswith(b"%PDF-")
    with zipfile.ZipFile(io.BytesIO(deck.bundle(project, listed, mats, pages))) as archive:
        names = set(archive.namelist())
        assert {"단면/단면 A–A′.svg", "사진/눈높이 장면.png", "사진/대지 사진.jpg", "다이어그램/층별 분해.svg", "수치.csv"} <= names
        assert not any(n.startswith("라이노 뷰/") or "움직이는" in n for n in names)

    # with neither a scheme nor Rhino the sections and photos can still be placed
    board.delete_paper(project, "mass-a")
    bare = slides.materials(project)
    assert bare["source"] is None and bare["items"][f"photo:{scene['id']}"]["ready"] and not bare["items"]["figures"]["ready"]
    assert f"- `photo:{scene['id']}`: 눈높이 장면" in slides.prompt_text(bare)
