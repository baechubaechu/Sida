// The Sida screen. Draws from the JSON API and keeps no project data in the browser:
// projects, the Conductor conversation, expert chats and results all live on this PC's server.
import {
  phaseLabel, visibleExperts, STATUS_LABELS, PROVIDER_LABELS, MODE_LABELS, STATE_UPDATE_LABELS,
  escapeHtml as escape, findProjects, relativeDate, projectSummary, chatItems, eventNotice,
  expertStatus, renderMarkdown, chatTitle, latestChat, chatLabel, DATA_KEYS, keyChanges,
  parseRoute, projectPath as projectUrl, expertPath, dateTime, arrangeDocument, itemTag, renderInline,
  questionAnswer, stateChangeView, sitePath, sitePageFor, needsSiteFirst, siteHeadline, areaText, zoneScope, missingText, SITE_PART_LABELS,
  UNKNOWN, restrictionGroups, buildingLine, chosenDong, lotQuery, lookupBody, briefSite,
  ordinanceFigure, ordinanceApplies, ordinanceSends, useResult, useError, useDefinitions,
  togglePicked, shapesToFetch, MAP_PICK_ZOOM, EXPORT_FORMATS, boardExport, keepNewDraft,
} from './model.js';
import {
  keepSelected, pickedNames, massIds, canCompare, COMPARE_QUESTION, addQuestion,
  ideaText, moveIdea, dropIdea, sameOrder, ideaPapers, linkPapers, pickedNotes, ideasInPlay, MAX_IDEA_TEXT, MAX_IDEA_PAPERS,
} from './board-model.js';
import {
  COMMANDS, GROUP_LABELS, readLine, suggest, pickOption, addHistory, remember, HISTORY_LINES,
} from './command-model.js';
import { talkPanel, talkMenu, initialTalk, panelShown, panelWidths, resizePanel } from './talk-panel-model.js';
import { VWorldView } from './vworld-view.js';

const app = document.querySelector('#app');
const announcer = document.querySelector('#announcer');
const toasts = document.querySelector('#toasts');
const settingsDialog = document.querySelector('#settings-dialog');
const settingsBody = document.querySelector('#settings-body');
const settingsForm = document.querySelector('#settings-form');
const tableHost = document.querySelector('#table-host');
let vworldView = null; // the board's masses on VWorld's 3D map, over the board area (vworld-view.js)
const vworldAuto = new Set(); // projects whose site buildings were looked for this session
const deleteDialog = document.querySelector('#delete-dialog');
const deleteError = document.querySelector('#delete-error');
const deleteConfirm = document.querySelector('#delete-confirm');
const projectInfoDialog = document.querySelector('#project-info-dialog');
const projectInfoBody = document.querySelector('#project-info-body');
let projectInfoEdit = null;
const deleteTalkDialog = document.querySelector('#delete-talk-dialog');
const deleteTalkConfirm = document.querySelector('#delete-talk-confirm');

const POLL_MS = 1000;
const MAIN_JOBS = new Set(['opening', 'message', 'expert']);
const SITE_EXPERTS = new Set(['site_reader', 'regulation_checker']); // they read the saved site facts
const REGION_LEVELS = ['sido', 'sigungu', 'emd', 'ri'];
const REGION_LABELS = { sido: '시·도', sigungu: '시·군·구', emd: '읍·면·동', ri: '리' };

const ui = {
  projects: null, projectsError: '', query: '', sort: 'recent',
  project: '', session: null, sessionError: '',
  chat: null, chatMissing: false, module: null, moduleMissing: false, openExperts: new Set(),
  versions: null, version: null, versionMissing: false, showRaw: false, checks: new Set(), feedback: {},
  job: null, live: [], pending: null,
  revisionOpen: false, creating: false, newDraft: {}, vworld: false,
  // The workspace: the drafting table, and beside it the experts, the site page or an expert's
  // page. Conductor conversations open in a collapsible left panel.
  expertsCollapsed: false, conductor: { open: true, active: null, list: false },
  // The right panel shows the experts or the idea board (2026-11-05 지훈: a tab beside the experts).
  sideTab: 'experts', ideaEdit: '', ideaConfirm: '', ideaBusy: false, ideaDrag: '', ideaLinkNew: true,
  pane: 'board', focusComposer: false, creatingTalk: false, talkMenu: '',
  panelRatios: { left: .27, right: .21, detail: .38 },
  settings: null, settingsDraft: null, settingsError: '', chatgptModels: null, chatgptNote: '',
  board: null, selected: [], 
  site: null, siteError: '', showSiteLines: false, find: null, siteFirst: false,
  ordinance: null, ordinanceError: '', ordinanceBusy: '', useFind: null, mapLayers: null, mapError: '', mapErrorStatus: 0,
  // Loaded conversations and their next-question contexts; closing the panel keeps both.
  talks: new Map(), talkViews: [],
  // The command line: history lines, typed lines for ↑↓, a command's open question, the last
  // command (an empty Enter repeats it), the highlighted suggestion and the help card.
  cmd: { lines: [], typed: [], back: -1, prompt: null, last: '', pick: 0, help: false },
};
const drafts = new Map();
const conductorScrolls = new Map();
const openingTried = new Set();
let currentRoute = { page: 'home' };
let trackToken = 0; // only the newest polling loop keeps going
let trackingId = null;
let table = null; // the drafting table of the open project (table.js, loaded on first use)
let tableFor = '';
let siteMap = null; // the map on the site page's "찾기" tab (site-map.js, loaded on first use)
let siteMapLoading = false;
let panelResize = null;
let resizeRenderPending = false;

