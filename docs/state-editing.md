# 설계 상태 승인·문서 편집 코어 연결

코어와 JSON API를 준비했습니다. 웹 화면은 아래 API에 연결하면 됩니다. 코어 함수는 터미널 입출력 없이 동작하며 CLI와 웹에서 사용할 수 있습니다.

## JSON API

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /api/projects/{name}/documents/{kind}` | `kind`는 `brief` 또는 `state` | `{kind, content, revision}` |
| `PUT /api/projects/{name}/documents/{kind}` | `{content, expected_revision}` | 저장된 `{kind, content, revision}` |
| `POST /api/projects/{name}/state-proposals` | `{agent: "site_reader"}` | `{proposal: {id, agent, diff}}` 또는 `{proposal: null}` |
| `POST /api/projects/{name}/state-proposals/{id}/apply` | 본문 없음 | `{applied: true, document: {kind, content, revision}}` |
| `POST /api/projects/{name}/state-proposals/{id}/skip` | 본문 없음 | `{skipped: true}` |

문서 조회는 프로젝트를 열거나 세션 시각을 갱신하지 않습니다. 편집에는 모델과 API 키가 필요 없습니다. 상태 제안은 기존 전문가 결과로 모델을 호출하므로 결과가 먼저 있어야 합니다. 요청 동안 화면에 진행 표시를 제공하세요. `ask`/`auto`/`off` 설정과 관계없이 API의 제안 요청은 명시적으로 적용할 때까지 상태를 저장하지 않습니다.

오류 응답은 `{detail: "메시지"}`입니다. 400은 잘못된 문서 종류·전문가·미실행 전문가, 404는 프로젝트나 문서 없음, 409는 오래된 문서·승인안 또는 변경된 입력, 502는 모델 호출 실패, 500은 설정·저장 실패입니다. Pydantic 요청 형식 검증 실패는 422입니다. 기존 localhost 및 cross-site 쓰기 제한은 그대로 적용됩니다.

코어 서비스는 `app.state.editing`(`EditingService`)에 있습니다. API가 보관한 승인안은 프로젝트별 최신 한 개이며 적용·건너뛰기 후 제거됩니다. 같은 서비스의 문서 저장과 승인 요청은 프로젝트별로 직렬화됩니다. 프로젝트마다 독립적으로 동작합니다. 서버 재시작 뒤에는 제안 요청을 다시 보내세요. 화면이 쓰는 대화 세션의 브리프도 문서 저장 후 새로 읽어야 합니다. 이 API의 문서 저장은 별도 대화 세션의 메모리를 직접 변경하지 않습니다.

## 상태 갱신 승인

1. `engine.propose_state(session, agent)`가 `StateProposal`을 반환합니다. 모델 호출만 하고 파일은 바꾸지 않습니다. 변경이 없으면 `None`입니다.
2. 화면에는 `proposal.diff`를 보여 줍니다. 내부 반영 기록은 숨기며, 요약이 같고 분석 버전만 달라졌다면 반영 기록을 갱신한다는 안내를 반환합니다.
3. 적용은 `engine.apply_state(session, proposal)`, 건너뛰기는 `engine.discard_state(session, proposal)`입니다. 서버에 보관한 승인안 객체를 사용합니다. 클라이언트가 임의로 보낸 `proposed` 문자열을 승인안으로 사용하지 않습니다.
4. 한 세션에는 최신 승인안 하나만 유효합니다. 건너뛴 승인안, 이미 적용한 승인안, 이전 승인안은 다시 적용할 수 없습니다. 앱을 재시작하면 승인안을 새로 생성합니다.

승인 전에 원본 상태, 브리프 또는 전문가 결과가 달라지면 `DocumentConflict`가 발생합니다. 최신 자료로 다시 제안하도록 안내하세요. 기존 파일과 백업은 덮어쓰지 않습니다. 제안 생성 뒤 입력이 그대로라면 이전 상태를 `project_state.prev.md`에 보관하고 승인한 상태를 저장합니다.

## 브리프·상태 편집

- 세션이 있으면 `engine.read_editable_document(session, "brief" | "state")`를 호출합니다. 결과는 `Document(kind, content, revision)`입니다.
- 저장은 `engine.edit_document(session, kind, content, expected_revision=document.revision)`입니다. 브리프를 저장하면 이후 모델 호출에 사용할 세션의 브리프도 새로 읽습니다.
- 세션 없이 프로젝트만 다루려면 `project_documents.read_document(project, kind)`와 `save_document(project, kind, content, expected_revision=...)`를 사용합니다.
- `revision`은 서버가 돌려준 값을 그대로 전달하세요. 표시용 상태 본문에는 내부 기록이 없으므로 클라이언트에서 다시 계산하면 안 됩니다.
- 편집 가능한 종류는 `brief`와 `state` 두 가지입니다. 임의 파일 경로는 받지 않습니다. 사용자가 작성한 Markdown 섹션은 그대로 저장하고, 이전 원문은 각각 `brief.prev.md`와 `project_state.prev.md`에 보관합니다.
- 내용이 같으면 파일과 백업을 쓰지 않습니다. 읽은 뒤 다른 사용자가 저장했으면 `DocumentConflict`로 거절하고 최신 문서를 다시 불러오게 합니다.

`DocumentConflict`는 HTTP 409로, 허용되지 않은 문서 종류는 400으로 처리합니다. 다른 `SidaError`는 기존 `core(...)` 오류 처리 경로를 사용합니다. 웹 라우터는 `document_api.py`, 작업 로직은 `editing.py`와 `engine.py`에 있습니다. 이 브랜치는 웹 템플릿을 수정하지 않습니다.

## 전문가 결과의 상태 반영 기록

승인한 전문가 결과의 SHA-256 값은 `project_state.md`의 예약된 HTML 주석 `sida-module-revisions`에 기록됩니다. 상태 본문과 함께 원자적으로 저장하므로 별도 파일 간 불일치가 없습니다.

Conductor는 저장된 내용과 현재 전문가 결과를 비교합니다. A의 상태만 갱신해도 B의 미반영 결과는 그대로 포함되며, 파일 시각이 같거나 더 오래돼도 내용이 바뀐 결과는 다시 포함됩니다. 기록은 모델 입력·승인 diff·문서 편집 화면에서 숨깁니다. 상태 편집 시 클라이언트가 넣은 기록은 사용하지 않고 기존 기록을 보존합니다.

기존 프로젝트에 기록이 없거나 기록이 손상된 경우에는 안전하게 미반영으로 취급해 전체 분석 결과를 포함합니다. 해당 전문가의 갱신안을 승인하면 그 버전부터 반영된 것으로 기록합니다. 여러 결과가 포함되어 모델 입력이 길어질 수 있으므로 기존 프로젝트에서는 필요한 전문가부터 상태에 반영하면 됩니다.

저장은 개별 파일 단위로 보호합니다. 문서 버전 확인은 읽은 이후의 변경을 감지하지만, 외부 편집기가 저장 순간에 동시에 쓰는 경우까지 운영체제 잠금으로 막지는 않습니다.
