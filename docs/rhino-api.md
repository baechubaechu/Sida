# 라이노 API (라이노 플러그인 ↔ Sida)

라이노 플러그인(`rhino-plugin/`)이 쓰는 JSON API입니다. 플러그인은 운반과 캡처만 합니다: 라이노가 잰 값(부피, 바닥 외곽선, 층별 면적)과 뷰 캡처를 **스냅샷**으로 보내고, 해석과 수치(연면적·건축면적·건폐율·용적률, 의미별 합계)는 Sida가 규칙으로 계산합니다. 수치를 추정하지 않습니다: 라이노가 재지 못한 개체(닫히지 않은 도형)는 "잴 수 없음"으로 남고, 대지 면적이 없으면 건폐율·용적률을 내지 않습니다(제도판 매스안과 같은 규칙). 로직은 `sida/experts/rhino/snapshot.py`, 경로는 `sida/experts/rhino/api.py`입니다.

플러그인은 같은 PC의 Sida(`http://127.0.0.1:8765`)를 부릅니다. 다른 주소에서 온 요청은 서버가 막습니다(`webapp.py`).

## 스냅샷

가장 새 스냅샷이 제도판의 "라이노 작업" 종이(`kind: rhino`, id `rhino`)가 됩니다. 설계자 자신의 작업이라 AI 섹션이 아니라 제도판에 바로 놓이고, 다시 보내면 같은 종이가 자리를 지킨 채 내용만 바뀝니다. 종이는 `title`(파일 이름), `snapshot`(id), `file`, `taken_at`, `objects`(개체 수), `layers`(`[{path, meaning}]`), `views`(`[{kind, file}]`), `diagrams`(그릴 수 있는 다이어그램 `[{kind, title}]`), `figures`(아래 수치와 `lines`)를 가지고, 옮기기만 됩니다. 화면은 종이에 가장 새 캡처(투시 먼저)와 수치 줄을 보여 주고, 속성 패널에서는 다이어그램을 그림으로 보여 주며 SVG·PNG로 내려받게 합니다(PNG는 브라우저가 SVG를 2배 크기로 그려 만듭니다). 레이어는 `라이노`입니다. 전문가는 가장 새 스냅샷의 수치와 레이어 의미만 프롬프트로 받고(`hooks.py`), 도형은 받지 않습니다.

스냅샷은 프로젝트 폴더 `rhino/snapshots/<id>/`에 `snapshot.json`과 `views/*.png`로 저장되고, 새 것 30개만 남습니다. id는 `YYYYMMDD-HHMMSS-NNNN`(보낸 시각, 같은 초 안의 순번)입니다.

스냅샷 v1(`schema: 1`), 단위 m, 좌표는 내보내기(`docs/board-api.md`의 내보내기)와 같은 틀(원점 대지 가운데, x 동쪽, y 북쪽, z 위):

```json
{"schema": 1,
 "rhino": {"version": "8.12", "file": "studio.3dm", "units": "m"},
 "origin": {"lon": 126.97, "lat": 37.56, "matches_project": true},
 "layers": [{"path": "Program::Housing", "meaning": "housing", "color": "#c86432", "floor_height": 3.0}],
 "objects": [{"id": "<라이노 guid>", "sida_id": "mass-a:0", "layer": "Program::Housing", "name": "동 A",
              "volume": 2160.0, "height": 12.0, "base": 0.0, "footprint": [[0, 0], [20, 0], [20, 9], [0, 9]],
              "floors": [{"z": 0.0, "area": 180.0, "outline": [[[0, 0], [20, 0], [20, 9], [0, 9]]]}, {"z": 3.0, "area": 180.0}],
              "mesh": {"v": [[0, 0, 0]], "f": [[0, 1, 2]]}}],
 "views": [{"kind": "plan", "file": "plan.png"}, {"kind": "axo", "file": "axo.png"}]}
```

