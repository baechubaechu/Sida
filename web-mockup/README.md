# Sida 웹 UI 테스트 목업

[Figma UI Draft v0.1](https://www.figma.com/design/GxmxEdWnkh77OwObTcSx5p/Sida?node-id=0-1)의 프로젝트 홈, 새 프로젝트, 메인 채팅, 전문가 목록 펼치기, 전문가 분할 채팅을 구현한 정적 웹 페이지입니다.

기존 Python 웹 앱과 별도로 실행합니다. 실제 LLM·API·개인 프로젝트를 사용하지 않습니다. 프로젝트와 대화는 브라우저 localStorage에 저장되며, 첨부 파일은 이름만 표시합니다. 저장이 차단된 브라우저에서는 현재 페이지를 열어 둔 동안만 유지됩니다.

## 로컬에서 보기

저장소 루트에서:

```sh
node web-mockup/scripts/serve.mjs
```

[http://127.0.0.1:4173](http://127.0.0.1:4173)을 엽니다. Node.js 22 이상이 필요하며 별도 설치·빌드 과정은 없습니다. 또는 `python -m http.server 4173 --bind 127.0.0.1 --directory web-mockup/public`로 실행할 수 있습니다.

## Vercel 배포

Vercel에서 이 Git 저장소를 가져오고 다음과 같이 설정합니다.

| 항목 | 값 |
| --- | --- |
| Root Directory | `web-mockup` |
| Framework Preset | `Other` |
| Build Command | 비움 (`vercel.json`에 지정) |
| Install Command | 비움 (`vercel.json`에 지정) |
| Output Directory | `public` |
| 환경변수 | 필요 없음 |

`web-mockup/vercel.json`이 정적 배포 설정을 제공합니다. 주소의 `#` 뒤에서 화면을 전환하므로 상세 화면에서 새로고침하거나 링크를 열어도 별도 서버 라우팅 설정이 필요 없습니다. 프로젝트 데이터는 방문자마다 해당 브라우저에만 저장됩니다.

## 확인할 흐름

- 프로젝트 검색·정렬 → 카드 선택 → 메인 채팅
- 프로젝트 카드 오른쪽 **⋯** → **프로젝트 삭제** → 확인 후 프로젝트와 메인·전문가 대화 삭제 (마지막 프로젝트를 삭제해도 새로고침 후 빈 목록 유지)
- 새 프로젝트 → 이름·설명 입력 → 작업 공간 → 홈 목록 확인
- 전문가 이름 클릭 → 분석 채팅 목록 → 분석 선택 → 분할 화면 → 닫기
- 메인 채팅의 **분석 보기** → 공간 검토자 채팅
- 메시지 전송 → 샘플 응답 → 새로고침 후 유지 확인
- 새 채팅과 새 분석 채팅 → 독립적인 대화
- 구분선 드래그 또는 키보드 좌우 화살표 → 패널 너비 변경
- 작은 화면에서 **전문가** 버튼 → 전문가 목록

Enter로 전송하고 Shift+Enter로 줄을 바꿉니다. 한국어 입력 조합 중 Enter는 전송하지 않습니다. 제목 옆의 UI 목업 표시와 설정의 안내에서 샘플 동작 범위를 확인할 수 있습니다.

## 디자인 수정

`public/styles.css` 위쪽의 `:root`에서 색상, 글꼴, 사이드바·전문가 패널 너비, 기본 여백을 바꿀 수 있습니다. 화면 구조와 동작은 `public/app.js`, 샘플 데이터와 상태 처리는 `public/model.js`에 있습니다. Figma의 텍스트·CSS 도형을 HTML·CSS로 옮겼으며 별도 이미지 자산은 없습니다. 글꼴은 설치된 Inter/Pretendard 또는 운영체제의 한국어 글꼴을 사용합니다.

## 테스트

```sh
node --test web-mockup/tests/model.test.mjs
python -m pytest tests/test_web_mockup.py
```

프로젝트 생성·검색·정렬, 대화와 전문가별 독립 저장, 새로고침 복원, 잘못된 저장 데이터 복구, 정적 배포 파일 구성을 확인합니다. CI는 Node 테스트와 기존 Python 검사를 실행합니다.
