import {
  STORAGE_KEY, EXPERTS, initialState, restoreState, findProjects, addProject, deleteProject,
  threadList, addThread, messageKey, sendMessage,
} from './model.js';

const app = document.querySelector('#app');
const announcer = document.querySelector('#announcer');
const dialog = document.querySelector('#settings-dialog');
const deleteDialog = document.querySelector('#delete-project-dialog');
let pendingDeleteId = null;
let state;
try { state = restoreState(localStorage.getItem(STORAGE_KEY)); }
catch { state = initialState(); }
let query = '';
let sort = 'recent';
let showExperts = false;
const drafts = new Map();
let currentRoute;

// All user-controlled values pass through this boundary before HTML rendering.
const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[c]);
const projectUrl = (id, thread = '01') => `#/project/${id}/chat/${thread}`;
const expertUrl = (id, expert, thread = '01', mainThread = '01') => `${projectUrl(id, mainThread)}/expert/${expert}/${thread}`;
const announce = (text) => { announcer.textContent = text; };

function save() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
  catch { announce('브라우저에 저장할 수 없어 이번에 연 페이지에서만 변경 내용이 유지됩니다.'); }
}

function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/');
  if (parts[0] === 'new') return { page: 'new' };
  if (parts[0] !== 'project') return { page: 'home' };
  const project = state.projects.find((p) => p.id === parts[1]);
  if (!project) return { page: 'home' };
  const mainThread = /^\d+$/.test(parts[3] || '') ? parts[3] : '01';
  const expert = EXPERTS.find(([id]) => id === parts[5]);
  const thread = expert ? threadList(state, project.id, expert[0]).find((t) => t.id === parts[6]) : null;
  return { page: 'project', project, mainThread, expert: thread ? expert : null, thread };
}

function mainThreads(projectId) {
  const key = `${projectId}:main`;
  if (!Object.hasOwn(state.threads, key)) state.threads[key] = [{ id: '01', title: '메인 채팅' }];
  return state.threads[key];
}

function sidebar(project, mainThread = '01') {
  const home = !project;
  return `<aside class="sidebar" aria-label="프로젝트 탐색">
    <a class="brand" href="#/" aria-label="Sida 프로젝트 홈">Sida</a>
    <nav class="nav-main" aria-label="주 메뉴">
      ${home ? '<a class="nav-link active" href="#/" aria-current="page">▦&nbsp; 프로젝트</a>' : ''}
      <a class="nav-link nav-new" href="#/new">＋&nbsp; 새 프로젝트</a>
    </nav>
    ${home ? `<section class="recent"><h2 class="nav-label">최근 항목</h2>
      ${findProjects(state.projects).slice(0, 3).map((p) => `<a class="nav-link" href="${projectUrl(p.id)}">${escape(p.name)}</a>`).join('')}</section>`
      : `<div class="project-nav"><h2 class="nav-label">프로젝트</h2>
        ${[project, ...state.projects.filter((p) => p.id !== project.id).slice(0, 1)].map((p) => `<a class="nav-link ${p.id === project.id ? 'active' : ''}" href="${projectUrl(p.id)}" ${p.id === project.id ? 'aria-current="page"' : ''}>${escape(p.name)}</a>`).join('')}
      </div>
      <button class="nav-link new-chat" data-action="new-main">＋&nbsp; 새 채팅</button>
      <h2 class="nav-label history-label">대화 기록</h2>
      ${mainThreads(project.id).map((t) => `<a class="nav-link history-link" href="${projectUrl(project.id, t.id)}" ${mainThread === t.id ? 'aria-current="true"' : ''}>${escape(t.title)}</a>`).join('')}`}
    <button class="nav-link sidebar-bottom" data-action="settings">${home ? '설정' : '프로젝트 설정'}</button>
  </aside>`;
}

