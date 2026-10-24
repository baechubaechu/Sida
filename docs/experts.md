# Experts: 설계 과정을 렌즈로 나누기

## 왜 바꿨나

이전 구성(01 site_reader → 02 constraint_mapper → 03 design_critic → 04 representation_planner →
05 presentation_editor)은 "분석 → 제약 → 비평 → 표현 → 발표"라는 단일 선형 파이프라인을 전제했다.
실제 설계는 그렇게 진행되지 않는다.

- 사이트가 프로젝트를 끌고 가는 경우 (인프라 절개, 급경사, 수변) — 사이트 읽기가 먼저
- 아이디어가 먼저인 경우 (스튜디오 과제, 공모) — 개념을 검증 가능한 문장으로 만드는 것이 먼저
- 프로그램이 복잡한 경우 (복합용도, 운영 주체 다수) — 사용자·인접성·공사 구분이 먼저
- 법규가 형태를 거의 결정하는 경우 (도심 소규모, 역세권, 일조·사선) — 검증 의제가 먼저

또 이전 구성에는 빠진 렌즈가 있었다: **프로그램**, **법규**, **개념**, **선례**, **공간조직 검토**,
**시스템(구조·외피·설비·피난)**. 특히 법규와 개념은 위 네 출발점 중 둘의 핵심이다.

마지막으로, 여러 전문가의 결과가 서로 어긋날 때 이를 정리하는 장치가 없었다.

## 원칙

1. **전문가는 독립 렌즈다.** 어떤 전문가도 단독으로, 어떤 순서로도 실행할 수 있다. 선행 출력이
   없으면 브리프만으로 작업하고, 무엇이 빠져 결과가 약해지는지 스스로 말한다.
2. **입력은 선언한다.** `config.yaml`의 `inputs`가 그 전문가가 읽을 선행 출력을 정한다. 워커는
   관련 출력만 받고, 나머지 완료된 전문가는 이름만 받는다 (컨텍스트 절약 + 무관한 결과에
   끌려가지 않음).
3. **모두 Handoff로 끝난다.** 각 출력의 마지막 섹션은 `## Handoff` — "→ regulation_checker:
   철도 인접 이격 확인" 식으로 다음에 볼 전문가를 지목한다. 이것이 조합의 연결고리다.
4. **Conductor가 조합한다.** 조건(hard/soft와 출처)·전문가 간 충돌·지금 내려야 할 결정·낡은
   뷰를 Conductor가 대화 안에서 정리한다. 3개 이상 완료 시, 출력이 충돌할 때, 설계자가 요청할 때.
   2026-10-10 회의에서 이 일을 하던 `constraint_mapper`와 `synthesizer`를 빼고 Conductor로 옮겼다
   (`agents/00_conductor.md`의 "Conditions and decisions").
5. **경로는 제안이다.** `paths`는 출발점별 권장 순서일 뿐이다. Conductor는 브리프의
   `Primary Driver`와 설계자가 실제로 막힌 지점으로 진입 전문가를 고른다. 경로에는 필수
   전문가만 넣는다.
6. **설정이 곧 목록이다.** Conductor 프롬프트의 전문가 목록과 project_state.md의 Module Status
   표는 `config.yaml`에서 생성된다. 전문가 추가 = 프롬프트 파일 1개 + `agents:` 항목 1개.

## 전문가 10개

번호는 단계 그룹이다 (1x 분석, 2x 개념, 4x 전개, 5x 비평, 6x 전달). 실행 순서가 아니다.
3x(통합)는 비어 있다. 조합은 Conductor가 한다.

### 필수 7개와 보류 3개

2026-10-10 회의에서 필수 7개(대지 분석가, 프로그램 분석가, 법규 검토자, 선례 연구자, 설계
비평가, 표현 계획자, 발표 편집자)와 보류 3개(개념 정리자, 공간 검토자, 시스템 자문가)로 나눴다.
`config.yaml`의 `tier`가 `core` 또는 `held`다.

보류 전문가는 지우지 않고 다음처럼 다룬다.

- 설계자가 전문가 화면에서 직접 실행하거나 Conductor에게 이름으로 부탁하면 돈다.
- Conductor는 먼저 권하지 않는다. 프롬프트의 전문가 목록에 `ON HOLD`로 표시되고, 경로(`paths`)에서 빠진다.
- 한 전문가가 끝난 뒤 Conductor가 이어서 보류 전문가를 부르면 실행하지 않고 `run_skipped`(`reason: held`)로 알린다(`engine.converse`).
- 세션 API의 `experts` 목록에 `tier`가 나오고, 화면은 단계 옆에 "보류"를 붙인다.

