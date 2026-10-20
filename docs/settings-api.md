# 설정 API (실행 모드, 법령 검색, 설계 상태 반영, API 키)

웹 UI 2단계 ④ 설정 화면이 쓰는 JSON API입니다. 화면은 이 API에 `fetch`로 붙이면 됩니다. 로직은 `sida/settings.py`, 경로는 `sida/settings_api.py`에 있습니다.

## 동작 방식

- 설정은 이 PC의 `config.local.yaml`에만 씁니다. 팀 공통 기본값인 `config.yaml`은 바꾸지 않습니다.
- API 키는 저장소 최상위의 `.env`에 씁니다. 응답에는 키 값이 들어가지 않고, 들어 있는지(`set`)와 끝 네 자리(`hint`)만 들어갑니다.
- 저장하면 바로 적용됩니다. 서버를 다시 켤 필요가 없습니다.
- **첫 실행**: `config.local.yaml`이 아직 없으면 `first_run`이 `true`입니다. 화면은 이때 설정 화면을 먼저 띄우고, 설계자가 "저장"을 누르면 `PUT /api/settings`를 부르세요. 바꾼 것이 없어도(`{}`) 파일이 만들어져 다음부터 `first_run`이 `false`가 됩니다.

## API

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/settings` | | 지금 설정(아래) |
| `PUT /api/settings` | 바꿀 항목만 담은 객체 | 저장한 뒤의 설정(`GET`과 같은 모양) |
| `PUT /api/settings/keys/{key}` | `{value}` | `{key, env, set, hint, verified}` |

### `GET /api/settings`의 항목

| 항목 | 뜻 |
|---|---|
| `first_run` | `config.local.yaml`이 없으면 `true` |
| `mode` | `cloud`(OpenRouter), `local`(Ollama), `custom`(Conductor와 워커가 서로 다름) |
| `local_profile` | 로컬 모드에서 쓸 프로필. `options.local_profiles` 중 하나 |
| `conductor`, `worker` | `{provider, model}`. 실제로 쓰일 제공자와 모델(프로필 반영 후) |
| `rag_enabled` | 법령 검색(법제처) 켜짐 여부 |
| `state_update` | 전문가 결과를 설계 상태에 반영하는 방식. `ask`(승인 받기), `auto`(바로 반영), `off`(안 함) |
| `gpu` | 감지한 GPU `{name, vram_gb, recommended_profile}`. NVIDIA가 아니거나 없으면 `null`. `recommended_profile`이 `null`이면 클라우드를 권합니다 |
| `keys` | 키마다 `{env, set, hint}`. `vworld_domain`만 비밀값이 아니라 `hint` 대신 `value`가 옵니다 |
| `warnings` | `openrouter_key_missing`(클라우드를 쓰는데 OpenRouter 키 없음), `rag_key_missing`(법령 검색을 켰는데 법제처 인증값 없음), `chatgpt_signed_out`(Conductor가 ChatGPT 구독인데 로그인 안 됨) |
| `chatgpt` | ChatGPT 구독 로그인 상태와 Conductor 모델 `{signed_in, email, plan_usage, registered, model}`. [chatgpt-login.md](chatgpt-login.md) |
| `options` | 화면의 선택지: `modes`, `providers`, `conductor_providers`(Conductor용, `chatgpt` 포함), `local_profiles`, `state_update` |

### `PUT /api/settings`에 넣을 수 있는 항목

모두 생략할 수 있고, 준 것만 바뀝니다.

| 항목 | 값 |
|---|---|
| `mode` | `cloud` 또는 `local`. Conductor와 워커를 함께 바꿉니다 |
| `local_profile` | `options.local_profiles` 중 하나 |
| `conductor_provider`, `worker_provider` | `openrouter` 또는 `ollama`. 한 역할만 바꿉니다(고급 설정). `mode`와 같이 주면 `mode`를 먼저 적용합니다. Conductor는 `chatgpt`(ChatGPT 구독)도 됩니다 |
| `chatgpt_model` | Conductor가 ChatGPT 구독에서 쓸 모델. [chatgpt-login.md](chatgpt-login.md) |
| `rag_enabled` | `true` 또는 `false` |
| `state_update` | `ask`, `auto`, `off` |

선택지에 없는 값이면 `400`이고 아무것도 저장하지 않습니다. 모르는 항목을 보내면 `422`입니다.

### API 키

| `{key}` | `.env` 이름 | 쓰는 곳 |
|---|---|---|
| `openrouter` | `OPENROUTER_API_KEY` | 클라우드 모드의 모델 |
| `openai` | `OPENAI_API_KEY` | Rhino 모델링 |
| `vworld` | `VWORLD_API_KEY` | 대지 조회, 지도 |
| `vworld_domain` | `VWORLD_DOMAIN` | 브이월드 키를 받을 때 등록한 주소(보통 `http://localhost:8765`) |
| `data_go_kr` | `DATA_GO_KR_API_KEY` | 건축물대장, 행위제한, 근거 조문 |
| `law` | `LAW_OPEN_API_OC` | 법령 검색, 조례 |

- OpenRouter와 OpenAI 키는 저장하기 전에 그 서비스에 확인합니다. 거부되면 `400`이고 저장하지 않습니다. 확인한 키는 응답의 `verified`가 `true`입니다.
- 정부 키(브이월드, 공공데이터포털, 법제처)는 확인하지 않고 그대로 저장합니다(`verified: false`). 키가 틀리면 대지 조회나 법령 검색에서 오류 안내가 나옵니다.
- 빈 값이나 여러 줄은 `400`, 표에 없는 `{key}`는 `404`입니다.
- 키 칸은 비워 두고 `hint`(예: `…5678`)만 자리 표시로 보여 주세요. 새로 입력했을 때만 보내면 됩니다.

## 예시

```js
const settings = await (await fetch("/api/settings")).json();
if (settings.first_run) showSettingsScreen(settings);

async function save(changes) {
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes), // 예: { mode: "local", local_profile: "local_plus" }
  });
  if (!res.ok) return alert((await res.json()).detail);
  render(await res.json());
}

async function saveKey(key, value) {
  const res = await fetch(`/api/settings/keys/${key}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) return alert((await res.json()).detail); // 예: 키가 거부됨
}
```

## 오류

오류 응답은 `{detail: "메시지"}`입니다. 400은 선택지에 없는 값이나 거부된 키, 404는 모르는 키 이름, 422는 요청 형식 오류(모르는 항목 포함)입니다.