// ------------------------------------------------------------------ helpers

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = 'GET', body, form } = {}) {
  const options = { method, headers: {} };
  if (form !== undefined) {
    options.body = form; // FormData: the browser sets the multipart Content-Type
  } else if (body !== undefined) {
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
const expertUrl = (name, agent, chat = '') => (chat ? expertPath(name, agent, 'chat', chat) : expertPath(name, agent));
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

// The expert chat on screen: the one in the address, or the expert's newest chat.
function activeChat() {
  return currentRoute.chat || latestChat(expertById(currentRoute.agent));
}

function jobRunning() {
  return Boolean(ui.job && ui.job.status === 'running');
}

// ------------------------------------------------------------------ routing and loading

function route() {
  return parseRoute(location.hash);
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
    const session = await api(`${projectApi(name)}/session`);
    if (ui.project !== name) return;
    ui.session = session;
    ui.sessionError = '';
    if (ui.conductor.active === null) {
      const id = initialTalk(session.talks || [], null);
      ui.conductor = { ...ui.conductor, active: id };
      if (id) {
        ui.talkViews.push({ id, context: [] });
        await loadTalk(name, id);
      }
    }
  } catch (error) {
    ui.session = null;
    ui.sessionError = error.status === 404 ? '프로젝트를 찾을 수 없습니다.' : error.message;
  }
}

// The site page's "find" tab: step-by-step region lists, a typed 지번 or address, the parcels found
// and the ones picked to look up. Nothing here is saved until the designer saves the site.
function freshFind() {
  return {
    mode: 'steps', lists: { sido: null, sigungu: null, emd: null, ri: null }, loading: '',
    chosen: { sido: null, sigungu: null, emd: null, ri: null }, main: '', sub: '', mountain: false,
    query: '', briefTried: false, search: null, candidates: null, picked: [], busy: '', error: '', errorStatus: 0,
    shapes: new Map(), mapBusy: false, // pnu → boundary (null once asked and none came)
  };
}

function freshUseFind() {
  return { query: '', candidates: null, busy: '', error: '', errorStatus: 0 };
}

// What the site's ordinance says about 건폐율·용적률 (GET .../site/ordinance), loaded with the tab.
async function loadOrdinance(name) {
  ui.ordinanceError = '';
  try {
    const ordinance = await api(`${projectApi(name)}/site/ordinance`);
    if (ui.project === name) ui.ordinance = ordinance;
  } catch (error) {
    if (ui.project === name) ui.ordinanceError = error.message;
  }
  render(false);
}

async function loadSite(name) {
  try {
    ui.site = await api(`${projectApi(name)}/site`);
    ui.siteError = '';
  } catch (error) {
    ui.site = null;
    ui.siteError = error.message;
  }
}

function clearExpert() {
  ui.chat = null;
  ui.chatMissing = false;
  ui.module = null;
  ui.moduleMissing = false;
  ui.versions = null;
  ui.version = null;
  ui.versionMissing = false;
}

// What the expert page's open tab needs: the result, the list of earlier results, and the
// open analysis chat or earlier result.
async function loadExpert(name, agent) {
  clearExpert();
  const expert = expertById(agent);
  const { tab, version } = currentRoute;
  const base = `${projectApi(name)}/modules/${encodeURIComponent(agent)}`;
  const skip = Promise.resolve(null);
  const [chat, module, versions, old] = await Promise.allSettled([
    tab === 'chat' && expert?.chat
      ? api(`${projectApi(name)}/experts/${encodeURIComponent(agent)}/chats/${encodeURIComponent(activeChat())}`) : skip,
    expert?.done ? api(base) : Promise.reject(new ApiError(404, '')),
    api(`${base}/versions`),
    tab === 'versions' && version ? api(`${base}/versions/${encodeURIComponent(version)}`) : skip,
  ]);
  if (chat.status === 'fulfilled') ui.chat = chat.value;
  else ui.chatMissing = chat.reason?.status === 404;
  if (module.status === 'fulfilled') ui.module = module.value;
  else ui.moduleMissing = module.reason?.status === 404;
  ui.versions = versions.status === 'fulfilled' ? versions.value.versions : [];
  if (old.status === 'fulfilled') ui.version = old.value;
  else ui.versionMissing = old.reason?.status === 404;
}

async function refreshProject() {
  const { name, agent } = currentRoute;
  if (currentRoute.page !== 'project') return;
  await Promise.all([loadSession(name), loadBoard(name), ...ui.talkViews.map((p) => loadTalk(name, p.id))]);
  if (agent && ui.session) await loadExpert(name, agent);
}

// ------------------------------------------------------------------ the drafting table

async function loadBoard(name) {
  try {
    const board = await api(`${projectApi(name)}/board`);
    if (ui.project !== name) return;
    ui.board = board;
    ui.selected = keepSelected(ui.selected, board);
    table?.setBoard(board);
    table?.setSelected(ui.selected);
  } catch (error) {
    if (error.status !== 404) toast(`제도판을 불러오지 못했습니다. ${error.message}`, 'error');
  }
}

// A table edit through the API; on failure say why and redraw the table from the server.
async function boardCall(name, call, reload = false) {
  try {
    const result = await call();
    if (reload) await loadBoard(name);
    return result || true;
  } catch (error) {
    toast(error.message, 'error');
    await loadBoard(name);
    return null;
  }
}

function tableHooks(name) {
  const paperUrl = (id) => `${projectApi(name)}/board/papers/${encodeURIComponent(id)}`;
  return {
    add: (paper) => boardCall(name, () => api(`${projectApi(name)}/board/papers`, { method: 'POST', body: paper }), true),
    update: (id, changes) => boardCall(name, () => api(paperUrl(id), { method: 'PATCH', body: changes }),
      ['blocks', 'floor_height', 'title', 'text'].some((key) => key in changes)),
    remove: (id) => boardCall(name, () => api(paperUrl(id), { method: 'DELETE' })),
    // A photo goes up as a file (multipart); fields: title, x, y, w, h.
    addPhoto: (blob, fileName, fields) => boardCall(name, () => {
      const form = new FormData();
      form.append('file', blob, fileName);
      for (const [key, value] of Object.entries(fields)) if (value !== undefined && value !== null && value !== '') form.append(key, String(value));
      return api(`${projectApi(name)}/board/photos`, { method: 'POST', form });
    }, true),
    photoUrl: (id) => `${projectApi(name)}/board/photos/${encodeURIComponent(id)}`,
    // The site's surroundings in 3D (ground, nearby buildings): GET .../site/context.
    context: (radius) => api(`${projectApi(name)}/site/context?radius=${encodeURIComponent(radius)}`),
    place: (id, placement) => boardCall(name, () => api(`${projectApi(name)}/board/tray/${encodeURIComponent(id)}/place`, { method: 'POST', body: placement }), true),
    discard: (id) => boardCall(name, () => api(`${projectApi(name)}/board/tray/${encodeURIComponent(id)}`, { method: 'DELETE' }), true),
    select: (ids) => { ui.selected = ids; render(false); },
    ask: () => askAbout(),
    openExpert: (agent) => { location.hash = expertUrl(name, agent); },
    experts: () => ui.session?.experts || [],
  };
}

// The table of this project, made once (three.js is loaded only when a project opens).
async function openTable(name) {
  if (tableFor === name && table) return;
  table?.destroy();
  table = null;
  tableFor = name;
  try {
    const { DraftingTable } = await import('./table.js');
    if (tableFor !== name) return;
    table = new DraftingTable(tableHooks(name));
    tableHost.replaceChildren(table.root);
    if (ui.board) { table.setBoard(ui.board); table.setSelected(ui.selected); }
    placeTable();
  } catch (error) {
    tableHost.replaceChildren();
    toast(`제도판을 열지 못했습니다. ${error.message}`, 'error');
  }
}

// The table lives outside the redrawn page (so WebGL, a drag or a note being typed survive
// redraws) and is laid over the page's #table-slot.
const slotWatch = new ResizeObserver(() => placeTable());

function placeTable() {
  const slot = app.querySelector('#table-slot');
  const r = slot?.getBoundingClientRect();
  if (!table || !r || !r.width || !r.height) { tableHost.hidden = true; return; }
  tableHost.hidden = false;
  Object.assign(tableHost.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  table.resize();
  if (vworldView?.open) vworldView.place(r);
}

// The "브이월드 3D" view (command vworld): the active scheme's masses on VWorld's live 3D map over
// the board area; leaving it shows the board again. Needs a looked-up site (its middle and frame).
async function toggleVWorld(name, on = !ui.vworld) {
  if (!on) {
    ui.vworld = false;
    vworldView?.hide();
    render(false);
    return;
  }
  const plan = table?.site?.plan || ui.board?.site?.plan;
  if (!plan?.origin) { toast('먼저 대지를 조회하세요. 대지 경계가 있어야 브이월드 3D 지도에 매스안을 세울 수 있습니다.', 'info'); return; }
  try {
    if (!ui.mapLayers) ui.mapLayers = await api('/api/site/map');
  } catch (error) {
    toast(`브이월드 3D 지도를 열 수 없습니다. ${error.message}`, 'error');
    return;
  }
  if (!vworldView) {
    vworldView = new VWorldView({
      saveHidden: async (ids) => {
        const saved = await api(`${projectApi(currentRoute.name)}/board/hidden`, { method: 'PUT', body: { ids } });
        if (ui.board) ui.board.hidden = saved.hidden;
      },
      close: () => toggleVWorld(currentRoute.name, false),
    });
  }
  ui.vworld = true;
  render(false);
  placeTable();
  const masses = (table?.papers || ui.board?.papers || []).filter((p) => p.kind === 'mass');
  const paper = masses.find((p) => p.id === table?.active) || masses[0] || null;
  const hidden = ui.board?.hidden || [];
  const firstTime = !hidden.length && !vworldAuto.has(name);
  vworldAuto.add(name);
  await vworldView.show({ script: ui.mapLayers.webgl3d.script, plan, paper, hidden, firstTime });
}

// Ask about what is picked: the cursor goes to the command line, and a prepared question goes
// under what is already typed. Nothing is sent yet; Enter opens a talk with the picked papers.
function askAbout(question = '') {
  if (currentRoute.page !== 'project') return;
  if (question) drafts.set('command', addQuestion(draftFor('command'), question));
  ui.focusComposer = true;
  render(false);
}

function unpick(id) {
  ui.selected = ui.selected.filter((x) => x !== id);
  table?.setSelected(ui.selected);
  render(false);
}

async function navigate() {
  const previous = currentRoute;
  currentRoute = route();
  if (currentRoute.agent || currentRoute.site) ui.pane = 'side';
  else if (previous.agent || previous.site) ui.pane = 'board';
  ui.revisionOpen = false;
  if (!currentRoute.site) ui.siteFirst = false; // left the site page without saving a site
  if (currentRoute.page !== 'project' || previous.name !== currentRoute.name || currentRoute.site) {
    if (ui.vworld) { ui.vworld = false; vworldView?.hide(); }
  }
  if (currentRoute.page !== 'project') {
    table?.destroy();
    table = null;
    tableFor = '';
  }
  if (currentRoute.page === 'home') {
    render();
    await loadProjects();
  } else if (currentRoute.page === 'project') {
    const { name, agent } = currentRoute;
    if (previous.page !== 'project' || previous.name !== name) {
      ui.session = null;
      ui.site = null;
      ui.find = freshFind();
      ui.ordinance = null;
      ui.ordinanceError = '';
      ui.useFind = freshUseFind();
      ui.chat = null;
      ui.job = null;
      trackToken += 1;
      trackingId = null;
      ui.live = [];
      ui.pending = null;
      ui.project = name;
      ui.board = null;
      ui.selected = [];
      ui.talks = new Map();
      ui.talkViews = [];
      ui.talkMenu = '';
      ui.conductor = { ...ui.conductor, active: null, list: false };
      conductorScrolls.clear();
      for (const key of drafts.keys()) if (key.startsWith('talk:') || key === 'conductor-new') drafts.delete(key);
      ui.cmd = { lines: [], typed: [], back: -1, prompt: null, last: '', pick: 0, help: false };
      drafts.delete('command');
      render();
      if (!ui.projects) loadProjects().then(() => render(false));
      openTable(name);
      await Promise.all([loadSession(name), loadBoard(name), loadSite(name)]);
    }
    if (currentRoute.site && currentRoute.tab === 'find') prepareFind(name);
    if (currentRoute.site && currentRoute.tab === 'ordinance' && !ui.ordinance && ui.site?.available) loadOrdinance(name);
    if (agent && ui.session) {
      if (agent !== previous.agent) ui.showRaw = false;
      clearExpert();
      render();
      await loadExpert(name, agent);
    }
    if (currentRoute.name !== name) return;
    render();
    if (!ui.session) return;
    if (ui.session.job) {
      if (ui.session.job.talk) openTalk(name, ui.session.job.talk);
      track(name, ui.session.job);
    }
    else if (ui.session.talks?.some(t => t.id === '01') && !ui.session.messages.length && !openingTried.has(name)) {
      openingTried.add(name);
      openTalk(name, '01');
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
  if (event.kind === 'tray_added' && ui.project) {
    loadBoard(ui.project).then(() => table?.openTray());
  }
  const sitePage = ui.project ? sitePageFor(event, ui.project, ui.site) : null;
  if (sitePage && location.hash !== sitePage) location.hash = sitePage;
  if (event.kind === 'run_skipped' && event.data?.reason === 'no_site' && ui.project) askForSite(ui.project, event.data.address);
  if (event.kind === 'conductor_reply') ui.live.push({ kind: 'conductor', text: event.data.text || '' });
  else if (event.kind === 'expert_reply') ui.live.push({ kind: 'expert', text: event.data.text || '' });
  else {
    const notice = eventNotice(event);
    if (!notice) return;
    // A talk shows its own progress; an expert run started from the command line reports
    // on the command line.
    if (ui.job?.kind === 'expert') ui.cmd.lines = addHistory(ui.cmd.lines, notice.text, notice.tone);
    else ui.live.push({ kind: 'note', text: notice.text, tone: notice.tone });
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

const projectLabel = (p) => p.display_name || p.name;
const currentProjectLabel = (name) => projectLabel(ui.projects?.find(p => p.name === name) || { name });

// A project link in the sidebar, with its delete button beside it.
function navProject(p) {
  return `<div class="nav-row"><a class="nav-link" href="${projectUrl(p.name)}">${escape(projectLabel(p))}</a>
    <button type="button" class="nav-delete" data-action="delete-project" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 삭제" title="프로젝트 삭제">삭제</button></div>`;
}

// The project list's sidebar. Inside a project the Conductor panel links back here instead.
function sidebar() {
  const projects = ui.projects ? findProjects(ui.projects) : [];
  const warned = ui.settings && Object.values(ui.settings.warnings || {}).some(Boolean);
  return `<aside class="sidebar" aria-label="프로젝트 탐색">
    <a class="brand" href="#/" aria-label="Sida 프로젝트 홈">Sida</a>
    <nav class="nav-main" aria-label="주 메뉴">
      <a class="nav-link active" href="#/" aria-current="page">▦&nbsp; 프로젝트</a>
      <a class="nav-link nav-new" href="#/new">＋&nbsp; 새 프로젝트</a>
    </nav>
    <section class="recent"><h2 class="nav-label">최근 항목</h2>
      ${projects.slice(0, 3).map((p) => navProject(p)).join('')}</section>
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
  return projects.map((p) => `<article class="project-card"><a class="project-open" href="${projectUrl(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 열기">
    <h3>${escape(projectLabel(p))}</h3>
    <p class="project-type">${escape(p.project_type || '건축 설계')}</p>
    <p class="project-summary">${escape(projectSummary(p))}</p>
    <div class="project-footer"><span>${escape(relativeDate(p.updated_at))}</span><span aria-hidden="true">↗</span></div>
  </a><div class="project-card-actions"><button type="button" data-action="project-info" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 정보 수정">정보 수정</button>
    <button type="button" class="card-delete" data-action="delete-project" data-project="${escape(p.name)}" aria-label="${escape(projectLabel(p))} 프로젝트 삭제" title="프로젝트 삭제">삭제</button></div></article>`).join('');
}

function homeView() {
  return `<div class="app-shell">${sidebar()}
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

// Papers picked on the drafting table go with the next message (and the next expert run).
// A chip's name opens the paper at reading size; × takes it out.
function pickedChips() {
  const withTable = tableShown();
  if (!ui.selected.length) {
    return withTable ? '<div class="picked" aria-label="질문에 함께 보낼 자료"><span class="picked-hint">제도판에서 종이를 고르면 이 질문에 자료로 붙습니다</span></div>' : '';
  }
  return `<div class="picked" aria-label="질문에 함께 보낼 자료"><span class="picked-label">함께 보낼 자료 ${ui.selected.length}개</span>
    <div class="picked-chips">${pickedNames(ui.selected, ui.board).map((p) => `<span class="attachment">${withTable
    ? `<button type="button" class="attachment-title" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)}</button>`
    : `<span class="attachment-title">${escape(p.name)}</span>`}<button type="button" class="attachment-remove" data-action="unpick" data-id="${escape(p.id)}" aria-label="${escape(p.name)} 질문 자료에서 빼기">×</button></span>`).join('')}</div></div>`;
}

// The table is always in the workspace of a project, next to what is open on the right.
function tableShown() {
  return currentRoute.page === 'project';
}

function contextChips(context) {
  if (!context?.length) return '';
  return `<div class="context-chips" aria-label="함께 보낸 제도판 종이">${context.map((c) => `<span class="paper-chip">${escape(c.name || c.id)}</span>`).join('')}</div>`;
}

function composer(key, placeholder, label, disabled) {
  return `<form class="composer" data-composer="${escape(key)}" aria-label="${escape(label)} 입력">
    ${pickedChips()}
    <textarea data-focus="${escape(key)}" aria-label="${escape(label)}에게 메시지" placeholder="${escape(placeholder)}" maxlength="6000" rows="1">${escape(draftFor(key))}</textarea>
    <div class="composer-footer"><span class="composer-hint">${disabled ? '작업이 끝나면 보낼 수 있습니다.' : 'Enter로 보내기 · Shift+Enter로 줄 바꿈'}</span>
      <button class="send-button" type="submit" aria-label="${escape(label)}에게 보내기" ${disabled ? 'disabled' : ''}>↑</button></div>
  </form>`;
}

// A saved message can go onto the idea board (all of it, or the part selected in it).
function ideaButton(source) {
  if (!source || currentRoute.page !== 'project') return '';
  return `<button type="button" class="to-idea" data-action="idea-from-message" ${source.talk ? `data-talk="${escape(source.talk)}"` : ''} title="이 메시지(또는 드래그로 고른 부분)를 아이디어 보드에 넣기">＋ 아이디어로</button>`;
}

function bubble(item, speaker, source = null) {
  if (item.kind === 'user') return `${contextChips(item.context)}<article class="message-user" aria-label="내 메시지">${escape(item.text)}${source && item.text ? ideaButton(source) : ''}</article>`;
  if (item.kind === 'note') return `<p class="event-note ${item.tone || ''}">${escape(item.text)}</p>`;
  if (item.kind === 'card') {
    const expert = expertById(item.agent);
    const status = expert ? STATUS_LABELS[expertStatus(expert, ui.job)] : '';
    return `<button class="analysis-card" data-action="open-expert" data-agent="${escape(item.agent)}">
      <h2>${escape(item.name)} 결과</h2>
      <p class="analysis-meta">${escape(item.name)}${status ? ` · ${escape(status)}` : ''}</p>
      <span class="analysis-link">분석 보기 ↗</span></button>`;
  }
  const [who, role] = Array.isArray(speaker) ? speaker : [speaker, ''];
  return `<article><h3 class="speaker">${escape(who)}${role ? ` <span>${escape(role)}</span>` : ''}</h3><div class="assistant-copy markdown">${renderMarkdown(item.text)}</div>${source && item.text ? ideaButton(source) : ''}</article>`;
}

function workingLine(forMain) {
  if (!jobRunning()) return '';
  const job = ui.job;
  if (forMain !== MAIN_JOBS.has(job.kind)) return '';
  const running = job.running_agent ? expertById(job.running_agent) : null;
  const text = running ? `${running.name} 실행 중입니다…` : forMain ? 'Conductor가 답을 쓰는 중입니다…' : '전문가가 답을 쓰는 중입니다…';
  return `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>${escape(text)}</p>`;
}

// ------------------------------------------------------------------ talks and the command line
// The same saved talks back the left panel and questions entered on the command line.

function talkTitle(talk) {
  if (talk?.title) return talk.title;
  return talk?.id === '01' ? '첫 대화' : '새 대화';
}

function talkSummary(id) {
  return ui.session?.talks?.find((t) => t.id === id) || { id, title: '', messages: 0, updated_at: '' };
}

// Saved conversations, newest first, inside the Conductor panel.
function talkActions(id) {
  return `<details class="talk-more" ${ui.talkMenu === id ? 'open' : ''}>
    <summary data-action="talk-menu" data-talk="${escape(id)}" data-focus="talk-menu-${escape(id)}" aria-label="${escape(talkTitle(talkSummary(id)))} 대화 메뉴" title="대화 메뉴">⋯</summary>
    <div class="talk-more-options"><button type="button" class="talk-delete" data-action="talk-delete" data-talk="${escape(id)}" ${jobRunning() ? 'disabled' : ''}>대화 삭제</button></div>
  </details>`;
}

function talksCard() {
  const session = ui.session;
  const talks = [...(session?.talks || [])].reverse();
  const body = !session
    ? `<p class="${ui.sessionError ? 'error-text' : 'muted'}">${escape(ui.sessionError || '대화를 불러오는 중입니다.')}</p>`
    : !talks.length ? '<p class="muted">저장된 대화가 없습니다. 새 대화를 시작해 보세요.</p>'
    : `<ul class="talk-list" aria-label="Conductor 대화 목록">${talks.map((t) => `<li>
        <button type="button" class="talk-row" data-action="talk-open" data-talk="${escape(t.id)}" aria-pressed="${ui.conductor.active === t.id}">
          <span class="talk-row-title">${escape(talkTitle(t))}</span>
          <span class="talk-row-meta">${t.messages ? `메시지 ${t.messages}개` : '아직 비어 있음'}${t.updated_at ? ` · ${escape(relativeDate(t.updated_at))}` : ''}${jobRunning() && ui.job.talk === t.id ? ' · 답하는 중' : ''}</span>
        </button>${talkActions(t.id)}</li>`).join('')}</ul>`;
  return `<section class="conductor-history" aria-label="대화 목록">
      <div class="talk-list-scroll" data-scroll="talks" data-scroll-from="top">${body}</div></section>`;
}

function conductorPanel() {
  const id = ui.conductor.active;
  const view = talkViewById(id);
  return `<aside class="conductor-panel panel" id="conductor-panel" aria-label="Conductor 대화" ${ui.conductor.open ? '' : 'hidden'}>
      <header class="pane-head"><div><span class="eyebrow">설계 대화</span><h2>Conductor</h2></div>
        <button type="button" class="ghost" data-action="conductor-close" aria-label="Conductor 대화 닫기" title="대화 패널 접기">‹</button></header>
      <div class="conductor-toolbar"><button type="button" data-action="talk-new">＋ 새 대화</button>
        <button type="button" data-action="talks-toggle" aria-expanded="${ui.conductor.list}">${ui.conductor.list ? '대화로 돌아가기' : '이전 대화'}</button></div>
      ${ui.sessionError ? `<p class="error-text conductor-error">${escape(ui.sessionError)}</p>` : ''}
      ${ui.conductor.list ? talksCard() : view ? talkConversation(view) : `<div class="conductor-welcome"><span class="conductor-mark" aria-hidden="true">S</span><h3>설계 이야기를 시작해 보세요</h3><p>아이디어를 나누거나 제도판에서 고른 자료를 함께 검토할 수 있습니다.</p></div>
        ${composer('conductor-new', 'Conductor에게 질문하세요…', 'Conductor', jobRunning() || ui.creatingTalk || !ui.session)}`}
    </aside>`;
}

function talkWorking(id) {
  if (!jobRunning() || ui.job.talk !== id) return '';
  const running = ui.job.running_agent ? expertById(ui.job.running_agent) : null;
  const text = running ? `${running.name} 실행 중입니다…` : 'Conductor가 답을 쓰는 중입니다…';
  return `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>${escape(text)}</p>`;
}

// The papers a view's next question carries: × takes one out, and what is picked on the table
// now can be added.
function talkContext(view) {
  const names = pickedNames(view.context, ui.board);
  const more = ui.selected.filter((id) => !view.context.includes(id));
  if (!names.length && !more.length) return '';
  return `<div class="talk-context" aria-label="이번 질문에 함께 보낼 자료">
      ${names.map((p) => `<span class="attachment"><button type="button" class="attachment-title" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)}</button><button type="button" class="attachment-remove" data-action="talk-unpick" data-talk="${escape(view.id)}" data-id="${escape(p.id)}" aria-label="${escape(p.name)} 빼기">×</button></span>`).join('')}
      ${more.length ? `<button type="button" class="talk-add-picked" data-action="talk-add-picked" data-talk="${escape(view.id)}">＋ 고른 종이 ${more.length}개 넣기</button>` : ''}
    </div>`;
}

function talkConversation(view) {
  const { id } = view;
  const loaded = ui.talks.get(id);
  const items = chatItems(loaded?.messages || []);
  const key = `talk:${id}`;
  const pending = ui.pending?.target === key ? [{ kind: 'user', text: ui.pending.text, context: ui.pending.context }] : [];
  const live = ui.job?.talk === id ? ui.live : [];
  const busy = jobRunning();
  const empty = !items.length && !pending.length && !live.length && !talkWorking(id);
  return `<section class="talk-conversation" data-talk="${escape(id)}" aria-label="대화: ${escape(talkTitle(talkSummary(id)))}">
      <header class="talk-head"><strong>${escape(talkTitle(talkSummary(id)))}</strong>${talkActions(id)}</header>
      <div class="talk-scroll" data-scroll="${escape(key)}">
        ${loaded?.error ? `<p class="error-text">${escape(loaded.error)}</p>` : ''}
        ${empty && !loaded?.error ? `<p class="muted">${loaded ? '아직 대화가 없습니다.' : '대화를 불러오는 중입니다.'}</p>` : ''}
        <div class="message-list" role="log" aria-label="대화 메시지">
          ${items.map((item) => bubble(item, ['Sida', 'Conductor'], { talk: id })).join('')}
          ${[...pending, ...live].map((item) => bubble(item, ['Sida', 'Conductor'])).join('')}
          ${talkWorking(id)}
        </div>
      </div>
      <form class="composer talk-composer" data-composer="${escape(key)}" aria-label="이 대화에 이어서 묻기">
        ${talkContext(view)}
        <textarea data-focus="${escape(key)}" aria-label="이 대화에 이어서 묻기" placeholder="이어서 묻기" maxlength="6000" rows="1">${escape(draftFor(key))}</textarea>
        <div class="composer-footer"><span class="composer-hint">${busy ? '작업이 끝나면 보낼 수 있습니다.' : 'Enter로 보내기 · Shift+Enter로 줄 바꿈'}</span>
          <button class="send-button" type="submit" aria-label="이 대화에 보내기" ${busy ? 'disabled' : ''}>↑</button></div>
      </form>
    </section>`;
}

// What Enter does with the line: while one word is typed, the highlighted suggestion runs.
function resolveLine(text) {
  const line = readLine(text);
  if (line.kind !== 'ask') return line;
  const offered = suggest(text);
  return offered.length ? readLine(offered[Math.min(ui.cmd.pick, offered.length - 1)].name) : line;
}

// What Enter will do with the line, shown before the input.
function commandMode(text) {
  if (ui.cmd.prompt) return { label: '답', tone: 'prompt' };
  const line = resolveLine(text);
  if (line.kind === 'command') return { label: line.command.name, tone: 'command' };
  if (line.kind === 'ask') return { label: 'AI에게', tone: 'ask' };
  return { label: '명령', tone: 'idle' };
}

function suggestionItems(text) {
  if (ui.cmd.prompt) return '';
  return suggest(text).map((c, i) => `<li role="option" id="cmd-opt-${i}" aria-selected="${i === ui.cmd.pick}" data-action="cmd-pick" data-command="${escape(c.name)}">
      <b>${escape(c.name)}</b>${c.aliases.length ? `<span class="cmd-alias">${escape(c.aliases.join(', '))}</span>` : ''}<span>${escape(c.label)}</span></li>`).join('');
}

function helpCard() {
  const groups = Object.keys(GROUP_LABELS).map((g) => `<div><h3>${escape(GROUP_LABELS[g])}</h3><dl>${COMMANDS.filter((c) => c.group === g)
    .map((c) => `<dt>${escape([c.name, ...c.aliases].join(' · '))}</dt><dd>${escape(c.label)}</dd>`).join('')}</dl></div>`).join('');
  return `<section class="command-help" aria-label="명령 목록"><header><strong>명령</strong>
      <button type="button" class="ghost" data-action="cmd-help" aria-label="명령 목록 닫기">×</button></header>
      <p class="muted">띄어쓰기 없는 영어 한 단어가 명령입니다. 그 밖의 글은 모두 Conductor에게 갑니다. Enter 실행 · Shift+Enter 줄 바꿈 · 빈 칸에서 Enter는 직전 명령 반복 · Esc 취소</p>
      <div class="command-help-groups">${groups}</div></section>`;
}

function commandBar() {
  const c = ui.cmd;
  const text = draftFor('command');
  const mode = commandMode(text);
  const items = suggestionItems(text);
  const picked = pickedNames(ui.selected, ui.board);
  const shown = panelShown(ui.conductor, ui.pane, matchMedia('(max-width: 900px)').matches);
  return `<section class="command-bar" aria-label="명령창">
      ${c.help ? helpCard() : ''}
      <div class="command-top"><ol class="command-history" aria-label="명령 기록">${c.lines.slice(-HISTORY_LINES).map((l) => `<li class="${escape(l.tone)}">${escape(l.text)}</li>`).join('')}
        ${ui.sessionError ? `<li class="error">${escape(ui.sessionError)} <a href="#/">← 프로젝트로 돌아가기</a></li>` : ''}
        ${c.prompt ? `<li class="command-question">${escape(c.prompt.text)} ${c.prompt.options.map((o, i) => `<button type="button" data-action="cmd-option" data-index="${i}">${i + 1} ${escape(o.label)}</button>`).join('')}</li>` : ''}</ol>
      </div>
      <form class="command-form" id="command-form">
        <button type="button" class="command-talks ${shown ? 'open' : ''}" data-action="conductor-toggle" aria-controls="conductor-panel" aria-expanded="${shown}" aria-label="Conductor 대화 ${shown ? '접기' : '열기'}">대화</button>
        <span class="command-mode ${mode.tone}" id="command-mode">${escape(mode.label)}</span>
        ${picked.length ? `<span class="command-picked" title="${escape(picked.map((p) => p.name).join(', '))}">자료 ${picked.length}개</span>` : ''}
        <textarea id="command-input" data-focus="command" rows="1" maxlength="6000" spellcheck="false" autocomplete="off"
          role="combobox" aria-expanded="${Boolean(items)}" aria-controls="command-suggest" aria-autocomplete="list" ${items ? `aria-activedescendant="cmd-opt-${c.pick}"` : ''}
          aria-label="명령 또는 질문" placeholder="${c.prompt ? '번호나 이름을 입력하세요 (Esc 취소)' : '명령(plan, zoom, help…) 또는 Conductor에게 질문'}">${escape(text)}</textarea>
        <button type="submit" class="command-run" aria-label="실행">↵</button>
      </form>
      <ul class="command-suggest" id="command-suggest" role="listbox" aria-label="명령 제안" ${items ? '' : 'hidden'}>${items}</ul>
    </section>`;
}

// The line's mode and suggestions change as it is typed, without redrawing the page.
function updateCommandLine() {
  const input = app.querySelector('#command-input');
  if (!input) return;
  const mode = commandMode(input.value);
  const label = app.querySelector('#command-mode');
  label.textContent = mode.label;
  label.className = `command-mode ${mode.tone}`;
  const items = suggestionItems(input.value);
  const list = app.querySelector('#command-suggest');
  list.innerHTML = items;
  list.hidden = !items;
  input.setAttribute('aria-expanded', String(Boolean(items)));
  if (items) input.setAttribute('aria-activedescendant', `cmd-opt-${ui.cmd.pick}`);
  else input.removeAttribute('aria-activedescendant');
}

function chatAnswering(agent, chat) {
  return jobRunning() && ui.job.kind === 'expert_chat' && ui.job.agent === agent && ui.job.chat === chat;
}

function siteRow(name) {
  const looked = Boolean(ui.site?.available);
  return `<a class="site-row" href="${sitePath(name)}">
      <span class="dot ${looked ? 'done' : 'idle'}" aria-hidden="true"></span>
      <span class="expert-text"><span class="expert-name">대지 사실</span>
      <span class="expert-phase">${escape(siteHeadline(ui.site) || '주소로 필지를 찾아 저장합니다')} · ${looked ? '조회함' : '조회 전'}</span></span>
      <span class="row-open" aria-hidden="true">↗</span></a>`;
}

// What the experts are doing now, under the list.
function runsBlock() {
  const job = ui.job;
  const running = jobRunning() && job.running_agent ? expertById(job.running_agent) : null;
  if (running) {
    return `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span><span><b>${escape(running.name)}</b> 실행 중입니다. 결과는 제도판의 AI 섹션에 놓입니다.</span></p>`;
  }
  return '<p class="runs-empty">전문가를 실행하면 결과가 제도판의 AI 섹션에 놓이고, 여기서 결과 문서와 분석 채팅을 엽니다.</p>';
}

function expertsPanel() {
  const experts = visibleExperts(ui.session?.experts);
  const busy = jobRunning();
  const picked = ui.selected.length;
  return `<aside id="experts-panel" class="experts panel" aria-label="전문가">
    ${sideTabs()}
    <header class="pane-head"><div><span class="eyebrow">함께 검토하기</span><h2>전문가 <span class="expert-count">${experts.length}</span></h2>
      <p>${picked ? `고른 종이 ${picked}장과 함께 실행` : '브리프와 제도판을 보고 실행'}</p></div>
      <button type="button" class="ghost" data-action="collapse-experts" aria-label="전문가 패널 접기" aria-controls="experts-panel" aria-expanded="true">›</button></header>
    <div class="experts-scroll">
    <h3 class="panel-label">대지</h3>${siteRow(currentRoute.name)}
    <h3 class="panel-label">전문가</h3>
    <ul class="expert-list">${experts.map((e) => {
    const status = expertStatus(e, ui.job);
    const id = escape(e.id);
    const threads = e.chat
      ? `<button class="thread-new" data-action="new-chat" data-agent="${id}">＋ 새 분석 채팅</button>
        ${(e.chats || []).map((c) => `<button data-action="open-chat" data-agent="${id}" data-chat="${escape(c.id)}">${escape(chatLabel(c))}${chatAnswering(e.id, c.id) ? ' · 답하는 중' : ''}</button>`).join('')}`
      : '<p class="muted small-text">채팅 없음. 결과 문서와 수정 요청만 있습니다.</p>';
    return `<li class="expert-item"><span class="dot ${status}" aria-hidden="true"></span>
      <details class="expert-row" data-agent="${id}" ${ui.openExperts.has(e.id) ? 'open' : ''}>
        <summary><span class="expert-name">${escape(e.name)}</span>
          <span class="expert-phase">${escape(phaseLabel(e))} · ${escape(STATUS_LABELS[status])}</span></summary>
        <div class="expert-threads"><button data-action="open-expert" data-agent="${id}">결과 문서 보기</button>${threads}</div></details>
      <button type="button" class="mini" data-action="run-expert" data-agent="${id}" ${busy ? 'disabled' : ''} title="${e.done ? '다시 실행' : '실행'}${picked ? ` (고른 종이 ${picked}장과 함께)` : ''}">${status === 'running' ? '실행 중' : e.done ? '다시' : '실행'}</button></li>`;
  }).join('')}</ul></div>
    <section class="runs" aria-label="검토 진행"><h3>검토 진행</h3>${runsBlock()}</section></aside>`;
}

// The two tabs on top of the right panel: the experts and the idea board.
function sideTabs() {
  const count = (ui.board?.ideas || []).length;
  const tab = (id, label) => `<button type="button" role="tab" data-action="side-tab" data-tab="${id}" aria-selected="${ui.sideTab === id}" aria-controls="experts-panel">${label}</button>`;
  return `<nav class="side-tabs" role="tablist" aria-label="오른쪽 칸">${tab('experts', '전문가')}${tab('ideas', `아이디어${count ? ` <span class="expert-count">${count}</span>` : ''}`)}</nav>`;
}

function ideaTalkChip(idea, editing) {
  if (!idea.talk) return '';
  const known = ui.session?.talks?.some((t) => t.id === idea.talk);
  const label = known ? `대화: ${talkTitle(talkSummary(idea.talk))}` : '지운 대화';
  return `<span class="attachment idea-talk">${known
    ? `<button type="button" class="attachment-title" data-action="talk-open" data-talk="${escape(idea.talk)}" title="이 대화 열기">${escape(label)}</button>`
    : `<span class="attachment-title">${escape(label)}</span>`}${editing ? `<button type="button" class="attachment-remove" data-action="idea-unlink-talk" data-idea="${escape(idea.id)}" aria-label="대화 연결 끊기">×</button>` : ''}</span>`;
}

function ideaItem(idea, index, total) {
  const id = escape(idea.id);
  const editing = ui.ideaEdit === idea.id;
  const busy = ui.ideaBusy;
  const papers = ideaPapers(idea, ui.board);
  const links = papers.map((p) => `<span class="attachment"><button type="button" class="attachment-title" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)}</button>${editing ? `<button type="button" class="attachment-remove" data-action="idea-unlink" data-idea="${id}" data-id="${escape(p.id)}" aria-label="${escape(p.name)} 연결 끊기">×</button>` : ''}</span>`).join('') + ideaTalkChip(idea, editing);
  const more = ui.selected.filter((x) => !(idea.papers || []).includes(x));
  const key = `idea-edit:${idea.id}`;
  const body = editing
    ? `<form class="idea-edit" data-idea-form="${id}">
        <textarea data-focus="${escape(key)}" data-idea-draft="${escape(key)}" aria-label="아이디어 ${index + 1} 고치기" maxlength="${MAX_IDEA_TEXT}" rows="3">${escape(draftFor(key))}</textarea>
        <div class="idea-edit-actions"><span class="composer-hint">Enter 저장 · Esc 취소</span>
          <button type="button" class="secondary small" data-action="idea-cancel">취소</button><button type="submit" class="primary small" ${busy ? 'disabled' : ''}>저장</button></div></form>`
    : `<p class="idea-text">${escape(idea.text)}</p>`;
  const confirm = ui.ideaConfirm === idea.id;
  return `<li class="idea ${idea.off ? 'is-off' : ''} ${ui.ideaDrag === idea.id ? 'is-dragging' : ''}" data-idea="${id}">
      <span class="idea-num" draggable="true" title="끌어서 순서 바꾸기" aria-hidden="true">${index + 1}</span>
      <div class="idea-body">
        ${idea.off ? '<span class="idea-off-badge">잠시 뺌 · AI에게 안 감</span>' : ''}
        ${body}
        ${links ? `<div class="idea-links" aria-label="연결된 자료">${links}</div>` : ''}
        <div class="idea-actions" aria-label="아이디어 ${index + 1} 편집">
          <button type="button" data-action="idea-move" data-idea="${id}" data-step="-1" aria-label="위로" title="위로" ${index === 0 || busy ? 'disabled' : ''}>↑</button>
          <button type="button" data-action="idea-move" data-idea="${id}" data-step="1" aria-label="아래로" title="아래로" ${index === total - 1 || busy ? 'disabled' : ''}>↓</button>
          ${editing ? '' : `<button type="button" data-action="idea-edit" data-idea="${id}">고치기</button>`}
          <button type="button" data-action="idea-off" data-idea="${id}" ${busy ? 'disabled' : ''} title="${idea.off ? 'AI가 다시 이 아이디어를 고려합니다' : '이 아이디어 없이 탐색해 보고 싶을 때: AI에게 보내지 않습니다'}">${idea.off ? '다시 넣기' : '잠시 빼기'}</button>
          ${more.length ? `<button type="button" data-action="idea-link" data-idea="${id}" ${busy || (idea.papers || []).length >= MAX_IDEA_PAPERS ? 'disabled' : ''}>＋ 고른 종이 ${more.length}개 연결</button>` : ''}
          <button type="button" class="idea-delete ${confirm ? 'confirm' : ''}" data-action="idea-delete" data-idea="${id}" ${busy ? 'disabled' : ''}>${confirm ? '정말 지우기' : '지우기'}</button>
        </div>
      </div>
    </li>`;
}

function ideasPanel() {
  const ideas = ui.board?.ideas || [];
  const busy = ui.ideaBusy || !ui.board;
  const picked = ui.selected.length;
  const notes = pickedNotes(ui.selected, ui.board);
  const inPlay = ideasInPlay(ui.board);
  const list = !ui.board ? '<p class="muted">제도판을 불러오는 중입니다.</p>'
    : ideas.length ? `<ol class="idea-list" aria-label="아이디어 목록 (순서대로)">${ideas.map((idea, i) => ideaItem(idea, i, ideas.length)).join('')}</ol>`
    : `<div class="idea-empty"><p><b>설계를 이끌 메인 아이디어를 모아 두세요.</b></p>
        <p>아래에 직접 적거나, 대화의 답변에서 <b>＋ 아이디어로</b>를 누르면 그 메시지(드래그로 고른 부분)가 들어옵니다. 순서가 곧 중요도입니다.</p></div>`;
  return `<aside id="experts-panel" class="experts panel ideas-panel" aria-label="아이디어 보드">
    ${sideTabs()}
    <header class="pane-head"><div><span class="eyebrow">메인 방향</span><h2>아이디어 보드 <span class="expert-count">${ideas.length}</span></h2>
      <p>${ideas.length ? `AI가 읽는 아이디어 ${inPlay}개 · AI는 읽기만 하고 바꾸지 않습니다` : 'AI는 읽기만 하고 바꾸지 않습니다'}</p></div>
      <button type="button" class="ghost" data-action="collapse-experts" aria-label="아이디어 보드 접기" aria-controls="experts-panel" aria-expanded="true">›</button></header>
    <div class="experts-scroll ideas-scroll" data-scroll="ideas" data-scroll-from="top">${list}</div>
    <form class="idea-new" id="idea-new-form" aria-label="새 아이디어">
      ${notes.length ? `<button type="button" class="idea-from-notes" data-action="idea-notes" ${busy ? 'disabled' : ''}>고른 메모 ${notes.length}장을 아이디어로</button>` : ''}
      <textarea data-focus="idea-new" data-idea-draft="idea-new" aria-label="새 아이디어" placeholder="새 아이디어 적기 (예: 길에서 마당이 보이게)" maxlength="${MAX_IDEA_TEXT}" rows="2">${escape(draftFor('idea-new'))}</textarea>
      <div class="idea-new-footer">
        ${picked ? `<label class="idea-link-picked"><input type="checkbox" id="idea-new-link" ${ui.ideaLinkNew ? 'checked' : ''}> 고른 종이 ${Math.min(picked, MAX_IDEA_PAPERS)}장 연결</label>` : '<span class="composer-hint">Enter 추가 · Shift+Enter 줄 바꿈</span>'}
        <button type="submit" class="primary small" ${busy ? 'disabled' : ''}>추가</button></div>
    </form>
  </aside>`;
}

function proposalBlock(agent) {
  const proposal = ui.session?.proposal;
  if (!proposal || proposal.agent !== agent) return '';
  const names = Object.fromEntries((ui.session?.experts || []).map((e) => [e.id, e.name]));
  const sections = stateChangeView(proposal.changes, names);
  const raw = (proposal.diff || '').startsWith('---');
  let body;
  if (sections.length) {
    body = `<div class="state-changes">${sections.map((s) => `<div class="state-change">
      <h4>${escape(s.title)}${s.summary ? ` <span class="summary">${escape(s.summary)}</span>` : ''}</h4><ul>${s.rows.map(stateChangeRow).join('')}</ul></div>`).join('')}</div>`;
  } else if (!proposal.changes) {
    body = `<pre class="diff">${escape(proposal.diff)}</pre>`;
  } else {
    body = `<p class="state-note">${raw ? '바뀌는 내용은 마지막 갱신 날짜뿐입니다.' : escape(proposal.diff)}</p>`;
  }
  const rawDiff = proposal.changes && raw
    ? `<details class="raw-diff"><summary>원본 비교 보기</summary><pre class="diff">${escape(proposal.diff)}</pre></details>` : '';
  return `<section class="proposal" aria-label="설계 상태 반영안">
    <h3>설계 상태에 반영할까요?</h3>
    <p class="muted">반영하면 설계 상태(PROJECT STATE)가 이렇게 바뀝니다.</p>
    ${body}${rawDiff}
    <div class="form-actions"><button class="secondary" data-action="skip-proposal" data-id="${escape(proposal.id)}">건너뛰기</button>
      <button class="primary" data-action="apply-proposal" data-id="${escape(proposal.id)}">반영하기</button></div>
  </section>`;
}

function stateChangeRow(row) {
  if (row.kind === 'changed') {
    const value = row.before
      ? `<span class="before">${escape(row.before)}</span> → <strong>${escape(row.text)}</strong>`
      : `<strong>${escape(row.text)}</strong>`;
    return `<li class="changed"><span class="field">${escape(row.label)}</span><span>${value}</span>${row.note ? `<p class="note">${escape(row.note)}</p>` : ''}</li>`;
  }
  if (row.kind === 'removed') return `<li class="removed"><span class="sr-only">빠짐: </span><s>${escape(row.text)}</s></li>`;
  return `<li class="added">${escape(row.text)}</li>`;
}

// ------------------------------------------------------------------ expert page

function expertLink(name, id) {
  const other = expertById(id);
  return other && other.tier !== 'held' ? `<a class="expert-chip" href="${expertUrl(name, id)}">${escape(other.name)}</a>` : '';
}

function itemsHtml(items, render = (item) => renderInline(item)) {
  return items.map((item) => `<li>${render(item)}</li>`).join('');
}

function tagged(item, tags) {
  const tag = itemTag(item, tags);
  return `${tag ? `<span class="status-badge ${tag.tone}">${escape(tag.label)}</span> ` : ''}${renderInline(item)}`;
}

// One section of an expert document, drawn the way that expert's layout asks (model.js EXPERT_LAYOUTS).
function sectionBlock(block, row, agent, index) {
  const { label, body, items } = block;
  let inner;
  if (row.kind === 'lead') {
    const [first, ...others] = items;
    inner = `<p class="lead-text">${renderInline(first || '')}</p>${others.length ? `<ul class="lead-others">${itemsHtml(others)}</ul>` : ''}`;
  } else if (row.kind === 'cards' || (row.kind === 'tagged' && row.cards)) {
    const draw = row.kind === 'tagged' ? (item) => tagged(item, row.tags) : (item) => renderInline(item);
    inner = `<ul class="card-list">${itemsHtml(items, draw)}</ul>`;
  } else if (row.kind === 'tagged') {
    inner = `<ul class="tag-list">${itemsHtml(items, (item) => tagged(item, row.tags))}</ul>`;
  } else if (row.kind === 'checklist') {
    inner = `<ul class="check-list">${items.map((item, i) => {
      const key = `${currentRoute.name}:${agent}:${label}:${i}`;
      return `<li><label><input type="checkbox" data-check="${escape(key)}" ${ui.checks.has(key) ? 'checked' : ''}> <span>${renderInline(item)}</span></label></li>`;
    }).join('')}</ul>`;
  } else if (row.kind === 'steps') {
    inner = `<ol class="step-list">${itemsHtml(items)}</ol>`;
  } else if (row.kind === 'qa') {
    inner = `<div class="qa-list">${items.map((item) => {
      const { question, answer } = questionAnswer(item);
      return answer
        ? `<details><summary>${renderInline(question)}</summary><p>${renderInline(answer)}</p></details>`
        : `<p>${renderInline(question)}</p>`;
    }).join('')}</div>`;
  } else {
    inner = `<div class="markdown">${renderMarkdown(body)}</div>`;
  }
  return `<section class="doc-section kind-${row.kind}" aria-labelledby="sec-${index}"><h2 id="sec-${index}">${escape(label)}</h2>${inner}</section>`;
}

function arrangedDoc(name, agent, content) {
  const ids = visibleExperts(ui.session?.experts).map((e) => e.id);
  const arranged = arrangeDocument(agent, content, ids);
  const raw = `<div class="markdown doc">${renderMarkdown(content)}</div>`;
  if (!arranged) return raw;
  let index = 0;
  const rows = arranged.rows.map((row) => `<div class="doc-row ${row.top ? 'top' : ''} cols-${row.blocks.length}">
      ${row.blocks.map((block) => sectionBlock(block, row, agent, index++)).join('')}</div>`).join('');
  const next = arranged.handoffs.length
    ? `<section class="doc-section handoff"><h2>다음 전문가</h2><ul>${arranged.handoffs.map((h) => `<li>${expertLink(name, h.agent)} ${renderInline(h.text)}</li>`).join('')}</ul></section>`
    : '';
  return `${arranged.intro ? `<div class="markdown">${renderMarkdown(arranged.intro)}</div>` : ''}${rows}${next}
    <details class="raw-doc" ${ui.showRaw ? 'open' : ''}><summary>원문 보기</summary>${raw}</details>`;
}

// Site reader and regulation checker work from the saved site facts: say which site, or that there is none.
function siteNote(name, agent) {
  if (!SITE_EXPERTS.has(agent) || !ui.site) return '';
  if (!ui.site.available) {
    return `<p class="site-note warn">아직 대지를 조회하지 않아 정부 데이터 없이 브리프만으로 실행됩니다. <a href="${sitePath(name, 'find')}">대지 찾기</a></p>`;
  }
  return `<p class="site-note">대지 · ${escape(siteHeadline(ui.site))} <a href="${sitePath(name)}">대지 보기</a></p>`;
}

function docTab(name, agent, expert) {
  const loading = !ui.module && !ui.moduleMissing && expert.done;
  if (!ui.module) {
    return `${siteNote(name, agent)}<div class="expert-note">${loading ? '불러오는 중입니다.' : '아직 실행 전입니다. 오른쪽에서 실행하면 결과가 여기에 나옵니다.'}</div>`;
  }
  const reads = expert.inputs?.length
    ? `<p class="reads">읽은 전문가 ${expert.inputs.map((id) => expertLink(name, id)).join('')}</p>` : '';
  return `${proposalBlock(agent)}${siteNote(name, agent)}${reads}${arrangedDoc(name, agent, ui.module.content)}`;
}

function chatTab(name, agent, expert) {
  const busy = jobRunning();
  const chat = activeChat();
  const chatOn = (ui.chat ? ui.chat.chat : expert.chat) && !ui.chatMissing;
  const items = chatItems(ui.chat?.messages);
  const live = ui.job?.kind === 'expert_chat' && ui.job.agent === agent && ui.job.chat === chat ? ui.live : [];
  const pending = ui.pending?.target === `${agent}/${chat}` ? [{ kind: 'user', text: ui.pending.text, context: ui.pending.context }] : [];
  const chats = expert.chats?.length ? expert.chats : [{ id: chat }];
  const list = `<nav class="chat-pills" aria-label="분석 채팅">
      ${chats.map((c) => `<a class="chat-pill ${c.id === chat ? 'active' : ''}" href="${expertUrl(name, agent, c.id)}" ${c.id === chat ? 'aria-current="page"' : ''}>${escape(chatTitle(c.id))}${chatAnswering(agent, c.id) ? ' · 답하는 중' : ''}</a>`).join('')}
      <button class="chat-pill new" data-action="new-chat" data-agent="${escape(agent)}">＋ 새 분석 채팅</button></nav>`;
  return `${list}
    <div class="chat-scroll" data-scroll="expert:${escape(agent)}:${escape(chat)}">
      ${ui.chatMissing ? `<p class="expert-note error-text">${escape(chatTitle(chat))} 대화를 찾을 수 없습니다. 다른 대화를 고르거나 새 분석 채팅을 시작해 주세요.</p>` : ''}
      ${!ui.chatMissing && !items.length && !pending.length && !live.length ? `<p class="muted">${escape(expert.name)}에게 결과에 대해 묻거나 더 파고들 점을 적어 보세요.</p>` : ''}
      <div class="message-list" role="log" aria-label="${escape(expert.name)} 대화">
        ${items.map((item) => bubble(item, expert.name, {})).join('')}
        ${[...pending, ...live].map((item) => bubble(item, expert.name)).join('')}
        ${workingLine(false)}
      </div>
    </div>
    ${chatOn ? composer(`expert:${agent}:${chat}`, `${expert.name}에게 메시지...`, expert.name, busy) : ''}`;
}

function versionsTab(name, agent) {
  const versions = ui.versions || [];
  const { version } = currentRoute;
  if (ui.versions === null) return '<p class="muted">불러오는 중입니다.</p>';
  if (!versions.length) {
    return '<div class="expert-note">이전 버전이 없습니다. 다시 실행하거나 수정 요청을 보내면 그 전 결과가 여기에 남습니다.</div>';
  }
  const current = ui.module
    ? `<li><a class="${version ? '' : 'active'}" href="${expertPath(name, agent, 'versions')}" ${version ? '' : 'aria-current="page"'}>지금 결과 · ${escape(dateTime(ui.module.updated_at))}</a></li>` : '';
  const list = `<ul class="version-list">${current}${versions.map((v) => `<li><a class="${v.id === version ? 'active' : ''}" href="${expertPath(name, agent, 'versions', v.id)}" ${v.id === version ? 'aria-current="page"' : ''}>${escape(dateTime(v.saved_at))}</a></li>`).join('')}</ul>`;
  let doc;
  if (version && ui.versionMissing) doc = '<p class="error-text">이 버전을 찾을 수 없습니다.</p>';
  else if (version && !ui.version) doc = '<p class="muted">불러오는 중입니다.</p>';
  else if (version) doc = `<p class="muted small-text">${escape(dateTime(ui.version.saved_at))}에 저장된 결과입니다. 지금 결과와 다를 수 있습니다.</p><div class="markdown doc">${renderMarkdown(ui.version.content)}</div>`;
  else doc = ui.module ? `<div class="markdown doc">${renderMarkdown(ui.module.content)}</div>` : '<p class="muted">지금 결과가 없습니다.</p>';
  return `<div class="versions">${list}<div class="version-doc">${doc}</div></div>`;
}

function runLine(agent) {
  if (!jobRunning()) return '';
  const job = ui.job;
  const mine = job.running_agent === agent || (job.agent === agent && job.kind === 'expert_chat');
  const text = mine ? (job.kind === 'expert_chat' ? '분석 채팅에 답하는 중입니다…' : '실행 중입니다…') : '다른 작업이 실행 중입니다. 끝나면 실행할 수 있습니다.';
  return `<p class="working" role="status">${mine ? '<span class="spinner" aria-hidden="true"></span>' : ''}${escape(text)}</p>`;
}

function reviewCard(name, agent, expert) {
  const busy = jobRunning();
  const revision = ui.revisionOpen
    ? `<form class="revision-form" id="revision-form"><label for="revision-text">무엇을 고칠지 적어 주세요</label>
        <textarea id="revision-text" data-focus="revision" maxlength="4000" rows="4">${escape(draftFor(`revision:${agent}`))}</textarea>
        <div class="form-actions"><button class="secondary" type="button" data-action="close-revision">취소</button>
        <button class="primary" type="submit" ${busy ? 'disabled' : ''}>보내기</button></div></form>`
    : '';
  const sent = ui.feedback[agent];
  const feedback = expert.done
    ? `<section class="feedback" aria-label="결과 평가"><h3>이 결과가 도움이 됐나요?</h3>
        ${sent ? `<p class="muted small-text">${sent.recorded ? '평가를 보냈습니다. 고맙습니다.' : '이 PC는 "사용 기록 보내기"가 꺼져 있어 평가가 전달되지 않았습니다. 설정에서 켤 수 있습니다.'}</p>` : `
        <label class="sr-only" for="feedback-text">한 줄 의견</label>
        <input id="feedback-text" data-focus="feedback" maxlength="500" placeholder="한 줄 의견 (선택)" value="${escape(draftFor(`feedback:${agent}`))}">
        <div class="feedback-buttons"><button class="secondary small" data-action="feedback" data-rating="up">도움 됨</button>
          <button class="secondary small" data-action="feedback" data-rating="down">아쉬움</button></div>`}
      </section>`
    : '';
  const proposalWaiting = ui.session?.proposal?.agent === agent && currentRoute.tab !== 'doc';
  return `<aside class="review-card" aria-label="검토">
    <h2>검토</h2>
    <p class="muted">결과를 확인하고 다음 작업을 고릅니다.</p>
    ${runLine(agent)}
    ${proposalWaiting ? `<p class="review-note">설계 상태 반영안이 기다리고 있습니다. <a href="${expertUrl(name, agent)}">결과 탭에서 보기</a></p>` : ''}
    <div class="review-actions">
      <button class="primary" data-action="run-expert" data-agent="${escape(agent)}" ${busy ? 'disabled' : ''}>${expert.done ? '다시 실행' : '실행'}</button>
      ${expert.done ? `<button class="secondary" data-action="open-revision" ${busy ? 'disabled' : ''}>수정 요청</button>` : ''}
    </div>
    ${revision}
    ${expert.chat ? '' : `<p class="muted small-text">${escape(expert.name)}는 정부 데이터에서 온 사실을 다루기 때문에 채팅이 없습니다. 바꿀 내용은 수정 요청으로 보내 주세요.</p>`}
    ${feedback}
  </aside>`;
}

function expertPage(name, agent) {
  if (!ui.session) {
    return `<section class="expert-page"><p class="${ui.sessionError ? 'error-text' : 'muted'}">${escape(ui.sessionError || '불러오는 중입니다.')}</p></section>`;
  }
  const expert = expertById(agent);
  if (!expert) {
    return `<section class="expert-page"><header class="expert-head"><div><h1>전문가를 찾을 수 없습니다</h1></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="전문가 화면 닫기">×</a></header></section>`;
  }
  const tab = currentRoute.tab === 'chat' && !expert.chat ? 'doc' : currentRoute.tab;
  const status = expertStatus(expert, ui.job);
  const tabs = [
    ['doc', '결과', expertUrl(name, agent)],
    ...(expert.chat ? [['chat', `분석 채팅${expert.chats?.length ? ` ${expert.chats.length}` : ''}`, expertPath(name, agent, 'chat')]] : []),
    ['versions', `이전 버전${ui.versions?.length ? ` ${ui.versions.length}` : ''}`, expertPath(name, agent, 'versions')],
  ];
  const body = tab === 'chat' ? chatTab(name, agent, expert) : tab === 'versions' ? versionsTab(name, agent) : docTab(name, agent, expert);
  return `<section class="expert-page" aria-label="${escape(expert.name)}">
    <header class="expert-head"><div>
      <h1>${escape(expert.name)}</h1>
      <p class="expert-meta">${escape(phaseLabel(expert))} · <span class="status-badge ${status}">${escape(STATUS_LABELS[status])}</span>${expert.updated_at ? ` · 마지막 실행 ${escape(dateTime(expert.updated_at))}` : ''}</p></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="전문가 화면 닫기">×</a>
    </header>
    <nav class="expert-tabs" aria-label="${escape(expert.name)} 화면">
      ${tabs.map(([id, label, href]) => `<a class="tab ${id === tab ? 'active' : ''}" href="${href}" ${id === tab ? 'aria-current="page"' : ''}>${escape(label)}</a>`).join('')}
    </nav>
    <div class="expert-body">
      <section class="expert-content ${tab === 'chat' ? 'is-chat' : ''}" aria-label="${escape(tabs.find((t) => t[0] === tab)[1])}">
        ${tab === 'chat' ? body : `<div class="content-scroll" data-scroll="page:${escape(agent)}:${tab}" data-scroll-from="top">${body}</div>`}
      </section>
      ${reviewCard(name, agent, expert)}
    </div>
  </section>`;
}

// ------------------------------------------------------------------ site page

const listOr = (items, empty) => (items.length ? `<ul>${items.join('')}</ul>` : `<p class="muted">${escape(empty)}</p>`);

function siteSection(title, inner, extra = '') {
  return `<section class="doc-section ${extra}"><h2>${escape(title)}</h2>${inner}</section>`;
}

function zoningBlock(name, site) {
  const s = site.summary;
  if (!s.zoning.length) return siteSection('용도지역', `<p>용도지역: ${UNKNOWN}</p>`);
  const rows = s.zoning.map((z) => `<tr><th scope="row">${escape(z.zone)}</th><td>${escape(zoneScope(z, s.parcel_count))}</td>
      <td>${escape(z.bcr_max)}% 이하</td><td>${escape(z.far_min)}~${escape(z.far_max)}%</td></tr>`).join('');
  return siteSection('용도지역', `<div class="table-wrap"><table class="site-table">
      <thead><tr><th scope="col">용도지역</th><th scope="col">범위</th><th scope="col">건폐율 법정 상한</th><th scope="col">용적률 법정 범위</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="muted small-text">법정 범위입니다. 실제 적용값은 ${escape(s.municipality || '해당 지자체')} 도시계획 조례가 이 범위 안에서 정합니다. <a href="${sitePath(name, 'ordinance')}">조례 보기</a></p>`, 'site-zoning');
}

function parcelItem(p) {
  const traits = [`면적 ${areaText(p.area_m2)}`, p.land_category && `지목 ${p.land_category}`, p.use && `이용 상황 ${p.use}`, p.road_side && `도로 접면 ${p.road_side}`]
    .filter(Boolean).join(' · ');
  const missing = p.errors.map((what) => SITE_PART_LABELS[what] || what);
  return `<li><strong>${escape(p.address || p.pnu)}</strong>${p.road_address ? `<span class="muted"> · ${escape(p.road_address)}</span>` : ''}
    <br>${escape(traits)}${missing.length ? `<br><span class="unknown">${UNKNOWN}: ${escape(missing.join(', '))}</span>` : ''}</li>`;
}

function buildingsBlock(site) {
  const many = site.parcels.length > 1;
  const items = site.parcels.flatMap((p) => {
    const where = many ? `<span class="muted">${escape(p.address || p.pnu)}</span> ` : '';
    if (p.buildings === null || p.buildings === undefined) return [`<li>${where}<span class="unknown">건축물대장 ${UNKNOWN}</span></li>`];
    if (!p.buildings.length) return [`<li>${where}등록된 건물 없음</li>`];
    return p.buildings.map((b) => `<li>${where}${escape(buildingLine(b))}</li>`);
  });
  return siteSection('기존 건축물 (건축물대장)', listOr(items, '필지가 없습니다.'));
}

function restrictionsBlock(site) {
  if (!site.restrictions.length) {
    return siteSection('건축제한 근거 조문', '<p class="muted">이 대지를 조회할 때는 가져오지 않았습니다. 다시 조회하면 채워집니다.</p>');
  }
  const many = site.restrictions.length > 1;
  const law = (l) => `<li>${escape(l.text)}${l.zones?.length ? ` <span class="muted small-text">${escape(l.zones.join(', '))}</span>` : ''}</li>`;
  const inner = site.restrictions.map((r) => {
    const { national, local, error } = restrictionGroups(r);
    const head = many ? `<h3>시·군·구 ${escape(r.area)}</h3>` : '';
    if (error) return `${head}<p class="unknown">가져오지 못했습니다(${escape(error)}). ${UNKNOWN}</p>`;
    if (!national.length && !local.length) return `${head}<p class="muted">해당하는 조문이 없습니다.</p>`;
    return `${head}<div class="doc-row cols-2">
        <div><h3>국가 법령</h3>${national.length ? `<ul>${national.map(law).join('')}</ul>` : '<p class="muted">없음</p>'}</div>
        <div><h3>조례</h3>${local.length ? `<ul>${local.map(law).join('')}</ul>` : '<p class="muted">없음</p>'}</div></div>`;
  }).join('');
  return siteSection('건축제한 근거 조문', `${inner}<p class="muted small-text">정부 응답에 법령 이름이 없어 조문 제목만 보여 줍니다.</p>`);
}

// Before any site is saved (or while loading): what the facts, ordinance and uses tabs show instead.
function siteNotYet(name) {
  const site = ui.site;
  if (!site) return `<p class="${ui.siteError ? 'error-text' : 'muted'}">${escape(ui.siteError || '불러오는 중입니다.')}</p>`;
  if (site.available) return '';
  return `<div class="expert-note"><p>아직 대지를 조회하지 않았습니다. 주소로 필지를 찾아 저장하면 정부 데이터에서 용도지역, 법정 건폐율·용적률, 조례, 기존 건축물, 건축제한 근거 조문을 가져옵니다.</p>
      <p class="note-actions"><a class="primary small" href="${sitePath(name, 'find')}">대지 찾기</a></p></div>`;
}

function factsTab(name) {
  const site = ui.site;
  const notYet = siteNotYet(name);
  if (notYet) return notYet;
  const s = site.summary;
  const overview = [
    `<li>필지 ${s.parcel_count}개${s.parcel_count > 1 ? '를 하나의 대지로 봄' : ''}</li>`,
    `<li>합계 면적 ${escape(areaText(s.total_area_m2))}${s.area_complete ? '' : ` <span class="unknown">(일부 필지 면적 ${UNKNOWN})</span>`}</li>`,
    `<li>조례를 정하는 지자체 ${escape(s.municipality || UNKNOWN)}</li>`,
  ].join('');
  const districts = s.districts.map((d) => `<li>${escape(d.name)} <span class="muted">${escape(d.relation)}</span></li>`);
  const roads = s.roads.map((r) => `<li>${escape(r.name)} <span class="muted">${escape(r.relation)}</span></li>`);
  const flags = s.flags.length ? siteSection('확인 필요', `<ul>${s.flags.map((f) => `<li>${escape(f)}</li>`).join('')}</ul>`, 'site-flags') : '';
  const missing = s.missing.length
    ? siteSection(UNKNOWN, `<ul>${s.missing.map((m) => `<li>${escape(missingText(m))}</li>`).join('')}</ul><p class="muted small-text">가져오지 못한 항목은 추정하지 않습니다. 다시 조회해 보세요.</p>`)
    : '';
  return `<div class="doc-row top">${siteSection('대지', `<ul>${overview}</ul>`)}</div>
    <div class="doc-row">${zoningBlock(name, site)}</div>
    ${flags ? `<div class="doc-row">${flags}</div>` : ''}
    <div class="doc-row cols-2">${siteSection('그 밖의 지역·지구', listOr(districts, '없음'))}${siteSection('도시계획 도로', listOr(roads, '없음'))}</div>
    <div class="doc-row">${siteSection('필지', `<ul class="card-list">${site.parcels.map(parcelItem).join('')}</ul>`)}</div>
    <div class="doc-row">${buildingsBlock(site)}</div>
    <div class="doc-row">${restrictionsBlock(site)}</div>
    ${missing ? `<div class="doc-row">${missing}</div>` : ''}
    <details class="raw-doc site-lines" ${ui.showSiteLines ? 'open' : ''}><summary>전문가가 받는 대지 사실 원문</summary><pre>${escape(site.lines.join('\n'))}</pre></details>`;
}

function regionSelect(level) {
  const f = ui.find;
  const list = f.lists[level];
  if (!list && f.loading !== level) return '';
  const chosen = f.chosen[level]?.code || '';
  const options = list
    ? `<option value="">고르세요</option>${list.map((r) => `<option value="${escape(r.code)}" ${r.code === chosen ? 'selected' : ''}>${escape(r.name)}</option>`).join('')}`
    : '<option value="">불러오는 중…</option>';
  return `<label for="region-${level}">${REGION_LABELS[level]}</label>
    <select id="region-${level}" data-region="${level}" data-focus="region-${level}" ${list && !f.busy ? '' : 'disabled'}>${options}</select>`;
}

function candidateList() {
  const f = ui.find;
  if (!f.candidates) return '';
  if (!f.candidates.length) return '';
  const picked = new Set(f.picked.map((p) => p.pnu));
  return `<section class="candidates" aria-labelledby="candidates-title"><h2 id="candidates-title">찾은 필지 ${f.candidates.length}개</h2>
    <p class="muted small-text">대지로 쓸 필지를 고르세요. 여러 개를 고르면 하나의 대지로 합칩니다.</p>
    <ul>${f.candidates.map((c) => `<li><label><input type="checkbox" data-pick="${escape(c.pnu)}" ${picked.has(c.pnu) ? 'checked' : ''} ${f.busy ? 'disabled' : ''}>
      <span><strong>${escape(c.address || c.pnu)}</strong>${c.road_address ? `<span class="muted"> · ${escape(c.road_address)}</span>` : ''}${c.building ? `<span class="muted"> · ${escape(c.building)}</span>` : ''}</span></label></li>`).join('')}</ul></section>`;
}

function pickedBlock() {
  const f = ui.find;
  if (!f.picked.length) return '';
  const saving = f.busy === 'save';
  return `<section class="picked-lots" aria-labelledby="picked-title"><h2 id="picked-title">고른 필지 ${f.picked.length}개</h2>
    <ul class="picked-list">${f.picked.map((p) => `<li><span>${escape(p.address || p.pnu)}</span>
      <button type="button" class="icon-button" data-action="site-unpick" data-pnu="${escape(p.pnu)}" aria-label="${escape(p.address || p.pnu)} 빼기" ${f.busy ? 'disabled' : ''}>×</button></li>`).join('')}</ul>
    ${ui.site?.available ? '<p class="muted small-text">저장하면 지금 대지 사실을 새로 조회한 값으로 바꿉니다.</p>' : ''}
    ${saving ? '<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>정부 데이터에서 대지 사실을 가져오는 중입니다. 몇 초 걸립니다.</p>' : ''}
    <div class="form-actions"><button type="button" class="primary" data-action="site-save" ${f.busy ? 'disabled' : ''}>이 필지로 대지 조회해 저장</button></div></section>`;
}

function mapBlock() {
  const f = ui.find;
  if (ui.mapError) {
    return `<p class="site-note warn">지도를 띄우지 못했습니다. ${escape(ui.mapError)} 지번이나 주소로는 찾을 수 있습니다.${ui.mapErrorStatus === 503 ? ' <button type="button" class="secondary small" data-action="settings">설정 열기</button>' : ''}</p>`;
  }
  const hint = f.mapBusy ? '누른 곳의 필지를 찾는 중입니다.' : '지도에서 필지를 누르면 고르고, 고른 필지를 다시 누르면 뺍니다. 지적선은 가까이 확대해야 보입니다.';
  return `<section class="site-map-wrap" aria-label="지도에서 필지 고르기">
    <div id="site-map-slot" class="site-map-slot">${ui.mapLayers ? '' : '<p class="muted">지도를 불러오는 중입니다.</p>'}</div>
    <p class="muted small-text" ${f.mapBusy ? 'role="status"' : ''}>${hint}</p></section>`;
}

function findTab() {
  const f = ui.find;
  const steps = f.mode === 'steps';
  const busy = Boolean(f.busy);
  const form = steps
    ? `<form class="site-form" id="lot-form" novalidate>
        <div class="region-grid">${REGION_LEVELS.map(regionSelect).join('')}</div>
        <fieldset class="lot-inputs"><legend>지번</legend>
          <label class="check"><input type="checkbox" data-lot="mountain" ${f.mountain ? 'checked' : ''}> 산</label>
          <label class="sr-only" for="lot-main">본번</label>
          <input id="lot-main" data-lot="main" data-focus="lot-main" inputmode="numeric" maxlength="4" placeholder="본번" value="${escape(f.main)}" autocomplete="off">
          <span aria-hidden="true">-</span>
          <label class="sr-only" for="lot-sub">부번 (선택)</label>
          <input id="lot-sub" data-lot="sub" data-focus="lot-sub" inputmode="numeric" maxlength="4" placeholder="부번 (선택)" value="${escape(f.sub)}" autocomplete="off">
          <button class="primary small" type="submit" ${busy || !chosenDong(f.chosen) ? 'disabled' : ''}>필지 찾기</button>
        </fieldset>
        <p class="muted small-text">부번을 비우면 그 본번의 필지가 모두 나옵니다.</p></form>`
    : `<form class="site-form" id="address-form" novalidate>
        <label for="site-query">지번 또는 도로명 주소</label>
        <div class="address-row"><input id="site-query" data-focus="site-query" maxlength="300" placeholder="예: 경기도 군포시 금정동 689" value="${escape(f.query)}" autocomplete="off">
          <button class="primary small" type="submit" ${busy ? 'disabled' : ''}>찾기</button></div>
        <p class="muted small-text">번지까지 적어 주세요. 오타는 고쳐 주지 않고, 건물·장소 이름으로는 찾지 않습니다.</p></form>`;
  const searching = f.busy === 'lots' || f.busy === 'search'
    ? '<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>필지를 찾는 중입니다.</p>' : '';
  const error = f.error
    ? `<p class="error-text" role="alert">${escape(f.error)}${f.errorStatus === 503 ? ' <button type="button" class="secondary small" data-action="settings">설정 열기</button>' : ''}</p>` : '';
  return `<div class="site-find">
    <div class="mode-switch" role="group" aria-label="찾는 방법">
      <button type="button" data-action="site-mode" data-mode="steps" aria-pressed="${steps}">지역 고르기</button>
      <button type="button" data-action="site-mode" data-mode="text" aria-pressed="${!steps}">주소 붙여넣기</button></div>
    ${form}${searching}${error}${mapBlock()}${candidateList()}${pickedBlock()}</div>`;
}

function siteTab(name, tab) {
  if (tab === 'find') return findTab();
  if (tab === 'ordinance') return ordinanceTab(name);
  if (tab === 'uses') return usesTab(name);
  return factsTab(name);
}

// ---- 조례: every article on 건폐율·용적률, never filtered; figures only as read by rule, with their line.

function figureCell(figure) {
  const f = ordinanceFigure(figure);
  return `<td><strong class="${f.text === UNKNOWN ? 'unknown' : ''}">${escape(f.text)}</strong>
    ${f.note ? `<br><span class="unknown small-text">${escape(f.note)}</span>` : ''}
    ${f.quote ? `<blockquote class="law-quote">${escape(f.quote)}${f.label ? ` <span class="muted">${escape(f.label)}</span>` : ''}</blockquote>` : ''}</td>`;
}

function ordinanceItem(group, item) {
  const applies = ordinanceApplies(item);
  const busy = ui.ordinanceBusy === item.id;
  const detailed = group.id === 'site' ? '' : `<label class="check"><input type="checkbox" data-ord-detailed="${escape(item.id)}" ${item.detailed ? 'checked' : ''} ${item.dismissed || busy ? 'disabled' : ''}> 전문가가 원문 읽기</label>`;
  return `<li class="ord-item ${item.dismissed ? 'dismissed' : ''}">
    <div class="ord-head"><strong>${escape(item.label)} ${escape(item.title)}</strong>
      ${applies ? `<span class="status-badge ${applies.tone}">${escape(applies.text)}</span>` : ''}</div>
    <details class="law-text"><summary>원문</summary><pre>${escape(item.text)}</pre></details>
    <div class="ord-actions"><span class="muted small-text">${escape(ordinanceSends(group.id, item))}</span>
      ${detailed}
      <button type="button" class="secondary small" data-action="ord-dismiss" data-id="${escape(item.id)}" data-on="${!item.dismissed}" ${busy ? 'disabled' : ''}>${item.dismissed ? '다시 보이기' : '숨기기'}</button></div></li>`;
}

function ordinanceTab(name) {
  const notYet = siteNotYet(name);
  if (notYet) return notYet;
  const o = ui.ordinance;
  if (!o) return `<p class="${ui.ordinanceError ? 'error-text' : 'muted'}">${escape(ui.ordinanceError || '조례를 불러오는 중입니다.')}</p>`;
  if (!o.available) {
    return `<div class="expert-note"><p>${o.error ? `조례를 가져오지 못했습니다: ${escape(o.error)}.` : '이 대지의 도시계획 조례를 아직 가져오지 않았습니다.'} 건폐율·용적률은 ${UNKNOWN}입니다(대지 사실 탭의 법정 범위만 확인됨).</p>
      <p class="note-actions"><a class="secondary small" href="${sitePath(name, 'find')}">대지 다시 조회</a></p></div>`;
  }
  const rows = o.base.map((b) => `<tr><th scope="row">${escape(b.zone)}</th>${figureCell(b.bcr)}${figureCell(b.far)}</tr>`).join('');
  const base = siteSection('기본 수치', `<div class="table-wrap"><table class="site-table ord-table">
      <thead><tr><th scope="col">용도지역</th><th scope="col">건폐율</th><th scope="col">용적률</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="3" class="unknown">대지의 용도지역 줄을 찾지 못했습니다. ${UNKNOWN}</td></tr>`}</tbody></table></div>
    <p class="muted small-text">조문 줄에서 정해진 규칙으로 읽은 값입니다. 아래 지구·구역 조문이 대지에 해당하면 그 조문이 우선합니다.</p>`);
  const articles = siteSection('기본 수치를 정하는 조문', o.articles.map((a) => `<details class="law-text"><summary>${escape(a.label)} ${escape(a.title)}</summary><pre>${escape(a.text)}</pre>
      ${a.annex ? `<h3>${escape(a.annex.label || '별표')}</h3>${a.annex.text ? `<pre>${escape(a.annex.text)}</pre>` : `<p class="unknown">별표 파일을 읽지 못했습니다. 조례 원문에서 직접 확인해 주세요.</p>`}` : ''}</details>`).join(''));
  const groups = o.groups.map((g) => `<div class="doc-row">${siteSection(`${g.title} (${g.items.length})`, `<p class="muted small-text">${escape(g.note)}</p>
      ${g.items.length ? `<ul class="ord-list">${g.items.map((item) => ordinanceItem(g, item)).join('')}</ul>` : '<p class="muted">없음</p>'}`)}</div>`).join('');
  return `<p class="ord-name"><b>${escape(o.name)}</b>${o.effective ? ` <span class="muted">· 시행 ${escape(o.effective)}</span>` : ''}</p>
    <div class="doc-row">${base}</div>
    <div class="doc-row">${articles}</div>
    ${groups}
    <p class="muted small-text">숨기기와 원문 읽기는 이 프로젝트에 저장되고, 대지 분석가·법규 검토자가 받는 조례 글에 반영됩니다.</p>`;
}

// ---- 계획 용도: whether a use 토지이음 knows may be built in each of the site's zones.

function useCard(use) {
  const busy = ui.useFind.busy === `remove:${use.name}`;
  const head = `<div class="use-head"><h2>${escape(use.name)}</h2>
    <span class="muted small-text">조회 ${escape(dateTime(use.checked_at))}</span>
    <button type="button" class="icon-button" data-action="use-remove" data-use="${escape(use.name)}" aria-label="${escape(use.name)} 지우기" ${busy ? 'disabled' : ''}>×</button></div>`;
  if (use.error) return `<section class="doc-section use-card">${head}<p class="unknown">${escape(useError(use.error))}</p></section>`;
  if (!use.zones.length) return `<section class="doc-section use-card">${head}<p class="muted">이 대지의 용도지역·지구에는 이 용도에 대한 정보가 없습니다.</p></section>`;
  const zones = use.zones.map((z) => `<h3>${escape(z.zone || z.code)}${z.zone_law ? ` <span class="muted">${escape(z.zone_law)}</span>` : ''}</h3>
    <ul class="use-acts">${z.acts.map((a) => {
      const r = useResult(a.result);
      return `<li><span class="status-badge ${r.tone}">${escape(r.text)}</span> ${escape(a.act || '행위 미확인')}
        ${a.conditions.length ? `<div class="use-conditions"><span class="small-text muted">단서 조항</span>${a.conditions.map((c) => `<pre>${escape(c)}</pre>`).join('')}</div>` : ''}</li>`;
    }).join('')}</ul>`).join('');
  const defs = useDefinitions(use);
  const definitions = defs.length
    ? `<details class="law-text"><summary>용도의 법적 정의</summary><ul>${defs.map((d) => `<li><b>${escape(d.name)}</b>${d.law ? ` <span class="muted">${escape(d.law)}</span>` : ''}${d.definition ? `<br>${escape(d.definition)}` : ''}</li>`).join('')}</ul></details>` : '';
  return `<section class="doc-section use-card">${head}${zones}${definitions}</section>`;
}

function usesTab(name) {
  const notYet = siteNotYet(name);
  if (notYet) return notYet;
  const u = ui.useFind;
  const busy = Boolean(u.busy);
  const candidates = u.candidates?.length
    ? `<section class="use-candidates" aria-labelledby="use-candidates-title"><h2 id="use-candidates-title">토지이음 용도 이름 ${u.candidates.length}개</h2>
      <p class="muted small-text">고르면 이 대지의 용도지역·지구마다 지을 수 있는지 조회해 저장합니다.</p>
      <ul>${u.candidates.map((c) => `<li><button type="button" class="secondary small" data-action="use-check" data-use="${escape(c.name)}" ${busy ? 'disabled' : ''}>${escape(c.name)}</button></li>`).join('')}</ul></section>` : '';
  const working = u.busy === 'search' ? '이름을 찾는 중입니다.' : u.busy.startsWith('check:') ? `${u.busy.slice(6)}을(를) 정부 데이터에서 확인하는 중입니다.` : '';
  const error = u.error
    ? `<p class="error-text" role="alert">${escape(u.error)}${u.errorStatus === 503 ? ' <button type="button" class="secondary small" data-action="settings">설정 열기</button>' : ''}</p>` : '';
  const uses = ui.site.uses || [];
  return `<form class="site-form" id="use-form" novalidate>
      <label for="use-query">지으려는 용도</label>
      <div class="address-row"><input id="use-query" data-focus="use-query" maxlength="50" placeholder="예: 공장, 단독주택, 미술관" value="${escape(u.query)}" autocomplete="off">
        <button class="primary small" type="submit" ${busy ? 'disabled' : ''}>이름 찾기</button></div>
      <p class="muted small-text">토지이음의 용도 이름과 정확히 같아야 조회됩니다. 이름 일부로 찾은 뒤 고르세요.</p></form>
    ${working ? `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>${escape(working)}</p>` : ''}${error}${candidates}
    ${uses.length ? uses.map(useCard).join('') : '<p class="muted">아직 조회한 용도가 없습니다.</p>'}
    <p class="muted small-text">결과는 토지이음의 판단(가능·금지 등)을 그대로 보여 줍니다. "금지"여도 단서 조항으로 허용될 수 있으니 단서를 함께 확인하세요. 대지를 다시 조회하면 저장한 용도도 새 용도지역으로 다시 확인합니다.</p>`;
}

function sitePage(name) {
  const tab = currentRoute.tab;
  const site = ui.site;
  const meta = site?.available
    ? `${escape(siteHeadline(site))}${site.fetched_at ? ` · 조회 ${escape(dateTime(site.fetched_at))}` : ''}`
    : '아직 조회하지 않았습니다';
  const tabs = [
    ['facts', '대지 사실', sitePath(name)], ['ordinance', '조례', sitePath(name, 'ordinance')],
    ['uses', '계획 용도', sitePath(name, 'uses')], ['find', '찾기', sitePath(name, 'find')],
  ];
  return `<section class="expert-page site-page" aria-label="대지">
    <header class="expert-head"><div><h1>대지</h1><p class="expert-meta">${meta}</p></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="대지 화면 닫기">×</a></header>
    <nav class="expert-tabs" aria-label="대지 화면">
      ${tabs.map(([id, label, href]) => `<a class="tab ${id === tab ? 'active' : ''}" href="${href}" ${id === tab ? 'aria-current="page"' : ''}>${label}</a>`).join('')}
    </nav>
    <div class="content-scroll" data-scroll="site:${tab}" data-scroll-from="top">${siteReaderBar(name, tab)}${siteTab(name, tab)}</div>
  </section>`;
}

// The site reader from the site page: run it on the saved site, or say it waits for one.
function siteReaderBar(name, tab) {
  const expert = expertById('site_reader');
  if (!expert) return '';
  const busy = jobRunning();
  if (ui.siteFirst && tab === 'find') {
    return `<div class="site-run waiting"><p>대지 분석가는 저장한 대지 사실로 실행합니다. 필지를 찾아 저장하면 바로 실행합니다.</p>
      <button class="secondary small" data-action="run-expert" data-agent="site_reader" data-without-site="true" ${busy ? 'disabled' : ''}>대지 없이 브리프로 실행</button></div>`;
  }
  if (!ui.site?.available) return '';
  if (expertStatus(expert, ui.job) === 'running') {
    return `<div class="site-run"><p class="working" role="status"><span class="spinner" aria-hidden="true"></span><b>대지 분석가</b> · 실행 중입니다. 결과는 제도판의 AI 섹션에 놓입니다.</p></div>`;
  }
  return `<div class="site-run"><p><b>대지 분석가</b> · ${expert.done ? `결과 있음 <a href="${expertPath(name, 'site_reader')}">결과 보기</a>` : '아직 실행 전'}</p>
    <button class="secondary small" data-action="run-expert" data-agent="site_reader" ${busy ? 'disabled' : ''}>${expert.done ? '다시 실행' : '실행'}</button></div>`;
}

// The board panel's head: where we are, the panel toggles, and what is picked on the table.
function boardHead(name, site, agent) {
  const shown = panelShown(ui.conductor, ui.pane, matchMedia('(max-width: 900px)').matches);
  const picked = pickedNames(ui.selected, ui.board);
  const compare = canCompare(ui.selected, ui.board);
  const masses = massIds(ui.board);
  const selection = picked.length
    ? `<span class="selection-count" role="status">선택 ${picked.length}개</span>
      <div class="selection-items">${picked.map((p) => `<button type="button" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)} ↗</button>`).join('')}</div>
      <button type="button" class="selection-ask" data-action="ask-selection" data-compare="${compare}">${compare ? '두 안 비교 질문 →' : '이 자료로 질문 →'}</button>
      <button type="button" class="selection-clear" data-action="clear-selection" aria-label="선택 모두 해제">×</button>`
    : `<span class="selection-guide">종이 클릭: 상세 보기 · Shift+클릭: 여러 장 골라 대화에 보내기</span>
      ${masses.length ? '<button type="button" class="selection-ask" data-action="select-masses">매스안 선택</button>' : ''}`;
  // The experts panel folds with its own › (2026-11-01 지훈): the head only offers it back once folded.
  return `<header class="board-head">
      <div class="board-heading"><span class="eyebrow"><a href="#/">프로젝트</a><span aria-hidden="true">/</span><button type="button" class="project-name-edit" data-action="project-info" data-project="${escape(name)}" title="프로젝트 정보 수정">${escape(currentProjectLabel(name))} ✎</button><span aria-hidden="true">/</span>${site ? '대지' : '디자인'}</span><h1>제도판</h1></div>
      <div class="panel-toggles">
        <button type="button" class="panel-toggle" data-action="conductor-toggle" aria-controls="conductor-panel" aria-expanded="${shown}" aria-label="Conductor 대화 ${shown ? '접기' : '열기'}">대화</button>
        ${site || agent || !ui.expertsCollapsed ? '' : `<button type="button" class="panel-toggle" data-action="toggle-experts-panel" aria-controls="experts-panel" aria-expanded="false"><span aria-hidden="true">‹</span> ${ui.sideTab === 'ideas' ? '아이디어' : '전문가'}</button>`}
        ${site ? '' : `<button type="button" class="panel-toggle" data-action="vworld-3d" aria-pressed="${Boolean(ui.vworld)}" title="브이월드 3D 지도에 매스안 세워 보기 (vworld)">브이월드 3D</button>`}
        <details class="export-menu"><summary class="panel-toggle" title="CAD·라이노 파일로 내보내기 (export)">내보내기</summary>
          <div class="export-options">${EXPORT_FORMATS.map((f) => `<button type="button" data-action="export-board" data-format="${f.key}">${f.label}</button>`).join('')}
          <p class="muted">대지 경계·매스안·트레이싱 선이 레이어별로 들어갑니다. 이 PC에 지도 묶음이 있으면 대지 주변 지형·등고선·건물도 '대지 주변' 레이어로 들어갑니다. 단위 m, 원점은 대지 가운데.</p></div></details>
        <button type="button" class="ghost settings-button" data-action="settings" aria-label="설정" title="설정">⚙${settingsWarned() ? '<span class="warn-dot" aria-label="확인할 설정 있음">●</span>' : ''}</button>
      </div>
      <p class="board-hint">기울이면 배치도가 3D가 됩니다 · 트레이싱지는 대지 위에 덮고, 옆으로 끌어내면 떼어집니다</p>
    </header>
    <div class="selection-bar ${picked.length ? 'has-selection' : ''}" aria-label="고른 종이">${selection}</div>`;
}

function settingsWarned() {
  return Boolean(ui.settings && Object.values(ui.settings.warnings || {}).some(Boolean));
}

function panelSplitter(side) {
  const label = side === 'left' ? '대화 패널 너비 조절' : '오른쪽 패널 너비 조절';
  return `<div class="studio-splitter splitter-${side}" role="separator" aria-label="${label}" aria-orientation="vertical"
    aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0" data-resize-side="${side}" data-focus="panel-${side}"
    title="드래그 또는 방향키로 너비 조절 · 두 번 누르면 기본 너비"></div>`;
}

function workspaceWidth(studio) {
  const css = getComputedStyle(studio);
  return studio.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
}

function applyPanelWidths(studio, widths, total) {
  studio.style.setProperty('--conductor-width', `${widths.left}px`);
  studio.style.setProperty('--side-width', `${widths.right}px`);
  for (const handle of studio.querySelectorAll('[data-resize-side]')) {
    const side = handle.dataset.resizeSide;
    const minimum = side === 'left' ? 280 : currentRoute.agent || currentRoute.site ? 320 : 240;
    const maximum = widths[side] + widths.board - 320;
    handle.setAttribute('aria-valuenow', Math.round(widths[side] / total * 100));
    handle.setAttribute('aria-valuemin', Math.round(Math.min(minimum, maximum) / total * 100));
    handle.setAttribute('aria-valuemax', Math.round(maximum / total * 100));
    handle.setAttribute('aria-valuetext', `${Math.round(widths[side])}픽셀`);
  }
}

function syncPanelWidths() {
  const studio = app.querySelector('.studio');
  if (!studio) return;
  if (matchMedia('(max-width: 900px)').matches) {
    studio.style.removeProperty('--conductor-width');
    studio.style.removeProperty('--side-width');
    return;
  }
  const total = workspaceWidth(studio);
  const detail = Boolean(currentRoute.agent || currentRoute.site);
  const widths = panelWidths(total, { left: ui.panelRatios.left, right: ui.panelRatios[detail ? 'detail' : 'right'] },
    { left: ui.conductor.open, right: detail || !ui.expertsCollapsed, detail });
  applyPanelWidths(studio, widths, total);
}

function workspaceView() {
  const { name, agent, site } = currentRoute;
  const expert = agent ? expertById(agent) : null;
  // The drafting table fills the screen; the experts sit on the right (and fold away), and the
  // site page or an expert's page takes their place. Conductor sits on the left when open.
  const side = site ? 'site-open' : agent ? 'expert-open' : '';
  const expertsFolded = !agent && !site && ui.expertsCollapsed;
  const sideLabel = site ? '대지' : expert ? expert.name : ui.sideTab === 'ideas' ? '아이디어' : '전문가';
  const tabs = [['conductor', '대화'], ['board', '제도판'], ['side', sideLabel]];
  return `<main class="studio with-table ${side} pane-${ui.pane} ${ui.conductor.open ? 'conductor-open' : ''} ${expertsFolded ? 'experts-collapsed' : ''}" id="main" tabindex="-1">
      ${conductorPanel()}
      ${ui.conductor.open ? panelSplitter('left') : ''}
      <section class="board panel" aria-label="제도판">${boardHead(name, site, agent)}<div class="board-canvas"><div id="table-slot"></div></div></section>
      ${site ? sitePage(name) : agent ? expertPage(name, agent) : ui.sideTab === 'ideas' ? ideasPanel() : expertsPanel()}
      ${!expertsFolded ? panelSplitter('right') : ''}
      ${commandBar()}
      <nav class="pane-tabs" aria-label="화면 바꾸기">${tabs.map(([id, label]) => `<button type="button" data-action="pane" data-pane="${id}" aria-pressed="${ui.pane === id}">${escape(label)}</button>`).join('')}</nav>
    </main>`;
}

function render(fresh = true) {
  if (panelResize) { resizeRenderPending = true; return; } // Keep the captured handle until release.
  // Keep typing and reading positions across redraws.
  const focused = document.activeElement?.dataset?.focus;
  const selection = focused ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  const scrolls = new Map();
  for (const el of app.querySelectorAll('[data-scroll]')) {
    if (!el.getClientRects().length) continue;
    const position = { top: el.scrollTop, bottom: el.scrollHeight - el.scrollTop - el.clientHeight < 40 };
    scrolls.set(el.dataset.scroll, position);
    if (el.closest('.conductor-panel')) conductorScrolls.set(el.dataset.scroll, position);
  }
  const page = currentRoute.page;
  app.innerHTML = page === 'home' ? homeView() : page === 'new' ? newView() : workspaceView();
  syncPanelWidths();
  document.title = `Sida · ${page === 'project' ? currentProjectLabel(currentRoute.name) : page === 'new' ? '새 프로젝트' : '프로젝트'}`;
  for (const el of app.querySelectorAll('[data-scroll]')) {
    if (!el.getClientRects().length) continue;
    // Chats follow their newest message; pages (data-scroll-from="top") open at the top.
    const fromTop = el.dataset.scrollFrom === 'top';
    const saved = fresh && !el.closest('.conductor-panel') ? null : scrolls.get(el.dataset.scroll) || conductorScrolls.get(el.dataset.scroll);
    if (!saved) el.scrollTop = fromTop ? 0 : el.scrollHeight;
    else el.scrollTop = saved.bottom && !fromTop ? el.scrollHeight : saved.top;
  }
  slotWatch.disconnect();
  const slot = app.querySelector('#table-slot');
  if (slot) slotWatch.observe(slot);
  placeTable();
  placeSiteMap();
  const ask = ui.focusComposer && app.querySelector('[data-focus="command"]');
  ui.focusComposer = false;
  const again = focused && app.querySelector(`[data-focus="${CSS.escape(focused)}"]`);
  if (ask) {
    ask.focus({ preventScroll: true });
    ask.setSelectionRange(ask.value.length, ask.value.length);
  } else if (again) {
    again.focus({ preventScroll: true });
    // Only text fields keep a cursor (a select or a checkbox has none to restore).
    if (selection && again.selectionStart != null && typeof again.setSelectionRange === 'function') again.setSelectionRange(...selection);
  } else if (fresh) {
    document.querySelector('#main')?.focus({ preventScroll: true });
  }
}

// ------------------------------------------------------------------ actions

function dismissTalkMenu(restoreFocus = false) {
  const opened = app.querySelector('.talk-more[open]');
  ui.talkMenu = talkMenu(ui.talkMenu, 'dismiss');
  for (const menu of app.querySelectorAll('.talk-more[open]')) menu.open = false;
  if (restoreFocus) opened?.querySelector('summary').focus({ preventScroll: true });
}

document.addEventListener('pointerdown', event => {
  if (ui.talkMenu && !event.target.closest('.talk-more')) dismissTalkMenu();
}, true);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && ui.talkMenu) {
    event.preventDefault();
    event.stopImmediatePropagation();
    dismissTalkMenu(true);
  }
}, true);

function askDeleteTalk(name, id) {
  dismissTalkMenu();
  if (jobRunning()) { toast('실행 중인 작업이 끝난 뒤 대화를 삭제해 주세요.', 'warn'); return; }
  deleteTalkDialog.dataset.project = name;
  deleteTalkDialog.dataset.talk = id;
  deleteTalkDialog.querySelector('#delete-talk-text').textContent = `‘${talkTitle(talkSummary(id))}’ 대화와 메시지를 삭제할까요? 되돌릴 수 없습니다. 브리프·대지·제도판·전문가 결과는 유지됩니다.`;
  deleteTalkDialog.querySelector('[role="alert"]').textContent = '';
  deleteTalkConfirm.disabled = false;
  deleteTalkDialog.showModal();
}

document.querySelector('#delete-talk-cancel').addEventListener('click', () => deleteTalkDialog.close());
deleteTalkConfirm.addEventListener('click', async () => {
  const { project: name, talk: id } = deleteTalkDialog.dataset;
  deleteTalkConfirm.disabled = true;
  try {
    await api(`${projectApi(name)}/talks/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (ui.project === name) {
      ui.talks.delete(id);
      ui.talkViews = ui.talkViews.filter(view => view.id !== id);
      drafts.delete(`talk:${id}`);
      conductorScrolls.delete(`talk:${id}`);
      ui.conductor = talkPanel(ui.conductor, 'remove', id);
      if (ui.session) ui.session.talks = ui.session.talks.filter(talk => talk.id !== id);
      await loadSession(name);
    }
    deleteTalkDialog.close();
    render(false);
    toast('대화를 삭제했습니다.', 'success');
  } catch (error) {
    deleteTalkDialog.querySelector('[role="alert"]').textContent = error.message;
    deleteTalkConfirm.disabled = false;
  }
});

async function openProjectInfo(name) {
  projectInfoEdit = null;
  projectInfoBody.innerHTML = '<p role="status">프로젝트 정보를 불러오는 중입니다.</p>';
  projectInfoDialog.showModal();
  try {
    const info = await api(`${projectApi(name)}/info`);
    if (!projectInfoDialog.open) return;
    projectInfoEdit = { name, ...info };
    projectInfoBody.innerHTML = `<label for="edit-project-name">프로젝트 이름</label><input id="edit-project-name" name="display_name" value="${escape(info.display_name)}" maxlength="80" required>
      <label for="edit-project-type">프로젝트 유형</label><input id="edit-project-type" name="type" value="${escape(info.type)}" maxlength="80">
      <label for="edit-project-description">설명 · 설계 의도</label><textarea id="edit-project-description" name="description" rows="6" maxlength="6000">${escape(info.description)}</textarea>
      <p class="muted small-text">대지 필지는 프로젝트의 대지 화면에서 수정할 수 있습니다.</p>
      <p class="form-error error-text" role="alert"></p>
      <div class="form-actions"><button type="button" class="secondary" id="project-info-cancel">취소</button><button type="submit" class="primary">저장</button></div>`;
    projectInfoBody.querySelector('input').focus();
  } catch (error) {
    projectInfoBody.innerHTML = `<p class="error-text" role="alert">${escape(error.message)}</p>`;
  }
}

document.querySelector('#project-info-close').addEventListener('click', () => projectInfoDialog.close());
projectInfoBody.addEventListener('click', event => { if (event.target.id === 'project-info-cancel') projectInfoDialog.close(); });
document.querySelector('#project-info-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!projectInfoEdit) return;
  const form = event.target;
  const saved = projectInfoEdit;
  const button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  const fields = Object.fromEntries(['display_name', 'type', 'description'].map(key => [key, form.elements[key].value]));
  try {
    await api(`${projectApi(saved.name)}/info`, { method: 'PATCH', body: { fields, expected_revision: saved.revision } });
    projectInfoDialog.close();
    await loadProjects();
    render(false);
    toast('프로젝트 정보를 저장했습니다.', 'success');
  } catch (error) {
    form.querySelector('[role="alert"]').textContent = error.message;
    button.disabled = false;
  }
});

function askDelete(name) {
  deleteDialog.dataset.project = name;
  deleteDialog.querySelector('#delete-text').textContent = `‘${currentProjectLabel(name)}’ 프로젝트를 삭제할까요? 브리프, Conductor 대화, 전문가 결과와 채팅, 제도판, 대지 정보가 모두 지워지며 되돌릴 수 없습니다.`;
  deleteError.textContent = '';
  deleteConfirm.disabled = false;
  deleteDialog.showModal();
}

async function deleteProject() {
  const name = deleteDialog.dataset.project;
  deleteConfirm.disabled = true;
  deleteError.textContent = '';
  try {
    await api(projectApi(name), { method: 'DELETE' });
  } catch (error) {
    deleteError.textContent = error.message;
    deleteConfirm.disabled = false;
    if (error.status !== 404) return;
  }
  deleteDialog.close();
  openingTried.delete(name);
  if (ui.projects) ui.projects = ui.projects.filter((p) => p.name !== name);
  toast(`‘${name}’ 프로젝트를 삭제했습니다.`, 'success');
  announce(`${name} 프로젝트를 삭제했습니다.`);
  if (currentRoute.page === 'project' && currentRoute.name === name) location.hash = '#/';
  else render(false);
  loadProjects().then(() => render(false));
}

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

// The picked papers go with this request and are let go once it is sent.
function takePicked() {
  const ids = ui.selected;
  const context = pickedNames(ids, ui.board);
  ui.selected = [];
  table?.setSelected([]);
  return { ids, context };
}

function send(key) {
  const { name, agent } = currentRoute;
  const text = draftFor(key).trim();
  if (!text || jobRunning()) return;
  drafts.delete(key);
  const { ids, context } = takePicked();
  const chat = activeChat();
  start(name, `${projectApi(name)}/experts/${encodeURIComponent(agent)}/chats/${encodeURIComponent(chat)}/messages`, { text, context: ids }, { target: `${agent}/${chat}`, text, context });
}

// ------------------------------------------------------------------ Conductor conversations

async function loadTalk(name, id) {
  try {
    const talk = await api(`${projectApi(name)}/talks/${encodeURIComponent(id)}`);
    if (ui.project === name) ui.talks.set(id, { messages: talk.messages });
  } catch (error) {
    if (ui.project === name) ui.talks.set(id, { messages: ui.talks.get(id)?.messages || [], error: error.message });
  }
}

// Selecting a conversation preserves each conversation's draft and paper context.
function openTalk(name, id, context = []) {
  dismissTalkMenu();
  const known = ui.talkViews.find((p) => p.id === id);
  ui.talkViews = [...ui.talkViews.filter((p) => p.id !== id), { id, context: known?.context || context }];
  ui.conductor = talkPanel(ui.conductor, 'select', id);
  ui.pane = 'conductor';
  if (!ui.talks.has(id)) loadTalk(name, id).then(() => render(false));
  render(false);
}

function talkViewById(id) {
  return ui.talkViews.find((p) => p.id === id);
}

function changeConductor(action) {
  dismissTalkMenu();
  if (action === 'toggle' && matchMedia('(max-width: 900px)').matches && ui.pane !== 'conductor') action = 'show';
  ui.conductor = talkPanel(ui.conductor, action);
  if (ui.conductor.open) ui.pane = 'conductor';
  else if (ui.pane === 'conductor') ui.pane = 'board';
  ui.cmd.help = false;
  render(false);
  if (!ui.conductor.open) app.querySelector('[data-action="conductor-toggle"]')?.focus({ preventScroll: true });
}

function sendTalk(id) {
  const name = currentRoute.name;
  const key = `talk:${id}`;
  const text = draftFor(key).trim();
  const view = talkViewById(id);
  if (!text || !view) return;
  if (jobRunning()) { toast('이전 작업이 아직 실행 중입니다. 끝나면 다시 보내 주세요.', 'warn'); return; }
  drafts.delete(key);
  start(name, `${projectApi(name)}/talks/${encodeURIComponent(id)}/messages`, { text, context: view.context },
    { target: key, text, context: pickedNames(view.context, ui.board) });
}

// A question typed on the command line starts a new talk with the papers picked on the table.
async function askFromLine(name, text) {
  if (jobRunning() || ui.creatingTalk) { toast('이전 작업이 아직 실행 중입니다. 끝나면 다시 보내 주세요.', 'warn'); return false; }
  ui.creatingTalk = true;
  const context = [...ui.selected];
  try {
    const { talk } = await api(`${projectApi(name)}/talks`, { method: 'POST' });
    ui.talks.set(talk.id, { messages: [] });
    if (ui.session) ui.session.talks = [...(ui.session.talks || []), { ...talk, title: text.split(/\s+/).join(' ').slice(0, 60) }];
    openTalk(name, talk.id, context);
    await start(name, `${projectApi(name)}/talks/${encodeURIComponent(talk.id)}/messages`, { text, context },
      { target: `talk:${talk.id}`, text, context: pickedNames(context, ui.board) });
    return true;
  } catch (error) {
    toast(error.message, 'error');
    return false;
  } finally {
    ui.creatingTalk = false;
  }
}

// ------------------------------------------------------------------ the command line

function say(text, tone = 'info') {
  ui.cmd.lines = addHistory(ui.cmd.lines, text, tone);
}

function focusCommandLine() {
  const input = app.querySelector('#command-input');
  if (!input) return false;
  input.focus({ preventScroll: true });
  input.setSelectionRange(input.value.length, input.value.length);
  return true;
}

// Enter on the command line: answer the open question, run a command, or ask the Conductor.
async function runCommandLine() {
  const name = currentRoute.name;
  const input = app.querySelector('#command-input');
  const text = input ? input.value : draftFor('command');
  const c = ui.cmd;
  c.back = -1;
  if (c.prompt) {
    const option = pickOption(text, c.prompt.options);
    if (!text.trim()) { cancelCommand(); return; }
    if (!option) { say(`'${text.trim()}'은(는) 보기에 없습니다. 번호나 이름을 입력하세요.`, 'warn'); drafts.delete('command'); render(false); focusCommandLine(); return; }
    const { prompt } = c;
    c.prompt = null;
    drafts.delete('command');
    prompt.answer(option);
    render(false);
    focusCommandLine();
    return;
  }
  const line = resolveLine(text);
  if (line.kind === 'empty') {
    if (c.last) runCommand(name, COMMANDS.find((x) => x.name === c.last));
    render(false);
    focusCommandLine();
    return;
  }
  c.typed = remember(c.typed, text);
  drafts.delete('command');
  c.pick = 0;
  if (line.kind === 'command') {
    if (line.viaKorean) say(`한글 자판으로 친 '${text.trim()}'을(를) ${line.command.name}(으)로 읽었습니다.`);
    runCommand(name, line.command);
    render(false);
    focusCommandLine();
    return;
  }
  render(false);
  if (!(await askFromLine(name, line.text))) drafts.set('command', text);
  render(false);
}

function cancelCommand() {
  const c = ui.cmd;
  if (c.prompt) say('취소했습니다.');
  c.prompt = null;
  c.help = false;
  ui.conductor = { ...ui.conductor, list: false };
  c.pick = 0;
  c.back = -1;
  drafts.delete('command');
  render(false);
  focusCommandLine();
}

const TABLE_COMMANDS = new Set(['plan', 'persp', 'zoom', 'north', 'select', 'note', 'pen', 'trace', 'mass', 'photo', 'delete', 'undo', 'redo', 'tray',
  'rect', 'pushpull', 'move', 'copy', 'rotate', 'scale', 'eraser', 'dist']);

function runCommand(name, command) {
  if (!command) return;
  const c = ui.cmd;
  c.last = command.name;
  c.help = false;
  if (TABLE_COMMANDS.has(command.name)) {
    if (!table) {
      say(`${command.name}: 제도판을 아직 불러오지 못했습니다.`, 'warn');
      return;
    }
    ui.pane = 'board';
    const problem = table.command(command.name);
    say(problem ? `${command.name}: ${problem}` : `${command.name} — ${command.label}`, problem ? 'warn' : 'info');
    return;
  }
  switch (command.name) {
    case 'board':
      if (currentRoute.agent || currentRoute.site) {
        location.hash = projectUrl(name);
        say('board — 오른쪽 페이지를 닫았습니다.');
      } else {
        ui.expertsCollapsed = !ui.expertsCollapsed;
        say(ui.expertsCollapsed ? 'board — 전문가 칸을 접었습니다.' : 'board — 전문가 칸을 폈습니다.');
      }
      ui.pane = 'board';
      break;
    case 'site':
      location.hash = sitePath(name);
      say('site — 대지 페이지를 엽니다.');
      break;
    case 'talks':
      ui.conductor = talkPanel(ui.conductor, 'list');
      ui.pane = 'conductor';
      say(ui.conductor.list ? 'talks — 대화 목록을 열었습니다.' : 'talks — 대화로 돌아갑니다.');
      break;
    case 'idea':
      openIdeas(name);
      say('idea — 아이디어 보드를 열었습니다. 오른쪽 칸에 적거나 대화에서 ＋ 아이디어로를 누르세요.');
      break;
    case 'export':
      c.prompt = {
        text: '어떤 파일로 내보낼까요?',
        options: EXPORT_FORMATS.map((f) => ({ key: f.key, label: f.label })),
        answer: (option) => { downloadBoard(name, option.key); },
      };
      break;
    case 'vworld':
      toggleVWorld(name);
      say(ui.vworld ? 'vworld — 제도판으로 돌아갑니다.' : 'vworld — 브이월드 3D 지도에 매스안을 세웁니다. 건물을 누르면 숨겨집니다.');
      break;
    case 'settings':
      openSettings();
      break;
    case 'help':
      c.help = true;
      break;
    case 'run': {
      const experts = visibleExperts(ui.session?.experts);
      if (!experts.length) { say('run: 전문가 목록을 아직 불러오지 못했습니다.', 'warn'); break; }
      c.prompt = {
        text: '어느 전문가를 실행할까요?',
        options: experts.map((e) => ({ key: e.id, label: e.name })),
        answer: (option) => { say(`run — ${option.label}을(를) 실행합니다.`); runExpert(name, option.key); },
      };
      break;
    }
    default:
      say(`${command.name}: 아직 쓸 수 없는 명령입니다.`, 'warn');
  }
}

// ------------------------------------------------------------------ the idea board

// Show the idea board in the right panel (closing an expert's or the site page first).
function openIdeas(name) {
  if (currentRoute.agent || currentRoute.site) location.hash = projectUrl(name);
  ui.sideTab = 'ideas';
  ui.expertsCollapsed = false;
  ui.pane = 'side';
}

// One idea-board change through the API; the board is read again either way.
async function ideaCall(name, path, method, body) {
  ui.ideaBusy = true;
  render(false);
  const result = await boardCall(name, () => api(`${projectApi(name)}/board/ideas${path}`, { method, body }), true);
  ui.ideaBusy = false;
  render(false);
  return result;
}

const ideaById = (id) => (ui.board?.ideas || []).find((i) => i.id === id);
const ideaUrl = (id) => `/${encodeURIComponent(id)}`;

// `done`: the toast to show, false for none.
async function addIdea(name, data, done) {
  const text = ideaText(data.text);
  if (!text) { toast('아이디어로 넣을 글이 없습니다.', 'warn'); return null; }
  const result = await ideaCall(name, '', 'POST', { ...data, text });
  if (result && done !== false) { toast(done || `아이디어 보드 ${(ui.board?.ideas || []).length}번에 넣었습니다.`); announce('아이디어를 넣었습니다.'); }
  return result;
}

async function addTypedIdea(name) {
  const text = draftFor('idea-new').trim();
  if (!text || ui.ideaBusy) return;
  const link = app.querySelector('#idea-new-link');
  const papers = link?.checked ? linkPapers([], ui.selected) : [];
  if (await addIdea(name, { text, papers }, '아이디어를 넣었습니다.')) {
    drafts.delete('idea-new');
    render(false);
    app.querySelector('[data-focus="idea-new"]')?.focus({ preventScroll: true });
  }
}

// The text selected inside a message. Kept as the selection changes, in case pressing the
// button clears the selection before the click arrives (a few seconds at most).
let messagePick = { article: null, text: '', at: 0 };
const selectedIn = (article) => {
  const sel = document.getSelection();
  if (!sel || sel.isCollapsed || !article.contains(sel.anchorNode)) return '';
  return sel.toString().trim();
};
document.addEventListener('selectionchange', () => {
  const sel = document.getSelection();
  const node = sel?.anchorNode;
  const article = (node?.nodeType === 1 ? node : node?.parentElement)?.closest?.('.message-list article');
  const text = article ? selectedIn(article) : '';
  if (text) messagePick = { article, text, at: Date.now() };
});

// The message as read on screen: the answer's rendered text, or the designer's own words.
function messageText(article) {
  const copy = article.querySelector('.assistant-copy');
  if (copy) return copy.innerText || copy.textContent || '';
  return [...article.childNodes].filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.textContent).join('');
}

function ideaFromMessage(name, button) {
  const article = button.closest('article');
  if (!article) return;
  const recent = messagePick.article === article && Date.now() - messagePick.at < 8000 && document.getSelection()?.isCollapsed;
  const picked = selectedIn(article) || (recent ? messagePick.text : '');
  const text = picked || messageText(article);
  messagePick = { article: null, text: '', at: 0 };
  const talk = button.dataset.talk || null;
  addIdea(name, { text, talk }, picked ? '고른 부분을 아이디어 보드에 넣었습니다.' : '메시지를 아이디어 보드에 넣었습니다.').then((result) => {
    if (result && !currentRoute.agent && !currentRoute.site) { ui.sideTab = 'ideas'; ui.expertsCollapsed = false; render(false); }
  });
}

async function ideasFromNotes(name) {
  const notes = pickedNotes(ui.selected, ui.board);
  let added = 0;
  for (const note of notes) {
    if (!(await addIdea(name, { text: note.text, papers: [note.id] }, false))) break;
    added += 1;
  }
  if (added) toast(`메모 ${added}장을 아이디어로 넣었습니다.`);
}

async function saveIdea(name, id) {
  const key = `idea-edit:${id}`;
  const text = draftFor(key).trim();
  if (!text) { toast('아이디어 내용을 적어 주세요. 지우려면 지우기를 누르세요.', 'warn'); return; }
  if (await ideaCall(name, ideaUrl(id), 'PATCH', { text })) { ui.ideaEdit = ''; drafts.delete(key); render(false); }
}

function orderIdeas(name, ids) {
  const now = (ui.board?.ideas || []).map((i) => i.id);
  if (sameOrder(now, ids)) return;
  const by = new Map((ui.board?.ideas || []).map((i) => [i.id, i]));
  ui.board.ideas = ids.map((id) => by.get(id)); // drawn at once; the server's answer follows
  ideaCall(name, '/order', 'PUT', { ids });
}

function ideaAction(name, action, button) {
  const id = button.dataset.idea;
  const idea = id ? ideaById(id) : null;
  if (action !== 'idea-delete') ui.ideaConfirm = '';
  if (action === 'side-tab') { ui.sideTab = button.dataset.tab; render(false); return; }
  if (action === 'idea-from-message') { ideaFromMessage(name, button); return; }
  if (action === 'idea-notes') { ideasFromNotes(name); return; }
  if (action === 'idea-cancel') { drafts.delete(`idea-edit:${ui.ideaEdit}`); ui.ideaEdit = ''; render(false); return; }
  if (!idea || ui.ideaBusy) return;
  if (action === 'idea-move') orderIdeas(name, moveIdea(ui.board.ideas.map((i) => i.id), id, Number(button.dataset.step)));
  if (action === 'idea-edit') {
    ui.ideaEdit = id;
    drafts.set(`idea-edit:${id}`, idea.text);
    render(false);
    const box = app.querySelector(`[data-focus="idea-edit:${CSS.escape(id)}"]`);
    box?.focus({ preventScroll: true });
    box?.setSelectionRange(box.value.length, box.value.length);
  }
  if (action === 'idea-off') ideaCall(name, ideaUrl(id), 'PATCH', { off: !idea.off });
  if (action === 'idea-link') ideaCall(name, ideaUrl(id), 'PATCH', { papers: linkPapers(idea.papers, ui.selected) });
  if (action === 'idea-unlink') ideaCall(name, ideaUrl(id), 'PATCH', { papers: (idea.papers || []).filter((x) => x !== button.dataset.id) });
  if (action === 'idea-unlink-talk') ideaCall(name, ideaUrl(id), 'PATCH', { talk: null });
  if (action === 'idea-delete') {
    if (ui.ideaConfirm !== id) { ui.ideaConfirm = id; render(false); return; }
    ui.ideaConfirm = '';
    if (ui.ideaEdit === id) ui.ideaEdit = '';
    ideaCall(name, ideaUrl(id), 'DELETE');
  }
}

// Dragging an idea onto another puts it before that one (after it, past the middle).
app.addEventListener('dragstart', (event) => {
  const item = event.target.closest?.('.idea[data-idea]');
  if (!item) return;
  ui.ideaDrag = item.dataset.idea;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', item.querySelector('.idea-text')?.textContent || '');
  item.classList.add('is-dragging');
});
app.addEventListener('dragover', (event) => {
  const item = ui.ideaDrag && event.target.closest?.('.idea[data-idea]');
  if (!item) return;
  event.preventDefault();
  const r = item.getBoundingClientRect();
  for (const el of app.querySelectorAll('.idea.drop-before, .idea.drop-after')) el.classList.remove('drop-before', 'drop-after');
  if (item.dataset.idea !== ui.ideaDrag) item.classList.add(event.clientY > r.top + r.height / 2 ? 'drop-after' : 'drop-before');
});
app.addEventListener('drop', (event) => {
  const item = ui.ideaDrag && event.target.closest?.('.idea[data-idea]');
  if (!item) return;
  event.preventDefault();
  const r = item.getBoundingClientRect();
  const ids = (ui.board?.ideas || []).map((i) => i.id);
  const dragged = ui.ideaDrag;
  ui.ideaDrag = '';
  orderIdeas(currentRoute.name, dropIdea(ids, dragged, item.dataset.idea, event.clientY > r.top + r.height / 2));
});
app.addEventListener('dragend', () => {
  if (!ui.ideaDrag) return;
  ui.ideaDrag = '';
  render(false);
});

// The drawing table as a DXF or 3dm file, with the scheme the table shows switched on.
async function downloadBoard(name, format) {
  const { url, filename } = boardExport(name, format, table?.active || '', currentProjectLabel(name));
  try {
    const response = await fetch(url);
    if (!response.ok) {
      let detail = '';
      try { detail = (await response.json()).detail; } catch { /* not JSON */ }
      throw new Error(typeof detail === 'string' && detail ? detail : `요청이 실패했습니다 (${response.status})`);
    }
    const link = document.createElement('a');
    link.href = URL.createObjectURL(await response.blob());
    link.download = filename;
    link.hidden = true;
    document.body.append(link);
    link.click();
    setTimeout(() => { link.remove(); URL.revokeObjectURL(link.href); }, 10000);
    say(`export — ${filename}을(를) 내려받았습니다.`);
  } catch (error) {
    const text = error instanceof TypeError ? 'Sida 서버에 연결할 수 없습니다.' : error.message;
    say(`export: ${text}`, 'warn');
    toast(`내보내지 못했습니다: ${text}`, 'error');
  }
  render(false);
}

async function sendFeedback(rating) {
  const { name, agent } = currentRoute;
  const key = `feedback:${agent}`;
  try {
    const { recorded } = await api(`${projectApi(name)}/experts/${encodeURIComponent(agent)}/feedback`, {
      method: 'POST', body: { rating, comment: draftFor(key).trim() },
    });
    drafts.delete(key);
    ui.feedback[agent] = { rating, recorded };
  } catch (error) {
    toast(error.message, 'error');
  }
  render(false);
}

async function newChat(agent) {
  const { name } = currentRoute;
  try {
    const { chat } = await api(`${projectApi(name)}/experts/${encodeURIComponent(agent)}/chats`, { method: 'POST' });
    await loadSession(name);
    ui.openExperts.add(agent);
    const target = expertUrl(name, agent, chat.id);
    if (location.hash !== target) { location.hash = target; return; }
    await loadExpert(name, agent);
    render(false);
  } catch (error) {
    toast(error.message, 'error');
  }
}

// ------------------------------------------------------------------ site page actions

function findFailed(error) {
  ui.find.error = error.message;
  ui.find.errorStatus = error.status;
}

async function loadRegions(level, parent) {
  const f = ui.find;
  f.loading = level;
  render(false);
  try {
    const { regions } = await api(parent ? `/api/site/regions?parent=${encodeURIComponent(parent)}` : '/api/site/regions');
    if (ui.find !== f) return; // another project opened meanwhile
    f.lists[level] = regions;
  } catch (error) {
    findFailed(error);
  }
  f.loading = '';
  render(false);
}

// Opening the "find" tab: the 시·도 list, and the brief's address ready for the text search.
async function prepareFind(name) {
  const f = ui.find;
  if (!f.lists.sido && !f.loading) loadRegions('sido', '');
  if (!ui.mapLayers && !ui.mapError) loadMapLayers();
  if (f.briefTried) return;
  f.briefTried = true;
  try {
    const { brief } = await api(projectApi(name));
    const address = briefSite(brief);
    if (ui.find === f && address && !f.query) {
      f.query = address;
      if (!f.chosen.sido) f.mode = 'text';
      render(false);
    }
  } catch { /* the brief is only a convenience here */ }
}

// ---- the map (site-map.js): background and 지적 line URLs once, parcel boundaries as they are needed

async function loadMapLayers() {
  try {
    ui.mapLayers = await api('/api/site/map');
  } catch (error) {
    ui.mapError = error.message;
    ui.mapErrorStatus = error.status;
  }
  render(false);
}

// The map element is moved into the redrawn page's slot (created once, on first need).
function placeSiteMap() {
  const slot = app.querySelector('#site-map-slot');
  if (!slot || !ui.mapLayers) return;
  if (!siteMap) { openSiteMap(); return; }
  siteMap.attach(slot);
  siteMap.show(mapGroups());
}

async function openSiteMap() {
  if (siteMapLoading) return;
  siteMapLoading = true;
  try {
    const { SiteMap } = await import('./site-map.js');
    siteMap = new SiteMap(ui.mapLayers, pickOnMap);
  } catch (error) {
    ui.mapError = error.message;
  }
  siteMapLoading = false;
  render(false);
}

// What the map draws: the saved site, the parcels found (not yet picked) and the picked ones.
function mapGroups() {
  const f = ui.find;
  const withShape = (p) => ({ pnu: p.pnu, shape: p.shape ?? f.shapes.get(p.pnu) ?? null });
  const picked = new Set(f.picked.map((p) => p.pnu));
  return {
    saved: ui.site?.available ? ui.site.parcels.map((p) => ({ pnu: p.pnu, shape: p.shape || null })) : [],
    candidate: (f.candidates || []).filter((c) => !picked.has(c.pnu)).map(withShape),
    picked: f.picked.map(withShape),
  };
}

async function fetchShapes() {
  const f = ui.find;
  if (!ui.mapLayers) return;
  const pnus = shapesToFetch([...(f.candidates || []), ...f.picked], f.shapes);
  if (!pnus.length) return;
  for (const pnu of pnus) f.shapes.set(pnu, null); // asked once, whatever comes back
  try {
    const { shapes } = await api(`/api/site/shapes?${pnus.map((p) => `pnu=${encodeURIComponent(p)}`).join('&')}`);
    for (const s of shapes) f.shapes.set(s.pnu, s.shape);
  } catch { /* the map just leaves those parcels out */ }
  if (ui.find === f) render(false);
}

// A click on the map: the parcel there goes into the picked list, or out if it was in.
async function pickOnMap(lon, lat, zoom) {
  const f = ui.find;
  if (f.busy || f.mapBusy) return;
  f.errorStatus = 0;
  if (zoom < MAP_PICK_ZOOM) { f.error = '필지를 고르려면 지도를 더 확대해 주세요.'; render(false); return; }
  f.error = '';
  f.mapBusy = true;
  render(false);
  try {
    const { candidates } = await api(`/api/site/parcel-at?lon=${lon.toFixed(7)}&lat=${lat.toFixed(7)}`);
    if (ui.find !== f) return;
    const [parcel] = candidates;
    if (!parcel) f.error = '누른 곳에 필지가 없습니다(도로·하천 등). 다른 곳을 눌러 주세요.';
    else {
      f.shapes.set(parcel.pnu, parcel.shape || null);
      f.picked = togglePicked(f.picked, parcel);
    }
  } catch (err) {
    findFailed(err);
  }
  f.mapBusy = false;
  render(false);
}

function chooseRegion(level, code) {
  const f = ui.find;
  const index = REGION_LEVELS.indexOf(level);
  f.chosen[level] = (f.lists[level] || []).find((r) => r.code === code) || null;
  for (const lower of REGION_LEVELS.slice(index + 1)) {
    f.chosen[lower] = null;
    f.lists[lower] = null;
  }
  f.candidates = null;
  f.error = '';
  const region = f.chosen[level];
  const next = REGION_LEVELS[index + 1];
  if (region && next && (level !== 'emd' || region.has_ri)) loadRegions(next, region.code);
  else render(false);
}

async function findLot() {
  const f = ui.find;
  const { query, error } = lotQuery(chosenDong(f.chosen), f.main, f.sub, f.mountain);
  f.error = error || '';
  f.errorStatus = 0;
  if (error) { render(false); return; }
  f.busy = 'lots';
  render(false);
  try {
    const { candidates, lot } = await api(`/api/site/lots?${query}`);
    f.candidates = candidates;
    f.search = null;
    if (!candidates.length) f.error = `${lot} 필지가 없습니다. 지번을 다시 확인해 주세요.`;
  } catch (err) {
    findFailed(err);
  }
  f.busy = '';
  render(false);
  fetchShapes();
}

async function searchAddress(name) {
  const f = ui.find;
  const text = f.query.trim();
  f.errorStatus = 0;
  if (!text) { f.error = '주소를 적어 주세요.'; render(false); return; }
  f.error = '';
  f.busy = 'search';
  render(false);
  try {
    const { query, candidates } = await api(`${projectApi(name)}/site/parcels`, { method: 'POST', body: { query: text } });
    f.candidates = candidates;
    f.search = { query, pnus: candidates.map((c) => c.pnu) };
    if (!candidates.length) f.error = '찾은 필지가 없습니다. 번지까지 적었는지, 오타가 없는지 확인해 주세요.';
  } catch (err) {
    findFailed(err);
  }
  f.busy = '';
  render(false);
  fetchShapes();
}

function togglePick(pnu, on) {
  const f = ui.find;
  const found = (f.candidates || []).find((c) => c.pnu === pnu);
  f.picked = f.picked.filter((p) => p.pnu !== pnu);
  if (on && found) f.picked.push(found);
  render(false);
}

// The Conductor wanted the site reader before a site was saved: the find tab searches the address
// it passed (the brief's otherwise), and saving the site runs the site reader.
function askForSite(name, address) {
  ui.siteFirst = true;
  const f = ui.find;
  const text = String(address || '').trim();
  if (!text || f.busy) return;
  f.query = text;
  f.mode = 'text';
  f.briefTried = true;
  searchAddress(name);
}

// Running the site reader with no site saved opens the site page to find it first; saving the site
// then runs it (or the designer runs it on the brief alone).
function runExpert(name, agent, withoutSite = false) {
  if (!withoutSite && needsSiteFirst(agent, ui.site)) {
    ui.siteFirst = true;
    location.hash = sitePath(name, 'find');
    return;
  }
  ui.siteFirst = false;
  start(name, `${projectApi(name)}/session/experts/${encodeURIComponent(agent)}/run`, { context: takePicked().ids });
}

async function setOrdinanceOption(name, id, change) {
  if (ui.ordinanceBusy) return;
  ui.ordinanceBusy = id;
  render(false);
  try {
    const ordinance = await api(`${projectApi(name)}/site/ordinance/options/${encodeURIComponent(id)}`, { method: 'PUT', body: change });
    if (ui.project === name) ui.ordinance = ordinance;
  } catch (err) {
    toast(err.message, 'error');
  }
  ui.ordinanceBusy = '';
  render(false);
}

function useFailed(error) {
  ui.useFind.error = error.message;
  ui.useFind.errorStatus = error.status;
}

async function searchUses() {
  const u = ui.useFind;
  const text = u.query.trim();
  u.errorStatus = 0;
  if (!text) { u.error = '용도 이름을 적어 주세요.'; render(false); return; }
  u.error = '';
  u.busy = 'search';
  render(false);
  try {
    const { uses } = await api(`/api/site/uses?q=${encodeURIComponent(text)}`);
    u.candidates = uses;
    if (!uses.length) u.error = `"${text}"이(가) 들어간 용도 이름이 없습니다. 더 짧게 적어 보세요.`;
  } catch (err) {
    useFailed(err);
  }
  u.busy = '';
  render(false);
}

async function checkUse(name, use) {
  const u = ui.useFind;
  if (u.busy) return;
  u.busy = `check:${use}`;
  u.error = '';
  u.errorStatus = 0;
  render(false);
  try {
    const site = await api(`${projectApi(name)}/site/uses`, { method: 'POST', body: { name: use } });
    if (ui.project === name) { ui.site = site; u.candidates = null; u.query = ''; }
  } catch (err) {
    useFailed(err);
  }
  u.busy = '';
  render(false);
}

async function removeUse(name, use) {
  const u = ui.useFind;
  if (u.busy) return;
  u.busy = `remove:${use}`;
  render(false);
  try {
    const site = await api(`${projectApi(name)}/site/uses/${encodeURIComponent(use)}`, { method: 'DELETE' });
    if (ui.project === name) ui.site = site;
  } catch (err) {
    useFailed(err);
  }
  u.busy = '';
  render(false);
}

async function saveSite(name) {
  const f = ui.find;
  if (!f.picked.length || f.busy) return;
  f.busy = 'save';
  f.error = '';
  f.errorStatus = 0;
  render(false);
  try {
    ui.site = await api(`${projectApi(name)}/site`, { method: 'PUT', body: lookupBody(f.picked, f.search) });
    ui.find = freshFind();
    ui.ordinance = null; // the new site may fall under another ordinance
    ui.useFind = freshUseFind();
    loadBoard(name); // the site paper on the table draws the new parcels and facts
    location.hash = sitePath(name);
    if (ui.siteFirst) {
      toast('대지 사실을 저장해 제도판의 대지 종이에 그렸습니다. 대지 분석가를 실행합니다.', 'success');
      runExpert(name, 'site_reader');
    } else {
      toast('대지 사실을 저장해 제도판의 대지 종이에 그렸습니다. 대지 분석가와 법규 검토자를 다시 실행하면 반영됩니다.', 'success');
    }
  } catch (err) {
    findFailed(err);
    f.busy = '';
  }
  render(false);
}

// Resize without redrawing the conversation or the WebGL table while the pointer is held.
function panelWidthKey(side) {
  return side === 'right' && (currentRoute.agent || currentRoute.site) ? 'detail' : side;
}

function currentPanelWidths(studio) {
  const css = getComputedStyle(studio);
  const total = workspaceWidth(studio);
  const left = parseFloat(css.getPropertyValue('--conductor-width')) || 0;
  const right = parseFloat(css.getPropertyValue('--side-width')) || 0;
  return { total, widths: { left, right, board: total - left - right } };
}

app.addEventListener('pointerdown', (event) => {
  const handle = event.target.closest('[data-resize-side]');
  if (!handle || event.button !== 0 || matchMedia('(max-width: 900px)').matches) return;
  event.preventDefault();
  const studio = handle.closest('.studio');
  const side = handle.dataset.resizeSide;
  panelResize = { ...currentPanelWidths(studio), side, studio, handle, pointer: event.pointerId, x: event.clientX,
    before: { ...ui.panelRatios }, minimum: side === 'left' ? 280 : currentRoute.agent || currentRoute.site ? 320 : 240 };
  handle.focus({ preventScroll: true });
  handle.setPointerCapture(event.pointerId);
  document.body.classList.add('resizing-panels');
});

window.addEventListener('pointermove', (event) => {
  const drag = panelResize;
  if (!drag || event.pointerId !== drag.pointer) return;
  const delta = (event.clientX - drag.x) * (drag.side === 'left' ? 1 : -1);
  const widths = resizePanel(drag.widths, drag.side, delta, drag.minimum);
  ui.panelRatios[panelWidthKey(drag.side)] = widths[drag.side] / drag.total;
  applyPanelWidths(drag.studio, widths, drag.total);
  placeTable();
});

function finishPanelResize(event, cancel = false) {
  if (!panelResize || event.pointerId !== panelResize.pointer) return;
  const drag = panelResize;
  panelResize = null;
  if (cancel) ui.panelRatios = drag.before;
  if (drag.handle.hasPointerCapture(drag.pointer)) drag.handle.releasePointerCapture(drag.pointer);
  document.body.classList.remove('resizing-panels');
  if (resizeRenderPending) {
    resizeRenderPending = false;
    render(false);
  } else {
    // Keep the same handle for a following click (including double-click to reset).
    syncPanelWidths();
    placeTable();
  }
}
window.addEventListener('pointerup', (event) => finishPanelResize(event));
window.addEventListener('pointercancel', (event) => finishPanelResize(event, true));
app.addEventListener('lostpointercapture', (event) => finishPanelResize(event, true));

app.addEventListener('keydown', (event) => {
  const handle = event.target.closest('[data-resize-side]');
  if (!handle || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const studio = handle.closest('.studio');
  const { total, widths } = currentPanelWidths(studio);
  const side = handle.dataset.resizeSide;
  const delta = event.key === 'Home' ? -total : event.key === 'End' ? total
    : (event.key === 'ArrowRight' ? 1 : -1) * (side === 'left' ? 1 : -1) * (event.shiftKey ? 40 : 16);
  const minimum = side === 'left' ? 280 : currentRoute.agent || currentRoute.site ? 320 : 240;
  ui.panelRatios[panelWidthKey(side)] = resizePanel(widths, side, delta, minimum)[side] / total;
  render(false);
});

app.addEventListener('dblclick', (event) => {
  const handle = event.target.closest('[data-resize-side]');
  if (!handle) return;
  const key = panelWidthKey(handle.dataset.resizeSide);
  ui.panelRatios[key] = { left: .27, right: .21, detail: .38 }[key];
  render(false);
});

app.addEventListener('click', (event) => {
  if (!event.target.closest('.talk-more')) dismissTalkMenu();
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action } = button.dataset;
  const { name, agent } = currentRoute;
  if (action === 'settings') openSettings();
  if (action === 'export-board') { button.closest('details')?.removeAttribute('open'); downloadBoard(name, button.dataset.format); }
  if (action === 'vworld-3d') toggleVWorld(name);
  if (action === 'sample') createSample();
  if (action === 'delete-project') askDelete(button.dataset.project);
  if (action === 'project-info') openProjectInfo(button.dataset.project);
  if (action === 'pane') { ui.pane = button.dataset.pane; if (ui.pane === 'conductor') ui.conductor = { ...ui.conductor, open: true }; render(false); }
  if (action === 'conductor-toggle') changeConductor('toggle');
  if (action === 'conductor-close') changeConductor('close');
  if (action === 'talks-toggle') changeConductor('list');
  if (action === 'talk-new') { changeConductor('new'); app.querySelector('[data-focus="conductor-new"]')?.focus({ preventScroll: true }); }
  if (action === 'collapse-experts') { ui.expertsCollapsed = true; if (ui.pane === 'side') ui.pane = 'board'; render(false); }
  if (action === 'toggle-experts-panel') { ui.expertsCollapsed = !ui.expertsCollapsed; render(false); }
  if (action === 'inspect-paper') table?.inspect(button.dataset.id);
  if (action === 'clear-selection') { ui.selected = []; table?.setSelected([]); render(false); }
  if (action === 'select-masses') table?.selectMasses();
  if (action === 'ask-selection') askAbout(button.dataset.compare === 'true' ? COMPARE_QUESTION : '');
  if (action === 'open-expert') location.hash = expertUrl(name, button.dataset.agent);
  if (action === 'open-chat') location.hash = expertUrl(name, button.dataset.agent, button.dataset.chat);
  if (action === 'new-chat') newChat(button.dataset.agent);
  if (action === 'run-expert') runExpert(name, button.dataset.agent, button.dataset.withoutSite === 'true');
  if (action === 'unpick') unpick(button.dataset.id);
  if (action === 'side-tab' || action.startsWith('idea-')) ideaAction(name, action, button);
  const talkId = button.dataset.talk;
  if (action === 'talk-menu') { event.preventDefault(); ui.talkMenu = talkMenu(ui.talkMenu, 'toggle', talkId); render(false); }
  if (action === 'talk-open') {
    openTalk(name, talkId);
    loadTalk(name, talkId).then(() => render(false));
    app.querySelector(`[data-focus="talk:${CSS.escape(talkId)}"]`)?.focus({ preventScroll: true });
  }
  if (action === 'talk-delete') askDeleteTalk(name, talkId);
  if (action === 'talk-unpick') { const p = talkViewById(talkId); if (p) p.context = p.context.filter((id) => id !== button.dataset.id); render(false); }
  if (action === 'talk-add-picked') { const p = talkViewById(talkId); if (p) p.context = [...new Set([...p.context, ...ui.selected])]; render(false); }
  if (action === 'cmd-help') { ui.cmd.help = false; render(false); focusCommandLine(); }
  if (action === 'cmd-option' && ui.cmd.prompt) {
    drafts.set('command', String(Number(button.dataset.index) + 1));
    render(false);
    runCommandLine();
  }
  if (action === 'cmd-pick') {
    drafts.set('command', button.dataset.command);
    ui.cmd.pick = 0;
    render(false);
    runCommandLine();
  }
  if (action === 'open-revision') { ui.revisionOpen = true; render(false); app.querySelector('#revision-text')?.focus(); }
  if (action === 'close-revision') { ui.revisionOpen = false; render(false); }
  if (action === 'apply-proposal') decideProposal(button.dataset.id, true);
  if (action === 'skip-proposal') decideProposal(button.dataset.id, false);
  if (action === 'feedback') sendFeedback(button.dataset.rating);
  if (action === 'site-mode') { ui.find.mode = button.dataset.mode; ui.find.error = ''; render(false); }
  if (action === 'site-unpick') togglePick(button.dataset.pnu, false);
  if (action === 'site-save') saveSite(name);
  if (action === 'ord-dismiss') setOrdinanceOption(name, button.dataset.id, { dismissed: button.dataset.on === 'true' });
  if (action === 'use-check') checkUse(name, button.dataset.use);
  if (action === 'use-remove') removeUse(name, button.dataset.use);
});

app.addEventListener('input', (event) => {
  const { target } = event;
  if (target.id === 'project-search') {
    ui.query = target.value;
    document.querySelector('#project-grid').innerHTML = projectCards();
  }
  if (target.form?.id === 'new-project-form') ui.newDraft = keepNewDraft(ui.newDraft, target.name, target.value);
  if (target.matches('.composer textarea')) drafts.set(target.closest('form').dataset.composer, target.value);
  if (target.id === 'command-input') {
    drafts.set('command', target.value);
    ui.cmd.pick = 0;
    updateCommandLine();
  }
  if (target.dataset.ideaDraft) drafts.set(target.dataset.ideaDraft, target.value);
  if (target.id === 'revision-text') drafts.set(`revision:${currentRoute.agent}`, target.value);
  if (target.id === 'feedback-text') drafts.set(`feedback:${currentRoute.agent}`, target.value);
  if (target.id === 'site-query') ui.find.query = target.value;
  if (target.id === 'use-query') ui.useFind.query = target.value;
  if (target.dataset.lot === 'main' || target.dataset.lot === 'sub') ui.find[target.dataset.lot] = target.value;
});

app.addEventListener('change', (event) => {
  if (event.target.id === 'project-sort') {
    ui.sort = event.target.value;
    document.querySelector('#project-grid').innerHTML = projectCards();
  }
  const { region, pick, lot } = event.target.dataset || {};
  if (region) chooseRegion(region, event.target.value);
  if (pick) togglePick(pick, event.target.checked);
  if (lot === 'mountain') ui.find.mountain = event.target.checked;
  if (event.target.id === 'idea-new-link') ui.ideaLinkNew = event.target.checked;
  const { ordDetailed } = event.target.dataset || {};
  if (ordDetailed) setOrdinanceOption(currentRoute.name, ordDetailed, { detailed: event.target.checked });
  // Checklist ticks stay on screen only for now (not saved to the project).
  const check = event.target.dataset?.check;
  if (check) {
    if (event.target.checked) ui.checks.add(check);
    else ui.checks.delete(check);
  }
});

// Keep which experts are unfolded in the panel, and the raw document, across redraws ('toggle' does not bubble).
app.addEventListener('toggle', (event) => {
  const row = event.target;
  if (row.matches?.('details.site-lines')) ui.showSiteLines = row.open;
  else if (row.matches?.('details.raw-doc')) ui.showRaw = row.open;
  if (!row.matches?.('details.expert-row')) return;
  if (row.open) ui.openExperts.add(row.dataset.agent);
  else ui.openExperts.delete(row.dataset.agent);
}, true);

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
      ui.newDraft = {};
      if (!created) toast(`같은 이름의 프로젝트 "${project.name}"를 열었습니다.`, 'info');
      await loadProjects();
      location.hash = projectUrl(project.name);
    } catch (err) {
      error.textContent = err.message;
      form.querySelector('button[type="submit"]').disabled = false;
    } finally {
      ui.creating = false;
    }
  } else if (form.id === 'lot-form') {
    findLot();
  } else if (form.id === 'address-form') {
    searchAddress(currentRoute.name);
  } else if (form.id === 'use-form') {
    searchUses();
  } else if (form.id === 'command-form') {
    runCommandLine();
  } else if (form.id === 'idea-new-form') {
    addTypedIdea(currentRoute.name);
  } else if (form.dataset.ideaForm) {
    saveIdea(currentRoute.name, form.dataset.ideaForm);
  } else if (form.dataset.composer === 'conductor-new') {
    const key = 'conductor-new';
    const text = draftFor(key).trim();
    if (!text || ui.creatingTalk || jobRunning()) return;
    if (await askFromLine(currentRoute.name, text)) drafts.delete(key);
    render(false);
  } else if (form.matches('.talk-composer')) {
    sendTalk(form.dataset.composer.slice('talk:'.length));
  } else if (form.matches('.composer')) {
    send(form.dataset.composer);
  } else if (form.id === 'revision-form') {
    const { name, agent } = currentRoute;
    const key = `revision:${agent}`;
    const revision = draftFor(key).trim();
    if (!revision || jobRunning()) return;
    drafts.delete(key);
    ui.revisionOpen = false;
    start(name, `${projectApi(name)}/session/experts/${encodeURIComponent(agent)}/run`, { revision, context: takePicked().ids });
  }
});