- `layers[].meaning`: 설계자가 플러그인 패널에서 레이어마다 고른 의미. `housing`(주거) `commercial`(상업) `office`(업무) `culture`(문화·교육) `core`(코어·설비) `other`(기타 용도)는 건물로 세고, `outdoor`(외부 공간) `surroundings`(주변 건물) `site`(대지 경계) `ignore`(제외)는 세지 않습니다. 모르는 값은 의미 없음으로 둡니다. 의미 없는 레이어의 개체는 수치에서 빠지고 개수만 알려 줍니다.
- `objects[]`: 보이는 입체(폴리서피스, 돌출, 서피스, SubD, 메시)마다. 건물 의미 레이어의 개체는 다 재고, 그 밖의 의미(주변 건물 등) 레이어의 개체는 `base`·`height`만, 의미 없는 레이어의 개체는 이름만 보냅니다(몇 개가 빠졌는지 알리려고). `sida_id`는 Sida에서 가져온 개체면 그 id(3dm 내보내기의 사용자 문자열 `sida.id`, 예 `mass-a:0`, 가져온 뒤 설계자가 고친 개체는 `sida.from`), 아니면 `null`. `volume`·`height`·`base`(가장 낮은 점의 z)·`footprint`·`floors`는 라이노가 잰 값이고 못 재면 `null`/빈 목록.
- `footprint`는 고리 하나(`[[x, y], …]`)이거나 고리 여러 개(`[[[x, y], …], …]`, 50개까지)입니다. 다른 고리 안에 있는 고리는 뚫린 곳(중정)이고 떨어져 있는 고리는 또 한 덩어리입니다(짝홀 규칙). 저장할 때는 늘 고리 목록입니다. `floors`는 개체 바닥에서 레이어 층고마다 자른 단면의 높이(`z`)와 넓이(중정 제외)입니다. `outline`(선택)은 그 단면의 외곽선(고리 목록, `footprint`와 같은 규칙)으로, 플러그인이 보낼 때만 넣고 다이어그램이 층마다 다른 모양을 그리는 데 씁니다. 없으면 다이어그램은 그 개체의 `footprint`를 층마다 씁니다. `mesh`는 화면용으로 선택이며 꼭짓점 20,000개를 넘으면 버리고 `mesh_dropped: true`가 남습니다(수치는 그대로). 개체 20,000개, 층 200개, 외곽선 점 500개까지.
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
| `GET /api/rhino/hello` | | `{ok, app, schema, meanings: [{code, word, built}], views, diagrams: [{kind, title, view}]}`. 플러그인이 Sida가 켜져 있는지, 어떤 스냅샷 형식을 읽는지 확인 |
| `POST /api/projects/{name}/rhino/snapshots` | `multipart/form-data`: `snapshot`(스냅샷 JSON을 담은 파일 부분, 예: `snapshot.json`, 64MB까지. 메시가 들어가면 몇 MB가 되어 폼 필드로는 1MB에서 막히므로 파일로 보냅니다), `views`(선언한 뷰마다 PNG 파일, 파일 이름이 `views[].file`) | `201 {snapshot, figures, paper, rev}`. `snapshot`은 요약(`id, taken_at, file, version, objects, layers, views, origin`). 형식이 틀리면 `400`(이유 포함), 선언한 뷰 파일이 빠져도 `400` |
| `GET /api/projects/{name}/rhino/snapshots` | | `{snapshots: [요약…]}` 새 것부터 |
| `GET /api/projects/{name}/rhino/snapshots/{id}` | | `{snapshot, figures}` 스냅샷 전체(메시 포함) |
| `GET /api/projects/{name}/rhino/snapshots/{id}/views/{file}` | | 그 뷰의 PNG. 없으면 `404` |
| `DELETE /api/projects/{name}/rhino/snapshots/{id}` | | `{ok}` |
| `GET /api/projects/{name}/rhino/snapshots/{id}/diagrams` | | `{diagrams: [{kind, title, view, ready, reason}]}`. 이 스냅샷을 그릴 수 있는 종류와, 못 그리면 그 이유(한국어) |
| `GET /api/projects/{name}/rhino/snapshots/{id}/diagrams/{kind}?format=json\|svg` | | `json`(기본)은 `{drawing}`(아래 그리기 지시), `svg`는 같은 그림의 SVG 파일. 모르는 종류나 그릴 수 없는 스냅샷은 `400`(이유 포함) |
| `POST /api/projects/{name}/rhino/figures` | 스냅샷 JSON 본문(뷰·메시는 비워도 됨) | `{figures}`. 저장하지 않음. 플러그인의 실시간 수치 패널이 모델링 중에 부름 |

