# 제도판 API (디자인 워크스페이스)

가운데 디자인 화면(제도판)이 쓰는 JSON API입니다. 제도판 위의 종이(대지, 매스안, 메모, 트레이싱지)를 프로젝트 폴더의 `board.json`에 저장하고, 설계자가 고른 종이를 Conductor와 전문가에게 함께 보냅니다. 로직은 `sida/board.py`, 경로는 `sida/board_api.py`에 있습니다. 화면 시험판은 `proto/drafting-table` 브랜치의 `prototypes/drafting-table/`입니다.

## 종이

제도판 하나는 `{rev, papers, pins}`입니다. `rev`는 저장할 때마다 1씩 오릅니다. 종이는 모두 `id`, `kind`, 위치 `x`, `y`(제도판 좌표, m), 크기 `w`, `h`를 가집니다. 서버는 위치와 크기를 그대로 저장하기만 합니다.

| kind | 더 가지는 것 | 누가 놓나 |
|---|---|---|
| `site` | 없음(내용은 대지 사실에서 옴) | 서버. 처음부터 있고 지울 수 없으며 옮기기만 됨. id는 `site` |
| `mass` | `title`, `blocks`(동 목록: `u`, `v` 위치, `w`·`d` 가로·세로 m, `floors` 층수 1~200, 1~20개), `floor_height`(기본 4.2m) | 설계자 |
| `note` | `text`(4000자까지) | 설계자 |
| `tracing` | `title`, `strokes`(펜 획: `[[x, y], ...]` 목록), `overlaid`(대지 위에 덮였는지) | 설계자 |

`pins`는 다음 단계(전문가 결과 종이와 핀)에서 씁니다. 지금은 빈 목록입니다.

## API

경로 앞부분은 모두 `/api/projects/{name}/board`입니다.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET` | | `{rev, papers, pins}`. 아직 저장한 적 없으면 대지 종이 하나와 `rev: 0` |
| `POST /papers` | 종이(`kind`는 `mass`·`note`·`tracing`, `id`는 없으면 서버가 만듦) | `201 {paper, rev}` |
| `PATCH /papers/{id}` | 바꿀 필드만. `id`·`kind`는 무시 | `{paper, rev}`. 대지 종이는 `x`·`y`·`w`·`h`만 |
| `DELETE /papers/{id}` | | `{rev}`. 대지 종이는 `400` |
| `GET /context?ids=a,b` | 고른 종이 id(쉼표로) | `{mode, papers, conductor, expert}`. 모델에게 실제로 가는 글. 화면에서 "AI에게 보이는 내용"을 보여 줄 때 |

종이는 하나씩 저장합니다. 설계자와 AI가 같은 제도판에 쓰기 때문에 통째로 덮어쓰면 다른 쪽이 놓은 종이가 사라집니다. 끌어서 옮길 때는 끌기가 끝날 때 `PATCH`를 한 번 부르세요.

## 고른 종이를 대화에 보내기

Shift+클릭으로 고른 종이의 id를 `context`로 보냅니다. 한 번에 8장까지입니다.

- `POST /api/projects/{name}/session/messages` `{text, context: ["mass-a", "n1"]}`
- `POST .../session/experts/{agent}/run` `{revision?, context}`
- `POST .../experts/{agent}/chats/{chat_id}/messages` `{text, context}`

없는 종이 id는 `400`입니다. 대화 기록에는 종이 이름만 남고, `GET .../session`의 그 메시지에 `context: [{id, name}]`가 붙어 옵니다(전문가 채팅 기록도 같음). 화면은 이것으로 말풍선 위에 칩을 그립니다.

## Conductor와 전문가가 받는 것

Conductor가 받는 양은 Conductor가 어디에 연결됐는지에 따라 정해집니다(2026-10-26 지훈 결정). `config.yaml`의 `conductor.board_context`로 바꿀 수 있습니다.

| `board_context` | Conductor | 전문가 |
|---|---|---|
| `auto`(기본) | ChatGPT 구독·OpenRouter면 `full`, Ollama면 `names` | 고른 종이 전부 |
| `full` | 제도판 종이 목록 + 고른 종이 전부 + `read_board` 도구(id로 종이 하나를 읽음) | 고른 종이 전부 |
| `names` | 대화 기록의 종이 이름 한 줄뿐 | 고른 종이 전부 |

- 매스안의 건축면적·연면적·최고 높이·건폐율·용적률은 서버가 동 목록과 대지 사실의 합계 면적으로 계산합니다. 화면이 계산한 값은 쓰지 않습니다. 필지 면적을 하나라도 모르면 건폐율·용적률은 내지 않습니다("미확인"). 건축면적은 동 면적의 합이라 동이 겹치면 실제보다 큽니다.
- 트레이싱지 그림은 글로 읽을 수 없어서 획 수와 덮였는지만 갑니다.
- 제도판을 한 번도 저장하지 않은 프로젝트는 아무것도 더하지 않습니다.
- Conductor가 `read_board`로 종이를 읽으면 작업 이벤트 `reading`의 `file`이 `board/<종이 id>`로 옵니다.

## 오류

`{detail: "메시지"}`입니다. 400은 잘못된 종이(kind, 숫자, 층수, 글 길이), 대지 종이를 지우거나 내용을 바꾸려 할 때, 없는 종이를 `context`로 보낼 때, 404는 프로젝트나 종이가 없을 때입니다.