// Keys on the command line: Enter runs, Shift+Enter breaks the line, ↑↓ pick a suggestion or
// go through earlier lines, Tab completes, Esc cancels. Enter while a Korean letter is still
// being composed belongs to the input method, not to the line.
function commandKey(event) {
  const input = event.target;
  const c = ui.cmd;
  const offered = c.prompt ? [] : suggest(input.value);
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    runCommandLine();
  } else if (event.key === 'Escape') {
    event.preventDefault();
    cancelCommand();
  } else if (event.key === 'Tab' && offered.length && !event.shiftKey) {
    event.preventDefault();
    input.value = offered[Math.min(c.pick, offered.length - 1)].name;
    drafts.set('command', input.value);
    c.pick = 0;
    updateCommandLine();
  } else if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && !event.isComposing) {
    const down = event.key === 'ArrowDown';
    if (offered.length > 1) {
      event.preventDefault();
      c.pick = (c.pick + (down ? 1 : -1) + offered.length) % offered.length;
      updateCommandLine();
    } else if (!input.value.includes('\n') && c.typed.length) {
      event.preventDefault();
      const at = c.back < 0 ? c.typed.length : c.back;
      const next = down ? at + 1 : Math.max(0, at - 1);
      c.back = next >= c.typed.length ? -1 : next;
      input.value = c.back < 0 ? '' : c.typed[c.back];
      drafts.set('command', input.value);
      updateCommandLine();
    }
  }
}

