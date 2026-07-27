#!/usr/bin/env python3
"""User settings and UI strings. Commands stay English; display text follows language."""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_DIR = Path.home() / "Sida"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"
_OLD_SETTINGS_PATH = Path.home() / "ArchitecturalHarness" / "settings.json"
DEFAULT_LANGUAGE = "en"
SUPPORTED = ("en", "ko")

# Display strings only. Slash commands (/help, /quit, ...) stay English always.
STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "welcome_title": "Sida",
        "welcome_body": (
            "A CLI prototype for architectural design reasoning.\n"
            "Chat with the Conductor and run modules only when needed."
        ),
        "lang_title": "Language",
        "lang_prompt": (
            "Choose UI language.\n"
            "  1) English\n"
            "  2) Korean  (commands stay in English: /help, /quit, /run ...)\n"
        ),
        "lang_input": "Select [1/2] (default 1): ",
        "lang_saved": "Language saved: English",
        "lang_saved_ko": "Language saved: Korean (UI Korean / commands English)",
        "api_missing": "API key is not set yet.",
        "api_title": "OpenRouter API key setup",
        "api_intro": (
            "This program calls LLMs through OpenRouter.\n"
            "You need an API key to run the Conductor and modules.\n"
            "\n"
            "[1] Open this URL in your browser:\n"
            "    https://openrouter.ai/keys\n"
            "\n"
            "[2] Sign up / log in, then Create Key.\n"
            "    (The key looks like sk-or-...)\n"
            "\n"
            "[3] Paste the key below.\n"
            "    - It will not be shown while typing.\n"
            "    - Saved only in this computer's .env file.\n"
            "    - Do not upload it to public repos."
        ),
        "api_current_overwrite": "Current key: {masked} (will be overwritten)",
        "api_paste": "Paste API key (cancel: press Enter): ",
        "api_too_short": "Key looks too short. Please check your OpenRouter key.",
        "api_cancelled": "Setup cancelled.",
        "api_verifying": "Verifying API key with OpenRouter...",
        "api_ok": "Done! API key works.",
        "api_ok_detail": "Saved to: {path}\nMasked: {masked}",
        "api_fail": "API key check failed. Please try again.",
        "api_fail_detail": "Reason: {reason}",
        "api_retry": "Try again? [Y/n]: ",
        "api_exists": "API key already set: {masked}",
        "api_reconfigure": "To reconfigure: python setup.py  or  /setup in chat",
        "api_required": "Cannot run without an API key.\n  Try again: python setup.py",
        "existing_projects": "Existing projects:",
        "resume_hint": "Resume:  python chat.py <project_name>",
        "list_hint": "List:    python chat.py --list",
        "start_sample": "Start with the sample project (sample_brief)?",
        "how_to_start": "How to start:",
        "more_projects": "... and {n} more",
        "hub_title": "Project hub",
        "hub_root": "Projects folder: {path}",
        "hub_empty": "(no projects yet)",
        "hub_menu": (
            "  [number]  open project\n"
            "  n         new project\n"
            "  s         new from sample brief\n"
            "  o         open by name\n"
            "  q         quit"
        ),
        "hub_prompt": "Choose: ",
        "hub_invalid": "Invalid choice.",
        "hub_open_name": "Project name: ",
        "hub_new_name": "New project name: ",
        "hub_brief_path": "Brief markdown path (Enter = empty template): ",
        "hub_created": "Created: {path}",
        "hub_opened": "Opening: {name}",
        "hub_not_found": "Project not found: {name}",
        "hub_closed": "Left project. Back to hub.",
        "hub_goodbye": "Goodbye.",
        "hub_exists": "Project already exists: {name}. Opening it.",
        "brief_title": "Basic project info",
        "brief_intro": "Folder created. Enter basic info for the brief.\n(Press Enter to skip any field — you can fill it later.)",
        "brief_type": "Project type: ",
        "brief_site": "Site: ",
        "brief_problem": "Core problem: ",
        "brief_issues": "Site issues (comma-separated): ",
        "brief_intention": "Design intention: ",
        "brief_direction": "Current design direction: ",
        "brief_saved": "Brief saved: {path}",
        "rename_prompt": "New project name: ",
        "rename_ok": "Renamed: {old} → {new}\nFolder: {path}",
        "rename_fail": "Rename failed: {reason}",
        "session_hint": "Commands: /help  /close (back to hub)  /quit (exit app)",
        "session_saved_close": "Conversation saved. Returning to project hub.",
        "session_saved_quit": "Conversation saved. Bye.",
    },
    "ko": {
        "welcome_title": "시다",
        "welcome_body": (
            "설계 추론을 돕는 CLI 프로토타입입니다.\n"
            "Conductor와 대화하며 필요할 때만 모듈을 실행합니다."
        ),
        "lang_title": "언어",
        "lang_prompt": (
            "UI 언어를 선택하세요.\n"
            "  1) English\n"
            "  2) 한국어  (명령어는 영어 유지: /help, /quit, /run ...)\n"
        ),
        "lang_input": "선택 [1/2] (기본 1): ",
        "lang_saved": "언어 저장됨: English",
        "lang_saved_ko": "언어 저장됨: 한국어 (화면 한국어 / 명령어 영어)",
        "api_missing": "API 키가 아직 설정되지 않았습니다.",
        "api_title": "OpenRouter API 키 설정",
        "api_intro": (
            "이 프로그램은 OpenRouter를 통해 LLM을 호출합니다.\n"
            "API 키가 있어야 Conductor와 모듈을 실행할 수 있습니다.\n"
            "\n"
            "[1] 브라우저에서 아래 주소를 엽니다.\n"
            "    https://openrouter.ai/keys\n"
            "\n"
            "[2] 회원가입 / 로그인 후 Create Key 로 키를 만듭니다.\n"
            "    (키가 sk-or-... 형태로 보입니다)\n"
            "\n"
            "[3] 아래에 키를 붙여넣습니다.\n"
            "    - 입력 중에는 화면에 표시되지 않습니다.\n"
            "    - 키는 이 컴퓨터의 .env 파일에만 저장됩니다.\n"
            "    - GitHub 등 공개 저장소에 올리지 마세요."
        ),
        "api_current_overwrite": "현재 키: {masked} (덮어씁니다)",
        "api_paste": "API 키 붙여넣기 (취소: Enter만 누르기): ",
        "api_too_short": "키가 너무 짧습니다. OpenRouter 키를 다시 확인해주세요.",
        "api_cancelled": "설정이 취소되었습니다.",
        "api_verifying": "OpenRouter에서 API 키를 확인하는 중...",
        "api_ok": "완료! API 키가 정상적으로 확인되었습니다.",
        "api_ok_detail": "저장 위치: {path}\n확인용 표시: {masked}",
        "api_fail": "API 키 확인에 실패했습니다. 다시 시도해주세요.",
        "api_fail_detail": "사유: {reason}",
        "api_retry": "다시 시도할까요? [Y/n]: ",
        "api_exists": "이미 설정된 키가 있습니다: {masked}",
        "api_reconfigure": "다시 설정: python setup.py  또는 채팅에서 /setup",
        "api_required": "API 키 없이 실행할 수 없습니다.\n  다시 시도: python setup.py",
        "existing_projects": "기존 프로젝트:",
        "resume_hint": "이어하기:  python chat.py <프로젝트이름>",
        "list_hint": "목록 보기: python chat.py --list",
        "start_sample": "샘플 프로젝트(sample_brief)로 시작할까요?",
        "how_to_start": "시작 방법:",
        "more_projects": "... 외 {n}개",
        "hub_title": "프로젝트 허브",
        "hub_root": "프로젝트 폴더: {path}",
        "hub_empty": "(아직 프로젝트 없음)",
        "hub_menu": (
            "  [번호]     프로젝트 열기\n"
            "  n         새 프로젝트\n"
            "  s         샘플 브리프로 새 프로젝트\n"
            "  o         이름으로 열기\n"
            "  q         종료"
        ),
        "hub_prompt": "선택: ",
        "hub_invalid": "잘못된 선택입니다.",
        "hub_open_name": "프로젝트 이름: ",
        "hub_new_name": "새 프로젝트 이름: ",
        "hub_brief_path": "브리프 md 경로 (Enter = 빈 템플릿): ",
        "hub_created": "생성됨: {path}",
        "hub_opened": "여는 중: {name}",
        "hub_not_found": "프로젝트 없음: {name}",
        "hub_closed": "프로젝트에서 나왔습니다. 허브로 돌아갑니다.",
        "hub_goodbye": "종료합니다.",
        "hub_exists": "이미 있는 프로젝트입니다: {name}. 엽니다.",
        "brief_title": "기본 프로젝트 정보",
        "brief_intro": "폴더가 만들어졌습니다. 브리프 기본 정보를 입력하세요.\n(Enter로 건너뛰기 가능 — 나중에 채워도 됩니다)",
        "brief_type": "프로젝트 유형: ",
        "brief_site": "사이트: ",
        "brief_problem": "핵심 문제: ",
        "brief_issues": "사이트 이슈 (쉼표로 구분): ",
        "brief_intention": "설계 의도: ",
        "brief_direction": "현재 설계 방향: ",
        "brief_saved": "브리프 저장됨: {path}",
        "rename_prompt": "새 프로젝트 이름: ",
        "rename_ok": "이름 변경: {old} → {new}\n폴더: {path}",
        "rename_fail": "이름 변경 실패: {reason}",
        "session_hint": "명령: /help  /close (허브로)  /quit (앱 종료)",
        "session_saved_close": "대화 저장됨. 프로젝트 허브로 돌아갑니다.",
        "session_saved_quit": "대화 저장됨. 종료합니다.",
    },
}


def load_settings() -> dict:
    path = SETTINGS_PATH
    if not path.exists() and _OLD_SETTINGS_PATH.exists():
        path = _OLD_SETTINGS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(data: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(data)
    SETTINGS_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_language() -> str:
    lang = str(load_settings().get("language", "")).lower()
    return lang if lang in SUPPORTED else DEFAULT_LANGUAGE


def set_language(lang: str) -> str:
    lang = lang.lower()
    if lang not in SUPPORTED:
        lang = DEFAULT_LANGUAGE
    save_settings({"language": lang})
    return lang


def has_language() -> bool:
    return load_settings().get("language") in SUPPORTED


def t(key: str, **kwargs: object) -> str:
    lang = get_language()
    table = STRINGS.get(lang) or STRINGS[DEFAULT_LANGUAGE]
    text = table.get(key) or STRINGS[DEFAULT_LANGUAGE].get(key) or key
    if kwargs:
        return text.format(**kwargs)
    return text
