# 사용 기록 수집 (telemetry)

Sida는 디자이너 각자의 PC에서 돌기 때문에, 팀이 사용 현황을 보려면 앱이 기록을 보내야 합니다. 이 기능은 **기본으로 꺼져 있고**, PC마다 설정 화면에서 켭니다(`config.local.yaml`에 저장).

## 흐름

1. Sida 코어(`sida/engine.py`)가 일이 생길 때 내는 이벤트(전문가 실행, 컨덕터 오류, state 반영)와 대지·법령 조회 실패, 디자이너가 누른 평가를 `sida/telemetry.py`가 짧은 기록으로 바꿉니다.
2. 기록은 PC의 `~/Sida/telemetry/queue.jsonl`에 쌓입니다. 인터넷이 끊겨도 잃지 않고, 5,000개를 넘으면 오래된 것부터 버립니다.
3. 웹 서버(`python webapp.py`)가 켜져 있는 동안 5분마다 100개씩 묶어 `telemetry.endpoint`(기본 `https://sida-data.duckdns.org/api/v1/events`)로 보냅니다. 보내지 못하면 다음에 다시 보냅니다. 앱 사용에는 영향이 없습니다.
4. 팀 VPS의 수집 서버(`collector/`)가 모양과 크기를 검사해 Postgres `events` 표에 넣습니다. 그 서버에는 기록을 읽어 가는 경로가 없습니다.

## 보내는 것

| 종류 (`kind`) | 내용 |
|---|---|
| `job` | 작업 종류(opening, message, expert, expert_chat), 전문가 id, 성공 여부, 걸린 초, 오류 종류, 컨덕터·워커 모델 이름 |
| `expert_run` | 전문가 id, 성공 여부, 걸린 초, 오류 종류 |
| `conductor_error` | 오류 종류 |
| `state_update` | 전문가 id, 결과(proposed, applied, unchanged, failed) |
| `unknown_agent` | 컨덕터가 부른 없는 전문가 이름 |
| `feedback` | 전문가 id, 평가(`up`, `down`), 디자이너가 직접 쓴 의견 |
| `failure` | 실패한 조회 단계(예: `site:search_parcels`, `law:search`)와 실패 종류 |

모든 요청에는 설치 ID(PC마다 무작위로 만든 값, `~/Sida/telemetry/install_id`), Sida 버전, OS 이름이 붙습니다.

**보내지 않는 것:** 브리프, 전문가가 만든 문서, project_state, 프로젝트 이름, 오류 원문. 오류는 원문 대신 정해진 종류(`timeout`, `rate_limit`, `auth`, `network`, `empty_reply`, `server`, `other`)만 보냅니다. 원문에는 API 키나 주소가 섞일 수 있기 때문입니다.

**따로 동의해야 보내는 것:** 실패한 조회의 입력(검색한 주소, 법령 질문). `telemetry.share_failure_inputs`를 켠 PC에서만 `failure` 기록에 `inputs`로 붙습니다.

수집을 끄면 PC에 남아 있던 기록도 지웁니다. 입력 공유만 끄면 남은 기록에서 입력만 지웁니다.

## 설정 (config.yaml / config.local.yaml)

```yaml
telemetry:
  enabled: false
  share_failure_inputs: false
  endpoint: https://sida-data.duckdns.org/api/v1/events
```

## 화면용 JSON API

### 설정: `GET/PUT /api/settings`

응답에 두 값이 더해졌습니다. 바꿀 때는 `PUT /api/settings`에 같은 이름으로 보냅니다(`true`/`false`).

| 필드 | 뜻 |
|---|---|
| `telemetry_enabled` | 사용 기록 보내기 |
| `telemetry_share_inputs` | 실패한 조회의 주소·질문도 보내기 |

### 평가: `POST /api/projects/{name}/experts/{agent}/feedback`

```json
{"rating": "down", "comment": "면적이 대장과 달라요"}
```

- `rating`: `up` 또는 `down` (필수), `comment`: 1,000자까지 (선택)
- 응답: `{"recorded": true}`. 이 PC가 수집을 꺼 두었으면 `{"recorded": false}`이니, 화면은 "설정에서 사용 기록 보내기를 켜면 팀에 전달돼요" 같은 안내를 보여 주면 됩니다.
- 잘못된 평가·긴 의견은 400, 없는 프로젝트·전문가는 404

## 수집 서버

코드는 `collector/`에 있고, 설치 방법은 [`collector/README.md`](../collector/README.md)에 있습니다. 로컬 앱 패키지(`sida`)에는 들어가지 않습니다.
