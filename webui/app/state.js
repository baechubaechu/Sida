// What the screen remembers while it is open (`ui`, drafts, the route) and the fixed elements of
// index.html. Nothing here is project data: that lives on this PC's server and is read again.

import { latestChat, parseRoute } from './model.js';
import { floatState } from './board-model.js';
import { DEFAULT_PANEL_RATIOS, defaultDock } from './dock-model.js';

export const app = document.querySelector('#app');

const announcer = document.querySelector('#announcer');
const toasts = document.querySelector('#toasts');
export const settingsDialog = document.querySelector('#settings-dialog');
export const settingsBody = document.querySelector('#settings-body');
export const settingsFooter = document.querySelector('#settings-footer');
export const newProjectDialog = document.querySelector('#new-project-dialog');
export const settingsForm = document.querySelector('#settings-form');
export const tableHost = document.querySelector('#table-host');
export const deleteDialog = document.querySelector('#delete-dialog');
export const deleteError = document.querySelector('#delete-error');
export const deleteConfirm = document.querySelector('#delete-confirm');
export const projectInfoDialog = document.querySelector('#project-info-dialog');
export const projectInfoBody = document.querySelector('#project-info-body');
export const deleteTalkDialog = document.querySelector('#delete-talk-dialog');
export const deleteTalkConfirm = document.querySelector('#delete-talk-confirm');

export const POLL_MS = 1000;
export const MAIN_JOBS = new Set(['opening', 'message', 'expert']);
export const SITE_EXPERTS = new Set(['site_reader', 'regulation_checker']); // they read the saved site facts
export const REGION_LEVELS = ['sido', 'sigungu', 'emd', 'ri'];
export const REGION_LABELS = { sido: '시·도', sigungu: '시·군·구', emd: '읍·면·동', ri: '리' };

export const ui = {
  // Asking the Sida relay for a key from settings (GET/POST /api/settings/relay-key): the last
  // answer, the form, and whether a "새로 요청" form was opened although a key is saved.
  relayKey: null, relayKeyDraft: { name: '', contact: '' }, relayKeyOpen: false, relayKeyBusy: false,
  projects: null, projectsError: '', query: '',
  // The list's sort and dragged order (folder names), kept on this PC by the server (GET/PUT /api/projects…).
  sort: 'recent', customOrder: [], listKept: false,
  // Saved site of each listed project, for the cards: name → { stamp: updated_at, card: siteCard() }.
  projectSites: new Map(),
  project: '', session: null, sessionError: '',
  chat: null, chatMissing: false, module: null, moduleMissing: false, openExperts: new Set(),
  versions: null, version: null, versionMissing: false, showRaw: false, checks: new Set(), feedback: {},
  job: null, live: [], pending: null,
  revisionOpen: false, creating: false, newDraft: {}, vworld: false,
  // The workspace: the drafting table, and on either side the docked panels (dock-model.js; kept
  // on this PC by the server); the site page or an expert's page takes the right side's place.
  // `narrowSide`: the tab shown beside 대화 on a narrow screen. `conductor.open` is not used for
  // showing the panel any more (the layout says where 대화 is and whether its side is folded).
  dock: defaultDock(), narrowSide: 'layers', conductor: { open: true, active: null, list: false },
  // The idea board floats over the drafting table in a corner (2026-11-07 지훈); it was a tab
  // beside the experts before. Where it sits is kept for this visit only (no browser storage).
  // `ideaNew`: ideas just put in (they pop in once).
  ideaNew: new Set(), ideaFloat: floatState(null), ideaEdit: '', ideaConfirm: '', ideaBusy: false, ideaDrag: '', ideaLinkNew: true,
  pane: 'board', focusComposer: false, creatingTalk: false, talkMenu: '',
  panelRatios: { ...DEFAULT_PANEL_RATIOS }, // the sides' widths as shares (dragged, kept with the layout)
  // The 레이어 panel (layers.js): the row picked for its tools, the layer being renamed (and what is
  // typed), the current layer new papers go onto ('' = their kind's), and the surroundings hidden.
  // `layersSaving`: layer saves still on their way.
  // `layerFolded`: layers whose sublayers are folded away in the panel (this visit).
  layerPick: '', layerRename: '', layerRenameText: '', currentLayer: '', aroundHidden: false, layersSaving: 0, layerFolded: new Set(),
  settings: null, settingsDraft: null, settingsError: '', settingsAdvancedOpen: false, chatgptModels: null, chatgptNote: '',
  // The papers selected on the table, the buildings picked on their own (paperId#index), and a
  // value the 속성 panel refused ({key, text}).
  board: null, selected: [], picked: [], propError: null, 
  site: null, siteError: '', showSiteLines: false, find: null, siteFirst: false,
  ordinance: null, ordinanceError: '', ordinanceBusy: '', useFind: null, mapLayers: null, mapError: '', mapErrorStatus: 0,
  // Loaded conversations and their next-question contexts; closing the panel keeps both.
  talks: new Map(), talkViews: [],
  // The command line: history lines, typed lines for ↑↓, a command's open question, the last
  // command (an empty Enter repeats it), the highlighted suggestion and the help card.
  cmd: { lines: [], typed: [], back: -1, prompt: null, last: '', pick: 0, help: false },
};
export const drafts = new Map();
export const conductorScrolls = new Map();
export const openingTried = new Set();
export let currentRoute = { page: 'home' };
export function setCurrentRoute(next) { currentRoute = next; }
// A redraw asked for while a pointer is held (a panel, the idea window or a circle being dragged)
// waits until release; the drag's finish redraws then.
// `growing`: a project's card is growing into its work screen or shrinking back (app.js); a
// redraw then would end that animation, so it waits like one during a drag.
export const deferred = { render: false, growing: false };

