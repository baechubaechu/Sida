// The Sida screen. Draws from the JSON API and keeps no project data in the browser:
// projects, the Conductor conversation, expert chats and results all live on this PC's server.
import {
  PHASES, STATUS_LABELS, PROVIDER_LABELS, MODE_LABELS, STATE_UPDATE_LABELS,
  escapeHtml as escape, findProjects, relativeDate, projectSummary, chatItems, eventNotice,
  expertStatus, renderMarkdown,
} from './model.js';

const app = document.querySelector('#app');
const announcer = document.querySelector('#announcer');
const toasts = document.querySelector('#toasts');
const settingsDialog = document.querySelector('#settings-dialog');
const settingsBody = document.querySelector('#settings-body');
const settingsForm = document.querySelector('#settings-form');

const POLL_MS = 1000;
const MAIN_JOBS = new Set(['opening', 'message', 'expert']);

const ui = {
  projects: null, projectsError: '', query: '', sort: 'recent',
  project: '', session: null, sessionError: '',
  chat: null, module: null, moduleMissing: false,
  job: null, live: [], pending: null,
  showExperts: false, revisionOpen: false, creating: false,
  settings: null, settingsDraft: null, settingsError: '', chatgptModels: null, chatgptNote: '',
};
const drafts = new Map();
const openingTried = new Set();
let currentRoute = { page: 'home' };
let trackToken = 0; // only the newest polling loop keeps going
let trackingId = null;

// ------------------------------------------------------------------ helpers

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = 'GET', body } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new ApiError(0, 'Sida 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해 주세요.'); }
  let data = null;
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : `요청이 실패했습니다 (${response.status})`;
    throw new ApiError(response.status, detail);
  }
  return data;
}

const projectApi = (name) => `/api/projects/${encodeURIComponent(name)}`;
const projectUrl = (name) => `#/project/${encodeURIComponent(name)}`;
const expertUrl = (name, agent) => `${projectUrl(name)}/expert/${encodeURIComponent(agent)}`;
const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
const announce = (text) => { announcer.textContent = text; };

function toast(text, tone = 'info') {
  const item = document.createElement('div');
  item.className = `toast ${tone}`;
  item.textContent = text;
  item.addEventListener('click', () => item.remove());
  toasts.append(item);
  while (toasts.children.length > 4) toasts.firstElementChild.remove();
  setTimeout(() => item.remove(), tone === 'error' ? 9000 : 5000);
}

function draftFor(key) {
  if (!drafts.has(key)) drafts.set(key, '');
  return drafts.get(key);
}

function expertById(agent) {
  return ui.session?.experts.find((e) => e.id === agent) || null;
}

function jobRunning() {
  return Boolean(ui.job && ui.job.status === 'running');
}

// ------------------------------------------------------------------ routing and loading

function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').map((p) => {
    try { return decodeURIComponent(p); } catch { return ''; }
  });
  if (parts[0] === 'new') return { page: 'new' };
  if (parts[0] === 'project' && parts[1]) {
    return { page: 'project', name: parts[1], agent: parts[2] === 'expert' ? parts[3] || '' : '' };
  }
  return { page: 'home' };
}

async function loadProjects() {
  try {
    ui.projects = (await api('/api/projects')).projects;
    ui.projectsError = '';
  } catch (error) {
    ui.projectsError = error.message;
  }
}

async function loadSession(name) {
  try {
    ui.session = await api(`${projectApi(name)}/session`);
    ui.sessionError = '';
  } catch (error) {
    ui.session = null;
    ui.sessionError = error.status === 404 ? '프로젝트를 찾을 수 없습니다.' : error.message;
  }
}

async function loadExpert(name, agent) {
  ui.chat = null;
  ui.module = null;
  ui.moduleMissing = false;
  const ran = expertById(agent)?.done;
  const [chat, module] = await Promise.allSettled([
    api(`${projectApi(name)}/experts/${encodeURIComponent(agent)}/chat`),
    ran ? api(`${projectApi(name)}/modules/${encodeURIComponent(agent)}`) : Promise.reject(new ApiError(404, '')),
  ]);
  if (chat.status === 'fulfilled') ui.chat = chat.value;
  if (module.status === 'fulfilled') ui.module = module.value;
  else ui.moduleMissing = module.reason?.status === 404;
}

async function refreshProject() {
  const { name, agent } = currentRoute;
  if (currentRoute.page !== 'project') return;
  await loadSession(name);
  if (agent && ui.session) await loadExpert(name, agent);
}

async function navigate() {
  const previous = currentRoute;
  currentRoute = route();
  ui.showExperts = false;
  ui.revisionOpen = false;
  if (currentRoute.page === 'home') {
    render();
    await loadProjects();
  } else if (currentRoute.page === 'project') {
    const { name, agent } = currentRoute;
    if (previous.page !== 'project' || previous.name !== name) {
      ui.session = null;
      ui.chat = null;
      ui.job = null;
      trackToken += 1;
      trackingId = null;
      ui.live = [];
      ui.pending = null;
      ui.project = name;
      render();
      if (!ui.projects) loadProjects().then(() => render(false));
      await loadSession(name);
    }
    if (agent && ui.session) {
      ui.chat = null;
      ui.module = null;
      ui.moduleMissing = false;
      render();
      await loadExpert(name, agent);
    }
    if (currentRoute.name !== name) return;
    render();
    if (!ui.session) return;
    if (ui.session.job) track(name, ui.session.job);
    else if (!ui.session.messages.length && !openingTried.has(name)) {
      openingTried.add(name);
      start(name, `${projectApi(name)}/session/opening`, {});
    }
    return;
  }
  render();
}