app.addEventListener('keydown', (event) => {
  if (event.target.id === 'command-input') { commandKey(event); return; }
  if (event.target.dataset?.ideaDraft) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      event.target.closest('form').requestSubmit();
    } else if (event.key === 'Escape' && ui.ideaEdit) {
      event.preventDefault();
      drafts.delete(`idea-edit:${ui.ideaEdit}`);
      ui.ideaEdit = '';
      render(false);
    }
    return;
  }
  if (event.target.matches('.composer textarea') && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    event.target.closest('form').requestSubmit();
  }
});

// Space anywhere outside a text field puts the cursor on the command line. There are no
// one-letter shortcuts (2026-11-02 지훈): a letter or number typed outside a text field goes
// to the command line as the start of a command word, as in CAD.
window.addEventListener('keydown', (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey || currentRoute.page !== 'project') return;
  const el = event.target;
  if (el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.isContentEditable || el.closest?.('dialog'))) return;
  if (event.key === ' ') {
    if (el?.tagName !== 'BUTTON' && focusCommandLine()) event.preventDefault();
    return;
  }
  // The key itself then lands on the command line (focus moves before it is typed).
  if ((event.key.length === 1 && /\S/.test(event.key)) || event.key === 'Process') focusCommandLine();
});

// ------------------------------------------------------------------ settings

