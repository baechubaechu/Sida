# 라이노 API (라이노 플러그인 ↔ Sida)

라이노 플러그인(`rhino-plugin/`, 아직 만드는 중)이 쓰는 JSON API입니다. 플러그인은 운반과 캡처만 합니다: 라이노가 잰 값(부피, 바닥 외곽선, 층별 면적)과 뷰 캡처를 **스냅샷**으로 보내고, 해석과 수치(연면적·건축면적·건폐율·용적률, 의미별 합계)는 Sida가 규칙으로 계산합니다. 수치를 추정하지 않습니다: 라이노가 재지 못한 개체(닫히지 않은 도형)는 "잴 수 없음"으로 남고, 대지 면적이 없으면 건폐율·용적률을 내지 않습니다(제도판 매스안과 같은 규칙). 로직은 `sida/experts/rhino/snapshot.py`, 경로는 `sida/experts/rhino/api.py`입니다.

플러그인은 같은 PC의 Sida(`http://127.0.0.1:8765`)를 부릅니다. 다른 주소에서 온 요청은 서버가 막습니다(`webapp.py`).

## 스냅샷

가장 새 스냅샷이 제도판의 "라이노 작업" 종이(`kind: rhino`, id `rhino`)가 됩니다. 설계자 자신의 작업이라 AI 섹션이 아니라 제도판에 바로 놓이고, 다시 보내면 같은 종이가 자리를 지킨 채 내용만 바뀝니다. 종이는 `title`(파일 이름), `snapshot`(id), `file`, `taken_at`, `objects`(개체 수), `layers`(`[{path, meaning}]`), `figures`(아래 수치와 `lines`)를 가지고, 옮기기만 됩니다. 전문가는 가장 새 스냅샷의 수치와 레이어 의미만 프롬프트로 받고(`hooks.py`), 도형은 받지 않습니다.

스냅샷은 프로젝트 폴더 `rhino/snapshots/<id>/`에 `snapshot.json`과 `views/*.png`로 저장되고, 새 것 30개만 남습니다. id는 `YYYYMMDD-HHMMSS-NNNN`(보낸 시각, 같은 초 안의 순번)입니다.

스냅샷 v1(`schema: 1`), 단위 m, 좌표는 내보내기(`docs/board-api.md`의 내보내기)와 같은 틀(원점 대지 가운데, x 동쪽, y 북쪽, z 위):

```json
{"schema": 1,
 "rhino": {"version": "8.12", "file": "studio.3dm", "units": "m"},
 "origin": {"lon": 126.97, "lat": 37.56, "matches_project": true},
 "layers": [{"path": "Program::Housing", "meaning": "housing", "color": "#c86432", "floor_height": 3.0}],
 "objects": [{"id": "<라이노 guid>", "sida_id": "mass-a:0", "layer": "Program::Housing", "name": "동 A",
              "volume": 2160.0, "height": 12.0, "base": 0.0, "footprint": [[0, 0], [20, 0], [20, 9], [0, 9]],
              "floors": [{"z": 0.0, "area": 180.0}, {"z": 3.0, "area": 180.0}],
              "mesh": {"v": [[0, 0, 0]], "f": [[0, 1, 2]]}}],
 "views": [{"kind": "plan", "file": "plan.png"}, {"kind": "axo", "file": "axo.png"}]}
```

- `layers[].meaning`: 설계자가 플러그인 패널에서 레이어마다 고른 의미. `housing`(주거) `commercial`(상업) `office`(업무) `culture`(문화·교육) `core`(코어·설비) `other`(기타 용도)는 건물로 세고, `outdoor`(외부 공간) `surroundings`(주변 건물) `site`(대지 경계) `ignore`(제외)는 세지 않습니다. 모르는 값은 의미 없음으로 둡니다. 의미 없는 레이어의 개체는 수치에서 빠지고 개수만 알려 줍니다.
- `objects[]`: 보이는 입체(폴리서피스, 돌출, 서피스, SubD, 메시)마다. 건물 의미 레이어의 개체는 다 재고, 그 밖의 의미(주변 건물 등) 레이어의 개체는 `base`·`height`만, 의미 없는 레이어의 개체는 이름만 보냅니다(몇 개가 빠졌는지 알리려고). `sida_id`는 Sida에서 가져온 개체면 그 id(3dm 내보내기의 사용자 문자열 `sida.id`, 예 `mass-a:0`, 가져온 뒤 설계자가 고친 개체는 `sida.from`), 아니면 `null`. `volume`·`height`·`base`(가장 낮은 점의 z)·`footprint`·`floors`는 라이노가 잰 값이고 못 재면 `null`/빈 목록.
- `footprint`는 고리 하나(`[[x, y], …]`)이거나 고리 여러 개(`[[[x, y], …], …]`, 50개까지)입니다. 다른 고리 안에 있는 고리는 뚫린 곳(중정)이고 떨어져 있는 고리는 또 한 덩어리입니다(짝홀 규칙). 저장할 때는 늘 고리 목록입니다. `floors`는 개체 바닥에서 레이어 층고마다 자른 단면의 높이(`z`)와 넓이(중정 제외)입니다. `mesh`는 화면용으로 선택이며 꼭짓점 20,000개를 넘으면 버리고 `mesh_dropped: true`가 남습니다(수치는 그대로). 개체 2,000개, 층 200개, 외곽선 점 500개까지.
- `views[]`: `kind`는 `plan` `axo` `persp` `elevation` `section` `eye`, `file`은 `plan.png`처럼 소문자·숫자 이름(8장, 각 10MB까지). 올릴 때 같은 이름의 PNG 파일을 함께 보냅니다.