// ------------------------------------------------------------------ jobs

async function start(name, path, body, pending = null) {
  try {
    const { job } = await api(path, { method: 'POST', body });
    ui.pending = pending;
    track(name, job);
    return true;
  } catch (error) {
    if (error.status === 409) {
      toast('이전 작업이 아직 실행 중입니다. 끝나면 다시 보내 주세요.', 'warn');
      await refreshProject();
      if (ui.session?.job) track(name, ui.session.job);
    } else {
      toast(error.message, 'error');
    }
    render(false);
    return false;
  }
}

function handleEvent(event) {
  if (event.kind === 'conductor_reply') ui.live.push({ kind: 'conductor', text: event.data.text || '' });
  else if (event.kind === 'expert_reply') ui.live.push({ kind: 'expert', text: event.data.text || '' });
  else {
    const notice = eventNotice(event);
    if (!notice) return;
    ui.live.push({ kind: 'note', text: notice.text, tone: notice.tone });
    if (notice.toast) toast(notice.text, notice.tone);
    announce(notice.text);
  }
}

async function track(name, job) {
  if (trackingId === job.id) return; // already following it
  const token = ++trackToken;
  trackingId = job.id;
  ui.job = job;
  ui.live = [];
  let seen = 0;
  const take = (view) => {
    for (const event of view.events || []) {
      if (event.seq <= seen) continue;
      seen = event.seq;
      handleEvent(event);
    }
  };
  take(job);
  render(false);
  let view = job;
  let misses = 0;
  while (view.status === 'running') {
    await sleep(POLL_MS);
    if (token !== trackToken || ui.project !== name) return; // left the project; the server keeps going
    try {
      view = await api(`${projectApi(name)}/session/jobs/${encodeURIComponent(job.id)}?after=${seen}`);
      misses = 0;
    } catch (error) {
      if (error.status === 404) break; // the server restarted and forgot the job
      misses += 1;
      if (misses >= 5) { toast(error.message, 'error'); break; }
      continue;
    }
    take(view);
    ui.job = { ...view, events: [] };
    render(false);
  }
  if (token !== trackToken) return;
  trackingId = null;
  if (view.status === 'failed') toast(view.error || '작업이 실패했습니다.', 'error');
  ui.job = null;
  await refreshProject();
  ui.live = [];
  ui.pending = null;
  render(false);
  loadProjects();
}

// ------------------------------------------------------------------ views

function sidebar(active) {
  const home = currentRoute.page !== 'project';
  const projects = ui.projects ? findProjects(ui.projects) : [];
  const warned = ui.settings && Object.values(ui.settings.warnings || {}).some(Boolean);
  const others = projects.filter((p) => p.name !== active).slice(0, home ? 3 : 2);
  return `<aside class="sidebar" aria-label="프로젝트 탐색">
    <a class="brand" href="#/" aria-label="Sida 프로젝트 홈">Sida</a>
    <nav class="nav-main" aria-label="주 메뉴">
      ${home ? `<a class="nav-link ${currentRoute.page === 'home' ? 'active' : ''}" href="#/" ${currentRoute.page === 'home' ? 'aria-current="page"' : ''}>▦&nbsp; 프로젝트</a>` : ''}
      <a class="nav-link nav-new" href="#/new">＋&nbsp; 새 프로젝트</a>
    </nav>
    ${home
    ? `<section class="recent"><h2 class="nav-label">최근 항목</h2>
      ${others.map((p) => `<a class="nav-link" href="${projectUrl(p.name)}">${escape(p.name)}</a>`).join('')}</section>`
    : `<div class="project-nav"><h2 class="nav-label">프로젝트</h2>
        <a class="nav-link active" href="${projectUrl(active)}" aria-current="page">${escape(active)}</a>
        ${others.map((p) => `<a class="nav-link" href="${projectUrl(p.name)}">${escape(p.name)}</a>`).join('')}
      </div>
      <h2 class="nav-label history-label">대화</h2>
      <a class="nav-link history-link" href="${projectUrl(active)}" ${currentRoute.agent ? '' : 'aria-current="true"'}>Conductor 대화</a>`}
    <button class="nav-link sidebar-bottom" data-action="settings">설정${warned ? ' <span class="warn-dot" aria-label="확인할 설정 있음">●</span>' : ''}</button>
  </aside>`;
}

