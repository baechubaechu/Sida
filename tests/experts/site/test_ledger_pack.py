"""건축물대장 packs from the 건축HUB bulk 표제부 file (ledger_pack, scripts/build_ledger_pack.py)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sida.experts.site import context3d, datago, ledger_pack
from tests.experts.site.test_context3d import fake_vworld_layers, plan_for_site

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
SAMPLE = FIXTURES / "ledger" / "mart_djy_03.txt"  # two real lines of the 2026-09 file (군포 금정동 689-14, 종로 세종로 106)
PNU_GUNPO = "4141010500106890014"


def bulk_zip(tmp_path: Path, name="국토교통부_건축물대장_표제부+(2026년+09월).zip", extra=()) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(ledger_pack.MEMBER, SAMPLE.read_text(encoding="utf-8") + "".join(v + "\n" for v in extra))
    return path


def line_for(pnu: str, building_area: float, height: float, floors: int) -> str:
    """The 종로 sample line moved to another lot, with another 건축면적, height and floors."""
    values = SAMPLE.read_text(encoding="utf-8").splitlines()[1].split("|")
    col = ledger_pack.COLUMNS
    values[col["sigungu"]], values[col["bjdong"]] = pnu[:5], pnu[5:10]
    values[col["bun"]], values[col["ji"]] = pnu[11:15], pnu[15:19]
    values[col["building_area_m2"]], values[col["height_m"]] = str(building_area), str(height)
    values[col["floors_above"]] = str(floors)
    return "|".join(values)


def test_a_bulk_line_reads_as_the_data_go_kr_reply_for_the_same_building(tmp_path):
    reply = json.loads((FIXTURES / "datago" / "brtitle_689_14.json").read_text(encoding="utf-8"))
    item = reply["response"]["body"]["items"]["item"]
    item = item[0] if isinstance(item, list) else item
    out = tmp_path / f"t{ledger_pack.SUFFIX}"
    assert ledger_pack.build(bulk_zip(tmp_path), out, ("41",), log=lambda _m: None) == 1  # 종로 left out
    rows, meta = ledger_pack.lookup([PNU_GUNPO, "4141010500106890099"], tmp_path)
    assert rows[PNU_GUNPO] == [datago._building(item)]
    assert rows["4141010500106890099"] == []  # covered, nothing registered
    assert meta["month"] == "2026-09" and meta["prefixes"] == "41"
    rows, meta = ledger_pack.lookup(["1111011900101060000"], tmp_path)  # Seoul: not in this pack
    assert rows == {} and meta is None


def test_pnu_of_a_line():
    values = SAMPLE.read_text(encoding="utf-8").splitlines()[1].split("|")
    assert ledger_pack.pnu_of(values) == "1111011900101060000"
    values[ledger_pack.COLUMNS["plat_gb"]] = "1"
    assert ledger_pack.pnu_of(values)[10] == "2"  # 산
    values[ledger_pack.COLUMNS["plat_gb"]] = "2"
    assert ledger_pack.pnu_of(values) is None  # 블록: no PNU
    assert ledger_pack.month_of("표제부 (2026년 09월).zip") == "2026-09" and ledger_pack.month_of("x.zip") == ""


def test_the_surroundings_read_the_pack_and_ask_only_next_to_the_site(tmp_path, monkeypatch):
    fake_vworld_layers(monkeypatch)
    monkeypatch.setattr(context3d, "LIVE_NEAR", 20.0)  # the site's own parcel only: its neighbours lie 45 m out
    asked = []
    monkeypatch.setattr(context3d.datago, "buildings", lambda pnu: asked.append(pnu) or [])
    plan = plan_for_site()
    first = context3d.build(plan, 200, folder=tmp_path, use_cache=False)
    every = set(asked)
    assert every and first["ledger_source"] is None  # no pack: every parcel asked
    # a pack covering these parcels' 시군구: only the parcels next to the site are asked now
    prefix = sorted(every)[0][:5]
    extra = [line_for("1111010100100020000", 400.0, 33.3, 9)]  # the 대장 of the building 60 m east
    ledger_pack.build(bulk_zip(tmp_path, extra=extra), tmp_path / f"t{ledger_pack.SUFFIX}", (prefix,), log=lambda _m: None)
    context3d._ledger_cache.clear()
    asked.clear()
    out = context3d.build(plan, 200, folder=tmp_path, use_cache=False)
    assert out["ledger_source"]["month"] == "2026-09" and out["ledger_source"]["from_pack"] == len(every) - 1
    assert asked == ["1111010100100010000"]  # the site's parcel, asked live
    east = next(b for b in out["buildings"] if b["height"] == 33.3)
    assert east["height_source"] == "ledger" and east["floors"] == 9
