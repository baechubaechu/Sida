# 대지 조회와 조례 조문 화면 연결

## 대지 조회 API

웹에서 주소로 대지를 조회하는 흐름입니다. 로직은 `sida/experts/site/site_facts.py`(`refresh`, `site_view`)에 있습니다.

| 순서 | 메서드·경로 | 요청 | 응답 |
|---|---|---|---|
| 1. 필지 찾기 | `POST /api/projects/{name}/site/parcels` | `{query: "경기도 군포시 금정동 689"}` | `{query, candidates: [{pnu, address, road_address, building, matched_by}]}` |
| 2. 조회해 저장 | `PUT /api/projects/{name}/site` | `{query, pnus: ["4141…0014", "4141…0015"]}` 또는 `{pnus: [...]}` | 아래 "대지 사실 모양" |
| 3. 다시 읽기 | `GET /api/projects/{name}/site` | 없음 | 같은 모양. 조회 전이면 `available: false` |

- 1번은 아무것도 저장하지 않습니다. 후보가 없으면 `candidates: []`입니다.
- 1번은 지번 주소로 먼저 찾고, 없을 때만 도로명 주소로 찾습니다. `matched_by`가 `"parcel"`이면 지번, `"road"`이면 도로명으로 찾은 것입니다. 시·도와 "시", "동"을 생략하거나 부번을 빼도 찾습니다(`금정동 689` → 689-14, 689-15 …). 오타는 고쳐 주지 않습니다. 결과가 없으면 다시 검색하도록 안내하세요. 건물·장소 이름으로는 찾지 않습니다.
- 2번의 `pnus`는 1번 후보의 `pnu`입니다. 여러 개를 주면 하나의 대지로 합칩니다(순서 유지). `query`는 1번과 같은 값을 보내세요. 서버가 다시 검색해 후보에 있는 필지만 받습니다.
- 아래 "단계별 주소 선택"으로 필지를 고른 경우에는 `query` 없이 `pnus`만 보냅니다. 서버는 다시 검색하지 않고 그 필지 번호를 그대로 조회합니다. 저장되는 `query`는 필지 주소들을 쉼표로 이은 것입니다.
- 2번은 필지마다 브이월드를 두 번, 건축물대장을 한 번 부르고, 건축제한 근거 조문과 조례도 조회하므로 몇 초 걸립니다. 진행 표시를 보여 주세요.
- 2번이 끝나면 조례도 함께 저장됩니다. 조례 화면은 아래 "조례 조문"의 API로 읽습니다. 같은 대지를 다시 조회해도 설계자가 고른 숨김·원문 검토는 유지됩니다.

### 단계별 주소 선택

화면의 기본 입력 방식입니다. 시·도 → 시·군·구 → 읍·면·동(→ 리)을 목록에서 고르고, 지번 숫자만 직접 입력합니다. 글자 검색(1번)은 주소를 붙여넣을 때 쓰는 보조입니다. 이 API는 프로젝트와 무관하고 아무것도 저장하지 않습니다. 로직은 `sida/experts/site/landapi.py`(`regions`, `find_lots`)에 있습니다.

| 순서 | 메서드·경로 | 요청 | 응답 |
|---|---|---|---|
| a. 시·도 목록 | `GET /api/site/regions` | 없음 | `{parent: "", level: "sido", regions: [지역]}` |
| b. 시·군·구 목록 | `GET /api/site/regions?parent=41` | 고른 시·도의 `code` | `level: "sigungu"` |
| c. 읍·면·동 목록 | `GET /api/site/regions?parent=41410` | 고른 시·군·구의 `code` | `level: "emd"` |
| d. 리 목록 | `GET /api/site/regions?parent=41830250` | 고른 읍·면의 `code` (`has_ri`가 `true`일 때만) | `level: "ri"` |
| e. 지번으로 필지 찾기 | `GET /api/site/lots?dong_code=4141010500&main=689&sub=14&mountain=false` | 동·리의 `dong_code`, 본번, 부번(선택), 산 여부(선택) | `{dong_code, lot: "689-14", candidates: [필지]}` |

