# 세션 화면 API (Conductor 대화, 전문가 실행, 전문가 채팅)

웹 UI 2단계 ② 세션 화면이 쓰는 JSON API입니다. 화면은 이 API에 `fetch`로 붙이면 됩니다. 로직은 `sida/engine.py`와 `sida/expert_chat.py`, 작업 관리는 `sida/session_jobs.py`, 경로는 `sida/session_api.py`에 있습니다.

## 동작 방식

- 메시지를 보내거나 전문가를 실행하면 서버는 바로 `202`와 작업(`job`)을 돌려주고, 모델 호출은 서버 안에서 따로 돕니다. 모델 호출은 몇 초에서 몇 분이 걸립니다.
- 화면은 작업이 끝날 때까지 1초마다 `GET .../session/jobs/{id}?after=<받은 마지막 seq>`를 불러 새 이벤트만 받아 그립니다. `status`가 `done`이나 `failed`가 되면 멈추고 `GET .../session`으로 화면을 새로 그립니다.
- Conductor가 대화 중에 전문가가 필요하다고 판단하면 묻지 않고 바로 실행합니다(2026-10-16 지훈 결정). 대신 화면은 아래 "알림"대로 실행을 분명히 보여 줘야 합니다.
- 전문가가 끝나면 Conductor가 결과를 보고 이어서 답하고, 필요하면 다음 전문가를 실행합니다(아래 "전문가 자동 호출"). 그래서 한 작업에 `conductor_reply`가 여러 번 올 수 있습니다.
- 한 프로젝트에서는 한 번에 작업 하나만 돕니다. 실행 중에 또 보내면 `409`입니다. 실행 중에는 입력창의 보내기 버튼을 막아 두세요.
- 작업은 서버 메모리에만 있습니다. 서버를 다시 켜면 대화 기록과 결과 문서는 그대로 있고, 돌던 작업만 사라집니다.

## API

