# 세션 화면 API (Conductor 대화, 전문가 실행)

웹 UI 2단계 ② 세션 화면이 쓰는 JSON API입니다. 화면은 이 API에 `fetch`로 붙이면 됩니다. 로직은 `sida/engine.py`, 작업 관리는 `sida/session_jobs.py`, 경로는 `sida/session_api.py`에 있습니다.

## 동작 방식

- 메시지를 보내거나 전문가를 실행하면 서버는 바로 `202`와 작업(`job`)을 돌려주고, 모델 호출은 서버 안에서 따로 돕니다. 모델 호출은 몇 초에서 몇 분이 걸립니다.
- 화면은 작업이 끝날 때까지 1초마다 `GET .../session/jobs/{id}?after=<받은 마지막 seq>`를 불러 새 이벤트만 받아 그립니다. `status`가 `done`이나 `failed`가 되면 멈추고 `GET .../session`으로 화면을 새로 그립니다.
- Conductor가 대화 중에 전문가가 필요하다고 판단하면 묻지 않고 바로 실행합니다(2026-10-16 지훈 결정). 대신 화면은 아래 "알림"대로 실행을 분명히 보여 줘야 합니다.
- 한 프로젝트에서는 한 번에 작업 하나만 돕니다. 실행 중에 또 보내면 `409`입니다. 실행 중에는 입력창의 보내기 버튼을 막아 두세요.
- 작업은 서버 메모리에만 있습니다. 서버를 다시 켜면 대화 기록과 결과 문서는 그대로 있고, 돌던 작업만 사라집니다.

## API

경로 앞부분은 모두 `/api/projects/{name}`입니다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /session` | | `{messages, job, experts, proposal}` |
| `POST /session/opening` | 본문 없음 | `202 {job}`. Conductor의 첫 인사. 화면을 열었을 때 `messages`가 비어 있으면 부르세요 |
| `POST /session/messages` | `{text}` | `202 {job}` |
| `POST /session/experts/{agent}/run` | 본문 없음 | `202 {job}`. 설계자가 전문가를 직접 실행(CLI의 `/run`). Conductor를 부르지 않음 |
| `GET /session/jobs/{id}` | `?after=0` | `{id, kind, agent, status, running_agent, error, started_at, finished_at, events}` |
| `GET /modules/{agent}` | | `{agent, name, phase, content, updated_at}`. 전문가 결과 문서(Markdown 원문). 아직 실행 전이면 `404` |

`GET /session`의 각 항목:

- `messages`: 대화 기록. `{role, text}`이고 `role`은 `user`, `conductor`, `system`입니다. `system`에는 `event`와 `agent`(전문가 id), `name`(화면용 이름)이 더 있습니다.
  - `event: "module_completed"`: 전문가 실행이 끝난 자리. 대화 안에 분석 카드(Figma "Spatial Review Card")를 그리고 "View analysis"로 `GET /modules/{agent}`를 엽니다. `text`는 모델에게 보낸 내부 메모라 화면에 보이지 않습니다.
  - `event: "run_requested"`: 설계자가 직접 실행을 누른 자리.
  - `event: "read"`: Conductor가 결과 문서를 읽은 자리. 작은 안내 줄 정도면 됩니다.
- `job`: 실행 중인 작업. 없으면 `null`. 화면을 새로 열었을 때 값이 있으면 그 작업을 `after=0`부터 이어서 조회하세요.
- `experts`: 우측 전문가 패널용 목록. `{id, name, phase, done, updated_at, status}`이고 `status`는 `idle`(실행 전), `running`(실행 중), `review`(설계 상태 반영 승인을 기다림), `done`입니다.
- `proposal`: 기다리는 설계 상태 반영안 `{id, agent, diff}`. 없으면 `null`.

## 이벤트

`events`의 한 줄은 `{seq, kind, data}`입니다. `data.agent`는 `{id, name}`입니다.

| kind | data | 화면에서 |
|---|---|---|
| `conductor_reply` | `text, usage` | Conductor 말풍선 |
| `module_started` | `agent` | **알림**: "대지 분석가 실행을 시작합니다". 우측 패널의 해당 전문가를 실행 중으로 |
| `module_saved` | `agent, path, preview, truncated` | **알림**: "대지 분석가 결과가 나왔습니다". 분석 카드, 미리보기(`preview`) |
| `module_failed` | `agent, reason` | **알림**: 실패, 저장된 것 없음 |
| `state_proposing` | `agent` | "설계 상태에 반영할 내용을 정리하는 중" |
| `state_proposed` | `agent, proposal: {id, agent, diff}` | **알림**: 검토 필요. 승인 화면(아래) |
| `state_applied` | `agent, path` | 설정이 `auto`일 때. "설계 상태에 반영했습니다" |
| `state_unchanged` | `agent` | 바뀔 내용 없음 |
| `state_failed` | `agent, reason` | 반영안을 못 만듦. 결과 문서는 저장됨 |
| `reading`, `read_failed` | `file` / `agent, reason` | 작은 안내 줄 |
| `unknown_agent`, `action_recovered` | | 작은 안내 줄 |
| `conductor_error` | `reason` | 오류 줄. 이 메시지는 기록되지 않았으니 다시 보내게 안내 |
| `notice` | `message` | 경고 줄(법령 검색 실패, 로컬 모델 준비 등) |

## 알림

Conductor가 전문가를 알아서 실행하므로, 설계자가 놓치지 않게 세 번 알립니다: `module_started`(시작), `module_saved`(결과), `state_proposed`(검토 필요). 화면 위쪽의 토스트와 우측 패널 표시를 같이 쓰는 것을 권합니다. 대화 기록에도 `module_completed` 줄이 남으므로 나중에 열어도 보입니다.

## 우측 전문가 패널

- `experts`를 전문가마다 탭(드롭다운)으로 보여 줍니다. 펼치면 `GET /modules/{agent}`의 결과 문서를 Markdown으로 그립니다. `done`이 `false`면 "아직 실행 전"과 직접 실행 버튼(`POST /session/experts/{agent}/run`)을 둡니다.
- `updated_at`을 화면이 마지막으로 연 시각(브라우저 `localStorage`)과 비교하면 "새 결과" 표시를 할 수 있습니다.

## 분석 상세와 승인 (Figma "Analysis Detail")

- 문서는 `GET /modules/{agent}`입니다.
- "Approve analysis"는 `POST /state-proposals/{proposal.id}/apply`, 건너뛰기는 `.../skip`입니다([state-editing.md](state-editing.md)). 해당 전문가의 `status`가 `review`일 때만 버튼을 켜세요.
- "Request revision"과 전문가별 채팅은 다음 작업입니다(아래).

## 다음: 전문가별 화면과 채팅

2026-10-16 지훈 결정: 전문가마다 전용 화면을 두고, 그 아래에 전문가와 따로 이야기하는 채팅 세션을 둡니다. 대화가 필요 없는 전문가는 채팅을 두지 않습니다. 메인 Conductor 대화와는 기록을 따로 저장합니다. 이 API는 다음 PR에서 추가합니다.

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

오류 응답은 `{detail: "메시지"}`입니다. 400은 빈 메시지나 없는 전문가, 404는 프로젝트·작업·결과 문서 없음, 409는 실행 중인 작업이 있음, 422는 요청 형식 오류입니다. 모델 오류는 HTTP 오류가 아니라 작업의 `status: "failed"`와 `error`로 옵니다.
