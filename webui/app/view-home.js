// The project list and the new-project form (HTML strings from `ui`).

import { escapeHtml as escape, findProjects, parcelOutline, readiness, relativeDate, projectSummary, projectPath as projectUrl, sitePath, siteSlot } from './model.js';
import { icon } from './icons.js';
import { projectLabel, ui } from './state.js';

// The project list's sidebar. Inside a project the Conductor panel links back here instead.
// The list itself is the page, so the sidebar does not repeat it or the "new project" button;
// it shows whether Sida can work on this PC (AI and government data), each line opening the
// settings part that fixes it.
function sidebar(current = true) {
  const status = readiness(ui.settings, ui.relayKey).map((s) => `<button type="button" class="status-row" data-action="settings" data-target="${escape(s.target)}">
      <span class="status-dot ${s.ok ? 'ok' : 'bad'}" aria-hidden="true"></span>
      <span class="status-text"><span class="status-label">${escape(s.label)}</span><span class="status-value">${escape(s.text)}${s.ok ? '' : '<span class="sr-only"> (설정에서 확인)</span>'}</span></span></button>`).join('');
  return `<aside class="sidebar" aria-label="프로젝트 탐색">
    <a class="brand" href="#/" aria-label="Sida 프로젝트 홈">Sida</a>
    <nav class="nav-main" aria-label="주 메뉴">
      <a class="nav-link${current ? ' active' : ''}"${current ? ' aria-current="page"' : ''} href="#/">${icon('projects')}프로젝트</a>
      <button type="button" class="nav-link" data-action="sample">${icon('sample')}예시 프로젝트 열기</button>
    </nav>
    <div class="sidebar-bottom">
      ${status ? `<section class="side-status" aria-label="연결 상태">${status}</section>` : ''}
      <button type="button" class="nav-link side-settings" data-action="settings">${icon('settings')}설정</button>
    </div>
  </aside>`;
}

// A project's saved site drawn as a north-up line drawing (with a scale bar when `bar`). Before the
// site arrives (or when asking failed) the box stays blank; without a site it shows an empty
// parcel and says so. Decorative: the text beside it says the same.
function siteDrawing(entry, width, height, bar = false) {
  const slot = siteSlot(entry);
  if (slot === 'loading' || slot === 'unknown') return '<div class="site-drawing pending-drawing" aria-hidden="true"></div>';
  if (slot !== 'drawn') {
    return `<div class="site-drawing empty-drawing" aria-hidden="true">${icon('parcel', 'empty-parcel')}<span>${slot === 'none' ? '대지 미정' : '필지 경계 미확인'}</span></div>`;
  }
  const outline = parcelOutline(entry.card.shapes, width, height, bar ? 36 : 24);
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
  const entry = ui.projectSites.get(project.name);
  const card = entry?.card;
  const noSite = siteSlot(entry) === 'none';
  const label = escape(projectLabel(project));
  const caps = card && card.bcr !== null ? ` · 법정 건폐율 ${card.bcr}% · 용적률 ${card.far}% 이하` : '';
  const facts = card ? `<p class="continue-facts">대지 ${escape(card.area)}${caps}</p>`
    : noSite ? '<p class="continue-facts muted">아직 대지를 정하지 않았어요.</p>' : '';
  const site = noSite ? `<a class="secondary" href="${sitePath(project.name, 'find')}">대지 정하기</a>` : '';
  return `<section class="continue" data-project="${escape(project.name)}" aria-labelledby="continue-title" style="view-transition-name: project-continue">
    <a class="continue-drawing" href="${projectUrl(project.name)}" data-open-project tabindex="-1" aria-hidden="true">${siteDrawing(entry, 400, 300, true)}</a>
    <div class="continue-body">
      <div class="continue-title"><h2 id="continue-title">${label}</h2><span class="continue-tag">최근 작업</span></div>
      ${card || project.project_type ? `<p class="continue-site">${siteLine(card, project)}</p>` : ''}
      ${facts}
      <p class="continue-progress">${expertDots(project)}<span>${escape(projectSummary(project))}</span><span class="muted">· ${escape(relativeDate(project.updated_at))}</span></p>
      <div class="continue-actions">${site}<a class="primary" href="${projectUrl(project.name)}" data-open-project aria-label="${label} 프로젝트 열기">열기</a></div>
    </div></section>`;
}