function projectCards() {
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
  return projects.map((p) => `<article class="project-card"><a class="project-open" href="${projectUrl(p.name)}" aria-label="${escape(p.name)} 프로젝트 열기">
    <h3>${escape(p.name)}</h3>
    <p class="project-type">${escape(p.project_type || '건축 설계')}</p>
    <p class="project-summary">${escape(projectSummary(p))}</p>
    <div class="project-footer"><span>${escape(relativeDate(p.updated_at))}</span><span aria-hidden="true">↗</span></div>
  </a></article>`).join('');
}

function homeView() {
  return `<div class="app-shell">${sidebar('')}
    <main class="home" id="main" tabindex="-1">
      <header class="home-heading"><div><h1>프로젝트</h1><p>건축 설계 프로젝트를 관리하고 이전 작업을 이어가세요.</p></div>
        <a class="primary" href="#/new">＋&nbsp; 새 프로젝트</a></header>
      <div class="project-tools">
        <label class="search-box"><span aria-hidden="true">⌕</span><span class="sr-only">프로젝트 검색</span><input id="project-search" type="search" placeholder="프로젝트 검색" value="${escape(ui.query)}" autocomplete="off"></label>
        <label class="sr-only" for="project-sort">프로젝트 정렬</label>
        <select id="project-sort"><option value="recent" ${ui.sort === 'recent' ? 'selected' : ''}>최근 수정순</option><option value="name" ${ui.sort === 'name' ? 'selected' : ''}>이름순</option></select>
      </div>
      <h2 class="section-label">내 프로젝트</h2><div class="project-grid" id="project-grid">${projectCards()}</div>
    </main></div>`;
}

function newView() {
  return `<main class="new-page" id="main" tabindex="-1">
    <header class="new-topbar"><a class="brand" href="#/">sida</a><a class="back-link" href="#/">← 프로젝트로 돌아가기</a></header>
    <form class="new-project" id="new-project-form" novalidate>
      <h1>새 프로젝트 만들기</h1><p class="intro">새 건축 설계 작업 공간을 만듭니다.</p>
      <label for="project-name">프로젝트 이름</label><input id="project-name" name="name" placeholder="제목 없는 프로젝트" required maxlength="80" autocomplete="off">
      <label for="project-type">프로젝트 유형</label><input id="project-type" name="type" placeholder="예: 미술관, 단독주택 (선택)" maxlength="200" autocomplete="off">
      <label for="project-site">대지 주소</label><input id="project-site" name="site" placeholder="지번 또는 도로명 주소 (선택)" maxlength="300" autocomplete="off">
      <label for="project-description">설명</label><textarea id="project-description" name="intention" placeholder="설계할 프로젝트와 지금 고민하는 점 (선택)" maxlength="4000"></textarea>
      <p class="form-note">대지 주소는 번지까지 정확히 적어 주세요. 다른 설계 조건은 Conductor와 대화하며 정리합니다.</p>
      <p class="form-error error-text" id="new-project-error" role="alert"></p>
      <div class="form-actions"><a class="secondary" href="#/">취소</a><button class="primary" type="submit" ${ui.creating ? 'disabled' : ''}>프로젝트 만들기</button></div>
    </form></main>`;
}

function composer(key, placeholder, label, disabled) {
  return `<form class="composer" data-composer="${escape(key)}" aria-label="${escape(label)} 입력">
    <textarea data-focus="${escape(key)}" aria-label="${escape(label)}에게 메시지" placeholder="${escape(placeholder)}" maxlength="6000" rows="1">${escape(draftFor(key))}</textarea>
    <div class="composer-footer"><span class="composer-hint">${disabled ? '작업이 끝나면 보낼 수 있습니다.' : 'Enter로 보내기, Shift+Enter로 줄바꿈'}</span>
      <button class="send-button" type="submit" aria-label="${escape(label)}에게 보내기" ${disabled ? 'disabled' : ''}>↑</button></div>
  </form>`;
}

function bubble(item, speaker) {
  if (item.kind === 'user') return `<article class="message-user" aria-label="내 메시지">${escape(item.text)}</article>`;
  if (item.kind === 'note') return `<p class="event-note ${item.tone || ''}">${escape(item.text)}</p>`;
  if (item.kind === 'card') {
    const expert = expertById(item.agent);
    const status = expert ? STATUS_LABELS[expertStatus(expert, ui.job)] : '';
    return `<button class="analysis-card" data-action="open-expert" data-agent="${escape(item.agent)}">
      <h2>${escape(item.name)} 결과</h2>
      <p class="analysis-meta">${escape(item.name)}${status ? ` · ${escape(status)}` : ''}</p>
      <span class="analysis-link">분석 보기 ↗</span></button>`;
  }
  return `<article><h3 class="speaker">${escape(speaker)}</h3><div class="assistant-copy markdown">${renderMarkdown(item.text)}</div></article>`;
}

function workingLine(forMain) {
  if (!jobRunning()) return '';
  const job = ui.job;
  if (forMain !== MAIN_JOBS.has(job.kind)) return '';
  const running = job.running_agent ? expertById(job.running_agent) : null;
  const text = running ? `${running.name} 실행 중입니다…` : forMain ? 'Conductor가 답을 쓰는 중입니다…' : '전문가가 답을 쓰는 중입니다…';
  return `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>${escape(text)}</p>`;
}

