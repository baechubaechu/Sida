# Sida 라이노 플러그인

라이노 8(Windows)용 플러그인입니다. 앱 패키지(`sida/`)에는 들어가지 않습니다(`relay/`, `collector/`와 같은 방식). 하는 일은 운반과 캡처뿐입니다.

- `SidaPull`: 이 문서의 Sida 프로젝트 제도판(대지 경계, 매스안, 주변 3D, 지형)을 `Sida` 레이어 아래로 가져옵니다. 전에 가져온 개체(사용자 문자열 `sida.id`가 있는 것)는 바꾸고, 설계자가 만든 개체는 건드리지 않습니다. 가져온 뒤 설계자가 옮기거나 고친 개체도 설계자의 것으로 보고 그대로 둡니다. 주변·대지 경계 레이어에는 의미를 미리 붙여 둡니다. 좌표는 Sida 내보내기와 같은 틀(원점 대지 가운데, m)을 문서 단위로 바꿔 둡니다.
- `SidaPush`: 건물 의미를 준 레이어의 보이는 입체마다 라이노가 잰 값(부피, 바닥 단면 외곽선(중정은 뚫린 곳으로), 층고마다 자른 층별 면적, 높이)과 평면·투시 뷰 캡처를 스냅샷으로 Sida에 보냅니다. 수치(연면적·건폐율·용적률)는 Sida가 계산해 돌려줍니다(`docs/rhino-api.md`).
- `SidaPanel`: 패널. 프로젝트 고르기(문서에 저장), 레이어마다 의미·층고, 가져오기·보내기·수치만 보기.

레이어 의미와 층고는 레이어의 사용자 문자열(`sida.meaning`, `sida.floor_height`)에, 프로젝트는 문서 문자열(`sida.project`)에 저장되어 파일을 다시 열어도 남습니다.

v1에서 아직 안 되는 것(설계상): 바닥 외곽선은 가장 낮은 점 5cm 위 단면이라 위층이 튀어나온 부분은 건축면적에서 빠집니다. 층고를 정하지 않은 레이어의 개체는 층별 면적이 없어 연면적에서 빠지고 Sida가 그렇게 알려 줍니다. 블록(인스턴스)은 열어 보지 않습니다. 캡처는 평면(Top)·투시(Perspective) 뷰 그대로입니다.

## 빌드

필요한 것: .NET SDK 8. RhinoCommon은 NuGet에서 받으므로 빌드에 라이노도 Windows도 필요하지 않습니다(대상은 `net7.0`, Linux에서도 빌드됩니다). PR마다 GitHub Actions(`rhino-plugin.yml`)가 빌드해 `.rhp`를 결과물로 올립니다.

```powershell
cd rhino-plugin\SidaRhino
dotnet build -c Release
# → bin\Release\net7.0\SidaRhino.rhp
```

라이노에서 시험: `PlugInManager` → 설치 → 위 `.rhp`. 또는 라이노 명령창에서 `_-PlugInManager _Load`로 경로를 줍니다. 그 뒤 `SidaPanel`.

Sida 앱이 같은 PC에서 `run.bat`으로 떠 있어야 합니다(`127.0.0.1:8765`). 다른 주소면 환경 변수 `SIDA_URL`.

## Yak 패키지 (CBT 배포)

```powershell
mkdir dist; copy SidaRhino\bin\Release\net7.0\SidaRhino.rhp dist\; copy manifest.yml dist\
cd dist; & "C:\Program Files\Rhino 8\System\Yak.exe" build
```

만들어진 `sida-0.1.0-rh8_0-any.yak`을 라이노 패키지 관리자(`PackageManager`)에서 설치하거나, CBT 참가자에게 파일로 줍니다.

## 한 사이클 시험 순서 (무교동 45)

1. Sida에서 대지 조회, 매스안 하나(블록 2개).
2. 라이노 8 빈 문서(단위 m 또는 mm) → `SidaPanel` → 프로젝트 고르기 → "Sida에서 가져오기". 대지 경계·매스·주변 3D가 같은 자리에 들어오는지.
3. 블록 하나를 밀고 층을 올리고, 새 레이어에 곡선 매스를 하나 더. 패널에서 레이어 의미(주거·상업)와 층고를 지정.
4. "수치만 보기": 연면적·건폐율·용적률이 손계산과 같은지. "Sida로 보내기": Sida 제도판에 "라이노 작업" 종이가 생기는지.
5. 같은 파일에서 다시 "Sida에서 가져오기": 설계자 레이어가 그대로인지.
6. Sida를 끄고 "Sida로 보내기": 패널에 한국어 안내가 나오고 라이노가 멈추지 않는지.