## 수치 (`figures`)

```json
{"floor_area_m2": 900.0, "footprint_m2": 320.0, "volume_m3": null, "height_m": 12.0,
 "coverage_pct": 32.0, "far_pct": 90.0, "site_area_m2": 1000.0,
 "objects": 3, "unmeasured": ["c1"], "no_floor_height": [], "unassigned": 1,
 "by_meaning": [{"meaning": "housing", "word": "주거", "floor_area_m2": 720.0, "footprint_m2": 230.0, "objects": 2}],
 "lines": ["연면적 900.0㎡ (주거 720.0, 상업 180.0)", "건축면적 320.0㎡", "건폐율 32.0% · 용적률 90.0%", "…"],
 "limits": [{"zone": "제2종일반주거지역", "bcr_max": 60, "far_min": 100, "far_max": 250, "ordinance_bcr": 60, "ordinance_far": null}]}
```

- 연면적은 건물 의미 개체의 층별 면적 합, 건축면적은 바닥 외곽선을 겹치는 부분 한 번만 세고 중정은 빼고 합친 넓이입니다. 부피는 한 개체라도 못 쟀으면 `null`. 건폐율·용적률은 대지 사실의 면적으로만 계산합니다.
- 층으로 세는 규칙: 플러그인은 바닥에서 층고마다 자르므로 층고의 배수보다 조금 높은 매스(파라펫)는 한 번 더 잘립니다. 그 높이 위로 층고의 절반 이상 입체가 있어야 층으로 셉니다(`base`·`height`·레이어 층고를 다 알 때).
- 최고 높이는 건물 의미 개체의 `base`를 다 알면 가장 낮은 바닥에서 가장 높은 꼭대기까지이고(저층부 위의 탑은 합친 높이), 하나라도 모르면 가장 높은 개체 하나의 높이입니다.
- `unmeasured`는 잴 수 없었던 개체(닫히지 않은 도형), `no_floor_height`는 층고를 정하지 않은 레이어의 개체(건축면적에는 들어가고 연면적에서는 빠짐), `unassigned`는 의미 없는 레이어의 개체 수입니다.
- `limits`는 대지 사실에 있는 그대로입니다: 용도지역별 법정 상한·범위와, 조례 조문에서 규칙으로 읽힌 값(못 읽었으면 `null`). 계산하지 않습니다.

## API

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/rhino/hello` | | `{ok, app, schema, meanings: [{code, word, built}], views}`. 플러그인이 Sida가 켜져 있는지, 어떤 스냅샷 형식을 읽는지 확인 |
| `POST /api/projects/{name}/rhino/snapshots` | `multipart/form-data`: `snapshot`(스냅샷 JSON 문자열), `views`(선언한 뷰마다 PNG 파일, 파일 이름이 `views[].file`) | `201 {snapshot, figures, paper, rev}`. `snapshot`은 요약(`id, taken_at, file, version, objects, layers, views, origin`). 형식이 틀리면 `400`(이유 포함), 선언한 뷰 파일이 빠져도 `400` |
| `GET /api/projects/{name}/rhino/snapshots` | | `{snapshots: [요약…]}` 새 것부터 |
| `GET /api/projects/{name}/rhino/snapshots/{id}` | | `{snapshot, figures}` 스냅샷 전체(메시 포함) |
| `GET /api/projects/{name}/rhino/snapshots/{id}/views/{file}` | | 그 뷰의 PNG. 없으면 `404` |
| `DELETE /api/projects/{name}/rhino/snapshots/{id}` | | `{ok}` |
| `POST /api/projects/{name}/rhino/figures` | 스냅샷 JSON 본문(뷰·메시는 비워도 됨) | `{figures}`. 저장하지 않음. 플러그인의 실시간 수치 패널이 모델링 중에 부름 |

## 3dm 내보내기와의 연결

제도판 내보내기(`GET /api/projects/{name}/board/export?format=3dm`)의 개체에는 사용자 문자열 `sida.id`(매스 동은 `<종이 id>:<동 번호>`, 필지는 `site:<pnu>`, 기준점은 `origin`)와 `sida.kind`가 붙고, 기준점에는 `sida.project`(프로젝트 폴더 이름)와 `sida.origin`(`경도,위도`)도 붙습니다. 자기 id가 없는 것(주변 건물, 지형, 도로)은 레이어 안의 순번으로 `context:<레이어 이름>:<번호>`와 `sida.kind` `context`가 붙습니다. 플러그인은 이것으로 Sida에서 온 개체와 설계자가 만든 개체를 가르고, 다시 가져올 때 Sida에서 온 개체만 바꾸며, 보낼 때 `sida_id`를 채웁니다. 가져올 때 개체마다 놓인 범위를 `sida.stamp`로 적어 두었다가, 다시 가져올 때 범위가 달라진 개체(설계자가 옮기거나 고친 것)는 지우지 않고 설계자의 개체로 남깁니다(`sida.id`가 `sida.from`으로 바뀜). Sida 자신의 레이어에는 의미도 붙여 둡니다(주변은 `surroundings`, 대지 경계는 `site`, 기준점·트레이싱은 `ignore`, 매스는 설계자가 정함). DXF에는 id가 없습니다.