function mainChat(name) {
  const session = ui.session;
  if (!session) {
    return `<div class="chat-scroll"><p class="${ui.sessionError ? 'error-text' : 'muted'}">${escape(ui.sessionError || '대화를 불러오는 중입니다.')}</p>
      ${ui.sessionError ? '<p><a class="back-link" href="#/">← 프로젝트로 돌아가기</a></p>' : ''}</div>`;
  }
  const items = chatItems(session.messages);
  const live = MAIN_JOBS.has(ui.job?.kind) ? ui.live : [];
  const pending = ui.pending?.target === 'main' ? [{ kind: 'user', text: ui.pending.text }] : [];
  const empty = !items.length && !live.length && !pending.length && !jobRunning();
  return `<div class="chat-scroll" data-scroll="main"><h1>Conductor 대화</h1>
      ${empty ? '<p class="muted intro-line">설계 중인 프로젝트와 지금 고민하는 점을 알려 주세요.</p>' : ''}
      <div class="message-list" role="log" aria-label="대화 메시지">
        ${[...items, ...pending, ...live].map((item) => bubble(item, 'Sida')).join('')}
        ${workingLine(true)}
      </div>
    </div>${composer('main', 'Sida에게 설계에 관해 질문하세요...', 'Sida', jobRunning())}`;
}

function expertsPanel() {
  const experts = ui.session?.experts || [];
  return `<aside class="experts" aria-label="전문가 목록"><h2>전문가</h2><p class="experts-intro">결과 문서와 전문가별 채팅</p>
    ${experts.map((e) => {
    const status = expertStatus(e, ui.job);
    return `<button class="expert-row-button" data-action="open-expert" data-agent="${escape(e.id)}">
        <span class="expert-name">${escape(e.name)}</span>
        <span class="expert-phase">${escape(PHASES[e.phase] || e.phase)}</span>
        <span class="status-badge ${status}">${escape(STATUS_LABELS[status])}</span></button>`;
  }).join('')}</aside>`;
}

function proposalBlock(agent) {
  const proposal = ui.session?.proposal;
  if (!proposal || proposal.agent !== agent) return '';
  return `<section class="proposal" aria-label="설계 상태 반영안">
    <h3>설계 상태에 반영할까요?</h3>
    <p class="muted">이 결과로 바뀌는 설계 상태(PROJECT STATE)입니다.</p>
    <pre class="diff">${escape(proposal.diff)}</pre>
    <div class="form-actions"><button class="secondary" data-action="skip-proposal" data-id="${escape(proposal.id)}">건너뛰기</button>
      <button class="primary" data-action="apply-proposal" data-id="${escape(proposal.id)}">반영하기</button></div>
  </section>`;
}

function expertPane(name, agent) {
  const expert = expertById(agent);
  if (!expert) {
    return `<section class="expert-chat"><header class="expert-chat-header"><div><h2>전문가를 찾을 수 없습니다</h2></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="전문가 화면 닫기">×</a></header></section>`;
  }
  const status = expertStatus(expert, ui.job);
  const busy = jobRunning();
  const chatOn = ui.chat ? ui.chat.chat : expert.chat;
  const items = chatItems(ui.chat?.messages);
  const live = ui.job?.kind === 'expert_chat' && ui.job.agent === agent ? ui.live : [];
  const pending = ui.pending?.target === agent ? [{ kind: 'user', text: ui.pending.text }] : [];
  const loading = !ui.chat && !ui.module && !ui.moduleMissing;
  const doc = ui.module
    ? `<details class="doc-block" ${items.length ? '' : 'open'}><summary>결과 문서 <span class="muted">${escape(relativeDate(ui.module.updated_at))}</span></summary>
        <div class="markdown doc">${renderMarkdown(ui.module.content)}</div></details>`
    : `<div class="expert-note">${loading ? '불러오는 중입니다.' : '아직 실행 전입니다. 실행하면 결과 문서가 여기에 나옵니다.'}</div>`;
  const revision = ui.revisionOpen
    ? `<form class="revision-form" id="revision-form"><label for="revision-text">무엇을 고칠지 적어 주세요</label>
        <textarea id="revision-text" data-focus="revision" maxlength="4000" rows="3">${escape(draftFor(`revision:${agent}`))}</textarea>
        <div class="form-actions"><button class="secondary" type="button" data-action="close-revision">취소</button>
        <button class="primary" type="submit" ${busy ? 'disabled' : ''}>수정 요청 보내기</button></div></form>`
    : '';
  return `<section class="expert-chat" aria-label="${escape(expert.name)}">
    <header class="expert-chat-header"><div><h2>${escape(expert.name)}</h2>
      <p>${escape(PHASES[expert.phase] || expert.phase)} · <span class="status-badge ${status}">${escape(STATUS_LABELS[status])}</span></p></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="전문가 화면 닫기">×</a></header>
    <div class="expert-actions">
      <button class="secondary small" data-action="run-expert" data-agent="${escape(agent)}" ${busy ? 'disabled' : ''}>${expert.done ? '다시 실행' : '실행'}</button>
      ${expert.done ? `<button class="secondary small" data-action="open-revision" ${busy ? 'disabled' : ''}>수정 요청</button>` : ''}
    </div>
    <div class="chat-scroll" data-scroll="expert:${escape(agent)}">
      ${proposalBlock(agent)}${revision}${doc}
      ${chatOn ? '' : `<p class="expert-note muted">${escape(expert.name)}는 정부 데이터에서 온 사실을 다루기 때문에 채팅이 없습니다. 바꿀 내용은 수정 요청으로 보내 주세요.</p>`}
      <div class="message-list" role="log" aria-label="${escape(expert.name)} 대화">
        ${[...items, ...pending, ...live].map((item) => bubble(item, expert.name)).join('')}
        ${workingLine(false)}
      </div>
    </div>
    ${chatOn ? composer(`expert:${agent}`, `${expert.name}에게 메시지...`, expert.name, busy) : ''}
  </section>`;
}

