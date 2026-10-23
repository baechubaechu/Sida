# 웹 화면 (webui/app)

`python webapp.py`(Windows는 `run.bat`)로 서버를 켜면 열리는 첫 화면(`http://127.0.0.1:8765/`)입니다. 팀원이 Figma 초안으로 만든 목업(PR #39)을 서버의 JSON API에 연결했습니다. 화면은 순수 HTML/CSS/JS이고 빌드 과정이 없습니다. 프로젝트와 대화는 브라우저가 아니라 이 PC의 `projects/` 폴더에 저장됩니다.

이전 서버 렌더링 화면(프로젝트 허브와 프로젝트 페이지)은 `/classic`에 남아 있습니다. 정부 API 키(브이월드, 공공데이터포털, 법제처) 입력처럼 새 화면에 아직 없는 것은 그쪽을 씁니다.

## 파일

| 파일 | 내용 |
|---|---|
| `webui/app/index.html` | 뼈대, 설정 창 |
| `webui/app/app.js` | 화면 그리기, API 호출, 작업 진행 따라가기 |
| `webui/app/model.js` | DOM과 `fetch`를 쓰지 않는 도우미 함수(검색·정렬, 대화 항목, 이벤트 알림 문구, Markdown). `tests/webui/model.test.mjs`가 확인합니다 |
| `webui/app/styles.css` | Figma v0.1 토큰과 화면 스타일 |

서버는 `/`에서 `index.html`을, `/app/...`에서 나머지 파일을 내보냅니다. 브라우저가 매번 새 파일인지 확인하므로(`Cache-Control: no-cache`) `git pull` 뒤 새로고침하면 바로 바뀝니다.

## 화면과 API

| 화면 | 쓰는 API |
|---|---|
| 프로젝트 목록 (`#/`) | `GET /api/projects`, 예시 프로젝트 `POST /api/projects/sample` |
| 새 프로젝트 (`#/new`) | `POST /api/projects` (`name`, `fields.type`·`site`·`intention`) |
| Conductor 대화 (`#/project/<이름>`) | `GET .../session`, 첫 인사 `POST .../session/opening`, 메시지 `POST .../session/messages`, 진행 `GET .../session/jobs/{id}` |
| 전문가 패널과 화면 (`#/project/<이름>/expert/<id>`, 분석 채팅을 고르면 `.../expert/<id>/chat/<채팅 id>`) | 결과 문서 `GET .../modules/{agent}`, 실행·수정 요청 `POST .../session/experts/{agent}/run`, 분석 채팅 목록과 새 채팅 `GET`/`POST .../experts/{agent}/chats`, 채팅 `GET .../experts/{agent}/chats/{chat_id}`, 메시지 `POST .../chats/{chat_id}/messages` |
| 설계 상태 반영 승인 | `POST .../state-proposals/{id}/apply`, `.../skip` |
| 설정 창 | `GET`/`PUT /api/settings`, `PUT /api/settings/keys/openrouter`, ChatGPT 로그인 `/api/settings/chatgpt...` |

API의 자세한 내용은 [session-api.md](session-api.md), [state-editing.md](state-editing.md), [settings-api.md](settings-api.md), [chatgpt-login.md](chatgpt-login.md)에 있습니다.

## 동작

- Conductor 대화는 프로젝트마다 하나입니다. 대화가 비어 있으면 화면을 열 때 Conductor가 먼저 인사합니다.
- 메시지를 보내면 작업이 끝날 때까지 1초마다 진행을 받아 그립니다. 그동안 보내기 버튼은 꺼집니다(한 프로젝트에 작업 하나).
- Conductor나 설계자가 전문가를 실행하면 화면 오른쪽 아래 알림이 시작, 결과, 검토 필요를 알리고, 대화에 분석 카드가 남습니다. 카드나 전문가 패널을 누르면 그 전문가 화면이 열립니다.
- 오른쪽 전문가 패널에서 전문가를 펼치면 "결과 문서 보기", "＋ 새 분석 채팅", 분석 채팅 목록("분석 01 · 첫 질문")이 나옵니다. 펼친 상태는 화면을 다시 그려도 유지됩니다.
- 전문가 화면에는 결과 문서, 설계 상태 반영안(반영하기·건너뛰기), 다시 실행, 수정 요청, 분석 채팅 고르기와 새 분석 채팅, 전문가 채팅이 있습니다. 대지 분석가는 채팅이 없고 수정 요청만 있습니다.
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