- 지역은 `{code, name, full_name, has_ri, dong_code}`입니다. 목록은 이름 가나다순입니다. `full_name`은 "경기도 군포시 금정동"처럼 시·도부터 쓴 이름입니다.
- 읍·면·동에서 `has_ri`가 `true`(읍·면)이면 리 목록을 한 번 더 보여 주고, 리의 `dong_code`를 씁니다. `false`(동)이면 그 동의 `dong_code`를 바로 씁니다. 시·도와 시·군·구의 `dong_code`는 빈 문자열입니다.
- 지번: `main`(본번)은 1~9999, `sub`(부번)는 0~9999입니다. `sub`를 빼면 그 본번의 필지 전부가 나옵니다(`689` → 689, 689-1, 689-14 …). 산 번지는 `mountain=true`입니다.
- 필지는 1번 후보와 같은 모양(`{pnu, address, road_address, building, matched_by: "lot"}`)이지만 도로명 주소와 건물 이름은 빈 문자열입니다. 없는 지번이면 `candidates: []`입니다. 오타를 고쳐 주지 않으니 다시 입력하도록 안내하세요.
- 고른 필지의 `pnu`를 2번(`PUT /api/projects/{name}/site`)에 `{pnus: [...]}`로 보내면 조회해 저장합니다.
- 서버는 받은 지역 목록을 기억해 두고 서버를 다시 켤 때까지 브이월드를 다시 부르지 않습니다.
- 필지 번호(PNU)는 `dong_code` 10자리 + 산 여부 1자리(일반 1, 산 2) + 본번 4자리 + 부번 4자리입니다.

오류 응답은 `{detail: "메시지"}`이고, `detail`은 사용자에게 그대로 보여 줄 수 있는 문장입니다.

| 상태 | 뜻 |
|---|---|
| 400 | 주소가 비었거나, `pnus`가 비었거나 검색 결과에 없는 필지, 없는 필지 번호, 형식이 틀린 코드·지번 |
| 404 | 프로젝트 없음 |
| 422 | 요청 형식 오류 |
| 429 | 브이월드(또는 공공데이터포털) 하루 호출 한도 초과 |
| 502 | 브이월드(또는 공공데이터포털) 연결 실패 또는 예상과 다른 응답 |
| 503 | 브이월드 키가 없거나 거부됨(`.env`의 `VWORLD_API_KEY`, `VWORLD_DOMAIN`). 계획 용도 API에서는 공공데이터포털 키(`DATA_GO_KR_API_KEY`) |

`detail`은 어느 쪽 API인지 밝혀 씁니다("브이월드가 키를 거부했습니다", "공공데이터포털이 키를 거부했습니다").

필지는 찾았지만 일부 항목(용도지역, 토지 특성, 건축물대장, 건축제한 근거 조문, 조례)을 가져오지 못한 경우는 오류가 아닙니다. 200으로 저장되고, 그 항목이 "미확인"으로 표시됩니다(`summary.missing`, `parcels[].errors`).

### 지도

주소를 고르면 지도에 그 필지를 보여 주고, 지도를 클릭해 필지를 고르거나 여러 필지를 합칠 수 있게 하는 API입니다. 프로젝트와 무관하고 아무것도 저장하지 않습니다. 로직은 `sida/experts/site/landapi.py`(`map_layers`, `parcel_at`, `parcel_shape`)에 있습니다. 좌표는 모두 경도·위도(EPSG:4326)이고 `[경도, 위도]` 순서입니다.

| 용도 | 메서드·경로 | 요청 | 응답 |
|---|---|---|---|
| 지도 이미지 주소 | `GET /api/site/map` | 없음 | `{base: {url, attribution}, cadastral: {url, params, crs, min_zoom, opacity}}` |
| 지도 클릭으로 필지 찾기 | `GET /api/site/parcel-at?lon=126.945978&lat=37.37025` | 클릭한 지점 | `{lon, lat, candidates: [필지]}` (0개 또는 1개) |
| 고른 필지들의 경계 | `GET /api/site/shapes?pnu=…&pnu=…` | 필지 번호(최대 50개) | `{shapes: [{pnu, shape}]}` |