function workspaceView() {
  const { name, agent } = currentRoute;
  const expert = agent ? expertById(agent) : null;
  return `<div class="app-shell workspace">${sidebar(name)}
    <main class="workspace-main" id="main" tabindex="-1">
      <header class="workspace-header"><div class="breadcrumb"><a href="#/">${escape(name)}</a><span>/</span><span>${escape(expert ? expert.name : 'Conductor 대화')}</span></div>
        <div class="workspace-controls"><button class="mobile-experts" data-action="toggle-experts">${agent || ui.showExperts ? '채팅' : '전문가'}</button></div></header>
      <div class="chat-layout ${agent ? 'split' : ''} ${ui.showExperts && !agent ? 'show-experts' : ''}">
        <section class="chat-main" aria-label="Conductor 대화">${mainChat(name)}</section>
        <div class="divider" role="separator" aria-label="패널 너비 조절" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow="50" tabindex="0">⋮</div>
        ${agent ? expertPane(name, agent) : expertsPanel()}
      </div>
    </main></div>`;
}

function render(fresh = true) {
  // Keep typing and reading positions across redraws.
  const focused = document.activeElement?.dataset?.focus;
  const selection = focused ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  const scrolls = new Map();
  for (const el of app.querySelectorAll('[data-scroll]')) {
    scrolls.set(el.dataset.scroll, { top: el.scrollTop, bottom: el.scrollHeight - el.scrollTop - el.clientHeight < 40 });
  }
  const page = currentRoute.page;
  app.innerHTML = page === 'home' ? homeView() : page === 'new' ? newView() : workspaceView();
  document.title = `Sida · ${page === 'project' ? currentRoute.name : page === 'new' ? '새 프로젝트' : '프로젝트'}`;
  for (const el of app.querySelectorAll('[data-scroll]')) {
    const saved = fresh ? null : scrolls.get(el.dataset.scroll);
    el.scrollTop = !saved || saved.bottom ? el.scrollHeight : saved.top;
  }
  const again = focused && app.querySelector(`[data-focus="${CSS.escape(focused)}"]`);
  if (again) {
    again.focus({ preventScroll: true });
    if (selection) again.setSelectionRange(...selection);
  } else if (fresh) {
    document.querySelector('#main')?.focus({ preventScroll: true });
  }
}

// ------------------------------------------------------------------ actions

async function createSample() {
  try {
    const { project } = await api('/api/projects/sample', { method: 'POST' });
    await loadProjects();
    location.hash = projectUrl(project.name);
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function decideProposal(id, apply) {
  const { name } = currentRoute;
  try {
    const path = apply
      ? `${projectApi(name)}/state-proposals/${encodeURIComponent(id)}/apply`
      : `${projectApi(name)}/state-proposals/${encodeURIComponent(id)}/skip`;
    await api(path, { method: 'POST' });
    toast(apply ? '설계 상태에 반영했습니다.' : '이번 반영안은 건너뛰었습니다.', apply ? 'success' : 'info');
  } catch (error) {
    toast(error.message, 'error');
  }
  await refreshProject();
  render(false);
}

function send(key) {
  const { name, agent } = currentRoute;
  const text = draftFor(key).trim();
  if (!text || jobRunning()) return;
  drafts.delete(key);
  if (key === 'main') {
    start(name, `${projectApi(name)}/session/messages`, { text }, { target: 'main', text });
  } else {
    start(name, `${projectApi(name)}/experts/${encodeURIComponent(agent)}/chat`, { text }, { target: agent, text });
  }
}

app.addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action } = button.dataset;
  const { name, agent } = currentRoute;
  if (action === 'settings') openSettings();
  if (action === 'sample') createSample();
  if (action === 'toggle-experts') {
    if (agent) location.hash = projectUrl(name);
    else { ui.showExperts = !ui.showExperts; render(false); }
  }
  if (action === 'open-expert') location.hash = expertUrl(name, button.dataset.agent);
  if (action === 'run-expert') start(name, `${projectApi(name)}/session/experts/${encodeURIComponent(button.dataset.agent)}/run`, {});
  if (action === 'open-revision') { ui.revisionOpen = true; render(false); app.querySelector('#revision-text')?.focus(); }
  if (action === 'close-revision') { ui.revisionOpen = false; render(false); }
  if (action === 'apply-proposal') decideProposal(button.dataset.id, true);
  if (action === 'skip-proposal') decideProposal(button.dataset.id, false);
});