function projectCards() {
  const projects = findProjects(state.projects, query, sort);
  if (!state.projects.length) return '<div class="empty"><p>아직 프로젝트가 없습니다.</p><p>새 프로젝트를 만들어 설계 작업을 시작하세요.</p><a class="primary" href="#/new">＋ 새 프로젝트</a></div>';
  return projects.length ? projects.map((p) => `<article class="project-card"><a class="project-open" href="${projectUrl(p.id)}" aria-label="${escape(p.name)} 프로젝트 열기">
    <h3>${escape(p.name)}</h3>
    <p class="project-type">${escape(p.type)} · ${escape(p.phase)}</p>
    <p class="project-summary">${escape(p.summary)}</p>
    <div class="project-footer"><span>${escape(p.date)}</span><span aria-hidden="true">↗</span></div>
  </a><details class="project-menu"><summary aria-label="${escape(p.name)} 프로젝트 메뉴">⋯</summary>
    <button type="button" class="delete-project" data-action="delete-project" data-project="${p.id}">프로젝트 삭제</button>
  </details></article>`).join('') : '<p class="empty" role="status">검색 결과가 없습니다. 다른 프로젝트 이름으로 검색해 보세요.</p>';
}

function homeView() {
  return `<div class="app-shell">${sidebar()}
    <main class="home" id="main" tabindex="-1" data-figma-node="3:2">
      <header class="home-heading"><div><h1>프로젝트</h1><p>건축 설계 프로젝트를 관리하고 이전 작업을 이어가세요.</p></div>
        <a class="primary" href="#/new">＋&nbsp; 새 프로젝트</a></header>
      <div class="project-tools">
        <label class="search-box"><span aria-hidden="true">⌕</span><span class="sr-only">프로젝트 검색</span><input id="project-search" type="search" placeholder="프로젝트 검색" value="${escape(query)}" autocomplete="off"></label>
        <label class="sr-only" for="project-sort">프로젝트 정렬</label>
        <select id="project-sort"><option value="recent" ${sort === 'recent' ? 'selected' : ''}>최근 수정순</option><option value="name" ${sort === 'name' ? 'selected' : ''}>이름순</option></select>
      </div>
      <h2 class="section-label">내 프로젝트</h2><div class="project-grid" id="project-grid">${projectCards()}</div>
    </main></div>`;
}

function newView() {
  return `<main class="new-page" id="main" tabindex="-1" data-figma-node="10:34">
    <header class="new-topbar"><a class="brand" href="#/">sida</a><a class="back-link" href="#/">← 프로젝트로 돌아가기</a></header>
    <form class="new-project" id="new-project-form">
      <h1>새 프로젝트 만들기</h1><p class="intro">새 건축 설계 작업 공간을 만듭니다.</p>
      <label for="project-name">프로젝트 이름</label><input id="project-name" name="name" placeholder="제목 없는 프로젝트" required maxlength="80" autocomplete="off">
      <label for="project-description">설명</label><textarea id="project-description" name="description" placeholder="설계할 프로젝트를 설명해 주세요 (선택)" maxlength="2000"></textarea>
      <p class="form-note">참고 자료와 설계 조건은 나중에 추가할 수 있습니다.</p>
      <div class="form-actions"><a class="secondary" href="#/">취소</a><button class="primary" type="submit">프로젝트 만들기</button></div>
    </form></main>`;
}

function draftFor(key) {
  if (!drafts.has(key)) drafts.set(key, { text: '', files: [] });
  return drafts.get(key);
}

function attachmentChips(files, removable = false, key = '') {
  return files.map((file, index) => removable
    ? `<button class="attachment" type="button" data-action="remove-file" data-key="${key}" data-index="${index}" aria-label="${escape(file)} 첨부 취소">${escape(file)} ×</button>`
    : `<span class="attachment">${escape(file)}</span>`).join('');
}

function composer(key, placeholder, expert = false) {
  const draft = draftFor(key);
  return `<form class="composer" data-message-key="${key}" aria-label="${expert ? '전문가' : '메인'} 채팅 입력">
    <textarea aria-label="${expert ? '전문가' : 'Sida'}에게 메시지" placeholder="${escape(placeholder)}" maxlength="6000" rows="1">${escape(draft.text)}</textarea>
    <div class="attachment-list">${attachmentChips(draft.files, true, key)}</div>
    <div class="composer-footer"><button class="attach-button" type="button" data-action="attach">＋ 파일 첨부</button>
      <input class="file-input" type="file" multiple hidden aria-label="참고 파일 선택">
      <button class="send-button" type="submit" aria-label="${expert ? '전문가' : 'Sida'}에게 보내기">↑</button></div>
  </form>`;
}