- 지도 화면은 Leaflet을 스크립트로 불러 쓰면 됩니다(빌드 없음).
  - 배경: `L.tileLayer(base.url)`. 브라우저가 브이월드에서 직접 받습니다.
  - 지적도 선: `L.tileLayer.wms(cadastral.url, {...cadastral.params, minZoom: cadastral.min_zoom, opacity: cadastral.opacity})`. 줌 18보다 작으면 브이월드가 빈 이미지를 주므로 그 아래에서는 켜지 않습니다. 투명 옵션을 줘도 이미지가 불투명하게 오므로 반투명으로 겹칩니다.
  - `cadastral.params`에는 `domain`이 없습니다. 브라우저는 Referer를 보내는데, 브이월드는 Referer와 `domain`이 같이 오면 키를 거부합니다(2026-10-14 실제 호출로 확인).
- 지도 이미지 주소에는 브이월드 키가 들어 있어 브라우저에 보입니다. 자기 PC에서만 도는 지금은 괜찮지만, 여러 사람이 접속하게 되면 서버가 지도를 대신 받아 전달해야 합니다.
- 필지: 1번 후보와 같은 모양에 `shape`가 더 있습니다(`{pnu, address, road_address, building, matched_by: "map", shape}`). 클릭한 곳이 도로·하천처럼 필지가 아니면 `candidates: []`입니다.
- `shape`는 GeoJSON 도형(`{type: "MultiPolygon", coordinates}`)입니다. `L.geoJSON(shape)`으로 그대로 그립니다. 없는 필지는 `shape: null`입니다.
- 고른 필지를 2번(`PUT /api/projects/{name}/site`)에 `{pnus: [...]}`로 보내 저장하면, 저장된 대지 사실의 `parcels[].shape`에 경계가 함께 저장됩니다. 다시 열 때는 브이월드를 부르지 않고 이것으로 그립니다. 경계만 가져오지 못한 경우 `shape`는 `null`이고 오류로 치지 않습니다.
- 오류: 한국 밖의 지점(위도·경도를 바꿔 넣은 경우 포함)이나 형식이 틀린 필지 번호는 400, 그 밖에는 위 표와 같습니다.

### 대지 사실 모양

```json
{
  "available": true,
  "query": "경기도 군포시 금정동 689",
  "fetched_at": "2026-10-06T15:20:11+09:00",
  "parcels": [
    {"pnu": "4141010500106890014", "address": "경기도 군포시 금정동 689-14", "road_address": "…",
     "building": "…", "area_m2": 1014.3, "land_category": "공장용지", "use": "공업용",
     "road_side": "소로한면", "shape": {"type": "MultiPolygon", "coordinates": ["…"]},
     "buildings": [{"name": "(주)혜창", "purpose": "공장", "floors_above": 4, "…": "…"}], "errors": []}
  ],
  "summary": {
    "parcel_count": 1, "municipality": "경기도 군포시", "total_area_m2": 1014.3, "area_complete": true,
    "zoning": [{"zone": "일반공업지역", "bcr_max": 70, "far_min": 150, "far_max": 350, "partial": false, "…": "…"}],
    "districts": [{"name": "과밀억제권역", "relation": "포함"}],
    "roads": [{"name": "소로1류(폭 10m~12m)", "relation": "접함"}],
    "flags": ["…확인이 필요한 사항…"],
    "missing": []
  },
  "restrictions": [{"area": "41410", "codes": ["UQA320", "…"], "laws": ["…"], "error": null}],
  "uses": [{"name": "공장", "checked_at": "…", "zones": ["…"], "error": null}],
  "lines": ["대지: 필지 1개, 면적 1,014.3㎡", "…"]
}
```

`lines`는 대지 사실을 한 줄씩 적은 문장들입니다. 화면을 따로 꾸미기 전에는 이것만 나열해도 됩니다. 두 칸 공백으로 시작하는 줄은 바로 위 줄의 부속(단서 조항, 용도 정의)입니다. `summary.zoning`의 `bcr_max`, `far_min`, `far_max`는 법정 범위이고, 조례가 정한 실제 수치는 조례 API의 `base`에 있습니다.

