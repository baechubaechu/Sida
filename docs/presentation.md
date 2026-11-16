# 발표 자료 (슬라이드 목록 → PowerPoint·PDF)

발표 편집자가 순서와 문장을 정하고, Sida가 그 자리에 라이노 모델의 그림과 수치를 채워 파일로 만듭니다. AI는 그림을 만들지 않고 숫자를 쓰지 않습니다. 코드는 `sida/experts/presentation/`(`slides.py`, `deck.py`, `api.py`, `hooks.py`)에 있습니다.

## 슬라이드 목록

발표 편집자(`agents/62_presentation_editor.md`)는 결과 문서 끝에 JSON 블록 하나를 붙입니다(표현 계획자의 모형 판 블록과 같은 방식).

```json
{"slides": [
  {"layout": "title", "title": "무교동 45 복합시설", "subtitle": "저층은 도시에 연다"},
  {"layout": "text", "title": "문제", "bullets": ["좁은 골목", "높은 용적률"], "notes": "30초 안에"},
  {"layout": "figure", "title": "프로그램", "figure": "diagram:program", "caption": "…", "bullets": ["…"]}
]}
```

| 항목 | 뜻 |
| --- | --- |
| `layout` | `title`(표지), `text`(글), `figure`(그림). 없거나 모르는 값이면 내용으로 정함(`figure`가 있으면 그림, 첫 장이고 항목이 없으면 표지) |
| `title`, `subtitle` | 120자, 300자까지 |
| `bullets` | 8개까지, 한 줄 300자까지 |
| `caption` | 그림 아래 한 줄 |
| `notes` | 말할 내용(PowerPoint의 슬라이드 노트). 1,500자까지 |
| `figure` | 자료의 키 하나 |

자료의 키는 가장 새 라이노 스냅샷에서 나옵니다(`slides.materials`).

| 키 | 채워지는 것 |
| --- | --- |
| `diagram:program` `diagram:floors` `diagram:stack` `diagram:site` `diagram:limits` | Sida가 규칙으로 그린 다이어그램([`rhino-api.md`](rhino-api.md)의 다이어그램) |
| `view:persp` `view:plan` … | 그 스냅샷의 라이노 캡처(같은 종류가 여럿이면 첫 장) |
| `figures` | 수치 표(대지면적, 건축면적, 연면적과 용도별, 건폐율·용적률과 한도, 최고 높이) |

편집자는 실행될 때 지금 쓸 수 있는 키 목록을 받습니다(`hooks.prompt_blocks` → `slides.prompt_text`, 그릴 수 없는 것은 이유와 함께). 목록에 없는 키나 지금 만들 수 없는 그림은 슬라이드 자리를 지키되 빈 칸으로 두고, 무엇이 왜 비었는지 `notes`로 알립니다. 슬라이드는 30장까지입니다.

목록이 없으면(편집자를 아직 실행하지 않았거나 예전 문서) Sida가 규칙으로 기본 순서를 놓습니다: 표지(브리프의 Project Name), 수치, 그릴 수 있는 다이어그램, 캡처. 문장은 쓰지 않습니다.

## API

| 경로 | 답 |
| --- | --- |
| `GET /api/projects/{name}/presentation` | `{source, written, title, slides, notes, snapshot, figure_rows, formats}`. `source`는 `editor`(편집자의 목록) 또는 `default`(기본 순서), `written`은 편집자 결과가 있는지. 슬라이드의 `figure`는 `null` 또는 `{key, kind, title, ready, why, file?}`. `snapshot`은 `{id, taken_at, file}` 또는 `null`, `figure_rows`는 수치 표의 `[항목, 값]` 줄 |
| `GET /api/projects/{name}/presentation/file?format=pptx\|pdf\|zip` | 파일. 이름은 `Content-Disposition`의 `filename*`(`<프로젝트 이름> 발표자료.pptx`). 모르는 형식은 400 |

저장하는 것은 없습니다. 부를 때마다 편집자의 문서와 가장 새 스냅샷에서 다시 만들므로, 파일의 수치는 늘 마지막으로 보낸 모델의 것입니다. 사람이 누른 때만 만들어집니다.

## 파일 (`deck.py`)

슬라이드는 16:9(960 × 540 pt) 쪽에 먼저 놓이고(`deck.pages`), PowerPoint와 PDF가 그 같은 쪽을 그립니다. 그래서 두 파일의 배치가 같습니다.

- **PowerPoint**(`python-pptx`): 제목은 슬라이드 제목 자리, 문장은 글머리표가 있는 텍스트 상자, 수치는 표, 다이어그램은 도형 묶음 하나(그룹)라서 파워포인트에서 색과 글을 바로 고칠 수 있습니다. 캡처는 라이노가 만든 PNG입니다. 한 덩어리의 벽처럼 같은 색으로 이어 칠하는 면은 도형 하나로 묶어 가볍게 합니다. `notes`는 슬라이드 노트로 들어갑니다. 글꼴은 맑은 고딕으로 적어 둡니다.
- **PDF**(`reportlab`): 같은 쪽을 벡터로 그립니다. 이 PC에 한글 글꼴(Windows의 맑은 고딕)이 있으면 쓴 글자만 파일에 넣고, 없으면 PDF 보기 프로그램이 가진 한글 고딕 이름을 적습니다.
- **묶음(zip)**: PowerPoint와 PDF, 그릴 수 있는 다이어그램 전부(SVG), 스냅샷의 캡처 전부(PNG), 수치 표(`수치.csv`, 엑셀에서 열림).

다이어그램은 슬라이드에서 제목 없이 그림만 놓이고, 범례와 수치 줄은 슬라이드에서 읽히는 크기(10 pt)로 그림 아래에 따로 놓입니다(`diagram_svg.layout(drawing, words=False)`, `diagram_svg.words`). 모양은 일부러 담백합니다(흰 바탕, 먹색 글, 가는 줄 하나). 슬라이드 템플릿은 디자인 담당과 맞출 자리입니다.

## 화면

발표 편집자 화면의 "발표자료" 탭(`#/project/{name}/expert/presentation_editor/slides`)이 슬라이드를 작은 쪽으로 보여 주고, 순서가 어디서 왔는지, 어느 라이노 작업의 그림인지, 무엇이 비었는지 알려 줍니다. "PowerPoint 받기", "PDF 받기", "그림까지 모두 받기"가 파일을 만듭니다. "결과" 탭은 문서에서 슬라이드 목록 블록을 빼고 보여 줍니다(`model.js`의 `stripSlideList`, `deckView`).