app.addEventListener('input', (event) => {
  const { target } = event;
  if (target.id === 'project-search') {
    ui.query = target.value;
    document.querySelector('#project-grid').innerHTML = projectCards();
  }
  if (target.matches('.composer textarea')) drafts.set(target.closest('form').dataset.composer, target.value);
  if (target.id === 'revision-text') drafts.set(`revision:${currentRoute.agent}`, target.value);
});

app.addEventListener('change', (event) => {
  if (event.target.id === 'project-sort') {
    ui.sort = event.target.value;
    document.querySelector('#project-grid').innerHTML = projectCards();
  }
});

app.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.id === 'new-project-form') {
    const name = form.elements.name.value.trim();
    const error = form.querySelector('#new-project-error');
    if (!name) { error.textContent = '프로젝트 이름을 입력해 주세요.'; form.elements.name.focus(); return; }
    const fields = {};
    for (const key of ['type', 'site', 'intention']) {
      const value = form.elements[key].value.trim();
      if (value) fields[key] = value;
    }
    ui.creating = true;
    form.querySelector('button[type="submit"]').disabled = true;
    try {
      const { project, created } = await api('/api/projects', { method: 'POST', body: { name, fields } });
      if (!created) toast(`같은 이름의 프로젝트 "${project.name}"를 열었습니다.`, 'info');
      await loadProjects();
      location.hash = projectUrl(project.name);
    } catch (err) {
      error.textContent = err.message;
      form.querySelector('button[type="submit"]').disabled = false;
    } finally {
      ui.creating = false;
    }
  } else if (form.matches('.composer')) {
    send(form.dataset.composer);
  } else if (form.id === 'revision-form') {
    const { name, agent } = currentRoute;
    const key = `revision:${agent}`;
    const revision = draftFor(key).trim();
    if (!revision || jobRunning()) return;
    drafts.delete(key);
    ui.revisionOpen = false;
    start(name, `${projectApi(name)}/session/experts/${encodeURIComponent(agent)}/run`, { revision });
  }
});

function resizePanel(separator, delta, absolute = false) {
  const layout = separator.parentElement;
  const bounds = layout.getBoundingClientRect();
  const current = layout.querySelector('.chat-main').getBoundingClientRect().width;
  const width = Math.max(bounds.width * 0.25, Math.min(bounds.width * 0.75, absolute ? delta : current + delta));
  if (layout.classList.contains('split')) layout.style.setProperty('--split-left', `${width}px`);
  else layout.style.setProperty('--expert-width', `${Math.max(240, bounds.width - width - 12)}px`);
  separator.setAttribute('aria-valuenow', String(Math.round((width / bounds.width) * 100)));
}

app.addEventListener('keydown', (event) => {
  if (event.target.matches('.composer textarea') && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    event.target.closest('form').requestSubmit();
  }
  if (event.target.matches('.divider') && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault();
    resizePanel(event.target, event.key === 'ArrowLeft' ? -24 : 24);
  }
});

app.addEventListener('pointerdown', (event) => {
  if (!event.target.matches('.divider') || event.button !== 0) return;
  const separator = event.target;
  separator.setPointerCapture(event.pointerId);
  const bounds = separator.parentElement.getBoundingClientRect();
  const move = (e) => resizePanel(separator, e.clientX - bounds.left, true);
  separator.addEventListener('pointermove', move);
  separator.addEventListener('lostpointercapture', () => separator.removeEventListener('pointermove', move), { once: true });
});

// ------------------------------------------------------------------ settings

function draftFromSettings(settings) {
  return {
    mode: settings.mode,
    local_profile: settings.local_profile,
    conductor_provider: settings.conductor.provider,
    worker_provider: settings.worker.provider,
    chatgpt_model: settings.chatgpt.model,
    rag_enabled: settings.rag_enabled,
    state_update: settings.state_update,
    telemetry_enabled: settings.telemetry_enabled,
    openrouter_key: '',
  };
}

const option = (value, label, selected) => `<option value="${escape(value)}" ${value === selected ? 'selected' : ''}>${escape(label)}</option>`;

