# Sida 자료 서버 중계 (relay)

자기 키가 없는 Sida 앱의 정부 API 호출(브이월드, 공공데이터포털, 법제처)을 서버의 키로 대신 해 주는 작은 서버입니다. 국내 서버(네이버 클라우드 `sida-data`, `/opt/sida-kr`)에서 Docker로 돕니다. 로컬 앱 패키지에는 들어가지 않습니다. 앱 쪽은 `sida/relay.py`입니다.

## 앱은 언제 이 서버를 쓰나

- 이 PC에 그 서비스의 키가 있으면 지금처럼 정부 API를 **직접** 부릅니다.
- 키가 없고 "Sida 키"(`SIDA_RELAY_TOKEN`, `sida_…`)가 있으면 이 서버를 거칩니다. 주소는 설정의 "Sida 자료 서버 주소"(`SIDA_RELAY_URL`)이고, 비워 두면 팀 서버(`https://sida-kr.duckdns.org`, `sida/relay.py`의 `DEFAULT_URL`)입니다. 정부 키는 앱에 없습니다.
- 그 밖에는 지금처럼 "키 없음"입니다.

## 접속 키 (사람마다 하나)

- 팀이 사람마다 접속 키를 만들어 줍니다. 앱은 `Authorization: Bearer sida_…`로 보냅니다. 지도 이미지는 브라우저가 직접 불러 머리글을 못 붙이므로 `sida_token` 매개변수로 보냅니다.
- 키가 없거나 모르는 키는 401, 폐기했거나 만료된 키는 403입니다. 앱은 "키를 거부했습니다"로 알립니다.
- 서버에는 키 원문이 아니라 SHA-256만 SQLite(`/data/relay.db`)에 둡니다. 키는 만들 때 한 번만 보이므로, 잃어버리면 폐기하고 새로 만듭니다.
- 사용 기록은 키·날짜·서비스마다 호출 수와 실패 수만 셉니다. 주소·지번·검색어는 남기지 않습니다.

```bash
cd /opt/sida-kr
docker compose exec relay python -m relay.admin issue "홍길동 (OO대)" --limit 3000 --days 90
docker compose exec relay python -m relay.admin list
docker compose exec relay python -m relay.admin revoke <id>
docker compose exec relay python -m relay.admin limit <id> 5000
docker compose exec relay python -m relay.admin usage --days 7
```

## 키 요청과 승인 (앱에서 키 받기)

키가 없는 사람은 앱 설정 창 "Sida 키 받기"에 이름(소속)과 연락처(선택)를 넣고 요청합니다.

1. 앱이 `POST /relay/requests`로 요청을 보내고, 서버는 받기 코드(`sidareq_…`)를 돌려줍니다. 서버에는 이름·연락처와 받기 코드의 SHA-256만 남습니다.
2. 관리자가 서버에서 기다리는 요청을 보고 승인하거나 거절합니다. `list`도 기다리는 요청 수를 알려 줍니다.
3. 앱은 설정 창을 열 때와 켤 때 `POST /relay/requests/claim`으로 묻습니다. 승인됐으면 그때 키를 만들어 **한 번만** 돌려주고, 앱이 `.env`에 저장합니다. 키를 사람이 옮겨 줄 필요가 없습니다.

```bash
docker compose exec relay python -m relay.admin requests          # 기다리는 요청 (--all: 답한 것까지)
docker compose exec relay python -m relay.admin approve <요청 id> --limit 3000 [--days 90]
docker compose exec relay python -m relay.admin refuse <요청 id>
```

- 한 주소에서 한 시간에 5번까지 요청할 수 있고, 답하지 않은 요청이 200개를 넘으면 더 받지 않습니다(429).
- 승인한 요청의 키를 앱이 아직 받아 가지 않았으면 `requests --all`에 "승인(아직 안 받아 감)"으로 보입니다.

## 한도

- 키마다 하루 API 호출 수(`--limit`, 기본 3,000번). 한국 시간 자정에 다시 셉니다. SQLite에 있어 서버를 다시 켜도 이어 셉니다.
- 키마다 1분에 API 120번, 지도 이미지 600장. 보내는 주소마다 1분에 1,500번(학교는 주소 하나를 같이 씀). 분당 한도는 메모리에만 둡니다.
- 넘으면 429이고 앱은 "하루 호출 한도"로 알립니다.

## 열린 경로

| 경로 | 보내는 곳 |
|---|---|
| `GET /relay/health` | `{"ok": true, "services": {"vworld", "datago", "law", "vworld3d"}}` 서버에 키가 있는지 (접속 키 필요 없음) |
| `GET /relay/vworld3d?sida_token=…` | 앱의 브이월드 3D 페이지(`static/vworld3d.html`)에 서버의 3D 스크립트 주소를 채워 돌려줌. 앱이 틀(iframe)로 엶. 하루 호출 수에 세지 않음 |
| `GET /relay/vworld3d-frame.js` | 위 페이지의 스크립트 (접속 키 필요 없음) |
| `POST /relay/requests` `{name, contact}` | 키 요청. `201 {id, claim, state: "pending"}` (접속 키 필요 없음) |
| `POST /relay/requests/claim` `{claim}` | 요청 상태 `{id, state}`. 승인 직후 한 번만 `key`가 붙음. 모르는 코드는 404 |
| `GET /relay/vworld/req/search`, `req/data`, `ned/data/<이름>` | `api.vworld.kr`의 같은 경로 (키·도메인을 서버가 붙임) |
| `GET /relay/vworld/req/wms`, `req/wmts/1.0.0/Base/{z}/{y}/{x}.png` | 지도 배경·지적선 이미지 (브라우저가 부름) |
| `GET /relay/datago/<토지이음·건축물대장 4개 경로>` | `apis.data.go.kr/1613000/...` |
| `GET /relay/law/DRF/lawSearch.do`, `lawService.do` (`target`은 `aiSearch`, `ordin`만) | `www.law.go.kr/DRF/...` |

