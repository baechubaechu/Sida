# 웹 화면 (webui/app)

`python webapp.py`(Windows는 `run.bat`)로 서버를 켜면 열리는 첫 화면(`http://127.0.0.1:8765/`)입니다. 팀원이 Figma 초안으로 만든 목업(PR #39)을 서버의 JSON API에 연결했습니다. 화면은 순수 HTML/CSS/JS이고 빌드 과정이 없습니다. 프로젝트와 대화는 브라우저가 아니라 이 PC의 `projects/` 폴더에 저장됩니다.

예전 서버 렌더링 화면(`/classic` 허브와 `/p/<프로젝트>` 페이지)은 2026-10-23에 없앴습니다. 서버가 템플릿(`webui/templates`, `webui/static`)으로 그리는 화면은 ChatGPT 로그인 결과 페이지 하나만 남았습니다.

## 파일

| 파일 | 내용 |
|---|---|
| `webui/app/index.html` | 뼈대, 설정 창 |
| `webui/app/app.js` | 화면 그리기, API 호출, 작업 진행 따라가기 |
| `webui/app/model.js` | DOM과 `fetch`를 쓰지 않는 도우미 함수(검색·정렬, 대화 항목, 이벤트 알림 문구, Markdown, 저장할 정부 데이터 키, 화면 주소, 전문가별 결과 배치 `EXPERT_LAYOUTS`). `tests/webui/model.test.mjs`가 확인합니다 |
| `webui/app/styles.css` | Figma v0.1 토큰과 화면 스타일 |

서버는 `/`에서 `index.html`을, `/app/...`에서 나머지 파일을 내보냅니다. 브라우저가 매번 새 파일인지 확인하므로(`Cache-Control: no-cache`) `git pull` 뒤 새로고침하면 바로 바뀝니다.

## 화면과 API

| 화면 | 쓰는 API |
|---|---|
| 프로젝트 목록 (`#/`) | `GET /api/projects`, 예시 프로젝트 `POST /api/projects/sample` |
| 새 프로젝트 (`#/new`) | `POST /api/projects` (`name`, `fields.type`·`site`·`intention`) |
| Conductor 대화 (`#/project/<이름>`) | `GET .../session`, 첫 인사 `POST .../session/opening`, 메시지 `POST .../session/messages`, 진행 `GET .../session/jobs/{id}` |
| 전문가 페이지 (`#/project/<이름>/expert/<id>` 결과, `.../chat/<채팅 id>` 분석 채팅, `.../versions/<버전 id>` 이전 버전) | 결과 문서 `GET .../modules/{agent}`, 이전 버전 `GET .../modules/{agent}/versions`, `.../versions/{id}`, 실행·수정 요청 `POST .../session/experts/{agent}/run`, 분석 채팅 목록과 새 채팅 `GET`/`POST .../experts/{agent}/chats`, 채팅 `GET .../experts/{agent}/chats/{chat_id}`, 메시지 `POST .../chats/{chat_id}/messages`, 평가 `POST .../experts/{agent}/feedback` |
| 대지 페이지 (`#/project/<이름>/site` 대지 사실, `.../site/find` 찾기) | 대지 사실 `GET .../site`, 지역 목록 `GET /api/site/regions`, 지번으로 찾기 `GET /api/site/lots`, 주소로 찾기 `POST .../site/parcels`, 조회해 저장 `PUT .../site`, 브리프의 대지 주소 `GET /api/projects/{name}` |
| 설계 상태 반영 승인 | `POST .../state-proposals/{id}/apply`, `.../skip` |
| 설정 창 | `GET`/`PUT /api/settings`, 키 `PUT /api/settings/keys/{openrouter·vworld·vworld_domain·data_go_kr·law}`, ChatGPT 로그인 `/api/settings/chatgpt...` |

API의 자세한 내용은 [session-api.md](session-api.md), [site-ordinance.md](site-ordinance.md), [state-editing.md](state-editing.md), [settings-api.md](settings-api.md), [chatgpt-login.md](chatgpt-login.md)에 있습니다.

## 동작

- Conductor 대화는 프로젝트마다 하나입니다. 대화가 비어 있으면 화면을 열 때 Conductor가 먼저 인사합니다.
- 메시지를 보내면 작업이 끝날 때까지 1초마다 진행을 받아 그립니다. 그동안 보내기 버튼은 꺼집니다(한 프로젝트에 작업 하나).
- Conductor나 설계자가 전문가를 실행하면 화면 오른쪽 아래 알림이 시작, 결과, 검토 필요를 알리고, 대화에 분석 카드가 남습니다. 카드나 전문가 패널을 누르면 그 전문가 화면이 열립니다.
- 오른쪽 전문가 패널에서 전문가를 펼치면 "결과 문서 보기", "＋ 새 분석 채팅", 분석 채팅 목록("분석 01 · 첫 질문")이 나옵니다. 펼친 상태는 화면을 다시 그려도 유지됩니다.
- 전문가를 열면 Conductor 대화는 왼쪽에 그대로 있고 오른쪽 반쪽이 그 전문가의 페이지가 됩니다. 가운데 줄을 끌어 너비를 바꿉니다.
- 전문가 페이지에는 탭 세 개(결과, 분석 채팅, 이전 버전)와 검토 영역(실행·다시 실행, 수정 요청, 평가)이 있습니다. 페이지가 넓으면 검토 영역이 오른쪽 열로, 좁으면 탭 아래 한 줄로 갑니다. 대지 분석가는 채팅 탭이 없고 수정 요청만 있습니다.
- 결과 탭은 전문가마다 다르게 배치합니다. 결과 문서의 `## 제목` 섹션을 잘라 카드, 표, 배지(확실/아마/확인, 브리프/후보/가정 등), 체크리스트, 순서 목록, 접는 문답으로 보여 줍니다. 배치는 `model.js`의 `EXPERT_LAYOUTS` 표 하나에 있어 그 표만 고치면 바뀝니다. 표에 없는 섹션은 끝에 그대로 붙고, 섹션을 하나도 못 찾으면 문서를 그대로 보여 줍니다. "원문 보기"를 펼치면 Markdown 원문이 나옵니다. 설계 상태 반영안(반영하기·건너뛰기)도 결과 탭 맨 위에 나옵니다.
- 결과 탭 위의 "읽은 전문가"(config `inputs`)와 아래 "다음 전문가"(문서의 Handoff)는 그 전문가 페이지로 가는 링크입니다.
- 오른쪽 패널 맨 위의 "대지 사실"을 누르면 전문가 페이지와 같은 자리에 대지 페이지가 열립니다. 대지 사실은 한 전문가의 결과가 아니라 대지 분석가와 법규 검토자가 함께 읽는 프로젝트 자료라서 전문가 페이지와 따로 둡니다.
- 대지 페이지의 "찾기" 탭은 시·도 → 시·군·구 → 읍·면·동(→ 리)을 고르고 지번을 넣는 방식이 기본이고, "주소 붙여넣기"로 글자 검색도 합니다. 새 프로젝트를 만들 때 적은 대지 주소가 있으면 글자 검색 칸에 미리 들어갑니다. 찾은 필지를 여러 개 고르면(다른 지번을 찾아 더 고를 수도 있음) 하나의 대지로 조회해 저장합니다.
- "대지 사실" 탭은 저장된 값을 그대로 보여 줍니다(대지 개요, 용도지역과 법정 건폐율·용적률, 확인 필요, 지역·지구, 도시계획 도로, 필지, 기존 건축물, 건축제한 근거 조문, 미확인). 가져오지 못한 항목은 추정하지 않고 "미확인"으로 둡니다. 맨 아래에서 전문가가 받는 대지 사실 원문을 펼쳐 볼 수 있습니다.
- 대지 분석가와 법규 검토자 페이지의 결과 탭 위에는 어떤 대지로 실행되는지(조회 전이면 브리프만으로 실행된다는 안내)가 나옵니다.
- 정부 데이터 키가 없거나 거부되면(503) 오류 문구 옆에 설정 열기 버튼이 나옵니다.
- 계획 용도, 조례 조문, 지도는 아직 화면이 없습니다(서버 API는 있음).
- 체크리스트의 체크는 지금은 화면에만 남고 프로젝트에 저장되지 않습니다(새로고침하면 사라짐). 저장은 다음 작업입니다.
- 평가(도움 됨/아쉬움, 한 줄 의견)는 설정의 "사용 기록 보내기"가 켜져 있을 때만 전달됩니다(`docs/telemetry.md`).
- 처음 실행(`config.local.yaml` 없음)이면 설정 창이 먼저 뜹니다. 저장을 누르면 다음부터는 뜨지 않습니다.
- 설정 창에서 Conductor를 "ChatGPT 구독"으로 고르면 로그인 버튼이 나옵니다. 새 창에서 로그인을 마치고 돌아오면 상태와 모델 목록이 바뀝니다.

## 목업에서 뺀 것

- 프로젝트 삭제, 파일 첨부: 서버 API가 없어서 뺐습니다.
- 메인 채팅 여러 개: Conductor 대화는 프로젝트당 하나로 정했습니다(2026-10-19).
- Vercel 배포 설정: Sida는 각자 PC에서 돌리므로 쓰지 않습니다(2026-10-19 결정).

## 고칠 때

- 로직은 코어와 JSON API에 두고, 화면은 그 결과를 그리기만 합니다.
- 서버나 설계자에게서 온 글은 모두 `escapeHtml`을 거쳐 HTML이 됩니다. `innerHTML`에 넣는 값은 이 규칙을 지켜 주세요.
- 화면이 부르는 `/api/...` 경로는 `tests/test_webapp.py`가 실제 경로와 맞는지 확인합니다. API 경로를 바꾸면 화면도 같이 고치세요.