`restrictions`, `uses`, `parcels[].buildings`는 2026-10-16에 생겼습니다. 그 전에 저장한 대지는 `restrictions: []`, `uses: []`, `buildings: null`로 옵니다. 다시 조회하면 채워집니다.

### 건축물대장, 건축제한 근거 조문, 계획 용도 (공공데이터포털)

로직은 `sida/experts/site/datago.py`(API 호출)와 `site_facts.py`(`attach_restrictions`, `check_use`, `remove_use`)에 있습니다. 모두 정부 응답에 있는 값만 담고, 가져오지 못한 것은 "미확인"입니다.

**기존 건축물** `parcels[].buildings`: 건축물대장 표제부에 등록된 건물 목록입니다. 대지를 조회할 때 같이 가져옵니다. 등록된 건물이 없으면 `[]`, 가져오지 못했으면 `null`이고 `parcels[].errors`에 `"buildings"`가 들어갑니다.

| 키 | 뜻 |
|---|---|
| `name`, `dong` | 건물 이름, 동 이름 |
| `main_or_annex`, `register_kind` | 주건축물·부속건축물, 대장 종류(일반·집합) |
| `purpose`, `purpose_detail` | 주용도, 기타 용도 |
| `structure`, `road_address` | 구조, 도로명 주소 |
| `floors_above`, `floors_below` | 지상·지하 층수(정수) |
| `plat_area_m2`, `building_area_m2`, `total_floor_area_m2` | 대지면적, 건축면적, 연면적(㎡) |
| `bcr`, `far`, `height_m` | 등록된 건폐율·용적률(%), 높이(m). 대장에 적힌 값 그대로이고, 지금 법규에 맞는지는 뜻하지 않습니다 |
| `approved` | 사용승인일(`YYYYMMDD`) |

숫자가 대장에 없으면 `null`입니다. 0은 대장에 0으로 적힌 값입니다. 대지 분석가에게는 등록된 건폐율·용적률을 빼고 넘기고, 법규 전문가에게는 모두 넘깁니다.

**건축제한 근거 조문** `restrictions`: 시·군·구마다 하나입니다. 대지가 속한 용도지역·지구(`codes`, 접한 것은 제외)의 건축제한을 정한 조문 목록입니다.

- `laws[]`는 `{text, law_code, local, zones}`입니다. `text`는 조문 제목(본문 첫 문장이 붙어 오기도 함), `zones`는 그 조문이 걸린 용도지역·지구 이름, `local`은 지자체 조례이면 `true`입니다.
- 응답에 법령 이름이 없습니다. 그래서 "제71조(용도지역안에서의 건축제한)"처럼 조문 제목만 보여 주고, 국가 법령과 조례로만 나눕니다. 법령 이름을 추측해 붙이지 마세요.
- 가져오지 못했으면 `error`에 이유(`network` 등)가 있고 `laws`는 `[]`입니다. 해당 조문이 정말 없는 경우와 구분해 보여 주세요.