// ------------------------------------------------------------------ helpers

export const announce = (text) => { announcer.textContent = text; };

export function toast(text, tone = 'info') {
  const item = document.createElement('div');
  item.className = `toast ${tone}`;
  item.textContent = text;
  item.addEventListener('click', () => item.remove());
  toasts.append(item);
  while (toasts.children.length > 4) toasts.firstElementChild.remove();
  setTimeout(() => item.remove(), tone === 'error' ? 9000 : 5000);
}

export function draftFor(key) {
  if (!drafts.has(key)) drafts.set(key, '');
  return drafts.get(key);
}

export function expertById(agent) {
  return ui.session?.experts.find((e) => e.id === agent) || null;
}

// The expert chat on screen: the one in the address, or the expert's newest chat.
export function activeChat() {
  return currentRoute.chat || latestChat(expertById(currentRoute.agent));
}

export function jobRunning() {
  return Boolean(ui.job && ui.job.status === 'running');
}

export function route() {
  return parseRoute(location.hash);
}

// The site page's "find" tab: step-by-step region lists, a typed 지번 or address, the parcels found
// and the ones picked to look up. Nothing here is saved until the designer saves the site.
export function freshFind() {
  return {
    mode: 'steps', lists: { sido: null, sigungu: null, emd: null, ri: null }, loading: '',
    chosen: { sido: null, sigungu: null, emd: null, ri: null }, main: '', sub: '', mountain: false,
    query: '', briefTried: false, search: null, candidates: null, picked: [], busy: '', error: '', errorStatus: 0,
    shapes: new Map(), mapBusy: false, // pnu → boundary (null once asked and none came)
  };
}

export function freshUseFind() {
  return { query: '', candidates: null, busy: '', error: '', errorStatus: 0 };
}

export const projectLabel = (p) => p.display_name || p.name;
export const currentProjectLabel = (name) => projectLabel(ui.projects?.find(p => p.name === name) || { name });

// The table is always in the workspace of a project, next to what is open on the right.
export function tableShown() {
  return currentRoute.page === 'project';
}

export function settingsWarned() {
  return Boolean(ui.settings && Object.values(ui.settings.warnings || {}).some(Boolean));
}

export function talkViewById(id) {
  return ui.talkViews.find((p) => p.id === id);
}

// The idea board is open while the pointer is over it, while an idea is being rewritten or typed
// into, or when the designer pinned it open; otherwise it is a row of circles.
export function ideaBoardOpen() {
  return Boolean(ui.ideaFloat.pinned || ui.ideaHover || ui.ideaEdit);
}
