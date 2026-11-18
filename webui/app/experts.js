// Expert actions: run, revise, analysis chats, feedback, the project-state proposal.

import { sitePath, needsSiteFirst, deckFileUrl, downloadName, DECK_FORMATS } from './model.js';
import { siteDiagramLabel, siteDiagramQuery } from './board-model.js';
import { diagramFileName } from './rhino-model.js';
import { api, expertUrl, projectApi } from './api.js';
import { fetchBlob, saveBlob, svgToPng, table, takePicked } from './board.js';
import { deckScheme, loadExpert, loadSession, refreshProject, start } from './jobs.js';
import { render } from './render.js';
import { activeChat, currentRoute, draftFor, drafts, jobRunning, siteDiagramChoice, toast, ui } from './state.js';

// Another massing scheme for the deck (the 매스안 choice on the 발표자료 tab): the deck is read again.
export async function pickDeckScheme(id) {
  const { name, agent } = currentRoute;
  ui.deckScheme = { project: name, id };
  await loadExpert(name, agent);
  render(false);
}

// The deck as a file (the presentation editor's 발표자료 tab): made by the server when asked, then
// saved under the name the server gives it.
export async function downloadDeck(format) {
  const { name } = currentRoute;
  const word = DECK_FORMATS.find((f) => f.format === format)?.word || '파일';
  if (ui.deckMaking) return;
  ui.deckMaking = format;
  render(false);
  try {
    const response = await fetch(deckFileUrl(name, format, deckScheme(name)));
    if (!response.ok) {
      let detail = '';
      try { detail = (await response.json()).detail; } catch { /* not JSON */ }
      throw new Error(typeof detail === 'string' && detail ? detail : `요청이 실패했습니다 (${response.status})`);
    }
    const filename = downloadName(response.headers.get('Content-Disposition'), `발표자료.${format}`);
    saveBlob(await response.blob(), filename);
    toast(`${filename}을(를) 내려받았습니다.`, 'success');
  } catch (error) {
    const text = error instanceof TypeError ? 'Sida 서버에 연결할 수 없습니다.' : error.message;
    toast(`${word}을 만들지 못했습니다: ${text}`, 'error');
  }
  ui.deckMaking = '';
  render(false);
}

// A button on the representation planner's 대지 다이어그램 tab: a diagram's range or hour (shown at
// once, then kept for the project, so the table's panel draws it the same), its picture as a file,
// or every ready diagram in one zip (GET .../site/diagrams/export).
export async function siteDiagramAction(action, kind, value) {
  const { name, agent } = currentRoute;
  const base = `${projectApi(name)}/site/diagrams`;
  const fail = (what, error) => toast(`${what} ${error instanceof TypeError ? 'Sida 서버에 연결할 수 없습니다.' : error.message}`, 'error');
  if (action === 'reload') { await loadExpert(name, agent); render(false); return; }
  if (action === 'export-all') {
    if (ui.siteDiagramsBusy) return;
    ui.siteDiagramsBusy = 'export-all';
    render(false);
    try {
      const response = await fetch(`${base}/export`);
      if (!response.ok) {
        let detail = '';
        try { detail = (await response.json()).detail; } catch { /* not JSON */ }
        throw new Error(typeof detail === 'string' && detail ? detail : `요청이 실패했습니다 (${response.status})`);
      }
      const filename = downloadName(response.headers.get('Content-Disposition'), '대지분석_다이어그램.zip');
      saveBlob(await response.blob(), filename);
      toast(`${filename}을(를) 내려받았습니다.`, 'success');
    } catch (error) {
      fail('다이어그램을 묶지 못했습니다.', error);
    }
    ui.siteDiagramsBusy = '';
    render(false);
    return;
  }
  const d = ui.siteDiagrams?.diagrams?.find((x) => x.kind === kind);
  if (!d) return;
  const choice = siteDiagramChoice(kind);
  if (action === 'range' || action === 'hour') {
    const next = action === 'range' ? { ...choice, range: value } : { ...choice, hour: value === 'all' ? null : Number(value) };
    Object.assign(d, next);
    render(false);
    try {
      Object.assign(d, await api(`${base}/${encodeURIComponent(kind)}`, { method: 'PUT', body: next }));
      table?.forgetDiagrams?.(); // the table's panel shows the kept choice too
    } catch (error) {
      fail('고른 범위를 저장하지 못했습니다.', error);
    }
    return;
  }
  if (action !== 'svg' && action !== 'png') return;
  const label = siteDiagramLabel(d, choice);
  try {
    const svg = await fetchBlob(`${base}/${encodeURIComponent(kind)}?${siteDiagramQuery(kind, choice)}`);
    const filename = diagramFileName('', label, action);
    saveBlob(action === 'png' ? await svgToPng(svg) : svg, filename);
    toast(`${filename}을(를) 내려받았습니다.`, 'success');
  } catch (error) {
    fail(`${d.title}을(를) 만들지 못했습니다.`, error);
  }
}

export async function decideProposal(id, apply) {
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

export function send(key) {
  const { name, agent } = currentRoute;
  const text = draftFor(key).trim();
  if (!text || jobRunning()) return;
  drafts.delete(key);
  const { ids, context } = takePicked();
  const chat = activeChat();
  start(name, `${projectApi(name)}/experts/${encodeURIComponent(agent)}/chats/${encodeURIComponent(chat)}/messages`, { text, context: ids }, { target: `${agent}/${chat}`, text, context });
}

export async function sendFeedback(rating) {
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

export async function newChat(agent) {
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

// Running the site reader with no site saved opens the site page to find it first; saving the site
// then runs it (or the designer runs it on the brief alone).
export function runExpert(name, agent, withoutSite = false) {
  if (!withoutSite && needsSiteFirst(agent, ui.site)) {
    ui.siteFirst = true;
    location.hash = sitePath(name, 'find');
    return;
  }
  ui.siteFirst = false;
  start(name, `${projectApi(name)}/session/experts/${encodeURIComponent(agent)}/run`, { context: takePicked().ids });
}
