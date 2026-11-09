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
| `GET /relay/vworld3d?sida_token=…` | 앱의 브이월드 3D 페이지(`static/vworld3d.html`)에 서버의 3D 스크립트 주소(`VWORLD_3D_API_KEY`)를 채워 돌려줌. 앱이 틀(iframe)로 엶. 하루 호출 수에 세지 않음. 3D 키가 없으면 503 |
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
- 3D 키는 보는 사람의 브라우저에 들어갑니다(웹 지도는 다 그렇고, 개발자 도구로 볼 수 있습니다). 그래서 **3D 지도 API만 고른 브이월드 키를 따로** 받아(서비스 URL `https://sida-kr.duckdns.org`) `relay.env`에 `VWORLD_3D_API_KEY=`로 넣습니다. 서버의 다른 조회에 쓰는 `VWORLD_API_KEY`는 절대 브라우저로 가지 않습니다. `VWORLD_3D_API_KEY`가 없으면 3D 페이지는 `503`이고 `/relay/health`의 `vworld3d`가 `false`라, 앱은 3D 지도 대신 "아직 Sida 자료 서버에 준비되지 않았습니다" 안내를 띄웁니다.
- 3D 키가 새어 나가면 브이월드에서 그 키만 폐기하고 새로 받아 `relay.env`를 바꾼 뒤 `docker compose up -d relay`로 다시 켭니다. 개발키는 도메인 확인이 느슨해 다른 곳에서도 쓰일 수 있고, 운영키는 도메인을 엄격히 봅니다.
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
   # 3D 지도 API만 고른 브이월드 키 (서비스 URL https://sida-kr.duckdns.org). 없으면 3D 지도는 꺼짐
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

## 소개 페이지 (`/`)

`https://sida-kr.duckdns.org/`에는 Sida를 소개하는 한 장짜리 페이지가 있습니다(`site/`, 순수 HTML/CSS, 빌드 없음). 중계 서버(`relay`)가 아니라 Caddy가 서버의 `/opt/sida-kr/site/` 폴더를 그대로 내주므로, 페이지를 고쳐도 `relay`를 다시 만들 필요가 없습니다. `/relay/*`와 `/health`가 먼저 처리되고, 그 밖의 주소는 이 폴더의 파일입니다(없는 파일은 404, `.`으로 시작하는 파일은 숨김).

### 고치는 법 (팀원용)

서버에 들어갈 필요가 없습니다. 저장소만 고치면 됩니다.

1. 최신 main에서 브랜치를 만들고(`git switch -c docs/site-...`) `relay/site/`의 파일을 고칩니다. 그림을 넣을 때는 이 폴더에 파일을 두고 `/파일이름`으로 부릅니다.
2. 미리 보기: `cd relay/site && python -m http.server 8790` 후 브라우저에서 `http://127.0.0.1:8790`.
3. 확인: `pytest -q tests/relay/test_site.py` (페이지 안 링크, 쓰는 파일이 폴더에 있는지, 다른 사이트의 글꼴·스크립트를 부르지 않는지, 비공개 저장소 주소가 없는지).
4. PR을 엽니다. CI를 통과해 main에 머지되면 1~2분 안에 서버가 가져가 저절로 반영됩니다.

- 다른 사이트의 글꼴·스크립트·분석 도구를 넣지 않습니다. 개인정보 처리방침에 접속 기록을 남기지 않는다고 적었기 때문입니다.
- 개인정보 처리방침과 키 신청 안내는 서버의 실제 동작(위의 "접속 키", "키 요청과 승인")과 맞아야 합니다. 이 부분을 바꿀 때는 관리자에게 확인받습니다.

### 자동 반영의 구조

서버가 GitHub에서 **가져오는** 방식입니다. 네이버 클라우드 방화벽이 서버의 SSH(22번)를 밖에 열지 않으므로, GitHub에서 서버로 밀어 넣지 않습니다.

- 서버의 `site-pull.timer`(systemd)가 1분마다 `site-pull.service`를 실행하고, 그 서비스가 `site` 계정으로 `/opt/sida-kr/site-sync/site-pull.sh`를 돌립니다. 파일은 이 저장소의 `relay/site-sync/`에 있습니다.
- 스크립트는 `~site/sida-site-src`에 main의 `relay/site/`만 얕게(sparse, depth 1) 받아 두고, 매번 `git fetch`로 `relay/site` 트리가 바뀌었는지만 봅니다. 바뀌었으면 `/opt/sida-kr/site/`로 `rsync --delete` 합니다(저장소에서 지운 파일은 서버에서도 지워짐). 마지막으로 반영한 트리는 `~site/sida-site-src/.deployed-tree`에 적습니다.
- GitHub 접근은 저장소의 **읽기 전용 배포 키**(Settings → Deploy keys, "sida-kr 서버 홈페이지 가져오기")입니다. 비밀키는 서버의 `~site/.ssh/github_site`에만 있고, `~site/.ssh/config`가 github.com에 이 키를 씁니다. 저장소가 비공개여도 됩니다.
- `site` 계정은 비밀번호가 없고 sudo·docker 그룹에 없으며, `/opt/sida-kr/site/`만 그 계정 소유입니다(정부 키가 든 `relay.env`는 못 읽음). 이 계정으로 들어오는 SSH 키는 없습니다.
- 기록 보기: `journalctl -u site-pull.service -n 20` (반영하면 "반영함: …" 한 줄). 바로 반영: `systemctl start site-pull.service`. 다시 처음부터 받기: `rm -rf ~site/sida-site-src`.

### 처음 설치 (서버)

1. `compose.yaml`의 `caddy` 서비스 `volumes`에 `- ./site:/srv/site:ro`를 더하고 `docker compose up -d caddy`로 다시 만듭니다.
2. `Caddyfile`의 마지막 `handle`을 다음으로 바꾸고 `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`.

   ```
   	handle {
   		root * /srv/site
   		file_server {
   			hide .*
   		}
   	}
   ```

3. 계정과 키: `useradd -m -s /bin/bash site && passwd -l site && chown -R site:site /opt/sida-kr/site`. `site`로 `ssh-keygen -t ed25519 -N "" -f ~/.ssh/github_site`, `ssh-keyscan -t ed25519 github.com > ~/.ssh/known_hosts_github`(지문이 GitHub 공개값 `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`인지 확인), `~/.ssh/config`에 `Host github.com` / `IdentityFile ~/.ssh/github_site` / `IdentitiesOnly yes` / `UserKnownHostsFile ~/.ssh/known_hosts_github`. 공개키는 저장소 Deploy keys에 읽기 전용으로 넣습니다.
4. `relay/site-sync/`를 `/opt/sida-kr/site-sync/`에 복사(root 소유, 스크립트 755)하고, `.service`·`.timer`를 `/etc/systemd/system/`에 복사한 뒤 `systemctl daemon-reload && systemctl enable --now site-pull.timer`.
5. 확인: `/`가 200, `/health`가 `ok`, `/relay/health`가 그대로, `/아무거나`와 `/relay.env`가 404인지 봅니다.