**계획 용도** `uses`: 설계자가 지으려는 용도를 이 대지에 지을 수 있는지입니다. 설계자가 고른 용도만 조회합니다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/site/uses?q=공장` | 용도 이름 일부 | `{query, uses: [{name, code}]}`. 토지이음이 아는 용도 이름(최대 100개). 정확히 같은 이름이 맨 앞, 그다음 짧은 이름 순 |
| `POST /api/projects/{name}/site/uses` | `{name: "공장"}` | 대지 사실 전체(위 모양). `uses`에 결과가 더해짐 |
| `DELETE /api/projects/{name}/site/uses/{용도}` | 없음 | 대지 사실 전체. 그 용도가 빠짐 |

- 용도 이름은 토지이음 이름과 정확히 같아야 합니다. 입력칸에서 `GET /api/site/uses`로 후보를 보여 주고 고르게 하세요. 정확히 같은 이름이 없으면 `POST`가 400이고 `detail`에 비슷한 이름을 적어 줍니다.
- 같은 용도를 다시 보내면 앞의 결과를 바꿉니다. 대지를 다시 조회하면(`PUT .../site`) 저장된 용도를 새 용도지역으로 다시 확인합니다.
- `uses[]`는 `{name, checked_at, zones, error}`이고, `zones[]`는 용도지역·지구마다 `{area, zone, code, zone_law, acts}`입니다.
  - `acts[]`는 `{act, result, conditions, uses}`입니다. `act`는 행위(건축, 신설·증설·이전 등), `result`는 토지이음의 판단(가능, 금지 등)입니다.
  - `conditions`는 붙어 있는 단서 조항 원문입니다. "금지"여도 단서로 허용되는 경우가 있으니 `result`와 함께 꼭 보여 주세요.
  - `uses[]`는 그 용도의 법적 정의 `{name, law, definition}`입니다.
- 이 대지의 용도지역·지구에 그 용도에 대한 정보가 없으면 `zones: []`입니다. 가져오지 못했으면 `error`에 이유가 있습니다.
- 오류: 대지 조회 전이거나 빈 이름, 토지이음에 없는 이름은 400, 조회한 적 없는 용도를 지우면 404, 공공데이터포털 키·연결 문제는 위 오류 표와 같습니다.

# 조례 조문

대지의 지자체 조례가 건폐율·용적률에 대해 말하는 것을 설계자에게 보여 주기 위한 자료와 JSON API입니다. 웹 화면은 아래 API에 연결하면 됩니다. 로직은 `sida/experts/site/site_facts.py`(`ordinance_options`, `set_option_dismissed`)에 있고, 경로는 `sida/experts/site/api.py`에 있습니다.

## 원칙

- 조문을 걸러내지 않습니다. 조례에서 건폐율·용적률을 다루는 조문은 전부 내려갑니다.
- 설계자는 조문마다 두 가지를 고를 수 있습니다.
  - **원문 검토**(`detailed`): 전문가가 이 조문의 원문을 읽게 합니다. 고르지 않은 완화·강화 조문은 전문가에게 제목만 갑니다.
  - **숨김**(`dismissed`): 필요 없는 조문입니다. 목록에는 남지만 전문가에게는 제목도 가지 않습니다. 숨김이 원문 검토보다 우선합니다.
- 두 선택은 프로젝트의 `site_facts.json`에 저장됩니다. 같은 조례를 다시 조회해도 유지됩니다.
- 수치는 조문에서 정해진 규칙으로 읽은 것이고, 항상 원문 줄(`quote`)과 함께 옵니다. 읽지 못한 경우 `value`는 `null`입니다.

## JSON API

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/projects/{name}/site/ordinance` | 없음 | 아래 "응답 모양" |
| `PUT /api/projects/{name}/site/ordinance/options/{id}` | `{dismissed: true \| false}`, `{detailed: true \| false}` 또는 둘 다 | 바뀐 뒤의 같은 응답 |

`id`는 조문 번호입니다(예: `제52조`, `제54조의2`). 기본 조문(`articles`)은 숨길 수 없습니다.

오류: 프로젝트가 없거나 그런 조문이 없으면 404, 요청 본문이 잘못되면 422입니다. 대지를 아직 조회하지 않았거나 조례를 찾지 못한 프로젝트는 200으로 `available: false`를 돌려줍니다.

## 응답 모양

```json
{
  "available": true,
  "municipality": "경기도 군포시",
  "name": "군포시 도시계획 조례",
  "effective": "2025-10-10",
  "error": null,
  "base": [
    {
      "zone": "일반공업지역",
      "bcr": {"value": 70, "quote": "일반공업지역 : 100분의 70 이하", "conditional": false, "label": "제49조"},
      "far": {"value": 350, "quote": "일반공업지역 : 100분의 350 이하", "conditional": false, "label": "제53조"}
    }
  ],
  "articles": [
    {"label": "제49조", "title": "용도지역안에서의 건폐율", "text": "…", "annex": null}
  ],
  "groups": [
    {
      "id": "site",
      "title": "대지 위치로 정해지는 것",
      "note": "대지가 그 지구·구역 안에 있으면 기본 수치보다 이 조문이 우선합니다.",
      "items": [
        {
          "id": "제34조", "label": "제34조", "title": "자연ㆍ특화경관지구안에서의 건폐율",
          "text": "…", "applies": false, "matched": [], "dismissed": false, "detailed": false
        }
      ]
    },
    {"id": "design", "title": "설계 내용으로 얻을 수 있는 완화", "note": "…", "items": []},
    {"id": "admin", "title": "행정이 따로 지정하는 것", "note": "…", "items": []}
  ]
}
```

