# 제도판 시험판 (Drafting Table prototype)

가운데 디자인 화면을 어떤 형태로 만들지 정하기 위한 시험판입니다. Sida 앱(`webui/app/`)과는 별개이고, 앱 빌드·테스트에 포함되지 않습니다. 필지 경계와 면적은 `tests/fixtures/landapi/`의 녹화 응답(군포 금정동 689-14, 689-15)에서 뽑은 것이고(`src/shared/parcels.json`), 매스안·Conductor 답·전문가 결과는 예시입니다. 저장 기능은 없습니다.

## 진입점 (만든 순서)

| 진입점 | 내용 |
|---|---|
| `src/tldraw-main.jsx` | tldraw 라이브러리로 만든 보드. 배포에는 유료 라이선스 키가 필요해 평가용으로만 씀 |
| `src/excalidraw-main.jsx` | Excalidraw(MIT)로 만든 보드. 직접 만든 카드를 임베드 기능으로 우회해야 함 |
| `src/own-main.jsx` | 직접 만든 무한 보드(`src/board/`). 3D·평면 전환, 트레이싱지 덮기·떼기·씌우기 |
| `src/table-main.jsx` | **제도판**(`src/table/`). 실제 축척 책상 위 대지를 기울여 평면→액소→투시로 보고, 트레이싱지를 덮고 떼며, 전문가 핀으로 그 자리를 봄 |

공통 부분은 `src/shared/`에 있습니다: 세 칸 틀(`Shell.jsx`: Conductor·디자인 화면·전문가), 대지 좌표와 면적·건폐율·용적률 계산(`geometry.js`), 3D 보기(`ThreeView.jsx`), SVG 배치도(`PlanView.jsx`).

## 빌드

```bash
cd prototypes/drafting-table
npm install
npm run build:table      # dist-table/app.js, style.css
```

결과물은 `dist-<이름>/`에 나옵니다. 브라우저에서 열려면 `style.css`를 넣은 HTML에 `<div id="root"></div>`와 `<script type="module" src="./app.js"></script>`를 두고 같은 폴더에서 정적 서버로 엽니다(`python -m http.server`).

## 제도판 조작

- `1` 평면, `2` 액소, `3` 투시, 오른쪽 위 막대로 0~75°. 우클릭(또는 Alt)+끌기로 기울이고 돌림
- 빈 곳 끌기: 책상 이동, ⌘/Ctrl+휠: 확대, `0`: 전체 보기
- `T` 트레이싱지 덮기 → `P` 펜으로 그림 → 종이를 옆으로 끌어내면 떼어짐, 대지로 끌어오면 제자리에 붙음
- `N` 메모, `V` 선택, Shift+클릭 여러 장 선택(Conductor에게 맥락으로 보냄), Delete 삭제

## 알려진 한계

- 종이는 3D 장면 위에 덧그리는 층(CSS3D)이라 건물 뒤에 놓인 종이도 앞에 보입니다.
- 기울이면 종이 글씨가 작고 비스듬해집니다.
- 저장, 실제 Conductor·전문가 연결, 주변 건물(정부 데이터) 없음.