function renderSettings() {
  const s = ui.settings;
  const d = ui.settingsDraft;
  if (!s || !d) {
    settingsBody.innerHTML = `<p class="${ui.settingsError ? 'error-text' : 'muted'}">${escape(ui.settingsError || '설정을 불러오는 중입니다.')}</p>`;
    return;
  }
  const warnings = [
    s.warnings.openrouter_key_missing && 'OpenRouter 키가 없습니다. 클라우드 모델을 쓰려면 아래에 키를 넣어 주세요.',
    s.warnings.rag_key_missing && '법령 검색을 켰지만 법제처 인증값이 없습니다. 이전 화면의 설정에서 넣어 주세요.',
    s.warnings.chatgpt_signed_out && 'Conductor가 ChatGPT 구독으로 되어 있지만 로그인되어 있지 않습니다.',
  ].filter(Boolean);
  const modes = d.mode === 'custom' ? [...s.options.modes, 'custom'] : s.options.modes;
  const chatgpt = s.chatgpt;
  const models = ui.chatgptModels?.length ? ui.chatgptModels : [{ slug: d.chatgpt_model, display_name: d.chatgpt_model }];
  const chatgptBlock = d.conductor_provider === 'chatgpt' || chatgpt.signed_in
    ? `<fieldset class="settings-group"><legend>ChatGPT 구독</legend>
        <p>${chatgpt.signed_in ? `로그인됨: ${escape(chatgpt.email || 'ChatGPT')}` : '로그인되어 있지 않습니다.'}</p>
        ${chatgpt.signed_in && !chatgpt.plan_usage ? '<p class="error-text">구독 사용을 허용하지 않아 Conductor가 쓸 수 없습니다. 다시 로그인해 주세요.</p>' : ''}
        <div class="settings-buttons">
          <button type="button" class="secondary small" data-settings="chatgpt-login">${chatgpt.signed_in ? '다시 로그인' : 'ChatGPT로 로그인'}</button>
          ${chatgpt.signed_in ? '<button type="button" class="secondary small" data-settings="chatgpt-logout">로그아웃</button>' : ''}
        </div>
        ${ui.chatgptNote ? `<p class="muted">${escape(ui.chatgptNote)}</p>` : ''}
        ${chatgpt.signed_in ? `<label for="set-chatgpt-model">Conductor 모델</label>
          <select id="set-chatgpt-model" data-field="chatgpt_model">${models.map((m) => option(m.slug, m.display_name || m.slug, d.chatgpt_model)).join('')}</select>` : ''}
      </fieldset>`
    : '';
  const keyStatus = s.keys?.openrouter;
  settingsBody.innerHTML = `
    ${s.first_run ? '<p class="settings-intro">처음 실행입니다. 실행 방식을 확인하고 저장해 주세요.</p>' : ''}
    ${warnings.map((w) => `<p class="event-note warn">${escape(w)}</p>`).join('')}
    <label for="set-mode">실행 모드</label>
    <select id="set-mode" data-field="mode">${modes.map((m) => option(m, MODE_LABELS[m] || m, d.mode)).join('')}</select>
    ${d.mode === 'local' && s.options.local_profiles.length ? `<label for="set-profile">로컬 프로필</label>
      <select id="set-profile" data-field="local_profile">${s.options.local_profiles.map((p) => option(p, p, d.local_profile)).join('')}</select>` : ''}
    <label for="set-conductor">Conductor</label>
    <select id="set-conductor" data-field="conductor_provider">${s.options.conductor_providers.map((p) => option(p, PROVIDER_LABELS[p] || p, d.conductor_provider)).join('')}</select>
    <label for="set-worker">전문가</label>
    <select id="set-worker" data-field="worker_provider">${s.options.providers.map((p) => option(p, PROVIDER_LABELS[p] || p, d.worker_provider)).join('')}</select>
    <p class="muted small-text">지금 모델: Conductor ${escape(s.conductor.model)}, 전문가 ${escape(s.worker.model)}</p>
    ${chatgptBlock}
    <label for="set-openrouter">OpenRouter 키</label>
    <input id="set-openrouter" data-field="openrouter_key" type="password" autocomplete="off" placeholder="${escape(keyStatus?.set ? `저장됨 ${keyStatus.hint || ''}` : '키를 넣으면 저장할 때 확인합니다')}" value="${escape(d.openrouter_key)}">
    <label for="set-state">전문가 결과를 설계 상태에</label>
    <select id="set-state" data-field="state_update">${s.options.state_update.map((m) => option(m, STATE_UPDATE_LABELS[m] || m, d.state_update)).join('')}</select>
    <label class="check"><input type="checkbox" data-field="rag_enabled" ${d.rag_enabled ? 'checked' : ''}> 법령 검색(법제처) 쓰기</label>
    <label class="check"><input type="checkbox" data-field="telemetry_enabled" ${d.telemetry_enabled ? 'checked' : ''}> 사용 기록 보내기 (브리프·문서 원문은 보내지 않음)</label>
    <p class="error-text" role="alert">${escape(ui.settingsError)}</p>
    <div class="form-actions"><a class="secondary" href="/classic">이전 화면</a><button type="button" class="primary" data-settings="save">저장</button></div>`;
}

async function loadSettings() {
  try {
    ui.settings = await api('/api/settings');
    ui.settingsError = '';
  } catch (error) {
    ui.settingsError = error.message;
  }
}

async function loadChatgptModels() {
  if (!ui.settings?.chatgpt.signed_in) { ui.chatgptModels = null; return; }
  try { ui.chatgptModels = (await api('/api/settings/chatgpt/models')).models; }
  catch (error) { ui.chatgptModels = null; ui.chatgptNote = `모델 목록을 받지 못했습니다. ${error.message}`; }
}

async function openSettings() {
  ui.settingsError = '';
  ui.chatgptNote = '';
  renderSettings();
  if (!settingsDialog.open) settingsDialog.showModal();
  await loadSettings();
  if (ui.settings) ui.settingsDraft = draftFromSettings(ui.settings);
  await loadChatgptModels();
  renderSettings();
}