- 그 밖의 경로는 404입니다. 아무 주소나 대신 불러 주는 서버가 되지 않게 Sida가 쓰는 경로만 엽니다.
- 응답은 상태 코드·형식·본문을 그대로 돌려줍니다. **저장하지 않습니다**(캐시 없음, 브이월드 이용약관 제19조). 질의도 기록하지 않습니다(`--no-access-log`).
- 앱이 보낸 `key`, `domain`, `apiKey`, `serviceKey`, `OC`, `sida_token`은 정부 서비스로 넘기지 않고 서버 것만 붙입니다. 응답에 서버 키가 섞여 오면 `***`로 가립니다.

## 브이월드 3D 지도 (중계 대신 페이지를 내줌)

브이월드 3D 지도(WebGL)는 브라우저가 브이월드 스크립트를 키와 함께 직접 불러야 하고, 브이월드가 페이지 주소를 키와 대조합니다. 그래서 응답을 대신 받아 주는 대신, 이 서버가 앱의 3D 페이지를 **자기 주소로** 내줍니다.

- 키가 없는 PC의 앱은 `https://sida-kr.duckdns.org/relay/vworld3d?sida_token=…`을 틀(iframe)로 열고, 제도판과 `postMessage`로만 주고받습니다(`webui/app/vworld3d-frame.js`). 3D 타일은 사용자 PC가 브이월드에서 바로 받습니다(서버를 거치지 않음).
- 브이월드에는 이 서버 주소가 페이지 주소로 보입니다(`Referrer-Policy: origin`이라 접속 키는 넘어가지 않음). 그래서 도메인을 엄격히 보는 **운영키로 바꿔도** 그대로 됩니다.
- 이 페이지를 틀로 넣을 수 있는 곳은 이 PC의 Sida 앱(`http://localhost`, `http://127.0.0.1`)뿐입니다(`Content-Security-Policy: frame-ancestors`).
- 3D 키는 보는 사람의 브라우저에 들어갑니다(웹 지도는 다 그렇습니다). 서버의 다른 조회에 쓰는 키와 나눠 두려면 3D 지도만 고른 브이월드 키를 따로 받아 `relay.env`에 `VWORLD_3D_API_KEY=`로 넣습니다. 없으면 `VWORLD_API_KEY`를 씁니다.
- 페이지와 스크립트는 `webui/app/`의 것을 `relay/static/`에 복사해 둡니다(서버 이미지는 `relay/`만으로 만들기 때문). 둘이 다르면 테스트가 실패하니, `webui/app/vworld3d.html`이나 `vworld3d-frame.js`를 고치면 `relay/static/`에도 복사합니다.

## 앱에서 이 서버로 안 되는 것

- 법제처 별표 파일 내려받기는 원래 키가 필요 없어 계속 직접 받습니다.

## 설치 (국내 서버)

`/opt/sida-kr`에 이미 `caddy`가 있다는 전제입니다(`compose.yaml`, `Caddyfile`).

1. 서버용 정부 키를 받습니다. 브이월드는 **이 서버 주소**(`https://sida-kr.duckdns.org`)로 키를 받아야 합니다(개발키는 6개월, 운영키는 심사). 공공데이터포털·법제처도 서버용으로 따로 받는 것을 권합니다.
2. 이 폴더의 `Dockerfile`, `requirements.txt`, `__init__.py`, `app.py`, `tokens.py`, `admin.py`와 `static/` 폴더를 서버의 `/opt/sida-kr/relay/`에 복사합니다(예: `git archive origin/main relay | ssh 서버 "tar -x -C /tmp"`).
3. `/opt/sida-kr/relay.env`를 만듭니다(권한 600, 저장소에 넣지 않음).

   ```
   VWORLD_API_KEY=...
   VWORLD_DOMAIN=https://sida-kr.duckdns.org
   DATA_GO_KR_API_KEY=...
   LAW_OPEN_API_OC=...
   # 선택: 3D 지도 전용 브이월드 키 (없으면 VWORLD_API_KEY)
   VWORLD_3D_API_KEY=...
   ```

4. `compose.yaml`에 서비스와 볼륨을 더합니다. 키 목록은 볼륨 `relay-data`에 남습니다.

   ```yaml
   services:
     relay:
       build: ./relay
       env_file: relay.env
       volumes:
         - relay-data:/data
       mem_limit: 192m
       restart: unless-stopped
   volumes:
     relay-data:
   ```

5. `Caddyfile`을 바꿉니다.

   ```
   sida-kr.duckdns.org {
   	handle /relay/* {
   		reverse_proxy relay:8000
   	}
   	handle /health {
   		respond "ok" 200
   	}
   	handle {
   		respond 404
   	}
   }
   ```

6. `docker compose up -d --build relay && docker compose restart caddy`
7. 확인: `curl https://sida-kr.duckdns.org/relay/health` → 서비스마다 `true`인지
8. 첫 접속 키를 만들고(`relay.admin issue`), 앱 설정 창에 주소와 키를 넣어 대지 조회가 되는지 봅니다.

서버는 1GB 메모리라 `mem_limit`을 작게 둡니다. 지도 이미지가 가장 많이 오가므로 사용자가 늘면 이 부분부터 봅니다. 백업은 볼륨의 `relay.db` 하나면 됩니다(키 원문은 없음).
