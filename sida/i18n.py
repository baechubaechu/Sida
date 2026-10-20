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


# Display strings only.
STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # --- app / setup
        "api_required": "No OpenRouter API key. Enter it on the settings screen.",
        # --- about
        "worker_name_site_reader": "Site Reader",
        "worker_desc_site_reader": (
            "Geographic/spatial site reading — systems, conflicts, opportunities (not codes)."
        ),
        "worker_name_program_analyst": "Program Analyst",
        "worker_desc_program_analyst": (
            "Users and rhythms, program parts, adjacency, public–private gradient."
        ),
        "worker_name_regulation_checker": "Regulation Checker",
        "worker_desc_regulation_checker": (
            "Site- and program-triggered codes, verify list, binding limits, incentives (KR default)."
        ),
        "worker_name_precedent_scout": "Precedent Scout",
        "worker_desc_precedent_scout": (
            "Precedents and typologies matched to the problem — lessons and cautions."
        ),
        "worker_name_concept_framer": "Concept Framer",
        "worker_desc_concept_framer": (
            "Sharpen the designer's idea into a testable concept and operative strategy."
        ),
        "worker_name_spatial_reviewer": "Spatial Reviewer",
        "worker_desc_spatial_reviewer": (
            "Test the described organization — circulation, section, thresholds, program fit."
        ),
        "worker_name_systems_advisor": "Systems Advisor",
        "worker_desc_systems_advisor": (
            "Structure, envelope, services, egress questions and trade-offs (no sizing)."
        ),
        "worker_name_design_critic": "Design Critic",
        "worker_desc_design_critic": (
            "Jury-style critique of the direction against the core problem."
        ),
        "worker_name_representation_planner": "Representation Planner",
        "worker_desc_representation_planner": (
            "Which diagrams, drawings, and models prove the concept and expose weak points."
        ),
        "worker_name_presentation_editor": "Presentation Editor",
        "worker_desc_presentation_editor": (
            "Review / portfolio story, structure, and anticipated questions."
        ),
        # --- hub settings
        "mode_name_cloud": "cloud (OpenRouter)",
        "mode_name_local": "local (Ollama)",
        "mode_name_custom": "custom",
        "busy_role": "Waiting on {role} …",
        "busy_conductor": "Conductor thinking …",
        "busy_worker": "Running {name} …",
        "busy_worker_retry": "Retrying {name} (fix headers) …",
        "busy_recovery": "Recovering action block …",
        "busy_state": "Updating project state from {name} …",
        "busy_rag": "Searching statutes …",
        "busy_law": "Looking up regulations …",
        "rag_warn_provider": (
            "[rag] Warning: unknown rag.provider '{provider}'. Continuing without retrieved regulations."
        ),
        "rag_warn_unreachable": (
            "[rag] Warning: cannot reach the statute search ({url}). "
            "Continuing without retrieved regulations."
        ),
        "rag_warn_bad_response": (
            "[rag] Warning: unexpected reply from the statute search. "
            "Continuing without retrieved regulations."
        ),
        "rag_warn_no_hits": "[rag] No matching regulation passages were found for this request.",
        "rag_warn_no_oc": (
            "[rag] Warning: statute search is on but LAW_OPEN_API_OC is not set in .env. "
            "Continuing without retrieved regulations."
        ),
        "rag_warn_law_not_applied": (
            "[rag] Warning: this law.go.kr key has not applied for the intelligent search API "
            "(open.law.go.kr → OPEN API 신청 → 지능형 법령검색 시스템 검색 API). "
            "Continuing without retrieved regulations."
        ),
        "rag_warn_law_denied": (
            "[rag] Warning: law.go.kr refused the request ({detail}). "
            "Continuing without retrieved regulations."
        ),
        "rag_warn_no_query": (
            "[rag] No statute search was run: there are no site facts and no Korean project type "
            "in the brief to search with. Look the site address up first."
        ),
        "rag_warn_error": "[rag] Warning: retrieval failed ({reason}). Continuing without retrieved regulations.",
        "expert_hook_failed": "[{domain}] Warning: could not prepare this domain's material ({reason}). Running without it.",
        "busy_modeling": "Rhino modeler thinking …",
        "modeling_model_too_old": (
            "Modeling requires GPT-{min_major}+ (got '{model}'). "
            "Set modeling.model to something like {example}."
        ),
        "modeling_label": "Modeler: ",
        "modeling_calling": "→ MCP {tool}",
        "modeling_dry_call": "(dry-run) would call {tool}",
        "modeling_round_limit": "Stopped after max tool rounds.",
        # --- brief
        "brief_type": "Project type: ",
        "brief_site": "Site: ",
        "brief_problem": "Core problem: ",
        "brief_issues": "Site issues (comma-separated): ",
        "brief_intention": "Design intention: ",
        "brief_direction": "Current design direction: ",
        "brief_driver": "Primary driver (site / idea / program / regulation / competition): ",
        # --- web UI
        "web_serving": "Sida web UI: {url}  (Ctrl+C to stop)",
        "web_tagline": "A studio assistant for architectural design reasoning",
        "web_projects": "Projects",
        "web_projects_root": "Folder: {path}",
        "web_no_projects": "No projects yet. Create one below or start from the sample brief.",
        "web_experts_done": "{done}/{total} experts done",
        "web_updated": "updated {when}",
        "web_new_project": "New project",
        "web_field_name": "Project name",
        "web_field_driver": "Primary driver",
        "web_driver_site": "site",
        "web_driver_idea": "idea",
        "web_driver_program": "program",
        "web_driver_regulation": "regulation",
        "web_driver_competition": "competition / review",
        "web_optional_hint": "Only the name is required. Fill in the rest now or later.",
        "web_create": "Create",
        "web_sample": "Start from the sample brief",
        "web_sample_hint": "Try Sida right away with an example brief.",
        "web_err_name": "Enter a project name.",
        "web_runtime": "Runtime",
        "web_runtime_mode": "Mode",
        "web_runtime_hint": "Change these on the settings screen.",
        "web_warn_no_key": (
            "No OpenRouter API key is set. Add one on the settings screen."
        ),
        "web_warn_rag_key": "Statute search is on but LAW_OPEN_API_OC is not set in .env.",
        "web_back_hub": "← Projects",
        "web_brief": "Brief",
        "web_experts": "Experts",
        "web_status_done": "done",
        "web_status_pending": "pending",
        "web_session_soon": (
            "The Conductor chat screen arrives in the next update."
        ),
        "web_not_found": "Project not found: {name}",
        "web_error_title": "Something went wrong",
        "web_chatgpt_done_title": "Signed in with ChatGPT",
        "web_chatgpt_done": "Signed in as {email}. Close this window and go back to Sida.",
        "web_chatgpt_no_plan": (
            "Signed in, but plan usage was not approved, so the Conductor cannot use this "
            "ChatGPT plan yet. Sign in again from settings and approve it (Go, Plus or Pro)."
        ),
        "web_chatgpt_failed_title": "ChatGPT sign-in failed",
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
        "ollama_speed": "[ollama] Speed on this PC: {rate} tokens/s.",
        "ollama_speed_slow": (
            "[ollama] That is slow for chat. Consider a smaller profile "
            "or cloud mode in the settings."
        ),
        "hw_profile_ok": "[gpu] {name} ({gb}GB VRAM) — fits the '{profile}' profile.",
        "hw_profile_too_big": (
            "[gpu] {name} ({gb}GB VRAM) is below what the '{profile}' profile needs. "
            "Recommended: '{rec}' (change it in the settings)."
        ),
        "hw_profile_can_upgrade": (
            "[gpu] {name} ({gb}GB VRAM) can also run the larger '{rec}' profile "
            "(current: '{profile}'; change it in the settings)."
        ),
        "hw_recommend_cloud": (
            "[gpu] {name} ({gb}GB VRAM) is below the 8GB minimum for the '{profile}' profile. "
            "Cloud mode is recommended (change it in the settings)."
        ),
        # --- conductor / modules
        "conductor_error": "[conductor] {reason}",
        "action_recovered": "[conductor] Action block was missing; recovered: {action} {agent}",
        "module_saved": "[module] Saved {path}",
        "module_archived": "[module] Previous version archived: {path}",
        "migrate_applied": "[migrate] Updated this project ({n} change(s)):",
        "module_failed": "[module] Failed: {reason}",
        "module_missing_headers": "[module] Warning: {name} output is missing headers: {headers}",
        "worker_input_trimmed": (
            "[module] {name}: trimmed {n} input(s) to fit the local model context "
            "(num_ctx={ctx}). Use cloud mode or a larger profile for full inputs."
        ),
        "worker_block_cut": (
            "[module] {name}: {what} did not fit the local model context (num_ctx={ctx}) and "
            "was cut. Do not rely on this output for it; use cloud mode or a larger profile."
        ),
        "prompt_label_ordinance": "the ordinance text",
        "unknown_agent": "Unknown agent: {agent}",
        # --- site facts
        "web_site_query_required": "Enter a lot-number address to search for.",
        "web_site_pnus_required": "Choose at least one parcel.",
        "web_site_pnu_bad": "A parcel number (PNU) is 19 digits: {pnu}",
        "web_site_pnu_unknown": "There is no parcel with the number {pnu}.",
        "web_site_region_bad": "A region code is 2, 5 or 8 digits (empty for the provinces): {code}",
        "web_site_dong_bad": "A 법정동 code is 10 digits: {code}",
        "web_site_lot_bad": "The main lot number is 1-9999 and the sub number 0-9999.",
        "web_site_point_bad": "That point is outside Korea: {lon}, {lat}",
        "web_site_shapes_limit": "Ask for at most {n} parcels at a time.",
        "web_site_none": "Look the site up first: no site facts are saved for this project.",
        "web_site_use_required": "Enter a planned use, such as 공장 or 단독주택.",
        "web_site_use_unknown": "That use has not been checked for this site: {name}",
        "web_site_use_not_found": "토지이음 has no use named exactly {name}. Close names: {names}",
        "web_site_use_no_match": "토지이음 has no use name containing {name}.",
        "site_err_no_key": (
            "[site] VWORLD_API_KEY is not set. Add VWORLD_API_KEY and VWORLD_DOMAIN to .env "
            "(see docs/dev-setup.md)."
        ),
        "site_err_invalid_key": (
            "[site] VWorld rejected the key ({detail}). The key may have expired, or VWORLD_DOMAIN "
            "does not match the service URL registered with it."
        ),
        "site_err_over_limit": "[site] VWorld daily request limit reached. Try again tomorrow.",
        "site_err_network": "[site] Could not reach VWorld ({detail}). Check the connection and try again.",
        "site_err_bad_response": "[site] Unexpected reply from VWorld ({detail}).",
        "datago_err_no_key": (
            "[site] DATA_GO_KR_API_KEY is not set. Add the data.go.kr key (the decoded one) to .env "
            "(see docs/dev-setup.md)."
        ),
        "datago_err_invalid_key": (
            "[site] data.go.kr rejected the key ({detail}). The key may have expired, or the service "
            "(토지이음 or 건축물대장) is not approved for it yet."
        ),
        "datago_err_over_limit": "[site] data.go.kr daily request limit reached. Try again tomorrow.",
        "datago_err_network": "[site] Could not reach data.go.kr ({detail}). Check the connection and try again.",
        "datago_err_bad_response": "[site] Unexpected reply from data.go.kr ({detail}).",
        "site_block_failed": "[site] Could not read site_facts.json ({reason}); running without site facts.",
        "state_proposing": "[state] Proposing project_state.md update from {agent} ...",
        "state_applied": "[state] project_state.md updated (backup: project_state.prev.md)",
        "none": "(none)",
        "empty": "(empty)",
    },
    "ko": {
        # --- app / setup
        "api_required": "OpenRouter API 키가 없습니다. 설정 화면에서 키를 넣어 주세요.",
        # --- about
        "worker_name_site_reader": "대지 분석가",
        "worker_desc_site_reader": (
            "지리·공간으로 대지 읽기 — 시스템, 충돌, 기회 (법규 분석은 하지 않음)."
        ),
        "worker_name_program_analyst": "프로그램 분석가",
        "worker_desc_program_analyst": (
            "이용자·리듬, 프로그램 구성, 인접성, 공·사 그라데이션."
        ),
        "worker_name_regulation_checker": "법규 검토자",
        "worker_desc_regulation_checker": (
            "대지·프로그램이 건드리는 법령, 검증 목록, 구속력 있는 한계, 인센티브 (기본 KR)."
        ),
        "worker_name_precedent_scout": "선례 연구자",
        "worker_desc_precedent_scout": (
            "문제에 맞는 선례·유형 — 배울 점과 베끼면 안 되는 점."
        ),
        "worker_name_concept_framer": "개념 정리자",
        "worker_desc_concept_framer": (
            "디자이너 의도를 검증 가능한 개념·작동 전략으로 다듬음."
        ),
        "worker_name_spatial_reviewer": "공간 검토자",
        "worker_desc_spatial_reviewer": (
            "말한 공간조직 점검 — 동선, 단면, 경계, 프로그램 배치."
        ),
        "worker_name_systems_advisor": "시스템 자문가",
        "worker_desc_systems_advisor": (
            "구조·외피·설비·피난 질문과 트레이드오프 (치수 산정 없음)."
        ),
        "worker_name_design_critic": "설계 비평가",
        "worker_desc_design_critic": (
            "핵심 문제에 대한 심사위원식 비평."
        ),
        "worker_name_representation_planner": "표현 계획자",
        "worker_desc_representation_planner": (
            "개념을 증명하고 약점을 드러낼 다이어그램·도면·모델 계획."
        ),
        "worker_name_presentation_editor": "발표 편집자",
        "worker_desc_presentation_editor": (
            "리뷰·포트폴리오 스토리, 구성, 예상 질문."
        ),
        # --- hub settings
        "mode_name_cloud": "클라우드 (OpenRouter)",
        "mode_name_local": "로컬 (Ollama)",
        "mode_name_custom": "사용자 지정",
        "busy_role": "{role} 응답 대기 중 …",
        "busy_conductor": "Conductor 생각 중 …",
        "busy_worker": "{name} 실행 중 …",
        "busy_worker_retry": "{name} 재시도 중 (헤더 보정) …",
        "busy_recovery": "action 블록 복구 중 …",
        "busy_state": "{name} 결과로 project_state 갱신 중 …",
        "busy_rag": "법령 조문 검색 중 …",
        "busy_law": "법령 검색 중 …",
        "rag_warn_provider": (
            "[rag] 경고: 알 수 없는 rag.provider '{provider}'. 법규 검색 없이 진행합니다."
        ),
        "rag_warn_unreachable": (
            "[rag] 경고: 법령 검색에 연결할 수 없습니다({url}). 법규 검색 없이 진행합니다."
        ),
        "rag_warn_bad_response": (
            "[rag] 경고: 법령 검색의 응답이 예상과 다릅니다. 법규 검색 없이 진행합니다."
        ),
        "rag_warn_no_hits": "[rag] 이번 요청에 맞는 법규 구절을 찾지 못했습니다.",
        "rag_warn_no_oc": (
            "[rag] 경고: 법령 검색이 켜져 있지만 .env에 LAW_OPEN_API_OC가 없습니다. "
            "법규 검색 없이 진행합니다."
        ),
        "rag_warn_law_not_applied": (
            "[rag] 경고: 이 법제처 키로는 지능형 검색 API를 신청하지 않았습니다 "
            "(open.law.go.kr → OPEN API 신청 → 지능형 법령검색 시스템 검색 API). "
            "법규 검색 없이 진행합니다."
        ),
        "rag_warn_law_denied": (
            "[rag] 경고: 법제처가 요청을 거부했습니다({detail}). 법규 검색 없이 진행합니다."
        ),
        "rag_warn_no_query": (
            "[rag] 법령 검색을 하지 않았습니다. 대지 사실이 없고 브리프에 한국어 프로젝트 유형도 없어 "
            "검색어를 만들 수 없습니다. 먼저 주소로 대지를 조회하세요."
        ),
        "rag_warn_error": "[rag] 경고: 검색에 실패했습니다({reason}). 법규 검색 없이 진행합니다.",
        "expert_hook_failed": "[{domain}] 경고: 이 영역의 자료를 준비하지 못했습니다({reason}). 해당 자료 없이 실행합니다.",
        "busy_modeling": "라이노 모델러 생각 중 …",
        "modeling_model_too_old": (
            "모델링은 GPT-{min_major}+ 만 가능합니다 (현재 '{model}'). "
            "modeling.model 을 {example} 같이 바꾸세요."
        ),
        "modeling_label": "모델러: ",
        "modeling_calling": "→ MCP {tool}",
        "modeling_dry_call": "(dry-run) {tool} 호출 예정",
        "modeling_round_limit": "도구 라운드 한도에 도달해 멈췄습니다.",
        # --- brief
        "brief_type": "프로젝트 유형: ",
        "brief_site": "사이트: ",
        "brief_problem": "핵심 문제: ",
        "brief_issues": "사이트 이슈 (쉼표로 구분): ",
        "brief_intention": "설계 의도: ",
        "brief_direction": "현재 설계 방향: ",
        "brief_driver": "설계 출발점 (site 사이트 / idea 아이디어 / program 프로그램 / regulation 법규 / competition 공모): ",
        # --- web UI
        "web_serving": "Sida 웹 UI: {url}  (끄려면 Ctrl+C)",
        "web_tagline": "건축 설계 추론을 돕는 조수",
        "web_projects": "프로젝트",
        "web_projects_root": "폴더: {path}",
        "web_no_projects": "아직 프로젝트가 없습니다. 아래에서 새로 만들거나 샘플 브리프로 시작하세요.",
        "web_experts_done": "전문가 {done}/{total} 완료",
        "web_updated": "{when} 수정",
        "web_new_project": "새 프로젝트",
        "web_field_name": "프로젝트 이름",
        "web_field_driver": "설계 출발점",
        "web_driver_site": "사이트",
        "web_driver_idea": "아이디어",
        "web_driver_program": "프로그램",
        "web_driver_regulation": "법규",
        "web_driver_competition": "공모 / 발표",
        "web_optional_hint": "이름만 넣어도 됩니다. 나머지는 지금 채워도 되고 나중에 채워도 됩니다.",
        "web_create": "만들기",
        "web_sample": "샘플 브리프로 시작",
        "web_sample_hint": "예시 브리프로 바로 써 볼 수 있습니다.",
        "web_err_name": "프로젝트 이름을 입력하세요.",
        "web_runtime": "실행 환경",
        "web_runtime_mode": "모드",
        "web_runtime_hint": "설정 화면에서 바꿉니다.",
        "web_warn_no_key": (
            "OpenRouter API 키가 없습니다. 설정 화면에서 넣어 주세요."
        ),
        "web_warn_rag_key": "법령 검색이 켜져 있지만 .env에 LAW_OPEN_API_OC가 없습니다.",
        "web_back_hub": "← 프로젝트 목록",
        "web_brief": "브리프",
        "web_experts": "전문가",
        "web_status_done": "완료",
        "web_status_pending": "대기",
        "web_session_soon": (
            "Conductor와 대화하는 화면은 다음 업데이트에 들어옵니다."
        ),
        "web_not_found": "프로젝트를 찾을 수 없습니다: {name}",
        "web_error_title": "문제가 생겼습니다",
        "web_chatgpt_done_title": "ChatGPT 로그인 완료",
        "web_chatgpt_done": "{email} 계정으로 로그인했습니다. 이 창을 닫고 Sida로 돌아가세요.",
        "web_chatgpt_no_plan": (
            "로그인은 됐지만 구독 사용을 허용하지 않아 Conductor가 이 ChatGPT 구독을 쓸 수 없습니다. "
            "설정에서 다시 로그인해 허용해 주세요(Go, Plus, Pro 구독)."
        ),
        "web_chatgpt_failed_title": "ChatGPT 로그인 실패",
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
        "ollama_speed": "[ollama] 이 PC에서의 속도: 초당 {rate}토큰.",
        "ollama_speed_slow": (
            "[ollama] 대화하기에는 느립니다. 설정에서 더 작은 프로필이나 "
            "클라우드 모드를 고려하세요."
        ),
        "hw_profile_ok": "[gpu] {name} (VRAM {gb}GB) — '{profile}' 프로필에 맞습니다.",
        "hw_profile_too_big": (
            "[gpu] {name} (VRAM {gb}GB)는 '{profile}' 프로필에 부족합니다. "
            "추천: '{rec}' (설정에서 바꿀 수 있습니다)."
        ),
        "hw_profile_can_upgrade": (
            "[gpu] {name} (VRAM {gb}GB)는 더 큰 '{rec}' 프로필도 돌릴 수 있습니다 "
            "(현재: '{profile}', 설정에서 바꿀 수 있습니다)."
        ),
        "hw_recommend_cloud": (
            "[gpu] {name} (VRAM {gb}GB)는 '{profile}' 프로필의 최소 8GB에 못 미칩니다. "
            "클라우드 모드를 추천합니다 (설정에서 바꿀 수 있습니다)."
        ),
        # --- conductor / modules
        "conductor_error": "[conductor] {reason}",
        "action_recovered": "[conductor] 액션 블록이 빠져 있어 복구했습니다: {action} {agent}",
        "module_saved": "[module] 저장됨 {path}",
        "module_archived": "[module] 이전 버전 보관: {path}",
        "migrate_applied": "[migrate] 이 프로젝트를 갱신했습니다 ({n}건):",
        "module_failed": "[module] 실패: {reason}",
        "module_missing_headers": "[module] 경고: {name} 출력에 빠진 섹션: {headers}",
        "worker_input_trimmed": (
            "[module] {name}: 로컬 모델 컨텍스트(num_ctx={ctx})에 맞추려고 입력 {n}개를 줄였습니다. "
            "전체 입력을 쓰려면 클라우드 모드나 더 큰 프로필을 쓰세요."
        ),
        "worker_block_cut": (
            "[module] {name}: {what}이 로컬 모델 컨텍스트(num_ctx={ctx})에 다 들어가지 않아 잘렸습니다. "
            "이 결과의 해당 내용은 믿지 말고 클라우드 모드나 더 큰 프로필로 다시 실행하세요."
        ),
        "prompt_label_ordinance": "조례 원문",
        "unknown_agent": "알 수 없는 모듈: {agent}",
        # --- site facts
        "web_site_query_required": "검색할 지번 주소를 입력하세요.",
        "web_site_pnus_required": "필지를 하나 이상 고르세요.",
        "web_site_pnu_bad": "필지 번호(PNU)는 숫자 19자리입니다: {pnu}",
        "web_site_pnu_unknown": "필지 번호 {pnu}에 해당하는 필지가 없습니다.",
        "web_site_region_bad": "지역 코드는 숫자 2·5·8자리입니다(시·도 목록은 비워 둡니다): {code}",
        "web_site_dong_bad": "법정동 코드는 숫자 10자리입니다: {code}",
        "web_site_lot_bad": "본번은 1~9999, 부번은 0~9999 사이의 숫자입니다.",
        "web_site_point_bad": "한국 밖의 지점입니다: {lon}, {lat}",
        "web_site_shapes_limit": "필지는 한 번에 {n}개까지 요청할 수 있습니다.",
        "web_site_none": "먼저 대지를 조회하세요. 이 프로젝트에 저장된 대지 사실이 없습니다.",
        "web_site_use_required": "계획 용도를 입력하세요. 예: 공장, 단독주택",
        "web_site_use_unknown": "이 대지에서 조회한 적 없는 용도입니다: {name}",
        "web_site_use_not_found": "토지이음에 정확히 '{name}'인 용도가 없습니다. 비슷한 이름: {names}",
        "web_site_use_no_match": "토지이음에 '{name}'이 들어간 용도 이름이 없습니다.",
        "site_err_no_key": (
            "[site] VWORLD_API_KEY가 없습니다. .env에 VWORLD_API_KEY와 VWORLD_DOMAIN을 넣어 주세요 "
            "(docs/dev-setup.md 참고)."
        ),
        "site_err_invalid_key": (
            "[site] 브이월드가 키를 거부했습니다({detail}). 키가 만료됐거나, VWORLD_DOMAIN이 "
            "키에 등록한 서비스 주소와 다를 수 있습니다."
        ),
        "site_err_over_limit": "[site] 브이월드 하루 호출 한도를 넘었습니다. 내일 다시 시도하세요.",
        "site_err_network": "[site] 브이월드에 연결하지 못했습니다({detail}). 연결을 확인하고 다시 시도하세요.",
        "site_err_bad_response": "[site] 브이월드 응답이 예상과 다릅니다({detail}).",
        "datago_err_no_key": (
            "[site] DATA_GO_KR_API_KEY가 없습니다. .env에 공공데이터포털 키(Decoding 키)를 넣어 주세요 "
            "(docs/dev-setup.md 참고)."
        ),
        "datago_err_invalid_key": (
            "[site] 공공데이터포털이 키를 거부했습니다({detail}). 키가 만료됐거나, 이 서비스(토지이음 또는 "
            "건축물대장)의 활용 신청이 아직 승인되지 않았을 수 있습니다."
        ),
        "datago_err_over_limit": "[site] 공공데이터포털 하루 호출 한도를 넘었습니다. 내일 다시 시도하세요.",
        "datago_err_network": "[site] 공공데이터포털에 연결하지 못했습니다({detail}). 연결을 확인하고 다시 시도하세요.",
        "datago_err_bad_response": "[site] 공공데이터포털 응답이 예상과 다릅니다({detail}).",
        "site_block_failed": "[site] site_facts.json을 읽지 못했습니다({reason}). 대지 사실 없이 실행합니다.",
        "state_proposing": "[state] {agent} 결과로 project_state.md 갱신안을 만드는 중 ...",
        "state_applied": "[state] project_state.md 갱신됨 (백업: project_state.prev.md)",
        "none": "(없음)",
        "empty": "(비어 있음)",
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


def agent_name(agent: dict) -> str:
    """Expert name shown to the user. config.yaml `name` is what the models see; screens use this."""
    aid = str(agent.get("id") or "")
    key = f"worker_name_{aid}"
    name = t(key)
    return name if name != key else str(agent.get("name") or aid)