async function saveSettings() {
  const s = ui.settings;
  const d = ui.settingsDraft;
  const changes = {};
  if (d.mode !== s.mode && d.mode !== 'custom') changes.mode = d.mode;
  if (d.local_profile !== s.local_profile) changes.local_profile = d.local_profile;
  if (d.conductor_provider !== s.conductor.provider) changes.conductor_provider = d.conductor_provider;
  if (d.worker_provider !== s.worker.provider) changes.worker_provider = d.worker_provider;
  if (d.chatgpt_model && d.chatgpt_model !== s.chatgpt.model) changes.chatgpt_model = d.chatgpt_model;
  if (d.rag_enabled !== s.rag_enabled) changes.rag_enabled = d.rag_enabled;
  if (d.state_update !== s.state_update) changes.state_update = d.state_update;
  if (d.telemetry_enabled !== s.telemetry_enabled) changes.telemetry_enabled = d.telemetry_enabled;
  try {
    if (d.openrouter_key.trim()) {
      await api('/api/settings/keys/openrouter', { method: 'PUT', body: { value: d.openrouter_key.trim() } });
    }
    ui.settings = await api('/api/settings', { method: 'PUT', body: changes });
    ui.settingsDraft = draftFromSettings(ui.settings);
    ui.settingsError = '';
    settingsDialog.close();
    toast('설정을 저장했습니다.', 'success');
    render(false);
  } catch (error) {
    ui.settingsError = error.message;
    renderSettings();
  }
}

settingsDialog.addEventListener('change', (event) => {
  const field = event.target.dataset.field;
  if (!field || !ui.settingsDraft) return;
  const d = ui.settingsDraft;
  d[field] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
  if (field === 'mode' && d.mode !== 'custom') {
    // A mode sets both roles; keep the role choices consistent with it.
    const provider = d.mode === 'cloud' ? 'openrouter' : 'ollama';
    d.conductor_provider = provider;
    d.worker_provider = provider;
  }
  if (field === 'conductor_provider' || field === 'worker_provider') {
    d.mode = d.conductor_provider === d.worker_provider && d.conductor_provider !== 'chatgpt'
      ? (d.conductor_provider === 'openrouter' ? 'cloud' : 'local') : 'custom';
  }
  if (field !== 'openrouter_key') renderSettings();
});

settingsDialog.addEventListener('input', (event) => {
  if (event.target.dataset.field === 'openrouter_key' && ui.settingsDraft) ui.settingsDraft.openrouter_key = event.target.value;
});

settingsDialog.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-settings]');
  if (!button) return;
  const action = button.dataset.settings;
  if (action === 'save') saveSettings();
  if (action === 'close') settingsDialog.close();
  if (action === 'chatgpt-login') {
    try {
      const { authorize_url: url } = await api('/api/settings/chatgpt/login', { method: 'POST', body: {} });
      window.open(url, '_blank', 'noopener');
      ui.chatgptNote = '열린 창에서 로그인을 마치고 이 화면으로 돌아오면 상태가 바뀝니다. 10분 안에 끝내 주세요.';
    } catch (error) {
      ui.chatgptNote = error.message;
    }
    renderSettings();
  }
  if (action === 'chatgpt-logout') {
    try {
      const { revoked } = await api('/api/settings/chatgpt', { method: 'DELETE' });
      ui.chatgptNote = revoked ? '로그아웃했습니다.' : '이 PC에서는 로그아웃했지만 OpenAI 쪽 연결 해제를 확인하지 못했습니다. ChatGPT 설정에서 Sida 연결을 끊어 주세요.';
    } catch (error) {
      ui.chatgptNote = error.message;
    }
    const draft = ui.settingsDraft;
    await loadSettings();
    ui.settingsDraft = { ...draftFromSettings(ui.settings), ...draft, chatgpt_model: ui.settings.chatgpt.model };
    ui.chatgptModels = null;
    renderSettings();
  }
});

settingsForm.addEventListener('submit', (event) => {
  event.preventDefault(); // Enter in a field must not close the dialog unsaved
});

window.addEventListener('focus', async () => {
  // Coming back from the ChatGPT sign-in window.
  if (!settingsDialog.open || !ui.settings || !ui.settingsDraft) return;
  const before = ui.settings.chatgpt.signed_in;
  const draft = ui.settingsDraft;
  await loadSettings();
  if (!ui.settings) return;
  ui.settingsDraft = { ...draft };
  if (ui.settings.chatgpt.signed_in !== before) {
    ui.chatgptNote = ui.settings.chatgpt.signed_in ? 'ChatGPT 로그인을 확인했습니다.' : '';
    await loadChatgptModels();
  }
  renderSettings();
});

// ------------------------------------------------------------------ start

window.addEventListener('hashchange', navigate);
document.querySelector('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  document.querySelector('#main')?.focus();
});

navigate();
loadSettings().then(() => {
  if (ui.settings?.first_run) openSettings();
  else render(false);
});