function draftFromSettings(settings) {
  return {
    mode: settings.mode,
    local_profile: settings.local_profile,
    conductor_provider: settings.conductor.provider,
    worker_provider: settings.worker.provider,
    chatgpt_model: settings.chatgpt.model,
    worker_chatgpt_model: settings.chatgpt.worker_model,
    rag_enabled: settings.rag_enabled,
    state_update: settings.state_update,
    telemetry_enabled: settings.telemetry_enabled,
    openrouter_key: '',
    keys: Object.fromEntries(DATA_KEYS.map(({ id, secret }) => [id, secret ? '' : settings.keys?.[id]?.value || ''])),
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
    s.warnings.rag_key_missing && '법령 검색을 켰지만 법제처 인증값이 없습니다. 아래 정부 데이터 키에 넣어 주세요.',
    s.warnings.chatgpt_signed_out && 'ChatGPT 구독으로 돌리게 되어 있지만 로그인되어 있지 않습니다.',
  ].filter(Boolean);
  const modes = d.mode === 'custom' ? [...s.options.modes, 'custom'] : s.options.modes;
  const chatgpt = s.chatgpt;
  const models = ui.chatgptModels?.length ? ui.chatgptModels : [{ slug: d.chatgpt_model, display_name: d.chatgpt_model }];
  const modelSelect = (id, field, label, value) => `<label for="${id}">${label}</label>
    <select id="${id}" data-field="${field}">${(ui.chatgptModels?.length ? models : [{ slug: value, display_name: value }])
      .map((m) => option(m.slug, m.display_name || m.slug, value)).join('')}</select>`;
  const chatgptBlock = d.conductor_provider === 'chatgpt' || d.worker_provider === 'chatgpt' || chatgpt.signed_in
    ? `<fieldset class="settings-group"><legend>ChatGPT 구독</legend>
        <p>${chatgpt.signed_in ? `로그인됨: ${escape(chatgpt.email || 'ChatGPT')}` : '로그인되어 있지 않습니다.'}</p>
        ${chatgpt.signed_in && !chatgpt.plan_usage ? '<p class="error-text">구독 사용을 허용하지 않아 Sida가 쓸 수 없습니다. 다시 로그인해 주세요.</p>' : ''}
        <div class="settings-buttons">
          <button type="button" class="secondary small" data-settings="chatgpt-login">${chatgpt.signed_in ? '다시 로그인' : 'ChatGPT로 로그인'}</button>
          ${chatgpt.signed_in ? '<button type="button" class="secondary small" data-settings="chatgpt-logout">로그아웃</button>' : ''}
        </div>
        ${ui.chatgptNote ? `<p class="muted">${escape(ui.chatgptNote)}</p>` : ''}
        ${chatgpt.signed_in ? modelSelect('set-chatgpt-model', 'chatgpt_model', 'Conductor 모델', d.chatgpt_model) : ''}
        ${chatgpt.signed_in && d.worker_provider === 'chatgpt' ? modelSelect('set-worker-chatgpt-model', 'worker_chatgpt_model', '전문가 모델', d.worker_chatgpt_model)
          + '<p class="muted small-text">전문가 문서는 길어서 구독 사용량을 Conductor보다 많이 씁니다.</p>' : ''}
      </fieldset>`
    : '';
  const keyStatus = s.keys?.openrouter;
  const dataKeys = DATA_KEYS.map(({ id, label, secret }) => {
    const status = s.keys?.[id];
    const hint = secret ? (status?.set ? `저장됨 ${status.hint || ''}` : '넣지 않음') : '예: localhost';
    return `<label for="set-key-${id}">${escape(label)}</label>
      <input id="set-key-${id}" data-key="${id}" type="${secret ? 'password' : 'text'}" autocomplete="off" placeholder="${escape(hint)}" value="${escape(d.keys[id])}">`;
  }).join('');
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
    <select id="set-worker" data-field="worker_provider">${(s.options.worker_providers || s.options.providers).map((p) => option(p, PROVIDER_LABELS[p] || p, d.worker_provider)).join('')}</select>
    <p class="muted small-text">지금 모델: Conductor ${escape(s.conductor.model)}, 전문가 ${escape(s.worker.model)}</p>
    ${chatgptBlock}
    <label for="set-openrouter">OpenRouter 키</label>
    <input id="set-openrouter" data-field="openrouter_key" type="password" autocomplete="off" placeholder="${escape(keyStatus?.set ? `저장됨 ${keyStatus.hint || ''}` : '키를 넣으면 저장할 때 확인합니다')}" value="${escape(d.openrouter_key)}">
    <label for="set-state">전문가 결과를 설계 상태에</label>
    <select id="set-state" data-field="state_update">${s.options.state_update.map((m) => option(m, STATE_UPDATE_LABELS[m] || m, d.state_update)).join('')}</select>
    <label class="check"><input type="checkbox" data-field="rag_enabled" ${d.rag_enabled ? 'checked' : ''}> 법령 검색(법제처) 쓰기</label>
    <label class="check"><input type="checkbox" data-field="telemetry_enabled" ${d.telemetry_enabled ? 'checked' : ''}> 사용 기록 보내기 (브리프·문서 원문은 보내지 않음)</label>
    <fieldset class="settings-group"><legend>정부 데이터 키</legend>
      <p class="muted small-text">대지 조회(브이월드·공공데이터포털)와 법령 검색(법제처)에 씁니다. 넣은 값은 이 PC의 .env에만 저장됩니다.</p>
      ${dataKeys}
    </fieldset>
    <p class="error-text" role="alert">${escape(ui.settingsError)}</p>
    <div class="form-actions"><button type="button" class="primary" data-settings="save">저장</button></div>`;
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
  if (d.worker_chatgpt_model && d.worker_chatgpt_model !== s.chatgpt.worker_model) changes.worker_chatgpt_model = d.worker_chatgpt_model;
  if (d.rag_enabled !== s.rag_enabled) changes.rag_enabled = d.rag_enabled;
  if (d.state_update !== s.state_update) changes.state_update = d.state_update;
  if (d.telemetry_enabled !== s.telemetry_enabled) changes.telemetry_enabled = d.telemetry_enabled;
  try {
    if (d.openrouter_key.trim()) {
      await api('/api/settings/keys/openrouter', { method: 'PUT', body: { value: d.openrouter_key.trim() } });
    }
    for (const [key, value] of keyChanges(d.keys, s.keys)) {
      await api(`/api/settings/keys/${key}`, { method: 'PUT', body: { value } });
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
  if (!ui.settingsDraft) return;
  if (event.target.dataset.field === 'openrouter_key') ui.settingsDraft.openrouter_key = event.target.value;
  if (event.target.dataset.key) ui.settingsDraft.keys[event.target.dataset.key] = event.target.value;
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
    ui.settingsDraft = { ...draftFromSettings(ui.settings), ...draft, chatgpt_model: ui.settings.chatgpt.model, worker_chatgpt_model: ui.settings.chatgpt.worker_model };
    ui.chatgptModels = null;
    renderSettings();
  }
});

deleteConfirm.addEventListener('click', deleteProject);

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
window.addEventListener('resize', () => { syncPanelWidths(); placeTable(); });
matchMedia('(max-width: 900px)').addEventListener('change', () => {
  if (currentRoute.page === 'project') render(false);
});
document.querySelector('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  document.querySelector('#main')?.focus();
});

navigate();
loadSettings().then(() => {
  if (ui.settings?.first_run) openSettings();
  else render(false);
});
