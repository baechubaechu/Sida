// The project list and the new-project form (HTML strings from `ui`).

import { escapeHtml as escape, findProjects, parcelOutline, relativeDate, projectSummary, projectPath as projectUrl, sitePath } from './model.js';
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

// A project's saved site drawn as a north-up line drawing (with a scale bar when `bar`), or a quiet
// note when no site is saved yet. The SVG is decorative: the address next to it says the same.
function siteDrawing(card, width, height, bar = false) {
  const outline = card && card.shapes.length ? parcelOutline(card.shapes, width, height, bar ? 36 : 24) : null;
  if (!outline) return `<div class="site-drawing empty-drawing" aria-hidden="true"><span>${card ? '필지 경계 미확인' : '대지 미정'}</span></div>`;
  const scale = bar ? `<g class="drawing-scale"><path d="M16 ${height - 14}h${outline.bar.px}"/><text x="${16 + outline.bar.px + 6}" y="${height - 10}">${outline.bar.m}m</text></g>
    <g class="drawing-north" transform="translate(${width - 22} 24)"><path d="M0 -10L5 6L0 3L-5 6Z"/><text y="18">N</text></g>` : '';
  return `<svg class="site-drawing" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-hidden="true" focusable="false">
    ${outline.paths.map((d) => `<path class="drawing-parcel" d="${d}"/>`).join('')}${scale}</svg>`;
}

function siteLine(card, project) {
  if (!card) return escape(project.project_type || '');
  return escape([card.address, card.zones.join(', ')].filter(Boolean).join(' · '));
}

// Expert progress as dots: filled for each finished expert, out of those shown on the board.
function expertDots(project) {
  const total = project.visible_expert_count ?? project.expert_count ?? 0;
  const done = (project.visible_completed ?? project.completed ?? []).length;
  if (!total) return '';
  const dots = Array.from({ length: total }, (_, i) => `<i class="${i < done ? 'on' : ''}"></i>`).join('');
  return `<span class="expert-dots" aria-hidden="true">${dots}</span>`;
}

// Inline name for a project card in view transitions: stable per project while the list is open.
function transitionName(project) {
  return `project-${ui.projects.indexOf(project)}`;
}

// The latest project, large, to pick up where the designer left off. Hidden while searching.
function continueCard(project) {
  const card = ui.projectSites.get(project.name)?.card;
  const label = escape(projectLabel(project));
  const caps = card && card.bcr !== null ? ` · 법정 건폐율 ${card.bcr}% · 용적률 ${card.far}% 이하` : '';
  const facts = card ? `<p class="continue-facts">대지 ${escape(card.area)}${caps}</p>` : '<p class="continue-facts muted">아직 대지를 정하지 않았어요.</p>';
  const site = card ? '' : `<a class="secondary" href="${sitePath(project.name, 'find')}">대지 정하기</a>`;
  return `<section class="continue" aria-labelledby="continue-title" style="view-transition-name: project-continue">
    <a class="continue-drawing" href="${projectUrl(project.name)}" tabindex="-1" aria-hidden="true">${siteDrawing(card, 400, 300, true)}</a>
    <div class="continue-body">
      <p class="continue-label">이어서 하기</p>
      <h2 id="continue-title">${label}</h2>
      ${card || project.project_type ? `<p class="continue-site">${siteLine(card, project)}</p>` : ''}
      ${facts}
      <p class="continue-progress">${expertDots(project)}<span>${escape(projectSummary(project))}</span><span class="muted">· ${escape(relativeDate(project.updated_at))}</span></p>
      <div class="continue-actions">${site}<a class="primary" href="${projectUrl(project.name)}" aria-label="${label} 프로젝트 열기">열기</a></div>
    </div></section>`;
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
  const add = ui.query.trim() ? '' : '<a class="project-new" href="#/new" style="view-transition-name: project-new"><span aria-hidden="true">＋</span>새 프로젝트</a>';
  return projects.map((p) => {
    const card = ui.projectSites.get(p.name)?.card;
    const line = siteLine(card, p);
    return `<article class="project-card" style="view-transition-name: ${transitionName(p)}"><a class="project-open" href="${projectUrl(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 열기">
    <div class="project-drawing">${siteDrawing(card, 240, 180)}</div>
    <h3>${escape(projectLabel(p))}</h3>
    ${line ? `<p class="project-type">${line}</p>` : ''}
    <p class="project-summary">${expertDots(p)}<span>${escape(projectSummary(p))}</span></p>
    <div class="project-footer"><span>${escape(relativeDate(p.updated_at))}</span><span aria-hidden="true">↗</span></div>
  </a><div class="project-card-actions"><button type="button" data-action="project-info" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 정보 수정">정보 수정</button>
    <button type="button" class="card-delete" data-action="delete-project" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 삭제" title="프로젝트 삭제">삭제</button></div></article>`;
  }).join('') + add;
}

// Everything below the heading: the continue card (unless searching) and the cards. Redrawn alone
// when the search or the order changes.
export function projectList() {
  const latest = ui.projects?.length && !ui.query.trim() ? findProjects(ui.projects, '', 'recent')[0] : null;
  return `${latest ? continueCard(latest) : ''}
    <h2 class="list-label">모든 프로젝트</h2><div class="project-grid" id="project-grid">${projectCards()}</div>`;
}

export function homeView() {
  return `<div class="app-shell">${sidebar()}
    <main class="home" id="main" tabindex="-1">
      <header class="home-heading"><h1>프로젝트</h1>
        <div class="project-tools">
          <label class="search-box"><span aria-hidden="true">⌕</span><span class="sr-only">프로젝트 검색</span><input id="project-search" data-focus="project-search" type="search" placeholder="프로젝트 검색" value="${escape(ui.query)}" autocomplete="off"></label>
          <label class="sr-only" for="project-sort">프로젝트 정렬</label>
          <select id="project-sort"><option value="recent" ${ui.sort === 'recent' ? 'selected' : ''}>최근 수정순</option><option value="name" ${ui.sort === 'name' ? 'selected' : ''}>이름순</option></select>
        </div>
        <a class="primary" href="#/new">＋&nbsp; 새 프로젝트</a></header>
      <div id="project-list">${projectList()}</div>
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
