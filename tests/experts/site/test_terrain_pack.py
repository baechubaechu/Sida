import json
import sqlite3
from contextlib import closing

from sida.experts.site import terrain_pack


def test_contour_points_are_kept_as_small_bytes_and_read_back_to_the_centimetre(tmp_path):
    line = [[127.0 + i * 1.3e-5, 37.5 + (i % 7) * 2.1e-6] for i in range(500)]
    conn = terrain_pack.create(tmp_path / f"t{terrain_pack.SUFFIX}", {"kind": "contours"})
    terrain_pack.add_contour(conn, 35.0, line)
    conn.commit()
    stored, = conn.execute("SELECT points FROM contours").fetchone()
    conn.close()
    assert isinstance(stored, bytes)
    text = json.dumps([[round(x, 7), round(y, 7)] for x, y in line], separators=(",", ":"))
    assert len(stored) * 4 < len(text)  # a quarter of the text form at most
    found, = terrain_pack.query(126.9, 37.4, 127.1, 37.6, folder=tmp_path)["contours"]
    assert found["elev"] == 35.0
    assert found["points"] == [[round(x, 7), round(y, 7)] for x, y in line]


def test_a_pack_made_before_keeps_reading_its_text_points(tmp_path):
    # FORMAT 1 packs (서울, made before) hold the points as JSON text
    path = tmp_path / f"old{terrain_pack.SUFFIX}"
    terrain_pack.create(path, {"kind": "contours"}).close()
    with closing(sqlite3.connect(path)) as conn:
        cur = conn.execute("INSERT INTO contours (elev, points) VALUES (?, ?)", (20.0, "[[127.0,37.5],[127.001,37.5]]"))
        conn.execute("INSERT INTO contours_box VALUES (?, ?, ?, ?, ?)", (cur.lastrowid, 127.0, 127.001, 37.5, 37.5))
        conn.commit()
    assert terrain_pack.query(126.9, 37.4, 127.1, 37.6, folder=tmp_path)["contours"] == [
        {"elev": 20.0, "points": [[127.0, 37.5], [127.001, 37.5]]}]
