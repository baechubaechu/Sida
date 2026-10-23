# ChatGPT 구독 연결 API (Conductor를 ChatGPT 구독으로)

설계자가 가진 ChatGPT 구독(Go, Plus, Pro)으로 Conductor를 돌리는 JSON API입니다. API 키 대신 ChatGPT 계정으로 로그인하고, 사용량은 그 계정의 구독 한도에서 빠집니다. 기존 방식(OpenRouter 키, Ollama)은 그대로 있고, 설정에서 Conductor 제공자를 `chatgpt`로 고를 때만 씁니다. 로직은 `sida/chatgpt_auth.py`(로그인)와 `sida/providers.py`의 `ChatGPTProvider`(모델 호출), 경로는 `sida/chatgpt_api.py`와 `webapp.py`의 `/auth/callback`에 있습니다.

OpenAI의 "Sign in with ChatGPT" 오픈소스·로컬 앱 경로를 따릅니다([문서](https://developers.openai.com/siwc/token-sharing-open-source)). Claude 구독(Pro/Max)은 Anthropic 약관이 서드파티 앱의 구독 로그인을 금지해서 쓰지 않습니다.

## 동작 방식

- Conductor와 전문가(워커)를 각각 ChatGPT 구독으로 돌릴 수 있습니다. 모델도 따로 고릅니다(`chatgpt_model`, `worker_chatgpt_model`). 전문가 문서는 길어서 구독 사용량을 Conductor보다 훨씬 많이 씁니다. 이 경로는 답 길이 상한을 받지 않으므로, 답이 중간에 잘리면 그 전문가 실행은 실패로 끝나고 저장되는 것은 없습니다(`module_failed`). 사용 한도를 넘으면 다른 제공자로 넘어가지 않고 한도 안내 오류가 납니다.
- 로그인은 설계자의 브라우저에서 OpenAI 로그인 화면을 거칩니다. 끝나면 브라우저가 Sida 서버의 `http://127.0.0.1:<포트>/auth/callback`으로 돌아오고, 그 화면에 결과가 나옵니다. 그 창은 닫으면 됩니다.
- 처음 로그인할 때 이 PC가 OpenAI에 앱으로 등록됩니다(비밀값 없음). 다음 로그인부터는 같은 등록을 다시 씁니다.
- 로그인 정보(토큰)는 저장소 밖 `~/Sida/chatgpt_login.json`에 이 PC 사용자만 읽을 수 있게 저장합니다. API 응답에는 토큰이 들어가지 않습니다.
- 토큰은 한 시간마다 만료되고, Sida가 알아서 갱신합니다. 갱신이 완전히 실패하면 로그아웃 상태가 되고 다시 로그인해야 합니다.
- PC 한 대에 ChatGPT 계정 하나입니다. 팀원은 각자 자기 PC에서 자기 계정으로 로그인합니다.

## API

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/settings/chatgpt` | | `{signed_in, email, plan_usage, registered}` |
| `POST /api/settings/chatgpt/login` | `{new_account?}` | `{authorize_url}` |
| `GET /api/settings/chatgpt/models` | | `{models: [{slug, display_name}]}` |
| `DELETE /api/settings/chatgpt` | | `{revoked}` |

- `signed_in`: 로그인되어 있는지. `email`: 로그인한 계정.
- `plan_usage`: 로그인할 때 구독 사용을 허용했는지. `false`면 로그인은 됐지만 Conductor가 쓸 수 없습니다(무료 계정이거나 허용을 안 누름). 다시 로그인하게 안내하세요.
- `registered`: 이 PC가 OpenAI에 등록돼 있는지(로그아웃해도 남음).
- `login`: 받은 `authorize_url`을 새 창이나 새 탭으로 여세요(`window.open`). 로그인 시도는 10분 안에 끝내야 합니다. `new_account: true`는 다른 ChatGPT 계정으로 새로 등록할 때만 씁니다.
- `models`: 이 계정이 쓸 수 있는 모델을 OpenAI가 주는 순서대로 돌려줍니다. 로그인 전이면 `502`입니다. 고른 모델의 `slug`를 아래 설정의 `chatgpt_model`로 저장하세요.
- `DELETE`: 로그아웃합니다. `revoked`가 `false`면 OpenAI 쪽 연결 해제를 확인하지 못한 것이니 "ChatGPT 설정에서 Sida 연결을 끊어 주세요"라고 안내하세요. 이 PC의 토큰은 어느 경우든 지웁니다.

### 설정 API에서 바뀐 것 ([settings-api.md](settings-api.md))

| 항목 | 내용 |
|---|---|
| `PUT /api/settings`의 `conductor_provider`, `worker_provider` | 둘 다 `chatgpt`도 받습니다 |
| `PUT /api/settings`의 `chatgpt_model` | Conductor가 ChatGPT 구독에서 쓸 모델(`models`의 `slug`) |
| `PUT /api/settings`의 `worker_chatgpt_model` | 전문가가 ChatGPT 구독에서 쓸 모델. `GET /api/settings`의 `chatgpt.worker_model`, 선택지는 `options.worker_providers` |
| `GET /api/settings`의 `chatgpt` | `{signed_in, email, plan_usage, registered, model, worker_model}` |
| `GET /api/settings`의 `warnings.chatgpt_signed_out` | Conductor나 전문가가 `chatgpt`인데 로그인 안 됨 |
| `GET /api/settings`의 `options.conductor_providers` | Conductor 제공자 선택지 `["openrouter", "ollama", "chatgpt"]` |

한 역할이라도 `chatgpt`이면 `mode`는 `custom`이 됩니다. 이때 `mode`를 `cloud`나 `local`로 저장하면 두 역할 모두 그 모드로 돌아갑니다.

## 예시

```js
async function signInWithChatGPT() {
  const res = await fetch("/api/settings/chatgpt/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  window.open((await res.json()).authorize_url, "_blank");
  // 설계자가 로그인을 마치고 돌아오면 상태를 다시 읽습니다(창에 다시 포커스가 올 때 등).
}

async function useChatGPTForConductor(slug) {
  await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conductor_provider: "chatgpt", chatgpt_model: slug }),
  });
}
```

## 제약 (OpenAI 미리보기 단계)

OpenAI가 이 경로를 아직 미리보기로 열어 둔 상태라 규칙이 바뀔 수 있습니다.

- `temperature`와 최대 답 길이는 보내지 않습니다(이 경로가 받지 않음). `config.yaml`의 Conductor `temperature`·`max_tokens`는 ChatGPT 구독일 때 쓰이지 않습니다.
- Conductor 지시문은 system 메시지 대신 `instructions`로 보냅니다. 답은 스트리밍으로 받고, 대화는 OpenAI에 저장하지 않습니다(`store: false`).
- 구독 한도를 다 쓰면 Conductor 답 대신 오류가 나옵니다. 다른 결제 방식으로 넘어가지 않습니다. ChatGPT 설정의 사용량을 보거나, Conductor를 OpenRouter로 돌려 쓰면 됩니다.
- 이 경로를 승인 없이 계속 쓸 수 있는지는 OpenAI 문서에 분명하지 않습니다.

## 오류

| 상태 | 뜻 |
|---|---|
| `/auth/callback` 400 | 로그인 거절, 시간 초과(10분), 이미 쓴 로그인 시도, 토큰 확인 실패. 화면에 이유가 나옵니다 |
| `/auth/callback` 502 | OpenAI 로그인 서버에 닿지 못함 |
| `502` (API) | 로그인 안 됨, 구독 사용 불가, 한도 초과, OpenAI 오류. `detail`에 이유가 있습니다 |
| `422` | 요청 형식 오류(모르는 항목 포함) |