export function projectCards() {
  if (ui.projects === null) {
    if (ui.projectsError) return `<p class="empty error-text" role="alert">${escape(ui.projectsError)}</p>`;
    // Card-shaped placeholders while the list loads (static: nothing moves).
    return `<span class="sr-only" role="status">프로젝트를 불러오는 중입니다.</span>${'<div class="project-card card-placeholder" aria-hidden="true"><div class="project-drawing"></div><i></i><i></i><i></i></div>'.repeat(3)}`;
  }
  if (!ui.projects.length) {
    return `<div class="empty"><p>아직 프로젝트가 없습니다.</p><p>새 프로젝트를 만들거나 예시 프로젝트로 시작해 보세요.</p>
      <div class="empty-actions"><a class="primary" href="#/new">${icon('plus')}새 프로젝트</a>
      <button class="secondary" type="button" data-action="sample">예시 프로젝트 열기</button></div></div>`;
  }
  const projects = findProjects(ui.projects, ui.query, ui.sort);
  if (!projects.length) return '<p class="empty" role="status">검색 결과가 없습니다. 다른 프로젝트 이름으로 검색해 보세요.</p>';
  // A dashed "new project" card ends the list, so a short list does not leave an empty row.
  const add = ui.query.trim() ? '' : `<a class="project-new" href="#/new" data-open-project style="view-transition-name: project-new">${icon('plus', 'icon icon-large')}새 프로젝트</a>`;
  return projects.map((p) => {
    const entry = ui.projectSites.get(p.name);
    const card = entry?.card;
    const line = siteLine(card, p);
    // Over the empty drawing (outside the card's own link): what to do about the missing site.
    const site = siteSlot(entry) === 'none' ? `<div class="drawing-cta"><a class="secondary" href="${sitePath(p.name, 'find')}" aria-label="${escape(projectLabel(p))} 대지 정하기">대지 정하기</a></div>` : '';
    return `<article class="project-card" data-project="${escape(p.name)}" style="view-transition-name: ${transitionName(p)}"><a class="project-open" href="${projectUrl(p.name)}" data-open-project aria-label="${escape(projectLabel(p))} 프로젝트 열기">
    <div class="project-drawing">${siteDrawing(entry, 240, 180)}</div>
    <h3>${escape(projectLabel(p))}</h3>
    ${line ? `<p class="project-type">${line}</p>` : ''}
    <p class="project-summary">${expertDots(p)}<span>${escape(projectSummary(p))}</span></p>
    <div class="project-footer"><span>${escape(relativeDate(p.updated_at))}</span>${icon('open')}</div>
  </a>${site}<div class="project-card-actions"><button type="button" data-action="project-info" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 정보 수정">정보 수정</button>
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
          <label class="search-box">${icon('search')}<span class="sr-only">프로젝트 검색</span><input id="project-search" data-focus="project-search" type="search" placeholder="프로젝트 검색" value="${escape(ui.query)}" autocomplete="off"></label>
          <label class="sr-only" for="project-sort">프로젝트 정렬</label>
          <select id="project-sort"><option value="recent" ${ui.sort === 'recent' ? 'selected' : ''}>최근 수정순</option><option value="name" ${ui.sort === 'name' ? 'selected' : ''}>이름순</option></select>
        </div>
        <a class="primary" href="#/new" data-open-project>${icon('plus')}새 프로젝트</a></header>
      <div id="project-list">${projectList()}</div>
    </main></div>`;
}

// The new-project page keeps the list's sidebar; the way back sits right above the form, paired
// with "취소" at its foot. The site address comes second: it is what Sida works from.
export function newView() {
  const d = ui.newDraft;
  const value = (key) => escape(d[key] || '');
  return `<div class="app-shell">${sidebar(false)}
    <main class="home new-home" id="main" tabindex="-1">
      <a class="back-link" href="#/">${icon('back')}프로젝트</a>
      <form class="new-project" id="new-project-form" novalidate>
        <h1>새 프로젝트 만들기</h1>
        <label for="project-name">프로젝트 이름</label><input id="project-name" name="name" data-focus="new-name" value="${value('name')}" placeholder="예: 무교동 근린생활시설" required maxlength="80" autocomplete="off">
        <label for="project-site">대지 주소 (선택)</label><input id="project-site" name="site" data-focus="new-site" value="${value('site')}" placeholder="예: 서울 중구 무교동 45" maxlength="300" autocomplete="off" aria-describedby="project-site-hint">
        <p class="field-hint" id="project-site-hint">번지까지 정확히 적어 주세요. 비워 두면 나중에 대지 화면에서 정할 수 있어요.</p>
        <label for="project-type">프로젝트 유형 (선택)</label><input id="project-type" name="type" data-focus="new-type" value="${value('type')}" placeholder="예: 미술관, 단독주택" maxlength="200" autocomplete="off">
        <label for="project-description">설명 (선택)</label><textarea id="project-description" name="intention" data-focus="new-intention" placeholder="설계할 프로젝트와 지금 고민하는 점" maxlength="4000" aria-describedby="project-description-hint">${value('intention')}</textarea>
        <p class="field-hint" id="project-description-hint">다른 설계 조건은 Conductor와 대화하며 정리합니다.</p>
        <p class="form-error error-text" id="new-project-error" role="alert"></p>
        <div class="form-actions"><a class="secondary" href="#/">취소</a><button class="primary" type="submit" ${ui.creating ? 'disabled' : ''}>프로젝트 만들기</button></div>
      </form></main></div>`;
}