경로 앞부분은 모두 `/api/projects/{name}`입니다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /session` | | `{messages, job, experts, proposal}` |
| `POST /session/opening` | 본문 없음 | `202 {job}`. Conductor의 첫 인사. 화면을 열었을 때 `messages`가 비어 있으면 부르세요 |
| `POST /session/messages` | `{text, context?}` | `202 {job}`. `context`는 제도판에서 고른 종이 id 목록([board-api.md](board-api.md)) |
| `POST /session/experts/{agent}/run` | 본문 없음, 또는 `{revision, context}` | `202 {job}`. 설계자가 전문가를 직접 실행. Conductor를 부르지 않음. `revision`을 주면 전문가가 지금 결과를 그 요청대로 고쳐 씀("Request revision") |
| `GET /experts/{agent}/chats` | | `{agent, name, chat, chats}`. 전문가의 분석 채팅 목록. `chats`는 `{id, messages, preview, updated_at}`이고 오래된 것부터 |
| `POST /experts/{agent}/chats` | 본문 없음 | `201 {chat}`. 빈 분석 채팅을 새로 만듦. `chat`이 `false`인 전문가는 `400` |
| `GET /experts/{agent}/chats/{chat_id}` | | `{agent, name, chat, chat_id, messages, job}`. 그 채팅의 기록. 없는 채팅은 `404` |
| `POST /experts/{agent}/chats/{chat_id}/messages` | `{text, context?}` | `202 {job}`. 그 채팅에서 전문가에게 메시지. `chat`이 `false`인 전문가는 `400`, 없는 채팅은 `404` |
| `GET /experts/{agent}/chat`, `POST /experts/{agent}/chat` | | 예전 경로. `chats/01`과 같음 |
| `GET /session/jobs/{id}` | `?after=0` | `{id, kind, agent, chat, status, running_agent, error, started_at, finished_at, events}`. `chat`은 전문가 채팅 작업이 쓰는 채팅 id(그 밖의 작업은 `null`) |
| `GET /modules/{agent}` | | `{agent, name, phase, content, updated_at}`. 전문가 결과 문서(Markdown 원문). 아직 실행 전이면 `404` |
| `GET /modules/{agent}/versions` | | `{agent, versions}`. 다시 실행이나 수정 요청 전의 결과들. `versions`는 `{id, saved_at}`이고 최신부터. `saved_at`은 그 결과를 저장한 이 PC의 시각(시간대 없음). 지금 결과는 들어 있지 않음 |
| `GET /modules/{agent}/versions/{id}` | | `{agent, id, saved_at, content}`. 이전 결과 하나. 없는 버전은 `404` |

`GET /session`의 각 항목:

- `messages`: 대화 기록. `{role, text}`이고 `role`은 `user`, `conductor`, `system`입니다. 제도판 종이를 함께 보낸 `user` 메시지에는 `context: [{id, name}]`가 더 있습니다. `system`에는 `event`와 `agent`(전문가 id), `name`(화면용 이름)이 더 있습니다.
  - `event: "module_completed"`: 전문가 실행이 끝난 자리. 대화 안에 분석 카드(Figma "Spatial Review Card")를 그리고 "View analysis"로 `GET /modules/{agent}`를 엽니다. `text`는 모델에게 보낸 내부 메모라 화면에 보이지 않습니다.
  - `event: "run_requested"`: 설계자가 직접 실행을 누른 자리.
  - `event: "read"`: Conductor가 결과 문서를 읽은 자리. 작은 안내 줄 정도면 됩니다.
  - `event: "note"`: 모델에게만 남긴 메모(예: 대지를 조회해 저장했다는 알림). `agent`가 없고 화면에 보이지 않습니다.
- `job`: 실행 중인 작업. 없으면 `null`. 화면을 새로 열었을 때 값이 있으면 그 작업을 `after=0`부터 이어서 조회하세요.
- `experts`: 우측 전문가 패널용 목록. `{id, name, phase, tier, done, updated_at, chat, chats, status, inputs}`이고 `tier`는 `core`(필수 7개) 또는 `held`(보류 3개: 개념 정리자, 공간 검토자, 시스템 자문가. 설계자가 직접 실행하거나 이름으로 부탁할 때만 돌고, Conductor가 먼저 권하거나 이어서 실행하지 않음), `chat`은 전문가 채팅이 있는지, `inputs`는 이 전문가가 읽는 다른 전문가 id 목록(config 순서), `chats`는 `GET /experts/{agent}/chats`의 `chats`와 같은 분석 채팅 목록(채팅 없는 전문가는 빈 목록), `status`는 `idle`(실행 전), `running`(실행 중), `review`(설계 상태 반영 승인을 기다림), `done`입니다.
- `proposal`: 기다리는 설계 상태 반영안 `{id, agent, diff, changes}`. `changes`는 섹션별로 바뀌는 항목입니다([state-editing.md](state-editing.md)). 없으면 `null`.

## 이벤트

`events`의 한 줄은 `{seq, kind, data}`입니다. `data.agent`는 `{id, name}`입니다.

| kind | data | 화면에서 |
|---|---|---|
| `conductor_reply` | `text, usage` | Conductor 말풍선 |
| `expert_reply` | `agent, text, usage` | 전문가 채팅의 전문가 말풍선 |
| `module_started` | `agent` | **알림**: "대지 분석가 실행을 시작합니다". 우측 패널의 해당 전문가를 실행 중으로 |
| `module_saved` | `agent, path, preview, truncated` | **알림**: "대지 분석가 결과가 나왔습니다". 분석 카드, 미리보기(`preview`) |
| `module_failed` | `agent, reason` | **알림**: 실패, 저장된 것 없음 |
| `state_proposing` | `agent` | "설계 상태에 반영할 내용을 정리하는 중" |
| `state_proposed` | `agent, proposal: {id, agent, diff, changes}` | **알림**: 검토 필요. 승인 화면(아래) |
| `state_applied` | `agent, path` | 설정이 `auto`일 때. "설계 상태에 반영했습니다" |
| `state_unchanged` | `agent` | 바뀔 내용 없음 |
| `state_failed` | `agent, reason` | 반영안을 못 만듦. 결과 문서는 저장됨 |
| `reading`, `read_failed` | `file` / `agent, reason` | 작은 안내 줄. 제도판 종이를 읽으면 `file`이 `board/<종이 id>`, `read_failed`의 `agent`가 종이 id |
| `unknown_agent`, `action_recovered` | | 작은 안내 줄 |
| `conductor_error` | `reason`, 때로 `after_run` | 오류 줄. 이 메시지는 기록되지 않았으니 다시 보내게 안내. `after_run: true`이면 전문가 결과는 저장됐고 Conductor의 이어지는 답만 실패한 것이라 다시 보내라고 하지 않음 |
| `run_skipped` | `agent, reason, limit` (`no_site`이면 `address`도) | **알림**: Conductor가 실행하려던 전문가를 실행하지 않음. `reason`은 `limit`(한 번에 실행하는 수를 채움), `state_pending`(설계 상태 반영안 검토가 먼저), `held`(보류 전문가라 다른 전문가 다음에 이어서 실행하지 않음), `no_site`(대지를 저장하기 전에 Conductor가 대지 분석가를 부름. `address`는 Conductor가 대화에서 넘긴 대지 주소, 없으면 `""`) |
| `notice` | `message` | 경고 줄(법령 검색 실패, 로컬 모델 준비 등) |
| `tray_added` | `paper` | **알림**: AI가 만든 종이(Conductor의 매스안·메모·수정안, 전문가 결과)가 제도판의 AI 섹션에 놓임. 제도판 화면이 `GET .../board`를 다시 부르면 `tray`에 있음([board-api.md](board-api.md)) |
| `tray_failed` | `reason` | Conductor가 만든 종이가 거부됨(`limit`이면 한 메시지에 3장을 넘김). Conductor가 이유를 받고 다시 하거나 설계자에게 말함 |

## 전문가 자동 호출

- Conductor는 모델의 함수 호출(tool calling)로 전문가를 부릅니다. 도구는 `run_expert`(전문가 실행)와 `read_expert_output`(완료된 결과 문서 읽기)이고(클라우드 Conductor는 제도판 종이를 읽는 `read_board`와 AI 섹션에 종이를 놓는 `propose_paper`도, [board-api.md](board-api.md)), OpenRouter·ChatGPT 구독·Ollama에서 씁니다. 함수 호출을 받지 않는 모델이나 제공자는 이전처럼 답 끝의 ```` ```action ```` 블록을 씁니다. 거부되면 그 모델은 서버를 다시 켤 때까지 블록 방식으로 돕니다.
- 대지를 아직 저장하지 않은 프로젝트에서 Conductor가 대지 분석가를 부르면 실행하지 않고 `run_skipped`(`reason: no_site`)를 보냅니다(영역 hook `run_needs`, `sida/experts/site/hooks.py`). Conductor는 대화에 나온 대지 주소를 `run_expert`의 `address`(블록 방식은 `"address"`)로 함께 넘기고, 화면은 그 주소로 찾기 탭을 엽니다. 설계자가 직접 누른 실행(`POST .../session/experts/{agent}/run`)은 막지 않습니다("대지 없이 브리프로 실행").
- 전문가가 끝나면 Conductor에게 결과를 보여 주고 이어서 답하게 합니다. 다음 전문가가 분명히 필요하면 바로 실행하고, 아니면 다음 단계를 제안하거나 설계자에게 묻습니다. 메시지 하나에 전문가는 최대 `conductor.max_expert_runs`번(기본 3) 실행합니다.
- 설계 상태 반영이 `ask`이면 반영안이 생긴 뒤에는 다음 전문가로 넘어가지 않습니다. 다음 실행이 기다리는 반영안을 덮어쓰기 때문입니다. Conductor는 반영안 검토를 권하는 답으로 끝냅니다.
- 실행이 실패하면 거기서 멈춥니다.
- 설정은 `config.yaml`의 `conductor.tool_calls`(`auto` | `off`)와 `conductor.max_expert_runs`입니다.