function messageList(key) {
  return `<div class="message-list" data-list-key="${key}" role="log" aria-label="대화 메시지">${(state.messages[key] || []).map((m) =>
    m.role === 'user' ? `<article class="message-user" aria-label="내 메시지">${escape(m.text)}${m.files.length ? `<div class="attachment-list">${attachmentChips(m.files)}</div>` : ''}</article>`
      : `<article><h3 class="speaker">Sida <span class="mock-response-label">샘플 응답</span></h3><p class="assistant-copy">${escape(m.text)}</p></article>`).join('')}</div>`;
}

function expertsView(project, expanded = '') {
  return `<aside class="experts" aria-label="전문가 목록"><h2>전문가</h2><p class="experts-intro">전문가별 채팅</p>
    ${EXPERTS.map(([id, name]) => `<details class="expert-row ${id === '41' ? 'spatial' : ''}" ${id === expanded ? 'open' : ''}>
      <summary><span>${id}</span><span>${name}</span></summary>
      <div class="expert-threads"><button data-action="new-expert" data-expert="${id}">＋ 새 분석 채팅</button>
        ${threadList(state, project.id, id).map((thread, i) => `<button data-action="open-expert" data-expert="${id}" data-thread="${thread.id}">${escape(thread.title)} · ${i === 1 ? '진행 중' : '검토 필요'}</button>`).join('')}
      </div></details>`).join('')}</aside>`;
}

function expertChatView(view) {
  const { project, expert, thread } = view;
  const key = messageKey(project.id, expert[0], thread.id);
  const spatial = expert[0] === '41';
  return `<section class="expert-chat" aria-label="${escape(thread.title)} 전문가 채팅">
    <header class="expert-chat-header"><div><h2>${escape(thread.title)}</h2><p>${expert[1]} · 전문가 채팅</p></div><a class="icon-button" href="${projectUrl(project.id, view.mainThread)}" aria-label="전문가 채팅 닫기">×</a></header>
    <div class="chat-scroll"><p class="expert-note">${spatial ? '현재 검토 중인 동선 연결 관계와 필요한 도면을 확인합니다.' : `${expert[1]}의 관점에서 설계 의도와 검토할 조건을 확인합니다.`}</p>
      <div class="expert-reply"><h3>${expert[1]}</h3>${spatial
        ? '<p>중앙 보이드 계단과 상층 순환 동선 사이의<br>접속 조건을 평면과 단면에서 검증해야 합니다.<br>추가 단면도나 배치 자료를 제공해 주세요.</p>'
        : '<p>설계의 현재 방향과 고민을 알려 주세요.<br>확인할 근거와 아직 정하지 않은 조건을 함께 살펴봅니다.</p>'}</div>
      ${messageList(key)}</div>
    ${composer(key, `${expert[1]}에게 메시지...`, true)}
  </section>`;
}

