# 법령 검색 API (허브의 법령 질문)

프로젝트 없이 건축·도시계획 법령을 묻는 검색창이 쓰는 JSON API입니다. CLI 허브의 `l`(법령 검색)과 같은 일을 합니다. 로직은 `sida/experts/regulation/law_search.py`의 `search_law`, 경로는 `sida/experts/regulation/api.py`에 있습니다.

프로젝트 안의 법규 검토자는 이 API를 쓰지 않습니다. 전문가가 실행될 때 법제처 검색이 자동으로 붙습니다.

## 동작 방식

- 질문으로 법제처 조문을 검색하고, 찾은 조문을 Conductor 모델에게 주어 답을 받습니다. 숫자와 조문은 찾은 조문에 있을 때만 답에 씁니다.
- 한 번 부르면 답이 나올 때까지 기다립니다(보통 몇 초에서 30초). 그동안 로딩 표시를 하고 보내기 버튼을 막아 두세요.
- 이전 질문은 기억하지 않습니다. 질문마다 따로 검색합니다.
- 설정에서 법령 검색이 꺼져 있으면(`GET /api/settings`의 `rag_enabled`가 `false`) 답하지 않고 `400`을 돌려줍니다. 찾은 조문 없이 모델 기억만으로 법령을 답하지 않게 하기 위해서입니다. 화면은 이때 설정 화면으로 안내하세요.

## API

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `POST /api/law/search` | `{question}` (500자 이하) | `{question, answer, sources, warning, notices}` |

- `answer`: 모델의 답(Markdown). 모델에게는 조문을 `sources`의 `index`와 같은 번호(`[1]`, `[2]`)와 출처 이름으로 주므로, 답은 둘 중 하나로 조문을 가리킵니다.
- `sources`: 찾은 조문 `{index, title, source, text, truncated}`. `text`는 조문 원문이고, `truncated`가 `true`면 원문이 중간에 잘렸다는 뜻이라 "원문 일부"라고 표시해 주세요.
- `warning`: 찾은 조문이 없을 때 그 이유(인증값 없음, 검색 결과 없음 등). 있으면 답 위에 경고로 보여 주세요. 이때 답은 조문 근거 없이 쓴 안내 수준입니다.
- `notices`: 로컬 모델을 준비하며 나온 안내 줄. 보통 비어 있습니다.

## 예시

```js
async function ask(question) {
  const res = await fetch("/api/law/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) return alert((await res.json()).detail);
  const { answer, sources, warning } = await res.json();
  render(answer, sources, warning);
}
```

## 오류

오류 응답은 `{detail: "메시지"}`입니다. 400은 빈 질문, 500자를 넘는 질문, 법령 검색이 꺼져 있음, 422는 요청 형식 오류, 500은 OpenRouter 키 없음 같은 설정 문제, 502는 모델 호출 실패입니다.