| id | 단계 | 무엇을 하나 | 하지 않는 것 |
|---|---|---|---|
| `site_reader` | 분석 | 사실(정부 자료·브리프, 출처 표시)·해석(근거 사실 명시)·미확인을 나눠 쓰고, 시스템이 어떻게 만나고 끊는지, 충돌·기회 | 프로그램·형태 제안, 수치 추정 |
| `program_analyst` | 분석 | 사용자와 리듬, 구성요소(브리프/후보/가정 구분), 인접·분리, 공사 그라디언트, 상대 면적 논리 | 면적 숫자 발명, 배치 제안 |
| `regulation_checker` | 분석 | 적용 법령(한국 기본), 확인 항목 표(왜/어디서), 형태를 묶을 제약, 인센티브 | 수치를 사실로 단정 — 항상 "verify" |
| `precedent_scout` | 분석 | 문제 기준 선례 3–6개: 문제·수법·교훈·주의. 불확실하면 이름 대신 유형 | 형태 복제 권고, 사실 발명 |
| `concept_framer` (보류) | 개념 | 설계자의 의도를 한 문장 개념 + 작동 전략 + 증명해야 할 주장 + 클리셰 위험 | 개념 대체, 형태 제안 |
| `spatial_reviewer` (보류) | 전개 | 설계자가 기술한 조직(레이어·단면·동선·경계·프로그램 배치)의 논리 검증, 약점별 검증 도면 | 대안 설계, 취향 판단 |
| `systems_advisor` (보류) | 전개 | 구조·외피·환경·설비·피난 질문과 옵션별 트레이드오프, 지금 안 정하면 잠기는 결정 | 치수·하중·수치 |
| `design_critic` | 비평 | 심사위원 시점: 핵심 문제에 답하는가, 모순, 약한 가정, 빠진 표현, 다음 행동 | 일반론 |
| `representation_planner` | 전달 | 다이어그램 위주: 다이어그램마다 종류·주장 하나·보여 줄 것과 뺄 것, 다이어그램 순서. 도면·렌더·모형은 다이어그램으로 안 되는 곳만 | 도면 나열, 개수 채우기 |
| `presentation_editor` | 전달 | 한 줄 요약, 문제, 시스템, 핵심 산출물, 포트폴리오 구조, 예상 질문 | 새 주장 추가, 과장 |

## 출발점별 경로 (config `paths`)

| 경로 | 언제 | 순서 |
|---|---|---|
| `site_driven` | 인프라·지형·수변이 문제를 만든다 | site_reader → program_analyst → regulation_checker → precedent_scout → design_critic |
| `idea_driven` | 개념이 먼저 있고 근거를 만들어야 한다 | precedent_scout → site_reader → program_analyst → design_critic |
| `program_driven` | 사용자·운영·구성이 복잡하다 | program_analyst → site_reader → regulation_checker → precedent_scout → design_critic |
| `regulation_driven` | 법규가 형태를 거의 결정한다 | regulation_checker → site_reader → program_analyst → design_critic |
| `review_prep` | 크리틱·심사 직전 | design_critic → representation_planner → presentation_editor |

경로는 순서를 강제하지 않는 힌트다. 대화 세션에서 Conductor가 한 번에 하나씩, 필요할 때만 제안한다.

## 조합이 실제로 일어나는 지점

```
브리프 (Primary Driver: idea)
  │
  ├─ Conductor: 진입 = precedent_scout (개념 정리자는 보류라 먼저 권하지 않음)
  │     출력 Handoff → site_reader: "단면 교차가 실제 대지에서 가능한지"
  │
  ├─ site_reader (inputs: 없는 것은 명시) → Handoff → regulation_checker: "철도 인접 이격"
  ├─ regulation_checker (inputs: site_reader, program_analyst — 후자 없음 → 명시)
  │
  ├─ 3개 완료 → Conductor가 조건·결정을 정리
  │     충돌 — 브리프의 "지상 연속 보행" vs Regulation Checker의 "철도 이격 verify"
  │     결정 — 단면 교차 위치: 역사 내부 / 외부 연결부 (옵션·비용·근거)
  │
  └─ 설계자 결정 → project_state.md Confirmed Decisions
        → design_critic이 그 결정을 전제로 방향을 비평
```

각 단계에서 `state_update`가 project_state.md의 Module Status 행과 관련 섹션을 갱신하므로,
Conductor는 전체 출력이 아니라 상태 파일의 takeaway와 Handoff 힌트로 다음을 고른다.

## 한계와 다음 단계

- `regulation_checker`는 검증 의제를 만든다. 실제 조례 수치·지구단위계획은 설계자가 확인한다.
  RAG 훅은 준비됨 (`rag.enabled`, `knowledge/regulations/`, `docs/rag.md`) — 코퍼스를 채운 뒤
  `enabled: true` 로 켠다.
- `precedent_scout`는 모델 지식에 의존한다. 유명한 작품 위주로 제한하고 모두 `(verify)`를 붙인다.
- `spatial_reviewer`는 텍스트로 기술된 조직만 검토한다. 도면·이미지 입력은 아직 없다.
- `design_critic`(inputs: all)은 완료된 출력을 모두 읽으므로 컨텍스트가 크다.
  워커는 클라우드 모델(gpt-4o-mini, 128K)이 기본이라 문제 없지만, 워커까지 로컬로 돌릴 때는
  `MODULE_CHAR_LIMIT`류의 절단이 필요하다.