## 알림

Conductor가 전문가를 알아서 실행하므로, 설계자가 놓치지 않게 세 번 알립니다: `module_started`(시작), `module_saved`(결과), `state_proposed`(검토 필요). 화면 위쪽의 토스트와 우측 패널 표시를 같이 쓰는 것을 권합니다. 대화 기록에도 `module_completed` 줄이 남으므로 나중에 열어도 보입니다.

## 우측 전문가 패널

- `experts`를 전문가마다 탭(드롭다운)으로 보여 줍니다. 펼치면 `GET /modules/{agent}`의 결과 문서를 Markdown으로 그립니다. `done`이 `false`면 "아직 실행 전"과 직접 실행 버튼(`POST /session/experts/{agent}/run`)을 둡니다.
- `updated_at`을 화면이 마지막으로 연 시각(브라우저 `localStorage`)과 비교하면 "새 결과" 표시를 할 수 있습니다.

## 분석 상세와 승인 (Figma "Analysis Detail")

- 문서는 `GET /modules/{agent}`입니다.
- "Approve analysis"는 `POST /state-proposals/{proposal.id}/apply`, 건너뛰기는 `.../skip`입니다([state-editing.md](state-editing.md)). 해당 전문가의 `status`가 `review`일 때만 버튼을 켜세요.
- "Request revision"은 수정 요청을 입력받아 `POST /session/experts/{agent}/run`에 `{revision: "..."}`로 보냅니다. 채팅이 없는 전문가도 쓸 수 있습니다.