## 다이어그램

다이어그램은 저장된 스냅샷에서 **규칙으로** 그립니다(`sida/experts/rhino/diagrams.py`). LLM이 그리지 않고, 수치를 추정하지 않습니다: 넓이는 라이노가 잰 값, 비율과 한도는 위 수치에 있는 값이며, 그리지 못한 것은 `notes`에 적습니다. 요청할 때마다 스냅샷과 지금의 대지 사실로 새로 그리므로 따로 저장하지 않습니다. 주변 건물은 파일에 쓸 수 있는 자료(수치지형도, `board_surroundings`)만 쓰고 브이월드 외곽선은 쓰지 않습니다.

Sida는 무엇을 어디에 그릴지만 정한 **그리기 지시**를 내고, 그리는 쪽은 따르기만 합니다. 플러그인은 지시대로 라이노 도형(입체, 해치, 선, 글자)을 만들고, `diagram_svg.py`는 같은 지시를 SVG로 그립니다. 단위 m, 좌표는 스냅샷과 같은 틀입니다.

```json
{"kind": "program", "title": "프로그램 매스", "view": "axo", "bounds": [x0, y0, z0, x1, y1, z1], "notes": ["…"],
 "items": [
  {"type": "slab", "rings": [[[x, y], …]], "z": 0.0, "height": 4.5, "color": "#cf5b5b", "tag": "commercial"},
  {"type": "fill", "rings": [[[x, y], …]], "z": 0.0, "color": "#d5d9de", "light": false, "role": ""},
  {"type": "line", "points": [[x, y, z], …], "closed": true, "bold": true, "dashed": true, "color": "#20262d"},
  {"type": "text", "at": [x, y, z], "text": "+9.0m  616.0㎡", "size": 1.4, "anchor": "start", "upright": true, "role": "", "swatch": null}]}
```

- `slab`은 `z`에서 `height`만큼 올린 판(고리는 짝홀 규칙), `fill`은 평평한 면(`light`는 옅게), `line`은 꺾은선, `text`의 `size`는 글자 높이입니다. `upright` 글자는 x-z 평면에 서 있습니다(남쪽에서 읽음).
- `role`이 있는 글자(`title`, `legend`, `caption`)는 그림의 말입니다. 평면 그림(`view: flat`)은 놓인 자리에 그대로 그리고, 축측 그림(`view: axo`)의 SVG는 그림 둘레의 지면에 따로 놓습니다(범례 줄은 `swatch` 색과 함께). 라이노에서는 모두 놓인 자리에 글자로 만듭니다.
- SVG의 축측은 남서쪽 위에서 본 등각 투영입니다. 평면 그림은 위에서 본 축척 그대로입니다.

| 종류 | 그리는 것 | 그릴 수 없을 때 |
|---|---|---|
| `program` 프로그램 매스 (axo) | 건물 의미 개체를 층마다 의미 색(`snapshot.MEANINGS`의 `color`)으로. 층이 없는 개체(층고 없음)는 한 덩어리로. 범례는 의미별 연면적과 비율 | 건물 의미 입체가 없음 |
| `floors` 층별 분해 (axo) | 같은 층판을 위아래로 벌려, 높이마다 `+9.0m  616.0㎡` | 층고를 정한 레이어가 없음 |
| `stack` 층별 면적 (flat) | 높이마다 의미별 면적 막대 | 층고를 정한 레이어가 없음 |
| `site` 대지 배치도 (flat) | 필지 경계, 건물 바닥, 주변 건물(대지에서 40m까지), 방위, 축척 막대 | 대지도 건물 바닥도 없음 |
| `limits` 법정 수치 비교 (flat) | 건폐율·용적률 막대와 한도(용도지역이 하나일 때만, 조례 값이 읽혔으면 조례, 아니면 법정 상한). 넘으면 넘은 만큼, 모르면 "미확인" | 늘 그릴 수 있음 |

