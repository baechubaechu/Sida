// The project list and the new-project form (HTML strings from `ui`).

import { escapeHtml as escape, findProjects, relativeDate, projectSummary, projectPath as projectUrl } from './model.js';
import { projectLabel, ui } from './state.js';

// The project list's sidebar. Inside a project the Conductor panel links back here instead.
// The list itself is the page, so the sidebar does not repeat it or the "new project" button.
function sidebar() {
  const warned = ui.settings && Object.values(ui.settings.warnings || {}).some(Boolean);
  return `<aside class="sidebar" aria-label="프로젝트 탐색">
    <a class="brand" href="#/" aria-label="Sida 프로젝트 홈">Sida</a>
    <nav class="nav-main" aria-label="주 메뉴">
      <a class="nav-link active" href="#/" aria-current="page">▦&nbsp; 프로젝트</a>
    </nav>
    <button class="nav-link sidebar-bottom" data-action="settings">설정${warned ? ' <span class="warn-dot" aria-label="확인할 설정 있음">●</span>' : ''}</button>
  </aside>`;
}

export function projectCards() {
  if (ui.projects === null) {
    return ui.projectsError
      ? `<p class="empty error-text" role="alert">${escape(ui.projectsError)}</p>`
      : '<p class="empty" role="status">프로젝트를 불러오는 중입니다.</p>';
  }
  if (!ui.projects.length) {
    return `<div class="empty"><p>아직 프로젝트가 없습니다.</p><p>새 프로젝트를 만들거나 예시 프로젝트로 시작해 보세요.</p>
      <div class="empty-actions"><a class="primary" href="#/new">＋ 새 프로젝트</a>
      <button class="secondary" type="button" data-action="sample">예시 프로젝트 열기</button></div></div>`;
  }
  const projects = findProjects(ui.projects, ui.query, ui.sort);
  if (!projects.length) return '<p class="empty" role="status">검색 결과가 없습니다. 다른 프로젝트 이름으로 검색해 보세요.</p>';
  // A dashed "new project" card ends the list, so a short list does not leave an empty row.
  const add = ui.query.trim() ? '' : '<a class="project-new" href="#/new"><span aria-hidden="true">＋</span>새 프로젝트</a>';
  return projects.map((p) => `<article class="project-card"><a class="project-open" href="${projectUrl(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 열기">
    <h3>${escape(projectLabel(p))}</h3>
    ${p.project_type ? `<p class="project-type">${escape(p.project_type)}</p>` : ''}
    <p class="project-summary">${escape(projectSummary(p))}</p>
    <div class="project-footer"><span>${escape(relativeDate(p.updated_at))}</span><span aria-hidden="true">↗</span></div>
  </a><div class="project-card-actions"><button type="button" data-action="project-info" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 정보 수정">정보 수정</button>
    <button type="button" class="card-delete" data-action="delete-project" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 삭제" title="프로젝트 삭제">삭제</button></div></article>`).join('') + add;
}

export function homeView() {
  return `<div class="app-shell">${sidebar()}
    <main class="home" id="main" tabindex="-1">
      <header class="home-heading"><div><h1>프로젝트</h1><p>건축 설계 프로젝트를 관리하고 이전 작업을 이어가세요.</p></div>
        <a class="primary" href="#/new">＋&nbsp; 새 프로젝트</a></header>
      <div class="project-tools">
        <label class="search-box"><span aria-hidden="true">⌕</span><span class="sr-only">프로젝트 검색</span><input id="project-search" type="search" placeholder="프로젝트 검색" value="${escape(ui.query)}" autocomplete="off"></label>
        <label class="sr-only" for="project-sort">프로젝트 정렬</label>
        <select id="project-sort"><option value="recent" ${ui.sort === 'recent' ? 'selected' : ''}>최근 수정순</option><option value="name" ${ui.sort === 'name' ? 'selected' : ''}>이름순</option></select>
      </div>
      <h2 class="sr-only">내 프로젝트</h2><div class="project-grid" id="project-grid">${projectCards()}</div>
    </main></div>`;
}

export function newView() {
  const d = ui.newDraft;
  const value = (key) => escape(d[key] || '');
  return `<main class="new-page" id="main" tabindex="-1">
    <header class="new-topbar"><a class="brand" href="#/">sida</a><a class="back-link" href="#/">← 프로젝트로 돌아가기</a></header>
    <form class="new-project" id="new-project-form" novalidate>
      <h1>새 프로젝트 만들기</h1><p class="intro">새 건축 설계 작업 공간을 만듭니다.</p>
      <label for="project-name">프로젝트 이름</label><input id="project-name" name="name" data-focus="new-name" value="${value('name')}" placeholder="제목 없는 프로젝트" required maxlength="80" autocomplete="off">
      <label for="project-type">프로젝트 유형</label><input id="project-type" name="type" data-focus="new-type" value="${value('type')}" placeholder="예: 미술관, 단독주택 (선택)" maxlength="200" autocomplete="off">
      <label for="project-site">대지 주소</label><input id="project-site" name="site" data-focus="new-site" value="${value('site')}" placeholder="지번 또는 도로명 주소 (선택)" maxlength="300" autocomplete="off">
      <label for="project-description">설명</label><textarea id="project-description" name="intention" data-focus="new-intention" placeholder="설계할 프로젝트와 지금 고민하는 점 (선택)" maxlength="4000">${value('intention')}</textarea>
      <p class="form-note">대지 주소는 번지까지 정확히 적어 주세요. 다른 설계 조건은 Conductor와 대화하며 정리합니다.</p>
      <p class="form-error error-text" id="new-project-error" role="alert"></p>
      <div class="form-actions"><a class="secondary" href="#/">취소</a><button class="primary" type="submit" ${ui.creating ? 'disabled' : ''}>프로젝트 만들기</button></div>
    </form></main>`;
}