function workspaceView(view) {
  const { project, mainThread, expert } = view;
  const key = messageKey(project.id, '', mainThread);
  const hasSeed = project.id === 'museum' && mainThread === '01';
  const threadTitle = mainThreads(project.id).find((t) => t.id === mainThread)?.title || '메인 채팅';
  return `<div class="app-shell workspace">${sidebar(project, mainThread)}
    <main class="workspace-main" id="main" tabindex="-1" data-figma-node="${expert ? '56:74' : '1:4'}">
      <header class="workspace-header"><div class="breadcrumb"><a href="#/">${escape(project.name)}</a><span>/</span><span>${escape(threadTitle)}</span></div>
        <div class="workspace-controls"><span class="demo-label">UI 목업</span><button class="mobile-experts" data-action="toggle-experts">${showExperts ? '채팅' : '전문가'}</button></div></header>
      <div class="chat-layout ${expert ? 'split' : ''} ${showExperts && !expert ? 'show-experts' : ''}">
        <section class="chat-main" aria-label="메인 채팅">
          <div class="chat-scroll"><h1>${escape(project.phase)}</h1>
          ${hasSeed ? `<article class="message-user seed-user" aria-label="내 메시지">중앙 보이드를 중심으로 관람 동선을<br>구성하고 싶습니다.</article>
            <article class="seed-assistant"><h2 class="speaker">Sida</h2><div class="assistant-copy"><p>현재 설명된 동선의 공간적 작동을 검토했습니다.</p><p>분석의 근거와 불확실성은 상세 문서에서 확인할 수 있습니다.</p></div>
            <button class="analysis-card" data-action="open-expert" data-expert="41" data-thread="01"><h2>공간 검토 01</h2><p class="analysis-meta">공간 검토자 · 검토 필요</p><p>동선 연결 / 보이드 주변 경계 / 검증할 도면</p><span class="analysis-link">분석 보기 ↗</span></button></article>`
            : `<article class="seed-assistant"><h2 class="speaker">Sida</h2><p class="assistant-copy">${project.description ? escape(project.description) : '설계 중인 프로젝트와 지금 고민하는 점을 알려 주세요.'}</p><p class="muted">테스트 목업에서는 샘플 응답으로 대화를 체험할 수 있습니다.</p></article>`}
            ${messageList(key)}
          </div>${composer(key, 'Sida에게 설계에 관해 질문하세요...')}
        </section>
        <div class="divider" role="separator" aria-label="패널 너비 조절" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow="50" tabindex="0">⋮</div>
        ${expert ? expertChatView(view) : expertsView(project)}
      </div>
    </main></div>`;
}

function render(focus = true) {
  currentRoute = route();
  app.innerHTML = currentRoute.page === 'home' ? homeView() : currentRoute.page === 'new' ? newView() : workspaceView(currentRoute);
  document.title = `Sida · ${currentRoute.project?.name || (currentRoute.page === 'new' ? '새 프로젝트' : '프로젝트')}`;
  if (focus) document.querySelector('#main').focus({ preventScroll: true });
  save();
}

function openExpert(expert, thread) {
  const view = currentRoute;
  showExperts = false;
  location.hash = expertUrl(view.project.id, expert, thread, view.mainThread);
}

app.addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;
  if (action === 'delete-project') {
    const project = state.projects.find((p) => p.id === button.dataset.project);
    if (!project) return;
    pendingDeleteId = project.id;
    deleteDialog.querySelector('#delete-project-description').textContent = `“${project.name}” 프로젝트를 삭제합니다.`;
    deleteDialog.returnValue = '';
    deleteDialog.showModal();
  }
  if (action === 'settings') dialog.showModal();
  if (action === 'toggle-experts') {
    if (currentRoute.expert) location.hash = projectUrl(currentRoute.project.id, currentRoute.mainThread);
    else { showExperts = !showExperts; render(false); }
  }
  if (action === 'open-expert') openExpert(button.dataset.expert, button.dataset.thread);
  if (action === 'new-expert') {
    const thread = addThread(state, currentRoute.project.id, button.dataset.expert);
    save();
    openExpert(button.dataset.expert, thread.id);
  }
  if (action === 'new-main') {
    const threads = mainThreads(currentRoute.project.id);
    const id = String(Math.max(...threads.map((t) => Number(t.id))) + 1).padStart(2, '0');
    threads.push({ id, title: `새 채팅 ${id}` });
    save();
    location.hash = projectUrl(currentRoute.project.id, id);
  }
  if (action === 'attach') button.closest('form').querySelector('.file-input').click();
  if (action === 'remove-file') {
    const draft = draftFor(button.dataset.key);
    draft.files.splice(Number(button.dataset.index), 1);
    const form = button.closest('form');
    form.querySelector('.attachment-list').innerHTML = attachmentChips(draft.files, true, button.dataset.key);
  }
});

app.addEventListener('input', (event) => {
  if (event.target.id === 'project-name') event.target.setCustomValidity('');
  if (event.target.id === 'project-search') {
    query = event.target.value;
    document.querySelector('#project-grid').innerHTML = projectCards();
  }
  if (event.target.matches('.composer textarea')) {
    draftFor(event.target.closest('form').dataset.messageKey).text = event.target.value;
  }
});