## 전문가별 화면과 채팅

2026-10-16 지훈 결정: 전문가마다 전용 화면을 두고, 그 아래에 전문가와 따로 이야기하는 채팅을 둡니다. Figma 초안 왼쪽의 "CONVERSATIONS" 목록(Main Chat 아래 전문가 대화)에 해당합니다.

- 채팅 기록은 Conductor 대화와 따로 저장됩니다. 전문가는 자기 역할, 브리프, 설계 상태, 자기 결과 문서를 보고 답합니다. 모델에게는 지금 대화하는 채팅의 기록만 보냅니다.
- 전문가마다 분석 채팅을 여러 개 둘 수 있습니다(2026-10-19 지훈 결정). 채팅 id는 `01`, `02`, … 이고 `chats/<전문가 id>/<채팅 id>.json`에 저장됩니다. 예전 버전의 `chats/<전문가 id>.json`은 옮기지 않고 그대로 `01`로 읽고 씁니다.
- `01`은 저장된 적이 없어도 목록에 항상 있습니다. 그래서 처음 여는 전문가 화면에서도 바로 말을 걸 수 있습니다. `01`이 아직 저장되지 않았을 때 "새 분석 채팅"을 누르면 `01`이 만들어지고, 그 뒤로는 `02`, `03`, … 이 생깁니다.
- 화면은 주소에 채팅 id가 없으면 가장 최근(번호가 가장 큰) 채팅을 엽니다.
- 설계자가 결과를 바꿔 달라고 하면 전문가가 무엇을 고칠지 한두 문장으로 답하고, 같은 작업 안에서 결과 문서를 다시 씁니다. 이벤트는 `expert_reply` 다음에 `module_started`, `module_saved`, `state_proposed`가 이어지고, 메인 대화에도 `module_completed` 줄이 남아 Conductor가 알게 됩니다. 채팅 기록에는 `{role: "system", event: "revised"}` 줄이 남습니다.
- 채팅 `messages`의 `role`은 `user`, `expert`, `system`입니다.
- `chat`이 `false`인 전문가는 채팅 칸을 숨기고 전용 화면과 수정 요청 버튼만 둡니다. 지금은 대지 분석가만 꺼져 있습니다. 결과가 정부 데이터에서 온 사실이라, 바꿀 일은 대지 조회 화면에서 합니다. 끄고 켜는 것은 `config.yaml`의 전문가 항목 `chat: false`입니다.
- 작업은 메인 대화와 같은 줄을 씁니다. 한 프로젝트에서 메인 대화든 전문가 채팅이든 작업 하나만 돌고, 작업 조회도 같은 `GET /session/jobs/{id}`입니다.

## 예시

```js
async function send(project, text) {
  const base = `/api/projects/${encodeURIComponent(project)}`;
  const res = await fetch(`${base}/session/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (res.status === 409) return alert("이전 작업이 아직 실행 중입니다.");
  let { job } = await res.json();
  let seen = 0;
  while (job.status === "running") {
    await new Promise((r) => setTimeout(r, 1000));
    job = await (await fetch(`${base}/session/jobs/${job.id}?after=${seen}`)).json();
    for (const event of job.events) {
      showEvent(event); // 위 표대로 그리기
      seen = event.seq;
    }
  }
  render(await (await fetch(`${base}/session`)).json());
}
```

## 오류

오류 응답은 `{detail: "메시지"}`입니다. 400은 빈 메시지, 없는 전문가, 채팅이 꺼진 전문가에게 보낸 메시지, 404는 프로젝트·작업·결과 문서 없음, 409는 실행 중인 작업이 있음, 422는 요청 형식 오류입니다. 모델 오류는 HTTP 오류가 아니라 작업의 `status: "failed"`와 `error`로 옵니다.
