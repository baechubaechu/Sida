# 개발 환경 세팅

Sida를 처음 개발하는 팀원을 위한 세팅 순서입니다. 어떤 편집기나 AI 에이전트(Claude Code, Cursor, Codex, Copilot 등)를 쓰든 1~5단계는 같고, 6단계에서 쓰는 도구에 맞는 부분만 보면 됩니다.

팀 규칙(브랜치, 커밋, PR)은 [`CONTRIBUTING.md`](../CONTRIBUTING.md)에 있습니다.

## 에이전트로 세팅하기

AI 에이전트를 쓴다면 빈 폴더를 에이전트로 열고 아래 메시지를 그대로 붙여 넣으세요. 에이전트가 clone부터 테스트까지 진행하고, GitHub 로그인과 API 키 입력만 직접 하면 됩니다.

```text
이 빈 폴더에 Sida 저장소를 받아서 개발 환경을 세팅해 줘.

1. 현재 폴더에 clone해: git clone https://github.com/baechubaechu/Sida.git .
2. clone한 뒤 AGENTS.md를 먼저 읽고, 이 저장소에서 작업하는 동안 그 규칙을 따라.
3. docs/dev-setup.md를 읽고 1~5단계를 순서대로 진행해.
   - 필요한 프로그램(Git, Python 3.10+, GitHub CLI)이 설치돼 있는지 먼저 확인하고, 없으면 설치 명령을 알려 줘.
   - git config core.hooksPath .githooks 설정, .venv 생성, pip install -e ".[dev]"까지 해 줘.
4. 아래 두 가지는 내가 직접 할 테니, 실행할 명령만 알려 주고 기다려.
   - GitHub 로그인(gh auth login)
   - 첫 실행(python chat.py): 실행 모드(클라우드/로컬) 선택과 API 키 입력. 키를 대화창에 붙여 넣으라고 하지 마.
5. 마지막에 ruff check . 와 pytest를 돌려서 결과를 알려 줘.
6. 커밋, push, 브랜치 생성은 하지 마. 세팅만 해.
```

직접 세팅한다면 아래 1~5단계를 따라 하세요.

## 1. 필요한 프로그램

| 프로그램 | 용도 | 설치 (Windows) |
|---|---|---|
| Git | 버전 관리 | `winget install --id Git.Git -e` |
| Python 3.10 이상 | 실행, 테스트 | `winget install --id Python.Python.3.12 -e` 또는 python.org (설치 시 "Add python.exe to PATH" 체크) |
| GitHub CLI (`gh`) | 터미널·에이전트에서 PR 열기 | `winget install --id GitHub.cli -e` |

macOS는 `brew install git python gh`로 설치합니다.

설치 후 새 터미널을 열어 확인합니다.

```bash
git --version
python --version    # 3.10 이상
gh --version
```

## 2. 저장소 받기와 Git 설정

```bash
git clone https://github.com/baechubaechu/Sida.git
cd Sida
git config core.hooksPath .githooks
```

- `core.hooksPath`: `main`에서 `git pull`할 때 머지된 로컬 브랜치를 자동으로 지우는 hook(`.githooks/post-merge`)을 켭니다. clone마다 한 번 필요합니다.
- 커밋 작성자 정보가 없다면 설정합니다.

```bash
git config --global user.name "GitHub 아이디"
git config --global user.email "GitHub에 등록한 이메일"
```

## 3. GitHub 로그인

PR을 열고 CI 결과를 보려면 `gh` 로그인이 필요합니다. 에이전트가 PR을 대신 열 때도 이 로그인을 씁니다.

```bash
gh auth login --web --git-protocol https
```

터미널에 나온 코드를 브라우저 인증 페이지에 입력하고 **Authorize**를 누릅니다. `gh auth status`에 `Logged in`이 나오면 됩니다.

PowerShell에서 설치 직후 `gh`를 찾지 못하면 터미널을 새로 열거나 전체 경로로 실행합니다.

```powershell
& "C:\Program Files\GitHub CLI\gh.exe" auth login --web --git-protocol https
```