app.addEventListener('change', (event) => {
  if (event.target.id === 'project-sort') {
    sort = event.target.value;
    document.querySelector('#project-grid').innerHTML = projectCards();
  }
  if (event.target.matches('.file-input')) {
    const form = event.target.closest('form');
    const key = form.dataset.messageKey;
    const draft = draftFor(key);
    draft.files = [...new Set([...draft.files, ...Array.from(event.target.files, (f) => f.name)])].slice(0, 10);
    form.querySelector('.attachment-list').innerHTML = attachmentChips(draft.files, true, key);
    event.target.value = '';
    announce('파일 이름을 첨부했습니다. 테스트 목업에서는 파일 내용을 업로드하지 않습니다.');
  }
});

app.addEventListener('submit', (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.id === 'new-project-form') {
    const name = form.elements.name;
    name.setCustomValidity('');
    if (!name.value.trim()) { name.setCustomValidity('프로젝트 이름을 입력해 주세요.'); name.reportValidity(); return; }
    const project = addProject(state, name.value, form.elements.description.value);
    save();
    location.hash = projectUrl(project.id);
    announce(`${project.name} 프로젝트를 만들었습니다.`);
  } else if (form.matches('.composer')) {
    const key = form.dataset.messageKey;
    const draft = draftFor(key);
    if (!sendMessage(state, key, draft.text, draft.files)) return;
    drafts.delete(key);
    const project = currentRoute.project;
    project.updated = Date.now();
    project.date = '방금 수정';
    save();
    render(false);
    const activeForm = Array.from(app.querySelectorAll('.composer')).find((f) => f.dataset.messageKey === key);
    const scroller = activeForm.previousElementSibling;
    scroller.scrollTop = scroller.scrollHeight;
    activeForm.querySelector('textarea').focus({ preventScroll: true });
    announce('메시지를 보냈습니다. 샘플 응답이 도착했습니다.');
  }
});

function resizePanel(separator, delta, absolute = false) {
  const layout = separator.parentElement;
  const bounds = layout.getBoundingClientRect();
  const current = layout.querySelector('.chat-main').getBoundingClientRect().width;
  const width = Math.max(bounds.width * .25, Math.min(bounds.width * .75, absolute ? delta : current + delta));
  if (layout.classList.contains('split')) layout.style.setProperty('--split-left', `${width}px`);
  else layout.style.setProperty('--expert-width', `${Math.max(240, bounds.width - width - 12)}px`);
  separator.setAttribute('aria-valuenow', String(Math.round(width / bounds.width * 100)));
}

app.addEventListener('keydown', (event) => {
  if (event.target.matches('.composer textarea') && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); event.target.closest('form').requestSubmit();
  }
  if (event.target.matches('#project-name')) event.target.setCustomValidity('');
  if (event.target.matches('.divider') && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault(); resizePanel(event.target, event.key === 'ArrowLeft' ? -24 : 24);
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

deleteDialog.addEventListener('close', () => {
  const id = pendingDeleteId;
  pendingDeleteId = null;
  if (deleteDialog.returnValue !== 'delete' || !id) return;
  const name = state.projects.find((p) => p.id === id)?.name;
  if (!deleteProject(state, id)) return;
  for (const key of drafts.keys()) {
    if (key.startsWith(`${id}:`)) drafts.delete(key);
  }
  save();
  if (currentRoute.project?.id === id) location.hash = '#/';
  else render();
  announce(`${name} 프로젝트와 대화를 삭제했습니다.`);
});

window.addEventListener('hashchange', () => { showExperts = false; render(); });
window.addEventListener('storage', (event) => {
  if (event.key !== STORAGE_KEY || event.newValue === null) return;
  state = restoreState(event.newValue);
  for (const key of drafts.keys()) {
    if (!state.projects.some((project) => key.startsWith(`${project.id}:`))) drafts.delete(key);
  }
  if (currentRoute.project && !state.projects.some((project) => project.id === currentRoute.project.id)) {
    location.hash = '#/';
  } else render(false);
});
document.querySelector('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  document.querySelector('#main').focus();
});
render(false);
