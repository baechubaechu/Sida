// The drafting table on the screen (table.js), the VWorld 3D view and the model board panel: made
// when a project opens, fed from the board API, and laid over the redrawn page.

import { expertPath, parseRecommendation, boardExport } from './model.js';
import { keepSelected, pickedNames, addQuestion, readModelSummary, rangeQuery } from './board-model.js';
import { VWorldView } from './vworld-view.js';
import { api, expertUrl, projectApi } from './api.js';
import { say } from './commands.js';
import { carryPapers, stowPapers } from './ideas.js';
import { followSelection } from './dock.js';
import { render } from './render.js';
import { app, currentProjectLabel, currentRoute, draftFor, drafts, tableHost, toast, ui } from './state.js';

let vworldView = null; // the board's masses on VWorld's 3D map, over the board area (vworld-view.js)
const vworldAuto = new Set(); // projects whose site buildings were looked for this session
export let table = null; // the drafting table of the open project (table.js, loaded on first use)
let tableFor = '';
let modelMaker = null; // the model board panel on the model maker's page: {name, host, maker} (model-maker.js)
let modelMakerLoading = false;

// ------------------------------------------------------------------ the drafting table

export async function loadBoard(name) {
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
export async function boardCall(name, call, reload = false) {
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

// The model board (모형 판, model-maker.js): the project's 3D range and surroundings, the kept
// settings, fitting the board to the range, its plan and its laser files.
function modelHooks(name) {
  const base = `${projectApi(name)}/site`;
  return {
    around: () => api(`${base}/context`),
    site: () => table?.site || ui.board?.site || null,
    range: () => api(`${base}/context/range`),
    settings: () => api(`${base}/model-base/settings`),
    fit: (p) => api(`${base}/model-base/fit?${new URLSearchParams(Object.entries(p).filter(([, v]) => v != null && v !== ''))}`),
    plan: (body) => api(`${base}/model-base/plan`, { method: 'POST', body }),
    files: (body) => downloadModelBoard(name, body),
  };
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
    // range {size, shape, orient}: as asked; none: the project's saved range.
    context: (range) => api(`${projectApi(name)}/site/context${range ? `?${rangeQuery(range)}` : ''}`),
    range: () => api(`${projectApi(name)}/site/context/range`),
    saveRange: (range) => api(`${projectApi(name)}/site/context/range`, { method: 'PUT', body: range }),
    // The model base: the stepped ground (GET .../site/model-base) and its laser files (a zip).
    modelBase: (interval, range) => api(`${projectApi(name)}/site/model-base?interval=${encodeURIComponent(interval)}${range ? `&${rangeQuery(range)}` : ''}`),
    modelSettings: () => modelHooks(name).settings(),
    place: (id, placement) => boardCall(name, () => api(`${projectApi(name)}/board/tray/${encodeURIComponent(id)}/place`, { method: 'POST', body: placement }), true),
    discard: (id) => boardCall(name, () => api(`${projectApi(name)}/board/tray/${encodeURIComponent(id)}`, { method: 'DELETE' }), true),
    // Selecting turns 레이어 to 속성 where they share a group; clearing goes back to 레이어.
    select: (ids) => {
      ui.selected = ids;
      followSelection(ids.length > 0);
      render(false);
    },
    // A paper carried toward the idea board, and papers dropped into it.
    carry: (at) => carryPapers(at),
    stow: (ids) => stowPapers(name, ids),
    ask: () => askAbout(),
    openExpert: (agent, tab) => { location.hash = tab ? expertPath(name, agent, tab) : expertUrl(name, agent); },
    experts: () => ui.session?.experts || [],
  };
}

// The table of this project, made once (three.js is loaded only when a project opens).
export async function openTable(name) {
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


export function placeTable() {
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
export async function toggleVWorld(name, on = !ui.vworld) {
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
  if (!ui.mapLayers.webgl3d) {
    toast(ui.mapLayers.relay
      ? '브이월드 3D 지도가 아직 Sida 자료 서버에 준비되지 않았습니다. 이 PC에 브이월드 키를 넣으면 바로 열 수 있습니다.'
      : '브이월드 3D 지도를 열 수 없습니다. 설정에서 브이월드 키나 Sida 자료 서버 키를 확인하세요.', 'info');
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
  await vworldView.show({ webgl3d: ui.mapLayers.webgl3d, plan, paper, hidden, firstTime });
}

// Ask about what is picked: the cursor goes to the command line, and a prepared question goes
// under what is already typed. Nothing is sent yet; Enter opens a talk with the picked papers.
export function askAbout(question = '') {
  if (currentRoute.page !== 'project') return;
  if (question) drafts.set('command', addQuestion(draftFor('command'), question));
  ui.focusComposer = true;
  render(false);
}

export function unpick(id) {
  ui.selected = ui.selected.filter((x) => x !== id);
  table?.setSelected(ui.selected);
  render(false);
}

// The picked papers go with this request and are let go once it is sent.
export function takePicked() {
  const ids = ui.selected;
  const context = pickedNames(ids, ui.board);
  ui.selected = [];
  table?.setSelected([]);
  return { ids, context };
}

// The drawing table as a DXF or 3dm file, with the scheme the table shows switched on.
export async function downloadBoard(name, format) {
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

// The laser files for a site model: the zip goes to the designer's downloads; the server's summary
// (X-Model-Base) comes back for the table to show. A 400 (too big, no terrain) comes as its message.
async function downloadModelBoard(name, body) {
  let response;
  try {
    response = await fetch(`${projectApi(name)}/site/model-base/files`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch {
    throw new Error('Sida 서버에 연결할 수 없습니다.');
  }
  if (!response.ok) {
    let detail = '';
    try { detail = (await response.json()).detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `요청이 실패했습니다 (${response.status})`);
  }
  const summary = readModelSummary(response.headers.get('X-Model-Base'));
  const link = document.createElement('a');
  link.href = URL.createObjectURL(await response.blob());
  link.download = `${currentProjectLabel(name)}_모형판_1-${body.scale}_${body.thickness_mm}mm.zip`;
  link.hidden = true;
  document.body.append(link);
  link.click();
  setTimeout(() => { link.remove(); URL.revokeObjectURL(link.href); }, 10000);
  return summary;
}

// The model board panel kept across redraws (one per project) and put into its slot.
export function placeModelMaker() {
  const slot = app.querySelector('#model-maker-slot');
  const name = currentRoute.name;
  if (!slot || !name) return;
  if (modelMaker?.name !== name) { openModelMaker(name); return; }
  slot.replaceChildren(modelMaker.host);
}

async function openModelMaker(name) {
  if (modelMakerLoading) return;
  modelMakerLoading = true;
  try {
    const { ModelMaker } = await import('./model-maker.js');
    const host = document.createElement('div');
    modelMaker = { name, host, maker: new ModelMaker(host, modelHooks(name)) };
    modelMaker.maker.open();
  } catch (error) {
    toast(`모형 판을 열지 못했습니다. ${error.message}`, 'error');
  }
  modelMakerLoading = false;
  render(false);
}

// Leaving the project: the table goes, so three.js stops drawing.
export function closeTable() {
  table?.destroy();
  table = null;
  tableFor = '';
}

export function hideVWorld() { vworldView?.hide(); }

// The 모형 tab's "추천대로 놓기": the board as the latest result recommends.
export function applyModelRecommendation() { modelMaker?.maker.apply(parseRecommendation(ui.module?.content)); }