## 4. Python 환경과 API 키

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"           # 실행 의존성 + pytest, ruff
python chat.py                    # 첫 실행: 언어 → 실행 모드(클라우드/로컬) → 필요하면 API 키
```

- 첫 실행 때 **클라우드(OpenRouter)** 와 **로컬(Ollama)** 중 하나를 고릅니다. 답은 이 PC 전용 파일 `config.local.yaml`에 저장되고 Git에 올라가지 않습니다. 나중에 허브에서 `c`(설정) → `9`로 바꿀 수 있습니다.
  - 클라우드: OpenRouter API 키가 필요합니다. GPU는 필요 없습니다.
  - 로컬: [Ollama](https://ollama.com) 설치와 GPU(VRAM 8GB 이상)가 필요합니다. 키와 비용은 없습니다. 자세한 내용은 [`gpu_tiers.md`](gpu_tiers.md).
- `config.yaml`은 팀 공통 기본값입니다. 개인 설정을 여기에 고쳐서 커밋하지 않습니다.
- 법령 검색은 기본으로 꺼져 있습니다. `.env`에 `LAW_OPEN_API_OC`를 넣고 허브 `c`(설정) → `4`로 켭니다. 법제처를 직접 호출하므로 별도 서버가 필요 없습니다.
- 키를 직접 넣으려면 `.env.example`을 `.env`로 복사해 채웁니다. `.env`는 커밋되지 않습니다.
- 테스트는 API 키 없이 돌아갑니다(가짜 응답 사용).
- PowerShell에서 `activate`가 "스크립트를 실행할 수 없습니다"로 막히면 명령 프롬프트(cmd)에서 실행하거나, 활성화 없이 `.venv\Scripts\python.exe -m pip ...`처럼 venv의 Python을 직접 씁니다.
- conda를 쓰고 있다면 `(base)` 환경이 켜진 채로 venv를 만들어도 됩니다. 다만 이후 명령은 venv를 활성화한 상태에서 실행합니다.

### 대지 조회용 키

`/site <주소>`로 필지와 용도지역을 조회하려면 정부 API 키가 필요합니다. 키는 팀에서 전달받아 `.env`에 넣습니다. 저장소, PR, 이슈에는 올리지 않습니다. 키가 없어도 나머지 기능과 테스트는 그대로 동작합니다.

```
VWORLD_API_KEY=
VWORLD_DOMAIN=http://localhost:8765
DATA_GO_KR_API_KEY=
LAW_OPEN_API_OC=
```

| 변수 | 발급처 | 지금 쓰는 곳 |
|---|---|---|
| `VWORLD_API_KEY`, `VWORLD_DOMAIN` | vworld.kr → 오픈API → 인증키 발급 | 주소 검색, 용도지역·지구, 토지 특성 |
| `DATA_GO_KR_API_KEY` | data.go.kr → 마이페이지 → 인증키 (Decoding 키) | 다음 단계: 행위제한, 근거 조문, 건축물대장 |
| `LAW_OPEN_API_OC` | open.law.go.kr → OPEN API 신청 | 법령 검색(허브 `l`, `regulation_checker`). 이후 단계: 조례 조문 원문 |

직접 발급할 때 알아 둘 것:

- **브이월드**: 발급할 때 등록한 서비스 주소를 `VWORLD_DOMAIN`에 그대로 넣습니다. 활용 API는 검색, 지오코더, 2D데이터, 국가중점, WMS/WFS를 고릅니다. 개발키는 6개월짜리이고 3회 연장할 수 있습니다. 만료되면 `/site`가 "키를 거부했습니다"라고 알립니다.
- **공공데이터포털**: 키는 계정당 하나이고 서비스마다 활용신청을 합니다(토지이용규제정보서비스, 토지이용규제법령정보서비스, 건축HUB 건축물대장정보). 토지이음 계열 두 서비스는 요청에 `Accept: application/xml` 헤더가 없으면 `HTTP_ERROR`(코드 04)를 돌려줍니다.
- **법제처**: OC 값은 신청할 때 직접 정하는 문자열입니다. IP를 등록하면 그 IP에서만 호출됩니다. 신청 목록에서 "지능형 법령검색 시스템 검색 API"(XML, JSON)를 체크해야 법령 검색이 됩니다. 빠져 있으면 "지능형 검색 API를 신청하지 않았습니다"라는 경고가 나옵니다.

## 5. 확인

```bash
ruff check .
pytest
```

둘 다 통과하면 세팅이 끝났습니다. CI도 같은 검사를 하고, 통과하지 않은 PR은 머지되지 않습니다.

앱을 실행해 보려면 `python chat.py`(Windows는 `run.bat`)를 실행합니다.

## 6. AI 에이전트 / 편집기별 설정

에이전트용 공통 규칙은 저장소 루트의 [`AGENTS.md`](../AGENTS.md) 하나에 있습니다. 여러 에이전트가 공통으로 읽는 파일 이름이라, 대부분의 도구는 저장소 폴더를 열기만 하면 자동으로 적용됩니다.

| 도구 | 읽는 규칙 파일 | 할 일 |
|---|---|---|
| Claude Code | `CLAUDE.md` → `AGENTS.md`를 불러옴 | 없음 |
| Cursor | `AGENTS.md` + `.cursor/rules/*.mdc` | 없음 |
| Codex, Copilot 등 `AGENTS.md`를 지원하는 도구 | `AGENTS.md` | 없음 |
| `AGENTS.md`를 읽지 않는 도구 (예: Gemini CLI 기본 설정) | 도구 전용 파일 | 도구 설정에서 규칙 파일을 `AGENTS.md`로 지정하거나, 작업을 맡길 때 "`AGENTS.md` 규칙을 따라"라고 알려 주세요. |

규칙을 고칠 때는 `AGENTS.md`만 고칩니다. 도구별 파일에 같은 내용을 복사하지 않습니다.

어떤 에이전트를 쓰든 지켜야 할 것:

- **작업은 항상 최신 `main`에서 새 브랜치로.** `main`에 직접 커밋하지 않습니다.
- **기능을 바꾸면 테스트도 같이.** 승인 없이 CI만으로 머지되므로 테스트가 안전장치입니다.
- **커밋·push는 본인이 요청했을 때만** 하도록 에이전트에 맡깁니다.
- **API 키를 에이전트 대화나 커밋에 넣지 않습니다.** 키는 `.env`에만 둡니다.

### 한 폴더에서 에이전트 두 개를 동시에 쓰지 않기

한 폴더에서는 한 번에 한 브랜치만 열 수 있습니다. Cursor와 Claude Code처럼 두 도구가 같은 폴더에서 동시에 작업하면 이런 일이 생깁니다.

- 한쪽이 작업 중인 변경이 다른 쪽에 "커밋 안 된 변경"으로 보입니다.
- 한쪽이 브랜치를 바꾸면 다른 쪽 작업 브랜치도 같이 바뀝니다.

이때 뜨는 "커밋 안 된 변경"을 그냥 커밋하지 마세요. 먼저 어떤 파일인지 확인합니다.

두 도구를 동시에 쓰려면 Git worktree로 작업 폴더를 나눕니다. 같은 저장소를 브랜치별로 다른 폴더에 엽니다.

```bash
git worktree add ../Sida-feat-x -b feat/x    # 새 폴더에서 새 브랜치
git worktree list
git worktree remove ../Sida-feat-x            # 작업이 머지된 뒤 정리
```

팀원끼리는 각자 자기 PC에 clone해서 쓰므로 이 문제가 생기지 않습니다. 팀원과는 GitHub의 PR에서만 만납니다.

## 7. 자주 생기는 문제

**파일 내용은 그대로인데 전체가 바뀐 것처럼 보임**
: 줄바꿈 차이(CRLF/LF)입니다. 저장소는 `.gitattributes`로 LF를 씁니다(`.bat`만 CRLF). `git status`에 변경이 없다면 커밋할 필요가 없습니다. 작업 중인 변경이 없을 때 파일을 다시 받으면 정리됩니다.

```bash
git rm -r --cached -q . && git reset --hard -q
```

(작업 중인 변경이 있으면 모두 사라지니, 반드시 `git status`가 깨끗할 때만 실행합니다.)

**push가 거부됨 (Push protection)**
: 커밋에 API 키가 들어 있습니다. 해당 커밋에서 키를 빼고, 키는 재발급합니다.

**PR이 머지되지 않고 "Update branch"가 뜸**
: PR 브랜치가 `main`보다 뒤처졌습니다. 버튼을 누르거나 `git merge main` 후 push하면 CI가 다시 돌고 자동 머지됩니다.

**머지된 브랜치에서 계속 작업했음**
: squash 머지라 같은 브랜치로 다음 PR을 열면 이미 들어간 커밋이 섞입니다. 변경을 옮겨서 새 브랜치로 올립니다.

```bash
git stash
git switch main && git pull
git switch -c feat/새-작업
git stash pop
```