| 항목 | 뜻 |
|---|---|
| `base` | 대지의 용도지역별 기본 수치. `bcr`은 건폐율, `far`는 용적률. 조문에 그 용도지역이 없으면 `null` |
| `base[].bcr.value` | 읽은 수치(%). 한 가지 수치로 읽히지 않거나 법정 범위를 벗어나면 `null`이고, 범위를 벗어난 경우 `out_of_range: true`가 붙습니다 |
| `base[].bcr.conditional` | 줄에 단서나 예외가 붙어 있음. 화면에 "원문 확인"을 같이 보여 주세요 |
| `articles` | 기본 수치를 정하는 조문의 원문. 별표를 따르는 조례는 `annex.text`에 별표 내용이 있습니다 |
| `groups` | 나머지 조문 전부. 순서는 항상 `site`, `design`, `admin` |
| `items[].applies` | `site` 묶음에서만 `true`/`false`: 대지가 속한 지구·구역 이름이 그 조문에 나오는지. `design`과 `admin`은 `null`(이 자료로 알 수 없음) |
| `items[].matched` | `applies: true`일 때 해당하는 지구·구역 이름 |
| `items[].dismissed` | 설계자가 숨긴 조문 |
| `items[].detailed` | 설계자가 원문 검토를 고른 조문. 숨긴 조문이면 항상 `false` |
| `items[].text` | 조문 원문. 항과 호마다 줄을 바꿔 두었습니다. 줄 앞 공백 두 칸은 호입니다 |

`text`는 줄바꿈을 살려서 보여 주세요(예: CSS `white-space: pre-wrap`).

## 세 묶음의 기준

조문 제목으로 나눕니다(`sida/experts/regulation/ordinance.py`의 `classify`).

| 묶음 | 기준 | 예 |
|---|---|---|
| `admin` | 제목에 "강화" | 건폐율의 강화 |
| `site` | 제목에 "지구", "구역", "성장관리", "그 밖", "기타" | 경관지구안에서의 건폐율, 그 밖의 용도지구·구역 등의 용적률 |
| `design` | 나머지 | 공원 등에 인접한 대지에 대한 용적률의 완화, 건폐율의 완화 |

제목에 건폐율·용적률이 없어도, 지구·구역의 조문이 본문에서 건폐율이나 용적률을 정하면 `site`에 넣습니다(예: 서울의 "자연경관지구 안에서의 건축제한").

분류는 제목에 따른 것이라 완벽하지 않습니다. 예를 들어 "건폐율의 완화" 한 조문 안에 방화지구(위치)와 기존 공장(설계)이 함께 들어 있는 조례가 있습니다. 그래서 화면은 묶음을 안내로만 쓰고, 조문 원문을 항상 펼쳐 볼 수 있게 해 주세요.

## 전문가에게 넘어가는 것

화면에는 모든 조문이 전부 나오지만, `regulation_checker`에게는 이 대지와 관련된 부분만 갑니다. 길이를 줄이고, 모델이 해당하지 않는 완화를 적용하지 않게 하기 위해서입니다.

| 조문 | 전문가가 받는 것 |
|---|---|
| 기본 조문 | 대지의 용도지역 줄과 그 밖의 항. 다른 용도지역 줄은 생략 |
| 별표(표 형식) | 대지의 용도지역 행 |
| `site`, `applies: true` | 건폐율·용적률을 다루는 항 |
| `site`, `applies: false` | 넘기지 않음 |
| `design`, `admin` | 제목 목록. `detailed: true`인 조문은 원문도 |
| `dismissed: true` | 넘기지 않음 |

실제 주소 기준으로 서울 세종로 1은 12,000자에서 2,900자로, 군포 금정동은 6,000자에서 2,800자로 줄었습니다.