## 실시간 (패널 ↔ 플러그인)

라이노 안 패널은 Sida 화면(`/app/rhino.html`)이고 라이노와 직접 말하지 않습니다. Sida가 가운데에서 전합니다(`sida/experts/rhino/live.py`). 플러그인은 문서가 바뀔 때마다 상태를 알리고 0.5초마다 할 일을 물어 가며, 패널은 1초마다 상태를 읽습니다. 이 상태는 메모리에만 있고 저장하지 않습니다. Sida를 다시 켜면 플러그인이 `known: false`를 보고 다시 알립니다. 붙잡아 두는 요청(long-poll)을 쓰지 않는 것은 Sida를 끌 때 서버가 바로 멈추게 하기 위해서입니다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `POST /api/rhino/live` | 플러그인: `{doc, file, units, project, autosync, busy, snapshot, notice}`. `busy`는 지금 하는 중인 일(`""`, `pull`, `push`, `draw`). `doc`은 플러그인이 정한 문서 id(라이노 하나에 하나, `rhino-<프로세스 번호>`: 그 라이노의 지금 문서), `snapshot`은 뷰·메시 없는 스냅샷(없으면 `null`), `notice`는 방금 한 일의 결과 `{text, ok}`(선택) | `{rev}`. 패널에 보이는 것이 바뀌었을 때만 `rev`가 오릅니다 |
| `GET /api/rhino/live?doc=` | 패널. `doc`이 없으면 가장 최근에 물어 온 문서 | `{connected, rev, state}`. `state`는 `{doc, file, units, project, project_known, autosync, busy, rhino, layers: [{path, meaning, color, floor_height, objects}], objects, figures, notice: {text, ok, at, n}}`. 도형은 담지 않습니다. 플러그인이 5초 넘게 묻지 않으면 `connected: false` |
| `POST /api/rhino/commands` | 패널: `{doc, type, …}`. `type`은 `pull`, `push`, `set_project`(`project`), `set_layer`(`path`, `meaning`, `floor_height` m 또는 `null`), `set_autosync`(`on`), `report`, `draw`(`kinds`: 다이어그램 종류 목록. 플러그인이 먼저 보내고(`push`) 그 스냅샷의 그리기 지시를 받아 문서에 그립니다) | `{id}`. 모르는 `type`·의미, 연결된 적 없는 `doc`은 `400` |
| `GET /api/rhino/commands?doc=&after=` | 플러그인. `after`는 끝낸 마지막 명령 id | `{known, commands: [{id, type, …}]}`. 묻는 것이 곧 연결 신호입니다 |

## 3dm 내보내기와의 연결

제도판 내보내기(`GET /api/projects/{name}/board/export?format=3dm`)의 개체에는 사용자 문자열 `sida.id`(매스 동은 `<종이 id>:<동 번호>`, 필지는 `site:<pnu>`, 기준점은 `origin`)와 `sida.kind`가 붙고, 기준점에는 `sida.project`(프로젝트 폴더 이름)와 `sida.origin`(`경도,위도`)도 붙습니다. 자기 id가 없는 것(주변 건물, 지형, 도로)은 레이어 안의 순번으로 `context:<레이어 이름>:<번호>`와 `sida.kind` `context`가 붙습니다. 플러그인은 이것으로 Sida에서 온 개체와 설계자가 만든 개체를 가르고, 다시 가져올 때 Sida에서 온 개체만 바꾸며, 보낼 때 `sida_id`를 채웁니다. 가져올 때 개체마다 놓인 범위를 `sida.stamp`로 적어 두었다가, 다시 가져올 때 범위가 달라진 개체(설계자가 옮기거나 고친 것)는 지우지 않고 설계자의 개체로 남깁니다(`sida.id`가 `sida.from`으로 바뀜). Sida 자신의 레이어에는 의미도 붙여 둡니다(주변은 `surroundings`, 대지 경계는 `site`, 기준점·트레이싱은 `ignore`, 매스는 설계자가 정함). DXF에는 id가 없습니다.
