#!/usr/bin/env python3
"""User settings and UI strings. Commands stay English; display text follows language.

Default language is Korean. English is the fallback for any missing key.
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_DIR = Path.home() / "Sida"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"
_OLD_SETTINGS_PATH = Path.home() / "ArchitecturalHarness" / "settings.json"
DEFAULT_LANGUAGE = "ko"
FALLBACK_LANGUAGE = "en"
SUPPORTED = ("ko", "en")

SETUP_CMD = "python setup_env.py"

# Display strings only. Slash commands (/help, /quit, ...) stay English always.
STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # --- app / setup
        "welcome_title": "Sida",
        "welcome_body": (
            "A CLI prototype for architectural design reasoning.\n"
            "Chat with the Conductor and run modules only when needed."
        ),
        "lang_title": "Language / 언어",
        "lang_prompt": (
            "Choose UI language. / UI 언어를 선택하세요.\n"
            "  1) 한국어  (명령어는 영어 유지: /help, /quit, /run ...)\n"
            "  2) English\n"
        ),
        "lang_input": "Select [1/2] (default 1): ",
        "lang_saved": "Language saved: English",
        "lang_saved_ko": "언어 저장됨: 한국어 (화면 한국어 / 명령어 영어)",
        "api_missing": "API key is not set yet.",
        "api_skip_local": "OpenRouter key not required — Conductor/Worker are local (Ollama).",
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
        "api_reconfigure": f"To reconfigure: {SETUP_CMD}  or  /setup in chat",
        "api_required": f"Cannot run without an API key.\n  Try again: {SETUP_CMD}",
        # --- hub
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
            "  l         regulation search (no project)\n"
            "  m         Rhino modeling (OpenAI GPT-6+ / MCP)\n"
            "  c         settings (provider / RAG / language)\n"
            "  q         quit"
        ),
        "hub_runtime": "Runtime: {summary}",
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
        "hub_projects_list": "Projects:",
        # --- hub settings
        "set_title": "Settings",
        "set_menu": (
            "  1) Conductor provider   (ollama / openrouter / mock)\n"
            "  2) Worker provider\n"
            "  3) Local GPU profile    (local 8GB / local_plus 12GB+)\n"
            "  4) RAG on/off\n"
            "  5) State update mode    (ask / auto / off)\n"
            "  6) OpenRouter API key\n"
            "  7) OpenAI API key       (Rhino modeling)\n"
            "  8) UI language\n"
            "  0) back"
        ),
        "set_prompt": "Settings: ",
        "set_cancel": "cancel",
        "set_confirm": "Apply? [Y/n]: ",
        "set_toggle": "Toggle {cur} → {nxt}",
        "set_pick_conductor": "Conductor provider:",
        "set_pick_worker": "Worker provider:",
        "set_pick_profile": "Local profile (Ollama):",
        "set_pick_state": "State update mode:",
        "set_saved": "Saved: {what}",
        "set_line_conductor": "Conductor:  {provider} / {profile} → {model}",
        "set_line_worker": "Worker:     {provider} → {model}",
        "set_line_rag": "RAG:        {enabled} ({provider})",
        "set_line_state": "State:      mode={mode} via {provider}",
        "set_line_lang": "Language:   {lang}",
        "set_line_openrouter": "OpenRouter: {status}",
        "set_or_needed": "key required for current providers",
        "set_or_skip": "not required (local/mock)",
        "busy_role": "Waiting on {role} …",
        "busy_conductor": "Conductor thinking …",
        "busy_worker": "Running {name} …",
        "busy_worker_retry": "Retrying {name} (fix headers) …",
        "busy_recovery": "Recovering action block …",
        "busy_state": "Updating project state from {name} …",
        "busy_rag": "Retrieving regulations (RAG) …",
        "busy_law": "Looking up regulations …",
        "law_title": "Regulation search",
        "law_intro": (
            "Ask about building / planning codes anytime — no design project needed.\n"
            "For context control, each question stands alone: prior questions are not "
            "added to the search/answer context. Restate the statute or article each time."
        ),
        "law_rag_off": "Warning: RAG is off in settings. Answers will lack retrieved passages.",
        "law_hint": "Type a full question. /back (or q) returns to the hub.",
        "law_prompt": "Law Q: ",
        "law_label": "Answer: ",
        "law_sources": "Sources:",
        "law_no_passages": "(no passages retrieved — answer is agenda-level only)",
        "law_cleared": "Conversation cleared.",
        "law_no_session_context": (
            "No session context is kept — each question is already independent."
        ),
        "law_bye": "Back to hub.",
        "law_failed": "Lookup failed: {reason}",
        "law_boot_failed": "Could not start regulation search: {reason}",
        "law_chunk_truncated": (
            "Note: some passages look truncated (~1k chars). "
            "Long articles may be incomplete in the index — check the full text on law.go.kr."
        ),
        "busy_modeling": "Rhino modeler thinking …",
        "modeling_title": "Rhino modeling",
        "modeling_intro": "OpenAI {model} (GPT-6+) + Rhino MCP. Separate from design projects.",
        "modeling_hint": "Needs OPENAI_API_KEY. Describe geometry. /ctx /clear /back.",
        "modeling_model_too_old": (
            "Modeling requires GPT-{min_major}+ (got '{model}'). "
            "Set modeling.model to something like {example}."
        ),
        "modeling_prompt": "Model: ",
        "modeling_label": "Modeler: ",
        "modeling_calling": "→ MCP {tool}",
        "modeling_dry_call": "(dry-run) would call {tool}",
        "modeling_dry_mode": "MCP offline — planning only (scripts not executed).",
        "modeling_mcp_ok": "Rhino MCP: {cmd}",
        "modeling_mcp_fail": "Rhino MCP failed: {reason}",
        "modeling_slots": "Slots: {detail}",
        "modeling_slots_fail": "list_slots: {reason}",
        "modeling_cleared": "Conversation cleared.",
        "modeling_bye": "Back to hub.",
        "modeling_failed": "Modeling failed: {reason}",
        "modeling_boot_failed": "Could not start modeler: {reason}",
        "modeling_round_limit": "Stopped after max tool rounds.",
        "openai_guide_title": "OpenAI API key (Rhino modeling)",
        "openai_guide_body": (
            "  Create a key at https://platform.openai.com/api-keys\n"
            "  Saved only in this computer's .env as OPENAI_API_KEY.\n"
            "  Used only for hub → m modeling (not Conductor/Worker)."
        ),
        "openai_current_overwrite": "Current key: {masked} (will overwrite)",
        "openai_exists": "OpenAI key on file: {masked}",
        "openai_reconfigure": "Reconfigure anytime: hub → c → 7",
        "openai_missing": "OpenAI API key required for Rhino modeling.",
        "openai_required": "OpenAI API key is required for modeling.",
        "openai_cancelled": "Cancelled — no OpenAI key saved.",
        "openai_verifying": "Verifying OpenAI key …",
        "openai_ok": "OpenAI key saved.",
        "openai_ok_detail": "Wrote {path} ({masked})",
        "openai_fail": "OpenAI key check failed.",
        "openai_fail_detail": "{reason}",
        "openai_retry": "Try again? [Y/n]: ",
        # --- brief
        "brief_title": "Basic project info",
        "brief_intro": "Folder created. Enter basic info for the brief.\n(Press Enter to skip any field — you can fill it later.)",
        "brief_type": "Project type: ",
        "brief_site": "Site: ",
        "brief_problem": "Core problem: ",
        "brief_issues": "Site issues (comma-separated): ",
        "brief_intention": "Design intention: ",
        "brief_direction": "Current design direction: ",
        "brief_driver": "Primary driver (site / idea / program / regulation / competition): ",
        "run_path": "Path: {name} → {experts}",
        "brief_saved": "Brief saved: {path}",
        "brief_backup": "Backup: {path}",
        "brief_no_changes": "(no changes)",
        "brief_fields_intro": "Enter = keep current value. Sections not listed here are preserved.",
        "brief_current": "  current: {value}",
        "brief_usage": "Usage: /brief | /brief edit (editor) | /brief fields (guided)",
        # --- editor
        "editor_opening": "Opening {file} in {editor} ... save and close the editor to continue.",
        "editor_unchanged": "No changes detected.",
        "editor_saved": "Saved: {path}",
        "editor_failed": (
            "Could not open an editor ({reason}).\n"
            "Set the EDITOR environment variable, or edit the file directly:\n  {path}"
        ),
        # --- rename
        "rename_prompt": "New project name: ",
        "rename_ok": "Renamed: {old} → {new}\nFolder: {path}",
        "rename_fail": "Rename failed: {reason}",
        # --- session banner
        "sess_projects_root": "Projects root: {path}",
        "sess_project": "Project:       {path}",
        "sess_brief": "Brief:         {path}",
        "sess_modules": "Modules:       {path}",
        "sess_state": "State:         {path}",
        "sess_context": "Context:       last {n} messages + project_state.md",
        "sess_conductor_local": "Conductor:     {provider} / {profile} → {model}{ctx}",
        "sess_conductor_cloud": "Conductor:     {provider} → {model}",
        "ollama_starting": "[ollama] Server not running — starting it ...",
        "ollama_started": "[ollama] Server is ready.",
        "ollama_not_running": (
            "Ollama is not running at {url}.\n"
            "Install from https://ollama.com and open the Ollama app, or set conductor.ollama_autostart: true."
        ),
        "ollama_not_installed": (
            "Ollama was not found on this computer.\n"
            "Install from https://ollama.com , then run this app again."
        ),
        "ollama_start_timeout": (
            "Started Ollama but it did not become ready at {url}.\n"
            "Open the Ollama app manually and retry."
        ),
        "ollama_model_missing": "Ollama model '{model}' is not installed. Run: ollama pull {model}",
        "ollama_model_missing_ask": "[ollama] Model '{model}' is not installed yet.",
        "ollama_pull_prompt": "Download '{model}' now? This may take several minutes. [Y/n]: ",
        "ollama_pulling": "[ollama] Downloading {model} ...",
        "ollama_pulled": "[ollama] Model ready: {model}",
        "ollama_warming": "[ollama] Loading {model} into VRAM ...",
        "ollama_warm": "[ollama] {model} is loaded.",
        "sess_created": "Created new project folder.",
        "sess_resumed": "Resumed existing project folder.",
        "sess_loaded_turns": "Loaded conversation: {n} user turn(s).",
        "session_hint": "Commands: /help  /close (back to hub)  /quit (exit app)",
        "session_saved_close": "Conversation saved. Returning to project hub.",
        "session_saved_quit": "Conversation saved. Bye.",
        "you_prompt": "You: ",
        "conductor_label": "Conductor: ",
        # --- conductor / modules
        "conductor_error": "[conductor] {reason}",
        "conductor_not_sent": "[conductor] Your message was not sent. Try again, or /close to leave.",
        "conductor_unknown_agent": "[conductor] Unknown agent id: {agent}",
        "conductor_unknown_read": "[conductor] Unknown module to read: {agent}",
        "conductor_read_fail": "[conductor] Cannot read {agent}: {reason}.",
        "read_reason_empty": "file is empty or missing",
        "read_reason_limit": "read limit reached for this turn",
        "conductor_reading": "[conductor] Reading modules/{file} ...",
        "action_recovered": "[conductor] Action block was missing; recovered: {action} {agent}",
        "module_running": "[module] Running {name}...",
        "module_saved": "[module] Saved {path}",
        "module_archived": "[module] Previous version archived: {path}",
        "migrate_applied": "[migrate] Updated this project ({n} change(s)):",
        "module_failed": "[module] Failed: {reason}",
        "module_nothing_saved": "[module] Nothing was saved. Try again with /run {agent}.",
        "module_preview": "--- {name} preview ---",
        "module_missing_headers": "[module] Warning: {name} output is missing headers: {headers}",
        "unknown_agent": "Unknown agent: {agent}",
        "run_usage": "Usage: /run <agent_id>",
        # --- info commands
        "project_folder": "Project folder: {path}",
        "project_session": "session_id:     {id}",
        "project_completed": "Completed:      {list}",
        "project_history_turns": "History turns:  {n}",
        "project_state_file": "State file:     {path}",
        "status_completed": "Completed: {list}",
        "status_folder": "Folder:    {path}",
        "status_history": "History:   {path}",
        "status_state": "State:     {path}",
        "state_usage": "Usage: /state | /state edit | /state update [agent_id]",
        "state_proposing": "[state] Proposing project_state.md update from {agent} ...",
        "state_propose_failed": "[state] Could not propose an update: {reason}. Edit with /state edit.",
        "state_no_change": "[state] No changes proposed.",
        "state_applied": "[state] project_state.md updated (backup: project_state.prev.md)",
        "state_apply_prompt": "Apply this update? [Y = yes / n = skip / e = apply then edit]: ",
        "state_skipped": "[state] Skipped. Edit later with /state edit or /state update.",
        "state_update_no_module": "[state] No completed module found. Run a module first, or pass an agent id.",
        "none": "(none)",
        "empty": "(empty)",
        "help_commands": (
            "Commands:\n"
            "  /help              show this help\n"
            "  /project           show current project folder\n"
            "  /rename <name>     rename this project (folder + display name)\n"
            "  /brief             show current brief.md\n"
            "  /brief edit        open brief.md in your editor (backup → brief.prev.md)\n"
            "  /brief fields      update basic brief fields (other sections kept)\n"
            "  /state             show project_state.md (Conductor memory)\n"
            "  /state edit        open project_state.md in your editor\n"
            "  /state update [id] propose a state update from a module output (diff + confirm)\n"
            "  /agents            list modules\n"
            "  /status            show completed modules\n"
            "  /setup             (re)configure OpenRouter API key\n"
            "  /language          change UI language\n"
            "  /run <agent_id>    run a module now (no conductor call)\n"
            "  /close             leave project → back to hub\n"
            "  /quit              exit the app\n"
            "\n"
            "Or just type normally to talk to the Conductor."
        ),
        "help_modules": "Modules:",
        # --- run.py
        "run_project": "Project: {path}",
        "run_step": "[{i}/{n}] Running {name}...",
        "run_outputs": "Outputs saved to {path}/",
        "run_failed": "{name} failed: {reason}\nCompleted modules are saved; rerun to continue.",
        "run_usage_cli": (
            "Usage: python run.py input/project_brief.md\n"
            "       python run.py --path site_driven input/project_brief.md\n"
            "       python run.py projects/project_name\n"
            "       python chat.py input/project_brief.md   # conversational"
        ),
    },
    "ko": {
        # --- app / setup
        "welcome_title": "시다",
        "welcome_body": (
            "설계 추론을 돕는 CLI 프로토타입입니다.\n"
            "Conductor와 대화하며 필요할 때만 모듈을 실행합니다."
        ),
        "lang_title": "언어 / Language",
        "lang_prompt": (
            "UI 언어를 선택하세요. / Choose UI language.\n"
            "  1) 한국어  (명령어는 영어 유지: /help, /quit, /run ...)\n"
            "  2) English\n"
        ),
        "lang_input": "선택 [1/2] (기본 1): ",
        "lang_saved": "Language saved: English",
        "lang_saved_ko": "언어 저장됨: 한국어 (화면 한국어 / 명령어 영어)",
        "api_missing": "API 키가 아직 설정되지 않았습니다.",
        "api_skip_local": "OpenRouter 키 불필요 — Conductor/Worker가 로컬(Ollama)입니다.",
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
        "api_reconfigure": f"다시 설정: {SETUP_CMD}  또는 채팅에서 /setup",
        "api_required": f"API 키 없이 실행할 수 없습니다.\n  다시 시도: {SETUP_CMD}",
        # --- hub
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
            "  l         건축법령 검색 (프로젝트 없이)\n"
            "  m         라이노 모델링 (OpenAI GPT-6+ / MCP)\n"
            "  c         설정 (provider / RAG / 언어)\n"
            "  q         종료"
        ),
        "hub_runtime": "런타임: {summary}",
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
        "hub_projects_list": "프로젝트:",
        # --- hub settings
        "set_title": "설정",
        "set_menu": (
            "  1) Conductor provider   (ollama / openrouter / mock)\n"
            "  2) Worker provider\n"
            "  3) 로컬 GPU 프로필       (local 8GB / local_plus 12GB+)\n"
            "  4) RAG 켜기/끄기\n"
            "  5) State 갱신 모드       (ask / auto / off)\n"
            "  6) OpenRouter API 키\n"
            "  7) OpenAI API 키         (라이노 모델링)\n"
            "  8) UI 언어\n"
            "  0) 뒤로"
        ),
        "set_prompt": "설정: ",
        "set_cancel": "취소",
        "set_confirm": "적용할까요? [Y/n]: ",
        "set_toggle": "{cur} → {nxt} 로 바꿀까요?",
        "set_pick_conductor": "Conductor provider:",
        "set_pick_worker": "Worker provider:",
        "set_pick_profile": "로컬 프로필 (Ollama):",
        "set_pick_state": "State 갱신 모드:",
        "set_saved": "저장됨: {what}",
        "set_line_conductor": "Conductor:  {provider} / {profile} → {model}",
        "set_line_worker": "Worker:     {provider} → {model}",
        "set_line_rag": "RAG:        {enabled} ({provider})",
        "set_line_state": "State:      mode={mode} / {provider}",
        "set_line_lang": "언어:       {lang}",
        "set_line_openrouter": "OpenRouter: {status}",
        "set_or_needed": "현재 provider에 키 필요",
        "set_or_skip": "불필요 (로컬/mock)",
        "busy_role": "{role} 응답 대기 중 …",
        "busy_conductor": "Conductor 생각 중 …",
        "busy_worker": "{name} 실행 중 …",
        "busy_worker_retry": "{name} 재시도 중 (헤더 보정) …",
        "busy_recovery": "action 블록 복구 중 …",
        "busy_state": "{name} 결과로 project_state 갱신 중 …",
        "busy_rag": "법규 RAG 검색 중 …",
        "busy_law": "법령 검색 중 …",
        "law_title": "건축법령 검색",
        "law_intro": (
            "설계 프로젝트 없이, 건축·도시계획 법령을 아무 때나 물을 수 있습니다.\n"
            "컨텍스트 관리를 위해 이전 질문은 검색·답변 컨텍스트에 넣지 않습니다. "
            "법령명·조항을 매 질문마다 다시 적어 주세요."
        ),
        "law_rag_off": "경고: 설정에서 RAG가 꺼져 있습니다. 검색 조문 없이 답할 수 있습니다.",
        "law_hint": "질문을 입력하세요. /back (또는 q) 는 허브로.",
        "law_prompt": "법령 Q: ",
        "law_label": "답변: ",
        "law_sources": "출처:",
        "law_no_passages": "(검색된 조문 없음 — 아젠다 수준 안내만 가능)",
        "law_cleared": "대화를 비웠습니다.",
        "law_no_session_context": (
            "세션 컨텍스트를 쌓지 않습니다 — 질문마다 이미 독립입니다."
        ),
        "law_bye": "허브로 돌아갑니다.",
        "law_failed": "검색 실패: {reason}",
        "law_boot_failed": "법령 검색을 시작할 수 없습니다: {reason}",
        "law_chunk_truncated": (
            "참고: 일부 조문이 약 1천 자로 잘린 채 옵니다. "
            "긴 조항은 인덱스에 뒷부분이 없을 수 있으니 law.go.kr 원문을 확인하세요."
        ),
        "busy_modeling": "라이노 모델러 생각 중 …",
        "modeling_title": "라이노 모델링",
        "modeling_intro": "OpenAI {model} (GPT-6+) + Rhino MCP. 설계 프로젝트와 별도입니다.",
        "modeling_hint": "OPENAI_API_KEY 필요. 만들 기하를 말하세요. /ctx /clear /back.",
        "modeling_model_too_old": (
            "모델링은 GPT-{min_major}+ 만 가능합니다 (현재 '{model}'). "
            "modeling.model 을 {example} 같이 바꾸세요."
        ),
        "modeling_prompt": "모델링: ",
        "modeling_label": "모델러: ",
        "modeling_calling": "→ MCP {tool}",
        "modeling_dry_call": "(dry-run) {tool} 호출 예정",
        "modeling_dry_mode": "MCP 없음 — 계획만 (스크립트 미실행).",
        "modeling_mcp_ok": "Rhino MCP: {cmd}",
        "modeling_mcp_fail": "Rhino MCP 실패: {reason}",
        "modeling_slots": "슬롯: {detail}",
        "modeling_slots_fail": "list_slots: {reason}",
        "modeling_cleared": "대화를 비웠습니다.",
        "modeling_bye": "허브로 돌아갑니다.",
        "modeling_failed": "모델링 실패: {reason}",
        "modeling_boot_failed": "모델러를 시작할 수 없습니다: {reason}",
        "modeling_round_limit": "도구 라운드 한도에 도달해 멈췄습니다.",
        "openai_guide_title": "OpenAI API 키 (라이노 모델링)",
        "openai_guide_body": (
            "  https://platform.openai.com/api-keys 에서 키를 만드세요.\n"
            "  이 컴퓨터 .env 의 OPENAI_API_KEY 에만 저장됩니다.\n"
            "  허브 → m 모델링 전용입니다 (Conductor/Worker와 무관)."
        ),
        "openai_current_overwrite": "현재 키: {masked} (덮어씁니다)",
        "openai_exists": "저장된 OpenAI 키: {masked}",
        "openai_reconfigure": "다시 설정: 허브 → c → 7",
        "openai_missing": "라이노 모델링에는 OpenAI API 키가 필요합니다.",
        "openai_required": "모델링에는 OpenAI API 키가 필요합니다.",
        "openai_cancelled": "취소됨 — OpenAI 키를 저장하지 않았습니다.",
        "openai_verifying": "OpenAI 키 확인 중 …",
        "openai_ok": "OpenAI 키 저장됨.",
        "openai_ok_detail": "저장: {path} ({masked})",
        "openai_fail": "OpenAI 키 확인 실패.",
        "openai_fail_detail": "{reason}",
        "openai_retry": "다시 시도할까요? [Y/n]: ",
        # --- brief
        "brief_title": "기본 프로젝트 정보",
        "brief_intro": "폴더가 만들어졌습니다. 브리프 기본 정보를 입력하세요.\n(Enter로 건너뛰기 가능 — 나중에 채워도 됩니다)",
        "brief_type": "프로젝트 유형: ",
        "brief_site": "사이트: ",
        "brief_problem": "핵심 문제: ",
        "brief_issues": "사이트 이슈 (쉼표로 구분): ",
        "brief_intention": "설계 의도: ",
        "brief_direction": "현재 설계 방향: ",
        "brief_driver": "설계 출발점 (site 사이트 / idea 아이디어 / program 프로그램 / regulation 법규 / competition 공모): ",
        "run_path": "경로: {name} → {experts}",
        "brief_saved": "브리프 저장됨: {path}",
        "brief_backup": "백업: {path}",
        "brief_no_changes": "(변경 없음)",
        "brief_fields_intro": "Enter = 현재 값 유지. 여기에 없는 섹션은 그대로 보존됩니다.",
        "brief_current": "  현재: {value}",
        "brief_usage": "사용법: /brief | /brief edit (에디터) | /brief fields (항목별 입력)",
        # --- editor
        "editor_opening": "{editor}로 {file}을(를) 엽니다 ... 저장 후 에디터를 닫으면 계속됩니다.",
        "editor_unchanged": "변경 사항이 없습니다.",
        "editor_saved": "저장됨: {path}",
        "editor_failed": (
            "에디터를 열 수 없습니다 ({reason}).\n"
            "EDITOR 환경 변수를 설정하거나 파일을 직접 편집하세요:\n  {path}"
        ),
        # --- rename
        "rename_prompt": "새 프로젝트 이름: ",
        "rename_ok": "이름 변경: {old} → {new}\n폴더: {path}",
        "rename_fail": "이름 변경 실패: {reason}",
        # --- session banner
        "sess_projects_root": "프로젝트 루트: {path}",
        "sess_project": "프로젝트:      {path}",
        "sess_brief": "브리프:        {path}",
        "sess_modules": "모듈 폴더:     {path}",
        "sess_state": "상태 파일:     {path}",
        "sess_context": "컨텍스트:      최근 {n}개 메시지 + project_state.md",
        "sess_conductor_local": "Conductor:     {provider} / {profile} → {model}{ctx}",
        "sess_conductor_cloud": "Conductor:     {provider} → {model}",
        "ollama_starting": "[ollama] 서버가 꺼져 있어 시작합니다 ...",
        "ollama_started": "[ollama] 서버 준비됨.",
        "ollama_not_running": (
            "Ollama가 {url} 에서 실행 중이 아닙니다.\n"
            "https://ollama.com 에서 설치 후 Ollama 앱을 실행하거나, conductor.ollama_autostart: true 로 두세요."
        ),
        "ollama_not_installed": (
            "이 컴퓨터에 Ollama가 없습니다.\n"
            "https://ollama.com 에서 설치한 뒤 다시 실행하세요."
        ),
        "ollama_start_timeout": (
            "Ollama를 시작했지만 {url} 에 아직 응답이 없습니다.\n"
            "Ollama 앱을 직접 연 뒤 다시 시도하세요."
        ),
        "ollama_model_missing": "Ollama 모델 '{model}' 이(가) 없습니다. 실행: ollama pull {model}",
        "ollama_model_missing_ask": "[ollama] 모델 '{model}' 이(가) 아직 없습니다.",
        "ollama_pull_prompt": "'{model}' 을(를) 지금 받을까요? 몇 분 걸릴 수 있습니다. [Y/n]: ",
        "ollama_pulling": "[ollama] {model} 받는 중 ...",
        "ollama_pulled": "[ollama] 모델 준비됨: {model}",
        "ollama_warming": "[ollama] {model} 을(를) VRAM에 올리는 중 ...",
        "ollama_warm": "[ollama] {model} 로드됨.",
        "sess_created": "새 프로젝트 폴더를 만들었습니다.",
        "sess_resumed": "기존 프로젝트를 이어서 엽니다.",
        "sess_loaded_turns": "이전 대화 불러옴: 사용자 턴 {n}개",
        "session_hint": "명령: /help  /close (허브로)  /quit (앱 종료)",
        "session_saved_close": "대화 저장됨. 프로젝트 허브로 돌아갑니다.",
        "session_saved_quit": "대화 저장됨. 종료합니다.",
        "you_prompt": "나: ",
        "conductor_label": "Conductor: ",
        # --- conductor / modules
        "conductor_error": "[conductor] {reason}",
        "conductor_not_sent": "[conductor] 메시지가 전송되지 않았습니다. 다시 시도하거나 /close 로 나가세요.",
        "conductor_unknown_agent": "[conductor] 알 수 없는 모듈 id: {agent}",
        "conductor_unknown_read": "[conductor] 읽을 수 없는 모듈: {agent}",
        "conductor_read_fail": "[conductor] {agent}을(를) 읽을 수 없습니다: {reason}.",
        "read_reason_empty": "파일이 비어 있거나 없음",
        "read_reason_limit": "이 턴의 읽기 한도 초과",
        "conductor_reading": "[conductor] modules/{file} 읽는 중 ...",
        "action_recovered": "[conductor] 액션 블록이 빠져 있어 복구했습니다: {action} {agent}",
        "module_running": "[module] {name} 실행 중...",
        "module_saved": "[module] 저장됨 {path}",
        "module_archived": "[module] 이전 버전 보관: {path}",
        "migrate_applied": "[migrate] 이 프로젝트를 갱신했습니다 ({n}건):",
        "module_failed": "[module] 실패: {reason}",
        "module_nothing_saved": "[module] 저장된 것 없음. /run {agent} 으로 다시 시도하세요.",
        "module_preview": "--- {name} 미리보기 ---",
        "module_missing_headers": "[module] 경고: {name} 출력에 빠진 섹션: {headers}",
        "unknown_agent": "알 수 없는 모듈: {agent}",
        "run_usage": "사용법: /run <agent_id>",
        # --- info commands
        "project_folder": "프로젝트 폴더: {path}",
        "project_session": "session_id:     {id}",
        "project_completed": "완료된 모듈:    {list}",
        "project_history_turns": "대화 턴:        {n}",
        "project_state_file": "상태 파일:      {path}",
        "status_completed": "완료: {list}",
        "status_folder": "폴더:  {path}",
        "status_history": "대화:  {path}",
        "status_state": "상태:  {path}",
        "state_usage": "사용법: /state | /state edit | /state update [agent_id]",
        "state_proposing": "[state] {agent} 결과로 project_state.md 갱신안을 만드는 중 ...",
        "state_propose_failed": "[state] 갱신안을 만들지 못했습니다: {reason}. /state edit 로 직접 수정하세요.",
        "state_no_change": "[state] 제안된 변경 사항이 없습니다.",
        "state_applied": "[state] project_state.md 갱신됨 (백업: project_state.prev.md)",
        "state_apply_prompt": "이 갱신을 적용할까요? [Y = 적용 / n = 건너뛰기 / e = 적용 후 에디터로 열기]: ",
        "state_skipped": "[state] 건너뜀. 나중에 /state edit 또는 /state update 로 반영할 수 있습니다.",
        "state_update_no_module": "[state] 완료된 모듈이 없습니다. 먼저 모듈을 실행하거나 agent id를 지정하세요.",
        "none": "(없음)",
        "empty": "(비어 있음)",
        "help_commands": (
            "명령어:\n"
            "  /help              이 도움말\n"
            "  /project           현재 프로젝트 폴더 정보\n"
            "  /rename <이름>     프로젝트 이름 변경 (폴더 + 표시 이름)\n"
            "  /brief             현재 brief.md 보기\n"
            "  /brief edit        brief.md 를 에디터로 열기 (백업 → brief.prev.md)\n"
            "  /brief fields      기본 항목만 다시 입력 (다른 섹션은 보존)\n"
            "  /state             project_state.md 보기 (Conductor 메모리)\n"
            "  /state edit        project_state.md 를 에디터로 열기\n"
            "  /state update [id] 모듈 결과로 상태 갱신안 제안 (diff 확인 후 적용)\n"
            "  /agents            모듈 목록\n"
            "  /status            완료된 모듈 보기\n"
            "  /setup             OpenRouter API 키 (재)설정\n"
            "  /language          UI 언어 변경\n"
            "  /run <agent_id>    모듈 즉시 실행 (Conductor 호출 없음)\n"
            "  /close             프로젝트 나가기 → 허브\n"
            "  /quit              앱 종료\n"
            "\n"
            "그냥 입력하면 Conductor와 대화합니다."
        ),
        "help_modules": "모듈:",
        # --- run.py
        "run_project": "프로젝트: {path}",
        "run_step": "[{i}/{n}] {name} 실행 중...",
        "run_outputs": "결과 저장 위치: {path}/",
        "run_failed": "{name} 실패: {reason}\n완료된 모듈은 저장되어 있습니다. 다시 실행하면 이어집니다.",
        "run_usage_cli": (
            "사용법: python run.py input/project_brief.md\n"
            "       python run.py --path site_driven input/project_brief.md\n"
            "       python run.py projects/project_name\n"
            "       python chat.py input/project_brief.md   # 대화형"
        ),
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
    table = STRINGS.get(lang) or STRINGS[FALLBACK_LANGUAGE]
    text = table.get(key) or STRINGS[FALLBACK_LANGUAGE].get(key) or key
    if kwargs:
        return text.format(**kwargs)
    return text
