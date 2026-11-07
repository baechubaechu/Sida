# Sida 자료 서버 중계 (relay)

자기 키가 없는 Sida 앱의 정부 API 호출(브이월드, 공공데이터포털, 법제처)을 서버의 키로 대신 해 주는 작은 서버입니다. 국내 서버(네이버 클라우드 `sida-data`, `/opt/sida-kr`)에서 Docker로 돕니다. 로컬 앱 패키지에는 들어가지 않습니다. 앱 쪽은 `sida/relay.py`입니다.

## 앱은 언제 이 서버를 쓰나

- 이 PC에 그 서비스의 키가 있으면 지금처럼 정부 API를 **직접** 부릅니다.
- 키가 없고, 설정 창에 "Sida 자료 서버 주소"(`SIDA_RELAY_URL`)와 "Sida 자료 서버 키"(`SIDA_RELAY_TOKEN`, `sida_…`)가 **둘 다** 있으면 이 서버를 거칩니다. 정부 키는 앱에 없습니다.
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

## 한도

- 키마다 하루 API 호출 수(`--limit`, 기본 3,000번). 한국 시간 자정에 다시 셉니다. SQLite에 있어 서버를 다시 켜도 이어 셉니다.
- 키마다 1분에 API 120번, 지도 이미지 600장. 보내는 주소마다 1분에 1,500번(학교는 주소 하나를 같이 씀). 분당 한도는 메모리에만 둡니다.
- 넘으면 429이고 앱은 "하루 호출 한도"로 알립니다.

## 열린 경로

| 경로 | 보내는 곳 |
|---|---|
| `GET /relay/health` | `{"ok": true, "services": {"vworld", "datago", "law"}}` 서버에 키가 있는지 (접속 키 필요 없음) |
| `GET /relay/vworld/req/search`, `req/data`, `ned/data/<이름>` | `api.vworld.kr`의 같은 경로 (키·도메인을 서버가 붙임) |
| `GET /relay/vworld/req/wms`, `req/wmts/1.0.0/Base/{z}/{y}/{x}.png` | 지도 배경·지적선 이미지 (브라우저가 부름) |
| `GET /relay/datago/<토지이음·건축물대장 4개 경로>` | `apis.data.go.kr/1613000/...` |
| `GET /relay/law/DRF/lawSearch.do`, `lawService.do` (`target`은 `aiSearch`, `ordin`만) | `www.law.go.kr/DRF/...` |

- 그 밖의 경로는 404입니다. 아무 주소나 대신 불러 주는 서버가 되지 않게 Sida가 쓰는 경로만 엽니다.
- 응답은 상태 코드·형식·본문을 그대로 돌려줍니다. **저장하지 않습니다**(캐시 없음, 브이월드 이용약관 제19조). 질의도 기록하지 않습니다(`--no-access-log`).
- 앱이 보낸 `key`, `domain`, `apiKey`, `serviceKey`, `OC`, `sida_token`은 정부 서비스로 넘기지 않고 서버 것만 붙입니다. 응답에 서버 키가 섞여 오면 `***`로 가립니다.

## 앱에서 이 서버로 안 되는 것

- **브이월드 3D 지도(WebGL)**: 브라우저가 브이월드 스크립트를 키와 함께 직접 불러야 하고, 브이월드가 페이지 주소를 키와 대조합니다. 중계로는 안 되어 키가 없는 PC에서는 3D 지도 버튼이 안내만 띄웁니다.
- 법제처 별표 파일 내려받기는 원래 키가 필요 없어 계속 직접 받습니다.

## 설치 (국내 서버)

`/opt/sida-kr`에 이미 `caddy`가 있다는 전제입니다(`compose.yaml`, `Caddyfile`).

1. 서버용 정부 키를 받습니다. 브이월드는 **이 서버 주소**(`https://sida-kr.duckdns.org`)로 키를 받아야 합니다(개발키는 6개월, 운영키는 심사). 공공데이터포털·법제처도 서버용으로 따로 받는 것을 권합니다.
2. 이 폴더의 `Dockerfile`, `requirements.txt`, `__init__.py`, `app.py`, `tokens.py`, `admin.py`를 서버의 `/opt/sida-kr/relay/`에 복사합니다.
3. `/opt/sida-kr/relay.env`를 만듭니다(권한 600, 저장소에 넣지 않음).

   ```
   VWORLD_API_KEY=...
   VWORLD_DOMAIN=https://sida-kr.duckdns.org
   DATA_GO_KR_API_KEY=...
   LAW_OPEN_API_OC=...
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
